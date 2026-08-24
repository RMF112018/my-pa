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

from my_pa.domain.relationship.governance import (
    EntityProposal,
    EntityProposalMethod,
    EntityProposalState,
    MutationRecordFamily,
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


def test_only_proposed_reads_as_open() -> None:
    """Narrow deliberately: the repository's own decide predicate names one state."""
    assert a_proposal().is_open is True
    assert a_proposal(state=EntityProposalState.NEEDS_REVIEW).is_open is False


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
    with pytest.raises(ValueError, match="positive integer"):
        a_proposal(expected_target_version=0)


def test_a_creating_kind_may_leave_the_expected_target_version_unset() -> None:
    """There is no record to have a version yet; the parents are read at promotion."""
    assert a_proposal().expected_target_version is None
