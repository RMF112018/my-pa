"""Write real, synthetic OOXML packages with the standard library alone.

The reader under test is a zip-and-XML reader, so a fixture that faked its input
would prove nothing about it. These helpers write genuine packages — content
types, package relationships, a workbook part, a workbook relationship part, a
shared-string table and one or more worksheet parts — with `zipfile`, so what
the reader opens is the shape a spreadsheet writes.

`write_workbook` can also plant a `xl/vbaProject.bin` member and name the file
`.xlsm`, which is how the macro-blindness claim is tested: the member is present,
the reader never opens it, and the rows still parse.

Every value here is invented for this repository. There is no TBR project
identity, no real code, no real party and no real workbook byte in this file.
"""

from __future__ import annotations

import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

#: Excel's 1900 date system counts from here once the leap bug is absorbed.
EXCEL_EPOCH = date(1899, 12, 30)

#: The workbook column headings the importer recognises, in workbook order.
HEADINGS: tuple[str, ...] = (
    "No #",
    "DESCRIPTION",
    "DATE IDENTIFIED",
    "STATUS",
    "DAYS ELAPSED",
    "REFERENCE",
    "RESPONSIBLE",
    "B.I.C",
    "DUE",
    "COMPLETION DATE",
    "COMMENTS",
    "LAST UPDATED",
)


def serial(value: date) -> str:
    """A calendar date as the 1900-system serial a spreadsheet would store."""
    return str((value - EXCEL_EPOCH).days)


@dataclass(frozen=True)
class Cell:
    """One cell to write. `None` text writes no cell at all.

    `numeric` stores the value as a number, which is how a spreadsheet stores a
    date and how it would store a code somebody forgot to format as text.
    `formula` writes an `f` element; `cached` is the value the spreadsheet left
    beside it, and omitting `cached` is how an uncomputed formula is planted.
    """

    text: str | None = None
    numeric: bool = False
    formula: str | None = None
    cached: str | None = None
    cached_numeric: bool = True
    inline: bool = False


def text(value: str) -> Cell:
    """A shared-string cell, which is how a spreadsheet stores ordinary text."""
    return Cell(text=value)


def number(value: str) -> Cell:
    """A numerically-typed cell."""
    return Cell(text=value, numeric=True)


def formula(expression: str, cached: str | None = None, *, cached_numeric: bool = True) -> Cell:
    """A formula cell. Without `cached` it is the uncomputed case."""
    return Cell(formula=expression, cached=cached, cached_numeric=cached_numeric)


BLANK = Cell()


def _column(index: int) -> str:
    name = ""
    remaining = index
    while True:
        name = chr(ord("A") + remaining % 26) + name
        remaining = remaining // 26 - 1
        if remaining < 0:
            return name


def _cell_xml(cell: Cell, column: str, row_number: int, strings: dict[str, int]) -> str:
    reference = f"{column}{row_number}"
    if cell.formula is not None:
        body = f"<f>{escape(cell.formula)}</f>"
        if cell.cached is not None:
            body += f"<v>{escape(cell.cached)}</v>"
            if not cell.cached_numeric:
                return f'<c r="{reference}" t="str">{body}</c>'
        return f'<c r="{reference}">{body}</c>'
    if cell.text is None:
        return ""
    if cell.numeric:
        return f'<c r="{reference}"><v>{escape(cell.text)}</v></c>'
    if cell.inline:
        return f'<c r="{reference}" t="inlineStr"><is><t>{escape(cell.text)}</t></is></c>'
    index = strings.setdefault(cell.text, len(strings))
    return f'<c r="{reference}" t="s"><v>{index}</v></c>'


def _sheet_xml(rows: Sequence[Sequence[Cell]], strings: dict[str, int]) -> str:
    body = []
    for row_number, row in enumerate(rows, start=1):
        cells = "".join(
            _cell_xml(cell, _column(index), row_number, strings) for index, cell in enumerate(row)
        )
        body.append(f'<row r="{row_number}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(body)}</sheetData></worksheet>"
    )


def _shared_strings_xml(strings: Mapping[str, int]) -> str:
    ordered = sorted(strings, key=lambda value: strings[value])
    items = "".join(f"<si><t>{escape(value)}</t></si>" for value in ordered)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(ordered)}" uniqueCount="{len(ordered)}">{items}</sst>'
    )


def _workbook_xml(sheet_names: Sequence[str], *, date1904: bool) -> str:
    sheets = "".join(
        f'<sheet name={quoteattr(name)} sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(sheet_names, start=1)
    )
    properties = '<workbookPr date1904="1"/>' if date1904 else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"{properties}<sheets>{sheets}</sheets></workbook>"
    )


def _workbook_rels_xml(count: int) -> str:
    worksheet = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
    shared = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"
    entries = "".join(
        f'<Relationship Id="rId{index}" Type="{worksheet}" Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, count + 1)
    )
    entries += f'<Relationship Id="rIdStrings" Type="{shared}" Target="sharedStrings.xml"/>'
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{entries}</Relationships>"
    )


_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="xl/workbook.xml"/></Relationships>'
)


def _content_types(count: int) -> str:
    sheets = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'spreadsheetml.worksheet+xml"/>'
        for index in range(1, count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.ms-excel.sheet.macroEnabled.main+xml"/>'
        f"{sheets}"
        '<Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'spreadsheetml.sharedStrings+xml"/>'
        "</Types>"
    )


def write_workbook(
    path: Path,
    sheets: Mapping[str, Sequence[Sequence[Cell]]],
    *,
    date1904: bool = False,
    with_vba: bool = False,
) -> Path:
    """Write one synthetic OOXML package and return its path."""
    strings: dict[str, int] = {}
    rendered = [_sheet_xml(rows, strings) for rows in sheets.values()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types(len(rendered)))
        archive.writestr("_rels/.rels", _ROOT_RELS)
        archive.writestr("xl/workbook.xml", _workbook_xml(list(sheets), date1904=date1904))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml(len(rendered)))
        archive.writestr("xl/sharedStrings.xml", _shared_strings_xml(strings))
        for index, body in enumerate(rendered, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", body)
        if with_vba:
            archive.writestr("xl/vbaProject.bin", b"\x00SYNTHETIC-NOT-A-MACRO\x00")
    return path


SHEET_NAME = "ActionItems"

#: The two synthetic sections, with synthetic prefixes. The names are the
#: authoritative ones; the prefixes are invented for this fixture, because no
#: accepted source enumerates the real prefix text.
PERMITS = "PERMITS - OPEN"
DESIGN = "DESIGN DEVELOPMENT - OPEN"

IDENTIFIED_ON = date(2026, 1, 5)
DUE_ON = date(2026, 1, 19)
CLOSED_ON = date(2026, 2, 10)


def _headings() -> list[Cell]:
    return [text(value) for value in HEADINGS]


def _section(name: str) -> list[Cell]:
    return [text(name)]


def register_rows() -> list[list[Cell]]:
    """The synthetic register every classification test reads.

    One row of every kind the classifier has to answer for, and no more: a
    complete row, an intentionally incomplete one, a blank, a leftover template
    row, a closed row, a void row, an unknown status, a duplicated code, a
    numerically-typed code, an uncomputed formula, and four codes that differ
    only in the digits after the separator.
    """
    return [
        _headings(),
        _section(PERMITS),
        # A complete row. DUE and DAYS ELAPSED are formulas with cached values,
        # which is the only way this build ever learns what a formula produced.
        [
            text("1.01"),
            text("The stamped permit set is outstanding."),
            text(IDENTIFIED_ON.isoformat()),
            text("IDENTIFIED"),
            formula("NETWORKDAYS(C3,TODAY())", "11"),
            text("RFI-0001"),
            text("A Synthetic Vendor"),
            text("A Synthetic Vendor"),
            formula("WORKDAY(C3,10)", serial(DUE_ON)),
            BLANK,
            text("Awaiting the authority."),
            text("2026-02-01"),
        ],
        # Intentionally incomplete: no description and no BIC.
        [
            text("1.02"),
            BLANK,
            text("2026-01-06"),
            text("PENDING"),
            BLANK,
            BLANK,
            text("Another Synthetic Vendor"),
            BLANK,
            text("2026-01-20"),
            BLANK,
            BLANK,
            BLANK,
        ],
        # Blank.
        [BLANK],
        # A leftover template row: derived columns only, no record content.
        [BLANK, BLANK, BLANK, BLANK, formula("NETWORKDAYS(C6,TODAY())", "0"), BLANK],
        # A status the workbook's own validation list does not carry.
        [
            text("1.03"),
            text("Something with an unknown status."),
            text("2026-01-07"),
            text("ESCALATED"),
        ],
        # A void row: the source carries no void date and no void reason.
        [
            text("1.04"),
            text("Withdrawn by the authority."),
            text("2026-01-08"),
            text("VOID"),
        ],
        _section(DESIGN),
        *[
            [
                text(code),
                text("A distinct design item."),
                text("2026-01-09"),
                text("IN PROGRESS"),
                BLANK,
                BLANK,
                text("A Synthetic Vendor"),
                text("A Synthetic Vendor"),
                text("2026-01-23"),
                BLANK,
                BLANK,
                BLANK,
            ]
            for code in ("3.01", "3.1", "3.10", "3.100")
        ],
        # The same code twice.
        [
            text("3.01"),
            text("A duplicate of the first design item."),
            text("2026-01-10"),
            text("ON HOLD"),
            BLANK,
            BLANK,
            text("A Synthetic Vendor"),
            text("A Synthetic Vendor"),
            text("2026-01-24"),
        ],
        # A code cell somebody left formatted as a number.
        [
            number("3.5"),
            text("A numerically typed code."),
            text("2026-01-11"),
            text("IDENTIFIED"),
        ],
        # A formula with no cached value, in a column that carries meaning.
        [
            text("3.06"),
            formula("VLOOKUP(A15,Help!A:B,2,FALSE)"),
            text("2026-01-12"),
            text("IDENTIFIED"),
        ],
        # A closed row, with the completion date the domain requires.
        [
            text("3.07"),
            text("A finished design item."),
            text("2026-01-13"),
            text("CLOSED"),
            BLANK,
            BLANK,
            text("A Synthetic Vendor"),
            text("A Synthetic Vendor"),
            text("2026-01-27"),
            text(CLOSED_ON.isoformat()),
        ],
    ]


def help_rows() -> list[list[Cell]]:
    """A second sheet the importer is never pointed at."""
    return [
        [text("HELP")],
        [text("1.99"), text("This template text must never become a record."), text("2026-01-01")],
    ]


def write_register(path: Path, *, with_vba: bool = False, date1904: bool = False) -> Path:
    """The standard synthetic register: one register sheet and one Help sheet."""
    return write_workbook(
        path,
        {SHEET_NAME: register_rows(), "Help": help_rows()},
        with_vba=with_vba,
        date1904=date1904,
    )
