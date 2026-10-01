"""WP-RE-02: Commitment mutations stage exactly the Record Events they should (FAST half).

Driven through `CommitmentManagementService` over the conftest fake unit of
work (`FakeRecordEventStager` publishes to `World.record_events` on a normal
exit only).

* **RE-AC-025** -- a create stages one `created` event at version 1.
* **RE-AC-026** -- an update stages one `updated` event, only when APPLIED, whose
  `changed_fields` is the typed comparison over `{summary, due_at,
  counterparty_person_id}`; a replay, a no-op and a stale rejection stage none.
* **RE-AC-027** -- a close stages one `state_changed` event over the static set
  `{state, closed_at, closure_evidence_ref}`; closing again is a no-op and
  stages none.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.application.commitments import (
    CommitmentManagementService,
    CommitmentVersionConflictError,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.record_events import (
    RecordEventActorClass,
    RecordEventDraft,
    RecordEventFamily,
    RecordEventKind,
)
from my_pa.domain.situation.continuity import CommitmentDirection
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.commitment import Commitment
from my_pa.domain.task.history import TaskMutationActor
from tests.conftest import FakeCommitmentManagementUnitOfWork, World

PRINCIPAL: Final = "prn_cmtemit00001"
WHEN: Final = datetime(2026, 9, 29, 12, tzinfo=UTC)
ORIGIN: Final = "cap_cmtemit000000001"
CORRELATION: Final = "corr_cmtemit00001"


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def service(world: World) -> CommitmentManagementService:
    return CommitmentManagementService(
        unit_of_work=lambda: FakeCommitmentManagementUnitOfWork(world), clock=lambda: WHEN
    )


def _create(service: CommitmentManagementService, *, key: str | None = None) -> Commitment:
    return service.create_commitment(
        principal_id=PRINCIPAL,
        counterparty_person_id=issue_identifier(IdKind.PERSON),
        direction=CommitmentDirection.OWED_BY_PRINCIPAL,
        summary="Send the synthetic report",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key=key,
    ).commitment


def _only(world: World) -> RecordEventDraft:
    assert len(world.record_events) == 1, world.record_events
    return world.record_events[0]


def test_a_create_stages_one_created_event(
    world: World, service: CommitmentManagementService
) -> None:
    receipt = service.create_commitment(
        principal_id=PRINCIPAL,
        counterparty_person_id=issue_identifier(IdKind.PERSON),
        direction=CommitmentDirection.OWED_BY_PRINCIPAL,
        summary="Send the synthetic report",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.SYSTEM,
        source_capability="commitments.create",
        correlation_id=CORRELATION,
    )
    event = _only(world)
    assert event.record_family is RecordEventFamily.COMMITMENT
    assert event.record_id == receipt.commitment.commitment_id
    assert event.event_kind is RecordEventKind.CREATED
    assert event.record_version == 1
    assert event.changed_fields == (
        "counterparty_person_id",
        "direction",
        "evidence_state",
        "opened_at",
        "origin_evidence_ref",
        "state",
        "summary",
    )
    assert event.source_receipt_id == receipt.history.history_id
    assert event.source_capability == "commitments.create"
    assert event.actor_class is RecordEventActorClass.SYSTEM
    assert event.correlation_id == CORRELATION


def test_an_applied_update_names_exactly_the_fields_it_changed(
    world: World, service: CommitmentManagementService
) -> None:
    commitment = _create(service)
    world.record_events.clear()
    service.update_commitment(
        principal_id=PRINCIPAL,
        commitment_id=commitment.commitment_id,
        expected_version=1,
        actor=TaskMutationActor.PRINCIPAL,
        values={"summary": "Send the revised report", "due_at": WHEN + timedelta(days=2)},
    )
    event = _only(world)
    assert event.event_kind is RecordEventKind.UPDATED
    assert event.changed_fields == ("due_at", "summary")
    assert event.record_version == 2
    assert event.source_capability == "commitments.update"


def test_an_update_to_the_same_values_is_a_no_op_and_stages_nothing(
    world: World, service: CommitmentManagementService
) -> None:
    commitment = _create(service)
    world.record_events.clear()
    receipt = service.update_commitment(
        principal_id=PRINCIPAL,
        commitment_id=commitment.commitment_id,
        expected_version=1,
        actor=TaskMutationActor.PRINCIPAL,
        values={"summary": commitment.summary},
    )
    assert receipt.history.outcome.value == "no_op"
    assert world.record_events == []


def test_a_stale_update_stages_nothing(world: World, service: CommitmentManagementService) -> None:
    commitment = _create(service)
    world.record_events.clear()
    with pytest.raises(CommitmentVersionConflictError):
        service.update_commitment(
            principal_id=PRINCIPAL,
            commitment_id=commitment.commitment_id,
            expected_version=9,
            actor=TaskMutationActor.PRINCIPAL,
            values={"summary": "Too late"},
        )
    assert world.record_events == []


def test_a_replayed_create_stages_nothing(
    world: World, service: CommitmentManagementService
) -> None:
    service.create_commitment(
        principal_id=PRINCIPAL,
        counterparty_person_id="per_cmtemit00000001",
        direction=CommitmentDirection.OWED_BY_PRINCIPAL,
        summary="Send the synthetic report",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key="cmt-emit-replay-0001",
    )
    world.record_events.clear()
    replay = service.create_commitment(
        principal_id=PRINCIPAL,
        counterparty_person_id="per_cmtemit00000001",
        direction=CommitmentDirection.OWED_BY_PRINCIPAL,
        summary="Send the synthetic report",
        origin_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key="cmt-emit-replay-0001",
    )
    assert replay.replayed
    assert world.record_events == []


def test_a_close_is_state_changed_over_the_static_set(
    world: World, service: CommitmentManagementService
) -> None:
    commitment = _create(service)
    world.record_events.clear()
    service.close_commitment(
        principal_id=PRINCIPAL,
        commitment_id=commitment.commitment_id,
        expected_version=1,
        closure_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    event = _only(world)
    assert event.event_kind is RecordEventKind.STATE_CHANGED
    assert event.changed_fields == ("closed_at", "closure_evidence_ref", "state")
    assert event.source_capability == "commitments.close"
    world.record_events.clear()
    again = service.close_commitment(
        principal_id=PRINCIPAL,
        commitment_id=commitment.commitment_id,
        expected_version=2,
        closure_evidence_ref=ORIGIN,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert again.history.outcome.value == "no_op"
    assert world.record_events == []
