"""The daily cycle scheduler's loop: poll, and when a run is due, run it once.

ADR-010 amendment of 2026-11-20, served as `apps/worker.py run --plane cycles`.
This module owns *when* and *single flight*; what a run does is composed by the
entry point and handed in as `run_for` (it lives in `application.daily_cycle`,
which infrastructure may not import).

**Due.** `domain.intelligence.daily_cycle.due` on the injected clock. The last
run date is this process's memory, not a stored value: a process that starts
runs at once for the current local date, which is the catch-up rule (one run
for the latest missed date, never a backfill), and every step is idempotent, so
running again after a restart writes nothing new.

**Single flight.** A run holds a PostgreSQL *session* advisory lock on its own
connection for the whole run. `pg_try_advisory_lock` does not wait: a second
worker that cannot take it skips this attempt and tries again on its next poll,
by which time the date's run has completed and its own run replays.

**Bounded and never fatal.** A run that raises is counted and logged as a code,
and the date stays due, so the next poll retries it. Only a completed begin step
(`run_for` answering True) advances the last run date.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, func, select

from my_pa.domain.intelligence.daily_cycle import due

__all__ = [
    "CYCLE_SCHEDULER_LOCK_KEY",
    "DEFAULT_CYCLE_POLL_SECONDS",
    "CycleSchedulerRun",
    "run_cycle_scheduler",
    "single_flight",
]

#: How often an idle scheduler looks at the clock. A minute late at midnight is
#: immaterial, and the wait is on the stop event, so a signal does not wait it out.
DEFAULT_CYCLE_POLL_SECONDS: Final = 60.0

#: The session advisory-lock key every scheduler process contends for.
CYCLE_SCHEDULER_LOCK_KEY: Final = int.from_bytes(
    hashlib.sha256(b"my-pa-daily-cycle-scheduler").digest()[:8], byteorder="big", signed=True
)

type RunFor = Callable[[date], bool]
type Log = Callable[[Mapping[str, object]], None]


@dataclass(frozen=True, slots=True)
class CycleSchedulerRun:
    """What one loop did. Counts only."""

    iterations: int = 0
    runs: int = 0
    skipped: int = 0
    failed: int = 0


@contextmanager
def single_flight(engine: Engine, *, key: int = CYCLE_SCHEDULER_LOCK_KEY) -> Iterator[bool]:
    """Yield True while this process holds the scheduler lock, False if another does."""
    with engine.connect() as connection:
        held = bool(connection.execute(select(func.pg_try_advisory_lock(key))).scalar_one())
        connection.commit()
        try:
            yield held
        finally:
            if held:
                connection.execute(select(func.pg_advisory_unlock(key))).scalar_one()
                connection.commit()


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
    """Poll until `stop` is set or `max_iterations` is reached; run each due date once.

    A bounded invocation (`max_iterations` set) does not wait between
    iterations, exactly as `infrastructure.jobs.worker.run_worker` does.
    """
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    if max_iterations is not None and max_iterations < 0:
        raise ValueError("max_iterations cannot be negative")
    last_run: date | None = None
    iterations = runs = skipped = failed = 0
    while not stop.is_set():
        if max_iterations is not None and iterations >= max_iterations:
            break
        iterations += 1
        business_date = due(clock(), zone=zone, last_run=last_run)
        if business_date is not None:
            try:
                with single_flight(engine, key=lock_key) as held:
                    if not held:
                        skipped += 1
                        log(
                            {
                                "event": "cycle_scheduler.skipped",
                                "business_date": business_date.isoformat(),
                                "reason": "lock_held",
                            }
                        )
                    elif run_for(business_date):
                        runs += 1
                        last_run = business_date
                    else:
                        failed += 1
            except Exception:
                failed += 1
                log(
                    {
                        "event": "cycle_scheduler.failed",
                        "business_date": business_date.isoformat(),
                        "reason": "internal_error",
                    }
                )
        if max_iterations is None:
            stop.wait(poll_seconds)
    return CycleSchedulerRun(iterations=iterations, runs=runs, skipped=skipped, failed=failed)
