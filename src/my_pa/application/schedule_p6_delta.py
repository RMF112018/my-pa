"""P6 XER S7-4b: the reads and the answer shape of the P6 delta (`schedule_changes.list`).

Contract `docs/architecture/schedule-xer-import-contract.md` section 11.4. The
pure comparison is `domain.schedule.p6_compare`; this module turns one P6
publication's accepted run (read through the P6 repository, Principal
partitioned) into its `P6DeltaSide`, and one `P6Change` into the wire shape.
Nothing here writes: the delta is never stored.

A publication's capture set (section 7.2) is the selection in force at its
admission (its capture event's keys), or -- when it was admitted under the
defaults -- the catalogue's default-captured keys plus every UDF and activity
code key the run captured (the defaults capture those per file).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

from my_pa.application.errors import InternalError
from my_pa.contracts.ports import ScheduleP6Repository
from my_pa.domain.schedule.p6.parser import default_capture_keys
from my_pa.domain.schedule.p6_compare import (
    P6Change,
    P6DeltaActivity,
    P6DeltaCalendar,
    P6DeltaRelationship,
    P6DeltaSide,
)
from my_pa.domain.schedule.p6_reads import P6PublicationRef
from my_pa.domain.schedule.scenario.model import MAX_ACTIVITIES, MAX_RELATIONSHIPS

__all__ = ["load_p6_delta_side", "p6_change_shape"]

#: Every stored calendar of one run (a P6 export holds far fewer).
_CALENDAR_LIMIT: Final = 100_000
_NUMBERS: Final = (
    "original_hours",
    "remaining_hours",
    "total_float_hours",
    "free_float_hours",
    "physical_pct",
)
#: Delta date name -> stored column (`start`/`finish` are the derived dates).
_DATES: Final[Mapping[str, str]] = {
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
_RELATIONSHIP_TYPE_PREFIX: Final = "PR_"


def _rendered(row: Mapping[str, object]) -> object:
    """One stored value as the reads render it: numbers as text, times ISO local."""
    number = row["value_number"]
    if isinstance(number, Decimal):
        text = format(number.normalize(), "f")
        return "0" if text in ("-0", "") else text
    moment = row["value_ts"]
    if isinstance(moment, datetime):
        return moment.isoformat(timespec="minutes" if moment.second == 0 else "seconds")
    if row["value_flag"] is not None:
        return bool(row["value_flag"])
    return row["value_text"]


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)  # type: ignore[call-overload]


def _pattern(value: object) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, list):
        raise InternalError()
    return tuple((int(pair[0]), int(pair[1])) for pair in value)


def _calendar(row: Mapping[str, Any]) -> P6DeltaCalendar:
    week = row["week"]
    exceptions = row["exceptions"]
    if not isinstance(week, list) or not isinstance(exceptions, list):
        raise InternalError()
    return P6DeltaCalendar(
        p6_calendar_id=int(row["p6_calendar_id"]),
        name=row["name"],
        week=tuple(_pattern(day) for day in week),
        exceptions={str(item["date"]): _pattern(item["intervals"]) for item in exceptions},
        data_sha256=row["data_sha256"],
    )


def _activity(row: Mapping[str, Any], fields: Mapping[str, tuple[Any, ...]]) -> P6DeltaActivity:
    sact = row["schedule_activity_id"]
    if sact is None:  # pragma: no cover - a complete publication's rows are linked
        raise InternalError()
    return P6DeltaActivity(
        schedule_activity_id=str(sact),
        activity_id=str(row["activity_id"]),
        name=str(row["activity_name"]),
        wbs_path=tuple(row["wbs_path"]),
        task_type=str(row["task_type"]),
        status=str(row["status_code"]),
        p6_calendar_id=_optional_int(row["p6_calendar_id"]),
        numbers={name: row[name] for name in _NUMBERS},
        dates={name: row[column] for name, column in _DATES.items()},
        constraint=(row["constraint_type"], row["constraint_date"]),
        constraint2=(row["constraint2_type"], row["constraint2_date"]),
        guid=row["p6_guid"],
        fields=fields,
    )


def _relationship(row: Mapping[str, Any]) -> P6DeltaRelationship:
    return P6DeltaRelationship(
        pred_activity_id=row["pred_activity_id"],
        succ_activity_id=row["succ_activity_id"],
        relationship_type=str(row["relationship_type"]).removeprefix(_RELATIONSHIP_TYPE_PREFIX),
        lag_hours=row["lag_hours"],
        is_external=bool(row["is_external"]),
    )


def _values_by_activity(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, tuple[object, ...]]]:
    found: dict[str, dict[str, list[object]]] = {}
    for row in rows:
        activity = row["activity_id"]
        if activity is None:  # pragma: no cover - an activity value names its Activity ID
            continue
        found.setdefault(str(activity), {}).setdefault(str(row["field_key"]), []).append(
            _rendered(row)
        )
    return {
        activity: {key: tuple(values) for key, values in keyed.items()}
        for activity, keyed in found.items()
    }


def load_p6_delta_side(
    p6: ScheduleP6Repository, principal_id: str, publication: P6PublicationRef
) -> P6DeltaSide:
    """One complete P6 publication's accepted run as the delta reads it (one transaction)."""
    run = publication.accepted_parser_run_id
    if run is None:  # pragma: no cover - a complete publication has its accepted run
        raise InternalError()
    project = p6.p6_project_block(principal_id, run)
    if project is None:  # pragma: no cover - a complete run has its project row
        raise InternalError()
    calendars = p6.p6_calendar_rows(
        principal_id, run, calendar_id=None, offset=0, limit=_CALENDAR_LIMIT
    )
    activities = p6.p6_activity_rows(principal_id, run, offset=0, limit=MAX_ACTIVITIES + 1)
    relationships = p6.p6_relationship_rows(
        principal_id, run, offset=0, limit=MAX_RELATIONSHIPS + 1
    )
    values = p6.p6_activity_field_values(principal_id, run, None)
    selection = p6.capture_selection(principal_id, publication.capture_event_id)
    if selection is None:
        keys = default_capture_keys() | {str(row["field_key"]) for row in values}
    else:
        keys = frozenset(selection)
    by_activity = _values_by_activity(values)
    data_date = project["data_date"]
    return P6DeltaSide(
        data_date=data_date if isinstance(data_date, datetime) else None,
        project=dict(project),
        calendars=tuple(_calendar(row) for row in calendars),
        activities=tuple(
            _activity(row, by_activity.get(str(row["activity_id"]), {})) for row in activities
        ),
        relationships=tuple(_relationship(row) for row in relationships),
        capture_keys=frozenset(keys),
    )


def _subject(change: P6Change) -> dict[str, object]:
    match change.scope.value:
        case "activity":
            return {
                "activity_id": change.subject[0],
                "schedule_activity_id": change.schedule_activity_id,
            }
        case "relationship":
            return {"pred_activity_id": change.subject[0], "succ_activity_id": change.subject[1]}
        case "calendar":
            return {"calendar_id": int(change.subject[0])}
    return {}


def _delta(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


def _plain(value: object) -> object:
    if isinstance(value, date | datetime):  # pragma: no cover - rendered by the domain
        return value.isoformat()
    return value


def p6_change_shape(change: P6Change) -> dict[str, object]:
    """One change on the wire: scope, kind, field, subject, both sides and its delta."""
    return {
        "scope": change.scope.value,
        "change_kind": change.kind.value,
        "field": change.field,
        "subject": _subject(change),
        "before": _plain(change.before),
        "after": _plain(change.after),
        "delta_minutes": change.delta_minutes,
        "delta": _delta(change.delta),
        "counts": None if change.counts is None else dict(change.counts),
    }
