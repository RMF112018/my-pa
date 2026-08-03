"""The application job plane: enqueue, claim under lease, finish.

This is the application's own plane and not `migration_control`. That schema
leases one resource per migration run and is written by the loader; conflating
the two would make an enrollment retry and a migration retry the same row, and
would put application code on the write path of migration governance state.

Six operations, because six is what a worker needs:

* `enqueue_job` records that an enrollment has work outstanding.
* `claim_job` takes the oldest claimable job under a bounded lease.
* `hold_lease` asserts, inside a write transaction, that the lease is still ours.
* `complete_job` and `release_job` end an attempt.
* `reap_abandoned_jobs` makes an abandoned final attempt terminal.

Claiming is idempotent in the sense that matters: `FOR UPDATE SKIP LOCKED`
means two workers running the same query take two different jobs rather than
one job twice, and the claim increments `attempt_count` in the same statement
that sets the lease, so an attempt is counted even by a worker that then dies
without reporting anything.

A crashed worker therefore releases its work by doing nothing, and there are two
cases rather than one. While attempts remain, the expired lease makes the job
claimable again. On the *final* attempt there is no next claim to recover it, so
without the reap the row would sit at `running` with an expired lease and an
exhausted attempt count — unclaimable, non-terminal, and reported as live work
that nothing is doing. Section 9.5 distinguishes `running` from `failed` and
`INV-PKL-007` forbids unavailable state that looks live, so that row is
`failed`; it just has not been written down yet.

`_ABANDONED` is that condition, declared once and used twice. `claim_job` reaps
before it claims, so the stored state converges on the next claim by any worker;
`job_state` derives the same answer from the same predicate, so a status read is
honest in the window before that happens. Deriving rather than writing on the
read path keeps a status query from needing a writable transaction, and using
one predicate for both is what stops the reported state and the stored state
from meaning different things. No sweeper process, no heartbeat table, and
nothing to restart — the recovery is a `WHERE` clause on the path that was
already going to run.

`complete_job` and `release_job` require the owner and match on it. A worker
whose lease expired while it was still running must not be able to report on
work another worker has since claimed, and the way it finds out is that its
update matches no row.

`hold_lease` is the same question asked *before* a write rather than after it,
and it exists because the worker no longer commits its whole job in one
transaction. `infrastructure.jobs.worker` used to hand a handler the connection
that then called `complete_job`, so a lost lease discarded the work by rolling
back the transaction it was written on. An extraction commits per object —
`module-boundaries.md` section 10 does not permit source bytes to be read inside
a database transaction, so the work cannot be one — and each of those
transactions asserts the lease itself. Without it, a worker whose lease expired
mid-pass would keep writing outcomes beside the results of the worker that took
over.

The clock is the server's. Every comparison and every expiry is computed with
`now()` inside the statement, so a worker with a skewed clock cannot extend its
own lease or declare another's expired.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Final, NamedTuple

from sqlalchemy import Connection, Row, and_, case, func, or_, select

from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import (
    DEFAULT_MAX_ATTEMPTS,
    MAX_LEASE_SECONDS,
    JobState,
    jobs,
)

__all__ = [
    "JobRecord",
    "LeasedJob",
    "claim_job",
    "complete_job",
    "enqueue_job",
    "hold_lease",
    "job_for",
    "job_state",
    "reap_abandoned_jobs",
    "release_job",
]

#: A job whose worker will never come back and which has no attempts left. The
#: lease is expired, so nobody holds it; the attempts are spent, so nobody may
#: take it. Declared once because `claim_job` writes this state and `job_state`
#: reports it, and the two answering differently would be worse than either
#: being wrong.
_ABANDONED: Final = and_(
    jobs.c.state == JobState.RUNNING.value,
    jobs.c.lease_expires_at <= func.now(),
    jobs.c.attempt_count >= jobs.c.max_attempts,
)

#: A worker names itself with a bounded token. The pattern excludes `.`, `:`,
#: `/`, and `@`, so a hostname, a URL, or an account cannot be stored as an
#: owner — this column is read by operators and appears in operational queries,
#: and `AGENTS.md` section 5 keeps hosts out of both.
_OWNER_PATTERN: Final = re.compile(r"\A[A-Za-z0-9_-]{4,64}\Z")


class JobRecord(NamedTuple):
    """One job as a status read sees it: which grant, and where it has got to."""

    operation_id: str
    enrollment_id: str
    state: JobState


class LeasedJob(NamedTuple):
    """A claim on one job: what to do, which attempt this is, and until when."""

    operation_id: str
    enrollment_id: str
    attempt: int
    lease_expires_at: datetime


def _validate_owner(owner: str) -> str:
    if not _OWNER_PATTERN.fullmatch(owner):
        raise ValueError(
            "worker owner must be 4-64 characters of letters, digits, hyphens, "
            "or underscores and must not be a host name or an address"
        )
    return owner


def enqueue_job(
    connection: Connection,
    enrollment_id: str,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> str:
    """Queue one unit of work for `enrollment_id` and return its `op_…`.

    Not idempotent, and deliberately so: the identifier it returns is the
    operation identifier section 8.6 requires async work to hand back, and two
    calls are two operations to observe separately. Where a caller needs "queue
    this once", the enrollment's own idempotency key is what already gives it
    that.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    if not 1 <= max_attempts <= DEFAULT_MAX_ATTEMPTS * 10:
        raise ValueError(f"max_attempts must be between 1 and {DEFAULT_MAX_ATTEMPTS * 10}")
    operation_id = issue_identifier(IdKind.OPERATION)
    connection.execute(
        jobs.insert().values(
            operation_id=operation_id,
            enrollment_id=enrollment_id,
            state=JobState.QUEUED.value,
            attempt_count=0,
            max_attempts=max_attempts,
        )
    )
    return operation_id


def reap_abandoned_jobs(connection: Connection) -> int:
    """Fail every job whose worker abandoned its final attempt. Returns the count.

    A job is abandoned when its lease has expired and its attempts are spent:
    nobody holds it and nobody may take it, so `running` is no longer true of
    it. Idempotent — a second call finds nothing, because the first made the
    rows terminal.

    `unavailable` is the recorded code because it is what is actually known: the
    worker stopped being available before it reported anything. Claiming to know
    more than that would be a guess written into the record.
    """
    statement = (
        jobs.update()
        .where(_ABANDONED)
        .values(
            state=JobState.FAILED.value,
            lease_owner=None,
            lease_expires_at=None,
            last_error_code=ErrorCode.UNAVAILABLE.value,
            updated_at=func.now(),
        )
    )
    return int(connection.execute(statement).rowcount)


def claim_job(connection: Connection, *, owner: str, lease_seconds: int) -> LeasedJob | None:
    """Claim the oldest claimable job for `owner`, or return `None`.

    Claimable means queued, or running with an expired lease — that second case
    is the recovery path for a crashed worker that still has attempts left. A
    job that has used every permitted attempt is not claimable, so the bound
    holds even if nobody ever calls `release_job`.

    Reaps first. Doing it here rather than in a separate process is what makes
    an abandoned final attempt reach a terminal state without introducing one:
    the only actor that exists is a worker looking for work, so that is where
    the convergence has to happen.
    """
    _validate_owner(owner)
    if not 1 <= lease_seconds <= MAX_LEASE_SECONDS:
        raise ValueError(f"lease_seconds must be between 1 and {MAX_LEASE_SECONDS}")

    reap_abandoned_jobs(connection)

    claimable = (
        select(jobs.c.operation_id)
        .where(
            or_(
                jobs.c.state == JobState.QUEUED.value,
                and_(
                    jobs.c.state == JobState.RUNNING.value,
                    jobs.c.lease_expires_at <= func.now(),
                ),
            ),
            jobs.c.attempt_count < jobs.c.max_attempts,
        )
        .order_by(jobs.c.created_at, jobs.c.operation_id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    statement = (
        jobs.update()
        .where(jobs.c.operation_id == claimable)
        .values(
            state=JobState.RUNNING.value,
            lease_owner=owner,
            lease_expires_at=func.now() + func.make_interval(0, 0, 0, 0, 0, 0, lease_seconds),
            attempt_count=jobs.c.attempt_count + 1,
            updated_at=func.now(),
        )
        .returning(
            jobs.c.operation_id,
            jobs.c.enrollment_id,
            jobs.c.attempt_count,
            jobs.c.lease_expires_at,
        )
    )
    row: Row[tuple[str, str, int, datetime]] | None = connection.execute(statement).one_or_none()
    if row is None:
        return None
    return LeasedJob(
        operation_id=str(row[0]),
        enrollment_id=str(row[1]),
        attempt=int(row[2]),
        lease_expires_at=row[3],
    )


def hold_lease(connection: Connection, operation_id: str, *, owner: str) -> bool:
    """Lock the job row and report whether `owner` still holds a live lease.

    Called first inside every transaction that writes an outcome, and its answer
    is what makes "a lost lease commits nothing" true of a worker that commits
    per object. A false answer is the caller's signal to raise, because raising
    is what rolls this transaction back; returning false and writing anyway
    would put one worker's result beside another's for the same job.

    `FOR UPDATE`, and that is the whole reason this is not two statements or a
    plain `SELECT`. The row lock is held until this transaction ends, so a claim
    by another worker cannot land between this read and the write that follows
    it — `claim_job` takes the same row `FOR UPDATE SKIP LOCKED` and will skip
    it while we hold it, and `complete_job` and `release_job` update it and
    block. Without the lock the answer would be true of an instant that had
    already passed by the time the outcome was inserted.

    The expiry is compared against `now()` inside the statement, like every other
    comparison in this module, so a worker with a skewed clock cannot decide its
    own lease is still good. The three conditions are the same three
    `complete_job` matches on plus that expiry: `complete_job` may rely on the
    reap having made an abandoned row terminal, while this runs mid-attempt, when
    nothing has yet reported the expiry.

    Returns false rather than raising for every way the lease can be gone — no
    such job, no longer running, owned by somebody else, or expired — because
    they are one fact to the caller and telling them apart would say something
    about a job this worker no longer holds.
    """
    validate_identifier(operation_id, IdKind.OPERATION)
    _validate_owner(owner)
    held = connection.execute(
        select(jobs.c.operation_id)
        .where(
            jobs.c.operation_id == operation_id,
            jobs.c.state == JobState.RUNNING.value,
            jobs.c.lease_owner == owner,
            jobs.c.lease_expires_at > func.now(),
        )
        .with_for_update()
    ).scalar_one_or_none()
    return held is not None


def complete_job(connection: Connection, operation_id: str, *, owner: str) -> bool:
    """Mark a job succeeded. Returns false when `owner` no longer holds the lease."""
    validate_identifier(operation_id, IdKind.OPERATION)
    _validate_owner(owner)
    statement = (
        jobs.update()
        .where(
            jobs.c.operation_id == operation_id,
            jobs.c.state == JobState.RUNNING.value,
            jobs.c.lease_owner == owner,
        )
        .values(
            state=JobState.SUCCEEDED.value,
            lease_owner=None,
            lease_expires_at=None,
            last_error_code=None,
            updated_at=func.now(),
        )
    )
    return connection.execute(statement).rowcount == 1


def release_job(
    connection: Connection,
    operation_id: str,
    *,
    owner: str,
    error_code: ErrorCode,
) -> JobState | None:
    """End a failed attempt, and report the state the job is now in.

    Returns to `queued` while attempts remain and to `failed` once they do not,
    which is the whole of the retry policy: bounded, and decided by the row
    rather than by a schedule. Returns `None` when `owner` no longer holds the
    lease, in which case the job belongs to someone else and nothing was
    written.
    """
    validate_identifier(operation_id, IdKind.OPERATION)
    _validate_owner(owner)
    exhausted = jobs.c.attempt_count >= jobs.c.max_attempts
    statement = (
        jobs.update()
        .where(
            jobs.c.operation_id == operation_id,
            jobs.c.state == JobState.RUNNING.value,
            jobs.c.lease_owner == owner,
        )
        .values(
            state=case(
                (exhausted, JobState.FAILED.value),
                else_=JobState.QUEUED.value,
            ),
            lease_owner=None,
            lease_expires_at=None,
            last_error_code=error_code.value,
            updated_at=func.now(),
        )
        .returning(jobs.c.state)
    )
    state = connection.execute(statement).scalar_one_or_none()
    return None if state is None else JobState(state)


def job_for(connection: Connection, operation_id: str) -> JobRecord | None:
    """Return the grant a job belongs to and the state it is in, or `None`.

    Reports an abandoned final attempt as `failed` from the moment its lease
    expires, rather than from the moment some later claim happens to write that
    down. The derivation uses the same `_ABANDONED` predicate `reap_abandoned_jobs`
    writes, so the answer here and the value that eventually lands in the column
    cannot disagree. It stays a read: a status query does not need a writable
    transaction to tell the truth.

    The enrollment travels with the state because a caller that has only an
    `op_…` has to be able to authorize the question it is asking, and the scope
    it runs in is the enrollment's. Two reads could return a state and a grant
    from two different statement snapshots; one cannot.
    """
    validate_identifier(operation_id, IdKind.OPERATION)
    reported = case((_ABANDONED, JobState.FAILED.value), else_=jobs.c.state)
    row: Row[tuple[str, str]] | None = connection.execute(
        select(jobs.c.enrollment_id, reported).where(jobs.c.operation_id == operation_id)
    ).one_or_none()
    if row is None:
        return None
    return JobRecord(operation_id=operation_id, enrollment_id=str(row[0]), state=JobState(row[1]))


def job_state(connection: Connection, operation_id: str) -> JobState | None:
    """Return the state of `operation_id`, or `None` when there is no such job.

    Derived from `job_for` rather than from a second statement, so the two
    cannot answer differently about the same row.
    """
    found = job_for(connection, operation_id)
    return None if found is None else found.state
