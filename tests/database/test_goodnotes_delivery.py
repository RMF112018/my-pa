"""Disposable PostgreSQL proof for GoodNotes NEW-only delivery receipts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, insert, text
from sqlalchemy.sql import Executable

from my_pa.application.commands import SubmitGoodNotesProposal
from my_pa.application.goodnotes_corrections import GoodNotesCorrectionService
from my_pa.application.goodnotes_delivery import (
    GoodNotesDeliveryAttemptLedger,
    GoodNotesNewOnlyDelivery,
)
from my_pa.application.goodnotes_occurrences import (
    GoodNotesOccurrenceReconciler,
    GoodNotesSemanticPromotionEvidence,
    semantic_proposal_sha256,
)
from my_pa.application.goodnotes_semantics import fingerprint_proposal
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.goodnotes.models import (
    GoodNotesDeliveryAttemptState,
    GoodNotesEntityKind,
    GoodNotesEntityResolution,
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
from my_pa.infrastructure.persistence.goodnotes_delivery import PostgresGoodNotesDeliveryRepository
from my_pa.infrastructure.persistence.goodnotes_semantics import SqlGoodNotesSemanticRepository
from my_pa.infrastructure.persistence.tables import projects

pytestmark = pytest.mark.database
ROOT = Path(__file__).resolve().parents[2]
DATABASE = "my_pa_goodnotes_delivery_test"
WHEN = datetime(2026, 8, 16, 22, 0, tzinfo=UTC)
LATER = WHEN + timedelta(hours=1)
CORRECTED = LATER + timedelta(minutes=1)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
B = "prn_bbbbbbbbbbbbbbbbbbbbbbbb"
DIGEST = hashlib.sha256(b"synthetic-goodnotes-delivery-page").hexdigest()
FINGERPRINT = "c" * 64
CROP = "d" * 64
SHARED_RUN = issue_stable_id("gnrun", "shared-delivery-run")
DESTINATION = "operator-local"


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
            match_method=GoodNotesMatchMethod.ORDINAL_WEAK,
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
    return run.run_id, version.page_version_id, notebook.notebook_id, logical.logical_page_id


def _segment(
    *,
    x_min: float,
    transcription: str,
    crop_sha256: str | None = None,
    primary_class: str | None = "MEETING",
    kind: str = "NOTE_UNIT",
    ranked_candidates: tuple[dict[str, object], ...] | None = None,
    transcription_status: str | None = None,
    confidence: dict[str, object] | None = None,
    candidate_tags: tuple[str, ...] | None = None,
) -> dict[str, object]:
    values: dict[str, object] = {
        "kind": kind,
        "geometry": {"x_min": x_min, "y_min": 0.2, "width": 0.2, "height": 0.1},
        "transcription": transcription,
        "primary_class": primary_class,
    }
    if crop_sha256 is not None:
        values["crop_sha256"] = crop_sha256
    if ranked_candidates is not None:
        values["ranked_candidates"] = ranked_candidates
    if transcription_status is not None:
        values["transcription_status"] = transcription_status
    if confidence is not None:
        values["confidence"] = confidence
    if candidate_tags is not None:
        values["candidate_tags"] = candidate_tags
    return values


def _propose(
    semantics: SqlGoodNotesSemanticRepository,
    *,
    principal_id: str,
    run_id: str,
    page_version_id: str,
    key: str,
    segments: tuple[dict[str, object], ...],
    ranked_candidates: tuple[dict[str, object], ...] = (),
    confidence: dict[str, object] | None = None,
    schema_version: str = "note-unit.v1",
) -> None:
    command = SubmitGoodNotesProposal(
        run_id=run_id,
        page_version_id=page_version_id,
        content_sha256=DIGEST,
        schema_version=schema_version,
        analyzer_name="synthetic",
        analyzer_version="1",
        idempotency_key=key,
        segments=segments,
        ranked_candidates=ranked_candidates,
        confidence=confidence,
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
    return tuple(
        GoodNotesSemanticPromotionEvidence(
            principal_id=principal_id,
            run_id=run_id,
            proposal_sha256=semantic_proposal_sha256(*proposal),
            disposition=Disposition.ACCEPT,
        )
        for proposal in repository.semantic_proposals_for_run(principal_id, run_id)
    )


def _project(connection: object, principal_id: str, name: str) -> str:
    project_id = issue_identifier(IdKind.PROJECT)
    connection.execute(  # type: ignore[union-attr]
        insert(projects).values(
            project_id=project_id,
            principal_id=principal_id,
            name=name,
            state="active",
            participants=[],
            opened_at=WHEN,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    return project_id


def _project_count(connection: object, principal_id: str, *, name: str | None = None) -> int:
    sql = "SELECT count(*) FROM knowledge.projects WHERE principal_id = :principal"
    values: dict[str, str] = {"principal": principal_id}
    if name is not None:
        sql += " AND name = :name"
        values["name"] = name
    return int(
        connection.execute(  # type: ignore[union-attr]
            text(sql),
            values,
        ).scalar_one()
    )


def test_two_principals_same_run_id_string_do_not_leak(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        delivery = PostgresGoodNotesDeliveryRepository(connection)
        run_a, page_a, _, _ = _plant(lineage, A, "iso-a", run_id=SHARED_RUN)
        run_b, page_b, _, _ = _plant(lineage, B, "iso-b", run_id=SHARED_RUN)
        assert run_a == run_b == SHARED_RUN
        _propose(
            semantics,
            principal_id=A,
            run_id=run_a,
            page_version_id=page_a,
            key="iso-a",
            segments=(_segment(x_min=0.1, transcription="synthetic note"),),
        )
        _propose(
            semantics,
            principal_id=B,
            run_id=run_b,
            page_version_id=page_b,
            key="iso-b",
            segments=(_segment(x_min=0.1, transcription="synthetic heading"),),
        )
        GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_a,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_a),
            clock=lambda: LATER,
        )
        GoodNotesOccurrenceReconciler().reconcile(
            B,
            run_b,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, B, run_b),
            clock=lambda: LATER,
        )
        result_a = GoodNotesNewOnlyDelivery().deliver(
            A, run_a, DESTINATION, repository=delivery, clock=lambda: LATER
        )
        result_b = GoodNotesNewOnlyDelivery().deliver(
            B, run_b, DESTINATION, repository=delivery, clock=lambda: LATER
        )
        assert result_a.receipt.body is not None and "synthetic note" in result_a.receipt.body
        assert result_b.receipt.body is not None and "synthetic heading" in result_b.receipt.body
        assert "synthetic heading" not in result_a.receipt.body
        assert "synthetic note" not in result_b.receipt.body
        assert delivery.delivery_receipt(B, result_a.receipt.receipt_id) is None
        assert delivery.delivery_receipt(A, result_b.receipt.receipt_id) is None
        with pytest.raises(ValueError, match="no stored GoodNotes ingestion run"):
            GoodNotesNewOnlyDelivery().deliver(
                B,
                issue_stable_id("gnrun", "missing-run"),
                DESTINATION,
                repository=delivery,
                clock=lambda: LATER,
            )


def test_new_plus_revised_receipt_membership_is_new_only(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        delivery = PostgresGoodNotesDeliveryRepository(connection)
        run_id, page_id, notebook_id, logical_id = _plant(lineage, A, "mix")
        note = lineage.store_note(
            GoodNotesNote(
                note_id=issue_stable_id("gnnt", A, "mix"),
                principal_id=A,
                notebook_id=notebook_id,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        occurrence = lineage.store_occurrence(
            GoodNotesNoteOccurrence(
                occurrence_id=issue_stable_id("gnocc", A, "mix"),
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
        lineage.store_revision(
            GoodNotesNoteRevision(
                revision_id=issue_stable_id("gnrev", A, "mix-first"),
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
            key="mix",
            segments=(
                _segment(x_min=0.1, transcription="follow up Thursday"),
                _segment(x_min=0.6, transcription="synthetic note", crop_sha256=CROP),
            ),
        )
        reconciled = GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_id,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_id),
            clock=lambda: LATER,
        )
        states = {item.change_state for item in reconciled.changes}
        assert GoodNotesNoteChangeState.NEW in states
        assert GoodNotesNoteChangeState.UNCHANGED in states
        assert GoodNotesNoteChangeState.REVISED not in states
        result = GoodNotesNewOnlyDelivery().deliver(
            A, run_id, DESTINATION, repository=delivery, clock=lambda: LATER
        )
        assert result.receipt.suppressed is False
        assert result.receipt.body is not None
        assert "synthetic note" in result.receipt.body
        assert "follow up Thursday" not in result.receipt.body
        assert "follow up Tuesday" not in result.receipt.body
        assert "REVISED" not in result.receipt.body
        replay = GoodNotesNewOnlyDelivery().deliver(
            A, run_id, DESTINATION, repository=delivery, clock=lambda: LATER
        )
        assert replay.receipt.replayed is True
        assert replay.receipt.receipt_id == result.receipt.receipt_id


def test_no_new_run_writes_suppressed_receipt(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        delivery = PostgresGoodNotesDeliveryRepository(connection)
        run_id, _, _, _ = _plant(lineage, A, "none")
        GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_id,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_id),
            clock=lambda: LATER,
        )
        result = GoodNotesNewOnlyDelivery().deliver(
            A, run_id, DESTINATION, repository=delivery, clock=lambda: LATER
        )
        assert result.receipt.suppressed is True
        assert result.receipt.body is None
        stored = delivery.delivery_receipt(A, result.receipt.receipt_id)
        assert stored is not None
        assert stored.suppressed is True


def test_unique_exact_candidate_associates(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        delivery = PostgresGoodNotesDeliveryRepository(connection)
        run_id, page_id, _, _ = _plant(lineage, A, "assoc")
        before = _project_count(connection, A, name="Alpha Project")
        project_id = _project(connection, A, "Alpha Project")
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="assoc",
            schema_version="note-unit.v2",
            segments=(
                _segment(
                    x_min=0.1,
                    transcription="synthetic note",
                    ranked_candidates=({"rank": 1, "candidate": "Alpha Project"},),
                ),
            ),
        )
        GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_id,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_id),
            clock=lambda: LATER,
        )
        result = GoodNotesNewOnlyDelivery().deliver(
            A, run_id, DESTINATION, repository=delivery, clock=lambda: LATER
        )
        assert len(result.associations) == 1
        assert result.associations[0].resolution is GoodNotesEntityResolution.ASSOCIATED
        assert result.associations[0].entity_kind is GoodNotesEntityKind.PROJECT
        assert result.associations[0].resolved_id == project_id
        assert _project_count(connection, A, name="Alpha Project") == before + 1


def test_ambiguous_name_stays_unresolved_and_does_not_create_a_project(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        delivery = PostgresGoodNotesDeliveryRepository(connection)
        run_id, page_id, _, _ = _plant(lineage, A, "ambig")
        _project(connection, A, "Shared Name")
        _project(connection, A, "Shared Name")
        before = _project_count(connection, A, name="Shared Name")
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="ambig",
            schema_version="note-unit.v2",
            segments=(
                _segment(
                    x_min=0.1,
                    transcription="synthetic heading",
                    ranked_candidates=({"rank": 1, "candidate": "Shared Name"},),
                ),
            ),
        )
        GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_id,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_id),
            clock=lambda: LATER,
        )
        result = GoodNotesNewOnlyDelivery().deliver(
            A, run_id, DESTINATION, repository=delivery, clock=lambda: LATER
        )
        assert len(result.associations) == 1
        assert result.associations[0].resolution is GoodNotesEntityResolution.UNRESOLVED
        assert result.associations[0].resolved_id is None
        assert _project_count(connection, A, name="Shared Name") == before == 2


def test_mixed_page_candidates_do_not_cross_contaminate(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        delivery = PostgresGoodNotesDeliveryRepository(connection)
        run_id, page_id, _, _ = _plant(lineage, A, "mixed")
        alpha = _project(connection, A, "Mixed Alpha Project")
        beta = _project(connection, A, "Mixed Beta Project")
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="mixed",
            schema_version="note-unit.v2",
            segments=(
                _segment(
                    x_min=0.1,
                    transcription="synthetic left",
                    ranked_candidates=({"rank": 1, "candidate": "Mixed Alpha Project"},),
                ),
                _segment(
                    x_min=0.6,
                    transcription="synthetic right",
                    ranked_candidates=({"rank": 1, "candidate": "Mixed Beta Project"},),
                ),
            ),
        )
        reconciled = GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_id,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_id),
            clock=lambda: LATER,
        )
        result = GoodNotesNewOnlyDelivery().deliver(
            A, run_id, DESTINATION, repository=delivery, clock=lambda: LATER
        )
        notes = {
            change.note_id: lineage.latest_revision_for_occurrence(A, change.occurrence_id)
            for change in reconciled.changes
            if change.note_id is not None and change.occurrence_id is not None
        }
        left_id = next(
            note_id
            for note_id, revision in notes.items()
            if revision and revision.transcription == "synthetic left"
        )
        right_id = next(
            note_id
            for note_id, revision in notes.items()
            if revision and revision.transcription == "synthetic right"
        )
        by_note = {item.note_id: item for item in result.associations}
        assert by_note[left_id].candidate == "Mixed Alpha Project"
        assert by_note[left_id].resolved_id == alpha
        assert by_note[right_id].candidate == "Mixed Beta Project"
        assert by_note[right_id].resolved_id == beta
        assert {item.candidate for item in result.associations if item.note_id == left_id} == {
            "Mixed Alpha Project"
        }
        assert {item.candidate for item in result.associations if item.note_id == right_id} == {
            "Mixed Beta Project"
        }


def test_v1_page_level_candidates_do_not_contaminate_two_note_units(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        delivery = PostgresGoodNotesDeliveryRepository(connection)
        run_id, page_id, _, _ = _plant(lineage, A, "v1mix")
        before = _project_count(connection, A, name="V1 Mix Project")
        _project(connection, A, "V1 Mix Project")
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="v1mix",
            schema_version="note-unit.v1",
            segments=(
                _segment(x_min=0.1, transcription="synthetic left"),
                _segment(x_min=0.6, transcription="synthetic right"),
            ),
            ranked_candidates=({"rank": 1, "candidate": "V1 Mix Project"},),
        )
        GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_id,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_id),
            clock=lambda: LATER,
        )
        result = GoodNotesNewOnlyDelivery().deliver(
            A, run_id, DESTINATION, repository=delivery, clock=lambda: LATER
        )
        assert result.associations == ()
        assert _project_count(connection, A, name="V1 Mix Project") == before + 1


def test_unreadable_does_not_become_fabricated_new_transcription(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        delivery = PostgresGoodNotesDeliveryRepository(connection)
        run_id, page_id, _, _ = _plant(lineage, A, "unreadable")
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="unreadable",
            schema_version="note-unit.v2",
            segments=(
                _segment(
                    x_min=0.1,
                    transcription="invented text",
                    transcription_status="UNREADABLE",
                ),
            ),
        )
        reconciled = GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_id,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_id),
            clock=lambda: LATER,
        )
        assert {item.change_state for item in reconciled.changes} == {
            GoodNotesNoteChangeState.AMBIGUOUS
        }
        assert all(item.note_id is None for item in reconciled.changes)
        revisions = connection.execute(
            text(
                "SELECT count(*) FROM knowledge.goodnotes_note_revisions "
                "WHERE principal_id = :principal AND transcription = :text"
            ),
            {"principal": A, "text": "invented text"},
        ).scalar_one()
        assert int(revisions) == 0
        result = GoodNotesNewOnlyDelivery().deliver(
            A, run_id, DESTINATION, repository=delivery, clock=lambda: LATER
        )
        assert result.receipt.suppressed is True
        assert result.associations == ()


def test_historical_summary_stays_bound_after_a_later_correction(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        delivery = PostgresGoodNotesDeliveryRepository(connection)
        run_id, page_id, _, _ = _plant(lineage, A, "bound-rev")
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="bound-rev",
            segments=(_segment(x_min=0.1, transcription="synthetic original"),),
        )
        reconciled = GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_id,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_id),
            clock=lambda: LATER,
        )
        new_changes = tuple(
            item for item in reconciled.changes if item.change_state is GoodNotesNoteChangeState.NEW
        )
        assert len(new_changes) == 1
        assert new_changes[0].revision_id is not None
        assert new_changes[0].occurrence_id is not None
        first = GoodNotesNewOnlyDelivery().deliver(
            A, run_id, DESTINATION, repository=delivery, clock=lambda: LATER
        )
        assert first.receipt.body is not None
        assert "synthetic original" in first.receipt.body
        corrected = GoodNotesCorrectionService().apply(
            A,
            new_changes[0].occurrence_id,
            transcription="synthetic corrected",
            repository=lineage,
            clock=lambda: CORRECTED,
        )
        assert corrected.revision.transcription == "synthetic corrected"
        latest = lineage.latest_revision_for_occurrence(A, new_changes[0].occurrence_id)
        assert latest is not None
        assert latest.transcription == "synthetic corrected"
        assert latest.revision_id != new_changes[0].revision_id
        second = GoodNotesNewOnlyDelivery().deliver(
            A, run_id, DESTINATION, repository=delivery, clock=lambda: LATER
        )
        assert second.receipt.replayed is True
        assert second.receipt.receipt_id == first.receipt.receipt_id
        assert second.receipt.summary_hash == first.receipt.summary_hash
        assert second.receipt.body == first.receipt.body
        assert "synthetic corrected" not in (second.receipt.body or "")


def test_null_revision_id_does_not_use_latest_at_delivery(engine: Engine) -> None:
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        delivery = PostgresGoodNotesDeliveryRepository(connection)
        run_id, _, notebook_id, logical_id = _plant(lineage, A, "legacy-null")
        note = lineage.store_note(
            GoodNotesNote(
                note_id=issue_stable_id("gnnt", A, "legacy-null"),
                principal_id=A,
                notebook_id=notebook_id,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=WHEN,
                last_seen_at=WHEN,
            )
        )
        occurrence = lineage.store_occurrence(
            GoodNotesNoteOccurrence(
                occurrence_id=issue_stable_id("gnocc", A, "legacy-null"),
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
        first = lineage.store_revision(
            GoodNotesNoteRevision(
                revision_id=issue_stable_id("gnrev", A, "legacy-null-first"),
                principal_id=A,
                note_id=note.note_id,
                schema_version="note-unit.v1",
                analyzer_name="synthetic",
                analyzer_version="1",
                transcription="synthetic original",
                created_at=WHEN,
                occurrence_id=occurrence.occurrence_id,
            )
        )
        lineage.store_revision(
            GoodNotesNoteRevision(
                revision_id=issue_stable_id("gnrev", A, "legacy-null-later"),
                principal_id=A,
                note_id=note.note_id,
                schema_version="note-unit.v1",
                analyzer_name="operator-correction",
                analyzer_version="1",
                transcription="synthetic corrected",
                created_at=LATER,
                occurrence_id=occurrence.occurrence_id,
                supersedes_revision_id=first.revision_id,
            )
        )
        lineage.store_run_note_change(
            GoodNotesRunNoteChange(
                change_id=issue_stable_id("gnchg", A, "legacy-null"),
                principal_id=A,
                run_id=run_id,
                note_id=note.note_id,
                occurrence_id=occurrence.occurrence_id,
                change_state=GoodNotesNoteChangeState.NEW,
                created_at=WHEN,
            )
        )
        latest = lineage.latest_revision_for_occurrence(A, occurrence.occurrence_id)
        assert latest is not None
        assert latest.transcription == "synthetic corrected"
        with pytest.raises(ValueError, match="no stored GoodNotes note revision"):
            GoodNotesNewOnlyDelivery().deliver(
                A, run_id, DESTINATION, repository=delivery, clock=lambda: LATER
            )


def test_attempt_crash_windows_do_not_duplicate_notes(engine: Engine) -> None:
    window = "crash-window"
    with engine.begin() as connection:
        lineage = PostgresGoodNotesRepository(connection)
        semantics = SqlGoodNotesSemanticRepository(connection)
        run_id, page_id, _, _ = _plant(lineage, A, "crash-win")
        _propose(
            semantics,
            principal_id=A,
            run_id=run_id,
            page_version_id=page_id,
            key="crash-win",
            segments=(_segment(x_min=0.1, transcription="synthetic note"),),
        )
        GoodNotesOccurrenceReconciler().reconcile(
            A,
            run_id,
            repository=lineage,
            promotion_evidence=_accepted_evidence(lineage, A, run_id),
            clock=lambda: LATER,
        )
        notes = connection.execute(
            text(
                "SELECT count(DISTINCT note_id) FROM knowledge.goodnotes_run_note_changes "
                "WHERE principal_id = :principal AND run_id = :run AND note_id IS NOT NULL"
            ),
            {"principal": A, "run": run_id},
        ).scalar_one()
        changes = connection.execute(
            text(
                "SELECT count(*) FROM knowledge.goodnotes_run_note_changes "
                "WHERE principal_id = :principal AND run_id = :run"
            ),
            {"principal": A, "run": run_id},
        ).scalar_one()
        revisions = connection.execute(
            text(
                "SELECT count(*) FROM knowledge.goodnotes_note_revisions "
                "WHERE principal_id = :principal AND occurrence_id IN ("
                " SELECT occurrence_id FROM knowledge.goodnotes_run_note_changes"
                " WHERE principal_id = :principal AND run_id = :run"
                " AND occurrence_id IS NOT NULL)"
            ),
            {"principal": A, "run": run_id},
        ).scalar_one()

    ledger = GoodNotesDeliveryAttemptLedger()
    with engine.begin() as connection:
        delivery = PostgresGoodNotesDeliveryRepository(connection)
        prepared = ledger.record(
            A,
            run_id,
            DESTINATION,
            window,
            GoodNotesDeliveryAttemptState.PREPARED,
            repository=delivery,
            clock=lambda: LATER,
        )
        assert prepared.state is GoodNotesDeliveryAttemptState.PREPARED
        assert delivery.delivery_receipt_by_key(A, run_id, DESTINATION, "0" * 64) is None

    with engine.begin() as connection:
        delivery = PostgresGoodNotesDeliveryRepository(connection)
        sent = ledger.record(
            A,
            run_id,
            DESTINATION,
            window,
            GoodNotesDeliveryAttemptState.SENT,
            repository=delivery,
            clock=lambda: LATER,
        )
        assert sent.state is GoodNotesDeliveryAttemptState.SENT
        windows = {item.state for item in delivery.delivery_attempts_for_token(A, window)}
        assert windows == {
            GoodNotesDeliveryAttemptState.PREPARED,
            GoodNotesDeliveryAttemptState.SENT,
        }

    with engine.begin() as connection:
        delivery = PostgresGoodNotesDeliveryRepository(connection)
        result = GoodNotesNewOnlyDelivery().deliver(
            A, run_id, DESTINATION, repository=delivery, clock=lambda: LATER
        )
        acknowledged = ledger.record(
            A,
            run_id,
            DESTINATION,
            window,
            GoodNotesDeliveryAttemptState.ACKNOWLEDGED,
            repository=delivery,
            clock=lambda: LATER,
            summary_hash=result.receipt.summary_hash,
            receipt_id=result.receipt.receipt_id,
        )
        replay = GoodNotesNewOnlyDelivery().deliver(
            A, run_id, DESTINATION, repository=delivery, clock=lambda: LATER
        )
        replayed = ledger.record(
            A,
            run_id,
            DESTINATION,
            window,
            GoodNotesDeliveryAttemptState.ACKNOWLEDGED,
            repository=delivery,
            clock=lambda: LATER,
            summary_hash=result.receipt.summary_hash,
            receipt_id=result.receipt.receipt_id,
        )
        assert replay.receipt.replayed is True
        assert replay.receipt.receipt_id == result.receipt.receipt_id
        assert replayed.attempt_id == acknowledged.attempt_id
        assert (
            connection.execute(
                text(
                    "SELECT count(DISTINCT note_id) FROM knowledge.goodnotes_run_note_changes "
                    "WHERE principal_id = :principal AND run_id = :run AND note_id IS NOT NULL"
                ),
                {"principal": A, "run": run_id},
            ).scalar_one()
            == notes
        )
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM knowledge.goodnotes_run_note_changes "
                    "WHERE principal_id = :principal AND run_id = :run"
                ),
                {"principal": A, "run": run_id},
            ).scalar_one()
            == changes
        )
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM knowledge.goodnotes_note_revisions "
                    "WHERE principal_id = :principal AND occurrence_id IN ("
                    " SELECT occurrence_id FROM knowledge.goodnotes_run_note_changes"
                    " WHERE principal_id = :principal AND run_id = :run"
                    " AND occurrence_id IS NOT NULL)"
                ),
                {"principal": A, "run": run_id},
            ).scalar_one()
            == revisions
        )
        receipts = connection.execute(
            text(
                "SELECT count(*) FROM knowledge.goodnotes_delivery_receipts "
                "WHERE principal_id = :principal AND run_id = :run"
            ),
            {"principal": A, "run": run_id},
        ).scalar_one()
        assert int(receipts) == 1
        windows = {item.state for item in delivery.delivery_attempts_for_token(A, window)}
        assert windows == {
            GoodNotesDeliveryAttemptState.PREPARED,
            GoodNotesDeliveryAttemptState.SENT,
            GoodNotesDeliveryAttemptState.ACKNOWLEDGED,
        }


@pytest.fixture
def engine(db_engine: Engine) -> Engine:
    return db_engine
