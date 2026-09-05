"""Canvas workspace table and audit vocabulary (UI-IMP-WP17)."""

from __future__ import annotations

import ast
import io
from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from my_pa.bootstrap.gateway import local_principal
from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
REVISION: Final = "d4e8b1c7a902"
PREVIOUS: Final = "6a2f9d1c4b80"
MIGRATION: Final = ROOT / "migrations/versions/20260905_d4e8b1c7a902_add_canvas_workspaces.py"
TABLE: Final = "canvas_workspaces"
ADMITTED_CAPABILITIES: Final[tuple[str, ...]] = (
    "canvas.workspace.get",
    "canvas.workspace.put",
)
ADMITTED_PURPOSES: Final[tuple[str, ...]] = (
    "canvas_workspace_authoring",
    "canvas_workspace_read",
)
SETTLED_CAPABILITY: Final = "capabilities.get"
SETTLED_PURPOSE: Final = "status_observation"
PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
FOCUS: Final = "ent_canvas0001canvas0001canvas00"
WHEN: Final = datetime(2026, 9, 5, 12, tzinfo=UTC)
POLICY_VERSION: Final = "policy-v1"
_ROWS = count(1)


def _config(buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


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


def _index() -> str:
    return f"{next(_ROWS):016x}"


def _audit(engine: Engine, *, capability: str, purpose: str) -> None:
    index = _index()
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.audit_events "  # noqa: S608
                "(audit_id, correlation_id, principal_id, capability, purpose, outcome, "
                " policy_version, scope_source_id_count, recorded_at) "
                "VALUES (:audit_id, :correlation_id, :principal_id, :capability, :purpose, "
                " 'allowed', :policy_version, 0, :recorded_at)"
            ),
            {
                "audit_id": f"audit_{index}",
                "correlation_id": f"corr_{index}",
                "principal_id": PRINCIPAL_A,
                "capability": capability,
                "purpose": purpose,
                "policy_version": POLICY_VERSION,
                "recorded_at": WHEN,
            },
        )


def test_revision_is_the_only_linear_head() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_revision_is_frozen_and_does_not_import_live_schema_or_enums() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    imported = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "my_pa.infrastructure.persistence.tables" not in imported
    assert not any(module.startswith("my_pa.domain") for module in imported)
    assert imported <= {"alembic", "typing", "__future__"}
    for value in (*ADMITTED_CAPABILITIES, *ADMITTED_PURPOSES):
        assert value in source


def test_offline_upgrade_emits_the_table_and_seed_unique(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    output = io.StringIO()
    command.upgrade(_config(output), "head", sql=True)
    sql = output.getvalue()
    assert f"CREATE TABLE knowledge.{TABLE}" in sql
    assert "UNIQUE NULLS NOT DISTINCT (principal_id, focus_entity_id, scope_entity_id)" in sql
    assert "canvas.workspace.get" in sql
    assert "canvas_workspace_authoring" in sql


def test_the_table_accepts_the_canonical_local_principal_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    output = io.StringIO()
    command.upgrade(_config(output), "head", sql=True)
    sql = output.getvalue()
    canvas_sql = sql[sql.index(f"CREATE TABLE knowledge.{TABLE}") :]
    assert local_principal().principal_id
    assert "principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'" in canvas_sql


@pytest.mark.database
def test_upgrade_creates_the_table(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        names = set(
            connection.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = :schema AND tablename = :table"
                ),
                {"schema": SCHEMA, "table": TABLE},
            ).scalars()
        )
    assert names == {TABLE}


@pytest.mark.database
def test_one_workspace_per_principal_and_seed(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.{TABLE} "  # noqa: S608
                "(principal_id, focus_entity_id, scope_entity_id, version, positions, "
                " created_at, updated_at) "
                "VALUES (:principal_id, :focus, NULL, 1, CAST(:positions AS jsonb), :when, :when)"
            ),
            {"principal_id": PRINCIPAL_A, "focus": FOCUS, "when": WHEN, "positions": "{}"},
        )
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.{TABLE} "  # noqa: S608
                "(principal_id, focus_entity_id, scope_entity_id, version, positions, "
                " created_at, updated_at) "
                "VALUES (:principal_id, :focus, NULL, 1, CAST(:positions AS jsonb), :when, :when)"
            ),
            {"principal_id": PRINCIPAL_A, "focus": FOCUS, "when": WHEN, "positions": "{}"},
        )
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.{TABLE} "  # noqa: S608
                "(principal_id, focus_entity_id, scope_entity_id, version, positions, "
                " created_at, updated_at) "
                "VALUES (:principal_id, :focus, NULL, 1, CAST(:positions AS jsonb), :when, :when)"
            ),
            {"principal_id": PRINCIPAL_B, "focus": FOCUS, "when": WHEN, "positions": "{}"},
        )


@pytest.mark.database
def test_head_admits_the_canvas_vocabulary(migrated_engine: Engine) -> None:
    _audit(migrated_engine, capability=ADMITTED_CAPABILITIES[0], purpose=ADMITTED_PURPOSES[1])
    _audit(migrated_engine, capability=ADMITTED_CAPABILITIES[1], purpose=ADMITTED_PURPOSES[0])


@pytest.mark.database
def test_downgrade_restores_the_previous_vocabulary(migrated_engine: Engine) -> None:
    command.downgrade(_config(), PREVIOUS)
    _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=SETTLED_PURPOSE)
    with pytest.raises(IntegrityError) as capability_refusal:
        _audit(migrated_engine, capability=ADMITTED_CAPABILITIES[0], purpose=SETTLED_PURPOSE)
    assert "capability_is_known" in str(capability_refusal.value)
    with pytest.raises(IntegrityError) as purpose_refusal:
        _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=ADMITTED_PURPOSES[0])
    assert "purpose_is_known" in str(purpose_refusal.value)
    command.upgrade(_config(), "head")
    _audit(migrated_engine, capability=ADMITTED_CAPABILITIES[0], purpose=ADMITTED_PURPOSES[1])
