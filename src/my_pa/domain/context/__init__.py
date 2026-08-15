"""Transport-neutral retrieval contract for `context.prepare`.

Distinct from `domain.modeling.gate`, which is the generative model-gate seam
and requires source identifiers on every evidence item.
"""

from my_pa.domain.context.prepared import (
    CONTEXT_POLICY_VERSION,
    CONTEXT_RANKING_VERSION,
    DEFAULT_EVIDENCE_BYTES,
    DEFAULT_EVIDENCE_ITEMS,
    MAX_CONVERSATION_CONTEXT_CHARACTERS,
    MAX_EVIDENCE_BYTES,
    MAX_EVIDENCE_ITEMS,
    MAX_EXCERPT_CHARACTERS,
    MAX_SUBJECT_HINTS,
    ContextCoverage,
    ContextLimitationCode,
    ContextPlane,
    ContextTruncation,
    ContradictionCode,
    ConversationContextError,
    CoverageState,
    EvidenceLifecycle,
    PreparedContext,
    PreparedContextError,
    PreparedContextEvidence,
    RetrievalMode,
    SelectionReasonCode,
    SourceAuthorityClass,
    validate_conversation_context,
)

__all__ = [
    "CONTEXT_POLICY_VERSION",
    "CONTEXT_RANKING_VERSION",
    "DEFAULT_EVIDENCE_BYTES",
    "DEFAULT_EVIDENCE_ITEMS",
    "MAX_CONVERSATION_CONTEXT_CHARACTERS",
    "MAX_EVIDENCE_BYTES",
    "MAX_EVIDENCE_ITEMS",
    "MAX_EXCERPT_CHARACTERS",
    "MAX_SUBJECT_HINTS",
    "ContextCoverage",
    "ContextLimitationCode",
    "ContextPlane",
    "ContextTruncation",
    "ContradictionCode",
    "ConversationContextError",
    "CoverageState",
    "EvidenceLifecycle",
    "PreparedContext",
    "PreparedContextError",
    "PreparedContextEvidence",
    "RetrievalMode",
    "SelectionReasonCode",
    "SourceAuthorityClass",
    "validate_conversation_context",
]
