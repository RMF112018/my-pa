"""Repository-side GoodNotes durable-note pipeline.

Owns stage advancement on the existing `goodnotes_ingestion_runs` identity.
Does not auto-activate. External Agent/model work is outside this module:
CONTENT_READY / WAITING_PROPOSAL is a commit point. Terminal SUCCEEDED only
after RECONCILE and PREVIEW. Lineage is not pipeline completion.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Protocol

from my_pa.application.goodnotes import require_available_liveness
from my_pa.application.goodnotes_delivery import (
    GoodNotesDeliveryAttemptLedger,
    GoodNotesDeliveryRepository,
    GoodNotesNewOnlyDelivery,
    existing_delivery_receipt,
)
from my_pa.application.goodnotes_lineage import (
    GoodNotesLineageRepository,
    GoodNotesLineageService,
    LineageReconcileRequest,
    ObservedNotebookFile,
    PageRenderer,
    ingestion_request_fingerprint,
    verify_persisted_page_identity,
)
from my_pa.application.goodnotes_occurrences import (
    GoodNotesOccurrenceReconciler,
    GoodNotesOccurrenceRepository,
    GoodNotesSemanticPromotionEvidence,
)
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import utc_now
from my_pa.domain.goodnotes.liveness import GoodNotesSourceLivenessReceipt
from my_pa.domain.goodnotes.models import (
    MAX_GOODNOTES_RASTER_BYTES,
    PIPELINE_STAGES,
    GoodNotesDeliveryAttemptState,
    GoodNotesIngestionRun,
    GoodNotesIngestionStatus,
    GoodNotesIngestionTrigger,
    GoodNotesPageRaster,
    GoodNotesPipelineStage,
    GoodNotesRunStage,
    GoodNotesSourceSnapshot,
    GoodNotesStageStatus,
    PageRender,
    SourcePage,
    issue_stable_id,
)

PREVIEW_DESTINATION = "operator-local"
ROLLOUT_STAGE_ORDER: tuple[str, ...] = (
    "observe-only",
    "page-identity-dry-run",
    "semantic-proposals-without-canonical-note-writes",
    "canonical-writes-with-delivery-disabled",
    "new-only-summary-preview",
    "operator-reviewed-delivery-canary",
    "bounded-scheduled-operation",
    "optional-tbr-bridge",
)
_TBR_STAGE = "optional-tbr-bridge"
_EFFECT_RANK: dict[str, int] = {
    "observe": 0,
    "split_render_lineage": 1,
    "semantic_proposals": 2,
    "canonical_writes": 3,
    "preview": 4,
    "attempt_ledger": 5,
}


class DurableNoteStageError(RuntimeError):
    """Injected or recorded stage failure. The run is not terminal success."""

    def __init__(self, stage: GoodNotesPipelineStage, run_id: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.run_id = run_id


class DurableNoteContinuationError(ValueError):
    """Identity or completed-stage consistency rejected. Existing run is not mutated."""


class RolloutGateError(RuntimeError):
    """The selected rollout stage forbids this run. No pipeline side effects."""


class AdmittedPageSplitter(Protocol):
    def __call__(self, payload: bytes) -> tuple[bytes, ...]: ...


class PageRasterizer(PageRenderer, Protocol):
    def render_png(self, page_bytes: bytes) -> tuple[PageRender, bytes]: ...


class GoodNotesDurableNoteStore(
    GoodNotesLineageRepository,
    GoodNotesOccurrenceRepository,
    GoodNotesDeliveryRepository,
    Protocol,
):
    """Lineage, stage ledger, rasters, proposals, occurrences, and preview."""

    def create_run(self, run: GoodNotesIngestionRun) -> GoodNotesIngestionRun: ...

    def update_run(self, run: GoodNotesIngestionRun) -> GoodNotesIngestionRun: ...

    def run(self, principal_id: str, run_id: str) -> GoodNotesIngestionRun | None: ...

    def run_by_request(
        self, principal_id: str, request_id: str
    ) -> GoodNotesIngestionRun | None: ...

    def record_stage(self, stage: GoodNotesRunStage) -> GoodNotesRunStage: ...

    def stages(self, principal_id: str, run_id: str) -> tuple[GoodNotesRunStage, ...]: ...

    def store_page_raster(self, raster: GoodNotesPageRaster) -> GoodNotesPageRaster: ...

    def page_raster(
        self, principal_id: str, page_version_id: str
    ) -> GoodNotesPageRaster | None: ...

    def semantic_proposals_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[tuple[str, str, str, str, dict[str, object]], ...]: ...

    def store_semantic_proposal(
        self,
        principal_id: str,
        run_id: str,
        page_version_id: str,
        schema_version: str,
        analyzer_name: str,
        analyzer_version: str,
        payload: dict[str, object],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class DurableNoteRequest:
    principal_id: str
    request_id: str
    source_root_id: str
    source_object_id: str
    source_id: str
    source_version_id: str
    observation: ObservedNotebookFile
    liveness: GoodNotesSourceLivenessReceipt
    pdf_bytes: bytes = field(repr=False)
    notebook_id: str | None = None
    label: str | None = None
    trigger_type: GoodNotesIngestionTrigger = GoodNotesIngestionTrigger.MANUAL
    observed_at: datetime | None = None
    representation_media_type: str = "application/pdf"


@dataclass(frozen=True, slots=True)
class DurableNoteResult:
    run: GoodNotesIngestionRun
    stages: tuple[GoodNotesRunStage, ...]
    waiting_for_proposal: bool
    preview_receipt_id: str | None = None
    rollout_stage: str = "observe-only"


def rollout_stage_permits(stage: str, effect: str) -> bool:
    """Whether the named orchestrator effect is in the selected stage's prefix."""
    if stage not in ROLLOUT_STAGE_ORDER or stage == _TBR_STAGE:
        return False
    return ROLLOUT_STAGE_ORDER.index(stage) >= _EFFECT_RANK[effect]


class GoodNotesDurableNoteOrchestrator:
    """Advance observe → settle → split/render → lineage → content-ready → …"""

    def __init__(
        self,
        *,
        lineage: GoodNotesLineageService | None = None,
        occurrences: GoodNotesOccurrenceReconciler | None = None,
        delivery: GoodNotesNewOnlyDelivery | None = None,
        rollout_stage: str = "observe-only",
    ) -> None:
        if rollout_stage not in ROLLOUT_STAGE_ORDER:
            raise RolloutGateError("unknown GoodNotes rollout stage")
        if rollout_stage == _TBR_STAGE:
            raise RolloutGateError("optional TBR bridge is unauthorized")
        self._lineage = lineage or GoodNotesLineageService()
        self._occurrences = occurrences or GoodNotesOccurrenceReconciler()
        self._delivery = delivery or GoodNotesNewOnlyDelivery()
        self._attempts = GoodNotesDeliveryAttemptLedger()
        self._rollout_stage = rollout_stage

    def run(
        self,
        request: DurableNoteRequest,
        *,
        renderer: PageRasterizer,
        splitter: AdmittedPageSplitter,
        store: GoodNotesDurableNoteStore,
        clock: Callable[[], datetime] = utc_now,
        fail_after: GoodNotesPipelineStage | None = None,
        destination: str = PREVIEW_DESTINATION,
        promotion_evidence: Sequence[GoodNotesSemanticPromotionEvidence] = (),
    ) -> DurableNoteResult:
        validate_identifier(request.principal_id, IdKind.PRINCIPAL)
        if self._rollout_stage == _TBR_STAGE:
            raise RolloutGateError("optional TBR bridge is unauthorized")
        if not request.pdf_bytes:
            raise ValueError("a durable-note run requires admitted PDF bytes")
        observed_at = request.observed_at or clock()
        require_available_liveness(
            request.liveness,
            source_root_id=request.source_root_id,
            relative_path=request.observation.relative_path,
            content_sha256=request.observation.sha256,
            at=observed_at,
        )
        existing = store.run_by_request(request.principal_id, request.request_id)
        if existing is not None:
            _assert_ingestion_identity(existing, request, renderer)
        completed = (
            {
                row.stage
                for row in store.stages(request.principal_id, existing.run_id)
                if row.status is GoodNotesStageStatus.SUCCEEDED
            }
            if existing is not None
            else set()
        )
        if existing is not None:
            _assert_completed_prefix(completed)
            if GoodNotesPipelineStage.LINEAGE in completed:
                _assert_lineage_artifact_presence(store, existing)
        pages: tuple[SourcePage, ...] = ()
        rasters: tuple[tuple[int, PageRender, bytes], ...] = ()
        if rollout_stage_permits(self._rollout_stage, "split_render_lineage"):
            pages, rasters = self._split_render(
                request, renderer=renderer, splitter=splitter, completed=completed
            )
            if existing is not None and GoodNotesPipelineStage.LINEAGE in completed:
                _assert_lineage_identity(store, existing, request, renderer, pages)
        if existing is not None:
            _assert_later_stage_consistency(store, existing, completed, destination=destination)
            _assert_not_abnormal_preview(store, existing, completed)
        terminal_preview = existing is not None and _is_terminal_preview(
            store, existing, completed, destination
        )
        run = self._bind_run(
            request,
            existing=existing,
            store=store,
            renderer=renderer,
            observed_at=observed_at,
            terminal_preview=terminal_preview,
        )
        completed = {
            row.stage
            for row in store.stages(request.principal_id, run.run_id)
            if row.status is GoodNotesStageStatus.SUCCEEDED
        }

        def after(stage: GoodNotesPipelineStage) -> None:
            if fail_after is stage:
                raise DurableNoteStageError(
                    stage, run.run_id, f"injected failure after {stage.value}"
                )

        def snapshot(
            current: GoodNotesIngestionRun,
            *,
            waiting: bool,
            preview_id: str | None = None,
        ) -> DurableNoteResult:
            return DurableNoteResult(
                run=current,
                stages=store.stages(request.principal_id, current.run_id),
                waiting_for_proposal=waiting,
                preview_receipt_id=preview_id,
                rollout_stage=self._rollout_stage,
            )

        prepared = False
        try:
            if GoodNotesPipelineStage.OBSERVE not in completed:
                self._complete_stage(store, run, GoodNotesPipelineStage.OBSERVE, observed_at, clock)
                after(GoodNotesPipelineStage.OBSERVE)
            if GoodNotesPipelineStage.SETTLE not in completed:
                self._complete_stage(store, run, GoodNotesPipelineStage.SETTLE, observed_at, clock)
                after(GoodNotesPipelineStage.SETTLE)
            if not rollout_stage_permits(self._rollout_stage, "split_render_lineage"):
                return snapshot(run, waiting=False)
            if GoodNotesPipelineStage.SPLIT_RENDER not in completed:
                self._complete_stage(
                    store, run, GoodNotesPipelineStage.SPLIT_RENDER, observed_at, clock
                )
                after(GoodNotesPipelineStage.SPLIT_RENDER)
            skip_lineage = GoodNotesPipelineStage.LINEAGE in completed
            if skip_lineage:
                snapshot_row = _required_snapshot(store, run)
                positions = store.page_positions(run.principal_id, snapshot_row.snapshot_id)
            else:
                lineage = self._lineage.reconcile(
                    LineageReconcileRequest(
                        principal_id=request.principal_id,
                        request_id=request.request_id,
                        source_root_id=request.source_root_id,
                        source_object_id=request.source_object_id,
                        observation=request.observation,
                        pages=pages,
                        notebook_id=request.notebook_id,
                        label=request.label,
                        trigger_type=request.trigger_type,
                        observed_at=observed_at,
                    ),
                    renderer=renderer,
                    repository=store,
                    clock=clock,
                    finalize_run=False,
                )
                run = lineage.run
                positions = lineage.positions
                if GoodNotesPipelineStage.LINEAGE not in completed:
                    self._complete_stage(
                        store, run, GoodNotesPipelineStage.LINEAGE, observed_at, clock
                    )
                    after(GoodNotesPipelineStage.LINEAGE)
            self._persist_rasters(store, run, positions, rasters, observed_at)
            if not rollout_stage_permits(self._rollout_stage, "semantic_proposals"):
                return snapshot(run, waiting=False)
            if GoodNotesPipelineStage.CONTENT_READY not in completed:
                self._complete_stage(
                    store, run, GoodNotesPipelineStage.CONTENT_READY, observed_at, clock
                )
                after(GoodNotesPipelineStage.CONTENT_READY)
            proposals = store.semantic_proposals_for_run(request.principal_id, run.run_id)
            if not proposals:
                if GoodNotesPipelineStage.WAITING_PROPOSAL not in completed:
                    self._complete_stage(
                        store, run, GoodNotesPipelineStage.WAITING_PROPOSAL, observed_at, clock
                    )
                    after(GoodNotesPipelineStage.WAITING_PROPOSAL)
                run = store.update_run(
                    replace(run, status=GoodNotesIngestionStatus.RUNNING, ended_at=None)
                )
                return snapshot(run, waiting=True)
            if not rollout_stage_permits(self._rollout_stage, "canonical_writes"):
                return snapshot(run, waiting=False)
            if GoodNotesPipelineStage.RECONCILE not in completed:
                self._occurrences.reconcile(
                    request.principal_id,
                    run.run_id,
                    repository=store,
                    clock=clock,
                    promotion_evidence=promotion_evidence,
                )
                self._complete_stage(
                    store, run, GoodNotesPipelineStage.RECONCILE, observed_at, clock
                )
                after(GoodNotesPipelineStage.RECONCILE)
            if not rollout_stage_permits(self._rollout_stage, "preview"):
                return snapshot(run, waiting=False)
            token = request.request_id
            if rollout_stage_permits(self._rollout_stage, "attempt_ledger"):
                self._attempts.record(
                    request.principal_id,
                    run.run_id,
                    destination,
                    token,
                    GoodNotesDeliveryAttemptState.PREPARED,
                    repository=store,
                    clock=clock,
                )
                prepared = True
            preview = self._delivery.deliver(
                request.principal_id,
                run.run_id,
                destination,
                repository=store,
                clock=clock,
            )
            if rollout_stage_permits(self._rollout_stage, "attempt_ledger"):
                self._attempts.record(
                    request.principal_id,
                    run.run_id,
                    destination,
                    token,
                    GoodNotesDeliveryAttemptState.ACKNOWLEDGED,
                    repository=store,
                    clock=clock,
                    summary_hash=preview.receipt.summary_hash,
                    receipt_id=preview.receipt.receipt_id,
                )
            if GoodNotesPipelineStage.PREVIEW not in completed:
                self._complete_stage(store, run, GoodNotesPipelineStage.PREVIEW, observed_at, clock)
                after(GoodNotesPipelineStage.PREVIEW)
            if not terminal_preview and run.status is not GoodNotesIngestionStatus.SUCCEEDED:
                run = store.update_run(
                    replace(
                        run,
                        status=GoodNotesIngestionStatus.SUCCEEDED,
                        ended_at=clock(),
                    )
                )
            elif terminal_preview and run.status is not GoodNotesIngestionStatus.SUCCEEDED:
                run = store.update_run(
                    replace(
                        run,
                        status=GoodNotesIngestionStatus.SUCCEEDED,
                        ended_at=clock() if run.ended_at is None else run.ended_at,
                    )
                )
            return snapshot(run, waiting=False, preview_id=preview.receipt.receipt_id)
        except DurableNoteStageError:
            raise
        except RolloutGateError:
            raise
        except DurableNoteContinuationError:
            raise
        except Exception as error:
            if terminal_preview:
                if prepared:
                    self._attempts.record(
                        request.principal_id,
                        run.run_id,
                        destination,
                        request.request_id,
                        GoodNotesDeliveryAttemptState.FAILED,
                        repository=store,
                        clock=clock,
                    )
                raise DurableNoteStageError(
                    GoodNotesPipelineStage.PREVIEW,
                    run.run_id,
                    "durable-note stage failed",
                ) from error
            failed = self._fail_run(store, run, clock, error)
            run = failed
            raise DurableNoteStageError(
                _current_open_stage(store, run.run_id, request.principal_id)
                or GoodNotesPipelineStage.PREVIEW,
                run.run_id,
                "durable-note stage failed",
            ) from error

    def _bind_run(
        self,
        request: DurableNoteRequest,
        *,
        existing: GoodNotesIngestionRun | None,
        store: GoodNotesDurableNoteStore,
        renderer: PageRasterizer,
        observed_at: datetime,
        terminal_preview: bool,
    ) -> GoodNotesIngestionRun:
        if existing is None:
            digest = ingestion_request_fingerprint(
                principal_id=request.principal_id,
                source_root_id=request.source_root_id,
                source_object_id=request.source_object_id,
                observation_sha256=request.observation.sha256,
                renderer=renderer,
            )
            return store.create_run(
                GoodNotesIngestionRun(
                    run_id=issue_stable_id("gnrun", request.principal_id, request.request_id),
                    principal_id=request.principal_id,
                    source_root_id=request.source_root_id,
                    trigger_type=request.trigger_type,
                    request_id=request.request_id,
                    idempotency_key=request.request_id,
                    request_fingerprint=digest,
                    started_at=observed_at,
                    status=GoodNotesIngestionStatus.RUNNING,
                )
            )
        if existing.status is GoodNotesIngestionStatus.FAILED and not terminal_preview:
            return store.update_run(
                replace(
                    existing,
                    status=GoodNotesIngestionStatus.RUNNING,
                    ended_at=None,
                    error_code=None,
                    error_class=None,
                )
            )
        return existing

    def _split_render(
        self,
        request: DurableNoteRequest,
        *,
        renderer: PageRasterizer,
        splitter: AdmittedPageSplitter,
        completed: set[GoodNotesPipelineStage],
    ) -> tuple[tuple[SourcePage, ...], tuple[tuple[int, PageRender, bytes], ...]]:
        del completed
        parts = splitter(request.pdf_bytes)
        pages: list[SourcePage] = []
        rasters: list[tuple[int, PageRender, bytes]] = []
        observed_at = request.observed_at or utc_now()
        for index, part in enumerate(parts, start=1):
            render, png = renderer.render_png(part)
            if len(png) > MAX_GOODNOTES_RASTER_BYTES:
                raise ValueError("GoodNotes visual raster exceeds the admitted size cap")
            pages.append(
                SourcePage(
                    principal_id=request.principal_id,
                    source_id=request.source_id,
                    source_object_id=request.source_object_id,
                    source_version_id=request.source_version_id,
                    page_number=index,
                    observed_at=observed_at,
                    content=part,
                    representation_media_type=request.representation_media_type,
                )
            )
            rasters.append((index, render, png))
        if not pages:
            raise ValueError("a durable-note run requires admitted pages")
        return tuple(pages), tuple(rasters)

    def _persist_rasters(
        self,
        store: GoodNotesDurableNoteStore,
        run: GoodNotesIngestionRun,
        positions: Sequence[object],
        rasters: Sequence[tuple[int, PageRender, bytes]],
        created_at: datetime,
    ) -> None:
        by_number = {number: (render, png) for number, render, png in rasters}
        for position in positions:
            page_number = position.page_number  # type: ignore[attr-defined]
            page_version_id = position.page_version_id  # type: ignore[attr-defined]
            if page_version_id is None:
                continue
            held = store.page_raster(run.principal_id, page_version_id)
            if held is not None:
                continue
            render, png = by_number[page_number]
            if len(png) > MAX_GOODNOTES_RASTER_BYTES:
                raise ValueError("GoodNotes visual raster exceeds the admitted size cap")
            store.store_page_raster(
                GoodNotesPageRaster(
                    principal_id=run.principal_id,
                    page_version_id=page_version_id,
                    run_id=run.run_id,
                    exact_render_sha256=render.exact_render_sha256,
                    png_sha256=hashlib.sha256(png).hexdigest(),
                    byte_length=len(png),
                    png_bytes=png,
                    renderer_name=render.renderer_name,
                    renderer_version=render.renderer_version,
                    render_profile_version=render.render_profile_version,
                    created_at=created_at,
                )
            )

    def _complete_stage(
        self,
        store: GoodNotesDurableNoteStore,
        run: GoodNotesIngestionRun,
        stage: GoodNotesPipelineStage,
        started_at: datetime,
        clock: Callable[[], datetime],
    ) -> GoodNotesRunStage:
        existing = {row.stage: row for row in store.stages(run.principal_id, run.run_id)}.get(stage)
        attempt = (
            1
            if existing is None
            else existing.attempt + (0 if existing.status is GoodNotesStageStatus.SUCCEEDED else 1)
        )
        if existing is not None and existing.status is GoodNotesStageStatus.SUCCEEDED:
            return existing
        return store.record_stage(
            GoodNotesRunStage(
                principal_id=run.principal_id,
                run_id=run.run_id,
                stage=stage,
                status=GoodNotesStageStatus.SUCCEEDED,
                started_at=started_at,
                attempt=max(attempt, 1),
                ended_at=clock(),
            )
        )

    def _fail_run(
        self,
        store: GoodNotesDurableNoteStore,
        run: GoodNotesIngestionRun,
        clock: Callable[[], datetime],
        error: Exception,
    ) -> GoodNotesIngestionRun:
        stage = _current_open_stage(store, run.run_id, run.principal_id)
        if stage is None:
            return run
        store.record_stage(
            GoodNotesRunStage(
                principal_id=run.principal_id,
                run_id=run.run_id,
                stage=stage,
                status=GoodNotesStageStatus.FAILED,
                started_at=run.started_at,
                ended_at=clock(),
                error_code="STAGE_FAILED",
                error_class=type(error).__name__,
            )
        )
        return store.update_run(
            replace(
                run,
                status=GoodNotesIngestionStatus.FAILED,
                ended_at=clock(),
                error_code="STAGE_FAILED",
                error_class=type(error).__name__,
            )
        )


def _current_open_stage(
    store: GoodNotesDurableNoteStore, run_id: str, principal_id: str
) -> GoodNotesPipelineStage | None:
    done = {
        row.stage
        for row in store.stages(principal_id, run_id)
        if row.status is GoodNotesStageStatus.SUCCEEDED
    }
    for stage in PIPELINE_STAGES:
        if stage not in done:
            return stage
    return None


def _bound_identity_error() -> DurableNoteContinuationError:
    return DurableNoteContinuationError("the request id is bound to another ingestion")


def _consistency_error() -> DurableNoteContinuationError:
    return DurableNoteContinuationError("durable-note continuation is inconsistent")


def _assert_ingestion_identity(
    existing: GoodNotesIngestionRun,
    request: DurableNoteRequest,
    renderer: PageRenderer,
) -> None:
    digest = ingestion_request_fingerprint(
        principal_id=request.principal_id,
        source_root_id=request.source_root_id,
        source_object_id=request.source_object_id,
        observation_sha256=request.observation.sha256,
        renderer=renderer,
    )
    if existing.request_fingerprint != digest:
        raise _bound_identity_error()
    if existing.source_root_id != request.source_root_id:
        raise _bound_identity_error()


def _assert_completed_prefix(completed: set[GoodNotesPipelineStage]) -> None:
    for stage in completed:
        for prior in PIPELINE_STAGES:
            if prior is stage:
                break
            if prior is GoodNotesPipelineStage.WAITING_PROPOSAL:
                continue
            if prior not in completed:
                raise _consistency_error()


def _required_snapshot(
    store: GoodNotesDurableNoteStore, run: GoodNotesIngestionRun
) -> GoodNotesSourceSnapshot:
    snapshots = store.snapshots_for_run(run.principal_id, run.run_id)
    if len(snapshots) != 1:
        raise _consistency_error()
    return snapshots[0]


def _assert_lineage_artifact_presence(
    store: GoodNotesDurableNoteStore, run: GoodNotesIngestionRun
) -> None:
    snapshot = _required_snapshot(store, run)
    positions = store.page_positions(run.principal_id, snapshot.snapshot_id)
    expected_count = snapshot.page_count
    if expected_count < 1 or len(positions) != expected_count:
        raise _consistency_error()
    numbers = tuple(item.page_number for item in positions)
    if numbers != tuple(range(1, expected_count + 1)):
        raise _consistency_error()
    for position in positions:
        if position.page_version_id is None or position.logical_page_id is None:
            raise _consistency_error()
        version = store.page_version(run.principal_id, position.page_version_id)
        if version is None:
            raise _consistency_error()
        page = store.page(run.principal_id, version.page_id)
        if page is None:
            raise _consistency_error()


def _assert_lineage_identity(
    store: GoodNotesDurableNoteStore,
    run: GoodNotesIngestionRun,
    request: DurableNoteRequest,
    renderer: PageRenderer,
    pages: tuple[SourcePage, ...],
) -> None:
    snapshot = _required_snapshot(store, run)
    if snapshot.source_object_id != request.source_object_id:
        raise _bound_identity_error()
    if snapshot.raw_sha256 != request.observation.sha256:
        raise _bound_identity_error()
    if snapshot.size_bytes != request.observation.size_bytes:
        raise _bound_identity_error()
    page_count = (
        request.observation.page_count if request.observation.page_count is not None else len(pages)
    )
    if snapshot.page_count != page_count or snapshot.page_count != len(pages):
        raise _bound_identity_error()
    if request.notebook_id is not None and snapshot.notebook_id != request.notebook_id:
        raise _bound_identity_error()
    notebook = store.notebook(run.principal_id, snapshot.notebook_id)
    if notebook is None or notebook.source_root_id != request.source_root_id:
        raise _bound_identity_error()
    positions = store.page_positions(run.principal_id, snapshot.snapshot_id)
    try:
        verify_persisted_page_identity(
            principal_id=run.principal_id,
            pages=pages,
            positions=positions,
            renderer=renderer,
            repository=store,
            verify_supplied_content_digest=False,
        )
    except ValueError as error:
        raise _bound_identity_error() from error


def _assert_later_stage_consistency(
    store: GoodNotesDurableNoteStore,
    run: GoodNotesIngestionRun,
    completed: set[GoodNotesPipelineStage],
    *,
    destination: str,
) -> None:
    if GoodNotesPipelineStage.LINEAGE in completed:
        snapshot = _required_snapshot(store, run)
        positions = store.page_positions(run.principal_id, snapshot.snapshot_id)
        if GoodNotesPipelineStage.CONTENT_READY in completed:
            for position in positions:
                if position.page_version_id is None:
                    raise _consistency_error()
                if store.page_raster(run.principal_id, position.page_version_id) is None:
                    raise _consistency_error()
    if (
        GoodNotesPipelineStage.RECONCILE in completed or GoodNotesPipelineStage.PREVIEW in completed
    ) and not store.semantic_proposals_for_run(run.principal_id, run.run_id):
        raise _consistency_error()
    if GoodNotesPipelineStage.RECONCILE in completed:
        changes = store.run_note_changes(run.principal_id, run.run_id)
        for change in changes:
            if change.occurrence_id is not None and (
                store.occurrence(run.principal_id, change.occurrence_id) is None
            ):
                raise _consistency_error()
            if change.revision_id is not None and (
                store.revision(run.principal_id, change.revision_id) is None
            ):
                raise _consistency_error()
            if change.note_id is not None and store.note(run.principal_id, change.note_id) is None:
                raise _consistency_error()
    if GoodNotesPipelineStage.PREVIEW in completed:
        receipt = existing_delivery_receipt(
            run.principal_id,
            run.run_id,
            destination,
            repository=store,
        )
        if receipt is not None:
            receipt = store.delivery_receipt_by_key(
                run.principal_id,
                run.run_id,
                destination,
                receipt.summary_hash,
            )
        if receipt is None:
            raise _consistency_error()
        if run.status is GoodNotesIngestionStatus.FAILED:
            raise _consistency_error()


def _preview_stage(
    store: GoodNotesDurableNoteStore, run: GoodNotesIngestionRun
) -> GoodNotesRunStage | None:
    found = [
        row
        for row in store.stages(run.principal_id, run.run_id)
        if row.stage is GoodNotesPipelineStage.PREVIEW
    ]
    return found[-1] if found else None


def _assert_not_abnormal_preview(
    store: GoodNotesDurableNoteStore,
    run: GoodNotesIngestionRun,
    completed: set[GoodNotesPipelineStage],
) -> None:
    del completed
    preview = _preview_stage(store, run)
    receipts = store.delivery_receipts_for_run(run.principal_id, run.run_id)
    if preview is not None and preview.status is GoodNotesStageStatus.FAILED and receipts:
        raise _consistency_error()


def _is_terminal_preview(
    store: GoodNotesDurableNoteStore,
    run: GoodNotesIngestionRun,
    completed: set[GoodNotesPipelineStage],
    destination: str,
) -> bool:
    if GoodNotesPipelineStage.PREVIEW not in completed:
        return False
    if run.status is GoodNotesIngestionStatus.FAILED:
        return False
    receipt = existing_delivery_receipt(
        run.principal_id,
        run.run_id,
        destination,
        repository=store,
    )
    if receipt is not None:
        receipt = store.delivery_receipt_by_key(
            run.principal_id,
            run.run_id,
            destination,
            receipt.summary_hash,
        )
    return receipt is not None
