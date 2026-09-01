"""Deployment-coherent WebAuthn/session persistence on disposable PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.identity.recovery_codes import normalize_recovery_code
from my_pa.domain.identity.secret_digests import digest_text
from my_pa.domain.identity.webauthn_credentials import WebAuthnChallengePurpose
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.webauthn_auth import (
    AuthSessionStore,
    RecoveryCodeStore,
    WebAuthnAuthPersistence,
    WebAuthnChallengeStore,
    WebAuthnCredentialStore,
    recovery_codes,
)

ROOT: Final = Path(__file__).resolve().parents[2]
DISPOSABLE_DATABASE: Final = "my_pa_webauthn_auth_persistence_test"
WHEN: Final = datetime(2026, 9, 1, 15, tzinfo=UTC)
RP_ID: Final = "my-pa.example"
ORIGIN: Final = "https://my-pa.example"


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


def _seed_principal(engine: Engine, principal_id: UUID | None = None) -> UUID:
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


def test_credentials_persist_across_store_instances_and_isolate_principals(
    engine: Engine,
) -> None:
    principal_a = _seed_principal(engine)
    principal_b = _seed_principal(engine)
    credential_id = b"cred-a"
    with engine.begin() as connection:
        store = WebAuthnCredentialStore(connection)
        created = store.create(
            principal_id=principal_a,
            credential_id=credential_id,
            public_key=b"cose-key",
            now=WHEN,
            label="laptop",
        )
        assert created.principal_id == principal_a
        with pytest.raises(ValueError, match="already registered"):
            store.create(
                principal_id=principal_b,
                credential_id=credential_id,
                public_key=b"other-key",
                now=WHEN,
            )
        other = store.create(
            principal_id=principal_b,
            credential_id=b"cred-b",
            public_key=b"cose-b",
            now=WHEN,
        )
        assert other.principal_id == principal_b
        assert {item.credential_id for item in store.list_for_principal(principal_a)} == {
            credential_id
        }

    with engine.begin() as connection:
        store = WebAuthnCredentialStore(connection)
        loaded = store.get_by_credential_id(credential_id)
        assert loaded is not None
        assert loaded.principal_id == principal_a
        used = store.record_use(credential_id, sign_count=3, now=WHEN + timedelta(minutes=1))
        assert used is not None and used.sign_count == 3
        revoked = store.revoke(credential_id, now=WHEN + timedelta(minutes=2), reason="lost")
        assert revoked is not None and revoked.revoked_at is not None
        assert store.get_by_credential_id(credential_id) is None
        kept = store.get_by_credential_id(credential_id, include_revoked=True)
        assert kept is not None and kept.revoke_reason == "lost"
        assert store.list_for_principal(principal_a) == ()
        assert store.list_for_principal(principal_a, include_revoked=True)


def test_challenges_consume_once_and_fail_closed(
    engine: Engine,
) -> None:
    principal = _seed_principal(engine)
    with engine.begin() as connection:
        store = WebAuthnChallengeStore(connection)
        issued = store.issue(
            purpose=WebAuthnChallengePurpose.AUTHENTICATION,
            rp_id=RP_ID,
            origin=ORIGIN,
            now=WHEN,
            principal_id=principal,
        )
        nonce = issued.challenge_bytes
        valid = store.get_valid(
            nonce,
            purpose=WebAuthnChallengePurpose.AUTHENTICATION,
            principal_id=principal,
            now=WHEN + timedelta(seconds=1),
        )
        assert valid is not None
        consumed = store.consume(
            nonce,
            purpose=WebAuthnChallengePurpose.AUTHENTICATION,
            principal_id=principal,
            now=WHEN + timedelta(seconds=2),
        )
        assert consumed is not None and consumed.consumed_at is not None
        replay = store.consume(
            nonce,
            purpose=WebAuthnChallengePurpose.AUTHENTICATION,
            principal_id=principal,
            now=WHEN + timedelta(seconds=3),
        )
        assert replay is None

    with engine.begin() as connection:
        store = WebAuthnChallengeStore(connection)
        expired = store.issue(
            purpose=WebAuthnChallengePurpose.REGISTRATION,
            rp_id=RP_ID,
            origin=ORIGIN,
            now=WHEN,
            principal_id=principal,
            ttl=timedelta(seconds=1),
        )
        assert (
            store.consume(
                expired.challenge_bytes,
                purpose=WebAuthnChallengePurpose.REGISTRATION,
                principal_id=principal,
                now=WHEN + timedelta(seconds=2),
            )
            is None
        )
        wrong_purpose = store.issue(
            purpose=WebAuthnChallengePurpose.STEP_UP,
            rp_id=RP_ID,
            origin=ORIGIN,
            now=WHEN,
            principal_id=principal,
        )
        assert (
            store.consume(
                wrong_purpose.challenge_bytes,
                purpose=WebAuthnChallengePurpose.AUTHENTICATION,
                principal_id=principal,
                now=WHEN + timedelta(seconds=1),
            )
            is None
        )
        bound = store.issue(
            purpose=WebAuthnChallengePurpose.AUTHENTICATION,
            rp_id=RP_ID,
            origin=ORIGIN,
            now=WHEN,
            principal_id=principal,
        )
        assert (
            store.consume(
                bound.challenge_bytes,
                purpose=WebAuthnChallengePurpose.AUTHENTICATION,
                principal_id=None,
                now=WHEN + timedelta(seconds=1),
            )
            is None
        )


def test_concurrent_challenge_consume_succeeds_once(engine: Engine) -> None:
    principal = _seed_principal(engine)
    with engine.begin() as connection:
        issued = WebAuthnChallengeStore(connection).issue(
            purpose=WebAuthnChallengePurpose.AUTHENTICATION,
            rp_id=RP_ID,
            origin=ORIGIN,
            now=WHEN,
            principal_id=principal,
        )
        nonce = issued.challenge_bytes

    def attempt() -> bool:
        with engine.begin() as connection:
            consumed = WebAuthnChallengeStore(connection).consume(
                nonce,
                purpose=WebAuthnChallengePurpose.AUTHENTICATION,
                principal_id=principal,
                now=WHEN + timedelta(seconds=1),
            )
            return consumed is not None

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = tuple(pool.map(lambda _item: attempt(), range(8)))
    assert outcomes.count(True) == 1
    with engine.begin() as connection:
        second = WebAuthnAuthPersistence(connection)
        assert (
            second.challenges.consume(
                nonce,
                purpose=WebAuthnChallengePurpose.AUTHENTICATION,
                principal_id=principal,
                now=WHEN + timedelta(seconds=2),
            )
            is None
        )


def test_recovery_codes_are_hashed_one_time_and_revocable(engine: Engine) -> None:
    principal = _seed_principal(engine)
    with engine.begin() as connection:
        store = RecoveryCodeStore(connection)
        issued = store.create_set(principal_id=principal, now=WHEN, code_count=3)
        assert len(issued.codes) == 3
        rows = connection.execute(
            recovery_codes.select().where(recovery_codes.c.set_id == issued.record.id)
        ).all()
        stored = {row.code_hash for row in rows}
        for code in issued.codes:
            assert code not in stored
            assert digest_text(normalize_recovery_code(code)) in stored
        first = issued.codes[0]
        consumed = store.consume_code(first, now=WHEN + timedelta(seconds=1))
        assert consumed is not None
        assert store.consume_code(first, now=WHEN + timedelta(seconds=2)) is None
        assert store.consume_code("ffff-ffff-ffff-ffff-ffff-ffff-ffff-ffff", now=WHEN) is None
        remaining = issued.codes[1]
        store.revoke_set(issued.record.id, now=WHEN + timedelta(seconds=3))
        assert store.consume_code(remaining, now=WHEN + timedelta(seconds=4)) is None


def test_concurrent_recovery_consume_succeeds_once(engine: Engine) -> None:
    principal = _seed_principal(engine)
    with engine.begin() as connection:
        issued = RecoveryCodeStore(connection).create_set(
            principal_id=principal, now=WHEN, code_count=1
        )
        code = issued.codes[0]

    def attempt() -> bool:
        with engine.begin() as connection:
            return RecoveryCodeStore(connection).consume_code(code, now=WHEN) is not None

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = tuple(pool.map(lambda _item: attempt(), range(8)))
    assert outcomes.count(True) == 1


def test_sessions_bind_principal_expire_rotate_and_revoke(engine: Engine) -> None:
    principal = _seed_principal(engine)
    other = _seed_principal(engine)
    with engine.begin() as connection:
        store = AuthSessionStore(connection)
        issued = store.create(principal_id=principal, now=WHEN)
        resolved = store.resolve(issued.raw_sid, now=WHEN + timedelta(minutes=1))
        assert resolved is not None
        assert resolved.principal_id == principal
        assert store.resolve("00" * 32, now=WHEN) is None
        idle_dead = store.create(
            principal_id=principal,
            now=WHEN,
            idle_ttl=timedelta(minutes=1),
            absolute_ttl=timedelta(hours=8),
        )
        assert store.resolve(idle_dead.raw_sid, now=WHEN + timedelta(minutes=2)) is None
        absolute_dead = store.create(
            principal_id=principal,
            now=WHEN,
            idle_ttl=timedelta(hours=1),
            absolute_ttl=timedelta(minutes=2),
        )
        assert store.resolve(absolute_dead.raw_sid, now=WHEN + timedelta(minutes=3)) is None
        long_lived = store.create(
            principal_id=principal,
            now=WHEN,
            idle_ttl=timedelta(minutes=30),
            absolute_ttl=timedelta(minutes=15),
        )
        assert long_lived.record.idle_expires_at == long_lived.record.absolute_expires_at
        touched = store.touch(
            long_lived.raw_sid,
            now=WHEN + timedelta(minutes=5),
            idle_ttl=timedelta(minutes=30),
        )
        assert touched is not None
        assert touched.idle_expires_at == long_lived.record.absolute_expires_at
        assert touched.absolute_expires_at == long_lived.record.absolute_expires_at
        rotated = store.rotate(issued.raw_sid, now=WHEN + timedelta(minutes=1))
        assert rotated is not None
        assert store.resolve(issued.raw_sid, now=WHEN + timedelta(minutes=1)) is None
        assert store.resolve(rotated.raw_sid, now=WHEN + timedelta(minutes=1)) is not None
        assert store.revoke(rotated.raw_sid, now=WHEN + timedelta(minutes=2))
        assert store.resolve(rotated.raw_sid, now=WHEN + timedelta(minutes=2)) is None
        live = store.create(principal_id=principal, now=WHEN)
        other_live = store.create(principal_id=other, now=WHEN)
        count = store.revoke_all_for_principal(principal, now=WHEN + timedelta(minutes=1))
        assert count >= 1
        assert store.resolve(live.raw_sid, now=WHEN + timedelta(minutes=1)) is None
        assert store.resolve(other_live.raw_sid, now=WHEN + timedelta(minutes=1)) is not None


def test_concurrent_rotation_creates_one_successor(engine: Engine) -> None:
    principal = _seed_principal(engine)
    with engine.begin() as connection:
        issued = AuthSessionStore(connection).create(principal_id=principal, now=WHEN)
        sid = issued.raw_sid

    def attempt() -> str | None:
        with engine.begin() as connection:
            rotated = AuthSessionStore(connection).rotate(sid, now=WHEN + timedelta(seconds=1))
            return None if rotated is None else rotated.raw_sid

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = tuple(pool.map(lambda _item: attempt(), range(8)))
    winners = [item for item in outcomes if item is not None]
    assert len(winners) == 1
    with engine.begin() as connection:
        store = AuthSessionStore(connection)
        assert store.resolve(sid, now=WHEN + timedelta(seconds=2)) is None
        assert store.resolve(winners[0], now=WHEN + timedelta(seconds=2)) is not None


def test_second_instance_observes_authoritative_state(engine: Engine) -> None:
    principal = _seed_principal(engine)
    with engine.begin() as connection:
        first = WebAuthnAuthPersistence(connection)
        session = first.sessions.create(principal_id=principal, now=WHEN)
        challenge = first.challenges.issue(
            purpose=WebAuthnChallengePurpose.AUTHENTICATION,
            rp_id=RP_ID,
            origin=ORIGIN,
            now=WHEN,
            principal_id=principal,
        )
        sid = session.raw_sid
        nonce = challenge.challenge_bytes
    with engine.begin() as connection:
        second = WebAuthnAuthPersistence(connection)
        resolved = second.sessions.resolve(sid, now=WHEN + timedelta(seconds=1))
        assert resolved is not None
        assert resolved.principal_id == principal
        consumed = second.challenges.consume(
            nonce,
            purpose=WebAuthnChallengePurpose.AUTHENTICATION,
            principal_id=principal,
            now=WHEN + timedelta(seconds=1),
        )
        assert consumed is not None
    with engine.begin() as connection:
        third = WebAuthnAuthPersistence(connection)
        assert (
            third.challenges.consume(
                nonce,
                purpose=WebAuthnChallengePurpose.AUTHENTICATION,
                principal_id=principal,
                now=WHEN + timedelta(seconds=2),
            )
            is None
        )


def test_malformed_and_rollback_leave_state_unchanged(engine: Engine) -> None:
    principal = _seed_principal(engine)
    with engine.begin() as connection:
        store = AuthSessionStore(connection)
        issued = store.create(principal_id=principal, now=WHEN)
        assert store.resolve("not-a-session", now=WHEN) is None
        assert store.resolve("", now=WHEN) is None
        sid = issued.raw_sid
    try:
        with engine.begin() as connection:
            WebAuthnCredentialStore(connection).create(
                principal_id=principal,
                credential_id=b"rollback-cred",
                public_key=b"key",
                now=WHEN,
            )
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass
    with engine.begin() as connection:
        credentials = WebAuthnCredentialStore(connection)
        assert credentials.get_by_credential_id(b"rollback-cred") is None
        assert AuthSessionStore(connection).resolve(sid, now=WHEN) is not None
        with pytest.raises(ValueError):
            credentials.create(
                principal_id=principal,
                credential_id=b"",
                public_key=b"key",
                now=WHEN,
            )


def test_credential_insert_without_principal_is_rejected(engine: Engine) -> None:
    missing = uuid4()
    with engine.begin() as connection:
        store = WebAuthnCredentialStore(connection)
        with pytest.raises(IntegrityError):
            store.create(
                principal_id=missing,
                credential_id=b"orphan",
                public_key=b"key",
                now=WHEN,
            )
