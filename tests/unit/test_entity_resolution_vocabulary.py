"""The resolution match-reason vocabulary, and the safety rule read off it.

RI-ENT-WP-09 adds two match reasons (`TYPED_NAME`, `COMMUNICATION_VALUE`) and
two contextual signals, and in the same move takes the domain's central safety
refusal off the presentation order it had been reading.

That refusal used to be `strongest_basis is ResolutionBasis.CANONICAL_NAME`,
which was correct only because `CANONICAL_NAME` happened to sort last in
`_BASIS_ORDER`. It is now `ResolutionCandidate.names_the_entity`, an explicit
membership test against `_BASES_THAT_NAME_AN_ENTITY`. The two formulations
coincide exactly over the vocabulary as it stood before this work package, and
this module **proves** that over every non-empty combination of the four
pre-existing bases rather than asserting it -- because "behaviour-preserving"
is the whole claim the refactor rests on, and a claim about a safety refusal is
worth what it is checked against.

It then pins the half that is deliberately *not* preserved: the two new bases
name no entity, so neither can produce a resolved outcome on its own. That is
audit section M's rule, "name/alias alone -> retrieval candidates, never
automatic merge", and it is the reason the new members were appended at the weak
end of `_BASIS_ORDER` rather than placed anywhere a `strongest_basis` could move
because of them.
"""

from __future__ import annotations

from itertools import combinations

import pytest

from my_pa.domain.relationship.entity import EntityStatus, EntityType
from my_pa.domain.relationship.resolution import (
    ContextualSignal,
    EntityResolution,
    ResolutionBasis,
    ResolutionCandidate,
    ResolutionEvidence,
    ResolutionOutcome,
    ResolutionWarning,
    order_candidates,
)

ALICE = "ent_aaaa0001aaaa0001aaaa0001"
ALICE_TWO = "ent_bbbb0002bbbb0002bbbb0002"

#: The four bases as they stood at `50d2e5b`, before RI-ENT-WP-09 appended two
#: more. Written out rather than derived from `ResolutionBasis`, so the
#: equivalence below keeps measuring the vocabulary the old formulation was
#: correct for even as the vocabulary grows past it.
BASES_BEFORE_WP09 = (
    ResolutionBasis.VERIFIED_EXTERNAL_IDENTIFIER,
    ResolutionBasis.EXTERNAL_IDENTIFIER,
    ResolutionBasis.ALIAS,
    ResolutionBasis.CANONICAL_NAME,
)

#: `_BASIS_ORDER` as it stood at `50d2e5b`, likewise written out. Appending at
#: the weak end is only safe if every one of these positions is unchanged, and
#: a copy of the old map is the only way to say so without reading the new one.
ORDER_BEFORE_WP09 = {
    ResolutionBasis.VERIFIED_EXTERNAL_IDENTIFIER: 0,
    ResolutionBasis.EXTERNAL_IDENTIFIER: 1,
    ResolutionBasis.ALIAS: 2,
    ResolutionBasis.CANONICAL_NAME: 3,
}

#: Every non-empty combination of the four pre-existing bases, as an evidence
#: set. Fifteen of them, which is small enough to enumerate and therefore small
#: enough to leave nothing to a representative example.
COMBINATIONS_BEFORE_WP09 = tuple(
    combination
    for size in range(1, len(BASES_BEFORE_WP09) + 1)
    for combination in combinations(BASES_BEFORE_WP09, size)
)


def a_candidate(
    *bases: ResolutionBasis,
    entity_id: str = ALICE,
    status: EntityStatus = EntityStatus.ACTIVE,
) -> ResolutionCandidate:
    return ResolutionCandidate(
        entity_id=entity_id,
        entity_type=EntityType.PERSON,
        display_name="Alice Synthetic",
        status=status,
        evidence=tuple(
            ResolutionEvidence(
                basis=basis,
                matched_value="alice synthetic",
                verified=basis is ResolutionBasis.VERIFIED_EXTERNAL_IDENTIFIER,
            )
            for basis in bases
        ),
        superseded_by_entity_id=ALICE_TWO if status is EntityStatus.MERGED_REDIRECT else None,
    )


# --- the refactor is behaviour-preserving, demonstrated ----------------------


@pytest.mark.parametrize("bases", COMBINATIONS_BEFORE_WP09, ids=lambda bases: "+".join(bases))
def test_naming_the_entity_agrees_with_the_ordering_test_it_replaced(
    bases: tuple[ResolutionBasis, ...],
) -> None:
    """The equivalence, over all fifteen combinations of the four old bases.

    `strongest_basis is CANONICAL_NAME` held exactly when *every* piece of
    evidence was a canonical name, because `CANONICAL_NAME` was the weakest
    member and `strongest_basis` is a minimum. `names_the_entity` asks the same
    question directly. Over the old vocabulary the two answers are the same
    answer, which is what makes replacing one with the other a refactor rather
    than a change.
    """
    candidate = a_candidate(*bases)
    was_a_bare_name = candidate.strongest_basis is ResolutionBasis.CANONICAL_NAME
    assert candidate.names_the_entity is not was_a_bare_name


@pytest.mark.parametrize("bases", COMBINATIONS_BEFORE_WP09, ids=lambda bases: "+".join(bases))
@pytest.mark.parametrize(
    "outcome", [ResolutionOutcome.RESOLVED_EXACT, ResolutionOutcome.HISTORICAL_MATCH]
)
def test_the_refusal_itself_is_unchanged_for_every_old_combination(
    bases: tuple[ResolutionBasis, ...], outcome: ResolutionOutcome
) -> None:
    """The equivalence again, at the level that matters: the constructor's answer.

    The property above could hold while the refusal was wired to it wrongly, so
    this asserts the observable behaviour -- whether `EntityResolution` refuses
    -- against what the replaced formulation would have decided, for both
    outcomes the refusal guards.
    """
    status = (
        EntityStatus.ACTIVE
        if outcome is ResolutionOutcome.RESOLVED_EXACT
        else EntityStatus.ARCHIVED
    )
    candidates = (a_candidate(*bases, status=status),)
    would_have_refused = candidates[0].strongest_basis is ResolutionBasis.CANONICAL_NAME
    if would_have_refused:
        with pytest.raises(ValueError, match="a name alone does not resolve an entity"):
            EntityResolution(outcome=outcome, candidates=candidates)
    else:
        assert EntityResolution(outcome=outcome, candidates=candidates).outcome is outcome


@pytest.mark.parametrize("bases", COMBINATIONS_BEFORE_WP09, ids=lambda bases: "+".join(bases))
def test_appending_left_every_existing_candidates_strongest_basis_identical(
    bases: tuple[ResolutionBasis, ...],
) -> None:
    """Nothing an existing candidate would have been presented as has moved.

    `strongest_basis` is the minimum of `_BASIS_ORDER` over the evidence, so a
    new member placed above `ALIAS` would have changed it for every candidate
    that matched both. This recomputes it from the pre-WP-09 map and requires
    the same member.
    """
    expected = min(bases, key=lambda basis: ORDER_BEFORE_WP09[basis])
    assert a_candidate(*bases).strongest_basis is expected


def test_the_presentation_order_of_two_old_candidates_is_unchanged() -> None:
    """The tie-break is a tie-break, and the appended members did not disturb it."""
    stronger = a_candidate(ResolutionBasis.ALIAS, entity_id=ALICE_TWO)
    weaker = a_candidate(ResolutionBasis.CANONICAL_NAME, entity_id=ALICE)
    assert order_candidates((weaker, stronger)) == (stronger, weaker)


# --- and what is deliberately not preserved: the new bases resolve nothing ---


def test_the_vocabulary_carries_exactly_the_expected_match_reasons() -> None:
    """A closed vocabulary, stated once so a silent addition is visible here."""
    assert [basis.value for basis in ResolutionBasis] == [
        "verified_external_identifier",
        "external_identifier",
        "alias",
        "canonical_name",
        "typed_name",
        "communication_value",
    ]


@pytest.mark.parametrize("basis", [ResolutionBasis.TYPED_NAME, ResolutionBasis.COMMUNICATION_VALUE])
@pytest.mark.parametrize(
    "outcome", [ResolutionOutcome.RESOLVED_EXACT, ResolutionOutcome.HISTORICAL_MATCH]
)
def test_a_new_basis_cannot_resolve_an_entity_on_its_own(
    basis: ResolutionBasis, outcome: ResolutionOutcome
) -> None:
    """Audit section M: name/alias alone yields retrieval candidates, never a merge.

    A typed name is a name, and a communication value is a value more than one
    entity may claim. Neither is an identifier this product verified, so neither
    may produce a resolved answer however the service is later written.
    """
    status = (
        EntityStatus.ACTIVE
        if outcome is ResolutionOutcome.RESOLVED_EXACT
        else EntityStatus.ARCHIVED
    )
    with pytest.raises(ValueError, match="a name alone does not resolve an entity"):
        EntityResolution(outcome=outcome, candidates=(a_candidate(basis, status=status),))


@pytest.mark.parametrize("basis", [ResolutionBasis.TYPED_NAME, ResolutionBasis.COMMUNICATION_VALUE])
def test_a_new_basis_is_a_candidate_and_says_it_named_nobody(basis: ResolutionBasis) -> None:
    """The other half: it is real evidence, it is just not evidence that resolves."""
    candidate = a_candidate(basis)
    assert candidate.names_the_entity is False
    assert (
        EntityResolution(
            outcome=ResolutionOutcome.AMBIGUOUS, candidates=(candidate,)
        ).resolved_entity_id
        is None
    )


@pytest.mark.parametrize("basis", [ResolutionBasis.TYPED_NAME, ResolutionBasis.COMMUNICATION_VALUE])
def test_a_new_basis_alongside_an_identifier_still_resolves(basis: ResolutionBasis) -> None:
    """Weak evidence beside strong evidence subtracts nothing.

    `names_the_entity` asks whether *any* evidence named the entity, so an
    identifier match that also matched a typed name resolves exactly as it did
    before the typed name was observable at all.
    """
    candidate = a_candidate(ResolutionBasis.VERIFIED_EXTERNAL_IDENTIFIER, basis)
    assert candidate.names_the_entity is True
    answer = EntityResolution(outcome=ResolutionOutcome.RESOLVED_EXACT, candidates=(candidate,))
    assert answer.resolved_entity_id == ALICE


def test_a_new_basis_is_presented_after_every_basis_that_names_an_entity() -> None:
    """The appended members sort at the weak end, which is where they were put."""
    naming = a_candidate(ResolutionBasis.ALIAS, entity_id=ALICE)
    typed = a_candidate(ResolutionBasis.TYPED_NAME, entity_id=ALICE_TWO)
    assert order_candidates((typed, naming)) == (naming, typed)


# --- the contextual signals -------------------------------------------------


def test_the_signal_vocabulary_carries_exactly_the_expected_signals() -> None:
    assert [signal.value for signal in ContextualSignal] == [
        "assigned_to_the_named_scope",
        "related_to_the_named_scope",
        "affiliated_with_the_named_scope",
        "participates_in_the_named_scope",
    ]


@pytest.mark.parametrize(
    "signal",
    [
        ContextualSignal.AFFILIATED_WITH_THE_NAMED_SCOPE,
        ContextualSignal.PARTICIPATES_IN_THE_NAMED_SCOPE,
    ],
)
def test_a_new_signal_corroborates_a_candidate_without_resolving_it(
    signal: ContextualSignal,
) -> None:
    """A signal supports a candidate; it never turns a bare name into an answer.

    The candidate below matched on a typed name and is corroborated by the new
    signal, and it is still refused as a resolved outcome. Corroboration and
    naming are separate questions, which is the distinction `ContextualSignal`
    exists to keep.
    """
    candidate = a_candidate(ResolutionBasis.TYPED_NAME)
    corroborated = ResolutionCandidate(
        entity_id=candidate.entity_id,
        entity_type=candidate.entity_type,
        display_name=candidate.display_name,
        status=candidate.status,
        evidence=candidate.evidence,
        signals=(signal,),
    )
    assert corroborated.is_corroborated is True
    assert corroborated.names_the_entity is False
    with pytest.raises(ValueError, match="a name alone does not resolve an entity"):
        EntityResolution(outcome=ResolutionOutcome.RESOLVED_EXACT, candidates=(corroborated,))


def test_a_new_signal_may_select_a_candidate_a_supplied_scope_narrowed_to() -> None:
    """`RESOLVED_CONTEXTUAL` is not guarded by the naming refusal, and stays so.

    The refusal covers `RESOLVED_EXACT` and `HISTORICAL_MATCH` only: a scope the
    caller supplied is evidence the caller brought, and section 15.1 admits
    exactly that. This pins that the appended members did not quietly widen the
    refusal onto the contextual outcome.
    """
    candidate = ResolutionCandidate(
        entity_id=ALICE,
        entity_type=EntityType.PERSON,
        display_name="Alice Synthetic",
        status=EntityStatus.ACTIVE,
        evidence=(
            ResolutionEvidence(basis=ResolutionBasis.TYPED_NAME, matched_value="alice synthetic"),
        ),
        signals=(ContextualSignal.PARTICIPATES_IN_THE_NAMED_SCOPE,),
    )
    answer = EntityResolution(
        outcome=ResolutionOutcome.RESOLVED_CONTEXTUAL,
        candidates=(candidate,),
        warnings=(ResolutionWarning.NARROWED_BY_SUPPLIED_SCOPE,),
    )
    assert answer.resolved_entity_id == ALICE
