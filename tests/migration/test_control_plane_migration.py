"""The control-plane revision applies to a real server and rolls back cleanly.

Runs the whole Alembic chain against a disposable database, never the canonical
`my_pa` one: `downgrade base` deletes schemas, and pointing that at a loaded
migration would destroy it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from conftest import CONTROL_SCHEMA
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.migration.control_plane import METADATA

ROOT = Path(__file__).resolve().parents[2]

DOMAIN_SCHEMAS = [
    "core",
    "procore",
    "email",
    "calendar",
    "contacts",
    "financial",
    "schedule",
    "construction",
]
_CONSTRAINTS = (
    "SELECT count(*) FROM pg_constraint con JOIN pg_namespace n ON n.oid = con.connamespace "
    "WHERE con.contype = :kind AND n.nspname = ANY(:schemas)"
)

TABLES_REVISION = "1e6c0a94f3b7"
CONTROL_PLANE_REVISION = "4b9f0d27ac31"

#: Restated rather than recomputed. A change to the control plane or to the
#: generator's renames has to be acknowledged here, not silently absorbed.
EXPECTED_CONTROL_TABLES = 9
EXPECTED_RENAMES = 764

pytestmark = pytest.mark.database


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def _scalar(engine: Engine, sql: str, **parameters: object) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(sql), parameters).scalar_one())


def _control_tables(engine: Engine) -> int:
    return _scalar(
        engine,
        "SELECT count(*) FROM information_schema.tables WHERE table_type = 'BASE TABLE' "
        "AND table_schema = :schema",
        schema=CONTROL_SCHEMA,
    )


def test_the_control_plane_applies_and_rolls_back(loader_database: str) -> None:
    engine = create_database_engine(loader_database)
    try:
        command.upgrade(_config(), "head")

        assert _control_tables(engine) == EXPECTED_CONTROL_TABLES
        assert {table.name for table in METADATA.tables.values()} == {
            "migration_runs",
            "phase_status",
            "batch_checkpoints",
            "table_progress",
            "quarantine_records",
            "audit_events",
            "leases",
            "source_key_map",
            "identifier_map",
        }

        # Seeded reference data, not run data.
        assert (
            _scalar(engine, "SELECT count(*) FROM migration_control.identifier_map")
            == EXPECTED_RENAMES
        )
        # OD-024: the one rename that is a naming decision rather than a length
        # one has to be findable by its legacy name.
        with engine.connect() as connection:
            rename = connection.execute(
                text(
                    "SELECT shortened, owning_table FROM migration_control.identifier_map "
                    "WHERE original = 'hb_project_number'"
                )
            ).one()
        assert rename == ("project_number", "construction_project_identity")

        # No run exists yet, so the ledger is empty.
        assert _scalar(engine, "SELECT count(*) FROM migration_control.migration_runs") == 0

        command.downgrade(_config(), TABLES_REVISION)
        assert _control_tables(engine) == 0

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


def test_the_load_can_stop_at_the_control_plane_before_the_constraints_exist(
    loader_database: str,
) -> None:
    """OD-017 and OD-019: the load runs with the control plane up and the FKs down."""
    engine = create_database_engine(loader_database)
    try:
        command.upgrade(_config(), CONTROL_PLANE_REVISION)

        assert _control_tables(engine) == EXPECTED_CONTROL_TABLES
        # 484 tables and their primary keys, and nothing the load would trip over.
        assert _scalar(engine, _CONSTRAINTS, kind="f", schemas=DOMAIN_SCHEMAS) == 0
        assert (
            _scalar(
                engine,
                "SELECT count(*) FROM pg_indexes WHERE schemaname = ANY(:schemas)",
                schemas=DOMAIN_SCHEMAS,
            )
            == 484
        )

        command.upgrade(_config(), "head")

        assert _scalar(engine, _CONSTRAINTS, kind="f", schemas=DOMAIN_SCHEMAS) == 270
        command.downgrade(_config(), "base")
    finally:
        engine.dispose()
