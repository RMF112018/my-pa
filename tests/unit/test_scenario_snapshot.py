"""Schedule Scenarios S6-1: version 1 as a publication snapshot (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` section 2.5 and
vector S1 (section 3.12): `minutes_per_source_unit` converts each
`published_value` duration with half-even rounding; out-of-range products are
null and counted, never clamped; other cell states are null and counted
missing; milestones get 0 and 0; published dates stay inert.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Final

import pytest

from my_pa.domain.schedule.model import (
    ScheduleActivityRowView,
    ScheduleBox,
    ScheduleCellState,
    ScheduleDateCell,
    ScheduleDurationCell,
    ScheduleRowType,
)
from my_pa.domain.schedule.scenario.canonical import content_object
from my_pa.domain.schedule.scenario.cpm import CpmIssueCode, CpmStatus, run_cpm
from my_pa.domain.schedule.scenario.model import (
    ActivityKind,
    LagCalendar,
    ProgressPolicy,
    format_instant,
)
from my_pa.domain.schedule.scenario.snapshot import (
    Snapshot,
    SnapshotRefusalError,
    SnapshotRefusalReason,
    SnapshotReport,
    snapshot_from_publication,
    snapshot_wbs_path,
)
from tests.fixtures.schedule_scenario import STD

PUBLICATION: Final = "spub_" + "p" * 26
VALUE: Final = ScheduleCellState.PUBLISHED_VALUE


def _duration(text: str | None, state: ScheduleCellState = VALUE) -> ScheduleDurationCell:
    return ScheduleDurationCell(state, None if text is None else Decimal(text))


def _row(
    ordinal: int,
    published: str,
    original: ScheduleDurationCell,
    remaining: ScheduleDurationCell,
    row_type: ScheduleRowType = ScheduleRowType.ACTIVITY,
) -> ScheduleActivityRowView:
    return ScheduleActivityRowView(
        row_id=f"srow_{ordinal:08d}rowrowrow",
        schedule_activity_id=f"sact_{published.lower()}00000000",
        published_activity_id=published,
        activity_name=f"Synthetic  {published}",
        row_type=row_type,
        row_ordinal=ordinal,
        page_number=1,
        physical_line_ordinal=ordinal,
        hierarchy_path=("Synthetic WBS",),
        original_duration=original,
        remaining_duration=remaining,
        start=ScheduleDateCell(VALUE, date(2027, 1, 4), "*"),
        finish=ScheduleDateCell(VALUE, date(2027, 1, 8), None),
        warning_codes=(),
        box=ScheduleBox(0, 0, 10, 10),
        page_width_mpt=1000,
        page_height_mpt=1000,
    )


S1_ROWS: Final = (
    _row(1, "X1", _duration("1.500"), _duration("0.001")),
    _row(2, "X2", _duration("0.003"), _duration("0.005")),
    _row(3, "X3", _duration("999999999.000"), _duration(None, ScheduleCellState.PUBLISHED_BLANK)),
    _row(4, "X4", _duration("0.000"), _duration("0.000"), ScheduleRowType.MILESTONE),
)

#: Vector S1: key -> (original_minutes, remaining_minutes, kind).
S1_EXPECTED: Final = {
    "X1": (750, 0, ActivityKind.TASK),
    "X2": (2, 2, ActivityKind.TASK),
    "X3": (None, None, ActivityKind.TASK),
    "X4": (0, 0, ActivityKind.MILESTONE),
}
S1_REPORT: Final = SnapshotReport(
    activities=4,
    milestones=1,
    durations_quantized=3,
    durations_out_of_range=1,
    original_missing=0,
    remaining_missing=1,
)


def _snapshot(rows: tuple[ScheduleActivityRowView, ...] = S1_ROWS, **overrides: object) -> Snapshot:
    arguments: dict[str, object] = {
        "publication_id": PUBLICATION,
        "data_date": date(2027, 1, 4),
        "rows": rows,
        "minutes_per_source_unit": 500,
        "calendars": (STD,),
        "default_calendar": "std",
    }
    arguments.update(overrides)
    return snapshot_from_publication(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize("vector", ["S1"])
def test_golden_snapshot(vector: str) -> None:
    assert vector == "S1"
    snapshot = _snapshot()
    assert snapshot.report == S1_REPORT
    by_published = {
        activity.published_reference.published_activity_id: activity  # type: ignore[union-attr]
        for activity in snapshot.content.activities
    }
    for published, (original, remaining, kind) in S1_EXPECTED.items():
        activity = by_published[published]
        assert (activity.original_minutes, activity.remaining_minutes, activity.kind) == (
            original,
            remaining,
            kind,
        ), published


def test_snapshot_fields_follow_the_contract() -> None:
    content = _snapshot().content
    assert format_instant(content.data_date) == "2027-01-04T00:00"
    assert content.settings.default_calendar == "std"
    assert content.settings.lag_calendar is LagCalendar.PREDECESSOR
    assert content.settings.progress_policy is ProgressPolicy.RETAINED_LOGIC
    assert content.settings.must_finish_by is None
    assert content.settings.critical_float_threshold_minutes == 0
    assert content.relationships == ()
    first = content.activities[0]
    assert first.key == "sact_x100000000"
    assert first.name == "Synthetic X1"
    assert first.wbs_path == ("Synthetic WBS",)
    assert (first.calendar, first.constraints, first.progress, first.distribution) == (
        None,
        (),
        None,
        None,
    )
    reference = content_object(content)["activities"][0]["published_reference"]  # type: ignore[index]
    assert reference == {
        "publication_id": PUBLICATION,
        "published_activity_id": "X1",
        "original_duration": {"state": "published_value", "value": "1.500"},
        "remaining_duration": {"state": "published_value", "value": "0.001"},
        "start": {"state": "published_value", "value": "2027-01-04", "marker": "*"},
        "finish": {"state": "published_value", "value": "2027-01-08", "marker": None},
    }


def test_snapshot_data_date_time_and_the_run_it_feeds() -> None:
    snapshot = _snapshot(data_date_time="07:30")
    assert format_instant(snapshot.content.data_date) == "2027-01-04T07:30"
    result = run_cpm(snapshot.content)
    # X3 has no remaining duration until the client sets one (never clamped).
    assert result.status is CpmStatus.REJECTED
    assert [(issue.code, issue.activity_key) for issue in result.issues] == [
        (CpmIssueCode.MISSING_DURATION, "sact_x300000000")
    ]


def test_snapshot_refusals() -> None:
    for factor in (0, 1441, True, "500"):
        with pytest.raises(SnapshotRefusalError) as raised:
            _snapshot(minutes_per_source_unit=factor)
        assert raised.value.reason is SnapshotRefusalReason.MINUTES_PER_SOURCE_UNIT
    for clock in ("7:30", "24:00", "07:60"):
        with pytest.raises(SnapshotRefusalError) as raised:
            _snapshot(data_date_time=clock)
        assert raised.value.reason is SnapshotRefusalReason.DATA_DATE
    with pytest.raises(SnapshotRefusalError) as raised:
        _snapshot(default_calendar="c6")
    assert raised.value.reason is SnapshotRefusalReason.CALENDAR
    with pytest.raises(SnapshotRefusalError) as raised:
        _snapshot(calendars=())
    assert raised.value.reason is SnapshotRefusalReason.CALENDAR
    with pytest.raises(SnapshotRefusalError) as raised:
        _snapshot(rows=(S1_ROWS[0], S1_ROWS[0]))
    assert raised.value.reason is SnapshotRefusalReason.ROWS


def test_a_boundary_product_is_kept_and_one_more_unit_is_out_of_range() -> None:
    rows = (
        _row(1, "Y1", _duration("3650.000"), _duration("3650.001")),
        _row(2, "Y2", _duration("3650.000"), _duration("3651.000")),
    )
    snapshot = _snapshot(rows, minutes_per_source_unit=1440)
    minutes = {
        a.published_reference.published_activity_id: (a.original_minutes, a.remaining_minutes)
        for a in snapshot.content.activities
    }  # type: ignore[union-attr]
    # 3650 * 1440 = 5,256,000 (the maximum); 3650.001 * 1440 = 5,256,001.44 -> 5,256,001.
    assert minutes == {"Y1": (5_256_000, None), "Y2": (5_256_000, None)}
    assert snapshot.report.durations_out_of_range == 2
    assert snapshot.report.durations_quantized == 0


def test_hierarchy_paths_map_deterministically() -> None:
    """Section 2.5 (FR8-F02): empty or holed paths are null; labels are normalized."""
    paths = {
        "H1": None,
        "H2": (),
        "H3": ("",),
        "H4": ("Site", "   "),
        "H5": ("  Site ", "Zone\t1"),
    }
    rows = tuple(
        replace(_row(index, name, _duration("1.000"), _duration("1.000")), hierarchy_path=path)
        for index, (name, path) in enumerate(paths.items(), 1)
    )
    content = _snapshot(rows).content
    by_published = {
        activity.published_reference.published_activity_id: activity.wbs_path  # type: ignore[union-attr]
        for activity in content.activities
    }
    assert by_published == {
        "H1": None,
        "H2": None,
        "H3": None,
        "H4": None,
        "H5": ("Site", "Zone 1"),
    }
    assert snapshot_wbs_path(("a",) * 32) == ("a",) * 32


def test_a_row_a_scenario_activity_cannot_hold_is_a_closed_refusal() -> None:
    unnamed = replace(_row(1, "U1", _duration("1.000"), _duration("1.000")), activity_name="   ")
    with pytest.raises(SnapshotRefusalError) as raised:
        _snapshot((unnamed,))
    assert raised.value.reason is SnapshotRefusalReason.ROWS
