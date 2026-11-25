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
from tests.pins import ALEMBIC_REVISION_COUNT
from tests.schema.communications_reads_vocabulary_contract import (
    COMMUNICATIONS_READ_CAPABILITIES,
    COMMUNICATIONS_READ_PURPOSES,
)
from tests.schema.files_workspace_vocabulary_contract import FILES_CAPABILITIES, FILES_PURPOSES
from tests.schema.knowledge_schema_ahead_contract import admitted_ahead
from tests.schema.lineage_schema_ahead_contract import lineage_admitted_ahead

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, NativeSourceCapability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
DISPOSABLE_DATABASE: Final = "my_pa_goodnotes_semantic_proposal_migration_test"
SCHEMA: Final = "knowledge"
REVISION: Final = "d7e1a4c8b926"
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
    assert REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PREVIOUS
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
        assert _admitted(engine, "capability_is_known") == declared | (
            admitted_ahead("capability")
            | lineage_admitted_ahead("capability")
            | FILES_CAPABILITIES
            | COMMUNICATIONS_READ_CAPABILITIES
        )
        assert _admitted(engine, "purpose_is_known") == {member.value for member in Purpose} | (
            admitted_ahead("purpose")
            | lineage_admitted_ahead("purpose")
            | FILES_PURPOSES
            | COMMUNICATIONS_READ_PURPOSES
        )
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
