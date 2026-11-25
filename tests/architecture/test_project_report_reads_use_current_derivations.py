"""The project-report reads reach derivations only through the current view (WP4P-S2).

ADR-024 decision 7: "current" is the derivation nothing supersedes, and the
view `project_report_current_derivations` is the reader's only route. A read
that names the derivations table, or reads a derivation's lines, line values,
row roles or stated totals without joining that view, would answer or count a
superseded derivation beside its successor (the double count the WP3P W1 risk
list named). Parsed from the source, so a statement never executed is still
caught:

* no read module names `project_report_derivations`, by import, name or
  string;
* every function of a read module that selects over one of the four child
  tables holds a `.join(...)` / `.outerjoin(...)` that names the view, or
  calls a module helper that does (the joined FROM clause), so every
  statement over a child table carries the view;
* no read module uses `float`.

The read modules are the persistence reads and, once it exists, the
application read service. Planted cases prove the scanner sees what it claims.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

PACKAGE: Final = Path(__file__).resolve().parents[2] / "src" / "my_pa"
PERSISTENCE: Final = PACKAGE / "infrastructure" / "persistence" / "project_report_reads.py"
SERVICE: Final = PACKAGE / "application" / "project_reports_reads.py"
VIEW: Final = "project_report_current_derivations"
TABLE: Final = "project_report_derivations"
CHILDREN: Final = frozenset(
    {
        "project_report_lines",
        "project_report_line_values",
        "project_report_row_roles",
        "project_report_stated_totals",
    }
)


def _read_modules() -> list[Path]:
    return [path for path in (PERSISTENCE, SERVICE) if path.exists()]


def _aliases(tree: ast.Module) -> dict[str, str]:
    """Local name -> table name, for the module's `tables` imports (`as` included)."""
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith(".tables"):
            for alias in node.names:
                found[alias.asname or alias.name] = alias.name
    return found


def _names(node: ast.AST, aliases: dict[str, str]) -> set[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(aliases.get(child.id, child.id))
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
    return found


def _names_the_table(source: str) -> list[int]:
    hits: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            hits += [node.lineno for alias in node.names if alias.name == TABLE]
            continue
        named = (isinstance(node, ast.Name) and node.id == TABLE) or (
            isinstance(node, ast.Attribute) and node.attr == TABLE
        )
        quoted = (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and TABLE in node.value.replace(VIEW, "")
        )
        if named or quoted:
            hits.append(node.lineno)
    return hits


def _direct_view_join(function: ast.FunctionDef, aliases: dict[str, str]) -> bool:
    """`function` holds a `.join(...)`/`.outerjoin(...)` naming the view."""
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("join", "outerjoin")
        ):
            named = set().union(*(_names(arg, aliases) for arg in [*node.args, node.func.value]))
            if VIEW in named:
                return True
    return False


def _selects(function: ast.FunctionDef) -> bool:
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "select"
        for node in ast.walk(function)
    )


def _unjoined_child_reads(source: str) -> list[str]:
    """Functions that select over a child table without a join to the view.

    A join may be the function's own or a module helper's it calls (a helper
    returning the joined FROM clause). A function that selects nothing (a join
    condition fragment) is checked where it is used.
    """
    tree = ast.parse(source)
    aliases = _aliases(tree)
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    joining = {f.name for f in functions if _direct_view_join(f, aliases)}
    found: list[str] = []
    for function in functions:
        if not _selects(function) or not _names(function, aliases) & CHILDREN:
            continue
        calls = {
            node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        if function.name not in joining and not calls & joining:
            found.append(function.name)
    return found


def _floats(source: str) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if (isinstance(node, ast.Name) and node.id == "float")
        or (isinstance(node, ast.Constant) and type(node.value) is float)
    ]


def test_the_read_module_exists() -> None:
    assert PERSISTENCE in _read_modules()


@pytest.mark.parametrize("path", _read_modules(), ids=lambda p: p.name)
def test_no_read_names_the_derivations_table(path: Path) -> None:
    assert _names_the_table(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("path", _read_modules(), ids=lambda p: p.name)
def test_every_child_table_read_joins_the_current_view(path: Path) -> None:
    assert _unjoined_child_reads(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("path", _read_modules(), ids=lambda p: p.name)
def test_no_float_in_a_read_module(path: Path) -> None:
    assert _floats(path.read_text(encoding="utf-8")) == []


# --- planted prove-red controls ---------------------------------------------------


_PLANTED_HEAD: Final = (
    "from my_pa.infrastructure.persistence.tables import (\n"
    "    project_report_current_derivations,\n"
    "    project_report_lines as lines,\n"
    ")\n"
)


def test_a_planted_table_name_is_caught() -> None:
    planted = "from my_pa.infrastructure.persistence.tables import project_report_derivations\n"
    assert _names_the_table(planted) == [1]
    assert _names_the_table("X = 'knowledge.project_report_derivations'\n") == [1]
    assert _names_the_table("X = 'knowledge.project_report_current_derivations'\n") == []


def test_a_planted_unjoined_child_read_is_caught() -> None:
    unjoined = _PLANTED_HEAD + "def read():\n    return select(lines.c.row_ordinal)\n"
    assert _unjoined_child_reads(unjoined) == ["read"]
    joined = _PLANTED_HEAD + (
        "def read():\n"
        "    return select(lines.c.row_ordinal).select_from(\n"
        "        lines.join(project_report_current_derivations, x))\n"
    )
    assert _unjoined_child_reads(joined) == []


def test_a_planted_float_is_caught() -> None:
    assert sorted(set(_floats("X = float('1')\nY = 0.5\n"))) == [1, 2]
