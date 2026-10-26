"""CPM Workbench S5a: the only PDFium code in the Full-Schedule plane.

Contract: `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
sections 2.3, 2.4, 3.5, 5.2 (V1-V9) and 7. This module opens admitted bytes
in memory, validates the container, and returns every top-level text object's
geometry, font, size, matrix and attributed text under the injected caps and
processing budget. It never renders, never initializes forms, never reads
actions, links, annotations or attachments, and never touches a file, the
environment or the clock (the budget's clock is injected).

Text comes only from the text page (section 2.4): for each top-level text
object, the characters `FPDFText_GetTextObject` attributes to it, in
character-index order, skipping generated characters. An object with no
attributed character is `suppressed`. Every raw `pypdfium2.raw` return value is
converted to a concrete Python type at the call site, so no `Any` escapes.

Refusals carry a closed issue code (and, when page-specific, the 1-based page
number) and never any source text; `PdfiumError` is mapped with `from None`.
"""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Final, Protocol

import pypdfium2 as pdfium  # type: ignore[import-untyped]
import pypdfium2.raw as pdfium_c  # type: ignore[import-untyped]

from my_pa.domain.schedule import (
    ScheduleBox,
    ScheduleIssueCode,
    ScheduleParseEngine,
    normalized_box_strings,
)

__all__ = [
    "ParseBudget",
    "PdfDocumentText",
    "PdfPageText",
    "PdfTextObject",
    "ScheduleParseRefusal",
    "engine_provenance",
    "extract_pdf_text_objects",
    "to_millipoints",
]

_PDF_MAGIC: Final = b"%PDF-"
_ENCRYPTED_OPEN_ERRORS: Final = frozenset({pdfium_c.FPDF_ERR_PASSWORD, pdfium_c.FPDF_ERR_SECURITY})
#: Contract 4.2: the page frame, its tolerance and the origin rule.
_PAGE_WIDTH_MPT: Final = 1_224_000
_PAGE_HEIGHT_MPT: Final = 792_000
_PAGE_TOLERANCE_MPT: Final = 500
#: Contract 5.1: a budget checkpoint after every this many objects of a page.
_OBJECT_CHECKPOINT_EVERY: Final = 1_000
_REPLACEMENT: Final = "�"
_MAX_CODE_POINT: Final = 0x10FFFF


class ScheduleParseRefusal(Exception):  # noqa: N818 - contract 3.5 name
    """A closed refusal. `str(exc)` is the code's value; it never holds source text."""

    def __init__(self, code: ScheduleIssueCode, page_number: int | None = None) -> None:
        super().__init__(code.value)
        self.code = code
        #: The 1-based page a page-specific refusal concerns (contract 5.14), or `None`.
        self.page_number = page_number


class ExtractionLimits(Protocol):
    """The `ScheduleParseLimits` fields extraction reads (V1, V5, V8)."""

    @property
    def max_bytes(self) -> int: ...
    @property
    def max_pages(self) -> int: ...
    @property
    def max_text_objects(self) -> int: ...
    @property
    def max_page_objects(self) -> int: ...
    @property
    def max_text_chars(self) -> int: ...
    @property
    def max_form_depth(self) -> int: ...


@dataclass(frozen=True, slots=True)
class ParseBudget:
    """A cooperative deadline over an injected clock (contract 5.15)."""

    clock: Callable[[], float]
    deadline: float | None

    def checkpoint(self) -> None:
        if self.deadline is not None and self.clock() > self.deadline:
            raise ScheduleParseRefusal(ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED)


@dataclass(frozen=True, slots=True)
class PdfTextObject:
    """One top-level text object as PDFium's text page presents it."""

    page_number: int
    #: 0-based index among the page's top-level objects (all types).
    object_ordinal: int
    #: Attributed non-generated characters (section 2.4); `""` iff suppressed.
    text: str
    suppressed: bool
    #: Any attributed character had a Unicode-map error, NUL or a surrogate.
    unmapped: bool
    font_base_name: str
    font_embedded: bool
    font_size_mpt: int
    box: ScheduleBox
    matrix: tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]

    def __post_init__(self) -> None:
        if (self.text == "") != self.suppressed:
            raise ValueError("a text object's text is empty iff it is suppressed")

    def normalized_box(self, page: PdfPageText) -> list[str]:
        """R2 section 12.3 normalized box against the page's measured size."""
        return normalized_box_strings(self.box, page.width_mpt, page.height_mpt)


@dataclass(frozen=True, slots=True)
class PdfPageText:
    page_number: int
    width_mpt: int
    height_mpt: int
    objects: tuple[PdfTextObject, ...]


@dataclass(frozen=True, slots=True)
class PdfDocumentText:
    page_count: int
    pages: tuple[PdfPageText, ...]


def to_millipoints(value: float) -> int:
    """Contract 4.1: exact `Decimal(float)` scaled to millipoints, half-even."""
    return int(Decimal(value).scaleb(3).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def engine_provenance() -> ScheduleParseEngine:
    """The installed PDFium build, carried beside (never inside) the digest."""
    return ScheduleParseEngine(
        pypdfium2_version=str(pdfium.version.PYPDFIUM_INFO),
        pdfium_version=str(pdfium.version.PDFIUM_INFO),
    )


def _handle(pointer: Any) -> int | None:  # noqa: ANN401 - raw ctypes handle
    value = ctypes.cast(pointer, ctypes.c_void_p).value
    return None if value is None else int(value)


@dataclass
class _Tally:
    """Cumulative counts the V8 caps compare against."""

    text_objects: int = 0
    page_objects: int = 0
    text_chars: int = 0
    readable: bool = False


def extract_pdf_text_objects(
    data: bytes, *, limits: ExtractionLimits, budget: ParseBudget
) -> PdfDocumentText:
    """Validate V1-V9 (contract 5.2) and return every page's text objects."""
    if len(data) > limits.max_bytes:
        raise ScheduleParseRefusal(ScheduleIssueCode.SOURCE_TOO_LARGE)
    if not data.startswith(_PDF_MAGIC):
        raise ScheduleParseRefusal(ScheduleIssueCode.UNSUPPORTED_MEDIA_TYPE)
    budget.checkpoint()
    document = _open(data)
    try:
        budget.checkpoint()
        if int(pdfium_c.FPDF_GetSecurityHandlerRevision(document.raw)) != -1:
            raise ScheduleParseRefusal(ScheduleIssueCode.ENCRYPTED_PDF)
        page_count = len(document)
        if page_count == 0:
            raise ScheduleParseRefusal(ScheduleIssueCode.UNSUPPORTED_LAYOUT)
        if page_count > limits.max_pages:
            raise ScheduleParseRefusal(ScheduleIssueCode.BOUNDS_EXCEEDED)
        sizes = [_page_size(document, index) for index in range(page_count)]
        tally = _Tally()
        pages = tuple(
            _extract_page(document, index, size, limits, budget, tally)
            for index, size in enumerate(sizes)
        )
        if not tally.readable:
            raise ScheduleParseRefusal(ScheduleIssueCode.IMAGE_ONLY_PDF)
        return PdfDocumentText(page_count=page_count, pages=pages)
    finally:
        document.close()


#: PDFium refuses these bytes with `FPDF_ERR_FORMAT` at both pinned versions.
_ERROR_PRIMER: Final = b"%PDF-"


def _prime_last_error() -> None:
    """Set PDFium's process-global last error to `FPDF_ERR_FORMAT`.

    Measured at 5.0.0 and 5.13.0: a load that fails without recording an error
    (an empty page tree reports "Success") leaves `err_code` at whatever an
    earlier failed load recorded, so an unrelated encrypted file opened before
    would turn a corrupt file into `ENCRYPTED_PDF`. Priming makes the mapping a
    function of the input bytes alone; an unrecorded failure maps to `CORRUPT_PDF`.
    """
    try:
        primer = pdfium.PdfDocument(_ERROR_PRIMER)
    except pdfium.PdfiumError:
        return
    primer.close()


def _open(data: bytes) -> pdfium.PdfDocument:
    _prime_last_error()
    try:
        return pdfium.PdfDocument(data)
    except pdfium.PdfiumError as error:
        code = (
            ScheduleIssueCode.ENCRYPTED_PDF
            if getattr(error, "err_code", None) in _ENCRYPTED_OPEN_ERRORS
            else ScheduleIssueCode.CORRUPT_PDF
        )
        raise ScheduleParseRefusal(code) from None


def _page_size(document: pdfium.PdfDocument, index: int) -> tuple[int, int]:
    """V6: the page size by index, checked for every page before any load."""
    size = pdfium_c.FS_SIZEF()
    if not pdfium_c.FPDF_GetPageSizeByIndexF(document.raw, index, ctypes.byref(size)):
        raise ScheduleParseRefusal(ScheduleIssueCode.UNSUPPORTED_LAYOUT, index + 1)
    width, height = to_millipoints(float(size.width)), to_millipoints(float(size.height))
    if (
        abs(width - _PAGE_WIDTH_MPT) > _PAGE_TOLERANCE_MPT
        or abs(height - _PAGE_HEIGHT_MPT) > _PAGE_TOLERANCE_MPT
    ):
        raise ScheduleParseRefusal(ScheduleIssueCode.UNSUPPORTED_LAYOUT, index + 1)
    return width, height


def _edges(getter: Callable[..., Any], page: pdfium.PdfPage) -> tuple[int, ...] | None:
    left, bottom, right, top = (ctypes.c_float() for _ in range(4))
    if not getter(page.raw, left, bottom, right, top):
        return None
    return tuple(to_millipoints(float(edge.value)) for edge in (left, bottom, right, top))


def _check_page_frame(page: pdfium.PdfPage, page_number: int) -> None:
    """V7: rotation 0, MediaBox origin at (0, 0), CropBox (if any) equal to it."""
    refusal = ScheduleParseRefusal(ScheduleIssueCode.UNSUPPORTED_LAYOUT, page_number)
    if int(pdfium_c.FPDFPage_GetRotation(page.raw)) != 0:
        raise refusal
    media = _edges(pdfium_c.FPDFPage_GetMediaBox, page)
    # A page whose own dictionary carries no /MediaBox cannot prove its origin
    # through this call; it is refused (fail closed).
    if media is None or abs(media[0]) > _PAGE_TOLERANCE_MPT or abs(media[1]) > _PAGE_TOLERANCE_MPT:
        raise refusal
    crop = _edges(pdfium_c.FPDFPage_GetCropBox, page)
    if crop is not None and any(
        abs(a - b) > _PAGE_TOLERANCE_MPT for a, b in zip(crop, media, strict=True)
    ):
        raise refusal


def _extract_page(
    document: pdfium.PdfDocument,
    index: int,
    size: tuple[int, int],
    limits: ExtractionLimits,
    budget: ParseBudget,
    tally: _Tally,
) -> PdfPageText:
    page_number = index + 1
    budget.checkpoint()
    page = document.get_page(index)
    try:
        _check_page_frame(page, page_number)
        text_handles = _count_objects(page, page_number, limits, budget, tally)
        textpage = page.get_textpage()
        try:
            tally.text_chars += int(pdfium_c.FPDFText_CountChars(textpage.raw))
            if tally.text_chars > limits.max_text_chars:
                raise ScheduleParseRefusal(ScheduleIssueCode.BOUNDS_EXCEEDED)
            objects = _attributed_objects(textpage, page_number, text_handles)
        finally:
            textpage.close()
    finally:
        page.close()
    if any(not obj.text.isspace() and obj.text for obj in objects):
        tally.readable = True
    return PdfPageText(
        page_number=page_number,
        width_mpt=size[0],
        height_mpt=size[1],
        # Whitespace-only objects counted toward the caps above; they are
        # never evidence (contract 5.2). Suppressed objects are kept.
        objects=tuple(obj for obj in objects if obj.suppressed or not obj.text.isspace()),
    )


@dataclass
class _Draft:
    ordinal: int
    pointer: Any
    chars: list[str]
    unmapped: bool = False


def _count_objects(
    page: pdfium.PdfPage,
    page_number: int,
    limits: ExtractionLimits,
    budget: ParseBudget,
    tally: _Tally,
) -> dict[int, _Draft]:
    """V8 object caps and the form rule, before any text of the page is read."""
    count = int(pdfium_c.FPDFPage_CountObjects(page.raw))
    tally.page_objects += count
    if tally.page_objects > limits.max_page_objects:
        raise ScheduleParseRefusal(ScheduleIssueCode.BOUNDS_EXCEEDED)
    drafts: dict[int, _Draft] = {}
    for ordinal in range(count):
        if ordinal and ordinal % _OBJECT_CHECKPOINT_EVERY == 0:
            budget.checkpoint()
        pointer = pdfium_c.FPDFPage_GetObject(page.raw, ordinal)
        kind = int(pdfium_c.FPDFPageObj_GetType(pointer))
        if kind == pdfium_c.FPDF_PAGEOBJ_TEXT:
            tally.text_objects += 1
            key = _handle(pointer)
            if key is None:
                raise ScheduleParseRefusal(ScheduleIssueCode.PARSER_EXCEPTION)
            drafts[key] = _Draft(ordinal, pointer, [])
        elif kind == pdfium_c.FPDF_PAGEOBJ_FORM:
            nested_objects, nested_text = _walk_form(pointer, 1, limits, page_number)
            tally.page_objects += nested_objects
            tally.text_objects += nested_text
            if tally.page_objects > limits.max_page_objects:
                raise ScheduleParseRefusal(ScheduleIssueCode.BOUNDS_EXCEEDED)
            if nested_text:
                # D-09: nested bounds are form-space; text in a form is refused.
                raise ScheduleParseRefusal(ScheduleIssueCode.UNSUPPORTED_LAYOUT, page_number)
    if tally.text_objects > limits.max_text_objects:
        raise ScheduleParseRefusal(ScheduleIssueCode.BOUNDS_EXCEEDED)
    return drafts


def _walk_form(
    form: Any,  # noqa: ANN401 - raw ctypes handle
    depth: int,
    limits: ExtractionLimits,
    page_number: int,
) -> tuple[int, int]:
    """(nested objects, nested text objects) below one form XObject."""
    if depth > limits.max_form_depth:
        raise ScheduleParseRefusal(ScheduleIssueCode.UNSUPPORTED_LAYOUT, page_number)
    objects = texts = 0
    for index in range(int(pdfium_c.FPDFFormObj_CountObjects(form))):
        child = pdfium_c.FPDFFormObj_GetObject(form, index)
        objects += 1
        kind = int(pdfium_c.FPDFPageObj_GetType(child))
        if kind == pdfium_c.FPDF_PAGEOBJ_TEXT:
            texts += 1
        elif kind == pdfium_c.FPDF_PAGEOBJ_FORM:
            child_objects, child_texts = _walk_form(child, depth + 1, limits, page_number)
            objects += child_objects
            texts += child_texts
    return objects, texts


def _attributed_objects(
    textpage: pdfium.PdfTextPage, page_number: int, drafts: dict[int, _Draft]
) -> list[PdfTextObject]:
    """Section 2.4: each object's attributed, non-generated characters."""
    raw = textpage.raw
    for index in range(int(pdfium_c.FPDFText_CountChars(raw))):
        if int(pdfium_c.FPDFText_IsGenerated(raw, index)) != 0:
            continue
        key = _handle(pdfium_c.FPDFText_GetTextObject(raw, index))
        if key is None:
            continue
        draft = drafts.get(key)
        if draft is None:
            # 2a: every attributed character belongs to a top-level text object.
            raise ScheduleParseRefusal(ScheduleIssueCode.PARSER_EXCEPTION)
        code_point = int(pdfium_c.FPDFText_GetUnicode(raw, index))
        bad_point = code_point == 0 or 0xD800 <= code_point <= 0xDFFF
        if bad_point or code_point > _MAX_CODE_POINT:
            draft.chars.append(_REPLACEMENT)
            draft.unmapped = True
        else:
            draft.chars.append(chr(code_point))
        if int(pdfium_c.FPDFText_HasUnicodeMapError(raw, index)) != 0:
            draft.unmapped = True
    return [
        _text_object(draft, page_number)
        for draft in sorted(drafts.values(), key=lambda d: d.ordinal)
    ]


def _text_object(draft: _Draft, page_number: int) -> PdfTextObject:
    obj = draft.pointer
    font = pdfium_c.FPDFTextObj_GetFont(obj)
    length = int(pdfium_c.FPDFFont_GetBaseFontName(font, None, 0))
    buffer = ctypes.create_string_buffer(max(length, 1))
    if length:
        pdfium_c.FPDFFont_GetBaseFontName(font, buffer, length)
    font_size = ctypes.c_float()
    if not pdfium_c.FPDFTextObj_GetFontSize(obj, ctypes.byref(font_size)):
        raise ScheduleParseRefusal(ScheduleIssueCode.PARSER_EXCEPTION)
    left, bottom, right, top = (ctypes.c_float() for _ in range(4))
    if not pdfium_c.FPDFPageObj_GetBounds(obj, left, bottom, right, top):
        raise ScheduleParseRefusal(ScheduleIssueCode.PARSER_EXCEPTION)
    matrix = pdfium_c.FS_MATRIX()
    if not pdfium_c.FPDFPageObj_GetMatrix(obj, ctypes.byref(matrix)):
        raise ScheduleParseRefusal(ScheduleIssueCode.PARSER_EXCEPTION)
    text = "".join(draft.chars)
    return PdfTextObject(
        page_number=page_number,
        object_ordinal=draft.ordinal,
        text=text,
        suppressed=text == "",
        unmapped=draft.unmapped,
        font_base_name=bytes(buffer.value).decode("latin-1"),
        font_embedded=int(pdfium_c.FPDFFont_GetIsEmbedded(font)) == 1,
        font_size_mpt=to_millipoints(float(font_size.value)),
        box=ScheduleBox(
            to_millipoints(float(left.value)),
            to_millipoints(float(bottom.value)),
            to_millipoints(float(right.value)),
            to_millipoints(float(top.value)),
        ),
        matrix=(
            Decimal(float(matrix.a)),
            Decimal(float(matrix.b)),
            Decimal(float(matrix.c)),
            Decimal(float(matrix.d)),
            Decimal(float(matrix.e)),
            Decimal(float(matrix.f)),
        ),
    )
