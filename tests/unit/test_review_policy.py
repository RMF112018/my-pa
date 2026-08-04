"""The WP-8 review gate is closed, total, and independent of confidence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.application.commands import DecideReviewCase
from my_pa.application.errors import InvalidRequestError
from my_pa.domain.capture.proposal import ProposalType, RiskClass
from my_pa.domain.capture.review import (
    ConsequentialClass,
    Disposition,
    ReviewRequiredError,
    requires_review,
)
from my_pa.infrastructure.persistence.review import promote_proposal, routes_to_review


@pytest.mark.parametrize("subject", list(ConsequentialClass), ids=lambda item: item.value)
def test_every_consequential_class_requires_review(subject: ConsequentialClass) -> None:
    """QC-AC-020 is a closed matrix, not a confidence-sensitive sample."""
    assert requires_review(subject)


def test_the_review_policy_refuses_values_outside_its_closed_vocabulary() -> None:
    with pytest.raises(TypeError, match="consequential class"):
        requires_review("commitment")  # type: ignore[arg-type]


@pytest.mark.parametrize("risk", list(RiskClass), ids=lambda item: item.value)
@pytest.mark.parametrize("kind", [ProposalType.COMMITMENT, ProposalType.DECISION])
def test_commitments_and_decisions_route_to_review_at_every_risk(
    kind: ProposalType, risk: RiskClass
) -> None:
    """A low extractor risk cannot bypass a consequential review class."""
    assert routes_to_review(kind, risk)


@pytest.mark.parametrize("risk", [RiskClass.HIGH, RiskClass.CRITICAL])
@pytest.mark.parametrize("kind", list(ProposalType), ids=lambda item: item.value)
def test_every_high_consequence_proposal_routes_to_review(
    kind: ProposalType, risk: RiskClass
) -> None:
    assert routes_to_review(kind, risk)


def test_low_risk_technical_enrichment_does_not_create_mandatory_review_burden() -> None:
    assert not routes_to_review(ProposalType.FOLLOW_UP, RiskClass.LOW)


def test_direct_promotion_is_refused_before_any_store_is_read() -> None:
    """No caller can turn a proposal canonical without an accepting decision."""
    with pytest.raises(ReviewRequiredError, match="requires a review disposition"):
        promote_proposal(
            None,  # type: ignore[arg-type] - refusal precedes persistence by contract
            proposal_id="prop_wp8proposal0001",
            decision_id=None,
            policy_version="policy-v1",
            accepted_at=datetime.now(UTC),
        )


def test_correction_requires_a_nonempty_corrected_value() -> None:
    with pytest.raises(InvalidRequestError):
        DecideReviewCase(
            review_case_id="rvw_wp8reviewcase01",
            expected_review_version=0,
            disposition=Disposition.CORRECT_AND_ACCEPT,
        )


def test_only_correction_may_carry_a_corrected_value() -> None:
    with pytest.raises(InvalidRequestError):
        DecideReviewCase(
            review_case_id="rvw_wp8reviewcase01",
            expected_review_version=0,
            disposition=Disposition.REJECT,
            corrected_value="synthetic correction",
        )
