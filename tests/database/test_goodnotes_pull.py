"""Isolated PostgreSQL checks for the durable GoodNotes pull ledger."""

from __future__ import annotations

import hashlib
import hmac
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Final

import pytest
from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.exc import DBAPIError

from my_pa.application.commands import CompleteGoodNotesPull
from my_pa.application.goodnotes_occurrences import semantic_proposal_sha256
from my_pa.application.goodnotes_pull_orchestration import (
    GoodNotesPullOrchestrator,
    PullAssignment,
    PullCompletion,
    PullCompletionAdmission,
    PullRepositoryConflictError,
    PullRequest,
    SemanticReviewConflictError,
    SemanticReviewDecision,
    _assignment_id,
    stamp_authenticated_pull_context,
)
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.gateway import local_principal
from my_pa.contracts.ports import GoodNotesPullWorkStateRecord, ReviewDecisionRequest
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
            repository.claim_batch(
                PRINCIPAL, "scheduler-a", "ctx-stable-a", (), (), max_attempts=3, lease_seconds=900
            )
            == ()
        )
    with engine.begin() as connection:
        restarted = SqlGoodNotesPullRepository(connection)
        assert (
            restarted.claim_batch(
                PRINCIPAL, "scheduler-a", "ctx-stable-a", (), (), max_attempts=3, lease_seconds=900
            )
            == ()
        )
        status = restarted.status(
            PRINCIPAL, "scheduler-a", context_id="ctx-stable-a", max_attempts=3, lease_seconds=900
        )
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
        repository.claim_batch(
            PRINCIPAL, "scheduler-a", "ctx-stable-a", (), (), max_attempts=3, lease_seconds=900
        )
        with pytest.raises(PullRepositoryConflictError):
            repository.claim_batch(
                PRINCIPAL, "scheduler-a", "ctx-other", (), (), max_attempts=3, lease_seconds=900
            )
        with pytest.raises(PullRepositoryConflictError):
            repository.claim_batch(
                PRINCIPAL, "scheduler-a", "ctx-stable-a", (), (), max_attempts=4, lease_seconds=900
            )


@pytest.mark.parametrize("canonical_enabled", [False, True])
@pytest.mark.parametrize("with_dates", [False, True])
def test_semantic_review_exact_replay_conflict_projection_and_client_status_isolation(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, canonical_enabled: bool, with_dates: bool
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
    if with_dates:
        date = {
            "scope": "PAGE",
            "value": "2026-09-05",
            "literal": "September 5",
            "evidence_refs": ["synthetic-heading"],
        }
        payload["date_evidence"] = {"page_candidates": [date]}
        corrected_payload["date_evidence"] = {
            "page_candidates": [{**date, "value": "2026-09-06", "literal": "September 6"}]
        }
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
        states = repository.work_states(PRINCIPAL, "scheduler-a")
        assert len(states) == 1
        assignment = PullAssignment(
            assignment_id=_assignment_id(
                stamp_authenticated_pull_context(
                    principal=local_principal(), client_id="scheduler-a", context_id=context_id
                ),
                states[0].work,
                1,
            ),
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
            max_attempts=10,
            lease_seconds=900,
        ) == (assignment,)
        material = repository.completion_material(
            PRINCIPAL, "scheduler-a", assignment.assignment_id
        )
        assert material is not None
        assert material.proposal_id == proposal_id
        assert material.result_sha256 == original_result_sha256
        assert (
            repository.completion_material(PRINCIPAL, "scheduler-b", assignment.assignment_id)
            is None
        )
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
        if with_dates:
            with pytest.raises(SemanticReviewConflictError):
                repository.record_semantic_review(
                    replace(decision, corrected_result_sha256=original_result_sha256)
                )
        assert repository.record_semantic_review(decision).replayed is False
        assert repository.record_semantic_review(decision).replayed is True
        corrected_material = repository.completion_material(
            PRINCIPAL, "scheduler-a", assignment.assignment_id
        )
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
        scheduler_a = repository.status(
            PRINCIPAL, "scheduler-a", context_id=context_id, max_attempts=10, lease_seconds=900
        )
        scheduler_b = repository.status(
            PRINCIPAL, "scheduler-b", context_id="ctx-stable-b", max_attempts=10, lease_seconds=900
        )
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
        scheduler_a = repository.status(
            PRINCIPAL, "scheduler-a", context_id=context_id, max_attempts=10, lease_seconds=900
        )
        scheduler_b = repository.status(
            PRINCIPAL, "scheduler-b", context_id="ctx-stable-b", max_attempts=10, lease_seconds=900
        )
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


def _seed_resume_work(connection: Connection, suffix: str = "0123456789abcdef01234567") -> None:
    run_id = f"gnrun_{suffix}"
    proposal_id = f"gnprp_{suffix}"
    notebook_id = f"gnnb_{suffix}"
    logical_page_id = f"gnlp_{suffix}"
    snapshot_id = f"gnsnap_{suffix}"
    page_version_id = f"gnver_{suffix}"
    payload = {"segments": [], "candidate_tags": [], "ranked_candidates": [], "confidence": None}
    original_result_sha256 = _corrected_result_sha256(payload)
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
            request_id=f"request-{suffix}",
            idempotency_key=f"run-{suffix}",
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
            idempotency_key=f"proposal-{suffix}",
            request_fingerprint="d" * 64,
            payload_sha256=original_result_sha256,
            payload=payload,
            created_at=WHEN,
            correlation_id=f"corr_{suffix}",
            request_id=f"proposal-request-{suffix}",
        )
    )
    connection.execute(
        goodnotes_source_snapshots.insert().values(
            principal_id=PRINCIPAL,
            snapshot_id=snapshot_id,
            notebook_id=notebook_id,
            source_object_id=f"obj_{suffix}",
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
            page_id=f"gnpg_{suffix}",
            source_id=f"src_{suffix}",
            source_object_id=f"obj_{suffix}",
            page_number=1,
        )
    )
    connection.execute(
        goodnotes_page_versions.insert().values(
            principal_id=PRINCIPAL,
            page_version_id=page_version_id,
            page_id=f"gnpg_{suffix}",
            source_version_id=f"ver_{suffix}",
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
    SqlGoodNotesPullRepository(connection).record_semantic_review(
        SemanticReviewDecision(
            decision_id=f"gnsrd_{suffix}",
            principal_id=PRINCIPAL,
            run_id=run_id,
            proposal_id=proposal_id,
            proposal_sha256=semantic_proposal_sha256(page_version_id, "v1", "test", "1", payload),
            action="accept",
            request_fingerprint=hashlib.sha256(suffix.encode()).hexdigest(),
            decided_at=WHEN,
        )
    )


def _resume_assignment(
    repository: SqlGoodNotesPullRepository, client: str, attempt: int = 1
) -> PullAssignment:
    state = repository.work_states(PRINCIPAL, client)[0]
    return PullAssignment(
        assignment_id=_assignment_id(
            stamp_authenticated_pull_context(
                principal=local_principal(), client_id=client, context_id=f"ctx-{client}"
            ),
            state.work,
            attempt,
        ),
        client_id=client,
        context_id=f"ctx-{client}",
        work=state.work,
        attempt=attempt,
    )


def _claim(
    repository: SqlGoodNotesPullRepository, client: str, attempt: int = 1, maximum: int = 3
) -> PullAssignment:
    assignment = _resume_assignment(repository, client, attempt)
    result = repository.claim_batch(
        PRINCIPAL,
        client,
        f"ctx-{client}",
        (assignment,),
        (attempt - 1,),
        max_attempts=maximum,
        lease_seconds=900,
    )
    assert len(result) == 1 and asdict(result[0]) == asdict(assignment)
    return assignment


def _admission(
    repository: SqlGoodNotesPullRepository, assignment: PullAssignment
) -> PullCompletionAdmission:
    material = repository.completion_material(
        PRINCIPAL, assignment.client_id, assignment.assignment_id
    )
    assert material is not None
    return PullCompletionAdmission(
        completion=PullCompletion(
            assignment_id=assignment.assignment_id,
            run_id=assignment.work.run_id,
            page_version_id=assignment.work.page_version_id,
            content_sha256=assignment.work.content_sha256,
            result_sha256=material.result_sha256,
            idempotency_key="same-key",
        ),
        request_fingerprint=hashlib.sha256(assignment.assignment_id.encode()).hexdigest(),
    )


def test_clients_have_independent_attempts_completion_keys_and_restart_state(
    engine: Engine,
) -> None:
    with engine.begin() as connection:
        _seed_resume_work(connection)
        repository = SqlGoodNotesPullRepository(connection, clock=lambda: WHEN)
        first, second = _claim(repository, "a"), _claim(repository, "b")
        for assignment in (first, second):
            admission = _admission(repository, assignment)
            receipt = repository.complete_batch(
                PRINCIPAL, assignment.client_id, assignment.context_id, (admission,)
            )
            replay = repository.complete_batch(
                PRINCIPAL, assignment.client_id, assignment.context_id, (admission,)
            )
            assert receipt[0].completion_id == replay[0].completion_id
            assert replay[0].replayed
    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(connection, clock=lambda: WHEN)
        for assignment in (first, second):
            state = repository.work_states(PRINCIPAL, assignment.client_id)[0]
            assert state.attempts == 1 and state.completed
            assert state.latest_assignment is not None
            assert (
                asdict(state.latest_assignment) == asdict(assignment) and state.assigned_at == WHEN
            )
        assert repository.work_states(PRINCIPAL, "c")[0].attempts == 0


def test_claim_lease_and_final_attempt_status_survive_restart(engine: Engine) -> None:
    with engine.begin() as connection:
        _seed_resume_work(connection)
        repository = SqlGoodNotesPullRepository(connection, clock=lambda: WHEN)
        first = _claim(repository, "a", maximum=2)
    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(
            connection, clock=lambda: WHEN + timedelta(seconds=899)
        )
        latest = repository.work_states(PRINCIPAL, "a")[0].latest_assignment
        assert latest is not None and asdict(latest) == asdict(first)
        with pytest.raises(PullRepositoryConflictError):
            _claim(repository, "a", 2, 2)
    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(
            connection, clock=lambda: WHEN + timedelta(seconds=900)
        )
        state = repository.status(
            PRINCIPAL, "a", context_id="ctx-a", max_attempts=2, lease_seconds=900
        )
        assert state.pending == 1 and state.assigned == 0
        second = _claim(repository, "a", 2, 2)
        assert asdict(_claim(repository, "a", 2, 2)) == asdict(second)
        state = repository.status(
            PRINCIPAL, "a", context_id="ctx-a", max_attempts=2, lease_seconds=900
        )
        assert state.assigned == 1 and state.exhausted == 0
    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(
            connection, clock=lambda: WHEN + timedelta(seconds=1800)
        )
        state = repository.status(
            PRINCIPAL, "a", context_id="ctx-a", max_attempts=2, lease_seconds=900
        )
        assert state.exhausted == 1 and state.assigned == 0
        repository.complete_batch(PRINCIPAL, "a", "ctx-a", (_admission(repository, second),))
        assert repository.work_states(PRINCIPAL, "a")[0].completed


@pytest.mark.parametrize("completion_first", [True, False])
def test_expired_completion_and_successor_serialize_in_both_orders(
    engine: Engine, completion_first: bool
) -> None:
    with engine.begin() as connection:
        _seed_resume_work(connection)
        repository = SqlGoodNotesPullRepository(connection, clock=lambda: WHEN)
        original = _claim(repository, "a")
        admission = _admission(repository, original)
    with engine.connect() as winner, engine.connect() as loser:
        winning_transaction = winner.begin()
        losing_transaction = loser.begin()
        first = SqlGoodNotesPullRepository(winner, clock=lambda: WHEN + timedelta(seconds=900))
        second = SqlGoodNotesPullRepository(loser, clock=lambda: WHEN + timedelta(seconds=900))
        if completion_first:
            first.complete_batch(PRINCIPAL, "a", "ctx-a", (admission,))
        else:
            _claim(first, "a", 2)
        loser.execute(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(DBAPIError, match="lock timeout"):
            if completion_first:
                _claim(second, "a", 2)
            else:
                second.complete_batch(PRINCIPAL, "a", "ctx-a", (admission,))
        losing_transaction.rollback()
        winning_transaction.commit()
    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(
            connection, clock=lambda: WHEN + timedelta(seconds=900)
        )
        with pytest.raises(PullRepositoryConflictError):
            if completion_first:
                _claim(repository, "a", 2)
            else:
                repository.complete_batch(PRINCIPAL, "a", "ctx-a", (admission,))
        state = repository.work_states(PRINCIPAL, "a")[0]
        assert state.attempts == (1 if completion_first else 2)
        assert state.completed is completion_first


def _discover(repository: SqlGoodNotesPullRepository, client: str) -> PullAssignment:
    context = stamp_authenticated_pull_context(
        principal=local_principal(), client_id=client, context_id=f"ctx-{client}"
    )
    orchestrator = GoodNotesPullOrchestrator(
        repository=repository, max_batch_size=1, max_attempts=3, cursor_signing_key=b"k" * 32
    )
    return orchestrator.discover(context, PullRequest(batch_size=1)).assignments[0]


def test_simultaneous_discovery_converges_and_restart_resumes(engine: Engine) -> None:
    with engine.begin() as connection:
        _seed_resume_work(connection)
    ready = Barrier(2)

    def discover() -> PullAssignment:
        with engine.begin() as connection:
            repository = SqlGoodNotesPullRepository(connection, clock=lambda: WHEN)
            ready.wait(timeout=5)
            return _discover(repository, "a")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(discover) for _ in range(2)]
        assignments = [future.result(timeout=10) for future in futures]
    assert assignments[0].assignment_id == assignments[1].assignment_id
    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(
            connection, clock=lambda: WHEN + timedelta(seconds=899)
        )
        resumed = _discover(repository, "a")
        assert resumed.assignment_id == assignments[0].assignment_id and resumed.attempt == 1
        assert (
            connection.scalar(text("SELECT count(*) FROM knowledge.goodnotes_pull_assignments"))
            == 1
        )
    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(
            connection, clock=lambda: WHEN + timedelta(seconds=900)
        )
        successor = _discover(repository, "a")
        assert successor.assignment_id != resumed.assignment_id and successor.attempt == 2
    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(
            connection, clock=lambda: WHEN + timedelta(seconds=900)
        )
        assert _discover(repository, "a").assignment_id == successor.assignment_id
        assert (
            connection.scalar(text("SELECT count(*) FROM knowledge.goodnotes_pull_assignments"))
            == 2
        )


def test_session_lease_validation_and_status_do_not_create_session(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(connection, clock=lambda: WHEN)
        repository.status(PRINCIPAL, "a", context_id="ctx-a", max_attempts=3, lease_seconds=900)
        assert (
            connection.scalar(text("SELECT count(*) FROM knowledge.goodnotes_pull_sessions")) == 0
        )
        for lease in (True, 59, 86401):
            with pytest.raises(PullRepositoryConflictError):
                repository.lock_session(
                    PRINCIPAL, "a", "ctx-a", max_attempts=3, lease_seconds=lease
                )
        assert (
            repository.lock_session(PRINCIPAL, "a", "ctx-a", max_attempts=3, lease_seconds=900)
            == WHEN
        )
        with pytest.raises(PullRepositoryConflictError):
            repository.lock_session(PRINCIPAL, "b", "ctx-a", max_attempts=3, lease_seconds=900)
        assert (
            connection.scalar(text("SELECT count(*) FROM knowledge.goodnotes_pull_sessions")) == 1
        )
        for context, lease in (("ctx-other", 900), ("ctx-a", 901)):
            with pytest.raises(PullRepositoryConflictError):
                repository.status(
                    PRINCIPAL, "a", context_id=context, max_attempts=3, lease_seconds=lease
                )
            with pytest.raises(PullRepositoryConflictError):
                repository.lock_session(
                    PRINCIPAL, "a", context, max_attempts=3, lease_seconds=lease
                )


@pytest.mark.parametrize("create_before_read", [True, False])
@pytest.mark.parametrize(
    ("context", "maximum", "lease"),
    [("ctx-a", 1, 60), ("ctx-wrong", 1, 900), ("ctx-a", 2, 900), ("ctx-a", 1, 900)],
)
def test_status_revalidates_a_session_created_during_absent_session_read(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    create_before_read: bool,
    context: str,
    maximum: int,
    lease: int,
) -> None:
    with engine.begin() as connection:
        _seed_resume_work(connection)
    original = SqlGoodNotesPullRepository._work_states
    events: list[str] = []
    with engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(
            connection,
            clock=lambda: events.append("clock") or WHEN + timedelta(seconds=120),
        )

        def create_session() -> None:
            with engine.begin() as creator:
                _claim(SqlGoodNotesPullRepository(creator, clock=lambda: WHEN), "a", maximum=1)

        def interleaved_read(
            self: SqlGoodNotesPullRepository, principal_id: str, *, client_id: str
        ) -> tuple[GoodNotesPullWorkStateRecord, ...]:
            if self is not repository:
                return original(self, principal_id, client_id=client_id)
            events.append("read")
            if events.count("read") == 1:
                if create_before_read:
                    create_session()
                result = original(self, principal_id, client_id=client_id)
                if not create_before_read:
                    create_session()
                return result
            # A matching newly visible session must be locked before its state is reread.
            with engine.connect() as contender:
                transaction = contender.begin()
                contender.execute(text("SET LOCAL lock_timeout = '200ms'"))
                with pytest.raises(DBAPIError, match="lock timeout"):
                    SqlGoodNotesPullRepository(contender, clock=lambda: WHEN).lock_session(
                        PRINCIPAL, "a", "ctx-a", max_attempts=1, lease_seconds=900
                    )
                transaction.rollback()
            return original(self, principal_id, client_id=client_id)

        monkeypatch.setattr(SqlGoodNotesPullRepository, "_work_states", interleaved_read)
        if (context, maximum, lease) != ("ctx-a", 1, 900):
            with pytest.raises(PullRepositoryConflictError):
                repository.status(
                    PRINCIPAL, "a", context_id=context, max_attempts=maximum, lease_seconds=lease
                )
        else:
            status = repository.status(
                PRINCIPAL, "a", context_id=context, max_attempts=maximum, lease_seconds=lease
            )
            assert (status.pending, status.assigned, status.completed, status.exhausted) == (
                0,
                1,
                0,
                0,
            )
            assert events == ["read", "read", "clock"]
        assert (
            connection.scalar(text("SELECT count(*) FROM knowledge.goodnotes_pull_sessions")) == 1
        )
