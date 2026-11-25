"""Schedule Scenarios S6-1: the change-set grammar and its application (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` section 2.9: ops are
applied in request order, each against the state the ops before it left; the
first failure is `ChangeSetRefusal(op_index, op_error)` with one of the 14
closed tokens; a failed final re-validation is `(len(ops), content_invalid)`;
nothing is partially applied; an empty effective change is allowed.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Final

import pytest

from my_pa.domain.schedule.scenario.canonical import (
    CONTENT_SCHEMA,
    CONTENT_SCHEMA_V2,
    content_schema,
    content_sha256,
)
from my_pa.domain.schedule.scenario.changeset import (
    ApplicationReport,
    ChangeOp,
    ChangeOpError,
    ChangeSetApplied,
    ChangeSetRefusal,
    apply_change_set,
)
from my_pa.domain.schedule.scenario.model import (
    ActivityKind,
    ActivityState,
    ConstraintType,
    FixedLagCalendar,
    LagCalendar,
    ScenarioActivity,
    ScenarioContent,
    activity_state,
)
from tests.fixtures.schedule_scenario import DAY, STD, at, link, network, task

E = ChangeOpError
SOURCE_KEY: Final = "sact_" + "a" * 26


def _parent() -> ScenarioContent:
    return network(
        [task("A", DAY), task("B", 2 * DAY), task("C", DAY)],
        [link("A", "B"), link("B", "C")],
    )


def _applied(ops: list[object], parent: ScenarioContent | None = None) -> ChangeSetApplied:
    outcome = apply_change_set(parent or _parent(), ops)
    assert isinstance(outcome, ChangeSetApplied), outcome
    return outcome


def _refused(ops: list[object], parent: ScenarioContent | None = None) -> ChangeSetRefusal:
    outcome = apply_change_set(parent or _parent(), ops)
    assert isinstance(outcome, ChangeSetRefusal), outcome
    return outcome


def _activity(content: ScenarioContent, key: str) -> ScenarioActivity:
    return {item.key: item for item in content.activities}[key]


def test_change_set_applies_in_request_order() -> None:
    # Two edits of one field: the later op wins, so request order is observable.
    renamed = _applied(
        [
            {"op": "activity.edit", "key": "x:A", "name": "Second"},
            {"op": "activity.edit", "key": "x:A", "name": "First"},
        ]
    )
    assert _activity(renamed.content, "x:A").name == "First"
    # Each op sees the state the ops before it left: link, then remove its end.
    removed = _applied(
        [
            {"op": "relationship.add", "pred": "x:A", "succ": "x:C", "type": "SS"},
            {"op": "activity.remove", "key": "x:C"},
        ]
    )
    assert removed.report == ApplicationReport(
        ops_applied=2, relationships_removed=2, content_changed=True
    )
    assert [(item.pred, item.succ) for item in removed.content.relationships] == [("x:A", "x:B")]
    # The reverse order refers to a key the first op already removed.
    assert _refused(
        [
            {"op": "activity.remove", "key": "x:C"},
            {"op": "relationship.add", "pred": "x:A", "succ": "x:C", "type": "SS"},
        ]
    ) == ChangeSetRefusal(1, E.KEY_ABSENT)


def test_added_activity_cannot_take_a_source_key() -> None:
    assert _refused(
        [{"op": "activity.add", "key": SOURCE_KEY, "name": "Mine", "kind": "task"}]
    ) == ChangeSetRefusal(0, E.SOURCE_KEY_REFUSED)
    assert _refused(
        [{"op": "activity.add", "key": "sact_bad", "name": "Mine", "kind": "task"}]
    ) == ChangeSetRefusal(0, E.SOURCE_KEY_REFUSED)
    assert _refused(
        [{"op": "activity.add", "key": "y:free", "name": "Mine", "kind": "task"}]
    ) == ChangeSetRefusal(0, E.INVALID_FIELD)
    assert _refused(
        [{"op": "activity.add", "key": "x:A", "name": "Again", "kind": "task"}]
    ) == ChangeSetRefusal(0, E.KEY_EXISTS)


def test_final_revalidation_refuses_with_content_invalid() -> None:
    # Progress is checked against the working data date at its op; moving the
    # data date earlier afterwards is caught only by the final re-validation.
    ops = [
        {"op": "progress.set", "key": "x:A", "actual_start": "2027-01-04T08:00"},
        {"op": "data_date.set", "at": "2027-01-01T00:00"},
    ]
    parent = network([task("A", DAY)], data_date="01-06 00:00")
    assert isinstance(apply_change_set(parent, ops[:1]), ChangeSetApplied)
    assert _refused(ops, parent) == ChangeSetRefusal(2, E.CONTENT_INVALID)
    assert _refused(ops, parent).op_index == len(ops)


def test_activity_ops() -> None:
    added = _applied(
        [
            {
                "op": "activity.add",
                "key": "x:D",
                "name": "  New\tactivity ",
                "kind": "task",
                "remaining_minutes": 300,
                "wbs_path": ["Phase  1"],
            },
            {"op": "activity.add", "key": "x:M", "name": "Done", "kind": "milestone"},
            {"op": "activity.edit", "key": "x:B", "kind": "task", "wbs_path": None},
        ]
    ).content
    new = _activity(added, "x:D")
    assert (new.name, new.wbs_path, new.remaining_minutes, new.original_minutes) == (
        "New activity",
        ("Phase 1",),
        300,
        None,
    )
    assert _activity(added, "x:M").kind is ActivityKind.MILESTONE
    assert _activity(added, "x:M").remaining_minutes == 0
    assert _refused([{"op": "activity.edit", "key": "x:A", "kind": "milestone"}]) == (
        ChangeSetRefusal(0, E.INVALID_FIELD)
    )
    assert _refused([{"op": "activity.edit", "key": "x:A"}]) == ChangeSetRefusal(0, E.INVALID_FIELD)
    assert _refused([{"op": "activity.edit", "key": "x:Q", "name": "Q"}]) == ChangeSetRefusal(
        0, E.KEY_ABSENT
    )
    assert _refused(
        [{"op": "activity.add", "key": "x:D", "name": "D", "kind": "task", "calendar": "c6"}]
    ) == ChangeSetRefusal(0, E.CALENDAR_ABSENT)
    assert _refused([{"op": "activity.add", "key": "x:D", "name": "", "kind": "task"}]) == (
        ChangeSetRefusal(0, E.INVALID_FIELD)
    )


def test_duration_and_distribution_ops() -> None:
    content = _applied(
        [
            {"op": "duration.set", "key": "x:A", "remaining_minutes": None},
            {"op": "duration.set", "key": "x:B", "original_minutes": 7, "remaining_minutes": 9},
            {
                "op": "distribution.set",
                "key": "x:B",
                "distribution": {"kind": "pert", "min": 1, "mode": 9, "max": 20},
            },
            {"op": "distribution.clear", "key": "x:C"},
        ]
    ).content
    assert _activity(content, "x:A").remaining_minutes is None
    assert (
        _activity(content, "x:B").original_minutes,
        _activity(content, "x:B").remaining_minutes,
    ) == (7, 9)
    assert _activity(content, "x:B").distribution is not None
    assert _refused(
        [
            {
                "op": "distribution.set",
                "key": "x:B",
                "distribution": {"kind": "pert", "min": 1, "max": 2},
            }
        ]
    ) == ChangeSetRefusal(0, E.INVALID_FIELD)
    assert _refused([{"op": "duration.set", "key": "x:A", "remaining_minutes": -1}]) == (
        ChangeSetRefusal(0, E.INVALID_FIELD)
    )
    assert _refused([{"op": "duration.set", "key": "x:A", "remaining_minutes": 2.5}]) == (
        ChangeSetRefusal(0, E.INVALID_FIELD)
    )


def test_relationship_ops() -> None:
    content = _applied(
        [
            {
                "op": "relationship.add",
                "pred": "x:A",
                "succ": "x:C",
                "type": "FF",
                "lag_minutes": -60,
            },
            {"op": "relationship.edit", "pred": "x:A", "succ": "x:B", "type": "SS"},
            {"op": "relationship.remove", "pred": "x:B", "succ": "x:C"},
        ]
    ).content
    assert [(r.pred, r.succ, r.type.value, r.lag_minutes) for r in content.relationships] == [
        ("x:A", "x:B", "SS", 0),
        ("x:A", "x:C", "FF", -60),
    ]
    cases = [
        (
            {"op": "relationship.add", "pred": "x:A", "succ": "x:B", "type": "FS"},
            E.RELATIONSHIP_EXISTS,
        ),
        ({"op": "relationship.add", "pred": "x:A", "succ": "x:A", "type": "FS"}, E.SELF_LOOP),
        ({"op": "relationship.add", "pred": "x:A", "succ": "x:Z", "type": "FS"}, E.KEY_ABSENT),
        ({"op": "relationship.add", "pred": "x:A", "succ": "x:C", "type": "XX"}, E.INVALID_FIELD),
        (
            {"op": "relationship.edit", "pred": "x:A", "succ": "x:C", "lag_minutes": 5},
            E.RELATIONSHIP_ABSENT,
        ),
        ({"op": "relationship.remove", "pred": "x:C", "succ": "x:A"}, E.RELATIONSHIP_ABSENT),
        (
            {
                "op": "relationship.add",
                "pred": "x:A",
                "succ": "x:C",
                "type": "FS",
                "lag_minutes": 1_051_201,
            },
            E.INVALID_FIELD,
        ),
    ]
    for op, error in cases:
        assert _refused([op]) == ChangeSetRefusal(0, error), op


def test_cycles_are_storable() -> None:
    content = _applied(
        [{"op": "relationship.add", "pred": "x:C", "succ": "x:A", "type": "FS"}]
    ).content
    assert len(content.relationships) == 3


def test_calendar_ops() -> None:
    six_day = {"key": "c6", "week": [[[480, 960]]] * 6 + [[]], "exceptions": []}
    content = _applied(
        [
            {"op": "calendar.put", "calendar": six_day},
            {"op": "activity.edit", "key": "x:A", "calendar": "c6"},
            {"op": "calendar.exception.put", "key": "std", "date": "2027-01-05", "intervals": []},
            {
                "op": "calendar.exception.put",
                "key": "std",
                "date": "2027-01-05",
                "intervals": [[480, 600]],
            },
            {"op": "calendar.exception.remove", "key": "c6", "date": "2027-02-01"},
            {
                "op": "settings.set",
                "lag_calendar": "twenty_four_hour",
                "critical_float_threshold_minutes": 60,
            },
        ]
    ).content
    assert [item.key for item in content.calendars] == ["c6", "std"]
    std = {item.key: item for item in content.calendars}["std"]
    assert [(item.day.isoformat(), item.intervals) for item in std.exceptions] == [
        ("2027-01-05", ((480, 600),))
    ]
    assert content.settings.lag_calendar is LagCalendar.TWENTY_FOUR_HOUR
    assert content.settings.critical_float_threshold_minutes == 60
    assert _refused([{"op": "calendar.remove", "key": "std"}]) == ChangeSetRefusal(
        0, E.CALENDAR_IN_USE
    )
    assert _refused([{"op": "calendar.remove", "key": "c6"}], content) == ChangeSetRefusal(
        0, E.CALENDAR_IN_USE
    )
    assert _refused([{"op": "calendar.remove", "key": "c9"}]) == ChangeSetRefusal(
        0, E.CALENDAR_ABSENT
    )
    assert _refused([{"op": "settings.set", "default_calendar": "c9"}]) == ChangeSetRefusal(
        0, E.CALENDAR_ABSENT
    )
    assert _refused(
        [{"op": "calendar.put", "calendar": {"key": "idle", "week": [[]] * 7, "exceptions": []}}]
    ) == ChangeSetRefusal(0, E.INVALID_FIELD)
    assert _refused(
        [{"op": "calendar.exception.put", "key": "std", "date": "2100-01-01", "intervals": []}]
    ) == ChangeSetRefusal(0, E.INVALID_FIELD)
    removed = _applied(
        [
            {"op": "activity.edit", "key": "x:A", "calendar": None},
            {"op": "calendar.remove", "key": "c6"},
        ],
        content,
    ).content
    assert [item.key for item in removed.calendars] == ["std"]


def _holidays(count: int, first: date = date(2027, 1, 1)) -> list[dict[str, object]]:
    return [
        {"date": (first + timedelta(days=offset)).isoformat(), "intervals": []}
        for offset in range(count)
    ]


def _calendar(key: str, exceptions: list[dict[str, object]]) -> dict[str, object]:
    return {"key": key, "week": [[[480, 960]]] * 5 + [[], []], "exceptions": exceptions}


def test_calendar_bounds() -> None:
    ops: list[object] = [
        {"op": "calendar.put", "calendar": _calendar(f"k{index:02d}", [])} for index in range(31)
    ]
    assert isinstance(apply_change_set(_parent(), ops), ChangeSetApplied)
    assert _refused([*ops, {"op": "calendar.put", "calendar": _calendar("k99", [])}]) == (
        ChangeSetRefusal(31, E.BOUND_EXCEEDED)
    )
    assert isinstance(
        apply_change_set(
            _parent(), [{"op": "calendar.put", "calendar": _calendar("std", _holidays(1000))}]
        ),
        ChangeSetApplied,
    )
    assert _refused([{"op": "calendar.put", "calendar": _calendar("std", _holidays(1001))}]) == (
        ChangeSetRefusal(0, E.BOUND_EXCEEDED)
    )
    two = [
        {"op": "calendar.put", "calendar": _calendar("std", _holidays(1000))},
        {"op": "calendar.put", "calendar": _calendar("k1", _holidays(1000))},
    ]
    assert isinstance(apply_change_set(_parent(), two), ChangeSetApplied)
    assert _refused([*two, {"op": "calendar.put", "calendar": _calendar("k2", _holidays(1))}]) == (
        ChangeSetRefusal(2, E.BOUND_EXCEEDED)
    )
    assert _refused(
        [*two, {"op": "calendar.exception.put", "key": "k1", "date": "2030-01-01", "intervals": []}]
    ) == ChangeSetRefusal(2, E.BOUND_EXCEEDED)


def test_constraint_ops() -> None:
    content = _applied(
        [
            {"op": "constraint.set", "key": "x:B", "type": "SNET", "at": "2027-01-11T08:00"},
            {"op": "constraint.set", "key": "x:B", "type": "FNET", "at": "2027-01-12T16:00"},
            {"op": "constraint.set", "key": "x:B", "type": "FNLT", "at": "2027-02-12T16:00"},
            {"op": "constraint.set", "key": "x:C", "type": "MSO", "at": "2027-01-20T08:00"},
            {"op": "constraint.set", "key": "x:C", "type": "MFO", "at": "2027-01-21T16:00"},
            {"op": "constraint.clear", "key": "x:A", "type": "SNLT"},
        ]
    ).content
    assert [item.type for item in _activity(content, "x:B").constraints] == [
        ConstraintType.FNET,
        ConstraintType.FNLT,
    ]
    assert [item.type for item in _activity(content, "x:C").constraints] == [ConstraintType.MFO]
    assert _refused(
        [{"op": "constraint.set", "key": "x:C", "type": "SNLT", "at": "2027-01-21T16:00"}], content
    ) == ChangeSetRefusal(0, E.CONSTRAINT_CONFLICT)
    assert _refused(
        [{"op": "constraint.set", "key": "x:B", "type": "MSO", "at": "2027-01-21T16:00"}], content
    ) == ChangeSetRefusal(0, E.CONSTRAINT_CONFLICT)
    assert _refused(
        [{"op": "constraint.set", "key": "x:B", "type": "MSO", "at": "2100-01-02T00:00"}]
    ) == ChangeSetRefusal(0, E.INVALID_FIELD)


def test_progress_ops() -> None:
    content = _applied(
        [
            {"op": "data_date.set", "at": "2027-01-06T00:00"},
            {
                "op": "progress.set",
                "key": "x:A",
                "actual_start": "2027-01-04T08:00",
                "actual_finish": "2027-01-04T16:00",
            },
            {
                "op": "progress.set",
                "key": "x:B",
                "actual_start": "2027-01-05T08:00",
                "remaining_minutes": 600,
            },
            {"op": "progress.clear", "key": "x:C"},
        ]
    ).content
    assert activity_state(_activity(content, "x:A")) is ActivityState.COMPLETE
    assert _activity(content, "x:A").remaining_minutes == 0
    assert activity_state(_activity(content, "x:B")) is ActivityState.IN_PROGRESS
    assert _activity(content, "x:B").remaining_minutes == 600
    cases = [
        {"op": "progress.set", "key": "x:A", "actual_start": "2027-01-05T08:00"},
        {
            "op": "progress.set",
            "key": "x:A",
            "actual_start": "2027-01-03T08:00",
            "actual_finish": "2027-01-02T08:00",
        },
        {
            "op": "progress.set",
            "key": "x:A",
            "actual_start": "2027-01-03T08:00",
            "actual_finish": "2027-01-03T16:00",
            "remaining_minutes": 5,
        },
    ]
    parent = network([task("A", DAY)], data_date="01-04 00:00")
    for op in cases:
        assert _refused([op], parent) == ChangeSetRefusal(0, E.PROGRESS_INVALID), op
    assert _refused(
        [{"op": "progress.set", "key": "x:A", "actual_finish": "2027-01-03T16:00"}], parent
    ) == (ChangeSetRefusal(0, E.INVALID_FIELD))
    done = network(
        [task("A", 0, started="01-04 08:00", finished="01-04 16:00")], data_date="01-05 00:00"
    )
    assert _refused([{"op": "duration.set", "key": "x:A", "remaining_minutes": 5}], done) == (
        ChangeSetRefusal(0, E.PROGRESS_INVALID)
    )


def test_grammar_refusals() -> None:
    assert _refused([{"op": "activity.rename", "key": "x:A"}]) == ChangeSetRefusal(0, E.UNKNOWN_OP)
    assert _refused([{"key": "x:A"}]) == ChangeSetRefusal(0, E.UNKNOWN_OP)
    assert _refused(["activity.remove"]) == ChangeSetRefusal(0, E.INVALID_FIELD)
    assert _refused([{"op": "activity.remove", "key": "x:A", "extra": 1}]) == ChangeSetRefusal(
        0, E.INVALID_FIELD
    )
    assert _refused([]) == ChangeSetRefusal(0, E.BOUND_EXCEEDED)
    assert _refused([{"op": "progress.clear", "key": "x:A"}] * 5_001) == ChangeSetRefusal(
        0, E.BOUND_EXCEEDED
    )
    assert _refused([{"op": "settings.set"}]) == ChangeSetRefusal(0, E.INVALID_FIELD)
    assert _refused([{"op": "data_date.set", "at": float("nan")}]) == ChangeSetRefusal(
        0, E.INVALID_FIELD
    )
    assert {member.value for member in ChangeOp} == {
        "activity.add",
        "activity.edit",
        "activity.remove",
        "duration.set",
        "distribution.set",
        "distribution.clear",
        "relationship.add",
        "relationship.edit",
        "relationship.remove",
        "calendar.put",
        "calendar.remove",
        "calendar.exception.put",
        "calendar.exception.remove",
        "constraint.set",
        "constraint.clear",
        "progress.set",
        "progress.clear",
        "data_date.set",
        "settings.set",
    }
    assert [member.value for member in ChangeOpError] == [
        "unknown_op",
        "invalid_field",
        "key_exists",
        "key_absent",
        "source_key_refused",
        "relationship_exists",
        "relationship_absent",
        "self_loop",
        "calendar_absent",
        "calendar_in_use",
        "constraint_conflict",
        "progress_invalid",
        "bound_exceeded",
        "content_invalid",
    ]


def test_an_empty_effective_change_is_allowed_and_a_refusal_changes_nothing() -> None:
    parent = _parent()
    digest = content_sha256(parent)
    same = _applied([{"op": "distribution.clear", "key": "x:A"}], parent)
    assert same.content == parent
    assert same.report == ApplicationReport(
        ops_applied=1, relationships_removed=0, content_changed=False
    )
    refused = apply_change_set(
        parent,
        [{"op": "activity.remove", "key": "x:A"}, {"op": "activity.remove", "key": "x:A"}],
    )
    assert refused == ChangeSetRefusal(1, E.KEY_ABSENT)
    assert content_sha256(parent) == digest
    assert len(parent.activities) == 3


@pytest.mark.parametrize(
    "op",
    [
        {"op": "activity.add", "key": "x:N", "name": "N", "kind": "task", "remaining_minutes": 0},
        {"op": "data_date.set", "at": "2027-01-05T00:00"},
    ],
)
def test_applied_content_reruns_cleanly(op: dict[str, object]) -> None:
    content = _applied([op]).content
    assert content.calendars == (STD,)
    assert at("01-04 00:00") <= content.data_date


def test_progress_finish_after_the_data_date_is_refused_at_its_op() -> None:
    """Section 2.9: `progress.set` is checked against the working data date at its own op.

    A later `data_date.set` that would make the finish admissible does not rescue it.
    """
    parent = network([task("A", DAY)], data_date="01-04 00:00")
    ops = [
        {
            "op": "progress.set",
            "key": "x:A",
            "actual_start": "2027-01-01T08:00",
            "actual_finish": "2027-01-05T08:00",
        },
        {"op": "data_date.set", "at": "2027-01-06T00:00"},
    ]
    assert _refused(ops, parent) == ChangeSetRefusal(0, E.PROGRESS_INVALID)


# --- S7-0 (import contract section 11.7): edged milestones, fixed lag calendar ------------


def _add(key: str, kind: str) -> dict[str, object]:
    return {"op": "activity.add", "key": key, "name": key, "kind": kind}


def test_activity_add_and_edit_accept_the_edged_kinds() -> None:
    added = _applied([_add("x:S", "start_milestone"), _add("x:F", "finish_milestone")])
    start, finish = _activity(added.content, "x:S"), _activity(added.content, "x:F")
    assert (start.kind, start.original_minutes, start.remaining_minutes) == (
        ActivityKind.START_MILESTONE,
        0,
        0,
    )
    assert (finish.kind, finish.original_minutes, finish.remaining_minutes) == (
        ActivityKind.FINISH_MILESTONE,
        0,
        0,
    )
    edited = _applied(
        [{"op": "activity.edit", "key": "x:S", "kind": "finish_milestone"}], added.content
    )
    assert _activity(edited.content, "x:S").kind is ActivityKind.FINISH_MILESTONE
    # Like `milestone`, an edged kind needs both durations 0.
    assert _refused([{"op": "activity.edit", "key": "x:A", "kind": "start_milestone"}]) == (
        ChangeSetRefusal(0, E.INVALID_FIELD)
    )


@pytest.mark.parametrize(
    ("kind", "constraint"),
    [
        ("start_milestone", "FNET"),
        ("start_milestone", "FNLT"),
        ("start_milestone", "MFO"),
        ("finish_milestone", "SNET"),
        ("finish_milestone", "SNLT"),
        ("finish_milestone", "MSO"),
    ],
)
def test_a_wrong_side_constraint_on_an_edged_milestone_is_a_conflict(
    kind: str, constraint: str
) -> None:
    """E4: a finish-side constraint on a start milestone, and the reverse."""
    ops: list[object] = [
        _add("x:M", kind),
        {"op": "constraint.set", "key": "x:M", "type": constraint, "at": "2027-01-05T08:00"},
    ]
    assert _refused(ops) == ChangeSetRefusal(1, E.CONSTRAINT_CONFLICT)


@pytest.mark.parametrize(
    ("kind", "constraints"),
    [
        ("start_milestone", ("SNET", "SNLT")),
        ("start_milestone", ("MSO",)),
        ("finish_milestone", ("FNET", "FNLT")),
        ("finish_milestone", ("MFO",)),
    ],
)
def test_an_own_side_constraint_on_an_edged_milestone_is_kept(
    kind: str, constraints: tuple[str, ...]
) -> None:
    ops: list[object] = [_add("x:M", kind)] + [
        {"op": "constraint.set", "key": "x:M", "type": name, "at": "2027-01-05T08:00"}
        for name in constraints
    ]
    content = _applied(ops).content
    assert [item.type.value for item in _activity(content, "x:M").constraints] == list(constraints)


def test_a_kind_edit_onto_a_wrong_side_constraint_is_a_conflict() -> None:
    parent = _applied(
        [
            _add("x:M", "milestone"),
            {"op": "constraint.set", "key": "x:M", "type": "FNLT", "at": "2027-01-05T16:00"},
        ]
    ).content
    assert _refused(
        [{"op": "activity.edit", "key": "x:M", "kind": "start_milestone"}], parent
    ) == ChangeSetRefusal(0, E.CONSTRAINT_CONFLICT)
    kept = _applied([{"op": "activity.edit", "key": "x:M", "kind": "finish_milestone"}], parent)
    assert _activity(kept.content, "x:M").kind is ActivityKind.FINISH_MILESTONE


def test_edged_milestone_progress_is_its_one_date() -> None:
    parent = _applied([_add("x:S", "start_milestone"), _add("x:F", "finish_milestone")]).content
    start_only = _applied(
        [{"op": "progress.set", "key": "x:S", "actual_start": "2027-01-01T08:00"}], parent
    )
    assert _activity(start_only.content, "x:S").progress is not None
    for ops in (
        # A start milestone's actual finish is null or its actual start.
        [
            {
                "op": "progress.set",
                "key": "x:S",
                "actual_start": "2027-01-01T08:00",
                "actual_finish": "2027-01-01T09:00",
            }
        ],
        # A finish milestone's date is its actual finish (the actual start equal).
        [{"op": "progress.set", "key": "x:F", "actual_start": "2027-01-01T08:00"}],
        [
            {
                "op": "progress.set",
                "key": "x:F",
                "actual_start": "2027-01-01T08:00",
                "actual_finish": "2027-01-01T16:00",
            }
        ],
    ):
        assert _refused(ops, parent) == ChangeSetRefusal(0, E.PROGRESS_INVALID), ops
    done = _applied(
        [
            {
                "op": "progress.set",
                "key": "x:F",
                "actual_start": "2027-01-01T16:00",
                "actual_finish": "2027-01-01T16:00",
            }
        ],
        parent,
    )
    assert activity_state(_activity(done.content, "x:F")) is ActivityState.COMPLETE


def test_settings_set_accepts_a_fixed_lag_calendar() -> None:
    parent = _applied(
        [
            {
                "op": "calendar.put",
                "calendar": {"key": "proj", "week": [[[480, 960]]] * 7, "exceptions": []},
            }
        ]
    ).content
    fixed = _applied([{"op": "settings.set", "lag_calendar": "calendar:proj"}], parent)
    assert fixed.content.settings.lag_calendar == FixedLagCalendar("proj")
    assert content_schema(fixed.content) == CONTENT_SCHEMA_V2
    assert _refused([{"op": "settings.set", "lag_calendar": "calendar:none"}], parent) == (
        ChangeSetRefusal(0, E.CALENDAR_ABSENT)
    )
    for wrong in ("calendar:", "calendar:UPPER", "project", 1):
        assert _refused([{"op": "settings.set", "lag_calendar": wrong}], parent) == (
            ChangeSetRefusal(0, E.INVALID_FIELD)
        ), wrong


def test_a_calendar_named_as_the_fixed_lag_calendar_cannot_be_removed() -> None:
    """E4: removal of a calendar named as the fixed lag calendar is `calendar_in_use`."""
    parent = _applied(
        [
            {
                "op": "calendar.put",
                "calendar": {"key": "proj", "week": [[[480, 960]]] * 7, "exceptions": []},
            },
            {"op": "settings.set", "lag_calendar": "calendar:proj"},
        ]
    ).content
    assert _refused([{"op": "calendar.remove", "key": "proj"}], parent) == ChangeSetRefusal(
        0, E.CALENDAR_IN_USE
    )
    released = _applied(
        [
            {"op": "settings.set", "lag_calendar": "predecessor"},
            {"op": "calendar.remove", "key": "proj"},
        ],
        parent,
    )
    assert content_schema(released.content) == CONTENT_SCHEMA


def test_the_child_schema_follows_the_content() -> None:
    """E5: a v2 feature makes a v2 child; removing every one returns the identical v1 hash."""
    parent = _parent()
    v1_digest = content_sha256(parent)
    assert content_schema(parent) == CONTENT_SCHEMA
    v2 = _applied([_add("x:S", "start_milestone")], parent).content
    assert content_schema(v2) == CONTENT_SCHEMA_V2
    back = _applied([{"op": "activity.remove", "key": "x:S"}], v2).content
    assert content_schema(back) == CONTENT_SCHEMA
    assert content_sha256(back) == v1_digest
    # Turning the kind back to `milestone` also returns to v1 (with that activity added).
    plain = _applied([_add("x:S", "milestone")], parent).content
    edged = _applied([{"op": "activity.edit", "key": "x:S", "kind": "finish_milestone"}], plain)
    unedged = _applied(
        [{"op": "activity.edit", "key": "x:S", "kind": "milestone"}], edged.content
    ).content
    assert content_sha256(unedged) == content_sha256(plain)
    assert content_schema(unedged) == CONTENT_SCHEMA
