"""Production visual renderer and real-PDF lineage identity."""

from __future__ import annotations

import hashlib
import zlib
from datetime import UTC, datetime

import pytest

from my_pa.application.goodnotes_lineage import (
    GoodNotesLineageService,
    LineageReconcileRequest,
    LineageReconcileResult,
    ObservedNotebookFile,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesIdentityStatus,
    GoodNotesIngestionStatus,
    GoodNotesMatchMethod,
    SourcePage,
)
from my_pa.infrastructure.goodnotes.pdf import split_admitted_pdf
from my_pa.infrastructure.goodnotes.render import (
    PDFIUM_NORMALIZED_PROFILE,
    PdfiumNormalizedRenderer,
    production_page_renderer,
)
from tests.unit.goodnotes_lineage_memory import MemoryLineageRepository
from tests.unit.vector_pdf import Rect, vector_pdf

WHEN = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
COVER = (Rect(72, 400, 220, 220, 0.15),)
BODY = (Rect(80, 80, 420, 520, 0.45),)
SMALL_MARK = (Rect(72, 400, 220, 220, 0.15), Rect(90, 600, 6, 6, 0.0))
LARGE_MARK = (Rect(72, 400, 220, 220, 0.15), Rect(40, 40, 200, 280, 0.0))
ROOT_ID = "icloud-goodnotes"


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _tiny_gray_jpeg() -> bytes:
    return (
        bytes.fromhex("ffd8ffe000104a46494600010100000100010000")
        + bytes.fromhex("ffdb0043")
        + bytes([0])
        + bytes([1] * 64)
        + bytes.fromhex("ffc0000b080008000801011100")
        + bytes.fromhex("ffc4001f000001050101010101010000000000000000000102030405060708090a0b")
        + bytes.fromhex(
            "ffc400b5100002010303020403050504040000017d01020300041105122131410613"
            "516107227114328191a1082342b1c11552d1f02433627282090a161718191a252627"
            "28292a3435363738393a434445464748494a535455565758595a636465666768696a"
            "737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aa"
            "b2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7"
            "e8e9eaf1f2f3f4f5f6f7f8f9fa"
        )
        + bytes.fromhex("ffda0008000100003f00ffd9")
    )


def _grayscale_png(width: int, height: int, pixels: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return len(data).to_bytes(4, "big") + tag + data + crc.to_bytes(4, "big")

    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 0, 0, 0, 0])
    raw = b"".join(b"\x00" + pixels[row * width : (row + 1) * width] for row in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _pages(
    pdf: bytes, object_id: str, version_id: str, source_id: str = "src_aaaaaaaaaaaaaaaaaaaaaaaa"
) -> tuple[SourcePage, ...]:
    return tuple(
        SourcePage(
            principal_id=A,
            source_id=source_id,
            source_object_id=object_id,
            source_version_id=version_id,
            page_number=index,
            observed_at=WHEN,
            content=part,
            representation_media_type="application/pdf",
        )
        for index, part in enumerate(split_admitted_pdf(pdf), start=1)
    )


def _observation(pdf: bytes, path: str) -> ObservedNotebookFile:
    return ObservedNotebookFile(
        relative_path=path,
        size_bytes=len(pdf),
        sha256=_sha(pdf),
        mtime_ns=1,
        page_count=len(split_admitted_pdf(pdf)),
    )


def _reconcile(
    pdf: bytes,
    *,
    object_id: str,
    request_id: str,
    path: str,
    version_id: str,
    repository: MemoryLineageRepository,
    notebook_id: str | None = None,
    finalize_run: bool = True,
) -> LineageReconcileResult:
    return GoodNotesLineageService().reconcile(
        LineageReconcileRequest(
            principal_id=A,
            request_id=request_id,
            source_root_id=ROOT_ID,
            source_object_id=object_id,
            observation=_observation(pdf, path),
            pages=_pages(pdf, object_id, version_id),
            notebook_id=notebook_id,
            observed_at=WHEN,
        ),
        renderer=production_page_renderer(),
        repository=repository,
        clock=lambda: WHEN,
        finalize_run=finalize_run,
    )


def test_production_renderer_is_the_pdfium_normalized_profile() -> None:
    renderer = production_page_renderer()
    assert isinstance(renderer, PdfiumNormalizedRenderer)
    assert renderer.profile_version == PDFIUM_NORMALIZED_PROFILE
    assert "pdfium-" in renderer.version


def test_visual_renderer_fails_closed_on_empty_and_invalid_input() -> None:
    renderer = production_page_renderer()
    with pytest.raises(ValueError, match="admitted bytes"):
        renderer.render(b"")
    with pytest.raises(ValueError, match="not a PDF"):
        renderer.render(b"not-a-document")
    with pytest.raises(ValueError, match="not readable"):
        renderer.render(b"%PDF-1.4\n%%EOF\n")
    with pytest.raises(ValueError):
        split_admitted_pdf(b"%PDF-1.4\n%%EOF\n")
    jpeg = _tiny_gray_jpeg()
    jpeg_render = production_page_renderer().render(jpeg)
    assert jpeg_render.normalized_render_sha256 != _sha(jpeg)
    assert jpeg_render.render_profile_version == PDFIUM_NORMALIZED_PROFILE


def test_lineage_finalize_run_false_leaves_the_run_running() -> None:
    pdf = vector_pdf((COVER,))
    pending = _reconcile(
        pdf,
        object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
        request_id="vis-finalize-false",
        path="Inbox/finalize.pdf",
        version_id="ver_aaaaaaaaaaaaaaaaaaaaaaaa",
        repository=MemoryLineageRepository(),
        finalize_run=False,
    )
    assert pending.run.status is GoodNotesIngestionStatus.RUNNING
    assert pending.run.ended_at is None
    finished = _reconcile(
        pdf,
        object_id="obj_bbbbbbbbbbbbbbbbbbbbbbbb",
        request_id="vis-finalize-true",
        path="Inbox/finalize-default.pdf",
        version_id="ver_bbbbbbbbbbbbbbbbbbbbbbbb",
        repository=MemoryLineageRepository(),
    )
    assert finished.run.status is GoodNotesIngestionStatus.SUCCEEDED
    assert finished.run.ended_at is not None


def test_png_page_bytes_render_without_equaling_the_raw_digest() -> None:
    pixels = bytes([255] * 32 + [0] * 32) * 8
    payload = _grayscale_png(16, 16, pixels)
    render = production_page_renderer().render(payload)
    assert render.normalized_render_sha256 != _sha(payload)
    assert render.exact_render_sha256 != _sha(payload)
    assert render.perceptual_hash is not None
    assert render.width == 16 and render.height == 16
    assert render.render_profile_version == PDFIUM_NORMALIZED_PROFILE


def test_identical_visible_pages_share_normalized_hash_despite_byte_churn() -> None:
    first = vector_pdf((COVER, BODY), producer="alpha", comment="first")
    second = vector_pdf((COVER, BODY), producer="beta", comment="regenerated", dummy_objects=4)
    assert first != second
    assert _sha(first) != _sha(second)
    renderer = production_page_renderer()
    first_pages = split_admitted_pdf(first)
    second_pages = split_admitted_pdf(second)
    first_renders = tuple(renderer.render(page) for page in first_pages)
    second_renders = tuple(renderer.render(page) for page in second_pages)
    assert [item.normalized_render_sha256 for item in first_renders] == [
        item.normalized_render_sha256 for item in second_renders
    ]
    assert [item.exact_render_sha256 for item in first_renders] == [
        item.exact_render_sha256 for item in second_renders
    ]
    for render, raw in zip(first_renders, first_pages, strict=True):
        assert render.normalized_render_sha256 != _sha(raw)
        assert render.exact_render_sha256 != _sha(raw)
    repository = MemoryLineageRepository()
    first_result = _reconcile(
        first,
        object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
        request_id="vis-1",
        path="Inbox/alpha.pdf",
        version_id="ver_aaaaaaaaaaaaaaaaaaaaaaaa",
        repository=repository,
    )
    second_result = _reconcile(
        second,
        object_id="obj_aaaaaaaaaaaaaaaaaaaaaaaa",
        request_id="vis-2",
        path="Inbox/alpha.pdf",
        version_id="ver_bbbbbbbbbbbbbbbbbbbbbbbb",
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


def test_append_creates_only_the_new_visual_page() -> None:
    original = vector_pdf((COVER, BODY), producer="append-a")
    appended = vector_pdf((COVER, BODY, (Rect(200, 200, 80, 80, 0.7),)), producer="append-b")
    repository = MemoryLineageRepository()
    first = _reconcile(
        original,
        object_id="obj_cccccccccccccccccccccccc",
        request_id="append-1",
        path="Inbox/append.pdf",
        version_id="ver_cccccccccccccccccccccccc",
        repository=repository,
    )
    second = _reconcile(
        appended,
        object_id="obj_cccccccccccccccccccccccc",
        request_id="append-2",
        path="Inbox/append.pdf",
        version_id="ver_dddddddddddddddddddddddd",
        repository=repository,
    )
    assert second.run.new_logical_page_count == 1
    by_number = {item.page_number: item for item in second.matches}
    assert by_number[1].logical_page_id == first.matches[0].logical_page_id
    assert by_number[2].logical_page_id == first.matches[1].logical_page_id
    assert by_number[3].is_new is True


def test_reorder_preserves_visual_identity_and_changes_ordinal() -> None:
    original = vector_pdf((COVER, BODY), producer="order-a")
    reordered = vector_pdf((BODY, COVER), producer="order-b")
    repository = MemoryLineageRepository()
    first = _reconcile(
        original,
        object_id="obj_eeeeeeeeeeeeeeeeeeeeeeee",
        request_id="order-1",
        path="Inbox/order.pdf",
        version_id="ver_eeeeeeeeeeeeeeeeeeeeeeee",
        repository=repository,
    )
    second = _reconcile(
        reordered,
        object_id="obj_eeeeeeeeeeeeeeeeeeeeeeee",
        request_id="order-2",
        path="Inbox/order.pdf",
        version_id="ver_ffffffffffffffffffffffff",
        repository=repository,
    )
    first_ids = {item.page_number: item.logical_page_id for item in first.matches}
    second_ids = {item.page_number: item.logical_page_id for item in second.matches}
    assert second_ids[1] == first_ids[2]
    assert second_ids[2] == first_ids[1]
    assert second.run.new_logical_page_count == 0


def test_two_identical_blank_pages_are_ambiguous() -> None:
    first_pdf = vector_pdf(((), ()), producer="blank-a")
    second_pdf = vector_pdf(((), ()), producer="blank-b", dummy_objects=3)
    repository = MemoryLineageRepository()
    first = _reconcile(
        first_pdf,
        object_id="obj_bbbbbbbbbbbbbbbbbbbbbbbb",
        request_id="blank-1",
        path="Inbox/blank.pdf",
        version_id="ver_bbbbbbbbbbbbbbbbbbbbbbbb",
        repository=repository,
    )
    assert first.run.new_logical_page_count == 2
    second = _reconcile(
        second_pdf,
        object_id="obj_bbbbbbbbbbbbbbbbbbbbbbbb",
        request_id="blank-2",
        path="Inbox/blank.pdf",
        version_id="ver_cccccccccccccccccccccccc",
        repository=repository,
    )
    assert all(item.identity_status is GoodNotesIdentityStatus.AMBIGUOUS for item in second.matches)
    assert all(item.match_method is GoodNotesMatchMethod.UNRESOLVED for item in second.matches)
    assert all(item.is_new for item in second.matches)
    assert second.run.ambiguous_page_count == 2


def test_small_added_mark_keeps_logical_page_identity() -> None:
    original = vector_pdf((COVER,), producer="mark-a")
    marked = vector_pdf((SMALL_MARK,), producer="mark-b")
    renderer = production_page_renderer()
    first_render = renderer.render(split_admitted_pdf(original)[0])
    marked_render = renderer.render(split_admitted_pdf(marked)[0])
    repository = MemoryLineageRepository()
    first = _reconcile(
        original,
        object_id="obj_121212121212121212121212",
        request_id="mark-1",
        path="Inbox/mark.pdf",
        version_id="ver_121212121212121212121212",
        repository=repository,
    )
    second = _reconcile(
        marked,
        object_id="obj_121212121212121212121212",
        request_id="mark-2",
        path="Inbox/mark.pdf",
        version_id="ver_131313131313131313131313",
        repository=repository,
    )
    match = second.matches[0]
    assert match.is_new is False
    assert match.logical_page_id == first.matches[0].logical_page_id
    assert first_render.normalized_render_sha256 != marked_render.normalized_render_sha256
    assert first_render.perceptual_hash == marked_render.perceptual_hash
    assert match.match_method in {
        GoodNotesMatchMethod.STRONG_VISUAL_FINGERPRINT,
        GoodNotesMatchMethod.PERCEPTUAL_STRUCTURAL,
    }


def test_large_added_mark_cannot_reuse_identity_by_sequence() -> None:
    original = vector_pdf((COVER,), producer="large-a")
    marked = vector_pdf((LARGE_MARK,), producer="large-b")
    renderer = production_page_renderer()
    first_render = renderer.render(split_admitted_pdf(original)[0])
    marked_render = renderer.render(split_admitted_pdf(marked)[0])
    assert first_render.normalized_render_sha256 != marked_render.normalized_render_sha256
    assert first_render.perceptual_hash != marked_render.perceptual_hash
    repository = MemoryLineageRepository()
    first = _reconcile(
        original,
        object_id="obj_141414141414141414141414",
        request_id="large-1",
        path="Inbox/large.pdf",
        version_id="ver_141414141414141414141414",
        repository=repository,
    )
    second = _reconcile(
        marked,
        object_id="obj_141414141414141414141414",
        request_id="large-2",
        path="Inbox/large.pdf",
        version_id="ver_151515151515151515151515",
        repository=repository,
    )
    match = second.matches[0]
    assert match.is_new is True
    assert match.logical_page_id != first.matches[0].logical_page_id
    assert match.identity_status is GoodNotesIdentityStatus.AMBIGUOUS
    assert match.match_method is GoodNotesMatchMethod.UNRESOLVED
    assert match.prior_page_version_id is None
    assert second.run.ambiguous_page_count == 1


def test_middle_page_mismatch_is_ambiguous_and_preserves_neighbors() -> None:
    original = vector_pdf((COVER, BODY, (Rect(300, 300, 40, 40, 0.8),)), producer="mid-a")
    marked = vector_pdf((COVER, SMALL_MARK, (Rect(300, 300, 40, 40, 0.8),)), producer="mid-b")
    repository = MemoryLineageRepository()
    first = _reconcile(
        original,
        object_id="obj_161616161616161616161616",
        request_id="mid-1",
        path="Inbox/middle.pdf",
        version_id="ver_161616161616161616161616",
        repository=repository,
    )
    second = _reconcile(
        marked,
        object_id="obj_161616161616161616161616",
        request_id="mid-2",
        path="Inbox/middle.pdf",
        version_id="ver_171717171717171717171717",
        repository=repository,
    )
    first_ids = {item.page_number: item.logical_page_id for item in first.matches}
    second_by_number = {item.page_number: item for item in second.matches}
    assert second.run.new_logical_page_count == 1
    assert second.run.ambiguous_page_count == 1
    assert second_by_number[1].logical_page_id == first_ids[1]
    assert second_by_number[1].identity_status is GoodNotesIdentityStatus.ACTIVE
    assert second_by_number[2].logical_page_id != first_ids[2]
    assert second_by_number[2].identity_status is GoodNotesIdentityStatus.AMBIGUOUS
    assert second_by_number[2].match_method is GoodNotesMatchMethod.UNRESOLVED
    assert second_by_number[3].logical_page_id == first_ids[3]
    assert second_by_number[3].identity_status is GoodNotesIdentityStatus.ACTIVE
    assert second_by_number[2].is_new is True
