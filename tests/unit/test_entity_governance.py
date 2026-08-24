"""Observation, proposal, and governed merge.

Organized around the thing the plane must never do: change who someone is
without a person deciding it. Every test below names a route by which that could
happen and asserts it is closed.

The merge tests are the sharp end. A merge joins two histories permanently, and
`RI-AC-039`, specification section 21.4 and `AGENTS.md` section 8.2 all put that
decision outside anything automatic — so the checks here are about *authority*
rather than about correctness of the join.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from my_pa.application.entity_governance import (
    EntityGovernanceService,
    ProposalNotOpenError,
    ReviewAuthorityError,
)
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import (
    MENTION_DISPLAY_NAME_LIMIT,
    EntityObservation,
    EntityProposalKind,
    EntityProposalMethod,
    EntityProposalState,
    ObservationKind,
    ReviewRequirement,
    requirement_for,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.relationship.proposal_payload import (
    EntityProposalPayload,
    dedupe_digest,
)
from tests.conftest import FakeUnitOfWork, World

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
OTHER = "prn_bbbb0002bbbb0002bbbb0002"
ALICE = "ent_aaaa0001aaaa0001"
ALICE_TWO = "ent_bbbb0002bbbb0002"

SOURCE = "src_aaaa0001aaaa0001"
OBJECT = "obj_aaaa0001aaaa0001"
VERSION = "ver_aaaa0001aaaa0001"

WHEN = datetime(2026, 8, 18, 12, tzinfo=UTC)
LATER = WHEN + timedelta(hours=1)


def _entities(world: World):  # noqa: ANN202
    return FakeUnitOfWork(world).entities


@pytest.fixture
def governing(world: World) -> EntityGovernanceService:
    return EntityGovernanceService(_entities(world))


def an_entity(entity_id: str, name: str = "Alice Chen", principal_id: str = PRINCIPAL) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=EntityType.PERSON,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


def an_observation(
    observation_id: str = "eobs_aaaa0001aaaa0001",
    entity_id: str | None = None,
    principal_id: str = PRINCIPAL,
) -> EntityObservation:
    return EntityObservation(
        observation_id=observation_id,
        principal_id=principal_id,
        kind=ObservationKind.MESSAGE_PARTICIPANT,
        observed_value="Alice Chen <a.chen@acme.test>",
        normalized_value=normalize_name("Alice Chen"),
        source_id=SOURCE,
        source_object_id=OBJECT,
        source_version_id=VERSION,
        observed_at=WHEN,
        recorded_at=WHEN,
        entity_id=entity_id,
    )


# --- the one field the queue publishes --------------------------------------


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("", "not blank"),
        ("   ", "no leading or trailing space"),
        ("\t", "no leading or trailing space"),
        (" Alice Chen", "no leading or trailing space"),
        ("Alice Chen ", "no leading or trailing space"),
        ("x" * (MENTION_DISPLAY_NAME_LIMIT + 1), "bounded"),
    ],
)
def test_a_disclosed_mention_name_is_refused_unless_it_is_trimmed_and_bounded(
    value: str, message: str
) -> None:
    """The record half of a bound the schema states as a CHECK.

    Both halves had to exist and neither had a test: both `raise` branches
    could be deleted with the whole suite green, on the one field
    `entities.unresolved_mentions` publishes.

    **Trimmed rather than trimmable**, because the two enforcement points must
    agree and they cannot be made to agree by trimming. Python's `str.strip()`
    removes every kind of whitespace; PostgreSQL's `trim()` removes only
    spaces. An earlier version of this bound differed in both directions: a
    tab-padded value was short enough here and too long at the server, and a
    tab-only value was blank here and acceptable there. Requiring the value to
    arrive already trimmed removes the difference rather than expressing one
    language's whitespace rule in the other's.
    """
    with pytest.raises(ValueError, match=message):
        EntityObservation(
            observation_id="eobs_bound0001bound01",
            principal_id=PRINCIPAL,
            kind=ObservationKind.MESSAGE_PARTICIPANT,
            observed_value="Alice Chen <a.chen@acme.test>",
            normalized_value=normalize_name("Alice Chen"),
            source_id=SOURCE,
            source_object_id=OBJECT,
            source_version_id=VERSION,
            observed_at=WHEN,
            recorded_at=WHEN,
            mention_display_name=value,
        )


def test_a_disclosed_mention_name_is_optional_and_defaults_to_nothing() -> None:
    """The control, and the property the column exists for.

    A writer that names nothing is not an error: the mention is queued and
    carries no text. The test above would pass against a record that refused
    every value, which would defeat the capability entirely.
    """
    assert an_observation().mention_display_name is None
    named = EntityObservation(
        observation_id="eobs_named0001named01",
        principal_id=PRINCIPAL,
        kind=ObservationKind.MESSAGE_PARTICIPANT,
        observed_value="Alice Chen <a.chen@acme.test>",
        normalized_value=normalize_name("Alice Chen"),
        source_id=SOURCE,
        source_object_id=OBJECT,
        source_version_id=VERSION,
        observed_at=WHEN,
        recorded_at=WHEN,
        mention_display_name="A. Chen",
    )
    assert named.mention_display_name == "A. Chen"


# --- an observation is not a person -----------------------------------------


def test_recording_an_observation_creates_no_entity(
    world: World, governing: EntityGovernanceService
) -> None:
    """Section 12.2, as a property of the method rather than of the caller."""
    governing.observe(PRINCIPAL, an_observation())
    assert world.entities == []
    assert len(world.entity_observations) == 1


def test_an_unlinked_observation_is_an_unresolved_mention(
    world: World, governing: EntityGovernanceService
) -> None:
    governing.observe(PRINCIPAL, an_observation())
    pending = governing.unresolved_mentions(PRINCIPAL)
    assert [item.observation_id for item in pending] == ["eobs_aaaa0001aaaa0001"]
    assert pending[0].is_unresolved_mention is True


def test_linking_an_observation_takes_it_off_the_unresolved_queue(
    world: World, governing: EntityGovernanceService
) -> None:
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    governing.observe(PRINCIPAL, an_observation())
    governing.link(PRINCIPAL, "eobs_aaaa0001aaaa0001", ALICE)
    assert governing.unresolved_mentions(PRINCIPAL) == []
    assert _entities(world).observations(PRINCIPAL, ALICE)[0].entity_id == ALICE


def test_an_observation_cannot_be_linked_to_another_principals_entity(
    world: World, governing: EntityGovernanceService
) -> None:
    _entities(world).create(OTHER, an_entity(ALICE, principal_id=OTHER))
    governing.observe(PRINCIPAL, an_observation())
    with pytest.raises(Exception, match="scope"):
        governing.link(PRINCIPAL, "eobs_aaaa0001aaaa0001", ALICE)


def test_an_observation_is_not_recorded_before_it_was_observed() -> None:
    with pytest.raises(ValueError, match="recorded before it was observed"):
        EntityObservation(
            observation_id="eobs_aaaa0001aaaa0001",
            principal_id=PRINCIPAL,
            kind=ObservationKind.CONTACT_RECORD,
            observed_value="Alice Chen",
            normalized_value="alice chen",
            source_id=SOURCE,
            source_object_id=OBJECT,
            source_version_id=VERSION,
            observed_at=LATER,
            recorded_at=WHEN,
        )


def test_an_observation_does_not_carry_its_observed_value_into_a_repr() -> None:
    """A name read out of someone's mail must not reach a traceback."""
    assert "a.chen@acme.test" not in repr(an_observation())


# --- a proposal applies nothing ---------------------------------------------


def test_proposing_changes_nothing(world: World, governing: EntityGovernanceService) -> None:
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    _entities(world).create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Chen"))
    governing.propose(
        PRINCIPAL,
        proposal_id="eprp_aaaa0001aaaa0001",
        kind=EntityProposalKind.MERGE_ENTITIES,
        payload={"retained_entity_id": ALICE, "merged_entity_id": ALICE_TWO},
        observation_ids=(),
        proposed_by="resolver",
        proposed_at=WHEN,
        method=EntityProposalMethod.DETERMINISTIC,
        method_version="1",
    )
    stored = _entities(world).get(PRINCIPAL, ALICE_TWO)
    assert stored is not None
    assert stored.status is EntityStatus.ACTIVE
    assert stored.superseded_by_entity_id is None
    assert world.entity_merges == []


def test_an_open_proposal_names_nobody_who_decided_it(
    world: World, governing: EntityGovernanceService
) -> None:
    proposal = governing.propose(
        PRINCIPAL,
        proposal_id="eprp_aaaa0001aaaa0001",
        kind=EntityProposalKind.RECORD_ALIAS,
        payload={"entity_id": ALICE, "alias_type": "nickname", "display_value": "Ali"},
        observation_ids=(),
        proposed_by="extractor",
        proposed_at=WHEN,
        method=EntityProposalMethod.DETERMINISTIC,
        method_version="1",
    )
    assert proposal.state is EntityProposalState.PROPOSED
    assert proposal.decided_by is None
    assert proposal.decided_at is None
    assert proposal.is_open is True


def test_a_proposal_cannot_name_a_decider_while_open() -> None:
    """The shape, not the convention: an undecided proposal has no actor to read."""
    from my_pa.domain.relationship.governance import EntityProposal

    payload = EntityProposalPayload.of(
        EntityProposalKind.RECORD_ALIAS,
        {"entity_id": ALICE, "alias_type": "nickname", "display_value": "Ali"},
    )
    with pytest.raises(ValueError, match="only a decided one"):
        EntityProposal(
            proposal_id="eprp_aaaa0001aaaa0001",
            principal_id=PRINCIPAL,
            kind=EntityProposalKind.RECORD_ALIAS,
            state=EntityProposalState.PROPOSED,
            payload=payload,
            observation_ids=(),
            proposed_at=WHEN,
            proposed_by="extractor",
            method=EntityProposalMethod.DETERMINISTIC,
            method_version="1",
            dedupe_sha256=dedupe_digest(payload),
            decided_by="someone",
            decided_at=WHEN,
        )


def test_a_proposal_cannot_name_its_own_review_requirement() -> None:
    """Derived from the kind, so a proposer cannot claim the weakest one."""
    assert requirement_for(EntityProposalKind.MERGE_ENTITIES) is ReviewRequirement.REQUIRES_OPERATOR
    assert requirement_for(EntityProposalKind.CREATE_ENTITY) is ReviewRequirement.REQUIRES_REVIEW
    assert (
        requirement_for(EntityProposalKind.RECORD_ALIAS)
        is ReviewRequirement.MAY_BE_ACCEPTED_AUTOMATICALLY
    )


# --- a merge needs an operator ----------------------------------------------


def _staged_merge(world: World, governing: EntityGovernanceService) -> None:
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    _entities(world).create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Chen"))
    governing.propose(
        PRINCIPAL,
        proposal_id="eprp_aaaa0001aaaa0001",
        kind=EntityProposalKind.MERGE_ENTITIES,
        payload={"retained_entity_id": ALICE, "merged_entity_id": ALICE_TWO},
        observation_ids=(),
        proposed_by="resolver",
        proposed_at=WHEN,
        method=EntityProposalMethod.DETERMINISTIC,
        method_version="1",
    )


def test_accepting_a_merge_without_operator_authority_is_refused(
    world: World, governing: EntityGovernanceService
) -> None:
    """The single most consequential refusal in this module."""
    _staged_merge(world, governing)
    with pytest.raises(ReviewAuthorityError, match="operator authority"):
        governing.accept(
            PRINCIPAL,
            "eprp_aaaa0001aaaa0001",
            decided_by="the resolver",
            decided_at=LATER,
            reason="looks like the same person",
            merge_id="emrg_aaaa0001aaaa0001",
        )
    stored = _entities(world).get(PRINCIPAL, ALICE_TWO)
    assert stored is not None
    assert stored.status is EntityStatus.ACTIVE
    assert world.entity_merges == []


def test_a_refused_merge_leaves_the_proposal_open(
    world: World, governing: EntityGovernanceService
) -> None:
    """Refusing the *authority* is not deciding the proposal."""
    _staged_merge(world, governing)
    with pytest.raises(ReviewAuthorityError):
        governing.accept(
            PRINCIPAL,
            "eprp_aaaa0001aaaa0001",
            decided_by="the resolver",
            decided_at=LATER,
            reason="looks like the same person",
            merge_id="emrg_aaaa0001aaaa0001",
        )
    assert [item.proposal_id for item in governing.open_proposals(PRINCIPAL)] == [
        "eprp_aaaa0001aaaa0001"
    ]


def test_an_operator_may_accept_a_merge(world: World, governing: EntityGovernanceService) -> None:
    _staged_merge(world, governing)
    decided = governing.accept(
        PRINCIPAL,
        "eprp_aaaa0001aaaa0001",
        decided_by="the operator",
        decided_at=LATER,
        reason="confirmed the same person by employee number",
        has_operator_authority=True,
        merge_id="emrg_aaaa0001aaaa0001",
    )
    assert decided.state is EntityProposalState.ACCEPTED
    assert decided.decided_by == "the operator"

    merged = _entities(world).get(PRINCIPAL, ALICE_TWO)
    assert merged is not None
    assert merged.status is EntityStatus.MERGED_REDIRECT
    assert merged.superseded_by_entity_id == ALICE


def test_an_accepted_merge_leaves_lineage(world: World, governing: EntityGovernanceService) -> None:
    """Section 15.3: the record is what makes the merge reversible."""
    _staged_merge(world, governing)
    governing.accept(
        PRINCIPAL,
        "eprp_aaaa0001aaaa0001",
        decided_by="the operator",
        decided_at=LATER,
        reason="confirmed by employee number",
        has_operator_authority=True,
        merge_id="emrg_aaaa0001aaaa0001",
    )
    lineage = governing.merge_lineage(PRINCIPAL, ALICE_TWO)
    assert len(lineage) == 1
    assert lineage[0].retained_entity_id == ALICE
    assert lineage[0].merged_entity_id == ALICE_TWO
    assert lineage[0].decided_by == "the operator"
    assert lineage[0].reason == "confirmed by employee number"


def test_a_merged_away_entity_still_exists(
    world: World, governing: EntityGovernanceService
) -> None:
    """Merging redirects; it does not delete.

    An entity that survives as a redirect is what lets `entities.resolve` answer
    `HISTORICAL_MATCH` for a reference to the old identity, instead of
    `NOT_FOUND` — which would be the system denying it had ever known them.
    """
    _staged_merge(world, governing)
    governing.accept(
        PRINCIPAL,
        "eprp_aaaa0001aaaa0001",
        decided_by="the operator",
        decided_at=LATER,
        reason="confirmed",
        has_operator_authority=True,
        merge_id="emrg_aaaa0001aaaa0001",
    )
    assert _entities(world).get(PRINCIPAL, ALICE_TWO) is not None


def test_accepting_a_merge_without_a_lineage_identifier_is_refused(
    world: World, governing: EntityGovernanceService
) -> None:
    """A merge whose lineage could not be written must not happen at all."""
    _staged_merge(world, governing)
    with pytest.raises(ValueError, match="needs an identifier"):
        governing.accept(
            PRINCIPAL,
            "eprp_aaaa0001aaaa0001",
            decided_by="the operator",
            decided_at=LATER,
            reason="confirmed",
            has_operator_authority=True,
        )


def test_a_decided_proposal_cannot_be_decided_again(
    world: World, governing: EntityGovernanceService
) -> None:
    _staged_merge(world, governing)
    governing.accept(
        PRINCIPAL,
        "eprp_aaaa0001aaaa0001",
        decided_by="the operator",
        decided_at=LATER,
        reason="confirmed",
        has_operator_authority=True,
        merge_id="emrg_aaaa0001aaaa0001",
    )
    with pytest.raises(ProposalNotOpenError, match="already been decided"):
        governing.accept(
            PRINCIPAL,
            "eprp_aaaa0001aaaa0001",
            decided_by="someone else",
            decided_at=LATER,
            reason="again",
            has_operator_authority=True,
            merge_id="emrg_bbbb0002bbbb0002",
        )


def test_rejecting_needs_no_operator_authority_and_changes_nothing(
    world: World, governing: EntityGovernanceService
) -> None:
    """Asymmetric on purpose: refusing a change has nothing to protect."""
    _staged_merge(world, governing)
    decided = governing.reject(
        PRINCIPAL,
        "eprp_aaaa0001aaaa0001",
        decided_by="a reviewer",
        decided_at=LATER,
        reason="different people, same name",
    )
    assert decided.state is EntityProposalState.REJECTED
    stored = _entities(world).get(PRINCIPAL, ALICE_TWO)
    assert stored is not None
    assert stored.status is EntityStatus.ACTIVE
    assert world.entity_merges == []


def test_a_rejected_proposal_is_kept_rather_than_deleted(
    world: World, governing: EntityGovernanceService
) -> None:
    """Section 10.11: no record is silently deleted."""
    _staged_merge(world, governing)
    governing.reject(
        PRINCIPAL,
        "eprp_aaaa0001aaaa0001",
        decided_by="a reviewer",
        decided_at=LATER,
        reason="different people",
    )
    held = _entities(world).proposal(PRINCIPAL, "eprp_aaaa0001aaaa0001")
    assert held is not None
    assert held.state is EntityProposalState.REJECTED
    assert held.decision_reason == "different people"


def test_a_decision_names_who_made_it(world: World, governing: EntityGovernanceService) -> None:
    _staged_merge(world, governing)
    with pytest.raises(ValueError, match="names who made it"):
        governing.reject(
            PRINCIPAL, "eprp_aaaa0001aaaa0001", decided_by="  ", decided_at=LATER, reason="no"
        )


def test_deciding_an_unknown_proposal_is_refused(governing: EntityGovernanceService) -> None:
    with pytest.raises(ProposalNotOpenError, match="no such proposal"):
        governing.reject(
            PRINCIPAL,
            "eprp_absent0001absent",
            decided_by="a reviewer",
            decided_at=LATER,
            reason="no",
        )


def test_governance_cannot_reach_another_principals_proposal(
    world: World, governing: EntityGovernanceService
) -> None:
    _staged_merge(world, governing)
    with pytest.raises(ProposalNotOpenError, match="no such proposal"):
        governing.reject(
            OTHER,
            "eprp_aaaa0001aaaa0001",
            decided_by="a reviewer",
            decided_at=LATER,
            reason="no",
        )
