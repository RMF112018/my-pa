"""WP2: the `meeting_sync_v1` parser (Manager rulings D1, D3, D4).

Envelope rejections, the major-version gate, duplicate keys, the size cap, and
every per-record quarantine reason, over synthetic fixtures only. No reason code
or diagnostic ever carries input text.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest

from my_pa.domain.meeting.model import AttendeeResponseStatus, MeetingStatus
from my_pa.domain.meeting_sync.diagnostics import (
    DiagnosticCode,
    PublicationRejection,
    ReasonCode,
)
from my_pa.domain.meeting_sync.model import EventStatus, ProviderEventIdFormat
from my_pa.infrastructure.meeting_sync import parser
from my_pa.infrastructure.meeting_sync.parser import (
    MAX_PUBLICATION_BYTES,
    PublicationStatus,
    parse_publication,
)

FIXTURES: Final = Path(__file__).resolve().parents[1] / "fixtures" / "meeting_sync"
PRIVATE_TITLE: Final = "Confidential merger talk with Synthetic Person"


def _event(**overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "calendar_ref": "cal-synthetic",
        "ical_uid": "uid-0001@example.invalid",
        "series_ical_uid": None,
        "occurrence_original_start_utc": None,
        "start_utc": "2026-12-01T15:00:00Z",
        "end_utc": "2026-12-01T16:00:00Z",
        "timezone_name": "America/New_York",
        "status": "confirmed",
        "all_day": False,
        "provider_event_id": "evt-0001",
        "provider_event_id_format": "mutable",
        "title": PRIVATE_TITLE,
        "location_text": None,
        "virtual_meeting_url": None,
        "attendees": [],
    }
    event.update(overrides)
    return event


def _publication(*events: object, **top: object) -> bytes:
    document: dict[str, Any] = {
        "schema": "meeting_sync_v1",
        "schema_version": "1.0.0",
        "generated_at_utc": "2026-11-21T06:00:00Z",
        "events": list(events),
    }
    document.update(top)
    return json.dumps(document).encode("utf-8")


def _reasons(data: bytes) -> tuple[ReasonCode, ...]:
    parsed = parse_publication(data)
    assert parsed.publication is not None
    assert parsed.publication.events == ()
    (entry,) = parsed.publication.quarantined
    return entry.reasons


def _no_content(data: bytes) -> None:
    parsed = parse_publication(data)
    rendered = repr(parsed.diagnostics) + repr(parsed.rejection)
    if parsed.publication is not None:
        rendered += repr(parsed.publication.quarantined)
    assert "Confidential" not in rendered
    assert "example.invalid" not in rendered


# ---- the fixtures ---------------------------------------------------------------


def test_the_synthetic_fixture_parses_into_accepted_and_quarantined_events() -> None:
    parsed = parse_publication((FIXTURES / "sync_publication.json").read_bytes())
    assert parsed.status is PublicationStatus.ACCEPTED
    publication = parsed.publication
    assert publication is not None
    assert publication.record_count == 5
    assert [event.ordinal for event in publication.events] == [0, 1, 2, 3]
    single, first, moved, cancelled = publication.events
    assert single.key.is_occurrence is False
    assert single.provider_event_id_format is ProviderEventIdFormat.IMMUTABLE_VERIFIED
    # Casefold normalization through the Meeting attendee rule, organizer first
    # in digest order is not promised; the set is the normalized addresses.
    assert {a.email_normalized for a in single.attendees} == {
        "organizer@example.invalid",
        "guest@example.invalid",
    }
    assert any(
        a.is_organizer and a.response_status is AttendeeResponseStatus.ACCEPTED
        for a in single.attendees
    )
    assert first.status is EventStatus.TENTATIVE
    assert first.meeting_status is MeetingStatus.SCHEDULED
    # A moved occurrence: identity is the original start, the start is UTC.
    assert moved.occurrence_original_start_utc == datetime(2026, 12, 9, 14, tzinfo=UTC)
    assert moved.start_utc == datetime(2026, 12, 9, 15, tzinfo=UTC)
    assert moved.provider_event_id is None
    assert moved.provider_event_id_format is ProviderEventIdFormat.UNKNOWN
    assert cancelled.meeting_status is MeetingStatus.CANCELLED
    (offsite,) = publication.quarantined
    assert offsite.ordinal == 4
    assert offsite.reasons == (ReasonCode.ALL_DAY_UNSUPPORTED, ReasonCode.TIMEZONE_NOT_IANA)
    assert parsed.diagnostics.code_counts[DiagnosticCode.CONTENT_FIELD_IGNORED.value] == 1


def test_malformed_json_is_rejected_with_position_only() -> None:
    parsed = parse_publication((FIXTURES / "malformed.json").read_bytes())
    assert parsed.status is PublicationStatus.REJECTED
    assert parsed.rejection is PublicationRejection.MALFORMED_JSON
    (entry,) = parsed.diagnostics.entries
    assert {name for name, _ in entry.detail} == {"line", "column", "offset"}


# ---- envelope -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"\xff\xfe", PublicationRejection.INVALID_ENCODING),
        (b'{"schema": "meeting_sync_v1", "schema": "x"}', PublicationRejection.DUPLICATE_JSON_KEY),
        (b'{"a": NaN}', PublicationRejection.MALFORMED_JSON),
        (b'{"a": Infinity}', PublicationRejection.MALFORMED_JSON),
        (b"[]", PublicationRejection.NOT_AN_OBJECT),
        (b"{}", PublicationRejection.MISSING_REQUIRED_KEY),
        (b'{"schema": "communications_evidence_v2"}', PublicationRejection.UNKNOWN_SCHEMA),
        (
            b'{"schema": "meeting_sync_v1", "schema_version": "1.0"}',
            PublicationRejection.INVALID_SCHEMA_VERSION,
        ),
        (
            b'{"schema": "meeting_sync_v1", "schema_version": "2.0.0", "events": []}',
            PublicationRejection.UNSUPPORTED_MAJOR_VERSION,
        ),
        (
            b'{"schema": "meeting_sync_v1", "schema_version": "1.0.0"}',
            PublicationRejection.MISSING_REQUIRED_KEY,
        ),
        (
            b'{"schema": "meeting_sync_v1", "schema_version": "1.0.0", "events": {}}',
            PublicationRejection.INVALID_TOP_LEVEL_FIELD,
        ),
    ],
)
def test_envelope_rejections(data: bytes, code: PublicationRejection) -> None:
    parsed = parse_publication(data)
    assert parsed.status is PublicationStatus.REJECTED
    assert parsed.rejection is code
    assert parsed.publication is None


def test_a_duplicate_key_inside_a_record_rejects_the_publication() -> None:
    data = (
        b'{"schema": "meeting_sync_v1", "schema_version": "1.0.0", '
        b'"events": [{"title": "a", "title": "b"}]}'
    )
    assert parse_publication(data).rejection is PublicationRejection.DUPLICATE_JSON_KEY


def test_the_size_cap_is_inclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    assert MAX_PUBLICATION_BYTES == 16 * 1024 * 1024
    data = _publication(_event())
    monkeypatch.setattr(parser, "MAX_PUBLICATION_BYTES", len(data))
    assert parse_publication(data).status is PublicationStatus.ACCEPTED
    monkeypatch.setattr(parser, "MAX_PUBLICATION_BYTES", len(data) - 1)
    parsed = parse_publication(data)
    assert parsed.rejection is PublicationRejection.FILE_TOO_LARGE


def test_a_newer_minor_is_accepted_and_reported() -> None:
    parsed = parse_publication(_publication(_event(), schema_version="1.4.0"))
    assert parsed.status is PublicationStatus.ACCEPTED
    assert parsed.diagnostics.code_counts[DiagnosticCode.SCHEMA_MINOR_NEWER.value] == 1


@pytest.mark.parametrize("top", [{"cycle_run_id": ""}, {"cycle_run_id": 7}])
def test_invalid_optional_top_level_fields_reject(top: dict[str, object]) -> None:
    parsed = parse_publication(_publication(_event(), **top))
    assert parsed.rejection is PublicationRejection.INVALID_TOP_LEVEL_FIELD


def test_a_missing_generated_at_utc_rejects_the_publication() -> None:
    document = json.loads(_publication(_event()))
    del document["generated_at_utc"]
    parsed = parse_publication(json.dumps(document).encode("utf-8"))
    assert parsed.status is PublicationStatus.REJECTED
    assert parsed.rejection is PublicationRejection.MISSING_REQUIRED_KEY
    assert parsed.publication is None
    (diagnostic,) = parsed.diagnostics.entries
    assert diagnostic.path == "generated_at_utc"


@pytest.mark.parametrize(
    "value",
    [
        None,
        "yesterday",
        "2026-11-21T06:00:00",  # naive: no offset
        "2026-11-21",
        1732168800,
        "0001-01-01T00:00:00Z",  # outside the representable range
    ],
)
def test_an_invalid_generated_at_utc_rejects_the_publication(value: object) -> None:
    parsed = parse_publication(_publication(_event(), generated_at_utc=value))
    assert parsed.status is PublicationStatus.REJECTED
    assert parsed.rejection is PublicationRejection.INVALID_TOP_LEVEL_FIELD
    (diagnostic,) = parsed.diagnostics.entries
    assert diagnostic.path == "generated_at_utc"
    assert "yesterday" not in repr(parsed.diagnostics)


def test_generated_at_utc_is_every_events_ordering_stamp_in_utc() -> None:
    parsed = parse_publication(
        _publication(
            _event(), _event(ical_uid="uid-0002"), generated_at_utc="2026-11-21T01:00:00-05:00"
        )
    )
    assert parsed.publication is not None
    stamp = datetime(2026, 11, 21, 6, tzinfo=UTC)
    assert parsed.publication.generated_at_utc == stamp
    assert [event.generated_at_utc for event in parsed.publication.events] == [stamp, stamp]


def test_unknown_keys_are_counted_never_fatal() -> None:
    parsed = parse_publication(_publication(_event(colour="blue"), producer="x"))
    assert parsed.status is PublicationStatus.ACCEPTED
    assert parsed.publication is not None and len(parsed.publication.events) == 1
    counts = parsed.diagnostics.code_counts
    assert counts[DiagnosticCode.UNKNOWN_TOP_LEVEL_KEYS.value] == 1
    assert counts[DiagnosticCode.UNKNOWN_RECORD_KEYS.value] == 1


def test_body_keys_are_never_read() -> None:
    parsed = parse_publication(_publication(_event(body="secret", description="secret")))
    assert parsed.publication is not None
    (event,) = parsed.publication.events
    assert "secret" not in repr(event)
    assert parsed.diagnostics.code_counts[DiagnosticCode.CONTENT_FIELD_IGNORED.value] == 1


# ---- per-record quarantine -------------------------------------------------------


_REASON_CASES: Final[list[tuple[object, ReasonCode]]] = [
    ("not an object", ReasonCode.RECORD_NOT_AN_OBJECT),
    ({k: v for k, v in _event().items() if k != "title"}, ReasonCode.MISSING_REQUIRED_FIELD),
    (_event(title=7), ReasonCode.INVALID_FIELD_TYPE),
    (_event(all_day="no"), ReasonCode.INVALID_FIELD_TYPE),
    (_event(attendees={}), ReasonCode.INVALID_FIELD_TYPE),
    (_event(status="maybe"), ReasonCode.INVALID_FIELD_VALUE),
    (_event(provider_event_id_format="stable"), ReasonCode.INVALID_FIELD_VALUE),
    (_event(start_utc="2026-12-01 15:00"), ReasonCode.UNPARSEABLE_TIMESTAMP),
    (_event(end_utc="2026-12-01T16:00:00"), ReasonCode.UNPARSEABLE_TIMESTAMP),
    (_event(start_utc="0001-01-01T00:00:00+01:00"), ReasonCode.UNPARSEABLE_TIMESTAMP),
    (_event(calendar_ref="c" * 321), ReasonCode.IDENTIFIER_UNREPRESENTABLE),
    (_event(ical_uid=""), ReasonCode.IDENTIFIER_UNREPRESENTABLE),
    (_event(provider_event_id="e" * 1025), ReasonCode.IDENTIFIER_UNREPRESENTABLE),
    (_event(title="t" * 201), ReasonCode.TITLE_UNREPRESENTABLE),
    (_event(title="   "), ReasonCode.TITLE_UNREPRESENTABLE),
    (_event(timezone_name="Eastern Standard Time"), ReasonCode.TIMEZONE_NOT_IANA),
    (_event(timezone_name="Mars/Olympus"), ReasonCode.TIMEZONE_NOT_IANA),
    (_event(virtual_meeting_url="http://meet.example.invalid/x"), ReasonCode.URL_UNREPRESENTABLE),
    (_event(virtual_meeting_url="https://" + "a" * 2050), ReasonCode.URL_UNREPRESENTABLE),
    (_event(location_text="l" * 501), ReasonCode.LOCATION_UNREPRESENTABLE),
    (_event(attendees=[{"display_name": "No address"}]), ReasonCode.ATTENDEES_UNREPRESENTABLE),
    (_event(attendees=["a@example.invalid"]), ReasonCode.ATTENDEES_UNREPRESENTABLE),
    (
        _event(attendees=[{"email": "A@example.invalid"}, {"email": "a@example.invalid"}]),
        ReasonCode.ATTENDEES_UNREPRESENTABLE,
    ),
    (
        _event(
            attendees=[
                {"email": "a@example.invalid", "is_organizer": True},
                {"email": "b@example.invalid", "is_organizer": True},
            ]
        ),
        ReasonCode.ATTENDEES_UNREPRESENTABLE,
    ),
    (_event(attendees=[{"email": "not-an-address"}]), ReasonCode.ATTENDEES_UNREPRESENTABLE),
    (
        _event(attendees=[{"email": "a@example.invalid", "response_status": "yes"}]),
        ReasonCode.ATTENDEES_UNREPRESENTABLE,
    ),
    (_event(all_day=True), ReasonCode.ALL_DAY_UNSUPPORTED),
    (_event(series_ical_uid="uid-series@example.invalid"), ReasonCode.SERIES_KEY_INCOMPLETE),
    (
        _event(occurrence_original_start_utc="2026-12-01T15:00:00Z"),
        ReasonCode.SERIES_KEY_INCOMPLETE,
    ),
    (_event(end_utc="2026-12-01T14:59:59Z"), ReasonCode.END_BEFORE_START),
]


@pytest.mark.parametrize(("record", "reason"), _REASON_CASES, ids=lambda v: str(v)[:40])
def test_every_quarantine_reason(record: object, reason: ReasonCode) -> None:
    data = _publication(record)
    assert reason in _reasons(data)
    _no_content(data)


def test_every_reason_code_is_exercised() -> None:
    exercised = {reason for _, reason in _REASON_CASES} | {ReasonCode.DUPLICATE_OCCURRENCE_KEY}
    assert exercised == set(ReasonCode)


def test_one_bad_record_never_rejects_the_publication() -> None:
    parsed = parse_publication(_publication(_event(title=""), _event(ical_uid="uid-0002")))
    assert parsed.status is PublicationStatus.ACCEPTED
    assert parsed.publication is not None
    assert [event.ordinal for event in parsed.publication.events] == [1]
    assert [entry.ordinal for entry in parsed.publication.quarantined] == [0]


def test_two_records_with_one_occurrence_key_are_both_quarantined() -> None:
    occurrence = {
        "series_ical_uid": "uid-s@example.invalid",
        "occurrence_original_start_utc": "2026-12-01T15:00:00Z",
    }
    parsed = parse_publication(
        _publication(
            _event(**occurrence),
            # The same instant, another spelling: still one key.
            _event(**{**occurrence, "occurrence_original_start_utc": "2026-12-01T10:00:00-05:00"}),
            _event(ical_uid="uid-0002"),
        )
    )
    assert parsed.publication is not None
    assert [event.ordinal for event in parsed.publication.events] == [2]
    assert [(entry.ordinal, entry.reasons) for entry in parsed.publication.quarantined] == [
        (0, (ReasonCode.DUPLICATE_OCCURRENCE_KEY,)),
        (1, (ReasonCode.DUPLICATE_OCCURRENCE_KEY,)),
    ]


def test_a_single_meeting_and_an_occurrence_of_one_uid_are_distinct_keys() -> None:
    parsed = parse_publication(
        _publication(
            _event(),
            _event(
                series_ical_uid="uid-0001@example.invalid",
                occurrence_original_start_utc="2026-12-01T15:00:00Z",
            ),
        )
    )
    assert parsed.publication is not None
    assert len(parsed.publication.events) == 2


def test_values_are_kept_exactly() -> None:
    url = "https://Meet.Example.invalid:443/Room?b=2&a=1#x"
    parsed = parse_publication(
        _publication(_event(virtual_meeting_url=url, location_text="", title=" Padded "))
    )
    assert parsed.publication is not None
    (event,) = parsed.publication.events
    assert event.virtual_meeting_url == url
    assert event.location_text == ""
    assert event.title == " Padded "
