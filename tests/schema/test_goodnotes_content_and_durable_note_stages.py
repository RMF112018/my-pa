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
INTELLIGENCE_REVISION: Final = "e9b2c4d7a150"
ATTEMPT_REVISION: Final = "f4c1a8e6b205"
ENTITY_REVISION: Final = "9def3c2e63bb"
ENTITY_KIND_REVISION: Final = "d9c4e1a7b628"
GROUNDING_REVISION: Final = "b7f2c9e4a618"
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
HEAD_REVISION: Final = INTELLIGENCE_REVISION
MIGRATION: Final = ROOT / (
    "migrations/versions/20260817_a4d9c2e7b815_admit_goodnotes_content_and_durable_note_stages.py"
)
CAPABILITIES_ADDED: Final[frozenset[str]] = frozenset({"goodnotes.content"})
PURPOSES_ADDED: Final[frozenset[str]] = frozenset({"goodnotes_content"})
NEW_TABLES: Final[frozenset[str]] = frozenset(
    {"goodnotes_ingestion_run_stages", "goodnotes_page_rasters"}
)

#: The constant whose presence marks a revision as one that freezes the audited
#: capability vocabulary. A revision that creates tables and admits nothing does
#: not write it, which is how `_latest_vocabulary_migration` tells the two apart.
_ADMITTING_CONSTANT: Final = "_CAPABILITIES_AT_THIS_REVISION"


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


def _latest_declaring(constant: str) -> Path:
    """The most recent revision in the chain that freezes `constant`.

    Capability vocabulary and purpose vocabulary are frozen independently: a
    revision may widen one and leave the other alone, and `e4d7b2f9a316` does
    exactly that. Asking a single "latest admitting revision" for both is asking
    one revision to answer for a set it never touched.
    """
    script = ScriptDirectory.from_config(_config())
    for entry in script.walk_revisions():
        path = Path(entry.path)
        if f"{constant}: Final = (" in path.read_text(encoding="utf-8"):
            return path
    raise AssertionError(
        f"no revision in the chain declares {constant}; the audited closed set "
        "is then installed by nothing and this comparison is vacuous"
    )


def _latest_vocabulary_migration() -> Path:
    """The file of the most recent revision that *freezes* the audited vocabulary.

    This read `script.get_revision(head).path` until `d2b8f5c04e71`, and the
    head was the right file only for as long as every revision widened the
    vocabulary. `d2b8f5c04e71` creates three tables and admits nothing, so it
    declares no `_CAPABILITIES_AT_THIS_REVISION` at all and the head reader
    raised on a constant that was never there — a DDL-only revision is not a
    vocabulary claim, and asking it for one is asking the wrong revision.

    So the search is for the property the claim is actually about: the last
    revision in the chain that states a frozen capability vocabulary is the one
    whose statement a running database is currently enforcing, because `D-69`
    means no later revision has touched the closed set. `walk_revisions()` walks
    head-first, so the first match is that revision. Derived rather than written
    down because a literal here would have to be edited by every later work
    package — and, as `d2b8f5c04e71` has just shown, by DDL-only ones too.
    """
    script = ScriptDirectory.from_config(_config())
    heads = list(script.get_heads())
    assert len(heads) == 1, f"expected a single Alembic head, found {heads}"
    for entry in script.walk_revisions():
        path = Path(entry.path)
        if f"{_ADMITTING_CONSTANT}: Final = (" in path.read_text(encoding="utf-8"):
            return path
    raise AssertionError(
        f"no revision in the chain declares {_ADMITTING_CONSTANT}; the audited "
        "closed sets are then installed by nothing and this comparison is vacuous"
    )


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
    assert script.get_revision("f4c1a8e6b205").down_revision == ENTITY_KIND_REVISION
    assert script.get_revision(ATTEMPT_REVISION).down_revision == ENTITY_KIND_REVISION
    assert script.get_revision(ENTITY_REVISION).down_revision == ATTEMPT_REVISION
    assert script.get_revision(ALIAS_REVISION).down_revision == ENTITY_REVISION
    assert script.get_revision(CAPABILITY_REVISION).down_revision == ALIAS_REVISION
    assert script.get_revision(GOVERNANCE_REVISION).down_revision == CAPABILITY_REVISION
    assert script.get_revision(QUEUE_REVISION).down_revision == GOVERNANCE_REVISION
    assert script.get_revision(MENTION_REVISION).down_revision == QUEUE_REVISION
    assert script.get_revision(HEAD_REVISION).down_revision == MENTION_REVISION
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == 65


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
    _ADMITTING_CONSTANT,
    "_CAPABILITIES_BEFORE_THIS_REVISION",
    "_PURPOSES_AT_THIS_REVISION",
    "_PURPOSES_BEFORE_THIS_REVISION",
)


def test_the_frozen_literals_are_the_domain_at_head() -> None:
    """The last *admitting* revision's frozen vocabulary is the domain, exactly.

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
    dispatches on. Which revision carries it was read as "the head" until
    `d2b8f5c04e71`, and that was a near-miss rather than the claim: the head is
    the revision that carries the vocabulary only while every revision admits
    something. `d2b8f5c04e71` creates the entity observation, proposal, and
    merge-lineage tables and admits nothing, so it states no vocabulary to
    compare — and the closed set a database migrated to it enforces is still the
    one `c1a7e4b93d58` installed, because `D-69` guarantees that only a revision
    which writes the set out can have changed it. The subject is therefore the
    most recent revision that *froze* a vocabulary, derived by walking the chain
    head-first for one that declares `_CAPABILITIES_AT_THIS_REVISION`; a
    DDL-only revision moves the head without moving that, and the rule survives
    the next one too. `a4d9c2e7b815` keeps the half that is still its own: the
    delta it added over its predecessor, and the sorted order of every literal
    it froze.

    **Corrected 2026-08-19.** Three sentences above named `d2b8f5c04e71` as the
    revision that admits the five `entities.*` capabilities and the `entity_read`
    purpose. It does not, and this docstring said so itself two paragraphs down —
    `d2b8f5c04e71` "creates the entity observation, proposal, and merge-lineage
    tables and admits nothing". `c1a7e4b93d58` is the admitting revision, which
    is what `CAPABILITY_REVISION` in this module has always held; only the prose
    disagreed. Derived rather than reasoned about: `grep -rln "entities\\."
    migrations/versions/` and `grep -rln "entity_read" migrations/versions/` each
    return exactly one file, and it is `c1a7e4b93d58`'s.
    """
    admitting = _latest_vocabulary_migration()
    admitted = frozenset(_frozen_names(admitting, _ADMITTING_CONSTANT))
    declared = {member.value for member in Capability} | {
        member.value for member in NativeSourceCapability
    }
    assert admitted <= declared
    # This module's own revision, kept separate from the head's. `admitted` is
    # the *latest* admitting revision's vocabulary; subtracting this revision's
    # predecessor from it would compare two different revisions' sets and call
    # the difference this one's delta.
    this_purposes = _frozen_literals("_PURPOSES_AT_THIS_REVISION")
    assert this_purposes <= {member.value for member in Purpose}
    assert (
        _frozen_literals("_CAPABILITIES_AT_THIS_REVISION")
        - _frozen_literals("_CAPABILITIES_BEFORE_THIS_REVISION")
        == CAPABILITIES_ADDED
    )
    assert this_purposes - _frozen_literals("_PURPOSES_BEFORE_THIS_REVISION") == PURPOSES_ADDED
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
    assert admitted == declared, (
        f"the last admitting revision {admitting.name} freezes a capability vocabulary "
        f"that is not the domain; the difference is {sorted(admitted ^ declared)}"
    )
    # Asked of the last revision that freezes *purposes*, which is not always the
    # last that freezes capabilities. `e4d7b2f9a316` admits one capability and
    # leaves the purpose set untouched, so it declares no purpose vocabulary —
    # and demanding one of it would force every capability-only revision to
    # restate a closed set it never altered, which is how a frozen literal stops
    # meaning "what this revision installed".
    purposes_at = _latest_declaring("_PURPOSES_AT_THIS_REVISION")
    purposes = frozenset(_frozen_names(purposes_at, "_PURPOSES_AT_THIS_REVISION"))
    assert purposes == {member.value for member in Purpose}, (
        f"the last purpose-freezing revision {purposes_at.name} freezes a purpose "
        f"vocabulary that is not the domain; the difference is "
        f"{sorted(purposes ^ {member.value for member in Purpose})}"
    )

    this_revision = _frozen_literals(_ADMITTING_CONSTANT)
    this_purposes = _frozen_literals("_PURPOSES_AT_THIS_REVISION")
    before = _frozen_literals("_CAPABILITIES_BEFORE_THIS_REVISION")
    assert this_revision - before == CAPABILITIES_ADDED
    assert this_purposes - _frozen_literals("_PURPOSES_BEFORE_THIS_REVISION") == PURPOSES_ADDED
    for path in (MIGRATION, admitting, _latest_declaring("_PURPOSES_AT_THIS_REVISION")):
        for constant in _FROZEN_CONSTANTS:
            if f"{constant}: Final = (" not in path.read_text(encoding="utf-8"):
                # A revision may widen one vocabulary and not the other, and
                # since `e4d7b2f9a316` one does: it admits a capability and
                # leaves the purposes alone, so it declares no purpose constant
                # at all. Demanding both of every admitting revision would force
                # a revision to restate a set it did not touch.
                continue
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
