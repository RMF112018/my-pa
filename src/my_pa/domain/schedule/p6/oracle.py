"""P6 XER S7-5: the engine-vs-P6 oracle and the evaluation adapters (stats only).

Contract `docs/architecture/schedule-xer-import-contract.md` sections 11.5 (the
paragraph naming this comparison and `unmodelled_settings`), 11.4 (the delta)
and 14 (S7-5 acceptance). Pure: the operator script
`ops/schedule/p6_evaluate.py` reads the file and prints; nothing here reads a
file, a clock, the environment or a database.

The oracle is a **check, never a claim of equivalence**. From one parsed export
it builds version 1 of a Scenario with the section 11.5 mapping defaults (the
same pure `snapshot_from_p6` the capability uses), runs the scenario CPM engine
at the snapshot's data date and compares, per activity joined by its Activity
ID (`task_code`), the engine's early start, early finish, late start, late
finish, total float and remaining early start with P6's own values from the
same export (`early_start_date`, `early_end_date`, `late_start_date`,
`late_end_date`, `total_float_hr_cnt` in hours x 60, `restart_date`). Per
quantity it reports how many activities were compared, how many are equal (and
the share), a histogram of `engine - P6` in minutes over fixed bucket edges, and
the activities with no P6 value (P6 often leaves late dates and float empty for
completed work), with a value off the engine's axis, or with no engine value
(a complete activity has no total float in the engine): none of those is a
mismatch. It also compares the critical sets (total float at most the project's
critical threshold, engine and P6 alike, over the activities both give a total
float; a complete activity has none in the engine) and lists the P6 options the export
sets that the engine does not model (`unmodelled_settings`).

Comparison rules (decided in S7-5, every one stated in the report's schema):

- Dates are compared minute exact on the engine's axis (P6 seconds are
  truncated, as the snapshot does); a difference is signed wall-clock minutes
  `engine - P6`.
- Total float is in working minutes on both sides: the engine's
  `total_float_minutes` against `total_float_hr_cnt x 60`, rounded half-even
  when the product is not integral (counted `p6_quantized`).
- Every activity state is compared and counted by state: a complete activity's
  engine dates are its actual dates (S6 section 3.5), an in-progress activity's
  early start is its actual start and its remaining early start is where the
  progress policy puts the remaining work, so a P6 convention that differs for
  progressed work shows in the per-state counts instead of being hidden.

The adapters turn a `P6ParseResult` into the plain records the snapshot and the
delta (`p6_compare`) take, exactly as the application builds them from the
stored rows of an accepted run; the Stable Activity a stored row links to is
here a synthetic key per Activity ID (the identity inside one Series is the
Activity ID, section 11.3).

Nothing returned holds a value from the file: only counts, shares, minute
distributions, closed codes and the names of the options.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final

from my_pa.domain.schedule.p6.catalogue import CATALOGUE, EntityKind
from my_pa.domain.schedule.p6.model import (
    P6Calendar,
    P6Entity,
    P6FieldValue,
    P6Outcome,
    P6ParseResult,
    P6Value,
)
from my_pa.domain.schedule.p6.parser import default_capture_keys
from my_pa.domain.schedule.p6_compare import (
    P6ChangeKind,
    P6DeltaActivity,
    P6DeltaCalendar,
    P6DeltaRelationship,
    P6DeltaSide,
    P6Rendered,
    compare_p6_publications,
)
from my_pa.domain.schedule.scenario.canonical import content_schema
from my_pa.domain.schedule.scenario.cpm import (
    CpmActivityResult,
    CpmStatus,
    engine_version_for,
    run_cpm,
)
from my_pa.domain.schedule.scenario.model import parse_instant
from my_pa.domain.schedule.scenario.p6_snapshot import (
    P6Snapshot,
    P6SnapshotActivity,
    P6SnapshotCalendar,
    P6SnapshotProject,
    P6SnapshotRefusalError,
    P6SnapshotRelationship,
    snapshot_from_p6,
)

__all__ = [
    "BUCKETS",
    "ORACLE_CAPTURE",
    "ORACLE_SCHEMA",
    "QUANTITIES",
    "bucket",
    "delta_counts",
    "delta_side",
    "evaluation_snapshot",
    "oracle_report",
    "same_project",
    "snapshot_report",
    "unmodelled_settings",
]

ORACLE_SCHEMA: Final = "p6-engine-oracle-v1"
#: The capture selection of the oracle's parse: the one optional SCHEDOPTIONS option
#: it reads (multiple float paths); every other input is a typed column.
_MULTIPLE_PATHS_KEY: Final = "xer:SCHEDOPTIONS.enable_multiple_longest_path_calc"
ORACLE_CAPTURE: Final = frozenset({_MULTIPLE_PATHS_KEY})

#: The compared quantities, in report order: (name, engine attribute, P6 column).
QUANTITIES: Final = (
    "early_start",
    "early_finish",
    "late_start",
    "late_finish",
    "total_float",
    "remaining_early_start",
)
_P6_COLUMN: Final[Mapping[str, str]] = {
    "early_start": "early_start",
    "early_finish": "early_finish",
    "late_start": "late_start",
    "late_finish": "late_finish",
    "total_float": "total_float_hours",
    "remaining_early_start": "remaining_early_start",
}
_STATES: Final = ("not_started", "in_progress", "complete")

#: Fixed histogram edges of `engine - P6` in minutes: (name, low, high), inclusive;
#: None is unbounded.
BUCKETS: Final[tuple[tuple[str, int | None, int | None], ...]] = (
    ("-inf..-2401", None, -2401),
    ("-2400..-481", -2400, -481),
    ("-480..-61", -480, -61),
    ("-60..-1", -60, -1),
    ("0", 0, 0),
    ("1..60", 1, 60),
    ("61..480", 61, 480),
    ("481..2400", 481, 2400),
    ("2401..inf", 2401, None),
)

_PUBLICATION: Final = "spub_evaluation0001"
_WHOLE: Final = Decimal(1)
_SHARE: Final = Decimal("0.0001")
_MINUTES_PER_HOUR: Final = 60
_ENGINE_FLOAT_TYPE: Final = "FT_FF"  # finish float, LF - EF: what the engine computes
_ENGINE_CRITICAL_PATH: Final = "CT_TotFloat"  # critical = total float <= threshold
_YES: Final = frozenset({"Y", "y", "1", "true", "True"})
_PERSONAL: Final = frozenset(item.field_key for item in CATALOGUE if item.personal)
_RELATIONSHIP_TYPE_PREFIX: Final = "PR_"

type _Json = bool | int | str | list[_Json] | dict[str, _Json] | None


def bucket(difference: int) -> str:
    """The histogram bucket of one `engine - P6` difference in minutes."""
    for name, low, high in BUCKETS:
        if (low is None or difference >= low) and (high is None or difference <= high):
            return name
    raise AssertionError("the buckets cover every integer")  # pragma: no cover


def _share(part: int, whole: int) -> str | None:
    """`part / whole` at 4 decimals (half-even) as text; null when nothing was compared."""
    if whole == 0:
        return None
    return str((Decimal(part) / Decimal(whole)).quantize(_SHARE, rounding=ROUND_HALF_EVEN))


# ---- the parse as the snapshot reads it -------------------------------------------------


def _text(entity: P6Entity, name: str) -> str | None:
    value = entity.get(name)
    return None if value is None else str(value)


def _moment(entity: P6Entity, name: str) -> datetime | None:
    value = entity.get(name)
    return value if isinstance(value, datetime) else None


def _number(entity: P6Entity, name: str) -> Decimal | None:
    value = entity.get(name)
    if isinstance(value, bool) or not isinstance(value, Decimal | int):
        return None
    return Decimal(value)


def _identifier(entity: P6Entity, name: str) -> int | None:
    value = entity.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _flag(entity: P6Entity, name: str) -> bool | None:
    value = entity.get(name)
    return value if isinstance(value, bool) else None


def _path(entity: P6Entity) -> tuple[str, ...]:
    value = entity.get("wbs_path")
    return value if isinstance(value, tuple) else ()


def _activity_keys(activities: Sequence[P6Entity]) -> dict[str, str]:
    """A synthetic Stable Activity key per Activity ID, in code point order of the IDs."""
    codes = sorted(str(item.get("activity_id")) for item in activities)
    return {code: f"sact_eval{index:010d}" for index, code in enumerate(codes)}


def _snapshot_project(project: P6Entity) -> P6SnapshotProject:
    data_date = _moment(project, "data_date")
    if data_date is None:  # pragma: no cover - an R field of a complete parse
        raise ValueError("a complete parse has a data date")
    return P6SnapshotProject(
        data_date=data_date,
        default_p6_calendar_id=_identifier(project, "default_p6_calendar_id"),
        lag_calendar=_text(project, "lag_calendar"),
        retained_logic=_flag(project, "retained_logic"),
        progress_override=_flag(project, "progress_override"),
        must_finish_by=_moment(project, "must_finish_by"),
        critical_float_hours=_number(project, "critical_float_hours"),
        ss_lag_from_early_start=_flag(project, "ss_lag_from_early_start"),
        use_expected_finish=_flag(project, "use_expected_finish"),
    )


def _snapshot_calendar(calendar: P6Calendar) -> P6SnapshotCalendar:
    return P6SnapshotCalendar(
        p6_calendar_id=calendar.p6_id, week=calendar.week, exceptions=calendar.exceptions
    )


def _snapshot_activity(activity: P6Entity, key: str) -> P6SnapshotActivity:
    return P6SnapshotActivity(
        schedule_activity_id=key,
        activity_id=str(activity.get("activity_id")),
        name=str(activity.get("activity_name")),
        task_type=str(activity.get("task_type")),
        status=str(activity.get("status_code")),
        wbs_path=_path(activity),
        p6_calendar_id=_identifier(activity, "p6_calendar_id"),
        original_hours=_number(activity, "original_hours"),
        remaining_hours=_number(activity, "remaining_hours"),
        start=_moment(activity, "start_at"),
        finish=_moment(activity, "finish_at"),
        late_finish=_moment(activity, "late_finish"),
        actual_start=_moment(activity, "actual_start"),
        actual_finish=_moment(activity, "actual_finish"),
        constraint=(_text(activity, "constraint_type"), _moment(activity, "constraint_date")),
        constraint2=(_text(activity, "constraint2_type"), _moment(activity, "constraint2_date")),
    )


def _snapshot_relationship(relationship: P6Entity) -> P6SnapshotRelationship:
    return P6SnapshotRelationship(
        pred_activity_id=_text(relationship, "pred_activity_id"),
        succ_activity_id=_text(relationship, "succ_activity_id"),
        relationship_type=str(relationship.get("relationship_type")),
        lag_hours=_number(relationship, "lag_hours"),
        is_external=bool(relationship.get("is_external")),
    )


def evaluation_snapshot(result: P6ParseResult) -> P6Snapshot:
    """Version 1 of a Scenario from one complete parse, every section 11.5 default.

    Raises `P6SnapshotRefusalError` exactly where the capability refuses, and
    `ValueError` for a failed parse.
    """
    if result.outcome is not P6Outcome.COMPLETE or result.project is None:
        raise ValueError("only a complete parse has a snapshot")
    keys = _activity_keys(result.activities)
    return snapshot_from_p6(
        publication_id=_PUBLICATION,
        project=_snapshot_project(result.project),
        calendars=tuple(_snapshot_calendar(item) for item in result.calendars),
        activities=tuple(
            _snapshot_activity(item, keys[str(item.get("activity_id"))])
            for item in result.activities
        ),
        relationships=tuple(_snapshot_relationship(item) for item in result.relationships),
    )


def snapshot_report(snapshot: P6Snapshot) -> dict[str, _Json]:
    """The section 11.5 report as counts (an outrun standard calendar is counted, not named)."""
    report = snapshot.p6_report
    return {
        "content_schema": content_schema(snapshot.content),
        "counts": dict(report.counts),
        "standard_calendar_horizon_exceeded": len(report.standard_calendar_horizon_exceeded),
        "unmodelled_settings": list(report.unmodelled_settings),
    }


# ---- the oracle -------------------------------------------------------------------------


def _captured(values: Sequence[P6FieldValue], key: str) -> P6Value:
    for value in values:
        if value.entity_kind is EntityKind.PROJECT and value.field_key == key:
            return value.value
    return None


def unmodelled_settings(result: P6ParseResult, snapshot: P6Snapshot) -> tuple[str, ...]:
    """Every P6 option this export sets that the engine does not model, in a fixed order.

    The snapshot's own (`ss_lag_from_early_start`, `use_expected_finish`) first,
    then the further SCHEDOPTIONS and PROJECT options the parser exposes.
    """
    project = result.project
    assert project is not None  # noqa: S101 - a snapshot exists only for a complete parse
    found = list(snapshot.p6_report.unmodelled_settings)
    float_type = _text(project, "float_type")
    if float_type is not None and float_type != _ENGINE_FLOAT_TYPE:
        found.append("total_float_type")
    if _flag(project, "open_ends_critical"):
        found.append("open_ends_critical")
    if _flag(project, "float_from_project_finish"):
        found.append("float_from_project_finish")
    path_type = _text(project, "critical_path_type")
    if path_type is not None and path_type != _ENGINE_CRITICAL_PATH:
        found.append("critical_path_longest_path")
    if str(_captured(result.field_values, _MULTIPLE_PATHS_KEY)) in _YES:
        found.append("multiple_float_paths")
    counts = snapshot.p6_report.counts
    if counts["external_relationships_dropped"]:
        found.append("external_relationships")
    if counts["progress_policy_defaulted"]:
        found.append("progress_actual_dates")
    return tuple(found)


def _p6_minutes(entity: P6Entity, quantity: str) -> tuple[str, int | None, bool]:
    """(`value` | `missing` | `off_axis`, P6 minutes, whether a float was quantized)."""
    column = _P6_COLUMN[quantity]
    if quantity == "total_float":
        hours = _number(entity, column)
        if hours is None:
            return "missing", None, False
        product = hours * _MINUTES_PER_HOUR
        minutes = int(product.quantize(_WHOLE, rounding=ROUND_HALF_EVEN))
        return "value", minutes, product != minutes
    moment = _moment(entity, column)
    if moment is None:
        return "missing", None, False
    try:
        return "value", parse_instant(moment.strftime("%Y-%m-%dT%H:%M")), False
    except ValueError:
        return "off_axis", None, False


def _engine_minutes(result: CpmActivityResult, quantity: str) -> int | None:
    if quantity == "early_start":
        return result.early_start
    if quantity == "early_finish":
        return result.early_finish
    if quantity == "late_start":
        return result.late_start
    if quantity == "late_finish":
        return result.late_finish
    if quantity == "total_float":
        return result.total_float_minutes
    return result.remaining_start


@dataclass(slots=True)
class _Tally:
    compared: int = 0
    equal: int = 0
    p6_missing: int = 0
    p6_off_axis: int = 0
    engine_missing: int = 0
    p6_quantized: int = 0
    max_abs: int | None = None
    histogram: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys((name for name, _, _ in BUCKETS), 0)
    )
    #: state -> [compared, equal]
    by_state: dict[str, list[int]] = field(
        default_factory=lambda: {state: [0, 0] for state in _STATES}
    )

    def add(self, state: str, difference: int) -> None:
        self.compared += 1
        self.histogram[bucket(difference)] += 1
        self.by_state[state][0] += 1
        if difference == 0:
            self.equal += 1
            self.by_state[state][1] += 1
        size = abs(difference)
        self.max_abs = size if self.max_abs is None else max(self.max_abs, size)

    def shape(self) -> dict[str, _Json]:
        return {
            "by_state": {
                state: {"compared": pair[0], "equal": pair[1]}
                for state, pair in self.by_state.items()
            },
            "compared": self.compared,
            "differences_minutes": dict(self.histogram),
            "engine_missing": self.engine_missing,
            "equal": self.equal,
            "equal_share": _share(self.equal, self.compared),
            "max_abs_difference_minutes": self.max_abs,
            "p6_missing": self.p6_missing,
            "p6_off_axis": self.p6_off_axis,
            "p6_quantized": self.p6_quantized,
        }


def _not_compared(status: str, **extra: _Json) -> dict[str, _Json]:
    return {
        "nature": "check, not a claim of equivalence",
        "schema": ORACLE_SCHEMA,
        "status": status,
        **extra,
    }


def oracle_report(result: P6ParseResult) -> dict[str, _Json]:
    """The engine-vs-P6 check of one parse (section 11.5, S7-5); stats only."""
    if result.outcome is not P6Outcome.COMPLETE or result.project is None:
        return _not_compared("parse_failed")
    try:
        snapshot = evaluation_snapshot(result)
    except P6SnapshotRefusalError as refused:
        return _not_compared("snapshot_refused", refusal=refused.reason.value)
    unmodelled: list[_Json] = list(unmodelled_settings(result, snapshot))
    content = snapshot.content
    computed = run_cpm(content)
    header: dict[str, _Json] = {
        "content_schema": content_schema(content),
        "engine_issue_counts": {
            code.value: count for code, count in sorted(computed.issue_counts.items())
        },
        "engine_status": computed.status.value,
        "engine_version": engine_version_for(content),
        "unmodelled_settings": unmodelled,
    }
    if computed.status is not CpmStatus.COMPUTED:
        return _not_compared("engine_rejected", **header)

    # The join: engine key -> Activity ID -> P6's row of that Activity ID (never row order).
    code_of = {
        activity.key: activity.published_reference.published_activity_id
        for activity in content.activities
        if activity.published_reference is not None
    }
    p6_rows = {str(item.get("activity_id")): item for item in result.activities}
    tallies = {quantity: _Tally() for quantity in QUANTITIES}
    threshold = content.settings.critical_float_threshold_minutes
    states = dict.fromkeys(_STATES, 0)
    critical = {"both": 0, "engine_only": 0, "p6_only": 0, "neither": 0, "not_compared": 0}
    for engine in computed.activities:
        row = p6_rows[code_of[engine.key]]
        state = engine.state.value
        states[state] += 1
        p6_float: int | None = None
        for quantity in QUANTITIES:
            tally = tallies[quantity]
            kind, p6_value, quantized = _p6_minutes(row, quantity)
            if quantity == "total_float":
                p6_float = p6_value
            engine_value = _engine_minutes(engine, quantity)
            if kind == "missing":
                tally.p6_missing += 1
                continue
            if kind == "off_axis":
                tally.p6_off_axis += 1
                continue
            if engine_value is None:
                tally.engine_missing += 1
                continue
            assert p6_value is not None  # noqa: S101 - a value
            if quantized:
                tally.p6_quantized += 1
            tally.add(state, engine_value - p6_value)
        if p6_float is None or engine.total_float_minutes is None:
            # Section 3.7: a complete activity has no engine float; P6 may leave it empty.
            critical["not_compared"] += 1
            continue
        p6_critical = p6_float <= threshold
        if engine.critical and p6_critical:
            critical["both"] += 1
        elif engine.critical:
            critical["engine_only"] += 1
        elif p6_critical:
            critical["p6_only"] += 1
        else:
            critical["neither"] += 1
    agreeing = critical["both"] + critical["neither"]
    compared = agreeing + critical["engine_only"] + critical["p6_only"]
    return {
        **_not_compared("compared", **header),
        "activities": len(computed.activities),
        "activities_by_state": dict(states),
        "critical": {
            "agreeing": agreeing,
            "agreement_share": _share(agreeing, compared),
            "both": critical["both"],
            "compared": compared,
            "engine": critical["both"] + critical["engine_only"],
            "engine_only": critical["engine_only"],
            "not_compared": critical["not_compared"],
            "p6": critical["both"] + critical["p6_only"],
            "p6_only": critical["p6_only"],
            "sets_equal": critical["engine_only"] == 0 and critical["p6_only"] == 0,
        },
        "quantities": {quantity: tallies[quantity].shape() for quantity in QUANTITIES},
    }


# ---- the delta between 2 parses (section 11.4) --------------------------------------------


def _rendered(value: P6Value) -> P6Rendered:
    """One captured value as the reads render it (numbers as text, times ISO local)."""
    if isinstance(value, bool) or value is None or isinstance(value, int | str):
        return value
    if isinstance(value, Decimal):
        text = format(value.normalize(), "f")
        return "0" if text in ("-0", "") else text
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes" if value.second == 0 else "seconds")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError("an unrenderable captured value")  # pragma: no cover


_DELTA_NUMBERS: Final = (
    "original_hours",
    "remaining_hours",
    "total_float_hours",
    "free_float_hours",
    "physical_pct",
)
_DELTA_DATES: Final[Mapping[str, str]] = {
    "start": "start_at",
    "finish": "finish_at",
    "early_start": "early_start",
    "early_finish": "early_finish",
    "late_start": "late_start",
    "late_finish": "late_finish",
    "planned_start": "planned_start",
    "planned_finish": "planned_finish",
    "actual_start": "actual_start",
    "actual_finish": "actual_finish",
}


def _capture_keys(result: P6ParseResult) -> frozenset[str]:
    """The capture set under the defaults: default keys plus the activity keys captured."""
    return default_capture_keys() | frozenset(
        value.field_key for value in result.field_values if value.entity_kind is EntityKind.ACTIVITY
    )


def delta_side(result: P6ParseResult, keys: Mapping[str, str]) -> P6DeltaSide:
    """One complete parse as the delta reads an accepted run (activities by Activity ID).

    `keys` maps each Activity ID to its Stable Activity key in this evaluation.
    """
    project = result.project
    if result.outcome is not P6Outcome.COMPLETE or project is None:
        raise ValueError("only a complete parse has a delta side")
    fields: dict[str, dict[str, list[P6Rendered]]] = {}
    for value in result.field_values:
        if value.entity_kind is EntityKind.ACTIVITY and value.activity_id is not None:
            fields.setdefault(value.activity_id, {}).setdefault(value.field_key, []).append(
                _rendered(value.value)
            )
    activities = sorted(result.activities, key=lambda item: str(item.get("activity_id")))
    relationships = sorted(
        result.relationships,
        key=lambda item: (
            _text(item, "pred_activity_id") is None,
            _text(item, "pred_activity_id") or "",
            _text(item, "succ_activity_id") is None,
            _text(item, "succ_activity_id") or "",
            item.p6_id,
        ),
    )
    data_date = _moment(project, "data_date")
    return P6DeltaSide(
        data_date=data_date,
        project=dict(project.columns),
        calendars=tuple(
            P6DeltaCalendar(
                p6_calendar_id=item.p6_id,
                name=None if (name := dict(item.columns).get("name")) is None else str(name),
                week=item.week,
                exceptions={day.isoformat(): intervals for day, intervals in item.exceptions},
                data_sha256=item.data_sha256,
            )
            for item in sorted(result.calendars, key=lambda item: item.p6_id)
        ),
        activities=tuple(
            P6DeltaActivity(
                schedule_activity_id=keys[code],
                activity_id=code,
                name=str(item.get("activity_name")),
                wbs_path=_path(item),
                task_type=str(item.get("task_type")),
                status=str(item.get("status_code")),
                p6_calendar_id=_identifier(item, "p6_calendar_id"),
                numbers={name: _number(item, name) for name in _DELTA_NUMBERS},
                dates={name: _moment(item, column) for name, column in _DELTA_DATES.items()},
                constraint=(_text(item, "constraint_type"), _moment(item, "constraint_date")),
                constraint2=(_text(item, "constraint2_type"), _moment(item, "constraint2_date")),
                guid=_text(item, "p6_guid"),
                fields={key: tuple(values) for key, values in fields.get(code, {}).items()},
            )
            for item in activities
            for code in (str(item.get("activity_id")),)
        ),
        relationships=tuple(
            P6DeltaRelationship(
                pred_activity_id=_text(item, "pred_activity_id"),
                succ_activity_id=_text(item, "succ_activity_id"),
                relationship_type=str(item.get("relationship_type")).removeprefix(
                    _RELATIONSHIP_TYPE_PREFIX
                ),
                lag_hours=_number(item, "lag_hours"),
                is_external=bool(item.get("is_external")),
            )
            for item in relationships
        ),
        capture_keys=_capture_keys(result),
    )


def same_project(earlier: P6ParseResult, later: P6ParseResult) -> bool:
    """Section 11.1: the 2 exports share the project short name or the project GUID."""
    if earlier.project is None or later.project is None:
        return False
    for name in ("project_short_name", "project_guid"):
        value = _text(earlier.project, name)
        if value is not None and value == _text(later.project, name):
            return True
    return False


def delta_counts(
    earlier: P6ParseResult, later: P6ParseResult, seen_before: frozenset[str]
) -> dict[str, _Json]:
    """The `earlier -> later` delta's counts by change kind (section 11.4); never a change.

    `seen_before` holds the Activity IDs of every export of the same project
    before `earlier` in the evaluation, so a returning one is `reintroduced`.
    """
    codes = sorted(
        {str(item.get("activity_id")) for item in (*earlier.activities, *later.activities)}
        | seen_before
    )
    keys = {code: f"sact_eval{index:010d}" for index, code in enumerate(codes)}
    from_side = delta_side(earlier, keys)
    to_side = delta_side(later, keys)
    in_earlier = {item.activity_id for item in from_side.activities}
    prior = frozenset(
        keys[item.activity_id]
        for item in to_side.activities
        if item.activity_id not in in_earlier and item.activity_id in seen_before
    )
    changes = compare_p6_publications(from_side, to_side, prior, personal_keys=_PERSONAL)
    return {
        "calendars_unmatched": changes.calendars_unmatched,
        "changes": len(changes.changes),
        "counts_by_kind": {kind.value: changes.counts_by_kind[kind] for kind in P6ChangeKind},
        "external_relationships": changes.external_relationships,
        "fields_not_comparable": changes.fields_not_comparable,
        "fields_withheld": changes.fields_withheld,
    }
