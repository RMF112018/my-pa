"""Project-context participation against a live PostgreSQL server (WP-MCP-PROJ-04)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Final

import pytest
from sqlalchemy import text

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
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.relationship.entity import (
    EntityProjectParticipationState,
    EntityType,
    ParticipationStatusCode,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

SCHEMA: Final = "knowledge"
PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
WHEN: Final = datetime(2026, 9, 13, 12, tzinfo=UTC)
ROLE_OF_RECORD: Final = "ARCHITECT_OF_RECORD"
LIMITS: Final = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)


class _Runtime:
    def __init__(self, url: str) -> None:
        self.work_engine = create_database_engine(url)
        self.audit_engine = create_database_engine(url)
        audit = SqlAlchemyAuditSink(self.audit_engine)

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(self.work_engine, audit=audit)

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            relationship_intelligence_enabled=True,
            relationship_intelligence_writes_enabled=True,
        )

    def close(self) -> None:
        self.work_engine.dispose()
        self.audit_engine.dispose()

    def invoke(
        self, command_value: Command, *, principal_id: str = PRINCIPAL_A
    ) -> ResponseEnvelope:
        capability = command_value.capability
        permitted = permitted_purposes(capability)
        purpose = (
            Purpose.CONTINUITY_AUTHORING
            if Purpose.CONTINUITY_AUTHORING in permitted
            else sorted(permitted)[0]
        )
        return self.service.invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=capability,
                purpose=purpose,
                principal_id=principal_id,
                requested_at=WHEN,
            ),
            command_value,
            principal=Principal(
                principal_id=principal_id, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
        )


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[_Runtime]:
    composed = _Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _participation(
    *,
    participant_entity_id: str,
    key: str,
    project_id: str | None = None,
    project_entity_id: str | None = None,
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
        role_code=ROLE_OF_RECORD,
    )


def _person_and_project(runtime: _Runtime, *, suffix: str) -> tuple[str, str]:
    person = runtime.invoke(
        CreateEntity(
            entity_type=EntityType.PERSON,
            display_name=f"Pat Synthetic {suffix}",
            idempotency_key=f"db-person-{suffix}",
        )
    )
    assert person.error is None and person.result is not None
    project = runtime.invoke(
        CreateProject(name=f"Harbour Tower {suffix}", idempotency_key=f"db-project-{suffix}")
    )
    assert project.error is None and project.result is not None
    return str(person.result["entity_id"]), str(project.result["project_id"])


def test_bound_project_create_list_revise_end_and_keeps_jsonb_echo(runtime: _Runtime) -> None:
    person_id, project_id = _person_and_project(runtime, suffix="lifecycle")
    created = runtime.invoke(
        _participation(participant_entity_id=person_id, project_id=project_id, key="db-create")
    )
    assert created.error is None, created.error
    listed = runtime.invoke(ListEntityParticipations(project_id=project_id))
    assert listed.error is None and listed.result is not None
    assert listed.result["perspective"] == "project"
    rows = listed.result["participations"]
    assert len(rows) == 1
    row = rows[0]
    read = runtime.invoke(ReadProject(project_id=project_id))
    assert read.error is None and read.result is not None
    assert read.result["participants"] == []
    assert "project_entity_id" not in read.result
    assert len(read.result["canonical_participations"]) == 1
    assert read.result["canonical_participations"][0]["participant_entity_id"] == person_id
    revised = runtime.invoke(
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
            idempotency_key="db-revise",
            role_code=ROLE_OF_RECORD,
        )
    )
    assert revised.error is None and revised.result is not None
    ended = runtime.invoke(
        EndEntityParticipation(
            participation_id=revised.result["record_id"],
            expected_version=revised.result["version"],
            idempotency_key="db-end",
        )
    )
    assert ended.error is None, ended.error
    with runtime.work_engine.connect() as connection:
        states = [
            held[0]
            for held in connection.execute(
                text(
                    f"SELECT state FROM {SCHEMA}.entity_project_participations "  # noqa: S608
                    "WHERE principal_id = :principal_id"
                ),
                {"principal_id": PRINCIPAL_A},
            )
        ]
        participants = connection.execute(
            text(
                f"SELECT participants FROM {SCHEMA}.projects WHERE project_id = :project_id"  # noqa: S608
            ),
            {"project_id": project_id},
        ).scalar_one()
    assert EntityProjectParticipationState.SUPERSEDED.value in states
    assert EntityProjectParticipationState.RETIRED.value in states
    assert EntityProjectParticipationState.ACTIVE.value not in states
    assert list(participants) == []
    after_end = runtime.invoke(ReadProject(project_id=project_id))
    assert after_end.error is None and after_end.result is not None
    assert after_end.result["participants"] == []
    assert after_end.result["canonical_participations"] == []


def test_duplicate_active_same_role_is_conflict(runtime: _Runtime) -> None:
    person_id, project_id = _person_and_project(runtime, suffix="dup")
    first = runtime.invoke(
        _participation(participant_entity_id=person_id, project_id=project_id, key="db-dup-1")
    )
    assert first.error is None, first.error
    second = runtime.invoke(
        _participation(participant_entity_id=person_id, project_id=project_id, key="db-dup-2")
    )
    assert second.error is not None
    assert second.error.code is ErrorCode.CONFLICT
    with runtime.work_engine.connect() as connection:
        count = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entity_project_participations "  # noqa: S608
                "WHERE principal_id = :principal_id"
            ),
            {"principal_id": PRINCIPAL_A},
        ).scalar_one()
    assert count == 1


def test_cross_principal_project_id_matches_read_project_not_found(runtime: _Runtime) -> None:
    person_id, project_id = _person_and_project(runtime, suffix="iso")
    missing_read = runtime.invoke(ReadProject(project_id=project_id), principal_id=PRINCIPAL_B)
    missing_create = runtime.invoke(
        _participation(participant_entity_id=person_id, project_id=project_id, key="db-foreign"),
        principal_id=PRINCIPAL_B,
    )
    assert missing_read.error is not None and missing_create.error is not None
    assert missing_read.error.code is ErrorCode.NOT_FOUND
    assert missing_create.error.code is ErrorCode.NOT_FOUND
    assert missing_read.error.safe_details == missing_create.error.safe_details
    assert project_id not in str(missing_create.error)


def test_unresolved_bridge_is_conflict_and_does_not_mint(runtime: _Runtime) -> None:
    person_id, project_id = _person_and_project(runtime, suffix="unresolved")
    with runtime.work_engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.project_entity_links "  # noqa: S608
                "SET linkage_state = 'unresolved_missing', project_entity_id = NULL "
                "WHERE principal_id = :principal_id AND project_id = :project_id"
            ),
            {"principal_id": PRINCIPAL_A, "project_id": project_id},
        )
        before = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entities WHERE principal_id = :principal_id"  # noqa: S608
            ),
            {"principal_id": PRINCIPAL_A},
        ).scalar_one()
    created = runtime.invoke(
        _participation(participant_entity_id=person_id, project_id=project_id, key="db-unresolved")
    )
    assert created.error is not None
    assert created.error.code is ErrorCode.CONFLICT
    assert created.error.safe_details == ("project_id",)
    with runtime.work_engine.connect() as connection:
        after = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entities WHERE principal_id = :principal_id"  # noqa: S608
            ),
            {"principal_id": PRINCIPAL_A},
        ).scalar_one()
        participations = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entity_project_participations "  # noqa: S608
                "WHERE principal_id = :principal_id"
            ),
            {"principal_id": PRINCIPAL_A},
        ).scalar_one()
        participants = connection.execute(
            text(
                f"SELECT participants FROM {SCHEMA}.projects WHERE project_id = :project_id"  # noqa: S608
            ),
            {"project_id": project_id},
        ).scalar_one()
        linkage = connection.execute(
            text(
                f"SELECT linkage_state FROM {SCHEMA}.project_entity_links "  # noqa: S608
                "WHERE project_id = :project_id"
            ),
            {"project_id": project_id},
        ).scalar_one()
    assert after == before
    assert participations == 0
    assert list(participants) == []
    assert linkage == "unresolved_missing"
