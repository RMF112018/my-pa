"""Admit GoodNotes browser query/read/correct vocabulary (UI-IMP-WP21)."""

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

from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
REVISION: Final = "a1c9e4b72f80"
PREVIOUS: Final = "2774329487be"
MIGRATION: Final = (
    ROOT / "migrations/versions/20260906_a1c9e4b72f80_admit_goodnotes_browser_contracts.py"
)
ADMITTED_CAPABILITIES: Final[tuple[str, ...]] = (
    "goodnotes.notebooks.list",
    "goodnotes.pages.list",
    "goodnotes.runs.list",
    "goodnotes.read",
    "goodnotes.search",
    "goodnotes.correct",
)
ADMITTED_PURPOSES: Final[tuple[str, ...]] = (
    "goodnotes_browse",
    "goodnotes_read",
    "goodnotes_correction",
)
SETTLED_CAPABILITY: Final = "capabilities.get"
SETTLED_PURPOSE: Final = "status_observation"
PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
WHEN: Final = datetime(2026, 9, 6, 12, tzinfo=UTC)
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


@pytest.mark.database
def test_head_admits_the_browser_vocabulary(migrated_engine: Engine) -> None:
    _audit(migrated_engine, capability=ADMITTED_CAPABILITIES[0], purpose=ADMITTED_PURPOSES[0])
    _audit(migrated_engine, capability=ADMITTED_CAPABILITIES[3], purpose=ADMITTED_PURPOSES[1])
    _audit(migrated_engine, capability=ADMITTED_CAPABILITIES[5], purpose=ADMITTED_PURPOSES[2])


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
    _audit(migrated_engine, capability=ADMITTED_CAPABILITIES[0], purpose=ADMITTED_PURPOSES[0])
