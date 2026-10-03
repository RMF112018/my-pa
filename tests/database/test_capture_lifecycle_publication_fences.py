"""Publication fences for an archived Capture root (CRL-WP-03 CP-CRL-05).

Each test admits a synthetic capture, archives it through the use case, and
shows the named sink refuses a new derivation. A foreign or absent root stays
`UnknownScopeError`. Reject of an already-open review case stays allowed and
writes no assertion.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine, func, insert, select, text
from sqlalchemy.engine import Connection

from my_pa.application.authorization import Authorization
from my_pa.application.capture_lifecycle import transition_capture
from my_pa.application.context.providers import PlaneGather
from my_pa.application.context.service import ContextPreparationService
from my_pa.application.relationship_memory import (
    MemoryProposalOrigin,
    ProposedEvidence,
    ProposeMemoryCommand,
    RelationshipMemoryProposalRepository,
    RelationshipMemoryProposalService,
)
from my_pa.contracts.ports import (
    AuditSink,
    CaptureAdmissionRequest,
    ReviewDecisionRequest,
    UnknownScopeError,
)
from my_pa.domain.capture.lifecycle import CaptureLifecycleOperation, CaptureWithdrawnError
from my_pa.domain.capture.proposal import ProposalMethod, ProposalState, ProposalType
from my_pa.domain.capture.review import Disposition
from my_pa.domain.capture.span import OffsetBasis, SpanRole
from my_pa.domain.capture.version import CaptureContent, ProcessingPolicy, digest_of
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.context.prepared import (
    ContextCoverage,
    ContextLimitationCode,
    ContextPlane,
    CoverageState,
    EvidenceLifecycle,
    PreparedContextEvidence,
    SourceAuthorityClass,
)
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import POLICY_VERSION, PolicyDecision
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import (
    PRODUCT_OWNED_CAPTURE_SOURCE_ID,
    EntityAssertionEvidence,
    EntityFactEvidenceLink,
    EntityObservation,
    EntityProposalEvidenceLink,
    EvidenceRole,
    MutationAuthority,
    MutationRecordFamily,
    ObservationAuthority,
    ObservationKind,
    ObservationState,
    capture_origin_triple,
)
from my_pa.domain.relationship.memory import EvidenceLinkRole, MemoryKind, MemoryProposalMethod
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.relationship.reenrichment import ReenrichmentSubjectKind
from my_pa.domain.search.query import SearchQuery
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.jobs.reenrichment import reenrichment_tables
from my_pa.infrastructure.persistence.capture import admit_capture, append_capture_label
from my_pa.infrastructure.persistence.capture_lifecycle import (
    require_active_capture_roots,
    retained_active_capture_roots,
)
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.entity_authoring import _record_evidence
from my_pa.infrastructure.persistence.entity_reenrichment import SqlCurrentReenrichmentBindings
from my_pa.infrastructure.persistence.principal_scope import PrincipalContext, capture_context
from my_pa.infrastructure.persistence.relationship_memory_proposals import (
    SqlRelationshipMemoryProposalRepository,
)
from my_pa.infrastructure.persistence.relationship_memory_review import (
    decide_relationship_memory_review,
)
from my_pa.infrastructure.persistence.review import decide_review, open_review_case
from my_pa.infrastructure.persistence.tables import (
    capture_labels,
    capture_proposal_spans,
    capture_proposals,
    capture_review_cases,
    capture_review_decisions,
    capture_spans,
    captures,
    context_run_items,
    entities,
    entity_assertion_evidence,
    entity_fact_evidence_links,
    entity_proposal_evidence_links,
    relationship_memory_proposals,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

NOW = datetime(2026, 10, 1, 18, 0, tzinfo=UTC)
REASON = "Synthetic withdrawal for a publication fence"
NOTE = "Synthetic fence note."


class _Audit(AuditSink):
    def record(self, event: object) -> None:  # type: ignore[override]
        del event


def _admit(connection: Connection, principal_id: str) -> tuple[str, str]:
    admission = admit_capture(
        connection,
        CaptureAdmissionRequest(
            capture_id=None,
            content=CaptureContent(NOTE),
            idempotency_key=f"fence-{issue_identifier(IdKind.CORRELATION)}",
            request_id=f"req-{issue_identifier(IdKind.CORRELATION)}",
            correlation_id=issue_identifier(IdKind.CORRELATION),
            principal_id=principal_id,
            audit_id=issue_identifier(IdKind.AUDIT),
            classification=Classification.PRIVATE_LOCAL,
            processing_policy=ProcessingPolicy.LOCAL_ONLY,
            server_received_at=NOW,
            accepted_at=NOW,
        ),
        context=capture_context(principal_id),
    )
    return admission.receipt.capture_id, admission.receipt.version_id


def _archive(engine: Engine, principal_id: str, capture_id: str) -> None:
    principal = Principal(principal_id, PrincipalKind.OPERATOR, authenticated=True)
    authorization = Authorization(
        principal=principal,
        capability=Capability.CAPTURE_REVISE,
        purpose=Purpose.CAPTURE_AUTHORING,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        request_id=f"req-{issue_identifier(IdKind.CORRELATION)}",
        audit_id=issue_identifier(IdKind.AUDIT),
        at=NOW,
        decision=PolicyDecision(allowed=True, policy_version=POLICY_VERSION),
        requested_source_ids=frozenset(),
        enrollments=(),
    )
    with SqlAlchemyUnitOfWork(engine, audit=_Audit()) as unit_of_work:
        transition_capture(
            unit_of_work,
            authorization,
            operation=CaptureLifecycleOperation.ARCHIVE,
            capture_id=capture_id,
            expected_lifecycle_revision=0,
            reason=REASON,
            idempotency_key=f"arch-{issue_identifier(IdKind.CORRELATION)}",
            now=NOW,
        )


def _context(principal_id: str) -> PrincipalContext:
    return capture_context(principal_id)


def _proposal(connection: Connection, version_id: str) -> tuple[str, str]:
    span_id = issue_identifier(IdKind.SPAN)
    proposal_id = issue_identifier(IdKind.PROPOSAL)
    digest = digest_of(NOTE[0:1])
    connection.execute(
        insert(capture_spans).values(
            span_id=span_id,
            version_id=version_id,
            start_offset=0,
            end_offset=1,
            offset_basis=OffsetBasis.UNICODE_CODE_POINT_V1.value,
            line_start=1,
            column_start=1,
            line_end=1,
            column_end=2,
            quoted_text_sha256=digest,
            span_role=SpanRole.DIRECT.value,
        )
    )
    connection.execute(
        insert(capture_proposals).values(
            proposal_id=proposal_id,
            version_id=version_id,
            proposal_type=ProposalType.COMMITMENT.value,
            state=ProposalState.PROPOSED.value,
            risk_class="high",
            method=ProposalMethod.DETERMINISTIC_RULE.value,
            method_version="v1",
            schema_version="v1",
        )
    )
    connection.execute(
        insert(capture_proposal_spans).values(proposal_id=proposal_id, span_id=span_id)
    )
    return proposal_id, span_id


def test_an_archived_root_is_withdrawn_and_a_foreign_root_is_not_found(
    migrated_engine: Engine,
) -> None:
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    other = issue_identifier(IdKind.PRINCIPAL)
    with migrated_engine.begin() as connection:
        capture_id, version_id = _admit(connection, principal_id)
        foreign_id, _version = _admit(connection, other)
        span_owner = _proposal(connection, version_id)[1]
    _archive(migrated_engine, principal_id, capture_id)
    with migrated_engine.begin() as connection:
        context = _context(principal_id)
        with pytest.raises(CaptureWithdrawnError):
            require_active_capture_roots(connection, context, capture_ids=(capture_id,))
        with pytest.raises(CaptureWithdrawnError):
            require_active_capture_roots(connection, context, version_ids=(version_id,))
        with pytest.raises(CaptureWithdrawnError):
            require_active_capture_roots(connection, context, span_ids=(span_owner,))
        absent = issue_identifier(IdKind.CAPTURE)
        with pytest.raises(UnknownScopeError):
            require_active_capture_roots(connection, context, capture_ids=(absent,))
        with pytest.raises(UnknownScopeError):
            require_active_capture_roots(connection, context, capture_ids=(foreign_id,))
        retained = retained_active_capture_roots(
            connection, context, capture_ids=(capture_id, foreign_id)
        )
    assert retained == ()


def test_a_label_on_an_archived_capture_is_refused(migrated_engine: Engine) -> None:
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    with migrated_engine.begin() as connection:
        capture_id, _version = _admit(connection, principal_id)
        stored = append_capture_label(
            connection, capture_id, "Fence label", context=_context(principal_id)
        )
    assert stored == "Fence label"
    _archive(migrated_engine, principal_id, capture_id)
    with pytest.raises(CaptureWithdrawnError), migrated_engine.begin() as connection:
        append_capture_label(
            connection, capture_id, "After archive", context=_context(principal_id)
        )
    with migrated_engine.connect() as connection:
        count = connection.execute(
            select(func.count())
            .select_from(capture_labels)
            .where(capture_labels.c.capture_id == capture_id)
        ).scalar_one()
    assert count == 1


def test_opening_and_accepting_a_review_of_an_archived_capture_writes_nothing(
    migrated_engine: Engine,
) -> None:
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    with migrated_engine.begin() as connection:
        capture_id, version_id = _admit(connection, principal_id)
        proposal_id, _span = _proposal(connection, version_id)
        case_id = open_review_case(connection, proposal_id)
    assert case_id is not None
    _archive(migrated_engine, principal_id, capture_id)
    with pytest.raises(CaptureWithdrawnError), migrated_engine.begin() as connection:
        open_review_case(connection, proposal_id)
    request = ReviewDecisionRequest(
        review_case_id=str(case_id),
        expected_review_version=0,
        disposition=Disposition.ACCEPT,
        principal_id=principal_id,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
        policy_version=POLICY_VERSION,
        decided_at=NOW,
    )
    with pytest.raises(CaptureWithdrawnError), migrated_engine.begin() as connection:
        decide_review(connection, request)
    rejected = ReviewDecisionRequest(
        review_case_id=str(case_id),
        expected_review_version=0,
        disposition=Disposition.REJECT,
        principal_id=principal_id,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
        policy_version=POLICY_VERSION,
        decided_at=NOW,
        reason="Synthetic class-3 refusal",
    )
    with migrated_engine.begin() as connection:
        decision = decide_review(connection, rejected)
    assert decision is not None
    assert decision.assertion_id is None
    with migrated_engine.connect() as connection:
        decisions = connection.execute(
            select(func.count())
            .select_from(capture_review_decisions)
            .where(capture_review_decisions.c.review_case_id == case_id)
        ).scalar_one()
        assertions = connection.execute(
            text("SELECT count(*) FROM knowledge.capture_assertions")
        ).scalar_one()
    assert decisions == 1
    assert assertions == 0


def test_work_evidence_on_an_archived_capture_is_withdrawn(migrated_engine: Engine) -> None:
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    with migrated_engine.begin() as connection:
        capture_id, _version = _admit(connection, principal_id)
    with SqlAlchemyUnitOfWork(migrated_engine, audit=_Audit()) as unit_of_work:
        assert unit_of_work.captures.accepts_work_evidence_reference(
            capture_id, principal_id=principal_id
        )
    _archive(migrated_engine, principal_id, capture_id)
    with (
        pytest.raises(CaptureWithdrawnError),
        SqlAlchemyUnitOfWork(migrated_engine, audit=_Audit()) as unit_of_work,
    ):
        unit_of_work.captures.accepts_work_evidence_reference(capture_id, principal_id=principal_id)
    absent = issue_identifier(IdKind.CAPTURE)
    with SqlAlchemyUnitOfWork(migrated_engine, audit=_Audit()) as unit_of_work:
        assert (
            unit_of_work.captures.accepts_work_evidence_reference(absent, principal_id=principal_id)
            is False
        )


def test_an_observation_of_an_archived_capture_is_refused(migrated_engine: Engine) -> None:
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    with migrated_engine.begin() as connection:
        capture_id, version_id = _admit(connection, principal_id)
    _archive(migrated_engine, principal_id, capture_id)
    source_id, source_object_id, source_version_id = capture_origin_triple(capture_id, version_id)
    assert source_id == PRODUCT_OWNED_CAPTURE_SOURCE_ID
    observation = EntityObservation(
        observation_id=issue_identifier(IdKind.ENTITY_OBSERVATION),
        principal_id=principal_id,
        kind=ObservationKind.USER_STATEMENT,
        observed_value="Synthetic mention",
        normalized_value=normalize_name("Synthetic mention"),
        source_id=source_id,
        source_object_id=source_object_id,
        source_version_id=source_version_id,
        observed_at=NOW,
        recorded_at=NOW,
        authority=ObservationAuthority.USER_AUTHORED_STATEMENT,
        state=ObservationState.CURRENT,
    )
    with pytest.raises(CaptureWithdrawnError), migrated_engine.begin() as connection:
        SqlEntityRepository(connection).record_observation(principal_id, observation)
    with migrated_engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT count(*) FROM knowledge.entity_observations "
                "WHERE observation_id = :observation_id"
            ),
            {"observation_id": observation.observation_id},
        ).scalar_one()
    assert stored == 0


def test_two_active_roots_share_in_sorted_order_and_one_archived_root_refuses_the_set(
    migrated_engine: Engine,
) -> None:
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    with migrated_engine.begin() as connection:
        first, _version = _admit(connection, principal_id)
        second, _other = _admit(connection, principal_id)
    with migrated_engine.begin() as connection:
        locked = require_active_capture_roots(
            connection, _context(principal_id), capture_ids=(second, first)
        )
    assert locked == tuple(sorted((first, second)))
    _archive(migrated_engine, principal_id, first)
    with pytest.raises(CaptureWithdrawnError), migrated_engine.begin() as connection:
        require_active_capture_roots(
            connection, _context(principal_id), capture_ids=(first, second)
        )
    with migrated_engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(captures)).scalar_one() >= 2
        cases = connection.execute(
            select(func.count()).select_from(capture_review_cases)
        ).scalar_one()
    assert cases == 0


def test_revising_an_archived_capture_is_refused(migrated_engine: Engine) -> None:
    """C-1: a revise of the caller's own archived root is withdrawn."""
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    with migrated_engine.begin() as connection:
        capture_id, _version = _admit(connection, principal_id)
    _archive(migrated_engine, principal_id, capture_id)
    with pytest.raises(CaptureWithdrawnError), migrated_engine.begin() as connection:
        admit_capture(
            connection,
            CaptureAdmissionRequest(
                capture_id=capture_id,
                content=CaptureContent("A successor the archive must refuse."),
                idempotency_key=f"revise-{issue_identifier(IdKind.CORRELATION)}",
                request_id=f"req-{issue_identifier(IdKind.CORRELATION)}",
                correlation_id=issue_identifier(IdKind.CORRELATION),
                principal_id=principal_id,
                audit_id=issue_identifier(IdKind.AUDIT),
                classification=Classification.PRIVATE_LOCAL,
                processing_policy=ProcessingPolicy.LOCAL_ONLY,
                server_received_at=NOW,
                accepted_at=NOW,
            ),
            context=_context(principal_id),
        )
    with migrated_engine.connect() as connection:
        versions = connection.execute(
            text("SELECT count(*) FROM knowledge.capture_versions WHERE capture_id = :capture_id"),
            {"capture_id": capture_id},
        ).scalar_one()
    assert versions == 1


def _archived_span(engine: Engine) -> tuple[str, str]:
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    with engine.begin() as connection:
        capture_id, version_id = _admit(connection, principal_id)
        span_id = _proposal(connection, version_id)[1]
    _archive(engine, principal_id, capture_id)
    return principal_id, span_id


def test_proposal_evidence_on_an_archived_span_is_refused(migrated_engine: Engine) -> None:
    """C-10 and C-12: a new proposal link, including one a reprocess would append, is refused."""
    principal_id, span_id = _archived_span(migrated_engine)
    link = EntityProposalEvidenceLink(
        proposal_id=issue_identifier(IdKind.ENTITY_PROPOSAL),
        principal_id=principal_id,
        sequence=1,
        role=EvidenceRole.DIRECT,
        created_at=NOW,
        capture_span_id=span_id,
    )
    with pytest.raises(CaptureWithdrawnError), migrated_engine.begin() as connection:
        SqlEntityRepository(connection).record_proposal_evidence_link(principal_id, link)
    with pytest.raises(CaptureWithdrawnError), migrated_engine.begin() as connection:
        SqlEntityRepository(connection).merge_proposal_evidence_links(
            principal_id, link.proposal_id, (link,)
        )
    with migrated_engine.connect() as connection:
        stored = connection.execute(
            select(func.count()).select_from(entity_proposal_evidence_links)
        ).scalar_one()
    assert stored == 0


def test_fact_evidence_on_an_archived_span_is_refused(migrated_engine: Engine) -> None:
    """C-11: promotion copies spans through this write, and an archived span stops it."""
    principal_id, span_id = _archived_span(migrated_engine)
    link = EntityFactEvidenceLink(
        link_id=issue_identifier(IdKind.ENTITY_FACT_EVIDENCE_LINK),
        principal_id=principal_id,
        role=EvidenceRole.DIRECT,
        authority=MutationAuthority.REVIEW_ACCEPTED,
        created_at=NOW,
        entity_id=issue_identifier(IdKind.ENTITY),
        capture_span_id=span_id,
    )
    with pytest.raises(CaptureWithdrawnError), migrated_engine.begin() as connection:
        SqlEntityRepository(connection).record_fact_evidence_link(principal_id, link)
    with migrated_engine.connect() as connection:
        stored = connection.execute(
            select(func.count()).select_from(entity_fact_evidence_links)
        ).scalar_one()
    assert stored == 0


def test_directed_evidence_on_an_archived_span_is_refused(migrated_engine: Engine) -> None:
    """C-14: ownership is decided first, then the archived root is withdrawn."""
    principal_id, span_id = _archived_span(migrated_engine)
    request = SimpleNamespace(
        evidence=(span_id,),
        minted_evidence_link_ids=(issue_identifier(IdKind.ENTITY_FACT_EVIDENCE_LINK),),
        record_family=MutationRecordFamily.ENTITY,
        principal_id=principal_id,
        authority=MutationAuthority.USER_CONFIRMED_ASSERTION,
        server_received_at=NOW,
    )
    with pytest.raises(CaptureWithdrawnError), migrated_engine.begin() as connection:
        _record_evidence(connection, request, SimpleNamespace(record_id="unused"))  # type: ignore[arg-type]
    with migrated_engine.connect() as connection:
        stored = connection.execute(
            select(func.count()).select_from(entity_fact_evidence_links)
        ).scalar_one()
    assert stored == 0


def test_assertion_evidence_on_an_archived_span_is_refused(migrated_engine: Engine) -> None:
    """C-15: a record-family assertion cannot cite an archived span."""
    principal_id, span_id = _archived_span(migrated_engine)
    evidence = EntityAssertionEvidence(
        evidence_id=issue_identifier(IdKind.ENTITY_ASSERTION_EVIDENCE),
        principal_id=principal_id,
        assertion_id=issue_identifier(IdKind.ENTITY_ASSERTION),
        role=EvidenceRole.SUPPORTING,
        created_at=NOW,
        capture_span_id=span_id,
    )
    with pytest.raises(CaptureWithdrawnError), migrated_engine.begin() as connection:
        SqlEntityRepository(connection).record_assertion_evidence(principal_id, evidence)
    with migrated_engine.connect() as connection:
        stored = connection.execute(
            select(func.count()).select_from(entity_assertion_evidence)
        ).scalar_one()
    assert stored == 0


class _MemoryRecorder(RelationshipMemoryProposalRepository):
    def __init__(self) -> None:
        self.recorded: tuple[object, tuple[object, ...]] | None = None

    def record_proposal(
        self, proposal: object, evidence: tuple[object, ...]
    ) -> tuple[object, int, bool]:
        self.recorded = (proposal, evidence)
        return proposal, len(evidence), True


def test_a_memory_proposal_on_an_archived_span_is_refused(migrated_engine: Engine) -> None:
    """C-16: the span is owned, then its archived root refuses the proposal."""
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    entity_id = issue_identifier(IdKind.ENTITY)
    with migrated_engine.begin() as connection:
        capture_id, version_id = _admit(connection, principal_id)
        span_id = _proposal(connection, version_id)[1]
        connection.execute(
            insert(entities).values(
                entity_id=entity_id,
                principal_id=principal_id,
                entity_type="person",
                canonical_name="synthetic person",
                display_name="Synthetic Person",
                status="active",
                created_at=NOW,
                updated_at=NOW,
                version=1,
            )
        )
    recorder = _MemoryRecorder()
    RelationshipMemoryProposalService().propose(
        recorder,
        ProposeMemoryCommand(
            principal_id=principal_id,
            subject_entity_id=entity_id,
            expected_subject_version=1,
            memory_kind=MemoryKind.WORKING_PREFERENCE,
            statement="prefers the fence note in writing",
            structured_value=None,
            evidence=(ProposedEvidence(role=EvidenceLinkRole.SUPPORTING, capture_span_id=span_id),),
        ),
        subject=Entity(
            entity_id=entity_id,
            principal_id=principal_id,
            entity_type=EntityType.PERSON,
            canonical_name="synthetic person",
            display_name="Synthetic Person",
            status=EntityStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
            version=1,
        ),
        origin=MemoryProposalOrigin(
            method=MemoryProposalMethod.RULE, method_version="synthetic-rule-v1"
        ),
        at=NOW,
    )
    assert recorder.recorded is not None
    proposal, evidence = recorder.recorded
    _archive(migrated_engine, principal_id, capture_id)
    with pytest.raises(CaptureWithdrawnError), migrated_engine.begin() as connection:
        SqlRelationshipMemoryProposalRepository(connection).record_proposal(
            proposal,
            evidence,  # type: ignore[arg-type]
        )
    with migrated_engine.connect() as connection:
        stored = connection.execute(
            select(func.count()).select_from(relationship_memory_proposals)
        ).scalar_one()
    assert stored == 0


def test_accepting_a_memory_review_of_an_archived_span_is_refused(
    migrated_engine: Engine,
) -> None:
    """C-17: accept shares cited spans before the entity locks. Reject stays class 3."""
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    entity_id = issue_identifier(IdKind.ENTITY)
    with migrated_engine.begin() as connection:
        capture_id, version_id = _admit(connection, principal_id)
        span_id = _proposal(connection, version_id)[1]
        connection.execute(
            insert(entities).values(
                entity_id=entity_id,
                principal_id=principal_id,
                entity_type="person",
                canonical_name="synthetic person",
                display_name="Synthetic Person",
                status="active",
                created_at=NOW,
                updated_at=NOW,
                version=1,
            )
        )
    recorder = _MemoryRecorder()
    receipt = RelationshipMemoryProposalService().propose(
        recorder,
        ProposeMemoryCommand(
            principal_id=principal_id,
            subject_entity_id=entity_id,
            expected_subject_version=1,
            memory_kind=MemoryKind.WORKING_PREFERENCE,
            statement="prefers the review fence in writing",
            structured_value=None,
            evidence=(ProposedEvidence(role=EvidenceLinkRole.DIRECT, capture_span_id=span_id),),
        ),
        subject=Entity(
            entity_id=entity_id,
            principal_id=principal_id,
            entity_type=EntityType.PERSON,
            canonical_name="synthetic person",
            display_name="Synthetic Person",
            status=EntityStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
            version=1,
        ),
        origin=MemoryProposalOrigin(
            method=MemoryProposalMethod.RULE, method_version="synthetic-rule-v1"
        ),
        at=NOW,
    )
    assert recorder.recorded is not None
    proposal, evidence = recorder.recorded
    with migrated_engine.begin() as connection:
        SqlRelationshipMemoryProposalRepository(connection).record_proposal(
            proposal,
            evidence,  # type: ignore[arg-type]
        )
    _archive(migrated_engine, principal_id, capture_id)
    accepted = ReviewDecisionRequest(
        review_case_id=receipt.review_case_id,
        expected_review_version=0,
        disposition=Disposition.ACCEPT,
        principal_id=principal_id,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
        policy_version=POLICY_VERSION,
        decided_at=NOW,
    )
    with pytest.raises(CaptureWithdrawnError), migrated_engine.begin() as connection:
        decide_relationship_memory_review(connection, accepted)
    with migrated_engine.connect() as connection:
        memories = connection.execute(
            text("SELECT count(*) FROM knowledge.relationship_memories")
        ).scalar_one()
    assert memories == 0


def test_context_prepare_drops_an_archived_capture(
    migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-18: publication revalidation drops an item archived after selection."""
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    with migrated_engine.begin() as connection:
        capture_id, version_id = _admit(connection, principal_id)
    _archive(migrated_engine, principal_id, capture_id)
    item = PreparedContextEvidence(
        reference_id=capture_id,
        principal_id=principal_id,
        plane=ContextPlane.CAPTURE,
        authority_class=SourceAuthorityClass.PRODUCT_OWNED_CAPTURE,
        lifecycle=EvidenceLifecycle.USER_AUTHORED,
        text=NOTE,
        freshness=NOW,
        capture_id=capture_id,
        capture_version_id=version_id,
    )

    def _selected(plane: ContextPlane, **_kwargs: object) -> PlaneGather:
        return PlaneGather(
            plane=plane,
            evidence=[item],
            coverage=[ContextCoverage(plane=plane, state=CoverageState.SEARCHED_COMPLETE)],
        )

    monkeypatch.setattr("my_pa.application.context.service.search_plane", _selected)
    principal = Principal(principal_id, PrincipalKind.OPERATOR, authenticated=True)
    authorization = Authorization(
        principal=principal,
        capability=Capability.CONTEXT_PREPARE,
        purpose=Purpose.CONTEXT_PREPARATION,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        request_id=f"req-{issue_identifier(IdKind.CORRELATION)}",
        audit_id=issue_identifier(IdKind.AUDIT),
        at=NOW,
        decision=PolicyDecision(allowed=True, policy_version=POLICY_VERSION),
        requested_source_ids=frozenset(),
        enrollments=(),
    )
    with SqlAlchemyUnitOfWork(migrated_engine, audit=_Audit()) as unit_of_work:
        prepared = ContextPreparationService(managed_documents_composed=False).prepare(
            unit_of_work,
            authorization,
            command=SimpleNamespace(  # type: ignore[arg-type]
                query="fence",
                conversation_context=None,
                subject_hints=(),
                requested_planes=(ContextPlane.CAPTURE,),
            ),
            query=SearchQuery("fence"),
        )
    assert ContextLimitationCode.CAPTURE_WITHDRAWN in prepared.limitations
    assert all(cited.capture_id != capture_id for cited in prepared.evidence)
    with migrated_engine.connect() as connection:
        cited = connection.execute(
            select(func.count())
            .select_from(context_run_items)
            .where(context_run_items.c.capture_id == capture_id)
        ).scalar_one()
    assert cited == 0


def test_reenrichment_still_reads_an_archived_capture_version(migrated_engine: Engine) -> None:
    """C-22: settlement reads the version number and leaves the bytes and span alone."""
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    with migrated_engine.begin() as connection:
        capture_id, version_id = _admit(connection, principal_id)
        span_id = _proposal(connection, version_id)[1]
        before = connection.execute(
            text("SELECT content FROM knowledge.capture_versions WHERE version_id = :version_id"),
            {"version_id": version_id},
        ).scalar_one()
    _archive(migrated_engine, principal_id, capture_id)
    with migrated_engine.begin() as connection:
        current = SqlCurrentReenrichmentBindings(connection, reenrichment_tables()).subject_version(
            principal_id, ReenrichmentSubjectKind.CAPTURE, capture_id
        )
        after = connection.execute(
            text("SELECT content FROM knowledge.capture_versions WHERE version_id = :version_id"),
            {"version_id": version_id},
        ).scalar_one()
        span = connection.execute(
            text("SELECT span_id FROM knowledge.capture_spans WHERE span_id = :span_id"),
            {"span_id": span_id},
        ).scalar_one()
    assert current == "1"
    assert after == before
    assert span == span_id
