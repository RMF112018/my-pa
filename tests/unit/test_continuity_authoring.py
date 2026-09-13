"""User-directed continuity writes populate the canonical read surface."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from my_pa.application.commands import (
    Command,
    CreateCapture,
    CreateProject,
    CreateSituation,
    GetPulse,
    ListProjects,
    ListSituations,
    RecordTask,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.relationship.entity import EntityType
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.situation.situation import (
    Project,
    ProjectEntityLink,
    ProjectEntityLinkageState,
    ProjectState,
)
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import WHEN, FakeUnitOfWork, Scene, World, build_service, metadata_for, operator


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


def test_explicit_project_create_is_visible_on_continuity_projects(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_CREATE,
        Purpose.CONTINUITY_AUTHORING,
        CreateProject(name="MCP Write Acceptance Test", idempotency_key="author-project-0001"),
    )
    assert created.error is None
    assert created.result is not None
    assert created.result["name"] == "MCP Write Acceptance Test"
    assert created.result["replayed"] is False
    project = scene.world.projects[0]
    assert project.version == 1
    assert len(scene.world.project_entity_links) == 1
    link = scene.world.project_entity_links[0]
    assert link.linkage_state is ProjectEntityLinkageState.BOUND
    assert link.project_id == project.project_id
    assert link.principal_id == scene.principal.principal_id
    assert link.project_entity_id is not None
    entity = next(row for row in scene.world.entities if row.entity_id == link.project_entity_id)
    assert entity.entity_type is EntityType.PROJECT
    assert entity.display_name == "MCP Write Acceptance Test"
    assert entity.canonical_name == normalize_name("MCP Write Acceptance Test")
    assert entity.version == 1
    listed = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS,
        Purpose.CAPTURE_REVIEW,
        ListProjects(),
    )
    assert listed.error is None
    assert listed.result is not None
    names = [row["name"] for row in listed.result["projects"]]
    assert "MCP Write Acceptance Test" in names


def test_explicit_situation_create_is_visible_on_continuity_situations(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_SITUATIONS_CREATE,
        Purpose.CONTINUITY_AUTHORING,
        CreateSituation(title="MCP Write Acceptance Situation", idempotency_key="author-sit-0001"),
    )
    assert created.error is None
    listed = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_SITUATIONS,
        Purpose.CAPTURE_REVIEW,
        ListSituations(),
    )
    assert listed.error is None
    assert listed.result is not None
    titles = [row["title"] for row in listed.result["situations"]]
    assert "MCP Write Acceptance Situation" in titles


def test_explicit_task_create_with_due_date_reaches_the_pulse(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    due = WHEN + timedelta(hours=24)
    created = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_TASKS_CREATE,
        Purpose.CONTINUITY_AUTHORING,
        RecordTask(
            title="Verify ChatLLM write behavior",
            idempotency_key="author-task-0001",
            due_at=due,
        ),
    )
    assert created.error is None
    assert created.result is not None
    assert created.result["evidence_state"] == "accepted"
    assert created.result["acceptance_kind"] == "direct_principal"
    pulse = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PULSE,
        Purpose.CAPTURE_REVIEW,
        GetPulse(),
    )
    assert pulse.error is None
    assert pulse.result is not None
    refs = [item["item_ref"] for item in pulse.result["pulse_items"]]
    assert created.result["task_id"] in refs


def test_authoring_replay_returns_the_same_project(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    command = CreateProject(name="Replay Project", idempotency_key="author-replay-0001")
    first = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_CREATE,
        Purpose.CONTINUITY_AUTHORING,
        command,
    )
    second = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_CREATE,
        Purpose.CONTINUITY_AUTHORING,
        command,
    )
    assert first.error is None and second.error is None
    assert first.result is not None and second.result is not None
    assert first.result["project_id"] == second.result["project_id"]
    assert second.result["replayed"] is True
    assert len(scene.world.projects) == 1
    assert len(scene.world.project_entity_links) == 1
    assert len([row for row in scene.world.entities if row.entity_type is EntityType.PROJECT]) == 1


def test_reused_key_with_different_content_conflicts(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    first = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_CREATE,
        Purpose.CONTINUITY_AUTHORING,
        CreateProject(name="Original", idempotency_key="author-conflict-0001"),
    )
    assert first.error is None
    refused = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_CREATE,
        Purpose.CONTINUITY_AUTHORING,
        CreateProject(name="Different", idempotency_key="author-conflict-0001"),
    )
    assert refused.error is not None
    assert refused.error.code is ErrorCode.CONFLICT
    assert list(refused.error.safe_details) == ["idempotency_key"]


def test_a_foreign_project_id_cannot_attach_a_task(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    stranger = operator()
    foreign = _invoke(
        service,
        stranger,
        Capability.CONTINUITY_PROJECTS_CREATE,
        Purpose.CONTINUITY_AUTHORING,
        CreateProject(name="Foreign project", idempotency_key="author-foreign-0001"),
    )
    assert foreign.error is None
    assert foreign.result is not None
    refused = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_TASKS_CREATE,
        Purpose.CONTINUITY_AUTHORING,
        RecordTask(
            title="Should not attach",
            idempotency_key="author-foreign-task-0001",
            project_id=foreign.result["project_id"],
        ),
    )
    assert refused.error is not None
    assert refused.error.code is ErrorCode.NOT_FOUND


def test_a_second_principal_does_not_see_another_principals_project(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS_CREATE,
        Purpose.CONTINUITY_AUTHORING,
        CreateProject(name="Owner only", idempotency_key="author-isolation-0001"),
    )
    assert created.error is None
    stranger = operator()
    listed = _invoke(
        service,
        stranger,
        Capability.CONTINUITY_PROJECTS,
        Purpose.CAPTURE_REVIEW,
        ListProjects(),
    )
    assert listed.error is None
    assert listed.result is not None
    assert listed.result["projects"] == []
    owned = scene.world.projects[0]
    stranger_view = FakeUnitOfWork(scene.world).projects.get_project_entity_link(
        stranger.principal_id, owned.project_id
    )
    assert stranger_view is None
    owner_view = FakeUnitOfWork(scene.world).projects.get_project_entity_link(
        scene.principal.principal_id, owned.project_id
    )
    assert owner_view is not None
    assert owner_view.linkage_state is ProjectEntityLinkageState.BOUND


def test_capture_create_does_not_create_a_project(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    stored = _invoke(
        service,
        scene.principal,
        Capability.CAPTURE_CREATE,
        Purpose.CAPTURE_AUTHORING,
        CreateCapture(text="Create a project called Ambient Inference", idempotency_key="cap-0001"),
    )
    assert stored.error is None
    listed = _invoke(
        service,
        scene.principal,
        Capability.CONTINUITY_PROJECTS,
        Purpose.CAPTURE_REVIEW,
        ListProjects(),
    )
    assert listed.error is None
    assert listed.result is not None
    assert listed.result["projects"] == []


def test_unknown_project_id_is_not_found_rather_than_attached() -> None:
    world = World()
    principal = operator()
    service = build_service(world, world.providers)
    refused = _invoke(
        service,
        principal,
        Capability.CONTINUITY_TASKS_CREATE,
        Purpose.CONTINUITY_AUTHORING,
        RecordTask(
            title="Missing project",
            idempotency_key="author-missing-0001",
            project_id=issue_identifier(IdKind.PROJECT),
        ),
    )
    assert refused.error is not None
    assert refused.error.code is ErrorCode.NOT_FOUND


def test_a_project_version_below_one_is_refused() -> None:
    when = datetime(2026, 9, 13, 12, tzinfo=UTC)
    with pytest.raises(ValueError, match="version"):
        Project(
            project_id="prj_aaaaaaaa11111111",
            principal_id="prn_aaaaaaaa11111111",
            name="Versioned",
            state=ProjectState.ACTIVE,
            opened_at=when,
            created_at=when,
            updated_at=when,
            version=0,
        )


def test_a_bound_link_requires_an_entity_and_an_unresolved_link_forbids_one() -> None:
    when = datetime(2026, 9, 13, 12, tzinfo=UTC)
    bound = ProjectEntityLink(
        principal_id="prn_aaaaaaaa11111111",
        project_id="prj_aaaaaaaa11111111",
        linkage_state=ProjectEntityLinkageState.BOUND,
        created_at=when,
        updated_at=when,
        project_entity_id="ent_aaaaaaaa11111111",
    )
    assert bound.project_entity_id == "ent_aaaaaaaa11111111"
    ambiguous = ProjectEntityLink(
        principal_id="prn_aaaaaaaa11111111",
        project_id="prj_bbbbbbbb22222222",
        linkage_state=ProjectEntityLinkageState.UNRESOLVED_AMBIGUOUS,
        created_at=when,
        updated_at=when,
    )
    assert ambiguous.project_entity_id is None
    with pytest.raises(ValueError, match="bound project-entity link"):
        ProjectEntityLink(
            principal_id="prn_aaaaaaaa11111111",
            project_id="prj_cccccccc33333333",
            linkage_state=ProjectEntityLinkageState.BOUND,
            created_at=when,
            updated_at=when,
        )
