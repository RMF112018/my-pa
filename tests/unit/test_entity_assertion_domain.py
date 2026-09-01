"""`EntityAssertion`/`EntityAssertionEvidence` invariants, without persistence
(RI-ENT-WP-07).

Every rule asserted here is also a CHECK constraint in `1cda4d536268`; the
database half lives in `tests/database/test_entity_assertion_provenance.py`,
and the schema half in
`tests/schema/test_entity_assertion_provenance_migration.py`. This module
proves only what a dataclass can prove, on the same argument every prior
RI-ENT unit-domain module states for its own record family -- plus RULING 1's
own behavioural proof that `AssertionStatus` is a plain, unordered `StrEnum`
nothing in this codebase sorts, compares, or weights.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Final

import pytest

from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.relationship.governance import (
    AssertionStatus,
    EntityAssertion,
    EntityAssertionEvidence,
    EntityAssertionState,
    EvidenceRole,
    MutationAuthority,
)

ROOT: Final = Path(__file__).resolve().parents[2]

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
ASSERTION_ID = "east_aaaa0001aaaa0001"
OTHER_ASSERTION_ID = "east_bbbb0002bbbb0002"
EVIDENCE_ID = "easev_aaaa0001aaaa0001"

NAME_ID = "enam_aaaa0001aaaa0001"
ADDRESS_ID = "eadr_aaaa0001aaaa0001"
COMMUNICATION_METHOD_ID = "ecmm_aaaa0001aaaa0001"
PARTICIPATION_ID = "eppt_aaaa0001aaaa0001"
AFFILIATION_ID = "poaf_aaaa0001aaaa0001"
ORGANIZATION_ENTITY_ID = "ent_aaaa0001aaaa0001"

OBSERVATION_ID = "eobs_aaaa0001aaaa0001"

WHEN = datetime(2026, 8, 31, 12, tzinfo=UTC)
LATER = WHEN + timedelta(hours=1)


def an_assertion(**overrides: object) -> EntityAssertion:
    fields: dict[str, object] = {
        "assertion_id": ASSERTION_ID,
        "principal_id": PRINCIPAL,
        "assertion_status": AssertionStatus.BEST_SUPPORTED,
        "asserted_by": MutationAuthority.USER_CONFIRMED_ASSERTION,
        "created_at": WHEN,
        "target_entity_name_id": NAME_ID,
    }
    return EntityAssertion(**{**fields, **overrides})  # type: ignore[arg-type]


def evidence_for(**overrides: object) -> EntityAssertionEvidence:
    fields: dict[str, object] = {
        "evidence_id": EVIDENCE_ID,
        "principal_id": PRINCIPAL,
        "assertion_id": ASSERTION_ID,
        "role": EvidenceRole.DIRECT,
        "created_at": WHEN,
        "entity_observation_id": OBSERVATION_ID,
    }
    return EntityAssertionEvidence(**{**fields, **overrides})  # type: ignore[arg-type]


# --- construction and defaults ----------------------------------------------


def test_an_assertion_defaults_to_active_state_and_version_one() -> None:
    assertion = an_assertion()
    assert assertion.state is EntityAssertionState.ACTIVE
    assert assertion.version == 1
    assert assertion.supersedes_assertion_id is None
    assert assertion.updated_at is None
    assert assertion.retired_at is None


def test_an_assertion_rejects_an_unknown_identifier_kind() -> None:
    with pytest.raises(InvalidIdentifierError):
        an_assertion(assertion_id="xid_aaaa0001aaaa0001")
    with pytest.raises(InvalidIdentifierError):
        an_assertion(principal_id=NAME_ID)


# --- exactly one target -------------------------------------------------------


def test_an_assertion_names_exactly_one_target_and_no_targets_is_refused() -> None:
    with pytest.raises(ValueError, match="exactly one target"):
        an_assertion(target_entity_name_id=None)


def test_an_assertion_names_exactly_one_target_and_two_targets_is_refused() -> None:
    with pytest.raises(ValueError, match="exactly one target"):
        an_assertion(target_entity_name_id=NAME_ID, target_entity_address_id=ADDRESS_ID)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_entity_name_id", NAME_ID),
        ("target_entity_address_id", ADDRESS_ID),
        ("target_communication_method_id", COMMUNICATION_METHOD_ID),
        ("target_participation_id", PARTICIPATION_ID),
        ("target_affiliation_id", AFFILIATION_ID),
        ("target_organization_profile_entity_id", ORGANIZATION_ENTITY_ID),
    ],
)
def test_an_assertion_admits_exactly_one_of_each_of_the_six_targets(field: str, value: str) -> None:
    assertion = an_assertion(**{"target_entity_name_id": None, field: value})
    assert getattr(assertion, field) == value


def test_an_assertion_organization_profile_target_uses_the_entity_id_kind() -> None:
    """`target_organization_profile_entity_id` names `entity_organization_profiles`'
    row by `entity_id` -- that table's own primary key (see
    `EntityOrganizationProfile`'s docstring) -- so it validates against
    `IdKind.ENTITY`, not a dedicated organization-profile prefix."""
    with pytest.raises(InvalidIdentifierError):
        an_assertion(
            target_entity_name_id=None,
            target_organization_profile_entity_id=NAME_ID,
        )


# --- predicate_code / rationale ----------------------------------------------


def test_an_assertion_predicate_code_may_be_null_meaning_the_whole_record() -> None:
    assertion = an_assertion(predicate_code=None)
    assert assertion.predicate_code is None


def test_an_assertion_predicate_code_is_not_blank_when_present() -> None:
    with pytest.raises(ValueError, match="predicate code is not blank"):
        an_assertion(predicate_code="   ")


def test_an_assertion_rationale_is_not_blank_when_present() -> None:
    with pytest.raises(ValueError, match="rationale is not blank"):
        an_assertion(rationale="  ")


def test_an_assertion_rationale_is_bounded() -> None:
    with pytest.raises(ValueError, match="rationale is bounded"):
        an_assertion(rationale="x" * 501)


# --- never infer provenance a source did not state (RULING 3) ----------------


def test_an_assertion_with_unknown_source_is_unresolved_not_a_guess() -> None:
    """RULING 3: when the source of an assertion is unknown, `assertion_status`
    is `UNRESOLVED` -- never a stronger value dressed up as a guess. Nothing in
    the dataclass forces this (it cannot know what a caller does not tell it),
    so this test proves the vocabulary at least admits the honest answer and
    that `UNRESOLVED` construction succeeds with no other field populated."""
    assertion = an_assertion(
        assertion_status=AssertionStatus.UNRESOLVED,
        observed_at=None,
        verified_at=None,
        rationale=None,
    )
    assert assertion.assertion_status is AssertionStatus.UNRESOLVED


# --- supersession (backward-pointing, non-destructive) -----------------------


def test_an_assertion_supersedes_field_points_backward_to_the_older_assertion() -> None:
    newer = an_assertion(
        assertion_id=OTHER_ASSERTION_ID,
        assertion_status=AssertionStatus.VERIFIED,
        created_at=LATER,
        supersedes_assertion_id=ASSERTION_ID,
    )
    assert newer.supersedes_assertion_id == ASSERTION_ID
    assert newer.assertion_id != newer.supersedes_assertion_id


def test_an_assertion_does_not_supersede_itself() -> None:
    with pytest.raises(ValueError, match="does not supersede itself"):
        an_assertion(supersedes_assertion_id=ASSERTION_ID)


def test_an_assertion_is_retired_only_once_it_leaves_service() -> None:
    with pytest.raises(ValueError, match="retired only once it leaves service"):
        an_assertion(retired_at=WHEN, state=EntityAssertionState.ACTIVE)
    retired = an_assertion(retired_at=WHEN, state=EntityAssertionState.RETIRED)
    assert retired.retired_at == WHEN


def test_an_assertion_version_is_positive() -> None:
    with pytest.raises(ValueError, match="version is a positive integer"):
        an_assertion(version=0)


# --- EntityAssertionEvidence ---------------------------------------------------


def test_assertion_evidence_names_exactly_one_record() -> None:
    with pytest.raises(ValueError, match="exactly one record"):
        evidence_for(entity_observation_id=None)
    with pytest.raises(ValueError, match="exactly one record"):
        evidence_for(entity_observation_id=OBSERVATION_ID, capture_span_id="span_aaaa0001aaaa0001")


def test_assertion_evidence_role_is_closed() -> None:
    evidence = evidence_for(role=EvidenceRole.COUNTEREVIDENCE)
    assert evidence.role is EvidenceRole.COUNTEREVIDENCE


def test_assertion_evidence_source_locator_is_optional_and_bounded() -> None:
    assert evidence_for(source_locator=None).source_locator is None
    with pytest.raises(ValueError, match="source locator is not blank"):
        evidence_for(source_locator="  ")
    with pytest.raises(ValueError, match="source locator is bounded"):
        evidence_for(source_locator="x" * 501)


# --- RULING 1: AssertionStatus is a plain StrEnum, never ordered -------------


def test_assertion_status_is_a_plain_strenum_not_an_intenum() -> None:
    assert issubclass(AssertionStatus, StrEnum)
    assert not issubclass(AssertionStatus, IntEnum)
    # No custom rich-comparison dunder was added to carry an ordering under a
    # different name.
    for name in ("__lt__", "__le__", "__gt__", "__ge__"):
        assert getattr(AssertionStatus, name) is getattr(StrEnum, name), (
            f"AssertionStatus defines its own {name}, which is exactly the "
            "ordering RULING 1 forbids"
        )


def test_assertion_status_has_the_audits_seven_unordered_members() -> None:
    assert {member.value for member in AssertionStatus} == {
        "verified",
        "best_supported",
        "inferred",
        "unresolved",
        "awaiting_confirmation",
        "contradicted",
        "superseded",
    }


#: Every module this revision's `AssertionStatus`/`assertion_status` code
#: could plausibly appear in -- walked by AST rather than trusted by
#: inspection, so a comparison introduced anywhere in this set reddens here
#: rather than being caught only by luck. Deliberately the whole `src/` and
#: `tests/` tree, on the same "do not just declare the rule, walk the tree"
#: argument `test_relationship_scoring_surface_is_denied` itself already
#: uses for its own scan.
_SCAN_ROOTS: Final = (ROOT / "src", ROOT / "tests")

_COMPARISON_OPERATORS: Final = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)


def _mentions_assertion_status(node: ast.expr) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and "assertion_status" in sub.id.lower():
            return True
        if isinstance(sub, ast.Attribute) and "assertion_status" in sub.attr.lower():
            return True
    return False


def test_nothing_in_the_repository_orders_or_compares_assertion_status() -> None:
    """RULING 1, proved behaviourally rather than merely declared.

    Walks the AST of every `.py` file under `src/` and `tests/` for an
    `ast.Compare` node using `<`, `<=`, `>`, or `>=` where either side of the
    comparison textually names `assertion_status` (a variable, attribute, or
    dict/mapping key referencing it) -- the exact shape a graded-scale misuse
    would take (`if a.assertion_status < b.assertion_status`, `sorted(rows,
    key=lambda r: r.assertion_status)` uses no comparison operator directly
    but `min`/`max`/`sorted` over the raw enum would still surface as a
    `Compare` node wherever a caller manually orders two values, which is the
    shape this scan is built to catch).
    """
    violations: list[str] = []
    for root in _SCAN_ROOTS:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                if not any(isinstance(op, _COMPARISON_OPERATORS) for op in node.ops):
                    continue
                operands = (node.left, *node.comparators)
                if any(_mentions_assertion_status(operand) for operand in operands):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == [], (
        f"{violations} order or compare `assertion_status` with <, <=, >, or >=. "
        "AssertionStatus is a set of unordered epistemic categories, not a "
        "graded scale (RULING 1) -- see AssertionStatus's own docstring"
    )
