"""The WP-8 review gate is closed, total, and independent of confidence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.application.commands import DecideReviewCase
from my_pa.application.errors import InvalidRequestError
from my_pa.contracts.ports import ReviewDecisionRequest
from my_pa.domain.capture.proposal import (
    MAX_NORMALIZED_VALUE_CHARACTERS,
    ProposalType,
    RiskClass,
)
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


def test_direct_promotion_global_guard_is_refused_before_any_store_is_read() -> None:
    """No proposal can become canonical without an accepting decision.

    Promotion accepts a proposal identifier, not a `ConsequentialClass`; the
    class gate is exhaustively proved above, while this independent global guard
    closes the only canonical writer before it can inspect any proposal class.
    """
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


def _port_correction(value: str) -> ReviewDecisionRequest:
    return ReviewDecisionRequest(
        review_case_id="rvw_wp8reviewcase01",
        expected_review_version=0,
        disposition=Disposition.CORRECT_AND_ACCEPT,
        principal_id="prn_wp8principal001",
        correlation_id="corr_wp8correlate01",
        audit_id="audit_wp8audit00001",
        policy_version="policy-v1",
        decided_at=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
        corrected_value=value,
    )


def test_corrected_value_bound_is_identical_at_command_and_port_boundaries() -> None:
    maximum = "x" * MAX_NORMALIZED_VALUE_CHARACTERS
    command = DecideReviewCase(
        review_case_id="rvw_wp8reviewcase01",
        expected_review_version=0,
        disposition=Disposition.CORRECT_AND_ACCEPT,
        corrected_value=maximum,
    )
    request = _port_correction(maximum)
    assert command.corrected_value == request.corrected_value == maximum

    too_long = "x" * (MAX_NORMALIZED_VALUE_CHARACTERS + 1)
    with pytest.raises(InvalidRequestError):
        DecideReviewCase(
            review_case_id="rvw_wp8reviewcase01",
            expected_review_version=0,
            disposition=Disposition.CORRECT_AND_ACCEPT,
            corrected_value=too_long,
        )
    with pytest.raises(ValueError, match="bounded"):
        _port_correction(too_long)


@pytest.mark.parametrize("blank", ["", " ", "\t\n"])
def test_command_and_port_correction_refuse_blank_values(blank: str) -> None:
    with pytest.raises(InvalidRequestError):
        DecideReviewCase(
            review_case_id="rvw_wp8reviewcase01",
            expected_review_version=0,
            disposition=Disposition.CORRECT_AND_ACCEPT,
            corrected_value=blank,
        )
    with pytest.raises(ValueError, match="not blank"):
        _port_correction(blank)


def test_corrected_content_is_absent_from_representations_and_safe_errors() -> None:
    marker = "PRIVATE-CORRECTION-MARKER"
    allowed = marker + "x" * (MAX_NORMALIZED_VALUE_CHARACTERS - len(marker))
    assert marker not in repr(
        DecideReviewCase(
            review_case_id="rvw_wp8reviewcase01",
            expected_review_version=0,
            disposition=Disposition.CORRECT_AND_ACCEPT,
            corrected_value=allowed,
        )
    )
    assert marker not in repr(_port_correction(allowed))

    refused = marker + "x" * MAX_NORMALIZED_VALUE_CHARACTERS
    failures: list[BaseException] = []
    with pytest.raises(InvalidRequestError) as command_error:
        DecideReviewCase(
            review_case_id="rvw_wp8reviewcase01",
            expected_review_version=0,
            disposition=Disposition.CORRECT_AND_ACCEPT,
            corrected_value=refused,
        )
    failures.append(command_error.value)
    with pytest.raises(ValueError) as port_error:
        _port_correction(refused)
    failures.append(port_error.value)

    for failure in failures:
        rendered = f"{failure!r} {failure.args} {failure.__cause__} {failure.__context__}"
        assert marker not in rendered
