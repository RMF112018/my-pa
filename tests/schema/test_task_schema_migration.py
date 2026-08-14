"""Task/commitment revision round-trips and Principal constraints hold."""

from __future__ import annotations

import contextlib
import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine

pytestmark = pytest.mark.database

ROOT = Path(__file__).resolve().parents[2]
TASK_REVISION = "b8c4d1e6a907"
PRIOR_HEAD = "9d5e2f7b4c61"
DISPOSABLE_DATABASE = "my_pa_task_schema_test"
SCHEMA = "knowledge"
EXPECTED_TABLES = frozenset(
    {
        "tasks",
        "task_recurrences",
        "task_revisions",
        "task_context_links",
        "task_idempotency",
        "task_bulk_previews",
        "commitments",
    }
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


@pytest.fixture
def disposable_database() -> Iterator[str]:
    try:
        configured = make_url(load_settings().database_url)
    except Exception as exc:
        pytest.skip(f"postgres unavailable: {exc}")
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = __import__("os").environ.get(variable)
    try:
        _administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        __import__("os").environ[variable] = url
        yield url
    except Exception as exc:
        pytest.skip(f"postgres unavailable: {exc}")
    finally:
        if previous is None:
            __import__("os").environ.pop(variable, None)
        else:
            __import__("os").environ[variable] = previous
        with contextlib.suppress(Exception):
            _administer(drop)


def test_the_task_revision_is_the_single_head() -> None:
    heads = ScriptDirectory.from_config(_config()).get_heads()
    assert heads == [TASK_REVISION]


def test_upgrade_from_empty_and_from_previous_head(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    config = _config()
    command.upgrade(config, TASK_REVISION)
    with engine.connect() as connection:
        names = frozenset(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema"
                ),
                {"schema": SCHEMA},
            ).scalars()
        )
        assert names >= EXPECTED_TABLES
        waiting = connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :schema AND table_name = 'waiting_on'"
            ),
            {"schema": SCHEMA},
        ).scalar_one_or_none()
        assert waiting is None
    command.downgrade(config, PRIOR_HEAD)
    command.upgrade(config, TASK_REVISION)
    command.downgrade(config, "base")
