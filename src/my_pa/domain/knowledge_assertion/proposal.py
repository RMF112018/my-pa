"""Knowledge Review proposal value objects (KLP-WP-01).

A Knowledge proposal carries the same factual payload as the assertion it would
become (`KnowledgeAssertionCandidate`), so it uses the same single typed value
branch (AC-005) and its fingerprint is, by construction, the assertion
fingerprint of that candidate (plan section 6.5, AC-009). The proposal states,
risk classes and dispositions are the closed vocabularies of plan section 4;
`RiskClass` is the existing Capture enum, reused rather than redefined.
"""

from __future__ import annotations

from dataclasses import dataclass

from my_pa.domain.capture.proposal import RiskClass
from my_pa.domain.common.classification import Classification
from my_pa.domain.knowledge_assertion.assertion import KnowledgeAssertionCandidate
from my_pa.domain.knowledge_assertion.vocabulary import (
    OPEN_PROPOSAL_STATES,
    KnowledgeProposalState,
    KnowledgeReviewRequirement,
)

__all__ = ["InvalidKnowledgeProposalError", "KnowledgeProposalDraft"]


class InvalidKnowledgeProposalError(ValueError):
    """Raised when a proposal draft has an illegal shape."""


@dataclass(frozen=True, slots=True)
class KnowledgeProposalDraft:
    """An open Knowledge Review proposal before persistence."""

    candidate: KnowledgeAssertionCandidate
    review_requirement: KnowledgeReviewRequirement
    risk_class: RiskClass
    classification: Classification
    state: KnowledgeProposalState = KnowledgeProposalState.NEEDS_REVIEW

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, KnowledgeAssertionCandidate):
            raise InvalidKnowledgeProposalError("candidate must be a KnowledgeAssertionCandidate")
        if not isinstance(self.review_requirement, KnowledgeReviewRequirement):
            raise InvalidKnowledgeProposalError("review_requirement must be a closed token")
        if not isinstance(self.risk_class, RiskClass):
            raise InvalidKnowledgeProposalError("risk_class must be a closed token")
        if not isinstance(self.classification, Classification):
            raise InvalidKnowledgeProposalError("classification must be a closed token")
        if self.state not in OPEN_PROPOSAL_STATES:
            raise InvalidKnowledgeProposalError("a proposal draft is open")

    def fingerprint(self) -> str:
        """`proposal_fingerprint`, equal to the candidate's assertion fingerprint."""
        return self.candidate.fingerprint()
