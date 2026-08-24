"""Additive GoodNotes NOTE_UNIT occurrence, revision, and run-change persistence."""

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
REVISION: Final = "c9e2b6a4d813"
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
HEAD_REVISION: Final = PHASE_A_REVISION
PRIOR: Final = "f8c3a1e6b247"
MIGRATION: Final = ROOT / (
    "migrations/versions/20260816_c9e2b6a4d813_add_goodnotes_note_unit_occurrence_.py"
)
DISPOSABLE_DATABASE: Final = "my_pa_goodnotes_note_occurrence_migration_test"
NEW_TABLES: Final = frozenset(
    {
        "goodnotes_notes",
        "goodnotes_note_occurrences",
        "goodnotes_note_revisions",
        "goodnotes_note_links",
        "goodnotes_run_note_changes",
    }
)
LINEAGE_TABLES: Final = frozenset(
    {
        "goodnotes_notebooks",
        "goodnotes_notebook_paths",
        "goodnotes_source_snapshots",
        "goodnotes_logical_pages",
        "goodnotes_page_positions",
        "goodnotes_ingestion_runs",
    }
)
LEGACY_TABLES: Final = frozenset(
    {
        "goodnotes_pages",
        "goodnotes_page_versions",
        "goodnotes_region_proposals",
        "goodnotes_review_decisions",
        "goodnotes_reconciliation_receipts",
    }
)


def _administer(maintenance: Engine, *statements: Executable) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def _tables(engine: Engine, schema: str = "knowledge") -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
                ),
                {"schema": schema},
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
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PRIOR
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == 69


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
    assert "GoodNotesNoteChangeState" not in source
    assert "GoodNotesNoteClass" not in source
    assert "GoodNotesNoteLinkKind" not in source
    assert "GoodNotesIdentityStatus" not in source


def test_the_frozen_sql_names_note_unit_tables_and_immutability() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f"CREATE TABLE knowledge.{table}" in source
    assert "ON DELETE CASCADE" not in source
    assert "ON DELETE RESTRICT" in source
    assert "one_goodnotes_occurrence_geometry" in source
    assert "one_goodnotes_run_occurrence_change" in source
    assert "one_goodnotes_note_link_target" in source
    assert "goodnotes_note_revisions_are_immutable" in source
    assert "goodnotes_run_note_changes_are_immutable" in source
    assert "REMOVED_OR_NO_LONGER_PRESENT" in source
    assert "geometry_key" in source
    assert "gnreg_" not in source
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
        assert _tables(engine) >= NEW_TABLES | LINEAGE_TABLES | LEGACY_TABLES
    finally:
        engine.dispose()


@pytest.mark.database
def test_prior_head_to_new_head_preserves_lineage_rows(disposable_database: str) -> None:
    command.upgrade(_config(), PRIOR)
    engine = create_database_engine(disposable_database)
    try:
        assert NEW_TABLES.isdisjoint(_tables(engine))
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_notebooks "
                    "(principal_id, notebook_id, source_root_id, identity_status, "
                    " created_at, last_observed_at) VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnnb_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'icloud-goodnotes', 'ACTIVE',"
                    " '2026-08-16T12:00:00+00', '2026-08-16T12:00:00+00')"
                )
            )
        command.upgrade(_config(), "head")
        with engine.connect() as connection:
            notebook_id = connection.execute(
                text("SELECT notebook_id FROM knowledge.goodnotes_notebooks")
            ).scalar_one()
            assert notebook_id == "gnnb_aaaaaaaaaaaaaaaaaaaaaaaa"
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == HEAD_REVISION
        assert _tables(engine) >= NEW_TABLES | LINEAGE_TABLES
    finally:
        engine.dispose()


def _seed_note_parents(connection: object) -> None:
    connection.execute(  # type: ignore[union-attr]
        text(
            "INSERT INTO knowledge.goodnotes_notebooks "
            "(principal_id, notebook_id, source_root_id, identity_status, "
            " created_at, last_observed_at) VALUES ("
            " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
            " 'gnnb_aaaaaaaaaaaaaaaaaaaaaaaa',"
            " 'icloud-goodnotes', 'ACTIVE',"
            " '2026-08-16T12:00:00+00', '2026-08-16T12:00:00+00')"
        )
    )
    connection.execute(  # type: ignore[union-attr]
        text(
            "INSERT INTO knowledge.goodnotes_logical_pages "
            "(principal_id, logical_page_id, notebook_id, created_at, "
            " last_seen_at, identity_status) VALUES ("
            " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
            " 'gnlp_aaaaaaaaaaaaaaaaaaaaaaaa',"
            " 'gnnb_aaaaaaaaaaaaaaaaaaaaaaaa',"
            " '2026-08-16T12:00:00+00', '2026-08-16T12:00:00+00', 'ACTIVE')"
        )
    )
    connection.execute(  # type: ignore[union-attr]
        text(
            "INSERT INTO knowledge.goodnotes_ingestion_runs "
            "(principal_id, run_id, source_root_id, trigger_type, request_id, "
            " idempotency_key, request_fingerprint, started_at, status) VALUES ("
            " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
            " 'gnrun_aaaaaaaaaaaaaaaaaaaaaaaa',"
            " 'icloud-goodnotes', 'MANUAL', 'req-1', 'req-1',"
            " 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',"
            " '2026-08-16T12:00:00+00', 'RUNNING')"
        )
    )
    connection.execute(  # type: ignore[union-attr]
        text(
            "INSERT INTO knowledge.goodnotes_notes "
            "(principal_id, note_id, notebook_id, identity_status, "
            " created_at, last_seen_at) VALUES ("
            " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
            " 'gnnt_aaaaaaaaaaaaaaaaaaaaaaaa',"
            " 'gnnb_aaaaaaaaaaaaaaaaaaaaaaaa', 'ACTIVE',"
            " '2026-08-16T12:00:00+00', '2026-08-16T12:00:00+00')"
        )
    )
    connection.execute(  # type: ignore[union-attr]
        text(
            "INSERT INTO knowledge.goodnotes_note_occurrences "
            "(principal_id, occurrence_id, note_id, logical_page_id, "
            " x_min, y_min, width, height, geometry_key, identity_status, "
            " created_at, last_seen_at) VALUES ("
            " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
            " 'gnocc_aaaaaaaaaaaaaaaaaaaaaaaa',"
            " 'gnnt_aaaaaaaaaaaaaaaaaaaaaaaa',"
            " 'gnlp_aaaaaaaaaaaaaaaaaaaaaaaa',"
            " 0.1000, 0.2000, 0.3000, 0.1500,"
            " '0.1000,0.2000,0.3000,0.1500:none', 'ACTIVE',"
            " '2026-08-16T12:00:00+00', '2026-08-16T12:00:00+00')"
        )
    )


@pytest.mark.database
def test_checks_uniqueness_and_immutability_are_server_properties(
    disposable_database: str,
) -> None:
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)
    try:
        with engine.begin() as connection:
            _seed_note_parents(connection)
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_note_revisions "
                    "(principal_id, revision_id, note_id, schema_version, "
                    " analyzer_name, analyzer_version, transcription, created_at) VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnrev_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnnt_aaaaaaaaaaaaaaaaaaaaaaaa', 'note-unit.v1',"
                    " 'synthetic', '1', 'follow up Tuesday',"
                    " '2026-08-16T12:00:00+00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_run_note_changes "
                    "(principal_id, change_id, run_id, note_id, occurrence_id, "
                    " change_state, created_at) VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnchg_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnrun_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnnt_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnocc_aaaaaaaaaaaaaaaaaaaaaaaa', 'NEW',"
                    " '2026-08-16T12:00:00+00')"
                )
            )
        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_note_occurrences "
                    "(principal_id, occurrence_id, note_id, logical_page_id, "
                    " x_min, y_min, width, height, geometry_key, identity_status, "
                    " created_at, last_seen_at) VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnocc_bbbbbbbbbbbbbbbbbbbbbbbb',"
                    " 'gnnt_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnlp_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 0.8000, 0.1000, 0.3000, 0.1000,"
                    " '0.8000,0.1000,0.3000,0.1000:none', 'ACTIVE',"
                    " '2026-08-16T12:00:00+00', '2026-08-16T12:00:00+00')"
                )
            )
        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_run_note_changes "
                    "(principal_id, change_id, run_id, note_id, occurrence_id, "
                    " change_state, created_at) VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnchg_bbbbbbbbbbbbbbbbbbbbbbbb',"
                    " 'gnrun_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnnt_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnocc_aaaaaaaaaaaaaaaaaaaaaaaa', 'REVISED',"
                    " '2026-08-16T12:00:00+00')"
                )
            )
        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_run_note_changes "
                    "(principal_id, change_id, run_id, note_id, occurrence_id, "
                    " change_state, created_at) VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnchg_cccccccccccccccccccccccc',"
                    " 'gnrun_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnnt_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnocc_aaaaaaaaaaaaaaaaaaaaaaaa', 'UNKNOWN',"
                    " '2026-08-16T12:00:00+00')"
                )
            )
        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_notes "
                    "(principal_id, note_id, notebook_id, identity_status, "
                    " created_at, last_seen_at) VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnreg_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnnb_aaaaaaaaaaaaaaaaaaaaaaaa', 'ACTIVE',"
                    " '2026-08-16T12:00:00+00', '2026-08-16T12:00:00+00')"
                )
            )
        with engine.begin() as connection, pytest.raises(Exception, match="append only"):
            connection.execute(
                text(
                    "UPDATE knowledge.goodnotes_note_revisions "
                    "SET transcription = 'erased' "
                    "WHERE revision_id = 'gnrev_aaaaaaaaaaaaaaaaaaaaaaaa'"
                )
            )
        with engine.begin() as connection, pytest.raises(Exception, match="append only"):
            connection.execute(
                text(
                    "DELETE FROM knowledge.goodnotes_note_revisions "
                    "WHERE revision_id = 'gnrev_aaaaaaaaaaaaaaaaaaaaaaaa'"
                )
            )
        with engine.begin() as connection, pytest.raises(Exception, match="append only"):
            connection.execute(
                text(
                    "UPDATE knowledge.goodnotes_run_note_changes "
                    "SET change_state = 'UNCHANGED' "
                    "WHERE change_id = 'gnchg_aaaaaaaaaaaaaaaaaaaaaaaa'"
                )
            )
        with engine.begin() as connection, pytest.raises(Exception, match="append only"):
            connection.execute(
                text(
                    "DELETE FROM knowledge.goodnotes_run_note_changes "
                    "WHERE change_id = 'gnchg_aaaaaaaaaaaaaaaaaaaaaaaa'"
                )
            )
    finally:
        engine.dispose()
