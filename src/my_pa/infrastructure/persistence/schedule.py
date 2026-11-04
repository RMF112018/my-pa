"""The CPM Workbench Schedule foundation tables, behind `contracts.ports.ScheduleRepository`.

Contract: `docs/architecture/cpm-workbench-foundation-contract.md` sections
3.5 and 5.4-5.7 (R2 WP-01). This module is the whole of the WP-01 persistence
plane: one admission transaction and the section 24 worker transactions, each
a repository method the caller runs inside one `SqlAlchemyScheduleUnitOfWork`.
There is no worker handler, capability or read service here; WP-03 composes
these methods.

**The partition is reached through the guard, never written by hand** -- the
`constraints.py` shape. Every statement over a partitioned table composes
`_mine` (over `partition_criterion`) or `_bound` (over
`principal_bound_values`), and the one statement joining two partitioned
tables (the canonicalization link) also composes
`matching_partition_criterion`. `enrollment_objects` carries no partition
column and is read only joined to `enrollments` under `_mine`;
`source_object_versions` (the unpartitioned source plane) is read only by the
exact `(version_id, source_object_id)` pair the request names, after the
enrollment join has proved the object is the Principal's.

**Every worker write holds its lease.** The first statement of every worker
method is `hold_lease` on `SCHEDULE_JOBS` (a `FOR UPDATE` on the job row held
to commit); a lost lease raises `ScheduleLeaseLostError`, so the unit of work
rolls back and nothing is written. The job row is then read partitioned and
must name the publication being written and the caller's attempt.

**The database is the final word.** The lifecycle triggers of the revision
re-verify every transition this module makes (F3, F6, F7, F8). The checks
here exist to answer with a typed, content-free error before a statement is
refused, never to replace those triggers. `knowledge.schedule_run_outcome`
(F9) is called only with a run identifier this module has just read under
`_mine` in the same transaction (contract section 4.10, RR1-F03).

**Schedule Scenarios S6-2** (schedule scenarios contract sections 14.8.5 and
14.8.6). A role-`baseline` admission carries its import-time approval and the
operator's attested channel; it takes the Project lock J before any row lock
and writes the Baseline and its `approve` event in this same transaction
through `schedule_scenarios.record_import_approval`. A `series_auto` admission
creates its own intake Series and marks it; an explicit Series naming an intake
Series is `SERIES_NOT_FOUND`.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType, TracebackType
from typing import Any, Final

from sqlalchemy import (
    ColumnElement,
    Engine,
    Join,
    Table,
    Text,
    and_,
    any_,
    bindparam,
    case,
    func,
    insert,
    literal,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, RowMapping

from my_pa.contracts.ports import (
    ScheduleAdmissionRejectedError,
    ScheduleIntegrityError,
    ScheduleLeaseLostError,
    ScheduleRepository,
    ScheduleUnitOfWork,
)
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.schedule import (
    ISSUE_SEVERITY,
    MAX_SCHEDULE_BATCH,
    MAX_SCHEDULE_SOURCE_BYTES,
    SCHEDULE_MEDIA_TYPE,
    TERMINAL_OUTCOMES,
    ParsedScheduleRow,
    ScheduleActivityObservation,
    ScheduleActivityRowView,
    ScheduleAdmission,
    ScheduleAdmissionOutcome,
    ScheduleAdmissionRefusal,
    ScheduleBaselineKind,
    ScheduleBox,
    ScheduleCanonicalizationProgress,
    ScheduleCellState,
    ScheduleDateCell,
    ScheduleDurationCell,
    ScheduleFinalization,
    ScheduleImportRequest,
    ScheduleIssueCode,
    ScheduleIssueSeverity,
    ScheduleJobView,
    ScheduleLatestUpdate,
    ScheduleLease,
    ScheduleParseCounts,
    ScheduleParseIssue,
    ScheduleParserIdentity,
    ScheduleParserRun,
    ScheduleParserRunStart,
    ScheduleParserRunStatus,
    SchedulePlan,
    SchedulePublication,
    SchedulePublicationDetail,
    SchedulePublicationRole,
    SchedulePublicationStatus,
    SchedulePublicationSummary,
    ScheduleRowType,
    ScheduleSeries,
    ScheduleSeriesSummary,
    ScheduleSourceBinding,
    StableScheduleActivity,
    cell_evidence_object,
    effective_publication_status,
    schedule_import_request_digest,
    validate_row_for_persistence,
)
from my_pa.domain.schedule.baselines import BaselineType
from my_pa.domain.schedule.compare import ScheduleComparisonRow
from my_pa.domain.schedule.plane import PLANE_ATTESTED_DECISION_CHANNELS, intake_series_name
from my_pa.domain.source.registry import issue_identifier

# Schedule scenarios contract section 14.8.5: the plane functions the admission
# calls. A module import (the plane module imports this one back the same way).
from my_pa.infrastructure.persistence import schedule_scenarios as _plane
from my_pa.infrastructure.persistence.jobs import (
    SCHEDULE_JOBS,
    enqueue_job,
    hold_lease,
    job_for,
    job_is_effectively_failed,
)
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    matching_partition_criterion,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    JobState,
    enrollment_objects,
    enrollments,
    projects,
    schedule_activities,
    schedule_import_issues,
    schedule_intake_series,
    schedule_jobs,
    schedule_parser_runs,
    schedule_publications,
    schedule_rows,
    schedule_series,
    source_object_versions,
)

__all__ = ["SqlAlchemyScheduleUnitOfWork", "SqlScheduleRepository"]

#: The row types that carry a published ID and link a Stable Activity.
_LINKABLE: Final = (ScheduleRowType.ACTIVITY.value, ScheduleRowType.MILESTONE.value)
_RUNNING: Final = ScheduleParserRunStatus.RUNNING.value
_PARSED: Final = ScheduleParserRunStatus.PARSED.value
_FAILED_RUN: Final = ScheduleParserRunStatus.FAILED.value
_PROCESSING: Final = SchedulePublicationStatus.PROCESSING.value
_SHA256_LENGTH: Final = 64
_HEX: Final = frozenset("0123456789abcdef")


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


def _refuse(reason: ScheduleAdmissionRefusal) -> ScheduleAdmissionRejectedError:
    return ScheduleAdmissionRejectedError(reason)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == _SHA256_LENGTH and set(value) <= _HEX


# The hydrators take the Principal from the authenticated parameter, never from
# the row: every row reaching them was read or written under `_mine`/`_bound`
# for that same Principal, so the stored value is that one by construction.


def _to_series(row: RowMapping, principal_id: str) -> ScheduleSeries:
    return ScheduleSeries(
        series_id=row["series_id"],
        principal_id=principal_id,
        project_id=row["project_id"],
        name=row["name"],
        name_key=row["name_key"],
        created_at=row["created_at"],
    )


def _to_publication(row: RowMapping, principal_id: str) -> SchedulePublication:
    baseline = row["baseline_kind"]
    size = row["document_size_bytes"]
    return SchedulePublication(
        publication_id=row["publication_id"],
        principal_id=principal_id,
        project_id=row["project_id"],
        series_id=row["series_id"],
        enrollment_id=row["enrollment_id"],
        source_object_id=row["source_object_id"],
        source_version_id=row["source_version_id"],
        idempotency_key=row["idempotency_key"],
        request_digest=row["request_digest"],
        publication_role=SchedulePublicationRole(row["publication_role"]),
        baseline_kind=None if baseline is None else ScheduleBaselineKind(baseline),
        expected_data_date=row["expected_data_date"],
        supersedes_publication_id=row["supersedes_publication_id"],
        status=SchedulePublicationStatus(row["status"]),
        document_sha256=row["document_sha256"],
        document_size_bytes=None if size is None else int(size),
        published_schedule_title=row["published_schedule_title"],
        data_date=row["data_date"],
        run_date=row["run_date"],
        accepted_parser_run_id=row["accepted_parser_run_id"],
        page_count=row["page_count"],
        row_count=row["row_count"],
        activity_count=row["activity_count"],
        ambiguous_row_count=row["ambiguous_row_count"],
        issue_count=row["issue_count"],
        admitted_at=row["admitted_at"],
        processing_started_at=row["processing_started_at"],
        completed_at=row["completed_at"],
        updated_at=row["updated_at"],
    )


def _to_run(row: RowMapping, principal_id: str) -> ScheduleParserRun:
    failure = row["failure_code"]
    return ScheduleParserRun(
        parser_run_id=row["parser_run_id"],
        principal_id=principal_id,
        project_id=row["project_id"],
        series_id=row["series_id"],
        publication_id=row["publication_id"],
        operation_id=row["operation_id"],
        attempt_number=row["attempt_number"],
        parser_name=row["parser_name"],
        parser_version=row["parser_version"],
        profile_id=row["profile_id"],
        profile_version=row["profile_version"],
        pypdfium2_version=row["pypdfium2_version"],
        pdfium_version=row["pdfium_version"],
        document_sha256=row["document_sha256"],
        status=ScheduleParserRunStatus(row["status"]),
        page_count=row["page_count"],
        row_count=row["row_count"],
        issue_count=row["issue_count"],
        warning_count=row["warning_count"],
        parse_result_sha256=row["parse_result_sha256"],
        failure_code=None if failure is None else ScheduleIssueCode(failure),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )


def _row_values(
    row: ParsedScheduleRow,
    *,
    row_id: str,
    parent_row_id: str | None,
    run: RowMapping,
) -> dict[str, object]:
    """One `schedule_rows` insert, the S5a record field for field (contract 4.6)."""
    return {
        "row_id": row_id,
        "project_id": run["project_id"],
        "series_id": run["series_id"],
        "publication_id": run["publication_id"],
        "parser_run_id": run["parser_run_id"],
        "row_ordinal": row.row_ordinal,
        "page_number": row.page_number,
        "physical_line_ordinal": row.physical_line_ordinal,
        "row_type": row.row_type.value,
        "indent_level": row.indent_level,
        "parent_row_id": parent_row_id,
        "hierarchy_path": None if row.hierarchy_path is None else list(row.hierarchy_path),
        "published_activity_id": row.published_activity_id,
        "activity_name": row.activity_name,
        "od_state": row.original_duration.state.value,
        "od_value": row.original_duration.value,
        "rd_state": row.remaining_duration.state.value,
        "rd_value": row.remaining_duration.value,
        "start_state": row.start.state.value,
        "start_date": row.start.value,
        "start_marker": row.start.marker,
        "finish_state": row.finish.state.value,
        "finish_date": row.finish.value,
        "finish_marker": row.finish.marker,
        "bbox_x0_mpt": row.box.x0,
        "bbox_y0_mpt": row.box.y0,
        "bbox_x1_mpt": row.box.x1,
        "bbox_y1_mpt": row.box.y1,
        "page_width_mpt": row.page_width_mpt,
        "page_height_mpt": row.page_height_mpt,
        "cell_evidence": cell_evidence_object(row),
        "warning_codes": [code.value for code in row.warning_codes],
    }


# ---- S5b-2 read helpers (worker contract section 3.9) ---------------------------

#: The publication statuses whose accepted run is served (comparison-eligible).
_ELIGIBLE: Final = (
    SchedulePublicationStatus.COMPLETE.value,
    SchedulePublicationStatus.PARTIAL.value,
)
#: Statuses that carry an accepted parser run (RR1-I01 issue counting).
_ACCEPTED: Final = frozenset(
    {*_ELIGIBLE, SchedulePublicationStatus.REVIEW_REQUIRED.value},
)
_UNFINISHED: Final = (
    SchedulePublicationStatus.QUEUED.value,
    SchedulePublicationStatus.PROCESSING.value,
)
_BOUND_PUBLICATION_COLUMNS: Final = (
    schedule_publications.c.series_id,
    schedule_publications.c.publication_id,
    schedule_publications.c.data_date,
    schedule_publications.c.status,
    schedule_publications.c.enrollment_id,
    schedule_publications.c.source_object_id,
    schedule_publications.c.source_version_id,
)
#: What a served row carries besides its provenance (never `created_at`).
_ROW_CONTENT_COLUMNS: Final = (
    schedule_rows.c.schedule_activity_id,
    schedule_rows.c.published_activity_id,
    schedule_rows.c.activity_name,
    schedule_rows.c.row_type,
    schedule_rows.c.hierarchy_path,
    schedule_rows.c.od_state,
    schedule_rows.c.od_value,
    schedule_rows.c.rd_state,
    schedule_rows.c.rd_value,
    schedule_rows.c.start_state,
    schedule_rows.c.start_date,
    schedule_rows.c.start_marker,
    schedule_rows.c.finish_state,
    schedule_rows.c.finish_date,
    schedule_rows.c.finish_marker,
)


def _bound_join(pubs: Table) -> Join:
    """A publication joined to the enrollment it was admitted through (its source)."""
    return pubs.join(enrollments, enrollments.c.enrollment_id == pubs.c.enrollment_id)


def _bound_criteria(principal_id: str) -> tuple[ColumnElement[bool], ...]:
    pubs = schedule_publications
    return (
        _mine(pubs, principal_id),
        _mine(enrollments, principal_id),
        matching_partition_criterion(pubs, enrollments),
    )


def _accepted_rows() -> Join:
    """Rows joined to their publication through its *accepted* run only."""
    rows = schedule_rows
    pubs = schedule_publications
    return rows.join(
        pubs,
        and_(
            pubs.c.publication_id == rows.c.publication_id,
            pubs.c.accepted_parser_run_id == rows.c.parser_run_id,
        ),
    )


def _accepted_criteria(principal_id: str) -> tuple[ColumnElement[bool], ...]:
    """Both partitions, and a complete or partial publication (U-03)."""
    rows = schedule_rows
    pubs = schedule_publications
    return (
        _mine(rows, principal_id),
        _mine(pubs, principal_id),
        matching_partition_criterion(rows, pubs),
        pubs.c.status.in_(_ELIGIBLE),
    )


def _effective_status_column() -> ColumnElement[str]:
    """R2 section 10.6 in SQL: an unfinished publication whose job reads `failed` is `failed`."""
    pubs = schedule_publications
    return case(
        (
            and_(pubs.c.status.in_(_UNFINISHED), job_is_effectively_failed(SCHEDULE_JOBS)),
            SchedulePublicationStatus.FAILED.value,
        ),
        else_=pubs.c.status,
    )


def _position(values: tuple[object, ...]) -> ColumnElement[Any]:
    """A keyset position as a bound row value, compared with `tuple_` of its columns."""
    return tuple_(*(literal(value) for value in values))


def _eligible_data_date(value: date | None) -> date:
    # T2-27: every complete/partial publication has a Data Date; a NULL is an
    # invariant breach, never a guessed order.
    if value is None:
        raise ScheduleIntegrityError("eligible_without_data_date")
    return value


def _source_binding(row: RowMapping) -> ScheduleSourceBinding:
    return ScheduleSourceBinding(
        source_id=row["source_id"],
        enrollment_id=row["enrollment_id"],
        source_object_id=row["source_object_id"],
        source_version_id=row["source_version_id"],
    )


def _path(value: Sequence[str] | None) -> tuple[str, ...] | None:
    return None if value is None else tuple(value)


def _duration(state: str, value: Decimal | None) -> ScheduleDurationCell:
    return ScheduleDurationCell(state=ScheduleCellState(state), value=value)


def _date(state: str, value: date | None, marker: str | None) -> ScheduleDateCell:
    return ScheduleDateCell(state=ScheduleCellState(state), value=value, marker=marker)


def _to_activity_row(row: RowMapping) -> ScheduleActivityRowView:
    activity = row["schedule_activity_id"]
    if activity is None:
        raise ScheduleIntegrityError("eligible_row_unlinked")
    return ScheduleActivityRowView(
        row_id=row["row_id"],
        schedule_activity_id=activity,
        published_activity_id=row["published_activity_id"],
        activity_name=row["activity_name"],
        row_type=ScheduleRowType(row["row_type"]),
        row_ordinal=row["row_ordinal"],
        page_number=row["page_number"],
        physical_line_ordinal=row["physical_line_ordinal"],
        hierarchy_path=_path(row["hierarchy_path"]),
        original_duration=_duration(row["od_state"], row["od_value"]),
        remaining_duration=_duration(row["rd_state"], row["rd_value"]),
        start=_date(row["start_state"], row["start_date"], row["start_marker"]),
        finish=_date(row["finish_state"], row["finish_date"], row["finish_marker"]),
        warning_codes=tuple(ScheduleIssueCode(code) for code in row["warning_codes"]),
        box=ScheduleBox(
            x0=row["bbox_x0_mpt"],
            y0=row["bbox_y0_mpt"],
            x1=row["bbox_x1_mpt"],
            y1=row["bbox_y1_mpt"],
        ),
        page_width_mpt=row["page_width_mpt"],
        page_height_mpt=row["page_height_mpt"],
    )


class SqlScheduleRepository(ScheduleRepository):
    """The Schedule foundation tables on one connection; never commits."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    # ---- shared reads --------------------------------------------------------

    def _publication(
        self, principal_id: str, publication_id: str, *, for_update: bool = False
    ) -> RowMapping | None:
        statement = select(schedule_publications).where(
            _mine(schedule_publications, principal_id),
            schedule_publications.c.publication_id == publication_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self._connection.execute(statement).mappings().one_or_none()

    def _series_row(self, principal_id: str, series_id: str) -> RowMapping | None:
        return (
            self._connection.execute(
                select(schedule_series).where(
                    _mine(schedule_series, principal_id),
                    schedule_series.c.series_id == series_id,
                )
            )
            .mappings()
            .one_or_none()
        )

    def _run(
        self, principal_id: str, parser_run_id: str, *, for_update: bool = False
    ) -> RowMapping | None:
        statement = select(schedule_parser_runs).where(
            _mine(schedule_parser_runs, principal_id),
            schedule_parser_runs.c.parser_run_id == parser_run_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self._connection.execute(statement).mappings().one_or_none()

    def _operation_of(self, principal_id: str, publication_id: str) -> str | None:
        found = self._connection.execute(
            select(schedule_jobs.c.operation_id).where(
                _mine(schedule_jobs, principal_id),
                schedule_jobs.c.publication_id == publication_id,
            )
        ).scalar_one_or_none()
        return None if found is None else str(found)

    def _effective(self, principal_id: str, row: RowMapping) -> SchedulePublicationStatus:
        operation_id = self._operation_of(principal_id, row["publication_id"])
        job = (
            None
            if operation_id is None
            else job_for(
                self._connection, operation_id, principal_id=principal_id, plane=SCHEDULE_JOBS
            )
        )
        return effective_publication_status(
            SchedulePublicationStatus(row["status"]),
            job_failed=job is not None and job.state is JobState.FAILED,
        )

    def _outcome(self, parser_run_id: str) -> SchedulePublicationStatus:
        """F9 over a run this transaction has just read under `_mine`."""
        return SchedulePublicationStatus(
            self._connection.execute(
                select(func.knowledge.schedule_run_outcome(parser_run_id))
            ).scalar_one()
        )

    # ---- the lease (contract section 5.5, lease rule) ---------------------------

    def _hold(self, lease: ScheduleLease) -> None:
        """The first statement of every worker method: the lease, locked."""
        if not hold_lease(
            self._connection, lease.operation_id, owner=lease.owner, plane=SCHEDULE_JOBS
        ):
            raise ScheduleLeaseLostError()

    def _job_names(self, principal_id: str, lease: ScheduleLease, publication_id: str) -> None:
        """The held job is the Principal's, is this publication's, and is this attempt."""
        job = self._connection.execute(
            select(schedule_jobs.c.publication_id, schedule_jobs.c.attempt_count).where(
                _mine(schedule_jobs, principal_id),
                schedule_jobs.c.operation_id == lease.operation_id,
            )
        ).one_or_none()
        if (
            job is None
            or job.publication_id != publication_id
            or job.attempt_count != lease.attempt
        ):
            raise ScheduleLeaseLostError()

    def _held_run(self, principal_id: str, parser_run_id: str, lease: ScheduleLease) -> RowMapping:
        """Lease, then the run (partitioned, locked), then the job naming its publication."""
        self._hold(lease)
        run = self._run(principal_id, parser_run_id, for_update=True)
        if run is None:
            raise ScheduleIntegrityError("parser_run_not_found")
        self._job_names(principal_id, lease, run["publication_id"])
        return run

    def _held_publication(
        self, principal_id: str, publication_id: str, lease: ScheduleLease
    ) -> RowMapping:
        """Lease, then the job naming this publication, then the publication, locked."""
        self._hold(lease)
        self._job_names(principal_id, lease, publication_id)
        publication = self._publication(principal_id, publication_id, for_update=True)
        if publication is None:
            raise ScheduleIntegrityError("publication_not_found")
        return publication

    @staticmethod
    def _require_processing(publication: RowMapping) -> None:
        if publication["status"] != _PROCESSING:
            raise ScheduleIntegrityError("publication_not_processing")

    def _close_running_runs(
        self, principal_id: str, publication_id: str, *, except_run: str | None = None
    ) -> None:
        """Every other `running` run of the publication ends `failed`, code NULL (D-09)."""
        criteria = [
            _mine(schedule_parser_runs, principal_id),
            schedule_parser_runs.c.publication_id == publication_id,
            schedule_parser_runs.c.status == _RUNNING,
        ]
        if except_run is not None:
            criteria.append(schedule_parser_runs.c.parser_run_id != except_run)
        self._connection.execute(
            update(schedule_parser_runs)
            .where(*criteria)
            .values(status=_FAILED_RUN, completed_at=func.now())
        )

    # ---- admission ---------------------------------------------------------------

    def admit_publication(
        self,
        principal_id: str,
        request: ScheduleImportRequest,
        request_digest: str,
        *,
        operator_channel: str | None = None,
    ) -> ScheduleAdmission:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if request_digest != schedule_import_request_digest(principal_id, request):
            raise ValueError("the request digest is not the digest of this request")
        # Schedule scenarios contract section 14.8.5: an approval comes with the
        # attested channel of the operator who made it, and only then.
        if (request.approval is None) != (operator_channel is None) or (
            operator_channel is not None
            and operator_channel not in PLANE_ATTESTED_DECISION_CHANNELS
        ):
            raise ValueError("an import approval is given on an attested operator channel")
        # (1) the idempotency key.
        replay = self._replay_by_key(principal_id, request, request_digest)
        if replay is not None:
            return replay
        # Section 14.8.5: the import-time approval decides under the Project lock J,
        # taken here, before any row lock this admission takes.
        if request.approval is not None:
            _plane.lock_project(self._connection, principal_id, request.project_id)
        # (2) and (3) every binding the request names, proven inside this partition.
        self._require_project(principal_id, request)
        self._require_source(principal_id, request)
        # (4) the Series (section 14.8.6: an automatic import's own intake Series).
        series = self._find_series(principal_id, request, request_digest)
        # (5) one publication per source version per Series.
        if series is not None:
            replay = self._replay_by_version(principal_id, series, request)
            if replay is not None:
                return replay
        # (6) the predecessor, locked.
        if request.supersedes_publication_id is not None:
            self._require_predecessor(principal_id, series, request)
        # (7) the writes.
        series_created = False
        if series is None:
            series, series_created = self._create_series(principal_id, request, request_digest)
        publication_id = issue_identifier(IdKind.SCHEDULE_PUBLICATION)
        inserted = (
            self._connection.execute(
                pg_insert(schedule_publications)
                .values(
                    _bound(
                        schedule_publications,
                        principal_id,
                        {
                            "publication_id": publication_id,
                            "project_id": request.project_id,
                            "series_id": series.series_id,
                            "enrollment_id": request.enrollment_id,
                            "source_object_id": request.source_object_id,
                            "source_version_id": request.source_version_id,
                            "idempotency_key": request.idempotency_key,
                            "request_digest": request_digest,
                            "publication_role": request.publication_role.value,
                            "baseline_kind": (
                                None
                                if request.baseline_kind is None
                                else request.baseline_kind.value
                            ),
                            "expected_data_date": request.expected_data_date,
                            "supersedes_publication_id": request.supersedes_publication_id,
                        },
                    )
                )
                .on_conflict_do_nothing()
                .returning(*schedule_publications.c)
            )
            .mappings()
            .one_or_none()
        )
        if inserted is None:
            return self._classify_lost_race(principal_id, series, request, request_digest)
        operation_id = enqueue_job(self._connection, publication_id, plane=SCHEDULE_JOBS)
        if request.series_auto:
            self._mark_intake(principal_id, request, series, publication_id)
        if request.approval is not None and operator_channel is not None:
            kind = request.baseline_kind
            if kind is None:  # the request invariant: an approval is a baseline's
                raise ScheduleIntegrityError("import_approval")
            _plane.record_import_approval(
                self._connection,
                principal_id,
                project_id=request.project_id,
                publication_id=publication_id,
                baseline_type=BaselineType(kind.value),
                approval=request.approval,
                operator_channel=operator_channel,
            )
        return ScheduleAdmission(
            series=series,
            publication=_to_publication(inserted, principal_id),
            operation_id=operation_id,
            outcome=ScheduleAdmissionOutcome.CREATED,
            series_created=series_created,
        )

    def _mark_intake(
        self,
        principal_id: str,
        request: ScheduleImportRequest,
        series: ScheduleSeries,
        publication_id: str,
    ) -> None:
        """Section 14.8.6: the intake row, with the name the worker may create (G9 verifies)."""
        if_new = request.series_name_if_new
        self._connection.execute(
            insert(schedule_intake_series).values(
                _bound(
                    schedule_intake_series,
                    principal_id,
                    {
                        "project_id": request.project_id,
                        "series_id": series.series_id,
                        "publication_id": publication_id,
                        "series_name_if_new": None if if_new is None else if_new.name,
                        "series_name_if_new_key": None if if_new is None else if_new.key,
                    },
                )
            )
        )

    def _replayed(self, principal_id: str, publication: RowMapping) -> ScheduleAdmission:
        series = self._series_row(principal_id, publication["series_id"])
        operation_id = self._operation_of(principal_id, publication["publication_id"])
        if series is None or operation_id is None:
            raise ScheduleIntegrityError("admission_replay_incomplete")
        return ScheduleAdmission(
            series=_to_series(series, principal_id),
            publication=_to_publication(publication, principal_id),
            operation_id=operation_id,
            outcome=ScheduleAdmissionOutcome.REPLAYED,
            series_created=False,
        )

    def _replay_by_key(
        self, principal_id: str, request: ScheduleImportRequest, request_digest: str
    ) -> ScheduleAdmission | None:
        found = (
            self._connection.execute(
                select(schedule_publications).where(
                    _mine(schedule_publications, principal_id),
                    schedule_publications.c.idempotency_key == request.idempotency_key,
                )
            )
            .mappings()
            .one_or_none()
        )
        if found is None:
            return None
        if found["request_digest"] != request_digest:
            raise _refuse(ScheduleAdmissionRefusal.IDEMPOTENCY_KEY_CONFLICT)
        return self._replayed(principal_id, found)

    def _require_project(self, principal_id: str, request: ScheduleImportRequest) -> None:
        owned = self._connection.execute(
            select(projects.c.project_id).where(
                _mine(projects, principal_id), projects.c.project_id == request.project_id
            )
        ).scalar_one_or_none()
        if owned is None:
            raise _refuse(ScheduleAdmissionRefusal.PROJECT_NOT_FOUND)

    def _require_source(self, principal_id: str, request: ScheduleImportRequest) -> None:
        enrollment = self._connection.execute(
            select(enrollments.c.media_types).where(
                _mine(enrollments, principal_id),
                enrollments.c.enrollment_id == request.enrollment_id,
            )
        ).one_or_none()
        if enrollment is None:
            raise _refuse(ScheduleAdmissionRefusal.ENROLLMENT_NOT_FOUND)
        enrolled = self._connection.execute(
            select(enrollment_objects.c.source_object_id)
            .join(enrollments, enrollments.c.enrollment_id == enrollment_objects.c.enrollment_id)
            .where(
                _mine(enrollments, principal_id),
                enrollment_objects.c.enrollment_id == request.enrollment_id,
                enrollment_objects.c.source_object_id == request.source_object_id,
            )
        ).scalar_one_or_none()
        if enrolled is None:
            raise _refuse(ScheduleAdmissionRefusal.SOURCE_OBJECT_NOT_ENROLLED)
        version = self._connection.execute(
            select(source_object_versions.c.media_type, source_object_versions.c.size_bytes).where(
                source_object_versions.c.version_id == request.source_version_id,
                source_object_versions.c.source_object_id == request.source_object_id,
            )
        ).one_or_none()
        if version is None:
            raise _refuse(ScheduleAdmissionRefusal.SOURCE_VERSION_NOT_FOUND)
        if version.media_type != SCHEDULE_MEDIA_TYPE:
            raise _refuse(ScheduleAdmissionRefusal.UNSUPPORTED_MEDIA_TYPE)
        if SCHEDULE_MEDIA_TYPE not in (enrollment.media_types or ()):
            raise _refuse(ScheduleAdmissionRefusal.MEDIA_TYPE_NOT_ENROLLED)
        if version.size_bytes is not None and version.size_bytes > MAX_SCHEDULE_SOURCE_BYTES:
            raise _refuse(ScheduleAdmissionRefusal.SOURCE_TOO_LARGE)

    def _find_series(
        self, principal_id: str, request: ScheduleImportRequest, request_digest: str
    ) -> ScheduleSeries | None:
        criteria = [
            _mine(schedule_series, principal_id),
            schedule_series.c.project_id == request.project_id,
        ]
        if request.series_auto:
            criteria.append(schedule_series.c.name_key == intake_series_name(request_digest).key)
        elif request.series_name is None:
            criteria.append(schedule_series.c.series_id == request.series_id)
        else:
            criteria.append(schedule_series.c.name_key == request.series_name.key)
        found = self._connection.execute(select(schedule_series).where(*criteria)).mappings()
        row = found.one_or_none()
        # Schedule scenarios S6-2-D08: an explicit Series naming an intake Series
        # is hidden as absent; the intake row, never the name, decides intake-ness.
        if (
            row is not None
            and not request.series_auto
            and self._is_intake_series(principal_id, row["series_id"])
        ):
            raise _refuse(ScheduleAdmissionRefusal.SERIES_NOT_FOUND)
        if row is None and request.series_id is not None:
            raise _refuse(ScheduleAdmissionRefusal.SERIES_NOT_FOUND)
        return None if row is None else _to_series(row, principal_id)

    def _is_intake_series(self, principal_id: str, series_id: str) -> bool:
        marked = self._connection.execute(
            select(schedule_intake_series.c.series_id).where(
                _mine(schedule_intake_series, principal_id),
                schedule_intake_series.c.series_id == series_id,
            )
        ).first()
        return marked is not None

    def _replay_by_version(
        self, principal_id: str, series: ScheduleSeries, request: ScheduleImportRequest
    ) -> ScheduleAdmission | None:
        found = (
            self._connection.execute(
                select(schedule_publications).where(
                    _mine(schedule_publications, principal_id),
                    schedule_publications.c.series_id == series.series_id,
                    schedule_publications.c.source_version_id == request.source_version_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if found is None:
            return None
        baseline = None if request.baseline_kind is None else request.baseline_kind.value
        if (
            found["publication_role"],
            found["baseline_kind"],
            found["expected_data_date"],
            found["supersedes_publication_id"],
        ) != (
            request.publication_role.value,
            baseline,
            request.expected_data_date,
            request.supersedes_publication_id,
        ):
            raise _refuse(ScheduleAdmissionRefusal.SOURCE_VERSION_CONFLICT)
        # Schedule scenarios contract section 14.8.5: a role-`baseline` replay also
        # compares the stored `approve` event's fields with the request's approval.
        approval = request.approval
        if approval is not None and baseline is not None:
            stored = _plane.stored_import_approval(
                self._connection, principal_id, found["publication_id"]
            )
            if stored != (
                baseline,
                approval.approval_reference,
                approval.effective_from,
                approval.reason,
            ):
                raise _refuse(ScheduleAdmissionRefusal.SOURCE_VERSION_CONFLICT)
        return self._replayed(principal_id, found)

    def _require_predecessor(
        self,
        principal_id: str,
        series: ScheduleSeries | None,
        request: ScheduleImportRequest,
    ) -> None:
        if series is None:
            raise _refuse(ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_FOUND)
        predecessor = (
            self._connection.execute(
                select(schedule_publications)
                .where(
                    _mine(schedule_publications, principal_id),
                    schedule_publications.c.publication_id == request.supersedes_publication_id,
                    schedule_publications.c.project_id == request.project_id,
                    schedule_publications.c.series_id == series.series_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if predecessor is None:
            raise _refuse(ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_FOUND)
        if self._effective(principal_id, predecessor) not in TERMINAL_OUTCOMES:
            raise _refuse(ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_TERMINAL)
        if predecessor["source_version_id"] == request.source_version_id:
            raise _refuse(ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_SAME_SOURCE_VERSION)
        successor = self._connection.execute(
            select(schedule_publications.c.publication_id).where(
                _mine(schedule_publications, principal_id),
                schedule_publications.c.supersedes_publication_id
                == request.supersedes_publication_id,
            )
        ).first()
        if successor is not None:
            raise _refuse(ScheduleAdmissionRefusal.SUPERSEDED_PUBLICATION_HAS_SUCCESSOR)

    def _create_series(
        self, principal_id: str, request: ScheduleImportRequest, request_digest: str
    ) -> tuple[ScheduleSeries, bool]:
        name = intake_series_name(request_digest) if request.series_auto else request.series_name
        if name is None:  # `_find_series` has already refused an unknown id
            raise ScheduleIntegrityError("series_not_named")
        created = (
            self._connection.execute(
                pg_insert(schedule_series)
                .values(
                    _bound(
                        schedule_series,
                        principal_id,
                        {
                            "series_id": issue_identifier(IdKind.SCHEDULE_SERIES),
                            "project_id": request.project_id,
                            "name": name.name,
                            "name_key": name.key,
                        },
                    )
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        schedule_series.c.principal_id,
                        schedule_series.c.project_id,
                        schedule_series.c.name_key,
                    ]
                )
                .returning(*schedule_series.c)
            )
            .mappings()
            .one_or_none()
        )
        if created is not None:
            return _to_series(created, principal_id), True
        # A concurrent admission created the same Series and committed first.
        raced = self._find_series(principal_id, request, request_digest)
        if raced is None:
            raise ScheduleIntegrityError("series_race_unresolved")
        return raced, False

    def _classify_lost_race(
        self,
        principal_id: str,
        series: ScheduleSeries,
        request: ScheduleImportRequest,
        request_digest: str,
    ) -> ScheduleAdmission:
        """A concurrent admission won a unique; answer as if it had been seen first."""
        replay = self._replay_by_key(principal_id, request, request_digest)
        if replay is None:
            replay = self._replay_by_version(principal_id, series, request)
        if replay is not None:
            return replay
        if request.supersedes_publication_id is not None:
            self._require_predecessor(principal_id, series, request)
        raise ScheduleIntegrityError("admission_race_unresolved")

    # ---- worker transactions ------------------------------------------------------

    def begin_processing(
        self, principal_id: str, publication_id: str, lease: ScheduleLease
    ) -> SchedulePlan:
        publication = self._held_publication(principal_id, publication_id, lease)
        status = SchedulePublicationStatus(publication["status"])
        if status in TERMINAL_OUTCOMES:
            # R6-F05: a reclaimed attempt after a committed outcome writes
            # nothing and lets the caller complete the job normally.
            return SchedulePlan(
                publication=_to_publication(publication, principal_id),
                attempt=lease.attempt,
                terminal=True,
                max_fetch_bytes=None,
            )
        if status is SchedulePublicationStatus.QUEUED:
            publication = (
                self._connection.execute(
                    update(schedule_publications)
                    .where(
                        _mine(schedule_publications, principal_id),
                        schedule_publications.c.publication_id == publication_id,
                    )
                    .values(
                        status=_PROCESSING,
                        processing_started_at=func.now(),
                        updated_at=func.now(),
                    )
                    .returning(*schedule_publications.c)
                )
                .mappings()
                .one()
            )
        # S5b-2 E-03: the source the worker selects its provider by, read in
        # this same plan transaction from the publication's own enrollment.
        enrollment = self._connection.execute(
            select(enrollments.c.max_bytes, enrollments.c.source_id).where(
                _mine(enrollments, principal_id),
                enrollments.c.enrollment_id == publication["enrollment_id"],
            )
        ).one()
        return SchedulePlan(
            publication=_to_publication(publication, principal_id),
            attempt=lease.attempt,
            terminal=False,
            max_fetch_bytes=min(int(enrollment.max_bytes), MAX_SCHEDULE_SOURCE_BYTES),
            source_id=str(enrollment.source_id),
        )

    def pin_document(
        self,
        principal_id: str,
        publication_id: str,
        lease: ScheduleLease,
        document_sha256: str,
        document_size_bytes: int,
    ) -> None:
        if not _is_sha256(document_sha256):
            raise ValueError("a document digest is 64 lowercase hex characters")
        if isinstance(document_size_bytes, bool) or not (
            0 <= document_size_bytes <= MAX_SCHEDULE_SOURCE_BYTES
        ):
            raise ValueError("a document size is 0 to 16777216 bytes")
        publication = self._held_publication(principal_id, publication_id, lease)
        self._require_processing(publication)
        pinned = publication["document_sha256"]
        if pinned is not None:
            if (pinned, publication["document_size_bytes"]) != (
                document_sha256,
                document_size_bytes,
            ):
                raise ScheduleIntegrityError("document_changed")
            return
        self._connection.execute(
            update(schedule_publications)
            .where(
                _mine(schedule_publications, principal_id),
                schedule_publications.c.publication_id == publication_id,
            )
            .values(
                document_sha256=document_sha256,
                document_size_bytes=document_size_bytes,
                updated_at=func.now(),
            )
        )

    def start_parser_run(
        self,
        principal_id: str,
        publication_id: str,
        lease: ScheduleLease,
        identity: ScheduleParserIdentity,
    ) -> ScheduleParserRunStart:
        publication = self._held_publication(principal_id, publication_id, lease)
        self._require_processing(publication)
        document = publication["document_sha256"]
        if document is None:
            raise ScheduleIntegrityError("document_not_pinned")
        runs = schedule_parser_runs
        mine = [_mine(runs, principal_id), runs.c.publication_id == publication_id]
        # FR6-F03: reuse is keyed by exactly the columns of
        # `a_schedule_parse_is_accepted_once` -- parser, profile and document,
        # not the PDFium engine versions, which the canonical result digest
        # deliberately excludes (S5a section 6.4). One rule, one key: a parsed
        # run survives an engine upgrade between attempts instead of colliding
        # with the unique on every later attempt.
        reusable = (
            self._connection.execute(
                select(runs).where(
                    *mine,
                    runs.c.status == _PARSED,
                    runs.c.parser_name == identity.parser_name,
                    runs.c.parser_version == identity.parser_version,
                    runs.c.profile_id == identity.profile_id,
                    runs.c.profile_version == identity.profile_version,
                    runs.c.document_sha256 == document,
                )
            )
            .mappings()
            .one_or_none()
        )
        if reusable is not None:
            return ScheduleParserRunStart(run=_to_run(reusable, principal_id), reused=True)
        this_attempt = (
            self._connection.execute(
                select(runs).where(*mine, runs.c.attempt_number == lease.attempt)
            )
            .mappings()
            .one_or_none()
        )
        if this_attempt is not None:
            if this_attempt["status"] != _RUNNING:
                raise ScheduleIntegrityError("attempt_already_ran")
            return ScheduleParserRunStart(run=_to_run(this_attempt, principal_id), reused=True)
        self._connection.execute(
            update(runs)
            .where(*mine, runs.c.status == _RUNNING, runs.c.attempt_number < lease.attempt)
            .values(status=_FAILED_RUN, completed_at=func.now())
        )
        started = (
            self._connection.execute(
                insert(runs)
                .values(
                    _bound(
                        runs,
                        principal_id,
                        {
                            "parser_run_id": issue_identifier(IdKind.SCHEDULE_PARSER_RUN),
                            "project_id": publication["project_id"],
                            "series_id": publication["series_id"],
                            "publication_id": publication_id,
                            "operation_id": lease.operation_id,
                            "attempt_number": lease.attempt,
                            "parser_name": identity.parser_name,
                            "parser_version": identity.parser_version,
                            "profile_id": identity.profile_id,
                            "profile_version": identity.profile_version,
                            "pypdfium2_version": identity.pypdfium2_version,
                            "pdfium_version": identity.pdfium_version,
                            "document_sha256": document,
                        },
                    )
                )
                .returning(*runs.c)
            )
            .mappings()
            .one()
        )
        return ScheduleParserRunStart(run=_to_run(started, principal_id), reused=False)

    def insert_rows(
        self,
        principal_id: str,
        parser_run_id: str,
        lease: ScheduleLease,
        rows: Sequence[ParsedScheduleRow],
    ) -> int:
        if not 1 <= len(rows) <= MAX_SCHEDULE_BATCH:
            raise ValueError("a row batch holds 1 to 1000 rows")
        for row in rows:
            validate_row_for_persistence(row)
        run = self._held_run(principal_id, parser_run_id, lease)
        if run["status"] != _RUNNING:
            raise ScheduleIntegrityError("parser_run_not_running")
        stored = schedule_rows
        mine = [_mine(stored, principal_id), stored.c.parser_run_id == parser_run_id]
        last = int(
            self._connection.execute(
                select(func.coalesce(func.max(stored.c.row_ordinal), 0)).where(*mine)
            ).scalar_one()
        )
        # R6-F04: the parser's ordinals are stored verbatim, so a batch must
        # continue the run exactly where the stored rows end.
        if [row.row_ordinal for row in rows] != list(range(last + 1, last + 1 + len(rows))):
            raise ScheduleIntegrityError("row_ordinal_gap")
        issued = {row.row_ordinal: issue_identifier(IdKind.SCHEDULE_ROW) for row in rows}
        earlier = {
            row.parent_row_ordinal
            for row in rows
            if row.parent_row_ordinal is not None and row.parent_row_ordinal not in issued
        }
        parents: dict[int, str] = dict(issued)
        if earlier:
            parents.update(
                (int(ordinal), str(row_id))
                for ordinal, row_id in self._connection.execute(
                    select(stored.c.row_ordinal, stored.c.row_id).where(
                        *mine, stored.c.row_ordinal.in_(sorted(earlier))
                    )
                )
            )
        values: list[dict[str, Any]] = []
        for row in rows:
            parent = row.parent_row_ordinal
            if parent is not None and parent not in parents:
                raise ScheduleIntegrityError("parent_row_missing")
            values.append(
                _bound(
                    stored,
                    principal_id,
                    _row_values(
                        row,
                        row_id=issued[row.row_ordinal],
                        parent_row_id=None if parent is None else parents[parent],
                        run=run,
                    ),
                )
            )
        self._connection.execute(insert(stored).values(values))
        return len(values)

    def insert_issues(
        self,
        principal_id: str,
        publication_id: str,
        lease: ScheduleLease,
        parser_run_id: str | None,
        issues: Sequence[ScheduleParseIssue],
    ) -> int:
        if not 0 < len(issues) <= MAX_SCHEDULE_BATCH:
            raise ValueError("an issue batch holds 1 to 1000 issues")
        if parser_run_id is None and any(issue.row_ordinal is not None for issue in issues):
            raise ValueError("an issue naming a row names its parser run")
        self._hold(lease)
        self._job_names(principal_id, lease, publication_id)
        publication = self._publication(principal_id, publication_id)
        if publication is None:
            raise ScheduleIntegrityError("publication_not_found")
        self._require_processing(publication)
        if parser_run_id is not None:
            run = self._run(principal_id, parser_run_id)
            if run is None or run["publication_id"] != publication_id:
                raise ScheduleIntegrityError("parser_run_not_found")
            if run["status"] != _RUNNING:
                raise ScheduleIntegrityError("parser_run_not_running")
        self._connection.execute(
            insert(schedule_import_issues).values(
                [
                    _bound(
                        schedule_import_issues,
                        principal_id,
                        {
                            "issue_id": issue_identifier(IdKind.SCHEDULE_IMPORT_ISSUE),
                            "project_id": publication["project_id"],
                            "series_id": publication["series_id"],
                            "publication_id": publication_id,
                            "parser_run_id": parser_run_id,
                            "severity": issue.severity.value,
                            "code": issue.code.value,
                            "page_number": issue.page_number,
                            "row_ordinal": issue.row_ordinal,
                            "field": None if issue.field is None else issue.field.value,
                        },
                    )
                    for issue in issues
                ]
            )
        )
        return len(issues)

    def _stored_counts(self, principal_id: str, parser_run_id: str) -> dict[str, int]:
        """Rows, ID-bearing rows, ambiguous rows, issues and warnings of one run."""
        rows = schedule_rows
        issues = schedule_import_issues
        row_counts = select(
            func.count().label("rows"),
            func.count().filter(rows.c.row_type.in_(_LINKABLE)).label("activities"),
            func.count()
            .filter(rows.c.row_type == ScheduleRowType.AMBIGUOUS.value)
            .label("ambiguous"),
            func.count()
            .filter(rows.c.row_type.in_(_LINKABLE), rows.c.schedule_activity_id.is_(None))
            .label("unlinked"),
            func.count().filter(rows.c.schedule_activity_id.is_not(None)).label("linked"),
        ).where(_mine(rows, principal_id), rows.c.parser_run_id == parser_run_id)
        issue_counts = select(
            func.count().label("issues"),
            func.count()
            .filter(issues.c.severity == ScheduleIssueSeverity.WARNING.value)
            .label("warnings"),
        ).where(_mine(issues, principal_id), issues.c.parser_run_id == parser_run_id)
        counted = dict(self._connection.execute(row_counts).mappings().one())
        counted.update(self._connection.execute(issue_counts).mappings().one())
        return {name: int(value) for name, value in counted.items()}

    def finish_parser_run(
        self,
        principal_id: str,
        parser_run_id: str,
        lease: ScheduleLease,
        *,
        parsed: ScheduleParseCounts | None,
        parse_result_sha256: str | None,
        failure_code: ScheduleIssueCode | None,
    ) -> ScheduleParserRun:
        if (parsed is None) == (failure_code is None):
            raise ValueError("a parser run ends parsed or with a failure code, not both")
        if (parsed is None) != (parse_result_sha256 is None):
            raise ValueError("a parsed run carries its result digest, a failed one none")
        if parse_result_sha256 is not None and not _is_sha256(parse_result_sha256):
            raise ValueError("a parse result digest is 64 lowercase hex characters")
        run = self._held_run(principal_id, parser_run_id, lease)
        if run["status"] != _RUNNING:
            raise ScheduleIntegrityError("parser_run_not_running")
        values: dict[str, object]
        if parsed is not None:
            stored = self._stored_counts(principal_id, parser_run_id)
            if (stored["rows"], stored["issues"], stored["warnings"]) != (
                parsed.rows,
                parsed.issues,
                parsed.warnings,
            ):
                raise ScheduleIntegrityError("count_mismatch")
            if self._outcome(parser_run_id) is SchedulePublicationStatus.FAILED:
                raise ScheduleIntegrityError("failed_outcome")
            values = {
                "status": _PARSED,
                "page_count": parsed.pages,
                "row_count": parsed.rows,
                "issue_count": parsed.issues,
                "warning_count": parsed.warnings,
                "parse_result_sha256": parse_result_sha256,
            }
        elif failure_code is not None:
            values = {"status": _FAILED_RUN, "failure_code": failure_code.value}
        finished = (
            self._connection.execute(
                update(schedule_parser_runs)
                .where(
                    _mine(schedule_parser_runs, principal_id),
                    schedule_parser_runs.c.parser_run_id == parser_run_id,
                )
                .values(completed_at=func.now(), **values)
                .returning(*schedule_parser_runs.c)
            )
            .mappings()
            .one()
        )
        return _to_run(finished, principal_id)

    def canonicalize_batch(
        self,
        principal_id: str,
        parser_run_id: str,
        lease: ScheduleLease,
        limit: int = MAX_SCHEDULE_BATCH,
    ) -> ScheduleCanonicalizationProgress:
        if not 1 <= limit <= MAX_SCHEDULE_BATCH:
            raise ValueError("a canonicalization batch links 1 to 1000 rows")
        run = self._held_run(principal_id, parser_run_id, lease)
        if run["status"] != _PARSED:
            raise ScheduleIntegrityError("parser_run_not_parsed")
        publication = self._publication(principal_id, run["publication_id"])
        if publication is None:
            raise ScheduleIntegrityError("publication_not_found")
        self._require_processing(publication)
        rows = schedule_rows
        linkable = [
            _mine(rows, principal_id),
            rows.c.parser_run_id == parser_run_id,
            rows.c.row_type.in_(_LINKABLE),
        ]
        # R6-F01: only a `complete`/`partial` outcome with unique IDs links.
        if self._outcome(parser_run_id) not in (
            SchedulePublicationStatus.COMPLETE,
            SchedulePublicationStatus.PARTIAL,
        ):
            raise ScheduleIntegrityError("identity_gate")
        duplicated = self._connection.execute(
            select(rows.c.published_activity_id)
            .where(*linkable)
            .group_by(rows.c.published_activity_id)
            .having(func.count() > 1)
            .limit(1)
        ).first()
        if duplicated is not None:
            raise ScheduleIntegrityError("identity_gate")
        batch = self._connection.execute(
            select(rows.c.row_id, rows.c.published_activity_id)
            .where(*linkable, rows.c.schedule_activity_id.is_(None))
            .order_by(rows.c.row_ordinal)
            .limit(limit)
        ).all()
        if not batch:
            return ScheduleCanonicalizationProgress(linked=0, created=0, remaining=0)
        # R6-F12: published-ID order, so two canonicalizations of one Series
        # take the unique index's locks in one order.
        published = sorted({str(row.published_activity_id) for row in batch})
        created = self._connection.execute(
            pg_insert(schedule_activities)
            .values(
                [
                    _bound(
                        schedule_activities,
                        principal_id,
                        {
                            "schedule_activity_id": issue_identifier(IdKind.SCHEDULE_ACTIVITY),
                            "project_id": run["project_id"],
                            "series_id": run["series_id"],
                            "published_activity_id": published_id,
                        },
                    )
                    for published_id in published
                ]
            )
            .on_conflict_do_nothing(
                index_elements=[
                    schedule_activities.c.principal_id,
                    schedule_activities.c.series_id,
                    schedule_activities.c.published_activity_id,
                ]
            )
            .returning(schedule_activities.c.schedule_activity_id)
        ).all()
        activities = schedule_activities
        linked = self._connection.execute(
            update(rows)
            .where(
                _mine(rows, principal_id),
                _mine(activities, principal_id),
                matching_partition_criterion(activities, rows),
                rows.c.row_id.in_([row.row_id for row in batch]),
                rows.c.schedule_activity_id.is_(None),
                activities.c.series_id == rows.c.series_id,
                activities.c.published_activity_id == rows.c.published_activity_id,
            )
            .values(schedule_activity_id=activities.c.schedule_activity_id)
        ).rowcount
        remaining = self._connection.execute(
            select(func.count())
            .select_from(rows)
            .where(*linkable, rows.c.schedule_activity_id.is_(None))
        ).scalar_one()
        return ScheduleCanonicalizationProgress(
            linked=int(linked), created=len(created), remaining=int(remaining)
        )

    def finalize_publication(
        self,
        principal_id: str,
        publication_id: str,
        lease: ScheduleLease,
        finalization: ScheduleFinalization,
    ) -> SchedulePublication:
        publication = self._held_publication(principal_id, publication_id, lease)
        self._require_processing(publication)
        accepted = finalization.accepted_parser_run_id
        run = self._run(principal_id, accepted)
        if run is None or run["publication_id"] != publication_id:
            raise ScheduleIntegrityError("parser_run_not_found")
        if run["status"] != _PARSED:
            raise ScheduleIntegrityError("parser_run_not_parsed")
        # FR6-F01: a run-less issue (a fetch-time condition such as
        # `source_version_changed`) exists only for the fail path; F3 refuses
        # every success terminal while one is recorded.
        issues = schedule_import_issues
        run_less = self._connection.execute(
            select(issues.c.issue_id)
            .where(
                _mine(issues, principal_id),
                issues.c.publication_id == publication_id,
                issues.c.parser_run_id.is_(None),
            )
            .limit(1)
        ).first()
        if run_less is not None:
            raise ScheduleIntegrityError("run_less_issue")
        # R6-F01: the terminal status is the run's derived outcome, never the
        # caller's choice; a `failed` outcome cannot be accepted at all.
        status = self._outcome(accepted)
        if status is SchedulePublicationStatus.FAILED:
            raise ScheduleIntegrityError("status_mismatch")
        stored = self._stored_counts(principal_id, accepted)
        if (
            status in (SchedulePublicationStatus.COMPLETE, SchedulePublicationStatus.PARTIAL)
            and stored["unlinked"]
        ) or (status is SchedulePublicationStatus.REVIEW_REQUIRED and stored["linked"]):
            raise ScheduleIntegrityError("incomplete_canonicalization")
        # R6-F03: no run is left running under a terminal publication.
        self._close_running_runs(principal_id, publication_id, except_run=accepted)
        finished = (
            self._connection.execute(
                update(schedule_publications)
                .where(
                    _mine(schedule_publications, principal_id),
                    schedule_publications.c.publication_id == publication_id,
                )
                .values(
                    status=status.value,
                    accepted_parser_run_id=accepted,
                    page_count=run["page_count"],
                    row_count=stored["rows"],
                    activity_count=stored["activities"],
                    ambiguous_row_count=stored["ambiguous"],
                    issue_count=stored["issues"],
                    published_schedule_title=finalization.published_schedule_title,
                    data_date=finalization.data_date,
                    run_date=finalization.run_date,
                    completed_at=func.now(),
                    updated_at=func.now(),
                )
                .returning(*schedule_publications.c)
            )
            .mappings()
            .one()
        )
        return _to_publication(finished, principal_id)

    def fail_publication(
        self,
        principal_id: str,
        publication_id: str,
        lease: ScheduleLease,
        code: ScheduleIssueCode,
        parser_run_id: str | None,
    ) -> SchedulePublication:
        if ISSUE_SEVERITY[code] is not ScheduleIssueSeverity.ERROR:
            raise ValueError("a publication fails only on an error code")
        publication = self._held_publication(principal_id, publication_id, lease)
        self._require_processing(publication)
        runs = schedule_parser_runs
        if parser_run_id is not None:
            run = self._run(principal_id, parser_run_id)
            if run is None or run["publication_id"] != publication_id:
                raise ScheduleIntegrityError("parser_run_not_found")
            if run["status"] != _RUNNING:
                raise ScheduleIntegrityError("parser_run_not_running")
        issues = schedule_import_issues
        recorded = self._connection.execute(
            select(issues.c.issue_id).where(
                _mine(issues, principal_id),
                issues.c.publication_id == publication_id,
                issues.c.code == code.value,
                issues.c.parser_run_id.is_not_distinct_from(parser_run_id),
            )
        ).first()
        if recorded is None:
            self._connection.execute(
                insert(issues).values(
                    _bound(
                        issues,
                        principal_id,
                        {
                            "issue_id": issue_identifier(IdKind.SCHEDULE_IMPORT_ISSUE),
                            "project_id": publication["project_id"],
                            "series_id": publication["series_id"],
                            "publication_id": publication_id,
                            "parser_run_id": parser_run_id,
                            "severity": ScheduleIssueSeverity.ERROR.value,
                            "code": code.value,
                        },
                    )
                )
            )
        if parser_run_id is not None:
            self._connection.execute(
                update(runs)
                .where(_mine(runs, principal_id), runs.c.parser_run_id == parser_run_id)
                .values(status=_FAILED_RUN, failure_code=code.value, completed_at=func.now())
            )
        # R6-F03: every other attempt's run ends with this publication.
        self._close_running_runs(principal_id, publication_id)
        issue_count = self._connection.execute(
            select(func.count())
            .select_from(issues)
            .where(_mine(issues, principal_id), issues.c.publication_id == publication_id)
        ).scalar_one()
        failed = (
            self._connection.execute(
                update(schedule_publications)
                .where(
                    _mine(schedule_publications, principal_id),
                    schedule_publications.c.publication_id == publication_id,
                )
                .values(
                    status=SchedulePublicationStatus.FAILED.value,
                    issue_count=int(issue_count),
                    completed_at=func.now(),
                    updated_at=func.now(),
                )
                .returning(*schedule_publications.c)
            )
            .mappings()
            .one()
        )
        return _to_publication(failed, principal_id)

    # ---- point reads ------------------------------------------------------------

    def get_series(self, principal_id: str, series_id: str) -> ScheduleSeries | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        row = self._series_row(principal_id, series_id)
        return None if row is None else _to_series(row, principal_id)

    def get_publication(self, principal_id: str, publication_id: str) -> SchedulePublication | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        row = self._publication(principal_id, publication_id)
        return None if row is None else _to_publication(row, principal_id)

    def get_effective_status(
        self, principal_id: str, publication_id: str
    ) -> SchedulePublicationStatus | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        row = self._publication(principal_id, publication_id)
        return None if row is None else self._effective(principal_id, row)

    def get_parser_runs(
        self, principal_id: str, publication_id: str
    ) -> tuple[ScheduleParserRun, ...]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        found = self._connection.execute(
            select(schedule_parser_runs)
            .where(
                _mine(schedule_parser_runs, principal_id),
                schedule_parser_runs.c.publication_id == publication_id,
            )
            .order_by(schedule_parser_runs.c.attempt_number)
        ).mappings()
        return tuple(_to_run(row, principal_id) for row in found)

    def count_parser_run_contents(self, principal_id: str, parser_run_id: str) -> tuple[int, int]:
        # S5b-2 contract 3.3.1 H6 (R7-N2, R7-N3): the worker reads this before
        # any write to a `running` run returned to it, because `insert_issues`
        # has no ordinal guard and a resumed run would duplicate its issues.
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        rows = self._connection.execute(
            select(func.count())
            .select_from(schedule_rows)
            .where(
                _mine(schedule_rows, principal_id), schedule_rows.c.parser_run_id == parser_run_id
            )
        ).scalar_one()
        issues = self._connection.execute(
            select(func.count())
            .select_from(schedule_import_issues)
            .where(
                _mine(schedule_import_issues, principal_id),
                schedule_import_issues.c.parser_run_id == parser_run_id,
            )
        ).scalar_one()
        return int(rows), int(issues)

    # ---- S5b-2 reads (worker contract sections 3.9, 3.10 and 4.3) ---------------
    #
    # Every statement composes `_mine` on every partitioned table it names and
    # `matching_partition_criterion` on every join of two; a root of another
    # Principal therefore reads exactly as an absent one, from one statement.

    def owns_project(self, principal_id: str, project_id: str) -> bool:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        found = self._connection.execute(
            select(projects.c.project_id).where(
                _mine(projects, principal_id), projects.c.project_id == project_id
            )
        ).scalar_one_or_none()
        return found is not None

    def list_series(
        self,
        principal_id: str,
        project_id: str,
        *,
        after: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[ScheduleSeriesSummary, ...]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        series = schedule_series
        statement = select(series).where(
            _mine(series, principal_id), series.c.project_id == project_id
        )
        if after is not None:
            statement = statement.where(
                tuple_(series.c.created_at, series.c.series_id) < _position(after)
            )
        found = (
            self._connection.execute(
                statement.order_by(series.c.created_at.desc(), series.c.series_id.desc()).limit(
                    limit
                )
            )
            .mappings()
            .all()
        )
        if not found:
            return ()
        ids = [row["series_id"] for row in found]
        pubs = schedule_publications
        counts = {
            str(series_id): int(count)
            for series_id, count in self._connection.execute(
                select(pubs.c.series_id, func.count())
                .where(_mine(pubs, principal_id), pubs.c.series_id.in_(ids))
                .group_by(pubs.c.series_id)
            )
        }
        latest = {
            str(row["series_id"]): self._latest_update(row)
            for row in self._connection.execute(
                select(*_BOUND_PUBLICATION_COLUMNS, enrollments.c.source_id)
                .select_from(_bound_join(pubs))
                .where(
                    *_bound_criteria(principal_id),
                    pubs.c.series_id.in_(ids),
                    pubs.c.publication_role == SchedulePublicationRole.UPDATE.value,
                    pubs.c.status.in_(_ELIGIBLE),
                )
                .order_by(
                    pubs.c.series_id,
                    pubs.c.data_date.desc(),
                    pubs.c.admitted_at.desc(),
                    pubs.c.publication_id.desc(),
                )
                .distinct(pubs.c.series_id)
            ).mappings()
        }
        return tuple(
            ScheduleSeriesSummary(
                series_id=row["series_id"],
                name=row["name"],
                created_at=row["created_at"],
                publication_count=counts.get(row["series_id"], 0),
                latest_update=latest.get(row["series_id"]),
            )
            for row in found
        )

    @staticmethod
    def _latest_update(row: RowMapping) -> ScheduleLatestUpdate:
        return ScheduleLatestUpdate(
            publication_id=row["publication_id"],
            data_date=_eligible_data_date(row["data_date"]),
            status=SchedulePublicationStatus(row["status"]),
            source=_source_binding(row),
        )

    def list_publications(
        self,
        principal_id: str,
        series_id: str,
        *,
        role: SchedulePublicationRole | None,
        status: SchedulePublicationStatus | None,
        after: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[SchedulePublicationSummary, ...]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        pubs = schedule_publications
        jobs = schedule_jobs
        runs = schedule_parser_runs
        effective = _effective_status_column()
        statement = (
            select(
                *pubs.c,
                effective.label("effective_status"),
                jobs.c.operation_id,
                enrollments.c.source_id,
                runs.c.parser_name,
                runs.c.parser_version,
                runs.c.profile_id,
                runs.c.profile_version,
                runs.c.pypdfium2_version,
                runs.c.pdfium_version,
            )
            .select_from(
                _bound_join(pubs)
                .join(jobs, jobs.c.publication_id == pubs.c.publication_id)
                .outerjoin(
                    runs,
                    and_(
                        runs.c.parser_run_id == pubs.c.accepted_parser_run_id,
                        _mine(runs, principal_id),
                        matching_partition_criterion(runs, pubs),
                    ),
                )
            )
            .where(
                *_bound_criteria(principal_id),
                _mine(jobs, principal_id),
                matching_partition_criterion(jobs, pubs),
                pubs.c.series_id == series_id,
            )
        )
        if role is not None:
            statement = statement.where(pubs.c.publication_role == role.value)
        if status is not None:
            statement = statement.where(effective == status.value)
        if after is not None:
            statement = statement.where(
                tuple_(pubs.c.admitted_at, pubs.c.publication_id) < _position(after)
            )
        found = self._connection.execute(
            statement.order_by(pubs.c.admitted_at.desc(), pubs.c.publication_id.desc()).limit(limit)
        ).mappings()
        return tuple(
            SchedulePublicationSummary(
                publication=_to_publication(row, principal_id),
                effective_status=SchedulePublicationStatus(row["effective_status"]),
                operation_id=row["operation_id"],
                source=_source_binding(row),
                accepted_parser=(
                    None
                    if row["accepted_parser_run_id"] is None
                    else ScheduleParserIdentity(
                        parser_name=row["parser_name"],
                        parser_version=row["parser_version"],
                        profile_id=row["profile_id"],
                        profile_version=row["profile_version"],
                        pypdfium2_version=row["pypdfium2_version"],
                        pdfium_version=row["pdfium_version"],
                    )
                ),
            )
            for row in found
        )

    def get_publication_detail(
        self, principal_id: str, publication_id: str
    ) -> SchedulePublicationDetail | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        pubs = schedule_publications
        found = (
            self._connection.execute(
                select(*pubs.c, enrollments.c.source_id)
                .select_from(_bound_join(pubs))
                .where(*_bound_criteria(principal_id), pubs.c.publication_id == publication_id)
            )
            .mappings()
            .one_or_none()
        )
        if found is None:
            return None
        jobs = schedule_jobs
        job = (
            self._connection.execute(
                select(
                    jobs.c.operation_id,
                    case(
                        (job_is_effectively_failed(SCHEDULE_JOBS), JobState.FAILED.value),
                        else_=jobs.c.state,
                    ).label("state"),
                    jobs.c.attempt_count,
                    jobs.c.max_attempts,
                    jobs.c.last_error_code,
                ).where(_mine(jobs, principal_id), jobs.c.publication_id == publication_id)
            )
            .mappings()
            .one_or_none()
        )
        if job is None:
            raise ScheduleIntegrityError("publication_without_job")
        issues = schedule_import_issues
        counted = select(issues.c.code, func.count()).where(
            _mine(issues, principal_id), issues.c.publication_id == publication_id
        )
        # RR1-I01: an accepted publication counts its accepted run's issues
        # only; a failed or unfinished one counts every issue recorded so far.
        if found["status"] in _ACCEPTED:
            counted = counted.where(issues.c.parser_run_id == found["accepted_parser_run_id"])
        issue_counts = {
            ScheduleIssueCode(code): int(count)
            for code, count in self._connection.execute(counted.group_by(issues.c.code))
        }
        persisted = SchedulePublicationStatus(found["status"])
        return SchedulePublicationDetail(
            publication=_to_publication(found, principal_id),
            effective_status=effective_publication_status(
                persisted, job_failed=job["state"] == JobState.FAILED.value
            ),
            job=ScheduleJobView(
                operation_id=job["operation_id"],
                state=job["state"],
                attempt_count=job["attempt_count"],
                max_attempts=job["max_attempts"],
                last_error_code=job["last_error_code"],
            ),
            runs=self.get_parser_runs(principal_id, publication_id),
            issue_counts=MappingProxyType(
                {code: issue_counts[code] for code in ScheduleIssueCode if code in issue_counts}
            ),
            source=_source_binding(found),
        )

    def list_activity_rows(
        self,
        principal_id: str,
        publication_id: str,
        *,
        row_type: ScheduleRowType | None,
        hierarchy_prefix: tuple[str, ...] | None,
        start_range: tuple[date | None, date | None],
        finish_range: tuple[date | None, date | None],
        after: tuple[int, str] | None,
        limit: int,
    ) -> tuple[ScheduleActivityRowView, ...]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        rows = schedule_rows
        statement = (
            select(rows)
            .select_from(_accepted_rows())
            .where(
                *_accepted_criteria(principal_id),
                rows.c.publication_id == publication_id,
                rows.c.row_type.in_(
                    _LINKABLE if row_type is None else (row_type.value,),
                ),
            )
        )
        if hierarchy_prefix is not None:
            statement = statement.where(
                rows.c.hierarchy_path[1 : len(hierarchy_prefix)] == list(hierarchy_prefix)
            )
        for state, value, (low, high) in (
            (rows.c.start_state, rows.c.start_date, start_range),
            (rows.c.finish_state, rows.c.finish_date, finish_range),
        ):
            # A date bound matches only a published value (contract 3.9).
            if low is not None or high is not None:
                statement = statement.where(state == ScheduleCellState.PUBLISHED_VALUE.value)
            if low is not None:
                statement = statement.where(value >= low)
            if high is not None:
                statement = statement.where(value <= high)
        if after is not None:
            statement = statement.where(
                tuple_(rows.c.row_ordinal, rows.c.row_id) > _position(after)
            )
        found = self._connection.execute(
            statement.order_by(rows.c.row_ordinal, rows.c.row_id).limit(limit)
        ).mappings()
        return tuple(_to_activity_row(row) for row in found)

    def activity_is_visible(
        self, principal_id: str, schedule_activity_id: str
    ) -> StableScheduleActivity | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        activities = schedule_activities
        rows = schedule_rows
        observed = (
            select(rows.c.row_id)
            .select_from(_accepted_rows())
            .where(
                *_accepted_criteria(principal_id),
                matching_partition_criterion(rows, activities),
                rows.c.schedule_activity_id == activities.c.schedule_activity_id,
            )
            .exists()
        )
        found = (
            self._connection.execute(
                select(activities).where(
                    _mine(activities, principal_id),
                    activities.c.schedule_activity_id == schedule_activity_id,
                    observed,
                )
            )
            .mappings()
            .one_or_none()
        )
        if found is None:
            return None
        return StableScheduleActivity(
            schedule_activity_id=found["schedule_activity_id"],
            principal_id=principal_id,
            project_id=found["project_id"],
            series_id=found["series_id"],
            published_activity_id=found["published_activity_id"],
            created_at=found["created_at"],
        )

    def activity_history(
        self,
        principal_id: str,
        schedule_activity_id: str,
        *,
        after: tuple[date, datetime, str] | None,
        limit: int,
    ) -> tuple[ScheduleActivityObservation, ...]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        rows = schedule_rows
        pubs = schedule_publications
        statement = (
            select(
                *_ROW_CONTENT_COLUMNS,
                pubs.c.publication_id,
                pubs.c.publication_role,
                pubs.c.baseline_kind,
                pubs.c.status,
                pubs.c.data_date,
                pubs.c.admitted_at,
                pubs.c.enrollment_id,
                pubs.c.source_object_id,
                pubs.c.source_version_id,
                enrollments.c.source_id,
            )
            .select_from(
                _accepted_rows().join(
                    enrollments, enrollments.c.enrollment_id == pubs.c.enrollment_id
                )
            )
            .where(
                *_accepted_criteria(principal_id),
                _mine(enrollments, principal_id),
                matching_partition_criterion(pubs, enrollments),
                rows.c.schedule_activity_id == schedule_activity_id,
            )
        )
        if after is not None:
            statement = statement.where(
                tuple_(pubs.c.data_date, pubs.c.admitted_at, pubs.c.publication_id)
                > _position(after)
            )
        found = self._connection.execute(
            statement.order_by(pubs.c.data_date, pubs.c.admitted_at, pubs.c.publication_id).limit(
                limit
            )
        ).mappings()
        return tuple(
            ScheduleActivityObservation(
                publication_id=row["publication_id"],
                publication_role=SchedulePublicationRole(row["publication_role"]),
                baseline_kind=(
                    None
                    if row["baseline_kind"] is None
                    else ScheduleBaselineKind(row["baseline_kind"])
                ),
                status=SchedulePublicationStatus(row["status"]),
                data_date=_eligible_data_date(row["data_date"]),
                admitted_at=row["admitted_at"],
                activity_name=row["activity_name"],
                row_type=ScheduleRowType(row["row_type"]),
                hierarchy_path=_path(row["hierarchy_path"]),
                original_duration=_duration(row["od_state"], row["od_value"]),
                remaining_duration=_duration(row["rd_state"], row["rd_value"]),
                start=_date(row["start_state"], row["start_date"], row["start_marker"]),
                finish=_date(row["finish_state"], row["finish_date"], row["finish_marker"]),
                source=_source_binding(row),
            )
            for row in found
        )

    def comparison_rows(
        self, principal_id: str, publication_id: str
    ) -> Iterator[ScheduleComparisonRow]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        rows = schedule_rows
        statement = (
            select(*_ROW_CONTENT_COLUMNS)
            .select_from(_accepted_rows())
            .where(
                *_accepted_criteria(principal_id),
                rows.c.publication_id == publication_id,
                rows.c.row_type.in_(_LINKABLE),
            )
            # Byte order of UTF-8 = code-point order = the merge's `str` order.
            .order_by(rows.c.published_activity_id.collate("C"))
        )
        found = self._connection.execution_options(yield_per=MAX_SCHEDULE_BATCH).execute(statement)
        for row in found.mappings():
            activity = row["schedule_activity_id"]
            if activity is None:
                raise ScheduleIntegrityError("eligible_row_unlinked")
            yield ScheduleComparisonRow(
                schedule_activity_id=activity,
                published_activity_id=row["published_activity_id"],
                activity_name=row["activity_name"],
                row_type=ScheduleRowType(row["row_type"]),
                hierarchy_path=_path(row["hierarchy_path"]),
                original_duration=_duration(row["od_state"], row["od_value"]),
                remaining_duration=_duration(row["rd_state"], row["rd_value"]),
                start=_date(row["start_state"], row["start_date"], row["start_marker"]),
                finish=_date(row["finish_state"], row["finish_date"], row["finish_marker"]),
            )

    def prior_observations(
        self,
        principal_id: str,
        series_id: str,
        *,
        before: tuple[date, datetime, str],
        schedule_activity_ids: frozenset[str],
    ) -> frozenset[str]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if not schedule_activity_ids:
            return frozenset()
        rows = schedule_rows
        pubs = schedule_publications
        found = self._connection.execute(
            select(rows.c.schedule_activity_id)
            .distinct()
            .select_from(_accepted_rows())
            .where(
                *_accepted_criteria(principal_id),
                pubs.c.series_id == series_id,
                tuple_(pubs.c.data_date, pubs.c.admitted_at, pubs.c.publication_id)
                < _position(before),
                rows.c.schedule_activity_id
                == any_(
                    bindparam(
                        "schedule_activity_ids",
                        value=sorted(schedule_activity_ids),
                        type_=ARRAY(Text),
                    )
                ),
            )
        ).scalars()
        return frozenset(str(found_id) for found_id in found)


class SqlAlchemyScheduleUnitOfWork(ScheduleUnitOfWork):
    """One PostgreSQL transaction over the Schedule foundation tables.

    The `SqlAlchemyConstraintManagementUnitOfWork` shape minus its Record Event
    buffer and Project repository (D-21): the unit of work owns
    `engine.begin()`, and the repository it hands out issues statements on that
    connection and never commits. The engine's default isolation (`READ
    COMMITTED`) is used; races are resolved by the uniques, the `ON CONFLICT DO
    NOTHING` re-reads and the predecessor's `FOR UPDATE`.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._context: AbstractContextManager[Connection] | None = None
        self._connection: Connection | None = None

    def __enter__(self) -> ScheduleUnitOfWork:
        if self._context is not None:
            raise RuntimeError("this unit of work is already inside a transaction")
        context = self._engine.begin()
        self._connection = context.__enter__()
        self._context = context
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        context = self._context
        self._context = None
        self._connection = None
        if context is not None:
            context.__exit__(exc_type, exc, traceback)

    @property
    def schedules(self) -> ScheduleRepository:
        connection = self._connection
        if connection is None:
            raise RuntimeError("this unit of work is not inside a transaction")
        return SqlScheduleRepository(connection)
