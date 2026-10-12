"""`c8f7ae406d47`: the append-only MCP interaction log in schema `observability`.

The revision creates the schema, `observability.mcp_interactions` with its
CHECKs and six indexes, three trigger functions and four triggers (DB-assigned
`recorded_at`; UPDATE and TRUNCATE refused; DELETE refused outside the 14-day
retention purge). It grants nothing. Downgrade drops everything it created in
reverse order and, by design, discards the log.

Row-level behaviour of the triggers and the store is in
`tests/database/test_mcp_interaction_store.py`; this module holds the revision's
identity, its frozen text, and its upgrade/downgrade against a server.
"""

from __future__ import annotations

import ast
import io
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.mcp_interactions import COLUMNS, RETENTION_DAYS

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "c8f7ae406d47"
PREVIOUS: Final = "a591b81f10a2"
MIGRATION: Final = ROOT / "migrations" / "versions" / "20261011_c8f7ae406d47_mcp_interaction_log.py"
SCHEMA: Final = "observability"
TABLE: Final = "mcp_interactions"
TRIGGERS: Final = frozenset(
    {
        "mcp_interactions_stamp_recorded_at",
        "mcp_interactions_refuse_update",
        "mcp_interactions_guard_delete",
        "mcp_interactions_refuse_truncate",
    }
)
FUNCTIONS: Final = frozenset(
    {
        "mcp_interactions_stamp_recorded_at",
        "mcp_interactions_refuse_change",
        "mcp_interactions_guard_delete",
    }
)
INDEXES: Final = frozenset(
    {
        "mcp_interactions_pkey",
        "mcp_interactions_by_recorded_at",
        "mcp_interactions_by_client",
        "mcp_interactions_by_capability",
        "mcp_interactions_by_tool",
        "mcp_interactions_by_correlation",
        "mcp_interactions_by_outcome",
    }
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def test_the_revision_is_the_single_head_on_the_report_type_registry() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [REVISION]
    revision = script.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == PREVIOUS


def test_the_revision_is_frozen_text_that_grants_nothing() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstring = tree.body[0]
    assert isinstance(docstring, ast.Expr) and docstring.end_lineno is not None
    code = "\n".join(source.splitlines()[docstring.end_lineno :]).upper()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert imported <= {"alembic", "__future__", "typing"}
    assert "import my_pa" not in source and "from my_pa" not in source
    assert "CREATE ROLE" not in code
    assert "GRANT " not in code
    assert "record_event_roles.py" in source, "the docstring must cite the role provisioner"


def test_the_trigger_retention_matches_the_store() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert f"interval '{RETENTION_DAYS} days'" in source
    assert RETENTION_DAYS == 14


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    return empty_database_url


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    built = create_database_engine(disposable_database)
    try:
        yield built
    finally:
        built.dispose()


def _version(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _schema_exists(engine: Engine) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :schema)"),
                {"schema": SCHEMA},
            ).scalar_one()
        )


def _names(engine: Engine, query: str) -> frozenset[str]:
    with engine.connect() as connection:
        return frozenset(
            str(name) for name in connection.execute(text(query), {"schema": SCHEMA}).scalars()
        )


def _triggers(engine: Engine) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT t.tgname, t.tgenabled FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relname = :table AND NOT t.tgisinternal"
            ),
            {"schema": SCHEMA, "table": TABLE},
        ).all()
    return {str(name): str(enabled) for name, enabled in rows}


def _columns(engine: Engine) -> tuple[str, ...]:
    with engine.connect() as connection:
        return tuple(
            str(name)
            for name in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table "
                    "ORDER BY ordinal_position"
                ),
                {"schema": SCHEMA, "table": TABLE},
            ).scalars()
        )


def _functions(engine: Engine) -> frozenset[str]:
    return _names(
        engine,
        "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = :schema",
    )


def _indexes(engine: Engine) -> frozenset[str]:
    return _names(engine, "SELECT indexname FROM pg_indexes WHERE schemaname = :schema")


def _assert_at_revision(engine: Engine) -> None:
    assert _version(engine) == REVISION
    assert _schema_exists(engine)
    assert _columns(engine) == COLUMNS, "the store's declaration must match the revision"
    assert _triggers(engine) == dict.fromkeys(TRIGGERS, "O")
    assert _functions(engine) == FUNCTIONS
    assert _indexes(engine) == INDEXES


def _assert_absent(engine: Engine) -> None:
    assert not _schema_exists(engine)
    assert _functions(engine) == frozenset()


@pytest.mark.database
@pytest.mark.migration_empty_to_head
def test_an_empty_database_upgrades_to_the_interaction_log_revision(
    disposable_database: str, engine: Engine
) -> None:
    del disposable_database
    command.upgrade(_config(), REVISION)
    _assert_at_revision(engine)


@pytest.mark.database
@pytest.mark.migration_edge
def test_the_revision_round_trips_onto_the_report_type_registry(
    disposable_database: str, engine: Engine
) -> None:
    """Up from `a591b81f10a2` and back leaves no schema, function or relation behind.

    The catalogue-wide comparison of the two states at `a591b81f10a2` is
    `test_every_revision_denotes_one_schema.py`'s; this test pins the objects
    this revision owns by name.
    """
    del disposable_database
    command.upgrade(_config(), PREVIOUS)
    _assert_absent(engine)
    command.upgrade(_config(), REVISION)
    _assert_at_revision(engine)
    command.downgrade(_config(), PREVIOUS)
    assert _version(engine) == PREVIOUS
    _assert_absent(engine)
    command.upgrade(_config(), REVISION)
    _assert_at_revision(engine)


@pytest.mark.database
@pytest.mark.migration_edge
def test_downgrade_discards_the_log_by_design(disposable_database: str, engine: Engine) -> None:
    """A row does not hold the downgrade: the log is bounded-retention telemetry."""
    del disposable_database
    command.upgrade(_config(), REVISION)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO observability.mcp_interactions ("
                "interaction_id, started_at, latency_ms, http_method, outcome, "
                "request_bytes, response_bytes, request_sha256, response_sha256, "
                "request_truncated, response_truncated, request_headers, diagnostics"
                ") VALUES ("
                "'mcpi_' || repeat('a', 32), now(), 1.5, 'POST', 'ok', 2, 2, "
                "repeat('0', 64), repeat('1', 64), false, false, '{}', '{}')"
            )
        )
    command.downgrade(_config(), PREVIOUS)
    assert _version(engine) == PREVIOUS
    _assert_absent(engine)
