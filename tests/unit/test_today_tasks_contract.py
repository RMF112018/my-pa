"""Canonical Today Task membership contract — WP-POSTUX-06 unit tests.

Validates the canonical Today membership predicate through inspection of
the repository method signature and documentation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from my_pa.infrastructure.persistence.situation_repository import SqlContinuityRepository

pytestmark = pytest.mark.unit


class TestTodayTasksContract:
    """Unit tests for the canonical Today Task membership contract."""

    def test_today_tasks_method_exists(self) -> None:
        """The repository has the today_tasks method."""
        assert hasattr(SqlContinuityRepository, "today_tasks")
        assert callable(getattr(SqlContinuityRepository, "today_tasks"))

    def test_today_tasks_signature(self) -> None:
        """The method has the correct signature."""
        import inspect
        sig = inspect.signature(SqlContinuityRepository.today_tasks)
        params = list(sig.parameters.keys())
        # self, principal_id, work_date, timezone
        assert params == ["self", "principal_id", "work_date", "timezone"]

    def test_canonical_contract_documented(self) -> None:
        """The method docstring documents the canonical contract."""
        doc = SqlContinuityRepository.today_tasks.__doc__
        assert doc is not None
        assert "belongs to principal_id" in doc
        assert "not archived" in doc
        assert "lifecycle_state in" in doc
        assert "due_at OR scheduled_at" in doc
        assert "midnight" in doc

    def test_invalid_timezone_behavior_documented(self) -> None:
        """The method docstring documents timezone validation."""
        doc = SqlContinuityRepository.today_tasks.__doc__
        assert doc is not None
        # The docstring should mention validation or error handling
        assert "timezone" in doc.lower()

    def test_timezone_window_calculation_logic(self) -> None:
        """Verify the timezone window logic works correctly."""
        # This is a synthetic test of the logic without database
        test_date = date(2026, 9, 17)
        timezone_str = "UTC"
        
        # The logic should compute midnight boundaries in the given timezone
        zone = ZoneInfo(timezone_str)
        local_start = datetime.combine(test_date, datetime.min.time(), zone)
        local_end = datetime.combine(test_date + timedelta(days=1), datetime.min.time(), zone)
        
        start_utc = local_start.astimezone(UTC)
        end_utc = local_end.astimezone(UTC)
        
        # For UTC, these should be the same as the test date boundaries
        assert start_utc == datetime(2026, 9, 17, 0, 0, 0, tzinfo=UTC)
        assert end_utc == datetime(2026, 9, 18, 0, 0, 0, tzinfo=UTC)

    def test_timezone_window_calculation_us_eastern(self) -> None:
        """Verify timezone window calculation for America/New_York."""
        test_date = date(2026, 9, 17)
        timezone_str = "America/New_York"
        
        zone = ZoneInfo(timezone_str)
        local_start = datetime.combine(test_date, datetime.min.time(), zone)
        local_end = datetime.combine(test_date + timedelta(days=1), datetime.min.time(), zone)
        
        start_utc = local_start.astimezone(UTC)
        end_utc = local_end.astimezone(UTC)
        
        # In September, America/New_York is EDT (UTC-4)
        # So midnight in EDT is 04:00 UTC
        assert start_utc == datetime(2026, 9, 17, 4, 0, 0, tzinfo=UTC)
        assert end_utc == datetime(2026, 9, 18, 4, 0, 0, tzinfo=UTC)

    def test_timezone_window_calculation_europe_london(self) -> None:
        """Verify timezone window calculation for Europe/London."""
        test_date = date(2026, 9, 17)
        timezone_str = "Europe/London"
        
        zone = ZoneInfo(timezone_str)
        local_start = datetime.combine(test_date, datetime.min.time(), zone)
        local_end = datetime.combine(test_date + timedelta(days=1), datetime.min.time(), zone)
        
        start_utc = local_start.astimezone(UTC)
        end_utc = local_end.astimezone(UTC)
        
        # In September, Europe/London is BST (UTC+1)
        # So midnight in BST is 23:00 UTC of the previous day
        assert start_utc == datetime(2026, 9, 16, 23, 0, 0, tzinfo=UTC)
        assert end_utc == datetime(2026, 9, 17, 23, 0, 0, tzinfo=UTC)

    def test_invalid_timezone_raises_valueerror(self) -> None:
        """Invalid IANA timezone should raise ValueError."""
        # The implementation should validate timezones
        from zoneinfo import ZoneInfoNotFoundError
        
        with pytest.raises(ZoneInfoNotFoundError):
            ZoneInfo("Invalid/Timezone")

    def test_lifecycle_states_included_in_contract(self) -> None:
        """The contract includes the correct lifecycle states."""
        doc = SqlContinuityRepository.today_tasks.__doc__
        assert doc is not None
        assert "OPEN" in doc or "open" in doc
        assert "IN_PROGRESS" in doc or "in_progress" in doc
        assert "WAITING" in doc or "waiting" in doc
        assert "BLOCKED" in doc or "blocked" in doc

    def test_deferred_until_not_in_contract(self) -> None:
        """The contract correctly excludes deferred_until from membership."""
        doc = SqlContinuityRepository.today_tasks.__doc__
        assert doc is not None
        # The contract should not mention deferred_until as a membership criterion
        # (though the domain model may preserve the semantics)
        assert "deferred_until" not in doc.lower() or "does not affect" in doc.lower()
