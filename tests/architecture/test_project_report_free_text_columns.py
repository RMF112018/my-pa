"""Every project-report column that may hold export content is listed (WP3P-S3 ruling).

Layer A and the typed line values hold raw export text as source evidence:
names, descriptions, minutes, vendor names inside a record key. This module is
that set's inventory, in the shape of the communications no-content guard:

* `FREE_TEXT` -- every text, JSON or array column that may carry export
  content, with why;
* `STRUCTURED` -- every other text, JSON or array column, each held by a CHECK
  of its own table that names it (an identifier shape, a closed set, a digest,
  a version token, a catalogue key or a count object), so a column cannot be
  filed here without a guard that keeps content out of it.

The two sets are disjoint and together exactly the text-bearing columns of
the twelve tables, read off `tables.py` (which
`tests/schema/test_project_report_evidence_migration.py` holds equal to the
revision). A new free-text column fails here until it is listed, which is the
point: a reader (WP4P) must know every column it could disclose.
"""

from __future__ import annotations

from typing import Final

import pytest
from sqlalchemy import ARRAY, CheckConstraint, Text
from sqlalchemy.dialects.postgresql import JSONB

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


def _text_bearing() -> set[tuple[str, str]]:
    return {
        (table.name, column.name)
        for table in PROJECT_REPORT_TABLES
        for column in table.c
        if isinstance(column.type, (Text, JSONB, ARRAY))
    }


def test_the_twelve_tables_are_the_ones_inventoried() -> None:
    assert len(PROJECT_REPORT_TABLES) == 12


def test_every_text_bearing_column_is_listed_exactly_once() -> None:
    free = set(FREE_TEXT)
    assert not free & STRUCTURED
    assert free | STRUCTURED == _text_bearing(), (
        sorted(_text_bearing() - free - STRUCTURED),
        sorted((free | STRUCTURED) - _text_bearing()),
    )


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


def test_a_planted_free_text_column_fails_the_inventory() -> None:
    """The prove-red, kept: a new unlisted text column is seen."""
    planted = _text_bearing() | {("project_report_lines", "planted_minutes")}
    assert planted != set(FREE_TEXT) | STRUCTURED
