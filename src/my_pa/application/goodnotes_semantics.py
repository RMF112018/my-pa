"""GoodNotes semantic work lookup and proposal admission.

Does not write canonical notes, occurrences, revisions, or run-note-changes.
Does not decide NEW/UNCHANGED/REVISED/REMOVED_OR_NO_LONGER_PRESENT/AMBIGUOUS.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any

from my_pa.application.authorization import Authorization
from my_pa.application.commands import SubmitGoodNotesProposal
from my_pa.application.errors import ConflictError, InvalidRequestError, NotFoundError, SafeDetail
from my_pa.contracts.ports import (
    GoodNotesProposalConflictError,
    UnitOfWork,
)
from my_pa.domain.goodnotes.models import GoodNotesPageWork, GoodNotesSemanticProposal

__all__ = [
    "GoodNotesDateEvidence",
    "GoodNotesDateScope",
    "GoodNotesDateSemantics",
    "GoodNotesPageDateStatus",
    "admit_date_evidence",
    "fingerprint_proposal",
    "lookup_work",
    "submit_proposal",
]

_MAX_DATE_LITERAL_LENGTH = 200
_MAX_DATE_EVIDENCE_REF_LENGTH = 200
_MAX_DATE_EVIDENCE_REFS = 32


class GoodNotesDateScope(StrEnum):
    """Meaning of a proposed date; page identity is never an event date."""

    PAGE = "PAGE"
    EVENT = "EVENT"
    BODY = "BODY"


class GoodNotesPageDateStatus(StrEnum):
    """Explicit outcome for the singular notebook-page date."""

    ABSENT = "ABSENT"
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class GoodNotesDateEvidence:
    """One client-proposed ISO date with its unmodified evidence metadata."""

    scope: GoodNotesDateScope
    value: date
    literal: str
    evidence_refs: tuple[str, ...]
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope, GoodNotesDateScope):
            raise TypeError("date scope must be a GoodNotesDateScope")
        if isinstance(self.value, datetime) or not isinstance(self.value, date):
            raise TypeError("date value must be a date without a time")
        _bounded_date_text(self.literal, what="date literal", maximum=_MAX_DATE_LITERAL_LENGTH)
        if not self.evidence_refs or len(self.evidence_refs) > _MAX_DATE_EVIDENCE_REFS:
            raise ValueError("date evidence references are outside their bound")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("date evidence references must be unique")
        for evidence_ref in self.evidence_refs:
            _bounded_date_text(
                evidence_ref,
                what="date evidence reference",
                maximum=_MAX_DATE_EVIDENCE_REF_LENGTH,
            )
        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(self.confidence, int | float):
                raise TypeError("date confidence must be numeric")
            if not math.isfinite(float(self.confidence)) or not 0 <= self.confidence <= 1:
                raise ValueError("date confidence must be between zero and one")


def admit_date_evidence(
    *,
    scope: GoodNotesDateScope,
    value: str,
    literal: str,
    evidence_refs: tuple[str, ...],
    confidence: float | None = None,
) -> GoodNotesDateEvidence:
    """Validate a client-proposed date without parsing prose or calling a model."""

    if not isinstance(value, str):
        raise TypeError("date value must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("date value must be a valid ISO calendar date") from None
    if parsed.isoformat() != value:
        raise ValueError("date value must use canonical ISO format")
    return GoodNotesDateEvidence(
        scope=scope,
        value=parsed,
        literal=literal,
        evidence_refs=evidence_refs,
        confidence=confidence,
    )


@dataclass(frozen=True, slots=True)
class GoodNotesDateSemantics:
    """Page date and zero-or-more event/body dates kept on separate planes."""

    page_candidates: tuple[GoodNotesDateEvidence, ...] = ()
    event_dates: tuple[GoodNotesDateEvidence, ...] = ()
    body_dates: tuple[GoodNotesDateEvidence, ...] = ()

    def __post_init__(self) -> None:
        _require_date_scope(self.page_candidates, GoodNotesDateScope.PAGE)
        _require_date_scope(self.event_dates, GoodNotesDateScope.EVENT)
        _require_date_scope(self.body_dates, GoodNotesDateScope.BODY)

    @property
    def page_date_status(self) -> GoodNotesPageDateStatus:
        distinct = {candidate.value for candidate in self.page_candidates}
        if not distinct:
            return GoodNotesPageDateStatus.ABSENT
        if len(distinct) == 1:
            return GoodNotesPageDateStatus.RESOLVED
        return GoodNotesPageDateStatus.AMBIGUOUS

    @property
    def page_date(self) -> date | None:
        """Return the page date only when the submitted evidence is unambiguous."""

        if self.page_date_status is not GoodNotesPageDateStatus.RESOLVED:
            return None
        return self.page_candidates[0].value


def _require_date_scope(values: object, expected: GoodNotesDateScope) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(value, GoodNotesDateEvidence) or value.scope is not expected
        for value in values
    ):
        raise ValueError(f"{expected.value.casefold()} dates contain a wrong-scope value")


def _bounded_date_text(value: object, *, what: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise ValueError(f"invalid {what}")


def fingerprint_proposal(command: SubmitGoodNotesProposal) -> tuple[str, str, dict[str, object]]:
    """Canonical fingerprint and payload digest for one proposal body."""
    body: dict[str, object] = {
        "run_id": command.run_id,
        "page_version_id": command.page_version_id,
        "content_sha256": command.content_sha256,
        "schema_version": command.schema_version,
        "analyzer_name": command.analyzer_name,
        "analyzer_version": command.analyzer_version,
        "segments": list(command.segments),
        "candidate_tags": list(command.candidate_tags),
        "ranked_candidates": list(command.ranked_candidates),
        "confidence": command.confidence,
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    digest = sha256(encoded.encode()).hexdigest()
    payload_digest = sha256(
        json.dumps(
            {
                "segments": list(command.segments),
                "candidate_tags": list(command.candidate_tags),
                "ranked_candidates": list(command.ranked_candidates),
                "confidence": command.confidence,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()
    return digest, payload_digest, body


def lookup_work(
    unit_of_work: UnitOfWork, authorization: Authorization, *, run_id: str, page_version_id: str
) -> GoodNotesPageWork:
    """Principal-bound page-version work, or a closed `not_found`."""
    work = unit_of_work.goodnotes_semantics.page_work(
        authorization.principal.principal_id, run_id, page_version_id
    )
    if work is None:
        raise NotFoundError()
    return work


def submit_proposal(
    unit_of_work: UnitOfWork,
    authorization: Authorization,
    command: SubmitGoodNotesProposal,
) -> GoodNotesSemanticProposal:
    """Admit one semantic proposal against immutable page-version work."""
    work = lookup_work(
        unit_of_work,
        authorization,
        run_id=command.run_id,
        page_version_id=command.page_version_id,
    )
    if work.content_sha256 != command.content_sha256:
        raise InvalidRequestError(SafeDetail.CONTENT_SHA256)
    fingerprint, payload_digest, body = fingerprint_proposal(command)
    try:
        admission = unit_of_work.goodnotes_semantics.submit_proposal(
            principal_id=authorization.principal.principal_id,
            run_id=command.run_id,
            page_version_id=command.page_version_id,
            content_sha256=command.content_sha256,
            schema_version=command.schema_version,
            analyzer_name=command.analyzer_name,
            analyzer_version=command.analyzer_version,
            idempotency_key=command.idempotency_key,
            request_fingerprint=fingerprint,
            payload_sha256=payload_digest,
            payload=body,
            correlation_id=authorization.correlation_id,
            request_id=authorization.request_id,
            audit_id=authorization.audit_id,
            created_at=authorization.at,
        )
    except GoodNotesProposalConflictError:
        raise ConflictError(SafeDetail.IDEMPOTENCY_KEY) from None
    return admission.proposal


def work_payload(work: GoodNotesPageWork) -> dict[str, Any]:
    return {
        "run_id": work.run_id,
        "page_version_id": work.page_version_id,
        "content_sha256": work.content_sha256,
        "logical_page_id": work.logical_page_id,
        "renderer_name": work.renderer_name,
        "renderer_version": work.renderer_version,
        "render_profile_version": work.render_profile_version,
    }


def proposal_payload(proposal: GoodNotesSemanticProposal) -> dict[str, Any]:
    return {
        "proposal_id": proposal.proposal_id,
        "run_id": proposal.run_id,
        "page_version_id": proposal.page_version_id,
        "replayed": proposal.replayed,
        "request_fingerprint": proposal.request_fingerprint,
    }
