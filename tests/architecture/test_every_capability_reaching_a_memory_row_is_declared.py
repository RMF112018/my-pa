"""Which capabilities reach a relationship-memory row, and which rows, derived.

`evidence/acceptance/RELATIONSHIP-MEMORY-RM-AC-20260822.md`'s `RM-API-AC-002`
carries the criterion "each capability has a grant boundary appropriate to the
rows it reaches". A grant boundary is only appropriate to a reach someone has
measured, and that row got the reach wrong in prose three times running, at
three successive heads, each time caught by a different independent review.

The first version named the eight `relationship_memory.*` capabilities and
stopped, so `entities.context` — which puts every carried memory's `statement`
verbatim on a card served under `entity_read` — was disclosed by nothing. The
correction added `entities.context` and `review.decide` and then asserted that
"the enumeration of capabilities outside the eight is complete at two". It is
three: `review.list` reads `relationship_memory_proposals` and correlates two
subqueries over `relationship_memory_review_decisions`, so a `capture_review`
grant learns a `subject_entity_id`, a `proposed_kind` and — after promotion — an
`accepted_memory_id`, for a subject the grant never named.

**The third failure is what gave this module its present shape.** The commit
that fixed the second derived *which capabilities* reach a memory row — the walk
below — and left *which tables each one reaches* beside it as prose. That prose
was wrong in the sentence announcing the fix. It said `review.decide` "reads four
of the eight" and, "on promotion, writes three". It reads three and writes five:
the fourth read was `relationship_memory_proposals` counted twice, `_copy_evidence`'s
own read of `relationship_memory_proposal_evidence` went unnamed, and `_promote`'s
three writes were quoted as the capability's when `insert(relationship_memory_review_decisions)`
and `update(relationship_memory_proposals)` fire on *every* disposition, promotion
or not.

Three false enumerations of the capabilities, a fourth of their tables, one
criterion. **So neither enumeration is prose here.** This module derives both
from the source, compares each to a declaration, *and parses `RM-API-AC-002` for
its own digits* so the row cannot restate a number the walk contradicts. The
declared sets are literals because a declaration is the thing under review;
everything they are measured against is derived.

Nine claims, separated because they fail for different reasons:

1. **The eight tables are the schema's, not this file's.** They are read off the
   `Table` objects in `infrastructure.persistence.tables`, and the count is
   asserted, so a ninth memory table cannot join the plane without being seen.
2. **Only the declared modules name one.** Exact set equality, so a third module
   that starts building a statement over a memory table has to be argued about
   here. This is the claim that keeps the walk below cheap: the whole
   memory-touching surface of `src/` is two files.
3. **The capability set is derived by a reachability walk and matches the
   declaration.** Exact set equality over `Capability` members, so a capability
   that starts reaching a memory row either updates the declaration or reddens.
4. **Every capability beyond the eight carries a written reason.** The eight are
   derived off the enum's own `relationship_memory.` prefix; the residue is the
   part `RM-API-AC-002` has to disclose, and each entry says what it discloses
   and under which purpose.
5. **Each capability's *tables* are derived too, split into reads and writes.**
   The same walk, carrying a table set along its edges instead of only a boolean,
   with `select` told apart from `insert`/`update`/`delete` by the statement
   constructor at the root of the expression the table name sits in. Exact set
   equality against `DECLARED_TABLE_REACH`, which is what a changed reach has to
   be re-argued against.
6. **Every mention of a memory table lands in one of those two sets.** A name
   that appears outside any statement chain is counted as a read — the
   conservative direction — *and* has to be in `UNCLASSIFIED_TABLE_MENTIONS` with
   a reason, so a statement shape this derivation cannot read is a redness rather
   than a silent omission.
7. **`RM-API-AC-002`'s own "N of the eight (…)" claims are checked against the
   walk**, count and membership both, for every capability the row has to
   disclose. Prose failed three times; it is now parsed.
   `test_claimed_test_counts_match_collection.py` is the precedent, and its
   lesson is taken with it: the pattern that matches
   nothing passes everything, so the parse asserts it found claims, asserts both
   verbs appear, and asserts every capability beyond the eight carries one.
8. **The port crossings that reach memory are the two planes**, which is
   anti-vacuity for claim 9 and a statement worth making on its own.
9. **The walk's demonstrated blind spots are closed or declared.** Four of them,
   each found by an independent review constructing a reach that slipped past the
   walk *and* past the untyped-receiver sweep: an unannotated receiver at a call
   site (`UNTYPED_PORT_CALL_SITES`), a port method referenced without being called
   — `functools.partial`, a callback, an assignment (`UNCALLED_PORT_METHOD_REFERENCES`),
   a call dispatched through a subscript (`DISPATCH_THROUGH_A_SUBSCRIPT`), and a
   table reached as `tables.<name>` rather than by a bare imported name, which
   claim 2 now sees.

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
This over-approximates towards *more* reach, never less, and claim 9 is what
says the approximation is not silently going the other way.

**A derived table set is a bound, not an itinerary.** It says which of the eight
a capability's code path *can* touch, unioned over every branch. `relationship_memory.archive`
writes no statement, but it shares `_insert_version` with `revise`, so
`relationship_memory_versions` and `relationship_memory_context_links` are in its
write set. That is the right side to err on for a disclosure claim and the wrong
side for a description of one request, and `RM-API-AC-002` says which it is
making.

**What is still open, stated because the row may claim only what is bound.**
Four escapes are closed above; these are not. A *call* whose receiver this walk
cannot type is caught only inside a module that imports `contracts.ports`, so a
module reaching a repository handed to it by some other route is unswept. An
uncalled reference to a port method whose receiver types to something *other*
than a port implementation is allowed through, which is what lets `receipt.history`
sit in a declaration rather than in the sweep — a genuine port hidden behind a
misleading annotation would ride out on the same rule. A statement built by a
helper that takes the table as a *parameter* would attribute the table to the
helper and the operation to whatever the helper does, which is correct, but a
helper that took the *operation* as a parameter too would not classify. And
`_memory_bindings` reads three import spellings; a fourth (a table fetched out of
`metadata.tables["…"]` by string) would be invisible to every claim here. None of
these exists today. Each is a way the derived sets could be narrower than the
truth without anything reddening, and `RM-API-AC-002` therefore cites this module
for what it derives rather than for completeness.

Nothing here opens a connection, reaches a source, or touches a database. It
parses the source tree and imports the table declarations for their names.
"""

from __future__ import annotations

import ast
import collections
import re
from functools import cache
from pathlib import Path
from typing import Final

import pytest
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

#: The acceptance package, parsed for the digits `RM-API-AC-002` states about the
#: rows each capability reaches. Claim 7 is the whole reason this path is here: a
#: number in that row has been wrong three times and checked by nothing.
ACCEPTANCE: Final = ROOT / "evidence" / "acceptance" / "RELATIONSHIP-MEMORY-RM-AC-20260822.md"

#: The row whose digits are bound.
ROW: Final = "RM-API-AC-002"

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
        "purpose `review_disposition`. Reads three of the eight — "
        "`relationship_memory_proposals` (the case test and again under "
        "`FOR UPDATE`), `relationship_memory_review_decisions` for the chain, and "
        "`relationship_memory_proposal_evidence` in both `_promote`'s count and "
        "`_copy_evidence`'s own select — and writes five. Three of those five are "
        "the promotion (`relationship_memories`, `relationship_memory_versions`, "
        "`relationship_memory_evidence_links`); the other two, "
        "`relationship_memory_review_decisions` and `relationship_memory_proposals`, "
        "are written on *every* disposition, including a reject. Bounded by what "
        "`_promotion_authority` can author and by the plane composition; "
        "`RM-API-AC-011` carries the promotion path."
    ),
}

#: Per capability, the memory tables it can read and the ones it can write.
#:
#: The declaration claim 5 is measured against, and the reason it exists rather
#: than a count: the row's third false enumeration got the *count* of
#: `review.decide`'s reads wrong by naming the same table twice, so a number on
#: its own would have absorbed the defect. Membership is what is declared; the
#: count follows from it.
#:
#: A capability's set is the union over every branch its handler can reach, which
#: is a bound and not an itinerary — see this module's docstring on
#: `relationship_memory.archive`.
DECLARED_TABLE_REACH: Final[dict[Capability, tuple[frozenset[str], frozenset[str]]]] = {
    Capability.RELATIONSHIP_MEMORY_CREATE: (
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_submissions",
                "relationship_memory_versions",
            }
        ),
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_submissions",
                "relationship_memory_versions",
            }
        ),
    ),
    Capability.RELATIONSHIP_MEMORY_REVISE: (
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_evidence_links",
                "relationship_memory_submissions",
                "relationship_memory_versions",
            }
        ),
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_submissions",
                "relationship_memory_versions",
            }
        ),
    ),
    Capability.RELATIONSHIP_MEMORY_ARCHIVE: (
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_submissions",
                "relationship_memory_versions",
            }
        ),
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_submissions",
                "relationship_memory_versions",
            }
        ),
    ),
    Capability.RELATIONSHIP_MEMORY_RESTORE: (
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_submissions",
                "relationship_memory_versions",
            }
        ),
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_submissions",
                "relationship_memory_versions",
            }
        ),
    ),
    Capability.RELATIONSHIP_MEMORY_GET: (
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_evidence_links",
                "relationship_memory_versions",
            }
        ),
        frozenset(),
    ),
    Capability.RELATIONSHIP_MEMORY_LIST: (
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_context_links",
                "relationship_memory_versions",
            }
        ),
        frozenset(),
    ),
    Capability.RELATIONSHIP_MEMORY_SEARCH: (
        frozenset({"relationship_memories", "relationship_memory_versions"}),
        frozenset(),
    ),
    Capability.RELATIONSHIP_MEMORY_HISTORY: (
        frozenset({"relationship_memories", "relationship_memory_versions"}),
        frozenset(),
    ),
    Capability.ENTITIES_CONTEXT: (
        frozenset({"relationship_memories", "relationship_memory_versions"}),
        frozenset(),
    ),
    Capability.REVIEW_LIST: (
        frozenset({"relationship_memory_proposals", "relationship_memory_review_decisions"}),
        frozenset(),
    ),
    Capability.REVIEW_DECIDE: (
        frozenset(
            {
                "relationship_memory_proposal_evidence",
                "relationship_memory_proposals",
                "relationship_memory_review_decisions",
            }
        ),
        frozenset(
            {
                "relationship_memories",
                "relationship_memory_evidence_links",
                "relationship_memory_proposals",
                "relationship_memory_review_decisions",
                "relationship_memory_versions",
            }
        ),
    ),
}

#: Where a memory table is named outside any statement this derivation can read.
#:
#: Each of these binds a table or a column expression to a local for a statement
#: built further down, so the operation is decided somewhere the name is not.
#: They are folded into the *read* set — the conservative direction — and listed
#: here as well, because a statement shape this walk cannot classify is exactly
#: how a write would come to be reported as a read.
UNCLASSIFIED_TABLE_MENTIONS: Final[dict[tuple[str, str, str], str]] = {
    (
        "infrastructure/persistence/relationship_memory.py",
        "page_for_entity",
        "current = relationship_memory_versions.alias('current')",
    ): "the version alias the page joins; the join is in the `select` below it",
    (
        "infrastructure/persistence/relationship_memory.py",
        "page_for_entity",
        "rank: ColumnElement[bool] = not_(relationship_memories.c.pinned)",
    ): "a sort key held in a local for the `order_by` below it, annotated because "
    "the declared SQLAlchemy floor cannot infer it",
    (
        "infrastructure/persistence/relationship_memory.py",
        "search",
        "current = relationship_memory_versions.alias('current')",
    ): "the same alias, for the search page",
    (
        "infrastructure/persistence/relationship_memory.py",
        "search",
        "vector = func.to_tsvector(text(f\"'{_SEARCH_CONFIG}'\"), current.c.statement_text)",
    ): "the tsvector over the aliased version's statement, matched in the `select` below it",
    (
        "infrastructure/persistence/relationship_memory.py",
        "summaries_for_context",
        "current = relationship_memory_versions.alias('current')",
    ): "the same alias, for the context card",
}

#: Calls dispatched through a subscript, in a module that holds a port.
#:
#: `_edges()` cannot follow one: the call's `func` is a `Subscript`, so there is
#: no name to look up and no receiver to type, and a reach behind one would be
#: absent from the derived answer with nothing to say so. **This is the
#: codebase's own dominant dispatch idiom**, which is why it is declared with a
#: reason each rather than assumed not to happen.
DISPATCH_THROUGH_A_SUBSCRIPT: Final[dict[tuple[str, str], str]] = {
    ("my_pa.application.service", "_HANDLERS[command.capability]"): (
        "the capability registry, and the one subscript this module does resolve — "
        "by reading the table rather than the call. `_handlers()` parses `_HANDLERS` "
        "out of the source and maps every capability to the `(class, method)` it "
        "dispatches to, which is where the walk starts."
    ),
    ("my_pa.infrastructure.persistence.entity", "_DIRECTIONS[direction]"): (
        "three lambdas over `entity_relationships`, selected by an edge direction. "
        "It reaches no memory table — `entity.py` names none of the eight — and it "
        "returns a predicate rather than calling a repository."
    ),
}

#: References to a memory-reaching port method that are not calls of it.
#:
#: `functools.partial(repository.summaries_for_context, …)`, a callback handed to
#: a registry, `handler = repository.cases` — each reaches a memory row through a
#: name `_edges()` never sees in call position. Sweeping for the *name* rather
#: than for the call catches all three, at the price of one collision, which is
#: what this declaration holds.
UNCALLED_PORT_METHOD_REFERENCES: Final[dict[tuple[str, str], str]] = {
    ("my_pa.application.service", "receipt.history"): (
        "not a port method. `receipt` is bound from `conflict.receipt` on a caught "
        "conflict, which this walk cannot type, and `history` there is the task "
        "write receipt's own history field. It collides with "
        "`RelationshipMemoryRepository.history`, with which it shares nothing but "
        "the word."
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


def _dotted(node: ast.expr) -> str | None:
    """`a.b.c` for a pure name/attribute chain, or `None` for anything else."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted(node.value)
        return None if prefix is None else f"{prefix}.{node.attr}"
    return None


def _table_expressions(
    node: ast.AST, names: dict[str, frozenset[str]]
) -> list[tuple[ast.expr, frozenset[str]]]:
    """Every expression inside `node` that this walk reads as a memory table."""
    found: list[tuple[ast.expr, frozenset[str]]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Name | ast.Attribute):
            continue
        key = _dotted(child)
        if key is not None and key in names:
            found.append((child, names[key]))
    return found


@cache
def _memory_bindings() -> dict[Path, dict[str, frozenset[str]]]:
    """Per module, every expression this walk reads as one of the eight tables.

    Three spellings, because for a while only the first was recognised and the
    other two were demonstrated escapes:

    * `from …tables import relationship_memories` binds a bare name. This was
      the whole of it, and it is the spelling both persistence modules use.
    * `from . import tables`, or `import ….tables as t`, binds the *module*, and
      `tables.relationship_memories` then reaches a row through an attribute no
      bare-name scan sees. Applied to an already-declared module it changes
      nothing; applied to a **new** one it let a module join the plane without
      appearing in the census below, which is the claim that keeps the walk
      cheap.
    * A module-level aggregate — `_MEMORY_COLUMNS` — carries the table into
      every statement that splats it, which is how `detail` and `history` name
      their columns and how `page_for_entity` names none of them directly.

    A fourth spelling, a table fetched out of `metadata.tables[…]` by string,
    would still be invisible. It does not occur, and this module's docstring says
    so rather than leaving it implied.
    """
    tables = memory_tables()
    found: dict[Path, dict[str, frozenset[str]]] = {}
    for path, tree in _sources():
        if path == DECLARATIONS:
            continue
        names: dict[str, frozenset[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if (node.module or "").endswith("tables") and alias.name in tables:
                        names[alias.asname or alias.name] = frozenset({alias.name})
                    elif alias.name == "tables":
                        local = alias.asname or alias.name
                        names.update({f"{local}.{table}": frozenset({table}) for table in tables})
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.endswith(".tables"):
                        local = alias.asname or alias.name
                        names.update({f"{local}.{table}": frozenset({table}) for table in tables})
        for statement in tree.body:
            target = _assigned_name(statement)
            value = getattr(statement, "value", None)
            if target is None or value is None:
                continue
            carried = frozenset[str]().union(
                *(tables for _child, tables in _table_expressions(value, names))
            )
            if carried:
                names[target] = carried
        found[path] = names
    return found


def _assigned_name(statement: ast.stmt) -> str | None:
    """The single bare name a statement assigns to, or `None`."""
    targets = (
        statement.targets
        if isinstance(statement, ast.Assign)
        else [statement.target]
        if isinstance(statement, ast.AnnAssign)
        else []
    )
    if len(targets) != 1 or not isinstance(targets[0], ast.Name):
        return None
    return targets[0].id


def test_only_the_declared_modules_issue_sql_against_a_memory_table() -> None:
    """Exact set equality, because the walk's cost assumes this answer is small.

    Two modules is what makes claim 3 a call-graph walk rather than a grep over
    six thousand lines of service: everything that touches a memory row bottoms
    out in one of these files, so the walk only has to find the callers.

    The census is over modules that *name* a table, not over modules that import
    one: `from . import tables` imports the whole declaration module, so an
    import-shaped census would have counted a module that never touched a memory
    row, and — worse — a bare-name census missed one that did.
    """
    naming = frozenset(
        _relative(path)
        for path, tree in _sources()
        if path != DECLARATIONS and _table_expressions(tree, _memory_bindings().get(path, {}))
    )
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

    Bare names because an annotation gives a bare name; twelve names are defined
    twice across the tree (`Disposition`, `EntityType` and ten others, domain
    models mirrored by adapters), and none of them is a repository or an
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
    """Per module, `local name -> (source module, original name)`.

    Absolute imports, plus module-level assignment aliases. An aliased *import*
    (`import … as x`) was followed from the start; an aliased *assignment*
    (`_aliased = relationship_memory_review_cases`) was not, and a call through
    the second name resolved to no edge at all — a reach that reddened nothing
    because the walk simply did not see the call.
    """
    found: dict[str, dict[str, tuple[str, str]]] = {}
    for path, tree in _sources():
        module = _module_name(path)
        bound = {
            alias.asname or alias.name: (node.module, alias.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
            for alias in node.names
        }
        for statement in tree.body:
            target = _assigned_name(statement)
            value = getattr(statement, "value", None)
            if target is None or not isinstance(value, ast.Name):
                continue
            if value.id in bound:
                bound[target] = bound[value.id]
            elif (module, value.id) in _module_functions():
                bound[target] = (module, value.id)
        found[module] = bound
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
    return frozenset(
        node
        for node, (path, _enclosing, function) in _nodes().items()
        if _table_expressions(function, _memory_bindings().get(path, {}))
    )


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
        "longer reaches one. If the code moved, update `DECLARED`, "
        "`BEYOND_THE_EIGHT`, `DECLARED_TABLE_REACH` and `RM-API-AC-002` together — "
        "the acceptance row cites this test by name. If the code did not move, this "
        "is not a finding about the code; it is this walk failing, and the repair is "
        "in the walk"
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


# --- claims 5 and 6: which tables, and read or written -----------------------
#
# The same nodes and the same edges, carrying a pair of table sets instead of a
# boolean. A table name is attributed to the statement it sits in, and the
# statement's operation is read off the constructor at the root of the
# expression chain — `select(...).select_from(t).where(_mine(t, p))` is one
# chain rooted at `select`, so both mentions of `t` are reads, and
# `insert(t).values(_bound(t, p, {...}))` is one chain rooted at `insert`.
# Attributing by chain root rather than by nearest call is what makes
# `_mine`/`_bound` — the partition wrappers every statement here goes through —
# transparent instead of opaque.

#: What each statement constructor does to a row. `select` is the only read, and
#: the split is the whole content of claim 5: `RM-API-AC-002` has to disclose
#: what a grant can *learn* separately from what it can *change*.
STATEMENT_CONSTRUCTORS: Final = {
    "select": "read",
    "insert": "write",
    "update": "write",
    "delete": "write",
}


def _chain_root(call: ast.Call, statements: dict[str, str]) -> str | None:
    """The constructor a call's expression chain is rooted at, if any.

    `select(a).where(b).limit(c)` is a `Call` whose `func` is an `Attribute` on a
    `Call` whose `func` is an `Attribute` on `select(a)`, so the root is found by
    walking down the `func` side. Where the chain is rooted at a *name* instead —
    `statement = select(...)` and then `statement.order_by(...)`, which both
    persistence modules do — the name is looked up in the statement locals this
    function is given.
    """
    function = call.func
    if isinstance(function, ast.Name):
        return function.id if function.id in STATEMENT_CONSTRUCTORS else None
    if isinstance(function, ast.Attribute):
        if isinstance(function.value, ast.Call):
            return _chain_root(function.value, statements)
        if isinstance(function.value, ast.Name):
            return statements.get(function.value.id)
    return None


def _statement_locals(function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, str]:
    """Locals holding a half-built statement, as `name -> constructor`."""
    found: dict[str, str] = {}
    for statement in ast.walk(function):
        target = _assigned_name(statement)
        value = getattr(statement, "value", None)
        if target is None or not isinstance(value, ast.Call):
            continue
        root = _chain_root(value, found)
        if root is not None:
            found[target] = root
    return found


def _local_table_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef, names: dict[str, frozenset[str]]
) -> dict[str, frozenset[str]]:
    """`names`, plus the locals a function aliases a memory table under.

    `current = relationship_memory_versions.alias("current")` is the only shape
    that occurs, and it occurs three times; without it every predicate written
    against the alias would be attributed to no table at all.
    """
    found = dict(names)
    for statement in ast.walk(function):
        target = _assigned_name(statement)
        value = getattr(statement, "value", None)
        if target is None or not isinstance(value, ast.Call):
            continue
        if not isinstance(value.func, ast.Attribute) or value.func.attr not in {
            "alias",
            "join",
            "outerjoin",
        }:
            continue
        carried = frozenset[str]().union(
            *(tables for _child, tables in _table_expressions(value, found))
        )
        if carried:
            found[target] = carried
    return found


#: `(reads, writes, unclassified)`, where `unclassified` names the enclosing
#: statement so a shape this derivation cannot read is legible.
TableReach = tuple[frozenset[str], frozenset[str], frozenset[tuple[str, str, str]]]


@cache
def _direct_table_reach() -> dict[Node, TableReach]:
    """Per function, the memory tables its own statements read and write."""
    found: dict[Node, TableReach] = {}
    for node, (path, _enclosing, function) in _nodes().items():
        names = _local_table_names(function, _memory_bindings().get(path, {}))
        mentions = _table_expressions(function, names)
        if not mentions:
            continue
        statements = _statement_locals(function)
        parents = {
            child: parent for parent in ast.walk(function) for child in ast.iter_child_nodes(parent)
        }
        reads: set[str] = set()
        writes: set[str] = set()
        unclassified: set[tuple[str, str, str]] = set()
        for child, tables in mentions:
            if isinstance(child.ctx, ast.Store | ast.Del):
                continue
            operation = None
            cursor: ast.AST = child
            while cursor in parents:
                cursor = parents[cursor]
                if isinstance(cursor, ast.Call):
                    root = _chain_root(cursor, statements)
                    if root is not None:
                        operation = STATEMENT_CONSTRUCTORS[root]
                        break
            if operation == "read":
                reads |= tables
            elif operation == "write":
                writes |= tables
            else:
                # Conservative: an unreadable shape is a read, never a silent
                # absence. It is registered as well, because a *write* misread as
                # a read is the failure this direction cannot catch on its own.
                reads |= tables
                unclassified.add(
                    (_relative(path), function.name, _enclosing_statement(child, parents))
                )
        found[node] = (frozenset(reads), frozenset(writes), frozenset(unclassified))
    return found


def _enclosing_statement(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    """The source of the smallest statement holding `node`, for a legible registry."""
    cursor = node
    while cursor in parents and not isinstance(cursor, ast.stmt):
        cursor = parents[cursor]
    return ast.unparse(cursor)


@cache
def _reachable_from(node: Node) -> frozenset[Node]:
    """`node` and everything it can call, transitively."""
    edges = _edges()
    seen = {node}
    pending = [node]
    while pending:
        for callee in edges.get(pending.pop(), frozenset()):
            if callee not in seen:
                seen.add(callee)
                pending.append(callee)
    return frozenset(seen)


@cache
def capability_table_reach() -> dict[Capability, tuple[frozenset[str], frozenset[str]]]:
    """The derived answer `RM-API-AC-002` needs: which rows, and read or written."""
    direct = _direct_table_reach()
    found: dict[Capability, tuple[frozenset[str], frozenset[str]]] = {}
    for capability, (owner, method) in _handlers().items():
        reached = _reachable_from(("C", owner, method))
        reads = frozenset[str]().union(*(direct[node][0] for node in reached if node in direct))
        writes = frozenset[str]().union(*(direct[node][1] for node in reached if node in direct))
        if reads or writes:
            found[capability] = (reads, writes)
    return found


def test_every_capability_reaches_exactly_the_tables_it_declares() -> None:
    """The derived table sets, against the declaration `RM-API-AC-002` restates.

    Exact set equality per capability and in both directions, for the reason the
    row's own history gives: a capability that starts reading a new memory table
    discloses something new under a purpose already granted, and a capability
    that stops leaves the row describing a reach the code no longer has.

    Membership rather than a count, because the defect this replaces was a count.
    "It reads four of the eight" was arrived at by counting
    `relationship_memory_proposals` twice and missing
    `relationship_memory_proposal_evidence` once; the two errors nearly cancelled
    and a bare number would have hidden the fact that they had not.
    """
    derived = capability_table_reach()
    assert set(derived) == set(DECLARED_TABLE_REACH), (
        f"{sorted(capability.value for capability in set(derived) ^ set(DECLARED_TABLE_REACH))} "
        "reaches a memory table without a declared table set, or declares one and "
        "reaches nothing"
    )
    wrong = [
        f"{capability.value} reads {sorted(derived[capability][0])} and writes "
        f"{sorted(derived[capability][1])}; it is declared to read "
        f"{sorted(DECLARED_TABLE_REACH[capability][0])} and write "
        f"{sorted(DECLARED_TABLE_REACH[capability][1])}"
        for capability in sorted(derived, key=lambda member: member.value)
        if derived[capability] != DECLARED_TABLE_REACH[capability]
    ]
    assert not wrong, (
        "the tables these capabilities reach are not the tables declared for them. "
        "Update `DECLARED_TABLE_REACH` and the matching `RM-API-AC-002` sentence "
        "together, or repair the walk if the code did not move:\n" + "\n".join(wrong)
    )


def test_the_table_derivation_reads_every_statement_shape_it_meets() -> None:
    """Anti-vacuity for claim 5, and the registry of what it could not classify.

    Three floors. Both persistence modules must be represented, or the split is
    measuring one plane; every one of the eight must be reached by something, or
    a table is being disclosed by a claim that never mentions it; and the
    unclassified mentions must be exactly the declared ones, because those are
    the places a write could be reported as a read.
    """
    direct = _direct_table_reach()
    assert direct, "no function names a memory table in a statement; the derivation went empty"
    reads = frozenset[str]().union(*(entry[0] for entry in direct.values()))
    writes = frozenset[str]().union(*(entry[1] for entry in direct.values()))
    assert reads | writes == memory_tables(), (
        f"{sorted(memory_tables() - (reads | writes))} is one of the eight and no "
        "derived statement reads or writes it; the derivation is not seeing the plane"
    )
    assert writes, "nothing writes a memory table; `insert`/`update` are not being seen"
    unclassified = frozenset[tuple[str, str, str]]().union(*(entry[2] for entry in direct.values()))
    assert unclassified == frozenset(UNCLASSIFIED_TABLE_MENTIONS), (
        f"{sorted(unclassified ^ frozenset(UNCLASSIFIED_TABLE_MENTIONS))} names a memory "
        "table outside any statement this derivation can read. It has been counted as a "
        "read; if it is a write, the derived set is wrong in the direction that matters"
    )


# --- claim 7: the acceptance row's own digits --------------------------------
#
# `test_claimed_test_counts_match_collection.py` is the precedent: parse a
# document's figures and check them against a derived truth. Its lesson is taken
# with its idiom — a pattern that stops matching is a guard that passes over
# nothing, which happened there twice — so the parse asserts what it found before
# anything asserts that what it found is right.

#: `` `review.decide` reads three of the eight (`a`, `b`, `c`) ``. The count is
#: spelled rather than in digits because the row's prose is spelled throughout,
#: and the tables are carried in the same clause rather than somewhere in the
#: surrounding paragraph: the defect being closed was a *correct* count beside a
#: wrong membership, and a pattern that read only the number would have passed it.
#:
#: The capability is optional because the second half of a reach is written with
#: the subject elided — "reads two of the eight (…) and writes none of the
#: eight" — and requiring the name would have bound the read of every capability
#: here and the write of none. That is the precedent module's own lesson about
#: punctuation, in a different costume: a pattern that insists on one spelling
#: silently guards the sentences written the other way. An elided subject carries
#: over from the claim before it, and an elided subject with nothing before it is
#: a failure rather than a skip.
TABLE_SET_CLAIM: Final = re.compile(
    r"(?:`(?P<capability>[a-z_]+(?:\.[a-z_]+)+)`\s+)?(?P<verb>reads|writes)\s+"
    r"(?P<count>[a-z]+)\s+of the eight(?:\s*\((?P<tables>[^)]*)\))?"
)

#: The row spells its numbers, and only these can be meant by "of the eight".
_SPELLED: Final = {
    "none": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
}

_BACKTICKED_TABLE: Final = re.compile(r"`(relationship_memor\w+)`")


@cache
def _acceptance_row() -> tuple[str, int]:
    """The `RM-API-AC-002` row and its line number, so a failure can be found."""
    text = ACCEPTANCE.read_text(encoding="utf-8")
    rows = [
        (line, number)
        for number, line in enumerate(text.splitlines(), start=1)
        if line.startswith(f"| {ROW} ")
    ]
    assert len(rows) == 1, (
        f"{ACCEPTANCE.name} holds {len(rows)} rows starting `| {ROW} `; this guard "
        "reads exactly one"
    )
    return rows[0]


def _row_claims() -> list[tuple[str, str, str, str | None]]:
    """`(capability, verb, count word, table list)` for every claim in the row.

    An elided subject takes the capability of the claim before it, which is what
    "reads two of the eight and writes none of the eight" means to a reader. One
    with nothing before it is carried through as the empty string so the check
    below fails on it by name rather than being quietly dropped here.
    """
    row, _line = _acceptance_row()
    found: list[tuple[str, str, str, str | None]] = []
    subject = ""
    for match in TABLE_SET_CLAIM.finditer(row):
        subject = match.group("capability") or subject
        found.append((subject, match.group("verb"), match.group("count"), match.group("tables")))
    return found


def test_the_acceptance_row_states_a_table_set_for_every_capability_it_discloses() -> None:
    """Anti-vacuity for claim 7, then the coverage requirement, both derived.

    A regular expression that matched nothing would make the parametrized check
    below a guard over an empty list, which is the exact failure the precedent
    module records twice. So: claims exist, both verbs appear, and — the part
    that is derived rather than a floor — every capability in
    `BEYOND_THE_EIGHT` carries both. Those three are what the row exists to
    disclose, and they are the three whose prose has been wrong.
    """
    claims = _row_claims()
    _row, line = _acceptance_row()
    assert claims, (
        f"no `` `capability` reads|writes N of the eight `` claim found at "
        f"{ACCEPTANCE.name}:{line}; either the row changed shape or this pattern went "
        "stale, and a stale pattern here checks nothing at all"
    )
    assert {verb for _capability, verb, _count, _tables in claims} == {"reads", "writes"}, (
        f"{ACCEPTANCE.name}:{line} states only "
        f"{sorted({verb for _c, verb, _n, _t in claims})}; a reach is two claims"
    )
    stated = {(capability, verb) for capability, verb, _count, _tables in claims}
    required = {
        (capability.value, verb) for capability in BEYOND_THE_EIGHT for verb in ("reads", "writes")
    }
    assert required <= stated, (
        f"{sorted(required - stated)} is a capability `RM-API-AC-002` has to disclose "
        "and the row states no table set for it. The three outside the eight are the "
        "disclosure; leaving one's reach in unparsed prose is how it was wrong three times"
    )


@pytest.mark.parametrize(("capability", "verb", "count", "tables"), _row_claims())
def test_every_table_set_the_acceptance_row_claims_matches_the_walk(
    capability: str, verb: str, count: str, tables: str | None
) -> None:
    """One claim in the row, against the walk. Count and membership both."""
    _row, line = _acceptance_row()
    members = {member.value: member for member in Capability}
    assert capability in members, (
        f"{ACCEPTANCE.name}:{line} states a table set for `{capability}`, which is no "
        "capability this build publishes"
    )
    assert count in _SPELLED, (
        f"{ACCEPTANCE.name}:{line} spells `{capability}`'s {verb} count as {count!r}, "
        f"which this guard cannot read. Spell it as one of {sorted(_SPELLED)}"
    )
    claimed = _SPELLED[count]
    reads, writes = capability_table_reach().get(members[capability], (frozenset(), frozenset()))
    derived = reads if verb == "reads" else writes
    assert claimed == len(derived), (
        f"{ACCEPTANCE.name}:{line} says `{capability}` {verb} {count} of the eight; the "
        f"walk derives {len(derived)} ({sorted(derived)}). Correct the row rather than "
        "this test"
    )
    if claimed == 0:
        assert tables is None, (
            f"{ACCEPTANCE.name}:{line} says `{capability}` {verb} none of the eight and "
            f"then lists {tables!r}"
        )
        return
    assert tables is not None, (
        f"{ACCEPTANCE.name}:{line} says `{capability}` {verb} {count} of the eight and "
        f"names none of them. Put the {claimed} in parentheses after the count — the "
        "count was right and the membership wrong the last time this row was corrected"
    )
    named = frozenset(_BACKTICKED_TABLE.findall(tables))
    assert named == derived, (
        f"{ACCEPTANCE.name}:{line} says `{capability}` {verb} {sorted(named)}; the walk "
        f"derives {sorted(derived)}. Correct the row rather than this test"
    )


# --- claim 9: the walk has no blind spot on the names that matter ------------


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


def _package(path: Path) -> str:
    """The package a relative import inside `path` is relative to."""
    module = _module_name(path)
    return module if path.name == "__init__.py" else module.rpartition(".")[0]


def _import_targets(path: Path, node: ast.Import | ast.ImportFrom) -> frozenset[str]:
    """Every dotted module an import statement names, absolute or relative.

    `from my_pa.contracts.ports import X`, `from my_pa.contracts import ports`,
    `import my_pa.contracts.ports`, `from ..contracts import ports` and
    `from .ports import X` all name the same module and are all returned as
    `my_pa.contracts.ports`. The first spelling was the only one recognised, and
    an independent review reached a repository from a module using the second.
    """
    if isinstance(node, ast.Import):
        return frozenset(alias.name for alias in node.names)
    if node.level:
        parts = _package(path).split(".")
        base = ".".join(parts[: max(len(parts) - node.level + 1, 0)])
        if node.module:
            base = f"{base}.{node.module}" if base else node.module
    else:
        base = node.module or ""
    return frozenset({base}) | {f"{base}.{alias.name}" for alias in node.names}


@cache
def _port_holding_modules() -> frozenset[str]:
    """Modules naming `contracts.ports` in an import — the ones holding a repository.

    The sweep is scoped to these because the port method names include `search`,
    `get` and `history`, which every dictionary and regular expression in the
    tree also answers to. Scoping by *who could hold a port* rather than by
    which names look distinctive keeps the population derived: a module that
    starts holding a port joins the sweep by importing one.

    Scoped by the module an import *names*, not by the exact string
    `from my_pa.contracts.ports import …`. `from my_pa.contracts import ports`
    reaches the same protocols and, before this, joined no sweep at all — a
    helper taking a repository as an unannotated parameter was invisible to the
    one claim that says the walk is not silently narrow.
    """
    return frozenset(
        _module_name(path)
        for path, tree in _sources()
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        and "my_pa.contracts.ports" in _import_targets(path, node)
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


def test_no_reference_to_a_memory_reaching_port_method_escapes_uncalled() -> None:
    """A port method handed around as a value, which no call-site sweep can see.

    `functools.partial(repository.summaries_for_context, …)`, a callback put in a
    registry, `handler = repository.cases` — each reaches a memory row, and in
    none of them is the method ever the `func` of a `Call`, so `_edges()` records
    no edge and the sibling sweep above finds no call site. An independent review
    built one and watched every test here stay green.

    Swept by *name* rather than by shape, so `partial` is not privileged over the
    next construct that takes a callable. The price is one collision with a data
    attribute of the same name, and the price is paid in a declaration that says
    which one and why rather than in a narrower rule.
    """
    names = {method for methods in _memory_reaching_port_methods().values() for method in methods}
    ports = frozenset[str]().union(
        *(_implementations(port) for port in _memory_reaching_port_methods())
    )
    holders = _port_holding_modules()
    escaping: set[tuple[str, str]] = set()
    for _node, (path, enclosing, function) in _nodes().items():
        module = _module_name(path)
        if module not in holders:
            continue
        known = _environment(enclosing, function)
        called = {id(call.func) for call in ast.walk(function) if isinstance(call, ast.Call)}
        for reference in ast.walk(function):
            if not isinstance(reference, ast.Attribute) or reference.attr not in names:
                continue
            if id(reference) in called:
                continue
            owner = _expression_type(reference.value, known)
            if owner is None or owner in ports:
                escaping.add((module, ast.unparse(reference)))
    assert escaping == frozenset(UNCALLED_PORT_METHOD_REFERENCES), (
        f"{sorted(escaping ^ frozenset(UNCALLED_PORT_METHOD_REFERENCES))} names a port "
        "method that reaches a memory row without calling it, so the walk records no "
        "edge and the derived capability set may be narrower than the truth. Call it "
        "through a name this walk can follow, or declare why it is not one"
    )


def test_no_dispatch_through_a_subscript_hides_a_memory_reach() -> None:
    """The codebase's own dispatch idiom, declared rather than assumed away.

    `_HANDLERS[command.capability](…)` is how this application routes every
    request, and `_edges()` cannot follow it: the call's `func` is a `Subscript`,
    which has neither a name to resolve nor a receiver to type. A second table of
    callables — `_MEMORY_READS["ctx"](repository, …)` — would reach memory rows
    and appear in no derived set, and an independent review demonstrated exactly
    that.

    Two exist, both declared with what they dispatch to. The claim is not that
    the idiom is absent; it is that each use of it has been read.
    """
    holders = _port_holding_modules()
    found: set[tuple[str, str]] = set()
    for _node, (path, _enclosing, function) in _nodes().items():
        module = _module_name(path)
        if module not in holders and _relative(path) not in MEMORY_SQL_MODULES:
            continue
        for call in ast.walk(function):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Subscript):
                found.add((module, ast.unparse(call.func)))
    assert found == frozenset(DISPATCH_THROUGH_A_SUBSCRIPT), (
        f"{sorted(found ^ frozenset(DISPATCH_THROUGH_A_SUBSCRIPT))} dispatches a call "
        "through a subscript in a module that holds a port or builds memory SQL. This "
        "walk follows no such call, so anything it reaches is missing from the derived "
        "sets. Say what it dispatches to, or route it through a name"
    )
