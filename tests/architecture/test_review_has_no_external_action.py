"""Review disposition has no source-system or external-action authority."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import my_pa.infrastructure.persistence.review as review_module
from my_pa.contracts.ports import ReviewRepository

#: The two the surface is *for*: one listing and one disposition.
THE_SURFACE: Final = frozenset({"cases", "decide"})

#: The Entity plane's own case read and decision ledger (`WP-RI-B-05`).
#:
#: Named rather than admitted by a pattern, so the exact accounting this module
#: has always given survives: a method added to `ReviewRepository` still reddens
#: the build until somebody writes it down here. What each one is, is storage —
#: reading the case, reading and appending its decision ledger, and the two
#: guarded `UPDATE`s an invalidation and a reprocess need. None of them acts on
#: anything outside this repository, which is what the module is called for.
#:
#: They exist on this port rather than inside `decide` because an accepted
#: Entity proposal is executed through the canonical Phase A mutation services,
#: which live in the application layer and which infrastructure may not import.
#: The other three subject kinds decide entirely in SQL and so need none of this.
THE_ENTITY_PLANES_STORAGE: Final = frozenset(
    {
        "entity_proposal_case",
        "entity_proposal_decision",
        "entity_proposal_decisions",
        "record_entity_proposal_decision",
        "invalidate_entity_proposal",
        "supersede_entity_proposal",
        "name_entity_proposal_successor",
    }
)

#: What a method on this port must never be named after, and the point of the
#: module: a review disposition creates canonical product-owned records and
#: receipts, never an external action. Checked against the names *and* the
#: annotations, because a method called `record_x` whose argument type is a
#: reminder is the same defect as one called `send_reminder`.
EXTERNAL_ACTION_TOKENS: Final = (
    "send",
    "notify",
    "deliver",
    "dispatch",
    "email",
    "calendar",
    "reminder",
    "webhook",
    "publish",
    "http",
    "provider",
)


def test_the_review_port_exposes_only_listing_and_disposition() -> None:
    public = {
        name
        for name, value in vars(ReviewRepository).items()
        if callable(value) and not name.startswith("_")
    }
    assert public == THE_SURFACE | THE_ENTITY_PLANES_STORAGE


def test_no_method_on_the_review_port_names_an_external_action() -> None:
    """The rule this module is named for, said directly rather than by counting.

    The assertion above is exact and is what stops a method being added without
    a reader noticing. This is what stops the *wrong* method being added and
    written down: whatever the port grows, none of it may be named after — or
    typed with — something outside this repository.
    """
    named: list[str] = []
    for name, value in vars(ReviewRepository).items():
        if not callable(value) or name.startswith("_"):
            continue
        surface = f"{name} {getattr(value, '__annotations__', {})}".lower()
        named.extend(
            f"{name} names {token}" for token in EXTERNAL_ACTION_TOKENS if token in surface
        )
    assert not named, (
        f"{named}: a review disposition creates canonical product-owned records "
        "and receipts, never an external action"
    )


def test_review_persistence_imports_no_provider_or_external_client() -> None:
    path = Path(review_module.__file__).resolve()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    forbidden = ("provider", "http", "requests", "reminder", "calendar", "email")
    assert not {name for name in imported if any(token in name.lower() for token in forbidden)}
