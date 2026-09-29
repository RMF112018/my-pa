"""WP-RE-02: Task mutations stage exactly the Record Events they should (FAST half).

Driven through `TaskManagementService` over the conftest fake unit of work,
whose `FakeRecordEventStager` publishes to `World.record_events` only when the
block ends normally.

* **RE-AC-018** -- a create stages one `created` event at version 1, naming the
  fields the create materialized, with the history receipt as `source_receipt_id`.
* **RE-AC-019** -- an APPLIED update stages one `updated` event whose
  `changed_fields` is the typed comparison of the patchable fields, including
  the implicit `role` clear when `commitment_id` is cleared.
* **RE-AC-020** -- an APPLIED transition stages one `state_changed` event over
  the static set `{lifecycle_state}`, plus the closure fields when it closes.
* **RE-AC-021/022/023** -- a replay, a no-op and a stale-version rejection stage
  nothing.
* **RE-AC-024 (builder half)** -- `task_record_event` is the builder
  `tasks.bulk_confirm` shares; its database half is
  `tests/database/test_record_event_bulk_confirm_concurrency.py`.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Final

import pytest

from my_pa.application.tasks import (
    TaskManagementService,
    TaskVersionConflictError,
    task_record_event,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.record_events import (
    RecordEventActorClass,
    RecordEventDraft,
    RecordEventFamily,
    RecordEventKind,
)
from my_pa.domain.situation.continuity import ContinuityAcceptanceKind, ContinuityEvidenceState
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.history import TaskMutationAction, TaskMutationActor
from my_pa.domain.task.lifecycle import TaskLifecycleState, TaskOriginKind
from my_pa.domain.task.role import TaskRole
from my_pa.domain.task.task import Task
from tests.conftest import FakeTaskManagementUnitOfWork, World

PRINCIPAL: Final = "prn_taskemit0001"
WHEN: Final = datetime(2026, 9, 29, 12, tzinfo=UTC)
CORRELATION: Final = "corr_taskemit0001"


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def service(world: World) -> TaskManagementService:
    return TaskManagementService(
        unit_of_work=lambda: FakeTaskManagementUnitOfWork(world), clock=lambda: WHEN
    )


def _create(service: TaskManagementService, **extra: object) -> Task:
    return service.create_task(
        principal_id=PRINCIPAL,
        title="Synthetic task",
        origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        actor=TaskMutationActor.PRINCIPAL,
        **extra,  # type: ignore[arg-type]
    ).task


def _only(world: World) -> RecordEventDraft:
    assert len(world.record_events) == 1, world.record_events
    return world.record_events[0]


# ---- RE-AC-018 --------------------------------------------------------------


def test_a_create_stages_one_created_event(world: World, service: TaskManagementService) -> None:
    receipt = service.create_task(
        principal_id=PRINCIPAL,
        title="Synthetic task",
        origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        actor=TaskMutationActor.ASSISTANT,
        source_capability="tasks.create",
        correlation_id=CORRELATION,
    )
    event = _only(world)
    assert event.record_family is RecordEventFamily.TASK
    assert event.record_id == receipt.task.task_id
    assert event.event_kind is RecordEventKind.CREATED
    assert event.record_version == 1
    assert event.changed_fields == (
        "acceptance_kind",
        "evidence_state",
        "lifecycle_state",
        "opened_at",
        "origin_kind",
        "title",
    )
    assert event.source_capability == "tasks.create"
    assert event.source_receipt_id == receipt.history.history_id
    assert event.actor_class is RecordEventActorClass.ASSISTANT
    assert event.classification is Classification.PRIVATE_LOCAL
    assert event.correlation_id == CORRELATION
    assert event.principal_id == PRINCIPAL
    assert event.causation_event_id is None


def test_a_create_names_its_optional_fields_only_when_it_holds_them(
    world: World, service: TaskManagementService
) -> None:
    _create(service, description="Words", commitment_id="cmt_taskemit0001", role=TaskRole.FOLLOW_UP)
    assert {"commitment_id", "description", "role"} <= set(_only(world).changed_fields)
    assert "priority" not in _only(world).changed_fields


def test_a_standalone_create_defaults_to_the_public_capability(
    world: World, service: TaskManagementService
) -> None:
    _create(service)
    assert _only(world).source_capability == "tasks.create"


# ---- RE-AC-019 --------------------------------------------------------------


def test_an_applied_update_names_exactly_the_fields_it_changed(
    world: World, service: TaskManagementService
) -> None:
    task = _create(service)
    world.record_events.clear()
    receipt = service.update_task(
        principal_id=PRINCIPAL,
        task_id=task.task_id,
        expected_version=1,
        actor=TaskMutationActor.PRINCIPAL,
        values={"title": "Renamed", "description": "New"},
        source_capability="tasks.update",
    )
    event = _only(world)
    assert event.event_kind is RecordEventKind.UPDATED
    assert event.changed_fields == ("description", "title")
    assert event.record_version == 2
    assert event.source_receipt_id == receipt.history.history_id
    assert event.source_capability == "tasks.update"


def test_clearing_the_commitment_names_the_implicit_role_clear(
    world: World, service: TaskManagementService
) -> None:
    task = _create(service, commitment_id="cmt_taskemit0001", role=TaskRole.FOLLOW_UP)
    world.record_events.clear()
    service.update_task(
        principal_id=PRINCIPAL,
        task_id=task.task_id,
        expected_version=1,
        actor=TaskMutationActor.PRINCIPAL,
        values={},
        clear_fields=frozenset({"commitment_id"}),
    )
    assert _only(world).changed_fields == ("commitment_id", "role")


def test_a_single_field_method_defaults_to_tasks_update(
    world: World, service: TaskManagementService
) -> None:
    task = _create(service)
    world.record_events.clear()
    service.update_title(
        principal_id=PRINCIPAL,
        task_id=task.task_id,
        title="Retitled",
        expected_version=1,
        actor=TaskMutationActor.PRINCIPAL,
    )
    event = _only(world)
    assert event.changed_fields == ("title",)
    assert event.source_capability == "tasks.update"


# ---- RE-AC-020 --------------------------------------------------------------


def test_a_non_closing_transition_is_state_changed_over_the_lifecycle_state(
    world: World, service: TaskManagementService
) -> None:
    task = _create(service)
    world.record_events.clear()
    service.transition_lifecycle(
        principal_id=PRINCIPAL,
        task_id=task.task_id,
        to_state=TaskLifecycleState.IN_PROGRESS,
        expected_version=1,
        actor=TaskMutationActor.PRINCIPAL,
    )
    event = _only(world)
    assert event.event_kind is RecordEventKind.STATE_CHANGED
    assert event.changed_fields == ("lifecycle_state",)
    assert event.source_capability == "tasks.transition"


def test_a_closing_transition_names_the_closure_fields(
    world: World, service: TaskManagementService
) -> None:
    task = _create(service)
    world.record_events.clear()
    service.transition_lifecycle(
        principal_id=PRINCIPAL,
        task_id=task.task_id,
        to_state=TaskLifecycleState.COMPLETED,
        expected_version=1,
        actor=TaskMutationActor.PRINCIPAL,
    )
    event = _only(world)
    assert event.event_kind is RecordEventKind.STATE_CHANGED
    assert event.changed_fields == ("closed_at", "closure_evidence_ref", "lifecycle_state")
    assert event.record_version == 2


# ---- RE-AC-021/022/023 ------------------------------------------------------


def test_a_replay_stages_nothing(world: World, service: TaskManagementService) -> None:
    _create(service, idempotency_key="task-emit-replay-0001")
    world.record_events.clear()
    replay = service.create_task(
        principal_id=PRINCIPAL,
        title="Synthetic task",
        origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        actor=TaskMutationActor.PRINCIPAL,
        idempotency_key="task-emit-replay-0001",
    )
    assert replay.replayed
    assert world.record_events == []


def test_a_no_op_stages_nothing(world: World, service: TaskManagementService) -> None:
    task = _create(service)
    world.record_events.clear()
    receipt = service.update_title(
        principal_id=PRINCIPAL,
        task_id=task.task_id,
        title=task.title,
        expected_version=1,
        actor=TaskMutationActor.PRINCIPAL,
    )
    assert receipt.history.outcome.value == "no_op"
    assert world.record_events == []


def test_a_stale_version_rejection_stages_nothing(
    world: World, service: TaskManagementService
) -> None:
    task = _create(service)
    world.record_events.clear()
    with pytest.raises(TaskVersionConflictError) as conflict:
        service.update_title(
            principal_id=PRINCIPAL,
            task_id=task.task_id,
            title="Too late",
            expected_version=7,
            actor=TaskMutationActor.PRINCIPAL,
        )
    assert conflict.value.receipt.history.outcome.value == "rejected"
    assert world.record_events == []


# ---- the shared builder (bulk_confirm's half of RE-AC-024) -------------------


def _task(**overrides: object) -> Task:
    base = Task(
        task_id=issue_identifier(IdKind.TASK),
        principal_id=PRINCIPAL,
        title="Synthetic task",
        lifecycle_state=TaskLifecycleState.OPEN,
        evidence_state=ContinuityEvidenceState.ACCEPTED,
        origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        opened_at=WHEN,
        created_at=WHEN,
        updated_at=WHEN,
        acceptance_kind=ContinuityAcceptanceKind.DIRECT_PRINCIPAL,
    )
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


def test_the_builder_carries_the_bulk_capability_and_receipt() -> None:
    before = _task()
    after = dataclasses.replace(before, title="Bulk", version=2)
    event = task_record_event(
        principal_id=PRINCIPAL,
        action=TaskMutationAction.UPDATE,
        before=before,
        after=after,
        actor=TaskMutationActor.PRINCIPAL,
        history_id="thst_taskemit0001",
        occurred_at=WHEN,
        source_capability="tasks.bulk_confirm",
    )
    assert event.changed_fields == ("title",)
    assert event.source_capability == "tasks.bulk_confirm"
    assert event.source_receipt_id == "thst_taskemit0001"
    assert event.record_version == 2


# ---- G1-TX-006: a committed refusal commits no Record Event ------------------


def test_a_committed_refusal_that_staged_an_event_is_rolled_back(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RE-AC-023's service-side guard, reached directly.

    Every REJECTED branch stages nothing, so the guard in
    `ApplicationService.invoke` never fires on a correct build. Here a handler
    that stages and then asks for its refusal to be committed stands in for a
    defective one: the guard must refuse the commit, so neither the refusal nor
    the event survives.
    """
    from my_pa.application import service as service_module
    from my_pa.application.commands import UpdateTask
    from my_pa.application.errors import ConflictError, SafeDetail
    from my_pa.contracts.v1.errors import ErrorCode
    from my_pa.domain.identity.operation import Capability, permitted_purposes
    from tests.conftest import FakeProviders, build_service, metadata_for, operator

    principal = operator()

    def defective(
        self: object, unit_of_work: object, authorization: object, command: object
    ) -> object:
        del self, authorization, command
        unit_of_work.record_events.stage(  # type: ignore[attr-defined]
            RecordEventDraft.issue(
                principal_id=principal.principal_id,
                record_family=RecordEventFamily.TASK,
                record_id=issue_identifier(IdKind.TASK),
                event_kind=RecordEventKind.UPDATED,
                record_version=2,
                changed_fields=("title",),
                source_capability="tasks.update",
                actor_class=RecordEventActorClass.PRINCIPAL,
                classification=Classification.PRIVATE_LOCAL,
                occurred_at=WHEN,
            )
        )
        raise service_module._CommitRejectedConflictError(ConflictError(SafeDetail.TASK_ID))

    monkeypatch.setattr(
        service_module,
        "_HANDLERS",
        MappingProxyType({**service_module._HANDLERS, Capability.TASKS_UPDATE: defective}),
    )
    service = build_service(world, FakeProviders())
    command = UpdateTask(
        task_id=issue_identifier(IdKind.TASK),
        expected_version=1,
        idempotency_key="task-emit-guard-0001",
        title="Anything",
    )
    purpose = next(iter(permitted_purposes(command.capability)))
    rollbacks = world.rollbacks
    envelope = service.invoke(
        metadata_for(command.capability, purpose, principal), command, principal=principal
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.INTERNAL_ERROR
    assert world.record_events == []
    assert world.rollbacks == rollbacks + 1
