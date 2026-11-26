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
* **per statement** (ruling R1-04): every statement that reads one of the
  five child tables **joins** the view in the same statement. A statement is
  a `select(...)` / `Select(...)` / `text(...)` call under any name it is
  imported as (ruling R2-02), with its whole method chain and the extensions
  made through the variable it is assigned to. "Joins" (ruling R3-01) means
  an inner `.join` of the view whose ON clause equates a child's
  `derivation_id` with the view's; a semi-join of a child's derivation column
  on the view's `derivation_id` (`==`, or `.in_(select(view.c.derivation_id))`)
  that sits under no `~`, `not_()`, `or_()` or `|`; or a `text()` that spells
  an inner or plain `JOIN <the view>` with `ON ... derivation_id = ...
  derivation_id` or `USING (derivation_id)` (`inner_joins_view`, shared with
  the runtime backstop). An `outerjoin`, `isouter=`, `full=`, a LEFT, RIGHT,
  FULL or CROSS join, an ON clause of `true()` or on another column, and a
  view merely mentioned (an uncorrelated `exists`, a cross-join predicate)
  never count;
* a statement nested in another (a subquery) that brings in a child table
  the outer statement does not read must join the view itself or be
  correlated to the outer statement (an `==` or `.in_` between the new child
  table and one the outer statement reads);
* names are resolved through locals, through every helper's *return value*
  (with its parameters bound to each call's arguments), and through a
  function's parameters (each call's argument, or the default), so a table
  passed as an argument is still seen. A table position that resolves to no
  known table or statement local (a `self` attribute, a computed `getattr`,
  `metadata.tables[...]` with a computed key, an unknown global) **fails
  closed**; so does a Call or a Subscript in a table position (ruling R3-02),
  unless it is a table method on a resolving receiver, a statement or
  SQLAlchemy call, a call of a module helper whose returns all resolve, or
  `<metadata>.tables[<constant>]`. A local or a parameter that rebinds the
  view's name (or the alias it is imported as) is a violation. Functions,
  `async` functions, lambdas and module-level code are all scanned, and a
  string names whatever table it spells;
* a helper that returns a bare child table (or a join, alias or selectable
  built on one) without the view is itself a violation, but one returning a
  child *column* or a predicate is not (ruling R2-06); any string that spells
  a child table without the view, or ends in `project_report_` (a computed
  table name), is a violation;
* no read module uses `float`.

The read modules are the persistence reads and the application read service.
Planted cases prove the scanner sees each bypass it claims to. The DB read
suites add a runtime backstop (`tests/database/project_report_reads_backstop.py`):
every statement the read repository executes over a child table must name the
view in a FROM or JOIN.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import pytest
from tests.database.project_report_reads_backstop import inner_joins_view

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
#: The calls that start a statement: `select(...)`, `Select(...)`, `<table>.select()`
#: and `text(...)`, under any alias they are imported as (ruling R2-02).
_STATEMENTS: Final = frozenset({"select", "Select", "text"})
#: Methods that add to a local collection (`bounds.append(...)`).
_GROWS: Final = frozenset({"append", "extend", "add", "update", "insert"})


def _read_modules() -> list[Path]:
    return [path for path in (PERSISTENCE, SERVICE) if path.exists()]


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
#: Methods whose receiver is a table (or a selectable built on one).
_TABLE_METHODS: Final = frozenset(
    {"c", "columns", "join", "outerjoin", "alias", "select", "subquery", "cte", "lateral"}
)
_JOINS: Final = frozenset({"join", "outerjoin"})
#: Calls whose arguments are negated or alternatives: a link under one never filters.
_WEAKENS: Final = frozenset({"not_", "or_"})
#: A child column that names a derivation (`derivation_id`, `left_derivation_id`).
_DERIVATION_COLUMN: Final = re.compile(r"(?:\w+_)?derivation_id\Z")
#: A string that ends in this prefix computes a table name (`"project_report_" + kind`).
_COMPUTED: Final = re.compile(r"project_report_\Z")


@dataclass
class _Link:
    """One `==` or `.in_(...)`: the names and columns of each side, and whether it filters."""

    left: set[str]
    right: set[str]
    #: The columns a side is (`t.c.derivation_id`), or None for anything else.
    left_columns: frozenset[str] | None = None
    right_columns: frozenset[str] | None = None
    #: False under `~`, `not_()`, `or_()` or `|` (ruling R3-01).
    filters: bool = True

    def on_derivation(self) -> bool:
        """The view's `derivation_id` equated with a child's derivation column."""
        return any(
            VIEW in view
            and view_columns == frozenset({"derivation_id"})
            and child & CHILDREN
            and VIEW not in child
            and child_columns
            and all(_DERIVATION_COLUMN.match(c) for c in child_columns)
            for view, view_columns, child, child_columns in (
                (self.left, self.left_columns, self.right, self.right_columns),
                (self.right, self.right_columns, self.left, self.left_columns),
            )
        )


@dataclass
class _Facts:
    """What a statement fragment reaches: the tables it names, and how it meets the view."""

    names: set[str] = field(default_factory=set)
    #: Table positions that resolve to neither a known table nor a statement local.
    unresolved: set[str] = field(default_factory=set)
    #: The view is inner-joined on `derivation_id` (`.join(view, <on>)`, or `text()`).
    joins_view: bool = False
    #: Every `==` and every `.in_(...)`.
    links: list[_Link] = field(default_factory=list)

    @property
    def children(self) -> set[str]:
        return self.names & CHILDREN

    def linked(self, one: set[str], other: set[str]) -> bool:
        return any(
            (link.left & one and link.right & other) or (link.left & other and link.right & one)
            for link in self.links
        )

    @property
    def semi_joined(self) -> bool:
        """A filtering link of the view's `derivation_id` to a child's (ruling R3-01)."""
        return any(link.filters and link.on_derivation() for link in self.links)

    @property
    def joined(self) -> bool:
        """The view is inner-joined, or semi-joined on a child's `derivation_id`."""
        return self.joins_view or self.semi_joined


class _Module:
    """One parsed read module: its parents, scopes, locals, parameters and helpers."""

    def __init__(self, source: str) -> None:
        self.tree = ast.parse(source)
        self.parent: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                self.parent[child] = node
        #: Local name -> table name, for the module's `tables` imports (`as` included).
        self.aliases: dict[str, str] = {}
        #: Names bound to the tables module itself (`tables.project_report_lines`).
        self.table_modules: set[str] = set()
        #: Names imported from SQLAlchemy (a function, class or module).
        self.sqlalchemy: set[str] = set()
        #: Names a statement starts with: `select`, `Select`, `text`, under any alias.
        self.statement_calls: set[str] = set(_STATEMENTS)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    local = alias.asname or alias.name
                    if node.module.endswith(".tables"):
                        self.aliases[local] = alias.name
                    elif alias.name == "tables":
                        self.table_modules.add(local)
                    if node.module.split(".")[0] == "sqlalchemy":
                        self.sqlalchemy.add(local)
                        if alias.name in _STATEMENTS:
                            self.statement_calls.add(local)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    if alias.name.split(".")[0] == "sqlalchemy":
                        self.sqlalchemy.add(local)
                    if alias.name.endswith(".tables"):
                        self.table_modules.add(local)
        #: Memoized `_names`, keyed by node and bindings.
        self._named: dict[tuple[object, ...], set[str]] = {}
        #: Local name -> the expressions assigned to it, per outermost scope.
        self.locals: dict[ast.AST, dict[str, list[ast.AST]]] = {}
        #: Function name -> its definitions (a `def`, or a lambda assigned to a name).
        self.functions: dict[str, list[_Def]] = {}
        #: Function name -> every call of it (`f(...)`, or `self.f(...)`).
        self.calls: dict[str, list[ast.Call]] = {}
        for node in ast.walk(self.tree):
            found = self.locals.setdefault(self.scope_of(node), {})
            for target, value in _bindings(node):
                found.setdefault(target, []).append(value)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                self.functions.setdefault(node.name, []).append(node)
            elif (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Lambda)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                self.functions.setdefault(node.targets[0].id, []).append(node.value)
            elif isinstance(node, ast.Call):
                called = _called_name(node)
                if called is not None:
                    self.calls.setdefault(called, []).append(node)

    # --- scopes ------------------------------------------------------------------

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

    def assigned(self, node: ast.Name) -> list[ast.AST]:
        scope = self.scope_of(node)
        return [
            *self.locals.get(scope, {}).get(node.id, []),
            *([] if scope is self.tree else self.locals.get(self.tree, {}).get(node.id, [])),
        ]

    def owner(self, node: ast.Name) -> _Def | None:
        """The innermost function `node` is a parameter of, if any."""
        current = self.parent.get(node)
        while current is not None:
            if isinstance(current, _Def) and node.id in _parameters(current):
                return current
            current = self.parent.get(current)
        return None

    def arguments(self, function: _Def, parameter: str) -> list[ast.AST]:
        """What `parameter` may hold: each call's argument, else its default."""
        name = (
            function.name
            if isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef)
            else _lambda_name(self, function)
        )
        values = [
            value
            for call in self.calls.get(name or "", [])
            for value in _bound(self, function, call).get(parameter, [])
        ]
        return values or _defaults(function).get(parameter, [])

    # --- reach -------------------------------------------------------------------

    def starts(self, node: ast.AST) -> bool:
        return _starts_statement(node, self.statement_calls)

    def facts(
        self, roots: list[ast.AST], *, nested: bool = True, bound: _Bound | None = None
    ) -> _Facts:
        """Everything `roots` reach, through locals, parameters and helpers' returns.

        With `nested=False`, a statement nested in a root is not entered: the
        facts are the root statement's own.
        """
        facts = _Facts()
        seen: set[tuple[object, ...]] = set()
        for root in roots:
            self._reach(root, {} if bound is None else bound, facts, seen, nested=nested)
        return facts

    def _names(self, node: ast.AST, bound: _Bound) -> set[str]:
        """The names one side of a link reaches (memoized; a cycle names nothing more)."""
        key = (id(node), tuple(sorted((k, tuple(map(id, v))) for k, v in bound.items())))
        if key in self._named:
            return self._named[key]
        self._named[key] = set()
        named = self.facts([node], bound=bound).names
        self._named[key] = named
        return named

    def _reach(
        self,
        root: ast.AST,
        bound: _Bound,
        facts: _Facts,
        seen: set[tuple[object, ...]],
        *,
        nested: bool,
        weakened: bool = False,
    ) -> None:
        own = _chain_root(root, self.statement_calls)
        todo: list[tuple[ast.AST, bool]] = [(root, weakened)]
        while todo:
            node, weak = todo.pop()
            for child in ast.iter_child_nodes(node):
                start = _chain_root(child, self.statement_calls)
                if nested or start is own or not self.starts(start):
                    todo.append((child, weak or _weakens(node, child)))
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                facts.names |= set(_SPELLED.findall(node.value))
                if inner_joins_view(node.value):
                    facts.joins_view = True
            elif isinstance(node, ast.BinOp):
                folded = _fold(node)
                if folded is not None:
                    facts.names |= set(_SPELLED.findall(folded))
            elif isinstance(node, ast.Name):
                self._reach_name(node, bound, facts, seen, nested=nested, weakened=weak)
            elif isinstance(node, ast.Attribute):
                facts.names.add(node.attr)
                if node.attr in _TABLE_METHODS:
                    self._table_position(node.value, bound, facts)
            elif isinstance(node, ast.Subscript):
                self._subscript(node, facts)
            if isinstance(node, ast.Call):
                self._reach_call(node, bound, facts, seen, nested=nested, weakened=weak)
            if (
                isinstance(node, ast.Compare)
                and len(node.ops) == 1
                and isinstance(node.ops[0], ast.Eq)
            ):
                facts.links.append(
                    self._link(node.left, node.comparators[0], bound, filters=not weak)
                )

    def _link(self, left: ast.AST, right: ast.AST, bound: _Bound, *, filters: bool) -> _Link:
        return _Link(
            self._names(left, bound),
            self._names(right, bound),
            self._columns(left, bound, set()),
            self._columns(right, bound, set()),
            filters=filters,
        )

    def _columns(self, node: ast.AST, bound: _Bound, seen: set[int]) -> frozenset[str] | None:
        """The columns `node` always is (`t.c.x`, `t.c["x"]`, `select(t.c.x)`), else None."""
        if id(node) in seen:
            return None
        seen.add(id(node))
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr in {"c", "columns"}
        ):
            return frozenset({node.attr})
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr in {"c", "columns"}
        ):
            key = _fold(node.slice)
            return None if key is None else frozenset({key})
        if isinstance(node, ast.Call | ast.Attribute):
            root = _chain_root(node, self.statement_calls)
            if (
                isinstance(root, ast.Call)
                and self.starts(root)
                and len(root.args) == 1
                and not root.keywords
            ):
                return self._columns(root.args[0], bound, seen)
            return None
        if isinstance(node, ast.Name):
            values = list(self.assigned(node))
            function = self.owner(node)
            if function is not None:
                values += bound.get((id(function), node.id)) or self.arguments(function, node.id)
            found = [self._columns(value, bound, seen) for value in values]
            if not found or any(columns is None for columns in found):
                return None
            return frozenset().union(*(c for c in found if c is not None))
        return None

    def _reach_name(
        self,
        node: ast.Name,
        bound: _Bound,
        facts: _Facts,
        seen: set[tuple[object, ...]],
        *,
        nested: bool,
        weakened: bool,
    ) -> None:
        facts.names.add(self.aliases.get(node.id, node.id))
        for value in self.assigned(node):
            key = ("local", id(value), weakened)
            if key not in seen:
                seen.add(key)
                self._reach(value, bound, facts, seen, nested=nested, weakened=weakened)
        function = self.owner(node)
        if function is not None:
            values = bound.get((id(function), node.id)) or self.arguments(function, node.id)
            for value in values:
                key = ("argument", id(value), id(function), weakened)
                if key not in seen:
                    seen.add(key)
                    self._reach(value, bound, facts, seen, nested=nested, weakened=weakened)
        if not isinstance(self.parent.get(node), ast.Call) or self.parent[node].func is not node:
            for function in self.functions.get(node.id, []):
                self._reach_returns(
                    function, bound, facts, seen, nested=nested, key=id(node), weakened=weakened
                )

    def _reach_call(
        self,
        node: ast.Call,
        bound: _Bound,
        facts: _Facts,
        seen: set[tuple[object, ...]],
        *,
        nested: bool,
        weakened: bool,
    ) -> None:
        called = _called_name(node)
        for function in self.functions.get(called or "", []):
            inner = dict(bound)
            for parameter, values in _bound(self, function, node).items():
                inner[(id(function), parameter)] = values
            self._reach_returns(
                function, inner, facts, seen, nested=nested, key=id(node), weakened=weakened
            )
        func = node.func
        if self._inner_join_on_derivation(node, bound):
            facts.joins_view = True
        if isinstance(func, ast.Attribute) and func.attr == "in_" and node.args:
            facts.links.append(self._link(func.value, node.args[0], bound, filters=not weakened))
        if isinstance(func, ast.Attribute) and func.attr == "select_from":
            for argument in node.args:
                self._table_position(argument, bound, facts)
        elif (
            isinstance(func, ast.Attribute)
            and func.attr in _JOINS
            and node.args
            and not isinstance(func.value, ast.Constant)  # `", ".join(...)` is a string's
        ):
            self._table_position(node.args[0], bound, facts)
        elif isinstance(func, ast.Name) and func.id in _JOINS:
            for argument in node.args[:2]:
                self._table_position(argument, bound, facts)
        if (
            isinstance(func, ast.Name)
            and func.id == "getattr"
            and len(node.args) > 1
            and _fold(node.args[1]) is None
        ):
            facts.unresolved.add(ast.unparse(node))

    def _inner_join_on_derivation(self, node: ast.Call, bound: _Bound) -> bool:
        """`a.join(b, on)` / `join(a, b, on)`: inner, the view a side, `on` on `derivation_id`.

        Ruling R3-01: `outerjoin`, `isouter=`, `full=`, an ON clause that is
        `true()` or on another column, and an ON link under `or_()` / `not_()`
        never count.
        """
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "join":
            sides = self._joined_tables(node, bound)
            positional = node.args[1:2]
        elif isinstance(func, ast.Name) and func.id == "join":
            sides = set().union(*(self._names(a, bound) for a in node.args[:2]))
            positional = node.args[2:3]
        else:
            return False
        keywords = {k.arg: k.value for k in node.keywords if k.arg is not None}
        for flag in ("isouter", "full"):
            value = keywords.get(flag)
            if value is not None and not (isinstance(value, ast.Constant) and value.value is False):
                return False
        on = positional[0] if positional else keywords.get("onclause")
        if VIEW not in sides or on is None:
            return False
        return self.facts([on], bound=bound).semi_joined

    def _reach_returns(
        self,
        function: _Def,
        bound: _Bound,
        facts: _Facts,
        seen: set[tuple[object, ...]],
        *,
        nested: bool,
        key: int,
        weakened: bool,
    ) -> None:
        marker = ("returns", id(function), key, weakened)
        if marker in seen:
            return
        seen.add(marker)
        for value in _returns(function):
            self._reach(value, bound, facts, seen, nested=nested, weakened=weakened)

    def _joined_tables(self, node: ast.Call, bound: _Bound) -> set[str]:
        """The tables a `.join(...)` chain joins (never the names in its ON clauses)."""
        assert isinstance(node.func, ast.Attribute)
        joined = self._names(node.args[0], bound) if node.args else set()
        receiver = node.func.value
        if (
            isinstance(receiver, ast.Call)
            and isinstance(receiver.func, ast.Attribute)
            and receiver.func.attr in _JOINS
        ):
            return joined | self._joined_tables(receiver, bound)
        return joined | self._names(receiver, bound)

    def _subscript(self, node: ast.Subscript, facts: _Facts) -> None:
        """`metadata.tables[<computed>]` names a table nobody can read."""
        if (
            isinstance(node.value, ast.Attribute)
            and node.value.attr == "tables"
            and _fold(node.slice) is None
        ):
            facts.unresolved.add(ast.unparse(node))

    # --- table positions (ruling R2-02: fail closed) -----------------------------

    def _table_position(self, node: ast.AST, bound: _Bound, facts: _Facts) -> None:
        """`node` is read as a table: it must resolve to a table or a statement local.

        Ruling R3-02: a Call or a Subscript in a table position fails closed
        too, unless it is a table method on a resolving receiver, a statement
        or SQLAlchemy call, a call of a module helper whose returns all
        resolve, or `<metadata>.tables[<constant>]`.
        """
        if isinstance(node, ast.Name):
            if not self._resolves(node, bound, set()):
                facts.unresolved.add(node.id)
        elif isinstance(node, ast.Attribute):
            known = node.attr in self.aliases.values() or node.attr.startswith("project_report_")
            module = isinstance(node.value, ast.Name) and node.value.id in self.table_modules
            if not (known and module) and not self._resolves_value(node, bound, set()):
                facts.unresolved.add(ast.unparse(node))
        elif isinstance(node, ast.Call | ast.Subscript) and not self._resolves_value(
            node, bound, set()
        ):
            facts.unresolved.add(ast.unparse(node))

    def _resolves(self, node: ast.Name, bound: _Bound, seen: set[int]) -> bool:
        if id(node) in seen:
            return True
        seen.add(id(node))
        if (
            node.id in self.aliases
            or node.id in self.table_modules
            or node.id in self.sqlalchemy
            or node.id in self.statement_calls
            or node.id in self.functions
        ):
            return True
        values = list(self.assigned(node))
        function = self.owner(node)
        if function is not None:
            values += bound.get((id(function), node.id)) or self.arguments(function, node.id)
        return bool(values) and all(self._resolves_value(v, bound, seen) for v in values)

    def _resolves_value(self, value: ast.AST, bound: _Bound, seen: set[int]) -> bool:
        if isinstance(value, ast.Lambda | ast.Constant):
            return True
        if isinstance(value, ast.Starred):
            return self._resolves_value(value.value, bound, seen)
        if isinstance(value, ast.Tuple | ast.List):
            return all(self._resolves_value(e, bound, seen) for e in value.elts)
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "getattr"
        ):
            return len(value.args) > 1 and _fold(value.args[1]) is not None
        if (
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id in self.table_modules
        ):
            return True
        if isinstance(value, ast.Subscript):
            # Only `<metadata>.tables[<constant>]` (ruling R3-02: `TABLES[k]`,
            # `vars(tables)[k]` and any other lookup fail closed).
            return (
                isinstance(value.value, ast.Attribute)
                and value.value.attr == "tables"
                and _fold(value.slice) is not None
            )
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            return self._resolves_call(value.func.id, bound, seen)
        if isinstance(value, ast.Call):
            # A method on a receiver (`lines.join(...)`, `select(...).subquery()`).
            return self._resolves_value(value.func, bound, seen)
        if isinstance(value, ast.Attribute):
            return self._resolves_value(value.value, bound, seen)
        return isinstance(value, ast.Name) and self._resolves(value, bound, seen)

    def _resolves_call(self, name: str, bound: _Bound, seen: set[int]) -> bool:
        """A call of `name` yields a known table: SQLAlchemy, a statement, or a helper.

        A module helper resolves only when every value it returns resolves
        (ruling R3-02); an imported helper, a builtin (`next`, `vars`) or an
        unknown name fails closed.
        """
        if name in self.sqlalchemy or name in self.statement_calls:
            return True
        functions = self.functions.get(name, [])
        returns = [value for function in functions for value in _returns(function)]
        if not returns:
            return False
        marker = id(functions[0])
        if marker in seen:
            return True
        seen.add(marker)
        return all(self._resolves_value(value, bound, seen) for value in returns)


#: `(id(function), parameter)` -> the expressions a call binds it to.
_Bound = dict[tuple[int, str], list[ast.AST]]


def _parameters(function: _Def) -> list[str]:
    arguments = function.args
    return [
        a.arg
        for a in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
        if a.arg not in {"self", "cls"}
    ]


def _defaults(function: _Def) -> dict[str, list[ast.AST]]:
    arguments = function.args
    positional = [*arguments.posonlyargs, *arguments.args]
    found: dict[str, list[ast.AST]] = {}
    for parameter, default in zip(
        positional[len(positional) - len(arguments.defaults) :], arguments.defaults, strict=True
    ):
        found[parameter.arg] = [default]
    for parameter, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True):
        if default is not None:
            found[parameter.arg] = [default]
    return found


def _bound(module: _Module, function: _Def, call: ast.Call) -> dict[str, list[ast.AST]]:
    """The parameters a call binds, with the defaults of those it leaves out."""
    arguments = function.args
    positional = [a.arg for a in (*arguments.posonlyargs, *arguments.args)]
    if positional and positional[0] in {"self", "cls"} and isinstance(call.func, ast.Attribute):
        positional = positional[1:]
    found: dict[str, list[ast.AST]] = {}
    for parameter, value in zip(positional, call.args, strict=False):
        if not isinstance(value, ast.Starred):
            found[parameter] = [value]
    for keyword in call.keywords:
        if keyword.arg is not None:
            found[keyword.arg] = [keyword.value]
    for parameter, values in _defaults(function).items():
        found.setdefault(parameter, values)
    return found


def _returns(function: _Def) -> list[ast.AST]:
    if isinstance(function, ast.Lambda):
        return [function.body]
    found: list[ast.AST] = []
    todo: list[ast.AST] = list(function.body)
    while todo:
        node = todo.pop()
        if isinstance(node, ast.Return) and node.value is not None:
            found.append(node.value)
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                todo.append(child)
    return found


def _lambda_name(module: _Module, function: ast.Lambda) -> str | None:
    holder = module.parent.get(function)
    if isinstance(holder, ast.Assign) and isinstance(holder.targets[0], ast.Name):
        return holder.targets[0].id
    return None


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _weakens(parent: ast.AST, child: ast.AST) -> bool:
    """`child` is a negation, an alternative or an ON clause: its links never filter.

    `~`, `not`, `not_()`, `or_()` and `|` weaken what they hold. A join's ON
    clause filters only as an inner join of the view (`_inner_join_on_derivation`
    reads it on its own), so an outer join's ON never passes for a semi-join.
    """
    if isinstance(parent, ast.Call) and _called_name(parent) in _JOINS:
        first_on = 1 if isinstance(parent.func, ast.Attribute) else 2
        if child in parent.args[first_on:] or (
            isinstance(child, ast.keyword) and child.arg == "onclause"
        ):
            return True
    if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Invert | ast.Not):
        return True
    if isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.BitOr):
        return True
    if isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.Or):
        return True
    return (
        isinstance(parent, ast.Call)
        and child is not parent.func
        and _called_name(parent) in _WEAKENS
    )


def _fold(node: ast.AST) -> str | None:
    """A string an expression always evaluates to (literals and `+` of them), else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _fold(node.left), _fold(node.right)
        return None if left is None or right is None else left + right
    return None


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
    # `self.x = <table>` binds an attribute nobody resolves: left to fail closed.
    return pairs


def _starts_statement(node: ast.AST, calls: frozenset[str] | set[str] = _STATEMENTS) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id in calls) or (
        isinstance(func, ast.Attribute) and func.attr in _STATEMENTS
    )


def _chain_root(node: ast.AST, calls: frozenset[str] | set[str] = _STATEMENTS) -> ast.AST:
    """The start of a method chain: the statement call, or the name it extends."""
    while True:
        if isinstance(node, ast.Call):
            if _starts_statement(node, calls):
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


def _is_selectable(module: _Module, node: ast.AST, seen: set[int] | None = None) -> bool:
    """A table, join, alias or selectable; never a column (`t.c.x`) or a method on one.

    Ruling R2-06: a helper returning a child *column* (or a predicate built on
    one) is not a bare table. A call is selectable only as a table method
    (`.join`, `.alias`, ...) on a selectable, or as a helper returning one.
    """
    seen = set() if seen is None else seen
    if id(node) in seen:
        return False
    seen.add(id(node))
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        if node.attr in {"c", "columns"}:
            return False
        return _is_selectable(module, node.value, seen)
    if isinstance(node, ast.Subscript):
        return isinstance(node.value, ast.Attribute) and node.value.attr == "tables"
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _TABLE_METHODS - {"c", "columns"}:
            return _is_selectable(module, func.value, seen)
        if isinstance(func, ast.Name) and func.id == "getattr":
            return True
        called = _called_name(node)
        return any(
            _is_selectable(module, value, seen)
            for function in module.functions.get(called or "", [])
            for value in _returns(function)
        )
    return False


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
                root = _chain_root(value, module.statement_calls)
                if module.starts(root) or (isinstance(root, ast.Name) and root.id in held):
                    held.add(name)
                    changed = True
                    break
    return held


def _enclosing(module: _Module, node: ast.AST, held: set[str]) -> list[ast.AST]:
    """The statements `node` is nested in: statement calls, or extensions of held ones."""
    found: list[ast.AST] = []
    current = module.parent.get(node)
    while current is not None:
        if module.starts(current):
            found.append(current)
        elif isinstance(current, ast.Call):
            root = _chain_root(current, module.statement_calls)
            if isinstance(root, ast.Name) and root.id in held:
                found.append(root)
        current = module.parent.get(current)
    return found


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
    """A statement's chain and, when assigned to a held local, every extension of it.

    `root` may also be a held local's name: then its parts are every value
    assigned to it and every extension of it.
    """
    scope = module.scope_of(root)
    if isinstance(root, ast.Name):
        targets = {root.id}
        parts: list[ast.AST] = list(module.locals.get(scope, {}).get(root.id, []))
    else:
        chain = _whole_chain(module, root)
        parts = [chain]
        parent = module.parent.get(chain)
        targets = (
            {n.id for t in parent.targets for n in ast.walk(t) if isinstance(n, ast.Name)}
            if isinstance(parent, ast.Assign)
            else set()
        )
    for node in ast.walk(scope):
        if isinstance(node, ast.Call):
            base = _chain_root(node, module.statement_calls)
            if isinstance(base, ast.Name) and base.id in targets & held:
                parts.append(node)
    return parts


def _unjoined_child_reads(source: str) -> list[str]:
    """`<scope>:<line>` of every statement over a child table that does not join the view.

    A top-level statement that names a child table must join the view (a
    join, or a semi-join of a child column on it); a merely mentioned view
    never counts. A nested statement that brings in a child table its outer
    statement does not read must join the view itself, or be correlated to
    the outer statement (an `==` or `.in_` between the new child table and
    one the outer statement reads). Any table position that resolves to no
    known table or statement local fails closed. Also every helper (a
    function or a lambda) returning a bare child table, join or alias
    without the view, and every string spelling a child table without the
    view or computing a table name.
    """
    module = _Module(source)
    found: list[tuple[int, str]] = []
    held_by_scope: dict[ast.AST, set[str]] = {}
    for node in ast.walk(module.tree):
        if not module.starts(node):
            continue
        scope = module.scope_of(node)
        held = held_by_scope.setdefault(scope, _statement_variables(module, scope))
        outer = _enclosing(module, node, held)
        if not outer:
            facts = module.facts(_statement_parts(module, node, held))
            if facts.unresolved or (facts.children and not facts.joined):
                found.append((node.lineno, module.name_of(node)))
            continue
        own = _Facts()
        for statement in outer:
            reached = module.facts(_statement_parts(module, statement, held), nested=False)
            own.names |= reached.names
        mine = module.facts([_whole_chain(module, node)])
        new = mine.children - own.children
        correlated = mine.linked(new, own.children | {VIEW})
        if mine.unresolved or (new and not (mine.joined or correlated)):
            found.append((node.lineno, module.name_of(node)))
    # Ruling R3-02: a local (or a parameter) that rebinds the view's name, or an
    # alias it is imported as, makes every join of "the view" a join of whatever
    # it now holds.
    for scope, bindings in module.locals.items():
        for name, values in bindings.items():
            if name == VIEW or module.aliases.get(name) == VIEW:
                found += [
                    (getattr(value, "lineno", 0), f"rebinds the view in {_scope_name(scope)}")
                    for value in values
                ]
    for node in ast.walk(module.tree):
        if isinstance(node, _Def):
            found += [
                (node.lineno, f"rebinds the view in {_scope_name(node)}")
                for name in _parameters(node)
                if name == VIEW or module.aliases.get(name) == VIEW
            ]
    for name, functions in module.functions.items():
        for function in functions:
            for value in _returns(function):
                if not _is_selectable(module, value):
                    continue
                facts = module.facts([value])
                if facts.unresolved or (facts.children and not facts.joined):
                    found.append((value.lineno, f"helper {name}"))
    for node in ast.walk(module.tree):
        if _is_docstring(module, node) or not (
            isinstance(node, ast.Constant) and isinstance(node.value, str)
        ):
            continue
        spelled = set(_SPELLED.findall(node.value))
        if (spelled & CHILDREN and VIEW not in spelled) or _COMPUTED.search(node.value):
            found.append((node.lineno, f"string in {module.name_of(node)}"))
    return [f"{name}:{line}" for line, name in sorted(set(found))]


def _scope_name(scope: ast.AST) -> str:
    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
        return scope.name
    return "<lambda>" if isinstance(scope, ast.Lambda) else "<module>"


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
#: The ON clause a join of the view filters on (ruling R3-01).
_ON: Final = "{t}.c.derivation_id == project_report_current_derivations.c.derivation_id"
_JOINED: Final = f"lines.join(project_report_current_derivations, {_ON.format(t='lines')})"


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
        "        project_report_current_derivations.c.derivation_id\n"
        "        == checks.c.left_derivation_id)))\n"
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
        "    joined = totals.join(project_report_current_derivations, on)\n    return totals\n",
    )
    assert _planted(performed) == ["helper _source", "read"]
    # The returned join is the helper's value: it counts, for the helper and its callers.
    returned = bare.replace(
        "    return totals\n",
        f"    return totals.join(project_report_current_derivations, {_ON.format(t='totals')})\n",
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
    # A subquery of a held statement's extension is nested in that statement: a
    # child table it brings in must be correlated to the outer one (R2-02).
    extended = (
        "def read():\n"
        f"    statement = select(lines.c.row_ordinal).select_from({_JOINED})\n"
        "    statement = statement.where(exists(select(literal(1)).where(\n"
        "        values.c.derivation_id == lines.c.derivation_id)))\n"
        "    return statement\n"
    )
    assert _planted(extended) == []
    uncorrelated = extended.replace(
        "values.c.derivation_id == lines.c.derivation_id", "values.c.x == 1"
    )
    assert _planted(uncorrelated) == ["read"]


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


# --- ruling R2-02: the bypasses the WP4P-R2 review planted -------------------------


def test_a_table_passed_as_an_argument_is_caught() -> None:
    """Mutant G1's shape: the statement lives in a helper that takes the table."""
    planted = (
        "def _evidence(table, ids):\n"
        "    return select(table.c.x).where(table.c.derivation_id.in_(ids))\n"
        "def read(ids):\n"
        "    return _evidence(totals, ids).order_by(totals.c.row_ordinal)\n"
    )
    assert _planted(planted) == ["_evidence"]
    joined = planted.replace(
        "select(table.c.x)",
        "select(table.c.x).select_from(table.join(project_report_current_derivations, "
        f"{_ON.format(t='table')}))",
    )
    assert _planted(joined) == []
    # A default argument binds the parameter too.
    assert _planted("def read(t=totals):\n    return select(t.c.x)\n") == ["read"]


def test_select_under_any_name_is_a_statement() -> None:
    aliased = "from sqlalchemy import select as sel\ndef read():\n    return sel(lines.c.x)\n"
    assert _planted(aliased) == ["read"]
    module = "import sqlalchemy as sa\ndef read():\n    return sa.Select(lines.c.x)\n"
    assert _planted(module) == ["read"]
    imported = "from sqlalchemy.sql import Select\ndef read():\n    return Select(lines.c.x)\n"
    assert _planted(imported) == ["read"]


def test_an_unresolved_table_fails_closed() -> None:
    """A table position nobody can resolve (`self`, a computed lookup) is a violation."""
    held = (
        "class R:\n"
        "    def __init__(self):\n"
        "        self._t = totals\n"
        "    def read(self):\n"
        "        return select(self._t.c.x)\n"
    )
    assert _planted(held) == ["read"]
    module = "from my_pa.infrastructure.persistence import tables\n"
    computed = f"{module}def read(kind):\n    return select(getattr(tables, kind).c.x)\n"
    assert _planted(computed) == ["read"]
    concatenated = (
        f"{module}def read():\n"
        "    t = getattr(tables, 'project_report_' + 'lines')\n"
        "    return select(t.c.x)\n"
    )
    assert sorted(_planted(concatenated)) == ["read", "string in read"]
    spelled = "def read(kind):\n    return text(f'SELECT 1 FROM knowledge.project_report_{kind}')\n"
    assert _planted(spelled) == ["string in read"]
    looked_up = (
        "def read(name):\n"
        "    t = metadata.tables[f'knowledge.project_report_{name}']\n"
        "    return select(t.c.x)\n"
    )
    assert sorted(_planted(looked_up)) == ["read", "string in read"]
    unknown = "def read():\n    return select(somewhere.c.x)\n"
    assert _planted(unknown) == ["read"]


def test_a_mentioned_view_is_not_a_joined_one() -> None:
    """Joined means a join (or a semi-join on a child column), never a mention."""
    uncorrelated = (
        "def read():\n"
        "    return select(lines.c.x).where(exists(select(literal(1)).select_from(\n"
        "        project_report_current_derivations)))\n"
    )
    assert _planted(uncorrelated) == ["read"]
    cross = (
        "def read():\n"
        "    return select(lines.c.x).where(\n"
        "        project_report_current_derivations.c.derivation_id.is_not(None))\n"
    )
    assert _planted(cross) == ["read"]
    semi = (
        "def read():\n"
        "    return select(lines.c.x).where(lines.c.derivation_id.in_(\n"
        "        select(project_report_current_derivations.c.derivation_id)))\n"
    )
    assert _planted(semi) == []
    unjoined_text = (
        'def read():\n    return text("SELECT 1 FROM knowledge.project_report_lines, "\n'
    )
    unjoined_text += '                "knowledge.project_report_current_derivations")\n'
    assert _planted(unjoined_text) == ["read"]


def test_an_uncorrelated_child_subquery_in_a_joined_statement_is_caught() -> None:
    scalar = (
        "def read():\n"
        "    return select(lines.c.x, select(values.c.raw_text).scalar_subquery())"
        f".select_from({_JOINED})\n"
    )
    assert _planted(scalar) == ["read"]
    correlated = scalar.replace(
        "select(values.c.raw_text)",
        "select(values.c.raw_text).where(values.c.derivation_id == lines.c.derivation_id)",
    )
    assert _planted(correlated) == []
    within = (
        "def read():\n"
        f"    return select(lines.c.x).select_from({_JOINED}).where(\n"
        "        lines.c.row_ordinal.in_(select(totals.c.row_ordinal)))\n"
    )
    assert _planted(within) == ["read"]
    assigned = (
        "def read():\n"
        "    v = select(values.c.x).cte('v')\n"
        f"    return select(v.c.x).select_from({_JOINED})\n"
    )
    assert _planted(assigned) == ["read"]
    united = (
        "def read():\n"
        f"    return select(lines.c.x).select_from({_JOINED}).union(select(values.c.y))\n"
    )
    assert _planted(united) == ["read"]


def test_a_helper_returning_a_child_column_is_not_a_bare_table() -> None:
    """Ruling R2-06: the helper rule applies to tables, joins and selectables only."""
    column = (
        "def _col():\n"
        "    return lines.c.derivation_id\n"
        f"def read():\n    return select(_col()).select_from({_JOINED})\n"
    )
    assert _planted(column) == []
    predicate = (
        "def _where():\n"
        "    return lines.c.derivation_id.in_(ids)\n"
        f"def read():\n    return select(lines.c.x).select_from({_JOINED}).where(_where())\n"
    )
    assert _planted(predicate) == []
    # The control: a helper returning the bare table is still caught.
    table = column.replace("return lines.c.derivation_id", "return lines")
    assert _planted(table) == ["helper _col"]


# --- ruling R3-01: a join of the view that does not filter --------------------------


def _read(statement: str) -> str:
    return f"def read():\n    return {statement}\n"


_CURRENT: Final = "project_report_current_derivations"
_ON_LINES: Final = _ON.format(t="lines")
_SEMI: Final = (
    f"exists(select(literal(1)).where({_CURRENT}.c.derivation_id == lines.c.derivation_id))"
)
_IN: Final = f"lines.c.derivation_id.in_(select({_CURRENT}.c.derivation_id))"


@pytest.mark.parametrize(
    "joined",
    [
        f"lines.outerjoin({_CURRENT}, {_ON_LINES})",
        f"lines.join({_CURRENT}, {_ON_LINES}, isouter=True)",
        f"lines.join({_CURRENT}, {_ON_LINES}, full=True)",
        f"join(lines, {_CURRENT}, {_ON_LINES}, isouter=True)",
    ],
    ids=["outerjoin", "isouter", "full", "join-function-isouter"],
)
def test_an_outer_join_of_the_view_is_caught(joined: str) -> None:
    """Probe (a): a LEFT or FULL join keeps every line, superseded or not."""
    head = "from sqlalchemy import join\n"
    assert _planted(head + _read(f"select(lines.c.x).select_from({joined})")) == ["read"]
    inner = joined.replace("outerjoin", "join")
    for flag in (", isouter=True", ", full=True"):
        inner = inner.replace(flag, "")
    assert _planted(head + _read(f"select(lines.c.x).select_from({inner})")) == []


@pytest.mark.parametrize(
    "where",
    [f"~{_SEMI}", f"~{_IN}", f"not_({_SEMI})", f"or_({_SEMI}, true())", f"{_IN} | true()"],
    ids=["invert-exists", "invert-in", "not_", "or_", "bitor"],
)
def test_an_anti_join_or_an_alternative_is_caught(where: str) -> None:
    """Probe (b): a negated or alternative semi-join reads the superseded derivations too."""
    assert _planted(_read(f"select(lines.c.x).where({where})")) == ["read"]
    # The controls: the same semi-joins, plain or under `and_`, filter.
    assert _planted(_read(f"select(lines.c.x).where({_SEMI})")) == []
    assert _planted(_read(f"select(lines.c.x).where(and_({_IN}, true()))")) == []


@pytest.mark.parametrize(
    "sql",
    [
        "FROM knowledge.project_report_lines LEFT JOIN knowledge.{v} USING (derivation_id)",
        "FROM knowledge.project_report_lines LEFT OUTER JOIN knowledge.{v} v "
        "ON l.derivation_id = v.derivation_id",
        "FROM knowledge.project_report_lines RIGHT JOIN knowledge.{v} USING (derivation_id)",
        "FROM knowledge.project_report_lines FULL JOIN knowledge.{v} USING (derivation_id)",
        "FROM knowledge.project_report_lines CROSS JOIN knowledge.{v}",
        "FROM knowledge.project_report_lines JOIN knowledge.{v} ON true",
        "FROM knowledge.project_report_lines l JOIN knowledge.{v} v "
        "ON l.principal_id = v.principal_id",
        "FROM knowledge.project_report_lines l JOIN knowledge.{v} v "
        "ON l.derivation_id = v.derivation_id OR true",
    ],
    ids=["left", "left-outer", "right", "full", "cross", "on-true", "other-column", "on-or"],
)
def test_a_text_join_that_does_not_filter_is_caught(sql: str) -> None:
    """Probe (c): `text()` must spell an inner join of the view on `derivation_id`."""
    assert _planted(_read(f'text("SELECT 1 {sql.format(v=_CURRENT)}")')) == ["read"]


def test_a_text_inner_join_on_the_derivation_filters() -> None:
    for sql in (
        "FROM knowledge.project_report_lines JOIN knowledge.{v} USING (derivation_id)",
        "FROM knowledge.project_report_lines INNER JOIN knowledge.{v} USING (derivation_id)",
        "FROM knowledge.project_report_lines l JOIN knowledge.{v} AS v "
        "ON l.principal_id = v.principal_id AND l.derivation_id = v.derivation_id WHERE x",
    ):
        assert _planted(_read(f'text("SELECT 1 {sql.format(v=_CURRENT)}")')) == [], sql


@pytest.mark.parametrize(
    "joined",
    [
        f"lines.join({_CURRENT}, true())",
        f"lines.join({_CURRENT}, lines.c.principal_id == {_CURRENT}.c.principal_id)",
        f"lines.join({_CURRENT}, lines.c.row_ordinal == {_CURRENT}.c.derivation_id)",
        f"lines.join({_CURRENT}, lines.c.derivation_id == {_CURRENT}.c.snapshot_id)",
        f"lines.join({_CURRENT}, or_({_ON_LINES}, true()))",
        f"lines.join({_CURRENT})",
    ],
    ids=["on-true", "principal", "wrong-child-column", "wrong-view-column", "on-or", "no-on"],
)
def test_a_join_on_the_wrong_column_is_caught(joined: str) -> None:
    """Probe (d): only `derivation_id` = the view's `derivation_id` links the two."""
    assert _planted(_read(f"select(lines.c.x).select_from({joined})")) == ["read"]


def test_a_semi_join_on_the_wrong_column_is_caught() -> None:
    """Probe (d): a bare `==` semi-join counts only on `derivation_id`."""
    principal = f"lines.c.principal_id == {_CURRENT}.c.principal_id"
    assert _planted(_read(f"select(lines.c.x).where({principal})")) == ["read"]
    assert _planted(_read(f"select(lines.c.x).where({_ON_LINES})")) == []
    # The ON clause through a helper whose parameter is the child (the module's `_current`).
    helper = (
        "def _current(child):\n"
        f"    return and_(child.c.principal_id == {_CURRENT}.c.principal_id,\n"
        f"                child.c.derivation_id == {_CURRENT}.c.derivation_id)\n"
    )
    joined = f"select(lines.c.x).select_from(lines.join({_CURRENT}, _current(lines)))"
    assert _planted(helper + _read(joined)) == []
    wrong = helper.replace("child.c.derivation_id ==", "child.c.row_ordinal ==")
    assert _planted(wrong + _read(joined)) == ["read"]


# --- ruling R3-02: table positions that failed open ---------------------------------


@pytest.mark.parametrize(
    "position",
    [
        "somewhere()",
        "child_table()",
        "vars(tables)[k]",
        "TABLES[k]",
        "next(t for t in metadata.sorted_tables if t.name == k)",
        "self._source()",
    ],
    ids=["unknown-call", "imported-helper", "vars-subscript", "global-subscript", "next", "method"],
)
def test_a_call_or_subscript_in_a_table_position_fails_closed(position: str) -> None:
    """A Call or Subscript that resolves to no known table is a violation."""
    head = (
        "from my_pa.infrastructure.persistence import tables\n"
        "from elsewhere import child_table\n"
        "TABLES = {'l': lines}\n"
    )
    planted = _planted(head + f"def read(k):\n    return select({position}.c.x)\n")
    assert planted == ["read"]


def test_a_resolving_call_or_subscript_in_a_table_position_passes() -> None:
    """The controls: a helper whose returns resolve, a table method, a constant lookup."""
    helper = (
        f"def _joined():\n    return {_JOINED}\ndef read():\n    return select(_joined().c.x)\n"
    )
    assert _planted(helper) == []
    method = f"def read():\n    return select(lines.c.x).select_from({_JOINED}.alias('a'))\n"
    assert _planted(method) == []
    constant = (
        "def read():\n"
        "    t = metadata.tables['knowledge.project_report_current_derivations']\n"
        "    return select(t.c.x)\n"
    )
    assert _planted(constant) == []
    # A helper whose return does not resolve is itself unresolved.
    unresolved = helper.replace(f"    return {_JOINED}\n", "    return somewhere()\n")
    assert _planted(unresolved) == ["read"]


@pytest.mark.parametrize(
    "rebinding",
    [
        "    project_report_current_derivations = lines.alias('x')\n",
        "    for project_report_current_derivations in (lines,):\n        pass\n",
        "    current = lines\n",
    ],
    ids=["assign", "for-target", "alias-name"],
)
def test_a_local_that_rebinds_the_view_is_caught(rebinding: str) -> None:
    """The static-only bypass: the view's name now holds a child table."""
    head = (
        "from my_pa.infrastructure.persistence.tables import "
        "project_report_current_derivations as current\n"
        if "current = " in rebinding
        else ""
    )
    view = "current" if head else _CURRENT
    joined = f"lines.join({view}, lines.c.derivation_id == {view}.c.derivation_id)"
    planted = head + f"def read():\n{rebinding}    return select(lines.c.x).select_from({joined})\n"
    assert "rebinds the view in read" in _planted(planted)
    assert (
        _planted(head + f"def read():\n    return select(lines.c.x).select_from({joined})\n") == []
    )


def test_a_parameter_that_rebinds_the_view_is_caught() -> None:
    planted = (
        "def read(project_report_current_derivations=lines):\n"
        f"    return select(lines.c.x).select_from({_JOINED})\n"
    )
    assert "rebinds the view in read" in _planted(planted)
