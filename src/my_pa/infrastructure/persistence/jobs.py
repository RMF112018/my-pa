"""The application job plane: enqueue, claim under lease, finish.

This is the application's own plane and not `migration_control`. That schema
leases one resource per migration run and is written by the loader; conflating
the two would make an enrollment retry and a migration retry the same row, and
would put application code on the write path of migration governance state.

Four operations, because four is what a worker needs:

* `enqueue_job` records that an enrollment has work outstanding.
* `claim_job` takes the oldest claimable job under a bounded lease.
* `complete_job` and `release_job` end an attempt.

Claiming is idempotent in the sense that matters: `FOR UPDATE SKIP LOCKED`
means two workers running the same query take two different jobs rather than
one job twice, and the claim increments `attempt_count` in the same statement
that sets the lease, so an attempt is counted even by a worker that then dies
without reporting anything. A crashed worker's lease expires by the clock and
its job becomes claimable again with no sweeper process, no heartbeat table, and
nothing to restart.

`complete_job` and `release_job` require the owner and match on it. A worker
whose lease expired while it was still running must not be able to report on
work another worker has since claimed, and the way it finds out is that its
update matches no row.

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
    "LeasedJob",
    "claim_job",
    "complete_job",
    "enqueue_job",
    "job_state",
    "release_job",
]

#: A worker names itself with a bounded token. The pattern excludes `.`, `:`,
#: `/`, and `@`, so a hostname, a URL, or an account cannot be stored as an
#: owner — this column is read by operators and appears in operational queries,
#: and `AGENTS.md` section 5 keeps hosts out of both.
_OWNER_PATTERN: Final = re.compile(r"\A[A-Za-z0-9_-]{4,64}\Z")


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


def claim_job(connection: Connection, *, owner: str, lease_seconds: int) -> LeasedJob | None:
    """Claim the oldest claimable job for `owner`, or return `None`.

    Claimable means queued, or running with an expired lease — that second case
    is the entire recovery path for a crashed worker. A job that has used every
    permitted attempt is not claimable, so the bound holds even if nobody ever
    calls `release_job`.
    """
    _validate_owner(owner)
    if not 1 <= lease_seconds <= MAX_LEASE_SECONDS:
        raise ValueError(f"lease_seconds must be between 1 and {MAX_LEASE_SECONDS}")

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


def job_state(connection: Connection, operation_id: str) -> JobState | None:
    """Return the state of `operation_id`, or `None` when there is no such job."""
    validate_identifier(operation_id, IdKind.OPERATION)
    state = connection.execute(
        select(jobs.c.state).where(jobs.c.operation_id == operation_id)
    ).scalar_one_or_none()
    return None if state is None else JobState(state)
