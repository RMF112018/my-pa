"""The producer path: what a proposer may say, and what the server decides for it.

`entities.proposals.create`'s application behaviour. The capability, the command
and the transport that publishes it are somebody else's; what is here is the
whole of the rule that makes publishing one safe — a producer describes a
mutation and cites what it read, and every field that carries authority,
identity, ordering or uniqueness is the server's.

Four properties, and each is a way the plane fails if it is missing:

1. **The server owns the identity, the state, the moment and the digest.** A
   producer that chose its own proposal identifier could rebind one; one that
   chose its own digest could choose a value nothing collides with and dedupe
   would be over whatever it picked.
2. **A payload cannot smuggle a server-owned field.** The refusal is by name and
   is proved against the whole declared set rather than a sample.
3. **An open-equivalent proposal is returned, not multiplied.** Two producers
   over the same evidence put one decision in front of a reviewer.
4. **A refusal has an effect.** Negative identity evidence suppresses the same
   claim on the same grounds, and only on the same grounds — new evidence gets a
   new hearing, which is the difference between remembering a decision and
   refusing to look again.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.application.entity_governance import (
    EntityGovernanceService,
    ProposalAdmission,
    ProposalSuppressedError,
    QuarantinedObservationError,
    UnknownObservationError,
)
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import (
    EntityFactEvidenceLink,
    EntityObservation,
    EntityProposal,
    EntityProposalKind,
    EntityProposalMethod,
    EntityProposalState,
    EvidenceRole,
    MutationAuthority,
    ObservationKind,
    ObservationState,
    ReviewRequirement,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.relationship.proposal_payload import (
    FORBIDDEN_PAYLOAD_FIELDS,
    EntityProposalPayload,
    ProposalPayloadError,
    dedupe_digest,
    schema_for,
)
from tests.conftest import FakeUnitOfWork, World

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
OTHER: Final = "prn_bbbb0002bbbb0002bbbb0002"
ALICE: Final = "ent_aaaa0001aaaa0001"
ALICE_TWO: Final = "ent_bbbb0002bbbb0002"
FIRST_OBSERVATION: Final = "eobs_aaaa0001aaaa0001"
SECOND_OBSERVATION: Final = "eobs_bbbb0002bbbb0002"

SOURCE: Final = "src_aaaa0001aaaa0001"
OBJECT: Final = "obj_aaaa0001aaaa0001"
VERSION: Final = "ver_aaaa0001aaaa0001"

WHEN: Final = datetime(2026, 8, 18, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)

ALIAS_PAYLOAD: Final[dict[str, str | bool]] = {
    "entity_id": ALICE,
    "alias_type": "nickname",
    "display_value": "Ali",
}


def _entities(world: World):  # noqa: ANN202
    return FakeUnitOfWork(world).entities


@pytest.fixture
def governing(world: World) -> EntityGovernanceService:
    return EntityGovernanceService(_entities(world))


def an_entity(entity_id: str, principal_id: str = PRINCIPAL, name: str = "Alice Chen") -> Entity:
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
    observation_id: str = FIRST_OBSERVATION,
    principal_id: str = PRINCIPAL,
    state: ObservationState = ObservationState.CURRENT,
) -> EntityObservation:
    return EntityObservation(
        observation_id=observation_id,
        principal_id=principal_id,
        kind=ObservationKind.MESSAGE_PARTICIPANT,
        observed_value="Alice Chen <a.chen@acme.invalid>",
        normalized_value=normalize_name("Alice Chen"),
        source_id=SOURCE,
        source_object_id=OBJECT,
        source_version_id=VERSION,
        observed_at=WHEN,
        recorded_at=WHEN,
        state=state,
    )


def _propose(
    governing: EntityGovernanceService,
    *,
    principal_id: str = PRINCIPAL,
    kind: EntityProposalKind = EntityProposalKind.RECORD_ALIAS,
    payload: dict[str, str | bool] | None = None,
    observation_ids: tuple[str, ...] = (),
    at: datetime = WHEN,
) -> ProposalAdmission:
    return governing.propose(
        principal_id,
        kind=kind,
        payload=ALIAS_PAYLOAD if payload is None else payload,
        observation_ids=observation_ids,
        proposed_by="extractor",
        method=EntityProposalMethod.DETERMINISTIC,
        method_version="1",
        at=at,
    )


def _refuse(world: World, entity_id: str, observation_id: str, link_id: str) -> None:
    """Record that this observation has been decided *not* to refer to this entity.

    Written straight onto the evidence table rather than through
    `resolve_mention`, because what the suppression rule reads is the row and not
    the path that produced it — and a producer must be suppressed by a refusal
    however it was recorded.
    """
    _entities(world).record_fact_evidence_link(
        PRINCIPAL,
        EntityFactEvidenceLink(
            link_id=link_id,
            principal_id=PRINCIPAL,
            role=EvidenceRole.COUNTEREVIDENCE,
            authority=MutationAuthority.USER_CONFIRMED_ASSERTION,
            created_at=WHEN,
            entity_id=entity_id,
            entity_observation_id=observation_id,
        ),
    )


# --- what the server owns ----------------------------------------------------


def test_the_server_mints_the_proposal_identifier(
    world: World, governing: EntityGovernanceService
) -> None:
    """A producer that named its own identifier could name one already taken."""
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    admitted = _propose(governing)
    validate_identifier(admitted.proposal_id, IdKind.ENTITY_PROPOSAL)
    stored = _entities(world).proposal(PRINCIPAL, admitted.proposal_id)
    assert stored is not None
    assert stored.proposal_id == admitted.proposal_id


def test_two_different_proposals_are_minted_different_identifiers(
    world: World, governing: EntityGovernanceService
) -> None:
    """The control for the test above: minting is per-proposal, not per-process."""
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    first = _propose(governing)
    second = _propose(governing, payload={**ALIAS_PAYLOAD, "display_value": "Alicia"})
    assert first.proposal_id != second.proposal_id
    assert len(world.entity_proposals) == 2


def test_the_server_owns_the_state_the_moment_and_the_digest(
    world: World, governing: EntityGovernanceService
) -> None:
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    admitted = _propose(governing)
    stored = _entities(world).proposal(PRINCIPAL, admitted.proposal_id)
    assert stored is not None
    assert stored.state is EntityProposalState.PROPOSED
    assert stored.proposed_at == WHEN
    assert stored.dedupe_sha256 == dedupe_digest(
        EntityProposalPayload.of(EntityProposalKind.RECORD_ALIAS, ALIAS_PAYLOAD)
    )
    assert admitted.dedupe_sha256 == stored.dedupe_sha256
    assert admitted.created is True


def test_the_admission_says_what_has_to_happen_next(
    world: World, governing: EntityGovernanceService
) -> None:
    """The producer's next question, answered rather than left to be inferred."""
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    assert _propose(governing).requirement is ReviewRequirement.MAY_BE_ACCEPTED_AUTOMATICALLY
    assert (
        _propose(
            governing,
            kind=EntityProposalKind.CREATE_ENTITY,
            payload={"entity_type": "person", "display_name": "Bo Zhang"},
        ).requirement
        is ReviewRequirement.REQUIRES_REVIEW
    )


def test_the_admission_carries_no_payload(world: World, governing: EntityGovernanceService) -> None:
    """A receipt that echoed the proposed text would put a name on a second surface."""
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    admitted = _propose(governing)
    assert "Ali" not in repr(admitted)
    assert not hasattr(admitted, "payload")


def test_a_proposal_creates_no_canonical_record(
    world: World, governing: EntityGovernanceService
) -> None:
    """The rule the whole plane rests on, asserted at the producer's entry point."""
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    _propose(governing)
    stored = _entities(world).get(PRINCIPAL, ALICE)
    assert stored is not None
    assert stored.version == 1
    assert _entities(world).aliases(PRINCIPAL, ALICE) == []
    assert world.entity_merges == []
    assert world.entity_mutation_events == []


# --- what a payload may not carry --------------------------------------------


@pytest.mark.parametrize("field", sorted(FORBIDDEN_PAYLOAD_FIELDS))
def test_no_payload_may_carry_a_server_owned_field(
    field: str, world: World, governing: EntityGovernanceService
) -> None:
    """Every declared name, not a sample of them.

    Parametrised over `FORBIDDEN_PAYLOAD_FIELDS` itself so that a name added to
    that set is covered the moment it is added, and a name quietly removed from
    it stops being tested loudly rather than silently.
    """
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    with pytest.raises(ProposalPayloadError):
        _propose(governing, payload={**ALIAS_PAYLOAD, field: "smuggled"})
    assert world.entity_proposals == []


def test_a_payload_naming_a_field_its_kind_does_not_take_is_refused(
    world: World, governing: EntityGovernanceService
) -> None:
    """The other half: a field that is nobody's is refused too, not only the server's."""
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    with pytest.raises(ProposalPayloadError, match="only fields its kind's command takes"):
        _propose(governing, payload={**ALIAS_PAYLOAD, "assignment_type": "employment"})
    assert world.entity_proposals == []


def test_the_forbidden_set_is_disjoint_from_every_kinds_schema() -> None:
    """A guard on the guard: no schema may admit a name the producer path refuses.

    Without it, a schema widened to admit `authority` would make a payload both
    valid for its kind and refused by the set — the kind of contradiction that
    surfaces as an unexplainable rejection rather than as a test failure.
    """
    for kind in EntityProposalKind:
        assert schema_for(kind).admitted.isdisjoint(FORBIDDEN_PAYLOAD_FIELDS), kind.value


# --- open-equivalent proposals dedupe rather than multiply --------------------


def test_an_identical_open_proposal_is_returned_rather_than_recorded_twice(
    world: World, governing: EntityGovernanceService
) -> None:
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    first = _propose(governing)
    second = _propose(governing, at=LATER)
    assert second.created is False
    assert second.proposal_id == first.proposal_id
    assert second.proposed_at == WHEN, "the deduped admission describes the proposal that stands"
    assert len(world.entity_proposals) == 1


def test_a_different_payload_is_a_different_proposal(
    world: World, governing: EntityGovernanceService
) -> None:
    """The control: dedupe is over the claim, so a different claim is heard."""
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    first = _propose(governing)
    second = _propose(governing, payload={**ALIAS_PAYLOAD, "display_value": "Chen"})
    assert second.created is True
    assert second.proposal_id != first.proposal_id
    assert len(world.entity_proposals) == 2


def test_a_deferred_proposal_still_absorbs_an_identical_one(
    world: World, governing: EntityGovernanceService
) -> None:
    """`OPEN_EQUIVALENT_PROPOSAL_STATES` includes `deferred`, and this is why.

    A reviewer who pushed a decision out has not been relieved of it. If a
    re-filing produced a second row, a producer could clear a deferral simply by
    proposing again, and the queue would fill with the decision the reviewer
    most recently declined to make.
    """
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    payload = EntityProposalPayload.of(EntityProposalKind.RECORD_ALIAS, ALIAS_PAYLOAD)
    _entities(world).record_proposal(
        PRINCIPAL,
        EntityProposal(
            proposal_id="eprp_dddd0004dddd0004",
            principal_id=PRINCIPAL,
            kind=EntityProposalKind.RECORD_ALIAS,
            state=EntityProposalState.DEFERRED,
            payload=payload,
            observation_ids=(),
            proposed_at=WHEN,
            proposed_by="extractor",
            method=EntityProposalMethod.DETERMINISTIC,
            method_version="1",
            dedupe_sha256=dedupe_digest(payload),
            decided_by="a reviewer",
            decided_at=LATER,
            decision_reason="ask her first",
        ),
    )
    admitted = _propose(governing, at=LATER)
    assert admitted.created is False
    assert admitted.proposal_id == "eprp_dddd0004dddd0004"
    assert len(world.entity_proposals) == 1


def test_a_rejected_proposal_does_not_absorb_a_later_one(
    world: World, governing: EntityGovernanceService
) -> None:
    """A refusal is final, so it is not what stops a re-proposal. Evidence is.

    `rejected` is deliberately outside the open-equivalent set: a claim refused
    once may be raised again on new grounds, and a unique index cannot tell
    whether the grounds are new. The test below is what does.
    """
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    first = _propose(governing)
    governing.reject(
        PRINCIPAL,
        first.proposal_id,
        decided_by="a reviewer",
        decided_at=LATER,
        reason="that is somebody else's nickname",
    )
    again = _propose(governing, at=LATER)
    assert again.created is True
    assert again.proposal_id != first.proposal_id


def test_dedupe_does_not_reach_across_the_partition(
    world: World, governing: EntityGovernanceService
) -> None:
    """Another Principal's open proposal is not this one's duplicate.

    If it were, the second Principal would be handed an identifier for a row in
    a partition they cannot read — and told their own proposal already existed
    when nothing of theirs did.
    """
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    _entities(world).create(OTHER, an_entity(ALICE_TWO, principal_id=OTHER))
    mine = _propose(governing)
    theirs = _propose(
        governing,
        principal_id=OTHER,
        payload={**ALIAS_PAYLOAD, "entity_id": ALICE_TWO},
    )
    assert theirs.created is True
    assert theirs.proposal_id != mine.proposal_id


# --- evidence is checked before it is cited ----------------------------------


def test_a_proposal_may_cite_the_observations_it_read(
    world: World, governing: EntityGovernanceService
) -> None:
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    _entities(world).record_observation(PRINCIPAL, an_observation())
    admitted = _propose(governing, observation_ids=(FIRST_OBSERVATION,))
    assert admitted.observation_ids == (FIRST_OBSERVATION,)
    stored = _entities(world).proposal(PRINCIPAL, admitted.proposal_id)
    assert stored is not None
    assert stored.observation_ids == (FIRST_OBSERVATION,)


def test_a_citation_of_an_observation_that_does_not_exist_is_refused(
    world: World, governing: EntityGovernanceService
) -> None:
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    with pytest.raises(UnknownObservationError, match="no such observation"):
        _propose(governing, observation_ids=(FIRST_OBSERVATION,))
    assert world.entity_proposals == []


def test_a_foreign_observation_is_refused_exactly_as_an_absent_one(
    world: World, governing: EntityGovernanceService
) -> None:
    """The refusal must not disclose that somebody else's record exists."""
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    _entities(world).record_observation(
        OTHER, an_observation(SECOND_OBSERVATION, principal_id=OTHER)
    )
    with pytest.raises(UnknownObservationError, match="no such observation"):
        _propose(governing, observation_ids=(SECOND_OBSERVATION,))
    assert world.entity_proposals == []
    theirs = _entities(world).observations(OTHER)
    assert [held.observation_id for held in theirs] == [SECOND_OBSERVATION], (
        "the staged foreign row went missing"
    )


def test_a_quarantined_observation_cannot_evidence_a_proposal(
    world: World, governing: EntityGovernanceService
) -> None:
    """Untrusted input does not become the basis of a canonical fact by being proposed."""
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    _entities(world).record_observation(
        PRINCIPAL, an_observation(state=ObservationState.QUARANTINED)
    )
    with pytest.raises(QuarantinedObservationError, match="quarantined observation"):
        _propose(governing, observation_ids=(FIRST_OBSERVATION,))
    assert world.entity_proposals == []


# --- a refusal suppresses the same claim on the same grounds -----------------


def test_a_claim_whose_every_citation_was_refused_is_suppressed(
    world: World, governing: EntityGovernanceService
) -> None:
    """Section 11's second sentence, and the reason a rejection is more than a row."""
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    _entities(world).record_observation(PRINCIPAL, an_observation())
    _refuse(world, ALICE, FIRST_OBSERVATION, "efev_aaaa0001aaaa0001")
    with pytest.raises(ProposalSuppressedError, match="already been refused"):
        _propose(governing, observation_ids=(FIRST_OBSERVATION,))
    assert world.entity_proposals == []


def test_one_citation_that_was_never_refused_is_genuinely_new_grounds(
    world: World, governing: EntityGovernanceService
) -> None:
    """Section 11's "unless genuinely new evidence invalidates the prior basis".

    The producer read something it had not read before. Suppressing that would
    make the plane unable to correct a refusal it got wrong, which is a worse
    failure than the one suppression exists to prevent.
    """
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    _entities(world).record_observation(PRINCIPAL, an_observation())
    _entities(world).record_observation(PRINCIPAL, an_observation(SECOND_OBSERVATION))
    _refuse(world, ALICE, FIRST_OBSERVATION, "efev_aaaa0001aaaa0001")
    admitted = _propose(governing, observation_ids=(FIRST_OBSERVATION, SECOND_OBSERVATION))
    assert admitted.created is True


def test_a_refusal_against_a_different_entity_suppresses_nothing(
    world: World, governing: EntityGovernanceService
) -> None:
    """Negative evidence is about a *pairing*. A refusal names which entity."""
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    _entities(world).create(PRINCIPAL, an_entity(ALICE_TWO, name="Alice Chen"))
    _entities(world).record_observation(PRINCIPAL, an_observation())
    _refuse(world, ALICE_TWO, FIRST_OBSERVATION, "efev_aaaa0001aaaa0001")
    admitted = _propose(governing, observation_ids=(FIRST_OBSERVATION,))
    assert admitted.created is True


def test_a_proposal_citing_nothing_is_never_suppressed(
    world: World, governing: EntityGovernanceService
) -> None:
    """It has no basis, so it has no basis that was refused.

    Stated as its own test because the rule reads "every citation was refused"
    and "every" over an empty tuple is true — the exact shape in which this
    suppression would otherwise refuse everything.
    """
    _entities(world).create(PRINCIPAL, an_entity(ALICE))
    _entities(world).record_observation(PRINCIPAL, an_observation())
    _refuse(world, ALICE, FIRST_OBSERVATION, "efev_aaaa0001aaaa0001")
    assert _propose(governing).created is True
