"""The public shapes of a Meeting answer (WP-MTG-01, package section 34.18).

Eight models: `MeetingView` for a full read and every write result,
`MeetingListEntry` for a `meetings.list`/`meetings.search` row, `MeetingSeriesView`,
the three child views a full read nests (`MeetingAttendeeView`,
`MeetingAttachmentView`, `MeetingNoteView`), and the two immutable history
receipts (`MeetingHistoryView`, `MeetingSeriesHistoryView`). Record lineage S1
(S1 contract section 7.2) appends the two note-history shapes:
`MeetingNoteVersionEntry` (a `meetings.notes.versions` row: no body and no
digest) and `MeetingNoteVersionView` (`meetings.notes.read_version`: the stored
content digest, and the body only when the caller asked for it). ADR-020 C4/C6
appends `MeetingPrepView`, one immutable prep-brief version, which `MeetingView`
nests twice: `prep` (the current head, on every answer) and `prep_version` (the
exact version a `meetings.read` asked for by `prep_version_number`, else `None`).

**What these models cannot carry is the point of them.**

*No Principal.* The caller already acts inside its own partition; echoing a
`principal_id` would make every answer a place another Principal's identifier
could appear if a filter ever broke.

*No request identity.* Neither receipt has an `idempotency_key` or a
`request_digest`: those are the server's arbitration of a write, not part of
what the write did.

*Minimal list rows.* `MeetingListEntry` has no description, no virtual link, no
attendee identity or email and no note body -- there is no field on it any of
them could go in. A full read is the only answer that carries them.

*No storage location.* An attachment is projected as the ManagedDocument's
current safe title, media type and availability. An `unavailable` projection has
a nullable title and media type and never a path, locator or foreign owner.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from my_pa.contracts.v1.base import StrictModel, UtcDatetime
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.documents.managed import MANAGED_MEDIA_TYPES, MAX_MANAGED_TITLE_CHARACTERS
from my_pa.domain.meeting.model import (
    MAX_ATTENDEE_DISPLAY_NAME_CHARACTERS,
    MAX_ATTENDEE_EMAIL_CHARACTERS,
    MAX_MEETING_ATTACHMENTS,
    MAX_MEETING_ATTENDEES,
    MAX_MEETING_DESCRIPTION_CHARACTERS,
    MAX_MEETING_LOCATION_CHARACTERS,
    MAX_MEETING_NOTES_CHARACTERS,
    MAX_MEETING_PREP_CHARACTERS,
    MAX_MEETING_TITLE_CHARACTERS,
    MAX_TIMEZONE_NAME_CHARACTERS,
    MAX_VIRTUAL_MEETING_URL_CHARACTERS,
    AttendeeResponseStatus,
    MeetingActor,
    MeetingAttachmentAvailability,
    MeetingHistoryAction,
    MeetingOutcome,
    MeetingStatus,
    validate_cancellation_pairing,
    validate_meeting_notes_markdown,
    validate_meeting_prep_markdown,
    validate_meeting_time_range,
    validate_meeting_title,
    validate_timezone_name,
    validate_virtual_meeting_url,
)
from my_pa.domain.meeting_sync.model import (
    MAX_CALENDAR_REF_CHARACTERS,
    MAX_ICAL_UID_CHARACTERS,
    MAX_PROVIDER_EVENT_ID_CHARACTERS,
    ProviderBindingState,
    ProviderEventIdFormat,
)

__all__ = [
    "MeetingAttachmentView",
    "MeetingAttendeeView",
    "MeetingHistoryView",
    "MeetingListEntry",
    "MeetingNoteVersionEntry",
    "MeetingNoteVersionView",
    "MeetingNoteView",
    "MeetingPrepView",
    "MeetingProviderBindingView",
    "MeetingSeriesHistoryView",
    "MeetingSeriesView",
    "MeetingView",
]

_Title = Field(min_length=1, max_length=MAX_MEETING_TITLE_CHARACTERS)
_TimezoneName = Field(min_length=1, max_length=MAX_TIMEZONE_NAME_CHARACTERS)
_Version = Field(ge=1)
#: The series' own version (plan D-21, OD-7 (i)): nullable, and never the
#: Meeting's `version`, which keeps its name and meaning.
_SeriesVersion = Field(default=None, ge=1)


def _check_versions(
    action: MeetingHistoryAction, outcome: MeetingOutcome, before: int, after: int
) -> None:
    """The receipt's version transition: create 0->1 applied; update +1 or equal."""
    if action is MeetingHistoryAction.CREATE:
        legal = before == 0 and after == 1 and outcome is MeetingOutcome.APPLIED
    elif outcome is MeetingOutcome.APPLIED:
        legal = before >= 1 and after == before + 1
    else:
        legal = before >= 1 and after == before
    if not legal:
        raise ValueError("history receipt version transition is not legal")


class MeetingAttendeeView(StrictModel):
    """One active attendee relationship: a structured child, never delimited text."""

    attendee_id: str
    entity_id: str | None = None
    display_name: str | None = Field(
        default=None, min_length=1, max_length=MAX_ATTENDEE_DISPLAY_NAME_CHARACTERS
    )
    #: The canonical normalized EMAIL form, exactly as stored.
    email: str | None = Field(default=None, min_length=1, max_length=MAX_ATTENDEE_EMAIL_CHARACTERS)
    is_organizer: bool
    response_status: AttendeeResponseStatus
    added_at: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> MeetingAttendeeView:
        validate_identifier(self.attendee_id, IdKind.MEETING_ATTENDEE)
        if self.entity_id is not None:
            validate_identifier(self.entity_id, IdKind.ENTITY)
        if self.entity_id is None and self.display_name is None and self.email is None:
            raise ValueError("an attendee carries at least one identity signal")
        return self


class MeetingAttachmentView(StrictModel):
    """One active Meeting-to-ManagedDocument relationship and its safe projection."""

    attachment_id: str
    document_id: str
    availability: MeetingAttachmentAvailability
    #: The ManagedDocument's current title and media type, derived at read time
    #: (no snapshot). Nullable only for an `unavailable` projection.
    title: str | None = Field(default=None, min_length=1, max_length=MAX_MANAGED_TITLE_CHARACTERS)
    media_type: str | None = None
    added_at: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> MeetingAttachmentView:
        validate_identifier(self.attachment_id, IdKind.MEETING_ATTACHMENT)
        validate_identifier(self.document_id, IdKind.MANAGED_DOCUMENT)
        if self.availability is not MeetingAttachmentAvailability.UNAVAILABLE and (
            self.title is None or self.media_type is None
        ):
            raise ValueError("an available attachment projects its title and media type")
        if self.media_type is not None and self.media_type not in MANAGED_MEDIA_TYPES:
            raise ValueError("the managed plane does not store that media type")
        return self


class MeetingNoteView(StrictModel):
    """The current note head only: one immutable full-body version."""

    note_version_id: str
    version_number: int = _Version
    body_markdown: str = Field(min_length=1, max_length=MAX_MEETING_NOTES_CHARACTERS)
    recorded_at: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> MeetingNoteView:
        validate_identifier(self.note_version_id, IdKind.MEETING_NOTE_VERSION)
        validate_meeting_notes_markdown(self.body_markdown)
        return self


class MeetingPrepView(StrictModel):
    """One immutable prep-brief version (ADR-020 C4, C6).

    `body_markdown` is the exact stored text, never rendered; `content_sha256`
    its stored lowercase SHA-256 hex and `character_count` its length in code
    points. `is_current` says no later version supersedes it. Version 1, and
    only version 1, supersedes nothing.
    """

    prep_version_id: str
    version_number: int = _Version
    supersedes_prep_version_id: str | None
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    character_count: int = Field(ge=1, le=MAX_MEETING_PREP_CHARACTERS)
    recorded_at: UtcDatetime
    is_current: bool
    body_markdown: str = Field(min_length=1, max_length=MAX_MEETING_PREP_CHARACTERS)

    @model_validator(mode="after")
    def _check(self) -> MeetingPrepView:
        validate_identifier(self.prep_version_id, IdKind.MEETING_PREP_VERSION)
        if self.supersedes_prep_version_id is not None:
            validate_identifier(self.supersedes_prep_version_id, IdKind.MEETING_PREP_VERSION)
        if (self.version_number == 1) != (self.supersedes_prep_version_id is None):
            raise ValueError("exactly the first prep version supersedes nothing")
        validate_meeting_prep_markdown(self.body_markdown)
        if self.character_count != len(self.body_markdown):
            raise ValueError("character_count is the body's length")
        return self


class MeetingSeriesView(StrictModel):
    """One MeetingSeries: the single canonical owner of the series title."""

    meeting_series_id: str
    title: str = _Title
    version: int = _Version
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> MeetingSeriesView:
        validate_identifier(self.meeting_series_id, IdKind.MEETING_SERIES)
        validate_meeting_title(self.title)
        return self


def _check_meeting_core(
    *,
    meeting_id: str,
    meeting_series_id: str | None,
    series_title: str | None,
    series_version: int | None,
    title: str,
    timezone_name: str,
    start_at: datetime,
    end_at: datetime | None,
    project_id: str | None,
) -> None:
    validate_identifier(meeting_id, IdKind.MEETING)
    if (meeting_series_id is None) != (series_title is None):
        raise ValueError("a series member carries its series title; a standalone carries neither")
    if meeting_series_id is None and series_version is not None:
        raise ValueError("a standalone Meeting carries no series version")
    if meeting_series_id is not None:
        validate_identifier(meeting_series_id, IdKind.MEETING_SERIES)
    if series_title is not None:
        validate_meeting_title(series_title)
    validate_meeting_title(title)
    validate_timezone_name(timezone_name)
    validate_meeting_time_range(start_at, end_at)
    if project_id is not None:
        validate_identifier(project_id, IdKind.PROJECT)


class MeetingView(StrictModel):
    """One Meeting occurrence, exactly as a full read and every write answer it.

    Attendees are the active set in the deterministic order organizer first,
    then `attendee_id` ascending; attachments are the active relationships;
    `notes` is the current note head or `None`; `prep` is the current prep
    head or `None` (ADR-020 C4). `prep_version` is the exact prep version a
    `meetings.read` named by `prep_version_number`, and `None` on every other
    answer (C6).
    """

    meeting_id: str
    meeting_series_id: str | None = None
    series_title: str | None = None
    #: The series' current version, read with the Meeting (plan D-21); `None`
    #: for a standalone Meeting. The Meeting's own version is `version`.
    series_version: int | None = _SeriesVersion
    title: str = _Title
    status: MeetingStatus
    start_at: UtcDatetime
    end_at: UtcDatetime | None = None
    timezone_name: str = _TimezoneName
    location_text: str | None = Field(default=None, max_length=MAX_MEETING_LOCATION_CHARACTERS)
    virtual_meeting_url: str | None = Field(
        default=None, min_length=1, max_length=MAX_VIRTUAL_MEETING_URL_CHARACTERS
    )
    description: str | None = Field(default=None, max_length=MAX_MEETING_DESCRIPTION_CHARACTERS)
    project_id: str | None = None
    version: int = _Version
    created_at: UtcDatetime
    updated_at: UtcDatetime
    cancelled_at: UtcDatetime | None = None
    attendees: tuple[MeetingAttendeeView, ...] = Field(default=(), max_length=MAX_MEETING_ATTENDEES)
    attachments: tuple[MeetingAttachmentView, ...] = Field(
        default=(), max_length=MAX_MEETING_ATTACHMENTS
    )
    notes: MeetingNoteView | None = None
    prep: MeetingPrepView | None = None
    prep_version: MeetingPrepView | None = None

    @field_validator("attendees", mode="after")
    @classmethod
    def _order_attendees(
        cls, value: tuple[MeetingAttendeeView, ...]
    ) -> tuple[MeetingAttendeeView, ...]:
        """Organizer first, then `attendee_id` ascending (section 34.10)."""
        return tuple(
            sorted(value, key=lambda attendee: (not attendee.is_organizer, attendee.attendee_id))
        )

    @model_validator(mode="after")
    def _check(self) -> MeetingView:
        _check_meeting_core(
            meeting_id=self.meeting_id,
            meeting_series_id=self.meeting_series_id,
            series_title=self.series_title,
            series_version=self.series_version,
            title=self.title,
            timezone_name=self.timezone_name,
            start_at=self.start_at,
            end_at=self.end_at,
            project_id=self.project_id,
        )
        validate_cancellation_pairing(self.status, self.cancelled_at)
        if self.virtual_meeting_url is not None:
            validate_virtual_meeting_url(self.virtual_meeting_url)
        attendee_ids = [attendee.attendee_id for attendee in self.attendees]
        if len(set(attendee_ids)) != len(attendee_ids):
            raise ValueError("an attendee appears once")
        if sum(1 for attendee in self.attendees if attendee.is_organizer) > 1:
            raise ValueError("a Meeting has at most one active organizer")
        attachment_ids = [attachment.attachment_id for attachment in self.attachments]
        document_ids = [attachment.document_id for attachment in self.attachments]
        if len(set(attachment_ids)) != len(attachment_ids) or len(set(document_ids)) != len(
            document_ids
        ):
            raise ValueError("a document is attached to a Meeting at most once")
        if self.prep is not None and not self.prep.is_current:
            raise ValueError("prep is the current prep head")
        return self


class MeetingListEntry(StrictModel):
    """One Meeting as a `meetings.list`/`meetings.search` page row.

    Deliberately minimal: no description, virtual link, attendee identity or
    email, and no note body (section 19.4).
    """

    meeting_id: str
    meeting_series_id: str | None = None
    series_title: str | None = None
    #: The series' current version, read with the Meeting (plan D-21); `None`
    #: for a standalone Meeting. The Meeting's own version is `version`.
    series_version: int | None = _SeriesVersion
    title: str = _Title
    status: MeetingStatus
    start_at: UtcDatetime
    end_at: UtcDatetime | None = None
    timezone_name: str = _TimezoneName
    location_text: str | None = Field(default=None, max_length=MAX_MEETING_LOCATION_CHARACTERS)
    project_id: str | None = None
    version: int = _Version
    attendee_count: int = Field(ge=0, le=MAX_MEETING_ATTENDEES)
    attachment_count: int = Field(ge=0, le=MAX_MEETING_ATTACHMENTS)
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> MeetingListEntry:
        _check_meeting_core(
            meeting_id=self.meeting_id,
            meeting_series_id=self.meeting_series_id,
            series_title=self.series_title,
            series_version=self.series_version,
            title=self.title,
            timezone_name=self.timezone_name,
            start_at=self.start_at,
            end_at=self.end_at,
            project_id=self.project_id,
        )
        return self


class MeetingHistoryView(StrictModel):
    """One immutable Meeting mutation receipt. No key, digest or Principal."""

    history_id: str
    meeting_id: str
    action: MeetingHistoryAction
    actor: MeetingActor
    outcome: MeetingOutcome
    before_version: int = Field(ge=0)
    after_version: int = Field(ge=1)
    occurred_at: UtcDatetime
    recorded_at: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> MeetingHistoryView:
        validate_identifier(self.history_id, IdKind.MEETING_HISTORY)
        validate_identifier(self.meeting_id, IdKind.MEETING)
        _check_versions(self.action, self.outcome, self.before_version, self.after_version)
        return self


class MeetingSeriesHistoryView(StrictModel):
    """One immutable MeetingSeries mutation receipt. No key, digest or Principal."""

    series_history_id: str
    meeting_series_id: str
    action: MeetingHistoryAction
    actor: MeetingActor
    outcome: MeetingOutcome
    before_version: int = Field(ge=0)
    after_version: int = Field(ge=1)
    occurred_at: UtcDatetime
    recorded_at: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> MeetingSeriesHistoryView:
        validate_identifier(self.series_history_id, IdKind.MEETING_SERIES_HISTORY)
        validate_identifier(self.meeting_series_id, IdKind.MEETING_SERIES)
        _check_versions(self.action, self.outcome, self.before_version, self.after_version)
        return self


class MeetingNoteVersionEntry(StrictModel):
    """One note version as `meetings.notes.versions` lists it: no body, no digest."""

    note_version_id: str
    version_number: int = _Version
    supersedes_note_version_id: str | None
    character_count: int = Field(ge=1, le=MAX_MEETING_NOTES_CHARACTERS)
    recorded_at: UtcDatetime
    is_current: bool

    @model_validator(mode="after")
    def _check(self) -> MeetingNoteVersionEntry:
        validate_identifier(self.note_version_id, IdKind.MEETING_NOTE_VERSION)
        if self.supersedes_note_version_id is not None:
            validate_identifier(self.supersedes_note_version_id, IdKind.MEETING_NOTE_VERSION)
        return self


class MeetingNoteVersionView(StrictModel):
    """One exact note version as `meetings.notes.read_version` answers it.

    `content_sha256` is the stored digest of the exact body; `body_markdown` is
    present only when the request asked for it (`include_body`), and is then
    the exact stored text.
    """

    note_version_id: str
    meeting_id: str
    version_number: int = _Version
    supersedes_note_version_id: str | None
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    character_count: int = Field(ge=1, le=MAX_MEETING_NOTES_CHARACTERS)
    recorded_at: UtcDatetime
    is_current: bool
    body_markdown: str | None = Field(
        default=None, min_length=1, max_length=MAX_MEETING_NOTES_CHARACTERS
    )

    @model_validator(mode="after")
    def _check(self) -> MeetingNoteVersionView:
        validate_identifier(self.note_version_id, IdKind.MEETING_NOTE_VERSION)
        validate_identifier(self.meeting_id, IdKind.MEETING)
        if self.supersedes_note_version_id is not None:
            validate_identifier(self.supersedes_note_version_id, IdKind.MEETING_NOTE_VERSION)
        return self

    def to_canonical_dict(self) -> dict[str, object]:
        """The JSON-mode representation; `body_markdown` only when it was asked for."""
        dumped = self.model_dump(mode="json")
        if self.body_markdown is None:
            del dumped["body_markdown"]
        return dumped


class MeetingProviderBindingView(StrictModel):
    """One Meeting's provider binding (communications intelligence WP2-W3).

    What `meetings.provider.bind` answers. The provider key the caller named --
    `calendar_ref`, `ical_uid` and, for an occurrence, `series_ical_uid` and
    `occurrence_original_start_utc` (the original start, never the current one)
    -- plus the mutable attributes: the provider event id and its format, the
    last observed provider state and when the provider last showed it. No
    Principal, no publication digest, no Meeting content. Additive and separate:
    `MeetingView` and `meetings.read` are unchanged (Manager ruling D11).
    """

    binding_id: str
    meeting_id: str
    calendar_ref: str = Field(min_length=1, max_length=MAX_CALENDAR_REF_CHARACTERS)
    ical_uid: str = Field(min_length=1, max_length=MAX_ICAL_UID_CHARACTERS)
    occurrence_original_start_utc: UtcDatetime | None = None
    series_ical_uid: str | None = Field(
        default=None, min_length=1, max_length=MAX_ICAL_UID_CHARACTERS
    )
    meeting_series_id: str | None = None
    provider_event_id: str | None = Field(
        default=None, min_length=1, max_length=MAX_PROVIDER_EVENT_ID_CHARACTERS
    )
    provider_event_id_format: ProviderEventIdFormat
    provider_state: ProviderBindingState
    last_seen_at: UtcDatetime | None = None
    version: int = _Version
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> MeetingProviderBindingView:
        validate_identifier(self.binding_id, IdKind.MEETING_PROVIDER_BINDING)
        validate_identifier(self.meeting_id, IdKind.MEETING)
        if (self.series_ical_uid is None) != (self.occurrence_original_start_utc is None):
            raise ValueError("an occurrence names its series and original start; a single neither")
        if self.series_ical_uid is not None and self.meeting_series_id is None:
            raise ValueError("an occurrence binding names the series its UID is bound to")
        if self.meeting_series_id is not None:
            validate_identifier(self.meeting_series_id, IdKind.MEETING_SERIES)
        return self
