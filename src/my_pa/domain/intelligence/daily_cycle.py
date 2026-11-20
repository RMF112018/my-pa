"""When the daily Morning Intelligence cycle is due, and the key it begins under.

ADR-010 amendment of 2026-11-20. Pure and injectable: the caller supplies the
instant, the zone and the last completed run date, so the rule is tested without
a clock or a database. Dates are taken on the local calendar of `zone`, so a
daylight-saving change neither repeats nor skips a run: there is exactly one
local midnight per local date, and the rule compares dates, not durations.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Final
from zoneinfo import ZoneInfo

from my_pa.domain.intelligence.catalog import CYCLE_MORNING_INTELLIGENCE

__all__ = [
    "DEFAULT_CYCLE_TIMEZONE",
    "SCHEDULED_AUTOMATION_PLATFORM",
    "SCHEDULED_RUN_TIME",
    "due",
    "scheduled_idempotency_key",
]

#: The operator's zone (decision of 2026-11-20); `MY_PA_CYCLE_SCHEDULER_TIMEZONE`.
DEFAULT_CYCLE_TIMEZONE: Final = "America/New_York"

#: Local wall-clock time the run is due at. Fixed, not configurable.
SCHEDULED_RUN_TIME: Final = time(0, 0)

#: The `automation_platform` the scheduler's `reports.begin_cycle` names.
SCHEDULED_AUTOMATION_PLATFORM: Final = "my_pa_scheduler"


def due(now: datetime, *, zone: ZoneInfo, last_run: date | None) -> date | None:
    """The business date a run is due for at `now`, or `None` when none is due.

    `last_run` is the business date of the last run whose begin step completed.
    `None` (a process that has not run yet) makes the current local date due
    at once, which is the catch-up rule: a missed midnight is made up once,
    for the latest missed date, and earlier missed dates are never backfilled.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    # The run time is local midnight, so every instant of a local date is at or
    # after it: the due date is simply the local calendar date.
    today = now.astimezone(zone).date()
    if last_run is not None and last_run >= today:
        return None
    return today


def scheduled_idempotency_key(business_date: date) -> str:
    """`auto-morning_intelligence-<YYYY-MM-DD>`: one key per business date."""
    return f"auto-{CYCLE_MORNING_INTELLIGENCE}-{business_date.isoformat()}"
