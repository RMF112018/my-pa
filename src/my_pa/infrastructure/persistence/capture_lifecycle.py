"""CRL-WP-03: the Capture root lifecycle repository (archive / restore).

The persistence half of `domain.capture.lifecycle`. Every function takes a
`Connection` already inside the caller's transaction and a `PrincipalContext`,
and every statement reaches the partition through `principal_scope`: a root,
event, receipt or job another Principal owns answers exactly what an absent
one answers. Nothing here opens or commits a transaction, takes a savepoint or
stages anything else; the use case (CP-CRL-03) owns the transaction.

**Lock order (MR-C06, plan (h)).** A lifecycle mutation takes the root
`FOR NO KEY UPDATE` first (`lock_capture_root`), then that root's job rows
`FOR UPDATE` in operation-id order (`suspend_capture_jobs` /
`resume_capture_jobs`), then inserts the event and the receipt. `NO KEY UPDATE`
conflicts with the `FOR SHARE` every other admission takes on the root, and not
with the `KEY SHARE` a foreign-key check takes, so ordinary inserts that
reference `captures` are not blocked by it.

**Append-only.** Events and receipts are inserted and read; the revision's
triggers refuse UPDATE and DELETE, so this module contains neither for them.
The only UPDATEs here are on `capture_jobs` control columns.

**The jobs overlay is a runtime projection.** `lease_generation` and
`pause_cause` exist only in the database (revision `0641c354ca85`, MR-C05);
`_capture_jobs` below names them through a metadata-free `table()` clause,
which cannot emit DDL, the `capture._capture_roots` precedent.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Final, NamedTuple, cast

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Connection,
    DateTime,
    Integer,
    Row,
    Table,
    Text,
    column,
    func,
    select,
    table,
)
from sqlalchemy.exc import IntegrityError

from my_pa.domain.capture.lifecycle import (
    MAX_LIFECYCLE_HISTORY,
    CaptureLifecycleEvent,
    CaptureLifecycleKeyConflictError,
    CaptureLifecycleOperation,
    CaptureLifecycleOutcome,
    CaptureLifecycleProjection,
    CaptureLifecycleReceipt,
    CaptureLifecycleSelector,
    CaptureLifecycleState,
    CapturePauseCause,
    CaptureProcessingEligibility,
    CaptureProcessingSubject,
    CaptureReasonCategory,
    pause_cause_for,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.identity.user_account import CallerSuppliedPrincipalError
from my_pa.infrastructure.persistence.principal_scope import (
    MissingPrincipalContextError,
    PrincipalContext,
    matching_partition_criterion,
    partition_criterion,
    principal_bound_values,
    principal_scoped,
    require_principal_context,
)
from my_pa.infrastructure.persistence.tables import (
    SCHEMA,
    JobState,
    capture_lifecycle_events,
    capture_lifecycle_receipts,
    capture_versions,
    captures,
)

__all__ = [
    "MAX_LIFECYCLE_HISTORY",
    "JobResumption",
    "latest_lifecycle",
    "latest_lifecycles",
    "lifecycle_history",
    "lifecycle_receipt",
    "lifecycle_selected",
    "lock_capture_root",
    "record_lifecycle_event",
    "record_lifecycle_receipt",
    "resume_capture_jobs",
    "share_capture_root",
    "suspend_capture_jobs",
]

#: Runtime projection of `knowledge.capture_jobs` including the two
#: database-only overlay columns. No MetaData, so it cannot emit DDL.
_capture_jobs = table(
    "capture_jobs",
    column("operation_id", Text),
    column("version_id", Text),
    column("state", Text),
    column("attempt_count", Integer),
    column("lease_owner", Text),
    column("lease_expires_at", DateTime(timezone=True)),
    column("updated_at", DateTime(timezone=True)),
    column("principal_id", Text),
    column("lease_generation", BigInteger),
    column("pause_cause", Text),
    schema=SCHEMA,
)
_JOBS: Final = cast(Table, _capture_jobs)

#: The job states archive suspends. Terminal rows are never touched.
_UNFINISHED: Final = (JobState.QUEUED.value, JobState.RUNNING.value)


#: The receipts' per-Principal key constraint, by name: the one unique violation
#: `record_lifecycle_receipt` turns into a typed refusal.
_KEY_CONSTRAINT: Final = "a_capture_lifecycle_key_admits_one_request_per_principal"


class JobResumption(NamedTuple):
    """What a restore did to the root's withdrawn work (MR-C12)."""

    resumed: int
    still_paused: int


def _owner(context: PrincipalContext | None) -> str:
    resolved = require_principal_context(context)
    if resolved.capture_principal_id is None:
        # The same refusal `principal_scope` makes for a text partition under a
        # context with no capture-plane identifier.
        raise MissingPrincipalContextError()
    return resolved.capture_principal_id


def _require_own(owner_principal_id: str, context: PrincipalContext | None) -> None:
    """A value naming an owner must name the context's own (MU-AC-02)."""
    if owner_principal_id != _owner(context):
        raise CallerSuppliedPrincipalError("owner_principal_id")


def lock_capture_root(
    connection: Connection, capture_id: str, *, context: PrincipalContext | None
) -> bool:
    """Take the root `FOR NO KEY UPDATE`, or report that this caller has none.

    The first statement of every archive or restore transaction (MR-C06). False
    for an absent root and for another Principal's alike, so the answer is no
    existence oracle.
    """
    validate_identifier(capture_id, IdKind.CAPTURE)
    held = connection.execute(
        principal_scoped(
            select(captures.c.capture_id).where(captures.c.capture_id == capture_id),
            captures,
            context,
        ).with_for_update(key_share=True)
    ).scalar_one_or_none()
    return held is not None


def share_capture_root(
    connection: Connection, capture_id: str, *, context: PrincipalContext | None
) -> bool:
    """Take the root `FOR SHARE`, or report that this caller has none (MR-C06).

    The first root statement of every other admission on a Capture (revise, and
    the later publication fences). `FOR SHARE` does not conflict with itself, so
    two revises still race on the version index exactly as T-21 proves; it does
    conflict with a lifecycle mutation's `FOR NO KEY UPDATE`, so a revise and an
    archive serialize on the root in whichever order they arrive.
    """
    validate_identifier(capture_id, IdKind.CAPTURE)
    held = connection.execute(
        principal_scoped(
            select(captures.c.capture_id).where(captures.c.capture_id == capture_id),
            captures,
            context,
        ).with_for_update(read=True)
    ).scalar_one_or_none()
    return held is not None


def lifecycle_selected(
    capture_id_column: ColumnElement[str],
    selector: CaptureLifecycleSelector,
    *,
    context: PrincipalContext | None,
) -> ColumnElement[bool] | None:
    """The condition a listing or search applies before totals and limits (CW-012).

    `None` for `ALL`. Otherwise the root's latest lifecycle revision, read by a
    correlated, partitioned subquery (0 when it has no event), decides by its
    parity: alternation from active/0 makes odd revisions archived and even
    ones active, so no stored state column is needed to filter.
    """
    selector = CaptureLifecycleSelector(selector)
    if selector is CaptureLifecycleSelector.ALL:
        return None
    latest = (
        select(func.coalesce(func.max(capture_lifecycle_events.c.lifecycle_revision), 0))
        .where(
            capture_lifecycle_events.c.capture_id == capture_id_column,
            partition_criterion(capture_lifecycle_events, context),
        )
        .scalar_subquery()
    )
    parity = 1 if selector is CaptureLifecycleSelector.ARCHIVED else 0
    return (latest % 2) == parity


_EVENT_COLUMNS: Final = (
    capture_lifecycle_events.c.event_id,
    capture_lifecycle_events.c.owner_principal_id,
    capture_lifecycle_events.c.capture_id,
    capture_lifecycle_events.c.lifecycle_revision,
    capture_lifecycle_events.c.operation,
    capture_lifecycle_events.c.resulting_state,
    capture_lifecycle_events.c.predecessor_event_id,
    capture_lifecycle_events.c.predecessor_revision,
    capture_lifecycle_events.c.transitioned_at,
    capture_lifecycle_events.c.intent_digest,
    capture_lifecycle_events.c.correlation_id,
    capture_lifecycle_events.c.audit_id,
    capture_lifecycle_events.c.reason_category,
)


def _to_event(row: Row[tuple[object, ...]]) -> CaptureLifecycleEvent:
    mapping = row._mapping
    return CaptureLifecycleEvent(
        event_id=str(mapping["event_id"]),
        owner_principal_id=str(mapping["owner_principal_id"]),
        capture_id=str(mapping["capture_id"]),
        lifecycle_revision=int(cast(int, mapping["lifecycle_revision"])),
        operation=CaptureLifecycleOperation(mapping["operation"]),
        resulting_state=CaptureLifecycleState(mapping["resulting_state"]),
        predecessor_event_id=cast(str | None, mapping["predecessor_event_id"]),
        predecessor_revision=cast(int | None, mapping["predecessor_revision"]),
        transitioned_at=cast(datetime, mapping["transitioned_at"]),
        intent_digest=str(mapping["intent_digest"]),
        correlation_id=str(mapping["correlation_id"]),
        audit_id=str(mapping["audit_id"]),
        reason_category=CaptureReasonCategory(mapping["reason_category"]),
    )


def latest_lifecycle(
    connection: Connection, capture_id: str, *, context: PrincipalContext | None
) -> CaptureLifecycleProjection:
    """The root's current lifecycle, projected from its latest event alone.

    A root with no event (or one this caller cannot see) projects active/0;
    the caller decides existence through `lock_capture_root` or the root read.
    """
    validate_identifier(capture_id, IdKind.CAPTURE)
    row = connection.execute(
        principal_scoped(
            select(*_EVENT_COLUMNS).where(capture_lifecycle_events.c.capture_id == capture_id),
            capture_lifecycle_events,
            context,
        )
        .order_by(capture_lifecycle_events.c.lifecycle_revision.desc())
        .limit(1)
    ).one_or_none()
    return CaptureLifecycleProjection.from_latest(
        owner_principal_id=_owner(context),
        capture_id=capture_id,
        latest=None if row is None else _to_event(row),
    )


def latest_lifecycles(
    connection: Connection,
    capture_ids: Iterable[str],
    *,
    context: PrincipalContext | None,
) -> dict[str, CaptureLifecycleProjection]:
    """The current lifecycle of each named root, in one statement (plan (d)).

    One partitioned read for a whole page, so a listing or search attaches
    lifecycle metadata without one query per row. A root with no event (or one
    this caller cannot see) projects active/0.
    """
    wanted = sorted({validate_identifier(value, IdKind.CAPTURE) for value in capture_ids})
    owner = _owner(context)
    found: dict[str, CaptureLifecycleProjection] = {
        capture_id: CaptureLifecycleProjection.initial(
            owner_principal_id=owner, capture_id=capture_id
        )
        for capture_id in wanted
    }
    if not wanted:
        return found
    rows = connection.execute(
        principal_scoped(
            select(*_EVENT_COLUMNS).where(capture_lifecycle_events.c.capture_id.in_(wanted)),
            capture_lifecycle_events,
            context,
        )
        .order_by(
            capture_lifecycle_events.c.capture_id,
            capture_lifecycle_events.c.lifecycle_revision.desc(),
        )
        .distinct(capture_lifecycle_events.c.capture_id)
    ).all()
    for row in rows:
        event = _to_event(row)
        found[event.capture_id] = CaptureLifecycleProjection.from_latest(
            owner_principal_id=owner, capture_id=event.capture_id, latest=event
        )
    return found


def lifecycle_history(
    connection: Connection,
    capture_id: str,
    *,
    context: PrincipalContext | None,
    limit: int = MAX_LIFECYCLE_HISTORY,
) -> tuple[CaptureLifecycleEvent, ...]:
    """The root's most recent `limit` events, oldest first (D-4, bounded)."""
    validate_identifier(capture_id, IdKind.CAPTURE)
    if isinstance(limit, bool) or not 1 <= limit <= MAX_LIFECYCLE_HISTORY:
        raise ValueError(f"a lifecycle history holds 1..{MAX_LIFECYCLE_HISTORY} events")
    rows = connection.execute(
        principal_scoped(
            select(*_EVENT_COLUMNS).where(capture_lifecycle_events.c.capture_id == capture_id),
            capture_lifecycle_events,
            context,
        )
        .order_by(capture_lifecycle_events.c.lifecycle_revision.desc())
        .limit(limit)
    ).all()
    return tuple(_to_event(row) for row in reversed(rows))


def record_lifecycle_event(
    connection: Connection, event: CaptureLifecycleEvent, *, context: PrincipalContext | None
) -> None:
    """Insert one event. The owner is stamped from the context, never the value."""
    _require_own(event.owner_principal_id, context)
    connection.execute(
        capture_lifecycle_events.insert().values(
            principal_bound_values(
                {
                    "event_id": event.event_id,
                    "capture_id": event.capture_id,
                    "lifecycle_revision": event.lifecycle_revision,
                    "operation": event.operation.value,
                    "resulting_state": event.resulting_state.value,
                    "predecessor_event_id": event.predecessor_event_id,
                    "predecessor_revision": event.predecessor_revision,
                    "transitioned_at": event.transitioned_at,
                    "intent_digest": event.intent_digest,
                    "correlation_id": event.correlation_id,
                    "audit_id": event.audit_id,
                    "reason_category": event.reason_category.value,
                },
                capture_lifecycle_events,
                context,
            )
        )
    )


def record_lifecycle_receipt(
    connection: Connection,
    receipt: CaptureLifecycleReceipt,
    *,
    context: PrincipalContext | None,
) -> None:
    """Insert one receipt; a reused key raises `CaptureLifecycleKeyConflictError`.

    The violation aborts the caller's transaction, which is the intended effect:
    the use case lets the refusal propagate so nothing it staged commits.
    """
    _require_own(receipt.owner_principal_id, context)
    try:
        _insert_receipt(connection, receipt, context=context)
    except IntegrityError as error:
        if getattr(getattr(error.orig, "diag", None), "constraint_name", None) == _KEY_CONSTRAINT:
            raise CaptureLifecycleKeyConflictError() from None
        raise


def _insert_receipt(
    connection: Connection,
    receipt: CaptureLifecycleReceipt,
    *,
    context: PrincipalContext | None,
) -> None:
    connection.execute(
        capture_lifecycle_receipts.insert().values(
            principal_bound_values(
                {
                    "receipt_id": receipt.receipt_id,
                    "idempotency_key": receipt.idempotency_key,
                    "capture_id": receipt.capture_id,
                    "operation": receipt.operation.value,
                    "intent_digest": receipt.intent_digest,
                    "expected_lifecycle_revision": receipt.expected_lifecycle_revision,
                    "resulting_lifecycle_revision": receipt.resulting_lifecycle_revision,
                    "outcome": receipt.outcome.value,
                    "event_id": receipt.event_id,
                    "issued_at": receipt.issued_at,
                    "correlation_id": receipt.correlation_id,
                    "audit_id": receipt.audit_id,
                },
                capture_lifecycle_receipts,
                context,
            )
        )
    )


def lifecycle_receipt(
    connection: Connection, idempotency_key: str, *, context: PrincipalContext | None
) -> CaptureLifecycleReceipt | None:
    """The receipt this caller's key is bound to, or `None` (CW-008 replay lookup).

    Partitioned, so one Principal's key never returns another's receipt.
    """
    row = connection.execute(
        principal_scoped(
            select(capture_lifecycle_receipts).where(
                capture_lifecycle_receipts.c.idempotency_key == idempotency_key
            ),
            capture_lifecycle_receipts,
            context,
        )
    ).one_or_none()
    if row is None:
        return None
    mapping = row._mapping
    return CaptureLifecycleReceipt(
        receipt_id=str(mapping["receipt_id"]),
        owner_principal_id=str(mapping["owner_principal_id"]),
        idempotency_key=str(mapping["idempotency_key"]),
        capture_id=str(mapping["capture_id"]),
        operation=CaptureLifecycleOperation(mapping["operation"]),
        intent_digest=str(mapping["intent_digest"]),
        expected_lifecycle_revision=int(mapping["expected_lifecycle_revision"]),
        resulting_lifecycle_revision=int(mapping["resulting_lifecycle_revision"]),
        outcome=CaptureLifecycleOutcome(mapping["outcome"]),
        event_id=mapping["event_id"],
        issued_at=mapping["issued_at"],
        correlation_id=str(mapping["correlation_id"]),
        audit_id=str(mapping["audit_id"]),
    )


def _lock_root_jobs(
    connection: Connection,
    capture_id: str,
    *,
    context: PrincipalContext | None,
    states: tuple[str, ...],
    pause_cause: str | None = None,
) -> list[Row[tuple[str, str, str, str, str]]]:
    """Lock the root's job rows in `states` `FOR UPDATE`, in operation-id order.

    Joined through `capture_versions` (both partitions must agree) and taken
    after the root lock, so no claim can land between this read and the update.
    """
    statement = (
        select(
            _capture_jobs.c.operation_id,
            _capture_jobs.c.state,
            capture_versions.c.version_id,
            capture_versions.c.processing_policy,
            capture_versions.c.classification,
        )
        .join(capture_versions, capture_versions.c.version_id == _capture_jobs.c.version_id)
        .where(
            capture_versions.c.capture_id == capture_id,
            _capture_jobs.c.state.in_(states),
            partition_criterion(_JOBS, context),
            matching_partition_criterion(_JOBS, capture_versions),
        )
        .order_by(_capture_jobs.c.operation_id)
        .with_for_update(of=_capture_jobs)
    )
    if pause_cause is not None:
        statement = statement.where(_capture_jobs.c.pause_cause == pause_cause)
    return list(connection.execute(statement).all())


def suspend_capture_jobs(
    connection: Connection, capture_id: str, *, context: PrincipalContext | None
) -> int:
    """Withdraw the root's unfinished work (archive; plan (f), CW-015).

    Queued rows keep identity, `next_attempt_at`, attempts and last error and
    gain `pause_cause = capture_withdrawn`. Running rows return to queued with
    the lease cleared, the generation advanced (so the old holder's lease is
    refused) and the attempt refunded, so archive is never a failure. Terminal
    rows are untouched. Returns how many rows were suspended.
    """
    validate_identifier(capture_id, IdKind.CAPTURE)
    locked = _lock_root_jobs(connection, capture_id, context=context, states=_UNFINISHED)
    queued = [row[0] for row in locked if row[1] == JobState.QUEUED.value]
    running = [row[0] for row in locked if row[1] == JobState.RUNNING.value]
    withdrawn = CapturePauseCause.CAPTURE_WITHDRAWN.value
    if queued:
        connection.execute(
            _capture_jobs.update()
            .where(
                _capture_jobs.c.operation_id.in_(queued),
                partition_criterion(_JOBS, context),
            )
            .values(pause_cause=withdrawn, updated_at=func.now())
        )
    if running:
        connection.execute(
            _capture_jobs.update()
            .where(
                _capture_jobs.c.operation_id.in_(running),
                partition_criterion(_JOBS, context),
            )
            .values(
                state=JobState.QUEUED.value,
                lease_owner=None,
                lease_expires_at=None,
                lease_generation=_capture_jobs.c.lease_generation + 1,
                attempt_count=func.greatest(_capture_jobs.c.attempt_count - 1, 0),
                pause_cause=withdrawn,
                updated_at=func.now(),
            )
        )
    return len(locked)


def resume_capture_jobs(
    connection: Connection,
    capture_id: str,
    *,
    context: PrincipalContext | None,
    eligibility: Callable[[CaptureProcessingSubject], CaptureProcessingEligibility],
) -> JobResumption:
    """Re-expose the root's withdrawn work under then-current policy (restore, MR-C12).

    Each `capture_withdrawn` row is evaluated through `eligibility`: an eligible
    row is cleared (its stored `next_attempt_at` still applies), an ineligible
    one becomes `current_policy_ineligible`. Restore creates no job and touches
    no terminal row and no stage result.
    """
    validate_identifier(capture_id, IdKind.CAPTURE)
    owner = _owner(context)
    locked = _lock_root_jobs(
        connection,
        capture_id,
        context=context,
        states=(JobState.QUEUED.value,),
        pause_cause=CapturePauseCause.CAPTURE_WITHDRAWN.value,
    )
    resumed: list[str] = []
    paused: list[str] = []
    for operation_id, _state, version_id, policy, classification in locked:
        subject = CaptureProcessingSubject(
            owner_principal_id=owner,
            capture_id=capture_id,
            version_id=version_id,
            processing_policy=policy,
            classification=Classification(classification),
        )
        cause = pause_cause_for(CaptureLifecycleState.ACTIVE, eligibility(subject))
        (paused if cause is not None else resumed).append(operation_id)
    for operation_ids, cause_value in (
        (resumed, None),
        (paused, CapturePauseCause.CURRENT_POLICY_INELIGIBLE.value),
    ):
        if operation_ids:
            connection.execute(
                _capture_jobs.update()
                .where(
                    _capture_jobs.c.operation_id.in_(operation_ids),
                    partition_criterion(_JOBS, context),
                )
                .values(pause_cause=cause_value, updated_at=func.now())
            )
    return JobResumption(resumed=len(resumed), still_paused=len(paused))
