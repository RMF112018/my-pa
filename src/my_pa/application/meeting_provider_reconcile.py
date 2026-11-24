"""`meetings.provider.review` and `meetings.provider.reconcile` (WP3b-S4; spec section 12.7).

The reconciliation pass the Principal completes before calendar sync applies
anything (Manager rulings D2, D3, D4, D6, D12; the pure values are
`domain/meeting_sync/reconcile.py`).

**Review** (a read) answers the pass block (`state` `pending`|`complete`,
`completed_at`, `unreviewed_count`), one keyset page of the in-scope Meetings
with neither a binding nor a mark, and the staged provider events whose key is
unbound: for each source with a staged publication, the events of its newest
publication that is applied or still staged (a skipped one is not the
provider's current view), tombstoned keys listed `suppressed`. The two lists
are side by side. **Nothing here pairs, ranks or compares a Meeting with an
event** -- no title, time or similarity is ever read against the other list
(ruling D2; `tests/architecture/test_meeting_provider_review_no_pairing.py`).
The staged event fields are eligible for the operator's own connected clients
(ruling D12, R-OP-3).

**Reconcile** (a write) takes the Principal's binding-writer advisory lock
first (ruling D8), then runs each item under its own SAVEPOINT, so an item
refused with a closed token rolls back alone and the others stand:

* a `bind` is exactly `MeetingApplication.bind_meeting_provider` -- the same
  CAS, rules, receipt and Record Event -- reserving under the
  `meetings.provider.bind` key space with the derived key
  `reconcile_item_key(batch key, index)`, and with Record Event
  `source_capability` `meetings.provider.reconcile`; a staged reference
  resolves to the staged event's full key, series UID and provider event id;
* a `no_provider_event` mark inserts one `meeting_provider_review_marks` row
  (idempotent by Meeting) and never versions the Meeting; a Meeting that is
  already provider-bound is refused `meeting_already_provider_bound`.

Then, in the same transaction, when no in-scope Meeting is left unreviewed
and the latch does not exist yet, the latch is recorded once with the in-scope
count and this call's correlation id (ruling D4). An empty batch does only
that. **Replay:** the same batch key replays every bind item (its derived key
answers its stored receipt, outcome `replayed`) and every mark (already
marked: `replayed`); a refused item wrote nothing, so a replay evaluates it
again. A changed bind item under the same batch key is refused
`idempotency_conflict` on that item.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from my_pa.application.meetings import MeetingApplication, MeetingProviderBindResult
from my_pa.contracts.ports import (
    MeetingProviderReconciliationPassRecord,
    MeetingProviderReviewMarkRecord,
    MeetingSyncApplyOutcome,
    StagedProviderEvent,
    UnitOfWork,
    UnreviewedMeetingRecord,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.contracts.v1.meetings import MeetingProviderBindingView
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.operation import Capability
from my_pa.domain.meeting.model import (
    MeetingError,
    MeetingErrorField,
    MeetingIdempotencyConflictError,
    MeetingInvalidRequestError,
    MeetingNotFoundError,
    MeetingStaleVersionError,
    MeetingUnavailableError,
)
from my_pa.domain.meeting_sync.binding import MeetingProviderBindRequest, ProviderBindAction
from my_pa.domain.meeting_sync.reconcile import (
    MAX_RECONCILE_ITEMS,
    MAX_REVIEW_PAGE_SIZE,
    ReconcileItem,
    ReconcileItemAction,
    ReconcileItemOutcome,
    ReconciliationPassState,
    reconcile_item_key,
    review_scope_start,
)

__all__ = [
    "MeetingProviderReconciliation",
    "ReconcileItemResult",
    "ReconcileRefusal",
    "ReconcileResult",
    "ReconciliationPass",
    "ReviewPage",
]

_RECONCILE_NAME: Final = Capability.MEETINGS_PROVIDER_RECONCILE.value


@dataclass(frozen=True, slots=True)
class ReconciliationPass:
    """The pass block both capabilities answer."""

    state: ReconciliationPassState
    completed_at: datetime | None
    unreviewed_count: int


@dataclass(frozen=True, slots=True)
class ReviewPage:
    """What `meetings.provider.review` answers: two side-by-side lists, never paired."""

    reconciliation: ReconciliationPass
    unreviewed_meetings: tuple[UnreviewedMeetingRecord, ...]
    #: The last listed Meeting when the page is full (pass it back as `after`).
    next_after: str | None
    unbound_provider_events: tuple[StagedProviderEvent, ...]


@dataclass(frozen=True, slots=True)
class ReconcileRefusal:
    """One item's closed refusal: the public error code and its one safe token."""

    code: ErrorCode
    #: The `SafeDetail` value naming the field or rule (answered as `detail`).
    safe_detail: str


@dataclass(frozen=True, slots=True)
class ReconcileItemResult:
    """One item's independent outcome."""

    index: int
    meeting_id: str
    outcome: ReconcileItemOutcome
    refusal: ReconcileRefusal | None = None
    #: The Meeting's binding after a bind (or its replay); `None` otherwise.
    binding: MeetingProviderBindingView | None = None
    #: The Meeting's version after a bind (or its replay); `None` otherwise.
    version: int | None = None


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """What `meetings.provider.reconcile` answers."""

    items: tuple[ReconcileItemResult, ...]
    reconciliation: ReconciliationPass
    #: Whether calendar sync applies staged publications (the latch exists).
    sync_enabled: bool


def _refusal(error: MeetingError) -> ReconcileRefusal:
    """The service's Meeting translation, per item (`service._meeting_translated`)."""
    if isinstance(error, MeetingStaleVersionError):
        return ReconcileRefusal(ErrorCode.CONFLICT, "stale_version")
    if isinstance(error, MeetingIdempotencyConflictError):
        return ReconcileRefusal(ErrorCode.CONFLICT, "idempotency_conflict")
    if isinstance(error, MeetingNotFoundError):
        return ReconcileRefusal(ErrorCode.NOT_FOUND, error.field.value)
    if isinstance(error, MeetingUnavailableError):
        return ReconcileRefusal(ErrorCode.UNAVAILABLE, error.field.value)
    return ReconcileRefusal(ErrorCode.INVALID_REQUEST, error.field.value)


def _current_pass(unit: UnitOfWork, principal_id: str, now: datetime) -> ReconciliationPass:
    latch = unit.meeting_sync.get_reconciliation_pass(principal_id)
    counts = unit.meeting_sync.count_review_scope(principal_id, since=review_scope_start(now))
    if latch is None:
        return ReconciliationPass(ReconciliationPassState.PENDING, None, counts.unreviewed)
    return ReconciliationPass(
        ReconciliationPassState.COMPLETE, latch.completed_at, counts.unreviewed
    )


class MeetingProviderReconciliation:
    """The review read and the reconcile write, over the caller's unit of work."""

    def __init__(self, meetings: MeetingApplication | None = None) -> None:
        self._meetings = MeetingApplication() if meetings is None else meetings

    # --- meetings.provider.review --------------------------------------------

    def review(
        self,
        unit: UnitOfWork,
        principal_id: str,
        *,
        now: datetime,
        page_size: int | None = None,
        after: str | None = None,
    ) -> ReviewPage:
        at = ensure_utc(now)
        limit = MAX_REVIEW_PAGE_SIZE if page_size is None else page_size
        if not 1 <= limit <= MAX_REVIEW_PAGE_SIZE:
            raise MeetingInvalidRequestError(MeetingErrorField.PAGE_SIZE)
        meetings = unit.meeting_sync.list_unreviewed_meetings(
            principal_id, since=review_scope_start(at), after_meeting_id=after, limit=limit
        )
        return ReviewPage(
            reconciliation=_current_pass(unit, principal_id, at),
            unreviewed_meetings=meetings,
            next_after=meetings[-1].meeting_id if len(meetings) == limit else None,
            unbound_provider_events=self._unbound_events(unit, principal_id),
        )

    @staticmethod
    def _unbound_events(unit: UnitOfWork, principal_id: str) -> tuple[StagedProviderEvent, ...]:
        """Per source, the unbound events of its newest applied-or-staged publication."""
        staging = unit.meeting_sync
        found: list[StagedProviderEvent] = []
        sources = staging.list_staging_sources(principal_id)
        for source_id in sources:
            current = [
                publication
                for publication in staging.list_publications(principal_id, source_id)
                if publication.apply_outcome in (None, MeetingSyncApplyOutcome.APPLIED)
            ]
            if current:  # apply order: the last is the newest
                found.extend(staging.list_unbound_events(principal_id, current[-1].snapshot_id))
        return tuple(found)

    # --- meetings.provider.reconcile -----------------------------------------

    def reconcile(
        self,
        unit: UnitOfWork,
        principal_id: str,
        items: tuple[ReconcileItem, ...],
        idempotency_key: str,
        now: datetime,
        *,
        correlation_id: str,
    ) -> ReconcileResult:
        at = ensure_utc(now)
        if len(items) > MAX_RECONCILE_ITEMS:
            raise MeetingInvalidRequestError(MeetingErrorField.ITEMS)
        # Every binding writer takes the Principal's lock first (ruling D8);
        # each bind item takes it again, re-entrantly.
        unit.meetings.lock_provider_binding_writers(principal_id)
        results: list[ReconcileItemResult] = []
        for index, item in enumerate(items):
            write = self._item_writer(
                unit, principal_id, item, idempotency_key, index, at, correlation_id
            )
            try:
                with unit.meeting_sync.savepoint():
                    results.append(write())
            except MeetingError as error:
                results.append(
                    ReconcileItemResult(
                        index=index,
                        meeting_id=item.meeting_id,
                        outcome=ReconcileItemOutcome.REFUSED,
                        refusal=_refusal(error),
                    )
                )
        latch = unit.meeting_sync.get_reconciliation_pass(principal_id)
        counts = unit.meeting_sync.count_review_scope(principal_id, since=review_scope_start(at))
        if latch is None and counts.unreviewed == 0:
            latch = MeetingProviderReconciliationPassRecord(
                completed_at=at,
                reviewed_meetings=counts.in_scope,
                reconcile_correlation_id=correlation_id,
            )
            unit.meeting_sync.insert_reconciliation_pass(principal_id, latch)
        reconciliation = (
            ReconciliationPass(ReconciliationPassState.PENDING, None, counts.unreviewed)
            if latch is None
            else ReconciliationPass(
                ReconciliationPassState.COMPLETE, latch.completed_at, counts.unreviewed
            )
        )
        return ReconcileResult(
            items=tuple(results), reconciliation=reconciliation, sync_enabled=latch is not None
        )

    def _item_writer(
        self,
        unit: UnitOfWork,
        principal_id: str,
        item: ReconcileItem,
        batch_key: str,
        index: int,
        at: datetime,
        correlation_id: str,
    ) -> Callable[[], ReconcileItemResult]:
        if item.action is ReconcileItemAction.NO_PROVIDER_EVENT:
            return lambda: self._mark(unit, principal_id, item, index, at)
        return lambda: self._bind(unit, principal_id, item, batch_key, index, at, correlation_id)

    @staticmethod
    def _mark(
        unit: UnitOfWork, principal_id: str, item: ReconcileItem, index: int, at: datetime
    ) -> ReconcileItemResult:
        meetings = unit.meetings
        if meetings.read_meeting(principal_id, item.meeting_id) is None:
            raise MeetingNotFoundError(MeetingErrorField.MEETING_ID)
        if meetings.read_provider_binding_for_meeting(principal_id, item.meeting_id) is not None:
            raise MeetingInvalidRequestError(MeetingErrorField.MEETING_ALREADY_PROVIDER_BOUND)
        written = unit.meeting_sync.insert_review_mark(
            principal_id, MeetingProviderReviewMarkRecord(meeting_id=item.meeting_id, marked_at=at)
        )
        return ReconcileItemResult(
            index=index,
            meeting_id=item.meeting_id,
            outcome=ReconcileItemOutcome.MARKED if written else ReconcileItemOutcome.REPLAYED,
        )

    def _bind(
        self,
        unit: UnitOfWork,
        principal_id: str,
        item: ReconcileItem,
        batch_key: str,
        index: int,
        at: datetime,
        correlation_id: str,
    ) -> ReconcileItemResult:
        if item.expected_version is None:  # the item's own validation requires it
            raise MeetingInvalidRequestError(MeetingErrorField.EXPECTED_VERSION)
        written: MeetingProviderBindResult = self._meetings.bind_meeting_provider(
            unit,
            principal_id,
            _bind_request(unit, principal_id, item),
            item.expected_version,
            reconcile_item_key(batch_key, index),
            at,
            source_capability=_RECONCILE_NAME,
            correlation_id=correlation_id,
        )
        return ReconcileItemResult(
            index=index,
            meeting_id=written.meeting_id,
            outcome=ReconcileItemOutcome.REPLAYED
            if written.replayed
            else ReconcileItemOutcome.BOUND,
            binding=written.binding,
            version=written.version,
        )


def _bind_request(
    unit: UnitOfWork, principal_id: str, item: ReconcileItem
) -> MeetingProviderBindRequest:
    """The bind the item names: by staged reference or by its full key."""
    if item.provider_event_ref is not None:
        staged = unit.meeting_sync.get_event(principal_id, item.provider_event_ref)
        if staged is None:
            raise MeetingNotFoundError(MeetingErrorField.PROVIDER_EVENT_REF)
        return MeetingProviderBindRequest(
            action=ProviderBindAction.BIND,
            meeting_id=item.meeting_id,
            calendar_ref=staged.calendar_ref,
            ical_uid=staged.ical_uid,
            occurrence_original_start_utc=staged.occurrence_original_start_utc,
            series_ical_uid=staged.series_ical_uid,
            provider_event_id=staged.provider_event_id,
            provider_event_id_format=staged.provider_event_id_format,
            adopt_provider_series=item.adopt_provider_series,
        )
    return MeetingProviderBindRequest(
        action=ProviderBindAction.BIND,
        meeting_id=item.meeting_id,
        calendar_ref=item.calendar_ref,
        ical_uid=item.ical_uid,
        occurrence_original_start_utc=item.occurrence_original_start_utc,
        series_ical_uid=item.series_ical_uid,
        provider_event_id=item.provider_event_id,
        provider_event_id_format=item.provider_event_id_format,
        adopt_provider_series=item.adopt_provider_series,
    )
