"""The schedule import handler: one claimed `schedule_jobs` row, one publication.

Contract: `docs/architecture/cpm-workbench-worker-capabilities-contract.md`
section 3.3 (R2 sections 22, 24 and 25). `process_schedule_publication` is a
`JobHandler`: it receives the engine, the lease and the owner, and drives the
S5b-1 repository methods through the R2 section 24 phases, each in its own
short `SqlAlchemyScheduleUnitOfWork` transaction whose first statement holds
the lease:

- H1 plan (`begin_processing`); a terminal publication returns at once.
- H2 the provider read, on an `AUTOCOMMIT` connection with **no** database
  transaction around the bytes; the pinned source version is rechecked after
  `metadata` and after `fetch`.
- H3 `pin_document`.
- H4 the parse, in the contained child (`schedule_parser_process`); no
  transaction is open.
- H5 `start_parser_run`; a `FAILED` result fails the publication with its one
  failed-ladder code.
- H6 rows, then issues, in batches of at most 1,000, then `finish_parser_run`
  -- skipped when the run returned is an already `parsed` one, whose stored
  digest must then equal the re-parse's (a determinism check, never blind
  trust); a `running` run that already holds a row or an issue is an invariant
  breach and is not resumed.
- H7 stable canonicalization, for a `complete`/`partial` outcome.
- H8 finalization; the status is derived by the database (F9/F3).

**Series-match hook** (schedule scenarios contract section 14.8.7). H8 and
the deterministic fail path run in a `SqlAlchemyScenarioUnitOfWork`
transaction and call `finalize_intake` after the terminal update: an intake
publication's match decision commits with its terminal status, and a
deterministic hook defect commits the finalization with no decision. The
effective-plane bit is the keyword `scenario_plane_effective`, default
`False` (S6-2-D12): `apps/worker.py` passes nothing until S6-3.

**Failure classes** (contract 3.3.2). A deterministic failure fails the
publication with a safe issue code while the lease is held and returns, so the
job completes (`succeeded` means "processing finished"). A transient failure
raises `JobExecutionError` and the loop releases the attempt. A lost lease
raises `LeaseLostError` and nothing further is written. An S5b-1 integrity
refusal other than `document_changed` is an invariant breach and transient.

**Budget.** 240 s cooperative, read at every checkpoint after H1; exceeding it
fails the publication with `processing_budget_exceeded`. The parse wall is
`min(150, remaining - 60)` and never below 15 s. The 300 s minimum lease
(`apps/worker.py`) exceeds the budget by 60 s, so a provider call that returns
after the lease expired is caught by the next `hold_lease`.

The module never imports PDFium or the parser package, and it neither logs nor
prints: every outcome is a stored state or an error code.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from sqlalchemy import Connection, Engine

from my_pa.contracts.ports import (
    ScheduleIntegrityError,
    ScheduleLeaseLostError,
    ScheduleRepository,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.schedule import (
    ISSUE_SEVERITY,
    MAX_SCHEDULE_BATCH,
    MAX_SCHEDULE_SOURCE_BYTES,
    SCHEDULE_MEDIA_TYPE,
    ParsedScheduleRow,
    ScheduleFinalization,
    ScheduleIssueCode,
    ScheduleIssueSeverity,
    ScheduleLease,
    ScheduleParseIssue,
    ScheduleParseResult,
    ScheduleParserIdentity,
    ScheduleParserRun,
    ScheduleParserRunStatus,
    SchedulePublication,
    SchedulePublicationStatus,
    ScheduleRowBoundsError,
    parse_result_sha256,
)
from my_pa.domain.source.provider import (
    ProviderError,
    SourceProvider,
    VersionChangedError,
)
from my_pa.infrastructure.jobs.schedule_parser_process import (
    DeterministicFailure,
    ParsedResult,
    TransientFailure,
    run_isolated_parse,
)
from my_pa.infrastructure.jobs.worker import JobExecutionError, LeaseLostError
from my_pa.infrastructure.persistence.jobs import LeasedJob
from my_pa.infrastructure.persistence.schedule import SqlAlchemyScheduleUnitOfWork
from my_pa.infrastructure.persistence.schedule_scenarios import SqlAlchemyScenarioUnitOfWork
from my_pa.infrastructure.providers.registered import RegisteredSourceProviders

__all__ = [
    "SCHEDULE_HANDLER_BUDGET_SECONDS",
    "SCHEDULE_MIN_LEASE_SECONDS",
    "SCHEDULE_PARSE_MAX_WALL_SECONDS",
    "SCHEDULE_PARSE_MIN_WALL_SECONDS",
    "SCHEDULE_PARSE_RESERVE_SECONDS",
    "ScheduleBudget",
    "process_schedule_publication",
]

SCHEDULE_HANDLER_BUDGET_SECONDS: Final = 240
#: Kept back from the parse wall for persistence, canonicalization and finalization.
SCHEDULE_PARSE_RESERVE_SECONDS: Final = 60
SCHEDULE_PARSE_MAX_WALL_SECONDS: Final = 150
SCHEDULE_PARSE_MIN_WALL_SECONDS: Final = 15
#: `apps/worker.py` refuses a shorter lease for the schedule plane (R2 section 25).
SCHEDULE_MIN_LEASE_SECONDS: Final = 300

#: The read phase's isolation level (the `extraction.py` precedent): each
#: provider statement commits by itself, so no snapshot is open while bytes
#: are read.
_READ_PHASE_ISOLATION: Final = "AUTOCOMMIT"
_PDF_MAGIC: Final = b"%PDF-"

#: The clock the budget reads; a module seam so tests can drive it.
_clock: Callable[[], float] = time.monotonic


@dataclass(frozen=True, slots=True)
class ScheduleBudget:
    """The handler's cooperative budget, measured on a monotonic clock."""

    start: float
    seconds: float
    clock: Callable[[], float] = time.monotonic

    def remaining(self) -> float:
        return self.start + self.seconds - self.clock()


def _checkpoint(budget: ScheduleBudget, label: str) -> bool:
    """`True` when the budget is spent at checkpoint `label` (a test seam)."""
    del label
    return budget.remaining() <= 0


def _provider_for(connection: Connection, source_id: str) -> SourceProvider | None:
    """The adapter serving `source_id` (a module seam; tests serve synthetic bytes)."""
    return RegisteredSourceProviders(connection).for_source(source_id)


class _Deterministic(Exception):  # noqa: N818 - an internal control-flow signal
    """Fail the publication with `code` and return (contract 3.3.2)."""

    def __init__(self, code: ScheduleIssueCode) -> None:
        super().__init__(code.value)
        self.code = code


class _Job:
    """One attempt's fixed facts and its unit-of-work helper."""

    def __init__(
        self, engine: Engine, job: LeasedJob, owner: str, *, plane_effective: bool = False
    ) -> None:
        self.engine = engine
        #: Section 14.8.7: whether a decided match is admitted (S6-3 passes the switch).
        self.plane_effective = plane_effective
        #: The stored job row's Principal, returned by the claim (`claim_job`'s
        #: `RETURNING`), never a request value.
        self.principal = job.principal_id
        self.publication_id = job.subject_id
        self.lease = ScheduleLease(job.operation_id, owner, job.attempt)
        self.budget = ScheduleBudget(
            start=_clock(), seconds=SCHEDULE_HANDLER_BUDGET_SECONDS, clock=_clock
        )
        #: The `running` run this attempt may still fail run-scoped, or `None`.
        self.running_run_id: str | None = None

    def transaction[T](self, work: Callable[[ScheduleRepository], T]) -> T:
        with SqlAlchemyScheduleUnitOfWork(self.engine) as uow:
            return work(uow.schedules)

    def finishing[T](self, work: Callable[[ScheduleRepository], T]) -> T:
        """A terminal transaction (H8, HF): the update, then the series-match hook.

        The hook's answer is discarded: a decision is stored, and an undecided
        defect leaves none (S6-2-U10); only a transient error propagates.
        """
        with SqlAlchemyScenarioUnitOfWork(self.engine) as uow:
            done = work(uow.schedules)
            uow.scenarios.finalize_intake(
                self.principal, self.publication_id, plane_effective=self.plane_effective
            )
            return done

    def spent(self, label: str) -> bool:
        return _checkpoint(self.budget, label)

    def fail(self, code: ScheduleIssueCode) -> None:
        """HF: one error issue, the publication `failed`, the running run with it."""
        run_id = self.running_run_id
        self.finishing(
            lambda schedules: schedules.fail_publication(
                self.principal, self.publication_id, self.lease, code, run_id
            )
        )


def process_schedule_publication(
    engine: Engine, job: LeasedJob, owner: str, *, scenario_plane_effective: bool = False
) -> None:
    """Drive one schedule publication through R2 section 24 (contract 3.3).

    `scenario_plane_effective` is the series-match hook's effective-plane bit
    (schedule scenarios contract section 14.8.7, S6-2-D12); it defaults off.
    """
    attempt = _Job(engine, job, owner, plane_effective=scenario_plane_effective)
    try:
        _process(attempt)
    except ScheduleLeaseLostError:
        raise LeaseLostError(job.operation_id) from None
    except ScheduleIntegrityError:
        # An invariant breach (identity gate, status mismatch, incomplete
        # canonicalization, a run-less issue, an ordinal gap): transient, so
        # the attempt bound limits the damage. `document_changed` never gets
        # here; it is a deterministic `source_version_changed` (H3).
        raise JobExecutionError(ErrorCode.INTERNAL_ERROR) from None


def _process(attempt: _Job) -> None:
    try:
        _phases(attempt)
    except _Deterministic as outcome:
        attempt.fail(outcome.code)


def _phases(attempt: _Job) -> None:
    principal, publication_id, lease = attempt.principal, attempt.publication_id, attempt.lease
    # H1: the plan.
    plan = attempt.transaction(
        lambda schedules: schedules.begin_processing(principal, publication_id, lease)
    )
    if plan.terminal:
        return
    if plan.source_id is None or plan.max_fetch_bytes is None:
        raise ScheduleIntegrityError("plan_incomplete")
    _budget(attempt, "C1")
    # H2: the provider read, outside any transaction.
    data = _read_source(attempt, plan.publication, plan.source_id, plan.max_fetch_bytes)
    _budget(attempt, "C2")
    # H3: the pin.
    try:
        attempt.transaction(
            lambda schedules: schedules.pin_document(
                principal, publication_id, lease, hashlib.sha256(data).hexdigest(), len(data)
            )
        )
    except ScheduleIntegrityError as refusal:
        if refusal.code != "document_changed":
            raise
        raise _Deterministic(ScheduleIssueCode.SOURCE_VERSION_CHANGED) from None
    _budget(attempt, "C3")
    wall = min(
        SCHEDULE_PARSE_MAX_WALL_SECONDS,
        attempt.budget.remaining() - SCHEDULE_PARSE_RESERVE_SECONDS,
    )
    if wall < SCHEDULE_PARSE_MIN_WALL_SECONDS:
        raise _Deterministic(ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED)
    # H4: the parse, in the contained child.
    result = _parse(data, plan.publication, wall)
    _budget(attempt, "C4")
    # H5: the parser run.
    run = _start_run(attempt, result)
    if result.outcome is SchedulePublicationStatus.FAILED:
        raise _Deterministic(_failed_code(result))
    # H6: rows, issues and the run's end -- or the reused parsed run, checked.
    if run.status is ScheduleParserRunStatus.PARSED:
        if run.parse_result_sha256 != parse_result_sha256(result):
            raise ScheduleIntegrityError("reused_run_digest_mismatch")
    else:
        _store(attempt, run.parser_run_id, result)
    # H7: stable canonicalization.
    if result.outcome in (SchedulePublicationStatus.COMPLETE, SchedulePublicationStatus.PARTIAL):
        _canonicalize(attempt, run.parser_run_id)
    # H8: finalization.
    _budget(attempt, "H8")
    finalization = ScheduleFinalization(
        accepted_parser_run_id=run.parser_run_id,
        published_schedule_title=result.published_schedule_title,
        data_date=result.data_date,
        run_date=result.run_date,
    )
    attempt.finishing(
        lambda schedules: schedules.finalize_publication(
            principal, publication_id, lease, finalization
        )
    )


def _budget(attempt: _Job, label: str) -> None:
    if attempt.spent(label):
        raise _Deterministic(ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED)


def _read_source(
    attempt: _Job, publication: SchedulePublication, source_id: str, max_fetch_bytes: int
) -> bytes:
    """H2: `metadata` then `fetch`, the pinned version rechecked after both (3.3.2).

    The connection is `AUTOCOMMIT`, so no transaction is open while the bytes
    are read. A missing provider, an adapter refusing its root and every
    `ProviderError` but a version change are `unavailable` (transient):
    absent and refused are one provider answer (E-11).
    """
    object_id = publication.source_object_id
    pinned = publication.source_version_id
    with attempt.engine.connect().execution_options(isolation_level=_READ_PHASE_ISOLATION) as reads:
        try:
            provider = _provider_for(reads, source_id)
        except ValueError:
            raise JobExecutionError(ErrorCode.UNAVAILABLE) from None
        if provider is None:
            raise JobExecutionError(ErrorCode.UNAVAILABLE)
        try:
            described = provider.metadata(object_id)
            if described.version_id != pinned:
                raise _Deterministic(ScheduleIssueCode.SOURCE_VERSION_CHANGED)
            if described.media_type is not None and described.media_type != SCHEDULE_MEDIA_TYPE:
                raise _Deterministic(ScheduleIssueCode.UNSUPPORTED_MEDIA_TYPE)
            if described.size_bytes is not None and described.size_bytes > max_fetch_bytes:
                raise _Deterministic(ScheduleIssueCode.SOURCE_TOO_LARGE)
            content = provider.fetch(object_id, max_bytes=max_fetch_bytes)
        except VersionChangedError:
            raise _Deterministic(ScheduleIssueCode.SOURCE_VERSION_CHANGED) from None
        except ProviderError:
            raise JobExecutionError(ErrorCode.UNAVAILABLE) from None
    if content.version_id != pinned:
        raise _Deterministic(ScheduleIssueCode.SOURCE_VERSION_CHANGED)
    data = content.content
    if content.is_truncated or len(data) > MAX_SCHEDULE_SOURCE_BYTES:
        raise _Deterministic(ScheduleIssueCode.SOURCE_TOO_LARGE)
    if not data.startswith(_PDF_MAGIC):
        raise _Deterministic(ScheduleIssueCode.UNSUPPORTED_MEDIA_TYPE)
    return data


def _parse(data: bytes, publication: SchedulePublication, wall: float) -> ScheduleParseResult:
    """H4: the contained child; its outcome classified per contract 3.4.6."""
    outcome = run_isolated_parse(
        data, expected_data_date=publication.expected_data_date, wall_seconds=wall
    )
    if isinstance(outcome, TransientFailure):
        raise JobExecutionError(outcome.error_code)
    if isinstance(outcome, DeterministicFailure):
        raise _Deterministic(outcome.code)
    if not isinstance(outcome, ParsedResult):  # pragma: no cover - the union is closed
        raise JobExecutionError(ErrorCode.INTERNAL_ERROR)
    return outcome.result


def _failed_code(result: ScheduleParseResult) -> ScheduleIssueCode:
    """A failed result carries exactly its one refusal issue, an error (S5a D-16)."""
    errors = [
        issue.code
        for issue in result.issues
        if ISSUE_SEVERITY[issue.code] is ScheduleIssueSeverity.ERROR
    ]
    if len(errors) != 1 or len(result.issues) != 1:
        raise ScheduleIntegrityError("failed_result_shape")
    return errors[0]


def _start_run(attempt: _Job, result: ScheduleParseResult) -> ScheduleParserRun:
    """H5: start (or reuse) the run; a reused `running` run must still be empty."""
    principal, publication_id, lease = attempt.principal, attempt.publication_id, attempt.lease
    identity = ScheduleParserIdentity.from_parse_result(result)

    def start(schedules: ScheduleRepository) -> ScheduleParserRun:
        run = schedules.start_parser_run(principal, publication_id, lease, identity).run
        if run.status is ScheduleParserRunStatus.RUNNING and schedules.count_parser_run_contents(
            principal, run.parser_run_id
        ) != (0, 0):
            # R7-N2/N3: this attempt's own run already holds a row or an issue.
            # `insert_issues` has no ordinal guard, so it is never resumed.
            raise ScheduleIntegrityError("running_run_not_empty")
        return run

    run = attempt.transaction(start)
    if run.status is ScheduleParserRunStatus.RUNNING:
        attempt.running_run_id = run.parser_run_id
    return run


def _batches[T](items: Sequence[T]) -> list[Sequence[T]]:
    return [items[i : i + MAX_SCHEDULE_BATCH] for i in range(0, len(items), MAX_SCHEDULE_BATCH)]


def _store(attempt: _Job, run_id: str, result: ScheduleParseResult) -> None:
    """H6: rows in ordinal order, then issues, then the run's end; budget before each."""
    principal, publication_id, lease = attempt.principal, attempt.publication_id, attempt.lease
    for rows in _batches(result.rows):
        _budget(attempt, "H6")

        def store_rows(
            schedules: ScheduleRepository, batch: Sequence[ParsedScheduleRow] = rows
        ) -> int:
            return schedules.insert_rows(principal, run_id, lease, batch)

        try:
            attempt.transaction(store_rows)
        except ScheduleRowBoundsError:
            raise _Deterministic(ScheduleIssueCode.BOUNDS_EXCEEDED) from None
    for issues in _batches(result.issues):
        _budget(attempt, "H6")

        def store_issues(
            schedules: ScheduleRepository, batch: Sequence[ScheduleParseIssue] = issues
        ) -> int:
            return schedules.insert_issues(principal, publication_id, lease, run_id, batch)

        attempt.transaction(store_issues)
    _budget(attempt, "H6")
    digest = parse_result_sha256(result)
    attempt.transaction(
        lambda schedules: schedules.finish_parser_run(
            principal,
            run_id,
            lease,
            parsed=result.counts,
            parse_result_sha256=digest,
            failure_code=None,
        )
    )
    attempt.running_run_id = None


def _canonicalize(attempt: _Job, run_id: str) -> None:
    """H7: link every activity/milestone row, 1,000 at a time; budget before each."""
    principal, lease = attempt.principal, attempt.lease
    while True:
        _budget(attempt, "H7")
        progress = attempt.transaction(
            lambda schedules: schedules.canonicalize_batch(principal, run_id, lease)
        )
        if progress.remaining == 0:
            return
        if progress.linked == 0:
            raise ScheduleIntegrityError("canonicalization_stalled")
