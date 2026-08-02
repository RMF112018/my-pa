"""The lease loop: claim one job, drive it to an end, and stop when told to.

**Why it lives here.** `module-boundaries.md` section 5.5 gives
`infrastructure.jobs` "leases, attempts, retry state" and the rule that "poison
work quarantines rather than looping" — which is a statement about the loop, not
about the statements it runs. Section 5.3 says the application does not "embed
process lifecycle", and the application layer additionally may not import
SQLAlchemy (`MB-AC-002`), so a loop placed there would have needed a new port
with claim, complete, and release on it: three more abstractions to carry a
sequence that has exactly one caller. Section 5.10 gives `apps.worker` "bounded
polling/lease execution", and that is the split taken here — the mechanics are
in this module and the *process* is in `apps/worker.py`: settings, engine,
signals, and what is printed when it stops.

**The transaction shape is the whole correctness argument.** Three transactions
per job, and each boundary is where it is for a reason.

1. *Claim, and commit.* The lease has to be visible to every other worker before
   the work starts, so the claim cannot sit inside the work's transaction. The
   claim also increments `attempt_count` in the same statement, so an attempt is
   spent even by a worker that dies immediately afterwards, and the bound
   converges without anything having to clean up.
2. *Work and completion, together.* The handler runs on the same connection that
   then calls `complete_job`, inside one transaction. `complete_job` matches on
   the lease owner and returns false when the lease has since been taken by
   somebody else — and that false raises, which rolls the *work* back with it.
   This is what makes "a lost lease cannot commit" true rather than merely
   likely: a worker whose lease expired mid-extraction does not get to write its
   result beside the result of the worker that took over.
3. *Release, alone.* A failed attempt is reported in its own transaction,
   because the one that failed has already been rolled back and there is nothing
   left to write it on. `release_job` also matches on the owner, so a worker that
   lost its lease writes nothing and says so.

**Bounded, and the bound is the row's.** `release_job` returns the job to
`queued` while attempts remain and to `failed` once they do not, and
`claim_job` will not claim a job whose attempts are spent. Work that fails every
time therefore stops being claimed after `max_attempts` and sits terminal with
the error code of its last attempt — quarantined in the sense section 5.5 means,
by a stored state that no loop can re-enter, rather than by a retry schedule this
module would have to be trusted to honour.

**Shutdown is bounded and abandons nothing.** The stop signal is a
`threading.Event`, checked once per iteration and waited on instead of slept
through, so a signal wakes an idle worker at once. It is deliberately *not*
checked inside `_execute`: a worker that dropped a claimed job on a signal would
leave a lease held until it expired, which is precisely the abandonment the
shutdown is supposed to avoid. The bound on how long a stop takes is therefore
one job, which is what the lease already bounds.

**Nothing here logs.** The run returns counts and the job plane holds the
states; both are readable without a logging framework, and a log line about a
job is one more place an identifier could be joined to something it should not
be. `apps/worker.py` prints the counts.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from sqlalchemy import Connection, Engine

from my_pa.contracts.v1.errors import ErrorCode
from my_pa.infrastructure.persistence.jobs import (
    LeasedJob,
    claim_job,
    complete_job,
    release_job,
)
from my_pa.infrastructure.persistence.tables import MAX_LEASE_SECONDS

__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_POLL_SECONDS",
    "JobExecutionError",
    "JobHandler",
    "LeaseLostError",
    "WorkerRun",
    "issue_worker_owner",
    "run_worker",
]

#: How long a claim is good for. Well under `MAX_LEASE_SECONDS`, because the
#: lease is also how long a crashed worker's job stays unclaimable: a long lease
#: buys a slow job nothing that a shorter one does not, and costs recovery time.
DEFAULT_LEASE_SECONDS: Final = 300

#: How long an idle worker waits before looking again. Long enough that an idle
#: worker is not a busy loop against the server, short enough that queued work
#: is picked up promptly. The wait is on the stop event, so a signal does not
#: wait it out.
DEFAULT_POLL_SECONDS: Final = 5.0

#: Bytes of randomness in a worker's name. The name is written to `lease_owner`,
#: which an operator reads, so it must not be a host name or an account —
#: `persistence.jobs` enforces that with a pattern, and this is what satisfies it
#: without anybody choosing a name that identifies a machine.
_OWNER_BYTES: Final = 8


class JobExecutionError(Exception):
    """A handler's declaration that this attempt failed, and which code says so.

    Carries an `ErrorCode` and nothing else. The job row's `last_error_code`
    column is constrained to the eleven public codes precisely so that a driver
    message — which can quote the value it rejected — cannot reach it, and a
    handler that wants to explain more than a code has nowhere to put it here on
    purpose.
    """

    def __init__(self, code: ErrorCode) -> None:
        super().__init__(f"the attempt failed with {code.value}")
        self.code = code


class LeaseLostError(Exception):
    """Raised inside the work transaction when the lease is no longer ours.

    Raised rather than returned, because raising is what rolls the work back.
    A worker that discovered this and returned normally would commit a result
    for a job another worker now owns.
    """


#: What a worker does with one claimed job, on the connection whose transaction
#: will also record the completion. Raising `JobExecutionError` names the code
#: the attempt failed with; raising anything else is an unclassified failure and
#: is recorded as `internal_error`.
type JobHandler = Callable[[Connection, LeasedJob], None]


@dataclass(frozen=True, slots=True)
class WorkerRun:
    """What one run of the loop did. Counts and nothing else.

    `released` counts attempts that ended in failure, whether or not attempts
    remained; `lost` counts attempts whose lease had been taken by another
    worker before they finished, which is a different event and is not a failure
    of the work. `iterations` counts times round the loop, so an idle run is
    distinguishable from one that found nothing to do because it was told to
    stop.
    """

    iterations: int = 0
    claimed: int = 0
    completed: int = 0
    released: int = 0
    lost: int = 0
    idle: int = 0


def issue_worker_owner() -> str:
    """Mint one worker's lease-owner name.

    Non-semantic by construction: `secrets.token_hex` output behind a fixed
    prefix. It names nothing about the machine, which is what keeps a host out
    of a column operators read (`AGENTS.md` section 5).
    """
    return f"worker-{secrets.token_hex(_OWNER_BYTES)}"


def _execute(engine: Engine, job: LeasedJob, *, owner: str, handler: JobHandler) -> str:
    """Run one claimed job to an end, and report which end it reached.

    Returns `"completed"`, `"released"`, or `"lost"`. The two failure paths are
    separated because they mean different things: a released attempt failed and
    may be retried within the bound, while a lost lease means this worker's
    result was discarded and the job belongs to somebody else.
    """
    failure: ErrorCode | None = None
    lost = False
    try:
        with engine.begin() as connection:
            handler(connection, job)
            if not complete_job(connection, job.operation_id, owner=owner):
                # The lease went while we were working. Raising is what discards
                # the work the handler just wrote on this connection.
                raise LeaseLostError(job.operation_id)
        return "completed"
    except LeaseLostError:
        lost = True
    except JobExecutionError as error:
        failure = error.code
    except Exception:
        # Unclassified, so nothing about it is safe to record beyond that the
        # attempt did not complete. Recorded here and acted on below, outside the
        # handler, so the driver's exception is not left in `__context__` of
        # anything this raises later.
        failure = ErrorCode.INTERNAL_ERROR

    if lost:
        return "lost"
    if failure is None:  # pragma: no cover - the branches above are exhaustive
        failure = ErrorCode.INTERNAL_ERROR
    with engine.begin() as connection:
        outcome = release_job(connection, job.operation_id, owner=owner, error_code=failure)
    # `None` means the update matched no row, which is the same discovery
    # `complete_job` makes: the lease is no longer ours and nothing was written.
    return "released" if outcome is not None else "lost"


def run_worker(
    engine: Engine,
    *,
    owner: str,
    handler: JobHandler,
    stop: threading.Event,
    max_iterations: int | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
) -> WorkerRun:
    """Claim and execute jobs until `stop` is set or `max_iterations` is reached.

    `max_iterations` bounds a run without a signal, which is what makes a drain
    or a test a bounded operation rather than a loop somebody has to interrupt.
    `None` means "until told to stop", which is what a service does.

    An iteration that finds no work waits on `stop` for `poll_seconds` and
    returns to the top. When `max_iterations` is set, an idle iteration does not
    wait at all: a bounded run asked to do at most *n* iterations should not
    spend *n* whole `poll_seconds` waits discovering there is nothing to do.
    """
    if not 1 <= lease_seconds <= MAX_LEASE_SECONDS:
        raise ValueError(f"lease_seconds must be between 1 and {MAX_LEASE_SECONDS}")
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    if max_iterations is not None and max_iterations < 0:
        raise ValueError("max_iterations cannot be negative")

    bounded = max_iterations is not None
    iterations = claimed = completed = released = lost = idle = 0

    while not stop.is_set():
        if max_iterations is not None and iterations >= max_iterations:
            break
        iterations += 1

        with engine.begin() as connection:
            # Committed on leaving this block, so the lease is visible to every
            # other worker before any work begins.
            job = claim_job(connection, owner=owner, lease_seconds=lease_seconds)

        if job is None:
            idle += 1
            if not bounded:
                stop.wait(poll_seconds)
            continue

        claimed += 1
        # Deliberately not interruptible. A signal arriving now is honoured by
        # the `while` condition after this job has reached an end, so no lease is
        # abandoned and no partial work is left behind.
        match _execute(engine, job, owner=owner, handler=handler):
            case "completed":
                completed += 1
            case "released":
                released += 1
            case _:
                lost += 1

    return WorkerRun(
        iterations=iterations,
        claimed=claimed,
        completed=completed,
        released=released,
        lost=lost,
        idle=idle,
    )
