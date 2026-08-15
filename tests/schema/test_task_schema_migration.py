"""Revision `3d7a2a3e8277`: the task-management foundation, additive over `tasks`.

WP-TM-01, in the shape `tests/schema/test_continuity_migration.py` set.

**The revision is in the chain**, and deliberately not "is the head": that
property is true only until the next revision is written.

**Empty to head, prior revision to head, and a full round trip.** All three are
here. The prior-revision-to-head leg is the one this revision's whole backfill
claim rests on: it seeds one `open` row and one `closed` row at `4f6a9c2d8e17`
— the exact shape `8f2b6c4d1a37` already left in the database — upgrades, and
checks the backfill maps each to exactly the `lifecycle_state` the migration's
docstring commits to, not merely that the upgrade did not error.

**The created and altered tables match the live declaration.** The revision
writes its DDL out rather than importing `tables.py`; the price is drift, and
this is where it is paid.

**The two new tables are principal-partitioned**, restated for `task_recurrences`
and `task_history` the way it was for the four `8f2b6c4d1a37` tables.

The database is disposable, created and dropped by this module's own fixture,
and is never the configured one: `downgrade base` deletes schemas. Every value
is synthetic.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, Table, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.task.history import TaskMutationAction, TaskMutationActor, TaskMutationOutcome
from my_pa.domain.task.lifecycle import TaskLifecycleState, TaskPriority
from my_pa.domain.task.recurrence import RecurrenceFrequency
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import METADATA, task_history, task_recurrences

ROOT: Final = Path(__file__).resolve().parents[2]

DISPOSABLE_DATABASE: Final = "my_pa_task_schema_migration_test"

SCHEMA: Final = "knowledge"

#: This revision and the one it revises.
TASK_REVISION: Final = "3d7a2a3e8277"
PREVIOUS_REVISION: Final = "4f6a9c2d8e17"

#: The two tables this revision creates; `tasks` is altered, not created.
NEW_TABLES: Final = ("task_recurrences", "task_history")


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture
def disposable_database() -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')
    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        _administer(maintenance, drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        _administer(maintenance, drop)
        maintenance.dispose()


def _tables(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
                ),
                {"schema": SCHEMA},
            ).scalars()
        )


def _columns(engine: Engine, table: str) -> dict[str, tuple[Any, ...]]:
    with engine.connect() as connection:
        return {
            str(row[0]): (row[1], row[2])
            for row in connection.execute(
                text(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": SCHEMA, "table": table},
            )
        }


def _indexes(engine: Engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = :schema AND tablename = :table"
                ),
                {"schema": SCHEMA, "table": table},
            ).scalars()
        )


def _constraint_names(engine: Engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT c.conname FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid = c.conrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace "
                    "WHERE n.nspname = :schema AND t.relname = :table"
                ),
                {"schema": SCHEMA, "table": table},
            ).scalars()
        )


def test_the_task_revision_is_in_the_chain_on_the_client_revision() -> None:
    """One head, and this revision revises the one the campaign left at head."""
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert TASK_REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(TASK_REVISION).down_revision == PREVIOUS_REVISION


@pytest.mark.database
def test_the_task_revision_runs_empty_to_head_and_head_to_empty(disposable_database: str) -> None:
    """Reversible, and nothing of this revision survives `downgrade base`."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert set(NEW_TABLES) <= _tables(engine)
        assert "lifecycle_state" in _columns(engine, "tasks")

        command.downgrade(_config(), "base")
        assert _tables(engine) == set()
    finally:
        engine.dispose()


@pytest.mark.database
def test_the_backfill_maps_every_legacy_state_explicitly(disposable_database: str) -> None:
    """The migration's documented claim, run against real rows.

    One `open` row and one `closed` row are seeded at `4f6a9c2d8e17` — the exact
    shape `8f2b6c4d1a37` already produces — and the upgrade to head is checked
    to map `open` to `lifecycle_state = 'open'` (the column default) and
    `closed` to `lifecycle_state = 'completed'` (the explicit backfill), and
    nothing else.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.tasks "  # noqa: S608
                    "(task_id, principal_id, title, state, evidence_state, "
                    "origin_evidence_ref, opened_at, created_at, updated_at) VALUES "
                    "('tsk_openaaaa0001aaaa0001a', 'prn_aaaa0001aaaa0001aaaa0001', "
                    "'an open task', 'open', 'proposed', 'cap_legacy0001aaaa0001a', "
                    "now(), now(), now())"
                )
            )
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.tasks "  # noqa: S608
                    "(task_id, principal_id, title, state, evidence_state, "
                    "origin_evidence_ref, opened_at, closed_at, closure_evidence_ref, "
                    "created_at, updated_at) VALUES "
                    "('tsk_closedaaa0001aaaa0001', 'prn_aaaa0001aaaa0001aaaa0001', "
                    "'a closed task', 'closed', 'proposed', 'cap_legacy0001aaaa0001a', "
                    "now(), now(), 'cap_closure0001aaaa0001', now(), now())"
                )
            )

        command.upgrade(_config(), "head")
        with engine.connect() as connection:
            rows = dict(
                connection.execute(
                    text(f"SELECT task_id, lifecycle_state FROM {SCHEMA}.tasks")  # noqa: S608
                ).all()
            )
        assert rows == {
            "tsk_openaaaa0001aaaa0001a": "open",
            "tsk_closedaaa0001aaaa0001": "completed",
        }
        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrading_this_revision_restores_exactly_the_previous_shape(
    disposable_database: str,
) -> None:
    """A round trip, not a one-way observation.

    One revision down, the two new tables are gone and `tasks` has lost every
    column this revision added; every legacy `tasks` column an existing row held
    at `4f6a9c2d8e17` is exactly what remains.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert set(NEW_TABLES) <= _tables(engine)
        assert "lifecycle_state" in _columns(engine, "tasks")

        command.downgrade(_config(), PREVIOUS_REVISION)
        assert set(NEW_TABLES) & _tables(engine) == set()
        for added_column in (
            "lifecycle_state",
            "priority",
            "scheduled_at",
            "deferred_until",
            "archived_at",
            "version",
            "recurrence_id",
        ):
            assert added_column not in _columns(engine, "tasks")
        legacy_columns = _columns(engine, "tasks")
        for legacy_column in (
            "task_id",
            "principal_id",
            "title",
            "state",
            "evidence_state",
            "origin_evidence_ref",
            "opened_at",
            "closed_at",
            "closure_evidence_ref",
            "created_at",
            "updated_at",
        ):
            assert legacy_column in legacy_columns

        command.upgrade(_config(), "head")
        assert set(NEW_TABLES) <= _tables(engine)
        assert "lifecycle_state" in _columns(engine, "tasks")

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
@pytest.mark.parametrize(
    "table", [task_recurrences, task_history], ids=lambda table: str(table.name)
)
def test_each_created_table_matches_the_live_declaration(
    disposable_database: str, table: Table
) -> None:
    """The cost of writing the DDL out, paid rather than described."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        declared_columns = {
            column.name: (
                {
                    "Text": "text",
                    "DateTime": "timestamp with time zone",
                    "Integer": "integer",
                    "JSONB": "jsonb",
                }[column.type.__class__.__name__],
                "NO" if not column.nullable else "YES",
            )
            for column in table.columns
        }
        assert _columns(engine, str(table.name)) == declared_columns

        named = {
            constraint.name
            for constraint in table.constraints
            if constraint.name is not None and not constraint.name.startswith("_")
        }
        live = _constraint_names(engine, str(table.name))
        assert named <= live, f"the declaration names {sorted(named - live)}, the server does not"

        declared_indexes = {index.name for index in table.indexes}
        assert declared_indexes <= _indexes(engine, str(table.name))

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_tasks_gains_exactly_the_columns_and_constraints_this_revision_declares(
    disposable_database: str,
) -> None:
    """`tasks` is altered, not created, so it is checked column-by-column."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        columns = _columns(engine, "tasks")
        assert columns["lifecycle_state"] == ("text", "NO")
        assert columns["priority"] == ("text", "YES")
        assert columns["scheduled_at"] == ("timestamp with time zone", "YES")
        assert columns["deferred_until"] == ("timestamp with time zone", "YES")
        assert columns["archived_at"] == ("timestamp with time zone", "YES")
        assert columns["version"] == ("integer", "NO")
        assert columns["recurrence_id"] == ("text", "YES")

        live = _constraint_names(engine, "tasks")
        for name in (
            "a_task_lifecycle_state_is_known",
            "a_task_lifecycle_state_matches_its_legacy_state",
            "a_task_priority_is_known",
            "a_task_version_is_positive",
            "a_task_recurrence_is_an_opaque_identifier",
            "tasks_recurrence_id_fkey",
        ):
            assert name in live

        indexes = _indexes(engine, "tasks")
        assert "tasks_by_principal_lifecycle_state" in indexes
        assert "tasks_by_recurrence" in indexes

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_every_new_table_is_principal_partitioned(disposable_database: str) -> None:
    """What admits the two new tables to `knowledge` at all."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        for table in NEW_TABLES:
            assert "principal_id" in _columns(engine, table)
            assert f"{table}_by_principal" in _indexes(engine, table)
        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_head_admits_exactly_the_frozen_vocabularies_the_domain_declares(
    disposable_database: str,
) -> None:
    """The frozen literals in the migration match the domain enums at head."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.connect() as connection:
            lifecycle_definition = str(
                connection.execute(
                    text(
                        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "WHERE n.nspname = :schema AND t.relname = 'tasks' "
                        "AND c.conname = 'a_task_lifecycle_state_is_known'"
                    ),
                    {"schema": SCHEMA},
                ).scalar_one()
            )
        for member in TaskLifecycleState:
            assert f"'{member.value}'" in lifecycle_definition

        with engine.connect() as connection:
            priority_definition = str(
                connection.execute(
                    text(
                        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "WHERE n.nspname = :schema AND t.relname = 'tasks' "
                        "AND c.conname = 'a_task_priority_is_known'"
                    ),
                    {"schema": SCHEMA},
                ).scalar_one()
            )
        for member in TaskPriority:
            assert f"'{member.value}'" in priority_definition

        with engine.connect() as connection:
            frequency_definition = str(
                connection.execute(
                    text(
                        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "WHERE n.nspname = :schema AND t.relname = 'task_recurrences' "
                        "AND c.conname = 'a_task_recurrence_frequency_is_known'"
                    ),
                    {"schema": SCHEMA},
                ).scalar_one()
            )
        for member in RecurrenceFrequency:
            assert f"'{member.value}'" in frequency_definition

        with engine.connect() as connection:
            action_definition = str(
                connection.execute(
                    text(
                        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "WHERE n.nspname = :schema AND t.relname = 'task_history' "
                        "AND c.conname = 'a_task_history_action_is_known'"
                    ),
                    {"schema": SCHEMA},
                ).scalar_one()
            )
        for member in TaskMutationAction:
            assert f"'{member.value}'" in action_definition

        with engine.connect() as connection:
            actor_definition = str(
                connection.execute(
                    text(
                        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "WHERE n.nspname = :schema AND t.relname = 'task_history' "
                        "AND c.conname = 'a_task_history_actor_is_known'"
                    ),
                    {"schema": SCHEMA},
                ).scalar_one()
            )
        for member in TaskMutationActor:
            assert f"'{member.value}'" in actor_definition

        with engine.connect() as connection:
            outcome_definition = str(
                connection.execute(
                    text(
                        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "WHERE n.nspname = :schema AND t.relname = 'task_history' "
                        "AND c.conname = 'a_task_history_outcome_is_known'"
                    ),
                    {"schema": SCHEMA},
                ).scalar_one()
            )
        for member in TaskMutationOutcome:
            assert f"'{member.value}'" in outcome_definition

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_task_history_enforces_the_version_pairing_at_the_server(
    disposable_database: str,
) -> None:
    """The CHECK a caller cannot bypass by skipping the domain layer."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.tasks "  # noqa: S608
                    "(task_id, principal_id, title, origin_evidence_ref, opened_at, "
                    "created_at, updated_at) VALUES "
                    "('tsk_hist0001aaaa0001aaaa', 'prn_aaaa0001aaaa0001aaaa0001', "
                    "'a task', 'cap_legacy0001aaaa0001a', now(), now(), now())"
                )
            )
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.task_history "  # noqa: S608
                    "(history_id, principal_id, task_id, action, actor, outcome, "
                    "before_version, after_version, occurred_at, recorded_at) VALUES "
                    "('thst_ok0001aaaa0001aaaa0', 'prn_aaaa0001aaaa0001aaaa0001', "
                    "'tsk_hist0001aaaa0001aaaa', 'create', 'principal', 'applied', "
                    "0, 1, now(), now())"
                )
            )
        with engine.begin() as connection, pytest.raises(Exception, match="version"):
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.task_history "  # noqa: S608
                    "(history_id, principal_id, task_id, action, actor, outcome, "
                    "before_version, after_version, occurred_at, recorded_at) VALUES "
                    "('thst_bad0001aaaa0001aaaa', 'prn_aaaa0001aaaa0001aaaa0001', "
                    "'tsk_hist0001aaaa0001aaaa', 'set_priority', 'principal', 'applied', "
                    "1, 1, now(), now())"
                )
            )
        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


def test_the_declaration_holds_the_two_new_tables_this_module_reads() -> None:
    """Guards every database test above against a renamed declaration."""
    declared = {str(table.name) for table in METADATA.tables.values()}
    assert set(NEW_TABLES) <= declared
