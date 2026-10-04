"""Closed vocabularies of the Knowledge Assertion plane (KLP-WP-01).

Each enum here is one closed column set of the R6 contract (plan section 4,
matrix `closed_vocabularies`), with the members spelled and ordered exactly as
the matrix lists them. `tests/unit/test_knowledge_assertion_domain.py` holds
every enum equal to the committed matrix copy
(`tests/architecture/klp_implementation_matrix_r6.json`), so a member cannot be
added, removed, renamed or reordered here without that test going red.

The WP-02 revision restates the same lists as frozen literals and never derives
them from these enums: a schema revision is a fixed point in history and must
not change meaning when Python changes.

Existing enums are reused rather than redefined: `Classification`
(`domain.common.classification`), `EntityType` (`domain.relationship.entity`)
and `RiskClass` (`domain.capture.proposal`). The "+1" additions to existing
enums (`ReviewSubjectKind`, `RecordEventFamily`, `ContextPlane`,
`SourceAuthorityClass`, the two context codes) and the new `OperatorSurface`
belong to WP-03/04/06 and are deliberately absent here.

Pure data: this module imports nothing from persistence and grants nothing.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from my_pa.domain.common.classification import Classification

__all__ = [
    "KNOWLEDGE_CLASSIFICATION_FLOORS",
    "LIVE_ASSERTION_LIFECYCLES",
    "OPEN_PROPOSAL_STATES",
    "RESPONSE_ONLY_SUBMISSION_REASONS",
    "STORED_SUBMISSION_REASONS",
    "TERMINAL_PROPOSAL_STATES",
    "KnowledgeAssertionLifecycle",
    "KnowledgeAutonomousAdmissionPolicy",
    "KnowledgeCanonicalOwner",
    "KnowledgeCardinality",
    "KnowledgeCheckpointKind",
    "KnowledgeCheckpointOutcome",
    "KnowledgeCheckpointReason",
    "KnowledgeConflictRule",
    "KnowledgeConsequentialClass",
    "KnowledgeContentOrigin",
    "KnowledgeDateKind",
    "KnowledgeDecisionChannel",
    "KnowledgeEpistemicStatus",
    "KnowledgeEvidenceAuthority",
    "KnowledgeEvidenceAvailability",
    "KnowledgeEvidenceIdentityKind",
    "KnowledgeEvidenceRole",
    "KnowledgeLedgerState",
    "KnowledgeMutationKind",
    "KnowledgeNormalizationRule",
    "KnowledgeOriginSystem",
    "KnowledgeOwnerRefKind",
    "KnowledgePredicateAdmissionState",
    "KnowledgeProposalState",
    "KnowledgeQualifierRule",
    "KnowledgeReadOnlyProofState",
    "KnowledgeReviewAuthorityClass",
    "KnowledgeReviewDisposition",
    "KnowledgeReviewRequirement",
    "KnowledgeSubjectKind",
    "KnowledgeSubmissionOrigin",
    "KnowledgeSubmissionOutcome",
    "KnowledgeSubmissionReason",
    "KnowledgeTemporalSemantics",
    "KnowledgeValueType",
]


class KnowledgeSubjectKind(StrEnum):
    """Matrix `knowledge_subject_kind`."""

    PRINCIPAL = "principal"
    ENTITY = "entity"
    PROJECT = "project"
    MANAGED_DOCUMENT = "managed_document"
    EVIDENCE_REF = "evidence_ref"


class KnowledgeValueType(StrEnum):
    """Matrix `knowledge_value_type`."""

    TEXT = "text"
    DATETIME = "datetime"


class KnowledgeCardinality(StrEnum):
    """Matrix `knowledge_cardinality`."""

    SINGLE_CURRENT = "single_current"
    MULTI_VALUE = "multi_value"


class KnowledgeTemporalSemantics(StrEnum):
    """Matrix `knowledge_temporal_semantics`."""

    ATEMPORAL = "atemporal"
    OBSERVED_STATE = "observed_state"
    HISTORICAL = "historical"


class KnowledgeQualifierRule(StrEnum):
    """Matrix `knowledge_qualifier_rule`."""

    NONE = "none"
    DATE_KIND = "date_kind"


class KnowledgeDateKind(StrEnum):
    """Matrix `knowledge_date_kind`."""

    MILESTONE = "milestone"
    DEADLINE = "deadline"
    INSPECTION = "inspection"
    DELIVERY = "delivery"
    EXPIRY = "expiry"


class KnowledgeCanonicalOwner(StrEnum):
    """Matrix `knowledge_canonical_owner`."""

    KNOWLEDGE_ASSERTION = "knowledge_assertion"
    CONTINUITY_DECISION = "continuity_decision"
    RELATIONSHIP_MEMORY = "relationship_memory"
    ENTITY = "entity"
    CONSTRAINTS = "constraints"
    TASKS = "tasks"
    COMMITMENTS = "commitments"
    MEETINGS = "meetings"
    MANAGED_DOCUMENT = "managed_document"


class KnowledgeAutonomousAdmissionPolicy(StrEnum):
    """Matrix `knowledge_autonomous_admission_policy`."""

    NEVER = "never"
    AUTHORITATIVE_SOURCE = "authoritative_source"


class KnowledgeReviewRequirement(StrEnum):
    """Matrix `knowledge_review_requirement`."""

    REQUIRES_REVIEW = "requires_review"
    REQUIRES_OPERATOR = "requires_operator"


class KnowledgeConsequentialClass(StrEnum):
    """Matrix `knowledge_consequential_class`."""

    NONE = "none"
    FINANCIAL_FACT = "financial_fact"
    DECISION = "decision"
    CRITICAL_DATE = "critical_date"


class KnowledgeNormalizationRule(StrEnum):
    """Matrix `knowledge_normalization_rule`."""

    TEXT_NFC_TRIM_COLLAPSE_WHITESPACE = "text_nfc_trim_collapse_whitespace"
    DATETIME_UTC_MICROSECOND = "datetime_utc_microsecond"


class KnowledgeConflictRule(StrEnum):
    """Matrix `knowledge_conflict_rule`."""

    REVIEW_ON_DIFFERENCE = "review_on_difference"
    COEXIST = "coexist"


class KnowledgeEvidenceAuthority(StrEnum):
    """Matrix `knowledge_evidence_authority`."""

    OBSERVED_SOURCE = "observed_source"
    AUTHORITATIVE_SOURCE = "authoritative_source"


class KnowledgePredicateAdmissionState(StrEnum):
    """Matrix `knowledge_predicate_admission_state`."""

    ACTIVE = "active"
    RETIRED = "retired"


class KnowledgeAssertionLifecycle(StrEnum):
    """Matrix `knowledge_assertion_lifecycle`."""

    ACTIVE = "active"
    REVALIDATION_REQUIRED = "revalidation_required"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class KnowledgeEpistemicStatus(StrEnum):
    """Matrix `knowledge_epistemic_status`."""

    SOURCE_OBSERVED = "source_observed"
    PRINCIPAL_ASSERTED = "principal_asserted"
    REVIEW_ACCEPTED = "review_accepted"
    CONTESTED = "contested"


class KnowledgeMutationKind(StrEnum):
    """Matrix `knowledge_mutation_kind`."""

    CREATE = "create"
    REVIEW_ACCEPT = "review_accept"
    REVIEW_CORRECT = "review_correct"
    SUPERSEDE_SUCCESSOR = "supersede_successor"
    SUPERSEDE_PREDECESSOR = "supersede_predecessor"
    EVIDENCE_ENRICH = "evidence_enrich"
    CLASSIFY = "classify"
    REVALIDATION_REQUIRED = "revalidation_required"
    REVALIDATION_CLEARED = "revalidation_cleared"
    ARCHIVE = "archive"


class KnowledgeEvidenceIdentityKind(StrEnum):
    """Matrix `knowledge_evidence_identity_kind`."""

    EXTERNAL_OBJECT = "external_object"
    CAPTURE = "capture"
    RELATIONSHIP_MEMORY = "relationship_memory"


class KnowledgeContentOrigin(StrEnum):
    """Matrix `knowledge_content_origin`."""

    EXTERNAL_SOURCE = "external_source"
    SYNTHETIC_SOURCE = "synthetic_source"
    CAPTURE = "capture"
    RELATIONSHIP_MEMORY = "relationship_memory"


class KnowledgeEvidenceAvailability(StrEnum):
    """Matrix `knowledge_evidence_availability`."""

    AVAILABLE = "available"
    PERMISSION_LOST = "permission_lost"
    DELETED = "deleted"


class KnowledgeEvidenceRole(StrEnum):
    """Matrix `knowledge_evidence_role`."""

    DIRECT = "direct"
    SUPPORTING = "supporting"
    COUNTEREVIDENCE = "counterevidence"


class KnowledgeSubmissionOrigin(StrEnum):
    """Matrix `knowledge_submission_origin`."""

    EXPLICIT_CREATE = "explicit_create"
    AUTONOMOUS_SUBMIT = "autonomous_submit"


class KnowledgeLedgerState(StrEnum):
    """Matrix `knowledge_ledger_state`."""

    RESERVED = "reserved"
    COMPLETED = "completed"


class KnowledgeSubmissionOutcome(StrEnum):
    """Matrix `knowledge_submission_outcome`."""

    DIRECT_CREATED = "direct_created"
    DIRECT_SUPERSEDED = "direct_superseded"
    REVIEW_QUEUED = "review_queued"
    DUPLICATE_EXISTING = "duplicate_existing"
    DUPLICATE_ENRICHED = "duplicate_enriched"
    DUPLICATE_PENDING_REVIEW = "duplicate_pending_review"
    DOMAIN_OWNED_ROUTED = "domain_owned_routed"
    DOMAIN_OWNED_NO_INTAKE = "domain_owned_no_intake"
    CONFLICT = "conflict"
    REFUSED = "refused"


class KnowledgeSubmissionReason(StrEnum):
    """Matrix `knowledge_submission_reason`."""

    CREATED = "created"
    SUPERSEDED = "superseded"
    REQUIRES_REVIEW = "requires_review"
    REQUIRES_OPERATOR = "requires_operator"
    EXACT_DUPLICATE = "exact_duplicate"
    EVIDENCE_ENRICHED = "evidence_enriched"
    PENDING_REVIEW_EXISTS = "pending_review_exists"
    CANONICAL_OWNER = "canonical_owner"
    CANONICAL_OWNER_NO_INTAKE = "canonical_owner_no_intake"
    INCOMPATIBLE_CURRENT_FACT = "incompatible_current_fact"
    SOURCE_PROFILE_INACTIVE = "source_profile_inactive"
    SOURCE_AUTHORITY_INSUFFICIENT = "source_authority_insufficient"
    CAPTURE_ARCHIVED = "capture_archived"
    SUBJECT_NOT_CANONICAL = "subject_not_canonical"
    OWNER_REF_INVALID = "owner_ref_invalid"
    CAUSAL_DEPTH_EXCEEDED = "causal_depth_exceeded"
    CAUSAL_ROOT_AMBIGUOUS = "causal_root_ambiguous"
    CAUSAL_REPEAT = "causal_repeat"
    CAUSAL_RATE_EXCEEDED = "causal_rate_exceeded"
    CLASSIFICATION_REFUSED = "classification_refused"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    CHECKPOINT_CONFLICT = "checkpoint_conflict"


class KnowledgeOwnerRefKind(StrEnum):
    """Matrix `knowledge_owner_ref_kind`."""

    TASK = "task"
    COMMITMENT = "commitment"
    CONSTRAINT = "constraint"
    MEETING = "meeting"


class KnowledgeProposalState(StrEnum):
    """Matrix `knowledge_proposal_state`."""

    NEEDS_REVIEW = "needs_review"
    DEFERRED = "deferred"
    UNRESOLVED = "unresolved"
    ACCEPTED = "accepted"
    CORRECTED_ACCEPTED = "corrected_accepted"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"
    SUPERSEDED = "superseded"


class KnowledgeReviewDisposition(StrEnum):
    """Matrix `knowledge_review_disposition`."""

    ACCEPT = "accept"
    CORRECT_AND_ACCEPT = "correct_and_accept"
    REJECT = "reject"
    DEFER = "defer"
    MARK_UNRESOLVED = "mark_unresolved"
    INVALIDATE = "invalidate"


class KnowledgeDecisionChannel(StrEnum):
    """Matrix `knowledge_decision_channel`."""

    LOCAL_CLI = "local_cli"
    LOCAL_WEB = "local_web"
    LOCAL_UNATTESTED = "local_unattested"
    REMOTE_INTERACTIVE = "remote_interactive"
    REMOTE_OPERATOR_REVIEW = "remote_operator_review"


class KnowledgeReviewAuthorityClass(StrEnum):
    """Matrix `knowledge_review_authority_class`."""

    ORDINARY_REVIEWER = "ordinary_reviewer"
    LOCAL_OPERATOR = "local_operator"
    REMOTE_OPERATOR_ATTESTED = "remote_operator_attested"


class KnowledgeCheckpointKind(StrEnum):
    """Matrix `knowledge_checkpoint_kind`."""

    DELTA_TOKEN = "delta_token"  # noqa: S105 - a checkpoint kind, not a credential
    PAGE_CURSOR = "page_cursor"
    SYNTHETIC = "synthetic"


class KnowledgeCheckpointOutcome(StrEnum):
    """Matrix `knowledge_checkpoint_outcome`."""

    ADVANCED = "advanced"
    CHECKPOINT_CONFLICT = "checkpoint_conflict"
    REFUSED = "refused"


class KnowledgeCheckpointReason(StrEnum):
    """Matrix `knowledge_checkpoint_reason`."""

    ADVANCED = "advanced"
    STALE_EXPECTED_VERSION = "stale_expected_version"
    ENVELOPE_UNVERIFIABLE = "envelope_unverifiable"
    SOURCE_PROFILE_INACTIVE = "source_profile_inactive"
    CANDIDATE_COUNT_MISMATCH = "candidate_count_mismatch"


class KnowledgeOriginSystem(StrEnum):
    """Matrix `knowledge_origin_system`."""

    OUTLOOK_MAIL = "outlook_mail"
    SHAREPOINT_DOCUMENTS = "sharepoint_documents"
    TEAMS_MESSAGES = "teams_messages"
    PUBLIC_WEB = "public_web"
    SYNTHETIC = "synthetic"


class KnowledgeReadOnlyProofState(StrEnum):
    """Matrix `knowledge_read_only_proof_state`."""

    UNPROVEN = "unproven"
    PROVEN = "proven"
    REVOKED = "revoked"


#: `knowledge_classification_floor`: the `Classification` subset a predicate may
#: name as its floor. `synthetic_test` is never a floor; only a synthetic source
#: profile can lower a row to it (R6 section 5.1, AC-059).
KNOWLEDGE_CLASSIFICATION_FLOORS: Final[tuple[Classification, ...]] = (
    Classification.PRIVATE_LOCAL,
    Classification.RESTRICTED_LOCAL,
)

#: The two reasons that are answered but never stored: an idempotency or
#: checkpoint conflict writes no row, so the stored-subset CHECK
#: `knowledge_submission_reason_is_known` excludes them (R6 section 4).
RESPONSE_ONLY_SUBMISSION_REASONS: Final[frozenset[KnowledgeSubmissionReason]] = frozenset(
    {
        KnowledgeSubmissionReason.IDEMPOTENCY_CONFLICT,
        KnowledgeSubmissionReason.CHECKPOINT_CONFLICT,
    }
)

#: `knowledge_assertion_submissions.reason` may hold exactly these, in enum order.
STORED_SUBMISSION_REASONS: Final[tuple[KnowledgeSubmissionReason, ...]] = tuple(
    reason for reason in KnowledgeSubmissionReason if reason not in RESPONSE_ONLY_SUBMISSION_REASONS
)

#: Live = {active, revalidation_required}; superseded and archived are terminal.
LIVE_ASSERTION_LIFECYCLES: Final[frozenset[KnowledgeAssertionLifecycle]] = frozenset(
    {KnowledgeAssertionLifecycle.ACTIVE, KnowledgeAssertionLifecycle.REVALIDATION_REQUIRED}
)

#: Open = {needs_review, deferred, unresolved}; the other five are terminal.
OPEN_PROPOSAL_STATES: Final[frozenset[KnowledgeProposalState]] = frozenset(
    {
        KnowledgeProposalState.NEEDS_REVIEW,
        KnowledgeProposalState.DEFERRED,
        KnowledgeProposalState.UNRESOLVED,
    }
)
TERMINAL_PROPOSAL_STATES: Final[frozenset[KnowledgeProposalState]] = frozenset(
    set(KnowledgeProposalState) - OPEN_PROPOSAL_STATES
)
