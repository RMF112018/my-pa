"""Unit tests for the PC-CM-IMP-WP01 project business-time rules."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from my_pa.domain.common.time import NaiveDatetimeError
from my_pa.domain.project_controls.business_time import (
    DEFAULT_DUE_BUSINESS_DAYS,
    DUE_SOON_BUSINESS_DAYS,
    BusinessDayError,
    ProjectTimezoneError,
    business_day_add,
    business_days_elapsed,
    default_due_date,
    due_soon_through,
    is_due_soon,
    is_overdue,
    is_weekday,
    project_today,
)
from my_pa.domain.project_controls.constraint import (
    ACTIVE_CONSTRAINT_LIFECYCLE_STATES,
    ConstraintLifecycleState,
)

S = ConstraintLifecycleState

# 2026-09-07 is a Monday.
MON = date(2026, 9, 7)
TUE = MON + timedelta(days=1)
FRI = MON + timedelta(days=4)
SAT = MON + timedelta(days=5)
SUN = MON + timedelta(days=6)
NEXT_MON = MON + timedelta(days=7)


def test_calendar_anchor_is_a_monday() -> None:
    assert MON.weekday() == 0
    assert is_weekday(FRI) and not is_weekday(SAT) and not is_weekday(SUN)


# --- project_today ---


@pytest.mark.parametrize(
    ("instant", "timezone_name", "expected"),
    [
        # 03:00Z on the 8th is still the evening of the 7th on the US west coast.
        (datetime(2026, 9, 8, 3, 0, tzinfo=UTC), "America/Los_Angeles", date(2026, 9, 7)),
        (datetime(2026, 9, 8, 7, 30, tzinfo=UTC), "America/Los_Angeles", date(2026, 9, 8)),
        # 13:00Z on the 7th is already the 8th in Auckland (UTC+12 in September).
        (datetime(2026, 9, 7, 13, 0, tzinfo=UTC), "Pacific/Auckland", date(2026, 9, 8)),
        (datetime(2026, 9, 7, 11, 0, tzinfo=UTC), "Pacific/Auckland", date(2026, 9, 7)),
        # Tokyo (UTC+9, no DST): 15:00Z is midnight next day.
        (datetime(2026, 9, 7, 15, 0, tzinfo=UTC), "Asia/Tokyo", date(2026, 9, 8)),
        (datetime(2026, 9, 7, 14, 59, tzinfo=UTC), "Asia/Tokyo", date(2026, 9, 7)),
        (datetime(2026, 9, 7, 23, 59, tzinfo=UTC), "UTC", date(2026, 9, 7)),
    ],
)
def test_project_today_projects_utc_instant_through_project_timezone(
    instant: datetime, timezone_name: str, expected: date
) -> None:
    assert project_today(instant, timezone_name) == expected


def test_project_today_normalises_a_non_utc_aware_instant_first() -> None:
    # 20:00 at UTC-7 is 03:00Z next day, which is still the 7th in Los Angeles.
    instant = datetime(2026, 9, 7, 20, 0, tzinfo=timezone(timedelta(hours=-7)))
    assert project_today(instant, "America/Los_Angeles") == date(2026, 9, 7)
    assert project_today(instant, "Asia/Tokyo") == date(2026, 9, 8)


@pytest.mark.parametrize("timezone_name", [None, "", "   "])
def test_missing_timezone_fails_closed_with_the_contract_code(timezone_name: str | None) -> None:
    with pytest.raises(ProjectTimezoneError) as excinfo:
        project_today(datetime(2026, 9, 7, 12, 0, tzinfo=UTC), timezone_name)
    assert excinfo.value.code == "project_timezone_unconfigured"


@pytest.mark.parametrize("timezone_name", ["Mars/Olympus", "PST", "America/Los Angeles", "../etc"])
def test_unknown_timezone_is_a_distinct_error(timezone_name: str) -> None:
    with pytest.raises(ProjectTimezoneError) as excinfo:
        project_today(datetime(2026, 9, 7, 12, 0, tzinfo=UTC), timezone_name)
    assert excinfo.value.code == "project_timezone_invalid"


def test_naive_instant_is_refused_before_timezone_is_considered() -> None:
    with pytest.raises(NaiveDatetimeError):
        project_today(datetime(2026, 9, 7, 12, 0), "UTC")
    with pytest.raises(NaiveDatetimeError):
        project_today(datetime(2026, 9, 7, 12, 0), None)


# --- business_day_add (WORKDAY) ---


@pytest.mark.parametrize(
    ("start", "n", "expected"),
    [
        (MON, 0, MON),
        (SAT, 0, SAT),
        (MON, 1, TUE),
        (MON, 4, FRI),
        (MON, 5, NEXT_MON),
        (FRI, 1, NEXT_MON),
        (SAT, 1, NEXT_MON),
        (SUN, 1, NEXT_MON),
        (FRI, 2, NEXT_MON + timedelta(days=1)),
        (MON, 10, MON + timedelta(days=14)),
        (TUE, 10, TUE + timedelta(days=14)),
        (FRI, 10, FRI + timedelta(days=14)),
        (MON, 7, MON + timedelta(days=9)),
    ],
)
def test_business_day_add_counts_monday_to_friday_excluding_start(
    start: date, n: int, expected: date
) -> None:
    assert business_day_add(start, n) == expected
    assert n == 0 or is_weekday(business_day_add(start, n))


def test_business_day_add_refuses_negative_offsets() -> None:
    with pytest.raises(BusinessDayError) as excinfo:
        business_day_add(MON, -1)
    assert excinfo.value.code == "business_day_offset_negative"


# --- business_days_elapsed (NETWORKDAYS) ---


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (MON, MON, 1),
        (MON, FRI, 5),
        (SAT, SUN, 0),
        (SAT, SAT, 0),
        (FRI, NEXT_MON, 2),
        (MON, SUN, 5),
        (MON, NEXT_MON, 6),
        (MON, MON + timedelta(days=13), 10),
        (FRI, MON, -5),
        (NEXT_MON, FRI, -2),
    ],
)
def test_business_days_elapsed_is_inclusive_weekday_count(
    start: date, end: date, expected: int
) -> None:
    assert business_days_elapsed(start, end) == expected


# --- default Due and Due Soon window ---


def test_default_due_is_ten_business_days_after_date_identified() -> None:
    assert DEFAULT_DUE_BUSINESS_DAYS == 10
    assert default_due_date(MON) == MON + timedelta(days=14)
    assert default_due_date(FRI) == FRI + timedelta(days=14)
    assert default_due_date(SAT) == business_day_add(SAT, 10) == NEXT_MON + timedelta(days=11)


def test_due_soon_through_is_seven_business_days_after_today() -> None:
    assert DUE_SOON_BUSINESS_DAYS == 7
    assert due_soon_through(MON) == MON + timedelta(days=9)
    assert due_soon_through(FRI) == FRI + timedelta(days=11)


@pytest.mark.parametrize("state", sorted(ACTIVE_CONSTRAINT_LIFECYCLE_STATES))
def test_due_soon_and_overdue_boundaries(state: ConstraintLifecycleState) -> None:
    today = MON
    through = due_soon_through(today)
    assert is_due_soon(state, today, today) is True
    assert is_overdue(state, today, today) is False
    assert is_due_soon(state, through, today) is True
    assert is_due_soon(state, through + timedelta(days=1), today) is False
    assert is_overdue(state, today - timedelta(days=1), today) is True
    assert is_due_soon(state, today - timedelta(days=1), today) is False
    assert is_overdue(state, None, today) is False
    assert is_due_soon(state, None, today) is False


@pytest.mark.parametrize("state", [S.DRAFT, S.CLOSED, S.VOID])
def test_draft_and_terminal_are_neither_overdue_nor_due_soon(
    state: ConstraintLifecycleState,
) -> None:
    for due in (MON - timedelta(days=30), MON, MON + timedelta(days=3)):
        assert is_overdue(state, due, MON) is False
        assert is_due_soon(state, due, MON) is False


@pytest.mark.parametrize("offset", range(-15, 31))
@pytest.mark.parametrize("today", [MON, FRI, SAT])
def test_overdue_and_due_soon_are_mutually_exclusive(today: date, offset: int) -> None:
    due = today + timedelta(days=offset)
    overdue = is_overdue(S.PENDING, due, today)
    due_soon = is_due_soon(S.PENDING, due, today)
    assert not (overdue and due_soon)
    assert overdue == (offset < 0)
    assert due_soon == (offset >= 0 and due <= due_soon_through(today))
