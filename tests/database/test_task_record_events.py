"""WP-RE-02: Task Record Events on a real database (RE-AC-018..023, T-16).

Marked `database` (auto `database_clone`) and routed to `database-current-head`.
Every write goes through `ApplicationService.invoke` on the production SQL units
of work, so what is checked is the committed feed row next to the committed
Task and history rows:

* **RE-AC-018** -- `tasks.create` and `continuity.tasks.create` each commit one
  `created` event; the continuity path names the OPENED lifecycle event as its
  receipt (G1-TX-003).
* **RE-AC-019 / 020** -- an APPLIED `tasks.update` commits one `updated` event,
  an APPLIED `tasks.transition` one `state_changed` event.
* **RE-AC-021..023 / T-16** -- a replay, a no-op and a committed stale-version
  REJECTED receipt commit zero events and advance no sequence.
* The standalone Task unit of work (U2) follows the same rule.

This module also holds the small harness the other WP-RE-02 database modules
import. Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, select

from my_pa.application.commands import (
    Command,
    CreateTask,
    RecordTask,
    TransitionTask,
    UpdateTask,
)
from my_pa.application.service import ApplicationService
from my_pa.application.tasks import TaskManagementService
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.history import TaskMutationActor
from my_pa.domain.task.lifecycle import TaskLifecycleState, TaskOriginKind
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.commitment_management import (
    SqlAlchemyCommitmentManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.tables import (
    continuity_lifecycle_events,
    record_event_sequences,
    record_events,
    task_history,
    tasks,
)
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

PRINCIPAL_A: Final = "prn_rcevwp02aaaa0001"
WHEN: Final = datetime(2026, 9, 29, 12, tzinfo=UTC)
LIMITS: Final = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)


class Runtime:
    """`ApplicationService` over the production SQL units of work."""

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
            commitment_management_unit_of_work=lambda: SqlAlchemyCommitmentManagementUnitOfWork(
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

    def ok(self, command_value: Command, *, principal_id: str = PRINCIPAL_A) -> dict[str, Any]:
        response = self.invoke(command_value, principal_id=principal_id)
        assert response.error is None, response.error
        assert response.result is not None
        return response.result


def feed(engine: Engine, principal_id: str = PRINCIPAL_A) -> list[dict[str, Any]]:
    """The committed feed of one Principal, in sequence order."""
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                select(record_events)
                .where(record_events.c.principal_id == principal_id)
                .order_by(record_events.c.sequence_number)
            ).mappings()
        ]


def next_sequence(engine: Engine, principal_id: str = PRINCIPAL_A) -> int | None:
    with engine.connect() as connection:
        return connection.execute(
            select(record_event_sequences.c.next_sequence).where(
                record_event_sequences.c.principal_id == principal_id
            )
        ).scalar_one_or_none()


def assert_gap_free(engine: Engine, principal_id: str = PRINCIPAL_A) -> None:
    events = feed(engine, principal_id)
    assert [event["sequence_number"] for event in events] == list(range(1, len(events) + 1))
    assert next_sequence(engine, principal_id) == (len(events) + 1 if events else None)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[Runtime]:
    composed = Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _history(engine: Engine, history_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        return dict(
            connection.execute(select(task_history).where(task_history.c.history_id == history_id))
            .mappings()
            .one()
        )


def _create(runtime: Runtime, key: str, **extra: object) -> dict[str, Any]:
    return runtime.ok(
        CreateTask(
            title="Synthetic task",
            idempotency_key=key,
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
            **extra,  # type: ignore[arg-type]
        )
    )


# ---- RE-AC-018 --------------------------------------------------------------


def test_tasks_create_commits_one_created_event(runtime: Runtime) -> None:
    created = _create(runtime, "wp02-task-create-0001")
    (event,) = feed(runtime.work_engine)
    assert event["record_family"] == "task"
    assert event["record_id"] == created["task"]["task_id"]
    assert event["event_kind"] == "created"
    assert event["record_version"] == 1
    assert event["source_capability"] == "tasks.create"
    assert event["source_receipt_id"] == created["history"]["history_id"]
    assert event["actor_class"] == "principal"
    assert event["classification"] == "private_local"
    assert event["correlation_id"].startswith("corr_")
    assert "title" in event["changed_fields"]
    assert_gap_free(runtime.work_engine)


def test_continuity_tasks_create_commits_one_created_event_naming_the_opened_event(
    runtime: Runtime,
) -> None:
    created = runtime.ok(RecordTask(title="Continuity task", idempotency_key="wp02-rec-0001"))
    (event,) = feed(runtime.work_engine)
    assert event["record_id"] == created["task_id"]
    assert event["event_kind"] == "created"
    assert event["source_capability"] == "continuity.tasks.create"
    with runtime.work_engine.connect() as connection:
        opened = connection.execute(
            select(continuity_lifecycle_events.c.event_id).where(
                continuity_lifecycle_events.c.object_id == created["task_id"],
                continuity_lifecycle_events.c.transition == "opened",
            )
        ).scalar_one()
        version = connection.execute(
            select(tasks.c.version).where(tasks.c.task_id == created["task_id"])
        ).scalar_one()
    assert event["source_receipt_id"] == opened
    assert event["record_version"] == version == 1
    assert event["changed_fields"] == [
        "acceptance_kind",
        "evidence_state",
        "lifecycle_state",
        "opened_at",
        "origin_kind",
        "title",
    ]


# ---- RE-AC-019 / 020 --------------------------------------------------------


def test_an_applied_update_commits_one_updated_event(runtime: Runtime) -> None:
    created = _create(runtime, "wp02-task-upd-0001")
    task_id = created["task"]["task_id"]
    updated = runtime.ok(
        UpdateTask(
            task_id=task_id,
            expected_version=1,
            idempotency_key="wp02-task-upd-0002",
            title="Renamed",
        )
    )
    events = feed(runtime.work_engine)
    assert len(events) == 2
    event = events[1]
    assert event["event_kind"] == "updated"
    assert event["changed_fields"] == ["title"]
    assert event["record_version"] == 2
    assert event["source_capability"] == "tasks.update"
    assert event["source_receipt_id"] == updated["history"]["history_id"]
    assert _history(runtime.work_engine, event["source_receipt_id"])["outcome"] == "applied"


def test_an_applied_transition_commits_one_state_changed_event(runtime: Runtime) -> None:
    created = _create(runtime, "wp02-task-tr-0001")
    runtime.ok(
        TransitionTask(
            task_id=created["task"]["task_id"],
            to_state=TaskLifecycleState.COMPLETED,
            expected_version=1,
            idempotency_key="wp02-task-tr-0002",
        )
    )
    event = feed(runtime.work_engine)[-1]
    assert event["event_kind"] == "state_changed"
    assert event["changed_fields"] == ["closed_at", "closure_evidence_ref", "lifecycle_state"]
    assert event["source_capability"] == "tasks.transition"
    assert_gap_free(runtime.work_engine)


# ---- RE-AC-021..023 / T-16 --------------------------------------------------


def test_a_replay_commits_no_event_and_no_advance(runtime: Runtime) -> None:
    _create(runtime, "wp02-task-rep-0001")
    before = (feed(runtime.work_engine), next_sequence(runtime.work_engine))
    replay = _create(runtime, "wp02-task-rep-0001")
    assert replay["replayed"] is True
    assert (feed(runtime.work_engine), next_sequence(runtime.work_engine)) == before


def test_a_no_op_commits_no_event_and_no_advance(runtime: Runtime) -> None:
    created = _create(runtime, "wp02-task-noop-0001")
    before = (feed(runtime.work_engine), next_sequence(runtime.work_engine))
    same = runtime.ok(
        UpdateTask(
            task_id=created["task"]["task_id"],
            expected_version=1,
            idempotency_key="wp02-task-noop-0002",
            title="Synthetic task",
        )
    )
    assert same["history"]["outcome"] == "no_op"
    assert (feed(runtime.work_engine), next_sequence(runtime.work_engine)) == before


@pytest.mark.parametrize("capability", ["update", "transition"])
def test_a_committed_rejection_commits_no_event_and_no_advance(
    runtime: Runtime, capability: str
) -> None:
    created = _create(runtime, f"wp02-task-rej-{capability}-0001")
    task_id = created["task"]["task_id"]
    before = (feed(runtime.work_engine), next_sequence(runtime.work_engine))
    stale: Command = (
        UpdateTask(
            task_id=task_id,
            expected_version=5,
            idempotency_key=f"wp02-task-rej-{capability}-0002",
            title="Too late",
        )
        if capability == "update"
        else TransitionTask(
            task_id=task_id,
            to_state=TaskLifecycleState.IN_PROGRESS,
            expected_version=5,
            idempotency_key=f"wp02-task-rej-{capability}-0002",
        )
    )
    refused = runtime.invoke(stale)
    assert refused.error is not None and refused.error.code is ErrorCode.CONFLICT
    with runtime.work_engine.connect() as connection:
        outcomes = list(
            connection.execute(
                select(task_history.c.outcome).where(task_history.c.task_id == task_id)
            ).scalars()
        )
    assert sorted(outcomes) == ["applied", "rejected"]  # the REJECTED receipt committed
    assert (feed(runtime.work_engine), next_sequence(runtime.work_engine)) == before


# ---- U2 standalone ----------------------------------------------------------


def test_the_standalone_task_unit_of_work_commits_the_event(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        service = TaskManagementService(
            unit_of_work=lambda: SqlAlchemyTaskManagementUnitOfWork(engine)
        )
        principal = issue_identifier(IdKind.PRINCIPAL)
        receipt = service.create_task(
            principal_id=principal,
            title="Standalone",
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
            actor=TaskMutationActor.PRINCIPAL,
        )
        (event,) = feed(engine, principal)
        assert event["record_id"] == receipt.task.task_id
        assert event["source_capability"] == "tasks.create"
        assert event["source_receipt_id"] == receipt.history.history_id
        assert_gap_free(engine, principal)
    finally:
        engine.dispose()
