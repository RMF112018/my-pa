"""The generated DDL applies to a real PostgreSQL server and rolls back cleanly.

The expected counts are restated here rather than recomputed from the registry.
Recomputing them would make the test agree with whatever the generator produced;
written out, a change in the target schema has to be acknowledged.

Every database test runs against a disposable database created and dropped by
its fixture, never against the configured one. `downgrade base` deletes schemas,
and pointing that at the canonical `my_pa` database would destroy a completed
migration. Nothing here reads the legacy SQLite source.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine

ROOT = Path(__file__).resolve().parents[2]

FOUNDATION_REVISION = "5d75f23847c9"
TABLES_REVISION = "1e6c0a94f3b7"

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

#: The control plane is a separate concern with its own revision and its own
#: test; the counts below are about the migrated target schema, so it is kept out
#: of them and asserted only by presence.
CONTROL_SCHEMA = "migration_control"
ALL_SCHEMAS = [*DOMAIN_SCHEMAS, CONTROL_SCHEMA]

#: 484 source tables are marked for creation. `contacts` gets none: no source
#: object resolves to it at schema version 128.
EXPECTED_TABLES_BY_SCHEMA = {
    "calendar": 11,
    "construction": 26,
    "core": 161,
    "email": 26,
    "financial": 67,
    "procore": 150,
    "schedule": 43,
}
EXPECTED_TABLE_COUNT = 484
EXPECTED_CHECK_CONSTRAINTS = 1946
EXPECTED_FOREIGN_KEYS = 270
EXPECTED_INDEXES = 1499  # 1015 generated plus one per primary key
#: Tables that declared AUTOINCREMENT, plus those with a single-column INTEGER
#: PRIMARY KEY that SQLite auto-assigned as a rowid alias without saying so; all
#: 46 are BY DEFAULT so the load can insert the source's own keys. The 47th is
#: the ALWAYS surrogate on the one table with no key of its own.
EXPECTED_IDENTITY_COLUMNS = {"BY DEFAULT": 46, "ALWAYS": 1}

#: A rowid alias with no AUTOINCREMENT in its source DDL. Without an identity
#: these would silently stop auto-assigning keys and reject an ordinary insert.
ROWID_ALIAS_TABLES = (
    ("core", "attachments", "source_record_id"),
    ("core", "files", "source_record_id"),
    ("email", "email_intelligence_active_policy", "id"),
    ("financial", "second_brain_financial_amount_facts_normalized", "id"),
    ("financial", "second_brain_financial_fact_normalization_runs", "id"),
    ("financial", "second_brain_financial_forecast_readiness_runs", "id"),
    ("financial", "second_brain_financial_readiness_agent_runs", "id"),
)

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
DISPOSABLE_DATABASE = "my_pa_target_schema_test"

_CONSTRAINTS = (
    "SELECT count(*) FROM pg_constraint con JOIN pg_namespace n ON n.oid = con.connamespace "
    "WHERE con.contype = :kind AND n.nspname = ANY(:schemas)"
)
_TABLES = (
    "SELECT count(*) FROM information_schema.tables WHERE table_type = 'BASE TABLE' "
    "AND table_schema = ANY(:schemas)"
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def _scalar(engine: Engine, sql: str, **parameters: str | list[str]) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(sql), parameters).scalar_one())


def _tables_by_schema(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT table_schema, count(*) FROM information_schema.tables "
                "WHERE table_type = 'BASE TABLE' AND table_schema = ANY(:schemas) "
                "GROUP BY table_schema"
            ),
            {"schemas": DOMAIN_SCHEMAS},
        ).all()
    return {str(schema): int(count) for schema, count in rows}


def _identity_generation(engine: Engine, schema: str, table: str, column: str) -> str | None:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT identity_generation FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table AND column_name = :column"
            ),
            {"schema": schema, "table": table, "column": column},
        ).scalar_one()


def _column_type(engine: Engine, schema: str, table: str, column: str) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table "
                    "AND column_name = :column"
                ),
                {"schema": schema, "table": table, "column": column},
            ).scalar_one()
        )


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


@pytest.mark.database
def test_the_target_schema_applies_and_rolls_back(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        assert _tables_by_schema(engine) == EXPECTED_TABLES_BY_SCHEMA
        assert _scalar(engine, _TABLES, schemas=DOMAIN_SCHEMAS) == EXPECTED_TABLE_COUNT

        assert _scalar(engine, _CONSTRAINTS, kind="c", schemas=DOMAIN_SCHEMAS) == (
            EXPECTED_CHECK_CONSTRAINTS
        )
        assert _scalar(engine, _CONSTRAINTS, kind="f", schemas=DOMAIN_SCHEMAS) == (
            EXPECTED_FOREIGN_KEYS
        )
        assert _scalar(engine, _CONSTRAINTS, kind="p", schemas=DOMAIN_SCHEMAS) == (
            EXPECTED_TABLE_COUNT
        )
        assert (
            _scalar(
                engine,
                "SELECT count(*) FROM pg_indexes WHERE schemaname = ANY(:schemas)",
                schemas=DOMAIN_SCHEMAS,
            )
            == EXPECTED_INDEXES
        )

        # No identifier reached PostgreSQL's silent truncation point.
        assert (
            _scalar(
                engine,
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = ANY(:schemas) AND length(c.relname) > 63",
                schemas=DOMAIN_SCHEMAS,
            )
            == 0
        )

        with engine.connect() as connection:
            identities = dict(
                connection.execute(
                    text(
                        "SELECT identity_generation, count(*) FROM information_schema.columns "
                        "WHERE is_identity = 'YES' AND table_schema = ANY(:schemas) "
                        "GROUP BY identity_generation"
                    ),
                    {"schemas": DOMAIN_SCHEMAS},
                ).all()
            )
        assert identities == EXPECTED_IDENTITY_COLUMNS

        # The schema is created, not populated.
        assert (
            _scalar(
                engine,
                "SELECT coalesce(sum(n_live_tup), 0) FROM pg_stat_user_tables "
                "WHERE schemaname = ANY(:schemas)",
                schemas=DOMAIN_SCHEMAS,
            )
            == 0
        )

        command.downgrade(_config(), FOUNDATION_REVISION)

        assert _tables_by_schema(engine) == {}
        assert (
            _scalar(
                engine,
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = :schema",
                schema=CONTROL_SCHEMA,
            )
            == 0
        )
        assert _scalar(
            engine,
            "SELECT count(*) FROM information_schema.schemata WHERE schema_name = ANY(:schemas)",
            schemas=ALL_SCHEMAS,
        ) == len(ALL_SCHEMAS)

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_column_types_follow_the_declared_type_and_the_checks(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), TABLES_REVISION)

        # A reserved word survives as a quoted name rather than being renamed.
        assert _column_type(engine, "procore", "procore_ep_budget_change_history", "column") == (
            "text"
        )
        # `CHECK(is_current IN (0, 1))` is the only evidence that promotes a boolean.
        assert _column_type(
            engine, "procore", "procore_ep_budget_change_history", "is_current"
        ) == ("boolean")
        # An INTEGER with no such check stays an integer, whatever its name suggests.
        assert _column_type(
            engine, "procore", "procore_ep_budget_change_history", "external_writeback_performed"
        ) == ("bigint")
        assert _column_type(
            engine, "schedule", "schedule_cpm_relationship_results", "normalized_lag_days"
        ) == ("double precision")
        assert _column_type(engine, "core", "accepted_commitments", "migration_run_id") == "uuid"

        for schema, table, column in ROWID_ALIAS_TABLES:
            assert _identity_generation(engine, schema, table, column) == "BY DEFAULT"
            assert _column_type(engine, schema, table, column) == "bigint"

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()
