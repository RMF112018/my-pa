"""Rewriting CHECK and index predicates: quoting, renames, and boolean literals."""

from __future__ import annotations

import pytest

from my_pa.infrastructure.migration.expressions import (
    ExpressionError,
    rewrite,
    uses_sqlite_only_function,
)


def test_column_references_are_quoted() -> None:
    assert rewrite("(status IN ('open'))", {"status": "status"}) == "(\"status\" IN ('open'))"


def test_a_reserved_word_column_needs_no_rename() -> None:
    assert rewrite('("column" IS NULL)', {"column": "column"}) == '("column" IS NULL)'
    assert rewrite("(column IS NULL)", {"column": "column"}) == '("column" IS NULL)'


def test_a_shortened_column_is_rewritten_to_its_target_name() -> None:
    rewritten = rewrite("(long_name > 0)", {"long_name": "long_na_1a2b3c4"})

    assert rewritten == '("long_na_1a2b3c4" > 0)'


def test_a_function_name_is_not_mistaken_for_a_column() -> None:
    columns = {"coalesce": "coalesce", "b": "b"}

    assert rewrite("COALESCE(b, '')", columns) == "COALESCE(\"b\", '')"


def test_a_string_literal_matching_a_column_name_is_left_alone() -> None:
    assert rewrite("(status IN ('status'))", {"status": "status"}) == "(\"status\" IN ('status'))"


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("(is_current = 1)", '("is_current" = true)'),
        ("(is_current = 0)", '("is_current" = false)'),
        ("is_active=1", '"is_active"=true'),
        ("(is_current <> 0)", '("is_current" <> false)'),
        ("(is_current IN (0, 1))", '("is_current" IN (false, true))'),
    ],
)
def test_literals_compared_against_a_promoted_boolean_become_true_or_false(
    expression: str, expected: str
) -> None:
    columns = {"is_current": "is_current", "is_active": "is_active"}
    booleans = frozenset({"is_current", "is_active"})

    assert rewrite(expression, columns, booleans) == expected


def test_an_unpromoted_integer_keeps_its_literal() -> None:
    assert rewrite("(is_active = 1)", {"is_active": "is_active"}) == '("is_active" = 1)'


def test_a_boolean_column_used_without_a_comparison_is_untouched() -> None:
    columns = {"is_current": "is_current", "closed_at": "closed_at"}
    booleans = frozenset({"is_current"})

    assert rewrite("(is_current IS NULL)", columns, booleans) == '("is_current" IS NULL)'


def test_an_out_of_range_literal_on_a_boolean_fails_closed() -> None:
    with pytest.raises(ExpressionError, match="compared against a boolean"):
        rewrite("(flag = 2)", {"flag": "flag"}, frozenset({"flag"}))


@pytest.mark.parametrize(
    "expression",
    ["(json_valid(payload))", "(datetime(created_at) > 0)", "(typeof(x) = 'text')"],
)
def test_sqlite_only_functions_are_detected(expression: str) -> None:
    assert uses_sqlite_only_function(expression)


@pytest.mark.parametrize(
    "expression",
    [
        "(length(excerpt) > 0)",
        "(status IN ('open'))",
        "(datetime IS NULL)",
        "(amount BETWEEN 0 AND 10)",
    ],
)
def test_portable_expressions_are_not_flagged(expression: str) -> None:
    """`datetime` as a bare column name is not a call to SQLite's `datetime()`."""
    assert not uses_sqlite_only_function(expression)
