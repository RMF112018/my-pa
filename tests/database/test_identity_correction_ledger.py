"""The three identity-correction tables against a real server.

`tests/unit/test_identity_correction.py` drives the domain records and proves the
contract. This drives the SQL and proves the contract holds where it has to:
against the append-only trigger that makes the effect ledger evidence rather than
a mutable note, the `UNIQUE (identity_operation_id, sequence)` that orders one
operation's effects, the composite foreign keys that make same-Principal
structural, the idempotency unique that makes a replay find its own earlier row,
and the CHECK that stops a writer choosing how long an operator's approval lasts.

**What this file proves and what it does not.** Nothing here goes through
`ApplicationService`, so nothing here writes an audit row: `entities.merge` and
`entities.merge.preview` are not admitted to `knowledge.audit_events`'
`capability_is_known` at this head, because Phase B takes one vocabulary revision
and several branches restating one frozen CHECK would produce several heads. The
merge that drives these tables end to end is `WP-RI-06`'s application half and is
somebody else's file. What is measured here is the schema.

Every identity is synthetic, and every recorded state holds identifiers, closed
vocabulary members and versions -- the rule the effect ledger's own declaration
states about what may go in `before_state` and `after_state`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.relationship.entity import EntityStatus
from my_pa.domain.relationship.identity_correction import (
    IDENTITY_PREVIEW_LIFETIME,
    IdentityEffect,
    IdentityEffectFamily,
    IdentityEffectKind,
    state_digest,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.persistence.entity import SqlEntityRepository

pytestmark = pytest.mark.database
SCHEMA: Final = "knowledge"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

SURVIVOR: Final = "ent_aaaa0001aaaa0001"
MERGED: Final = "ent_bbbb0002bbbb0002"
FOREIGN: Final = "ent_ffff0009ffff0009"

PREVIEW: Final = "eipv_aaaa0001aaaa01"
OPERATION: Final = "eiop_aaaa0001aaaa01"

CORRELATION: Final = "corr_aaaa0001aaaa0001"
AUDIT: Final = "audit_aaaa0001aaaa01"

WHEN: Final = datetime(2026, 8, 24, 12, tzinfo=UTC)
DIGEST: Final = "0" * 64
OTHER_DIGEST: Final = "1" * 64


@pytest.fixture
def migrated_engine(db_engine: Engine) -> Engine:
    """Current-head clone seeded with the three synthetic entities this ledger cites."""

    with db_engine.begin() as connection:
        for entity_id, principal_id in (
            (SURVIVOR, PRINCIPAL_A),
            (MERGED, PRINCIPAL_A),
            (FOREIGN, PRINCIPAL_B),
        ):
            display_name = f"Synthetic {entity_id}"
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
                    "(entity_id, principal_id, entity_type, canonical_name, display_name, "
                    " status, created_at, updated_at, version) "
                    "VALUES (:entity_id, :principal_id, 'person', :canonical_name, "
                    ":display_name, "
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
    return db_engine


def _insert_preview(engine: Engine, **overrides: object) -> None:
    values: dict[str, object] = {
        "preview_id": PREVIEW,
        "principal_id": PRINCIPAL_A,
        "operation_type": "merge",
        "survivor_entity_id": SURVIVOR,
        "expected_survivor_version": 1,
        "merged_away": '[{"entity_id": "' + MERGED + '", "expected_version": 1}]',
        "preview_digest": DIGEST,
        "conflict_digest": OTHER_DIGEST,
        "plan_digest": OTHER_DIGEST,
        "created_by": "operator",
        "actor_class": "user",
        "created_at": WHEN,
        "expires_at": WHEN + IDENTITY_PREVIEW_LIFETIME,
        "source_identity_operation_id": None,
    }
    values.update(overrides)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_identity_previews "  # noqa: S608
                "(preview_id, principal_id, operation_type, survivor_entity_id, "
                " expected_survivor_version, merged_away, preview_digest, conflict_digest, "
                " plan_digest, source_identity_operation_id, "
                " created_by, actor_class, created_at, expires_at) "
                "VALUES (:preview_id, :principal_id, :operation_type, :survivor_entity_id, "
                " :expected_survivor_version, CAST(:merged_away AS jsonb), :preview_digest, "
                " :conflict_digest, :plan_digest, :source_identity_operation_id, "
                " :created_by, :actor_class, :created_at, "
                " :expires_at)"
            ),
            values,
        )


def _insert_operation(engine: Engine, **overrides: object) -> None:
    values: dict[str, object] = {
        "identity_operation_id": OPERATION,
        "principal_id": PRINCIPAL_A,
        "operation_type": "merge",
        "survivor_entity_id": SURVIVOR,
        "merged_entity_ids": '["' + MERGED + '"]',
        "preview_id": PREVIEW,
        "preview_digest": DIGEST,
        "idempotency_key": "merge-0001",
        "request_digest": OTHER_DIGEST,
        "performed_by": "operator",
        "actor_class": "user",
        "correlation_id": CORRELATION,
        "audit_id": AUDIT,
        "receipt_id": "rcpt_aaaa0001aaaa01",
        "state": "completed",
        "started_at": WHEN,
        "completed_at": WHEN + timedelta(seconds=2),
        "effect_count": 1,
        "effects_digest": DIGEST,
        "source_identity_operation_id": None,
    }
    values.update(overrides)
    if values["state"] == "in_progress":
        values.setdefault("completed_at", None)
        values["effect_count"] = None
        values["effects_digest"] = None
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_identity_operations "  # noqa: S608
                "(identity_operation_id, principal_id, operation_type, survivor_entity_id, "
                " merged_entity_ids, preview_id, preview_digest, idempotency_key, "
                " request_digest, performed_by, actor_class, correlation_id, audit_id, receipt_id, "
                " state, started_at, completed_at, effect_count, effects_digest, "
                " source_identity_operation_id) "
                "VALUES (:identity_operation_id, :principal_id, :operation_type, "
                " :survivor_entity_id, CAST(:merged_entity_ids AS jsonb), :preview_id, "
                " :preview_digest, :idempotency_key, :request_digest, :performed_by, "
                " :actor_class, :correlation_id, :audit_id, :receipt_id, :state, "
                " :started_at, :completed_at, :effect_count, :effects_digest, "
                " :source_identity_operation_id)"
            ),
            values,
        )


def _insert_effect(engine: Engine, **overrides: object) -> None:
    before = {"entity_id": MERGED}
    after = {"entity_id": SURVIVOR}
    values: dict[str, object] = {
        "effect_id": "eief_aaaa0001aaaa01",
        "identity_operation_id": OPERATION,
        "principal_id": PRINCIPAL_A,
        "sequence": 1,
        "record_family": IdentityEffectFamily.ALIAS.value,
        "record_id": "eals_aaaa0001aaaa01",
        "effect_kind": IdentityEffectKind.OWNER_REPARENTED.value,
        "before_state": '{"entity_id": "' + MERGED + '"}',
        "after_state": '{"entity_id": "' + SURVIVOR + '"}',
        "before_sha256": state_digest(before),
        "after_sha256": state_digest(after),
        "recorded_at": WHEN,
    }
    values.update(overrides)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_identity_effects "  # noqa: S608
                "(effect_id, identity_operation_id, principal_id, sequence, record_family, "
                " record_id, effect_kind, before_state, after_state, before_sha256, "
                " after_sha256, recorded_at) "
                "VALUES (:effect_id, :identity_operation_id, :principal_id, :sequence, "
                " :record_family, :record_id, :effect_kind, CAST(:before_state AS jsonb), "
                " CAST(:after_state AS jsonb), :before_sha256, :after_sha256, :recorded_at)"
            ),
            values,
        )


# --- the preview control row -------------------------------------------------


def test_a_preview_is_stored_and_read_back(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    with migrated_engine.connect() as connection:
        stored = connection.execute(
            text(
                f"SELECT expires_at - created_at AS lifetime, consumed_at "  # noqa: S608
                f"FROM {SCHEMA}.entity_identity_previews WHERE preview_id = :preview_id"
            ),
            {"preview_id": PREVIEW},
        ).one()
    assert stored.lifetime == IDENTITY_PREVIEW_LIFETIME
    assert stored.consumed_at is None


def test_the_server_refuses_a_preview_lifetime_a_writer_chose(migrated_engine: Engine) -> None:
    """The domain refuses it too; a row written around the repository is refused here."""
    with pytest.raises(IntegrityError) as refused:
        _insert_preview(migrated_engine, expires_at=WHEN + timedelta(hours=8))
    assert "a_preview_expires_fifteen_minutes_after_it_was_created" in str(refused.value)


def test_the_server_refuses_a_preview_over_another_principals_entity(
    migrated_engine: Engine,
) -> None:
    with pytest.raises(IntegrityError) as refused:
        _insert_preview(migrated_engine, survivor_entity_id=FOREIGN)
    assert "a_preview_retains_an_entity_of_its_principal" in str(refused.value)


def test_the_server_bounds_the_merged_away_set(migrated_engine: Engine) -> None:
    entries = ", ".join(f'{{"entity_id": "ent_merged{index:08d}"}}' for index in range(11))
    eleven = f"[{entries}]"
    with pytest.raises(IntegrityError) as refused:
        _insert_preview(migrated_engine, merged_away=eleven)
    assert "a_preview_merges_away_a_bounded_set_of_entities" in str(refused.value)
    with pytest.raises(IntegrityError):
        _insert_preview(migrated_engine, merged_away="[]")


# --- the operation ledger ----------------------------------------------------


def test_an_operation_consumes_a_preview_of_its_own_principal(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.entity_identity_operations")  # noqa: S608
            ).scalar_one()
            == 1
        )


def test_the_server_refuses_an_operation_against_another_principals_preview(
    migrated_engine: Engine,
) -> None:
    """The composite reference, not a predicate the writer has to remember."""
    _insert_preview(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_operation(migrated_engine, principal_id=PRINCIPAL_B)
    assert "an_identity_operation" in str(refused.value)


def test_one_idempotency_key_holds_one_operation_per_principal(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_operation(
            migrated_engine,
            identity_operation_id="eiop_bbbb0002bbbb02",
            request_digest=DIGEST,
        )
    assert "one_identity_operation_per_principal_and_key" in str(refused.value)


def test_an_operation_requires_one_unique_server_receipt(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    with pytest.raises(IntegrityError):
        _insert_operation(migrated_engine, receipt_id=None)
    _insert_operation(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_operation(
            migrated_engine,
            identity_operation_id="eiop_bbbb0002bbbb02",
            idempotency_key="merge-0002",
            request_digest=DIGEST,
        )
    assert "one_receipt_per_identity_operation" in str(refused.value)


def test_an_operation_in_progress_may_not_name_an_end(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_operation(migrated_engine, state="in_progress")
    assert "an_identity_operation_is_finished_exactly_when_it_names_an_end" in str(refused.value)


def test_an_operation_is_updated_from_in_progress_to_completed(migrated_engine: Engine) -> None:
    """The asymmetry with the effects: status is revised, evidence is not."""
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine, state="in_progress", completed_at=None)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_identity_operations "  # noqa: S608
                "SET state = 'completed', completed_at = :when, "
                "effect_count = 1, effects_digest = :effects_digest "
                "WHERE identity_operation_id = :identity_operation_id"
            ),
            {
                "when": WHEN + timedelta(seconds=1),
                "effects_digest": DIGEST,
                "identity_operation_id": OPERATION,
            },
        )
    with migrated_engine.connect() as connection:
        settled = connection.execute(
            text(
                f"SELECT state, effect_count, effects_digest "  # noqa: S608
                f"FROM {SCHEMA}.entity_identity_operations "
                "WHERE identity_operation_id = :identity_operation_id"
            ),
            {"identity_operation_id": OPERATION},
        ).one()
        assert settled == (
            "completed",
            1,
            DIGEST,
        )


def test_the_server_refuses_an_unknown_operation_type(migrated_engine: Engine) -> None:
    """The final-completion revision admits merge and split, and nothing else."""
    _insert_preview(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_operation(migrated_engine, operation_type="rename")
    assert "an_identity_operation_type_is_known" in str(refused.value)


def test_the_server_admits_one_split_bound_to_one_completed_merge(
    migrated_engine: Engine,
) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    _insert_effect(migrated_engine)
    split_preview = "eipv_bbbb0002bbbb02"
    split_operation = "eiop_bbbb0002bbbb02"
    _insert_preview(
        migrated_engine,
        preview_id=split_preview,
        operation_type="split",
        source_identity_operation_id=OPERATION,
    )
    _insert_operation(
        migrated_engine,
        identity_operation_id=split_operation,
        operation_type="split",
        preview_id=split_preview,
        idempotency_key="split-0001",
        receipt_id="rcpt_bbbb0002bbbb02",
        source_identity_operation_id=OPERATION,
    )
    with migrated_engine.connect() as connection:
        stored = connection.execute(
            text(
                f"SELECT source_identity_operation_id "  # noqa: S608
                f"FROM {SCHEMA}.entity_identity_operations "
                "WHERE identity_operation_id = :operation_id"
            ),
            {"operation_id": split_operation},
        ).scalar_one()
    assert stored == OPERATION


def test_completed_split_lookup_ignores_failed_and_in_progress_attempts(
    migrated_engine: Engine,
) -> None:
    """RI-FC-WP-07: only a completed inverse prevents another split attempt."""
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    _insert_effect(migrated_engine)
    for suffix, state in (("bbbb0002bbbb02", "failed"), ("cccc0003cccc03", "in_progress")):
        preview_id = f"eipv_{suffix}"
        _insert_preview(
            migrated_engine,
            preview_id=preview_id,
            operation_type="split",
            source_identity_operation_id=OPERATION,
        )
        _insert_operation(
            migrated_engine,
            identity_operation_id=f"eiop_{suffix}",
            operation_type="split",
            preview_id=preview_id,
            idempotency_key=f"split-{state}",
            receipt_id=f"rcpt_{suffix}",
            state=state,
            completed_at=None if state == "in_progress" else WHEN + timedelta(seconds=3),
            source_identity_operation_id=OPERATION,
        )
    with migrated_engine.connect() as connection:
        repository = SqlEntityRepository(connection)
        assert repository.split_for_source_operation(PRINCIPAL_A, OPERATION) is None
    completed_preview = "eipv_dddd0004dddd04"
    completed_operation = "eiop_dddd0004dddd04"
    _insert_preview(
        migrated_engine,
        preview_id=completed_preview,
        operation_type="split",
        source_identity_operation_id=OPERATION,
    )
    _insert_operation(
        migrated_engine,
        identity_operation_id=completed_operation,
        operation_type="split",
        preview_id=completed_preview,
        idempotency_key="split-completed",
        receipt_id="rcpt_dddd0004dddd04",
        source_identity_operation_id=OPERATION,
    )
    with migrated_engine.connect() as connection:
        found = SqlEntityRepository(connection).split_for_source_operation(PRINCIPAL_A, OPERATION)
    assert found is not None
    assert found.identity_operation_id == completed_operation


def test_entity_split_restores_semantics_with_a_monotonic_token(
    migrated_engine: Engine,
) -> None:
    """RI-FC-WP-07: a pre-merge version cannot become current again after split."""
    before = {"status": "active", "superseded_by_entity_id": None, "version": 1}
    after = {
        "status": "merged_redirect",
        "superseded_by_entity_id": SURVIVOR,
        "version": 2,
    }
    effect = IdentityEffect(
        effect_id="eief_bbbb0002bbbb02",
        identity_operation_id=OPERATION,
        principal_id=PRINCIPAL_A,
        sequence=1,
        family=IdentityEffectFamily.ENTITY,
        record_id=MERGED,
        kind=IdentityEffectKind.ENTITY_REDIRECTED,
        before_state=before,
        after_state=after,
        before_sha256=state_digest(before),
        after_sha256=state_digest(after),
        recorded_at=WHEN,
    )
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entities SET status = 'merged_redirect', "  # noqa: S608
                "superseded_by_entity_id = :survivor, version = 2 WHERE entity_id = :merged"
            ),
            {"survivor": SURVIVOR, "merged": MERGED},
        )
        repository = SqlEntityRepository(connection)
        repository.restore_identity_effect(PRINCIPAL_A, effect)
        restored = repository.get(PRINCIPAL_A, MERGED)
        assert restored is not None
        assert restored.status is EntityStatus.ACTIVE
        assert restored.superseded_by_entity_id is None
        assert restored.version == 3
        with pytest.raises(UnknownScopeError):
            repository.redirect_entity(
                PRINCIPAL_A,
                MERGED,
                SURVIVOR,
                expected_version=1,
            )


# --- the append-only effect ledger -------------------------------------------


def test_an_effect_is_stored_with_both_states_and_both_digests(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    _insert_effect(migrated_engine)
    with migrated_engine.connect() as connection:
        stored = connection.execute(
            text(
                f"SELECT before_state, after_state, before_sha256, after_sha256 "  # noqa: S608
                f"FROM {SCHEMA}.entity_identity_effects"
            )
        ).one()
    assert stored.before_state == {"entity_id": MERGED}
    assert stored.after_state == {"entity_id": SURVIVOR}
    assert stored.before_sha256 == state_digest({"entity_id": MERGED})
    assert stored.after_sha256 == state_digest({"entity_id": SURVIVOR})


def test_an_effect_row_cannot_be_updated(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    _insert_effect(migrated_engine)
    with pytest.raises(DBAPIError) as refused, migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_identity_effects "  # noqa: S608
                'SET after_state = \'{"entity_id": "ent_rewritten00001"}\'::jsonb'
            )
        )
    assert "append only" in str(refused.value)


def test_an_effect_row_cannot_be_deleted(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    _insert_effect(migrated_engine)
    with pytest.raises(DBAPIError) as refused, migrated_engine.begin() as connection:
        connection.execute(text(f"DELETE FROM {SCHEMA}.entity_identity_effects"))  # noqa: S608
    assert "append only" in str(refused.value)
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.entity_identity_effects")  # noqa: S608
            ).scalar_one()
            == 1
        )


def test_one_effect_per_operation_and_sequence(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    _insert_effect(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_effect(
            migrated_engine,
            effect_id="eief_bbbb0002bbbb02",
            record_id="eals_bbbb0002bbbb02",
        )
    assert "one_identity_effect_per_operation_and_sequence" in str(refused.value)


def test_one_effect_per_operation_and_record(migrated_engine: Engine) -> None:
    """Two rows about one record would leave a split unable to say what to restore."""
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    _insert_effect(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_effect(
            migrated_engine,
            effect_id="eief_bbbb0002bbbb02",
            sequence=2,
            effect_kind=IdentityEffectKind.ROW_COALESCED.value,
        )
    assert "one_identity_effect_per_operation_and_record" in str(refused.value)


def test_the_server_refuses_an_effect_that_records_no_change(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    same = '{"entity_id": "' + MERGED + '"}'
    with pytest.raises(IntegrityError) as refused:
        _insert_effect(
            migrated_engine,
            after_state=same,
            after_sha256=state_digest({"entity_id": MERGED}),
        )
    assert "an_identity_effect_records_a_change" in str(refused.value)


def test_the_server_refuses_an_effect_state_that_says_nothing(migrated_engine: Engine) -> None:
    """A `{}` state is the redirect-only ledger, written one row at a time."""
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_effect(migrated_engine, before_state="{}", before_sha256=state_digest({}))
    assert "an_identity_effect_before_state_says_something" in str(refused.value)


def test_the_server_refuses_an_effect_of_another_principals_operation(
    migrated_engine: Engine,
) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_effect(migrated_engine, principal_id=PRINCIPAL_B)
    assert "an_identity_effect_records_an_operation_of_its_principal" in str(refused.value)


def test_the_server_refuses_a_record_id_that_is_not_an_opaque_identifier(
    migrated_engine: Engine,
) -> None:
    """`record_id` names nine families and carries no foreign key; shape is what is left."""
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    with pytest.raises(IntegrityError) as refused:
        _insert_effect(migrated_engine, record_id="/etc/passwd")
    assert "an_identity_effect_record_id_is_an_opaque_identifier" in str(refused.value)


def test_the_ledger_reads_back_in_sequence_order(migrated_engine: Engine) -> None:
    _insert_preview(migrated_engine)
    _insert_operation(migrated_engine)
    _insert_effect(
        migrated_engine,
        effect_id="eief_cccc0003cccc03",
        sequence=3,
        record_family=IdentityEffectFamily.IDENTIFIER.value,
        record_id="xid_cccc0003cccc0003",
    )
    _insert_effect(
        migrated_engine,
        effect_id="eief_bbbb0002bbbb02",
        sequence=2,
        record_id="eals_bbbb0002bbbb02",
    )
    _insert_effect(migrated_engine)
    with migrated_engine.connect() as connection:
        sequences = [
            row.sequence
            for row in connection.execute(
                text(
                    f"SELECT sequence FROM {SCHEMA}.entity_identity_effects "  # noqa: S608
                    "WHERE identity_operation_id = :identity_operation_id "
                    "ORDER BY sequence"
                ),
                {"identity_operation_id": OPERATION},
            )
        ]
    assert sequences == [1, 2, 3]
