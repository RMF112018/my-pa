"""Per-plane retrieval for context preparation.

Each function searches one plane and isolates plane-local faults. A unit-of-work
break is re-raised so the request fails closed. Application code does not import
infrastructure search-error types; production maps those onto port errors, and
the fake raises `KeyError` when an enrollment was not staged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from my_pa.application.authorization import Authorization
from my_pa.contracts.ports import (
    CaptureSearchRequest,
    EvidenceUnavailableError,
    RepositoryFailureError,
    SearchOutcome,
    UnitOfWork,
)
from my_pa.domain.capture.version import CaptureVersion
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.coverage import CoverageState as ExtractionCoverageState
from my_pa.domain.common.identifiers import InvalidIdentifierError, parse_identifier
from my_pa.domain.context.prepared import (
    MAX_EXCERPT_CHARACTERS,
    ContextCoverage,
    ContextPlane,
    CoverageState,
    EvidenceLifecycle,
    PreparedContextError,
    PreparedContextEvidence,
    SelectionReasonCode,
    SourceAuthorityClass,
)
from my_pa.domain.search.query import (
    RankCategory,
    SearchQuery,
    SearchQueryError,
    SearchRequest,
    bound_snippet,
)
from my_pa.domain.situation.situation import Project, Situation

__all__ = ["PlaneGather", "eligible_planes", "search_plane"]

_INTERNAL_TYPE_NAMES = frozenset(
    {
        "SearchInternalError",
        "CaptureSearchInternalError",
        "RepositoryFailureError",
    }
)
_UNAVAILABLE_TYPE_NAMES = frozenset(
    {
        "SearchUnavailableError",
        "CaptureSearchUnavailableError",
        "EvidenceUnavailableError",
        "KeyError",
        "NotImplementedError",
    }
)

_EXTRACTION_COVERAGE: dict[ExtractionCoverageState, CoverageState] = {
    ExtractionCoverageState.PROCESSED: CoverageState.SEARCHED_COMPLETE,
    ExtractionCoverageState.PARTIALLY_PROCESSED: CoverageState.INCOMPLETE,
    ExtractionCoverageState.STALE: CoverageState.STALE,
    ExtractionCoverageState.SUPERSEDED: CoverageState.STALE,
    ExtractionCoverageState.UNAVAILABLE: CoverageState.UNAVAILABLE,
    ExtractionCoverageState.NOT_ENROLLED: CoverageState.NOT_ENROLLED,
    ExtractionCoverageState.ELIGIBLE: CoverageState.INCOMPLETE,
    ExtractionCoverageState.QUEUED: CoverageState.INCOMPLETE,
    ExtractionCoverageState.QUARANTINED: CoverageState.INCOMPLETE,
    ExtractionCoverageState.UNSUPPORTED: CoverageState.INCOMPLETE,
}


@dataclass
class PlaneGather:
    """What one plane contributed, including coverage and whether it internally faulted."""

    plane: ContextPlane
    evidence: list[PreparedContextEvidence] = field(default_factory=list)
    coverage: list[ContextCoverage] = field(default_factory=list)
    unavailable: bool = False
    incomplete: bool = False
    internal_fault: bool = False
    attempted: bool = True


def eligible_planes(*, managed_documents_composed: bool) -> tuple[ContextPlane, ...]:
    """Planes this composition may search. Relationship is not admitted on this UoW."""
    planes = [ContextPlane.KNOWLEDGE, ContextPlane.CAPTURE, ContextPlane.CONTINUITY]
    if managed_documents_composed:
        planes.append(ContextPlane.MANAGED_DOCUMENT)
    return tuple(planes)


def search_plane(
    plane: ContextPlane,
    *,
    unit_of_work: UnitOfWork,
    authorization: Authorization,
    query: SearchQuery,
    extra_terms: tuple[str, ...],
    subject_hints: tuple[str, ...],
    managed_documents_composed: bool,
) -> PlaneGather:
    """Search one plane, isolating local faults."""
    if plane is ContextPlane.RELATIONSHIP:
        return _relationship_unavailable()
    if plane is ContextPlane.MANAGED_DOCUMENT and not managed_documents_composed:
        return PlaneGather(
            plane=plane,
            coverage=[
                ContextCoverage(plane=plane, state=CoverageState.UNAVAILABLE),
            ],
            unavailable=True,
            attempted=False,
        )
    try:
        if plane is ContextPlane.KNOWLEDGE:
            return _search_knowledge(unit_of_work, authorization, query, extra_terms, subject_hints)
        if plane is ContextPlane.CAPTURE:
            return _search_capture(unit_of_work, authorization, query, extra_terms, subject_hints)
        if plane is ContextPlane.CONTINUITY:
            return _search_continuity(
                unit_of_work, authorization, query, extra_terms, subject_hints
            )
        return _search_managed_documents(
            unit_of_work, authorization, query, extra_terms, subject_hints
        )
    except (KeyError, NotImplementedError, EvidenceUnavailableError) as error:
        return _unavailable(plane, internal=False, error=error)
    except RepositoryFailureError as error:
        return _unavailable(plane, internal=True, error=error)
    except Exception as error:
        name = type(error).__name__
        if name in _UNAVAILABLE_TYPE_NAMES:
            return _unavailable(plane, internal=False, error=error)
        if name in _INTERNAL_TYPE_NAMES:
            return _unavailable(plane, internal=True, error=error)
        raise


def _unavailable(plane: ContextPlane, *, internal: bool, error: BaseException) -> PlaneGather:
    del error
    state = CoverageState.UNAVAILABLE
    return PlaneGather(
        plane=plane,
        coverage=[ContextCoverage(plane=plane, state=state)],
        unavailable=True,
        internal_fault=internal,
    )


def _relationship_unavailable() -> PlaneGather:
    return PlaneGather(
        plane=ContextPlane.RELATIONSHIP,
        coverage=[
            ContextCoverage(plane=ContextPlane.RELATIONSHIP, state=CoverageState.NOT_ADMITTED)
        ],
        unavailable=True,
        attempted=False,
    )


def _excerpt(text: str) -> str:
    excerpt, _truncated = bound_snippet(text)
    if len(excerpt) > MAX_EXCERPT_CHARACTERS:
        excerpt = excerpt[:MAX_EXCERPT_CHARACTERS].rstrip()
    return excerpt


def _tokens(*parts: str | None) -> tuple[str, ...]:
    seen: list[str] = []
    for part in parts:
        if not part:
            continue
        for token in part.split():
            lowered = token.lower()
            if lowered and lowered not in seen:
                seen.append(lowered)
    return tuple(seen)


def _whole_words(searchable: str) -> set[str]:
    return {part.lower() for part in searchable.split() if part}


def _all_whole_words(searchable: str, terms: tuple[str, ...]) -> bool:
    if not terms:
        return False
    words = _whole_words(searchable)
    return all(term in words for term in terms)


def _any_lexical(searchable: str, terms: tuple[str, ...]) -> bool:
    if not terms:
        return False
    lowered = searchable.lower()
    words = _whole_words(searchable)
    return any(term in words or term in lowered for term in terms)


def _identities(*values: str | None) -> frozenset[str]:
    return frozenset(value for value in values if value is not None)


def _reason_codes(
    *,
    identities: frozenset[str],
    searchable: str,
    query: SearchQuery,
    extra_terms: tuple[str, ...],
    subject_hints: tuple[str, ...],
    lexical_rank: RankCategory | None = None,
    accepted: bool = False,
    linked: tuple[SelectionReasonCode, ...] = (),
) -> tuple[SelectionReasonCode, ...]:
    codes: list[SelectionReasonCode] = []
    query_id = query.text
    if query_id in identities:
        codes.append(SelectionReasonCode.EXACT_IDENTIFIER)
    if any(hint in identities for hint in subject_hints):
        codes.append(SelectionReasonCode.EXPLICIT_SUBJECT)
        if SelectionReasonCode.EXACT_IDENTIFIER not in codes:
            codes.append(SelectionReasonCode.EXACT_IDENTIFIER)
    codes.extend(linked)
    if accepted:
        codes.append(SelectionReasonCode.ACCEPTED_RECORD)
    query_terms = _tokens(query.text)
    if lexical_rank is RankCategory.STRONG or _all_whole_words(searchable, query_terms):
        codes.append(SelectionReasonCode.LEXICAL_STRONG)
    elif (
        lexical_rank is RankCategory.MODERATE
        or lexical_rank is RankCategory.WEAK
        or _any_lexical(searchable, query_terms + extra_terms)
    ):
        codes.append(SelectionReasonCode.LEXICAL_MODERATE)
    return tuple(dict.fromkeys(codes))


def _map_extraction_coverage(state: ExtractionCoverageState) -> CoverageState:
    return _EXTRACTION_COVERAGE.get(state, CoverageState.INCOMPLETE)


def _search_knowledge(
    unit_of_work: UnitOfWork,
    authorization: Authorization,
    query: SearchQuery,
    extra_terms: tuple[str, ...],
    subject_hints: tuple[str, ...],
) -> PlaneGather:
    gather = PlaneGather(plane=ContextPlane.KNOWLEDGE)
    enrollments = authorization.enrollments
    if not enrollments:
        gather.coverage.append(
            ContextCoverage(plane=ContextPlane.KNOWLEDGE, state=CoverageState.NOT_ENROLLED)
        )
        gather.attempted = False
        return gather
    principal_id = authorization.principal.principal_id
    faults = 0
    for enrollment in enrollments:
        request = SearchRequest(enrollment_id=enrollment.enrollment_id, query=query)
        try:
            outcome = unit_of_work.knowledge.search(request, now=authorization.at)
        except (KeyError, NotImplementedError, EvidenceUnavailableError):
            gather.coverage.append(
                ContextCoverage(
                    plane=ContextPlane.KNOWLEDGE,
                    state=CoverageState.UNAVAILABLE,
                    enrollment_id=enrollment.enrollment_id,
                )
            )
            gather.unavailable = True
            continue
        except RepositoryFailureError:
            gather.coverage.append(
                ContextCoverage(
                    plane=ContextPlane.KNOWLEDGE,
                    state=CoverageState.UNAVAILABLE,
                    enrollment_id=enrollment.enrollment_id,
                )
            )
            gather.unavailable = True
            faults += 1
            continue
        except Exception as error:
            name = type(error).__name__
            if name in _UNAVAILABLE_TYPE_NAMES:
                gather.coverage.append(
                    ContextCoverage(
                        plane=ContextPlane.KNOWLEDGE,
                        state=CoverageState.UNAVAILABLE,
                        enrollment_id=enrollment.enrollment_id,
                    )
                )
                gather.unavailable = True
                continue
            if name in _INTERNAL_TYPE_NAMES:
                gather.coverage.append(
                    ContextCoverage(
                        plane=ContextPlane.KNOWLEDGE,
                        state=CoverageState.UNAVAILABLE,
                        enrollment_id=enrollment.enrollment_id,
                    )
                )
                gather.unavailable = True
                faults += 1
                continue
            raise
        gather.coverage.append(_knowledge_coverage(enrollment.enrollment_id, outcome))
        classification = outcome.disclosure.classification
        freshness = outcome.disclosure.freshness.observed_at
        for match in outcome.matches:
            text = _excerpt(match.snippet)
            if not text:
                continue
            identities = _identities(
                match.knowledge_id,
                match.source_id,
                match.source_object_id,
                match.version_id,
            )
            searchable = f"{match.snippet} {match.knowledge_id} {match.source_object_id}"
            extra_hit = _any_lexical(searchable, extra_terms)
            codes = _reason_codes(
                identities=identities,
                searchable=searchable,
                query=query,
                extra_terms=extra_terms,
                subject_hints=subject_hints,
                lexical_rank=match.rank,
            )
            if not codes and extra_hit:
                codes = (SelectionReasonCode.LEXICAL_MODERATE,)
            if not codes:
                continue
            gather.evidence.append(
                PreparedContextEvidence(
                    reference_id=match.knowledge_id,
                    principal_id=principal_id,
                    plane=ContextPlane.KNOWLEDGE,
                    authority_class=SourceAuthorityClass.ENROLLED_SOURCE,
                    lifecycle=EvidenceLifecycle.SOURCE_EVIDENCE,
                    text=text,
                    classification=classification,
                    freshness=freshness,
                    reason_codes=codes,
                    source_id=match.source_id,
                    source_object_id=match.source_object_id,
                    source_version_id=match.version_id,
                    knowledge_id=match.knowledge_id,
                )
            )
    if enrollments and faults == len(enrollments):
        gather.internal_fault = True
    return gather


def _knowledge_coverage(enrollment_id: str, outcome: SearchOutcome) -> ContextCoverage:
    mapped = _map_extraction_coverage(outcome.disclosure.coverage.state)
    incomplete = mapped is CoverageState.INCOMPLETE or outcome.disclosure.truncation.is_truncated
    if incomplete and mapped is CoverageState.SEARCHED_COMPLETE:
        mapped = CoverageState.INCOMPLETE
    return ContextCoverage(
        plane=ContextPlane.KNOWLEDGE,
        state=mapped,
        enrollment_id=enrollment_id,
        freshness=outcome.disclosure.freshness.observed_at,
    )


def _search_capture(
    unit_of_work: UnitOfWork,
    authorization: Authorization,
    query: SearchQuery,
    extra_terms: tuple[str, ...],
    subject_hints: tuple[str, ...],
) -> PlaneGather:
    principal_id = authorization.principal.principal_id
    matches: dict[tuple[str, str], None] = {}
    truncated = False
    for request_query in _capture_queries(query, extra_terms):
        outcome = unit_of_work.captures.search(
            CaptureSearchRequest(query=request_query, limit=32),
            principal_id=principal_id,
        )
        truncated = truncated or outcome.truncated
        for match in outcome.matches:
            matches[(match.capture_id, match.version_id)] = None
    evidence: list[PreparedContextEvidence] = []
    query_terms = _tokens(query.text)
    for capture_id, version_id in matches:
        stored = unit_of_work.captures.version(
            capture_id, version_id=version_id, principal_id=principal_id
        )
        if stored is None:
            continue
        item = _capture_evidence(stored, query, extra_terms, subject_hints, query_terms)
        if item is not None:
            evidence.append(item)
    state = CoverageState.INCOMPLETE if truncated else CoverageState.SEARCHED_COMPLETE
    return PlaneGather(
        plane=ContextPlane.CAPTURE,
        evidence=evidence,
        coverage=[ContextCoverage(plane=ContextPlane.CAPTURE, state=state)],
        incomplete=truncated,
    )


def _capture_queries(query: SearchQuery, extra_terms: tuple[str, ...]) -> tuple[SearchQuery, ...]:
    queries = [query]
    if extra_terms:
        joined = " ".join(extra_terms)
        try:
            extra = SearchQuery(joined)
        except SearchQueryError:
            extra = None
        if extra is not None and extra.fingerprint != query.fingerprint:
            queries.append(extra)
    return tuple(queries)


def _capture_evidence(
    stored: CaptureVersion,
    query: SearchQuery,
    extra_terms: tuple[str, ...],
    subject_hints: tuple[str, ...],
    query_terms: tuple[str, ...],
) -> PreparedContextEvidence | None:
    text = _excerpt(stored.content.text)
    if not text:
        return None
    identities = _identities(stored.capture_id, stored.version_id)
    searchable = stored.content.text
    codes = _reason_codes(
        identities=identities,
        searchable=searchable,
        query=query,
        extra_terms=extra_terms,
        subject_hints=subject_hints,
        lexical_rank=RankCategory.STRONG if _all_whole_words(searchable, query_terms) else None,
    )
    if not codes:
        if _any_lexical(searchable, extra_terms):
            codes = (SelectionReasonCode.LEXICAL_MODERATE,)
        else:
            return None
    return PreparedContextEvidence(
        reference_id=stored.version_id,
        principal_id=stored.owner_principal_id,
        plane=ContextPlane.CAPTURE,
        authority_class=SourceAuthorityClass.PRODUCT_OWNED_CAPTURE,
        lifecycle=EvidenceLifecycle.USER_AUTHORED,
        text=text,
        classification=stored.classification,
        freshness=stored.recorded_at,
        reason_codes=codes,
        capture_id=stored.capture_id,
        capture_version_id=stored.version_id,
    )


def _search_continuity(
    unit_of_work: UnitOfWork,
    authorization: Authorization,
    query: SearchQuery,
    extra_terms: tuple[str, ...],
    subject_hints: tuple[str, ...],
) -> PlaneGather:
    principal_id = authorization.principal.principal_id
    situations = unit_of_work.situations.list_situations(principal_id)
    projects = unit_of_work.projects.list_projects(principal_id)
    pulse = unit_of_work.pulse.derive_pulse(principal_id, authorization.at)
    evidence: list[PreparedContextEvidence] = []
    project_ids = {project.project_id for project in projects}
    for situation in situations:
        item = _situation_evidence(
            situation, query, extra_terms, subject_hints, project_ids, principal_id
        )
        if item is not None:
            evidence.append(item)
    for project in projects:
        item = _project_evidence(project, query, extra_terms, subject_hints, principal_id)
        if item is not None:
            evidence.append(item)
    for pulse_item in pulse:
        searchable = f"{pulse_item.reason} {pulse_item.item_ref} {pulse_item.pulse_id}"
        identities = _identities(pulse_item.pulse_id, pulse_item.item_ref, *pulse_item.basis_refs)
        if not _continuity_matches(searchable, identities, query, extra_terms, subject_hints):
            continue
        text = _excerpt(f"{pulse_item.item_ref} {pulse_item.reason}")
        if not text:
            continue
        try:
            parse_identifier(pulse_item.item_ref)
        except InvalidIdentifierError:
            continue
        codes = _reason_codes(
            identities=identities,
            searchable=searchable,
            query=query,
            extra_terms=extra_terms,
            subject_hints=subject_hints,
            accepted=True,
        )
        if not codes:
            continue
        try:
            evidence.append(
                PreparedContextEvidence(
                    reference_id=pulse_item.item_ref,
                    principal_id=principal_id,
                    plane=ContextPlane.CONTINUITY,
                    authority_class=SourceAuthorityClass.PRODUCT_OWNED_CONTINUITY,
                    lifecycle=EvidenceLifecycle.ACCEPTED,
                    text=text,
                    classification=Classification.PRIVATE_LOCAL,
                    freshness=pulse_item.generated_at,
                    reason_codes=codes,
                    product_id=pulse_item.item_ref,
                )
            )
        except PreparedContextError:
            continue
    try:
        continuity = unit_of_work.continuity_read
    except NotImplementedError:
        continuity = None
    if continuity is not None:
        _extend_continuity_read(
            evidence,
            continuity,
            principal_id,
            query,
            extra_terms,
            subject_hints,
        )
    return PlaneGather(
        plane=ContextPlane.CONTINUITY,
        evidence=evidence,
        coverage=[
            ContextCoverage(plane=ContextPlane.CONTINUITY, state=CoverageState.SEARCHED_COMPLETE)
        ],
    )


def _continuity_matches(
    searchable: str,
    identities: frozenset[str],
    query: SearchQuery,
    extra_terms: tuple[str, ...],
    subject_hints: tuple[str, ...],
) -> bool:
    if query.text in identities or any(hint in identities for hint in subject_hints):
        return True
    terms = _tokens(query.text) + extra_terms
    return _any_lexical(searchable, terms)


def _situation_evidence(
    situation: Situation,
    query: SearchQuery,
    extra_terms: tuple[str, ...],
    subject_hints: tuple[str, ...],
    project_ids: set[str],
    principal_id: str,
) -> PreparedContextEvidence | None:
    description = situation.description or ""
    searchable = f"{situation.title} {description} {situation.situation_id}"
    identities = _identities(situation.situation_id, *situation.object_refs)
    if not _continuity_matches(searchable, identities, query, extra_terms, subject_hints):
        return None
    linked: list[SelectionReasonCode] = []
    if any(ref in project_ids for ref in situation.object_refs):
        linked.append(SelectionReasonCode.PROJECT_LINK)
    if any(
        hint in situation.object_refs or hint == situation.situation_id for hint in subject_hints
    ):
        linked.append(SelectionReasonCode.SITUATION_LINK)
    text = _excerpt(situation.title if not description else f"{situation.title}: {description}")
    if not text:
        return None
    codes = _reason_codes(
        identities=identities,
        searchable=searchable,
        query=query,
        extra_terms=extra_terms,
        subject_hints=subject_hints,
        accepted=True,
        linked=tuple(linked),
    )
    if not codes:
        return None
    return PreparedContextEvidence(
        reference_id=situation.situation_id,
        principal_id=principal_id,
        plane=ContextPlane.CONTINUITY,
        authority_class=SourceAuthorityClass.PRODUCT_OWNED_CONTINUITY,
        lifecycle=EvidenceLifecycle.ACCEPTED,
        text=text,
        classification=Classification.PRIVATE_LOCAL,
        freshness=situation.updated_at,
        reason_codes=codes,
        product_id=situation.situation_id,
    )


def _project_evidence(
    project: Project,
    query: SearchQuery,
    extra_terms: tuple[str, ...],
    subject_hints: tuple[str, ...],
    principal_id: str,
) -> PreparedContextEvidence | None:
    description = project.description or ""
    searchable = f"{project.name} {description} {project.project_id}"
    identities = _identities(project.project_id, *project.participants)
    if not _continuity_matches(searchable, identities, query, extra_terms, subject_hints):
        return None
    linked: list[SelectionReasonCode] = []
    if query.text == project.project_id or project.project_id in subject_hints:
        linked.append(SelectionReasonCode.PROJECT_LINK)
    text = _excerpt(project.name if not description else f"{project.name}: {description}")
    if not text:
        return None
    codes = _reason_codes(
        identities=identities,
        searchable=searchable,
        query=query,
        extra_terms=extra_terms,
        subject_hints=subject_hints,
        accepted=True,
        linked=tuple(linked),
    )
    if not codes:
        return None
    return PreparedContextEvidence(
        reference_id=project.project_id,
        principal_id=principal_id,
        plane=ContextPlane.CONTINUITY,
        authority_class=SourceAuthorityClass.PRODUCT_OWNED_CONTINUITY,
        lifecycle=EvidenceLifecycle.ACCEPTED,
        text=text,
        classification=Classification.PRIVATE_LOCAL,
        freshness=project.updated_at,
        reason_codes=codes,
        product_id=project.project_id,
    )


def _extend_continuity_read(
    evidence: list[PreparedContextEvidence],
    continuity: object,
    principal_id: str,
    query: SearchQuery,
    extra_terms: tuple[str, ...],
    subject_hints: tuple[str, ...],
) -> None:
    """Optional accepted continuity projection. Identifier-first; never dumps free text."""
    listers = (
        ("commitments", "commitment_id", "summary"),
        ("decisions", "decision_id", "question"),
        ("tasks", "task_id", "title"),
    )
    for method_name, id_attr, text_attr in listers:
        method = getattr(continuity, method_name, None)
        if not callable(method):
            continue
        for record in method(principal_id):
            product_id = getattr(record, id_attr)
            label = getattr(record, text_attr, "") or product_id
            searchable = f"{label} {product_id}"
            identities = _identities(product_id)
            if not _continuity_matches(searchable, identities, query, extra_terms, subject_hints):
                continue
            text = _excerpt(str(label))
            if not text:
                continue
            codes = _reason_codes(
                identities=identities,
                searchable=searchable,
                query=query,
                extra_terms=extra_terms,
                subject_hints=subject_hints,
                accepted=True,
            )
            if not codes:
                continue
            if any(item.product_id == product_id for item in evidence):
                continue
            evidence.append(
                PreparedContextEvidence(
                    reference_id=product_id,
                    principal_id=principal_id,
                    plane=ContextPlane.CONTINUITY,
                    authority_class=SourceAuthorityClass.PRODUCT_OWNED_CONTINUITY,
                    lifecycle=EvidenceLifecycle.ACCEPTED,
                    text=text,
                    classification=Classification.PRIVATE_LOCAL,
                    reason_codes=codes,
                    product_id=product_id,
                )
            )


def _search_managed_documents(
    unit_of_work: UnitOfWork,
    authorization: Authorization,
    query: SearchQuery,
    extra_terms: tuple[str, ...],
    subject_hints: tuple[str, ...],
) -> PlaneGather:
    principal_id = authorization.principal.principal_id
    found = unit_of_work.managed_documents.documents(limit=32, principal_id=principal_id)
    evidence: list[PreparedContextEvidence] = []
    for document in found:
        searchable = f"{document.title} {document.document_id} {document.latest_version_id}"
        identities = _identities(document.document_id, document.latest_version_id)
        if not _continuity_matches(searchable, identities, query, extra_terms, subject_hints):
            continue
        text = _excerpt(document.title)
        if not text:
            continue
        codes = _reason_codes(
            identities=identities,
            searchable=searchable,
            query=query,
            extra_terms=extra_terms,
            subject_hints=subject_hints,
        )
        if not codes:
            continue
        evidence.append(
            PreparedContextEvidence(
                reference_id=document.latest_version_id,
                principal_id=principal_id,
                plane=ContextPlane.MANAGED_DOCUMENT,
                authority_class=SourceAuthorityClass.MANAGED_DOCUMENT,
                lifecycle=EvidenceLifecycle.USER_AUTHORED,
                text=text,
                classification=Classification.PRIVATE_LOCAL,
                freshness=document.latest_recorded_at,
                reason_codes=codes,
                managed_document_id=document.document_id,
                managed_document_version_id=document.latest_version_id,
            )
        )
    return PlaneGather(
        plane=ContextPlane.MANAGED_DOCUMENT,
        evidence=evidence,
        coverage=[
            ContextCoverage(
                plane=ContextPlane.MANAGED_DOCUMENT, state=CoverageState.SEARCHED_COMPLETE
            )
        ],
    )
