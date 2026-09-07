"""Isolated PostgreSQL proofs for auth grants, local identity, and state."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text

from my_pa.domain.identity.auth_grants import AUTH_GRANT_TTL, AuthGrantPurpose
from my_pa.domain.identity.auth_state import AuthStateKind, AuthStateReason
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.domain.identity.user_account import (
    SYNTHETIC_TENANT_ID,
    AccountIdentityProvider,
    EntraTokenClaims,
)
from my_pa.domain.identity.webauthn_credentials import WebAuthnChallengePurpose
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.auth_grants import AuthGrantStore
from my_pa.infrastructure.persistence.auth_state import AuthStateValidator
from my_pa.infrastructure.persistence.user_accounts import UserAccountRepository
from my_pa.infrastructure.persistence.webauthn_auth import (
    WebAuthnChallengeStore,
    WebAuthnCredentialStore,
)

pytestmark = pytest.mark.database

WHEN = datetime(2026, 9, 7, 12, tzinfo=UTC)


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        yield engine
    finally:
        engine.dispose()


def _counts(engine: Engine) -> tuple[int, int, int]:
    with engine.connect() as connection:
        accounts = connection.execute(
            text("SELECT count(*) FROM identity.user_accounts")
        ).scalar_one()
        credentials = connection.execute(
            text("SELECT count(*) FROM identity.webauthn_credentials")
        ).scalar_one()
        grants = connection.execute(text("SELECT count(*) FROM identity.auth_grants")).scalar_one()
    return int(accounts), int(credentials), int(grants)


def test_one_live_grant_per_purpose_and_expired_row_is_retired(engine: Engine) -> None:
    with engine.begin() as connection:
        store = AuthGrantStore(connection)
        first = store.issue(AuthGrantPurpose.BOOTSTRAP, now=WHEN)
        assert first.record.exchanged_at is None
        assert len(first.raw_grant) == 64
        with pytest.raises(ValueError, match="unconsumed grant already exists"):
            store.issue(AuthGrantPurpose.BOOTSTRAP, now=WHEN)
        exchanged = store.exchange(first.raw_grant, AuthGrantPurpose.BOOTSTRAP, now=WHEN)
        assert exchanged is not None and exchanged.exchanged_at == WHEN
        with pytest.raises(ValueError, match="unconsumed grant already exists"):
            store.issue(AuthGrantPurpose.BOOTSTRAP, now=WHEN + timedelta(minutes=1))
    later = WHEN + AUTH_GRANT_TTL + timedelta(minutes=1)
    with engine.begin() as connection:
        store = AuthGrantStore(connection)
        replacement = store.issue(AuthGrantPurpose.BOOTSTRAP, now=later, ttl=timedelta(minutes=5))
        assert replacement.record.id != first.record.id
        retired = store.get_by_raw(first.raw_grant, AuthGrantPurpose.BOOTSTRAP, now=later)
        assert retired is not None
        assert retired.revoked_at == later
        assert retired.revoke_reason == "expired"
        assert store.active(AuthGrantPurpose.BOOTSTRAP, now=later) is not None


def test_exchange_then_consume_and_replays_fail(engine: Engine) -> None:
    with engine.begin() as connection:
        store = AuthGrantStore(connection)
        issued = store.issue(AuthGrantPurpose.BOOTSTRAP, now=WHEN)
        assert store.consume(issued.raw_grant, AuthGrantPurpose.BOOTSTRAP, now=WHEN) is None
        exchanged = store.exchange(issued.raw_grant, AuthGrantPurpose.BOOTSTRAP, now=WHEN)
        assert exchanged is not None
        assert store.exchange(issued.raw_grant, AuthGrantPurpose.BOOTSTRAP, now=WHEN) is None
        consumed = store.consume(
            issued.raw_grant, AuthGrantPurpose.BOOTSTRAP, now=WHEN + timedelta(minutes=1)
        )
        assert consumed is not None
        assert consumed.consumed_at == WHEN + timedelta(minutes=1)
        assert consumed.exchanged_at == WHEN
        assert store.consume(issued.raw_grant, AuthGrantPurpose.BOOTSTRAP, now=WHEN) is None
        assert store.active(AuthGrantPurpose.BOOTSTRAP, now=WHEN) is None


def test_resolve_or_create_local_is_idempotent_and_fails_closed_on_collision(
    engine: Engine,
) -> None:
    with engine.begin() as connection:
        repository = UserAccountRepository(connection)
        first = repository.resolve_or_create_local(now=WHEN)
        assert first.principal_id == LOCAL_OPERATOR_UUID
        assert first.identity_provider is AccountIdentityProvider.LOCAL
        assert first.tid is None and first.oid is None
        second = repository.resolve_or_create_local(now=WHEN + timedelta(minutes=1))
        assert second.id == first.id
        assert second.principal_id == first.principal_id
        entra = repository.resolve_or_create(
            EntraTokenClaims(tid="tenant-a", oid="object-a"), now=WHEN
        )
        assert entra.identity_provider is AccountIdentityProvider.ENTRA
        synthetic = repository.resolve_or_create(
            EntraTokenClaims(tid=SYNTHETIC_TENANT_ID, oid="object-s"), now=WHEN
        )
        assert synthetic.identity_provider is AccountIdentityProvider.SYNTHETIC
        assert synthetic.principal_id != first.principal_id
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM identity.user_accounts"))
        connection.execute(
            text(
                "INSERT INTO identity.user_accounts "
                "(id, principal_id, identity_provider, identity_subject, tid, oid, "
                " first_seen_at, consent_state, lifecycle_state) "
                "VALUES (:id, :principal_id, 'entra', :subject, :tid, :oid, "
                " :now, 'pending', 'active')"
            ),
            {
                "id": uuid4(),
                "principal_id": LOCAL_OPERATOR_UUID,
                "subject": "tenant-collision:object-collision",
                "tid": "tenant-collision",
                "oid": "object-collision",
                "now": WHEN,
            },
        )
        repository = UserAccountRepository(connection)
        with pytest.raises(ValueError, match="stored local account binding is inconsistent"):
            repository.resolve_or_create_local(now=WHEN)


def test_auth_state_validator_classifies_without_repair(engine: Engine) -> None:
    before = _counts(engine)
    with engine.begin() as connection:
        empty = AuthStateValidator(connection).inspect(now=WHEN)
    assert empty.kind is AuthStateKind.UNINITIALIZED
    assert empty.reasons == (AuthStateReason.BOOTSTRAP_REQUIRED,)
    assert _counts(engine) == before

    with engine.begin() as connection:
        local = UserAccountRepository(connection).resolve_or_create_local(now=WHEN)
        local_only = AuthStateValidator(connection).inspect(now=WHEN)
    assert local.principal_id == LOCAL_OPERATOR_UUID
    assert local_only.kind is AuthStateKind.UNINITIALIZED
    assert AuthStateReason.LOCAL_ACCOUNT_WITHOUT_CREDENTIAL not in local_only.reasons
    after_local = _counts(engine)

    with engine.begin() as connection:
        WebAuthnCredentialStore(connection).create(
            principal_id=LOCAL_OPERATOR_UUID,
            credential_id=b"cred-local",
            public_key=b"cose-local",
            now=WHEN,
        )
        ready = AuthStateValidator(connection).inspect(now=WHEN)
    assert ready.kind is AuthStateKind.READY
    assert ready.reasons == (AuthStateReason.READY,)
    assert ready.active_credential_count == 1
    assert _counts(engine)[1] == after_local[1] + 1

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM identity.webauthn_credentials"))
        connection.execute(
            text("DELETE FROM identity.user_accounts WHERE principal_id = :principal"),
            {"principal": LOCAL_OPERATOR_UUID},
        )
        foreign = UserAccountRepository(connection).resolve_or_create(
            EntraTokenClaims(tid="tenant-foreign", oid="object-foreign"), now=WHEN
        )
        WebAuthnCredentialStore(connection).create(
            principal_id=foreign.principal_id,
            credential_id=b"cred-foreign",
            public_key=b"cose-foreign",
            now=WHEN,
        )
        before_inspect = _counts(engine)
        inconsistent = AuthStateValidator(connection).inspect(now=WHEN)
    assert inconsistent.kind is AuthStateKind.INCONSISTENT
    assert AuthStateReason.FOREIGN_ACTIVE_CREDENTIAL in inconsistent.reasons
    assert _counts(engine) == before_inspect
    with engine.connect() as connection:
        remaining = connection.execute(
            text("SELECT principal_id FROM identity.webauthn_credentials")
        ).scalar_one()
        assert remaining == foreign.principal_id
        assert remaining != LOCAL_OPERATOR_UUID


def test_webauthn_challenge_persists_auth_grant_id(engine: Engine) -> None:
    with engine.begin() as connection:
        grant = AuthGrantStore(connection).issue(AuthGrantPurpose.BOOTSTRAP, now=WHEN)
        exchanged = AuthGrantStore(connection).exchange(
            grant.raw_grant, AuthGrantPurpose.BOOTSTRAP, now=WHEN
        )
        assert exchanged is not None
        issued = WebAuthnChallengeStore(connection).issue(
            purpose=WebAuthnChallengePurpose.BOOTSTRAP_REGISTRATION,
            rp_id="my-pa.example",
            origin="https://my-pa.example",
            now=WHEN,
            auth_grant_id=exchanged.id,
        )
        assert issued.record.auth_grant_id == exchanged.id
        loaded = WebAuthnChallengeStore(connection).get_valid(
            issued.challenge_bytes,
            purpose=WebAuthnChallengePurpose.BOOTSTRAP_REGISTRATION,
            principal_id=None,
            now=WHEN,
        )
        assert loaded is not None
        assert loaded.auth_grant_id == exchanged.id
