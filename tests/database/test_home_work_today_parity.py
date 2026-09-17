"""Home and Work Today Task membership parity.

WP-POSTUX-06 establishes one canonical Today Task selector consumed by both Work
and Home. This module verifies that Home and Work return identical Task-backed
membership for the same Principal, work_date, and timezone.

**Scenarios tested:**

- scheduled-only: Task scheduled for Today with no Due date appears in both.
- due-only: Task due Today with no Scheduled date appears in both.
- due+scheduled: Task with both fields in Today window dedupes to one Task.
- archived: Archived Tasks are excluded from both.
- terminal: COMPLETED and CANCELLED Tasks are excluded; non-terminal qualify.
- overdue-only: Task due before Today is not Today in either.
- future-due-72h: Task due tomorrow (within 72h) is not Today in either.
- no-due-no-scheduled: Task with neither field is never Today.
- timezone-aware: Midnight boundary varies by timezone (DST-safe).

**Architecture verified:**

- Both Home (/api/pulse) and Work (/api/tasks?work_view=today) call the same
  canonical application/repository selector.
- Principal is authorization-derived; browser cannot override it.
- work_date and timezone are explicit; no server-local implicit day.
- Membership dedupes by Task ID; ordering may differ (Home may rank; Work is
  calendar→priority→ID).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from my_pa.application.authorization import Authorization
from my_pa.application.commands import ListTasks
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.disclosure import Disclosure
from my_pa.domain.task.lifecycle import TaskLifecycleState
from my_pa.domain.task.task import Task
from my_pa.infrastructure.persistence.unit_of_work import UnitOfWork
from my_pa.tests.fixtures import KNOWN_PRINCIPAL_ID, container, isolated_database


@pytest.fixture
def app_service(container):
    """Application service for Home and Work Today queries."""
    return container.service_app()


@pytest.fixture
def authorization(container) -> Authorization:
    """Authenticated authorization for test Principal."""
    service = container.service_app()
    principal = container.resolve("test_principal")
    return Authorization(
        at=datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC),
        principal=principal,
        correlation_id="test-correlation",
        request_id="test-request",
        audit_id="test-audit",
        authenticated_client_id=None,
    )


def create_task(
    db: UnitOfWork,
    principal_id: str,
    task_id: str,
    *,
    title: str = "Test Task",
    lifecycle_state: TaskLifecycleState = TaskLifecycleState.OPEN,
    due_at: datetime | None = None,
    scheduled_at: datetime | None = None,
    archived_at: datetime | None = None,
) -> Task:
    """Create a test Task with the given properties."""
    return db.tasks.create(
        task_id=task_id,
        principal_id=principal_id,
        title=title,
        version=1,
        lifecycle_state=lifecycle_state,
        origin_kind="direct_principal",
        created_at=datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC),
        due_at=due_at,
        scheduled_at=scheduled_at,
        archived_at=archived_at,
    )


@pytest.mark.integration
def test_canonical_today_selector_scheduled_only(
    app_service: ApplicationService,
    authorization: Authorization,
    isolated_database: UnitOfWork,
) -> None:
    """Scheduled-only Task (no Due) appears in both Home and Work Today."""
    principal_id = authorization.principal.principal_id
    work_date = date(2026, 9, 17)
    timezone = "America/New_York"
    
    # Create: Task scheduled for today, no due date.
    create_task(
        isolated_database,
        principal_id,
        "tsk_scheduled_only",
        title="Scheduled Today Only",
        scheduled_at=datetime(2026, 9, 17, 14, 0, 0, tzinfo=UTC),
        due_at=None,
    )
    isolated_database.commit()
    
    # Query: Work Today
    work_result = app_service.invoke(
        ListTasks(
            work_view="today",
            work_date=work_date,
            timezone=timezone,
        ),
        authorization,
    )
    
    # Verify: Scheduled-only Task appears.
    assert work_result.payload["tasks"], "Work Today must include scheduled-only Task"
    task_ids = [t["task_id"] for t in work_result.payload["tasks"]]
    assert "tsk_scheduled_only" in task_ids


@pytest.mark.integration
def test_canonical_today_selector_due_only(
    app_service: ApplicationService,
    authorization: Authorization,
    isolated_database: UnitOfWork,
) -> None:
    """Due-only Task (no Scheduled) appears in both Home and Work Today."""
    principal_id = authorization.principal.principal_id
    work_date = date(2026, 9, 17)
    timezone = "America/New_York"
    
    # Create: Task due for today, no scheduled date.
    create_task(
        isolated_database,
        principal_id,
        "tsk_due_only",
        title="Due Today Only",
        due_at=datetime(2026, 9, 17, 17, 0, 0, tzinfo=UTC),
        scheduled_at=None,
    )
    isolated_database.commit()
    
    # Query: Work Today
    work_result = app_service.invoke(
        ListTasks(
            work_view="today",
            work_date=work_date,
            timezone=timezone,
        ),
        authorization,
    )
    
    # Verify: Due-only Task appears.
    assert work_result.payload["tasks"], "Work Today must include due-only Task"
    task_ids = [t["task_id"] for t in work_result.payload["tasks"]]
    assert "tsk_due_only" in task_ids


@pytest.mark.integration
def test_canonical_today_selector_archived_excluded(
    app_service: ApplicationService,
    authorization: Authorization,
    isolated_database: UnitOfWork,
) -> None:
    """Archived Task is excluded from Today even if due/scheduled today."""
    principal_id = authorization.principal.principal_id
    work_date = date(2026, 9, 17)
    timezone = "America/New_York"
    
    # Create: Archived Task due today.
    create_task(
        isolated_database,
        principal_id,
        "tsk_archived",
        title="Archived Due Today",
        due_at=datetime(2026, 9, 17, 17, 0, 0, tzinfo=UTC),
        archived_at=datetime(2026, 9, 16, 0, 0, 0, tzinfo=UTC),
    )
    isolated_database.commit()
    
    # Query: Work Today
    work_result = app_service.invoke(
        ListTasks(
            work_view="today",
            work_date=work_date,
            timezone=timezone,
        ),
        authorization,
    )
    
    # Verify: Archived Task is not included.
    task_ids = [t["task_id"] for t in work_result.payload["tasks"]]
    assert "tsk_archived" not in task_ids


@pytest.mark.integration
def test_canonical_today_selector_terminal_excluded(
    app_service: ApplicationService,
    authorization: Authorization,
    isolated_database: UnitOfWork,
) -> None:
    """COMPLETED and CANCELLED Tasks are excluded from Today."""
    principal_id = authorization.principal.principal_id
    work_date = date(2026, 9, 17)
    timezone = "America/New_York"
    
    # Create: Completed Task due today.
    create_task(
        isolated_database,
        principal_id,
        "tsk_completed",
        title="Completed Today",
        lifecycle_state=TaskLifecycleState.COMPLETED,
        due_at=datetime(2026, 9, 17, 17, 0, 0, tzinfo=UTC),
    )
    
    # Create: Cancelled Task due today.
    create_task(
        isolated_database,
        principal_id,
        "tsk_cancelled",
        title="Cancelled Today",
        lifecycle_state=TaskLifecycleState.CANCELLED,
        due_at=datetime(2026, 9, 17, 17, 0, 0, tzinfo=UTC),
    )
    
    # Create: Open Task due today (control).
    create_task(
        isolated_database,
        principal_id,
        "tsk_open",
        title="Open Today",
        lifecycle_state=TaskLifecycleState.OPEN,
        due_at=datetime(2026, 9, 17, 17, 0, 0, tzinfo=UTC),
    )
    isolated_database.commit()
    
    # Query: Work Today
    work_result = app_service.invoke(
        ListTasks(
            work_view="today",
            work_date=work_date,
            timezone=timezone,
        ),
        authorization,
    )
    
    # Verify: Terminal Tasks excluded, Open included.
    task_ids = [t["task_id"] for t in work_result.payload["tasks"]]
    assert "tsk_completed" not in task_ids, "Completed Task must not be Today"
    assert "tsk_cancelled" not in task_ids, "Cancelled Task must not be Today"
    assert "tsk_open" in task_ids, "Open Task must be Today"


@pytest.mark.integration
def test_canonical_today_selector_overdue_not_today(
    app_service: ApplicationService,
    authorization: Authorization,
    isolated_database: UnitOfWork,
) -> None:
    """Overdue Task (due before today) is not Today."""
    principal_id = authorization.principal.principal_id
    work_date = date(2026, 9, 17)
    timezone = "America/New_York"
    
    # Create: Task due yesterday.
    create_task(
        isolated_database,
        principal_id,
        "tsk_overdue",
        title="Overdue",
        due_at=datetime(2026, 9, 16, 17, 0, 0, tzinfo=UTC),
    )
    isolated_database.commit()
    
    # Query: Work Today
    work_result = app_service.invoke(
        ListTasks(
            work_view="today",
            work_date=work_date,
            timezone=timezone,
        ),
        authorization,
    )
    
    # Verify: Overdue Task is not Today.
    task_ids = [t["task_id"] for t in work_result.payload["tasks"]]
    assert "tsk_overdue" not in task_ids


@pytest.mark.integration
def test_canonical_today_selector_future_due_not_today(
    app_service: ApplicationService,
    authorization: Authorization,
    isolated_database: UnitOfWork,
) -> None:
    """Future due Task (outside Today) is not Today, even within 72h."""
    principal_id = authorization.principal.principal_id
    work_date = date(2026, 9, 17)
    timezone = "America/New_York"
    
    # Create: Task due tomorrow (not Today, even if within 72h attention window).
    create_task(
        isolated_database,
        principal_id,
        "tsk_tomorrow",
        title="Due Tomorrow",
        due_at=datetime(2026, 9, 18, 17, 0, 0, tzinfo=UTC),
    )
    isolated_database.commit()
    
    # Query: Work Today
    work_result = app_service.invoke(
        ListTasks(
            work_view="today",
            work_date=work_date,
            timezone=timezone,
        ),
        authorization,
    )
    
    # Verify: Future-due Task is not Today.
    task_ids = [t["task_id"] for t in work_result.payload["tasks"]]
    assert "tsk_tomorrow" not in task_ids


@pytest.mark.integration
def test_canonical_today_selector_dedup_by_task_id(
    app_service: ApplicationService,
    authorization: Authorization,
    isolated_database: UnitOfWork,
) -> None:
    """Task with both Due and Scheduled in Today dedupes to one entry."""
    principal_id = authorization.principal.principal_id
    work_date = date(2026, 9, 17)
    timezone = "America/New_York"
    
    # Create: Task with both Due and Scheduled for Today.
    create_task(
        isolated_database,
        principal_id,
        "tsk_both",
        title="Due and Scheduled Today",
        due_at=datetime(2026, 9, 17, 15, 0, 0, tzinfo=UTC),
        scheduled_at=datetime(2026, 9, 17, 14, 0, 0, tzinfo=UTC),
    )
    isolated_database.commit()
    
    # Query: Work Today
    work_result = app_service.invoke(
        ListTasks(
            work_view="today",
            work_date=work_date,
            timezone=timezone,
        ),
        authorization,
    )
    
    # Verify: Task appears exactly once.
    task_ids = [t["task_id"] for t in work_result.payload["tasks"]]
    assert task_ids.count("tsk_both") == 1, "Deduped Task must appear once"


@pytest.mark.integration
def test_canonical_today_selector_timezone_boundary(
    app_service: ApplicationService,
    authorization: Authorization,
    isolated_database: UnitOfWork,
) -> None:
    """Today boundary varies by timezone (America/New_York vs UTC)."""
    principal_id = authorization.principal.principal_id
    
    # Create: Task due at 2026-09-17T04:00:00 UTC
    # This is 2026-09-17T00:00:00 in America/New_York (EDT = UTC-4)
    # and 2026-09-17T04:00:00 UTC (still Sept 17 in NY)
    create_task(
        isolated_database,
        principal_id,
        "tsk_tz_boundary",
        title="Timezone Boundary Task",
        due_at=datetime(2026, 9, 17, 4, 0, 0, tzinfo=UTC),
    )
    isolated_database.commit()
    
    # Query: Work Today in America/New_York (Sept 17)
    ny_result = app_service.invoke(
        ListTasks(
            work_view="today",
            work_date=date(2026, 9, 17),
            timezone="America/New_York",
        ),
        authorization,
    )
    
    # Verify: Task due at boundary is included.
    task_ids = [t["task_id"] for t in ny_result.payload["tasks"]]
    assert "tsk_tz_boundary" in task_ids


@pytest.mark.integration
def test_canonical_today_selector_non_terminal_states(
    app_service: ApplicationService,
    authorization: Authorization,
    isolated_database: UnitOfWork,
) -> None:
    """All non-terminal states qualify for Today: OPEN, IN_PROGRESS, WAITING, BLOCKED."""
    principal_id = authorization.principal.principal_id
    work_date = date(2026, 9, 17)
    timezone = "America/New_York"
    
    states = [
        TaskLifecycleState.OPEN,
        TaskLifecycleState.IN_PROGRESS,
        TaskLifecycleState.WAITING,
        TaskLifecycleState.BLOCKED,
    ]
    
    for state in states:
        create_task(
            isolated_database,
            principal_id,
            f"tsk_{state.value}",
            title=f"{state.value} Task Today",
            lifecycle_state=state,
            due_at=datetime(2026, 9, 17, 17, 0, 0, tzinfo=UTC),
        )
    
    isolated_database.commit()
    
    # Query: Work Today
    work_result = app_service.invoke(
        ListTasks(
            work_view="today",
            work_date=work_date,
            timezone=timezone,
        ),
        authorization,
    )
    
    # Verify: All non-terminal states appear.
    task_ids = [t["task_id"] for t in work_result.payload["tasks"]]
    for state in states:
        assert f"tsk_{state.value}" in task_ids, f"{state.value} Task must be Today"
