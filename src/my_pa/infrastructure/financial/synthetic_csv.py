"""Financial controlled source F-1: the `my-pa-synthetic-finance-v1` parser (contract section 7).

`parse_synthetic_finance(data)` turns the bytes of 1 synthetic export into a
domain `SourceVersion` or a closed `FinanceParseRefusalCode` with its line --
**whole-file reject**, never a partial acceptance. The format is invented for
this repository (a strict, unquoted, ASCII-only CSV subset with a frozen
24-column header, a `source_version` record on line 3, an `end` record last and
a body SHA-256 declared on line 3); it imitates no real export.

Validation runs in the contract's order V1-V16; the first failing step decides.
The function is pure: no file, network, environment, clock, subprocess,
logging, printing, `eval`/`exec`, `pickle`, `csv` sniffing or XML. It is linear
in its input. A refusal carries the code and line only, never cell text.

`FinanceParseOutcome` is the domain record (contract F1-D26): it is imported
here, never redefined.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.project_controls.financial.model import (
    IDENTIFIER_PATTERN,
    MEASURES_BY_PERSPECTIVE,
    AccountLine,
    AccountMeasure,
    ChangeOrder,
    ChangeStatus,
    CostBasis,
    FinanceParseOutcome,
    FinanceParseRefusalCode,
    FinancialPerspective,
    LegSide,
    ScopeTransfer,
    SourceVersion,
    SourceVersionStatus,
    TransferLeg,
    period_start,
)
from my_pa.domain.project_controls.financial.money import (
    AmountError,
    add_amounts,
    currency_error,
    parse_amount,
)

__all__ = [
    "BOM",
    "FORMAT_NAME",
    "HEADER",
    "HEADER_COLUMNS",
    "PRODUCTION_LIMITS",
    "FinanceParseLimits",
    "parse_synthetic_finance",
]

_C = FinanceParseRefusalCode

#: Section 7.3 line 1: the interchange format version.
FORMAT_NAME: Final = "my-pa-synthetic-finance-v1"
#: Section 7.4: the frozen header, in this order.
HEADER_COLUMNS: Final = (
    "record_type",
    "ref",
    "source_system",
    "source_version_ref",
    "period",
    "cutoff_at",
    "status",
    "approved_by",
    "approved_at",
    "supersedes_ref",
    "perspective",
    "currency",
    "cost_basis",
    "external_project_id",
    "external_contract_id",
    "cost_code",
    "wbs_package",
    "measure",
    "amount",
    "change_status",
    "transfer_ref",
    "leg_side",
    "row_count",
    "body_sha256",
)
HEADER: Final = ",".join(HEADER_COLUMNS)
#: The UTF-8 byte-order mark (refused, never stripped).
BOM: Final = b"\xef\xbb\xbf"


@dataclass(frozen=True, slots=True)
class FinanceParseLimits:
    """Section 7.6 bounds; tests may inject tighter ones."""

    max_bytes: int
    max_records: int
    max_line_bytes: int
    max_cell_chars: int

    def __post_init__(self) -> None:
        for value in (self.max_bytes, self.max_records, self.max_line_bytes, self.max_cell_chars):
            if type(value) is not int:
                raise TypeError("a parse limit is an int")
            if value < 1:
                raise ValueError("a parse limit is positive")


#: Section 7.6 production values.
PRODUCTION_LIMITS: Final = FinanceParseLimits(
    max_bytes=4194304, max_records=20000, max_line_bytes=1024, max_cell_chars=64
)

_SOURCE_VERSION: Final = "source_version"
_ACCOUNT_LINE: Final = "account_line"
_CHANGE_ORDER: Final = "change_order"
_TRANSFER_LEG: Final = "transfer_leg"
_END: Final = "end"
_RECORD_TYPES: Final = frozenset(
    {_SOURCE_VERSION, _ACCOUNT_LINE, _CHANGE_ORDER, _TRANSFER_LEG, _END}
)

_REQUIRED: Final = "R"
_OPTIONAL: Final = "O"
_EMPTY: Final = "-"
_DEPENDS_ON_STATUS: Final = "S"


def _requirements(required: str, optional: str = "", dependent: str = "") -> Mapping[str, str]:
    marks = dict.fromkeys(HEADER_COLUMNS[1:], _EMPTY)
    for column in required.split():
        marks[column] = _REQUIRED
    for column in optional.split():
        marks[column] = _OPTIONAL
    for column in dependent.split():
        marks[column] = _DEPENDS_ON_STATUS
    return MappingProxyType(marks)


#: Section 7.4: R required, O optional, - must be empty, S depends on `status`.
_COLUMN_REQUIREMENTS: Final[Mapping[str, Mapping[str, str]]] = MappingProxyType(
    {
        _SOURCE_VERSION: _requirements(
            "source_system source_version_ref period cutoff_at status perspective currency"
            " cost_basis row_count body_sha256",
            dependent="approved_by approved_at supersedes_ref",
        ),
        _ACCOUNT_LINE: _requirements(
            "ref currency external_project_id cost_code wbs_package measure amount",
            optional="external_contract_id",
        ),
        _CHANGE_ORDER: _requirements(
            "ref currency external_project_id cost_code wbs_package amount change_status",
            optional="external_contract_id",
        ),
        _TRANSFER_LEG: _requirements(
            "ref currency external_project_id cost_code wbs_package amount change_status"
            " transfer_ref leg_side"
        ),
        _END: _requirements("row_count"),
    }
)

_IDENTIFIER_COLUMNS: Final = frozenset(
    {
        "ref",
        "source_system",
        "source_version_ref",
        "approved_by",
        "supersedes_ref",
        "external_project_id",
        "external_contract_id",
        "cost_code",
        "wbs_package",
        "transfer_ref",
    }
)
_ENUM_COLUMNS: Final[Mapping[str, type[StrEnum]]] = MappingProxyType(
    {
        "status": SourceVersionStatus,
        "perspective": FinancialPerspective,
        "cost_basis": CostBasis,
        "measure": AccountMeasure,
        "change_status": ChangeStatus,
        "leg_side": LegSide,
    }
)
_FORMULA_PREFIXES: Final = frozenset("=+-@")
_PERIOD: Final = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])")
_TIMESTAMP: Final = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z"
)
_COUNT: Final = re.compile(r"0|[1-9][0-9]{0,5}")
_TIMESTAMP_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"
_DIGEST: Final = re.compile(r"[0-9a-f]{64}")
_NON_ASCII: Final = re.compile(rb"[\x80-\xff]")
_CONTROL: Final = re.compile(rb"[\x00-\x09\x0b\x0c\x0e-\x1f\x7f]")
_CELL_COUNT: Final = len(HEADER_COLUMNS)
_INDEX: Final[Mapping[str, int]] = MappingProxyType(
    {column: index for index, column in enumerate(HEADER_COLUMNS)}
)


class _RefusalError(Exception):
    """Internal: a whole-file refusal (code and line only; never cell text)."""

    def __init__(self, code: FinanceParseRefusalCode, line: int | None) -> None:
        super().__init__(code.value)
        self.code = code
        self.line = line


@dataclass(frozen=True, slots=True)
class _Record:
    """1 validated record line: its number and its 24 cells by column."""

    line: int
    cells: Mapping[str, str]

    def get(self, column: str) -> str:
        return self.cells[column]

    def optional(self, column: str) -> str | None:
        return self.cells[column] or None


def _line_of(data: bytes, index: int) -> int:
    return data.count(b"\n", 0, index) + 1


def _check_bytes(data: bytes, limits: FinanceParseLimits) -> None:
    """V2-V7: size, BOM, encoding, control bytes, quotes, final LF."""
    if len(data) == 0:
        raise _RefusalError(_C.EMPTY_INPUT, None)
    if len(data) > limits.max_bytes:
        raise _RefusalError(_C.TOO_LARGE, None)
    if data.startswith(BOM):
        raise _RefusalError(_C.BOM_PRESENT, 1)
    found = _NON_ASCII.search(data)
    if found is not None:
        raise _RefusalError(_C.NON_ASCII, _line_of(data, found.start()))
    index = data.find(b"\r")
    if index >= 0:
        raise _RefusalError(_C.CARRIAGE_RETURN, _line_of(data, index))
    found = _CONTROL.search(data)
    if found is not None:
        raise _RefusalError(_C.CONTROL_CHARACTER, _line_of(data, found.start()))
    index = data.find(b'"')
    if index >= 0:
        raise _RefusalError(_C.QUOTE_CHARACTER, _line_of(data, index))
    if not data.endswith(b"\n"):
        raise _RefusalError(_C.PARTIAL_EXPORT, data.count(b"\n") + 1)


def _split_lines(data: bytes, limits: FinanceParseLimits) -> list[str]:
    """V8: row and line caps before any cell is split."""
    lines = data[:-1].decode("ascii").split("\n")
    if len(lines) - 2 > limits.max_records:
        raise _RefusalError(_C.TOO_MANY_ROWS, None)
    for number, text in enumerate(lines, start=1):
        if len(text) > limits.max_line_bytes:
            raise _RefusalError(_C.LINE_TOO_LONG, number)
    return lines


def _check_preamble(lines: Sequence[str]) -> None:
    """V9-V10: the format line and the frozen header; a file without a record is truncated."""
    if lines[0] != FORMAT_NAME:
        raise _RefusalError(_C.FORMAT_UNRECOGNIZED, 1)
    if len(lines) < 2:
        raise _RefusalError(_C.PARTIAL_EXPORT, len(lines))
    columns = lines[1].split(",")
    if len(set(columns)) != len(columns):
        raise _RefusalError(_C.DUPLICATE_COLUMN, 2)
    if lines[1] != HEADER:
        raise _RefusalError(_C.HEADER_MISMATCH, 2)
    if len(lines) < 3:
        raise _RefusalError(_C.PARTIAL_EXPORT, len(lines))


def _split_cells(lines: Sequence[str], limits: FinanceParseLimits) -> list[_Record]:
    """V11: every line from 3 has 24 cells, each within the cell bound."""
    records: list[_Record] = []
    for number, text in enumerate(lines[2:], start=3):
        cells = text.split(",")
        if len(cells) != _CELL_COUNT:
            raise _RefusalError(_C.FIELD_COUNT, number)
        if any(len(cell) > limits.max_cell_chars for cell in cells):
            raise _RefusalError(_C.CELL_TOO_LONG, number)
        records.append(
            _Record(number, MappingProxyType(dict(zip(HEADER_COLUMNS, cells, strict=True))))
        )
    return records


def _requirement(record_type: str, column: str, status: str) -> str:
    mark = _COLUMN_REQUIREMENTS[record_type][column]
    if mark != _DEPENDS_ON_STATUS:
        return mark
    if column == "supersedes_ref":
        return _REQUIRED if status == SourceVersionStatus.WITHDRAWN.value else _OPTIONAL
    if status == SourceVersionStatus.PROPOSED.value:
        return _EMPTY
    if status in (SourceVersionStatus.APPROVED.value, SourceVersionStatus.WITHDRAWN.value):
        return _REQUIRED
    return _OPTIONAL  # an unknown status is refused by its own grammar below


def _check_timestamp(text: str, line: int) -> None:
    match = _TIMESTAMP.fullmatch(text)
    if match is None:
        raise _RefusalError(_C.TIMESTAMP_GRAMMAR, line)
    year, month, day, hour, minute, second = (int(part) for part in match.groups())
    try:
        datetime(year, month, day, hour, minute, second, tzinfo=UTC)
    except ValueError:
        raise _RefusalError(_C.TIMESTAMP_GRAMMAR, line) from None


def _check_cell(column: str, text: str, line: int) -> None:
    """Section 7.5 grammar of 1 non-empty cell."""
    if column in _IDENTIFIER_COLUMNS:
        if IDENTIFIER_PATTERN.fullmatch(text) is None:
            raise _RefusalError(_C.IDENTIFIER_GRAMMAR, line)
    elif column in _ENUM_COLUMNS:
        if text not in {member.value for member in _ENUM_COLUMNS[column]}:
            raise _RefusalError(_C.ENUM_VALUE, line)
    elif column == "amount":
        try:
            parse_amount(text)
        except AmountError as error:
            raise _RefusalError(_C(error.code), line) from None
    elif column == "period":
        if _PERIOD.fullmatch(text) is None:
            raise _RefusalError(_C.PERIOD_GRAMMAR, line)
    elif column in ("cutoff_at", "approved_at"):
        _check_timestamp(text, line)
    elif column == "currency":
        code = currency_error(text)
        if code is not None:
            raise _RefusalError(_C(code), line)
    elif column == "row_count":
        if _COUNT.fullmatch(text) is None:
            raise _RefusalError(_C.COUNT_GRAMMAR, line)
    elif column == "body_sha256" and _DIGEST.fullmatch(text) is None:
        raise _RefusalError(_C.DIGEST_GRAMMAR, line)


def _check_record(record: _Record, record_type: str) -> None:
    """Requirements (`cell_missing`, `cell_not_empty`), then formula, then grammars."""
    status = record.get("status")
    columns = HEADER_COLUMNS[1:]
    for column in columns:
        mark = _requirement(record_type, column, status)
        present = record.get(column) != ""
        if mark == _REQUIRED and not present:
            raise _RefusalError(_C.CELL_MISSING, record.line)
        if mark == _EMPTY and present:
            raise _RefusalError(_C.CELL_NOT_EMPTY, record.line)
    for column in HEADER_COLUMNS:
        text = record.get(column)
        if column != "amount" and text and text[0] in _FORMULA_PREFIXES:
            raise _RefusalError(_C.FORMULA_INJECTION, record.line)
    for column in columns:
        text = record.get(column)
        if text:
            _check_cell(column, text, record.line)


def _check_source_version(record: _Record) -> None:
    """V12: line 3 is the `source_version` record, fully validated."""
    if record.get("record_type") != _SOURCE_VERSION:
        raise _RefusalError(_C.SOURCE_VERSION_NOT_FIRST, record.line)
    _check_record(record, _SOURCE_VERSION)


def _check_end(header: _Record, records: Sequence[_Record]) -> None:
    """V13: 1 `end` record, last; both counts equal the actual count; its cells validated."""
    last = records[-1]
    if len(records) < 2 or last.get("record_type") != _END:
        raise _RefusalError(_C.PARTIAL_EXPORT, last.line)
    body = records[1:-1]
    for record in body:
        if record.get("record_type") == _END:
            raise _RefusalError(_C.PARTIAL_EXPORT, record.line)
    actual = str(len(body))
    if header.get("row_count") != actual:
        raise _RefusalError(_C.PARTIAL_EXPORT, header.line)
    if last.get("row_count") != actual:
        raise _RefusalError(_C.PARTIAL_EXPORT, last.line)
    _check_record(last, _END)


def _check_body_hash(data: bytes, header: _Record) -> None:
    """V14: SHA-256 of the body (line 4 through the final LF) equals `body_sha256`."""
    start = 0
    for _ in range(3):
        start = data.index(b"\n", start) + 1
    if hashlib.sha256(data[start:]).hexdigest() != header.get("body_sha256"):
        raise _RefusalError(_C.HASH_MISMATCH, header.line)


def _check_body_records(body: Sequence[_Record]) -> None:
    """V15: every record between line 3 and the `end` line, in order."""
    for record in body:
        record_type = record.get("record_type")
        if record_type == _SOURCE_VERSION:
            raise _RefusalError(_C.SOURCE_VERSION_DUPLICATE, record.line)
        if record_type not in _RECORD_TYPES:
            raise _RefusalError(_C.RECORD_TYPE_UNKNOWN, record.line)
        _check_record(record, record_type)


def _of_type(body: Sequence[_Record], record_type: str) -> list[_Record]:
    return [record for record in body if record.get("record_type") == record_type]


def _check_transfers(legs: Sequence[_Record]) -> dict[str, list[_Record]]:
    """Section 7.7 transfer rules, each rule over every group (first-appearance order)."""
    groups: dict[str, list[_Record]] = {}
    for leg in legs:
        groups.setdefault(leg.get("transfer_ref"), []).append(leg)
    for group in groups.values():
        if len(group) != 2:
            raise _RefusalError(_C.TRANSFER_LEG_COUNT, group[-1].line)
    for group in groups.values():
        if {leg.get("leg_side") for leg in group} != {LegSide.DEBIT.value, LegSide.CREDIT.value}:
            raise _RefusalError(_C.TRANSFER_LEG_SIDES, group[-1].line)
    for group in groups.values():
        for leg in group:
            amount = parse_amount(leg.get("amount"))
            negative = leg.get("leg_side") == LegSide.DEBIT.value
            if (amount < 0) != negative or amount.is_zero():
                raise _RefusalError(_C.TRANSFER_LEG_SIGN, group[-1].line)
    rules = (
        (_C.TRANSFER_SCOPE_MISMATCH, ("cost_code", "wbs_package"), True),
        (_C.TRANSFER_SAME_PROJECT, ("external_project_id",), False),
        (_C.TRANSFER_STATUS_MISMATCH, ("change_status",), True),
    )
    for code, columns, must_equal in rules:
        for first, second in groups.values():
            equal = all(first.get(column) == second.get(column) for column in columns)
            if equal != must_equal:
                raise _RefusalError(code, second.line)
    for first, second in groups.values():
        if not add_amounts(
            parse_amount(first.get("amount")), parse_amount(second.get("amount"))
        ).is_zero():
            raise _RefusalError(_C.TRANSFER_UNBALANCED, second.line)
    return groups


def _check_cross_records(header: _Record, body: Sequence[_Record]) -> dict[str, list[_Record]]:
    """V16: section 7.7 cross-record rules in the listed order (first offending line)."""
    for record in body:
        if record.get("currency") != header.get("currency"):
            raise _RefusalError(_C.LINE_CURRENCY_MISMATCH, record.line)
    if _instant(header.get("cutoff_at")) < period_start(header.get("period")):
        raise _RefusalError(_C.CUTOFF_BEFORE_PERIOD, header.line)
    if header.get("status") == SourceVersionStatus.WITHDRAWN.value and body:
        raise _RefusalError(_C.WITHDRAWAL_HAS_ROWS, header.line)
    if header.get("supersedes_ref") == header.get("source_version_ref"):
        raise _RefusalError(_C.SUPERSEDES_SELF, header.line)
    lines = _of_type(body, _ACCOUNT_LINE)
    perspective = FinancialPerspective(header.get("perspective"))
    for record in lines:
        if perspective not in MEASURES_BY_PERSPECTIVE[AccountMeasure(record.get("measure"))]:
            raise _RefusalError(_C.MEASURE_PERSPECTIVE_MISMATCH, record.line)
    for record in lines:
        if parse_amount(record.get("amount")) < 0:
            raise _RefusalError(_C.AMOUNT_SIGN, record.line)
    for record in _of_type(body, _CHANGE_ORDER):
        if parse_amount(record.get("amount")).is_zero():
            raise _RefusalError(_C.CHANGE_ORDER_ZERO, record.line)
    refs: set[str] = set()
    transfer_refs: set[str] = set()
    for record in body:
        ref = record.get("ref")
        if ref in refs or ref in transfer_refs:
            raise _RefusalError(_C.DUPLICATE_REF, record.line)
        refs.add(ref)
        transfer_ref = record.get("transfer_ref")
        if transfer_ref:
            if transfer_ref in refs:
                raise _RefusalError(_C.DUPLICATE_REF, record.line)
            transfer_refs.add(transfer_ref)
    identities: set[tuple[str, str, str, str, str]] = set()
    for record in lines:
        identity = (
            record.get("external_project_id"),
            record.get("external_contract_id"),
            record.get("cost_code"),
            record.get("wbs_package"),
            record.get("measure"),
        )
        if identity in identities:
            raise _RefusalError(_C.DUPLICATE_IDENTITY, record.line)
        identities.add(identity)
    return _check_transfers(_of_type(body, _TRANSFER_LEG))


def _instant(text: str) -> datetime:
    return datetime.strptime(text, _TIMESTAMP_FORMAT).replace(tzinfo=UTC)


def _optional_instant(text: str | None) -> datetime | None:
    return None if text is None else _instant(text)


def _leg(record: _Record) -> TransferLeg:
    return TransferLeg(
        record.get("ref"),
        record.get("external_project_id"),
        LegSide(record.get("leg_side")),
        parse_amount(record.get("amount")),
    )


def _transfer(legs: Sequence[_Record]) -> ScopeTransfer:
    by_side = {record.get("leg_side"): record for record in legs}
    credit = by_side[LegSide.CREDIT.value]
    debit = by_side[LegSide.DEBIT.value]
    return ScopeTransfer(
        credit.get("transfer_ref"),
        credit.get("cost_code"),
        credit.get("wbs_package"),
        ChangeStatus(credit.get("change_status")),
        (_leg(credit), _leg(debit)),
    )


def _build(
    header: _Record, body: Sequence[_Record], groups: Mapping[str, Sequence[_Record]]
) -> SourceVersion:
    """Every cell has passed its checks: the domain constructors cannot refuse it."""
    return SourceVersion(
        source_system=header.get("source_system"),
        source_version_ref=header.get("source_version_ref"),
        period=header.get("period"),
        cutoff_at=_instant(header.get("cutoff_at")),
        status=SourceVersionStatus(header.get("status")),
        approved_by=header.optional("approved_by"),
        approved_at=_optional_instant(header.optional("approved_at")),
        supersedes_ref=header.optional("supersedes_ref"),
        perspective=FinancialPerspective(header.get("perspective")),
        currency=header.get("currency"),
        cost_basis=CostBasis(header.get("cost_basis")),
        account_lines=tuple(
            AccountLine(
                record.get("ref"),
                record.get("external_project_id"),
                record.optional("external_contract_id"),
                record.get("cost_code"),
                record.get("wbs_package"),
                AccountMeasure(record.get("measure")),
                parse_amount(record.get("amount")),
            )
            for record in _of_type(body, _ACCOUNT_LINE)
        ),
        change_orders=tuple(
            ChangeOrder(
                record.get("ref"),
                record.get("external_project_id"),
                record.optional("external_contract_id"),
                record.get("cost_code"),
                record.get("wbs_package"),
                ChangeStatus(record.get("change_status")),
                parse_amount(record.get("amount")),
            )
            for record in _of_type(body, _CHANGE_ORDER)
        ),
        transfers=tuple(_transfer(group) for group in groups.values()),
    )


def _parse(data: bytes, limits: FinanceParseLimits) -> SourceVersion:
    _check_bytes(data, limits)
    lines = _split_lines(data, limits)
    _check_preamble(lines)
    records = _split_cells(lines, limits)
    header = records[0]
    _check_source_version(header)
    _check_end(header, records)
    _check_body_hash(data, header)
    body = records[1:-1]
    _check_body_records(body)
    groups = _check_cross_records(header, body)
    return _build(header, body, groups)


def parse_synthetic_finance(
    data: bytes, *, limits: FinanceParseLimits = PRODUCTION_LIMITS
) -> FinanceParseOutcome:
    """Section 7.9: 1 synthetic export to an admitted version or 1 refusal (code, line)."""
    if type(data) is not bytes:
        raise TypeError("the synthetic parser accepts bytes only")
    if type(limits) is not FinanceParseLimits:
        raise TypeError("limits must be FinanceParseLimits")
    file_sha256 = hashlib.sha256(data).hexdigest()
    try:
        version = _parse(data, limits)
    except _RefusalError as refusal:
        return FinanceParseOutcome(None, refusal.code, refusal.line, file_sha256)
    return FinanceParseOutcome(version, None, None, file_sha256)
