"""Home and Work consume one Today selector: `tasks.list_tasks` + TODAY.

WP-POSTUX-06 forbids a second Today SQL path. Work already evaluates civil-day
membership in `_extend_work_view_conditions` (TODAY). Home's `/api/pulse`
composition must call the same `list_tasks(..., work_view=TODAY, work_start,
work_end)` after `_work_window`. This suite writes through
`SqlTaskManagementRepository.insert_task` and reads through `list_tasks` with
that Work TODAY window — the selector both surfaces are required to share.

Membership (not Pulse ranking) is the subject. Ordering is calendar timestamp,
then priority, then task_id.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Engine

from my_pa.application.service import _work_window
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

pytestmark = pytest.mark.database

DISPOSABLE_DATABASE: Final = "my_pa_home_work_today_parity_test"
PRINCIPAL: Final = "prn_todayhome001todayhome001"
WHEN: Final = datetime(2026, 9, 1, 12, tzinfo=UTC)
WORK_DATE: Final = date(2026, 9, 17)
TIMEZONE: Final = "America/New_York"


def _window() -> tuple[datetime, datetime]:
    return _work_window(WORK_DATE, TIMEZONE)


def _task(
    *,
    title: str,
    lifecycle_state: TaskLifecycleState = TaskLifecycleState.OPEN,
    due_at: datetime | None = None,
    scheduled_at: datetime | None = None,
    archived_at: datetime | None = None,
    priority: TaskPriority | None = None,
    closed_at: datetime | None = None,
) -> Task:
    now = WHEN
    return Task(
        task_id=issue_identifier(IdKind.TASK),
        principal_id=PRINCIPAL,
        title=title,
        lifecycle_state=lifecycle_state,
        evidence_state=ContinuityEvidenceState.ACCEPTED,
        origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        opened_at=now,
        created_at=now,
        updated_at=now,
        due_at=due_at,
        scheduled_at=scheduled_at,
        archived_at=archived_at,
        priority=priority,
        closed_at=closed_at,
        acceptance_kind=ContinuityAcceptanceKind.DIRECT_PRINCIPAL,
    )


def _today_ids(engine: Engine) -> tuple[str, ...]:
    start, end = _window()
    with SqlAlchemyTaskManagementUnitOfWork(engine) as uow:
        found = uow.tasks.list_tasks(
            PRINCIPAL,
            work_view=TaskWorkView.TODAY,
            work_start=start,
            work_end=end,
            work_now=datetime(2026, 9, 17, 16, tzinfo=UTC),
            limit=50,
        )
    return tuple(task.task_id for task in found)


def _insert(engine: Engine, task: Task) -> str:
    with SqlAlchemyTaskManagementUnitOfWork(engine) as uow:
        uow.tasks.insert_task(task)
    return task.task_id


def test_scheduled_only_task_is_today(migrated_engine: Engine) -> None:
    start, end = _window()
    scheduled = start + timedelta(hours=10)
    task_id = _insert(
        migrated_engine,
        _task(title="Scheduled only", scheduled_at=scheduled),
    )
    assert task_id in _today_ids(migrated_engine)
    assert start <= scheduled < end


def test_due_only_task_is_today(migrated_engine: Engine) -> None:
    start, _end = _window()
    task_id = _insert(
        migrated_engine,
        _task(title="Due only", due_at=start + timedelta(hours=12)),
    )
    assert task_id in _today_ids(migrated_engine)


def test_due_and_scheduled_same_task_appears_once(migrated_engine: Engine) -> None:
    start, _end = _window()
    task_id = _insert(
        migrated_engine,
        _task(
            title="Both instants",
            due_at=start + timedelta(hours=15),
            scheduled_at=start + timedelta(hours=9),
        ),
    )
    ids = _today_ids(migrated_engine)
    assert ids.count(task_id) == 1


def test_archived_task_is_excluded(migrated_engine: Engine) -> None:
    start, _end = _window()
    task_id = _insert(
        migrated_engine,
        _task(
            title="Archived",
            due_at=start + timedelta(hours=8),
            archived_at=WHEN,
        ),
    )
    assert task_id not in _today_ids(migrated_engine)


def test_terminal_tasks_are_excluded(migrated_engine: Engine) -> None:
    start, _end = _window()
    due = start + timedelta(hours=8)
    completed = _insert(
        migrated_engine,
        _task(
            title="Completed",
            lifecycle_state=TaskLifecycleState.COMPLETED,
            due_at=due,
            closed_at=WHEN,
        ),
    )
    cancelled = _insert(
        migrated_engine,
        _task(
            title="Cancelled",
            lifecycle_state=TaskLifecycleState.CANCELLED,
            due_at=due,
            closed_at=WHEN,
        ),
    )
    open_id = _insert(migrated_engine, _task(title="Open", due_at=due))
    ids = _today_ids(migrated_engine)
    assert completed not in ids
    assert cancelled not in ids
    assert open_id in ids


def test_overdue_only_is_not_today(migrated_engine: Engine) -> None:
    start, _end = _window()
    task_id = _insert(
        migrated_engine,
        _task(title="Overdue", due_at=start - timedelta(hours=2)),
    )
    assert task_id not in _today_ids(migrated_engine)


def test_due_tomorrow_within_72h_is_not_today(migrated_engine: Engine) -> None:
    _start, end = _window()
    task_id = _insert(
        migrated_engine,
        _task(title="Tomorrow", due_at=end + timedelta(hours=12)),
    )
    assert task_id not in _today_ids(migrated_engine)


def test_neither_due_nor_scheduled_is_not_today(migrated_engine: Engine) -> None:
    task_id = _insert(migrated_engine, _task(title="Unscheduled"))
    assert task_id not in _today_ids(migrated_engine)


def test_ordering_is_calendar_then_priority_then_id(migrated_engine: Engine) -> None:
    start, _end = _window()
    later = _insert(
        migrated_engine,
        _task(
            title="Later p1",
            due_at=start + timedelta(hours=14),
            priority=TaskPriority.P1,
        ),
    )
    earlier_p3 = _insert(
        migrated_engine,
        _task(
            title="Earlier p3",
            due_at=start + timedelta(hours=8),
            priority=TaskPriority.P3,
        ),
    )
    earlier_p1 = _insert(
        migrated_engine,
        _task(
            title="Earlier p1",
            due_at=start + timedelta(hours=8),
            priority=TaskPriority.P1,
        ),
    )
    ids = _today_ids(migrated_engine)
    assert ids.index(earlier_p1) < ids.index(earlier_p3)
    assert ids.index(earlier_p3) < ids.index(later)


def test_dst_spring_forward_civil_day_membership(migrated_engine: Engine) -> None:
    work_date = date(2026, 3, 8)
    start, end = _work_window(work_date, "America/New_York")
    inside = _insert(
        migrated_engine,
        _task(title="DST inside", due_at=start + timedelta(hours=1)),
    )
    after = _insert(
        migrated_engine,
        _task(title="DST after", due_at=end),
    )
    with SqlAlchemyTaskManagementUnitOfWork(migrated_engine) as uow:
        found = uow.tasks.list_tasks(
            PRINCIPAL,
            work_view=TaskWorkView.TODAY,
            work_start=start,
            work_end=end,
            limit=50,
        )
    ids = tuple(task.task_id for task in found)
    assert inside in ids
    assert after not in ids
    assert (end - start) == timedelta(hours=23)
