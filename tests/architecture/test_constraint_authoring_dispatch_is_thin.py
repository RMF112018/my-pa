"""No Constraint mutation semantics live in the dispatcher (PC-CM-IMP-WP07, T07-08).

`ConstraintManagementService` is the one canonical entry point for mutating a
Constraint or a Category. WP07 admits it to a transport and reimplements none of
it, and this is the guard that keeps that true after the next edit rather than
only on the day it was written.

Read from the AST of `src/my_pa/application/service.py`, per handler:

* every one of the twelve calls exactly one `ConstraintManagementService`
  method, through the composition seam and nothing else;
* none of them reaches a repository, an allocator, a revision writer or a
  history writer directly;
* none of them constructs a disposition, a receipt, a revision or a version;
* every one passes `authorization.principal.principal_id`, which is the only
  identity a handler may use.

The failure this exists to prevent is not a crash. It is a second answer about a
mutation — a disposition recomputed here, a version incremented here — able to
disagree with the ledger the WP06 service actually wrote, silently.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[2]
SOURCE: Final = ROOT / "src" / "my_pa" / "application" / "service.py"

#: Handler name to the single `ConstraintManagementService` method it may call.
HANDLERS: Final[dict[str, str]] = {
    "_constraints_create": "create_draft",
    "_constraints_publish": "publish",
    "_constraints_update": "update",
    "_constraints_transition": "transition_active",
    "_constraints_close": "close",
    "_constraints_close_follow_up": "close_with_follow_up",
    "_constraints_void": "void",
    "_constraints_reopen": "reopen",
    "_constraint_categories_create": "create_category",
    "_constraint_categories_update": "update_category",
    "_constraint_categories_deactivate": "deactivate_category",
    "_constraint_categories_reorder": "reorder_categories",
}

#: Names a handler must not call. Each is a way of doing the plane's own work in
#: the wrong file: reaching persistence, minting a receipt, or building a record.
FORBIDDEN_CALLS: Final[frozenset[str]] = frozenset(
    {
        "insert_constraint",
        "update_constraint",
        "insert_revision",
        "insert_history",
        "insert_category",
        "update_category_row",
        "insert_category_history",
        "insert_relationship",
        "get_for_update",
        "get_category_for_update",
        "find_history_by_idempotency_key",
        "find_category_history_by_idempotency_key",
        "record_constraint_mutation",
        "record_category_mutation",
        "next_constraint_code",
        "allocate_code",
        "revise_category",
        "publish_constraint",
    }
)

#: Types a handler must not construct: each is an authoritative value the WP06
#: service decides, and a second construction is a second answer.
FORBIDDEN_CONSTRUCTIONS: Final[frozenset[str]] = frozenset(
    {
        "ConstraintHistoryEntry",
        "ConstraintCategoryHistoryEntry",
        "ConstraintRevision",
        "ConstraintRelationship",
        "ConstraintMutationResult",
        "ConstraintCategoryMutationResult",
        "ConstraintCategoryReorderResult",
        "ConstraintFollowUpResult",
        "ProjectConstraint",
        "ConstraintCategory",
    }
)


def _module() -> ast.Module:
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


def _handler(name: str) -> ast.FunctionDef:
    for node in ast.walk(_module()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not defined in {SOURCE.name}")


def _attribute_calls(body: ast.AST) -> list[str]:
    return [
        node.func.attr
        for node in ast.walk(body)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]


def test_every_authoring_capability_has_a_handler_in_this_file() -> None:
    """The map above is not a subset anyone can shrink without noticing."""
    assert len(HANDLERS) == 12
    for name in HANDLERS:
        assert _handler(name) is not None


@pytest.mark.parametrize(("handler", "method"), sorted(HANDLERS.items()))
def test_each_handler_calls_exactly_one_mutation_service_method(handler: str, method: str) -> None:
    body = _handler(handler)
    calls = _attribute_calls(body)
    assert calls.count(method) == 1, f"{handler} does not call {method} exactly once"
    reached = [name for name in calls if name in set(HANDLERS.values())]
    assert reached == [method], f"{handler} reaches {reached}"


@pytest.mark.parametrize("handler", sorted(HANDLERS))
def test_each_handler_resolves_the_service_through_the_composition_seam(handler: str) -> None:
    """`_constraint_mutations()` is what answers `unsupported` for an unwired build."""
    calls = _attribute_calls(_handler(handler))
    assert calls.count("_constraint_mutations") == 1


@pytest.mark.parametrize("handler", sorted(HANDLERS))
def test_no_handler_reaches_persistence_or_the_allocator(handler: str) -> None:
    offending = sorted(set(_attribute_calls(_handler(handler))) & FORBIDDEN_CALLS)
    assert offending == [], f"{handler} reaches {offending} instead of the WP06 service"


@pytest.mark.parametrize("handler", sorted(HANDLERS))
def test_no_handler_constructs_an_authoritative_value(handler: str) -> None:
    built = sorted(
        {
            node.func.id
            for node in ast.walk(_handler(handler))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        & FORBIDDEN_CONSTRUCTIONS
    )
    assert built == [], f"{handler} builds {built}, which the mutation service decides"


@pytest.mark.parametrize("handler", sorted(HANDLERS))
def test_no_handler_does_version_arithmetic(handler: str) -> None:
    """A `+ 1` on a version here would be a second opinion about the ledger."""
    for node in ast.walk(_handler(handler)):
        if not isinstance(node, ast.BinOp):
            continue
        rendered = ast.unparse(node)
        assert "version" not in rendered, f"{handler} computes {rendered}"


@pytest.mark.parametrize("handler", sorted(HANDLERS))
def test_each_handler_takes_its_principal_from_the_authorization(handler: str) -> None:
    """The only identity a handler may use, and never a command or envelope field."""
    rendered = ast.unparse(_handler(handler))
    assert "principal_id=authorization.principal.principal_id" in rendered
    assert "metadata.principal_id" not in rendered
    assert "command.principal_id" not in rendered


@pytest.mark.parametrize("handler", sorted(HANDLERS))
def test_each_handler_names_the_actor_rather_than_accepting_one(handler: str) -> None:
    """`actor` is transport-derived: a caller cannot claim SYSTEM or ASSISTANT."""
    rendered = ast.unparse(_handler(handler))
    assert "actor=ConstraintMutationActor.PRINCIPAL" in rendered
    assert "command.actor" not in rendered
