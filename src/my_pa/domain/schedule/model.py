"""CPM Workbench S5a: the parser-facing Full-Schedule vocabulary and records.

Contract: `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
sections 3.3, 4.7, 4.8, 5.13 and 6.1. Pure and standard-library only (plus the
opaque-identifier validator, `docs/architecture/cpm-workbench-foundation-contract.md`
D-18): nothing here reads a PDF, a database, the clock or the environment. The
closed enums carry the exact R2 section 43.2 member names and lower-snake
values so WP-01 extends this module instead of renaming it; declaration order
is the canonical sort order. The S5b-1 foundation symbols (that contract's
sections 5.1-5.3) follow the S5a ones at the end of the module.

Every record checks its own invariants in `__post_init__` and raises
`ValueError` with a fixed message that never carries source text.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier

__all__ = [
    "DURATION_EXPONENT",
    "ISSUE_SEVERITY",
    "MAX_ACTIVITY_NAME_CHARACTERS",
    "MAX_CELL_EVIDENCE_BYTES",
    "MAX_DURATION_EXCLUSIVE",
    "MAX_HIERARCHY_LABEL_CHARACTERS",
    "MAX_HIERARCHY_PATH",
    "MAX_PARSER_IDENTITY_CHARACTERS",
    "MAX_PUBLISHED_ACTIVITY_ID_CHARACTERS",
    "MAX_PUBLISHED_SCHEDULE_TITLE_CHARACTERS",
    "MAX_ROW_WARNING_CODES",
    "MAX_SCHEDULE_BATCH",
    "MAX_SCHEDULE_IDEMPOTENCY_KEY_CHARACTERS",
    "MAX_SCHEDULE_SOURCE_BYTES",
    "MAX_SERIES_NAME_CHARACTERS",
    "ROW_CELL_FIELDS",
    "SCHEDULE_IDEMPOTENCY_KEY_PATTERN",
    "SCHEDULE_MEDIA_TYPE",
    "TERMINAL_OUTCOMES",
    "InvalidScheduleSeriesNameError",
    "ParsedScheduleRow",
    "ScheduleAdmission",
    "ScheduleAdmissionOutcome",
    "ScheduleAdmissionRefusal",
    "ScheduleBaselineKind",
    "ScheduleBox",
    "ScheduleCanonicalizationProgress",
    "ScheduleCellEvidence",
    "ScheduleCellFragment",
    "ScheduleCellState",
    "ScheduleDateCell",
    "ScheduleDurationCell",
    "ScheduleFieldCode",
    "ScheduleFinalization",
    "ScheduleImportIssue",
    "ScheduleImportRequest",
    "ScheduleIssueCode",
    "ScheduleIssueSeverity",
    "ScheduleLease",
    "ScheduleParseCounts",
    "ScheduleParseEngine",
    "ScheduleParseIssue",
    "ScheduleParseResult",
    "ScheduleParserIdentity",
    "ScheduleParserRun",
    "ScheduleParserRunStart",
    "ScheduleParserRunStatus",
    "SchedulePlan",
    "SchedulePublication",
    "SchedulePublicationRole",
    "SchedulePublicationStatus",
    "ScheduleRowBoundsError",
    "ScheduleRowType",
    "ScheduleSeries",
    "ScheduleSeriesName",
    "StableScheduleActivity",
    "StoredScheduleRow",
    "derive_outcome",
    "effective_publication_status",
    "normalize_activity_id",
    "normalize_display_text",
    "normalize_series_name",
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


# --- S5b-1 foundation (R2 WP-01) ---------------------------------------------
#
# Contract: `docs/architecture/cpm-workbench-foundation-contract.md` sections
# 5.1-5.3. These extend the S5a vocabulary above and never restate it.


class SchedulePublicationRole(StrEnum):
    """R2 section 43.2 publication roles, in canonical order."""

    UPDATE = "update"
    BASELINE = "baseline"
    REFERENCE = "reference"


class ScheduleBaselineKind(StrEnum):
    """R2 section 43.2 baseline kinds; set exactly on a `BASELINE` publication."""

    WORKING = "working"
    CONTRACT = "contract"


class ScheduleParserRunStatus(StrEnum):
    """One parser attempt: `RUNNING` moves once to `PARSED` or `FAILED`."""

    RUNNING = "running"
    PARSED = "parsed"
    FAILED = "failed"


class ScheduleAdmissionOutcome(StrEnum):
    CREATED = "created"
    REPLAYED = "replayed"


class ScheduleAdmissionRefusal(StrEnum):
    """Every typed rejection of an admission (contract section 5.5)."""

    PROJECT_NOT_FOUND = "project_not_found"
    SERIES_NOT_FOUND = "series_not_found"
    ENROLLMENT_NOT_FOUND = "enrollment_not_found"
    SOURCE_OBJECT_NOT_ENROLLED = "source_object_not_enrolled"
    SOURCE_VERSION_NOT_FOUND = "source_version_not_found"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    MEDIA_TYPE_NOT_ENROLLED = "media_type_not_enrolled"
    SOURCE_TOO_LARGE = "source_too_large"
    SUPERSEDED_PUBLICATION_NOT_FOUND = "superseded_publication_not_found"
    SUPERSEDED_PUBLICATION_NOT_TERMINAL = "superseded_publication_not_terminal"
    SUPERSEDED_PUBLICATION_SAME_SOURCE_VERSION = "superseded_publication_same_source_version"
    SUPERSEDED_PUBLICATION_HAS_SUCCESSOR = "superseded_publication_has_successor"
    IDEMPOTENCY_KEY_CONFLICT = "idempotency_key_conflict"
    SOURCE_VERSION_CONFLICT = "source_version_conflict"


MAX_SERIES_NAME_CHARACTERS: Final = 200
MAX_PUBLISHED_ACTIVITY_ID_CHARACTERS: Final = 256
MAX_ACTIVITY_NAME_CHARACTERS: Final = 2000
MAX_HIERARCHY_LABEL_CHARACTERS: Final = 2000
#: The bound on a row's canonical `cell_evidence_bytes` (R2 section 18.6).
MAX_CELL_EVIDENCE_BYTES: Final = 16384
MAX_SCHEDULE_SOURCE_BYTES: Final = 16777216
MAX_SCHEDULE_BATCH: Final = 1000
MAX_SCHEDULE_IDEMPOTENCY_KEY_CHARACTERS: Final = 128
#: The project-history / Constraint Management idempotency-key precedent.
SCHEDULE_IDEMPOTENCY_KEY_PATTERN: Final = re.compile(r"\A[A-Za-z0-9_-]{8,128}\Z")
SCHEDULE_MEDIA_TYPE: Final = "application/pdf"
MAX_PUBLISHED_SCHEDULE_TITLE_CHARACTERS: Final = 300
MAX_PARSER_IDENTITY_CHARACTERS: Final = 64

#: `unicodedata.category` values a Series name may not contain (R2 section 10.1).
_REJECTED_NAME_CATEGORIES: Final = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})


class InvalidScheduleSeriesNameError(ValueError):
    """A Series name that cannot be normalized; the message carries no text."""


class ScheduleRowBoundsError(ValueError):
    """A parsed row exceeds a persistence bound; the message carries no text."""


def _identifier(value: object, kind: IdKind) -> None:
    validate_identifier(value, kind)  # type: ignore[arg-type]


def _optional_identifier(value: object, kind: IdKind) -> None:
    if value is not None:
        _identifier(value, kind)


def _non_negative_int(value: object) -> bool:
    return _is_int(value) and value >= 0  # type: ignore[operator]


def _is_idempotency_key(value: object) -> bool:
    return isinstance(value, str) and SCHEDULE_IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is not None


def _is_optional_date(value: object) -> bool:
    return value is None or (isinstance(value, date) and not isinstance(value, datetime))


def _series_key(name: str) -> str:
    return unicodedata.normalize("NFC", name.casefold())


def _series_name_is_normal(name: object) -> bool:
    return (
        isinstance(name, str)
        and 1 <= len(name) <= MAX_SERIES_NAME_CHARACTERS
        and normalize_display_text(name) == name
        and not any(unicodedata.category(ch) in _REJECTED_NAME_CATEGORIES for ch in name)
    )


@dataclass(frozen=True, slots=True)
class ScheduleSeriesName:
    """A normalized Series name and its comparison key; see `normalize_series_name`."""

    name: str
    key: str

    def __post_init__(self) -> None:
        if not _series_name_is_normal(self.name):
            raise InvalidScheduleSeriesNameError("a schedule series name is not normalized")
        if self.key != _series_key(self.name):
            raise InvalidScheduleSeriesNameError("a schedule series key is NFC(casefold(name))")


def normalize_series_name(raw: str) -> ScheduleSeriesName:
    """R2 section 10.1: NFC, whitespace runs to one space, strip, then refuse.

    Refused: any character of category `Cc`, `Cf`, `Cs`, `Co` or `Cn`
    remaining after whitespace collapse, or a length outside 1..200.
    """
    if not isinstance(raw, str):
        raise InvalidScheduleSeriesNameError("a schedule series name is text")
    name = normalize_display_text(raw)
    if any(unicodedata.category(ch) in _REJECTED_NAME_CATEGORIES for ch in name):
        raise InvalidScheduleSeriesNameError("a schedule series name has a refused character")
    if not 1 <= len(name) <= MAX_SERIES_NAME_CHARACTERS:
        raise InvalidScheduleSeriesNameError("a schedule series name is 1 to 200 characters")
    return ScheduleSeriesName(name=name, key=_series_key(name))


@dataclass(frozen=True, slots=True)
class ScheduleSeries:
    series_id: str
    principal_id: str
    project_id: str
    name: str
    name_key: str
    created_at: datetime

    def __post_init__(self) -> None:
        _identifier(self.series_id, IdKind.SCHEDULE_SERIES)
        _identifier(self.principal_id, IdKind.PRINCIPAL)
        _identifier(self.project_id, IdKind.PROJECT)
        ScheduleSeriesName(name=self.name, key=self.name_key)


@dataclass(frozen=True, slots=True)
class ScheduleImportRequest:
    """One admission request; exactly one of `series_id` / `series_name` is set."""

    project_id: str
    series_id: str | None
    series_name: ScheduleSeriesName | None
    enrollment_id: str
    source_object_id: str
    source_version_id: str
    publication_role: SchedulePublicationRole
    baseline_kind: ScheduleBaselineKind | None
    expected_data_date: date | None
    supersedes_publication_id: str | None
    idempotency_key: str

    def __post_init__(self) -> None:
        _identifier(self.project_id, IdKind.PROJECT)
        if (self.series_id is None) == (self.series_name is None):
            raise ValueError("an import request names a series by id or by name, not both")
        _optional_identifier(self.series_id, IdKind.SCHEDULE_SERIES)
        if self.series_name is not None and not isinstance(self.series_name, ScheduleSeriesName):
            raise ValueError("an import request series name is normalized")
        _identifier(self.enrollment_id, IdKind.ENROLLMENT)
        _identifier(self.source_object_id, IdKind.SOURCE_OBJECT)
        _identifier(self.source_version_id, IdKind.VERSION)
        if not isinstance(self.publication_role, SchedulePublicationRole):
            raise ValueError("an import request carries a closed publication role")
        if self.baseline_kind is not None and not isinstance(
            self.baseline_kind, ScheduleBaselineKind
        ):
            raise ValueError("an import request carries a closed baseline kind")
        if (self.publication_role is SchedulePublicationRole.BASELINE) != (
            self.baseline_kind is not None
        ):
            raise ValueError("a baseline kind is set exactly on a baseline publication")
        if not _is_optional_date(self.expected_data_date):
            raise ValueError("an expected data date is a date")
        _optional_identifier(self.supersedes_publication_id, IdKind.SCHEDULE_PUBLICATION)
        if not _is_idempotency_key(self.idempotency_key):
            raise ValueError("an idempotency key is 8 to 128 of [A-Za-z0-9_-]")


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_HEX.fullmatch(value) is not None


_PUBLICATION_COUNTS: Final = (
    "page_count",
    "row_count",
    "activity_count",
    "ambiguous_row_count",
    "issue_count",
)
_ACCEPTED_TERMINALS: Final = frozenset(
    {
        SchedulePublicationStatus.COMPLETE,
        SchedulePublicationStatus.PARTIAL,
        SchedulePublicationStatus.REVIEW_REQUIRED,
    }
)


@dataclass(frozen=True, slots=True)
class SchedulePublication:
    """One admitted publication: every `schedule_publications` column, typed."""

    publication_id: str
    principal_id: str
    project_id: str
    series_id: str
    enrollment_id: str
    source_object_id: str
    source_version_id: str
    idempotency_key: str
    request_digest: str
    publication_role: SchedulePublicationRole
    baseline_kind: ScheduleBaselineKind | None
    expected_data_date: date | None
    supersedes_publication_id: str | None
    status: SchedulePublicationStatus
    document_sha256: str | None
    document_size_bytes: int | None
    published_schedule_title: str | None
    data_date: date | None
    run_date: date | None
    accepted_parser_run_id: str | None
    page_count: int | None
    row_count: int | None
    activity_count: int | None
    ambiguous_row_count: int | None
    issue_count: int | None
    admitted_at: datetime
    processing_started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime

    def __post_init__(self) -> None:
        _identifier(self.publication_id, IdKind.SCHEDULE_PUBLICATION)
        _identifier(self.principal_id, IdKind.PRINCIPAL)
        _identifier(self.project_id, IdKind.PROJECT)
        _identifier(self.series_id, IdKind.SCHEDULE_SERIES)
        _identifier(self.enrollment_id, IdKind.ENROLLMENT)
        _identifier(self.source_object_id, IdKind.SOURCE_OBJECT)
        _identifier(self.source_version_id, IdKind.VERSION)
        _optional_identifier(self.supersedes_publication_id, IdKind.SCHEDULE_PUBLICATION)
        _optional_identifier(self.accepted_parser_run_id, IdKind.SCHEDULE_PARSER_RUN)
        if not _is_idempotency_key(self.idempotency_key):
            raise ValueError("an idempotency key is 8 to 128 of [A-Za-z0-9_-]")
        if not _is_sha256(self.request_digest):
            raise ValueError("a request digest is 64 lowercase hex characters")
        if (self.publication_role is SchedulePublicationRole.BASELINE) != (
            self.baseline_kind is not None
        ):
            raise ValueError("a baseline kind is set exactly on a baseline publication")
        if self.supersedes_publication_id == self.publication_id:
            raise ValueError("a publication does not supersede itself")
        if (self.document_sha256 is None) != (self.document_size_bytes is None):
            raise ValueError("a pinned document has both its digest and its size")
        if self.document_sha256 is not None and not _is_sha256(self.document_sha256):
            raise ValueError("a document digest is 64 lowercase hex characters")
        if self.document_size_bytes is not None and not (
            _non_negative_int(self.document_size_bytes)
            and self.document_size_bytes <= MAX_SCHEDULE_SOURCE_BYTES
        ):
            raise ValueError("a document size is 0 to 16777216 bytes")
        title = self.published_schedule_title
        if title is not None and not 1 <= len(title) <= MAX_PUBLISHED_SCHEDULE_TITLE_CHARACTERS:
            raise ValueError("a published schedule title is 1 to 300 characters")
        if any(
            getattr(self, name) is not None and not _non_negative_int(getattr(self, name))
            for name in _PUBLICATION_COUNTS
        ):
            raise ValueError("publication counts are non-negative integers")
        self._check_progress()

    def _check_progress(self) -> None:
        """The `a_schedule_publication_records_its_progress` rule, in Python."""
        status = self.status
        counts = [getattr(self, name) for name in _PUBLICATION_COUNTS]
        described = (self.published_schedule_title, self.data_date, self.run_date)
        if status is SchedulePublicationStatus.QUEUED:
            if any(
                value is not None
                for value in (
                    self.processing_started_at,
                    self.completed_at,
                    self.accepted_parser_run_id,
                    self.document_sha256,
                    *counts,
                    *described,
                )
            ):
                raise ValueError("a queued publication records no progress")
        elif status is SchedulePublicationStatus.PROCESSING:
            if self.processing_started_at is None or any(
                value is not None
                for value in (self.completed_at, self.accepted_parser_run_id, *counts, *described)
            ):
                raise ValueError("a processing publication records only its start and document")
        elif status in _ACCEPTED_TERMINALS:
            if any(
                value is None
                for value in (
                    self.processing_started_at,
                    self.completed_at,
                    self.accepted_parser_run_id,
                    self.document_sha256,
                    *counts,
                )
            ):
                raise ValueError("an accepted publication records its run, document and counts")
        elif status is SchedulePublicationStatus.FAILED:
            if (
                self.processing_started_at is None
                or self.completed_at is None
                or self.issue_count is None
                or self.issue_count < 1
            ):
                raise ValueError("a failed publication records its completion and issues")
            if any(
                value is not None
                for value in (self.accepted_parser_run_id, *counts[:4], *described)
            ):
                raise ValueError("a failed publication accepts no run")
        else:
            raise ValueError("a publication carries a closed status")


def _is_nonempty_text(value: object) -> bool:
    return isinstance(value, str) and value != ""


def _bounded_text(value: object, limit: int) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= limit


@dataclass(frozen=True, slots=True)
class ScheduleParserIdentity:
    """The parser, profile and engine one run is keyed by."""

    parser_name: str
    parser_version: str
    profile_id: str
    profile_version: int
    pypdfium2_version: str
    pdfium_version: str

    def __post_init__(self) -> None:
        if not all(
            _bounded_text(value, MAX_PARSER_IDENTITY_CHARACTERS)
            for value in (
                self.parser_name,
                self.parser_version,
                self.profile_id,
                self.pypdfium2_version,
                self.pdfium_version,
            )
        ):
            raise ValueError("parser identity fields are 1 to 64 characters")
        if not _positive_int(self.profile_version):
            raise ValueError("a profile version is a positive integer")

    @classmethod
    def from_parse_result(cls, result: ScheduleParseResult) -> ScheduleParserIdentity:
        return cls(
            parser_name=result.parser_name,
            parser_version=result.parser_version,
            profile_id=result.profile_id,
            profile_version=result.profile_version,
            pypdfium2_version=result.engine.pypdfium2_version,
            pdfium_version=result.engine.pdfium_version,
        )


_RUN_COUNTS: Final = ("page_count", "row_count", "issue_count", "warning_count")


@dataclass(frozen=True, slots=True)
class ScheduleParserRun:
    """One parser attempt: every `schedule_parser_runs` column, typed."""

    parser_run_id: str
    principal_id: str
    project_id: str
    series_id: str
    publication_id: str
    operation_id: str
    attempt_number: int
    parser_name: str
    parser_version: str
    profile_id: str
    profile_version: int
    pypdfium2_version: str
    pdfium_version: str
    document_sha256: str
    status: ScheduleParserRunStatus
    page_count: int | None
    row_count: int | None
    issue_count: int | None
    warning_count: int | None
    parse_result_sha256: str | None
    failure_code: ScheduleIssueCode | None
    started_at: datetime
    completed_at: datetime | None

    def __post_init__(self) -> None:
        _identifier(self.parser_run_id, IdKind.SCHEDULE_PARSER_RUN)
        _identifier(self.principal_id, IdKind.PRINCIPAL)
        _identifier(self.project_id, IdKind.PROJECT)
        _identifier(self.series_id, IdKind.SCHEDULE_SERIES)
        _identifier(self.publication_id, IdKind.SCHEDULE_PUBLICATION)
        _identifier(self.operation_id, IdKind.OPERATION)
        if not _positive_int(self.attempt_number):
            raise ValueError("an attempt number is a positive integer")
        _ = self.identity
        if not _is_sha256(self.document_sha256):
            raise ValueError("a document digest is 64 lowercase hex characters")
        if self.parse_result_sha256 is not None and not _is_sha256(self.parse_result_sha256):
            raise ValueError("a parse result digest is 64 lowercase hex characters")
        if self.failure_code is not None and not isinstance(self.failure_code, ScheduleIssueCode):
            raise ValueError("a failure code is a closed issue code")
        counts = [getattr(self, name) for name in _RUN_COUNTS]
        if any(value is not None and not _non_negative_int(value) for value in counts):
            raise ValueError("parser run counts are non-negative integers")
        if None not in counts and self.warning_count > self.issue_count:  # type: ignore[operator]
            raise ValueError("a run has no more warnings than issues")
        self._check_outcome(counts)

    def _check_outcome(self, counts: list[int | None]) -> None:
        status = self.status
        if status is ScheduleParserRunStatus.RUNNING:
            if self.completed_at is not None or self.parse_result_sha256 is not None:
                raise ValueError("a running parser run records no outcome")
            if self.failure_code is not None or any(value is not None for value in counts):
                raise ValueError("a running parser run records no outcome")
        elif status is ScheduleParserRunStatus.PARSED:
            if self.completed_at is None or self.parse_result_sha256 is None or None in counts:
                raise ValueError("a parsed run records its completion, counts and digest")
            if self.failure_code is not None:
                raise ValueError("a parsed run carries no failure code")
        elif status is ScheduleParserRunStatus.FAILED:
            if self.completed_at is None:
                raise ValueError("a failed parser run records its completion")
            if self.parse_result_sha256 is not None or any(value is not None for value in counts):
                raise ValueError("a failed parser run records no counts or digest")
        else:
            raise ValueError("a parser run carries a closed status")

    @property
    def identity(self) -> ScheduleParserIdentity:
        return ScheduleParserIdentity(
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            profile_id=self.profile_id,
            profile_version=self.profile_version,
            pypdfium2_version=self.pypdfium2_version,
            pdfium_version=self.pdfium_version,
        )


def _published_id_is_exact(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= MAX_PUBLISHED_ACTIVITY_ID_CHARACTERS
        and value == value.strip()
    )


@dataclass(frozen=True, slots=True)
class StableScheduleActivity:
    """One Stable Schedule Activity: an exact published ID within one Series."""

    schedule_activity_id: str
    principal_id: str
    project_id: str
    series_id: str
    published_activity_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        _identifier(self.schedule_activity_id, IdKind.SCHEDULE_ACTIVITY)
        _identifier(self.principal_id, IdKind.PRINCIPAL)
        _identifier(self.project_id, IdKind.PROJECT)
        _identifier(self.series_id, IdKind.SCHEDULE_SERIES)
        if not _published_id_is_exact(self.published_activity_id):
            raise ValueError("a published activity id is 1 to 256 characters, trimmed")


_LINKABLE_ROW_TYPES: Final = frozenset({ScheduleRowType.ACTIVITY, ScheduleRowType.MILESTONE})


@dataclass(frozen=True, slots=True)
class StoredScheduleRow:
    """One stored row: its identifiers, its stable link and the S5a record."""

    row_id: str
    parser_run_id: str
    publication_id: str
    schedule_activity_id: str | None
    parent_row_id: str | None
    row: ParsedScheduleRow

    def __post_init__(self) -> None:
        _identifier(self.row_id, IdKind.SCHEDULE_ROW)
        _identifier(self.parser_run_id, IdKind.SCHEDULE_PARSER_RUN)
        _identifier(self.publication_id, IdKind.SCHEDULE_PUBLICATION)
        _optional_identifier(self.schedule_activity_id, IdKind.SCHEDULE_ACTIVITY)
        _optional_identifier(self.parent_row_id, IdKind.SCHEDULE_ROW)
        if not isinstance(self.row, ParsedScheduleRow):
            raise ValueError("a stored row carries a parsed row")
        if self.schedule_activity_id is not None and self.row.row_type not in _LINKABLE_ROW_TYPES:
            raise ValueError("only an activity or milestone row links a stable activity")
        if (self.parent_row_id is None) != (self.row.parent_row_ordinal is None):
            raise ValueError("a stored row names its parent exactly when the parse did")


@dataclass(frozen=True, slots=True)
class ScheduleImportIssue:
    """One stored import issue; an issue naming a row names its run."""

    issue_id: str
    publication_id: str
    parser_run_id: str | None
    issue: ScheduleParseIssue

    def __post_init__(self) -> None:
        _identifier(self.issue_id, IdKind.SCHEDULE_IMPORT_ISSUE)
        _identifier(self.publication_id, IdKind.SCHEDULE_PUBLICATION)
        _optional_identifier(self.parser_run_id, IdKind.SCHEDULE_PARSER_RUN)
        if not isinstance(self.issue, ScheduleParseIssue):
            raise ValueError("a stored issue carries a parse issue")
        if self.issue.row_ordinal is not None and self.parser_run_id is None:
            raise ValueError("an issue naming a row names its parser run")


@dataclass(frozen=True, slots=True)
class ScheduleLease:
    """The caller's hold on one `schedule_jobs` row."""

    operation_id: str
    owner: str
    attempt: int

    def __post_init__(self) -> None:
        _identifier(self.operation_id, IdKind.OPERATION)
        if not _is_nonempty_text(self.owner):
            raise ValueError("a lease names its owner")
        if not _positive_int(self.attempt):
            raise ValueError("a lease attempt is a positive integer")


@dataclass(frozen=True, slots=True)
class ScheduleAdmission:
    series: ScheduleSeries
    publication: SchedulePublication
    operation_id: str
    outcome: ScheduleAdmissionOutcome
    series_created: bool

    def __post_init__(self) -> None:
        _identifier(self.operation_id, IdKind.OPERATION)
        if (self.publication.series_id, self.publication.principal_id) != (
            self.series.series_id,
            self.series.principal_id,
        ):
            raise ValueError("an admission's publication belongs to its series")
        if not isinstance(self.outcome, ScheduleAdmissionOutcome):
            raise ValueError("an admission carries a closed outcome")
        if self.series_created and self.outcome is not ScheduleAdmissionOutcome.CREATED:
            raise ValueError("a replayed admission creates no series")


@dataclass(frozen=True, slots=True)
class SchedulePlan:
    """What one attempt may do: nothing when terminal, else fetch at most this."""

    publication: SchedulePublication
    attempt: int
    terminal: bool
    max_fetch_bytes: int | None

    def __post_init__(self) -> None:
        if not _positive_int(self.attempt):
            raise ValueError("a plan attempt is a positive integer")
        if self.terminal != (self.publication.status in TERMINAL_OUTCOMES):
            raise ValueError("a plan is terminal exactly when its publication is")
        if self.terminal:
            if self.max_fetch_bytes is not None:
                raise ValueError("a terminal plan fetches nothing")
        elif not (
            _non_negative_int(self.max_fetch_bytes)
            and self.max_fetch_bytes <= MAX_SCHEDULE_SOURCE_BYTES  # type: ignore[operator]
        ):
            raise ValueError("a plan fetches 0 to 16777216 bytes")


@dataclass(frozen=True, slots=True)
class ScheduleParserRunStart:
    run: ScheduleParserRun
    reused: bool

    def __post_init__(self) -> None:
        if self.reused and self.run.status is ScheduleParserRunStatus.FAILED:
            raise ValueError("a failed run is never reused")


@dataclass(frozen=True, slots=True)
class ScheduleCanonicalizationProgress:
    linked: int
    created: int
    remaining: int

    def __post_init__(self) -> None:
        if not all(_non_negative_int(v) for v in (self.linked, self.created, self.remaining)):
            raise ValueError("canonicalization progress counts are non-negative integers")


@dataclass(frozen=True, slots=True)
class ScheduleFinalization:
    """What the caller supplies at finalization; the status is derived, never given."""

    accepted_parser_run_id: str
    published_schedule_title: str | None
    data_date: date | None
    run_date: date | None

    def __post_init__(self) -> None:
        _identifier(self.accepted_parser_run_id, IdKind.SCHEDULE_PARSER_RUN)
        title = self.published_schedule_title
        if title is not None and not _bounded_text(title, MAX_PUBLISHED_SCHEDULE_TITLE_CHARACTERS):
            raise ValueError("a published schedule title is 1 to 300 characters")


def effective_publication_status(
    status: SchedulePublicationStatus, *, job_failed: bool
) -> SchedulePublicationStatus:
    """R2 section 10.6: an exhausted job reads `FAILED`; nothing is written."""
    if job_failed and status in (
        SchedulePublicationStatus.QUEUED,
        SchedulePublicationStatus.PROCESSING,
    ):
        return SchedulePublicationStatus.FAILED
    return status
