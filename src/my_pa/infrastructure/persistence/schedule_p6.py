"""P6 XER admission and worker transactions over the S5 and S7-2 tables (S7-3).

Contract `docs/architecture/schedule-xer-import-contract.md` sections 8.2
(storage), 9.1 (admission), 9.3 (worker H1-H8) and 11.1-11.3 (identity,
re-exports, matching) under ADR-023. `SqlScheduleP6Repository` extends the S5
`SqlScheduleRepository` and reuses its partition guard, lease hold, Series
resolution, run start, failure path and outcome function unchanged; it adds
only what a P6 publication needs and never hydrates a P6 row into the
PDF-shaped `SchedulePublication`/`ScheduleParserRun` (whose enrollment and
engine fields a P6 row does not carry).

Every statement composes `_mine`/`_bound` (the partition guard); every
worker method's first statement holds the lease; the S7-2 triggers (per-run
insert while `running`, activity link once after `parsed`, the F3/F6/F9
restatements) re-verify each transition. The workspace path is written once,
at admission, and no method here reads it back.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from types import TracebackType
from typing import Any, Final

from sqlalchemy import Engine, Table, and_, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, RowMapping

from my_pa.contracts.ports import (
    ScheduleAdmissionRejectedError,
    ScheduleIntegrityError,
    ScheduleP6AdmissionRepository,
    ScheduleP6UnitOfWork,
    ScheduleRepository,
)
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.schedule import (
    MAX_SCHEDULE_BATCH,
    MAX_SCHEDULE_SOURCE_BYTES,
    TERMINAL_OUTCOMES,
    ScheduleIssueCode,
    ScheduleIssueSeverity,
    ScheduleLease,
    SchedulePublicationStatus,
)
from my_pa.domain.schedule.p6.catalogue import CATALOGUE_VERSION, EntityKind
from my_pa.domain.schedule.p6.model import (
    PROFILE_ID,
    PROFILE_VERSION,
    P6Calendar,
    P6Entity,
    P6FieldValue,
    P6Issue,
    P6ObservedField,
)
from my_pa.domain.schedule.p6_import import (
    P6_PARSER_NAME,
    P6ActivityIdentity,
    P6Admission,
    P6AdmissionOutcome,
    P6AdmissionRefusal,
    P6AdmissionRejectedError,
    P6ImportRequest,
    P6ProjectIdentity,
    P6Snapshot,
    p6_import_request_digest,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.jobs import SCHEDULE_JOBS, enqueue_job
from my_pa.infrastructure.persistence.principal_scope import matching_partition_criterion
from my_pa.infrastructure.persistence.schedule import (
    SqlScheduleRepository,
    _bound,
    _mine,
)
from my_pa.infrastructure.persistence.tables import (
    schedule_activities,
    schedule_import_issues,
    schedule_p6_activities,
    schedule_p6_calendars,
    schedule_p6_capture_events,
    schedule_p6_field_values,
    schedule_p6_observed_fields,
    schedule_p6_projects,
    schedule_p6_relationships,
    schedule_p6_snapshots,
    schedule_p6_wbs,
    schedule_parser_runs,
    schedule_publications,
)

__all__ = [
    "P6Plan",
    "P6RunStart",
    "SqlAlchemyScheduleP6UnitOfWork",
    "SqlScheduleP6Repository",
    "p6_issue_severity",
    "p6_stored_name",
]

_PDF: Final = "pdf"
_RUNNING: Final = "running"
_PARSED: Final = "parsed"
_FAILED_RUN: Final = "failed"
_PROCESSING: Final = SchedulePublicationStatus.PROCESSING.value
_COMPLETE: Final = SchedulePublicationStatus.COMPLETE.value
#: Section 5.2: a table or field name is stored only when it matches.
_NAME: Final = re.compile(r"\A[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_SHAPES: Final = ("integer", "decimal", "date", "flag", "token", "text")
_TITLE_CHARACTERS: Final = 300


def p6_stored_name(name: str | None) -> str | None:
    """Section 5.2: an unknown table or field name is stored only if it matches the pattern."""
    return name if name is not None and _NAME.match(name) else None


def p6_issue_severity(issue: P6Issue) -> ScheduleIssueSeverity:
    """Fatal is stored `error`; warning and info are stored `warning` (S7-2 CHECK)."""
    return ScheduleIssueSeverity.ERROR if issue.fatal else ScheduleIssueSeverity.WARNING


@dataclass(frozen=True, slots=True)
class P6Plan:
    """H1 for a P6 publication: what the attempt may do."""

    publication_id: str
    project_id: str
    series_id: str
    terminal: bool
    snapshot_id: str
    capture_event_id: str | None
    accept_project_identity_change: bool


@dataclass(frozen=True, slots=True)
class P6RunStart:
    """H5: the run this attempt writes, or the parsed run it reuses."""

    parser_run_id: str
    status: str
    parse_result_sha256: str | None
    reused: bool


def _sql_value(value: object) -> object:
    return list(value) if isinstance(value, tuple) else value


def _entity_values(entity: P6Entity) -> dict[str, object]:
    return {name: _sql_value(value) for name, value in entity.columns}


class SqlScheduleP6Repository(SqlScheduleRepository, ScheduleP6AdmissionRepository):
    """The P6 transactions on one connection; never commits."""

    @classmethod
    def sharing(cls, schedules: ScheduleRepository) -> SqlScheduleP6Repository:
        """The P6 repository on the connection of an S5 repository (one transaction)."""
        if not isinstance(schedules, SqlScheduleRepository):
            raise TypeError("a P6 repository shares a SQL schedule repository's connection")
        return cls(schedules._connection)

    # ---- admission (section 9.1 step 4) ------------------------------------------------

    def admit_p6_publication(
        self,
        principal_id: str,
        request: P6ImportRequest,
        request_digest: str,
        snapshot: P6Snapshot,
    ) -> P6Admission:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if request_digest != p6_import_request_digest(principal_id, request):
            raise ValueError("the request digest is not the digest of this request")
        if snapshot.sha256 != request.expected_sha256 or snapshot.format is not request.format:
            raise ValueError("the snapshot is not the bytes this request names")
        # (1) the idempotency key.
        replay = self._p6_replay_by_key(principal_id, request.idempotency_key, request_digest)
        if replay is not None:
            return replay
        # (2) the Project; (3) the Series exactly as S5/S6.
        # The S5 refusals, re-typed: a P6 caller sees only the P6 vocabulary.
        try:
            self._require_project(principal_id, request)
        except ScheduleAdmissionRejectedError:
            raise P6AdmissionRejectedError(P6AdmissionRefusal.PROJECT_NOT_FOUND) from None
        try:
            series = self._find_series(principal_id, request, request_digest)
        except ScheduleAdmissionRejectedError:
            raise P6AdmissionRejectedError(P6AdmissionRefusal.SERIES_NOT_FOUND) from None
        if series is not None:
            # A Series holding any PDF publication refuses (operator decision 2026-11-23).
            if self._series_holds_pdf(principal_id, series.series_id):
                raise P6AdmissionRejectedError(P6AdmissionRefusal.SERIES_FORMAT)
            # Content idempotency: the same bytes in this Series answer the existing one.
            present = self._published_snapshot(principal_id, series.series_id, snapshot.sha256)
            if present is not None:
                return self._p6_admission(principal_id, present, P6AdmissionOutcome.ALREADY_PRESENT)
        if request.supersedes_publication_id is not None:
            self._require_p6_predecessor(
                principal_id,
                None if series is None else series.series_id,
                request.supersedes_publication_id,
            )
        # (4) the writes: snapshot (once per Principal), Series, publication, job.
        snapshot_id = self._store_snapshot(principal_id, snapshot)
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
                            "idempotency_key": request.idempotency_key,
                            "request_digest": request_digest,
                            "publication_role": "update",
                            "supersedes_publication_id": request.supersedes_publication_id,
                            "source_format": request.format.value,
                            "p6_snapshot_id": snapshot_id,
                            "p6_workspace_id": request.workspace_id,
                            "p6_workspace_path": request.path,
                            "p6_workspace_version": request.expected_version,
                            "p6_capture_event_id": self._current_capture_event(
                                principal_id, series.series_id
                            ),
                            "accept_project_identity_change": (
                                request.accept_project_identity_change
                            ),
                        },
                    )
                )
                .on_conflict_do_nothing()
                .returning(schedule_publications.c.publication_id)
            )
            .scalars()
            .one_or_none()
        )
        if inserted is None:
            # A concurrent admission won a unique: answer as if it had been seen first.
            replay = self._p6_replay_by_key(principal_id, request.idempotency_key, request_digest)
            if replay is not None:
                return replay
            present = self._published_snapshot(principal_id, series.series_id, snapshot.sha256)
            if present is not None:
                return self._p6_admission(principal_id, present, P6AdmissionOutcome.ALREADY_PRESENT)
            raise ScheduleIntegrityError("admission_race_unresolved")
        operation_id = enqueue_job(self._connection, publication_id, plane=SCHEDULE_JOBS)
        if request.series_auto:
            self._mark_intake(principal_id, request, series, publication_id)
        return P6Admission(
            series_id=series.series_id,
            series_created=series_created,
            publication_id=publication_id,
            operation_id=operation_id,
            outcome=P6AdmissionOutcome.CREATED,
            status=SchedulePublicationStatus.QUEUED.value,
            snapshot_id=snapshot_id,
            sha256=snapshot.sha256,
            size_bytes=snapshot.size_bytes,
        )

    def _p6_publication_row(self, principal_id: str, *criteria: Any) -> RowMapping | None:  # noqa: ANN401
        pubs, snaps = schedule_publications, schedule_p6_snapshots
        return (
            self._connection.execute(
                select(pubs, snaps.c.sha256.label("snapshot_sha256"), snaps.c.size_bytes)
                .select_from(
                    pubs.outerjoin(
                        snaps,
                        and_(
                            matching_partition_criterion(snaps, pubs),
                            snaps.c.snapshot_id == pubs.c.p6_snapshot_id,
                        ),
                    )
                )
                .where(_mine(pubs, principal_id), *criteria)
            )
            .mappings()
            .one_or_none()
        )

    def _p6_admission(
        self, principal_id: str, row: RowMapping, outcome: P6AdmissionOutcome
    ) -> P6Admission:
        operation_id = self._operation_of(principal_id, row["publication_id"])
        if operation_id is None or row["p6_snapshot_id"] is None:
            raise ScheduleIntegrityError("admission_replay_incomplete")
        return P6Admission(
            series_id=row["series_id"],
            series_created=False,
            publication_id=row["publication_id"],
            operation_id=operation_id,
            outcome=outcome,
            status=self._effective(principal_id, row).value,
            snapshot_id=row["p6_snapshot_id"],
            sha256=row["snapshot_sha256"],
            size_bytes=int(row["size_bytes"]),
        )

    def _p6_replay_by_key(
        self, principal_id: str, idempotency_key: str, request_digest: str
    ) -> P6Admission | None:
        found = self._p6_publication_row(
            principal_id, schedule_publications.c.idempotency_key == idempotency_key
        )
        if found is None:
            return None
        if found["request_digest"] != request_digest:
            raise P6AdmissionRejectedError(P6AdmissionRefusal.IDEMPOTENCY_KEY_CONFLICT)
        return self._p6_admission(principal_id, found, P6AdmissionOutcome.REPLAYED)

    def _series_holds_pdf(self, principal_id: str, series_id: str) -> bool:
        pubs = schedule_publications
        return (
            self._connection.execute(
                select(pubs.c.publication_id)
                .where(
                    _mine(pubs, principal_id),
                    pubs.c.series_id == series_id,
                    pubs.c.source_format == _PDF,
                )
                .limit(1)
            ).first()
            is not None
        )

    def _published_snapshot(
        self, principal_id: str, series_id: str, sha256: str
    ) -> RowMapping | None:
        return self._p6_publication_row(
            principal_id,
            schedule_publications.c.series_id == series_id,
            schedule_p6_snapshots.c.sha256 == sha256,
        )

    def _require_p6_predecessor(
        self, principal_id: str, series_id: str | None, predecessor_id: str
    ) -> None:
        if series_id is None:
            raise P6AdmissionRejectedError(P6AdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_FOUND)
        pubs = schedule_publications
        predecessor = (
            self._connection.execute(
                select(pubs)
                .where(
                    _mine(pubs, principal_id),
                    pubs.c.publication_id == predecessor_id,
                    pubs.c.series_id == series_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if predecessor is None:
            raise P6AdmissionRejectedError(P6AdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_FOUND)
        if self._effective(principal_id, predecessor) not in TERMINAL_OUTCOMES:
            raise P6AdmissionRejectedError(P6AdmissionRefusal.SUPERSEDED_PUBLICATION_NOT_TERMINAL)
        successor = self._connection.execute(
            select(pubs.c.publication_id).where(
                _mine(pubs, principal_id), pubs.c.supersedes_publication_id == predecessor_id
            )
        ).first()
        if successor is not None:
            raise P6AdmissionRejectedError(P6AdmissionRefusal.SUPERSEDED_PUBLICATION_HAS_SUCCESSOR)

    def _store_snapshot(self, principal_id: str, snapshot: P6Snapshot) -> str:
        """Section 9.1: the bytes once per Principal and SHA-256 (content-addressed)."""
        snaps = schedule_p6_snapshots
        self._connection.execute(
            pg_insert(snaps)
            .values(
                _bound(
                    snaps,
                    principal_id,
                    {
                        "snapshot_id": issue_identifier(IdKind.SCHEDULE_P6_SNAPSHOT),
                        "format": snapshot.format.value,
                        "size_bytes": snapshot.size_bytes,
                        "sha256": snapshot.sha256,
                        "content": snapshot.content,
                    },
                )
            )
            .on_conflict_do_nothing(index_elements=[snaps.c.principal_id, snaps.c.sha256])
        )
        stored = self._connection.execute(
            select(snaps.c.snapshot_id, snaps.c.format).where(
                _mine(snaps, principal_id), snaps.c.sha256 == snapshot.sha256
            )
        ).one()
        if stored.format != snapshot.format.value:
            raise ScheduleIntegrityError("snapshot_format")
        return str(stored.snapshot_id)

    def _current_capture_event(self, principal_id: str, series_id: str) -> str | None:
        """Section 7.2: the Series' current selection (its last event), or none (defaults)."""
        events = schedule_p6_capture_events
        found = self._connection.execute(
            select(events.c.event_id)
            .where(_mine(events, principal_id), events.c.series_id == series_id)
            .order_by(events.c.sequence.desc())
            .limit(1)
        ).scalar_one_or_none()
        return None if found is None else str(found)

    # ---- worker: plan, snapshot, selection ---------------------------------------------

    def begin_p6_processing(
        self, principal_id: str, publication_id: str, lease: ScheduleLease
    ) -> P6Plan:
        """H1: lease, job, publication; a queued one moves to `processing`."""
        publication = self._held_publication(principal_id, publication_id, lease)
        if publication["source_format"] == _PDF or publication["p6_snapshot_id"] is None:
            raise ScheduleIntegrityError("not_a_p6_publication")
        status = SchedulePublicationStatus(publication["status"])
        if status is SchedulePublicationStatus.QUEUED:
            self._connection.execute(
                update(schedule_publications)
                .where(
                    _mine(schedule_publications, principal_id),
                    schedule_publications.c.publication_id == publication_id,
                )
                .values(status=_PROCESSING, processing_started_at=func.now(), updated_at=func.now())
            )
        return P6Plan(
            publication_id=publication_id,
            project_id=publication["project_id"],
            series_id=publication["series_id"],
            terminal=status in TERMINAL_OUTCOMES,
            snapshot_id=publication["p6_snapshot_id"],
            capture_event_id=publication["p6_capture_event_id"],
            accept_project_identity_change=bool(publication["accept_project_identity_change"]),
        )

    def load_p6_snapshot(
        self, principal_id: str, publication_id: str, lease: ScheduleLease
    ) -> tuple[bytes, str, int]:
        """H2: the publication's snapshot bytes, stored SHA-256 and size (no provider)."""
        self._held_publication(principal_id, publication_id, lease)
        pubs, snaps = schedule_publications, schedule_p6_snapshots
        found = self._connection.execute(
            select(snaps.c.content, snaps.c.sha256, snaps.c.size_bytes)
            .select_from(
                pubs.join(
                    snaps,
                    and_(
                        matching_partition_criterion(snaps, pubs),
                        snaps.c.snapshot_id == pubs.c.p6_snapshot_id,
                    ),
                )
            )
            .where(
                _mine(pubs, principal_id),
                _mine(snaps, principal_id),
                pubs.c.publication_id == publication_id,
            )
        ).one_or_none()
        if found is None:
            raise ScheduleIntegrityError("snapshot_not_found")
        size = int(found.size_bytes)
        if not 1 <= size <= MAX_SCHEDULE_SOURCE_BYTES:
            raise ScheduleIntegrityError("snapshot_size")
        return bytes(found.content), str(found.sha256), size

    def capture_selection(
        self, principal_id: str, capture_event_id: str | None
    ) -> tuple[str, ...] | None:
        """Section 7.2: the selection in force at admission (`None`: the defaults)."""
        if capture_event_id is None:
            return None
        events = schedule_p6_capture_events
        keys = self._connection.execute(
            select(events.c.field_keys).where(
                _mine(events, principal_id), events.c.event_id == capture_event_id
            )
        ).scalar_one_or_none()
        if keys is None:
            raise ScheduleIntegrityError("capture_event_not_found")
        return tuple(str(key) for key in keys)

    def p6_series_identities(
        self, principal_id: str, series_id: str, publication_id: str
    ) -> tuple[P6ProjectIdentity, ...]:
        """Section 11.1: the identities of the Series' earlier complete P6 publications."""
        pubs, projects = schedule_publications, schedule_p6_projects
        rows = self._connection.execute(
            select(projects.c.project_short_name, projects.c.project_guid)
            .select_from(
                pubs.join(
                    projects,
                    and_(
                        matching_partition_criterion(projects, pubs),
                        projects.c.parser_run_id == pubs.c.accepted_parser_run_id,
                    ),
                )
            )
            .where(
                _mine(pubs, principal_id),
                _mine(projects, principal_id),
                pubs.c.series_id == series_id,
                pubs.c.publication_id != publication_id,
                pubs.c.status == _COMPLETE,
                pubs.c.source_format != _PDF,
            )
        ).all()
        return tuple(P6ProjectIdentity(row.project_short_name, row.project_guid) for row in rows)

    # ---- worker: the run (H5, H6) --------------------------------------------------------

    def start_p6_parser_run(
        self, principal_id: str, publication_id: str, lease: ScheduleLease
    ) -> P6RunStart:
        """H5: `p6_xer_v1` under the catalogue version; no engine (S7-2 CHECK)."""
        run, reused = self._start_run_row(
            principal_id,
            publication_id,
            lease,
            parser_name=P6_PARSER_NAME,
            parser_version=CATALOGUE_VERSION,
            profile_id=PROFILE_ID,
            profile_version=PROFILE_VERSION,
            pypdfium2_version=None,
            pdfium_version=None,
        )
        return P6RunStart(
            parser_run_id=run["parser_run_id"],
            status=run["status"],
            parse_result_sha256=run["parse_result_sha256"],
            reused=reused,
        )

    def count_p6_run_contents(self, principal_id: str, parser_run_id: str) -> int:
        """Rows of every P6 per-run table plus the run's issues (a resumed run must be empty)."""
        total = 0
        for table in (*_PER_RUN_TABLES, schedule_import_issues):
            total += int(
                self._connection.execute(
                    select(func.count())
                    .select_from(table)
                    .where(_mine(table, principal_id), table.c.parser_run_id == parser_run_id)
                ).scalar_one()
            )
        return total

    def _running_run(
        self, principal_id: str, parser_run_id: str, lease: ScheduleLease
    ) -> RowMapping:
        run = self._held_run(principal_id, parser_run_id, lease)
        if run["status"] != _RUNNING:
            raise ScheduleIntegrityError("parser_run_not_running")
        return run

    def _insert(self, table: Table, principal_id: str, rows: Sequence[dict[str, object]]) -> int:
        if not 1 <= len(rows) <= MAX_SCHEDULE_BATCH:
            raise ValueError("a P6 batch holds 1 to 1000 rows")
        self._connection.execute(
            insert(table).values([_bound(table, principal_id, row) for row in rows])
        )
        return len(rows)

    @staticmethod
    def _run_key(run: RowMapping) -> dict[str, object]:
        return {"parser_run_id": run["parser_run_id"], "publication_id": run["publication_id"]}

    def insert_p6_project(
        self,
        principal_id: str,
        parser_run_id: str,
        lease: ScheduleLease,
        project: P6Entity,
    ) -> int:
        run = self._running_run(principal_id, parser_run_id, lease)
        return self._insert(
            schedule_p6_projects,
            principal_id,
            [
                {
                    **self._run_key(run),
                    **_entity_values(project),
                    "catalogue_version": CATALOGUE_VERSION,
                    "record_line": project.record_line,
                }
            ],
        )

    def insert_p6_wbs(
        self, principal_id: str, parser_run_id: str, lease: ScheduleLease, wbs: Sequence[P6Entity]
    ) -> int:
        run = self._running_run(principal_id, parser_run_id, lease)
        key = self._run_key(run)
        return self._insert(
            schedule_p6_wbs,
            principal_id,
            [{**key, **_entity_values(item), "record_line": item.record_line} for item in wbs],
        )

    def insert_p6_activities(
        self,
        principal_id: str,
        parser_run_id: str,
        lease: ScheduleLease,
        activities: Sequence[P6Entity],
        links: Mapping[str, str] | None,
    ) -> int:
        """Activities, linked at insert to their Stable Activity when `links` is given."""
        run = self._running_run(principal_id, parser_run_id, lease)
        key = {**self._run_key(run), "project_id": run["project_id"], "series_id": run["series_id"]}
        rows: list[dict[str, object]] = []
        for item in activities:
            values = _entity_values(item)
            link = None if links is None else links[str(values["activity_id"])]
            rows.append(
                {**key, **values, "schedule_activity_id": link, "record_line": item.record_line}
            )
        return self._insert(schedule_p6_activities, principal_id, rows)

    def insert_p6_relationships(
        self,
        principal_id: str,
        parser_run_id: str,
        lease: ScheduleLease,
        relationships: Sequence[P6Entity],
    ) -> int:
        run = self._running_run(principal_id, parser_run_id, lease)
        key = self._run_key(run)
        return self._insert(
            schedule_p6_relationships,
            principal_id,
            [
                {**key, **_entity_values(item), "record_line": item.record_line}
                for item in relationships
            ],
        )

    def insert_p6_calendars(
        self,
        principal_id: str,
        parser_run_id: str,
        lease: ScheduleLease,
        calendars: Sequence[P6Calendar],
    ) -> int:
        run = self._running_run(principal_id, parser_run_id, lease)
        key = self._run_key(run)
        rows: list[dict[str, object]] = []
        for calendar in calendars:
            rows.append(
                {
                    **key,
                    **{name: _sql_value(value) for name, value in calendar.columns},
                    "week": [[list(pair) for pair in day] for day in calendar.week],
                    "exceptions": [
                        {"date": day.isoformat(), "intervals": [list(pair) for pair in intervals]}
                        for day, intervals in calendar.exceptions
                    ],
                    "exception_count": len(calendar.exceptions),
                    "data_sha256": calendar.data_sha256,
                    "record_line": calendar.record_line,
                }
            )
        return self._insert(schedule_p6_calendars, principal_id, rows)

    def insert_p6_field_values(
        self,
        principal_id: str,
        parser_run_id: str,
        lease: ScheduleLease,
        values: Sequence[P6FieldValue],
        links: Mapping[str, str] | None,
    ) -> int:
        """Section 7.3: one typed value column each; an activity's linked when `links` is given."""
        run = self._running_run(principal_id, parser_run_id, lease)
        key = {**self._run_key(run), "project_id": run["project_id"], "series_id": run["series_id"]}
        rows: list[dict[str, object]] = []
        for value in values:
            typed: dict[str, object] = {
                "value_text": None,
                "value_number": None,
                "value_ts": None,
                "value_flag": None,
            }
            column = _VALUE_COLUMN.get(value.value_type)
            if column is None:
                raise ScheduleIntegrityError("field_value_type")
            typed[column] = value.value
            activity = value.activity_id if value.entity_kind is EntityKind.ACTIVITY else None
            rows.append(
                {
                    **key,
                    "entity_kind": value.entity_kind.value,
                    "entity_p6_id": value.entity_p6_id,
                    "field_key": value.field_key,
                    "ordinal": value.ordinal,
                    "activity_id": activity,
                    "schedule_activity_id": (
                        None if links is None or activity is None else links.get(activity)
                    ),
                    **typed,
                    "code_path": list(value.code_path),
                    "description": value.description,
                    "source_table": value.source_table,
                    "record_line": value.record_line,
                }
            )
        return self._insert(schedule_p6_field_values, principal_id, rows)

    def insert_p6_observed_fields(
        self,
        principal_id: str,
        parser_run_id: str,
        lease: ScheduleLease,
        observed: Sequence[P6ObservedField],
    ) -> int:
        """Section 7.4: stats only; a name outside the 5.2 pattern is stored as null."""
        run = self._running_run(principal_id, parser_run_id, lease)
        key = self._run_key(run)
        rows: list[dict[str, object]] = []
        for field in observed:
            shapes = dict(field.shapes)
            rows.append(
                {
                    **key,
                    "table_position": field.table_position,
                    "field_position": field.position,
                    "source_table": p6_stored_name(field.table),
                    "field_name": p6_stored_name(field.field),
                    "field_key": field.field_key,
                    "catalogued": field.catalogued,
                    "tier": field.tier,
                    "present": True,
                    "record_count": field.records,
                    "nonempty_count": field.nonempty,
                    "min_length": field.min_length,
                    "max_length": field.max_length,
                    **{f"shape_{shape}": int(shapes.get(shape, 0)) for shape in _SHAPES},
                    "unknown_enum_count": field.unknown_enum,
                    "over_length_count": field.over_length,
                    "captured": field.captured,
                }
            )
        return self._insert(schedule_p6_observed_fields, principal_id, rows)

    def _issue_rows(
        self, principal_id: str, run: RowMapping, issues: Sequence[P6Issue]
    ) -> list[dict[str, object]]:
        return [
            {
                "issue_id": issue_identifier(IdKind.SCHEDULE_IMPORT_ISSUE),
                "project_id": run["project_id"],
                "series_id": run["series_id"],
                "publication_id": run["publication_id"],
                "parser_run_id": run["parser_run_id"],
                "severity": p6_issue_severity(issue).value,
                "code": issue.code.value,
                "source_table": p6_stored_name(issue.table),
                "record_line": issue.line,
                "field": p6_stored_name(issue.field),
            }
            for issue in issues
        ]

    def insert_p6_issues(
        self,
        principal_id: str,
        parser_run_id: str,
        lease: ScheduleLease,
        issues: Sequence[P6Issue],
    ) -> int:
        run = self._running_run(principal_id, parser_run_id, lease)
        return self._insert(
            schedule_import_issues, principal_id, self._issue_rows(principal_id, run, issues)
        )

    def finish_p6_parser_run(
        self,
        principal_id: str,
        parser_run_id: str,
        lease: ScheduleLease,
        *,
        activities: int,
        issues: int,
        warnings: int,
        parse_result_sha256: str,
    ) -> None:
        """H6 end: the run `parsed` with the counts the database holds and the frame digest."""
        run = self._running_run(principal_id, parser_run_id, lease)
        stored = self._p6_counts(principal_id, parser_run_id)
        if (stored["activities"], stored["issues"], stored["warnings"]) != (
            activities,
            issues,
            warnings,
        ):
            raise ScheduleIntegrityError("count_mismatch")
        if self._outcome(parser_run_id) is SchedulePublicationStatus.FAILED:
            raise ScheduleIntegrityError("failed_outcome")
        del run
        self._connection.execute(
            update(schedule_parser_runs)
            .where(
                _mine(schedule_parser_runs, principal_id),
                schedule_parser_runs.c.parser_run_id == parser_run_id,
            )
            .values(
                status=_PARSED,
                completed_at=func.now(),
                page_count=0,
                row_count=activities,
                issue_count=issues,
                warning_count=warnings,
                parse_result_sha256=parse_result_sha256,
            )
        )

    def _p6_counts(self, principal_id: str, parser_run_id: str) -> dict[str, int]:
        acts, issues = schedule_p6_activities, schedule_import_issues
        counted = (
            self._connection.execute(
                select(
                    func.count().label("activities"),
                    func.count().filter(acts.c.schedule_activity_id.is_(None)).label("unlinked"),
                    func.count().filter(acts.c.schedule_activity_id.is_not(None)).label("linked"),
                ).where(_mine(acts, principal_id), acts.c.parser_run_id == parser_run_id)
            )
            .mappings()
            .one()
        )
        issue_counts = (
            self._connection.execute(
                select(
                    func.count().label("issues"),
                    func.count()
                    .filter(issues.c.severity == ScheduleIssueSeverity.WARNING.value)
                    .label("warnings"),
                ).where(_mine(issues, principal_id), issues.c.parser_run_id == parser_run_id)
            )
            .mappings()
            .one()
        )
        return {name: int(value) for name, value in {**counted, **issue_counts}.items()}

    # ---- worker: Stable Activities (H7) ----------------------------------------------------

    def ensure_p6_stable_activities(
        self,
        principal_id: str,
        publication_id: str,
        lease: ScheduleLease,
        activity_ids: Sequence[str],
    ) -> dict[str, str]:
        """H7 (section 11.3): the Stable Activity of each exact Activity ID in the Series.

        Created once per `(Series, task_code)` and found again by every later
        publication; 1 to 1,000 IDs, taken in sorted order (the S5 lock order).
        """
        if not 1 <= len(activity_ids) <= MAX_SCHEDULE_BATCH:
            raise ValueError("a Stable Activity batch holds 1 to 1000 IDs")
        publication = self._held_publication(principal_id, publication_id, lease)
        self._require_processing(publication)
        codes = sorted(set(activity_ids))
        activities = schedule_activities
        self._connection.execute(
            pg_insert(activities)
            .values(
                [
                    _bound(
                        activities,
                        principal_id,
                        {
                            "schedule_activity_id": issue_identifier(IdKind.SCHEDULE_ACTIVITY),
                            "project_id": publication["project_id"],
                            "series_id": publication["series_id"],
                            "published_activity_id": code,
                        },
                    )
                    for code in codes
                ]
            )
            .on_conflict_do_nothing(
                index_elements=[
                    activities.c.principal_id,
                    activities.c.series_id,
                    activities.c.published_activity_id,
                ]
            )
        )
        found = self._connection.execute(
            select(activities.c.published_activity_id, activities.c.schedule_activity_id).where(
                _mine(activities, principal_id),
                activities.c.series_id == publication["series_id"],
                activities.c.published_activity_id.in_(codes),
            )
        ).all()
        links = {str(row.published_activity_id): str(row.schedule_activity_id) for row in found}
        if set(links) != set(codes):
            raise ScheduleIntegrityError("stable_activity_missing")
        return links

    def p6_run_outcome(self, principal_id: str, parser_run_id: str) -> str:
        """F9 over one of the Principal's runs (read under `_mine` first, section 4.10)."""
        if self._run(principal_id, parser_run_id) is None:
            raise ScheduleIntegrityError("parser_run_not_found")
        return self._outcome(parser_run_id).value

    def link_p6_batch(self, principal_id: str, parser_run_id: str, lease: ScheduleLease) -> int:
        """H7 after `parsed`: link up to 1,000 still unlinked activities; the number left."""
        run = self._held_run(principal_id, parser_run_id, lease)
        if run["status"] != _PARSED:
            raise ScheduleIntegrityError("parser_run_not_parsed")
        if self._outcome(parser_run_id) is not SchedulePublicationStatus.COMPLETE:
            raise ScheduleIntegrityError("identity_gate")
        acts = schedule_p6_activities
        batch = self._connection.execute(
            select(acts.c.p6_task_id, acts.c.activity_id)
            .where(
                _mine(acts, principal_id),
                acts.c.parser_run_id == parser_run_id,
                acts.c.schedule_activity_id.is_(None),
            )
            .order_by(acts.c.activity_id)
            .limit(MAX_SCHEDULE_BATCH)
        ).all()
        if batch:
            links = self.ensure_p6_stable_activities(
                principal_id, run["publication_id"], lease, [str(row.activity_id) for row in batch]
            )
            for row in batch:
                self._connection.execute(
                    update(acts)
                    .where(
                        _mine(acts, principal_id),
                        acts.c.parser_run_id == parser_run_id,
                        acts.c.p6_task_id == row.p6_task_id,
                    )
                    .values(schedule_activity_id=links[str(row.activity_id)])
                )
        return self._p6_counts(principal_id, parser_run_id)["unlinked"]

    # ---- worker: terminal (H8, HF) -----------------------------------------------------------

    def finalize_p6_publication(
        self,
        principal_id: str,
        publication_id: str,
        lease: ScheduleLease,
        parser_run_id: str,
    ) -> str:
        """H8: the derived status (F9), the counts, the data date; returns the status."""
        publication = self._held_publication(principal_id, publication_id, lease)
        self._require_processing(publication)
        run = self._run(principal_id, parser_run_id)
        if run is None or run["publication_id"] != publication_id:
            raise ScheduleIntegrityError("parser_run_not_found")
        if run["status"] != _PARSED:
            raise ScheduleIntegrityError("parser_run_not_parsed")
        status = self._outcome(parser_run_id)
        if status not in (
            SchedulePublicationStatus.COMPLETE,
            SchedulePublicationStatus.REVIEW_REQUIRED,
        ):
            raise ScheduleIntegrityError("status_mismatch")
        stored = self._p6_counts(principal_id, parser_run_id)
        if (status is SchedulePublicationStatus.COMPLETE and stored["unlinked"]) or (
            status is SchedulePublicationStatus.REVIEW_REQUIRED and stored["linked"]
        ):
            raise ScheduleIntegrityError("incomplete_canonicalization")
        project = self._connection.execute(
            select(
                schedule_p6_projects.c.project_name,
                schedule_p6_projects.c.data_date,
                schedule_p6_projects.c.export_date,
            ).where(
                _mine(schedule_p6_projects, principal_id),
                schedule_p6_projects.c.parser_run_id == parser_run_id,
            )
        ).one()
        self._close_running_runs(principal_id, publication_id, except_run=parser_run_id)
        data_date: datetime | None = project.data_date
        exported: date | None = project.export_date
        title = str(project.project_name)
        self._connection.execute(
            update(schedule_publications)
            .where(
                _mine(schedule_publications, principal_id),
                schedule_publications.c.publication_id == publication_id,
            )
            .values(
                status=status.value,
                accepted_parser_run_id=parser_run_id,
                page_count=0,
                row_count=stored["activities"],
                activity_count=stored["activities"],
                ambiguous_row_count=0,
                issue_count=stored["issues"],
                published_schedule_title=title if len(title) <= _TITLE_CHARACTERS else None,
                data_date=None if data_date is None else data_date.date(),
                run_date=exported,
                completed_at=func.now(),
                updated_at=func.now(),
            )
        )
        return status.value

    def fail_p6_publication(
        self,
        principal_id: str,
        publication_id: str,
        lease: ScheduleLease,
        parser_run_id: str | None,
        code: ScheduleIssueCode,
    ) -> str:
        """HF for a non-parse failure (budget, child, bounds): the S5 failure path."""
        self._fail_row(principal_id, publication_id, lease, code, parser_run_id)
        return SchedulePublicationStatus.FAILED.value

    def fail_p6_parse(
        self,
        principal_id: str,
        publication_id: str,
        lease: ScheduleLease,
        parser_run_id: str,
        issues: Sequence[P6Issue],
    ) -> str:
        """HF for a fatal parse: its listed issues (the fatal one included), then failed.

        The run ends `failed` with the fatal code as its `failure_code`; every
        other running run ends with the publication (R6-F03).
        """
        fatal = [issue for issue in issues if issue.fatal]
        if not fatal or len(issues) > _MAX_STORED_ISSUES:
            raise ScheduleIntegrityError("failed_result_shape")
        publication = self._held_publication(principal_id, publication_id, lease)
        self._require_processing(publication)
        run = self._run(principal_id, parser_run_id)
        if run is None or run["publication_id"] != publication_id or run["status"] != _RUNNING:
            raise ScheduleIntegrityError("parser_run_not_running")
        rows = self._issue_rows(principal_id, run, issues)
        for start in range(0, len(rows), MAX_SCHEDULE_BATCH):
            self._insert(
                schedule_import_issues, principal_id, rows[start : start + MAX_SCHEDULE_BATCH]
            )
        self._connection.execute(
            update(schedule_parser_runs)
            .where(
                _mine(schedule_parser_runs, principal_id),
                schedule_parser_runs.c.parser_run_id == parser_run_id,
            )
            .values(status=_FAILED_RUN, failure_code=fatal[0].code.value, completed_at=func.now())
        )
        self._end_failed(principal_id, publication_id)
        return SchedulePublicationStatus.FAILED.value

    # ---- reads the worker tests and S7-4 build on --------------------------------------------

    def p6_activity_identities(
        self, principal_id: str, publication_id: str
    ) -> tuple[P6ActivityIdentity, ...]:
        """Section 11.3: the accepted run's activities (Activity ID and GUID), by ID."""
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        pubs, acts = schedule_publications, schedule_p6_activities
        rows = self._connection.execute(
            select(acts.c.activity_id, acts.c.p6_guid)
            .select_from(
                pubs.join(
                    acts,
                    and_(
                        matching_partition_criterion(acts, pubs),
                        acts.c.parser_run_id == pubs.c.accepted_parser_run_id,
                    ),
                )
            )
            .where(
                _mine(pubs, principal_id),
                _mine(acts, principal_id),
                pubs.c.publication_id == publication_id,
            )
            .order_by(acts.c.activity_id)
        ).all()
        return tuple(P6ActivityIdentity(str(row.activity_id), row.p6_guid) for row in rows)


#: Section 7.3: the value column each captured value type fills.
_VALUE_COLUMN: Final = {
    "text": "value_text",
    "number": "value_number",
    "ts": "value_ts",
    "flag": "value_flag",
}
#: Section 5.5: at most this many issues are listed (counts stay complete).
_MAX_STORED_ISSUES: Final = 10_000
_PER_RUN_TABLES: Final = (
    schedule_p6_projects,
    schedule_p6_wbs,
    schedule_p6_activities,
    schedule_p6_relationships,
    schedule_p6_calendars,
    schedule_p6_field_values,
    schedule_p6_observed_fields,
)


class SqlAlchemyScheduleP6UnitOfWork(ScheduleP6UnitOfWork):
    """One PostgreSQL transaction over the Schedule and P6 tables (the S5 shape)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._context: Any = None
        self._connection: Connection | None = None

    def __enter__(self) -> SqlAlchemyScheduleP6UnitOfWork:
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
    def p6(self) -> SqlScheduleP6Repository:
        connection = self._connection
        if connection is None:
            raise RuntimeError("this unit of work is not inside a transaction")
        return SqlScheduleP6Repository(connection)
