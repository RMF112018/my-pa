"""CPM Workbench S5b-2: the A-to-B delta `cpm-workbench-full-delta-v1` (FAST).

Worker and capabilities contract section 3.10 (R2 section 29): every change kind
and its rule, `reintroduced` replacing `added` for a Stable Activity observed
before A, the to-minus-from sign convention, no number for a non-value state,
marker-only and provenance-only differences emitting nothing, one merge pass,
and the `(published_activity_id, kind_rank, field_rank)` order with counts over
all 11 kinds. Every value is synthetic.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Final

import pytest

from my_pa.domain.schedule import (
    ScheduleCellState,
    ScheduleDateCell,
    ScheduleDurationCell,
    ScheduleFieldCode,
    ScheduleRowType,
)
from my_pa.domain.schedule.compare import (
    DELTA_ALGORITHM_VERSION,
    ScheduleActivityIdentity,
    ScheduleChange,
    ScheduleChangeKind,
    ScheduleComparisonRow,
    ScheduleHierarchySide,
    change_sort_key,
    compare_publications,
    unmatched_target_activity_ids,
)

VALUE: Final = ScheduleCellState.PUBLISHED_VALUE
BLANK: Final = ScheduleCellState.PUBLISHED_BLANK
AMBIGUOUS: Final = ScheduleCellState.AMBIGUOUS


def _sact(published: str) -> str:
    return "sact_" + "".join(ch for ch in published if ch.isalnum()).ljust(8, "0")


def _row(published: str = "A-100", **overrides: object) -> ScheduleComparisonRow:
    fields: dict[str, object] = {
        "schedule_activity_id": _sact(published),
        "published_activity_id": published,
        "activity_name": "Synthetic activity",
        "row_type": ScheduleRowType.ACTIVITY,
        "hierarchy_path": ("Synthetic WBS",),
        "original_duration": ScheduleDurationCell(VALUE, Decimal("10.000")),
        "remaining_duration": ScheduleDurationCell(VALUE, Decimal("5.000")),
        "start": ScheduleDateCell(VALUE, date(2026, 5, 4), None),
        "finish": ScheduleDateCell(VALUE, date(2026, 5, 15), None),
    }
    fields.update(overrides)
    return ScheduleComparisonRow(**fields)  # type: ignore[arg-type]


def _only(changes: tuple[ScheduleChange, ...]) -> ScheduleChange:
    (change,) = changes
    return change


#: One A/B pair per kind that emits exactly that kind and nothing else.
_CASES: Final[
    dict[
        ScheduleChangeKind,
        tuple[list[ScheduleComparisonRow], list[ScheduleComparisonRow], frozenset[str]],
    ]
] = {
    ScheduleChangeKind.ADDED: ([], [_row()], frozenset()),
    ScheduleChangeKind.REMOVED: ([_row()], [], frozenset()),
    ScheduleChangeKind.REINTRODUCED: ([], [_row()], frozenset({_sact("A-100")})),
    ScheduleChangeKind.RENAMED: ([_row()], [_row(activity_name="Renamed activity")], frozenset()),
    ScheduleChangeKind.ROW_TYPE_CHANGED: (
        [_row()],
        [_row(row_type=ScheduleRowType.MILESTONE)],
        frozenset(),
    ),
    ScheduleChangeKind.ORIGINAL_DURATION_CHANGED: (
        [_row()],
        [_row(original_duration=ScheduleDurationCell(VALUE, Decimal("12.500")))],
        frozenset(),
    ),
    ScheduleChangeKind.REMAINING_DURATION_CHANGED: (
        [_row()],
        [_row(remaining_duration=ScheduleDurationCell(VALUE, Decimal("3.000")))],
        frozenset(),
    ),
    ScheduleChangeKind.START_CHANGED: (
        [_row()],
        [_row(start=ScheduleDateCell(VALUE, date(2026, 5, 11), None))],
        frozenset(),
    ),
    ScheduleChangeKind.FINISH_CHANGED: (
        [_row()],
        [_row(finish=ScheduleDateCell(VALUE, date(2026, 5, 12), None))],
        frozenset(),
    ),
    ScheduleChangeKind.HIERARCHY_CHANGED: (
        [_row()],
        [_row(hierarchy_path=("Synthetic WBS", "Phase 2"))],
        frozenset(),
    ),
    ScheduleChangeKind.FIELD_STATE_CHANGED: (
        [_row()],
        [_row(remaining_duration=ScheduleDurationCell(BLANK, None))],
        frozenset(),
    ),
}


def test_the_kinds_are_the_eleven_in_rank_order() -> None:
    assert [kind.value for kind in ScheduleChangeKind] == [
        "added",
        "removed",
        "reintroduced",
        "renamed",
        "row_type_changed",
        "original_duration_changed",
        "remaining_duration_changed",
        "start_changed",
        "finish_changed",
        "hierarchy_changed",
        "field_state_changed",
    ]
    assert DELTA_ALGORITHM_VERSION == "cpm-workbench-full-delta-v1"


@pytest.mark.parametrize("kind", list(ScheduleChangeKind), ids=lambda kind: kind.value)
def test_each_change_kind(kind: ScheduleChangeKind) -> None:
    before, after, prior = _CASES[kind]
    delta = compare_publications(before, after, prior)
    change = _only(delta.changes)
    assert change.change_kind is kind
    assert change.published_activity_id == "A-100"
    assert change.schedule_activity_id == _sact("A-100")
    assert delta.counts_by_kind[kind] == 1
    expected_field = {
        ScheduleChangeKind.ADDED: None,
        ScheduleChangeKind.REMOVED: None,
        ScheduleChangeKind.REINTRODUCED: None,
        ScheduleChangeKind.RENAMED: ScheduleFieldCode.ACTIVITY_NAME,
        ScheduleChangeKind.ROW_TYPE_CHANGED: None,
        ScheduleChangeKind.ORIGINAL_DURATION_CHANGED: ScheduleFieldCode.ORIGINAL_DURATION,
        ScheduleChangeKind.REMAINING_DURATION_CHANGED: ScheduleFieldCode.REMAINING_DURATION,
        ScheduleChangeKind.START_CHANGED: ScheduleFieldCode.START,
        ScheduleChangeKind.FINISH_CHANGED: ScheduleFieldCode.FINISH,
        ScheduleChangeKind.HIERARCHY_CHANGED: ScheduleFieldCode.HIERARCHY,
        ScheduleChangeKind.FIELD_STATE_CHANGED: ScheduleFieldCode.REMAINING_DURATION,
    }[kind]
    assert change.field is expected_field
    identity = ScheduleActivityIdentity("Synthetic activity", ScheduleRowType.ACTIVITY)
    if kind is ScheduleChangeKind.REMOVED:
        assert (change.before, change.after) == (identity, None)
    elif kind in (ScheduleChangeKind.ADDED, ScheduleChangeKind.REINTRODUCED):
        assert (change.before, change.after) == (None, identity)
    elif kind is ScheduleChangeKind.RENAMED:
        assert (change.before, change.after) == ("Synthetic activity", "Renamed activity")
    elif kind is ScheduleChangeKind.ROW_TYPE_CHANGED:
        assert (change.before, change.after) == (
            ScheduleRowType.ACTIVITY,
            ScheduleRowType.MILESTONE,
        )


def test_reintroduced_replaces_added() -> None:
    a = [_row("A-100")]
    b = [_row("A-100"), _row("B-200"), _row("C-300")]
    # B-200 was observed before A (any role, superseded included); C-300 never.
    prior = frozenset({_sact("B-200")})
    assert unmatched_target_activity_ids(a, b) == frozenset({_sact("B-200"), _sact("C-300")})
    delta = compare_publications(a, b, prior)
    kinds = {change.published_activity_id: change.change_kind for change in delta.changes}
    assert kinds == {
        "B-200": ScheduleChangeKind.REINTRODUCED,
        "C-300": ScheduleChangeKind.ADDED,
    }
    assert delta.counts_by_kind[ScheduleChangeKind.ADDED] == 1
    assert delta.counts_by_kind[ScheduleChangeKind.REINTRODUCED] == 1


def test_sign_convention() -> None:
    a = [_row()]
    b = [
        _row(
            original_duration=ScheduleDurationCell(VALUE, Decimal("8.250")),
            remaining_duration=ScheduleDurationCell(VALUE, Decimal("7.000")),
            start=ScheduleDateCell(VALUE, date(2026, 5, 1), None),
            finish=ScheduleDateCell(VALUE, date(2026, 5, 20), None),
        )
    ]
    by_kind = {
        change.change_kind: change for change in compare_publications(a, b, frozenset()).changes
    }
    # to - from: a shorter OD is negative, a later finish positive.
    assert by_kind[ScheduleChangeKind.ORIGINAL_DURATION_CHANGED].delta_source_units == Decimal(
        "-1.750"
    )
    assert by_kind[ScheduleChangeKind.REMAINING_DURATION_CHANGED].delta_source_units == Decimal(
        "2.000"
    )
    assert by_kind[ScheduleChangeKind.START_CHANGED].delta_calendar_days == -3
    assert by_kind[ScheduleChangeKind.FINISH_CHANGED].delta_calendar_days == 5
    for change in by_kind.values():
        assert (change.delta_calendar_days is None) != (change.delta_source_units is None)


@pytest.mark.parametrize(
    ("field", "before", "after"),
    [
        (
            "original_duration",
            ScheduleDurationCell(VALUE, Decimal("10.000")),
            ScheduleDurationCell(AMBIGUOUS, None),
        ),
        (
            "remaining_duration",
            ScheduleDurationCell(BLANK, None),
            ScheduleDurationCell(VALUE, Decimal("4.000")),
        ),
        (
            "start",
            ScheduleDateCell(VALUE, date(2026, 5, 4), None),
            ScheduleDateCell(BLANK, None, None),
        ),
        (
            "finish",
            ScheduleDateCell(AMBIGUOUS, None, None),
            ScheduleDateCell(VALUE, date(2026, 6, 1), "*"),
        ),
    ],
)
def test_no_number_is_fabricated_for_non_value_states(
    field: str, before: object, after: object
) -> None:
    change = _only(
        compare_publications(
            [_row(**{field: before})], [_row(**{field: after})], frozenset()
        ).changes
    )
    assert change.change_kind is ScheduleChangeKind.FIELD_STATE_CHANGED
    assert change.field is ScheduleFieldCode(field)
    assert (change.before, change.after) == (before, after)
    assert change.delta_calendar_days is None
    assert change.delta_source_units is None


def test_both_sides_in_the_same_non_value_state_is_no_change() -> None:
    blank = ScheduleDurationCell(BLANK, None)
    assert not compare_publications(
        [_row(original_duration=blank)], [_row(original_duration=blank)], frozenset()
    ).changes


def test_hierarchy_null_on_one_side_is_a_field_state_change() -> None:
    change = _only(compare_publications([_row()], [_row(hierarchy_path=None)], frozenset()).changes)
    assert change.change_kind is ScheduleChangeKind.FIELD_STATE_CHANGED
    assert change.field is ScheduleFieldCode.HIERARCHY
    assert change.before == ScheduleHierarchySide(VALUE, ("Synthetic WBS",))
    assert change.after == ScheduleHierarchySide(AMBIGUOUS, None)
    assert not compare_publications(
        [_row(hierarchy_path=None)], [_row(hierarchy_path=None)], frozenset()
    ).changes


def test_marker_and_provenance_only_differences_emit_nothing() -> None:
    # An equal date that only gains a marker (planned -> actual) is not a v1
    # change (residual U2-07); the comparison row carries no page, ordinal, box
    # or style, so provenance cannot reach the delta at all.
    a = [_row(finish=ScheduleDateCell(VALUE, date(2026, 5, 15), None))]
    b = [_row(finish=ScheduleDateCell(VALUE, date(2026, 5, 15), "*"))]
    assert not compare_publications(a, b, frozenset()).changes
    assert {
        "page_number",
        "row_ordinal",
        "physical_line_ordinal",
        "box",
        "cells",
        "warning_codes",
    }.isdisjoint(ScheduleComparisonRow.__dataclass_fields__)


def test_equal_values_compare_as_decimals() -> None:
    a = [_row(original_duration=ScheduleDurationCell(VALUE, Decimal("1.500")))]
    b = [_row(original_duration=ScheduleDurationCell(VALUE, Decimal("1.500")))]
    assert not compare_publications(a, b, frozenset()).changes


class _Counted(str):
    """A published id that counts every comparison made with it."""

    __slots__ = ()
    calls = 0

    def __lt__(self, other: str) -> bool:
        _Counted.calls += 1
        return str.__lt__(self, other)

    def __gt__(self, other: str) -> bool:
        _Counted.calls += 1
        return str.__gt__(self, other)

    def __eq__(self, other: object) -> bool:
        _Counted.calls += 1
        return str.__eq__(self, other)

    def __ne__(self, other: object) -> bool:
        _Counted.calls += 1
        return str.__ne__(self, other)

    __hash__ = str.__hash__


def test_merge_is_single_pass() -> None:
    a = [
        _row(_Counted(f"A-{n:05d}"), schedule_activity_id=f"sact_a{n:08d}")
        for n in range(0, 600, 2)
    ]
    a += [_row(_Counted(f"B-{n:05d}"), schedule_activity_id=f"sact_b{n:08d}") for n in range(300)]
    b = [
        _row(_Counted(f"A-{n:05d}"), schedule_activity_id=f"sact_a{n:08d}")
        for n in range(1, 600, 2)
    ]
    b += [
        _row(
            _Counted(f"B-{n:05d}"),
            schedule_activity_id=f"sact_b{n:08d}",
            activity_name="Renamed",
        )
        for n in range(300)
    ]
    a.sort(key=lambda row: str(row.published_activity_id))
    b.sort(key=lambda row: str(row.published_activity_id))
    total = len(a) + len(b)
    _Counted.calls = 0
    delta = compare_publications(a, b, frozenset())
    # Each step compares the two current IDs at most twice and consumes a row:
    # no sort, no search, no second pass over either side.
    assert _Counted.calls <= 2 * total
    assert delta.counts_by_kind[ScheduleChangeKind.REMOVED] == 300
    assert delta.counts_by_kind[ScheduleChangeKind.ADDED] == 300
    assert delta.counts_by_kind[ScheduleChangeKind.RENAMED] == 300


def test_ordering_and_counts_by_kind() -> None:
    a = [
        _row("A-1"),
        _row("B-2"),
        _row("C-3", hierarchy_path=None),
    ]
    b = [
        _row(
            "A-1",
            activity_name="Renamed",
            original_duration=ScheduleDurationCell(AMBIGUOUS, None),
            remaining_duration=ScheduleDurationCell(VALUE, Decimal("1.000")),
            finish=ScheduleDateCell(VALUE, date(2026, 6, 1), None),
            hierarchy_path=("Other",),
        ),
        _row("C-3", hierarchy_path=("Synthetic WBS",)),
        _row("D-4"),
    ]
    delta = compare_publications(a, b, frozenset())
    assert [(c.published_activity_id, c.change_kind, c.field) for c in delta.changes] == [
        ("A-1", ScheduleChangeKind.RENAMED, ScheduleFieldCode.ACTIVITY_NAME),
        (
            "A-1",
            ScheduleChangeKind.REMAINING_DURATION_CHANGED,
            ScheduleFieldCode.REMAINING_DURATION,
        ),
        ("A-1", ScheduleChangeKind.FINISH_CHANGED, ScheduleFieldCode.FINISH),
        ("A-1", ScheduleChangeKind.HIERARCHY_CHANGED, ScheduleFieldCode.HIERARCHY),
        ("A-1", ScheduleChangeKind.FIELD_STATE_CHANGED, ScheduleFieldCode.ORIGINAL_DURATION),
        ("B-2", ScheduleChangeKind.REMOVED, None),
        ("C-3", ScheduleChangeKind.FIELD_STATE_CHANGED, ScheduleFieldCode.HIERARCHY),
        ("D-4", ScheduleChangeKind.ADDED, None),
    ]
    assert list(delta.changes) == sorted(delta.changes, key=change_sort_key)
    assert list(delta.counts_by_kind) == list(ScheduleChangeKind)
    assert dict(delta.counts_by_kind) == {
        **dict.fromkeys(ScheduleChangeKind, 0),
        ScheduleChangeKind.RENAMED: 1,
        ScheduleChangeKind.REMAINING_DURATION_CHANGED: 1,
        ScheduleChangeKind.FINISH_CHANGED: 1,
        ScheduleChangeKind.HIERARCHY_CHANGED: 1,
        ScheduleChangeKind.FIELD_STATE_CHANGED: 2,
        ScheduleChangeKind.REMOVED: 1,
        ScheduleChangeKind.ADDED: 1,
    }


def test_published_ids_order_by_code_point() -> None:
    # The repository orders `COLLATE "C"`; Python `str` order is the same
    # code-point order, so an upper-case, a lower-case and a non-ASCII ID merge
    # without a false add/remove pair.
    ids = sorted(["a-1", "B-1", "É-1", "Z-1"])
    assert ids == ["B-1", "Z-1", "a-1", "É-1"]
    rows = [_row(pid, schedule_activity_id=f"sact_{n:08d}") for n, pid in enumerate(ids)]
    assert not compare_publications(rows, rows, frozenset()).changes


def test_a_published_id_naming_two_stable_activities_is_refused() -> None:
    with pytest.raises(ValueError, match="one stable activity"):
        compare_publications(
            [_row()], [replace(_row(), schedule_activity_id="sact_other0001")], frozenset()
        )
