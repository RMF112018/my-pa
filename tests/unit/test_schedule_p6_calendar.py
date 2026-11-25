"""S7-1 acceptance A3: the `clndr_data` calendar blob (contract section 3.4) (FAST).

Week 1 = Sunday; `d|N` counts days from 1899-12-30; an `00:00` end is minute
1,440; an exception without an interval is a holiday; render -> parse -> equal
over a deterministic family of generated calendars.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from my_pa.domain.schedule.p6.calendar import (
    CALENDAR_EPOCH,
    CalendarBoundError,
    CalendarData,
    CalendarDataError,
    parse_calendar_data,
    render_calendar_data,
)
from my_pa.domain.schedule.p6.model import P6_LIMITS, Bound


def _parse(text: str) -> CalendarData:
    return parse_calendar_data(
        text,
        max_depth=P6_LIMITS.calendar_tree_depth,
        max_nodes=P6_LIMITS.calendar_tree_nodes,
        max_exceptions=P6_LIMITS.calendar_exceptions,
    )


def _day(number: int, *intervals: str) -> str:
    body = "".join(f"\x7f\x7f(0||{index}({value})())" for index, value in enumerate(intervals))
    return f"\x7f\x7f(0||{number}()({body}))"


def _blob(days: str = "", exceptions: str = "", *, week: bool = True) -> str:
    week_part = f"\x7f\x7f(0||DaysOfWeek()({days}))" if week else ""
    exception_part = f"\x7f\x7f(0||Exceptions()({exceptions}))" if exceptions else ""
    return f"(0||CalendarData()({week_part}\x7f\x7f(0||VIEW(ShowTotal|Y)()){exception_part}))"


def test_week_day_one_is_sunday_and_the_week_is_stored_monday_first() -> None:
    data = _parse(_blob(_day(1, "s|09:00|f|10:00") + _day(2, "s|08:00|f|12:00") + _day(7)))
    assert data.week is not None
    monday, *_, saturday, sunday = data.week
    assert monday == ((480, 720),)
    assert sunday == ((540, 600),)
    assert saturday == ()


def test_exception_serial_counts_from_1899_12_30() -> None:
    assert date(1899, 12, 30) == CALENDAR_EPOCH
    data = _parse(_blob(exceptions="\x7f\x7f(0||0(d|47484)())\x7f\x7f(0||1(d|2)())"))
    assert [day for day, _ in data.exceptions] == [date(1900, 1, 1), date(2030, 1, 1)]


def test_midnight_end_is_minute_1440() -> None:
    data = _parse(_blob(_day(2, "s|16:00|f|00:00", "s|00:00|f|08:00")))
    assert data.week is not None
    assert data.week[0] == ((0, 480), (960, 1440))


def test_exception_without_interval_is_a_holiday_and_with_intervals_is_work() -> None:
    data = _parse(
        _blob(
            exceptions="\x7f\x7f(0||0(d|47484)())\x7f\x7f(0||1(d|47495)(\x7f\x7f(0||0(s|08:00|f|12:00)())))"
        )
    )
    assert data.exceptions == ((date(2030, 1, 1), ()), (date(2030, 1, 12), ((480, 720),)))


def test_a_blob_without_days_of_week_has_no_week() -> None:
    assert _parse(_blob(week=False, exceptions="\x7f\x7f(0||0(d|47484)())")).week is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "(0||CalendarData()(",
        "(0||Other()())",
        _blob(_day(8)),
        _blob(_day(2) + _day(2)),
        _blob(_day(2, "s|12:00|f|08:00")),
        _blob(_day(2, "s|08:00|f|12:00", "s|11:00|f|13:00")),
        _blob(_day(2, "s|8:00|f|12:00")),
        _blob(_day(2, "s|08:00|x|12:00")),
        _blob(exceptions="\x7f\x7f(0||0(d|1)())"),
        _blob(exceptions="\x7f\x7f(0||0(d|47484)())\x7f\x7f(0||1(d|47484)())"),
        _blob(exceptions="\x7f\x7f(0||0(x|47484)())"),
        _blob() + "trailing",
    ],
)
def test_malformed_blobs_are_refused(text: str) -> None:
    with pytest.raises(CalendarDataError):
        _parse(text)


def test_tree_and_exception_bounds_are_named() -> None:
    nested = "(0||SYN()())"
    for _ in range(15):
        nested = f"(0||SYN()({nested}))"
    with pytest.raises(CalendarBoundError) as depth:
        _parse(f"(0||CalendarData()({nested}))")
    assert depth.value.bound is Bound.CALENDAR_TREE_DEPTH
    with pytest.raises(CalendarBoundError) as nodes:
        parse_calendar_data(_blob(_day(2)), max_depth=16, max_nodes=3, max_exceptions=10)
    assert nodes.value.bound is Bound.CALENDAR_TREE_NODES
    exceptions = "".join(f"\x7f\x7f(0||{i}(d|{47484 + i})())" for i in range(3))
    with pytest.raises(CalendarBoundError) as count:
        parse_calendar_data(
            _blob(exceptions=exceptions), max_depth=16, max_nodes=99, max_exceptions=2
        )
    assert count.value.bound is Bound.CALENDAR_EXCEPTIONS


def _intervals(rng: random.Random) -> tuple[tuple[int, int], ...]:
    points = sorted(rng.sample(range(0, 1441, 15), 2 * rng.randint(0, 3)))
    return tuple((points[i], points[i + 1]) for i in range(0, len(points), 2))


def _random_calendar(seed: int) -> CalendarData:
    rng = random.Random(seed)  # noqa: S311 - a fixed seed for a deterministic family
    week = None if seed % 7 == 0 else tuple(_intervals(rng) for _ in range(7))
    days = sorted(
        {
            date(1900, 1, 1) + timedelta(days=rng.randint(0, 109_000))
            for _ in range(rng.randint(0, 30))
        }
    )
    return CalendarData(week=week, exceptions=tuple((day, _intervals(rng)) for day in days))


@pytest.mark.parametrize("seed", range(200))
def test_render_then_parse_is_identity(seed: int) -> None:
    calendar = _random_calendar(seed)
    assert _parse(render_calendar_data(calendar)) == calendar
