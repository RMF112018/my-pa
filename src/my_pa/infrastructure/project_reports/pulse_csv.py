"""The exported-report CSV reader, the header-signature registry and the 15 adapters.

This is the **only** module that names the export provider's header strings
(WP3P rulings, plan section 12.2). Everything else in the project-reports slice
works on closed field keys.

Three steps, each pure (no IO, no clock, no database):

1. **Read** (`prepare_export`). Size at most `MAX_EXPORT_BYTES`; strict UTF-8
   (`not_utf8`); a byte-order mark recorded and stripped for parsing; no NUL
   (`nul_byte`); a strict RFC 4180 state machine (comma, double quotes,
   doubled quotes, CR/LF/CRLF inside quotes, a record ending at an unquoted CR,
   LF or CRLF; an unterminated quote or a quote inside an unquoted field is
   `malformed_csv`); a non-empty header of unique, non-empty cells
   (`invalid_header`). An oversize file is not a rejection code: the lifecycle
   skips it (`skipped_too_large`), so it raises `ExportTooLargeError`.
2. **Layer A plan** (`LayerAPlan`). Every record with its exact raw text, its
   terminator and its cells, so the BOM plus every `raw + terminator`
   re-encodes to the input bytes. That is asserted before a plan is returned
   (`ReconstructionError` otherwise).
3. **Derivation plan** (`derive`). The header signature chooses the adapter;
   the filename is never an input. An unregistered signature, more than 1 %
   malformed rows, or a project-number cross-check mismatch (ruling D11)
   quarantines the derivation with every Layer A row kept and none classified.
   Otherwise every data row gets its role, every detail row becomes a typed
   line over the view's closed field catalogue, and every stated total is
   reconciled in both evidence units.

Diagnostics carry codes, record numbers and byte offsets only, never content.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.project_reports.identity import (
    RecordIdentity,
    RecordKeyKind,
    normalize_whitespace,
    record_identity,
)
from my_pa.domain.project_reports.measures import classify_status
from my_pa.domain.project_reports.model import (
    FAMILY_OF_VIEW,
    Additivity,
    CompletenessClass,
    DerivationState,
    FamilyView,
    IdentityState,
    LineKind,
    ObservationState,
    QuarantineReason,
    ReconciliationOutcome,
    RecordFamily,
    RejectionCode,
    RowReason,
    RowRole,
    StatusClass,
    ValueKind,
)
from my_pa.domain.project_reports.money import (
    AmountRefusedError,
    NumericCell,
    parse_decimal,
    parse_money,
    read_cell,
)
from my_pa.domain.project_reports.reconciliation import (
    BLANK_GROUP_KEY,
    CrossReportCheck,
    ReconciliationSummary,
    StatedTotalCheck,
    TotalColumn,
    cross_report_check,
    reconcile_totals,
    summarize,
)
from my_pa.domain.project_reports.roles import (
    ClassifiedRow,
    GroupKeys,
    classify_rows,
    completeness_class,
    malformed_ratio_exceeded,
    quarantined_role_counts,
    role_counts,
)
from my_pa.domain.project_reports.signature import header_refusal, header_signature

__all__ = [
    "ADAPTER_VERSION",
    "MAX_EXPORT_BYTES",
    "READER_VERSION",
    "REGISTRY",
    "STATUS_MAP_VERSION",
    "DerivationPlan",
    "ExportRejectedError",
    "ExportTooLargeError",
    "FamilyAdapter",
    "FieldSpec",
    "LayerAPlan",
    "LinePlan",
    "RawRecord",
    "ReconstructionError",
    "Terminator",
    "TypedValue",
    "carries_project_number",
    "derive",
    "pair_cross_report",
    "prepare_export",
    "project_number_cross_check",
]

READER_VERSION: Final = "pulse_csv_reader_v1"
ADAPTER_VERSION: Final = "pulse_adapter_v1"
STATUS_MAP_VERSION: Final = "status_map_v1"
#: Ruling D17: 16 MiB (the largest real export is far below it).
MAX_EXPORT_BYTES: Final = 16 * 1024 * 1024
_BOM: Final = b"\xef\xbb\xbf"


# --------------------------------------------------------------------------
# 1. The reader
# --------------------------------------------------------------------------


class Terminator(StrEnum):
    CRLF = "crlf"
    LF = "lf"
    CR = "cr"
    #: Only the last record of a file may have none.
    NONE = "none"


_TERMINATOR_TEXT: Final = MappingProxyType(
    {Terminator.CRLF: "\r\n", Terminator.LF: "\n", Terminator.CR: "\r", Terminator.NONE: ""}
)


class ExportRejectedError(ValueError):
    """The whole file is refused: a closed code plus record number and byte offset only."""

    def __init__(self, code: RejectionCode, *, record: int | None, offset: int | None) -> None:
        super().__init__(code.value)
        self.code = code
        self.record = record
        self.offset = offset


class ExportTooLargeError(ValueError):
    """Over `MAX_EXPORT_BYTES`: skipped by the lifecycle, never read."""


class ReconstructionError(AssertionError):
    """The planned records do not re-encode to the input bytes (a reader defect)."""


@dataclass(frozen=True, slots=True)
class RawRecord:
    """One physical CSV record; `ordinal` 0 is the header, data rows count from 1."""

    ordinal: int
    raw_record: str
    terminator: Terminator
    cells: tuple[str, ...]
    byte_offset: int
    #: Line breaks inside quoted fields, by kind.
    embedded_crlf: int = 0
    embedded_lf: int = 0
    embedded_cr: int = 0

    @property
    def embedded_line_breaks(self) -> int:
        return self.embedded_crlf + self.embedded_lf + self.embedded_cr


_UNQUOTED_END: Final = re.compile(r'[,\r\n"]')


def _breaks(chunk: str) -> tuple[int, int, int]:
    crlf = chunk.count("\r\n")
    return crlf, chunk.count("\n") - crlf, chunk.count("\r") - crlf


def _malformed(record: int, offset: int) -> ExportRejectedError:
    return ExportRejectedError(RejectionCode.MALFORMED_CSV, record=record, offset=offset)


def _split_records(text: str, base_offset: int) -> list[RawRecord]:
    records: list[RawRecord] = []
    n = len(text)
    i = 0
    offset = base_offset
    while i < n:
        start = i
        cells: list[str] = []
        crlf = lf = cr = 0

        while True:
            if i < n and text[i] == '"':
                i += 1
                parts: list[str] = []
                while True:
                    j = text.find('"', i)
                    if j < 0:
                        raise _malformed(len(records), offset)
                    chunk = text[i:j]
                    parts.append(chunk)
                    a, b, c = _breaks(chunk)
                    crlf, lf, cr = crlf + a, lf + b, cr + c
                    if j + 1 < n and text[j + 1] == '"':
                        parts.append('"')
                        i = j + 2
                        continue
                    i = j + 1
                    break
                if i < n and text[i] not in ",\r\n":
                    raise _malformed(len(records), offset)
                cells.append("".join(parts))
            else:
                match = _UNQUOTED_END.search(text, i)
                end = n if match is None else match.start()
                if end < n and text[end] == '"':
                    raise _malformed(len(records), offset)
                cells.append(text[i:end])
                i = end
            if i < n and text[i] == ",":
                i += 1
                continue
            break
        raw = text[start:i]
        if i >= n:
            terminator = Terminator.NONE
        elif text[i] == "\r":
            if i + 1 < n and text[i + 1] == "\n":
                terminator, i = Terminator.CRLF, i + 2
            else:
                terminator, i = Terminator.CR, i + 1
        else:
            terminator, i = Terminator.LF, i + 1
        records.append(RawRecord(len(records), raw, terminator, tuple(cells), offset, crlf, lf, cr))
        offset += len((raw + _TERMINATOR_TEXT[terminator]).encode("utf-8"))
    return records


@dataclass(frozen=True, slots=True)
class LayerAPlan:
    """The raw, classification-free image of one export (ruling D1)."""

    reader_version: str
    file_sha256: str
    byte_count: int
    bom_present: bool
    header: RawRecord
    rows: tuple[RawRecord, ...]
    signature: str

    @property
    def records(self) -> tuple[RawRecord, ...]:
        return (self.header, *self.rows)

    def reconstruct(self) -> bytes:
        body = "".join(r.raw_record + _TERMINATOR_TEXT[r.terminator] for r in self.records)
        return (_BOM if self.bom_present else b"") + body.encode("utf-8")

    @property
    def reconstruction_sha256(self) -> str:
        return hashlib.sha256(self.reconstruct()).hexdigest()


def _assert_reconstructs(plan: LayerAPlan) -> None:
    if plan.reconstruction_sha256 != plan.file_sha256:
        raise ReconstructionError("the planned records do not reconstruct the file")
    for record in plan.records[:-1]:
        if record.terminator is Terminator.NONE:
            raise ReconstructionError("only the last record may lack a terminator")


def prepare_export(data: bytes) -> LayerAPlan:
    """The Layer A plan of one export, or a rejection (plan section 4.1, in order)."""
    if type(data) is not bytes:
        raise TypeError("an export is read as bytes")
    if len(data) > MAX_EXPORT_BYTES:
        raise ExportTooLargeError("the export exceeds MAX_EXPORT_BYTES")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ExportRejectedError(RejectionCode.NOT_UTF8, record=None, offset=error.start) from None
    bom = data.startswith(_BOM)
    if bom:
        text = text[1:]
    nul = text.find("\x00")
    if nul >= 0:
        offset = len(text[:nul].encode("utf-8")) + (len(_BOM) if bom else 0)
        raise ExportRejectedError(RejectionCode.NUL_BYTE, record=None, offset=offset)
    records = _split_records(text, len(_BOM) if bom else 0)
    if not records or header_refusal(records[0].cells) is not None:
        raise ExportRejectedError(RejectionCode.INVALID_HEADER, record=0, offset=0)
    plan = LayerAPlan(
        reader_version=READER_VERSION,
        file_sha256=hashlib.sha256(data).hexdigest(),
        byte_count=len(data),
        bom_present=bom,
        header=records[0],
        rows=tuple(records[1:]),
        signature=header_signature(records[0].cells),
    )
    _assert_reconstructs(plan)
    return plan


# --------------------------------------------------------------------------
# 2. Typed values
# --------------------------------------------------------------------------

_DATE: Final = re.compile(r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})")
_BOOLEAN: Final = MappingProxyType({"Yes": True, "No": False})

type CellValue = Decimal | date | bool | str | None


@dataclass(frozen=True, slots=True)
class TypedValue:
    """One catalogued cell: its raw text always beside its typed value."""

    field_key: str
    value_kind: ValueKind
    raw_text: str
    value: CellValue
    reason: RowReason | None = None


def _type_cell(kind: ValueKind, raw: str) -> tuple[CellValue, RowReason | None]:
    if raw == "":
        return None, None
    try:
        if kind is ValueKind.MONEY:
            return parse_money(raw), None
        if kind is ValueKind.NUMBER:
            return parse_decimal(raw), None
    except AmountRefusedError as refused:
        return None, refused.reason
    if kind is ValueKind.DATE:
        match = _DATE.fullmatch(raw)
        if match is None:
            return None, RowReason.TYPE_ERROR
        try:
            return date(int(match.group(3)), int(match.group(1)), int(match.group(2))), None
        except ValueError:
            return None, RowReason.TYPE_ERROR
    if kind is ValueKind.BOOLEAN:
        if raw not in _BOOLEAN:
            return None, RowReason.TYPE_ERROR
        return _BOOLEAN[raw], None
    return raw, None


# --------------------------------------------------------------------------
# 3. Adapters and the registry
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One column of a view's closed field catalogue."""

    column_index: int
    header: str
    field_key: str
    value_kind: ValueKind
    additivity: Additivity = Additivity.UNKNOWN


type Cells = Sequence[str]
type LineKindRule = Callable[[Cells], LineKind]
type IdentityRule = Callable[
    [Cells, ClassifiedRow, LineKind], tuple[RecordIdentity, RowReason | None]
]
type StatusRule = Callable[[Cells, ClassifiedRow, LineKind], str | None]


@dataclass(frozen=True, slots=True)
class FamilyAdapter:
    """A registry entry: `signature -> (family, view, adapter_version)` plus its rules."""

    view: FamilyView
    fields: tuple[FieldSpec, ...]
    keys: GroupKeys
    line_kinds: tuple[LineKind, ...]
    line_kind: LineKindRule
    identity: IdentityRule
    status: StatusRule | None = None
    status_exact: Mapping[str, StatusClass] = MappingProxyType({})
    status_prefixes: Mapping[str, StatusClass] = MappingProxyType({})
    #: Columns whose non-empty identifier cells must carry the bound project number (D11).
    cross_check_columns: tuple[int, ...] = ()
    adapter_version: str = ADAPTER_VERSION

    @property
    def family(self) -> RecordFamily:
        return FAMILY_OF_VIEW[self.view]

    @property
    def header(self) -> tuple[str, ...]:
        return tuple(spec.header for spec in self.fields)

    @property
    def signature(self) -> str:
        return header_signature(self.header)

    @property
    def total_columns(self) -> tuple[TotalColumn, ...]:
        return tuple(
            TotalColumn(
                spec.column_index,
                spec.field_key,
                spec.additivity,
                money=spec.value_kind is ValueKind.MONEY,
            )
            for spec in self.fields
            if spec.value_kind in (ValueKind.MONEY, ValueKind.NUMBER)
        )


def _fields(
    *specs: tuple[str, str, ValueKind, Additivity] | tuple[str, str, ValueKind],
) -> tuple[FieldSpec, ...]:
    out: list[FieldSpec] = []
    for index, spec in enumerate(specs):
        additivity = spec[3] if len(spec) == 4 else Additivity.UNKNOWN
        out.append(FieldSpec(index, spec[0], spec[1], spec[2], additivity))
    return tuple(out)


_ID = ValueKind.IDENTIFIER
_TEXT = ValueKind.TEXT
_DATE_KIND = ValueKind.DATE
_NUM = ValueKind.NUMBER
_MONEY = ValueKind.MONEY
_BOOL = ValueKind.BOOLEAN
_ADD = Additivity.ADDITIVE
_NON = Additivity.NON_ADDITIVE

#: Status maps (`status_map_v1`): only observed or exporter-defined values; the rest is `unknown`.
_OPEN_CLOSED: Final = MappingProxyType({"Open": StatusClass.OPEN, "Closed": StatusClass.CLOSED})
_APPROVAL: Final = MappingProxyType({"Approved": StatusClass.APPROVED, "Void": StatusClass.VOID})
_APPROVAL_PREFIXES: Final = MappingProxyType({"Pending": StatusClass.PENDING})


def _inherited(row: ClassifiedRow, level: int) -> str:
    for step in row.group_path:
        if step.level == level:
            return step.key
    return ""


def _constant(kind: LineKind) -> LineKindRule:
    def rule(_cells: Cells) -> LineKind:
        return kind

    return rule


def _identified(kind: RecordKeyKind, *columns: int) -> IdentityRule:
    def rule(
        cells: Cells, _row: ClassifiedRow, _line: LineKind
    ) -> tuple[RecordIdentity, RowReason | None]:
        return _with_reason(record_identity(kind, *(cells[c] for c in columns)))

    return rule


def _with_reason(identity: RecordIdentity) -> tuple[RecordIdentity, RowReason | None]:
    if identity.state is IdentityState.IDENTITY_MISSING:
        return identity, RowReason.IDENTITY_MISSING
    if identity.state is IdentityState.AMBIGUOUS_IDENTITY:
        return identity, RowReason.AMBIGUOUS_IDENTITY
    return identity, None


def _snapshot_scoped(
    _cells: Cells, _row: ClassifiedRow, _line: LineKind
) -> tuple[RecordIdentity, RowReason | None]:
    return RecordIdentity(IdentityState.SNAPSHOT_SCOPED), None


def _status_column(column: int) -> StatusRule:
    def rule(cells: Cells, _row: ClassifiedRow, _line: LineKind) -> str | None:
        return cells[column]

    return rule


def _status_level(level: int) -> StatusRule:
    def rule(_cells: Cells, row: ClassifiedRow, _line: LineKind) -> str | None:
        return _inherited(row, level)

    return rule


# --- buyout ---------------------------------------------------------------


def _buyout_line(cells: Cells) -> LineKind:
    if cells[4] != "" or cells[6] != "":
        return LineKind.COMMITMENT
    if cells[7] != "":
        return LineKind.COMMITMENT_CHANGE_ORDER
    if cells[3] != "":
        return LineKind.PRIME_CHANGE_ORDER
    if cells[2] != "":
        return LineKind.BUDGET_CHANGE
    if cells[1] != "" and cells[5] == "":
        return LineKind.BUDGET_LINE
    # A vendor with nothing but the (never loaded) original-budget cell is a
    # vendor-only line: a budget line carries no vendor (evidence inventory s3).
    return LineKind.VENDOR_ONLY


def _buyout_identity(
    cells: Cells, row: ClassifiedRow, line: LineKind
) -> tuple[RecordIdentity, RowReason | None]:
    if line is not LineKind.COMMITMENT:
        return RecordIdentity(IdentityState.SNAPSHOT_SCOPED), None
    code = _inherited(row, 1)
    if code == BLANK_GROUP_KEY:
        code = ""
    return _with_reason(record_identity(RecordKeyKind.COMMITMENT, cells[4], code))


# --- change-order reconciliation -------------------------------------------


def _reconciliation_line(cells: Cells) -> LineKind:
    if any(cells[c] != "" for c in (7, 8, 9, 10)):
        return LineKind.COMMITMENT_CO_LINE
    return LineKind.PRIME_PCO_LINE


def _reconciliation_identity(
    _cells: Cells, _row: ClassifiedRow, line: LineKind
) -> tuple[RecordIdentity, RowReason | None]:
    if line is LineKind.COMMITMENT_CO_LINE:
        return RecordIdentity(IdentityState.SNAPSHOT_SCOPED), RowReason.AMBIGUOUS_COMMITMENT_CO
    return RecordIdentity(IdentityState.SNAPSHOT_SCOPED), None


def _reconciliation_status(cells: Cells, _row: ClassifiedRow, line: LineKind) -> str | None:
    return cells[8] if line is LineKind.COMMITMENT_CO_LINE else cells[3]


# --- daily log --------------------------------------------------------------


def _manpower_identity(
    cells: Cells, row: ClassifiedRow, _line: LineKind
) -> tuple[RecordIdentity, RowReason | None]:
    return _with_reason(record_identity(RecordKeyKind.MANPOWER, _inherited(row, 1), cells[1]))


_OBSERVATION_9: Final = _fields(
    ("Observation > Assignee Company (Vendor) Name", "observation.assignee_vendor", _TEXT),
    ("Observation > Status", "observation.status", _TEXT),
    ("Observation > Count", "observation.count", _NUM, _NON),
    ("Observation > Date Created", "observation.date_created", _DATE_KIND),
    ("Observation > Date Closed", "observation.date_closed", _DATE_KIND),
    ("Observation > Number", "observation.number", _ID),
    ("Observation > Title", "observation.title", _TEXT),
    ("Observation > Type", "observation.type", _TEXT),
    ("Observation > Description", "observation.description", _TEXT),
)
_OBSERVATION_8: Final = _fields(
    ("Observation > Assignee Company (Vendor) Name", "observation.assignee_vendor", _TEXT),
    ("Observation > Status", "observation.status", _TEXT),
    ("Observation > Count", "observation.count", _NUM, _NON),
    ("Observation > Date Created", "observation.date_created", _DATE_KIND),
    ("Observation > Number", "observation.number", _ID),
    ("Observation > Title", "observation.title", _TEXT),
    ("Observation > Type", "observation.type", _TEXT),
    ("Observation > Description", "observation.description", _TEXT),
)

_ADAPTERS: Final = (
    FamilyAdapter(
        view=FamilyView.OAC,
        fields=_fields(
            ("Meeting > Number", "meeting.number", _ID),
            ("Meeting > Date", "meeting.date", _DATE_KIND),
            ("Meeting Item > Category", "item.category", _TEXT),
            ("Meeting Item > Agenda/Item Number", "item.number", _ID),
            ("Meeting Item > Title", "item.title", _TEXT),
            ("Meeting Item > Description", "item.description", _TEXT),
            ("Meeting Item > Date Updated", "item.date_updated", _DATE_KIND),
            ("Meeting Item > Minutes", "item.minutes", _TEXT),
        ),
        keys=GroupKeys(),
        line_kinds=(LineKind.ITEM,),
        line_kind=_constant(LineKind.ITEM),
        identity=_identified(RecordKeyKind.ITEM, 3),
    ),
    FamilyAdapter(
        view=FamilyView.WITH_DATE_CLOSED,
        fields=_OBSERVATION_9,
        keys=GroupKeys(0, 1),
        line_kinds=(LineKind.OBSERVATION,),
        line_kind=_constant(LineKind.OBSERVATION),
        identity=_identified(RecordKeyKind.OBSERVATION, 5),
        status=_status_level(2),
        status_exact=_OPEN_CLOSED,
    ),
    FamilyAdapter(
        view=FamilyView.OPEN_BY_VENDOR,
        fields=_OBSERVATION_8,
        keys=GroupKeys(0, 1),
        line_kinds=(LineKind.OBSERVATION,),
        line_kind=_constant(LineKind.OBSERVATION),
        identity=_identified(RecordKeyKind.OBSERVATION, 4),
        status=_status_level(2),
        status_exact=_OPEN_CLOSED,
    ),
    FamilyAdapter(
        view=FamilyView.BY_STATUS,
        fields=_fields(
            ("Coordination Issue > Status", "issue.status", _TEXT),
            ("Coordination Issue > Issue Number", "issue.number", _ID),
            ("Coordination Issue > Title", "issue.title", _TEXT),
            ("Coordination Issue > Description", "issue.description", _TEXT),
            ("Coordination Issue > Assignee Company Name", "issue.assignee_company", _TEXT),
            ("Coordination Issue > Assignee Name", "issue.assignee_name", _TEXT),
            ("Coordination Issue > Date Created", "issue.date_created", _DATE_KIND),
            ("Coordination Issue > Due Date", "issue.due_date", _DATE_KIND),
            ("Coordination Issue > Type", "issue.type", _TEXT),
            ("Coordination Issue > Trade", "issue.trade", _TEXT),
            ("Coordination Issue > Date Updated", "issue.date_updated", _DATE_KIND),
        ),
        keys=GroupKeys(0),
        line_kinds=(LineKind.ISSUE,),
        line_kind=_constant(LineKind.ISSUE),
        identity=_identified(RecordKeyKind.COORDINATION_ISSUE, 1),
        status=_status_level(1),
        status_exact=_OPEN_CLOSED,
    ),
    FamilyAdapter(
        view=FamilyView.LINKED_TO_DRAWINGS,
        fields=_fields(
            ("RFI > Number", "rfi.number", _ID),
            ("RFI > Subject", "rfi.subject", _TEXT),
            ("RFI > Drawing Number", "rfi.drawing_number", _ID),
            ("Drawing Markup Link > Count", "drawing_link.count", _NUM, _NON),
            ("Drawing Markup Link > Tool Type", "drawing_link.tool_type", _TEXT),
            ("Drawing Markup Link > Type", "drawing_link.type", _TEXT),
        ),
        keys=GroupKeys(),
        line_kinds=(LineKind.RFI_DRAWING_LINK,),
        line_kind=_constant(LineKind.RFI_DRAWING_LINK),
        identity=_identified(RecordKeyKind.RFI, 0),
    ),
    FamilyAdapter(
        view=FamilyView.OPEN_OUTSTANDING,
        fields=_fields(
            ("RFI > Number", "rfi.number", _ID),
            ("RFI > Subject", "rfi.subject", _TEXT),
            ("RFI > Ball In Court", "rfi.ball_in_court", _TEXT),
            ("RFI > RFI Priority", "rfi.priority", _TEXT),
            ("RFI > Date Initiated", "rfi.date_initiated", _DATE_KIND),
            ("RFI > Due Date", "rfi.due_date", _DATE_KIND),
            ("RFI > Due Date Variance (Days)", "rfi.due_date_variance_days", _NUM, _NON),
        ),
        keys=GroupKeys(),
        line_kinds=(LineKind.RFI_ROW,),
        line_kind=_constant(LineKind.RFI_ROW),
        identity=_identified(RecordKeyKind.RFI, 0),
    ),
    FamilyAdapter(
        view=FamilyView.RECENTLY_CLOSED,
        fields=_fields(
            ("RFI > Number", "rfi.number", _ID),
            ("RFI > Subject", "rfi.subject", _TEXT),
            ("RFI > RFI Priority", "rfi.priority", _TEXT),
            ("RFI > Date Initiated", "rfi.date_initiated", _DATE_KIND),
            ("RFI > Date Closed", "rfi.date_closed", _DATE_KIND),
            ("RFI > Count", "rfi.count", _NUM, _NON),
        ),
        keys=GroupKeys(),
        line_kinds=(LineKind.RFI_ROW,),
        line_kind=_constant(LineKind.RFI_ROW),
        identity=_identified(RecordKeyKind.RFI, 0),
    ),
    FamilyAdapter(
        view=FamilyView.GROUPED_BY_CHANGE,
        fields=_fields(
            ("Budget Change > Number", "budget_change.number", _ID),
            ("Budget Change > Date Created", "budget_change.date_created", _DATE_KIND),
            ("Budget Change > Title", "budget_change.title", _TEXT),
            ("Budget Change > Status", "budget_change.status", _TEXT),
            ("Budget Code > Budget Code", "budget_code.code", _ID),
            ("Budget Code > Budget Code Description", "budget_code.description", _TEXT),
            ("Budget Change Adjustment Line Item > Amount", "adjustment.amount", _MONEY, _ADD),
            ("Budget Change Adjustment Line Item > Description", "adjustment.description", _TEXT),
        ),
        keys=GroupKeys(0),
        line_kinds=(LineKind.BUDGET_CHANGE_LINE,),
        line_kind=_constant(LineKind.BUDGET_CHANGE_LINE),
        identity=_snapshot_scoped,
        status=_status_column(3),
        status_exact=_APPROVAL,
        status_prefixes=_APPROVAL_PREFIXES,
        cross_check_columns=(4,),
    ),
    FamilyAdapter(
        view=FamilyView.BY_CODE,
        fields=_fields(
            ("Budget Code > Budget Code", "budget_code.code", _ID),
            ("Budget Code > Budget Code Description", "budget_code.description", _TEXT),
            ("Budget Change Adjustment Line Item > Amount", "adjustment.amount", _MONEY, _ADD),
            ("Budget Change Adjustment Line Item > Description", "adjustment.description", _TEXT),
            ("Budget Change > Number", "budget_change.number", _ID),
            ("Budget Change > Date Created", "budget_change.date_created", _DATE_KIND),
        ),
        keys=GroupKeys(),
        line_kinds=(LineKind.BUDGET_CHANGE_LINE,),
        line_kind=_constant(LineKind.BUDGET_CHANGE_LINE),
        identity=_snapshot_scoped,
        cross_check_columns=(0,),
    ),
    FamilyAdapter(
        view=FamilyView.BUYOUT_SUMMARY,
        fields=_fields(
            ("Budget Code > Budget Code", "budget_code.code", _ID),
            (
                "Budget Line Item > Original Budget Amount",
                "budget_line.original_amount",
                _MONEY,
                _ADD,
            ),
            (
                "Budget Change Adjustment Line Item > Amount",
                "budget_change_line.amount",
                _MONEY,
                _ADD,
            ),
            (
                "Prime Contract Change Order Line Item > Approved Amount",
                "prime_co_line.approved_amount",
                _MONEY,
                _ADD,
            ),
            ("Commitment > Number", "commitment.number", _ID),
            ("Company (Vendor) > Name", "vendor.name", _TEXT),
            ("Commitment Line Item > Amount", "commitment_line.amount", _MONEY, _ADD),
            (
                "Commitment Change Order Line Item > Approved Amount (Including Markup)",
                "commitment_co_line.approved_amount_with_markup",
                _MONEY,
                _ADD,
            ),
        ),
        keys=GroupKeys(0),
        line_kinds=(
            LineKind.BUDGET_LINE,
            LineKind.BUDGET_CHANGE,
            LineKind.PRIME_CHANGE_ORDER,
            LineKind.COMMITMENT,
            LineKind.COMMITMENT_CHANGE_ORDER,
            LineKind.VENDOR_ONLY,
        ),
        line_kind=_buyout_line,
        identity=_buyout_identity,
        cross_check_columns=(0, 4),
    ),
    FamilyAdapter(
        view=FamilyView.RECONCILIATION,
        fields=_fields(
            ("Prime Contract Change Order > Number", "prime_co.number", _ID),
            ("Prime Contract Potential Change Order > Number", "pco.number", _ID),
            (
                "Prime Contract Potential Change Order > Date Created",
                "pco.date_created",
                _DATE_KIND,
            ),
            ("Prime Contract Potential Change Order > Status", "pco.status", _TEXT),
            (
                "Prime Contract Change Order Line Item > Description",
                "prime_co_line.description",
                _TEXT,
            ),
            (
                "Prime Contract Change Order Line Item > Amount",
                "prime_co_line.amount",
                _MONEY,
                _ADD,
            ),
            (
                "Prime Contract Change Order Line Item > Date Created",
                "prime_co_line.date_created",
                _DATE_KIND,
            ),
            ("Commitment Change Order > Number", "commitment_co.number", _ID),
            ("Commitment Change Order > Status", "commitment_co.status", _TEXT),
            (
                "Commitment Change Order Line Item > Description",
                "commitment_co_line.description",
                _TEXT,
            ),
            (
                "Commitment Change Order Line Item > Amount",
                "commitment_co_line.amount",
                _MONEY,
                _ADD,
            ),
        ),
        keys=GroupKeys(0),
        line_kinds=(LineKind.PRIME_PCO_LINE, LineKind.COMMITMENT_CO_LINE),
        line_kind=_reconciliation_line,
        identity=_reconciliation_identity,
        status=_reconciliation_status,
        status_exact=_APPROVAL,
        status_prefixes=_APPROVAL_PREFIXES,
    ),
    FamilyAdapter(
        view=FamilyView.DELAYS,
        fields=_fields(
            ("Daily Log Delay > Date", "delay.date", _DATE_KIND),
            ("Daily Log Delay > Delay Type", "delay.type", _TEXT),
            ("Daily Log Delay > Start Time", "delay.start_time", _TEXT),
            ("Daily Log Delay > End Time", "delay.end_time", _TEXT),
            ("Daily Log Delay > Comments", "delay.comments", _TEXT),
            (
                "Daily Log Observed Weather Condition > Is Weather Delay",
                "weather.is_weather_delay",
                _BOOL,
            ),
        ),
        keys=GroupKeys(5),
        line_kinds=(LineKind.DELAY,),
        line_kind=_constant(LineKind.DELAY),
        identity=_snapshot_scoped,
    ),
    FamilyAdapter(
        view=FamilyView.MANPOWER,
        fields=_fields(
            ("Daily Log Manpower > Date", "manpower.date", _DATE_KIND),
            ("Daily Log Manpower > Company (Vendor) Name", "manpower.vendor", _TEXT),
            ("Daily Log Manpower > Workers", "manpower.workers", _NUM, _ADD),
            ("Daily Log Manpower > Hours", "manpower.hours", _NUM, _ADD),
            ("Daily Log Manpower > Total Hours", "manpower.total_hours", _NUM, _ADD),
            ("Daily Log Manpower > Comments", "manpower.comments", _TEXT),
        ),
        keys=GroupKeys(0),
        line_kinds=(LineKind.MANPOWER,),
        line_kind=_constant(LineKind.MANPOWER),
        identity=_manpower_identity,
    ),
    FamilyAdapter(
        view=FamilyView.NOTES,
        fields=_fields(
            ("Daily Log Note > Date", "note.date", _DATE_KIND),
            ("Daily Log Note > Comment", "note.comment", _TEXT),
        ),
        keys=GroupKeys(),
        line_kinds=(LineKind.NOTE,),
        line_kind=_constant(LineKind.NOTE),
        identity=_snapshot_scoped,
    ),
    FamilyAdapter(
        view=FamilyView.WEATHER,
        fields=_fields(
            ("Daily Log Observed Weather Condition > Date", "weather.date", _DATE_KIND),
            (
                "Daily Log Observed Weather Condition > Measured Humidity Average",
                "weather.humidity_average",
                _NUM,
                _NON,
            ),
            (
                "Daily Log Observed Weather Condition > Measured Temperature Average",
                "weather.temperature_average",
                _NUM,
                _NON,
            ),
            (
                "Daily Log Observed Weather Condition > Measured Wind Speed Average",
                "weather.wind_speed_average",
                _NUM,
                _NON,
            ),
            (
                "Daily Log Observed Weather Condition > Measured Dew Point",
                "weather.dew_point",
                _NUM,
                _NON,
            ),
            (
                "Daily Log Observed Weather Condition > Measured Precipitation Since Midnight",
                "weather.precipitation_since_midnight",
                _NUM,
            ),
        ),
        keys=GroupKeys(),
        line_kinds=(LineKind.WEATHER,),
        line_kind=_constant(LineKind.WEATHER),
        identity=_identified(RecordKeyKind.WEATHER, 0),
    ),
)

#: `signature -> adapter`; reviewed code, never configuration (plan section 4.2).
REGISTRY: Final[Mapping[str, FamilyAdapter]] = MappingProxyType(
    {adapter.signature: adapter for adapter in _ADAPTERS}
)


# --------------------------------------------------------------------------
# 4. The project-number cross-check (ruling D11)
# --------------------------------------------------------------------------


def carries_project_number(value: str, project_number: str) -> bool:
    """`value` starts with the bound number, token-bounded.

    Token-bounded: the next character, if any, is not alphanumeric, so a bound
    number never matches a longer number that merely starts with it.
    """
    text = normalize_whitespace(value)
    number = normalize_whitespace(project_number)
    if number == "" or not text.startswith(number):
        return False
    return len(text) == len(number) or not text[len(number)].isalnum()


_CROSS_CHECKED_ROLES: Final = frozenset(
    {RowRole.DETAIL, RowRole.GROUP_HEADER, RowRole.GROUPING_ONLY}
)


def project_number_cross_check(
    adapter: FamilyAdapter,
    rows: Sequence[ClassifiedRow],
    cells: Sequence[Cells],
    project_number: str | None,
) -> ReconciliationOutcome | None:
    """`None` for a view without identifier columns; else match, mismatch or not_checked."""
    if not adapter.cross_check_columns:
        return None
    if project_number is None or normalize_whitespace(project_number) == "":
        return ReconciliationOutcome.NOT_CHECKED
    checked = 0
    for row in rows:
        if row.role not in _CROSS_CHECKED_ROLES:
            continue
        for column in adapter.cross_check_columns:
            value = cells[row.ordinal - 1][column]
            if value == "" or value == BLANK_GROUP_KEY:
                continue
            checked += 1
            if not carries_project_number(value, project_number):
                return ReconciliationOutcome.MISMATCH
    return ReconciliationOutcome.MATCH if checked else ReconciliationOutcome.NOT_CHECKED


# --------------------------------------------------------------------------
# 5. The derivation plan
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LinePlan:
    """One detail row as a typed line (Layer B)."""

    ordinal: int
    line_kind: LineKind
    state: ObservationState
    reasons: tuple[RowReason, ...]
    identity: RecordIdentity
    identity_reason: RowReason | None
    status_raw: str | None
    status_class: StatusClass | None
    values: tuple[TypedValue, ...]


@dataclass(frozen=True, slots=True)
class DerivationPlan:
    """Classified, or quarantined with every Layer A row kept and none classified."""

    layer_a: LayerAPlan
    state: DerivationState
    quarantine_reason: QuarantineReason | None
    adapter: FamilyAdapter | None
    role_counts: Mapping[str, int]
    rows: tuple[ClassifiedRow, ...] = ()
    lines: tuple[LinePlan, ...] = ()
    stated_totals: tuple[StatedTotalCheck, ...] = ()
    reconciliation: ReconciliationSummary | None = None
    completeness: CompletenessClass | None = None
    cross_check: ReconciliationOutcome | None = None

    @property
    def data_row_count(self) -> int:
        return len(self.layer_a.rows)


def _quarantine(
    layer_a: LayerAPlan,
    reason: QuarantineReason,
    adapter: FamilyAdapter | None,
    cross_check: ReconciliationOutcome | None = None,
) -> DerivationPlan:
    counts = quarantined_role_counts(len(layer_a.rows))
    return DerivationPlan(
        layer_a, DerivationState.QUARANTINED, reason, adapter, counts, cross_check=cross_check
    )


def _line(adapter: FamilyAdapter, row: ClassifiedRow, cells: Cells) -> LinePlan:
    values: list[TypedValue] = []
    reasons: list[RowReason] = []
    for spec in adapter.fields:
        raw = cells[spec.column_index]
        value, reason = _type_cell(spec.value_kind, raw)
        values.append(TypedValue(spec.field_key, spec.value_kind, raw, value, reason))
        if reason is not None and reason not in reasons:
            reasons.append(reason)
    kind = adapter.line_kind(cells)
    identity, identity_reason = adapter.identity(cells, row, kind)
    status_raw: str | None = None
    status_class: StatusClass | None = None
    if adapter.status is not None:
        status_raw = adapter.status(cells, row, kind)
        status_class = classify_status(
            status_raw or "", exact=adapter.status_exact, prefixes=adapter.status_prefixes
        )
    return LinePlan(
        ordinal=row.ordinal,
        line_kind=kind,
        state=ObservationState.DEGRADED if reasons else ObservationState.TYPED,
        reasons=tuple(reasons),
        identity=identity,
        identity_reason=identity_reason,
        status_raw=status_raw,
        status_class=status_class,
        values=tuple(values),
    )


def derive(
    layer_a: LayerAPlan,
    *,
    project_number: str | None = None,
    registry: Mapping[str, FamilyAdapter] = REGISTRY,
) -> DerivationPlan:
    """The derivation of one export; the header signature alone chooses the adapter."""
    adapter = registry.get(layer_a.signature)
    if adapter is None:
        return _quarantine(layer_a, QuarantineReason.UNKNOWN_HEADER_SIGNATURE, None)
    cells = [record.cells for record in layer_a.rows]
    rows = classify_rows(cells, width=len(layer_a.header.cells), keys=adapter.keys)
    counts = role_counts(rows, len(cells))
    if malformed_ratio_exceeded(counts, len(cells)):
        return _quarantine(layer_a, QuarantineReason.MALFORMED_RATIO_EXCEEDED, adapter)
    cross_check = project_number_cross_check(adapter, rows, cells, project_number)
    if cross_check is ReconciliationOutcome.MISMATCH:
        return _quarantine(
            layer_a, QuarantineReason.BINDING_PROJECT_NUMBER_MISMATCH, adapter, cross_check
        )
    lines = tuple(
        _line(adapter, row, cells[row.ordinal - 1]) for row in rows if row.role is RowRole.DETAIL
    )
    # Only header, grand-total and detail cells are read, and those rows always
    # have the header's width; a malformed row of any width is never indexed.
    checks = reconcile_totals(rows, cells, adapter.total_columns)
    return DerivationPlan(
        layer_a=layer_a,
        state=DerivationState.CLASSIFIED,
        quarantine_reason=None,
        adapter=adapter,
        role_counts=counts,
        rows=rows,
        lines=lines,
        stated_totals=checks,
        reconciliation=summarize(checks),
        completeness=completeness_class(counts),
        cross_check=cross_check,
    )


# --------------------------------------------------------------------------
# 6. The cross-report check, paired within one source
# --------------------------------------------------------------------------

_PRIME_CO_APPROVED_COLUMN: Final = 3
_PCO_LINE_AMOUNT_COLUMN: Final = 5


def pair_cross_report(buyout: DerivationPlan, reconciliation: DerivationPlan) -> CrossReportCheck:
    """Buyout's approved prime-change grand total against the change-order reconciliation.

    Both plans must be classified derivations of their views; anything else is
    `not_checked`. The right side is the numbered change-order subtotals plus
    the approved `(Blank)`-group line amounts (domain `cross_report_check`).
    """
    usable = (
        buyout.state is DerivationState.CLASSIFIED
        and reconciliation.state is DerivationState.CLASSIFIED
        and buyout.adapter is not None
        and buyout.adapter.view is FamilyView.BUYOUT_SUMMARY
        and reconciliation.adapter is not None
        and reconciliation.adapter.view is FamilyView.RECONCILIATION
    )
    if not usable:
        return cross_report_check(None, (), ())
    grand = [row for row in buyout.rows if row.role is RowRole.GRAND_TOTAL]
    if len(grand) != 1:
        return cross_report_check(None, (), ())
    buyout_cells = buyout.layer_a.rows[grand[0].ordinal - 1].cells
    left = read_cell(buyout_cells[_PRIME_CO_APPROVED_COLUMN], money=True)
    subtotals: list[tuple[str, NumericCell]] = []
    for row in reconciliation.rows:
        if row.role in (RowRole.GROUP_HEADER, RowRole.GROUPING_ONLY) and row.group_level == 1:
            row_cells = reconciliation.layer_a.rows[row.ordinal - 1].cells
            subtotals.append(
                (row.group_key or "", read_cell(row_cells[_PCO_LINE_AMOUNT_COLUMN], money=True))
            )
    by_ordinal = {line.ordinal: line for line in reconciliation.lines}
    blank_lines: list[tuple[StatusClass, NumericCell]] = []
    for row in reconciliation.rows:
        if row.role is not RowRole.DETAIL or _inherited(row, 1) != BLANK_GROUP_KEY:
            continue
        line = by_ordinal[row.ordinal]
        if line.line_kind is not LineKind.PRIME_PCO_LINE:
            continue
        row_cells = reconciliation.layer_a.rows[row.ordinal - 1].cells
        blank_lines.append(
            (
                line.status_class or StatusClass.UNKNOWN,
                read_cell(row_cells[_PCO_LINE_AMOUNT_COLUMN], money=True),
            )
        )
    return cross_report_check(left, subtotals, blank_lines)
