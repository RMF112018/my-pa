"""`EntityProposal` after WP-RI-B-05: authority, result and the eight states.

The payload's own rules are proved in `test_entity_proposal_payload`. What is
proved here is everything the record says *about* the request rather than in it:
which method produced it, whether a model is named, what a decision looks like in
each of the eight states, and the one asymmetry section 15 forces -- an accepted
identity-correction proposal names no canonical record, because accepting it
performs no identity change.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.relationship.governance import (
    UNDECIDED_PROPOSAL_STATES,
    EntityProposal,
    EntityProposalMethod,
    EntityProposalState,
    MutationRecordFamily,
    ReviewRequirement,
    initial_state_for,
    requirement_for,
)
from my_pa.domain.relationship.proposal_payload import (
    EntityProposalKind,
    EntityProposalPayload,
    dedupe_digest,
)

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
PROPOSAL: Final = "eprp_aaaa0001aaaa0001"
ALICE: Final = "ent_aaaa0001aaaa0001"
ALICE_TWO: Final = "ent_bbbb0002bbbb0002"
SUCCESSOR: Final = "eprp_bbbb0002bbbb0002"
WHEN: Final = datetime(2026, 8, 18, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)

ALIAS_PAYLOAD: Final = EntityProposalPayload.of(
    EntityProposalKind.RECORD_ALIAS,
    {"entity_id": ALICE, "alias_type": "nickname", "display_value": "Ali"},
)
MERGE_PAYLOAD: Final = EntityProposalPayload.of(
    EntityProposalKind.MERGE_ENTITIES,
    {"retained_entity_id": ALICE, "merged_entity_id": ALICE_TWO},
)


def a_proposal(**overrides: object) -> EntityProposal:
    payload = overrides.pop("payload", ALIAS_PAYLOAD)
    assert isinstance(payload, EntityProposalPayload)
    fields: dict[str, object] = {
        "proposal_id": PROPOSAL,
        "principal_id": PRINCIPAL,
        "kind": payload.kind,
        "state": EntityProposalState.PROPOSED,
        "payload": payload,
        "observation_ids": (),
        "proposed_at": WHEN,
        "proposed_by": "extractor",
        "method": EntityProposalMethod.DETERMINISTIC,
        "method_version": "1",
        "dedupe_sha256": dedupe_digest(payload),
    }
    fields.update(overrides)
    return EntityProposal(**fields)  # type: ignore[arg-type]


# --- method and model identity ------------------------------------------------


def test_a_deterministic_proposal_names_no_model() -> None:
    """A named model would claim a model ran, which nothing here did."""
    with pytest.raises(ValueError, match="only a model proposal does"):
        a_proposal(model_id="localnamer", model_version="1")


def test_a_local_model_proposal_names_its_model() -> None:
    """The other half: a model conclusion filed under no model identity."""
    with pytest.raises(ValueError, match="only a model proposal does"):
        a_proposal(method=EntityProposalMethod.LOCAL_MODEL)


def test_a_named_model_states_its_version() -> None:
    with pytest.raises(ValueError, match="named model states its version"):
        a_proposal(method=EntityProposalMethod.LOCAL_MODEL, model_id="localnamer")


def test_a_local_model_proposal_with_both_is_accepted() -> None:
    proposal = a_proposal(
        method=EntityProposalMethod.LOCAL_MODEL,
        model_id="localnamer",
        model_version="0.4.1",
    )
    assert proposal.method is EntityProposalMethod.LOCAL_MODEL


def test_a_method_version_is_a_bounded_lowercase_token() -> None:
    with pytest.raises(ValueError, match="bounded lowercase token"):
        a_proposal(method_version="Version One")


# --- the dedupe digest --------------------------------------------------------


def test_a_dedupe_digest_is_a_sha256_digest() -> None:
    """A column that admitted anything would make uniqueness a producer's choice."""
    with pytest.raises(ValueError, match="sha256 digest"):
        a_proposal(dedupe_sha256="not-a-digest")


# --- the payload belongs to the kind -----------------------------------------


def test_a_proposal_carries_the_payload_of_its_own_kind() -> None:
    """Otherwise the schema checked one mutation and the record named another."""
    with pytest.raises(ValueError, match="payload of its own kind"):
        a_proposal(kind=EntityProposalKind.SPLIT_IDENTITY)


def test_a_proposal_payload_is_a_checked_payload() -> None:
    """A bare mapping is the shape WP-RI-06 stored and this record no longer takes."""
    with pytest.raises(ValueError, match="schema-checked payload"):
        EntityProposal(
            proposal_id=PROPOSAL,
            principal_id=PRINCIPAL,
            kind=EntityProposalKind.RECORD_ALIAS,
            state=EntityProposalState.PROPOSED,
            payload={"entity_id": ALICE},  # type: ignore[arg-type]
            observation_ids=(),
            proposed_at=WHEN,
            proposed_by="extractor",
            method=EntityProposalMethod.DETERMINISTIC,
            method_version="1",
            dedupe_sha256=dedupe_digest(ALIAS_PAYLOAD),
        )


# --- the eight states ---------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        EntityProposalState.ACCEPTED,
        EntityProposalState.CORRECTED_ACCEPTED,
        EntityProposalState.REJECTED,
        EntityProposalState.DEFERRED,
    ],
)
def test_a_decided_proposal_names_who_decided_it(state: EntityProposalState) -> None:
    with pytest.raises(ValueError, match="only a decided one"):
        a_proposal(state=state)


@pytest.mark.parametrize(
    "state",
    [EntityProposalState.PROPOSED, EntityProposalState.NEEDS_REVIEW],
)
def test_an_undecided_proposal_names_nobody(state: EntityProposalState) -> None:
    with pytest.raises(ValueError, match="only a decided one"):
        a_proposal(state=state, decided_by="a reviewer", decided_at=LATER)


def test_a_needs_review_proposal_is_a_legal_undecided_state() -> None:
    """The state four could not express: awaiting a person rather than awaiting anything."""
    proposal = a_proposal(state=EntityProposalState.NEEDS_REVIEW)
    assert proposal.decided_by is None


def test_an_invalidated_proposal_records_why() -> None:
    with pytest.raises(ValueError, match="only an invalidated one"):
        a_proposal(
            state=EntityProposalState.INVALIDATED,
            decided_by="a reviewer",
            decided_at=LATER,
        )


def test_only_an_invalidated_proposal_records_why() -> None:
    with pytest.raises(ValueError, match="only an invalidated one"):
        a_proposal(
            state=EntityProposalState.REJECTED,
            decided_by="a reviewer",
            decided_at=LATER,
            invalidated_reason="evidence no longer holds",
        )


def test_an_invalidation_reason_is_bounded() -> None:
    with pytest.raises(ValueError, match="reason is bounded"):
        a_proposal(
            state=EntityProposalState.INVALIDATED,
            decided_by="a reviewer",
            decided_at=LATER,
            invalidated_reason="e" * 501,
        )


def test_a_superseded_proposal_records_when_and_names_no_decider() -> None:
    """Supersession is not a decision: nobody disposed of an overtaken proposal."""
    proposal = a_proposal(state=EntityProposalState.SUPERSEDED, superseded_at=LATER)
    assert proposal.decided_by is None
    assert proposal.superseded_at == LATER


def test_only_a_superseded_proposal_records_when_it_was_superseded() -> None:
    with pytest.raises(ValueError, match="only a superseded one"):
        a_proposal(superseded_at=LATER)


def test_a_superseded_proposal_records_a_moment() -> None:
    with pytest.raises(ValueError, match="only a superseded one"):
        a_proposal(state=EntityProposalState.SUPERSEDED)


def test_a_proposal_is_not_superseded_before_it_was_proposed() -> None:
    with pytest.raises(ValueError, match="before it was proposed"):
        a_proposal(state=EntityProposalState.SUPERSEDED, superseded_at=WHEN - timedelta(hours=1))


def test_both_undecided_states_read_as_open() -> None:
    """`WP-RI-B-05` widened this, and widened the repository's predicate with it.

    This asserted that `NEEDS_REVIEW` was *not* open, and the reason recorded
    for the narrowness was `SqlEntityRepository.decide_proposal`'s
    `state = 'proposed'` predicate: a record claiming a decision was available
    that the server refused would surface as a scope error rather than as the
    refusal the caller hit. The predicate now names `UNDECIDED_PROPOSAL_STATES`,
    the same tuple this property reads, so the two cannot disagree — and nothing
    would write `needs_review` at all if they still did.

    `DEFERRED` stays outside both, and that is asserted beside them below.
    """
    assert a_proposal().is_open is True
    assert a_proposal(state=EntityProposalState.NEEDS_REVIEW).is_open is True


# --- the record a proposal became ---------------------------------------------


def test_an_accepted_proposal_may_name_the_record_it_became() -> None:
    proposal = a_proposal(
        state=EntityProposalState.ACCEPTED,
        decided_by="a reviewer",
        decided_at=LATER,
        accepted_record_type=MutationRecordFamily.ALIAS,
        accepted_record_id="eals_aaaa0001aaaa0001",
        accepted_record_version=1,
    )
    assert proposal.accepted_record_type is MutationRecordFamily.ALIAS


def test_an_undecided_proposal_names_no_record() -> None:
    """A promotion with no acceptance behind it."""
    with pytest.raises(ValueError, match="only when it was accepted"):
        a_proposal(
            accepted_record_type=MutationRecordFamily.ALIAS,
            accepted_record_id="eals_aaaa0001aaaa0001",
            accepted_record_version=1,
        )


def test_an_accepted_record_is_named_in_full() -> None:
    with pytest.raises(ValueError, match="family, identifier and version"):
        a_proposal(
            state=EntityProposalState.ACCEPTED,
            decided_by="a reviewer",
            decided_at=LATER,
            accepted_record_id="eals_aaaa0001aaaa0001",
        )


def test_accepting_a_merge_proposal_records_intent_rather_than_a_record() -> None:
    """Section 15, as a shape the record refuses rather than a rule a service keeps.

    A merge proposal a reviewer accepted has changed no identity: the merge is a
    separate operator act through `entities.merge`. A row claiming otherwise
    would present a reviewer's acceptance as an executed identity join.
    """
    accepted = a_proposal(
        payload=MERGE_PAYLOAD,
        state=EntityProposalState.ACCEPTED,
        decided_by="the operator",
        decided_at=LATER,
    )
    assert accepted.accepted_record_id is None

    with pytest.raises(ValueError, match="records intent, not a record"):
        a_proposal(
            payload=MERGE_PAYLOAD,
            state=EntityProposalState.ACCEPTED,
            decided_by="the operator",
            decided_at=LATER,
            accepted_record_type=MutationRecordFamily.ENTITY,
            accepted_record_id=ALICE,
            accepted_record_version=2,
        )


# --- the expected target version ---------------------------------------------


def test_an_expected_target_version_is_positive() -> None:
    with pytest.raises(ValueError, match="only mention resolution"):
        a_proposal(expected_target_version=0)


def test_mention_resolution_may_expect_the_initial_zero_version() -> None:
    payload = EntityProposalPayload.of(
        EntityProposalKind.RESOLVE_MENTION,
        {
            "observation_id": "eobs_aaaa0001aaaa0001",
            "disposition": "link_existing",
            "entity_id": ALICE,
        },
    )
    assert a_proposal(payload=payload, expected_target_version=0).expected_target_version == 0


def test_a_creating_kind_may_leave_the_expected_target_version_unset() -> None:
    """There is no record to have a version yet; the parents are read at promotion."""
    assert a_proposal().expected_target_version is None


# --- the initial state, and what "open" means after WP-RI-B-05 ---------------


@pytest.mark.parametrize("kind", list(EntityProposalKind), ids=lambda kind: kind.value)
def test_every_kind_is_first_written_in_a_state_nothing_has_decided(
    kind: EntityProposalKind,
) -> None:
    """Over all seventeen kinds, because this is what makes `NEEDS_REVIEW` safe.

    `initial_state_for` derives the initial state from the kind's review
    requirement, so a producer's proposal lands on the reviewer's queue rather
    than in the pile a configured threshold may act on. The property that makes
    that a widening of the queue and not of authority is this one: whatever the
    requirement, the state is one nothing has decided.
    """
    assert initial_state_for(kind) in UNDECIDED_PROPOSAL_STATES


@pytest.mark.parametrize("kind", list(EntityProposalKind), ids=lambda kind: kind.value)
def test_the_initial_state_says_exactly_what_the_requirement_says(
    kind: EntityProposalKind,
) -> None:
    """The derivation, stated as the equivalence rather than as a second table.

    A kind a person has to look at is written `needs_review`; a kind a
    configured threshold may accept is written `proposed`. Asserting the
    equivalence rather than seventeen expected values is what makes a kind added
    to `_REQUIREMENT_BY_KIND` covered on the day it is added.
    """
    needs_a_person = requirement_for(kind) is not ReviewRequirement.MAY_BE_ACCEPTED_AUTOMATICALLY
    assert (initial_state_for(kind) is EntityProposalState.NEEDS_REVIEW) is needs_a_person


def test_a_merge_is_written_needs_review_and_still_requires_the_operator() -> None:
    """`REQUIRES_OPERATOR` shares the state and keeps its own rule.

    The state says a person must look; the requirement says which person may
    act. Collapsing them into a third state would put the operator rule in two
    places, and `EntityGovernanceService._decide` reads the requirement.
    """
    assert initial_state_for(EntityProposalKind.MERGE_ENTITIES) is (
        EntityProposalState.NEEDS_REVIEW
    )
    assert requirement_for(EntityProposalKind.MERGE_ENTITIES) is (
        ReviewRequirement.REQUIRES_OPERATOR
    )


@pytest.mark.parametrize("state", list(EntityProposalState), ids=lambda state: state.value)
def test_a_proposal_is_open_exactly_in_the_two_undecided_states(
    state: EntityProposalState,
) -> None:
    """`is_open` and the repository's `UPDATE` predicate read one set.

    Parametrised over all eight rather than asserting the two, so a ninth state
    is answered here rather than defaulting to "not open" unnoticed. `DEFERRED`
    is deliberately not open: a deferred proposal was decided once, and routing
    it back to a reviewer is a disposition the Review plane owns.
    """
    proposal = a_proposal(**_decided_fields(state))
    assert proposal.is_open is (state in UNDECIDED_PROPOSAL_STATES)


def _decided_fields(state: EntityProposalState) -> dict[str, object]:
    """The other columns each state forces, so a record in it can exist at all."""
    fields: dict[str, object] = {"state": state}
    if state in (
        EntityProposalState.ACCEPTED,
        EntityProposalState.CORRECTED_ACCEPTED,
        EntityProposalState.REJECTED,
        EntityProposalState.DEFERRED,
        EntityProposalState.INVALIDATED,
    ):
        fields |= {"decided_by": "reviewer", "decided_at": LATER}
    if state is EntityProposalState.INVALIDATED:
        fields |= {"invalidated_reason": "the basis failed"}
    if state is EntityProposalState.SUPERSEDED:
        fields |= {"superseded_at": LATER}
    return fields


# --- the successor pointer ----------------------------------------------------


def test_only_a_superseded_proposal_names_its_successor() -> None:
    """A live proposal claiming to have been replaced is a false record."""
    with pytest.raises(ValueError, match="only a superseded proposal"):
        a_proposal(superseded_by_proposal_id=SUCCESSOR)


def test_a_superseded_proposal_may_name_its_successor() -> None:
    superseded = a_proposal(
        state=EntityProposalState.SUPERSEDED,
        superseded_at=LATER,
        superseded_by_proposal_id=SUCCESSOR,
    )
    assert superseded.superseded_by_proposal_id == SUCCESSOR


def test_a_superseded_proposal_need_not_name_a_successor() -> None:
    """The other direction is open: not everything that overtakes a proposal is one."""
    assert (
        a_proposal(state=EntityProposalState.SUPERSEDED, superseded_at=LATER)
    ).superseded_by_proposal_id is None


def test_a_proposal_is_not_its_own_successor() -> None:
    with pytest.raises(ValueError, match="not its own successor"):
        a_proposal(
            state=EntityProposalState.SUPERSEDED,
            superseded_at=LATER,
            superseded_by_proposal_id=PROPOSAL,
        )


def test_a_successor_is_named_as_a_proposal_identifier() -> None:
    with pytest.raises(InvalidIdentifierError):
        a_proposal(
            state=EntityProposalState.SUPERSEDED,
            superseded_at=LATER,
            superseded_by_proposal_id=ALICE,
        )
