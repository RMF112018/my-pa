"""PDFium tier for the Full-Schedule plane: what the synthetic fixtures present.

FAST. Contract `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
sections 2.3, 2.4 and 8. The readback here uses raw `pypdfium2` directly (a
test may; under `src/my_pa` only `infrastructure/schedule/pdf.py` may) and only
functions that exist with identical argtypes at the 5.0.0 floor and at 5.13.0,
so the same module proves the fixtures at both. It establishes, independently
of any parser, that every generated PDF shows PDFium exactly the text objects,
fonts, sizes, matrices, bounds, attributed characters, page geometry,
encryption and structure its generator intended.

The second half tests `src/my_pa/infrastructure/schedule/pdf.py` and the parse
entry point against PDFium (contract sections 2.4, 5.2, 7 and 10.4): text
acquisition from attributed characters, suppressed objects, caps checked
before the work they bound, the injected budget, safe error mapping, handle
cleanup and determinism. Probe PDFs are built with the fixture generator's
stdlib assembler; nothing is written to disk.
"""

from __future__ import annotations

import ctypes
import dataclasses
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

import pypdfium2 as pdfium  # type: ignore[import-untyped]
import pypdfium2.raw as pdfium_c  # type: ignore[import-untyped]
import pytest

from my_pa.domain.schedule import (
    ScheduleBox,
    ScheduleCellState,
    ScheduleFieldCode,
    ScheduleIssueCode,
    ScheduleParseEngine,
    ScheduleParseResult,
    SchedulePublicationStatus,
    ScheduleRowType,
    canonical_json_bytes,
    parse_result_object,
    parse_result_sha256,
)
from my_pa.infrastructure.schedule import PRODUCTION_LIMITS, ScheduleParseLimits
from my_pa.infrastructure.schedule import pdf as schedule_pdf
from my_pa.infrastructure.schedule.full_profile import (
    PdfPhysicalRow,
    ProfileTextObject,
    assign_full_cells,
    classify_full_row,
    exclude_profile_non_data,
    group_table_rows_by_overlap,
    parse_full_schedule,
)
from my_pa.infrastructure.schedule.pdf import (
    ParseBudget,
    PdfDocumentText,
    PdfPageText,
    PdfTextObject,
    ScheduleParseRefusal,
    extract_pdf_text_objects,
)
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
        ("encrypted_pdf", "user_password"): pdfium_c.FPDF_ERR_PASSWORD,
        ("encrypted_pdf", "unknown_filter"): pdfium_c.FPDF_ERR_SECURITY,
    }
    for (family, variant), code in expected.items():
        with pytest.raises(pdfium.PdfiumError) as caught:
            pdfium.PdfDocument(gen.build(family, variant).pdf)
        assert caught.value.err_code == code, (family, variant)
    # The empty page tree fails to load without recording an error of its own
    # (see `test_a_stale_pdfium_error_never_decides_the_refusal`).
    with pytest.raises(pdfium.PdfiumError):
        pdfium.PdfDocument(gen.build("wrong_page_size", "zero_pages").pdf)
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


# --- pdf.py and the parse entry point (contract 10.4) ---------------------------

D = Decimal
R, B = gen.REGULAR, gen.BOLD
NAME = "Synthetic activity 001"
NO_BUDGET = ParseBudget(lambda: 0.0, None)


def _probe(*draws: gen.Draw, fonts: list[gen.FontSpec] | None = None) -> bytes:
    page = gen.PageSpec(draws=tuple(draws))
    return gen.assemble_document((page,), fonts if fonts is not None else gen.default_fonts())


def _extract(pdf: bytes, limits: ScheduleParseLimits = PRODUCTION_LIMITS) -> PdfDocumentText:
    return extract_pdf_text_objects(pdf, limits=limits, budget=NO_BUDGET)


def _texts(pdf: bytes) -> list[str]:
    return [o.text for o in _extract(pdf).pages[0].objects]


def _draw(
    text: str, x: str = "134", y: str = "600", font: str = R, size: str = "7", **kw: object
) -> gen.Draw:
    return gen.Draw(text, font, D(size), D(x), D(y), **kw)  # type: ignore[arg-type]


def _refusal(call: Callable[[], object]) -> ScheduleParseRefusal:
    with pytest.raises(ScheduleParseRefusal) as caught:
        call()
    return caught.value


def _parse_case(case: gen.FixtureCase, **overrides: object) -> ScheduleParseResult:
    limits = ScheduleParseLimits(**case.limits) if case.limits else PRODUCTION_LIMITS
    kwargs: dict[str, Any] = {
        "expected_data_date": case.expected_data_date,
        "limits": limits,
        "clock": gen.fake_clock(case.clock_calls_before_expiry),
        "deadline": None if case.clock_calls_before_expiry is None else 1.0,
    }
    kwargs.update(overrides)
    return parse_full_schedule(case.pdf, **kwargs)


def _only_issue(result: ScheduleParseResult) -> tuple[ScheduleIssueCode, int | None]:
    assert result.outcome is SchedulePublicationStatus.FAILED
    assert result.rows == ()
    (issue,) = result.issues
    return issue.code, issue.page_number


def test_object_text_is_attributed_non_generated_characters() -> None:
    """Contract 2.4's measured table, re-measured on the fixture fonts.

    A PDFium change in what the text page attributes fails here first. The
    suppression envelope is PDFium-internal (U-15): on these Type3 fonts at
    7 pt the 22-character name is suppressed up to at least 3.0 pt and not at
    3.4 pt (the R5 probe measured "not at 2.0 pt" with other glyph widths).
    """
    for dx in ("0.1", "0.25", "0.3", "0.5", "1.0", "2.0", "3.0"):
        assert _texts(_probe(_draw(NAME), _draw(NAME, str(134 + D(dx))))) == [NAME, ""], dx
    for dx in ("3.4", "4.0"):
        assert _texts(_probe(_draw(NAME), _draw(NAME, str(134 + D(dx))))) == [NAME, NAME], dx
    assert _texts(_probe(_draw(NAME), _draw(NAME), _draw(NAME, "134.2"))) == [NAME, "", ""]
    for dx in ("0.3", "0.5", "1.0"):
        assert _texts(_probe(_draw("5"), _draw("5", str(134 + D(dx))))) == ["5", ""], dx
    for dx in ("2.0", "3.6"):
        assert _texts(_probe(_draw("5"), _draw("5", str(134 + D(dx))))) == ["5", "5"], dx
    for dx in ("0", "0.3"):
        assert _texts(_probe(_draw("5"), _draw("8", str(134 + D(dx))))) == ["5", "8"], dx
    for first, second, x in ((R, B, "134"), (B, R, "134"), (R, B, "134.3")):
        assert _texts(_probe(_draw("Same", font=first), _draw("Same", x, font=second))) == [
            "Same",
            "",
        ]
    assert _texts(_probe(_draw("Same"), _draw("Same", y="600.3"))) == ["Same", ""]
    # Whitespace runs inside one object are reported collapsed (D-30).
    assert _texts(_probe(_draw("SYN  1000"))) == ["SYN 1000"]
    assert _texts(_probe(_draw("  Pad  "))) == [" Pad "]
    tab = _extract(_probe(_draw("A\tB  C"))).pages[0].objects
    assert [o.text for o in tab] == ["A\tB C"]
    assert tab[0].unmapped  # code 9 is outside this font's mapped range
    # Generated separators never reach an object's text.
    line = _probe(_draw("SYN-1000", "60.30"), _draw(NAME), _draw("5", "492.5"))
    assert _texts(line) == ["SYN-1000", NAME, "5"]
    assert _texts(_probe(_draw("Dup"), _draw("Dup", "620"))) == ["Dup", "Dup"]
    assert _texts(_probe(_draw("Dup"), _draw("Dup", y="585"))) == ["Dup", "Dup"]
    # `() Tj` makes no object at all; `( ) Tj` is a 1-space object that counts
    # toward the caps and is then dropped as whitespace-only evidence.
    empty = _probe(_draw(""), _draw("x", "200"))
    assert [(o.object_ordinal, o.text) for o in _extract(empty).pages[0].objects] == [(0, "x")]
    space = _probe(_draw(" "), _draw("x", "200"))
    assert [(o.object_ordinal, o.text) for o in _extract(space).pages[0].objects] == [(1, "x")]
    capped = _refusal(lambda: _extract(space, ScheduleParseLimits(max_text_objects=1)))
    assert capped.code is ScheduleIssueCode.BOUNDS_EXCEEDED
    # Without /ToUnicode PDFium falls back to the code with the error flag set.
    fonts = [*gen.default_fonts(), gen.FontSpec(gen.UNMAPPED, "Arial", to_unicode=False)]
    (unmapped,) = _extract(_probe(_draw(NAME, font=gen.UNMAPPED), fonts=fonts)).pages[0].objects
    assert (unmapped.text, unmapped.unmapped) == (NAME, True)


def test_no_generated_character_enters_evidence() -> None:
    case = gen.build("full_valid_2p", "base")
    drawn = [[d.text for d in spec.draws] for spec in case.pages]
    extracted = [[o.text for o in page.objects] for page in _extract(case.pdf).pages]
    assert extracted == drawn
    result = _parse_case(case)
    raws = [f.raw for row in result.rows for cell in row.cells for f in cell.fragments]
    assert raws
    assert all(raw == raw.strip() and "\r" not in raw and "\n" not in raw for raw in raws)
    assert {"SYN-1000", "Synthetic activity 001", "04-May-26"} <= set(raws)


def _suppressed(pdf: bytes) -> PdfTextObject:
    (obj,) = [o for o in _extract(pdf).pages[0].objects if o.suppressed]
    return obj


def _zero_tz(pdf: bytes) -> bytes:
    index = pdf.index(b"100 Tz")
    return pdf[:index] + b"  0 Tz" + pdf[index + 6 :]


def _known(obj: PdfTextObject) -> ProfileTextObject:
    return ProfileTextObject(obj, obj.text)


def _object(
    text: str,
    box: tuple[int, int, int, int],
    ordinal: int,
    *,
    suppressed: bool = False,
    font: str = "Arial",
) -> PdfTextObject:
    return PdfTextObject(
        page_number=1,
        object_ordinal=ordinal,
        text="" if suppressed else text,
        suppressed=suppressed,
        unmapped=False,
        font_base_name=font,
        font_embedded=True,
        font_size_mpt=7_000,
        box=ScheduleBox(*box),
        matrix=(D(1), D(0), D(0), D(1), D(0), D(0)),
    )


def _zones(*objects: PdfTextObject) -> dict[int, ProfileTextObject]:
    zones = exclude_profile_non_data(PdfPageText(1, 1_224_000, 792_000, objects), gen_profile())
    return {o.ordinal: o for o in (*zones.metadata_objects, *zones.table_objects)}


def gen_profile() -> Any:  # noqa: ANN401 - the frozen profile, imported lazily for brevity
    from my_pa.infrastructure.schedule import P6_FULL_V1

    return P6_FULL_V1


def _classify_rows(*objects: ProfileTextObject) -> list[Any]:
    rows: list[Any] = []
    previous: PdfPhysicalRow | None = None
    for row in group_table_rows_by_overlap(objects, page_number=1):
        rows.append(classify_full_row(assign_full_cells(row), previous, row_ordinal=len(rows) + 1))
        previous = row
    return rows


def test_suppressed_objects_resolve_deterministically() -> None:
    # RR1-F02 causes, measured: 0 Tf, 0 Tz and out-of-range codes give 0
    # attributed characters and a zero-area box, which is always twinless.
    zero_tf = _suppressed(_probe(_draw("SYN", size="0"), _draw("x", "200")))
    zero_tz = _suppressed(_zero_tz(_probe(_draw("SYN"), _draw("x", "200"))))
    codes = _suppressed(_probe(_draw("", "480", codes=b"\x0a\x0b"), _draw("x", "200")))
    for obj in (zero_tf, zero_tz, codes):
        assert (obj.box.x1 - obj.box.x0) * (obj.box.y1 - obj.box.y0) == 0
    for obj in (zero_tf, codes):
        assert _zones(obj)[obj.object_ordinal].text is None
    # Measured: `0 Tz` folds into the object matrix (a == 0), so in the data
    # zone the object is not near-horizontal and V10 refuses the page first.
    assert zero_tz.matrix[0] == 0
    refused = _refusal(lambda: _zones(zero_tz))
    assert (refused.code, refused.page_number) == (ScheduleIssueCode.UNSUPPORTED_LAYOUT, 1)
    # A same-text copy takes its twin's text; a copy whose candidates disagree
    # is twinless, never first-write-wins.
    original = _object(NAME, (134_000, 598_600, 211_000, 604_900), 0)
    copy = _object(NAME, (134_300, 598_600, 211_300, 604_900), 1, suppressed=True)
    resolved = _zones(original, copy)[1]
    assert (resolved.text, resolved.twin) == (NAME, 0)
    other = _object("Other text", (200_000, 598_600, 235_000, 604_900), 2)
    assert _zones(original, copy, other)[1].text is None
    # RR1-F03: a split name whose second fragment is duplicated at +0.1 pt
    # takes the second fragment's text, never the first's.
    first = _object("Synthetic", (134_000, 598_600, 165_500, 604_900), 0)
    second = _object("activity 004", (165_500, 598_600, 207_500, 604_900), 1)
    dup = _object("activity 004", (165_600, 598_600, 207_600, 604_900), 2, suppressed=True)
    assert (_zones(first, second, dup)[2].text, _zones(first, second, dup)[2].twin) == (
        "activity 004",
        1,
    )
    # The twin is the candidate with the largest intersection, not the lowest ordinal.
    five_a = _object("5", (458_000, 598_600, 461_500, 604_900), 0)
    five_b = _object("5", (460_000, 598_600, 463_500, 604_900), 1)
    five_c = _object("5", (459_800, 598_600, 463_300, 604_900), 2, suppressed=True)
    assert _zones(five_a, five_b, five_c)[2].twin == 1
    # RR1-F04: a suppressed object and its twin in one cell always overlap,
    # even when their x-intersection (200 mpt) is under the 250 mpt test.
    name = _object("Synthetic", (134_000, 598_600, 165_500, 604_900), 0)
    shifted = _object("Synthetic", (165_300, 598_600, 196_800, 604_900), 1, suppressed=True)
    ident = _object("SYN-1", (60_300, 598_600, 77_800, 604_900), 2)
    zones = _zones(name, shifted, ident)
    (row,) = _classify_rows(*zones.values())
    name_cell = row.assigned.cells[1]
    assert name_cell.state is ScheduleCellState.AMBIGUOUS
    assert (ScheduleIssueCode.OVERLAPPING_CELL_TEXT, ScheduleFieldCode.ACTIVITY_NAME) in row.issues
    # The zero-char fixture: the twinless object is an unknown-text fragment
    # that makes its own cell ambiguous and contributes no text.
    result = _parse_case(gen.build("full_overlapping_cell_text", "zero_char_object"))
    rd = result.rows[3].cells[3]
    assert (rd.state, rd.text, [f.raw for f in rd.fragments]) == (
        ScheduleCellState.AMBIGUOUS,
        "5",
        ["", "5"],
    )
    assert result.counts.suppressed_objects == 1


def test_unmapped_characters_make_the_cell_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    case = gen.build("full_overlapping_cell_text", "unmapped")
    row = _parse_case(case).rows[3]
    assert row.row_type is ScheduleRowType.AMBIGUOUS
    assert row.cells[1].state is ScheduleCellState.AMBIGUOUS
    real = pdfium_c.FPDFText_GetUnicode
    for replacement in (0xD800, 0x0):
        # Only the `f` after "Synthetic " ("Synthetic finish milestone", page 2)
        # is rewritten; the `f` of "Summary Page n of m" keeps its code.
        history: list[int] = []

        def fake(
            textpage: object, index: int, value: int = replacement, seen: list[int] = history
        ) -> int:
            code = int(real(textpage, index))
            seen.append(code)
            return value if seen[-3:] == [ord("c"), ord(" "), ord("f")] else code

        monkeypatch.setattr(pdfium_c, "FPDFText_GetUnicode", fake)
        base = gen.build("full_valid_2p", "base")
        result = _parse_case(base)
        (row,) = [r for r in result.rows if r.cells[0].text == "SYN-1005"]
        assert row.row_type is ScheduleRowType.AMBIGUOUS
        assert row.cells[1].state is ScheduleCellState.AMBIGUOUS
        assert row.cells[1].text == "Synthetic �inish milestone"
        assert result.outcome is SchedulePublicationStatus.REVIEW_REQUIRED
        assert b"\\ud800" not in canonical_json_bytes(parse_result_object(result))
        monkeypatch.setattr(pdfium_c, "FPDFText_GetUnicode", real)


def test_unknown_character_handle_is_parser_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    real = pdfium_c.FPDFText_GetTextObject
    stray = ctypes.c_void_p(0xDEAD0)

    def fake(textpage: object, index: int) -> object:
        return stray if index == 0 else real(textpage, index)

    monkeypatch.setattr(pdfium_c, "FPDFText_GetTextObject", fake)
    result = _parse_case(gen.build("full_valid_2p", "base"))
    assert _only_issue(result) == (ScheduleIssueCode.PARSER_EXCEPTION, None)


def test_zero_height_own_row_is_placed_by_the_seed_key() -> None:
    upper = _object("SYN-1", (60_300, 598_600, 77_800, 604_900), 0)
    lower = _object("SYN-2", (60_300, 568_600, 77_800, 574_900), 1)
    ghost = _object("", (480_000, 585_000, 480_000, 585_000), 2, suppressed=True)
    objects = [ProfileTextObject.of(o) for o in (ghost, lower, upper)]
    rows = group_table_rows_by_overlap(objects, page_number=1)
    assert [r.seed.ordinal for r in rows] == [0, 2, 1]
    assert [r.physical_line_ordinal for r in rows] == [1, 2, 3]
    # Contained in a seed interval, it joins that row and never seeds.
    inside = _object("", (480_000, 600_000, 480_000, 600_000), 3, suppressed=True)
    rows = group_table_rows_by_overlap(
        [ProfileTextObject.of(o) for o in (upper, inside)], page_number=1
    )
    assert [[o.ordinal for o in r.objects] for r in rows] == [[0, 3]]


def test_unknown_text_fragment_does_not_decide_the_row_case() -> None:
    def ghost(x: int, y: int, ordinal: int, font: str = "Arial") -> ProfileTextObject:
        box = (x, y, x, y)
        return ProfileTextObject.of(_object("", box, ordinal, suppressed=True, font=font))

    def values(y: int, start: int) -> list[ProfileTextObject]:
        return [
            _known(_object("6", (461_500, y - 1_400, 465_000, y + 4_900), start)),
            _known(_object("08-Jun-26", (501_000, y - 1_400, 532_500, y + 4_900), start + 1)),
        ]

    missing = (ScheduleIssueCode.ACTIVITY_LIKE_ROW_MISSING_ID, ScheduleFieldCode.ACTIVITY_ID)
    id_cell = (ScheduleIssueCode.AMBIGUOUS_CELL, ScheduleFieldCode.ACTIVITY_ID)
    # RR2-F03: a missing-ID row plus a zero-area object in the ID band.
    (row,) = _classify_rows(*values(600_000, 0), ghost(70_000, 600_000, 9))
    assert {missing, id_cell} <= set(row.issues)
    # A wrap line plus such an object in a value band is still a wrap.
    label = _known(_object("Synthetic Stage", (60_300, 598_600, 112_800, 604_900), 0))
    head = [label, *values(600_000, 1)]
    cont = _known(_object("continued", (134_000, 590_600, 165_500, 596_900), 5))
    rows = _classify_rows(*head, cont, ghost(480_000, 592_000, 9))
    assert (ScheduleIssueCode.ROW_WRAP_UNSUPPORTED, None) in rows[1].issues
    # RR3-F01: a row of only a zero-area object: AMBIGUOUS_CELL, no missing ID.
    (row,) = _classify_rows(ghost(480_000, 600_000, 9))
    assert missing not in row.issues
    assert (ScheduleIssueCode.AMBIGUOUS_CELL, None) in row.issues
    assert row.row_type is ScheduleRowType.AMBIGUOUS
    # RR3-F02: out-of-grid or OTHER-font unknown fragments leave the row type.
    ident = _known(_object("SYN-1", (60_300, 598_600, 77_800, 604_900), 0))
    name = _known(_object(NAME, (134_000, 598_600, 211_000, 604_900), 1))
    rest = [
        *values(600_000, 2),
        _known(_object("5", (492_500, 598_600, 496_000, 604_900), 4)),
        _known(_object("15-May-26", (562_000, 598_600, 593_500, 604_900), 5)),
    ]
    (row,) = _classify_rows(ident, name, *rest, ghost(30_000, 600_000, 9))
    assert row.row_type is ScheduleRowType.ACTIVITY
    assert (ScheduleIssueCode.AMBIGUOUS_CELL, None) in row.issues
    (row,) = _classify_rows(ident, name, *rest, ghost(480_000, 600_000, 9, font="Courier"))
    assert row.row_type is ScheduleRowType.ACTIVITY
    assert row.assigned.cells[3].state is ScheduleCellState.AMBIGUOUS


# --- caps, budget, refusals -------------------------------------------------------


@dataclass
class _Calls:
    opened: int = 0
    pages: int = 0
    textpages: int = 0
    unicode: int = 0
    clock: int = 0


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Calls]:
    seen = _Calls()
    real_get_page = pdfium.PdfDocument.get_page
    real_textpage = pdfium.PdfPage.get_textpage
    real_unicode = pdfium_c.FPDFText_GetUnicode
    real_document = pdfium.PdfDocument

    class Counting(real_document):  # type: ignore[misc, valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            seen.opened += 1

    def get_page(self: Any, index: int) -> Any:  # noqa: ANN401
        seen.pages += 1
        return real_get_page(self, index)

    def get_textpage(self: Any) -> Any:  # noqa: ANN401
        seen.textpages += 1
        return real_textpage(self)

    def unicode(textpage: object, index: int) -> int:
        seen.unicode += 1
        return int(real_unicode(textpage, index))

    monkeypatch.setattr(pdfium, "PdfDocument", Counting)
    monkeypatch.setattr(real_document, "get_page", get_page)
    monkeypatch.setattr(pdfium.PdfPage, "get_textpage", get_textpage)
    monkeypatch.setattr(pdfium_c, "FPDFText_GetUnicode", unicode)
    yield seen


def test_byte_cap_is_checked_before_pdfium_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("PdfDocument must not be called past the byte cap")

    monkeypatch.setattr(pdfium, "PdfDocument", forbidden)
    case = gen.build("bounds_exceeded", "bytes")
    assert _only_issue(_parse_case(case)) == (ScheduleIssueCode.SOURCE_TOO_LARGE, None)
    tight = ScheduleParseLimits(max_bytes=100)
    small = gen.build("full_valid_2p", "base")
    refusal = _refusal(lambda: extract_pdf_text_objects(small.pdf, limits=tight, budget=NO_BUDGET))
    assert refusal.code is ScheduleIssueCode.SOURCE_TOO_LARGE
    assert _only_issue(parse_full_schedule(b"not a pdf")) == (
        ScheduleIssueCode.UNSUPPORTED_MEDIA_TYPE,
        None,
    )


def test_page_cap_is_checked_before_any_page_loads(calls: _Calls) -> None:
    result = _parse_case(gen.build("bounds_exceeded", "pages"))
    assert _only_issue(result) == (ScheduleIssueCode.BOUNDS_EXCEEDED, None)
    assert (calls.opened, calls.pages) == (1, 0)
    # A size refusal (V6) also precedes every page load.
    letter = _parse_case(gen.build("wrong_page_size", "letter"))
    assert _only_issue(letter) == (ScheduleIssueCode.UNSUPPORTED_LAYOUT, 1)
    assert calls.pages == 0


def test_object_and_char_caps_stop_before_the_next_page(calls: _Calls) -> None:
    case = gen.build("full_valid_2p", "base")
    for limits, textpages in (
        (ScheduleParseLimits(max_page_objects=20), 0),
        (ScheduleParseLimits(max_text_objects=20), 0),
        (ScheduleParseLimits(max_text_chars=200), 1),
    ):
        calls.pages = calls.textpages = calls.unicode = 0
        result = parse_full_schedule(case.pdf, limits=limits)
        assert _only_issue(result) == (ScheduleIssueCode.BOUNDS_EXCEEDED, None)
        # Page 1 only; the char cap is read before any character is.
        assert (calls.pages, calls.textpages, calls.unicode) == (1, textpages, 0), limits
    # The caps are cumulative: page 1 alone fits, page 1 + page 2 does not.
    first = _extract(case.pdf).pages[0]
    per_page = len(first.objects)
    calls.pages = 0
    result = parse_full_schedule(case.pdf, limits=ScheduleParseLimits(max_text_objects=per_page))
    assert _only_issue(result) == (ScheduleIssueCode.BOUNDS_EXCEEDED, None)
    assert calls.pages == 2


def test_corrupt_encrypted_and_image_only_fail_closed() -> None:
    expected = {
        ("corrupt_pdf", "garbage"): ScheduleIssueCode.CORRUPT_PDF,
        ("corrupt_pdf", "not_a_pdf"): ScheduleIssueCode.UNSUPPORTED_MEDIA_TYPE,
        ("corrupt_pdf", "empty"): ScheduleIssueCode.UNSUPPORTED_MEDIA_TYPE,
        ("encrypted_pdf", "user_password"): ScheduleIssueCode.ENCRYPTED_PDF,
        ("encrypted_pdf", "empty_user_password"): ScheduleIssueCode.ENCRYPTED_PDF,
        ("encrypted_pdf", "unknown_filter"): ScheduleIssueCode.ENCRYPTED_PDF,
        ("image_only_pdf", "base"): ScheduleIssueCode.IMAGE_ONLY_PDF,
        ("wrong_page_size", "zero_pages"): ScheduleIssueCode.CORRUPT_PDF,
    }
    for (family, variant), code in expected.items():
        result = _parse_case(gen.build(family, variant))
        assert _only_issue(result) == (code, None), (family, variant)
        assert result.counts.issues == 1
        assert result.published_schedule_title is None
    # Truncation anywhere is a closed refusal, never an exception.
    pdf = gen.build("full_valid_2p", "base").pdf
    for cut in (9, len(pdf) // 2, len(pdf) - 30):
        result = parse_full_schedule(pdf[:cut])
        assert result.outcome is SchedulePublicationStatus.FAILED
    with pytest.raises(TypeError):
        parse_full_schedule("%PDF-1.7")  # type: ignore[arg-type]


def test_a_stale_pdfium_error_never_decides_the_refusal() -> None:
    zero = gen.build("wrong_page_size", "zero_pages").pdf
    locked = gen.build("encrypted_pdf", "user_password").pdf
    # The hazard, measured: PDFium's last error is process-global and the
    # empty page tree does not overwrite it.
    with pytest.raises(pdfium.PdfiumError):
        pdfium.PdfDocument(locked)
    with pytest.raises(pdfium.PdfiumError) as caught:
        pdfium.PdfDocument(zero)
    assert caught.value.err_code == pdfium_c.FPDF_ERR_PASSWORD
    # The parser primes the error first, so history never leaks into the code.
    for before in (locked, gen.build("encrypted_pdf", "unknown_filter").pdf, b"%PDF-"):
        parse_full_schedule(before)
        assert _only_issue(parse_full_schedule(zero)) == (ScheduleIssueCode.CORRUPT_PDF, None)


def test_security_error_and_unknown_filter_are_encrypted() -> None:
    for variant in ("user_password", "empty_user_password", "unknown_filter"):
        case = gen.build("encrypted_pdf", variant)
        refusal = _refusal(lambda c=case: _extract(c.pdf))  # type: ignore[misc]
        assert refusal.code is ScheduleIssueCode.ENCRYPTED_PDF, variant
        assert refusal.__cause__ is None
        # Mapped from `PdfiumError` with `from None`: no chained source text.
        assert refusal.__suppress_context__ is (variant != "empty_user_password")


def test_page_origin_is_validated() -> None:
    for variant in ("rotated", "rotated_180", "offset_origin", "letter"):
        result = _parse_case(gen.build("wrong_page_size", variant))
        assert _only_issue(result) == (ScheduleIssueCode.UNSUPPORTED_LAYOUT, 1), variant
    pdf = gen.build("full_valid_2p", "base").pdf
    media = b"/MediaBox [0 0 1224 792]"
    same_crop = pdf.replace(media, media + b" /CropBox [0.2 0.2 1224 792]", 1)
    assert _parse_case(gen.build("full_valid_2p", "base")).outcome is (
        SchedulePublicationStatus.COMPLETE
    )
    assert parse_full_schedule(same_crop).outcome is SchedulePublicationStatus.COMPLETE
    other_crop = pdf.replace(media, media + b" /CropBox [0 0 1224 700]", 1)
    assert _only_issue(parse_full_schedule(other_crop)) == (
        ScheduleIssueCode.UNSUPPORTED_LAYOUT,
        1,
    )
    # A /MediaBox only inherited from the page tree cannot prove its origin
    # through `FPDFPage_GetMediaBox` (measured: it returns 0); fail closed.
    inherited = pdf.replace(media + b" ", b"").replace(
        b"/Type /Pages /Kids", b"/Type /Pages " + media + b" /Kids", 1
    )
    assert _only_issue(parse_full_schedule(inherited)) == (
        ScheduleIssueCode.UNSUPPORTED_LAYOUT,
        1,
    )


def test_form_xobject_text_is_unsupported_layout() -> None:
    for variant in ("form_text", "form_depth"):
        result = _parse_case(gen.build("bounds_exceeded", variant))
        assert _only_issue(result) == (ScheduleIssueCode.UNSUPPORTED_LAYOUT, 1), variant
    # A shallow form holding only a path is admitted.
    plan = gen._small_plan()
    spec = gen.PageSpec(tuple(plan.pages[0]), form=gen.FormSpec(depth=4, text=None))
    pdf = gen.assemble_document((spec,), plan.fonts)
    assert parse_full_schedule(pdf).outcome is SchedulePublicationStatus.COMPLETE
    # Nested objects count toward the all-object cap.
    tight = ScheduleParseLimits(max_page_objects=len(plan.pages[0]) + 3)
    assert _only_issue(parse_full_schedule(pdf, limits=tight)) == (
        ScheduleIssueCode.BOUNDS_EXCEEDED,
        None,
    )


def test_budget_refuses_at_first_and_mid_extraction_checkpoints(calls: _Calls) -> None:
    case = gen.build("full_valid_2p", "base")
    for k, pages in ((0, 0), (gen.TIME_MID_CALLS, 1)):
        counter = [0]
        inner = gen.fake_clock(k)

        def clock(inner: Callable[[], float] = inner, counter: list[int] = counter) -> float:
            counter[0] += 1
            return inner()

        calls.pages = calls.opened = 0
        result = parse_full_schedule(case.pdf, clock=clock, deadline=1.0)
        assert _only_issue(result) == (ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED, None)
        # k = 0: the checkpoint after V2, before PDFium opens anything.
        # k = 3: after V2, after open, before page 1; the 4th, before page 2, expires.
        assert (counter[0], calls.pages) == (k + 1, pages)
    assert calls.opened == 1
    # No deadline: the clock is never read.
    untouched = [0]

    def never() -> float:
        untouched[0] += 1
        return 1e9

    assert parse_full_schedule(case.pdf, clock=never).outcome is SchedulePublicationStatus.COMPLETE
    assert untouched == [0]


def test_refusals_carry_codes_only() -> None:
    refusal = ScheduleParseRefusal(ScheduleIssueCode.CORRUPT_PDF)
    assert str(refusal) == "corrupt_pdf"
    assert refusal.args == ("corrupt_pdf",)
    for family, variant in gen.CASES:
        case = gen.build(family, variant)
        if case.truth.outcome != gen.FAILED or family == "bounds_exceeded":
            continue
        result = _parse_case(case)
        data = canonical_json_bytes(parse_result_object(result))
        for secret in (b"Synthetic", b"SYN-", b"synthetic-user", b"garbage", b"not a pdf"):
            assert secret not in data, (case.name, secret)


@dataclass
class _Ledger:
    events: list[tuple[str, int]] = dataclasses.field(default_factory=list)
    opened: dict[str, list[int]] = dataclasses.field(default_factory=dict)


def test_handles_are_closed_on_every_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = _Ledger()
    real_document = pdfium.PdfDocument

    class Tracked(real_document):  # type: ignore[misc, valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            ledger.opened.setdefault("document", []).append(id(self))

    def tracking(kind: str, original: Callable[..., Any]) -> Callable[..., Any]:
        def close(self: Any) -> Any:  # noqa: ANN401
            ledger.events.append((kind, id(self)))
            return original(self)

        return close

    def opening(kind: str, original: Callable[..., Any]) -> Callable[..., Any]:
        def make(*args: Any) -> Any:  # noqa: ANN401
            made = original(*args)
            ledger.opened.setdefault(kind, []).append(id(made))
            return made

        return make

    monkeypatch.setattr(pdfium, "PdfDocument", Tracked)
    monkeypatch.setattr(real_document, "close", tracking("document", real_document.close))
    monkeypatch.setattr(real_document, "get_page", opening("page", real_document.get_page))
    monkeypatch.setattr(pdfium.PdfPage, "close", tracking("page", pdfium.PdfPage.close))
    monkeypatch.setattr(
        pdfium.PdfPage, "get_textpage", opening("textpage", pdfium.PdfPage.get_textpage)
    )
    monkeypatch.setattr(pdfium.PdfTextPage, "close", tracking("textpage", pdfium.PdfTextPage.close))
    exits = [
        (gen.build("full_valid_2p", "base"), {}),
        (gen.build("full_valid_2p", "base"), {"limits": ScheduleParseLimits(max_text_chars=200)}),
        (gen.build("full_valid_2p", "base"), {"limits": ScheduleParseLimits(max_text_objects=20)}),
        (gen.build("bounds_exceeded", "time_mid"), {}),
        (gen.build("wrong_page_size", "offset_origin"), {}),
        (gen.build("bounds_exceeded", "form_text"), {}),
        (gen.build("encrypted_pdf", "empty_user_password"), {}),
        (gen.build("image_only_pdf", "base"), {}),
        (gen.build("full_draft_watermark", "skew_1deg"), {}),
    ]
    for case, overrides in exits:
        ledger.events.clear()
        ledger.opened.clear()
        _parse_case(case, **overrides)
        order = {key: index for index, key in enumerate(ledger.events)}
        for kind in ("document", "page", "textpage"):
            for handle in ledger.opened.get(kind, []):
                assert (kind, handle) in order, (case.name, kind)
        # Innermost first, by the parser itself: a text page closes before its
        # page, and every page before the document (no reliance on cascades).
        document_closes = [i for (k, _h), i in order.items() if k == "document"]
        assert len(document_closes) == len(ledger.opened.get("document", [])) == 1, case.name
        for kind in ("page", "textpage"):
            for handle in ledger.opened.get(kind, []):
                assert order[(kind, handle)] < document_closes[0], (case.name, kind)
        if ledger.opened.get("textpage"):
            pages = [i for (k, _h), i in order.items() if k == "page"]
            texts = [i for (k, _h), i in order.items() if k == "textpage"]
            assert all(any(t < p for p in pages) for t in texts)


def test_extraction_is_identical_across_runs() -> None:
    for family, variant in (
        ("full_valid_2p", "base"),
        ("full_draft_watermark", "double_draw"),
        ("full_duplicate_text_object", "under_watermark"),
        ("full_overlapping_cell_text", "zero_char_object"),
    ):
        pdf = gen.build(family, variant).pdf
        assert _extract(pdf) == _extract(pdf)
        first, second = parse_full_schedule(pdf), parse_full_schedule(pdf)
        assert canonical_json_bytes(parse_result_object(first)) == canonical_json_bytes(
            parse_result_object(second)
        )
        assert parse_result_sha256(first) == parse_result_sha256(second)


def test_engine_provenance_is_outside_the_digest() -> None:
    result = _parse_case(gen.build("full_valid_2p", "base"))
    assert result.engine == schedule_pdf.engine_provenance()
    assert result.engine.pypdfium2_version == str(pdfium.version.PYPDFIUM_INFO)
    assert result.engine.pdfium_version == str(pdfium.version.PDFIUM_INFO)
    other = dataclasses.replace(result, engine=ScheduleParseEngine("1.2.3", "4.5.6.7"))
    assert parse_result_sha256(other) == parse_result_sha256(result)
    canonical = canonical_json_bytes(parse_result_object(result))
    assert canonical == canonical_json_bytes(parse_result_object(other))
    assert "engine" not in parse_result_object(result)
    for version in (result.engine.pypdfium2_version, result.engine.pdfium_version):
        assert version.encode("ascii") not in canonical
    golden = gen.golden_path("full_valid_2p", "base").read_bytes()
    assert b"engine" not in golden
    assert result.engine.pdfium_version.encode("ascii") not in golden
