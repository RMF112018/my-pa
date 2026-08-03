"""The extraction executor: one claimed job, one object at a time.

This is the handler `apps/worker.py` wires into `jobs.worker.run_worker`. It
walks the objects an enrollment holds that have reached no outcome yet, reads
each one through the provider its source is configured with, and records what
came back through the writers `persistence.extraction` already had.

**Why it is here and not in `application`.** The handler signature takes an
`Engine` and this module opens transactions, and `application` may not import
SQLAlchemy (`MB-AC-002`). `module-boundaries.md` section 5.5 gives
`infrastructure.jobs` "leases, attempts, retry state" and the rule that "poison
work quarantines rather than looping", which is exactly what the per-object loop
below decides. It may not import `my_pa.application` either
(`test_dependency_direction.py`), which is why the two refusals it raises are a
`JobExecutionError` carrying an `ErrorCode` and a `LeaseLostError`, and not the
application's error vocabulary.

**Three phases: one per job, then two per object.**

1. *Plan*, once per job. One read transaction: which objects are pending, and
   the two facts about the enrollment the read phase needs — its source and its
   byte ceiling. It commits and closes before any object is touched, so the
   plan is a snapshot rather than a cursor held open across the whole pass.
2. *Read*, per object, **with no transaction open**. `module-boundaries.md`
   section 10 says source bytes are read outside the database transaction, and
   `application/service.py` names this path as the rule's target — the exception
   `D-35` grants `sources.fetch` is granted to a bounded request, not to a
   worker walking ten thousand objects. The connection this phase holds is in
   `AUTOCOMMIT`, so the provider's own statements — the `observe_object` behind
   `metadata`, the two lookups behind an identifier resolution — each commit on
   their own and leave the session idle. Nothing holds a snapshot while
   `os.read` runs.
3. *Write*, per object, in its own transaction. `hold_lease` first, and a false
   answer raises `LeaseLostError` before anything is written; then the outcome.

**What a lost lease must not commit, and what it may leave behind.** It must not
commit an `extractions` row, a `quarantine_records` row, or the `succeeded`
state — the first two because `hold_lease` is the first statement of the
transaction that would write them, and the third because `complete_job` matches
on the owner. It *may* leave behind the objects this worker committed before the
lease went. Those rows are true: they were written while the lease was held, they
are keyed under `one_extraction_per_version_per_enrollment`, and the worker that
takes over skips them because `pending_objects` excludes an object that already
has an outcome. Convergence, not atomicity, and saying so is the point — a
reader who believed the job was all-or-nothing would expect a re-run to start
from nothing and would be wrong.

**Nothing is skipped silently.** Every object the plan named reaches one of five
ends, and three of them are stored rows: an extraction, an `unsupported` row, or
a quarantine with the reason that stopped it. The other two store nothing and
neither is a skip — the source was momentarily unavailable, or the enrollment's
allowlist does not cover the object's content type. Both leave the object
uncovered, which is what makes the enrollment report `partially_processed` with
`scope_not_fully_extracted` rather than complete: an absent outcome is reported
as an absent outcome instead of being counted as one.

A PDF takes the `unsupported` row. It is still unsupported (`P00-OD-003` is open
and nothing here opens it) and it is now *counted*, where before this executor
existed it was absent from every count there was.

**One failure is not an outcome and is not caught.** An `UnauthorizedObjectError`
naming the *object* means `enrollment_objects` says the enrollment holds it and
`authorized_object` says it does not — the store disagreeing with itself, which
`docs/specs` section 12 calls broken rather than partial. It ends the attempt
with `internal_error`. The same exception naming the object's *content type* is
an ordinary refusal: the enrollment's allowlist does not cover it, that is not
the object's fault, and the loop continues. The two are told apart by asking the
store which of the two dimensions refused, not by reading the message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sqlalchemy import Connection, Engine, Text, literal, select

from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.extraction.quarantine import QuarantineReason
from my_pa.domain.extraction.text import ExtractionOutcome, extract_text
from my_pa.domain.source.provider import (
    ProviderError,
    SourceProvider,
    TraversalDeniedError,
    VersionChangedError,
)
from my_pa.infrastructure.jobs.worker import JobExecutionError, LeaseLostError
from my_pa.infrastructure.persistence.extraction import (
    UnauthorizedObjectError,
    authorized_object,
    quarantine_object,
    record_outcome,
)
from my_pa.infrastructure.persistence.jobs import LeasedJob, hold_lease
from my_pa.infrastructure.persistence.knowledge import pending_objects
from my_pa.infrastructure.persistence.tables import enrollments
from my_pa.infrastructure.providers.registered import RegisteredSourceProviders

__all__ = ["extract_enrollment"]

#: The read phase's isolation level, and the whole of how "bytes are read outside
#: the transaction" is made true rather than asserted. `metadata` writes — a
#: `RegistryIdentity` issues identifiers through `observe_object` — and an
#: identifier resolution reads, so the provider needs a live connection during a
#: call that also opens a file. Under `AUTOCOMMIT` each of those statements
#: commits by itself and the session is idle again before the read starts; under
#: any other level the first statement would open a snapshot that stayed open
#: until the fetch returned.
_READ_PHASE_ISOLATION: Final = "AUTOCOMMIT"


@dataclass(frozen=True, slots=True)
class _Plan:
    """What one pass has to do, read once and then closed.

    `pending` is ordered by identifier, which `pending_objects` guarantees, so
    two workers over the same enrollment walk the same sequence and a re-run
    after a crash resumes in a decidable order.
    """

    enrollment_id: str
    source_id: str
    max_bytes: int
    pending: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Denial:
    """A provider refusal that stopped one object, and the reason to record.

    Distinct from an `ExtractionOutcome` because there is nothing to extract: the
    bytes were never read, so there is no text, no media type, and — for a
    containment failure at resolution time — no proven version either.
    `quarantine_object` takes exactly these three things and has no parameter
    content could arrive through.
    """

    source_object_id: str
    version_id: str | None
    reason: QuarantineReason


def extract_enrollment(engine: Engine, job: LeasedJob, owner: str) -> None:
    """Extract every object of `job`'s enrollment that has no outcome yet.

    Raises `LeaseLostError` the moment a write finds the lease gone, so the
    attempt stops where it stopped rather than finishing a pass for a job it no
    longer holds. Raises `JobExecutionError` when the whole attempt cannot
    proceed — no provider for the source, or a store that contradicts itself.
    Everything else that can go wrong is a property of one object and is recorded
    against that object.

    Returns nothing, because there is nothing a caller could do with a count that
    the stored rows do not already say better: `coverage_for` reads the same rows
    and is the one place the numbers are assembled.
    """
    plan = _plan(engine, job.subject_id)
    if plan is None:
        # Nothing pending. The common case for a re-run, and the honest one for a
        # job whose enrollment has been deleted underneath it — the cascade takes
        # the job row too, so this is a loop over an empty set rather than a
        # branch guarding one.
        return

    with engine.connect().execution_options(isolation_level=_READ_PHASE_ISOLATION) as reads:
        provider = _provider(reads, plan.source_id)
        for source_object_id in plan.pending:
            recordable = _read(provider, plan, source_object_id)
            if recordable is None:
                continue
            _write(engine, job, owner=owner, enrollment_id=plan.enrollment_id, result=recordable)


def _plan(engine: Engine, enrollment_id: str) -> _Plan | None:
    """Read the work list and the two enrollment facts the read phase needs.

    `None` means there is nothing to do. The pending set is read first and the
    enrollment second on purpose: a non-empty pending set is rows in
    `enrollment_objects`, which cascade from `enrollments`, so by the time the
    second statement runs the row it asks for cannot be absent.

    `media_types` is deliberately not read here. The allowlist is enforced by
    `record_outcome`, in the transaction that would store the text, and a copy of
    it in this module would be a second place the same decision is made — which
    is the divergence this package has been blocked for more than once.
    """
    with engine.begin() as connection:
        pending = pending_objects(connection, enrollment_id)
        if not pending:
            return None
        source_id, max_bytes = connection.execute(
            select(enrollments.c.source_id, enrollments.c.max_bytes).where(
                enrollments.c.enrollment_id == enrollment_id
            )
        ).one()
    return _Plan(
        enrollment_id=enrollment_id,
        source_id=str(source_id),
        max_bytes=int(max_bytes),
        pending=pending,
    )


def _provider(connection: Connection, source_id: str) -> SourceProvider:
    """The adapter serving `source_id`, or an `unavailable` attempt.

    `None` from the lookup means no row configures this source, and a root that
    has gone is a `ValueError` from the adapter's own constructor. Both are
    `unavailable`: the work cannot proceed and nothing about it is the
    enrollment's fault, so the attempt is released and retried within the bound
    rather than recorded against any object.

    The lookup is `RegisteredSourceProviders` rather than a second reading of
    `knowledge.sources` here. It is the one place that turns a row into an
    adapter, and a copy of that decision in the worker would be the second copy
    of a security-relevant lookup — which root, served by which provider.
    """
    try:
        found = RegisteredSourceProviders(connection).for_source(source_id)
    except ValueError:
        # The adapter's constructor refusing its root: configured, and not there.
        raise JobExecutionError(ErrorCode.UNAVAILABLE) from None
    if found is None:
        raise JobExecutionError(ErrorCode.UNAVAILABLE)
    return found


def _read(
    provider: SourceProvider, plan: _Plan, source_object_id: str
) -> ExtractionOutcome | _Denial | None:
    """Observe and read one object, and say what should be recorded for it.

    `None` is "record nothing": the source was momentarily unavailable, which is
    not a fact about the object and must not become a stored outcome. The object
    stays uncovered, which is what leaves the enrollment `partially_processed`
    with `scope_not_fully_extracted` — an honest report that something is missing,
    where a quarantine would have been a claim that the object itself was the
    problem.

    `metadata` immediately before `fetch`, in that order, because the provider
    binds the two: a read is served only against an observation this instance
    made, and the fingerprint taken at description time is what the read is
    compared against. It is the same order `_sources_fetch` uses for the same
    reason.

    Neither call is wrapped in a transaction and neither may be. See the module
    docstring; this is the boundary the handler signature changed for.
    """
    try:
        described = provider.metadata(source_object_id)
        content = provider.fetch(source_object_id, max_bytes=plan.max_bytes)
    except TraversalDeniedError:
        # Containment could not be proved *now*, whatever was true when the
        # identifier was issued. No version was proven, so none is recorded:
        # attributing the quarantine to bytes nobody saw would be an invention.
        return _Denial(source_object_id, None, QuarantineReason.CONTAINMENT_UNPROVEN)
    except VersionChangedError:
        # The object changed between the observation and the read. `conflict` in
        # section 10's terms, and never stale bytes labelled current.
        return _Denial(source_object_id, None, QuarantineReason.SOURCE_VERSION_CHANGED)
    except ProviderError:
        return None

    return extract_text(
        source_id=provider.source_id,
        source_object_id=source_object_id,
        observed_version_id=described.version_id,
        content_version_id=content.version_id,
        media_type=content.media_type,
        content=content.content,
        # The object's own modification time, not this worker's clock:
        # `Provenance` refuses a processing time earlier than the observation,
        # and a fixed or skewed clock can precede a file's `mtime`.
        observed_at=described.modified_at,
        is_truncated=content.is_truncated,
    )


def _write(
    engine: Engine,
    job: LeasedJob,
    *,
    owner: str,
    enrollment_id: str,
    result: ExtractionOutcome | _Denial,
) -> None:
    """Record one object's result, or refuse to, in one transaction.

    `hold_lease` is the first statement and it is not a courtesy check: it takes
    the job row `FOR UPDATE`, so no other worker's claim can land between the
    answer and the insert that follows it in this same transaction. A false
    answer raises, and raising is what rolls this transaction back with nothing
    written.

    An `ExtractionOutcome` goes through `record_outcome`, which routes a
    quarantined one to `quarantine_object` itself — so a caller cannot persist a
    batch and lose the quarantines by filtering for the ones with text. A
    `_Denial` never reached an outcome and goes to `quarantine_object` directly.

    Both writers refuse an object the enrollment does not authorize, and both
    refusals reach one classifier. Handling only the `record_outcome` one would
    leave a quarantine's refusal to fall through as an unclassified failure —
    the same code, reached without anyone having decided it.
    """
    with engine.begin() as connection:
        if not hold_lease(connection, job.operation_id, owner=owner):
            raise LeaseLostError(job.operation_id)
        try:
            if isinstance(result, _Denial):
                quarantine_object(
                    connection,
                    enrollment_id=enrollment_id,
                    source_object_id=result.source_object_id,
                    version_id=result.version_id,
                    reason=result.reason,
                )
            else:
                record_outcome(connection, enrollment_id=enrollment_id, outcome=result)
        except UnauthorizedObjectError:
            _classify_refusal(
                connection,
                enrollment_id=enrollment_id,
                source_object_id=(
                    result.source_object_id
                    if isinstance(result, _Denial)
                    else result.provenance.source_object_id
                ),
            )


def _classify_refusal(connection: Connection, *, enrollment_id: str, source_object_id: str) -> None:
    """Decide which of the two authorization dimensions refused, and act.

    Asked of the store rather than read off the message, because the message is
    prose and this decision is the difference between continuing and failing the
    attempt.

    If the object *is* authorized, the refusal was about its content type: the
    enrollment's allowlist does not cover it, no row is written, and the loop
    continues. The object stays uncovered and the coverage report says so.

    If it is not, then `enrollment_objects` offered this object as pending work
    for this enrollment while `authorized_object` refuses it — two reads of the
    same rows disagreeing. That is a broken store rather than a partial result,
    and it fails the attempt with `internal_error`. Softening it into a skip is
    exactly the laundering `docs/specs` section 12 forbids.

    `from None` so the refusal is not left in `__context__`: it carries both
    identifiers, and this exception travels to a loop that records a code.
    """
    authorized = connection.execute(
        select(authorized_object(literal(source_object_id, Text), enrollment_id=enrollment_id))
    ).scalar_one()
    if not authorized:
        raise JobExecutionError(ErrorCode.INTERNAL_ERROR) from None
