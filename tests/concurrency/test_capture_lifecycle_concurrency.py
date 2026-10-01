"""T-CRL-06..09: capture lifecycle against the processing lease (CRL-WP-03).

Marked `database` and `recovery`. T-CRL-06 holds a stage transaction open until
archive is observed blocked, then lets the stage commit. The other three are
the stale-lease, generation, and final-attempt refusals. A lock timeout or a
deadlock is a failure of the test, not a retry.

Every identity here is synthetic.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.engine import Connection
from tests.concurrency.test_meeting_writes import _wait_until_blocked
from tests.pipeline.conftest import PRINCIPAL_ID, save

from my_pa.application.authorization import Authorization
from my_pa.application.capture_lifecycle import transition_capture
from my_pa.contracts.ports import AuditSink
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.lifecycle import CaptureLifecycleOperation
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import POLICY_VERSION, PolicyDecision
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.jobs.capture_pipeline import derive, process_capture_version
from my_pa.infrastructure.jobs.worker import LeaseLostError, issue_worker_owner
from my_pa.infrastructure.persistence.jobs import (
    CAPTURE_JOBS,
    claim_job,
    complete_job,
    hold_lease,
    reap_abandoned_jobs,
    release_job,
)
from my_pa.infrastructure.persistence.tables import capture_stage_results
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = [pytest.mark.database, pytest.mark.recovery]

NOW: Final = datetime(2026, 10, 1, 16, 30, tzinfo=UTC)
LOCK_TIMEOUT: Final = "20s"
JOIN_TIMEOUT_SECONDS: Final = 60.0
REASON: Final = "Synthetic concurrent withdrawal"


class _Audit(AuditSink):
    def record(self, event: object) -> None:  # type: ignore[override]
        del event


class Pause:
    """Hold the armed thread open immediately after one statement."""

    def __init__(self, engine: Engine, statement_prefix: str) -> None:
        self._prefix = statement_prefix
        self._owner: int | None = None
        self.reached = threading.Event()
        self.release = threading.Event()
        event.listen(engine, "after_cursor_execute", self._after)

    def arm(self) -> None:
        self._owner = threading.get_ident()

    def _after(self, *args: Any) -> None:  # noqa: ANN401
        statement = str(args[2])
        if self._owner == threading.get_ident() and statement.lstrip().startswith(self._prefix):
            self._owner = None
            self.reached.set()
            if not self.release.wait(JOIN_TIMEOUT_SECONDS):
                raise AssertionError("the paused transaction was never released")


@pytest.fixture
def engine(db_engine: Engine) -> Engine:
    @event.listens_for(db_engine, "connect")
    def _impatient(dbapi_connection: object, _record: object) -> None:
        with dbapi_connection.cursor() as cursor:  # type: ignore[attr-defined]
            cursor.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")

    return db_engine


def _archive(engine: Engine, capture_id: str, *, key: str, expected: int = 0) -> None:
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
            operation=CaptureLifecycleOperation.ARCHIVE,
            capture_id=capture_id,
            expected_lifecycle_revision=expected,
            reason=REASON,
            idempotency_key=key,
            now=NOW,
        )


def _restore(engine: Engine, capture_id: str, *, key: str, expected: int) -> None:
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
            operation=CaptureLifecycleOperation.RESTORE,
            capture_id=capture_id,
            expected_lifecycle_revision=expected,
            reason=REASON,
            idempotency_key=key,
            now=NOW,
        )


def _claim(engine: Engine) -> tuple[str, Any]:
    owner = issue_worker_owner()
    with engine.begin() as connection:
        job = claim_job(
            connection,
            owner=owner,
            lease_seconds=60,
            principal_id=PRINCIPAL_ID,
            plane=CAPTURE_JOBS,
        )
    assert job is not None
    return owner, job


def _control(connection: Connection, operation_id: str) -> dict[str, object]:
    row = connection.execute(
        text(
            "SELECT state, attempt_count, max_attempts, pause_cause, last_error_code, "
            "dead_lettered_at, lease_generation FROM knowledge.capture_jobs "
            "WHERE operation_id = :operation_id"
        ),
        {"operation_id": operation_id},
    ).one()
    return dict(row._mapping)


def test_a_stage_holds_the_root_and_the_job_until_archive_can_proceed(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-CRL-06: archive waits, the stage commits, remaining work is withdrawn."""
    with engine.begin() as connection:
        saved = save(connection, "Synthetic stage versus archive.")
    owner, job = _claim(engine)
    pause = Pause(engine, "SELECT knowledge.capture_jobs.operation_id")
    archive_finished = threading.Event()
    real_derive = derive

    def _derive_after_archive(content: str) -> object:
        assert archive_finished.wait(JOIN_TIMEOUT_SECONDS), "archive did not finish"
        return real_derive(content)

    monkeypatch.setattr("my_pa.infrastructure.jobs.capture_pipeline.derive", _derive_after_archive)

    def _stage() -> None:
        pause.arm()
        with pytest.raises(LeaseLostError):
            process_capture_version(engine, job, owner)

    def _archive_and_release() -> None:
        try:
            _archive(engine, saved.capture_id, key="tcrl06-arch")
        finally:
            archive_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        held = pool.submit(_stage)
        assert pause.reached.wait(JOIN_TIMEOUT_SECONDS), "the stage never took its lease"
        waiting = pool.submit(_archive_and_release)
        try:
            _wait_until_blocked(engine, waiting)
        finally:
            pause.release.set()
        held.result(timeout=JOIN_TIMEOUT_SECONDS)
        waiting.result(timeout=JOIN_TIMEOUT_SECONDS)

    with engine.connect() as connection:
        job_row = _control(connection, saved.operation_id)
        stages = connection.scalar(
            select(func.count())
            .select_from(capture_stage_results)
            .where(capture_stage_results.c.version_id == saved.version_id)
        )
    assert job_row["state"] == "queued"
    assert job_row["pause_cause"] == "capture_withdrawn"
    assert job_row["last_error_code"] is None
    assert job_row["dead_lettered_at"] is None
    assert stages == 1


def test_a_stale_holder_after_archive_loses_the_lease_and_writes_nothing(engine: Engine) -> None:
    """T-CRL-07."""
    with engine.begin() as connection:
        saved = save(connection, "Synthetic stale holder.")
    owner, job = _claim(engine)
    _archive(engine, saved.capture_id, key="tcrl07-arch")
    with engine.begin() as connection:
        held = hold_lease(
            connection,
            job.operation_id,
            owner=owner,
            plane=CAPTURE_JOBS,
            generation=job.generation,
        )
        stages = connection.scalar(
            select(func.count())
            .select_from(capture_stage_results)
            .where(capture_stage_results.c.version_id == saved.version_id)
        )
        row = _control(connection, saved.operation_id)
    assert held is False
    assert stages == 0
    assert row["state"] == "queued"
    assert row["pause_cause"] == "capture_withdrawn"
    assert row["last_error_code"] is None


def test_an_old_generation_cannot_publish_complete_or_release(engine: Engine) -> None:
    """T-CRL-08: archive, restore, reclaim; generation g is refused everywhere."""
    with engine.begin() as connection:
        saved = save(connection, "Synthetic generation fence.")
    owner, stale = _claim(engine)
    assert stale.generation is not None
    _archive(engine, saved.capture_id, key="tcrl08-arch")
    _restore(engine, saved.capture_id, key="tcrl08-rest", expected=1)
    with engine.begin() as connection:
        reclaimed = claim_job(
            connection,
            owner=owner,
            lease_seconds=60,
            principal_id=PRINCIPAL_ID,
            plane=CAPTURE_JOBS,
        )
    assert reclaimed is not None
    assert reclaimed.generation == stale.generation + 2
    with pytest.raises(LeaseLostError):
        process_capture_version(engine, stale, owner)
    with engine.begin() as connection:
        completed = complete_job(
            connection,
            stale.operation_id,
            owner=owner,
            plane=CAPTURE_JOBS,
            generation=stale.generation,
        )
        released = release_job(
            connection,
            stale.operation_id,
            owner=owner,
            error_code=ErrorCode.UNAVAILABLE,
            plane=CAPTURE_JOBS,
            generation=stale.generation,
        )
        stages = connection.scalar(
            select(func.count())
            .select_from(capture_stage_results)
            .where(capture_stage_results.c.version_id == saved.version_id)
        )
        row = _control(connection, saved.operation_id)
    assert completed is False
    assert released is None
    assert stages == 0
    assert row["state"] == "running"
    assert int(row["lease_generation"]) == reclaimed.generation  # type: ignore[arg-type]


def test_a_final_attempt_is_refunded_and_claimable_after_restore(engine: Engine) -> None:
    """T-CRL-09."""
    with engine.begin() as connection:
        saved = save(connection, "Synthetic final attempt.")
        connection.execute(
            text(
                "UPDATE knowledge.capture_jobs SET state = 'running', "
                "attempt_count = max_attempts, lease_owner = 'worker-lifecycle04', "
                "lease_expires_at = now() - interval '1 second', lease_generation = 4 "
                "WHERE operation_id = :operation_id"
            ),
            {"operation_id": saved.operation_id},
        )
    _archive(engine, saved.capture_id, key="tcrl09-arch")
    with engine.begin() as connection:
        reaped = reap_abandoned_jobs(connection, principal_id=PRINCIPAL_ID, plane=CAPTURE_JOBS)
        withdrawn = _control(connection, saved.operation_id)
    assert reaped == 0
    assert withdrawn["state"] == "queued"
    assert int(withdrawn["attempt_count"]) == int(withdrawn["max_attempts"]) - 1  # type: ignore[arg-type]
    assert withdrawn["last_error_code"] is None
    assert withdrawn["dead_lettered_at"] is None
    _restore(engine, saved.capture_id, key="tcrl09-rest", expected=1)
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
