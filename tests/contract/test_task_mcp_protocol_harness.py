"""F-010: MCP protocol harness for the Task capability family.

Proves the ten protocol-level properties the remediation plan requires,
end to end over the MCP transport — a real JSON-RPC exchange, a real server,
and the SDK's own client — without re-testing domain logic that other tests
already cover.

1.  tools/list publishes Task capabilities with descriptions
2.  tasks.create → returns task_id + version
3.  tasks.read with returned task_id → returns the same Task
4.  tasks.update with expected_version → returns new version
5.  Follow-up tasks.read confirms the mutation
6.  tasks.transition with new version → terminal state
7.  tasks.list shows the terminal task
8.  Version conflict: stale expected_version → conflict error
9.  Ambiguity: task_not_found for nonexistent ID
10. Pulse items for Tasks carry subject_title
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone

import pytest
from tests.conftest import (
    Scene,
    build_service,
    staged_record,
    staged_search,
)
from tests.contract.test_transport_parity import a_permitted_purpose, document
from tests.transports import McpTransport, mcp_transport

from my_pa.domain.identity.operation import Capability
from my_pa.domain.situation.continuity import (
    ContinuityAcceptanceKind,
    ContinuityEvidenceState,
    TaskState,
)
from my_pa.domain.situation.continuity import Task as ContinuityTask
from my_pa.contracts.v1.errors import ErrorCode

type Served = AbstractContextManager[McpTransport]

TASK_CAPABILITIES = {
    "tasks.create",
    "tasks.read",
    "tasks.list",
    "tasks.search",
    "tasks.update",
    "tasks.transition",
    "tasks.history",
    "tasks.bulk_preview",
    "tasks.bulk_confirm",
}


# ---- fixtures ----------------------------------------------------------------


@pytest.fixture
def served(scene: Scene) -> Served[McpTransport]:
    """One running MCP server with staged data for task operations."""
    staged_record(scene, text="quarterly revenue review")
    scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)
    return mcp_transport(build_service(scene.world, scene.providers), scene.principal)


def _task_doc(scene: Scene, capability: Capability, payload: dict) -> dict:
    """Build a well-formed request document for a task capability."""
    return document(capability, scene.principal.principal_id, payload)


# ---- 1. tools/list publishes Task capabilities with descriptions -------------


@pytest.mark.slow
def test_tools_list_publishes_task_capabilities_with_descriptions(
    served: Served[McpTransport],
) -> None:
    """Every task capability appears in tools/list and carries a non-empty description."""
    with served as session:
        listed = session.list_tools()
    published = {tool.name: tool for tool in listed.tools}
    for cap_name in TASK_CAPABILITIES:
        assert cap_name in published, f"{cap_name} missing from tools/list"
        assert published[cap_name].description, f"{cap_name} has no description"


# ---- 2–7. The happy-path lifecycle: create → read → update → read → transition → list


@pytest.mark.slow
def test_task_lifecycle_over_mcp(scene: Scene) -> None:
    """Walk a Task from creation through update and transition to a terminal state.

    Covers scenarios 2–7 in a single sequential exchange on one MCP session,
    because each step depends on identifiers and versions returned by the
    previous one.
    """
    staged_record(scene, text="lifecycle harness")
    scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)
    served = mcp_transport(build_service(scene.world, scene.providers), scene.principal)

    with served as session:
        # -- 2. tasks.create → returns task_id + version --
        create_answer = session.send(
            "tasks.create",
            _task_doc(scene, Capability.TASKS_CREATE, {
                "title": "Harness lifecycle task",
                "origin_evidence_ref": "cap_origin0001origin0001",
                "idempotency_key": "harness-lifecycle-create-001",
            }),
        )
        assert not create_answer.failed, f"tasks.create failed: {create_answer.document}"
        create_payload = create_answer.document["payload"]
        task = create_payload["task"]
        task_id = task["task_id"]
        version_0 = task["version"]
        assert task_id, "task_id must be non-empty"
        assert version_0 is not None, "version must be present"
        assert task["title"] == "Harness lifecycle task"

        # -- 3. tasks.read with returned task_id → returns the same Task --
        read_answer = session.send(
            "tasks.read",
            _task_doc(scene, Capability.TASKS_READ, {"task_id": task_id}),
        )
        assert not read_answer.failed, f"tasks.read failed: {read_answer.document}"
        read_task = read_answer.document["payload"]["task"]
        assert read_task["task_id"] == task_id
        assert read_task["version"] == version_0
        assert read_task["title"] == "Harness lifecycle task"

        # -- 4. tasks.update with expected_version → returns new version --
        update_answer = session.send(
            "tasks.update",
            _task_doc(scene, Capability.TASKS_UPDATE, {
                "task_id": task_id,
                "expected_version": version_0,
                "idempotency_key": "harness-lifecycle-update-001",
                "title": "Harness lifecycle task, revised",
            }),
        )
        assert not update_answer.failed, f"tasks.update failed: {update_answer.document}"
        update_payload = update_answer.document["payload"]
        updated_task = update_payload["task"]
        version_1 = updated_task["version"]
        assert version_1 != version_0, "version must advance after update"
        assert updated_task["title"] == "Harness lifecycle task, revised"

        # -- 5. Follow-up tasks.read confirms the mutation --
        read2_answer = session.send(
            "tasks.read",
            _task_doc(scene, Capability.TASKS_READ, {"task_id": task_id}),
        )
        assert not read2_answer.failed
        read2_task = read2_answer.document["payload"]["task"]
        assert read2_task["version"] == version_1
        assert read2_task["title"] == "Harness lifecycle task, revised"

        # -- 6. tasks.transition with new version → terminal state --
        transition_answer = session.send(
            "tasks.transition",
            _task_doc(scene, Capability.TASKS_TRANSITION, {
                "task_id": task_id,
                "to_state": "completed",
                "expected_version": version_1,
                "idempotency_key": "harness-lifecycle-transition-001",
                "closure_evidence_ref": "cap_origin0001origin0001",
            }),
        )
        assert not transition_answer.failed, (
            f"tasks.transition failed: {transition_answer.document}"
        )
        transitioned = transition_answer.document["payload"]["task"]
        assert transitioned["lifecycle_state"] == "completed"
        version_2 = transitioned["version"]

        # -- 7. tasks.list shows the terminal task --
        list_answer = session.send(
            "tasks.list",
            _task_doc(scene, Capability.TASKS_LIST, {}),
        )
        assert not list_answer.failed, f"tasks.list failed: {list_answer.document}"
        tasks_listed = list_answer.document["payload"]["tasks"]
        listed_ids = [t["task_id"] for t in tasks_listed]
        assert task_id in listed_ids, "completed task must appear in tasks.list"


# ---- 8. Version conflict: stale expected_version → conflict error ------------


@pytest.mark.slow
def test_stale_version_produces_conflict_error(scene: Scene) -> None:
    """A stale expected_version on tasks.update → conflict error code."""
    staged_record(scene, text="conflict harness")
    scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)
    served = mcp_transport(build_service(scene.world, scene.providers), scene.principal)

    with served as session:
        # Create a task
        create_answer = session.send(
            "tasks.create",
            _task_doc(scene, Capability.TASKS_CREATE, {
                "title": "Conflict test task",
                "origin_evidence_ref": "cap_origin0001origin0001",
                "idempotency_key": "harness-conflict-create-001",
            }),
        )
        assert not create_answer.failed
        task = create_answer.document["payload"]["task"]
        task_id = task["task_id"]
        version_0 = task["version"]

        # Update once to advance the version
        update_answer = session.send(
            "tasks.update",
            _task_doc(scene, Capability.TASKS_UPDATE, {
                "task_id": task_id,
                "expected_version": version_0,
                "idempotency_key": "harness-conflict-update-001",
                "title": "Conflict test task, first update",
            }),
        )
        assert not update_answer.failed

        # Now try to update with the stale version_0
        stale_answer = session.send(
            "tasks.update",
            _task_doc(scene, Capability.TASKS_UPDATE, {
                "task_id": task_id,
                "expected_version": version_0,
                "idempotency_key": "harness-conflict-update-002",
                "title": "Conflict test task, stale update",
            }),
        )
        assert stale_answer.failed, "stale version must cause a failure"
        error = stale_answer.document.get("error") or stale_answer.document
        assert error["code"] == ErrorCode.CONFLICT.value, (
            f"expected conflict error, got {error.get('code')}"
        )


# ---- 9. Ambiguity: task_not_found for nonexistent ID ------------------------


@pytest.mark.slow
def test_nonexistent_task_id_produces_not_found(
    served: Served[McpTransport], scene: Scene
) -> None:
    """tasks.read with a fabricated task_id → not_found error code."""
    with served as session:
        answer = session.send(
            "tasks.read",
            _task_doc(scene, Capability.TASKS_READ, {
                "task_id": "tsk_0000000000000000000000000000",
            }),
        )
    assert answer.failed, "nonexistent task_id must cause a failure"
    error = answer.document.get("error") or answer.document
    assert error["code"] == ErrorCode.NOT_FOUND.value, (
        f"expected not_found error, got {error.get('code')}"
    )


# ---- 10. Pulse items for Tasks carry subject_title --------------------------


@pytest.mark.slow
def test_pulse_items_for_tasks_carry_subject_title(scene: Scene) -> None:
    """A task with a due_at in the past produces a Pulse item with subject_title.

    This is the "What is it?" fix: when a Task appears on the Pulse, the item
    must carry `subject_title` so the consumer knows *which* task without a
    second round-trip.
    """
    staged_record(scene, text="pulse harness")
    scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)

    # Stage a continuity-plane task with an overdue due_at so the pulse derivation fires.
    from my_pa.domain.common.identifiers import IdKind
    from my_pa.domain.source.registry import issue_identifier

    now = datetime.now(tz=timezone.utc)
    overdue_task = ContinuityTask(
        task_id=issue_identifier(IdKind.TASK),
        principal_id=scene.principal.principal_id,
        title="Overdue harness task for pulse",
        state=TaskState.OPEN,
        evidence_state=ContinuityEvidenceState.ACCEPTED,
        origin_evidence_ref="cap_origin0001origin0001",
        opened_at=now - timedelta(days=3),
        created_at=now - timedelta(days=3),
        updated_at=now - timedelta(days=3),
        due_at=now - timedelta(days=1),
        acceptance_kind=ContinuityAcceptanceKind.DIRECT_PRINCIPAL,
    )
    scene.world.continuity_tasks.append(overdue_task)

    served = mcp_transport(build_service(scene.world, scene.providers), scene.principal)

    with served as session:
        pulse_answer = session.send(
            "continuity.pulse",
            _task_doc(scene, Capability.CONTINUITY_PULSE, {}),
        )
    assert not pulse_answer.failed, f"continuity.pulse failed: {pulse_answer.document}"
    items = pulse_answer.document["payload"]["pulse_items"]
    task_items = [item for item in items if item.get("item_type") == "task"]
    assert task_items, "an overdue task must produce at least one Pulse item"
    for item in task_items:
        assert "subject_title" in item, (
            f"Pulse item {item.get('pulse_id')} is missing subject_title"
        )
        assert item["subject_title"], "subject_title must be non-empty"
