"""Additive widening of GoodNotes entity association kinds for Meeting and Agenda."""

from __future__ import annotations

import ast
import io
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.sql import Executable

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "d9c4e1a7b628"
PRIOR: Final = "b7f2c9e4a618"
ATTEMPT_REVISION: Final = "f4c1a8e6b205"
ENTITY_REVISION: Final = "9def3c2e63bb"
#: Where `upgrade head` lands, which the database tier reads back out of
#: `alembic_version`. That is a position in the chain rather than a property of
#: this revision, so it moves whenever a revision is added; the chain test below
#: is written not to depend on it.
ALIAS_REVISION: Final = "b7f4d1a92c36"
HEAD_REVISION: Final = "c1a7e4b93d58"
MIGRATION: Final = ROOT / (
    "migrations/versions/20260817_d9c4e1a7b628_widen_goodnotes_entity_kind_meeting_agenda.py"
)
DISPOSABLE_DATABASE: Final = "my_pa_goodnotes_entity_kind_migration_test"


def _administer(maintenance: Engine, *statements: Executable) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def _kind_check(engine: Engine, name: str) -> str | None:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT pg_get_constraintdef(c.oid) "
                "FROM pg_constraint c "
                "JOIN pg_class t ON c.conrelid = t.oid "
                "JOIN pg_namespace n ON t.relnamespace = n.oid "
                "WHERE n.nspname = 'knowledge' "
                "AND t.relname = 'goodnotes_entity_associations' "
                "AND c.conname = :name"
            ),
            {"name": name},
        ).scalar_one_or_none()


@pytest.fixture
def disposable_database() -> Iterator[str]:
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


def test_the_chain_has_one_head_and_this_revision_is_on_it() -> None:
    """One unbranched head, and this revision on the chain below it.

    Asserts a single head and this revision's place on the chain rather than
    which revision happens to be last: the head it named was another revision's,
    so it had to be re-pinned by every work package that added one.
    """
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PRIOR
    assert script.get_revision(ATTEMPT_REVISION).down_revision == REVISION
    assert script.get_revision(ENTITY_REVISION).down_revision == ATTEMPT_REVISION
    assert script.get_revision(ALIAS_REVISION).down_revision == ENTITY_REVISION
    assert script.get_revision(HEAD_REVISION).down_revision == ALIAS_REVISION
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == 61


def test_the_revision_imports_neither_tables_nor_domain_enums() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "my_pa.infrastructure.persistence.tables" not in imported
    assert not any(module.startswith("my_pa.domain") for module in imported)
    assert "from my_pa" not in source
    assert "GoodNotesEntityKind" not in source
    assert "CREATE TABLE" not in source


def test_the_frozen_sql_widens_meeting_and_agenda_by_alter() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "DROP CONSTRAINT goodnotes_entity_associations_entity_kind_check" in source
    assert "ADD CONSTRAINT goodnotes_entity_association_kind_is_known" in source
    assert "'MEETING'" in source
    assert "'AGENDA'" in source
    assert "'PROJECT'" in source
    assert "'PERSON'" in source
    assert "'NOTE'" in source
    assert "CREATE TABLE" not in source
    for semantic in ("pgvector", "halfvec", "embedding", "hnsw", "ivfflat"):
        assert semantic not in source.casefold()


@pytest.mark.database
def test_empty_database_reaches_the_new_head(disposable_database: str) -> None:
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == HEAD_REVISION
        definition = _kind_check(engine, "goodnotes_entity_association_kind_is_known")
        assert definition is not None
        assert "MEETING" in definition
        assert "AGENDA" in definition
        assert "PROJECT" in definition
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrade_restores_the_prior_kind_check(disposable_database: str) -> None:
    command.upgrade(_config(), "head")
    command.downgrade(_config(), PRIOR)
    engine = create_database_engine(disposable_database)
    try:
        definition = _kind_check(engine, "goodnotes_entity_associations_entity_kind_check")
        assert definition is not None
        assert "MEETING" not in definition
        assert "AGENDA" not in definition
        assert "PROJECT" in definition
        assert _kind_check(engine, "goodnotes_entity_association_kind_is_known") is None
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == PRIOR
    finally:
        engine.dispose()
