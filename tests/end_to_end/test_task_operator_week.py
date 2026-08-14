"""Plan §47 operator-week harness through ApplicationService.invoke."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from tests.conftest import World, metadata_for, operator

from my_pa.application.commands import (
    ApplyTaskBulk,
    CreateCommitment,
    CreateTask,
    ListTasks,
    PreviewTaskBulk,
    ReadTaskHistory,
    TasksAttention,
    TasksWaitingOn,
    TransitionTask,
    UpdateTask,
)
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.tasks.models import (
    CommitmentDirection,
    RecurrenceFrequency,
    TaskRole,
    TaskState,
)

pytestmark = pytest.mark.e2e

MONDAY = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
TUESDAY = date(2026, 8, 11)
TUESDAY_NOON = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
WEDNESDAY_AFTERNOON = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)


def _invoke(
    world: World, capability: Capability, purpose: Purpose, command: object
) -> ResponseEnvelope:
    principal = operator(principal_id="prn_operator0001")
    from tests.conftest import DEFAULT_LIMITS, FakeUnitOfWork

    from my_pa.application.service import ApplicationService

    service = ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(world),
        limits=DEFAULT_LIMITS,
        clock=lambda: TUESDAY_NOON,
    )
    metadata = metadata_for(capability, purpose, principal)
    return service.invoke(metadata, command, principal=principal)


def test_operator_week_through_invoke(world: World) -> None:
    turner = _invoke(
        world,
        Capability.TASKS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateTask(
            title="call Mike about Turner permit tomorrow",
            idempotency_key="week-turner-0001",
            priority="high",
            due_date=TUESDAY,
            due_timezone="America/New_York",
        ),
    )
    assert turner.result["task"]["priority"] == "p2"
    assert turner.result["task"]["due_date"] == "2026-08-11"
    turner_id = turner.result["task"]["task_id"]

    friday = _invoke(
        world,
        Capability.TASKS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateTask(
            title="Friday executive report",
            idempotency_key="week-friday-0001",
            recurrence_frequency=RecurrenceFrequency.WEEKLY,
            recurrence_weekdays=(4,),
            due_date=date(2026, 8, 14),
            due_timezone="America/New_York",
        ),
    )
    assert friday.result["task"]["recurrence_id"]
    friday_id = friday.result["task"]["task_id"]

    proposed = _invoke(
        world,
        Capability.TASKS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateTask(
            title="send the meeting action",
            idempotency_key="week-meeting-0001",
            origin_evidence_ref="prop_meeting00000001",
        ),
    )
    assert proposed.result["task"]["origin_evidence_ref"] == "prop_meeting00000001"

    attention = _invoke(world, Capability.TASKS_ATTENTION, Purpose.TASK_REVIEW, TasksAttention())
    assert any(item["task_id"] == turner_id for item in attention.result["items"])

    updated = _invoke(
        world,
        Capability.TASKS_UPDATE,
        Purpose.TASK_AUTHORING,
        UpdateTask(
            referenced_task_id=turner_id,
            expected_version=1,
            idempotency_key="week-turner-upd-0001",
            scheduled_at=WEDNESDAY_AFTERNOON,
        ),
    )
    assert updated.result["task"]["scheduled_at"]
    assert updated.result["task"]["scheduled_date"] is None

    person = "per_sarah00000001"
    _invoke(
        world,
        Capability.COMMITMENTS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateCommitment(
            counterparty_person_id=person,
            direction=CommitmentDirection.OWED_TO_PRINCIPAL,
            summary="Sarah owes the permit log",
            idempotency_key="week-cmt-0001",
        ),
    )
    _invoke(
        world,
        Capability.TASKS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateTask(
            title="Follow up with Sarah on Friday",
            idempotency_key="week-follow-0001",
            task_role=TaskRole.FOLLOW_UP,
            person_id=person,
            due_date=date(2026, 8, 14),
        ),
    )
    waiting = _invoke(world, Capability.TASKS_WAITING_ON, Purpose.TASK_REVIEW, TasksWaitingOn())
    assert waiting.result["commitments"]
    assert waiting.result["follow_ups"]

    warranty = _invoke(
        world,
        Capability.TASKS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateTask(title="warranty-log", idempotency_key="week-warranty-0001"),
    )
    done = _invoke(
        world,
        Capability.TASKS_TRANSITION,
        Purpose.TASK_AUTHORING,
        TransitionTask(
            task_id=warranty.result["task"]["task_id"],
            expected_version=1,
            idempotency_key="week-warranty-done",
            target_state=TaskState.COMPLETED,
        ),
    )
    assert done.result["task"]["state"] == "completed"
    assert all(item.state.value == "open" for item in world.commitments.values())

    reopened = _invoke(
        world,
        Capability.TASKS_TRANSITION,
        Purpose.TASK_AUTHORING,
        TransitionTask(
            task_id=warranty.result["task"]["task_id"],
            expected_version=2,
            idempotency_key="week-warranty-undo",
            target_state=TaskState.OPEN,
        ),
    )
    assert reopened.result["task"]["state"] == "open"
    history = _invoke(
        world,
        Capability.TASKS_HISTORY,
        Purpose.TASK_REVIEW,
        ReadTaskHistory(task_id=warranty.result["task"]["task_id"]),
    )
    assert len(history.result["revisions"]) == 3

    ranked = _invoke(world, Capability.TASKS_ATTENTION, Purpose.TASK_REVIEW, TasksAttention())
    assert ranked.result["items"]
    turner_item = next(item for item in ranked.result["items"] if item["task_id"] == turner_id)
    assert turner_item["priority"] == "p2"

    preview = _invoke(
        world,
        Capability.TASKS_PREVIEW,
        Purpose.TASK_AUTHORING,
        PreviewTaskBulk(
            operation="reschedule",
            task_ids=(turner_id,),
            expected_versions=(2,),
            scheduled_at=datetime(2026, 8, 13, 16, 0, tzinfo=UTC),
        ),
    )
    first_apply = _invoke(
        world,
        Capability.TASKS_BULK,
        Purpose.TASK_AUTHORING,
        ApplyTaskBulk(
            preview_token=preview.result["preview_token"],
            idempotency_key="week-bulk-0001",
        ),
    )
    assert first_apply.result["status"] == "ok"
    second_apply = _invoke(
        world,
        Capability.TASKS_BULK,
        Purpose.TASK_AUTHORING,
        ApplyTaskBulk(
            preview_token=preview.result["preview_token"],
            idempotency_key="week-bulk-0002",
        ),
    )
    assert second_apply.result["status"] == "drift"

    complete_friday = TransitionTask(
        task_id=friday_id,
        expected_version=1,
        idempotency_key="week-friday-done",
        target_state=TaskState.COMPLETED,
    )
    _invoke(world, Capability.TASKS_TRANSITION, Purpose.TASK_AUTHORING, complete_friday)
    _invoke(world, Capability.TASKS_TRANSITION, Purpose.TASK_AUTHORING, complete_friday)
    series = [
        task
        for task in world.task_rows.values()
        if task.recurrence_id == friday.result["task"]["recurrence_id"]
    ]
    assert len(series) == 2

    listed = _invoke(world, Capability.TASKS_LIST, Purpose.TASK_REVIEW, ListTasks())
    assert listed.result["tasks"]
