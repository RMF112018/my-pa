"""RE-DBH-01: statement-level TRUNCATE refusal on the Record Event relations.

The revision adds no table and no row. Downgrade refuses while either relation
holds a row and deletes nothing. An empty downgrade removes only the new
triggers and function, leaving the append-only trigger in place.
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
from sqlalchemy.exc import DBAPIError

from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "c8e4a1b70d35"
PREVIOUS: Final = "1d9b248e7f83"
MIGRATION: Final = (
    ROOT / "migrations" / "versions" / "20261002_c8e4a1b70d35_record_event_truncate_refusal.py"
)
RESTRICT_VIOLATION: Final = "23001"
TRIGGERS: Final = (
    ("record_events", "record_events_refuse_truncate"),
    ("record_event_sequences", "record_event_sequences_refuse_truncate"),
)


def _config(buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


def test_the_revision_is_on_the_record_event_revision_under_the_capture_head() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == ["93f3aa113f58"]
    assert script.get_revision("0641c354ca85").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_revision_imports_no_domain_or_persistence_modules() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert imported <= {"alembic", "__future__", "typing"}
    assert "my_pa" not in source
    assert "CREATE ROLE" not in source.upper()
    assert "GRANT " not in source.upper()


def test_the_historical_record_event_revision_has_no_truncate_trigger() -> None:
    historical = (
        ROOT / "migrations" / "versions" / "20260929_1d9b248e7f83_record_events.py"
    ).read_text(encoding="utf-8")
    assert "BEFORE TRUNCATE" not in historical
    assert historical.split("revision: str = ", 1)[1].startswith('"1d9b248e7f83"')


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


def _enabled(engine: Engine, table: str, trigger: str) -> str | None:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT t.tgenabled FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'knowledge' AND c.relname = :table AND t.tgname = :trigger"
            ),
            {"table": table, "trigger": trigger},
        ).scalar_one_or_none()


@pytest.mark.database
@pytest.mark.migration_empty_to_head
def test_an_empty_database_upgrades_to_the_truncate_refusal_revision(
    disposable_database: str, engine: Engine
) -> None:
    del disposable_database
    command.upgrade(_config(), REVISION)
    assert _version(engine) == REVISION
    for table, trigger in TRIGGERS:
        assert _enabled(engine, table, trigger) == "O"
    assert _enabled(engine, "record_events", "record_events_are_append_only") == "O"


@pytest.mark.database
@pytest.mark.migration_edge
def test_the_record_event_revision_upgrades_to_the_truncate_refusal_revision(
    disposable_database: str, engine: Engine
) -> None:
    del disposable_database
    command.upgrade(_config(), PREVIOUS)
    command.upgrade(_config(), REVISION)
    assert _version(engine) == REVISION
    for table, trigger in TRIGGERS:
        assert _enabled(engine, table, trigger) == "O"


@pytest.mark.database
def test_downgrade_refuses_while_a_record_event_exists(
    disposable_database: str, engine: Engine
) -> None:
    del disposable_database
    command.upgrade(_config(), "head")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.record_events ("
                "event_id, principal_id, sequence_number, record_family, record_id, "
                "event_kind, record_version, changed_fields, source_capability, "
                "actor_class, classification, occurred_at"
                ") VALUES ("
                "'rcev_truncmig0001event1', 'prn_truncmig0001prin1', 1, 'task', "
                "'task_truncmig0001task1', 'created', 1, ARRAY['title'], 'tasks.create', "
                "'principal', 'private_local', '2026-10-02T12:00:00Z'"
                ")"
            )
        )
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert getattr(refused.value.orig, "sqlstate", None) == RESTRICT_VIOLATION
    assert _version(engine) == REVISION
    with engine.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM knowledge.record_events")
        ).scalar_one()
    assert count == 1


@pytest.mark.database
def test_an_empty_downgrade_drops_only_the_truncate_refusal(
    disposable_database: str, engine: Engine
) -> None:
    del disposable_database
    command.upgrade(_config(), "head")
    command.downgrade(_config(), PREVIOUS)
    assert _version(engine) == PREVIOUS
    for table, trigger in TRIGGERS:
        assert _enabled(engine, table, trigger) is None
    assert _enabled(engine, "record_events", "record_events_are_append_only") == "O"
    with engine.connect() as connection:
        tables = set(
            connection.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'knowledge' "
                    "AND tablename IN ('record_events', 'record_event_sequences')"
                )
            ).scalars()
        )
    assert tables == {"record_events", "record_event_sequences"}
