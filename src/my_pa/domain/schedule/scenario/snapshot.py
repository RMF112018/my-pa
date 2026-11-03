"""Schedule Scenarios S6-1: version 1 as a snapshot of one publication (contract section 2.5).

The PDF carries no duration unit, so the client declares
`minutes_per_source_unit` (1..1,440, no default). A `published_value` cell `v`
becomes `int((v * minutes_per_source_unit).quantize(1, ROUND_HALF_EVEN))`
minutes; a product above 5,256,000 is **null** and counted out of range (never
clamped, so the run rejects `missing_duration` until the client sets it); a
non-integral product is counted quantized; any other cell state is null and
counted missing; a milestone always gets 0 and 0. Published dates stay inert in
`published_reference` (the `*` marker is never read). No relationship,
constraint, progress or distribution is invented.

Eligibility of the publication (owned, effective `complete`/`partial`, not in an
intake Series) is the caller's check (S6-2/S6-3); this module is pure.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import Final

from my_pa.domain.schedule.model import (
    ScheduleActivityRowView,
    ScheduleCellState,
    ScheduleDurationCell,
    ScheduleRowType,
    normalize_display_text,
)
from my_pa.domain.schedule.scenario.model import (
    MAX_ACTIVITIES,
    MAX_DURATION_MINUTES,
    ActivityKind,
    PublishedReference,
    ScenarioActivity,
    ScenarioCalendar,
    ScenarioContent,
    ScenarioSettings,
    content_problem,
    parse_instant,
)

__all__ = [
    "MAX_MINUTES_PER_SOURCE_UNIT",
    "Snapshot",
    "SnapshotRefusalError",
    "SnapshotRefusalReason",
    "SnapshotReport",
    "snapshot_from_publication",
    "snapshot_wbs_path",
]

MAX_MINUTES_PER_SOURCE_UNIT: Final = 1_440
_TIME_OF_DAY: Final = re.compile(r"\A([01][0-9]|2[0-3]):([0-5][0-9])\Z")
_WHOLE: Final = Decimal(1)


class SnapshotRefusalReason(StrEnum):
    """Closed refusal tokens; the public details are the matching `SafeDetail`s."""

    MINUTES_PER_SOURCE_UNIT = "minutes_per_source_unit"
    CALENDAR = "calendar"
    DATA_DATE = "data_date"
    ROWS = "rows"


class SnapshotRefusalError(ValueError):
    def __init__(self, reason: SnapshotRefusalReason) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SnapshotReport:
    activities: int
    milestones: int
    durations_quantized: int
    durations_out_of_range: int
    original_missing: int
    remaining_missing: int


@dataclass(frozen=True, slots=True)
class Snapshot:
    content: ScenarioContent
    report: SnapshotReport


class _Counter:
    def __init__(self) -> None:
        self.quantized = 0
        self.out_of_range = 0
        self.original_missing = 0
        self.remaining_missing = 0

    def minutes(self, cell: ScheduleDurationCell, factor: int, *, original: bool) -> int | None:
        if cell.state is not ScheduleCellState.PUBLISHED_VALUE or cell.value is None:
            if original:
                self.original_missing += 1
            else:
                self.remaining_missing += 1
            return None
        product = cell.value * factor
        minutes = int(product.quantize(_WHOLE, rounding=ROUND_HALF_EVEN))
        if minutes > MAX_DURATION_MINUTES:
            self.out_of_range += 1
            return None
        if product != minutes:
            self.quantized += 1
        return minutes


def snapshot_wbs_path(hierarchy_path: tuple[str, ...] | None) -> tuple[str, ...] | None:
    """Section 2.5 (FR8-F02): the published hierarchy as an inert `wbs_path`.

    Each label is normalized. A missing or empty path is null; so is a path in
    which any label normalizes to nothing (the S5 parser stores an unnamed
    parent as `""`), because a path with a hole in it would misstate the
    hierarchy and `wbs_path` is inert, so dropping it cannot change a result.
    """
    if not hierarchy_path:
        return None
    labels = tuple(normalize_display_text(label) for label in hierarchy_path)
    return None if any(not label for label in labels) else labels


def snapshot_from_publication(
    *,
    publication_id: str,
    data_date: date,
    rows: Sequence[ScheduleActivityRowView],
    minutes_per_source_unit: int,
    calendars: Sequence[ScenarioCalendar],
    default_calendar: str,
    data_date_time: str = "00:00",
) -> Snapshot:
    """Build version 1 from the accepted run's activity and milestone rows."""
    factor = minutes_per_source_unit
    if type(factor) is not int or not 1 <= factor <= MAX_MINUTES_PER_SOURCE_UNIT:
        raise SnapshotRefusalError(SnapshotRefusalReason.MINUTES_PER_SOURCE_UNIT)
    if _TIME_OF_DAY.fullmatch(data_date_time) is None or type(data_date) is not date:
        raise SnapshotRefusalError(SnapshotRefusalReason.DATA_DATE)
    try:
        instant = parse_instant(f"{data_date.isoformat()}T{data_date_time}")
    except ValueError:
        raise SnapshotRefusalError(SnapshotRefusalReason.DATA_DATE) from None
    if len(rows) > MAX_ACTIVITIES or not all(
        isinstance(row, ScheduleActivityRowView) for row in rows
    ):
        raise SnapshotRefusalError(SnapshotRefusalReason.ROWS)
    counter = _Counter()
    activities: list[ScenarioActivity] = []
    milestones = 0
    for row in rows:
        is_milestone = row.row_type is ScheduleRowType.MILESTONE
        if is_milestone:
            milestones += 1
            original: int | None = 0
            remaining: int | None = 0
        else:
            original = counter.minutes(row.original_duration, factor, original=True)
            remaining = counter.minutes(row.remaining_duration, factor, original=False)
        try:
            activities.append(
                ScenarioActivity(
                    key=row.schedule_activity_id,
                    name=normalize_display_text(row.activity_name),
                    kind=ActivityKind.MILESTONE if is_milestone else ActivityKind.TASK,
                    wbs_path=snapshot_wbs_path(row.hierarchy_path),
                    calendar=None,
                    original_minutes=original,
                    remaining_minutes=remaining,
                    published_reference=PublishedReference(
                        publication_id=publication_id,
                        published_activity_id=row.published_activity_id,
                        original_duration=row.original_duration,
                        remaining_duration=row.remaining_duration,
                        start=row.start,
                        finish=row.finish,
                    ),
                )
            )
        except ValueError:
            # Anything else a row view admits but a scenario activity does not
            # (an unnamed row, a non-Stable key) is a closed refusal, never a bare error.
            raise SnapshotRefusalError(SnapshotRefusalReason.ROWS) from None
    try:
        content = ScenarioContent(
            data_date=instant,
            settings=ScenarioSettings(default_calendar=default_calendar),
            calendars=tuple(calendars),
            activities=tuple(activities),
        )
    except ValueError:
        raise SnapshotRefusalError(SnapshotRefusalReason.CALENDAR) from None
    problem = content_problem(content)
    if problem is not None:
        reason = (
            SnapshotRefusalReason.ROWS
            if "activities" in problem
            else SnapshotRefusalReason.CALENDAR
        )
        raise SnapshotRefusalError(reason)
    report = SnapshotReport(
        activities=len(activities),
        milestones=milestones,
        durations_quantized=counter.quantized,
        durations_out_of_range=counter.out_of_range,
        original_missing=counter.original_missing,
        remaining_missing=counter.remaining_missing,
    )
    return Snapshot(content=content, report=report)
