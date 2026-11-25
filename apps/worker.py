"""Composition root for the worker process.

    .venv/bin/python apps/worker.py run
    .venv/bin/python apps/worker.py run --once
    .venv/bin/python apps/worker.py run --plane capture
    .venv/bin/python apps/worker.py run --plane reenrichment
    .venv/bin/python apps/worker.py run --plane schedule
    .venv/bin/python apps/worker.py run --plane cycles
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
named by `--plane`; `_PLANES` is the closed set of names and is what `--plane`'s
`choices` are derived from, so a plane cannot exist that the flag will not
accept.

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
* `reenrichment` runs `infrastructure.jobs.reenrichment.run_reenrichment_worker`
  (`WP-03` / `RI-P3-BLK-001`). One claimed item is one durable Relationship
  Intelligence invalidation: the binding's exact subject, input, producer and
  policy versions are re-read and locked, and the item is applied only if none
  of them has moved since it was registered. What it applies is a deterministic
  re-resolution of mention/identity linkage against the corrected identity
  graph. **It reads no source, opens no socket and calls no model either**, and
  it settles `partial` rather than `succeeded` whenever it left something
  undone. Before this plane existed the claim-and-settle primitive had no caller
  anywhere in the repository and no durable work was ever executed.
* `schedule` runs `infrastructure.jobs.schedule.process_schedule_publication`
  (CPM Workbench S5b-2, worker and capabilities contract sections 3.2-3.4). One
  claimed job is one admitted schedule publication: the pinned source version is
  read through its provider, and the PDF is parsed **only** by the isolated,
  rlimit-bounded child process (`infrastructure.jobs.schedule_parser_child`) --
  this process never loads PDFium. Rows, issues, canonicalization and
  finalization are written in short lease-checked transactions within a 240 s
  budget. The plane is refused (exit 2, before an engine is built) unless
  `MY_PA_SCHEDULE_ENABLED` is on, and with a `--lease-seconds` below 300, which
  is the budget plus the parse reserve. Schedule Scenarios S6-3: the job handler
  is bound with `scenario_plane_effective` -- both `MY_PA_SCHEDULE_ENABLED` and
  `MY_PA_SCHEDULE_SCENARIOS_ENABLED` on -- so the intake series-match hook admits
  a decided match only while the plane is effective. Generic PDF extraction on the
  `enrollment` plane stays `unsupported`.

* `cycles` runs the cycles-plane steps (`infrastructure.jobs.cycle_scheduler`,
  ADR-010 amendment of 2026-11-20; communications contract section 19). It
  claims no job: it polls the clock and runs each step that is due, each under
  its own session advisory lock, so two `cycles` processes never run the same
  step together and a busy step never holds up the other. Two steps, each with
  its own switch:

  - the daily Morning Intelligence cycle (`MY_PA_CYCLE_SCHEDULER_ENABLED`):
    once per local date in `MY_PA_CYCLE_SCHEDULER_TIMEZONE` (at local
    midnight, or at once on start) it closes the operator Principal's stale
    open cycles and begins the date's cycle through `ApplicationService.invoke`
    (`application.daily_cycle`);
  - the communications ingestion poll (`MY_PA_COMMUNICATIONS_INGEST_ENABLED`):
    every `MY_PA_COMMUNICATIONS_INGEST_POLL_SECONDS` (default 900, and at once
    on start) one stability-gated `IngestionLifecycle.poll_enabled` over every
    enabled ingest source of the operator Principal. The lifecycle is built
    once and lives as long as the process, so its in-process stability memory
    (two consecutive polls with the same size and version token) survives
    between polls. After each poll the staged `meeting_sync_v1` publications
    are applied (`MeetingSyncApplier.apply_pending`, WP3b-S3) under the same
    step lock, once the reconciliation latch exists, with a second
    counts-only line (`meeting_sync.apply`). The workspace stores are composed from
    `MY_PA_FILES_WORKSPACES` at start; a misconfigured root refuses the plane
    (exit 2, `plane cycles workspace_misconfigured`);
  - the project-reports ingestion poll (`MY_PA_PROJECT_REPORTS_INGEST_ENABLED`,
    WP3P ruling D5): every `MY_PA_PROJECT_REPORTS_INGEST_POLL_SECONDS`
    (default 900, and at once on start), under its own lock
    (`PROJECT_REPORTS_POLL_LOCK_KEY`, the one `bindings apply` takes), one
    stability-gated poll of every enabled project-report source over the
    project-reports lifecycle (`bootstrap.project_reports`), then the bounded
    re-derivation sweep (ruling D9), with two counts-only lines
    (`project_reports_ingest.run`, `project_reports.rederive`). Its workspace
    stores are composed eagerly, as for the communications poll.

  With every switch off the plane is refused (exit 2, `plane cycles
  disabled`, before an engine is built). It prints one JSON line per run,
  codes and counts only; `--lease-seconds` does not apply to it.

Three planes and one loop for the job planes: `run_worker` is parameterised over
the plane (`D-76`, `D-77`), so the lease protocol has one implementation and
three tables it runs against. The `reenrichment` plane is **not** on that loop, and the reason
is in the table rather than in a preference: `entity_reenrichment_work` is
deliberately not a `JobPlane` -- it carries its own lease columns, its own
`next_attempt_at`, a terminal vocabulary that includes `partial` and `stale`,
and a version-currency fence no job plane has. Parameterising `run_worker` over
a second lease protocol would have made one function mean two things, so the
re-enrichment loop is its own small one in `infrastructure.jobs.reenrichment`
and this file dispatches to whichever the chosen plane names. Running more than
one plane means running the command more than once.

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
import functools
import json
import signal
import sys
import threading
from collections.abc import Mapping
from datetime import date
from types import FrameType, MappingProxyType
from zoneinfo import ZoneInfo

from sqlalchemy import select

from my_pa.application.capture_lifecycle import always_eligible
from my_pa.application.daily_cycle import DailyCycleRunner
from my_pa.application.ingestion import IngestionLifecycle, IngestRunReport
from my_pa.application.meeting_sync_apply import MeetingSyncApplier, MeetingSyncApplyReport
from my_pa.application.project_reports_rederive import ProjectReportsRederiver, RederiveReport
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.communications_ingest import ingestion_lifecycle, meeting_sync_applier
from my_pa.bootstrap.gateway import local_principal
from my_pa.bootstrap.project_reports import project_reports_lifecycle, rederiver
from my_pa.bootstrap.settings import AuthMode, load_settings
from my_pa.contracts.ports import FileWorkspaceRootError, IngestRunOutcome
from my_pa.domain.common.time import utc_now
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.jobs.capture_pipeline import (
    configure_processing_eligibility,
    process_capture_version,
)
from my_pa.infrastructure.jobs.cycle_scheduler import (
    COMMS_INGEST_LOCK_KEY,
    DEFAULT_CYCLE_POLL_SECONDS,
    PROJECT_REPORTS_POLL_LOCK_KEY,
    CycleSchedulerRun,
    DailyStep,
    IntervalStep,
    SchedulerStep,
    run_scheduler_steps,
)
from my_pa.infrastructure.jobs.extraction import extract_enrollment
from my_pa.infrastructure.jobs.reenrichment import (
    DEFAULT_REENRICHMENT_POLL_SECONDS,
    ReenrichmentRun,
    run_reenrichment_worker,
)
from my_pa.infrastructure.jobs.schedule import (
    SCHEDULE_MIN_LEASE_SECONDS,
    process_schedule_publication,
)
from my_pa.infrastructure.jobs.worker import (
    DEFAULT_LEASE_SECONDS,
    DEFAULT_POLL_SECONDS,
    JobHandler,
    WorkerRun,
    issue_worker_owner,
    run_worker,
)
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.jobs import (
    CAPTURE_JOBS,
    ENROLLMENT_JOBS,
    SCHEDULE_JOBS,
    JobPlane,
)
from my_pa.infrastructure.persistence.tables import JobState, entity_reenrichment_work
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from my_pa.infrastructure.persistence.worker_health import record_worker_heartbeat

configure_processing_eligibility(always_eligible)

#: The three *job* planes this process can serve, and the handler each one's work
#: needs. A mapping rather than an `if`, so that a plane cannot be added without
#: `--plane`'s `choices` learning about it. The handler travels with the plane
#: because the pairing is not a preference: a `capver_…` claimed off
#: `knowledge.jobs` would be a subject of the wrong kind, and
#: `JobPlane.subject_kind` is what refuses one.
_JOB_PLANES: Mapping[str, tuple[JobPlane, JobHandler]] = MappingProxyType(
    {
        "enrollment": (ENROLLMENT_JOBS, extract_enrollment),
        "capture": (CAPTURE_JOBS, process_capture_version),
        # CPM Workbench S5b-2 (contract section 3.2, surface 1).
        "schedule": (SCHEDULE_JOBS, process_schedule_publication),
    }
)

#: Every plane `--plane` accepts, which is the three above plus `reenrichment`.
#: That one is named here and not in `_JOB_PLANES` because it does not
#: claim off a `JobPlane` at all -- see the module docstring -- and putting it in
#: that mapping would have required a `JobPlane` for a table that deliberately
#: is not one. `sorted(_PLANES)` is still the single source of `--plane`'s
#: choices, so the two cannot disagree.
_PLANES: frozenset[str] = frozenset({*_JOB_PLANES, "reenrichment", "cycles"})

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
    print(f"paused       {run.paused}")
    print(f"idle         {run.idle}")


def _report_reenrichment(owner: str, run: ReenrichmentRun) -> None:
    """The re-enrichment plane's own counts.

    A separate function rather than a shared one, because the two runs do not
    settle in the same vocabulary and printing them under one set of headings
    would have to call a `partial` settlement either `completed` or `released`.
    `partial` and `stale` are the two an operator most needs to see, so they get
    their own lines.
    """
    print(f"owner        {owner}")
    print("plane        reenrichment")
    print(f"iterations   {run.iterations}")
    print(f"claimed      {run.claimed}")
    print(f"succeeded    {run.succeeded}")
    print(f"partial      {run.partial}")
    print(f"stale        {run.stale}")
    print(f"failed       {run.failed}")
    print(f"idle         {run.idle}")
    print(f"rebound      {run.rebound}")


def _run_reenrichment(args: argparse.Namespace) -> int:
    """Serve the re-enrichment plane. Same process, same signals, own loop.

    The heartbeat is the same content-free row the other two planes write and
    `worker_health.record_worker_heartbeat` already admits `reenrichment` as a
    plane. It differs in where it finds the Principals to report for: there is
    no `JobPlane.table` to select from, so the outstanding partition comes from
    `entity_reenrichment_work` itself.

    `poll_seconds` has its own default because it belongs to a different loop;
    `--poll-seconds` still overrides it, so an operator sets one flag either
    way.
    """
    settings = load_settings()
    engine = create_database_engine(settings.parsed_database_url(), statement_timeout_ms=30_000)
    owner = issue_worker_owner()
    stop = threading.Event()
    _install_stop_handlers(stop)
    principal_id = (
        local_principal().principal_id if settings.auth_mode is AuthMode.LOCAL_OPERATOR else None
    )
    heartbeat_principals: set[str] = {principal_id} if principal_id is not None else set()

    def heartbeat(*, stopped: bool = False) -> None:
        with engine.begin() as connection:
            if not stopped:
                heartbeat_principals.update(
                    str(value)
                    for value in connection.scalars(
                        select(entity_reenrichment_work.c.principal_id)
                        .where(entity_reenrichment_work.c.state.in_(["queued", "running"]))
                        .distinct()
                    )
                )
            for heartbeat_principal in heartbeat_principals:
                record_worker_heartbeat(
                    connection,
                    owner=owner,
                    principal_id=heartbeat_principal,
                    plane="reenrichment",
                    stopped=stopped,
                )

    try:
        heartbeat()
        run = run_reenrichment_worker(
            engine,
            owner=owner,
            stop=stop,
            max_iterations=1 if args.once else args.max_iterations,
            lease_seconds=args.lease_seconds,
            poll_seconds=(
                DEFAULT_REENRICHMENT_POLL_SECONDS
                if args.poll_seconds == DEFAULT_POLL_SECONDS
                else args.poll_seconds
            ),
            heartbeat=heartbeat,
        )
    finally:
        heartbeat(stopped=True)
        engine.dispose()
    _report_reenrichment(owner, run)
    return 0


def _log_line(fields: object) -> None:
    """One structured log line on standard output. Identifiers, counts and codes only."""
    print(json.dumps(fields, sort_keys=True, default=str), flush=True)


def _report_cycles(run: CycleSchedulerRun) -> None:
    print("plane        cycles")
    print(f"iterations   {run.iterations}")
    print(f"runs         {run.runs}")
    print(f"skipped      {run.skipped}")
    print(f"failed       {run.failed}")
    for name, counts in run.steps.items():
        print(f"step         {name} runs={counts.runs}", end="")
        print(f" skipped={counts.skipped} failed={counts.failed}")


def comms_ingest_log_fields(reports: tuple[IngestRunReport, ...]) -> dict[str, object]:
    """The poll step's one log line: outcomes and summed counts, never a path or id."""
    outcomes: dict[str, int] = {}
    counts: dict[str, int] = {}
    for report in reports:
        outcomes[report.outcome.value] = outcomes.get(report.outcome.value, 0) + 1
        for key, value in report.counts.items():
            counts[key] = counts.get(key, 0) + value
    return {
        "event": "comms_ingest.run",
        "sources": len(reports),
        "outcomes": dict(sorted(outcomes.items())),
        "counts": dict(sorted(counts.items())),
    }


def meeting_sync_apply_log_fields(report: MeetingSyncApplyReport) -> dict[str, object]:
    """The applier's one log line after a poll: closed count names, never an id."""
    return {"event": "meeting_sync.apply", "counts": dict(sorted(report.counts.items()))}


def _comms_ingest_step(
    lifecycle: IngestionLifecycle,
    applier: MeetingSyncApplier,
    principal_id: str,
    seconds: int,
) -> IntervalStep:
    """The ingestion poll step over one long-lived lifecycle (its stability memory).

    After the poll, the staged meeting-sync publications are applied (WP3b-S3,
    ruling D1), under the same step lock; nothing applies before the latch.
    """

    def poll() -> bool:
        reports = lifecycle.poll_enabled(principal_id)
        _log_line(comms_ingest_log_fields(reports))
        applied = applier.apply_pending(principal_id)
        _log_line(meeting_sync_apply_log_fields(applied))
        return all(
            report.outcome is not IngestRunOutcome.FAILED for report in reports
        ) and not applied.counts.get("publications_failed")

    return IntervalStep(
        name="comms_ingest",
        event="comms_ingest",
        lock_key=COMMS_INGEST_LOCK_KEY,
        interval_seconds=seconds,
        run_once=poll,
    )


def project_reports_ingest_log_fields(reports: tuple[IngestRunReport, ...]) -> dict[str, object]:
    """The project-reports poll's line: outcomes and summed counts, never a path or id."""
    fields = comms_ingest_log_fields(reports)
    fields["event"] = "project_reports_ingest.run"
    return fields


def project_reports_rederive_log_fields(report: RederiveReport) -> dict[str, object]:
    """The re-derivation sweep's line after a poll: closed count names, never an id."""
    return {"event": "project_reports.rederive", "counts": dict(sorted(report.counts.items()))}


def _project_reports_step(
    lifecycle: IngestionLifecycle,
    sweep: ProjectReportsRederiver,
    principal_id: str,
    seconds: int,
) -> IntervalStep:
    """The project-reports poll step (ruling D5), then the re-derivation sweep (D9).

    One long-lived lifecycle (its stability memory) and one lock, the
    project-reports poll lock, for both; a failed run or a failed re-derivation
    fails the step.
    """

    def poll() -> bool:
        reports = lifecycle.poll_enabled(principal_id)
        _log_line(project_reports_ingest_log_fields(reports))
        swept = sweep.sweep(principal_id)
        _log_line(project_reports_rederive_log_fields(swept))
        return all(
            report.outcome is not IngestRunOutcome.FAILED for report in reports
        ) and not swept.counts.get("derivations_failed")

    return IntervalStep(
        name="project_reports_ingest",
        event="project_reports_ingest",
        lock_key=PROJECT_REPORTS_POLL_LOCK_KEY,
        interval_seconds=seconds,
        run_once=poll,
    )


def _run_cycles(args: argparse.Namespace) -> int:
    """Serve the cycles-plane steps (ADR-010 amendment; communications contract 19).

    Refused before an engine is built unless `MY_PA_CYCLE_SCHEDULER_ENABLED`,
    `MY_PA_COMMUNICATIONS_INGEST_ENABLED` or `MY_PA_PROJECT_REPORTS_INGEST_ENABLED`
    is on. The Principal is the fixed
    local operator (`local_principal`): every remote OAuth client row is
    constrained to it, so it owns ChatLLM's cycles and the ingested
    communications. The daily begin step goes through a minimal
    `ApplicationService` -- the default composition already serves
    `reports.begin_cycle` -- with the audit sink on its own engine, as the
    gateway composes it. The ingestion poll writes no audit row
    (`bootstrap.communications_ingest`).
    """
    settings = load_settings()
    if not (
        settings.cycle_scheduler_enabled
        or settings.communications_ingest_enabled
        or settings.project_reports_ingest_enabled
    ):
        print("plane cycles disabled")
        return 2
    engine = create_database_engine(settings.parsed_database_url(), statement_timeout_ms=30_000)
    engines = [engine]
    steps: list[SchedulerStep] = []
    try:
        if settings.cycle_scheduler_enabled:
            audit_engine = create_database_engine(
                settings.parsed_database_url(), statement_timeout_ms=30_000
            )
            engines.append(audit_engine)
            audit = SqlAlchemyAuditSink(audit_engine)

            def unit_of_work() -> SqlAlchemyUnitOfWork:
                return SqlAlchemyUnitOfWork(engine, audit=audit)

            runner = DailyCycleRunner(
                service=ApplicationService(
                    unit_of_work=unit_of_work, limits=settings.effective_limits()
                ),
                unit_of_work=unit_of_work,
                principal=local_principal(),
                clock=utc_now,
            )

            def run_for(business_date: date) -> bool:
                outcome = runner(business_date)
                _log_line(outcome.log_fields())
                return outcome.begun

            steps.append(
                DailyStep(zone=ZoneInfo(settings.cycle_scheduler_timezone), run_for=run_for)
            )
        if settings.communications_ingest_enabled:
            try:
                lifecycle = ingestion_lifecycle(settings, engine, eager=True)
            except FileWorkspaceRootError:
                print("plane cycles workspace_misconfigured")
                return 2
            steps.append(
                _comms_ingest_step(
                    lifecycle,
                    meeting_sync_applier(engine),
                    local_principal().principal_id,
                    settings.communications_ingest_poll_seconds,
                )
            )
        if settings.project_reports_ingest_enabled:
            try:
                reports_lifecycle = project_reports_lifecycle(settings, engine, eager=True)
            except FileWorkspaceRootError:
                print("plane cycles workspace_misconfigured")
                return 2
            steps.append(
                _project_reports_step(
                    reports_lifecycle,
                    rederiver(engine),
                    local_principal().principal_id,
                    settings.project_reports_ingest_poll_seconds,
                )
            )
        stop = threading.Event()
        _install_stop_handlers(stop)
        run = run_scheduler_steps(
            engine,
            steps=steps,
            stop=stop,
            clock=utc_now,
            log=_log_line,
            poll_seconds=(
                DEFAULT_CYCLE_POLL_SECONDS
                if args.poll_seconds == DEFAULT_POLL_SECONDS
                else args.poll_seconds
            ),
            max_iterations=1 if args.once else args.max_iterations,
        )
    finally:
        for built in engines:
            built.dispose()
    _report_cycles(run)
    return 0


def _schedule_refusal(args: argparse.Namespace, *, schedule_enabled: bool) -> str | None:
    """Why the `schedule` plane may not run in this process, or `None`.

    CPM Workbench S5b-2 contract sections 3.1 and 3.2: the plane is off unless
    `MY_PA_SCHEDULE_ENABLED` is on, and its lease must outlast the handler's
    240 s budget plus the 60 s parse reserve, because the handler cannot extend
    a lease. Decided before an engine is built, a job is claimed or a heartbeat
    is written; the message names the reason and nothing else.
    """
    if args.plane != "schedule":
        return None
    if not schedule_enabled:
        return "plane schedule disabled"
    if args.lease_seconds < SCHEDULE_MIN_LEASE_SECONDS:
        return f"plane schedule requires --lease-seconds >= {SCHEDULE_MIN_LEASE_SECONDS}"
    return None


def _run(args: argparse.Namespace) -> int:
    if args.plane == "reenrichment":
        return _run_reenrichment(args)
    if args.plane == "cycles":
        return _run_cycles(args)
    settings = load_settings()
    refusal = _schedule_refusal(args, schedule_enabled=settings.schedule_enabled)
    if refusal is not None:
        print(refusal)
        return 2
    engine = create_database_engine(settings.parsed_database_url(), statement_timeout_ms=30_000)
    plane, handler = _JOB_PLANES[args.plane]
    if args.plane == "schedule":
        # Schedule Scenarios S6-3 (contract section 15.8, S6-2-D12): the
        # series-match hook admits a decided match only while the plane is
        # effective; the scenario switch alone never starts a worker.
        handler = functools.partial(
            process_schedule_publication,
            scenario_plane_effective=(
                settings.schedule_enabled and settings.schedule_scenarios_enabled
            ),
        )
    owner = issue_worker_owner()
    stop = threading.Event()
    _install_stop_handlers(stop)
    # Local/synthetic operation intentionally remains one partition. Entra mode
    # consumes the Principal already stamped on each queued row; no command-line
    # flag or request is allowed to name a Principal.
    principal_id = (
        local_principal().principal_id if settings.auth_mode is AuthMode.LOCAL_OPERATOR else None
    )
    heartbeat_principals: set[str] = {principal_id} if principal_id is not None else set()

    def heartbeat(*, stopped: bool = False) -> None:
        with engine.begin() as connection:
            if not stopped:
                heartbeat_principals.update(
                    str(value)
                    for value in connection.scalars(
                        select(plane.table.c.principal_id)
                        .where(
                            plane.table.c.state.in_([JobState.QUEUED.value, JobState.RUNNING.value])
                        )
                        .distinct()
                    )
                )
            for heartbeat_principal in heartbeat_principals:
                record_worker_heartbeat(
                    connection,
                    owner=owner,
                    principal_id=heartbeat_principal,
                    plane=args.plane,
                    stopped=stopped,
                )

    try:
        heartbeat()
        run = run_worker(
            engine,
            owner=owner,
            handler=handler,
            stop=stop,
            # Local mode is fixed to the process Principal. Entra mode is the
            # trusted global consumer described above; either way there is no
            # caller-controlled Principal argument.
            principal_id=principal_id,
            plane=plane,
            max_iterations=1 if args.once else args.max_iterations,
            lease_seconds=args.lease_seconds,
            poll_seconds=args.poll_seconds,
            heartbeat=heartbeat,
        )
    finally:
        heartbeat(stopped=True)
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
