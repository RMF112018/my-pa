"""No statement anywhere under `src/` updates or deletes a stored capture version.

`QC-AC-010` has **two independent halves**, and this module is one of them. The
other is `tests/schema/test_capture_immutability.py`, which puts two concurrent
connections against a real server and watches the `BEFORE UPDATE OR DELETE`
trigger refuse both. Neither implies the other, and that is the reason they are
two modules rather than two assertions:

* a build that dropped the trigger would still pass **here**, because no writer
  in the tree would have gained an `UPDATE`;
* a build that grew an `update()` on `capture_versions` would still pass
  **there**, because the server would refuse the statement whether or not the
  code that never ran contains it.

`D-55` is the standing reason this matters. A single plant proves only whichever
half it happened to reach first, and a criterion "proven" by such a plant is
proven at neither end. So each half's plant is required to leave the other half
**green**, which is a claim about the two modules together and is recorded in
the implementation evidence rather than assertable from inside either one.

**What this half is for.** The trigger says a stored version cannot be changed.
It does not say the product never tries: a writer holding an `UPDATE` against
`capture_versions` is a writer whose ordinary path is a runtime error the caller
sees as `internal_error`, and it is also the shape a later package would reach
for first when asked to "fix a typo in a capture". ADR-003 clause 3 says an edit
is a new version. This is that clause, read out of the source rather than out of
the schema.

**The detector is proven able to fire before its zero is believed.** Three
controls sit beside the claim: the walk's universe is stated and required to be
non-empty and to contain the one module that writes captures; the detector is
required to find the `insert()` that module really does perform against exactly
this table, which is what says its name resolution works on real code; and the
detector is run over a synthetic module that does contain an `UPDATE` and is
required to report it. A guard that matches nothing is the failure this
repository has recorded twice (`D-26`, `D-44`), and a zero with no control
beside it is exactly that failure wearing a green tick.

Nothing here opens a path, reaches a source, or touches a database. It reads the
repository's own committed source with `ast`.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
SOURCE: Final = ROOT / "src"

#: The table whose rows may never change. Written as the name the declaration
#: binds, because that is the name a writer under `src/` has to use to reach it.
TABLE: Final = "capture_versions"

#: The statement builders that change or remove a row. `insert` is deliberately
#: absent: appending is the whole mechanism, and a guard that refused it would
#: refuse the product.
MUTATING_BUILDERS: Final = frozenset({"update", "delete"})

#: Raw SQL naming the table in a statement that is not an append. Matched
#: against string literals, because a writer can reach a table through
#: `text(...)` without ever naming the declaration — and `persistence.jobs`
#: proves that path is in live use for other tables.
_RAW_SQL: Final = re.compile(
    rf"\b(?:UPDATE|DELETE\s+FROM)\s+(?:\w+\.)?{TABLE}\b",
    re.IGNORECASE,
)


class _Statements(ast.NodeVisitor):
    """Every statement one module builds against one named table.

    Both call shapes SQLAlchemy accepts are collected — `table.update()` and
    `update(table)` — because a guard that knew only one of them would be a
    guard a writer evades by preferring the other, without ever intending to.
    """

    def __init__(self, table: str) -> None:
        self.table = table
        self.builders: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:
        function = node.func
        if isinstance(function, ast.Attribute) and _names(function.value) == self.table:
            self.builders.append(function.attr)
        elif isinstance(function, ast.Name) and any(
            _names(argument) == self.table for argument in node.args
        ):
            self.builders.append(function.id)
        self.generic_visit(node)


def _names(node: ast.expr) -> str | None:
    """The table this expression names, for the two forms a module can write it."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _built_against(tree: ast.AST, table: str) -> list[str]:
    visitor = _Statements(table)
    visitor.visit(tree)
    return visitor.builders


def _raw_statements(tree: ast.AST) -> list[str]:
    """Raw SQL against the table, read out of the module's string literals."""
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _RAW_SQL.search(node.value)
    ]


def _modules() -> dict[Path, ast.Module]:
    """Every Python module under `src/`, parsed once."""
    return {path: ast.parse(path.read_text(encoding="utf-8")) for path in SOURCE.rglob("*.py")}


def test_the_detector_finds_a_mutating_statement_when_one_is_present() -> None:
    """The control that makes the zero below a measurement.

    A synthetic module, not the tree: it holds one of each shape the detector
    claims to see, and every one has to be reported. If this reddens, the walk
    below is incapable of seeing what it says it looked for, and its silence
    means nothing at all.
    """
    planted = ast.parse(
        "from sqlalchemy import delete, update\n"
        "from my_pa.infrastructure.persistence.tables import capture_versions\n"
        "def a(connection):\n"
        "    connection.execute(capture_versions.update().values(content='x'))\n"
        "def b(connection):\n"
        "    connection.execute(delete(capture_versions))\n"
        "def c(connection):\n"
        "    connection.execute(text('UPDATE knowledge.capture_versions SET content = :c'))\n"
    )
    assert set(_built_against(planted, TABLE)) & MUTATING_BUILDERS == {"update", "delete"}
    assert len(_raw_statements(planted)) == 1


def test_the_walk_covers_the_source_tree_and_reaches_the_module_that_writes_captures() -> None:
    """The universe, stated. A walk over nothing proves nothing about anything."""
    modules = _modules()
    assert len(modules) > 50, f"the walk found {len(modules)} modules under {SOURCE}"
    writer = SOURCE / "my_pa" / "infrastructure" / "persistence" / "capture.py"
    assert writer in modules, "the module that writes capture versions was not walked"

    # And the detector resolves this table's name in real code: the append it
    # really does perform is found, which is what says the zero below is a zero
    # about statements rather than about name resolution.
    assert "insert" in _built_against(modules[writer], TABLE)


def test_no_module_under_src_updates_or_deletes_a_stored_capture_version() -> None:
    """`QC-AC-010`, read out of the source: an edit appends and nothing overwrites.

    Reported per module and per statement, so a failure names the writer that
    grew the path rather than only that one exists somewhere.
    """
    modules = _modules()
    found = {
        path.relative_to(ROOT).as_posix(): sorted(
            set(_built_against(tree, TABLE)) & MUTATING_BUILDERS
        )
        + _raw_statements(tree)
        for path, tree in modules.items()
    }
    offending = {path: statements for path, statements in found.items() if statements}
    assert offending == {}, (
        "a module under src/ builds a statement that changes or removes a stored "
        f"capture version: {offending}. ADR-003 clause 3 makes an edit a new "
        "version; the predecessor stays exactly as it was written"
    )
