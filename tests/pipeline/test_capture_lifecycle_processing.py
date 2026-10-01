"""CRL-WP-03 CP-CRL-04: capture processing stops without becoming a failure.

Archive withdraws queued and running work. Then-current ineligibility pauses
the attempt, refunds it, and leaves no error code. Restore reuses the same
job. Worker health does not count a paused row as backlog.

Synthetic fixtures only. The worker is the production `run_worker`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.engine import Connection
from tests.pipeline.conftest import PRINCIPAL_ID, RICH_NOTE, drain, save

from my_pa.application.authorization import Authorization
from my_pa.application.capture_lifecycle import always_eligible, transition_capture
from my_pa.contracts.ports import AuditSink
from my_pa.domain.capture.lifecycle import (
    CaptureLifecycleOperation,
    CaptureProcessingEligibility,
    CaptureProcessingSubject,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import POLICY_VERSION, PolicyDecision
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.jobs.capture_pipeline import configure_processing_eligibility
from my_pa.infrastructure.persistence.jobs import CAPTURE_JOBS, claim_job, reap_abandoned_jobs
from my_pa.infrastructure.persistence.tables import JobState, capture_jobs, capture_stage_results
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from my_pa.infrastructure.persistence.worker_health import (
    record_worker_heartbeat,
    worker_plane_health,
)

pytestmark = [pytest.mark.database, pytest.mark.recovery]

NOW = datetime(2026, 10, 1, 16, 0, tzinfo=UTC)
REASON = "Synthetic withdrawal for processing"


class _Audit(AuditSink):
    def record(self, event: object) -> None:  # type: ignore[override]
        del event


@pytest.fixture(autouse=True)
def _restore_eligibility() -> Iterator[None]:
    yield
    configure_processing_eligibility(always_eligible)


def _job(connection: Connection, operation_id: str) -> dict[str, object]:
    row = connection.execute(
        text(
            "SELECT state, attempt_count, max_attempts, pause_cause, last_error_code, "
            "dead_lettered_at, lease_generation, next_attempt_at "
            "FROM knowledge.capture_jobs WHERE operation_id = :operation_id"
        ),
        {"operation_id": operation_id},
    ).one()
    return dict(row._mapping)


def _transition(
    engine: Engine,
    capture_id: str,
    operation: CaptureLifecycleOperation,
    *,
    expected: int,
    key: str,
    eligibility: Callable[
        [CaptureProcessingSubject], CaptureProcessingEligibility
    ] = always_eligible,
) -> None:
    principal = Principal(PRINCIPAL_ID, PrincipalKind.OPERATOR, authenticated=True)
    authorization = Authorization(
        principal=principal,
        capability=Capability.CAPTURE_REVISE,
        purpose=Purpose.CAPTURE_AUTHORING,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        request_id=f"req-{key}",
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
            operation=operation,
            capture_id=capture_id,
            expected_lifecycle_revision=expected,
            reason=REASON,
            idempotency_key=key,
            now=NOW,
            eligibility=eligibility,
        )


def _refuse(_subject: CaptureProcessingSubject) -> CaptureProcessingEligibility:
    return CaptureProcessingEligibility.INELIGIBLE


def test_archive_while_queued_is_not_claimable_and_not_a_failure(engine: Engine) -> None:
    with engine.begin() as connection:
        saved = save(connection, "Synthetic queued withdrawal.")
    _transition(
        engine, saved.capture_id, CaptureLifecycleOperation.ARCHIVE, expected=0, key="q-arch"
    )
    run = drain(engine, jobs=2)
    assert (run.claimed, run.paused, run.released, run.lost, run.completed) == (0, 0, 0, 0, 0)
    with engine.connect() as connection:
        job = _job(connection, saved.operation_id)
    assert job["state"] == JobState.QUEUED.value
    assert job["pause_cause"] == "capture_withdrawn"
    assert job["last_error_code"] is None
    assert job["dead_lettered_at"] is None


def test_archive_while_running_refunds_the_attempt_and_records_no_failure(engine: Engine) -> None:
    with engine.begin() as connection:
        saved = save(connection, "Synthetic running withdrawal.")
        claimed = claim_job(
            connection,
            owner="worker-lifecycle04",
            lease_seconds=60,
            principal_id=PRINCIPAL_ID,
            plane=CAPTURE_JOBS,
        )
    assert claimed is not None
    _transition(
        engine, saved.capture_id, CaptureLifecycleOperation.ARCHIVE, expected=0, key="r-arch"
    )
    with engine.connect() as connection:
        job = _job(connection, saved.operation_id)
        stages = connection.scalar(
            select(func.count())
            .select_from(capture_stage_results)
            .where(capture_stage_results.c.version_id == saved.version_id)
        )
    assert job["state"] == JobState.QUEUED.value
    assert job["attempt_count"] == 0
    assert job["pause_cause"] == "capture_withdrawn"
    assert job["last_error_code"] is None
    assert job["dead_lettered_at"] is None
    assert stages == 0


def test_a_final_attempt_running_job_is_suspended_not_reaped(engine: Engine) -> None:
    with engine.begin() as connection:
        saved = save(connection, "Synthetic final-attempt withdrawal.")
        connection.execute(
            text(
                "UPDATE knowledge.capture_jobs SET state = 'running', "
                "attempt_count = max_attempts, lease_owner = 'worker-lifecycle04', "
                "lease_expires_at = now() - interval '1 second', lease_generation = 1 "
                "WHERE operation_id = :operation_id"
            ),
            {"operation_id": saved.operation_id},
        )
    _transition(
        engine, saved.capture_id, CaptureLifecycleOperation.ARCHIVE, expected=0, key="f-arch"
    )
    with engine.begin() as connection:
        reaped = reap_abandoned_jobs(connection, principal_id=PRINCIPAL_ID, plane=CAPTURE_JOBS)
        withdrawn = _job(connection, saved.operation_id)
    assert reaped == 0
    assert withdrawn["state"] == JobState.QUEUED.value
    assert int(withdrawn["attempt_count"]) == int(withdrawn["max_attempts"]) - 1  # type: ignore[arg-type]
    assert withdrawn["pause_cause"] == "capture_withdrawn"
    assert withdrawn["last_error_code"] is None
    _transition(
        engine, saved.capture_id, CaptureLifecycleOperation.RESTORE, expected=1, key="f-rest"
    )
    with engine.begin() as connection:
        resumed = claim_job(
            connection,
            owner="worker-lifecycle04",
            lease_seconds=30,
            principal_id=PRINCIPAL_ID,
            plane=CAPTURE_JOBS,
            respect_retry_schedule=True,
        )
    assert resumed is not None
    assert resumed.operation_id == saved.operation_id


def test_then_current_ineligibility_pauses_without_an_error(engine: Engine) -> None:
    configure_processing_eligibility(_refuse)
    with engine.begin() as connection:
        saved = save(connection, "Synthetic policy pause.")
    run = drain(engine, jobs=1)
    assert (run.claimed, run.paused, run.released, run.completed, run.lost) == (1, 1, 0, 0, 0)
    with engine.connect() as connection:
        job = _job(connection, saved.operation_id)
        stages = connection.scalar(
            select(func.count())
            .select_from(capture_stage_results)
            .where(capture_stage_results.c.version_id == saved.version_id)
        )
    assert job["state"] == JobState.QUEUED.value
    assert job["attempt_count"] == 0
    assert job["pause_cause"] == "current_policy_ineligible"
    assert job["last_error_code"] is None
    assert job["dead_lettered_at"] is None
    assert stages == 0
    assert job["next_attempt_at"] > datetime.now(UTC)  # type: ignore[operator]


def test_policy_pause_reevaluates_only_when_the_backoff_is_due(engine: Engine) -> None:
    configure_processing_eligibility(_refuse)
    with engine.begin() as connection:
        saved = save(connection, "Synthetic policy backoff.")
    assert drain(engine, jobs=1).paused == 1
    early = drain(engine, jobs=2)
    assert early.claimed == 0
    with engine.begin() as connection:
        before = _job(connection, saved.operation_id)
        connection.execute(
            text(
                "UPDATE knowledge.capture_jobs SET next_attempt_at = now() - interval '1 second' "
                "WHERE operation_id = :operation_id"
            ),
            {"operation_id": saved.operation_id},
        )
    again = drain(engine, jobs=1)
    assert again.paused == 1
    with engine.connect() as connection:
        after = _job(connection, saved.operation_id)
    assert after["attempt_count"] == 0
    assert after["pause_cause"] == "current_policy_ineligible"
    assert after["last_error_code"] is None
    assert int(after["lease_generation"]) > int(before["lease_generation"])  # type: ignore[arg-type]


def test_restore_resumes_the_same_operation_and_does_not_duplicate_stages(engine: Engine) -> None:
    with engine.begin() as connection:
        saved = save(connection, RICH_NOTE)
    assert drain(engine, jobs=1).completed == 1
    with engine.connect() as connection:
        stages = connection.scalar(
            select(func.count())
            .select_from(capture_stage_results)
            .where(capture_stage_results.c.version_id == saved.version_id)
        )
    _transition(
        engine, saved.capture_id, CaptureLifecycleOperation.ARCHIVE, expected=0, key="d-arch"
    )
    _transition(
        engine, saved.capture_id, CaptureLifecycleOperation.RESTORE, expected=1, key="d-rest"
    )
    with engine.connect() as connection:
        job = _job(connection, saved.operation_id)
        after = connection.scalar(
            select(func.count())
            .select_from(capture_stage_results)
            .where(capture_stage_results.c.version_id == saved.version_id)
        )
    assert job["state"] == JobState.SUCCEEDED.value
    assert job["pause_cause"] is None
    assert after == stages
    assert drain(engine, jobs=1).claimed == 0


def test_restore_under_an_ineligible_policy_stays_paused(engine: Engine) -> None:
    with engine.begin() as connection:
        saved = save(connection, "Synthetic ineligible restore.")
    _transition(
        engine, saved.capture_id, CaptureLifecycleOperation.ARCHIVE, expected=0, key="i-arch"
    )
    _transition(
        engine,
        saved.capture_id,
        CaptureLifecycleOperation.RESTORE,
        expected=1,
        key="i-rest",
        eligibility=_refuse,
    )
    with engine.connect() as connection:
        restored = _job(connection, saved.operation_id)
    assert restored["state"] == JobState.QUEUED.value
    assert restored["pause_cause"] == "current_policy_ineligible"
    assert restored["last_error_code"] is None
    assert restored["dead_lettered_at"] is None
    # The stored next_attempt_at is already due, so one re-evaluation runs and
    # pauses again. It still does not become a failure.
    configure_processing_eligibility(_refuse)
    run = drain(engine, jobs=1)
    assert (run.paused, run.released, run.completed, run.lost) == (1, 0, 0, 0)
    with engine.connect() as connection:
        job = _job(connection, saved.operation_id)
    assert job["state"] == JobState.QUEUED.value
    assert job["attempt_count"] == 0
    assert job["pause_cause"] == "current_policy_ineligible"
    assert job["last_error_code"] is None
    assert job["dead_lettered_at"] is None


def test_worker_health_backlog_excludes_paused_rows(engine: Engine) -> None:
    with engine.begin() as connection:
        saved = save(connection, "Synthetic backlog exclusion.")
        record_worker_heartbeat(
            connection,
            owner="worker-lifecycle04",
            principal_id=PRINCIPAL_ID,
            plane="capture",
        )
        before = worker_plane_health(connection, principal_id=PRINCIPAL_ID, plane_name="capture")
    assert before.backlog == 1
    _transition(
        engine, saved.capture_id, CaptureLifecycleOperation.ARCHIVE, expected=0, key="h-arch"
    )
    with engine.connect() as connection:
        after = worker_plane_health(connection, principal_id=PRINCIPAL_ID, plane_name="capture")
        queued = connection.scalar(
            select(func.count())
            .select_from(capture_jobs)
            .where(capture_jobs.c.state == JobState.QUEUED.value)
        )
    assert queued == 1
    assert after.backlog == 0
