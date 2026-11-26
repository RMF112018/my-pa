"""The `schedule` plane handler's P6 XER path: one claimed job, one P6 publication.

Contract `docs/architecture/schedule-xer-import-contract.md` section 9.3 (S7-3)
on the S5b-2 handler (`schedule.py`), which dispatches here on the
publication's `source_format` and keeps its lease, budget, failure classes and
series-match hook. The phases, each in its own short transaction whose first
statement holds the lease:

- H1 plan (`begin_p6_processing`); a terminal publication returns at once.
- H2 the snapshot from the database (no provider call); its SHA-256 and size
  are verified against the stored digest.
- H3 `pin_document` (already known, re-asserted; F3 checks it is the snapshot's).
- H4 the parse in the existing contained child, `p6_xer` mode, under the
  capture selection in force at admission; the frame is decoded without the
  parser, re-rendered and bound to the bytes (`run_isolated_p6_parse`).
- H5 `start_p6_parser_run` (`p6_xer_v1`, the catalogue version); a fatal
  parse fails the publication with its listed issues.
- Identity (section 11.1): no earlier complete P6 publication of the Series
  sharing the short name or GUID adds `p6_project_identity_changed`, unless
  the admission accepted the change; the outcome is then `review_required`.
- H7a for a `complete` outcome: the Stable Activities by exact `task_code`
  (created once per Series), so activities and captured values link at insert.
- H6 typed rows, field values, observed fields and issues in batches of at
  most 1,000 (names outside the section 5.2 pattern stored as null; the list
  capped at 10,000), then the run `parsed` with the frame digest.
- H7 any activity still unlinked is linked after `parsed` (a reused run).
- H8 finalization (the status is F9's) and the ADR-017 series-match hook.

`partial` is never produced. The module never imports the parser package or
PDFium, and it neither logs nor prints.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Final

from my_pa.contracts.ports import ScheduleIntegrityError, ScheduleRepository
from my_pa.domain.schedule import MAX_SCHEDULE_BATCH, ScheduleIssueCode
from my_pa.domain.schedule.p6.model import (
    MAX_LISTED_ISSUES,
    P6Entity,
    P6Issue,
    P6IssueCode,
    P6Outcome,
    P6ParseResult,
    P6Severity,
)
from my_pa.domain.schedule.p6_import import P6ProjectIdentity, p6_identity_changed
from my_pa.infrastructure.jobs.schedule_parser_process import (
    DeterministicFailure,
    IsolatedP6Parse,
    ParsedP6Result,
    TransientFailure,
    run_isolated_p6_parse,
)
from my_pa.infrastructure.jobs.worker import JobExecutionError
from my_pa.infrastructure.persistence.schedule_p6 import P6Plan, SqlScheduleP6Repository

if TYPE_CHECKING:
    from my_pa.infrastructure.jobs.schedule import _Job

__all__ = ["process_p6_publication"]

_RUNNING: Final = "running"
_PARSED: Final = "parsed"
_COMPLETE: Final = "complete"


def _parse_p6(data: bytes, capture: Sequence[str] | None, wall: float) -> IsolatedP6Parse:
    """H4 (a module seam: a test may force an outcome)."""
    return run_isolated_p6_parse(data, capture=capture, wall_seconds=wall)


class _Deterministic(Exception):  # noqa: N818 - an internal control-flow signal
    """Fail the publication with `code` and return (S5b-2 contract 3.3.2)."""

    def __init__(self, code: ScheduleIssueCode) -> None:
        super().__init__(code.value)
        self.code = code


def _p6(schedules: ScheduleRepository) -> SqlScheduleP6Repository:
    return SqlScheduleP6Repository.sharing(schedules)


def process_p6_publication(attempt: _Job, *, parse_wall: Callable[[], float | None]) -> None:
    """Drive one P6 publication through section 9.3 (the caller maps lease and integrity).

    `parse_wall` is the S5 parse wall for the time left (`None` when below the
    15 s floor), computed by the S5 handler so both formats share one budget.
    """
    try:
        _phases(attempt, parse_wall)
    except _Deterministic as outcome:
        code, run_id = outcome.code, attempt.running_run_id
        attempt.finishing(
            lambda schedules: _p6(schedules).fail_p6_publication(
                attempt.principal, attempt.publication_id, attempt.lease, run_id, code
            )
        )


def _budget(attempt: _Job, label: str) -> None:
    if attempt.spent(label):
        raise _Deterministic(ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED)


def _phases(attempt: _Job, parse_wall: Callable[[], float | None]) -> None:
    principal, publication_id, lease = attempt.principal, attempt.publication_id, attempt.lease
    # H1: the plan.
    plan = attempt.transaction(
        lambda schedules: _p6(schedules).begin_p6_processing(principal, publication_id, lease)
    )
    if plan.terminal:
        return
    _budget(attempt, "C1")
    # H2: the snapshot, from the database, verified.
    data, sha256, size = attempt.transaction(
        lambda schedules: _p6(schedules).load_p6_snapshot(principal, publication_id, lease)
    )
    if hashlib.sha256(data).hexdigest() != sha256 or len(data) != size:
        raise ScheduleIntegrityError("snapshot_digest")
    _budget(attempt, "C2")
    # H3: the pin (re-asserted; F3 binds it to the snapshot).
    attempt.transaction(
        lambda schedules: schedules.pin_document(principal, publication_id, lease, sha256, size)
    )
    _budget(attempt, "C3")
    wall = parse_wall()
    if wall is None:
        raise _Deterministic(ScheduleIssueCode.PROCESSING_BUDGET_EXCEEDED)
    capture = attempt.transaction(
        lambda schedules: _p6(schedules).capture_selection(principal, plan.capture_event_id)
    )
    # H4: the parse, in the contained child.
    parsed = _classified(_parse_p6(data, capture, wall))
    result = parsed.result
    _budget(attempt, "C4")
    # H5: the parser run.
    run_id, status, stored_digest = _start_run(attempt)
    if result.outcome is P6Outcome.FAILED:
        _fail_parse(attempt, run_id, result)
        return
    if status == _PARSED:
        # A reused parsed run: its digest must equal the re-parse's (never blind trust).
        if stored_digest != parsed.frame_sha256:
            raise ScheduleIntegrityError("reused_run_digest_mismatch")
    else:
        _store(attempt, plan, run_id, parsed)
    # H7: any activity still unlinked (a reused run), only for a `complete` outcome.
    _link(attempt, run_id)
    # H8: finalization and the series-match hook.
    _budget(attempt, "H8")
    attempt.finishing(
        lambda schedules: _p6(schedules).finalize_p6_publication(
            principal, publication_id, lease, run_id
        )
    )


def _classified(outcome: IsolatedP6Parse) -> ParsedP6Result:
    if isinstance(outcome, TransientFailure):
        raise JobExecutionError(outcome.error_code)
    if isinstance(outcome, DeterministicFailure):
        raise _Deterministic(outcome.code)
    if not isinstance(outcome, ParsedP6Result):  # pragma: no cover - the union is closed
        raise ScheduleIntegrityError("parse_outcome")
    return outcome


def _start_run(attempt: _Job) -> tuple[str, str, str | None]:
    principal, publication_id, lease = attempt.principal, attempt.publication_id, attempt.lease

    def start(schedules: ScheduleRepository) -> tuple[str, str, str | None]:
        repository = _p6(schedules)
        run = repository.start_p6_parser_run(principal, publication_id, lease)
        if run.status == _RUNNING and repository.count_p6_run_contents(
            principal, run.parser_run_id
        ):
            # This attempt's own run already holds rows: never resumed (R7-N2/N3).
            raise ScheduleIntegrityError("running_run_not_empty")
        return run.parser_run_id, run.status, run.parse_result_sha256

    run_id, status, digest = attempt.transaction(start)
    if status == _RUNNING:
        attempt.running_run_id = run_id
    return run_id, status, digest


def _fail_parse(attempt: _Job, run_id: str, result: P6ParseResult) -> None:
    """HF for a fatal parse: the listed issues (at most 10,000), the run and publication failed."""
    issues = result.issues[:MAX_LISTED_ISSUES]
    attempt.finishing(
        lambda schedules: _p6(schedules).fail_p6_parse(
            attempt.principal, attempt.publication_id, attempt.lease, run_id, issues
        )
    )
    attempt.running_run_id = None


def _batches[T](items: Sequence[T]) -> list[Sequence[T]]:
    return [items[i : i + MAX_SCHEDULE_BATCH] for i in range(0, len(items), MAX_SCHEDULE_BATCH)]


def _identity_issue(attempt: _Job, plan: P6Plan, project: P6Entity) -> P6Issue | None:
    """Section 11.1: `p6_project_identity_changed` when no earlier identity is shared."""
    short_name, guid = project.get("project_short_name"), project.get("project_guid")
    current = P6ProjectIdentity(
        short_name if isinstance(short_name, str) else None,
        guid if isinstance(guid, str) else None,
    )
    earlier = attempt.transaction(
        lambda schedules: _p6(schedules).p6_series_identities(
            attempt.principal, plan.series_id, plan.publication_id
        )
    )
    if not p6_identity_changed(current, earlier, accepted=plan.accept_project_identity_change):
        return None
    return P6Issue(
        code=P6IssueCode.PROJECT_IDENTITY_CHANGED,
        severity=P6Severity.WARNING,
        table="PROJECT",
        line=project.record_line,
        field="proj_short_name",
    )


type _BatchWrite[T] = Callable[[SqlScheduleP6Repository, Sequence[T]], object]


def _write_batches[T](attempt: _Job, label: str, items: Sequence[T], write: _BatchWrite[T]) -> None:
    """One transaction per batch of at most 1,000, the budget read before each."""
    for batch in _batches(items):
        _budget(attempt, label)

        def run(schedules: ScheduleRepository, rows: Sequence[T] = batch) -> object:
            return write(_p6(schedules), rows)

        attempt.transaction(run)


def _store(attempt: _Job, plan: P6Plan, run_id: str, parsed: ParsedP6Result) -> None:
    """H7a then H6: Stable Activities (complete only), rows, issues, the run's end."""
    principal, publication_id, lease = attempt.principal, attempt.publication_id, attempt.lease
    result = parsed.result
    project = result.project
    if project is None:  # a complete parse always has its project
        raise ScheduleIntegrityError("project_missing")
    identity = _identity_issue(attempt, plan, project)
    issues = ([] if identity is None else [identity]) + list(result.issues)
    issues = issues[:MAX_LISTED_ISSUES]
    links: dict[str, str] | None = None
    if identity is None:
        # H7a: a `complete` outcome links at insert (review_required links nothing, F3).
        found: dict[str, str] = {}
        codes = sorted({str(activity.get("activity_id")) for activity in result.activities})
        _write_batches(
            attempt,
            "H7",
            codes,
            lambda repository, batch: found.update(
                repository.ensure_p6_stable_activities(principal, publication_id, lease, batch)
            ),
        )
        links = found
    _write_batches(
        attempt,
        "H6",
        [project],
        lambda repository, rows: repository.insert_p6_project(principal, run_id, lease, rows[0]),
    )
    _write_batches(
        attempt,
        "H6",
        result.wbs,
        lambda repository, rows: repository.insert_p6_wbs(principal, run_id, lease, rows),
    )
    _write_batches(
        attempt,
        "H6",
        result.activities,
        lambda repository, rows: repository.insert_p6_activities(
            principal, run_id, lease, rows, links
        ),
    )
    _write_batches(
        attempt,
        "H6",
        result.relationships,
        lambda repository, rows: repository.insert_p6_relationships(principal, run_id, lease, rows),
    )
    _write_batches(
        attempt,
        "H6",
        result.calendars,
        lambda repository, rows: repository.insert_p6_calendars(principal, run_id, lease, rows),
    )
    _write_batches(
        attempt,
        "H6",
        result.field_values,
        lambda repository, rows: repository.insert_p6_field_values(
            principal, run_id, lease, rows, links
        ),
    )
    _write_batches(
        attempt,
        "H6",
        result.observed_fields,
        lambda repository, rows: repository.insert_p6_observed_fields(
            principal, run_id, lease, rows
        ),
    )
    _write_batches(
        attempt,
        "H6",
        issues,
        lambda repository, rows: repository.insert_p6_issues(principal, run_id, lease, rows),
    )
    _budget(attempt, "H6")
    attempt.transaction(
        lambda schedules: _p6(schedules).finish_p6_parser_run(
            principal,
            run_id,
            lease,
            activities=len(result.activities),
            issues=len(issues),
            warnings=sum(1 for issue in issues if not issue.fatal),
            parse_result_sha256=parsed.frame_sha256,
        )
    )
    attempt.running_run_id = None


def _link(attempt: _Job, run_id: str) -> None:
    """H7 after `parsed`: link what is left, 1,000 at a time, for a `complete` outcome."""
    principal, lease = attempt.principal, attempt.lease
    outcome = attempt.transaction(
        lambda schedules: _p6(schedules).p6_run_outcome(principal, run_id)
    )
    if outcome != _COMPLETE:
        return
    previous: int | None = None
    while True:
        _budget(attempt, "H7")
        remaining = attempt.transaction(
            lambda schedules: _p6(schedules).link_p6_batch(principal, run_id, lease)
        )
        if remaining == 0:
            return
        if previous is not None and remaining >= previous:
            raise ScheduleIntegrityError("canonicalization_stalled")
        previous = remaining
