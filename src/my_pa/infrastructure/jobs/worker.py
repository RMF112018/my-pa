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

**The transaction shape is the whole correctness argument.** This loop opens
three transactions per job and the handler opens its own; each boundary is where
it is for a reason.

1. *Claim, and commit.* The lease has to be visible to every other worker before
   the work starts, so the claim cannot sit inside the work's transaction. The
   claim also increments `attempt_count` in the same statement, so an attempt is
   spent even by a worker that dies immediately afterwards, and the bound
   converges without anything having to clean up.
2. *Work, on the engine.* The handler is given the `Engine` and the lease owner
   rather than an open `Connection`, and it opens as many transactions as the
   work needs. That is not a preference: `module-boundaries.md` section 10 says
   source bytes are read *outside* the database transaction, and
   `application/service.py` names this worker's extraction path as the rule's
   target. A handler holding one transaction across a whole enrollment would
   also have to finish inside `DEFAULT_LEASE_SECONDS`, which at the configured
   ceilings it cannot — the rollback would then discard every object rather than
   the last one, and three attempts later the job would be terminal `failed`
   having recorded nothing at all.
3. *Completion, alone.* `complete_job` runs in its own transaction and matches on
   the lease owner. A false answer raises, and `succeeded` is not written.
4. *Release, alone.* A failed attempt is reported in its own transaction, because
   the one that failed has already been rolled back and there is nothing left to
   write it on. `release_job` also matches on the owner, so a worker that lost
   its lease writes nothing and says so.

**What the old shape bought, and what buys it now.** The handler used to run on
the connection that then called `complete_job`, so raising discarded the work it
had written. That is where "a lost lease cannot commit" came from, and it is
gone. It is replaced by `persistence.jobs.hold_lease`, which every write
transaction takes as its first statement: a worker whose lease has been taken
finds out *before* it writes, and its transaction rolls back having written
nothing. The property is now per object rather than per job, and it is proved in
that narrow form — a coarse proof would pass on a handler that asserted the
lease once and then wrote ten times.

**What a lost lease may leave behind, said plainly rather than papered over.**
Objects the handler committed *before* the lease went are still there, and they
are true: they were written while the lease was held, they are keyed under
`one_extraction_per_version_per_enrollment`, and the worker that takes the job
over skips them because they are no longer pending. This is convergence, not
atomicity, and the difference matters — a reader who believed the job was atomic
would expect a re-run to start from nothing.

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

**One loop, two planes** (`D-76`, `D-77`). `persistence.jobs` was already
parameterised over a `JobPlane` — one lease rule, two tables — but this loop was
not, so `claim_job` here resolved to `ENROLLMENT_JOBS` and the capture plane had
a writer and no reader. WP-7 adds the `plane` argument rather than a second loop,
because every sentence above is a statement about the lease protocol and the
lease protocol is the thing the two planes share. What differs between them is
which table the claim reads and what the handler does with `subject_id` — an
`enr_…` on one and a `capver_…` on the other, which is exactly what
`JobPlane.subject_kind` records. A second loop would be the "same persistence
twice" objection `D-41` names, answered here the way `D-77` answered it: by
sharing the code, not the table.

The default stays `ENROLLMENT_JOBS`, so nothing that already called this changed
behaviour. That is a compatibility default and not a preference: `apps/worker.py`
names its plane explicitly, and a caller that omits it is asking for the plane
this loop has always run.

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

from sqlalchemy import Engine

from my_pa.contracts.v1.errors import ErrorCode
from my_pa.infrastructure.persistence.jobs import (
    ENROLLMENT_JOBS,
    JobPlane,
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
    """Raised, by a handler or by this module, when the lease is no longer ours.

    Raised rather than returned, because raising is what rolls back the
    transaction that discovered it. A handler that found this and returned
    normally would go on to write outcomes for a job another worker now owns,
    and this loop would then mark it `succeeded`.

    A handler raises it from inside a write transaction, on a false answer from
    `persistence.jobs.hold_lease`; `_execute` raises it on a false answer from
    `complete_job`. Both mean the same thing to the loop, which is why there is
    one type for them.
    """


#: What a worker does with one claimed job. It receives the engine and the lease
#: owner rather than an open connection, because the extraction path reads source
#: bytes and `module-boundaries.md` section 10 does not permit that inside a
#: database transaction. The owner travels with it because a handler that commits
#: as it goes has to assert the lease itself: what the old signature bought — "a
#: lost lease commits nothing", because raising discarded work written on the
#: completing connection — is bought instead by `hold_lease`, which every write
#: transaction takes before it writes.
#:
#: Raising `JobExecutionError` names the code the attempt failed with; raising
#: `LeaseLostError` says the lease went and the attempt belongs to somebody else;
#: raising anything else is an unclassified failure and is recorded as
#: `internal_error`.
type JobHandler = Callable[[Engine, LeasedJob, str], None]
type Heartbeat = Callable[[], None]


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


def _execute(
    engine: Engine, job: LeasedJob, *, owner: str, handler: JobHandler, plane: JobPlane
) -> str:
    """Run one claimed job to an end, and report which end it reached.

    Returns `"completed"`, `"released"`, or `"lost"`. The two failure paths are
    separated because they mean different things: a released attempt failed and
    may be retried within the bound, while a lost lease means this worker stopped
    writing at the moment it lost the job and the job belongs to somebody else.

    The handler runs before the completion and outside it. Its own transactions
    are its own — see the module docstring for why they have to be, and for what
    `hold_lease` re-establishes in their place. What this function still owns is
    that `succeeded` is written only by the lease holder, in a transaction of its
    own, after the handler has returned.
    """
    failure: ErrorCode | None = None
    lost = False
    try:
        handler(engine, job, owner)
        with engine.begin() as connection:
            if not complete_job(connection, job.operation_id, owner=owner, plane=plane):
                # The lease went while we were working. There is nothing to
                # discard here any more — the handler committed as it went, and
                # `hold_lease` is what stopped it once the lease was gone — so
                # what this raise prevents is the `succeeded` state itself.
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
        outcome = release_job(
            connection, job.operation_id, owner=owner, error_code=failure, plane=plane
        )
    # `None` means the update matched no row, which is the same discovery
    # `complete_job` makes: the lease is no longer ours and nothing was written.
    return "released" if outcome is not None else "lost"


def run_worker(
    engine: Engine,
    *,
    owner: str,
    handler: JobHandler,
    stop: threading.Event,
    principal_id: str,
    plane: JobPlane = ENROLLMENT_JOBS,
    max_iterations: int | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    heartbeat: Heartbeat | None = None,
) -> WorkerRun:
    """Claim and execute jobs until `stop` is set or `max_iterations` is reached.

    `max_iterations` bounds a run without a signal, which is what makes a drain
    or a test a bounded operation rather than a loop somebody has to interrupt.
    `None` means "until told to stop", which is what a service does.

    An iteration that finds no work waits on `stop` for `poll_seconds` and
    returns to the top. When `max_iterations` is set, an idle iteration does not
    wait at all: a bounded run asked to do at most *n* iterations should not
    spend *n* whole `poll_seconds` waits discovering there is nothing to do.

    `principal_id` is the Principal whose queue this loop serves, and it is
    required rather than defaulted (WP-04). Until the queues carried a partition,
    `claim_job` took the oldest claimable row in the whole table, which made the
    dequeue a global FIFO: one Principal's backlog decided when another's work
    ran. A default here would restore that by omission, so there is none — a
    worker says whose work it is doing. The composition root supplies it from the
    Principal it already derived, never from a request.

    `plane` chooses which job table the claim, the completion, and the release
    run against. One worker process serves one plane: a loop that claimed from
    both would have to decide which handler a claimed job belongs to, and the
    only thing that could tell it is the table the job came out of — which is
    the argument, so it may as well be the argument.
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
        if heartbeat is not None:
            heartbeat()

        with engine.begin() as connection:
            # Committed on leaving this block, so the lease is visible to every
            # other worker before any work begins.
            job = claim_job(
                connection,
                owner=owner,
                lease_seconds=lease_seconds,
                principal_id=principal_id,
                plane=plane,
                # A bounded invocation is an explicit drain/recovery operation,
                # so it may consume the persisted retry schedule immediately.
                # The unbounded service loop always respects wall-clock backoff.
                respect_retry_schedule=not bounded,
            )

        if job is None:
            idle += 1
            if not bounded:
                stop.wait(poll_seconds)
            continue

        claimed += 1
        # Deliberately not interruptible. A signal arriving now is honoured by
        # the `while` condition after this job has reached an end, so no lease is
        # abandoned and nothing is left `running` for another worker to wait out.
        # What a handler had already committed stays committed and is skipped by
        # the attempt that follows; the module docstring says why that is
        # convergence rather than a partial write.
        match _execute(engine, job, owner=owner, handler=handler, plane=plane):
            case "completed":
                completed += 1
            case "released":
                released += 1
            case _:
                lost += 1
        if heartbeat is not None:
            heartbeat()

    return WorkerRun(
        iterations=iterations,
        claimed=claimed,
        completed=completed,
        released=released,
        lost=lost,
        idle=idle,
    )
