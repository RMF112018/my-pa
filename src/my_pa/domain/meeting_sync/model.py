"""Closed vocabularies and immutable records for a parsed `meeting_sync_v1` publication.

A publication is a list of calendar events, each keyed by the neutral calendar
reference, its iCalendar UID and, for an occurrence of a recurring series, the
occurrence's **original** start (never its current start), so a moved
occurrence keeps its identity (contract section 12.1). A single meeting has no
series UID and no original start; an occurrence has both (`series_key_incomplete`
otherwise).

Every field the Meeting plane would store is checked here against the Meeting
domain's own validators, so an event that reaches resolution can be written
exactly as stated: nothing is truncated, a time zone is a real zone, a link is
HTTPS, a title is 1..200 nonblank characters (Manager rulings D3/D4). Attendee
addresses use the Meeting attendee normalization
(`normalize_attendee_email`, the Relationship Intelligence EMAIL rule), and are
parsed and validated only: WP2 never applies them to a Meeting.

Events carry no body or description (Manager ruling D1).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.meeting.model import (
    AttendeeResponseStatus,
    MeetingError,
    MeetingStatus,
    NormalizedAttendee,
    normalize_attendee,
    validate_attendee_set,
    validate_meeting_location_text,
    validate_meeting_title,
    validate_timezone_name,
    validate_virtual_meeting_url,
)
from my_pa.domain.meeting_sync.diagnostics import ReasonCode

__all__ = [
    "MAX_CALENDAR_REF_CHARACTERS",
    "MAX_ICAL_UID_CHARACTERS",
    "MAX_PROVIDER_EVENT_ID_CHARACTERS",
    "SCHEMA_NAME",
    "SUPPORTED_MAJOR",
    "EventStatus",
    "MeetingSyncEvent",
    "MeetingSyncPublication",
    "OccurrenceKey",
    "ProviderBindingState",
    "ProviderEventIdFormat",
    "QuarantinedEvent",
    "SchemaVersion",
    "SyncAttendee",
    "normalized_attendees",
    "representability_reasons",
]

SCHEMA_NAME: Final = "meeting_sync_v1"
SUPPORTED_MAJOR: Final = 1

#: The binding table bounds (migration frozen literals).
MAX_CALENDAR_REF_CHARACTERS: Final = 320
MAX_ICAL_UID_CHARACTERS: Final = 1024
MAX_PROVIDER_EVENT_ID_CHARACTERS: Final = 1024


class EventStatus(StrEnum):
    """The provider's event status, in the publication's own neutral spelling."""

    CONFIRMED = "confirmed"
    TENTATIVE = "tentative"
    CANCELLED = "cancelled"


class ProviderEventIdFormat(StrEnum):
    """Whether the provider event id is stable. Attribute only, never identity."""

    IMMUTABLE_VERIFIED = "immutable_verified"
    MUTABLE = "mutable"
    UNKNOWN = "unknown"


class ProviderBindingState(StrEnum):
    """A binding's last observed provider state (C10). WP2 never writes `not_seen`."""

    ACTIVE = "active"
    CANCELLED = "cancelled"
    NOT_SEEN = "not_seen"


@dataclass(frozen=True, slots=True)
class SchemaVersion:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True, slots=True)
class OccurrenceKey:
    """The provider identity of one Meeting (contract section 12.1).

    `original_start_utc is None` is a single meeting; otherwise an occurrence.
    """

    calendar_ref: str
    ical_uid: str
    original_start_utc: datetime | None

    @property
    def is_occurrence(self) -> bool:
        return self.original_start_utc is not None


@dataclass(frozen=True, slots=True)
class SyncAttendee:
    """One parsed attendee: a normalized address, never applied in WP2."""

    email_normalized: str
    display_name: str | None
    is_organizer: bool
    response_status: AttendeeResponseStatus


@dataclass(frozen=True, slots=True)
class MeetingSyncEvent:
    """One accepted event record, every stored field already representable.

    Construct through the parser, which checks `representability_reasons` first;
    an event that reaches here is never refused by the Meeting validators.
    """

    ordinal: int
    calendar_ref: str
    ical_uid: str
    series_ical_uid: str | None
    occurrence_original_start_utc: datetime | None
    start_utc: datetime
    end_utc: datetime
    timezone_name: str
    status: EventStatus
    provider_event_id: str | None
    provider_event_id_format: ProviderEventIdFormat
    title: str
    location_text: str | None
    virtual_meeting_url: str | None
    #: The publication's `generated_at_utc` (WP2-F1): the record's ordering
    #: stamp, compared with the binding's `last_applied_generated_at_utc`.
    generated_at_utc: datetime
    attendees: tuple[SyncAttendee, ...] = ()

    @property
    def key(self) -> OccurrenceKey:
        return OccurrenceKey(self.calendar_ref, self.ical_uid, self.occurrence_original_start_utc)

    @property
    def meeting_status(self) -> MeetingStatus:
        """`confirmed` and `tentative` are a scheduled Meeting; `cancelled` is cancelled."""
        if self.status is EventStatus.CANCELLED:
            return MeetingStatus.CANCELLED
        return MeetingStatus.SCHEDULED

    @property
    def provider_state(self) -> ProviderBindingState:
        if self.status is EventStatus.CANCELLED:
            return ProviderBindingState.CANCELLED
        return ProviderBindingState.ACTIVE


@dataclass(frozen=True, slots=True)
class QuarantinedEvent:
    """A record that was not accepted: its ordinal and closed reasons, no content."""

    ordinal: int
    reasons: tuple[ReasonCode, ...]


@dataclass(frozen=True, slots=True)
class MeetingSyncPublication:
    schema_version: SchemaVersion
    generated_at_utc: datetime
    record_count: int
    events: tuple[MeetingSyncEvent, ...]
    quarantined: tuple[QuarantinedEvent, ...]


def _refused(check: Callable[[object], object], value: object) -> bool:
    try:
        check(value)
    except MeetingError:
        return True
    return False


def _bounded(value: str, maximum: int) -> bool:
    return 1 <= len(value) <= maximum and value.strip() != ""


def representability_reasons(
    *,
    calendar_ref: str,
    ical_uid: str,
    series_ical_uid: str | None,
    occurrence_original_start_utc: datetime | None,
    start_utc: datetime,
    end_utc: datetime,
    timezone_name: str,
    all_day: bool,
    provider_event_id: str | None,
    title: str,
    location_text: str | None,
    virtual_meeting_url: str | None,
    attendees: tuple[dict[str, object], ...],
) -> tuple[ReasonCode, ...]:
    """Every reason the Meeting plane could not hold this event exactly, sorted.

    Empty means representable. Types are the parser's concern; this checks values.
    """
    reasons: set[ReasonCode] = set()
    identifiers_ok = (
        _bounded(calendar_ref, MAX_CALENDAR_REF_CHARACTERS)
        and _bounded(ical_uid, MAX_ICAL_UID_CHARACTERS)
        and (series_ical_uid is None or _bounded(series_ical_uid, MAX_ICAL_UID_CHARACTERS))
        and (
            provider_event_id is None
            or _bounded(provider_event_id, MAX_PROVIDER_EVENT_ID_CHARACTERS)
        )
    )
    if not identifiers_ok:
        reasons.add(ReasonCode.IDENTIFIER_UNREPRESENTABLE)
    if (series_ical_uid is None) != (occurrence_original_start_utc is None):
        reasons.add(ReasonCode.SERIES_KEY_INCOMPLETE)
    if all_day:
        reasons.add(ReasonCode.ALL_DAY_UNSUPPORTED)
    if end_utc < start_utc:
        reasons.add(ReasonCode.END_BEFORE_START)
    if _refused(validate_meeting_title, title):
        reasons.add(ReasonCode.TITLE_UNREPRESENTABLE)
    if _refused(validate_timezone_name, timezone_name):
        reasons.add(ReasonCode.TIMEZONE_NOT_IANA)
    if location_text is not None and _refused(validate_meeting_location_text, location_text):
        reasons.add(ReasonCode.LOCATION_UNREPRESENTABLE)
    if virtual_meeting_url is not None and _refused(
        validate_virtual_meeting_url, virtual_meeting_url
    ):
        reasons.add(ReasonCode.URL_UNREPRESENTABLE)
    if normalized_attendees(attendees) is None:
        reasons.add(ReasonCode.ATTENDEES_UNREPRESENTABLE)
    return tuple(sorted(reasons, key=lambda member: member.value))


def normalized_attendees(
    attendees: tuple[dict[str, object], ...],
) -> tuple[SyncAttendee, ...] | None:
    """The attendee set under the Meeting attendee rules, or `None` when refused.

    Each attendee needs an address (normalized casefold, the Meeting EMAIL rule);
    the set is held to the Meeting bounds (at most 100, no duplicate address,
    at most one organizer). Output is in Meeting digest order.
    """
    members: list[NormalizedAttendee] = []
    try:
        for entry in attendees:
            if entry.get("email") is None:
                return None
            members.append(
                normalize_attendee(
                    display_name=entry.get("display_name"),
                    email=entry.get("email"),
                    is_organizer=entry.get("is_organizer", False),
                    response_status=entry.get("response_status", AttendeeResponseStatus.UNKNOWN),
                )
            )
        ordered = validate_attendee_set(members)
    except MeetingError:
        return None
    return tuple(
        SyncAttendee(
            email_normalized=member.email_normalized or "",
            display_name=member.display_name,
            is_organizer=member.is_organizer,
            response_status=member.response_status,
        )
        for member in ordered
    )
