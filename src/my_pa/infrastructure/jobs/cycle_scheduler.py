"""The cycles plane's loop: poll, and run each due step once under its own lock.

ADR-010 amendment of 2026-11-20, served as `apps/worker.py run --plane cycles`;
generalized to a tuple of steps for communications WP3a (Manager ruling M2,
contract section 19). This module owns *when* and *single flight*; what a step
does is composed by the entry point and handed in as a callable (the daily
cycle lives in `application.daily_cycle` and the ingestion poll in
`application.ingestion`, neither of which infrastructure may import).

**Steps.** A `SchedulerStep` is a name, a lock key, a due rule and a run. Two
shapes exist:

* `DailyStep` -- the Morning Intelligence cycle. Due by
  `domain.intelligence.daily_cycle.due` on the injected clock; the last run
  date is this process's memory, so a process that starts runs at once for the
  current local date (the catch-up rule: one run for the latest missed date,
  never a backfill). Only a completed begin step (`run_for` answering True)
  advances the last run date, so a failed or raising run is retried on the
  next poll.
* `IntervalStep` -- a fixed-interval step (the communications ingestion poll,
  default 900 s). Due at once on start and then every `interval_seconds` after
  the previous *attempt* (success or not): the poll is idempotent and a failing
  source must not be hammered once a minute.

**Single flight, per step.** A step runs holding a PostgreSQL *session*
advisory lock on its own key, on its own connection, for the whole run.
`pg_try_advisory_lock` does not wait: a step whose lock another process holds
is skipped for this poll (and stays due), and the other steps of the same
iteration run regardless.

**Bounded and never fatal.** A step that raises is counted and logged as a
code; nothing propagates out of the loop. Log lines carry an event, closed
codes and counts only.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Final, Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, func, select

from my_pa.domain.intelligence.daily_cycle import due

__all__ = [
    "COMMS_INGEST_LOCK_KEY",
    "CYCLE_SCHEDULER_LOCK_KEY",
    "DEFAULT_COMMS_INGEST_POLL_SECONDS",
    "DEFAULT_CYCLE_POLL_SECONDS",
    "CycleSchedulerRun",
    "DailyStep",
    "IntervalStep",
    "SchedulerStep",
    "StepCounts",
    "advisory_lock_key",
    "run_cycle_scheduler",
    "run_scheduler_steps",
    "single_flight",
]

#: How often an idle scheduler looks at the clock. A minute late at midnight is
#: immaterial, and the wait is on the stop event, so a signal does not wait it out.
DEFAULT_CYCLE_POLL_SECONDS: Final = 60.0

#: The communications ingestion poll's interval (contract section 19: 15 minutes).
DEFAULT_COMMS_INGEST_POLL_SECONDS: Final = 900


def advisory_lock_key(label: bytes) -> int:
    """The session advisory-lock key for `label`: the first 8 bytes of its SHA-256, signed."""
    return int.from_bytes(hashlib.sha256(label).digest()[:8], byteorder="big", signed=True)


#: The session advisory-lock key every daily-cycle step contends for.
CYCLE_SCHEDULER_LOCK_KEY: Final = advisory_lock_key(b"my-pa-daily-cycle-scheduler")

#: The session advisory-lock key every communications ingestion poll contends for.
COMMS_INGEST_LOCK_KEY: Final = advisory_lock_key(b"my-pa-ingest-poll")

type RunFor = Callable[[date], bool]
type Log = Callable[[Mapping[str, object]], None]


class SchedulerStep(Protocol):
    """One step of the cycles plane: a name, a lock key, a due rule and a run."""

    @property
    def name(self) -> str:
        """A closed token naming the step in counts."""
        ...

    @property
    def event(self) -> str:
        """The log-event prefix of this step's `skipped` and `failed` lines."""
        ...

    @property
    def lock_key(self) -> int:
        """The session advisory-lock key this step's single flight contends for."""
        ...

    def due(self, now: datetime) -> Mapping[str, object] | None:
        """The log context of the run due at `now`, or `None` when none is due."""
        ...

    def run(self, now: datetime, context: Mapping[str, object]) -> bool:
        """Run once (lock held); True when the run completed."""
        ...


@dataclass(slots=True)
class DailyStep:
    """The daily Morning Intelligence cycle: due once per local date (module docstring)."""

    zone: ZoneInfo
    run_for: RunFor
    lock_key: int = CYCLE_SCHEDULER_LOCK_KEY
    name: str = "daily_cycle"
    event: str = "cycle_scheduler"
    last_run: date | None = None

    def due(self, now: datetime) -> Mapping[str, object] | None:
        business_date = due(now, zone=self.zone, last_run=self.last_run)
        return None if business_date is None else {"business_date": business_date.isoformat()}

    def run(self, now: datetime, context: Mapping[str, object]) -> bool:
        business_date = date.fromisoformat(str(context["business_date"]))
        if not self.run_for(business_date):
            return False
        self.last_run = business_date
        return True


@dataclass(slots=True)
class IntervalStep:
    """A fixed-interval step: due on start, then `interval_seconds` after each attempt."""

    name: str
    event: str
    lock_key: int
    interval_seconds: float
    run_once: Callable[[], bool]
    last_attempt: datetime | None = None

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")

    def due(self, now: datetime) -> Mapping[str, object] | None:
        if self.last_attempt is not None and now - self.last_attempt < timedelta(
            seconds=self.interval_seconds
        ):
            return None
        return {}

    def run(self, now: datetime, context: Mapping[str, object]) -> bool:
        self.last_attempt = now
        return self.run_once()


@dataclass(frozen=True, slots=True)
class StepCounts:
    """What one step did across the loop. Counts only."""

    runs: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass(frozen=True, slots=True)
class CycleSchedulerRun:
    """What one loop did: totals over every step, and each step's own counts."""

    iterations: int = 0
    runs: int = 0
    skipped: int = 0
    failed: int = 0
    steps: Mapping[str, StepCounts] = field(default_factory=dict)


@contextmanager
def single_flight(engine: Engine, *, key: int = CYCLE_SCHEDULER_LOCK_KEY) -> Iterator[bool]:
    """Yield True while this process holds the lock `key`, False if another does."""
    with engine.connect() as connection:
        held = bool(connection.execute(select(func.pg_try_advisory_lock(key))).scalar_one())
        connection.commit()
        try:
            yield held
        finally:
            if held:
                connection.execute(select(func.pg_advisory_unlock(key))).scalar_one()
                connection.commit()


def run_scheduler_steps(
    engine: Engine,
    *,
    steps: Sequence[SchedulerStep],
    stop: threading.Event,
    clock: Callable[[], datetime],
    log: Log,
    poll_seconds: float = DEFAULT_CYCLE_POLL_SECONDS,
    max_iterations: int | None = None,
) -> CycleSchedulerRun:
    """Poll until `stop` is set or `max_iterations` is reached; run each due step once.

    Every iteration asks each step, in order, whether it is due and runs it
    under its own lock. A bounded invocation (`max_iterations` set) does not
    wait between iterations, exactly as `infrastructure.jobs.worker.run_worker`
    does.
    """
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    if max_iterations is not None and max_iterations < 0:
        raise ValueError("max_iterations cannot be negative")
    names = [step.name for step in steps]
    if len(set(names)) != len(names):
        raise ValueError("step names must be distinct")
    counts = {name: [0, 0, 0] for name in names}
    iterations = 0
    while not stop.is_set():
        if max_iterations is not None and iterations >= max_iterations:
            break
        iterations += 1
        for step in steps:
            _attempt(engine, step, clock=clock, log=log, counts=counts[step.name])
        if max_iterations is None:
            stop.wait(poll_seconds)
    per_step = {name: StepCounts(*values) for name, values in counts.items()}
    return CycleSchedulerRun(
        iterations=iterations,
        runs=sum(c.runs for c in per_step.values()),
        skipped=sum(c.skipped for c in per_step.values()),
        failed=sum(c.failed for c in per_step.values()),
        steps=per_step,
    )


def _attempt(
    engine: Engine,
    step: SchedulerStep,
    *,
    clock: Callable[[], datetime],
    log: Log,
    counts: list[int],
) -> None:
    """One step, once: due check, its own lock, the run; counts are runs, skipped, failed."""
    now = clock()
    context = step.due(now)
    if context is None:
        return
    try:
        with single_flight(engine, key=step.lock_key) as held:
            if not held:
                counts[1] += 1
                log({"event": f"{step.event}.skipped", **context, "reason": "lock_held"})
            elif step.run(now, context):
                counts[0] += 1
            else:
                counts[2] += 1
    except Exception:
        counts[2] += 1
        log({"event": f"{step.event}.failed", **context, "reason": "internal_error"})


def run_cycle_scheduler(
    engine: Engine,
    *,
    zone: ZoneInfo,
    run_for: RunFor,
    stop: threading.Event,
    clock: Callable[[], datetime],
    log: Log,
    poll_seconds: float = DEFAULT_CYCLE_POLL_SECONDS,
    max_iterations: int | None = None,
    lock_key: int = CYCLE_SCHEDULER_LOCK_KEY,
) -> CycleSchedulerRun:
    """The daily cycle alone: `run_scheduler_steps` over one `DailyStep`."""
    return run_scheduler_steps(
        engine,
        steps=(DailyStep(zone=zone, run_for=run_for, lock_key=lock_key),),
        stop=stop,
        clock=clock,
        log=log,
        poll_seconds=poll_seconds,
        max_iterations=max_iterations,
    )
