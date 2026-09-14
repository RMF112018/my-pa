"""R01-WP03 Project ownership, Capture scope, and settings-history integrity."""

from __future__ import annotations

import ast
import io
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, ForeignKeyConstraint, UniqueConstraint, insert, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError

from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import (
    captures,
    constraint_categories,
    constraint_project_settings,
    constraint_project_settings_history,
    project_constraints,
    tasks,
)

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "e6a4c2f91b73"
PREVIOUS: Final = "c4f1a8e52d90"
MIGRATION: Final = (
    ROOT / "migrations" / "versions" / "20260914_e6a4c2f91b73_project_controls_run01_integrity.py"
)
PRINCIPAL: Final = "prn_aaaaaaaa11111111"
OTHER_PRINCIPAL: Final = "prn_bbbbbbbb22222222"
PROJECT: Final = "prj_aaaaaaaa11111111"
CAPTURE: Final = "cap_aaaaaaaa11111111"
WHEN: Final = datetime(2026, 9, 14, 12, tzinfo=UTC)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def _engine(url: str) -> Engine:
    return create_database_engine(url)


def _seed_project(connection: Connection) -> None:
    connection.execute(
        text(
            """
            INSERT INTO knowledge.projects (
              project_id, principal_id, name, description, state, participants,
              opened_at, closed_at, created_at, updated_at, version
            ) VALUES (
              :project_id, :principal_id, 'Synthetic Project', NULL, 'active',
              '[]'::jsonb, :at, NULL, :at, :at, 1
            )
            """
        ),
        {"project_id": PROJECT, "principal_id": PRINCIPAL, "at": WHEN},
    )


def _literal(name: str) -> str:
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"missing frozen literal {name}")


def _values(expression: str) -> frozenset[str]:
    body = expression[expression.index("(") + 1 : expression.rindex(")")]
    return frozenset(re.findall(r"'([^']+)'", body))


def test_revision_identity_and_frozen_vocabulary_are_exact() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREVIOUS

    before = _values(_literal("_CAPABILITIES_BEFORE_THIS_REVISION"))
    after = _values(_literal("_CAPABILITIES_AT_THIS_REVISION"))
    assert len(before) == 177
    assert len(after) == 183
    assert after - before == {
        "constraints.create_published",
        "constraints.portfolio_list",
        "constraints.portfolio_search",
        "constraints.portfolio_overview",
        "project_controls.configure",
        "project_controls.status",
    }
    assert _literal("_PURPOSES_BEFORE_THIS_REVISION") == _literal("_PURPOSES_AT_THIS_REVISION")
    assert len(_values(_literal("_PURPOSES_AT_THIS_REVISION"))) == 45
    assert len(Capability) == 172
    assert len(Purpose) == 45
    assert "from my_pa.domain" not in MIGRATION.read_text(encoding="utf-8")


def test_metadata_declares_every_same_principal_fk_and_history_guard() -> None:
    expected = {
        captures: "a_capture_names_a_project_in_its_principal",
        tasks: "a_task_names_a_project_in_its_principal",
        constraint_project_settings: "constraint_settings_project_is_same_principal",
        constraint_categories: "constraint_categories_project_is_same_principal",
        project_constraints: "project_constraints_project_is_same_principal",
        constraint_project_settings_history: (
            "a_constraint_settings_history_names_a_project_in_its_principal"
        ),
    }
    for table, name in expected.items():
        foreign_key = next(
            constraint
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint) and constraint.name == name
        )
        assert [column.name for column in foreign_key.columns] in (
            ["project_id", "owner_principal_id"],
            ["project_id", "principal_id"],
        )
        assert [element.column.name for element in foreign_key.elements] == [
            "project_id",
            "principal_id",
        ]

    assert not constraint_project_settings_history.c.idempotency_key.nullable
    assert not constraint_project_settings_history.c.request_digest.nullable
    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "constraint_settings_history_idempotency_is_unique_per_principal"
        and [column.name for column in constraint.columns] == ["principal_id", "idempotency_key"]
        for constraint in constraint_project_settings_history.constraints
    )


@pytest.mark.database
def test_predecessor_to_head_preserves_null_capture_scope(empty_database_url: str) -> None:
    engine = _engine(empty_database_url)
    try:
        command.upgrade(_config(), PREVIOUS)
        with engine.begin() as connection:
            _seed_project(connection)
            connection.execute(
                text(
                    "INSERT INTO knowledge.captures "
                    "(capture_id, owner_principal_id, created_at) VALUES (:id, :principal, :at)"
                ),
                {"id": CAPTURE, "principal": PRINCIPAL, "at": WHEN},
            )
        command.upgrade(_config(), REVISION)
        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(captures.c.project_id).where(captures.c.capture_id == CAPTURE)
                ).scalar_one()
                is None
            )
            assert "a_project_is_identified_within_its_principal" in set(
                connection.execute(
                    text(
                        "SELECT conname FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid=c.conrelid "
                        "JOIN pg_namespace n ON n.oid=t.relnamespace "
                        "WHERE n.nspname='knowledge' AND t.relname='projects'"
                    )
                ).scalars()
            )
    finally:
        engine.dispose()


@pytest.mark.database
def test_upgrade_refuses_cross_principal_existing_settings(empty_database_url: str) -> None:
    engine = _engine(empty_database_url)
    try:
        command.upgrade(_config(), PREVIOUS)
        with engine.begin() as connection:
            _seed_project(connection)
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.constraint_project_settings (
                      principal_id, project_id, timezone_name, version, created_at, updated_at
                    ) VALUES (:principal, :project, 'America/New_York', 1, :at, :at)
                    """
                ),
                {"principal": OTHER_PRINCIPAL, "project": PROJECT, "at": WHEN},
            )
        with pytest.raises(DBAPIError, match="outside their Principal"):
            command.upgrade(_config(), REVISION)
    finally:
        engine.dispose()


@pytest.mark.database
def test_head_enforces_composite_scope_and_immutable_settings_history(
    empty_database_url: str,
) -> None:
    engine = _engine(empty_database_url)
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            _seed_project(connection)
            cross_principal = connection.begin_nested()
            try:
                with pytest.raises(IntegrityError):
                    connection.execute(
                        insert(captures).values(
                            capture_id=CAPTURE,
                            owner_principal_id=OTHER_PRINCIPAL,
                            project_id=PROJECT,
                            created_at=WHEN,
                        )
                    )
            finally:
                cross_principal.rollback()
            connection.execute(
                insert(constraint_project_settings_history).values(
                    history_id="cpsh_aaaaaaaa11111111",
                    principal_id=PRINCIPAL,
                    project_id=PROJECT,
                    action="configure",
                    actor="principal",
                    outcome="applied",
                    before_settings_version=None,
                    after_settings_version=1,
                    resulting_timezone_name="America/New_York",
                    resulting_settings_updated_at=WHEN,
                    idempotency_key="settings-key-0001",
                    request_digest="a" * 64,
                    correlation_id="corr_aaaaaaaa11111111",
                    occurred_at=WHEN,
                    recorded_at=WHEN,
                )
            )

        with engine.begin() as connection, pytest.raises(DBAPIError, match="stay as written"):
            connection.execute(
                update(constraint_project_settings_history)
                .where(constraint_project_settings_history.c.history_id == "cpsh_aaaaaaaa11111111")
                .values(actor="assistant")
            )
        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                insert(constraint_project_settings_history).values(
                    history_id="cpsh_bbbbbbbb22222222",
                    principal_id=PRINCIPAL,
                    project_id=PROJECT,
                    action="configure",
                    actor="principal",
                    outcome="no_op",
                    before_settings_version=1,
                    after_settings_version=1,
                    resulting_timezone_name="America/New_York",
                    resulting_settings_updated_at=WHEN,
                    idempotency_key="settings-key-0001",
                    request_digest="a" * 64,
                    occurred_at=WHEN,
                    recorded_at=WHEN,
                )
            )
        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                insert(constraint_project_settings_history).values(
                    history_id="cpsh_cccccccc33333333",
                    principal_id=PRINCIPAL,
                    project_id=PROJECT,
                    action="configure",
                    actor="principal",
                    outcome="applied",
                    before_settings_version=1,
                    after_settings_version=1,
                    resulting_timezone_name="America/New_York",
                    resulting_settings_updated_at=WHEN,
                    idempotency_key="settings-key-0002",
                    request_digest="b" * 64,
                    failure_detail="must not accompany success",
                    occurred_at=WHEN,
                    recorded_at=WHEN,
                )
            )
    finally:
        engine.dispose()


@pytest.mark.database
def test_empty_head_to_base_round_trip(empty_database_url: str) -> None:
    engine = _engine(empty_database_url)
    try:
        command.upgrade(_config(), "head")
        command.downgrade(_config(), "base")
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema='knowledge'"
                    )
                ).scalar_one()
                == 0
            )
    finally:
        engine.dispose()
