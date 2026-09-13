"""Project-context participation through the existing RI plane (WP-MCP-PROJ-04)."""

from __future__ import annotations

import pytest

from my_pa.application.commands import (
    Command,
    CreateEntity,
    CreateEntityParticipation,
    CreateProject,
    EndEntityParticipation,
    ListEntityParticipations,
    ReadProject,
    ReviseEntityParticipation,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.relationship.entity import (
    EntityProjectParticipationState,
    EntityType,
    ParticipationStatusCode,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
)
from my_pa.domain.situation.situation import (
    Project,
    ProjectEntityLink,
    ProjectEntityLinkageState,
    ProjectState,
)
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import WHEN, Scene, build_service, metadata_for, operator

ROLE_OF_RECORD: str = "ARCHITECT_OF_RECORD"


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


def _participation(
    *,
    participant_entity_id: str,
    key: str,
    project_id: str | None = None,
    project_entity_id: str | None = None,
    role_code: str | None = ROLE_OF_RECORD,
    project_display_name: str = "Pat on Harbour",
) -> CreateEntityParticipation:
    return CreateEntityParticipation(
        participant_entity_id=participant_entity_id,
        project_display_name=project_display_name,
        role_basis_code=RoleBasisCode.CONTRACTUAL,
        stakeholder_side_code=StakeholderSideCode.DESIGN,
        stakeholder_class_code=StakeholderClassCode.CORE,
        relationship_status_code=ParticipationStatusCode.ACTIVE,
        idempotency_key=key,
        project_entity_id=project_entity_id,
        project_id=project_id,
        role_code=role_code,
    )


def _person_and_project(scene: Scene) -> tuple[ApplicationService, str, str]:
    service = build_service(scene.world, scene.providers)
    person = _invoke(
        service,
        scene.principal,
        CreateEntity(
            entity_type=EntityType.PERSON,
            display_name="Pat Synthetic",
            idempotency_key="proj-04-person-0001",
        ),
    )
    assert person.error is None and person.result is not None
    project = _invoke(
        service,
        scene.principal,
        CreateProject(name="Harbour Tower", idempotency_key="proj-04-project-0001"),
    )
    assert project.error is None and project.result is not None
    return service, str(person.result["entity_id"]), str(project.result["project_id"])


def test_create_requires_exactly_one_project_selector() -> None:
    person = issue_identifier(IdKind.ENTITY)
    with pytest.raises(InvalidRequestError) as neither:
        _participation(participant_entity_id=person, key="neither")
    assert neither.value.safe_details == (SafeDetail.SELECTOR,)
    with pytest.raises(InvalidRequestError) as both:
        _participation(
            participant_entity_id=person,
            key="both",
            project_id=issue_identifier(IdKind.PROJECT),
            project_entity_id=issue_identifier(IdKind.ENTITY),
        )
    assert both.value.safe_details == (SafeDetail.SELECTOR,)


def test_list_requires_exactly_one_selector_and_project_form_is_project_end() -> None:
    with pytest.raises(InvalidRequestError) as neither:
        ListEntityParticipations()
    assert neither.value.safe_details == (SafeDetail.SELECTOR,)
    with pytest.raises(InvalidRequestError) as both:
        ListEntityParticipations(
            entity_id=issue_identifier(IdKind.ENTITY),
            project_id=issue_identifier(IdKind.PROJECT),
        )
    assert both.value.safe_details == (SafeDetail.SELECTOR,)
    with pytest.raises(InvalidRequestError) as participant:
        ListEntityParticipations(
            project_id=issue_identifier(IdKind.PROJECT),
            perspective="participant",
        )
    assert participant.value.safe_details == (SafeDetail.SELECTOR,)
    ListEntityParticipations(project_id=issue_identifier(IdKind.PROJECT))
    ListEntityParticipations(project_id=issue_identifier(IdKind.PROJECT), perspective="project")


def test_bound_project_create_list_revise_end_via_project_id(scene: Scene) -> None:
    service, person_id, project_id = _person_and_project(scene)
    created = _invoke(
        service,
        scene.principal,
        _participation(participant_entity_id=person_id, project_id=project_id, key="create"),
    )
    assert created.error is None and created.result is not None
    listed = _invoke(
        service,
        scene.principal,
        ListEntityParticipations(project_id=project_id),
    )
    assert listed.error is None and listed.result is not None
    assert listed.result["perspective"] == "project"
    rows = listed.result["participations"]
    assert len(rows) == 1
    row = rows[0]
    assert row["participant_entity_id"] == person_id
    assert row["role_code"] == ROLE_OF_RECORD
    assert row["state"] == EntityProjectParticipationState.ACTIVE.value
    from_participant = _invoke(
        service,
        scene.principal,
        ListEntityParticipations(entity_id=person_id, perspective="participant"),
    )
    assert from_participant.error is None and from_participant.result is not None
    assert len(from_participant.result["participations"]) == 1
    revised = _invoke(
        service,
        scene.principal,
        ReviseEntityParticipation(
            participation_id=row["participation_id"],
            expected_version=row["version"],
            project_entity_id=row["project_entity_id"],
            participant_entity_id=person_id,
            project_display_name="Pat on Harbour, corrected",
            role_basis_code=RoleBasisCode.CONTRACTUAL,
            stakeholder_side_code=StakeholderSideCode.DESIGN,
            stakeholder_class_code=StakeholderClassCode.CORE,
            relationship_status_code=ParticipationStatusCode.ACTIVE,
            idempotency_key="revise",
            role_code=ROLE_OF_RECORD,
        ),
    )
    assert revised.error is None and revised.result is not None
    ended = _invoke(
        service,
        scene.principal,
        EndEntityParticipation(
            participation_id=revised.result["record_id"],
            expected_version=revised.result["version"],
            idempotency_key="end",
        ),
    )
    assert ended.error is None
    states = {held.state for held in scene.world.entity_project_participations}
    assert EntityProjectParticipationState.SUPERSEDED in states
    assert EntityProjectParticipationState.RETIRED in states
    assert EntityProjectParticipationState.ACTIVE not in states


def test_duplicate_active_same_role_is_conflict(scene: Scene) -> None:
    service, person_id, project_id = _person_and_project(scene)
    first = _invoke(
        service,
        scene.principal,
        _participation(participant_entity_id=person_id, project_id=project_id, key="dup-1"),
    )
    assert first.error is None
    second = _invoke(
        service,
        scene.principal,
        _participation(participant_entity_id=person_id, project_id=project_id, key="dup-2"),
    )
    assert second.error is not None
    assert second.error.code is ErrorCode.CONFLICT
    assert len(scene.world.entity_project_participations) == 1


def test_cross_principal_project_id_matches_read_project_not_found(scene: Scene) -> None:
    service, person_id, project_id = _person_and_project(scene)
    stranger = operator()
    missing_read = _invoke(service, stranger, ReadProject(project_id=project_id))
    missing_create = _invoke(
        service,
        stranger,
        _participation(participant_entity_id=person_id, project_id=project_id, key="foreign"),
    )
    assert missing_read.error is not None and missing_create.error is not None
    assert missing_read.error.code is ErrorCode.NOT_FOUND
    assert missing_create.error.code is ErrorCode.NOT_FOUND
    assert missing_read.error.safe_details == missing_create.error.safe_details
    assert project_id not in str(missing_create.error)


def test_cross_principal_participant_is_not_found(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    stranger = operator()
    foreign_person = _invoke(
        service,
        stranger,
        CreateEntity(
            entity_type=EntityType.PERSON,
            display_name="Foreign Participant",
            idempotency_key="foreign-person",
        ),
    )
    assert foreign_person.error is None and foreign_person.result is not None
    project = _invoke(
        service,
        scene.principal,
        CreateProject(name="Owner Tower", idempotency_key="owner-project"),
    )
    assert project.error is None and project.result is not None
    created = _invoke(
        service,
        scene.principal,
        _participation(
            participant_entity_id=str(foreign_person.result["entity_id"]),
            project_id=str(project.result["project_id"]),
            key="foreign-participant",
        ),
    )
    assert created.error is not None
    assert created.error.code is ErrorCode.NOT_FOUND
    assert str(foreign_person.result["entity_id"]) not in str(created.error)


def test_unresolved_bridge_is_conflict_and_does_not_mint(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    person = _invoke(
        service,
        scene.principal,
        CreateEntity(
            entity_type=EntityType.PERSON,
            display_name="Pat Synthetic",
            idempotency_key="unresolved-person",
        ),
    )
    assert person.error is None and person.result is not None
    project_id = issue_identifier(IdKind.PROJECT)
    scene.world.projects.append(
        Project(
            project_id=project_id,
            principal_id=scene.principal.principal_id,
            name="Unresolved Harbour",
            state=ProjectState.ACTIVE,
            opened_at=WHEN,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    scene.world.project_entity_links.append(
        ProjectEntityLink(
            principal_id=scene.principal.principal_id,
            project_id=project_id,
            linkage_state=ProjectEntityLinkageState.UNRESOLVED_MISSING,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    before = len(scene.world.entities)
    created = _invoke(
        service,
        scene.principal,
        _participation(
            participant_entity_id=str(person.result["entity_id"]),
            project_id=project_id,
            key="unresolved-create",
        ),
    )
    assert created.error is not None
    assert created.error.code is ErrorCode.CONFLICT
    assert created.error.safe_details == (SafeDetail.PROJECT_ID.value,)
    assert len(scene.world.entities) == before
    assert scene.world.entity_project_participations == []
    assert scene.world.project_entity_links[0].linkage_state is (
        ProjectEntityLinkageState.UNRESOLVED_MISSING
    )


def test_name_matching_does_not_bind_an_unresolved_project(scene: Scene) -> None:
    service, person_id, bound_id = _person_and_project(scene)
    unresolved_id = issue_identifier(IdKind.PROJECT)
    scene.world.projects.append(
        Project(
            project_id=unresolved_id,
            principal_id=scene.principal.principal_id,
            name="Harbour Tower",
            state=ProjectState.ACTIVE,
            opened_at=WHEN,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    scene.world.project_entity_links.append(
        ProjectEntityLink(
            principal_id=scene.principal.principal_id,
            project_id=unresolved_id,
            linkage_state=ProjectEntityLinkageState.UNRESOLVED_MISSING,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    before = len(scene.world.entities)
    created = _invoke(
        service,
        scene.principal,
        _participation(
            participant_entity_id=person_id,
            project_id=unresolved_id,
            key="name-match",
        ),
    )
    assert created.error is not None
    assert created.error.code is ErrorCode.CONFLICT
    assert len(scene.world.entities) == before
    assert scene.world.entity_project_participations == []
    bound = _invoke(service, scene.principal, ReadProject(project_id=bound_id))
    assert bound.error is None and bound.result is not None
    assert bound.result["canonical_participations"] == []


def test_project_payload_keeps_json_echo_and_projects_canonical_summary(
    scene: Scene,
) -> None:
    service, person_id, project_id = _person_and_project(scene)
    empty = _invoke(service, scene.principal, ReadProject(project_id=project_id))
    assert empty.error is None and empty.result is not None
    assert empty.result["participants"] == []
    assert empty.result["canonical_participations"] == []
    assert "project_entity_id" not in empty.result
    created = _invoke(
        service,
        scene.principal,
        _participation(participant_entity_id=person_id, project_id=project_id, key="summary"),
    )
    assert created.error is None
    read = _invoke(service, scene.principal, ReadProject(project_id=project_id))
    assert read.error is None and read.result is not None
    assert read.result["participants"] == []
    assert "project_entity_id" not in read.result
    summaries = read.result["canonical_participations"]
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["participant_entity_id"] == person_id
    assert summary["role_code"] == ROLE_OF_RECORD
    assert summary["relationship_status_code"] == ParticipationStatusCode.ACTIVE.value
    assert summary["state"] == EntityProjectParticipationState.ACTIVE.value
    assert "project_entity_id" not in summary
    assert set(summary) == {
        "participant_entity_id",
        "role_code",
        "relationship_status_code",
        "participation_id",
        "state",
    }


def test_direct_non_project_entity_is_not_found(scene: Scene) -> None:
    service, person_id, _project_id = _person_and_project(scene)
    created = _invoke(
        service,
        scene.principal,
        _participation(
            participant_entity_id=person_id,
            project_entity_id=person_id,
            key="person-as-project",
        ),
    )
    assert created.error is not None
    assert created.error.code is ErrorCode.NOT_FOUND
    assert created.error.safe_details == (SafeDetail.PROJECT_ENTITY_ID.value,)
    assert scene.world.entity_project_participations == []
