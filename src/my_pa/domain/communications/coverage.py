"""Persisted coverage, read back: merged intervals, gaps, lanes, freshness (contract section 9).

The pure half of the WP3a coverage read. Its input is one `WindowFact` per
ingested snapshot (the declared window, inclusive at both ends, its overall
coverage state and its per-lane states); its output is what a reader may say
about the source:

* **intervals** -- the windows of `complete` snapshots, merged when the next
  start is at most `WINDOW_RESOLUTION` (1 s) after the previous end
  (`corpus.merge_intervals`, the one merge rule);
* **gaps** -- the uncovered spans between merged intervals, inclusive like a
  window: from 1 s after the earlier end to 1 s before the next start, so a gap
  of `n` seconds is `(end - start) + 1`;
* **lanes** -- per declared lane (`key_kind`, `role`, `lane`), how many
  snapshots reported each state, the state of the latest one, and the merged
  intervals of the windows in which that lane was `complete`. A lane that is
  `not_authorized` is reported as such, never as "no messages";
* **freshness** -- `now` minus the latest covered instant, in whole seconds
  (zero when the latest window ends after `now`);
* **range coverage** -- for `[start, end]` (whole seconds, inclusive), whether
  the merged intervals cover it `complete`ly, `partial`ly (with the gaps inside
  the range) or not at all (`none`). `rolling_coverage` is that read for the
  last `ROLLING_DAYS` days.

Nothing here has a clock: `now` is always a parameter.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from typing import Final

from my_pa.domain.communications.corpus import Interval, merge_intervals
from my_pa.domain.communications.model import WINDOW_RESOLUTION, CoverageState

__all__ = [
    "ROLLING_DAYS",
    "CoverageSummary",
    "LaneCoverage",
    "LaneFact",
    "RangeCoverage",
    "RangeState",
    "WindowFact",
    "gaps_between",
    "range_coverage",
    "rolling_coverage",
    "summarize_coverage",
]

#: The monitoring read's span (contract section 19: open gaps per source).
ROLLING_DAYS: Final = 30


class RangeState(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class LaneFact:
    """One declared lane of one window: closed values only."""

    key_kind: str
    role: str
    lane: str
    authorized: bool | None
    state: str


@dataclass(frozen=True, slots=True)
class WindowFact:
    """One ingested snapshot's declared window (inclusive end) and states."""

    start: datetime
    end: datetime
    state: str
    lanes: tuple[LaneFact, ...]


@dataclass(frozen=True, slots=True)
class LaneCoverage:
    key_kind: str
    role: str
    lane: str
    states: Mapping[str, int]
    latest_state: str
    latest_authorized: bool | None
    intervals: tuple[Interval, ...]


@dataclass(frozen=True, slots=True)
class CoverageSummary:
    snapshots: int
    complete_snapshots: int
    intervals: tuple[Interval, ...]
    gaps: tuple[Interval, ...]
    latest_covered: datetime | None
    freshness_seconds: int | None
    lanes: tuple[LaneCoverage, ...]


@dataclass(frozen=True, slots=True)
class RangeCoverage:
    start: datetime
    end: datetime
    state: RangeState
    gaps: tuple[Interval, ...]
    covered_seconds: int


def _second(moment: datetime) -> datetime:
    return moment.replace(microsecond=0)


def gaps_between(merged: Sequence[Interval]) -> tuple[Interval, ...]:
    """The inclusive gaps between consecutive merged intervals."""
    return tuple(
        Interval(a.end + WINDOW_RESOLUTION, b.start - WINDOW_RESOLUTION)
        for a, b in pairwise(merged)
    )


def _complete(windows: Sequence[WindowFact]) -> tuple[Interval, ...]:
    return merge_intervals(
        [Interval(w.start, w.end) for w in windows if w.state == CoverageState.COMPLETE.value]
    )


def _lanes(windows: Sequence[WindowFact]) -> tuple[LaneCoverage, ...]:
    by_lane: dict[tuple[str, str, str], list[tuple[WindowFact, LaneFact]]] = {}
    for window in windows:
        for lane in window.lanes:
            by_lane.setdefault((lane.key_kind, lane.role, lane.lane), []).append((window, lane))
    result: list[LaneCoverage] = []
    for (key_kind, role, lane_name), facts in sorted(by_lane.items()):
        _, latest = max(facts, key=lambda f: (f[0].end, f[0].start, f[1].state))
        result.append(
            LaneCoverage(
                key_kind=key_kind,
                role=role,
                lane=lane_name,
                states=dict(sorted(Counter(lane.state for _, lane in facts).items())),
                latest_state=latest.state,
                latest_authorized=latest.authorized,
                intervals=merge_intervals(
                    [
                        Interval(window.start, window.end)
                        for window, lane in facts
                        if lane.state == CoverageState.COMPLETE.value
                    ]
                ),
            )
        )
    return tuple(result)


def summarize_coverage(windows: Sequence[WindowFact], *, now: datetime) -> CoverageSummary:
    """The whole-source read (module docstring)."""
    merged = _complete(windows)
    latest = merged[-1].end if merged else None
    freshness = None
    if latest is not None:
        freshness = max(0, int((_second(now) - latest) / WINDOW_RESOLUTION))
    return CoverageSummary(
        snapshots=len(windows),
        complete_snapshots=sum(1 for w in windows if w.state == CoverageState.COMPLETE.value),
        intervals=merged,
        gaps=gaps_between(merged),
        latest_covered=latest,
        freshness_seconds=freshness,
        lanes=_lanes(windows),
    )


def range_coverage(merged: Sequence[Interval], *, start: datetime, end: datetime) -> RangeCoverage:
    """How `merged` (already merged, ordered) covers `[start, end]`, both whole seconds."""
    start, end = _second(start), _second(end)
    if end < start:
        raise ValueError("a range ends at or after its start")
    clipped = [
        Interval(max(i.start, start), min(i.end, end))
        for i in merged
        if i.end >= start and i.start <= end
    ]
    if not clipped:
        return RangeCoverage(start, end, RangeState.NONE, (Interval(start, end),), 0)
    gaps: list[Interval] = []
    if clipped[0].start > start:
        gaps.append(Interval(start, clipped[0].start - WINDOW_RESOLUTION))
    gaps.extend(gaps_between(clipped))
    if clipped[-1].end < end:
        gaps.append(Interval(clipped[-1].end + WINDOW_RESOLUTION, end))
    covered = sum(i.inclusive_seconds for i in clipped)
    state = RangeState.PARTIAL if gaps else RangeState.COMPLETE
    return RangeCoverage(start, end, state, tuple(gaps), covered)


def rolling_coverage(windows: Sequence[WindowFact], *, now: datetime) -> RangeCoverage:
    """`range_coverage` of the complete windows over `[now - ROLLING_DAYS, now]`."""
    return range_coverage(_complete(windows), start=now - timedelta(days=ROLLING_DAYS), end=now)
