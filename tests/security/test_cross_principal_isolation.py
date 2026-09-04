"""Two synthetic Moss principals; zero leakage (MU-AC-01, MU-AC-04).

Database tier. The database is disposable, created and dropped by this
module's own fixture (the `test_foundation_migration.py` pattern), and every
identity is synthetic: one made-up Moss tenant, two invented `(tid, oid)`
pairs inside it.

The records used to prove isolation are `principal_scope_grants` rows — the
first per-Principal partition the campaign creates — read through the same
fail-closed guard every future partition will use. What is asserted is the
v4.0 gate for R0A (MU-AC-04): before any live data exists, an automated test
proves one Principal cannot read another's rows, in either direction, and
that list operations return zero foreign rows rather than filtered leftovers.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text

from my_pa.domain.identity.user_account import (
    ConsentState,
    ForeignTenantError,
    MissingClaimError,
    UserLifecycleState,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.principal_scope import (
    MissingPrincipalContextError,
    PrincipalContext,
    UnpartitionedTableError,
    principal_scoped,
)
from my_pa.infrastructure.persistence.user_accounts import (
    UserAccountRepository,
    principal_scope_grants,
    user_accounts,
)
from my_pa.infrastructure.security.principal_identity import PrincipalIdentityService

ROOT = Path(__file__).resolve().parents[2]
DATABASE = "my_pa_principal_isolation_test"
MOSS_TENANT = "11111111-2222-3333-4444-555555555555"
FOREIGN_TENANT = "99999999-8888-7777-6666-555555555555"
WHEN = datetime(2026, 8, 5, 12, tzinfo=UTC)

PRINCIPAL_A_CLAIMS: dict[str, object] = {
    "tid": MOSS_TENANT,
    "oid": "aaaa0001-0000-0000-0000-000000000001",
    "upn": "synthetic.a@moss.example",
    "name": "Synthetic A",
}
PRINCIPAL_B_CLAIMS: dict[str, object] = {
    "tid": MOSS_TENANT,
    "oid": "bbbb0002-0000-0000-0000-000000000002",
    "upn": "synthetic.b@moss.example",
    "name": "Synthetic B",
}


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def engine(db_engine: Engine) -> Engine:
    return db_engine


@pytest.fixture
def service() -> PrincipalIdentityService:
    return PrincipalIdentityService(home_tenant_id=MOSS_TENANT)


pytestmark = pytest.mark.database


@pytest.mark.migration_edge
def test_the_identity_revision_round_trips_from_empty(empty_database_url: str) -> None:
    """The identity schema upgrades from empty to head and downgrades back."""
    engine = create_database_engine(empty_database_url)
    try:
        command.upgrade(_config(), "head")
        with engine.connect() as connection:
            schemas = set(connection.execute(text("SELECT nspname FROM pg_namespace")).scalars())
            assert "identity" in schemas
            tables = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables"
                        " WHERE table_schema = 'identity'"
                    )
                ).scalars()
            )
            assert tables == {
                "user_accounts",
                "principal_scope_grants",
                "remote_clients",
                "remote_capability_grants",
                "remote_security_controls",
                "oauth_authorization_codes",
                "oauth_access_tokens",
                "oauth_refresh_token_families",
                "oauth_refresh_tokens",
                "webauthn_credentials",
                "webauthn_challenges",
                "recovery_code_sets",
                "recovery_codes",
                "auth_sessions",
            }
        command.downgrade(_config(), "base")
        with engine.connect() as connection:
            schemas = set(connection.execute(text("SELECT nspname FROM pg_namespace")).scalars())
            assert "identity" not in schemas
    finally:
        engine.dispose()


def test_two_moss_principals_resolve_to_distinct_stable_principals(
    engine: Engine, service: PrincipalIdentityService
) -> None:
    """Same Moss tenant, different `oid` — two accounts; retry changes nothing."""
    with engine.begin() as connection:
        first_a = service.authenticate(connection, claims=PRINCIPAL_A_CLAIMS, now=WHEN)
        first_b = service.authenticate(connection, claims=PRINCIPAL_B_CLAIMS, now=WHEN)
        retry_a = service.authenticate(connection, claims=PRINCIPAL_A_CLAIMS, now=WHEN)

    assert first_a.account.principal_id != first_b.account.principal_id
    assert retry_a.account.principal_id == first_a.account.principal_id
    assert retry_a.account.first_seen_at == first_a.account.first_seen_at
    assert first_a.account.lifecycle_state is UserLifecycleState.ACTIVE
    assert first_a.account.consent_state is ConsentState.PENDING
    assert first_a.account.home_tenant_verified is True


def test_concurrent_first_sign_ins_mint_exactly_one_principal(
    engine: Engine, service: PrincipalIdentityService
) -> None:
    """The `(tid, oid)` constraint, not a check, closes the duplicate window."""

    def _authenticate(_: int) -> object:
        with engine.begin() as connection:
            return service.authenticate(
                connection, claims=PRINCIPAL_A_CLAIMS, now=WHEN
            ).account.principal_id

    with ThreadPoolExecutor(max_workers=4) as pool:
        principal_ids = set(pool.map(_authenticate, range(8)))
    assert len(principal_ids) == 1


def test_principal_a_records_are_illegible_to_principal_b_and_vice_versa(
    engine: Engine, service: PrincipalIdentityService
) -> None:
    """MU-AC-01/MU-AC-04: creation on one side is invisible from the other."""
    with engine.begin() as connection:
        a = service.authenticate(connection, claims=PRINCIPAL_A_CLAIMS, now=WHEN)
        b = service.authenticate(connection, claims=PRINCIPAL_B_CLAIMS, now=WHEN)
        repository = UserAccountRepository(connection)

        # Principal A creates a record; Principal B creates a record.
        a_grant = repository.record_scope_grant(
            a.context, scope="Mail.Read", consent_type="user", now=WHEN
        )
        b_grant = repository.record_scope_grant(
            b.context, scope="Calendars.Read", consent_type="user", now=WHEN
        )

        # A reads only A's record; B reads only B's record.
        a_reads = repository.scope_grants(a.context)
        b_reads = repository.scope_grants(b.context)

    assert [grant.id for grant in a_reads] == [a_grant.id]
    assert [grant.id for grant in b_reads] == [b_grant.id]
    # Zero of the other's records appear in either list, in either direction.
    assert all(grant.principal_id == a.context.principal_id for grant in a_reads)
    assert all(grant.principal_id == b.context.principal_id for grant in b_reads)
    assert b_grant.id not in {grant.id for grant in a_reads}
    assert a_grant.id not in {grant.id for grant in b_reads}


def test_list_operations_return_zero_foreign_rows_not_filtered_leftovers(
    engine: Engine, service: PrincipalIdentityService
) -> None:
    """A Principal with no records lists nothing, however many others have."""
    with engine.begin() as connection:
        a = service.authenticate(connection, claims=PRINCIPAL_A_CLAIMS, now=WHEN)
        b = service.authenticate(connection, claims=PRINCIPAL_B_CLAIMS, now=WHEN)
        repository = UserAccountRepository(connection)
        for scope in ("Mail.Read", "Calendars.Read", "Contacts.Read"):
            repository.record_scope_grant(a.context, scope=scope, consent_type="user", now=WHEN)

        assert repository.scope_grants(b.context) == ()
        assert len(repository.scope_grants(a.context)) == 3

        # The account view is equally partitioned: B's scoped account read
        # resolves to B, never to A, and carries B's identity claims.
        b_account = repository.account_for(b.context)
    assert b_account is not None
    assert b_account.oid == PRINCIPAL_B_CLAIMS["oid"]


def test_a_non_moss_tenant_is_rejected_before_any_account_exists(
    engine: Engine, service: PrincipalIdentityService
) -> None:
    """MU-AC-03: the foreign tenant is denied and the registry stays empty."""
    foreign_claims = dict(PRINCIPAL_A_CLAIMS, tid=FOREIGN_TENANT)
    with engine.begin() as connection:
        with pytest.raises(ForeignTenantError):
            service.authenticate(connection, claims=foreign_claims, now=WHEN)
        accounts = connection.execute(select(user_accounts.c.id)).all()
    assert accounts == []


def test_missing_and_invalid_claims_are_rejected(
    engine: Engine, service: PrincipalIdentityService
) -> None:
    incomplete = {key: value for key, value in PRINCIPAL_A_CLAIMS.items() if key != "oid"}
    with engine.begin() as connection:
        with pytest.raises(MissingClaimError):
            service.authenticate(connection, claims=incomplete, now=WHEN)
        with pytest.raises(MissingClaimError):
            service.authenticate(connection, claims={"tid": MOSS_TENANT, "oid": "  "}, now=WHEN)
        accounts = connection.execute(select(user_accounts.c.id)).all()
    assert accounts == []


def test_a_caller_supplied_principal_id_in_the_body_is_rejected(
    engine: Engine, service: PrincipalIdentityService
) -> None:
    """MU-AC-02: only token-derived identity is accepted on the write path."""
    from my_pa.domain.identity.user_account import CallerSuppliedPrincipalError

    with engine.begin() as connection:
        b = service.authenticate(connection, claims=PRINCIPAL_B_CLAIMS, now=WHEN)
        with pytest.raises(CallerSuppliedPrincipalError):
            service.authenticate(
                connection,
                claims=PRINCIPAL_A_CLAIMS,
                payload={"principal_id": str(b.account.principal_id)},
                now=WHEN,
            )
        with pytest.raises(CallerSuppliedPrincipalError):
            service.authenticate(
                connection,
                claims=PRINCIPAL_A_CLAIMS,
                payload={"metadata": {"principal_id": str(b.account.principal_id)}},
                now=WHEN,
            )


def test_data_access_without_principal_context_is_denied(engine: Engine) -> None:
    """Fail closed: absent context denies; an unpartitioned table refuses."""
    with engine.connect() as connection:
        repository = UserAccountRepository(connection)
        with pytest.raises(MissingPrincipalContextError):
            repository.scope_grants(None)
        with pytest.raises(MissingPrincipalContextError):
            repository.account_for(None)
        with pytest.raises(MissingPrincipalContextError):
            repository.record_scope_grant(None, scope="Mail.Read", consent_type="user", now=WHEN)


def test_the_guard_refuses_a_table_without_a_principal_partition() -> None:
    """`principal_id`-less tables are unreachable through the scoped path."""
    from sqlalchemy import Column, Integer, MetaData, Table

    unpartitioned = Table("unpartitioned", MetaData(), Column("id", Integer, primary_key=True))
    context = PrincipalContext(principal_id=__import__("uuid").uuid4())
    with pytest.raises(UnpartitionedTableError):
        principal_scoped(select(unpartitioned.c.id), unpartitioned, context)


def test_the_grant_table_binds_every_row_to_a_registered_principal(
    engine: Engine, service: PrincipalIdentityService
) -> None:
    """Structural half of MU-AC-01: a grant cannot name an unknown Principal."""
    from uuid import uuid4

    from sqlalchemy.exc import IntegrityError

    with engine.connect() as connection, pytest.raises(IntegrityError):
        connection.execute(
            principal_scope_grants.insert().values(
                id=uuid4(),
                principal_id=uuid4(),  # registered nowhere
                scope="Mail.Read",
                consent_type="user",
                consented_at=WHEN,
                revoked_at=None,
            )
        )
