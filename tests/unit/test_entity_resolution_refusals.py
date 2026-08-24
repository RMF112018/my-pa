"""What a recorded refusal does to the next resolution, and what it must not do.

A user who says "this mention is not that person" has said something durable,
and this module is the whole of what the resolver does with it: the refused
entity stops being offered. What the refusal must **not** do is make anything
else easier to resolve — a rejection is evidence against one pairing and
evidence for nothing, and the failure this module exists to prevent is a refusal
that turns two same-named candidates into a lone match the contextual rule then
lifts out of `AMBIGUOUS`.

So the filter is applied to the finished answer. `_by_name` and `_name_outcome`
never see the refusals, which means their decision — one candidate is not by
itself a resolution, a bare name is never an identifier, truncation is always
ambiguous — is the same decision it would have been, and removal can only take
candidates away from it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.application.entity_resolution import EntityResolutionService, ResolutionRequest
from my_pa.domain.relationship.entity import (
    AliasType,
    Entity,
    EntityAlias,
    EntityStatus,
    EntityType,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.relationship.resolution import ResolutionOutcome, ResolutionWarning
from tests.conftest import FakeUnitOfWork, World

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
ALICE = "ent_aaaa0001aaaa0001"
ALICE_TWO = "ent_bbbb0002bbbb0002"
WHEN = datetime(2026, 8, 18, 12, tzinfo=UTC)
REFERENCE = "Alice Chen"


def an_entity(entity_id: str, name: str = REFERENCE) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=PRINCIPAL,
        entity_type=EntityType.PERSON,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


def _resolve(world: World, *, refused: frozenset[str] = frozenset()):  # noqa: ANN202
    return EntityResolutionService(FakeUnitOfWork(world).entities).resolve(
        PRINCIPAL,
        ResolutionRequest(raw_reference=REFERENCE, at=WHEN, refused_entity_ids=refused),
    )


@pytest.fixture
def two_of_them(world: World) -> World:
    """Two people carrying one name, which is `AMBIGUOUS` and stays that way."""
    entities = FakeUnitOfWork(world).entities
    entities.create(PRINCIPAL, an_entity(ALICE))
    entities.create(PRINCIPAL, an_entity(ALICE_TWO))
    return world


@pytest.fixture
def one_named_alias(world: World) -> World:
    """One entity that names itself by alias, which resolves on its own."""
    entities = FakeUnitOfWork(world).entities
    entities.create(PRINCIPAL, an_entity(ALICE, "Someone Else"))
    entities.record_alias(
        PRINCIPAL,
        EntityAlias(
            alias_id="eals_aaaa0001aaaa01",
            entity_id=ALICE,
            principal_id=PRINCIPAL,
            alias_type=AliasType.PREFERRED_NAME,
            normalized_value=normalize_name(REFERENCE),
            display_value=REFERENCE,
        ),
    )
    return world


# --- the refusal takes candidates away and never adds evidence ----------------


def test_without_a_refusal_two_same_named_entities_are_ambiguous(two_of_them: World) -> None:
    """The baseline every assertion below is measured against."""
    answer = _resolve(two_of_them)
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert {candidate.entity_id for candidate in answer.candidates} == {ALICE, ALICE_TWO}


def test_refusing_one_of_two_leaves_the_other_ambiguous_rather_than_resolved(
    two_of_them: World,
) -> None:
    """**The defect this design exists to prevent.**

    Folding the refusal into the candidate set before the count is taken would
    make the survivor a lone match, and a lone match with a corroborating signal
    or a supplied scope is a `RESOLVED_CONTEXTUAL`. The user said who this is
    *not*; that is not evidence of who it is.
    """
    answer = _resolve(two_of_them, refused=frozenset({ALICE}))
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert [candidate.entity_id for candidate in answer.candidates] == [ALICE_TWO]
    assert ResolutionWarning.A_REFUSED_PAIRING_WAS_WITHHELD in answer.warnings
    assert ResolutionWarning.NARROWED_BY_SUPPLIED_SCOPE not in answer.warnings


def test_ambiguity_never_picks_the_first_candidate(two_of_them: World) -> None:
    """Asserted from both directions, so ordering cannot be what decides it."""
    for refused in (ALICE, ALICE_TWO):
        answer = _resolve(two_of_them, refused=frozenset({refused}))
        assert answer.outcome is ResolutionOutcome.AMBIGUOUS
        assert answer.resolved_entity_id is None


def test_refusing_every_candidate_answers_not_found(two_of_them: World) -> None:
    """Which is the only outcome that licenses a `create_new`, and honestly so."""
    answer = _resolve(two_of_them, refused=frozenset({ALICE, ALICE_TWO}))
    assert answer.outcome is ResolutionOutcome.NOT_FOUND
    assert answer.candidates == ()
    assert ResolutionWarning.A_REFUSED_PAIRING_WAS_WITHHELD in answer.warnings


def test_a_refusal_of_a_resolution_withdraws_it_entirely(one_named_alias: World) -> None:
    """A resolved answer carries exactly one candidate, so refusing it leaves none."""
    resolved = _resolve(one_named_alias)
    assert resolved.outcome is ResolutionOutcome.RESOLVED_EXACT
    assert resolved.resolved_entity_id == ALICE
    withdrawn = _resolve(one_named_alias, refused=frozenset({ALICE}))
    assert withdrawn.outcome is ResolutionOutcome.NOT_FOUND
    assert withdrawn.resolved_entity_id is None


def test_a_refusal_of_something_absent_changes_nothing(one_named_alias: World) -> None:
    """No warning either: an answer that never carried the pairing withheld nothing."""
    answer = _resolve(one_named_alias, refused=frozenset({ALICE_TWO}))
    assert answer.outcome is ResolutionOutcome.RESOLVED_EXACT
    assert answer.resolved_entity_id == ALICE
    assert ResolutionWarning.A_REFUSED_PAIRING_WAS_WITHHELD not in answer.warnings


def test_a_bare_name_is_never_an_identity_however_few_carry_it(world: World) -> None:
    """The rule the refusal filter must not create a way around.

    One entity, one canonical-name match, nothing refused and nothing supplied:
    still `AMBIGUOUS`, because uniqueness is a fact about the database rather
    than about the person.
    """
    FakeUnitOfWork(world).entities.create(PRINCIPAL, an_entity(ALICE))
    answer = _resolve(world)
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert answer.resolved_entity_id is None


def test_the_refusal_set_is_validated_rather_than_accepted(world: World) -> None:
    """It names entities, and a request that named something else would be a bug."""
    with pytest.raises(Exception, match="identifier"):
        ResolutionRequest(raw_reference=REFERENCE, refused_entity_ids=frozenset({"not-an-id"}))
