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
ATTEMPT_REVISION: Final = "f4c1a8e6b205"
ENTITY_REVISION: Final = "9def3c2e63bb"
ENTITY_KIND_REVISION: Final = "d9c4e1a7b628"
GROUNDING_REVISION: Final = "b7f2c9e4a618"
#: Where `upgrade head` lands, which the database tier reads back out of
#: `alembic_version`. That is a position in the chain rather than a property of
#: this revision, so it moves whenever a revision is added; the chain test below
#: is written not to depend on it.
ALIAS_REVISION: Final = "b7f4d1a92c36"
HEAD_REVISION: Final = "c1a7e4b93d58"
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


def _frozen_names(path: Path, constant: str) -> list[str]:
    """The literals one revision freezes under `constant`, in the order written."""
    source = path.read_text(encoding="utf-8")
    start = source.index(f"{constant}: Final = (")
    end = source.index("\n)", start)
    return re.findall(r"'([^']+)'", source[start:end])


def _frozen_literals(constant: str) -> frozenset[str]:
    return frozenset(_frozen_names(MIGRATION, constant))


def _head_migration() -> Path:
    """The file of whichever revision is currently at the head of the chain.

    Derived rather than written down, for the reason
    `test_the_chain_has_one_head_and_this_revision_is_on_it` no longer pins a
    head: the identity of the last revision moves every time one is written, and
    a literal here would have to be edited by every later work package.
    """
    script = ScriptDirectory.from_config(_config())
    heads = list(script.get_heads())
    assert len(heads) == 1, f"expected a single Alembic head, found {heads}"
    return Path(script.get_revision(heads[0]).path)


def test_the_chain_has_one_head_and_this_revision_is_on_it() -> None:
    """Deliberately not "is the head".

    Being the head is true only until the next revision is written, and pinning
    it here made every later work package edit this file — which is what
    `9def3c2e63bb` had to do. A single unbranched chain that contains this
    revision, on the predecessor it names, is the property everything below
    depends on, and it does not rot. See
    `tests/schema/test_extraction_schema_migration.py`'s chain test for the
    argument in full.
    """
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PRIOR
    assert script.get_revision(GROUNDING_REVISION).down_revision == REVISION
    assert script.get_revision(ENTITY_KIND_REVISION).down_revision == GROUNDING_REVISION
    assert script.get_revision(ATTEMPT_REVISION).down_revision == ENTITY_KIND_REVISION
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
    assert "Capability" not in source
    assert "Purpose" not in source
    assert "GoodNotesPipelineStage" not in source


#: Every frozen vocabulary a revision of this shape declares.
_FROZEN_CONSTANTS: Final = (
    "_CAPABILITIES_AT_THIS_REVISION",
    "_CAPABILITIES_BEFORE_THIS_REVISION",
    "_PURPOSES_AT_THIS_REVISION",
    "_PURPOSES_BEFORE_THIS_REVISION",
)


def test_the_frozen_literals_are_the_domain_at_head() -> None:
    """The *head* revision's frozen vocabulary is the domain, exactly.

    This assertion used to be made of `a4d9c2e7b815`, and it was correct for as
    long as `a4d9c2e7b815` was the last revision to widen the audited vocabulary.
    It is not any more, and it is not *stale* — it is a claim that revision no
    longer carries. `c1a7e4b93d58` admits the five `entities.*` capabilities and
    the `entity_read` purpose to the `audit_events` closed sets, so
    `a4d9c2e7b815`'s literals are now what they are required to be by `D-69`:
    frozen at the vocabulary that revision emitted when it merged, and therefore
    short of the domain by exactly what `c1a7e4b93d58` added. Asserting equality
    of the older revision would
    force every later widening to edit a merged migration, which is the defect
    `D-69` exists to forbid.

    So the claim is kept and moved rather than dropped: *some* revision's frozen
    literals still have to equal the live domain exactly — otherwise the closed
    set a running database enforces has drifted from the enum the application
    dispatches on — and the revision that carries it is whichever one is at the
    head, derived. `a4d9c2e7b815` keeps the half that is still its own: the delta
    it added over its predecessor, and the sorted order of every literal it
    froze.
    """
    head = _head_migration()
    admitted = frozenset(_frozen_names(head, "_CAPABILITIES_AT_THIS_REVISION"))
    declared = {member.value for member in Capability} | {
        member.value for member in NativeSourceCapability
    }
    assert admitted == declared, (
        f"the head revision {head.name} freezes a capability vocabulary that is not "
        f"the domain; the difference is {sorted(admitted ^ declared)}"
    )
    purposes = frozenset(_frozen_names(head, "_PURPOSES_AT_THIS_REVISION"))
    assert purposes == {member.value for member in Purpose}, (
        f"the head revision {head.name} freezes a purpose vocabulary that is not the "
        f"domain; the difference is {sorted(purposes ^ {member.value for member in Purpose})}"
    )

    this_revision = _frozen_literals("_CAPABILITIES_AT_THIS_REVISION")
    this_purposes = _frozen_literals("_PURPOSES_AT_THIS_REVISION")
    before = _frozen_literals("_CAPABILITIES_BEFORE_THIS_REVISION")
    assert this_revision - before == CAPABILITIES_ADDED
    assert this_purposes - _frozen_literals("_PURPOSES_BEFORE_THIS_REVISION") == PURPOSES_ADDED
    for path in (MIGRATION, head):
        for constant in _FROZEN_CONSTANTS:
            names = _frozen_names(path, constant)
            assert names == sorted(names), f"{path.name}'s {constant} is not in sorted order"


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
