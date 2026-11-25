"""The project-report reads: catalog, query, record history, compare, coverage (WP4P-S3).

The design of record is the WP4P-W1 report, sections 2.2-2.8 and 2.12, with the
Manager's rulings D1-D10 and A1-A5. This module is the service half; its MCP
wiring (capabilities, policy, the read switch, SafeDetail rendering, ChatLLM)
is WP4P-S4. Every method takes the authenticated Principal's identifier
(server-derived) and, for a cursor, the caller's grant set (`None` for a
local caller).

* **Always the current derivation.** Every version is read through
  `UnitOfWork.project_report_reads`, which reaches derivations only through
  `project_report_current_derivations`; this module never names the
  derivations table (`tests/architecture/test_project_report_reads_use_current_derivations.py`).
  "Latest" is computed here with the one D10 order (`latest_version`).
* **Every answer** carries its `versions[]` block (one entry per version used,
  each with its own filter semantics), the once-per-answer `qualifiers[]`
  (`filter_semantics_unknown` when any version used is `unknown`) and a
  `cursor_state`.
* **Errors.** A malformed or out-of-bounds field is `invalid_request` with one
  SafeDetail token and never its value. An unknown and another Principal's
  identifier are both `not_found`, indistinguishably: every read is scoped to
  the Principal. A cursor of another request or Principal is `conflict` /
  `cursor`; a cursor whose resolved version set changed (a new export, a
  re-derivation, a binding correction) answers
  `scope_changed_restart_required` and nothing else (ruling D4 (b)), checked
  after the versions are resolved and before any line is read.
* **Measures** (section 2.6) are computed per series over the detail lines
  the query's row filters select across the whole version (never the page,
  so paging never changes them), or over every detail line when no row filter
  applies; each carries `measure_scope` (`"filtered"` / `"version"`, ruling
  B1 amended). They go through `plan_measure`, whose reconciliation inputs
  always judge the whole version: amounts are withheld by a reconciliation
  mismatch derivation-wide under either scope (D9) and by a cross-check
  mismatch on the two columns it concerns; a cross-check counts only when
  both of its sides are current (ruling A4, held by the repository); record
  and row counts are never withheld by a mismatch but carry the
  `reconciliation_mismatch` qualifier (ruling A2). A column's population and
  the `unknown` status block are judged over the whole version too. No zero
  is substituted. Stated totals are evidence and are answered only in
  `source_totals`, never in `measures` (PULSE-AC-08); their outcome is
  against the whole version's lines (`reconciliation_scope: "version"`), so a
  filtered answer never presents one as matching its sum.
* **Money is `Decimal` only**, answered as plain fixed-point strings
  (`format_amount`); no float exists anywhere in the path.
* **Closure is never inferred**: a record absent from a later version is
  `not_observed` / `not_observed_in_latest`, with its status as last observed.
  Nor is absence inferred from an unreadable version: a quarantined side makes
  `compare` answer `comparable: false`, and a quarantined latest version makes
  `record_history` answer `latest_unreadable` with its reasons (ruling R1-01).

The WP5 facade (`project_summary`, `match_rfis`, `availability`) takes plain
types and is composed by the meeting context; it is not an MCP tool.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Final

from my_pa.application.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.application.project_reports_coverage import (
    SeriesCoverage,
    SourceCoverage,
    project_reports_coverage,
)
from my_pa.contracts.ports import (
    IngestConsumer,
    ProjectReportBindingRecord,
    ProjectReportIdentifierTerm,
    ProjectReportLineQuery,
    ProjectReportLineValueRecord,
    ProjectReportReadLine,
    ProjectReportReadsRepository,
    ProjectReportRfiTerm,
    ProjectReportStatedTotalRecord,
    ProjectReportVersionRecord,
    UnitOfWork,
)
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.common.time import format_rfc3339, utc_now
from my_pa.domain.project_reports.catalogue import (
    IDENTIFIER_KINDS,
    MEASURES,
    STATUS_CLASSES,
    VIEW_FIELDS,
    MeasureBasis,
    MeasureSpec,
    date_fields,
    field_entry,
    searchable_text_fields,
)
from my_pa.domain.project_reports.cursor import (
    MAX_CURSOR_CHARACTERS,
    ComparePosition,
    CursorMalformedError,
    ProjectReportsCursor,
    QueryPosition,
    ResolvedVersion,
    compare_position,
    cursor_binding,
    decode_cursor,
    encode_cursor,
    grant_digest,
    query_position,
    scope_digest,
)
from my_pa.domain.project_reports.identity import (
    AMBIGUOUS_PREFIX,
    RfiNumber,
    match_rfi,
    normalize_whitespace,
    split_rfi_number,
)
from my_pa.domain.project_reports.measures import MeasureValue, derivation_blockers
from my_pa.domain.project_reports.model import (
    FAMILY_OF_VIEW,
    BindingState,
    DerivationState,
    FamilyView,
    FilterSemantics,
    IdentityState,
    NotReportableReason,
    RecordFamily,
    ReportQualifier,
    StatusClass,
    ValueKind,
    VersionPresence,
)
from my_pa.domain.project_reports.money import NumericCell
from my_pa.domain.project_reports.reads import (
    MeasureAnswer,
    MeasureInputs,
    MeasureScope,
    PlannedLine,
    RecordState,
    UsedVersion,
    answer_qualifiers,
    compare_by_content,
    compare_records,
    content_signature,
    format_amount,
    is_series_id,
    measure_scope,
    plan_measure,
    version_filter_semantics,
)
from my_pa.domain.project_reports.versions import (
    RecordObservation,
    VersionRef,
    compare_versions,
    latest_version,
    version_order_key,
)

__all__ = [
    "AVAILABILITY_REASONS",
    "DEFAULT_COMPARE_LIMIT",
    "DEFAULT_QUERY_LIMIT",
    "MAX_ANSWER_TEXT_CHARACTERS",
    "MAX_COMPARE_LIMIT",
    "MAX_CURSOR_CHARACTERS",
    "MAX_FIELD_TEXT_CHARACTERS",
    "MAX_FILTER_ITEMS",
    "MAX_OBSERVATIONS",
    "MAX_PROJECT_IDS",
    "MAX_QUERY_LIMIT",
    "MAX_RECORD_IDS",
    "MAX_RFI_NUMBERS",
    "MAX_SERIES",
    "MAX_SOURCE_TOTALS",
    "MAX_TEXT_CHARACTERS",
    "MAX_VERSIONS",
    "PROJECT_REPORTS_CATALOG",
    "PROJECT_REPORTS_COMPARE",
    "PROJECT_REPORTS_COVERAGE",
    "PROJECT_REPORTS_QUERY",
    "PROJECT_REPORTS_RECORD_HISTORY",
    "SCOPE_CHANGED_RESTART_REQUIRED",
    "Availability",
    "CatalogAnswer",
    "CatalogRequest",
    "CompareAnswer",
    "CompareRequest",
    "CoverageAnswer",
    "CoverageRequest",
    "IdentifierItem",
    "ProjectReportReads",
    "ProjectSummary",
    "QueryAnswer",
    "QueryRequest",
    "RecordHistoryAnswer",
    "RecordHistoryRequest",
    "RfiNumberMatch",
    "availability_payload",
    "catalog_payload",
    "compare_payload",
    "coverage_payload",
    "project_summary_payload",
    "query_payload",
    "record_history_payload",
]

PROJECT_REPORTS_CATALOG: Final = "project_reports.catalog"
PROJECT_REPORTS_QUERY: Final = "project_reports.query"
PROJECT_REPORTS_RECORD_HISTORY: Final = "project_reports.record_history"
PROJECT_REPORTS_COMPARE: Final = "project_reports.compare"
PROJECT_REPORTS_COVERAGE: Final = "project_reports.coverage"
SCOPE_CHANGED_RESTART_REQUIRED: Final = "scope_changed_restart_required"

# --- bounds (design section 2.4) -----------------------------------------------------------
MAX_PROJECT_IDS: Final = 50
MAX_SERIES: Final = 200
#: At most this many items in one list filter (statuses, identifiers, group keys, ...).
MAX_FILTER_ITEMS: Final = 20
MAX_TEXT_CHARACTERS: Final = 200
#: An identifier, a status or a group key is at most this long.
MAX_TERM_CHARACTERS: Final = 512
DEFAULT_QUERY_LIMIT: Final = 25
MAX_QUERY_LIMIT: Final = 100
MAX_FIELD_TEXT_CHARACTERS: Final = 2_000
MAX_ANSWER_TEXT_CHARACTERS: Final = 200_000
MAX_RECORD_IDS: Final = 25
MAX_OBSERVATIONS: Final = 200
DEFAULT_COMPARE_LIMIT: Final = 500
MAX_COMPARE_LIMIT: Final = 500
MAX_SOURCE_TOTALS: Final = 200
#: A request resolving more versions than this is refused (design section 2.5).
MAX_VERSIONS: Final = 2_000
MAX_RFI_NUMBERS: Final = 10
_LINE_BATCH: Final = 1_000

#: Why the WP5 facade finds a Project's reports unavailable (closed).
AVAILABILITY_REASONS: Final = ("reads_disabled", "unbound", "never_ingested", "all_quarantined")
#: The families `project_summary` counts (design section 2.12).
_SUMMARY_FAMILIES: Final = (
    RecordFamily.OBSERVATIONS,
    RecordFamily.COORDINATION_ISSUES,
    RecordFamily.RFIS,
)
_COMPARE_SECTIONS: Final = ("added", "not_observed", "changed", "lines")
_TEXT_KINDS: Final = frozenset({ValueKind.TEXT, ValueKind.IDENTIFIER})


# --- requests -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CatalogRequest:
    project_ids: Sequence[str] | None = None
    record_family: str | None = None


@dataclass(frozen=True, slots=True)
class IdentifierItem:
    kind: str
    value: str


@dataclass(frozen=True, slots=True)
class QueryRequest:
    project_id: str
    record_family: str
    series_id: str | None = None
    version: str | None = None
    status_classes: Sequence[str] = ()
    statuses: Sequence[str] = ()
    date_field: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    identifiers: Sequence[IdentifierItem] = ()
    group_keys: Sequence[str] = ()
    text: str | None = None
    measures: Sequence[str] = ()
    include_rows: bool = True
    limit: int = DEFAULT_QUERY_LIMIT
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class RecordHistoryRequest:
    record_ids: Sequence[str] = ()
    project_id: str | None = None
    record_family: str | None = None
    identity_key: str | None = None


@dataclass(frozen=True, slots=True)
class CompareRequest:
    series_id: str
    from_version: str | None = None
    to_version: str | None = None
    limit: int = DEFAULT_COMPARE_LIMIT
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class CoverageRequest:
    project_ids: Sequence[str] | None = None
    record_family: str | None = None


# --- answers --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VersionBlock:
    """One version an answer used (design section 2.2)."""

    record: ProjectReportVersionRecord
    filter_semantics: FilterSemantics
    is_latest: bool


@dataclass(frozen=True, slots=True)
class SeriesEntry:
    series_id: str
    record_family: RecordFamily | None
    family_view: FamilyView | None
    slug_label: str | None
    signature_prefix: str
    versions: int
    quarantined_versions: int
    latest: VersionBlock


@dataclass(frozen=True, slots=True)
class SourceEntry:
    ingest_source_id: str
    binding_state: BindingState
    enabled: bool
    project_number: str | None
    currency: str | None


@dataclass(frozen=True, slots=True)
class CatalogProject:
    project_id: str
    project_number: str | None
    currency: str | None
    sources: tuple[SourceEntry, ...]
    series: tuple[SeriesEntry, ...]


@dataclass(frozen=True, slots=True)
class CatalogAnswer:
    projects: tuple[CatalogProject, ...]
    series_total: int
    truncated: bool
    qualifiers: tuple[ReportQualifier, ...]


@dataclass(frozen=True, slots=True)
class MeasureEntry:
    """One measure over one version of one series (or `no_snapshot` without one)."""

    answer: MeasureAnswer
    series_id: str | None
    version: str | None
    currency: str | None
    #: The lines it was computed over (ruling B1, amended).
    scope: MeasureScope = MeasureScope.VERSION


@dataclass(frozen=True, slots=True)
class RowEntry:
    line: ProjectReportReadLine
    series_id: str
    currency: str
    truncated_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RfiNumberMatch:
    """One RFI number matched exactly (`exact`, `ambiguous_prefix` or `none`)."""

    prefix: str | None
    suffix: int
    state: str
    #: `(prefix, suffix, record_id)` of each distinct candidate record.
    candidates: tuple[tuple[str | None, int, str | None], ...]


@dataclass(frozen=True, slots=True)
class QueryAnswer:
    rows: tuple[RowEntry, ...]
    rfi_match: tuple[RfiNumberMatch, ...]
    measures: tuple[MeasureEntry, ...]
    source_totals: tuple[tuple[str, ProjectReportStatedTotalRecord], ...] | None
    source_totals_truncated: bool
    versions: tuple[VersionBlock, ...]
    qualifiers: tuple[ReportQualifier, ...]
    next_cursor: str | None
    cursor_state: str | None


@dataclass(frozen=True, slots=True)
class Observation:
    line: ProjectReportReadLine
    series_id: str
    changed_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SeriesPresence:
    series_id: str
    presence: VersionPresence
    last_observed_version: str
    last_status: StatusClass | None
    #: Why the latest version is unreadable (`latest_unreadable` only, ruling R1-01).
    reasons: frozenset[NotReportableReason] = frozenset()


@dataclass(frozen=True, slots=True)
class RecordHistory:
    record_id: str
    identity_key: str
    identity_version: str
    record_family: RecordFamily
    observations: tuple[Observation, ...]
    observations_truncated: bool
    series: tuple[SeriesPresence, ...]


@dataclass(frozen=True, slots=True)
class RecordHistoryAnswer:
    records: tuple[RecordHistory, ...]
    not_found: tuple[str, ...]
    versions: tuple[VersionBlock, ...]
    qualifiers: tuple[ReportQualifier, ...]


@dataclass(frozen=True, slots=True)
class CompareEntry:
    section: str
    #: added / not_observed / changed: the record's identity key.
    identity_key: str | None = None
    changed_fields: tuple[str, ...] = ()
    old_status_class: StatusClass | None = None
    new_status_class: StatusClass | None = None
    #: lines: the content signature, its side and whether it matched.
    signature: str | None = None
    side: str | None = None
    content_matched: bool | None = None


@dataclass(frozen=True, slots=True)
class MeasureDelta:
    name: str
    status_class: StatusClass | None
    #: `to - from` when both sides are reportable.
    delta: Decimal | None
    reasons: frozenset[NotReportableReason]
    money: bool
    currency: str | None
    #: Both sides' measure qualifiers: `reconciliation_mismatch` on a count (ruling A2).
    qualifiers: frozenset[ReportQualifier] = frozenset()


@dataclass(frozen=True, slots=True)
class CompareAnswer:
    series_id: str
    comparable: bool
    entries: tuple[CompareEntry, ...]
    measures_delta: tuple[MeasureDelta, ...]
    versions: tuple[VersionBlock, ...]
    qualifiers: tuple[ReportQualifier, ...]
    next_cursor: str | None
    cursor_state: str | None


@dataclass(frozen=True, slots=True)
class CoverageProject:
    project_id: str
    sources: tuple[SourceCoverage, ...]
    retired_sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoverageAnswer:
    projects: tuple[CoverageProject, ...]
    record_family: RecordFamily | None


@dataclass(frozen=True, slots=True)
class Availability:
    state: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    project_id: str
    availability: Availability
    counts: tuple[MeasureEntry, ...] = ()
    versions: tuple[VersionBlock, ...] = ()
    qualifiers: tuple[ReportQualifier, ...] = ()


# --- normalization --------------------------------------------------------------------------


def _identifier(value: object, kind: IdKind, detail: SafeDetail) -> str:
    if not isinstance(value, str):
        raise InvalidRequestError(detail)
    try:
        return validate_identifier(value, kind)
    except InvalidIdentifierError:
        raise InvalidRequestError(detail) from None


def _project_ids(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise InvalidRequestError(SafeDetail.PROJECT_IDS)
    if not value or len(value) > MAX_PROJECT_IDS:
        raise InvalidRequestError(SafeDetail.PROJECT_IDS)
    found = tuple(_identifier(item, IdKind.PROJECT, SafeDetail.PROJECT_IDS) for item in value)
    if len(set(found)) != len(found):
        raise InvalidRequestError(SafeDetail.PROJECT_IDS)
    return found


def _family(value: object, *, required: bool) -> RecordFamily | None:
    if value is None and not required:
        return None
    choices = tuple(family.value for family in RecordFamily)
    if not isinstance(value, str) or value not in choices:
        raise InvalidRequestError(
            SafeDetail.RECORD_FAMILY, allowed_values={SafeDetail.RECORD_FAMILY: choices}
        )
    return RecordFamily(value)


def _terms(value: object, detail: SafeDetail) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence) or len(value) > MAX_FILTER_ITEMS:
        raise InvalidRequestError(detail)
    found: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or len(item) > MAX_TERM_CHARACTERS:
            raise InvalidRequestError(detail)
        found.append(item)
    return tuple(sorted(set(found)))


def _day(value: object, detail: SafeDetail) -> date | None:
    if value is None:
        return None
    if type(value) is not date:
        raise InvalidRequestError(detail)
    return value


def _snapshot(value: object, detail: SafeDetail) -> str | None:
    if value is None:
        return None
    return _identifier(value, IdKind.INGEST_SNAPSHOT, detail)


def _series(value: object) -> str:
    if not is_series_id(value):
        raise InvalidRequestError(SafeDetail.SERIES_ID)
    assert isinstance(value, str)  # noqa: S101 - is_series_id checked the type
    return value


def _limit(value: object, high: int) -> int:
    if type(value) is not int or not 1 <= value <= high:
        raise InvalidRequestError(SafeDetail.LIMIT)
    return value


def _cursor_token(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_CURSOR_CHARACTERS:
        raise InvalidRequestError(SafeDetail.CURSOR)
    return value


@dataclass(frozen=True, slots=True)
class _Query:
    project_id: str
    family: RecordFamily
    series_id: str | None
    version: str | None
    status_classes: tuple[StatusClass, ...]
    statuses: tuple[str, ...]
    date_field: str | None
    date_from: date | None
    date_to: date | None
    rfi_terms: tuple[ProjectReportRfiTerm, ...]
    identifiers: tuple[ProjectReportIdentifierTerm, ...]
    group_keys: tuple[str, ...]
    text: str | None
    measures: tuple[str, ...]
    include_rows: bool
    limit: int
    cursor: str | None

    @property
    def row_filtered(self) -> bool:
        """Any row filter applies (a date field without a bound selects every line)."""
        return bool(
            self.status_classes
            or self.statuses
            or (
                self.date_field is not None
                and (self.date_from is not None or self.date_to is not None)
            )
            or self.rfi_terms
            or self.identifiers
            or self.group_keys
            or self.text is not None
        )

    def line_query(
        self, derivation_ids: tuple[str, ...], *, limit: int, after: tuple[int, int] | None
    ) -> ProjectReportLineQuery:
        """The repository read of the lines these row filters select."""
        return ProjectReportLineQuery(
            derivation_ids=derivation_ids,
            limit=limit,
            after=after,
            status_classes=self.status_classes,
            statuses=self.statuses,
            date_field=self.date_field,
            date_from=self.date_from,
            date_to=self.date_to,
            rfi_terms=self.rfi_terms,
            identifiers=self.identifiers,
            group_keys=self.group_keys,
            text=self.text,
            text_fields=searchable_text_fields(self.family) if self.text is not None else (),
        )

    def document(self) -> dict[str, object]:
        """The request without cursor and limit, as the cursor binding covers it."""
        return {
            "project_id": self.project_id,
            "record_family": self.family.value,
            "series_id": self.series_id,
            "version": self.version,
            "status_classes": [status.value for status in self.status_classes],
            "statuses": list(self.statuses),
            "date_field": self.date_field,
            "date_from": None if self.date_from is None else self.date_from.isoformat(),
            "date_to": None if self.date_to is None else self.date_to.isoformat(),
            "rfi_terms": [[term.prefix, term.suffix] for term in self.rfi_terms],
            "identifiers": [[term.field_key, term.value] for term in self.identifiers],
            "group_keys": list(self.group_keys),
            "text": self.text,
            "measures": list(self.measures),
            "include_rows": self.include_rows,
        }


def _identifier_terms(
    value: object, family: RecordFamily
) -> tuple[tuple[ProjectReportRfiTerm, ...], tuple[ProjectReportIdentifierTerm, ...]]:
    if isinstance(value, str) or not isinstance(value, Sequence) or len(value) > MAX_FILTER_ITEMS:
        raise InvalidRequestError(SafeDetail.IDENTIFIERS)
    kinds = IDENTIFIER_KINDS[family]
    rfis: set[ProjectReportRfiTerm] = set()
    exact: set[ProjectReportIdentifierTerm] = set()
    for item in value:
        if not isinstance(item, IdentifierItem) or item.kind not in kinds:
            raise InvalidRequestError(
                SafeDetail.IDENTIFIERS, allowed_values={SafeDetail.IDENTIFIERS: tuple(kinds)}
            )
        text: object = item.value  # typed by the dataclass, checked as received
        if not isinstance(text, str) or len(text) > MAX_TERM_CHARACTERS:
            raise InvalidRequestError(SafeDetail.IDENTIFIERS)
        text = normalize_whitespace(text)
        if not text:
            raise InvalidRequestError(SafeDetail.IDENTIFIERS)
        if item.kind == "rfi":
            number = split_rfi_number(text)
            if number is None:
                raise InvalidRequestError(SafeDetail.IDENTIFIERS)
            rfis.add(ProjectReportRfiTerm(number.prefix, number.suffix))
        else:
            exact.add(ProjectReportIdentifierTerm(kinds[item.kind], text))
    return (
        tuple(sorted(rfis, key=lambda t: (t.suffix, t.prefix or ""))),
        tuple(sorted(exact, key=lambda t: (t.field_key, t.value))),
    )


def normalize_query(request: QueryRequest) -> _Query:
    """Section 2.4 bounds; `invalid_request` with one SafeDetail token otherwise."""
    project_id = _identifier(request.project_id, IdKind.PROJECT, SafeDetail.PROJECT_ID)
    family = _family(request.record_family, required=True)
    assert family is not None  # noqa: S101 - required
    series = None if request.series_id is None else _series(request.series_id)
    version = _snapshot(request.version, SafeDetail.VERSION)
    if version is not None and series is None:
        raise InvalidRequestError(SafeDetail.SERIES_ID)
    status_values = tuple(status.value for status in StatusClass)
    raw_classes = _terms(request.status_classes, SafeDetail.STATUS_CLASSES)
    if any(item not in status_values for item in raw_classes):
        raise InvalidRequestError(
            SafeDetail.STATUS_CLASSES, allowed_values={SafeDetail.STATUS_CLASSES: status_values}
        )
    statuses = _terms(request.statuses, SafeDetail.STATUSES)
    date_field: object = request.date_field
    if date_field is not None and (
        not isinstance(date_field, str) or date_field not in date_fields(family)
    ):
        raise InvalidRequestError(
            SafeDetail.DATE_FIELD, allowed_values={SafeDetail.DATE_FIELD: date_fields(family)}
        )
    date_from = _day(request.date_from, SafeDetail.DATE_FROM)
    date_to = _day(request.date_to, SafeDetail.DATE_TO)
    if (date_from is not None or date_to is not None) and date_field is None:
        raise InvalidRequestError(SafeDetail.DATE_FIELD)
    if date_from is not None and date_to is not None and date_from > date_to:
        raise InvalidRequestError(SafeDetail.DATE_TO)
    rfi_terms, identifiers = _identifier_terms(request.identifiers, family)
    group_keys = _terms(request.group_keys, SafeDetail.GROUP_KEYS)
    text: object = request.text
    if text is not None:
        if not isinstance(text, str) or len(text) > MAX_TEXT_CHARACTERS or not text.strip():
            raise InvalidRequestError(SafeDetail.TEXT)
        text = text.strip()
    allowed = tuple(name for name, spec in MEASURES.items() if spec.family is family)
    measures = _terms(request.measures, SafeDetail.MEASURES)
    if any(name not in allowed for name in measures):
        raise InvalidRequestError(
            SafeDetail.MEASURES, allowed_values={SafeDetail.MEASURES: allowed}
        )
    if type(request.include_rows) is not bool:
        raise InvalidRequestError(SafeDetail.INCLUDE_ROWS)
    return _Query(
        project_id=project_id,
        family=family,
        series_id=series,
        version=version,
        status_classes=tuple(StatusClass(item) for item in raw_classes),
        statuses=statuses,
        date_field=date_field,
        date_from=date_from,
        date_to=date_to,
        rfi_terms=rfi_terms,
        identifiers=identifiers,
        group_keys=group_keys,
        text=text,
        measures=measures,
        include_rows=request.include_rows,
        limit=_limit(request.limit, MAX_QUERY_LIMIT),
        cursor=_cursor_token(request.cursor),
    )


def check_record_history_request(
    request: RecordHistoryRequest,
) -> tuple[tuple[str, ...], tuple[str, RecordFamily, str] | None]:
    """Exactly one of `record_ids[]` and `project_id` + `record_family` + `identity_key`."""
    keyed = (request.project_id, request.record_family, request.identity_key)
    ids: object = request.record_ids
    if isinstance(ids, str) or not isinstance(ids, Sequence) or len(ids) > MAX_RECORD_IDS:
        raise InvalidRequestError(SafeDetail.RECORD_IDS)
    if ids:
        if any(part is not None for part in keyed):
            raise InvalidRequestError(SafeDetail.RECORD_IDS)
        found = tuple(
            dict.fromkeys(
                _identifier(item, IdKind.PROJECT_REPORT_RECORD, SafeDetail.RECORD_IDS)
                for item in ids
            )
        )
        return found, None
    if request.project_id is None:
        raise InvalidRequestError(SafeDetail.RECORD_IDS)
    project_id = _identifier(request.project_id, IdKind.PROJECT, SafeDetail.PROJECT_ID)
    family = _family(request.record_family, required=True)
    assert family is not None  # noqa: S101 - required
    key = request.identity_key
    if not isinstance(key, str) or not key.strip() or len(key) > MAX_TERM_CHARACTERS:
        raise InvalidRequestError(SafeDetail.IDENTITY_KEY)
    return (), (project_id, family, key)


@dataclass(frozen=True, slots=True)
class _Compare:
    series_id: str
    from_version: str | None
    to_version: str | None
    limit: int
    cursor: str | None

    def document(self) -> dict[str, object]:
        return {
            "series_id": self.series_id,
            "from_version": self.from_version,
            "to_version": self.to_version,
        }


def normalize_compare(request: CompareRequest) -> _Compare:
    return _Compare(
        series_id=_series(request.series_id),
        from_version=_snapshot(request.from_version, SafeDetail.FROM_VERSION),
        to_version=_snapshot(request.to_version, SafeDetail.TO_VERSION),
        limit=_limit(request.limit, MAX_COMPARE_LIMIT),
        cursor=_cursor_token(request.cursor),
    )


# --- helpers over versions and lines ------------------------------------------------------


def _ref(version: ProjectReportVersionRecord) -> VersionRef:
    return VersionRef(version.snapshot_id, version.date_label, version.first_seen_at)


def _by_series(
    versions: Iterable[ProjectReportVersionRecord],
) -> dict[str, list[ProjectReportVersionRecord]]:
    """Series in the repository's order (first first-seen, then id); versions in D10 order."""
    series: dict[str, list[ProjectReportVersionRecord]] = {}
    for version in versions:
        series.setdefault(version.series_id, []).append(version)
    for members in series.values():
        members.sort(key=lambda v: version_order_key(_ref(v)))
    return series


def _latest_of(members: Sequence[ProjectReportVersionRecord]) -> ProjectReportVersionRecord:
    latest = latest_version(_ref(v) for v in members)
    return next(v for v in members if latest is not None and v.snapshot_id == latest.snapshot_id)


def _block(
    version: ProjectReportVersionRecord, series: Mapping[str, list[ProjectReportVersionRecord]]
) -> VersionBlock:
    members = series.get(version.series_id, [version])
    return VersionBlock(
        record=version,
        filter_semantics=version_filter_semantics(
            version.filter_declared_at, version.first_seen_at
        ),
        is_latest=_latest_of(members).snapshot_id == version.snapshot_id,
    )


def _qualifiers(blocks: Iterable[VersionBlock]) -> tuple[ReportQualifier, ...]:
    return answer_qualifiers(
        [UsedVersion(_ref(block.record), block.filter_semantics) for block in blocks]
    )


def _bounded(versions: Sequence[ProjectReportVersionRecord], detail: SafeDetail) -> None:
    if len(versions) > MAX_VERSIONS:
        raise InvalidRequestError(detail)


def _all_lines(
    reads: ProjectReportReadsRepository,
    principal_id: str,
    derivation_id: str,
    filters: _Query | None = None,
) -> list[ProjectReportReadLine]:
    """Every detail line of one current derivation (or every one `filters` selects), batched."""
    found: list[ProjectReportReadLine] = []
    after: tuple[int, int] | None = None
    while True:
        batch = reads.query_lines(
            principal_id,
            ProjectReportLineQuery(derivation_ids=(derivation_id,), limit=_LINE_BATCH, after=after)
            if filters is None
            else filters.line_query((derivation_id,), limit=_LINE_BATCH, after=after),
        )
        found.extend(batch)
        if len(batch) < _LINE_BATCH:
            return found
        after = (0, batch[-1].row_ordinal)


def _value(line: ProjectReportReadLine, field_key: str) -> ProjectReportLineValueRecord | None:
    return next((v for v in line.values if v.field_key == field_key), None)


def _planned(spec: MeasureSpec, lines: Iterable[ProjectReportReadLine]) -> list[PlannedLine]:
    planned: list[PlannedLine] = []
    for line in lines:
        cell = None
        if spec.field_key is not None:
            value = _value(line, spec.field_key)
            cell = (
                NumericCell("", None)
                if value is None
                else NumericCell(
                    value.raw_text,
                    value.value if isinstance(value.value, Decimal) else None,
                    value.value_reason,
                )
            )
        key = line.identity_key if line.identity_state is IdentityState.IDENTIFIED else None
        planned.append(PlannedLine(line.line_kind, line.status_class, key, cell))
    return planned


def _inputs(version: ProjectReportVersionRecord, mismatched: frozenset[str]) -> MeasureInputs:
    return MeasureInputs(
        state=version.state,
        quarantine_reason=version.quarantine_reason,
        reconciliation=version.reconciliation,
        cross_check_mismatch=version.derivation_id in mismatched,
    )


def _mismatched(
    reads: ProjectReportReadsRepository, principal_id: str, derivation_ids: Sequence[str]
) -> frozenset[str]:
    """The derivations a current cross-check mismatch names (both sides current, ruling A4)."""
    found: set[str] = set()
    for check in reads.cross_checks_of(principal_id, derivation_ids):
        if check.outcome.value == "mismatch":
            found.update((check.left_derivation_id, check.right_derivation_id))
    return frozenset(found)


def _measure(
    reads: ProjectReportReadsRepository,
    principal_id: str,
    spec: MeasureSpec,
    version: ProjectReportVersionRecord,
    mismatched: frozenset[str],
    lines: dict[str, list[ProjectReportReadLine]],
    filters: _Query | None = None,
) -> MeasureEntry:
    """One measure over a version's lines, or the ones a query's row filters select.

    `lines` caches each derivation's lines across the measures of one answer
    (one answer has one set of filters). The reconciliation inputs are the
    whole version's under either scope (ruling B1, amended; D9).
    """
    scope = measure_scope(row_filtered=filters is not None and filters.row_filtered)
    selecting = filters if scope is MeasureScope.FILTERED else None

    def read(chosen: _Query | None) -> list[ProjectReportReadLine]:
        if version.state is not DerivationState.CLASSIFIED:
            return []
        # The whole version under its derivation id (as `compare` fills it), a slice beside it.
        key = version.derivation_id if chosen is None else f"{version.derivation_id}#filtered"
        if key not in lines:
            lines[key] = _all_lines(reads, principal_id, version.derivation_id, chosen)
        return lines[key]

    whole = _planned(spec, read(None))
    answer = plan_measure(
        spec,
        whole if selecting is None else _planned(spec, read(selecting)),
        _inputs(version, mismatched),
        # Population and the `unknown` block judge the whole version (never a slice).
        version_lines=None if selecting is None else whole,
    )
    return MeasureEntry(answer, version.series_id, version.snapshot_id, version.currency, scope)


def _no_snapshot(spec: MeasureSpec, scope: MeasureScope = MeasureScope.VERSION) -> MeasureEntry:
    return MeasureEntry(plan_measure(spec, [], MeasureInputs(None)), None, None, None, scope)


def _truncate(line: ProjectReportReadLine) -> tuple[ProjectReportReadLine, tuple[str, ...]]:
    """Each text value at most 2,000 characters; the truncated field keys are named."""
    truncated: list[str] = []
    values: list[ProjectReportLineValueRecord] = []
    for value in line.values:
        if len(value.raw_text) > MAX_FIELD_TEXT_CHARACTERS:
            truncated.append(value.field_key)
            raw = value.raw_text[:MAX_FIELD_TEXT_CHARACTERS]
            kept = raw if isinstance(value.value, str) else value.value
            values.append(
                ProjectReportLineValueRecord(
                    value.field_key, value.value_kind, raw, kept, value.value_reason
                )
            )
        else:
            values.append(value)
    if not truncated:
        return line, ()
    return _replace_values(line, tuple(values)), tuple(sorted(truncated))


def _replace_values(
    line: ProjectReportReadLine, values: tuple[ProjectReportLineValueRecord, ...]
) -> ProjectReportReadLine:
    return ProjectReportReadLine(
        derivation_id=line.derivation_id,
        snapshot_id=line.snapshot_id,
        row_ordinal=line.row_ordinal,
        record_family=line.record_family,
        family_view=line.family_view,
        line_kind=line.line_kind,
        identity_state=line.identity_state,
        observation_state=line.observation_state,
        record_id=line.record_id,
        identity_key=line.identity_key,
        degraded_reasons=line.degraded_reasons,
        status_raw=line.status_raw,
        status_class=line.status_class,
        identifier_prefix=line.identifier_prefix,
        identifier_numeric_suffix=line.identifier_numeric_suffix,
        group_path=line.group_path,
        values=values,
    )


def _text_size(line: ProjectReportReadLine) -> int:
    """The characters a row answers: each raw text once (a text value is its raw text)."""
    return sum(len(value.raw_text) for value in line.values) + len(line.status_raw or "")


def _raw(line: ProjectReportReadLine) -> dict[str, str]:
    return {value.field_key: value.raw_text for value in line.values}


# --- the service --------------------------------------------------------------------------


class ProjectReportReads:
    """The five reads and the WP5 facade (module docstring)."""

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], AbstractContextManager[UnitOfWork]],
        clock: Callable[[], datetime] = utc_now,
        reads_enabled: bool = True,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._reads_enabled = reads_enabled

    # --- shared ----------------------------------------------------------------------------

    @staticmethod
    def _cursor(
        token: str | None,
        *,
        parse: Callable[[object], QueryPosition | ComparePosition],
        binding: str,
    ) -> ProjectReportsCursor | None:
        """Shape, then binding: malformed is `invalid_request`, foreign is `conflict`."""
        if token is None:
            return None
        try:
            cursor = decode_cursor(token, parse)
        except CursorMalformedError:
            raise InvalidRequestError(SafeDetail.CURSOR) from None
        if cursor.binding != binding:
            raise ConflictError(SafeDetail.CURSOR)
        return cursor

    @staticmethod
    def _bindings(
        unit: UnitOfWork, principal_id: str
    ) -> dict[str, list[ProjectReportBindingRecord]]:
        """The Principal's project-report bindings (active or retired) by Project."""
        by_project: dict[str, list[ProjectReportBindingRecord]] = {}
        for binding in unit.project_reports.list_bindings(principal_id):
            by_project.setdefault(binding.project_id, []).append(binding)
        return by_project

    def _projects(
        self, unit: UnitOfWork, principal_id: str, project_ids: tuple[str, ...] | None
    ) -> tuple[dict[str, list[ProjectReportBindingRecord]], tuple[str, ...]]:
        bindings = self._bindings(unit, principal_id)
        if project_ids is None:
            return bindings, tuple(sorted(bindings))
        if any(project_id not in bindings for project_id in project_ids):
            # Unknown, foreign and never-bound alike.
            raise NotFoundError(SafeDetail.PROJECT_IDS)
        return bindings, project_ids

    # --- catalog ---------------------------------------------------------------------------

    def catalog(self, principal_id: str, request: CatalogRequest) -> CatalogAnswer:
        project_ids = _project_ids(request.project_ids)
        family = _family(request.record_family, required=False)
        with self._unit_of_work() as unit:
            bindings, chosen = self._projects(unit, principal_id, project_ids)
            versions = (
                unit.project_report_reads.list_report_versions(
                    principal_id, project_ids=list(chosen), record_family=family
                )
                if chosen
                else ()
            )
            _bounded(versions, SafeDetail.PROJECT_IDS)
            enabled = {
                source.ingest_source_id: source.enabled
                for source in unit.ingestion.list_sources(principal_id)
                if source.consumer is IngestConsumer.PULSE_CSV_EXPORT
            }
            projects: list[CatalogProject] = []
            total = 0
            emitted = 0
            blocks: list[VersionBlock] = []
            for project_id in chosen:
                sources: list[SourceEntry] = []
                for binding in sorted(bindings[project_id], key=lambda b: b.ingest_source_id):
                    revision = unit.project_reports.get_binding_revision(
                        principal_id, binding.binding_revision_id
                    )
                    sources.append(
                        SourceEntry(
                            ingest_source_id=binding.ingest_source_id,
                            binding_state=binding.state,
                            enabled=enabled.get(binding.ingest_source_id, False),
                            project_number=None
                            if revision is None
                            else revision.declared_project_number,
                            currency=None if revision is None else revision.currency,
                        )
                    )
                series = _by_series(v for v in versions if v.project_id == project_id)
                entries: list[SeriesEntry] = []
                for series_id, members in series.items():
                    total += 1
                    if emitted >= MAX_SERIES:
                        continue
                    emitted += 1
                    latest = _block(_latest_of(members), series)
                    blocks.append(latest)
                    entries.append(
                        SeriesEntry(
                            series_id=series_id,
                            record_family=latest.record.record_family,
                            family_view=latest.record.family_view,
                            slug_label=latest.record.slug_label,
                            signature_prefix=latest.record.header_signature[:8],
                            versions=len(members),
                            quarantined_versions=sum(
                                1 for v in members if v.state is DerivationState.QUARANTINED
                            ),
                            latest=latest,
                        )
                    )
                active = [s for s in sources if s.binding_state is BindingState.ACTIVE]
                first = active[0] if active else (sources[0] if sources else None)
                projects.append(
                    CatalogProject(
                        project_id=project_id,
                        project_number=None if first is None else first.project_number,
                        currency=None if first is None else first.currency,
                        sources=tuple(sources),
                        series=tuple(entries),
                    )
                )
        return CatalogAnswer(
            projects=tuple(projects),
            series_total=total,
            truncated=total > emitted,
            qualifiers=_qualifiers(blocks),
        )

    # --- query -----------------------------------------------------------------------------

    def query(
        self,
        principal_id: str,
        request: QueryRequest,
        *,
        grants: Iterable[tuple[str, str | None]] | None = None,
    ) -> QueryAnswer:
        normalized = normalize_query(request)
        binding = cursor_binding(
            capability=PROJECT_REPORTS_QUERY,
            principal_id=principal_id,
            request=normalized.document(),
        )
        cursor = self._cursor(normalized.cursor, parse=query_position, binding=binding)
        with self._unit_of_work() as unit:
            reads = unit.project_report_reads
            if normalized.project_id not in self._bindings(unit, principal_id):
                raise NotFoundError(SafeDetail.PROJECT_ID)
            versions = reads.list_report_versions(
                principal_id, project_ids=[normalized.project_id], record_family=normalized.family
            )
            _bounded(versions, SafeDetail.PROJECT_ID)
            series = _by_series(versions)
            selected = self._select(series, normalized)
            blocks = tuple(_block(version, series) for version in selected)
            resolved = [
                ResolvedVersion(v.series_id, v.snapshot_id, v.derivation_id) for v in selected
            ]
            scope = scope_digest(grant_digest(grants), resolved)
            if cursor is not None and cursor.scope != scope:
                # Ruling D4 (b): the versions changed between pages; nothing else is answered.
                return QueryAnswer(
                    rows=(),
                    rfi_match=(),
                    measures=(),
                    source_totals=None,
                    source_totals_truncated=False,
                    versions=(),
                    qualifiers=(),
                    next_cursor=None,
                    cursor_state=SCOPE_CHANGED_RESTART_REQUIRED,
                )
            readable = [v for v in selected if v.state is DerivationState.CLASSIFIED]
            rows, next_cursor = self._rows(
                reads, principal_id, normalized, selected, readable, cursor, binding, scope
            )
            rfi_match = self._rfi_match(reads, principal_id, normalized, readable)
            measures: tuple[MeasureEntry, ...] = ()
            totals: tuple[tuple[str, ProjectReportStatedTotalRecord], ...] | None = None
            truncated = False
            if normalized.measures:
                measures = self._measures(reads, principal_id, normalized, selected)
                snapshot_of = {v.derivation_id: v.snapshot_id for v in selected}
                stated = reads.stated_totals_of(principal_id, [v.derivation_id for v in readable])
                truncated = len(stated) > MAX_SOURCE_TOTALS
                totals = tuple(
                    (snapshot_of[total.derivation_id], total)
                    for total in stated[:MAX_SOURCE_TOTALS]
                )
        return QueryAnswer(
            rows=rows,
            rfi_match=rfi_match,
            measures=measures,
            source_totals=totals,
            source_totals_truncated=truncated,
            versions=blocks,
            qualifiers=_qualifiers(blocks),
            next_cursor=next_cursor,
            cursor_state=None,
        )

    @staticmethod
    def _select(
        series: Mapping[str, list[ProjectReportVersionRecord]], normalized: _Query
    ) -> list[ProjectReportVersionRecord]:
        """One version per series: the named one, or each series' latest."""
        if normalized.series_id is not None:
            members = series.get(normalized.series_id)
            if not members:
                raise NotFoundError(SafeDetail.SERIES_ID)
            if normalized.version is None:
                return [_latest_of(members)]
            named = [v for v in members if v.snapshot_id == normalized.version]
            if not named:
                raise NotFoundError(SafeDetail.VERSION)
            return named
        return [_latest_of(members) for members in series.values()]

    @staticmethod
    def _rows(
        reads: ProjectReportReadsRepository,
        principal_id: str,
        normalized: _Query,
        selected: Sequence[ProjectReportVersionRecord],
        readable: Sequence[ProjectReportVersionRecord],
        cursor: ProjectReportsCursor | None,
        binding: str,
        scope: str,
    ) -> tuple[tuple[RowEntry, ...], str | None]:
        if not normalized.include_rows or not readable:
            return (), None
        ordinal = {v.derivation_id: index for index, v in enumerate(selected)}
        order = [v.derivation_id for v in readable]
        after: tuple[int, int] | None = None
        if cursor is not None:
            position = cursor.position
            if not isinstance(position, QueryPosition):
                raise InvalidRequestError(SafeDetail.CURSOR)
            index = next(
                (
                    i
                    for i, v in enumerate(readable)
                    if ordinal[v.derivation_id] == position.series_ordinal
                    and v.snapshot_id == position.version
                ),
                None,
            )
            if index is None:
                raise InvalidRequestError(SafeDetail.CURSOR)
            after = (index, position.row_ordinal)
        lines = reads.query_lines(
            principal_id,
            normalized.line_query(tuple(order), limit=normalized.limit + 1, after=after),
        )
        by_derivation = {v.derivation_id: v for v in readable}
        page: list[RowEntry] = []
        used = 0
        stopped = False
        for line in lines[: normalized.limit]:
            kept, truncated = _truncate(line)
            size = _text_size(kept)
            if page and used + size > MAX_ANSWER_TEXT_CHARACTERS:
                stopped = True
                break
            used += size
            version = by_derivation[line.derivation_id]
            page.append(RowEntry(kept, version.series_id, version.currency, truncated))
        more = stopped or len(lines) > normalized.limit
        if not more or not page:
            return tuple(page), None
        last = page[-1].line
        token = encode_cursor(
            ProjectReportsCursor(
                binding=binding,
                scope=scope,
                position=QueryPosition(
                    ordinal[last.derivation_id], last.snapshot_id, last.row_ordinal
                ),
            )
        )
        return tuple(page), token

    @staticmethod
    def _rfi_match(
        reads: ProjectReportReadsRepository,
        principal_id: str,
        normalized: _Query,
        readable: Sequence[ProjectReportVersionRecord],
    ) -> tuple[RfiNumberMatch, ...]:
        """For every RFI named without a prefix: exact, or `ambiguous_prefix` with candidates."""
        bare = [term for term in normalized.rfi_terms if term.prefix is None]
        if not bare:
            return ()
        return _match_numbers(
            reads,
            principal_id,
            [v.derivation_id for v in readable],
            [(None, term.suffix) for term in bare],
        )

    @staticmethod
    def _measures(
        reads: ProjectReportReadsRepository,
        principal_id: str,
        normalized: _Query,
        selected: Sequence[ProjectReportVersionRecord],
    ) -> tuple[MeasureEntry, ...]:
        """Per answer scope, never per page: the cursor plays no part (ruling B1, amended)."""
        mismatched = _mismatched(
            reads,
            principal_id,
            [v.derivation_id for v in selected if v.state is DerivationState.CLASSIFIED],
        )
        cache: dict[str, list[ProjectReportReadLine]] = {}
        entries: list[MeasureEntry] = []
        scope = measure_scope(row_filtered=normalized.row_filtered)
        for name in normalized.measures:
            spec = MEASURES[name]
            # One version per series, never summed across 2 series of a view.
            chosen = [v for v in selected if v.family_view is spec.view]
            if not chosen:
                entries.append(_no_snapshot(spec, scope))
            for version in chosen:
                entries.append(
                    _measure(reads, principal_id, spec, version, mismatched, cache, normalized)
                )
        return tuple(entries)

    # --- record history --------------------------------------------------------------------

    def record_history(
        self, principal_id: str, request: RecordHistoryRequest
    ) -> RecordHistoryAnswer:
        record_ids, keyed = check_record_history_request(request)
        with self._unit_of_work() as unit:
            reads = unit.project_report_reads
            if keyed is not None:
                project_id, family, key = keyed
                if project_id not in self._bindings(unit, principal_id):
                    raise NotFoundError(SafeDetail.PROJECT_ID)
                entries = reads.find_records(principal_id, project_id, family, key)
                if not entries:
                    raise NotFoundError(SafeDetail.IDENTITY_KEY)
                not_found: tuple[str, ...] = ()
            else:
                looked = {
                    rid: unit.project_reports.get_record(principal_id, rid) for rid in record_ids
                }
                entries = tuple(entry for entry in looked.values() if entry is not None)
                not_found = tuple(rid for rid, entry in looked.items() if entry is None)
            if not entries:
                return RecordHistoryAnswer((), not_found, (), ())
            pairs = sorted({(e.project_id, e.record_family) for e in entries})
            versions: list[ProjectReportVersionRecord] = []
            for project_id, family in pairs:
                versions += reads.list_report_versions(
                    principal_id, project_ids=[project_id], record_family=family
                )
            _bounded(versions, SafeDetail.RECORD_IDS)
            series = _by_series(versions)
            by_snapshot = {v.snapshot_id: v for v in versions}
            lines = reads.lines_of_records(principal_id, [e.record_id for e in entries])
        used: dict[str, VersionBlock] = {}
        histories: list[RecordHistory] = []
        series_order = {series_id: index for index, series_id in enumerate(series)}
        for entry in entries:
            mine = [
                line
                for line in lines
                if line.record_id == entry.record_id and line.snapshot_id in by_snapshot
            ]
            mine.sort(
                key=lambda line: (
                    series_order[by_snapshot[line.snapshot_id].series_id],
                    version_order_key(_ref(by_snapshot[line.snapshot_id])),
                    line.row_ordinal,
                )
            )
            observations: list[Observation] = []
            previous: dict[str, dict[str, str]] = {}
            for line in mine:
                version = by_snapshot[line.snapshot_id]
                raw = _raw(line)
                before = previous.get(version.series_id)
                changed = (
                    ()
                    if before is None
                    else tuple(
                        sorted(k for k in set(before) | set(raw) if before.get(k) != raw.get(k))
                    )
                )
                previous[version.series_id] = raw
                observations.append(Observation(line, version.series_id, changed))
            presences: list[SeriesPresence] = []
            for series_id in dict.fromkeys(o.series_id for o in observations):
                members = series[series_id]
                refs = [_ref(v) for v in members]
                presence = compare_versions(
                    refs,
                    [
                        RecordObservation(
                            _ref(by_snapshot[o.line.snapshot_id]),
                            entry.record_id,
                            o.line.status_class,
                        )
                        for o in observations
                        if o.series_id == series_id
                    ],
                )[entry.record_id]
                latest = _latest_of(members)
                # Ruling R1-01: a quarantined latest version has no lines, so the
                # record's absence from it is never inferred (as `compare` answers
                # `comparable: false`); the readable versions' history still stands.
                unreadable = derivation_blockers(latest.state, latest.quarantine_reason)
                presences.append(
                    SeriesPresence(
                        series_id,
                        VersionPresence.LATEST_UNREADABLE if unreadable else presence.presence,
                        presence.last_observed.snapshot_id,
                        presence.last_status,
                        unreadable,
                    )
                )
                for member in members:
                    used.setdefault(member.snapshot_id, _block(member, series))
            histories.append(
                RecordHistory(
                    record_id=entry.record_id,
                    identity_key=entry.identity_key,
                    identity_version=entry.identity_version,
                    record_family=entry.record_family,
                    observations=tuple(observations[:MAX_OBSERVATIONS]),
                    observations_truncated=len(observations) > MAX_OBSERVATIONS,
                    series=tuple(presences),
                )
            )
        blocks = tuple(used.values())
        return RecordHistoryAnswer(tuple(histories), not_found, blocks, _qualifiers(blocks))

    # --- compare ---------------------------------------------------------------------------

    def compare(
        self,
        principal_id: str,
        request: CompareRequest,
        *,
        grants: Iterable[tuple[str, str | None]] | None = None,
    ) -> CompareAnswer:
        normalized = normalize_compare(request)
        binding = cursor_binding(
            capability=PROJECT_REPORTS_COMPARE,
            principal_id=principal_id,
            request=normalized.document(),
        )
        cursor = self._cursor(normalized.cursor, parse=compare_position, binding=binding)
        with self._unit_of_work() as unit:
            reads = unit.project_report_reads
            versions = reads.list_report_versions(principal_id)
            members = [v for v in versions if v.series_id == normalized.series_id]
            if not members:  # unknown and another Principal's series alike
                raise NotFoundError(SafeDetail.SERIES_ID)
            _bounded(members, SafeDetail.SERIES_ID)
            series = _by_series(members)
            ordered = series[normalized.series_id]
            pair = self._pair(ordered, normalized)
            if pair is None:
                only = _block(ordered[-1], series)
                return CompareAnswer(
                    normalized.series_id, False, (), (), (only,), _qualifiers([only]), None, None
                )
            before, after = pair
            blocks = (_block(before, series), _block(after, series))
            resolved = [ResolvedVersion(v.series_id, v.snapshot_id, v.derivation_id) for v in pair]
            scope = scope_digest(grant_digest(grants), resolved)
            if cursor is not None and cursor.scope != scope:
                return CompareAnswer(
                    normalized.series_id,
                    True,
                    (),
                    (),
                    (),
                    (),
                    None,
                    SCOPE_CHANGED_RESTART_REQUIRED,
                )
            if any(v.state is not DerivationState.CLASSIFIED for v in pair):
                # A quarantined version has no lines: nothing is compared, nothing inferred.
                return CompareAnswer(
                    normalized.series_id, False, (), (), blocks, _qualifiers(blocks), None, None
                )
            cache = {
                v.derivation_id: _all_lines(reads, principal_id, v.derivation_id) for v in pair
            }
            mismatched = _mismatched(reads, principal_id, [v.derivation_id for v in pair])
            deltas = self._deltas(reads, principal_id, before, after, mismatched, cache)
        entries = _compare_entries(cache[before.derivation_id], cache[after.derivation_id])
        start = 0
        if cursor is not None:
            position = cursor.position
            if not isinstance(position, ComparePosition):
                raise InvalidRequestError(SafeDetail.CURSOR)
            start = _entry_index(entries, position) + 1
        page = entries[start : start + normalized.limit]
        next_cursor = None
        if start + normalized.limit < len(entries):
            next_cursor = encode_cursor(
                ProjectReportsCursor(
                    binding=binding,
                    scope=scope,
                    position=_entry_position(entries, start + normalized.limit - 1),
                )
            )
        return CompareAnswer(
            normalized.series_id,
            True,
            tuple(page),
            deltas,
            blocks,
            _qualifiers(blocks),
            next_cursor,
            None,
        )

    @staticmethod
    def _pair(
        ordered: Sequence[ProjectReportVersionRecord], normalized: _Compare
    ) -> tuple[ProjectReportVersionRecord, ProjectReportVersionRecord] | None:
        """`(from, to)` in D10 order; `None` when the series has one version and none was named."""
        index = {v.snapshot_id: i for i, v in enumerate(ordered)}
        if normalized.to_version is not None and normalized.to_version not in index:
            raise NotFoundError(SafeDetail.TO_VERSION)
        if normalized.from_version is not None and normalized.from_version not in index:
            raise NotFoundError(SafeDetail.FROM_VERSION)
        to_index = (
            len(ordered) - 1 if normalized.to_version is None else index[normalized.to_version]
        )
        if normalized.from_version is None:
            if to_index == 0:
                if normalized.to_version is not None and len(ordered) > 1:
                    raise InvalidRequestError(SafeDetail.TO_VERSION)
                return None
            from_index = to_index - 1
        else:
            from_index = index[normalized.from_version]
            if from_index >= to_index:
                raise InvalidRequestError(SafeDetail.FROM_VERSION)
        return ordered[from_index], ordered[to_index]

    @staticmethod
    def _deltas(
        reads: ProjectReportReadsRepository,
        principal_id: str,
        before: ProjectReportVersionRecord,
        after: ProjectReportVersionRecord,
        mismatched: frozenset[str],
        cache: dict[str, list[ProjectReportReadLine]],
    ) -> tuple[MeasureDelta, ...]:
        deltas: list[MeasureDelta] = []
        for name, spec in MEASURES.items():
            if spec.view is not after.family_view:
                continue
            old = _measure(reads, principal_id, spec, before, mismatched, cache).answer
            new = _measure(reads, principal_id, spec, after, mismatched, cache).answer
            money = _is_money(spec)
            # Ruling R1-09: an amount is never set against one in another currency.
            mixed = (
                frozenset({NotReportableReason.CURRENCY_MIXED})
                if money and before.currency != after.currency
                else frozenset()
            )
            pairs: list[tuple[StatusClass | None, MeasureValue | None, MeasureValue | None]] = []
            if old.total is not None or new.total is not None:
                pairs.append((None, old.total, new.total))
            for status in STATUS_CLASSES.get(spec.view, ()):
                if status in old.by_status or status in new.by_status:
                    pairs.append((status, old.by_status.get(status), new.by_status.get(status)))
            for status_class, first, second in pairs:
                reasons = frozenset(
                    (first.reasons if first is not None else frozenset())
                    | (second.reasons if second is not None else frozenset())
                    | mixed
                )
                delta = None
                if (
                    not reasons
                    and first is not None
                    and second is not None
                    and first.value is not None
                    and second.value is not None
                ):
                    delta = second.value - first.value
                deltas.append(
                    MeasureDelta(
                        name,
                        status_class,
                        delta,
                        reasons,
                        money,
                        after.currency,
                        # Ruling A2 on a compare (R1-03): a count of either side's
                        # mismatched version is qualified, never blocked.
                        old.qualifiers | new.qualifiers,
                    )
                )
        return tuple(deltas)

    # --- coverage --------------------------------------------------------------------------

    def coverage(self, principal_id: str, request: CoverageRequest) -> CoverageAnswer:
        project_ids = _project_ids(request.project_ids)
        family = _family(request.record_family, required=False)
        with self._unit_of_work() as unit:
            bindings, chosen = self._projects(unit, principal_id, project_ids)
            now = self._clock()
            projects: list[CoverageProject] = []
            for project_id in chosen:
                bound = sorted(bindings[project_id], key=lambda b: b.ingest_source_id)
                sources = project_reports_coverage(
                    unit, principal_id, [b.ingest_source_id for b in bound], now=now
                )
                if family is not None:
                    sources = tuple(_family_only(source, family) for source in sources)
                projects.append(
                    CoverageProject(
                        project_id=project_id,
                        sources=sources,
                        retired_sources=tuple(
                            b.ingest_source_id for b in bound if b.state is BindingState.RETIRED
                        ),
                    )
                )
        return CoverageAnswer(tuple(projects), family)

    # --- the WP5 facade (design section 2.12) -------------------------------------------------

    def availability(self, principal_id: str, project_id: str) -> Availability:
        """`available`, or `unavailable` with one closed reason (`AVAILABILITY_REASONS`)."""
        if not self._reads_enabled:
            return Availability("unavailable", "reads_disabled")
        with self._unit_of_work() as unit:
            return self._availability(unit, principal_id, project_id)

    def _availability(self, unit: UnitOfWork, principal_id: str, project_id: str) -> Availability:
        bindings = self._bindings(unit, principal_id).get(project_id, [])
        if not any(b.state is BindingState.ACTIVE for b in bindings):
            return Availability("unavailable", "unbound")
        versions = unit.project_report_reads.list_report_versions(
            principal_id, project_ids=[project_id]
        )
        if not versions:
            return Availability("unavailable", "never_ingested")
        latest = [_latest_of(members) for members in _by_series(versions).values()]
        if all(v.state is DerivationState.QUARANTINED for v in latest):
            return Availability("unavailable", "all_quarantined")
        return Availability("available")

    def project_summary(self, principal_id: str, project_id: str) -> ProjectSummary:
        """Latest-version record counts by status class for observations, issues and RFIs."""
        if not self._reads_enabled:
            return ProjectSummary(project_id, Availability("unavailable", "reads_disabled"))
        with self._unit_of_work() as unit:
            state = self._availability(unit, principal_id, project_id)
            if state.state != "available":
                return ProjectSummary(project_id, state)
            reads = unit.project_report_reads
            versions = [
                v
                for v in reads.list_report_versions(principal_id, project_ids=[project_id])
                if v.record_family in _SUMMARY_FAMILIES
            ]
            series = _by_series(versions)
            latest = [_latest_of(members) for members in series.values()]
            mismatched = _mismatched(
                reads,
                principal_id,
                [v.derivation_id for v in latest if v.state is DerivationState.CLASSIFIED],
            )
            cache: dict[str, list[ProjectReportReadLine]] = {}
            counts = tuple(
                _measure(
                    reads,
                    principal_id,
                    MEASURES[f"{version.family_view.value}.record_count"],
                    version,
                    mismatched,
                    cache,
                )
                for version in latest
                if version.family_view is not None
            )
        blocks = tuple(_block(version, series) for version in latest)
        return ProjectSummary(project_id, state, counts, blocks, _qualifiers(blocks))

    def match_rfis(
        self,
        principal_id: str,
        project_id: str,
        numbers: Sequence[tuple[str | None, int]],
    ) -> tuple[RfiNumberMatch, ...]:
        """Each `(prefix or None, suffix)` matched exactly in the latest RFI versions (<= 10)."""
        if len(numbers) > MAX_RFI_NUMBERS or any(
            type(suffix) is not int or suffix < 0 or not (prefix is None or isinstance(prefix, str))
            for prefix, suffix in numbers
        ):
            raise InvalidRequestError(SafeDetail.IDENTIFIERS)
        if not self._reads_enabled or not numbers:
            return ()
        with self._unit_of_work() as unit:
            reads = unit.project_report_reads
            versions = reads.list_report_versions(
                principal_id, project_ids=[project_id], record_family=RecordFamily.RFIS
            )
            latest = [_latest_of(members) for members in _by_series(versions).values()]
            readable = [v.derivation_id for v in latest if v.state is DerivationState.CLASSIFIED]
            return _match_numbers(reads, principal_id, readable, numbers)


# --- module helpers -----------------------------------------------------------------------


def _match_numbers(
    reads: ProjectReportReadsRepository,
    principal_id: str,
    derivation_ids: Sequence[str],
    numbers: Sequence[tuple[str | None, int]],
) -> tuple[RfiNumberMatch, ...]:
    candidates = (
        reads.rfi_candidates(principal_id, derivation_ids, [s for _p, s in numbers])
        if derivation_ids
        else ()
    )
    found: list[RfiNumberMatch] = []
    for prefix, suffix in numbers:
        pool = [c for c in candidates if c.suffix == suffix]
        result = match_rfi(prefix, suffix, [RfiNumber("", c.prefix, c.suffix) for c in pool])
        prefixes = {number.prefix for number in result.matches}
        matched = sorted(
            {(c.prefix, c.suffix, c.record_id) for c in pool if c.prefix in prefixes},
            key=lambda c: (c[0] or "", c[2] or ""),
        )
        if not result.matches:
            state = "none"
        elif result.flag == AMBIGUOUS_PREFIX:
            state = AMBIGUOUS_PREFIX
        else:
            state = "exact"
        found.append(RfiNumberMatch(prefix, suffix, state, tuple(matched)))
    return tuple(found)


def _is_money(spec: MeasureSpec) -> bool:
    if spec.field_key is None:
        return False
    entry = field_entry(spec.view, spec.field_key)
    return entry is not None and entry.value_kind is ValueKind.MONEY


def _family_only(source: SourceCoverage, family: RecordFamily) -> SourceCoverage:
    return SourceCoverage(
        ingest_source_id=source.ingest_source_id,
        enabled=source.enabled,
        binding_state=source.binding_state,
        project_number=source.project_number,
        snapshots=source.snapshots,
        ingested=source.ingested,
        rejected=source.rejected,
        quarantined=source.quarantined,
        series=tuple(
            s
            for s in source.series
            if s.family_view is not None and FAMILY_OF_VIEW[FamilyView(s.family_view)] is family
        ),
    )


def _record_states(lines: Sequence[ProjectReportReadLine]) -> dict[str, RecordState]:
    """Each identified record of a version: its first line's status, its fields' raw texts."""
    grouped: dict[str, list[ProjectReportReadLine]] = {}
    for line in lines:
        if line.identity_state is IdentityState.IDENTIFIED and line.identity_key is not None:
            grouped.setdefault(line.identity_key, []).append(line)
    states: dict[str, RecordState] = {}
    for key, members in grouped.items():
        texts: dict[str, list[str]] = {}
        for line in members:
            for value in line.values:
                texts.setdefault(value.field_key, []).append(value.raw_text)
        # A record on several lines (an RFI per drawing link) compares as the multiset.
        raw = {k: "\x1f".join(sorted(v)) for k, v in texts.items()}
        states[key] = RecordState(members[0].status_class, raw)
    return states


def _signature(line: ProjectReportReadLine) -> str:
    return content_signature(line.line_kind, [step[1] for step in line.group_path], _raw(line))


def _compare_entries(
    before: Sequence[ProjectReportReadLine], after: Sequence[ProjectReportReadLine]
) -> list[CompareEntry]:
    """Added, not observed, changed (by identity key), then the snapshot-scoped lines."""
    diff = compare_records(_record_states(before), _record_states(after))
    entries = [CompareEntry("added", identity_key=key) for key in diff.added]
    entries += [CompareEntry("not_observed", identity_key=key) for key in diff.not_observed]
    entries += [
        CompareEntry("changed", key, fields, old, new) for key, fields, old, new in diff.changed
    ]

    def scoped(lines: Sequence[ProjectReportReadLine]) -> list[str]:
        return [
            _signature(line)
            for line in lines
            if line.identity_state is not IdentityState.IDENTIFIED
        ]

    entries += [
        CompareEntry(
            "lines",
            signature=entry.signature,
            side=entry.side,
            content_matched=entry.content_matched,
        )
        for entry in compare_by_content(scoped(before), scoped(after))
    ]
    return entries


def _entry_position(entries: Sequence[CompareEntry], index: int) -> ComparePosition:
    """`[section rank, index]`: the deterministic entry order, pinned by the scope digest."""
    entry = entries[index]
    return ComparePosition(_COMPARE_SECTIONS.index(entry.section), f"{index:010d}")


def _entry_index(entries: Sequence[CompareEntry], position: ComparePosition) -> int:
    if not position.key.isdigit():
        raise InvalidRequestError(SafeDetail.CURSOR)
    index = int(position.key)
    if index >= len(entries) or _entry_position(entries, index) != position:
        raise InvalidRequestError(SafeDetail.CURSOR)
    return index


# --- answers as payloads ------------------------------------------------------------------
#
# What the five reads answer on every transport (WP4P-S4 wires them). Every
# amount is a plain fixed-point string, money with its currency; dates are ISO
# and instants RFC 3339 UTC. Exported text is data, never instructions.


def _iso_label(label: str | None) -> str | None:
    return None if label is None else f"{label[:4]}-{label[4:6]}-{label[6:]}"


def _version_payload(block: VersionBlock) -> dict[str, object]:
    v = block.record
    return {
        "version": v.snapshot_id,
        "series_id": v.series_id,
        "project_id": v.project_id,
        "record_family": None if v.record_family is None else v.record_family.value,
        "family_view": None if v.family_view is None else v.family_view.value,
        "publication_date": _iso_label(v.date_label),
        "first_seen_at": format_rfc3339(v.first_seen_at),
        "filter_semantics": block.filter_semantics.value,
        "completeness_class": None if v.completeness_class is None else v.completeness_class.value,
        "derivation_state": v.state.value,
        "quarantine_reason": None if v.quarantine_reason is None else v.quarantine_reason.value,
        "adapter_version": v.adapter_version,
        "identity_version": v.identity_version,
        "status_map_version": v.status_map_version,
        "currency": v.currency,
        "is_latest": block.is_latest,
    }


def _amount(value: Decimal, *, money: bool, currency: str | None) -> object:
    text = format_amount(value, money=money)
    return {"amount": text, "currency": currency} if money else text


def _measure_value(value: MeasureValue, *, money: bool, currency: str | None) -> dict[str, object]:
    if value.reportable and value.value is not None:
        return {
            "state": "reportable",
            "value": _amount(value.value, money=money, currency=currency),
        }
    return {"state": "not_reportable", "reasons": sorted(reason.value for reason in value.reasons)}


def _measure_payload(entry: MeasureEntry) -> dict[str, object]:
    answer = entry.answer
    spec = answer.spec
    money = _is_money(spec)
    unit = "money" if money else ("count" if spec.field_key is None else "number")
    payload: dict[str, object] = {
        "measure": spec.name,
        "measure_scope": entry.scope.value,
        "series_id": entry.series_id,
        "version": entry.version,
        "basis": spec.basis.value,
        "status_basis": None if spec.status_basis is None else spec.status_basis.value,
        "unit": unit,
        "total": None
        if answer.total is None
        else _measure_value(answer.total, money=money, currency=entry.currency),
        "by_status": {
            status.value: _measure_value(value, money=money, currency=entry.currency)
            for status, value in answer.by_status.items()
        },
        "qualifiers": sorted(q.value for q in answer.qualifiers),
    }
    if spec.basis is MeasureBasis.KEYED_DETAIL_SUM:
        payload["by_key"] = [
            {"key": list(key), **_measure_value(value, money=money, currency=entry.currency)}
            for key, value in answer.by_key.items()
        ]
    if money:
        # `reportable` certifies source integrity only (ADR-024 decision 2).
        payload["evidence_basis"] = "source_evidence"
    return payload


def _field_value(value: ProjectReportLineValueRecord, currency: str) -> object:
    held = value.value
    if held is None:
        return None
    if isinstance(held, Decimal):
        return _amount(held, money=value.value_kind is ValueKind.MONEY, currency=currency)
    if isinstance(held, bool):
        return held
    if isinstance(held, date):
        return held.isoformat()
    return held


def _row_payload(row: RowEntry) -> dict[str, object]:
    line = row.line
    return {
        "version": line.snapshot_id,
        "series_id": row.series_id,
        "row_ordinal": line.row_ordinal,
        "line_kind": line.line_kind.value,
        "record_id": line.record_id,
        "identity_key": line.identity_key,
        "identity_state": line.identity_state.value,
        "observation_state": line.observation_state.value,
        "degraded_reasons": [reason.value for reason in line.degraded_reasons],
        "status": line.status_raw,
        "status_class": None if line.status_class is None else line.status_class.value,
        "group": [{"level": level, "key": key} for level, key, _ordinal in line.group_path],
        "fields": {value.field_key: _field_value(value, row.currency) for value in line.values},
        "raw": {
            value.field_key: value.raw_text
            for value in line.values
            if value.value_kind not in _TEXT_KINDS
        },
        "truncated_fields": list(row.truncated_fields),
    }


def _rfi_payload(match: RfiNumberMatch) -> dict[str, object]:
    return {
        "prefix": match.prefix,
        "suffix": match.suffix,
        "state": match.state,
        "candidates": [
            {"prefix": prefix, "suffix": suffix, "record_id": record_id}
            for prefix, suffix, record_id in match.candidates
        ],
    }


def _total_payload(version: str, total: ProjectReportStatedTotalRecord) -> dict[str, object]:
    entry = None
    for fields in VIEW_FIELDS.values():
        entry = next((e for e in fields if e.field_key == total.field_key), None)
        if entry is not None:
            break
    money = entry is not None and entry.value_kind is ValueKind.MONEY
    return {
        "version": version,
        "row_ordinal": total.row_ordinal,
        "scope": total.scope.value,
        "group_key": total.group_key,
        "field_key": total.field_key,
        "raw_text": total.raw_text,
        "value": None if total.value is None else format_amount(total.value, money=money),
        "computed_value": None
        if total.computed_value is None
        else format_amount(total.computed_value, money=money),
        "additivity": total.additivity.value,
        "outcome": total.outcome.value,
    }


def _qualifier_list(qualifiers: Iterable[ReportQualifier]) -> list[str]:
    return [qualifier.value for qualifier in qualifiers]


def catalog_payload(answer: CatalogAnswer) -> dict[str, object]:
    """What `project_reports.catalog` answers."""
    projects = []
    for project in answer.projects:
        series = []
        for entry in project.series:
            view = entry.family_view
            family = entry.record_family
            series.append(
                {
                    "series_id": entry.series_id,
                    "record_family": None if family is None else family.value,
                    "family_view": None if view is None else view.value,
                    "slug_label": entry.slug_label,
                    "signature_prefix": entry.signature_prefix,
                    "versions": entry.versions,
                    "quarantined_versions": entry.quarantined_versions,
                    "latest": _version_payload(entry.latest),
                    "measures_available": []
                    if view is None
                    else [name for name, spec in MEASURES.items() if spec.view is view],
                    "filters_available": {
                        "date_fields": []
                        if view is None
                        else [e.field_key for e in VIEW_FIELDS[view] if e.date_field],
                        "status_classes": []
                        if view is None
                        else [s.value for s in STATUS_CLASSES.get(view, ())],
                        "identifier_kinds": []
                        if family is None
                        else sorted(IDENTIFIER_KINDS[family]),
                    },
                }
            )
        projects.append(
            {
                "project_id": project.project_id,
                "project_number": project.project_number,
                "currency": project.currency,
                "sources": [
                    {
                        "ingest_source_id": source.ingest_source_id,
                        "binding_state": source.binding_state.value,
                        "enabled": source.enabled,
                    }
                    for source in project.sources
                ],
                "series": series,
            }
        )
    return {
        "projects": projects,
        "series_total": answer.series_total,
        "truncated": answer.truncated,
        "qualifiers": _qualifier_list(answer.qualifiers),
        "cursor_state": None,
    }


def query_payload(answer: QueryAnswer) -> dict[str, object]:
    """What `project_reports.query` answers."""
    payload: dict[str, object] = {
        "rows": [_row_payload(row) for row in answer.rows],
        "rfi_match": [_rfi_payload(match) for match in answer.rfi_match],
        "measures": [_measure_payload(entry) for entry in answer.measures],
        "versions": [_version_payload(block) for block in answer.versions],
        "qualifiers": _qualifier_list(answer.qualifiers),
        "next_cursor": answer.next_cursor,
        "cursor_state": answer.cursor_state,
    }
    if answer.source_totals is not None:
        # Evidence, never a measure (PULSE-AC-08).
        payload["source_totals"] = {
            "basis": "source_evidence",
            # Each outcome is the stated total against the whole version's lines,
            # never against a filtered measure (ruling B1, amended).
            "reconciliation_scope": "version",
            "entries": [_total_payload(version, total) for version, total in answer.source_totals],
            "truncated": answer.source_totals_truncated,
        }
    return payload


def _observation_payload(observation: Observation) -> dict[str, object]:
    line = observation.line
    dates = {
        value.field_key: value.value.isoformat() if isinstance(value.value, date) else None
        for value in line.values
        if value.value_kind is ValueKind.DATE
    }
    return {
        "version": line.snapshot_id,
        "series_id": observation.series_id,
        "family_view": line.family_view.value,
        "row_ordinal": line.row_ordinal,
        "status": line.status_raw,
        "status_class": None if line.status_class is None else line.status_class.value,
        "dates": dates,
        "changed_fields": list(observation.changed_fields),
    }


def record_history_payload(answer: RecordHistoryAnswer) -> dict[str, object]:
    """What `project_reports.record_history` answers."""
    return {
        "records": [
            {
                "record_id": history.record_id,
                "record_family": history.record_family.value,
                "identity_key": history.identity_key,
                "identity_version": history.identity_version,
                "observations": [_observation_payload(o) for o in history.observations],
                "observations_truncated": history.observations_truncated,
                "series": [
                    {
                        "series_id": presence.series_id,
                        "presence": presence.presence.value,
                        "last_observed_version": presence.last_observed_version,
                        "last_status": None
                        if presence.last_status is None
                        else presence.last_status.value,
                        "reasons": sorted(reason.value for reason in presence.reasons),
                    }
                    for presence in history.series
                ],
            }
            for history in answer.records
        ],
        "not_found": list(answer.not_found),
        "versions": [_version_payload(block) for block in answer.versions],
        "qualifiers": _qualifier_list(answer.qualifiers),
        "cursor_state": None,
    }


def _entry_payload(entry: CompareEntry) -> dict[str, object]:
    if entry.section == "lines":
        return {
            "signature": entry.signature,
            "side": entry.side,
            "content_matched": entry.content_matched,
        }
    payload: dict[str, object] = {"identity_key": entry.identity_key}
    if entry.section == "changed":
        payload["changed_fields"] = list(entry.changed_fields)
        payload["old_status_class"] = (
            None if entry.old_status_class is None else entry.old_status_class.value
        )
        payload["new_status_class"] = (
            None if entry.new_status_class is None else entry.new_status_class.value
        )
    return payload


def compare_payload(answer: CompareAnswer) -> dict[str, object]:
    """What `project_reports.compare` answers (never `closed`: `not_observed`)."""
    sections: dict[str, list[dict[str, object]]] = {name: [] for name in _COMPARE_SECTIONS}
    for entry in answer.entries:
        sections[entry.section].append(_entry_payload(entry))
    return {
        "series_id": answer.series_id,
        "comparable": answer.comparable,
        **sections,
        "measures_delta": [
            {
                "measure": delta.name,
                "status_class": None if delta.status_class is None else delta.status_class.value,
                **(
                    {
                        "state": "reportable",
                        "delta": _amount(delta.delta, money=delta.money, currency=delta.currency),
                    }
                    if delta.delta is not None
                    else {
                        "state": "not_reportable",
                        "reasons": sorted(reason.value for reason in delta.reasons),
                    }
                ),
                "qualifiers": sorted(qualifier.value for qualifier in delta.qualifiers),
            }
            for delta in answer.measures_delta
        ],
        "versions": [_version_payload(block) for block in answer.versions],
        "qualifiers": _qualifier_list(answer.qualifiers),
        "next_cursor": answer.next_cursor,
        "cursor_state": answer.cursor_state,
    }


def _series_coverage(series: SeriesCoverage) -> dict[str, object]:
    return {
        "series_id": series.series_id,
        "family_view": series.family_view,
        "versions": series.versions,
        "earliest_date_label": series.earliest_date_label,
        "latest_date_label": series.latest_date_label,
        "first_seen": format_rfc3339(series.first_seen),
        "last_seen": format_rfc3339(series.last_seen),
        "freshness_seconds": series.freshness_seconds,
        "filter_semantics": series.filter_semantics.value,
        "version_filter_semantics": [
            {"version": version, "filter_semantics": semantics.value}
            for version, semantics in series.version_filter_semantics
        ],
        "completeness": dict(series.completeness),
        "quarantined": dict(series.quarantined),
    }


def coverage_payload(answer: CoverageAnswer) -> dict[str, object]:
    """What `project_reports.coverage` answers (unbound folders are not counted, D7)."""
    return {
        "record_family": None if answer.record_family is None else answer.record_family.value,
        "projects": [
            {
                "project_id": project.project_id,
                "sources": [
                    {
                        "ingest_source_id": source.ingest_source_id,
                        "enabled": source.enabled,
                        "binding_state": source.binding_state,
                        "snapshots": source.snapshots,
                        "ingested": source.ingested,
                        "rejected": source.rejected,
                        "quarantined": source.quarantined,
                        "series": [_series_coverage(series) for series in source.series],
                    }
                    for source in project.sources
                ],
                "retired_sources": list(project.retired_sources),
            }
            for project in answer.projects
        ],
        "cursor_state": None,
    }


def availability_payload(availability: Availability) -> dict[str, object]:
    return {"state": availability.state, "reason": availability.reason}


def project_summary_payload(summary: ProjectSummary) -> dict[str, object]:
    """What the WP5 meeting context composes (not an MCP tool)."""
    return {
        "project_id": summary.project_id,
        "availability": availability_payload(summary.availability),
        "counts": [_measure_payload(entry) for entry in summary.counts],
        "versions": [_version_payload(block) for block in summary.versions],
        "qualifiers": _qualifier_list(summary.qualifiers),
    }
