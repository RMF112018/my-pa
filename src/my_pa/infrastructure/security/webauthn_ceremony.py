"""WebAuthn/passkey ceremony over WP02 persistence.

Verification is delegated to the `webauthn` library. This module owns challenge
purpose isolation, Principal binding, recovery, step-up grants, and session
handoff. It does not mint the production HMAC cookie.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import Connection
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

from my_pa.domain.identity.auth_sessions import IssuedAuthSession
from my_pa.domain.identity.binding import durable_principal_uuid
from my_pa.domain.identity.user_account import EntraTokenClaims
from my_pa.domain.identity.webauthn_credentials import (
    WebAuthnChallenge,
    WebAuthnChallengePurpose,
    WebAuthnCredential,
)
from my_pa.domain.identity.webauthn_relying_party import (
    WebAuthnCeremonyError,
    WebAuthnRelyingParty,
)
from my_pa.infrastructure.persistence.user_accounts import UserAccountRepository
from my_pa.infrastructure.persistence.webauthn_auth import WebAuthnAuthPersistence

__all__ = [
    "ADMIN_GRANT_TTL",
    "CeremonyResult",
    "WebAuthnCeremonyService",
]

ADMIN_GRANT_TTL: Final = timedelta(minutes=5)
_LAST_CREDENTIAL_BLOCK: Final = "last_passkey_requires_recovery"


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
    ) -> None:
        self._stores = WebAuthnAuthPersistence(connection)
        self._accounts = UserAccountRepository(connection)
        self._rp = relying_party
        self._clock = clock
        self._verify_registration = verify_registration
        self._verify_authentication = verify_authentication

    def ensure_account(
        self,
        *,
        tid: str,
        oid: str,
        upn: str | None,
        display_name: str | None,
    ) -> UUID:
        """Map attested `(tid, oid)` to the durable identity-plane UUID."""
        account = self._accounts.resolve_or_create(
            EntraTokenClaims(tid=tid, oid=oid, upn=upn, display_name=display_name),
            now=self._clock(),
        )
        return account.principal_id

    def registration_options(self, principal_id: UUID, *, origin: str) -> CeremonyResult:
        self._require_origin(origin)
        now = self._clock()
        existing = self._stores.credentials.list_for_principal(principal_id)
        issued = self._stores.challenges.issue(
            purpose=WebAuthnChallengePurpose.REGISTRATION,
            rp_id=self._rp.rp_id,
            origin=origin,
            now=now,
            principal_id=principal_id,
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
        challenge = self._consume_challenge(
            _client_challenge(credential),
            purpose=WebAuthnChallengePurpose.REGISTRATION,
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
        credential_id = bytes(verified.credential_id)
        public_key = bytes(verified.credential_public_key)
        sign_count = int(verified.sign_count)
        try:
            record = self._stores.credentials.create(
                principal_id=principal_id,
                credential_id=credential_id,
                public_key=public_key,
                now=self._clock(),
                sign_count=sign_count,
                user_handle=principal_id.bytes,
                label=label,
            )
        except ValueError as error:
            if "already registered" in str(error):
                raise WebAuthnCeremonyError("duplicate_credential") from error
            raise
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
        return self._assert(
            origin=origin,
            credential=credential,
            purpose=WebAuthnChallengePurpose.AUTHENTICATION,
            create_session=True,
        )

    def step_up_options(self, principal_id: UUID, *, origin: str) -> CeremonyResult:
        self._require_origin(origin)
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
        self, principal_id: UUID, *, origin: str, credential: Mapping[str, Any]
    ) -> CeremonyResult:
        result = self._assert(
            origin=origin,
            credential=credential,
            purpose=WebAuthnChallengePurpose.STEP_UP,
            expected_principal=principal_id,
            create_session=False,
        )
        grant = self._stores.challenges.issue(
            purpose=WebAuthnChallengePurpose.CREDENTIAL_ADMINISTRATION,
            rp_id=self._rp.rp_id,
            origin=origin,
            now=self._clock(),
            principal_id=principal_id,
            ttl=ADMIN_GRANT_TTL,
        )
        return CeremonyResult(
            payload={
                **result.payload,
                "administrationGrant": bytes_to_base64url(grant.challenge_bytes),
            }
        )

    def list_credentials(self, principal_id: UUID) -> CeremonyResult:
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
        administration_grant: bytes,
    ) -> CeremonyResult:
        self._consume_admin_grant(principal_id, origin=origin, grant=administration_grant)
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
        self, principal_id: UUID, *, origin: str, administration_grant: bytes
    ) -> CeremonyResult:
        self._consume_admin_grant(principal_id, origin=origin, grant=administration_grant)
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
        consumed = self._stores.recovery.consume_code(presented, now=self._clock())
        if consumed is None:
            raise WebAuthnCeremonyError("invalid_recovery_code")
        principal_id = self._stores.recovery.principal_for_set(consumed.set_id)
        if principal_id is None:
            raise WebAuthnCeremonyError("invalid_recovery_code")
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
        self, principal_id: UUID, *, origin: str, administration_grant: bytes
    ) -> CeremonyResult:
        self._consume_admin_grant(principal_id, origin=origin, grant=administration_grant)
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

    def _consume_admin_grant(self, principal_id: UUID, *, origin: str, grant: bytes) -> None:
        self._require_origin(origin)
        record = self._stores.challenges.consume(
            grant,
            purpose=WebAuthnChallengePurpose.CREDENTIAL_ADMINISTRATION,
            principal_id=principal_id,
            now=self._clock(),
        )
        if record is None:
            raise WebAuthnCeremonyError("step_up_required")
        if record.origin != origin or record.rp_id != self._rp.rp_id:
            raise WebAuthnCeremonyError("wrong_origin")

    def _require_origin(self, origin: str) -> None:
        if not self._rp.accepts_origin(origin):
            raise WebAuthnCeremonyError("wrong_origin")

    def _has_active_recovery(self, principal_id: UUID) -> bool:
        return bool(self._stores.recovery.active_sets_for(principal_id))


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


def principal_uuid_from_text(principal_id: str) -> UUID:
    """Durable UUID for a capture-plane principal identifier."""
    return durable_principal_uuid(principal_id)
