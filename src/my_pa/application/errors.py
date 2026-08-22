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
