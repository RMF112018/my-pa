"""No runtime code writes the Knowledge predicate registry (KLP-WP-02, KLP-AC-004).

`knowledge.knowledge_assertion_predicates` is global, migration-owned vocabulary:
the single Knowledge revision inserts the eight seed rows (R6
section 11.6) and nothing else ever inserts, updates or deletes a row. The
database refuses UPDATE and DELETE by trigger; this module closes the INSERT
half statically, over every Python file under `src/`, `apps/` and `ops/`, and
over every other Alembic revision.

What it detects:

- SQL text that inserts into, updates, deletes from, copies into or truncates
  the registry, in any string constant (case-insensitive, schema-qualified or
  not);
- a SQLAlchemy `insert(...)` / `update(...)` / `delete(...)` whose first
  argument is the registry `Table`, under any import alias, and a
  `.insert()` / `.update()` / `.delete()` method call on it.

What it cannot see, stated rather than implied: SQL assembled at runtime from
fragments that never spell the table name, and writes from outside these
trees (for example a hand-run `psql`). Reads remain free: later work packages
select from the registry.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
TABLE: Final = "knowledge_assertion_predicates"
KNOWLEDGE_REVISION_SUFFIX: Final = "_knowledge_assertion_layer.py"
RUNTIME_TREES: Final = ("src", "apps", "ops")
_WRITE_SQL: Final = re.compile(
    rf"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|COPY|TRUNCATE(?:\s+TABLE)?)\s+"
    rf"(?:ONLY\s+)?(?:\"?knowledge\"?\s*\.\s*)?\"?{TABLE}\b",
    re.IGNORECASE,
)
_WRITE_CALLS: Final = frozenset({"insert", "update", "delete"})


def _python_files(*trees: str) -> Iterator[Path]:
    for tree in trees:
        yield from sorted((ROOT / tree).rglob("*.py"))


def _aliases(tree: ast.AST) -> set[str]:
    """Every local name bound to the registry `Table` by an import."""
    names = {TABLE}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == TABLE:
                    names.add(alias.asname or alias.name)
    return names


def _is_registry(node: ast.expr, aliases: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in aliases
    if isinstance(node, ast.Attribute):
        return node.attr == TABLE
    return False


def writes(source: str) -> list[str]:
    """Every registry write `source` spells, as short descriptions."""
    found: list[str] = []
    tree = ast.parse(source)
    aliases = _aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _WRITE_SQL.search(node.value):
                found.append(f"SQL text at line {node.lineno}")
        elif isinstance(node, ast.JoinedStr):
            text = "".join(
                part.value
                for part in node.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
            if _WRITE_SQL.search(text):
                found.append(f"SQL f-string at line {node.lineno}")
        elif isinstance(node, ast.Call):
            function = node.func
            name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else None
            )
            if name in _WRITE_CALLS and node.args and _is_registry(node.args[0], aliases):
                found.append(f"{name}(registry) at line {node.lineno}")
            if (
                isinstance(function, ast.Attribute)
                and function.attr in _WRITE_CALLS
                and _is_registry(function.value, aliases)
            ):
                found.append(f"registry.{function.attr}() at line {node.lineno}")
    return found


def test_the_detector_finds_every_write_shape_it_claims() -> None:
    """The plant that keeps the scan below from being vacuous."""
    planted = {
        "insert": "from x import knowledge_assertion_predicates\n"
        "insert(knowledge_assertion_predicates).values(predicate_code='a.b')\n",
        "aliased": "from my_pa.infrastructure.persistence.tables import "
        "knowledge_assertion_predicates as registry\nupdate(registry)\n",
        "attribute": "tables.knowledge_assertion_predicates.delete()\n",
        "method": "knowledge_assertion_predicates.insert()\n",
        "sql": "SQL = 'insert into knowledge.knowledge_assertion_predicates values (1)'\n",
        "quoted_sql": 'SQL = \'DELETE FROM "knowledge"."knowledge_assertion_predicates"\'\n',
        "fstring": "SQL = f'UPDATE knowledge.knowledge_assertion_predicates SET x = {v}'\n",
        "truncate": "SQL = 'TRUNCATE TABLE knowledge_assertion_predicates'\n",
    }
    for shape, source in planted.items():
        assert writes(source), shape
    assert not writes(
        "select(knowledge_assertion_predicates).where(knowledge_assertion_predicates.c.x == 1)\n"
        "SQL = 'SELECT * FROM knowledge.knowledge_assertion_predicates'\n"
    )


def test_no_runtime_module_writes_the_predicate_registry() -> None:
    offenders = {
        path.relative_to(ROOT).as_posix(): found
        for path in _python_files(*RUNTIME_TREES)
        if (found := writes(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}


def test_the_runtime_scan_reads_the_registry_declaration() -> None:
    """Guards the parametrization: the trees are non-empty and hold the declaration."""
    files = list(_python_files(*RUNTIME_TREES))
    assert len(files) > 300
    declaration = ROOT / "src" / "my_pa" / "infrastructure" / "persistence" / "tables.py"
    assert declaration in files
    assert f'"{TABLE}"' in declaration.read_text(encoding="utf-8")


def test_only_the_knowledge_revision_inserts_seed_rows_and_none_updates_or_deletes() -> None:
    """AC-004: the eight seeds are the only rows; no revision rewrites them."""
    for path in _python_files("migrations"):
        found = writes(path.read_text(encoding="utf-8"))
        if path.name.endswith(KNOWLEDGE_REVISION_SUFFIX):
            assert len(found) == 1 and found[0].startswith("SQL text"), found
            assert "INSERT INTO knowledge.knowledge_assertion_predicates" in path.read_text(
                encoding="utf-8"
            )
        else:
            assert found == [], path.name
