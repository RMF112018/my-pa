"""Schedule Scenarios S6-1: integer-minute calendar functions (contract section 3.2).

A calendar is compiled once into a per-day pattern list and a cumulative
working-minute table over the whole axis (36,525 days), so every function is
`O(log days)` through `bisect`; minute loops exist only in the tests' oracle.

`F(t)` below is the number of working minutes in `[0, t)`. Every function is
expressed through it:

* `working_minutes(C, a, b) = F(b) - F(a)` (signed and additive);
* `advance(C, t, d)`, `d > 0`: the end of the working minute with index
  `F(t) + d - 1`, the smallest `t' > t` with `W(C, t, t') = d`;
* `retreat(C, t, d)`, `d > 0`: the start of the working minute with index
  `F(t) - d`, the largest `t' < t` with `W(C, t', t) = d`;
* `next_work(C, t)`: the start of the working minute with index `F(t)`;
* `prev_end(C, t)`: the end of the working minute with index `F(t) - 1`.

A result that would leave `[0, HORIZON_MINUTES]` raises `CalendarHorizonError`;
the engine turns it into the `horizon_exceeded` rejection.
"""

from __future__ import annotations

from array import array
from bisect import bisect_right
from datetime import date
from functools import cache, lru_cache
from itertools import accumulate
from typing import Final

from my_pa.domain.schedule.scenario.model import (
    HORIZON_MINUTES,
    MINUTES_PER_DAY,
    DayPattern,
    ScenarioCalendar,
)

__all__ = [
    "AXIS_DAYS",
    "COMPILED_CALENDAR_CACHE_SIZE",
    "CalendarHorizonError",
    "CompiledCalendar",
    "advance",
    "compile_calendar",
    "next_work",
    "prev_end",
    "retreat",
    "shift",
    "twenty_four_hour_calendar",
    "working",
    "working_minutes",
]

#: Days on the axis: 2000-01-01 .. 2099-12-31.
AXIS_DAYS: Final = 36_525
#: `date(2000, 1, 1).weekday()`: a Saturday.
_FIRST_WEEKDAY: Final = 5
_EPOCH_ORDINAL: Final = date(2000, 1, 1).toordinal()
_ALL_DAY: Final[DayPattern] = ((0, MINUTES_PER_DAY),)


class CalendarHorizonError(Exception):
    """A calendar result would leave the axis `[0, HORIZON_MINUTES]`."""


def _pattern_minutes(pattern: DayPattern) -> int:
    return sum(end - start for start, end in pattern)


class CompiledCalendar:
    """The cumulative working-minute table of one calendar over the whole axis.

    Memory (FR8-F06, residual S6-U16): the day patterns are not materialised per
    day; a day's pattern is its exception's, else its weekday's, and the
    cumulative table is one `array('q')` of 36,526 entries (about 0.3 MB).
    """

    __slots__ = ("_cumulative", "_exceptions", "_total", "_week", "key")

    def __init__(
        self, key: str, week: tuple[DayPattern, ...], exceptions: dict[int, DayPattern]
    ) -> None:
        if len(week) != 7 or not all(0 <= day < AXIS_DAYS for day in exceptions):
            raise ValueError("a compiled calendar has 7 weekday patterns and axis exceptions")
        self.key = key
        self._week = week
        self._exceptions = exceptions
        weekly = [_pattern_minutes(pattern) for pattern in week]
        cumulative = array("q", [0])
        cumulative.extend(
            accumulate(
                _pattern_minutes(exceptions[day])
                if day in exceptions
                else weekly[(_FIRST_WEEKDAY + day) % 7]
                for day in range(AXIS_DAYS)
            )
        )
        self._cumulative = cumulative
        self._total = cumulative[-1]

    def _pattern(self, day: int) -> DayPattern:
        found = self._exceptions.get(day)
        return self._week[(_FIRST_WEEKDAY + day) % 7] if found is None else found

    def is_working(self, minute: int) -> bool:
        _check_minute(minute)
        day, minute_of_day = divmod(minute, MINUTES_PER_DAY)
        return any(start <= minute_of_day < end for start, end in self._pattern(day))

    def worked_before(self, instant: int) -> int:
        """`F(t)`: working minutes in `[0, t)`."""
        _check_instant(instant)
        day, minute_of_day = divmod(instant, MINUTES_PER_DAY)
        if day == AXIS_DAYS:
            return self._total
        partial = sum(
            min(end, minute_of_day) - start
            for start, end in self._pattern(day)
            if start < minute_of_day
        )
        return self._cumulative[day] + partial

    def minute_at(self, index: int) -> int:
        """The start of the working minute with 0-based `index` (`0 <= index < total`)."""
        if not 0 <= index < self._total:
            raise CalendarHorizonError("no such working minute on the axis")
        day = bisect_right(self._cumulative, index) - 1
        remainder = index - self._cumulative[day]
        for start, end in self._pattern(day):
            if remainder < end - start:
                return day * MINUTES_PER_DAY + start + remainder
            remainder -= end - start
        raise AssertionError("the cumulative table and the day pattern disagree")


def _check_instant(value: int) -> None:
    if type(value) is not int or not 0 <= value <= HORIZON_MINUTES:
        raise ValueError("an instant lies on the axis")


def _check_minute(value: int) -> None:
    if type(value) is not int or not 0 <= value < HORIZON_MINUTES:
        raise ValueError("a minute lies on the axis")


def _check_duration(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("a calendar duration is a non-negative integer")


#: One content's calendars (at most 32) plus headroom; about 0.3 MB each.
COMPILED_CALENDAR_CACHE_SIZE: Final = 40


@lru_cache(maxsize=COMPILED_CALENDAR_CACHE_SIZE)
def compile_calendar(calendar: ScenarioCalendar) -> CompiledCalendar:
    """Compile a calendar (memoized by value: a compiled calendar is never mutated)."""
    exceptions = {
        exception.day.toordinal() - _EPOCH_ORDINAL: exception.intervals
        for exception in calendar.exceptions
    }
    return CompiledCalendar(calendar.key, calendar.week, exceptions)


@cache
def twenty_four_hour_calendar() -> CompiledCalendar:
    """The `twenty_four_hour` lag calendar: every minute works."""
    return CompiledCalendar("twenty_four_hour", (_ALL_DAY,) * 7, {})


def working(calendar: CompiledCalendar, minute: int) -> bool:
    """Minute `[m, m+1)` is working."""
    return calendar.is_working(minute)


def working_minutes(calendar: CompiledCalendar, start: int, end: int) -> int:
    """`W(C, a, b)`: working minutes in `[a, b)`, negative when `a > b`."""
    return calendar.worked_before(end) - calendar.worked_before(start)


def advance(calendar: CompiledCalendar, instant: int, duration: int) -> int:
    _check_duration(duration)
    if duration == 0:
        _check_instant(instant)
        return instant
    return calendar.minute_at(calendar.worked_before(instant) + duration - 1) + 1


def retreat(calendar: CompiledCalendar, instant: int, duration: int) -> int:
    _check_duration(duration)
    if duration == 0:
        _check_instant(instant)
        return instant
    return calendar.minute_at(calendar.worked_before(instant) - duration)


def next_work(calendar: CompiledCalendar, instant: int) -> int:
    """The smallest working minute `m >= t`."""
    return calendar.minute_at(calendar.worked_before(instant))


def prev_end(calendar: CompiledCalendar, instant: int) -> int:
    """The largest `m <= t` whose preceding minute `m - 1` works."""
    return calendar.minute_at(calendar.worked_before(instant) - 1) + 1


def shift(calendar: CompiledCalendar, instant: int, lag: int) -> int:
    """`advance` for a non-negative lag, `retreat` for a lead."""
    if type(lag) is not int:
        raise ValueError("a lag is an integer")
    if lag >= 0:
        return advance(calendar, instant, lag)
    return retreat(calendar, instant, -lag)
