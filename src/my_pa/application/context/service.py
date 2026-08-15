"""Assemble a prepared context from authorized planes.

The handler is a thin adapter: it normalizes the query and returns the
canonical payload. Enrollments are discovered from `Authorization.enrollments`;
the caller does not supply them.
"""

from __future__ import annotations

from my_pa.application.authorization import Authorization
from my_pa.application.commands import PrepareContext
from my_pa.application.context.providers import eligible_planes, search_plane
from my_pa.application.context.ranking import rank_and_pack
from my_pa.application.errors import InternalError
from my_pa.contracts.ports import UnitOfWork
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.context.prepared import (
    CONTEXT_POLICY_VERSION,
    CONTEXT_RANKING_VERSION,
    DEFAULT_EVIDENCE_BYTES,
    DEFAULT_EVIDENCE_ITEMS,
    MAX_EVIDENCE_BYTES,
    MAX_EVIDENCE_ITEMS,
    ContextCoverage,
    ContextLimitationCode,
    ContextPlane,
    CoverageState,
    PreparedContext,
    PreparedContextEvidence,
    RetrievalMode,
)
from my_pa.domain.search.query import SearchQuery
from my_pa.domain.source.registry import issue_identifier

__all__ = ["ContextPreparationService"]

_ATTEMPTED_INCOMPLETE = frozenset(
    {
        CoverageState.INCOMPLETE,
        CoverageState.UNAVAILABLE,
        CoverageState.STALE,
        CoverageState.PERMISSION_DENIED,
    }
)


class ContextPreparationService:
    """Retrieve, rank, and pack a mixed context packet for one principal."""

    def __init__(self, *, managed_documents_composed: bool) -> None:
        self._managed_documents_composed = managed_documents_composed

    def prepare(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        command: PrepareContext,
        query: SearchQuery,
    ) -> PreparedContext:
        extra_terms = _conversation_terms(command.conversation_context)
        requested = command.requested_planes
        eligible = eligible_planes(managed_documents_composed=self._managed_documents_composed)
        considered = (*eligible, ContextPlane.RELATIONSHIP)
        selected = tuple(plane for plane in considered if not requested or plane in requested)

        gathers = [
            search_plane(
                plane,
                unit_of_work=unit_of_work,
                authorization=authorization,
                query=query,
                extra_terms=extra_terms,
                subject_hints=command.subject_hints,
                managed_documents_composed=self._managed_documents_composed,
            )
            for plane in selected
        ]
        attempted = [gather for gather in gathers if gather.attempted]
        if attempted and all(gather.internal_fault for gather in attempted):
            raise InternalError()

        evidence = tuple(item for gather in gathers for item in gather.evidence)
        packed = rank_and_pack(
            evidence,
            max_items=min(DEFAULT_EVIDENCE_ITEMS, MAX_EVIDENCE_ITEMS),
            max_bytes=min(DEFAULT_EVIDENCE_BYTES, MAX_EVIDENCE_BYTES),
        )
        coverage = tuple(item for gather in gathers for item in gather.coverage)
        unavailable = tuple(gather.plane for gather in gathers if gather.unavailable)
        skipped = [plane for plane in considered if plane not in selected]
        if skipped:
            coverage = coverage + tuple(
                ContextCoverage(plane=plane, state=CoverageState.UNAVAILABLE) for plane in skipped
            )
            unavailable = tuple(dict.fromkeys((*unavailable, *skipped)))

        limitations = packed.limitations
        if _no_matching_evidence(packed.items, coverage):
            limitations = (*limitations, ContextLimitationCode.NO_MATCHING_EVIDENCE)
        applied = tuple(
            hint
            for hint in command.subject_hints
            if any(_hint_applied(hint, item) for item in packed.items)
        )
        return PreparedContext(
            context_manifest_id=issue_identifier(IdKind.CONTEXT_MANIFEST),
            principal_id=authorization.principal.principal_id,
            retrieval_mode=RetrievalMode.LEXICAL_STRUCTURED,
            ranking_version=CONTEXT_RANKING_VERSION,
            policy_version=CONTEXT_POLICY_VERSION,
            generated_at=authorization.at,
            query_fingerprint=query.fingerprint,
            evidence=packed.items,
            coverage=coverage,
            unavailable_planes=unavailable,
            limitations=limitations,
            contradictions_or_conflicts=packed.contradictions,
            truncation=packed.truncation,
            applied_subjects=applied,
        )


def _conversation_terms(conversation_context: str | None) -> tuple[str, ...]:
    if not conversation_context:
        return ()
    seen: list[str] = []
    for token in conversation_context.split():
        lowered = token.lower()
        if lowered and lowered not in seen:
            seen.append(lowered)
    return tuple(seen)


def _hint_applied(hint: str, item: PreparedContextEvidence) -> bool:
    identities = (
        item.knowledge_id,
        item.source_id,
        item.source_object_id,
        item.source_version_id,
        item.capture_id,
        item.capture_version_id,
        item.product_id,
        item.managed_document_id,
        item.managed_document_version_id,
        item.reference_id,
    )
    return hint in identities


def _no_matching_evidence(
    items: tuple[PreparedContextEvidence, ...], coverage: tuple[ContextCoverage, ...]
) -> bool:
    if items:
        return False
    states = [row.state for row in coverage]
    if not any(state is CoverageState.SEARCHED_COMPLETE for state in states):
        return False
    return not any(state in _ATTEMPTED_INCOMPLETE for state in states)
