"""WP3a-I2: the pure coverage read (`domain.communications.coverage`), FAST tier.

Merged intervals over complete windows only, the 1 s adjacency edge against a
2 s gap, inclusive gap seconds, per-lane states (not_authorized kept apart),
freshness, and range coverage complete / partial / none, including the rolling
30-day monitoring read. Windows are synthetic UTC instants (no DST arithmetic is
involved: windows are taken as declared in UTC).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.domain.communications.corpus import Interval
from my_pa.domain.communications.coverage import (
    ROLLING_DAYS,
    LaneFact,
    RangeState,
    WindowFact,
    range_coverage,
    rolling_coverage,
    summarize_coverage,
)

D0: Final = datetime(2026, 11, 1, 4, tzinfo=UTC)
SECOND: Final = timedelta(seconds=1)


def lane(key_kind: str, state: str, *, authorized: bool | None = True) -> LaneFact:
    role = key_kind if key_kind in {"inbox", "sent"} else "other"
    return LaneFact(key_kind, role, "mail", authorized, state)


def window(
    start: datetime, end: datetime, state: str = "complete", lanes: tuple[LaneFact, ...] = ()
) -> WindowFact:
    return WindowFact(start, end, state, lanes)


def day(n: int) -> tuple[datetime, datetime]:
    start = D0 + timedelta(days=n)
    return start, start + timedelta(days=1) - SECOND


def test_adjacent_windows_one_second_apart_merge() -> None:
    a, b = day(0), day(1)
    summary = summarize_coverage([window(*a), window(*b)], now=b[1])
    assert summary.intervals == (Interval(a[0], b[1]),)
    assert summary.gaps == ()


def test_a_two_second_step_is_a_one_second_gap() -> None:
    a_start, a_end = day(0)
    b_start = a_end + 2 * SECOND
    summary = summarize_coverage(
        [window(a_start, a_end), window(b_start, b_start + timedelta(hours=1))], now=b_start
    )
    (gap,) = summary.gaps
    assert gap == Interval(a_end + SECOND, a_end + SECOND)
    assert gap.inclusive_seconds == 1


def test_a_whole_missing_day_is_a_gap_of_86400_seconds() -> None:
    summary = summarize_coverage([window(*day(0)), window(*day(2))], now=day(2)[1])
    (gap,) = summary.gaps
    assert gap.inclusive_seconds == 86_400
    assert (gap.start, gap.end) == day(1)


def test_only_complete_windows_cover_and_overlaps_merge() -> None:
    a = day(0)
    partial = window(*day(1), state="partial")
    overlap = window(a[0] + timedelta(hours=6), a[1] + timedelta(hours=3))
    summary = summarize_coverage([window(*a), overlap, partial], now=a[1])
    assert summary.snapshots == 3
    assert summary.complete_snapshots == 2
    assert summary.intervals == (Interval(a[0], a[1] + timedelta(hours=3)),)


def test_freshness_is_now_minus_the_latest_covered_instant() -> None:
    a = day(0)
    now = a[1] + timedelta(hours=2, microseconds=900_000)
    summary = summarize_coverage([window(*a)], now=now)
    assert summary.latest_covered == a[1]
    assert summary.freshness_seconds == 7200
    assert summarize_coverage([window(*a)], now=a[0]).freshness_seconds == 0
    empty = summarize_coverage([], now=now)
    assert (empty.latest_covered, empty.freshness_seconds, empty.intervals) == (None, None, ())


def test_lanes_report_states_latest_state_and_their_own_intervals() -> None:
    first = window(
        *day(0),
        lanes=(
            lane("inbox", "complete"),
            lane("sent", "failed"),
            lane("procore_rfis", "not_authorized", authorized=False),
        ),
    )
    second = window(
        *day(1),
        lanes=(
            lane("inbox", "complete"),
            lane("sent", "complete"),
            lane("procore_rfis", "not_authorized", authorized=False),
        ),
    )
    summary = summarize_coverage([second, first], now=day(1)[1])
    lanes = {item.key_kind: item for item in summary.lanes}
    assert lanes["inbox"].intervals == (Interval(day(0)[0], day(1)[1]),)
    assert lanes["sent"].states == {"complete": 1, "failed": 1}
    assert lanes["sent"].latest_state == "complete"
    assert lanes["sent"].intervals == (Interval(*day(1)),)
    restricted = lanes["procore_rfis"]
    assert (restricted.latest_state, restricted.latest_authorized) == ("not_authorized", False)
    assert restricted.intervals == ()
    assert restricted.states == {"not_authorized": 2}


def test_range_coverage_is_complete_partial_or_none() -> None:
    merged = (Interval(*day(0)), Interval(*day(2)))
    whole = range_coverage(merged, start=day(0)[0], end=day(0)[1])
    assert (whole.state, whole.gaps, whole.covered_seconds) == (RangeState.COMPLETE, (), 86_400)
    partial = range_coverage(merged, start=day(0)[0], end=day(2)[1])
    assert partial.state is RangeState.PARTIAL
    assert partial.gaps == (Interval(*day(1)),)
    none = range_coverage(merged, start=day(4)[0], end=day(4)[1])
    assert none.state is RangeState.NONE
    assert none.gaps == (Interval(*day(4)),)
    assert none.covered_seconds == 0


def test_range_edges_are_gaps_too() -> None:
    merged = (Interval(*day(1)),)
    result = range_coverage(merged, start=day(0)[0], end=day(2)[1])
    assert result.gaps == (Interval(*day(0)), Interval(*day(2)))


def test_a_range_ending_before_it_starts_is_refused() -> None:
    with pytest.raises(ValueError, match="ends at or after"):
        range_coverage((), start=day(1)[0], end=day(0)[0])


def test_the_rolling_read_spans_thirty_days_to_now() -> None:
    now = D0 + timedelta(days=40)
    windows = [window(*day(n)) for n in range(5, 41)]  # covers day 5 through now
    rolling = rolling_coverage(windows, now=now)
    assert ROLLING_DAYS == 30
    assert rolling.start == now - timedelta(days=30)
    assert rolling.end == now
    assert rolling.state is RangeState.COMPLETE
    holed = [w for w in windows if w.start != day(30)[0]]
    holed_read = rolling_coverage(holed, now=now)
    assert holed_read.state is RangeState.PARTIAL
    assert holed_read.gaps == (Interval(*day(30)),)
    assert rolling_coverage([], now=now).state is RangeState.NONE
