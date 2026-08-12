"""Static migration-chain evidence for the bounded GoodNotes tables."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
REVISION = "91d7b3e5a204"
PARENT = "f1a6c3e8b902"
MIGRATION = ROOT / "migrations/versions/20260812_91d7b3e5a204_add_bounded_goodnotes_ingestion.py"


def test_goodnotes_revision_is_on_the_single_candidate_chain() -> None:
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    revision = script.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == PARENT
    assert len(script.get_heads()) == 1
    ancestors = {item.revision for item in script.walk_revisions()}
    assert REVISION in ancestors


def test_goodnotes_schema_is_partitioned_append_only_and_has_lexical_indexes() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for table in (
        "goodnotes_pages",
        "goodnotes_page_versions",
        "goodnotes_region_proposals",
        "goodnotes_review_decisions",
        "goodnotes_reconciliation_receipts",
    ):
        block = source[source.index(f'"{table}"') :]
        assert '"principal_id"' in block[:2500]
    assert "goodnotes_page_versions_are_immutable" in source
    assert "goodnotes_region_proposals_are_immutable" in source
    assert "goodnotes_transcription_fts" in source
    assert "goodnotes_corrected_text_fts" in source
    for semantic_primitive in ("pgvector", "halfvec", "embedding", "hnsw", "ivfflat"):
        assert semantic_primitive not in source.casefold()
