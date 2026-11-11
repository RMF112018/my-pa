"""CPM Workbench S5b-2: the 7 Schedule capabilities' behaviour.

Contract: `docs/architecture/cpm-workbench-worker-capabilities-contract.md`
sections 3.5-3.11 (R2 sections 9, 10, 29, 30, 31.1, 32). `ApplicationService`
asks the switch (and, for a read, the remote grant re-check) and then hands the
authorized request here; everything below runs on the dedicated
`ScheduleUnitOfWork`, never on the shared unit of work.

* **Import** (section 3.6) is attested-local only (E-12): a remote composition is
  `unsupported` (E-10), an unattested local caller -- stdio MCP included -- is
  `denied` by `attested_lineage_authority`, both before any read or write. The
  S5b-1 admission transaction then does every check and the one enqueue.
* **Reads** (section 3.9) decode their cursor before the root lookup (R7-F10),
  answer an absent and another Principal's root identically, serve only
  accepted runs of complete or partial publications (U-03), count issues per
  RR1-I01, and never return a `schedule_activities.created_at`.
* **Changes** (section 3.10) recompute the delta on every page from immutable
  terminal inputs; the cursor position is a bare offset (E-08).

Every answer carries `schedule_disclosure` (section 3.8): coverage of the
publications the answer references, never of the enrolled corpus.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

from my_pa.application.authorization import Authorization
from my_pa.application.commands import (
    ImportSchedulePublication,
    ListScheduleActivities,
    ListScheduleChanges,
    ListSchedulePublications,
    ListScheduleSeries,
    ReadScheduleActivityHistory,
    ReadSchedulePublication,
)
from my_pa.application.errors import (
    ApplicationError,
    ConflictError,
    DeniedError,
    InternalError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
    UnsupportedError,
)
from my_pa.application.lineage_authority import attested_lineage_authority
from my_pa.contracts.ports import (
    ScheduleAdmissionRejectedError,
    ScheduleRepository,
    ScheduleUnitOfWork,
)
from my_pa.contracts.v1.disclosure import (
    Coverage,
    CoverageState,
    Disclosure,
    Freshness,
    FreshnessState,
    Scope,
    SourceReference,
    Truncation,
    Trust,
)
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.provenance import TrustLevel
from my_pa.domain.schedule import (
    ScheduleActivityObservation,
    ScheduleActivityRowView,
    ScheduleAdmissionOutcome,
    ScheduleAdmissionRefusal,
    ScheduleDateCell,
    ScheduleDurationCell,
    ScheduleParserRun,
    SchedulePublication,
    SchedulePublicationDetail,
    SchedulePublicationRole,
    SchedulePublicationStatus,
    SchedulePublicationSummary,
    ScheduleRowType,
    ScheduleSeriesSummary,
    ScheduleSourceBinding,
    normalized_box_strings,
    schedule_import_request_digest,
)
from my_pa.domain.schedule.compare import (
    DELTA_ALGORITHM_VERSION,
    ScheduleActivityIdentity,
    ScheduleChange,
    ScheduleChangeKind,
    ScheduleChangeSide,
    ScheduleHierarchySide,
    compare_publications,
    unmatched_target_activity_ids,
)
from my_pa.domain.schedule.cursor import (
    DEFAULT_SCHEDULE_PAGE_SIZE,
    ScheduleCursorError,
    ScheduleCursorOrder,
    SchedulePosition,
    decode_schedule_cursor,
    encode_schedule_cursor,
    schedule_cursor_binding,
)

__all__ = [
    "SCHEDULE_IMPORT_TRUST_BASIS",
    "SCHEDULE_READ_TRUST_BASIS",
    "ScheduleAnswer",
    "ScheduleApplication",
    "schedule_disclosure",
    "schedule_import_disclosure",
]

#: Section 3.8: what a read's facts rest on -- the parser and its profile.
SCHEDULE_READ_TRUST_BASIS: Final = ("cpm-workbench-full-parser", "p6_full_v1")
#: Section 3.8: an admission rests on the admission checks, not on a parse.
SCHEDULE_IMPORT_TRUST_BASIS: Final = ("schedule_admission",)
_TRUNCATION_REASON: Final = "page_size_reached"
_NO_TRUNCATION: Final = Truncation()
_SERVED: Final = frozenset({SchedulePublicationStatus.COMPLETE, SchedulePublicationStatus.PARTIAL})
_PARTIAL_STATES: Final = frozenset(
    {
        CoverageState.PARTIALLY_PROCESSED,
        CoverageState.QUARANTINED,
        CoverageState.UNSUPPORTED,
        CoverageState.UNAVAILABLE,
        CoverageState.STALE,
    }
)
_DURATION_PLACES: Final = Decimal("0.001")

#: Section 3.5.3: each typed admission refusal and its public answer, as the
#: error class and its details (constructed by name, never dispatched through a
#: table of callables).
_REFUSALS: Final[
    Mapping[ScheduleAdmissionRefusal, tuple[type[ApplicationError], tuple[SafeDetail, ...]]]
] = {
    ScheduleAdmissionRefusal.PROJECT_NOT_FOUND: (NotFoundError, (SafeDetail.PROJECT_ID,)),
    ScheduleAdmissionRefusal.SERIES_NOT_FOUND: (NotFoundError, (SafeDetail.SERIES_ID,)),
    ScheduleAdmissionRefusal.ENROLLMENT_NOT_FOUND: (NotFoundError, (SafeDetail.ENROLLMENT_ID,)),
    ScheduleAdmissionRefusal.SOURCE_OBJECT_NOT_ENROLLED: (
        NotFoundError,
        (SafeDetail.SOURCE_OBJECT_ID,),
    ),
    ScheduleAdmissionRefusal.SOURCE_VERSION_NOT_FOUND: (
        NotFoundError,
        (SafeDetail.SOURCE_VERSION_ID,),
    ),
    ScheduleAdmissionRefusal.UNSUPPORTED_MEDIA_TYPE: (
        UnsupportedError,
        (SafeDetail.SOURCE_VERSION_ID,),
    ),
    ScheduleAdmissionRefusal.MEDIA_TYPE_NOT_ENROLLED: (DeniedError, ()),
    ScheduleAdmissionRefusal.SOURCE_TOO_LARGE: (UnsupportedError, (SafeDetail.MAX_BYTES,)),
    ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_FOUND: (
        NotFoundError,
        (SafeDetail.SUPERSEDES_PUBLICATION_ID,),
    ),
    ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_TERMINAL: (
        ConflictError,
        (SafeDetail.SUPERSEDES_PUBLICATION_ID,),
    ),
    ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_SAME_SOURCE_VERSION: (
        InvalidRequestError,
        (SafeDetail.SUPERSEDES_PUBLICATION_ID,),
    ),
    ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_HAS_SUCCESSOR: (
        ConflictError,
        (SafeDetail.SUPERSEDES_PUBLICATION_ID,),
    ),
    ScheduleAdmissionRefusal.IDEMPOTENCY_KEY_CONFLICT: (
        ConflictError,
        (SafeDetail.IDEMPOTENCY_KEY,),
    ),
    ScheduleAdmissionRefusal.SOURCE_VERSION_CONFLICT: (
        ConflictError,
        (SafeDetail.SOURCE_VERSION_ID,),
    ),
}


def _refusal_error(refusal: ScheduleAdmissionRefusal) -> ApplicationError:
    error_class, details = _REFUSALS[refusal]
    return error_class(*details)


@dataclass(frozen=True, slots=True)
class ScheduleAnswer:
    """One Schedule capability's payload and the disclosure that must accompany it."""

    payload: dict[str, Any]
    disclosure: Disclosure


# ---- disclosure (section 3.8) ------------------------------------------------------


def _coverage(statuses: Sequence[SchedulePublicationStatus]) -> Coverage:
    if not statuses:
        # R7-F08: an empty reference set is an ordinary answer, never `not_enrolled`.
        return Coverage(state=CoverageState.ELIGIBLE)
    processed = sum(1 for status in statuses if status in _SERVED)
    quarantined = sum(
        1 for status in statuses if status is SchedulePublicationStatus.REVIEW_REQUIRED
    )
    unsupported = sum(1 for status in statuses if status is SchedulePublicationStatus.FAILED)
    unique = set(statuses)
    if unique == {SchedulePublicationStatus.COMPLETE}:
        state = CoverageState.PROCESSED
    elif unique <= {SchedulePublicationStatus.QUEUED, SchedulePublicationStatus.PROCESSING}:
        state = CoverageState.QUEUED
    elif unique == {SchedulePublicationStatus.REVIEW_REQUIRED}:
        state = CoverageState.QUARANTINED
    elif unique == {SchedulePublicationStatus.FAILED}:
        state = CoverageState.UNSUPPORTED
    else:
        state = CoverageState.PARTIALLY_PROCESSED
    return Coverage(
        state=state,
        eligible=len(statuses),
        processed=processed,
        quarantined=quarantined,
        unsupported=unsupported,
    )


def schedule_disclosure(
    *,
    publications: Sequence[tuple[ScheduleSourceBinding, SchedulePublicationStatus]],
    observed_at: datetime,
    truncation: Truncation = _NO_TRUNCATION,
    trust_basis: tuple[str, ...] = SCHEDULE_READ_TRUST_BASIS,
) -> Disclosure:
    """The envelope of a Schedule answer over the publications it references.

    `publications` pairs each referenced publication's source binding with its
    effective status. Scope and source references name exactly those; the
    coverage counts them (section 3.8), and an empty set is `eligible` with
    every count 0.
    """
    coverage = _coverage([status for _, status in publications])
    bindings = [binding for binding, _ in publications]
    return Disclosure(
        scope=Scope(
            source_ids=tuple(sorted({binding.source_id for binding in bindings})),
            enrollment_ids=tuple(sorted({binding.enrollment_id for binding in bindings})),
        ),
        coverage=coverage,
        freshness=Freshness(
            observed_at=observed_at, state=FreshnessState.CURRENT_FOR_OBSERVED_VERSION
        ),
        trust=Trust(level=TrustLevel.SOURCE_BOUND_DERIVED, basis=trust_basis),
        truncation=truncation,
        source_references=tuple(
            SourceReference(source_id=s, source_object_id=o, version_id=v)
            for s, o, v in sorted(
                {
                    (binding.source_id, binding.source_object_id, binding.source_version_id)
                    for binding in bindings
                }
            )
        ),
        partial_result=coverage.state in _PARTIAL_STATES or truncation.is_truncated,
        classification=Classification.PRIVATE_LOCAL,
        cloud_eligible=False,
    )


def schedule_import_disclosure(
    *,
    binding: ScheduleSourceBinding,
    status: SchedulePublicationStatus,
    observed_at: datetime,
) -> Disclosure:
    """The import's envelope: its one source version, `queued` when just admitted."""
    return schedule_disclosure(
        publications=((binding, status),),
        observed_at=observed_at,
        trust_basis=SCHEDULE_IMPORT_TRUST_BASIS,
    )


# ---- payload rendering (section 3.5.2) -----------------------------------------------


def _instant(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _day(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _units(value: Decimal) -> str:
    return format(value.quantize(_DURATION_PLACES), "f")


def _duration(cell: ScheduleDurationCell) -> dict[str, Any]:
    return {
        "state": cell.state.value,
        "value": None if cell.value is None else _units(cell.value),
    }


def _date(cell: ScheduleDateCell) -> dict[str, Any]:
    return {"state": cell.state.value, "value": _day(cell.value), "marker": cell.marker}


def _path(path: tuple[str, ...] | None) -> list[str] | None:
    return None if path is None else list(path)


def _side(side: ScheduleChangeSide) -> object:
    match side:
        case ScheduleRowType():
            return side.value
        case None | str():
            return side
        case ScheduleActivityIdentity():
            return {"activity_name": side.activity_name, "row_type": side.row_type.value}
        case ScheduleDurationCell():
            return _duration(side)
        case ScheduleDateCell():
            return _date(side)
        case ScheduleHierarchySide():
            return {"state": side.state.value, "path": _path(side.path)}
        case tuple():
            return list(side)
    raise InternalError()  # pragma: no cover - the union is closed


def _change(change: ScheduleChange) -> dict[str, Any]:
    return {
        "schedule_activity_id": change.schedule_activity_id,
        "published_activity_id": change.published_activity_id,
        "change_kind": change.change_kind.value,
        "field": None if change.field is None else change.field.value,
        "before": _side(change.before),
        "after": _side(change.after),
        "delta_calendar_days": change.delta_calendar_days,
        "delta_source_units": (
            None if change.delta_source_units is None else _units(change.delta_source_units)
        ),
    }


def _publication_row(summary: SchedulePublicationSummary) -> dict[str, Any]:
    publication = summary.publication
    parser = summary.accepted_parser
    return {
        "publication_id": publication.publication_id,
        "publication_role": publication.publication_role.value,
        "baseline_kind": _value(publication.baseline_kind),
        "supersedes_publication_id": publication.supersedes_publication_id,
        "status": summary.effective_status.value,
        "persisted_status": publication.status.value,
        "published_schedule_title": publication.published_schedule_title,
        "data_date": _day(publication.data_date),
        "run_date": _day(publication.run_date),
        "admitted_at": _instant(publication.admitted_at),
        "completed_at": _instant(publication.completed_at),
        "page_count": publication.page_count,
        "row_count": publication.row_count,
        "activity_count": publication.activity_count,
        "ambiguous_row_count": publication.ambiguous_row_count,
        "issue_count": publication.issue_count,
        "parser_name": None if parser is None else parser.parser_name,
        "parser_version": None if parser is None else parser.parser_version,
        "profile_id": None if parser is None else parser.profile_id,
        "profile_version": None if parser is None else parser.profile_version,
        "operation_id": summary.operation_id,
    }


def _value(member: Any) -> str | None:  # noqa: ANN401 - an optional StrEnum member
    return None if member is None else str(member.value)


def _run(run: ScheduleParserRun) -> dict[str, Any]:
    return {
        "parser_run_id": run.parser_run_id,
        "attempt_number": run.attempt_number,
        "status": run.status.value,
        "parser_name": run.parser_name,
        "parser_version": run.parser_version,
        "profile_id": run.profile_id,
        "profile_version": run.profile_version,
        "pypdfium2_version": run.pypdfium2_version,
        "pdfium_version": run.pdfium_version,
        "failure_code": _value(run.failure_code),
        "started_at": _instant(run.started_at),
        "completed_at": _instant(run.completed_at),
    }


def _publication_detail(detail: SchedulePublicationDetail) -> dict[str, Any]:
    publication = detail.publication
    job = detail.job
    return {
        "publication_id": publication.publication_id,
        "series_id": publication.series_id,
        "project_id": publication.project_id,
        "enrollment_id": publication.enrollment_id,
        "source_object_id": publication.source_object_id,
        "source_version_id": publication.source_version_id,
        "publication_role": publication.publication_role.value,
        "baseline_kind": _value(publication.baseline_kind),
        "expected_data_date": _day(publication.expected_data_date),
        "supersedes_publication_id": publication.supersedes_publication_id,
        "status": detail.effective_status.value,
        "persisted_status": publication.status.value,
        "document_sha256": publication.document_sha256,
        "document_size_bytes": publication.document_size_bytes,
        "published_schedule_title": publication.published_schedule_title,
        "data_date": _day(publication.data_date),
        "run_date": _day(publication.run_date),
        "counts": {
            "page": publication.page_count,
            "row": publication.row_count,
            "activity": publication.activity_count,
            "ambiguous_row": publication.ambiguous_row_count,
            "issue": publication.issue_count,
        },
        "admitted_at": _instant(publication.admitted_at),
        "processing_started_at": _instant(publication.processing_started_at),
        "completed_at": _instant(publication.completed_at),
        "job": {
            "operation_id": job.operation_id,
            "state": job.state,
            "attempt_count": job.attempt_count,
            "max_attempts": job.max_attempts,
            "last_error_code": job.last_error_code,
        },
        "accepted_parser_run_id": publication.accepted_parser_run_id,
        "parser_runs": [_run(run) for run in detail.runs],
        "issue_counts": {code.value: count for code, count in detail.issue_counts.items()},
    }


def _activity(row: ScheduleActivityRowView) -> dict[str, Any]:
    return {
        "schedule_activity_id": row.schedule_activity_id,
        "published_activity_id": row.published_activity_id,
        "activity_name": row.activity_name,
        "row_type": row.row_type.value,
        "row_ordinal": row.row_ordinal,
        "page_number": row.page_number,
        "hierarchy_path": _path(row.hierarchy_path),
        "original_duration": _duration(row.original_duration),
        "remaining_duration": _duration(row.remaining_duration),
        "start": _date(row.start),
        "finish": _date(row.finish),
        "warning_codes": [code.value for code in row.warning_codes],
        "provenance": {
            "page_number": row.page_number,
            "physical_line_ordinal": row.physical_line_ordinal,
            "bbox_normalized": normalized_box_strings(
                row.box, row.page_width_mpt, row.page_height_mpt
            ),
        },
    }


def _observation(observation: ScheduleActivityObservation) -> dict[str, Any]:
    return {
        "publication_id": observation.publication_id,
        "publication_role": observation.publication_role.value,
        "baseline_kind": _value(observation.baseline_kind),
        "data_date": _day(observation.data_date),
        "admitted_at": _instant(observation.admitted_at),
        "activity_name": observation.activity_name,
        "row_type": observation.row_type.value,
        "hierarchy_path": _path(observation.hierarchy_path),
        "original_duration": _duration(observation.original_duration),
        "remaining_duration": _duration(observation.remaining_duration),
        "start": _date(observation.start),
        "finish": _date(observation.finish),
    }


def _series(summary: ScheduleSeriesSummary) -> dict[str, Any]:
    latest = summary.latest_update
    return {
        "series_id": summary.series_id,
        "name": summary.name,
        "publication_count": summary.publication_count,
        "latest_update": (
            None
            if latest is None
            else {"publication_id": latest.publication_id, "data_date": _day(latest.data_date)}
        ),
    }


def _end(publication: SchedulePublication) -> dict[str, Any]:
    return {
        "publication_id": publication.publication_id,
        "publication_role": publication.publication_role.value,
        "baseline_kind": _value(publication.baseline_kind),
        "data_date": _day(publication.data_date),
    }


# ---- cursor plumbing (section 3.7) ---------------------------------------------------


def _plain(value: object) -> object:
    return list(value) if isinstance(value, tuple) else value


def _request_of(command: object) -> dict[str, object]:
    """The normalized command fields a cursor binds, without the cursor and page size."""
    return {
        name: _plain(value)
        for name, value in asdict(command).items()  # type: ignore[call-overload]
        if name not in {"cursor", "page_size"}
    }


@dataclass(frozen=True, slots=True)
class _Paging:
    """One request's effective page size, cursor binding and resume position."""

    page_size: int
    binding: str
    order: ScheduleCursorOrder
    position: SchedulePosition | None
    issued_at: datetime

    def next_cursor(self, position: SchedulePosition) -> str:
        return encode_schedule_cursor(
            binding=self.binding, order=self.order, position=position, issued_at=self.issued_at
        )

    def truncation(self, more: bool, last: SchedulePosition | None) -> Truncation:
        if not more or last is None:
            return _NO_TRUNCATION
        return Truncation(
            is_truncated=True, reason=_TRUNCATION_REASON, next_cursor=self.next_cursor(last)
        )


def _paging(
    authorization: Authorization,
    command: Any,  # noqa: ANN401 - a Schedule list command (has `page_size`, `cursor`)
    order: ScheduleCursorOrder,
) -> _Paging:
    """Bind and decode before any database read, so a bad cursor never reaches one."""
    size = command.page_size or DEFAULT_SCHEDULE_PAGE_SIZE
    binding = schedule_cursor_binding(
        capability=command.capability.value,
        principal_id=authorization.principal.principal_id,
        purpose=authorization.purpose.value,
        request=_request_of(command),
        page_size=size,
        order=order,
    )
    position: SchedulePosition | None = None
    if command.cursor is not None:
        refused = False
        try:
            position = decode_schedule_cursor(
                command.cursor, binding=binding, order=order, now=authorization.at
            ).position
        except ScheduleCursorError:
            refused = True
        if refused:
            raise ConflictError(SafeDetail.CURSOR)
    return _Paging(
        page_size=size,
        binding=binding,
        order=order,
        position=position,
        issued_at=authorization.at,
    )


def _date_or_none(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def _key(publication: SchedulePublication) -> tuple[date, datetime, str]:
    """R2 section 29.1's publication order `(data_date, admitted_at, publication_id)`."""
    if publication.data_date is None:
        # T2-27: an eligible publication always has a Data Date.
        raise InternalError()
    return (publication.data_date, publication.admitted_at, publication.publication_id)


def _typed[T](value: object, kind: type[T]) -> T:
    if not isinstance(value, kind):  # pragma: no cover - the cursor module typed it
        raise InternalError()
    return value


class ScheduleApplication:
    """The 7 Schedule use cases on the Schedule unit of work (contract sections 3.6-3.11)."""

    def __init__(self, unit_of_work: Callable[[], ScheduleUnitOfWork]) -> None:
        self._unit_of_work = unit_of_work

    # ---- import (section 3.6) -------------------------------------------------------

    def import_publication(
        self,
        authorization: Authorization,
        command: ImportSchedulePublication,
        *,
        scenario_plane_effective: bool = False,
    ) -> ScheduleAnswer:
        # E-10: never from a remote composition, whatever its Principal kind
        # (every remote OAuth client is an operator, so policy alone would not
        # refuse). Then E-12: only an attested local operator surface.
        if (
            authorization.transport is CaptureTransport.REMOTE_CLIENT
            or authorization.capability_grants is not None
            or authorization.authenticated_client_id is not None
        ):
            raise UnsupportedError()
        authority = attested_lineage_authority(authorization)
        principal_id = authorization.principal.principal_id
        request = command.import_request()
        # Schedule scenarios contract section 15.9 (R10-F01, S6-3-D22): the plane
        # gates, after E-10/E-12 so a remote or unattested caller never learns of
        # the plane, keyed on the request's own approval -- `import_request` has
        # already refused, whatever the switch, an approval missing a field.
        if not scenario_plane_effective and request.series_auto:
            raise InvalidRequestError(SafeDetail.SERIES_AUTO)
        if not scenario_plane_effective and request.approval is not None:
            raise InvalidRequestError(SafeDetail.PUBLICATION_ROLE)
        operator_channel = (
            authority.decision_channel.value if request.approval is not None else None
        )
        digest = schedule_import_request_digest(principal_id, request)
        refusal: ScheduleAdmissionRefusal | None = None
        try:
            with self._unit_of_work() as work:
                admission = work.schedules.admit_publication(
                    principal_id, request, digest, operator_channel=operator_channel
                )
                created = admission.outcome is ScheduleAdmissionOutcome.CREATED
                status = (
                    SchedulePublicationStatus.QUEUED
                    if created
                    else work.schedules.get_effective_status(
                        principal_id, admission.publication.publication_id
                    )
                )
        except ScheduleAdmissionRejectedError as error:
            refusal = error.reason
        if refusal is not None:
            # Raised outside the handler so the refusal is not left in `__context__`.
            raise _refusal_error(refusal)
        if status is None:  # pragma: no cover - the admission just read it
            raise InternalError()
        source_id = next(
            (
                enrollment.source_id
                for enrollment in authorization.enrollments
                if enrollment.enrollment_id == command.enrollment_id
            ),
            None,
        )
        if source_id is None:  # pragma: no cover - authorization scoped this enrollment
            raise InternalError()
        publication = admission.publication
        return ScheduleAnswer(
            payload={
                "series_id": admission.series.series_id,
                "publication_id": publication.publication_id,
                "operation_id": admission.operation_id,
                "status": "queued" if created else "replayed",
                "created": created,
            },
            disclosure=schedule_import_disclosure(
                binding=ScheduleSourceBinding(
                    source_id=source_id,
                    enrollment_id=publication.enrollment_id,
                    source_object_id=publication.source_object_id,
                    source_version_id=publication.source_version_id,
                ),
                status=status,
                observed_at=authorization.at,
            ),
        )

    # ---- reads (section 3.9) ------------------------------------------------------------

    def list_series(
        self, authorization: Authorization, command: ListScheduleSeries
    ) -> ScheduleAnswer:
        paging = _paging(authorization, command, ScheduleCursorOrder.SERIES)
        principal_id = authorization.principal.principal_id
        after = (
            None
            if paging.position is None
            else (_typed(paging.position[0], datetime), _typed(paging.position[1], str))
        )
        with self._unit_of_work() as work:
            if not work.schedules.owns_project(principal_id, command.project_id):
                raise NotFoundError(SafeDetail.PROJECT_ID)
            found = work.schedules.list_series(
                principal_id, command.project_id, after=after, limit=paging.page_size + 1
            )
            page = found[: paging.page_size]
            intake = work.schedules.intake_series_ids(
                principal_id, [summary.series_id for summary in page]
            )
        last = None if not page else (page[-1].created_at, page[-1].series_id)
        return ScheduleAnswer(
            payload={
                "project_id": command.project_id,
                "series": [
                    {**_series(summary), "series_kind": _series_kind(summary.series_id in intake)}
                    for summary in page
                ],
                "page_size": paging.page_size,
            },
            disclosure=schedule_disclosure(
                publications=[
                    (summary.latest_update.source, summary.latest_update.status)
                    for summary in page
                    if summary.latest_update is not None
                ],
                observed_at=authorization.at,
                truncation=paging.truncation(len(found) > paging.page_size, last),
            ),
        )

    def list_publications(
        self, authorization: Authorization, command: ListSchedulePublications
    ) -> ScheduleAnswer:
        paging = _paging(authorization, command, ScheduleCursorOrder.PUBLICATIONS)
        principal_id = authorization.principal.principal_id
        after = (
            None
            if paging.position is None
            else (_typed(paging.position[0], datetime), _typed(paging.position[1], str))
        )
        role = (
            None
            if command.publication_role is None
            else SchedulePublicationRole(command.publication_role)
        )
        status = None if command.status is None else SchedulePublicationStatus(command.status)
        with self._unit_of_work() as work:
            if work.schedules.get_series(principal_id, command.series_id) is None:
                raise NotFoundError(SafeDetail.SERIES_ID)
            found = work.schedules.list_publications(
                principal_id,
                command.series_id,
                role=role,
                status=status,
                after=after,
                limit=paging.page_size + 1,
            )
            kind = _series_kind(
                bool(work.schedules.intake_series_ids(principal_id, [command.series_id]))
            )
        page = found[: paging.page_size]
        last = (
            None
            if not page
            else (page[-1].publication.admitted_at, page[-1].publication.publication_id)
        )
        return ScheduleAnswer(
            payload={
                "series_id": command.series_id,
                "publications": [
                    {**_publication_row(summary), "series_kind": kind} for summary in page
                ],
                "page_size": paging.page_size,
            },
            disclosure=schedule_disclosure(
                publications=[(summary.source, summary.effective_status) for summary in page],
                observed_at=authorization.at,
                truncation=paging.truncation(len(found) > paging.page_size, last),
            ),
        )

    def read_publication(
        self, authorization: Authorization, command: ReadSchedulePublication
    ) -> ScheduleAnswer:
        principal_id = authorization.principal.principal_id
        with self._unit_of_work() as work:
            detail = work.schedules.get_publication_detail(principal_id, command.publication_id)
            intake = (
                {}
                if detail is None
                else work.schedules.intake_publication_ids(principal_id, [command.publication_id])
            )
        if detail is None:
            raise NotFoundError(SafeDetail.PUBLICATION_ID)
        return ScheduleAnswer(
            payload=_with_match_state(_publication_detail(detail), detail, intake),
            disclosure=schedule_disclosure(
                publications=[(detail.source, detail.effective_status)],
                observed_at=authorization.at,
            ),
        )

    def list_activities(
        self, authorization: Authorization, command: ListScheduleActivities
    ) -> ScheduleAnswer:
        paging = _paging(authorization, command, ScheduleCursorOrder.ACTIVITIES)
        principal_id = authorization.principal.principal_id
        after = (
            None
            if paging.position is None
            else (_typed(paging.position[0], int), _typed(paging.position[1], str))
        )
        row_type = None if command.row_type is None else ScheduleRowType(command.row_type)
        with self._unit_of_work() as work:
            detail = _eligible(work.schedules, principal_id, command.publication_id)
            found = work.schedules.list_activity_rows(
                principal_id,
                command.publication_id,
                row_type=row_type,
                hierarchy_prefix=command.hierarchy_prefix,
                start_range=(_date_or_none(command.start_from), _date_or_none(command.start_to)),
                finish_range=(_date_or_none(command.finish_from), _date_or_none(command.finish_to)),
                after=after,
                limit=paging.page_size + 1,
            )
        page = found[: paging.page_size]
        last = None if not page else (page[-1].row_ordinal, page[-1].row_id)
        return ScheduleAnswer(
            payload={
                "publication_id": command.publication_id,
                "activities": [_activity(row) for row in page],
                "page_size": paging.page_size,
            },
            disclosure=schedule_disclosure(
                publications=[(detail.source, detail.effective_status)],
                observed_at=authorization.at,
                truncation=paging.truncation(len(found) > paging.page_size, last),
            ),
        )

    def activity_history(
        self, authorization: Authorization, command: ReadScheduleActivityHistory
    ) -> ScheduleAnswer:
        paging = _paging(authorization, command, ScheduleCursorOrder.HISTORY)
        principal_id = authorization.principal.principal_id
        after = (
            None
            if paging.position is None
            else (
                _typed(paging.position[0], date),
                _typed(paging.position[1], datetime),
                _typed(paging.position[2], str),
            )
        )
        with self._unit_of_work() as work:
            # U-03: visible only through an accepted row of a complete or partial
            # publication; an orphan, an absent and a foreign one are one answer.
            activity = work.schedules.activity_is_visible(
                principal_id, command.schedule_activity_id
            )
            if activity is None:
                raise NotFoundError(SafeDetail.SCHEDULE_ACTIVITY_ID)
            found = work.schedules.activity_history(
                principal_id,
                command.schedule_activity_id,
                after=after,
                limit=paging.page_size + 1,
            )
        page = found[: paging.page_size]
        last = (
            None
            if not page
            else (page[-1].data_date, page[-1].admitted_at, page[-1].publication_id)
        )
        return ScheduleAnswer(
            payload={
                "schedule_activity_id": activity.schedule_activity_id,
                "series_id": activity.series_id,
                "published_activity_id": activity.published_activity_id,
                "observations": [_observation(observation) for observation in page],
                "page_size": paging.page_size,
            },
            disclosure=schedule_disclosure(
                publications=[(observation.source, observation.status) for observation in page],
                observed_at=authorization.at,
                truncation=paging.truncation(len(found) > paging.page_size, last),
            ),
        )

    def list_changes(
        self, authorization: Authorization, command: ListScheduleChanges
    ) -> ScheduleAnswer:
        paging = _paging(authorization, command, ScheduleCursorOrder.CHANGES)
        principal_id = authorization.principal.principal_id
        offset = 0 if paging.position is None else _typed(paging.position[0], int)
        with self._unit_of_work() as work:
            schedules = work.schedules
            first = schedules.get_publication_detail(principal_id, command.from_publication_id)
            if first is None:
                raise NotFoundError(SafeDetail.FROM_PUBLICATION_ID)
            second = schedules.get_publication_detail(principal_id, command.to_publication_id)
            if second is None:
                raise NotFoundError(SafeDetail.TO_PUBLICATION_ID)
            # Schedule scenarios contract sections 11.4, 15.6.2 (S6-3-D18): an
            # intake publication is never one end of a delta.
            intake = schedules.intake_publication_ids(
                principal_id, [command.from_publication_id, command.to_publication_id]
            )
            if command.to_publication_id in intake:
                raise InvalidRequestError(SafeDetail.TO_PUBLICATION_ID)
            if command.from_publication_id in intake:
                raise InvalidRequestError(SafeDetail.FROM_PUBLICATION_ID)
            a, b = first.publication, second.publication
            if (a.project_id, a.series_id) != (b.project_id, b.series_id):
                raise InvalidRequestError(SafeDetail.TO_PUBLICATION_ID)
            if not {first.effective_status, second.effective_status} <= _SERVED:
                raise ConflictError(SafeDetail.STATUS)
            before = _key(a)
            if not before < _key(b):
                raise InvalidRequestError(SafeDetail.TO_PUBLICATION_ID)
            from_rows = list(schedules.comparison_rows(principal_id, a.publication_id))
            to_rows = list(schedules.comparison_rows(principal_id, b.publication_id))
            prior = schedules.prior_observations(
                principal_id,
                a.series_id,
                before=before,
                schedule_activity_ids=unmatched_target_activity_ids(from_rows, to_rows),
            )
        delta = compare_publications(from_rows, to_rows, prior)
        listed: Iterable[ScheduleChange] = delta.changes
        if command.change_kind is not None:
            kind = ScheduleChangeKind(command.change_kind)
            listed = [change for change in delta.changes if change.change_kind is kind]
        selected = tuple(listed)
        if offset > len(selected):
            raise ConflictError(SafeDetail.CURSOR)
        end = offset + paging.page_size
        page = selected[offset:end]
        return ScheduleAnswer(
            payload={
                "algorithm_version": DELTA_ALGORITHM_VERSION,
                "from": _end(a),
                "to": _end(b),
                "counts_by_kind": {
                    kind.value: count for kind, count in delta.counts_by_kind.items()
                },
                "changes": [_change(change) for change in page],
                "page_size": paging.page_size,
            },
            disclosure=schedule_disclosure(
                publications=[
                    (first.source, first.effective_status),
                    (second.source, second.effective_status),
                ],
                observed_at=authorization.at,
                truncation=paging.truncation(end < len(selected), (end,)),
                trust_basis=(*SCHEDULE_READ_TRUST_BASIS, DELTA_ALGORITHM_VERSION),
            ),
        )


def _series_kind(intake: bool) -> str:
    """Section 15.6.2: a Series is `intake` (the worker's own) or `standard`."""
    return "intake" if intake else "standard"


_TERMINAL: Final = frozenset(
    {
        SchedulePublicationStatus.COMPLETE,
        SchedulePublicationStatus.PARTIAL,
        SchedulePublicationStatus.REVIEW_REQUIRED,
        SchedulePublicationStatus.FAILED,
    }
)


def _with_match_state(
    payload: dict[str, Any],
    detail: SchedulePublicationDetail,
    intake: Mapping[str, str | None],
) -> dict[str, Any]:
    """Section 15.6.2: `series_kind`, and an intake publication's match state.

    `pending` while non-terminal; `decided` once a decision is recorded; a
    terminal intake publication with no decision is `undecided`
    (S6-2-U09/U10).
    """
    publication_id = detail.publication.publication_id
    if publication_id not in intake:
        return {**payload, "series_kind": _series_kind(False)}
    decision = intake[publication_id]
    if decision is not None:
        state = "decided"
    elif detail.effective_status in _TERMINAL:
        state = "undecided"
    else:
        state = "pending"
    return {
        **payload,
        "series_kind": _series_kind(True),
        "match_state": state,
        "match_decision_id": decision,
    }


def _eligible(
    schedules: ScheduleRepository, principal_id: str, publication_id: str
) -> SchedulePublicationDetail:
    """The root publication, owned (`not_found`) and effective complete or partial (`conflict`)."""
    detail = schedules.get_publication_detail(principal_id, publication_id)
    if detail is None:
        raise NotFoundError(SafeDetail.PUBLICATION_ID)
    if detail.effective_status not in _SERVED:
        raise ConflictError(SafeDetail.STATUS)
    return detail
