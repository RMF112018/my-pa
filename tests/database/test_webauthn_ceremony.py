"""Ceremony persistence: consume-once, Principal isolation, recovery, sessions."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Final
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url
from webauthn.helpers import bytes_to_base64url

from my_pa.application.webauthn_ceremony import WebAuthnCeremonyError, WebAuthnCeremonyService
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.identity.webauthn_relying_party import WebAuthnRelyingParty
from my_pa.infrastructure.database.engine import create_database_engine

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
DISPOSABLE_DATABASE: Final = "my_pa_webauthn_ceremony_test"
WHEN: Final = datetime(2026, 9, 2, 15, tzinfo=UTC)
ORIGIN: Final = "http://localhost:3100"
RP = WebAuthnRelyingParty(rp_id="localhost", rp_name="my-pa", allowed_origins=(ORIGIN,))


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')
    try:
        _administer(maintenance, drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        yield url
    finally:
        _administer(maintenance, drop)
        maintenance.dispose()


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)
    try:
        yield engine
    finally:
        engine.dispose()


def _seed(engine: Engine, principal_id: UUID | None = None) -> UUID:
    identifier = principal_id or uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO identity.user_accounts "
                "(id, principal_id, tid, oid, first_seen_at, consent_state, lifecycle_state) "
                "VALUES (:id, :principal_id, :tid, :oid, :now, 'granted', 'active')"
            ),
            {
                "id": uuid4(),
                "principal_id": identifier,
                "tid": f"tid-{identifier}",
                "oid": f"oid-{identifier}",
                "now": WHEN,
            },
        )
    return identifier


def _service(
    connection: Connection,
    verify_registration: Callable[..., SimpleNamespace] | None = None,
) -> WebAuthnCeremonyService:
    if verify_registration is None:
        return WebAuthnCeremonyService(connection, RP, clock=lambda: WHEN)
    return WebAuthnCeremonyService(
        connection,
        RP,
        clock=lambda: WHEN,
        verify_registration=verify_registration,
    )


def test_registration_persists_and_replay_fails(engine: Engine) -> None:
    principal = _seed(engine)
    credential_id = b"cred-a"
    public_key = b"cose-key"

    def verify_registration(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            credential_id=credential_id,
            credential_public_key=public_key,
            sign_count=0,
            user_verified=True,
        )

    with engine.begin() as connection:
        service = _service(connection, verify_registration=verify_registration)
        options = service.registration_options(principal, origin=ORIGIN)
        challenge = options.payload["challenge"]
        assert isinstance(challenge, str)
        payload = {
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
        created = service.registration_complete(principal, origin=ORIGIN, credential=payload)
        assert created.payload["registered"] is True
        with pytest.raises(WebAuthnCeremonyError) as replayed:
            service.registration_complete(principal, origin=ORIGIN, credential=payload)
        assert replayed.value.code == "invalid_challenge"


def test_authentication_challenge_cannot_register(engine: Engine) -> None:
    principal = _seed(engine)
    with engine.begin() as connection:
        service = _service(connection)
        options = service.authentication_options(origin=ORIGIN, principal_id=principal)
        challenge = options.payload["challenge"]
        payload = {
            "id": bytes_to_base64url(b"x"),
            "rawId": bytes_to_base64url(b"x"),
            "response": {
                "clientDataJSON": bytes_to_base64url(
                    __import__("json")
                    .dumps({"type": "webauthn.create", "origin": ORIGIN, "challenge": challenge})
                    .encode()
                )
            },
        }
        with pytest.raises(WebAuthnCeremonyError) as raised:
            service.registration_complete(principal, origin=ORIGIN, credential=payload)
        assert raised.value.code == "invalid_challenge"


def test_recovery_consume_once_and_cross_principal(engine: Engine) -> None:
    principal_a = _seed(engine)
    principal_b = _seed(engine)
    with engine.begin() as connection:
        service = _service(connection)
        grant = service._stores.challenges.issue(
            purpose=__import__(
                "my_pa.domain.identity.webauthn_credentials",
                fromlist=["WebAuthnChallengePurpose"],
            ).WebAuthnChallengePurpose.CREDENTIAL_ADMINISTRATION,
            rp_id="localhost",
            origin=ORIGIN,
            now=WHEN,
            principal_id=principal_a,
        )
        issued = service.issue_recovery(
            principal_a, origin=ORIGIN, administration_grant=grant.challenge_bytes
        )
        assert issued.recovery_codes
        code = issued.recovery_codes[0]
        recovered = service.consume_recovery(code, origin=ORIGIN)
        assert recovered.issued_session is not None
        assert recovered.payload["principalId"] == str(principal_a)
        with pytest.raises(WebAuthnCeremonyError) as reused:
            service.consume_recovery(code, origin=ORIGIN)
        assert reused.value.code == "invalid_recovery_code"
        grant_b = service._stores.challenges.issue(
            purpose=__import__(
                "my_pa.domain.identity.webauthn_credentials",
                fromlist=["WebAuthnChallengePurpose"],
            ).WebAuthnChallengePurpose.CREDENTIAL_ADMINISTRATION,
            rp_id="localhost",
            origin=ORIGIN,
            now=WHEN,
            principal_id=principal_b,
        )
        issued_b = service.issue_recovery(
            principal_b, origin=ORIGIN, administration_grant=grant_b.challenge_bytes
        )
        assert issued_b.recovery_codes
        recovered_b = service.consume_recovery(issued_b.recovery_codes[0], origin=ORIGIN)
        assert recovered_b.payload["principalId"] == str(principal_b)
        assert recovered_b.payload["principalId"] != str(principal_a)


def test_library_rejects_malformed_registration(engine: Engine) -> None:
    principal = _seed(engine)
    with engine.begin() as connection:
        service = WebAuthnCeremonyService(connection, RP, clock=lambda: WHEN)
        options = service.registration_options(principal, origin=ORIGIN)
        challenge = options.payload["challenge"]
        payload = {
            "id": "AAAA",
            "rawId": "AAAA",
            "response": {
                "clientDataJSON": bytes_to_base64url(
                    __import__("json")
                    .dumps({"type": "webauthn.create", "origin": ORIGIN, "challenge": challenge})
                    .encode()
                ),
                "attestationObject": "AAAA",
            },
        }
        with pytest.raises(WebAuthnCeremonyError) as raised:
            service.registration_complete(principal, origin=ORIGIN, credential=payload)
        assert raised.value.code == "invalid_registration"
