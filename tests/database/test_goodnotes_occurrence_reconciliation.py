"""Disposable PostgreSQL proof for GoodNotes occurrence reconciliation."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import Executable

from my_pa.application.commands import SubmitGoodNotesProposal
from my_pa.application.goodnotes_occurrences import (
    GoodNotesOccurrenceReconciler,
    GoodNotesSemanticPromotionEvidence,
    OccurrenceReconcileBusyError,
    _context_anchor,
    semantic_proposal_sha256,
)
from my_pa.application.goodnotes_semantics import fingerprint_proposal
from my_pa.contracts.ports import GoodNotesSemanticReviewDecisionRecord
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.goodnotes.models import (
    GoodNotesIdentityStatus,
    GoodNotesIngestionRun,
    GoodNotesIngestionStatus,
    GoodNotesIngestionTrigger,
    GoodNotesLogicalPage,
    GoodNotesMatchMethod,
    GoodNotesNote,
    GoodNotesNotebook,
    GoodNotesNoteChangeState,
    GoodNotesNoteOccurrence,
    GoodNotesNoteRevision,
    GoodNotesPage,
    GoodNotesPagePosition,
    GoodNotesPageRaster,
    GoodNotesPageVersion,
    GoodNotesRunNoteChange,
    GoodNotesSourceSnapshot,
    issue_stable_id,
)
from my_pa.domain.goodnotes.page_crop import aligned_crop_box
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.goodnotes.visual import grayscale_png
from my_pa.infrastructure.persistence.goodnotes import PostgresGoodNotesRepository
from my_pa.infrastructure.persistence.goodnotes_pull import (
    SqlGoodNotesPullRepository,
    _corrected_result_sha256,
)
from my_pa.infrastructure.persistence.goodnotes_semantics import SqlGoodNotesSemanticRepository
from my_pa.infrastructure.persistence.tables import (
    goodnotes_ingestion_run_stages,
    goodnotes_logical_pages,
    goodnotes_semantic_proposals,
)

pytestmark = pytest.mark.database
ROOT = Path(__file__).resolve().parents[2]
DATABASE = "my_pa_goodnotes_occurrence_reconcile_test"
WHEN = datetime(2026, 8, 16, 21, 0, tzinfo=UTC)
LATER = WHEN + timedelta(hours=1)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
B = "prn_bbbbbbbbbbbbbbbbbbbbbbbb"
DIGEST = hashlib.sha256(b"synthetic-goodnotes-occurrence-page").hexdigest()
FINGERPRINT = "c" * 64
CROP = "d" * 64
SHARED_RUN = issue_stable_id("gnrun", "shared-occurrence-run")


def _ink_png(
    *,
    width: int = 80,
    height: int = 80,
    boxes: tuple[tuple[float, float, float, float], ...] | None = None,
) -> bytes:
    painted = boxes if boxes is not None else ((0.1, 0.2, 0.2, 0.1), (0.6, 0.2, 0.2, 0.1))
    pixels = bytearray([255] * width * height)
    for x_min, y_min, box_width, box_height in painted:
        x0, y0, x1, y1 = aligned_crop_box(x_min, y_min, box_width, box_height, width, height)
        for row in range(y0, y1):
            for column in range(x0, x1):
                pixels[row * width + column] = 10
    return grayscale_png(bytes(pixels), width, height)


def administer(engine: Engine, *statements: Executable) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)


def _notebook(principal_id: str, token: str) -> GoodNotesNotebook:
    return GoodNotesNotebook(
        notebook_id=issue_stable_id("gnnb", principal_id, token),
        principal_id=principal_id,
        source_root_id="icloud-goodnotes",
        identity_status=GoodNotesIdentityStatus.ACTIVE,
        created_at=WHEN,
        last_observed_at=WHEN,
        label=token,
    )


def _run(principal_id: str, token: str, *, run_id: str | None = None) -> GoodNotesIngestionRun:
    request_id = f"req-{principal_id[-4:]}-{token}"
    return GoodNotesIngestionRun(
        run_id=run_id or issue_stable_id("gnrun", principal_id, token),
        principal_id=principal_id,
        source_root_id="icloud-goodnotes",
        trigger_type=GoodNotesIngestionTrigger.MANUAL,
        request_id=request_id,
        idempotency_key=request_id,
        request_fingerprint=FINGERPRINT,
        started_at=WHEN,
        status=GoodNotesIngestionStatus.RUNNING,
    )


def _plant(
    repository: PostgresGoodNotesRepository,
    principal_id: str,
    token: str,
    *,
    run_id: str | None = None,
) -> tuple[str, str, str, str]:
    notebook = repository.store_notebook(_notebook(principal_id, token))
    logical = repository.store_logical_page(
        GoodNotesLogicalPage(
            logical_page_id=issue_stable_id("gnlp", principal_id, token),
            principal_id=principal_id,
            notebook_id=notebook.notebook_id,
            created_at=WHEN,
            last_seen_at=WHEN,
            identity_status=GoodNotesIdentityStatus.ACTIVE,
        )
    )
    run = repository.create_run(_run(principal_id, token, run_id=run_id))
    object_suffix = hashlib.sha256(f"{principal_id}:{token}:object".encode()).hexdigest()[:24]
    source_object_id = f"obj_{object_suffix}"
    snapshot = repository.store_snapshot(
        GoodNotesSourceSnapshot(
            snapshot_id=issue_stable_id("gnsnap", principal_id, token),
            principal_id=principal_id,
            notebook_id=notebook.notebook_id,
            source_object_id=source_object_id,
            observed_path=f"Inbox/{token}.pdf",
            raw_sha256=hashlib.sha256(f"{principal_id}:{token}".encode()).hexdigest(),
            size_bytes=32,
            page_count=1,
            observed_at=WHEN,
            settled_at=WHEN,
            run_id=run.run_id,
        )
    )
    page = GoodNotesPage(
        page_id=issue_stable_id("gnpg", principal_id, token),
        principal_id=principal_id,
        source_id="src_aaaaaaaaaaaaaaaaaaaaaaaa",
        source_object_id=source_object_id,
        page_number=1,
    )
    version = repository.store_page_version_render(
        page=page,
        version=GoodNotesPageVersion(
            page_version_id=issue_stable_id("gnver", principal_id, token),
            page_id=page.page_id,
            source_version_id="ver_aaaaaaaaaaaaaaaaaaaaaaaa",
            content_sha256=DIGEST,
            exact_render_sha256=hashlib.sha256(_ink_png()).hexdigest(),
            observed_at=WHEN,
            logical_page_id=logical.logical_page_id,
            renderer_name="synthetic",
            renderer_version="1",
            render_profile_version="v1",
        ),
    )
    repository.store_page_position(
        GoodNotesPagePosition(
            principal_id=principal_id,
            snapshot_id=snapshot.snapshot_id,
            page_number=1,
            logical_page_id=logical.logical_page_id,
            created_at=WHEN,
            match_method=GoodNotesMatchMethod.UNRESOLVED,
            page_version_id=version.page_version_id,
        )
    )
    png = _ink_png()
    repository.store_page_raster(
        GoodNotesPageRaster(
            principal_id=principal_id,
            page_version_id=version.page_version_id,
            run_id=run.run_id,
            exact_render_sha256=hashlib.sha256(png).hexdigest(),
            png_sha256=hashlib.sha256(png).hexdigest(),
            byte_length=len(png),
            png_bytes=png,
            renderer_name="synthetic",
            renderer_version="1",
            render_profile_version="v1",
            created_at=WHEN,
        )
    )
    repository.connection.execute(
        goodnotes_ingestion_run_stages.insert().values(
            principal_id=principal_id,
            run_id=run.run_id,
            stage="CONTENT_READY",
            status="SUCCEEDED",
            started_at=WHEN,
            ended_at=WHEN,
        )
    )
    return run.run_id, version.page_version_id, notebook.notebook_id, logical.logical_page_id


def _segment(
    *,
    x_min: float,
    transcription: str,
    crop_sha256: str | None = None,
    kind: str = "NOTE_UNIT",
) -> dict[str, object]:
    values: dict[str, object] = {
        "kind": kind,
        "geometry": {"x_min": x_min, "y_min": 0.2, "width": 0.2, "height": 0.1},
        "transcription": transcription,
        "primary_class": "MEETING",
    }
    if crop_sha256 is not None:
        values["crop_sha256"] = crop_sha256
    return values


def _propose(
    semantics: SqlGoodNotesSemanticRepository,
    *,
    principal_id: str,
    run_id: str,
    page_version_id: str,
    key: str,
    segments: tuple[dict[str, object], ...],
) -> None:
    command = SubmitGoodNotesProposal(
        run_id=run_id,
        page_version_id=page_version_id,
        content_sha256=DIGEST,
        schema_version="note-unit.v1",
        analyzer_name="synthetic",
        analyzer_version="1",
        idempotency_key=key,
        segments=segments,
    )
    fingerprint, payload_digest, body = fingerprint_proposal(command)
    semantics.submit_proposal(
        principal_id=principal_id,
        run_id=run_id,
        page_version_id=page_version_id,
        content_sha256=DIGEST,
        schema_version=command.schema_version,
        analyzer_name=command.analyzer_name,
        analyzer_version=command.analyzer_version,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        payload_sha256=payload_digest,
        payload=body,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        request_id=key,
        audit_id=issue_identifier(IdKind.AUDIT),
        created_at=WHEN,
    )


def _accepted_evidence(
    repository: PostgresGoodNotesRepository,
    principal_id: str,
    run_id: str,
) -> tuple[GoodNotesSemanticPromotionEvidence, ...]:
    pull = SqlGoodNotesPullRepository(repository.connection)
    for row in repository.connection.execute(
        select(goodnotes_semantic_proposals).where(
            goodnotes_semantic_proposals.c.principal_id == principal_id,
            goodnotes_semantic_proposals.c.run_id == run_id,
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
                principal_id=principal_id,
                run_id=run_id,
                proposal_id=str(row.proposal_id),
                proposal_sha256=digest,
                action="accept",
                request_fingerprint=digest,
                decided_at=WHEN,
            )
        )
    return ()


def _counts(connection: object, principal_id: str) -> tuple[int, int]:
    notes = int(
        connection.execute(  # type: ignore[union-attr]
            text("SELECT count(*) FROM knowledge.goodnotes_notes WHERE principal_id = :principal"),
            {"principal": principal_id},
        ).scalar_one()
    )
    changes = int(
        connection.execute(  # type: ignore[union-attr]
            text(
                "SELECT count(*) FROM knowledge.goodnotes_run_note_changes "
                "WHERE principal_id = :principal"
            ),
            {"principal": principal_id},
        ).scalar_one()
    )
    return notes, changes


def test_two_principals_same_run_id_string_do_not_leak(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_a, page_a, _, _ = _plant(lineage, A, "iso-a", run_id=SHARED_RUN)
        run_b, page_b, _, _ = _plant(lineage, B, "iso-b", run_id=SHARED_RUN)
        assert run_a == run_b == SHARED_RUN
        _propose(
            semantics,
            principal_id=A,
            run_id=run_a,
            page_version_id=page_a,
            key="iso-a",
            segments=(_segment(x_min=0.1, transcription="alpha note"),),
        )
        _propose(
            semantics,
            principal_id=B,
            run_id=run_b,
            page_version_id=page_b,
            key="iso-b",
            segments=(_segment(x_min=0.1, transcription="beta note"),),
        )
        reconciler = GoodNotesOccurrenceReconciler()
        result_a = reconciler.reconcile(
            A,
            run_a,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_a),
            clock=lambda: LATER,
        )
        result_b = reconciler.reconcile(
            B,
            run_b,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, B, run_b),
            clock=lambda: LATER,
        )
        assert result_a.changes[0].change_state is GoodNotesNoteChangeState.NEW
        assert result_b.changes[0].change_state is GoodNotesNoteChangeState.NEW
        note_a = result_a.changes[0].note_id
        note_b = result_b.changes[0].note_id
        occurrence_a = result_a.changes[0].occurrence_id
        assert note_a is not None and note_b is not None and occurrence_a is not None
        assert lineage.run_note_changes(B, run_a)[0].note_id != note_a
        assert lineage.note(B, note_a) is None
        assert lineage.note(A, note_b) is None
        assert lineage.occurrence(B, occurrence_a) is None
        with pytest.raises(ValueError, match="no stored GoodNotes ingestion run"):
            reconciler.reconcile(
                B, issue_stable_id("gnrun", "missing-run"), repository=lineage, clock=lambda: LATER
            )


def test_crash_before_commit_writes_nothing(engine: Engine) -> None:
    class Boom(PostgresGoodNotesRepository):
        def store_run_note_change(self, change: GoodNotesRunNoteChange) -> GoodNotesRunNoteChange:
            raise RuntimeError("crash-before-commit")

    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, _, _ = _plant(lineage, A, "crash")
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="crash",
            segments=(_segment(x_min=0.1, transcription="do not persist"),),
        )

    before_notes, before_changes = 0, 0
    with engine.begin() as connection:
        before_notes, before_changes = _counts(connection, A)

    with pytest.raises(RuntimeError, match="crash-before-commit"), engine.begin() as connection:
        repository = Boom(connection)
        GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_id,
            repository=repository,
            promotion_evidence=_accepted_evidence(repository, A, run_id),
            clock=lambda: LATER,
        )

    with engine.begin() as connection:
        notes, changes = _counts(connection, A)
        assert notes == before_notes
        assert changes == before_changes
        repository = PostgresGoodNotesRepository(connection)
        assert repository.run_note_changes(A, run_id) == ()


def test_success_then_duplicate_request_replays_the_same_change_ids(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, _, _ = _plant(lineage, A, "replay")
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="replay",
            segments=(_segment(x_min=0.1, transcription="same note"),),
        )
        reconciler = GoodNotesOccurrenceReconciler()
        first = reconciler.reconcile(
            A,
            run_id,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_id),
            clock=lambda: LATER,
        )
        assert [item.change_state for item in first.changes] == [GoodNotesNoteChangeState.NEW]
        notes_after_first, changes_after_first = _counts(connection, A)

    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        second = GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_id,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_id),
            clock=lambda: LATER,
        )
        assert second.replayed is True
        assert [item.change_id for item in second.changes] == [
            item.change_id for item in first.changes
        ]
        assert [item.change_state for item in second.changes] == [GoodNotesNoteChangeState.NEW]
        notes_after_second, changes_after_second = _counts(connection, A)
        assert notes_after_second == notes_after_first
        assert changes_after_second == changes_after_first


def test_overlapping_reconciles_busy_or_serialize_without_duplicate_new(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, _, _ = _plant(lineage, A, "overlap")
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="overlap",
            segments=(_segment(x_min=0.1, transcription="one winner"),),
        )
        promotion_evidence = _accepted_evidence(lineage, A, run_id)

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        with engine.connect() as connection:
            trans = connection.begin()
            try:
                barrier.wait(timeout=10)
                try:
                    GoodNotesOccurrenceReconciler().reconcile(
                        A,
                        run_id,
                        repository=PostgresGoodNotesRepository(connection),
                        promotion_evidence=promotion_evidence,
                        clock=lambda: LATER,
                    )
                    with lock:
                        outcomes.append("ok")
                    trans.commit()
                except OccurrenceReconcileBusyError:
                    with lock:
                        outcomes.append("busy")
                    trans.rollback()
            except Exception:
                trans.rollback()
                raise

    first = threading.Thread(target=worker)
    second = threading.Thread(target=worker)
    first.start()
    second.start()
    first.join()
    second.join()
    assert "ok" in outcomes
    assert outcomes.count("busy") == 1 or outcomes.count("ok") == 2
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        changes = repository.run_note_changes(A, run_id)
        assert len(changes) == 1
        assert changes[0].change_state is GoodNotesNoteChangeState.NEW
        notes, change_count = _counts(connection, A)
        assert change_count >= 1
        assert notes >= 1


def test_ambiguous_does_not_insert_a_silent_new_pick(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, notebook_id, logical_id = _plant(lineage, A, "ambiguous")
        note = lineage.store_note(
            GoodNotesNote(
                note_id=issue_stable_id("gnnt", A, "ambiguous"),
                principal_id=A,
                notebook_id=notebook_id,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        first = lineage.store_occurrence(
            GoodNotesNoteOccurrence(
                occurrence_id=issue_stable_id("gnocc", A, "ambiguous-one"),
                principal_id=A,
                note_id=note.note_id,
                logical_page_id=logical_id,
                x_min=0.10,
                y_min=0.2,
                width=0.2,
                height=0.1,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
                crop_sha256=CROP,
            )
        )
        second = lineage.store_occurrence(
            GoodNotesNoteOccurrence(
                occurrence_id=issue_stable_id("gnocc", A, "ambiguous-two"),
                principal_id=A,
                note_id=note.note_id,
                logical_page_id=logical_id,
                x_min=0.50,
                y_min=0.2,
                width=0.2,
                height=0.1,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
                crop_sha256=CROP,
            )
        )
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="ambiguous",
            segments=(
                _segment(x_min=0.12, transcription="one", crop_sha256=CROP),
                _segment(x_min=0.52, transcription="two", crop_sha256=CROP),
            ),
        )
        notes_before, _ = _counts(connection, A)
        result = GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_id,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_id),
            clock=lambda: LATER,
        )
        states = {item.change_state for item in result.changes}
        assert GoodNotesNoteChangeState.NEW not in states
        assert states == {GoodNotesNoteChangeState.AMBIGUOUS}
        identified = {
            item.occurrence_id for item in result.changes if item.occurrence_id is not None
        }
        assert identified == {first.occurrence_id, second.occurrence_id}
        assert any(item.occurrence_id is None for item in result.changes)
        notes_after, _ = _counts(connection, A)
        assert notes_after == notes_before
        assert lineage.occurrence(A, first.occurrence_id) is not None
        stored = lineage.occurrence(A, first.occurrence_id)
        assert stored is not None
        assert stored.identity_status is GoodNotesIdentityStatus.AMBIGUOUS


def test_missing_geometry_fails_closed_without_partial_writes(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, _, _ = _plant(lineage, A, "bad-geometry")
        semantics.submit_proposal(
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            content_sha256=DIGEST,
            schema_version="note-unit.v1",
            analyzer_name="synthetic",
            analyzer_version="1",
            idempotency_key="bad-geometry",
            request_fingerprint="e" * 64,
            payload_sha256=_corrected_result_sha256(
                {
                    "segments": [{"kind": "NOTE_UNIT", "transcription": "no box"}],
                    "candidate_tags": [],
                    "ranked_candidates": [],
                    "confidence": None,
                }
            ),
            payload={
                "segments": [{"kind": "NOTE_UNIT", "transcription": "no box"}],
                "candidate_tags": [],
                "ranked_candidates": [],
                "confidence": None,
            },
            correlation_id=issue_identifier(IdKind.CORRELATION),
            request_id="bad-geometry",
            audit_id=issue_identifier(IdKind.AUDIT),
            created_at=WHEN,
        )
        notes_before, changes_before = _counts(connection, A)
        with pytest.raises(ValueError, match="missing required geometry"):
            GoodNotesOccurrenceReconciler().reconcile(
                A,
                run_id,
                repository=lineage,
                promotion_evidence=_accepted_evidence(lineage, A, run_id),
                clock=lambda: LATER,
            )
        notes_after, changes_after = _counts(connection, A)
        assert notes_after == notes_before
        assert changes_after == changes_before


def test_unique_visual_match_with_new_transcription_is_revised(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, notebook_id, logical_id = _plant(lineage, A, "revised")
        note = lineage.store_note(
            GoodNotesNote(
                note_id=issue_stable_id("gnnt", A, "revised"),
                principal_id=A,
                notebook_id=notebook_id,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        occurrence = lineage.store_occurrence(
            GoodNotesNoteOccurrence(
                occurrence_id=issue_stable_id("gnocc", A, "revised"),
                principal_id=A,
                note_id=note.note_id,
                logical_page_id=logical_id,
                x_min=0.1,
                y_min=0.2,
                width=0.2,
                height=0.1,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        original = lineage.store_revision(
            GoodNotesNoteRevision(
                revision_id=issue_stable_id("gnrev", A, "revised-first"),
                principal_id=A,
                note_id=note.note_id,
                schema_version="note-unit.v1",
                analyzer_name="synthetic",
                analyzer_version="1",
                transcription="follow up Tuesday",
                created_at=WHEN,
                occurrence_id=occurrence.occurrence_id,
            )
        )
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="revised",
            segments=(_segment(x_min=0.1, transcription="follow up Thursday"),),
        )
        result = GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_id,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_id),
            clock=lambda: LATER,
        )
        assert [item.change_state for item in result.changes] == [
            GoodNotesNoteChangeState.UNCHANGED
        ]
        assert result.changes[0].occurrence_id == occurrence.occurrence_id
        latest = lineage.latest_revision_for_occurrence(A, occurrence.occurrence_id)
        assert latest is not None
        assert latest.transcription == "follow up Thursday"
        assert latest.supersedes_revision_id == original.revision_id
        assert lineage.revision(A, original.revision_id) is not None
        assert lineage.revision(A, original.revision_id).transcription == "follow up Tuesday"


def test_new_occurrence_does_not_reuse_note_by_page_wide_context_hash(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, notebook_id, logical_id = _plant(lineage, A, "append")
        heading = _segment(x_min=0.4, transcription="synthetic heading", kind="SOURCE_CONTEXT")
        existing_unit = _segment(x_min=0.1, transcription="synthetic note", crop_sha256=CROP)
        appended = _segment(x_min=0.6, transcription="synthetic note", crop_sha256="e" * 64)
        note = lineage.store_note(
            GoodNotesNote(
                note_id=issue_stable_id("gnnt", A, "append"),
                principal_id=A,
                notebook_id=notebook_id,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        existing = lineage.store_occurrence(
            GoodNotesNoteOccurrence(
                occurrence_id=issue_stable_id("gnocc", A, "append"),
                principal_id=A,
                note_id=note.note_id,
                logical_page_id=logical_id,
                x_min=0.1,
                y_min=0.2,
                width=0.2,
                height=0.1,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
                crop_sha256=CROP,
                context_anchor_sha256=_context_anchor((heading, existing_unit, appended)),
            )
        )
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="append",
            segments=(heading, existing_unit, appended),
        )
        notes_before, _ = _counts(connection, A)
        result = GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_id,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_id),
            clock=lambda: LATER,
        )
        notes_after, _ = _counts(connection, A)
        assert notes_after == notes_before + 1
        notebook_notes = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM knowledge.goodnotes_notes "
                    "WHERE principal_id = :principal AND notebook_id = :notebook"
                ),
                {"principal": A, "notebook": notebook_id},
            ).scalar_one()
        )
        assert notebook_notes == 2
        new_changes = [
            item for item in result.changes if item.change_state is GoodNotesNoteChangeState.NEW
        ]
        assert len(new_changes) == 1
        new_note_id = new_changes[0].note_id
        new_occurrence_id = new_changes[0].occurrence_id
        assert new_note_id is not None and new_occurrence_id is not None
        assert new_note_id != note.note_id
        assert new_occurrence_id != existing.occurrence_id
        stored = lineage.occurrence(A, new_occurrence_id)
        assert stored is not None
        assert stored.note_id != note.note_id
        assert stored.note_id == new_note_id
        paired = [item for item in result.changes if item.occurrence_id == existing.occurrence_id]
        assert len(paired) == 1
        assert paired[0].change_state in {
            GoodNotesNoteChangeState.UNCHANGED,
            GoodNotesNoteChangeState.REVISED,
        }
        assert paired[0].note_id == note.note_id


def test_revision_page_version_survives_occurrence_pointer_update(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, _, _ = _plant(lineage, A, "pointer")
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="pointer",
            segments=(_segment(x_min=0.1, transcription="first ink"),),
        )
        first = GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_id,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_id),
            clock=lambda: LATER,
        )
        assert first.changes[0].revision_id is not None
        revision = lineage.revision(A, first.changes[0].revision_id)
        assert revision is not None
        assert revision.page_version_id == page_id
        occurrence_id = first.changes[0].occurrence_id
        assert occurrence_id is not None
        occurrence = lineage.occurrence(A, occurrence_id)
        assert occurrence is not None
        lineage.store_occurrence(replace(occurrence, last_seen_at=LATER))
        held = lineage.revision(A, revision.revision_id)
        assert held is not None
        assert held.page_version_id == page_id


def test_mismatched_note_occurrence_pair_is_refused(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        run_id, _, notebook_id, logical_id = _plant(lineage, A, "mismatch")
        first_note = lineage.store_note(
            GoodNotesNote(
                note_id=issue_stable_id("gnnt", A, "mismatch-one"),
                principal_id=A,
                notebook_id=notebook_id,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        second_note = lineage.store_note(
            GoodNotesNote(
                note_id=issue_stable_id("gnnt", A, "mismatch-two"),
                principal_id=A,
                notebook_id=notebook_id,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        occurrence = lineage.store_occurrence(
            GoodNotesNoteOccurrence(
                occurrence_id=issue_stable_id("gnocc", A, "mismatch"),
                principal_id=A,
                note_id=first_note.note_id,
                logical_page_id=logical_id,
                x_min=0.1,
                y_min=0.2,
                width=0.2,
                height=0.1,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        with pytest.raises(IntegrityError), connection.begin_nested():
            lineage.store_run_note_change(
                GoodNotesRunNoteChange(
                    change_id=issue_stable_id("gnchg", A, "mismatch"),
                    principal_id=A,
                    run_id=run_id,
                    note_id=second_note.note_id,
                    occurrence_id=occurrence.occurrence_id,
                    change_state=GoodNotesNoteChangeState.NEW,
                    created_at=LATER,
                )
            )


def test_current_only_ambiguous_insert_is_allowed_and_new_still_requires_fks(
    engine: Engine,
) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        run_id, page_id, notebook_id, _ = _plant(lineage, A, "anon-amb")
        note = lineage.store_note(
            GoodNotesNote(
                note_id=issue_stable_id("gnnt", A, "anon-amb"),
                principal_id=A,
                notebook_id=notebook_id,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        stored = lineage.store_run_note_change(
            GoodNotesRunNoteChange(
                change_id=issue_stable_id("gnchg", A, "anon-amb"),
                principal_id=A,
                run_id=run_id,
                note_id=None,
                occurrence_id=None,
                change_state=GoodNotesNoteChangeState.AMBIGUOUS,
                created_at=LATER,
                page_version_id=page_id,
                geometry_key="0.1000,0.2000,0.2000,0.1000:none",
                reason="UNVERIFIED_VISUAL",
            )
        )
        assert stored.note_id is None
        assert stored.occurrence_id is None
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_run_note_changes ("
                    " principal_id, change_id, run_id, note_id, occurrence_id,"
                    " change_state, created_at, page_version_id, geometry_key"
                    ") VALUES ("
                    " :principal, :change_id, :run_id, NULL, NULL, 'NEW', :created,"
                    " :page, '0.1000,0.2000,0.2000,0.1000:none')"
                ),
                {
                    "principal": A,
                    "change_id": issue_stable_id("gnchg", A, "anon-new"),
                    "run_id": run_id,
                    "created": LATER,
                    "page": page_id,
                },
            )
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO knowledge.goodnotes_note_revisions ("
                    " principal_id, revision_id, note_id, schema_version,"
                    " analyzer_name, analyzer_version, transcription, created_at,"
                    " page_version_id"
                    ") VALUES ("
                    " :principal, :revision, :note, 'note-unit.v1', 'synthetic', '1',"
                    " 'orphan provenance', :created, 'gnver_ffffffffffffffffffffffff')"
                ),
                {
                    "principal": A,
                    "revision": issue_stable_id("gnrev", A, "bad-page"),
                    "note": note.note_id,
                    "created": LATER,
                },
            )


def test_deleted_logical_page_emits_removed_for_prior_occurrences(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, notebook_id, cover_id = _plant(lineage, A, "keep")
        body = lineage.store_logical_page(
            GoodNotesLogicalPage(
                logical_page_id=issue_stable_id("gnlp", A, "gone"),
                principal_id=A,
                notebook_id=notebook_id,
                created_at=WHEN,
                last_seen_at=WHEN,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
            )
        )
        note = lineage.store_note(
            GoodNotesNote(
                note_id=issue_stable_id("gnnt", A, "gone"),
                principal_id=A,
                notebook_id=notebook_id,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        gone = lineage.store_occurrence(
            GoodNotesNoteOccurrence(
                occurrence_id=issue_stable_id("gnocc", A, "gone"),
                principal_id=A,
                note_id=note.note_id,
                logical_page_id=body.logical_page_id,
                x_min=0.1,
                y_min=0.2,
                width=0.2,
                height=0.1,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="keep",
            segments=(_segment(x_min=0.1, transcription="cover note"),),
        )
        result = GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_id,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_id),
            clock=lambda: LATER,
        )
        removed = [
            item
            for item in result.changes
            if item.change_state is GoodNotesNoteChangeState.REMOVED_OR_NO_LONGER_PRESENT
        ]
        assert len(removed) == 1
        assert removed[0].occurrence_id == gone.occurrence_id
        assert cover_id != body.logical_page_id
        stored = lineage.occurrence(A, gone.occurrence_id)
        assert stored is not None
        assert stored.identity_status is GoodNotesIdentityStatus.RETIRED


@pytest.fixture
def engine(db_engine: Engine) -> Engine:
    return db_engine


def test_promotion_requires_persisted_review_and_terminal_zero_output_receipt(
    engine: Engine,
) -> None:
    from my_pa.contracts.ports import GoodNotesSemanticReviewConflictError
    from my_pa.infrastructure.persistence.tables import goodnotes_semantic_promotion_receipts

    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        run_id, page_id, _, _ = _plant(repository, A, "zero-reviewed")
        _propose(
            SqlGoodNotesSemanticRepository(connection),
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="zero-reviewed",
            segments=(_segment(x_min=0.1, transcription="context", kind="SOURCE_CONTEXT"),),
        )
        pull = SqlGoodNotesPullRepository(connection)
        assert pull.accepted_semantic_material(A, run_id) is None
        assert pull.accepted_semantic_material(B, run_id) is None
        with pytest.raises(ValueError):
            GoodNotesOccurrenceReconciler().reconcile(A, run_id, repository=repository)
        assert _counts(connection, A) == (0, 0)
        _accepted_evidence(repository, A, run_id)
        result = GoodNotesOccurrenceReconciler().reconcile(A, run_id, repository=repository)
        assert result.changes == ()
        receipt = connection.execute(select(goodnotes_semantic_promotion_receipts)).one()
        assert len(receipt.bindings) == 1
        assert "segments" not in receipt.bindings[0]
        replay = GoodNotesOccurrenceReconciler().reconcile(A, run_id, repository=repository)
        assert replay.replayed
        assert pull.record_semantic_promotion(A, run_id) == receipt.receipt_id
        # A later run may retire a page; historical promotion remains replayable.
        connection.execute(
            update(goodnotes_logical_pages)
            .where(goodnotes_logical_pages.c.principal_id == A)
            .values(identity_status="RETIRED")
        )
        assert repository.accepted_semantic_material(A, run_id, require_promoted=True) is not None
        # Exact original Review retry remains legal after canonical promotion.
        _accepted_evidence(repository, A, run_id)
        proposal = connection.execute(select(goodnotes_semantic_proposals)).one()
        with pytest.raises(GoodNotesSemanticReviewConflictError):
            pull.record_semantic_review(
                GoodNotesSemanticReviewDecisionRecord(
                    decision_id="gnsrd_" + "b" * 24,
                    principal_id=A,
                    run_id=run_id,
                    proposal_id=proposal.proposal_id,
                    proposal_sha256=semantic_proposal_sha256(
                        proposal.page_version_id,
                        proposal.schema_version,
                        proposal.analyzer_name,
                        proposal.analyzer_version,
                        proposal.payload,
                    ),
                    action="reject",
                    request_fingerprint="a" * 64,
                    decided_at=LATER,
                )
            )
        assert _counts(connection, A) == (0, 0)


def test_full_run_missing_position_never_promotes_subset(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        run_id, page_id, notebook_id, _ = _plant(repository, A, "partial-run")
        _propose(
            SqlGoodNotesSemanticRepository(connection),
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="partial-run",
            segments=(_segment(x_min=0.1, transcription="synthetic"),),
        )
        _accepted_evidence(repository, A, run_id)
        # A second immutable snapshot advertises a page which is not ready yet.
        repository.store_snapshot(
            GoodNotesSourceSnapshot(
                snapshot_id=issue_stable_id("gnsnap", "pending-second"),
                principal_id=A,
                notebook_id=notebook_id,
                source_object_id="obj_bbbbbbbbbbbbbbbbbbbbbbbb",
                observed_path="pending.pdf",
                raw_sha256="f" * 64,
                size_bytes=1,
                page_count=1,
                observed_at=WHEN,
                settled_at=WHEN,
                run_id=run_id,
            )
        )
        assert repository.accepted_semantic_material(A, run_id) is None
        with pytest.raises(ValueError):
            GoodNotesOccurrenceReconciler().reconcile(A, run_id, repository=repository)
        assert _counts(connection, A) == (0, 0)


@pytest.mark.parametrize("promotion_first", [False, True])
def test_review_and_promotion_serialize_on_same_run_lock(
    engine: Engine, promotion_first: bool
) -> None:
    from sqlalchemy.exc import DBAPIError

    from my_pa.contracts.ports import GoodNotesSemanticReviewConflictError

    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        run_id, page_id, _, _ = _plant(repository, A, "race")
        _propose(
            SqlGoodNotesSemanticRepository(connection),
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="race",
            segments=(_segment(x_min=0.1, transcription="context", kind="SOURCE_CONTEXT"),),
        )
        _accepted_evidence(repository, A, run_id)
        proposal = connection.execute(select(goodnotes_semantic_proposals)).one()
        rejection = GoodNotesSemanticReviewDecisionRecord(
            decision_id="gnsrd_" + "b" * 24,
            principal_id=A,
            run_id=run_id,
            proposal_id=proposal.proposal_id,
            proposal_sha256=semantic_proposal_sha256(
                proposal.page_version_id,
                proposal.schema_version,
                proposal.analyzer_name,
                proposal.analyzer_version,
                proposal.payload,
            ),
            action="reject",
            request_fingerprint="a" * 64,
            decided_at=LATER,
        )
    with engine.connect() as winner:
        transaction = winner.begin()
        if promotion_first:
            GoodNotesOccurrenceReconciler().reconcile(
                A, run_id, repository=PostgresGoodNotesRepository(winner)
            )
        else:
            SqlGoodNotesPullRepository(winner).record_semantic_review(rejection)
        with engine.connect() as contender:
            competing = contender.begin()
            contender.execute(text("SET LOCAL lock_timeout = '250ms'"))
            with pytest.raises(DBAPIError, match="lock timeout"):
                if promotion_first:
                    SqlGoodNotesPullRepository(contender).record_semantic_review(rejection)
                else:
                    GoodNotesOccurrenceReconciler().reconcile(
                        A, run_id, repository=PostgresGoodNotesRepository(contender)
                    )
            competing.rollback()
        transaction.commit()
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        if promotion_first:
            with pytest.raises(GoodNotesSemanticReviewConflictError):
                SqlGoodNotesPullRepository(connection).record_semantic_review(rejection)
            assert (
                repository.accepted_semantic_material(A, run_id, require_promoted=True) is not None
            )
        else:
            assert repository.accepted_semantic_material(A, run_id) is None
            with pytest.raises(ValueError):
                GoodNotesOccurrenceReconciler().reconcile(A, run_id, repository=repository)
        assert _counts(connection, A) == (0, 0)


def test_corrected_review_payload_is_canonical_and_original_is_immutable(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        run_id, page_id, _, _ = _plant(repository, A, "corrected")
        _propose(
            SqlGoodNotesSemanticRepository(connection),
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="corrected",
            segments=(_segment(x_min=0.1, transcription="original synthetic"),),
        )
        _accepted_evidence(repository, A, run_id)
        proposal = connection.execute(select(goodnotes_semantic_proposals)).one()
        correction = {
            "segments": [_segment(x_min=0.1, transcription="corrected synthetic")],
            "candidate_tags": ["corrected"],
            "ranked_candidates": [],
            "confidence": 0.9,
        }
        pull = SqlGoodNotesPullRepository(connection)
        recorded = pull.record_semantic_review(
            GoodNotesSemanticReviewDecisionRecord(
                decision_id="gnsrd_bbbbbbbbbbbbbbbbbbbbbbbb",
                principal_id=A,
                run_id=run_id,
                proposal_id=proposal.proposal_id,
                proposal_sha256=semantic_proposal_sha256(
                    proposal.page_version_id,
                    proposal.schema_version,
                    proposal.analyzer_name,
                    proposal.analyzer_version,
                    proposal.payload,
                ),
                action="correct_and_accept",
                request_fingerprint="b" * 64,
                decided_at=LATER,
                corrected_payload=correction,
                corrected_result_sha256=_corrected_result_sha256(correction),
            )
        )
        assert recorded.sequence == 2  # ACCEPT is revisable until canonical promotion.
        result = GoodNotesOccurrenceReconciler().reconcile(A, run_id, repository=repository)
        occurrence_id = result.changes[0].occurrence_id
        assert occurrence_id is not None
        revision = repository.latest_revision_for_occurrence(A, occurrence_id)
        assert revision is not None
        assert revision.transcription == "corrected synthetic"
        material = repository.accepted_semantic_material(A, run_id, require_promoted=True)
        assert material is not None
        assert material[0].payload == correction
        stored = connection.execute(select(goodnotes_semantic_proposals)).one()
        assert stored.payload == proposal.payload
        assert stored.payload_sha256 == proposal.payload_sha256


def test_ambiguous_new_page_cannot_promote_even_with_accept(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        run_id, page_id, _, logical_id = _plant(repository, A, "ambiguous-new")
        _propose(
            SqlGoodNotesSemanticRepository(connection),
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="ambiguous-new",
            segments=(_segment(x_min=0.1, transcription="synthetic"),),
        )
        _accepted_evidence(repository, A, run_id)
        connection.execute(
            update(goodnotes_logical_pages)
            .where(
                goodnotes_logical_pages.c.principal_id == A,
                goodnotes_logical_pages.c.logical_page_id == logical_id,
            )
            .values(identity_status="AMBIGUOUS")
        )
        assert repository.accepted_semantic_material(A, run_id) is None
        with pytest.raises(ValueError):
            GoodNotesOccurrenceReconciler().reconcile(A, run_id, repository=repository)
        assert _counts(connection, A) == (0, 0)


def test_promoted_run_refuses_new_proposal_key_and_preserves_durable_replay(engine: Engine) -> None:
    from my_pa.contracts.ports import GoodNotesProposalConflictError
    from my_pa.infrastructure.persistence.tables import goodnotes_semantic_promotion_receipts

    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        run_id, page_id, _, _ = _plant(repository, A, "late-proposal")
        _propose(
            SqlGoodNotesSemanticRepository(connection),
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="initial",
            segments=(_segment(x_min=0.1, transcription="synthetic"),),
        )
        _accepted_evidence(repository, A, run_id)
        first = GoodNotesOccurrenceReconciler().reconcile(A, run_id, repository=repository)
        assert first.changes
        receipt = connection.execute(select(goodnotes_semantic_promotion_receipts)).one()
    with engine.begin() as connection:
        semantics = SqlGoodNotesSemanticRepository(connection)
        with pytest.raises(GoodNotesProposalConflictError, match="already promoted"):
            _propose(
                semantics,
                principal_id=A,
                run_id=run_id,
                page_version_id=page_id,
                key="late-request",
                segments=(_segment(x_min=0.1, transcription="synthetic"),),
            )
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="initial",
            segments=(_segment(x_min=0.1, transcription="synthetic"),),
        )
        with pytest.raises(GoodNotesProposalConflictError):
            _propose(
                semantics,
                principal_id=A,
                run_id=run_id,
                page_version_id=page_id,
                key="initial",
                segments=(_segment(x_min=0.1, transcription="changed"),),
            )
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        replay = GoodNotesOccurrenceReconciler().reconcile(A, run_id, repository=repository)
        assert replay.replayed
        assert replay.changes == first.changes
        assert repository.accepted_semantic_material(A, run_id, require_promoted=True) is not None
        assert len(connection.execute(select(goodnotes_semantic_proposals)).all()) == 1
        stored = connection.execute(select(goodnotes_semantic_promotion_receipts)).one()
        assert stored == receipt


@pytest.mark.parametrize("promotion_first", [False, True])
def test_submit_and_promotion_share_run_lock(engine: Engine, promotion_first: bool) -> None:
    from sqlalchemy.exc import DBAPIError

    from my_pa.contracts.ports import GoodNotesProposalConflictError, RepositoryFailureError
    from my_pa.infrastructure.persistence.tables import goodnotes_semantic_promotion_receipts

    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        run_id, page_id, _, _ = _plant(repository, A, "submit-race")
        _propose(
            SqlGoodNotesSemanticRepository(connection),
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="initial",
            segments=(_segment(x_min=0.1, transcription="synthetic"),),
        )
        _accepted_evidence(repository, A, run_id)
    with engine.connect() as winner:
        transaction = winner.begin()
        if promotion_first:
            GoodNotesOccurrenceReconciler().reconcile(
                A, run_id, repository=PostgresGoodNotesRepository(winner)
            )
        else:
            _propose(
                SqlGoodNotesSemanticRepository(winner),
                principal_id=A,
                run_id=run_id,
                page_version_id=page_id,
                key="racing-request",
                segments=(_segment(x_min=0.1, transcription="synthetic"),),
            )
        with engine.connect() as contender:
            competing = contender.begin()
            contender.execute(text("SET LOCAL lock_timeout = '250ms'"))
            if promotion_first:
                # Submit maps the DB timeout to its existing content-safe error.
                with pytest.raises(RepositoryFailureError, match="could not be completed"):
                    _propose(
                        SqlGoodNotesSemanticRepository(contender),
                        principal_id=A,
                        run_id=run_id,
                        page_version_id=page_id,
                        key="racing-request",
                        segments=(_segment(x_min=0.1, transcription="synthetic"),),
                    )
            else:
                with pytest.raises(DBAPIError, match="lock timeout"):
                    GoodNotesOccurrenceReconciler().reconcile(
                        A, run_id, repository=PostgresGoodNotesRepository(contender)
                    )
            competing.rollback()
        transaction.commit()
    with engine.begin() as connection:
        repository = PostgresGoodNotesRepository(connection)
        if promotion_first:
            with pytest.raises(GoodNotesProposalConflictError, match="already promoted"):
                _propose(
                    SqlGoodNotesSemanticRepository(connection),
                    principal_id=A,
                    run_id=run_id,
                    page_version_id=page_id,
                    key="racing-request",
                    segments=(_segment(x_min=0.1, transcription="synthetic"),),
                )
            _propose(
                SqlGoodNotesSemanticRepository(connection),
                principal_id=A,
                run_id=run_id,
                page_version_id=page_id,
                key="initial",
                segments=(_segment(x_min=0.1, transcription="synthetic"),),
            )
            assert (
                GoodNotesOccurrenceReconciler().reconcile(A, run_id, repository=repository).replayed
            )
            assert len(connection.execute(select(goodnotes_semantic_proposals)).all()) == 1
            assert len(connection.execute(select(goodnotes_semantic_promotion_receipts)).all()) == 1
        else:
            # Ordinary pre-promotion multiple proposals remain ambiguous, never
            # allowing a receipt which could later be poisoned by the second row.
            assert repository.accepted_semantic_material(A, run_id) is None
            with pytest.raises(ValueError):
                GoodNotesOccurrenceReconciler().reconcile(A, run_id, repository=repository)
            assert len(connection.execute(select(goodnotes_semantic_proposals)).all()) == 2
            assert connection.execute(select(goodnotes_semantic_promotion_receipts)).first() is None
