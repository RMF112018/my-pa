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
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.application.goodnotes_occurrences import semantic_proposal_sha256
from my_pa.application.goodnotes_pull_orchestration import (
    PullRepositoryConflictError,
    SemanticReviewConflictError,
    SemanticReviewDecision,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.goodnotes_pull import SqlGoodNotesPullRepository
from my_pa.infrastructure.persistence.tables import (
    goodnotes_ingestion_runs,
    goodnotes_semantic_proposals,
)

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
DATABASE: Final = "my_pa_goodnotes_pull_repository_test"
PRINCIPAL: Final = "prn_0123456789abcdef01234567"
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
    payload = {"notes": []}
    proposal_sha256 = semantic_proposal_sha256(
        "gnver_0123456789abcdef01234567", "v1", "test", "1", payload
    )
    decision = SemanticReviewDecision(
        decision_id="gnsrd_0123456789abcdef01234567",
        principal_id=PRINCIPAL,
        run_id=run_id,
        proposal_id=proposal_id,
        proposal_sha256=proposal_sha256,
        action="accept",
        request_fingerprint="a" * 64,
        decided_at=WHEN,
    )
    with isolated_engine.begin() as connection:
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
            goodnotes_semantic_proposals.insert().values(
                principal_id=PRINCIPAL,
                proposal_id=proposal_id,
                run_id=run_id,
                page_version_id="gnver_0123456789abcdef01234567",
                content_sha256="c" * 64,
                schema_version="v1",
                analyzer_name="test",
                analyzer_version="1",
                idempotency_key="proposal-key-1",
                request_fingerprint="d" * 64,
                payload_sha256="e" * 64,
                payload=payload,
                created_at=WHEN,
                correlation_id="cor_0123456789abcdef01234567",
                request_id="proposal-request-1",
            )
        )
        repository = SqlGoodNotesPullRepository(connection)
        assert repository.record_semantic_review(decision).replayed is False
        assert repository.record_semantic_review(decision).replayed is True
        evidence = repository.semantic_review_evidence(PRINCIPAL, run_id, (proposal_sha256,))
        assert len(evidence) == 1
        assert evidence[0].disposition.value == "accept"
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
