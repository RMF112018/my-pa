"""Reassign and filter Task Project membership (WP-MCP-PROJ-05)."""

from __future__ import annotations

import pytest

from my_pa.application.commands import (
    Command,
    CreateProject,
    CreateTask,
    ListTasks,
    ReadTask,
    RecordTask,
    UpdateTask,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.situation.continuity import ContinuityAcceptanceKind, ContinuityEvidenceState
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.lifecycle import TaskLifecycleState, TaskOriginKind
from my_pa.domain.task.task import Task as TaskV2
from tests.conftest import WHEN, Scene, build_service, metadata_for, operator

TASK_ID = issue_identifier(IdKind.TASK)


def _invoke(
    service: ApplicationService,
    principal: Principal,
    command: Command,
) -> ResponseEnvelope:
    capability = command.capability
    return service.invoke(
        metadata_for(capability, sorted(permitted_purposes(capability))[0], principal),
        command,
        principal=principal,
    )


def _mirror_continuity_task(scene: Scene, principal: Principal, payload: dict[str, object]) -> None:
    task_id = str(payload["task_id"])
    if any(row.task_id == task_id for row in scene.world.tasks_v2):
        return
    scene.world.tasks_v2.append(
        TaskV2(
            task_id=task_id,
            principal_id=principal.principal_id,
            title=str(payload["title"]),
            lifecycle_state=TaskLifecycleState.OPEN,
            evidence_state=ContinuityEvidenceState.ACCEPTED,
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
            opened_at=WHEN,
            created_at=WHEN,
            updated_at=WHEN,
            project_id=None if payload["project_id"] is None else str(payload["project_id"]),
            acceptance_kind=ContinuityAcceptanceKind.DIRECT_PRINCIPAL,
        )
    )


def _project(service: ApplicationService, principal: Principal, *, name: str, key: str) -> str:
    created = _invoke(service, principal, CreateProject(name=name, idempotency_key=key))
    assert created.error is None and created.result is not None
    return str(created.result["project_id"])


def _attached_task(
    scene: Scene,
    service: ApplicationService,
    principal: Principal,
    *,
    title: str,
    key: str,
    project_id: str | None,
) -> dict[str, object]:
    created = _invoke(
        service,
        principal,
        RecordTask(title=title, idempotency_key=key, project_id=project_id),
    )
    assert created.error is None and created.result is not None
    _mirror_continuity_task(scene, principal, created.result)
    return created.result


def _rich_task(
    service: ApplicationService,
    principal: Principal,
    *,
    title: str,
    key: str,
    project_id: str | None,
) -> ResponseEnvelope:
    return _invoke(
        service,
        principal,
        CreateTask(
            title=title,
            idempotency_key=key,
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
            project_id=project_id,
        ),
    )


def test_clear_project_and_project_id_together_are_invalid_request() -> None:
    with pytest.raises(InvalidRequestError) as refused:
        UpdateTask(
            task_id=TASK_ID,
            expected_version=1,
            idempotency_key="both-project-fields",
            project_id=issue_identifier(IdKind.PROJECT),
            clear_project=True,
        )
    assert refused.value.safe_details == (SafeDetail.PROJECT_ID,)


def test_project_id_is_not_a_clear_fields_member() -> None:
    with pytest.raises(InvalidRequestError) as refused:
        UpdateTask(
            task_id=TASK_ID,
            expected_version=1,
            idempotency_key="clear-fields-project",
            clear_fields=("project_id",),
        )
    assert refused.value.safe_details == (SafeDetail.SELECTOR,)


def test_rich_create_accepts_an_owned_project_and_readback_preserves_it(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    harbour = _project(service, scene.principal, name="Owned Harbour", key="wp04a-owned-project")

    created = _rich_task(
        service,
        scene.principal,
        title="Inspect the owned harbour",
        key="wp04a-owned-create",
        project_id=harbour,
    )

    assert created.error is None and created.result is not None
    assert created.result["task"]["project_id"] == harbour
    assert created.result["replayed"] is False
    read = _invoke(
        service,
        scene.principal,
        ReadTask(task_id=str(created.result["task"]["task_id"])),
    )
    assert read.error is None and read.result is not None
    assert read.result["task"]["project_id"] == harbour


def test_rich_create_refuses_missing_and_foreign_projects_without_writes(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    stranger = operator()
    foreign = _project(service, stranger, name="Foreign Quay", key="wp04a-foreign-project")
    missing = issue_identifier(IdKind.PROJECT)
    before_tasks = tuple(scene.world.tasks_v2)
    before_history = tuple(scene.world.task_history_v2)

    missing_answer = _rich_task(
        service,
        scene.principal,
        title="Must not bind a missing project",
        key="wp04a-missing-create",
        project_id=missing,
    )
    foreign_answer = _rich_task(
        service,
        scene.principal,
        title="Must not bind a foreign project",
        key="wp04a-foreign-create",
        project_id=foreign,
    )

    assert missing_answer.error is not None and foreign_answer.error is not None
    assert missing_answer.error.code is ErrorCode.NOT_FOUND
    assert foreign_answer.error.code is ErrorCode.NOT_FOUND
    assert missing_answer.error.safe_details == foreign_answer.error.safe_details == ("project_id",)
    assert missing not in str(missing_answer.error)
    assert foreign not in str(foreign_answer.error)
    assert tuple(scene.world.tasks_v2) == before_tasks
    assert tuple(scene.world.task_history_v2) == before_history


def test_rich_create_project_binding_is_digest_bound_and_replays_in_a_new_service(
    scene: Scene,
) -> None:
    service = build_service(scene.world, scene.providers)
    harbour = _project(service, scene.principal, name="Replay Harbour", key="wp04a-replay-project")
    quay = _project(service, scene.principal, name="Replay Quay", key="wp04a-conflict-project")
    key = "wp04a-project-create-replay"
    first = _rich_task(
        service,
        scene.principal,
        title="Keep one project binding",
        key=key,
        project_id=harbour,
    )
    assert first.error is None and first.result is not None
    after_first_tasks = tuple(scene.world.tasks_v2)
    after_first_history = tuple(scene.world.task_history_v2)

    restarted = build_service(scene.world, scene.providers)
    replay = _rich_task(
        restarted,
        scene.principal,
        title="Keep one project binding",
        key=key,
        project_id=harbour,
    )
    conflict = _rich_task(
        restarted,
        scene.principal,
        title="Keep one project binding",
        key=key,
        project_id=quay,
    )

    assert replay.error is None and replay.result is not None
    assert replay.result["replayed"] is True
    assert replay.result["task"] == first.result["task"]
    assert conflict.error is not None
    assert conflict.error.code is ErrorCode.CONFLICT
    assert conflict.error.safe_details == ("idempotency_key",)
    assert tuple(scene.world.tasks_v2) == after_first_tasks
    assert tuple(scene.world.task_history_v2) == after_first_history


def test_create_read_reassign_clear_and_list_by_project(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    harbour = _project(service, scene.principal, name="Harbour Tower", key="proj-05-harbour")
    quay = _project(service, scene.principal, name="Quay Wall", key="proj-05-quay")
    attached = _attached_task(
        scene,
        service,
        scene.principal,
        title="Check the pour",
        key="proj-05-task-harbour",
        project_id=harbour,
    )
    other = _attached_task(
        scene,
        service,
        scene.principal,
        title="Walk the quay",
        key="proj-05-task-quay",
        project_id=quay,
    )
    read = _invoke(service, scene.principal, ReadTask(task_id=str(attached["task_id"])))
    assert read.error is None and read.result is not None
    assert read.result["task"]["project_id"] == harbour
    listed = _invoke(service, scene.principal, ListTasks())
    assert listed.error is None and listed.result is not None
    by_id = {row["task_id"]: row for row in listed.result["tasks"]}
    assert set(by_id) == {attached["task_id"], other["task_id"]}
    assert by_id[str(attached["task_id"])]["project_id"] == harbour
    reassigned = _invoke(
        service,
        scene.principal,
        UpdateTask(
            task_id=str(attached["task_id"]),
            expected_version=int(read.result["task"]["version"]),
            idempotency_key="proj-05-reassign",
            project_id=quay,
        ),
    )
    assert reassigned.error is None and reassigned.result is not None
    assert reassigned.result["task"]["project_id"] == quay
    assert reassigned.result["task"]["version"] == int(read.result["task"]["version"]) + 1
    scoped = _invoke(service, scene.principal, ListTasks(project_id=quay))
    assert scoped.error is None and scoped.result is not None
    assert {row["task_id"] for row in scoped.result["tasks"]} == {
        attached["task_id"],
        other["task_id"],
    }
    cleared = _invoke(
        service,
        scene.principal,
        UpdateTask(
            task_id=str(attached["task_id"]),
            expected_version=int(reassigned.result["task"]["version"]),
            idempotency_key="proj-05-clear",
            clear_project=True,
        ),
    )
    assert cleared.error is None and cleared.result is not None
    assert cleared.result["task"]["project_id"] is None
    after_clear = _invoke(service, scene.principal, ListTasks(project_id=quay))
    assert after_clear.error is None and after_clear.result is not None
    assert [row["task_id"] for row in after_clear.result["tasks"]] == [other["task_id"]]
    unscoped = _invoke(service, scene.principal, ListTasks())
    assert unscoped.error is None and unscoped.result is not None
    assert {row["task_id"] for row in unscoped.result["tasks"]} == {
        attached["task_id"],
        other["task_id"],
    }


def test_stale_project_update_still_conflicts(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    harbour = _project(service, scene.principal, name="Stale Harbour", key="proj-05-stale-project")
    quay = _project(service, scene.principal, name="Stale Quay", key="proj-05-stale-quay")
    attached = _attached_task(
        scene,
        service,
        scene.principal,
        title="Stale pour",
        key="proj-05-stale-task",
        project_id=harbour,
    )
    first = _invoke(
        service,
        scene.principal,
        UpdateTask(
            task_id=str(attached["task_id"]),
            expected_version=1,
            idempotency_key="proj-05-stale-first",
            project_id=quay,
        ),
    )
    assert first.error is None and first.result is not None
    stale = _invoke(
        service,
        scene.principal,
        UpdateTask(
            task_id=str(attached["task_id"]),
            expected_version=1,
            idempotency_key="proj-05-stale-second",
            clear_project=True,
        ),
    )
    assert stale.error is not None
    assert stale.error.code is ErrorCode.CONFLICT
    held = _invoke(service, scene.principal, ReadTask(task_id=str(attached["task_id"])))
    assert held.error is None and held.result is not None
    assert held.result["task"]["project_id"] == quay
    assert held.result["task"]["version"] == 2


def test_cross_principal_target_project_matches_missing_not_found(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    harbour = _project(service, scene.principal, name="Owner Harbour", key="proj-05-owner-project")
    attached = _attached_task(
        scene,
        service,
        scene.principal,
        title="Owner pour",
        key="proj-05-owner-task",
        project_id=harbour,
    )
    stranger = operator()
    foreign = _project(service, stranger, name="Foreign Harbour", key="proj-05-foreign-project")
    missing_id = issue_identifier(IdKind.PROJECT)
    before_tasks = tuple(scene.world.tasks_v2)
    before_history = tuple(scene.world.task_history_v2)
    missing = _invoke(
        service,
        scene.principal,
        UpdateTask(
            task_id=str(attached["task_id"]),
            expected_version=1,
            idempotency_key="proj-05-missing-project",
            project_id=missing_id,
        ),
    )
    foreign_target = _invoke(
        service,
        scene.principal,
        UpdateTask(
            task_id=str(attached["task_id"]),
            expected_version=1,
            idempotency_key="proj-05-foreign-project-target",
            project_id=foreign,
        ),
    )
    assert missing.error is not None and foreign_target.error is not None
    assert missing.error.code is ErrorCode.NOT_FOUND
    assert foreign_target.error.code is ErrorCode.NOT_FOUND
    assert missing.error.safe_details == foreign_target.error.safe_details == ("project_id",)
    assert missing_id not in str(missing.error)
    assert foreign not in str(foreign_target.error)
    assert tuple(scene.world.tasks_v2) == before_tasks
    assert tuple(scene.world.task_history_v2) == before_history
    held = _invoke(service, scene.principal, ReadTask(task_id=str(attached["task_id"])))
    assert held.error is None and held.result is not None
    assert held.result["task"]["project_id"] == harbour
