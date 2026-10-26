"""PDFium tier for the Full-Schedule plane: what the synthetic fixtures present.

FAST. Contract `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
sections 2.3, 2.4 and 8. The readback here uses raw `pypdfium2` directly (a
test may; under `src/my_pa` only `infrastructure/schedule/pdf.py` may) and only
functions that exist with identical argtypes at the 5.0.0 floor and at 5.13.0,
so the same module proves the fixtures at both. It establishes, independently
of any parser, that every generated PDF shows PDFium exactly the text objects,
fonts, sizes, matrices, bounds, attributed characters, page geometry,
encryption and structure its generator intended. The `pdf.py` extraction tests
of contract section 10.4 are added here by the WP-02 parser change.
"""

from __future__ import annotations

import ctypes
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

import pypdfium2 as pdfium  # type: ignore[import-untyped]
import pypdfium2.raw as pdfium_c  # type: ignore[import-untyped]
import pytest

from tests.fixtures import schedule_full_pdf as gen

#: Cases whose bytes PDFium opens and whose page specs are readable text pages.
_RAW_ONLY = {"corrupt_pdf", "encrypted_pdf", "image_only_pdf"}
_READABLE = [
    (family, variant)
    for family, variant in gen.CASES
    if family not in _RAW_ONLY
    and (family, variant)
    not in {
        ("wrong_page_size", "zero_pages"),
        ("bounds_exceeded", "pages"),
        ("bounds_exceeded", "form_text"),
        ("bounds_exceeded", "form_depth"),
    }
]


def _mpt(value: float) -> int:
    return int(Decimal(value).scaleb(3).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def _handle(pointer: object) -> int | None:
    value = ctypes.cast(pointer, ctypes.c_void_p).value
    return None if value is None else int(value)


@dataclass
class _Seen:
    base_name: str
    embedded: bool
    size: float
    matrix: tuple[float, ...]
    box: tuple[int, int, int, int]
    text: str = ""
    map_errors: int = 0


@dataclass
class _Page:
    width: float
    height: float
    rotation: int
    media_box: tuple[float, float, float, float]
    has_crop_box: bool
    object_types: list[int]
    text_objects: list[_Seen]


def _box(obj: object) -> tuple[int, int, int, int]:
    left, bottom, right, top = (ctypes.c_float() for _ in range(4))
    assert pdfium_c.FPDFPageObj_GetBounds(obj, left, bottom, right, top)
    return (_mpt(left.value), _mpt(bottom.value), _mpt(right.value), _mpt(top.value))


def _read(pdf: bytes) -> tuple[int, list[_Page]]:
    document = pdfium.PdfDocument(pdf)
    try:
        revision = int(pdfium_c.FPDF_GetSecurityHandlerRevision(document.raw))
        pages: list[_Page] = []
        for index in range(len(document)):
            size = pdfium_c.FS_SIZEF()
            assert pdfium_c.FPDF_GetPageSizeByIndexF(document.raw, index, ctypes.byref(size))
            page = document[index]
            textpage = page.get_textpage()
            try:
                pages.append(_read_page(page, textpage, size))
            finally:
                textpage.close()
                page.close()
        return revision, pages
    finally:
        document.close()


def _read_page(page: pdfium.PdfPage, textpage: pdfium.PdfTextPage, size: object) -> _Page:
    edges = [ctypes.c_float() for _ in range(4)]
    assert pdfium_c.FPDFPage_GetMediaBox(page.raw, *edges)
    crop = [ctypes.c_float() for _ in range(4)]
    seen: list[_Seen] = []
    handles: dict[int, int] = {}
    types: list[int] = []
    for index in range(int(pdfium_c.FPDFPage_CountObjects(page.raw))):
        obj = pdfium_c.FPDFPage_GetObject(page.raw, index)
        kind = int(pdfium_c.FPDFPageObj_GetType(obj))
        types.append(kind)
        if kind != pdfium_c.FPDF_PAGEOBJ_TEXT:
            continue
        font = pdfium_c.FPDFTextObj_GetFont(obj)
        buffer = ctypes.create_string_buffer(256)
        pdfium_c.FPDFFont_GetBaseFontName(font, buffer, 256)
        font_size = ctypes.c_float()
        assert pdfium_c.FPDFTextObj_GetFontSize(obj, ctypes.byref(font_size))
        matrix = pdfium_c.FS_MATRIX()
        assert pdfium_c.FPDFPageObj_GetMatrix(obj, ctypes.byref(matrix))
        key = _handle(obj)
        assert key is not None
        handles[key] = len(seen)
        seen.append(
            _Seen(
                base_name=buffer.value.decode("latin-1"),
                embedded=bool(pdfium_c.FPDFFont_GetIsEmbedded(font)),
                size=font_size.value,
                matrix=(matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f),
                box=_box(obj),
            )
        )
    for index in range(int(pdfium_c.FPDFText_CountChars(textpage.raw))):
        if pdfium_c.FPDFText_IsGenerated(textpage.raw, index):
            continue
        key = _handle(pdfium_c.FPDFText_GetTextObject(textpage.raw, index))
        if key is None:
            continue
        target = seen[handles[key]]
        target.text += chr(pdfium_c.FPDFText_GetUnicode(textpage.raw, index))
        target.map_errors += int(pdfium_c.FPDFText_HasUnicodeMapError(textpage.raw, index))
    return _Page(
        width=size.width,
        height=size.height,
        rotation=int(pdfium_c.FPDFPage_GetRotation(page.raw)),
        media_box=tuple(edge.value for edge in edges),  # type: ignore[arg-type]
        has_crop_box=bool(pdfium_c.FPDFPage_GetCropBox(page.raw, *crop)),
        object_types=types,
        text_objects=seen,
    )


def _expected_text(draw: gen.Draw) -> str:
    # Section 2.4: a run of spaces inside one object is reported as one space.
    return "" if draw.suppressed else re.sub(" +", " ", draw.text)


def _box_tolerance(draw: gen.Draw) -> int:
    if draw.tr == 1:
        return 501  # a stroke copy's box grows by half the 1 pt line width
    if draw.rot != gen.IDENTITY:
        return 1  # rotated bounds pass through float32 trigonometry
    return 0


@pytest.mark.parametrize(("family", "variant"), _READABLE, ids=lambda v: str(v))
def test_generated_fixtures_present_the_intended_objects_to_pdfium(
    family: str, variant: str
) -> None:
    case = gen.build(family, variant)
    revision, pages = _read(case.pdf)
    assert revision == -1
    fonts = {spec.key: spec for spec in case.fonts}
    assert len(pages) == len(case.pages)
    for spec, page in zip(case.pages, pages, strict=True):
        assert page.object_types == [pdfium_c.FPDF_PAGEOBJ_TEXT] * len(spec.draws)
        assert page.rotation == {0: 0, 90: 1, 180: 2}[spec.rotate]
        assert page.media_box == tuple(float(v) for v in spec.media_box)
        assert not page.has_crop_box
        width = spec.media_box[2] - spec.media_box[0]
        height = spec.media_box[3] - spec.media_box[1]
        if spec.rotate in (90, 270):
            width, height = height, width
        assert (page.width, page.height) == (width, height)
        for draw, seen in zip(spec.draws, page.text_objects, strict=True):
            font = fonts[draw.font]
            assert seen.base_name == font.base_name
            assert seen.embedded
            assert Decimal(seen.size) == draw.size
            expected_box = gen.box_mpt(gen.analytic_box(draw, font.metrics))
            tolerance = _box_tolerance(draw)
            assert all(
                abs(a - b) <= tolerance for a, b in zip(seen.box, expected_box, strict=True)
            ), (draw.text, seen.box, expected_box)
            a, b, c, d = draw.rot
            for got, want in zip(seen.matrix, (a, b, c, d, draw.x, draw.y), strict=True):
                assert abs(Decimal(got) - want) < Decimal("0.0001")
            assert seen.text == _expected_text(draw), (draw.text, seen.text)
            if font.to_unicode:
                assert seen.map_errors == 0
            else:
                assert seen.map_errors == len(seen.text) > 0


def test_table_rotations_stay_clear_of_a_millipoint_rounding_tie() -> None:
    """Rotated table bounds round identically on any float32 PDFium build."""
    for family, variant in (("full_draft_watermark", "slight_skew"),):
        case = gen.build(family, variant)
        for spec in case.pages:
            for draw in spec.draws:
                if draw.role != "table" or draw.rot == gen.IDENTITY:
                    continue
                for edge in gen.analytic_box(draw, "uniform"):
                    fraction = (edge * 1000) % 1
                    assert abs(fraction - Decimal("0.5")) > Decimal("0.05")


def test_fixture_text_state_is_reset_in_every_block() -> None:
    block = re.compile(rb"BT (.*?) ET", re.DOTALL)
    reset = re.compile(rb"^/F\w+ [0-9.]+ Tf 0 Tc 0 Tw 100 Tz 0 TL [01] Tr 0 Ts [-0-9. ]+ Tm (\(|<)")
    seen = 0
    for family, variant in gen.CASES:
        case = gen.build(family, variant)
        if family in ("encrypted_pdf", "corrupt_pdf"):
            continue
        for body in block.findall(case.pdf):
            seen += 1
            assert reset.match(body), (case.name, body[:80])
    assert seen > 30_000


def test_failure_fixtures_fail_to_open_with_the_measured_codes() -> None:
    expected = {
        ("corrupt_pdf", "garbage"): pdfium_c.FPDF_ERR_FORMAT,
        ("wrong_page_size", "zero_pages"): pdfium_c.FPDF_ERR_FORMAT,
        ("encrypted_pdf", "user_password"): pdfium_c.FPDF_ERR_PASSWORD,
        ("encrypted_pdf", "unknown_filter"): pdfium_c.FPDF_ERR_SECURITY,
    }
    for (family, variant), code in expected.items():
        with pytest.raises(pdfium.PdfiumError) as caught:
            pdfium.PdfDocument(gen.build(family, variant).pdf)
        assert caught.value.err_code == code, (family, variant)
    assert gen.build("corrupt_pdf", "not_a_pdf").pdf == b"not a pdf"
    assert gen.build("corrupt_pdf", "empty").pdf == b""


def test_empty_user_password_fixture_opens_with_revision_2_and_decrypts() -> None:
    case = gen.build("encrypted_pdf", "empty_user_password")
    revision, pages = _read(case.pdf)
    assert revision == 2
    plain = gen.build("bounds_exceeded", "rows")  # the same small plan, unencrypted
    _, plain_pages = _read(plain.pdf)
    assert [[o.text for o in p.text_objects] for p in pages] == [
        [o.text for o in p.text_objects] for p in plain_pages
    ]
    assert any(o.text == "Synthetic Project Schedule" for o in pages[0].text_objects)


def test_image_only_fixture_has_no_text_object() -> None:
    _, pages = _read(gen.build("image_only_pdf", "base").pdf)
    assert len(pages) == 1
    assert pdfium_c.FPDF_PAGEOBJ_TEXT not in pages[0].object_types
    assert sorted(pages[0].object_types) == sorted(
        [pdfium_c.FPDF_PAGEOBJ_IMAGE, pdfium_c.FPDF_PAGEOBJ_PATH]
    )
    assert (pages[0].width, pages[0].height) == (1224.0, 792.0)


def test_page_cap_fixture_has_251_blank_frame_size_pages() -> None:
    document = pdfium.PdfDocument(gen.build("bounds_exceeded", "pages").pdf)
    try:
        assert len(document) == 251
        size = pdfium_c.FS_SIZEF()
        for index in (0, 250):
            assert pdfium_c.FPDF_GetPageSizeByIndexF(document.raw, index, ctypes.byref(size))
            assert (size.width, size.height) == (1224.0, 792.0)
    finally:
        document.close()


def test_byte_cap_fixture_is_the_valid_document_padded_past_16_mib() -> None:
    case = gen.build("bounds_exceeded", "bytes")
    base = gen.build("full_valid_2p", "base")
    assert len(case.pdf) == 16_777_216 + 1
    assert case.pdf.startswith(base.pdf)
    assert set(case.pdf[len(base.pdf) :]) == {0x0A}


def _form_depth(obj: object) -> tuple[int, int]:
    """(nesting depth, nested text objects) below one form object."""
    depth, texts = 1, 0
    for index in range(int(pdfium_c.FPDFFormObj_CountObjects(obj))):
        child = pdfium_c.FPDFFormObj_GetObject(obj, index)
        kind = int(pdfium_c.FPDFPageObj_GetType(child))
        if kind == pdfium_c.FPDF_PAGEOBJ_TEXT:
            texts += 1
        elif kind == pdfium_c.FPDF_PAGEOBJ_FORM:
            child_depth, child_texts = _form_depth(child)
            depth = max(depth, child_depth + 1)
            texts += child_texts
    return depth, texts


@pytest.mark.parametrize(("variant", "depth", "texts"), [("form_text", 1, 1), ("form_depth", 5, 0)])
def test_form_fixtures_nest_as_intended(variant: str, depth: int, texts: int) -> None:
    case = gen.build("bounds_exceeded", variant)
    document = pdfium.PdfDocument(case.pdf)
    try:
        page = document[0]
        try:
            forms = []
            for index in range(int(pdfium_c.FPDFPage_CountObjects(page.raw))):
                obj = pdfium_c.FPDFPage_GetObject(page.raw, index)
                if pdfium_c.FPDFPageObj_GetType(obj) == pdfium_c.FPDF_PAGEOBJ_FORM:
                    forms.append(_form_depth(obj))
            assert forms == [(depth, texts)]
        finally:
            page.close()
    finally:
        document.close()


def test_fixture_fonts_are_type3_with_the_profile_base_names() -> None:
    names = {
        spec.base_name for family, variant in gen.CASES for spec in gen.build(family, variant).fonts
    }
    assert names == {"Arial", "Arial,Bold", "SYNABC+Arial,Bold"}
    pdf = gen.build("full_valid_2p", "base").pdf
    assert pdf.count(b"/Subtype /Type3") == 2
    assert b"/FontFile" not in pdf
