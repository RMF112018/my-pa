"""GoodNotes semantic work lookup and proposal admission.

Does not write canonical notes, occurrences, revisions, or run-note-changes.
Does not decide NEW/UNCHANGED/REVISED/REMOVED_OR_NO_LONGER_PRESENT/AMBIGUOUS.
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from my_pa.application.authorization import Authorization
from my_pa.application.commands import SubmitGoodNotesProposal
from my_pa.application.errors import ConflictError, InvalidRequestError, NotFoundError, SafeDetail
from my_pa.contracts.ports import (
    GoodNotesProposalConflictError,
    UnitOfWork,
)
from my_pa.domain.goodnotes.dates import (
    GoodNotesDateEvidence,
    GoodNotesDateScope,
    GoodNotesDateSemantics,
    GoodNotesPageDateStatus,
    admit_date_evidence,
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
    payload = {
        key: body[key] for key in ("segments", "candidate_tags", "ranked_candidates", "confidence")
    }
    if command.date_evidence:
        body["date_evidence"] = command.date_evidence
        payload["date_evidence"] = command.date_evidence
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    digest = sha256(encoded.encode()).hexdigest()
    payload_digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
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
