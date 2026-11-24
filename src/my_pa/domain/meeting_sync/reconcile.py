"""The reconciliation pass, as pure values (WP3b-S4; spec section 12.7, rulings D2-D4, D6).

Before calendar sync applies anything, the Principal reviews every **in-scope**
Meeting once (ruling D3): every Meeting that is not cancelled and starts at or
after `now - COLLECTOR_LOOKBACK`. Each must be explicitly bound to a provider
key or marked `no_provider_event`; there is no "mark all". Older and cancelled
Meetings can never collide with a sync record and need no mark.

`meetings.provider.review` lists the in-scope Meetings that have neither a
binding nor a mark beside the staged provider events whose key is unbound. The
two lists are **side by side**: nothing here or in the review pairs, ranks or
compares a Meeting with an event (ruling D2; a FAST guard reads this slice for
it). `meetings.provider.reconcile` takes 0..50 items, each an explicit bind or
mark, applied independently; the call that leaves no in-scope Meeting unreviewed
records the one-way latch (ruling D4).

`ReconcileItem` is one normalized item. A bind names the Meeting, its
`expected_version`, and the provider event either by its opaque staged
reference (`provider_event_ref`, the `msevt_` id the review answered) **or** by
its full key (`calendar_ref`, `ical_uid`, and for an occurrence
`occurrence_original_start_utc` with `series_ical_uid`), never both; the
optional `provider_event_id` and its format belong to the full-key form (a
reference takes them from the staged event). `adopt_provider_series` is ruling
D6's flag (`binding.py`). A mark names the Meeting only.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.meeting.model import (
    MeetingErrorField,
    MeetingInvalidRequestError,
    validate_meeting_id,
)
from my_pa.domain.meeting_sync.model import COLLECTOR_LOOKBACK, ProviderEventIdFormat

__all__ = [
    "MAX_RECONCILE_ITEMS",
    "MAX_REVIEW_PAGE_SIZE",
    "MAX_UNBOUND_PROVIDER_EVENTS",
    "RECONCILE_ITEM_KEY_PREFIX",
    "ReconcileItem",
    "ReconcileItemAction",
    "ReconcileItemOutcome",
    "ReconciliationPassState",
    "reconcile_item_key",
    "review_scope_start",
]

#: At most this many items per `meetings.provider.reconcile` call (ruling D2).
#: Zero is allowed: an empty call completes a pass that has nothing left.
MAX_RECONCILE_ITEMS: Final = 50
#: At most this many unreviewed Meetings per `meetings.provider.review` page.
MAX_REVIEW_PAGE_SIZE: Final = 100
#: At most this many unbound provider events per `meetings.provider.review`
#: answer (Manager ruling on the S4 handoff, decision 6 amended). The list is
#: ordered by start, then key, and the first this-many are answered with the
#: full count and a `truncated` flag; binding or marking shrinks the list.
MAX_UNBOUND_PROVIDER_EVENTS: Final = 200
#: Every derived bind-item key starts with this, so it is recognizably a
#: reconcile item's in the `meetings.provider.bind` key space.
RECONCILE_ITEM_KEY_PREFIX: Final = "reconcile-"


class ReconcileItemAction(StrEnum):
    """What one reconcile item does."""

    BIND = "bind"
    NO_PROVIDER_EVENT = "no_provider_event"


class ReconcileItemOutcome(StrEnum):
    """What one reconcile item did. Items are independent."""

    BOUND = "bound"
    MARKED = "marked"
    #: The same item already succeeded: its stored binding or mark is answered.
    REPLAYED = "replayed"
    #: Refused with one closed token; the item wrote nothing.
    REFUSED = "refused"


class ReconciliationPassState(StrEnum):
    """The Principal's pass: `complete` once the latch is recorded (ruling D4)."""

    PENDING = "pending"
    COMPLETE = "complete"


def review_scope_start(now: datetime) -> datetime:
    """The earliest `start_at` an in-scope Meeting may have (ruling D3)."""
    return now - COLLECTOR_LOOKBACK


def reconcile_item_key(batch_key: str, index: int) -> str:
    """The bind item's own idempotency key under `meetings.provider.bind` (ruling D2).

    `sha256(batch key, index)`: a replay of the batch with the same key replays
    every bind item; a different batch key or index is a different item.
    """
    digest = hashlib.sha256(f"{batch_key}\x00{index}".encode()).hexdigest()
    return RECONCILE_ITEM_KEY_PREFIX + digest


@dataclass(frozen=True, slots=True)
class ReconcileItem:
    """One normalized reconcile item (module docstring).

    Constructing one validates its shape; a refusal names the first offending
    field. The key fields themselves are validated by
    `MeetingProviderBindRequest` when the bind is built.
    """

    action: ReconcileItemAction
    meeting_id: str
    expected_version: int | None = None
    provider_event_ref: str | None = None
    calendar_ref: str | None = None
    ical_uid: str | None = None
    occurrence_original_start_utc: datetime | None = None
    series_ical_uid: str | None = None
    provider_event_id: str | None = None
    provider_event_id_format: ProviderEventIdFormat | None = None
    adopt_provider_series: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.action, ReconcileItemAction):
            raise MeetingInvalidRequestError(MeetingErrorField.ACTION)
        validate_meeting_id(self.meeting_id)
        if not isinstance(self.adopt_provider_series, bool):
            raise MeetingInvalidRequestError(MeetingErrorField.ADOPT_PROVIDER_SERIES)
        key_fields = (
            (self.calendar_ref, MeetingErrorField.CALENDAR_REF),
            (self.ical_uid, MeetingErrorField.ICAL_UID),
            (self.occurrence_original_start_utc, MeetingErrorField.OCCURRENCE_ORIGINAL_START_UTC),
            (self.series_ical_uid, MeetingErrorField.SERIES_ICAL_UID),
            (self.provider_event_id, MeetingErrorField.PROVIDER_EVENT_ID),
            (self.provider_event_id_format, MeetingErrorField.PROVIDER_EVENT_ID_FORMAT),
        )
        if self.action is ReconcileItemAction.NO_PROVIDER_EVENT:
            for value, token in (
                (self.expected_version, MeetingErrorField.EXPECTED_VERSION),
                (self.provider_event_ref, MeetingErrorField.PROVIDER_EVENT_REF),
                *key_fields,
            ):
                if value is not None:
                    raise MeetingInvalidRequestError(token)
            if self.adopt_provider_series:
                raise MeetingInvalidRequestError(MeetingErrorField.ADOPT_PROVIDER_SERIES)
            return
        if (
            not isinstance(self.expected_version, int)
            or isinstance(self.expected_version, bool)
            or self.expected_version < 1
        ):
            raise MeetingInvalidRequestError(MeetingErrorField.EXPECTED_VERSION)
        if self.provider_event_ref is not None:
            # A reference names the whole key; any key field beside it is refused,
            # so a reference can never be mistaken for a different key.
            if not isinstance(self.provider_event_ref, str):
                raise MeetingInvalidRequestError(MeetingErrorField.PROVIDER_EVENT_REF)
            for value, token in key_fields:
                if value is not None:
                    raise MeetingInvalidRequestError(token)
            return
        # The full-key form: the key itself is validated by the bind request.
        if self.calendar_ref is None:
            raise MeetingInvalidRequestError(MeetingErrorField.PROVIDER_EVENT_REF)
