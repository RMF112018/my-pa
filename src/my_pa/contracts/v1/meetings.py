"""The public shapes of a Meeting answer (WP-MTG-01, package section 34.18).

Eight models: `MeetingView` for a full read and every write result,
`MeetingListEntry` for a `meetings.list`/`meetings.search` row, `MeetingSeriesView`,
the three child views a full read nests (`MeetingAttendeeView`,
`MeetingAttachmentView`, `MeetingNoteView`), and the two immutable history
receipts (`MeetingHistoryView`, `MeetingSeriesHistoryView`).

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
    validate_meeting_time_range,
    validate_meeting_title,
    validate_timezone_name,
    validate_virtual_meeting_url,
)

__all__ = [
    "MeetingAttachmentView",
    "MeetingAttendeeView",
    "MeetingHistoryView",
    "MeetingListEntry",
    "MeetingNoteView",
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
    `notes` is the current note head or `None`.
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
