"""Shared database harness for the CPM Workbench S5b-2 Schedule capability tests.

A helper module, not a test module: pytest does not collect it. It composes a
real `ApplicationService` over PostgreSQL with the Schedule switch and factory
stated explicitly (worker and capabilities contract section 3.1), seeds
synthetic sources, Projects and enrollments, and publishes synthetic schedules
the way production does: `schedule_publications.import` through the attested
CLI surface, then the real `process_schedule_publication` handler under
`run_worker` with two seams replaced -- the provider (`_provider_for`, serving
synthetic `%PDF-` bytes) and the contained parse (`run_isolated_parse`,
returning a synthetic `ScheduleParseResult` built here). Every row the reads
serve is therefore written by the S5b-1 repository through the S5b-2 handler.

Every identity, name and value here is synthetic.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Final

import pytest
from sqlalchemy import Connection, Engine, func, select, text

from my_pa.application.commands import Command, ImportSchedulePublication
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.schedule import (
    ISSUE_SEVERITY,
    ROW_CELL_FIELDS,
    ParsedScheduleRow,
    ScheduleBox,
    ScheduleCellEvidence,
    ScheduleCellFragment,
    ScheduleCellState,
    ScheduleDateCell,
    ScheduleDurationCell,
    ScheduleIssueCode,
    ScheduleParseCounts,
    ScheduleParseEngine,
    ScheduleParseIssue,
    ScheduleParseResult,
    SchedulePublicationStatus,
    ScheduleRowType,
)
from my_pa.domain.source.provider import (
    ObjectKind,
    SourceObject,
    SourceObjectContent,
    SourceProvider,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.jobs import schedule as handler_module
from my_pa.infrastructure.jobs.schedule import process_schedule_publication
from my_pa.infrastructure.jobs.schedule_parser_process import IsolatedParse, ParsedResult
from my_pa.infrastructure.jobs.worker import WorkerRun, run_worker
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.jobs import SCHEDULE_JOBS
from my_pa.infrastructure.persistence.schedule import SqlAlchemyScheduleUnitOfWork
from my_pa.infrastructure.persistence.tables import audit_events
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

__all__ = [
    "CPM_TABLES",
    "OTHER_PRINCIPAL",
    "OWNER",
    "PRINCIPAL",
    "REMOTE_CLIENT",
    "Activity",
    "ScheduleRuntime",
    "World",
    "build_result",
    "cpm_snapshot",
]

PRINCIPAL: Final = "prn_schedcap0001"
OTHER_PRINCIPAL: Final = "prn_schedcap0002"
REMOTE_CLIENT: Final = "synthetic-schedule-remote-client"
OWNER: Final = "cpm-capability-worker"
SIXTEEN_MIB: Final = 16_777_216
LIMITS: Final = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)
CPM_TABLES: Final = (
    "schedule_series",
    "schedule_publications",
    "schedule_activities",
    "schedule_jobs",
    "schedule_parser_runs",
    "schedule_rows",
    "schedule_import_issues",
)
VALUE: Final = ScheduleCellState.PUBLISHED_VALUE
BLANK: Final = ScheduleCellState.PUBLISHED_BLANK


@dataclass(frozen=True)
class World:
    principal: str
    tag: str
    source: str
    project: str
    enrollment: str


@dataclass(frozen=True)
class Activity:
    """One synthetic activity or milestone row a publication carries."""

    published_id: str
    name: str = "Synthetic activity"
    row_type: ScheduleRowType = ScheduleRowType.ACTIVITY
    path: tuple[str, ...] | None = ("Synthetic WBS",)
    od: str | None = "10.000"
    rd: str | None = "5.000"
    start: date | None = date(2026, 5, 4)
    finish: date | None = date(2026, 5, 15)
    page: int = 1


def _cells(published_id: str, name: str) -> tuple[ScheduleCellEvidence, ...]:
    texts = {"activity_id": published_id, "activity_name": name}
    cells = []
    for code in ROW_CELL_FIELDS:
        value = texts.get(code.value)
        if value is None:
            cells.append(ScheduleCellEvidence(code, BLANK, None, ()))
        else:
            fragment = ScheduleCellFragment(
                raw=value,
                box=ScheduleBox(1_000, 1_000, 2_000, 2_000),
                font_base_name="Arial",
                font_size_mpt=7_000,
            )
            cells.append(ScheduleCellEvidence(code, VALUE, value, (fragment,)))
    return tuple(cells)


def _duration(value: str | None) -> ScheduleDurationCell:
    if value is None:
        return ScheduleDurationCell(BLANK, None)
    return ScheduleDurationCell(VALUE, Decimal(value).quantize(Decimal("0.001")))


def _date(value: date | None) -> ScheduleDateCell:
    return (
        ScheduleDateCell(BLANK, None, None)
        if value is None
        else ScheduleDateCell(VALUE, value, None)
    )


def _row(ordinal: int, activity: Activity) -> ParsedScheduleRow:
    top = 600_000 - 6_000 * (ordinal % 90)
    return ParsedScheduleRow(
        row_ordinal=ordinal,
        page_number=activity.page,
        physical_line_ordinal=ordinal,
        row_type=activity.row_type,
        indent_level=0,
        parent_row_ordinal=None,
        hierarchy_path=activity.path,
        published_activity_id=activity.published_id,
        activity_name=activity.name,
        original_duration=_duration(activity.od),
        remaining_duration=_duration(activity.rd),
        start=_date(activity.start),
        finish=_date(activity.finish),
        box=ScheduleBox(52_570, top - 5_000, 593_500, top),
        page_width_mpt=1_224_000,
        page_height_mpt=792_000,
        cells=_cells(activity.published_id, activity.name),
        warning_codes=(),
    )


def build_result(
    data: bytes,
    activities: Sequence[Activity],
    *,
    data_date: date,
    outcome: SchedulePublicationStatus = SchedulePublicationStatus.COMPLETE,
    title: str = "Synthetic Schedule",
) -> ScheduleParseResult:
    """A canonical-shaped parse result for `data`, with the outcome's issues.

    `partial` carries one `invalid_date` issue on row 1, `review_required` one
    `duplicate_activity_id` issue, so the database's run outcome (F9) derives
    the same status the result states.
    """
    rows = tuple(_row(n, activity) for n, activity in enumerate(activities, start=1))
    issues: tuple[ScheduleParseIssue, ...] = ()
    if outcome is SchedulePublicationStatus.PARTIAL:
        code = ScheduleIssueCode.INVALID_DATE
        issues = (ScheduleParseIssue(code, ISSUE_SEVERITY[code], 1, 1, None),)
    elif outcome is SchedulePublicationStatus.REVIEW_REQUIRED:
        code = ScheduleIssueCode.DUPLICATE_ACTIVITY_ID
        issues = (ScheduleParseIssue(code, ISSUE_SEVERITY[code], 1, 1, None),)
    elif outcome is not SchedulePublicationStatus.COMPLETE:
        raise ValueError("the harness builds complete, partial or review_required results")

    def count(row_type: ScheduleRowType) -> int:
        return sum(1 for row in rows if row.row_type is row_type)

    return ScheduleParseResult(
        parser_name="cpm-workbench-full-parser",
        parser_version="1",
        profile_id="p6_full_v1",
        profile_version=1,
        document_sha256=hashlib.sha256(data).hexdigest(),
        document_size_bytes=len(data),
        outcome=outcome,
        published_schedule_title=title,
        data_date=data_date,
        run_date=data_date,
        counts=ScheduleParseCounts(
            pages=max((row.page_number for row in rows), default=1),
            rows=len(rows),
            project_summaries=count(ScheduleRowType.PROJECT_SUMMARY),
            wbs_summaries=count(ScheduleRowType.WBS_SUMMARY),
            activities=count(ScheduleRowType.ACTIVITY),
            milestones=count(ScheduleRowType.MILESTONE),
            ambiguous=count(ScheduleRowType.AMBIGUOUS),
            chart_objects_excluded=0,
            watermark_objects_excluded=0,
            suppressed_objects=0,
            duplicate_objects_collapsed=0,
            non_embedded_font_objects=0,
            issues=len(issues),
            warnings=0,
        ),
        rows=rows,
        issues=issues,
        engine=ScheduleParseEngine(pypdfium2_version="4.30.0", pdfium_version="synthetic-1"),
    )


class _Provider(SourceProvider):
    """Serves the synthetic bytes of every registered object at its version."""

    def __init__(self, source_id: str, objects: Mapping[str, tuple[str, bytes]]) -> None:
        self._source_id = source_id
        self._objects = objects

    @property
    def source_id(self) -> str:
        return self._source_id

    def list_children(self, parent_object_id: str | None = None) -> Iterator[SourceObject]:
        del parent_object_id
        return iter(())

    def metadata(self, source_object_id: str) -> SourceObject:
        version, data = self._objects[source_object_id]
        return SourceObject(
            source_id=self._source_id,
            source_object_id=source_object_id,
            version_id=version,
            kind=ObjectKind.FILE,
            media_type="application/pdf",
            size_bytes=len(data),
            modified_at=datetime(2026, 5, 4, tzinfo=UTC),
        )

    def fetch(self, source_object_id: str, *, max_bytes: int) -> SourceObjectContent:
        version, data = self._objects[source_object_id]
        return SourceObjectContent(
            source_object_id=source_object_id,
            version_id=version,
            media_type="application/pdf",
            content=data[:max_bytes],
            is_truncated=len(data) > max_bytes,
        )


def cpm_snapshot(engine: Engine) -> dict[str, list[str]]:
    """Every CPM row this database holds, as comparable text."""
    found: dict[str, list[str]] = {}
    with engine.connect() as connection:
        for table in CPM_TABLES:
            rows = connection.execute(text(f"SELECT * FROM knowledge.{table}")).all()  # noqa: S608
            found[table] = sorted(repr(tuple(row)) for row in rows)
    return found


@dataclass
class ScheduleRuntime:
    """`ApplicationService` over PostgreSQL with the Schedule plane stated explicitly."""

    url: str
    enabled: bool = True
    composed: bool = True
    now: datetime | None = None
    objects: dict[str, tuple[str, bytes]] = field(default_factory=dict)
    results: dict[str, IsolatedParse] = field(default_factory=dict)
    _counter: int = 0

    def __post_init__(self) -> None:
        self.engine = create_database_engine(self.url)
        self.audit_engine = create_database_engine(self.url)
        audit = SqlAlchemyAuditSink(self.audit_engine)
        enabled = self.enabled and self.composed

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(self.engine, audit=audit, schedule_enabled=enabled)

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            clock=self._clock,
            schedule_enabled=self.enabled,
            schedule_unit_of_work=(
                (lambda: SqlAlchemyScheduleUnitOfWork(self.engine)) if self.composed else None
            ),
        )

    def _clock(self) -> datetime:
        return datetime.now(UTC) if self.now is None else self.now

    def close(self) -> None:
        self.engine.dispose()
        self.audit_engine.dispose()

    # ---- seeds -----------------------------------------------------------------------

    def world(self, principal: str, tag: str, *, source: str | None = None) -> World:
        world = World(
            principal=principal,
            tag=tag,
            source=source or f"src_{tag}0001",
            project=f"prj_{tag}0001",
            enrollment=f"enr_{tag}0001",
        )
        with self.engine.begin() as c:
            if source is None:
                c.execute(
                    text(
                        "INSERT INTO knowledge.sources (source_id, provider_kind, label, "
                        "classification, native_root) VALUES (:s, 'fixture', 'Synthetic', "
                        "'synthetic_test', :root)"
                    ),
                    {"s": world.source, "root": f"/synthetic/schedule/{tag}"},
                )
            c.execute(
                text(
                    "INSERT INTO knowledge.enrollments (enrollment_id, source_id, principal_id, "
                    "purpose, policy_version, idempotency_key, request_fingerprint, object_ids, "
                    "depth, media_types, max_items, max_bytes) VALUES (:e, :s, :p, "
                    "'schedule_import', 'policy-v1', :key, 'synthetic', ARRAY[:root], 0, "
                    "ARRAY['application/pdf'], 100, :max)"
                ),
                {
                    "e": world.enrollment,
                    "s": world.source,
                    "p": principal,
                    "key": f"{tag}-pdf",
                    "root": f"obj_{tag}root",
                    "max": SIXTEEN_MIB,
                },
            )
            c.execute(
                text(
                    "INSERT INTO knowledge.projects (project_id, principal_id, name, opened_at, "
                    "created_at, updated_at) VALUES (:j, :p, 'Synthetic Project', now(), now(), "
                    "now())"
                ),
                {"j": world.project, "p": principal},
            )
        return world

    def source_object(
        self,
        world: World,
        *,
        media_type: str = "application/pdf",
        size: int | None = None,
        enrolled: bool = True,
        enrollment: str | None = None,
    ) -> tuple[str, str]:
        """A new enrolled object and its one version: `(object_id, version_id)`."""
        self._counter += 1
        suffix = f"{world.tag}{self._counter:05d}"
        object_id, version_id = f"obj_{suffix}", f"ver_{suffix}"
        with self.engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO knowledge.source_objects (source_object_id, source_id, kind, "
                    "native_locator) VALUES (:o, :s, 'file', :locator)"
                ),
                {"o": object_id, "s": world.source, "locator": f"/synthetic/{suffix}.pdf"},
            )
            c.execute(
                text(
                    "INSERT INTO knowledge.source_object_versions (version_id, source_object_id, "
                    "fingerprint, media_type, size_bytes, modified_at) VALUES (:v, :o, :v, :m, "
                    ":size, now())"
                ),
                {"v": version_id, "o": object_id, "m": media_type, "size": size},
            )
            if enrolled:
                c.execute(
                    text(
                        "INSERT INTO knowledge.enrollment_objects (enrollment_id, "
                        "source_object_id) VALUES (:e, :o)"
                    ),
                    {"e": enrollment or world.enrollment, "o": object_id},
                )
        self.objects[object_id] = (version_id, f"%PDF-1.7 synthetic {suffix}".encode())
        return object_id, version_id

    # ---- invoke ------------------------------------------------------------------------

    def invoke(
        self,
        command: Command,
        *,
        principal_id: str = PRINCIPAL,
        purpose: Purpose | None = None,
        surface: OperatorSurface | None = None,
        remote_client: str | None = None,
        grants: frozenset[tuple[Capability, Purpose | None]] | None = None,
        service: ApplicationService | None = None,
    ) -> ResponseEnvelope:
        """One request; a remote call carries a grant on its own capability unless given."""
        capability = command.capability
        chosen = purpose or sorted(permitted_purposes(capability))[0]
        remote = remote_client is not None
        if remote and grants is None:
            grants = frozenset({(capability, chosen)})
        return (service or self.service).invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=capability,
                purpose=chosen,
                principal_id=principal_id,
                requested_at=self._clock(),
            ),
            command,
            principal=Principal(
                principal_id=principal_id, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
            transport=CaptureTransport.REMOTE_CLIENT if remote else CaptureTransport.LOCAL,
            capability_grants=grants,
            authenticated_client_id=remote_client,
            operator_surface=surface,
        )

    def ok(self, command: Command, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        envelope = self.invoke(command, **kwargs)
        assert envelope.error is None, (command.capability.value, envelope.error)
        dumped = envelope.to_canonical_dict()
        result = dumped["result"]
        assert isinstance(result, dict)
        return {**result, "__disclosure__": dumped["disclosure"]}

    def refused(self, command: Command, **kwargs: Any) -> tuple[str, list[str]]:  # noqa: ANN401
        envelope = self.invoke(command, **kwargs)
        assert envelope.error is not None, command.capability.value
        error = envelope.to_canonical_dict()["error"]
        assert isinstance(error, dict)
        return str(error["code"]), list(error.get("safe_details") or [])

    # ---- publish -----------------------------------------------------------------------

    def import_(
        self,
        world: World,
        object_id: str,
        version_id: str,
        *,
        series_name: str | None = "Master Schedule",
        series_id: str | None = None,
        role: str = "update",
        baseline_kind: str | None = None,
        key: str | None = None,
        supersedes: str | None = None,
        expected: str | None = None,
        surface: OperatorSurface = OperatorSurface.CLI,
    ) -> dict[str, Any]:
        """`schedule_publications.import` through the attested CLI surface."""
        self._counter += 1
        return self.ok(
            ImportSchedulePublication(
                project_id=world.project,
                series_id=series_id,
                series_name=None if series_id is not None else series_name,
                enrollment_id=world.enrollment,
                source_object_id=object_id,
                source_version_id=version_id,
                publication_role=role,
                baseline_kind=baseline_kind,
                expected_data_date=expected,
                supersedes_publication_id=supersedes,
                idempotency_key=key or f"schedule-import-{world.tag}-{self._counter:05d}",
            ),
            principal_id=world.principal,
            surface=surface,
        )

    def serve(self, monkeypatch: pytest.MonkeyPatch, world: World) -> None:
        """Route the handler's two seams to this runtime's objects and results."""

        def provide(_connection: Connection, source_id: str) -> SourceProvider | None:
            return _Provider(source_id, self.objects)

        def parse(data: bytes, **_kwargs: object) -> IsolatedParse:
            return self.results[hashlib.sha256(data).hexdigest()]

        del world
        monkeypatch.setattr(handler_module, "_provider_for", provide)
        monkeypatch.setattr(handler_module, "run_isolated_parse", parse)

    def run_worker(self, principal: str = PRINCIPAL) -> WorkerRun:
        return run_worker(
            self.engine,
            owner=OWNER,
            handler=process_schedule_publication,
            stop=threading.Event(),
            principal_id=principal,
            plane=SCHEDULE_JOBS,
            max_iterations=1,
            lease_seconds=300,
        )

    def publish(
        self,
        monkeypatch: pytest.MonkeyPatch,
        world: World,
        activities: Sequence[Activity],
        *,
        data_date: date,
        outcome: SchedulePublicationStatus = SchedulePublicationStatus.COMPLETE,
        **import_options: Any,  # noqa: ANN401
    ) -> str:
        """Import one synthetic publication and process it; returns its publication id."""
        object_id, version_id = self.source_object(world)
        data = self.objects[object_id][1]
        self.results[hashlib.sha256(data).hexdigest()] = ParsedResult(
            build_result(data, activities, data_date=data_date, outcome=outcome)
        )
        admitted = self.import_(world, object_id, version_id, **import_options)
        self.serve(monkeypatch, world)
        ran = self.run_worker(world.principal)
        assert ran.completed == 1, ran
        return str(admitted["publication_id"])

    # ---- reads of the store -------------------------------------------------------------

    def audit_count(self, capability: Capability | None = None) -> int:
        statement = select(func.count()).select_from(audit_events)
        if capability is not None:
            statement = statement.where(audit_events.c.capability == capability.value)
        with self.audit_engine.connect() as connection:
            return int(connection.execute(statement).scalar_one())

    def last_audit(self) -> Mapping[str, Any]:
        with self.audit_engine.connect() as connection:
            row = (
                connection.execute(
                    select(audit_events).order_by(audit_events.c.recorded_at.desc()).limit(1)
                )
                .mappings()
                .one()
            )
        return dict(row)

    def scalar(self, sql: str, **params: object) -> Any:  # noqa: ANN401
        with self.engine.connect() as connection:
            return connection.execute(text(sql), params).scalar_one()

    def execute(self, sql: str, **params: object) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(sql), params)


def factory_of(runtime: ScheduleRuntime) -> Callable[[], SqlAlchemyScheduleUnitOfWork]:
    return lambda: SqlAlchemyScheduleUnitOfWork(runtime.engine)
