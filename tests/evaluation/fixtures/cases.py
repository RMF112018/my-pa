"""Frozen evaluation cases. Subset of the managed-knowledge plan, synthetic only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from my_pa.domain.context.preference import ContextPreferenceCurrent
from tests.evaluation.fixtures.corpus import (
    ALMOND_CAPTURE,
    BUDGET_A,
    BUDGET_B,
    INJECT_KNOWLEDGE,
    NORTHWIND_REVIEW,
    OAT_CAPTURE,
    PRINCIPAL_A,
    SHIP_PROJECT,
    ZEPHYR_B,
    alias_preferences,
)

__all__ = ["FROZEN_CASES", "FrozenCase"]


@dataclass(frozen=True, slots=True)
class FrozenCase:
    """One frozen query and the identities that count as known evidence."""

    name: str
    family: str
    query: str
    principal_id: str
    relevant_ids: frozenset[str]
    forbidden_ids: frozenset[str] = frozenset()
    preferences: tuple[ContextPreferenceCurrent, ...] = ()
    require_return: frozenset[str] = frozenset()
    expect_empty: bool = False


FROZEN_CASES: Final[tuple[FrozenCase, ...]] = (
    FrozenCase(
        name="exact_id_northwind_review",
        family="exact_id",
        query=NORTHWIND_REVIEW,
        principal_id=PRINCIPAL_A,
        relevant_ids=frozenset({NORTHWIND_REVIEW}),
    ),
    FrozenCase(
        name="alias_skipjack",
        family="alias",
        query="Skipjack",
        principal_id=PRINCIPAL_A,
        relevant_ids=frozenset({NORTHWIND_REVIEW}),
        preferences=alias_preferences(),
    ),
    FrozenCase(
        name="paraphrase_named_entity",
        family="paraphrase",
        query="notes about the Northwind dock review",
        principal_id=PRINCIPAL_A,
        relevant_ids=frozenset({NORTHWIND_REVIEW}),
    ),
    FrozenCase(
        name="paraphrase_low_overlap",
        family="paraphrase",
        query="the Q3 status meeting notes for the northern trading programme",
        principal_id=PRINCIPAL_A,
        relevant_ids=frozenset({NORTHWIND_REVIEW}),
    ),
    FrozenCase(
        name="paraphrase_no_shared_tokens",
        family="paraphrase",
        query="how did the seasonal inspection of the loading bay go",
        principal_id=PRINCIPAL_A,
        relevant_ids=frozenset({NORTHWIND_REVIEW}),
    ),
    FrozenCase(
        name="capture_oat_milk",
        family="capture",
        query="oat milk",
        principal_id=PRINCIPAL_A,
        relevant_ids=frozenset({OAT_CAPTURE}),
    ),
    FrozenCase(
        name="continuity_ship_packet",
        family="continuity",
        query="Ship the Northwind quarterly packet",
        principal_id=PRINCIPAL_A,
        relevant_ids=frozenset({SHIP_PROJECT}),
    ),
    FrozenCase(
        name="contradiction_budget_pair",
        family="contradiction",
        query="Project Northwind budget",
        principal_id=PRINCIPAL_A,
        relevant_ids=frozenset({BUDGET_A, BUDGET_B}),
    ),
    FrozenCase(
        name="no_match_xylophone",
        family="no_match",
        query="xylophone inventory protocol",
        principal_id=PRINCIPAL_A,
        relevant_ids=frozenset(),
        expect_empty=True,
    ),
    FrozenCase(
        name="unrelated_distractors_northwind",
        family="distractors",
        query="Project Northwind quarterly review",
        principal_id=PRINCIPAL_A,
        relevant_ids=frozenset({NORTHWIND_REVIEW, SHIP_PROJECT}),
    ),
    FrozenCase(
        name="prompt_injection_as_data",
        family="prompt_injection",
        query="documents.create",
        principal_id=PRINCIPAL_A,
        relevant_ids=frozenset({INJECT_KNOWLEDGE}),
        require_return=frozenset({INJECT_KNOWLEDGE}),
    ),
    FrozenCase(
        name="cross_principal_zephyr",
        family="cross_principal",
        query="Zephyr confidential budget",
        principal_id=PRINCIPAL_A,
        relevant_ids=frozenset(),
        forbidden_ids=frozenset({ZEPHYR_B, ALMOND_CAPTURE}),
        expect_empty=True,
    ),
)
