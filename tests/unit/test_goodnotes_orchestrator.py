"""Repository-side durable-note pipeline: lineage is not terminal success."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from my_pa.application.goodnotes_lineage import ObservedNotebookFile
from my_pa.application.goodnotes_orchestrator import (
    DurableNoteRequest,
    DurableNoteResult,
    DurableNoteStageError,
    GoodNotesDurableNoteOrchestrator,
    RolloutGateError,
)
from my_pa.bootstrap.goodnotes_durable_note import compose_durable_note_orchestrator
from my_pa.bootstrap.settings import GoodNotesRolloutStage, Settings
from my_pa.domain.goodnotes.models import (
    GoodNotesDeliveryAttemptState,
    GoodNotesIngestionStatus,
    GoodNotesPipelineStage,
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
    return _orchestrator(stage).run(
        _request(pdf, request_id),
        renderer=production_page_renderer(),
        splitter=splitter,
        store=store,
        clock=lambda: WHEN,
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
