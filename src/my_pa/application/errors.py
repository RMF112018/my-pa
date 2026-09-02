"""How an internal failure becomes one of the eleven public errors.

`docs/specs` section 10 fixes the taxonomy and then constrains what an error may
carry: no path, no provider detail, no query text, no stack trace, no database
detail, no credential, and no evidence of whether a denied object exists. Two
things here make that structural rather than a rule to remember.

**The message is a constant keyed by the code.** `_MESSAGES` is the whole set of
sentences this system can produce, and `problem_detail` looks the sentence up
rather than accepting one. There is no parameter a caller could interpolate a
rejected value into, so the "rejected value {x}" leak has nowhere to happen. The
messages are deliberately flat and uninformative in the same way the fixture
provider's single denial sentence is: `denied` and `not_found` share the posture
that a caller must not be able to subtract one answer from another to learn that
something exists.

**Detail is a closed token, not free text.** `ProblemDetail.safe_details` already
bounds an entry to a short lowercase token, and every value this module supplies
comes from `SafeDetail` below. A field name or a limit name is actionable; a
value is a disclosure, and there is no code path here that can pass one.

The exception types are one per code rather than one type with a code attribute,
because the classification is made at the point the failure is understood — a
`TraversalDeniedError` is `denied` where a `VersionChangedError` is `conflict`,
and those are decisions, not lookups. Raising the right type is how a use case
records which decision it made.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from my_pa.contracts.v1.errors import ErrorCode, ProblemDetail, retry_guidance_for

__all__ = [
    "AmbiguousRequestError",
    "ApplicationError",
    "ConflictError",
    "DeniedError",
    "InternalError",
    "InvalidRequestError",
    "NotFoundError",
    "QuarantinedError",
    "SafeDetail",
    "UnavailableError",
    "UnsupportedError",
    "problem_detail",
]


class SafeDetail(StrEnum):
    """Every token this layer may put in `safe_details`.

    Closed, because the field is the one remaining place a value could reach a
    public error. Each names a field, a bound, or a subject — never what was in
    one. New members are added with the code that can report them.
    """

    #: Which request field was rejected.
    SOURCE_ID = "source_id"
    SOURCE_OBJECT_ID = "source_object_id"
    ENROLLMENT_ID = "enrollment_id"
    OPERATION_ID = "operation_id"
    KNOWLEDGE_ID = "knowledge_id"
    CAPTURE_ID = "capture_id"
    VERSION_ID = "version_id"
    REVIEW_CASE_ID = "review_case_id"
    EXPECTED_REVIEW_VERSION = "expected_review_version"
    DISPOSITION = "disposition"
    CORRECTED_VALUE = "corrected_value"
    CAPTURE_KIND = "capture_kind"
    CONTEXT_SOURCE_OBJECT_ID = "context_source_object_id"
    CONTEXT_SOURCE_VERSION_ID = "context_source_version_id"
    TEXT = "text"
    CLIENT_CREATED_AT = "client_created_at"
    OCCURRED_AT = "occurred_at"
    QUERY = "query"
    CURSOR = "cursor"
    PAGE_SIZE = "page_size"
    SNIPPET_WORDS = "snippet_words"
    MAX_BYTES = "max_bytes"
    MAX_ITEMS = "max_items"
    MAX_CHARACTERS = "max_characters"
    DEPTH = "depth"
    MEDIA_TYPES = "media_types"
    IDEMPOTENCY_KEY = "idempotency_key"
    SELECTOR = "selector"
    REPRESENTATION = "representation"
    SUBJECT = "subject"
    CONVERSATION_CONTEXT = "conversation_context"
    SUBJECT_HINTS = "subject_hints"
    REQUESTED_PLANES = "requested_planes"
    TARGET_ID = "target_id"
    ACTION = "action"
    ALIAS = "alias"
    #: The managed-document plane's own fields (WP-28). Each names a field and
    #: never its value, exactly as every member above does — `TITLE` says the
    #: title was refused and never what it said, and `CONTENT` says the bytes
    #: were refused and carries none of them.
    DOCUMENT_ID = "document_id"
    EXPECTED_VERSION_NUMBER = "expected_version_number"
    TITLE = "title"
    NAME = "name"
    PROJECT_ID = "project_id"
    SITUATION_ID = "situation_id"
    DUE_AT = "due_at"
    MEDIA_TYPE = "media_type"
    CONTENT = "content"
    LIMIT = "limit"
    #: Which bound refused the request.
    MAX_ENROLLMENT_DEPTH = "max_enrollment_depth"
    MAX_CAPTURE_CHARACTERS = "max_capture_characters"
    #: Why a scope could not be resolved to exactly one grant.
    MULTIPLE_ENROLLMENTS_COVER_THE_SCOPE = "multiple_enrollments_cover_the_scope"
    #: What the extractor said about an object's content type.
    MEDIA_TYPE_NOT_EXTRACTABLE = "media_type_not_extractable"
    PROCESSING_STOPPED = "processing_stopped"
    #: The task-read plane's own fields (WP-TM-03). `TASK_ID` names the request
    #: field, exactly as `DOCUMENT_ID` and `CAPTURE_ID` do for their own planes;
    #: `LIFECYCLE_STATE` and `PRIORITY` name the two structured filters
    #: `tasks.list` accepts, and each says only that the filter value was
    #: rejected, never what it was.
    TASK_ID = "task_id"
    LIFECYCLE_STATE = "lifecycle_state"
    PRIORITY = "priority"
    #: The task-write plane's own fields (WP-TM-04). Each names a field and
    #: never its value, exactly as every member above does. `EXPECTED_VERSION`
    #: says the version was rejected, `ORIGIN_EVIDENCE_REF` says the evidence
    #: reference was rejected, and so on. `SCHEDULED_AT`, `DEFERRED_UNTIL`, and
    #: `CLOSURE_EVIDENCE_REF` are task-specific fields that may be rejected.
    #: `BULK_OPERATION_ID` names the bulk operation identifier, and `MUTATIONS`
    #: says the mutations list was rejected.
    EXPECTED_VERSION = "expected_version"
    ORIGIN_EVIDENCE_REF = "origin_evidence_ref"
    SCHEDULED_AT = "scheduled_at"
    DEFERRED_UNTIL = "deferred_until"
    CLOSURE_EVIDENCE_REF = "closure_evidence_ref"
    INVALID_EVIDENCE_REFERENCE = "invalid_evidence_reference"
    REVIEW_DECISION_ID = "review_decision_id"
    BULK_OPERATION_ID = "bulk_operation_id"
    MUTATIONS = "mutations"
    #: The Commitment plane's own fields (WP-TM-05), each naming a field and
    #: never its value, exactly as every member above does.
    #: `COUNTERPARTY_PERSON_ID` says the counterparty identifier was rejected
    #: — malformed, or, where a caller supplied more than one plausible
    #: candidate for it, ambiguous. `COMMITMENT_ID` names the request field,
    #: exactly as `TASK_ID` does for the task plane.
    COUNTERPARTY_PERSON_ID = "counterparty_person_id"
    COMMITMENT_ID = "commitment_id"
    #: The GoodNotes semantic plane's own fields (GN-04). Each names a field and
    #: never its value. Transcription is data and is never echoed here.
    RUN_ID = "run_id"
    AUTHORIZATION_ID = "authorization_id"
    CAMPAIGN_CLASS = "campaign_class"
    REPETITION = "repetition"
    PAGE_VERSION_ID = "page_version_id"
    CONTENT_SHA256 = "content_sha256"
    SCHEMA_VERSION = "schema_version"
    ANALYZER_NAME = "analyzer_name"
    ANALYZER_VERSION = "analyzer_version"
    SEGMENTS = "segments"
    GEOMETRY = "geometry"
    TRANSCRIPTION = "transcription"
    CANDIDATE_TAGS = "candidate_tags"
    RANKED_CANDIDATES = "ranked_candidates"
    CONFIDENCE = "confidence"
    #: Intelligence Artifact / Report plane. Each names a field and never its
    #: value. Markdown bodies and source URLs are data and are never echoed.
    CYCLE_RUN_ID = "cycle_run_id"
    ARTIFACT_ID = "artifact_id"
    FOCUS_AREA_ID = "focus_area_id"
    STAGE = "stage"
    ARTIFACT_KIND = "artifact_kind"
    SOURCE_LANE = "source_lane"
    REPORT_DATE = "report_date"
    SET_ID = "set_id"
    DEPENDENCY_REPORT_IDS = "dependency_report_ids"
    PROVENANCE = "provenance"
    STRUCTURED_CONTENT = "structured_content"
    BODY_MARKDOWN = "body_markdown"
    ADVISORY_DIGEST = "advisory_digest"
    #: The Relationship Memory plane. Field *names* only, as every member here
    #: is: `STATEMENT` names the field a malformed note arrived in and never
    #: carries the note, which is the whole reason this enum is a closed token
    #: set rather than a formatted message.
    MEMORY_ID = "memory_id"
    MEMORY_KIND = "memory_kind"
    SUBJECT_ENTITY_ID = "subject_entity_id"
    STATEMENT = "statement"
    STRUCTURED_VALUE = "structured_value"
    CONTEXT_LINKS = "context_links"
    PINNED = "pinned"
    LIFECYCLE = "lifecycle"
    KINDS = "kinds"
    AS_OF = "as_of"
    EFFECTIVE_FROM = "effective_from"
    EFFECTIVE_TO = "effective_to"
    CORRECTION_REASON = "correction_reason"
    INCLUDE_STATEMENT = "include_statement"
    OBSERVED_AT = "observed_at"
    #: The entity plane's authoring fields (WP-RI-A-02). Field *names* only, as
    #: every member here is. `ENTITY_ID` is new and was overdue: `entities.get`
    #: answered a missing entity with `TARGET_ID`, which is the generic token
    #: and says nothing about which of a request's several identifiers was the
    #: one that did not resolve. A write naming an entity, an identifier and a
    #: cursor at once needs three tokens, not one repeated.
    ENTITY_ID = "entity_id"
    ENTITY_TYPE = "entity_type"
    IDENTIFIER_ID = "identifier_id"
    ALIAS_ID = "alias_id"
    ALIAS_TYPE = "alias_type"
    NAMESPACE = "namespace"
    DISPLAY_NAME = "display_name"
    DISPLAY_VALUE = "display_value"
    CANONICAL_NAME = "canonical_name"
    STATUS = "status"
    REASON = "reason"
    EVIDENCE = "evidence"
    IDENTIFIERS = "identifiers"
    ALIASES = "aliases"
    STATES = "states"
    NAMESPACES = "namespaces"
    ALIAS_TYPES = "alias_types"
    EXPECTED_IDENTIFIER_VERSION = "expected_identifier_version"
    EXPECTED_ALIAS_VERSION = "expected_alias_version"
    #: The completion contract's stable outcome codes, carried as details on the
    #: eleven public error codes rather than as new members of `ErrorCode`.
    #:
    #: **Each names an outcome, and the public code alone cannot.** `conflict`
    #: is one code covering a stale version, a spent idempotency key, a
    #: duplicated fact and an address two entities claim — four different next
    #: actions, and a caller told only `conflict` has to guess which. These
    #: tokens are what the contract fixes, so they are what the token set
    #: carries.
    #:
    #: They are deliberately distinct from the field names above.
    #: `EXPECTED_VERSION` says the field was malformed; `STALE_VERSION` says it
    #: was well-formed and no longer current. `IDEMPOTENCY_KEY` says the key was
    #: malformed; `IDEMPOTENCY_CONFLICT` says it is bound to a different
    #: request. Collapsing either pair would make a caller's own correctable
    #: mistake indistinguishable from a state it has to re-read.
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    CONFLICTED_IDENTIFIER = "conflicted_identifier"
    HISTORICAL_ENTITY = "historical_entity"
    STALE_VERSION = "stale_version"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    DUPLICATE_FACT = "duplicate_fact"
    EVIDENCE_INVALID = "evidence_invalid"
    #: Not a conflict and not the caller's fault: a binding the store could not
    #: settle against a concurrent retirement, which is `unavailable` and
    #: retryable. Named so a caller can tell it from `CONFLICTED_IDENTIFIER`,
    #: which is permanent and must not be retried.
    CONCURRENT_RETIREMENT = "concurrent_retirement"
    #: The entity plane's directed-relationship writes (WP-RI-A-03). Field
    #: *names* only, as every member here is. Two of them are worth stating
    #: plainly: `REASON` — declared with the authoring fields above and shared
    #: with them — says the explanation attached to an `end` was refused and
    #: never carries a word of it, and `EVIDENCE_REFS` says a cited reference
    #: was refused without saying which one or whether it exists — which is the
    #: same collapse `NotFoundError` makes, kept here so a caller cannot
    #: subtract one answer from another to learn what another Principal holds.
    #: `ENTITY_ID` is shared with the authoring block for the same reason and is
    #: not redeclared: one token, one meaning, across all of `entities.`.
    FROM_ENTITY_ID = "from_entity_id"
    TO_ENTITY_ID = "to_entity_id"
    SCOPE_ENTITY_ID = "scope_entity_id"
    ASSIGNMENT_ID = "assignment_id"
    ASSIGNMENT_TYPE = "assignment_type"
    RELATIONSHIP_ID = "relationship_id"
    RELATIONSHIP_TYPE = "relationship_type"
    ROLE = "role"
    DISCIPLINE = "discipline"
    RESPONSIBILITY_CLASS = "responsibility_class"
    EXPECTED_ENTITY_VERSION = "expected_entity_version"
    EXPECTED_SCOPE_VERSION = "expected_scope_version"
    EVIDENCE_REFS = "evidence_refs"
    END_NOW = "end_now"
    ACTIVE_ONLY = "active_only"
    #: The observation and resolution surface (WP-RI-A-04). The field tokens
    #: name a field and never carry its value -- `OBSERVED_VALUE` is the token
    #: `observed_value`, which is what a caller needs in order to correct the
    #: request, and the name or address it rejected stays where it was sent.
    #: `ENTITY_ID`, `ENTITY_TYPE`, `CANONICAL_NAME` and `REASON` are declared
    #: with the authoring fields above and shared with this surface rather than
    #: redeclared: one token, one meaning, across all of `entities.`.
    OBSERVATION_ID = "observation_id"
    OBSERVATION_KIND = "observation_kind"
    OBSERVATION_AUTHORITY = "observation_authority"
    OBSERVED_VALUE = "observed_value"
    MENTION_DISPLAY_NAME = "mention_display_name"
    SOURCE_VERSION_ID = "source_version_id"
    CAPTURE_VERSION_ID = "capture_version_id"
    EXPECTED_RESOLUTION_VERSION = "expected_resolution_version"
    REJECTED_ENTITY_ID = "rejected_entity_id"
    #: The fifth verdict the Relationship Intelligence contract fixes as a
    #: stable problem, beside the four the authoring block already declares
    #: (`AMBIGUOUS_IDENTITY`, `CONFLICTED_IDENTIFIER`, `HISTORICAL_ENTITY` and
    #: `EVIDENCE_INVALID`). It is a `safe_details` token over the existing
    #: eleven `ErrorCode` members rather than a new member of that enum: the
    #: code says what class of failure this is and the detail says which rule
    #: refused, and a twelfth code would make every reader that switches on the
    #: eleven wrong.
    REVIEW_REQUIRED = "review_required"
    #: Governed identity correction (WP-RI-06). Four tokens over the existing
    #: eleven `ErrorCode` members, declared on the same argument the completion
    #: contract's outcome codes above are: the code says what class of failure
    #: this is and the detail says which rule refused.
    #:
    #: `PREVIEW_EXPIRED` and `PREVIEW_STALE` are both `conflict` and are
    #: deliberately different tokens, because the next action differs: an expired
    #: preview needs a fresh one, and a stale one needs the operator to re-read
    #: what changed before asking for a fresh one.
    #:
    #: **`PREVIEW_STALE` covers a mismatched digest as well as version drift,
    #: and the collapse is deliberate.** A caller that could tell "your preview
    #: is for different entities" from "your preview is for these entities at
    #: different versions" learns which half of a forged token was wrong, which
    #: is a probe. Both answers require the same thing -- ask for a new preview
    #: and read it -- so one token is the whole of what a caller can act on.
    #:
    #: `OPERATOR_REQUIRED` is `denied` and says the acting context declared no
    #: operator authority. It is distinct from `REVIEW_REQUIRED`: a reviewer who
    #: may decide an identity-correction proposal still may not execute one, and
    #: a caller told the wrong token would go and find a reviewer.
    #:
    #: `IDENTITY_CORRECTION_CONFLICT` is the blocking-conflict answer -- a
    #: preview already consumed, or a record family this phase cannot transform
    #: with reversible lineage. It names no record, because a merge blocker is a
    #: statement about somebody's identity and the enumeration belongs in the
    #: preview the operator asked for, not in an error a client logs.
    PREVIEW_EXPIRED = "preview_expired"
    PREVIEW_STALE = "preview_stale"
    OPERATOR_REQUIRED = "operator_required"
    IDENTITY_CORRECTION_CONFLICT = "identity_correction_conflict"
    #: The transport fields `WP-RI-B-05` and `WP-RI-B-06` accept, which nothing
    #: else names.
    #: Each is the transport field's own name, which is this enum's rule -- a
    #: token names a *field* and never a value -- and each is added rather than
    #: reused because no existing member names the same field. `PAYLOAD` is the
    #: one worth arguing about: a proposal's `payload` is a nested object whose
    #: admitted names come from the kind, so a refusal of a name inside it is
    #: still a refusal of `payload`, and a token per admitted name would restate
    #: seventeen schemas here.
    #:
    #: **Four tokens B4 offered and this package declined**, recorded here so
    #: the decision is legible rather than a silence: `CORRECTION_PATCH`,
    #: `SUBJECT_KIND`, `PROPOSAL_STATE` and a repointing of a Review reason from
    #: `ACTION` to `REASON`. Every one of the four sites already names a field
    #: and discloses nothing, which is the whole of this enum's rule, so they are
    #: imprecise rather than unsafe. The sharpest of them, `CORRECTED_VALUE` on a
    #: refused `correction_patch`, cannot be made exact by a token alone:
    #: `_review_decide` catches one `ReviewCorrectionError` raised by both the
    #: bounded-string path and the typed-patch path, so reporting
    #: `correction_patch` there would replace an imprecise token with a wrong one
    #: for half the refusals. Making it exact needs the domain error to carry
    #: which field failed, which is a change to `domain/capture/review.py` that no
    #: Phase B contract asks for.
    PROPOSAL_KIND = "kind"
    PAYLOAD = "payload"
    PROPOSED_BY = "proposed_by"
    MERGED_AWAY = "merged_away"
    PREVIEW_ID = "preview_id"
    PREVIEW_DIGEST = "preview_digest"
    CHOICES = "choices"

    #: `RI-ENT-WP-11`'s record-family write fields. One token per field a
    #: command can actually refuse, added with the code that reports it, which
    #: is what this enum's own docstring asks for.
    #:
    #: **A token per field rather than one per family.** A caller told
    #: `target_id` when the value it got wrong was `name_type_code` learns which
    #: request failed and not which part of it, and these commands carry up to
    #: fifteen caller-supplied fields each. The lifecycle writes already set the
    #: precedent -- `assignment_id`, `alias_id`, `identifier_id` are three
    #: tokens for three identifiers rather than one shared `record_id`.
    #:
    #: Each names a *field*, never a value: which key was rejected, and nothing
    #: about what was in it. A display value, an address line and a job title
    #: are exactly the content this vocabulary exists to keep out of a public
    #: error, and none of them is echoed by naming the key it arrived under.
    ENTITY_NAME_ID = "entity_name_id"
    NAME_TYPE_CODE = "name_type_code"
    IS_PREFERRED = "is_preferred"


#: The complete set of sentences a public error may carry. Flat on purpose: a
#: message that described the request would describe it to whoever guessed it.
_MESSAGES: Mapping[ErrorCode, str] = MappingProxyType(
    {
        ErrorCode.INVALID_REQUEST: "the request is malformed, incomplete, or contradictory",
        ErrorCode.AMBIGUOUS_REQUEST: "the request names more than one plausible subject",
        ErrorCode.DENIED: "the request is not permitted for this principal, purpose, and scope",
        ErrorCode.UNAVAILABLE: "the requested evidence is temporarily unavailable",
        ErrorCode.UNSUPPORTED: "the requested capability, media type, or representation "
        "is not supported",
        ErrorCode.NOT_FOUND: "no record matches the request within the authorized scope",
        ErrorCode.CONFLICT: "the request conflicts with the current state",
        ErrorCode.RATE_LIMITED: "a resource limit was reached",
        ErrorCode.QUARANTINED: "processing of the requested evidence was stopped by policy",
        ErrorCode.CANCELLED: "the operation was cancelled",
        ErrorCode.INTERNAL_ERROR: "the request could not be completed",
    }
)


class ApplicationError(Exception):
    """A failure this layer has already classified into a public error code.

    The message a caller receives comes from `_MESSAGES`, never from the
    exception, so the string passed to `Exception.__init__` stays an internal
    label and cannot become a disclosure channel by being rendered.
    """

    code: ErrorCode = ErrorCode.INTERNAL_ERROR

    def __init__(self, *details: SafeDetail) -> None:
        super().__init__(self.code.value)
        self.safe_details: tuple[SafeDetail, ...] = details


class InvalidRequestError(ApplicationError):
    """Malformed, missing, contradictory, or out-of-bounds request fields."""

    code = ErrorCode.INVALID_REQUEST


class AmbiguousRequestError(ApplicationError):
    """More than one plausible scope, selector, or identity. Never guessed."""

    code = ErrorCode.AMBIGUOUS_REQUEST


class DeniedError(ApplicationError):
    """Principal, purpose, scope, or policy disallows the request.

    Carries no denial reason into the public payload. The reason is recorded in
    the audit event, where the operator can read it and a caller cannot.
    """

    code = ErrorCode.DENIED


class UnavailableError(ApplicationError):
    """Source, persistence, extractor, or evidence could not be reached."""

    code = ErrorCode.UNAVAILABLE


class UnsupportedError(ApplicationError):
    """A capability, media type, range, or representation this build does not serve."""

    code = ErrorCode.UNSUPPORTED


class NotFoundError(ApplicationError):
    """An authorized lookup matched nothing.

    Indistinguishable from a denial by design: both messages are flat and
    neither states whether the subject exists.
    """

    code = ErrorCode.NOT_FOUND


class ConflictError(ApplicationError):
    """A version, idempotency, cursor, or state conflict. Retry after refresh."""

    code = ErrorCode.CONFLICT


class QuarantinedError(ApplicationError):
    """Processing was stopped by security or quality policy."""

    code = ErrorCode.QUARANTINED


class InternalError(ApplicationError):
    """An unexpected failure, reported generically."""

    code = ErrorCode.INTERNAL_ERROR


def problem_detail(error: ApplicationError, *, correlation_id: str) -> ProblemDetail:
    """Render `error` as the public problem it was already classified as.

    The retry guidance is looked up from the code rather than chosen here, so
    the contract's own table decides it and this module cannot disagree with it.
    """
    return ProblemDetail(
        code=error.code,
        message=_MESSAGES[error.code],
        correlation_id=correlation_id,
        retry=retry_guidance_for(error.code),
        safe_details=tuple(detail.value for detail in error.safe_details),
    )
