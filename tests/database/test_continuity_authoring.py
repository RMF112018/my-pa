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
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.application.commands import Command, CreateProject, RecordTask, GetPulse, ListProjects
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
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


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    try:
        _administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        yield url
    finally:
        _administer(drop)
        maintenance.dispose()


@pytest.fixture
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


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
    command.upgrade(_config(), "head")
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
    assert int(count) == 1


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
