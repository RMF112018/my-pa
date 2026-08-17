"""Admit `goodnotes.content` and create durable-note stage and raster tables.

`a4d9c2e7b815` widens the audited vocabulary and creates
`knowledge.goodnotes_ingestion_run_stages` and `knowledge.goodnotes_page_rasters`.
It imports neither a domain enum (`D-69`) nor `tables.py` (`D-48`).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

from alembic.config import Config
from alembic.script import ScriptDirectory

from my_pa.domain.identity.operation import Capability, NativeSourceCapability
from my_pa.domain.identity.purpose import Purpose

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "a4d9c2e7b815"
PRIOR: Final = "c3e9a7f1b204"
HEAD_REVISION: Final = "b7f2c9e4a618"
MIGRATION: Final = ROOT / (
    "migrations/versions/20260817_a4d9c2e7b815_admit_goodnotes_content_and_durable_note_stages.py"
)
CAPABILITIES_ADDED: Final[frozenset[str]] = frozenset({"goodnotes.content"})
PURPOSES_ADDED: Final[frozenset[str]] = frozenset({"goodnotes_content"})
NEW_TABLES: Final[frozenset[str]] = frozenset(
    {"goodnotes_ingestion_run_stages", "goodnotes_page_rasters"}
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def _frozen_literals(constant: str) -> frozenset[str]:
    source = MIGRATION.read_text(encoding="utf-8")
    start = source.index(f"{constant}: Final = (")
    end = source.index("\n)", start)
    return frozenset(re.findall(r"'([^']+)'", source[start:end]))


def test_the_chain_has_one_head_and_this_revision_is_the_head() -> None:
    script = ScriptDirectory.from_config(_config())
    assert list(script.get_heads()) == [HEAD_REVISION]
    assert script.get_revision(REVISION).down_revision == PRIOR
    assert script.get_revision(HEAD_REVISION).down_revision == REVISION
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == 56


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
    assert "Capability" not in source
    assert "Purpose" not in source
    assert "GoodNotesPipelineStage" not in source


def test_the_frozen_literals_are_the_domain_at_head() -> None:
    admitted = _frozen_literals("_CAPABILITIES_AT_THIS_REVISION")
    declared = {member.value for member in Capability} | {
        member.value for member in NativeSourceCapability
    }
    assert admitted == declared
    purposes = _frozen_literals("_PURPOSES_AT_THIS_REVISION")
    assert purposes == {member.value for member in Purpose}
    assert admitted - _frozen_literals("_CAPABILITIES_BEFORE_THIS_REVISION") == CAPABILITIES_ADDED
    assert purposes - _frozen_literals("_PURPOSES_BEFORE_THIS_REVISION") == PURPOSES_ADDED
    source = MIGRATION.read_text(encoding="utf-8")
    for constant in (
        "_CAPABILITIES_AT_THIS_REVISION",
        "_CAPABILITIES_BEFORE_THIS_REVISION",
        "_PURPOSES_AT_THIS_REVISION",
        "_PURPOSES_BEFORE_THIS_REVISION",
    ):
        start = source.index(f"{constant}: Final = (")
        end = source.index("\n)", start)
        names = re.findall(r"'([^']+)'", source[start:end])
        assert names == sorted(names), f"{constant} is not in sorted order"


def test_the_frozen_sql_names_the_stage_ledger_and_raster_cap() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f"CREATE TABLE {{SCHEMA}}.{table}" in source
    assert "ON DELETE CASCADE" not in source
    assert "byte_length BETWEEN 1 AND 2097152" in source
    assert "OBSERVE" in source
    assert "WAITING_PROPOSAL" in source
    assert "image/png" in source
    assert "png_bytes" in source
    for semantic in ("pgvector", "halfvec", "embedding", "hnsw", "ivfflat"):
        assert semantic not in source
