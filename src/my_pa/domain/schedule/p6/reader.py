"""XER bytes to tables: encoding, `ERMHDR`, `%T`/`%F`/`%R`/`%E` (S7-1).

Contract `docs/architecture/schedule-xer-import-contract.md` sections 3.1,
3.2, 5.3 (version), 5.4 (caps) and 5.5 (structural validation). One pass over
the lines with bounded state: the file-size cap is checked before decoding,
every other cap before the record or value that would exceed it is kept, and
the reader stops at the first fatal line. Decoding is strict: UTF-8 if the
bytes are valid UTF-8, else Windows-1252, else `p6_encoding_invalid`. CRLF
and LF line ends are equivalent; nothing about which was used is kept.

Issues carry a table or field name only if it matches the name pattern of
section 5.2; anything else is reported by position, so no issue ever carries
an arbitrary string from the file. Pure, standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Final

from my_pa.domain.schedule.p6.model import (
    TABLE_RECORD_BOUNDS,
    Bound,
    P6Header,
    P6Issue,
    P6IssueCode,
    P6Limits,
    P6Severity,
)

__all__ = [
    "NAME_PATTERN",
    "RawRead",
    "RawTable",
    "read_xer",
    "safe_name",
]

#: Section 5.2: a field (or table) name that may be reported by name.
NAME_PATTERN: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
#: Section 5.3: accepted export versions.
VERSION_PATTERN: Final = re.compile(r"^[0-9]{1,2}\.[0-9]{1,2}(\.[0-9]{1,4}){0,2}$")
_EXPORT_DATE: Final = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")
_CALENDAR_TABLE: Final = "CALENDAR"
_CALENDAR_DATA: Final = "clndr_data"


def safe_name(name: str) -> str | None:
    """`name` if it matches the section 5.2 pattern, else None (report by position)."""
    return name if NAME_PATTERN.match(name) else None


@dataclass(frozen=True, slots=True)
class RawTable:
    """One `%T` table as read: names and string values, nothing typed yet."""

    name: str
    position: int
    line: int
    fields: tuple[str, ...]
    rows: tuple[tuple[int, tuple[str, ...]], ...]

    def index(self, field: str) -> int | None:
        try:
            return self.fields.index(field)
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class RawRead:
    header: P6Header | None
    tables: tuple[RawTable, ...]
    fatal: P6Issue | None
    total_records: int


class _FatalError(Exception):
    def __init__(self, issue: P6Issue) -> None:
        super().__init__(issue.code.value)
        self.issue = issue


def _fatal(
    code: P6IssueCode,
    *,
    line: int | None = None,
    table: str | None = None,
    field: str | None = None,
    bound: Bound | None = None,
) -> _FatalError:
    return _FatalError(
        P6Issue(
            code,
            P6Severity.FATAL,
            table=None if table is None else safe_name(table),
            line=line,
            field=None if field is None else safe_name(field),
            bound=bound,
        )
    )


def _decode(data: bytes) -> tuple[str, str]:
    try:
        return data.decode("utf-8", errors="strict"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252", errors="strict"), "cp1252"
    except UnicodeDecodeError:
        raise _fatal(P6IssueCode.ENCODING_INVALID) from None


def _header(line: str) -> P6Header:
    parts = line.split("\t")
    if parts[0] != "ERMHDR" or len(parts) < 2 or not VERSION_PATTERN.match(parts[1]):
        raise _fatal(P6IssueCode.HEADER_INVALID, line=1)
    export_date: date | None = None
    if len(parts) > 2 and (match := _EXPORT_DATE.match(parts[2])):
        try:
            export_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            export_date = None
    return P6Header(export_version=parts[1], export_date=export_date, encoding="")


class _State:
    def __init__(self, limits: P6Limits) -> None:
        self.limits = limits
        self.tables: list[RawTable] = []
        self.names: set[str] = set()
        self.name: str | None = None
        self.table_line = 0
        self.fields: tuple[str, ...] | None = None
        self.rows: list[tuple[int, tuple[str, ...]]] = []
        self.total = 0
        self.ended = False
        self.header: P6Header | None = None

    def close(self, line: int) -> None:
        if self.name is None:
            return
        if self.fields is None:
            raise _fatal(P6IssueCode.STRUCTURE_INVALID, line=line, table=self.name)
        self.tables.append(
            RawTable(self.name, len(self.tables), self.table_line, self.fields, tuple(self.rows))
        )
        self.name, self.fields, self.rows = None, None, []

    def table(self, parts: list[str], line: int) -> None:
        if len(parts) != 2 or not parts[1] or parts[1] in self.names:
            raise _fatal(P6IssueCode.STRUCTURE_INVALID, line=line)
        self.close(line)
        if len(self.names) + 1 > self.limits.tables:
            raise _fatal(P6IssueCode.BOUND_EXCEEDED, line=line, bound=Bound.TABLES)
        self.names.add(parts[1])
        self.name, self.table_line = parts[1], line

    def field_names(self, parts: list[str], line: int) -> None:
        if self.name is None or self.fields is not None or len(parts) < 2:
            raise _fatal(P6IssueCode.STRUCTURE_INVALID, line=line, table=self.name)
        names = tuple(parts[1:])
        if len(names) > self.limits.fields_per_table:
            raise _fatal(
                P6IssueCode.BOUND_EXCEEDED,
                line=line,
                table=self.name,
                bound=Bound.FIELDS_PER_TABLE,
            )
        if len(set(names)) != len(names):
            raise _fatal(P6IssueCode.STRUCTURE_INVALID, line=line, table=self.name)
        self.fields = names

    def record(self, parts: list[str], line: int) -> None:
        if self.name is None or self.fields is None:
            raise _fatal(P6IssueCode.STRUCTURE_INVALID, line=line, table=self.name)
        values = tuple(parts[1:])
        if len(values) != len(self.fields):
            raise _fatal(P6IssueCode.RECORD_WIDTH_MISMATCH, line=line, table=self.name)
        if self.total + 1 > self.limits.total_records:
            raise _fatal(
                P6IssueCode.BOUND_EXCEEDED, line=line, table=self.name, bound=Bound.TOTAL_RECORDS
            )
        bound = TABLE_RECORD_BOUNDS.get(self.name)
        if bound is not None and len(self.rows) + 1 > getattr(self.limits, bound.value):
            raise _fatal(P6IssueCode.BOUND_EXCEEDED, line=line, table=self.name, bound=bound)
        for field, value in zip(self.fields, values, strict=True):
            calendar = self.name == _CALENDAR_TABLE and field == _CALENDAR_DATA
            cap = self.limits.calendar_data_characters if calendar else self.limits.value_characters
            if len(value) > cap:
                raise _fatal(
                    P6IssueCode.BOUND_EXCEEDED,
                    line=line,
                    table=self.name,
                    field=field,
                    bound=Bound.CALENDAR_DATA_CHARACTERS if calendar else Bound.VALUE_CHARACTERS,
                )
        self.total += 1
        self.rows.append((line, values))


def _read(data: bytes, limits: P6Limits, state: _State) -> None:
    if len(data) > limits.file_bytes:
        raise _fatal(P6IssueCode.BOUND_EXCEEDED, bound=Bound.FILE_BYTES)
    text, encoding = _decode(data)
    byte_lines = data.split(b"\n")
    lines = text.split("\n")
    # Both encodings are ASCII-compatible, so byte 0x0A splits the same lines.
    if len(byte_lines) != len(lines):
        raise _fatal(P6IssueCode.ENCODING_INVALID)
    if lines[-1] == "":
        # The text after the final line end is not a line.
        byte_lines, lines = byte_lines[:-1], lines[:-1]
    for number, (raw, line) in enumerate(zip(byte_lines, lines, strict=True), start=1):
        if raw.endswith(b"\r"):
            raw, line = raw[:-1], line[:-1]
        if len(raw) > limits.line_bytes:
            raise _fatal(P6IssueCode.BOUND_EXCEEDED, line=number, bound=Bound.LINE_BYTES)
        if number == 1:
            parsed = _header(line)
            state.header = P6Header(parsed.export_version, parsed.export_date, encoding)
            continue
        if state.ended:
            if line:
                raise _fatal(P6IssueCode.STRUCTURE_INVALID, line=number)
            continue
        parts = line.split("\t")
        tag = parts[0]
        if tag == "%T":
            state.table(parts, number)
        elif tag == "%F":
            state.field_names(parts, number)
        elif tag == "%R":
            state.record(parts, number)
        elif tag == "%E" and len(parts) == 1:
            state.close(number)
            state.ended = True
        else:
            raise _fatal(P6IssueCode.STRUCTURE_INVALID, line=number, table=state.name)
    if not state.ended:
        raise _fatal(P6IssueCode.STRUCTURE_INVALID)


def read_xer(data: bytes, limits: P6Limits) -> RawRead:
    """Read `data` into tables, stopping at the first fatal issue (sections 3, 5.4, 5.5)."""
    state = _State(limits)
    try:
        _read(data, limits, state)
    except _FatalError as stop:
        return RawRead(state.header, tuple(state.tables), stop.issue, state.total)
    return RawRead(state.header, tuple(state.tables), None, state.total)
