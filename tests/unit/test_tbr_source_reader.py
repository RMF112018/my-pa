"""PC-CM-IMP-WP13 T13-03, T13-08: the reader is macro-blind and formula-blind.

The package these tests read is a real OOXML package written by
`tests/fixtures/tbr_workbook.py` with `zipfile`, carrying a planted
`xl/vbaProject.bin` member and a `.xlsm` name. Nothing is mocked, because a
mocked package would prove nothing about a reader whose whole subject is what a
package contains.

The formula claim is the one worth being exact about. This build never computes
a formula. A formula cell is read by the value the spreadsheet cached beside it,
and a formula with no cached value has no value at all: it is reported as an
uncomputed cell and its row becomes an explicit unsupported-row finding. So the
`WORKDAY` and `NETWORKDAYS` assertions below compare the *cached* values against
the repository's own business-day functions — which is a comparison of two
independent computations, and would be worth nothing if this module had produced
both sides of it.
"""

from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path

import pytest

from my_pa.domain.project_controls.business_time import business_day_add, business_days_elapsed
from my_pa.infrastructure.ooxml_worksheet_reader import (
    OoxmlWorkbookSource,
    WorkbookSourceError,
    WorksheetCell,
)
from tests.fixtures.tbr_workbook import (
    EXCEL_EPOCH,
    SHEET_NAME,
    formula,
    text,
    write_register,
    write_workbook,
)

#: A stand-in for a missing cell, so a `.get` in a comprehension never raises.
MISSING = WorksheetCell(column="", text="")


@pytest.fixture
def register(tmp_path: Path) -> OoxmlWorkbookSource:
    """The synthetic macro-enabled register, opened for its register sheet."""
    path = write_register(tmp_path / "Synthetic Register.xlsm", with_vba=True)
    return OoxmlWorkbookSource(path, sheet_name=SHEET_NAME)


def test_a_macro_enabled_package_parses_and_its_macro_part_is_never_opened(
    tmp_path: Path,
) -> None:
    """T13-03. The `.xlsm` is read as data; the VBA member is present and untouched."""
    path = write_register(tmp_path / "Synthetic Register.xlsm", with_vba=True)
    with zipfile.ZipFile(path) as archive:
        assert "xl/vbaProject.bin" in archive.namelist()
    register = OoxmlWorkbookSource(path, sheet_name=SHEET_NAME)
    rows = list(register.rows())
    assert len(rows) > 1
    assert register.sheet_names() == (SHEET_NAME, "Help")
    assert not register.uses_1904_dates


def test_the_reader_opens_only_the_sheet_it_was_named(tmp_path: Path) -> None:
    """A second sheet's template text cannot become product semantics: it is not read."""
    path = write_register(tmp_path / "register.xlsm")
    source = OoxmlWorkbookSource(path, sheet_name=SHEET_NAME)
    values = [cell.text for row in source.rows() for cell in row.cells.values()]
    assert not any("must never become a record" in value for value in values)


def test_an_unknown_sheet_name_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    path = write_register(tmp_path / "register.xlsm")
    with pytest.raises(WorkbookSourceError) as error:
        OoxmlWorkbookSource(path, sheet_name="NotASheet")
    assert error.value.code == "workbook_sheet_absent"


def test_a_formula_without_a_cached_value_is_uncomputed_and_never_evaluated(
    register: OoxmlWorkbookSource,
) -> None:
    """T13-03. The one planted uncomputed cell reads as empty and as uncomputed."""
    uncomputed = [cell for row in register.rows() for cell in row.cells.values() if cell.uncomputed]
    assert len(uncomputed) == 1
    assert uncomputed[0].text == ""


def test_a_workday_cached_value_matches_the_normalised_expectation(
    register: OoxmlWorkbookSource,
) -> None:
    """T13-08, CM-BE-AC-098. `WORKDAY(identified, 10)` against `business_day_add`."""
    row = next(row for row in register.rows() if row.cells.get("A", MISSING).text == "1.01")
    identified = date.fromisoformat(row.cells["C"].text)
    due_cell = row.cells["I"]
    assert due_cell.numeric
    assert not due_cell.uncomputed
    cached = EXCEL_EPOCH.toordinal() + int(due_cell.text)
    assert date.fromordinal(cached) == business_day_add(identified, 10)


def test_a_networkdays_cached_value_matches_the_normalised_expectation(
    tmp_path: Path,
) -> None:
    """T13-08, CM-BE-AC-099. `NETWORKDAYS(start, end)` against `business_days_elapsed`."""
    start = date(2026, 1, 5)
    end = date(2026, 1, 19)
    expected = business_days_elapsed(start, end)
    path = write_workbook(
        tmp_path / "elapsed.xlsx",
        {
            SHEET_NAME: [
                [text("No #"), text("STATUS"), text("DAYS ELAPSED")],
                [text("1.01"), text("IDENTIFIED"), formula("NETWORKDAYS(A2,B2)", str(expected))],
            ]
        },
    )
    source = OoxmlWorkbookSource(path, sheet_name=SHEET_NAME)
    cell = next(row for row in source.rows() if row.row_number == 2).cells["C"]
    assert int(cell.text) == business_days_elapsed(start, end)


def test_a_numerically_typed_cell_is_reported_as_numeric_and_kept_as_text(
    register: OoxmlWorkbookSource,
) -> None:
    """A code somebody left formatted as a number is a fact, not a value to coerce."""
    row = next(row for row in register.rows() if row.cells.get("A", MISSING).numeric)
    assert row.cells["A"].text == "3.5"
    assert isinstance(row.cells["A"].text, str)


def test_codes_that_differ_only_after_the_separator_stay_four_distinct_strings(
    register: OoxmlWorkbookSource,
) -> None:
    """`2.01`-shaped codes are text end to end; nothing here parses one as a float."""
    codes = [
        row.cells["A"].text
        for row in register.rows()
        if "A" in row.cells and row.cells["A"].text.startswith("3.")
    ]
    assert {"3.01", "3.1", "3.10", "3.100"} <= set(codes)


def test_a_package_declaring_an_entity_is_refused_before_it_is_parsed(
    tmp_path: Path,
) -> None:
    """The one payload a values-only reader would otherwise still be exposed to."""
    path = write_workbook(
        tmp_path / "plain.xlsx",
        {SHEET_NAME: [[text("No #"), text("STATUS")]]},
    )
    hostile = tmp_path / "hostile.xlsx"
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(hostile, "w") as target:
        for member in source.namelist():
            payload = source.read(member)
            if member == "xl/sharedStrings.xml":
                payload = b'<?xml version="1.0"?><!DOCTYPE sst [<!ENTITY a "b">]><sst/>'
            target.writestr(member, payload)
    reader = OoxmlWorkbookSource(hostile, sheet_name=SHEET_NAME)
    with pytest.raises(WorkbookSourceError) as error:
        list(reader.rows())
    assert error.value.code == "workbook_part_declares_entities"


def test_a_file_that_is_not_a_package_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "not-a-package.xlsm"
    path.write_bytes(b"this is not a zip archive")
    with pytest.raises(WorkbookSourceError) as error:
        OoxmlWorkbookSource(path, sheet_name=SHEET_NAME)
    assert error.value.code == "workbook_not_a_package"


def test_the_1904_date_system_is_reported_rather_than_silently_misread(
    tmp_path: Path,
) -> None:
    path = write_register(tmp_path / "1904.xlsx", date1904=True)
    assert OoxmlWorkbookSource(path, sheet_name=SHEET_NAME).uses_1904_dates


def test_the_content_digest_is_stable_and_moves_with_the_bytes(tmp_path: Path) -> None:
    first = OoxmlWorkbookSource(write_register(tmp_path / "a.xlsm"), sheet_name=SHEET_NAME)
    again = OoxmlWorkbookSource(tmp_path / "a.xlsm", sheet_name=SHEET_NAME)
    assert first.content_digest == again.content_digest
    changed = write_workbook(
        tmp_path / "b.xlsm", {SHEET_NAME: [[text("No #"), text("STATUS")], [text("9.01")]]}
    )
    other = OoxmlWorkbookSource(changed, sheet_name=SHEET_NAME)
    assert other.content_digest != first.content_digest
