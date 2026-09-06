"""The Constraint read plane stays inside the boundaries WP03 was authorised to occupy.

WP03 adds a canonical backend read plane: a pure domain read-model module, a
stateless application read service, and ten repository methods that answer
questions. It adds no transport, no capability, no schema and no writer. That
sentence is the work package's whole shape, and every clause of it is a boundary
a later change could cross without any test noticing, because crossing it makes
the code *work* — it just makes it work in the wrong layer.

Each rule below is one of those clauses, and each names the defect it forecloses.

* **Dependency direction.** An application service that imports
  `my_pa.infrastructure` gets a concrete repository and a working import. It also
  gets a service that cannot be exercised without a database, an application layer
  that cannot be reasoned about without SQLAlchemy, and a cycle the layering was
  built to prevent. The read service takes its port as a locally declared
  `Protocol` passed per call; that only stays true if nothing imports downward.
* **No transport or capability coupling.** WP03 is deliberately not reachable
  from MCP, the BFF or any gateway yet — that is WP04's work. A read model that
  learned about `Capability` or `Purpose` would bind the canonical projection to
  one caller's authorisation vocabulary, and the next caller would inherit a
  contract shaped for a transport it does not use.
* **Domain purity.** `read_models.py` is the type vocabulary every later package
  reads through. A `sqlalchemy` or `pydantic` import in it would make the product's
  canonical shapes depend on a persistence library's or a validation library's
  release cycle, and would put an ORM object one attribute away from every view.
* **No raw principal in a view.** The partition key is `principal_id`. A view is
  the thing that leaves the backend. A `principal_id` on a view is a partition key
  on the wire — the disclosure this repository partitions to prevent — and it
  would arrive by the most ordinary route there is: copying a persisted record's
  field list into the view that renders it. `PersistedConstraintRecord` is the one
  exemption, and this module requires it to be the *only* one.
* **No Constraint migration, and the Constraint declarations unchanged.** WP03's
  plan states it adds no migration and edits no table declaration (plan §A). A
  read plane that quietly added an index or a column would be a schema change
  delivered under a read package's review. Both rules are scoped to the Constraint
  tables rather than to the repository: an earlier draft froze the whole revision
  set and the whole of `tables.py`, and an unrelated GoodNotes revision landing on
  `main` turned it red — this guard reporting another team's migration as a WP03
  defect. A tripwire that fires on work it does not govern teaches people to
  re-pin it without reading, which is how a guard stops guarding.
* **Sync read boundary.** WP02 shipped the sync tables; WP11 will ship the sync
  behaviour. WP03 reads four of those columns to derive four states and does
  nothing else — no run, no lease, no baseline write, no workbook, no connector.
  The failure mode is not a wrong answer, it is a read package silently becoming
  the sync writer because deriving a state is one short step from recording one.
* **`ConstraintSyncStateView` is bounded.** The frontend recognises ten sync state
  names; only four are derivable from persisted rows without WP11's behaviour
  (plan, "Sync read boundary"). Emitting a fifth would mean inventing a value to
  satisfy a fixture — a backend claiming knowledge it does not have. The enum is
  required to hold exactly the four, so the deferred six cannot be added quietly.

**How these are measured.** Everything about source shape is read with `ast`, so a
comment, a docstring or a line continuation changes nothing about what is seen —
and the vocabulary rules deliberately ignore docstrings, because these modules
*explain* in prose the very things they must not *do* in code, and a text grep
would report those explanations as violations. The one digest taken against the
base tree is stated as a recorded constant: CI clones at `fetch-depth: 1`, so the
base commit is not an object the runner holds, and reading it back through `git
show` fails the run rather than proving anything. Skipping when the object is
absent would be worse — a guard that passes because it could not look is not a
guard — so the value is measured once and written down, where changing it is a
reviewable edit to the very file whose job is to notice the change.

Nothing here opens a connection, reaches a database, imports `alembic`, or
executes a statement.
"""

from __future__ import annotations

import ast
import hashlib
import re
import sys
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]

#: The commit this work package branched from. Named so the failure messages can
#: say what the pins below were measured against; nothing here reads it back out
#: of the object store.
BASE_COMMIT: Final = "a222ce0f04f7bed8bec33b38338c87a6733034d4"

APPLICATION_MODULE: Final = ROOT / "src" / "my_pa" / "application" / "constraints.py"
READ_MODELS_MODULE: Final = (
    ROOT / "src" / "my_pa" / "domain" / "project_controls" / "read_models.py"
)
PERSISTENCE_MODULE: Final = (
    ROOT / "src" / "my_pa" / "infrastructure" / "persistence" / "constraints.py"
)
TABLES_MODULE: Final = ROOT / "src" / "my_pa" / "infrastructure" / "persistence" / "tables.py"
MIGRATIONS: Final = ROOT / "migrations" / "versions"

#: The revision that installed the Constraint tables. WP03 queries what it built
#: and adds nothing beside it, so it is the one revision permitted to name a
#: Constraint table and the one that must stay on the path to head.
WP02_CONSTRAINT_REVISION: Final = "2774329487be"

#: The fourteen tables WP02 installed. Named here rather than derived from
#: `tables.py`, so that deleting a declaration cannot quietly shrink the set this
#: module claims to cover.
CONSTRAINT_TABLES: Final = frozenset(
    {
        "constraint_categories",
        "constraint_category_history",
        "constraint_project_settings",
        "constraint_sync_baselines",
        "constraint_sync_conflicts",
        "constraint_sync_runs",
        "constraint_sync_targets",
        "project_constraint_evidence_links",
        "project_constraint_history",
        "project_constraint_parties",
        "project_constraint_relationships",
        "project_constraint_revision_parties",
        "project_constraint_revisions",
        "project_constraints",
    }
)

#: The digest of those fourteen declarations on the base tree, built exactly the
#: way the guard rebuilds it. Pinned rather than read back through git: CI checks
#: out at `actions/checkout`'s default `fetch-depth: 1` and the workflow sets no
#: depth, so the base commit is not an object the runner has. A guard that asked
#: for it would error there, and one that skipped when it was missing would pass
#: without looking.
BASE_CONSTRAINT_TABLES_SHA256: Final = (
    "f05660848766e21ae5bb11a6e134ff0fc464c15974d4413aa8cb64a11ecaed0a"
)

#: Package roots the application read service may never reach. `infrastructure`
#: is the layering rule; the rest are the transport and authorisation edges WP04
#: owns and WP03 is not permitted to anticipate.
FORBIDDEN_ROOTS: Final = frozenset({"infrastructure", "adapters", "bootstrap"})

#: Module-path segments that name a transport, gateway or capability plane.
#: Matched against every dotted import path, so `my_pa.mcp.tools` and
#: `my_pa.application.capabilities` are both caught wherever they live.
TRANSPORT_SEGMENTS: Final = frozenset({"mcp", "bff", "gateway", "capabilities", "capability"})

#: Authorisation vocabulary that must not appear in the read plane at all.
AUTHORISATION_NAMES: Final = frozenset({"Capability", "Purpose"})

#: The WP02 sync tables. WP03 reads two of them and writes none.
SYNC_TABLES: Final = frozenset(
    {
        "constraint_sync_targets",
        "constraint_sync_runs",
        "constraint_sync_baselines",
        "constraint_sync_conflicts",
    }
)

#: The statement builders that change a row. `select` is absent on purpose:
#: reading these tables is exactly what WP03 is for.
WRITE_BUILDERS: Final = frozenset({"insert", "update", "delete"})

#: WP11's machinery, named as words. Applied to identifiers and to live string
#: literals only — never to docstrings, which discuss these words precisely
#: because the code must not use them.
DEFERRED_MACHINERY: Final = re.compile(
    r"\b(lease|leases|workbook|workbooks|microsoft|msgraph|connector|connectors)\b",
    re.IGNORECASE,
)

#: The `my_pa` layer `read_models.py` may import. Everything else it imports must
#: be the standard library.
DOMAIN_PREFIX: Final = "my_pa.domain"

#: Dataclass name suffixes that mark a type as something the backend hands out.
VIEW_SUFFIXES: Final = ("View", "Entry", "Overview", "Page")

#: The one type in `read_models.py` allowed to carry the partition key. It is an
#: internal repository-to-service record — a faithful picture of a persisted row,
#: hydrated by the repository and consumed by the read service — and it never
#: leaves the backend. The test below requires it to be the ONLY exemption.
PRINCIPAL_BEARING_EXEMPTION: Final = "PersistedConstraintRecord"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_paths(tree: ast.Module) -> set[str]:
    """Every dotted module path this module imports, in all three import forms.

    `import a.b`, `from a.b import c` and `from a import b` are collected as
    `a.b`, `a.b` and `a.b` respectively — the last one by joining the module to
    each imported name, which is what catches `from my_pa import infrastructure`.
    Relative imports are resolved against the module's own package.
    """
    paths: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            paths.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                # No relative import exists in these modules today; resolving it
                # to an unmistakable sentinel keeps a future one visible rather
                # than silently exempt.
                module = f"<relative:{node.level}>{module}"
            if module:
                paths.add(module)
            paths.update(f"{module}.{alias.name}" if module else alias.name for alias in node.names)
    return paths


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """Identity of every docstring expression in the module.

    These modules explain the boundaries they must not cross, so their prose
    names `workbook`, `connector` and `principal_id` freely. Prose is not code.
    """
    marked: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            marked.add(id(body[0].value))
    return marked


def _code_words(tree: ast.Module) -> set[str]:
    """Every name and live string literal in the module. Docstrings excluded.

    This is the vocabulary the module actually executes: identifiers it binds or
    reads, attributes it reaches for, arguments it declares, and the string
    literals it hands to SQLAlchemy or compares against.
    """
    docstrings = _docstring_nodes(tree)
    words: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            words.add(node.id)
        elif isinstance(node, ast.Attribute):
            words.add(node.attr)
        elif isinstance(node, ast.arg) or (isinstance(node, ast.keyword) and node.arg):
            words.add(node.arg)  # type: ignore[arg-type]
        elif isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            words.add(node.name)
        elif isinstance(node, ast.alias):
            words.add(node.asname or node.name)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            words.add(node.value)
    return words


def _statements_against(tree: ast.Module, tables: frozenset[str]) -> dict[str, set[str]]:
    """Statement builders this module composes against each named table.

    Both SQLAlchemy call shapes are read — `table.update()` and `update(table)` —
    because a guard that knew one of them is a guard evaded by preferring the
    other, and nobody would evade it on purpose.
    """
    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Attribute) and (name := _named_table(function.value)) in tables:
            found.setdefault(str(name), set()).add(function.attr)
        elif isinstance(function, ast.Name):
            for argument in node.args:
                if (name := _named_table(argument)) in tables:
                    found.setdefault(str(name), set()).add(function.id)
    return found


def _named_table(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _dataclass_fields(tree: ast.Module) -> dict[str, list[str]]:
    """Annotated class-body fields, by class name.

    Annotated assignments in a class body are exactly what `@dataclass` turns
    into fields, so this is the field list without importing the module.
    """
    return {
        node.name: [
            statement.target.id
            for statement in node.body
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
        ]
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }


def _revision_parents(value: ast.expr | None) -> tuple[str, ...]:
    """The revisions a `down_revision` names.

    Three shapes exist in this tree and all three are read: a single string, the
    literal `None` at the base of a lineage, and a tuple at a merge point — this
    repository has merged two heads more than once, and a walk that saw only the
    string form would report every merged-in lineage tip as a live head.
    """
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return (value.value,)
    if isinstance(value, ast.Tuple | ast.List):
        return tuple(
            element.value
            for element in value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        )
    return ()


def _code_strings(tree: ast.Module) -> set[str]:
    """Every live string literal in the module, docstrings excluded.

    A migration names its tables as strings — `op.create_table("…")`,
    `sa.Column`'s foreign-key targets, raw DDL text — so string literals are
    where a revision's subject shows. Docstrings are excluded for the reason they
    are excluded everywhere in this module: a revision that *mentions* the
    Constraint tables in prose while touching none of them is not a violation.
    """
    docstrings = _docstring_nodes(tree)
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }


def _declared_revision(path: Path) -> str | None:
    """The `revision` a migration file declares, or `None` if it declares none."""
    for statement in _tree(path).body:
        target: ast.expr | None = None
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            target = statement.target
        elif (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            target = statement.targets[0]
        if target is not None and target.id == "revision":
            value = statement.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
    return None


def _constraint_table_declarations(path: Path) -> dict[str, str]:
    """The source of each `<name> = Table(...)` whose name is a Constraint table.

    Sliced from the module rather than digesting the whole file, so an unrelated
    plane's table can change without implicating this work package.
    """
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    declarations: dict[str, str] = {}
    for node in ast.parse(source).body:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        if getattr(node.value.func, "id", None) != "Table":
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if name in CONSTRAINT_TABLES and node.end_lineno is not None:
            declarations[name] = "".join(lines[node.lineno - 1 : node.end_lineno])
    return declarations


def _revision_graph(directory: Path) -> dict[str, tuple[str, ...]]:
    """Each migration's `revision` and the revisions it descends from, read from source.

    Read with `ast` rather than by importing `alembic` or opening a database:
    the head is a property of the committed files, and asking a live environment
    for it would make this test depend on a configured database it has no reason
    to need.
    """
    graph: dict[str, tuple[str, ...]] = {}
    for path in sorted(directory.glob("*.py")):
        assigned: dict[str, ast.expr | None] = {}
        for statement in _tree(path).body:
            target: ast.expr | None = None
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                target = statement.target
            elif (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
            ):
                target = statement.targets[0]
            if target is None or target.id not in {"revision", "down_revision"}:
                continue
            assigned[target.id] = statement.value
        revision = _revision_parents(assigned.get("revision"))
        assert len(revision) == 1, f"{path.name} declares no single string `revision`"
        assert revision[0] not in graph, f"{revision[0]} is declared by two migrations"
        graph[revision[0]] = _revision_parents(assigned.get("down_revision"))
    return graph


def test_the_detectors_report_the_violations_they_claim_to_find() -> None:
    """The control that makes every zero below a measurement.

    A synthetic module holding one of each forbidden shape, run through the same
    functions that read the real tree. If this reddens, the emptiness reported by
    the tests below says nothing about the tree.
    """
    planted = _tree_from_source(
        '"""A docstring naming a workbook, a connector and principal_id."""\n'
        "import my_pa.infrastructure.persistence.constraints\n"
        "from my_pa import infrastructure\n"
        "from my_pa.adapters.mcp.tools import register\n"
        "import sqlalchemy\n"
        "from sqlalchemy import update\n"
        "def writer(connection):\n"
        "    connection.execute(constraint_sync_runs.insert().values(state='started'))\n"
        "    connection.execute(update(constraint_sync_baselines))\n"
        "    lease = acquire_workbook_lease(Capability.READ)\n"
        "    return lease\n"
        "class ThingView:\n"
        "    principal_id: str\n"
    )
    imports = _imported_paths(planted)
    assert "my_pa.infrastructure.persistence.constraints" in imports
    assert "my_pa.infrastructure" in imports
    assert "sqlalchemy" in imports
    assert any("mcp" in path.split(".") for path in imports)

    statements = _statements_against(planted, SYNC_TABLES)
    assert statements["constraint_sync_runs"] & WRITE_BUILDERS == {"insert"}
    assert statements["constraint_sync_baselines"] & WRITE_BUILDERS == {"update"}

    words = _code_words(planted)
    assert "Capability" in words
    assert {word for word in words if DEFERRED_MACHINERY.search(word)} != set()
    # And the docstring's own `workbook`/`connector` is not among them.
    assert not any(word.startswith("A docstring") for word in words)

    assert _dataclass_fields(planted)["ThingView"] == ["principal_id"]


def _tree_from_source(source: str) -> ast.Module:
    return ast.parse(source)


def test_the_read_plane_modules_all_exist_and_were_parsed() -> None:
    """The universe, stated. A rule read out of a missing file is not a rule."""
    for path in (APPLICATION_MODULE, READ_MODELS_MODULE, PERSISTENCE_MODULE, TABLES_MODULE):
        assert path.is_file(), f"{path.relative_to(ROOT)} does not exist"
        assert _tree(path).body, f"{path.relative_to(ROOT)} is empty"


def test_the_application_read_service_imports_nothing_from_infrastructure() -> None:
    """`application -> domain` only: the service is exercised without a database.

    Every import form is checked, including `from my_pa import infrastructure`,
    which binds the package without ever spelling a dotted path.
    """
    offending = sorted(
        path
        for path in _imported_paths(_tree(APPLICATION_MODULE))
        if path == "my_pa.infrastructure" or path.startswith("my_pa.infrastructure.")
    )
    assert offending == [], (
        f"{APPLICATION_MODULE.relative_to(ROOT)} imports infrastructure: {offending}. "
        "The read service takes its repository as the locally declared "
        "`ConstraintReadRepository` Protocol, passed per call; the concrete "
        "SqlConstraintManagementRepository satisfies it structurally at the "
        "composition edge. Delete the import and widen the Protocol instead"
    )


def test_the_read_plane_reaches_no_transport_gateway_or_capability_module() -> None:
    """WP03 is a read plane, not an edge: WP04 owns everything that exposes it.

    Both the application service and the domain read models are checked, because
    a canonical read model that learned a transport's vocabulary would export it
    to every later caller.
    """
    offending: dict[str, list[str]] = {}
    for module in (APPLICATION_MODULE, READ_MODELS_MODULE):
        reached = sorted(
            path
            for path in _imported_paths(_tree(module))
            if set(path.split(".")) & (FORBIDDEN_ROOTS | TRANSPORT_SEGMENTS)
        )
        if reached:
            offending[module.relative_to(ROOT).as_posix()] = reached
    assert offending == {}, (
        f"the read plane imports a transport, gateway or capability module: {offending}. "
        "Exposing these reads over MCP or the BFF is WP04's work and belongs in "
        "WP04's modules; the read plane must stay callable without any of them"
    )


def test_the_read_plane_names_no_capability_or_purpose_enum() -> None:
    """Authorisation vocabulary belongs to the caller, not to the projection.

    A read model that named `Capability` or `Purpose` would shape the canonical
    Constraint contract around one transport's authorisation model, and every
    later caller would inherit it whether or not it applies.
    """
    offending = {
        module.relative_to(ROOT).as_posix(): sorted(
            AUTHORISATION_NAMES & _code_words(_tree(module))
        )
        for module in (APPLICATION_MODULE, READ_MODELS_MODULE)
        if AUTHORISATION_NAMES & _code_words(_tree(module))
    }
    assert offending == {}, (
        f"the read plane names an authorisation enum: {offending}. The trusted "
        "`principal_id` arrives as an explicit keyword argument resolved at the "
        "edge; the read plane neither checks nor names a capability"
    )


def test_the_domain_read_models_import_only_the_standard_library_and_the_domain() -> None:
    """`read_models.py` is the product's canonical shape vocabulary; it depends on nothing.

    A `sqlalchemy` import here would put a persistence library in the domain and
    an ORM object one attribute away from every view; a `pydantic` one would bind
    the canonical shapes to a validation library's release cycle.
    """
    offending = sorted(
        path
        for path in _imported_paths(_tree(READ_MODELS_MODULE))
        if not (path == DOMAIN_PREFIX or path.startswith(f"{DOMAIN_PREFIX}."))
        and path.split(".")[0] not in sys.stdlib_module_names
    )
    assert offending == [], (
        f"{READ_MODELS_MODULE.relative_to(ROOT)} imports outside the standard library "
        f"and {DOMAIN_PREFIX}: {offending}. These read models are frozen slotted "
        "dataclasses over stdlib types by design — move whatever needs the "
        "dependency into the layer that already has it"
    )


def test_no_read_view_carries_the_partition_key() -> None:
    """The partition key never becomes a field on something the backend hands out.

    Checked by field name rather than by type, and by substring rather than by
    exact match, so `principal_id`, `principal`, `owner_principal_id` and
    `principal_ids` are all caught. `PersistedConstraintRecord` is exempt: it is
    the repository-to-service picture of a persisted row, not a view, and it
    never leaves the backend. That exemption is required below to be the only one.
    """
    fields = _dataclass_fields(_tree(READ_MODELS_MODULE))
    offending = {
        name: sorted(field for field in declared if "principal" in field.lower())
        for name, declared in fields.items()
        if name.endswith(VIEW_SUFFIXES) and any("principal" in field.lower() for field in declared)
    }
    assert offending == {}, (
        f"a read view declares a principal-shaped field: {offending}. `principal_id` "
        "is the partition key: it is how a row is found, never part of what the row "
        "says. Drop the field; the caller already knows which Principal it asked as"
    )


def test_the_persisted_record_is_the_only_type_permitted_to_carry_a_principal() -> None:
    """The exemption is stated once and is required to stay a single exemption.

    Without this, the rule above would be satisfied by any future leaking type
    that simply avoided the four view suffixes.
    """
    fields = _dataclass_fields(_tree(READ_MODELS_MODULE))
    carriers = sorted(
        name
        for name, declared in fields.items()
        if any("principal" in field.lower() for field in declared)
    )
    assert carriers == [PRINCIPAL_BEARING_EXEMPTION], (
        f"types in {READ_MODELS_MODULE.name} carrying a principal-shaped field: "
        f"{carriers}; exactly [{PRINCIPAL_BEARING_EXEMPTION!r}] is permitted. If a new "
        "internal record genuinely needs the partition key, add it here deliberately "
        "with the reason — and never to a type that is projected to a caller"
    )


def test_the_sync_state_view_holds_only_the_four_derivable_states() -> None:
    """Four of the frontend's ten sync names are derivable from persisted rows; six are not.

    `EXTERNAL_IMPORT_PENDING`, `WORKBOOK_UNAVAILABLE`, `SCHEMA_UNSUPPORTED`,
    `PARTIAL`, `VERIFICATION_PENDING` and `VERIFICATION_FAILED` each need a
    connector call, a workbook read or a live run comparison — WP11's behaviour.
    Adding one here would mean emitting a state the backend cannot substantiate,
    to satisfy a fixture.
    """
    declarations = [
        node
        for node in _tree(READ_MODELS_MODULE).body
        if isinstance(node, ast.ClassDef) and node.name == "ConstraintSyncStateView"
    ]
    assert len(declarations) == 1, "ConstraintSyncStateView is not declared exactly once"
    members = {
        statement.targets[0].id
        for statement in declarations[0].body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
    }
    assert members == {"NEVER_SYNCED", "IN_SYNC", "DB_EXPORT_PENDING", "CONFLICT"}, (
        f"ConstraintSyncStateView holds {sorted(members)}. Exactly the four states "
        "derivable from persisted rows are permitted; the remaining six frontend "
        "names are deferred to WP11 and must not be emitted before the behaviour "
        "that substantiates them exists"
    )


def test_the_read_plane_writes_nothing_to_the_sync_tables() -> None:
    """WP02 shipped the sync tables; WP11 ships the sync behaviour. WP03 only reads.

    Deriving a sync state is one short step from recording one, and that step is
    where a read package quietly becomes the sync writer.
    """
    offending: dict[str, dict[str, list[str]]] = {}
    for module in (APPLICATION_MODULE, PERSISTENCE_MODULE):
        statements = _statements_against(_tree(module), SYNC_TABLES)
        writes = {
            table: sorted(builders & WRITE_BUILDERS)
            for table, builders in statements.items()
            if builders & WRITE_BUILDERS
        }
        if writes:
            offending[module.relative_to(ROOT).as_posix()] = writes
    assert offending == {}, (
        f"the read plane writes to a sync table: {offending}. WP03 starts no run, "
        "acquires no lease, writes no baseline and resolves no conflict — it reads "
        "`constraint_sync_targets` and `constraint_sync_conflicts` and derives a "
        "state. The writer belongs in WP11"
    )


def test_the_read_plane_names_no_lease_workbook_or_external_connector() -> None:
    """The deferred machinery is absent from the code, not merely unused.

    Measured over identifiers and live string literals only. These modules discuss
    workbooks and connectors at length in their docstrings — explaining exactly
    why they do not touch them — and prose is not behaviour.
    """
    offending = {}
    for module in (APPLICATION_MODULE, PERSISTENCE_MODULE, READ_MODELS_MODULE):
        named = sorted(
            word for word in _code_words(_tree(module)) if DEFERRED_MACHINERY.search(word)
        )
        if named:
            offending[module.relative_to(ROOT).as_posix()] = named
    assert offending == {}, (
        f"the read plane names WP11's machinery in code: {offending}. A lease, a "
        "workbook and a Microsoft Graph connector are all things WP03 proved it "
        "does not need in order to derive four sync states from persisted rows"
    )


def test_no_revision_but_wp02_s_touches_a_constraint_table() -> None:
    """WP03 ships no Constraint migration.

    Stated as what WP03 actually promised rather than as a frozen snapshot of
    `migrations/versions/`. An earlier draft of this guard pinned the revision
    count and a digest of the filenames, and an unrelated GoodNotes revision
    landing on `main` turned it red — a guard named for this work package
    reporting another team's migration as a WP03 defect. A tripwire that fires on
    work it does not govern trains people to re-pin it without reading, which is
    how a guard stops guarding.

    So the question asked here is the narrow one: does any revision other than
    WP02's own perform DDL that names a Constraint table? Unrelated migrations
    are invisible to it, and a WP03 migration could not be.

    **What this does not cover, stated plainly.** WP03's promise is the wider
    "adds no migration", and a revision touching only non-Constraint tables would
    pass here. Closing that half needs a diff against the merge base, which is
    precisely what CI's depth-1 clone cannot supply — the constraint that forced
    this rewrite in the first place. It is therefore a review-time fact rather
    than a CI-time invariant: `git diff origin/main..HEAD -- migrations/` is
    empty on this branch, and a reviewer can confirm it in one command. A guard
    that faked the check by re-freezing the revision set would be the tripwire
    this rewrite removed.
    """
    offenders: dict[str, list[str]] = {}
    for path in sorted(MIGRATIONS.glob("*.py")):
        revision = _declared_revision(path)
        if revision == WP02_CONSTRAINT_REVISION:
            continue
        named = sorted(
            {table for table in CONSTRAINT_TABLES if table in _code_strings(_tree(path))}
        )
        if named:
            offenders[path.name] = named
    assert offenders == {}, (
        f"revisions outside WP02's {WP02_CONSTRAINT_REVISION} name Constraint "
        f"tables: {offenders}. WP03 is a read plane over the schema WP02 already "
        "installed. If an index or a column is genuinely needed, it is a schema "
        "change and belongs in its own reviewed migration, not in a read package"
    )
    assert any(
        _declared_revision(path) == WP02_CONSTRAINT_REVISION for path in MIGRATIONS.glob("*.py")
    ), (
        f"WP02's revision {WP02_CONSTRAINT_REVISION} is not in "
        "migrations/versions/, so the loop above skipped nothing and proved nothing"
    )


def test_the_migration_graph_has_exactly_one_head_descending_from_wp02() -> None:
    """One head, and WP02's Constraint revision is still on the way to it.

    Derived from the `revision`/`down_revision` graph over the committed files —
    rather than by importing alembic or asking a database — so it is a fact about
    the repository rather than about an environment.

    Two claims, and neither pins a head *value*: a pinned value would go stale on
    the next unrelated migration, for the same reason the guard above no longer
    pins a filename set. What matters is that `alembic upgrade head` stays
    unambiguous, and that nobody rewrote or orphaned the revision that installed
    the Constraint tables underneath this read plane.
    """
    graph = _revision_graph(MIGRATIONS)
    assert len(graph) > 50, f"the revision walk found only {len(graph)} migrations"
    descended = {parent for parents in graph.values() for parent in parents}
    unknown = sorted(descended - set(graph))
    assert unknown == [], f"a migration descends from revisions no file declares: {unknown}"
    heads = sorted(revision for revision in graph if revision not in descended)
    assert len(heads) == 1, (
        f"the migration graph has heads {heads}; exactly one is expected. More "
        "than one means two revisions branched from the same parent and "
        "`alembic upgrade head` is ambiguous"
    )
    ancestors: set[str] = set()
    frontier = [heads[0]]
    while frontier:
        revision = frontier.pop()
        for parent in graph.get(revision, ()):
            if parent not in ancestors:
                ancestors.add(parent)
                frontier.append(parent)
    assert WP02_CONSTRAINT_REVISION in ancestors, (
        f"WP02's revision {WP02_CONSTRAINT_REVISION} is not an ancestor of the "
        f"single head {heads[0]}. The Constraint tables this read plane queries "
        "are installed by that revision; if it is no longer on the path to head, "
        "either it was rewritten or the head is on a branch that never applied it"
    )


def test_the_constraint_table_declarations_are_unchanged() -> None:
    """WP03 edits no Constraint table: no column, no index, no constraint.

    Digested over the fourteen Constraint `Table(...)` declarations only, not over
    the whole of `tables.py`. The file is twelve thousand lines shared by every
    plane in the repository, so a whole-file digest would redden on any unrelated
    table's change — the same false-positive shape the revision guard above was
    rewritten to shed. Slicing to the declarations WP03 actually claims not to
    have touched keeps the assertion narrow and true.

    Pinned rather than read back through git: CI clones at `fetch-depth: 1` and
    the workflow sets no depth, so the base commit is not an object the runner
    holds. Asking git for it fails the run; skipping when it is absent would be
    worse still, because a guard that passes because it could not look is not a
    guard. A digest written down can only go stale through an edit to this line,
    which is a reviewable diff in the file whose job is to notice that edit.
    """
    declarations = _constraint_table_declarations(TABLES_MODULE)
    missing = sorted(CONSTRAINT_TABLES - set(declarations))
    assert missing == [], (
        f"tables.py declares no Table for {missing}, so the digest below would "
        "describe a smaller set than this guard claims to cover"
    )
    digest = hashlib.sha256()
    for name in sorted(declarations):
        digest.update(name.encode("utf-8"))
        digest.update(declarations[name].encode("utf-8"))
    assert digest.hexdigest() == BASE_CONSTRAINT_TABLES_SHA256, (
        "the Constraint table declarations in "
        "src/my_pa/infrastructure/persistence/tables.py differ from the base "
        f"tree (base {BASE_CONSTRAINT_TABLES_SHA256[:16]}, now "
        f"{digest.hexdigest()[:16]}). A read plane needs no schema change: WP03 "
        "adds no migration and edits no declaration. If an index is genuinely "
        "needed, it is a schema change and belongs in its own reviewed migration"
    )
