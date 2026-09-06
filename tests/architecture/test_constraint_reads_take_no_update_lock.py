"""No Constraint read path acquires a row lock, and the two that do stay mutation-only.

`SELECT ... FOR UPDATE` is the correct instrument in exactly one place in the
Constraint plane: the read-modify-write pair that a mutation performs inside its
own transaction, where the lock is what makes the optimistic `version` check
meaningful. `get_for_update` and `get_category_for_update` exist for that and
have no other purpose.

**The defect this prevents.** WP03 adds a read plane — list, detail, history,
relationships, evidence, sync facts, overview — on top of the same repository
class that already holds those two locking helpers. The cheapest way to write a
new read method is to copy the nearest existing one, and the nearest existing one
is a locker. A `list_constraints` that copied `get_for_update`'s statement would
be correct in every test, correct in every review reading it for *what it
returns*, and would silently take a write lock on every row of a Register page —
turning a page render into a blocker for concurrent mutations, and turning a
50-row list into a 50-row lock footprint held for the length of the request. The
symptom is contention under load, which is the class of defect that does not
appear until it appears in production.

**Why this is measured rather than reviewed.** The mistake is invisible in the
method's name, its signature, its return type and its tests. It is visible only
in one chained call, and only to a reader who thought to look for it. So the
whole set of read methods is enumerated here by name and every one is required to
be free of `with_for_update` — and the enumeration itself is checked against the
module, so a read method that is *renamed* rather than fixed does not slip out of
the guard's universe by leaving it.

**The zero is controlled.** A guard that finds nothing has proven nothing until
it has been shown able to find something. Two controls sit beside the claim:
`get_for_update` and `get_category_for_update` are required to **contain** the
call the reads are required to lack — measured by the same detector, so a
detector that stopped resolving `with_for_update` reddens here instead of
reporting a false zero — and the read names are required to actually resolve to
methods in the module. `D-26` and `D-44` are this repository's record of guards
that matched nothing and were believed; neither shape is available here.

**The second half of the rule.** A read that does not write `with_for_update`
itself but *calls* `get_for_update` has taken the lock just the same, one frame
down. So the reads are also required to make no call to either locking helper.

Nothing here opens a connection, reaches a database, or executes a statement. It
parses the repository's own committed source with `ast`.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]

#: The one module that holds every Constraint SQL statement in the product.
MODULE: Final = ROOT / "src" / "my_pa" / "infrastructure" / "persistence" / "constraints.py"

#: The chained call that turns a `SELECT` into a locking read.
LOCK_CALL: Final = "with_for_update"

#: The only two methods permitted to lock. Both exist to serve a mutation's
#: read-modify-write pair; neither is reachable from a read path.
LOCKERS: Final = frozenset({"get_for_update", "get_category_for_update"})

#: Every method on the repository that answers a question without changing a row.
#: The ten WP03 additions (plan §G, P1-P10) and the five reads that predate them.
#: Spelled out rather than derived from a name pattern, because a pattern would
#: quietly stop covering a method the moment someone named one differently.
READ_METHODS: Final = frozenset(
    {
        # WP03 read plane (plan §G).
        "list_categories",
        "read_constraint",
        "list_constraints",
        "parties_for",
        "entity_labels",
        "list_history",
        "relationships_for",
        "evidence_links_for",
        "sync_summary",
        "overview_facts",
        # Reads that predate WP03 and are equally forbidden to lock.
        "get",
        "get_category",
        "get_revision",
        "get_project_settings",
        "find_history_by_idempotency_key",
    }
)


def _module() -> ast.Module:
    return ast.parse(MODULE.read_text(encoding="utf-8"))


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    """Every function defined in the module, by name.

    Both `def` forms are collected. The repository class is synchronous today,
    but a guard that knew only `FunctionDef` would go blind the day one method
    became `async`, and it would go blind silently.
    """
    found: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found[node.name] = node  # type: ignore[assignment]
    return found


def _called_names(node: ast.AST) -> set[str]:
    """Every attribute or bare name this function calls.

    `x.with_for_update()` is an `Attribute` call and `self.get_for_update(...)`
    is too, so one collector answers both halves of the rule.
    """
    called: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        function = child.func
        if isinstance(function, ast.Attribute):
            called.add(function.attr)
        elif isinstance(function, ast.Name):
            called.add(function.id)
    return called


def test_the_detector_reports_a_locking_read_when_one_is_present() -> None:
    """The control that makes the zeros below measurements rather than silences.

    A synthetic module, not the tree. If this reddens, the walks below cannot see
    what they claim to have looked for and their emptiness means nothing.
    """
    planted = ast.parse(
        "class R:\n"
        "    def list_constraints(self, principal_id):\n"
        "        return self._connection.execute(\n"
        "            select(project_constraints).where(_mine()).with_for_update()\n"
        "        )\n"
        "    def read_constraint(self, principal_id, constraint_id):\n"
        "        return self.get_for_update(principal_id, constraint_id)\n"
    )
    functions = _functions(planted)
    assert LOCK_CALL in _called_names(functions["list_constraints"])
    assert LOCKERS & _called_names(functions["read_constraint"]) == {"get_for_update"}


def test_every_named_read_method_exists_in_the_repository_module() -> None:
    """The universe, stated. A rule about methods that are absent is a rule about nothing.

    This is what stops a read from escaping the guard by being renamed: the guard
    reddens on the rename instead of quietly narrowing to the methods that stayed.
    """
    defined = set(_functions(_module()))
    missing = sorted(READ_METHODS - defined)
    assert missing == [], (
        f"{MODULE.name} does not define these read methods: {missing}. Either the "
        "method was renamed — in which case update READ_METHODS in this module so "
        "the new name stays covered — or the read plane is incomplete"
    )


def test_the_two_mutation_only_helpers_still_take_the_lock_they_exist_to_take() -> None:
    """The other control: the detector is shown finding the call in real code.

    These two are the reason `with_for_update` is in the module at all. If either
    stopped locking, its mutation's optimistic `version` check would become a
    race the tests would not otherwise notice — and this module's zeros below
    would become unfalsifiable at the same moment.
    """
    functions = _functions(_module())
    for name in sorted(LOCKERS):
        assert name in functions, f"{MODULE.name} no longer defines {name}"
        assert LOCK_CALL in _called_names(functions[name]), (
            f"{name} no longer calls {LOCK_CALL}(). It exists to hold the row while "
            "its caller re-reads, compares `version` and writes; without the lock "
            "that comparison is a race. Restore the locking read, or — if the "
            "method genuinely became a read — remove it from LOCKERS here"
        )


def test_no_read_method_issues_a_locking_select() -> None:
    """Plan row T4, first half: a read renders a page, it does not block writers.

    Reported per method, so a failure names the read that grew the lock rather
    than only that one exists.
    """
    functions = _functions(_module())
    offending = sorted(
        name
        for name in READ_METHODS
        if name in functions and LOCK_CALL in _called_names(functions[name])
    )
    assert offending == [], (
        f"these read methods call {LOCK_CALL}(): {offending}. A read must not take a "
        "row lock: a Register page would hold one lock per row for the length of the "
        "request and block every concurrent mutation on those rows. Drop the "
        f".{LOCK_CALL}() from the statement; only {sorted(LOCKERS)} may lock, and "
        "only because a mutation re-reads through them inside its own transaction"
    )


def test_no_read_method_reaches_a_lock_through_the_mutation_only_helpers() -> None:
    """Plan row T4, second half: a lock taken one frame down is still a lock taken.

    `get_for_update` is a convenient way to fetch a Constraint by identity, and a
    read that wanted exactly that would find it and work. It would also lock.
    """
    functions = _functions(_module())
    offending = {
        name: sorted(LOCKERS & _called_names(functions[name]))
        for name in sorted(READ_METHODS)
        if name in functions and LOCKERS & _called_names(functions[name])
    }
    assert offending == {}, (
        f"these read methods call a mutation-only locking helper: {offending}. The "
        "helper locks the row it returns, so the read locks it too. Use the "
        "non-locking read for the same row — `get` for a Constraint aggregate, "
        "`read_constraint` for the read record, `get_category` for a category"
    )
