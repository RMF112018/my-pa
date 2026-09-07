"""Ceremony persistence: consume-once, Principal isolation, recovery, sessions."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Final
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, text
from webauthn.helpers import bytes_to_base64url

from my_pa.application.webauthn_bff_attestation import issue_webauthn_attestation
from my_pa.bootstrap.gateway import _webauthn_execute
from my_pa.domain.identity.auth_grants import AuthGrantPurpose
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.domain.identity.user_account import SYNTHETIC_TENANT_ID
from my_pa.domain.identity.webauthn_relying_party import WebAuthnCeremonyError, WebAuthnRelyingParty
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.auth_grants import AuthGrantStore
from my_pa.infrastructure.persistence.webauthn_auth import WebAuthnAuthPersistence
from my_pa.infrastructure.security.webauthn_ceremony import (
    CeremonyResult,
    WebAuthnCeremonyService,
)

pytestmark = pytest.mark.database

WHEN: Final = datetime(2026, 9, 2, 15, tzinfo=UTC)
ORIGIN: Final = "http://localhost:3100"
OTHER_ORIGIN: Final = "http://127.0.0.1:3100"
RP = WebAuthnRelyingParty(
    rp_id="localhost",
    rp_name="my-pa",
    allowed_origins=(ORIGIN, OTHER_ORIGIN),
)
BFF_SECRET: Final = "synthetic-webauthn-bff-secret-00000000"  # noqa: S105


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def isolate_identity(engine: Engine) -> Iterator[None]:
    yield
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE identity.recovery_codes, identity.recovery_code_sets, "
                "identity.webauthn_challenges, identity.webauthn_credentials, "
                "identity.auth_grants, identity.auth_sessions, identity.user_accounts "
                "CASCADE"
            )
        )


def _seed_synthetic(engine: Engine, principal_id: UUID | None = None) -> UUID:
    identifier = principal_id or uuid4()
    oid = f"oid-{identifier}"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO identity.user_accounts "
                "(id, principal_id, identity_provider, identity_subject, tid, oid, "
                " first_seen_at, consent_state, lifecycle_state) "
                "VALUES (:id, :principal_id, 'synthetic', :subject, :tid, :oid, "
                " :now, 'granted', 'active')"
            ),
            {
                "id": uuid4(),
                "principal_id": identifier,
                "subject": f"{SYNTHETIC_TENANT_ID}:{oid}",
                "tid": SYNTHETIC_TENANT_ID,
                "oid": oid,
                "now": WHEN,
            },
        )
    return identifier


def _verify_registration(
    credential_id: bytes = b"cred-a", public_key: bytes = b"cose-key"
) -> Callable[..., SimpleNamespace]:
    def verify_registration(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            credential_id=credential_id,
            credential_public_key=public_key,
            sign_count=0,
            user_verified=True,
        )

    return verify_registration


def _verify_authentication(*, sign_count: int = 1) -> Callable[..., SimpleNamespace]:
    def verify_authentication(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(new_sign_count=sign_count, user_verified=True)

    return verify_authentication


def _service(
    connection: Connection,
    *,
    verify_registration: Callable[..., SimpleNamespace] | None = None,
    verify_authentication: Callable[..., SimpleNamespace] | None = None,
    require_local_operator: bool = True,
) -> WebAuthnCeremonyService:
    kwargs: dict[str, Any] = {
        "clock": lambda: WHEN,
        "require_local_operator": require_local_operator,
    }
    if verify_registration is not None:
        kwargs["verify_registration"] = verify_registration
    if verify_authentication is not None:
        kwargs["verify_authentication"] = verify_authentication
    return WebAuthnCeremonyService(connection, RP, **kwargs)


def _credential_payload(
    challenge: str, credential_id: bytes = b"cred-a"
) -> dict[str, str | dict[str, str]]:
    return {
        "id": bytes_to_base64url(credential_id),
        "rawId": bytes_to_base64url(credential_id),
        "type": "public-key",
        "response": {
            "clientDataJSON": bytes_to_base64url(
                __import__("json")
                .dumps({"type": "webauthn.create", "origin": ORIGIN, "challenge": challenge})
                .encode()
            ),
            "attestationObject": "AA",
        },
    }


def _assertion_payload(
    challenge: str, credential_id: bytes = b"cred-a"
) -> dict[str, str | dict[str, str]]:
    return {
        "id": bytes_to_base64url(credential_id),
        "rawId": bytes_to_base64url(credential_id),
        "type": "public-key",
        "response": {
            "clientDataJSON": bytes_to_base64url(
                __import__("json")
                .dumps({"type": "webauthn.get", "origin": ORIGIN, "challenge": challenge})
                .encode()
            ),
            "authenticatorData": "AA",
            "signature": "AA",
        },
    }


def _bootstrap(connection: Connection, *, credential_id: bytes = b"cred-a") -> CeremonyResult:
    grants = AuthGrantStore(connection)
    issued = grants.issue(AuthGrantPurpose.BOOTSTRAP, now=WHEN)
    service = _service(connection, verify_registration=_verify_registration(credential_id))
    options = service.bootstrap_registration_options(origin=ORIGIN, grant=issued.raw_grant)
    challenge = options.payload["challenge"]
    assert isinstance(challenge, str)
    return service.bootstrap_registration_complete(
        origin=ORIGIN, credential=_credential_payload(challenge, credential_id)
    )


def test_bootstrap_uninitialized_happy_path(engine: Engine) -> None:
    with engine.begin() as connection:
        created = _bootstrap(connection)
        assert created.payload["registered"] is True
        assert created.issued_session is not None
        assert created.recovery_codes
        state = _service(connection).auth_state()
        assert state.payload == {"state": "ready"}
        assert list(state.payload) == ["state"]


def test_bootstrap_grant_replay_fails(engine: Engine) -> None:
    with engine.begin() as connection:
        grants = AuthGrantStore(connection)
        issued = grants.issue(AuthGrantPurpose.BOOTSTRAP, now=WHEN)
        service = _service(connection, verify_registration=_verify_registration())
        service.bootstrap_registration_options(origin=ORIGIN, grant=issued.raw_grant)
        with pytest.raises(WebAuthnCeremonyError) as replayed:
            service.bootstrap_registration_options(origin=ORIGIN, grant=issued.raw_grant)
        assert replayed.value.code == "bootstrap_grant_invalid"


def test_post_ready_bootstrap_is_refused(engine: Engine) -> None:
    with engine.begin() as connection:
        _bootstrap(connection)
        grants = AuthGrantStore(connection)
        issued = grants.issue(AuthGrantPurpose.BOOTSTRAP, now=WHEN)
        service = _service(connection, verify_registration=_verify_registration(b"cred-b"))
        with pytest.raises(WebAuthnCeremonyError) as raised:
            service.bootstrap_registration_options(origin=ORIGIN, grant=issued.raw_grant)
        assert raised.value.code == "bootstrap_unavailable"


def test_auth_state_public_payload_is_only_state(engine: Engine) -> None:
    with engine.begin() as connection:
        payload = _service(connection).auth_state().payload
        assert payload == {"state": "uninitialized"}
        assert "reasons" not in payload
        assert "principalId" not in payload
        assert "active_credential_count" not in payload


def test_authentication_challenge_cannot_register(engine: Engine) -> None:
    with engine.begin() as connection:
        bootstrapped = _bootstrap(connection)
        sid = bootstrapped.issued_session.raw_sid if bootstrapped.issued_session else None
        service = _service(
            connection,
            verify_registration=_verify_registration(b"cred-b"),
            verify_authentication=_verify_authentication(),
        )
        options = service.authentication_options(origin=ORIGIN, principal_id=LOCAL_OPERATOR_UUID)
        challenge = options.payload["challenge"]
        assert isinstance(challenge, str)
        step = service.step_up_options(LOCAL_OPERATOR_UUID, origin=ORIGIN)
        step_challenge = step.payload["challenge"]
        assert isinstance(step_challenge, str)
        stepped = service.step_up_complete(
            LOCAL_OPERATOR_UUID,
            origin=ORIGIN,
            credential=_assertion_payload(step_challenge),
            authorizing_sid=sid,
        )
        grant = stepped.payload["administrationGrant"]
        assert isinstance(grant, str)
        with pytest.raises(WebAuthnCeremonyError) as raised:
            service.registration_complete(
                LOCAL_OPERATOR_UUID,
                origin=ORIGIN,
                credential=_credential_payload(challenge, b"cred-b"),
            )
        assert raised.value.code == "invalid_challenge"


def test_library_rejects_malformed_registration(engine: Engine) -> None:
    with engine.begin() as connection:
        grants = AuthGrantStore(connection)
        issued = grants.issue(AuthGrantPurpose.BOOTSTRAP, now=WHEN)
        service = WebAuthnCeremonyService(
            connection, RP, clock=lambda: WHEN, require_local_operator=True
        )
        options = service.bootstrap_registration_options(origin=ORIGIN, grant=issued.raw_grant)
        challenge = options.payload["challenge"]
        assert isinstance(challenge, str)
        with pytest.raises(WebAuthnCeremonyError) as raised:
            service.bootstrap_registration_complete(
                origin=ORIGIN, credential=_credential_payload(challenge)
            )
        assert raised.value.code == "invalid_registration"


def test_recovery_consume_once_for_local_operator(engine: Engine) -> None:
    with engine.begin() as connection:
        bootstrapped = _bootstrap(connection)
        assert bootstrapped.recovery_codes
        code = bootstrapped.recovery_codes[0]
        service = _service(connection)
        recovered = service.consume_recovery(code, origin=ORIGIN)
        assert recovered.issued_session is not None
        assert recovered.payload["principalId"] == str(LOCAL_OPERATOR_UUID)
        with pytest.raises(WebAuthnCeremonyError) as reused:
            service.consume_recovery(code, origin=ORIGIN)
        assert reused.value.code == "invalid_recovery_code"


def test_foreign_principal_credential_cannot_mint_session(engine: Engine) -> None:
    foreign = _seed_synthetic(engine)
    with engine.begin() as connection:
        stores = WebAuthnAuthPersistence(connection)
        stores.credentials.create(
            principal_id=foreign,
            credential_id=b"foreign-cred",
            public_key=b"cose-foreign",
            now=WHEN,
        )
        service = _service(
            connection,
            verify_authentication=_verify_authentication(),
            require_local_operator=True,
        )
        with pytest.raises(WebAuthnCeremonyError) as raised:
            service.authentication_options(origin=ORIGIN)
        assert raised.value.code == "auth_state_inconsistent"
        sessions = connection.execute(
            text("SELECT count(*) FROM identity.auth_sessions")
        ).scalar_one()
        assert int(sessions) == 0


def test_registration_options_requires_grant_and_consumes_once(engine: Engine) -> None:
    with engine.begin() as connection:
        bootstrapped = _bootstrap(connection)
        sid = bootstrapped.issued_session.raw_sid if bootstrapped.issued_session else None
        service = _service(
            connection,
            verify_registration=_verify_registration(b"cred-b"),
            verify_authentication=_verify_authentication(),
        )
        with pytest.raises(WebAuthnCeremonyError) as missing:
            service.registration_options(
                LOCAL_OPERATOR_UUID, origin=ORIGIN, grant="", authorizing_sid=sid
            )
        assert missing.value.code in {"step_up_required", "unauthenticated"}
        step = service.step_up_options(LOCAL_OPERATOR_UUID, origin=ORIGIN)
        challenge = step.payload["challenge"]
        assert isinstance(challenge, str)
        stepped = service.step_up_complete(
            LOCAL_OPERATOR_UUID,
            origin=ORIGIN,
            credential=_assertion_payload(challenge),
            authorizing_sid=sid,
        )
        grant = stepped.payload["administrationGrant"]
        assert isinstance(grant, str)
        first = service.registration_options(
            LOCAL_OPERATOR_UUID, origin=ORIGIN, grant=grant, authorizing_sid=sid
        )
        assert "challenge" in first.payload
        with pytest.raises(WebAuthnCeremonyError) as second:
            service.registration_options(
                LOCAL_OPERATOR_UUID, origin=ORIGIN, grant=grant, authorizing_sid=sid
            )
        assert second.value.code == "step_up_required"


def test_authenticated_registration_without_grant_fails(engine: Engine) -> None:
    with engine.begin() as connection:
        bootstrapped = _bootstrap(connection)
        sid = bootstrapped.issued_session.raw_sid if bootstrapped.issued_session else None
        service = _service(connection)
        with pytest.raises(WebAuthnCeremonyError) as raised:
            service.registration_options(
                LOCAL_OPERATOR_UUID,
                origin=ORIGIN,
                grant="0" * 64,
                authorizing_sid=sid,
            )
        assert raised.value.code == "step_up_required"


def test_bootstrap_grant_cannot_be_used_for_operator_recovery_or_enrollment(
    engine: Engine,
) -> None:
    with engine.begin() as connection:
        grants = AuthGrantStore(connection)
        bootstrap_grant = grants.issue(AuthGrantPurpose.BOOTSTRAP, now=WHEN)
        service = _service(connection, verify_registration=_verify_registration())
        with pytest.raises(WebAuthnCeremonyError) as recovery:
            service.operator_recovery_registration_options(
                origin=ORIGIN, grant=bootstrap_grant.raw_grant
            )
        assert recovery.value.code == "operator_recovery_unavailable"
        created = service.bootstrap_registration_options(
            origin=ORIGIN, grant=bootstrap_grant.raw_grant
        )
        challenge = created.payload["challenge"]
        assert isinstance(challenge, str)
        bootstrapped = service.bootstrap_registration_complete(
            origin=ORIGIN, credential=_credential_payload(challenge)
        )
        sid = bootstrapped.issued_session.raw_sid if bootstrapped.issued_session else None
        grants = AuthGrantStore(connection)
        leftover = grants.issue(AuthGrantPurpose.BOOTSTRAP, now=WHEN)
        with pytest.raises(WebAuthnCeremonyError) as enroll:
            service.registration_options(
                LOCAL_OPERATOR_UUID,
                origin=ORIGIN,
                grant=leftover.raw_grant,
                authorizing_sid=sid,
            )
        assert enroll.value.code == "step_up_required"
        with pytest.raises(WebAuthnCeremonyError) as operator:
            service.operator_recovery_registration_options(origin=ORIGIN, grant=leftover.raw_grant)
        assert operator.value.code == "operator_recovery_grant_invalid"


def test_operator_recovery_revokes_sessions_and_preserves_passkeys(engine: Engine) -> None:
    with engine.begin() as connection:
        first = _bootstrap(connection, credential_id=b"cred-a")
        old_sid = first.issued_session.raw_sid if first.issued_session else None
        grants = AuthGrantStore(connection)
        recovery_grant = grants.issue(AuthGrantPurpose.OPERATOR_RECOVERY, now=WHEN)
        service = _service(connection, verify_registration=_verify_registration(b"cred-b"))
        options = service.operator_recovery_registration_options(
            origin=ORIGIN, grant=recovery_grant.raw_grant
        )
        challenge = options.payload["challenge"]
        assert isinstance(challenge, str)
        completed = service.operator_recovery_registration_complete(
            origin=ORIGIN, credential=_credential_payload(challenge, b"cred-b")
        )
        assert completed.issued_session is not None
        assert completed.recovery_codes
        listed = service.list_credentials(LOCAL_OPERATOR_UUID)
        credentials = listed.payload["credentials"]
        assert isinstance(credentials, list)
        assert len(credentials) == 2
        stores = WebAuthnAuthPersistence(connection)
        assert stores.sessions.resolve(old_sid or "", now=WHEN) is None
        assert stores.sessions.resolve(completed.issued_session.raw_sid, now=WHEN) is not None


def test_wrong_origin_fails(engine: Engine) -> None:
    with engine.begin() as connection:
        grants = AuthGrantStore(connection)
        issued = grants.issue(AuthGrantPurpose.BOOTSTRAP, now=WHEN)
        service = _service(connection, verify_registration=_verify_registration())
        with pytest.raises(WebAuthnCeremonyError) as raised:
            service.bootstrap_registration_options(
                origin="https://evil.example", grant=issued.raw_grant
            )
        assert raised.value.code == "wrong_origin"


def test_attestation_does_not_create_accounts(engine: Engine) -> None:
    unknown = uuid4()
    execute = _webauthn_execute(
        engine,
        relying_party=RP,
        bff_secret=BFF_SECRET,
        clock=lambda: WHEN,
        require_local_operator=True,
    )
    token = issue_webauthn_attestation(BFF_SECRET, principal_id=unknown, now=WHEN)
    with pytest.raises(WebAuthnCeremonyError) as raised:
        execute("credentials/list", ORIGIN, {}, token, None)
    assert raised.value.code == "unauthenticated"
    with engine.connect() as connection:
        count = connection.execute(text("SELECT count(*) FROM identity.user_accounts")).scalar_one()
    assert int(count) == 0


def test_concurrent_bootstrap_complete_succeeds_once(engine: Engine) -> None:
    with engine.begin() as connection:
        grants = AuthGrantStore(connection)
        issued = grants.issue(AuthGrantPurpose.BOOTSTRAP, now=WHEN)
        service = _service(connection, verify_registration=_verify_registration())
        options = service.bootstrap_registration_options(origin=ORIGIN, grant=issued.raw_grant)
        challenge = options.payload["challenge"]
        assert isinstance(challenge, str)
        payload = _credential_payload(challenge)

    def attempt() -> str | None:
        try:
            with engine.begin() as connection:
                service = _service(connection, verify_registration=_verify_registration())
                result = service.bootstrap_registration_complete(origin=ORIGIN, credential=payload)
                return str(result.payload.get("credentialId"))
        except WebAuthnCeremonyError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = tuple(pool.map(lambda _item: attempt(), range(8)))
    assert outcomes.count(None) == 7
    assert sum(1 for item in outcomes if item is not None) == 1
    with engine.connect() as connection:
        credentials = connection.execute(
            text("SELECT count(*) FROM identity.webauthn_credentials")
        ).scalar_one()
        grants_consumed = connection.execute(
            text(
                "SELECT count(*) FROM identity.auth_grants "
                "WHERE purpose = 'bootstrap' AND consumed_at IS NOT NULL"
            )
        ).scalar_one()
    assert int(credentials) == 1
    assert int(grants_consumed) == 1
