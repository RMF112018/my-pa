"""WebAuthn/passkey ceremony over WP02 persistence.

Verification is delegated to the `webauthn` library. This module owns challenge
purpose isolation, Principal binding, recovery, step-up grants, and session
handoff. It does not mint the production HMAC cookie.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import Connection, select, update
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.auth_grants import AuthGrantPurpose
from my_pa.domain.identity.auth_sessions import AuthSession, IssuedAuthSession
from my_pa.domain.identity.auth_state import AuthStateKind
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID, durable_principal_uuid
from my_pa.domain.identity.secret_digests import AuthSecretError, digest_bytes
from my_pa.domain.identity.webauthn_credentials import (
    WebAuthnChallenge,
    WebAuthnChallengePurpose,
    WebAuthnCredential,
)
from my_pa.domain.identity.webauthn_relying_party import (
    WebAuthnCeremonyError,
    WebAuthnRelyingParty,
)
from my_pa.infrastructure.persistence.auth_grants import auth_grants
from my_pa.infrastructure.persistence.auth_state import AuthStateValidator
from my_pa.infrastructure.persistence.user_accounts import UserAccountRepository
from my_pa.infrastructure.persistence.webauthn_auth import (
    WebAuthnAuthPersistence,
    webauthn_challenges,
)

__all__ = [
    "ADMIN_GRANT_TTL",
    "CeremonyResult",
    "WebAuthnCeremonyService",
]

ADMIN_GRANT_TTL: Final = timedelta(minutes=5)
_LAST_CREDENTIAL_BLOCK: Final = "last_passkey_requires_recovery"
_LOG: Final = logging.getLogger(__name__)
_Admit = Literal["bootstrap", "operator_recovery", "ordinary"]


@dataclass(frozen=True, slots=True)
class _VerifiedRegistration:
    credential_id: bytes
    public_key: bytes
    sign_count: int


@dataclass(frozen=True, slots=True)
class CeremonyResult:
    """JSON-safe ceremony outcome. Secrets only appear when issued once."""

    payload: Mapping[str, Any]
    issued_session: IssuedAuthSession | None = None
    recovery_codes: tuple[str, ...] | None = None


class WebAuthnCeremonyService:
    """One-connection ceremony. Principal is an argument, never a request field."""

    def __init__(
        self,
        connection: Connection,
        relying_party: WebAuthnRelyingParty,
        *,
        clock: Callable[[], datetime],
        verify_registration: Callable[..., Any] = verify_registration_response,
        verify_authentication: Callable[..., Any] = verify_authentication_response,
        require_local_operator: bool = False,
    ) -> None:
        self._connection = connection
        self._stores = WebAuthnAuthPersistence(connection)
        self._accounts = UserAccountRepository(connection)
        self._rp = relying_party
        self._clock = clock
        self._verify_registration = verify_registration
        self._verify_authentication = verify_authentication
        self._require_local_operator = require_local_operator

    def auth_state(self) -> CeremonyResult:
        state = AuthStateValidator(self._connection).inspect(now=self._clock())
        return CeremonyResult(payload={"state": state.kind.value})

    def bootstrap_registration_options(self, *, origin: str, grant: str) -> CeremonyResult:
        self._require_origin(origin)
        self._admit("bootstrap")
        now = self._clock()
        self._accounts.resolve_or_create_local(now=now)
        exchanged = self._stores.grants.exchange(grant, AuthGrantPurpose.BOOTSTRAP, now=now)
        if exchanged is None:
            _log_grant_failure("bootstrap_grant_invalid", None)
            raise WebAuthnCeremonyError("bootstrap_grant_invalid")
        issued = self._stores.challenges.issue(
            purpose=WebAuthnChallengePurpose.BOOTSTRAP_REGISTRATION,
            rp_id=self._rp.rp_id,
            origin=origin,
            now=now,
            principal_id=LOCAL_OPERATOR_UUID,
            auth_grant_id=exchanged.id,
        )
        options = generate_registration_options(
            rp_id=self._rp.rp_id,
            rp_name=self._rp.rp_name,
            user_name=str(LOCAL_OPERATOR_UUID),
            user_id=LOCAL_OPERATOR_UUID.bytes,
            user_display_name="my-pa",
            challenge=issued.challenge_bytes,
            attestation=AttestationConveyancePreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[],
        )
        return CeremonyResult(payload=_options_payload(options_to_json(options)))

    def bootstrap_registration_complete(
        self,
        *,
        origin: str,
        credential: Mapping[str, Any],
        label: str | None = None,
    ) -> CeremonyResult:
        self._require_origin(origin)
        self._admit("bootstrap")
        now = self._clock()
        challenge, grant_id = self._lock_grant_bound_challenge(
            credential,
            purpose=WebAuthnChallengePurpose.BOOTSTRAP_REGISTRATION,
            grant_purpose=AuthGrantPurpose.BOOTSTRAP,
            origin=origin,
            invalid_grant_code="bootstrap_grant_invalid",
        )
        verified = self._verified_registration(
            credential,
            challenge=challenge,
            origin=origin,
            grant_purpose=AuthGrantPurpose.BOOTSTRAP,
        )
        account = self._accounts.resolve_or_create_local(now=now)
        record = self._create_credential(
            principal_id=account.principal_id,
            verified=verified,
            label=label,
        )
        recovery = self._stores.recovery.create_set(principal_id=account.principal_id, now=now)
        session = self._stores.sessions.create(principal_id=account.principal_id, now=now)
        self._finish_grant_bound_registration(
            challenge,
            grant_id=grant_id,
            grant_purpose=AuthGrantPurpose.BOOTSTRAP,
            origin=origin,
        )
        return CeremonyResult(
            payload={
                "registered": True,
                "credentialId": bytes_to_base64url(record.credential_id),
            },
            issued_session=session,
            recovery_codes=recovery.codes,
        )

    def operator_recovery_registration_options(self, *, origin: str, grant: str) -> CeremonyResult:
        self._require_origin(origin)
        self._admit("operator_recovery")
        now = self._clock()
        exchanged = self._stores.grants.exchange(grant, AuthGrantPurpose.OPERATOR_RECOVERY, now=now)
        if exchanged is None:
            _log_grant_failure("operator_recovery_grant_invalid", None)
            raise WebAuthnCeremonyError("operator_recovery_grant_invalid")
        existing = self._stores.credentials.list_for_principal(LOCAL_OPERATOR_UUID)
        issued = self._stores.challenges.issue(
            purpose=WebAuthnChallengePurpose.OPERATOR_RECOVERY_REGISTRATION,
            rp_id=self._rp.rp_id,
            origin=origin,
            now=now,
            principal_id=LOCAL_OPERATOR_UUID,
            auth_grant_id=exchanged.id,
        )
        options = generate_registration_options(
            rp_id=self._rp.rp_id,
            rp_name=self._rp.rp_name,
            user_name=str(LOCAL_OPERATOR_UUID),
            user_id=LOCAL_OPERATOR_UUID.bytes,
            user_display_name="my-pa",
            challenge=issued.challenge_bytes,
            attestation=AttestationConveyancePreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=_descriptors(existing),
        )
        return CeremonyResult(payload=_options_payload(options_to_json(options)))

    def operator_recovery_registration_complete(
        self,
        *,
        origin: str,
        credential: Mapping[str, Any],
        label: str | None = None,
    ) -> CeremonyResult:
        self._require_origin(origin)
        self._admit("operator_recovery")
        now = self._clock()
        challenge, grant_id = self._lock_grant_bound_challenge(
            credential,
            purpose=WebAuthnChallengePurpose.OPERATOR_RECOVERY_REGISTRATION,
            grant_purpose=AuthGrantPurpose.OPERATOR_RECOVERY,
            origin=origin,
            invalid_grant_code="operator_recovery_grant_invalid",
        )
        verified = self._verified_registration(
            credential,
            challenge=challenge,
            origin=origin,
            grant_purpose=AuthGrantPurpose.OPERATOR_RECOVERY,
        )
        record = self._create_credential(
            principal_id=LOCAL_OPERATOR_UUID,
            verified=verified,
            label=label,
        )
        self._stores.sessions.revoke_all_for_principal(
            LOCAL_OPERATOR_UUID, now=now, reason="operator_recovery"
        )
        recovery = self._stores.recovery.create_set(principal_id=LOCAL_OPERATOR_UUID, now=now)
        for prior in self._stores.recovery.active_sets_for(LOCAL_OPERATOR_UUID):
            if prior.id != recovery.record.id:
                self._stores.recovery.revoke_set(prior.id, now=now)
        session = self._stores.sessions.create(principal_id=LOCAL_OPERATOR_UUID, now=now)
        self._finish_grant_bound_registration(
            challenge,
            grant_id=grant_id,
            grant_purpose=AuthGrantPurpose.OPERATOR_RECOVERY,
            origin=origin,
        )
        return CeremonyResult(
            payload={
                "registered": True,
                "credentialId": bytes_to_base64url(record.credential_id),
            },
            issued_session=session,
            recovery_codes=recovery.codes,
        )

    def registration_options(
        self,
        principal_id: UUID,
        *,
        origin: str,
        grant: str,
        authorizing_sid: str | None,
    ) -> CeremonyResult:
        self._require_origin(origin)
        self._admit("ordinary")
        now = self._clock()
        session = self._resolve_authorizing_session(principal_id, authorizing_sid)
        consumed = self._stores.grants.consume(
            grant,
            AuthGrantPurpose.CREDENTIAL_ADMINISTRATION,
            now=now,
            authorizing_session_id=session.id,
        )
        if consumed is None:
            _log_grant_failure("step_up_required", None)
            raise WebAuthnCeremonyError("step_up_required")
        existing = self._stores.credentials.list_for_principal(principal_id)
        issued = self._stores.challenges.issue(
            purpose=WebAuthnChallengePurpose.CREDENTIAL_REGISTRATION,
            rp_id=self._rp.rp_id,
            origin=origin,
            now=now,
            principal_id=principal_id,
            auth_grant_id=consumed.id,
        )
        options = generate_registration_options(
            rp_id=self._rp.rp_id,
            rp_name=self._rp.rp_name,
            user_name=str(principal_id),
            user_id=principal_id.bytes,
            user_display_name="my-pa",
            challenge=issued.challenge_bytes,
            attestation=AttestationConveyancePreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=_descriptors(existing),
        )
        return CeremonyResult(payload=_options_payload(options_to_json(options)))

    def registration_complete(
        self,
        principal_id: UUID,
        *,
        origin: str,
        credential: Mapping[str, Any],
        label: str | None = None,
    ) -> CeremonyResult:
        self._require_origin(origin)
        self._admit("ordinary")
        challenge = self._consume_challenge(
            _client_challenge(credential),
            purpose=WebAuthnChallengePurpose.CREDENTIAL_REGISTRATION,
            principal_id=principal_id,
            origin=origin,
        )
        try:
            verified = self._verify_registration(
                credential=dict(credential),
                expected_challenge=challenge.challenge_bytes,
                expected_rp_id=self._rp.rp_id,
                expected_origin=origin,
                require_user_verification=True,
            )
        except Exception as error:
            raise WebAuthnCeremonyError("invalid_registration") from error
        if not getattr(verified, "user_verified", True):
            raise WebAuthnCeremonyError("user_verification_missing")
        record = self._create_credential(
            principal_id=principal_id,
            verified=_VerifiedRegistration(
                credential_id=bytes(verified.credential_id),
                public_key=bytes(verified.credential_public_key),
                sign_count=int(verified.sign_count),
            ),
            label=label,
        )
        return CeremonyResult(
            payload={
                "registered": True,
                "credentialId": bytes_to_base64url(record.credential_id),
            }
        )

    def authentication_options(
        self, *, origin: str, principal_id: UUID | None = None
    ) -> CeremonyResult:
        self._require_origin(origin)
        self._admit("ordinary")
        allow: tuple[WebAuthnCredential, ...] = ()
        if principal_id is not None:
            allow = self._stores.credentials.list_for_principal(principal_id)
        issued = self._stores.challenges.issue(
            purpose=WebAuthnChallengePurpose.AUTHENTICATION,
            rp_id=self._rp.rp_id,
            origin=origin,
            now=self._clock(),
            principal_id=principal_id,
        )
        options = generate_authentication_options(
            rp_id=self._rp.rp_id,
            challenge=issued.challenge_bytes,
            allow_credentials=_descriptors(allow) if allow else None,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        return CeremonyResult(payload=_options_payload(options_to_json(options)))

    def authentication_complete(
        self, *, origin: str, credential: Mapping[str, Any]
    ) -> CeremonyResult:
        self._admit("ordinary")
        return self._assert(
            origin=origin,
            credential=credential,
            purpose=WebAuthnChallengePurpose.AUTHENTICATION,
            create_session=True,
        )

    def step_up_options(self, principal_id: UUID, *, origin: str) -> CeremonyResult:
        self._require_origin(origin)
        self._admit("ordinary")
        existing = self._stores.credentials.list_for_principal(principal_id)
        if not existing:
            raise WebAuthnCeremonyError("unknown_credential")
        issued = self._stores.challenges.issue(
            purpose=WebAuthnChallengePurpose.STEP_UP,
            rp_id=self._rp.rp_id,
            origin=origin,
            now=self._clock(),
            principal_id=principal_id,
        )
        options = generate_authentication_options(
            rp_id=self._rp.rp_id,
            challenge=issued.challenge_bytes,
            allow_credentials=_descriptors(existing),
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        return CeremonyResult(payload=_options_payload(options_to_json(options)))

    def step_up_complete(
        self,
        principal_id: UUID,
        *,
        origin: str,
        credential: Mapping[str, Any],
        authorizing_sid: str | None,
    ) -> CeremonyResult:
        self._admit("ordinary")
        result = self._assert(
            origin=origin,
            credential=credential,
            purpose=WebAuthnChallengePurpose.STEP_UP,
            expected_principal=principal_id,
            create_session=False,
        )
        session = self._resolve_authorizing_session(principal_id, authorizing_sid)
        now = self._clock()
        self._stores.grants.revoke_active(
            AuthGrantPurpose.CREDENTIAL_ADMINISTRATION,
            now=now,
            reason="replaced",
        )
        issued = self._stores.grants.issue(
            AuthGrantPurpose.CREDENTIAL_ADMINISTRATION,
            now=now,
            ttl=ADMIN_GRANT_TTL,
            authorizing_session_id=session.id,
        )
        return CeremonyResult(
            payload={
                **result.payload,
                "administrationGrant": issued.raw_grant,
            }
        )

    def list_credentials(self, principal_id: UUID) -> CeremonyResult:
        self._admit("ordinary")
        records = self._stores.credentials.list_for_principal(principal_id)
        return CeremonyResult(
            payload={
                "credentials": [
                    {
                        "credentialId": bytes_to_base64url(item.credential_id),
                        "label": item.label,
                        "createdAt": item.created_at.isoformat(),
                        "lastUsedAt": None
                        if item.last_used_at is None
                        else item.last_used_at.isoformat(),
                    }
                    for item in records
                ]
            }
        )

    def revoke_credential(
        self,
        principal_id: UUID,
        *,
        origin: str,
        credential_id: bytes,
        administration_grant: str,
        authorizing_sid: str | None,
    ) -> CeremonyResult:
        self._consume_admin_grant(
            principal_id,
            origin=origin,
            grant=administration_grant,
            authorizing_sid=authorizing_sid,
        )
        remaining = self._stores.credentials.list_for_principal(principal_id)
        target = next((item for item in remaining if item.credential_id == credential_id), None)
        if target is None:
            raise WebAuthnCeremonyError("unknown_credential")
        if len(remaining) == 1 and not self._has_active_recovery(principal_id):
            raise WebAuthnCeremonyError(_LAST_CREDENTIAL_BLOCK)
        revoked = self._stores.credentials.revoke(credential_id, now=self._clock())
        if revoked is None or revoked.principal_id != principal_id:
            raise WebAuthnCeremonyError("unknown_credential")
        return CeremonyResult(payload={"revoked": True})

    def issue_recovery(
        self,
        principal_id: UUID,
        *,
        origin: str,
        administration_grant: str,
        authorizing_sid: str | None,
    ) -> CeremonyResult:
        self._consume_admin_grant(
            principal_id,
            origin=origin,
            grant=administration_grant,
            authorizing_sid=authorizing_sid,
        )
        now = self._clock()
        current = self._stores.recovery.create_set(principal_id=principal_id, now=now)
        for prior in self._stores.recovery.active_sets_for(principal_id):
            if prior.id != current.record.id:
                self._stores.recovery.revoke_set(prior.id, now=now)
        return CeremonyResult(
            payload={"generation": current.record.generation, "remaining": len(current.codes)},
            recovery_codes=current.codes,
        )

    def consume_recovery(self, presented: str, *, origin: str) -> CeremonyResult:
        self._require_origin(origin)
        self._admit("ordinary")
        consumed = self._stores.recovery.consume_code(presented, now=self._clock())
        if consumed is None:
            raise WebAuthnCeremonyError("invalid_recovery_code")
        principal_id = self._stores.recovery.principal_for_set(consumed.set_id)
        if principal_id is None:
            raise WebAuthnCeremonyError("invalid_recovery_code")
        if self._require_local_operator and principal_id != LOCAL_OPERATOR_UUID:
            raise WebAuthnCeremonyError("principal_mismatch")
        session = self._stores.sessions.create(principal_id=principal_id, now=self._clock())
        account = self._accounts.get(principal_id)
        return CeremonyResult(
            payload={
                "recovered": True,
                "principalId": str(principal_id),
                "tid": None if account is None else account.tid,
                "oid": None if account is None else account.oid,
            },
            issued_session=session,
        )

    def revoke_all_sessions(
        self,
        principal_id: UUID,
        *,
        origin: str,
        administration_grant: str,
        authorizing_sid: str | None,
    ) -> CeremonyResult:
        self._consume_admin_grant(
            principal_id,
            origin=origin,
            grant=administration_grant,
            authorizing_sid=authorizing_sid,
        )
        count = self._stores.sessions.revoke_all_for_principal(
            principal_id, now=self._clock(), reason="step_up_revoke_all"
        )
        return CeremonyResult(payload={"revoked": count})

    def _assert(
        self,
        *,
        origin: str,
        credential: Mapping[str, Any],
        purpose: WebAuthnChallengePurpose,
        expected_principal: UUID | None = None,
        create_session: bool,
    ) -> CeremonyResult:
        self._require_origin(origin)
        raw_id = _credential_id(credential)
        stored = self._stores.credentials.get_by_credential_id(raw_id)
        if stored is None:
            include_revoked = self._stores.credentials.get_by_credential_id(
                raw_id, include_revoked=True
            )
            if include_revoked is not None:
                raise WebAuthnCeremonyError("revoked_credential")
            raise WebAuthnCeremonyError("unknown_credential")
        if expected_principal is not None and stored.principal_id != expected_principal:
            raise WebAuthnCeremonyError("principal_mismatch")
        if (
            create_session
            and self._require_local_operator
            and stored.principal_id != LOCAL_OPERATOR_UUID
        ):
            raise WebAuthnCeremonyError("principal_mismatch")
        challenge = self._consume_challenge(
            _client_challenge(credential),
            purpose=purpose,
            principal_id=stored.principal_id
            if purpose is WebAuthnChallengePurpose.STEP_UP
            else (
                stored.principal_id
                if purpose is WebAuthnChallengePurpose.AUTHENTICATION
                else expected_principal
            ),
            origin=origin,
            allow_unbound=(
                purpose is WebAuthnChallengePurpose.AUTHENTICATION and expected_principal is None
            ),
            stored_principal=stored.principal_id,
        )
        try:
            verified = self._verify_authentication(
                credential=dict(credential),
                expected_challenge=challenge.challenge_bytes,
                expected_rp_id=self._rp.rp_id,
                expected_origin=origin,
                credential_public_key=stored.public_key,
                credential_current_sign_count=stored.sign_count,
                require_user_verification=True,
            )
        except Exception as error:
            raise WebAuthnCeremonyError("invalid_assertion") from error
        if not getattr(verified, "user_verified", True):
            raise WebAuthnCeremonyError("user_verification_missing")
        new_count = int(verified.new_sign_count)
        updated = self._stores.credentials.record_use(
            stored.credential_id, sign_count=new_count, now=self._clock()
        )
        if updated is None:
            raise WebAuthnCeremonyError("unknown_credential")
        account = self._accounts.get(stored.principal_id)
        payload: dict[str, Any] = {
            "authenticated": True,
            "principalId": str(stored.principal_id),
            "tid": None if account is None else account.tid,
            "oid": None if account is None else account.oid,
            "signCount": updated.sign_count,
        }
        session = None
        if create_session:
            session = self._stores.sessions.create(
                principal_id=stored.principal_id, now=self._clock()
            )
        return CeremonyResult(payload=payload, issued_session=session)

    def _consume_challenge(
        self,
        challenge_bytes: bytes,
        *,
        purpose: WebAuthnChallengePurpose,
        principal_id: UUID | None,
        origin: str,
        allow_unbound: bool = False,
        stored_principal: UUID | None = None,
    ) -> WebAuthnChallenge:
        now = self._clock()
        record = self._stores.challenges.consume(
            challenge_bytes,
            purpose=purpose,
            principal_id=principal_id,
            now=now,
        )
        if record is None and allow_unbound and stored_principal is not None:
            record = self._stores.challenges.consume(
                challenge_bytes,
                purpose=purpose,
                principal_id=None,
                now=now,
            )
            if record is not None and record.principal_id not in {None, stored_principal}:
                raise WebAuthnCeremonyError("principal_mismatch")
        if record is None:
            raise WebAuthnCeremonyError("invalid_challenge")
        if record.rp_id != self._rp.rp_id or record.origin != origin:
            raise WebAuthnCeremonyError("wrong_origin")
        return record

    def _consume_admin_grant(
        self,
        principal_id: UUID,
        *,
        origin: str,
        grant: str,
        authorizing_sid: str | None,
    ) -> None:
        self._require_origin(origin)
        self._admit("ordinary")
        session = self._resolve_authorizing_session(principal_id, authorizing_sid)
        record = self._stores.grants.consume(
            grant,
            AuthGrantPurpose.CREDENTIAL_ADMINISTRATION,
            now=self._clock(),
            authorizing_session_id=session.id,
        )
        if record is None:
            _log_grant_failure("step_up_required", None)
            raise WebAuthnCeremonyError("step_up_required")

    def _require_origin(self, origin: str) -> None:
        if not self._rp.accepts_origin(origin):
            raise WebAuthnCeremonyError("wrong_origin")

    def _has_active_recovery(self, principal_id: UUID) -> bool:
        return bool(self._stores.recovery.active_sets_for(principal_id))

    def _admit(self, kind: _Admit) -> None:
        state = AuthStateValidator(self._connection).inspect(now=self._clock())
        if state.kind is AuthStateKind.INCONSISTENT:
            raise WebAuthnCeremonyError("auth_state_inconsistent")
        if kind == "bootstrap":
            if state.kind is AuthStateKind.READY:
                raise WebAuthnCeremonyError("bootstrap_unavailable")
            return
        if state.kind is AuthStateKind.UNINITIALIZED:
            if kind == "operator_recovery":
                raise WebAuthnCeremonyError("operator_recovery_unavailable")
            raise WebAuthnCeremonyError("bootstrap_required")

    def _resolve_authorizing_session(self, principal_id: UUID, sid: str | None) -> AuthSession:
        if sid is None or not sid.strip():
            raise WebAuthnCeremonyError("unauthenticated")
        session = self._stores.sessions.resolve(sid, now=self._clock())
        if session is None:
            raise WebAuthnCeremonyError("unauthenticated")
        if session.principal_id != principal_id:
            raise WebAuthnCeremonyError("principal_mismatch")
        return session

    def _lock_grant_bound_challenge(
        self,
        credential: Mapping[str, Any],
        *,
        purpose: WebAuthnChallengePurpose,
        grant_purpose: AuthGrantPurpose,
        origin: str,
        invalid_grant_code: str,
    ) -> tuple[WebAuthnChallenge, UUID]:
        now = ensure_utc(self._clock())
        try:
            digest = digest_bytes(_client_challenge(credential))
        except (WebAuthnCeremonyError, AuthSecretError) as error:
            if isinstance(error, WebAuthnCeremonyError):
                raise
            raise WebAuthnCeremonyError("invalid_challenge") from error
        row = self._connection.execute(
            select(*webauthn_challenges.c)
            .where(
                webauthn_challenges.c.challenge_digest == digest,
                webauthn_challenges.c.consumed_at.is_(None),
                webauthn_challenges.c.expires_at > now,
                webauthn_challenges.c.purpose == purpose.value,
                webauthn_challenges.c.principal_id == LOCAL_OPERATOR_UUID,
            )
            .with_for_update()
        ).one_or_none()
        if row is None:
            raise WebAuthnCeremonyError("invalid_challenge")
        mapping = row._mapping
        if mapping["rp_id"] != self._rp.rp_id or mapping["origin"] != origin:
            raise WebAuthnCeremonyError("wrong_origin")
        grant_id = mapping["auth_grant_id"]
        if grant_id is None:
            raise WebAuthnCeremonyError(invalid_grant_code)
        grant_row = self._connection.execute(
            select(*auth_grants.c).where(auth_grants.c.id == grant_id).with_for_update()
        ).one_or_none()
        if grant_row is None:
            _log_grant_failure(invalid_grant_code, grant_id)
            raise WebAuthnCeremonyError(invalid_grant_code)
        grant = grant_row._mapping
        if (
            grant["purpose"] != grant_purpose.value
            or grant["exchanged_at"] is None
            or grant["consumed_at"] is not None
            or grant["revoked_at"] is not None
            or grant["expires_at"] <= now
            or grant["target_principal_id"] != LOCAL_OPERATOR_UUID
        ):
            _log_grant_failure(invalid_grant_code, grant_id)
            raise WebAuthnCeremonyError(invalid_grant_code)
        challenge = WebAuthnChallenge(
            id=mapping["id"],
            challenge_digest=mapping["challenge_digest"],
            purpose=WebAuthnChallengePurpose(mapping["purpose"]),
            rp_id=mapping["rp_id"],
            origin=mapping["origin"],
            created_at=mapping["created_at"],
            expires_at=mapping["expires_at"],
            challenge_bytes=bytes(mapping["challenge_bytes"]),
            principal_id=mapping["principal_id"],
            credential_record_id=mapping["credential_record_id"],
            auth_grant_id=mapping["auth_grant_id"],
            consumed_at=mapping["consumed_at"],
        )
        return challenge, grant_id

    def _verified_registration(
        self,
        credential: Mapping[str, Any],
        *,
        challenge: WebAuthnChallenge,
        origin: str,
        grant_purpose: AuthGrantPurpose,
    ) -> _VerifiedRegistration:
        try:
            verified = self._verify_registration(
                credential=dict(credential),
                expected_challenge=challenge.challenge_bytes,
                expected_rp_id=self._rp.rp_id,
                expected_origin=origin,
                require_user_verification=True,
            )
        except WebAuthnCeremonyError:
            self._burn_failed_registration(challenge, grant_purpose)
            raise
        except Exception as error:
            self._burn_failed_registration(challenge, grant_purpose)
            raise WebAuthnCeremonyError("invalid_registration") from error
        if not getattr(verified, "user_verified", True):
            self._burn_failed_registration(challenge, grant_purpose)
            raise WebAuthnCeremonyError("user_verification_missing")
        return _VerifiedRegistration(
            credential_id=bytes(verified.credential_id),
            public_key=bytes(verified.credential_public_key),
            sign_count=int(verified.sign_count),
        )

    def _burn_failed_registration(
        self, challenge: WebAuthnChallenge, grant_purpose: AuthGrantPurpose
    ) -> None:
        now = self._clock()
        self._stores.challenges.consume(
            challenge.challenge_bytes,
            purpose=challenge.purpose,
            principal_id=challenge.principal_id,
            now=now,
        )
        self._stores.grants.revoke_active(grant_purpose, now=now, reason="ceremony_failed")
        _log_grant_failure("invalid_registration", challenge.auth_grant_id)

    def _finish_grant_bound_registration(
        self,
        challenge: WebAuthnChallenge,
        *,
        grant_id: UUID,
        grant_purpose: AuthGrantPurpose,
        origin: str,
    ) -> None:
        now = self._clock()
        consumed = self._stores.challenges.consume(
            challenge.challenge_bytes,
            purpose=challenge.purpose,
            principal_id=challenge.principal_id,
            now=now,
        )
        if consumed is None:
            raise WebAuthnCeremonyError("invalid_challenge")
        if consumed.rp_id != self._rp.rp_id or consumed.origin != origin:
            raise WebAuthnCeremonyError("wrong_origin")
        instant = ensure_utc(now)
        row = self._connection.execute(
            update(auth_grants)
            .where(
                auth_grants.c.id == grant_id,
                auth_grants.c.purpose == grant_purpose.value,
                auth_grants.c.target_principal_id == LOCAL_OPERATOR_UUID,
                auth_grants.c.exchanged_at.is_not(None),
                auth_grants.c.consumed_at.is_(None),
                auth_grants.c.revoked_at.is_(None),
                auth_grants.c.expires_at > instant,
            )
            .values(consumed_at=instant)
            .returning(auth_grants.c.id)
        ).one_or_none()
        if row is None:
            code = (
                "bootstrap_grant_invalid"
                if grant_purpose is AuthGrantPurpose.BOOTSTRAP
                else "operator_recovery_grant_invalid"
            )
            _log_grant_failure(code, grant_id)
            raise WebAuthnCeremonyError(code)

    def _create_credential(
        self, *, principal_id: UUID, verified: _VerifiedRegistration, label: str | None
    ) -> WebAuthnCredential:
        try:
            return self._stores.credentials.create(
                principal_id=principal_id,
                credential_id=verified.credential_id,
                public_key=verified.public_key,
                now=self._clock(),
                sign_count=verified.sign_count,
                user_handle=principal_id.bytes,
                label=label,
            )
        except ValueError as error:
            if "already registered" in str(error):
                raise WebAuthnCeremonyError("duplicate_credential") from error
            raise


def _descriptors(records: tuple[WebAuthnCredential, ...]) -> list[PublicKeyCredentialDescriptor]:
    return [PublicKeyCredentialDescriptor(id=item.credential_id) for item in records if item.active]


def _options_payload(serialized: str) -> Mapping[str, Any]:
    import json

    document = json.loads(serialized)
    if not isinstance(document, dict):
        raise WebAuthnCeremonyError("invalid_registration")
    return document


def _client_challenge(credential: Mapping[str, Any]) -> bytes:
    from webauthn.helpers import base64url_to_bytes

    response = credential.get("response")
    if not isinstance(response, Mapping):
        raise WebAuthnCeremonyError("invalid_assertion")
    client_data = response.get("clientDataJSON")
    if not isinstance(client_data, str) or not client_data:
        raise WebAuthnCeremonyError("invalid_assertion")
    try:
        import json

        decoded = base64url_to_bytes(client_data)
        parsed = json.loads(decoded.decode("utf-8"))
        challenge = parsed["challenge"]
        if not isinstance(challenge, str):
            raise WebAuthnCeremonyError("invalid_challenge")
        return base64url_to_bytes(challenge)
    except WebAuthnCeremonyError:
        raise
    except Exception as error:
        raise WebAuthnCeremonyError("invalid_assertion") from error


def _credential_id(credential: Mapping[str, Any]) -> bytes:
    from webauthn.helpers import base64url_to_bytes

    raw = credential.get("rawId") or credential.get("id")
    if not isinstance(raw, str) or not raw:
        raise WebAuthnCeremonyError("unknown_credential")
    try:
        return base64url_to_bytes(raw)
    except Exception as error:
        raise WebAuthnCeremonyError("unknown_credential") from error


def _log_grant_failure(code: str, grant_id: UUID | None) -> None:
    _LOG.info("webauthn grant failure code=%s grant_id=%s", code, grant_id)


def principal_uuid_from_text(principal_id: str) -> UUID:
    """Durable UUID for a capture-plane principal identifier."""
    return durable_principal_uuid(principal_id)
