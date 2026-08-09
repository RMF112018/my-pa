"""Composition root for the worker process.

    .venv/bin/python apps/worker.py run
    .venv/bin/python apps/worker.py run --once
    .venv/bin/python apps/worker.py run --plane capture
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
holds and then stops, so no lease is abandoned and nothing is left `running` for
another worker to wait out; a second signal is left to Python's default handling,
because an operator asking twice is asking for the process to go now and this
script should not be the thing that refuses.

**What this worker executes, and on which plane.** One process serves one plane,
named by `--plane`, and each plane's handler travels with it in `_PLANES`.

* `enrollment` (the default) runs `infrastructure.jobs.extraction.extract_enrollment`.
  One claimed job is one enrollment's outstanding objects: for each, the provider
  its source is configured with is asked to describe and read it,
  `domain.extraction.text` decides what came back, and the outcome is stored.
  Work commits per object, so a worker that is killed or loses its lease part-way
  leaves the objects it had already recorded and the next attempt starts from the
  ones that have no outcome yet.
* `capture` runs `infrastructure.jobs.capture_pipeline.process_capture_version`.
  One claimed job is one stored capture version, and the nine stages run over it
  in their own transactions — validate, normalize, detect language, segment,
  match deterministically, normalize moments, confirm the text is searchable,
  derive work-object proposals, and persist them with the spans they cite. **It
  reads no source, opens no socket, and calls no model.** Everything it works
  from is text already in the database, which is why WP-7 needed no new
  configuration and no new credential.

Two planes and one loop: `run_worker` is parameterised over the plane
(`D-76`, `D-77`), so the lease protocol has one implementation and two tables it
runs against. Running both planes means running the command twice.

**What it still does not do, stated rather than left as an absence.** PDFs are
recorded as `unsupported` and counted; nothing here extracts them, because
`P00-OD-003` is an open operator decision. An object whose bytes changed after it
was extracted keeps its stored text and its old version — reprocessing is an
explicit new operation and there is no scheduler for it. And a job whose
enrollment is enormous can still exhaust its three attempts before it finishes,
in which case it lands terminal `failed` with the coverage it did achieve, which
`sources.status` reports honestly as partial.

This worker finds work only where an operator has both registered a source
(`apps/cli/sources.py`) and enrolled part of it (`sources.enroll`); with neither,
it idles, and the counts it prints say so.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from collections.abc import Mapping
from types import FrameType, MappingProxyType

from my_pa.bootstrap.settings import load_settings
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.jobs.capture_pipeline import process_capture_version
from my_pa.infrastructure.jobs.extraction import extract_enrollment
from my_pa.infrastructure.jobs.worker import (
    DEFAULT_LEASE_SECONDS,
    DEFAULT_POLL_SECONDS,
    JobHandler,
    WorkerRun,
    issue_worker_owner,
    run_worker,
)
from my_pa.infrastructure.persistence.jobs import CAPTURE_JOBS, ENROLLMENT_JOBS, JobPlane

#: The two planes this process can serve, and the handler each one's work needs.
#: A mapping rather than an `if`, so that a third plane arrives as a row here and
#: `--plane`'s `choices` cannot disagree with what `_run` can dispatch. The
#: handler travels with the plane because the pairing is not a preference: a
#: `capver_…` claimed off `knowledge.jobs` would be a subject of the wrong kind,
#: and `JobPlane.subject_kind` is what refuses one.
_PLANES: Mapping[str, tuple[JobPlane, JobHandler]] = MappingProxyType(
    {
        "enrollment": (ENROLLMENT_JOBS, extract_enrollment),
        "capture": (CAPTURE_JOBS, process_capture_version),
    }
)

#: The signals an operator stops this process with. `SIGHUP` is deliberately
#: absent: it has no defined meaning for this process, and claiming one would be
#: inventing an operational contract nothing asked for.
_STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM)


def _install_stop_handlers(stop: threading.Event) -> None:
    """Make `SIGINT` and `SIGTERM` request a clean stop, once each."""

    def _request_stop(number: int, frame: FrameType | None) -> None:
        stop.set()
        # Restore the default so a second signal is not swallowed by a process
        # that is already trying to finish.
        signal.signal(number, signal.SIG_DFL)

    for number in _STOP_SIGNALS:
        signal.signal(number, _request_stop)


def _report(owner: str, plane: str, run: WorkerRun) -> None:
    """Print what the run did. Counts, an owner token, and nothing else."""
    print(f"owner        {owner}")
    print(f"plane        {plane}")
    print(f"iterations   {run.iterations}")
    print(f"claimed      {run.claimed}")
    print(f"completed    {run.completed}")
    print(f"released     {run.released}")
    print(f"lost         {run.lost}")
    print(f"idle         {run.idle}")


def _run(args: argparse.Namespace) -> int:
    settings = load_settings()
    engine = create_database_engine(settings.parsed_database_url())
    plane, handler = _PLANES[args.plane]
    owner = issue_worker_owner()
    stop = threading.Event()
    _install_stop_handlers(stop)
    try:
        run = run_worker(
            engine,
            owner=owner,
            handler=handler,
            stop=stop,
            plane=plane,
            max_iterations=1 if args.once else args.max_iterations,
            lease_seconds=args.lease_seconds,
            poll_seconds=args.poll_seconds,
        )
    finally:
        engine.dispose()
    _report(owner, args.plane, run)
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
    run.add_argument(
        "--plane",
        choices=sorted(_PLANES),
        default="enrollment",
        help="which job plane to claim from; one process serves one plane",
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
