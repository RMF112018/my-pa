"""Reassign and filter Task Project membership against PostgreSQL (WP-MCP-PROJ-05)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Final

import pytest

from my_pa.application.commands import (
    Command,
    CreateProject,
    ListTasks,
    ReadTask,
    RecordTask,
    UpdateTask,
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
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
WHEN: Final = datetime(2026, 9, 13, 12, tzinfo=UTC)
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
            task_management_unit_of_work=lambda: SqlAlchemyTaskManagementUnitOfWork(
                self.work_engine
            ),
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


def _project(runtime: _Runtime, *, name: str, key: str, principal_id: str = PRINCIPAL_A) -> str:
    created = runtime.invoke(
        CreateProject(name=name, idempotency_key=key), principal_id=principal_id
    )
    assert created.error is None and created.result is not None
    return str(created.result["project_id"])


def _task(
    runtime: _Runtime,
    *,
    title: str,
    key: str,
    project_id: str | None,
    principal_id: str = PRINCIPAL_A,
) -> dict[str, object]:
    created = runtime.invoke(
        RecordTask(title=title, idempotency_key=key, project_id=project_id),
        principal_id=principal_id,
    )
    assert created.error is None and created.result is not None
    return created.result


def test_sql_create_read_reassign_clear_and_list_by_project(runtime: _Runtime) -> None:
    harbour = _project(runtime, name="SQL Harbour", key="proj-05-db-harbour")
    quay = _project(runtime, name="SQL Quay", key="proj-05-db-quay")
    attached = _task(
        runtime, title="Check the pour", key="proj-05-db-task-harbour", project_id=harbour
    )
    other = _task(runtime, title="Walk the quay", key="proj-05-db-task-quay", project_id=quay)
    read = runtime.invoke(ReadTask(task_id=str(attached["task_id"])))
    assert read.error is None and read.result is not None
    assert read.result["task"]["project_id"] == harbour
    unscoped = runtime.invoke(ListTasks())
    assert unscoped.error is None and unscoped.result is not None
    by_id = {row["task_id"]: row for row in unscoped.result["tasks"]}
    assert set(by_id) == {attached["task_id"], other["task_id"]}
    assert by_id[str(attached["task_id"])]["project_id"] == harbour
    reassigned = runtime.invoke(
        UpdateTask(
            task_id=str(attached["task_id"]),
            expected_version=int(read.result["task"]["version"]),
            idempotency_key="proj-05-db-reassign",
            project_id=quay,
        )
    )
    assert reassigned.error is None and reassigned.result is not None
    assert reassigned.result["task"]["project_id"] == quay
    scoped = runtime.invoke(ListTasks(project_id=quay))
    assert scoped.error is None and scoped.result is not None
    assert {row["task_id"] for row in scoped.result["tasks"]} == {
        attached["task_id"],
        other["task_id"],
    }
    cleared = runtime.invoke(
        UpdateTask(
            task_id=str(attached["task_id"]),
            expected_version=int(reassigned.result["task"]["version"]),
            idempotency_key="proj-05-db-clear",
            clear_project=True,
        )
    )
    assert cleared.error is None and cleared.result is not None
    assert cleared.result["task"]["project_id"] is None
    after_clear = runtime.invoke(ListTasks(project_id=quay))
    assert after_clear.error is None and after_clear.result is not None
    assert [row["task_id"] for row in after_clear.result["tasks"]] == [other["task_id"]]
    still_unscoped = runtime.invoke(ListTasks())
    assert still_unscoped.error is None and still_unscoped.result is not None
    assert {row["task_id"] for row in still_unscoped.result["tasks"]} == {
        attached["task_id"],
        other["task_id"],
    }


def test_sql_stale_project_update_still_conflicts(runtime: _Runtime) -> None:
    harbour = _project(runtime, name="SQL Stale Harbour", key="proj-05-db-stale-project")
    quay = _project(runtime, name="SQL Stale Quay", key="proj-05-db-stale-quay")
    attached = _task(
        runtime, title="SQL stale pour", key="proj-05-db-stale-task", project_id=harbour
    )
    first = runtime.invoke(
        UpdateTask(
            task_id=str(attached["task_id"]),
            expected_version=1,
            idempotency_key="proj-05-db-stale-first",
            project_id=quay,
        )
    )
    assert first.error is None and first.result is not None
    stale = runtime.invoke(
        UpdateTask(
            task_id=str(attached["task_id"]),
            expected_version=1,
            idempotency_key="proj-05-db-stale-second",
            clear_project=True,
        )
    )
    assert stale.error is not None
    assert stale.error.code is ErrorCode.CONFLICT
    held = runtime.invoke(ReadTask(task_id=str(attached["task_id"])))
    assert held.error is None and held.result is not None
    assert held.result["task"]["project_id"] == quay
    assert held.result["task"]["version"] == 2


def test_sql_cross_principal_target_project_matches_missing_not_found(runtime: _Runtime) -> None:
    harbour = _project(runtime, name="SQL Owner Harbour", key="proj-05-db-owner-project")
    attached = _task(
        runtime, title="SQL owner pour", key="proj-05-db-owner-task", project_id=harbour
    )
    foreign = _project(
        runtime,
        name="SQL Foreign Harbour",
        key="proj-05-db-foreign-project",
        principal_id=PRINCIPAL_B,
    )
    missing_id = issue_identifier(IdKind.PROJECT)
    missing = runtime.invoke(
        UpdateTask(
            task_id=str(attached["task_id"]),
            expected_version=1,
            idempotency_key="proj-05-db-missing-project",
            project_id=missing_id,
        )
    )
    foreign_target = runtime.invoke(
        UpdateTask(
            task_id=str(attached["task_id"]),
            expected_version=1,
            idempotency_key="proj-05-db-foreign-project-target",
            project_id=foreign,
        )
    )
    assert missing.error is not None and foreign_target.error is not None
    assert missing.error.code is ErrorCode.NOT_FOUND
    assert foreign_target.error.code is ErrorCode.NOT_FOUND
    assert missing.error.safe_details == foreign_target.error.safe_details == ("project_id",)
    held = runtime.invoke(ReadTask(task_id=str(attached["task_id"])))
    assert held.error is None and held.result is not None
    assert held.result["task"]["project_id"] == harbour
