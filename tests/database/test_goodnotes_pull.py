"""Isolated PostgreSQL checks for the durable GoodNotes pull ledger."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.engine import make_url

from my_pa.application.goodnotes_occurrences import _reviewed_proposals, semantic_proposal_sha256
from my_pa.application.goodnotes_pull_orchestration import (
    PullAssignment,
    PullCompletion,
    PullCompletionAdmission,
    PullRepositoryConflictError,
    SemanticReviewConflictError,
    SemanticReviewDecision,
)
from my_pa.bootstrap.gateway import local_principal
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.goodnotes_pull import (
    SqlGoodNotesPullRepository,
    _corrected_result_sha256,
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
    goodnotes_semantic_proposals,
    goodnotes_source_snapshots,
)

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
DATABASE: Final = "my_pa_goodnotes_pull_repository_test"
PRINCIPAL: Final = local_principal().principal_id
WHEN: Final = datetime(2026, 9, 4, 5, 0, tzinfo=UTC)


def _administer(engine: Engine, statement: object) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture
def isolated_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    raw = os.environ.get("MY_PA_DATABASE_URL")
    if raw is None:
        pytest.skip("MY_PA_DATABASE_URL is not configured for an isolated database test")
    configured = make_url(raw)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)')
    _administer(maintenance, drop)
    _administer(maintenance, text(f'CREATE DATABASE "{DATABASE}"'))
    url = configured.set(database=DATABASE).render_as_string(hide_password=False)
    monkeypatch.setenv("MY_PA_DATABASE_URL", url)
    engine = create_database_engine(url)
    try:
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        yield engine
    finally:
        engine.dispose()
        _administer(maintenance, drop)
        maintenance.dispose()


def test_empty_claim_replays_after_restart_and_status_is_content_free(
    isolated_engine: Engine,
) -> None:
    with isolated_engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(connection)
        assert (
            repository.claim_batch(PRINCIPAL, "scheduler-a", "ctx-stable-a", (), (), max_attempts=3)
            == ()
        )
    with isolated_engine.begin() as connection:
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


def test_session_identity_and_retry_policy_fail_closed(isolated_engine: Engine) -> None:
    with isolated_engine.begin() as connection:
        repository = SqlGoodNotesPullRepository(connection)
        repository.claim_batch(PRINCIPAL, "scheduler-a", "ctx-stable-a", (), (), max_attempts=3)
        with pytest.raises(PullRepositoryConflictError):
            repository.claim_batch(PRINCIPAL, "scheduler-a", "ctx-other", (), (), max_attempts=3)
        with pytest.raises(PullRepositoryConflictError):
            repository.claim_batch(PRINCIPAL, "scheduler-a", "ctx-stable-a", (), (), max_attempts=4)


def test_semantic_review_exact_replay_conflict_and_projection(isolated_engine: Engine) -> None:
    run_id = "gnrun_0123456789abcdef01234567"
    proposal_id = "gnprp_0123456789abcdef01234567"
    notebook_id = "gnnb_0123456789abcdef01234567"
    logical_page_id = "gnlp_0123456789abcdef01234567"
    snapshot_id = "gnsnap_0123456789abcdef01234567"
    page_version_id = "gnver_0123456789abcdef01234567"
    payload: dict[str, object] = {
        "segments": [],
        "candidate_tags": [],
        "ranked_candidates": [],
        "confidence": None,
    }
    corrected_payload = {**payload, "confidence": 0.75}
    original_result_sha256 = _corrected_result_sha256(payload)
    corrected_result_sha256 = _corrected_result_sha256(corrected_payload)
    proposal_sha256 = semantic_proposal_sha256(page_version_id, "v1", "test", "1", payload)
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
    with isolated_engine.begin() as connection:
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
                png_sha256="7" * 64,
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
            context_id="ctx-stable-a",
            work=states[0].work,
            attempt=1,
        )
        assert repository.claim_batch(
            PRINCIPAL,
            "scheduler-a",
            "ctx-stable-a",
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
        reviewed = _reviewed_proposals(
            PRINCIPAL,
            run_id,
            ((page_version_id, "v1", "test", "1", payload),),
            evidence,
        )
        assert reviewed[0][4] == corrected_payload
        stored_payload = connection.scalar(
            select(goodnotes_semantic_proposals.c.payload).where(
                goodnotes_semantic_proposals.c.principal_id == PRINCIPAL,
                goodnotes_semantic_proposals.c.proposal_id == proposal_id,
            )
        )
        assert stored_payload == payload
        receipts = repository.complete_batch(
            PRINCIPAL,
            "scheduler-a",
            "ctx-stable-a",
            (
                PullCompletionAdmission(
                    completion=PullCompletion(
                        assignment_id=assignment.assignment_id,
                        run_id=run_id,
                        page_version_id=page_version_id,
                        content_sha256="c" * 64,
                        result_sha256=corrected_result_sha256,
                        idempotency_key=assignment.assignment_id,
                    ),
                    request_fingerprint="6" * 64,
                ),
            ),
        )
        assert receipts[0].result_sha256 == corrected_result_sha256
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
        latest = repository.semantic_review_evidence(PRINCIPAL, run_id, (proposal_sha256,))
        assert latest[0].disposition.value == "invalidate"
        connection.execute(
            goodnotes_semantic_proposals.insert().values(
                principal_id=PRINCIPAL,
                proposal_id="gnprp_fedcba9876543210fedcba98",
                run_id=run_id,
                page_version_id="gnver_0123456789abcdef01234567",
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
            repository.completion_material(PRINCIPAL, "scheduler-a", "3" * 64)
