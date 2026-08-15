"""Assemble a prepared context from authorized planes.

The handler is a thin adapter: it normalizes the query and returns the
canonical payload. Enrollments are discovered from `Authorization.enrollments`;
the caller does not supply them. Remote grant intersection is applied here so a
`context.prepare` grant does not search every plane the Principal can read.
Context-run metadata is persisted after packing, in the same unit of work.
"""

from __future__ import annotations

import time

from my_pa.application.authorization import Authorization
from my_pa.application.commands import PrepareContext
from my_pa.application.context.providers import search_plane, searchable_planes
from my_pa.application.context.ranking import apply_preferences, rank_and_pack
from my_pa.application.errors import InternalError
from my_pa.contracts.ports import UnitOfWork
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.context.preference import ContextPreferenceAction, ContextPreferenceCurrent
from my_pa.domain.context.prepared import (
    CONTEXT_POLICY_VERSION,
    CONTEXT_RANKING_VERSION,
    DEFAULT_EVIDENCE_BYTES,
    DEFAULT_EVIDENCE_ITEMS,
    MAX_EVIDENCE_BYTES,
    MAX_EVIDENCE_ITEMS,
    ContextCoverage,
    ContextLimitationCode,
    CoverageState,
    PreparedContext,
    PreparedContextEvidence,
    RetrievalMode,
)
from my_pa.domain.context.run import (
    CONTEXT_RUN_OUTCOME_SUCCESS,
    ContextRunItemRecord,
    ContextRunRecord,
    excerpt_sha256,
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
        started = time.monotonic()
        extra_terms = _conversation_terms(command.conversation_context)
        preferences = unit_of_work.context_preferences.current_for(
            authorization.principal.principal_id
        )
        subject_hints = _hints_with_aliases(
            command.subject_hints,
            preferences,
            query=command.query,
            conversation_context=command.conversation_context,
        )
        requested = command.requested_planes
        considered = searchable_planes(
            managed_documents_composed=self._managed_documents_composed,
            capability_grants=authorization.capability_grants,
        )
        selected = tuple(plane for plane in considered if not requested or plane in requested)

        gathers = [
            search_plane(
                plane,
                unit_of_work=unit_of_work,
                authorization=authorization,
                query=query,
                extra_terms=extra_terms,
                subject_hints=subject_hints,
                managed_documents_composed=self._managed_documents_composed,
            )
            for plane in selected
        ]
        attempted = [gather for gather in gathers if gather.attempted]
        if attempted and all(gather.internal_fault for gather in attempted):
            raise InternalError()

        evidence = tuple(item for gather in gathers for item in gather.evidence)
        evidence, applied_preferences, preference_limitations = apply_preferences(
            evidence,
            preferences,
            query=command.query,
            conversation_context=command.conversation_context,
        )
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

        limitations = packed.limitations + preference_limitations
        if _no_matching_evidence(packed.items, coverage):
            limitations = (*limitations, ContextLimitationCode.NO_MATCHING_EVIDENCE)
        applied = tuple(
            hint
            for hint in command.subject_hints
            if any(_hint_applied(hint, item) for item in packed.items)
        )
        prepared = PreparedContext(
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
            applied_preferences=applied_preferences,
        )
        duration_ms = max(0, round((time.monotonic() - started) * 1000))
        unit_of_work.context_runs.record(
            _run_record(prepared, authorization, duration_ms=duration_ms)
        )
        return prepared


def _run_record(
    prepared: PreparedContext,
    authorization: Authorization,
    *,
    duration_ms: int,
) -> ContextRunRecord:
    """Identifiers and digests of one disclosure. Never the query or excerpt text."""
    return ContextRunRecord(
        context_manifest_id=prepared.context_manifest_id,
        principal_id=prepared.principal_id,
        request_id=authorization.request_id,
        correlation_id=authorization.correlation_id,
        transport=authorization.transport.value,
        purpose=authorization.purpose.value,
        query_fingerprint=prepared.query_fingerprint,
        retrieval_mode=prepared.retrieval_mode,
        ranking_version=prepared.ranking_version,
        policy_version=prepared.policy_version,
        generated_at=prepared.generated_at,
        total_items=prepared.total_items,
        total_bytes=prepared.total_bytes,
        outcome=CONTEXT_RUN_OUTCOME_SUCCESS,
        truncated=prepared.truncation.is_truncated,
        items=tuple(
            ContextRunItemRecord(
                position=position,
                reference_id=item.reference_id,
                principal_id=item.principal_id,
                plane=item.plane,
                authority_class=item.authority_class,
                lifecycle=item.lifecycle,
                classification=item.classification,
                excerpt_sha256=excerpt_sha256(item.text),
                reason_codes=",".join(code.value for code in item.reason_codes),
                source_id=item.source_id,
                source_object_id=item.source_object_id,
                source_version_id=item.source_version_id,
                knowledge_id=item.knowledge_id,
                capture_id=item.capture_id,
                capture_version_id=item.capture_version_id,
                product_id=item.product_id,
                managed_document_id=item.managed_document_id,
                managed_document_version_id=item.managed_document_version_id,
                span_start=item.span_start,
                span_end=item.span_end,
            )
            for position, item in enumerate(prepared.evidence)
        ),
        audit_id=authorization.audit_id,
        duration_ms=duration_ms,
        truncation_reason=prepared.truncation.reason,
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


def _hints_with_aliases(
    subject_hints: tuple[str, ...],
    preferences: tuple[ContextPreferenceCurrent, ...],
    *,
    query: str,
    conversation_context: str | None,
) -> tuple[str, ...]:
    """Add confirmed-alias targets when the query names the alias.

    This does not invent evidence or widen enrollments: it treats an already
    owned identity as an explicit subject the same way `subject_hints` does.
    """
    folded_query = query.casefold()
    if conversation_context:
        folded_query = f"{folded_query} {conversation_context.casefold()}"
    extras: list[str] = []
    for preference in preferences:
        if preference.action is not ContextPreferenceAction.CONFIRM_ALIAS:
            continue
        if preference.alias is None or preference.alias.casefold() not in folded_query:
            continue
        if preference.target_id not in subject_hints and preference.target_id not in extras:
            extras.append(preference.target_id)
    return (*subject_hints, *extras)


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
