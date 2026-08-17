"""Server-grounded NOTE_UNIT novelty. Agent crop is never canonical identity."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from my_pa.application.goodnotes_occurrences import GoodNotesOccurrenceReconciler
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
    GoodNotesSourceSnapshot,
    issue_stable_id,
)
from my_pa.domain.goodnotes.page_crop import aligned_crop_box, crop_normalized_png
from my_pa.infrastructure.goodnotes.visual import grayscale_png
from tests.unit.goodnotes_durable_note_memory import MemoryDurableNoteStore

WHEN = datetime(2026, 8, 16, 21, 0, tzinfo=UTC)
LATER = WHEN + timedelta(hours=1)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
AGENT_CROP = "a" * 64
OTHER_AGENT_CROP = "b" * 64
FINGERPRINT = "c" * 64
DIGEST = hashlib.sha256(b"synthetic-grounding-page").hexdigest()


def _ink_png(
    *,
    width: int = 80,
    height: int = 80,
    boxes: tuple[tuple[float, float, float, float], ...] = ((0.1, 0.2, 0.2, 0.1),),
    ink: int = 10,
) -> bytes:
    pixels = bytearray([255] * width * height)
    for x_min, y_min, box_width, box_height in boxes:
        x0, y0, x1, y1 = aligned_crop_box(x_min, y_min, box_width, box_height, width, height)
        for row in range(y0, y1):
            for column in range(x0, x1):
                pixels[row * width + column] = ink
    return grayscale_png(bytes(pixels), width, height)


def _blank_png(*, width: int = 80, height: int = 80) -> bytes:
    return grayscale_png(bytes([255] * width * height), width, height)


def _plant(
    store: MemoryDurableNoteStore,
    token: str,
    *,
    png: bytes | None,
    logical_token: str | None = None,
) -> tuple[str, str, str, str]:
    notebook = store.store_notebook(
        GoodNotesNotebook(
            notebook_id=issue_stable_id("gnnb", A, token),
            principal_id=A,
            source_root_id="icloud-goodnotes",
            identity_status=GoodNotesIdentityStatus.ACTIVE,
            created_at=WHEN,
            last_observed_at=WHEN,
            label=token,
        )
    )
    page_token = logical_token or token
    logical = store.store_logical_page(
        GoodNotesLogicalPage(
            logical_page_id=issue_stable_id("gnlp", A, page_token),
            principal_id=A,
            notebook_id=notebook.notebook_id,
            created_at=WHEN,
            last_seen_at=WHEN,
            identity_status=GoodNotesIdentityStatus.ACTIVE,
        )
    )
    run = store.create_run(
        GoodNotesIngestionRun(
            run_id=issue_stable_id("gnrun", A, token),
            principal_id=A,
            source_root_id="icloud-goodnotes",
            trigger_type=GoodNotesIngestionTrigger.MANUAL,
            request_id=f"req-{token}",
            idempotency_key=f"req-{token}",
            request_fingerprint=FINGERPRINT,
            started_at=WHEN,
            status=GoodNotesIngestionStatus.RUNNING,
        )
    )
    snapshot = store.store_snapshot(
        GoodNotesSourceSnapshot(
            snapshot_id=issue_stable_id("gnsnap", A, token),
            principal_id=A,
            notebook_id=notebook.notebook_id,
            source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
            observed_path=f"Inbox/{token}.pdf",
            raw_sha256=hashlib.sha256(f"{A}:{token}".encode()).hexdigest(),
            size_bytes=32,
            page_count=1,
            observed_at=WHEN,
            settled_at=WHEN,
            run_id=run.run_id,
        )
    )
    page = GoodNotesPage(
        page_id=issue_stable_id("gnpg", A, token),
        principal_id=A,
        source_id="src_aaaaaaaaaaaaaaaaaaaaaaaa",
        source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
        page_number=1,
    )
    version = store.store_page_version_render(
        page=page,
        version=GoodNotesPageVersion(
            page_version_id=issue_stable_id("gnver", A, token),
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
    store.store_page_position(
        GoodNotesPagePosition(
            principal_id=A,
            snapshot_id=snapshot.snapshot_id,
            page_number=1,
            logical_page_id=logical.logical_page_id,
            created_at=WHEN,
            match_method=GoodNotesMatchMethod.ORDINAL_WEAK,
            page_version_id=version.page_version_id,
        )
    )
    if png is not None:
        store.store_page_raster(
            GoodNotesPageRaster(
                principal_id=A,
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


def _next_version(
    store: MemoryDurableNoteStore,
    *,
    key: str,
    notebook_id: str,
    logical_id: str,
    png: bytes,
) -> tuple[str, str]:
    run = store.create_run(
        GoodNotesIngestionRun(
            run_id=issue_stable_id("gnrun", A, key),
            principal_id=A,
            source_root_id="icloud-goodnotes",
            trigger_type=GoodNotesIngestionTrigger.MANUAL,
            request_id=f"req-{key}",
            idempotency_key=f"req-{key}",
            request_fingerprint=FINGERPRINT,
            started_at=WHEN,
            status=GoodNotesIngestionStatus.RUNNING,
        )
    )
    snapshot = store.store_snapshot(
        GoodNotesSourceSnapshot(
            snapshot_id=issue_stable_id("gnsnap", A, key),
            principal_id=A,
            notebook_id=notebook_id,
            source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
            observed_path=f"Inbox/{key}.pdf",
            raw_sha256=hashlib.sha256(f"{A}:{key}".encode()).hexdigest(),
            size_bytes=32,
            page_count=1,
            observed_at=WHEN,
            settled_at=WHEN,
            run_id=run.run_id,
        )
    )
    page = GoodNotesPage(
        page_id=issue_stable_id("gnpg", A, key),
        principal_id=A,
        source_id="src_aaaaaaaaaaaaaaaaaaaaaaaa",
        source_object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
        page_number=1,
    )
    version = store.store_page_version_render(
        page=page,
        version=GoodNotesPageVersion(
            page_version_id=issue_stable_id("gnver", A, key),
            page_id=page.page_id,
            source_version_id="ver_aaaaaaaaaaaaaaaaaaaaaaaa",
            content_sha256=DIGEST,
            observed_at=WHEN,
            logical_page_id=logical_id,
            renderer_name="synthetic",
            renderer_version="1",
            render_profile_version="v1",
        ),
    )
    store.store_page_position(
        GoodNotesPagePosition(
            principal_id=A,
            snapshot_id=snapshot.snapshot_id,
            page_number=1,
            logical_page_id=logical_id,
            created_at=WHEN,
            match_method=GoodNotesMatchMethod.ORDINAL_WEAK,
            page_version_id=version.page_version_id,
        )
    )
    store.store_page_raster(
        GoodNotesPageRaster(
            principal_id=A,
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
    return run.run_id, version.page_version_id


def _segment(
    *,
    x_min: float,
    transcription: str,
    crop_sha256: str | None = None,
    y_min: float = 0.2,
    width: float = 0.2,
    height: float = 0.1,
    transcription_status: str | None = None,
) -> dict[str, object]:
    values: dict[str, object] = {
        "kind": "NOTE_UNIT",
        "geometry": {"x_min": x_min, "y_min": y_min, "width": width, "height": height},
        "transcription": transcription,
        "primary_class": "MEETING",
    }
    if crop_sha256 is not None:
        values["crop_sha256"] = crop_sha256
    if transcription_status is not None:
        values["transcription_status"] = transcription_status
    return values


def test_hallucinated_crop_without_raster_is_ambiguous_ledger_not_new() -> None:
    store = MemoryDurableNoteStore()
    run_id, page_id, _, _ = _plant(store, "no-raster", png=None)
    store.store_semantic_proposal(
        A,
        run_id,
        page_id,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.1, transcription="ghost", crop_sha256=AGENT_CROP)]},
    )
    result = GoodNotesOccurrenceReconciler().reconcile(
        A, run_id, repository=store, clock=lambda: LATER
    )
    assert [item.change_state for item in result.changes] == [GoodNotesNoteChangeState.AMBIGUOUS]
    assert result.changes[0].note_id is None
    assert result.changes[0].occurrence_id is None
    assert result.changes[0].page_version_id == page_id
    assert store._notes == {}


def test_hallucinated_box_on_white_of_inked_page_is_ambiguous_not_new() -> None:
    png = _ink_png(boxes=((0.1, 0.2, 0.2, 0.1),))
    store = MemoryDurableNoteStore()
    run_id, page_id, _, _ = _plant(store, "white-box", png=png)
    store.store_semantic_proposal(
        A,
        run_id,
        page_id,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.6, transcription="ghost on white", crop_sha256=AGENT_CROP)]},
    )
    result = GoodNotesOccurrenceReconciler().reconcile(
        A, run_id, repository=store, clock=lambda: LATER
    )
    assert [item.change_state for item in result.changes] == [GoodNotesNoteChangeState.AMBIGUOUS]
    assert result.changes[0].note_id is None
    assert store._notes == {}


def test_blank_crop_is_ambiguous_not_new() -> None:
    store = MemoryDurableNoteStore()
    run_id, page_id, _, _ = _plant(store, "blank", png=_blank_png())
    store.store_semantic_proposal(
        A,
        run_id,
        page_id,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.1, transcription="empty", crop_sha256=AGENT_CROP)]},
    )
    result = GoodNotesOccurrenceReconciler().reconcile(
        A, run_id, repository=store, clock=lambda: LATER
    )
    assert [item.change_state for item in result.changes] == [GoodNotesNoteChangeState.AMBIGUOUS]
    assert result.changes[0].note_id is None
    assert store._notes == {}


def test_agent_crop_is_ignored_when_server_crop_matches() -> None:
    png = _ink_png()
    store = MemoryDurableNoteStore()
    first_run, first_page, notebook_id, logical_id = _plant(store, "agent-a", png=png)
    store.store_semantic_proposal(
        A,
        first_run,
        first_page,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.1, transcription="same ink", crop_sha256=AGENT_CROP)]},
    )
    first = GoodNotesOccurrenceReconciler().reconcile(
        A, first_run, repository=store, clock=lambda: LATER
    )
    assert [item.change_state for item in first.changes] == [GoodNotesNoteChangeState.NEW]
    server_digest = crop_normalized_png(png, 0.1, 0.2, 0.2, 0.1).digest
    stored = store.occurrence(A, first.changes[0].occurrence_id)  # type: ignore[arg-type]
    assert stored is not None
    assert stored.crop_sha256 == server_digest
    assert stored.crop_sha256 != AGENT_CROP

    second_run, second_page = _next_version(
        store, key="agent-b", notebook_id=notebook_id, logical_id=logical_id, png=png
    )
    store.store_semantic_proposal(
        A,
        second_run,
        second_page,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.1, transcription="same ink", crop_sha256=OTHER_AGENT_CROP)]},
    )
    second = GoodNotesOccurrenceReconciler().reconcile(
        A, second_run, repository=store, clock=lambda: LATER
    )
    assert GoodNotesNoteChangeState.NEW not in {item.change_state for item in second.changes}
    assert len(store._notes) == 1
    assert second.changes[0].occurrence_id == first.changes[0].occurrence_id


def test_transcription_only_is_unchanged_with_revision() -> None:
    png = _ink_png()
    store = MemoryDurableNoteStore()
    run_id, page_id, notebook_id, logical_id = _plant(store, "transcript", png=png)
    note = store.store_note(
        GoodNotesNote(
            note_id=issue_stable_id("gnnt", A, "transcript"),
            principal_id=A,
            notebook_id=notebook_id,
            identity_status=GoodNotesIdentityStatus.ACTIVE,
            created_at=WHEN,
            last_seen_at=WHEN,
        )
    )
    occurrence = store.store_occurrence(
        GoodNotesNoteOccurrence(
            occurrence_id=issue_stable_id("gnocc", A, "transcript"),
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
            crop_sha256=crop_normalized_png(png, 0.1, 0.2, 0.2, 0.1).digest,
        )
    )
    original = store.store_revision(
        GoodNotesNoteRevision(
            revision_id=issue_stable_id("gnrev", A, "transcript-first"),
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
    store.store_semantic_proposal(
        A,
        run_id,
        page_id,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.1, transcription="follow up Thursday")]},
    )
    result = GoodNotesOccurrenceReconciler().reconcile(
        A, run_id, repository=store, clock=lambda: LATER
    )
    assert [item.change_state for item in result.changes] == [GoodNotesNoteChangeState.UNCHANGED]
    latest = store.latest_revision_for_occurrence(A, occurrence.occurrence_id)
    assert latest is not None
    assert latest.revision_id != original.revision_id
    assert latest.transcription == "follow up Thursday"
    assert latest.page_version_id == page_id
    assert result.changes[0].revision_id == latest.revision_id


def test_visual_crop_change_is_revised() -> None:
    first_png = _ink_png(ink=10)
    second_png = _ink_png(ink=40)
    store = MemoryDurableNoteStore()
    first_run, first_page, notebook_id, logical_id = _plant(store, "ink-a", png=first_png)
    store.store_semantic_proposal(
        A,
        first_run,
        first_page,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.1, transcription="same words")]},
    )
    first = GoodNotesOccurrenceReconciler().reconcile(
        A, first_run, repository=store, clock=lambda: LATER
    )
    occurrence_id = first.changes[0].occurrence_id
    assert occurrence_id is not None

    second_run, second_page = _next_version(
        store,
        key="ink-b",
        notebook_id=notebook_id,
        logical_id=logical_id,
        png=second_png,
    )
    store.store_semantic_proposal(
        A,
        second_run,
        second_page,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.1, transcription="same words")]},
    )
    second = GoodNotesOccurrenceReconciler().reconcile(
        A, second_run, repository=store, clock=lambda: LATER
    )
    assert [item.change_state for item in second.changes] == [GoodNotesNoteChangeState.REVISED]
    assert second.changes[0].occurrence_id == occurrence_id


def test_deleted_logical_page_emits_removed() -> None:
    png = _ink_png()
    store = MemoryDurableNoteStore()
    first_run, first_page, notebook_id, cover_id = _plant(store, "keep", png=png)
    body = store.store_logical_page(
        GoodNotesLogicalPage(
            logical_page_id=issue_stable_id("gnlp", A, "gone"),
            principal_id=A,
            notebook_id=notebook_id,
            created_at=WHEN,
            last_seen_at=WHEN,
            identity_status=GoodNotesIdentityStatus.ACTIVE,
        )
    )
    note = store.store_note(
        GoodNotesNote(
            note_id=issue_stable_id("gnnt", A, "gone"),
            principal_id=A,
            notebook_id=notebook_id,
            identity_status=GoodNotesIdentityStatus.ACTIVE,
            created_at=WHEN,
            last_seen_at=WHEN,
        )
    )
    gone = store.store_occurrence(
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
    store.store_semantic_proposal(
        A,
        first_run,
        first_page,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.1, transcription="cover note")]},
    )
    result = GoodNotesOccurrenceReconciler().reconcile(
        A, first_run, repository=store, clock=lambda: LATER
    )
    states = {item.change_state: item for item in result.changes}
    assert GoodNotesNoteChangeState.REMOVED_OR_NO_LONGER_PRESENT in states
    removed = states[GoodNotesNoteChangeState.REMOVED_OR_NO_LONGER_PRESENT]
    assert removed.occurrence_id == gone.occurrence_id
    assert cover_id != body.logical_page_id
    stored = store.occurrence(A, gone.occurrence_id)
    assert stored is not None
    assert stored.identity_status is GoodNotesIdentityStatus.RETIRED


def test_unreadable_does_not_mint_fabricated_new_transcription() -> None:
    store = MemoryDurableNoteStore()
    run_id, page_id, _, _ = _plant(store, "unreadable", png=_ink_png())
    store.store_semantic_proposal(
        A,
        run_id,
        page_id,
        "note-unit.v2",
        "synthetic",
        "1",
        {
            "segments": [
                _segment(
                    x_min=0.1, transcription="invented text", transcription_status="UNREADABLE"
                )
            ]
        },
    )
    result = GoodNotesOccurrenceReconciler().reconcile(
        A, run_id, repository=store, clock=lambda: LATER
    )
    assert [item.change_state for item in result.changes] == [GoodNotesNoteChangeState.AMBIGUOUS]
    assert result.changes[0].note_id is None
    assert result.changes[0].occurrence_id is None
    assert store._notes == {}
    assert store._revisions == {}
    assert "invented text" not in repr(result)
