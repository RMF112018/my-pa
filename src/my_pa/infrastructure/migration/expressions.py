"""Rewrite SQLite CHECK and index predicates for PostgreSQL.

Two things change. Column references are re-quoted so that reserved words such
as ``procore_ep_budget_change_history."column"`` and any name shortened to fit
63 bytes still resolve. And where a column was promoted to ``boolean``, the 0/1
literals it is compared against become ``false``/``true``, because
``is_active = 1`` is a type error in PostgreSQL.

Nothing else is translated: the source predicates are ``IN (...)``, comparison,
``IS NULL``, ``BETWEEN``, and ``length()`` forms that are already valid
PostgreSQL. Anything containing a SQLite-only function is refused rather than
emulated, so the caller can drop it and record it (OD-016).
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from my_pa.infrastructure.migration.identifiers import quote

#: Functions and pseudo-columns with no PostgreSQL equivalent. A CHECK that uses
#: one cannot be ported and must be dropped and recorded verbatim.
SQLITE_ONLY_FUNCTIONS = frozenset(
    {
        "changes",
        "date",
        "datetime",
        "glob",
        "hex",
        "ifnull",
        "iif",
        "instr",
        "json_array_length",
        "json_extract",
        "json_quote",
        "json_type",
        "json_valid",
        "julianday",
        "last_insert_rowid",
        "likelihood",
        "likely",
        "printf",
        "randomblob",
        "sqlite_version",
        "strftime",
        "time",
        "total_changes",
        "typeof",
        "unicode",
        "unixepoch",
        "unlikely",
        "zeroblob",
    }
)

_COMPARISONS = frozenset({"=", "==", "<>", "!=", ">", "<", ">=", "<="})
_TOKEN = re.compile(
    r"""
      (?P<space>\s+)
    | (?P<string>'([^']|'')*')
    | (?P<quoted>"([^"]|"")*")
    | (?P<name>[A-Za-z_][A-Za-z0-9_$]*)
    | (?P<number>\d+(\.\d+)?)
    | (?P<operator><=|>=|<>|!=|==|.)
    """,
    re.VERBOSE | re.DOTALL,
)


class ExpressionError(RuntimeError):
    """An expression cannot be represented in PostgreSQL."""


def _tokenise(expression: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    position = 0
    while position < len(expression):
        match = _TOKEN.match(expression, position)
        if match is None or match.end() == position:
            raise ExpressionError(f"cannot tokenise {expression!r} at offset {position}")
        kind = match.lastgroup or "operator"
        tokens.append((kind, match.group(0)))
        position = match.end()
    return tokens


def uses_sqlite_only_function(expression: str) -> bool:
    """True when the expression calls a function PostgreSQL does not provide."""
    tokens = _tokenise(expression)
    for index, (kind, text) in enumerate(tokens):
        if kind != "name" or text.lower() not in SQLITE_ONLY_FUNCTIONS:
            continue
        if _next_significant(tokens, index) == "(":
            return True
    return False


def _next_significant(tokens: list[tuple[str, str]], index: int) -> str | None:
    for kind, text in tokens[index + 1 :]:
        if kind != "space":
            return text
    return None


def rewrite(
    expression: str,
    columns: Mapping[str, str],
    boolean_columns: frozenset[str] = frozenset(),
) -> str:
    """Return ``expression`` with columns re-quoted and boolean literals corrected.

    ``columns`` maps a source column name to its target name.
    """
    tokens = _tokenise(expression)
    output: list[str] = []
    index = 0
    while index < len(tokens):
        kind, text = tokens[index]
        if kind == "name" and text in columns and _next_significant(tokens, index) != "(":
            output.append(quote(columns[text]))
            if text in boolean_columns:
                index = _rewrite_boolean_operand(tokens, index, output)
                continue
        else:
            output.append(text)
        index += 1
    return "".join(output)


def _rewrite_boolean_operand(
    tokens: list[tuple[str, str]],
    index: int,
    output: list[str],
) -> int:
    """Emit the comparison following a promoted boolean column with 0/1 as false/true.

    Returns the index of the next token the caller should process.
    """
    cursor = index + 1
    pending: list[str] = []
    while cursor < len(tokens) and tokens[cursor][0] == "space":
        pending.append(tokens[cursor][1])
        cursor += 1
    if cursor >= len(tokens):
        output.extend(pending)
        return cursor
    kind, text = tokens[cursor]
    if kind == "operator" and text in _COMPARISONS:
        pending.append(text)
        cursor += 1
        while cursor < len(tokens) and tokens[cursor][0] == "space":
            pending.append(tokens[cursor][1])
            cursor += 1
        if cursor < len(tokens) and tokens[cursor][0] == "number":
            pending.append(_boolean_literal(tokens[cursor][1]))
            cursor += 1
        output.extend(pending)
        return cursor
    if kind == "name" and text.upper() == "IN":
        pending.append(text)
        cursor += 1
        depth = 0
        while cursor < len(tokens):
            inner_kind, inner_text = tokens[cursor]
            if inner_text == "(":
                depth += 1
            elif inner_text == ")":
                depth -= 1
            pending.append(
                _boolean_literal(inner_text) if inner_kind == "number" and depth else inner_text
            )
            cursor += 1
            if depth == 0 and inner_text == ")":
                break
        output.extend(pending)
        return cursor
    output.extend(pending)
    return cursor


def _boolean_literal(text: str) -> str:
    if text == "0":
        return "false"
    if text == "1":
        return "true"
    raise ExpressionError(f"literal {text!r} compared against a boolean column")
