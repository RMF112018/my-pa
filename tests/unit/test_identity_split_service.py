"""Direct behavioral proof for governed split preview and apply.

The transport suites prove exposure.  These tests call the service itself so
the inverse order, source-ledger binding, version check, replay, and one-winner
preview consumption remain load-bearing without a database runtime.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Final, cast

import pytest

from my_pa.application.errors import (
    ConflictError,
    DeniedError,
    InvalidRequestError,
    NotFoundError,
)
from my_pa.application.identity_correction import (
    IdentityCorrectionService,
    SplitCommand,
    SplitDisposition,
    SplitPreviewCommand,
    SplitPreviewReport,
    SplitReceipt,
)
from my_pa.contracts.ports import (
    AmbiguitySettlement,
    EntitiesRepository,
    PreviewAmbiguity,
    RelationshipMemoryRepository,
)
from my_pa.domain.relationship.entity import (
    AliasState,
    AliasType,
    Entity,
    EntityAlias,
    EntityStatus,
    EntityType,
)
from my_pa.domain.relationship.governance import ActorClass, EntityProposal
from my_pa.domain.relationship.identity_correction import (
    AmbiguityDisposition,
    AmbiguityReason,
    IdentityEffect,
    IdentityEffectDraft,
    IdentityEffectFamily,
    IdentityEffectKind,
    IdentityOperation,
    IdentityOperationState,
    IdentityOperationType,
    IdentityPreview,
    dispositions_for,
    effects_digest_for,
    sequence_effects,
)
from my_pa.domain.relationship.normalization import normalize_name

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
OTHER_PRINCIPAL: Final = "prn_bbbb0002bbbb0002bbbb0002"
SURVIVOR: Final = "ent_aaaa0001aaaa0001"
MERGED: Final = "ent_bbbb0002bbbb0002"
SOURCE_OPERATION: Final = "eiop_aaaa0001aaaa01"
WHEN: Final = datetime(2026, 8, 28, 12, tzinfo=UTC)


def _entity(entity_id: str, *, version: int = 1) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=PRINCIPAL,
        entity_type=EntityType.PERSON,
        canonical_name=normalize_name("Synthetic Person"),
        display_name="Synthetic Person",
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=version,
    )


def _source_effects() -> tuple[IdentityEffect, ...]:
    return sequence_effects(
        (
            IdentityEffectDraft(
                family=IdentityEffectFamily.ENTITY,
                record_id=MERGED,
                kind=IdentityEffectKind.ENTITY_REDIRECTED,
                before_state={
                    "status": "active",
                    "superseded_by_entity_id": None,
                    "version": 1,
                },
                after_state={
                    "status": "merged_redirect",
                    "superseded_by_entity_id": SURVIVOR,
                    "version": 1,
                },
            ),
            IdentityEffectDraft(
                family=IdentityEffectFamily.RELATIONSHIP_MEMORY,
                record_id="mem_aaaa0001aaaa01",
                kind=IdentityEffectKind.OWNER_REPARENTED,
                before_state={
                    "subject_entity_id": MERGED,
                    "origin_subject_entity_id": MERGED,
                    "version": 1,
                },
                after_state={
                    "subject_entity_id": SURVIVOR,
                    "origin_subject_entity_id": MERGED,
                    "version": 2,
                },
            ),
        ),
        identity_operation_id=SOURCE_OPERATION,
        principal_id=PRINCIPAL,
        recorded_at=WHEN,
    )


def _source(*, effects: tuple[IdentityEffect, ...] | None = None) -> IdentityOperation:
    held = _source_effects() if effects is None else effects
    return IdentityOperation(
        identity_operation_id=SOURCE_OPERATION,
        principal_id=PRINCIPAL,
        operation_type=IdentityOperationType.MERGE,
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=(MERGED,),
        preview_id="eipv_aaaa0001aaaa01",
        preview_digest="0" * 64,
        idempotency_key="source-merge",
        request_digest="1" * 64,
        reason="synthetic duplicate",
        performed_by="operator",
        actor_class=ActorClass.USER,
        correlation_id="corr_aaaa0001aaaa0001",
        audit_id="audit_aaaa0001aaaa01",
        receipt_id="rcpt_aaaa0001aaaa01",
        state=IdentityOperationState.COMPLETED,
        started_at=WHEN,
        completed_at=WHEN,
        effect_count=len(held),
        effects_digest=effects_digest_for(held),
    )


class _Entities:
    def __init__(self) -> None:
        self.effects = _source_effects()
        self.source = _source(effects=self.effects)
        self.entities = {SURVIVOR: _entity(SURVIVOR), MERGED: _entity(MERGED)}
        self.preview: IdentityPreview | None = None
        self.operations: list[IdentityOperation] = []
        self.split_effects: tuple[IdentityEffect, ...] = ()
        self.restored: list[tuple[IdentityEffectFamily, str]] = []
        self.restoration_order: list[tuple[IdentityEffectFamily, str]] = []
        self.consume_wins = True
        self.states_match = True
        self.created_after_merge: dict[IdentityEffectFamily, tuple[str, ...]] = {}
        self.ambiguities: tuple[PreviewAmbiguity, ...] = ()
        self.settlements: tuple[AmbiguitySettlement, ...] = ()
        self.reparented: list[tuple[IdentityEffectFamily, str, str, int]] = []
        self.bound_aliases: list[EntityAlias] = []
        self.mismatched: set[str] = set()
        self.proposals_list: list[EntityProposal] = []

    def observation(self, principal_id: str, reference: str) -> None:
        del principal_id, reference
        return None

    def proposals(self, principal_id: str) -> list[EntityProposal]:
        """No proposal-family `POST_MERGE_CREATED` case is exercised at this layer.

        `tests/database/test_identity_split_ambiguity.py` proves it against a
        real `entity_proposals` row and its payload; this fake stays empty so
        `_post_merge_created`'s proposal-discovery loop is a no-op here rather
        than an `AttributeError`.
        """
        assert principal_id == PRINCIPAL
        return list(self.proposals_list)

    def identity_operation(self, principal_id: str, operation_id: str) -> IdentityOperation | None:
        if principal_id != PRINCIPAL or operation_id != SOURCE_OPERATION:
            return None
        return self.source

    def split_for_source_operation(self, principal_id: str, operation_id: str) -> object | None:
        if principal_id != PRINCIPAL or operation_id != SOURCE_OPERATION:
            return None
        return next(
            (
                operation
                for operation in self.operations
                if operation.state is IdentityOperationState.COMPLETED
                and operation.source_identity_operation_id == operation_id
            ),
            None,
        )

    def identity_effects(self, principal_id: str, operation_id: str) -> tuple[IdentityEffect, ...]:
        if principal_id != PRINCIPAL:
            return ()
        return self.effects if operation_id == SOURCE_OPERATION else self.split_effects

    def identity_effect_matches_after_state(
        self, principal_id: str, effect: IdentityEffect
    ) -> bool:
        return (
            principal_id == PRINCIPAL
            and self.states_match
            and effect.record_id not in self.mismatched
            and effect.family is not IdentityEffectFamily.RELATIONSHIP_MEMORY
        )

    def records_bound_to_entity_outside(
        self,
        principal_id: str,
        family: IdentityEffectFamily,
        entity_id: str,
        known_record_ids: Collection[str],
        *,
        limit: int,
    ) -> list[str]:
        """What was created against the survivor after the merge, per family."""
        assert principal_id == PRINCIPAL and entity_id == SURVIVOR and limit > 0
        return [
            record_id
            for record_id in self.created_after_merge.get(family, ())
            if record_id not in known_record_ids
        ]

    def record_preview_ambiguities(
        self, principal_id: str, ambiguities: tuple[PreviewAmbiguity, ...]
    ) -> None:
        assert principal_id == PRINCIPAL
        self.ambiguities = ambiguities

    def preview_ambiguities(self, principal_id: str, preview_id: str) -> list[PreviewAmbiguity]:
        assert principal_id == PRINCIPAL
        return [ambiguity for ambiguity in self.ambiguities if ambiguity.preview_id == preview_id]

    def record_ambiguity_settlements(
        self, principal_id: str, settlements: tuple[AmbiguitySettlement, ...]
    ) -> None:
        assert principal_id == PRINCIPAL
        self.settlements = settlements

    def get(self, principal_id: str, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id) if principal_id == PRINCIPAL else None

    def record_identity_preview(self, principal_id: str, preview: IdentityPreview) -> None:
        assert principal_id == PRINCIPAL
        self.preview = preview

    def identity_operation_for_key(
        self, principal_id: str, idempotency_key: str
    ) -> IdentityOperation | None:
        if principal_id != PRINCIPAL:
            return None
        return next(
            (
                operation
                for operation in self.operations
                if operation.idempotency_key == idempotency_key
            ),
            None,
        )

    def identity_preview(self, principal_id: str, preview_id: str) -> IdentityPreview | None:
        if principal_id != PRINCIPAL or self.preview is None:
            return None
        return self.preview if self.preview.preview_id == preview_id else None

    def serialize_identifier_entity_scopes(
        self, principal_id: str, entity_ids: frozenset[str]
    ) -> None:
        assert principal_id == PRINCIPAL
        assert entity_ids == frozenset({SURVIVOR, MERGED})

    def consume_identity_preview(self, principal_id: str, preview_id: str, *, at: datetime) -> bool:
        assert self.preview is not None
        assert principal_id == PRINCIPAL and self.preview.preview_id == preview_id
        if not self.consume_wins:
            return False
        self.preview = replace(self.preview, consumed_at=at)
        return True

    def record_identity_operation(self, principal_id: str, operation: IdentityOperation) -> None:
        assert principal_id == PRINCIPAL
        self.operations.append(operation)

    def restore_identity_effect(self, principal_id: str, effect: IdentityEffect) -> None:
        assert principal_id == PRINCIPAL
        self.restored.append((effect.family, effect.record_id))
        self.restoration_order.append((effect.family, effect.record_id))

    def aliases(
        self, principal_id: str, entity_id: str, *, limit: int | None = None
    ) -> list[EntityAlias]:
        assert principal_id == PRINCIPAL and limit is not None
        return [alias for alias in self.bound_aliases if alias.entity_id == entity_id]

    def reparent_entity_reference(
        self,
        principal_id: str,
        *,
        family: IdentityEffectFamily,
        record_id: str,
        from_entity_ids: frozenset[str],
        to_entity_id: str,
        expected_version: int,
        at: datetime,
        after_state: Mapping[str, object] | None = None,
    ) -> None:
        # RI-ENT-WP-06b widened the real reparent_entity_reference with an
        # after_state keyword (non-entity-reference columns a reparenting also
        # writes, e.g. is_preferred demotion). This fake accepts and ignores its
        # value -- nothing this file asserts on `self.reparented` depends on it,
        # and a stale signature without this parameter would raise TypeError the
        # moment a real caller passed it (the same regression fixed in
        # tests/recovery/test_identity_correction_recovery.py's sibling fake).
        assert principal_id == PRINCIPAL and from_entity_ids == frozenset({SURVIVOR}) and at
        self.reparented.append((family, record_id, to_entity_id, expected_version))

    def record_identity_effects(
        self, principal_id: str, effects: tuple[IdentityEffect, ...]
    ) -> None:
        assert principal_id == PRINCIPAL
        self.split_effects = effects

    def complete_identity_operation(self, principal_id: str, operation: IdentityOperation) -> None:
        assert principal_id == PRINCIPAL
        self.operations[-1] = operation


class _Memories:
    def __init__(self) -> None:
        self.restored: list[tuple[IdentityEffectFamily, str]] = []
        self.restoration_order: list[tuple[IdentityEffectFamily, str]] = []
        self.states_match = True
        self.created_after_merge: dict[IdentityEffectFamily, tuple[str, ...]] = {}

    def identity_effect_matches_after_state(
        self, principal_id: str, effect: IdentityEffect
    ) -> bool:
        return principal_id == PRINCIPAL and self.states_match

    def records_bound_to_entity_outside(
        self,
        principal_id: str,
        family: IdentityEffectFamily,
        entity_id: str,
        known_record_ids: Collection[str],
        *,
        limit: int,
    ) -> list[str]:
        """The memory plane's half of `_Entities.records_bound_to_entity_outside` above.

        No `RELATIONSHIP_MEMORY`/`MEMORY_PROPOSAL`/`MEMORY_CONTEXT_LINK`
        `POST_MERGE_CREATED` case is exercised at this layer either -- see
        `_Entities.proposals`'s docstring for why that lives at the database
        tier instead.
        """
        assert principal_id == PRINCIPAL and entity_id == SURVIVOR and limit > 0
        return [
            record_id
            for record_id in self.created_after_merge.get(family, ())
            if record_id not in known_record_ids
        ]

    def restore_identity_effect(
        self,
        principal_id: str,
        effect: IdentityEffect,
        *,
        restored_state: Mapping[str, object],
    ) -> None:
        assert principal_id == PRINCIPAL
        assert restored_state
        self.restored.append((effect.family, effect.record_id))
        self.restoration_order.append((effect.family, effect.record_id))


def _service(entities: _Entities, memories: _Memories) -> IdentityCorrectionService:
    return IdentityCorrectionService(
        cast(EntitiesRepository, entities), cast(RelationshipMemoryRepository, memories)
    )


def _preview(entities: _Entities, memories: _Memories) -> SplitPreviewReport:
    return _service(entities, memories).split_preview(
        SplitPreviewCommand(PRINCIPAL, SOURCE_OPERATION, "undo synthetic merge"),
        at=WHEN + timedelta(minutes=1),
        requested_by="operator",
        actor_class=ActorClass.USER,
        has_operator_authority=True,
    )


def _command(report: SplitPreviewReport, *, principal_id: str = PRINCIPAL) -> SplitCommand:
    return SplitCommand(
        principal_id=principal_id,
        preview_id=report.preview.preview_id,
        preview_digest=report.preview.preview_digest,
        idempotency_key="split-once",
        reason="undo synthetic merge",
    )


def _apply(service: IdentityCorrectionService, command: SplitCommand) -> SplitReceipt:
    return service.split_apply(
        command,
        at=WHEN + timedelta(minutes=2),
        correlation_id="corr_bbbb0002bbbb0002",
        audit_id="audit_bbbb0002bbbb02",
        performed_by="operator",
        actor_class=ActorClass.USER,
        has_operator_authority=True,
    )


def test_split_preview_and_apply_restore_exact_states_in_inverse_order_and_replay() -> None:
    entities, memories = _Entities(), _Memories()
    memories.restoration_order = entities.restoration_order
    service = _service(entities, memories)
    report = _preview(entities, memories)

    assert report.source_operation == entities.source
    assert len(report.projected_effects) == len(entities.effects)
    assert report.projected_effects[0].family is IdentityEffectFamily.RELATIONSHIP_MEMORY
    receipt = _apply(service, _command(report))

    assert not receipt.replayed
    assert receipt.operation.state is IdentityOperationState.COMPLETED
    assert receipt.operation.effect_count == len(receipt.effects) == len(entities.effects)
    assert receipt.operation.effects_digest == effects_digest_for(receipt.effects)
    assert memories.restored == [(IdentityEffectFamily.RELATIONSHIP_MEMORY, "mem_aaaa0001aaaa01")]
    assert entities.restored == [(IdentityEffectFamily.ENTITY, MERGED)]
    assert entities.restoration_order == [
        (IdentityEffectFamily.RELATIONSHIP_MEMORY, "mem_aaaa0001aaaa01"),
        (IdentityEffectFamily.ENTITY, MERGED),
    ]
    for effect, source in zip(receipt.effects, reversed(entities.effects), strict=True):
        assert effect.before_state == source.after_state
        expected_semantics = {
            key: value for key, value in source.before_state.items() if key != "version"
        }
        restored_semantics = {
            key: value for key, value in effect.after_state.items() if key != "version"
        }
        assert restored_semantics == expected_semantics
        if effect.family in {
            IdentityEffectFamily.ENTITY,
            IdentityEffectFamily.RELATIONSHIP_MEMORY,
        }:
            assert effect.after_state["version"] > source.after_state["version"]

    replay = _apply(service, _command(report))
    assert replay.replayed
    assert replay.operation == receipt.operation
    assert replay.effects == receipt.effects
    assert len(memories.restored) == len(entities.restored) == 1


def test_split_requires_operator_and_the_exact_principal_source_and_current_versions() -> None:
    entities, memories = _Entities(), _Memories()
    service = _service(entities, memories)
    with pytest.raises(DeniedError):
        service.split_preview(
            SplitPreviewCommand(PRINCIPAL, SOURCE_OPERATION, "undo"),
            at=WHEN,
            requested_by="reviewer",
            actor_class=ActorClass.USER,
            has_operator_authority=False,
        )
    with pytest.raises(NotFoundError):
        service.split_preview(
            SplitPreviewCommand(OTHER_PRINCIPAL, SOURCE_OPERATION, "undo"),
            at=WHEN,
            requested_by="operator",
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with pytest.raises(NotFoundError):
        service.split_preview(
            SplitPreviewCommand(PRINCIPAL, "eiop_bbbb0002bbbb02", "undo"),
            at=WHEN,
            requested_by="operator",
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )

    report = _preview(entities, memories)
    with pytest.raises(DeniedError):
        service.split_apply(
            _command(report),
            at=WHEN + timedelta(minutes=2),
            correlation_id="corr_bbbb0002bbbb0002",
            audit_id="audit_bbbb0002bbbb02",
            performed_by="reviewer",
            actor_class=ActorClass.USER,
            has_operator_authority=False,
        )
    with pytest.raises(ConflictError):
        _apply(service, _command(report, principal_id=OTHER_PRINCIPAL))
    with pytest.raises(ConflictError):
        _apply(service, replace(_command(report), preview_digest="f" * 64))
    entities.entities[SURVIVOR] = _entity(SURVIVOR, version=2)
    with pytest.raises(ConflictError):
        _apply(service, _command(report))
    assert entities.operations == [] and entities.restored == [] and memories.restored == []


def test_split_refuses_a_corrupt_source_ledger_and_a_stale_effect_state() -> None:
    entities, memories = _Entities(), _Memories()
    entities.source = replace(entities.source, effect_count=len(entities.effects) + 1)
    with pytest.raises(ConflictError):
        _preview(entities, memories)

    entities = _Entities()
    entities.source = replace(entities.source, effects_digest="f" * 64)
    with pytest.raises(ConflictError):
        _preview(entities, memories)

    entities = _Entities()
    # `ENTITY` and not `RELATIONSHIP_MEMORY`: `dispositions_for(ENTITY)` is
    # empty, so a mismatched `ENTITY` effect still refuses outright exactly as
    # a corrupt ledger does. `RELATIONSHIP_MEMORY` no longer proves this --
    # since the fix this module tests, it admits `LEAVE_UNRESOLVED` and a
    # mismatched effect for it is an ambiguity, not a refusal (see
    # `test_dispositions_for_the_four_writerless_families_is_leave_unresolved_only`
    # and the `RELATIONSHIP_MEMORY`-family test below).
    entities.states_match = False
    with pytest.raises(ConflictError):
        _preview(entities, memories)
    assert entities.preview is None


def test_only_one_concurrent_split_apply_can_consume_the_preview() -> None:
    entities, memories = _Entities(), _Memories()
    service = _service(entities, memories)
    report = _preview(entities, memories)
    entities.consume_wins = False

    with pytest.raises(ConflictError):
        _apply(service, _command(report))
    assert entities.operations == [] and entities.restored == [] and memories.restored == []


# --- RI-P2-BLK-001 / WP-01: what the merge ledger does not prove --------------

NEW_ALIAS: Final = "eals_cccc0003cccc0003cccc0003cccc"
MOVED_ALIAS: Final = "eals_dddd0004dddd0004dddd0004dddd"
FOREIGN_ENTITY: Final = "ent_ffff0006ffff0006"


def _alias(alias_id: str, entity_id: str, *, version: int = 1) -> EntityAlias:
    return EntityAlias(
        alias_id=alias_id,
        entity_id=entity_id,
        alias_type=AliasType.NICKNAME,
        normalized_value="synthetic",
        display_value="Synthetic",
        principal_id=PRINCIPAL,
        state=AliasState.ACTIVE,
        version=version,
    )


def _with_alias_effect() -> _Entities:
    """A source merge that also reparented one alias onto the survivor."""
    entities = _Entities()
    entities.effects = sequence_effects(
        (
            *(
                IdentityEffectDraft(
                    family=effect.family,
                    record_id=effect.record_id,
                    kind=effect.kind,
                    before_state=effect.before_state,
                    after_state=effect.after_state,
                )
                for effect in entities.effects
            ),
            IdentityEffectDraft(
                family=IdentityEffectFamily.ALIAS,
                record_id=MOVED_ALIAS,
                kind=IdentityEffectKind.OWNER_REPARENTED,
                before_state={
                    "entity_id": MERGED,
                    "state": "active",
                    "version": 1,
                    "superseded_by_alias_id": None,
                    "updated_at": None,
                },
                after_state={
                    "entity_id": SURVIVOR,
                    "state": "active",
                    "version": 2,
                    "superseded_by_alias_id": None,
                    "updated_at": None,
                },
            ),
        ),
        identity_operation_id=SOURCE_OPERATION,
        principal_id=PRINCIPAL,
        recorded_at=WHEN,
    )
    entities.source = _source(effects=entities.effects)
    return entities


def _settle(
    report: SplitPreviewReport,
    disposition: AmbiguityDisposition,
    *,
    target_entity_id: str | None = None,
) -> SplitCommand:
    return replace(
        _command(report),
        dispositions=tuple(
            SplitDisposition(
                ambiguity_id=ambiguity.ambiguity_id,
                disposition=disposition,
                target_entity_id=target_entity_id,
            )
            for ambiguity in report.ambiguities
        ),
    )


def test_a_row_created_against_the_survivor_after_the_merge_is_reported_not_ignored() -> None:
    """RI-P2-BLK-001: discovery, the bounded answers, and the refusals before any write."""
    entities, memories = _Entities(), _Memories()
    entities.created_after_merge = {IdentityEffectFamily.ALIAS: (NEW_ALIAS,)}
    entities.bound_aliases = [_alias(NEW_ALIAS, SURVIVOR, version=1)]
    service = _service(entities, memories)
    report = _preview(entities, memories)

    (ambiguity,) = report.ambiguities
    assert ambiguity.record_family is IdentityEffectFamily.ALIAS
    assert ambiguity.record_id == NEW_ALIAS
    assert ambiguity.reason == AmbiguityReason.POST_MERGE_CREATED
    assert ambiguity.allowed_dispositions == (
        AmbiguityDisposition.ASSIGN_TO_ENTITY.value,
        AmbiguityDisposition.LEAVE_UNRESOLVED.value,
    )
    assert ambiguity.allowed_target_entity_ids == (SURVIVOR, MERGED)
    assert set(ambiguity.evidence_summary) == {
        "source_identity_operation_id",
        "bound_entity_id",
        "recorded_effect_count",
    }

    with pytest.raises(InvalidRequestError):
        _apply(service, _command(report))
    with pytest.raises(InvalidRequestError):
        _apply(service, _settle(report, AmbiguityDisposition.PRESERVE_SHARED))
    with pytest.raises(InvalidRequestError):
        _apply(
            service,
            replace(
                _command(report),
                dispositions=(
                    SplitDisposition(
                        "eiam_9999999999999999999999999999999a",
                        AmbiguityDisposition.LEAVE_UNRESOLVED,
                    ),
                ),
            ),
        )
    with pytest.raises(InvalidRequestError):
        _apply(
            service,
            replace(
                _command(report),
                dispositions=(
                    SplitDisposition(ambiguity.ambiguity_id, AmbiguityDisposition.LEAVE_UNRESOLVED),
                    SplitDisposition(ambiguity.ambiguity_id, AmbiguityDisposition.LEAVE_UNRESOLVED),
                ),
            ),
        )
    with pytest.raises(InvalidRequestError):
        _apply(
            service,
            _settle(
                report,
                AmbiguityDisposition.ASSIGN_TO_ENTITY,
                target_entity_id=FOREIGN_ENTITY,
            ),
        )
    assert entities.operations == [] and entities.reparented == []
    assert entities.settlements == ()

    receipt = _apply(
        service,
        _settle(report, AmbiguityDisposition.ASSIGN_TO_ENTITY, target_entity_id=MERGED),
    )
    assert receipt.operation.state is IdentityOperationState.COMPLETED
    assert entities.reparented == [(IdentityEffectFamily.ALIAS, NEW_ALIAS, MERGED, 1)]
    (settlement,) = entities.settlements
    assert settlement.ambiguity_id == ambiguity.ambiguity_id
    assert settlement.disposition == AmbiguityDisposition.ASSIGN_TO_ENTITY.value
    assert settlement.target_entity_id == MERGED
    assert settlement.identity_operation_id == receipt.operation.identity_operation_id


def test_a_row_changed_after_the_merge_is_classified_instead_of_refusing_the_split() -> None:
    """RI-P2-BLK-001: the deterministic half still runs; the changed row is settled."""
    entities, memories = _with_alias_effect(), _Memories()
    entities.mismatched = {MOVED_ALIAS}
    service = _service(entities, memories)
    report = _preview(entities, memories)

    (ambiguity,) = report.ambiguities
    assert ambiguity.record_id == MOVED_ALIAS
    assert ambiguity.reason == AmbiguityReason.POST_MERGE_MODIFIED
    assert set(ambiguity.evidence_summary) == {
        "source_identity_operation_id",
        "source_effect_id",
        "source_effect_sequence",
        "recorded_after_sha256",
    }
    # The alias is the one record with no projected effect. Everything the
    # ledger still proves is restored without the operator choosing anything.
    assert {draft.record_id for draft in report.projected_effects} == {
        MERGED,
        "mem_aaaa0001aaaa01",
    }

    receipt = _apply(service, _settle(report, AmbiguityDisposition.LEAVE_UNRESOLVED))
    assert len(receipt.effects) == len(entities.effects) - 1
    assert entities.reparented == []
    (settlement,) = entities.settlements
    assert settlement.disposition == AmbiguityDisposition.LEAVE_UNRESOLVED.value
    assert settlement.target_entity_id is None
    assert entities.restored == [(IdentityEffectFamily.ENTITY, MERGED)]


def test_an_assignment_this_transaction_cannot_perform_is_refused_before_any_write() -> None:
    """A record that no longer binds to the survivor cannot be moved off it."""
    entities, memories = _Entities(), _Memories()
    entities.created_after_merge = {IdentityEffectFamily.ALIAS: (NEW_ALIAS,)}
    service = _service(entities, memories)
    report = _preview(entities, memories)

    with pytest.raises(ConflictError):
        _apply(
            service,
            _settle(report, AmbiguityDisposition.ASSIGN_TO_ENTITY, target_entity_id=MERGED),
        )
    assert entities.operations == [] and entities.reparented == []
    assert entities.settlements == () and entities.restored == []


def test_preserve_shared_is_admitted_for_evidence_and_for_nothing_else() -> None:
    """RI v0.2 section 15.4 line 1186 is about evidence, and an observation is evidence."""
    shared = {
        family
        for family in IdentityEffectFamily
        if AmbiguityDisposition.PRESERVE_SHARED in dispositions_for(family)
    }
    assert shared == {IdentityEffectFamily.OBSERVATION}
    assert dispositions_for(IdentityEffectFamily.ENTITY) == ()
    assert dispositions_for(IdentityEffectFamily.REVIEW_CASE) == ()
    assert dispositions_for(IdentityEffectFamily.DERIVED_CONTEXT) == ()


def test_dispositions_for_the_four_writerless_families_is_leave_unresolved_only() -> None:
    """`PROPOSAL` and the three memory families admit exactly `LEAVE_UNRESOLVED`.

    None of the four has an operator-directed rebinding writer this revision
    can call: `entity_proposals` carries no entity column for `PROPOSAL`, and
    `RelationshipMemoryRepository` / `RelationshipMemoryProposalRepository`
    publish no update-or-rebind method at all for the other three. So
    `ASSIGN_TO_ENTITY` -- which this mapping wrongly offered before this fix --
    is absent, and `LEAVE_UNRESOLVED` is the one answer left, because it needs
    no writer: it is a settlement row, not a mutation of the record.
    """
    writerless = (
        IdentityEffectFamily.PROPOSAL,
        IdentityEffectFamily.RELATIONSHIP_MEMORY,
        IdentityEffectFamily.MEMORY_PROPOSAL,
        IdentityEffectFamily.MEMORY_CONTEXT_LINK,
    )
    for family in writerless:
        assert dispositions_for(family) == (AmbiguityDisposition.LEAVE_UNRESOLVED,)


def test_a_relationship_memory_changed_after_the_merge_is_an_ambiguity_not_a_refusal() -> None:
    """The gap this fix closes, proved at the unit level with the existing `_Memories` fake.

    Before this fix, a `RELATIONSHIP_MEMORY` effect whose `after_state` no
    longer matched (`_Memories.states_match = False`, already how this suite's
    fake represents a memory-family post-merge modification -- no new fixture
    needed) hit `effect.family not in _ATTRIBUTABLE_FAMILIES` and refused the
    whole split with `PREVIEW_STALE`, exactly `RI-P2-BLK-001` for a family
    nobody had closed it for yet. It is now an ambiguity, narrowed to the one
    disposition this family can honestly offer.
    """
    entities, memories = _Entities(), _Memories()
    memories.states_match = False
    service = _service(entities, memories)
    report = _preview(entities, memories)

    (ambiguity,) = report.ambiguities
    assert ambiguity.record_family is IdentityEffectFamily.RELATIONSHIP_MEMORY
    assert ambiguity.record_id == "mem_aaaa0001aaaa01"
    assert ambiguity.reason == AmbiguityReason.POST_MERGE_MODIFIED
    assert ambiguity.allowed_dispositions == (AmbiguityDisposition.LEAVE_UNRESOLVED.value,)
    # The deterministic half is untouched: the `ENTITY` effect the ledger still
    # proves is projected and restored without becoming a question.
    assert {draft.record_id for draft in report.projected_effects} == {MERGED}

    # Fail-closed: no disposition for it still refuses.
    with pytest.raises(InvalidRequestError):
        _apply(service, _command(report))
    # The narrowing is enforced: `ASSIGN_TO_ENTITY` is rejected even with an
    # admissible target, because `_validated_dispositions` checks the chosen
    # disposition against this ambiguity's own `allowed_dispositions`.
    with pytest.raises(InvalidRequestError):
        _apply(
            service,
            _settle(report, AmbiguityDisposition.ASSIGN_TO_ENTITY, target_entity_id=MERGED),
        )
    assert entities.operations == [] and entities.settlements == ()

    receipt = _apply(service, _settle(report, AmbiguityDisposition.LEAVE_UNRESOLVED))
    assert receipt.operation.state is IdentityOperationState.COMPLETED
    assert entities.reparented == []
    (settlement,) = entities.settlements
    assert settlement.record_family == IdentityEffectFamily.RELATIONSHIP_MEMORY
    assert settlement.disposition == AmbiguityDisposition.LEAVE_UNRESOLVED.value
    assert settlement.target_entity_id is None
    assert entities.restored == [(IdentityEffectFamily.ENTITY, MERGED)]
