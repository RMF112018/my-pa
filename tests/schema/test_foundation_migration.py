"""The foundation revision round-trips: empty database to head and back.

The names are restated here rather than imported from the revision. A test that
imports the list it is checking proves only that a loop ran; these nine schemas
and two extensions are the contract every later phase builds on, so they are
written out.

Every database test runs against a disposable database created and dropped by
its fixture, never against the configured one. `downgrade base` deletes schemas,
and pointing that at the canonical `my_pa` database would destroy a completed
migration. Nothing here reads the legacy SQLite source.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from my_pa.bootstrap.settings import ENV_PREFIX
from my_pa.infrastructure.database.engine import create_database_engine, healthcheck

ROOT = Path(__file__).resolve().parents[2]

EXPECTED_SCHEMAS = frozenset(
    {
        "core",
        "procore",
        "email",
        "calendar",
        "contacts",
        "financial",
        "schedule",
        "construction",
        "migration_control",
    }
)
EXPECTED_EXTENSIONS = frozenset({"pg_trgm", "unaccent"})

#: Fixed name so a run interrupted before teardown is cleaned up by the next
#: one instead of leaving a growing pile of databases behind.
DISPOSABLE_DATABASE = "my_pa_foundation_test"


def _config(output_buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=output_buffer)


def _schemas(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(connection.execute(text("SELECT nspname FROM pg_namespace")).scalars())


def _extensions(engine: Engine) -> set[str]:
    return set(healthcheck(engine).extensions)


def test_offline_mode_emits_the_ddl_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--sql` has to work with no server: it is how the DDL gets reviewed.

    Needs no database, so it stays in the fast tier.
    """
    monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", "postgresql+psycopg://nobody@nowhere/nothing")
    buffer = io.StringIO()

    command.upgrade(_config(output_buffer=buffer), "head", sql=True)

    emitted = buffer.getvalue()
    for schema in EXPECTED_SCHEMAS:
        assert f'CREATE SCHEMA IF NOT EXISTS "{schema}"' in emitted
    for extension in EXPECTED_EXTENSIONS:
        assert f'CREATE EXTENSION IF NOT EXISTS "{extension}"' in emitted


@pytest.mark.database
def test_upgrade_from_empty_and_downgrade_back_to_empty(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        assert _schemas(engine).isdisjoint(EXPECTED_SCHEMAS)
        assert _extensions(engine).isdisjoint(EXPECTED_EXTENSIONS)

        command.upgrade(_config(), "head")

        assert healthcheck(engine).server_version
        assert EXPECTED_SCHEMAS.issubset(_schemas(engine))
        assert EXPECTED_EXTENSIONS.issubset(_extensions(engine))

        command.downgrade(_config(), "base")

        assert _schemas(engine).isdisjoint(EXPECTED_SCHEMAS)
        assert _extensions(engine).isdisjoint(EXPECTED_EXTENSIONS)
    finally:
        engine.dispose()


@pytest.mark.database
def test_upgrade_is_repeatable_after_a_full_round_trip(disposable_database: str) -> None:
    """A resumed run re-applies head; the revision must not depend on being new."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        command.downgrade(_config(), "base")
        command.upgrade(_config(), "head")

        assert EXPECTED_SCHEMAS.issubset(_schemas(engine))
        assert EXPECTED_EXTENSIONS.issubset(_extensions(engine))
    finally:
        engine.dispose()


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; migration tests still drive Alembic themselves."""
    return empty_database_url
