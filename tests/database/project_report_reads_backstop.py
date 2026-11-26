"""A runtime backstop for the current-derivations rule (ruling R2-02).

`tests/architecture/test_project_report_reads_use_current_derivations.py`
parses the read modules; this listener checks what they actually send. While
it is installed, every statement the project-report read repository executes
(`before_cursor_execute`, issued from
`infrastructure/persistence/project_report_reads.py`) that names one of the
five child tables (lines, line values, row roles, stated totals,
cross-checks) must filter on `project_report_current_derivations`
(`filters_on_the_view`). A violation is raised at once (the read fails) and
also recorded, so a caller that swallows the error still fails the test at
teardown.

Ruling R3-01: "filters" means an inner (or plain) `JOIN <the view>` whose ON
equates a `derivation_id` with a `derivation_id` (or `USING (derivation_id)`),
never a LEFT, RIGHT, FULL, CROSS or NATURAL join and never an ON clause under
`OR` or `NOT` (`inner_joins_view`, which the static guard applies to `text()`
too); or a semi-join, `EXISTS (SELECT ... FROM <the view> WHERE ...
derivation_id = ...derivation_id)` or `derivation_id IN (SELECT
...derivation_id FROM <the view>)`, not preceded by `NOT`. The text check
cannot see an `OR` around a semi-join; that shape is the static guard's to
refuse.

The DB read suites install it for every test (an autouse fixture in each).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from sqlalchemy import event
from sqlalchemy.engine import Engine

READS_MODULE: Final = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "my_pa"
    / "infrastructure"
    / "persistence"
    / "project_report_reads.py"
)
_CHILD: Final = re.compile(
    r"\bproject_report_(?:lines|line_values|row_roles|stated_totals|cross_checks)\b"
)
_NAMED_VIEW: Final = r'(?:"?knowledge"?\.)?"?project_report_current_derivations\b"?'
_MODIFIER: Final = r"(?:LEFT|RIGHT|FULL|CROSS|NATURAL|INNER)\s+(?:OUTER\s+)?"
#: `<kind> JOIN <the view> [alias] ON <clause>` or `... USING (derivation_id)`; the
#: clause runs to the next join, WHERE, GROUP BY, ORDER BY, LIMIT, `)` or the end.
_JOIN_OF_VIEW: Final = re.compile(
    rf"(?P<kind>\b{_MODIFIER})?\bJOIN\s+{_NAMED_VIEW}"
    r'(?:\s+(?:AS\s+)?(?!ON\b|USING\b)"?\w+"?)?\s+'
    rf"(?:ON\b(?P<on>.*?)(?=\b(?:{_MODIFIER})?JOIN\b|\bWHERE\b|\bGROUP\s+BY\b"
    r"|\bORDER\s+BY\b|\bLIMIT\b|\)|\Z)"
    r'|USING\s*\(\s*"?derivation_id"?\s*\))',
    re.IGNORECASE | re.DOTALL,
)
#: `<...>derivation_id = <...>derivation_id`, qualified or not, quoted or not.
_DERIVATION_EQUATION: Final = re.compile(
    r'[\w."]*derivation_id"?\s*=\s*[\w."]*derivation_id\b', re.IGNORECASE
)
_OR_NOT: Final = re.compile(r"\b(?:OR|NOT)\b", re.IGNORECASE)
#: `EXISTS (SELECT ... )`, with one level of nested parentheses (bound parameters).
_EXISTS: Final = re.compile(
    r"\bEXISTS\s*\(\s*SELECT\b(?P<body>[^()]*(?:\([^()]*\)[^()]*)*)\)",
    re.IGNORECASE,
)
#: What a negated semi-join ends in: `NOT EXISTS` or `NOT (EXISTS`.
_NEGATED: Final = re.compile(r"\bNOT\s*\(?\s*\Z", re.IGNORECASE)
_FROM_VIEW: Final = re.compile(rf"\bFROM\s+{_NAMED_VIEW}(?:\s|$)", re.IGNORECASE)
#: `<...>derivation_id IN (SELECT <...>derivation_id FROM <the view>` (a `NOT IN` never matches).
_IN_VIEW: Final = re.compile(
    rf'derivation_id"?\s+IN\s*\(\s*SELECT\s+[\w."]*derivation_id"?\s+FROM\s+{_NAMED_VIEW}',
    re.IGNORECASE,
)


def inner_joins_view(sql: str) -> bool:
    """`sql` inner-joins the view on `derivation_id` (ruling R3-01)."""
    for match in _JOIN_OF_VIEW.finditer(" ".join(sql.split())):
        kind = (match.group("kind") or "").split()
        if kind and kind[0].upper() != "INNER":
            continue
        on = match.group("on")
        if on is None or (_DERIVATION_EQUATION.search(on) and not _OR_NOT.search(on)):
            return True
    return False


def filters_on_the_view(sql: str) -> bool:
    """`sql` inner-joins the view on `derivation_id`, or semi-joins it on one."""
    if inner_joins_view(sql):
        return True
    flat = " ".join(sql.split())
    if _IN_VIEW.search(flat):
        return True
    for match in _EXISTS.finditer(flat):
        if _NEGATED.search(flat[: match.start()]):
            continue
        body = match.group("body")
        where = re.split(r"\bWHERE\b", body, maxsplit=1, flags=re.IGNORECASE)
        if (
            _FROM_VIEW.search(where[0])
            and len(where) == 2
            and _DERIVATION_EQUATION.search(where[1])
            and not _OR_NOT.search(where[1])
        ):
            return True
    return False


@dataclass
class Backstop:
    """What the listener saw: the child-table statements checked, and the violations."""

    checked: int = 0
    violations: list[str] = field(default_factory=list)


def _issued_from(modules: frozenset[str]) -> bool:
    frame = sys._getframe(2)
    while frame is not None:
        if frame.f_code.co_filename in modules:
            return True
        frame = frame.f_back
    return False


@contextmanager
def current_derivations_backstop(
    modules: tuple[Path, ...] = (READS_MODULE,),
) -> Iterator[Backstop]:
    """Install the listener on every engine for the duration of the block."""
    seen = Backstop()
    sources = frozenset(str(path.resolve()) for path in modules)

    def check(_connection: object, _cursor: object, statement: str, *_rest: object) -> None:
        if not _CHILD.search(statement) or not _issued_from(sources):
            return
        seen.checked += 1
        if not filters_on_the_view(statement):
            seen.violations.append(statement)
            raise AssertionError(
                "a project-report read touched a child table without joining "
                f"project_report_current_derivations:\n{statement}"
            )

    event.listen(Engine, "before_cursor_execute", check)
    try:
        yield seen
    finally:
        event.remove(Engine, "before_cursor_execute", check)
    assert seen.violations == [], seen.violations
