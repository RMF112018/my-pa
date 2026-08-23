"""Which capabilities can reach a relationship-memory row, derived rather than listed.

`evidence/acceptance/RELATIONSHIP-MEMORY-RM-AC-20260822.md`'s `RM-API-AC-002`
carries the criterion "each capability has a grant boundary appropriate to the
rows it reaches". A grant boundary is only appropriate to a reach someone has
measured, and that row got the reach wrong twice in a row, in prose, at two
successive heads.

The first version named the eight `relationship_memory.*` capabilities and
stopped, so `entities.context` — which puts every carried memory's `statement`
verbatim on a card served under `entity_read` — was disclosed by nothing. The
correction added `entities.context` and `review.decide` and then asserted that
"the enumeration of capabilities outside the eight is complete at two". It is
three: `review.list` reads `relationship_memory_proposals` and correlates two
subqueries over `relationship_memory_review_decisions`, so a `capture_review`
grant learns a `subject_entity_id`, a `proposed_kind` and — after promotion — an
`accepted_memory_id`, for a subject the grant never named. The same correction
also said of `review.decide` that "it reads no memory row" while it reads four
of the eight tables, and left `relationship_memory_evidence_links` off
`_promote`'s write list.

Three false enumerations, one criterion, zero tests. **So the enumeration is not
prose here.** This module derives the answer from the source and compares it to
a declaration, and the acceptance row cites it by name rather than asserting the
same thing a fourth time. The declared set is a literal because a declaration is
the thing under review; everything it is measured against is derived.

Five claims, separated because they fail for different reasons:

1. **The eight tables are the schema's, not this file's.** They are read off the
   `Table` objects in `infrastructure.persistence.tables`, and the count is
   asserted, so a ninth memory table cannot join the plane without being seen.
2. **Only the declared modules issue SQL against them.** Exact set equality, so
   a third module that starts building a statement over a memory table has to be
   argued about here. This is the claim that keeps the walk below cheap: the
   whole memory-touching surface of `src/` is two files.
3. **The capability set is derived by a reachability walk and matches the
   declaration.** Exact set equality over `Capability` members, so a capability
   that starts reaching a memory row either updates the declaration or reddens.
4. **Every capability beyond the eight carries a written reason.** The eight are
   derived off the enum's own `relationship_memory.` prefix; the residue is the
   part `RM-API-AC-002` has to disclose, and each entry says what it discloses
   and under which purpose.
5. **The walk has no blind spot on the names that matter.** The walk types call
   receivers from annotations, and an untyped receiver is a place a reach could
   hide. So every call in a module holding a port reference whose method name is
   one of the port methods that reach memory must resolve to a type. Zero do not
   today; a first one reddens rather than silently narrowing claim 3.

**Why a walk and not a grep.** The reach is four hops long and no hop is
spelled: `ApplicationService._entities_context` constructs an
`EntityContextService`, whose `_memory_summary` calls `summaries_for_context` on
a `RelationshipMemoryRepository` it holds as `self._memories`, which
`SqlRelationshipMemoryRepository` implements over `relationship_memories` and
`relationship_memory_versions`. Nothing on that path contains both a capability
name and a table name, which is exactly why three hand-written enumerations in a
row missed a hop.

**How receivers are typed.** A parameter's annotation, a `self` in a method
body, a `self._x` assigned in `__init__` from an annotated parameter, a local
assigned from a constructor call, and a property's return annotation. Where the
receiver types to an abstract port, every implementation of that port is
followed — which is how `unit_of_work.reviews.cases(...)` reaches `_Reviews`.
This over-approximates towards *more* reach, never less, and claim 5 is what
says the approximation is not silently going the other way.

Nothing here opens a connection, reaches a source, or touches a database. It
parses the source tree and imports the table declarations for their names.
"""

from __future__ import annotations

import ast
import collections
from functools import cache
from pathlib import Path
from typing import Final

from sqlalchemy import Table

from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.infrastructure.persistence import tables as declarations

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"

#: Where the table declarations live, and the one module excluded from the
#: "issues SQL against a memory table" census below: declaring a table is not
#: querying one.
DECLARATIONS: Final = PACKAGE / "infrastructure" / "persistence" / "tables.py"

#: Where the port protocols live. Claim 5 scopes its blind-spot sweep to the
#: modules that import from here, because a module that holds no port reference
#: cannot be calling a repository through one.
PORTS: Final = PACKAGE / "contracts" / "ports.py"

#: The application registry that says what a capability executes. Read as source
#: rather than imported, so a capability wired to a handler is visible here even
#: if importing the service in this tier were ever to become expensive.
SERVICE: Final = PACKAGE / "application" / "service.py"

#: The prefix the memory plane's table names share. Stops one letter short of
#: `relationship_memory_` on purpose, because `relationship_memories` is one of
#: the eight. It is a *selector* and not a list: the names, the count and the
#: membership all come from the `Table` objects it selects.
TABLE_PREFIX: Final = "relationship_memor"

#: The prefix the plane's own capability values share, used to split the derived
#: set into "the eight" and the residue that has to carry a reason. Matched
#: against `Capability` rather than against a hand-written list of the plane's
#: members, so a further `relationship_memory.*` capability is counted as one of
#: the plane's own rather than surfacing as an undocumented exception.
CAPABILITY_PREFIX: Final = "relationship_memory."

#: The modules that build a statement over one of the eight. Exact, so a third
#: joining the plane is argued about here rather than merged quietly — and the
#: two-file answer is what lets claim 3 walk callers instead of grepping.
MEMORY_SQL_MODULES: Final = frozenset(
    {
        "infrastructure/persistence/relationship_memory.py",
        "infrastructure/persistence/relationship_memory_review.py",
    }
)

#: Every capability whose handler can read or write one of the eight memory
#: tables. Compared for exact equality against the walk, so this is the sentence
#: `RM-API-AC-002` cites and the walk is what makes it checkable.
DECLARED: Final = frozenset(
    {
        Capability.RELATIONSHIP_MEMORY_CREATE,
        Capability.RELATIONSHIP_MEMORY_REVISE,
        Capability.RELATIONSHIP_MEMORY_ARCHIVE,
        Capability.RELATIONSHIP_MEMORY_RESTORE,
        Capability.RELATIONSHIP_MEMORY_GET,
        Capability.RELATIONSHIP_MEMORY_LIST,
        Capability.RELATIONSHIP_MEMORY_SEARCH,
        Capability.RELATIONSHIP_MEMORY_HISTORY,
        Capability.ENTITIES_CONTEXT,
        Capability.REVIEW_LIST,
        Capability.REVIEW_DECIDE,
    }
)

#: The three that are *not* `relationship_memory.*`, and what each one discloses
#: under a purpose issued for something else. This is the part of
#: `RM-API-AC-002` that is a disclosure rather than a design, so each entry says
#: the purpose, the rows and the fields rather than only the name.
BEYOND_THE_EIGHT: Final = {
    Capability.ENTITIES_CONTEXT: (
        "purpose `entity_read`. Reads `relationship_memories` joined to "
        "`relationship_memory_versions` through `summaries_for_context`, and "
        "carries each surviving memory's `statement` verbatim on the card — so "
        "an `entity_read` grant does return memory text. Bounded by the "
        "classification filter, the 25-memory card limit and `_mine`, not by "
        "the purpose name; `RM-API-AC-013` carries the card's own bound."
    ),
    Capability.REVIEW_LIST: (
        "purpose `capture_review`. `relationship_memory_review_cases` selects "
        "`relationship_memory_proposals` with two correlated subqueries over "
        "`relationship_memory_review_decisions`, so the listing discloses a "
        "`subject_entity_id`, a `proposed_kind` and, once promoted, an "
        "`accepted_memory_id` and `accepted_memory_version_id` — for a subject "
        "the grant never named. It carries no statement text: "
        "`RelationshipMemoryReviewCase` has no statement field. Gated by the "
        "plane composition rather than by the capability name, which is what "
        "`RM-API-AC-011` and `RM-API-AC-018` carry."
    ),
    Capability.REVIEW_DECIDE: (
        "purpose `review_disposition`. Reads `relationship_memory_proposals` "
        "twice (the case test and the `FOR UPDATE` read), "
        "`relationship_memory_review_decisions` for the chain and "
        "`relationship_memory_proposal_evidence` for the count; writes "
        "`relationship_memories`, `relationship_memory_versions` and "
        "`relationship_memory_evidence_links` on promotion. Bounded by what "
        "`_promotion_authority` can author and by the plane composition; "
        "`RM-API-AC-011` carries the promotion path."
    ),
}

#: Call sites in a port-holding module whose method name is one a memory-reaching
#: port declares, and whose receiver this walk cannot type. Empty, and asserted
#: empty rather than left implicit: an entry here is a place claim 3 could be
#: narrower than the truth without saying so, and the honest repair is an
#: annotation rather than a line in this registry.
UNTYPED_PORT_CALL_SITES: Final[frozenset[tuple[str, str]]] = frozenset()


# --- the source tree, parsed once --------------------------------------------


@cache
def _sources() -> tuple[tuple[Path, ast.Module], ...]:
    return tuple((path, ast.parse(path.read_text(encoding="utf-8"))) for path in _paths())


@cache
def _paths() -> tuple[Path, ...]:
    return tuple(sorted(PACKAGE.rglob("*.py")))


def _module_name(path: Path) -> str:
    dotted = path.relative_to(PACKAGE).with_suffix("").as_posix().replace("/", ".")
    if dotted == "__init__":
        return "my_pa"
    return "my_pa." + dotted.removesuffix(".__init__")


def _relative(path: Path) -> str:
    return path.relative_to(PACKAGE).as_posix()


def _methods(node: ast.ClassDef) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        child.name: child
        for child in node.body
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
    }


# --- claim 1: the eight tables -----------------------------------------------


@cache
def memory_tables() -> frozenset[str]:
    """The names `tables.py` binds the memory plane's `Table` objects to.

    Read off the objects rather than typed here, so the set this whole module
    measures is the schema's own and a ninth table joins it by existing.
    """
    return frozenset(
        name
        for name, value in vars(declarations).items()
        if isinstance(value, Table) and value.name.startswith(TABLE_PREFIX)
    )


def test_the_memory_plane_declares_exactly_eight_tables() -> None:
    """Anti-vacuity, and the one number `RM-P-AC-018` and this module share.

    A selector that matched nothing would make every other claim here pass over
    an empty set, and a selector that matched a table the plane does not own
    would widen the walk silently. The count is the check on both.
    """
    tables = memory_tables()
    assert len(tables) == 8, (
        f"the memory plane now declares {len(tables)} tables ({sorted(tables)}), not eight. "
        "If a table joined the plane, the walk below and `RM-P-AC-018` both move"
    )
    for name in tables:
        assert getattr(declarations, name).name == name, (
            f"{name} is bound to a table named {getattr(declarations, name).name}; this "
            "module assumes the binding name and the SQL name agree"
        )


# --- claim 2: which modules issue SQL against them ---------------------------


@cache
def _memory_bindings() -> dict[Path, frozenset[str]]:
    """Per module, the local names bound to one of the eight table objects."""
    tables = memory_tables()
    found: dict[Path, frozenset[str]] = {}
    for path, tree in _sources():
        if path == DECLARATIONS:
            continue
        bound = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("tables")
            for alias in node.names
            if alias.name in tables
        }
        if bound:
            found[path] = frozenset(bound)
    return found


def test_only_the_declared_modules_issue_sql_against_a_memory_table() -> None:
    """Exact set equality, because the walk's cost assumes this answer is small.

    Two modules is what makes claim 3 a call-graph walk rather than a grep over
    six thousand lines of service: everything that touches a memory row bottoms
    out in one of these files, so the walk only has to find the callers.
    """
    naming = frozenset(_relative(path) for path in _memory_bindings())
    assert naming == MEMORY_SQL_MODULES, (
        f"{sorted(naming ^ MEMORY_SQL_MODULES)} builds statements over a memory table "
        "but is not declared, or is declared and no longer does. A third module on this "
        "plane changes what `RM-API-AC-002` has to enumerate"
    )


# --- the reachability walk ---------------------------------------------------
#
# A node is one function: `("C", class, method)` or `("M", module, function)`.
# A node *reaches* a memory row if it names one of the eight table bindings, or
# calls a node that does. Nested `def`s are walked as part of the function that
# encloses them, which is deliberate — `_Reviews.cases` builds its whole query
# inside a nested `statement()` handed to `_read`, and attributing it to the
# enclosing method is what makes the port crossing visible.


def _annotated(node: ast.expr | None) -> str | None:
    """Reduce an annotation to a bare class name, or `None` if it is not one."""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        # `Repository | None`: the union's one real member is the type.
        for side in (node.left, node.right):
            if isinstance(side, ast.Constant) and side.value is None:
                continue
            resolved = _annotated(side)
            if resolved is not None:
                return resolved
        return None
    if isinstance(node, ast.Subscript) and _annotated(node.value) == "Optional":
        return _annotated(node.slice)
    return None


@cache
def _classes() -> dict[str, tuple[Path, ast.ClassDef]]:
    """Module-level classes by bare name, first definition wins.

    Bare names because an annotation gives a bare name; a handful of names are
    defined twice across the tree (`Disposition`, `EntityType` and nine others,
    domain models mirrored by adapters), and none of them is a repository or an
    application service, so the collision cannot merge a memory-reaching node
    into an unrelated one.
    """
    found: dict[str, tuple[Path, ast.ClassDef]] = {}
    for path, tree in _sources():
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                found.setdefault(node.name, (path, node))
    return found


@cache
def _subclasses() -> dict[str, frozenset[str]]:
    """Direct subclass names, by base name."""
    found: dict[str, set[str]] = collections.defaultdict(set)
    for name, (_path, node) in _classes().items():
        for base in node.bases:
            if isinstance(base, ast.Name):
                found[base.id].add(name)
            elif isinstance(base, ast.Attribute):
                found[base.attr].add(name)
    return {base: frozenset(names) for base, names in found.items()}


def _implementations(name: str) -> frozenset[str]:
    """A class and everything below it, so a port call reaches its implementors."""
    seen = {name}
    pending = [name]
    while pending:
        for child in _subclasses().get(pending.pop(), frozenset()):
            if child not in seen:
                seen.add(child)
                pending.append(child)
    return frozenset(seen)


@cache
def _module_functions() -> dict[tuple[str, str], ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        (_module_name(path), node.name): node
        for path, tree in _sources()
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


@cache
def _imported_names() -> dict[str, dict[str, tuple[str, str]]]:
    """Per module, `local name -> (source module, original name)` for absolute imports."""
    found: dict[str, dict[str, tuple[str, str]]] = {}
    for path, tree in _sources():
        found[_module_name(path)] = {
            alias.asname or alias.name: (node.module, alias.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
            for alias in node.names
        }
    return found


#: `("C", class, method)` or `("M", module, function)`.
Node = tuple[str, str, str]


@cache
def _nodes() -> dict[Node, tuple[Path, str | None, ast.FunctionDef | ast.AsyncFunctionDef]]:
    found: dict[Node, tuple[Path, str | None, ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for path, tree in _sources():
        module = _module_name(path)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                found[("M", module, node.name)] = (path, None, node)
            elif isinstance(node, ast.ClassDef):
                for method in _methods(node).values():
                    found[("C", node.name, method.name)] = (path, node.name, method)
    return found


@cache
def _self_attributes() -> dict[str, dict[str, str]]:
    """Per class, `self._x -> type name`, from `__init__` and class-level annotations."""
    found: dict[str, dict[str, str]] = {}
    for name, (_path, node) in _classes().items():
        attributes: dict[str, str] = {}
        for statement in node.body:
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                annotated = _annotated(statement.annotation)
                if annotated is not None:
                    attributes[statement.target.id] = annotated
        initialiser = _methods(node).get("__init__")
        if initialiser is not None:
            arguments = initialiser.args
            parameters = {
                argument.arg: _annotated(argument.annotation)
                for argument in [
                    *arguments.posonlyargs,
                    *arguments.args,
                    *arguments.kwonlyargs,
                ]
            }
            for statement in ast.walk(initialiser):
                if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
                    continue
                target = statement.targets[0]
                if not isinstance(target, ast.Attribute):
                    continue
                if not (isinstance(target.value, ast.Name) and target.value.id == "self"):
                    continue
                value = statement.value
                if isinstance(value, ast.Name) and parameters.get(value.id):
                    attributes[target.attr] = str(parameters[value.id])
                elif (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id in _classes()
                ):
                    attributes[target.attr] = value.func.id
        found[name] = attributes
    return found


def _attribute_type(owner: str, attribute: str) -> str | None:
    """`owner.attribute`, resolved through a property's return type or `self._x`."""
    entry = _classes().get(owner)
    if entry is not None:
        method = _methods(entry[1]).get(attribute)
        if method is not None:
            return _annotated(method.returns)
    return _self_attributes().get(owner, {}).get(attribute)


def _environment(
    enclosing: str | None, function: ast.FunctionDef | ast.AsyncFunctionDef
) -> dict[str, str]:
    """The names inside one function this walk can put a type to."""
    known: dict[str, str] = {}
    if enclosing is not None:
        known["self"] = enclosing
    arguments = function.args
    for argument in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]:
        annotated = _annotated(argument.annotation)
        if annotated is not None:
            known[argument.arg] = annotated
    for statement in ast.walk(function):
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            annotated = _annotated(statement.annotation)
            if annotated is not None:
                known[statement.target.id] = annotated
        elif (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id in _classes()
        ):
            known[statement.targets[0].id] = statement.value.func.id
    return known


def _expression_type(node: ast.expr, known: dict[str, str]) -> str | None:
    """The class an expression evaluates to, or `None` where the walk cannot say."""
    if isinstance(node, ast.Name):
        return known.get(node.id) or (node.id if node.id in _classes() else None)
    if isinstance(node, ast.Attribute):
        owner = _expression_type(node.value, known)
        return None if owner is None else _attribute_type(owner, node.attr)
    if isinstance(node, ast.Call):
        function = node.func
        if isinstance(function, ast.Name) and function.id in _classes():
            return function.id
        if isinstance(function, ast.Attribute):
            owner = _expression_type(function.value, known)
            if owner is not None:
                entry = _classes().get(owner)
                if entry is not None:
                    method = _methods(entry[1]).get(function.attr)
                    if method is not None:
                        return _annotated(method.returns)
        return None
    if isinstance(node, ast.IfExp):
        # `unit_of_work.relationship_memory if composed else None`.
        return _expression_type(node.body, known) or _expression_type(node.orelse, known)
    if isinstance(node, ast.Await):
        return _expression_type(node.value, known)
    return None


@cache
def _edges() -> dict[Node, frozenset[Node]]:
    """Caller to callee, over everything this walk can resolve."""
    found: dict[Node, set[Node]] = collections.defaultdict(set)
    for node, (path, enclosing, function) in _nodes().items():
        module = _module_name(path)
        known = _environment(enclosing, function)
        for call in ast.walk(function):
            if not isinstance(call, ast.Call):
                continue
            called = call.func
            if isinstance(called, ast.Name):
                if (module, called.id) in _module_functions():
                    found[node].add(("M", module, called.id))
                    continue
                imported = _imported_names()[module].get(called.id)
                if imported is not None and imported in _module_functions():
                    found[node].add(("M", imported[0], imported[1]))
            elif isinstance(called, ast.Attribute):
                owner = _expression_type(called.value, known)
                if owner is None:
                    continue
                for implementation in _implementations(owner):
                    if ("C", implementation, called.attr) in _nodes():
                        found[node].add(("C", implementation, called.attr))
    return {caller: frozenset(callees) for caller, callees in found.items()}


@cache
def _directly_naming_a_memory_table() -> frozenset[Node]:
    bindings = _memory_bindings()
    found: set[Node] = set()
    for node, (path, _enclosing, function) in _nodes().items():
        bound = bindings.get(path)
        if bound is None:
            continue
        named = {name.id for name in ast.walk(function) if isinstance(name, ast.Name)}
        if named & bound:
            found.add(node)
    return frozenset(found)


@cache
def reaching_nodes() -> frozenset[Node]:
    """Every function that can read or write one of the eight, transitively."""
    callers: dict[Node, set[Node]] = collections.defaultdict(set)
    for caller, callees in _edges().items():
        for callee in callees:
            callers[callee].add(caller)
    reached = set(_directly_naming_a_memory_table())
    pending = list(reached)
    while pending:
        for caller in callers.get(pending.pop(), set()):
            if caller not in reached:
                reached.add(caller)
                pending.append(caller)
    return frozenset(reached)


# --- claim 3: the capability set ---------------------------------------------


@cache
def _handlers() -> dict[Capability, tuple[str, str]]:
    """`_HANDLERS` in `service.py`, as `capability -> (class, method)`.

    Read from the registry rather than from a list here, for the reason the
    registry's own comment gives: a capability is available exactly when
    something there can execute it, so there is no second place to edit.
    """
    tree = ast.parse(SERVICE.read_text(encoding="utf-8"))
    found: dict[Capability, tuple[str, str]] = {}
    for node in ast.walk(tree):
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        if not any(isinstance(target, ast.Name) and target.id == "_HANDLERS" for target in targets):
            continue
        for mapping in ast.walk(node):
            if not isinstance(mapping, ast.Dict):
                continue
            for key, value in zip(mapping.keys, mapping.values, strict=True):
                if (
                    isinstance(key, ast.Attribute)
                    and isinstance(key.value, ast.Name)
                    and key.value.id == "Capability"
                    and isinstance(value, ast.Attribute)
                    and isinstance(value.value, ast.Name)
                ):
                    found[Capability[key.attr]] = (value.value.id, value.attr)
    return found


@cache
def reaching_capabilities() -> frozenset[Capability]:
    """The derived answer `RM-API-AC-002` needs: who can reach a memory row."""
    reached = reaching_nodes()
    return frozenset(
        capability
        for capability, (owner, method) in _handlers().items()
        if ("C", owner, method) in reached
    )


def test_the_walk_finds_a_registry_a_population_and_a_path() -> None:
    """Anti-vacuity, in the three places this walk can silently find nothing.

    An empty handler registry, an empty set of functions naming a table, or a
    reaching set no larger than the functions that name one directly would each
    make claim 3 an assertion about nothing — and the third is the one that
    matters, because it is what says the *call graph* resolved rather than just
    the two persistence modules.
    """
    assert len(_handlers()) >= 60, (
        f"only {len(_handlers())} capabilities were read out of `_HANDLERS`; the "
        "registry moved or this parse went stale"
    )
    direct = _directly_naming_a_memory_table()
    assert len(direct) >= 12, (
        f"only {len(direct)} functions name a memory table binding; the two "
        "persistence modules hold more than that, so the scan is not reaching them"
    )
    reached = reaching_nodes()
    assert len(reached) > len(direct) + 8, (
        f"the walk reached {len(reached)} functions from {len(direct)} that name a "
        "table directly. The callers did not resolve, so claim 3 is measuring the "
        "persistence layer and calling it the capability surface"
    )
    eight = frozenset(
        capability for capability in Capability if capability.value.startswith(CAPABILITY_PREFIX)
    )
    assert len(eight) == 8, f"the plane now publishes {len(eight)} capabilities of its own, not 8"
    assert eight <= reaching_capabilities(), (
        f"{sorted(capability.value for capability in eight - reaching_capabilities())} are "
        "`relationship_memory.*` capabilities the walk did not find reaching a memory row. "
        "That is not a finding about the code; it is this walk failing"
    )


def test_every_capability_that_reaches_a_memory_row_is_declared() -> None:
    """The derived enumeration, against the one `RM-API-AC-002` cites.

    Exact set equality in both directions. A capability that starts reaching a
    memory row is a new disclosure surface and has to be argued about in the
    acceptance row; a capability that stops reaching one leaves a claim in that
    row describing something the code no longer does, which is the same defect
    pointing the other way.
    """
    derived = reaching_capabilities()
    assert derived == DECLARED, (
        f"{sorted(capability.value for capability in derived ^ DECLARED)} reaches a "
        "relationship-memory table without being declared, or is declared and no "
        "longer reaches one. Update `DECLARED`, `BEYOND_THE_EIGHT` and "
        "`RM-API-AC-002` together — the acceptance row cites this test by name"
    )


def test_every_capability_beyond_the_eight_says_what_it_discloses() -> None:
    """The residue is the disclosure, so the residue is what carries a reason.

    The eight are derived off the enum's own prefix rather than subtracted from
    a list here, so a ninth `relationship_memory.*` capability joins the plane
    without landing in `BEYOND_THE_EIGHT` and being described as an exception.
    """
    eight = frozenset(
        capability for capability in Capability if capability.value.startswith(CAPABILITY_PREFIX)
    )
    residue = reaching_capabilities() - eight
    assert residue == frozenset(BEYOND_THE_EIGHT), (
        f"{sorted(capability.value for capability in residue ^ frozenset(BEYOND_THE_EIGHT))} "
        "reaches a memory row from outside the eight with no written reason, or "
        "carries a reason and no longer reaches one"
    )
    for capability, reason in BEYOND_THE_EIGHT.items():
        purposes = permitted_purposes(capability)
        assert any(f"`{purpose.value}`" in reason for purpose in purposes), (
            f"{capability.value}'s reason names no purpose it actually holds "
            f"({sorted(purpose.value for purpose in purposes)}); the purpose is the "
            "grant boundary the criterion is about"
        )


# --- claim 5: the walk has no blind spot on the names that matter ------------


@cache
def _memory_reaching_port_methods() -> dict[str, frozenset[str]]:
    """Per port protocol, the methods whose implementations reach a memory row.

    This is the boundary the application layer actually crosses, and it is where
    an untyped receiver would hide a reach — so it is what claim 5 sweeps for.
    """
    reached = reaching_nodes()
    ports = ast.parse(PORTS.read_text(encoding="utf-8"))
    found: dict[str, frozenset[str]] = {}
    for node in ports.body:
        if not isinstance(node, ast.ClassDef):
            continue
        crossing = frozenset(
            method
            for method in _methods(node)
            for implementation in _implementations(node.name) - {node.name}
            if ("C", implementation, method) in reached
        )
        if crossing:
            found[node.name] = crossing
    return found


@cache
def _port_holding_modules() -> frozenset[str]:
    """Modules importing from `contracts.ports` — the only ones holding a repository.

    The sweep is scoped to these because the port method names include `search`,
    `get` and `history`, which every dictionary and regular expression in the
    tree also answers to. Scoping by *who could hold a port* rather than by
    which names look distinctive keeps the population derived: a module that
    starts holding a port joins the sweep by importing one.
    """
    return frozenset(
        _module_name(path)
        for path, tree in _sources()
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "my_pa.contracts.ports"
    )


def test_the_port_crossings_that_reach_a_memory_row_are_the_two_planes() -> None:
    """Anti-vacuity for claim 5, and a statement worth making on its own.

    Two ports carry the whole reach: the memory repository, which is the plane's
    own, and the review repository, which is the shared capture-plane surface the
    memory plane joined. That second one is the entire content of the
    `review.list` and `review.decide` findings — a capability can reach memory
    rows through a port that has nothing to do with memory in its name.
    """
    crossings = _memory_reaching_port_methods()
    assert set(crossings) == {"RelationshipMemoryRepository", "ReviewRepository"}, (
        f"the ports reaching a memory row are now {sorted(crossings)}. A third one is a "
        "new way for a capability to reach memory without naming it"
    )
    assert crossings["ReviewRepository"] == frozenset({"cases", "decide"}), (
        f"the review-plane crossings are now {sorted(crossings['ReviewRepository'])}; "
        "`RM-API-AC-002` enumerates exactly these"
    )


def test_no_call_to_a_memory_reaching_port_method_has_an_untyped_receiver() -> None:
    """The walk's own blind spot, asserted rather than assumed away.

    Claim 3 resolves a call by typing its receiver, so a receiver it cannot type
    is a call it does not follow — and an unfollowed call to `summaries_for_context`
    or `cases` would narrow the derived set without anything saying so. Every such
    call in a module that holds a port reference is required to resolve. There are
    none today; a first one is repaired with an annotation, not with an entry here.
    """
    names = {method for methods in _memory_reaching_port_methods().values() for method in methods}
    assert names, "no port method reaches a memory row; the crossing map went empty"
    holders = _port_holding_modules()
    assert len(holders) >= 20, (
        f"only {len(holders)} modules import from `contracts.ports`; the sweep's "
        "population collapsed and it now checks almost nothing"
    )
    untyped: set[tuple[str, str]] = set()
    for _node, (path, enclosing, function) in _nodes().items():
        module = _module_name(path)
        if module not in holders:
            continue
        known = _environment(enclosing, function)
        for call in ast.walk(function):
            if not isinstance(call, ast.Call):
                continue
            called = call.func
            if not isinstance(called, ast.Attribute) or called.attr not in names:
                continue
            if _expression_type(called.value, known) is None:
                untyped.add((module, ast.unparse(called)))
    assert untyped == UNTYPED_PORT_CALL_SITES, (
        f"{sorted(untyped - UNTYPED_PORT_CALL_SITES)} call a port method that reaches a "
        "memory row through a receiver this walk cannot type, so the derived capability "
        "set may be narrower than the truth. Annotate the receiver"
    )
