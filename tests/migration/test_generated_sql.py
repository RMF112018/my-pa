"""The committed SQL agrees with the committed registry and carries nothing private.

The revisions execute these files, so they are the artefact review actually sees.
Needs no database.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from my_pa.infrastructure.migration.identifiers import MAX_IDENTIFIER_BYTES
from my_pa.infrastructure.migration.source import load_registry
from my_pa.infrastructure.migration.sql_files import SqlFileError, read_statements, write_statements

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "migrations" / "sql"
REGISTRY_PATH = ROOT / "migrations" / "data" / "disposition_registry.json"

STEPS = ("target_tables", "target_indexes", "target_foreign_keys")
CREATE_TABLE = re.compile(r'^CREATE TABLE "(?P<schema>[^"]+)"\."(?P<table>[^"]+)"', re.MULTILINE)


def _all_statements() -> list[str]:
    statements: list[str] = []
    for step in STEPS:
        for half in ("up", "down"):
            statements.extend(read_statements(SQL_DIR / f"{step}.{half}.sql"))
    return statements


def test_each_step_has_an_upgrade_and_a_matching_downgrade() -> None:
    for step in STEPS:
        up = read_statements(SQL_DIR / f"{step}.up.sql")
        down = read_statements(SQL_DIR / f"{step}.down.sql")
        assert up, f"{step} has no statements"
        assert len(up) == len(down), f"{step} does not undo itself statement for statement"


def test_the_tables_created_are_exactly_the_ones_the_registry_marks_for_creation() -> None:
    registry = load_registry(REGISTRY_PATH)
    expected = {
        (entry.target_schema, entry.legacy_object)
        for entry in registry.values()
        if entry.created and entry.object_type == "table"
    }

    created = {
        (match.group("schema"), match.group("table"))
        for statement in read_statements(SQL_DIR / "target_tables.up.sql")
        for match in CREATE_TABLE.finditer(statement)
    }

    assert created == expected


def test_no_view_is_created_as_a_table() -> None:
    """OD-018: the two SQLite read models are hand-ported, not generated."""
    registry = load_registry(REGISTRY_PATH)
    views = {entry.legacy_object for entry in registry.values() if entry.object_type == "view"}
    created = {
        match.group("table")
        for statement in read_statements(SQL_DIR / "target_tables.up.sql")
        for match in CREATE_TABLE.finditer(statement)
    }

    assert views
    assert not (views & created)


def test_every_quoted_identifier_fits_the_budget() -> None:
    for statement in _all_statements():
        for identifier in statement.split('"')[1::2]:
            assert len(identifier.encode("utf-8")) <= MAX_IDENTIFIER_BYTES, identifier


def test_no_former_employer_branding_reaches_the_target_schema() -> None:
    pattern = re.compile(r"\bhb\b|\bhb[-_]|hbintel|hedrick", re.IGNORECASE)
    for step in STEPS:
        for half in ("up", "down"):
            text = (SQL_DIR / f"{step}.{half}.sql").read_text(encoding="utf-8")
            assert not pattern.search(text), f"{step}.{half}.sql names a legacy identity"


def test_the_sql_carries_no_personal_path_or_credential() -> None:
    pattern = re.compile(r"/Users/|/Volumes/|postgres://|password", re.IGNORECASE)
    for step in STEPS:
        for half in ("up", "down"):
            text = (SQL_DIR / f"{step}.{half}.sql").read_text(encoding="utf-8")
            assert not pattern.search(text)


def test_statements_round_trip_through_the_file_format(tmp_path: Path) -> None:
    statements = ('CREATE TABLE "a"."b" (\n    "c" text\n);', 'DROP TABLE "a"."b" CASCADE;')
    path = tmp_path / "round.sql"

    write_statements(path, statements)

    assert read_statements(path) == statements


def test_an_embedded_semicolon_is_refused(tmp_path: Path) -> None:
    """Splitting has to be exact, so a statement that would break it is rejected."""
    with pytest.raises(SqlFileError, match="embedded ';'"):
        write_statements(tmp_path / "bad.sql", ["SELECT 1; SELECT 2;"])
