"""SQLite declared types, boolean promotion, and column defaults.

Every column in every migratable source table is declared ``TEXT``, ``INTEGER``,
or ``REAL``, so the type map is a three-entry lookup rather than a heuristic
(OD-009). Unknown declarations fail closed instead of falling back to ``text``.

An ``INTEGER`` column becomes ``boolean`` only where the source carries a CHECK
constraint restricting it to 0/1 (OD-015). A column that merely happens to hold
0 and 1 today is not thereby a boolean, and a name like ``is_active`` is not
evidence of anything.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from my_pa.infrastructure.migration.sqlite_ddl import CheckConstraint

SQLITE_TO_POSTGRES: Mapping[str, str] = {
    "TEXT": "text",
    "INTEGER": "bigint",
    "REAL": "double precision",
}

BOOLEAN_TYPE = "boolean"
INTEGER_IDENTITY_TYPE = "bigint"

#: SQLite's ``CURRENT_TIMESTAMP`` and ``datetime('now')`` both render UTC as
#: ``YYYY-MM-DD HH:MM:SS`` text. The legacy columns are ``TEXT``, so the target
#: default has to produce the same text rather than a ``timestamptz``.
_UTC_TEXT_NOW = "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"

_BOOLEAN_CHECK = re.compile(
    r"""^\(\s*(?:"(?P<quoted>[^"]+)"|(?P<bare>[A-Za-z_][A-Za-z0-9_]*))\s*
        IN\s*\(\s*(?P<first>[01])\s*,\s*(?P<second>[01])\s*\)\s*\)$""",
    re.IGNORECASE | re.VERBOSE,
)
_NUMERIC_LITERAL = re.compile(r"^-?\d+(\.\d+)?$")
_STRING_LITERAL = re.compile(r"^'([^']|'')*'$")
_SQLITE_NOW = re.compile(r"^datetime\s*\(\s*'now'\s*\)$", re.IGNORECASE)


class TypeMappingError(RuntimeError):
    """A source type or default has no defensible PostgreSQL equivalent."""


def map_declared_type(declared: str) -> str:
    """Return the PostgreSQL type for a SQLite declared type."""
    mapped = SQLITE_TO_POSTGRES.get(declared.strip().upper())
    if mapped is None:
        raise TypeMappingError(f"no mapping for declared SQLite type {declared!r}")
    return mapped


def _check_target_column(expression: str) -> str | None:
    """Return the column a ``x IN (0, 1)`` CHECK constrains, if that is its shape."""
    match = _BOOLEAN_CHECK.match(" ".join(expression.split()))
    if match is None:
        return None
    if {match.group("first"), match.group("second")} != {"0", "1"}:
        return None
    return match.group("quoted") or match.group("bare")


def boolean_promotions(
    checks: Iterable[CheckConstraint],
    integer_columns: Iterable[str],
) -> frozenset[str]:
    """Return the ``INTEGER`` columns a CHECK constrains to exactly 0 and 1."""
    integers = frozenset(integer_columns)
    promoted = set()
    for check in checks:
        column = _check_target_column(check.expression)
        if column is not None and column in integers:
            promoted.add(column)
    return frozenset(promoted)


def is_boolean_check(expression: str) -> bool:
    """True when the expression is the ``x IN (0, 1)`` form that justifies a promotion."""
    return _check_target_column(expression) is not None


def translate_default(default: str, target_type: str) -> str:
    """Return the PostgreSQL default expression for a SQLite column default."""
    text = " ".join(default.split())
    if text.upper() == "CURRENT_TIMESTAMP" or _SQLITE_NOW.match(text):
        if target_type != "text":
            raise TypeMappingError(f"timestamp default {default!r} on {target_type} column")
        return _UTC_TEXT_NOW
    if target_type == BOOLEAN_TYPE:
        if text == "0":
            return "false"
        if text == "1":
            return "true"
        raise TypeMappingError(f"default {default!r} on a promoted boolean column")
    if _NUMERIC_LITERAL.match(text) or _STRING_LITERAL.match(text):
        return text
    raise TypeMappingError(f"unsupported column default {default!r}")
