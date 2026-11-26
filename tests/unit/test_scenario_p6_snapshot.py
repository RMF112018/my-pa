"""P6 XER S7-4b: the P6 scenario snapshot mapping, row for row (acceptance D6).

Contract `docs/architecture/schedule-xer-import-contract.md` section 11.5 (the
mapping table), 11.6 (the standard calendar) and 11.7 (edged milestones, the
fixed lag calendar, content v1/v2). Every case is one base and one edit, so a
red test names the mapping row it guards. Every value is synthetic.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

import pytest

from my_pa.domain.schedule.model import ScheduleCellState
from my_pa.domain.schedule.scenario.canonical import (
    CONTENT_SCHEMA,
    CONTENT_SCHEMA_V2,
    CONTENT_SCHEMA_V3,
    content_bytes,
    content_from_object,
    content_object,
    content_schema,
)
from my_pa.domain.schedule.scenario.cpm import CpmStatus, run_cpm
from my_pa.domain.schedule.scenario.model import (
    ActivityKind,
    ConstraintType,
    FixedLagCalendar,
    LagCalendar,
    ProgressPolicy,
    RelationshipType,
    format_instant,
)
from my_pa.domain.schedule.scenario.p6_snapshot import (
    REPORT_COUNTS,
    P6Snapshot,
    P6SnapshotActivity,
    P6SnapshotCalendar,
    P6SnapshotProject,
    P6SnapshotRefusal,
    P6SnapshotRefusalError,
    P6SnapshotRelationship,
    P6SnapshotRequest,
    snapshot_from_p6,
)
from my_pa.domain.schedule.scenario.standard_calendar import STANDARD_CALENDAR_KEY

PUBLICATION: Final = "spub_p6snapshot01"
WORKDAY: Final = ((480, 720), (780, 1020))
WEEK: Final = (WORKDAY,) * 5 + ((), ())


def cal(p6_id: int = 501, **changes: Any) -> P6SnapshotCalendar:  # noqa: ANN401
    base = P6SnapshotCalendar(p6_calendar_id=p6_id, week=WEEK, exceptions=((date(2030, 1, 1), ()),))
    return dataclasses.replace(base, **changes)


def act(code: str, number: int, task_type: str = "TT_Task", **changes: Any) -> P6SnapshotActivity:  # noqa: ANN401
    base = P6SnapshotActivity(
        schedule_activity_id=f"sact_p6snap{number:04d}",
        activity_id=code,
        name=f"Synthetic {code}",
        task_type=task_type,
        status="TK_NotStart",
        wbs_path=("Synthetic Area",),
        p6_calendar_id=501,
        original_hours=Decimal("0") if task_type in {"TT_Mile", "TT_FinMile"} else Decimal("40"),
        remaining_hours=Decimal("0") if task_type in {"TT_Mile", "TT_FinMile"} else Decimal("40"),
        start=datetime(2030, 1, 7, 8, 0),
        finish=datetime(2030, 1, 11, 17, 0),
        late_finish=datetime(2030, 1, 11, 17, 0),
    )
    return dataclasses.replace(base, **changes)


def rel(
    pred: str, succ: str, kind: str = "PR_FS", lag: str = "0", *, external: bool = False
) -> P6SnapshotRelationship:
    return P6SnapshotRelationship(pred, None if external else succ, kind, Decimal(lag), external)


PROJECT: Final = P6SnapshotProject(
    data_date=datetime(2030, 1, 7, 8, 0),
    default_p6_calendar_id=501,
    lag_calendar="rcal_Predecessor",
    retained_logic=True,
    progress_override=False,
    must_finish_by=None,
    critical_float_hours=Decimal("0"),
)


def snap(
    *,
    project: P6SnapshotProject = PROJECT,
    calendars: tuple[P6SnapshotCalendar, ...] = (cal(),),
    activities: tuple[P6SnapshotActivity, ...] = (act("SYN-1010", 2), act("SYN-1020", 3)),
    relationships: tuple[P6SnapshotRelationship, ...] = (rel("SYN-1010", "SYN-1020"),),
    request: P6SnapshotRequest | None = None,
) -> P6Snapshot:
    return snapshot_from_p6(
        publication_id=PUBLICATION,
        project=project,
        calendars=calendars,
        activities=activities,
        relationships=relationships,
        request=request,
    )


def refused(**kwargs: Any) -> P6SnapshotRefusal:  # noqa: ANN401
    with pytest.raises(P6SnapshotRefusalError) as caught:
        snap(**kwargs)
    return caught.value.reason


def counts(snapshot: P6Snapshot) -> dict[str, int]:
    return dict(snapshot.p6_report.counts)


def by_code(snapshot: P6Snapshot) -> dict[str, Any]:
    return {
        a.published_reference.published_activity_id: a  # type: ignore[union-attr]
        for a in snapshot.content.activities
    }


# ---- data date, calendars, settings ---------------------------------------------------


def test_a_plain_task_network_is_a_byte_identical_v1_content_and_runs() -> None:
    built = snap()
    content = built.content
    assert format_instant(content.data_date) == "2030-01-07T08:00"
    assert content_schema(content) == CONTENT_SCHEMA
    assert content_from_object(content_object(content)) == content
    assert b'"fields"' not in content_bytes(content)
    assert [c.key for c in content.calendars] == ["p6-501"]
    assert content.settings.default_calendar == "p6-501"
    assert content.settings.lag_calendar is LagCalendar.PREDECESSOR
    assert content.settings.progress_policy is ProgressPolicy.RETAINED_LOGIC
    assert tuple(built.p6_report.counts) == REPORT_COUNTS
    assert counts(built)["tasks"] == 2
    assert counts(built)["relationships"] == 1
    assert run_cpm(content).status is CpmStatus.COMPUTED


def test_calendar_week_minutes_and_exception_window() -> None:
    calendar = cal(
        exceptions=(
            (date(1999, 12, 31), ()),
            (date(2030, 1, 1), ()),
            (date(2030, 1, 12), ((480, 720),)),
        )
    )
    built = snap(calendars=(calendar,))
    (stored,) = built.content.calendars
    assert stored.week[0] == WORKDAY
    assert stored.week[5:] == ((), ())
    assert [item.day for item in stored.exceptions] == [date(2030, 1, 1), date(2030, 1, 12)]
    assert counts(built)["exceptions_out_of_range"] == 1
    # Independent review S7-4b: both window ends are inclusive, the day after is out.
    edges = snap(
        calendars=(
            cal(
                exceptions=(
                    (date(2000, 1, 1), ()),
                    (date(2099, 12, 31), ()),
                    (date(2100, 1, 1), ()),
                )
            ),
        )
    )
    (edged,) = edges.content.calendars
    assert [item.day for item in edged.exceptions] == [date(2000, 1, 1), date(2099, 12, 31)]
    assert counts(edges)["exceptions_out_of_range"] == 1


def test_default_every_used_calendar_and_no_unused_one() -> None:
    built = snap(
        calendars=(cal(501), cal(502), cal(503)),
        activities=(act("SYN-1010", 2), act("SYN-1020", 3, p6_calendar_id=502)),
    )
    assert [c.key for c in built.content.calendars] == ["p6-501", "p6-502"]


def test_more_than_4_intervals_a_day_is_refused() -> None:
    five = tuple((start, start + 30) for start in range(480, 780, 60))
    assert refused(calendars=(cal(week=(five,) * 5 + ((), ())),)) is P6SnapshotRefusal.CALENDAR
    exception = cal(exceptions=((date(2030, 1, 2), five),))
    assert refused(calendars=(exception,)) is P6SnapshotRefusal.CALENDAR


def test_at_most_32_calendars() -> None:
    def network(n: int) -> dict[str, Any]:
        return {
            "calendars": tuple(cal(600 + i) for i in range(n)),
            "activities": tuple(
                act(f"SYN-{2000 + i}", 100 + i, p6_calendar_id=600 + i) for i in range(n)
            ),
            "relationships": (),
            "project": dataclasses.replace(PROJECT, default_p6_calendar_id=600),
        }

    assert len(snap(**network(32)).content.calendars) == 32
    assert refused(**network(33)) is P6SnapshotRefusal.CALENDAR


def test_default_calendar_rule() -> None:
    # The request's, if given (and available).
    chosen = snap(
        calendars=(cal(501), cal(502)),
        request=P6SnapshotRequest(default_calendar="p6-502"),
    )
    assert chosen.content.settings.default_calendar == "p6-502"
    assert counts(chosen)["default_calendar_standard"] == 0
    assert (
        refused(request=P6SnapshotRequest(default_calendar="p6-999")) is P6SnapshotRefusal.CALENDAR
    )
    # Else the project default when it exists and parses.
    assert snap().content.settings.default_calendar == "p6-501"
    # Else the MY-PA standard calendar, counted.
    for project in (
        dataclasses.replace(PROJECT, default_p6_calendar_id=None),
        dataclasses.replace(PROJECT, default_p6_calendar_id=999),
    ):
        fallback = snap(project=project)
        assert fallback.content.settings.default_calendar == STANDARD_CALENDAR_KEY
        assert counts(fallback)["default_calendar_standard"] == 1
    unparseable = snap(
        calendars=(cal(501), cal(502, week=())),
        project=dataclasses.replace(PROJECT, default_p6_calendar_id=502),
    )
    assert unparseable.content.settings.default_calendar == STANDARD_CALENDAR_KEY


def test_activity_calendar_remap_and_the_missing_calendar_default() -> None:
    built = snap(
        activities=(
            act("SYN-1010", 2, p6_calendar_id=777),
            act("SYN-1020", 3, p6_calendar_id=None),
        ),
    )
    acts = by_code(built)
    assert acts["SYN-1010"].calendar == STANDARD_CALENDAR_KEY
    assert acts["SYN-1020"].calendar == STANDARD_CALENDAR_KEY
    assert counts(built)["calendars_defaulted"] == 2
    remapped = snap(
        calendars=(cal(501), cal(502)),
        request=P6SnapshotRequest(calendar_map={"p6-501": "p6-502"}),
    )
    assert {a.calendar for a in remapped.content.activities} == {"p6-502"}
    assert refused(request=P6SnapshotRequest(calendar_map={"p6-501": "p6-999"})) is (
        P6SnapshotRefusal.CALENDAR
    )


def test_a_request_calendar_adds_or_substitutes() -> None:
    other_week = (((420, 900),),) * 5 + ((), ())
    substitute = cal(501, week=other_week)
    built = snap(request=P6SnapshotRequest(calendars=(substitute,)))
    (stored,) = built.content.calendars
    assert stored.key == "p6-501"
    assert stored.week[0] == ((420, 900),)
    added = snap(request=P6SnapshotRequest(calendars=(cal(900),), default_calendar="p6-900"))
    assert [c.key for c in added.content.calendars] == ["p6-501", "p6-900"]
    assert added.content.settings.default_calendar == "p6-900"
    twice = P6SnapshotRequest(calendars=(cal(900), cal(900)))
    assert refused(request=twice) is P6SnapshotRefusal.CALENDAR


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("rcal_Predecessor", LagCalendar.PREDECESSOR),
        ("rcal_Successor", LagCalendar.SUCCESSOR),
        ("rcal_24Hour", LagCalendar.TWENTY_FOUR_HOUR),
        (None, LagCalendar.PREDECESSOR),
    ],
)
def test_lag_calendar_mapping(token: str | None, expected: LagCalendar) -> None:
    built = snap(project=dataclasses.replace(PROJECT, lag_calendar=token))
    assert built.content.settings.lag_calendar is expected


def test_rcal_project_is_the_project_default_as_a_fixed_lag_calendar_and_v2() -> None:
    built = snap(project=dataclasses.replace(PROJECT, lag_calendar="rcal_Project"))
    assert built.content.settings.lag_calendar == FixedLagCalendar("p6-501")
    assert content_schema(built.content) == CONTENT_SCHEMA_V2
    assert counts(built)["lag_calendar_standard"] == 0
    # The request's default does not move it: rcal_Project is the project's own calendar.
    chosen = snap(
        project=dataclasses.replace(PROJECT, lag_calendar="rcal_Project"),
        calendars=(cal(501), cal(502)),
        request=P6SnapshotRequest(default_calendar="p6-502"),
    )
    assert chosen.content.settings.lag_calendar == FixedLagCalendar("p6-501")
    standard = snap(
        project=dataclasses.replace(
            PROJECT, lag_calendar="rcal_Project", default_p6_calendar_id=None
        )
    )
    assert standard.content.settings.lag_calendar == FixedLagCalendar(STANDARD_CALENDAR_KEY)
    assert counts(standard)["lag_calendar_standard"] == 1
    assert run_cpm(built.content).status is CpmStatus.COMPUTED


@pytest.mark.parametrize(
    ("override", "retained", "expected", "defaulted"),
    [
        (True, False, ProgressPolicy.PROGRESS_OVERRIDE, 0),
        (False, True, ProgressPolicy.RETAINED_LOGIC, 0),
        (False, False, ProgressPolicy.RETAINED_LOGIC, 1),
        (None, None, ProgressPolicy.RETAINED_LOGIC, 1),
    ],
)
def test_progress_policy_mapping_and_its_default(
    override: bool | None, retained: bool | None, expected: ProgressPolicy, defaulted: int
) -> None:
    built = snap(
        project=dataclasses.replace(PROJECT, progress_override=override, retained_logic=retained)
    )
    assert built.content.settings.progress_policy is expected
    assert counts(built)["progress_policy_defaulted"] == defaulted


def test_must_finish_by_and_the_critical_threshold() -> None:
    built = snap(
        project=dataclasses.replace(
            PROJECT, must_finish_by=datetime(2030, 2, 1, 17, 0), critical_float_hours=Decimal("8")
        )
    )
    assert format_instant(built.content.settings.must_finish_by or 0) == "2030-02-01T17:00"
    assert built.content.settings.critical_float_threshold_minutes == 480


# ---- activities, durations, constraints, progress --------------------------------------


def test_activity_kinds_are_faithful_and_loe_and_wbs_are_excluded() -> None:
    built = snap(
        activities=(
            act("SYN-1000", 1, "TT_Mile"),
            act("SYN-1010", 2),
            act("SYN-1015", 5, "TT_Rsrc"),
            act("SYN-1020", 3, "TT_LOE"),
            act("SYN-1025", 6, "TT_WBS"),
            act("SYN-1030", 4, "TT_FinMile"),
        ),
        relationships=(
            rel("SYN-1000", "SYN-1010"),
            rel("SYN-1010", "SYN-1020"),
            rel("SYN-1010", "SYN-1030"),
        ),
    )
    kinds = {code: a.kind for code, a in by_code(built).items()}
    assert kinds == {
        "SYN-1000": ActivityKind.START_MILESTONE,
        "SYN-1010": ActivityKind.TASK,
        "SYN-1015": ActivityKind.TASK,
        "SYN-1030": ActivityKind.FINISH_MILESTONE,
    }
    c = counts(built)
    assert (c["loe_excluded"], c["wbs_summary_excluded"], c["resource_dependent_tasks"]) == (
        1,
        1,
        1,
    )
    assert (c["start_milestones"], c["finish_milestones"]) == (1, 1)
    # The LOE's relationship is excluded with it, counted.
    assert c["relationships_excluded"] == 1
    assert len(built.content.relationships) == 2
    assert built.report.milestones == 2
    assert content_schema(built.content) == CONTENT_SCHEMA_V2


def test_durations_round_half_even_and_are_counted() -> None:
    built = snap(
        activities=(
            act("SYN-1010", 2, original_hours=Decimal("0.0125"), remaining_hours=Decimal("0.0375")),
            act("SYN-1020", 3, original_hours=None, remaining_hours=Decimal("100000")),
        ),
    )
    acts = by_code(built)
    # 0.75 minutes -> 1 (half-even of 0.75 is 1); 2.25 -> 2.
    assert (acts["SYN-1010"].original_minutes, acts["SYN-1010"].remaining_minutes) == (1, 2)
    tie = snap(
        activities=(
            act(
                "SYN-1010",
                2,
                original_hours=Decimal("0.075"),
                remaining_hours=Decimal("0.175"),
            ),
        ),
        relationships=(),
    )
    # Exactly 4.5 and 10.5 minutes: half-even gives 4 and 10 (half-up would give 5 and 11).
    assert (
        by_code(tie)["SYN-1010"].original_minutes,
        by_code(tie)["SYN-1010"].remaining_minutes,
    ) == (4, 10)
    c = counts(built)
    assert c["durations_quantized"] == 2
    assert (c["original_missing"], c["durations_out_of_range"]) == (1, 1)
    assert acts["SYN-1020"].original_minutes is None
    assert acts["SYN-1020"].remaining_minutes is None
    assert built.report.durations_quantized == 2


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("CS_MSOA", ConstraintType.SNET),
        ("CS_MEOA", ConstraintType.FNET),
        ("CS_MSOB", ConstraintType.SNLT),
        ("CS_MEOB", ConstraintType.FNLT),
        ("CS_MANDSTART", ConstraintType.MSO),
        ("CS_MANDFIN", ConstraintType.MFO),
    ],
)
def test_constraint_mapping(token: str, expected: ConstraintType) -> None:
    at = datetime(2030, 1, 8, 8, 0)
    built = snap(activities=(act("SYN-1010", 2, constraint=(token, at)), act("SYN-1020", 3)))
    (constraint,) = by_code(built)["SYN-1010"].constraints
    assert constraint.type is expected
    assert format_instant(constraint.at) == "2030-01-08T08:00"


@pytest.mark.parametrize("token", ["CS_MSO", "CS_MEO", "CS_ALAP"])
def test_unrepresentable_constraints_are_dropped_and_counted(token: str) -> None:
    built = snap(
        activities=(
            act("SYN-1010", 2, constraint=(token, datetime(2030, 1, 8, 8, 0))),
            act("SYN-1020", 3),
        )
    )
    assert by_code(built)["SYN-1010"].constraints == ()
    assert counts(built)["constraints_unsupported"] == 1


def test_a_pair_the_slot_rule_refuses_keeps_the_primary() -> None:
    at = datetime(2030, 1, 8, 8, 0)
    built = snap(
        activities=(
            act("SYN-1010", 2, constraint=("CS_MANDSTART", at), constraint2=("CS_MSOB", at)),
            act("SYN-1020", 3, constraint=("CS_MSOA", at), constraint2=("CS_MEOB", at)),
        )
    )
    acts = by_code(built)
    assert [c.type for c in acts["SYN-1010"].constraints] == [ConstraintType.MSO]
    assert [c.type for c in acts["SYN-1020"].constraints] == [
        ConstraintType.SNET,
        ConstraintType.FNLT,
    ]
    assert counts(built)["constraints_dropped"] == 1


def test_milestone_constraints_move_to_the_milestones_own_side() -> None:
    at = datetime(2030, 1, 8, 8, 0)
    built = snap(
        activities=(
            act("SYN-1000", 1, "TT_Mile", constraint=("CS_MEOA", at)),
            act("SYN-1001", 7, "TT_Mile", constraint=("CS_MANDFIN", at)),
            act("SYN-1030", 4, "TT_FinMile", constraint=("CS_MSOB", at)),
            act("SYN-1031", 8, "TT_FinMile", constraint=("CS_MEOB", at)),
        ),
        relationships=(),
    )
    acts = by_code(built)
    assert [c.type for c in acts["SYN-1000"].constraints] == [ConstraintType.SNET]
    assert [c.type for c in acts["SYN-1001"].constraints] == [ConstraintType.MSO]
    assert [c.type for c in acts["SYN-1030"].constraints] == [ConstraintType.FNLT]
    assert [c.type for c in acts["SYN-1031"].constraints] == [ConstraintType.FNLT]
    assert counts(built)["milestone_constraints_converted"] == 3
    # The date is unchanged: nothing is lost.
    assert format_instant(acts["SYN-1000"].constraints[0].at) == "2030-01-08T08:00"


def test_progress_and_actual_dates() -> None:
    start, finish = datetime(2030, 1, 6, 8, 0), datetime(2030, 1, 7, 8, 0)
    built = snap(
        activities=(
            act("SYN-1000", 1, "TT_Mile", status="TK_Complete", actual_start=start),
            act(
                "SYN-1010", 2, status="TK_Active", actual_start=start, remaining_hours=Decimal("8")
            ),
            act(
                "SYN-1020",
                3,
                status="TK_Complete",
                actual_start=start,
                actual_finish=finish,
                remaining_hours=Decimal("0"),
            ),
            act("SYN-1030", 4, "TT_FinMile", status="TK_Complete", actual_finish=finish),
        ),
        relationships=(),
    )
    acts = by_code(built)
    mile = acts["SYN-1000"].progress
    assert (mile.actual_start, mile.actual_finish) == (mile.actual_start, mile.actual_start)
    assert acts["SYN-1010"].progress.actual_finish is None
    assert acts["SYN-1020"].progress.actual_finish is not None
    fin = acts["SYN-1030"].progress
    assert format_instant(fin.actual_finish) == "2030-01-07T08:00"
    assert fin.actual_start == fin.actual_finish


def test_complete_without_the_needed_actual_date_is_refused() -> None:
    for activity in (
        act("SYN-1010", 2, status="TK_Complete", actual_start=datetime(2030, 1, 6, 8, 0)),
        act("SYN-1000", 1, "TT_Mile", status="TK_Complete"),
        act(
            "SYN-1030",
            4,
            "TT_FinMile",
            status="TK_Complete",
            actual_start=datetime(2030, 1, 6, 8, 0),
        ),
    ):
        assert refused(activities=(activity,), relationships=()) is P6SnapshotRefusal.ROWS


def test_relationships_lags_and_external_ones() -> None:
    built = snap(
        activities=(act("SYN-1010", 2), act("SYN-1020", 3), act("SYN-1030", 4)),
        relationships=(
            rel("SYN-1010", "SYN-1020", "PR_SS", "4.5"),
            rel("SYN-1020", "SYN-1030", "PR_FF", "-8"),
            rel("SYN-1010", "SYN-1030", "PR_SF", "0.01"),
            rel("SYN-1030", "", external=True),
        ),
    )
    found = {(r.type, r.lag_minutes) for r in built.content.relationships}
    assert found == {
        (RelationshipType.SS, 270),
        (RelationshipType.FF, -480),
        (RelationshipType.SF, 1),
    }
    c = counts(built)
    assert c["external_relationships_dropped"] == 1
    assert c["lags_quantized"] == 1


def test_parallel_relationships_are_all_kept_and_make_the_content_v3() -> None:
    # S7-7: P6 allows an SS and an FF between the same 2 activities; the content keeps
    # both (one per (pred, succ, type)), so nothing is counted parallel-dropped, and
    # the external and unknown-endpoint exclusions are counted as before.
    built = snap(
        activities=(act("SYN-1010", 2), act("SYN-1020", 3)),
        relationships=(
            rel("SYN-1010", "SYN-1020", "PR_SS", "8"),
            rel("SYN-1010", "SYN-1020", "PR_FF", "0"),
            rel("SYN-1020", "SYN-1010", "PR_FS", "0"),
            rel("SYN-1010", "SYN-9999"),
        ),
    )
    links = {(r.pred, r.succ, r.type) for r in built.content.relationships}
    assert links == {
        ("sact_p6snap0002", "sact_p6snap0003", RelationshipType.SS),
        ("sact_p6snap0002", "sact_p6snap0003", RelationshipType.FF),
        ("sact_p6snap0003", "sact_p6snap0002", RelationshipType.FS),
    }
    assert content_schema(built.content) == CONTENT_SCHEMA_V3
    c = counts(built)
    assert c["relationships"] == 3
    assert c["relationships_parallel_dropped"] == 0
    assert c["relationships_excluded"] == 1
    assert c["external_relationships_dropped"] == 0


def test_either_file_order_of_a_ladder_gives_the_same_content() -> None:
    # S7-7: before, the first of the two rows survived, so the export's row order chose
    # the network. Now both file orders give one content (bytes and digest).
    ladder = (
        rel("SYN-1010", "SYN-1020", "PR_SS", "8"),
        rel("SYN-1010", "SYN-1020", "PR_FF", "16"),
    )
    forward = snap(relationships=ladder)
    backward = snap(relationships=ladder[::-1])
    assert content_bytes(forward.content) == content_bytes(backward.content)
    assert content_schema(forward.content) == CONTENT_SCHEMA_V3
    assert counts(forward) == counts(backward)
    assert counts(forward)["relationships_parallel_dropped"] == 0
    assert run_cpm(forward.content) == run_cpm(backward.content)


def test_a_repeated_type_on_one_pair_keeps_the_largest_lag_in_any_order() -> None:
    # P6 does not write the same type twice between one pair; if an export does, the
    # largest lag binds both passes, so it is kept whatever the row order and the
    # other is counted `relationships_parallel_dropped`.
    rows = (
        rel("SYN-1010", "SYN-1020", "PR_FS", "8"),
        rel("SYN-1010", "SYN-1020", "PR_FS", "16"),
    )
    for ordered in (rows, rows[::-1]):
        built = snap(relationships=ordered)
        assert [(r.type, r.lag_minutes) for r in built.content.relationships] == [
            (RelationshipType.FS, 960)
        ]
        assert content_schema(built.content) == CONTENT_SCHEMA
        assert counts(built)["relationships_parallel_dropped"] == 1


# ---- published reference and content schema -------------------------------------------


def test_published_reference_fields_are_null_unless_requested() -> None:
    built = snap()
    for activity in built.content.activities:
        reference = activity.published_reference
        assert reference is not None
        assert reference.publication_id == PUBLICATION
        assert reference.fields is None
        assert reference.original_duration.value == Decimal("40.000")
        assert reference.start.value == date(2030, 1, 7)
    assert b'"fields"' not in content_bytes(built.content)


def test_requested_fields_travel_inert_and_make_the_content_v2() -> None:
    first = act(
        "SYN-1010",
        2,
        fields={"xer:TASK.est_wt": "1.25", "udf:TASK:Synthetic Number": 3, "code:Phase": True},
    )
    built = snap(
        activities=(first, act("SYN-1020", 3)),
        request=P6SnapshotRequest(
            include_fields=("xer:TASK.est_wt", "udf:TASK:Synthetic Number", "code:Phase")
        ),
    )
    acts = by_code(built)
    assert acts["SYN-1010"].published_reference.fields == (
        ("code:Phase", True),
        ("udf:TASK:Synthetic Number", 3),
        ("xer:TASK.est_wt", "1.25"),
    )
    # A missing value is null under its key, never an absent key or `{}`.
    assert dict(acts["SYN-1020"].published_reference.fields) == {
        "code:Phase": None,
        "udf:TASK:Synthetic Number": None,
        "xer:TASK.est_wt": None,
    }
    assert content_schema(built.content) == CONTENT_SCHEMA_V2
    document = content_bytes(built.content)
    assert b'"xer:TASK.est_wt":"1.25"' in document
    assert content_from_object(content_object(built.content)) == built.content
    # The engine never reads them: the same network computes the same result.
    with_fields, without = run_cpm(built.content), run_cpm(snap().content)
    assert with_fields.summary.project_finish == without.summary.project_finish


def test_hours_not_exact_at_3_decimals_are_an_ambiguous_published_cell() -> None:
    built = snap(
        activities=(act("SYN-1010", 2, original_hours=Decimal("1.00005")),), relationships=()
    )
    reference = by_code(built)["SYN-1010"].published_reference
    assert reference.original_duration.state is ScheduleCellState.AMBIGUOUS


def test_an_unlinked_activity_or_a_bad_data_date_is_refused() -> None:
    assert refused(
        activities=(act("SYN-1010", 2, schedule_activity_id=None),), relationships=()
    ) is (P6SnapshotRefusal.ROWS)
    early = dataclasses.replace(PROJECT, data_date=datetime(1999, 12, 31, 8, 0))
    assert refused(project=early) is P6SnapshotRefusal.DATA_DATE


def test_unmodelled_settings_and_the_standard_calendar_horizon() -> None:
    built = snap(
        project=dataclasses.replace(
            PROJECT,
            ss_lag_from_early_start=True,
            use_expected_finish=True,
            default_p6_calendar_id=None,
        ),
        activities=(act("SYN-1010", 2, late_finish=datetime(2060, 1, 1, 8, 0)),),
        relationships=(),
    )
    assert built.p6_report.unmodelled_settings == ("ss_lag_from_early_start", "use_expected_finish")
    # Materialized to 2050: a published date in 2060 outruns the standard calendar.
    assert built.p6_report.standard_calendar_horizon_exceeded == (STANDARD_CALENDAR_KEY,)
    assert snap().p6_report.standard_calendar_horizon_exceeded == ()
