"""Synthetic `p6_full_v1` Full-Schedule PDFs and their independent ground truth.

Contract: `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
sections 8 and 9. Standard library only — no PDF library, no `math`, no
randomness, no clock. Every PDF is assembled byte by byte the way
`src/my_pa/infrastructure/goodnotes/pdf.py` `_assemble_pdf` does it: a fixed
object order, a classic xref and a trailer, no `/Info`, no timestamps and no
random `/ID` (the encrypted family uses the fixed `/ID` `000102...0f`).
Content-stream numbers are written from `Decimal` with fixed formatting.

Fonts are Type3 fonts whose glyph boxes come from `d1` inside the file, so
PDFium's text-object bounds are analytic and identical across hosts and across
the `pypdfium2` floor and current versions (contract 6.6, D-14).

Each case is a pure function of `(family, variant)`: `build(family, variant)`
returns a `FixtureCase` holding the bytes, the parse inputs and `truth` — the
rows, cells, issues, counts and outcome the generator *intends*, written from
its own layout plan and never from parser output (contract 8.4). Golden files
(contract 9) pin parser output and are written only by the explicit
`write-goldens` command below; no test calls the writer.

Every name, label, identifier and date here is invented (`Synthetic Project`,
`SYN-1000`); no proprietary corpus text appears.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

GENERATOR_VERSION = 1

GOLDEN_DIRECTORY = Path(__file__).resolve().parent / "schedule_full_goldens"

# --- states, codes and fields (the domain's string values; stdlib only) ------

PUBLISHED_VALUE = "published_value"
PUBLISHED_BLANK = "published_blank"
EXTRACTION_FAILED = "extraction_failed"
AMBIGUOUS = "ambiguous"

PROJECT_SUMMARY = "project_summary"
WBS_SUMMARY = "wbs_summary"
ACTIVITY = "activity"
MILESTONE = "milestone"

COMPLETE = "complete"
PARTIAL = "partial"
REVIEW_REQUIRED = "review_required"
FAILED = "failed"

ACTIVITY_ID = "activity_id"
ACTIVITY_NAME = "activity_name"
ORIGINAL_DURATION = "original_duration"
REMAINING_DURATION = "remaining_duration"
START = "start"
FINISH = "finish"
HIERARCHY = "hierarchy"
CELL_FIELDS = (ACTIVITY_ID, ACTIVITY_NAME, ORIGINAL_DURATION, REMAINING_DURATION, START, FINISH)

#: Issue codes in declaration order (the domain enum's order).
ISSUE_CODE_ORDER = (
    "source_version_changed",
    "source_too_large",
    "unsupported_media_type",
    "corrupt_pdf",
    "encrypted_pdf",
    "image_only_pdf",
    "unsupported_layout",
    "page_metadata_mismatch",
    "expected_data_date_mismatch",
    "header_signature_mismatch",
    "header_od_occluded",
    "duplicate_text_object_collapsed",
    "overlapping_cell_text",
    "row_wrap_unsupported",
    "activity_like_row_missing_id",
    "duplicate_activity_id",
    "invalid_date",
    "invalid_duration",
    "ambiguous_cell",
    "hierarchy_ambiguous",
    "bounds_exceeded",
    "parser_exception",
    "processing_budget_exceeded",
)
WARNING_CODES = frozenset({"header_od_occluded", "duplicate_text_object_collapsed"})

# --- profile-frame geometry (contract 8.3; points) ---------------------------

D = Decimal
PAGE_W = D(1224)
PAGE_H = D(792)
BODY = D(7)
INDENT = tuple(
    D(v) for v in ("52.57", "56.78", "60.30", "63.88", "67.70", "71.53", "75.35", "79.08")
)
JITTER = D("0.6")
NAME_X = D(134)
OD_RIGHT = D(465)
RD_RIGHT = D(496)
START_X = D(501)
FINISH_X = D(562)
CHART_NAME_X = D(620)
CHART_DATE_X = D(700)
#: Synthetic choice (contract 8.3): the finish copy in the chart sits beside the
#: start copy so the two never coincide.
CHART_FINISH_X = D(760)
FIRST_BASELINE = D(685)
PITCH = D(15)
ANCHOR_Y = D(710)
ANCHOR_X = tuple(D(v) for v in ("38.88", "134.52", "446.63", "478.20", "520.50", "576.97"))
ANCHOR_TEXT = ("Activity ID", "Activity Name", "OD", "RD", "Start", "Finish")
SUMMARY_SIZE = {0: D(10), 1: D(8)}
TITLE = "Synthetic Project Schedule"
LAYOUT = "Layout: SYN Full"
DATA_DATE = date(2026, 5, 4)
RUN_DATE = date(2026, 5, 11)
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

ZERO = D(0)
IDENTITY = (D(1), ZERO, ZERO, D(1))
ROT_7 = (D("0.992546"), D("0.121869"), D("-0.121869"), D("0.992546"))
ROT_0_4 = (D("0.999976"), D("0.006981"), D("-0.006981"), D("0.999976"))
ROT_1 = (D("0.999848"), D("0.017452"), D("-0.017452"), D("0.999848"))

#: The `signature` watermark: 217 pt `DRAFT` rotated 7 degrees. Its box edges sit
#: 8.0 / 8.8 / 8.0 / 9.0 pt from the profile signature box (checked at build).
WATERMARK_SIZE = D(217)
WATERMARK_ORIGIN = (D("319.5"), D("295.1"))
SIGNATURE_BOX = (D(309), D(244), D(872), D(503))


def token_for(value: date, marker: str | None = None) -> str:
    """A date in the profile grammar `DD-Mon-YY` (locale independent)."""
    return f"{value.day:02d}-{_MONTHS[value.month - 1]}-{value.year % 100:02d}{marker or ''}"


# --- fonts and glyph metrics -------------------------------------------------

#: (llx, lly, urx, ury) per glyph, in 1/1000 text-space units; advance is 500.
UNIFORM_BOX = (0, -200, 500, 700)
FIRST_CHAR = 32
LAST_CHAR = 126


def glyph_box(char: str, metrics: str) -> tuple[int, int, int, int]:
    """The `d1` box of one glyph under the named metrics (contract 8.2)."""
    if metrics == "uniform":
        return UNIFORM_BOX
    if char == "1":
        return (80, 0, 420, 650)
    if char.isdigit():
        return (0, 0, 500, 650)
    if char in "gjpqy":
        return (0, -200, 500, 500)
    if "a" <= char <= "z":
        return (0, 0, 500, 500)
    return (0, 0, 500, 700)


@dataclass(frozen=True)
class FontSpec:
    key: str
    base_name: str
    metrics: str = "uniform"
    to_unicode: bool = True


REGULAR = "R"
BOLD = "B"
UNMAPPED = "U"


# --- draws -------------------------------------------------------------------


@dataclass(frozen=True)
class Draw:
    """One `BT ... Tj ET` text object."""

    text: str
    font: str
    size: Decimal
    x: Decimal
    y: Decimal
    rot: tuple[Decimal, Decimal, Decimal, Decimal] = IDENTITY
    tr: int = 0
    codes: bytes | None = None
    #: `table`, `meta`, `chart` or `watermark`: where the generator put it.
    role: str = "table"
    #: The generator expects PDFium to attribute 0 characters to this object.
    suppressed: bool = False

    @property
    def shown(self) -> bytes:
        return self.codes if self.codes is not None else self.text.encode("ascii")


@dataclass(frozen=True)
class FormSpec:
    """Form XObjects for family 26: nesting depth, innermost text or path."""

    depth: int
    text: Draw | None


@dataclass(frozen=True)
class PageSpec:
    draws: tuple[Draw, ...]
    media_box: tuple[int, int, int, int] = (0, 0, 1224, 792)
    rotate: int = 0
    form: FormSpec | None = None
    image_only: bool = False


def _num(value: Decimal | int) -> str:
    text = format(D(value).normalize(), "f")
    return "0" if text in ("-0", "0") else text


def _escape(raw: bytes) -> bytes:
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _text_block(draw: Draw, resource: str) -> bytes:
    a, b, c, d = draw.rot
    shown = (
        b"<" + draw.codes.hex().encode("ascii") + b">"
        if draw.codes is not None
        else b"(" + _escape(draw.shown) + b")"
    )
    # Every text-state parameter is written in every block (contract 8.2,
    # RR1-F02): Tc, Tw, Tz, TL, Tr and Ts persist across BT/ET otherwise.
    head = (
        f"BT /{resource} {_num(draw.size)} Tf 0 Tc 0 Tw 100 Tz 0 TL {draw.tr} Tr 0 Ts "
        f"{_num(a)} {_num(b)} {_num(c)} {_num(d)} {_num(draw.x)} {_num(draw.y)} Tm "
    ).encode("ascii")
    return head + shown + b" Tj ET\n"


def analytic_box(draw: Draw, metrics: str) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """The object's page-space bounds in points, from the glyph table."""
    if not any(FIRST_CHAR <= code <= LAST_CHAR for code in draw.shown):
        # Codes outside FirstChar..LastChar draw nothing: PDFium reports a
        # zero-area box at the show origin (measured at 5.0.0 and 5.13.0).
        return (draw.x, draw.y, draw.x, draw.y)
    boxes = [glyph_box(chr(code), metrics) for code in draw.shown]
    llx = min(500 * i + box[0] for i, box in enumerate(boxes))
    urx = max(500 * i + box[2] for i, box in enumerate(boxes))
    lly = min(box[1] for box in boxes)
    ury = max(box[3] for box in boxes)
    scale = draw.size / 1000
    a, b, c, d = draw.rot
    xs: list[Decimal] = []
    ys: list[Decimal] = []
    for gx in (llx, urx):
        for gy in (lly, ury):
            tx, ty = scale * gx, scale * gy
            xs.append(draw.x + a * tx + c * ty)
            ys.append(draw.y + b * tx + d * ty)
    return (min(xs), min(ys), max(xs), max(ys))


def mpt(value: Decimal) -> int:
    return int((value * 1000).quantize(D(1), rounding=ROUND_HALF_EVEN))


def box_mpt(box: tuple[Decimal, Decimal, Decimal, Decimal]) -> tuple[int, int, int, int]:
    return (mpt(box[0]), mpt(box[1]), mpt(box[2]), mpt(box[3]))


# --- ground truth ------------------------------------------------------------


@dataclass(frozen=True)
class TruthCell:
    field: str
    state: str
    #: The normalized cell text (fragments joined by one space), or `None`.
    text: str | None
    #: Fragment boxes in page-space millipoints, in x order.
    boxes: tuple[tuple[int, int, int, int], ...]


@dataclass(frozen=True)
class TruthRow:
    page: int
    line: int
    row_type: str
    indent_level: int | None
    #: 1-based ordinal of the intended parent row, or `None`.
    parent: int | None
    hierarchy_path: tuple[str, ...] | None
    activity_id: str | None
    name: str | None
    original_duration: tuple[str, str | None]
    remaining_duration: tuple[str, str | None]
    start: tuple[str, str | None, str | None]
    finish: tuple[str, str | None, str | None]
    box: tuple[int, int, int, int]
    cells: tuple[TruthCell, ...]
    #: Row-referencing issues as `(code, field)`, in contract 5.14 order.
    issues: tuple[tuple[str, str | None], ...]

    @property
    def warning_codes(self) -> tuple[str, ...]:
        codes = {code for code, _ in self.issues}
        return tuple(code for code in ISSUE_CODE_ORDER if code in codes)


@dataclass(frozen=True)
class Truth:
    outcome: str
    rows: tuple[TruthRow, ...]
    #: Issues without a row reference: `(code, page or None, field or None)`.
    document_issues: tuple[tuple[str, int | None, str | None], ...]
    title: str | None
    data_date: date | None
    run_date: date | None
    #: Expected counts (contract 3.3 names); `None` for a `failed` case.
    counts: Mapping[str, int] | None

    @property
    def issue_counts(self) -> dict[str, int]:
        found: dict[str, int] = {}
        keys = [(code, page, None, fld) for code, page, fld in self.document_issues]
        for ordinal, row in enumerate(self.rows, start=1):
            keys.extend((code, row.page, ordinal, fld) for code, fld in row.issues)
        for key in set(keys):
            found[key[0]] = found.get(key[0], 0) + 1
        return dict(sorted(found.items()))


@dataclass(frozen=True)
class FixtureCase:
    family: str
    variant: str
    pdf: bytes
    expected_data_date: date | None
    #: Tightened `ScheduleParseLimits` fields, or `None` for production limits.
    limits: Mapping[str, int] | None
    #: For the budget cases: the fake clock returns 0.0 for this many calls and
    #: 10.0 after, against `deadline=1.0` (contract 5.15). `None` = no budget.
    clock_calls_before_expiry: int | None
    truth: Truth
    #: The page specs, for the PDFium readback test (empty for raw-byte cases).
    pages: tuple[PageSpec, ...] = ()
    fonts: tuple[FontSpec, ...] = ()

    @property
    def name(self) -> str:
        return f"{self.family}__{self.variant}"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.pdf).hexdigest()


# --- PDF assembly ------------------------------------------------------------


def _rc4(key: bytes, data: bytes) -> bytes:
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) % 256
        state[i], state[j] = state[j], state[i]
    out = bytearray()
    i = j = 0
    for byte in data:
        i = (i + 1) % 256
        j = (j + state[i]) % 256
        state[i], state[j] = state[j], state[i]
        out.append(byte ^ state[(state[i] + state[j]) % 256])
    return bytes(out)


_PASSWORD_PAD = bytes.fromhex("28bf4e5e4e758a4164004e56fffa01082e2e00b6d0683e802f0ca9fe6453697a")
FIXED_ID = bytes(range(16))


def _md5(data: bytes) -> bytes:
    return hashlib.md5(data, usedforsecurity=False).digest()


@dataclass(frozen=True)
class _Rc4Security:
    """Standard security handler, revision 2, 40-bit RC4."""

    user: bytes
    owner: bytes
    permissions: int = -44

    @property
    def owner_entry(self) -> bytes:
        owner_key = _md5((self.owner + _PASSWORD_PAD)[:32])[:5]
        return _rc4(owner_key, (self.user + _PASSWORD_PAD)[:32])

    @property
    def file_key(self) -> bytes:
        material = (
            (self.user + _PASSWORD_PAD)[:32]
            + self.owner_entry
            + (self.permissions & 0xFFFFFFFF).to_bytes(4, "little")
            + FIXED_ID
        )
        return _md5(material)[:5]

    @property
    def user_entry(self) -> bytes:
        return _rc4(self.file_key, _PASSWORD_PAD)

    def encrypt(self, number: int, data: bytes) -> bytes:
        key = _md5(self.file_key + number.to_bytes(3, "little") + b"\x00\x00")[:10]
        return _rc4(key, data)


class _Writer:
    def __init__(self) -> None:
        self.bodies: list[tuple[bytes, bytes | None]] = []

    def reserve(self) -> int:
        self.bodies.append((b"", None))
        return len(self.bodies)

    def put(self, number: int, inner: str | bytes, stream: bytes | None = None) -> None:
        raw = inner.encode("ascii") if isinstance(inner, str) else inner
        self.bodies[number - 1] = (raw, stream)

    def add(self, inner: str | bytes, stream: bytes | None = None) -> int:
        number = self.reserve()
        self.put(number, inner, stream)
        return number

    def assemble(
        self,
        *,
        security: _Rc4Security | None = None,
        encrypt_dict: str | None = None,
    ) -> bytes:
        bodies: list[bytes] = []
        for number, (inner, stream) in enumerate(self.bodies, start=1):
            if stream is None:
                bodies.append(inner)
                continue
            data = security.encrypt(number, stream) if security is not None else stream
            bodies.append(
                b"<< "
                + inner
                + f" /Length {len(data)} >>\nstream\n".encode("ascii")
                + data
                + b"\nendstream"
            )
        trailer_extra = ""
        if encrypt_dict is not None:
            encrypt_number = len(bodies) + 1
            bodies.append(encrypt_dict.encode("ascii"))
            hex_id = FIXED_ID.hex()
            trailer_extra = f" /Encrypt {encrypt_number} 0 R /ID [<{hex_id}> <{hex_id}>]"
        parts = [b"%PDF-1.7\n"]
        cursor = len(parts[0])
        offsets: list[int] = []
        for index, body in enumerate(bodies, start=1):
            obj = f"{index} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
            offsets.append(cursor)
            parts.append(obj)
            cursor += len(obj)
        xref = [f"xref\n0 {len(bodies) + 1}\n0000000000 65535 f \n".encode("ascii")]
        xref.extend(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets)
        trailer = (
            f"trailer<< /Size {len(bodies) + 1} /Root 1 0 R{trailer_extra} >>\n"
            f"startxref\n{cursor}\n%%EOF\n"
        ).encode("ascii")
        return b"".join(parts + xref + [trailer])


_TO_UNICODE = (
    b"/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
    b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
    b"/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
    b"1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
    b"1 beginbfrange\n<20> <7E> <0020>\nendbfrange\n"
    b"endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
)


def _glyph_proc(box: tuple[int, int, int, int]) -> bytes:
    llx, lly, urx, ury = box
    return (f"500 0 {llx} {lly} {urx} {ury} d1 {llx} {lly} {urx - llx} {ury - lly} re f\n").encode(
        "ascii"
    )


def _write_font(writer: _Writer, spec: FontSpec) -> int:
    codes = range(FIRST_CHAR, LAST_CHAR + 1)
    proc_numbers: dict[tuple[int, int, int, int], int] = {}
    entries: list[str] = []
    for code in codes:
        box = glyph_box(chr(code), spec.metrics)
        if box not in proc_numbers:
            proc_numbers[box] = writer.add("", _glyph_proc(box))
        entries.append(f"/g{code} {proc_numbers[box]} 0 R")
    char_procs = writer.add("<< " + " ".join(entries) + " >>")
    differences = " ".join(f"/g{code}" for code in codes)
    widths = " ".join("500" for _ in codes)
    to_unicode = ""
    if spec.to_unicode:
        to_unicode = f" /ToUnicode {writer.add('', _TO_UNICODE)} 0 R"
    return writer.add(
        f"<< /Type /Font /Subtype /Type3 /BaseFont /{spec.base_name} "
        f"/FontBBox [0 -200 500 700] /FontMatrix [0.001 0 0 0.001 0 0] "
        f"/CharProcs {char_procs} 0 R "
        f"/Encoding << /Type /Encoding /Differences [32 {differences}] >> "
        f"/FirstChar 32 /LastChar 126 /Widths [{widths}] /Resources << >>{to_unicode} >>"
    )


def assemble_document(
    pages: Sequence[PageSpec],
    fonts: Sequence[FontSpec],
    *,
    security: _Rc4Security | None = None,
    encrypt_filter: str = "Standard",
) -> bytes:
    """Write the pages with the given Type3 fonts as one PDF."""
    writer = _Writer()
    catalog = writer.reserve()
    page_tree = writer.reserve()
    font_numbers = {spec.key: _write_font(writer, spec) for spec in fonts}
    font_resources = " ".join(f"/F{key} {number} 0 R" for key, number in font_numbers.items())
    page_numbers: list[int] = []
    for page in pages:
        content = bytearray()
        xobjects = ""
        if page.image_only:
            image = writer.add(
                "/Type /XObject /Subtype /Image /Width 1 /Height 1 "
                "/ColorSpace /DeviceGray /BitsPerComponent 8",
                b"\x80",
            )
            xobjects = f" /XObject << /Im1 {image} 0 R >>"
            content += b"q 100 0 0 100 200 300 cm /Im1 Do Q\n50 50 150 50 re f\n"
        for draw in page.draws:
            content += _text_block(draw, f"F{draw.font}")
        if page.form is not None:
            inner = _form_content(page.form)
            child: int | None = None
            for _level in range(page.form.depth):
                resources = f"/Font << {font_resources} >>"
                body = inner
                if child is not None:
                    resources += f" /XObject << /Fm1 {child} 0 R >>"
                    body = b"/Fm1 Do\n"
                child = writer.add(
                    f"/Type /XObject /Subtype /Form /BBox [0 0 1224 792] "
                    f"/Resources << {resources} >>",
                    body,
                )
            xobjects = f" /XObject << /Fm1 {child} 0 R >>"
            content += b"/Fm1 Do\n"
        contents = writer.add("", bytes(content))
        rotate = f" /Rotate {page.rotate}" if page.rotate else ""
        media = " ".join(str(v) for v in page.media_box)
        page_numbers.append(
            writer.add(
                f"<< /Type /Page /Parent {page_tree} 0 R /MediaBox [{media}]{rotate} "
                f"/Resources << /Font << {font_resources} >>{xobjects} >> "
                f"/Contents {contents} 0 R >>"
            )
        )
    writer.put(catalog, f"<< /Type /Catalog /Pages {page_tree} 0 R >>")
    kids = " ".join(f"{number} 0 R" for number in page_numbers)
    writer.put(page_tree, f"<< /Type /Pages /Kids [{kids}] /Count {len(page_numbers)} >>")
    if security is None:
        return writer.assemble()
    encrypt = (
        f"<< /Filter /{encrypt_filter} /V 1 /R 2 /Length 40 "
        f"/O <{security.owner_entry.hex()}> /U <{security.user_entry.hex()}> "
        f"/P {security.permissions} >>"
    )
    stream_security = security if encrypt_filter == "Standard" else None
    return writer.assemble(security=stream_security, encrypt_dict=encrypt)


def _form_content(form: FormSpec) -> bytes:
    if form.text is not None:
        return _text_block(form.text, f"F{form.text.font}")
    return b"10 10 100 20 re f\n"


# --- layout plan -------------------------------------------------------------


@dataclass(frozen=True)
class Val:
    """One value cell's intent: the drawn token and the expected typed result."""

    token: str | None
    state: str
    value: str | None = None
    marker: str | None = None


BLANK = Val(None, PUBLISHED_BLANK)


def dur(token: str) -> Val:
    return Val(token, PUBLISHED_VALUE, str(D(token).quantize(D("0.001"))))


def day(value: date, marker: str | None = None) -> Val:
    return Val(token_for(value, marker), PUBLISHED_VALUE, value.isoformat(), marker)


def bad(token: str) -> Val:
    return Val(token, EXTRACTION_FAILED)


def ambiguous_val(token: str | None) -> Val:
    return Val(token, AMBIGUOUS)


@dataclass
class _Cell:
    state: str | None = None
    draws: list[Draw] = field(default_factory=list)
    text: str | None = None


@dataclass
class _Row:
    page: int
    row_type: str
    level: int | None
    parent: int | None
    activity_id: str | None
    name: str | None
    vals: dict[str, Val]
    cells: dict[str, _Cell]
    issues: list[tuple[str, str | None]]
    determinate: bool = True


def _collapse(text: str) -> str:
    return " ".join(text.split())


class Plan:
    """Builds pages, draws and truth rows together."""

    def __init__(self, fonts: Sequence[FontSpec] | None = None) -> None:
        self.fonts: list[FontSpec] = list(fonts) if fonts is not None else default_fonts()
        self.pages: list[list[Draw]] = []
        self.page_options: list[dict[str, object]] = []
        self.rows: list[_Row] = []
        self.document_issues: list[tuple[str, int | None, str | None]] = []
        self.last_summary: dict[int, int] = {}
        self.extra_counts: dict[str, int] = {}

    # pages and frame

    def new_page(self) -> int:
        self.pages.append([])
        self.page_options.append({})
        return len(self.pages)

    def draw(self, page: int, draw: Draw) -> Draw:
        self.pages[page - 1].append(draw)
        return draw

    def frame(
        self,
        page: int,
        total: int,
        *,
        title: str = TITLE,
        data_date: date = DATA_DATE,
        run_date: date = RUN_DATE,
        signature: tuple[int, int] | None = None,
        anchors: Mapping[int, str | None] | None = None,
        anchor_x: Mapping[int, Decimal] | None = None,
        extra_header: Sequence[Draw] = (),
    ) -> None:
        meta = functools.partial(Draw, role="meta")
        self.draw(page, meta(title, BOLD, D(12), D(40), D(760)))
        self.draw(page, meta(LAYOUT, REGULAR, BODY, D(40), D(740)))
        self.draw(page, meta(f"Data Date: {token_for(data_date)}", REGULAR, BODY, D(300), D(740)))
        self.draw(page, meta(f"Run Date: {token_for(run_date)}", REGULAR, BODY, D(900), D(740)))
        for index, text in enumerate(ANCHOR_TEXT):
            shown = text if anchors is None or index not in anchors else anchors[index]
            if shown is None:
                continue
            x = ANCHOR_X[index] if anchor_x is None else anchor_x.get(index, ANCHOR_X[index])
            self.draw(page, meta(shown, REGULAR, BODY, x, ANCHOR_Y))
        for extra in extra_header:
            self.draw(page, extra)
        self.draw(page, meta("May 26", REGULAR, BODY, D(700), ANCHOR_Y))
        self.draw(page, meta("Synthetic legend", REGULAR, BODY, D(40), D(60)))
        n, m = signature if signature is not None else (page, total)
        self.draw(page, meta(f"Summary Page {n} of {m}", REGULAR, BODY, D(1000), D(40)))

    # rows

    def _place(self, level: int, *, summary: bool) -> int | None:
        parent = self.last_summary.get(level - 1) if level > 0 else None
        if summary:
            for deeper in [lv for lv in self.last_summary if lv >= level]:
                del self.last_summary[deeper]
            self.last_summary[level] = len(self.rows) + 1
        return parent

    def _value_draws(self, page: int, y: Decimal, vals: Mapping[str, Val]) -> dict[str, _Cell]:
        cells: dict[str, _Cell] = {}
        for fld in (ORIGINAL_DURATION, REMAINING_DURATION, START, FINISH):
            val = vals[fld]
            cell = _Cell(state=val.state)
            if val.token is not None:
                width = D(len(val.token)) * BODY / 2
                x = {
                    ORIGINAL_DURATION: OD_RIGHT - width,
                    REMAINING_DURATION: RD_RIGHT - width,
                    START: START_X,
                    FINISH: FINISH_X,
                }[fld]
                cell.draws.append(self.draw(page, Draw(val.token, REGULAR, BODY, x, y)))
            cells[fld] = cell
        return cells

    def summary(
        self,
        page: int,
        y: Decimal,
        level: int,
        label: str,
        od: Val,
        rd: Val,
        start: Val,
        finish: Val,
        *,
        size: Decimal | None = None,
        x: Decimal | None = None,
        label_y: Decimal | None = None,
        issues: Sequence[tuple[str, str | None]] = (),
    ) -> int:
        vals = {ORIGINAL_DURATION: od, REMAINING_DURATION: rd, START: start, FINISH: finish}
        cells = self._value_draws(page, y, vals)
        label_draw = self.draw(
            page,
            Draw(
                label,
                BOLD,
                size if size is not None else SUMMARY_SIZE.get(level, BODY),
                x if x is not None else INDENT[level],
                label_y if label_y is not None else y,
            ),
        )
        cells[ACTIVITY_ID] = _Cell(state=PUBLISHED_BLANK)
        cells[ACTIVITY_NAME] = _Cell(state=PUBLISHED_VALUE, draws=[label_draw])
        first_summary = not any(row.row_type in (PROJECT_SUMMARY, WBS_SUMMARY) for row in self.rows)
        parent = self._place(level, summary=True)
        # Contract 5.11 rule 7: the first summary is the project summary when it
        # is determinate at level 0 (callers mark the indeterminate cases).
        row_type = PROJECT_SUMMARY if first_summary and level == 0 else WBS_SUMMARY
        self.rows.append(
            _Row(page, row_type, level, parent, None, label, vals, cells, list(issues))
        )
        return len(self.rows)

    def activity(
        self,
        page: int,
        y: Decimal,
        level: int,
        activity_id: str,
        name: str,
        od: Val,
        rd: Val,
        start: Val,
        finish: Val,
        *,
        x_shift: Decimal = ZERO,
        id_text: str | None = None,
        name_draws: Sequence[Draw] | None = None,
        row_type: str | None = None,
        issues: Sequence[tuple[str, str | None]] = (),
    ) -> int:
        vals = {ORIGINAL_DURATION: od, REMAINING_DURATION: rd, START: start, FINISH: finish}
        cells = self._value_draws(page, y, vals)
        id_draw = self.draw(
            page, Draw(id_text or activity_id, REGULAR, BODY, INDENT[level] + x_shift, y)
        )
        if name_draws is None:
            name_draws = [Draw(name, REGULAR, BODY, NAME_X, y)]
        for draw in name_draws:
            self.draw(page, draw)
        cells[ACTIVITY_ID] = _Cell(state=PUBLISHED_VALUE, draws=[id_draw])
        cells[ACTIVITY_NAME] = _Cell(state=PUBLISHED_VALUE, draws=list(name_draws))
        if row_type is None:
            zero = od.value == "0.000" and rd.value == "0.000"
            one_date = (start.state == PUBLISHED_VALUE) != (finish.state == PUBLISHED_VALUE) and (
                PUBLISHED_BLANK in (start.state, finish.state)
            )
            row_type = MILESTONE if zero and one_date else ACTIVITY
        parent = self._place(level, summary=False)
        self.rows.append(
            _Row(page, row_type, level, parent, activity_id, name, vals, cells, list(issues))
        )
        return len(self.rows)

    def bare_row(
        self,
        page: int,
        draws: Mapping[str, Sequence[Draw]],
        vals: Mapping[str, Val],
        *,
        issues: Sequence[tuple[str, str | None]],
        states: Mapping[str, str] | None = None,
    ) -> int:
        """An `AMBIGUOUS` row whose cells the caller lays out directly."""
        cells: dict[str, _Cell] = {}
        for fld in CELL_FIELDS:
            placed = [self.draw(page, d) for d in draws.get(fld, ())]
            default = PUBLISHED_VALUE if placed else PUBLISHED_BLANK
            state = (states or {}).get(fld) or (vals[fld].state if fld in vals else default)
            cells[fld] = _Cell(state=state, draws=placed)
        full_vals = {
            fld: vals.get(fld, BLANK)
            for fld in (ORIGINAL_DURATION, REMAINING_DURATION, START, FINISH)
        }
        self.rows.append(
            _Row(page, AMBIGUOUS, None, None, None, None, full_vals, cells, list(issues))
        )
        return len(self.rows)

    def chart_copies(self, page: int, y: Decimal, name: str, *dates: Val) -> None:
        self.draw(page, Draw(name, REGULAR, BODY, CHART_NAME_X, y, role="chart"))
        for x, val in zip((CHART_DATE_X, CHART_FINISH_X), dates, strict=False):
            if val.token is not None:
                self.draw(page, Draw(val.token, REGULAR, BODY, x, y, role="chart"))

    def watermark(self, page: int, *, shift: tuple[Decimal, Decimal] = (D(0), D(0))) -> Draw:
        x, y = WATERMARK_ORIGIN
        return self.draw(
            page,
            Draw(
                "DRAFT",
                REGULAR,
                WATERMARK_SIZE,
                x + shift[0],
                y + shift[1],
                ROT_7,
                role="watermark",
            ),
        )

    # truth

    def _metrics(self, draw: Draw) -> str:
        for spec in self.fonts:
            if spec.key == draw.font:
                return spec.metrics
        raise ValueError("draw names an unknown font")

    def _base(self, draw: Draw) -> str:
        for spec in self.fonts:
            if spec.key == draw.font:
                return spec.base_name
        raise ValueError("draw names an unknown font")

    def box(self, draw: Draw) -> tuple[int, int, int, int]:
        return box_mpt(analytic_box(draw, self._metrics(draw)))

    def truth(
        self,
        outcome: str,
        *,
        title: str | None = TITLE,
        data_date: date | None = DATA_DATE,
        run_date: date | None = RUN_DATE,
    ) -> Truth:
        rows: list[TruthRow] = []
        lines: dict[int, int] = {}
        names = {index: row.name for index, row in enumerate(self.rows, start=1)}
        for row in self.rows:
            lines[row.page] = lines.get(row.page, 0) + 1
            cells: list[TruthCell] = []
            boxes: list[tuple[int, int, int, int]] = []
            for fld in CELL_FIELDS:
                cell = row.cells[fld]
                ordered = sorted(cell.draws, key=lambda d: self.box(d)[0])
                frag_boxes = tuple(self.box(d) for d in ordered)
                boxes.extend(frag_boxes)
                text = cell.text
                if text is None and ordered:
                    text = " ".join(_collapse(d.text) for d in ordered)
                cells.append(TruthCell(fld, cell.state or PUBLISHED_BLANK, text, frag_boxes))
            box = (
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            )
            path: tuple[str, ...] | None = None
            if row.row_type != AMBIGUOUS and row.determinate:
                chain: list[str] = []
                cursor = row.parent
                while cursor is not None:
                    chain.append(names[cursor] or "")
                    cursor = self.rows[cursor - 1].parent
                path = tuple(reversed(chain))
            vals = row.vals
            rows.append(
                TruthRow(
                    page=row.page,
                    line=lines[row.page],
                    row_type=row.row_type,
                    indent_level=row.level,
                    parent=row.parent,
                    hierarchy_path=path,
                    activity_id=row.activity_id if row.row_type in (ACTIVITY, MILESTONE) else None,
                    name=row.name if row.row_type != AMBIGUOUS else None,
                    original_duration=(
                        vals[ORIGINAL_DURATION].state,
                        vals[ORIGINAL_DURATION].value,
                    ),
                    remaining_duration=(
                        vals[REMAINING_DURATION].state,
                        vals[REMAINING_DURATION].value,
                    ),
                    start=(vals[START].state, vals[START].value, vals[START].marker),
                    finish=(vals[FINISH].state, vals[FINISH].value, vals[FINISH].marker),
                    box=box,
                    cells=tuple(cells),
                    issues=_ordered_issues(row.issues),
                )
            )
        counts = self._counts(rows)
        return Truth(
            outcome=outcome,
            rows=tuple(rows),
            document_issues=tuple(self.document_issues),
            title=title,
            data_date=data_date,
            run_date=run_date,
            counts=counts,
        )

    def _counts(self, rows: Sequence[TruthRow]) -> dict[str, int]:
        draws = [d for page in self.pages for d in page]
        by_type = {
            t: sum(1 for r in rows if r.row_type == t)
            for t in (PROJECT_SUMMARY, WBS_SUMMARY, ACTIVITY, MILESTONE, AMBIGUOUS)
        }
        counts = {
            "pages": len(self.pages),
            "rows": len(rows),
            "project_summaries": by_type[PROJECT_SUMMARY],
            "wbs_summaries": by_type[WBS_SUMMARY],
            "activities": by_type[ACTIVITY],
            "milestones": by_type[MILESTONE],
            "ambiguous": by_type[AMBIGUOUS],
            "chart_objects_excluded": sum(1 for d in draws if d.role == "chart"),
            "watermark_objects_excluded": sum(1 for d in draws if d.role == "watermark"),
            "suppressed_objects": sum(1 for d in draws if d.suppressed and d.role != "chart"),
            "duplicate_objects_collapsed": 0,
            "non_embedded_font_objects": 0,
        }
        counts.update(self.extra_counts)
        issues = Truth(
            COMPLETE, tuple(rows), tuple(self.document_issues), None, None, None, None
        ).issue_counts
        counts["issues"] = sum(issues.values())
        counts["warnings"] = sum(v for k, v in issues.items() if k in WARNING_CODES)
        return counts

    def page_specs(self) -> tuple[PageSpec, ...]:
        return tuple(PageSpec(draws=tuple(draws)) for draws in self.pages)

    def case(
        self,
        family: str,
        variant: str,
        outcome: str,
        *,
        expected_data_date: date | None = None,
        page_specs: Sequence[PageSpec] | None = None,
        title: str | None = TITLE,
        data_date: date | None = DATA_DATE,
        run_date: date | None = RUN_DATE,
    ) -> FixtureCase:
        specs = tuple(page_specs) if page_specs is not None else self.page_specs()
        truth = self.truth(outcome, title=title, data_date=data_date, run_date=run_date)
        return FixtureCase(
            family=family,
            variant=variant,
            pdf=assemble_document(specs, self.fonts),
            expected_data_date=expected_data_date,
            limits=None,
            clock_calls_before_expiry=None,
            truth=truth,
            pages=specs,
            fonts=tuple(self.fonts),
        )


def _ordered_issues(
    issues: Sequence[tuple[str, str | None]],
) -> tuple[tuple[str, str | None], ...]:
    field_order = {name: index for index, name in enumerate((*CELL_FIELDS, HIERARCHY))}
    unique = set(issues)
    return tuple(
        sorted(
            unique,
            key=lambda item: (
                ISSUE_CODE_ORDER.index(item[0]),
                -1 if item[1] is None else field_order[item[1]],
            ),
        )
    )


def default_fonts(*, bold_name: str = "Arial,Bold", metrics: str = "uniform") -> list[FontSpec]:
    return [FontSpec(REGULAR, "Arial", metrics), FontSpec(BOLD, bold_name, metrics)]


def baseline(line: int) -> Decimal:
    """The baseline of the `line`-th (1-based) row slot on a page."""
    return FIRST_BASELINE - PITCH * (line - 1)


def _d(month: int, dom: int, year: int = 2026) -> date:
    return date(year, month, dom)


def _name(index: int) -> str:
    return f"Synthetic activity {index:03d}"


# --- families ----------------------------------------------------------------

Builder = Callable[[str], FixtureCase]


def _standard_activity(plan: Plan, page: int, line: int, level: int, index: int) -> int:
    """An ordinary activity `SYN-(1000+index)` with neutral values."""
    return plan.activity(
        page,
        baseline(line),
        level,
        f"SYN-{1000 + index}",
        _name(index + 1),
        dur("10"),
        dur("5"),
        day(_d(5, 4)),
        day(_d(5, 15)),
    )


def _project(plan: Plan, page: int, line: int, label: str = "Synthetic Project") -> int:
    return plan.summary(
        page, baseline(line), 0, label, dur("120"), dur("80"), day(_d(5, 4)), day(_d(10, 30))
    )


def _wbs(plan: Plan, page: int, line: int, level: int, label: str) -> int:
    return plan.summary(
        page, baseline(line), level, label, dur("60"), dur("40"), day(_d(5, 4)), day(_d(7, 31))
    )


def _full_valid_2p_plan(variant: str) -> Plan:
    bold_name = "SYNABC+Arial,Bold" if variant == "subset_prefix" else "Arial,Bold"
    plan = Plan(default_fonts(bold_name=bold_name))
    p1 = plan.new_page()
    p2 = plan.new_page()
    plan.frame(p1, 2)
    plan.frame(p2, 2)
    _project(plan, p1, 1)
    _wbs(plan, p1, 2, 1, "Synthetic Phase A")
    plan.activity(
        p1, baseline(3), 2, "SYN-1000", _name(1), dur("10"), dur("5"), day(_d(5, 4)), day(_d(5, 15))
    )
    id_text = "SYN  1001" if variant == "id_double_space" else None
    plan.activity(
        p1,
        baseline(4),
        2,
        "SYN 1001" if id_text else "SYN-1001",
        _name(2),
        dur("12.5"),
        dur("0"),
        day(_d(5, 11), "*"),
        day(_d(5, 27)),
        id_text=id_text,
    )
    plan.activity(
        p1,
        baseline(5),
        2,
        "SYN-1002",
        "Synthetic start milestone",
        dur("0"),
        dur("0"),
        day(_d(5, 4)),
        BLANK,
    )
    name_draws = None
    if variant == "split_name":
        first = Draw("Synthetic", REGULAR, BODY, NAME_X, baseline(6))
        # 9 glyphs end at 165.5 pt; the second fragment starts 0.2 pt earlier.
        second = Draw("activity 004", REGULAR, BODY, D("165.3"), baseline(6))
        name_draws = [first, second]
    plan.activity(
        p1,
        baseline(6),
        2,
        "SYN-1003",
        _name(4),
        dur("20"),
        dur("20"),
        day(_d(5, 18)),
        day(_d(6, 12)),
        name_draws=name_draws,
    )
    if variant == "zone_edges":
        # Every object's y-centre is exactly 700.000 pt (baseline + 1.75 pt).
        plan.activity(
            p2,
            D("698.25"),
            2,
            "SYN-1007",
            _name(8),
            dur("3"),
            dur("3"),
            day(_d(6, 1)),
            day(_d(6, 3)),
        )
    _wbs(plan, p2, 1, 1, "Synthetic Phase B")
    plan.activity(
        p2,
        baseline(2),
        2,
        "SYN-1004",
        _name(5),
        dur("15"),
        dur("15"),
        day(_d(8, 3)),
        day(_d(8, 21)),
    )
    plan.activity(
        p2,
        baseline(3),
        2,
        "SYN-1005",
        "Synthetic finish milestone",
        dur("0"),
        dur("0"),
        BLANK,
        day(_d(10, 30)),
    )
    plan.activity(
        p2, baseline(4), 2, "SYN-1006", _name(7), dur("8"), dur("8"), day(_d(9, 1)), day(_d(9, 10))
    )
    if variant == "zone_edges":
        # y-centre exactly 95.000 pt.
        plan.activity(
            p2,
            D("93.25"),
            2,
            "SYN-1008",
            _name(9),
            dur("2"),
            dur("2"),
            day(_d(9, 14)),
            day(_d(9, 15)),
        )
    return plan


def full_valid_2p(variant: str) -> FixtureCase:
    return _full_valid_2p_plan(variant).case("full_valid_2p", variant, COMPLETE)


def full_merged_summary_label(variant: str) -> FixtureCase:
    plan = Plan()
    p1 = plan.new_page()
    plan.frame(p1, 1)
    # A 10 pt project label from x0 52.57 whose box (to 202.57) crosses 131.0.
    _project(plan, p1, 1, "Synthetic Project merged label")
    # An 8 pt level-1 label whose box (56.78 to 208.78) crosses 131.0 and
    # whose x-centre (132.78) lies in the Name band.
    _wbs(plan, p1, 2, 1, "Synthetic Phase A merged summary label")
    for line, index in ((3, 0), (4, 1), (5, 2)):
        _standard_activity(plan, p1, line, 2, index)
    outcome = COMPLETE
    if variant == "label_only":
        draw = Draw("Synthetic Phase B", BOLD, SUMMARY_SIZE[1], INDENT[1], baseline(6))
        plan.bare_row(
            p1,
            {ACTIVITY_ID: [draw]},
            {},
            issues=[("ambiguous_cell", None)],
            states={ACTIVITY_ID: PUBLISHED_BLANK, ACTIVITY_NAME: PUBLISHED_VALUE},
        )
        # The label is the summary's merged name cell, not an ID fragment.
        row = plan.rows[-1]
        row.cells[ACTIVITY_NAME] = _Cell(state=PUBLISHED_VALUE, draws=[draw])
        row.cells[ACTIVITY_ID] = _Cell(state=PUBLISHED_BLANK)
        outcome = REVIEW_REQUIRED
    return plan.case("full_merged_summary_label", variant, outcome)


def full_summary_vertical_offset(variant: str) -> FixtureCase:
    metrics = "glyph" if variant == "glyph_metrics" else "uniform"
    plan = Plan(default_fonts(metrics=metrics))
    p1 = plan.new_page()
    plan.frame(p1, 1)
    # 10 pt label centre 3.0 pt above the 7 pt cells' centre: baseline + 2.25.
    y = baseline(1)
    plan.summary(
        p1,
        y,
        0,
        "Synthetic Project",
        dur("120"),
        dur("80"),
        day(_d(5, 4)),
        day(_d(10, 30)),
        label_y=y + D("2.25"),
    )
    _wbs(plan, p1, 2, 1, "Synthetic Phase A")
    for line, index in ((3, 0), (4, 1), (5, 2)):
        _standard_activity(plan, p1, line, 2, index)
    _wbs(plan, p1, 6, 1, "Synthetic Phase B")
    plan.activity(
        p1,
        baseline(7),
        2,
        "SYN-1010",
        "Synthetic gauging activity 011",
        dur("1"),
        dur("1"),
        day(_d(6, 1)),
        day(_d(6, 1)),
    )
    return plan.case("full_summary_vertical_offset", variant, COMPLETE)


def full_summary_zero_zero(variant: str) -> FixtureCase:
    plan = Plan()
    p1 = plan.new_page()
    plan.frame(p1, 1)
    _project(plan, p1, 1)
    plan.summary(p1, baseline(2), 1, "Synthetic Phase A", dur("0"), dur("0"), day(_d(5, 4)), BLANK)
    _standard_activity(plan, p1, 3, 2, 0)
    _standard_activity(plan, p1, 4, 2, 1)
    outcome = COMPLETE
    if variant == "id_both_dates":
        plan.activity(
            p1,
            baseline(5),
            2,
            "SYN-1002",
            _name(3),
            dur("0"),
            dur("0"),
            day(_d(5, 4)),
            day(_d(5, 4)),
            row_type=AMBIGUOUS,
            issues=[("ambiguous_cell", None)],
        )
        _ambiguous_row_from_activity(plan)
        outcome = REVIEW_REQUIRED
    return plan.case("full_summary_zero_zero", variant, outcome)


def _ambiguous_row_from_activity(plan: Plan) -> None:
    """Mark the last planned activity as an `AMBIGUOUS` row outside the tree."""
    row = plan.rows[-1]
    row.row_type = AMBIGUOUS
    row.level = None
    row.parent = None
    row.activity_id = None
    row.name = None


def full_nested_hierarchy(variant: str) -> FixtureCase:
    plan = Plan()
    pages = [plan.new_page() for _ in range(3)]
    for page in pages:
        plan.frame(page, 3)
    p1, p2, p3 = pages
    _project(plan, p1, 1)
    _wbs(plan, p1, 2, 1, "Synthetic Phase A")
    _wbs(plan, p1, 3, 2, "Synthetic Stage 1")
    _wbs(plan, p1, 4, 3, "Synthetic Step 1")
    index = 0
    line = 5
    # Level-4 jitter: ID left edges alternate +0.0 / +0.6 pt (contract 8.3).
    for shift in (D(0), JITTER, D(0), JITTER):
        plan.activity(
            p1,
            baseline(line),
            4,
            f"SYN-{1000 + index}",
            _name(index + 1),
            dur("4"),
            dur("4"),
            day(_d(5, 4)),
            day(_d(5, 8)),
            x_shift=shift,
        )
        index += 1
        line += 1
    for level, label in (
        (4, "Synthetic Block 1"),
        (5, "Synthetic Unit 1"),
        (6, "Synthetic Part 1"),
    ):
        _wbs(plan, p1, line, level, label)
        line += 1
    for _ in range(3):
        _standard_activity(plan, p1, line, 7, index)
        index += 1
        line += 1
    # Page 2 opens with level-7 activities whose parent is on page 1.
    for line in (1, 2, 3):
        _standard_activity(plan, p2, line, 7, index)
        index += 1
    _wbs(plan, p2, 4, 3, "Synthetic Step 2")
    plan.activity(
        p2,
        baseline(5),
        4,
        f"SYN-{1000 + index}",
        _name(index + 1),
        dur("4"),
        dur("4"),
        day(_d(6, 1)),
        day(_d(6, 5)),
    )
    index += 1
    # The repeated label at a second position (page 3).
    _wbs(plan, p3, 1, 1, "Synthetic Phase A")
    _wbs(plan, p3, 2, 2, "Synthetic Stage 2")
    _standard_activity(plan, p3, 3, 3, index)
    return plan.case("full_nested_hierarchy", variant, COMPLETE)


def full_header_occluded_od(variant: str) -> FixtureCase:
    plan = Plan()
    p1 = plan.new_page()
    p2 = plan.new_page()
    plan.frame(p1, 2)
    occluding = Draw(token_for(DATA_DATE), REGULAR, BODY, D("436.0"), ANCHOR_Y, role="meta")
    anchors: dict[int, str | None] = {2: None} if variant == "replaced" else {}
    plan.frame(p2, 2, anchors=anchors, extra_header=[occluding])
    _project(plan, p1, 1)
    _wbs(plan, p1, 2, 1, "Synthetic Phase A")
    _standard_activity(plan, p1, 3, 2, 0)
    _standard_activity(plan, p2, 1, 2, 1)
    _standard_activity(plan, p2, 2, 2, 2)
    plan.document_issues.append(("header_od_occluded", 2, ORIGINAL_DURATION))
    return plan.case("full_header_occluded_od", variant, COMPLETE)


def full_header_mismatch(variant: str) -> FixtureCase:
    plan = Plan()
    p1 = plan.new_page()
    p2 = plan.new_page()
    broken = {3: None, 4: None}
    plan.frame(p1, 2, anchors=broken if variant == "first_page" else None)
    plan.frame(p2, 2, anchors=broken if variant == "later_page" else None)
    _project(plan, p1, 1)
    _wbs(plan, p1, 2, 1, "Synthetic Phase A")
    _standard_activity(plan, p1, 3, 2, 0)
    _standard_activity(plan, p2, 1, 2, 1)
    if variant == "first_page":
        return _failed(plan.case("full_header_mismatch", variant, FAILED), "unsupported_layout", 1)
    plan.document_issues.append(("header_signature_mismatch", 2, None))
    return plan.case("full_header_mismatch", variant, REVIEW_REQUIRED)


def full_missing_activity_id(variant: str) -> FixtureCase:
    plan = Plan()
    p1 = plan.new_page()
    p2 = plan.new_page()
    plan.frame(p1, 2)
    plan.frame(p2, 2)
    _project(plan, p1, 1)
    _wbs(plan, p1, 2, 1, "Synthetic Phase A")
    _standard_activity(plan, p1, 3, 2, 0)
    _standard_activity(plan, p2, 1, 2, 1)
    y = baseline(2)
    vals = {
        ORIGINAL_DURATION: dur("6"),
        REMAINING_DURATION: dur("6"),
        START: day(_d(6, 8)),
        FINISH: day(_d(6, 15)),
    }
    draws = {
        ORIGINAL_DURATION: [Draw("6", REGULAR, BODY, OD_RIGHT - D("3.5"), y)],
        REMAINING_DURATION: [Draw("6", REGULAR, BODY, RD_RIGHT - D("3.5"), y)],
        START: [Draw(token_for(_d(6, 8)), REGULAR, BODY, START_X, y)],
        FINISH: [Draw(token_for(_d(6, 15)), REGULAR, BODY, FINISH_X, y)],
    }
    plan.bare_row(p2, draws, vals, issues=[("activity_like_row_missing_id", ACTIVITY_ID)])
    plan.chart_copies(p2, y, "Synthetic unidentified activity")
    _standard_activity(plan, p2, 3, 2, 2)
    return plan.case("full_missing_activity_id", variant, REVIEW_REQUIRED)


def full_duplicate_activity_id(variant: str) -> FixtureCase:
    plan = Plan()
    p1 = plan.new_page()
    plan.frame(p1, 1)
    _project(plan, p1, 1)
    _wbs(plan, p1, 2, 1, "Synthetic Phase A")
    duplicate = [("duplicate_activity_id", ACTIVITY_ID)]
    plan.activity(
        p1,
        baseline(3),
        2,
        "SYN-1100",
        _name(1),
        dur("5"),
        dur("5"),
        day(_d(5, 4)),
        day(_d(5, 8)),
        issues=duplicate,
    )
    _standard_activity(plan, p1, 4, 2, 1)
    plan.activity(
        p1,
        baseline(5),
        2,
        "SYN-1100",
        _name(3),
        dur("7"),
        dur("7"),
        day(_d(5, 11)),
        day(_d(5, 19)),
        issues=duplicate,
    )
    return plan.case("full_duplicate_activity_id", variant, REVIEW_REQUIRED)


def _duration_date_plan(where: str) -> Plan:
    plan = Plan()
    p1 = plan.new_page()
    plan.frame(p1, 1)
    _project(plan, p1, 1)
    token = token_for(_d(3, 15, 2028))
    if where == "rd":
        plan.summary(
            p1,
            baseline(2),
            1,
            "Synthetic Phase A",
            dur("30"),
            bad(token),
            day(_d(5, 4)),
            day(_d(6, 12)),
            issues=[("invalid_duration", REMAINING_DURATION)],
        )
        plan.activity(
            p1,
            baseline(3),
            2,
            "SYN-1000",
            _name(1),
            dur("10"),
            bad(token),
            day(_d(5, 4)),
            day(_d(5, 15)),
            issues=[("invalid_duration", REMAINING_DURATION)],
        )
    else:
        _wbs(plan, p1, 2, 1, "Synthetic Phase A")
        plan.activity(
            p1,
            baseline(3),
            2,
            "SYN-1000",
            _name(1),
            bad(token),
            dur("5"),
            day(_d(5, 4)),
            day(_d(5, 15)),
            issues=[("invalid_duration", ORIGINAL_DURATION)],
        )
    _standard_activity(plan, p1, 4, 2, 1)
    return plan


def _place_date_token_at(plan: Plan, fld: str, x: Decimal) -> None:
    """Move the drawn token of `fld` in every row that failed it to `x`."""
    for row in plan.rows:
        cell = row.cells[fld]
        if row.vals[fld].state != EXTRACTION_FAILED:
            continue
        old = cell.draws[0]
        moved = replace(old, x=x)
        page = plan.pages[row.page - 1]
        page[page.index(old)] = moved
        cell.draws[0] = moved


def full_duration_date_in_rd(variant: str) -> FixtureCase:
    plan = _duration_date_plan("rd")
    _place_date_token_at(plan, REMAINING_DURATION, D("467.6"))
    return plan.case("full_duration_date_in_rd", variant, PARTIAL)


def full_duration_date_in_od(variant: str) -> FixtureCase:
    plan = _duration_date_plan("od")
    _place_date_token_at(plan, ORIGINAL_DURATION, D("436.0"))
    return plan.case("full_duration_date_in_od", variant, PARTIAL)


def full_invalid_date(variant: str) -> FixtureCase:
    plan = Plan()
    p1 = plan.new_page()
    plan.frame(p1, 1)
    _project(plan, p1, 1)
    _wbs(plan, p1, 2, 1, "Synthetic Phase A")
    plan.activity(
        p1,
        baseline(3),
        2,
        "SYN-1000",
        _name(1),
        dur("10"),
        dur("5"),
        day(_d(2, 2, 2027)),
        bad("31-Feb-27"),
        issues=[("invalid_date", FINISH)],
    )
    plan.activity(
        p1,
        baseline(4),
        2,
        "SYN-1001",
        _name(2),
        dur("10"),
        dur("5"),
        bad("30-Foo-26"),
        day(_d(6, 30)),
        issues=[("invalid_date", START)],
    )
    _standard_activity(plan, p1, 5, 2, 2)
    return plan.case("full_invalid_date", variant, PARTIAL)


def full_chart_duplicates(variant: str) -> FixtureCase:
    plan = Plan()
    p1 = plan.new_page()
    plan.frame(p1, 1)
    _project(plan, p1, 1)
    _wbs(plan, p1, 2, 1, "Synthetic Phase A")
    for line, index in ((3, 0), (4, 1), (5, 2), (6, 3)):
        _standard_activity(plan, p1, line, 2, index)
    for ordinal, row in enumerate(plan.rows, start=1):
        plan.chart_copies(p1, baseline(ordinal), row.name or "", row.vals[START], row.vals[FINISH])
    return plan.case("full_chart_duplicates", variant, COMPLETE)


def full_draft_watermark(variant: str) -> FixtureCase:
    plan = Plan()
    p1 = plan.new_page()
    plan.frame(p1, 1)
    _project(plan, p1, 1)
    _wbs(plan, p1, 2, 1, "Synthetic Phase A")
    for line in range(3, 21):
        index = line - 3
        if line == 6:
            plan.activity(
                p1,
                baseline(line),
                2,
                "SYN-1003",
                "DRAFT",
                dur("3"),
                dur("3"),
                day(_d(5, 4)),
                day(_d(5, 6)),
            )
        elif line == 8 and variant in ("slight_skew", "skew_1deg"):
            rot = ROT_0_4 if variant == "slight_skew" else ROT_1
            skewed = Draw("Synthetic skew activity", REGULAR, BODY, NAME_X, baseline(line), rot)
            plan.activity(
                p1,
                baseline(line),
                2,
                f"SYN-{1000 + index}",
                "Synthetic skew activity",
                dur("10"),
                dur("5"),
                day(_d(5, 4)),
                day(_d(5, 15)),
                name_draws=[skewed],
            )
        else:
            _standard_activity(plan, p1, line, 2, index)
    shift = (D(-20), D(20)) if variant == "off_signature" else (D(0), D(0))
    mark = plan.watermark(p1, shift=shift)
    if variant == "double_draw":
        plan.draw(p1, replace(mark, tr=1, suppressed=True))
    if variant in ("off_signature", "skew_1deg"):
        return _failed(plan.case("full_draft_watermark", variant, FAILED), "unsupported_layout", 1)
    return plan.case("full_draft_watermark", variant, COMPLETE)


def full_duplicate_text_object(variant: str) -> FixtureCase:
    plan = Plan()
    p1 = plan.new_page()
    plan.frame(p1, 1)
    _project(plan, p1, 1)
    _wbs(plan, p1, 2, 1, "Synthetic Phase A")
    # `under_watermark` moves the duplicated rows into the watermark's box
    # (y 252..512 pt) and gives the duplicated name a box reaching x 301 pt.
    under = variant == "under_watermark"
    first = 14 if under else 3
    for line in range(3, first):
        _standard_activity(plan, p1, line, 2, line - 3)
    y_name = baseline(first)
    y_od = baseline(first + 1)
    long_name = "Synthetic activity with a deliberately long name 01"
    name = long_name if under else _name(90)
    outcome = PARTIAL
    if variant in ("base", "under_watermark"):
        original = Draw(name, REGULAR, BODY, NAME_X, y_name)
        copies = [
            replace(original, suppressed=True),
            replace(original, x=NAME_X + D("0.2"), suppressed=True),
        ]
        plan.activity(
            p1,
            y_name,
            2,
            "SYN-1090",
            name,
            dur("10"),
            dur("5"),
            day(_d(5, 4)),
            day(_d(5, 15)),
            name_draws=[original],
            issues=[("duplicate_text_object_collapsed", ACTIVITY_NAME)],
        )
        for copy in copies:
            plan.draw(p1, copy)
        plan.extra_counts["duplicate_objects_collapsed"] = 2
    elif variant == "shift_0_5":
        original = Draw(name, REGULAR, BODY, NAME_X, y_name)
        shifted = replace(original, x=NAME_X + D("0.5"), suppressed=True)
        plan.activity(
            p1,
            y_name,
            2,
            "SYN-1090",
            name,
            dur("10"),
            dur("5"),
            day(_d(5, 4)),
            day(_d(5, 15)),
            name_draws=[original, shifted],
            row_type=AMBIGUOUS,
            issues=[("overlapping_cell_text", ACTIVITY_NAME), ("ambiguous_cell", ACTIVITY_NAME)],
        )
        _ambiguous_row_from_activity(plan)
        plan.rows[-1].cells[ACTIVITY_NAME].state = AMBIGUOUS
        outcome = REVIEW_REQUIRED
    elif variant == "bold_over_regular":
        original = Draw(name, REGULAR, BODY, NAME_X, y_name)
        bold = replace(original, font=BOLD, suppressed=True)
        plan.activity(
            p1,
            y_name,
            2,
            "SYN-1090",
            name,
            dur("10"),
            dur("5"),
            day(_d(5, 4)),
            day(_d(5, 15)),
            name_draws=[original, bold],
            row_type=AMBIGUOUS,
            issues=[("overlapping_cell_text", ACTIVITY_NAME), ("ambiguous_cell", None)],
        )
        _ambiguous_row_from_activity(plan)
        plan.rows[-1].cells[ACTIVITY_NAME].state = AMBIGUOUS
        plan.rows[-1].cells[ACTIVITY_ID].state = AMBIGUOUS
        outcome = REVIEW_REQUIRED
    else:  # same_text_2pt
        plan.activity(
            p1, y_name, 2, "SYN-1090", name, dur("10"), dur("5"), day(_d(5, 4)), day(_d(5, 15))
        )
    if variant != "shift_0_5" and variant != "bold_over_regular":
        # OD `5` drawn twice: 0.3 pt apart (suppressed, not collapsed) or 2.0 pt
        # apart (`same_text_2pt`: both reported).
        offset = D("2.0") if variant == "same_text_2pt" else D("0.3")
        od = Draw("5", REGULAR, BODY, OD_RIGHT - D("3.5"), y_od)
        second = replace(od, x=od.x + offset, suppressed=variant != "same_text_2pt")
        plan.activity(
            p1,
            y_od,
            2,
            "SYN-1091",
            _name(91),
            ambiguous_val("5"),
            dur("5"),
            day(_d(5, 4)),
            day(_d(5, 15)),
            issues=[("overlapping_cell_text", ORIGINAL_DURATION)],
        )
        row = plan.rows[-1]
        page = plan.pages[p1 - 1]
        drawn = row.cells[ORIGINAL_DURATION].draws[0]
        page[page.index(drawn)] = od
        page.append(second)
        row.cells[ORIGINAL_DURATION].draws[:] = [od, second]
    if under:
        plan.watermark(p1)
    return plan.case("full_duplicate_text_object", variant, outcome)


def full_overlapping_cell_text(variant: str) -> FixtureCase:
    fonts = default_fonts()
    if variant == "unmapped":
        fonts.append(FontSpec(UNMAPPED, "Arial", to_unicode=False))
    plan = Plan(fonts)
    p1 = plan.new_page()
    plan.frame(p1, 1)
    _project(plan, p1, 1)
    _wbs(plan, p1, 2, 1, "Synthetic Phase A")
    _standard_activity(plan, p1, 3, 2, 0)
    y = baseline(4)
    outcome = REVIEW_REQUIRED
    if variant == "od":
        plan.activity(
            p1,
            y,
            2,
            "SYN-1101",
            _name(2),
            ambiguous_val("5"),
            dur("5"),
            day(_d(5, 4)),
            day(_d(5, 15)),
            issues=[("overlapping_cell_text", ORIGINAL_DURATION)],
        )
        row = plan.rows[-1]
        five = row.cells[ORIGINAL_DURATION].draws[0]
        eight = plan.draw(p1, replace(five, text="8", x=five.x + D("0.3")))
        row.cells[ORIGINAL_DURATION].draws.append(eight)
        outcome = PARTIAL
    elif variant in ("id", "id_split"):
        if variant == "id":
            first = Draw("SYN-1101", REGULAR, BODY, INDENT[2], y)
            second = Draw("SYN-1102", REGULAR, BODY, INDENT[2] + D("0.3"), y)
            issues = [("overlapping_cell_text", ACTIVITY_ID), ("ambiguous_cell", ACTIVITY_ID)]
        else:
            first = Draw("SYN-", REGULAR, BODY, INDENT[2], y)
            second = Draw("1201", REGULAR, BODY, INDENT[2] + D(14), y)
            issues = [("ambiguous_cell", ACTIVITY_ID)]
        vals = {
            ORIGINAL_DURATION: dur("10"),
            REMAINING_DURATION: dur("5"),
            START: day(_d(5, 4)),
            FINISH: day(_d(5, 15)),
        }
        draws = {
            ACTIVITY_ID: [first, second],
            ACTIVITY_NAME: [Draw(_name(2), REGULAR, BODY, NAME_X, y)],
            ORIGINAL_DURATION: [Draw("10", REGULAR, BODY, OD_RIGHT - BODY, y)],
            REMAINING_DURATION: [Draw("5", REGULAR, BODY, RD_RIGHT - D("3.5"), y)],
            START: [Draw(token_for(_d(5, 4)), REGULAR, BODY, START_X, y)],
            FINISH: [Draw(token_for(_d(5, 15)), REGULAR, BODY, FINISH_X, y)],
        }
        plan.bare_row(p1, draws, vals, issues=issues, states={ACTIVITY_ID: AMBIGUOUS})
    elif variant == "unmapped":
        name = Draw(_name(2), UNMAPPED, BODY, NAME_X, y)
        plan.activity(
            p1,
            y,
            2,
            "SYN-1101",
            _name(2),
            dur("10"),
            dur("5"),
            day(_d(5, 4)),
            day(_d(5, 15)),
            name_draws=[name],
            row_type=AMBIGUOUS,
            issues=[("ambiguous_cell", ACTIVITY_NAME)],
        )
        _ambiguous_row_from_activity(plan)
        plan.rows[-1].cells[ACTIVITY_NAME].state = AMBIGUOUS
    else:  # zero_char_object
        plan.activity(
            p1,
            y,
            2,
            "SYN-1101",
            _name(2),
            dur("10"),
            ambiguous_val("5"),
            day(_d(5, 4)),
            day(_d(5, 15)),
            issues=[("ambiguous_cell", REMAINING_DURATION)],
        )
        row = plan.rows[-1]
        # Codes 0x0a 0x0b lie outside FirstChar..LastChar: 0 characters and a
        # zero-area box at the show origin (measured).
        ghost = plan.draw(
            p1, Draw("", REGULAR, BODY, D(480), y, codes=b"\x0a\x0b", suppressed=True)
        )
        row.cells[REMAINING_DURATION].draws.append(ghost)
        row.cells[REMAINING_DURATION].text = "5"
        outcome = PARTIAL
    _standard_activity(plan, p1, 5, 2, 3)
    return plan.case("full_overlapping_cell_text", variant, outcome)


def full_ambiguous_hierarchy(variant: str) -> FixtureCase:
    plan = Plan()
    p1 = plan.new_page()
    plan.frame(p1, 1)
    hierarchy = [("hierarchy_ambiguous", HIERARCHY)]
    if variant == "close_centroids":
        plan.summary(
            p1,
            baseline(1),
            0,
            "Synthetic Project",
            dur("120"),
            dur("80"),
            day(_d(5, 4)),
            day(_d(10, 30)),
            issues=hierarchy,
        )
        for line in (2, 3):
            plan.activity(
                p1,
                baseline(line),
                1,
                f"SYN-{998 + line}",
                _name(line - 1),
                dur("10"),
                dur("5"),
                day(_d(5, 4)),
                day(_d(5, 15)),
                issues=hierarchy,
            )
            plan.rows[-1].cells[ACTIVITY_ID].draws[0] = _moved_id(plan, D("54.40"))
        for row in plan.rows:
            row.level = None
            row.parent = None
            row.determinate = False
        plan.rows[0].row_type = WBS_SUMMARY
    elif variant == "orphan":
        plan.activity(
            p1,
            baseline(1),
            2,
            "SYN-1000",
            _name(1),
            dur("10"),
            dur("5"),
            day(_d(5, 4)),
            day(_d(5, 15)),
            issues=hierarchy,
        )
        plan.rows[-1].determinate = False
        _project(plan, p1, 2)
        _wbs(plan, p1, 3, 1, "Synthetic Phase A")
        _standard_activity(plan, p1, 4, 2, 1)
        _standard_activity(plan, p1, 5, 2, 2)
    else:  # level_gap
        _project(plan, p1, 1)
        _wbs(plan, p1, 2, 1, "Synthetic Phase A")
        _standard_activity(plan, p1, 3, 2, 0)
        _standard_activity(plan, p1, 4, 2, 1)
        plan.activity(
            p1,
            baseline(5),
            3,
            "SYN-1002",
            _name(3),
            dur("10"),
            dur("5"),
            day(_d(5, 4)),
            day(_d(5, 15)),
            issues=hierarchy,
        )
        plan.rows[-1].parent = None
        plan.rows[-1].determinate = False
    return plan.case("full_ambiguous_hierarchy", variant, PARTIAL)


def _moved_id(plan: Plan, x: Decimal) -> Draw:
    row = plan.rows[-1]
    old = row.cells[ACTIVITY_ID].draws[0]
    moved = replace(old, x=x)
    page = plan.pages[row.page - 1]
    page[page.index(old)] = moved
    return moved


def full_row_wrap_unsupported(variant: str) -> FixtureCase:
    plan = Plan()
    p1 = plan.new_page()
    plan.frame(p1, 1)
    _project(plan, p1, 1)
    _wbs(plan, p1, 2, 1, "Synthetic Phase A")
    wrap = [("row_wrap_unsupported", None)]
    if variant == "regular_name":
        _standard_activity(plan, p1, 3, 2, 0)
        line = Draw("Synthetic continuation text", REGULAR, BODY, NAME_X, baseline(3) - 8)
        plan.bare_row(
            p1, {ACTIVITY_NAME: [line]}, {}, issues=wrap, states={ACTIVITY_NAME: PUBLISHED_VALUE}
        )
    else:
        _wbs(plan, p1, 3, 2, "Synthetic Stage with a label")
        line = Draw("continued onto a second line", BOLD, BODY, INDENT[2], baseline(3) - 8)
        plan.bare_row(
            p1, {ACTIVITY_ID: [line]}, {}, issues=wrap, states={ACTIVITY_ID: PUBLISHED_BLANK}
        )
        # A bold label belongs to the merged name cell (summary case).
        row = plan.rows[-1]
        row.cells[ACTIVITY_NAME] = _Cell(state=PUBLISHED_VALUE, draws=[line])
        row.cells[ACTIVITY_ID] = _Cell(state=PUBLISHED_BLANK)
        _standard_activity(plan, p1, 5, 3, 1)
    _standard_activity(plan, p1, 6, 2, 2)
    return plan.case("full_row_wrap_unsupported", variant, REVIEW_REQUIRED)


# family 19 -------------------------------------------------------------------

PAGES_86 = 86
ROWS_PER_PAGE_86 = tuple(40 if page <= 54 else 39 for page in range(1, PAGES_86 + 1))


def _corpus_sequence() -> list[tuple[str, int]]:
    """(kind, level) for the 3408 rows: `P`, `W`, `A` (activity-like)."""
    sequence: list[tuple[str, int]] = [("P", 0)]
    groups: list[int] = []
    for _ in range(73):
        sequence += [("W", 1), ("W", 2), ("W", 3)]
        groups.append(len(sequence))
        sequence += [("W", 4), ("W", 5), ("W", 6)]
        groups.append(len(sequence))
    sequence += [("W", 1), ("W", 2), ("W", 3)]
    groups.append(len(sequence))
    sequence += [("W", 4)]
    groups.append(len(sequence))
    # 2965 activity-like rows over 148 groups: 20 each, 5 extra in the first 5.
    levels = []
    for position in groups:
        level = sequence[position - 1][1] + 1
        levels.append((position, level))
    expanded: list[tuple[str, int]] = []
    cursor = 0
    for group_index, (position, level) in enumerate(levels):
        expanded += sequence[cursor:position]
        size = 21 if group_index < 5 else 20
        expanded += [("A", level)] * size
        cursor = position
    expanded += sequence[cursor:]
    return expanded


def full_multi_page_86_equivalent(variant: str) -> FixtureCase:
    sequence = _corpus_sequence()
    plan = Plan()
    pages = [plan.new_page() for _ in range(PAGES_86)]
    for page in pages:
        if page == 37:
            occluding = Draw(token_for(DATA_DATE), REGULAR, BODY, D("436.0"), ANCHOR_Y, role="meta")
            plan.frame(page, PAGES_86, anchors={2: None}, extra_header=[occluding])
        else:
            plan.frame(page, PAGES_86)
    plan.document_issues.append(("header_od_occluded", 37, ORIGINAL_DURATION))
    slots: list[tuple[int, int]] = [
        (page, line) for page in pages for line in range(1, ROWS_PER_PAGE_86[page - 1] + 1)
    ]
    first_row_on: dict[int, int] = {}
    for ordinal, (page, _line) in enumerate(slots):
        first_row_on.setdefault(page, ordinal)
    # The single missing-ID row: the 6th activity-like row on page 21.
    activity_like = [i for i, (kind, _l) in enumerate(sequence) if kind == "A"]
    page21 = [i for i in activity_like if slots[i][0] == 21]
    missing = page21[5]
    summary_rd = next(i for i, (k, _l) in enumerate(sequence) if k == "W" and slots[i][0] == 55)
    activity_rd = next(i for i in activity_like if slots[i][0] == 58)
    activity_od = next(i for i in activity_like if slots[i][0] == 61)
    id_index = 0
    wbs_index = 0
    level4_seen = 0
    starts = finishes = 0
    bad_token = token_for(_d(3, 15, 2028))
    for ordinal, (kind, level) in enumerate(sequence):
        page, line = slots[ordinal]
        y = baseline(line)
        if kind == "P":
            row = _project(plan, page, line)
        elif kind == "W":
            wbs_index += 1
            rd = dur("40")
            issues: list[tuple[str, str | None]] = []
            if ordinal == summary_rd:
                rd = bad(bad_token)
                issues = [("invalid_duration", REMAINING_DURATION)]
            row = plan.summary(
                page,
                y,
                level,
                f"Synthetic Phase {wbs_index:03d}",
                dur("60"),
                rd,
                day(_d(5, 4)),
                day(_d(7, 31)),
                issues=issues,
            )
        elif ordinal == missing:
            vals = {
                ORIGINAL_DURATION: dur("6"),
                REMAINING_DURATION: dur("6"),
                START: day(_d(6, 8)),
                FINISH: day(_d(6, 15)),
            }
            draws = {
                ORIGINAL_DURATION: [Draw("6", REGULAR, BODY, OD_RIGHT - D("3.5"), y)],
                REMAINING_DURATION: [Draw("6", REGULAR, BODY, RD_RIGHT - D("3.5"), y)],
                START: [Draw(token_for(_d(6, 8)), REGULAR, BODY, START_X, y)],
                FINISH: [Draw(token_for(_d(6, 15)), REGULAR, BODY, FINISH_X, y)],
            }
            row = plan.bare_row(
                page, draws, vals, issues=[("activity_like_row_missing_id", ACTIVITY_ID)]
            )
            plan.chart_copies(page, y, "Synthetic unidentified activity", vals[START], vals[FINISH])
            continue
        else:
            od, rd = dur("10"), dur("5")
            start, finish = day(_d(5, 4)), day(_d(5, 15))
            issues = []
            if id_index % 46 == 10 and starts < 32 and ordinal not in (activity_rd, activity_od):
                od, rd, finish = dur("0"), dur("0"), BLANK
                starts += 1
            elif (
                id_index % 46 == 30 and finishes < 32 and ordinal not in (activity_rd, activity_od)
            ):
                od, rd, start = dur("0"), dur("0"), BLANK
                finishes += 1
            if ordinal == activity_rd:
                rd = bad(bad_token)
                issues = [("invalid_duration", REMAINING_DURATION)]
            if ordinal == activity_od:
                od = bad(bad_token)
                issues = [("invalid_duration", ORIGINAL_DURATION)]
            shift = D(0)
            if level == 4:
                shift = JITTER if level4_seen % 2 else D(0)
                level4_seen += 1
            row = plan.activity(
                page,
                y,
                level,
                f"SYN-{1000 + id_index}",
                f"Synthetic activity {id_index + 1:04d}",
                od,
                rd,
                start,
                finish,
                x_shift=shift,
                issues=issues,
            )
            id_index += 1
        planned = plan.rows[row - 1]
        if ordinal in (summary_rd, activity_rd, activity_od):
            for fld in (ORIGINAL_DURATION, REMAINING_DURATION):
                if planned.vals[fld].state == EXTRACTION_FAILED:
                    x = D("467.6") if fld == REMAINING_DURATION else D("436.0")
                    old = planned.cells[fld].draws[0]
                    moved = replace(old, x=x)
                    sheet = plan.pages[page - 1]
                    sheet[sheet.index(old)] = moved
                    planned.cells[fld].draws[0] = moved
        plan.chart_copies(page, y, planned.name or "", planned.vals[START], planned.vals[FINISH])
    if starts != 32 or finishes != 32:
        raise ValueError("family 19 milestone plan drifted")
    for page in pages:
        plan.watermark(page)
    return plan.case("full_multi_page_86_equivalent", variant, REVIEW_REQUIRED)


# failure families --------------------------------------------------------------


def _failed(case: FixtureCase, code: str, page: int | None = None) -> FixtureCase:
    truth = Truth(FAILED, (), ((code, page, None),), None, None, None, None)
    return replace(case, truth=truth)


def _raw_case(family: str, variant: str, pdf: bytes, code: str) -> FixtureCase:
    truth = Truth(FAILED, (), ((code, None, None),), None, None, None, None)
    return FixtureCase(family, variant, pdf, None, None, None, truth)


def corrupt_pdf(variant: str) -> FixtureCase:
    if variant == "garbage":
        return _raw_case(
            "corrupt_pdf", variant, b"%PDF-1.7\n" + b"\x00garbage\n" * 8, "corrupt_pdf"
        )
    if variant == "not_a_pdf":
        return _raw_case("corrupt_pdf", variant, b"not a pdf", "unsupported_media_type")
    return _raw_case("corrupt_pdf", variant, b"", "unsupported_media_type")


def _small_plan() -> Plan:
    plan = Plan()
    p1 = plan.new_page()
    plan.frame(p1, 1)
    _project(plan, p1, 1)
    _wbs(plan, p1, 2, 1, "Synthetic Phase A")
    _standard_activity(plan, p1, 3, 2, 0)
    _standard_activity(plan, p1, 4, 2, 1)
    return plan


def encrypted_pdf(variant: str) -> FixtureCase:
    plan = _small_plan()
    specs = plan.page_specs()
    if variant == "unknown_filter":
        security = _Rc4Security(b"", b"synthetic-owner")
        pdf = assemble_document(specs, plan.fonts, security=security, encrypt_filter="SynUnknown")
    else:
        user = b"synthetic-user" if variant == "user_password" else b""
        pdf = assemble_document(specs, plan.fonts, security=_Rc4Security(user, b"synthetic-owner"))
    case = plan.case("encrypted_pdf", variant, FAILED)
    return _failed(replace(case, pdf=pdf), "encrypted_pdf")


def image_only_pdf(variant: str) -> FixtureCase:
    specs = (PageSpec(draws=(), image_only=True),)
    pdf = assemble_document(specs, [])
    truth = Truth(FAILED, (), (("image_only_pdf", None, None),), None, None, None, None)
    return FixtureCase("image_only_pdf", variant, pdf, None, None, None, truth, specs, ())


def wrong_page_size(variant: str) -> FixtureCase:
    plan = _small_plan()
    draws = tuple(plan.pages[0])
    if variant == "zero_pages":
        pdf = assemble_document((), plan.fonts)
        truth = Truth(FAILED, (), (("corrupt_pdf", None, None),), None, None, None, None)
        return FixtureCase(
            "wrong_page_size", variant, pdf, None, None, None, truth, (), tuple(plan.fonts)
        )
    spec = {
        "letter": PageSpec(draws, media_box=(0, 0, 612, 792)),
        "rotated": PageSpec(draws, rotate=90),
        "rotated_180": PageSpec(draws, rotate=180),
        "offset_origin": PageSpec(draws, media_box=(100, 50, 1324, 842)),
    }[variant]
    case = plan.case("wrong_page_size", variant, FAILED, page_specs=(spec,))
    return _failed(case, "unsupported_layout", 1)


def page_metadata_mismatch(variant: str) -> FixtureCase:
    plan = Plan()
    p1 = plan.new_page()
    p2 = plan.new_page()
    plan.frame(p1, 2)
    title: str | None = TITLE
    data_date: date | None = DATA_DATE
    run_date: date | None = RUN_DATE
    if variant == "data_date":
        plan.frame(p2, 2, data_date=_d(5, 5))
        data_date = None
    elif variant == "run_date":
        plan.frame(p2, 2, run_date=_d(5, 12))
        run_date = None
    elif variant == "title":
        plan.frame(p2, 2, title="Synthetic Project Schedule Variant")
        title = None
    elif variant == "page_number":
        plan.frame(p2, 2, signature=(1, 2))
    else:  # page_total
        plan.frame(p2, 2, signature=(2, 3))
    _project(plan, p1, 1)
    _wbs(plan, p1, 2, 1, "Synthetic Phase A")
    _standard_activity(plan, p1, 3, 2, 0)
    _standard_activity(plan, p2, 1, 2, 1)
    plan.document_issues.append(("page_metadata_mismatch", 2, None))
    # D-18: an item incoherent across pages is reported as `None`.
    return plan.case(
        "page_metadata_mismatch",
        variant,
        REVIEW_REQUIRED,
        title=title,
        data_date=data_date,
        run_date=run_date,
    )


def expected_data_date_mismatch(variant: str) -> FixtureCase:
    plan = _full_valid_2p_plan("base")
    if variant == "mismatch":
        plan.document_issues.append(("expected_data_date_mismatch", None, None))
        return plan.case(
            "expected_data_date_mismatch", variant, REVIEW_REQUIRED, expected_data_date=_d(5, 5)
        )
    return plan.case("expected_data_date_mismatch", variant, COMPLETE, expected_data_date=_d(5, 4))


#: Tightened limits per bounds variant (contract 8.5, decision on bounds).
BOUNDS_LIMITS: Mapping[str, Mapping[str, int]] = {
    "text_objects": {"max_text_objects": 20},
    "page_objects": {"max_page_objects": 20},
    "chars": {"max_text_chars": 200},
    "rows": {"max_rows": 3},
    "issues": {"max_issues": 1},
    "row_warnings": {"max_row_warnings": 1},
    "hierarchy_depth": {"max_hierarchy_depth": 2},
    "cell_evidence": {"max_cell_evidence_bytes": 256},
}
#: Synthetic choice for `time_mid`: 3 clock reads (after V2, after open, before
#: page 1 loads) return 0.0; the 4th (before page 2 loads) expires.
TIME_MID_CALLS = 3
MAX_BYTES = 16_777_216


def bounds_exceeded(variant: str) -> FixtureCase:
    family = "bounds_exceeded"
    if variant == "bytes":
        base = full_valid_2p("base")
        padded = base.pdf + b"\n" * (MAX_BYTES + 1 - len(base.pdf))
        return _failed(
            replace(base, family=family, variant=variant, pdf=padded), "source_too_large"
        )
    if variant == "pages":
        specs = tuple(PageSpec(draws=()) for _ in range(251))
        pdf = assemble_document(specs, [])
        truth = Truth(FAILED, (), (("bounds_exceeded", None, None),), None, None, None, None)
        return FixtureCase(family, variant, pdf, None, None, None, truth, specs, ())
    if variant in ("form_text", "form_depth"):
        plan = _small_plan()
        text = Draw("SYN-9000", REGULAR, BODY, D(40), D(300)) if variant == "form_text" else None
        form = FormSpec(depth=1 if variant == "form_text" else 5, text=text)
        spec = PageSpec(tuple(plan.pages[0]), form=form)
        case = plan.case(family, variant, FAILED, page_specs=(spec,))
        return _failed(case, "unsupported_layout", 1)
    if variant in ("time_first", "time_mid"):
        base = full_valid_2p("base")
        calls = 0 if variant == "time_first" else TIME_MID_CALLS
        case = replace(base, family=family, variant=variant, clock_calls_before_expiry=calls)
        return _failed(case, "processing_budget_exceeded")
    source: FixtureCase
    if variant == "rows":
        source = _small_plan().case(family, variant, FAILED)
    elif variant == "issues":
        source = full_invalid_date("base")
    elif variant == "row_warnings":
        source = full_duplicate_text_object("shift_0_5")
    else:
        source = full_valid_2p("base")
    case = replace(source, family=family, variant=variant, limits=BOUNDS_LIMITS[variant])
    return _failed(case, "bounds_exceeded")


# --- registry ------------------------------------------------------------------

#: The 26 R2 section 37 families, in contract 8.5 order, with their variants.
FAMILIES: Mapping[str, tuple[Builder, tuple[str, ...]]] = {
    "full_valid_2p": (
        full_valid_2p,
        ("base", "subset_prefix", "zone_edges", "split_name", "id_double_space"),
    ),
    "full_merged_summary_label": (full_merged_summary_label, ("base", "label_only")),
    "full_summary_vertical_offset": (full_summary_vertical_offset, ("base", "glyph_metrics")),
    "full_summary_zero_zero": (full_summary_zero_zero, ("base", "id_both_dates")),
    "full_nested_hierarchy": (full_nested_hierarchy, ("base",)),
    "full_header_occluded_od": (full_header_occluded_od, ("replaced", "overlay")),
    "full_header_mismatch": (full_header_mismatch, ("later_page", "first_page")),
    "full_missing_activity_id": (full_missing_activity_id, ("base",)),
    "full_duplicate_activity_id": (full_duplicate_activity_id, ("base",)),
    "full_duration_date_in_rd": (full_duration_date_in_rd, ("base",)),
    "full_duration_date_in_od": (full_duration_date_in_od, ("base",)),
    "full_invalid_date": (full_invalid_date, ("base",)),
    "full_chart_duplicates": (full_chart_duplicates, ("base",)),
    "full_draft_watermark": (
        full_draft_watermark,
        ("signature", "off_signature", "slight_skew", "skew_1deg", "double_draw"),
    ),
    "full_duplicate_text_object": (
        full_duplicate_text_object,
        ("base", "shift_0_5", "bold_over_regular", "same_text_2pt", "under_watermark"),
    ),
    "full_overlapping_cell_text": (
        full_overlapping_cell_text,
        ("od", "id", "id_split", "unmapped", "zero_char_object"),
    ),
    "full_ambiguous_hierarchy": (
        full_ambiguous_hierarchy,
        ("close_centroids", "orphan", "level_gap"),
    ),
    "full_row_wrap_unsupported": (full_row_wrap_unsupported, ("regular_name", "bold_label")),
    "full_multi_page_86_equivalent": (full_multi_page_86_equivalent, ("base",)),
    "corrupt_pdf": (corrupt_pdf, ("garbage", "not_a_pdf", "empty")),
    "encrypted_pdf": (encrypted_pdf, ("user_password", "empty_user_password", "unknown_filter")),
    "image_only_pdf": (image_only_pdf, ("base",)),
    "wrong_page_size": (
        wrong_page_size,
        ("letter", "rotated", "rotated_180", "offset_origin", "zero_pages"),
    ),
    "page_metadata_mismatch": (
        page_metadata_mismatch,
        ("data_date", "run_date", "title", "page_number", "page_total"),
    ),
    "expected_data_date_mismatch": (expected_data_date_mismatch, ("mismatch", "match")),
    "bounds_exceeded": (
        bounds_exceeded,
        (
            "bytes",
            "pages",
            "text_objects",
            "page_objects",
            "chars",
            "rows",
            "issues",
            "row_warnings",
            "hierarchy_depth",
            "cell_evidence",
            "form_text",
            "form_depth",
            "time_first",
            "time_mid",
        ),
    ),
}

CASES: tuple[tuple[str, str], ...] = tuple(
    (family, variant) for family, (_builder, variants) in FAMILIES.items() for variant in variants
)

#: Cases whose golden records `result: null` (contract 9).
RESULTLESS_CASES = frozenset(
    {
        ("full_multi_page_86_equivalent", "base"),
        ("bounds_exceeded", "bytes"),
        ("bounds_exceeded", "pages"),
    }
)


@functools.cache
def build(family: str, variant: str) -> FixtureCase:
    """The fixture for one `(family, variant)`; pure, cached per process."""
    builder, variants = FAMILIES[family]
    if variant not in variants:
        raise KeyError(f"{family} has no variant {variant}")
    case = builder(variant)
    _check_watermark_geometry()
    return case


def _check_watermark_geometry() -> None:
    """The `signature` watermark box sits 6..10 pt from every signature edge."""
    x, y = WATERMARK_ORIGIN
    box = analytic_box(Draw("DRAFT", REGULAR, WATERMARK_SIZE, x, y, ROT_7), "uniform")
    for edge, target in zip(box, SIGNATURE_BOX, strict=True):
        if not D(6) <= abs(edge - target) <= D(10):
            raise ValueError("the signature watermark no longer sits 6..10 pt off every edge")


# --- goldens (contract 9) ----------------------------------------------------


def golden_path(family: str, variant: str) -> Path:
    return GOLDEN_DIRECTORY / f"{family}__{variant}.json"


def linkage_basis(outcome: str) -> str:
    if outcome in (COMPLETE, PARTIAL):
        return "eligible"
    return REVIEW_REQUIRED if outcome == REVIEW_REQUIRED else FAILED


def golden_document(case: FixtureCase) -> dict[str, object]:
    """Parse the case with the WP-02 parser and shape its golden (contract 9).

    Imports the parser lazily: this generator stays standard-library only and
    nothing but `write_goldens` reaches the parser.
    """
    from my_pa.domain.schedule import (
        canonical_json_bytes,
        parse_result_object,
        parse_result_sha256,
        stable_link_candidates,
    )
    from my_pa.infrastructure.schedule.full_profile import (
        ScheduleParseLimits,
        parse_full_schedule,
    )

    limits = ScheduleParseLimits(**case.limits) if case.limits else ScheduleParseLimits()
    clock = fake_clock(case.clock_calls_before_expiry)
    deadline = None if case.clock_calls_before_expiry is None else 1.0
    result = parse_full_schedule(
        case.pdf,
        expected_data_date=case.expected_data_date,
        limits=limits,
        clock=clock,
        deadline=deadline,
    )
    obj = parse_result_object(result)
    issue_counts: dict[str, int] = {}
    for issue in result.issues:
        issue_counts[issue.code.value] = issue_counts.get(issue.code.value, 0) + 1
    basis = linkage_basis(result.outcome.value)
    return {
        "family": case.family,
        "variant": case.variant,
        "generator_version": GENERATOR_VERSION,
        "parse_inputs": {
            "expected_data_date": (
                None if case.expected_data_date is None else case.expected_data_date.isoformat()
            ),
            "limits": "production" if not case.limits else dict(case.limits),
        },
        "pdf_sha256": case.sha256,
        "pdf_size_bytes": len(case.pdf),
        "result_sha256": parse_result_sha256(result),
        "summary": {
            "outcome": result.outcome.value,
            "counts": obj["counts"],
            "issue_counts": dict(sorted(issue_counts.items())),
        },
        "linkage": {
            "basis": basis,
            "rows": [
                {"row_ordinal": row.row_ordinal, "published_activity_id": row.published_activity_id}
                for row in stable_link_candidates(result)
            ],
        },
        "result": None
        if (case.family, case.variant) in RESULTLESS_CASES
        else json.loads(canonical_json_bytes(obj)),
    }


def golden_bytes(document: Mapping[str, object]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "ascii"
    )


def fake_clock(calls_before_expiry: int | None) -> Callable[[], float]:
    """0.0 for the first `k` calls, 10.0 after (contract 5.15)."""
    counter = [0]

    def clock() -> float:
        counter[0] += 1
        if calls_before_expiry is None or counter[0] <= calls_before_expiry:
            return 0.0
        return 10.0

    return clock


def write_goldens(directory: Path = GOLDEN_DIRECTORY) -> list[tuple[Path, str]]:
    """Regenerate every golden file. Explicit only; no test calls this."""
    directory.mkdir(parents=True, exist_ok=True)
    written: list[tuple[Path, str]] = []
    for family, variant in CASES:
        data = golden_bytes(golden_document(build(family, variant)))
        path = directory / f"{family}__{variant}.json"
        path.write_bytes(data)
        written.append((path, hashlib.sha256(data).hexdigest()))
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.fixtures.schedule_full_pdf")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("write-goldens", help="regenerate every golden file")
    commands.add_parser("pdf-digests", help="print every generated PDF's SHA-256")
    args = parser.parse_args(argv)
    if args.command == "write-goldens":
        for path, digest in write_goldens():
            print(f"{digest}  {path.name}")
        return 0
    for family, variant in CASES:
        case = build(family, variant)
        print(f"{case.sha256}  {case.name}  {len(case.pdf)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
