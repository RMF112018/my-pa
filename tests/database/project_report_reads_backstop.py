"""A runtime backstop for the current-derivations rule (ruling R2-02).

`tests/architecture/test_project_report_reads_use_current_derivations.py`
parses the read modules; this listener checks what they actually send. While
it is installed, every statement the project-report read repository executes
(`before_cursor_execute`, issued from
`infrastructure/persistence/project_report_reads.py`) that names one of the
five child tables (lines, line values, row roles, stated totals,
cross-checks) must name `project_report_current_derivations` in a FROM or a
JOIN. A violation is raised at once (the read fails) and also recorded, so a
caller that swallows the error still fails the test at teardown.

The text check is deliberately simple: a statement that reaches the view only
through an uncorrelated `exists (SELECT ... FROM <the view>)` still passes it.
That mention-only shape is the static guard's to refuse (it requires a join or
a semi-join on a child column).

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
_VIEW: Final = re.compile(
    r"\b(?:FROM|JOIN)\s+(?:\"?knowledge\"?\.)?\"?project_report_current_derivations\b",
    re.IGNORECASE,
)


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
        if not _VIEW.search(statement):
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
