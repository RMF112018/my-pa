"""Service-layer tests for TaskManagementService.list_today_tasks — WP-POSTUX-06.

Validates that the service method correctly delegates to the continuity repository
and passes through timezone validation errors.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Final
from unittest.mock import Mock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from my_pa.application.tasks import TaskManagementService
from my_pa.contracts.ports import ContinuityRepository
from my_pa.domain.situation.continuity import (
    ContinuityAcceptanceKind,
    ContinuityEvidenceState,
    Task,
    TaskState,
)

pytestmark = pytest.mark.unit

TEST_DATE: Final = date(2026, 9, 17)
TEST_PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
TEST_TASK_ID: Final = "tsk_aaaa0001aaaa0001aaaa0001"


class TestTaskManagementServiceTodayTasks:
    """Service-layer tests for list_today_tasks method."""

    def test_list_today_tasks_calls_repository_with_correct_parameters(self) -> None:
        """The service calls repository.today_tasks with passed parameters."""
        # Arrange
        mock_repo = Mock(spec=ContinuityRepository)
        service = TaskManagementService(unit_of_work=Mock())
        
        expected_tasks = (
            Task(
                task_id=TEST_TASK_ID,
                principal_id=TEST_PRINCIPAL,
                title="Test Task",
                state=TaskState.OPEN,
                evidence_state=ContinuityEvidenceState.ACCEPTED,
                acceptance_kind=ContinuityAcceptanceKind.DIRECT_PRINCIPAL,
                origin_evidence_ref=None,
                opened_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ),
        )
        mock_repo.today_tasks.return_value = expected_tasks
        
        # Act
        result = service.list_today_tasks(
            principal_id=TEST_PRINCIPAL,
            work_date=TEST_DATE,
            timezone="America/New_York",
            continuity_repo=mock_repo,
        )
        
        # Assert
        assert result == expected_tasks
        mock_repo.today_tasks.assert_called_once_with(
            TEST_PRINCIPAL,
            TEST_DATE,
            "America/New_York",
        )

    def test_list_today_tasks_propagates_repository_timezone_error(self) -> None:
        """Invalid timezone error from repository is raised to caller."""
        mock_repo = Mock(spec=ContinuityRepository)
        mock_repo.today_tasks.side_effect = ValueError("invalid IANA timezone: Foo/Bar")
        
        service = TaskManagementService(unit_of_work=Mock())
        
        with pytest.raises(ValueError, match="invalid IANA timezone"):
            service.list_today_tasks(
                principal_id=TEST_PRINCIPAL,
                work_date=TEST_DATE,
                timezone="Foo/Bar",
                continuity_repo=mock_repo,
            )

    def test_list_today_tasks_returns_empty_tuple_when_no_matches(self) -> None:
        """When repository returns empty, service returns empty tuple."""
        mock_repo = Mock(spec=ContinuityRepository)
        mock_repo.today_tasks.return_value = ()
        
        service = TaskManagementService(unit_of_work=Mock())
        
        result = service.list_today_tasks(
            principal_id=TEST_PRINCIPAL,
            work_date=TEST_DATE,
            timezone="UTC",
            continuity_repo=mock_repo,
        )
        
        assert result == ()

    def test_list_today_tasks_preserves_task_order(self) -> None:
        """Tasks returned from repository are returned in the same order."""
        mock_repo = Mock(spec=ContinuityRepository)
        
        task_ids = [f"tsk_aaaa000{i}bbbb000{i}cccc000{i}" for i in range(1, 6)]
        tasks = tuple(
            Task(
                task_id=task_ids[i - 1],
                principal_id=TEST_PRINCIPAL,
                title=f"Task {i}",
                state=TaskState.OPEN,
                evidence_state=ContinuityEvidenceState.ACCEPTED,
                acceptance_kind=ContinuityAcceptanceKind.DIRECT_PRINCIPAL,
                origin_evidence_ref=None,
                opened_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            for i in range(1, 6)
        )
        mock_repo.today_tasks.return_value = tasks
        
        service = TaskManagementService(unit_of_work=Mock())
        
        result = service.list_today_tasks(
            principal_id=TEST_PRINCIPAL,
            work_date=TEST_DATE,
            timezone="UTC",
            continuity_repo=mock_repo,
        )
        
        assert result == tasks
        assert [t.task_id for t in result] == task_ids

    def test_list_today_tasks_does_not_mutate_tasks(self) -> None:
        """The service does not modify or mutate tasks returned from repository."""
        mock_repo = Mock(spec=ContinuityRepository)
        
        task_id = "tsk_bbbb0001cccc0001dddd0001"
        now = datetime.now(UTC)
        original_task = Task(
            task_id=task_id,
            principal_id=TEST_PRINCIPAL,
            title="Original Task",
            state=TaskState.CLOSED,
            evidence_state=ContinuityEvidenceState.ACCEPTED,
            acceptance_kind=ContinuityAcceptanceKind.DIRECT_PRINCIPAL,
            origin_evidence_ref=None,
            opened_at=now,
            created_at=now,
            updated_at=now,
            closed_at=now,
        )
        mock_repo.today_tasks.return_value = (original_task,)
        
        service = TaskManagementService(unit_of_work=Mock())
        
        result = service.list_today_tasks(
            principal_id=TEST_PRINCIPAL,
            work_date=TEST_DATE,
            timezone="UTC",
            continuity_repo=mock_repo,
        )
        
        # Verify task is returned unchanged
        assert result[0].task_id == original_task.task_id
        assert result[0].title == original_task.title
        assert result[0].state == original_task.state

    def test_list_today_tasks_method_is_readonly(self) -> None:
        """The list_today_tasks method does not take any mutation parameters."""
        import inspect
        
        sig = inspect.signature(TaskManagementService.list_today_tasks)
        # Should not have any mutation-related parameters like expected_version, actor, etc.
        assert "expected_version" not in sig.parameters
        assert "actor" not in sig.parameters
        assert "idempotency_key" not in sig.parameters
        
        # Should have the read-only ones
        assert "principal_id" in sig.parameters
        assert "work_date" in sig.parameters
        assert "timezone" in sig.parameters
        assert "continuity_repo" in sig.parameters

    def test_list_today_tasks_documentation_complete(self) -> None:
        """The method docstring documents the canonical contract."""
        doc = TaskManagementService.list_today_tasks.__doc__
        assert doc is not None
        assert "canonical Today Task set" in doc
        assert "principal_id" in doc
        assert "not archived" in doc
        assert "lifecycle" in doc
        assert "due_at OR scheduled_at" in doc
        assert "midnight" in doc
        assert "timezone" in doc

    @pytest.mark.parametrize("timezone", [
        "UTC",
        "America/New_York",
        "Europe/London",
        "Asia/Tokyo",
        "Australia/Sydney",
    ])
    def test_list_today_tasks_accepts_valid_timezones(self, timezone: str) -> None:
        """The method accepts valid IANA timezones."""
        mock_repo = Mock(spec=ContinuityRepository)
        mock_repo.today_tasks.return_value = ()
        
        service = TaskManagementService(unit_of_work=Mock())
        
        # Should not raise
        service.list_today_tasks(
            principal_id=TEST_PRINCIPAL,
            work_date=TEST_DATE,
            timezone=timezone,
            continuity_repo=mock_repo,
        )
        
        mock_repo.today_tasks.assert_called_once()
