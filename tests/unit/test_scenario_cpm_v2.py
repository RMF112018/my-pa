"""S7-0: engine `my-pa-cpm-v2` -- start and finish milestones, fixed lag calendars (FAST).

Contract `docs/architecture/schedule-xer-import-contract.md` section 11.7 (E1,
E2, E3, E8 at the domain level). Calendar `std` is Monday-Friday 08:00-16:00;
`D = 2027-01-04T00:00` (a Monday) unless stated; instants are written
`MM-DD HH:MM` in 2027. Every expectation below was computed by hand from the
section 11.7 table and the S6 section 3 rules:

* forward, start milestone: `ES = EF = next_work(C, x)`; finish milestone:
  `ES = EF = max(D, prev_end(C, x))`;
* backward, start milestone: `LS = LF = next_work(C, y)`; finish milestone:
  `LS = LF = prev_end(C, y)`;
* a kept mandatory pin is never snapped; floats are working minutes;
* gap-end rule: a predecessor's backward bound through a not-pinned finish
  milestone is `next_work(C, LF)`, not `LF` (its own dates are unchanged).

Every value is synthetic.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Final

import pytest

from my_pa.domain.schedule.scenario.canonical import (
    CONTENT_SCHEMA,
    CONTENT_SCHEMA_V2,
    content_schema,
    content_sha256,
    result_sha256,
)
from my_pa.domain.schedule.scenario.cpm import (
    ENGINE_VERSION,
    ENGINE_VERSION_V2,
    CpmResult,
    CpmStatus,
    _run,
    engine_version_for,
    result_document,
    run_cpm,
)
from my_pa.domain.schedule.scenario.model import (
    ActivityKind,
    ActivityState,
    FixedLagCalendar,
    LagCalendar,
    ScenarioContent,
    format_instant,
)
from tests.fixtures.schedule_scenario import (
    C6,
    DAY,
    GOLDEN_NETWORKS,
    MFO,
    MSO,
    SNET,
    STD,
    at,
    link,
    milestone,
    network,
    task,
)

START: Final = ActivityKind.START_MILESTONE
FINISH: Final = ActivityKind.FINISH_MILESTONE

Row = tuple[str, str, str, str, int | None, int | None]


def _rows(result: CpmResult) -> dict[str, Row]:
    """key (without `x:`) -> (ES, EF, LS, LF, TF, FF) as `MM-DD HH:MM` text."""

    def text(minutes: int) -> str:
        return format_instant(minutes)[5:].replace("T", " ")

    return {
        item.key.removeprefix("x:"): (
            text(item.early_start),
            text(item.early_finish),
            text(item.late_start),
            text(item.late_finish),
            item.total_float_minutes,
            item.free_float_minutes,
        )
        for item in result.activities
    }


def _paths(result: CpmResult) -> list[list[str]]:
    return [[key.removeprefix("x:") for key in path] for path in result.critical_paths]


def _as_v1(content: ScenarioContent) -> ScenarioContent:
    """The same network with every edged milestone written as a v1 `milestone`."""
    return replace(
        content,
        activities=tuple(
            replace(activity, kind=ActivityKind.MILESTONE)
            if activity.kind in (START, FINISH)
            else activity
            for activity in content.activities
        ),
    )


# --- E3: new goldens -----------------------------------------------------------------------

#: E3 / section 11.7 example: a task finishing Monday 16:00 drives, by FS 0, a start
#: milestone at Tuesday 08:00 and a finish milestone at Monday 16:00.
MONDAY_1600: Final = network(
    [task("A", DAY), milestone("S", START), milestone("F", FINISH)],
    [link("A", "S"), link("A", "F")],
)
#: E3: both edges after FS+120 on `twenty_four_hour` (the lag ends Monday 18:00).
TWENTY_FOUR_HOUR_START: Final = network(
    [task("A", DAY), milestone("S", START)],
    [link("A", "S", "FS", 120)],
    lag_calendar=LagCalendar.TWENTY_FOUR_HOUR,
)
TWENTY_FOUR_HOUR_FINISH: Final = network(
    [task("A", DAY), milestone("F", FINISH)],
    [link("A", "F", "FS", 120)],
    lag_calendar=LagCalendar.TWENTY_FOUR_HOUR,
)
#: E3: A ends Friday 01-08 16:00; FS+480 on the fixed lag calendar `c6` (Mon-Sat)
#: ends Saturday 01-09 16:00 (on `std` it would end Monday 01-11 16:00).
FIXED_LAG_START: Final = network(
    [task("A", DAY, constraints=[(SNET, "01-08 00:00")]), milestone("S", START)],
    [link("A", "S", "FS", 480)],
    calendars=(STD, C6),
    lag_calendar=FixedLagCalendar("c6"),
)
FIXED_LAG_FINISH: Final = network(
    [task("A", DAY, constraints=[(SNET, "01-08 00:00")]), milestone("F", FINISH)],
    [link("A", "F", "FS", 480)],
    calendars=(STD, C6),
    lag_calendar=FixedLagCalendar("c6"),
)
#: E3: the data date (Monday 00:00) is a non-working instant and the only bound.
DATA_DATE_ONLY: Final = network([milestone("F", FINISH), milestone("S", START)])
#: E3: late dates of both kinds; X (3 days) sets the project finish 01-06 16:00.
LATE_DATES: Final = network(
    [task("A", DAY), milestone("S", START), milestone("F", FINISH), task("X", 3 * DAY)],
    [link("A", "S"), link("A", "F")],
)
#: E3: kept mandatory pins are applied unsnapped (16:00 would snap to Tuesday 08:00
#: for a start milestone; Tuesday 08:00 to Monday 16:00 for a finish milestone).
PINNED: Final = network(
    [
        milestone("S", START, constraints=[(MSO, "01-04 16:00")]),
        milestone("F", FINISH, constraints=[(MFO, "01-05 08:00")]),
    ]
)

V2_GOLDENS: Final[dict[str, ScenarioContent]] = {
    "monday_1600": MONDAY_1600,
    "twenty_four_hour_start": TWENTY_FOUR_HOUR_START,
    "twenty_four_hour_finish": TWENTY_FOUR_HOUR_FINISH,
    "fixed_lag_start": FIXED_LAG_START,
    "fixed_lag_finish": FIXED_LAG_FINISH,
    "data_date_only": DATA_DATE_ONLY,
    "late_dates": LATE_DATES,
    "pinned": PINNED,
}

#: vector -> ({activity: (ES, EF, LS, LF, TF, FF)}, critical paths, project finish).
V2_EXPECTED: Final[dict[str, tuple[dict[str, Row], list[list[str]], str]]] = {
    "monday_1600": (
        {
            "A": ("01-04 08:00", "01-04 16:00", "01-04 08:00", "01-04 16:00", 0, 0),
            "S": ("01-05 08:00", "01-05 08:00", "01-05 08:00", "01-05 08:00", 0, 0),
            "F": ("01-04 16:00", "01-04 16:00", "01-04 16:00", "01-04 16:00", 0, 0),
        },
        [["A", "F"], ["A", "S"]],
        "01-05 08:00",
    ),
    "twenty_four_hour_start": (
        {
            # The lag ends Monday 18:00; the start milestone is at Tuesday 08:00.
            "A": ("01-04 08:00", "01-04 16:00", "01-04 08:00", "01-04 16:00", 0, 0),
            "S": ("01-05 08:00", "01-05 08:00", "01-05 08:00", "01-05 08:00", 0, 0),
        },
        [["A", "S"]],
        "01-05 08:00",
    ),
    "twenty_four_hour_finish": (
        {
            # The finish milestone is at the end of Monday's work (16:00). Gap-end rule:
            # A's bound is next_work(Mon 16:00) = Tue 08:00 less 120 clock minutes =
            # Tue 06:00, whose previous std working end is Mon 16:00: TF 0 (S7-0 review
            # F1; it read Fri 14:00 / Mon 14:00, -120, before the rule).
            "A": ("01-04 08:00", "01-04 16:00", "01-04 08:00", "01-04 16:00", 0, 0),
            "F": ("01-04 16:00", "01-04 16:00", "01-04 16:00", "01-04 16:00", 0, 0),
        },
        [["A", "F"]],
        "01-04 16:00",
    ),
    "fixed_lag_start": (
        {
            "A": ("01-08 08:00", "01-08 16:00", "01-08 08:00", "01-08 16:00", 0, 0),
            "S": ("01-11 08:00", "01-11 08:00", "01-11 08:00", "01-11 08:00", 0, 0),
        },
        [["A", "S"]],
        "01-11 08:00",
    ),
    "fixed_lag_finish": (
        {
            # The lag ends Saturday 16:00 on c6; on std the previous working end is
            # Friday 16:00. Backward (gap-end rule), next_work(std, Fri 16:00) = Mon
            # 01-11 08:00; retreat(c6, Mon 08:00, 480) = Sat 08:00, whose previous std
            # working end is Friday 16:00: TF 0 (it read Thu, -480, before the rule).
            "A": ("01-08 08:00", "01-08 16:00", "01-08 08:00", "01-08 16:00", 0, 0),
            "F": ("01-08 16:00", "01-08 16:00", "01-08 16:00", "01-08 16:00", 0, 0),
        },
        [["A", "F"]],
        "01-08 16:00",
    ),
    "data_date_only": (
        {
            # prev_end(Mon 00:00) is Friday 16:00, before D: the data date itself.
            "F": ("01-04 00:00", "01-04 00:00", "01-01 16:00", "01-01 16:00", 0, 0),
            "S": ("01-04 08:00", "01-04 08:00", "01-04 08:00", "01-04 08:00", 0, 0),
        },
        [["F"], ["S"]],
        "01-04 08:00",
    ),
    "late_dates": (
        {
            "A": ("01-04 08:00", "01-04 16:00", "01-06 08:00", "01-06 16:00", 960, 0),
            "S": ("01-05 08:00", "01-05 08:00", "01-07 08:00", "01-07 08:00", 960, 960),
            "F": ("01-04 16:00", "01-04 16:00", "01-06 16:00", "01-06 16:00", 960, 960),
            "X": ("01-04 08:00", "01-06 16:00", "01-04 08:00", "01-06 16:00", 0, 0),
        },
        [["X"]],
        "01-06 16:00",
    ),
    "pinned": (
        {
            "S": ("01-04 16:00", "01-04 16:00", "01-04 16:00", "01-04 16:00", 0, 0),
            "F": ("01-05 08:00", "01-05 08:00", "01-05 08:00", "01-05 08:00", 0, 0),
        },
        [["F"], ["S"]],
        "01-05 08:00",
    ),
}

#: Each v2 golden's frozen `result_sha256` (a change needs an engine version bump).
V2_RESULT_SHA256: Final[dict[str, str]] = {
    "data_date_only": "c2a444680b3e4a0b374c9963b5094784c2fb14a3920288af4b67699826c2417c",
    "fixed_lag_finish": "59a4502d1f9dbac400f6486bbe373ad1e228a55ba535e73d16051a087bae5ca9",
    "fixed_lag_start": "4b681eb8ec7fcd5726f513691335d8970f5dc98f3000b29c10f1cd4f6c897ad4",
    "late_dates": "95654fbdf3211ca1eb5b04e1d68b3cacc67f2ee0ec18dc6cc3c8fa7a381aeb86",
    "monday_1600": "6c446699d8824718b53fe2b89e30993a97c40b6aefcce5682797cde7d2f947dd",
    "pinned": "42110028beb65fec966bd3f603d4bb2d2c6220221a92a01f7c40ee89206f097a",
    "twenty_four_hour_finish": "42fb51037bdcf48b878ecbdc9a134541262793589eb0d706c85f8454ac9b2baa",
    "twenty_four_hour_start": "923dd865ca8ce4fccdc4d0f512bc3013677fc62de960331658e0b50f33d0940a",
}


def test_every_v2_golden_is_expected() -> None:
    assert sorted(V2_EXPECTED) == sorted(V2_GOLDENS)
    for vector, content in V2_GOLDENS.items():
        assert content_schema(content) == CONTENT_SCHEMA_V2, vector


@pytest.mark.parametrize("vector", sorted(V2_GOLDENS))
def test_v2_golden_network_matches(vector: str) -> None:
    rows, paths, finish = V2_EXPECTED[vector]
    result = run_cpm(V2_GOLDENS[vector])
    assert result.status is CpmStatus.COMPUTED
    assert result.engine_version == ENGINE_VERSION_V2
    assert _rows(result) == rows
    assert _paths(result) == paths
    assert format_instant(result.summary.project_finish or 0)[5:].replace("T", " ") == finish


def test_start_milestone_snaps_to_the_next_working_start() -> None:
    """E3 / section 11.7 example, read directly: Tuesday 08:00, never Monday 16:00."""
    by_key = {item.key: item for item in run_cpm(MONDAY_1600).activities}
    assert by_key["x:S"].early_start == by_key["x:S"].early_finish == at("01-05 08:00")
    assert by_key["x:S"].late_start == by_key["x:S"].late_finish == at("01-05 08:00")
    # Under v1 the same network (both as `milestone`) reads Monday 16:00 for both.
    v1 = {item.key: item for item in run_cpm(_as_v1(MONDAY_1600)).activities}
    assert v1["x:S"].early_start == v1["x:F"].early_start == at("01-04 16:00")


def test_finish_milestone_stays_at_the_previous_working_end() -> None:
    by_key = {item.key: item for item in run_cpm(MONDAY_1600).activities}
    assert by_key["x:F"].early_start == by_key["x:F"].early_finish == at("01-04 16:00")
    lagged = {item.key: item for item in run_cpm(TWENTY_FOUR_HOUR_FINISH).activities}
    # The lag ends Monday 18:00 (non-working); the finish milestone is the end of Monday.
    assert lagged["x:F"].early_finish == at("01-04 16:00")


def test_finish_milestone_bound_only_by_the_data_date_is_the_data_date() -> None:
    by_key = {item.key: item for item in run_cpm(DATA_DATE_ONLY).activities}
    assert by_key["x:F"].early_start == by_key["x:F"].early_finish == at("01-04 00:00")


def test_pinned_milestones_are_never_snapped() -> None:
    by_key = {item.key: item for item in run_cpm(PINNED).activities}
    for name, when in (("x:S", "01-04 16:00"), ("x:F", "01-05 08:00")):
        item = by_key[name]
        assert (item.early_start, item.early_finish, item.late_start, item.late_finish) == (
            at(when),
        ) * 4, name


@pytest.mark.parametrize("vector", ["monday_1600", "late_dates", "data_date_only", "pinned"])
def test_v2_floats_equal_the_unsnapped_working_minutes(vector: str) -> None:
    """Section 11.7: snapping crosses only non-working time, so TF and FF are the v1 ones.

    Only for networks whose lags are on the activities' own calendar: on
    `twenty_four_hour` or a fixed lag calendar the wall-clock date matters.
    """
    content = V2_GOLDENS[vector]
    v2 = {item.key: item for item in run_cpm(content).activities}
    v1 = {item.key: item for item in run_cpm(_as_v1(content)).activities}
    assert set(v1) == set(v2)
    for name, item in v2.items():
        assert (item.total_float_minutes, item.free_float_minutes) == (
            v1[name].total_float_minutes,
            v1[name].free_float_minutes,
        ), name


def test_gap_end_rule_gives_the_finish_milestone_predecessor_no_negative_float() -> None:
    """Section 11.7 gap-end rule (S7-0 review F1): F's late date stays Monday 16:00,
    but A's backward bound through it is next_work(Mon 16:00) = Tuesday 08:00."""
    by_key = {item.key: item for item in run_cpm(TWENTY_FOUR_HOUR_FINISH).activities}
    assert by_key["x:F"].late_finish == at("01-04 16:00")
    assert by_key["x:A"].late_finish == at("01-04 16:00")
    assert by_key["x:A"].total_float_minutes == 0


def test_a_start_milestone_needs_no_gap_end_rule() -> None:
    """The symmetric case: a start milestone only snaps later (to the next working
    start) on both passes, so its late date is never before the anchor its predecessor
    drives; lags on `twenty_four_hour` both sides leave every float non-negative."""
    content = network(
        [task("A", DAY), milestone("S", START), task("B", DAY)],
        [link("A", "S", "FS", 120), link("S", "B", "FS", 120)],
        lag_calendar=LagCalendar.TWENTY_FOUR_HOUR,
    )
    rows = _rows(run_cpm(content))
    assert rows == {
        # A ends Mon 16:00; +120 = Mon 18:00 -> S at Tue 08:00; +120 = Tue 10:00.
        "A": ("01-04 08:00", "01-04 16:00", "01-04 08:00", "01-04 16:00", 0, 0),
        "S": ("01-05 08:00", "01-05 08:00", "01-05 08:00", "01-05 08:00", 0, 0),
        "B": ("01-05 10:00", "01-06 10:00", "01-05 10:00", "01-06 10:00", 0, 0),
    }


def test_edged_milestone_with_progress_is_complete_at_its_date() -> None:
    content = network(
        [
            milestone("S", START, started="01-04 08:00"),
            milestone("F", FINISH, started="01-05 16:00", finished="01-05 16:00"),
            task("B", DAY),
        ],
        [link("S", "B"), link("F", "B")],
        data_date="01-06 00:00",
    )
    result = run_cpm(content)
    by_key = {item.key: item for item in result.activities}
    assert by_key["x:S"].state is ActivityState.COMPLETE
    assert (by_key["x:S"].early_start, by_key["x:S"].early_finish) == (at("01-04 08:00"),) * 2
    assert by_key["x:F"].state is ActivityState.COMPLETE
    assert (by_key["x:F"].early_start, by_key["x:F"].early_finish) == (at("01-05 16:00"),) * 2
    assert by_key["x:B"].early_start == at("01-06 08:00")


@pytest.mark.parametrize("vector", sorted(V2_GOLDENS))
def test_v2_golden_result_sha256_is_stable(vector: str) -> None:
    document = result_document(run_cpm(V2_GOLDENS[vector]))
    assert document["engine_version"] == "my-pa-cpm-v2"
    assert document["input_content_sha256"] == content_sha256(V2_GOLDENS[vector])
    assert result_sha256(document) == V2_RESULT_SHA256[vector]


# --- E1 / E2: v1 is untouched; v2 over a v1 network gives the same activity results ----------


@pytest.mark.parametrize("vector", sorted(GOLDEN_NETWORKS))
def test_v1_goldens_run_on_the_v1_path(vector: str) -> None:
    """E1: every S6 golden is a v1 content and runs on `my-pa-cpm-v1`."""
    content = GOLDEN_NETWORKS[vector]
    assert content_schema(content) == CONTENT_SCHEMA
    assert engine_version_for(content) == ENGINE_VERSION
    assert run_cpm(content).engine_version == ENGINE_VERSION


@pytest.mark.parametrize("vector", sorted(GOLDEN_NETWORKS))
def test_v2_path_on_every_v1_golden_matches_v1(vector: str) -> None:
    """E2: the v2 path over a v1 golden (milestones, no fixed lag calendar) differs only
    in `engine_version`; operations, issues and every activity result are equal."""
    content = GOLDEN_NETWORKS[vector]
    v1 = run_cpm(content)
    v2 = _run(content, ENGINE_VERSION_V2, 4_000_000)
    assert v2.engine_version == ENGINE_VERSION_V2
    one, two = result_document(v1), result_document(v2)
    assert two.pop("engine_version") == ENGINE_VERSION_V2
    assert one.pop("engine_version") == ENGINE_VERSION
    assert one == two
    assert v1.operations == v2.operations


def test_a_v2_content_never_runs_on_the_v1_path() -> None:
    with pytest.raises(ValueError, match="never runs on my-pa-cpm-v1"):
        _run(MONDAY_1600, ENGINE_VERSION, 4_000_000)
    with pytest.raises(ValueError, match="engine version"):
        _run(MONDAY_1600, "my-pa-cpm-v3", 4_000_000)


# --- E8 (domain): the engine follows the content schema -------------------------------------


def test_the_engine_follows_the_content_schema() -> None:
    """E8: a v1 content runs as `my-pa-cpm-v1`, the same network with one edged
    milestone as `my-pa-cpm-v2`; a rejected v2 run still names v2."""
    v1 = network([task("A", DAY), milestone("M")], [link("A", "M")])
    v2 = network([task("A", DAY), milestone("M", FINISH)], [link("A", "M")])
    assert result_document(run_cpm(v1))["engine_version"] == "my-pa-cpm-v1"
    assert result_document(run_cpm(v2))["engine_version"] == "my-pa-cpm-v2"
    rejected = network([task("A", None), milestone("M", START)])
    result = run_cpm(rejected)
    assert result.status is CpmStatus.REJECTED
    assert result.engine_version == ENGINE_VERSION_V2
    fixed = network([task("A", DAY)], calendars=(STD, C6), lag_calendar=FixedLagCalendar("c6"))
    assert run_cpm(fixed).engine_version == ENGINE_VERSION_V2


def test_operation_budget_counts_each_snap() -> None:
    """Each edge snap is one counted calendar call: 1 forward + 1 backward per milestone,
    plus 1 gap-end call for the finish milestone F, which has a predecessor."""
    v2 = run_cpm(MONDAY_1600)
    v1 = run_cpm(_as_v1(MONDAY_1600))
    assert v2.operations == v1.operations + 5
    assert run_cpm(MONDAY_1600, operation_budget=v2.operations).status is CpmStatus.COMPUTED
    assert run_cpm(MONDAY_1600, operation_budget=v2.operations - 1).status is CpmStatus.REJECTED
