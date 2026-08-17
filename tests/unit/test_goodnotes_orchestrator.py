"""Repository-side durable-note pipeline: lineage is not terminal success."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from my_pa.application.goodnotes_lineage import ObservedNotebookFile
from my_pa.application.goodnotes_orchestrator import (
    DurableNoteRequest,
    DurableNoteStageError,
    GoodNotesDurableNoteOrchestrator,
)
from my_pa.domain.goodnotes.models import (
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
    result = GoodNotesDurableNoteOrchestrator().run(
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
    orchestrator = GoodNotesDurableNoteOrchestrator()
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
    orchestrator = GoodNotesDurableNoteOrchestrator()
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
    result = GoodNotesDurableNoteOrchestrator().run(
        _request(pdf, "durable-namespace"),
        renderer=production_page_renderer(),
        splitter=split_admitted_pdf,
        store=store,
        clock=lambda: WHEN,
    )
    assert result.run.run_id == issue_stable_id("gnrun", A, "durable-namespace")
    assert result.run.run_id.startswith("gnrun_")
