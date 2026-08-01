"""Reading CHECK constraints, AUTOINCREMENT, and index shapes out of stored SQL."""

from __future__ import annotations

import pytest

from my_pa.infrastructure.migration.sqlite_ddl import (
    SqliteDdlError,
    parse_index,
    parse_table,
    split_top_level,
    strip_comments,
)

TABLE = """
CREATE TABLE example (
  record_key TEXT PRIMARY KEY,   -- the natural key
  status TEXT NOT NULL CHECK(status IN ('open', 'closed, pending')),
  is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0, 1)),
  "column" TEXT,
  created_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(record_key, status),
  CHECK (created_utc IS NOT NULL OR status IS NULL),
  FOREIGN KEY(record_key) REFERENCES other(record_key)
)
"""


def test_column_and_table_checks_are_read_with_their_owner() -> None:
    parsed = parse_table(TABLE)

    assert [(check.column, check.expression) for check in parsed.checks] == [
        ("status", "(status IN ('open', 'closed, pending'))"),
        ("is_current", "(is_current IN (0, 1))"),
        (None, "(created_utc IS NOT NULL OR status IS NULL)"),
    ]


def test_a_comma_inside_a_string_literal_does_not_split_a_column() -> None:
    """`'closed, pending'` is one value, not the end of a column definition."""
    items = split_top_level("a TEXT CHECK(a IN ('x, y')), b TEXT")

    assert items == ("a TEXT CHECK(a IN ('x, y'))", "b TEXT")


def test_comments_are_removed_but_string_bodies_survive() -> None:
    assert strip_comments("a -- note\nb") == "a \nb"
    assert strip_comments("x = '-- not a comment'") == "x = '-- not a comment'"


def test_autoincrement_is_reported_for_the_column_that_declares_it() -> None:
    parsed = parse_table("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")

    assert parsed.autoincrement_columns == {"id"}


def test_a_table_without_autoincrement_reports_none() -> None:
    assert (
        parse_table("CREATE TABLE t (id INTEGER PRIMARY KEY)").autoincrement_columns == frozenset()
    )


def test_a_quoted_table_name_does_not_confuse_the_body_scan() -> None:
    parsed = parse_table("CREATE TABLE \"t\" (a TEXT CHECK(a IN ('q')))")

    assert [check.expression for check in parsed.checks] == ["(a IN ('q'))"]


def test_unbalanced_parentheses_fail_closed() -> None:
    with pytest.raises(SqliteDdlError, match="unbalanced"):
        parse_table("CREATE TABLE t (a TEXT")


def test_a_partial_index_keeps_its_predicate() -> None:
    parsed = parse_index(
        "CREATE UNIQUE INDEX i ON t(project_key, slot_key)\n     WHERE is_active = 1"
    )

    assert parsed.key_expressions == ("project_key", "slot_key")
    assert parsed.predicate == "is_active = 1"


def test_an_expression_key_survives_as_written() -> None:
    parsed = parse_index("CREATE UNIQUE INDEX i ON t(a, COALESCE(b, ''))")

    assert parsed.key_expressions == ("a", "COALESCE(b, '')")
    assert parsed.predicate is None
