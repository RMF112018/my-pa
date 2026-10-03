"""Read-time lifecycle disclosure (CRL-WP-03 CP-CRL-06).

The overlay names the current state of a root the caller owns. A foreign or
absent root is omitted, so the surface shows it as unavailable. Stored bytes,
spans, and frozen context-run rows stay as they were.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

from my_pa.application.authorization import Authorization
from my_pa.application.commands import (
    GetCommitmentHistory,
    ListCommitments,
    ListEntityObservations,
    ListReviewCases,
    ListTasks,
    ListUnresolvedMentions,
    ReadCommitment,
    ReadTask,
    RevealSubject,
    SearchCommitments,
    SearchTasks,
    WaitingOn,
)
from my_pa.application.commitments import CommitmentManagementService
from my_pa.application.context.providers import PlaneGather
from my_pa.application.context.service import ContextPreparationService
from my_pa.application.service import ApplicationService
from my_pa.application.tasks import TaskManagementService
from my_pa.contracts.ports import ReviewDecisionRequest
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.context.prepared import (
    ContextCoverage,
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
from my_pa.domain.relationship.governance import (
    PRODUCT_OWNED_CAPTURE_SOURCE_ID,
    EntityObservation,
    ObservationAuthority,
    ObservationKind,
    ObservationState,
    capture_origin_triple,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.search.query import SearchQuery
from my_pa.domain.situation.continuity import CommitmentDirection
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.history import TaskMutationActor
from my_pa.domain.task.lifecycle import TaskOriginKind
from my_pa.infrastructure.persistence.capture_lifecycle import (
    capture_lifecycle_states,
    evidence_lifecycle_states,
)
from my_pa.infrastructure.persistence.commitment_management import (
    SqlAlchemyCommitmentManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.principal_scope import capture_context
from my_pa.infrastructure.persistence.review import decide_review, open_review_case
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.test_capture_lifecycle_publication_fences import (
    NOTE,
    NOW,
    _admit,
    _archive,
    _Audit,
    _proposal,
)

pytestmark = pytest.mark.database

_LIMITS = EffectiveLimits(
    max_page_size=50,
    default_page_size=20,
    max_fetch_bytes=1024,
    max_enrollment_depth=1,
)


def _auth(principal_id: str, capability: Capability, purpose: Purpose) -> Authorization:
    return Authorization(
        principal=Principal(principal_id, PrincipalKind.OPERATOR, authenticated=True),
        capability=capability,
        purpose=purpose,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        request_id=f"req-{issue_identifier(IdKind.CORRELATION)}",
        audit_id=issue_identifier(IdKind.AUDIT),
        at=NOW,
        decision=PolicyDecision(allowed=True, policy_version=POLICY_VERSION),
        requested_source_ids=frozenset(),
        enrollments=(),
    )


def _service(engine: Engine) -> ApplicationService:
    return ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(engine, audit=_Audit()),
        limits=_LIMITS,
        clock=lambda: NOW,
        relationship_intelligence_enabled=True,
    )


def _observe(
    connection: Connection,
    principal_id: str,
    *,
    source_id: str,
    source_object_id: str,
    source_version_id: str,
) -> str:
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
    SqlEntityRepository(connection).record_observation(principal_id, observation)
    return observation.observation_id


def test_owned_states_are_disclosed_and_foreign_roots_are_omitted(
    migrated_engine: Engine,
) -> None:
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    other = issue_identifier(IdKind.PRINCIPAL)
    absent = issue_identifier(IdKind.CAPTURE)
    with migrated_engine.begin() as connection:
        capture_id, _version_id = _admit(connection, principal_id)
        foreign_id, _foreign_version = _admit(connection, other)
        context = capture_context(principal_id)
        active = capture_lifecycle_states(
            connection, (capture_id, foreign_id, absent), context=context
        )
    assert set(active) == {capture_id}
    assert active[capture_id].value == "active"
    _archive(migrated_engine, principal_id, capture_id)
    with migrated_engine.begin() as connection:
        rooted, rooted_version = _admit(connection, principal_id)
        proposal_id, _span = _proposal(connection, rooted_version)
        case_id = open_review_case(connection, proposal_id)
        decision = decide_review(
            connection,
            ReviewDecisionRequest(
                review_case_id=str(case_id),
                expected_review_version=0,
                disposition=Disposition.ACCEPT,
                principal_id=principal_id,
                correlation_id=issue_identifier(IdKind.CORRELATION),
                audit_id=issue_identifier(IdKind.AUDIT),
                policy_version=POLICY_VERSION,
                decided_at=NOW,
            ),
        )
    assert decision is not None and decision.assertion_id is not None
    assertion_id = decision.assertion_id
    _archive(migrated_engine, principal_id, rooted)
    with migrated_engine.connect() as connection:
        states = evidence_lifecycle_states(
            connection,
            (capture_id, rooted, assertion_id, foreign_id, absent, "not-an-id"),
            context=capture_context(principal_id),
        )
    assert states[capture_id] == "archived"
    assert states[rooted] == "archived"
    assert states[assertion_id] == "archived"
    assert foreign_id not in states
    assert absent not in states


def test_read_surfaces_name_an_archived_root_without_rewriting_bytes(
    migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    other = issue_identifier(IdKind.PRINCIPAL)
    absent = issue_identifier(IdKind.CAPTURE)
    with migrated_engine.begin() as connection:
        capture_id, version_id = _admit(connection, principal_id)
        foreign_id, _foreign_version = _admit(connection, other)
        source_id, source_object_id, source_version_id = capture_origin_triple(
            capture_id, version_id
        )
        owned_observation = _observe(
            connection,
            principal_id,
            source_id=source_id,
            source_object_id=source_object_id,
            source_version_id=source_version_id,
        )
        configured_observation = _observe(
            connection,
            principal_id,
            source_id=issue_identifier(IdKind.SOURCE),
            source_object_id=issue_identifier(IdKind.SOURCE_OBJECT),
            source_version_id=issue_identifier(IdKind.VERSION),
        )
        proposal_id, _span = _proposal(connection, version_id)
        open_review_case(connection, proposal_id)
    assert source_id == PRODUCT_OWNED_CAPTURE_SOURCE_ID
    tasks = TaskManagementService(
        unit_of_work=lambda: SqlAlchemyTaskManagementUnitOfWork(migrated_engine),
        clock=lambda: NOW,
    )
    owned_task = tasks.create_task(
        principal_id=principal_id,
        title="ProvenanceNeedle owned",
        origin_kind=TaskOriginKind.EVIDENCE,
        origin_evidence_ref=capture_id,
        actor=TaskMutationActor.PRINCIPAL,
    ).task.task_id
    foreign_task = tasks.create_task(
        principal_id=principal_id,
        title="ProvenanceNeedle foreign",
        origin_kind=TaskOriginKind.EVIDENCE,
        origin_evidence_ref=foreign_id,
        actor=TaskMutationActor.PRINCIPAL,
    ).task.task_id
    absent_task = tasks.create_task(
        principal_id=principal_id,
        title="ProvenanceNeedle absent",
        origin_kind=TaskOriginKind.EVIDENCE,
        origin_evidence_ref=absent,
        actor=TaskMutationActor.PRINCIPAL,
    ).task.task_id
    commitments = CommitmentManagementService(
        unit_of_work=lambda: SqlAlchemyCommitmentManagementUnitOfWork(migrated_engine),
        clock=lambda: NOW,
    )
    commitment_id = commitments.create_commitment(
        principal_id=principal_id,
        counterparty_person_id=issue_identifier(IdKind.PERSON),
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
        summary="ProvenanceNeedle commitment",
        origin_evidence_ref=capture_id,
        accepted_by_review_decision_id=issue_identifier(IdKind.REVIEW_DECISION),
        actor=TaskMutationActor.PRINCIPAL,
    ).commitment.commitment_id
    service = _service(migrated_engine)
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
    with SqlAlchemyUnitOfWork(migrated_engine, audit=_Audit()) as unit_of_work:
        prepared = ContextPreparationService(managed_documents_composed=False).prepare(
            unit_of_work,
            _auth(principal_id, Capability.CONTEXT_PREPARE, Purpose.CONTEXT_PREPARATION),
            command=SimpleNamespace(  # type: ignore[arg-type]
                query="provenance",
                conversation_context=None,
                subject_hints=(),
                requested_planes=(ContextPlane.CAPTURE,),
            ),
            query=SearchQuery("provenance"),
        )
        reveal = service._knowledge_reveal(
            unit_of_work,
            _auth(principal_id, Capability.KNOWLEDGE_REVEAL, Purpose.CAPTURE_REVIEW),
            RevealSubject(subject_id=capture_id),
        )
    assert prepared.evidence[0].capture_lifecycle_state == "active"
    assert reveal.payload["capture_lifecycle_state"] == "active"
    assert reveal.payload["versions"][0]["capture_lifecycle_state"] == "active"
    assert "capture_lifecycle_state" not in reveal.payload["spans"][0]
    _archive(migrated_engine, principal_id, capture_id)
    with migrated_engine.connect() as connection:
        column = connection.execute(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema = 'knowledge' AND table_name = 'context_run_items' "
                "AND column_name = 'capture_lifecycle_state'"
            )
        ).scalar_one()
    assert column == 0
    with SqlAlchemyUnitOfWork(migrated_engine, audit=_Audit()) as unit_of_work:
        archived = service._knowledge_reveal(
            unit_of_work,
            _auth(principal_id, Capability.KNOWLEDGE_REVEAL, Purpose.CAPTURE_REVIEW),
            RevealSubject(subject_id=capture_id),
        )
        listed = service._review_list(
            unit_of_work,
            _auth(principal_id, Capability.REVIEW_LIST, Purpose.CAPTURE_REVIEW),
            ListReviewCases(page_size=20),
        )
        observations = service._entities_observations_list(
            unit_of_work,
            _auth(principal_id, Capability.ENTITIES_OBSERVATIONS_LIST, Purpose.ENTITY_READ),
            ListEntityObservations(page_size=20),
        )
        mentions = service._entities_unresolved_mentions(
            unit_of_work,
            _auth(principal_id, Capability.ENTITIES_UNRESOLVED_MENTIONS, Purpose.ENTITY_READ),
            ListUnresolvedMentions(page_size=20),
        )
        task_read = service._tasks_read(
            unit_of_work,
            _auth(principal_id, Capability.TASKS_READ, Purpose.TASK_READ),
            ReadTask(task_id=owned_task),
        )
        task_list = service._tasks_list(
            unit_of_work,
            _auth(principal_id, Capability.TASKS_LIST, Purpose.TASK_READ),
            ListTasks(page_size=20),
        )
        task_search = service._tasks_search(
            unit_of_work,
            _auth(principal_id, Capability.TASKS_SEARCH, Purpose.TASK_READ),
            SearchTasks(query="ProvenanceNeedle"),
        )
        commitment_read = service._commitments_read(
            unit_of_work,
            _auth(principal_id, Capability.COMMITMENTS_READ, Purpose.COMMITMENT_READ),
            ReadCommitment(commitment_id=commitment_id),
        )
        commitment_list = service._commitments_list(
            unit_of_work,
            _auth(principal_id, Capability.COMMITMENTS_LIST, Purpose.COMMITMENT_READ),
            ListCommitments(page_size=20),
        )
        commitment_search = service._commitments_search(
            unit_of_work,
            _auth(principal_id, Capability.COMMITMENTS_SEARCH, Purpose.COMMITMENT_READ),
            SearchCommitments(query="ProvenanceNeedle"),
        )
        history = service._commitments_history(
            unit_of_work,
            _auth(principal_id, Capability.COMMITMENTS_HISTORY, Purpose.COMMITMENT_READ),
            GetCommitmentHistory(commitment_id=commitment_id, page_size=20),
        )
        waiting = service._commitments_waiting_on(
            unit_of_work,
            _auth(principal_id, Capability.COMMITMENTS_WAITING_ON, Purpose.COMMITMENT_READ),
            WaitingOn(page_size=20),
        )
    assert archived.payload["capture_lifecycle_state"] == "archived"
    assert archived.payload["versions"][0]["capture_lifecycle_state"] == "archived"
    assert archived.payload["versions"][0]["version_id"] == version_id
    capture_cases = [
        case for case in listed.payload["review_cases"] if case.get("capture_id") == capture_id
    ]
    assert capture_cases
    assert capture_cases[0]["capture_lifecycle_state"] == "archived"
    others = [case for case in listed.payload["review_cases"] if "capture_id" not in case]
    assert all("capture_lifecycle_state" not in case for case in others)
    by_observation = {row["observation_id"]: row for row in observations.payload["observations"]}
    assert by_observation[owned_observation]["capture_lifecycle_state"] == "archived"
    assert "capture_lifecycle_state" not in by_observation[configured_observation]
    by_mention = {row["observation_id"]: row for row in mentions.payload["mentions"]}
    assert by_mention[owned_observation]["capture_lifecycle_state"] == "archived"
    assert "capture_lifecycle_state" not in by_mention[configured_observation]
    assert task_read.payload["task"]["origin_evidence_capture_state"] == "archived"
    listed_tasks = {row["task_id"]: row for row in task_list.payload["tasks"]}
    assert listed_tasks[owned_task]["origin_evidence_capture_state"] == "archived"
    assert listed_tasks[foreign_task]["origin_evidence_capture_state"] is None
    assert listed_tasks[absent_task]["origin_evidence_capture_state"] is None
    searched = {row["task_id"]: row for row in task_search.payload["tasks"]}
    assert searched[owned_task]["origin_evidence_capture_state"] == "archived"
    commitment = commitment_read.payload["commitment"]
    assert commitment["origin_evidence_capture_state"] == "archived"
    listed_commitments = {
        row["commitment_id"]: row for row in commitment_list.payload["commitments"]
    }
    assert listed_commitments[commitment_id]["origin_evidence_capture_state"] == "archived"
    found = {row["commitment_id"]: row for row in commitment_search.payload["commitments"]}
    assert found[commitment_id]["origin_evidence_capture_state"] == "archived"
    assert history.payload["history"]
    assert all(
        row["origin_evidence_capture_state"] == "archived" for row in history.payload["history"]
    )
    waiting_rows = {row["commitment_id"]: row for row in waiting.payload["waiting_on"]}
    assert waiting_rows[commitment_id]["origin_evidence_capture_state"] == "archived"
