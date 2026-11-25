"""Additive GoodNotes notebook lineage, logical pages, and run ledger."""

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import Executable
from tests.pins import ALEMBIC_HEAD, ALEMBIC_REVISION_COUNT

from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "f8c3a1e6b247"
#: The current head, from the reviewed snapshot (`tests/pins.json`).
HEAD_REVISION: Final = ALEMBIC_HEAD
PRIOR: Final = "d4a8c1e7b930"
MIGRATION: Final = ROOT / (
    "migrations/versions/20260816_f8c3a1e6b247_add_goodnotes_notebook_lineage_logical_.py"
)
DISPOSABLE_DATABASE: Final = "my_pa_goodnotes_lineage_migration_test"
NEW_TABLES: Final = frozenset(
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
NEW_VERSION_COLUMNS: Final = frozenset(
    {
        "logical_page_id",
        "normalized_render_sha256",
        "perceptual_hash",
        "render_width",
        "render_height",
        "renderer_name",
        "renderer_version",
        "render_profile_version",
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


def test_the_chain_has_one_head_and_this_revision_is_on_it() -> None:
    """On the chain, in order — not at the end of it.

    The name already said "is on it" while the assertion said "is the head", and
    the assertion is the half that rotted when `9def3c2e63bb` landed. One
    unbranched head, this revision reachable from it, and the ordered links
    below are what the tests in this module depend on; which revision happens to
    be last is not.
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
    assert "GoodNotesIdentityStatus" not in source
    assert "GoodNotesMatchMethod" not in source


def test_the_frozen_sql_names_lineage_tables_and_immutability() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f"CREATE TABLE knowledge.{table}" in source
    assert "ON DELETE CASCADE" not in source
    assert "ON DELETE RESTRICT" in source
    assert "one_goodnotes_snapshot_per_notebook_bytes" in source
    assert "one_current_goodnotes_notebook_path" in source
    assert "one_goodnotes_ingestion_request" in source
    assert "goodnotes_source_snapshots_are_immutable" in source
    assert "goodnotes_page_positions_are_immutable" in source
    assert (
        "page_number"
        not in source[source.index("goodnotes_logical_pages") :].split(
            "goodnotes_page_positions", 1
        )[0]
    )
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
        assert _tables(engine) >= NEW_TABLES | LEGACY_TABLES
        assert _columns(engine, "goodnotes_page_versions") >= NEW_VERSION_COLUMNS
    finally:
        engine.dispose()


@pytest.mark.database
def test_prior_head_to_new_head_preserves_ordinal_pages(disposable_database: str) -> None:
    command.upgrade(_config(), PRIOR)
    engine = create_database_engine(disposable_database)
    try:
        assert NEW_TABLES.isdisjoint(_tables(engine))
        assert NEW_VERSION_COLUMNS.isdisjoint(_columns(engine, "goodnotes_page_versions"))
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
                    " '2026-08-12T10:00:00+00')"
                )
            )
        command.upgrade(_config(), REVISION)
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT page_id, page_number, logical_page_id, normalized_render_sha256 "
                    "FROM knowledge.goodnotes_pages "
                    "JOIN knowledge.goodnotes_page_versions USING (principal_id, page_id)"
                )
            ).one()
            assert row.page_id == "gnpg_aaaaaaaaaaaaaaaaaaaaaaaa"
            assert row.page_number == 1
            assert row.logical_page_id is None
            assert row.normalized_render_sha256 is None
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == REVISION
        assert _tables(engine) >= NEW_TABLES
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrade_removes_lineage_and_leaves_ordinal_pages(disposable_database: str) -> None:
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
        command.downgrade(_config(), PRIOR)
        remaining = _tables(engine)
        assert NEW_TABLES.isdisjoint(remaining)
        assert remaining >= LEGACY_TABLES
        assert NEW_VERSION_COLUMNS.isdisjoint(_columns(engine, "goodnotes_page_versions"))
        with engine.connect() as connection:
            page_id = connection.execute(
                text("SELECT page_id FROM knowledge.goodnotes_pages")
            ).scalar_one()
            assert page_id == "gnpg_aaaaaaaaaaaaaaaaaaaaaaaa"
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert revision == PRIOR
    finally:
        engine.dispose()


@pytest.mark.database
def test_exact_byte_replay_and_immutability_are_server_properties(
    disposable_database: str,
) -> None:
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)
    try:
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
            connection.execute(
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
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_source_snapshots "
                    "(principal_id, snapshot_id, notebook_id, source_object_id, "
                    " observed_path, raw_sha256, size_bytes, page_count, observed_at, "
                    " settled_at, run_id) VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnsnap_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnnb_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'obj_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'Inbox/alpha.pdf',"
                    " 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',"
                    " 32, 1, '2026-08-16T12:00:00+00', '2026-08-16T12:00:00+00',"
                    " 'gnrun_aaaaaaaaaaaaaaaaaaaaaaaa')"
                )
            )
        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_source_snapshots "
                    "(principal_id, snapshot_id, notebook_id, source_object_id, "
                    " observed_path, raw_sha256, size_bytes, page_count, observed_at, "
                    " settled_at, run_id) VALUES ("
                    " 'prn_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'gnsnap_cccccccccccccccccccccccc',"
                    " 'gnnb_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'obj_aaaaaaaaaaaaaaaaaaaaaaaa',"
                    " 'Inbox/renamed.pdf',"
                    " 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',"
                    " 99, 2, '2026-08-16T13:00:00+00', '2026-08-16T13:00:00+00',"
                    " 'gnrun_aaaaaaaaaaaaaaaaaaaaaaaa')"
                )
            )
        with engine.begin() as connection, pytest.raises(Exception, match="append only"):
            connection.execute(
                text(
                    "UPDATE knowledge.goodnotes_source_snapshots "
                    "SET page_count = 9 WHERE snapshot_id = 'gnsnap_aaaaaaaaaaaaaaaaaaaaaaaa'"
                )
            )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE knowledge.goodnotes_ingestion_runs "
                    "SET status = 'SUCCEEDED' WHERE run_id = 'gnrun_aaaaaaaaaaaaaaaaaaaaaaaa'"
                )
            )
            status = connection.execute(
                text(
                    "SELECT status FROM knowledge.goodnotes_ingestion_runs "
                    "WHERE run_id = 'gnrun_aaaaaaaaaaaaaaaaaaaaaaaa'"
                )
            ).scalar_one()
            assert status == "SUCCEEDED"
    finally:
        engine.dispose()


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; migration tests still drive Alembic themselves."""
    return empty_database_url
