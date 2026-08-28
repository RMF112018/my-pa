"""Direct behavioral proof for governed split preview and apply.

The transport suites prove exposure.  These tests call the service itself so
the inverse order, source-ledger binding, version check, replay, and one-winner
preview consumption remain load-bearing without a database runtime.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Final, cast

import pytest

from my_pa.application.errors import ConflictError, DeniedError, NotFoundError
from my_pa.application.identity_correction import (
    IdentityCorrectionService,
    SplitCommand,
    SplitPreviewCommand,
    SplitPreviewReport,
    SplitReceipt,
)
from my_pa.contracts.ports import EntitiesRepository, RelationshipMemoryRepository
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import ActorClass
from my_pa.domain.relationship.identity_correction import (
    IdentityEffect,
    IdentityEffectDraft,
    IdentityEffectFamily,
    IdentityEffectKind,
    IdentityOperation,
    IdentityOperationState,
    IdentityOperationType,
    IdentityPreview,
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

    def observation(self, principal_id: str, reference: str) -> None:
        del principal_id, reference
        return None

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
            and effect.family is not IdentityEffectFamily.RELATIONSHIP_MEMORY
        )

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

    def identity_effect_matches_after_state(
        self, principal_id: str, effect: IdentityEffect
    ) -> bool:
        return principal_id == PRINCIPAL and self.states_match

    def restore_identity_effect(self, principal_id: str, effect: IdentityEffect) -> None:
        assert principal_id == PRINCIPAL
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
    memories.states_match = False
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
