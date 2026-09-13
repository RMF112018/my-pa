"""Versioned continuity.projects.update and continuity.projects.close."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.adapters.normalization import normalize
from my_pa.application.commands import CloseProject, Command, CreateProject, UpdateProject
from my_pa.application.errors import InvalidRequestError
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode, RetryGuidance
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.situation.situation import Project, ProjectState
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.history import TaskMutationOutcome
from tests.conftest import Scene, build_service, metadata_for, operator
from tests.contract.test_transport_parity import document


def _invoke(
    service: ApplicationService,
    principal: Principal,
    capability: Capability,
    purpose: Purpose,
    command: Command,
) -> ResponseEnvelope:
    return service.invoke(
        metadata_for(capability, purpose, principal),
        command,
        principal=principal,
    )


def _create(service: ApplicationService, principal: Principal, *, name: str, key: str) -> dict:
    created = _invoke(
        service,
        principal,
        Capability.CONTINUITY_PROJECTS_CREATE,
        Purpose.CONTINUITY_AUTHORING,
        CreateProject(name=name, idempotency_key=key),
    )
    assert created.error is None and created.result is not None
    return created.result


def test_update_may_change_each_mutable_field(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(service, scene.principal, name="Mutable", key="mutate-fields-0001")
    project_id = created["project_id"]
    renamed = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_UPDATE,
        Purpose.CONTINUITY_AUTHORING,
        UpdateProject(
            project_id=project_id,
            expected_version=1,
            idempotency_key="mutate-name-0001",
            name="Renamed",
        ),
    )
    assert renamed.error is None and renamed.result is not None
    assert renamed.result["name"] == "Renamed"
    assert renamed.result["version"] == 2
    assert renamed.result["replayed"] is False
    described = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_UPDATE,
        Purpose.CONTINUITY_AUTHORING,
        UpdateProject(
            project_id=project_id,
            expected_version=2,
            idempotency_key="mutate-description-0001",
            description="A held description",
        ),
    )
    assert described.error is None and described.result is not None
    assert described.result["description"] == "A held description"
    assert described.result["version"] == 3
    paused = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_UPDATE,
        Purpose.CONTINUITY_AUTHORING,
        UpdateProject(
            project_id=project_id,
            expected_version=3,
            idempotency_key="mutate-state-0001",
            state=ProjectState.ON_HOLD,
        ),
    )
    assert paused.error is None and paused.result is not None
    assert paused.result["state"] == "on_hold"
    assert paused.result["version"] == 4
    assert scene.world.project_history[-1].outcome is TaskMutationOutcome.APPLIED
    assert scene.world.project_history[-1].after_version == 4
    assert scene.world.project_history[-1].before_version == 3


def test_update_toggles_active_and_on_hold(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(service, scene.principal, name="Toggle", key="mutate-toggle-0001")
    held = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_UPDATE,
        Purpose.CONTINUITY_AUTHORING,
        UpdateProject(
            project_id=created["project_id"],
            expected_version=1,
            idempotency_key="mutate-toggle-hold-0001",
            state=ProjectState.ON_HOLD,
        ),
    )
    assert held.error is None and held.result is not None
    assert held.result["state"] == "on_hold"
    resumed = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_UPDATE,
        Purpose.CONTINUITY_AUTHORING,
        UpdateProject(
            project_id=created["project_id"],
            expected_version=2,
            idempotency_key="mutate-toggle-active-0001",
            state=ProjectState.ACTIVE,
        ),
    )
    assert resumed.error is None and resumed.result is not None
    assert resumed.result["state"] == "active"
    assert resumed.result["version"] == 3


@pytest.mark.parametrize("start_state", [ProjectState.ACTIVE, ProjectState.ON_HOLD])
def test_close_moves_active_or_on_hold_to_closed(scene: Scene, start_state: ProjectState) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(
        service,
        scene.principal,
        name=f"Closeable {start_state.value}",
        key=f"mutate-close-{start_state.value}-0001",
    )
    project_id = created["project_id"]
    version = 1
    if start_state is ProjectState.ON_HOLD:
        held = _invoke(
            service,
            scene.principal,
            Capability.CONTINUITY_PROJECTS_UPDATE,
            Purpose.CONTINUITY_AUTHORING,
            UpdateProject(
                project_id=project_id,
                expected_version=1,
                idempotency_key=f"mutate-close-prep-{start_state.value}-0001",
                state=ProjectState.ON_HOLD,
            ),
        )
        assert held.error is None and held.result is not None
        version = 2
    closed = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_CLOSE,
        Purpose.CONTINUITY_AUTHORING,
        CloseProject(
            project_id=project_id,
            expected_version=version,
            idempotency_key=f"mutate-close-{start_state.value}-0002",
        ),
    )
    assert closed.error is None and closed.result is not None
    assert closed.result["state"] == "closed"
    assert closed.result["closed_at"] is not None
    assert closed.result["version"] == version + 1
    stored = next(row for row in scene.world.projects if row.project_id == project_id)
    assert stored.state is ProjectState.CLOSED
    assert stored.closed_at is not None
    assert stored.closed_at.tzinfo is UTC


def test_closed_cannot_return_to_active(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(service, scene.principal, name="Terminal", key="mutate-illegal-0001")
    closed = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_CLOSE,
        Purpose.CONTINUITY_AUTHORING,
        CloseProject(
            project_id=created["project_id"],
            expected_version=1,
            idempotency_key="mutate-illegal-close-0001",
        ),
    )
    assert closed.error is None
    refused = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_UPDATE,
        Purpose.CONTINUITY_AUTHORING,
        UpdateProject(
            project_id=created["project_id"],
            expected_version=2,
            idempotency_key="mutate-illegal-reopen-0001",
            state=ProjectState.ACTIVE,
        ),
    )
    assert refused.error is not None
    assert refused.error.code is ErrorCode.CONFLICT
    assert list(refused.error.safe_details) == ["project_id"]
    assert refused.error.retry is RetryGuidance.AFTER_REFRESH
    stored = next(row for row in scene.world.projects if row.project_id == created["project_id"])
    assert stored.state is ProjectState.CLOSED
    assert stored.version == 2


def test_close_of_already_closed_is_conflict(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(service, scene.principal, name="Already closed", key="mutate-reclose-0001")
    first = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_CLOSE,
        Purpose.CONTINUITY_AUTHORING,
        CloseProject(
            project_id=created["project_id"],
            expected_version=1,
            idempotency_key="mutate-reclose-applied-0001",
        ),
    )
    assert first.error is None and first.result is not None
    replay = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_CLOSE,
        Purpose.CONTINUITY_AUTHORING,
        CloseProject(
            project_id=created["project_id"],
            expected_version=1,
            idempotency_key="mutate-reclose-applied-0001",
        ),
    )
    assert replay.error is None and replay.result is not None
    assert replay.result["replayed"] is True
    assert replay.result["version"] == first.result["version"]
    second = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_CLOSE,
        Purpose.CONTINUITY_AUTHORING,
        CloseProject(
            project_id=created["project_id"],
            expected_version=2,
            idempotency_key="mutate-reclose-again-0001",
        ),
    )
    assert second.error is not None
    assert second.error.code is ErrorCode.CONFLICT
    assert list(second.error.safe_details) == ["project_id"]


def test_closed_via_update_is_invalid_request() -> None:
    with pytest.raises(InvalidRequestError) as refused:
        UpdateProject(
            project_id=issue_identifier(IdKind.PROJECT),
            expected_version=1,
            idempotency_key="mutate-closed-token-0001",
            state=ProjectState.CLOSED,
        )
    assert list(refused.value.safe_details) == ["selector"]


def test_illegal_state_token_is_invalid_request(scene: Scene) -> None:
    created = _create(
        build_service(scene.world, scene.providers),
        scene.principal,
        name="Token",
        key="mutate-token-0001",
    )
    with pytest.raises(InvalidRequestError) as refused:
        normalize(
            Capability.CONTINUITY_PROJECTS_UPDATE.value,
            document(
                Capability.CONTINUITY_PROJECTS_UPDATE,
                scene.principal.principal_id,
                {
                    "project_id": created["project_id"],
                    "expected_version": 1,
                    "idempotency_key": "mutate-token-0002",
                    "state": "archived",
                },
            ),
        )
    assert list(refused.value.safe_details) == ["selector"]


def test_stale_write_is_conflict_and_records_rejected_history(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(service, scene.principal, name="Stale", key="mutate-stale-0001")
    first = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_UPDATE,
        Purpose.CONTINUITY_AUTHORING,
        UpdateProject(
            project_id=created["project_id"],
            expected_version=1,
            idempotency_key="mutate-stale-apply-0001",
            name="First writer",
        ),
    )
    assert first.error is None and first.result is not None
    stale = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_UPDATE,
        Purpose.CONTINUITY_AUTHORING,
        UpdateProject(
            project_id=created["project_id"],
            expected_version=1,
            idempotency_key="mutate-stale-loser-0001",
            name="Second writer",
        ),
    )
    assert stale.error is not None
    assert stale.error.code is ErrorCode.CONFLICT
    assert list(stale.error.safe_details) == ["project_id"]
    assert stale.error.retry is RetryGuidance.AFTER_REFRESH
    stored = next(row for row in scene.world.projects if row.project_id == created["project_id"])
    assert stored.name == "First writer"
    assert stored.version == 2
    rejected = [
        row for row in scene.world.project_history if row.outcome is TaskMutationOutcome.REJECTED
    ]
    assert len(rejected) == 1
    assert rejected[0].before_version == rejected[0].after_version == 2


def test_idempotent_replay_returns_the_current_project(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(service, scene.principal, name="Replay", key="mutate-replay-0001")
    command = UpdateProject(
        project_id=created["project_id"],
        expected_version=1,
        idempotency_key="mutate-replay-update-0001",
        name="Replay name",
    )
    first = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_UPDATE,
        Purpose.CONTINUITY_AUTHORING,
        command,
    )
    second = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_UPDATE,
        Purpose.CONTINUITY_AUTHORING,
        command,
    )
    assert first.error is None and second.error is None
    assert first.result is not None and second.result is not None
    assert second.result["replayed"] is True
    assert second.result["project_id"] == first.result["project_id"]
    assert second.result["version"] == first.result["version"] == 2
    applied = [
        row
        for row in scene.world.project_history
        if row.outcome is TaskMutationOutcome.APPLIED and row.action.value == "update"
    ]
    assert len(applied) == 1


def test_same_key_different_digest_conflicts(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(service, scene.principal, name="Digest", key="mutate-digest-0001")
    first = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_UPDATE,
        Purpose.CONTINUITY_AUTHORING,
        UpdateProject(
            project_id=created["project_id"],
            expected_version=1,
            idempotency_key="mutate-digest-shared-0001",
            name="First digest",
        ),
    )
    assert first.error is None
    refused = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_UPDATE,
        Purpose.CONTINUITY_AUTHORING,
        UpdateProject(
            project_id=created["project_id"],
            expected_version=1,
            idempotency_key="mutate-digest-shared-0001",
            name="Different digest",
        ),
    )
    assert refused.error is not None
    assert refused.error.code is ErrorCode.CONFLICT
    assert list(refused.error.safe_details) == ["idempotency_key"]


def test_cross_principal_mutation_is_not_found(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(service, scene.principal, name="Owned", key="mutate-iso-0001")
    stranger = operator()
    refused = _invoke(
        service,
        stranger,
        Capability.CONTINUITY_PROJECTS_UPDATE,
        Purpose.CONTINUITY_AUTHORING,
        UpdateProject(
            project_id=created["project_id"],
            expected_version=1,
            idempotency_key="mutate-iso-stranger-0001",
            name="Hijack",
        ),
    )
    assert refused.error is not None
    assert refused.error.code is ErrorCode.NOT_FOUND
    assert list(refused.error.safe_details) == ["project_id"]
    stored = next(row for row in scene.world.projects if row.project_id == created["project_id"])
    assert stored.name == "Owned"


def test_missing_project_is_not_found(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    refused = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_CLOSE,
        Purpose.CONTINUITY_AUTHORING,
        CloseProject(
            project_id=issue_identifier(IdKind.PROJECT),
            expected_version=1,
            idempotency_key="mutate-missing-0001",
        ),
    )
    assert refused.error is not None
    assert refused.error.code is ErrorCode.NOT_FOUND


def test_payload_system_field_is_invalid_request(scene: Scene) -> None:
    created = _create(
        build_service(scene.world, scene.providers),
        scene.principal,
        name="Envelope",
        key="mutate-envelope-0001",
    )
    with pytest.raises(InvalidRequestError):
        normalize(
            Capability.CONTINUITY_PROJECTS_UPDATE.value,
            document(
                Capability.CONTINUITY_PROJECTS_UPDATE,
                scene.principal.principal_id,
                {
                    "project_id": created["project_id"],
                    "expected_version": 1,
                    "idempotency_key": "mutate-envelope-payload-0001",
                    "name": "Should not land",
                    "principal_id": scene.principal.principal_id,
                },
            ),
        )
    with pytest.raises(InvalidRequestError):
        normalize(
            Capability.CONTINUITY_PROJECTS_CLOSE.value,
            document(
                Capability.CONTINUITY_PROJECTS_CLOSE,
                scene.principal.principal_id,
                {
                    "project_id": created["project_id"],
                    "expected_version": 1,
                    "idempotency_key": "mutate-envelope-close-0001",
                    "closed_at": "2026-09-13T12:00:00Z",
                },
            ),
        )


def test_command_constructor_rejects_system_owned_fields() -> None:
    project_id = issue_identifier(IdKind.PROJECT)
    with pytest.raises(TypeError):
        UpdateProject(
            project_id=project_id,
            expected_version=1,
            idempotency_key="mutate-ctor-0001",
            name="Named",
            principal_id="prn_cccc0001cccc0001cccc0001",
        )
    with pytest.raises(TypeError):
        CloseProject(
            project_id=project_id,
            expected_version=1,
            idempotency_key="mutate-ctor-0002",
            version=9,
        )


def test_update_requires_at_least_one_mutable_field() -> None:
    with pytest.raises(InvalidRequestError) as refused:
        UpdateProject(
            project_id=issue_identifier(IdKind.PROJECT),
            expected_version=1,
            idempotency_key="mutate-empty-0001",
        )
    assert list(refused.value.safe_details) == ["selector"]


def test_closed_at_invariant_holds_after_close(scene: Scene) -> None:
    created_at = datetime(2026, 9, 13, 12, tzinfo=UTC)
    seeded = Project(
        project_id=issue_identifier(IdKind.PROJECT),
        principal_id=scene.principal.principal_id,
        name="Invariant",
        state=ProjectState.ACTIVE,
        opened_at=created_at,
        created_at=created_at,
        updated_at=created_at,
        version=1,
    )
    scene.world.projects.append(seeded)
    service = build_service(scene.world, scene.providers)
    closed = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_CLOSE,
        Purpose.CONTINUITY_AUTHORING,
        CloseProject(
            project_id=seeded.project_id,
            expected_version=1,
            idempotency_key="mutate-invariant-0001",
        ),
    )
    assert closed.error is None and closed.result is not None
    stored = next(row for row in scene.world.projects if row.project_id == seeded.project_id)
    Project(
        project_id=stored.project_id,
        principal_id=stored.principal_id,
        name=stored.name,
        state=stored.state,
        opened_at=stored.opened_at,
        created_at=stored.created_at,
        updated_at=stored.updated_at,
        closed_at=stored.closed_at,
        version=stored.version,
    )
    assert stored.state is ProjectState.CLOSED
    assert stored.closed_at is not None
