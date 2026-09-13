"""User-directed continuity writes against a live PostgreSQL server.

The FAST fakes cannot see the unique reservation race, the acceptance-kind
CHECK, or SQL pulse/list hydration. This module measures those on a disposable
database created and dropped here, never the configured one. Every identifier
is synthetic.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text

from my_pa.application.commands import (
    Command,
    CreateProject,
    GetPulse,
    ListProjects,
    ReadProject,
    RecordTask,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import AuthoringConflictError, UnitOfWork
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.continuity_authoring import SqlContinuityAuthoringRepository
from my_pa.infrastructure.persistence.situation_repository import SqlProjectRepository
from my_pa.infrastructure.persistence.tables import projects
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
DISPOSABLE_DATABASE: Final = "my_pa_continuity_authoring_test"
PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
WHEN: Final = datetime(2026, 8, 15, 12, tzinfo=UTC)
LIMITS: Final = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


class _Runtime:
    def __init__(self, url: str) -> None:
        self.work_engine = create_database_engine(url)
        self.audit_engine = create_database_engine(url)
        audit = SqlAlchemyAuditSink(self.audit_engine)

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(self.work_engine, audit=audit)

        self.service = ApplicationService(unit_of_work=unit_of_work, limits=LIMITS)

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


def test_a_direct_project_and_task_are_visible_on_sql_list_and_pulse(runtime: _Runtime) -> None:
    created = runtime.invoke(
        CreateProject(name="MCP Write Acceptance Test", idempotency_key="author-db-project-0001")
    )
    assert created.error is None
    assert created.result is not None
    project_id = created.result["project_id"]
    due = datetime.now(UTC) + timedelta(hours=24)
    task = runtime.invoke(
        RecordTask(
            title="Verify ChatLLM write behavior",
            idempotency_key="author-db-task-0001",
            project_id=project_id,
            due_at=due,
        )
    )
    assert task.error is None
    assert task.result is not None
    assert task.result["acceptance_kind"] == "direct_principal"
    assert task.result["evidence_state"] == "accepted"
    listed = runtime.invoke(ListProjects())
    assert listed.error is None
    assert listed.result is not None
    assert "MCP Write Acceptance Test" in [row["name"] for row in listed.result["projects"]]
    pulse = runtime.invoke(GetPulse())
    assert pulse.error is None
    assert pulse.result is not None
    assert task.result["task_id"] in [item["item_ref"] for item in pulse.result["pulse_items"]]


def test_a_replayed_key_does_not_insert_a_second_project(
    runtime: _Runtime, migrated_engine: Engine
) -> None:
    first = runtime.invoke(
        CreateProject(name="MCP Write Acceptance Test", idempotency_key="author-db-replay-0001")
    )
    second = runtime.invoke(
        CreateProject(name="MCP Write Acceptance Test", idempotency_key="author-db-replay-0001")
    )
    assert first.error is None and second.error is None
    assert first.result is not None and second.result is not None
    assert second.result["replayed"] is True
    assert second.result["project_id"] == first.result["project_id"]
    with migrated_engine.connect() as connection:
        count = connection.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.projects")  # noqa: S608
        ).scalar_one()
        entities = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entities "  # noqa: S608
                "WHERE entity_type = 'project'"
            )
        ).scalar_one()
        links = connection.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.project_entity_links")  # noqa: S608
        ).scalar_one()
        version = connection.execute(
            text(
                f"SELECT version FROM {SCHEMA}.projects "  # noqa: S608
                "WHERE project_id = :project_id"
            ),
            {"project_id": first.result["project_id"]},
        ).scalar_one()
        link = (
            connection.execute(
                text(
                    f"SELECT linkage_state, project_entity_id "  # noqa: S608
                    f"FROM {SCHEMA}.project_entity_links "
                    "WHERE project_id = :project_id"
                ),
                {"project_id": first.result["project_id"]},
            )
            .mappings()
            .one()
        )
    assert int(count) == 1
    assert int(entities) == 1
    assert int(links) == 1
    assert int(version) == 1
    assert link["linkage_state"] == "bound"
    assert link["project_entity_id"] is not None


def test_concurrent_same_key_creates_one_project(migrated_engine: Engine) -> None:
    key = "author-db-concurrent-0001"
    digest = "same-payload-digest"
    owned: list[bool] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2, timeout=10)

    def worker() -> None:
        object_id = issue_identifier(IdKind.PROJECT)
        try:
            with migrated_engine.connect() as connection, connection.begin():
                repository = SqlContinuityAuthoringRepository(connection)
                barrier.wait()
                claimed = repository.reserve(
                    principal_id=PRINCIPAL_A,
                    idempotency_key=key,
                    capability=Capability.CONTINUITY_PROJECTS_CREATE.value,
                    payload_digest=digest,
                    object_id=object_id,
                )
                if claimed:
                    repository.author_project(
                        principal_id=PRINCIPAL_A,
                        project_id=object_id,
                        name="MCP Write Acceptance Test",
                        description=None,
                    )
                owned.append(claimed)
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert errors == []
    assert owned.count(True) == 1
    assert owned.count(False) == 1
    with migrated_engine.connect() as connection:
        projects = connection.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.projects")  # noqa: S608
        ).scalar_one()
        keys = connection.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.continuity_authoring_submissions")  # noqa: S608
        ).scalar_one()
    assert int(projects) == 1
    assert int(keys) == 1


def test_a_reused_key_with_different_content_is_a_conflict_and_inserts_nothing(
    migrated_engine: Engine,
) -> None:
    object_id = issue_identifier(IdKind.PROJECT)
    with migrated_engine.connect() as connection, connection.begin():
        repository = SqlContinuityAuthoringRepository(connection)
        assert repository.reserve(
            principal_id=PRINCIPAL_A,
            idempotency_key="author-db-conflict-0001",
            capability=Capability.CONTINUITY_PROJECTS_CREATE.value,
            payload_digest="first-digest",
            object_id=object_id,
        )
        repository.author_project(
            principal_id=PRINCIPAL_A,
            project_id=object_id,
            name="MCP Write Acceptance Test",
            description=None,
        )
    with migrated_engine.connect() as connection, connection.begin():
        repository = SqlContinuityAuthoringRepository(connection)
        with pytest.raises(AuthoringConflictError):
            repository.reserve(
                principal_id=PRINCIPAL_A,
                idempotency_key="author-db-conflict-0001",
                capability=Capability.CONTINUITY_PROJECTS_CREATE.value,
                payload_digest="second-digest",
                object_id=issue_identifier(IdKind.PROJECT),
            )
    with migrated_engine.connect() as connection:
        assert (
            int(
                connection.execute(
                    text(f"SELECT count(*) FROM {SCHEMA}.projects")  # noqa: S608
                ).scalar_one()
            )
            == 1
        )


def test_principal_b_cannot_see_principal_a_bridge(migrated_engine: Engine) -> None:
    principal_b = "prn_bbbb0002bbbb0002bbbb0002"
    object_id = issue_identifier(IdKind.PROJECT)
    with migrated_engine.connect() as connection, connection.begin():
        repository = SqlContinuityAuthoringRepository(connection)
        assert repository.reserve(
            principal_id=PRINCIPAL_A,
            idempotency_key="author-db-bridge-0001",
            capability=Capability.CONTINUITY_PROJECTS_CREATE.value,
            payload_digest="bridge-digest",
            object_id=object_id,
        )
        repository.author_project(
            principal_id=PRINCIPAL_A,
            project_id=object_id,
            name="Owner bridge",
            description=None,
        )
        projects = SqlProjectRepository(connection)
        assert projects.get_project_entity_link(PRINCIPAL_A, object_id) is not None
        assert projects.get_project_entity_link(principal_b, object_id) is None


def test_duplicate_active_project_canonical_name_fails_create(migrated_engine: Engine) -> None:
    first_id = issue_identifier(IdKind.PROJECT)
    second_id = issue_identifier(IdKind.PROJECT)
    with migrated_engine.connect() as connection, connection.begin():
        repository = SqlContinuityAuthoringRepository(connection)
        assert repository.reserve(
            principal_id=PRINCIPAL_A,
            idempotency_key="author-db-dup-0001",
            capability=Capability.CONTINUITY_PROJECTS_CREATE.value,
            payload_digest="dup-digest-1",
            object_id=first_id,
        )
        repository.author_project(
            principal_id=PRINCIPAL_A,
            project_id=first_id,
            name="Duplicate Name",
            description=None,
        )
        assert repository.reserve(
            principal_id=PRINCIPAL_A,
            idempotency_key="author-db-dup-0002",
            capability=Capability.CONTINUITY_PROJECTS_CREATE.value,
            payload_digest="dup-digest-2",
            object_id=second_id,
        )
        with pytest.raises(ValueError, match="canonical name is already held"):
            repository.author_project(
                principal_id=PRINCIPAL_A,
                project_id=second_id,
                name="Duplicate Name",
                description=None,
            )


def test_sql_read_collapses_missing_and_cross_principal(runtime: _Runtime) -> None:
    created = runtime.invoke(
        CreateProject(name="Owner visible", idempotency_key="author-db-read-0001")
    )
    assert created.error is None and created.result is not None
    owned = runtime.invoke(ReadProject(project_id=created.result["project_id"]))
    assert owned.error is None and owned.result is not None
    assert owned.result["project_id"] == created.result["project_id"]
    assert owned.result["version"] == 1
    assert "project_entity_id" not in owned.result
    missing = runtime.invoke(ReadProject(project_id=issue_identifier(IdKind.PROJECT)))
    foreign = runtime.invoke(
        ReadProject(project_id=created.result["project_id"]),
        principal_id="prn_bbbb0002bbbb0002bbbb0002",
    )
    assert missing.error is not None and foreign.error is not None
    assert missing.error.code == foreign.error.code
    assert missing.error.code.value == "not_found"


def test_sql_list_keyset_does_not_skip_or_duplicate_on_tied_created_at(
    migrated_engine: Engine,
) -> None:
    when = datetime(2026, 9, 13, 12, tzinfo=UTC)
    ids = sorted(issue_identifier(IdKind.PROJECT) for _ in range(3))
    with migrated_engine.connect() as connection, connection.begin():
        for index, project_id in enumerate(ids):
            connection.execute(
                projects.insert().values(
                    project_id=project_id,
                    principal_id=PRINCIPAL_A,
                    name=f"Keyset {index}",
                    description=None,
                    state="active",
                    participants=[],
                    opened_at=when,
                    closed_at=None,
                    created_at=when,
                    updated_at=when,
                    version=1,
                )
            )
        repository = SqlProjectRepository(connection)
        first = repository.list_projects(PRINCIPAL_A, limit=2)
        assert [row.project_id for row in first] == [ids[2], ids[1]]
        rest = repository.list_projects(PRINCIPAL_A, after=ids[1], limit=2)
        assert [row.project_id for row in rest] == [ids[0]]
        escaped = repository.list_projects(PRINCIPAL_A, query="Keyset %", limit=10)
        assert escaped == ()
        named = repository.list_projects(PRINCIPAL_A, exact_name="Keyset 1", limit=10)
        assert [row.project_id for row in named] == [ids[1]]
