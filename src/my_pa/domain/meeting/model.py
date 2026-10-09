"""WP-MTG-01: the Meeting records domain vocabulary, rules and request values.

Pure domain: nothing here persists, mints an identifier, reads a clock, or
reaches the application layer. It fixes what a Meeting *is* so the persistence
(WP-MTG-02) and application (WP-MTG-03) layers cannot disagree about it:

* the closed enums every Meeting column, filter and receipt draws from;
* the bounds each human field is held to (package sections 34.10, 35.6, 35.8);
* the validators that apply those bounds to a caller's value and return the
  exact form that is stored -- in particular `validate_virtual_meeting_url`,
  which *validates* an HTTPS URL and then returns the caller's string
  unchanged, because section 35.6 replaces "normalized URL" with "exact
  accepted string";
* the attendee rules (normalization through the Relationship Intelligence
  EMAIL rule, duplicate precedence, one organizer);
* the note-body composition helpers;
* the normalized, immutable request values the application consumes;
* the three write-capability names (plan D-21), declared here because the
  `Capability` members that carry them do not exist until WP-MTG-04;
* the closed domain Meeting error family (plan D-20), whose only payload is a
  field *token* -- never a rejected value.

**No request value carries a Principal.** The authenticated `principal_id` is a
parameter of every application call (plan D-24), never an attribute a caller
could have stated.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.common.time import NaiveDatetimeError, ensure_utc
from my_pa.domain.relationship.normalization import (
    ExternalIdentifierNamespace,
    NormalizationError,
    normalize_identifier,
)
from my_pa.domain.search.query import MAX_QUERY_CHARACTERS

__all__ = [
    "DEFAULT_MEETING_PAGE_SIZE",
    "MAX_ATTENDEE_DISPLAY_NAME_CHARACTERS",
    "MAX_ATTENDEE_EMAIL_CHARACTERS",
    "MAX_MEETING_ATTACHMENTS",
    "MAX_MEETING_ATTENDEES",
    "MAX_MEETING_CLEAR_FIELDS",
    "MAX_MEETING_DESCRIPTION_CHARACTERS",
    "MAX_MEETING_IDEMPOTENCY_KEY_CHARACTERS",
    "MAX_MEETING_LOCATION_CHARACTERS",
    "MAX_MEETING_NOTES_CHARACTERS",
    "MAX_MEETING_PAGE_SIZE",
    "MAX_MEETING_QUERY_CHARACTERS",
    "MAX_MEETING_TITLE_CHARACTERS",
    "MAX_TIMEZONE_NAME_CHARACTERS",
    "MAX_VIRTUAL_MEETING_URL_CHARACTERS",
    "MEETINGS_CREATE_NAME",
    "MEETINGS_SERIES_UPDATE_NAME",
    "MEETINGS_UPDATE_NAME",
    "MEETING_NOTE_SEPARATOR",
    "MEETING_WRITE_CAPABILITY_NAMES",
    "MIN_MEETING_IDEMPOTENCY_KEY_CHARACTERS",
    "AttendeeResponseStatus",
    "MeetingActor",
    "MeetingAttachmentAvailability",
    "MeetingClearField",
    "MeetingCreateRequest",
    "MeetingCursorError",
    "MeetingError",
    "MeetingErrorField",
    "MeetingHistoryAction",
    "MeetingIdempotencyConflictError",
    "MeetingInvalidRequestError",
    "MeetingListRequest",
    "MeetingNotFoundError",
    "MeetingNotesMode",
    "MeetingOutcome",
    "MeetingSearchRequest",
    "MeetingSeriesSelector",
    "MeetingSeriesUpdateRequest",
    "MeetingSortDirection",
    "MeetingStaleVersionError",
    "MeetingStatus",
    "MeetingTimeScope",
    "MeetingUnavailableError",
    "MeetingUpdateRequest",
    "NormalizedAttendee",
    "attendee_digest_sort_key",
    "compose_appended_note",
    "compose_note_body",
    "normalize_attendee",
    "normalize_attendee_email",
    "note_content_sha256",
    "validate_attendee_set",
    "validate_aware_instant",
    "validate_cancellation_pairing",
    "validate_meeting_description",
    "validate_meeting_location_text",
    "validate_meeting_notes_markdown",
    "validate_meeting_time_range",
    "validate_meeting_title",
    "validate_timezone_name",
    "validate_virtual_meeting_url",
]


# --------------------------------------------------------------------------- enums


class MeetingStatus(StrEnum):
    """A Meeting's reversible state. There is no deleted state (AC-008)."""

    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"


class AttendeeResponseStatus(StrEnum):
    """An attendee's closed response vocabulary (section 34.10)."""

    UNKNOWN = "unknown"
    NEEDS_ACTION = "needs_action"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    TENTATIVE = "tentative"


class MeetingHistoryAction(StrEnum):
    """What a Meeting or MeetingSeries history receipt records."""

    CREATE = "create"
    UPDATE = "update"


class MeetingActor(StrEnum):
    """Who a history receipt attributes the write to.

    v1 writes record `PRINCIPAL` only (readiness F020); the other two members are
    the closed vocabulary the history columns admit.
    """

    PRINCIPAL = "principal"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MeetingOutcome(StrEnum):
    """Whether a write changed state or normalized to no material change."""

    APPLIED = "applied"
    NO_OP = "no_op"


class MeetingNotesMode(StrEnum):
    """How supplied note content combines with the current note head."""

    APPEND = "append"
    REPLACE = "replace"


class MeetingClearField(StrEnum):
    """The scalar fields `meetings.update` may clear to SQL NULL.

    A clear is always explicit: `null` is never an implicit clear (section 19.6).
    """

    END_AT = "end_at"
    LOCATION_TEXT = "location_text"
    VIRTUAL_MEETING_URL = "virtual_meeting_url"
    DESCRIPTION = "description"
    PROJECT_ID = "project_id"


class MeetingAttachmentAvailability(StrEnum):
    """A read's projection of an attached ManagedDocument (section 34.11)."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    UNAVAILABLE = "unavailable"


class MeetingTimeScope(StrEnum):
    """The `time_scope` list/search filter (section 34.13)."""

    ALL = "all"
    UPCOMING = "upcoming"
    PAST = "past"


class MeetingSortDirection(StrEnum):
    """Keyset direction over `(start_at, meeting_id)`."""

    ASC = "asc"
    DESC = "desc"


class MeetingSeriesSelector(StrEnum):
    """The three legal series-selector states of `meetings.create` (section 35.8).

    A: neither `meeting_series_id` nor `series_title` -- a standalone Meeting,
    with no fabricated singleton series (AC-003). B: `series_title` only -- a new
    series and its first occurrence, one request identity. C: `meeting_series_id`
    only -- an occurrence of an existing series. Both at once is refused.
    """

    STANDALONE = "standalone"
    NEW_SERIES = "new_series"
    EXISTING_SERIES = "existing_series"


# -------------------------------------------------------------------------- bounds

#: Title and series title: 1..200 code points, at least one non-whitespace one.
MAX_MEETING_TITLE_CHARACTERS: Final = 200
MAX_MEETING_LOCATION_CHARACTERS: Final = 500
MAX_MEETING_DESCRIPTION_CHARACTERS: Final = 100_000
#: Notes: 1..100000 nonblank on input, and the *final* composed body too.
MAX_MEETING_NOTES_CHARACTERS: Final = 100_000
MAX_ATTENDEE_DISPLAY_NAME_CHARACTERS: Final = 200
MAX_ATTENDEE_EMAIL_CHARACTERS: Final = 320
MAX_TIMEZONE_NAME_CHARACTERS: Final = 64
MAX_VIRTUAL_MEETING_URL_CHARACTERS: Final = 2048
MAX_MEETING_ATTENDEES: Final = 100
MAX_MEETING_ATTACHMENTS: Final = 50
MAX_MEETING_CLEAR_FIELDS: Final = len(MeetingClearField)
DEFAULT_MEETING_PAGE_SIZE: Final = 50
MAX_MEETING_PAGE_SIZE: Final = 100
#: The search plane's own bound, reused rather than restated.
MAX_MEETING_QUERY_CHARACTERS: Final = MAX_QUERY_CHARACTERS
#: Canonical key length 1..128 (section 35.6, readiness F014, plan D-16). No
#: character class and no 8-character minimum: the superseded 8..128 would turn
#: a valid short key into an internal error.
MIN_MEETING_IDEMPOTENCY_KEY_CHARACTERS: Final = 1
MAX_MEETING_IDEMPOTENCY_KEY_CHARACTERS: Final = 128

#: What `append` puts between the current note head and the supplied chunk.
MEETING_NOTE_SEPARATOR: Final = "\n\n"


# ------------------------------------------------------------------ error family


class MeetingErrorField(StrEnum):
    """The closed set of field tokens a Meeting error may carry (plan D-20).

    Every value is the value of an existing `SafeDetail` member or of one of the
    members section 35.16 adds, so the WP-MTG-04 translation is a lookup and
    never a new token. A token names a field and never what was in it.
    """

    # Section 35.16 additions.
    MEETING_ID = "meeting_id"
    MEETING_SERIES_ID = "meeting_series_id"
    ATTENDEES = "attendees"
    ATTENDEE_ID = "attendee_id"
    ATTACHMENT_ID = "attachment_id"
    TIMEZONE_NAME = "timezone_name"
    START_AT = "start_at"
    END_AT = "end_at"
    VIRTUAL_MEETING_URL = "virtual_meeting_url"
    NOTES = "notes"
    SERIES_SELECTOR = "series_selector"
    DUPLICATE_ATTENDEE = "duplicate_attendee"
    ORGANIZER = "organizer"
    LOCATION_TEXT = "location_text"
    DESCRIPTION = "description"
    RESPONSE_STATUS = "response_status"
    CLEAR_FIELDS = "clear_fields"
    # Existing `SafeDetail` members, reused.
    TITLE = "title"
    STATUS = "status"
    DOCUMENT_ID = "document_id"
    PROJECT_ID = "project_id"
    ENTITY_ID = "entity_id"
    EXPECTED_VERSION = "expected_version"
    IDEMPOTENCY_KEY = "idempotency_key"
    CURSOR = "cursor"
    QUERY = "query"
    PAGE_SIZE = "page_size"
    MUTATIONS = "mutations"


class MeetingError(ValueError):
    """Base of the closed domain Meeting error family.

    Carries a field token and nothing else: the message is built from the token
    alone, so no title, email, note body, URL, query text or rejected value can
    reach a log line or a public error through it.
    """

    _summary: str = "meeting request refused"

    def __init__(self, field: MeetingErrorField) -> None:
        self.field: MeetingErrorField = MeetingErrorField(field)
        super().__init__(f"{self._summary}: {self.field.value}")


class MeetingInvalidRequestError(MeetingError):
    """A malformed or out-of-bounds field, or a violated cross-field rule."""

    _summary = "invalid meeting request"


class MeetingNotFoundError(MeetingError):
    """An absent or foreign Meeting-plane reference; the two are indistinguishable."""

    _summary = "meeting reference not found"


class MeetingStaleVersionError(MeetingError):
    """`expected_version` no longer matches the locked row."""

    _summary = "stale meeting version"

    def __init__(self, field: MeetingErrorField = MeetingErrorField.EXPECTED_VERSION) -> None:
        super().__init__(field)


class MeetingIdempotencyConflictError(MeetingError):
    """The idempotency key was already used with a different request digest."""

    _summary = "meeting idempotency conflict"

    def __init__(self, field: MeetingErrorField = MeetingErrorField.IDEMPOTENCY_KEY) -> None:
        super().__init__(field)


class MeetingCursorError(MeetingError):
    """The `after` anchor is absent, foreign, or outside the current filter set."""

    _summary = "invalid meeting cursor"

    def __init__(self, field: MeetingErrorField = MeetingErrorField.CURSOR) -> None:
        super().__init__(field)


class MeetingUnavailableError(MeetingError):
    """Meeting storage or search is temporarily unavailable."""

    _summary = "meeting storage unavailable"


def _invalid(token: MeetingErrorField) -> MeetingInvalidRequestError:
    return MeetingInvalidRequestError(token)


# ---------------------------------------------------------------------- validators


def _is_blank(value: str) -> bool:
    return all(character.isspace() for character in value)


def _identifier(value: object, kind: IdKind, token: MeetingErrorField) -> str:
    """`value` as a validated identifier of `kind`, or a token-only refusal."""
    if not isinstance(value, str):
        raise _invalid(token)
    try:
        return validate_identifier(value, kind)
    except InvalidIdentifierError:
        raise _invalid(token) from None


def _optional_identifier(value: object, kind: IdKind, token: MeetingErrorField) -> str | None:
    return None if value is None else _identifier(value, kind, token)


def validate_meeting_title(
    value: object, *, token: MeetingErrorField = MeetingErrorField.TITLE
) -> str:
    """A Meeting or MeetingSeries title, returned exactly as supplied.

    1..200 code points with at least one non-whitespace character. Not stripped,
    collapsed, case-folded or Unicode-normalized (section 35.6).
    """
    if not isinstance(value, str):
        raise _invalid(token)
    if not 1 <= len(value) <= MAX_MEETING_TITLE_CHARACTERS or _is_blank(value):
        raise _invalid(token)
    return value


def validate_meeting_location_text(value: object) -> str:
    """`location_text` exactly as supplied; the empty string is a legal value."""
    if not isinstance(value, str) or len(value) > MAX_MEETING_LOCATION_CHARACTERS:
        raise _invalid(MeetingErrorField.LOCATION_TEXT)
    return value


def validate_meeting_description(value: object) -> str:
    """`description` exactly as supplied; stored as data, never trusted HTML."""
    if not isinstance(value, str) or len(value) > MAX_MEETING_DESCRIPTION_CHARACTERS:
        raise _invalid(MeetingErrorField.DESCRIPTION)
    return value


def validate_meeting_notes_markdown(value: object) -> str:
    """Supplied note content: 1..100000 characters, nonblank, stored exactly."""
    if not isinstance(value, str):
        raise _invalid(MeetingErrorField.NOTES)
    if not 1 <= len(value) <= MAX_MEETING_NOTES_CHARACTERS or _is_blank(value):
        raise _invalid(MeetingErrorField.NOTES)
    return value


def validate_timezone_name(value: object) -> str:
    """A retained civil/display zone: 1..64 characters naming a valid `ZoneInfo`.

    Validated independently of any timestamp: the zone is context, and the
    aware instant alone decides when the Meeting is (section 35.6).
    """
    token = MeetingErrorField.TIMEZONE_NAME
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_TIMEZONE_NAME_CHARACTERS:
        raise _invalid(token)
    if value != value.strip():
        raise _invalid(token)
    try:
        ZoneInfo(value)
    except (KeyError, ValueError, OSError):
        # `ZoneInfoNotFoundError` is a `KeyError`; a path-like key is a
        # `ValueError`. Neither message is carried: both quote the key.
        raise _invalid(token) from None
    return value


def validate_aware_instant(
    value: object, *, token: MeetingErrorField = MeetingErrorField.START_AT
) -> datetime:
    """An offset-aware instant canonicalized to UTC through `ensure_utc`.

    A naive wall time is refused, so the server never guesses a DST fold or a
    nonexistent local time. The supplied offset need not match any zone name.
    """
    if not isinstance(value, datetime):
        raise _invalid(token)
    try:
        return ensure_utc(value)
    except NaiveDatetimeError:
        raise _invalid(token) from None


def validate_meeting_time_range(start_at: datetime, end_at: datetime | None) -> None:
    """`end_at`, when present, is not before `start_at`; equality is zero duration."""
    if end_at is not None and ensure_utc(end_at) < ensure_utc(start_at):
        raise _invalid(MeetingErrorField.END_AT)


def validate_cancellation_pairing(status: MeetingStatus, cancelled_at: datetime | None) -> None:
    """`cancelled_at` is present exactly when the Meeting is cancelled."""
    if (status is MeetingStatus.CANCELLED) != (cancelled_at is not None):
        raise _invalid(MeetingErrorField.STATUS)


def validate_virtual_meeting_url(value: object) -> str:
    """An HTTPS meeting link, validated per section 35.6 and returned unchanged.

    The returned string is the caller's string: no host lowercasing, default
    port stripping, query reordering, escape rewriting, fragment removal or
    trailing-slash change. What is stored and digested is what was accepted.
    """
    token = MeetingErrorField.VIRTUAL_MEETING_URL
    if not isinstance(value, str):
        raise _invalid(token)
    if not 1 <= len(value) <= MAX_VIRTUAL_MEETING_URL_CHARACTERS:
        raise _invalid(token)
    if value != value.strip():
        raise _invalid(token)
    if any(ord(character) <= 0x20 or ord(character) == 0x7F for character in value):
        raise _invalid(token)
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise _invalid(token) from None
    if parsed.scheme.lower() != "https":
        raise _invalid(token)
    if not parsed.hostname:
        raise _invalid(token)
    if parsed.username is not None or parsed.password is not None:
        raise _invalid(token)
    try:
        _ = parsed.port
    except ValueError:
        raise _invalid(token) from None
    return value


# ------------------------------------------------------------------ attendee rules


@dataclass(frozen=True, slots=True)
class NormalizedAttendee:
    """One attendee after normalization: the stored snapshot and dedupe form.

    `display_name` is trimmed (and absent when it trims to empty);
    `email_normalized` is the Relationship Intelligence EMAIL form. At least one
    of the three identity signals is present. Construct through
    `normalize_attendee`.
    """

    display_name: str | None
    email_normalized: str | None
    entity_id: str | None
    is_organizer: bool
    response_status: AttendeeResponseStatus


def normalize_attendee_email(value: object) -> str:
    """An attendee email in the one canonical form Meeting stores and compares.

    `normalize_identifier(ExternalIdentifierNamespace.EMAIL, raw)` -- the existing
    Relationship Intelligence rule, not a second normalizer (section 35.6).
    """
    token = MeetingErrorField.ATTENDEES
    if not isinstance(value, str) or len(value) > MAX_ATTENDEE_EMAIL_CHARACTERS:
        raise _invalid(token)
    try:
        normalized = normalize_identifier(ExternalIdentifierNamespace.EMAIL, value)
    except NormalizationError:
        raise _invalid(token) from None
    if len(normalized) > MAX_ATTENDEE_EMAIL_CHARACTERS:
        raise _invalid(token)
    return normalized


def normalize_attendee(
    *,
    display_name: object = None,
    email: object = None,
    entity_id: object = None,
    is_organizer: object = False,
    response_status: object = AttendeeResponseStatus.UNKNOWN,
) -> NormalizedAttendee:
    """Normalize one attendee input object (section 34.10, section 35.6).

    `entity_id` is checked for shape only here; that it names a same-Principal,
    ACTIVE Person is a same-transaction check the application makes. No contact
    or Entity is ever created from an email (AC-011).
    """
    name: str | None = None
    if display_name is not None:
        if not isinstance(display_name, str):
            raise _invalid(MeetingErrorField.ATTENDEES)
        if len(display_name) > MAX_ATTENDEE_DISPLAY_NAME_CHARACTERS:
            raise _invalid(MeetingErrorField.ATTENDEES)
        name = display_name.strip() or None
    email_normalized = None if email is None else normalize_attendee_email(email)
    entity = _optional_identifier(entity_id, IdKind.ENTITY, MeetingErrorField.ENTITY_ID)
    if not isinstance(is_organizer, bool):
        raise _invalid(MeetingErrorField.ORGANIZER)
    if not isinstance(response_status, str):
        raise _invalid(MeetingErrorField.RESPONSE_STATUS)
    try:
        status = AttendeeResponseStatus(response_status)
    except ValueError:
        raise _invalid(MeetingErrorField.RESPONSE_STATUS) from None
    if name is None and email_normalized is None and entity is None:
        raise _invalid(MeetingErrorField.ATTENDEES)
    return NormalizedAttendee(
        display_name=name,
        email_normalized=email_normalized,
        entity_id=entity,
        is_organizer=is_organizer,
        response_status=status,
    )


def attendee_digest_sort_key(attendee: NormalizedAttendee) -> tuple[str, str, str, bool, str]:
    """The deterministic attendee order a request digest serializes (section 35.9).

    `(entity_id-or-empty, email_normalized-or-empty, display_name-or-empty,
    is_organizer, response_status)` -- the section 35.9 order, which governs
    over section 34.14's (plan D-17).
    """
    return (
        attendee.entity_id or "",
        attendee.email_normalized or "",
        attendee.display_name or "",
        attendee.is_organizer,
        attendee.response_status.value,
    )


def validate_attendee_set(
    attendees: Iterable[NormalizedAttendee],
) -> tuple[NormalizedAttendee, ...]:
    """An active attendee set, checked and returned in digest order.

    Refused (section 34.10): more than 100; two with the same Entity; two with
    the same normalized email (which also covers the same Entity with different
    emails and the same email with different Entities); an exact duplicate
    object, including a name-only one; more than one organizer. The same display
    name alone is not identity and is allowed.
    """
    members = tuple(attendees)
    if len(members) > MAX_MEETING_ATTENDEES:
        raise _invalid(MeetingErrorField.ATTENDEES)
    if any(not isinstance(member, NormalizedAttendee) for member in members):
        raise _invalid(MeetingErrorField.ATTENDEES)
    entities = Counter(member.entity_id for member in members if member.entity_id is not None)
    emails = Counter(
        member.email_normalized for member in members if member.email_normalized is not None
    )
    if any(count > 1 for count in entities.values()):
        raise _invalid(MeetingErrorField.DUPLICATE_ATTENDEE)
    if any(count > 1 for count in emails.values()):
        raise _invalid(MeetingErrorField.DUPLICATE_ATTENDEE)
    if len(set(members)) != len(members):
        raise _invalid(MeetingErrorField.DUPLICATE_ATTENDEE)
    if sum(1 for member in members if member.is_organizer) > 1:
        raise _invalid(MeetingErrorField.ORGANIZER)
    return tuple(sorted(members, key=attendee_digest_sort_key))


# -------------------------------------------------------------------- note helpers


def _bounded_note(body: str) -> str:
    if len(body) > MAX_MEETING_NOTES_CHARACTERS:
        raise _invalid(MeetingErrorField.NOTES)
    return body


def compose_appended_note(prior: str | None, chunk: str) -> str:
    """The body an `append` produces: exactly `prior + "\\n\\n" + chunk`.

    With no current note the chunk is the whole first version. The chunk must be
    nonblank and the final body is held to 100000 characters (section 34.12).
    """
    supplied = validate_meeting_notes_markdown(chunk)
    if prior is None:
        return supplied
    return _bounded_note(prior + MEETING_NOTE_SEPARATOR + supplied)


def compose_note_body(mode: MeetingNotesMode, prior: str | None, supplied: str) -> str:
    """The body `mode` produces from the current head and the supplied content.

    `replace` stores the supplied content exactly; whether it is a no-op (exact
    equality with `prior`) is the application's decision, not a rewrite here.
    """
    if mode is MeetingNotesMode.APPEND:
        return compose_appended_note(prior, supplied)
    return validate_meeting_notes_markdown(supplied)


def note_content_sha256(body: str) -> str:
    """SHA-256 of the stored UTF-8 note body, lowercase hex."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ---------------------------------------------------------- request value objects


def _sorted_unique_identifiers(
    values: Iterable[object], kind: IdKind, token: MeetingErrorField, maximum: int
) -> tuple[str, ...]:
    members = tuple(_identifier(value, kind, token) for value in values)
    if len(members) > maximum or len(set(members)) != len(members):
        raise _invalid(token)
    return tuple(sorted(members))


def _optional_text(value: str | None, validator: Callable[[object], str]) -> str | None:
    return None if value is None else validator(value)


@dataclass(frozen=True, slots=True)
class MeetingCreateRequest:
    """A normalized `meetings.create` request (section 19.2, section 35.8).

    Timestamps are canonical UTC; the virtual URL is the exact accepted string;
    `attendees` is the validated set in digest order; `attachment_document_ids`
    is sorted. `series_selector` is the exact A/B/C state. The idempotency key and
    the Principal are not fields: both are parameters of the application call.
    """

    title: str
    start_at: datetime
    timezone_name: str
    end_at: datetime | None = None
    meeting_series_id: str | None = None
    series_title: str | None = None
    location_text: str | None = None
    virtual_meeting_url: str | None = None
    description: str | None = None
    project_id: str | None = None
    attendees: tuple[NormalizedAttendee, ...] = ()
    attachment_document_ids: tuple[str, ...] = ()
    notes_markdown: str | None = None
    series_selector: MeetingSeriesSelector = field(init=False)

    def __post_init__(self) -> None:
        validate_meeting_title(self.title)
        start_at = validate_aware_instant(self.start_at, token=MeetingErrorField.START_AT)
        validate_timezone_name(self.timezone_name)
        end_at = (
            None
            if self.end_at is None
            else validate_aware_instant(self.end_at, token=MeetingErrorField.END_AT)
        )
        validate_meeting_time_range(start_at, end_at)
        series_id = _optional_identifier(
            self.meeting_series_id, IdKind.MEETING_SERIES, MeetingErrorField.MEETING_SERIES_ID
        )
        if series_id is not None and self.series_title is not None:
            raise _invalid(MeetingErrorField.SERIES_SELECTOR)
        if self.series_title is not None:
            validate_meeting_title(self.series_title)
            selector = MeetingSeriesSelector.NEW_SERIES
        elif series_id is not None:
            selector = MeetingSeriesSelector.EXISTING_SERIES
        else:
            selector = MeetingSeriesSelector.STANDALONE
        _optional_text(self.location_text, validate_meeting_location_text)
        _optional_text(self.virtual_meeting_url, validate_virtual_meeting_url)
        _optional_text(self.description, validate_meeting_description)
        _optional_text(self.notes_markdown, validate_meeting_notes_markdown)
        _optional_identifier(self.project_id, IdKind.PROJECT, MeetingErrorField.PROJECT_ID)
        attendees = validate_attendee_set(self.attendees)
        documents = _sorted_unique_identifiers(
            self.attachment_document_ids,
            IdKind.MANAGED_DOCUMENT,
            MeetingErrorField.DOCUMENT_ID,
            MAX_MEETING_ATTACHMENTS,
        )
        object.__setattr__(self, "start_at", start_at)
        object.__setattr__(self, "end_at", end_at)
        object.__setattr__(self, "attendees", attendees)
        object.__setattr__(self, "attachment_document_ids", documents)
        object.__setattr__(self, "series_selector", selector)


@dataclass(frozen=True, slots=True)
class MeetingUpdateRequest:
    """A normalized `meetings.update` request (section 19.6, section 35.8).

    `None` on a scalar means *omitted* (unchanged), never a clear: a clear is
    only ever a `clear_fields` member. `attendees_replace is None` means
    unchanged; `()` means replace the active set with the empty set. Collections
    are sorted, so two semantically identical requests compare equal.
    `expected_version` and the idempotency key are parameters of the application
    call.

    Series membership is reassignable through `meetings.update` (operator
    decision 2026-10-09, retiring AC-007): an absent `meeting_series_id` leaves
    membership unchanged; a series id attaches or moves the Meeting to an
    existing series of the same principal (a missing or foreign series is
    refused as not found); an explicit null detaches it to standalone. The
    Meeting keeps its identity; a change bumps its version and is recorded in
    its history, receipt and Record Event. Here the three states are
    `meeting_series_id is None and not detach_series` (absent), a validated
    `meeting_series_id` (attach or move) and `detach_series=True` (detach); both
    together is invalid. `series_title` is never accepted on update.
    """

    meeting_id: str
    title: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    timezone_name: str | None = None
    status: MeetingStatus | None = None
    location_text: str | None = None
    virtual_meeting_url: str | None = None
    description: str | None = None
    project_id: str | None = None
    clear_fields: tuple[MeetingClearField, ...] = ()
    attendees_replace: tuple[NormalizedAttendee, ...] | None = None
    attachment_add_document_ids: tuple[str, ...] = ()
    attachment_remove_ids: tuple[str, ...] = ()
    notes_mode: MeetingNotesMode | None = None
    notes_markdown: str | None = None
    meeting_series_id: str | None = None
    detach_series: bool = False

    def __post_init__(self) -> None:
        _identifier(self.meeting_id, IdKind.MEETING, MeetingErrorField.MEETING_ID)
        if not isinstance(self.detach_series, bool):
            raise _invalid(MeetingErrorField.MEETING_SERIES_ID)
        if self.detach_series and self.meeting_series_id is not None:
            raise _invalid(MeetingErrorField.MEETING_SERIES_ID)
        _optional_identifier(
            self.meeting_series_id, IdKind.MEETING_SERIES, MeetingErrorField.MEETING_SERIES_ID
        )
        if self.title is not None:
            validate_meeting_title(self.title)
        start_at = (
            None
            if self.start_at is None
            else validate_aware_instant(self.start_at, token=MeetingErrorField.START_AT)
        )
        end_at = (
            None
            if self.end_at is None
            else validate_aware_instant(self.end_at, token=MeetingErrorField.END_AT)
        )
        if start_at is not None:
            validate_meeting_time_range(start_at, end_at)
        if self.timezone_name is not None:
            validate_timezone_name(self.timezone_name)
        status = None
        if self.status is not None:
            try:
                status = MeetingStatus(self.status)
            except ValueError:
                raise _invalid(MeetingErrorField.STATUS) from None
        _optional_text(self.location_text, validate_meeting_location_text)
        _optional_text(self.virtual_meeting_url, validate_virtual_meeting_url)
        _optional_text(self.description, validate_meeting_description)
        _optional_identifier(self.project_id, IdKind.PROJECT, MeetingErrorField.PROJECT_ID)
        clears = self._clear_fields()
        if self.project_id is not None and MeetingClearField.PROJECT_ID in clears:
            raise _invalid(MeetingErrorField.CLEAR_FIELDS)
        attendees = (
            None
            if self.attendees_replace is None
            else validate_attendee_set(self.attendees_replace)
        )
        added = _sorted_unique_identifiers(
            self.attachment_add_document_ids,
            IdKind.MANAGED_DOCUMENT,
            MeetingErrorField.DOCUMENT_ID,
            MAX_MEETING_ATTACHMENTS,
        )
        removed = _sorted_unique_identifiers(
            self.attachment_remove_ids,
            IdKind.MEETING_ATTACHMENT,
            MeetingErrorField.ATTACHMENT_ID,
            MAX_MEETING_ATTACHMENTS,
        )
        if set(added) & set(removed):
            raise _invalid(MeetingErrorField.ATTACHMENT_ID)
        notes_mode = self._notes_mode()
        object.__setattr__(self, "start_at", start_at)
        object.__setattr__(self, "end_at", end_at)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "clear_fields", clears)
        object.__setattr__(self, "attendees_replace", attendees)
        object.__setattr__(self, "attachment_add_document_ids", added)
        object.__setattr__(self, "attachment_remove_ids", removed)
        object.__setattr__(self, "notes_mode", notes_mode)
        if not self.has_material_selector:
            raise _invalid(MeetingErrorField.MUTATIONS)

    def _clear_fields(self) -> tuple[MeetingClearField, ...]:
        token = MeetingErrorField.CLEAR_FIELDS
        try:
            clears = tuple(MeetingClearField(value) for value in self.clear_fields)
        except (TypeError, ValueError):
            raise _invalid(token) from None
        if len(clears) > MAX_MEETING_CLEAR_FIELDS or len(set(clears)) != len(clears):
            raise _invalid(token)
        return tuple(sorted(clears, key=lambda member: member.value))

    def _notes_mode(self) -> MeetingNotesMode | None:
        if (self.notes_mode is None) != (self.notes_markdown is None):
            raise _invalid(MeetingErrorField.NOTES)
        if self.notes_mode is None:
            return None
        try:
            mode = MeetingNotesMode(self.notes_mode)
        except ValueError:
            raise _invalid(MeetingErrorField.NOTES) from None
        validate_meeting_notes_markdown(self.notes_markdown)
        return mode

    @property
    def has_material_selector(self) -> bool:
        """Whether at least one mutation was requested.

        Empty `clear_fields` and empty attachment arrays request nothing. A
        present `attendees_replace`, even empty, requests a replacement. A series
        id or `detach_series` requests a membership change.
        """
        scalars = (
            self.title,
            self.start_at,
            self.end_at,
            self.timezone_name,
            self.status,
            self.location_text,
            self.virtual_meeting_url,
            self.description,
            self.project_id,
            self.notes_mode,
            self.attendees_replace,
            self.meeting_series_id,
        )
        return (
            any(value is not None for value in scalars)
            or self.detach_series
            or bool(self.clear_fields)
            or bool(self.attachment_add_document_ids)
            or bool(self.attachment_remove_ids)
        )


@dataclass(frozen=True, slots=True)
class MeetingSeriesUpdateRequest:
    """A normalized `meetings.series.update` request: the series title only."""

    meeting_series_id: str
    title: str

    def __post_init__(self) -> None:
        _identifier(
            self.meeting_series_id, IdKind.MEETING_SERIES, MeetingErrorField.MEETING_SERIES_ID
        )
        validate_meeting_title(self.title)


@dataclass(frozen=True, slots=True)
class MeetingListRequest:
    """A normalized `meetings.list` filter set and page (section 19.4).

    Filters combine with AND. `start_at_from` is inclusive and `start_at_before`
    exclusive, and when both are present `start_at_from < start_at_before`.
    `attendee_email` is compared in its normalized EMAIL form. `after` is a
    Meeting keyset anchor that the persistence layer resolves inside the same
    Principal and the same filter set.
    """

    meeting_series_id: str | None = None
    project_id: str | None = None
    start_at_from: datetime | None = None
    start_at_before: datetime | None = None
    attendee_entity_id: str | None = None
    attendee_email: str | None = None
    status: MeetingStatus | None = None
    time_scope: MeetingTimeScope = MeetingTimeScope.ALL
    sort_direction: MeetingSortDirection = MeetingSortDirection.ASC
    page_size: int = DEFAULT_MEETING_PAGE_SIZE
    after: str | None = None

    def __post_init__(self) -> None:
        _optional_identifier(
            self.meeting_series_id, IdKind.MEETING_SERIES, MeetingErrorField.MEETING_SERIES_ID
        )
        _optional_identifier(self.project_id, IdKind.PROJECT, MeetingErrorField.PROJECT_ID)
        _optional_identifier(self.attendee_entity_id, IdKind.ENTITY, MeetingErrorField.ENTITY_ID)
        _optional_identifier(self.after, IdKind.MEETING, MeetingErrorField.CURSOR)
        start_from = (
            None
            if self.start_at_from is None
            else validate_aware_instant(self.start_at_from, token=MeetingErrorField.START_AT)
        )
        start_before = (
            None
            if self.start_at_before is None
            else validate_aware_instant(self.start_at_before, token=MeetingErrorField.START_AT)
        )
        if start_from is not None and start_before is not None and start_from >= start_before:
            raise _invalid(MeetingErrorField.START_AT)
        email = (
            None if self.attendee_email is None else normalize_attendee_email(self.attendee_email)
        )
        try:
            status = None if self.status is None else MeetingStatus(self.status)
        except ValueError:
            raise _invalid(MeetingErrorField.STATUS) from None
        try:
            time_scope = MeetingTimeScope(self.time_scope)
        except ValueError:
            raise _invalid(MeetingErrorField.START_AT) from None
        try:
            direction = MeetingSortDirection(self.sort_direction)
        except ValueError:
            raise _invalid(MeetingErrorField.CURSOR) from None
        page_size: object = self.page_size
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= MAX_MEETING_PAGE_SIZE
        ):
            raise _invalid(MeetingErrorField.PAGE_SIZE)
        object.__setattr__(self, "start_at_from", start_from)
        object.__setattr__(self, "start_at_before", start_before)
        object.__setattr__(self, "attendee_email", email)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "time_scope", time_scope)
        object.__setattr__(self, "sort_direction", direction)


@dataclass(frozen=True, slots=True)
class MeetingSearchRequest:
    """A normalized `meetings.search` request: a query plus the exact list filters.

    The query is kept exactly as supplied (1..512 characters, nonblank); it is a
    search input and is never echoed into an error or a log.
    """

    query: str
    filters: MeetingListRequest = field(default_factory=MeetingListRequest)

    def __post_init__(self) -> None:
        query: object = self.query
        if (
            not isinstance(query, str)
            or not 1 <= len(query) <= MAX_MEETING_QUERY_CHARACTERS
            or _is_blank(query)
        ):
            raise _invalid(MeetingErrorField.QUERY)
        filters: object = self.filters
        if not isinstance(filters, MeetingListRequest):
            raise _invalid(MeetingErrorField.QUERY)


# ------------------------------------------------------------ capability names

#: The three Meeting write-capability names (plan D-21). WP-MTG-04 asserts each
#: `Capability.MEETINGS_*.value` equals its constant here, and the migration's
#: frozen `meeting_write_requests.capability` CHECK literals are these strings.
MEETINGS_CREATE_NAME: Final = "meetings.create"
MEETINGS_UPDATE_NAME: Final = "meetings.update"
MEETINGS_SERIES_UPDATE_NAME: Final = "meetings.series.update"
MEETING_WRITE_CAPABILITY_NAMES: Final = frozenset(
    {MEETINGS_CREATE_NAME, MEETINGS_UPDATE_NAME, MEETINGS_SERIES_UPDATE_NAME}
)
