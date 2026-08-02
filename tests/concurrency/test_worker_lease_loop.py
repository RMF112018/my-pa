"""The lease loop claims, executes, ends, and stops — and never commits blind.

Against a real server, because every claim this module makes is about a
PostgreSQL transaction: that a lost lease rolls the work back, that a crashed
worker's job is recovered by the next claim rather than by a sweeper, and that a
job whose attempts are spent stops being claimable. None of those can be shown
against an in-memory double, which would agree with whatever the loop did.

The handler always writes something real — a `coverage_limitations` row for the
job's own enrollment — so "the work committed" and "the work was discarded" are
row counts rather than assertions about a flag the test set itself.

Everything is synthetic. The source root is an invented path that is never
opened and no live source is reached.
"""

from __future__ import annotations

import io
import os
import re
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.extraction.coverage import LimitationReason
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.enrollment import EnrollmentRequest, EnrollmentScope
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import SourceProviderKind, issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.jobs.worker import (
    JobExecutionError,
    issue_worker_owner,
    run_worker,
)
from my_pa.infrastructure.persistence.enrollment import accept_enrollment
from my_pa.infrastructure.persistence.extraction import record_limitation
from my_pa.infrastructure.persistence.jobs import LeasedJob, claim_job, enqueue_job, job_state
from my_pa.infrastructure.persistence.registry import observe_object, register_source
from my_pa.infrastructure.persistence.tables import DEFAULT_MAX_ATTEMPTS, JobState

ROOT = Path(__file__).resolve().parents[2]

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
DISPOSABLE_DATABASE = "my_pa_worker_test"

WHEN = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

#: Synthetic throughout. No such path exists and none is opened.
NATIVE_ROOT = "/synthetic/worker/corpus"

#: The owner pattern `persistence.jobs` enforces, restated so that a name this
#: module mints is checked against the rule rather than against itself.
OWNER_PATTERN: Final = re.compile(r"\A[A-Za-z0-9_-]{4,64}\Z")


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def disposable_database() -> Iterator[str]:
    """An empty database at head, dropped when the module finishes."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')
    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        _administer(maintenance, drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        _administer(maintenance, drop)
        maintenance.dispose()


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    built = create_database_engine(disposable_database)
    try:
        with built.begin() as connection:
            connection.execute(text("TRUNCATE knowledge.sources CASCADE"))
        yield built
    finally:
        built.dispose()


def _enqueue(engine: Engine, key: str, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> str:
    """One source, one observed object, one enrollment, and one queued job."""
    with engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Synthetic corpus",
            classification=Classification.SYNTHETIC_TEST,
            native_root=f"{NATIVE_ROOT}/{key}",
        )
        observed = observe_object(
            connection,
            source_id=source.source_id,
            native_locator=f"{NATIVE_ROOT}/{key}/note.md",
            kind=ObjectKind.FILE,
            fingerprint=f"fingerprint-{key}",
            modified_at=WHEN,
            media_type="text/markdown",
            size_bytes=32,
        )
        accepted = accept_enrollment(
            connection,
            EnrollmentRequest(
                source_id=source.source_id,
                principal_id=issue_identifier(IdKind.PRINCIPAL),
                purpose=Purpose.BOUNDED_ENROLLMENT,
                scope=EnrollmentScope(object_ids=(observed.source_object_id,)),
                media_types=("text/markdown",),
                policy_version="policy-v1",
                idempotency_key=f"enroll-{key}",
                max_items=10,
                max_bytes=4096,
            ),
        )
        return enqueue_job(connection, accepted.enrollment.enrollment_id, max_attempts=max_attempts)


class Recorder:
    """A handler that writes one real row per attempt and counts its calls.

    The row is a `coverage_limitations` row for the job's own enrollment, which
    is real work with a real unique key: it commits or it does not, and a test
    can tell which by counting.
    """

    def __init__(self, *, fail: bool = False, code: ErrorCode = ErrorCode.UNAVAILABLE) -> None:
        self.calls = 0
        self.jobs: list[str] = []
        self._fail = fail
        self._code = code

    def __call__(self, connection: Connection, job: LeasedJob) -> None:
        self.calls += 1
        self.jobs.append(job.operation_id)
        record_limitation(
            connection,
            enrollment_id=job.enrollment_id,
            observed_at=WHEN,
            reason=LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN,
            affected_count=1,
        )
        if self._fail:
            raise JobExecutionError(self._code)


def _limitations(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM knowledge.coverage_limitations")
            ).scalar_one()
        )


def _job_row(engine: Engine, operation_id: str) -> tuple[str, int, str | None, str | None]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT state, attempt_count, lease_owner, last_error_code "
                "FROM knowledge.jobs WHERE operation_id = :id"
            ),
            {"id": operation_id},
        ).one()
    return (str(row[0]), int(row[1]), row[2], row[3])


def test_a_worker_names_itself_without_naming_a_machine() -> None:
    """`AGENTS.md` section 5: no host in a column an operator reads.

    Runs in every tier, because it needs no server: the constraint is on the
    name, and `persistence.jobs` refuses a name that could be a host, an address,
    or an account.
    """
    minted = {issue_worker_owner() for _ in range(32)}
    assert len(minted) == 32, "two workers minted the same name"
    for owner in minted:
        assert OWNER_PATTERN.fullmatch(owner), f"{owner!r} is not an acceptable lease owner"
        assert "." not in owner and ":" not in owner and "@" not in owner


@pytest.mark.database
def test_the_worker_claims_executes_and_completes(engine: Engine) -> None:
    operation_id = _enqueue(engine, "completes")
    handler = Recorder()

    run = run_worker(
        engine,
        owner=issue_worker_owner(),
        handler=handler,
        stop=threading.Event(),
        max_iterations=2,
    )

    assert handler.calls == 1
    assert handler.jobs == [operation_id]
    assert (run.claimed, run.completed, run.released, run.lost) == (1, 1, 0, 0)
    # The second iteration found nothing, which is how the loop reports an empty
    # queue rather than by blocking.
    assert run.idle == 1
    assert _limitations(engine) == 1
    state, attempts, owner, code = _job_row(engine, operation_id)
    assert (state, attempts, owner, code) == (JobState.SUCCEEDED.value, 1, None, None)


@pytest.mark.database
def test_a_failed_attempt_is_released_and_the_work_is_discarded(engine: Engine) -> None:
    """A release returns the job to `queued` while attempts remain.

    The handler wrote a row before it failed, and that row is gone: the work and
    the completion share one transaction, so a failure takes both.
    """
    operation_id = _enqueue(engine, "releases")
    handler = Recorder(fail=True)

    run = run_worker(
        engine,
        owner=issue_worker_owner(),
        handler=handler,
        stop=threading.Event(),
        max_iterations=1,
    )

    assert (run.claimed, run.completed, run.released, run.lost) == (1, 0, 1, 0)
    assert _limitations(engine) == 0, "a failed attempt committed its partial work"
    state, attempts, owner, code = _job_row(engine, operation_id)
    assert (state, attempts, owner, code) == (
        JobState.QUEUED.value,
        1,
        None,
        ErrorCode.UNAVAILABLE.value,
    )


@pytest.mark.database
def test_poison_work_stops_being_claimed_once_its_attempts_are_spent(engine: Engine) -> None:
    """`module-boundaries.md` section 5.5: poison work quarantines rather than looping.

    The loop is given far more iterations than the job has attempts. It stops
    attempting the job after `max_attempts` because the *row* stops being
    claimable, not because the loop counted — which is what makes the bound hold
    for a second worker as well as for this one.
    """
    operation_id = _enqueue(engine, "poison")
    handler = Recorder(fail=True)

    run = run_worker(
        engine,
        owner=issue_worker_owner(),
        handler=handler,
        stop=threading.Event(),
        max_iterations=DEFAULT_MAX_ATTEMPTS + 5,
    )

    assert handler.calls == DEFAULT_MAX_ATTEMPTS
    assert run.released == DEFAULT_MAX_ATTEMPTS
    assert run.idle == 5, "the loop kept finding the poisoned job after it was terminal"
    state, attempts, owner, code = _job_row(engine, operation_id)
    assert state == JobState.FAILED.value
    assert attempts == DEFAULT_MAX_ATTEMPTS
    assert owner is None
    assert code == ErrorCode.UNAVAILABLE.value
    assert _limitations(engine) == 0

    # And a fresh worker cannot pick it up either.
    with engine.begin() as connection:
        assert claim_job(connection, owner=issue_worker_owner(), lease_seconds=60) is None
        assert job_state(connection, operation_id) is JobState.FAILED


@pytest.mark.database
def test_a_worker_that_lost_its_lease_commits_nothing(engine: Engine) -> None:
    """ "A lost lease cannot commit", proved by taking the lease mid-handler.

    The handler writes its row and, while still inside the work transaction, a
    second connection reassigns the lease — which is exactly what a slow worker
    whose lease expired would find. `complete_job` then matches no row, the loop
    raises, and the row the handler wrote goes with the rollback. Anything less
    would leave two workers' results for one job.
    """
    operation_id = _enqueue(engine, "stolen")
    thief = issue_worker_owner()

    def steal(connection: Connection, job: LeasedJob) -> None:
        record_limitation(
            connection,
            enrollment_id=job.enrollment_id,
            observed_at=WHEN,
            reason=LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN,
            affected_count=1,
        )
        with engine.begin() as other:
            other.execute(
                text(
                    "UPDATE knowledge.jobs SET lease_owner = :owner, "
                    " lease_expires_at = now() + interval '60 seconds' "
                    "WHERE operation_id = :id"
                ),
                {"owner": thief, "id": job.operation_id},
            )

    run = run_worker(
        engine,
        owner=issue_worker_owner(),
        handler=steal,
        stop=threading.Event(),
        max_iterations=1,
    )

    assert (run.claimed, run.completed, run.released, run.lost) == (1, 0, 0, 1)
    assert _limitations(engine) == 0, "a worker without the lease committed its work"
    state, _, owner, _ = _job_row(engine, operation_id)
    # Still running, still owned by whoever has it now. This worker wrote nothing.
    assert (state, owner) == (JobState.RUNNING.value, thief)


@pytest.mark.database
def test_a_crashed_worker_loses_no_job_and_the_next_claim_recovers_it(engine: Engine) -> None:
    """A worker that dies mid-attempt releases its work by doing nothing.

    The lease is taken with a one-second expiry and then abandoned — no
    completion, no release, which is what a killed process leaves behind. The
    next claim finds the job again, and the attempt the dead worker spent is
    still spent, so the bound converges rather than restarting.
    """
    operation_id = _enqueue(engine, "crashed")
    dead = issue_worker_owner()
    with engine.begin() as connection:
        claimed = claim_job(connection, owner=dead, lease_seconds=1)
    assert claimed is not None
    assert claimed.operation_id == operation_id

    # The lease is expired rather than waited out: this is the same state the
    # server would reach a second later, and waiting for it would make the test
    # slow without making it stronger.
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE knowledge.jobs SET lease_expires_at = now() - interval '1 second'")
        )

    handler = Recorder()
    run = run_worker(
        engine,
        owner=issue_worker_owner(),
        handler=handler,
        stop=threading.Event(),
        max_iterations=1,
    )

    assert (run.claimed, run.completed) == (1, 1)
    assert handler.calls == 1, "the recovered job was executed more than once"
    assert _limitations(engine) == 1, "the recovered job duplicated its work"
    state, attempts, owner, _ = _job_row(engine, operation_id)
    assert (state, owner) == (JobState.SUCCEEDED.value, None)
    assert attempts == 2, "the dead worker's attempt was not counted against the bound"


@pytest.mark.database
def test_a_stop_signal_ends_the_loop_without_abandoning_the_job_it_holds(
    engine: Engine,
) -> None:
    """Bounded shutdown: the held job reaches an end before the loop exits.

    The stop event is set from *inside* the handler, which is the moment a signal
    is most damaging — the lease is held and the work is half done. The loop
    finishes that job and then stops, so the lease is released rather than left
    to expire, and the work committed rather than being half written.
    """
    first = _enqueue(engine, "signalled-one")
    second = _enqueue(engine, "signalled-two")
    stop = threading.Event()
    handler = Recorder()

    def stopping(connection: Connection, job: LeasedJob) -> None:
        handler(connection, job)
        # As if SIGTERM arrived here.
        stop.set()

    run = run_worker(engine, owner=issue_worker_owner(), handler=stopping, stop=stop)

    assert stop.is_set()
    assert (run.claimed, run.completed, run.iterations) == (1, 1, 1)
    assert handler.calls == 1
    assert _limitations(engine) == 1

    done, other = (first, second) if handler.jobs == [first] else (second, first)
    state, _, owner, _ = _job_row(engine, done)
    assert (state, owner) == (JobState.SUCCEEDED.value, None), "the finished job kept its lease"
    # The one it never started is untouched and still available to anybody.
    assert _job_row(engine, other) == (JobState.QUEUED.value, 0, None, None)


@pytest.mark.database
def test_a_signal_between_the_claim_and_the_work_still_finishes_the_claimed_job(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window the other shutdown tests leave unpinned.

    `test_a_stop_signal_ends_the_loop_without_abandoning_the_job_it_holds` sets
    the flag from inside the handler, so it pins the window *during* the work.
    The window between the committed claim and the start of the work is a
    different one, and a reviewer showed it was invisible: planting
    `if stop.is_set(): break` immediately after the claim — while leaving the
    pre-claim guard intact — abandons a job with its lease held and the whole
    database tier still passed.

    The signal is delivered from a seam around `claim_job` itself, which is
    exactly that instant: the claim has committed, the lease is held, and the
    handler has not started. The job must still reach a terminal state with its
    lease released, because a worker that dropped it here would leave live work
    that nothing is doing until the lease expires.
    """
    operation_id = _enqueue(engine, "signal-after-claim")
    stop = threading.Event()
    handler = Recorder()
    real_claim = claim_job

    def claim_then_signal(
        connection: Connection, *, owner: str, lease_seconds: int
    ) -> LeasedJob | None:
        job = real_claim(connection, owner=owner, lease_seconds=lease_seconds)
        if job is not None:
            # As if SIGTERM arrived in the instant after the claim committed.
            stop.set()
        return job

    monkeypatch.setattr(
        "my_pa.infrastructure.jobs.worker.claim_job", claim_then_signal, raising=True
    )

    run = run_worker(engine, owner=issue_worker_owner(), handler=handler, stop=stop)

    assert stop.is_set()
    assert (run.claimed, run.completed, run.lost) == (1, 1, 0)
    assert handler.calls == 1, "the claimed job was abandoned instead of being finished"
    assert _limitations(engine) == 1
    state, attempts, owner, code = _job_row(engine, operation_id)
    assert (state, attempts, owner, code) == (JobState.SUCCEEDED.value, 1, None, None), (
        "the worker stopped while still holding the lease it had just taken"
    )


@pytest.mark.database
def test_a_worker_already_told_to_stop_claims_nothing(engine: Engine) -> None:
    """The condition is checked before the claim, not after it.

    A worker that claimed a job and then noticed it had been asked to stop would
    hold a lease it never intended to work on.
    """
    operation_id = _enqueue(engine, "pre-stopped")
    stop = threading.Event()
    stop.set()
    handler = Recorder()

    run = run_worker(engine, owner=issue_worker_owner(), handler=handler, stop=stop)

    assert (run.iterations, run.claimed) == (0, 0)
    assert handler.calls == 0
    assert _job_row(engine, operation_id) == (JobState.QUEUED.value, 0, None, None)


@pytest.mark.database
def test_two_workers_over_one_job_execute_it_once(engine: Engine) -> None:
    """`FOR UPDATE SKIP LOCKED` means two claims take two jobs, never one twice."""
    _enqueue(engine, "single")
    first = Recorder()
    second = Recorder()

    run_worker(
        engine, owner=issue_worker_owner(), handler=first, stop=threading.Event(), max_iterations=1
    )
    run_worker(
        engine, owner=issue_worker_owner(), handler=second, stop=threading.Event(), max_iterations=1
    )

    assert (first.calls, second.calls) == (1, 0)
    assert _limitations(engine) == 1


@pytest.mark.database
def test_an_unclassified_handler_failure_is_recorded_as_internal_error(engine: Engine) -> None:
    """A handler that raises something else is still bounded and still reported.

    `internal_error` rather than a guess: nothing about an unclassified exception
    is safe to record beyond that the attempt did not complete, and the column is
    constrained to the eleven public codes so there is nowhere for a driver
    message to go.
    """
    operation_id = _enqueue(engine, "unclassified")

    def explode(connection: Connection, job: LeasedJob) -> None:
        raise ZeroDivisionError("a failure this loop was never told how to classify")

    run = run_worker(
        engine,
        owner=issue_worker_owner(),
        handler=explode,
        stop=threading.Event(),
        max_iterations=1,
    )

    assert run.released == 1
    _, _, _, code = _job_row(engine, operation_id)
    assert code == ErrorCode.INTERNAL_ERROR.value


@pytest.mark.parametrize(
    ("field", "value"),
    [("lease_seconds", 0), ("lease_seconds", 10_000), ("poll_seconds", 0), ("max_iterations", -1)],
)
def test_the_loop_refuses_an_out_of_range_bound(field: str, value: int) -> None:
    """Bounds are checked before anything is claimed, so no connection is needed."""
    arguments: dict[str, object] = {field: value}
    with pytest.raises(ValueError, match=field.replace("_", "_")):
        run_worker(
            create_database_engine("postgresql+psycopg://nobody@127.0.0.1:1/nothing"),
            owner=issue_worker_owner(),
            handler=Recorder(),
            stop=threading.Event(),
            **arguments,  # type: ignore[arg-type]
        )
