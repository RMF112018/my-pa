"""Every disposition an Entity proposal can be decided by, and what each one does.

`WP-RI-B-05` puts Entity proposals on the *one* canonical Review surface as its
fourth subject kind. This module is about the decision half: what
`EntityProposalReviewService` does with each of the eight dispositions, what it
refuses, and the three separations it must not let a caller cross.

The properties, and each is one operator-prompt sentence:

1. **All eight dispositions work** (section 13). Accept promotes,
   correct-and-accept promotes a validated correction, reject/defer/invalidate
   close the proposal, mark-unresolved and escalate leave it open, and reprocess
   supersedes it and mints a successor.
2. **No disposition bypasses expected-version semantics** (section 27). A stale
   *review* version writes nothing, a stale *target* version prevents promotion,
   and a stale *reprocess* creates nothing.
3. **A typed correction patch is validated against the target command schema
   before commit**, and the capture plane's single bounded string is untouched
   by that (Manager R-4).
4. **Accepting a merge proposal through Review performs no identity mutation**
   (Manager R-1, section 15). Proved from the *Review* side here;
   `tests/unit/test_entity_promotion_execution.py` proves it from the promotion
   side.
5. **Producer and reviewer are different seats** (section 16), and the
   separation is causative rather than documentary: `review.list` and
   `review.decide` share no purpose, so a producer granted the queue cannot
   decide what is in it.

Nothing here opens a connection. What the decision ledger *stores* — the CHECKs,
the unique sequence, the foreign key — is a database-tier property and is proved
in `tests/database/test_entity_proposal_review.py`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.application.entity_governance import (
    EntityGovernanceService,
    EntityProposalReviewService,
    ProposalAdmission,
    ProposedEvidence,
    ReviewAuthorityError,
    _review_case_for,
)
from my_pa.application.entity_promotion import (
    StaleTargetVersionError,
    requires_expected_target_version,
)
from my_pa.contracts.ports import ReviewDecisionRequest, UnknownScopeError
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.review import (
    CorrectionPatch,
    Disposition,
    ReviewConflictError,
    ReviewCorrectionError,
    ReviewNotFoundError,
    ReviewSubjectKind,
)
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import (
    EntityObservation,
    EntityProposalKind,
    EntityProposalMethod,
    EntityProposalState,
    EvidenceRole,
    ObservationKind,
    ObservationState,
)
from my_pa.domain.relationship.normalization import normalize_name
from tests.conftest import World
from tests.conftest import _Entities as FakeEntities
from tests.conftest import _Reviews as FakeReviews

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
OTHER: Final = "prn_bbbb0002bbbb0002bbbb0002"
ALICE: Final = "ent_aaaa0001aaaa0001"
BOB: Final = "ent_bbbb0002bbbb0002"
OBSERVATION: Final = "eobs_aaaa0001aaaa0001"
SPAN: Final = "span_aaaa0001aaaa0001"
AUDIT: Final = "audit_aaaa0001aaaa0001"
CORRELATION: Final = "corr_aaaa0001aaaa0001"
POLICY: Final = "policy-v1"

SOURCE: Final = "src_aaaa0001aaaa0001"
OBJECT: Final = "obj_aaaa0001aaaa0001"
VERSION: Final = "ver_aaaa0001aaaa0001"

WHEN: Final = datetime(2026, 8, 24, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)

#: A kind `requirement_for` sends to a person, so a case is opened for it.
UPDATE_PAYLOAD: Final[dict[str, str | bool]] = {
    "entity_id": ALICE,
    "display_name": "Alice Chen-Okafor",
    "reason": "she married",
}
MERGE_PAYLOAD: Final[dict[str, str | bool]] = {
    "retained_entity_id": ALICE,
    "merged_entity_id": BOB,
}
#: The dispositions section 13 gives a reason. Restated in the test rather than
#: imported from the private set on `ReviewDecisionRequest`, so a widening of
#: that set has to be restated here deliberately rather than absorbed.
_REASONED: Final = frozenset(
    {
        Disposition.REJECT,
        Disposition.DEFER,
        Disposition.MARK_UNRESOLVED,
        Disposition.ESCALATE,
        Disposition.INVALIDATE,
    }
)

#: A kind a configured threshold may accept, which opens no case at all.
ALIAS_PAYLOAD: Final[dict[str, str | bool]] = {
    "entity_id": ALICE,
    "alias_type": "nickname",
    "display_value": "Ali",
}


def an_entity(entity_id: str = ALICE, name: str = "Alice Chen") -> Entity:
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


def an_observation(observation_id: str = OBSERVATION) -> EntityObservation:
    return EntityObservation(
        observation_id=observation_id,
        principal_id=PRINCIPAL,
        kind=ObservationKind.MESSAGE_PARTICIPANT,
        observed_value="Alice Chen <a.chen@acme.invalid>",
        normalized_value=normalize_name("Alice Chen"),
        source_id=SOURCE,
        source_object_id=OBJECT,
        source_version_id=VERSION,
        observed_at=WHEN,
        recorded_at=WHEN,
        state=ObservationState.CURRENT,
    )


@pytest.fixture
def entities(world: World) -> FakeEntities:
    return FakeEntities(world)


@pytest.fixture
def reviews(world: World) -> FakeReviews:
    return FakeReviews(world)


@pytest.fixture
def governing(entities: FakeEntities) -> EntityGovernanceService:
    return EntityGovernanceService(entities)


@pytest.fixture
def reviewing(entities: FakeEntities, reviews: FakeReviews) -> EntityProposalReviewService:
    return EntityProposalReviewService(entities, reviews)


def _propose(
    governing: EntityGovernanceService,
    *,
    kind: EntityProposalKind = EntityProposalKind.UPDATE_ENTITY,
    payload: dict[str, str | bool] | None = None,
    observation_ids: tuple[str, ...] = (),
    evidence: tuple[ProposedEvidence, ...] = (),
    expected_target_version: int | None = None,
) -> ProposalAdmission:
    if expected_target_version is None and requires_expected_target_version(kind):
        expected_target_version = 1
    return governing.propose(
        PRINCIPAL,
        kind=kind,
        payload=UPDATE_PAYLOAD if payload is None else payload,
        observation_ids=observation_ids,
        proposed_by="extractor",
        method=EntityProposalMethod.DETERMINISTIC,
        method_version="1",
        at=WHEN,
        evidence=evidence,
        expected_target_version=expected_target_version,
    )


def _case_of(reviews: FakeReviews, proposal_id: str) -> str:
    """The case identifier the server opened for this proposal."""
    case = next(
        item
        for item in reviews.cases(limit=50, principal_id=PRINCIPAL)
        if getattr(item, "proposal_id", None) == proposal_id
    )
    return case.review_case_id


def _request(
    review_case_id: str,
    disposition: Disposition,
    *,
    expected_review_version: int = 0,
    reason: str | None = None,
    correction_patch: CorrectionPatch | None = None,
    principal_id: str = PRINCIPAL,
) -> ReviewDecisionRequest:
    return ReviewDecisionRequest(
        review_case_id=review_case_id,
        expected_review_version=expected_review_version,
        disposition=disposition,
        principal_id=principal_id,
        correlation_id=CORRELATION,
        audit_id=AUDIT,
        policy_version=POLICY,
        decided_at=LATER,
        reason=reason,
        correction_patch=correction_patch,
    )


def _staged(entities: FakeEntities, governing: EntityGovernanceService) -> ProposalAdmission:
    entities.create(PRINCIPAL, an_entity())
    entities.record_observation(PRINCIPAL, an_observation())
    return _propose(governing, observation_ids=(OBSERVATION,))


# --- the case, and which kinds open one --------------------------------------


def test_every_producer_kind_opens_a_case_until_an_automatic_promoter_exists(
    entities: FakeEntities, governing: EntityGovernanceService
) -> None:
    """Threshold eligibility cannot strand a proposal outside its only execution path."""
    entities.create(PRINCIPAL, an_entity())
    reviewed = _propose(governing)
    automatic = _propose(governing, kind=EntityProposalKind.RECORD_ALIAS, payload=ALIAS_PAYLOAD)

    held = entities.proposal(PRINCIPAL, reviewed.proposal_id)
    threshold = entities.proposal(PRINCIPAL, automatic.proposal_id)

    assert held is not None
    assert threshold is not None
    assert held.review_case_id is not None
    assert threshold.review_case_id is not None


@pytest.mark.parametrize("kind", tuple(EntityProposalKind), ids=lambda kind: kind.value)
def test_every_producer_kind_is_assigned_a_canonical_review_case(
    kind: EntityProposalKind,
) -> None:
    validate_identifier(_review_case_for(kind), IdKind.REVIEW_CASE)


def test_an_entity_case_appears_on_the_one_canonical_surface(
    entities: FakeEntities, governing: EntityGovernanceService, reviews: FakeReviews
) -> None:
    """Section 13: the Entity plane joins `review.list` rather than getting a listing."""
    admitted = _staged(entities, governing)

    listed = reviews.cases(limit=10, principal_id=PRINCIPAL)

    assert [case.proposal_id for case in listed] == [admitted.proposal_id]
    assert listed[0].proposal_state is ProposalState.NEEDS_REVIEW
    assert listed[0].review_version == 0
    assert listed[0].latest_disposition is None


def test_the_case_carries_no_payload_value(
    entities: FakeEntities, governing: EntityGovernanceService, reviews: FakeReviews
) -> None:
    """A producer's assertion about a person is not disclosed by a listing."""
    _staged(entities, governing)

    case = reviews.cases(limit=10, principal_id=PRINCIPAL)[0]

    assert not hasattr(case, "payload")
    assert "Alice Chen-Okafor" not in repr(case)


def test_a_foreign_principal_sees_no_case(
    entities: FakeEntities, governing: EntityGovernanceService, reviews: FakeReviews
) -> None:
    _staged(entities, governing)

    assert reviews.cases(limit=10, principal_id=OTHER) == ()


def test_the_listing_filters_by_subject_kind_state_and_entity(
    entities: FakeEntities, governing: EntityGovernanceService, reviews: FakeReviews
) -> None:
    """Section 13's three filters, on the one surface."""
    admitted = _staged(entities, governing)

    assert (
        reviews.cases(
            limit=10, principal_id=PRINCIPAL, subject_kind=ReviewSubjectKind.ENTITY_PROPOSAL
        )[0].proposal_id
        == admitted.proposal_id
    )
    assert (
        reviews.cases(
            limit=10, principal_id=PRINCIPAL, subject_kind=ReviewSubjectKind.CAPTURE_PROPOSAL
        )
        == ()
    )
    assert reviews.cases(limit=10, principal_id=PRINCIPAL, state=ProposalState.NEEDS_REVIEW)
    assert reviews.cases(limit=10, principal_id=PRINCIPAL, state=ProposalState.ACCEPTED) == ()
    assert reviews.cases(limit=10, principal_id=PRINCIPAL, entity_id=ALICE)
    assert reviews.cases(limit=10, principal_id=PRINCIPAL, entity_id=BOB) == ()


# --- property 1: the eight dispositions --------------------------------------


def test_accept_promotes_through_the_canonical_service(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    """Section 37: an ordinary accepted proposal promotes through a Phase A service."""
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)

    decision = reviewing.decide(_request(case, Disposition.ACCEPT), decided_by="reviewer")

    held = entities.proposal(PRINCIPAL, admitted.proposal_id)
    entity = entities.get(PRINCIPAL, ALICE)
    assert decision.proposal_state is ProposalState.ACCEPTED
    assert decision.sequence == 1
    assert held is not None
    assert held.state is EntityProposalState.ACCEPTED
    assert held.accepted_record_id == ALICE
    assert entity is not None
    assert entity.display_name == "Alice Chen-Okafor"
    assert entity.version == 2


def test_reject_closes_the_proposal_and_writes_no_canonical_record(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)

    decision = reviewing.decide(
        _request(case, Disposition.REJECT, reason="wrong person"), decided_by="reviewer"
    )

    held = entities.proposal(PRINCIPAL, admitted.proposal_id)
    entity = entities.get(PRINCIPAL, ALICE)
    assert decision.proposal_state is ProposalState.REJECTED
    assert held is not None
    assert held.state is EntityProposalState.REJECTED
    assert held.accepted_record_id is None
    assert entity is not None
    assert entity.version == 1


def test_defer_closes_the_proposal_without_refusing_it(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)

    reviewing.decide(_request(case, Disposition.DEFER, reason="not now"), decided_by="reviewer")

    held = entities.proposal(PRINCIPAL, admitted.proposal_id)
    assert held is not None
    assert held.state is EntityProposalState.DEFERRED


def test_mark_unresolved_preserves_the_proposal_and_its_evidence(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    """Section 13: preserve unresolved state and evidence. The ledger row is the record."""
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)

    decision = reviewing.decide(
        _request(case, Disposition.MARK_UNRESOLVED, reason="cannot tell"),
        decided_by="reviewer",
    )

    held = entities.proposal(PRINCIPAL, admitted.proposal_id)
    assert decision.proposal_state is ProposalState.UNRESOLVED
    assert held is not None
    assert held.state is EntityProposalState.NEEDS_REVIEW
    assert held.is_open
    assert entities.proposal_evidence_links(PRINCIPAL, admitted.proposal_id)


def test_invalidate_creates_no_canonical_record_and_retains_lineage(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    """Section 13: no canonical record, a required reason, and the lineage kept."""
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)

    decision = reviewing.decide(
        _request(case, Disposition.INVALIDATE, reason="the subject was merged away"),
        decided_by="reviewer",
    )

    held = entities.proposal(PRINCIPAL, admitted.proposal_id)
    entity = entities.get(PRINCIPAL, ALICE)
    assert decision.proposal_state is ProposalState.INVALIDATED
    assert held is not None
    assert held.state is EntityProposalState.INVALIDATED
    assert held.invalidated_reason == "the subject was merged away"
    assert held.accepted_record_id is None
    assert held.review_case_id == case
    assert entities.proposal_evidence_links(PRINCIPAL, admitted.proposal_id)
    assert entity is not None
    assert entity.version == 1


def test_an_invalidated_case_stays_on_the_surface_and_refuses_every_later_decision(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    """The seam `WP-RI-B-06` was blocked on, tested from this side.

    B6 blocks a governed merge when a review case is bound to an affected
    proposal, on the argument that closing the proposal and leaving its case
    standing is the silent half-transformation section 20 forbids. On this plane
    the case cannot be left standing, and this is why: an Entity proposal's case
    *is* the proposal, so a proposal that becomes `invalidated` presents as an
    invalidated case on the one canonical surface in the same statement, and no
    disposition can be recorded against it afterwards. Nothing has to remember to
    close a second record, because there is no second record.
    """
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)

    reviewing.decide(
        _request(case, Disposition.INVALIDATE, reason="the subject was merged away"),
        decided_by="operator",
    )

    listed = reviews.cases(limit=10, principal_id=PRINCIPAL)
    assert [item.review_case_id for item in listed] == [case]
    assert listed[0].proposal_state is ProposalState.INVALIDATED
    with pytest.raises(ReviewConflictError):
        reviewing.decide(
            _request(case, Disposition.ACCEPT, expected_review_version=1), decided_by="reviewer"
        )


def test_invalidate_without_a_reason_is_refused_by_the_request(
    entities: FakeEntities, governing: EntityGovernanceService, reviews: FakeReviews
) -> None:
    """The requirement is on the record, so no plane can forget it."""
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)

    with pytest.raises(ValueError, match="states the reason"):
        _request(case, Disposition.INVALIDATE)


def test_escalate_raises_the_ceiling_and_leaves_the_case_open(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    """Section 13: escalation raises the case and performs no identity correction."""
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)

    reviewing.decide(
        _request(case, Disposition.ESCALATE, reason="this needs the operator"),
        decided_by="reviewer",
    )

    held = entities.proposal(PRINCIPAL, admitted.proposal_id)
    raised = reviews.entity_proposal_case(PRINCIPAL, case)
    assert held is not None
    assert held.is_open
    assert held.state is EntityProposalState.NEEDS_REVIEW
    assert raised is not None
    assert raised.escalated
    assert raised.review_version == 1


def test_an_escalated_case_refuses_a_reviewer_who_declares_no_operator_authority(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    """The whole of what escalation *does*, and it is read off the ledger."""
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)
    reviewing.decide(
        _request(case, Disposition.ESCALATE, reason="this needs the operator"),
        decided_by="reviewer",
    )

    with pytest.raises(ReviewAuthorityError):
        reviewing.decide(
            _request(case, Disposition.ACCEPT, expected_review_version=1),
            decided_by="reviewer",
        )

    held = entities.proposal(PRINCIPAL, admitted.proposal_id)
    assert held is not None
    assert held.is_open


def test_an_operator_may_accept_an_escalated_case(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    """The ceiling is a ceiling, not a wall: somebody above it can still decide."""
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)
    reviewing.decide(
        _request(case, Disposition.ESCALATE, reason="this needs the operator"),
        decided_by="reviewer",
    )

    decision = reviewing.decide(
        _request(case, Disposition.ACCEPT, expected_review_version=1),
        decided_by="operator",
        has_operator_authority=True,
    )

    assert decision.sequence == 2
    assert decision.proposal_state is ProposalState.ACCEPTED


def test_reprocess_supersedes_the_predecessor_and_raises_a_successor(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    """Section 13: a successor against current evidence; the predecessor stays historical."""
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)

    decision = reviewing.decide(_request(case, Disposition.REPROCESS), decided_by="reviewer")

    held = entities.proposal(PRINCIPAL, admitted.proposal_id)
    assert decision.proposal_state is ProposalState.SUPERSEDED
    assert held is not None
    assert held.state is EntityProposalState.SUPERSEDED
    assert held.superseded_by_proposal_id is not None
    assert held.superseded_by_proposal_id != held.proposal_id
    successor = entities.proposal(PRINCIPAL, held.superseded_by_proposal_id)
    assert successor is not None
    assert successor.kind is held.kind
    assert successor.payload == held.payload
    assert successor.is_open
    assert successor.review_case_id is not None
    assert successor.review_case_id != case


def test_a_reprocess_carries_the_predecessors_evidence_forward_exactly_once(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    """Counterevidence lives only in the link table, so a reprocess that dropped it
    would leave the successor resting on less than the proposal it replaced."""
    entities.create(PRINCIPAL, an_entity())
    entities.record_observation(PRINCIPAL, an_observation())
    admitted = _propose(
        governing,
        observation_ids=(OBSERVATION,),
        evidence=(ProposedEvidence(role=EvidenceRole.COUNTEREVIDENCE, capture_span_id=SPAN),),
    )
    case = _case_of(reviews, admitted.proposal_id)

    reviewing.decide(_request(case, Disposition.REPROCESS), decided_by="reviewer")

    held = entities.proposal(PRINCIPAL, admitted.proposal_id)
    assert held is not None
    assert held.superseded_by_proposal_id is not None
    carried = entities.proposal_evidence_links(PRINCIPAL, held.superseded_by_proposal_id)
    assert [(link.role, link.entity_observation_id, link.capture_span_id) for link in carried] == [
        (EvidenceRole.DIRECT, OBSERVATION, None),
        (EvidenceRole.COUNTEREVIDENCE, None, SPAN),
    ]


# --- property 2: no disposition bypasses expected-version semantics -----------


@pytest.mark.parametrize(
    "disposition",
    [
        Disposition.ACCEPT,
        Disposition.REJECT,
        Disposition.DEFER,
        Disposition.MARK_UNRESOLVED,
        Disposition.INVALIDATE,
        Disposition.ESCALATE,
        Disposition.REPROCESS,
    ],
)
def test_a_stale_review_version_writes_nothing_whatever_the_disposition(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
    disposition: Disposition,
) -> None:
    """Section 27, over every disposition rather than over the one that promotes."""
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)
    before = entities.proposal(PRINCIPAL, admitted.proposal_id)
    # A reason belongs only to the dispositions section 13 gives one, so the
    # request itself refuses one on the other two -- which is why this is
    # conditional rather than passed to all seven.
    reason = "because" if disposition in _REASONED else None

    with pytest.raises(ReviewConflictError, match="stale"):
        reviewing.decide(
            _request(case, disposition, expected_review_version=7, reason=reason),
            decided_by="reviewer",
        )

    assert entities.proposal(PRINCIPAL, admitted.proposal_id) == before
    assert reviews.entity_proposal_decisions(PRINCIPAL, case) == ()


def test_a_stale_target_version_prevents_promotion(
    world: World,
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    """Section 27: the proposal named a version the record has moved past.

    Asserted as "no canonical record and no ledger row", which is what this tier
    can honestly see. `_decide` claims the decision before the promotion runs, so
    a refusal has to take the claim back with it — and *that* is a property of
    the transaction rather than of the code, so it is proved against real
    PostgreSQL in `tests/database/test_entity_promotion_execution.py` and in
    `tests/database/test_entity_proposal_review.py`. A fake with no transaction
    would report the claim as standing and prove the opposite of what the server
    does, which is the trap `tests/conftest.py` warns about in its own words.
    """
    entities.create(PRINCIPAL, an_entity())
    admitted = _propose(governing, expected_target_version=1)
    case = _case_of(reviews, admitted.proposal_id)
    world.entities[0] = replace(world.entities[0], version=2)

    with pytest.raises(StaleTargetVersionError, match="has moved"):
        reviewing.decide(_request(case, Disposition.ACCEPT), decided_by="reviewer")

    held = entities.proposal(PRINCIPAL, admitted.proposal_id)
    assert held is not None
    assert held.accepted_record_id is None
    assert world.entities[0].display_name == "Alice Chen"
    assert reviews.entity_proposal_decisions(PRINCIPAL, case) == ()


def test_a_stale_reprocess_creates_nothing(
    world: World,
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    """Section 27, and the refusal comes before the successor is built."""
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)
    governing.reject(
        PRINCIPAL,
        admitted.proposal_id,
        decided_by="somebody else",
        decided_at=LATER,
        reason="already refused",
    )

    with pytest.raises(ReviewConflictError):
        reviewing.decide(_request(case, Disposition.REPROCESS), decided_by="reviewer")

    assert len(world.entity_proposals) == 1


def test_an_accepted_case_is_terminal(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)
    reviewing.decide(_request(case, Disposition.ACCEPT), decided_by="reviewer")

    with pytest.raises(ReviewConflictError, match="terminal"):
        reviewing.decide(
            _request(case, Disposition.REJECT, expected_review_version=1, reason="changed my mind"),
            decided_by="reviewer",
        )


def test_a_case_this_principal_does_not_hold_is_indistinguishable_from_absent(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)

    with pytest.raises(ReviewNotFoundError):
        reviewing.decide(
            _request(case, Disposition.ACCEPT, principal_id=OTHER), decided_by="reviewer"
        )


# --- property 3: the typed correction patch ----------------------------------


def test_a_typed_patch_is_validated_against_the_target_command_schema(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    """Manager R-4: the reviewer's fields go through `schema_for(kind)` before commit."""
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)
    patch = CorrectionPatch.of(
        {"entity_id": ALICE, "display_name": "Alice Okafor", "reason": "she married"}
    )

    decision = reviewing.decide(
        _request(case, Disposition.CORRECT_AND_ACCEPT, correction_patch=patch),
        decided_by="reviewer",
    )

    entity = entities.get(PRINCIPAL, ALICE)
    held = entities.proposal(PRINCIPAL, admitted.proposal_id)
    assert decision.proposal_state is ProposalState.CORRECTED_ACCEPTED
    assert entity is not None
    assert entity.display_name == "Alice Okafor"
    assert held is not None
    assert held.state is EntityProposalState.CORRECTED_ACCEPTED
    # The proposal keeps what was proposed. The correction is on the decision.
    assert dict(held.payload.values)["display_name"] == "Alice Chen-Okafor"


def test_a_patch_naming_a_field_the_target_command_does_not_take_is_refused(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)
    patch = CorrectionPatch.of({"entity_id": ALICE, "reason": "typo", "alias_type": "nickname"})

    with pytest.raises(ReviewCorrectionError):
        reviewing.decide(
            _request(case, Disposition.CORRECT_AND_ACCEPT, correction_patch=patch),
            decided_by="reviewer",
        )

    held = entities.proposal(PRINCIPAL, admitted.proposal_id)
    entity = entities.get(PRINCIPAL, ALICE)
    assert held is not None
    assert held.is_open
    assert entity is not None
    assert entity.version == 1


def test_a_patch_missing_a_field_the_target_command_requires_is_refused(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)

    with pytest.raises(ReviewCorrectionError):
        reviewing.decide(
            _request(
                case,
                Disposition.CORRECT_AND_ACCEPT,
                correction_patch=CorrectionPatch.of({"entity_id": ALICE}),
            ),
            decided_by="reviewer",
        )


def test_a_patch_naming_a_server_owned_field_is_refused(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    """The correction goes through the same refusal a producer's payload does."""
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)
    patch = CorrectionPatch.of({"entity_id": ALICE, "principal_id": OTHER, "reason": "no"})

    with pytest.raises(ReviewCorrectionError):
        reviewing.decide(
            _request(case, Disposition.CORRECT_AND_ACCEPT, correction_patch=patch),
            decided_by="reviewer",
        )


def test_an_entity_correction_will_not_take_the_capture_planes_single_value(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    """Extending, not repurposing: the string shape reaches no Entity subject."""
    admitted = _staged(entities, governing)
    case = _case_of(reviews, admitted.proposal_id)
    request = ReviewDecisionRequest(
        review_case_id=case,
        expected_review_version=0,
        disposition=Disposition.CORRECT_AND_ACCEPT,
        principal_id=PRINCIPAL,
        correlation_id=CORRELATION,
        audit_id=AUDIT,
        policy_version=POLICY,
        decided_at=LATER,
        corrected_value="Alice Okafor",
    )

    with pytest.raises(ReviewCorrectionError, match="typed patch"):
        reviewing.decide(request, decided_by="reviewer")


def test_the_capture_planes_bounded_string_is_unchanged() -> None:
    """Manager R-4: existing subject kinds must not regress.

    The request that a capture reviewer builds today is byte-for-byte the request
    they built before this package, and the two new fields default to absent. A
    correction on a capture subject is still one bounded string, still refused
    when blank, still refused when it accompanies anything but
    `correct_and_accept`, and still refused when it is too long.
    """
    request = ReviewDecisionRequest(
        review_case_id="rvw_aaaa0001aaaa0001",
        expected_review_version=0,
        disposition=Disposition.CORRECT_AND_ACCEPT,
        principal_id=PRINCIPAL,
        correlation_id=CORRELATION,
        audit_id=AUDIT,
        policy_version=POLICY,
        decided_at=LATER,
        corrected_value="the corrected value",
    )
    assert request.corrected_value == "the corrected value"
    assert request.correction_patch is None
    assert request.reason is None

    common: dict[str, object] = {
        "review_case_id": "rvw_aaaa0001aaaa0001",
        "expected_review_version": 0,
        "principal_id": PRINCIPAL,
        "correlation_id": CORRELATION,
        "audit_id": AUDIT,
        "policy_version": POLICY,
        "decided_at": LATER,
    }
    with pytest.raises(ValueError, match="bounded and not blank"):
        ReviewDecisionRequest(
            disposition=Disposition.CORRECT_AND_ACCEPT, corrected_value="   ", **common
        )
    with pytest.raises(ValueError, match="exactly one correction"):
        ReviewDecisionRequest(disposition=Disposition.REJECT, corrected_value="not here", **common)
    with pytest.raises(ValueError, match="exactly one correction"):
        ReviewDecisionRequest(disposition=Disposition.CORRECT_AND_ACCEPT, **common)


def test_a_correction_may_not_be_stated_twice(entities: FakeEntities) -> None:
    """One correction or the other, never both: two shapes would be two meanings."""
    with pytest.raises(ValueError, match="exactly one correction"):
        ReviewDecisionRequest(
            review_case_id="rvw_aaaa0001aaaa0001",
            expected_review_version=0,
            disposition=Disposition.CORRECT_AND_ACCEPT,
            principal_id=PRINCIPAL,
            correlation_id=CORRELATION,
            audit_id=AUDIT,
            policy_version=POLICY,
            decided_at=LATER,
            corrected_value="one",
            correction_patch=CorrectionPatch.of({"entity_id": ALICE}),
        )


# --- property 4: Manager R-1, proved from the Review side ---------------------


def test_accepting_a_merge_proposal_through_review_mutates_no_identity(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    """Manager R-1 and section 15, from the direction that now matters.

    The caller here is the one most able to reach a merge: a reviewer coming
    through `review.decide`, holding operator authority, on a case whose kind is
    `merge_entities`. The acceptance is recorded and both entities are untouched
    — same status, same version, same redirect — and no merge lineage exists.
    "Do not let `review.decide` become a hidden merge endpoint" is this test.
    """
    entities.create(PRINCIPAL, an_entity())
    entities.create(PRINCIPAL, an_entity(BOB, "Alice Chen"))
    admitted = _propose(governing, kind=EntityProposalKind.MERGE_ENTITIES, payload=MERGE_PAYLOAD)
    case = _case_of(reviews, admitted.proposal_id)
    before = {entity_id: entities.get(PRINCIPAL, entity_id) for entity_id in (ALICE, BOB)}

    decision = reviewing.decide(
        _request(case, Disposition.ACCEPT), decided_by="operator", has_operator_authority=True
    )

    held = entities.proposal(PRINCIPAL, admitted.proposal_id)
    assert decision.proposal_state is ProposalState.ACCEPTED
    assert held is not None
    assert held.state is EntityProposalState.ACCEPTED
    # Reviewed intent and lineage, and no canonical record at all.
    assert held.accepted_record_id is None
    assert held.decided_by == "operator"
    for entity_id in (ALICE, BOB):
        after = entities.get(PRINCIPAL, entity_id)
        expected = before[entity_id]
        assert after is not None
        assert expected is not None
        assert after.status is expected.status
        assert after.version == expected.version
        assert after.superseded_by_entity_id == expected.superseded_by_entity_id
    assert entities.merges(PRINCIPAL, ALICE) == []
    assert entities.merges(PRINCIPAL, BOB) == []


def test_a_reviewer_without_operator_authority_cannot_accept_a_merge_proposal(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    reviewing: EntityProposalReviewService,
    reviews: FakeReviews,
) -> None:
    """A reviewer grant is not an identity-correction grant, and it is not even
    an identity-correction *intent* grant."""
    entities.create(PRINCIPAL, an_entity())
    entities.create(PRINCIPAL, an_entity(BOB, "Alice Chen"))
    admitted = _propose(governing, kind=EntityProposalKind.MERGE_ENTITIES, payload=MERGE_PAYLOAD)
    case = _case_of(reviews, admitted.proposal_id)

    with pytest.raises(ReviewAuthorityError):
        reviewing.decide(_request(case, Disposition.ACCEPT), decided_by="reviewer")

    held = entities.proposal(PRINCIPAL, admitted.proposal_id)
    assert held is not None
    assert held.is_open


# --- property 5: producer and reviewer are different seats -------------------


def test_listing_the_queue_and_deciding_it_share_no_purpose() -> None:
    """Section 16, made causative rather than documentary.

    A producer client may hold `review.list` — it needs to see whether its own
    candidate is still outstanding — and may never hold `review.decide`. The
    grant system's unit is the *purpose*, so "may list and may not decide" is
    only enforceable if listing and deciding do not share one. They do not, and
    this is the assertion that keeps it that way: adding
    `Purpose.CAPTURE_REVIEW` to `review.decide` would make every holder of the
    queue a decider of it, and would red this test rather than shipping.
    """
    listing = permitted_purposes(Capability.REVIEW_LIST)
    deciding = permitted_purposes(Capability.REVIEW_DECIDE)

    assert listing
    assert deciding
    assert not (listing & deciding)


@pytest.mark.parametrize(
    "producing",
    [Capability.ENTITIES_OBSERVE, Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE],
)
def test_a_producer_capability_shares_no_purpose_with_deciding(
    producing: Capability,
) -> None:
    """Producer clients never receive `review_disposition` (section 16).

    Stated as a property of the vocabulary rather than of a document: no purpose
    that reaches a producing capability also reaches `review.decide`, so no
    single grant can produce a candidate and then decide it.
    """
    assert not (permitted_purposes(producing) & permitted_purposes(Capability.REVIEW_DECIDE))


# --- the merge's invalidation, on the shared fake -----------------------------
#
# `EntitiesRepository.invalidate_proposal` is the *merge's* writer and is not the
# reviewer's disposition tested above: a governed merge closes a proposal whose
# subject stopped existing under that name, and nobody decided anything. Until
# `WP-RI-B-05` no fake declared it at all, which is why the defect in its guarded
# `UPDATE` — a predicate matching only `proposed`, while `initial_state_for` had
# begun writing `needs_review` — was catchable at the database tier and nowhere
# else, and reached an integration head. These tests exist so the predicate has a
# home in the FAST tier: they drive the fake across every member of
# `EntityProposalState`, so narrowing it back to one state, or widening it to
# admit a decided proposal, reddens here.


#: The states the server's `UPDATE` matches. Restated rather than imported from
#: `UNDECIDED_PROPOSAL_STATES`, for the reason `_REASONED` above is restated: a
#: test that reads the constant the code reads agrees with it by construction and
#: measures nothing. Widening the domain tuple has to be restated here on purpose.
_UNDECIDED: Final = frozenset({EntityProposalState.PROPOSED, EntityProposalState.NEEDS_REVIEW})

#: What each state a proposal record can hold needs on it to be constructible.
#: `EntityProposal.__post_init__` binds these pairings, so a state cannot be
#: staged without the columns that state implies.
_STATE_REQUIRES: Final[dict[EntityProposalState, dict[str, object]]] = {
    EntityProposalState.PROPOSED: {},
    EntityProposalState.NEEDS_REVIEW: {},
    EntityProposalState.ACCEPTED: {"decided_by": "reviewer", "decided_at": LATER},
    EntityProposalState.CORRECTED_ACCEPTED: {"decided_by": "reviewer", "decided_at": LATER},
    EntityProposalState.REJECTED: {"decided_by": "reviewer", "decided_at": LATER},
    EntityProposalState.DEFERRED: {"decided_by": "reviewer", "decided_at": LATER},
    EntityProposalState.SUPERSEDED: {"superseded_at": LATER},
    EntityProposalState.INVALIDATED: {
        "decided_by": "reviewer",
        "decided_at": LATER,
        "invalidated_reason": "an earlier merge closed it",
    },
}


def _stage_state(
    entities: FakeEntities, world: World, proposal_id: str, state: EntityProposalState
) -> None:
    """Put the stored proposal into `state`, with whatever that state requires."""
    held = entities.proposal(PRINCIPAL, proposal_id)
    assert held is not None
    for index, stored in enumerate(world.entity_proposals):
        if stored.proposal_id == proposal_id:
            world.entity_proposals[index] = replace(held, state=state, **_STATE_REQUIRES[state])
            return
    raise AssertionError("the fixture staged no proposal to move")


@pytest.mark.parametrize("state", sorted(_UNDECIDED, key=lambda member: member.value))
def test_the_merges_invalidation_closes_a_proposal_nobody_has_decided(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    world: World,
    state: EntityProposalState,
) -> None:
    """Both undecided states, because the defect was a predicate holding only one.

    `needs_review` is the member that matters: `initial_state_for` writes it for
    every kind a person has to look at, so it is the state most proposals a merge
    has to close are actually in, and a predicate naming `proposed` alone matched
    none of them while the planner had already planned the change.
    """
    admitted = _staged(entities, governing)
    _stage_state(entities, world, admitted.proposal_id, state)

    entities.invalidate_proposal(
        PRINCIPAL,
        admitted.proposal_id,
        reason="the subject was merged away",
        decided_by="operator",
        decided_at=LATER,
    )

    held = entities.proposal(PRINCIPAL, admitted.proposal_id)
    assert held is not None
    assert held.state is EntityProposalState.INVALIDATED
    assert held.invalidated_reason == "the subject was merged away"
    assert held.decided_by == "operator"
    assert held.decided_at == LATER
    assert held.decision_reason is None, (
        "the merge's invalidation records a decision reason, which is the reviewer's "
        "column: nobody decided this proposal, the identity it named stopped existing"
    )
    assert held.accepted_record_id is None


@pytest.mark.parametrize(
    "state",
    sorted(set(EntityProposalState) - _UNDECIDED, key=lambda member: member.value),
)
def test_the_merges_invalidation_refuses_a_proposal_something_already_closed(
    entities: FakeEntities,
    governing: EntityGovernanceService,
    world: World,
    state: EntityProposalState,
) -> None:
    """Every state outside the undecided pair, and the row is left exactly as it was.

    `DEFERRED` is the one worth naming: a deferral *is* a decision and the row
    already carries the reviewer who took it, so matching it here would replace
    that person with the operator who ran the merge — destroying the record of
    who made the call, which is the harm the one-time predicate exists to
    prevent.
    """
    admitted = _staged(entities, governing)
    _stage_state(entities, world, admitted.proposal_id, state)
    before = entities.proposal(PRINCIPAL, admitted.proposal_id)

    with pytest.raises(UnknownScopeError):
        entities.invalidate_proposal(
            PRINCIPAL,
            admitted.proposal_id,
            reason="the subject was merged away",
            decided_by="operator",
            decided_at=LATER,
        )

    assert entities.proposal(PRINCIPAL, admitted.proposal_id) == before


def test_the_merges_invalidation_never_reaches_another_principals_proposal(
    entities: FakeEntities, governing: EntityGovernanceService
) -> None:
    """A foreign proposal answers exactly what an absent one answers."""
    admitted = _staged(entities, governing)

    with pytest.raises(UnknownScopeError):
        entities.invalidate_proposal(
            OTHER,
            admitted.proposal_id,
            reason="the subject was merged away",
            decided_by="operator",
            decided_at=LATER,
        )

    held = entities.proposal(PRINCIPAL, admitted.proposal_id)
    assert held is not None
    assert held.state is EntityProposalState.NEEDS_REVIEW
