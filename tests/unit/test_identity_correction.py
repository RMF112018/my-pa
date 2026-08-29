"""The preview binding, the operation's two mechanisms, and the effect ledger's order.

Nothing here opens a connection. What is proved is the half of `WP-RI-06` that
has to hold before any SQL exists: that a preview cannot be written with an
expiry a caller chose, that the preview digest and the idempotency key stay
separate concepts, that an effect cannot be stored with half its evidence or with
a digest that disagrees with the state beside it, and that the ledger's order is
a property of the effects rather than of the walk that found them.

The database-tier sibling drives the same records against the append-only
triggers and the composite foreign keys.

Every identity here is synthetic and every state is identifiers and closed
vocabulary members, which is the rule the effect ledger's own declaration states
about what may go in `before_state` and `after_state`.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from itertools import permutations
from types import SimpleNamespace
from typing import Final
from unittest.mock import MagicMock

import pytest

from my_pa.application.errors import ConflictError, DeniedError, NotFoundError
from my_pa.application.identity_correction import (
    IdentityCorrectionService,
    SplitCommand,
    SplitPreviewCommand,
    SplitPreviewReport,
    SplitReceipt,
    _inverse_drafts,
    plan_entities,
)
from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import ActorClass
from my_pa.domain.relationship.identity_correction import (
    IDENTITY_PREVIEW_LIFETIME,
    MAX_MERGED_AWAY_ENTITIES,
    IdentityConflict,
    IdentityConflictKind,
    IdentityEffect,
    IdentityEffectDraft,
    IdentityEffectFamily,
    IdentityEffectKind,
    IdentityOperation,
    IdentityOperationState,
    IdentityOperationType,
    IdentityPreview,
    blocks_merge,
    conflict_digest_for,
    effects_digest_for,
    plan_digest_for,
    preview_digest_for,
    sequence_effects,
    sequence_inverse_effects,
    state_digest,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.persistence.relationship_memory import SqlRelationshipMemoryRepository

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
SURVIVOR: Final = "ent_aaaa0001aaaa0001"
MERGED: Final = "ent_bbbb0002bbbb0002"
OTHER_MERGED: Final = "ent_cccc0003cccc0003"
OTHER_PRINCIPAL: Final = "prn_bbbb0002bbbb0002bbbb0002"

PREVIEW: Final = "eipv_aaaa0001aaaa01"
OPERATION: Final = "eiop_aaaa0001aaaa01"
EFFECT: Final = "eief_aaaa0001aaaa01"

CORRELATION: Final = "corr_aaaa0001aaaa0001"
AUDIT: Final = "audit_aaaa0001aaaa01"

WHEN: Final = datetime(2026, 8, 24, 12, tzinfo=UTC)
DIGEST: Final = "0" * 64
OTHER_DIGEST: Final = "1" * 64


def a_preview(**overrides: object) -> IdentityPreview:
    values: dict[str, object] = {
        "preview_id": PREVIEW,
        "principal_id": PRINCIPAL,
        "operation_type": IdentityOperationType.MERGE,
        "survivor_entity_id": SURVIVOR,
        "expected_survivor_version": 3,
        "merged_away": ((MERGED, 1),),
        "preview_digest": DIGEST,
        "conflict_digest": OTHER_DIGEST,
        "plan_digest": OTHER_DIGEST,
        "created_by": "operator",
        "actor_class": ActorClass.USER,
        "created_at": WHEN,
        "expires_at": WHEN + IDENTITY_PREVIEW_LIFETIME,
    }
    values.update(overrides)
    return IdentityPreview(**values)


def an_operation(**overrides: object) -> IdentityOperation:
    values: dict[str, object] = {
        "identity_operation_id": OPERATION,
        "principal_id": PRINCIPAL,
        "operation_type": IdentityOperationType.MERGE,
        "survivor_entity_id": SURVIVOR,
        "merged_entity_ids": (MERGED,),
        "preview_id": PREVIEW,
        "preview_digest": DIGEST,
        "idempotency_key": "merge-0001",
        "request_digest": OTHER_DIGEST,
        "performed_by": "operator",
        "actor_class": ActorClass.USER,
        "correlation_id": CORRELATION,
        "audit_id": AUDIT,
        "receipt_id": "rcpt_aaaa0001aaaa01",
        "state": IdentityOperationState.COMPLETED,
        "started_at": WHEN,
        "completed_at": WHEN + timedelta(seconds=2),
    }
    values.update(overrides)
    return IdentityOperation(**values)


def a_draft(
    record_id: str,
    *,
    family: IdentityEffectFamily = IdentityEffectFamily.ALIAS,
    kind: IdentityEffectKind = IdentityEffectKind.OWNER_REPARENTED,
) -> IdentityEffectDraft:
    return IdentityEffectDraft(
        family=family,
        record_id=record_id,
        kind=kind,
        before_state={"entity_id": MERGED},
        after_state={"entity_id": SURVIVOR},
    )


# --- the preview binding -----------------------------------------------------


def test_a_preview_expires_exactly_fifteen_minutes_after_it_was_created() -> None:
    assert timedelta(minutes=15) == IDENTITY_PREVIEW_LIFETIME
    assert a_preview().expires_at == WHEN + timedelta(minutes=15)


@pytest.mark.parametrize("minutes", [14, 16, 60])
def test_a_writer_cannot_choose_a_preview_lifetime(minutes: int) -> None:
    """The whole force of a fixed expiry is that no caller decides it."""
    with pytest.raises(ValueError, match="fifteen minutes"):
        a_preview(expires_at=WHEN + timedelta(minutes=minutes))


def test_a_preview_is_expired_at_its_expiry_and_not_before() -> None:
    preview = a_preview()
    assert not preview.is_expired(preview.expires_at - timedelta(seconds=1))
    assert preview.is_expired(preview.expires_at)


def test_a_preview_that_nothing_has_used_is_not_consumed() -> None:
    assert not a_preview().is_consumed
    assert a_preview(consumed_at=WHEN + timedelta(minutes=1)).is_consumed


def test_a_preview_cannot_be_consumed_before_it_was_created() -> None:
    with pytest.raises(ValueError, match="consumed before"):
        a_preview(consumed_at=WHEN - timedelta(seconds=1))


def test_a_preview_binds_its_preview_digest_and_not_its_conflict_digest() -> None:
    """The two columns are adjacent strings of the same shape; only one admits."""
    preview = a_preview()
    assert preview.binds(DIGEST)
    assert not preview.binds(OTHER_DIGEST)


def test_a_preview_merges_away_between_one_and_ten_entities() -> None:
    with pytest.raises(ValueError, match="between 1 and"):
        a_preview(merged_away=())
    too_many = tuple((f"ent_merged{index:08d}", 1) for index in range(MAX_MERGED_AWAY_ENTITIES + 1))
    with pytest.raises(ValueError, match="between 1 and"):
        a_preview(merged_away=too_many)


def test_a_preview_names_each_merged_away_entity_once() -> None:
    with pytest.raises(ValueError, match="each merged-away entity once"):
        a_preview(merged_away=((MERGED, 1), (MERGED, 2)))


def test_a_preview_does_not_merge_the_survivor_into_itself() -> None:
    with pytest.raises(ValueError, match="survivor into itself"):
        a_preview(merged_away=((SURVIVOR, 1),))


@pytest.mark.parametrize("version", [0, -1])
def test_a_preview_expects_versions_that_could_exist(version: int) -> None:
    with pytest.raises(ValueError, match="version that could exist"):
        a_preview(expected_survivor_version=version)
    with pytest.raises(ValueError, match="version that could exist"):
        a_preview(merged_away=((MERGED, version),))


@pytest.mark.parametrize("digest", ["", "not-a-digest", "0" * 63, "G" * 64])
def test_a_preview_digest_is_a_sha256_digest(digest: str) -> None:
    with pytest.raises(ValueError, match="sha256 digest"):
        a_preview(preview_digest=digest)
    with pytest.raises(ValueError, match="sha256 digest"):
        a_preview(conflict_digest=digest)
    with pytest.raises(ValueError, match="sha256 digest"):
        a_preview(plan_digest=digest)


def test_a_preview_names_a_preview_identifier_and_an_entity_identifier() -> None:
    with pytest.raises(InvalidIdentifierError):
        a_preview(preview_id=OPERATION)
    with pytest.raises(InvalidIdentifierError):
        a_preview(survivor_entity_id=PREVIEW)


# --- the digests -------------------------------------------------------------


def test_the_preview_digest_is_over_the_binding_and_is_order_insensitive() -> None:
    """Two requests naming the same entities in different orders are one preview."""
    forwards = preview_digest_for(
        operation_type=IdentityOperationType.MERGE,
        principal_id=PRINCIPAL,
        survivor_entity_id=SURVIVOR,
        expected_survivor_version=3,
        merged_away=((MERGED, 1), (OTHER_MERGED, 2)),
        plan_digest=OTHER_DIGEST,
    )
    backwards = preview_digest_for(
        operation_type=IdentityOperationType.MERGE,
        principal_id=PRINCIPAL,
        survivor_entity_id=SURVIVOR,
        expected_survivor_version=3,
        merged_away=((OTHER_MERGED, 2), (MERGED, 1)),
        plan_digest=OTHER_DIGEST,
    )
    assert forwards == backwards


@pytest.mark.parametrize(
    "tampered",
    [
        {"principal_id": "prn_bbbb0002bbbb0002bbbb0002"},
        {"survivor_entity_id": OTHER_MERGED},
        {"expected_survivor_version": 4},
        {"merged_away": ((MERGED, 2),)},
        {"merged_away": ((OTHER_MERGED, 1),)},
    ],
)
def test_the_preview_digest_moves_when_any_part_of_the_binding_moves(
    tampered: dict[str, object],
) -> None:
    """A request that changed an identity or a version cannot present as the original."""
    binding: dict[str, object] = {
        "operation_type": IdentityOperationType.MERGE,
        "principal_id": PRINCIPAL,
        "survivor_entity_id": SURVIVOR,
        "expected_survivor_version": 3,
        "merged_away": ((MERGED, 1),),
        "plan_digest": OTHER_DIGEST,
    }
    original = preview_digest_for(**binding)
    assert preview_digest_for(**{**binding, **tampered}) != original


def test_the_preview_token_moves_when_the_operator_visible_plan_moves() -> None:
    binding = {
        "operation_type": IdentityOperationType.MERGE,
        "principal_id": PRINCIPAL,
        "survivor_entity_id": SURVIVOR,
        "expected_survivor_version": 3,
        "merged_away": ((MERGED, 1),),
        "plan_digest": DIGEST,
    }
    assert preview_digest_for(**binding) != preview_digest_for(
        **{**binding, "plan_digest": OTHER_DIGEST}
    )


def test_the_plan_digest_is_order_insensitive_and_binds_counts_and_effect_states() -> None:
    conflict = IdentityConflict(
        IdentityConflictKind.AMBIGUOUS_DISPOSITION,
        IdentityEffectFamily.ALIAS,
        "alias_aaaa0001aaaa01",
    )
    effect = a_draft("alias_bbbb0002bbbb02")
    first = plan_digest_for(
        groups=(("alias", "transformed", 1), ("observation", "unchanged", 0)),
        conflicts=(conflict,),
        projected_effects=(effect,),
    )
    assert first == plan_digest_for(
        groups=(("observation", "unchanged", 0), ("alias", "transformed", 1)),
        conflicts=(conflict,),
        projected_effects=(effect,),
    )
    assert first != plan_digest_for(
        groups=(("alias", "transformed", 2), ("observation", "unchanged", 0)),
        conflicts=(conflict,),
        projected_effects=(effect,),
    )
    assert first != plan_digest_for(
        groups=(("alias", "transformed", 1), ("observation", "unchanged", 0)),
        conflicts=(conflict,),
        projected_effects=(
            IdentityEffectDraft(
                family=effect.family,
                record_id=effect.record_id,
                kind=effect.kind,
                before_state=effect.before_state,
                after_state={"entity_id": OTHER_MERGED},
            ),
        ),
    )


def test_the_conflict_digest_is_over_a_set_and_not_over_a_walk_order() -> None:
    conflicts = [
        IdentityConflict(
            kind=IdentityConflictKind.ACTIVE_IDENTIFIER_CONFLICT,
            family=IdentityEffectFamily.IDENTIFIER,
            record_id="xid_aaaa0001aaaa0001",
        ),
        IdentityConflict(
            kind=IdentityConflictKind.UNSUPPORTED_FAMILY,
            family=IdentityEffectFamily.PROPOSAL,
            record_id="eprp_aaaa0001aaaa01",
        ),
    ]
    assert conflict_digest_for(conflicts) == conflict_digest_for(list(reversed(conflicts)))
    assert conflict_digest_for(conflicts) == conflict_digest_for([*conflicts, conflicts[0]])


def test_a_conflict_appearing_between_preview_and_apply_moves_the_conflict_digest() -> None:
    """The case section 27 names: a concurrent identifier claim, versions unchanged."""
    empty = conflict_digest_for(())
    claimed = conflict_digest_for(
        [
            IdentityConflict(
                kind=IdentityConflictKind.ACTIVE_IDENTIFIER_CONFLICT,
                family=IdentityEffectFamily.IDENTIFIER,
                record_id="xid_aaaa0001aaaa0001",
            )
        ]
    )
    assert empty != claimed


def test_the_two_blocking_conflict_kinds_are_the_two_the_contract_names() -> None:
    blocking = {kind for kind in IdentityConflictKind if blocks_merge(kind)}
    assert blocking == {
        IdentityConflictKind.ACTIVE_IDENTIFIER_CONFLICT,
        IdentityConflictKind.UNSUPPORTED_FAMILY,
    }
    assert not blocks_merge(IdentityConflictKind.AMBIGUOUS_DISPOSITION)


def test_a_conflict_reports_whether_it_blocks_rather_than_storing_it() -> None:
    conflict = IdentityConflict(
        kind=IdentityConflictKind.AMBIGUOUS_DISPOSITION,
        family=IdentityEffectFamily.ASSIGNMENT,
        record_id="asn_aaaa0001aaaa0001",
    )
    assert not conflict.blocks
    assert "blocks" not in {declared.name for declared in fields(IdentityConflict)}


# --- the operation -----------------------------------------------------------


def test_an_operation_carries_a_preview_digest_and_an_idempotency_key_separately() -> None:
    """Section 23: the preview token is not the mutation idempotency key."""
    operation = an_operation()
    assert operation.preview_digest != operation.idempotency_key
    assert operation.request_digest != operation.preview_digest


def test_an_operation_never_reprs_its_key_or_its_reason() -> None:
    rendered = repr(an_operation(reason="duplicate synthetic contact rows"))
    assert "merge-0001" not in rendered
    assert "duplicate synthetic contact rows" not in rendered


def test_an_operation_in_progress_names_no_end() -> None:
    running = an_operation(state=IdentityOperationState.IN_PROGRESS, completed_at=None)
    assert running.completed_at is None
    with pytest.raises(ValueError, match="finished exactly when"):
        an_operation(state=IdentityOperationState.IN_PROGRESS)


@pytest.mark.parametrize("state", [IdentityOperationState.COMPLETED, IdentityOperationState.FAILED])
def test_a_finished_operation_names_an_end(state: IdentityOperationState) -> None:
    assert an_operation(state=state).completed_at is not None
    with pytest.raises(ValueError, match="finished exactly when"):
        an_operation(state=state, completed_at=None)


def test_an_operation_does_not_end_before_it_started() -> None:
    with pytest.raises(ValueError, match="end before it started"):
        an_operation(completed_at=WHEN - timedelta(seconds=1))


def test_an_operation_reason_is_bounded() -> None:
    with pytest.raises(ValueError, match="reason is bounded"):
        an_operation(reason="x" * 501)
    with pytest.raises(ValueError, match="reason is not blank"):
        an_operation(reason="   ")


def test_an_operation_names_each_merged_away_entity_once_and_not_the_survivor() -> None:
    with pytest.raises(ValueError, match="each merged-away entity once"):
        an_operation(merged_entity_ids=(MERGED, MERGED))
    with pytest.raises(ValueError, match="survivor into itself"):
        an_operation(merged_entity_ids=(SURVIVOR,))


def test_an_operation_carries_an_idempotency_key() -> None:
    with pytest.raises(ValueError, match="idempotency key"):
        an_operation(idempotency_key="")


def test_an_operation_requires_a_server_receipt_identifier() -> None:
    with pytest.raises(InvalidIdentifierError):
        an_operation(receipt_id="audit_aaaa0001aaaa01")


# --- the effect ledger -------------------------------------------------------


def test_an_effect_records_both_states_and_both_digests() -> None:
    effect = sequence_effects(
        [a_draft("eals_aaaa0001aaaa01")],
        identity_operation_id=OPERATION,
        principal_id=PRINCIPAL,
        recorded_at=WHEN,
    )[0]
    assert effect.before_state == {"entity_id": MERGED}
    assert effect.after_state == {"entity_id": SURVIVOR}
    assert effect.before_sha256 == state_digest(effect.before_state)
    assert effect.after_sha256 == state_digest(effect.after_state)


def test_an_effect_refuses_a_state_that_disagrees_with_its_recorded_digest() -> None:
    """The tamper detection the append-only trigger cannot supply on its own."""
    with pytest.raises(ValueError, match="does not match its recorded digest"):
        IdentityEffect(
            effect_id=EFFECT,
            identity_operation_id=OPERATION,
            principal_id=PRINCIPAL,
            sequence=1,
            family=IdentityEffectFamily.ALIAS,
            record_id="eals_aaaa0001aaaa01",
            kind=IdentityEffectKind.OWNER_REPARENTED,
            before_state={"entity_id": MERGED},
            after_state={"entity_id": SURVIVOR},
            before_sha256=state_digest({"entity_id": OTHER_MERGED}),
            after_sha256=state_digest({"entity_id": SURVIVOR}),
            recorded_at=WHEN,
        )


def test_an_effect_records_a_change_rather_than_a_repetition() -> None:
    with pytest.raises(ValueError, match="records a change"):
        IdentityEffectDraft(
            family=IdentityEffectFamily.ALIAS,
            record_id="eals_aaaa0001aaaa01",
            kind=IdentityEffectKind.OWNER_REPARENTED,
            before_state={"entity_id": MERGED},
            after_state={"entity_id": MERGED},
        )


@pytest.mark.parametrize(
    ("family", "record_id"),
    [
        (IdentityEffectFamily.ENTITY, MERGED),
        (IdentityEffectFamily.ALIAS, "eals_aaaa0001aaaa01"),
        (IdentityEffectFamily.IDENTIFIER, "xid_aaaa0001aaaa0001"),
        (IdentityEffectFamily.ASSIGNMENT, "asn_aaaa0001aaaa0001"),
        (IdentityEffectFamily.RELATIONSHIP, "erel_aaaa0001aaaa01"),
        (IdentityEffectFamily.RELATIONSHIP_MEMORY, "mem_aaaa0001aaaa01"),
    ],
)
def test_a_split_restores_semantics_without_restoring_an_old_version(
    family: IdentityEffectFamily, record_id: str
) -> None:
    """RI-FC-WP-07: inverse state is historical evidence, not a reusable token."""
    before = {"semantic": "before", "version": 7}
    after = {"semantic": "after", "version": 8}
    source = IdentityEffect(
        effect_id=EFFECT,
        identity_operation_id=OPERATION,
        principal_id=PRINCIPAL,
        sequence=1,
        family=family,
        record_id=record_id,
        kind=(
            IdentityEffectKind.ENTITY_REDIRECTED
            if family is IdentityEffectFamily.ENTITY
            else IdentityEffectKind.OWNER_REPARENTED
        ),
        before_state=before,
        after_state=after,
        before_sha256=state_digest(before),
        after_sha256=state_digest(after),
        recorded_at=WHEN,
    )

    restored = _inverse_drafts((source,))[0]

    assert source.before_state == {"semantic": "before", "version": 7}
    assert restored.before_state == {"semantic": "after", "version": 8}
    assert restored.after_state == {"semantic": "before", "version": 9}


def test_a_redirect_advances_the_merged_entity_version() -> None:
    merged = Entity(
        entity_id=MERGED,
        principal_id=PRINCIPAL,
        entity_type=EntityType.PERSON,
        canonical_name=normalize_name("Synthetic Person"),
        display_name="Synthetic Person",
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=7,
    )

    change = plan_entities(SURVIVOR, (merged,))[0]

    assert change.before_state["version"] == 7
    assert change.after_state["version"] == 8
    assert change.expected_version == 7


def test_relationship_memory_merge_and_split_advance_one_token_each() -> None:
    def rows(*values: SimpleNamespace) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: list(values))

    planning = MagicMock()
    planning.execute.side_effect = [
        rows(
            SimpleNamespace(
                memory_id="mem_aaaa0001aaaa01",
                subject_entity_id=MERGED,
                origin_subject_entity_id=MERGED,
                version=7,
            )
        ),
        rows(),
        rows(),
    ]
    draft = SqlRelationshipMemoryRepository(planning).plan_identity_merge(
        PRINCIPAL, frozenset({MERGED}), SURVIVOR, 5
    )[0]
    assert draft.before_state == {
        "subject_entity_id": MERGED,
        "origin_subject_entity_id": MERGED,
        "version": 7,
    }
    assert draft.after_state == {
        "subject_entity_id": SURVIVOR,
        "origin_subject_entity_id": MERGED,
        "version": 8,
    }

    source = sequence_effects(
        (draft,),
        identity_operation_id=OPERATION,
        principal_id=PRINCIPAL,
        recorded_at=WHEN,
    )[0]
    assert source.before_sha256 == state_digest(source.before_state)
    assert source.after_sha256 == state_digest(source.after_state)

    merging = MagicMock()
    merging.execute.return_value = SimpleNamespace(rowcount=1)
    SqlRelationshipMemoryRepository(merging).apply_identity_effect(PRINCIPAL, draft)
    merge_statement = merging.execute.call_args.args[0]
    assert merge_statement._values["subject_entity_id"].value == SURVIVOR
    assert merge_statement._values["origin_subject_entity_id"].value == MERGED
    assert merge_statement._values["version"].value == 8
    assert "relationship_memories.version = 7" in str(
        merge_statement.compile(compile_kwargs={"literal_binds": True})
    )

    split = _inverse_drafts((source,))[0]
    assert split.before_state == source.after_state
    assert split.after_state == {
        "subject_entity_id": MERGED,
        "origin_subject_entity_id": MERGED,
        "version": 9,
    }

    restoring = MagicMock()
    restoring.execute.return_value = SimpleNamespace(rowcount=1)
    SqlRelationshipMemoryRepository(restoring).restore_identity_effect(
        PRINCIPAL, source, restored_state=split.after_state
    )
    statement = restoring.execute.call_args.args[0]
    assert statement._values["subject_entity_id"].value == MERGED
    assert statement._values["origin_subject_entity_id"].value == MERGED
    assert statement._values["version"].value == 9
    assert "relationship_memories.version = 8" in str(
        statement.compile(compile_kwargs={"literal_binds": True})
    )


class _SplitEntities:
    """The split service's exact port surface, kept deliberately in memory."""

    def __init__(self, source: IdentityOperation, effects: tuple[IdentityEffect, ...]) -> None:
        self.source = source
        self.effects_by_operation = {source.identity_operation_id: effects}
        self.preview: IdentityPreview | None = None
        self.operations_by_key: dict[str, IdentityOperation] = {}
        self.restored: list[IdentityEffect] = []
        self.survivor = Entity(
            entity_id=SURVIVOR,
            principal_id=PRINCIPAL,
            entity_type=EntityType.PERSON,
            canonical_name=normalize_name("Synthetic Survivor"),
            display_name="Synthetic Survivor",
            status=EntityStatus.ACTIVE,
            created_at=WHEN,
            updated_at=WHEN,
            version=3,
        )

    def identity_operation(self, principal_id: str, operation_id: str) -> IdentityOperation | None:
        if principal_id != PRINCIPAL or operation_id != self.source.identity_operation_id:
            return None
        return self.source

    def split_for_source_operation(
        self, principal_id: str, source_operation_id: str
    ) -> IdentityOperation | None:
        if principal_id != PRINCIPAL:
            return None
        return next(
            (
                operation
                for operation in self.operations_by_key.values()
                if operation.source_identity_operation_id == source_operation_id
                and operation.state is IdentityOperationState.COMPLETED
            ),
            None,
        )

    def identity_effects(self, principal_id: str, operation_id: str) -> list[IdentityEffect]:
        if principal_id != PRINCIPAL:
            return []
        return list(self.effects_by_operation.get(operation_id, ()))

    def identity_effect_matches_after_state(
        self, principal_id: str, effect: IdentityEffect
    ) -> bool:
        return principal_id == PRINCIPAL

    def records_bound_to_entity_outside(
        self,
        principal_id: str,
        family: IdentityEffectFamily,
        entity_id: str,
        known_record_ids: Collection[str],
        *,
        limit: int,
    ) -> list[str]:
        """Nothing was created against the survivor after this synthetic merge."""
        assert principal_id == PRINCIPAL and entity_id == SURVIVOR and limit > 0
        del family, known_record_ids
        return []

    def preview_ambiguities(self, principal_id: str, preview_id: str) -> list[object]:
        """This merge's whole ledger still matches, so the preview asked nothing."""
        assert principal_id == PRINCIPAL
        del preview_id
        return []

    def get(self, principal_id: str, entity_id: str) -> Entity | None:
        if principal_id == PRINCIPAL and entity_id == SURVIVOR:
            return self.survivor
        return None

    def record_identity_preview(self, principal_id: str, preview: IdentityPreview) -> None:
        assert principal_id == PRINCIPAL
        self.preview = preview

    def identity_operation_for_key(
        self, principal_id: str, idempotency_key: str
    ) -> IdentityOperation | None:
        return None if principal_id != PRINCIPAL else self.operations_by_key.get(idempotency_key)

    def identity_preview(self, principal_id: str, preview_id: str) -> IdentityPreview | None:
        if (
            principal_id != PRINCIPAL
            or self.preview is None
            or self.preview.preview_id != preview_id
        ):
            return None
        return self.preview

    def serialize_identifier_entity_scopes(
        self, principal_id: str, entity_ids: frozenset[str]
    ) -> None:
        assert principal_id == PRINCIPAL
        assert entity_ids == {SURVIVOR, MERGED}

    def consume_identity_preview(self, principal_id: str, preview_id: str, *, at: datetime) -> bool:
        if (
            principal_id != PRINCIPAL
            or self.preview is None
            or self.preview.preview_id != preview_id
            or self.preview.is_consumed
        ):
            return False
        self.preview = replace(self.preview, consumed_at=at)
        return True

    def record_identity_operation(self, principal_id: str, operation: IdentityOperation) -> None:
        assert principal_id == PRINCIPAL
        self.operations_by_key[operation.idempotency_key] = operation

    def restore_identity_effect(self, principal_id: str, effect: IdentityEffect) -> None:
        assert principal_id == PRINCIPAL
        self.restored.append(effect)

    def record_identity_effects(
        self, principal_id: str, effects: tuple[IdentityEffect, ...]
    ) -> None:
        assert principal_id == PRINCIPAL
        assert self.operations_by_key
        operation = next(reversed(self.operations_by_key.values()))
        self.effects_by_operation[operation.identity_operation_id] = effects

    def complete_identity_operation(self, principal_id: str, operation: IdentityOperation) -> None:
        assert principal_id == PRINCIPAL
        self.operations_by_key[operation.idempotency_key] = operation


class _SplitMemories:
    def __init__(self) -> None:
        self.restored: list[IdentityEffect] = []

    def identity_effect_matches_after_state(
        self, principal_id: str, effect: IdentityEffect
    ) -> bool:
        return principal_id == PRINCIPAL

    def restore_identity_effect(
        self,
        principal_id: str,
        effect: IdentityEffect,
        *,
        restored_state: Mapping[str, object],
    ) -> None:
        assert principal_id == PRINCIPAL
        assert restored_state
        self.restored.append(effect)


def _split_fixture() -> tuple[_SplitEntities, _SplitMemories, IdentityCorrectionService]:
    drafts = (
        IdentityEffectDraft(
            family=IdentityEffectFamily.ENTITY,
            record_id=MERGED,
            kind=IdentityEffectKind.ENTITY_REDIRECTED,
            before_state={"status": "active", "superseded_by_entity_id": None, "version": 7},
            after_state={
                "status": "merged_redirect",
                "superseded_by_entity_id": SURVIVOR,
                "version": 8,
            },
        ),
        IdentityEffectDraft(
            family=IdentityEffectFamily.RELATIONSHIP_MEMORY,
            record_id="mem_aaaa0001aaaa01",
            kind=IdentityEffectKind.DERIVED_STATE_INVALIDATED,
            before_state={"subject_entity_id": MERGED, "provenance": "source", "version": 7},
            after_state={"subject_entity_id": SURVIVOR, "provenance": "source", "version": 8},
        ),
    )
    effects = sequence_effects(
        drafts,
        identity_operation_id=OPERATION,
        principal_id=PRINCIPAL,
        recorded_at=WHEN,
    )
    source = an_operation(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=(MERGED,),
        effect_count=len(effects),
        effects_digest=effects_digest_for(effects),
    )
    entities = _SplitEntities(source, effects)
    memories = _SplitMemories()
    return entities, memories, IdentityCorrectionService(entities, memories)  # type: ignore[arg-type]


def _split_preview(service: IdentityCorrectionService) -> SplitPreviewReport:
    return service.split_preview(
        SplitPreviewCommand(
            principal_id=PRINCIPAL,
            source_identity_operation_id=OPERATION,
            reason="reverse the synthetic mistaken merge",
        ),
        at=WHEN,
        requested_by="operator",
        actor_class=ActorClass.USER,
        has_operator_authority=True,
    )


def _split_apply(
    service: IdentityCorrectionService, preview: IdentityPreview, **overrides: object
) -> SplitReceipt:
    values: dict[str, object] = {
        "principal_id": PRINCIPAL,
        "preview_id": preview.preview_id,
        "preview_digest": preview.preview_digest,
        "idempotency_key": "split-0001",
        "reason": "reverse the synthetic mistaken merge",
    }
    values.update(overrides)
    return service.split_apply(
        SplitCommand(**values),
        at=WHEN + timedelta(seconds=1),
        correlation_id=CORRELATION,
        audit_id=AUDIT,
        performed_by="operator",
        actor_class=ActorClass.USER,
        has_operator_authority=True,
    )


def test_split_service_restores_semantics_memory_provenance_and_replays_exactly() -> None:
    entities, memories, service = _split_fixture()
    report = _split_preview(service)

    first = _split_apply(service, report.preview)
    replay = _split_apply(service, report.preview)

    assert first.replayed is False
    assert replay == replace(first, replayed=True)
    assert [effect.family for effect in entities.restored] == [IdentityEffectFamily.ENTITY]
    assert [effect.family for effect in memories.restored] == [
        IdentityEffectFamily.RELATIONSHIP_MEMORY
    ]
    memory_inverse = next(
        effect
        for effect in first.effects
        if effect.family is IdentityEffectFamily.RELATIONSHIP_MEMORY
    )
    assert memory_inverse.after_state == {
        "subject_entity_id": MERGED,
        "provenance": "source",
        "version": 9,
    }
    assert memory_inverse.before_sha256 == state_digest(memory_inverse.before_state)
    assert memory_inverse.after_sha256 == state_digest(memory_inverse.after_state)
    entity_inverse = next(
        effect for effect in first.effects if effect.family is IdentityEffectFamily.ENTITY
    )
    assert entity_inverse.after_state["version"] == 9


def test_split_service_refuses_expiry_stale_version_and_incomplete_ledger() -> None:
    entities, _, service = _split_fixture()
    report = _split_preview(service)
    with pytest.raises(ConflictError):
        service.split_apply(
            SplitCommand(
                principal_id=PRINCIPAL,
                preview_id=report.preview.preview_id,
                preview_digest=report.preview.preview_digest,
                idempotency_key="expired",
                reason="reverse the synthetic mistaken merge",
            ),
            at=report.preview.expires_at,
            correlation_id=CORRELATION,
            audit_id=AUDIT,
            performed_by="operator",
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    entities.survivor = replace(entities.survivor, version=4)
    with pytest.raises(ConflictError):
        _split_apply(service, report.preview, idempotency_key="stale")

    incomplete_entities, _, incomplete = _split_fixture()
    incomplete_entities.source = replace(incomplete_entities.source, effect_count=99)
    with pytest.raises(ConflictError):
        _split_preview(incomplete)


def test_split_service_refuses_cross_principal_and_missing_operator_authority() -> None:
    _, _, service = _split_fixture()
    with pytest.raises(NotFoundError):
        service.split_preview(
            SplitPreviewCommand(
                principal_id=OTHER_PRINCIPAL,
                source_identity_operation_id=OPERATION,
                reason="reverse the synthetic mistaken merge",
            ),
            at=WHEN,
            requested_by="operator",
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with pytest.raises(DeniedError):
        service.split_preview(
            SplitPreviewCommand(
                principal_id=PRINCIPAL,
                source_identity_operation_id=OPERATION,
                reason="reverse the synthetic mistaken merge",
            ),
            at=WHEN,
            requested_by="operator",
            actor_class=ActorClass.USER,
            has_operator_authority=False,
        )


def test_an_effect_refuses_a_state_that_says_nothing() -> None:
    """A recorded state of `{}` is a redirect-only ledger written one row at a time."""
    with pytest.raises(ValueError, match="says something"):
        IdentityEffectDraft(
            family=IdentityEffectFamily.ENTITY,
            record_id=MERGED,
            kind=IdentityEffectKind.ENTITY_REDIRECTED,
            before_state={},
            after_state={"status": "merged_redirect"},
        )


def test_an_effect_names_an_opaque_record_id_of_any_family() -> None:
    with pytest.raises(InvalidIdentifierError):
        a_draft("/etc/passwd")


# --- deterministic ordering --------------------------------------------------


def _drafts() -> list[IdentityEffectDraft]:
    return [
        a_draft(
            MERGED,
            family=IdentityEffectFamily.ENTITY,
            kind=IdentityEffectKind.ENTITY_REDIRECTED,
        ),
        a_draft("eals_aaaa0001aaaa01"),
        a_draft("eals_bbbb0002bbbb02"),
        a_draft("xid_aaaa0001aaaa0001", family=IdentityEffectFamily.IDENTIFIER),
        a_draft(
            "erel_aaaa0001aaaa01",
            family=IdentityEffectFamily.RELATIONSHIP,
            kind=IdentityEffectKind.SELF_EDGE_SUPERSEDED,
        ),
        a_draft(
            "eprp_aaaa0001aaaa01",
            family=IdentityEffectFamily.PROPOSAL,
            kind=IdentityEffectKind.DEPENDENT_INVALIDATED,
        ),
    ]


def _numbering(drafts: list[IdentityEffectDraft]) -> list[tuple[int, str, str]]:
    return [
        (effect.sequence, effect.family.value, effect.record_id)
        for effect in sequence_effects(
            drafts,
            identity_operation_id=OPERATION,
            principal_id=PRINCIPAL,
            recorded_at=WHEN,
        )
    ]


def test_the_same_effects_are_numbered_the_same_way_however_they_were_found() -> None:
    """Determinism as a measured property: the walk order must not reach the ledger.

    Every permutation rather than a sample of shuffles. A sampled proof of a
    property this small says only that the sampler did not find the counterexample,
    and an emitter walking six affected families can produce any of these orders.
    """
    expected = _numbering(_drafts())
    for order in permutations(range(len(_drafts()))):
        reordered = [_drafts()[position] for position in order]
        assert _numbering(reordered) == expected


def test_the_ledger_numbers_from_one_without_gaps() -> None:
    numbering = _numbering(_drafts())
    assert [sequence for sequence, _, _ in numbering] == list(range(1, len(numbering) + 1))


def test_the_identity_change_is_recorded_before_what_it_caused() -> None:
    """`WP-07` walks the ledger backwards, so the redirect must be first here."""
    first_sequence, first_family, first_record = _numbering(_drafts())[0]
    assert (first_sequence, first_family, first_record) == (
        1,
        IdentityEffectFamily.ENTITY.value,
        MERGED,
    )


def test_an_operation_records_one_effect_per_record() -> None:
    duplicated = [
        a_draft("eals_aaaa0001aaaa01"),
        a_draft("eals_aaaa0001aaaa01", kind=IdentityEffectKind.ROW_COALESCED),
    ]
    with pytest.raises(ValueError, match="one effect per record"):
        sequence_effects(
            duplicated,
            identity_operation_id=OPERATION,
            principal_id=PRINCIPAL,
            recorded_at=WHEN,
        )


def test_the_same_record_in_two_families_is_two_effects() -> None:
    """`record_id` is unique per family, not globally; the pair is what identifies a row."""
    numbering = _numbering(
        [
            a_draft("eals_aaaa0001aaaa01"),
            a_draft("eals_aaaa0001aaaa01", family=IdentityEffectFamily.OBSERVATION),
        ]
    )
    assert len(numbering) == 2


def test_effect_identifiers_are_issued_rather_than_derived_from_their_subject() -> None:
    """A deterministic identifier would be one derived from the row it names."""
    drafts = [a_draft("eals_aaaa0001aaaa01")]
    first = sequence_effects(
        drafts, identity_operation_id=OPERATION, principal_id=PRINCIPAL, recorded_at=WHEN
    )[0]
    second = sequence_effects(
        drafts, identity_operation_id=OPERATION, principal_id=PRINCIPAL, recorded_at=WHEN
    )[0]
    assert first.effect_id != second.effect_id
    assert first.sequence == second.sequence


# --- the closed vocabularies -------------------------------------------------


def test_the_operation_type_admits_only_what_this_phase_performs() -> None:
    """`WP-07` widens this with the code that writes the value."""
    assert [member.value for member in IdentityOperationType] == ["merge", "split"]


def test_a_split_preview_and_operation_bind_exactly_one_source_merge() -> None:
    source = "eiop_bbbb0002bbbb02"
    preview = a_preview(
        operation_type=IdentityOperationType.SPLIT,
        source_identity_operation_id=source,
    )
    operation = an_operation(
        operation_type=IdentityOperationType.SPLIT,
        source_identity_operation_id=source,
    )
    assert preview.source_identity_operation_id == source
    assert operation.source_identity_operation_id == source
    with pytest.raises(ValueError, match="source merge"):
        a_preview(operation_type=IdentityOperationType.SPLIT)
    with pytest.raises(ValueError, match="source merge"):
        an_operation(source_identity_operation_id=source)


def test_an_inverse_is_numbered_in_exact_reverse_source_order() -> None:
    source = sequence_effects(
        _drafts(),
        identity_operation_id=OPERATION,
        principal_id=PRINCIPAL,
        recorded_at=WHEN,
    )
    inverse = sequence_inverse_effects(
        source,
        identity_operation_id="eiop_bbbb0002bbbb02",
        principal_id=PRINCIPAL,
        recorded_at=WHEN + timedelta(seconds=1),
    )
    assert [(row.family, row.record_id) for row in inverse] == [
        (row.family, row.record_id) for row in reversed(source)
    ]
    assert all(
        inverse_row.before_state == source_row.after_state
        and inverse_row.after_state == source_row.before_state
        for inverse_row, source_row in zip(inverse, reversed(source), strict=True)
    )
    assert effects_digest_for(inverse) == effects_digest_for(tuple(inverse))


def test_every_effect_kind_names_a_transformation_of_an_existing_row() -> None:
    """Both states are required precisely because no kind creates or destroys one."""
    assert {member.value for member in IdentityEffectKind} == {
        "entity_redirected",
        "owner_reparented",
        "row_coalesced",
        "self_edge_superseded",
        "dependent_invalidated",
        "derived_state_invalidated",
    }


def test_the_effect_families_include_the_ones_a_mutation_ledger_excludes() -> None:
    """A merge does something to a proposal, and an inversion has to put it back."""
    families = {member.value for member in IdentityEffectFamily}
    assert {"proposal", "review_case", "derived_context"} <= families
