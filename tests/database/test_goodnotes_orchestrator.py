"""Disposable PostgreSQL proof for the durable-note orchestrator store."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.sql import Executable

from my_pa.application.goodnotes_lineage import ObservedNotebookFile
from my_pa.application.goodnotes_occurrences import (
    semantic_proposal_sha256,
)
from my_pa.application.goodnotes_orchestrator import (
    DurableNoteRequest,
    DurableNoteResult,
    DurableNoteStageError,
    GoodNotesDurableNoteOrchestrator,
)
from my_pa.contracts.ports import GoodNotesSemanticReviewDecisionRecord
from my_pa.domain.goodnotes.liveness import (
    GoodNotesSourceLiveness,
    GoodNotesSourceLivenessReceipt,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesIngestionStatus,
    GoodNotesPipelineStage,
    GoodNotesStageStatus,
    issue_stable_id,
)
from my_pa.infrastructure.goodnotes.pdf import split_admitted_pdf
from my_pa.infrastructure.goodnotes.render import production_page_renderer
from my_pa.infrastructure.persistence.goodnotes_durable_note import PostgresDurableNoteStore
from my_pa.infrastructure.persistence.goodnotes_pull import SqlGoodNotesPullRepository
from my_pa.infrastructure.persistence.goodnotes_semantics import SqlGoodNotesSemanticRepository
from my_pa.infrastructure.persistence.tables import goodnotes_semantic_proposals
from tests.unit.vector_pdf import Rect, vector_pdf

pytestmark = pytest.mark.database
ROOT = Path(__file__).resolve().parents[2]
DATABASE = "my_pa_goodnotes_orchestrator_test"
WHEN = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
B = "prn_bbbbbbbbbbbbbbbbbbbbbbbb"
SOURCE = "src_aaaaaaaaaaaaaaaaaaaaaaaa"
ROOT_ID = "icloud-goodnotes"
COVER = (Rect(72, 400, 220, 220, 0.15),)
BODY = (Rect(80, 80, 420, 520, 0.45),)


def administer(engine: Engine, *statements: Executable) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _object_id(token: str) -> str:
    return "obj_" + hashlib.sha256(f"object:{token}".encode()).hexdigest()[:24]


def _version_id(token: str) -> str:
    return "ver_" + hashlib.sha256(f"version:{token}".encode()).hexdigest()[:24]


def _request(pdf: bytes, request_id: str) -> DurableNoteRequest:
    return DurableNoteRequest(
        principal_id=A,
        request_id=request_id,
        source_root_id=ROOT_ID,
        source_object_id=_object_id(request_id),
        source_id=SOURCE,
        source_version_id=_version_id(request_id),
        observation=ObservedNotebookFile(
            relative_path=f"Notebooks/{request_id}.goodnotes",
            size_bytes=len(pdf),
            sha256=_sha(pdf),
            mtime_ns=1,
            page_count=len(split_admitted_pdf(pdf)),
        ),
        liveness=GoodNotesSourceLivenessReceipt(
            source_root_id=ROOT_ID,
            relative_path=f"Notebooks/{request_id}.goodnotes",
            state=GoodNotesSourceLiveness.AVAILABLE,
            checked_at=WHEN,
            maximum_staleness_seconds=300,
            last_seen_at=WHEN,
            current_sha256=_sha(pdf),
            prior_sha256=None,
        ),
        pdf_bytes=pdf,
        notebook_id=issue_stable_id("gnnb", A, request_id),
        observed_at=WHEN,
    )


def _segment() -> dict[str, object]:
    return {
        "kind": "NOTE_UNIT",
        "geometry": {"x_min": 0.1, "y_min": 0.1, "width": 0.2, "height": 0.2},
        "transcription": "synthetic note",
        "primary_class": "MEETING",
    }


def _succeeded(
    store: PostgresDurableNoteStore, principal_id: str, run_id: str
) -> set[GoodNotesPipelineStage]:
    return {
        row.stage
        for row in store.stages(principal_id, run_id)
        if row.status is GoodNotesStageStatus.SUCCEEDED
    }


def _notebook_logical_ids(
    store: PostgresDurableNoteStore, principal_id: str, run_id: str
) -> tuple[str, ...]:
    snapshots = store.snapshots_for_run(principal_id, run_id)
    assert snapshots
    return tuple(
        page.logical_page_id for page in store.logical_pages(principal_id, snapshots[0].notebook_id)
    )


def _propose(store: PostgresDurableNoteStore, run_id: str) -> str:
    positions = ()
    for snapshot in store.snapshots_for_run(A, run_id):
        positions = store.page_positions(A, snapshot.snapshot_id)
        break
    assert positions
    for position in positions:
        version_id = position.page_version_id
        assert version_id is not None
        store.store_semantic_proposal(
            A,
            run_id,
            version_id,
            "note-unit.v1",
            "synthetic",
            "1",
            {
                "segments": [_segment()],
                "candidate_tags": [],
                "ranked_candidates": [],
                "confidence": None,
            },
        )
    return store.semantic_proposals_for_run(A, run_id)[0][0]


def _run(
    store: PostgresDurableNoteStore,
    pdf: bytes,
    request_id: str,
    *,
    fail_after: GoodNotesPipelineStage | None = None,
) -> DurableNoteResult:
    request = _request(pdf, request_id)
    existing = store.run_by_request(A, request_id)
    if existing is not None:
        pull = SqlGoodNotesPullRepository(store.connection)
        for row in store.connection.execute(
            select(goodnotes_semantic_proposals).where(
                goodnotes_semantic_proposals.c.principal_id == A,
                goodnotes_semantic_proposals.c.run_id == existing.run_id,
            )
        ):
            digest = semantic_proposal_sha256(
                str(row.page_version_id),
                str(row.schema_version),
                str(row.analyzer_name),
                str(row.analyzer_version),
                row.payload,
            )
            pull.record_semantic_review(
                GoodNotesSemanticReviewDecisionRecord(
                    decision_id="gnsrd_" + digest[:24],
                    principal_id=A,
                    run_id=existing.run_id,
                    proposal_id=str(row.proposal_id),
                    proposal_sha256=digest,
                    action="accept",
                    request_fingerprint=digest,
                    decided_at=WHEN,
                )
            )
    return GoodNotesDurableNoteOrchestrator(rollout_stage="new-only-summary-preview").run(
        request,
        renderer=production_page_renderer(),
        splitter=split_admitted_pdf,
        store=store,
        clock=lambda: WHEN,
        fail_after=fail_after,
    )


def test_lineage_alone_is_not_terminal_success(engine: Engine) -> None:
    pdf = vector_pdf((COVER,))
    with engine.begin() as connection:
        store = PostgresDurableNoteStore(connection)
        result = _run(store, pdf, "durable-lineage-only")
        assert result.run.status is GoodNotesIngestionStatus.RUNNING
        assert result.waiting_for_proposal is True
        assert result.run.status is not GoodNotesIngestionStatus.SUCCEEDED
        stages = _succeeded(store, A, result.run.run_id)
        assert GoodNotesPipelineStage.LINEAGE in stages
        assert GoodNotesPipelineStage.CONTENT_READY in stages
        assert GoodNotesPipelineStage.WAITING_PROPOSAL in stages
        assert GoodNotesPipelineStage.PREVIEW not in stages
        assert GoodNotesPipelineStage.RECONCILE not in stages


def test_fail_after_lineage_resume_does_not_duplicate_logical_pages(engine: Engine) -> None:
    pdf = vector_pdf((COVER,))
    with engine.begin() as connection:
        store = PostgresDurableNoteStore(connection)
        request_id = "durable-fail-lineage"
        with pytest.raises(DurableNoteStageError) as raised:
            _run(store, pdf, request_id, fail_after=GoodNotesPipelineStage.LINEAGE)
        assert raised.value.stage is GoodNotesPipelineStage.LINEAGE
        run = store.run(A, raised.value.run_id)
        assert run is not None
        assert run.status is not GoodNotesIngestionStatus.SUCCEEDED
        first_pages = _notebook_logical_ids(store, A, run.run_id)
        assert len(first_pages) == 1
        snapshots = store.snapshots_for_run(A, run.run_id)
        assert snapshots
        positions = store.page_positions(A, snapshots[0].snapshot_id)
        assert positions
        version_id = positions[0].page_version_id
        assert version_id is not None
        assert store.page_raster(A, version_id) is None
        resumed = _run(store, pdf, request_id)
        assert resumed.run.status is not GoodNotesIngestionStatus.SUCCEEDED
        assert resumed.waiting_for_proposal is True
        assert _notebook_logical_ids(store, A, resumed.run.run_id) == first_pages
        assert store.page_raster(A, version_id) is not None
        stages = _succeeded(store, A, resumed.run.run_id)
        assert GoodNotesPipelineStage.LINEAGE in stages
        assert GoodNotesPipelineStage.CONTENT_READY in stages
        assert GoodNotesPipelineStage.WAITING_PROPOSAL in stages


def test_proposal_reaches_preview_and_raster_is_principal_scoped(engine: Engine) -> None:
    pdf = vector_pdf((COVER, BODY))
    with engine.begin() as connection:
        store = PostgresDurableNoteStore(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        request_id = "durable-e2e"
        first = _run(store, pdf, request_id)
        assert first.run.status is not GoodNotesIngestionStatus.SUCCEEDED
        assert first.waiting_for_proposal is True
        version_id = _propose(store, first.run.run_id)
        proposals = store.semantic_proposals_for_run(A, first.run.run_id)
        assert proposals
        assert proposals[0][0] == version_id
        finished = _run(store, pdf, request_id)
        assert finished.run.status is GoodNotesIngestionStatus.SUCCEEDED
        assert finished.waiting_for_proposal is False
        assert finished.preview_receipt_id is not None
        stages = _succeeded(store, A, finished.run.run_id)
        assert GoodNotesPipelineStage.PREVIEW in stages
        raster = store.page_raster(A, version_id)
        assert raster is not None
        assert raster.png_sha256 == _sha(raster.png_bytes)
        semantic = semantics.page_raster(A, finished.run.run_id, version_id)
        assert semantic is not None
        assert semantic.png_sha256 == raster.png_sha256
        assert semantic.exact_render_sha256 == raster.exact_render_sha256
        assert store.page_raster(B, version_id) is None
        assert semantics.page_raster(B, finished.run.run_id, version_id) is None
        assert store.stages(B, finished.run.run_id) == ()


@pytest.fixture
def engine(db_engine: Engine) -> Engine:
    return db_engine
