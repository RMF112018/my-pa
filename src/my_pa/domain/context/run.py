"""Insert-only context-run metadata: references and digests, never query text.

A stored run is enough to reconstruct which evidence was disclosed — identifiers,
digests, fingerprints, and policy/ranking versions — without keeping a second
copy of private excerpts or the query that produced them. Rollback of
`context.prepare` is capability revoke (AC-KC-037), not a row delete.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.context.prepared import (
    MAX_METADATA_CHARACTERS,
    ContextPlane,
    EvidenceLifecycle,
    RetrievalMode,
    SourceAuthorityClass,
)

__all__ = [
    "CONTEXT_RUN_OUTCOME_SUCCESS",
    "ContextRunItemRecord",
    "ContextRunRecord",
    "excerpt_sha256",
]

#: The only outcome this package persists: a run is written after packing, inside
#: the prepare transaction. A handler failure rolls the row back rather than
#: storing exception text.
CONTEXT_RUN_OUTCOME_SUCCESS: str = "success"

_FINGERPRINT_LENGTH = 64


def excerpt_sha256(text: str) -> str:
    """UTF-8 sha-256 of disclosed excerpt text. The text itself is not stored."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest(value: str, name: str) -> None:
    if len(value) != _FINGERPRINT_LENGTH or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} is a sha-256 hex digest")


@dataclass(frozen=True, slots=True)
class ContextRunItemRecord:
    """One disclosed evidence reference: IDs and the excerpt digest, never the text."""

    position: int
    reference_id: str
    principal_id: str
    plane: ContextPlane
    authority_class: SourceAuthorityClass
    lifecycle: EvidenceLifecycle
    classification: Classification
    excerpt_sha256: str
    reason_codes: str
    source_id: str | None = None
    source_object_id: str | None = None
    source_version_id: str | None = None
    knowledge_id: str | None = None
    capture_id: str | None = None
    capture_version_id: str | None = None
    product_id: str | None = None
    managed_document_id: str | None = None
    managed_document_version_id: str | None = None
    span_start: int | None = None
    span_end: int | None = None

    def __post_init__(self) -> None:
        if self.position < 0:
            raise ValueError("context run item position starts at zero")
        try:
            validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        except InvalidIdentifierError as exc:
            raise ValueError("principal_id is not a well-formed identifier") from exc
        if not self.reference_id:
            raise ValueError("reference_id is required")
        _digest(self.excerpt_sha256, "excerpt_sha256")
        if len(self.reason_codes) > 512:
            raise ValueError("reason_codes is bounded")


@dataclass(frozen=True, slots=True)
class ContextRunRecord:
    """One prepared-context disclosure, without the query or any excerpt text."""

    context_manifest_id: str
    principal_id: str
    request_id: str
    correlation_id: str
    transport: str
    purpose: str
    query_fingerprint: str
    retrieval_mode: RetrievalMode
    ranking_version: str
    policy_version: str
    generated_at: datetime
    total_items: int
    total_bytes: int
    outcome: str
    truncated: bool
    items: tuple[ContextRunItemRecord, ...]
    audit_id: str | None = None
    duration_ms: int | None = None
    truncation_reason: str | None = None

    def __post_init__(self) -> None:
        try:
            validate_identifier(self.context_manifest_id, IdKind.CONTEXT_MANIFEST)
            validate_identifier(self.principal_id, IdKind.PRINCIPAL)
            validate_identifier(self.correlation_id, IdKind.CORRELATION)
            if self.audit_id is not None:
                validate_identifier(self.audit_id, IdKind.AUDIT)
        except InvalidIdentifierError as exc:
            raise ValueError("context run identifiers are not well-formed") from exc
        if not self.request_id:
            raise ValueError("request_id is required")
        _digest(self.query_fingerprint, "query_fingerprint")
        if self.purpose != "context_preparation":
            raise ValueError("a context run records context_preparation")
        if self.outcome != CONTEXT_RUN_OUTCOME_SUCCESS:
            raise ValueError("a persisted context run records a success token")
        if (
            self.truncation_reason is not None
            and len(self.truncation_reason) > MAX_METADATA_CHARACTERS
        ):
            raise ValueError("truncation reason is bounded")
        object.__setattr__(self, "generated_at", ensure_utc(self.generated_at))
        if any(item.principal_id != self.principal_id for item in self.items):
            raise ValueError("context run items crossed their Principal boundary")
        if len(self.items) != self.total_items:
            raise ValueError("total_items must match the stored item count")
