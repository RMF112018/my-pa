"""In-memory GoodNotes evaluation unit of work. Isolated from live Postgres.

Serves `goodnotes.work` and `goodnotes.content` only. `goodnotes.propose`
refuses. No other plane is reachable.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from types import TracebackType
from typing import cast

from my_pa.contracts.ports import (
    Acceptance,
    AuditSink,
    CaptureRepository,
    CommitmentManagementRepository,
    ContextPreferenceRepository,
    ContextRunRepository,
    EnrollmentRepository,
    EntitiesRepository,
    GoodNotesProposalAdmission,
    GoodNotesSemanticRepository,
    KnowledgeRepository,
    ManagedDocumentRepository,
    OperationQueue,
    PortError,
    ProjectRepository,
    PulseRepository,
    ReviewRepository,
    SituationRepository,
    SourceProviders,
    SourceRepository,
    TaskManagementRepository,
    UnitOfWork,
)
from my_pa.domain.audit.events import AuditEvent
from my_pa.domain.goodnotes.models import GoodNotesPageRaster, GoodNotesPageWork
from my_pa.domain.source.enrollment import Enrollment, EnrollmentRequest

MappingWork = dict[tuple[str, str, str], GoodNotesPageWork]
MappingRaster = dict[tuple[str, str], GoodNotesPageRaster]


class GsqsB0EvaluationError(PortError):
    """The evaluation surface refused a plane it does not serve."""


class _EmptyEnrollments(EnrollmentRepository):
    def for_principal(self, principal_id: str) -> tuple[Enrollment, ...]:
        del principal_id
        return ()

    def accept(self, request: EnrollmentRequest) -> Acceptance:
        del request
        raise GsqsB0EvaluationError()

    def record_scope(self, enrollment_id: str, source_object_ids: Iterable[str]) -> int:
        del enrollment_id, source_object_ids
        raise GsqsB0EvaluationError()


class _MemoryAudit(AuditSink):
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


class _EvaluationSemantics(GoodNotesSemanticRepository):
    def __init__(self, work: MappingWork, rasters: MappingRaster) -> None:
        self._work = work
        self._rasters = rasters

    def page_work(
        self, principal_id: str, run_id: str, page_version_id: str
    ) -> GoodNotesPageWork | None:
        return self._work.get((principal_id, run_id, page_version_id))

    def page_raster(
        self, principal_id: str, run_id: str, page_version_id: str
    ) -> GoodNotesPageRaster | None:
        raster = self._rasters.get((principal_id, page_version_id))
        if raster is None or raster.run_id != run_id:
            return None
        return raster

    def submit_proposal(
        self,
        *,
        principal_id: str,
        run_id: str,
        page_version_id: str,
        content_sha256: str,
        schema_version: str,
        analyzer_name: str,
        analyzer_version: str,
        idempotency_key: str,
        request_fingerprint: str,
        payload_sha256: str,
        payload: dict[str, object],
        correlation_id: str,
        request_id: str,
        audit_id: str | None,
        created_at: datetime,
    ) -> GoodNotesProposalAdmission:
        del (
            principal_id,
            run_id,
            page_version_id,
            content_sha256,
            schema_version,
            analyzer_name,
            analyzer_version,
            idempotency_key,
            request_fingerprint,
            payload_sha256,
            payload,
            correlation_id,
            request_id,
            audit_id,
            created_at,
        )
        raise GsqsB0EvaluationError()


def _closed() -> object:
    class Closed:
        def __getattr__(self, item: str) -> object:
            del item
            raise GsqsB0EvaluationError()

    return Closed()


class GsqsB0EvaluationUnitOfWork(UnitOfWork):
    """One in-memory transaction over evaluation page work and rasters."""

    def __init__(
        self,
        pages: Sequence[tuple[GoodNotesPageWork, GoodNotesPageRaster]],
    ) -> None:
        work: MappingWork = {}
        rasters: MappingRaster = {}
        for item, raster in pages:
            work[(item.principal_id, item.run_id, item.page_version_id)] = item
            rasters[(raster.principal_id, raster.page_version_id)] = raster
        self._semantics = _EvaluationSemantics(work, rasters)
        self._enrollments = _EmptyEnrollments()
        self._audit = _MemoryAudit()
        self._unused = _closed()

    def __enter__(self) -> UnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback

    @property
    def providers(self) -> SourceProviders:
        return cast(SourceProviders, self._unused)

    @property
    def sources(self) -> SourceRepository:
        return cast(SourceRepository, self._unused)

    @property
    def enrollments(self) -> EnrollmentRepository:
        return self._enrollments

    @property
    def operations(self) -> OperationQueue:
        return cast(OperationQueue, self._unused)

    @property
    def knowledge(self) -> KnowledgeRepository:
        return cast(KnowledgeRepository, self._unused)

    @property
    def captures(self) -> CaptureRepository:
        return cast(CaptureRepository, self._unused)

    @property
    def reviews(self) -> ReviewRepository:
        return cast(ReviewRepository, self._unused)

    @property
    def situations(self) -> SituationRepository:
        return cast(SituationRepository, self._unused)

    @property
    def projects(self) -> ProjectRepository:
        return cast(ProjectRepository, self._unused)

    @property
    def pulse(self) -> PulseRepository:
        return cast(PulseRepository, self._unused)

    @property
    def managed_documents(self) -> ManagedDocumentRepository:
        return cast(ManagedDocumentRepository, self._unused)

    @property
    def tasks(self) -> TaskManagementRepository:
        return cast(TaskManagementRepository, self._unused)

    @property
    def commitments(self) -> CommitmentManagementRepository:
        return cast(CommitmentManagementRepository, self._unused)

    @property
    def entities(self) -> EntitiesRepository:
        return cast(EntitiesRepository, self._unused)

    @property
    def context_runs(self) -> ContextRunRepository:
        return cast(ContextRunRepository, self._unused)

    @property
    def context_preferences(self) -> ContextPreferenceRepository:
        return cast(ContextPreferenceRepository, self._unused)

    @property
    def goodnotes_semantics(self) -> GoodNotesSemanticRepository:
        return self._semantics

    @property
    def audit(self) -> AuditSink:
        return self._audit
