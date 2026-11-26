"""P6 XER S7-4a: the selection write and the 5 P6 reads' behaviour.

Contract `docs/architecture/schedule-xer-import-contract.md` sections 7.1-7.7
and 10.1-10.6 under ADR-023. `ApplicationService` asks the P6 switch first
(`unsupported` before anything is read), re-checks a remote read grant, and
hands the authorized request here; everything below runs on the P6 unit of
work, scoped to the acting Principal.

* **`schedule_p6_fields.set_captured`** appends one event to the Series'
  capture chain under a compare-and-swap on `expected_sequence`
  (`conflict(SEQUENCE)`), with the section 7.7 caps; it applies from the
  Series' next import (the admission records the event in force). The write
  is idempotent without a ledger table (no migration in this slice): the
  chain *is* the arbitration. A retry of the same request -- same Series,
  keys, `include_personal`, `expected_sequence` and writer -- finds the event
  it appended at `expected_sequence + 1` and replays it (`created: false`);
  anything else meets the compare-and-swap.
* **The reads** serve one *complete* P6 publication (another status is
  `conflict(STATUS)`), or a Stable Activity's complete P6 publications, under
  the S5 disclosure with the P6 trust basis (`p6_xer_v1` and the catalogue
  version), offset cursors bound to the request, and the section 7.7 filter
  and sort grammar. A captured `personal` field is served only to a caller
  holding a grant on `schedule_p6_field_values.list` (a local caller holds
  every grant) and only from a publication whose selection carried
  `include_personal`; naming one otherwise is `invalid_request(FIELD_KEY)`.
* **Never served**: the workspace path, the snapshot bytes, `clndr_data`,
  the ERMHDR user fields and exception text -- no method here reads them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from my_pa.application.authorization import Authorization
from my_pa.application.commands import (
    ListScheduleP6Activities,
    ListScheduleP6AvailableFields,
    ListScheduleP6Calendars,
    ListScheduleP6FieldValues,
    ListScheduleP6Relationships,
    SetScheduleP6CapturedFields,
)
from my_pa.application.errors import (
    ConflictError,
    InternalError,
    InvalidRequestError,
    NotFoundError,
    RateLimitedError,
    SafeDetail,
)
from my_pa.application.lineage_authority import lineage_write_provenance
from my_pa.application.schedules import P6_READ_TRUST_BASIS, ScheduleAnswer, schedule_disclosure
from my_pa.contracts.ports import ScheduleP6Repository, ScheduleP6UnitOfWork
from my_pa.contracts.v1.disclosure import Truncation
from my_pa.domain.identity.operation import Capability
from my_pa.domain.schedule import SchedulePublicationStatus
from my_pa.domain.schedule.cursor import (
    DEFAULT_SCHEDULE_PAGE_SIZE,
    ScheduleCursorError,
    ScheduleCursorOrder,
    decode_schedule_cursor,
    encode_schedule_cursor,
    schedule_cursor_binding,
)
from my_pa.domain.schedule.p6.catalogue import (
    CATALOGUE,
    TABLE_ENTITY,
    CatalogueField,
    EntityKind,
)
from my_pa.domain.schedule.p6_reads import (
    MAX_P6_CAPTURE_EVENTS,
    P6FieldObservation,
    P6PublicationRef,
    P6SeriesState,
    entity_kind_of,
    is_personal_key,
    is_selectable_catalogued_key,
    p6_included_fields,
    p6_predicates,
    p6_sort,
    value_type_of,
)

__all__ = [
    "ScheduleP6Reads",
    "p6_activity_shape",
    "p6_publication_block",
    "p6_value",
]

_COMPLETE: Final = SchedulePublicationStatus.COMPLETE.value
#: Section 10.5: a calendar carries at most this many exceptions inline.
_INLINE_EXCEPTIONS: Final = 100
_NO_TRUNCATION: Final = Truncation()
#: The catalogue's selectable keys (section 7.2) and their records.
_SELECTABLE: Final[Mapping[str, CatalogueField]] = {
    field.field_key: field for field in CATALOGUE if is_selectable_catalogued_key(field.field_key)
}
#: Section 7.2: the catalogue's default-captured keys (O+), the defaults with no selection.
_DEFAULT_KEYS: Final = frozenset(key for key, field in _SELECTABLE.items() if field.default_capture)
_RELATIONSHIP_TYPE_PREFIX: Final = "PR_"


# ---- value rendering (section 10.5) ---------------------------------------------------


def _number(value: Decimal | int | None) -> str | None:
    if value is None:
        return None
    number = Decimal(value)
    rendered = format(number.normalize(), "f")
    return "0" if rendered in ("-0", "") else rendered


def _instant(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="minutes" if value.second == 0 else "seconds")


def _hhmm(minutes: object) -> str:
    if type(minutes) is not int or not 0 <= minutes <= 1440:
        raise InternalError()
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _intervals(pairs: object) -> list[list[str]]:
    if not isinstance(pairs, list):
        raise InternalError()
    return [[_hhmm(pair[0]), _hhmm(pair[1])] for pair in pairs]


def p6_value(row: Mapping[str, object]) -> tuple[str, object]:
    """One stored value as `(value_type, value)`: numbers as text, times ISO local."""
    if row["value_number"] is not None:
        return "number", _number(row["value_number"])  # type: ignore[arg-type]
    if row["value_ts"] is not None:
        return "ts", _instant(row["value_ts"])  # type: ignore[arg-type]
    if row["value_flag"] is not None:
        return "flag", bool(row["value_flag"])
    return "text", row["value_text"]


def _fields_of(rows: Sequence[Mapping[str, object]]) -> dict[int, dict[str, object]]:
    """Entity id -> `{field_key: value}` (a list when the key repeats by ordinal)."""
    found: dict[int, dict[str, list[object]]] = {}
    for row in rows:
        entity = int(row["entity_p6_id"])  # type: ignore[call-overload]
        found.setdefault(entity, {}).setdefault(str(row["field_key"]), []).append(p6_value(row)[1])
    return {
        entity: {key: values[0] if len(values) == 1 else values for key, values in keyed.items()}
        for entity, keyed in found.items()
    }


def _constraint(kind: object, day: object) -> dict[str, object]:
    return {"type": kind, "date": _instant(day)}  # type: ignore[arg-type]


def p6_activity_shape(row: Mapping[str, Any], fields: Mapping[str, object]) -> dict[str, Any]:
    """Section 10.5 `activity`."""
    return {
        "schedule_activity_id": row["schedule_activity_id"],
        "activity_id": row["activity_id"],
        "name": row["activity_name"],
        "kind": row["kind"],
        "task_type": row["task_type"],
        "status": row["status_code"],
        "wbs_path": list(row["wbs_path"]),
        "calendar_id": row["p6_calendar_id"],
        "original_hours": _number(row["original_hours"]),
        "remaining_hours": _number(row["remaining_hours"]),
        "start": _instant(row["start_at"]),
        "finish": _instant(row["finish_at"]),
        "early_start": _instant(row["early_start"]),
        "early_finish": _instant(row["early_finish"]),
        "late_start": _instant(row["late_start"]),
        "late_finish": _instant(row["late_finish"]),
        "planned_start": _instant(row["planned_start"]),
        "planned_finish": _instant(row["planned_finish"]),
        "actual_start": _instant(row["actual_start"]),
        "actual_finish": _instant(row["actual_finish"]),
        "total_float_hours": _number(row["total_float_hours"]),
        "free_float_hours": _number(row["free_float_hours"]),
        "constraint": _constraint(row["constraint_type"], row["constraint_date"]),
        "constraint2": _constraint(row["constraint2_type"], row["constraint2_date"]),
        "physical_pct": _number(row["physical_pct"]),
        "duration_type": row["duration_type"],
        "fields": dict(fields),
    }


def _relationship_shape(row: Mapping[str, Any], fields: Mapping[str, object]) -> dict[str, Any]:
    kind = str(row["relationship_type"])
    return {
        "pred_activity_id": row["pred_activity_id"],
        "succ_activity_id": row["succ_activity_id"],
        "type": kind.removeprefix(_RELATIONSHIP_TYPE_PREFIX),
        "lag_hours": _number(row["lag_hours"]),
        "is_external": bool(row["is_external"]),
        "fields": dict(fields),
    }


def _calendar_shape(
    row: Mapping[str, Any],
    fields: Mapping[str, object],
    exceptions: Sequence[Mapping[str, Any]],
    *,
    truncated: bool,
) -> dict[str, Any]:
    week = row["week"]
    return {
        "calendar_id": row["p6_calendar_id"],
        "name": row["name"],
        "type": row["calendar_type"],
        "is_default": row["is_default"],
        "base_calendar_id": row["base_p6_calendar_id"],
        "hours_per_day": _number(row["hours_per_day"]),
        "week": [_intervals(day) for day in week] if isinstance(week, list) else [],
        "exception_count": row["exception_count"],
        "exceptions": [
            {"date": item["date"], "intervals": _intervals(item["intervals"])}
            for item in exceptions
        ],
        "exceptions_truncated": truncated,
        "fields": dict(fields),
    }


#: The PROJECT/SCHEDOPTIONS settings `schedule_publications.read` serves in `p6`.
_P6_SETTINGS: Final = (
    "planned_start",
    "must_finish_by",
    "scheduled_finish",
    "critical_float_hours",
    "critical_path_type",
    "next_data_date",
    "lag_calendar",
    "retained_logic",
    "progress_override",
    "float_type",
    "open_ends_critical",
    "external_dependencies",
    "use_expected_finish",
    "ss_lag_from_early_start",
    "float_from_project_finish",
    "default_p6_calendar_id",
)


def _setting(value: object) -> object:
    if isinstance(value, Decimal):
        return _number(value)
    if isinstance(value, datetime):
        return _instant(value)
    return value


def p6_publication_block(
    publication: P6PublicationRef, project: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Section 10.1: the additive `p6` block of `schedule_publications.read`.

    Project identity, export version and date, data date, settings and counts.
    Never the workspace path or an ERMHDR user field (neither is read).
    """
    block: dict[str, Any] = {
        "source_format": publication.source_format,
        "capture_event_id": publication.capture_event_id,
    }
    if project is None:
        return {**block, "project": None}
    return {
        **block,
        "project": {
            "p6_project_id": project["p6_project_id"],
            "short_name": project["project_short_name"],
            "guid": project["project_guid"],
            "name": project["project_name"],
        },
        "export_version": project["export_version"],
        "export_date": None
        if project["export_date"] is None
        else project["export_date"].isoformat(),
        "encoding": project["encoding"],
        "catalogue_version": project["catalogue_version"],
        "data_date": _instant(project["data_date"]),
        "settings": {name: _setting(project[name]) for name in _P6_SETTINGS},
        "counts": dict(project["counts"]),
    }


# ---- paging (an offset bound to the request, section 10.3) ----------------------------


def _plain(value: object) -> object:
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    return value


class _Offset:
    """One request's page size, binding and resume offset (the S5 cursor, offset order)."""

    def __init__(self, authorization: Authorization, command: Any) -> None:  # noqa: ANN401
        self.page_size: int = command.page_size or DEFAULT_SCHEDULE_PAGE_SIZE
        self._issued_at = authorization.at
        request = {
            name: _plain(value)
            for name, value in asdict(command).items()
            if name not in {"cursor", "page_size"}
        }
        self._binding = schedule_cursor_binding(
            capability=command.capability.value,
            principal_id=authorization.principal.principal_id,
            purpose=authorization.purpose.value,
            request=request,
            page_size=self.page_size,
            order=ScheduleCursorOrder.SCENARIO_CONTENT,
        )
        self.offset = 0
        if command.cursor is not None:
            refused = False
            try:
                position = decode_schedule_cursor(
                    command.cursor,
                    binding=self._binding,
                    order=ScheduleCursorOrder.SCENARIO_CONTENT,
                    now=authorization.at,
                ).position
            except ScheduleCursorError:
                refused = True
            if refused:
                raise ConflictError(SafeDetail.CURSOR)
            self.offset = int(position[0])  # type: ignore[arg-type]

    def truncation(self, more: bool) -> Truncation:
        if not more:
            return _NO_TRUNCATION
        return Truncation(
            is_truncated=True,
            reason="page_size_reached",
            next_cursor=encode_schedule_cursor(
                binding=self._binding,
                order=ScheduleCursorOrder.SCENARIO_CONTENT,
                position=(self.offset + self.page_size,),
                issued_at=self._issued_at,
            ),
        )


def _personal_holder(authorization: Authorization) -> bool:
    """Section 10.4: a local caller, or a remote one granted `field_values.list`."""
    grants = authorization.capability_grants
    return grants is None or any(
        capability is Capability.SCHEDULE_P6_FIELD_VALUES_LIST for capability, _ in grants
    )


def _named_keys(command: Any) -> frozenset[str]:  # noqa: ANN401 - a P6 read command
    keys: set[str] = set()
    fields = p6_included_fields(getattr(command, "fields", None))
    keys.update(fields or ())
    keys.update(
        predicate.field_key for predicate in p6_predicates(getattr(command, "filter", None))
    )
    sort = p6_sort(getattr(command, "sort", None))
    if sort is not None:
        keys.add(sort.field_key)
    return frozenset(keys)


def _require_visible(
    authorization: Authorization,
    command: Any,  # noqa: ANN401 - a P6 read command
    publications: Sequence[P6PublicationRef],
) -> bool:
    """Whether personal values are served here; naming one that is not is refused."""
    visible = _personal_holder(authorization) and all(
        publication.include_personal for publication in publications
    )
    if not visible and any(is_personal_key(key) for key in _named_keys(command)):
        raise InvalidRequestError(SafeDetail.FIELD_KEY)
    return visible


def _disclosure(
    authorization: Authorization,
    publications: Sequence[P6PublicationRef],
    truncation: Truncation = _NO_TRUNCATION,
) -> Any:  # noqa: ANN401 - a Disclosure
    return schedule_disclosure(
        publications=[
            (None, SchedulePublicationStatus(publication.status)) for publication in publications
        ],
        observed_at=authorization.at,
        truncation=truncation,
        trust_basis=P6_READ_TRUST_BASIS,
    )


class ScheduleP6Reads:
    """`schedule_p6_fields.*` and the 4 P6 row reads on the P6 unit of work."""

    def __init__(self, unit_of_work: Callable[[], ScheduleP6UnitOfWork]) -> None:
        self._unit_of_work = unit_of_work

    # ---- the root publication -----------------------------------------------------------

    @staticmethod
    def _complete(
        repository: ScheduleP6Repository, principal_id: str, publication_id: str
    ) -> P6PublicationRef:
        found = repository.p6_publication(principal_id, publication_id)
        if found is None:
            raise NotFoundError(SafeDetail.PUBLICATION_ID)
        if found.status != _COMPLETE or found.accepted_parser_run_id is None:
            raise ConflictError(SafeDetail.STATUS)
        return found

    # ---- schedule_p6_fields.available (sections 7.1, 7.4, 10.5) ---------------------------

    def available(
        self, authorization: Authorization, command: ListScheduleP6AvailableFields
    ) -> ScheduleAnswer:
        paging = _Offset(authorization, command)
        principal_id = authorization.principal.principal_id
        with self._unit_of_work() as work:
            series = work.p6.p6_series_state(principal_id, command.series_id)
            if series is None:
                raise NotFoundError(SafeDetail.SERIES_ID)
            if series.holds_pdf:
                raise ConflictError(SafeDetail.SERIES_FORMAT)
            publications = work.p6.p6_series_publications(principal_id, command.series_id)
            observations = work.p6.p6_field_observations(principal_id, command.series_id)
        rows = _registry(series, observations)
        page = rows[paging.offset : paging.offset + paging.page_size]
        complete = [item for item in publications if item.status == _COMPLETE]
        return ScheduleAnswer(
            payload={
                "series_id": command.series_id,
                "selection": _selection_state(series),
                "fields": page,
                "page_size": paging.page_size,
            },
            disclosure=_disclosure(
                authorization,
                complete,
                paging.truncation(paging.offset + paging.page_size < len(rows)),
            ),
        )

    # ---- schedule_p6_fields.set_captured (sections 7.2, 10.3) -----------------------------

    def set_captured(
        self, authorization: Authorization, command: SetScheduleP6CapturedFields
    ) -> ScheduleAnswer:
        principal_id = authorization.principal.principal_id
        keys = command.selected_keys()
        provenance = lineage_write_provenance(authorization, user_directed=False)
        written = {
            "authority_class": provenance.authority_class.value,
            "decision_channel": provenance.decision_channel.value,
            "asserting_client_id": provenance.asserting_client_id,
            "acceptance_basis": provenance.acceptance_basis.value,
            "user_directed_claim": provenance.user_directed_claim,
        }
        if any(is_personal_key(key) for key in keys) and not command.include_personal:
            raise InvalidRequestError(SafeDetail.INCLUDE_PERSONAL)
        with self._unit_of_work() as work:
            series = work.p6.p6_series_state(principal_id, command.series_id, for_update=True)
            if series is None:
                raise NotFoundError(SafeDetail.SERIES_ID)
            if series.holds_pdf:
                raise ConflictError(SafeDetail.SERIES_FORMAT)
            current = 0 if series.last_event is None else series.last_event.sequence
            if current != command.expected_sequence:
                replayed = work.p6.p6_capture_event(
                    principal_id, command.series_id, command.expected_sequence + 1
                )
                if (
                    replayed is not None
                    and replayed.field_keys == keys
                    and replayed.include_personal == command.include_personal
                    and replayed.decision_channel == written["decision_channel"]
                    and replayed.asserting_client_id == written["asserting_client_id"]
                ):
                    return self._capture_answer(authorization, command, replayed, created=False)
                raise ConflictError(SafeDetail.SEQUENCE)
            if current >= MAX_P6_CAPTURE_EVENTS:
                raise RateLimitedError(SafeDetail.SEQUENCE)
            observations = work.p6.p6_field_observations(principal_id, command.series_id)
            available = set(_SELECTABLE) | {
                item.field_key for item in observations if not item.catalogued
            }
            if series.last_event is not None:
                available |= set(series.last_event.field_keys)
            if any(key not in available for key in keys):
                raise InvalidRequestError(SafeDetail.FIELD_KEY)
            appended = work.p6.append_p6_capture_event(
                principal_id,
                series,
                sequence=current + 1,
                field_keys=keys,
                include_personal=command.include_personal,
                provenance=written,
            )
            if appended is None:
                # A concurrent selection took this sequence first.
                raise ConflictError(SafeDetail.SEQUENCE)
        return self._capture_answer(authorization, command, appended, created=True)

    @staticmethod
    def _capture_answer(
        authorization: Authorization,
        command: SetScheduleP6CapturedFields,
        event: Any,  # noqa: ANN401 - a P6CaptureEvent
        *,
        created: bool,
    ) -> ScheduleAnswer:
        return ScheduleAnswer(
            payload={
                "series_id": command.series_id,
                "event_id": event.event_id,
                "sequence": event.sequence,
                "field_key_count": len(event.field_keys),
                "field_keys": list(event.field_keys),
                "include_personal": event.include_personal,
                "catalogue_version": event.catalogue_version,
                "created": created,
                "applies_from": "next_import",
            },
            disclosure=_disclosure(authorization, ()),
        )

    # ---- schedule_p6_activities.list (sections 7.5, 10.5) ---------------------------------

    def activities(
        self, authorization: Authorization, command: ListScheduleP6Activities
    ) -> ScheduleAnswer:
        paging = _Offset(authorization, command)
        principal_id = authorization.principal.principal_id
        fields = p6_included_fields(command.fields) or ()
        with self._unit_of_work() as work:
            publication = self._complete(work.p6, principal_id, command.publication_id)
            _require_visible(authorization, command, (publication,))
            run = str(publication.accepted_parser_run_id)
            rows = work.p6.p6_activity_rows(
                principal_id,
                run,
                predicates=p6_predicates(command.filter),
                sort=p6_sort(command.sort),
                offset=paging.offset,
                limit=paging.page_size + 1,
            )
            page = rows[: paging.page_size]
            values = _fields_of(
                work.p6.p6_entity_values(
                    principal_id,
                    run,
                    EntityKind.ACTIVITY.value,
                    [int(row["p6_task_id"]) for row in page],  # type: ignore[call-overload]
                    fields,
                )
            )
        return ScheduleAnswer(
            payload={
                "publication_id": command.publication_id,
                "activities": [
                    p6_activity_shape(row, values.get(int(row["p6_task_id"]), {}))  # type: ignore[call-overload]
                    for row in page
                ],
                "page_size": paging.page_size,
            },
            disclosure=_disclosure(
                authorization, (publication,), paging.truncation(len(rows) > paging.page_size)
            ),
        )

    # ---- schedule_p6_relationships.list (section 10.5) ------------------------------------

    def relationships(
        self, authorization: Authorization, command: ListScheduleP6Relationships
    ) -> ScheduleAnswer:
        paging = _Offset(authorization, command)
        principal_id = authorization.principal.principal_id
        fields = p6_included_fields(command.fields) or ()
        with self._unit_of_work() as work:
            publication = self._complete(work.p6, principal_id, command.publication_id)
            _require_visible(authorization, command, (publication,))
            run = str(publication.accepted_parser_run_id)
            rows = work.p6.p6_relationship_rows(
                principal_id, run, offset=paging.offset, limit=paging.page_size + 1
            )
            page = rows[: paging.page_size]
            values = _fields_of(
                work.p6.p6_entity_values(
                    principal_id,
                    run,
                    EntityKind.RELATIONSHIP.value,
                    [int(row["p6_relationship_id"]) for row in page],  # type: ignore[call-overload]
                    fields,
                )
            )
        return ScheduleAnswer(
            payload={
                "publication_id": command.publication_id,
                "relationships": [
                    _relationship_shape(row, values.get(int(row["p6_relationship_id"]), {}))  # type: ignore[call-overload]
                    for row in page
                ],
                "page_size": paging.page_size,
            },
            disclosure=_disclosure(
                authorization, (publication,), paging.truncation(len(rows) > paging.page_size)
            ),
        )

    # ---- schedule_p6_calendars.list (section 10.5) ----------------------------------------

    def calendars(
        self, authorization: Authorization, command: ListScheduleP6Calendars
    ) -> ScheduleAnswer:
        paging = _Offset(authorization, command)
        principal_id = authorization.principal.principal_id
        fields = p6_included_fields(command.fields) or ()
        with self._unit_of_work() as work:
            publication = self._complete(work.p6, principal_id, command.publication_id)
            _require_visible(authorization, command, (publication,))
            run = str(publication.accepted_parser_run_id)
            if command.calendar_id is None:
                rows = work.p6.p6_calendar_rows(
                    principal_id,
                    run,
                    calendar_id=None,
                    offset=paging.offset,
                    limit=paging.page_size + 1,
                )
            else:
                rows = work.p6.p6_calendar_rows(
                    principal_id, run, calendar_id=command.calendar_id, offset=0, limit=1
                )
                if not rows:
                    raise NotFoundError(SafeDetail.CALENDAR_ID)
            page = rows[: paging.page_size]
            values = _fields_of(
                work.p6.p6_entity_values(
                    principal_id,
                    run,
                    EntityKind.CALENDAR.value,
                    [int(row["p6_calendar_id"]) for row in page],  # type: ignore[call-overload]
                    fields,
                )
            )
        rendered: list[dict[str, Any]] = []
        more = len(rows) > paging.page_size
        for row in page:
            stored = row["exceptions"]
            exceptions = stored if isinstance(stored, list) else []
            if command.calendar_id is None:
                shown = exceptions[:_INLINE_EXCEPTIONS]
                truncated = len(exceptions) > _INLINE_EXCEPTIONS
            else:
                # The one named calendar: its exceptions are what the cursor pages.
                shown = exceptions[paging.offset : paging.offset + paging.page_size]
                truncated = paging.offset + paging.page_size < len(exceptions)
                more = truncated
            rendered.append(
                _calendar_shape(
                    row,
                    values.get(int(row["p6_calendar_id"]), {}),  # type: ignore[call-overload]
                    shown,
                    truncated=truncated,
                )
            )
        return ScheduleAnswer(
            payload={
                "publication_id": command.publication_id,
                "calendars": rendered,
                "page_size": paging.page_size,
            },
            disclosure=_disclosure(authorization, (publication,), paging.truncation(more)),
        )

    # ---- schedule_p6_field_values.list (sections 7.3, 7.5, 10.4, 10.5) ---------------------

    def field_values(
        self, authorization: Authorization, command: ListScheduleP6FieldValues
    ) -> ScheduleAnswer:
        paging = _Offset(authorization, command)
        principal_id = authorization.principal.principal_id
        fields = p6_included_fields(command.fields)
        kind = entity_kind_of(command.entity_kind)
        with self._unit_of_work() as work:
            if command.publication_id is not None:
                publications: tuple[P6PublicationRef, ...] = (
                    self._complete(work.p6, principal_id, command.publication_id),
                )
            else:
                publications = work.p6.p6_stable_activity_runs(
                    principal_id, str(command.schedule_activity_id)
                )
                if not publications:
                    raise NotFoundError(SafeDetail.SCHEDULE_ACTIVITY_ID)
            visible = _require_visible(authorization, command, publications)
            rows = work.p6.p6_value_rows(
                principal_id,
                parser_run_ids=[str(item.accepted_parser_run_id) for item in publications],
                schedule_activity_id=command.schedule_activity_id,
                entity_kind=None if kind is None else kind.value,
                field_keys=fields,
                withheld_keys=() if visible else _PERSONAL_KEYS,
                predicates=p6_predicates(command.filter),
                sort=p6_sort(command.sort),
                offset=paging.offset,
                limit=paging.page_size + 1,
            )
        page = rows[: paging.page_size]
        return ScheduleAnswer(
            payload={
                "publication_id": command.publication_id,
                "schedule_activity_id": command.schedule_activity_id,
                "values": [_value_shape(row) for row in page],
                "page_size": paging.page_size,
            },
            disclosure=_disclosure(
                authorization, publications, paging.truncation(len(rows) > paging.page_size)
            ),
        )


_PERSONAL_KEYS: Final = tuple(sorted(field.field_key for field in CATALOGUE if field.personal))


def _value_shape(row: Mapping[str, Any]) -> dict[str, Any]:
    """Section 10.5 `field value` (plus its publication, for the cross-version read)."""
    value_type, value = p6_value(row)
    kind = str(row["entity_kind"])
    reference = row["activity_id"] if kind == EntityKind.ACTIVITY.value else row["entity_p6_id"]
    return {
        "publication_id": row["publication_id"],
        "entity_kind": kind,
        "entity_ref": reference,
        "field_key": row["field_key"],
        "ordinal": row["ordinal"],
        "value_type": value_type,
        "value": value,
        "code_path": list(row["code_path"]) if row["code_path"] else None,
    }


def _selection_state(series: P6SeriesState) -> dict[str, Any]:
    event = series.last_event
    if event is None:
        return {"sequence": 0, "event_id": None, "include_personal": False, "defaults": True}
    return {
        "sequence": event.sequence,
        "event_id": event.event_id,
        "include_personal": event.include_personal,
        "defaults": False,
    }


def _ratio(observation: P6FieldObservation | None) -> str | None:
    if observation is None or observation.records == 0:
        return None
    return format(
        (Decimal(observation.nonempty) / Decimal(observation.records)).quantize(Decimal("0.001")),
        "f",
    )


def _registry(
    series: P6SeriesState, observations: Sequence[P6FieldObservation]
) -> list[dict[str, Any]]:
    """Section 7.1: the catalogue's selectable fields union the Series' observed fields.

    Captured: in the last event's keys, or -- with no selection yet -- a
    default (O+) catalogued key or any UDF / code key (section 7.2's default).
    """
    by_key = {item.field_key: item for item in observations}
    event = series.last_event

    def captured(key: str) -> bool:
        if event is not None:
            return key in event.field_keys
        return key in _DEFAULT_KEYS or key.startswith(("udf:", "code:"))

    rows: dict[str, dict[str, Any]] = {}
    for key, field in _SELECTABLE.items():
        observed = by_key.get(key)
        rows[key] = {
            "field_key": key,
            "entity_kind": field.entity_kind.value,
            "value_type": str(value_type_of(key) or "text"),
            "unit": None if field.unit in ("—", "") else field.unit,
            "tier": field.tier.value,
            "catalogued": True,
            "default_capture": field.default_capture,
            "captured": captured(key),
            "personal": field.personal,
            "observed": _observed(observed),
        }
    for item in observations:
        if item.field_key in rows or item.catalogued:
            continue
        table = item.source_table
        kind = item.entity_kind or (
            TABLE_ENTITY.get(table, EntityKind.PROJECT).value if table else None
        )
        rows[item.field_key] = {
            "field_key": item.field_key,
            "entity_kind": kind,
            "value_type": item.value_type or "text",
            "unit": None,
            "tier": item.tier,
            "catalogued": False,
            "default_capture": item.field_key.startswith(("udf:", "code:")),
            "captured": captured(item.field_key),
            "personal": False,
            "observed": _observed(item),
        }
    return [rows[key] for key in sorted(rows)]


def _observed(item: P6FieldObservation | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "imports_seen": item.imports_seen,
        "last_seen_publication_id": item.last_seen_publication_id,
        "nonempty_ratio": _ratio(item),
    }
