"""WP-KC-06: admit `context.feedback` and create preference event/projection tables.

`c6f1a8d3e204` widens the audited vocabulary and creates
`knowledge.context_preference_events` / `context_preference_current`.
It is no longer the chain head after `b7c4e9a2d518`. It imports neither a
domain enum (`D-69`) nor `tables.py` (`D-48`).
"""

from __future__ import annotations

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
from my_pa.domain.context.preference import ContextPreferenceAction, ContextPreferenceClass
from my_pa.domain.identity.operation import Capability, NativeSourceCapability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
DISPOSABLE_DATABASE: Final = "my_pa_context_feedback_migration_test"
SCHEMA: Final = "knowledge"

HEAD_REVISION: Final = "c6f1a8d3e204"
PREVIOUS: Final = "9b2d5f8c3e01"

CAPABILITIES_ADDED: Final[frozenset[str]] = frozenset({"context.feedback"})
PURPOSES_ADDED: Final[frozenset[str]] = frozenset({"context_preference"})

WHEN: Final = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

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


def _revision_source(revision: str) -> str:
    matches = [
        path for path in (ROOT / "migrations" / "versions").glob("*.py") if revision in path.name
    ]
    assert len(matches) == 1, f"{revision} names {len(matches)} revision files"
    return matches[0].read_text(encoding="utf-8")


def _frozen_literals(constant: str) -> frozenset[str]:
    source = _revision_source(HEAD_REVISION)
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


def test_the_chain_has_one_head_and_this_revision_is_in_the_chain() -> None:
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert HEAD_REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(HEAD_REVISION).down_revision == PREVIOUS
    # 79 since `7e114f822af2` (RI-ENT-WP-02) added the entity_names/
    # entity_organization_profiles migration on top of this chain; 80 since
    # `441b071bf37b` (RI-ENT-WP-03) added the entity_addresses/
    # entity_communication_methods migration on top of that; 81 since
    # `f5b06925857e` (RI-ENT-WP-04) added the entity_project_participations/
    # taxonomy migration on top of that; 82 since `17149a48fa30`
    # (RI-ENT-WP-05) added the entity_person_organization_affiliations
    # migration on top of that; 83 since `8dc3619891bb` (RI-ENT-WP-06a)
    # added the entity_relationship_types taxonomy migration on top of that;
    # 84 since `9a3f6c1e8d24` (RI-ENT-WP-06b) widened the identity-correction
    # family vocabulary on top of that; 85 since `1cda4d536268`
    # (RI-ENT-WP-07) added the entity_assertions/entity_assertion_evidence
    # migration on top of that; 86 since `c99cd8ed8d1c` (commit `37ead78`,
    # RI-ENT-WP-08's blocker-clearing pass) renamed the seeded
    # entity_relationship_types row `design_coordinates_with` to
    # `design_coordination_with` on top of that; 87 since `2c00c9ac64bc`
    # (UI-IMP-WP02) added WebAuthn credential, challenge, recovery-code, and
    # opaque session tables on top of that; 88 since `16f05c46b8c3`
    # (RI-ENT-WP-10/11) widened three closed-set CHECKs --
    # `audit_events.capability_is_known` 115 -> 135,
    # `entity_mutation_events.a_mutated_record_family_is_known` 6 -> 11 and
    # `entity_proposals.an_accepted_proposal_record_family_is_known` 6 -> 11 --
    # for RI-ENT-WP-10's five entity reads and RI-ENT-WP-11's fifteen entity
    # mutation contracts on top of that, creating and altering no table; 89
    # since `b8e4d1a6c073` (RI-ENT-WP-12) backfilled one `display`-typed
    # `entity_names` row per active `entities` row on top of that, re-parented
    # from `c99cd8ed8d1c` onto `16f05c46b8c3` so the chain keeps one head
    # (RULING-M11); 91 since `6a2f9d1c4b80` added the GoodNotes pull schema on
    # top of that -- counted on the merged tree, not derived (RULING-M2).
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == 92


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
    source = _revision_source(HEAD_REVISION)
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


def test_the_revision_freezes_action_and_class_literals() -> None:
    source = _revision_source(HEAD_REVISION)
    for member in (*ContextPreferenceAction, *ContextPreferenceClass):
        assert f"'{member.value}'" in source


def test_the_revision_reads_no_enum_and_no_tables_module() -> None:
    source = _revision_source(HEAD_REVISION)
    assert "my_pa.domain" not in source
    assert "infrastructure.persistence.tables" not in source
    for forbidden in ("Capability", "Purpose"):
        assert f"import {forbidden}" not in source


@pytest.mark.database
def test_the_revision_runs_empty_to_head_and_prior_to_head(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        declared = {member.value for member in Capability} | {
            member.value for member in NativeSourceCapability
        }
        assert _admitted(engine, "capability_is_known") == declared
        assert _admitted(engine, "purpose_is_known") == {member.value for member in Purpose}
        assert {"context_preference_events", "context_preference_current"} <= _tables(engine)

        command.downgrade(_config(), PREVIOUS)
        assert "context_preference_events" not in _tables(engine)
        assert "context_preference_current" not in _tables(engine)
        with pytest.raises(IntegrityError):
            _record(engine, "context.feedback", "context_preparation")
        with pytest.raises(IntegrityError):
            _record(engine, "context.prepare", "context_preference")

        command.upgrade(_config(), "head")
        assert {"context_preference_events", "context_preference_current"} <= _tables(engine)
        _record(engine, "context.feedback", "context_preference")
    finally:
        engine.dispose()


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; migration tests still drive Alembic themselves."""
    return empty_database_url
