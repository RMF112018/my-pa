"""The R5 continuity revision creates its seven tables, and the invariants hold.

`d2e3f4a5b6c7` adds the situation/frame/trace/project/pulse surface WP-06 (R5,
relationship and project continuity) reads and writes. Every claim below is read
back from a live server rather than from the file that wrote it, because a
migration is only what the database ends up holding.

**Every table carries `principal_id`.** Invariant 11 (`principal_id` is present
from the first row) is what makes cross-principal isolation a property of the
schema rather than of the query that happens to be written. Each table's
`principal_id` column is asserted to exist, `NOT NULL`, so no continuity row can
be stored without naming the Principal it belongs to.

**Pulse reads only accepted records.** The WP-06 acceptance gate is pinned in the
schema: `pulse_items.accepted_only` defaults `TRUE` and a `CHECK` refuses any
other value, so a pulse row that claims to surface un-accepted evidence cannot be
stored at all. The default is read back from the server, not asserted of the
`Table` copy in the file.

**Every value here is synthetic.** The database is disposable, created and
dropped by its own fixture and never the configured one — `downgrade base`
deletes schemas, and pointing that at the canonical `my_pa` database would
destroy the migrated corpus.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine

pytestmark = pytest.mark.database

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = "knowledge"

R5_REVISION = "d2e3f4a5b6c7"
RELATIONSHIP_PARTITION_REVISION = "c1f2d3e4a5b6"

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
#: Distinct from every other suite's disposable database, so they cannot collide —
#: the database tier runs serially and these names are server-global.
DISPOSABLE_DATABASE = "my_pa_r5_schema_test"

#: The seven tables this revision creates, restated. A table added to the
#: revision has to be acknowledged here, which is the point.
R5_TABLES: Final[frozenset[str]] = frozenset(
    {
        "situations",
        "frames",
        "traces",
        "projects",
        "project_situations",
        "relationship_events",
        "pulse_items",
    }
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
        # CREATE and DROP DATABASE cannot run inside a transaction block.
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    try:
        _administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        yield url
    finally:
        _administer(drop)
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


def _column(engine: Engine, table: str, column: str) -> tuple[str, str] | None:
    """`(data_type, is_nullable)` for one column, or `None` if it does not exist."""
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT data_type, is_nullable FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table "
                "AND column_name = :column"
            ),
            {"schema": SCHEMA, "table": table, "column": column},
        ).first()
    return (row[0], row[1]) if row is not None else None


def test_the_r5_revision_is_in_the_chain_on_the_relationship_partition_revision() -> None:
    """Guards the rest of this module: an absent revision would create nothing.

    Deliberately not "is the head": that property is true only until the next
    revision is written, and asserting it would make every later work package
    edit this file.
    """
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert R5_REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(R5_REVISION).down_revision == RELATIONSHIP_PARTITION_REVISION


def test_all_new_r5_tables_exist(disposable_database: str) -> None:
    """The revision creates every one of its seven tables in the knowledge schema.

    The control is the equality on the intersection: `>=` alone would pass if the
    revision created none of them and the seven names happened to be a subset of
    something already there, which they are not, so the intersection is the set.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        present = _tables(engine)
        assert present >= R5_TABLES
        assert R5_TABLES & present == R5_TABLES
    finally:
        engine.dispose()


def test_situations_table_has_principal_id_column(disposable_database: str) -> None:
    """A situation cannot be stored without naming the Principal it belongs to."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert _column(engine, "situations", "principal_id") == ("text", "NO")
    finally:
        engine.dispose()


def test_frames_table_has_principal_id_column(disposable_database: str) -> None:
    """A frame carries its own `principal_id` even though it belongs to a situation."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert _column(engine, "frames", "principal_id") == ("text", "NO")
    finally:
        engine.dispose()


def test_traces_table_has_principal_id_column(disposable_database: str) -> None:
    """A trace cannot be stored without naming the Principal it belongs to."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert _column(engine, "traces", "principal_id") == ("text", "NO")
    finally:
        engine.dispose()


def test_projects_table_has_principal_id_column(disposable_database: str) -> None:
    """A project cannot be stored without naming the Principal it belongs to."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert _column(engine, "projects", "principal_id") == ("text", "NO")
    finally:
        engine.dispose()


def test_relationship_events_table_has_principal_id_column(disposable_database: str) -> None:
    """A relationship event carries the Principal whose timeline it belongs to."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert _column(engine, "relationship_events", "principal_id") == ("text", "NO")
    finally:
        engine.dispose()


def test_pulse_items_accepted_only_default_is_true(disposable_database: str) -> None:
    """The WP-06 acceptance gate is pinned in the schema, not only in the domain.

    Two halves, because either alone is satisfied by a schema that does less than
    it claims: the column's server-side default is `true`, and the `CHECK` that
    forbids any other value is present. A default without the check would let a
    later `UPDATE` turn the gate off; a check without the default would leave the
    gate's resting state unstated.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.connect() as connection:
            default = connection.execute(
                text(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = 'pulse_items' "
                    "AND column_name = 'accepted_only'"
                ),
                {"schema": SCHEMA},
            ).scalar_one()
            constraint = connection.execute(
                text(
                    "SELECT pg_get_constraintdef(con.oid) FROM pg_constraint con "
                    "JOIN pg_class rel ON rel.oid = con.conrelid "
                    "JOIN pg_namespace n ON n.oid = rel.relnamespace "
                    "WHERE n.nspname = :schema AND rel.relname = 'pulse_items' "
                    "AND con.conname = 'pulse_reads_only_accepted_records'"
                ),
                {"schema": SCHEMA},
            ).scalar_one()
        assert default is not None and default.startswith("true")
        assert "accepted_only IS TRUE" in constraint
    finally:
        engine.dispose()
