"""Additive GoodNotes occurrence grounding: server crop identity and ledger FKs."""

from __future__ import annotations

import ast
import io
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.sql import Executable
from tests.pins import ALEMBIC_HEAD, ALEMBIC_REVISION_COUNT

from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "b7f2c9e4a618"
PRIOR: Final = "a4d9c2e7b815"
#: The current head, from the reviewed snapshot (`tests/pins.json`).
HEAD_REVISION: Final = ALEMBIC_HEAD
MIGRATION: Final = ROOT / (
    "migrations/versions/20260817_b7f2c9e4a618_ground_goodnotes_note_unit_visual_identity.py"
)
DISPOSABLE_DATABASE: Final = "my_pa_goodnotes_occurrence_grounding_migration_test"


def _administer(maintenance: Engine, *statements: Executable) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def _columns(engine: Engine, table: str, schema: str = "knowledge") -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": schema, "table": table},
            ).scalars()
        )


def test_the_chain_has_one_head_and_this_revision_is_on_it() -> None:
    """One unbranched head, and this revision on the chain below it.

    Asserts a single head and this revision's place on the chain rather than
    which revision happens to be last: the head it named was another revision's,
    so it had to be re-pinned by every work package that added one.
    """
    script = ScriptDirectory.from_config(_config())
    assert REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PRIOR
    # 92 migration files: `a4d8e31b2c90` (R8 promotion receipt) extends
    # the 91-file predecessor chain ending at `6a2f9d1c4b80` (pull/review),
    # whose parent is `c3f8a1d07e94`. The first 85
    # run through `1cda4d536268` (RI-ENT-WP-07), plus
    # `c99cd8ed8d1c` (commit `37ead78`, RI-ENT-WP-08's blocker-clearing pass),
    # which renames the seeded entity_relationship_types row
    # `design_coordinates_with` to `design_coordination_with`, plus
    # `2c00c9ac64bc` (UI-IMP-WP02), which adds WebAuthn credential, challenge,
    # recovery-code, and opaque session tables, plus `16f05c46b8c3`
    # (RI-ENT-WP-10/11), which widens the three closed-set CHECKs on
    # `audit_events`, `entity_mutation_events` and `entity_proposals` for
    # RI-ENT-WP-10's five entity reads and RI-ENT-WP-11's fifteen entity
    # mutation contracts, creating and altering no table, plus `b8e4d1a6c073`
    # (RI-ENT-WP-12), which backfills one `display`-typed `entity_names` row
    # per active `entities` row and was re-parented from `c99cd8ed8d1c` onto
    # `16f05c46b8c3` so the chain keeps one head (RULING-M11). Two branches
    # wrote 87 here from a shared baseline of 86, the base merge counted 88,
    # and RI-ENT-WP-12's integration counted 89 from the merged tree rather
    # than adding one to either side (RULING-M2).
    # R8 adds one receipt migration on the previous 91-revision chain.
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == ALEMBIC_REVISION_COUNT


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
    assert "GoodNotesNoteChangeState" not in source


def test_the_frozen_sql_is_additive_and_fail_closed() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "one_goodnotes_occurrence_note_pair" in source
    assert "goodnotes_note_revisions_occurrence_note_fk" in source
    assert "goodnotes_run_note_changes_occurrence_note_fk" in source
    assert "one_goodnotes_run_current_ambiguous_change" in source
    assert "goodnotes_change_identity_matches_state" in source
    assert "REMOVED_OR_NO_LONGER_PRESENT" in source
    assert "AMBIGUOUS" in source
    assert "DROP TABLE" not in source
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
        assert "page_version_id" in _columns(engine, "goodnotes_note_revisions")
        assert "revision_id" in _columns(engine, "goodnotes_run_note_changes")
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrade_drops_only_this_revision(disposable_database: str) -> None:
    command.upgrade(_config(), "head")
    command.downgrade(_config(), PRIOR)
    engine = create_database_engine(disposable_database)
    try:
        assert "page_version_id" not in _columns(engine, "goodnotes_note_revisions")
        assert "revision_id" not in _columns(engine, "goodnotes_run_note_changes")
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == PRIOR
            tables = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'knowledge' AND table_type = 'BASE TABLE'"
                    )
                ).scalars()
            )
        assert "goodnotes_notes" in tables
        assert "goodnotes_note_occurrences" in tables
        assert "goodnotes_page_rasters" in tables
    finally:
        engine.dispose()


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; migration tests still drive Alembic themselves."""
    return empty_database_url
