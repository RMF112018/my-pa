"""The authority and disclosure boundary for bounded model assistance.

Retrieved text is carried only as explicitly labelled untrusted evidence.  A
provider can return structured proposals, but cannot name a capability, policy
decision, Principal, or durable mutation.  Semantic retrieval has a separate
three-part gate and remains disabled until every part has passed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier


class ModelRoutePolicy(StrEnum):
    DISABLED = "disabled"
    LOCAL_PROPOSALS_ONLY = "local_proposals_only"


@dataclass(frozen=True, slots=True)
class SemanticRetrievalGate:
    benchmark_passed: bool = False
    security_review_passed: bool = False
    privacy_review_passed: bool = False

    @property
    def enabled(self) -> bool:
        return self.benchmark_passed and self.security_review_passed and self.privacy_review_passed


@dataclass(frozen=True, slots=True)
class ContextEvidence:
    """One exact lexical/evidence retrieval result, never an instruction."""

    reference_id: str
    principal_id: str
    source_id: str
    source_object_id: str
    source_version_id: str
    text: str = field(repr=False)
    span_start: int = 0
    span_end: int = 0
    instruction_authority: bool = False

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.source_id, IdKind.SOURCE)
        validate_identifier(self.source_object_id, IdKind.SOURCE_OBJECT)
        validate_identifier(self.source_version_id, IdKind.VERSION)
        if not self.reference_id or len(self.reference_id) > 80:
            raise ValueError("an evidence reference is required and bounded")
        if self.instruction_authority:
            raise ValueError("retrieved content cannot have instruction authority")
        if self.span_start < 0 or self.span_end < self.span_start or self.span_end > len(self.text):
            raise ValueError("evidence span is outside the retrieved text")


@dataclass(frozen=True, slots=True)
class ContextManifest:
    principal_id: str
    purpose: str
    provider_id: str
    model_id: str
    prompt_schema_version: str
    policy_version: str
    evidence: tuple[ContextEvidence, ...]
    external_disclosure_allowed: bool = False

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        for value in (
            self.purpose,
            self.provider_id,
            self.model_id,
            self.prompt_schema_version,
            self.policy_version,
        ):
            if not value or len(value) > 100:
                raise ValueError("model context metadata is required and bounded")
        if not self.evidence:
            raise ValueError("a model context must cite evidence")
        if any(item.principal_id != self.principal_id for item in self.evidence):
            raise ValueError("model context evidence crossed its Principal boundary")


@dataclass(frozen=True, slots=True)
class ModelProposal:
    """A provider's structured, noncanonical output."""

    proposal_type: str
    normalized_value: str = field(repr=False)
    evidence_reference_ids: tuple[str, ...]
    confidence: float

    def __post_init__(self) -> None:
        if not self.proposal_type or len(self.proposal_type) > 64:
            raise ValueError("proposal_type is required and bounded")
        if not self.normalized_value or len(self.normalized_value) > 4096:
            raise ValueError("normalized_value is required and bounded")
        if not self.evidence_reference_ids or len(set(self.evidence_reference_ids)) != len(
            self.evidence_reference_ids
        ):
            raise ValueError("a proposal must cite distinct evidence")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between zero and one")
