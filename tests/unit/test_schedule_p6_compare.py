"""P6 XER S7-4b: the pure delta `cpm-workbench-p6-delta-v1` (acceptance D5).

Contract `docs/architecture/schedule-xer-import-contract.md` sections 11.2-11.4.
Every change kind on a synthetic pair, each built from one base and one edit,
so a red test names the rule it guards. Every value is synthetic.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import pytest

from my_pa.domain.schedule.p6_compare import (
    P6_DELTA_ALGORITHM_VERSION,
    P6Change,
    P6ChangeKind,
    P6ChangeScope,
    P6DeltaActivity,
    P6DeltaCalendar,
    P6DeltaRelationship,
    P6DeltaSide,
    compare_p6_publications,
    p6_unmatched_target_activity_ids,
)

WEEK: Final = ((), *(((480, 720), (780, 1020)),) * 5, ())
DATA_DATE: Final = datetime(2030, 1, 7, 8, 0)


def activity(code: str, number: int, **changes: Any) -> P6DeltaActivity:  # noqa: ANN401
    base = P6DeltaActivity(
        schedule_activity_id=f"sact_p6delta{number:04d}",
        activity_id=code,
        name=f"Synthetic {code}",
        wbs_path=("Area A",),
        task_type="TT_Task",
        status="TK_NotStart",
        p6_calendar_id=501,
        numbers={
            "original_hours": Decimal("40"),
            "remaining_hours": Decimal("40"),
            "total_float_hours": Decimal("0"),
            "free_float_hours": Decimal("0"),
            "physical_pct": Decimal("0"),
        },
        dates={
            "start": datetime(2030, 1, 7, 8, 0),
            "finish": datetime(2030, 1, 11, 17, 0),
            "early_start": datetime(2030, 1, 7, 8, 0),
            "early_finish": datetime(2030, 1, 11, 17, 0),
            "late_start": datetime(2030, 1, 7, 8, 0),
            "late_finish": datetime(2030, 1, 11, 17, 0),
            "planned_start": datetime(2030, 1, 7, 8, 0),
            "planned_finish": datetime(2030, 1, 11, 17, 0),
            "actual_start": None,
            "actual_finish": None,
        },
        constraint=(None, None),
        constraint2=(None, None),
        guid=f"guid-{code}",
        fields={},
    )
    return dataclasses.replace(base, **changes)


def calendar(p6_id: int = 501, **changes: Any) -> P6DeltaCalendar:  # noqa: ANN401
    base = P6DeltaCalendar(
        p6_calendar_id=p6_id,
        name=f"Synthetic Calendar {p6_id}",
        week=WEEK,
        exceptions={"2030-01-01": ()},
        data_sha256=f"{p6_id:064d}",
    )
    return dataclasses.replace(base, **changes)


def link(pred: str, succ: str, kind: str = "FS", lag: str = "0") -> P6DeltaRelationship:
    return P6DeltaRelationship(pred, succ, kind, Decimal(lag), is_external=False)


def side(**changes: Any) -> P6DeltaSide:  # noqa: ANN401
    base = P6DeltaSide(
        data_date=DATA_DATE,
        project={"lag_calendar": "rcal_Predecessor", "export_version": "26.4"},
        calendars=(calendar(),),
        activities=(activity("SYN-1000", 1), activity("SYN-1010", 2)),
        relationships=(link("SYN-1000", "SYN-1010"),),
        capture_keys=frozenset(),
    )
    return dataclasses.replace(base, **changes)


def only(changes: tuple[P6Change, ...], kind: P6ChangeKind) -> list[P6Change]:
    return [change for change in changes if change.kind is kind]


def with_numbers(item: P6DeltaActivity, **numbers: str | None) -> P6DeltaActivity:
    merged: dict[str, Decimal | None] = dict(item.numbers)
    merged.update({k: None if v is None else Decimal(v) for k, v in numbers.items()})
    return dataclasses.replace(item, numbers=merged)


def with_dates(item: P6DeltaActivity, **dates: datetime | None) -> P6DeltaActivity:
    merged: dict[str, datetime | None] = dict(item.dates)
    merged.update(dates)
    return dataclasses.replace(item, dates=merged)


def test_identical_sides_have_no_change_and_every_kind_is_counted() -> None:
    delta = compare_p6_publications(side(), side(), frozenset())
    assert delta.changes == ()
    assert tuple(delta.counts_by_kind) == tuple(P6ChangeKind)
    assert set(delta.counts_by_kind.values()) == {0}
    assert P6_DELTA_ALGORITHM_VERSION == "cpm-workbench-p6-delta-v1"


def test_added_removed_and_reintroduced() -> None:
    a = side(activities=(activity("SYN-1000", 1), activity("SYN-1010", 2)))
    b = side(
        activities=(activity("SYN-1000", 1), activity("SYN-1020", 3), activity("SYN-1030", 4)),
        relationships=(),
    )
    prior = frozenset({"sact_p6delta0004"})
    assert p6_unmatched_target_activity_ids(a.activities, b.activities) == {
        "sact_p6delta0003",
        "sact_p6delta0004",
    }
    delta = compare_p6_publications(a, b, prior)
    assert [c.subject for c in only(delta.changes, P6ChangeKind.REMOVED)] == [("SYN-1010",)]
    assert [c.subject for c in only(delta.changes, P6ChangeKind.ADDED)] == [("SYN-1020",)]
    assert [c.subject for c in only(delta.changes, P6ChangeKind.REINTRODUCED)] == [("SYN-1030",)]
    removed = only(delta.changes, P6ChangeKind.REMOVED)[0]
    assert removed.before == {"name": "Synthetic SYN-1010", "task_type": "TT_Task"}
    assert removed.after is None


def test_a_renumbered_activity_is_removed_and_added_with_a_hint_never_merged() -> None:
    a = side(activities=(activity("SYN-1000", 1), activity("SYN-1010", 2, guid="guid-same")))
    b = side(
        activities=(activity("SYN-1000", 1), activity("SYN-1011", 3, guid="guid-same")),
        relationships=(),
    )
    delta = compare_p6_publications(a, b, frozenset())
    assert delta.counts_by_kind[P6ChangeKind.REMOVED] == 1
    assert delta.counts_by_kind[P6ChangeKind.ADDED] == 1
    (hint,) = only(delta.changes, P6ChangeKind.RENUMBER_CANDIDATE)
    assert hint.before == {"activity_id": "SYN-1010", "schedule_activity_id": "sact_p6delta0002"}
    assert hint.after == {"activity_id": "SYN-1011", "schedule_activity_id": "sact_p6delta0003"}
    # A hint, never a link: each side keeps its own Stable Activity.
    assert hint.schedule_activity_id == "sact_p6delta0003"
    no_guid = side(
        activities=(activity("SYN-1000", 1), activity("SYN-1011", 3, guid=None)),
        relationships=(),
    )
    assert not only(
        compare_p6_publications(a, no_guid, frozenset()).changes, P6ChangeKind.RENUMBER_CANDIDATE
    )


@pytest.mark.parametrize(
    ("changes", "kind", "field"),
    [
        ({"name": "Synthetic Renamed"}, P6ChangeKind.RENAMED, "name"),
        ({"wbs_path": ("Area B", "Package B1")}, P6ChangeKind.WBS_MOVED, "wbs_path"),
        ({"task_type": "TT_FinMile"}, P6ChangeKind.TYPE_CHANGED, "task_type"),
        ({"status": "TK_Active"}, P6ChangeKind.STATUS_CHANGED, "status"),
        (
            {"constraint": ("CS_MSOA", datetime(2030, 1, 8, 8, 0))},
            P6ChangeKind.CONSTRAINT_CHANGED,
            "constraint",
        ),
        (
            {"constraint2": ("CS_MEOB", datetime(2030, 1, 9, 17, 0))},
            P6ChangeKind.CONSTRAINT_CHANGED,
            "constraint2",
        ),
    ],
)
def test_each_plain_activity_rule(
    changes: Mapping[str, Any], kind: P6ChangeKind, field: str
) -> None:
    b = side(activities=(activity("SYN-1000", 1, **changes), activity("SYN-1010", 2)))
    delta = compare_p6_publications(side(), b, frozenset())
    assert [(c.kind, c.field) for c in delta.changes] == [(kind, field)]
    (change,) = delta.changes
    assert change.scope is P6ChangeScope.ACTIVITY
    assert change.subject == ("SYN-1000",)
    assert change.schedule_activity_id == "sact_p6delta0001"


def test_duration_float_and_progress_carry_a_signed_number_delta() -> None:
    edited = with_numbers(
        activity("SYN-1000", 1),
        original_hours="48",
        remaining_hours="12.5",
        total_float_hours="-8",
        free_float_hours=None,
        physical_pct="25",
    )
    delta = compare_p6_publications(
        side(), side(activities=(edited, activity("SYN-1010", 2))), frozenset()
    )
    found = {(c.kind, c.field): c for c in delta.changes}
    assert found[(P6ChangeKind.DURATION_CHANGED, "original_hours")].delta == Decimal(8)
    remaining = found[(P6ChangeKind.DURATION_CHANGED, "remaining_hours")]
    assert (remaining.before, remaining.after, remaining.delta) == ("40", "12.5", Decimal("-27.5"))
    assert found[(P6ChangeKind.FLOAT_CHANGED, "total_float_hours")].delta == Decimal(-8)
    free = found[(P6ChangeKind.FLOAT_CHANGED, "free_float_hours")]
    assert (free.before, free.after, free.delta) == ("0", None, None)
    assert found[(P6ChangeKind.PROGRESS_CHANGED, "physical_pct")].delta == Decimal(25)


def test_each_date_has_its_own_signed_delta_in_calendar_minutes() -> None:
    edited = with_dates(
        activity("SYN-1000", 1),
        start=datetime(2030, 1, 8, 8, 0),
        early_finish=datetime(2030, 1, 11, 13, 0),
        late_start=datetime(2030, 1, 6, 8, 0),
        actual_start=datetime(2030, 1, 7, 9, 30),
    )
    delta = compare_p6_publications(
        side(), side(activities=(edited, activity("SYN-1010", 2))), frozenset()
    )
    dates = {c.field: c for c in only(delta.changes, P6ChangeKind.DATES_CHANGED)}
    assert dates["start"].delta_minutes == 1440
    assert dates["early_finish"].delta_minutes == -240
    assert dates["late_start"].delta_minutes == -1440
    assert (dates["actual_start"].before, dates["actual_start"].delta_minutes) == (None, None)
    assert dates["actual_start"].after == "2030-01-07T09:30"
    assert set(dates) == {"start", "early_finish", "late_start", "actual_start"}


def test_calendar_changed_follows_the_calendars_content_not_its_id() -> None:
    same_content = calendar(777, data_sha256=f"{501:064d}")
    renumbered = side(
        calendars=(same_content,),
        activities=(
            activity("SYN-1000", 1, p6_calendar_id=777),
            activity("SYN-1010", 2, p6_calendar_id=777),
        ),
    )
    delta = compare_p6_publications(side(), renumbered, frozenset())
    assert not only(delta.changes, P6ChangeKind.CALENDAR_CHANGED)
    other = side(
        calendars=(calendar(), calendar(502)),
        activities=(activity("SYN-1000", 1, p6_calendar_id=502), activity("SYN-1010", 2)),
    )
    (change,) = only(
        compare_p6_publications(side(), other, frozenset()).changes, P6ChangeKind.CALENDAR_CHANGED
    )
    assert change.before == {"calendar_id": 501, "name": "Synthetic Calendar 501"}
    assert change.after == {"calendar_id": 502, "name": "Synthetic Calendar 502"}


def test_calendar_week_and_exception_counts() -> None:
    week = ((), *(((420, 900),),) * 5, ())
    edited = calendar(
        week=week,
        exceptions={"2030-01-02": (), "2030-01-03": ((480, 720),)},
        data_sha256="f" * 64,
    )
    b = side(calendars=(edited,))
    delta = compare_p6_publications(side(), b, frozenset())
    (week_change,) = only(delta.changes, P6ChangeKind.CALENDAR_WEEK_CHANGED)
    assert week_change.scope is P6ChangeScope.CALENDAR
    assert week_change.after["week"][1] == [["07:00", "15:00"]]  # type: ignore[index]
    (exceptions,) = only(delta.changes, P6ChangeKind.CALENDAR_EXCEPTIONS_CHANGED)
    assert exceptions.counts == {"dates_added": 2, "dates_removed": 1, "dates_changed": 0}
    # The activities' calendar content changed too.
    assert delta.counts_by_kind[P6ChangeKind.CALENDAR_CHANGED] == 2


def test_calendars_match_by_id_then_by_unique_name_and_the_rest_are_counted() -> None:
    renamed_id = calendar(901, name="Synthetic Calendar 501", week=((), *(((480, 960),),) * 5, ()))
    stray = calendar(902, name="Synthetic Elsewhere")
    delta = compare_p6_publications(side(), side(calendars=(renamed_id, stray)), frozenset())
    assert delta.counts_by_kind[P6ChangeKind.CALENDAR_WEEK_CHANGED] == 1
    assert delta.calendars_unmatched == 1


def test_relationships_match_by_activity_id_pair() -> None:
    a = side(relationships=(link("SYN-1000", "SYN-1010"), link("SYN-1010", "SYN-1000", "SS")))
    b = side(
        relationships=(
            link("SYN-1000", "SYN-1010", "FF", "8"),
            P6DeltaRelationship("SYN-1000", None, "FS", Decimal(0), is_external=True),
        ),
        activities=(activity("SYN-1000", 1), activity("SYN-1010", 2)),
    )
    b = dataclasses.replace(b, relationships=(*b.relationships, link("SYN-1010", "SYN-1000", "SS")))
    c = dataclasses.replace(b, relationships=(link("SYN-1000", "SYN-1010", "FF", "8"),))
    delta = compare_p6_publications(a, b, frozenset())
    changed = only(delta.changes, P6ChangeKind.RELATIONSHIP_CHANGED)
    assert [(x.field, x.before, x.after) for x in changed] == [
        ("type", "FS", "FF"),
        ("lag_hours", "0", "8"),
    ]
    assert changed[1].delta == Decimal(8)
    assert delta.external_relationships == 1
    removed = compare_p6_publications(a, c, frozenset())
    (gone,) = only(removed.changes, P6ChangeKind.RELATIONSHIP_REMOVED)
    assert gone.subject == ("SYN-1010", "SYN-1000")
    (new,) = only(
        compare_p6_publications(c, a, frozenset()).changes, P6ChangeKind.RELATIONSHIP_ADDED
    )
    assert new.after == {"type": "SS", "lag_hours": "0"}


def test_project_data_date_and_settings() -> None:
    b = side(
        data_date=datetime(2030, 1, 14, 8, 0),
        project={"lag_calendar": "rcal_Project", "export_version": "26.4", "export_date": None},
    )
    delta = compare_p6_publications(side(), b, frozenset())
    (moved,) = only(delta.changes, P6ChangeKind.DATA_DATE_CHANGED)
    assert moved.delta_minutes == 7 * 1440
    (setting,) = only(delta.changes, P6ChangeKind.SETTINGS_CHANGED)
    assert (setting.field, setting.before, setting.after) == (
        "lag_calendar",
        "rcal_Predecessor",
        "rcal_Project",
    )
    # A re-export: only the header moves (section 11.2).
    header = side(project={"lag_calendar": "rcal_Predecessor", "export_version": "26.5"})
    assert [c.field for c in compare_p6_publications(side(), header, frozenset()).changes] == [
        "export_version"
    ]


def test_captured_fields_compare_only_where_both_capture_sets_hold_them() -> None:
    keys_a = frozenset({"xer:TASK.est_wt", "udf:TASK:Synthetic Text", "xer:TASK.rev_fdbk_flag"})
    keys_b = frozenset({"xer:TASK.est_wt", "udf:TASK:Synthetic Text", "code:Synthetic Phase"})
    a = side(
        capture_keys=keys_a,
        activities=(
            activity(
                "SYN-1000",
                1,
                fields={"xer:TASK.est_wt": ("1",), "xer:TASK.rev_fdbk_flag": (False,)},
            ),
            activity("SYN-1010", 2, fields={"udf:TASK:Synthetic Text": ("one",)}),
        ),
    )
    b = side(
        capture_keys=keys_b,
        activities=(
            activity(
                "SYN-1000", 1, fields={"xer:TASK.est_wt": ("2",), "code:Synthetic Phase": ("P1",)}
            ),
            activity("SYN-1010", 2, fields={"udf:TASK:Synthetic Text": ("one",)}),
        ),
    )
    delta = compare_p6_publications(a, b, frozenset())
    assert [(c.subject, c.field, c.before, c.after) for c in delta.changes] == [
        (("SYN-1000",), "xer:TASK.est_wt", "1", "2")
    ]
    # One key only in A's set, one only in B's: counted, never a change.
    assert delta.fields_not_comparable == 2
    withheld = compare_p6_publications(
        a, b, frozenset(), personal_keys=frozenset({"xer:TASK.est_wt"})
    )
    assert withheld.changes == ()
    assert withheld.fields_withheld == 1


def test_changes_sort_by_scope_subject_kind_field() -> None:
    edited = with_numbers(activity("SYN-1000", 1, name="Synthetic Renamed"), original_hours="8")
    b = side(
        data_date=datetime(2030, 1, 8, 8, 0),
        activities=(edited, activity("SYN-1010", 2, status="TK_Active")),
        relationships=(),
    )
    delta = compare_p6_publications(side(), b, frozenset())
    assert [(c.scope.value, c.subject, c.kind.value) for c in delta.changes] == [
        ("project", (), "data_date_changed"),
        ("activity", ("SYN-1000",), "renamed"),
        ("activity", ("SYN-1000",), "duration_changed"),
        ("activity", ("SYN-1010",), "status_changed"),
        ("relationship", ("SYN-1000", "SYN-1010"), "relationship_removed"),
    ]
    assert sum(delta.counts_by_kind.values()) == len(delta.changes)


def test_one_activity_id_is_one_stable_activity() -> None:
    b = side(activities=(activity("SYN-1000", 9), activity("SYN-1010", 2)))
    with pytest.raises(ValueError, match="stable activity"):
        compare_p6_publications(side(), b, frozenset())


# ---- F1: the delta reads only the comparable keys' values ---------------------------------

SHARED: Final = "udf:TASK:Synthetic Shared"
PERSONAL: Final = "xer:TASK.create_user"
ONLY_A: Final = tuple(f"udf:TASK:Synthetic Only A {n:03d}" for n in range(40))
ONLY_B: Final = tuple(f"udf:TASK:Synthetic Only B {n:03d}" for n in range(40))
ROWS: Final = 250


class _Recorder:
    """A P6 repository over synthetic rows that records the value keys it is asked for."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, tuple[str, ...] | None]] = []
        self.rows_read = 0
        stored_a = (SHARED, PERSONAL, *ONLY_A)
        self.values = {
            "run-a": self._values("run-a", stored_a),
            "run-b": self._values("run-b", (SHARED, PERSONAL, *ONLY_B)),
        }
        self.selection = {"event-b": (SHARED, PERSONAL, *ONLY_B)}

    @staticmethod
    def _values(run: str, keys: tuple[str, ...]) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "activity_id": f"SYN-{n:04d}",
                "field_key": key,
                "ordinal": 0,
                "value_text": f"{run} {key} {n}",
                "value_number": None,
                "value_ts": None,
                "value_flag": None,
            }
            for n in range(ROWS)
            for key in sorted(keys)
        )

    def p6_project_block(self, principal_id: str, run: str) -> dict[str, object]:
        return {"data_date": DATA_DATE, "run": run}

    def p6_calendar_rows(self, *args: object, **kwargs: object) -> tuple[()]:
        return ()

    def p6_activity_rows(self, *args: object, **kwargs: object) -> tuple[dict[str, object], ...]:
        base = activity("SYN-0000", 0)
        return tuple(
            {
                "schedule_activity_id": f"sact_p6delta{n:04d}",
                "activity_id": f"SYN-{n:04d}",
                "activity_name": base.name,
                "wbs_path": list(base.wbs_path),
                "task_type": base.task_type,
                "status_code": base.status,
                "p6_calendar_id": None,
                **base.numbers,
                **{
                    {"start": "start_at", "finish": "finish_at"}.get(name, name): value
                    for name, value in base.dates.items()
                },
                "constraint_type": None,
                "constraint_date": None,
                "constraint2_type": None,
                "constraint2_date": None,
                "p6_guid": f"guid-{n}",
            }
            for n in range(ROWS)
        )

    def p6_relationship_rows(self, *args: object, **kwargs: object) -> tuple[()]:
        return ()

    def p6_activity_field_keys(self, principal_id: str, run: str) -> frozenset[str]:
        return frozenset(str(row["field_key"]) for row in self.values[run])

    def p6_activity_field_values(
        self, principal_id: str, run: str, field_keys: tuple[str, ...] | None
    ) -> tuple[dict[str, object], ...]:
        self.asked.append((run, None if field_keys is None else tuple(field_keys)))
        found = tuple(
            row for row in self.values[run] if field_keys is None or row["field_key"] in field_keys
        )
        self.rows_read += len(found)
        return found

    def capture_selection(self, principal_id: str, event: str | None) -> tuple[str, ...] | None:
        return None if event is None else self.selection[event]


def _ref(run: str, event: str | None) -> Any:  # noqa: ANN401
    from my_pa.domain.schedule.p6_reads import P6PublicationRef

    return P6PublicationRef(
        publication_id=f"pub-{run}",
        series_id="series",
        project_id="project",
        source_format="p6_xer",
        status="complete",
        accepted_parser_run_id=run,
        capture_event_id=event,
        include_personal=True,
        admitted_at=DATA_DATE,
    )


def test_the_delta_reads_no_personal_nor_one_sided_value() -> None:
    """F1: a pair with many one-sided and personal values reads only the shared key's."""
    from my_pa.application import schedule_p6_delta as reads
    from my_pa.domain.schedule.p6_reads import is_personal_key

    assert is_personal_key(PERSONAL)
    repo = _Recorder()
    a, b = _ref("run-a", None), _ref("run-b", "event-b")
    from_side, to_side, personal = reads.load_p6_delta_pair(repo, "principal", a, b)  # type: ignore[arg-type]
    assert repo.asked == [("run-a", (SHARED,)), ("run-b", (SHARED,))]
    assert repo.rows_read == 2 * ROWS
    assert personal == frozenset({PERSONAL})
    delta = compare_p6_publications(from_side, to_side, frozenset(), personal_keys=personal)
    # The same answer as a delta that read every value.
    full = _Recorder()
    every = tuple(
        reads.load_p6_delta_side(
            full,  # type: ignore[arg-type]
            "principal",
            ref,
            capture_keys=reads.p6_delta_capture_keys(full, "principal", ref),  # type: ignore[arg-type]
            field_keys=None,  # type: ignore[arg-type]
        )
        for ref in (a, b)
    )
    reference = compare_p6_publications(*every, frozenset(), personal_keys=personal)
    assert delta == reference
    assert [c.field for c in delta.changes] == [SHARED] * ROWS
    assert delta.fields_withheld == 1
    assert delta.fields_not_comparable == len(from_side.capture_keys ^ to_side.capture_keys)
    assert delta.fields_not_comparable >= len(ONLY_A) + len(ONLY_B)
