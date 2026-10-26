"""CPM Workbench S5a: the parser-facing Full-Schedule vocabulary and records.

Contract: `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
sections 3.3, 4.7, 4.8, 5.13 and 6.1. Pure and standard-library only: nothing
here reads a PDF, a database, the clock or the environment. The closed enums
carry the exact R2 section 43.2 member names and lower-snake values so WP-01
extends this module instead of renaming it; declaration order is the
canonical sort order.

Every record checks its own invariants in `__post_init__` and raises
`ValueError` with a fixed message that never carries source text.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType
from typing import Final

__all__ = [
    "DURATION_EXPONENT",
    "ISSUE_SEVERITY",
    "MAX_DURATION_EXCLUSIVE",
    "MAX_HIERARCHY_PATH",
    "MAX_ROW_WARNING_CODES",
    "ROW_CELL_FIELDS",
    "TERMINAL_OUTCOMES",
    "ParsedScheduleRow",
    "ScheduleBox",
    "ScheduleCellEvidence",
    "ScheduleCellFragment",
    "ScheduleCellState",
    "ScheduleDateCell",
    "ScheduleDurationCell",
    "ScheduleFieldCode",
    "ScheduleIssueCode",
    "ScheduleIssueSeverity",
    "ScheduleParseCounts",
    "ScheduleParseEngine",
    "ScheduleParseIssue",
    "ScheduleParseResult",
    "SchedulePublicationStatus",
    "ScheduleRowType",
    "derive_outcome",
    "normalize_activity_id",
    "normalize_display_text",
    "parse_profile_date",
    "parse_profile_duration",
    "stable_link_candidates",
]


class ScheduleRowType(StrEnum):
    """R2 section 43.2 row types, in canonical order."""

    PROJECT_SUMMARY = "project_summary"
    WBS_SUMMARY = "wbs_summary"
    ACTIVITY = "activity"
    MILESTONE = "milestone"
    AMBIGUOUS = "ambiguous"


class ScheduleCellState(StrEnum):
    """R2 section 17.2 cell states, in canonical order."""

    PUBLISHED_VALUE = "published_value"
    PUBLISHED_BLANK = "published_blank"
    EXTRACTION_FAILED = "extraction_failed"
    AMBIGUOUS = "ambiguous"


class ScheduleIssueSeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


class ScheduleFieldCode(StrEnum):
    """The six table columns plus the hierarchy pseudo-field, in canonical order."""

    ACTIVITY_ID = "activity_id"
    ACTIVITY_NAME = "activity_name"
    ORIGINAL_DURATION = "original_duration"
    REMAINING_DURATION = "remaining_duration"
    START = "start"
    FINISH = "finish"
    HIERARCHY = "hierarchy"


class ScheduleIssueCode(StrEnum):
    """The 23 R2 section 43.2 issue codes, in R2 order.

    `SOURCE_VERSION_CHANGED` belongs to the closed set but the parser never
    emits it (it is a fetch-time condition owned by WP-03).
    """

    SOURCE_VERSION_CHANGED = "source_version_changed"
    SOURCE_TOO_LARGE = "source_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    CORRUPT_PDF = "corrupt_pdf"
    ENCRYPTED_PDF = "encrypted_pdf"
    IMAGE_ONLY_PDF = "image_only_pdf"
    UNSUPPORTED_LAYOUT = "unsupported_layout"
    PAGE_METADATA_MISMATCH = "page_metadata_mismatch"
    EXPECTED_DATA_DATE_MISMATCH = "expected_data_date_mismatch"
    HEADER_SIGNATURE_MISMATCH = "header_signature_mismatch"
    HEADER_OD_OCCLUDED = "header_od_occluded"
    DUPLICATE_TEXT_OBJECT_COLLAPSED = "duplicate_text_object_collapsed"
    OVERLAPPING_CELL_TEXT = "overlapping_cell_text"
    ROW_WRAP_UNSUPPORTED = "row_wrap_unsupported"
    ACTIVITY_LIKE_ROW_MISSING_ID = "activity_like_row_missing_id"
    DUPLICATE_ACTIVITY_ID = "duplicate_activity_id"
    INVALID_DATE = "invalid_date"
    INVALID_DURATION = "invalid_duration"
    AMBIGUOUS_CELL = "ambiguous_cell"
    HIERARCHY_AMBIGUOUS = "hierarchy_ambiguous"
    BOUNDS_EXCEEDED = "bounds_exceeded"
    PARSER_EXCEPTION = "parser_exception"
    PROCESSING_BUDGET_EXCEEDED = "processing_budget_exceeded"


class SchedulePublicationStatus(StrEnum):
    """R2 publication statuses; the parser emits only `TERMINAL_OUTCOMES`."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETE = "complete"
    PARTIAL = "partial"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"


TERMINAL_OUTCOMES: Final = frozenset(
    {
        SchedulePublicationStatus.COMPLETE,
        SchedulePublicationStatus.PARTIAL,
        SchedulePublicationStatus.REVIEW_REQUIRED,
        SchedulePublicationStatus.FAILED,
    }
)

_WARNING_CODES: Final = frozenset(
    {ScheduleIssueCode.HEADER_OD_OCCLUDED, ScheduleIssueCode.DUPLICATE_TEXT_OBJECT_COLLAPSED}
)

#: Total over `ScheduleIssueCode`: two warnings, every other code an error.
ISSUE_SEVERITY: Final[Mapping[ScheduleIssueCode, ScheduleIssueSeverity]] = MappingProxyType(
    {
        code: (
            ScheduleIssueSeverity.WARNING if code in _WARNING_CODES else ScheduleIssueSeverity.ERROR
        )
        for code in ScheduleIssueCode
    }
)

#: The six cells every row carries, in field order (`HIERARCHY` is not a cell).
ROW_CELL_FIELDS: Final = (
    ScheduleFieldCode.ACTIVITY_ID,
    ScheduleFieldCode.ACTIVITY_NAME,
    ScheduleFieldCode.ORIGINAL_DURATION,
    ScheduleFieldCode.REMAINING_DURATION,
    ScheduleFieldCode.START,
    ScheduleFieldCode.FINISH,
)

MAX_HIERARCHY_PATH: Final = 32
MAX_ROW_WARNING_CODES: Final = 16
DURATION_EXPONENT: Final = -3
#: `NUMERIC(12,3)`: at most 9 integer digits.
MAX_DURATION_EXCLUSIVE: Final = Decimal(1_000_000_000)

_CODE_ORDER: Final = {code: index for index, code in enumerate(ScheduleIssueCode)}
_SHA256_HEX: Final = re.compile(r"[0-9a-f]{64}")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _positive_int(value: object) -> bool:
    return _is_int(value) and value > 0  # type: ignore[operator]


@dataclass(frozen=True, slots=True)
class ScheduleBox:
    """A PDF-space box in integer millipoints (1 pt = 1000 mpt)."""

    x0: int
    y0: int
    x1: int
    y1: int

    def __post_init__(self) -> None:
        if not all(_is_int(v) for v in (self.x0, self.y0, self.x1, self.y1)):
            raise ValueError("a schedule box holds integer millipoints")
        if self.x0 > self.x1 or self.y0 > self.y1:
            raise ValueError("a schedule box must have x0 <= x1 and y0 <= y1")


@dataclass(frozen=True, slots=True)
class ScheduleCellFragment:
    """One source text object's evidence inside a cell."""

    raw: str
    box: ScheduleBox
    font_base_name: str
    font_size_mpt: int

    def __post_init__(self) -> None:
        if not _is_int(self.font_size_mpt) or self.font_size_mpt < 0:
            raise ValueError("a cell fragment font size is non-negative millipoints")


@dataclass(frozen=True, slots=True)
class ScheduleCellEvidence:
    """One table cell: its state, normalized text and source fragments."""

    field: ScheduleFieldCode
    state: ScheduleCellState
    text: str | None
    fragments: tuple[ScheduleCellFragment, ...]

    def __post_init__(self) -> None:
        if self.field not in ROW_CELL_FIELDS:
            raise ValueError("cell evidence names one of the six table fields")
        if (self.text is None) != (not self.fragments):
            raise ValueError("cell evidence text is None iff it has no fragments")
        if self.state is ScheduleCellState.PUBLISHED_BLANK and self.fragments:
            raise ValueError("a published-blank cell has no fragments")


@dataclass(frozen=True, slots=True)
class ScheduleDurationCell:
    state: ScheduleCellState
    value: Decimal | None

    def __post_init__(self) -> None:
        if (self.value is not None) != (self.state is ScheduleCellState.PUBLISHED_VALUE):
            raise ValueError("a duration value is present iff the cell is published_value")
        if self.value is not None:
            if not self.value.is_finite():
                raise ValueError("a duration value is a finite Decimal")
            if self.value.as_tuple().exponent != DURATION_EXPONENT:
                raise ValueError("a duration value is quantized to 3 decimals")
            if self.value < 0 or self.value >= MAX_DURATION_EXCLUSIVE:
                raise ValueError("a duration value is non-negative and fits NUMERIC(12,3)")


@dataclass(frozen=True, slots=True)
class ScheduleDateCell:
    state: ScheduleCellState
    value: date | None
    marker: str | None

    def __post_init__(self) -> None:
        if (self.value is not None) != (self.state is ScheduleCellState.PUBLISHED_VALUE):
            raise ValueError("a date value is present iff the cell is published_value")
        if self.marker not in (None, "*"):
            raise ValueError("a date marker is absent or '*'")
        if self.marker is not None and self.value is None:
            raise ValueError("a date marker needs a date value")


@dataclass(frozen=True, slots=True)
class ScheduleParseIssue:
    code: ScheduleIssueCode
    severity: ScheduleIssueSeverity
    page_number: int | None
    row_ordinal: int | None
    field: ScheduleFieldCode | None

    def __post_init__(self) -> None:
        if not isinstance(self.code, ScheduleIssueCode):
            raise ValueError("an issue carries a closed issue code")
        if self.severity is not ISSUE_SEVERITY[self.code]:
            raise ValueError("an issue severity must equal ISSUE_SEVERITY[code]")
        for ordinal in (self.page_number, self.row_ordinal):
            if ordinal is not None and not _positive_int(ordinal):
                raise ValueError("issue page and row references are 1-based")
        if self.field is not None and not isinstance(self.field, ScheduleFieldCode):
            raise ValueError("an issue field is a closed field code")


def _dense_increasing(codes: Sequence[ScheduleIssueCode]) -> bool:
    order = [_CODE_ORDER[code] for code in codes]
    return all(left < right for left, right in pairwise(order))


@dataclass(frozen=True, slots=True)
class ParsedScheduleRow:
    """One physical table row of a Full-Schedule publication (contract 6.1)."""

    row_ordinal: int
    page_number: int
    physical_line_ordinal: int
    row_type: ScheduleRowType
    indent_level: int | None
    parent_row_ordinal: int | None
    hierarchy_path: tuple[str, ...] | None
    published_activity_id: str | None
    activity_name: str | None
    original_duration: ScheduleDurationCell
    remaining_duration: ScheduleDurationCell
    start: ScheduleDateCell
    finish: ScheduleDateCell
    box: ScheduleBox
    page_width_mpt: int
    page_height_mpt: int
    cells: tuple[ScheduleCellEvidence, ...]
    warning_codes: tuple[ScheduleIssueCode, ...]

    def __post_init__(self) -> None:
        if not all(
            _positive_int(v)
            for v in (
                self.row_ordinal,
                self.page_number,
                self.physical_line_ordinal,
                self.page_width_mpt,
                self.page_height_mpt,
            )
        ):
            raise ValueError("row ordinals and page dimensions are positive integers")
        if self.indent_level is not None and (
            not _is_int(self.indent_level) or self.indent_level < 0
        ):
            raise ValueError("an indent level is a non-negative integer")
        self._check_identity()
        if self.parent_row_ordinal is not None and (
            not _positive_int(self.parent_row_ordinal)
            or self.parent_row_ordinal >= self.row_ordinal
        ):
            raise ValueError("a parent row precedes its child")
        if self.hierarchy_path is not None and len(self.hierarchy_path) > MAX_HIERARCHY_PATH:
            raise ValueError("a hierarchy path holds at most 32 labels")
        if len(self.warning_codes) > MAX_ROW_WARNING_CODES:
            raise ValueError("a row carries at most 16 warning codes")
        if not _dense_increasing(self.warning_codes):
            raise ValueError("row warning codes are distinct and in declaration order")
        if tuple(cell.field for cell in self.cells) != ROW_CELL_FIELDS:
            raise ValueError("a row carries exactly the six cells in field order")

    def _check_identity(self) -> None:
        row_type = self.row_type
        if row_type in (ScheduleRowType.ACTIVITY, ScheduleRowType.MILESTONE):
            if not self.published_activity_id or not self.activity_name:
                raise ValueError("an activity or milestone carries an ID and a name")
        elif row_type in (ScheduleRowType.PROJECT_SUMMARY, ScheduleRowType.WBS_SUMMARY):
            if self.published_activity_id is not None or not self.activity_name:
                raise ValueError("a summary carries a label and no activity ID")
        elif row_type is ScheduleRowType.AMBIGUOUS:
            if self.published_activity_id is not None or self.activity_name is not None:
                raise ValueError("an ambiguous row carries neither ID nor name")
        else:
            raise ValueError("a row carries a closed row type")


@dataclass(frozen=True, slots=True)
class ScheduleParseCounts:
    """Derived counts; `issues`/`warnings` count de-duplicated issues."""

    pages: int
    rows: int
    project_summaries: int
    wbs_summaries: int
    activities: int
    milestones: int
    ambiguous: int
    chart_objects_excluded: int
    watermark_objects_excluded: int
    suppressed_objects: int
    duplicate_objects_collapsed: int
    non_embedded_font_objects: int
    issues: int
    warnings: int

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if not _is_int(value) or value < 0:
                raise ValueError("parse counts are non-negative integers")


@dataclass(frozen=True, slots=True)
class ScheduleParseEngine:
    """PDFium provenance, carried beside (never inside) the canonical result."""

    pypdfium2_version: str
    pdfium_version: str

    def __post_init__(self) -> None:
        if not self.pypdfium2_version or not self.pdfium_version:
            raise ValueError("engine provenance names both versions")


_ROW_TYPE_COUNTS: Final = (
    ("project_summaries", ScheduleRowType.PROJECT_SUMMARY),
    ("wbs_summaries", ScheduleRowType.WBS_SUMMARY),
    ("activities", ScheduleRowType.ACTIVITY),
    ("milestones", ScheduleRowType.MILESTONE),
    ("ambiguous", ScheduleRowType.AMBIGUOUS),
)


@dataclass(frozen=True, slots=True)
class ScheduleParseResult:
    parser_name: str
    parser_version: str
    profile_id: str
    profile_version: int
    document_sha256: str
    document_size_bytes: int
    outcome: SchedulePublicationStatus
    published_schedule_title: str | None
    data_date: date | None
    run_date: date | None
    counts: ScheduleParseCounts
    rows: tuple[ParsedScheduleRow, ...]
    issues: tuple[ScheduleParseIssue, ...]
    engine: ScheduleParseEngine

    def __post_init__(self) -> None:
        if not self.parser_name or not self.parser_version or not self.profile_id:
            raise ValueError("a parse result names its parser and profile")
        if not _positive_int(self.profile_version):
            raise ValueError("a profile version is a positive integer")
        if not _SHA256_HEX.fullmatch(self.document_sha256):
            raise ValueError("a document digest is 64 lowercase hex characters")
        if not _is_int(self.document_size_bytes) or self.document_size_bytes < 0:
            raise ValueError("a document size is a non-negative integer")
        if self.outcome not in TERMINAL_OUTCOMES:
            raise ValueError("a parse outcome is a terminal publication status")
        if self.outcome is SchedulePublicationStatus.FAILED and self.rows:
            raise ValueError("a failed parse carries no rows")
        if tuple(row.row_ordinal for row in self.rows) != tuple(range(1, len(self.rows) + 1)):
            raise ValueError("rows are numbered 1..N in order")
        self._check_counts()

    def _check_counts(self) -> None:
        counts = self.counts
        expected = {
            "rows": len(self.rows),
            "issues": len(self.issues),
            "warnings": sum(
                1 for issue in self.issues if issue.severity is ScheduleIssueSeverity.WARNING
            ),
        }
        for name, row_type in _ROW_TYPE_COUNTS:
            expected[name] = sum(1 for row in self.rows if row.row_type is row_type)
        if any(getattr(counts, name) != value for name, value in expected.items()):
            raise ValueError("parse counts must equal those derived from rows and issues")


# --- normalization -----------------------------------------------------------


def normalize_activity_id(raw: str) -> str:
    """R2 section 16.2: NFC and surrounding whitespace only."""
    return unicodedata.normalize("NFC", raw).strip()


_SPACE_RUN: Final = re.compile(r" +")


def normalize_display_text(raw: str) -> str:
    """NFC, every whitespace run to one ASCII space, then strip."""
    text = unicodedata.normalize("NFC", raw)
    collapsed = "".join(" " if ch.isspace() else ch for ch in text)
    return _SPACE_RUN.sub(" ", collapsed).strip(" ")


# --- grammars ----------------------------------------------------------------

_MONTHS: Final = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_DATE: Final = re.compile(
    r"(?P<dd>0[1-9]|[12][0-9]|3[01])-(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"-(?P<yy>[0-9]{2})(?P<marker>\*)?"
)
_DURATION: Final = re.compile(r"(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,3})?")
_MILLI: Final = Decimal("0.001")


def parse_profile_date(token: str) -> tuple[date, str | None] | None:
    """Contract 4.7: `DD-Mon-YY` with an optional raw `*` marker; 2000..2099."""
    match = _DATE.fullmatch(token)
    if match is None:
        return None
    try:
        value = date(
            2000 + int(match.group("yy")),
            _MONTHS.index(match.group("mon")) + 1,
            int(match.group("dd")),
        )
    except ValueError:
        return None
    return value, match.group("marker")


def parse_profile_duration(token: str) -> Decimal | None:
    """Contract 4.8: an unsigned decimal, at most 9 integer and 3 fraction digits."""
    if _DURATION.fullmatch(token) is None:
        return None
    return Decimal(token).quantize(_MILLI)


# --- outcome -----------------------------------------------------------------

_FAILED_CODES: Final = frozenset(
    {
        ScheduleIssueCode.SOURCE_TOO_LARGE,
        ScheduleIssueCode.UNSUPPORTED_MEDIA_TYPE,
        ScheduleIssueCode.CORRUPT_PDF,
        ScheduleIssueCode.ENCRYPTED_PDF,
        ScheduleIssueCode.IMAGE_ONLY_PDF,
        ScheduleIssueCode.UNSUPPORTED_LAYOUT,
        ScheduleIssueCode.BOUNDS_EXCEEDED,
        ScheduleIssueCode.PARSER_EXCEPTION,
        ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED,
    }
)
_REVIEW_CODES: Final = frozenset(
    {
        ScheduleIssueCode.PAGE_METADATA_MISMATCH,
        ScheduleIssueCode.EXPECTED_DATA_DATE_MISMATCH,
        ScheduleIssueCode.HEADER_SIGNATURE_MISMATCH,
        ScheduleIssueCode.ROW_WRAP_UNSUPPORTED,
        ScheduleIssueCode.ACTIVITY_LIKE_ROW_MISSING_ID,
        ScheduleIssueCode.DUPLICATE_ACTIVITY_ID,
    }
)
_PARTIAL_CODES: Final = frozenset(
    {
        ScheduleIssueCode.INVALID_DATE,
        ScheduleIssueCode.INVALID_DURATION,
        ScheduleIssueCode.OVERLAPPING_CELL_TEXT,
        ScheduleIssueCode.AMBIGUOUS_CELL,
        ScheduleIssueCode.HIERARCHY_AMBIGUOUS,
    }
)


def derive_outcome(
    issues: Iterable[ScheduleParseIssue], rows: Iterable[ParsedScheduleRow]
) -> SchedulePublicationStatus:
    """Contract 5.13, first match wins.

    `SOURCE_VERSION_CHANGED` is never a parser issue; passing one is a
    programming error and raises `ValueError` rather than being given an
    outcome the contract does not assign.
    """
    codes = {issue.code for issue in issues}
    if ScheduleIssueCode.SOURCE_VERSION_CHANGED in codes:
        raise ValueError("source_version_changed is not a parser issue")
    if codes & _FAILED_CODES:
        return SchedulePublicationStatus.FAILED
    if codes & _REVIEW_CODES or any(row.row_type is ScheduleRowType.AMBIGUOUS for row in rows):
        return SchedulePublicationStatus.REVIEW_REQUIRED
    if codes & _PARTIAL_CODES:
        return SchedulePublicationStatus.PARTIAL
    return SchedulePublicationStatus.COMPLETE


def stable_link_candidates(result: ScheduleParseResult) -> tuple[ParsedScheduleRow, ...]:
    """Activity and milestone rows of a `COMPLETE`/`PARTIAL` result, else `()`."""
    if result.outcome not in (
        SchedulePublicationStatus.COMPLETE,
        SchedulePublicationStatus.PARTIAL,
    ):
        return ()
    return tuple(
        row
        for row in result.rows
        if row.row_type in (ScheduleRowType.ACTIVITY, ScheduleRowType.MILESTONE)
    )
