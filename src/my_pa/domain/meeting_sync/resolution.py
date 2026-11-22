"""Meeting provider identity and recurrence resolution (contract section 12.2).

Pure decisions over state the application has already read under lock:

1. a known occurrence key updates the bound Meeting -- only the provider-owned
   fields (Manager ruling D2: `start_at`, `end_at`, `timezone_name`, `status`,
   `title`, `location_text`, `virtual_meeting_url`), never attendees,
   description, notes, prep, project or attachments;
2. an unknown occurrence of a known series creates a Meeting in that series;
3. an unknown series creates the series (`series_title` = the event title)
   with its first occurrence; the application binds both (D7);
4. resolution never matches by title or time: an existing unbound Meeting is
   bound only by the explicit `meetings.provider.bind` reconciliation (W3);
5. a cancelled event with a known key cancels the Meeting, never deletes it; a
   cancelled event with an unknown key creates nothing (D5,
   `cancelled_unknown_skipped`);
6. a changed provider event id with the same key is the same Meeting: the id is
   a binding attribute, never part of the key;
7. a known key is applied only in publication order (WP2-F1): the event's
   `generated_at_utc` stamp is compared with the binding's
   `last_applied_generated_at_utc`. A strictly older stamp is skipped
   (`stale_record_skipped`); an equal stamp from a different publication (a
   different `last_seen_source_sha256`) is ambiguous and skipped
   (`ordering_conflict_skipped`); either skip writes nothing. An equal stamp
   from the same publication is the idempotent replay path, and a newer stamp,
   or a binding with no stamp yet (an explicit bind), applies as rules 1, 5, 6.
   A no-change record still stores its stamp, so a later older record is
   recognised.

A single meeting and occurrences of one `(calendar_ref, ical_uid)` are mutually
exclusive in v1 (D9): an event whose UID is already bound as the other kind is
refused (`binding_kind_conflict`) rather than given a second identity.

Re-applying an identical event changes nothing: `provider_update` answers `None`
when every provider-owned field already matches, and `refreshed_binding` answers
`None` when the binding already records this exact observation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.meeting.model import (
    MeetingClearField,
    MeetingCreateRequest,
    MeetingStatus,
    MeetingUpdateRequest,
)
from my_pa.domain.meeting_sync.model import (
    MeetingSyncEvent,
    OccurrenceKey,
    ProviderBindingState,
    ProviderEventIdFormat,
)

__all__ = [
    "SYNC_IDEMPOTENCY_KEY_PREFIX",
    "BindingAttributes",
    "KnownOccurrence",
    "ProviderFields",
    "Resolution",
    "ResolutionDiagnostic",
    "ResolutionKind",
    "ordering_skip",
    "provider_create",
    "provider_update",
    "refreshed_binding",
    "resolve_event",
    "sync_idempotency_key",
]

#: Every sync write's idempotency key starts with this, so it can never be
#: mistaken for a client key in `meeting_write_requests`.
SYNC_IDEMPOTENCY_KEY_PREFIX: Final = "mpsync_"


class ResolutionKind(StrEnum):
    UPDATE_BOUND = "update_bound"
    CREATE_IN_SERIES = "create_in_series"
    CREATE_SERIES = "create_series"
    CREATE_STANDALONE = "create_standalone"
    SKIP = "skip"


class ResolutionDiagnostic(StrEnum):
    """Why an event was skipped. Content-free."""

    CANCELLED_UNKNOWN_SKIPPED = "cancelled_unknown_skipped"
    BINDING_KIND_CONFLICT = "binding_kind_conflict"
    STALE_RECORD_SKIPPED = "stale_record_skipped"
    ORDERING_CONFLICT_SKIPPED = "ordering_conflict_skipped"


@dataclass(frozen=True, slots=True)
class KnownOccurrence:
    """The binding the event's occurrence key already resolves to."""

    binding_id: str
    meeting_id: str
    #: The binding's ordering stamp and last publication digest (rule 7).
    last_applied_generated_at_utc: datetime | None = None
    last_seen_source_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class Resolution:
    kind: ResolutionKind
    meeting_id: str | None = None
    meeting_series_id: str | None = None
    diagnostic: ResolutionDiagnostic | None = None


def ordering_skip(
    event: MeetingSyncEvent, bound: KnownOccurrence, *, source_sha256: str
) -> ResolutionDiagnostic | None:
    """Rule 7: why a known key's event must not be applied, or `None` to apply it."""
    applied = bound.last_applied_generated_at_utc
    if applied is None:
        return None
    if event.generated_at_utc < applied:
        return ResolutionDiagnostic.STALE_RECORD_SKIPPED
    if event.generated_at_utc == applied and bound.last_seen_source_sha256 != source_sha256:
        return ResolutionDiagnostic.ORDERING_CONFLICT_SKIPPED
    return None


def resolve_event(
    event: MeetingSyncEvent,
    *,
    bound: KnownOccurrence | None,
    series_id: str | None,
    other_kind_bound: bool,
    source_sha256: str,
) -> Resolution:
    """Rules 1-7 above. `series_id` is the series the event's series UID is bound to.

    `other_kind_bound` is whether the event's `(calendar_ref, ical_uid)` is bound
    as the other kind (a single meeting when this is an occurrence, or the
    reverse). `source_sha256` is the digest of the event's publication (rule 7).
    """
    if bound is not None:
        skipped = ordering_skip(event, bound, source_sha256=source_sha256)
        if skipped is not None:
            return Resolution(ResolutionKind.SKIP, meeting_id=bound.meeting_id, diagnostic=skipped)
        return Resolution(ResolutionKind.UPDATE_BOUND, meeting_id=bound.meeting_id)
    if event.meeting_status is MeetingStatus.CANCELLED:
        return Resolution(
            ResolutionKind.SKIP, diagnostic=ResolutionDiagnostic.CANCELLED_UNKNOWN_SKIPPED
        )
    if other_kind_bound:
        return Resolution(
            ResolutionKind.SKIP, diagnostic=ResolutionDiagnostic.BINDING_KIND_CONFLICT
        )
    if not event.key.is_occurrence:
        return Resolution(ResolutionKind.CREATE_STANDALONE)
    if series_id is not None:
        return Resolution(ResolutionKind.CREATE_IN_SERIES, meeting_series_id=series_id)
    return Resolution(ResolutionKind.CREATE_SERIES)


@dataclass(frozen=True, slots=True)
class ProviderFields:
    """The provider-owned state of one Meeting (D2), as currently stored."""

    title: str
    start_at: datetime
    end_at: datetime | None
    timezone_name: str
    status: MeetingStatus
    location_text: str | None
    virtual_meeting_url: str | None


def provider_update(
    meeting_id: str, current: ProviderFields, event: MeetingSyncEvent
) -> MeetingUpdateRequest | None:
    """The `meetings.update` request carrying exactly the provider-owned changes.

    `None` when nothing the provider owns differs. A provider field that became
    absent (a location or link) is an explicit clear. Nothing else is ever named.
    """
    clears: list[MeetingClearField] = []
    title = None if current.title == event.title else event.title
    start_at = None if current.start_at == event.start_utc else event.start_utc
    end_at = None if current.end_at == event.end_utc else event.end_utc
    timezone_name = None if current.timezone_name == event.timezone_name else event.timezone_name
    status = None if current.status is event.meeting_status else event.meeting_status
    location_text: str | None = None
    if current.location_text != event.location_text:
        if event.location_text is None:
            clears.append(MeetingClearField.LOCATION_TEXT)
        else:
            location_text = event.location_text
    virtual_meeting_url: str | None = None
    if current.virtual_meeting_url != event.virtual_meeting_url:
        if event.virtual_meeting_url is None:
            clears.append(MeetingClearField.VIRTUAL_MEETING_URL)
        else:
            virtual_meeting_url = event.virtual_meeting_url
    supplied = (title, start_at, end_at, timezone_name, status, location_text, virtual_meeting_url)
    if all(value is None for value in supplied) and not clears:
        return None
    if start_at is not None and end_at is None:
        # The request validates the supplied pair; the merged end is the event's.
        end_at = event.end_utc
    return MeetingUpdateRequest(
        meeting_id=meeting_id,
        title=title,
        start_at=start_at,
        end_at=end_at,
        timezone_name=timezone_name,
        status=status,
        location_text=location_text,
        virtual_meeting_url=virtual_meeting_url,
        clear_fields=tuple(clears),
    )


def provider_create(
    event: MeetingSyncEvent, *, meeting_series_id: str | None = None, new_series: bool = False
) -> MeetingCreateRequest:
    """The `meetings.create` request for an unknown, non-cancelled event (rules 2, 3)."""
    return MeetingCreateRequest(
        title=event.title,
        start_at=event.start_utc,
        end_at=event.end_utc,
        timezone_name=event.timezone_name,
        meeting_series_id=meeting_series_id,
        series_title=event.title if new_series else None,
        location_text=event.location_text,
        virtual_meeting_url=event.virtual_meeting_url,
    )


@dataclass(frozen=True, slots=True)
class BindingAttributes:
    """A binding's mutable attributes: never part of its identity (rule 6)."""

    provider_event_id: str | None
    provider_event_id_format: ProviderEventIdFormat
    provider_state: ProviderBindingState
    last_seen_source_sha256: str | None
    last_seen_record_ordinal: int | None
    last_seen_at: datetime | None
    last_applied_generated_at_utc: datetime | None = None


def refreshed_binding(
    current: BindingAttributes,
    event: MeetingSyncEvent,
    *,
    source_sha256: str,
    seen_at: datetime,
) -> tuple[BindingAttributes, bool] | None:
    """The binding's attributes after observing `event`, and whether they are material.

    `None` when the binding already records this exact observation (the same
    publication digest and ordinal, the same provider attributes): an identical
    replay. The ordering stamp is always the event's (rule 7), so a no-change
    record still records it. Material means a provider attribute changed (`provider_event_id`, its
    format, `provider_state`), which is what bumps the binding version; a new
    observation of identical attributes only refreshes `last_seen_*`.
    """
    after = BindingAttributes(
        provider_event_id=event.provider_event_id,
        provider_event_id_format=event.provider_event_id_format,
        provider_state=event.provider_state,
        last_seen_source_sha256=source_sha256,
        last_seen_record_ordinal=event.ordinal,
        last_seen_at=seen_at,
        last_applied_generated_at_utc=event.generated_at_utc,
    )
    material = (
        current.provider_event_id != after.provider_event_id
        or current.provider_event_id_format is not after.provider_event_id_format
        or current.provider_state is not after.provider_state
    )
    same_observation = (
        current.last_seen_source_sha256 == source_sha256
        and current.last_seen_record_ordinal == event.ordinal
    )
    if same_observation and not material:
        return None
    return after, material


def sync_idempotency_key(key: OccurrenceKey, *, source_sha256: str, record_ordinal: int) -> str:
    """The deterministic `meeting_write_requests` key of one applied record.

    SHA-256 over canonical JSON of (binding key, source SHA-256, record ordinal),
    prefixed: 71 characters, inside the 1..128 Meeting key bound.
    """
    original = (
        None
        if key.original_start_utc is None
        else key.original_start_utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    )
    document = [key.calendar_ref, key.ical_uid, original, source_sha256, record_ordinal]
    canonical = json.dumps(document, separators=(",", ":"), ensure_ascii=False)
    return SYNC_IDEMPOTENCY_KEY_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
