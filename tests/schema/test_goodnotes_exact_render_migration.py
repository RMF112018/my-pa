"""Additive exact visual render digest on GoodNotes page versions."""

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import Executable

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "c3e9a7f1b204"
PRIOR: Final = "e8c1b5a7d204"
INTELLIGENCE_REVISION: Final = "e9b2c4d7a150"
#: Where `upgrade head` lands, which the database tier reads back out of
#: `alembic_version`. That is a position in the chain rather than a property of
#: this revision, so it moves whenever a revision is added; the chain test below
#: is written not to depend on it.
ALIAS_REVISION: Final = "b7f4d1a92c36"
CAPABILITY_REVISION: Final = "c1a7e4b93d58"
GOVERNANCE_REVISION: Final = "d2b8f5c04e71"
#: The unresolved-mention capability admission, between governance and head.
QUEUE_REVISION: Final = "e4d7b2f9a316"
MENTION_REVISION: Final = "f3a8c1d7e592"
#: The Work task and commitment contracts, which stack on the intelligence
#: plane and carry the head until the Relationship Memory plane stacks on them.
WORK_REVISION: Final = "a4d9e7c2b615"
#: The Relationship Memory plane, which is where `upgrade head` now lands.
#: `WORK_REVISION` above was head until this revision stacked on it;
#: naming both keeps the chain assertion below a statement about the order
#: rather than about whichever revision happens to be last.
MEMORY_REVISION: Final = "f1c6b904a2d7"
#: The entity lifecycle and ledger revision (WP-RI-A-01), which is where
#: `upgrade head` now lands. `MEMORY_REVISION` above was head until this one
#: stacked on it; naming both keeps the chain assertion below a statement about
#: the order rather than about whichever revision happens to be last.
LIFECYCLE_REVISION: Final = "2fe4e13fb449"
#: Phase A's single vocabulary revision, which is where `upgrade head` now
#: lands. `LIFECYCLE_REVISION` above was head until this one stacked on it;
#: naming both keeps the chain assertion below a statement about the order
#: rather than about whichever revision happens to be last.
PHASE_A_REVISION: Final = "823e23b6cc63"
#: Phase B's vocabulary revision, which is where `upgrade head` now lands.
#: `PHASE_A_REVISION` above was head until the Phase B chain stacked on it;
#: naming both keeps the chain assertion below a statement about the order
#: rather than about whichever revision happens to be last.
PHASE_B_REVISION: Final = "b64e29a0f7c1"
PHASE_B_HEAD: Final = "3d07af4dc513"
GSQS_REVISION: Final = "c4b0a1d9e827"
HEAD_REVISION: Final = "17149a48fa30"
MIGRATION: Final = ROOT / (
    "migrations/versions/20260817_c3e9a7f1b204_add_goodnotes_exact_render_digest.py"
)
DISPOSABLE_DATABASE: Final = "my_pa_goodnotes_exact_render_migration_test"
NEW_COLUMN: Final = "exact_render_sha256"


def _administer(maintenance: Engine, *statements: Executable) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def _columns(engine: Engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'knowledge' AND table_name = :table"
                ),
                {"table": table},
            ).scalars()
        )


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
    """Renamed from "is the head", because that was never the claim needed here.

    This revision stopped being the head one revision after it landed, and the
    pin then rotted again at `9def3c2e63bb`. What the tests below actually
    depend on is a single unbranched chain that reaches this revision on the
    predecessor it names, with the successor that was written against it still
    naming it — none of which the identity of the last revision affects.
    """
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PRIOR
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == 82


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
    assert "CREATE TABLE" not in source


def test_the_frozen_sql_adds_nullable_exact_render_digest() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "ALTER TABLE knowledge.goodnotes_page_versions" in source
    assert "ADD COLUMN exact_render_sha256 varchar(64)" in source
    assert "goodnotes_version_exact_render_sha256_shape" in source
    assert "^[a-f0-9]{64}$" in source
    assert "DROP COLUMN IF EXISTS exact_render_sha256" in source
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
        assert NEW_COLUMN in _columns(engine, "goodnotes_page_versions")
    finally:
        engine.dispose()


@pytest.mark.database
def test_prior_head_to_new_head_leaves_legacy_exact_render_null(
    disposable_database: str,
) -> None:
    command.upgrade(_config(), PRIOR)
    engine = create_database_engine(disposable_database)
    try:
        assert NEW_COLUMN not in _columns(engine, "goodnotes_page_versions")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_pages "
                    "(principal_id, page_id, source_id, source_object_id, page_number) "
                    "VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnpg_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'src_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'obj_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 1)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_page_versions "
                    "(principal_id, page_version_id, page_id, source_version_id, "
                    " content_sha256, observed_at) VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnver_bbbbbbbbbbbbbbbbbbbbbbbb',"
                    " 'gnpg_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'ver_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',"
                    " '2026-08-17T10:00:00+00')"
                )
            )
        command.upgrade(_config(), REVISION)
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT content_sha256, exact_render_sha256, normalized_render_sha256 "
                    "FROM knowledge.goodnotes_page_versions"
                )
            ).one()
            assert row.content_sha256 == "a" * 64
            assert row.exact_render_sha256 is None
            assert row.normalized_render_sha256 is None
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == REVISION
        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "UPDATE knowledge.goodnotes_page_versions "
                    "SET exact_render_sha256 = 'not-a-digest'"
                )
            )
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrade_drops_exact_render_and_leaves_content_digest(
    disposable_database: str,
) -> None:
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_pages "
                    "(principal_id, page_id, source_id, source_object_id, page_number) "
                    "VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnpg_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'src_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'obj_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 1)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_page_versions "
                    "(principal_id, page_version_id, page_id, source_version_id, "
                    " content_sha256, observed_at, exact_render_sha256) VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnver_bbbbbbbbbbbbbbbbbbbbbbbb',"
                    " 'gnpg_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'ver_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',"
                    " '2026-08-17T10:00:00+00',"
                    " 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb')"
                )
            )
        command.downgrade(_config(), PRIOR)
        assert NEW_COLUMN not in _columns(engine, "goodnotes_page_versions")
        with engine.connect() as connection:
            digest = connection.execute(
                text("SELECT content_sha256 FROM knowledge.goodnotes_page_versions")
            ).scalar_one()
            assert digest == "a" * 64
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == PRIOR
    finally:
        engine.dispose()
