"""WP-MTG-01: the eight public Meeting views (package section 34.18, section 19).

Field sets, exclusions (no Principal, idempotency key or request digest; minimal
list rows), attendee ordering, attachment availability, receipt version
transitions and `UtcDatetime` serialization. Covers the view portions of
MYPA-MTG-AC-003, 004, 008, 010, 012-015 and 018.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from my_pa.contracts.v1.base import StrictModel
from my_pa.contracts.v1.meetings import (
    MeetingAttachmentView,
    MeetingAttendeeView,
    MeetingHistoryView,
    MeetingListEntry,
    MeetingNoteView,
    MeetingSeriesHistoryView,
    MeetingSeriesView,
    MeetingView,
)
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.meeting import (
    AttendeeResponseStatus,
    MeetingAttachmentAvailability,
    MeetingStatus,
)

MEETING = make_identifier(IdKind.MEETING, "aaaa1111bbbb")
SERIES = make_identifier(IdKind.MEETING_SERIES, "aaaa1111bbbb")
PROJECT = make_identifier(IdKind.PROJECT, "aaaa1111bbbb")
ENTITY = make_identifier(IdKind.ENTITY, "aaaa1111bbbb")
DOCUMENT = make_identifier(IdKind.MANAGED_DOCUMENT, "aaaa1111bbbb")
NOTE = make_identifier(IdKind.MEETING_NOTE_VERSION, "aaaa1111bbbb")
HISTORY = make_identifier(IdKind.MEETING_HISTORY, "aaaa1111bbbb")
SERIES_HISTORY = make_identifier(IdKind.MEETING_SERIES_HISTORY, "aaaa1111bbbb")
AT = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)

ALL_VIEWS: list[type[StrictModel]] = [
    MeetingView,
    MeetingListEntry,
    MeetingSeriesView,
    MeetingAttendeeView,
    MeetingAttachmentView,
    MeetingNoteView,
    MeetingHistoryView,
    MeetingSeriesHistoryView,
]


def _attendee(suffix: str, **overrides: Any) -> MeetingAttendeeView:  # noqa: ANN401
    arguments: dict[str, Any] = {
        "attendee_id": make_identifier(IdKind.MEETING_ATTENDEE, suffix),
        "display_name": "Ada",
        "is_organizer": False,
        "response_status": AttendeeResponseStatus.UNKNOWN,
        "added_at": AT,
    }
    arguments.update(overrides)
    return MeetingAttendeeView(**arguments)


def _attachment(suffix: str = "aaaa1111bbbb", **overrides: Any) -> MeetingAttachmentView:  # noqa: ANN401
    arguments: dict[str, Any] = {
        "attachment_id": make_identifier(IdKind.MEETING_ATTACHMENT, suffix),
        "document_id": make_identifier(IdKind.MANAGED_DOCUMENT, suffix),
        "availability": MeetingAttachmentAvailability.ACTIVE,
        "title": "Minutes",
        "media_type": "text/plain",
        "added_at": AT,
    }
    arguments.update(overrides)
    return MeetingAttachmentView(**arguments)


def _meeting(**overrides: Any) -> MeetingView:  # noqa: ANN401
    arguments: dict[str, Any] = {
        "meeting_id": MEETING,
        "title": "Weekly sync",
        "status": MeetingStatus.SCHEDULED,
        "start_at": AT,
        "timezone_name": "America/New_York",
        "version": 1,
        "created_at": AT,
        "updated_at": AT,
    }
    arguments.update(overrides)
    return MeetingView(**arguments)


def _list_entry(**overrides: Any) -> MeetingListEntry:  # noqa: ANN401
    arguments: dict[str, Any] = {
        "meeting_id": MEETING,
        "title": "Weekly sync",
        "status": MeetingStatus.SCHEDULED,
        "start_at": AT,
        "timezone_name": "America/New_York",
        "version": 1,
        "attendee_count": 0,
        "attachment_count": 0,
        "updated_at": AT,
    }
    arguments.update(overrides)
    return MeetingListEntry(**arguments)


def _history(**overrides: Any) -> MeetingHistoryView:  # noqa: ANN401
    arguments: dict[str, Any] = {
        "history_id": HISTORY,
        "meeting_id": MEETING,
        "action": "create",
        "actor": "principal",
        "outcome": "applied",
        "before_version": 0,
        "after_version": 1,
        "occurred_at": AT,
        "recorded_at": AT,
    }
    arguments.update(overrides)
    return MeetingHistoryView(**arguments)


# ------------------------------------------------------------------- field sets

EXPECTED_FIELDS: dict[type[StrictModel], set[str]] = {
    MeetingView: {
        "meeting_id",
        "meeting_series_id",
        "series_title",
        "title",
        "status",
        "start_at",
        "end_at",
        "timezone_name",
        "location_text",
        "virtual_meeting_url",
        "description",
        "project_id",
        "version",
        "created_at",
        "updated_at",
        "cancelled_at",
        "attendees",
        "attachments",
        "notes",
    },
    MeetingListEntry: {
        "meeting_id",
        "meeting_series_id",
        "series_title",
        "title",
        "status",
        "start_at",
        "end_at",
        "timezone_name",
        "location_text",
        "project_id",
        "version",
        "attendee_count",
        "attachment_count",
        "updated_at",
    },
    MeetingSeriesView: {"meeting_series_id", "title", "version", "created_at", "updated_at"},
    MeetingAttendeeView: {
        "attendee_id",
        "entity_id",
        "display_name",
        "email",
        "is_organizer",
        "response_status",
        "added_at",
    },
    MeetingAttachmentView: {
        "attachment_id",
        "document_id",
        "availability",
        "title",
        "media_type",
        "added_at",
    },
    MeetingNoteView: {"note_version_id", "version_number", "body_markdown", "recorded_at"},
    MeetingHistoryView: {
        "history_id",
        "meeting_id",
        "action",
        "actor",
        "outcome",
        "before_version",
        "after_version",
        "occurred_at",
        "recorded_at",
    },
    MeetingSeriesHistoryView: {
        "series_history_id",
        "meeting_series_id",
        "action",
        "actor",
        "outcome",
        "before_version",
        "after_version",
        "occurred_at",
        "recorded_at",
    },
}


@pytest.mark.parametrize("view", ALL_VIEWS, ids=lambda view: view.__name__)
def test_view_field_set_is_exact(view: type[StrictModel]) -> None:
    assert set(view.model_fields) == EXPECTED_FIELDS[view]


@pytest.mark.parametrize("view", ALL_VIEWS, ids=lambda view: view.__name__)
def test_no_view_exposes_internal_fields(view: type[StrictModel]) -> None:
    internal = {
        "principal_id",
        "owner_principal_id",
        "idempotency_key",
        "request_digest",
        "email_normalized",
        "removed_at",
        "supersedes_note_version_id",
        "content_sha256",
        "meeting_history_id",
        "conversation_id",
        "task_id",
    }
    assert not set(view.model_fields) & internal


@pytest.mark.parametrize("view", ALL_VIEWS, ids=lambda view: view.__name__)
def test_every_view_is_a_strict_model(view: type[StrictModel]) -> None:
    assert issubclass(view, StrictModel)
    assert view.model_config["extra"] == "forbid"
    assert view.model_config["frozen"] is True


def test_list_rows_exclude_pii_links_description_and_notes() -> None:
    fields = set(MeetingListEntry.model_fields)
    for excluded in ("description", "virtual_meeting_url", "attendees", "attachments", "notes"):
        assert excluded not in fields


def test_unknown_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        _meeting(principal_id="prn_aaaa1111bbbb")


# ----------------------------------------------------------------------- MeetingView


def test_full_read_carries_every_ac_004_field() -> None:
    view = _meeting(
        meeting_series_id=SERIES,
        series_title="Board",
        end_at=AT + timedelta(hours=1),
        location_text="Room 4",
        virtual_meeting_url="HTTPS://Host:443/p?q#f",
        description="Agenda",
        project_id=PROJECT,
        attendees=(_attendee("aaaa1111aaaa", entity_id=ENTITY, email="ada@example.com"),),
        attachments=(_attachment(),),
        notes=MeetingNoteView(
            note_version_id=NOTE, version_number=1, body_markdown="Notes", recorded_at=AT
        ),
    )
    dumped = view.to_canonical_dict()
    assert dumped["virtual_meeting_url"] == "HTTPS://Host:443/p?q#f"
    assert dumped["series_title"] == "Board"
    assert dumped["notes"]["body_markdown"] == "Notes"
    assert dumped["attendees"][0]["email"] == "ada@example.com"
    assert dumped["attachments"][0]["availability"] == "active"


def test_standalone_meeting_has_no_series_and_no_title() -> None:
    view = _meeting()
    assert view.meeting_series_id is None
    assert view.series_title is None
    with pytest.raises(ValidationError):
        _meeting(meeting_series_id=SERIES)
    with pytest.raises(ValidationError):
        _meeting(series_title="Orphan title")


def test_timestamps_serialize_as_utc_z() -> None:
    offset = timezone(timedelta(hours=-4))
    view = _meeting(start_at=datetime(2026, 10, 1, 10, 0, tzinfo=offset))
    dumped = view.to_canonical_dict()
    assert dumped["start_at"] == "2026-10-01T14:00:00.000Z"
    assert dumped["created_at"].endswith("Z")


def test_naive_timestamp_is_refused() -> None:
    with pytest.raises(ValidationError):
        _meeting(start_at=datetime(2026, 10, 1, 14, 0))


def test_end_before_start_is_refused_and_equal_is_allowed() -> None:
    assert _meeting(end_at=AT).end_at == AT
    with pytest.raises(ValidationError):
        _meeting(end_at=AT - timedelta(seconds=1))


def test_cancellation_is_paired_with_cancelled_at() -> None:
    assert _meeting(status=MeetingStatus.CANCELLED, cancelled_at=AT).cancelled_at == AT
    with pytest.raises(ValidationError):
        _meeting(status=MeetingStatus.CANCELLED)
    with pytest.raises(ValidationError):
        _meeting(status=MeetingStatus.SCHEDULED, cancelled_at=AT)


def test_attendees_are_organizer_first_then_attendee_id_ascending() -> None:
    view = _meeting(
        attendees=(
            _attendee("cccc3333cccc"),
            _attendee("aaaa1111aaaa"),
            _attendee("bbbb2222bbbb", is_organizer=True),
        )
    )
    assert [attendee.attendee_id for attendee in view.attendees] == [
        make_identifier(IdKind.MEETING_ATTENDEE, "bbbb2222bbbb"),
        make_identifier(IdKind.MEETING_ATTENDEE, "aaaa1111aaaa"),
        make_identifier(IdKind.MEETING_ATTENDEE, "cccc3333cccc"),
    ]


def test_at_most_one_organizer_and_unique_children() -> None:
    with pytest.raises(ValidationError):
        _meeting(
            attendees=(
                _attendee("aaaa1111aaaa", is_organizer=True),
                _attendee("bbbb2222bbbb", is_organizer=True),
            )
        )
    with pytest.raises(ValidationError):
        _meeting(attendees=(_attendee("aaaa1111aaaa"), _attendee("aaaa1111aaaa")))
    with pytest.raises(ValidationError):
        _meeting(attachments=(_attachment(), _attachment()))


def test_virtual_url_must_satisfy_the_https_rule() -> None:
    with pytest.raises(ValidationError):
        _meeting(virtual_meeting_url="http://example.com")


def test_meeting_view_bounds() -> None:
    with pytest.raises(ValidationError):
        _meeting(title="   ")
    with pytest.raises(ValidationError):
        _meeting(timezone_name="Mars/Olympus")
    with pytest.raises(ValidationError):
        _meeting(location_text="a" * 501)
    with pytest.raises(ValidationError):
        _meeting(description="a" * 100_001)
    with pytest.raises(ValidationError):
        _meeting(version=0)
    with pytest.raises(ValidationError):
        _meeting(meeting_id=SERIES)


# ---------------------------------------------------------------- children views


def test_attendee_needs_an_identity_signal() -> None:
    with pytest.raises(ValidationError):
        _attendee("aaaa1111aaaa", display_name=None)
    assert _attendee("aaaa1111aaaa", display_name=None, entity_id=ENTITY).entity_id == ENTITY
    with pytest.raises(ValidationError):
        _attendee("aaaa1111aaaa", entity_id=PROJECT)


def test_attachment_availability_projection() -> None:
    assert _attachment(availability=MeetingAttachmentAvailability.ARCHIVED).title == "Minutes"
    unavailable = _attachment(
        availability=MeetingAttachmentAvailability.UNAVAILABLE, title=None, media_type=None
    )
    assert unavailable.title is None
    assert unavailable.media_type is None
    with pytest.raises(ValidationError):
        _attachment(title=None)
    with pytest.raises(ValidationError):
        _attachment(media_type="application/x-not-managed")
    with pytest.raises(ValidationError):
        _attachment(document_id=MEETING)


def test_note_view_is_bounded_nonblank_body() -> None:
    with pytest.raises(ValidationError):
        MeetingNoteView(note_version_id=NOTE, version_number=1, body_markdown="  ", recorded_at=AT)
    with pytest.raises(ValidationError):
        MeetingNoteView(note_version_id=NOTE, version_number=0, body_markdown="x", recorded_at=AT)


def test_series_view() -> None:
    view = MeetingSeriesView(
        meeting_series_id=SERIES, title="Board", version=2, created_at=AT, updated_at=AT
    )
    assert view.to_canonical_dict()["title"] == "Board"
    with pytest.raises(ValidationError):
        MeetingSeriesView(
            meeting_series_id=MEETING, title="Board", version=1, created_at=AT, updated_at=AT
        )


def test_list_entry_counts_are_bounded() -> None:
    assert _list_entry(attendee_count=100, attachment_count=50).attendee_count == 100
    with pytest.raises(ValidationError):
        _list_entry(attendee_count=101)
    with pytest.raises(ValidationError):
        _list_entry(attachment_count=-1)


# -------------------------------------------------------------------- receipts


@pytest.mark.parametrize(
    ("action", "outcome", "before", "after"),
    [("create", "applied", 0, 1), ("update", "applied", 3, 4), ("update", "no_op", 3, 3)],
)
def test_legal_receipt_transitions(action: str, outcome: str, before: int, after: int) -> None:
    view = _history(action=action, outcome=outcome, before_version=before, after_version=after)
    assert view.to_canonical_dict()["outcome"] == outcome
    series = MeetingSeriesHistoryView(
        series_history_id=SERIES_HISTORY,
        meeting_series_id=SERIES,
        action=action,
        actor="principal",
        outcome=outcome,
        before_version=before,
        after_version=after,
        occurred_at=AT,
        recorded_at=AT,
    )
    assert series.after_version == after


@pytest.mark.parametrize(
    ("action", "outcome", "before", "after"),
    [
        ("create", "applied", 1, 2),
        ("create", "no_op", 0, 1),
        ("update", "applied", 3, 5),
        ("update", "applied", 0, 1),
        ("update", "no_op", 3, 4),
    ],
)
def test_illegal_receipt_transitions(action: str, outcome: str, before: int, after: int) -> None:
    with pytest.raises(ValidationError):
        _history(action=action, outcome=outcome, before_version=before, after_version=after)


def test_receipt_vocabularies_are_closed() -> None:
    with pytest.raises(ValidationError):
        _history(actor="operator")
    with pytest.raises(ValidationError):
        _history(action="delete")
    with pytest.raises(ValidationError):
        _history(history_id=SERIES_HISTORY)


def test_views_are_frozen() -> None:
    view = _meeting()
    with pytest.raises(ValidationError):
        view.title = "changed"
