"""S7-1 acceptance A2: catalogue `p6-field-catalogue-v1` equals contract section 6 (FAST).

`docs/architecture/schedule-xer-import-contract.md` section 6 is the
authority; the module renders its tables 6.3-6.10 back to Markdown rows and
must equal the contract row for row, and its 6.7/6.8 optional-field lists
name for name. A row removed, added or changed on either side turns these red.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from my_pa.domain.schedule.p6 import catalogue
from my_pa.domain.schedule.p6.catalogue import (
    CATALOGUE,
    CATALOGUE_VERSION,
    ENUMERATIONS,
    EntityKind,
    Tier,
    ValueType,
    catalogue_field,
    render_section,
)
from my_pa.domain.schedule.p6.parser import FIELD_KEY_PATTERN

ROOT: Final = Path(__file__).resolve().parents[2]
CONTRACT: Final = ROOT / "docs" / "architecture" / "schedule-xer-import-contract.md"
SECTIONS: Final = ("6.3", "6.4", "6.5", "6.6", "6.7", "6.8", "6.9", "6.10")


def _contract() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def _section_text(section: str) -> str:
    text = _contract()
    start = text.index(f"### {section} ")
    following = re.search(r"\n#{2,3} ", text[start + 4 :])
    assert following is not None
    return text[start : start + 4 + following.start()]


def _contract_rows(section: str) -> tuple[str, ...]:
    rows = []
    for line in _section_text(section).splitlines():
        if line.startswith("|") and not line.startswith("|---"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            rows.append("| " + " | ".join(cells) + " |")
    return tuple(rows)


@pytest.mark.parametrize("section", SECTIONS)
def test_catalogue_tables_render_row_for_row_as_the_contract(section: str) -> None:
    assert render_section(section) == _contract_rows(section)


def _backticked_list(start: str, stop: str) -> list[str]:
    text = _contract()
    begin = text.index(start)
    end = text.index(stop, begin)
    return re.findall(r"`([A-Za-z0-9_]+)`", text[begin + len(start) : end])


def test_project_optional_list_matches_the_contract() -> None:
    names = _backticked_list("Optional, generic field store (O\u2212, all [S]):", "Their XML")
    assert tuple(names) == catalogue.PROJECT_OPTIONAL_FIELDS
    personal = re.findall(r"`([a-z_]+)`\s+\(personal\)", _section_text("6.7"))
    assert set(personal) == set(catalogue.PROJECT_PERSONAL_FIELDS)
    for name, xml in catalogue.PROJECT_OPTIONAL_XML.items():
        assert f"`{name}` =\n`{xml}`" in _section_text("6.7") or f"`{name}` = `{xml}`" in (
            _section_text("6.7").replace("\n", " ")
        )


def test_schedoptions_optional_list_matches_the_contract() -> None:
    names = _backticked_list("Optional (O\u2212, [S]):", "Enumerations:")
    assert tuple(names) == catalogue.SCHEDOPTIONS_OPTIONAL_FIELDS


def test_every_enumeration_token_is_the_contracts() -> None:
    section = _contract()[_contract().index("### 6.3") : _contract().index("## 7. ")]
    tokens_in_contract = set(re.findall(r"`([A-Za-z]{2,5}_[A-Za-z0-9_]+)`", section))
    module_tokens = {
        token for seen, documented in ENUMERATIONS.values() for token in (*seen, *documented)
    }
    assert module_tokens <= tokens_in_contract
    # Every P6 token the contract lists in an enumeration is in some value set.
    enumerated = {
        token
        for token in tokens_in_contract
        if token.split("_")[0]
        in {"TT", "TK", "DT", "CP", "CS", "PT", "PR", "WS", "CA", "rcal", "FT", "SD"}
    }
    assert enumerated <= module_tokens


def test_catalogue_counts_match_the_sample_shape() -> None:
    """Section 3.5: the catalogue covers the sample's 305 fields in 16 tables."""
    assert CATALOGUE_VERSION == "p6-field-catalogue-v1"
    assert len(CATALOGUE) == 305
    tables = {field.table for field in CATALOGUE}
    assert len(tables) == 16
    counts = {table: sum(1 for field in CATALOGUE if field.table == table) for table in tables}
    assert counts == {
        "CURRTYPE": 11,
        "FINTMPL": 3,
        "LOCATION": 15,
        "NONWORK": 4,
        "OBS": 6,
        "UDFTYPE": 9,
        "PROJECT": 88,
        "CALENDAR": 13,
        "SCHEDOPTIONS": 25,
        "PROJWBS": 26,
        "ACTVTYPE": 8,
        "TASK": 67,
        "ACTVCODE": 8,
        "TASKPRED": 11,
        "TASKACTV": 4,
        "UDFVALUE": 7,
    }


def test_every_field_key_matches_the_section_7_7_grammar() -> None:
    for field in CATALOGUE:
        assert FIELD_KEY_PATTERN.match(field.field_key), field.field_key
        assert field.field_key == f"xer:{field.table}.{field.field}"


def test_derived_attributes_follow_the_cells() -> None:
    task_code = catalogue_field("TASK", "task_code")
    assert task_code is not None
    assert (task_code.tier, task_code.value_type, task_code.max_characters) == (
        Tier.REQUIRED,
        ValueType.TEXT,
        40,
    )
    assert task_code.typed_column == "activity_id"
    assert task_code.engine_use and task_code.delta_use
    cstr_date = catalogue_field("TASK", "cstr_date")
    assert cstr_date is not None and cstr_date.required and cstr_date.empty_allowed
    blob = catalogue_field("CALENDAR", "clndr_data")
    assert blob is not None and blob.tier is Tier.DERIVED and blob.required
    user = catalogue_field("TASK", "create_user")
    assert user is not None and user.personal and user.tier is Tier.OPTIONAL
    expect = catalogue_field("TASK", "expect_end_date")
    assert expect is not None and expect.default_capture and expect.is_generic_store
    never = catalogue_field("UDFTYPE", "indicator_expression")
    assert never is not None and never.tier is Tier.NEVER
    text = catalogue_field("UDFVALUE", "udf_text")
    assert text is not None and text.is_component and text.sample_status == "seen"
    number = catalogue_field("UDFVALUE", "udf_number")
    assert number is not None and number.sample_status == "documented"
    assert catalogue_field("TASKPRED", "task_id") is not None
    assert {f.entity_kind for f in CATALOGUE if f.table == "TASKPRED"} == {EntityKind.RELATIONSHIP}


def test_documented_tables_are_catalogued_without_fields() -> None:
    assert "RSRC" in catalogue.DOCUMENTED_TABLES
    assert "TASKRSRC" in catalogue.DOCUMENTED_TABLES
    assert catalogue.is_catalogued_table("SHIFTPER")
    assert catalogue.table_fields("RSRC") == ()
    assert not catalogue.is_catalogued_table("SYNEXTRA")
