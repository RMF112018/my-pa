"""Work mutation receipts project current Capture provenance, including replays."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from my_pa.application.commands import (
    ArchiveCapture,
    CloseCommitment,
    CreateCapture,
    CreateCommitment,
    CreateTask,
    ReadCommitment,
    ReadTask,
    RestoreCapture,
    TransitionTask,
    UpdateCommitment,
    UpdateTask,
)
from my_pa.application.service import ApplicationService
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.situation.continuity import CommitmentDirection
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.lifecycle import TaskLifecycleState
from tests.conftest import (
    DEFAULT_LIMITS,
    WHEN,
    FakeCommitmentManagementUnitOfWork,
    FakeTaskManagementUnitOfWork,
    FakeUnitOfWork,
    World,
    _Captures,
    _fake_lifecycle,
    metadata_for,
    operator,
)


@pytest.mark.parametrize(
    "operation",
    [
        "task_create",
        "task_update",
        "task_transition",
        "commitment_create",
        "commitment_update",
        "commitment_close",
    ],
)
@pytest.mark.parametrize("origin_kind", [IdKind.CAPTURE, IdKind.ASSERTION])
def test_write_and_replay_labels_follow_current_lifecycle(
    operation: str, origin_kind: IdKind, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    principal = operator()
    seed_service = ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(world), limits=DEFAULT_LIMITS, clock=lambda: WHEN
    )

    def seed(key: str) -> str:
        response = seed_service.invoke(
            metadata_for(CreateCapture.capability, Purpose.CAPTURE_AUTHORING, principal),
            CreateCapture(text="Synthetic provenance evidence", idempotency_key=key),
            principal=principal,
        )
        assert response.error is None, response.error
        assert response.result is not None
        return str(response.result["capture_id"])

    origin_root = seed("seed-origin")
    closure_root = seed("seed-closure")
    origin = origin_root if origin_kind is IdKind.CAPTURE else issue_identifier(IdKind.ASSERTION)
    closure = closure_root
    roots = {origin: origin_root, closure: closure_root}
    batches: list[tuple[str, tuple[str, ...]]] = []
    world.work_evidence_refs.update((principal.principal_id, ref) for ref in roots)

    def resolve(
        self: _Captures, principal_id: str, references: tuple[str, ...]
    ) -> Mapping[str, str]:
        batches.append((principal_id, references))
        return {
            ref: _fake_lifecycle(world, root, principal_id).state.value
            for ref in references
            if (root := roots.get(ref)) is not None and world.captures[root][0] == principal_id
        }

    monkeypatch.setattr(_Captures, "evidence_lifecycle_states", resolve)
    service = ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(world),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        managed_store=world.managed_store,
        task_management_unit_of_work=lambda: FakeTaskManagementUnitOfWork(world),
        commitment_management_unit_of_work=lambda: FakeCommitmentManagementUnitOfWork(world),
    )

    def invoke(command: object, purpose: Purpose) -> dict:
        response = service.invoke(
            metadata_for(command.capability, purpose, principal), command, principal=principal
        )
        assert response.error is None, response.error
        assert response.result is not None
        return response.result

    is_task = operation.startswith("task")
    purpose = Purpose.TASK_AUTHORING if is_task else Purpose.COMMITMENT_AUTHORING
    if is_task:
        create = CreateTask(
            title="Synthetic follow up", origin_evidence_ref=origin, idempotency_key="create-task"
        )
    else:
        person = issue_identifier(IdKind.PERSON)
        world.current_counterparties.add((principal.principal_id, person))
        create = CreateCommitment(
            counterparty_person_id=person,
            direction=CommitmentDirection.OWED_TO_PRINCIPAL,
            summary="Synthetic obligation",
            origin_evidence_ref=origin,
            idempotency_key="create-commitment",
        )
    field = "task" if is_task else "commitment"
    created = invoke(create, purpose)
    identifier = created[field][f"{field}_id"]
    version = created[field]["version"]
    if operation.endswith("create"):
        command = create
        first = created
    elif operation == "task_update":
        closed = invoke(
            TransitionTask(
                task_id=identifier,
                expected_version=version,
                to_state=TaskLifecycleState.COMPLETED,
                closure_evidence_ref=closure,
                idempotency_key="close-before-task-update",
            ),
            purpose,
        )
        version = closed[field]["version"]
        command = UpdateTask(
            task_id=identifier,
            expected_version=version,
            title="Updated synthetic task",
            idempotency_key="update-task",
        )
        first = invoke(command, purpose)
    elif operation == "task_transition":
        command = TransitionTask(
            task_id=identifier,
            expected_version=version,
            to_state=TaskLifecycleState.COMPLETED,
            closure_evidence_ref=closure,
            idempotency_key="transition-task",
        )
        first = invoke(command, purpose)
    elif operation == "commitment_update":
        closed = invoke(
            CloseCommitment(
                commitment_id=identifier,
                expected_version=version,
                closure_evidence_ref=closure,
                idempotency_key="close-before-commitment-update",
            ),
            purpose,
        )
        version = closed[field]["version"]
        command = UpdateCommitment(
            commitment_id=identifier,
            expected_version=version,
            summary="Updated synthetic commitment",
            idempotency_key="update-commitment",
        )
        first = invoke(command, purpose)
    else:
        command = CloseCommitment(
            commitment_id=identifier,
            expected_version=version,
            closure_evidence_ref=closure,
            idempotency_key="close-commitment",
        )
        first = invoke(command, purpose)
    has_closure = not operation.endswith("create")
    expected_refs = (origin, closure) if has_closure else (origin,)
    assert first[field]["origin_evidence_capture_state"] == "active"
    assert first[field]["closure_evidence_capture_state"] == ("active" if has_closure else None)
    assert batches[-1] == (principal.principal_id, expected_refs)

    read_command = (
        ReadTask(task_id=identifier) if is_task else ReadCommitment(commitment_id=identifier)
    )
    read_purpose = Purpose.TASK_READ if is_task else Purpose.COMMITMENT_READ
    immediate_read = invoke(read_command, read_purpose)
    for label in ("origin_evidence_capture_state", "closure_evidence_capture_state"):
        assert first[field][label] == immediate_read[field][label]
    assert first[field]["origin_evidence_ref"] == origin
    assert first[field]["closure_evidence_ref"] == (closure if has_closure else None)
    assert "Synthetic provenance evidence" not in repr(first)
    assert "Synthetic provenance evidence" not in repr(immediate_read)
    durable_before = (
        tuple(world.tasks_v2),
        tuple(world.commitments_v2),
        tuple(world.task_history_v2),
        tuple(world.commitment_history_v2),
    )
    for revision, state in ((0, "archived"), (1, "active")):
        for root in roots.values():
            lifecycle_command = (
                ArchiveCapture(
                    capture_id=root,
                    expected_lifecycle_revision=revision,
                    reason="Synthetic withdrawal",
                    idempotency_key=f"archive-{root}",
                )
                if state == "archived"
                else RestoreCapture(
                    capture_id=root,
                    expected_lifecycle_revision=revision,
                    reason="Synthetic restoration",
                    idempotency_key=f"restore-{root}",
                )
            )
            invoke(lifecycle_command, Purpose.CAPTURE_AUTHORING)
        events_before = tuple(world.record_events)
        batches.clear()
        replay = invoke(command, purpose)
        assert replay["replayed"] is True
        assert "Synthetic provenance evidence" not in repr(replay)
        assert batches == [(principal.principal_id, expected_refs)]
        read = invoke(read_command, read_purpose)
        assert "Synthetic provenance evidence" not in repr(read)
        assert replay[field]["origin_evidence_ref"] == origin
        assert replay[field]["closure_evidence_ref"] == (closure if has_closure else None)
        for label in ("origin_evidence_capture_state", "closure_evidence_capture_state"):
            expected = state if label.startswith("origin") or has_closure else None
            assert replay[field][label] == read[field][label] == expected
        assert replay[field]["version"] == first[field]["version"]
        if "history" in first:
            assert replay["history"] == first["history"]
        assert events_before == tuple(world.record_events)
        assert durable_before == (
            tuple(world.tasks_v2),
            tuple(world.commitments_v2),
            tuple(world.task_history_v2),
            tuple(world.commitment_history_v2),
        )
