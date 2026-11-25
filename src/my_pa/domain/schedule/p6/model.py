"""P6 XER parse model: issue codes, limits and the plain-data result (S7-1).

Contract `docs/architecture/schedule-xer-import-contract.md` sections 5.1-5.5
(tiers, unknown-field policy, version variation, caps, structural validation),
7.3 (field values), 7.4 (observed fields) and 7.7 (capture limits). Plain
frozen dataclasses: no database type, no IO. Pure, standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final

from my_pa.domain.schedule.p6.catalogue import EntityKind

__all__ = [
    "FATAL_CODES",
    "MAX_LISTED_ISSUES",
    "P6_LIMITS",
    "PROFILE_ID",
    "PROFILE_VERSION",
    "Bound",
    "CalendarStatus",
    "P6Calendar",
    "P6Entity",
    "P6FieldValue",
    "P6Header",
    "P6Issue",
    "P6IssueCode",
    "P6Limits",
    "P6ObservedField",
    "P6ObservedTable",
    "P6Outcome",
    "P6ParseResult",
    "P6Severity",
    "P6Value",
]

PROFILE_ID: Final = "p6_xer_v1"
PROFILE_VERSION: Final = 1

#: A typed value: id/int -> int, hours/num -> Decimal, flag -> bool, ts -> datetime,
#: a calendar day -> date, text/name/enum -> str, empty -> None.
type P6Value = int | Decimal | bool | datetime | date | str | None


class P6IssueCode(StrEnum):
    """Section 5.5 codes, plus the info code section 5.1 asks for (tolerated field missing)."""

    ENCODING_INVALID = "p6_encoding_invalid"
    HEADER_INVALID = "p6_header_invalid"
    STRUCTURE_INVALID = "p6_structure_invalid"
    RECORD_WIDTH_MISMATCH = "p6_record_width_mismatch"
    BOUND_EXCEEDED = "p6_bound_exceeded"
    REQUIRED_TABLE_MISSING = "p6_required_table_missing"
    REQUIRED_FIELD_MISSING = "p6_required_field_missing"
    MULTIPLE_PROJECTS = "p6_multiple_projects"
    VALUE_INVALID = "p6_value_invalid"
    UNKNOWN_ENUM_VALUE = "p6_unknown_enum_value"
    DUPLICATE_ACTIVITY_ID = "p6_duplicate_activity_id"
    REFERENCE_DANGLING = "p6_reference_dangling"
    WBS_CYCLE = "p6_wbs_cycle"
    UNKNOWN_TABLE = "p6_unknown_table"
    UNKNOWN_FIELD = "p6_unknown_field"
    UNKNOWN_FIELD_UNNAMED = "p6_unknown_field_unnamed"
    EXPORT_VERSION_UNTESTED = "p6_export_version_untested"
    EXTERNAL_RELATIONSHIP = "p6_external_relationship"
    CALENDAR_INVALID = "p6_calendar_invalid"
    CALENDAR_BASE_SUBSTITUTED = "p6_calendar_base_substituted"
    CALENDAR_MISSING = "p6_calendar_missing"
    CAPTURE_CAP_REACHED = "p6_capture_cap_reached"
    TOLERATED_FIELD_MISSING = "p6_tolerated_field_missing"


#: Codes that are fatal whenever they occur (5.5). `p6_value_invalid` and
#: `p6_unknown_enum_value` are fatal only on an R field, so they carry severity per issue.
FATAL_CODES: Final = frozenset(
    {
        P6IssueCode.ENCODING_INVALID,
        P6IssueCode.HEADER_INVALID,
        P6IssueCode.STRUCTURE_INVALID,
        P6IssueCode.RECORD_WIDTH_MISMATCH,
        P6IssueCode.BOUND_EXCEEDED,
        P6IssueCode.REQUIRED_TABLE_MISSING,
        P6IssueCode.REQUIRED_FIELD_MISSING,
        P6IssueCode.MULTIPLE_PROJECTS,
        P6IssueCode.DUPLICATE_ACTIVITY_ID,
        P6IssueCode.REFERENCE_DANGLING,
        P6IssueCode.WBS_CYCLE,
    }
)


class P6Severity(StrEnum):
    FATAL = "fatal"
    WARNING = "warning"
    INFO = "info"


class P6Outcome(StrEnum):
    """`failed` on any fatal issue, else `complete` (section 9.3; `partial` is unused)."""

    COMPLETE = "complete"
    FAILED = "failed"


class Bound(StrEnum):
    """Section 5.4 bounds; a `p6_bound_exceeded` issue names one."""

    FILE_BYTES = "file_bytes"
    LINE_BYTES = "line_bytes"
    TABLES = "tables"
    FIELDS_PER_TABLE = "fields_per_table"
    TOTAL_RECORDS = "total_records"
    TASK_RECORDS = "task_records"
    TASKPRED_RECORDS = "taskpred_records"
    PROJWBS_RECORDS = "projwbs_records"
    CALENDAR_RECORDS = "calendar_records"
    CALENDAR_EXCEPTIONS = "calendar_exceptions"
    UDFTYPE_RECORDS = "udftype_records"
    ACTVTYPE_RECORDS = "actvtype_records"
    ACTVCODE_RECORDS = "actvcode_records"
    UDFVALUE_RECORDS = "udfvalue_records"
    TASKACTV_RECORDS = "taskactv_records"
    TASKRSRC_RECORDS = "taskrsrc_records"
    VALUE_CHARACTERS = "value_characters"
    CALENDAR_DATA_CHARACTERS = "calendar_data_characters"
    CALENDAR_TREE_DEPTH = "calendar_tree_depth"
    CALENDAR_TREE_NODES = "calendar_tree_nodes"
    WBS_DEPTH = "wbs_depth"


@dataclass(frozen=True, slots=True)
class P6Limits:
    """Section 5.4 caps (production values) and the section 7.7 capture caps.

    A test may only tighten them (`tightened`), never loosen them.
    """

    file_bytes: int = 16_777_216
    line_bytes: int = 4_194_304
    tables: int = 128
    fields_per_table: int = 512
    total_records: int = 2_000_000
    task_records: int = 25_000
    taskpred_records: int = 100_000
    projwbs_records: int = 25_000
    calendar_records: int = 1_000
    calendar_exceptions: int = 20_000
    udftype_records: int = 2_000
    actvtype_records: int = 2_000
    actvcode_records: int = 100_000
    udfvalue_records: int = 1_000_000
    taskactv_records: int = 500_000
    taskrsrc_records: int = 500_000
    value_characters: int = 65_536
    calendar_data_characters: int = 1_048_576
    calendar_tree_depth: int = 16
    calendar_tree_nodes: int = 200_000
    wbs_depth: int = 64
    captured_fields: int = 300
    captured_values_per_entity: int = 300
    captured_values: int = 3_000_000
    captured_text_characters: int = 4_000

    def tightened(self, **changes: int) -> P6Limits:
        """A copy with some caps lowered; raising any cap is refused."""
        for name, value in changes.items():
            if value > getattr(self, name):
                raise ValueError(f"limit {name} can only be tightened")
        return replace(self, **changes)

    def as_dict(self) -> dict[str, int]:
        return {item.name: getattr(self, item.name) for item in fields(self)}


P6_LIMITS: Final = P6Limits()

#: Per-table record bounds (section 5.4).
TABLE_RECORD_BOUNDS: Final = {
    "TASK": Bound.TASK_RECORDS,
    "TASKPRED": Bound.TASKPRED_RECORDS,
    "PROJWBS": Bound.PROJWBS_RECORDS,
    "CALENDAR": Bound.CALENDAR_RECORDS,
    "UDFTYPE": Bound.UDFTYPE_RECORDS,
    "ACTVTYPE": Bound.ACTVTYPE_RECORDS,
    "ACTVCODE": Bound.ACTVCODE_RECORDS,
    "UDFVALUE": Bound.UDFVALUE_RECORDS,
    "TASKACTV": Bound.TASKACTV_RECORDS,
    "TASKRSRC": Bound.TASKRSRC_RECORDS,
}

#: Issues listed individually per parse; `issue_counts` stays complete beyond it.
MAX_LISTED_ISSUES: Final = 10_000


@dataclass(frozen=True, slots=True)
class P6Issue:
    """One typed issue: code, severity, and where (table, 1-based line, field)."""

    code: P6IssueCode
    severity: P6Severity
    table: str | None = None
    line: int | None = None
    field: str | None = None
    bound: Bound | None = None

    @property
    def fatal(self) -> bool:
        return self.severity is P6Severity.FATAL


@dataclass(frozen=True, slots=True)
class P6Header:
    """`ERMHDR` fields 2 and 3 and the decoding chosen (section 3.2); nothing else of it."""

    export_version: str
    export_date: date | None
    encoding: str


@dataclass(frozen=True, slots=True)
class P6ObservedTable:
    name: str | None
    position: int
    line: int
    catalogued: bool
    records: int


@dataclass(frozen=True, slots=True)
class P6ObservedField:
    """Section 7.4: stats only, never a value."""

    table: str | None
    table_position: int
    field: str | None
    position: int
    field_key: str | None
    catalogued: bool
    tier: str | None
    records: int
    nonempty: int
    min_length: int | None
    max_length: int | None
    shapes: tuple[tuple[str, int], ...]
    unknown_enum: int
    unknown_enum_tokens: tuple[str, ...]
    over_length: int
    captured: bool


@dataclass(frozen=True, slots=True)
class P6Entity:
    """One typed row (project, WBS, activity, relationship): its typed and derived columns."""

    entity_kind: EntityKind
    p6_id: int
    record_line: int
    columns: tuple[tuple[str, P6Value | tuple[str, ...]], ...]

    def get(self, name: str) -> P6Value | tuple[str, ...]:
        for key, value in self.columns:
            if key == name:
                return value
        raise KeyError(name)


class CalendarStatus(StrEnum):
    PARSED = "parsed"
    BASE_SUBSTITUTED = "base_substituted"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class P6Calendar:
    """A CALENDAR row: typed columns plus the parsed `clndr_data` (section 3.4, 8.2)."""

    p6_id: int
    record_line: int
    columns: tuple[tuple[str, P6Value], ...]
    status: CalendarStatus
    used: bool
    #: 7 lists, Monday first, of (start, end) minutes; empty when invalid.
    week: tuple[tuple[tuple[int, int], ...], ...]
    #: sorted (date, intervals); no interval = non-working.
    exceptions: tuple[tuple[date, tuple[tuple[int, int], ...]], ...]
    data_sha256: str | None


@dataclass(frozen=True, slots=True)
class P6FieldValue:
    """Section 7.3: one captured optional value with exactly one typed value."""

    entity_kind: EntityKind
    entity_p6_id: int
    activity_id: str | None
    field_key: str
    ordinal: int
    value_type: str
    value: P6Value
    code_path: tuple[str, ...]
    description: str | None
    source_table: str
    record_line: int


@dataclass(frozen=True, slots=True)
class P6ParseResult:
    """The whole parse: the canonical frame is rendered from exactly this."""

    profile_id: str
    profile_version: int
    catalogue_version: str
    outcome: P6Outcome
    header: P6Header | None
    issues: tuple[P6Issue, ...]
    issue_counts: tuple[tuple[str, int], ...]
    tables: tuple[P6ObservedTable, ...]
    observed_fields: tuple[P6ObservedField, ...]
    project: P6Entity | None = None
    wbs: tuple[P6Entity, ...] = ()
    activities: tuple[P6Entity, ...] = ()
    relationships: tuple[P6Entity, ...] = ()
    calendars: tuple[P6Calendar, ...] = ()
    field_values: tuple[P6FieldValue, ...] = ()
    captured_keys: tuple[str, ...] = field(default=())
