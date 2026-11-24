"""Every project-report column that may hold export content is listed (WP3P-S3 ruling).

Layer A and the typed line values hold raw export text as source evidence:
names, descriptions, minutes, vendor names inside a record key. This module is
that set's inventory, in the shape of the communications no-content guard:

* `FREE_TEXT` -- every column that may carry export content, with why;
* `STRUCTURED` -- every other column that is not of an explicitly non-text
  type, each held by a CHECK of its own table that names it (an identifier
  shape, a closed set, a digest, a version token, a catalogue key or a count
  object), so a column cannot be filed here without a guard that keeps content
  out of it.

Only the explicitly non-text types (`NON_TEXT_TYPES`: Boolean, the integers,
Numeric, Date and DateTime) are exempt. Every other column -- `Text`, `String`,
`VARCHAR`, `Unicode`, `JSON`, `JSONB`, `ARRAY` or a type not yet seen -- must be
listed, so a classification by allow-list cannot miss a new text type (the R1
S1 finding). The two sets are disjoint and together exactly the non-exempt
columns of the twelve tables, read off `tables.py` (which
`tests/schema/test_project_report_evidence_migration.py` holds equal to the
revision). A new free-text column fails here until it is listed, which is the
point: a reader (WP4P) must know every column it could disclose.
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from sqlalchemy import (
    ARRAY,
    JSON,
    VARCHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    Unicode,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeEngine

from my_pa.infrastructure.persistence.tables import PROJECT_REPORT_TABLES

#: `(table, column)`: may hold export content.
FREE_TEXT: Final[dict[tuple[str, str], str]] = {
    ("project_report_binding_revisions", "declared_project_number"): "operator-declared number",
    ("project_report_filter_declarations", "slug_label"): "saved-report slug",
    ("project_report_filter_declarations", "description"): "operator filter prose",
    ("project_report_snapshots", "header_raw_record"): "the exact header record",
    ("project_report_snapshots", "header_cells"): "the header cells",
    ("project_report_rows", "raw_record"): "the exact data record",
    ("project_report_rows", "cells"): "the data cells",
    ("project_report_row_roles", "group_key"): "a raw grouping cell",
    ("project_report_row_roles", "group_path"): "raw grouping cells of the path",
    ("project_report_records", "identity_key"): "exported numbers, a vendor name",
    ("project_report_lines", "status_raw"): "the exported status text",
    ("project_report_lines", "identifier_prefix"): "an exported number prefix",
    ("project_report_line_values", "raw_text"): "any catalogued cell",
    ("project_report_line_values", "value_text"): "a typed text cell",
    ("project_report_stated_totals", "raw_text"): "a stated total cell",
    ("project_report_stated_totals", "group_key"): "a raw grouping cell",
}

#: `(table, column)`: held by a CHECK of its table that names it.
STRUCTURED: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        *(
            (table, column)
            for table, columns in {
                "project_report_binding_revisions": (
                    "binding_revision_id",
                    "principal_id",
                    "ingest_source_id",
                    "project_id",
                    "state",
                    "supersedes_revision_id",
                    "currency",
                    "recorded_by",
                    "change_set_sha256",
                    "reason_code",
                ),
                "project_report_filter_declarations": ("principal_id", "binding_revision_id"),
                "project_report_bindings": (
                    "principal_id",
                    "ingest_source_id",
                    "binding_revision_id",
                    "project_id",
                    "state",
                ),
                "project_report_snapshots": (
                    "principal_id",
                    "snapshot_id",
                    "ingest_source_id",
                    "file_sha256",
                    "header_terminator",
                    "header_signature",
                    "signature_version",
                    "reader_version",
                    "reconstruction_sha256",
                ),
                "project_report_rows": ("principal_id", "snapshot_id", "terminator"),
                "project_report_derivations": (
                    "derivation_id",
                    "principal_id",
                    "snapshot_id",
                    "ingest_source_id",
                    "binding_revision_id",
                    "project_id",
                    "state",
                    "quarantine_reason",
                    "record_family",
                    "family_view",
                    "adapter_version",
                    "identity_version",
                    "status_map_version",
                    "completeness_class",
                    "role_counts",
                    "reconciliation",
                    "trigger",
                    "supersedes_derivation_id",
                ),
                "project_report_row_roles": (
                    "principal_id",
                    "derivation_id",
                    "snapshot_id",
                    "row_role",
                    "row_reason",
                ),
                "project_report_records": (
                    "record_id",
                    "principal_id",
                    "project_id",
                    "record_family",
                    "identity_version",
                    "identity_basis",
                    "created_by_derivation_id",
                ),
                "project_report_lines": (
                    "principal_id",
                    "derivation_id",
                    "row_role",
                    "project_id",
                    "record_family",
                    "family_view",
                    "line_kind",
                    "record_id",
                    "identity_state",
                    "identity_reason",
                    "observation_state",
                    "degraded_reasons",
                    "status_class",
                ),
                "project_report_line_values": (
                    "principal_id",
                    "derivation_id",
                    "field_key",
                    "value_kind",
                    "value_reason",
                ),
                "project_report_stated_totals": (
                    "principal_id",
                    "derivation_id",
                    "row_role",
                    "scope",
                    "field_key",
                    "additivity",
                    "outcome",
                ),
                "project_report_cross_checks": (
                    "principal_id",
                    "check_kind",
                    "left_derivation_id",
                    "right_derivation_id",
                    "project_id",
                    "date_label",
                    "outcome",
                ),
            }.items()
            for column in columns
        )
    }
)


#: The only exempt column types: none of them can hold text. `Integer` covers
#: `SmallInteger` and `BigInteger` (its subclasses). A UUID type would join here
#: if the tables used one; they do not.
NON_TEXT_TYPES: Final[tuple[type[TypeEngine[Any]], ...]] = (
    Boolean,
    Integer,
    Numeric,
    Date,
    DateTime,
)


def _text_bearing(tables: tuple[Table, ...]) -> set[tuple[str, str]]:
    """Every column of `tables` not of an explicitly non-text type."""
    return {
        (table.name, column.name)
        for table in tables
        for column in table.c
        if not isinstance(column.type, NON_TEXT_TYPES)
    }


def _unlisted(tables: tuple[Table, ...]) -> set[tuple[str, str]]:
    """The text-bearing columns of `tables` neither inventory lists: must be empty."""
    return _text_bearing(tables) - set(FREE_TEXT) - STRUCTURED


def test_the_twelve_tables_are_the_ones_inventoried() -> None:
    assert len(PROJECT_REPORT_TABLES) == 12


def test_every_text_bearing_column_is_listed_exactly_once() -> None:
    free = set(FREE_TEXT)
    assert not free & STRUCTURED
    assert _unlisted(PROJECT_REPORT_TABLES) == set()
    # And nothing listed is stale (a renamed or dropped column, or an exempt one).
    assert (free | STRUCTURED) - _text_bearing(PROJECT_REPORT_TABLES) == set()


@pytest.mark.parametrize(("table_name", "column"), sorted(STRUCTURED))
def test_a_structured_column_is_held_by_a_check_that_names_it(table_name: str, column: str) -> None:
    table = next(t for t in PROJECT_REPORT_TABLES if t.name == table_name)
    checks = [
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    assert any(
        text.startswith(f"{column} ") or f"({column} " in text or f" {column} " in text
        for text in checks
    ), (table_name, column)


@pytest.mark.parametrize(
    "planted_type",
    [String(200), VARCHAR(40), Unicode(200), Text(), JSON(), JSONB(), ARRAY(Text())],
    ids=lambda t: type(t).__name__,
)
def test_a_planted_text_column_of_any_type_fails_the_inventory(
    planted_type: TypeEngine[Any],
) -> None:
    """The real check, on a throwaway table: an unlisted text column of any type is seen,
    while the exempt types beside it are not."""
    planted = Table(
        "project_report_lines",
        MetaData(),
        Column("planted_minutes", planted_type),
        Column("planted_count", Integer),
        Column("planted_small", SmallInteger),
        Column("planted_big", BigInteger),
        Column("planted_flag", Boolean),
        Column("planted_amount", Numeric(20, 4)),
        Column("planted_day", Date),
        Column("planted_at", DateTime(timezone=True)),
    )
    assert _unlisted((planted,)) == {("project_report_lines", "planted_minutes")}
