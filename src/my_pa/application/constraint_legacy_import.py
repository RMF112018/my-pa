"""PC-CM-IMP-WP13: the one place a legacy Constraints register becomes canonical.

`ConstraintManagementService` cannot do this and is deliberately not touched.
Its own docstring says legacy is unreachable from it — no method there accepts an
`origin` or a `record_quality`, so every record it makes is `PRODUCT` and
`NORMAL`. This module is the narrow second writer that the accepted migration
exception reserves: it is the only application module allowed to construct a
`ConstraintOrigin.LEGACY_WORKBOOK_IMPORT` record, and the only one allowed to
claim `ConstraintRecordQuality.LEGACY_INCOMPLETE`. The ordinary product mutation
plane stays exactly as strict as it was.

**The persistence layer needed no new method.** `insert_category`,
`insert_constraint`, `insert_revision` and `insert_history` persist whatever
domain object they are handed and know nothing about origin, and
`insert_category` already accepts the `next_sequence` and `issued_count` the
allocator seeding needs. Reads go through the read hydrator so that a stored
legacy-incomplete row is never pushed back through the write aggregate's
constructor, which would refuse it.

**Nothing is invented.** No missing date, status, party, category, code,
description, completion or void value is ever synthesized. A row that cannot be
represented without inventing one is reported as an unsupported row and imported
by nothing. A code is carried as text end to end: `2.01`, `2.1`, `2.10` and
`2.100` are four distinct codes and none of them is ever a float.

**One field is renamed rather than invented, and it is named here.** The
workbook's `COMMENTS` column is carried into the canonical `current_update`
field, which is the register's free-text progress note under its canonical name.
Every other column keeps its meaning: `DAYS ELAPSED` and `LAST UPDATED` are
derived workbook artefacts, are read by nothing, and take no part in any digest
— which is what makes a workbook's own modification stamp unable to act as an
import cursor.

**Provenance lives in the receipt, in columns that already mean this.** The
composed `idempotency_key` is the operation's identity (register, project and
source row), `request_digest` is the SHA-256 of what the row asked for, and
`client_context` names the tool. No column was added and no migration was
written. The human-readable source identity, sheet name and row number live in
the structured report, never in a column and never in a log.

**No baseline row is written.** `constraint_sync_baselines.verified_at` is NOT
NULL, so an unverified baseline is not representable, and fabricating one would
be exactly the false external verification the contract forbids. An imported
record has no baseline and therefore reads as `NEVER_SYNCED`, which is true.
No three-way synchronization is implemented here; that is a later package.

**The report is redacted by construction.** It carries counts, identifiers,
codes, prefixes, type names and stable issue codes. It never carries a
description, a comment, a party label, a closure note, a void reason or any
other workbook narrative, and the dataclasses below are shaped so that there is
no field for one to be put in.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Protocol

from my_pa.contracts.ports import ConstraintManagementUnitOfWork
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.project_controls.business_time import project_today
from my_pa.domain.project_controls.category import (
    CONSTRAINT_CATEGORY_PREFIX_PATTERN,
    ConstraintCategory,
    ConstraintCategoryState,
)
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
    ProjectConstraint,
)
from my_pa.domain.project_controls.history import (
    ConstraintHistoryEntry,
    ConstraintMutationActor,
    ConstraintMutationOperation,
    ConstraintMutationOutcome,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.read_models import (
    MAX_LIST_LIMIT,
    ConstraintListQuery,
    ConstraintListScope,
    ConstraintListSpec,
)
from my_pa.domain.project_controls.revision import ConstraintRevision
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "AUTHORITATIVE_CATEGORY_NAMES",
    "TOOL_CLIENT_CONTEXT",
    "WORKBOOK_STATUS_VOCABULARY",
    "CategoryPlan",
    "ConstraintLegacyImportService",
    "ConstraintSourceReader",
    "ImportDisposition",
    "ImportPlan",
    "ImportReport",
    "LegacyImportError",
    "LegacyImportIdempotencyConflictError",
    "LegacyImportOutcome",
    "LegacyImportProjectUnavailableError",
    "RowClass",
    "RowIssue",
    "SourceCell",
    "SourceRow",
    "SourceScan",
    "plan_import",
    "render_markdown",
    "report_as_dict",
    "row_idempotency_key",
    "row_request_digest",
    "scan_source",
]

#: The tool identity and version, persisted in the receipt's `client_context`.
TOOL_CLIENT_CONTEXT: Final = "tbr-import/1"

#: The version tag mixed into every composed idempotency key. Changing the
#: composition changes this, so a later composition cannot silently collide with
#: a key an earlier one wrote.
KEY_SCHEME: Final = "tbrimp1"

#: The seven authoritative Category names of the accepted migration definition.
#: The names are authoritative; the *prefix text* is enumerated in no accepted
#: source, so each Category's prefix is read from the codes the source workbook
#: itself carries under that section and is invented nowhere.
AUTHORITATIVE_CATEGORY_NAMES: Final[tuple[str, ...]] = (
    "PERMITS - OPEN",
    "AHJ COORDINATION - OPEN",
    "DESIGN DEVELOPMENT - OPEN",
    "UTILITY SERVICE PROVIDERS - OPEN",
    "MOSS INTERNAL COORDINATION ITEMS",
    "PRECONSTRUCTION PROGRESS - OPEN",
    "BUYOUT & PROCUREMENT - OPEN",
)

#: The workbook's own status validation list, and the canonical state each maps
#: to. Two names differ only by a separator; the other four map directly.
WORKBOOK_STATUS_VOCABULARY: Final[Mapping[str, ConstraintLifecycleState]] = {
    "IDENTIFIED": ConstraintLifecycleState.IDENTIFIED,
    "PENDING": ConstraintLifecycleState.PENDING,
    "IN PROGRESS": ConstraintLifecycleState.IN_PROGRESS,
    "ON HOLD": ConstraintLifecycleState.ON_HOLD,
    "CLOSED": ConstraintLifecycleState.CLOSED,
    "VOID": ConstraintLifecycleState.VOID,
}

#: Workbook column headings, normalised, and the field each carries. The two
#: derived columns are mapped so that they can be recognised and then ignored:
#: an unrecognised column is reported, and a column silently dropped is not.
COLUMN_HEADINGS: Final[Mapping[str, str]] = {
    "NO #": "code",
    "NO#": "code",
    "NO": "code",
    "DESCRIPTION": "description",
    "DATE IDENTIFIED": "date_identified",
    "STATUS": "status",
    "DAYS ELAPSED": "days_elapsed",
    "REFERENCE": "reference",
    "RESPONSIBLE": "responsible",
    "B.I.C": "bic",
    "B.I.C.": "bic",
    "BIC": "bic",
    "DUE": "due_date",
    "COMPLETION DATE": "completion_date",
    "COMMENTS": "comments",
    "LAST UPDATED": "last_updated",
}

#: The fields that carry record meaning. Everything else the workbook computes
#: for itself, and a change to one of those changes no digest.
SEMANTIC_FIELDS: Final[tuple[str, ...]] = (
    "code",
    "description",
    "date_identified",
    "status",
    "reference",
    "responsible",
    "bic",
    "due_date",
    "completion_date",
    "comments",
)

#: Fields read, recognised and then deliberately ignored.
DERIVED_FIELDS: Final[frozenset[str]] = frozenset({"days_elapsed", "last_updated"})

#: `2.01` is prefix `2` and sequence text `01`. The sequence keeps its text so
#: that `01`, `1`, `10` and `100` stay four different codes.
_CODE_SEPARATOR: Final = "."

#: Excel's 1900 date system counts from this day, which absorbs the 1900 leap
#: bug for every serial above 60. A serial at or below 60 is ambiguous under
#: that bug and is refused rather than guessed.
_EXCEL_EPOCH: Final = date(1899, 12, 30)
_AMBIGUOUS_SERIAL_LIMIT: Final = 60
_MAX_SERIAL: Final = 2_958_465


class LegacyImportError(ValueError):
    """A legacy import could not proceed. `code` is stable and quotes no value."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LegacyImportProjectUnavailableError(LegacyImportError):
    """The Project has no Constraint settings for this Principal.

    Unconfigured and foreign are deliberately indistinguishable, which is the
    same answer the product mutation plane and the read plane already give.
    """


class LegacyImportIdempotencyConflictError(LegacyImportError):
    """A source row's import identity is already used for different content."""


class _DryRunRollbackError(RuntimeError):
    """Leaves the dry-run transaction by exception so it can only roll back."""


# --- The source port ----------------------------------------------------------


class SourceCell(Protocol):
    """One non-empty source cell, as stored.

    `text` is verbatim and always a string. `numeric` says the cell was typed as
    a number, which matters because a numerically-typed code cell is a defect to
    report rather than a value to coerce. `uncomputed` marks a formula cell with
    no cached value: this build never evaluates a formula, so such a cell has no
    value at all and its row is unsupported.
    """

    @property
    def text(self) -> str: ...

    @property
    def numeric(self) -> bool: ...

    @property
    def uncomputed(self) -> bool: ...


class SourceRow(Protocol):
    """One source row, its non-empty cells keyed by column letter."""

    @property
    def sheet_name(self) -> str: ...

    @property
    def row_number(self) -> int: ...

    @property
    def cells(self) -> Mapping[str, SourceCell]: ...


class ConstraintSourceReader(Protocol):
    """A bounded, values-only reader over one legacy register worksheet.

    Structural rather than nominal on purpose: the one adapter that satisfies it
    lives in `infrastructure` and cannot import this module, because an adapter
    that reached back into the application would invert the dependency the port
    exists to create.
    """

    @property
    def content_digest(self) -> str: ...

    @property
    def sheet_name(self) -> str: ...

    @property
    def uses_1904_dates(self) -> bool: ...

    def rows(self) -> Iterator[SourceRow]: ...


# --- Report vocabulary --------------------------------------------------------


class RowClass(StrEnum):
    """A/B/C, plus the fourth answer a classifier must be able to give."""

    A_COMPLETE = "a_complete"
    B_LEGACY_INCOMPLETE = "b_legacy_incomplete"
    C_IGNORED = "c_ignored"
    UNSUPPORTED = "unsupported"


class ImportDisposition(StrEnum):
    """Whether the run may proceed, as the report states it."""

    READY = "ready"
    BLOCKED = "blocked"


#: Stable issue codes. Each names a structure, never a value.
ISSUE_HEADER_ABSENT: Final = "header_row_absent"
ISSUE_HEADER_UNKNOWN_COLUMN: Final = "header_column_unrecognised"
ISSUE_ROW_BEFORE_SECTION: Final = "row_before_any_section"
ISSUE_FORMULA_UNCOMPUTED: Final = "formula_without_cached_value"
ISSUE_CODE_MISSING: Final = "code_missing"
ISSUE_CODE_NUMERIC_CELL: Final = "code_cell_typed_as_number"
ISSUE_CODE_GRAMMAR: Final = "code_grammar_unrecognised"
ISSUE_CODE_PREFIX_MISMATCH: Final = "code_prefix_mismatches_section"
ISSUE_CODE_DUPLICATE: Final = "code_duplicated_in_source"
ISSUE_CODE_WITHIN_ISSUED_RANGE: Final = "code_within_existing_issued_range"
ISSUE_CODE_COLLIDES_WITH_CANONICAL: Final = "code_already_present_in_canonical"
ISSUE_STATUS_MISSING: Final = "status_missing"
ISSUE_STATUS_UNKNOWN: Final = "status_outside_workbook_vocabulary"
ISSUE_CLOSED_WITHOUT_COMPLETION: Final = "closed_without_completion_date"
ISSUE_VOID_FIELDS_UNAVAILABLE: Final = "void_fields_not_present_in_source"
ISSUE_DATE_UNREADABLE: Final = "date_unreadable"
ISSUE_DATE_SERIAL_AMBIGUOUS: Final = "date_serial_ambiguous"
ISSUE_CATEGORY_UNKNOWN: Final = "category_outside_authoritative_names"
ISSUE_CATEGORY_DUPLICATE_SECTION: Final = "category_section_repeated"
ISSUE_CATEGORY_PREFIX_INVALID: Final = "category_prefix_invalid_grammar"
ISSUE_CATEGORY_PREFIX_COLLISION: Final = "category_prefix_collides"
ISSUE_PARTY_FOREIGN_ENTITY: Final = "party_entity_not_in_partition"
ISSUE_IDEMPOTENCY_COLLISION: Final = "import_identity_reused_for_new_content"
ISSUE_CANONICAL_PAGE_TRUNCATED: Final = "existing_register_exceeds_one_page"
ISSUE_DATE_SYSTEM_1904: Final = "workbook_uses_1904_date_system"


@dataclass(frozen=True, slots=True)
class RowIssue:
    """One reportable finding, addressed by row identity and code only.

    There is deliberately no field for content. A collision is reported by the
    code and the row it was found in, and a reader who needs the cell opens the
    workbook under their own authority.
    """

    row_identity: str
    issue: str
    constraint_code: str | None = None


@dataclass(frozen=True, slots=True)
class CategoryPlan:
    """What one source section proposes for one canonical Category."""

    name: str
    prefix: str
    row_count: int
    max_imported_sequence: int | None
    proposed_next_sequence: int
    proposed_issued_count: int
    existing_category_id: str | None = None
    existing_next_sequence: int | None = None
    existing_version: int | None = None


@dataclass(frozen=True, slots=True)
class ImportReport:
    """The whole bounded, redacted result of one dry-run or one apply."""

    tool: str
    mode: str
    register_id: str
    project_id: str
    sheet_name: str
    source_digest: str
    generated_at: str
    total_source_rows: int
    class_counts: Mapping[str, int]
    lifecycle_counts: Mapping[str, int]
    category_plans: tuple[CategoryPlan, ...]
    attention_counts: Mapping[str, int]
    unresolved_party_count: int
    resolved_party_count: int
    planned_inserts: int
    planned_no_ops: int
    issues: tuple[RowIssue, ...]
    blockers: tuple[str, ...]
    disposition: ImportDisposition
    applied: int = 0
    replayed: int = 0


@dataclass(frozen=True, slots=True)
class LegacyImportOutcome:
    """A run's report, and nothing a caller could mistake for a record."""

    report: ImportReport


# --- Scanning -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _RowValues:
    """One source row's semantic cell text, plus the section it sits under."""

    row_identity: str
    row_number: int
    section: str
    values: Mapping[str, str]
    numeric_fields: frozenset[str]


@dataclass(frozen=True, slots=True)
class _SectionScan:
    """One source section, and the code prefixes observed beneath it."""

    name: str
    row_count: int


@dataclass(frozen=True, slots=True)
class SourceScan:
    """Everything reading the source established, before any database is asked.

    Pure and side-effect free: `scan_source` opens nothing but the reader, so a
    test can prove classification, code preservation and digest stability with no
    server anywhere.
    """

    register_id: str
    project_id: str
    sheet_name: str
    source_digest: str
    total_rows: int
    ignored_rows: int
    rows: tuple[_RowValues, ...] = ()
    sections: tuple[_SectionScan, ...] = ()
    issues: tuple[RowIssue, ...] = ()


def _normalise(text: str) -> str:
    return " ".join(text.split())


def _heading(text: str) -> str:
    return _normalise(text).upper()


def row_idempotency_key(register_id: str, project_id: str, row_identity: str) -> str:
    """The composed import identity of one source row.

    `<scheme>-<sha256(scheme, register, project, row identity)>`, which satisfies
    the stored `^[A-Za-z0-9_-]{8,128}$` rule by construction and is stable across
    reruns of the same register against the same Project. The parts are joined
    by a unit separator so that no two different tuples can render to one string.
    """
    material = "\x1f".join((KEY_SCHEME, register_id, project_id, row_identity))
    return f"{KEY_SCHEME}-{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


def row_request_digest(values: Mapping[str, str], section: str) -> str:
    """The SHA-256 of one row's normalised semantic content.

    Over the semantic fields and the section only, so key order, whitespace and
    the workbook's own derived columns cannot move it — which is what makes the
    workbook's `LAST UPDATED` stamp unusable as an import cursor.
    """
    payload = {name: values.get(name, "") for name in SEMANTIC_FIELDS}
    payload["section"] = section
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _section_heading(row: SourceRow, code_column: str) -> str | None:
    """The heading text a section row carries, if this row is a heading at all.

    A section row is one filled cell, in the register's own first column, typed
    as text, and not itself a code. Everything else is a data row and is
    classified as one — which is what keeps a row that carries only a
    description from being read as a Category nobody wrote.
    """
    filled = [
        (column, cell)
        for column, cell in row.cells.items()
        if cell.text.strip() and not cell.uncomputed
    ]
    if len(filled) != 1:
        return None
    column, cell = filled[0]
    if column != code_column or cell.numeric:
        return None
    heading = cell.text.strip()
    return None if _split_code(heading) is not None else heading


def _authoritative_name(heading: str) -> str | None:
    wanted = _heading(heading)
    for name in AUTHORITATIVE_CATEGORY_NAMES:
        if _heading(name) == wanted:
            return name
    return None


def scan_source(reader: ConstraintSourceReader, *, register_id: str, project_id: str) -> SourceScan:
    """Read the source into typed rows and structural findings. No database.

    Reads the worksheet exactly once. A row with an uncomputed formula in a
    semantic column is an unsupported row; a row before the first section header
    is an unsupported row; a heading-only row that is not one of the seven
    authoritative names is an unsupported row. Nothing is repaired.
    """
    issues: list[RowIssue] = []
    rows: list[_RowValues] = []
    counts: dict[str, int] = {}
    order: list[str] = []
    columns: dict[str, str] = {}
    code_column = ""
    section: str | None = None
    seen_sections: set[str] = set()
    total = 0
    ignored = 0

    if reader.uses_1904_dates:
        issues.append(RowIssue(row_identity=reader.sheet_name, issue=ISSUE_DATE_SYSTEM_1904))

    for row in reader.rows():
        total += 1
        identity = f"{row.sheet_name}!{row.row_number}"
        if not columns:
            found = _header_columns(row)
            if found is None:
                ignored += 1
                continue
            columns.update(found)
            code_column = next(column for column, name in sorted(found.items()) if name == "code")
            for cell in row.cells.values():
                if _heading(cell.text) not in COLUMN_HEADINGS and cell.text.strip():
                    issues.append(
                        RowIssue(row_identity=identity, issue=ISSUE_HEADER_UNKNOWN_COLUMN)
                    )
            continue
        heading = _section_heading(row, code_column)
        if heading is not None:
            announced = _authoritative_name(heading)
            if announced is None:
                issues.append(RowIssue(row_identity=identity, issue=ISSUE_CATEGORY_UNKNOWN))
                continue
            if announced in seen_sections:
                issues.append(
                    RowIssue(row_identity=identity, issue=ISSUE_CATEGORY_DUPLICATE_SECTION)
                )
            seen_sections.add(announced)
            section = announced
            if announced not in counts:
                counts[announced] = 0
                order.append(announced)
            continue
        values, numeric, uncomputed = _row_fields(row, columns)
        if uncomputed:
            issues.append(RowIssue(row_identity=identity, issue=ISSUE_FORMULA_UNCOMPUTED))
            continue
        if not any(values.get(name, "") for name in SEMANTIC_FIELDS):
            ignored += 1
            continue
        if section is None:
            issues.append(RowIssue(row_identity=identity, issue=ISSUE_ROW_BEFORE_SECTION))
            continue
        counts[section] = counts[section] + 1
        rows.append(
            _RowValues(
                row_identity=identity,
                row_number=row.row_number,
                section=section,
                values=values,
                numeric_fields=numeric,
            )
        )

    if not columns:
        issues.append(RowIssue(row_identity=reader.sheet_name, issue=ISSUE_HEADER_ABSENT))

    return SourceScan(
        register_id=register_id,
        project_id=project_id,
        sheet_name=reader.sheet_name,
        source_digest=reader.content_digest,
        total_rows=total,
        ignored_rows=ignored,
        rows=tuple(rows),
        sections=tuple(_SectionScan(name=name, row_count=counts[name]) for name in order),
        issues=tuple(issues),
    )


def _header_columns(row: SourceRow) -> dict[str, str] | None:
    """The column-letter to field mapping this row declares, if it is the header."""
    mapping: dict[str, str] = {}
    for column, cell in row.cells.items():
        field_name = COLUMN_HEADINGS.get(_heading(cell.text))
        if field_name is not None:
            mapping[column] = field_name
    return mapping if "code" in mapping.values() and "status" in mapping.values() else None


def _row_fields(
    row: SourceRow, columns: Mapping[str, str]
) -> tuple[Mapping[str, str], frozenset[str], bool]:
    values: dict[str, str] = {}
    numeric: set[str] = set()
    uncomputed = False
    for column, cell in row.cells.items():
        field_name = columns.get(column)
        if field_name is None or field_name in DERIVED_FIELDS:
            continue
        if cell.uncomputed:
            uncomputed = True
            continue
        text = cell.text.strip()
        if not text:
            continue
        values[field_name] = text
        if cell.numeric:
            numeric.add(field_name)
    return values, frozenset(numeric), uncomputed


# --- Planning -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ResolvedRow:
    """One importable row: the report-safe summary and the values it carries.

    The values never reach a report. They exist only long enough to become a
    `ProjectConstraint`, and no field of `ImportReport` can hold one.
    """

    row_identity: str
    section: str
    classification: RowClass
    constraint_code: str
    sequence: int
    lifecycle_state: ConstraintLifecycleState
    record_quality: ConstraintRecordQuality
    idempotency_key: str
    request_digest: str
    description: str | None
    date_identified: date | None
    due_date: date | None
    reference: str | None
    current_update: str | None
    completion_date: date | None
    bic: tuple[PartyRef, ...]
    responsible: tuple[PartyRef, ...]


@dataclass(frozen=True, slots=True)
class ImportPlan:
    """A dry run's whole answer: the report, and the rows an apply would write.

    `rows` carries source values and is never rendered: `ImportReport` is the
    artefact, and it has no field a value could be put in.
    """

    report: ImportReport
    rows: tuple[_ResolvedRow, ...] = ()
    categories: Mapping[str, CategoryPlan] = field(default_factory=dict)


def _excel_date(text: str, *, numeric: bool) -> date | None:
    """One workbook date cell as a `date`, or `None` when it cannot be read.

    Two readings and no third. An ISO text cell is parsed as written; a
    numerically-typed cell is a 1900-system serial. A serial at or below 60 sits
    inside the 1900 leap-year bug and is refused rather than guessed at.
    """
    if numeric:
        try:
            serial = int(float(text))
        except ValueError:
            return None
        if serial <= _AMBIGUOUS_SERIAL_LIMIT or serial > _MAX_SERIAL:
            return None
        return _EXCEL_EPOCH + timedelta(days=serial)
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _split_code(code: str) -> tuple[str, str] | None:
    """`2.01` as `("2", "01")`. The sequence keeps its text; nothing becomes a float."""
    prefix, separator, sequence = code.partition(_CODE_SEPARATOR)
    if not separator or not prefix or not sequence:
        return None
    if not sequence.isdigit() or not CONSTRAINT_CATEGORY_PREFIX_PATTERN.match(prefix):
        return None
    return prefix, sequence


def _party(text: str, party_map: Mapping[str, str], known_entities: frozenset[str]) -> PartyRef:
    """One party cell as a reference, without a single guess.

    An entity is claimed only when the operator's explicit map names this exact
    source wording, and only when that identity is in this Principal's own
    partition. Everything else is `UNRESOLVED`, carrying the source wording,
    which is exactly what that kind exists for. No substring, name or address
    heuristic is used anywhere in this module.
    """
    entity_id = party_map.get(text)
    if entity_id is not None and entity_id in known_entities:
        return PartyRef(kind=PartyKind.ENTITY, entity_id=entity_id, label=text)
    return PartyRef(kind=PartyKind.UNRESOLVED, label=text)


def _observed_prefixes(scan: SourceScan) -> Mapping[str, str]:
    """The one code prefix each section's own rows establish.

    The most frequent readable prefix under the section wins, with ties broken
    by sort order so the answer is deterministic. A section whose rows carry no
    readable code establishes no prefix and therefore proposes no Category:
    inventing one would be inventing the very text no accepted source carries.
    """
    counted: dict[str, dict[str, int]] = {}
    for row in scan.rows:
        split = _split_code(row.values.get("code", ""))
        if split is None:
            continue
        tally = counted.setdefault(row.section, {})
        tally[split[0]] = tally.get(split[0], 0) + 1
    return {
        section: min(tally, key=lambda prefix: (-tally[prefix], prefix))
        for section, tally in counted.items()
    }


def plan_import(
    scan: SourceScan,
    *,
    existing_categories: Sequence[CategoryPlan] = (),
    existing_codes: frozenset[str] = frozenset(),
    already_imported: Mapping[str, str] = MappingProxyType({}),
    canonical_page_truncated: bool = False,
    party_map: Mapping[str, str] | None = None,
    known_entities: frozenset[str] = frozenset(),
    mode: str,
    generated_at: datetime,
    applied: int = 0,
    replayed: int = 0,
) -> ImportPlan:
    """Turn a scan into a bounded report and the rows an apply would write.

    Pure: it reads no database and writes nothing. Everything the database
    contributes — the Project's Categories, the codes already canonical, which
    Entity identities exist — arrives as an argument, so the whole classification
    can be proved without a server.
    """
    mapping = dict(party_map or {})
    issues: list[RowIssue] = list(scan.issues)
    resolved: list[_ResolvedRow] = []
    class_counts = {member.value: 0 for member in RowClass}
    class_counts[RowClass.C_IGNORED.value] = scan.ignored_rows
    lifecycle_counts: dict[str, int] = {}
    sequences: dict[str, list[int]] = {}
    seen_codes: set[str] = set()
    unresolved_parties = 0
    resolved_parties = 0
    no_ops = 0

    #: The prefix a section's own codes establish. Read from the source and
    #: never invented: the accepted definition enumerates the seven Category
    #: names and says the prefixes exist, and enumerates no prefix text.
    section_prefix = _observed_prefixes(scan)

    for row in scan.rows:
        outcome = _resolve_row(row, mapping, known_entities)
        if isinstance(outcome, RowIssue):
            issues.append(outcome)
            class_counts[RowClass.UNSUPPORTED.value] += 1
            continue
        candidate, row_issues = outcome
        issues.extend(row_issues)
        candidate = replace(
            candidate,
            idempotency_key=row_idempotency_key(
                scan.register_id, scan.project_id, row.row_identity
            ),
            request_digest=row_request_digest(row.values, row.section),
        )
        stored = already_imported.get(candidate.idempotency_key)
        if stored is not None:
            seen_codes.add(candidate.constraint_code)
            if stored == candidate.request_digest:
                # The receipt says this row is already canonical, unchanged. It
                # writes nothing, consumes no allocator sequence, and is not a
                # collision with the record it *is*.
                class_counts[candidate.classification.value] += 1
                no_ops += 1
                continue
            issues.append(
                RowIssue(
                    row_identity=row.row_identity,
                    issue=ISSUE_IDEMPOTENCY_COLLISION,
                    constraint_code=candidate.constraint_code,
                )
            )
            class_counts[RowClass.UNSUPPORTED.value] += 1
            continue
        prefix, _ = candidate.constraint_code.split(_CODE_SEPARATOR, 1)
        if prefix != section_prefix.get(row.section):
            issues.append(
                RowIssue(
                    row_identity=row.row_identity,
                    issue=ISSUE_CODE_PREFIX_MISMATCH,
                    constraint_code=candidate.constraint_code,
                )
            )
            class_counts[RowClass.UNSUPPORTED.value] += 1
            continue
        if candidate.constraint_code in seen_codes:
            issues.append(
                RowIssue(
                    row_identity=row.row_identity,
                    issue=ISSUE_CODE_DUPLICATE,
                    constraint_code=candidate.constraint_code,
                )
            )
            class_counts[RowClass.UNSUPPORTED.value] += 1
            continue
        if candidate.constraint_code in existing_codes:
            issues.append(
                RowIssue(
                    row_identity=row.row_identity,
                    issue=ISSUE_CODE_COLLIDES_WITH_CANONICAL,
                    constraint_code=candidate.constraint_code,
                )
            )
            class_counts[RowClass.UNSUPPORTED.value] += 1
            continue
        seen_codes.add(candidate.constraint_code)
        sequences.setdefault(row.section, []).append(candidate.sequence)
        class_counts[candidate.classification.value] += 1
        state = candidate.lifecycle_state.value
        lifecycle_counts[state] = lifecycle_counts.get(state, 0) + 1
        for party in candidate.bic + candidate.responsible:
            if party.kind is PartyKind.UNRESOLVED:
                unresolved_parties += 1
            else:
                resolved_parties += 1
        resolved.append(candidate)

    existing_by_name = {plan.name: plan for plan in existing_categories}
    existing_by_prefix = {plan.prefix: plan for plan in existing_categories}
    categories: dict[str, CategoryPlan] = {}
    for section in scan.sections:
        observed = section_prefix.get(section.name)
        if observed is None:
            continue
        found = sorted(sequences.get(section.name, []))
        highest = found[-1] if found else None
        current = existing_by_name.get(section.name)
        clashing = existing_by_prefix.get(observed)
        if (clashing is not None and clashing.name != section.name) or (
            current is not None and current.prefix != observed
        ):
            issues.append(
                RowIssue(row_identity=section.name, issue=ISSUE_CATEGORY_PREFIX_COLLISION)
            )
        floor = 1 if current is None else current.proposed_next_sequence
        issued = 0 if current is None else current.proposed_issued_count
        for sequence in found:
            if current is not None and sequence < floor:
                issues.append(
                    RowIssue(
                        row_identity=section.name,
                        issue=ISSUE_CODE_WITHIN_ISSUED_RANGE,
                        constraint_code=f"{observed}{_CODE_SEPARATOR}{sequence}",
                    )
                )
        categories[section.name] = CategoryPlan(
            name=section.name,
            prefix=observed,
            row_count=len(found),
            max_imported_sequence=highest,
            proposed_next_sequence=max(floor, (highest or 0) + 1),
            proposed_issued_count=issued + len(found),
            existing_category_id=None if current is None else current.existing_category_id,
            existing_next_sequence=None if current is None else current.proposed_next_sequence,
            existing_version=None if current is None else current.existing_version,
        )

    if canonical_page_truncated:
        issues.append(RowIssue(row_identity=scan.sheet_name, issue=ISSUE_CANONICAL_PAGE_TRUNCATED))

    blockers = sorted({issue.issue for issue in issues} & _BLOCKING_ISSUES)
    attention = {
        ConstraintRecordQuality.LEGACY_INCOMPLETE.value: class_counts[
            RowClass.B_LEGACY_INCOMPLETE.value
        ],
        ConstraintRecordQuality.NORMAL.value: class_counts[RowClass.A_COMPLETE.value],
    }
    report = ImportReport(
        tool=TOOL_CLIENT_CONTEXT,
        mode=mode,
        register_id=scan.register_id,
        project_id=scan.project_id,
        sheet_name=scan.sheet_name,
        source_digest=scan.source_digest,
        generated_at=generated_at.astimezone(UTC).isoformat(),
        total_source_rows=scan.total_rows,
        class_counts=dict(sorted(class_counts.items())),
        lifecycle_counts=dict(sorted(lifecycle_counts.items())),
        category_plans=tuple(categories[name] for name in sorted(categories)),
        attention_counts=attention,
        unresolved_party_count=unresolved_parties,
        resolved_party_count=resolved_parties,
        planned_inserts=len(resolved),
        planned_no_ops=no_ops,
        issues=tuple(issues),
        blockers=tuple(blockers),
        disposition=ImportDisposition.BLOCKED if blockers else ImportDisposition.READY,
        applied=applied,
        replayed=replayed,
    )
    return ImportPlan(report=report, rows=tuple(resolved), categories=categories)


#: The findings that stop an apply. Everything else is reported and survivable:
#: an unsupported row imports nothing and blocks nothing, which is what lets a
#: partially-clean register be imported without repairing it first.
_BLOCKING_ISSUES: Final[frozenset[str]] = frozenset(
    {
        ISSUE_HEADER_ABSENT,
        ISSUE_DATE_SYSTEM_1904,
        ISSUE_CATEGORY_PREFIX_COLLISION,
        ISSUE_CODE_WITHIN_ISSUED_RANGE,
        ISSUE_CODE_COLLIDES_WITH_CANONICAL,
        ISSUE_IDEMPOTENCY_COLLISION,
        ISSUE_CANONICAL_PAGE_TRUNCATED,
        ISSUE_PARTY_FOREIGN_ENTITY,
    }
)


def _resolve_row(
    row: _RowValues, party_map: Mapping[str, str], known_entities: frozenset[str]
) -> RowIssue | tuple[_ResolvedRow, tuple[RowIssue, ...]]:
    """One source row as an importable record, or the one finding that stops it."""
    values = row.values
    code = values.get("code", "")
    if not code:
        return RowIssue(row_identity=row.row_identity, issue=ISSUE_CODE_MISSING)
    if "code" in row.numeric_fields:
        return RowIssue(
            row_identity=row.row_identity, issue=ISSUE_CODE_NUMERIC_CELL, constraint_code=code
        )
    split = _split_code(code)
    if split is None:
        return RowIssue(
            row_identity=row.row_identity, issue=ISSUE_CODE_GRAMMAR, constraint_code=code
        )
    status = values.get("status", "")
    if not status:
        return RowIssue(
            row_identity=row.row_identity, issue=ISSUE_STATUS_MISSING, constraint_code=code
        )
    state = WORKBOOK_STATUS_VOCABULARY.get(_heading(status))
    if state is None:
        return RowIssue(
            row_identity=row.row_identity, issue=ISSUE_STATUS_UNKNOWN, constraint_code=code
        )
    if state is ConstraintLifecycleState.VOID:
        return RowIssue(
            row_identity=row.row_identity,
            issue=ISSUE_VOID_FIELDS_UNAVAILABLE,
            constraint_code=code,
        )

    issues: list[RowIssue] = []
    dates: dict[str, date | None] = {}
    for name in ("date_identified", "due_date", "completion_date"):
        text = values.get(name, "")
        if not text:
            dates[name] = None
            continue
        parsed = _excel_date(text, numeric=name in row.numeric_fields)
        if parsed is None:
            issues.append(
                RowIssue(
                    row_identity=row.row_identity,
                    issue=ISSUE_DATE_UNREADABLE,
                    constraint_code=code,
                )
            )
        dates[name] = parsed

    if state is ConstraintLifecycleState.CLOSED and dates["completion_date"] is None:
        return RowIssue(
            row_identity=row.row_identity,
            issue=ISSUE_CLOSED_WITHOUT_COMPLETION,
            constraint_code=code,
        )

    bic = tuple(
        _party(values[name], party_map, known_entities) for name in ("bic",) if values.get(name)
    )
    responsible = tuple(
        _party(values[name], party_map, known_entities)
        for name in ("responsible",)
        if values.get(name)
    )
    for name in ("bic", "responsible"):
        wording = values.get(name, "")
        mapped = party_map.get(wording)
        if wording and mapped is not None and mapped not in known_entities:
            issues.append(
                RowIssue(
                    row_identity=row.row_identity,
                    issue=ISSUE_PARTY_FOREIGN_ENTITY,
                    constraint_code=code,
                )
            )

    resolved = _ResolvedRow(
        row_identity=row.row_identity,
        section=row.section,
        classification=RowClass.A_COMPLETE,
        constraint_code=code,
        sequence=int(split[1]),
        lifecycle_state=state,
        record_quality=ConstraintRecordQuality.NORMAL,
        idempotency_key="",
        request_digest="",
        description=values.get("description"),
        date_identified=dates["date_identified"],
        due_date=dates["due_date"],
        reference=values.get("reference"),
        current_update=values.get("comments"),
        completion_date=dates["completion_date"]
        if state is ConstraintLifecycleState.CLOSED
        else None,
        bic=bic,
        responsible=responsible,
    )
    incomplete = (
        resolved.description is None
        or not resolved.description.strip()
        or resolved.date_identified is None
        or resolved.due_date is None
        or not resolved.bic
    )
    return (
        replace(
            resolved,
            classification=(RowClass.B_LEGACY_INCOMPLETE if incomplete else RowClass.A_COMPLETE),
            record_quality=(
                ConstraintRecordQuality.LEGACY_INCOMPLETE
                if incomplete
                else ConstraintRecordQuality.NORMAL
            ),
        ),
        tuple(issues),
    )


# --- Rendering ----------------------------------------------------------------


def report_as_dict(report: ImportReport) -> dict[str, object]:
    """The report as plain JSON-ready data, field by field.

    Written out rather than produced by `asdict` so that a field added to a
    dataclass has to be added here too: an automatic walk would carry a new
    field into the artefact before anyone had decided it was safe to publish.
    """
    return {
        "tool": report.tool,
        "mode": report.mode,
        "registerId": report.register_id,
        "projectId": report.project_id,
        "sheetName": report.sheet_name,
        "sourceDigest": report.source_digest,
        "generatedAt": report.generated_at,
        "totalSourceRows": report.total_source_rows,
        "classCounts": dict(report.class_counts),
        "lifecycleCounts": dict(report.lifecycle_counts),
        "attentionCounts": dict(report.attention_counts),
        "unresolvedPartyCount": report.unresolved_party_count,
        "resolvedPartyCount": report.resolved_party_count,
        "plannedInserts": report.planned_inserts,
        "plannedNoOps": report.planned_no_ops,
        "applied": report.applied,
        "replayed": report.replayed,
        "categories": [
            {
                "name": plan.name,
                "prefix": plan.prefix,
                "rowCount": plan.row_count,
                "maxImportedSequence": plan.max_imported_sequence,
                "proposedNextSequence": plan.proposed_next_sequence,
                "proposedIssuedCount": plan.proposed_issued_count,
                "existingCategoryId": plan.existing_category_id,
                "existingNextSequence": plan.existing_next_sequence,
            }
            for plan in report.category_plans
        ],
        "issues": [
            {
                "rowIdentity": issue.row_identity,
                "issue": issue.issue,
                "constraintCode": issue.constraint_code,
            }
            for issue in report.issues
        ],
        "blockers": list(report.blockers),
        "disposition": report.disposition.value,
    }


def _table(headings: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headings) + " |",
        "|" + "|".join("---" for _ in headings) + "|",
    ]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return lines


def render_markdown(report: ImportReport) -> str:
    """The same report a reviewer reads, from the same values the JSON carries."""
    lines = [
        "# TBR Constraint import — " + report.mode,
        "",
        f"**Disposition: {report.disposition.value.upper()}.**",
        "",
        *_table(
            ("field", "value"),
            (
                ("tool", report.tool),
                ("register", report.register_id),
                ("project", report.project_id),
                ("sheet", report.sheet_name),
                ("source digest", report.source_digest),
                ("generated at", report.generated_at),
                ("total source rows", report.total_source_rows),
                ("planned inserts", report.planned_inserts),
                ("planned no-ops", report.planned_no_ops),
                ("applied", report.applied),
                ("replayed", report.replayed),
            ),
        ),
        "",
        "## Classification",
        "",
        *_table(("class", "rows"), sorted(report.class_counts.items())),
        "",
        "## Lifecycle",
        "",
        *_table(("state", "rows"), sorted(report.lifecycle_counts.items())),
        "",
        "## Record quality",
        "",
        *_table(("quality", "rows"), sorted(report.attention_counts.items())),
        "",
        "## Parties",
        "",
        *_table(
            ("kind", "count"),
            (
                ("unresolved", report.unresolved_party_count),
                ("entity", report.resolved_party_count),
            ),
        ),
        "",
        "## Categories",
        "",
        *_table(
            (
                "name",
                "prefix",
                "rows",
                "max imported sequence",
                "proposed next sequence",
                "proposed issued count",
            ),
            [
                (
                    plan.name,
                    plan.prefix,
                    plan.row_count,
                    "-" if plan.max_imported_sequence is None else plan.max_imported_sequence,
                    plan.proposed_next_sequence,
                    plan.proposed_issued_count,
                )
                for plan in report.category_plans
            ],
        ),
        "",
        "## Findings",
        "",
    ]
    if report.issues:
        lines.extend(
            _table(
                ("row", "issue", "code"),
                [
                    (issue.row_identity, issue.issue, issue.constraint_code or "-")
                    for issue in report.issues
                ],
            )
        )
    else:
        lines.append("No structural finding.")
    lines.extend(["", "## Blockers", ""])
    if report.blockers:
        lines.extend(f"- `{blocker}`" for blocker in report.blockers)
    else:
        lines.append("None.")
    lines.append("")
    lines.append(
        "Counts, identifiers, codes, prefixes and issue codes only. No workbook "
        "narrative, description, comment, party label, closure note or void reason "
        "appears in this report."
    )
    return "\n".join(lines) + "\n"


# --- The service --------------------------------------------------------------


class ConstraintLegacyImportService:
    """Dry-run and disposable apply. There is no third mode and no real target.

    The unit of work is a factory, exactly as the product mutation plane takes
    one, and the clock is injected so a run is reproducible. Nothing here opens a
    connection, chooses a database, or names one.
    """

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], ConstraintManagementUnitOfWork],
        clock: Callable[[], datetime],
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def dry_run(
        self,
        *,
        principal_id: str,
        project_id: str,
        register_id: str,
        reader: ConstraintSourceReader,
        party_map: Mapping[str, str] | None = None,
    ) -> LegacyImportOutcome:
        """Read everything, decide everything, write nothing.

        The transaction is left by exception on purpose. No statement on this
        path is a write, and raising on the way out means the claim does not
        depend on that remaining true: the transaction can only roll back.
        """
        scan = scan_source(reader, register_id=register_id, project_id=project_id)
        plan: ImportPlan | None = None
        try:
            with self._unit_of_work() as uow:
                plan = self._plan(
                    uow,
                    principal_id=principal_id,
                    project_id=project_id,
                    scan=scan,
                    party_map=party_map,
                    mode="dry-run",
                )
                raise _DryRunRollbackError
        except _DryRunRollbackError:
            pass
        if plan is None:  # pragma: no cover - the block above always assigns first
            raise LegacyImportError("legacy_import_dry_run_empty", "the dry run produced no plan")
        return LegacyImportOutcome(report=plan.report)

    def apply_disposable(
        self,
        *,
        principal_id: str,
        project_id: str,
        register_id: str,
        reader: ConstraintSourceReader,
        party_map: Mapping[str, str] | None = None,
        before_write: Callable[[], None] | None = None,
    ) -> LegacyImportOutcome:
        """One bounded transaction: seed the Categories, write the records, or nothing.

        A blocked plan writes nothing at all and raises, so a register with a
        code collision or a reused import identity cannot be half-imported. A row
        whose import identity is already recorded with the same digest is a
        replay: it writes nothing and consumes no allocator sequence.

        `before_write` is a test seam and nothing else. It is called once, inside
        the transaction and before the first record write, so a recovery test can
        raise from it and prove the batch leaves nothing behind.
        """
        scan = scan_source(reader, register_id=register_id, project_id=project_id)
        with self._unit_of_work() as uow:
            plan = self._plan(
                uow,
                principal_id=principal_id,
                project_id=project_id,
                scan=scan,
                party_map=party_map,
                mode="apply-disposable",
            )
            if ISSUE_IDEMPOTENCY_COLLISION in plan.report.blockers:
                raise LegacyImportIdempotencyConflictError(
                    ISSUE_IDEMPOTENCY_COLLISION,
                    "a source row's import identity is already recorded for other content",
                )
            if plan.report.blockers:
                raise LegacyImportError(
                    "legacy_import_blocked",
                    f"the plan is blocked by {len(plan.report.blockers)} finding(s)",
                )
            now = self._clock().astimezone(UTC)
            pending = plan.rows
            if before_write is not None:
                before_write()
            # A run whose every row is a replay writes nothing at all — not even
            # an idempotent Category update, which would still be a row written
            # by an operation whose answer is "this already happened".
            category_ids = (
                self._seed_categories(
                    uow, principal_id=principal_id, project_id=project_id, plan=plan, now=now
                )
                if pending
                else {}
            )
            for row in pending:
                self._write_row(
                    uow,
                    principal_id=principal_id,
                    project_id=project_id,
                    category_id=category_ids[row.section],
                    row=row,
                    now=now,
                )
            report = replace(plan.report, applied=len(pending), replayed=plan.report.planned_no_ops)
        return LegacyImportOutcome(report=report)

    # --- Seams and helpers ------------------------------------------------

    def _plan(
        self,
        uow: ConstraintManagementUnitOfWork,
        *,
        principal_id: str,
        project_id: str,
        scan: SourceScan,
        party_map: Mapping[str, str] | None,
        mode: str,
    ) -> ImportPlan:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(project_id, IdKind.PROJECT)
        settings = uow.constraints.get_project_settings(principal_id, project_id)
        if settings is None:
            raise LegacyImportProjectUnavailableError(
                "legacy_import_project_unavailable",
                "the project is not available to this principal",
            )
        now = self._clock().astimezone(UTC)
        # Raises `ProjectTimezoneError` when the stored zone is missing or not an
        # IANA name. There is no workstation or server fallback on this path.
        today = project_today(now, settings.timezone_name)
        existing = tuple(
            CategoryPlan(
                name=row.title,
                prefix=row.prefix,
                row_count=0,
                max_imported_sequence=None,
                proposed_next_sequence=row.next_sequence,
                proposed_issued_count=row.issued_count,
                existing_category_id=row.category_id,
                existing_next_sequence=row.next_sequence,
                existing_version=row.version,
            )
            for row in uow.constraints.list_categories(principal_id, project_id)
        )
        query = ConstraintListQuery(scope=ConstraintListScope.ALL, limit=MAX_LIST_LIMIT)
        page = uow.constraints.list_constraints(
            principal_id,
            project_id,
            spec=ConstraintListSpec(
                query=query,
                as_of=now,
                project_today=today,
                due_soon_through=today,
                fetch_limit=query.limit + 1,
            ),
        )
        mapping = dict(party_map or {})
        known = (
            frozenset(uow.constraints.entity_labels(principal_id, sorted(set(mapping.values()))))
            if mapping
            else frozenset()
        )
        keys = {
            row.row_identity: row_idempotency_key(
                scan.register_id, scan.project_id, row.row_identity
            )
            for row in scan.rows
        }
        recorded: dict[str, str] = {}
        for key in keys.values():
            entry = uow.constraints.find_history_by_idempotency_key(principal_id, key)
            if entry is not None and entry.request_digest is not None:
                recorded[key] = entry.request_digest
        plan = plan_import(
            scan,
            existing_categories=existing,
            already_imported=recorded,
            existing_codes=frozenset(
                record.constraint_code for record in page if record.constraint_code is not None
            ),
            canonical_page_truncated=len(page) > query.limit,
            party_map=mapping,
            known_entities=known,
            mode=mode,
            generated_at=now,
        )
        return plan

    def _seed_categories(
        self,
        uow: ConstraintManagementUnitOfWork,
        *,
        principal_id: str,
        project_id: str,
        plan: ImportPlan,
        now: datetime,
    ) -> Mapping[str, str]:
        """Create or advance each Category, with its allocator seeded above the import.

        `insert_category` and `update_category` already take `next_sequence` and
        `issued_count`, so no new persistence API exists for this. The prefix is
        locked on creation because historical public codes exist for it, which is
        what the accepted seeding rule asks for.
        """
        identifiers: dict[str, str] = {}
        for order, name in enumerate(sorted(plan.categories)):
            entry = plan.categories[name]
            if entry.existing_category_id is None:
                category = ConstraintCategory(
                    category_id=issue_identifier(IdKind.CONSTRAINT_CATEGORY),
                    principal_id=principal_id,
                    project_id=project_id,
                    prefix=entry.prefix,
                    title=entry.name,
                    state=ConstraintCategoryState.ACTIVE,
                    created_at=now,
                    updated_at=now,
                    display_order=order,
                    prefix_locked_at=now,
                )
                uow.constraints.insert_category(
                    principal_id,
                    category,
                    next_sequence=entry.proposed_next_sequence,
                    issued_count=entry.proposed_issued_count,
                )
                identifiers[name] = category.category_id
                continue
            current = uow.constraints.get_category_for_update(
                principal_id, entry.existing_category_id
            )
            if current is None:
                raise LegacyImportError(
                    "legacy_import_category_vanished",
                    "a category listed for this project could not be locked",
                )
            uow.constraints.update_category(
                principal_id,
                replace(current, updated_at=now),
                next_sequence=entry.proposed_next_sequence,
                issued_count=entry.proposed_issued_count,
                version=(entry.existing_version or 1) + 1,
            )
            identifiers[name] = entry.existing_category_id
        return identifiers

    def _write_row(
        self,
        uow: ConstraintManagementUnitOfWork,
        *,
        principal_id: str,
        project_id: str,
        category_id: str,
        row: _ResolvedRow,
        now: datetime,
    ) -> None:
        """One imported record, its initial revision and its receipt. All three or none.

        The write order is the product plane's: the record names the revision it
        is about to get, the receipt is appended, and the revision closes the
        cycle. `published_at` is the instant this record entered the canonical
        register, which is a fact about the import and not a workbook value —
        the workbook holds no publication timestamp, and inventing one would be
        exactly what this module refuses to do everywhere else.
        """
        constraint = ProjectConstraint(
            constraint_id=issue_identifier(IdKind.PROJECT_CONSTRAINT),
            principal_id=principal_id,
            lifecycle_state=row.lifecycle_state,
            origin=ConstraintOrigin.LEGACY_WORKBOOK_IMPORT,
            created_at=now,
            updated_at=now,
            version=1,
            project_id=project_id,
            category_id=category_id,
            constraint_code=row.constraint_code,
            description=row.description,
            date_identified=row.date_identified,
            due_date=row.due_date,
            reference=row.reference,
            current_update=row.current_update,
            bic=row.bic,
            responsible=row.responsible,
            completion_date=row.completion_date,
            record_quality=row.record_quality,
            published_at=now,
        )
        revision_id = issue_identifier(IdKind.PROJECT_CONSTRAINT_REVISION)
        uow.constraints.insert_constraint(principal_id, constraint, current_revision_id=revision_id)
        receipt = ConstraintHistoryEntry(
            history_id=issue_identifier(IdKind.PROJECT_CONSTRAINT_HISTORY),
            principal_id=principal_id,
            constraint_id=constraint.constraint_id,
            operation=ConstraintMutationOperation.CREATE,
            actor=ConstraintMutationActor.SYSTEM,
            outcome=ConstraintMutationOutcome.APPLIED,
            before_version=0,
            after_version=constraint.version,
            occurred_at=now,
            recorded_at=now,
            project_id=project_id,
            revision_id=revision_id,
            idempotency_key=row.idempotency_key,
            request_digest=row.request_digest,
            client_context=TOOL_CLIENT_CONTEXT,
        )
        uow.constraints.insert_history(principal_id, receipt)
        uow.constraints.insert_revision(
            principal_id,
            ConstraintRevision.from_constraint(
                constraint,
                revision_id=revision_id,
                history_id=receipt.history_id,
                recorded_at=now,
            ),
        )
