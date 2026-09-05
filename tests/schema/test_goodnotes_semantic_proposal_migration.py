"""Admit `goodnotes.work` / `goodnotes.propose` and create proposal receipts.

`d7e1a4c8b926` widens the audited vocabulary and creates
`knowledge.goodnotes_semantic_proposals`. It imports neither a domain enum
(`D-69`) nor `tables.py` (`D-48`).
"""

from __future__ import annotations

import ast
import io
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, NativeSourceCapability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
DISPOSABLE_DATABASE: Final = "my_pa_goodnotes_semantic_proposal_migration_test"
SCHEMA: Final = "knowledge"
REVISION: Final = "d7e1a4c8b926"
DELIVERY_REVISION: Final = "e8c1b5a7d204"
EXACT_RENDER_REVISION: Final = "c3e9a7f1b204"
CONTENT_REVISION: Final = "a4d9c2e7b815"
GROUNDING_REVISION: Final = "b7f2c9e4a618"
ENTITY_KIND_REVISION: Final = "d9c4e1a7b628"
INTELLIGENCE_REVISION: Final = "e9b2c4d7a150"
ATTEMPT_REVISION: Final = "f4c1a8e6b205"
ENTITY_REVISION: Final = "9def3c2e63bb"
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
PHASE_B_START: Final = "c7a1f04b9e63"
#: The chain's current head is `6a2f9d1c4b80` (GoodNotes pull/review), serialized
#: as the direct child of `c3f8a1d07e94`. That graph-vocabulary parent is additive on
#: `b8e4d1a6c073`, whose RI-ENT-WP-12 migration backfills one
#: `display`-typed `entity_names` row per active `entities` row -- `display_value`
#: from `entities.display_name`, `normalized_value` from `entities.canonical_name`,
#: never a `legal` name -- and writes no `entity_project_participations` row
#: (RULING-M10). It was written against `c99cd8ed8d1c` and re-parented onto
#: `16f05c46b8c3` once RI-ENT-WP-10/11 merged (RULING-M11), so the pair stand as one
#: chain rather than two heads. `16f05c46b8c3` (RI-ENT-WP-10/11) widens three
#: closed-set CHECKs -- `audit_events.capability_is_known` (115 -> 135),
#: `entity_mutation_events.a_mutated_record_family_is_known` (6 -> 11) and
#: `entity_proposals.an_accepted_proposal_record_family_is_known` (6 -> 11) -- to admit
#: RI-ENT-WP-10's five entity reads and RI-ENT-WP-11's fifteen entity mutation contracts,
#: creating and altering no table; it was itself re-parented from `c99cd8ed8d1c` onto
#: `2c00c9ac64bc` (UI-IMP-WP02 auth persistence) for the same reason. `2c00c9ac64bc`
#: adds WebAuthn credential, challenge, recovery-code and opaque session tables, and is
#: itself additive on `c99cd8ed8d1c` (RI-ENT-WP-08's blocker-clearing pass), which
#: renames the seeded `entity_relationship_types` row `design_coordinates_with` to
#: `design_coordination_with`; that in turn stacked on `1cda4d536268` (RI-ENT-WP-07).
#: Written out rather than derived so chain drift fails here rather than passing.
HEAD_REVISION: Final = "6a2f9d1c4b80"
PREVIOUS: Final = "c9e2b6a4d813"
MIGRATION: Final = ROOT / (
    "migrations/versions/20260816_d7e1a4c8b926_admit_goodnotes_work_and_propose.py"
)
CAPABILITIES_ADDED: Final[frozenset[str]] = frozenset({"goodnotes.propose", "goodnotes.work"})
PURPOSES_ADDED: Final[frozenset[str]] = frozenset({"goodnotes_proposal", "goodnotes_work"})
WHEN: Final = datetime(2026, 8, 16, 19, 0, tzinfo=UTC)

_CONSTRAINT: Final = text(
    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
    "JOIN pg_class t ON t.oid = c.conrelid "
    "JOIN pg_namespace n ON n.oid = t.relnamespace "
    "WHERE n.nspname = :schema AND t.relname = :table AND c.conname = :name"
)
_AUDIT_INSERT: Final = text(
    "INSERT INTO knowledge.audit_events (audit_id, correlation_id, principal_id, "
    " capability, purpose, outcome, policy_version, scope_source_id_count, recorded_at) "
    "VALUES (:audit, :correlation, :principal, :capability, :purpose, "
    " 'allowed', 'policy-v1', 0, :at)"
)


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def _frozen_literals(constant: str) -> frozenset[str]:
    source = MIGRATION.read_text(encoding="utf-8")
    start = source.index(f"{constant}: Final = (")
    end = source.index("\n)", start)
    return frozenset(re.findall(r"'([^']+)'", source[start:end]))


def _admitted(engine: Engine, constraint: str) -> frozenset[str]:
    with engine.connect() as connection:
        definition = connection.execute(
            _CONSTRAINT, {"schema": SCHEMA, "table": "audit_events", "name": constraint}
        ).scalar_one()
    return frozenset(re.findall(r"'([^']+)'::text", str(definition)))


def _tables(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
                ),
                {"schema": SCHEMA},
            ).scalars()
        )


def _record(engine: Engine, capability: str, purpose: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            _AUDIT_INSERT,
            {
                "audit": issue_identifier(IdKind.AUDIT),
                "correlation": issue_identifier(IdKind.CORRELATION),
                "principal": issue_identifier(IdKind.PRINCIPAL),
                "capability": capability,
                "purpose": purpose,
                "at": WHEN,
            },
        )


def test_the_chain_has_one_head_and_this_revision_is_on_it() -> None:
    """On the chain, in order — not at the end of it.

    The name already said "is on it" while the assertion said "is the head", and
    the assertion is the half that rotted when `9def3c2e63bb` landed. One
    unbranched head, this revision reachable from it, and the ordered links
    below are what this module depends on; which revision happens to be last is
    not.
    """
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert script.get_revision(DELIVERY_REVISION).down_revision == REVISION
    assert script.get_revision(EXACT_RENDER_REVISION).down_revision == DELIVERY_REVISION
    assert script.get_revision(CONTENT_REVISION).down_revision == EXACT_RENDER_REVISION
    assert script.get_revision(GROUNDING_REVISION).down_revision == CONTENT_REVISION
    assert script.get_revision(ENTITY_KIND_REVISION).down_revision == GROUNDING_REVISION
    assert script.get_revision("f4c1a8e6b205").down_revision == ENTITY_KIND_REVISION
    assert script.get_revision(ATTEMPT_REVISION).down_revision == ENTITY_KIND_REVISION
    assert script.get_revision(ENTITY_REVISION).down_revision == ATTEMPT_REVISION
    assert script.get_revision(ALIAS_REVISION).down_revision == ENTITY_REVISION
    assert script.get_revision(CAPABILITY_REVISION).down_revision == ALIAS_REVISION
    assert script.get_revision(GOVERNANCE_REVISION).down_revision == CAPABILITY_REVISION
    assert script.get_revision(QUEUE_REVISION).down_revision == GOVERNANCE_REVISION
    assert script.get_revision(MENTION_REVISION).down_revision == QUEUE_REVISION
    assert script.get_revision(INTELLIGENCE_REVISION).down_revision == MENTION_REVISION
    assert script.get_revision(WORK_REVISION).down_revision == INTELLIGENCE_REVISION
    assert script.get_revision(MEMORY_REVISION).down_revision == WORK_REVISION
    assert script.get_revision(PHASE_A_REVISION).down_revision == LIFECYCLE_REVISION
    assert script.get_revision(GSQS_REVISION).down_revision == PHASE_A_REVISION
    assert script.get_revision(PHASE_B_START).down_revision == GSQS_REVISION
    assert script.get_revision(PHASE_B_REVISION).down_revision == "a1f7d3c85e40"
    assert script.get_revision(PHASE_B_HEAD).down_revision == PHASE_B_REVISION
    assert script.get_heads() == [HEAD_REVISION]
    # 91 migration files: 90 through `c3f8a1d07e94` as described below, plus
    # `6a2f9d1c4b80` (GoodNotes pull/review) as its direct child. The first 85
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
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == 91


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


def test_the_frozen_literals_are_the_domain_at_head() -> None:
    admitted = _frozen_literals("_CAPABILITIES_AT_THIS_REVISION")
    declared = {member.value for member in Capability} | {
        member.value for member in NativeSourceCapability
    }
    assert admitted <= declared
    purposes = _frozen_literals("_PURPOSES_AT_THIS_REVISION")
    assert purposes <= {member.value for member in Purpose}
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


def test_the_frozen_sql_names_the_receipt_table_and_immutability() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE {SCHEMA}.goodnotes_semantic_proposals" in source
    assert "ON DELETE RESTRICT" in source
    assert "ON DELETE CASCADE" not in source
    assert "one_goodnotes_semantic_proposal_key" in source
    assert "goodnotes_semantic_proposals_are_immutable" in source
    assert "goodnotes_run_note_changes" not in source.split("CREATE TABLE")[1]


@pytest.mark.database
def test_empty_to_head_and_prior_to_head_admit_the_new_names(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        declared = {member.value for member in Capability} | {
            member.value for member in NativeSourceCapability
        }
        assert _admitted(engine, "capability_is_known") == declared
        assert _admitted(engine, "purpose_is_known") == {member.value for member in Purpose}
        assert "goodnotes.work" in _admitted(engine, "capability_is_known")
        assert "goodnotes.propose" in _admitted(engine, "capability_is_known")
        assert "knowledge.search" in _admitted(engine, "capability_is_known")
        assert "goodnotes_semantic_proposals" in _tables(engine)

        command.downgrade(_config(), PREVIOUS)
        assert "goodnotes_semantic_proposals" not in _tables(engine)
        with pytest.raises(IntegrityError):
            _record(engine, "goodnotes.work", "knowledge_search")
        with pytest.raises(IntegrityError):
            _record(engine, "knowledge.search", "goodnotes_work")
        _record(engine, "knowledge.search", "knowledge_search")

        command.upgrade(_config(), "head")
        assert "goodnotes_semantic_proposals" in _tables(engine)
        _record(engine, "goodnotes.work", "goodnotes_work")
        _record(engine, "goodnotes.propose", "goodnotes_proposal")
    finally:
        engine.dispose()


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; migration tests still drive Alembic themselves."""
    return empty_database_url
