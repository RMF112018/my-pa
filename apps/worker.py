"""Composition root for the worker process.

    .venv/bin/python apps/worker.py run
    .venv/bin/python apps/worker.py run --once
    .venv/bin/python apps/worker.py run --max-iterations 20 --lease-seconds 60

This is the only place in the worker that chooses an implementation
(`module-boundaries.md` section 5.10): it loads validated configuration, builds
the engine, installs the signal handlers, and hands
`infrastructure.jobs.worker.run_worker` an owner and a handler. The loop itself
knows nothing about settings, signals, or standard output.

Argparse, like every other operational script here. The target is explicit —
`MY_PA_DATABASE_URL` is required and has no default (`P00-OD-008`) — and the
output is counts and states, never a row value.

**Shutdown.** `SIGINT` and `SIGTERM` set one event. The loop finishes the job it
holds and then stops, so no lease is abandoned and no partial work is committed;
a second signal is left to Python's default handling, because an operator asking
twice is asking for the process to go now and this script should not be the
thing that refuses.

**What this worker executes, and what it does not.** There is no extraction
executor to wire, so `_unexecutable` is the handler and every claimed job is
released as `unavailable` until its attempts are spent. That is a deferral
stated as one, not a stub pretending to work, and the reason is a gap this work
package does not own: `sources.enroll` records the `obj_…` identifiers a
*provider instance* minted, and `FixtureSourceProvider` documents that those
live only as long as the instance and are never derived from a locator, while
`persistence.extraction` will only record an outcome against a `source_objects`
row that `observe_object` issued from a native locator. Nothing in the tree
bridges the two — `register_source` and `observe_object` have no production
caller at all — so an executor written here would have to invent that bridge,
which is a source-registration and enumeration design rather than a lease loop.
Releasing as `unavailable` records what is actually known, which is the same
answer and the same code `reap_abandoned_jobs` writes for a worker that stopped
being available before it reported anything.

In practice this worker finds no work: nothing registers a source, so nothing
can enroll one, so nothing enqueues a job. The handler is what happens if
something does, and it is bounded — three attempts and the job is terminal
`failed` rather than retried forever.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from types import FrameType

from sqlalchemy import Connection

from my_pa.bootstrap.settings import load_settings
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.jobs.worker import (
    DEFAULT_LEASE_SECONDS,
    DEFAULT_POLL_SECONDS,
    JobExecutionError,
    WorkerRun,
    issue_worker_owner,
    run_worker,
)
from my_pa.infrastructure.persistence.jobs import LeasedJob

#: The signals an operator stops this process with. `SIGHUP` is deliberately
#: absent: it has no defined meaning for this process, and claiming one would be
#: inventing an operational contract nothing asked for.
_STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM)


def _unexecutable(connection: Connection, job: LeasedJob) -> None:
    """Refuse the job truthfully: no executor is wired to perform it.

    Named and raised rather than quietly completed. Completing would write
    `succeeded` for work nobody did, which `sources.status` would then report as
    `complete_for_scope` — a claim about a bounded scope that was never
    processed. See this module's docstring for what is missing and why building
    it is a different work package.
    """
    raise JobExecutionError(ErrorCode.UNAVAILABLE)


def _install_stop_handlers(stop: threading.Event) -> None:
    """Make `SIGINT` and `SIGTERM` request a clean stop, once each."""

    def _request_stop(number: int, frame: FrameType | None) -> None:
        stop.set()
        # Restore the default so a second signal is not swallowed by a process
        # that is already trying to finish.
        signal.signal(number, signal.SIG_DFL)

    for number in _STOP_SIGNALS:
        signal.signal(number, _request_stop)


#: What this process will do with work it claims, said by the process itself.
#: The docstring above, the runbook, and `README.md` all disclose it, and none of
#: them is what an operator reads when a run prints `idle 1`: without this line,
#: "no executor is wired" and "healthy worker, empty queue" are the same output.
#: A printed sentence is the whole of it — there is no status mechanism here.
_NO_EXECUTOR_NOTICE = (
    "notice      no extraction executor is wired; claimed work is released as "
    "'unavailable' and fails once its attempts are spent"
)


def _report(owner: str, run: WorkerRun) -> None:
    """Print what the run did. Counts, an owner token, and nothing else."""
    print(f"owner        {owner}")
    print(f"iterations   {run.iterations}")
    print(f"claimed      {run.claimed}")
    print(f"completed    {run.completed}")
    print(f"released     {run.released}")
    print(f"lost         {run.lost}")
    print(f"idle         {run.idle}")


def _run(args: argparse.Namespace) -> int:
    settings = load_settings()
    engine = create_database_engine(settings.database_url)
    owner = issue_worker_owner()
    stop = threading.Event()
    _install_stop_handlers(stop)
    # Said at startup rather than in the summary, because a worker running until
    # it is signalled prints its summary only when it stops.
    print(_NO_EXECUTOR_NOTICE, flush=True)
    try:
        run = run_worker(
            engine,
            owner=owner,
            handler=_unexecutable,
            stop=stop,
            max_iterations=1 if args.once else args.max_iterations,
            lease_seconds=args.lease_seconds,
            poll_seconds=args.poll_seconds,
        )
    finally:
        engine.dispose()
    _report(owner, run)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the my-pa worker.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run", help="claim and execute queued work")
    bound = run.add_mutually_exclusive_group()
    bound.add_argument("--once", action="store_true", help="do at most one iteration and exit")
    bound.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="stop after this many iterations; omit to run until signalled",
    )
    run.add_argument("--lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS)
    run.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse and dispatch.

    Dispatched by name rather than through a callable stored on the namespace,
    so that adding a subcommand without wiring it is a `match` that does not
    compile rather than an `AttributeError` at run time.
    """
    args = build_parser().parse_args(argv)
    match args.command:
        case "run":
            return _run(args)
        case unknown:  # pragma: no cover - argparse rejects an unknown command first
            raise SystemExit(f"unhandled command {unknown!r}")


if __name__ == "__main__":
    sys.exit(main())
