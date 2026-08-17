"""Named GoodNotes A-X acceptance corpus on the production page renderer.

High-risk acceptance is measured here with a fixed synthetic, non-personal
corpus through `PdfiumNormalizedRenderer` / `pdfium-normalized-v1`. Tests compose
existing visual, occurrence-grounding, and NEW-only delivery contracts rather
than injecting `MappedPageRenderer` hashes.

Letters this module asserts: A, B, C, D, I, J, Q, R, M, plus the repository-
provable release floors (regenerated false-new = 0, reordered false-new = 0,
fabricated unreadable = 0, NEW-only membership). T and X (live Teams/OAuth) and
live personal GoodNotes/NAS remain external.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace

from my_pa.application.goodnotes_delivery import (
    GoodNotesNewOnlyDelivery,
    build_new_only_summary,
)
from my_pa.application.goodnotes_occurrences import GoodNotesOccurrenceReconciler
from my_pa.domain.goodnotes.models import (
    GoodNotesEntityDirectoryRecord,
    GoodNotesEntityKind,
    GoodNotesMatchMethod,
    GoodNotesNoteChangeState,
    GoodNotesNoteClass,
    GoodNotesNoteRevision,
    issue_stable_id,
)
from my_pa.domain.goodnotes.page_crop import crop_normalized_png
from my_pa.infrastructure.goodnotes.pdf import split_admitted_pdf
from my_pa.infrastructure.goodnotes.render import (
    PDFIUM_NORMALIZED_PROFILE,
    MappedPageRenderer,
    PdfiumNormalizedRenderer,
    production_page_renderer,
)
from tests.unit.goodnotes_durable_note_memory import MemoryDurableNoteStore
from tests.unit.goodnotes_lineage_memory import MemoryLineageRepository
from tests.unit.test_goodnotes_delivery import (
    DESTINATION,
    RUN,
    _change,
    _FakeDeliveryRepository,
    _meeting_revision,
    _note,
    _occurrence,
    _run,
)
from tests.unit.test_goodnotes_delivery import LATER as DELIVERY_LATER
from tests.unit.test_goodnotes_delivery import WHEN as DELIVERY_WHEN
from tests.unit.test_goodnotes_delivery import A as DELIVERY_A
from tests.unit.test_goodnotes_occurrence_grounding import (
    AGENT_CROP,
    OTHER_AGENT_CROP,
    _ink_png,
    _next_version,
    _plant,
    _segment,
)
from tests.unit.test_goodnotes_occurrence_grounding import LATER as GROUNDING_LATER
from tests.unit.test_goodnotes_occurrence_grounding import A as GROUNDING_A
from tests.unit.test_goodnotes_visual_renderer import (
    BODY,
    COVER,
    SMALL_MARK,
    _reconcile,
    _sha,
)
from tests.unit.vector_pdf import Rect, vector_pdf

OBJECT_A = "obj_aaaaaaaaaaaaaaaaaaaaaa0a"
OBJECT_B = "obj_aaaaaaaaaaaaaaaaaaaaaa0b"
OBJECT_C = "obj_aaaaaaaaaaaaaaaaaaaaaa0c"
OBJECT_D = "obj_aaaaaaaaaaaaaaaaaaaaaa0d"


def _production() -> PdfiumNormalizedRenderer:
    renderer = production_page_renderer()
    assert isinstance(renderer, PdfiumNormalizedRenderer)
    assert renderer.profile_version == PDFIUM_NORMALIZED_PROFILE
    assert not isinstance(renderer, MappedPageRenderer)
    return renderer


def test_a_byte_different_visually_equivalent_pdfs_share_normalized_identity() -> None:
    """A / regenerated false-new = 0: producer/comment/dummy_objects churn is not a new page."""
    first = vector_pdf((COVER, BODY), producer="alpha", comment="first")
    second = vector_pdf((COVER, BODY), producer="beta", comment="regenerated", dummy_objects=4)
    assert first != second
    assert _sha(first) != _sha(second)
    renderer = _production()
    first_pages = split_admitted_pdf(first)
    second_pages = split_admitted_pdf(second)
    first_renders = tuple(renderer.render(page) for page in first_pages)
    second_renders = tuple(renderer.render(page) for page in second_pages)
    assert [item.normalized_render_sha256 for item in first_renders] == [
        item.normalized_render_sha256 for item in second_renders
    ]
    for render, raw in zip(first_renders, first_pages, strict=True):
        content_sha256 = hashlib.sha256(raw).hexdigest()
        assert content_sha256 == _sha(raw)
        assert render.normalized_render_sha256 != content_sha256
        assert render.exact_render_sha256 != content_sha256
        assert render.render_profile_version == PDFIUM_NORMALIZED_PROFILE
    repository = MemoryLineageRepository()
    first_result = _reconcile(
        first,
        object_id=OBJECT_A,
        request_id="corpus-a-1",
        path="Inbox/corpus-a.pdf",
        version_id="ver_aaaaaaaaaaaaaaaaaaaaaa0a",
        repository=repository,
    )
    second_result = _reconcile(
        second,
        object_id=OBJECT_A,
        request_id="corpus-a-2",
        path="Inbox/corpus-a.pdf",
        version_id="ver_aaaaaaaaaaaaaaaaaaaaaa0b",
        repository=repository,
    )
    assert first_result.notebook.notebook_id == second_result.notebook.notebook_id
    assert second_result.run.new_logical_page_count == 0
    assert {item.logical_page_id for item in first_result.matches} == {
        item.logical_page_id for item in second_result.matches
    }
    assert all(not item.is_new for item in second_result.matches)
    assert all(
        item.match_method is GoodNotesMatchMethod.EXACT_NORMALIZED_RENDER
        for item in second_result.matches
    )
    pages = repository.logical_pages(
        first_result.notebook.principal_id, first_result.notebook.notebook_id
    )
    assert len(pages) == 2


def test_b_append_adds_only_the_new_visual_page() -> None:
    """B: append allocates only the added visual page; prior pages keep identity."""
    original = vector_pdf((COVER, BODY), producer="append-a", comment="base")
    appended = vector_pdf(
        (COVER, BODY, (Rect(200, 200, 80, 80, 0.7),)),
        producer="append-b",
        comment="appended",
        dummy_objects=2,
    )
    repository = MemoryLineageRepository()
    first = _reconcile(
        original,
        object_id=OBJECT_B,
        request_id="corpus-b-1",
        path="Inbox/corpus-b.pdf",
        version_id="ver_aaaaaaaaaaaaaaaaaaaaaa0c",
        repository=repository,
    )
    second = _reconcile(
        appended,
        object_id=OBJECT_B,
        request_id="corpus-b-2",
        path="Inbox/corpus-b.pdf",
        version_id="ver_aaaaaaaaaaaaaaaaaaaaaa0d",
        repository=repository,
    )
    assert _production().profile_version == PDFIUM_NORMALIZED_PROFILE
    assert second.run.new_logical_page_count == 1
    by_number = {item.page_number: item for item in second.matches}
    assert by_number[1].logical_page_id == first.matches[0].logical_page_id
    assert by_number[2].logical_page_id == first.matches[1].logical_page_id
    assert by_number[1].is_new is False
    assert by_number[2].is_new is False
    assert by_number[3].is_new is True


def test_c_added_handwriting_keeps_logical_page_identity() -> None:
    """C: a small added mark on an existing page does not allocate a new logical page."""
    original = vector_pdf((COVER,), producer="mark-a", comment="clean")
    marked = vector_pdf((SMALL_MARK,), producer="mark-b", comment="ink", dummy_objects=3)
    renderer = _production()
    first_render = renderer.render(split_admitted_pdf(original)[0])
    marked_render = renderer.render(split_admitted_pdf(marked)[0])
    assert first_render.normalized_render_sha256 != marked_render.normalized_render_sha256
    repository = MemoryLineageRepository()
    first = _reconcile(
        original,
        object_id=OBJECT_C,
        request_id="corpus-c-page-1",
        path="Inbox/corpus-c.pdf",
        version_id="ver_aaaaaaaaaaaaaaaaaaaaaa0e",
        repository=repository,
    )
    second = _reconcile(
        marked,
        object_id=OBJECT_C,
        request_id="corpus-c-page-2",
        path="Inbox/corpus-c.pdf",
        version_id="ver_aaaaaaaaaaaaaaaaaaaaaa0f",
        repository=repository,
    )
    match = second.matches[0]
    assert match.is_new is False
    assert match.logical_page_id == first.matches[0].logical_page_id
    assert second.run.new_logical_page_count == 0


def test_c_note_unit_novelty_is_crop_grounded_not_agent_geometry() -> None:
    """C: agent geometry/crop_sha256 alone cannot mint NEW; server crop is identity."""
    png = _ink_png()
    store = MemoryDurableNoteStore()
    first_run, first_page, notebook_id, logical_id = _plant(store, "corpus-c-crop", png=png)
    store.store_semantic_proposal(
        GROUNDING_A,
        first_run,
        first_page,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.1, transcription="same ink", crop_sha256=AGENT_CROP)]},
    )
    first = GoodNotesOccurrenceReconciler().reconcile(
        GROUNDING_A, first_run, repository=store, clock=lambda: GROUNDING_LATER
    )
    assert [item.change_state for item in first.changes] == [GoodNotesNoteChangeState.NEW]
    stored = store.occurrence(GROUNDING_A, first.changes[0].occurrence_id)  # type: ignore[arg-type]
    assert stored is not None
    assert stored.crop_sha256 == crop_normalized_png(png, 0.1, 0.2, 0.2, 0.1).digest
    assert stored.crop_sha256 != AGENT_CROP

    second_run, second_page = _next_version(
        store, key="corpus-c-crop-b", notebook_id=notebook_id, logical_id=logical_id, png=png
    )
    store.store_semantic_proposal(
        GROUNDING_A,
        second_run,
        second_page,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.1, transcription="same ink", crop_sha256=OTHER_AGENT_CROP)]},
    )
    second = GoodNotesOccurrenceReconciler().reconcile(
        GROUNDING_A, second_run, repository=store, clock=lambda: GROUNDING_LATER
    )
    assert GoodNotesNoteChangeState.NEW not in {item.change_state for item in second.changes}
    assert len(store._notes) == 1

    white = MemoryDurableNoteStore()
    white_run, white_page, _, _ = _plant(white, "corpus-c-white", png=png)
    white.store_semantic_proposal(
        GROUNDING_A,
        white_run,
        white_page,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.6, transcription="ghost on white", crop_sha256=AGENT_CROP)]},
    )
    ghost = GoodNotesOccurrenceReconciler().reconcile(
        GROUNDING_A, white_run, repository=white, clock=lambda: GROUNDING_LATER
    )
    assert [item.change_state for item in ghost.changes] == [GoodNotesNoteChangeState.AMBIGUOUS]
    assert ghost.changes[0].note_id is None
    assert white._notes == {}


def test_d_reorder_of_byte_different_regenerated_pages_preserves_visual_identity() -> None:
    """D / reordered false-new = 0: regenerated reorder changes ordinal only."""
    original = vector_pdf((COVER, BODY), producer="order-a", comment="first")
    reordered = vector_pdf(
        (BODY, COVER), producer="order-b", comment="regenerated", dummy_objects=3
    )
    assert original != reordered
    assert _sha(original) != _sha(reordered)
    renderer = _production()
    original_pages = split_admitted_pdf(original)
    reordered_pages = split_admitted_pdf(reordered)
    assert (
        renderer.render(original_pages[0]).normalized_render_sha256
        == renderer.render(reordered_pages[1]).normalized_render_sha256
    )
    assert (
        renderer.render(original_pages[1]).normalized_render_sha256
        == renderer.render(reordered_pages[0]).normalized_render_sha256
    )
    repository = MemoryLineageRepository()
    first = _reconcile(
        original,
        object_id=OBJECT_D,
        request_id="corpus-d-1",
        path="Inbox/corpus-d.pdf",
        version_id="ver_aaaaaaaaaaaaaaaaaaaaaa10",
        repository=repository,
    )
    second = _reconcile(
        reordered,
        object_id=OBJECT_D,
        request_id="corpus-d-2",
        path="Inbox/corpus-d.pdf",
        version_id="ver_aaaaaaaaaaaaaaaaaaaaaa11",
        repository=repository,
    )
    first_ids = {item.page_number: item.logical_page_id for item in first.matches}
    second_by_number = {item.page_number: item for item in second.matches}
    assert second_by_number[1].logical_page_id == first_ids[2]
    assert second_by_number[2].logical_page_id == first_ids[1]
    assert second_by_number[1].is_new is False
    assert second_by_number[2].is_new is False
    assert second.run.new_logical_page_count == 0


def test_i_mixed_page_note_unit_v2_candidates_do_not_cross_contaminate() -> None:
    """I: mixed-page NOTE_UNIT v2 candidates stay on the unit that named them."""
    png = _ink_png(boxes=((0.1, 0.2, 0.2, 0.1), (0.6, 0.2, 0.2, 0.1)))
    store = MemoryDurableNoteStore()
    run_id, page_id, _, _ = _plant(store, "corpus-i-occ", png=png)
    store.store_semantic_proposal(
        GROUNDING_A,
        run_id,
        page_id,
        "note-unit.v2",
        "synthetic",
        "1",
        {
            "segments": [
                _segment(x_min=0.1, transcription="synthetic left"),
                _segment(x_min=0.6, transcription="synthetic right"),
            ]
        },
    )
    minted = GoodNotesOccurrenceReconciler().reconcile(
        GROUNDING_A, run_id, repository=store, clock=lambda: GROUNDING_LATER
    )
    assert [item.change_state for item in minted.changes] == [
        GoodNotesNoteChangeState.NEW,
        GoodNotesNoteChangeState.NEW,
    ]
    assert len(store._notes) == 2
    left_occ = store.occurrence(GROUNDING_A, minted.changes[0].occurrence_id)  # type: ignore[arg-type]
    right_occ = store.occurrence(GROUNDING_A, minted.changes[1].occurrence_id)  # type: ignore[arg-type]
    assert left_occ is not None and right_occ is not None
    assert left_occ.x_min != right_occ.x_min
    assert left_occ.note_id != right_occ.note_id

    page = issue_stable_id("gnver", "corpus-i-v2")
    left_revision = GoodNotesNoteRevision(
        revision_id=issue_stable_id("gnrev", "corpus-i-left"),
        principal_id=DELIVERY_A,
        note_id=issue_stable_id("gnnt", "corpus-i-left"),
        schema_version="note-unit.v2",
        analyzer_name="synthetic",
        analyzer_version="1",
        transcription="synthetic left",
        created_at=DELIVERY_WHEN,
        occurrence_id=issue_stable_id("gnocc", "corpus-i-left"),
        primary_class=GoodNotesNoteClass.MEETING,
    )
    right_revision = GoodNotesNoteRevision(
        revision_id=issue_stable_id("gnrev", "corpus-i-right"),
        principal_id=DELIVERY_A,
        note_id=issue_stable_id("gnnt", "corpus-i-right"),
        schema_version="note-unit.v2",
        analyzer_name="synthetic",
        analyzer_version="1",
        transcription="synthetic right",
        created_at=DELIVERY_WHEN,
        occurrence_id=issue_stable_id("gnocc", "corpus-i-right"),
        primary_class=GoodNotesNoteClass.MEETING,
    )
    left = _change(
        "corpus-i-left", GoodNotesNoteChangeState.NEW, revision_id=left_revision.revision_id
    )
    right = _change(
        "corpus-i-right", GoodNotesNoteChangeState.NEW, revision_id=right_revision.revision_id
    )
    repo = _FakeDeliveryRepository(
        principal_id=DELIVERY_A,
        stored_run=_run(),
        changes=(left, right),
        occurrences={
            left.occurrence_id: _occurrence("corpus-i-left", page),
            right.occurrence_id: replace(_occurrence("corpus-i-right", page), x_min=0.6),
        },
        revisions={
            left_revision.revision_id: left_revision,
            right_revision.revision_id: right_revision,
        },
        proposals=(
            (
                page,
                "note-unit.v2",
                "synthetic",
                "1",
                {
                    "segments": [
                        {
                            "kind": "NOTE_UNIT",
                            "geometry": {
                                "x_min": 0.1,
                                "y_min": 0.2,
                                "width": 0.2,
                                "height": 0.1,
                            },
                            "transcription": "synthetic left",
                            "ranked_candidates": [{"rank": 1, "candidate": "Alpha Project"}],
                        },
                        {
                            "kind": "NOTE_UNIT",
                            "geometry": {
                                "x_min": 0.6,
                                "y_min": 0.2,
                                "width": 0.2,
                                "height": 0.1,
                            },
                            "transcription": "synthetic right",
                            "ranked_candidates": [{"rank": 1, "candidate": "Beta Project"}],
                        },
                    ],
                },
            ),
        ),
        directory=(
            GoodNotesEntityDirectoryRecord(
                entity_id="prj_aaaaaaaaaaaaaaaa",
                kind=GoodNotesEntityKind.PROJECT,
                normalized_name="alpha project",
            ),
            GoodNotesEntityDirectoryRecord(
                entity_id="prj_bbbbbbbbbbbbbbbb",
                kind=GoodNotesEntityKind.PROJECT,
                normalized_name="beta project",
            ),
        ),
    )
    result = GoodNotesNewOnlyDelivery().deliver(
        DELIVERY_A, RUN, DESTINATION, repository=repo, clock=lambda: DELIVERY_WHEN
    )
    by_note = {item.note_id: item for item in result.associations}
    assert set(by_note) == {left.note_id, right.note_id}
    assert by_note[left.note_id].candidate == "Alpha Project"
    assert by_note[left.note_id].resolved_id == "prj_aaaaaaaaaaaaaaaa"
    assert by_note[right.note_id].candidate == "Beta Project"
    assert by_note[right.note_id].resolved_id == "prj_bbbbbbbbbbbbbbbb"


def test_j_unreadable_or_empty_transcription_does_not_mint_new() -> None:
    """J / fabricated unreadable = 0: UNREADABLE or empty transcription does not mint NEW."""
    invented = MemoryDurableNoteStore()
    run_id, page_id, _, _ = _plant(invented, "corpus-j-unreadable", png=_ink_png())
    invented.store_semantic_proposal(
        GROUNDING_A,
        run_id,
        page_id,
        "note-unit.v2",
        "synthetic",
        "1",
        {
            "segments": [
                _segment(
                    x_min=0.1,
                    transcription="invented text",
                    transcription_status="UNREADABLE",
                )
            ]
        },
    )
    invented_result = GoodNotesOccurrenceReconciler().reconcile(
        GROUNDING_A, run_id, repository=invented, clock=lambda: GROUNDING_LATER
    )
    assert [item.change_state for item in invented_result.changes] == [
        GoodNotesNoteChangeState.AMBIGUOUS
    ]
    assert invented_result.changes[0].note_id is None
    assert invented._notes == {}
    assert invented._revisions == {}
    assert "invented text" not in repr(invented_result)

    empty = MemoryDurableNoteStore()
    empty_run, empty_page, _, _ = _plant(empty, "corpus-j-empty", png=_ink_png())
    empty.store_semantic_proposal(
        GROUNDING_A,
        empty_run,
        empty_page,
        "note-unit.v2",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.1, transcription="", transcription_status="UNREADABLE")]},
    )
    empty_result = GoodNotesOccurrenceReconciler().reconcile(
        GROUNDING_A, empty_run, repository=empty, clock=lambda: GROUNDING_LATER
    )
    assert [item.change_state for item in empty_result.changes] == [
        GoodNotesNoteChangeState.AMBIGUOUS
    ]
    assert empty_result.changes[0].note_id is None
    assert empty._notes == {}


def test_q_no_new_rows_suppresses_summary() -> None:
    """Q: no NEW rows writes a suppressed internal receipt and does not send an empty body."""
    assert build_new_only_summary(()) is None
    repo = _FakeDeliveryRepository(
        principal_id=DELIVERY_A,
        stored_run=_run(),
        changes=(_change("corpus-q", GoodNotesNoteChangeState.REVISED),),
        occurrences={},
        revisions={},
    )
    result = GoodNotesNewOnlyDelivery().deliver(
        DELIVERY_A, RUN, DESTINATION, repository=repo, clock=lambda: DELIVERY_WHEN
    )
    assert result.receipt.suppressed is True
    assert result.receipt.body is None
    assert result.receipt.replayed is False
    assert result.associations == ()


def test_r_historical_new_only_summary_stays_bound_to_run_revision() -> None:
    """R: a later correction does not rewrite the historical NEW-only summary."""
    page = issue_stable_id("gnver", "corpus-r")
    bound = _meeting_revision("corpus-r", "synthetic original")
    later = replace(
        bound,
        revision_id=issue_stable_id("gnrev", "corpus-r-later"),
        transcription="synthetic corrected",
        created_at=DELIVERY_LATER,
        supersedes_revision_id=bound.revision_id,
    )
    change = _change("corpus-r", GoodNotesNoteChangeState.NEW, revision_id=bound.revision_id)
    repo = _FakeDeliveryRepository(
        principal_id=DELIVERY_A,
        stored_run=_run(),
        changes=(change,),
        occurrences={change.occurrence_id: _occurrence("corpus-r", page)},
        revisions={bound.revision_id: bound, later.revision_id: later},
    )
    first = GoodNotesNewOnlyDelivery().deliver(
        DELIVERY_A, RUN, DESTINATION, repository=repo, clock=lambda: DELIVERY_WHEN
    )
    assert first.receipt.body is not None
    assert "synthetic original" in first.receipt.body
    assert "synthetic corrected" not in first.receipt.body
    second = GoodNotesNewOnlyDelivery().deliver(
        DELIVERY_A, RUN, DESTINATION, repository=repo, clock=lambda: DELIVERY_LATER
    )
    assert second.receipt.replayed is True
    assert second.receipt.summary_hash == first.receipt.summary_hash
    assert second.receipt.body == first.receipt.body


def test_m_duplicate_run_retry_does_not_create_extra_note_rows() -> None:
    """M: a duplicate reconcile of the same run replays change ids and adds no notes."""
    png = _ink_png()
    store = MemoryDurableNoteStore()
    run_id, page_id, _, _ = _plant(store, "corpus-m", png=png)
    store.store_semantic_proposal(
        GROUNDING_A,
        run_id,
        page_id,
        "note-unit.v1",
        "synthetic",
        "1",
        {"segments": [_segment(x_min=0.1, transcription="same note")]},
    )
    reconciler = GoodNotesOccurrenceReconciler()
    first = reconciler.reconcile(
        GROUNDING_A, run_id, repository=store, clock=lambda: GROUNDING_LATER
    )
    assert [item.change_state for item in first.changes] == [GoodNotesNoteChangeState.NEW]
    notes_after_first = len(store._notes)
    changes_after_first = len(store.run_note_changes(GROUNDING_A, run_id))
    second = reconciler.reconcile(
        GROUNDING_A, run_id, repository=store, clock=lambda: GROUNDING_LATER
    )
    assert second.replayed is True
    assert [item.change_id for item in second.changes] == [item.change_id for item in first.changes]
    assert len(store._notes) == notes_after_first == 1
    assert len(store.run_note_changes(GROUNDING_A, run_id)) == changes_after_first


def test_release_floor_regenerated_false_new_is_zero() -> None:
    """Release floor: regenerated visually equivalent PDFs allocate zero NEW logical pages."""
    first = vector_pdf((COVER,), producer="floor-regen-a", comment="one")
    second = vector_pdf((COVER,), producer="floor-regen-b", comment="two", dummy_objects=5)
    repository = MemoryLineageRepository()
    _reconcile(
        first,
        object_id="obj_aaaaaaaaaaaaaaaaaaaaaa20",
        request_id="floor-regen-1",
        path="Inbox/floor-regen.pdf",
        version_id="ver_aaaaaaaaaaaaaaaaaaaaaa20",
        repository=repository,
    )
    result = _reconcile(
        second,
        object_id="obj_aaaaaaaaaaaaaaaaaaaaaa20",
        request_id="floor-regen-2",
        path="Inbox/floor-regen.pdf",
        version_id="ver_aaaaaaaaaaaaaaaaaaaaaa21",
        repository=repository,
    )
    assert result.run.new_logical_page_count == 0
    assert all(not item.is_new for item in result.matches)


def test_release_floor_reordered_false_new_is_zero() -> None:
    """Release floor: reordered regenerated pages allocate zero NEW logical pages."""
    original = vector_pdf((COVER, BODY), producer="floor-order-a")
    reordered = vector_pdf((BODY, COVER), producer="floor-order-b", dummy_objects=2)
    repository = MemoryLineageRepository()
    _reconcile(
        original,
        object_id="obj_aaaaaaaaaaaaaaaaaaaaaa21",
        request_id="floor-order-1",
        path="Inbox/floor-order.pdf",
        version_id="ver_aaaaaaaaaaaaaaaaaaaaaa22",
        repository=repository,
    )
    result = _reconcile(
        reordered,
        object_id="obj_aaaaaaaaaaaaaaaaaaaaaa21",
        request_id="floor-order-2",
        path="Inbox/floor-order.pdf",
        version_id="ver_aaaaaaaaaaaaaaaaaaaaaa23",
        repository=repository,
    )
    assert result.run.new_logical_page_count == 0


def test_release_floor_fabricated_unreadable_is_zero() -> None:
    """Release floor: fabricated UNREADABLE content mints zero NEW notes."""
    store = MemoryDurableNoteStore()
    run_id, page_id, _, _ = _plant(store, "floor-unreadable", png=_ink_png())
    store.store_semantic_proposal(
        GROUNDING_A,
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
        GROUNDING_A, run_id, repository=store, clock=lambda: GROUNDING_LATER
    )
    assert GoodNotesNoteChangeState.NEW not in {item.change_state for item in result.changes}
    assert store._notes == {}


def test_release_floor_new_only_membership() -> None:
    """Release floor: user-facing summary membership is NEW-only; non-NEW states are omitted."""
    body = build_new_only_summary(
        (
            _note(
                "floor-new",
                note_class=GoodNotesNoteClass.MEETING,
                transcription="synthetic note",
            ),
        )
    )
    assert body is not None
    assert "NEW MEETING NOTES" in body
    assert "synthetic note" in body
    assert "REVISED" not in body
    page = issue_stable_id("gnver", "floor-new-only")
    revision = _meeting_revision("floor-new-only", "synthetic note")
    repo = _FakeDeliveryRepository(
        principal_id=DELIVERY_A,
        stored_run=_run(),
        changes=(
            _change(
                "floor-new-only",
                GoodNotesNoteChangeState.NEW,
                revision_id=revision.revision_id,
            ),
            _change("floor-revised", GoodNotesNoteChangeState.REVISED),
            _change("floor-unchanged", GoodNotesNoteChangeState.UNCHANGED),
            _change("floor-ambiguous", GoodNotesNoteChangeState.AMBIGUOUS),
        ),
        occurrences={
            issue_stable_id("gnocc", "floor-new-only"): _occurrence("floor-new-only", page)
        },
        revisions={revision.revision_id: revision},
    )
    result = GoodNotesNewOnlyDelivery().deliver(
        DELIVERY_A, RUN, DESTINATION, repository=repo, clock=lambda: DELIVERY_WHEN
    )
    assert result.receipt.body is not None
    assert "synthetic note" in result.receipt.body
    assert "NEW MEETING NOTES" in result.receipt.body
    assert "REVISED" not in result.receipt.body
    assert "UNCHANGED" not in result.receipt.body
    assert "AMBIGUOUS" not in result.receipt.body
