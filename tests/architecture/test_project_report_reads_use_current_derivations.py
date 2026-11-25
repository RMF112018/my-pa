"""The project-report reads reach derivations only through the current view (WP4P-S2).

ADR-024 decision 7: "current" is the derivation nothing supersedes, and the
view `project_report_current_derivations` is the reader's only route. A read
that names the derivations table, or reads a derivation's lines, line values,
row roles, stated totals or cross-checks without the view, would answer or
count a superseded derivation beside its successor (the double count the WP3P
W1 risk list named). Parsed from the source, so a statement never executed is
still caught:

* no read module names `project_report_derivations`, by import, name or
  string;
* **per statement** (ruling R1-04): every `select(...)` / `text(...)` statement
  that reads one of the five child tables names the view in the same
  statement. A statement is its whole method chain, with the extensions made
  through the variable it is assigned to (`statement = statement.where(...)`);
  a `select` nested in a statement is a subquery of it, never one of its own.
  Names are resolved through local variables and through every helper the
  statement calls, by the helper's *return value* only, so a join a helper
  merely performs elsewhere never counts. Functions, `async` functions,
  lambdas and module-level code are all scanned, and a string names whatever
  table it spells (a `text()` statement included);
* a helper that returns a bare child table (or a join or alias built on one)
  without the view is itself a violation, and so is any string that spells a
  child table without the view;
* no read module uses `float`.

The read modules are the persistence reads and the application read service.
Planted cases prove the scanner sees each bypass it claims to.
"""

from __future__ import annotations

import ast
import re
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
        "project_report_cross_checks",
    }
)
_SPELLED: Final = re.compile(r"\b(" + "|".join(sorted([VIEW, *CHILDREN])) + r")\b")
#: The calls that start a statement: `select(...)`, `<table>.select()` and `text(...)`.
_STATEMENTS: Final = frozenset({"select", "text"})
#: Methods that add to a local collection (`bounds.append(...)`).
_GROWS: Final = frozenset({"append", "extend", "add", "update", "insert"})


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


_Def = ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda


class _Module:
    """One parsed read module: its parents, scopes, locals and helpers."""

    def __init__(self, source: str) -> None:
        self.tree = ast.parse(source)
        self.aliases = _aliases(self.tree)
        self.parent: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                self.parent[child] = node
        #: Local name -> the expressions assigned to it, per outermost scope.
        self.locals: dict[ast.AST, dict[str, list[ast.AST]]] = {}
        #: Helper name -> `(its return expressions, its outermost scope)`.
        self.helpers: dict[str, list[tuple[ast.AST, ast.AST]]] = {}
        for node in ast.walk(self.tree):
            scope = self.scope_of(node)
            found = self.locals.setdefault(scope, {})
            for target, value in _bindings(node):
                found.setdefault(target, []).append(value)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Return) and inner.value is not None:
                        self.helpers.setdefault(node.name, []).append((inner.value, scope))
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Lambda)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                self.helpers.setdefault(node.targets[0].id, []).append((node.value.body, scope))

    def scope_of(self, node: ast.AST) -> ast.AST:
        """The outermost function (or lambda) holding `node`, else the module."""
        outermost: ast.AST = self.tree
        current = self.parent.get(node)
        while current is not None:
            if isinstance(current, _Def):
                outermost = current
            current = self.parent.get(current)
        return outermost

    def name_of(self, node: ast.AST) -> str:
        current = self.parent.get(node)
        while current is not None:
            if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
                return current.name
            if isinstance(current, ast.Lambda):
                return "<lambda>"
            current = self.parent.get(current)
        return "<module>"

    def assigned(self, scope: ast.AST, name: str) -> list[ast.AST]:
        return [
            *self.locals.get(scope, {}).get(name, []),
            *([] if scope is self.tree else self.locals.get(self.tree, {}).get(name, [])),
        ]

    def names(
        self, expression: ast.AST, scope: ast.AST, seen: set[tuple[int, str]] | None = None
    ) -> set[str]:
        """Every table a statement fragment names, through its locals and helpers' returns."""
        seen = set() if seen is None else seen
        found: set[str] = set()
        for node in ast.walk(expression):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found |= set(_SPELLED.findall(node.value))
            elif isinstance(node, ast.Name):
                found.add(self.aliases.get(node.id, node.id))
                key = (id(scope), node.id)
                if key not in seen:
                    seen.add(key)
                    for value in self.assigned(scope, node.id):
                        found |= self.names(value, scope, seen)
                found |= self._returns(node.id, seen)
            elif isinstance(node, ast.Attribute):
                found.add(node.attr)
                if isinstance(self.parent.get(node), ast.Call):
                    found |= self._returns(node.attr, seen)
        return found

    def _returns(self, helper: str, seen: set[tuple[int, str]]) -> set[str]:
        key = (0, f"helper:{helper}")
        if key in seen:
            return set()
        seen.add(key)
        found: set[str] = set()
        for value, scope in self.helpers.get(helper, []):
            found |= self.names(value, scope, seen)
        return found


def _bindings(node: ast.AST) -> list[tuple[str, ast.AST]]:
    """`(local name, assigned expression)` pairs a node makes."""
    pairs: list[tuple[str, ast.AST]] = []
    if isinstance(node, ast.Assign):
        for target in node.targets:
            pairs += [(n.id, node.value) for n in ast.walk(target) if isinstance(n, ast.Name)]
    elif isinstance(node, ast.AnnAssign | ast.AugAssign | ast.NamedExpr) and node.value is not None:
        if isinstance(node.target, ast.Name):
            pairs.append((node.target.id, node.value))
    elif isinstance(node, ast.For | ast.AsyncFor | ast.comprehension):
        pairs += [(n.id, node.iter) for n in ast.walk(node.target) if isinstance(n, ast.Name)]
    elif isinstance(node, ast.withitem) and node.optional_vars is not None:
        pairs += [
            (n.id, node.context_expr)
            for n in ast.walk(node.optional_vars)
            if isinstance(n, ast.Name)
        ]
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _GROWS
        and isinstance(node.func.value, ast.Name)
    ):
        pairs += [(node.func.value.id, arg) for arg in node.args]
    return pairs


def _starts_statement(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id in _STATEMENTS) or (
        isinstance(func, ast.Attribute) and func.attr in _STATEMENTS
    )


def _chain_root(node: ast.AST) -> ast.AST:
    """The start of a method chain: the statement call, or the name it extends."""
    while True:
        if isinstance(node, ast.Call):
            if _starts_statement(node):
                return node
            node = node.func
        elif isinstance(node, ast.Attribute | ast.Subscript):
            node = node.value
        else:
            return node


def _base(node: ast.AST) -> ast.AST:
    """What an expression is built on: `lines.join(...).alias()` is built on `lines`."""
    while isinstance(node, ast.Call | ast.Attribute | ast.Subscript):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node


def _statement_variables(module: _Module, scope: ast.AST) -> set[str]:
    """The locals of `scope` that hold a statement (assigned one, or an extension of one)."""
    held: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, values in module.locals.get(scope, {}).items():
            if name in held:
                continue
            for value in values:
                root = _chain_root(value)
                if _starts_statement(root) or (isinstance(root, ast.Name) and root.id in held):
                    held.add(name)
                    changed = True
                    break
    return held


def _is_subquery(module: _Module, node: ast.AST, held: set[str]) -> bool:
    """`node` is nested in another statement, or in an extension of a held one."""
    current = module.parent.get(node)
    while current is not None:
        if _starts_statement(current):
            return True
        if isinstance(current, ast.Call):
            root = _chain_root(current)
            if isinstance(root, ast.Name) and root.id in held:
                return True
        current = module.parent.get(current)
    return False


def _whole_chain(module: _Module, node: ast.AST) -> ast.AST:
    """The outermost call of the method chain `node` starts."""
    current = node
    while True:
        parent = module.parent.get(current)
        grand = None if parent is None else module.parent.get(parent)
        if (
            isinstance(parent, ast.Attribute)
            and parent.value is current
            and isinstance(grand, ast.Call)
            and grand.func is parent
        ):
            current = grand
        else:
            return current


def _statement_parts(module: _Module, root: ast.AST, held: set[str]) -> list[ast.AST]:
    """A statement's chain and, when assigned to a held local, every extension of it."""
    chain = _whole_chain(module, root)
    parts = [chain]
    parent = module.parent.get(chain)
    if isinstance(parent, ast.Assign):
        targets = {n.id for t in parent.targets for n in ast.walk(t) if isinstance(n, ast.Name)}
        scope = module.scope_of(root)
        for node in ast.walk(scope):
            if isinstance(node, ast.Call):
                base = _chain_root(node)
                if isinstance(base, ast.Name) and base.id in targets & held:
                    parts.append(node)
    return parts


def _unjoined_child_reads(source: str) -> list[str]:
    """`<scope>:<line>` of every statement over a child table that does not name the view.

    Also every helper (a function or a lambda) returning a bare child table,
    join or alias without the view, and every string spelling a child table
    without the view.
    """
    module = _Module(source)
    found: list[tuple[int, str]] = []
    held_by_scope: dict[ast.AST, set[str]] = {}
    for node in ast.walk(module.tree):
        if not _starts_statement(node):
            continue
        scope = module.scope_of(node)
        held = held_by_scope.setdefault(scope, _statement_variables(module, scope))
        if _is_subquery(module, node, held):
            continue
        named: set[str] = set()
        for part in _statement_parts(module, node, held):
            named |= module.names(part, scope)
        if named & CHILDREN and VIEW not in named:
            found.append((node.lineno, module.name_of(node)))
    for name, returns in module.helpers.items():
        for value, scope in returns:
            base = _base(value)
            if not isinstance(base, ast.Name):
                continue
            if module.names(base, scope) & CHILDREN and VIEW not in module.names(value, scope):
                found.append((value.lineno, f"helper {name}"))
    for node in ast.walk(module.tree):
        if _is_docstring(module, node) or not (
            isinstance(node, ast.Constant) and isinstance(node.value, str)
        ):
            continue
        spelled = set(_SPELLED.findall(node.value))
        if spelled & CHILDREN and VIEW not in spelled:
            found.append((node.lineno, f"string in {module.name_of(node)}"))
    return [f"{name}:{line}" for line, name in sorted(set(found))]


def _is_docstring(module: _Module, node: ast.AST) -> bool:
    parent = module.parent.get(node)
    holder = None if parent is None else module.parent.get(parent)
    return (
        isinstance(parent, ast.Expr)
        and isinstance(holder, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and holder.body[0] is parent
    )


def _scopes_of(found: list[str]) -> list[str]:
    return [entry.rsplit(":", 1)[0] for entry in found]


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
    "    project_report_cross_checks as checks,\n"
    "    project_report_current_derivations,\n"
    "    project_report_line_values as values,\n"
    "    project_report_lines as lines,\n"
    "    project_report_stated_totals as totals,\n"
    ")\n"
)
_JOINED: Final = "lines.join(project_report_current_derivations, x)"


def _planted(body: str) -> list[str]:
    return _scopes_of(_unjoined_child_reads(_PLANTED_HEAD + body))


def test_a_planted_table_name_is_caught() -> None:
    planted = "from my_pa.infrastructure.persistence.tables import project_report_derivations\n"
    assert _names_the_table(planted) == [1]
    assert _names_the_table("X = 'knowledge.project_report_derivations'\n") == [1]
    assert _names_the_table("X = 'knowledge.project_report_current_derivations'\n") == []


def test_a_planted_unjoined_child_read_is_caught() -> None:
    assert _planted("def read():\n    return select(lines.c.row_ordinal)\n") == ["read"]
    joined = f"def read():\n    return select(lines.c.row_ordinal).select_from({_JOINED})\n"
    assert _planted(joined) == []
    # Cross-checks are a child table too; an `exists` over the view names it.
    assert _planted("def read():\n    return select(checks.c.outcome)\n") == ["read"]
    current = (
        "def read():\n"
        "    return select(checks.c.outcome).where(exists(select(literal(1)).where(\n"
        "        project_report_current_derivations.c.derivation_id == checks.c.left)))\n"
    )
    assert _planted(current) == []


def test_a_helper_returning_a_bare_child_table_is_caught() -> None:
    """Bypass 1 (mutant M15's shape): the caller names no child table itself."""
    bare = (
        "def _source():\n"
        "    return totals\n"
        "def read(ids):\n"
        "    source = _source()\n"
        "    return select(source.c.row_ordinal).where(source.c.derivation_id.in_(ids))\n"
    )
    assert _planted(bare) == ["helper _source", "read"]
    # A join the helper performs but does not return never counts.
    performed = bare.replace(
        "    return totals\n",
        "    joined = totals.join(project_report_current_derivations, x)\n    return totals\n",
    )
    assert _planted(performed) == ["helper _source", "read"]
    # The returned join is the helper's value: it counts, for the helper and its callers.
    returned = bare.replace(
        "    return totals\n",
        "    return totals.join(project_report_current_derivations, x)\n",
    )
    assert _planted(returned) == []


def test_a_second_unjoined_statement_beside_a_joined_one_is_caught() -> None:
    """Bypass 2: one function joins the view, a second statement in it does not."""
    planted = (
        "def read():\n"
        f"    joined = select(lines.c.row_ordinal).select_from({_JOINED})\n"
        "    bare = select(values.c.raw_text)\n"
        "    return joined, bare\n"
    )
    assert _unjoined_child_reads(_PLANTED_HEAD + planted) == ["read:10"]
    # A subquery of a held statement's extension is part of that statement.
    extended = (
        "def read():\n"
        f"    statement = select(lines.c.row_ordinal).select_from({_JOINED})\n"
        "    statement = statement.where(exists(select(literal(1)).where(values.c.x == 1)))\n"
        "    return statement\n"
    )
    assert _planted(extended) == []


def test_module_level_async_and_lambda_statements_are_caught() -> None:
    """Bypass 3: only `def` bodies were walked."""
    assert _planted("STATEMENT = select(lines.c.row_ordinal)\n") == ["<module>"]
    assert _planted("async def read():\n    return select(lines.c.row_ordinal)\n") == ["read"]
    assert _planted("read = lambda: select(lines.c.row_ordinal)\n") == ["<lambda>"]
    source = "source = lambda: totals\ndef read():\n    return select(source().c.value)\n"
    assert _planted(source) == ["helper source", "read"]


def test_a_text_statement_over_a_child_table_is_caught() -> None:
    """Bypass 4: strings were checked only for the derivations table."""
    bare = 'def read():\n    return text("SELECT 1 FROM knowledge.project_report_lines")\n'
    assert _planted(bare) == ["read", "string in read"]
    joined = (
        "def read():\n"
        '    return text("SELECT 1 FROM knowledge.project_report_lines JOIN "\n'
        '                "knowledge.project_report_current_derivations USING (derivation_id)")\n'
    )
    assert _planted(joined) == []
    held = '_SQL = "SELECT 1 FROM knowledge.project_report_cross_checks"\n'
    assert _planted(held) == ["string in <module>"]
    docstring = 'def read():\n    """Reads project_report_lines through the view."""\n'
    assert _planted(docstring) == []


def test_a_planted_float_is_caught() -> None:
    assert sorted(set(_floats("X = float('1')\nY = 0.5\n"))) == [1, 2]
