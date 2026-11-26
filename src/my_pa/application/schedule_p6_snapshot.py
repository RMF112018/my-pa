"""P6 XER S7-4b: the reads of a P6 scenario snapshot and its report shape.

Contract `docs/architecture/schedule-xer-import-contract.md` section 11.5. The
pure mapping is `domain.schedule.scenario.p6_snapshot`; this module reads one
P6 publication's accepted run through the P6 repository (Principal
partitioned), resolves the request's `p6` options (calendar references of any
P6 publication of the same Project the caller owns, the captured fields to
carry) and maps the domain refusals to public errors. It writes nothing; the
version is written by `ScheduleScenarioApplication` like every other version 1.

Persistence decision (no migration in S7-4b): the stored version keeps the S6
snapshot report's six columns (activities, milestones, durations quantized,
out of range, original and remaining missing). The P6 counts of section 11.5,
`default_calendar_standard` among them, the unmodelled settings and
`standard_calendar_horizon_exceeded` are reported in the `schedule_scenarios.create`
answer (`p6_snapshot_report`) and recomputed for its replay: the publication's
rows are immutable, so the same request always gives the same report.
`default_calendar_standard` is also visible in the stored content itself (the
default calendar is `my-pa-us-40h-v1`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

from my_pa.application.errors import (
    ApplicationError,
    ConflictError,
    InternalError,
    InvalidRequestError,
    SafeDetail,
)
from my_pa.contracts.ports import ScheduleP6Repository
from my_pa.domain.schedule.p6.parser import default_capture_keys
from my_pa.domain.schedule.p6_reads import P6PublicationRef, is_personal_key
from my_pa.domain.schedule.scenario.model import (
    MAX_ACTIVITIES,
    MAX_RELATIONSHIPS,
    CapturedValue,
    is_captured_field_key,
)
from my_pa.domain.schedule.scenario.p6_snapshot import (
    P6Snapshot,
    P6SnapshotActivity,
    P6SnapshotCalendar,
    P6SnapshotProject,
    P6SnapshotRefusal,
    P6SnapshotRefusalError,
    P6SnapshotRelationship,
    P6SnapshotReport,
    P6SnapshotRequest,
    snapshot_from_p6,
)

__all__ = ["build_p6_snapshot", "p6_snapshot_report_shape"]

_CALENDAR_LIMIT: Final = 100_000
_COMPLETE: Final = "complete"
_REFUSALS: Final[Mapping[P6SnapshotRefusal, ApplicationError]] = {
    P6SnapshotRefusal.CALENDAR: InvalidRequestError(SafeDetail.CALENDAR),
    # A publication the engine cannot hold (an actual date off its axis, a
    # complete activity without its actual date): the S6 `rows` refusal.
    P6SnapshotRefusal.ROWS: ConflictError(SafeDetail.FROM_PUBLICATION_ID),
    P6SnapshotRefusal.DATA_DATE: ConflictError(SafeDetail.FROM_PUBLICATION_ID),
}


def _refusal(reason: P6SnapshotRefusal) -> ApplicationError:
    template = _REFUSALS[reason]
    return type(template)(*template.safe_details)


def _pattern(value: object) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, list):
        raise InternalError()
    return tuple((int(pair[0]), int(pair[1])) for pair in value)


def _calendar(row: Mapping[str, Any]) -> P6SnapshotCalendar:
    week, exceptions = row["week"], row["exceptions"]
    if not isinstance(week, list) or not isinstance(exceptions, list):
        raise InternalError()
    return P6SnapshotCalendar(
        p6_calendar_id=int(row["p6_calendar_id"]),
        week=tuple(_pattern(day) for day in week),
        exceptions=tuple(
            (date.fromisoformat(str(item["date"])), _pattern(item["intervals"]))
            for item in exceptions
        ),
    )


def _captured(row: Mapping[str, object]) -> CapturedValue:
    """A stored value as an inert content value: a non-integral number travels as text."""
    number = row["value_number"]
    if isinstance(number, Decimal):
        if number == number.to_integral_value():
            return int(number)
        text = format(number.normalize(), "f")
        return "0" if text in ("-0", "") else text
    moment = row["value_ts"]
    if isinstance(moment, datetime):
        return moment.isoformat(timespec="minutes" if moment.second == 0 else "seconds")
    flag = row["value_flag"]
    if flag is not None:
        return bool(flag)
    text_value = row["value_text"]
    return None if text_value is None else str(text_value)


def _activity(row: Mapping[str, Any], fields: Mapping[str, CapturedValue]) -> P6SnapshotActivity:
    sact = row["schedule_activity_id"]
    return P6SnapshotActivity(
        schedule_activity_id=None if sact is None else str(sact),
        activity_id=str(row["activity_id"]),
        name=str(row["activity_name"]),
        task_type=str(row["task_type"]),
        status=str(row["status_code"]),
        wbs_path=tuple(row["wbs_path"]),
        p6_calendar_id=None if row["p6_calendar_id"] is None else int(row["p6_calendar_id"]),
        original_hours=row["original_hours"],
        remaining_hours=row["remaining_hours"],
        start=row["start_at"],
        finish=row["finish_at"],
        late_finish=row["late_finish"],
        actual_start=row["actual_start"],
        actual_finish=row["actual_finish"],
        constraint=(row["constraint_type"], row["constraint_date"]),
        constraint2=(row["constraint2_type"], row["constraint2_date"]),
        fields=fields,
    )


def _project(row: Mapping[str, Any]) -> P6SnapshotProject:
    data_date = row["data_date"]
    if not isinstance(data_date, datetime):  # pragma: no cover - a required field
        raise InternalError()
    default = row["default_p6_calendar_id"]
    return P6SnapshotProject(
        data_date=data_date,
        default_p6_calendar_id=None if default is None else int(default),
        lag_calendar=row["lag_calendar"],
        retained_logic=row["retained_logic"],
        progress_override=row["progress_override"],
        must_finish_by=row["must_finish_by"],
        critical_float_hours=row["critical_float_hours"],
        ss_lag_from_early_start=row["ss_lag_from_early_start"],
        use_expected_finish=row["use_expected_finish"],
    )


def _relationship(row: Mapping[str, Any]) -> P6SnapshotRelationship:
    return P6SnapshotRelationship(
        pred_activity_id=row["pred_activity_id"],
        succ_activity_id=row["succ_activity_id"],
        relationship_type=str(row["relationship_type"]),
        lag_hours=row["lag_hours"],
        is_external=bool(row["is_external"]),
    )


def _capture_keys(
    p6: ScheduleP6Repository, principal_id: str, publication: P6PublicationRef, run: str
) -> frozenset[str]:
    selection = p6.capture_selection(principal_id, publication.capture_event_id)
    if selection is not None:
        return frozenset(selection)
    stored = p6.p6_activity_field_values(principal_id, run, None)
    return default_capture_keys() | {str(row["field_key"]) for row in stored}


def _extra_calendars(
    p6: ScheduleP6Repository,
    principal_id: str,
    project_id: str,
    references: Sequence[Mapping[str, Any]],
) -> tuple[P6SnapshotCalendar, ...]:
    """Section 11.5: any imported P6 calendar of the same Project the caller owns."""
    found: list[P6SnapshotCalendar] = []
    for reference in references:
        other = p6.p6_publication(principal_id, str(reference["publication_id"]))
        if (
            other is None
            or other.project_id != project_id
            or other.status != _COMPLETE
            or other.accepted_parser_run_id is None
        ):
            # Absent, foreign, another Project's or not complete read alike.
            raise InvalidRequestError(SafeDetail.CALENDAR)
        rows = p6.p6_calendar_rows(
            principal_id,
            other.accepted_parser_run_id,
            calendar_id=int(reference["calendar_id"]),
            offset=0,
            limit=1,
        )
        if not rows:
            raise InvalidRequestError(SafeDetail.CALENDAR)
        found.append(_calendar(rows[0]))
    return tuple(found)


def build_p6_snapshot(
    p6: ScheduleP6Repository,
    principal_id: str,
    publication_id: str,
    options: Mapping[str, Any],
) -> P6Snapshot:
    """Read the accepted run, resolve the options and map it (one read transaction)."""
    publication = p6.p6_publication(principal_id, publication_id)
    if publication is None or publication.accepted_parser_run_id is None:
        raise ConflictError(SafeDetail.STATUS)
    run = publication.accepted_parser_run_id
    project = p6.p6_project_block(principal_id, run)
    if project is None:  # pragma: no cover - a complete run has its project row
        raise InternalError()
    include = tuple(str(key) for key in options.get("include_fields") or ())
    if include:
        captured = _capture_keys(p6, principal_id, publication, run)
        if any(
            key not in captured or not is_captured_field_key(key) or is_personal_key(key)
            for key in include
        ):
            raise InvalidRequestError(SafeDetail.FIELD_KEY)
    values: dict[str, dict[str, CapturedValue]] = {}
    for row in p6.p6_activity_field_values(principal_id, run, include) if include else ():
        if row["ordinal"] != 0 or row["activity_id"] is None:
            continue  # a repeated (code) value travels by its first ordinal
        values.setdefault(str(row["activity_id"]), {})[str(row["field_key"])] = _captured(row)
    request = P6SnapshotRequest(
        calendars=_extra_calendars(
            p6, principal_id, publication.project_id, options.get("calendars") or ()
        ),
        default_calendar=options.get("default_calendar"),
        calendar_map=dict(options.get("calendar_map") or {}),
        include_fields=include,
    )
    calendars = p6.p6_calendar_rows(
        principal_id, run, calendar_id=None, offset=0, limit=_CALENDAR_LIMIT
    )
    activities = p6.p6_activity_rows(principal_id, run, offset=0, limit=MAX_ACTIVITIES + 1)
    relationships = p6.p6_relationship_rows(
        principal_id, run, offset=0, limit=MAX_RELATIONSHIPS + 1
    )
    refusal: P6SnapshotRefusal | None = None
    snapshot: P6Snapshot | None = None
    try:
        snapshot = snapshot_from_p6(
            publication_id=publication_id,
            project=_project(project),
            calendars=tuple(_calendar(row) for row in calendars),
            activities=tuple(
                _activity(row, values.get(str(row["activity_id"]), {})) for row in activities
            ),
            relationships=tuple(_relationship(row) for row in relationships),
            request=request,
        )
    except P6SnapshotRefusalError as refused:
        refusal = refused.reason
    if refusal is not None:
        raise _refusal(refusal)
    if snapshot is None:  # pragma: no cover
        raise InternalError()
    return snapshot


def p6_snapshot_report_shape(report: P6SnapshotReport) -> dict[str, object]:
    """Section 11.5: every count, the unmodelled settings, the outrun standard calendars."""
    return {
        "counts": dict(report.counts),
        "unmodelled_settings": list(report.unmodelled_settings),
        "standard_calendar_horizon_exceeded": list(report.standard_calendar_horizon_exceeded),
    }
