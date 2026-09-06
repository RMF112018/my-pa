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
* **No new migration, and `tables.py` unchanged.** WP03's plan states it moves no
  Alembic head and edits no table declaration (plan §A). A read plane that quietly
  added an index or a column would be a schema change delivered under a read
  package's review, and the head it moved would collide with whatever WP04 writes
  next. Both are pinned against the base commit rather than described.
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
would report those explanations as violations. The two pins against the base
commit are read with `git show`, not from a recorded constant, so they cannot go
stale silently.

Nothing here opens a connection, reaches a database, imports `alembic`, or
executes a statement.
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]

#: The commit this work package branched from. The schema pins below are stated
#: against it rather than against a hash typed into this file, so they keep
#: meaning after any commit that does not touch the pinned paths.
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

#: The single Alembic head at `BASE_COMMIT`, which WP03 does not move.
EXPECTED_HEAD: Final = "2774329487be"

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


def _git_show(path: str) -> bytes:
    """The bytes of one path at `BASE_COMMIT`, read from the object store."""
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:{path}"],  # noqa: S607
        capture_output=True,
        check=True,
    ).stdout


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


def test_wp03_adds_no_migration_file() -> None:
    """The set of revisions is exactly the base commit's set.

    Stated as set equality in both directions: an added revision reddens, and so
    does a deleted one, because a read package that removed a migration would be
    a far stranger event than one that added it.
    """
    at_base = {
        line.strip()
        for line in subprocess.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-C",
                str(ROOT),
                "ls-tree",
                "--name-only",
                f"{BASE_COMMIT}:migrations/versions",
            ],
            capture_output=True,
            check=True,
            text=True,
        ).stdout.splitlines()
        if line.strip().endswith(".py")
    }
    assert at_base, "no revision files were found at the base commit"
    now = {path.name for path in MIGRATIONS.glob("*.py")}
    assert now == at_base, (
        f"migrations/versions/ changed: added {sorted(now - at_base)}, removed "
        f"{sorted(at_base - now)}. WP03 is a read plane over the schema WP02 "
        "already installed; it adds no revision and moves no head"
    )


def test_the_alembic_head_is_still_the_single_revision_wp02_left() -> None:
    """One head, and it is the one the plan pinned.

    Derived from the `revision`/`down_revision` graph over the committed files —
    the node no other revision descends from — rather than by importing alembic
    or asking a database, so it is a fact about the repository rather than about
    an environment.
    """
    graph = _revision_graph(MIGRATIONS)
    assert len(graph) > 50, f"the revision walk found only {len(graph)} migrations"
    descended = {parent for parents in graph.values() for parent in parents}
    unknown = sorted(descended - set(graph))
    assert unknown == [], f"a migration descends from revisions no file declares: {unknown}"
    heads = sorted(revision for revision in graph if revision not in descended)
    assert heads == [EXPECTED_HEAD], (
        f"the migration graph has heads {heads}; exactly [{EXPECTED_HEAD!r}] is "
        "expected. More than one head means two revisions branched from the same "
        "parent and `alembic upgrade head` is ambiguous; a different single head "
        "means a revision was added after the base commit"
    )


def test_the_table_declarations_are_byte_identical_to_the_base_commit() -> None:
    """WP03 edits no table declaration: no column, no index, no constraint.

    Compared by digest against `git show` at the base commit rather than against a
    hash typed into this file, so the pin cannot quietly describe a stale
    expectation, and the failure message can say what to do about it.
    """
    path = "src/my_pa/infrastructure/persistence/tables.py"
    at_base = hashlib.sha256(_git_show(path)).hexdigest()
    now = hashlib.sha256(TABLES_MODULE.read_bytes()).hexdigest()
    assert now == at_base, (
        f"{path} differs from {BASE_COMMIT[:12]} (base {at_base[:16]}, now "
        f"{now[:16]}). A read plane needs no schema change: WP03's plan states it "
        "adds no migration and edits no declaration. If an index is genuinely "
        "needed, it is a schema change and belongs in its own reviewed migration"
    )
