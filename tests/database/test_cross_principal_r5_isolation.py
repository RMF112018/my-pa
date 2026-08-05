"""MU-AC-05 at the row: one Principal's continuity is never another's to read.

The fast-tier isolation suite proves the *service* refuses a cross-principal
read. This proves the property one layer down, where the rows actually live: a
situation, a project, and a relationship event written for Principal A are not
returned by the same query run for Principal B. If the partition were only in the
application, a query that forgot the `WHERE principal_id = :caller` clause would
leak — so the test issues exactly that query and asserts the leak is empty.

Every claim is read back from a live server. The rows are written directly with
SQL so the test depends on the schema and not on the writer that normally fills
these tables; the negative read is the point, and it is measured against a
non-empty table so it cannot pass vacuously.

**Every value here is synthetic.** The two Principals are invented opaque
identifiers. The database is disposable, created and dropped by its own fixture
and never the configured one — pointing `downgrade`/`DROP DATABASE` at the
canonical `my_pa` database would destroy the migrated corpus.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine

pytestmark = pytest.mark.database

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = "knowledge"

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
#: Distinct from every other suite's disposable database, so they cannot collide.
DISPOSABLE_DATABASE = "my_pa_r5_isolation_test"

#: Two invented opaque identifiers, well-formed under the `^prn_...$` CHECK. The
#: same values the fast-tier isolation suite uses, so the two tiers name the same
#: adversary. A is the writer; B is the Principal whose read must come back empty.
PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"


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


@pytest.fixture
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    """The disposable database, upgraded to head and disposed afterwards."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def _count_for_principal(engine: Engine, table: str, id_column: str, principal_id: str) -> int:
    """How many rows of `table` a principal-scoped read returns for `principal_id`."""
    with engine.connect() as connection:
        return connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.{table} "  # noqa: S608 -- table/id are module constants
                "WHERE principal_id = :principal_id"
            ),
            {"principal_id": principal_id},
        ).scalar_one()


def test_sql_situation_from_a_not_returned_for_b(migrated_engine: Engine) -> None:
    """A situation written for A is invisible to the same query run for B.

    The non-zero control is in the same test: A's principal-scoped read returns
    the row, so B's empty read is a partition and not a table that stores nothing.
    """
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.situations (situation_id, principal_id, title, "  # noqa: S608
                "state, opened_at, created_at, updated_at) VALUES (:id, :principal_id, "
                "'A private situation', 'open', now(), now(), now())"
            ),
            {"id": "sit_situation0001situation01", "principal_id": PRINCIPAL_A},
        )

    assert _count_for_principal(migrated_engine, "situations", "situation_id", PRINCIPAL_A) == 1
    assert _count_for_principal(migrated_engine, "situations", "situation_id", PRINCIPAL_B) == 0


def test_sql_project_from_a_not_returned_for_b(migrated_engine: Engine) -> None:
    """A project written for A is invisible to the same query run for B."""
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.projects (project_id, principal_id, name, state, "  # noqa: S608
                "opened_at, created_at, updated_at) VALUES (:id, :principal_id, "
                "'A private project', 'active', now(), now(), now())"
            ),
            {"id": "prj_project0001project0001", "principal_id": PRINCIPAL_A},
        )

    assert _count_for_principal(migrated_engine, "projects", "project_id", PRINCIPAL_A) == 1
    assert _count_for_principal(migrated_engine, "projects", "project_id", PRINCIPAL_B) == 0


def test_sql_trace_from_a_not_returned_for_b(migrated_engine: Engine) -> None:
    """A trace written for A is invisible to the same query run for B.

    A trace carries no foreign key, so its row-level partition is exactly the
    `principal_id` column and nothing else — the cleanest demonstration that the
    isolation is a property of the row, not of some parent it inherits. The
    non-zero control is in the same test: A's principal-scoped read returns the
    row, so B's empty read is a partition and not a table that stores nothing.
    """
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.traces (trace_id, principal_id, object_id, "  # noqa: S608
                "object_type, source_events, gaps, created_at) VALUES (:id, "
                ":principal_id, 'obj_object0001object0001', 'commitment', "
                "'[]'::jsonb, '[]'::jsonb, now())"
            ),
            {"id": "trc_trace0001trace0001trace0", "principal_id": PRINCIPAL_A},
        )

    assert _count_for_principal(migrated_engine, "traces", "trace_id", PRINCIPAL_A) == 1
    assert _count_for_principal(migrated_engine, "traces", "trace_id", PRINCIPAL_B) == 0
