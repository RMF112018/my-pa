"""Project business time: the project's calendar date, working days, Due rules.

Every date-derived Constraint reading (Overdue, Due Soon, the default Due)
starts from one question — what is *today* on this project? — and the answer
is not the server's clock: it is a UTC instant projected through the Project's
own IANA timezone into a calendar date (`project_today`). When no timezone is
configured there is no defensible answer, so the function fails closed with
`project_timezone_unconfigured` rather than guessing; the browser and ChatLLM
never choose a fallback either.

Working days are Monday-Friday with no holiday calendar, and the two
functions mirror the spreadsheet these rules were accepted from:
`business_day_add` is Excel `WORKDAY` without holidays (the start date is not
one of the days added), `business_days_elapsed` is `NETWORKDAYS` (inclusive
of both ends). The default Due is +10 working days from Date Identified; Due
Soon runs from today through +7 working days; Overdue is strictly before
today. Both derivations are False outside the active states, and they are
mutually exclusive by construction (`<` today versus `>=` today).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from my_pa.domain.common.time import ensure_utc
from my_pa.domain.project_controls.constraint import (
    ACTIVE_CONSTRAINT_LIFECYCLE_STATES,
    ConstraintLifecycleState,
)

__all__ = [
    "DEFAULT_DUE_BUSINESS_DAYS",
    "DUE_SOON_BUSINESS_DAYS",
    "BusinessDayError",
    "ProjectTimezoneError",
    "business_day_add",
    "business_days_elapsed",
    "default_due_date",
    "due_soon_through",
    "is_due_soon",
    "is_overdue",
    "is_weekday",
    "project_today",
]

#: Default Due is this many working days after Date Identified.
DEFAULT_DUE_BUSINESS_DAYS: Final = 10
#: Due Soon covers today through this many working days ahead, inclusive.
DUE_SOON_BUSINESS_DAYS: Final = 7

_SATURDAY: Final = 5


class ProjectTimezoneError(ValueError):
    """The project date could not be determined. `code` is stable.

    `project_timezone_unconfigured`: no timezone was supplied. The Draft may
    still be saved with explicit dates; only a backend-defaulted date fails.
    `project_timezone_invalid`: the name is not a known IANA zone.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class BusinessDayError(ValueError):
    """A business-day computation was asked for something it does not define."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def is_weekday(value: date) -> bool:
    """Monday through Friday. No holiday calendar in v1."""
    return value.weekday() < _SATURDAY


def project_today(instant: datetime, timezone_name: str | None) -> date:
    """The calendar date of `instant` in the project's timezone.

    `instant` must be timezone-aware (a naive value raises the same
    `NaiveDatetimeError` every other public instant does); it is normalised
    to UTC first so a non-UTC aware value cannot skew the projection.
    """
    utc_instant = ensure_utc(instant)
    if timezone_name is None or not timezone_name.strip():
        raise ProjectTimezoneError(
            "project_timezone_unconfigured",
            "the project has no timezone, so no project date can be defaulted",
        )
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ProjectTimezoneError(
            "project_timezone_invalid", f"unknown IANA timezone {timezone_name!r}"
        ) from error
    return utc_instant.astimezone(zone).date()


def business_day_add(start: date, n: int) -> date:
    """`start` plus `n` working days; Excel `WORKDAY` without holidays.

    The start date is never one of the days counted, so a Friday plus one is
    the following Monday and a Saturday plus one is also Monday. `n == 0`
    returns `start` unchanged even on a weekend, as `WORKDAY` does. Negative
    `n` is refused (`business_day_offset_negative`): nothing in the accepted
    contract subtracts working days, and defining it would be speculation.
    """
    if n < 0:
        raise BusinessDayError(
            "business_day_offset_negative", "business_day_add does not subtract working days"
        )
    current = start
    remaining = n
    while remaining > 0:
        current += timedelta(days=1)
        if is_weekday(current):
            remaining -= 1
    return current


def business_days_elapsed(start: date, end: date) -> int:
    """Working days from `start` through `end`, both inclusive; Excel `NETWORKDAYS`.

    Monday through Friday of one week is 5; a Saturday to its Sunday is 0;
    Friday to the next Monday is 2. When `end` is before `start` the count is
    the negated inclusive count of the reversed range, as `NETWORKDAYS`
    returns, so the sign says which way round the dates were.
    """
    if end < start:
        return -business_days_elapsed(end, start)
    count = 0
    current = start
    while current <= end:
        if is_weekday(current):
            count += 1
        current += timedelta(days=1)
    return count


def default_due_date(date_identified: date) -> date:
    """The accepted default Due: ten working days after Date Identified."""
    return business_day_add(date_identified, DEFAULT_DUE_BUSINESS_DAYS)


def due_soon_through(today: date) -> date:
    """The last date counted as Due Soon: seven working days after `today`."""
    return business_day_add(today, DUE_SOON_BUSINESS_DAYS)


def is_overdue(
    lifecycle_state: ConstraintLifecycleState, due_date: date | None, today: date
) -> bool:
    """Active, has a Due Date, and that date is strictly before `today`."""
    if lifecycle_state not in ACTIVE_CONSTRAINT_LIFECYCLE_STATES or due_date is None:
        return False
    return due_date < today


def is_due_soon(
    lifecycle_state: ConstraintLifecycleState, due_date: date | None, today: date
) -> bool:
    """Active, has a Due Date, and that date is in `today` through `due_soon_through(today)`."""
    if lifecycle_state not in ACTIVE_CONSTRAINT_LIFECYCLE_STATES or due_date is None:
        return False
    return today <= due_date <= due_soon_through(today)
