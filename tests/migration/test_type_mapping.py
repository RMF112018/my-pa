"""Declared-type mapping, boolean promotion, and default translation."""

from __future__ import annotations

import pytest

from my_pa.infrastructure.migration.sqlite_ddl import CheckConstraint
from my_pa.infrastructure.migration.type_mapping import (
    TypeMappingError,
    boolean_promotions,
    is_boolean_check,
    map_declared_type,
    translate_default,
)


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        ("TEXT", "text"),
        ("text", "text"),
        ("INTEGER", "bigint"),
        ("REAL", "double precision"),
    ],
)
def test_the_three_declared_types_map_directly(declared: str, expected: str) -> None:
    assert map_declared_type(declared) == expected


@pytest.mark.parametrize("declared", ["", "BLOB", "NUMERIC", "TIMESTAMP", "JSON"])
def test_an_unmapped_declared_type_fails_closed(declared: str) -> None:
    """No silent fallback to `text`: the profile says these do not occur."""
    with pytest.raises(TypeMappingError, match="no mapping"):
        map_declared_type(declared)


@pytest.mark.parametrize(
    "expression",
    ["(is_current IN (0, 1))", "(is_current IN (1,0))", '("is_current" in ( 0 , 1 ))'],
)
def test_a_zero_or_one_check_justifies_a_boolean(expression: str) -> None:
    assert boolean_promotions([CheckConstraint(expression, None)], ["is_current"]) == {"is_current"}
    assert is_boolean_check(expression)


@pytest.mark.parametrize(
    "expression",
    [
        "(external_writeback_performed = 0)",
        "(retry_count IN (1, 2, 3))",
        "(is_current IN (0, 2))",
        "(is_current >= 0)",
        "(status IN ('open', 'closed'))",
    ],
)
def test_other_checks_leave_the_column_an_integer(expression: str) -> None:
    """OD-015: only an explicit 0/1 restriction is evidence of a boolean."""
    columns = ["external_writeback_performed", "retry_count", "is_current", "status"]
    assert boolean_promotions([CheckConstraint(expression, None)], columns) == frozenset()
    assert not is_boolean_check(expression)


def test_a_check_on_a_text_column_is_not_a_promotion() -> None:
    assert boolean_promotions([CheckConstraint("(flag IN (0, 1))", None)], ["other"]) == frozenset()


@pytest.mark.parametrize(
    ("default", "target_type", "expected"),
    [
        ("0", "bigint", "0"),
        ("30", "bigint", "30"),
        ("0.0", "double precision", "0.0"),
        ("'pending'", "text", "'pending'"),
        ("'[]'", "text", "'[]'"),
        ("0", "boolean", "false"),
        ("1", "boolean", "true"),
    ],
)
def test_literal_defaults_carry_through(default: str, target_type: str, expected: str) -> None:
    assert translate_default(default, target_type) == expected


@pytest.mark.parametrize("default", ["CURRENT_TIMESTAMP", "datetime('now')", "datetime( 'now' )"])
def test_a_timestamp_default_keeps_the_legacy_utc_text_format(default: str) -> None:
    """The source columns are TEXT holding `YYYY-MM-DD HH:MM:SS` in UTC."""
    assert (
        translate_default(default, "text")
        == "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"
    )


def test_a_timestamp_default_on_a_non_text_column_fails_closed() -> None:
    with pytest.raises(TypeMappingError, match="timestamp default"):
        translate_default("CURRENT_TIMESTAMP", "bigint")


def test_an_unrecognised_default_fails_closed() -> None:
    with pytest.raises(TypeMappingError, match="unsupported column default"):
        translate_default("random()", "bigint")


def test_a_non_binary_default_on_a_boolean_fails_closed() -> None:
    with pytest.raises(TypeMappingError, match="promoted boolean"):
        translate_default("2", "boolean")
