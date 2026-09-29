"""T-18 (WP-RE-01 scope): the Record Event flush happens in one place, the right way.

RE-AC-014: the flush is the last database work before COMMIT. The lock-order
proof (TRANSACTION matrix section 5) holds only while three things stay true,
and this module parses the source tree to hold them there:

1. **The flush is reached only from a transaction owner's exit.** Production
   code calls `flush_record_events` from exactly the four SQL unit-of-work
   `__exit__` methods (U1-U4) -- never from a service, a repository or a
   handler, where it could run before other domain work.
2. **In each of those exits the flush precedes the connection clear**
   (G1-TX-001, stop N7): the call appears before `self._connection = None`.
3. **Staging never happens inside a savepoint** (G1-TX-007): no `stage(` call
   sits inside a `with ....begin_nested()` block, where a rolled-back savepoint
   could leave a draft for a change that never committed.

Plus four structural facts the design depends on:

4. the causation foreign key is NOT DEFERRABLE, in `tables.py` and in the
   revision's frozen DDL, so no event check is deferred to COMMIT;
5. each of U1-U4 overrides `record_events` in its own class body, rather than
   inheriting the port's refusing default;
6. no production code catches `NotImplementedError` around `record_events` --
   the refusing default is fail-closed only while nobody swallows it.

**Extension point (WP-RE-04).** `FLUSH_SITES` is the exact set of production
functions allowed to flush. WP-RE-04 adds the re-enrichment worker's (W5)
end-of-transaction flush to it, with that module's own ordering clause
(exactly one flush per committing exit, after `_correct_settlement_to_partial`),
and adds the memory-never-a-causation-root clause beside `test_*` below. Neither
is asserted here.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from sqlalchemy import ForeignKeyConstraint

from my_pa.infrastructure.persistence.tables import record_events

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"
PERSISTENCE: Final = PACKAGE / "infrastructure" / "persistence"
#: Found by its slug rather than its revision identifier: under OD-4 (Option B)
#: the revision is re-pointed in WP-RE-06, and this guard must not pin the head.
(MIGRATION,) = sorted((ROOT / "migrations" / "versions").glob("*_record_events.py"))
FLUSH: Final = "flush_record_events"

#: `(module relative to src/my_pa, class, function)` for every production call
#: of the flush. WP-RE-04 adds the W5 re-enrichment worker site here.
FLUSH_SITES: Final[frozenset[tuple[str, str, str]]] = frozenset(
    {
        ("infrastructure/persistence/unit_of_work.py", "SqlAlchemyUnitOfWork", "__exit__"),
        (
            "infrastructure/persistence/task_management.py",
            "SqlAlchemyTaskManagementUnitOfWork",
            "__exit__",
        ),
        (
            "infrastructure/persistence/commitment_management.py",
            "SqlAlchemyCommitmentManagementUnitOfWork",
            "__exit__",
        ),
        (
            "infrastructure/persistence/constraints.py",
            "SqlAlchemyConstraintManagementUnitOfWork",
            "__exit__",
        ),
    }
)

#: The four SQL transaction owners, each of which must own a buffer.
UNIT_OF_WORK_CLASSES: Final = frozenset((path, cls) for path, cls, _ in FLUSH_SITES)

CAUSATION_FOREIGN_KEY: Final = "a_record_event_cause_is_an_event_of_its_principal"


def _modules() -> Iterator[tuple[str, ast.Module]]:
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(PACKAGE).as_posix()
        yield relative, ast.parse(path.read_text(encoding="utf-8"))


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _enclosing(tree: ast.Module) -> Iterator[tuple[str, str, ast.AST]]:
    """`(class, function, node)` for every node under a function, `-` at module level."""
    for top in tree.body:
        if isinstance(top, ast.ClassDef):
            for member in top.body:
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
                    for node in ast.walk(member):
                        yield top.name, member.name, node
        elif isinstance(top, ast.FunctionDef | ast.AsyncFunctionDef):
            for node in ast.walk(top):
                yield "-", top.name, node


def _flush_calls() -> set[tuple[str, str, str]]:
    return {
        (relative, cls, function)
        for relative, tree in _modules()
        for cls, function, node in _enclosing(tree)
        if isinstance(node, ast.Call) and _called_name(node) == FLUSH
    }


def _function(relative: str, cls: str, function: str) -> ast.FunctionDef:
    tree = ast.parse((PACKAGE / relative).read_text(encoding="utf-8"))
    for top in tree.body:
        if isinstance(top, ast.ClassDef) and top.name == cls:
            for member in top.body:
                if isinstance(member, ast.FunctionDef) and member.name == function:
                    return member
    raise AssertionError(f"{relative}:{cls}.{function} not found")


def test_the_flush_is_called_only_from_the_four_unit_of_work_exits() -> None:
    assert _flush_calls() == FLUSH_SITES


def test_each_exit_flushes_before_it_clears_its_connection() -> None:
    for relative, cls, function in FLUSH_SITES:
        body = _function(relative, cls, function)
        flush_lines = [
            node.lineno
            for node in ast.walk(body)
            if isinstance(node, ast.Call) and _called_name(node) == FLUSH
        ]
        clear_lines = [
            node.lineno
            for node in ast.walk(body)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute) and target.attr == "_connection"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and node.value.value is None
        ]
        assert len(flush_lines) == 1, f"{cls}.{function} flushes {len(flush_lines)} times"
        assert clear_lines, f"{cls}.{function} never clears its connection"
        assert flush_lines[0] < min(clear_lines), (
            f"{cls}.{function} clears its connection before it flushes (stop N7)"
        )


def _stage_inside_savepoint(tree: ast.Module) -> list[int]:
    found: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.With | ast.AsyncWith):
            continue
        if not any(
            isinstance(item.context_expr, ast.Call)
            and _called_name(item.context_expr) == "begin_nested"
            for item in node.items
        ):
            continue
        found.extend(
            inner.lineno
            for statement in node.body
            for inner in ast.walk(statement)
            if isinstance(inner, ast.Call) and _called_name(inner) == "stage"
        )
    return found


def test_no_draft_is_staged_inside_a_savepoint() -> None:
    offenders = {
        relative: lines for relative, tree in _modules() if (lines := _stage_inside_savepoint(tree))
    }
    assert offenders == {}


def test_the_savepoint_scan_sees_a_stage_inside_begin_nested() -> None:
    """The control: the scan above is not vacuous."""
    planted = ast.parse(
        "def f(connection, stager, draft):\n"
        "    with connection.begin_nested():\n"
        "        stager.stage(draft)\n"
    )
    assert _stage_inside_savepoint(planted) == [3]


def test_the_causation_foreign_key_is_not_deferrable() -> None:
    (foreign_key,) = (
        constraint
        for constraint in record_events.constraints
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name == CAUSATION_FOREIGN_KEY
    )
    assert foreign_key.deferrable is False
    assert foreign_key.initially is None
    ddl = MIGRATION.read_text(encoding="utf-8")
    start = ddl.index(f"CONSTRAINT {CAUSATION_FOREIGN_KEY}")
    clause = ddl[start : ddl.index(")\n", ddl.index("REFERENCES", start))]
    assert "NOT DEFERRABLE" in " ".join(clause.split())
    assert "INITIALLY DEFERRED" not in clause


def test_each_unit_of_work_owns_its_record_event_buffer() -> None:
    for relative, cls in UNIT_OF_WORK_CLASSES:
        tree = ast.parse((PACKAGE / relative).read_text(encoding="utf-8"))
        (declaration,) = (
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == cls
        )
        own = {
            member.name
            for member in declaration.body
            if isinstance(member, ast.FunctionDef)
            and any(
                isinstance(decorator, ast.Name) and decorator.id == "property"
                for decorator in member.decorator_list
            )
        }
        assert "record_events" in own, f"{cls} inherits the refusing default"


def _swallows_the_refusal(tree: ast.Module) -> list[int]:
    found: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        touches = any(
            isinstance(inner, ast.Attribute) and inner.attr == "record_events"
            for statement in node.body
            for inner in ast.walk(statement)
        )
        catches = any(
            handler.type is None
            or any(
                isinstance(name, ast.Name) and name.id == "NotImplementedError"
                for name in ast.walk(handler.type)
            )
            for handler in node.handlers
        )
        if touches and catches:
            found.append(node.lineno)
    return found


def test_no_production_code_swallows_the_refusing_default() -> None:
    offenders = {
        relative: lines for relative, tree in _modules() if (lines := _swallows_the_refusal(tree))
    }
    assert offenders == {}


def test_the_refusal_scan_sees_a_swallowed_refusal() -> None:
    """The control: the scan above is not vacuous."""
    planted = ast.parse(
        "def f(unit, draft):\n"
        "    try:\n"
        "        unit.record_events.stage(draft)\n"
        "    except NotImplementedError:\n"
        "        pass\n"
    )
    assert _swallows_the_refusal(planted) == [2]
