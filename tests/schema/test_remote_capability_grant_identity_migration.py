"""`7a5c4e9d2b61` narrows grant uniqueness to unrevoked rows.

The legacy `one_remote_capability_grant` UNIQUE constraint spans every grant
row, so a revoked grant permanently occupies the canonical identity. The new
partial unique index admits revoked history beside one active replacement and
treats `purpose IS NULL` as a value (`NULLS NOT DISTINCT`). Duplicate unrevoked
identities refuse the upgrade with no row mutation.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID
from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "7a5c4e9d2b61"
CURRENT_HEAD: Final = "7a5c4e9d2b61"
PREVIOUS: Final = "6f6ead27d122"
MIGRATION: Final = (
    ROOT / "migrations/versions/20260923_7a5c4e9d2b61_remote_grant_unrevoked_identity.py"
)
CONSTRAINT: Final = "one_remote_capability_grant"
INDEX: Final = "uq_remote_capability_grants_unrevoked_identity"
WHEN: Final = datetime(2026, 9, 23, 12, tzinfo=UTC)
PRINCIPAL_ID: Final = "10000000-0000-4000-8000-000000000001"
CLIENT_ID: Final = "20000000-0000-4000-8000-000000000001"
GRANT_A: Final = "30000000-0000-4000-8000-000000000001"
GRANT_B: Final = "30000000-0000-4000-8000-000000000002"
GRANT_C: Final = "30000000-0000-4000-8000-000000000003"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    return empty_database_url


@pytest.fixture
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def _seed_client(engine: Engine) -> None:
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
                "id": PRINCIPAL_ID,
                "principal_id": LOCAL_OPERATOR_UUID,
                "subject": f"synthetic:{LOCAL_OPERATOR_UUID}",
                "tid": "synthetic-tenant",
                "oid": "synthetic-object",
                "now": WHEN,
            },
        )
        connection.execute(
            text(
                "INSERT INTO identity.remote_clients "
                "(id, principal_id, oauth_client_id, client_name, redirect_uris, "
                " registered_scopes, enabled, writes_enabled, created_at) "
                "VALUES (:id, :principal_id, 'synthetic-client', 'synthetic', '[]', "
                " 'my-pa.read', true, false, now())"
            ),
            {"id": CLIENT_ID, "principal_id": LOCAL_OPERATOR_UUID},
        )


def _grant(
    engine: Engine,
    *,
    grant_id: str,
    capability: str,
    purpose: str | None,
    revoked_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO identity.remote_capability_grants "
                "(id, remote_client_id, external_scope, capability, capability_version, "
                " purpose, resource, is_write, expires_at, revoked_at, created_at) "
                "VALUES (:id, :client_id, 'my-pa.read', :capability, 'v1', :purpose, "
                " 'https://my-pa.example/mcp', false, :expires_at, :revoked_at, now())"
            ),
            {
                "id": grant_id,
                "client_id": CLIENT_ID,
                "capability": capability,
                "purpose": purpose,
                "expires_at": expires_at,
                "revoked_at": revoked_at,
            },
        )


def _constraint_present(engine: Engine) -> bool:
    with engine.connect() as connection:
        return (
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE conname = :name AND connamespace = "
                    "(SELECT oid FROM pg_namespace WHERE nspname = 'identity')"
                ),
                {"name": CONSTRAINT},
            ).scalar_one()
            > 0
        )


def _index_row(engine: Engine) -> tuple[bool, bool, str | None]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT i.indisunique, i.indnullsnotdistinct, pg_get_indexdef(i.indexrelid) "
                "FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relname = :name AND n.nspname = 'identity'"
            ),
            {"name": INDEX},
        ).one_or_none()
    if row is None:
        return False, False, None
    return bool(row[0]), bool(row[1]), str(row[2])


def test_revision_is_the_only_linear_head() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_revision_is_frozen_and_does_not_import_live_schema_or_enums() -> None:
    import ast

    source = MIGRATION.read_text(encoding="utf-8")
    imported = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "my_pa.infrastructure.persistence.tables" not in imported
    assert not any(module.startswith("my_pa.domain") for module in imported)
    assert imported <= {"alembic", "sqlalchemy", "typing", "__future__"}
    assert "NULLS NOT DISTINCT WHERE revoked_at IS NULL" in source
    assert "DROP CONSTRAINT one_remote_capability_grant" in source


@pytest.mark.migration
@pytest.mark.migration_edge
@pytest.mark.database
def test_upgrade_replaces_the_all_history_unique_with_the_partial_index(
    migrated_engine: Engine,
) -> None:
    assert not _constraint_present(migrated_engine)
    unique, nulls_not_distinct, definition = _index_row(migrated_engine)
    assert unique is True
    assert nulls_not_distinct is True
    assert definition is not None
    assert "WHERE (revoked_at IS NULL)" in definition


@pytest.mark.migration
@pytest.mark.migration_edge
@pytest.mark.database
def test_revoked_history_and_a_new_active_replacement_coexist(migrated_engine: Engine) -> None:
    _seed_client(migrated_engine)
    _grant(
        migrated_engine,
        grant_id=GRANT_A,
        capability="tasks.list",
        purpose="task_read",
        revoked_at=WHEN,
    )
    _grant(
        migrated_engine,
        grant_id=GRANT_B,
        capability="tasks.list",
        purpose="task_read",
    )
    with migrated_engine.connect() as connection:
        count = connection.execute(
            text(
                "SELECT count(*) FROM identity.remote_capability_grants "
                "WHERE capability = 'tasks.list'"
            )
        ).scalar_one()
    assert count == 2


@pytest.mark.migration
@pytest.mark.migration_edge
@pytest.mark.database
def test_duplicate_unrevoked_identity_refuses_upgrade_without_mutation(
    disposable_database: str,
) -> None:
    command.upgrade(_config(), PREVIOUS)
    engine = create_database_engine(disposable_database)
    try:
        _seed_client(engine)
        _grant(engine, grant_id=GRANT_A, capability="tasks.list", purpose=None)
        _grant(engine, grant_id=GRANT_B, capability="tasks.list", purpose=None)
        with pytest.raises(
            RuntimeError,
            match=(
                "duplicate unrevoked remote capability grants require explicit operator resolution"
            ),
        ):
            command.upgrade(_config(), REVISION)
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == PREVIOUS
            )
            rows = connection.execute(
                text(
                    "SELECT id::text, capability, purpose, revoked_at "
                    "FROM identity.remote_capability_grants ORDER BY id::text"
                )
            ).all()
            assert [tuple(row) for row in rows] == [
                (GRANT_A, "tasks.list", None, None),
                (GRANT_B, "tasks.list", None, None),
            ]
            assert _constraint_present(engine)
    finally:
        engine.dispose()


@pytest.mark.migration
@pytest.mark.migration_edge
@pytest.mark.database
def test_two_unrevoked_purpose_null_identical_identities_are_rejected_after_upgrade(
    migrated_engine: Engine,
) -> None:
    _seed_client(migrated_engine)
    _grant(migrated_engine, grant_id=GRANT_A, capability="tasks.list", purpose=None)
    with pytest.raises(IntegrityError):
        _grant(migrated_engine, grant_id=GRANT_B, capability="tasks.list", purpose=None)


@pytest.mark.migration
@pytest.mark.migration_edge
@pytest.mark.database
def test_downgrade_restores_the_legacy_unique(migrated_engine: Engine) -> None:
    _seed_client(migrated_engine)
    _grant(migrated_engine, grant_id=GRANT_A, capability="tasks.list", purpose="task_read")
    command.downgrade(_config(), PREVIOUS)
    assert _constraint_present(migrated_engine)
    assert not _index_row(migrated_engine)[2]
    with pytest.raises(IntegrityError):
        _grant(migrated_engine, grant_id=GRANT_B, capability="tasks.list", purpose="task_read")
    command.upgrade(_config(), "head")


@pytest.mark.migration
@pytest.mark.migration_edge
@pytest.mark.database
def test_downgrade_guard_is_non_destructive_on_historical_duplicates(
    migrated_engine: Engine,
) -> None:
    _seed_client(migrated_engine)
    _grant(
        migrated_engine,
        grant_id=GRANT_A,
        capability="tasks.list",
        purpose="task_read",
        revoked_at=WHEN,
    )
    _grant(
        migrated_engine,
        grant_id=GRANT_B,
        capability="tasks.list",
        purpose="task_read",
        revoked_at=WHEN,
    )
    with pytest.raises(
        RuntimeError,
        match="duplicate all-history grant identities require explicit operator resolution",
    ):
        command.downgrade(_config(), PREVIOUS)
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == CURRENT_HEAD
        )
        rows = connection.execute(
            text(
                "SELECT id::text, capability, purpose, revoked_at "
                "FROM identity.remote_capability_grants ORDER BY id::text"
            )
        ).all()
        assert [tuple(row) for row in rows] == [
            (GRANT_A, "tasks.list", "task_read", WHEN),
            (GRANT_B, "tasks.list", "task_read", WHEN),
        ]


@pytest.mark.migration_empty_to_head
@pytest.mark.database
def test_an_empty_database_upgrades_to_the_new_head(disposable_database: str) -> None:
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)
    try:
        with engine.connect() as connection:
            stamped = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert stamped == CURRENT_HEAD
    finally:
        engine.dispose()
