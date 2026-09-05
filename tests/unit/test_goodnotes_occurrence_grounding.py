"""Server-grounded NOTE_UNIT novelty. Agent crop is never canonical identity."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from my_pa.application.goodnotes_delivery import GoodNotesNewOnlyDelivery
from my_pa.application.goodnotes_occurrences import (
    GoodNotesOccurrenceReconciler,
    GoodNotesSemanticPromotionEvidence,
    _note_units,
    match_occurrences,
)
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


def _accepted_evidence(
    store: MemoryDurableNoteStore, run_id: str
) -> tuple[GoodNotesSemanticPromotionEvidence, ...]:
    if (A, run_id) not in store._promotions:
        for proposal in store.semantic_proposals_for_run(A, run_id):
            store.review_semantic_proposal(A, run_id, proposal[0])
    return ()


def test_missing_raster_blocks_canonical_admission_but_classifies_visual_ambiguity() -> None:
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
    _accepted_evidence(store, run_id)
    reconciler = GoodNotesOccurrenceReconciler()
    with pytest.raises(ValueError, match="lacks complete server review evidence"):
        reconciler.reconcile(A, run_id, repository=store, clock=lambda: LATER)
    assert store._notes == {}
    assert store._occurrences == {}
    assert store._revisions == {}
    assert store._links == {}
    assert store._changes == {}
    assert store._promotions == {}

    # The lower-level visual classification still treats an ungrounded crop as
    # ambiguous. Exercise that unit in isolation; this is not canonical admission.
    proposal = store.semantic_proposals_for_run(A, run_id)[0]
    version = store.page_version(A, page_id)
    assert version is not None and version.logical_page_id is not None
    snapshot = store.snapshots_for_run(A, run_id)[0]
    current = _note_units(
        payload=proposal[4],
        page_version_id=page_id,
        logical_page_id=version.logical_page_id,
        snapshot_id=snapshot.snapshot_id,
        schema_version=proposal[1],
        analyzer_name=proposal[2],
        analyzer_version=proposal[3],
        png_bytes=None,
    )
    assert len(current) == 1 and not current[0].visual_verified
    changes = reconciler._persist(
        principal_id=A,
        run_id=run_id,
        notebook_id=snapshot.notebook_id,
        matches=match_occurrences(current=current, prior=()),
        repository=store,
        now=LATER,
    )
    assert [item.change_state for item in changes] == [GoodNotesNoteChangeState.AMBIGUOUS]
    assert changes[0].note_id is None
    assert changes[0].occurrence_id is None
    assert changes[0].page_version_id == page_id
    assert store._notes == {}
    assert store._promotions == {}


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
        A,
        run_id,
        repository=store,
        clock=lambda: LATER,
        promotion_evidence=_accepted_evidence(store, run_id),
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
        A,
        run_id,
        repository=store,
        clock=lambda: LATER,
        promotion_evidence=_accepted_evidence(store, run_id),
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
        A,
        first_run,
        repository=store,
        clock=lambda: LATER,
        promotion_evidence=_accepted_evidence(store, first_run),
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
        A,
        second_run,
        repository=store,
        clock=lambda: LATER,
        promotion_evidence=_accepted_evidence(store, second_run),
    )
    assert GoodNotesNoteChangeState.NEW not in {item.change_state for item in second.changes}
    assert len(store._notes) == 1
    assert second.changes[0].occurrence_id == first.changes[0].occurrence_id


def test_transcription_only_is_unchanged_with_revision() -> None:
    png = _ink_png()
    store = MemoryDurableNoteStore()
    run_id, page_id, notebook_id, logical_id = _plant(store, "transcript", png=png)
    store.store_semantic_proposal(
        A,
        run_id,
        page_id,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.1, transcription="follow up Tuesday")]},
    )
    _accepted_evidence(store, run_id)
    first = GoodNotesOccurrenceReconciler().reconcile(
        A, run_id, repository=store, clock=lambda: WHEN
    )
    occurrence = store._occurrences[(A, first.changes[0].occurrence_id)]
    original = store.latest_revision_for_occurrence(A, occurrence.occurrence_id)
    assert original is not None
    run_id, page_id = _next_version(
        store, key="transcript-next", notebook_id=notebook_id, logical_id=logical_id, png=png
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
        A,
        run_id,
        repository=store,
        clock=lambda: LATER,
        promotion_evidence=_accepted_evidence(store, run_id),
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
        A,
        first_run,
        repository=store,
        clock=lambda: LATER,
        promotion_evidence=_accepted_evidence(store, first_run),
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
        A,
        second_run,
        repository=store,
        clock=lambda: LATER,
        promotion_evidence=_accepted_evidence(store, second_run),
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
        A,
        first_run,
        repository=store,
        clock=lambda: LATER,
        promotion_evidence=_accepted_evidence(store, first_run),
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
        A,
        run_id,
        repository=store,
        clock=lambda: LATER,
        promotion_evidence=_accepted_evidence(store, run_id),
    )
    assert [item.change_state for item in result.changes] == [GoodNotesNoteChangeState.AMBIGUOUS]
    assert result.changes[0].note_id is None
    assert result.changes[0].occurrence_id is None
    assert store._notes == {}
    assert store._revisions == {}
    assert "invented text" not in repr(result)


def test_cross_page_move_preserves_identity_history_and_suppresses_new_delivery() -> None:
    png = _ink_png()
    store = MemoryDurableNoteStore()
    first_run, first_page, notebook_id, first_logical = _plant(store, "move-first", png=png)
    payload: dict[str, object] = {"segments": [_segment(x_min=0.1, transcription="same ink")]}
    store.store_semantic_proposal(
        A, first_run, first_page, "note-unit.v1", "synthetic", "1", payload
    )
    reconciler = GoodNotesOccurrenceReconciler()
    first = reconciler.reconcile(
        A,
        first_run,
        repository=store,
        clock=lambda: LATER,
        promotion_evidence=_accepted_evidence(store, first_run),
    )
    original = first.changes[0]
    assert original.note_id is not None and original.occurrence_id is not None
    old_revision = store.latest_revision_for_occurrence(A, original.occurrence_id)
    target = store.store_logical_page(
        GoodNotesLogicalPage(
            logical_page_id=issue_stable_id("gnlp", A, "move-target"),
            principal_id=A,
            notebook_id=notebook_id,
            created_at=WHEN,
            last_seen_at=WHEN,
            identity_status=GoodNotesIdentityStatus.ACTIVE,
        )
    )
    run_id, version_id = _next_version(
        store,
        key="move-second",
        notebook_id=notebook_id,
        logical_id=target.logical_page_id,
        png=png,
    )
    store.store_semantic_proposal(A, run_id, version_id, "note-unit.v1", "synthetic", "1", payload)
    result = reconciler.reconcile(
        A,
        run_id,
        repository=store,
        clock=lambda: LATER + timedelta(minutes=1),
        promotion_evidence=_accepted_evidence(store, run_id),
    )
    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.change_state is GoodNotesNoteChangeState.REVISED
    assert (change.note_id, change.occurrence_id) == (original.note_id, original.occurrence_id)
    occurrence = store.occurrence(A, original.occurrence_id)
    assert occurrence is not None
    assert occurrence.logical_page_id == target.logical_page_id
    assert occurrence.page_version_id == version_id
    revision = store.latest_revision_for_occurrence(A, original.occurrence_id)
    assert revision is not None and old_revision is not None
    assert revision.supersedes_revision_id == old_revision.revision_id
    assert revision.page_version_id == version_id
    assert {link.target_logical_page_id for link in store._links.values()} == {
        first_logical,
        target.logical_page_id,
    }
    replay = reconciler.reconcile(A, run_id, repository=store, clock=lambda: LATER)
    assert replay.replayed and replay.changes == result.changes
    delivery = GoodNotesNewOnlyDelivery().deliver(
        A, run_id, "operator-local", repository=store, clock=lambda: LATER
    )
    assert delivery.receipt.body is None
    assert delivery.receipt.suppressed
    replayed_delivery = GoodNotesNewOnlyDelivery().deliver(
        A, run_id, "operator-local", repository=store, clock=lambda: LATER
    )
    assert replayed_delivery.receipt.receipt_id == delivery.receipt.receipt_id

    links_before_return = dict(store._links)
    return_run, return_version = _next_version(
        store,
        key="move-return",
        notebook_id=notebook_id,
        logical_id=first_logical,
        png=png,
    )
    store.store_semantic_proposal(
        A, return_run, return_version, "note-unit.v1", "synthetic", "1", payload
    )
    _accepted_evidence(store, return_run)
    returned = reconciler.reconcile(
        A, return_run, repository=store, clock=lambda: LATER + timedelta(minutes=2)
    )
    assert len(returned.changes) == 1
    returning_change = returned.changes[0]
    assert returning_change.change_state is GoodNotesNoteChangeState.REVISED
    assert (returning_change.note_id, returning_change.occurrence_id) == (
        original.note_id,
        original.occurrence_id,
    )
    returned_occurrence = store.occurrence(A, original.occurrence_id)
    assert returned_occurrence is not None
    assert returned_occurrence.logical_page_id == first_logical
    assert returned_occurrence.page_version_id == return_version
    returned_revision = store.latest_revision_for_occurrence(A, original.occurrence_id)
    assert returned_revision is not None
    assert returned_revision.supersedes_revision_id == revision.revision_id
    assert store._links == links_before_return
    assert reconciler.reconcile(A, return_run, repository=store).changes == returned.changes
    return_delivery = GoodNotesNewOnlyDelivery().deliver(
        A, return_run, "operator-local", repository=store, clock=lambda: LATER
    )
    assert return_delivery.receipt.suppressed and return_delivery.receipt.body is None


def test_retired_destination_refuses_before_canonical_writes() -> None:
    png = _ink_png()
    store = MemoryDurableNoteStore()
    run_id, page_id, notebook_id, logical_id = _plant(store, "occupied", png=png)
    note = store.store_note(
        GoodNotesNote(
            note_id=issue_stable_id("gnnt", A, "occupied"),
            principal_id=A,
            notebook_id=notebook_id,
            identity_status=GoodNotesIdentityStatus.RETIRED,
            created_at=WHEN,
            last_seen_at=WHEN,
        )
    )
    prior = store.store_occurrence(
        GoodNotesNoteOccurrence(
            occurrence_id=issue_stable_id("gnocc", A, "occupied"),
            principal_id=A,
            note_id=note.note_id,
            logical_page_id=logical_id,
            x_min=0.1,
            y_min=0.2,
            width=0.2,
            height=0.1,
            crop_sha256=crop_normalized_png(png, 0.1, 0.2, 0.2, 0.1).digest,
            identity_status=GoodNotesIdentityStatus.RETIRED,
            created_at=WHEN,
            last_seen_at=WHEN,
        )
    )
    store.store_semantic_proposal(
        A,
        run_id,
        page_id,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.1, transcription="same ink")]},
    )
    _accepted_evidence(store, run_id)
    with pytest.raises(ValueError, match="destination is ambiguous"):
        GoodNotesOccurrenceReconciler().reconcile(A, run_id, repository=store, clock=lambda: LATER)
    assert store.occurrence(A, prior.occurrence_id) == prior
    assert store.run_note_changes(A, run_id) == ()
    assert store.latest_revision_for_occurrence(A, prior.occurrence_id) is None
    assert store.accepted_semantic_material(A, run_id, require_promoted=True) is None


def _date_plane(value: str) -> dict[str, object]:
    return {
        "page_candidates": [
            {"scope": "PAGE", "value": value, "literal": value, "evidence_refs": ["header"]}
        ]
    }


@pytest.mark.parametrize(
    "prior_dates,current_dates",
    [
        ({}, {}),
        ({}, _date_plane("2026-09-05")),
        (_date_plane("2026-09-05"), _date_plane("2026-09-06")),
        (_date_plane("2026-09-05"), {}),
    ],
)
def test_date_only_revision_uses_last_revision_not_ambiguous_run_pointer(
    prior_dates: dict[str, object], current_dates: dict[str, object]
) -> None:
    from dataclasses import replace

    from my_pa.domain.capture.review import Disposition

    store = MemoryDurableNoteStore()
    first_run, page, notebook, logical = _plant(store, "date-first", png=_ink_png())
    payload = {
        "segments": [_segment(x_min=0.1, transcription="same ink")],
        "date_evidence": prior_dates,
    }
    store.store_semantic_proposal(A, first_run, page, "note-unit.v1", "synthetic", "1", payload)
    _accepted_evidence(store, first_run)
    first = GoodNotesOccurrenceReconciler().reconcile(
        A, first_run, repository=store, clock=lambda: WHEN
    )
    occurrence_id = first.changes[0].occurrence_id
    assert occurrence_id is not None
    original = store.latest_revision_for_occurrence(A, occurrence_id)
    assert original is not None
    run, page = _next_version(
        store, key="date-next", notebook_id=notebook, logical_id=logical, png=_ink_png()
    )
    # AMBIGUOUS bookkeeping may point at an unrelated, unpromoted run.
    occurrence = store._occurrences[(A, occurrence_id)]
    store.store_occurrence(
        replace(
            occurrence,
            identity_status=GoodNotesIdentityStatus.AMBIGUOUS,
            run_id=issue_stable_id("gnrun", A, "ambiguous"),
        )
    )
    store.store_semantic_proposal(A, run, page, "note-unit.v1", "synthetic", "1", payload)
    store.review_semantic_proposal(
        A, run, page, Disposition.CORRECT_AND_ACCEPT, {**payload, "date_evidence": current_dates}
    )
    result = GoodNotesOccurrenceReconciler().reconcile(
        A, run, repository=store, clock=lambda: LATER
    )
    changed = prior_dates != current_dates
    assert result.changes[0].change_state is (
        GoodNotesNoteChangeState.REVISED if changed else GoodNotesNoteChangeState.UNCHANGED
    )
    latest = store.latest_revision_for_occurrence(A, occurrence_id)
    assert latest is not None
    if changed:
        assert latest.supersedes_revision_id == original.revision_id
        assert latest.page_version_id == page
        assert latest.transcription == original.transcription
    else:
        assert latest == original
    assert store._revisions[(A, original.revision_id)] == original
    assert GoodNotesOccurrenceReconciler().reconcile(A, run, repository=store).replayed
    assert (
        GoodNotesNewOnlyDelivery()
        .deliver(A, run, "operator-local", repository=store)
        .receipt.suppressed
    )


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_snapshot",
        "wrong_principal",
        "wrong_notebook",
        "membership",
        "unpromoted",
        "tampered",
    ],
)
def test_prior_date_provenance_fails_closed(corruption: str) -> None:
    from dataclasses import replace

    from my_pa.application.goodnotes_occurrences import _prior_date_digest

    store = MemoryDurableNoteStore()
    run, page, _, _ = _plant(store, "date-refusal", png=_ink_png())
    store.store_semantic_proposal(
        A,
        run,
        page,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.1, transcription="same ink")]},
    )
    _accepted_evidence(store, run)
    first = GoodNotesOccurrenceReconciler().reconcile(A, run, repository=store, clock=lambda: WHEN)
    occurrence_id = first.changes[0].occurrence_id
    assert occurrence_id is not None
    occurrence = store._occurrences[(A, occurrence_id)]
    revision = store.latest_revision_for_occurrence(A, occurrence_id)
    assert revision is not None and revision.snapshot_id is not None
    snapshot_key = (A, revision.snapshot_id)
    snapshot = store._snapshots[snapshot_key]
    if corruption == "missing_snapshot":
        del store._snapshots[snapshot_key]
    elif corruption == "wrong_principal":
        store._snapshots[snapshot_key] = replace(
            snapshot, principal_id="prn_bbbbbbbbbbbbbbbbbbbbbbbb"
        )
    elif corruption == "wrong_notebook":
        store._snapshots[snapshot_key] = replace(
            snapshot, notebook_id=issue_stable_id("gnnb", A, "wrong")
        )
    elif corruption == "membership":
        store._positions.clear()
    elif corruption == "unpromoted":
        store._promotions.clear()
    else:
        key = (A, run, page)
        store._reviews[key] = replace(
            store._reviews[key], payload={"date_evidence": _date_plane("2026-09-06")}
        )
    with pytest.raises(ValueError):
        _prior_date_digest(A, occurrence, revision, store)
