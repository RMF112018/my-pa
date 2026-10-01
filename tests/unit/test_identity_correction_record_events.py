"""WP-RE-04 Phase 4B (FAST): the merge/split batch rules, without a database.

The fail-closed stops the database cannot reach on a consistent tree are proven
here with stand-in ports:

* **N17** -- a retargeted context link whose owning memory this transaction
  cannot resolve refuses the whole operation;
* **N19** -- a batch with no `entity` event has no identifiable root and is
  refused rather than staged unrooted;
* the root is the lowest-`entity_id` Entity event and never a memory event,
  and every other event names it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from my_pa.application.errors import InternalError
from my_pa.application.identity_correction import (
    IdentityCorrectionService,
    _Batch,
)
from my_pa.contracts.ports import MemoryFeedFacts
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.record_events import RecordEventFamily, RecordEventKind
from my_pa.domain.relationship.governance import ActorClass
from my_pa.domain.relationship.identity_correction import (
    IdentityEffect,
    IdentityEffectFamily,
    IdentityEffectKind,
    IdentityOperation,
    IdentityOperationState,
    IdentityOperationType,
    state_digest,
)
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import FakeRecordEventStager

PRINCIPAL = "prn_idcevents00000001"
WHEN = datetime(2026, 9, 29, 12, tzinfo=UTC)
MEMORY = "mem_idcevents00000001"
LOW = "ent_idcevents00000001"
HIGH = "ent_idcevents00000002"


class _Memories:
    def __init__(self, owner: MemoryFeedFacts | None) -> None:
        self._owner = owner

    def context_link_owner(self, principal_id: str, context_link_id: str) -> Any:  # noqa: ANN401
        return self._owner

    def memory_feed_facts(self, principal_id: str, memory_id: str) -> Any:  # noqa: ANN401
        return self._owner


def _service(owner: MemoryFeedFacts | None, sink: list[Any]) -> IdentityCorrectionService:
    return IdentityCorrectionService(
        object(),  # type: ignore[arg-type]
        _Memories(owner),  # type: ignore[arg-type]
        stager=FakeRecordEventStager(sink),
    )


def _operation() -> IdentityOperation:
    return IdentityOperation(
        identity_operation_id=issue_identifier(IdKind.ENTITY_IDENTITY_OPERATION),
        principal_id=PRINCIPAL,
        operation_type=IdentityOperationType.MERGE,
        survivor_entity_id="ent_idcevents00000009",
        merged_entity_ids=(LOW, HIGH),
        preview_id=issue_identifier(IdKind.ENTITY_IDENTITY_PREVIEW),
        preview_digest="0" * 64,
        idempotency_key="merge-key",
        request_digest="0" * 64,
        reason="synthetic",
        performed_by=PRINCIPAL,
        actor_class=ActorClass.USER,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
        receipt_id=issue_identifier(IdKind.RECEIPT),
        state=IdentityOperationState.COMPLETED,
        started_at=WHEN,
        completed_at=WHEN,
    )


def _link_effect() -> IdentityEffect:
    before = {"target_id": LOW, "origin_subject_entity_id": LOW}
    after = {"target_id": HIGH, "origin_subject_entity_id": LOW}
    return IdentityEffect(
        effect_id=issue_identifier(IdKind.ENTITY_IDENTITY_EFFECT),
        identity_operation_id=issue_identifier(IdKind.ENTITY_IDENTITY_OPERATION),
        principal_id=PRINCIPAL,
        sequence=1,
        family=IdentityEffectFamily.MEMORY_CONTEXT_LINK,
        record_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_CONTEXT_LINK),
        kind=IdentityEffectKind.OWNER_REPARENTED,
        before_state=before,
        after_state=after,
        before_sha256=state_digest(before),
        after_sha256=state_digest(after),
        recorded_at=WHEN,
    )


def test_an_unresolvable_context_link_owner_refuses_the_operation() -> None:
    """STOP N17 is fail-closed: no event is staged for a link with no owner."""
    sink: list[Any] = []
    service = _service(None, sink)
    with pytest.raises(InternalError):
        service._collect_effect(PRINCIPAL, _Batch(), _link_effect(), split=False)


def test_a_batch_without_an_entity_event_has_no_root_and_is_refused() -> None:
    """STOP N19: a memory is never promoted to root."""
    owner = MemoryFeedFacts(
        memory_id=MEMORY, version=3, classification=Classification.PRIVATE_LOCAL
    )
    service = _service(owner, [])
    batch = _Batch()
    batch.touch_memory(MEMORY, ("context_links",), issue_identifier(IdKind.ENTITY_IDENTITY_EFFECT))
    with pytest.raises(InternalError):
        service._stage_batch(PRINCIPAL, _operation(), batch, capability="entities.merge", at=WHEN)


def test_the_root_is_the_lowest_entity_and_everything_else_names_it() -> None:
    owner = MemoryFeedFacts(
        memory_id=MEMORY, version=3, classification=Classification.RESTRICTED_LOCAL
    )
    pending: list[Any] = []
    stager = FakeRecordEventStager(pending)
    service = IdentityCorrectionService(
        object(),  # type: ignore[arg-type]
        _Memories(owner),  # type: ignore[arg-type]
        stager=stager,
    )
    batch = _Batch()
    effect = issue_identifier(IdKind.ENTITY_IDENTITY_EFFECT)
    batch.touch_memory(MEMORY, ("subject_entity_id", "version"), effect)
    batch.touch_memory(MEMORY, ("context_links",), effect)
    batch.add(RecordEventFamily.ENTITY, HIGH, RecordEventKind.STATE_CHANGED, 2, ("status",), effect)
    batch.add(RecordEventFamily.ENTITY, LOW, RecordEventKind.STATE_CHANGED, 2, ("status",), effect)
    service._stage_batch(PRINCIPAL, _operation(), batch, capability="entities.merge", at=WHEN)
    stager.settle(committed=True)
    root, *rest = pending
    assert (root.record_family, root.record_id, root.causation_event_id) == (
        RecordEventFamily.ENTITY,
        LOW,
        None,
    )
    assert [event.record_id for event in rest] == [MEMORY, HIGH]
    assert all(event.causation_event_id == root.event_id for event in rest)
    (memory,) = [e for e in pending if e.record_family is RecordEventFamily.RELATIONSHIP_MEMORY]
    assert memory.changed_fields == ("context_links", "subject_entity_id", "version")
    assert memory.record_version == 3
    assert memory.classification is Classification.RESTRICTED_LOCAL
    assert all(event.source_capability == "entities.merge" for event in pending)
