"""S7-0: the MY-PA standard calendar `my-pa-us-40h-v1` (FAST).

Contract `docs/architecture/schedule-xer-import-contract.md` section 11.6 and
its planned tests (acceptance E6): each fixed-date holiday on a Saturday, a
Sunday and a weekday (the named examples included); New Year on a Saturday
crossing into the previous year and at the window edge; each nth-weekday rule,
"last Monday of May" with 5 and with 4 Mondays; leap years 2000, 2024 and 2096;
Juneteenth absent in 2020 and present in 2021; 2099 complete; the count per
year; the horizon clipping; determinism of the canonical bytes. Every expected
date below is written out literally; the oracle at the end recomputes every
year from a brute-force month scan that shares no code with the generator.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Final

import pytest

from my_pa.domain.schedule.scenario.canonical import content_bytes
from my_pa.domain.schedule.scenario.model import parse_instant
from my_pa.domain.schedule.scenario.standard_calendar import (
    STANDARD_CALENDAR_KEY,
    STANDARD_WORKDAY,
    FederalHoliday,
    federal_holidays,
    materialized_years,
    standard_calendar,
    standard_calendar_horizon_exceeded,
    standard_calendar_key,
)
from tests.fixtures.schedule_scenario import DAY, network, task

H = FederalHoliday


def _observed(year: int) -> dict[FederalHoliday, date]:
    return {item.holiday: item.observed for item in federal_holidays(year)}


# --- fixed-date holidays: Saturday, Sunday, weekday ------------------------------------------

#: (holiday, year, observed): the named section 11.6 examples first, then one of each
#: fixed-date holiday on a Saturday (Friday before), a Sunday (Monday after) and a weekday.
FIXED_CASES: Final = (
    # Named examples.
    (H.INDEPENDENCE_DAY, 2099, date(2099, 7, 3)),  # Saturday -> Friday 3 Jul
    (H.CHRISTMAS_DAY, 2021, date(2021, 12, 24)),  # Saturday -> Friday 24 Dec
    (H.VETERANS_DAY, 2000, date(2000, 11, 10)),  # Saturday -> Friday 10 Nov
    (H.NEW_YEARS_DAY, 2022, date(2021, 12, 31)),  # Saturday -> Friday 31 Dec 2021
    # New Year's Day.
    (H.NEW_YEARS_DAY, 2023, date(2023, 1, 2)),  # Sunday
    (H.NEW_YEARS_DAY, 2021, date(2021, 1, 1)),  # Friday
    # Juneteenth.
    (H.JUNETEENTH, 2021, date(2021, 6, 18)),  # Saturday
    (H.JUNETEENTH, 2022, date(2022, 6, 20)),  # Sunday
    (H.JUNETEENTH, 2023, date(2023, 6, 19)),  # Monday
    # Independence Day.
    (H.INDEPENDENCE_DAY, 2026, date(2026, 7, 3)),  # Saturday
    (H.INDEPENDENCE_DAY, 2021, date(2021, 7, 5)),  # Sunday
    (H.INDEPENDENCE_DAY, 2022, date(2022, 7, 4)),  # Monday
    # Veterans Day.
    (H.VETERANS_DAY, 2023, date(2023, 11, 10)),  # Saturday
    (H.VETERANS_DAY, 2029, date(2029, 11, 12)),  # Sunday
    (H.VETERANS_DAY, 2021, date(2021, 11, 11)),  # Thursday
    # Christmas Day.
    (H.CHRISTMAS_DAY, 2022, date(2022, 12, 26)),  # Sunday
    (H.CHRISTMAS_DAY, 2023, date(2023, 12, 25)),  # Monday
)


@pytest.mark.parametrize(("holiday", "year", "observed"), FIXED_CASES)
def test_fixed_date_holiday_is_observed_by_the_weekend_rule(
    holiday: FederalHoliday, year: int, observed: date
) -> None:
    assert _observed(year)[holiday] == observed


def test_each_fixed_date_holiday_meets_saturday_sunday_and_a_weekday() -> None:
    fixed = {H.NEW_YEARS_DAY, H.JUNETEENTH, H.INDEPENDENCE_DAY, H.VETERANS_DAY, H.CHRISTMAS_DAY}
    seen: dict[FederalHoliday, set[str]] = {holiday: set() for holiday in fixed}
    for holiday, year, observed in FIXED_CASES:
        actual = {
            H.NEW_YEARS_DAY: date(year, 1, 1),
            H.JUNETEENTH: date(year, 6, 19),
            H.INDEPENDENCE_DAY: date(year, 7, 4),
            H.VETERANS_DAY: date(year, 11, 11),
            H.CHRISTMAS_DAY: date(year, 12, 25),
        }[holiday]
        weekday = actual.weekday()
        seen[holiday].add("sat" if weekday == 5 else "sun" if weekday == 6 else "weekday")
        assert observed.weekday() < 5
    assert all(kinds == {"sat", "sun", "weekday"} for kinds in seen.values()), seen


def test_new_year_on_a_saturday_crosses_into_the_previous_year() -> None:
    assert date(2022, 1, 1).weekday() == 5
    assert _observed(2022)[H.NEW_YEARS_DAY] == date(2021, 12, 31)
    # It is 2022's holiday, so 2021 carries 11 holidays of its own and 2022's on 31 Dec.
    assert date(2021, 12, 31) not in {item.observed for item in federal_holidays(2021)}


def test_new_year_2000_is_dropped_at_the_window_edge() -> None:
    assert date(2000, 1, 1).weekday() == 5
    assert H.NEW_YEARS_DAY not in _observed(2000)
    assert len(federal_holidays(2000)) == 9


# --- nth-weekday rules ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("holiday", "year", "observed"),
    [
        (H.MARTIN_LUTHER_KING_JR_DAY, 2027, date(2027, 1, 18)),  # 3rd Monday of January
        (H.MARTIN_LUTHER_KING_JR_DAY, 2024, date(2024, 1, 15)),
        (H.PRESIDENTS_DAY, 2027, date(2027, 2, 15)),  # 3rd Monday of February
        (H.MEMORIAL_DAY, 2027, date(2027, 5, 31)),  # May 2027 has 5 Mondays
        (H.MEMORIAL_DAY, 2026, date(2026, 5, 25)),  # May 2026 has 4 Mondays
        (H.LABOR_DAY, 2027, date(2027, 9, 6)),  # 1st Monday of September
        (H.LABOR_DAY, 2025, date(2025, 9, 1)),  # the 1st is the Monday
        (H.COLUMBUS_DAY, 2027, date(2027, 10, 11)),  # 2nd Monday of October
        (H.THANKSGIVING_DAY, 2027, date(2027, 11, 25)),  # 4th Thursday of November
        (H.THANKSGIVING_DAY, 2026, date(2026, 11, 26)),
    ],
)
def test_nth_weekday_rules(holiday: FederalHoliday, year: int, observed: date) -> None:
    assert _observed(year)[holiday] == observed


def test_memorial_day_is_the_last_monday_with_5_and_with_4_mondays() -> None:
    for year, mondays, last in ((2027, 5, date(2027, 5, 31)), (2026, 4, date(2026, 5, 25))):
        in_may = [date(year, 5, d) for d in range(1, 32) if date(year, 5, d).weekday() == 0]
        assert len(in_may) == mondays
        assert _observed(year)[H.MEMORIAL_DAY] == last == in_may[-1]


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (
            2000,  # a century leap year; 1 Jan is a Saturday
            {
                H.MARTIN_LUTHER_KING_JR_DAY: date(2000, 1, 17),
                H.PRESIDENTS_DAY: date(2000, 2, 21),
                H.MEMORIAL_DAY: date(2000, 5, 29),
                H.LABOR_DAY: date(2000, 9, 4),
                H.COLUMBUS_DAY: date(2000, 10, 9),
                H.THANKSGIVING_DAY: date(2000, 11, 23),
            },
        ),
        (
            2024,
            {
                H.MARTIN_LUTHER_KING_JR_DAY: date(2024, 1, 15),
                H.PRESIDENTS_DAY: date(2024, 2, 19),
                H.MEMORIAL_DAY: date(2024, 5, 27),
                H.LABOR_DAY: date(2024, 9, 2),
                H.COLUMBUS_DAY: date(2024, 10, 14),
                H.THANKSGIVING_DAY: date(2024, 11, 28),
            },
        ),
        (
            2096,
            {
                H.MARTIN_LUTHER_KING_JR_DAY: date(2096, 1, 16),
                H.PRESIDENTS_DAY: date(2096, 2, 20),
                H.MEMORIAL_DAY: date(2096, 5, 28),
                H.LABOR_DAY: date(2096, 9, 3),
                H.COLUMBUS_DAY: date(2096, 10, 8),
                H.THANKSGIVING_DAY: date(2096, 11, 22),
            },
        ),
    ],
)
def test_leap_years_take_every_nth_weekday_rule(
    year: int, expected: dict[FederalHoliday, date]
) -> None:
    assert date(year, 2, 29).month == 2  # a leap year
    observed = _observed(year)
    for holiday, when in expected.items():
        assert observed[holiday] == when, holiday


# --- Juneteenth, 2099, counts ----------------------------------------------------------------


def test_juneteenth_starts_in_2021() -> None:
    assert H.JUNETEENTH not in _observed(2020)
    assert _observed(2021)[H.JUNETEENTH] == date(2021, 6, 18)  # Saturday 19 -> Friday 18


def test_2099_is_complete() -> None:
    assert [item.observed for item in federal_holidays(2099)] == [
        date(2099, 1, 1),
        date(2099, 1, 19),
        date(2099, 2, 16),
        date(2099, 5, 25),
        date(2099, 6, 19),
        date(2099, 7, 3),
        date(2099, 9, 7),
        date(2099, 10, 12),
        date(2099, 11, 11),
        date(2099, 11, 26),
        date(2099, 12, 25),
    ]
    assert [item.holiday for item in federal_holidays(2099)] == list(FederalHoliday)


def test_the_count_per_year() -> None:
    """10 before 2021 and 11 from 2021, less an observed day outside the window (2000)."""
    counts = {year: len(federal_holidays(year)) for year in range(2000, 2100)}
    assert counts[2000] == 9
    assert all(counts[year] == 10 for year in range(2001, 2021))
    assert all(counts[year] == 11 for year in range(2021, 2100))


def test_years_outside_the_window_are_refused() -> None:
    for year in (1999, 2100):
        with pytest.raises(ValueError, match=r"2000\.\.2099"):
            federal_holidays(year)


# --- materialization, keys, determinism ------------------------------------------------------


def test_the_horizon_is_clipped_to_the_window() -> None:
    assert materialized_years(2027) == range(2025, 2048)
    assert materialized_years(2001) == range(2000, 2022)
    assert materialized_years(2090) == range(2088, 2100)
    assert len(standard_calendar(2027).exceptions) == 23 * 11 == 253
    assert len(standard_calendar(2001).exceptions) == 9 + 20 * 10 + 11
    assert len(standard_calendar(2090).exceptions) == 12 * 11
    assert max(len(standard_calendar(year).exceptions) for year in range(2000, 2101)) <= 253


def test_the_standard_calendar_shape() -> None:
    calendar = standard_calendar(2027)
    assert calendar.key == STANDARD_CALENDAR_KEY == "my-pa-us-40h-v1"
    assert STANDARD_WORKDAY == ((480, 960),)
    assert calendar.week == (((480, 960),),) * 5 + ((), ())
    assert all(item.intervals == () for item in calendar.exceptions)
    assert calendar.exceptions[0].day == date(2025, 1, 1)
    assert calendar.exceptions[-1].day == date(2047, 12, 25)


def test_a_workday_variant_has_its_own_key() -> None:
    assert standard_calendar_key() == "my-pa-us-40h-v1"
    assert standard_calendar_key(((420, 930),)) == "my-pa-us-40h-v1-07001530"
    assert standard_calendar_key(((480, 720), (780, 1020))) == "my-pa-us-40h-v1-0800120013001700"
    variant = standard_calendar(2027, ((420, 930),))
    assert variant.key == "my-pa-us-40h-v1-07001530"
    assert variant.week[0] == ((420, 930),)
    assert variant.exceptions == standard_calendar(2027).exceptions
    with pytest.raises(ValueError, match="32 characters"):
        standard_calendar_key(((0, 60), (120, 180), (240, 300)))
    for wrong in ((), ((960, 480),), ((480, 960), (900, 1000)), ((0, 1441),)):
        with pytest.raises(ValueError):
            standard_calendar_key(wrong)


#: SHA-256 of the canonical content holding `standard_calendar(2027)` (rule-generated).
STANDARD_2027_CONTENT_SHA256: Final = (
    "efc60d5098a47b862437dde6026c9f96e14f81cac0a6a7f2749382d5c59c49ad"
)


def _standard_content_bytes() -> bytes:
    calendar = standard_calendar(2027)
    return content_bytes(
        network([task("A", DAY)], calendars=(calendar,), default_calendar=calendar.key)
    )


def test_the_generator_is_pure_and_deterministic() -> None:
    first = _standard_content_bytes()
    assert _standard_content_bytes() == first
    assert standard_calendar(2027) == standard_calendar(2027)
    assert hashlib.sha256(first).hexdigest() == STANDARD_2027_CONTENT_SHA256


# --- the horizon report ----------------------------------------------------------------------


def test_a_run_past_the_materialized_horizon_is_reported() -> None:
    calendar = standard_calendar(2027)  # holidays of 2025..2047
    content = network([task("A", DAY)], calendars=(calendar,), default_calendar=calendar.key)
    inside = parse_instant("2047-12-31T16:00")
    assert standard_calendar_horizon_exceeded(content, inside) == ()
    # 1 Jan 2048 (a Wednesday) is the first holiday not materialized.
    assert standard_calendar_horizon_exceeded(content, parse_instant("2048-01-01T00:00")) == ()
    past = parse_instant("2048-01-01T00:01")
    assert standard_calendar_horizon_exceeded(content, past) == ("my-pa-us-40h-v1",)


def test_extending_the_calendar_clears_the_report() -> None:
    calendar = standard_calendar(2027)
    later = standard_calendar(2045)  # holidays of 2043..2065
    extended = type(calendar)(
        key=calendar.key,
        week=calendar.week,
        exceptions=tuple(
            {item.day: item for item in (*calendar.exceptions, *later.exceptions)}.values()
        ),
    )
    content = network([task("A", DAY)], calendars=(extended,), default_calendar=extended.key)
    assert standard_calendar_horizon_exceeded(content, parse_instant("2060-06-01T00:00")) == ()


def test_only_standard_calendars_are_reported() -> None:
    content = network([task("A", DAY)])  # calendar `std` has no holidays at all
    assert standard_calendar_horizon_exceeded(content, parse_instant("2099-12-31T00:00")) == ()


# --- the independent oracle --------------------------------------------------------------------


def _oracle(year: int) -> set[date]:
    """Brute force: scan each month day by day; no code shared with the generator."""

    def nth(month: int, weekday: int, n: int) -> date:
        days = []
        day = date(year, month, 1)
        while day.month == month:
            if day.weekday() == weekday:
                days.append(day)
            day += timedelta(days=1)
        return days[n - 1] if n > 0 else days[-1]

    def observed(day: date) -> date:
        return {5: day - timedelta(days=1), 6: day + timedelta(days=1)}.get(day.weekday(), day)

    fixed = [(1, 1), (7, 4), (11, 11), (12, 25)] + ([(6, 19)] if year >= 2021 else [])
    found = {observed(date(year, month, day)) for month, day in fixed}
    found |= {nth(1, 0, 3), nth(2, 0, 3), nth(5, 0, -1), nth(9, 0, 1), nth(10, 0, 2)}
    found.add(nth(11, 3, 4))
    return {day for day in found if date(2000, 1, 1) <= day <= date(2099, 12, 31)}


def test_every_year_matches_the_brute_force_oracle() -> None:
    for year in range(2000, 2100):
        assert {item.observed for item in federal_holidays(year)} == _oracle(year), year
