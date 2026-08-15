"""The retrieval contract: a bounded, provenance-rich context package.

This is not `domain.modeling.gate.ContextManifest`. That type is the generative
model-gate seam and requires `source_id` / `source_object_id` / `source_version_id`
on every evidence item, plus `model_id` and `provider_id` on the package.
`PreparedContext` is the transport-neutral answer `context.prepare` returns: it
can cite enrolled source evidence *and* product-owned capture, continuity,
relationship, and managed-document evidence without inventing fake source IDs,
and it does not require a model route.

Retrieved text is data. `instruction_authority` is structurally false: an
evidence item that claims otherwise cannot be constructed. Empty evidence is
valid — a no-match with `searched_complete` versus `unavailable` is a coverage
and limitation distinction, not a missing-evidence error.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import (
    IdKind,
    InvalidIdentifierError,
    parse_identifier,
    validate_identifier,
)
from my_pa.domain.common.time import ensure_utc, format_rfc3339
from my_pa.domain.search.query import MAX_SNIPPET_CHARACTERS

__all__ = [
    "CONTEXT_POLICY_VERSION",
    "CONTEXT_RANKING_VERSION",
    "DEFAULT_EVIDENCE_BYTES",
    "DEFAULT_EVIDENCE_ITEMS",
    "MAX_CONVERSATION_CONTEXT_CHARACTERS",
    "MAX_EVIDENCE_BYTES",
    "MAX_EVIDENCE_ITEMS",
    "MAX_EVIDENCE_REFERENCE_BYTES",
    "MAX_EXCERPT_CHARACTERS",
    "MAX_METADATA_CHARACTERS",
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

#: Stay strictly below the model-gate ceiling of 100 items / 1_048_576 bytes.
MAX_EVIDENCE_ITEMS: Final = 32
MAX_EVIDENCE_BYTES: Final = 65_536
DEFAULT_EVIDENCE_ITEMS: Final = 16
DEFAULT_EVIDENCE_BYTES: Final = 32_768

#: Per-item excerpt hard max. Reuses the search snippet character ceiling so a
#: context excerpt cannot be a larger window into personal content than a
#: search result already is. Measured in characters, not UTF-8 bytes; the
#: package's aggregate bound below is in bytes.
MAX_EXCERPT_CHARACTERS: Final = MAX_SNIPPET_CHARACTERS

#: Evidence `reference_id` ceiling, matching `ContextEvidence`.
MAX_EVIDENCE_REFERENCE_BYTES: Final = 80

#: `ranking_version` and `policy_version` ceiling.
MAX_METADATA_CHARACTERS: Final = 64

#: Untrusted conversation text the caller may supply as hinting. Not persisted.
MAX_CONVERSATION_CONTEXT_CHARACTERS: Final = 2048

#: Opaque subject hints, validated for identifier shape only.
MAX_SUBJECT_HINTS: Final = 8

#: Lexical/structured ranking identity. Semantic retrieval is WP-KC-07/08.
CONTEXT_RANKING_VERSION: Final = "lexical_structured.v1"

#: Stub policy identity for the context-preparation contract itself.
CONTEXT_POLICY_VERSION: Final = "context-prepare-v1"

_FINGERPRINT: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_FORBIDDEN_CATEGORIES: Final[frozenset[str]] = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
_CONTINUITY_KINDS: Final[frozenset[IdKind]] = frozenset(
    {
        IdKind.PROJECT,
        IdKind.SITUATION,
        IdKind.COMMITMENT,
        IdKind.CONTINUITY_DECISION,
        IdKind.TASK,
    }
)
_RELATIONSHIP_KINDS: Final[frozenset[IdKind]] = frozenset({IdKind.PERSON, IdKind.ORGANIZATION})


class PreparedContextError(ValueError):
    """A prepared-context value is malformed, unbounded, or contradictory."""


class ConversationContextError(ValueError):
    """Caller-supplied conversation text is malformed or unbounded.

    Messages name the rule and never the value, so a log or public error that
    renders this exception cannot echo untrusted conversation text.
    """


class ContextPlane(StrEnum):
    """The knowledge planes `context.prepare` may search."""

    KNOWLEDGE = "knowledge"
    CAPTURE = "capture"
    CONTINUITY = "continuity"
    RELATIONSHIP = "relationship"
    MANAGED_DOCUMENT = "managed_document"


class RetrievalMode(StrEnum):
    """How evidence was selected. Semantic retrieval remains gated off."""

    LEXICAL_STRUCTURED = "lexical_structured"
    HYBRID_SEMANTIC = "hybrid_semantic"


class SourceAuthorityClass(StrEnum):
    """Which authority class an evidence item cites. Forbids fake source IDs."""

    ENROLLED_SOURCE = "enrolled_source"
    PRODUCT_OWNED_CAPTURE = "product_owned_capture"
    PRODUCT_OWNED_CONTINUITY = "product_owned_continuity"
    PRODUCT_OWNED_RELATIONSHIP = "product_owned_relationship"
    MANAGED_DOCUMENT = "managed_document"


class EvidenceLifecycle(StrEnum):
    """How firmly the cited record is held."""

    SOURCE_EVIDENCE = "source_evidence"
    USER_AUTHORED = "user_authored"
    ACCEPTED = "accepted"
    PROPOSED = "proposed"
    DERIVED = "derived"


class SelectionReasonCode(StrEnum):
    """Why an item was selected. Categories, never a float score."""

    EXPLICIT_SUBJECT = "explicit_subject"
    EXACT_IDENTIFIER = "exact_identifier"
    CONFIRMED_ALIAS = "confirmed_alias"
    PROJECT_LINK = "project_link"
    SITUATION_LINK = "situation_link"
    RELATIONSHIP_LINK = "relationship_link"
    LEXICAL_STRONG = "lexical_strong"
    LEXICAL_MODERATE = "lexical_moderate"
    RECENT_EVIDENCE = "recent_evidence"
    ACCEPTED_RECORD = "accepted_record"
    PINNED_FOCUS = "pinned_focus"
    SEMANTIC_MATCH = "semantic_match"


class CoverageState(StrEnum):
    """Per-plane coverage of a prepared context. Distinct from extraction coverage."""

    SEARCHED_COMPLETE = "searched_complete"
    INCOMPLETE = "incomplete"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    PERMISSION_DENIED = "permission_denied"
    NOT_ENROLLED = "not_enrolled"
    NOT_ADMITTED = "not_admitted"


class ContextLimitationCode(StrEnum):
    """Closed limitation tokens the retrieval contract itself may carry."""

    PLANES_NOT_SEARCHED = "planes_not_searched"
    NO_MATCHING_EVIDENCE = "no_matching_evidence"
    RESULT_TRUNCATED = "result_truncated"


class ContradictionCode(StrEnum):
    """Closed codes for disclosed conflicts between cited evidence."""

    CONFLICTING_EVIDENCE = "conflicting_evidence"


_PLANE_AUTHORITY: Final[dict[ContextPlane, SourceAuthorityClass]] = {
    ContextPlane.KNOWLEDGE: SourceAuthorityClass.ENROLLED_SOURCE,
    ContextPlane.CAPTURE: SourceAuthorityClass.PRODUCT_OWNED_CAPTURE,
    ContextPlane.CONTINUITY: SourceAuthorityClass.PRODUCT_OWNED_CONTINUITY,
    ContextPlane.RELATIONSHIP: SourceAuthorityClass.PRODUCT_OWNED_RELATIONSHIP,
    ContextPlane.MANAGED_DOCUMENT: SourceAuthorityClass.MANAGED_DOCUMENT,
}


def validate_conversation_context(value: str) -> str:
    """Return `value` unchanged, or refuse it without echoing it.

    Same control-character spirit as `SearchQuery`: controls, formatting,
    surrogates, private-use, and unassigned characters are refused rather than
    stripped, because stripping would silently answer a different question.
    Whitespace is not folded — this is untrusted conversation text, not a query.
    """
    if not isinstance(value, str):
        raise ConversationContextError(
            f"conversation context must be a string, got {type(value).__name__}"
        )
    if len(value) > MAX_CONVERSATION_CONTEXT_CHARACTERS:
        raise ConversationContextError(
            f"conversation context is at most {MAX_CONVERSATION_CONTEXT_CHARACTERS} characters"
        )
    if "\x00" in value:
        raise ConversationContextError("conversation context cannot contain a null byte")
    for character in value:
        if unicodedata.category(character) in _FORBIDDEN_CATEGORIES:
            raise ConversationContextError(
                "conversation context cannot contain control, formatting, surrogate, "
                "private-use, or unassigned characters"
            )
    return value


def _bounded_metadata(value: str, name: str) -> None:
    if not value or len(value) > MAX_METADATA_CHARACTERS:
        raise PreparedContextError(
            f"{name} is required and at most {MAX_METADATA_CHARACTERS} characters"
        )


def _optional_id(value: str | None, kind: IdKind, name: str) -> None:
    if value is None:
        return
    try:
        validate_identifier(value, kind)
    except InvalidIdentifierError as exc:
        raise PreparedContextError(f"{name} is not a well-formed {kind.value} identifier") from exc


def _required_id(value: str | None, kind: IdKind, name: str) -> None:
    if value is None:
        raise PreparedContextError(f"{name} is required for this authority class")
    _optional_id(value, kind, name)


def _absent(value: str | None, name: str) -> None:
    if value is not None:
        raise PreparedContextError(f"{name} cannot be set for this authority class")


@dataclass(frozen=True, slots=True)
class ContextCoverage:
    """Coverage of one plane, optionally inside one enrollment."""

    plane: ContextPlane
    state: CoverageState
    enrollment_id: str | None = None
    freshness: datetime | None = None
    limitations: tuple[ContextLimitationCode, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.plane, ContextPlane):
            raise PreparedContextError("coverage plane is required")
        if not isinstance(self.state, CoverageState):
            raise PreparedContextError("coverage state is required")
        if self.enrollment_id is not None:
            try:
                validate_identifier(self.enrollment_id, IdKind.ENROLLMENT)
            except InvalidIdentifierError as exc:
                raise PreparedContextError(
                    "coverage enrollment_id is not a well-formed identifier"
                ) from exc
        if self.freshness is not None:
            object.__setattr__(self, "freshness", ensure_utc(self.freshness))
        if any(not isinstance(code, ContextLimitationCode) for code in self.limitations):
            raise PreparedContextError("coverage limitations must be ContextLimitationCode members")

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "plane": self.plane.value,
            "state": self.state.value,
            "enrollment_id": self.enrollment_id,
            "freshness": None if self.freshness is None else format_rfc3339(self.freshness),
            "limitations": [code.value for code in self.limitations],
        }


@dataclass(frozen=True, slots=True)
class ContextTruncation:
    """Whether the package was cut to its item or byte ceiling."""

    is_truncated: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.is_truncated, bool):
            raise PreparedContextError("is_truncated must be a boolean")
        if self.reason is not None and (
            not self.reason or len(self.reason) > MAX_METADATA_CHARACTERS
        ):
            raise PreparedContextError("truncation reason is bounded")
        if self.is_truncated is False and self.reason is not None:
            raise PreparedContextError("an untruncated package carries no truncation reason")
        if self.is_truncated is True and self.reason is None:
            raise PreparedContextError("a truncated package must say why")

    def to_canonical_dict(self) -> dict[str, object]:
        return {"is_truncated": self.is_truncated, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class PreparedContextEvidence:
    """One retrieved item. Text is untrusted data and has no instruction authority.

    Identity is a discriminated set of optional fields. Construction raises when
    the authority class and the IDs disagree, so a capture cannot be given a
    fake `src_` and a source item cannot omit its three source identifiers.
    """

    reference_id: str
    principal_id: str
    plane: ContextPlane
    authority_class: SourceAuthorityClass
    lifecycle: EvidenceLifecycle
    text: str = field(repr=False)
    instruction_authority: bool = False
    classification: Classification = Classification.PRIVATE_LOCAL
    span_start: int | None = None
    span_end: int | None = None
    freshness: datetime | None = None
    reason_codes: tuple[SelectionReasonCode, ...] = ()
    reveal_subject_id: str | None = None
    source_id: str | None = None
    source_object_id: str | None = None
    source_version_id: str | None = None
    knowledge_id: str | None = None
    capture_id: str | None = None
    capture_version_id: str | None = None
    product_id: str | None = None
    managed_document_id: str | None = None
    managed_document_version_id: str | None = None

    def __post_init__(self) -> None:
        try:
            validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        except InvalidIdentifierError as exc:
            raise PreparedContextError("principal_id is not a well-formed identifier") from exc
        if not self.reference_id or len(self.reference_id.encode()) > MAX_EVIDENCE_REFERENCE_BYTES:
            raise PreparedContextError("an evidence reference is required and bounded")
        if not isinstance(self.plane, ContextPlane):
            raise PreparedContextError("plane is required")
        if not isinstance(self.authority_class, SourceAuthorityClass):
            raise PreparedContextError("authority_class is required")
        if _PLANE_AUTHORITY[self.plane] is not self.authority_class:
            raise PreparedContextError("authority class does not match the evidence plane")
        if not isinstance(self.lifecycle, EvidenceLifecycle):
            raise PreparedContextError("lifecycle is required")
        if not isinstance(self.classification, Classification):
            raise PreparedContextError("classification is required")
        if self.instruction_authority:
            raise PreparedContextError("retrieved content cannot have instruction authority")
        if not isinstance(self.text, str):
            raise PreparedContextError("evidence text must be a string")
        if not self.text:
            raise PreparedContextError("evidence text is required")
        if len(self.text) > MAX_EXCERPT_CHARACTERS:
            raise PreparedContextError(
                f"an evidence excerpt is at most {MAX_EXCERPT_CHARACTERS} characters"
            )
        if self.span_start is not None or self.span_end is not None:
            if self.span_start is None or self.span_end is None:
                raise PreparedContextError("evidence span requires both ends")
            if isinstance(self.span_start, bool) or isinstance(self.span_end, bool):
                raise PreparedContextError("evidence span is outside the retrieved text")
            if (
                self.span_start < 0
                or self.span_end < self.span_start
                or self.span_end > len(self.text)
            ):
                raise PreparedContextError("evidence span is outside the retrieved text")
        if self.freshness is not None:
            object.__setattr__(self, "freshness", ensure_utc(self.freshness))
        if any(not isinstance(code, SelectionReasonCode) for code in self.reason_codes):
            raise PreparedContextError("reason_codes must be SelectionReasonCode members")
        if self.reveal_subject_id is not None:
            try:
                validate_identifier(self.reveal_subject_id)
            except InvalidIdentifierError as exc:
                raise PreparedContextError(
                    "reveal_subject_id is not a well-formed identifier"
                ) from exc
        self._validate_identity()

    def _validate_identity(self) -> None:
        match self.authority_class:
            case SourceAuthorityClass.ENROLLED_SOURCE:
                _required_id(self.source_id, IdKind.SOURCE, "source_id")
                _required_id(self.source_object_id, IdKind.SOURCE_OBJECT, "source_object_id")
                _required_id(self.source_version_id, IdKind.VERSION, "source_version_id")
                _optional_id(self.knowledge_id, IdKind.KNOWLEDGE, "knowledge_id")
                _absent(self.capture_id, "capture_id")
                _absent(self.capture_version_id, "capture_version_id")
                _absent(self.product_id, "product_id")
                _absent(self.managed_document_id, "managed_document_id")
                _absent(self.managed_document_version_id, "managed_document_version_id")
            case SourceAuthorityClass.PRODUCT_OWNED_CAPTURE:
                _required_id(self.capture_id, IdKind.CAPTURE, "capture_id")
                _required_id(self.capture_version_id, IdKind.CAPTURE_VERSION, "capture_version_id")
                _absent(self.source_id, "source_id")
                _absent(self.source_object_id, "source_object_id")
                _absent(self.source_version_id, "source_version_id")
                _absent(self.knowledge_id, "knowledge_id")
                _absent(self.product_id, "product_id")
                _absent(self.managed_document_id, "managed_document_id")
                _absent(self.managed_document_version_id, "managed_document_version_id")
            case SourceAuthorityClass.PRODUCT_OWNED_CONTINUITY:
                self._require_product(_CONTINUITY_KINDS, "continuity")
                self._absent_source_and_capture()
                _absent(self.managed_document_id, "managed_document_id")
                _absent(self.managed_document_version_id, "managed_document_version_id")
            case SourceAuthorityClass.PRODUCT_OWNED_RELATIONSHIP:
                self._require_product(_RELATIONSHIP_KINDS, "relationship")
                self._absent_source_and_capture()
                _absent(self.managed_document_id, "managed_document_id")
                _absent(self.managed_document_version_id, "managed_document_version_id")
            case SourceAuthorityClass.MANAGED_DOCUMENT:
                _required_id(
                    self.managed_document_id, IdKind.MANAGED_DOCUMENT, "managed_document_id"
                )
                _required_id(
                    self.managed_document_version_id,
                    IdKind.MANAGED_DOCUMENT_VERSION,
                    "managed_document_version_id",
                )
                self._absent_source_and_capture()
                _absent(self.product_id, "product_id")

    def _absent_source_and_capture(self) -> None:
        _absent(self.source_id, "source_id")
        _absent(self.source_object_id, "source_object_id")
        _absent(self.source_version_id, "source_version_id")
        _absent(self.knowledge_id, "knowledge_id")
        _absent(self.capture_id, "capture_id")
        _absent(self.capture_version_id, "capture_version_id")

    def _require_product(self, allowed: frozenset[IdKind], plane_name: str) -> None:
        if self.product_id is None:
            raise PreparedContextError(f"product_id is required for {plane_name} evidence")
        try:
            kind, _suffix = parse_identifier(self.product_id)
        except InvalidIdentifierError as exc:
            raise PreparedContextError("product_id is not a well-formed identifier") from exc
        if kind not in allowed:
            raise PreparedContextError(f"product_id is not a {plane_name} identifier")

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "reference_id": self.reference_id,
            "principal_id": self.principal_id,
            "plane": self.plane.value,
            "authority_class": self.authority_class.value,
            "lifecycle": self.lifecycle.value,
            "text": self.text,
            "instruction_authority": self.instruction_authority,
            "classification": self.classification.value,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "freshness": None if self.freshness is None else format_rfc3339(self.freshness),
            "reason_codes": [code.value for code in self.reason_codes],
            "reveal_subject_id": self.reveal_subject_id,
            "source_id": self.source_id,
            "source_object_id": self.source_object_id,
            "source_version_id": self.source_version_id,
            "knowledge_id": self.knowledge_id,
            "capture_id": self.capture_id,
            "capture_version_id": self.capture_version_id,
            "product_id": self.product_id,
            "managed_document_id": self.managed_document_id,
            "managed_document_version_id": self.managed_document_version_id,
        }


@dataclass(frozen=True, slots=True)
class PreparedContext:
    """One assembled context package. Empty evidence is a valid no-match."""

    context_manifest_id: str
    principal_id: str
    retrieval_mode: RetrievalMode
    ranking_version: str
    policy_version: str
    generated_at: datetime
    query_fingerprint: str
    evidence: tuple[PreparedContextEvidence, ...] = ()
    coverage: tuple[ContextCoverage, ...] = ()
    unavailable_planes: tuple[ContextPlane, ...] = ()
    limitations: tuple[ContextLimitationCode, ...] = ()
    contradictions_or_conflicts: tuple[ContradictionCode, ...] = ()
    truncation: ContextTruncation = field(default_factory=ContextTruncation)
    applied_subjects: tuple[str, ...] = ()
    applied_preferences: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            validate_identifier(self.context_manifest_id, IdKind.CONTEXT_MANIFEST)
            validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        except InvalidIdentifierError as exc:
            raise PreparedContextError("prepared context identifiers are not well-formed") from exc
        if not isinstance(self.retrieval_mode, RetrievalMode):
            raise PreparedContextError("retrieval_mode is required")
        _bounded_metadata(self.ranking_version, "ranking_version")
        _bounded_metadata(self.policy_version, "policy_version")
        object.__setattr__(self, "generated_at", ensure_utc(self.generated_at))
        if not _FINGERPRINT.fullmatch(self.query_fingerprint):
            raise PreparedContextError("query_fingerprint is a sha-256 hex digest")
        if len(self.evidence) > MAX_EVIDENCE_ITEMS:
            raise PreparedContextError("prepared context evidence exceeds its count bound")
        total_bytes = sum(len(item.text.encode()) for item in self.evidence)
        if total_bytes > MAX_EVIDENCE_BYTES:
            raise PreparedContextError("prepared context evidence exceeds its aggregate byte bound")
        if any(item.principal_id != self.principal_id for item in self.evidence):
            raise PreparedContextError("prepared context evidence crossed its Principal boundary")
        if any(item.instruction_authority for item in self.evidence):
            raise PreparedContextError("retrieved content cannot have instruction authority")
        if any(not isinstance(plane, ContextPlane) for plane in self.unavailable_planes):
            raise PreparedContextError("unavailable_planes must name ContextPlane members")
        if len(set(self.unavailable_planes)) != len(self.unavailable_planes):
            raise PreparedContextError("unavailable_planes must be distinct")
        if any(not isinstance(code, ContextLimitationCode) for code in self.limitations):
            raise PreparedContextError("limitations must be ContextLimitationCode members")
        if any(
            not isinstance(code, ContradictionCode) for code in self.contradictions_or_conflicts
        ):
            raise PreparedContextError("contradictions must be ContradictionCode members")
        for identifier in (*self.applied_subjects, *self.applied_preferences):
            try:
                validate_identifier(identifier)
            except InvalidIdentifierError as exc:
                raise PreparedContextError("applied identifiers are shape-validated only") from exc
        if len(self.applied_subjects) > MAX_SUBJECT_HINTS:
            raise PreparedContextError(f"at most {MAX_SUBJECT_HINTS} applied subjects")

    @property
    def total_items(self) -> int:
        return len(self.evidence)

    @property
    def total_bytes(self) -> int:
        return sum(len(item.text.encode()) for item in self.evidence)

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "context_manifest_id": self.context_manifest_id,
            "principal_id": self.principal_id,
            "retrieval_mode": self.retrieval_mode.value,
            "ranking_version": self.ranking_version,
            "policy_version": self.policy_version,
            "generated_at": format_rfc3339(self.generated_at),
            "query_fingerprint": self.query_fingerprint,
            "applied_subjects": list(self.applied_subjects),
            "applied_preferences": list(self.applied_preferences),
            "evidence": [item.to_canonical_dict() for item in self.evidence],
            "coverage": [item.to_canonical_dict() for item in self.coverage],
            "unavailable_planes": [plane.value for plane in self.unavailable_planes],
            "limitations": [code.value for code in self.limitations],
            "contradictions_or_conflicts": [
                code.value for code in self.contradictions_or_conflicts
            ],
            "truncation": self.truncation.to_canonical_dict(),
            "total_items": self.total_items,
            "total_bytes": self.total_bytes,
            "instruction_authority": False,
        }
