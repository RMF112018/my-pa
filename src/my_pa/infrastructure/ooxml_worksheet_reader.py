"""A bounded, values-only OOXML worksheet reader built on the standard library.

PC-CM-IMP-WP13. This is the one adapter behind the legacy-import source port
`my_pa.application.constraint_legacy_import` declares. It exists so that a
legacy Constraints workbook can be read without buying a spreadsheet library
for a package whose only inputs, at this head, are synthetic fixtures.

**Nothing here evaluates a formula, and nothing here can execute a macro.** The
reader opens the package with `zipfile` and parses three parts with
`xml.etree.ElementTree`: the workbook part, the shared-string table, and the one
named worksheet part (reached through the workbook's own relationship part,
which is how a worksheet part is named at all). A macro-enabled package carries
`xl/vbaProject.bin`; this reader never opens it, and a zip-and-XML reader is
structurally incapable of interpreting it. A cell holding a formula is reported
by the value Excel cached beside it; a formula with no cached value is reported
as an *uncomputed* cell and is never computed here or anywhere downstream.

**Bounded before it is parsed.** Member count, member size, shared-string count,
row and column counts and cell length all carry explicit limits, and a package
whose XML declares a DTD or an entity is refused outright rather than handed to
a parser: an entity-expansion payload is the one attack a values-only reader
would otherwise still be exposed to.

**No value is written down by this module.** It raises structural failures with
stable codes and never quotes a cell in a message.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from xml.etree import ElementTree

__all__ = [
    "MAX_ARCHIVE_MEMBERS",
    "MAX_CELL_CHARACTERS",
    "MAX_COLUMNS_PER_ROW",
    "MAX_PART_BYTES",
    "MAX_ROWS",
    "MAX_SHARED_STRINGS",
    "OoxmlWorkbookSource",
    "WorkbookSourceError",
    "WorksheetCell",
    "WorksheetRow",
]

_MAIN_NS: Final = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOCUMENT_REL_NS: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS: Final = "http://schemas.openxmlformats.org/package/2006/relationships"

_WORKBOOK_PART: Final = "xl/workbook.xml"
_WORKBOOK_RELS_PART: Final = "xl/_rels/workbook.xml.rels"
_SHARED_STRINGS_PART: Final = "xl/sharedStrings.xml"

#: Bounds. Each is a refusal, never a truncation: a reader that silently dropped
#: the tail of a workbook would report counts a reviewer could not reproduce.
MAX_ARCHIVE_MEMBERS: Final = 1024
MAX_PART_BYTES: Final = 32 * 1024 * 1024
MAX_SHARED_STRINGS: Final = 200_000
MAX_ROWS: Final = 50_000
MAX_COLUMNS_PER_ROW: Final = 256
MAX_CELL_CHARACTERS: Final = 4096

#: `A1`, `AB12`. A cell reference this does not match is a structural failure.
_CELL_REFERENCE = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")

#: Refused before parsing. `xml.etree` does not fetch an external entity, but it
#: does expand an internal one, so a package declaring either is not read.
_FORBIDDEN_XML_TOKENS: Final = (b"<!DOCTYPE", b"<!ENTITY")


class WorkbookSourceError(ValueError):
    """The package could not be read as a bounded OOXML workbook. `code` is stable.

    Every message names a structure, a part, a bound or a sheet name the caller
    itself supplied. None quotes a cell value.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class WorksheetCell:
    """One non-empty cell, as stored.

    `text` is what the file holds, verbatim and always as `str`: a code cell
    holding `2.01`, `2.1`, `2.10` and `2.100` yields four distinct strings, and
    nothing here parses one into a float. `numeric` says the cell was *typed* as
    a number, which is a fact about the workbook the importer must be able to
    report rather than repair. `uncomputed` marks a formula cell with no cached
    value; its `text` is empty and no caller may treat that emptiness as a value.
    """

    column: str
    text: str
    numeric: bool = False
    uncomputed: bool = False


@dataclass(frozen=True, slots=True)
class WorksheetRow:
    """One worksheet row, keyed by column letter. Empty cells are absent."""

    sheet_name: str
    row_number: int
    cells: Mapping[str, WorksheetCell]


def _read_part(archive: zipfile.ZipFile, part: str) -> bytes:
    try:
        info = archive.getinfo(part)
    except KeyError as error:
        raise WorkbookSourceError(
            "workbook_part_missing", f"the package carries no {part} part"
        ) from error
    if info.file_size > MAX_PART_BYTES:
        raise WorkbookSourceError(
            "workbook_part_too_large", f"the {part} part exceeds the {MAX_PART_BYTES} byte bound"
        )
    with archive.open(info) as handle:
        payload = handle.read(MAX_PART_BYTES + 1)
    if len(payload) > MAX_PART_BYTES:
        raise WorkbookSourceError(
            "workbook_part_too_large", f"the {part} part exceeds the {MAX_PART_BYTES} byte bound"
        )
    return payload


def _parse(payload: bytes, part: str) -> ElementTree.Element:
    upper = payload.upper()
    if any(token in upper for token in _FORBIDDEN_XML_TOKENS):
        raise WorkbookSourceError(
            "workbook_part_declares_entities",
            f"the {part} part declares a DTD or an entity and is not read",
        )
    try:
        # The suppression below is earned rather than asserted: the payload is
        # size-bounded above and refused outright when it declares a DTD or an
        # entity, which is the exposure that rule names. Buying a parser
        # dependency to restate the same check is the dependency this package
        # decided against.
        return ElementTree.fromstring(payload)  # noqa: S314
    except ElementTree.ParseError as error:
        raise WorkbookSourceError(
            "workbook_part_malformed", f"the {part} part is not well-formed XML"
        ) from error


def _shared_strings(archive: zipfile.ZipFile) -> tuple[str, ...]:
    """The shared-string table, or an empty table when the part is absent."""
    if _SHARED_STRINGS_PART not in archive.namelist():
        return ()
    root = _parse(_read_part(archive, _SHARED_STRINGS_PART), _SHARED_STRINGS_PART)
    items = root.findall(f"{{{_MAIN_NS}}}si")
    if len(items) > MAX_SHARED_STRINGS:
        raise WorkbookSourceError(
            "workbook_shared_strings_too_many",
            f"the shared-string table exceeds the {MAX_SHARED_STRINGS} entry bound",
        )
    return tuple(_joined_text(item) for item in items)


def _joined_text(node: ElementTree.Element) -> str:
    """Every `t` descendant concatenated, which is how a rich string reads."""
    return "".join(element.text or "" for element in node.iter(f"{{{_MAIN_NS}}}t"))


def _relationship_targets(archive: zipfile.ZipFile) -> Mapping[str, str]:
    """Relationship id to part name, for the workbook's own relationships."""
    root = _parse(_read_part(archive, _WORKBOOK_RELS_PART), _WORKBOOK_RELS_PART)
    targets: dict[str, str] = {}
    for relationship in root.findall(f"{{{_PACKAGE_REL_NS}}}Relationship"):
        identifier = relationship.get("Id")
        target = relationship.get("Target")
        if identifier is None or target is None:
            continue
        targets[identifier] = _normalized_target(target)
    return targets


def _normalized_target(target: str) -> str:
    """A workbook-relative target as a package part name.

    Only the two forms a spreadsheet writes are accepted — `worksheets/sheet1.xml`
    and `/xl/worksheets/sheet1.xml`. Anything carrying a parent segment is
    refused rather than resolved, because a reader that resolved `..` would read
    a part the workbook did not name.
    """
    cleaned = target.lstrip("/")
    if ".." in cleaned.split("/"):
        raise WorkbookSourceError(
            "workbook_relationship_escapes", "a workbook relationship names a parent path"
        )
    if target.startswith("/"):
        return cleaned
    return f"xl/{cleaned}"


class OoxmlWorkbookSource:
    """One workbook package, opened for one named worksheet.

    Construction reads the workbook part and the relationship part, so an
    unreadable package, an unknown sheet name or a 1904-date workbook fails
    before any row is yielded. `content_digest` is the SHA-256 of the package
    bytes and is the only identity this module publishes: the file's path and
    name are the operator's and never appear in a report or a message.
    """

    def __init__(self, path: Path, *, sheet_name: str) -> None:
        self._path = path
        self._sheet_name = sheet_name
        self._content_digest = _digest_of(path)
        with self._open() as archive:
            self._worksheet_part = self._resolve_worksheet(archive)
            self._uses_1904_dates = self._read_date_system(archive)

    @property
    def content_digest(self) -> str:
        """The SHA-256 of the package bytes, lowercase hex."""
        return self._content_digest

    @property
    def sheet_name(self) -> str:
        """The worksheet this source was opened for."""
        return self._sheet_name

    @property
    def uses_1904_dates(self) -> bool:
        """Whether the workbook declares the 1904 date system."""
        return self._uses_1904_dates

    def _open(self) -> zipfile.ZipFile:
        try:
            archive = zipfile.ZipFile(self._path)
        except (OSError, zipfile.BadZipFile) as error:
            raise WorkbookSourceError(
                "workbook_not_a_package", "the source is not a readable OOXML package"
            ) from error
        if len(archive.namelist()) > MAX_ARCHIVE_MEMBERS:
            archive.close()
            raise WorkbookSourceError(
                "workbook_too_many_members",
                f"the package exceeds the {MAX_ARCHIVE_MEMBERS} member bound",
            )
        return archive

    def _read_date_system(self, archive: zipfile.ZipFile) -> bool:
        root = _parse(_read_part(archive, _WORKBOOK_PART), _WORKBOOK_PART)
        properties = root.find(f"{{{_MAIN_NS}}}workbookPr")
        if properties is None:
            return False
        return properties.get("date1904") in {"1", "true"}

    def _resolve_worksheet(self, archive: zipfile.ZipFile) -> str:
        root = _parse(_read_part(archive, _WORKBOOK_PART), _WORKBOOK_PART)
        targets = _relationship_targets(archive)
        for sheet in root.iter(f"{{{_MAIN_NS}}}sheet"):
            if sheet.get("name") != self._sheet_name:
                continue
            identifier = sheet.get(f"{{{_DOCUMENT_REL_NS}}}id")
            if identifier is None or identifier not in targets:
                raise WorkbookSourceError(
                    "workbook_sheet_unrelated",
                    f"the sheet named {self._sheet_name!r} names no worksheet part",
                )
            return targets[identifier]
        raise WorkbookSourceError(
            "workbook_sheet_absent", f"the package carries no sheet named {self._sheet_name!r}"
        )

    def sheet_names(self) -> tuple[str, ...]:
        """Every sheet the workbook declares, in workbook order."""
        with self._open() as archive:
            root = _parse(_read_part(archive, _WORKBOOK_PART), _WORKBOOK_PART)
            return tuple(
                name
                for sheet in root.iter(f"{{{_MAIN_NS}}}sheet")
                if (name := sheet.get("name")) is not None
            )

    def rows(self) -> Iterator[WorksheetRow]:
        """Every row of the named worksheet, in sheet order, values only."""
        with self._open() as archive:
            strings = _shared_strings(archive)
            root = _parse(_read_part(archive, self._worksheet_part), self._worksheet_part)
            for ordinal, row in enumerate(root.iter(f"{{{_MAIN_NS}}}row"), start=1):
                if ordinal > MAX_ROWS:
                    raise WorkbookSourceError(
                        "workbook_too_many_rows",
                        f"the worksheet exceeds the {MAX_ROWS} row bound",
                    )
                yield self._row(row, ordinal, strings)

    def _row(
        self, row: ElementTree.Element, ordinal: int, strings: tuple[str, ...]
    ) -> WorksheetRow:
        declared = row.get("r")
        row_number = int(declared) if declared is not None and declared.isdigit() else ordinal
        cells: dict[str, WorksheetCell] = {}
        for index, cell in enumerate(row.findall(f"{{{_MAIN_NS}}}c")):
            if index >= MAX_COLUMNS_PER_ROW:
                raise WorkbookSourceError(
                    "workbook_too_many_columns",
                    f"a worksheet row exceeds the {MAX_COLUMNS_PER_ROW} column bound",
                )
            resolved = self._cell(cell, index, row_number, strings)
            if resolved is not None:
                cells[resolved.column] = resolved
        return WorksheetRow(sheet_name=self._sheet_name, row_number=row_number, cells=cells)

    def _cell(
        self,
        cell: ElementTree.Element,
        index: int,
        row_number: int,
        strings: tuple[str, ...],
    ) -> WorksheetCell | None:
        column = self._column_of(cell, index, row_number)
        kind = cell.get("t")
        formula = cell.find(f"{{{_MAIN_NS}}}f")
        value = cell.find(f"{{{_MAIN_NS}}}v")
        if kind == "inlineStr":
            inline = cell.find(f"{{{_MAIN_NS}}}is")
            text = "" if inline is None else _joined_text(inline)
            return self._bounded(column, text, numeric=False, uncomputed=False)
        if value is None:
            if formula is None:
                return None
            return WorksheetCell(column=column, text="", numeric=False, uncomputed=True)
        raw = value.text or ""
        if kind == "s":
            text = self._shared(raw, strings)
            return self._bounded(column, text, numeric=False, uncomputed=False)
        return self._bounded(column, raw, numeric=kind in {None, "n"}, uncomputed=False)

    def _shared(self, raw: str, strings: tuple[str, ...]) -> str:
        try:
            index = int(raw)
        except ValueError as error:
            raise WorkbookSourceError(
                "workbook_shared_string_index_malformed",
                "a shared-string cell names a non-integer index",
            ) from error
        if index < 0 or index >= len(strings):
            raise WorkbookSourceError(
                "workbook_shared_string_index_absent",
                "a shared-string cell names an index the table does not carry",
            )
        return strings[index]

    def _bounded(
        self, column: str, text: str, *, numeric: bool, uncomputed: bool
    ) -> WorksheetCell | None:
        if len(text) > MAX_CELL_CHARACTERS:
            raise WorkbookSourceError(
                "workbook_cell_too_long",
                f"a cell in column {column} exceeds the {MAX_CELL_CHARACTERS} character bound",
            )
        if not text:
            return None
        return WorksheetCell(column=column, text=text, numeric=numeric, uncomputed=uncomputed)

    def _column_of(self, cell: ElementTree.Element, index: int, row_number: int) -> str:
        reference = cell.get("r")
        if reference is None:
            return _column_name(index)
        match = _CELL_REFERENCE.match(reference)
        if match is None or int(match.group(2)) != row_number:
            raise WorkbookSourceError(
                "workbook_cell_reference_malformed",
                f"a cell in row {row_number} carries an unreadable reference",
            )
        return match.group(1)


def _column_name(index: int) -> str:
    """`0` is `A`, `26` is `AA`. Used only for a cell that declares no reference."""
    name = ""
    remaining = index
    while True:
        name = chr(ord("A") + remaining % 26) + name
        remaining = remaining // 26 - 1
        if remaining < 0:
            return name


def _digest_of(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise WorkbookSourceError("workbook_unreadable", "the source could not be read") from error
    return digest.hexdigest()
