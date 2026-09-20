"""Home and Work consume one Today selector: `tasks.list` + TODAY.

WP-POSTUX-06 forbids a second Today SQL path. Work evaluates civil-day
membership in `_extend_work_view_conditions` (TODAY). Home's `/api/pulse`
composition calls `tasks.list` with `work_view=today` and composes *every*
returned Task into its answer, with no intersecting filter of its own
(`web/src/app/api/pulse/route.ts`). The Python-side layer both surfaces reach
is therefore `ApplicationService._tasks_list` with `work_view=TODAY`, which
derives the window with `_work_window` and hands it to the one repository
predicate.

This suite proves two different things and says which is which:

* **membership** — the SQL predicate itself, written through
  `SqlTaskManagementRepository.insert_task` and read through `list_tasks`
  with the Work TODAY window (`_today_ids`). These tests exercise one path,
  not two, and claim nothing about parity.
* **parity** — the capability-layer tests at the end of this module run the
  *Home* parameterization of `tasks.list` and the *Work* parameterization of
  the same capability through `ApplicationService` over one shared corpus and
  assert the two answers are the identical ordered set, and that the set equals
  what the repository predicate alone returns. That exercises `_work_window`
  and the repository predicate together, which the repository call alone does
  not.

Membership (not Pulse ranking) is the subject. Ordering is calendar timestamp,
then priority, then task_id.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Engine

from my_pa.application.commands import Command, ListTasks
from my_pa.application.service import ApplicationService, _work_window
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.situation.continuity import ContinuityAcceptanceKind, ContinuityEvidenceState
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.lifecycle import (
    TaskArchiveMode,
    TaskLifecycleState,
    TaskOriginKind,
    TaskPriority,
    TaskWorkView,
)
from my_pa.domain.task.task import Task
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

DISPOSABLE_DATABASE: Final = "my_pa_home_work_today_parity_test"
PRINCIPAL: Final = "prn_todayhome001todayhome001"
OTHER_PRINCIPAL: Final = "prn_todayforeign001todayfore"
WHEN: Final = datetime(2026, 9, 1, 12, tzinfo=UTC)
WORK_DATE: Final = date(2026, 9, 17)
TIMEZONE: Final = "America/New_York"
LIMITS: Final = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)


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
    deferred_until: datetime | None = None,
    principal_id: str = PRINCIPAL,
) -> Task:
    now = WHEN
    return Task(
        task_id=issue_identifier(IdKind.TASK),
        principal_id=principal_id,
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
        deferred_until=deferred_until,
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


def test_another_principals_task_is_not_today(migrated_engine: Engine) -> None:
    """Ownership is part of the predicate, not an assumption of the fixtures.

    The foreign row satisfies every other clause — not archived, OPEN, due
    inside the same window as the control row — so only `principal_id` can
    keep it out.
    """
    start, _end = _window()
    due = start + timedelta(hours=9)
    foreign = _insert(
        migrated_engine,
        _task(title="Foreign principal", due_at=due, principal_id=OTHER_PRINCIPAL),
    )
    own = _insert(migrated_engine, _task(title="Own", due_at=due))
    ids = _today_ids(migrated_engine)
    assert own in ids
    assert foreign not in ids


def test_exact_local_midnight_is_today(migrated_engine: Engine) -> None:
    """The lower bound is inclusive in the SQL predicate, not only in arithmetic.

    `due_at` and `scheduled_at` are set to exactly `work_start` — 2026-09-17
    00:00 America/New_York, i.e. 2026-09-17 04:00Z — which is the one instant
    `>=` admits and `>` would not. The exclusive upper bound is proved by
    `test_due_tomorrow_within_72h_is_not_today` and by the DST case, which
    places a task at exactly `work_end`.
    """
    start, _end = _window()
    assert start == datetime(2026, 9, 17, 4, tzinfo=UTC)
    due_at_midnight = _insert(migrated_engine, _task(title="Due at midnight", due_at=start))
    scheduled_at_midnight = _insert(
        migrated_engine, _task(title="Scheduled at midnight", scheduled_at=start)
    )
    ids = _today_ids(migrated_engine)
    assert due_at_midnight in ids
    assert scheduled_at_midnight in ids


def test_deferred_until_does_not_affect_membership(migrated_engine: Engine) -> None:
    """A deferral changes nothing about Today membership, in either direction.

    Both rows are canonically Today (`due_at` inside the window). One carries a
    `deferred_until` two days before the window, one two days after it; the
    contract says membership is unchanged either way, and the control row with
    no deferral pins that the three are otherwise identical.
    """
    start, end = _window()
    due = start + timedelta(hours=11)
    deferred_before = _insert(
        migrated_engine,
        _task(
            title="Deferred before the window",
            due_at=due,
            deferred_until=start - timedelta(days=2),
        ),
    )
    deferred_after = _insert(
        migrated_engine,
        _task(
            title="Deferred after the window",
            due_at=due,
            deferred_until=end + timedelta(days=2),
        ),
    )
    undeferred = _insert(migrated_engine, _task(title="Not deferred", due_at=due))
    ids = _today_ids(migrated_engine)
    assert deferred_before in ids
    assert deferred_after in ids
    assert undeferred in ids


# --- Parity: Home's and Work's parameterizations of one capability ----------
#
# Everything above reads the repository directly and proves the SQL predicate.
# Everything below goes through `ApplicationService`, which is the layer both
# surfaces actually reach: `/api/pulse` calls `tasks.list` with
# `work_view=today&work_date=&timezone=` and composes every returned Task,
# and Work's `/api/tasks` calls the same capability with
# `pageSize=50&workView=today&archived=exclude` plus the same date and zone.


class _Runtime:
    """`ApplicationService` over the disposable catalog, invoked as a surface would."""

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

    def invoke(self, command_value: Command, *, principal_id: str = PRINCIPAL) -> ResponseEnvelope:
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
                requested_at=datetime(2026, 9, 17, 16, tzinfo=UTC),
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


def _listed_ids(runtime: _Runtime, command: ListTasks) -> tuple[str, ...]:
    answered = runtime.invoke(command)
    assert answered.error is None, answered.error
    assert answered.result is not None
    entries = answered.result["tasks"]
    assert isinstance(entries, list)
    return tuple(str(entry["task_id"]) for entry in entries)


#: Home: `/api/pulse` sends work_view, work_date and timezone and nothing else,
#: so page size and archive mode are the capability's own defaults.
_HOME_LIST: Final = ListTasks(work_view=TaskWorkView.TODAY, work_date=WORK_DATE, timezone=TIMEZONE)

#: Work: the Workbench sends `pageSize=50&workView=today&archived=exclude`
#: alongside the same civil date and zone.
_WORK_LIST: Final = ListTasks(
    work_view=TaskWorkView.TODAY,
    work_date=WORK_DATE,
    timezone=TIMEZONE,
    page_size=50,
    archive_mode=TaskArchiveMode.EXCLUDE,
)


def _parity_corpus(engine: Engine) -> tuple[str, ...]:
    """Write one corpus covering every clause; return the expected Today order."""
    start, end = _window()
    early = _insert(
        engine,
        _task(title="Early p1", due_at=start, priority=TaskPriority.P1),
    )
    midday = _insert(
        engine,
        _task(title="Midday scheduled", scheduled_at=start + timedelta(hours=10)),
    )
    deferred = _insert(
        engine,
        _task(
            title="Deferred but Today",
            due_at=start + timedelta(hours=14),
            deferred_until=end + timedelta(days=1),
        ),
    )
    _insert(
        engine, _task(title="Archived Today", due_at=start + timedelta(hours=9), archived_at=WHEN)
    )
    _insert(
        engine,
        _task(
            title="Foreign Today",
            due_at=start + timedelta(hours=9),
            principal_id=OTHER_PRINCIPAL,
        ),
    )
    _insert(engine, _task(title="Overdue", due_at=start - timedelta(hours=2)))
    _insert(engine, _task(title="Tomorrow", due_at=end + timedelta(hours=2)))
    _insert(
        engine,
        _task(
            title="Completed Today",
            lifecycle_state=TaskLifecycleState.COMPLETED,
            due_at=start + timedelta(hours=9),
            closed_at=WHEN,
        ),
    )
    return (early, midday, deferred)


def test_home_and_work_parameterizations_answer_one_identical_today_set(
    migrated_engine: Engine, runtime: _Runtime
) -> None:
    """Home's and Work's own `tasks.list` arguments answer the same ordered set.

    This is the parity claim, asserted rather than asserted-about: the two
    parameterizations differ exactly as the two surfaces differ (Home omits
    page size and archive mode; Work states both), and the answers must be the
    same ordered tuple over a corpus that includes rows each clause excludes —
    archived, foreign-Principal, overdue, tomorrow, terminal.
    """
    expected = _parity_corpus(migrated_engine)
    home = _listed_ids(runtime, _HOME_LIST)
    work = _listed_ids(runtime, _WORK_LIST)
    assert home == work
    assert home == expected


def test_capability_layer_answers_exactly_the_repository_predicate(
    migrated_engine: Engine, runtime: _Runtime
) -> None:
    """`_work_window` + the capability add and remove nothing.

    The repository call in `_today_ids` supplies the window itself; the
    capability derives it from `work_date` and `timezone`. Equality of the two
    answers is what makes the repository-level membership tests above evidence
    about the surfaces.
    """
    expected = _parity_corpus(migrated_engine)
    assert _listed_ids(runtime, _HOME_LIST) == _today_ids(migrated_engine)
    assert _today_ids(migrated_engine) == expected
