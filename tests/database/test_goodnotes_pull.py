"""Isolated PostgreSQL checks for the durable GoodNotes pull ledger."""

from __future__ import annotations

import hashlib
import hmac
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier
from typing import Final

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError

from my_pa.application.commands import CompleteGoodNotesPull
from my_pa.application.goodnotes_occurrences import semantic_proposal_sha256
from my_pa.application.goodnotes_pull_orchestration import (
    PullAssignment,
    PullCompletion,
    PullCompletionAdmission,
    PullRepositoryConflictError,
    SemanticReviewConflictError,
    SemanticReviewDecision,
)
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.gateway import local_principal
from my_pa.contracts.ports import ReviewDecisionRequest
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.domain.capture.review import Disposition, ReviewConflictError, ReviewDecision
from my_pa.domain.goodnotes.models import GoodNotesSemanticReviewCase
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.goodnotes_pull import (
    SqlGoodNotesPullRepository,
    _corrected_result_sha256,
    _semantic_review_case_id,
)
from my_pa.infrastructure.persistence.tables import (
    goodnotes_ingestion_run_stages,
    goodnotes_ingestion_runs,
    goodnotes_logical_pages,
    goodnotes_notebooks,
    goodnotes_page_positions,
    goodnotes_page_rasters,
    goodnotes_page_versions,
    goodnotes_pages,
    goodnotes_semantic_promotion_receipts,
    goodnotes_semantic_proposals,
    goodnotes_semantic_review_decisions,
    goodnotes_source_snapshots,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.conftest import DEFAULT_LIMITS

pytestmark = pytest.mark.database

PRINCIPAL: Final = local_principal().principal_id
WHEN: Final = datetime(2026, 9, 4, 5, 0, tzinfo=UTC)


@pytest.fixture
def engine(db_engine: Engine) -> Engine:
    return db_engine


def test_empty_claim_replays_after_restart_and_status_is_content_free(
    engine: Engine,
) -> None:
    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(connection)
        assert (
            repository.claim_batch(PRINCIPAL, "scheduler-a", "ctx-stable-a", (), (), max_attempts=3)
            == ()
        )
    with engine.begin() as connection:
        restarted = SqlGoodNotesPullRepository(connection)
        assert (
            restarted.claim_batch(PRINCIPAL, "scheduler-a", "ctx-stable-a", (), (), max_attempts=3)
            == ()
        )
        status = restarted.status(PRINCIPAL, "scheduler-a")
        assert (status.pending, status.assigned, status.completed, status.exhausted) == (
            0,
            0,
            0,
            0,
        )
        row = connection.execute(
            text(
                "SELECT assignment_count, request_fingerprint "
                "FROM knowledge.goodnotes_pull_claims WHERE principal_id = :principal"
            ),
            {"principal": PRINCIPAL},
        ).one()
        assert row.assignment_count == 0
        assert len(row.request_fingerprint) == 64


def test_session_identity_and_retry_policy_fail_closed(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(connection)
        repository.claim_batch(PRINCIPAL, "scheduler-a", "ctx-stable-a", (), (), max_attempts=3)
        with pytest.raises(PullRepositoryConflictError):
            repository.claim_batch(PRINCIPAL, "scheduler-a", "ctx-other", (), (), max_attempts=3)
        with pytest.raises(PullRepositoryConflictError):
            repository.claim_batch(PRINCIPAL, "scheduler-a", "ctx-stable-a", (), (), max_attempts=4)


@pytest.mark.parametrize("canonical_enabled", [False, True])
def test_semantic_review_exact_replay_conflict_projection_and_client_status_isolation(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, canonical_enabled: bool
) -> None:
    run_id = "gnrun_0123456789abcdef01234567"
    proposal_id = "gnprp_0123456789abcdef01234567"
    notebook_id = "gnnb_0123456789abcdef01234567"
    logical_page_id = "gnlp_0123456789abcdef01234567"
    snapshot_id = "gnsnap_0123456789abcdef01234567"
    page_version_id = "gnver_0123456789abcdef01234567"
    payload: dict[str, object] = {
        "segments": [
            {
                "kind": "SOURCE_CONTEXT",
                "transcription": "synthetic context",
                "geometry": {"x_min": 0.1, "y_min": 0.1, "width": 0.2, "height": 0.2},
            }
        ],
        "candidate_tags": [],
        "ranked_candidates": [],
        "confidence": None,
    }
    corrected_payload = {**payload, "confidence": 0.75}
    original_result_sha256 = _corrected_result_sha256(payload)
    corrected_result_sha256 = _corrected_result_sha256(corrected_payload)
    proposal_sha256 = semantic_proposal_sha256(page_version_id, "v1", "test", "1", payload)
    context_id = hmac.new(
        b"k" * 32,
        b"goodnotes-pull-context-v1\0" + PRINCIPAL.encode("utf-8") + b"\0scheduler-a",
        hashlib.sha256,
    ).hexdigest()
    decision = SemanticReviewDecision(
        decision_id="gnsrd_0123456789abcdef01234567",
        principal_id=PRINCIPAL,
        run_id=run_id,
        proposal_id=proposal_id,
        proposal_sha256=proposal_sha256,
        action="correct_and_accept",
        request_fingerprint="a" * 64,
        decided_at=WHEN,
        corrected_payload=corrected_payload,
        corrected_result_sha256=corrected_result_sha256,
    )
    with engine.begin() as connection:
        connection.execute(
            goodnotes_notebooks.insert().values(
                principal_id=PRINCIPAL,
                notebook_id=notebook_id,
                source_root_id="synthetic",
                identity_status="ACTIVE",
                created_at=WHEN,
                last_observed_at=WHEN,
            )
        )
        connection.execute(
            goodnotes_ingestion_runs.insert().values(
                principal_id=PRINCIPAL,
                run_id=run_id,
                source_root_id="synthetic",
                trigger_type="SCHEDULED",
                request_id="request-1",
                idempotency_key="run-key-1",
                request_fingerprint="b" * 64,
                started_at=WHEN,
                status="SUCCEEDED",
            )
        )
        connection.execute(
            goodnotes_ingestion_run_stages.insert().values(
                principal_id=PRINCIPAL,
                run_id=run_id,
                stage="CONTENT_READY",
                status="SUCCEEDED",
                attempt=1,
                started_at=WHEN,
                ended_at=WHEN,
            )
        )
        connection.execute(
            goodnotes_logical_pages.insert().values(
                principal_id=PRINCIPAL,
                logical_page_id=logical_page_id,
                notebook_id=notebook_id,
                created_at=WHEN,
                last_seen_at=WHEN,
                identity_status="ACTIVE",
            )
        )
        connection.execute(
            goodnotes_semantic_proposals.insert().values(
                principal_id=PRINCIPAL,
                proposal_id=proposal_id,
                run_id=run_id,
                page_version_id=page_version_id,
                content_sha256="c" * 64,
                schema_version="v1",
                analyzer_name="test",
                analyzer_version="1",
                idempotency_key="proposal-key-1",
                request_fingerprint="d" * 64,
                payload_sha256=original_result_sha256,
                payload=payload,
                created_at=WHEN,
                correlation_id="corr_0123456789abcdef01234567",
                request_id="proposal-request-1",
            )
        )
        connection.execute(
            goodnotes_source_snapshots.insert().values(
                principal_id=PRINCIPAL,
                snapshot_id=snapshot_id,
                notebook_id=notebook_id,
                source_object_id="obj_0123456789abcdef01234567",
                observed_path="synthetic.pdf",
                raw_sha256="8" * 64,
                size_bytes=1,
                page_count=1,
                observed_at=WHEN,
                settled_at=WHEN,
                run_id=run_id,
            )
        )
        connection.execute(
            goodnotes_pages.insert().values(
                principal_id=PRINCIPAL,
                page_id="gnpg_0123456789abcdef01234567",
                source_id="src_0123456789abcdef01234567",
                source_object_id="obj_0123456789abcdef01234567",
                page_number=1,
            )
        )
        connection.execute(
            goodnotes_page_versions.insert().values(
                principal_id=PRINCIPAL,
                page_version_id=page_version_id,
                page_id="gnpg_0123456789abcdef01234567",
                source_version_id="ver_0123456789abcdef01234567",
                content_sha256="c" * 64,
                observed_at=WHEN,
                logical_page_id=logical_page_id,
                exact_render_sha256="9" * 64,
                renderer_name="synthetic",
                renderer_version="1",
                render_profile_version="v1",
            )
        )
        connection.execute(
            goodnotes_page_positions.insert().values(
                principal_id=PRINCIPAL,
                snapshot_id=snapshot_id,
                page_number=1,
                logical_page_id=logical_page_id,
                page_version_id=page_version_id,
                match_method="ORDINAL_WEAK",
                created_at=WHEN,
            )
        )
        connection.execute(
            goodnotes_page_rasters.insert().values(
                principal_id=PRINCIPAL,
                page_version_id=page_version_id,
                run_id=run_id,
                exact_render_sha256="9" * 64,
                png_sha256=hashlib.sha256(b"x").hexdigest(),
                media_type="image/png",
                byte_length=1,
                png_bytes=b"x",
                renderer_name="synthetic",
                renderer_version="1",
                render_profile_version="v1",
                created_at=WHEN,
            )
        )
        repository = SqlGoodNotesPullRepository(connection)
        states = repository.work_states(PRINCIPAL)
        assert len(states) == 1
        assignment = PullAssignment(
            assignment_id="3" * 64,
            client_id="scheduler-a",
            context_id=context_id,
            work=states[0].work,
            attempt=1,
        )
        assert repository.claim_batch(
            PRINCIPAL,
            "scheduler-a",
            context_id,
            (assignment,),
            (0,),
            max_attempts=3,
        ) == (assignment,)
        material = repository.completion_material(PRINCIPAL, "scheduler-a", "3" * 64)
        assert material is not None
        assert material.proposal_id == proposal_id
        assert material.result_sha256 == original_result_sha256
        assert repository.completion_material(PRINCIPAL, "scheduler-b", "3" * 64) is None
        assert repository.completion_material(PRINCIPAL, "scheduler-a", "4" * 64) is None
        review_case_id = _semantic_review_case_id(PRINCIPAL, proposal_id)
        monkeypatch.setattr(
            SqlGoodNotesPullRepository,
            "semantic_review_cases",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("named lookup must not delegate to the bounded list path")
            ),
        )
        named_case = repository.semantic_review_case(PRINCIPAL, review_case_id)
        assert named_case is not None
        assert named_case.proposal_id == proposal_id
        assert named_case.review_version == 0
        assert (
            repository.semantic_review_case("prn_fedcba9876543210fedcba98", review_case_id) is None
        )
        assert repository.record_semantic_review(decision).replayed is False
        assert repository.record_semantic_review(decision).replayed is True
        corrected_material = repository.completion_material(PRINCIPAL, "scheduler-a", "3" * 64)
        assert corrected_material is not None
        assert corrected_material.proposal_sha256 == proposal_sha256
        assert corrected_material.result_sha256 == corrected_result_sha256
        evidence = repository.semantic_review_evidence(PRINCIPAL, run_id, (proposal_sha256,))
        assert len(evidence) == 1
        assert evidence[0].disposition.value == "correct_and_accept"
        assert evidence[0].corrected_payload == corrected_payload
        assert evidence[0].result_sha256 == corrected_result_sha256
        assert evidence[0].is_bound_to(PRINCIPAL, run_id)
        assert not evidence[0].is_bound_to("prn_fedcba9876543210fedcba98", run_id)
        assert not evidence[0].is_bound_to(PRINCIPAL, "gnrun_fedcba9876543210fedcba98")
        reviewed = repository.accepted_semantic_material(PRINCIPAL, run_id)
        assert reviewed is not None
        assert reviewed[0].payload == corrected_payload
        assert (
            repository.accepted_semantic_material(PRINCIPAL, run_id, require_promoted=True) is None
        )
        stored_payload = connection.scalar(
            select(goodnotes_semantic_proposals.c.payload).where(
                goodnotes_semantic_proposals.c.principal_id == PRINCIPAL,
                goodnotes_semantic_proposals.c.proposal_id == proposal_id,
            )
        )
        assert stored_payload == payload
    service = ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(
            engine,
            audit=SqlAlchemyAuditSink(engine),
            goodnotes_pull_enabled=True,
        ),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        goodnotes_pull_enabled=True,
        goodnotes_pull_cursor_signing_key=b"k" * 32,
        goodnotes_canonical_semantic_writes_enabled=canonical_enabled,
    )
    admission = PullCompletionAdmission(
        completion=PullCompletion(
            assignment_id=assignment.assignment_id,
            run_id=run_id,
            page_version_id=page_version_id,
            content_sha256="c" * 64,
            result_sha256=corrected_result_sha256,
            idempotency_key=assignment.assignment_id,
        ),
        request_fingerprint="e" * 64,
    )
    blocker = engine.connect()
    blocker_transaction = blocker.begin()
    try:
        blocked_repository = SqlGoodNotesPullRepository(blocker)
        invalidated = blocked_repository.record_semantic_review(
            SemanticReviewDecision(
                decision_id="gnsrd_fedcba9876543210fedcba98",
                principal_id=PRINCIPAL,
                run_id=run_id,
                proposal_id=proposal_id,
                proposal_sha256=proposal_sha256,
                action="invalidate",
                request_fingerprint="f" * 64,
                decided_at=WHEN,
            )
        )
        assert invalidated.sequence == 2
        with engine.connect() as contender:
            contender_transaction = contender.begin()
            contender.execute(text("SET LOCAL lock_timeout = '250ms'"))
            with pytest.raises(DBAPIError, match="lock timeout"):
                SqlGoodNotesPullRepository(contender).complete_batch(
                    PRINCIPAL,
                    "scheduler-a",
                    context_id,
                    (admission,),
                )
            contender_transaction.rollback()
        blocker_transaction.commit()
    finally:
        if blocker_transaction.is_active:
            blocker_transaction.rollback()
        blocker.close()

    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(connection)
        with pytest.raises(PullRepositoryConflictError):
            repository.complete_batch(
                PRINCIPAL,
                "scheduler-a",
                context_id,
                (admission,),
            )
        accepted = repository.record_semantic_review(
            SemanticReviewDecision(
                decision_id="gnsrd_aaaaaaaaaaaaaaaaaaaaaaaa",
                principal_id=PRINCIPAL,
                run_id=run_id,
                proposal_id=proposal_id,
                proposal_sha256=proposal_sha256,
                action="accept",
                request_fingerprint="1" * 64,
                decided_at=WHEN,
            )
        )
        assert accepted.sequence == 3
        scheduler_a = repository.status(PRINCIPAL, "scheduler-a")
        scheduler_b = repository.status(PRINCIPAL, "scheduler-b")
        assert (
            scheduler_a.pending,
            scheduler_a.assigned,
            scheduler_a.completed,
            scheduler_a.exhausted,
        ) == (0, 1, 0, 0)
        assert (
            scheduler_b.pending,
            scheduler_b.assigned,
            scheduler_b.completed,
            scheduler_b.exhausted,
        ) == (1, 0, 0, 0)
        with pytest.raises(PullRepositoryConflictError):
            repository.complete_batch(
                PRINCIPAL,
                "scheduler-b",
                "ctx-stable-b",
                (admission,),
            )

    completed = service.invoke(
        RequestMetadata(
            request_id="req_0123456789abcdef01234567",
            principal_id=PRINCIPAL,
            capability=Capability.GOODNOTES_COMPLETE,
            purpose=Purpose.GOODNOTES_PULL,
            requested_at=WHEN,
        ),
        CompleteGoodNotesPull((assignment.assignment_id,)),
        principal=local_principal(),
        authenticated_client_id="scheduler-a",
    )
    assert completed.error is None, completed.error
    assert completed.result is not None
    assert completed.result["completions"][0]["replayed"] is False  # type: ignore[index]
    replayed = service.invoke(
        RequestMetadata(
            request_id="req_111111111111111111111111",
            principal_id=PRINCIPAL,
            capability=Capability.GOODNOTES_COMPLETE,
            purpose=Purpose.GOODNOTES_PULL,
            requested_at=WHEN,
        ),
        CompleteGoodNotesPull((assignment.assignment_id,)),
        principal=local_principal(),
        authenticated_client_id="scheduler-a",
    )
    assert replayed.error is None, replayed.error
    assert replayed.result is not None
    assert replayed.result["completions"][0]["replayed"] is True  # type: ignore[index]

    if canonical_enabled:
        with engine.begin() as connection:
            repository = SqlGoodNotesPullRepository(connection)
            assert (
                repository.accepted_semantic_material(PRINCIPAL, run_id, require_promoted=True)
                is not None
            )
            receipts = connection.execute(select(goodnotes_semantic_promotion_receipts)).all()
            assert len(receipts) == 1
            assert len(receipts[0].bindings) == 1
            assert receipts[0].bindings[0]["decision_id"] == accepted.decision_id
            assert repository.record_semantic_review(replace(accepted, sequence=None)).replayed
            with pytest.raises(SemanticReviewConflictError):
                repository.record_semantic_review(
                    SemanticReviewDecision(
                        decision_id="gnsrd_bbbbbbbbbbbbbbbbbbbbbbbb",
                        principal_id=PRINCIPAL,
                        run_id=run_id,
                        proposal_id=proposal_id,
                        proposal_sha256=proposal_sha256,
                        action="invalidate",
                        request_fingerprint="2" * 64,
                        decided_at=WHEN,
                    )
                )
        return

    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(connection)
        scheduler_a = repository.status(PRINCIPAL, "scheduler-a")
        scheduler_b = repository.status(PRINCIPAL, "scheduler-b")
        assert (
            scheduler_a.pending,
            scheduler_a.assigned,
            scheduler_a.completed,
            scheduler_a.exhausted,
        ) == (0, 0, 1, 0)
        assert (
            scheduler_b.pending,
            scheduler_b.assigned,
            scheduler_b.completed,
            scheduler_b.exhausted,
        ) == (1, 0, 0, 0)
        with pytest.raises(SemanticReviewConflictError):
            repository.record_semantic_review(
                SemanticReviewDecision(
                    decision_id=decision.decision_id,
                    principal_id=PRINCIPAL,
                    run_id=run_id,
                    proposal_id=proposal_id,
                    proposal_sha256=proposal_sha256,
                    action="reject",
                    request_fingerprint=decision.request_fingerprint,
                    decided_at=WHEN,
                )
            )
        invalidated = repository.record_semantic_review(
            SemanticReviewDecision(
                decision_id="gnsrd_bbbbbbbbbbbbbbbbbbbbbbbb",
                principal_id=PRINCIPAL,
                run_id=run_id,
                proposal_id=proposal_id,
                proposal_sha256=proposal_sha256,
                action="invalidate",
                request_fingerprint="2" * 64,
                decided_at=WHEN,
            )
        )
        assert invalidated.sequence == 4
        latest = repository.semantic_review_evidence(PRINCIPAL, run_id, (proposal_sha256,))
        assert latest[0].disposition.value == "invalidate"

    refused = service.invoke(
        RequestMetadata(
            request_id="req_fedcba9876543210fedcba98",
            principal_id=PRINCIPAL,
            capability=Capability.GOODNOTES_COMPLETE,
            purpose=Purpose.GOODNOTES_PULL,
            requested_at=WHEN,
        ),
        CompleteGoodNotesPull((assignment.assignment_id,)),
        principal=local_principal(),
        authenticated_client_id="scheduler-a",
    )
    assert refused.error is not None
    assert refused.error.code.value == "conflict"

    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(connection)
        concurrent_proposal_id = "gnprp_fedcba9876543210fedcba98"
        connection.execute(
            goodnotes_semantic_proposals.insert().values(
                principal_id=PRINCIPAL,
                proposal_id=concurrent_proposal_id,
                run_id=run_id,
                page_version_id=page_version_id,
                content_sha256="c" * 64,
                schema_version="v1",
                analyzer_name="test",
                analyzer_version="2",
                idempotency_key="proposal-key-2",
                request_fingerprint="6" * 64,
                payload_sha256="7" * 64,
                payload={"notes": ["ambiguous"]},
                created_at=WHEN,
                correlation_id="corr_fedcba9876543210fedcba98",
                request_id="proposal-request-2",
            )
        )
        with pytest.raises(PullRepositoryConflictError):
            repository.completion_material(PRINCIPAL, "scheduler-a", assignment.assignment_id)

    concurrent_case_id = _semantic_review_case_id(PRINCIPAL, concurrent_proposal_id)
    requests = (
        ReviewDecisionRequest(
            review_case_id=concurrent_case_id,
            expected_review_version=0,
            disposition=Disposition.ACCEPT,
            principal_id=PRINCIPAL,
            correlation_id="corr_goodnotesracea",
            audit_id="audit_goodnotesracea",
            policy_version="policy-v1",
            decided_at=WHEN,
        ),
        ReviewDecisionRequest(
            review_case_id=concurrent_case_id,
            expected_review_version=0,
            disposition=Disposition.REJECT,
            principal_id=PRINCIPAL,
            correlation_id="corr_goodnotesraceb",
            audit_id="audit_goodnotesraceb",
            policy_version="policy-v1",
            decided_at=WHEN,
            reason="synthetic stale contender",
        ),
    )
    original_named_lookup = SqlGoodNotesPullRepository.semantic_review_case
    both_observed_version_zero = Barrier(2)

    def synchronized_named_lookup(
        repository: SqlGoodNotesPullRepository,
        principal_id: str,
        review_case_id: str,
    ) -> GoodNotesSemanticReviewCase:
        case = original_named_lookup(repository, principal_id, review_case_id)
        assert case is not None
        assert case.review_version == 0
        both_observed_version_zero.wait(timeout=5)
        return case

    monkeypatch.setattr(
        SqlGoodNotesPullRepository,
        "semantic_review_case",
        synchronized_named_lookup,
    )

    def decide(request: ReviewDecisionRequest) -> ReviewDecision:
        with engine.begin() as connection:
            return SqlGoodNotesPullRepository(connection).decide_semantic_review(request)

    outcomes: list[ReviewDecision] = []
    failures: list[Exception] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(decide, request) for request in requests)
        for future in futures:
            try:
                outcomes.append(future.result(timeout=10))
            except Exception as error:
                failures.append(error)

    assert len(outcomes) == 1
    assert outcomes[0].sequence == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ReviewConflictError)
    monkeypatch.setattr(
        SqlGoodNotesPullRepository,
        "semantic_review_case",
        original_named_lookup,
    )
    winner = requests[0] if outcomes[0].disposition is Disposition.ACCEPT else requests[1]
    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(connection)
        replayed = repository.decide_semantic_review(winner)
        assert replayed.sequence == 1
        assert (
            connection.scalar(
                select(func.count())
                .select_from(goodnotes_semantic_review_decisions)
                .where(
                    goodnotes_semantic_review_decisions.c.principal_id == PRINCIPAL,
                    goodnotes_semantic_review_decisions.c.proposal_id == concurrent_proposal_id,
                )
            )
            == 1
        )
