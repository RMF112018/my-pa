"""Canonical Today Task membership contract — WP-POSTUX-06.

The `database` tier. Everything here runs against a live PostgreSQL server to verify
that the repository's `today_tasks()` method correctly implements the canonical
Today membership contract:

For Principal P, civil date D, validated IANA timezone Z, a Task is Today iff:
1. belongs to P
2. not archived (archived_at is NULL)
3. lifecycle in OPEN, IN_PROGRESS, WAITING, BLOCKED
4. due_at OR scheduled_at falls in [midnight(D,Z), midnight(D+1,Z)) after server-side TZ conversion

Tests cover:
- Due date within Today window (in)
- Scheduled date within Today window (in)
- Both due and scheduled in window (in, not deduped)
- Due date before Today (out)
- Due date after Today (out)
- Scheduled date before Today (out)
- Scheduled date after Today (out)
- No due or scheduled date (out)
- Archived tasks (out)
- Terminal lifecycle states (out)
- Open/In Progress/Waiting/Blocked lifecycle states (in)
- Principal isolation (correct principal in, wrong principal out)
- Timezone boundary cases
- Midnight boundary conditions
- Invalid timezone rejection
- Empty result when no match
- Deferred_until semantics preserved (not affecting Today membership)
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Engine
from sqlalchemy.engine import Connection
from zoneinfo import ZoneInfo

from my_pa.infrastructure.persistence.situation_repository import SqlContinuityRepository
from my_pa.infrastructure.persistence.tables import tasks as tasks_table

pytestmark = pytest.mark.database

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

# Test date: September 17, 2026 (UTC Wednesday)
TEST_DATE: Final = date(2026, 9, 17)

# Timezone references for testing
UTC_TZ: Final = "UTC"
US_EASTERN: Final = "America/New_York"
EUROPE_LONDON: Final = "Europe/London"
ASIA_TOKYO: Final = "Asia/Tokyo"


@pytest.fixture
def repo_conn(migrated_engine: Engine) -> tuple[SqlContinuityRepository, Connection]:
    """Create a repository and connection for testing within a transaction."""
    with migrated_engine.begin() as connection:
        yield (SqlContinuityRepository(connection), connection)


def _insert_task(
    connection: Connection,
    task_id: str,
    principal_id: str,
    title: str,
    lifecycle_state: str = "open",
    due_at: datetime | None = None,
    scheduled_at: datetime | None = None,
    archived_at: datetime | None = None,
    evidence_state: str = "accepted",
) -> None:
    """Insert a task directly into the database for testing."""
    now = datetime.now(UTC)
    connection.execute(
        tasks_table.insert().values(
            task_id=task_id,
            principal_id=principal_id,
            title=title,
            description=None,
            state="open",
            evidence_state=evidence_state,
            origin_kind="direct_principal",
            origin_evidence_ref=None,
            project_id=None,
            situation_id=None,
            due_at=due_at,
            opened_at=now,
            closed_at=None,
            closure_evidence_ref=None,
            accepted_by_review_decision_id=None,
            acceptance_kind="direct_principal",
            created_at=now,
            updated_at=now,
            lifecycle_state=lifecycle_state,
            priority="normal",
            scheduled_at=scheduled_at,
            deferred_until=None,
            archived_at=archived_at,
            version=1,
            recurrence_id=None,
            commitment_id=None,
            role=None,
        )
    )


class TestTodayTasksMembership:
    """Tests for the canonical Today Task membership contract."""

    def test_due_date_in_window_utc(self, repo_conn: tuple[SqlContinuityRepository, Connection]) -> None:
        """A task with due_at in Today's window is included."""
        repository, connection = repo_conn
        # Midnight UTC on TEST_DATE
        window_start = datetime.combine(TEST_DATE, datetime.min.time(), ZoneInfo(UTC_TZ))
        due_moment = window_start + timedelta(hours=12)
        
        _insert_task(connection, "tsk_due_in", PRINCIPAL_A, "Task Due Today", due_at=due_moment)
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 1
        assert result[0].task_id == "tsk_due_in"

    def test_scheduled_date_in_window_utc(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task with scheduled_at in Today's window is included."""
        window_start = datetime.combine(TEST_DATE, datetime.min.time(), ZoneInfo(UTC_TZ))
        scheduled_moment = window_start + timedelta(hours=14)
        
        _insert_task(connection, "tsk_sched_in", PRINCIPAL_A, "Task Scheduled Today", scheduled_at=scheduled_moment)
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 1
        assert result[0].task_id == "tsk_sched_in"

    def test_both_due_and_scheduled_in_window(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task with both due_at and scheduled_at in window appears once (not deduped as two items)."""
        window_start = datetime.combine(TEST_DATE, datetime.min.time(), ZoneInfo(UTC_TZ))
        due_moment = window_start + timedelta(hours=8)
        scheduled_moment = window_start + timedelta(hours=16)
        
        _insert_task(
            connection,
            "tsk_both",
            PRINCIPAL_A,
            "Task With Both",
            due_at=due_moment,
            scheduled_at=scheduled_moment,
        )
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 1
        assert result[0].task_id == "tsk_both"

    def test_due_date_before_today_excluded(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task with due_at before Today's window is excluded."""
        window_start = datetime.combine(TEST_DATE, datetime.min.time(), ZoneInfo(UTC_TZ))
        due_moment = window_start - timedelta(seconds=1)
        
        _insert_task(connection, "tsk_due_before", PRINCIPAL_A, "Task Due Yesterday", due_at=due_moment)
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 0

    def test_due_date_after_today_excluded(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task with due_at after Today's window is excluded."""
        window_end = datetime.combine(TEST_DATE + timedelta(days=1), datetime.min.time(), ZoneInfo(UTC_TZ))
        due_moment = window_end
        
        _insert_task(connection, "tsk_due_after", PRINCIPAL_A, "Task Due Tomorrow", due_at=due_moment)
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 0

    def test_scheduled_date_before_today_excluded(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task with scheduled_at before Today's window is excluded."""
        window_start = datetime.combine(TEST_DATE, datetime.min.time(), ZoneInfo(UTC_TZ))
        scheduled_moment = window_start - timedelta(seconds=1)
        
        _insert_task(connection, "tsk_sched_before", PRINCIPAL_A, "Task Scheduled Yesterday", scheduled_at=scheduled_moment)
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 0

    def test_scheduled_date_after_today_excluded(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task with scheduled_at after Today's window is excluded."""
        window_end = datetime.combine(TEST_DATE + timedelta(days=1), datetime.min.time(), ZoneInfo(UTC_TZ))
        scheduled_moment = window_end
        
        _insert_task(connection, "tsk_sched_after", PRINCIPAL_A, "Task Scheduled Tomorrow", scheduled_at=scheduled_moment)
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 0

    def test_no_due_or_scheduled_excluded(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task with neither due_at nor scheduled_at is excluded."""
        _insert_task(connection, "tsk_no_date", PRINCIPAL_A, "Task With No Date")
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 0

    def test_archived_task_excluded(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task that is archived is excluded, even if due_at is in window."""
        window_start = datetime.combine(TEST_DATE, datetime.min.time(), ZoneInfo(UTC_TZ))
        due_moment = window_start + timedelta(hours=12)
        archived_moment = datetime.now(UTC)
        
        _insert_task(
            connection,
            "tsk_archived",
            PRINCIPAL_A,
            "Task Archived",
            due_at=due_moment,
            archived_at=archived_moment,
        )
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 0

    def test_completed_lifecycle_excluded(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task with lifecycle_state=completed is excluded."""
        window_start = datetime.combine(TEST_DATE, datetime.min.time(), ZoneInfo(UTC_TZ))
        due_moment = window_start + timedelta(hours=12)
        
        _insert_task(
            connection,
            "tsk_completed",
            PRINCIPAL_A,
            "Task Completed",
            lifecycle_state="completed",
            due_at=due_moment,
        )
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 0

    def test_cancelled_lifecycle_excluded(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task with lifecycle_state=cancelled is excluded."""
        window_start = datetime.combine(TEST_DATE, datetime.min.time(), ZoneInfo(UTC_TZ))
        due_moment = window_start + timedelta(hours=12)
        
        _insert_task(
            connection,
            "tsk_cancelled",
            PRINCIPAL_A,
            "Task Cancelled",
            lifecycle_state="cancelled",
            due_at=due_moment,
        )
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 0

    def test_open_lifecycle_included(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task with lifecycle_state=open and due_at in window is included."""
        window_start = datetime.combine(TEST_DATE, datetime.min.time(), ZoneInfo(UTC_TZ))
        due_moment = window_start + timedelta(hours=12)
        
        _insert_task(
            connection,
            "tsk_open",
            PRINCIPAL_A,
            "Task Open",
            lifecycle_state="open",
            due_at=due_moment,
        )
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 1
        assert result[0].task_id == "tsk_open"

    def test_in_progress_lifecycle_included(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task with lifecycle_state=in_progress and due_at in window is included."""
        window_start = datetime.combine(TEST_DATE, datetime.min.time(), ZoneInfo(UTC_TZ))
        due_moment = window_start + timedelta(hours=12)
        
        _insert_task(
            connection,
            "tsk_in_progress",
            PRINCIPAL_A,
            "Task In Progress",
            lifecycle_state="in_progress",
            due_at=due_moment,
        )
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 1
        assert result[0].task_id == "tsk_in_progress"

    def test_waiting_lifecycle_included(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task with lifecycle_state=waiting and due_at in window is included."""
        window_start = datetime.combine(TEST_DATE, datetime.min.time(), ZoneInfo(UTC_TZ))
        due_moment = window_start + timedelta(hours=12)
        
        _insert_task(
            connection,
            "tsk_waiting",
            PRINCIPAL_A,
            "Task Waiting",
            lifecycle_state="waiting",
            due_at=due_moment,
        )
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 1
        assert result[0].task_id == "tsk_waiting"

    def test_blocked_lifecycle_included(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task with lifecycle_state=blocked and due_at in window is included."""
        window_start = datetime.combine(TEST_DATE, datetime.min.time(), ZoneInfo(UTC_TZ))
        due_moment = window_start + timedelta(hours=12)
        
        _insert_task(
            connection,
            "tsk_blocked",
            PRINCIPAL_A,
            "Task Blocked",
            lifecycle_state="blocked",
            due_at=due_moment,
        )
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 1
        assert result[0].task_id == "tsk_blocked"

    def test_principal_isolation_other_principal_excluded(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task belonging to a different principal is excluded."""
        window_start = datetime.combine(TEST_DATE, datetime.min.time(), ZoneInfo(UTC_TZ))
        due_moment = window_start + timedelta(hours=12)
        
        _insert_task(
            connection,
            "tsk_other_principal",
            PRINCIPAL_B,
            "Task Belonging to B",
            due_at=due_moment,
        )
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 0

    def test_timezone_america_new_york(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """Today's window is correctly computed for America/New_York timezone."""
        # In America/New_York on Sept 17, 2026, local midnight is earlier than UTC
        zone = ZoneInfo(US_EASTERN)
        local_start = datetime.combine(TEST_DATE, datetime.min.time(), zone)
        # Place a task at local noon, which should be in the window
        due_moment = local_start + timedelta(hours=12)
        
        _insert_task(
            connection,
            "tsk_ny_noon",
            PRINCIPAL_A,
            "Task NY Noon",
            due_at=due_moment,
        )
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, US_EASTERN)
        
        assert len(result) == 1
        assert result[0].task_id == "tsk_ny_noon"

    def test_timezone_europe_london(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """Today's window is correctly computed for Europe/London timezone."""
        zone = ZoneInfo(EUROPE_LONDON)
        local_start = datetime.combine(TEST_DATE, datetime.min.time(), zone)
        due_moment = local_start + timedelta(hours=12)
        
        _insert_task(
            connection,
            "tsk_london_noon",
            PRINCIPAL_A,
            "Task London Noon",
            due_at=due_moment,
        )
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, EUROPE_LONDON)
        
        assert len(result) == 1
        assert result[0].task_id == "tsk_london_noon"

    def test_timezone_asia_tokyo(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """Today's window is correctly computed for Asia/Tokyo timezone."""
        zone = ZoneInfo(ASIA_TOKYO)
        local_start = datetime.combine(TEST_DATE, datetime.min.time(), zone)
        due_moment = local_start + timedelta(hours=12)
        
        _insert_task(
            connection,
            "tsk_tokyo_noon",
            PRINCIPAL_A,
            "Task Tokyo Noon",
            due_at=due_moment,
        )
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, ASIA_TOKYO)
        
        assert len(result) == 1
        assert result[0].task_id == "tsk_tokyo_noon"

    def test_midnight_boundary_start_inclusive(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task with due_at at the start of Today's window (midnight) is included."""
        zone = ZoneInfo(UTC_TZ)
        midnight = datetime.combine(TEST_DATE, datetime.min.time(), zone)
        
        _insert_task(
            connection,
            "tsk_midnight_start",
            PRINCIPAL_A,
            "Task at Midnight Start",
            due_at=midnight,
        )
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 1
        assert result[0].task_id == "tsk_midnight_start"

    def test_midnight_boundary_end_exclusive(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task with due_at at the end of Today's window (next midnight) is excluded."""
        zone = ZoneInfo(UTC_TZ)
        next_midnight = datetime.combine(TEST_DATE + timedelta(days=1), datetime.min.time(), zone)
        
        _insert_task(
            connection,
            "tsk_midnight_end",
            PRINCIPAL_A,
            "Task at Midnight End",
            due_at=next_midnight,
        )
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 0

    def test_invalid_timezone_raises_error(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """An invalid IANA timezone raises ValueError."""
        with pytest.raises(ValueError, match="invalid IANA timezone"):
            repository.today_tasks(PRINCIPAL_A, TEST_DATE, "Invalid/Timezone")

    def test_empty_result_when_no_match(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """When no tasks match, an empty tuple is returned."""
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert result == ()

    def test_deferred_until_does_not_affect_today_membership(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """A task with deferred_until in the future is still included if due_at is in Today window."""
        window_start = datetime.combine(TEST_DATE, datetime.min.time(), ZoneInfo(UTC_TZ))
        due_moment = window_start + timedelta(hours=12)
        deferred_moment = datetime.now(UTC) + timedelta(days=7)
        
        now = datetime.now(UTC)
        connection.execute(
            tasks_table.insert().values(
                task_id="tsk_deferred",
                principal_id=PRINCIPAL_A,
                title="Task Deferred",
                description=None,
                state="open",
                evidence_state="accepted",
                origin_kind="direct_principal",
                origin_evidence_ref=None,
                project_id=None,
                situation_id=None,
                due_at=due_moment,
                opened_at=now,
                closed_at=None,
                closure_evidence_ref=None,
                accepted_by_review_decision_id=None,
                acceptance_kind="direct_principal",
                created_at=now,
                updated_at=now,
                lifecycle_state="open",
                priority="normal",
                scheduled_at=None,
                deferred_until=deferred_moment,
                archived_at=None,
                version=1,
                recurrence_id=None,
                commitment_id=None,
                role=None,
            )
        )
        connection.commit()
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 1
        assert result[0].task_id == "tsk_deferred"

    def test_multiple_tasks_all_included(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """Multiple tasks matching the criteria are all included in the result."""
        window_start = datetime.combine(TEST_DATE, datetime.min.time(), ZoneInfo(UTC_TZ))
        
        _insert_task(connection, "tsk_1", PRINCIPAL_A, "Task 1", due_at=window_start + timedelta(hours=1))
        _insert_task(connection, "tsk_2", PRINCIPAL_A, "Task 2", due_at=window_start + timedelta(hours=2))
        _insert_task(connection, "tsk_3", PRINCIPAL_A, "Task 3", due_at=window_start + timedelta(hours=3))
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 3
        task_ids = {task.task_id for task in result}
        assert task_ids == {"tsk_1", "tsk_2", "tsk_3"}

    def test_results_ordered_by_task_id(self, connection: Connection, repository: SqlContinuityRepository) -> None:
        """Results are ordered by task_id for determinism."""
        window_start = datetime.combine(TEST_DATE, datetime.min.time(), ZoneInfo(UTC_TZ))
        
        _insert_task(connection, "tsk_z", PRINCIPAL_A, "Task Z", due_at=window_start + timedelta(hours=1))
        _insert_task(connection, "tsk_a", PRINCIPAL_A, "Task A", due_at=window_start + timedelta(hours=2))
        _insert_task(connection, "tsk_m", PRINCIPAL_A, "Task M", due_at=window_start + timedelta(hours=3))
        
        result = repository.today_tasks(PRINCIPAL_A, TEST_DATE, UTC_TZ)
        
        assert len(result) == 3
        task_ids = [task.task_id for task in result]
        assert task_ids == ["tsk_a", "tsk_m", "tsk_z"]
