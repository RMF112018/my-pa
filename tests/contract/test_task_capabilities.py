"""Task capabilities execute through ApplicationService.invoke."""

from __future__ import annotations

from datetime import UTC, date, datetime

from tests.conftest import World, build_service, metadata_for, operator

from my_pa.application.commands import (
    ApplyTaskBulk,
    CreateCommitment,
    CreateTask,
    ListTasks,
    PreviewTaskBulk,
    ReadTask,
    ReadTaskHistory,
    SearchTasks,
    TasksAttention,
    TasksWaitingOn,
    TransitionTask,
    UpdateTask,
)
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.tasks.models import CommitmentDirection, RecurrenceFrequency, TaskRole, TaskState

WHEN = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)


def _run(
    world: World,
    capability: Capability,
    purpose: Purpose,
    command: object,
    *,
    principal: Principal | None = None,
) -> ResponseEnvelope:
    actor = principal or operator(principal_id="prn_operator0001")
    service = build_service(world, world.providers)
    metadata = metadata_for(capability, purpose, actor)
    return service.invoke(metadata, command, principal=actor)


def test_direct_create_is_accepted_p3_by_default(world: World) -> None:
    envelope = _run(
        world,
        Capability.TASKS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateTask(title="file the warranty log", idempotency_key="task-create-0001"),
    )
    assert envelope.error is None
    assert envelope.result["status"] == "ok"
    assert envelope.result["task"]["priority"] == "p3"
    assert envelope.result["task"]["acceptance_kind"] == "direct_principal"
    assert envelope.result["task"]["accepted_by_review_decision_id"] is None


def test_high_alias_is_p2_and_replay_is_idempotent(world: World) -> None:
    command = CreateTask(
        title="call Mike about Turner permit",
        idempotency_key="task-create-0002",
        priority="high",
        due_date=date(2026, 8, 11),
        due_timezone="America/New_York",
    )
    first = _run(world, Capability.TASKS_CREATE, Purpose.TASK_AUTHORING, command)
    second = _run(world, Capability.TASKS_CREATE, Purpose.TASK_AUTHORING, command)
    assert first.result["task"]["priority"] == "p2"
    assert second.result["task"]["task_id"] == first.result["task"]["task_id"]
    different = _run(
        world,
        Capability.TASKS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateTask(title="other", idempotency_key="task-create-0002"),
    )
    assert different.error is not None
    assert different.error.code is ErrorCode.CONFLICT


def test_stale_version_is_conflict(world: World) -> None:
    created = _run(
        world,
        Capability.TASKS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateTask(title="versioned", idempotency_key="task-create-0003"),
    )
    task_id = created.result["task"]["task_id"]
    stale = _run(
        world,
        Capability.TASKS_UPDATE,
        Purpose.TASK_AUTHORING,
        UpdateTask(
            task_id=task_id,
            expected_version=99,
            idempotency_key="task-upd-0001",
            title="nope",
        ),
    )
    assert stale.error is not None
    assert stale.error.code is ErrorCode.CONFLICT


def test_referenced_task_id_updates_schedule(world: World) -> None:
    created = _run(
        world,
        Capability.TASKS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateTask(title="that task", idempotency_key="task-create-0004"),
    )
    task_id = created.result["task"]["task_id"]
    when = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)
    updated = _run(
        world,
        Capability.TASKS_UPDATE,
        Purpose.TASK_AUTHORING,
        UpdateTask(
            referenced_task_id=task_id,
            expected_version=1,
            idempotency_key="task-upd-0002",
            scheduled_at=when,
        ),
    )
    assert updated.error is None
    assert updated.result["task"]["scheduled_at"] is not None
    assert updated.result["task"]["scheduled_date"] is None


def test_list_search_history_and_attention(world: World) -> None:
    created = _run(
        world,
        Capability.TASKS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateTask(
            title="call Mike about Turner permit",
            idempotency_key="task-create-0005",
            priority="high",
            due_date=date(2026, 8, 2),
        ),
    )
    task_id = created.result["task"]["task_id"]
    listed = _run(world, Capability.TASKS_LIST, Purpose.TASK_REVIEW, ListTasks())
    assert any(item["task_id"] == task_id for item in listed.result["tasks"])
    found = _run(world, Capability.TASKS_SEARCH, Purpose.TASK_REVIEW, SearchTasks(query="Turner"))
    assert found.result["tasks"]
    hist = _run(
        world, Capability.TASKS_HISTORY, Purpose.TASK_REVIEW, ReadTaskHistory(task_id=task_id)
    )
    assert hist.result["revisions"]
    ranked = _run(world, Capability.TASKS_ATTENTION, Purpose.TASK_REVIEW, TasksAttention())
    assert ranked.result["items"]
    assert ranked.result["items"][0]["priority"] == "p2"


def test_waiting_on_is_derived(world: World) -> None:
    person = "per_sarah00000001"
    _run(
        world,
        Capability.COMMITMENTS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateCommitment(
            counterparty_person_id=person,
            direction=CommitmentDirection.OWED_TO_PRINCIPAL,
            summary="Sarah owes the permit log",
            idempotency_key="cmt-create-0001",
        ),
    )
    _run(
        world,
        Capability.TASKS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateTask(
            title="Follow up with Sarah",
            idempotency_key="task-create-0006",
            task_role=TaskRole.FOLLOW_UP,
            person_id=person,
            due_date=date(2026, 8, 14),
        ),
    )
    view = _run(world, Capability.TASKS_WAITING_ON, Purpose.TASK_REVIEW, TasksWaitingOn())
    assert view.result["commitments"]
    assert view.result["follow_ups"]


def test_complete_does_not_close_commitment_and_reopen_appends(world: World) -> None:
    created = _run(
        world,
        Capability.TASKS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateTask(title="warranty log", idempotency_key="task-create-0007"),
    )
    task_id = created.result["task"]["task_id"]
    _run(
        world,
        Capability.COMMITMENTS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateCommitment(
            counterparty_person_id="per_vendor0000001",
            direction=CommitmentDirection.OWED_TO_PRINCIPAL,
            summary="vendor owes the log",
            idempotency_key="cmt-create-0002",
        ),
    )
    done = _run(
        world,
        Capability.TASKS_TRANSITION,
        Purpose.TASK_AUTHORING,
        TransitionTask(
            task_id=task_id,
            expected_version=1,
            idempotency_key="task-trn-0001",
            target_state=TaskState.COMPLETED,
        ),
    )
    assert done.result["task"]["state"] == "completed"
    commitments = world.commitments
    assert all(item.state.value == "open" for item in commitments.values())
    reopened = _run(
        world,
        Capability.TASKS_TRANSITION,
        Purpose.TASK_AUTHORING,
        TransitionTask(
            task_id=task_id,
            expected_version=2,
            idempotency_key="task-trn-0002",
            target_state=TaskState.OPEN,
        ),
    )
    assert reopened.result["task"]["state"] == "open"
    assert reopened.result["version_after"] == 3


def test_bulk_preview_then_stale_apply_drifts(world: World) -> None:
    created = _run(
        world,
        Capability.TASKS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateTask(title="Turner reschedule", idempotency_key="task-create-0008"),
    )
    task_id = created.result["task"]["task_id"]
    preview = _run(
        world,
        Capability.TASKS_PREVIEW,
        Purpose.TASK_AUTHORING,
        PreviewTaskBulk(
            operation="reschedule",
            task_ids=(task_id,),
            expected_versions=(1,),
            scheduled_at=datetime(2026, 8, 13, 15, 0, tzinfo=UTC),
        ),
    )
    assert preview.result["status"] == "preview_bound"
    token = preview.result["preview_token"]
    _run(
        world,
        Capability.TASKS_UPDATE,
        Purpose.TASK_AUTHORING,
        UpdateTask(
            task_id=task_id,
            expected_version=1,
            idempotency_key="task-upd-0003",
            title="moved",
        ),
    )
    drifted = _run(
        world,
        Capability.TASKS_BULK,
        Purpose.TASK_AUTHORING,
        ApplyTaskBulk(preview_token=token, idempotency_key="task-blk-0001"),
    )
    assert drifted.result["status"] == "drift"


def test_recurring_completion_creates_one_next_occurrence(world: World) -> None:
    created = _run(
        world,
        Capability.TASKS_CREATE,
        Purpose.TASK_AUTHORING,
        CreateTask(
            title="Friday executive report",
            idempotency_key="task-create-0009",
            recurrence_frequency=RecurrenceFrequency.WEEKLY,
            recurrence_weekdays=(4,),
            due_date=date(2026, 8, 14),
            due_timezone="America/New_York",
        ),
    )
    task_id = created.result["task"]["task_id"]
    assert created.result["task"]["recurrence_id"]
    first_complete = TransitionTask(
        task_id=task_id,
        expected_version=1,
        idempotency_key="task-trn-0003",
        target_state=TaskState.COMPLETED,
    )
    _run(world, Capability.TASKS_TRANSITION, Purpose.TASK_AUTHORING, first_complete)
    _run(world, Capability.TASKS_TRANSITION, Purpose.TASK_AUTHORING, first_complete)
    occurrences = [
        task
        for task in world.task_rows.values()
        if task.recurrence_id == created.result["task"]["recurrence_id"]
    ]
    assert len(occurrences) == 2
    assert sum(1 for task in occurrences if not task.is_terminal) == 1


def test_read_missing_task_is_not_found(world: World) -> None:
    envelope = _run(
        world,
        Capability.TASKS_READ,
        Purpose.TASK_REVIEW,
        ReadTask(task_id="tsk_00000000deadbeef"),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.NOT_FOUND
