"""The FAST fake's TODAY rule and the SQL TODAY predicate answer one set.

`tests/conftest.py` re-states the Today membership rule in Python for the fake
task repository, because a SQLAlchemy `ColumnElement` cannot be evaluated over
in-memory `Task` objects and the fake cannot reach PostgreSQL. That duplicate
is what the FAST tier and `tests/contract/test_http_transport.py` actually
execute, so the fast tiers only exercise the real predicate to the extent the
two agree — and nothing made them keep agreeing.

This module is that enforcement: one corpus of `Task` rows covering every
clause of the contract (ownership, `archived_at`, lifecycle state, `due_at` and
`scheduled_at` against both boundaries, `deferred_until`) is written to both
repositories, both are asked the same TODAY question with the same window, and
the two ordered answers must be identical. A divergence in either direction —
the fake admitting a row SQL excludes, or ordering the page differently — fails
here rather than silently weakening every FAST test that trusts the fake.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Engine

from my_pa.application.service import _work_window
from my_pa.contracts.ports import TaskManagementRepository
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.situation.continuity import ContinuityAcceptanceKind, ContinuityEvidenceState
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.lifecycle import (
    TaskLifecycleState,
    TaskOriginKind,
    TaskPriority,
    TaskWorkView,
)
from my_pa.domain.task.task import Task
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from tests.conftest import World, _TasksRead

pytestmark = pytest.mark.database

PRINCIPAL: Final = "prn_todayagree01todayagree01"
OTHER_PRINCIPAL: Final = "prn_todayagree02todayagree02"
WHEN: Final = datetime(2026, 9, 1, 12, tzinfo=UTC)
WORK_DATE: Final = date(2026, 9, 17)
TIMEZONE: Final = "America/New_York"
WORK_NOW: Final = datetime(2026, 9, 17, 16, tzinfo=UTC)


def _task(
    *,
    title: str,
    lifecycle_state: TaskLifecycleState = TaskLifecycleState.OPEN,
    due_at: datetime | None = None,
    scheduled_at: datetime | None = None,
    archived_at: datetime | None = None,
    deferred_until: datetime | None = None,
    priority: TaskPriority | None = None,
    closed_at: datetime | None = None,
    principal_id: str = PRINCIPAL,
) -> Task:
    return Task(
        task_id=issue_identifier(IdKind.TASK),
        principal_id=principal_id,
        title=title,
        lifecycle_state=lifecycle_state,
        evidence_state=ContinuityEvidenceState.ACCEPTED,
        origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        opened_at=WHEN,
        created_at=WHEN,
        updated_at=WHEN,
        due_at=due_at,
        scheduled_at=scheduled_at,
        archived_at=archived_at,
        deferred_until=deferred_until,
        priority=priority,
        closed_at=closed_at,
        acceptance_kind=ContinuityAcceptanceKind.DIRECT_PRINCIPAL,
    )


def _corpus() -> tuple[Task, ...]:
    """One row per clause of the contract, on both sides of each boundary."""
    start, end = _work_window(WORK_DATE, TIMEZONE)
    return (
        _task(title="Due at exact local midnight", due_at=start, priority=TaskPriority.P2),
        _task(title="Due at midnight, higher priority", due_at=start, priority=TaskPriority.P1),
        _task(title="Due at midnight, no priority", due_at=start),
        _task(title="Scheduled midday", scheduled_at=start + timedelta(hours=10)),
        _task(
            title="Due and scheduled",
            due_at=start + timedelta(hours=15),
            scheduled_at=start + timedelta(hours=9),
        ),
        _task(
            title="Last instant of the civil day",
            due_at=end - timedelta(microseconds=1),
        ),
        _task(title="Exactly next local midnight", due_at=end),
        _task(title="Overdue", due_at=start - timedelta(microseconds=1)),
        _task(title="Neither due nor scheduled"),
        _task(
            title="Deferred before the window",
            due_at=start + timedelta(hours=11),
            deferred_until=start - timedelta(days=2),
        ),
        _task(
            title="Deferred after the window",
            due_at=start + timedelta(hours=11),
            deferred_until=end + timedelta(days=2),
        ),
        _task(title="Archived", due_at=start + timedelta(hours=8), archived_at=WHEN),
        _task(
            title="Completed",
            lifecycle_state=TaskLifecycleState.COMPLETED,
            due_at=start + timedelta(hours=8),
            closed_at=WHEN,
        ),
        _task(
            title="Cancelled",
            lifecycle_state=TaskLifecycleState.CANCELLED,
            due_at=start + timedelta(hours=8),
            closed_at=WHEN,
        ),
        _task(
            title="Waiting",
            lifecycle_state=TaskLifecycleState.WAITING,
            due_at=start + timedelta(hours=7),
        ),
        _task(
            title="Blocked",
            lifecycle_state=TaskLifecycleState.BLOCKED,
            due_at=start + timedelta(hours=6),
        ),
        _task(
            title="In progress",
            lifecycle_state=TaskLifecycleState.IN_PROGRESS,
            scheduled_at=start + timedelta(hours=5),
        ),
        _task(
            title="Another Principal's Today task",
            due_at=start + timedelta(hours=9),
            principal_id=OTHER_PRINCIPAL,
        ),
    )


def _today_ids(repository: TaskManagementRepository) -> tuple[str, ...]:
    start, end = _work_window(WORK_DATE, TIMEZONE)
    found = repository.list_tasks(
        PRINCIPAL,
        work_view=TaskWorkView.TODAY,
        work_start=start,
        work_end=end,
        work_now=WORK_NOW,
        limit=50,
    )
    return tuple(task.task_id for task in found)


def test_fake_today_rule_matches_the_sql_today_predicate(migrated_engine: Engine) -> None:
    corpus = _corpus()

    fake = _TasksRead(World())
    for task in corpus:
        fake.insert_task(task)
    fake_ids = _today_ids(fake)

    with SqlAlchemyTaskManagementUnitOfWork(migrated_engine) as uow:
        for task in corpus:
            uow.tasks.insert_task(task)
    with SqlAlchemyTaskManagementUnitOfWork(migrated_engine) as uow:
        sql_ids = _today_ids(uow.tasks)

    assert fake_ids == sql_ids
    # The corpus must not be trivially empty or trivially whole, or equality
    # would be satisfied by a predicate that admits nothing or everything.
    assert 0 < len(sql_ids) < len(corpus)
