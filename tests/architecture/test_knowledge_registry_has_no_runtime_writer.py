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

KLP-WP-04 extends it to KLP-AC-086 ("a self-improving task cannot change
authorization, source scope, predicate definitions or disclosure policy"). The
discovery client's own runtime paths (submit, checkpoint, Review) reach none of
the writers of that policy:

- predicate definitions: the registry scan above;
- source scope: `knowledge_discovery_source_profiles` (scope digest, authority
  ceiling, disabled_at) is written only by the maintenance body `_Maintenance`
  in the Knowledge persistence module, and that body's repository methods are
  called only by the registered operator command
  `apps/cli/knowledge_source_profiles.py`;
- authorization: `remote_capability_grants` is written only by its repository
  (`remote_identity.py`) and the operator CLI `apps/cli/remote_mcp.py`, and the
  grant-writing repository methods are called only from that CLI;
- disclosure policy: the Knowledge client profiles and discovery profiles are
  immutable mappings of frozensets, and no module rebinds or mutates them
  (classification floors are predicate columns, covered by the registry scan).

A write is an `insert`/`pg_insert`/`update`/`delete` call (or a `.insert()` /
`.update()` / `.delete()` method) whose table is the module-level table or a
local name bound to it, or SQL text naming it.
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


PROFILE_TABLE: Final = "knowledge_discovery_source_profiles"
GRANT_TABLE: Final = "remote_capability_grants"
KNOWLEDGE_PERSISTENCE: Final = "src/my_pa/infrastructure/persistence/knowledge_assertions.py"
PROFILE_CLI: Final = "apps/cli/knowledge_source_profiles.py"
GRANT_CLI: Final = "apps/cli/remote_mcp.py"
GRANT_REPOSITORY: Final = "src/my_pa/infrastructure/persistence/remote_identity.py"
#: The maintenance repository methods that write source scope or evidence policy.
MAINTENANCE_WRITERS: Final = frozenset(
    {
        "apply_source_profile",
        "disable_source_profile",
        "classify_evidence_restricted",
        "record_evidence_availability",
        "drain_availability_revalidation",
        "redact_sealed_checkpoint_requests",
    }
)
GRANT_WRITERS: Final = frozenset({"grant", "clear_grant_expiry"})
_TABLE_WRITES: Final = frozenset({"insert", "pg_insert", "update", "delete"})


def table_writers(source: str, table: str) -> list[str]:
    """`Class.method` (or `function`) qualnames whose body writes `table`."""
    sql = re.compile(
        rf"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|COPY|TRUNCATE(?:\s+TABLE)?)\s+"
        rf"(?:ONLY\s+)?(?:\"?\w+\"?\s*\.\s*)?\"?{table}\b",
        re.IGNORECASE,
    )
    found: list[str] = []

    def visit(node: ast.AST, scope: str, aliases: frozenset[str]) -> None:
        local = set(aliases)
        for child in ast.walk(node):
            if isinstance(child, ast.Assign):
                values = child.value.elts if isinstance(child.value, ast.Tuple) else [child.value]
                targets = [
                    element
                    for target in child.targets
                    for element in (target.elts if isinstance(target, ast.Tuple) else [target])
                ]
                for target, value in zip(targets, values, strict=False):
                    if isinstance(target, ast.Name) and _names_table(value, local, table):
                        local.add(target.id)
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                function = child.func
                name = (
                    function.id
                    if isinstance(function, ast.Name)
                    else function.attr
                    if isinstance(function, ast.Attribute)
                    else None
                )
                if (
                    name in _TABLE_WRITES
                    and child.args
                    and _names_table(child.args[0], local, table)
                ) or (
                    isinstance(function, ast.Attribute)
                    and function.attr in _WRITE_CALLS
                    and _names_table(function.value, local, table)
                ):
                    found.append(scope)
            elif isinstance(child, ast.Constant) and isinstance(child.value, str):
                if sql.search(child.value):
                    found.append(scope)

    tree = ast.parse(source)
    module_aliases = frozenset({table})
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    visit(item, f"{node.name}.{item.name}", module_aliases)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            visit(node, node.name, module_aliases)
        else:
            visit(node, "<module>", module_aliases)
    return sorted(set(found))


def _names_table(node: ast.expr, aliases: set[str] | frozenset[str], table: str) -> bool:
    if isinstance(node, ast.Name):
        return node.id in aliases
    if isinstance(node, ast.Attribute):
        return node.attr == table
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        # `table.alias(...)` / `cast(Table, table.alias(...))` keep the table.
        return node.func.attr == "alias" and _names_table(node.func.value, aliases, table)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "cast":
        return any(_names_table(argument, aliases, table) for argument in node.args[1:])
    return False


def _callers(names: frozenset[str]) -> dict[str, set[str]]:
    """Runtime files that call any method in `names`, by method name."""
    found: dict[str, set[str]] = {}
    for path in _python_files(*RUNTIME_TREES):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in names
            ):
                found.setdefault(node.func.attr, set()).add(path.relative_to(ROOT).as_posix())
    return found


def _writers_everywhere(table: str) -> dict[str, list[str]]:
    return {
        path.relative_to(ROOT).as_posix(): found
        for path in _python_files(*RUNTIME_TREES)
        if (found := table_writers(path.read_text(encoding="utf-8"), table))
    }


def test_the_table_writer_detector_finds_every_shape_it_claims() -> None:
    planted = (
        "class A:\n    def m(self):\n        p = knowledge_discovery_source_profiles\n"
        "        self.c.execute(update(p).values(disabled_at=None))\n",
        "class B:\n    def m(self):\n        e, p = x, knowledge_discovery_source_profiles\n"
        "        pg_insert(p).values()\n",
        "def f():\n    tables.knowledge_discovery_source_profiles.delete()\n",
        "def g():\n    q = cast(Table, knowledge_discovery_source_profiles.alias('x'))\n"
        "    insert(q)\n",
        "def h():\n    SQL = 'UPDATE knowledge.knowledge_discovery_source_profiles SET a = 1'\n",
    )
    for source in planted:
        assert table_writers(source, PROFILE_TABLE), source
    assert table_writers(planted[0], PROFILE_TABLE) == ["A.m"]
    assert not table_writers(
        "class C:\n    def m(self):\n        p = knowledge_discovery_source_profiles\n"
        "        select(p).with_for_update(key_share=True)\n",
        PROFILE_TABLE,
    )


def test_source_scope_is_written_only_by_the_maintenance_body() -> None:
    writers = _writers_everywhere(PROFILE_TABLE)
    assert set(writers) == {KNOWLEDGE_PERSISTENCE}, writers
    assert writers[KNOWLEDGE_PERSISTENCE], "the maintenance body must be seen writing"
    assert {qualname.split(".")[0] for qualname in writers[KNOWLEDGE_PERSISTENCE]} == {
        "_Maintenance"
    }


def test_the_maintenance_writers_are_reached_only_by_the_operator_command() -> None:
    callers = _callers(MAINTENANCE_WRITERS)
    assert callers, "the operator command must be seen calling the maintenance writers"
    assert set().union(*callers.values()) == {PROFILE_CLI}, callers
    command_text = ROOT / "tests/architecture/test_operator_commands_are_not_capabilities.py"
    assert '"knowledge_source_profiles.py":' in command_text.read_text(encoding="utf-8")


def test_authorization_grants_are_written_only_by_their_repository_and_operator_cli() -> None:
    writers = _writers_everywhere(GRANT_TABLE)
    assert GRANT_REPOSITORY in writers, writers
    assert set(writers) <= {GRANT_REPOSITORY, GRANT_CLI}, writers
    callers = _callers(GRANT_WRITERS)
    assert set().union(*callers.values()) == {GRANT_CLI}, callers


def test_the_knowledge_write_bodies_write_no_policy_table() -> None:
    text = (ROOT / KNOWLEDGE_PERSISTENCE).read_text(encoding="utf-8")
    for table in (TABLE, PROFILE_TABLE, GRANT_TABLE):
        for qualname in table_writers(text, table):
            assert qualname.startswith("_Maintenance."), (table, qualname)


def test_the_disclosure_profiles_are_immutable_and_never_rebound() -> None:
    from types import MappingProxyType

    from my_pa.bootstrap import knowledge_discovery_profiles as profiles

    for name in ("DISCOVERY_PROFILES", "KNOWLEDGE_CLIENT_PROFILES"):
        mapping = getattr(profiles, name)
        assert isinstance(mapping, MappingProxyType), name
        assert all(isinstance(value, frozenset) for value in mapping.values()), name
    owner = "src/my_pa/bootstrap/knowledge_discovery_profiles.py"
    rebind = re.compile(
        r"\b(?:DISCOVERY_PROFILES|KNOWLEDGE_CLIENT_PROFILES|DISCOVERY_PROFILE|"
        r"OPERATOR_REVIEW_PROFILE)\s*(?:\[[^\]]*\]\s*)?=(?!=)"
        r"|setattr\(\s*(?:knowledge_discovery_profiles|profiles)\b"
    )
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in _python_files(*RUNTIME_TREES)
        if path.relative_to(ROOT).as_posix() != owner
        and rebind.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
    assert rebind.search("DISCOVERY_PROFILES['x'] = frozenset()")
    assert not rebind.search("if DISCOVERY_PROFILES == other:")


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
