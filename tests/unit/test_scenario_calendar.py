"""Schedule Scenarios S6-1: calendar functions against a minute-by-minute oracle (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` sections 3.1-3.2 and
3.13 (1). The oracle below walks single minutes and shares nothing with the
engine's cumulative tables: seeded random calendars (`random.Random(seed)`,
fixed seeds, test-only), windows of at most 21 days, every function compared
at every probed instant. Horizon edges and argument checks are pinned too.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Final

import pytest

from my_pa.domain.schedule.scenario.calendar import (
    AXIS_DAYS,
    CalendarHorizonError,
    advance,
    compile_calendar,
    next_work,
    prev_end,
    retreat,
    shift,
    twenty_four_hour_calendar,
    working,
    working_minutes,
)
from my_pa.domain.schedule.scenario.model import (
    HORIZON_MINUTES,
    CalendarException,
    ScenarioCalendar,
    parse_instant,
)

EPOCH: Final = date(2000, 1, 1)
WINDOW_DAYS: Final = 21


def _rng(seed: int) -> random.Random:
    """A seeded, test-only generator (section 3.13); never security material."""
    return random.Random(seed)  # noqa: S311 - deterministic test data, not a secret


class Oracle:
    """Minute-by-minute reference: a minute works iff its day's pattern covers it."""

    def __init__(self, calendar: ScenarioCalendar) -> None:
        self.week = calendar.week
        self.exceptions = {item.day: item.intervals for item in calendar.exceptions}

    def working(self, minute: int) -> bool:
        day = EPOCH + timedelta(days=minute // 1440)
        pattern = self.exceptions.get(day, self.week[day.weekday()])
        return any(start <= minute % 1440 < end for start, end in pattern)

    def count(self, a: int, b: int) -> int:
        if a > b:
            return -self.count(b, a)
        return sum(1 for minute in range(a, b) if self.working(minute))

    def advance(self, t: int, d: int, limit: int) -> int | None:
        if d == 0:
            return t
        seen, minute = 0, t
        while minute < limit:
            if self.working(minute):
                seen += 1
                if seen == d:
                    return minute + 1
            minute += 1
        return None

    def retreat(self, t: int, d: int, floor: int) -> int | None:
        if d == 0:
            return t
        seen, minute = 0, t
        while minute > floor:
            minute -= 1
            if self.working(minute):
                seen += 1
                if seen == d:
                    return minute
        return None

    def next_work(self, t: int, limit: int) -> int | None:
        minute = t
        while minute < limit:
            if self.working(minute):
                return minute
            minute += 1
        return None

    def prev_end(self, t: int, floor: int) -> int | None:
        minute = t
        while minute > floor:
            if self.working(minute - 1):
                return minute
            minute -= 1
        return None


def _random_pattern(rng: random.Random) -> tuple[tuple[int, int], ...]:
    cuts = sorted(rng.sample(range(0, 1441), 2 * rng.randint(0, 4)))
    pattern = [(cuts[k], cuts[k + 1]) for k in range(0, len(cuts), 2)]
    # Strictly separated: drop an interval that touches its predecessor.
    kept: list[tuple[int, int]] = []
    for start, end in pattern:
        if start < end and (not kept or kept[-1][1] < start):
            kept.append((start, end))
    return tuple(kept)


def _random_calendar(rng: random.Random, window_start: date) -> ScenarioCalendar:
    week = tuple(_random_pattern(rng) for _ in range(7))
    if not any(week):
        week = (((rng.randint(0, 1000), 1200),), *week[1:])
    exceptions = {
        window_start + timedelta(days=rng.randint(0, WINDOW_DAYS)): _random_pattern(rng)
        for _ in range(rng.randint(0, 5))
    }
    return ScenarioCalendar(
        "rnd",
        week,
        tuple(CalendarException(day=day, intervals=pattern) for day, pattern in exceptions.items()),
    )


@pytest.mark.parametrize("seed", range(24))
def test_calendar_functions_match_the_minute_oracle(seed: int) -> None:
    rng = _rng(seed)
    window_start = EPOCH + timedelta(days=rng.randint(9000, 30000))
    calendar = _random_calendar(rng, window_start)
    compiled = compile_calendar(calendar)
    oracle = Oracle(calendar)
    low = (window_start - EPOCH).days * 1440
    high = low + WINDOW_DAYS * 1440
    for _ in range(30):
        t = rng.randint(low, high)
        u = rng.randint(low, high)
        d = rng.choice([0, 1, rng.randint(1, 600), rng.randint(1, 3000)])
        assert working_minutes(compiled, t, u) == oracle.count(t, u)
        if t < HORIZON_MINUTES:
            assert working(compiled, t) is oracle.working(t)
        expected = oracle.advance(t, d, high + 1440)
        if expected is not None:
            assert advance(compiled, t, d) == expected
            assert shift(compiled, t, d) == expected
            assert working_minutes(compiled, t, expected) == d
        expected = oracle.retreat(t, d, low - 1440)
        if expected is not None:
            assert retreat(compiled, t, d) == expected
            if d:
                assert shift(compiled, t, -d) == expected
        expected = oracle.next_work(t, high + 1440)
        if expected is not None:
            assert next_work(compiled, t) == expected
        expected = oracle.prev_end(t, low - 1440)
        if expected is not None:
            assert prev_end(compiled, t) == expected


STD: Final = ScenarioCalendar("std", (((480, 960),),) * 5 + ((), ()))


def test_standard_week_examples() -> None:
    compiled = compile_calendar(STD)
    monday = parse_instant("2027-01-04T00:00")
    assert next_work(compiled, monday) == parse_instant("2027-01-04T08:00")
    assert advance(compiled, parse_instant("2027-01-04T08:00"), 1440) == parse_instant(
        "2027-01-06T16:00"
    )
    assert retreat(compiled, parse_instant("2027-01-04T08:00"), 480) == parse_instant(
        "2027-01-01T08:00"
    )
    assert prev_end(compiled, parse_instant("2027-01-04T08:00")) == parse_instant(
        "2027-01-01T16:00"
    )
    # A zero duration never moves, even off working time.
    assert advance(compiled, monday, 0) == retreat(compiled, monday, 0) == monday
    assert working_minutes(compiled, parse_instant("2027-01-08T16:00"), monday) == -2400


def test_twenty_four_hour_calendar_counts_every_minute() -> None:
    all_day = twenty_four_hour_calendar()
    assert all_day is twenty_four_hour_calendar()
    t = parse_instant("2027-01-09T13:07")
    assert advance(all_day, t, 960) == t + 960
    assert retreat(all_day, t, 960) == t - 960
    assert next_work(all_day, t) == prev_end(all_day, t) == t
    assert working_minutes(all_day, t, t + 12345) == 12345


def test_results_outside_the_axis_raise_horizon_errors() -> None:
    compiled = compile_calendar(STD)
    last_friday = parse_instant("2099-12-31T08:00")  # a Thursday; Friday is 2100-01-01
    assert advance(compiled, last_friday, 480) == parse_instant("2099-12-31T16:00")
    with pytest.raises(CalendarHorizonError):
        advance(compiled, last_friday, 481)
    with pytest.raises(CalendarHorizonError):
        next_work(compiled, parse_instant("2099-12-31T16:00"))
    with pytest.raises(CalendarHorizonError):
        retreat(compiled, parse_instant("2000-01-03T09:00"), 61)
    with pytest.raises(CalendarHorizonError):
        prev_end(compiled, parse_instant("2000-01-03T08:00"))
    all_day = twenty_four_hour_calendar()
    assert advance(all_day, HORIZON_MINUTES - 5, 5) == HORIZON_MINUTES
    with pytest.raises(CalendarHorizonError):
        next_work(all_day, HORIZON_MINUTES)
    assert AXIS_DAYS * 1440 == HORIZON_MINUTES


def test_arguments_are_checked() -> None:
    compiled = compile_calendar(STD)
    with pytest.raises(ValueError, match="axis"):
        working_minutes(compiled, -1, 0)
    with pytest.raises(ValueError, match="axis"):
        working(compiled, HORIZON_MINUTES)
    with pytest.raises(ValueError, match="non-negative"):
        advance(compiled, 0, -1)
    with pytest.raises(ValueError, match="integer"):
        shift(compiled, 0, True)  # type: ignore[arg-type]


def test_an_exception_replaces_the_weekday_pattern() -> None:
    holiday = ScenarioCalendar(
        "std", STD.week, (CalendarException(day=date(2027, 1, 5), intervals=()),)
    )
    saturday = ScenarioCalendar(
        "std", STD.week, (CalendarException(day=date(2027, 1, 9), intervals=((600, 660),)),)
    )
    compiled = compile_calendar(holiday)
    assert advance(compiled, parse_instant("2027-01-04T08:00"), 960) == parse_instant(
        "2027-01-06T16:00"
    )
    assert (
        working_minutes(
            compile_calendar(saturday),
            parse_instant("2027-01-09T00:00"),
            parse_instant("2027-01-10T00:00"),
        )
        == 60
    )
