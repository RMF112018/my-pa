"""Database contract for the authoritative identity-history projection.

This focused module is completed by the integration owner once WP-01's migration
and shared repository wiring land.  The tests are intentionally stated against
the public query rather than by scraping review records.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection

from my_pa.domain.relationship.identity_correction import (
    IDENTITY_PREVIEW_LIFETIME,
    state_digest,
)
from my_pa.domain.relationship.identity_history import (
    IdentityHistoryEntry,
    IdentityHistoryOperation,
    IdentityHistorySource,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity_identity_history import SqlIdentityHistoryQuery


def test_every_history_union_branch_carries_its_own_principal_predicate() -> None:
    """Deleting a branch predicate must redden before a database is contacted."""
    query = object.__new__(SqlIdentityHistoryQuery)
    statement = query._history("prn_aaaa0001aaaa0001aaaa0001", "ent_aaaa0001aaaa0001")
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()

    assert sql.count("principal_id =") == 3
    assert "entity_mutation_events" in sql
    assert "entity_identity_operations" in sql
    assert "entity_merge_records" in sql
    assert "union all" in sql


def test_history_is_not_derived_from_preview_proposal_or_review_tables() -> None:
    query = object.__new__(SqlIdentityHistoryQuery)
    statement = query._history("prn_aaaa0001aaaa0001aaaa0001", "ent_aaaa0001aaaa0001")
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()

    assert "entity_identity_previews" not in sql
    assert "entity_proposals" not in sql
    assert "entity_proposal_review" not in sql


# --- governed lineage against a real server (RI-P2-HIGH-001) -----------------

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: Distinct from every other database-tier fixture's disposable database, so
#: this suite can run alongside them without one dropping another's database.
DISPOSABLE_DATABASE: Final = "my_pa_identity_history_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

SURVIVOR: Final = "ent_aaaa0001aaaa0001"
MERGED: Final = "ent_bbbb0002bbbb0002"
LEGACY: Final = "ent_cccc0003cccc0003"
FOREIGN: Final = "ent_ffff0009ffff0009"

MERGE_PREVIEW: Final = "eipv_aaaa0001aaaa01"
SPLIT_PREVIEW: Final = "eipv_bbbb0002bbbb02"
MERGE_OPERATION: Final = "eiop_aaaa0001aaaa01"
SPLIT_OPERATION: Final = "eiop_bbbb0002bbbb02"
MERGE_RECEIPT: Final = "rcpt_aaaa0001aaaa01"
SPLIT_RECEIPT: Final = "rcpt_bbbb0002bbbb02"

CORRELATION: Final = "corr_aaaa0001aaaa0001"
AUDIT: Final = "audit_aaaa0001aaaa01"
PROPOSAL: Final = "eprp_aaaa0001aaaa0001"
LEGACY_MERGE: Final = "emrg_aaaa0001aaaa0001"
MUTATION: Final = "emut_aaaa0001aaaa01"

WHEN: Final = datetime(2026, 8, 28, 12, tzinfo=UTC)
DIGEST: Final = "0" * 64
OTHER_DIGEST: Final = "1" * 64


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def _seed_entities(connection: Connection) -> None:
    for entity_id, principal_id in (
        (SURVIVOR, PRINCIPAL_A),
        (MERGED, PRINCIPAL_A),
        (LEGACY, PRINCIPAL_A),
        (FOREIGN, PRINCIPAL_B),
    ):
        display_name = f"Synthetic {entity_id}"
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
                "(entity_id, principal_id, entity_type, canonical_name, display_name, "
                " status, created_at, updated_at, version) "
                "VALUES (:entity_id, :principal_id, 'person', :canonical_name, :display_name, "
                " 'active', :when, :when, 1)"
            ),
            {
                "entity_id": entity_id,
                "principal_id": principal_id,
                "canonical_name": normalize_name(display_name),
                "display_name": display_name,
                "when": WHEN,
            },
        )


def _seed_direct_mutation(connection: Connection) -> None:
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.entity_mutation_events "  # noqa: S608
            "(event_id, principal_id, capability, record_family, record_id, prior_version, "
            " new_version, authority, before_state, after_state, reason, idempotency_key, "
            " request_digest, correlation_id, audit_id, actor_class, recorded_at) "
            "VALUES (:event_id, :principal_id, 'entities.update', 'entity', :record_id, 1, 2, "
            " 'user_confirmed_assertion', CAST(:before_state AS jsonb), "
            " CAST(:after_state AS jsonb), 'a corrected display name', 'update-0001', "
            " :request_digest, :correlation_id, :audit_id, 'user', :recorded_at)"
        ),
        {
            "event_id": MUTATION,
            "principal_id": PRINCIPAL_A,
            "record_id": SURVIVOR,
            "before_state": '{"entity_id": "' + SURVIVOR + '", "entity_version": 1}',
            "after_state": '{"entity_id": "' + SURVIVOR + '", "entity_version": 2}',
            "request_digest": DIGEST,
            "correlation_id": CORRELATION,
            "audit_id": AUDIT,
            "recorded_at": WHEN + timedelta(minutes=1),
        },
    )


def _seed_preview(connection: Connection, preview_id: str, **overrides: object) -> None:
    values: dict[str, object] = {
        "preview_id": preview_id,
        "principal_id": PRINCIPAL_A,
        "operation_type": "merge",
        "survivor_entity_id": SURVIVOR,
        "expected_survivor_version": 1,
        "merged_away": '[{"entity_id": "' + MERGED + '", "expected_version": 1}]',
        "preview_digest": DIGEST,
        "conflict_digest": OTHER_DIGEST,
        "plan_digest": OTHER_DIGEST,
        "created_by": "the operator",
        "actor_class": "user",
        "created_at": WHEN,
        "expires_at": WHEN + IDENTITY_PREVIEW_LIFETIME,
        "source_identity_operation_id": None,
    }
    values.update(overrides)
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.entity_identity_previews "  # noqa: S608
            "(preview_id, principal_id, operation_type, survivor_entity_id, "
            " expected_survivor_version, merged_away, preview_digest, conflict_digest, "
            " plan_digest, source_identity_operation_id, created_by, actor_class, "
            " created_at, expires_at) "
            "VALUES (:preview_id, :principal_id, :operation_type, :survivor_entity_id, "
            " :expected_survivor_version, CAST(:merged_away AS jsonb), :preview_digest, "
            " :conflict_digest, :plan_digest, :source_identity_operation_id, :created_by, "
            " :actor_class, :created_at, :expires_at)"
        ),
        values,
    )


def _seed_operation(connection: Connection, **overrides: object) -> None:
    values: dict[str, object] = {
        "identity_operation_id": MERGE_OPERATION,
        "principal_id": PRINCIPAL_A,
        "operation_type": "merge",
        "survivor_entity_id": SURVIVOR,
        "merged_entity_ids": '["' + MERGED + '"]',
        "preview_id": MERGE_PREVIEW,
        "preview_digest": DIGEST,
        "idempotency_key": "merge-0001",
        "request_digest": OTHER_DIGEST,
        "reason": "one person, two rows",
        "performed_by": "the operator",
        "actor_class": "user",
        "correlation_id": CORRELATION,
        "audit_id": AUDIT,
        "receipt_id": MERGE_RECEIPT,
        "state": "completed",
        "started_at": WHEN,
        "completed_at": WHEN + timedelta(minutes=2),
        "effect_count": 1,
        "effects_digest": DIGEST,
        "source_identity_operation_id": None,
    }
    values.update(overrides)
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.entity_identity_operations "  # noqa: S608
            "(identity_operation_id, principal_id, operation_type, survivor_entity_id, "
            " merged_entity_ids, preview_id, preview_digest, idempotency_key, request_digest, "
            " reason, performed_by, actor_class, correlation_id, audit_id, receipt_id, state, "
            " started_at, completed_at, effect_count, effects_digest, "
            " source_identity_operation_id) "
            "VALUES (:identity_operation_id, :principal_id, :operation_type, "
            " :survivor_entity_id, CAST(:merged_entity_ids AS jsonb), :preview_id, "
            " :preview_digest, :idempotency_key, :request_digest, :reason, :performed_by, "
            " :actor_class, :correlation_id, :audit_id, :receipt_id, :state, :started_at, "
            " :completed_at, :effect_count, :effects_digest, :source_identity_operation_id)"
        ),
        values,
    )


def _seed_effect(connection: Connection, effect_id: str, operation_id: str) -> None:
    before = {"entity_id": MERGED}
    after = {"entity_id": SURVIVOR}
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.entity_identity_effects "  # noqa: S608
            "(effect_id, identity_operation_id, principal_id, sequence, record_family, "
            " record_id, effect_kind, before_state, after_state, before_sha256, after_sha256, "
            " recorded_at) "
            "VALUES (:effect_id, :identity_operation_id, :principal_id, 1, 'alias', "
            " :record_id, 'owner_reparented', CAST(:before_state AS jsonb), "
            " CAST(:after_state AS jsonb), :before_sha256, :after_sha256, :recorded_at)"
        ),
        {
            "effect_id": effect_id,
            "identity_operation_id": operation_id,
            "principal_id": PRINCIPAL_A,
            "record_id": "alias_aaaa0001aaaa01",
            "before_state": '{"entity_id": "' + MERGED + '"}',
            "after_state": '{"entity_id": "' + SURVIVOR + '"}',
            "before_sha256": state_digest(before),
            "after_sha256": state_digest(after),
            "recorded_at": WHEN,
        },
    )


def _seed_legacy_merge(connection: Connection) -> None:
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.entity_proposals "  # noqa: S608
            "(proposal_id, principal_id, kind, payload, observation_ids, proposed_at, "
            " proposed_by, method, method_version, dedupe_sha256) "
            "VALUES (:proposal_id, :principal_id, 'merge_entities', '{}'::jsonb, '[]'::jsonb, "
            " :when, 'the operator', 'rule', 'seed.1', repeat('0', 64))"
        ),
        {"proposal_id": PROPOSAL, "principal_id": PRINCIPAL_A, "when": WHEN},
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.entity_merge_records "  # noqa: S608
            "(merge_id, principal_id, retained_entity_id, merged_entity_id, proposal_id, "
            " decided_by, reason, decided_at) "
            "VALUES (:merge_id, :principal_id, :retained, :merged, :proposal_id, "
            " 'the operator', 'accepted before the governed ledger existed', :decided_at)"
        ),
        {
            "merge_id": LEGACY_MERGE,
            "principal_id": PRINCIPAL_A,
            "retained": SURVIVOR,
            "merged": LEGACY,
            "proposal_id": PROPOSAL,
            "decided_at": WHEN + timedelta(minutes=4),
        },
    )


@pytest.fixture
def seeded_engine(disposable_database: str) -> Iterator[Engine]:
    """One entity's whole history: a direct mutation, a merge, its split, a legacy merge."""
    engine = create_database_engine(disposable_database)
    try:
        with engine.begin() as connection:
            _seed_entities(connection)
            _seed_direct_mutation(connection)
            _seed_preview(connection, MERGE_PREVIEW)
            _seed_preview(
                connection,
                SPLIT_PREVIEW,
                operation_type="split",
                source_identity_operation_id=MERGE_OPERATION,
            )
            _seed_operation(connection)
            _seed_operation(
                connection,
                identity_operation_id=SPLIT_OPERATION,
                operation_type="split",
                preview_id=SPLIT_PREVIEW,
                idempotency_key="split-0001",
                receipt_id=SPLIT_RECEIPT,
                reason="two people, one row",
                completed_at=WHEN + timedelta(minutes=3),
                source_identity_operation_id=MERGE_OPERATION,
            )
            _seed_effect(connection, "eief_aaaa0001aaaa01", MERGE_OPERATION)
            _seed_effect(connection, "eief_bbbb0002bbbb02", SPLIT_OPERATION)
            _seed_legacy_merge(connection)
        yield engine
    finally:
        engine.dispose()


def _history(engine: Engine, principal_id: str) -> tuple[IdentityHistoryEntry, ...]:
    with engine.connect() as connection:
        found = SqlIdentityHistoryQuery(connection).entries(principal_id, SURVIVOR, limit=10)
    return tuple(entry for entry, _source_order in found)


@pytest.mark.database
def test_a_split_names_the_governed_merge_it_descended_from(seeded_engine: Engine) -> None:
    """The finding: without these two columns the descent is unrecoverable."""
    split = next(
        entry
        for entry in _history(seeded_engine, PRINCIPAL_A)
        if entry.history_id == SPLIT_OPERATION
    )

    assert split.operation is IdentityHistoryOperation.SPLIT
    assert split.source is IdentityHistorySource.IDENTITY_OPERATION
    assert split.source_identity_operation_id == MERGE_OPERATION
    assert split.receipt_id == SPLIT_RECEIPT


@pytest.mark.database
def test_a_governed_merge_names_its_receipt_and_descends_from_nothing(
    seeded_engine: Engine,
) -> None:
    merge = next(
        entry
        for entry in _history(seeded_engine, PRINCIPAL_A)
        if entry.history_id == MERGE_OPERATION
    )

    assert merge.operation is IdentityHistoryOperation.MERGE
    assert merge.receipt_id == MERGE_RECEIPT
    assert merge.source_identity_operation_id is None


@pytest.mark.database
def test_a_direct_mutation_and_a_legacy_merge_name_neither(seeded_engine: Engine) -> None:
    """Those ledgers hold no governed operation, so the projection says so."""
    ungoverned = {
        entry.history_id: entry
        for entry in _history(seeded_engine, PRINCIPAL_A)
        if entry.source is not IdentityHistorySource.IDENTITY_OPERATION
    }

    assert set(ungoverned) == {MUTATION, LEGACY_MERGE}
    for entry in ungoverned.values():
        assert entry.source_identity_operation_id is None
        assert entry.receipt_id is None


@pytest.mark.database
def test_the_whole_history_stays_chronological_and_complete(seeded_engine: Engine) -> None:
    """Widening the entry must not drop a branch, reorder one, or duplicate one."""
    entries = _history(seeded_engine, PRINCIPAL_A)

    assert [entry.history_id for entry in entries] == [
        MUTATION,
        MERGE_OPERATION,
        SPLIT_OPERATION,
        LEGACY_MERGE,
    ]
    assert [entry.occurred_at for entry in entries] == sorted(
        entry.occurred_at for entry in entries
    )
    assert [entry.source for entry in entries] == [
        IdentityHistorySource.DIRECT_MUTATION,
        IdentityHistorySource.IDENTITY_OPERATION,
        IdentityHistorySource.IDENTITY_OPERATION,
        IdentityHistorySource.LEGACY_MERGE,
    ]
    # The legacy ledger recorded a decision and not the rows it moved, so it is
    # the one branch with nothing to show; every other branch still does.
    assert [bool(entry.changes) for entry in entries] == [True, True, True, False]


@pytest.mark.database
def test_another_principal_reads_no_lineage_at_all(seeded_engine: Engine) -> None:
    """The new columns are inside the partitioned branches, not beside them."""
    assert _history(seeded_engine, PRINCIPAL_B) == ()
