"""Read the parts of a SQLite ``CREATE`` statement that ``PRAGMA`` does not expose.

``PRAGMA table_info`` gives columns, types, defaults, and the primary key, and
``PRAGMA index_list``/``index_info`` give indexes -- but neither reports CHECK
constraints or ``AUTOINCREMENT``. Those only exist in the stored statement text,
so this module tokenises it.

The scope is deliberately narrow: split a statement body on top-level commas
while respecting string literals, quoted identifiers, comments, and nesting;
recognise which items are column definitions and which are table constraints;
and pull out the CHECK expressions verbatim. It is not a general SQL parser and
fails closed on anything it does not recognise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TABLE_CONSTRAINT_KEYWORDS = frozenset({"PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT"})
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


class SqliteDdlError(RuntimeError):
    """A stored SQLite statement could not be read."""


@dataclass(frozen=True)
class CheckConstraint:
    """A CHECK constraint as written in the source, with its owning column if any."""

    expression: str
    column: str | None


@dataclass(frozen=True)
class ParsedTable:
    """The parts of ``CREATE TABLE`` that the pragmas do not report."""

    checks: tuple[CheckConstraint, ...]
    autoincrement_columns: frozenset[str]


def strip_comments(sql: str) -> str:
    """Remove ``--`` and ``/* */`` comments, preserving string and quoted-identifier bodies."""
    out: list[str] = []
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if char in "'\"`":
            end = _scan_quoted(sql, index)
            out.append(sql[index:end])
            index = end
        elif sql.startswith("--", index):
            end = sql.find("\n", index)
            index = length if end == -1 else end
        elif sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            index = length if end == -1 else end + 2
            out.append(" ")
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _scan_quoted(sql: str, start: int) -> int:
    """Return the index just past the quoted run beginning at ``start``."""
    quote_char = sql[start]
    index = start + 1
    while index < len(sql):
        if sql[index] == quote_char:
            if index + 1 < len(sql) and sql[index + 1] == quote_char:
                index += 2
                continue
            return index + 1
        index += 1
    raise SqliteDdlError(f"unterminated {quote_char} quoted text")


def body_of(sql: str) -> str:
    """Return the text inside the outermost parentheses of a ``CREATE`` statement."""
    clean = strip_comments(sql)
    start = _find_top_level(clean, "(")
    if start is None:
        raise SqliteDdlError("statement has no parenthesised body")
    end = matching_paren(clean, start)
    return clean[start + 1 : end]


def _find_top_level(sql: str, target: str) -> int | None:
    index = 0
    while index < len(sql):
        char = sql[index]
        if char in "'\"`":
            index = _scan_quoted(sql, index)
        elif char == target:
            return index
        else:
            index += 1
    return None


def matching_paren(sql: str, open_index: int) -> int:
    """Return the index of the ``)`` closing the ``(`` at ``open_index``."""
    depth = 0
    index = open_index
    while index < len(sql):
        char = sql[index]
        if char in "'\"`":
            index = _scan_quoted(sql, index)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise SqliteDdlError("unbalanced parentheses")


def split_top_level(body: str) -> tuple[str, ...]:
    """Split ``body`` on commas that are not nested inside parentheses or quotes."""
    items: list[str] = []
    depth = 0
    start = 0
    index = 0
    while index < len(body):
        char = body[index]
        if char in "'\"`":
            index = _scan_quoted(body, index)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            items.append(body[start:index])
            start = index + 1
        index += 1
    items.append(body[start:])
    return tuple(item.strip() for item in items if item.strip())


def first_word(item: str) -> str:
    match = _IDENTIFIER.match(item.lstrip())
    return match.group(0).upper() if match else ""


def leading_identifier(item: str) -> str:
    """Return the column name a column definition starts with."""
    text = item.lstrip()
    if text[:1] in '"`':
        end = _scan_quoted(text, 0)
        return text[1 : end - 1].replace(text[0] * 2, text[0])
    match = _IDENTIFIER.match(text)
    if match is None:
        raise SqliteDdlError(f"cannot read a column name from {item!r}")
    return match.group(0)


def _extract_checks(item: str) -> tuple[str, ...]:
    """Return every ``CHECK (...)`` expression in ``item``, parentheses included."""
    found: list[str] = []
    index = 0
    while index < len(item):
        char = item[index]
        if char in "'\"`":
            index = _scan_quoted(item, index)
            continue
        if item[index : index + 5].upper() == "CHECK" and _is_word_boundary(item, index, 5):
            open_index = item.find("(", index + 5)
            if open_index == -1:
                raise SqliteDdlError(f"CHECK without an expression in {item!r}")
            close_index = matching_paren(item, open_index)
            found.append(item[open_index : close_index + 1])
            index = close_index + 1
            continue
        index += 1
    return tuple(found)


def _is_word_boundary(text: str, start: int, length: int) -> bool:
    before = text[start - 1] if start else " "
    after = text[start + length] if start + length < len(text) else " "
    return not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_")


def parse_table(sql: str) -> ParsedTable:
    """Extract CHECK constraints and AUTOINCREMENT columns from ``CREATE TABLE`` text."""
    checks: list[CheckConstraint] = []
    autoincrement: set[str] = set()
    for item in split_top_level(body_of(sql)):
        if first_word(item) in _TABLE_CONSTRAINT_KEYWORDS:
            checks.extend(CheckConstraint(expression, None) for expression in _extract_checks(item))
            continue
        column = leading_identifier(item)
        checks.extend(CheckConstraint(expression, column) for expression in _extract_checks(item))
        if re.search(r"\bAUTOINCREMENT\b", item, re.IGNORECASE):
            autoincrement.add(column)
    return ParsedTable(tuple(checks), frozenset(autoincrement))


@dataclass(frozen=True)
class ParsedIndex:
    """The column list and optional predicate of a ``CREATE INDEX`` statement."""

    key_expressions: tuple[str, ...]
    predicate: str | None


def parse_index(sql: str) -> ParsedIndex:
    """Extract the key expressions and ``WHERE`` predicate from ``CREATE INDEX`` text."""
    clean = strip_comments(sql)
    open_index = _find_top_level(clean, "(")
    if open_index is None:
        raise SqliteDdlError("CREATE INDEX has no key list")
    close_index = matching_paren(clean, open_index)
    keys = split_top_level(clean[open_index + 1 : close_index])
    tail = clean[close_index + 1 :].strip()
    predicate: str | None = None
    if tail:
        match = re.match(r"WHERE\b(.*)", tail, re.IGNORECASE | re.DOTALL)
        if match is None:
            raise SqliteDdlError(f"unsupported CREATE INDEX tail {tail!r}")
        predicate = " ".join(match.group(1).split())
    return ParsedIndex(tuple(" ".join(key.split()) for key in keys), predicate)
