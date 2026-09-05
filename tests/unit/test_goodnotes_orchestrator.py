"""Repository-side durable-note pipeline: lineage is not terminal success."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from my_pa.application.goodnotes_delivery import GoodNotesNewOnlyDelivery
from my_pa.application.goodnotes_lineage import (
    GoodNotesLineageService,
    ObservedNotebookFile,
    ingestion_request_fingerprint,
)
from my_pa.application.goodnotes_occurrences import (
    GoodNotesSemanticPromotionEvidence,
    semantic_proposal_sha256,
)
from my_pa.application.goodnotes_orchestrator import (
    DurableNoteContinuationError,
    DurableNoteRequest,
    DurableNoteResult,
    DurableNoteStageError,
    GoodNotesDurableNoteOrchestrator,
    RolloutGateError,
)
from my_pa.bootstrap.goodnotes_durable_note import compose_durable_note_orchestrator
from my_pa.bootstrap.goodnotes_rollout import rollout_report
from my_pa.bootstrap.settings import GoodNotesRolloutStage, Settings
from my_pa.domain.capture.review import Disposition
from my_pa.domain.goodnotes.liveness import (
    GoodNotesSourceLiveness,
    GoodNotesSourceLivenessReceipt,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesDeliveryAttemptState,
    GoodNotesIdentityStatus,
    GoodNotesIngestionStatus,
    GoodNotesPipelineStage,
    GoodNotesRunStage,
    GoodNotesStageStatus,
    issue_stable_id,
)
from my_pa.infrastructure.goodnotes.pdf import split_admitted_pdf
from my_pa.infrastructure.goodnotes.render import production_page_renderer
from tests.unit.goodnotes_durable_note_memory import MemoryDurableNoteStore
from tests.unit.vector_pdf import Rect, vector_pdf

WHEN = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
SOURCE = "src_aaaaaaaaaaaaaaaaaaaaaaaa"
OBJECT = "obj_aaaaaaaaaaaaaaaaaaaaaaaa"
VERSION = "ver_aaaaaaaaaaaaaaaaaaaaaaaa"
ROOT_ID = "icloud-goodnotes"
COVER = (Rect(72, 400, 220, 220, 0.15),)
BODY = (Rect(80, 80, 420, 520, 0.45),)


DSN = "postgresql+psycopg://my_pa@localhost:5433/my_pa_settings_probe"
PREVIEW = "new-only-summary-preview"
SEMANTIC = "semantic-proposals-without-canonical-note-writes"
DRY_RUN = "page-identity-dry-run"
CANONICAL = "canonical-writes-with-delivery-disabled"
CANARY = "operator-reviewed-delivery-canary"
SCHEDULED = "bounded-scheduled-operation"


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _request(pdf: bytes, request_id: str) -> DurableNoteRequest:
    return DurableNoteRequest(
        principal_id=A,
        request_id=request_id,
        source_root_id=ROOT_ID,
        source_object_id=OBJECT,
        source_id=SOURCE,
        source_version_id=VERSION,
        observation=ObservedNotebookFile(
            relative_path="Notebooks/durable.goodnotes",
            size_bytes=len(pdf),
            sha256=_sha(pdf),
            mtime_ns=1,
            page_count=len(split_admitted_pdf(pdf)),
        ),
        liveness=GoodNotesSourceLivenessReceipt(
            source_root_id=ROOT_ID,
            relative_path="Notebooks/durable.goodnotes",
            state=GoodNotesSourceLiveness.AVAILABLE,
            checked_at=WHEN,
            maximum_staleness_seconds=300,
            last_seen_at=WHEN,
            current_sha256=_sha(pdf),
            prior_sha256=None,
        ),
        pdf_bytes=pdf,
        observed_at=WHEN,
    )


_PREFIX: dict[GoodNotesRolloutStage, dict[str, bool]] = {
    GoodNotesRolloutStage.OBSERVE_ONLY: {},
    GoodNotesRolloutStage.PAGE_IDENTITY_DRY_RUN: {},
    GoodNotesRolloutStage.SEMANTIC_PROPOSALS_WITHOUT_CANONICAL_NOTE_WRITES: {
        "goodnotes_durable_note_intelligence_enabled": True,
    },
    GoodNotesRolloutStage.CANONICAL_WRITES_WITH_DELIVERY_DISABLED: {
        "goodnotes_durable_note_intelligence_enabled": True,
        "goodnotes_canonical_semantic_writes_enabled": True,
    },
    GoodNotesRolloutStage.NEW_ONLY_SUMMARY_PREVIEW: {
        "goodnotes_durable_note_intelligence_enabled": True,
        "goodnotes_canonical_semantic_writes_enabled": True,
    },
    GoodNotesRolloutStage.OPERATOR_REVIEWED_DELIVERY_CANARY: {
        "goodnotes_durable_note_intelligence_enabled": True,
        "goodnotes_canonical_semantic_writes_enabled": True,
        "goodnotes_user_facing_summary_delivery_enabled": True,
    },
    GoodNotesRolloutStage.BOUNDED_SCHEDULED_OPERATION: {
        "goodnotes_durable_note_ingestion_enabled": True,
        "goodnotes_durable_note_intelligence_enabled": True,
        "goodnotes_canonical_semantic_writes_enabled": True,
        "goodnotes_user_facing_summary_delivery_enabled": True,
    },
    GoodNotesRolloutStage.OPTIONAL_TBR_BRIDGE: {
        "goodnotes_durable_note_ingestion_enabled": True,
        "goodnotes_durable_note_intelligence_enabled": True,
        "goodnotes_canonical_semantic_writes_enabled": True,
        "goodnotes_user_facing_summary_delivery_enabled": True,
        "goodnotes_tbr_bridge_enabled": True,
    },
}


def _orchestrator(stage: str = PREVIEW) -> GoodNotesDurableNoteOrchestrator:
    return GoodNotesDurableNoteOrchestrator(rollout_stage=stage)


def _compose(stage: GoodNotesRolloutStage) -> GoodNotesDurableNoteOrchestrator:
    return compose_durable_note_orchestrator(
        Settings(
            database_url=DSN,
            goodnotes_rollout_stage=stage,
            **_PREFIX[stage],
        )  # type: ignore[arg-type]
    )


def _succeeded(result: DurableNoteResult) -> set[GoodNotesPipelineStage]:
    return {row.stage for row in result.stages if row.status.value == "SUCCEEDED"}


def _notes(store: MemoryDurableNoteStore) -> list[object]:
    return [item for item in store._notes.values() if item.principal_id == A]


def _segment() -> dict[str, object]:
    return {
        "kind": "NOTE_UNIT",
        "geometry": {"x_min": 0.1, "y_min": 0.1, "width": 0.2, "height": 0.2},
        "transcription": "synthetic note",
        "primary_class": "MEETING",
    }


def _propose(store: MemoryDurableNoteStore, run_id: str) -> None:
    positions = ()
    for snapshot in store.snapshots_for_run(A, run_id):
        positions = store.page_positions(A, snapshot.snapshot_id)
        break
    assert positions
    version_id = positions[0].page_version_id
    assert version_id is not None
    store.store_semantic_proposal(
        A,
        run_id,
        version_id,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment()]},
    )


def _propose_source_context(store: MemoryDurableNoteStore, run_id: str) -> None:
    positions = ()
    for snapshot in store.snapshots_for_run(A, run_id):
        positions = store.page_positions(A, snapshot.snapshot_id)
        break
    assert positions
    version_id = positions[0].page_version_id
    assert version_id is not None
    store.store_semantic_proposal(
        A,
        run_id,
        version_id,
        "note-unit.v1",
        "synthetic",
        "1",
        {
            "segments": [
                {
                    "kind": "SOURCE_CONTEXT",
                    "geometry": {"x_min": 0.1, "y_min": 0.1, "width": 0.2, "height": 0.2},
                    "transcription": "",
                }
            ]
        },
    )


def _promotion_evidence(
    store: MemoryDurableNoteStore,
    run_id: str,
    disposition: Disposition = Disposition.ACCEPT,
) -> tuple[GoodNotesSemanticPromotionEvidence, ...]:
    return tuple(
        GoodNotesSemanticPromotionEvidence(
            principal_id=A,
            run_id=run_id,
            proposal_sha256=semantic_proposal_sha256(*proposal),
            disposition=disposition,
            corrected_payload=(
                {
                    "run_id": run_id,
                    "page_version_id": proposal[0],
                    "content_sha256": "0" * 64,
                    "schema_version": proposal[1],
                    "analyzer_name": proposal[2],
                    "analyzer_version": proposal[3],
                    "candidate_tags": [],
                    "ranked_candidates": [],
                    "confidence": None,
                    **proposal[4],
                }
                if disposition is Disposition.CORRECT_AND_ACCEPT
                else None
            ),
            result_sha256=(
                hashlib.sha256(b"corrected-payload").hexdigest()
                if disposition is Disposition.CORRECT_AND_ACCEPT
                else None
            ),
        )
        for proposal in store.semantic_proposals_for_run(A, run_id)
    )


@pytest.mark.parametrize(
    ("state", "current_sha256", "changed"),
    [
        (GoodNotesSourceLiveness.MISSING, None, None),
        (GoodNotesSourceLiveness.STALE, None, None),
        (GoodNotesSourceLiveness.REAPPEARED, "current", True),
    ],
)
def test_liveness_refusal_happens_before_ingestion(
    state: GoodNotesSourceLiveness,
    current_sha256: str | None,
    changed: bool | None,
) -> None:
    pdf = vector_pdf((COVER,))
    request = _request(pdf, f"liveness-{state.value.lower()}")
    receipt = replace(
        request.liveness,
        state=state,
        current_sha256=_sha(pdf) if current_sha256 is not None else None,
        reappeared_content_changed=changed,
    )
    store = MemoryDurableNoteStore()
    with pytest.raises(ValueError, match="not available"):
        _orchestrator("observe-only").run(
            replace(request, liveness=receipt),
            renderer=production_page_renderer(),
            splitter=split_admitted_pdf,
            store=store,
            clock=lambda: WHEN,
        )
    assert store.runs == {}


def test_stale_available_receipt_is_refused_and_acknowledged_reappearance_proceeds() -> None:
    pdf = vector_pdf((COVER,))
    request = _request(pdf, "liveness-age")
    stale = replace(request.liveness, checked_at=WHEN - timedelta(seconds=301))
    store = MemoryDurableNoteStore()
    with pytest.raises(ValueError, match="receipt is stale"):
        _orchestrator("observe-only").run(
            replace(request, liveness=stale),
            renderer=production_page_renderer(),
            splitter=split_admitted_pdf,
            store=store,
            clock=lambda: WHEN,
        )
    acknowledged = replace(request.liveness, prior_sha256="0" * 64)
    result = _orchestrator("observe-only").run(
        replace(request, liveness=acknowledged),
        renderer=production_page_renderer(),
        splitter=split_admitted_pdf,
        store=store,
        clock=lambda: WHEN,
    )
    assert result.run.status is GoodNotesIngestionStatus.RUNNING


@pytest.mark.parametrize(
    "disposition",
    [Disposition.REJECT, Disposition.DEFER, Disposition.INVALIDATE, Disposition.REPROCESS],
)
def test_nonpromoting_review_dispositions_refuse_canonical_promotion(
    disposition: Disposition,
) -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    request = _request(pdf, f"review-{disposition.value}")
    first = _orchestrator().run(
        request,
        renderer=production_page_renderer(),
        splitter=split_admitted_pdf,
        store=store,
        clock=lambda: WHEN,
    )
    _propose(store, first.run.run_id)
    with pytest.raises(DurableNoteStageError) as raised:
        _orchestrator().run(
            request,
            renderer=production_page_renderer(),
            splitter=split_admitted_pdf,
            store=store,
            clock=lambda: WHEN,
            promotion_evidence=_promotion_evidence(store, first.run.run_id, disposition),
        )
    assert "not eligible" in str(raised.value.__cause__)
    assert store._notes == {}


@pytest.mark.parametrize("evidence", [None, Disposition.CORRECT_AND_ACCEPT])
def test_canonical_promotion_requires_evidence_and_accepts_corrected_review(
    evidence: Disposition | None,
) -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    request = _request(pdf, f"review-{evidence or 'absent'}")
    first = _orchestrator().run(
        request,
        renderer=production_page_renderer(),
        splitter=split_admitted_pdf,
        store=store,
        clock=lambda: WHEN,
    )
    _propose(store, first.run.run_id)
    kwargs = (
        {}
        if evidence is None
        else {"promotion_evidence": _promotion_evidence(store, first.run.run_id, evidence)}
    )
    if evidence is None:
        with pytest.raises(DurableNoteStageError) as raised:
            _orchestrator().run(
                request,
                renderer=production_page_renderer(),
                splitter=split_admitted_pdf,
                store=store,
                clock=lambda: WHEN,
                **kwargs,
            )
        assert "lacks server review evidence" in str(raised.value.__cause__)
        assert store._notes == {}
    else:
        result = _orchestrator().run(
            request,
            renderer=production_page_renderer(),
            splitter=split_admitted_pdf,
            store=store,
            clock=lambda: WHEN,
            **kwargs,
        )
        assert result.run.status is GoodNotesIngestionStatus.SUCCEEDED
        assert store._notes


@pytest.mark.parametrize("mutation", ["principal", "run", "digest", "duplicate"])
def test_promotion_evidence_is_context_bound_and_unique(mutation: str) -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    request = _request(pdf, f"review-binding-{mutation}")
    first = _orchestrator().run(
        request,
        renderer=production_page_renderer(),
        splitter=split_admitted_pdf,
        store=store,
        clock=lambda: WHEN,
    )
    _propose(store, first.run.run_id)
    item = _promotion_evidence(store, first.run.run_id)[0]
    if mutation == "principal":
        evidence = (replace(item, principal_id="prn_bbbbbbbbbbbbbbbbbbbbbbbb"),)
    elif mutation == "run":
        evidence = (replace(item, run_id=issue_stable_id("gnrun", A, "other")),)
    elif mutation == "digest":
        evidence = (replace(item, proposal_sha256="0" * 64),)
    else:
        evidence = (item, item)
    with pytest.raises(DurableNoteStageError):
        _orchestrator().run(
            request,
            renderer=production_page_renderer(),
            splitter=split_admitted_pdf,
            store=store,
            clock=lambda: WHEN,
            promotion_evidence=evidence,
        )
    assert store._notes == {}


def test_lineage_alone_is_not_terminal_success() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    result = _orchestrator(SEMANTIC).run(
        _request(pdf, "durable-lineage-only"),
        renderer=production_page_renderer(),
        splitter=split_admitted_pdf,
        store=store,
        clock=lambda: WHEN,
    )
    assert result.run.status is GoodNotesIngestionStatus.RUNNING
    assert result.waiting_for_proposal is True
    assert result.run.status is not GoodNotesIngestionStatus.SUCCEEDED
    stages = {row.stage for row in result.stages if row.status.value == "SUCCEEDED"}
    assert GoodNotesPipelineStage.LINEAGE in stages
    assert GoodNotesPipelineStage.PREVIEW not in stages


def test_admitted_vector_pdf_reaches_preview_only_after_proposal() -> None:
    pdf = vector_pdf((COVER, BODY))
    store = MemoryDurableNoteStore()
    orchestrator = _orchestrator()
    first = orchestrator.run(
        _request(pdf, "durable-e2e"),
        renderer=production_page_renderer(),
        splitter=split_admitted_pdf,
        store=store,
        clock=lambda: WHEN,
    )
    assert first.run.status is not GoodNotesIngestionStatus.SUCCEEDED
    assert first.waiting_for_proposal is True
    _propose(store, first.run.run_id)
    finished = orchestrator.run(
        _request(pdf, "durable-e2e"),
        renderer=production_page_renderer(),
        splitter=split_admitted_pdf,
        store=store,
        clock=lambda: WHEN,
        promotion_evidence=_promotion_evidence(store, first.run.run_id),
    )
    assert finished.run.status is GoodNotesIngestionStatus.SUCCEEDED
    assert finished.waiting_for_proposal is False
    assert finished.preview_receipt_id is not None
    assert finished.preview_receipt_id.startswith("gndlv_")
    notes = [item for item in store._notes.values() if item.principal_id == A]
    assert notes


@pytest.mark.parametrize(
    "fail_after",
    [
        GoodNotesPipelineStage.LINEAGE,
        GoodNotesPipelineStage.WAITING_PROPOSAL,
        GoodNotesPipelineStage.RECONCILE,
    ],
)
def test_injected_failure_is_not_terminal_success_and_resume_does_not_duplicate(
    fail_after: GoodNotesPipelineStage,
) -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    orchestrator = _orchestrator()
    request = _request(pdf, f"durable-fail-{fail_after.value}")
    if fail_after is GoodNotesPipelineStage.RECONCILE:
        waiting = orchestrator.run(
            request,
            renderer=production_page_renderer(),
            splitter=split_admitted_pdf,
            store=store,
            clock=lambda: WHEN,
        )
        _propose(store, waiting.run.run_id)
    with pytest.raises(DurableNoteStageError) as raised:
        orchestrator.run(
            request,
            renderer=production_page_renderer(),
            splitter=split_admitted_pdf,
            store=store,
            clock=lambda: WHEN,
            fail_after=fail_after,
            promotion_evidence=_promotion_evidence(store, waiting.run.run_id)
            if fail_after is GoodNotesPipelineStage.RECONCILE
            else (),
        )
    assert raised.value.stage is fail_after
    run = store.run(A, raised.value.run_id)
    assert run is not None
    assert run.status is not GoodNotesIngestionStatus.SUCCEEDED
    if fail_after is not GoodNotesPipelineStage.RECONCILE:
        _propose(store, raised.value.run_id)
    resumed = orchestrator.run(
        request,
        renderer=production_page_renderer(),
        splitter=split_admitted_pdf,
        store=store,
        clock=lambda: WHEN,
        promotion_evidence=_promotion_evidence(store, raised.value.run_id),
    )
    assert resumed.run.status is GoodNotesIngestionStatus.SUCCEEDED
    notes = [item for item in store._notes.values() if item.principal_id == A]
    assert len(notes) == 1
    changes = store.run_note_changes(A, resumed.run.run_id)
    assert len(changes) == 1


def test_run_ids_are_the_existing_ingestion_namespace() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    result = _orchestrator("observe-only").run(
        _request(pdf, "durable-namespace"),
        renderer=production_page_renderer(),
        splitter=split_admitted_pdf,
        store=store,
        clock=lambda: WHEN,
    )
    assert result.run.run_id == issue_stable_id("gnrun", A, "durable-namespace")
    assert result.run.run_id.startswith("gnrun_")
    assert result.rollout_stage == "observe-only"


def _run(
    store: MemoryDurableNoteStore,
    pdf: bytes,
    request_id: str,
    stage: str,
    *,
    splitter: Callable[[bytes], tuple[bytes, ...]] = split_admitted_pdf,
) -> DurableNoteResult:
    request = _request(pdf, request_id)
    existing = store.run_by_request(A, request_id)
    return _orchestrator(stage).run(
        request,
        renderer=production_page_renderer(),
        splitter=splitter,
        store=store,
        clock=lambda: WHEN,
        promotion_evidence=() if existing is None else _promotion_evidence(store, existing.run_id),
    )


def test_observe_only_does_not_split_render_or_persist_lineage() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    calls: list[bytes] = []

    def splitter(payload: bytes) -> tuple[bytes, ...]:
        calls.append(payload)
        return split_admitted_pdf(payload)

    result = _run(store, pdf, "stage-observe", "observe-only", splitter=splitter)
    assert result.rollout_stage == "observe-only"
    assert calls == []
    assert result.waiting_for_proposal is False
    assert result.preview_receipt_id is None
    assert result.run.status is not GoodNotesIngestionStatus.SUCCEEDED
    stages = _succeeded(result)
    assert GoodNotesPipelineStage.OBSERVE in stages
    assert GoodNotesPipelineStage.SETTLE in stages
    assert GoodNotesPipelineStage.SPLIT_RENDER not in stages
    assert GoodNotesPipelineStage.LINEAGE not in stages
    assert store.snapshots_for_run(A, result.run.run_id) == ()
    assert _notes(store) == []
    assert store._attempts == []


def test_page_identity_dry_run_stops_before_semantic_proposals() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    result = _run(store, pdf, "stage-dry-run", DRY_RUN)
    assert result.rollout_stage == DRY_RUN
    stages = _succeeded(result)
    assert GoodNotesPipelineStage.LINEAGE in stages
    assert GoodNotesPipelineStage.CONTENT_READY not in stages
    assert GoodNotesPipelineStage.WAITING_PROPOSAL not in stages
    assert result.waiting_for_proposal is False
    assert result.preview_receipt_id is None
    assert _notes(store) == []
    assert store.snapshots_for_run(A, result.run.run_id)


def test_semantic_proposals_do_not_write_canonical_notes() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    first = _run(store, pdf, "stage-semantic", SEMANTIC)
    assert first.waiting_for_proposal is True
    _propose(store, first.run.run_id)
    second = _run(store, pdf, "stage-semantic", SEMANTIC)
    assert second.rollout_stage == SEMANTIC
    assert second.waiting_for_proposal is False
    assert second.preview_receipt_id is None
    stages = _succeeded(second)
    assert GoodNotesPipelineStage.CONTENT_READY in stages
    assert GoodNotesPipelineStage.RECONCILE not in stages
    assert _notes(store) == []


def test_canonical_writes_do_not_preview_or_deliver() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    first = _run(store, pdf, "stage-canonical", CANONICAL)
    _propose(store, first.run.run_id)
    second = _run(store, pdf, "stage-canonical", CANONICAL)
    assert second.rollout_stage == CANONICAL
    stages = _succeeded(second)
    assert GoodNotesPipelineStage.RECONCILE in stages
    assert GoodNotesPipelineStage.PREVIEW not in stages
    assert second.preview_receipt_id is None
    assert second.run.status is not GoodNotesIngestionStatus.SUCCEEDED
    assert _notes(store)
    assert store._attempts == []


def test_new_only_preview_does_not_record_attempt_windows() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    first = _run(store, pdf, "stage-preview", PREVIEW)
    _propose(store, first.run.run_id)
    second = _run(store, pdf, "stage-preview", PREVIEW)
    assert second.rollout_stage == PREVIEW
    assert second.preview_receipt_id is not None
    assert second.run.status is GoodNotesIngestionStatus.SUCCEEDED
    assert store._attempts == []
    composed = _compose(GoodNotesRolloutStage.NEW_ONLY_SUMMARY_PREVIEW)
    assert composed._rollout_stage == PREVIEW


def test_delivery_canary_records_dormant_attempts_without_send() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    first = _run(store, pdf, "stage-canary", CANARY)
    _propose(store, first.run.run_id)
    second = _run(store, pdf, "stage-canary", CANARY)
    assert second.rollout_stage == CANARY
    assert second.preview_receipt_id is not None
    states = {item.state for item in store._attempts}
    assert GoodNotesDeliveryAttemptState.PREPARED in states
    assert GoodNotesDeliveryAttemptState.ACKNOWLEDGED in states
    assert GoodNotesDeliveryAttemptState.SENT not in states


def test_bounded_scheduled_matches_canary_effects_and_is_distinct() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    first = _run(store, pdf, "stage-scheduled", SCHEDULED)
    _propose(store, first.run.run_id)
    second = _run(store, pdf, "stage-scheduled", SCHEDULED)
    assert second.rollout_stage == SCHEDULED
    assert second.preview_receipt_id is not None
    states = {item.state for item in store._attempts}
    assert GoodNotesDeliveryAttemptState.PREPARED in states
    assert GoodNotesDeliveryAttemptState.SENT not in states
    assert second.rollout_stage != CANARY


def test_optional_tbr_bridge_fails_closed_without_side_effects() -> None:
    with pytest.raises(RolloutGateError, match="unauthorized"):
        GoodNotesDurableNoteOrchestrator(rollout_stage="optional-tbr-bridge")
    with pytest.raises(RolloutGateError, match="unknown"):
        GoodNotesDurableNoteOrchestrator(rollout_stage="production")
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    result = _run(store, pdf, "stage-observe-control", "observe-only")
    assert store.snapshots_for_run(A, result.run.run_id) == ()
    assert _notes(store) == []


def test_later_effect_cannot_run_at_an_earlier_stage() -> None:
    pdf = vector_pdf((COVER, BODY))
    store = MemoryDurableNoteStore()
    dry = _run(store, pdf, "no-later-at-dry-run", DRY_RUN)
    _propose(store, dry.run.run_id)
    again = _run(store, pdf, "no-later-at-dry-run", DRY_RUN)
    assert _succeeded(again) == _succeeded(dry)
    assert GoodNotesPipelineStage.RECONCILE not in _succeeded(again)
    assert again.preview_receipt_id is None
    assert _notes(store) == []
    assert store._attempts == []


class _SpyLineage(GoodNotesLineageService):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def reconcile(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        return super().reconcile(*args, **kwargs)  # type: ignore[arg-type]


class _BoomDelivery(GoodNotesNewOnlyDelivery):
    def deliver(self, *args: object, **kwargs: object) -> object:
        raise ValueError("injected local receipt failure")


class _Clock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self) -> None:
        self.current = self.current + timedelta(minutes=5)


def _run_at(
    store: MemoryDurableNoteStore,
    request: DurableNoteRequest,
    stage: str,
    *,
    lineage: GoodNotesLineageService | None = None,
    delivery: GoodNotesNewOnlyDelivery | None = None,
    renderer: object | None = None,
    clock: Callable[[], datetime] | None = None,
) -> DurableNoteResult:
    existing = store.run_by_request(request.principal_id, request.request_id)
    return GoodNotesDurableNoteOrchestrator(
        lineage=lineage,
        delivery=delivery,
        rollout_stage=stage,
    ).run(
        request,
        renderer=renderer or production_page_renderer(),  # type: ignore[arg-type]
        splitter=split_admitted_pdf,
        store=store,
        clock=clock or (lambda: WHEN),
        promotion_evidence=() if existing is None else _promotion_evidence(store, existing.run_id),
    )


def test_t1_completed_lineage_is_not_re_executed() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    spy = _SpyLineage()
    request = _request(pdf, "t1-skip-lineage")
    first = _run_at(store, request, PREVIEW, lineage=spy)
    assert spy.calls == 1
    _propose(store, first.run.run_id)
    second = _run_at(store, request, PREVIEW, lineage=spy)
    assert second.run.status is GoodNotesIngestionStatus.SUCCEEDED
    assert spy.calls == 1


def test_ingestion_fingerprint_is_the_orchestrator_contract() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    request = _request(pdf, "fingerprint-contract")
    renderer = production_page_renderer()
    result = _run_at(store, request, DRY_RUN, renderer=renderer)
    assert result.run.request_fingerprint == ingestion_request_fingerprint(
        principal_id=request.principal_id,
        source_root_id=request.source_root_id,
        source_object_id=request.source_object_id,
        observation_sha256=request.observation.sha256,
        renderer=renderer,
    )


@pytest.mark.parametrize(
    "mutate",
    [
        "source_object_id",
        "source_id",
        "source_version_id",
        "observation_digest",
        "representation_media_type",
        "renderer",
        "principal",
    ],
)
def test_t2_bound_identity_rejects_before_prepared(mutate: str) -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    request = _request(pdf, f"t2-{mutate}")
    first = _run(store, pdf, request.request_id, PREVIEW)
    run_id = first.run.run_id
    before = store.run(A, run_id)
    assert before is not None
    before_status = before.status
    before_ended = before.ended_at
    before_stages = store.stages(A, run_id)
    renderer: object = production_page_renderer()
    changed = request
    if mutate == "source_object_id":
        changed = replace(request, source_object_id="obj_bbbbbbbbbbbbbbbbbbbbbbbb")
    elif mutate == "source_id":
        changed = replace(request, source_id="src_bbbbbbbbbbbbbbbbbbbbbbbb")
    elif mutate == "source_version_id":
        changed = replace(request, source_version_id="ver_bbbbbbbbbbbbbbbbbbbbbbbb")
    elif mutate == "observation_digest":
        other_pdf = vector_pdf((BODY,))
        changed = replace(
            request,
            pdf_bytes=other_pdf,
            observation=replace(
                request.observation,
                sha256=_sha(other_pdf),
                size_bytes=len(other_pdf),
                page_count=len(split_admitted_pdf(other_pdf)),
            ),
            liveness=replace(request.liveness, current_sha256=_sha(other_pdf)),
        )
    elif mutate == "representation_media_type":
        changed = replace(request, representation_media_type="image/jpeg")
    elif mutate == "renderer":

        class _OtherRenderer:
            name = "other-renderer"
            version = production_page_renderer().version
            profile_version = production_page_renderer().profile_version

            def render_png(self, page_bytes: bytes) -> object:
                return production_page_renderer().render_png(page_bytes)

            def render(self, page_bytes: bytes) -> object:
                return production_page_renderer().render(page_bytes)

        renderer = _OtherRenderer()
    elif mutate == "principal":
        changed = replace(request, principal_id="prn_bbbbbbbbbbbbbbbbbbbbbbbb")
    if mutate == "principal":
        _run_at(store, changed, CANARY, renderer=renderer)
    else:
        with pytest.raises(DurableNoteContinuationError):
            _run_at(store, changed, CANARY, renderer=renderer)
    held = store.run(A, run_id)
    assert held is not None
    assert held.status is before_status
    assert held.ended_at == before_ended
    assert store.stages(A, run_id) == before_stages
    assert store._attempts == []
    assert store.delivery_receipts_for_run(A, run_id) == ()
    assert len(_notes(store)) == 0


def test_t2_path_and_mtime_are_observation_only() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    request = _request(pdf, "t2-mtime-path")
    first = _run(store, pdf, request.request_id, PREVIEW)
    _propose(store, first.run.run_id)
    changed = replace(
        request,
        observation=replace(
            request.observation,
            relative_path="Notebooks/moved.goodnotes",
            mtime_ns=99,
        ),
        liveness=replace(request.liveness, relative_path="Notebooks/moved.goodnotes"),
        label="moved",
    )
    finished = _run_at(store, changed, PREVIEW)
    assert finished.run.status is GoodNotesIngestionStatus.SUCCEEDED


def test_t3_t4_t7_t8_t9_preview_then_canary_replays_receipt() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    clock = _Clock(WHEN)
    request = _request(pdf, "t3-happy")
    report_before = rollout_report(
        Settings(database_url=DSN, goodnotes_rollout_stage=GoodNotesRolloutStage.OBSERVE_ONLY)
    )
    first = _run_at(store, request, PREVIEW, clock=clock)
    _propose(store, first.run.run_id)
    previewed = _run_at(store, request, PREVIEW, clock=clock)
    assert previewed.run.status is GoodNotesIngestionStatus.SUCCEEDED
    ended = previewed.run.ended_at
    receipt_id = previewed.preview_receipt_id
    assert receipt_id is not None
    assert store._attempts == []
    clock.advance()
    canary = _run_at(store, request, CANARY, clock=clock)
    assert canary.preview_receipt_id == receipt_id
    receipts = store.delivery_receipts_for_run(A, canary.run.run_id)
    assert len(receipts) == 1
    states = {item.state for item in store._attempts}
    assert states == {
        GoodNotesDeliveryAttemptState.PREPARED,
        GoodNotesDeliveryAttemptState.ACKNOWLEDGED,
    }
    assert GoodNotesDeliveryAttemptState.SENT not in states
    held = store.run(A, canary.run.run_id)
    assert held is not None
    assert held.status is GoodNotesIngestionStatus.SUCCEEDED
    assert held.ended_at == ended
    assert GoodNotesPipelineStage.PREVIEW in _succeeded(canary)
    assert len(_notes(store)) == 1
    report_after = rollout_report(
        Settings(database_url=DSN, goodnotes_rollout_stage=GoodNotesRolloutStage.OBSERVE_ONLY)
    )
    assert report_after == report_before
    assert report_after["current_stage"] == "observe-only"


def test_completed_preview_survives_later_correction_and_occurrence_retirement() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    request = _request(pdf, "preview-historical-receipt")
    first = _run(store, pdf, request.request_id, PREVIEW)
    _propose(store, first.run.run_id)
    previewed = _run_at(store, request, PREVIEW)
    receipt_id = previewed.preview_receipt_id
    ended_at = previewed.run.ended_at
    assert receipt_id is not None

    occurrence_key, occurrence = next(iter(store._occurrences.items()))
    store._occurrences[occurrence_key] = replace(
        occurrence,
        identity_status=GoodNotesIdentityStatus.RETIRED,
    )
    bound = store.latest_revision_for_occurrence(A, occurrence.occurrence_id)
    assert bound is not None
    store.store_revision(
        replace(
            bound,
            revision_id=issue_stable_id("gnrev", "post-preview-correction"),
            transcription="synthetic corrected later",
            created_at=WHEN + timedelta(seconds=1),
            supersedes_revision_id=bound.revision_id,
        )
    )

    recovered = _run_at(store, request, CANARY)
    assert recovered.preview_receipt_id == receipt_id
    assert recovered.run.status is GoodNotesIngestionStatus.SUCCEEDED
    assert recovered.run.ended_at == ended_at
    receipts = store.delivery_receipts_for_run(A, recovered.run.run_id)
    assert len(receipts) == 1
    assert receipts[0].receipt_id == receipt_id


def test_t5_t6_canary_failure_after_prepared_preserves_terminal_state() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    request = _request(pdf, "t5-canary-fail")
    first = _run(store, pdf, request.request_id, PREVIEW)
    _propose(store, first.run.run_id)
    previewed = _run_at(store, request, PREVIEW)
    ended = previewed.run.ended_at
    receipt_id = previewed.preview_receipt_id
    notes = list(_notes(store))
    with pytest.raises(DurableNoteStageError):
        _run_at(store, request, CANARY, delivery=_BoomDelivery())
    held = store.run(A, previewed.run.run_id)
    assert held is not None
    assert held.status is GoodNotesIngestionStatus.SUCCEEDED
    assert held.ended_at == ended
    preview_row = [
        row for row in store.stages(A, held.run_id) if row.stage is GoodNotesPipelineStage.PREVIEW
    ][-1]
    assert preview_row.status is GoodNotesStageStatus.SUCCEEDED
    states = [item.state for item in store._attempts]
    assert states.count(GoodNotesDeliveryAttemptState.PREPARED) == 1
    assert states.count(GoodNotesDeliveryAttemptState.FAILED) == 1
    assert GoodNotesDeliveryAttemptState.ACKNOWLEDGED not in states
    assert GoodNotesDeliveryAttemptState.SENT not in states
    assert store.delivery_receipts_for_run(A, held.run_id)[0].receipt_id == receipt_id
    assert _notes(store) == notes


def test_t10_orchestrator_tests_are_synthetic() -> None:
    assert _segment()["transcription"] == "synthetic note"
    pdf = vector_pdf((COVER,))
    request = _request(pdf, "t10-synthetic")
    assert "Inbox" not in request.observation.relative_path
    assert request.request_id == "t10-synthetic"


@pytest.mark.parametrize(
    "forged",
    [
        GoodNotesPipelineStage.LINEAGE,
        GoodNotesPipelineStage.CONTENT_READY,
        GoodNotesPipelineStage.RECONCILE,
        GoodNotesPipelineStage.PREVIEW,
    ],
)
def test_t11_inconsistent_completed_prefix_fails_closed(forged: GoodNotesPipelineStage) -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    first = _run(store, pdf, f"t11-prefix-{forged.value}", "observe-only")
    store.record_stage(
        GoodNotesRunStage(
            principal_id=A,
            run_id=first.run.run_id,
            stage=forged,
            status=GoodNotesStageStatus.SUCCEEDED,
            started_at=WHEN,
            attempt=1,
            ended_at=WHEN,
        )
    )
    with pytest.raises(DurableNoteContinuationError):
        _run(store, pdf, f"t11-prefix-{forged.value}", PREVIEW)
    stages = {row.stage for row in store.stages(A, first.run.run_id)}
    assert GoodNotesPipelineStage.SPLIT_RENDER not in stages
    assert store._attempts == []


def test_t11_reconcile_without_content_ready_fails_closed() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    first = _run(store, pdf, "t11-reconcile-gap", DRY_RUN)
    store.record_stage(
        GoodNotesRunStage(
            principal_id=A,
            run_id=first.run.run_id,
            stage=GoodNotesPipelineStage.RECONCILE,
            status=GoodNotesStageStatus.SUCCEEDED,
            started_at=WHEN,
            attempt=1,
            ended_at=WHEN,
        )
    )
    with pytest.raises(DurableNoteContinuationError):
        _run(store, pdf, "t11-reconcile-gap", PREVIEW)
    assert GoodNotesPipelineStage.CONTENT_READY not in {
        row.stage for row in store.stages(A, first.run.run_id)
    }
    assert store._attempts == []


def test_t12_missing_lineage_evidence_fails_closed_missing_raster_does_not() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    _run(store, pdf, "t12-missing-snapshot", DRY_RUN)
    store._snapshots.clear()
    with pytest.raises(DurableNoteContinuationError):
        _run(store, pdf, "t12-missing-snapshot", DRY_RUN)
    store = MemoryDurableNoteStore()
    _run(store, pdf, "t12-missing-positions", DRY_RUN)
    store._positions.clear()
    with pytest.raises(DurableNoteContinuationError):
        _run(store, pdf, "t12-missing-positions", DRY_RUN)
    store = MemoryDurableNoteStore()
    _run(store, pdf, "t12-missing-raster-ok", DRY_RUN)
    store._rasters.clear()
    resumed = _run(store, pdf, "t12-missing-raster-ok", DRY_RUN)
    assert GoodNotesPipelineStage.LINEAGE in _succeeded(resumed)
    assert store._rasters


def test_t13_corrupt_reconcile_evidence_fails_closed() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    request = _request(pdf, "t13-corrupt")
    first = _run(store, pdf, request.request_id, PREVIEW)
    _propose(store, first.run.run_id)
    reconciled = _run_at(store, request, CANONICAL)
    assert GoodNotesPipelineStage.RECONCILE in _succeeded(reconciled)
    changes = store.run_note_changes(A, reconciled.run.run_id)
    assert changes
    store._revisions.clear()
    with pytest.raises(DurableNoteContinuationError):
        _run_at(store, request, PREVIEW)
    assert store.delivery_receipts_for_run(A, reconciled.run.run_id) == ()
    assert store._attempts == []


def test_t14_inconsistent_and_abnormal_preview_fail_closed() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    request = _request(pdf, "t14-missing-receipt")
    first = _run(store, pdf, request.request_id, PREVIEW)
    _propose(store, first.run.run_id)
    previewed = _run_at(store, request, PREVIEW)
    ended = previewed.run.ended_at
    store._receipts.clear()
    with pytest.raises(DurableNoteContinuationError):
        _run_at(store, request, CANARY)
    held = store.run(A, previewed.run.run_id)
    assert held is not None
    assert held.status is GoodNotesIngestionStatus.SUCCEEDED
    assert held.ended_at == ended
    assert store._attempts == []

    store = MemoryDurableNoteStore()
    request = _request(pdf, "t14-abnormal")
    first = _run(store, pdf, request.request_id, PREVIEW)
    _propose(store, first.run.run_id)
    previewed = _run_at(store, request, PREVIEW)
    store.record_stage(
        GoodNotesRunStage(
            principal_id=A,
            run_id=previewed.run.run_id,
            stage=GoodNotesPipelineStage.PREVIEW,
            status=GoodNotesStageStatus.FAILED,
            started_at=WHEN,
            attempt=1,
            ended_at=WHEN,
            error_code="STAGE_FAILED",
            error_class="ValueError",
        )
    )
    with pytest.raises(DurableNoteContinuationError):
        _run_at(store, request, CANARY)
    assert store._attempts == []
    preview_row = [
        row
        for row in store.stages(A, previewed.run.run_id)
        if row.stage is GoodNotesPipelineStage.PREVIEW
    ][-1]
    assert preview_row.status is GoodNotesStageStatus.FAILED
    assert store.delivery_receipts_for_run(A, previewed.run.run_id)


def test_t15_post_lineage_crash_recovers_rasters_without_rerunning_lineage() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    spy = _SpyLineage()
    request = _request(pdf, "t15-lineage-crash")
    with pytest.raises(DurableNoteStageError) as raised:
        GoodNotesDurableNoteOrchestrator(lineage=spy, rollout_stage=PREVIEW).run(
            request,
            renderer=production_page_renderer(),
            splitter=split_admitted_pdf,
            store=store,
            clock=lambda: WHEN,
            fail_after=GoodNotesPipelineStage.LINEAGE,
        )
    assert spy.calls == 1
    assert store._rasters == {}
    snapshots = store.snapshots_for_run(A, raised.value.run_id)
    assert snapshots
    positions = store.page_positions(A, snapshots[0].snapshot_id)
    logical = {item.logical_page_id for item in positions}
    _propose(store, raised.value.run_id)
    resumed = _run_at(store, request, PREVIEW, lineage=spy)
    assert spy.calls == 1
    assert resumed.run.status is GoodNotesIngestionStatus.SUCCEEDED
    assert store._rasters
    later = store.page_positions(A, snapshots[0].snapshot_id)
    assert {item.logical_page_id for item in later} == logical


def test_t16_failed_run_mismatch_causes_zero_mutation() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    request = _request(pdf, "t16-failed")
    first = _run(store, pdf, request.request_id, PREVIEW)
    failed = store.update_run(
        replace(
            first.run,
            status=GoodNotesIngestionStatus.FAILED,
            ended_at=WHEN,
            error_code="STAGE_FAILED",
            error_class="ValueError",
        )
    )
    before_stages = store.stages(A, failed.run_id)
    before_notes = dict(store._notes)
    changed = replace(request, source_object_id="obj_bbbbbbbbbbbbbbbbbbbbbbbb")
    with pytest.raises(DurableNoteContinuationError):
        _run_at(store, changed, CANARY)
    held = store.run(A, failed.run_id)
    assert held is not None
    assert held.status is GoodNotesIngestionStatus.FAILED
    assert held.ended_at == WHEN
    assert held.error_code == "STAGE_FAILED"
    assert held.error_class == "ValueError"
    assert store.stages(A, failed.run_id) == before_stages
    assert store._attempts == []
    assert store.delivery_receipts_for_run(A, failed.run_id) == ()
    assert store._notes == before_notes


def test_t17_zero_change_reconcile_is_valid_and_canary_replays_suppressed_receipt() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    request = _request(pdf, "t17-zero-change")
    first = _run(store, pdf, request.request_id, PREVIEW)
    _propose_source_context(store, first.run.run_id)
    previewed = _run_at(store, request, PREVIEW)
    assert GoodNotesPipelineStage.RECONCILE in _succeeded(previewed)
    assert store.run_note_changes(A, previewed.run.run_id) == ()
    receipts = store.delivery_receipts_for_run(A, previewed.run.run_id)
    assert len(receipts) == 1
    assert receipts[0].suppressed is True
    canary = _run_at(store, request, CANARY)
    assert canary.preview_receipt_id == receipts[0].receipt_id
    assert len(store.delivery_receipts_for_run(A, previewed.run.run_id)) == 1
    states = {item.state for item in store._attempts}
    assert GoodNotesDeliveryAttemptState.PREPARED in states
    assert GoodNotesDeliveryAttemptState.ACKNOWLEDGED in states
    assert GoodNotesDeliveryAttemptState.SENT not in states


def test_t17_completed_reconcile_without_proposal_fails_closed() -> None:
    pdf = vector_pdf((COVER,))
    store = MemoryDurableNoteStore()
    first = _run(store, pdf, "t17-missing-proposal", PREVIEW)
    store.record_stage(
        GoodNotesRunStage(
            principal_id=A,
            run_id=first.run.run_id,
            stage=GoodNotesPipelineStage.RECONCILE,
            status=GoodNotesStageStatus.SUCCEEDED,
            started_at=WHEN,
            attempt=1,
            ended_at=WHEN,
        )
    )
    with pytest.raises(DurableNoteContinuationError):
        _run(store, pdf, "t17-missing-proposal", PREVIEW)
    assert store.delivery_receipts_for_run(A, first.run.run_id) == ()
    assert store._attempts == []
