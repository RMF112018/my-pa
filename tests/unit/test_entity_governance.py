"""Observation, proposal, and governed merge.

Organized around the thing the plane must never do: change who someone is
without a person deciding it. Every test below names a route by which that could
happen and asserts it is closed.

The merge tests are the sharp end. A merge joins two histories permanently, and
`RI-AC-039`, specification section 21.4 and `AGENTS.md` section 8.2 all put that
decision outside anything automatic — so the checks here are about *authority*
rather than about correctness of the join.

**And since `WP-RI-B-05` they are also about the join not happening here at
all.** Accepting a `merge_entities` proposal records reviewed intent; the
identity change is an operator act under `entity_identity_correction`. The
tests below that used to assert a redirect and a lineage row now assert their
absence, which is the same subject read the other way round: what a reviewer's
disposition may reach.
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
from tests.conftest import World
from tests.unit.entity_proposal_fakes import ProposalEntities

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
OTHER = "prn_bbbb0002bbbb0002bbbb0002"
ALICE = "ent_aaaa0001aaaa0001"
ALICE_TWO = "ent_bbbb0002bbbb0002"

SOURCE = "src_aaaa0001aaaa0001"
OBJECT = "obj_aaaa0001aaaa0001"
VERSION = "ver_aaaa0001aaaa0001"

WHEN = datetime(2026, 8, 18, 12, tzinfo=UTC)
LATER = WHEN + timedelta(hours=1)


def _entities(world: World) -> ProposalEntities:
    """The entity plane over this `World`, with the proposal-plane methods.

    `ProposalEntities` rather than `FakeUnitOfWork(world).entities`, and the
    reason is stated in that module: `tests/conftest.py` is frozen for
    `WP-RI-B-05`, so the four methods the proposal and promotion paths need had
    to be written beside it instead of in it. Both share one `World`, so a test
    that stages rows through either sees them through the other.
    """
    return ProposalEntities(world)


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
        kind=EntityProposalKind.MERGE_ENTITIES,
        payload={"retained_entity_id": ALICE, "merged_entity_id": ALICE_TWO},
        observation_ids=(),
        proposed_by="resolver",
        method=EntityProposalMethod.DETERMINISTIC,
        method_version="1",
        at=WHEN,
    )
    stored = _entities(world).get(PRINCIPAL, ALICE_TWO)
    assert stored is not None
    assert stored.status is EntityStatus.ACTIVE
    assert stored.superseded_by_entity_id is None
    assert world.entity_merges == []


def test_an_open_proposal_names_nobody_who_decided_it(
    world: World, governing: EntityGovernanceService
) -> None:
    admitted = governing.propose(
        PRINCIPAL,
        kind=EntityProposalKind.RECORD_ALIAS,
        payload={"entity_id": ALICE, "alias_type": "nickname", "display_value": "Ali"},
        observation_ids=(),
        proposed_by="extractor",
        method=EntityProposalMethod.DETERMINISTIC,
        method_version="1",
        at=WHEN,
    )
    assert admitted.state is EntityProposalState.PROPOSED
    assert admitted.created is True
    proposal = _entities(world).proposal(PRINCIPAL, admitted.proposal_id)
    assert proposal is not None
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


def _staged_merge(world: World, governing: EntityGovernanceService) -> str:
    """Two entities and one open merge proposal. Returns the minted identifier."""
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    _entities(world).create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Chen"))
    return governing.propose(
        PRINCIPAL,
        kind=EntityProposalKind.MERGE_ENTITIES,
        payload={"retained_entity_id": ALICE, "merged_entity_id": ALICE_TWO},
        observation_ids=(),
        proposed_by="resolver",
        method=EntityProposalMethod.DETERMINISTIC,
        method_version="1",
        at=WHEN,
    ).proposal_id


def test_accepting_a_merge_without_operator_authority_is_refused(
    world: World, governing: EntityGovernanceService
) -> None:
    """The single most consequential refusal in this module."""
    proposal_id = _staged_merge(world, governing)
    with pytest.raises(ReviewAuthorityError, match="operator authority"):
        governing.accept(
            PRINCIPAL,
            proposal_id,
            decided_by="the resolver",
            decided_at=LATER,
            reason="looks like the same person",
        )
    stored = _entities(world).get(PRINCIPAL, ALICE_TWO)
    assert stored is not None
    assert stored.status is EntityStatus.ACTIVE
    assert world.entity_merges == []


def test_a_refused_merge_leaves_the_proposal_open(
    world: World, governing: EntityGovernanceService
) -> None:
    """Refusing the *authority* is not deciding the proposal."""
    proposal_id = _staged_merge(world, governing)
    with pytest.raises(ReviewAuthorityError):
        governing.accept(
            PRINCIPAL,
            proposal_id,
            decided_by="the resolver",
            decided_at=LATER,
            reason="looks like the same person",
        )
    assert [item.proposal_id for item in governing.open_proposals(PRINCIPAL)] == [proposal_id]


def test_an_operator_may_accept_a_merge(world: World, governing: EntityGovernanceService) -> None:
    """The decision is recorded, and the decision is all that is recorded."""
    proposal_id = _staged_merge(world, governing)
    decided = governing.accept(
        PRINCIPAL,
        proposal_id,
        decided_by="the operator",
        decided_at=LATER,
        reason="confirmed the same person by employee number",
        has_operator_authority=True,
    )
    assert decided.state is EntityProposalState.ACCEPTED
    assert decided.decided_by == "the operator"
    assert decided.accepted_record_id is None, (
        "an accepted identity correction names no canonical record; it records intent"
    )


def test_accepting_a_merge_proposal_mutates_no_identity(
    world: World, governing: EntityGovernanceService
) -> None:
    """`WP-RI-B-05`, and the sharpest assertion in this file.

    Both entities are photographed before the acceptance and compared after it,
    field for field on the two fields a merge changes plus the version every
    optimistic write on this plane is checked against. Accepting a
    `merge_entities` proposal must leave all six values exactly as they were:
    a reviewer's disposition is not an identity-correction authority, and if
    acceptance ever redirects an entity again this test is what says so.

    Written to fail loudly against the code this replaced. Restoring the
    `redirect_entity` / `record_merge` pair inside the decision path turns the
    status of `ALICE_TWO` into `merged_redirect`, fills its
    `superseded_by_entity_id`, and puts a row in `merge_lineage` — three
    assertions here, so the mutation cannot be half-detected.
    """
    proposal_id = _staged_merge(world, governing)
    entities = _entities(world)
    before = {}
    for entity_id in (ALICE, ALICE_TWO):
        held = entities.get(PRINCIPAL, entity_id)
        assert held is not None
        # Both are active and unversioned before the decision, so "unchanged"
        # below is an assertion about something rather than about an absence.
        assert held.status is EntityStatus.ACTIVE
        assert held.superseded_by_entity_id is None
        before[entity_id] = held

    governing.accept(
        PRINCIPAL,
        proposal_id,
        decided_by="the operator",
        decided_at=LATER,
        reason="confirmed the same person by employee number",
        has_operator_authority=True,
    )

    for entity_id, was in before.items():
        now = entities.get(PRINCIPAL, entity_id)
        assert now is not None, "accepting a proposal removed an entity"
        assert now.status is was.status, f"{entity_id} changed status on a review disposition"
        assert now.version == was.version, f"{entity_id} was versioned by a review disposition"
        assert now.superseded_by_entity_id is was.superseded_by_entity_id
    assert world.entity_merges == [], "a review disposition wrote merge lineage"


def test_accepting_a_merge_leaves_the_lineage_to_the_operator_act(
    world: World, governing: EntityGovernanceService
) -> None:
    """Section 15.3's lineage record still exists; acceptance is not what writes it.

    The record is what makes a merge reversible, so nothing here argues against
    writing one — it argues about *which act* writes it. `entities.merge` does,
    holding a live preview bound to exact versions. An accepted proposal is the
    reviewed intent that operator act cites, which is why the proposal survives
    the decision with both entity identifiers still readable in its payload.
    """
    proposal_id = _staged_merge(world, governing)
    governing.accept(
        PRINCIPAL,
        proposal_id,
        decided_by="the operator",
        decided_at=LATER,
        reason="confirmed by employee number",
        has_operator_authority=True,
    )
    assert governing.merge_lineage(PRINCIPAL, ALICE_TWO) == []
    intent = _entities(world).proposal(PRINCIPAL, proposal_id)
    assert intent is not None
    assert intent.state is EntityProposalState.ACCEPTED
    assert intent.decided_by == "the operator"
    assert intent.decision_reason == "confirmed by employee number"
    assert intent.payload.as_mapping() == {
        "retained_entity_id": ALICE,
        "merged_entity_id": ALICE_TWO,
    }


def test_accepting_a_merge_asks_for_no_lineage_identifier(
    world: World, governing: EntityGovernanceService
) -> None:
    """The parameter is gone, and its absence is the mechanism.

    `accept` used to take a `merge_id` and refuse without one, because it was
    about to write a merge record. A method that still took one would be a
    method that still intended to, and the honest form of "this no longer merges"
    is that there is nowhere left to put the merge's identifier.
    """
    proposal_id = _staged_merge(world, governing)
    with pytest.raises(TypeError):
        governing.accept(
            PRINCIPAL,
            proposal_id,
            decided_by="the operator",
            decided_at=LATER,
            reason="confirmed",
            has_operator_authority=True,
            merge_id="emrg_aaaa0001aaaa0001",
        )


def test_a_decided_proposal_cannot_be_decided_again(
    world: World, governing: EntityGovernanceService
) -> None:
    proposal_id = _staged_merge(world, governing)
    governing.accept(
        PRINCIPAL,
        proposal_id,
        decided_by="the operator",
        decided_at=LATER,
        reason="confirmed",
        has_operator_authority=True,
    )
    with pytest.raises(ProposalNotOpenError, match="already been decided"):
        governing.accept(
            PRINCIPAL,
            proposal_id,
            decided_by="someone else",
            decided_at=LATER,
            reason="again",
            has_operator_authority=True,
        )


def test_rejecting_needs_no_operator_authority_and_changes_nothing(
    world: World, governing: EntityGovernanceService
) -> None:
    """Asymmetric on purpose: refusing a change has nothing to protect."""
    proposal_id = _staged_merge(world, governing)
    decided = governing.reject(
        PRINCIPAL,
        proposal_id,
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
    proposal_id = _staged_merge(world, governing)
    governing.reject(
        PRINCIPAL,
        proposal_id,
        decided_by="a reviewer",
        decided_at=LATER,
        reason="different people",
    )
    held = _entities(world).proposal(PRINCIPAL, proposal_id)
    assert held is not None
    assert held.state is EntityProposalState.REJECTED
    assert held.decision_reason == "different people"


def test_a_decision_names_who_made_it(world: World, governing: EntityGovernanceService) -> None:
    proposal_id = _staged_merge(world, governing)
    with pytest.raises(ValueError, match="names who made it"):
        governing.reject(PRINCIPAL, proposal_id, decided_by="  ", decided_at=LATER, reason="no")


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
    proposal_id = _staged_merge(world, governing)
    with pytest.raises(ProposalNotOpenError, match="no such proposal"):
        governing.reject(
            OTHER,
            proposal_id,
            decided_by="a reviewer",
            decided_at=LATER,
            reason="no",
        )
