"""WP-MTG-01: the Meeting records domain (package sections 34.8-34.12, 35.5-35.9).

Covers the domain portions of MYPA-MTG-AC-001..015, 018 and 021: identifier
prefixes, bounds, aware-time and IANA validation (including DST boundaries and
offset/zone mismatch), end >= start, cancellation pairing, the A/B/C series
selector, attendee normalization/duplicate/organizer rules, note composition,
the section 35.6 URL rule, the section 35.9 digest sort key, the D-21 name
constants and the D-20 error family.
"""

from __future__ import annotations

import dataclasses
import hashlib
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from my_pa.domain.common.identifiers import (
    IdKind,
    InvalidIdentifierError,
    make_identifier,
    validate_identifier,
)
from my_pa.domain.meeting import (
    DEFAULT_MEETING_PAGE_SIZE,
    MAX_ATTENDEE_DISPLAY_NAME_CHARACTERS,
    MAX_ATTENDEE_EMAIL_CHARACTERS,
    MAX_MEETING_ATTACHMENTS,
    MAX_MEETING_ATTENDEES,
    MAX_MEETING_CLEAR_FIELDS,
    MAX_MEETING_DESCRIPTION_CHARACTERS,
    MAX_MEETING_IDEMPOTENCY_KEY_CHARACTERS,
    MAX_MEETING_LOCATION_CHARACTERS,
    MAX_MEETING_NOTES_CHARACTERS,
    MAX_MEETING_PAGE_SIZE,
    MAX_MEETING_QUERY_CHARACTERS,
    MAX_MEETING_TITLE_CHARACTERS,
    MAX_TIMEZONE_NAME_CHARACTERS,
    MAX_VIRTUAL_MEETING_URL_CHARACTERS,
    MEETING_WRITE_CAPABILITY_NAMES,
    MEETINGS_CREATE_NAME,
    MEETINGS_SERIES_UPDATE_NAME,
    MEETINGS_UPDATE_NAME,
    MIN_MEETING_IDEMPOTENCY_KEY_CHARACTERS,
    AttendeeResponseStatus,
    MeetingActor,
    MeetingAttachmentAvailability,
    MeetingClearField,
    MeetingCreateRequest,
    MeetingCursorError,
    MeetingError,
    MeetingErrorField,
    MeetingHistoryAction,
    MeetingIdempotencyConflictError,
    MeetingInvalidRequestError,
    MeetingListRequest,
    MeetingNotesMode,
    MeetingNotFoundError,
    MeetingOutcome,
    MeetingSearchRequest,
    MeetingSeriesSelector,
    MeetingSeriesUpdateRequest,
    MeetingSortDirection,
    MeetingStaleVersionError,
    MeetingStatus,
    MeetingTimeScope,
    MeetingUnavailableError,
    MeetingUpdateRequest,
    NormalizedAttendee,
    attendee_digest_sort_key,
    compose_appended_note,
    compose_note_body,
    normalize_attendee,
    normalize_attendee_email,
    note_content_sha256,
    validate_attendee_set,
    validate_aware_instant,
    validate_cancellation_pairing,
    validate_meeting_description,
    validate_meeting_location_text,
    validate_meeting_notes_markdown,
    validate_meeting_time_range,
    validate_meeting_title,
    validate_timezone_name,
    validate_virtual_meeting_url,
)
from my_pa.domain.meeting import model as meeting_model
from my_pa.domain.relationship.normalization import (
    ExternalIdentifierNamespace,
    normalize_identifier,
)

MEETING = make_identifier(IdKind.MEETING, "aaaa1111bbbb")
SERIES = make_identifier(IdKind.MEETING_SERIES, "aaaa1111bbbb")
PROJECT = make_identifier(IdKind.PROJECT, "aaaa1111bbbb")
ENTITY_A = make_identifier(IdKind.ENTITY, "aaaa1111aaaa")
ENTITY_B = make_identifier(IdKind.ENTITY, "bbbb2222bbbb")
DOC_A = make_identifier(IdKind.MANAGED_DOCUMENT, "aaaa1111aaaa")
DOC_B = make_identifier(IdKind.MANAGED_DOCUMENT, "bbbb2222bbbb")
ATTACH_A = make_identifier(IdKind.MEETING_ATTACHMENT, "aaaa1111aaaa")
START = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)
NEW_YORK = "America/New_York"


def _refused(
    token: MeetingErrorField,
) -> AbstractContextManager[pytest.ExceptionInfo[MeetingInvalidRequestError]]:
    return pytest.raises(MeetingInvalidRequestError, match=f": {token.value}$")


def _create(**overrides: object) -> MeetingCreateRequest:
    arguments: dict[str, object] = {
        "title": "Weekly sync",
        "start_at": START,
        "timezone_name": NEW_YORK,
    }
    arguments.update(overrides)
    return MeetingCreateRequest(**arguments)  # type: ignore[arg-type]


# ------------------------------------------------------------------- identifiers

MEETING_PREFIXES = {
    IdKind.MEETING: "mtg",
    IdKind.MEETING_SERIES: "mser",
    IdKind.MEETING_ATTENDEE: "matt",
    IdKind.MEETING_ATTACHMENT: "matc",
    IdKind.MEETING_HISTORY: "mhst",
    IdKind.MEETING_NOTE_VERSION: "mnote",
    IdKind.MEETING_SERIES_HISTORY: "mshst",
}


@pytest.mark.parametrize(("kind", "prefix"), MEETING_PREFIXES.items())
def test_meeting_prefixes_are_the_package_prefixes(kind: IdKind, prefix: str) -> None:
    assert kind.value == prefix
    identifier = make_identifier(kind, "abc123def456")
    assert validate_identifier(identifier, kind) == identifier


def test_meeting_prefixes_collide_with_no_other_kind() -> None:
    values = [kind.value for kind in IdKind]
    assert len(values) == len(set(values))
    others = {kind.value for kind in IdKind if kind not in MEETING_PREFIXES}
    assert not set(MEETING_PREFIXES.values()) & others


def test_a_meeting_identifier_is_not_a_series_identifier() -> None:
    with pytest.raises(InvalidIdentifierError):
        validate_identifier(MEETING, IdKind.MEETING_SERIES)


# ------------------------------------------------------------------------ bounds


def test_bounds_are_the_section_35_bounds() -> None:
    assert MAX_MEETING_TITLE_CHARACTERS == 200
    assert MAX_MEETING_LOCATION_CHARACTERS == 500
    assert MAX_MEETING_DESCRIPTION_CHARACTERS == 100_000
    assert MAX_MEETING_NOTES_CHARACTERS == 100_000
    assert MAX_ATTENDEE_DISPLAY_NAME_CHARACTERS == 200
    assert MAX_ATTENDEE_EMAIL_CHARACTERS == 320
    assert MAX_TIMEZONE_NAME_CHARACTERS == 64
    assert MAX_VIRTUAL_MEETING_URL_CHARACTERS == 2048
    assert MAX_MEETING_ATTENDEES == 100
    assert MAX_MEETING_ATTACHMENTS == 50
    assert MAX_MEETING_CLEAR_FIELDS == 5
    assert DEFAULT_MEETING_PAGE_SIZE == 50
    assert MAX_MEETING_PAGE_SIZE == 100
    assert MAX_MEETING_QUERY_CHARACTERS == 512


def test_idempotency_key_bound_is_one_to_128_with_no_eight_minimum() -> None:
    assert MIN_MEETING_IDEMPOTENCY_KEY_CHARACTERS == 1
    assert MAX_MEETING_IDEMPOTENCY_KEY_CHARACTERS == 128


def test_closed_enums_have_exactly_the_package_members() -> None:
    assert {m.value for m in MeetingStatus} == {"scheduled", "cancelled"}
    assert {m.value for m in AttendeeResponseStatus} == {
        "unknown",
        "needs_action",
        "accepted",
        "declined",
        "tentative",
    }
    assert {m.value for m in MeetingHistoryAction} == {"create", "update"}
    assert {m.value for m in MeetingActor} == {"principal", "assistant", "system"}
    assert {m.value for m in MeetingOutcome} == {"applied", "no_op"}
    assert {m.value for m in MeetingNotesMode} == {"append", "replace"}
    assert {m.value for m in MeetingClearField} == {
        "end_at",
        "location_text",
        "virtual_meeting_url",
        "description",
        "project_id",
    }
    assert {m.value for m in MeetingAttachmentAvailability} == {
        "active",
        "archived",
        "unavailable",
    }
    assert {m.value for m in MeetingTimeScope} == {"all", "upcoming", "past"}
    assert {m.value for m in MeetingSortDirection} == {"asc", "desc"}


# --------------------------------------------------------------- human strings


@pytest.mark.parametrize("title", ["x", "  padded  ", "Ünïcödé", "a" * 200, "\tTab kept"])
def test_title_is_kept_exactly(title: str) -> None:
    assert validate_meeting_title(title) == title


@pytest.mark.parametrize("title", ["", " ", "\n\t ", "a" * 201, None, 5])
def test_title_bounds_and_blankness_are_refused(title: object) -> None:
    with _refused(MeetingErrorField.TITLE):
        validate_meeting_title(title)


def test_location_and_description_keep_exact_content_including_empty() -> None:
    assert validate_meeting_location_text("") == ""
    assert validate_meeting_location_text(" Room 4 ") == " Room 4 "
    assert validate_meeting_description("") == ""
    assert validate_meeting_description("<b>not html</b>") == "<b>not html</b>"
    with _refused(MeetingErrorField.LOCATION_TEXT):
        validate_meeting_location_text("a" * 501)
    with _refused(MeetingErrorField.DESCRIPTION):
        validate_meeting_description("a" * 100_001)
    assert validate_meeting_description("a" * 100_000) == "a" * 100_000


@pytest.mark.parametrize("body", ["", "   ", "\n\n", "a" * 100_001])
def test_notes_must_be_nonblank_and_bounded(body: str) -> None:
    with _refused(MeetingErrorField.NOTES):
        validate_meeting_notes_markdown(body)


# ---------------------------------------------------------------- time and zone


@pytest.mark.parametrize("name", ["America/New_York", "UTC", "Europe/London", "Asia/Kolkata"])
def test_valid_iana_zones_are_accepted_exactly(name: str) -> None:
    assert validate_timezone_name(name) == name


@pytest.mark.parametrize(
    "name",
    ["", "Not/AZone", "America", " UTC", "UTC ", "../etc/passwd", "/etc/localtime", "a" * 65, None],
)
def test_invalid_zones_are_refused_without_quoting_them(name: object) -> None:
    with _refused(MeetingErrorField.TIMEZONE_NAME) as caught:
        validate_timezone_name(name)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None or caught.value.__suppress_context__


def test_naive_wall_time_is_refused() -> None:
    with _refused(MeetingErrorField.START_AT):
        validate_aware_instant(datetime(2026, 3, 8, 2, 30))
    with _refused(MeetingErrorField.END_AT):
        validate_aware_instant(
            datetime(2026, 3, 8, 2, 30),
            token=MeetingErrorField.END_AT,
        )
    with _refused(MeetingErrorField.START_AT):
        _create(start_at=datetime(2026, 3, 8, 2, 30))


def test_a_date_is_not_an_instant() -> None:
    with _refused(MeetingErrorField.START_AT):
        validate_aware_instant(date(2026, 3, 8))


def test_aware_instant_is_canonicalized_to_utc() -> None:
    supplied = datetime(2026, 10, 1, 10, 0, tzinfo=timezone(timedelta(hours=-4)))
    canonical = validate_aware_instant(supplied)
    assert canonical == datetime(2026, 10, 1, 14, 0, tzinfo=UTC)
    assert canonical.utcoffset() == timedelta(0)


def test_spring_forward_offset_instant_is_accepted_without_guessing() -> None:
    # 02:30 on 2026-03-08 does not exist in New York; the explicit -05:00 offset
    # makes it an unambiguous instant, which is all the server needs.
    supplied = datetime(2026, 3, 8, 2, 30, tzinfo=timezone(timedelta(hours=-5)))
    request = _create(start_at=supplied, timezone_name=NEW_YORK)
    assert request.start_at == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
    assert request.timezone_name == NEW_YORK


def test_fall_back_offsets_are_two_distinct_instants() -> None:
    first = _create(start_at=datetime(2026, 11, 1, 1, 30, tzinfo=timezone(timedelta(hours=-4))))
    second = _create(start_at=datetime(2026, 11, 1, 1, 30, tzinfo=timezone(timedelta(hours=-5))))
    assert first.start_at == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert second.start_at == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)


def test_zoneinfo_fold_is_resolved_by_the_aware_value_not_guessed() -> None:
    zone = ZoneInfo(NEW_YORK)
    earlier = validate_aware_instant(datetime(2026, 11, 1, 1, 30, fold=0, tzinfo=zone))
    later = validate_aware_instant(datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=zone))
    assert later - earlier == timedelta(hours=1)


def test_offset_and_zone_mismatch_is_accepted_and_zone_retained() -> None:
    tokyo_offset = datetime(2026, 10, 1, 23, 0, tzinfo=timezone(timedelta(hours=9)))
    request = _create(start_at=tokyo_offset, timezone_name=NEW_YORK)
    assert request.start_at == datetime(2026, 10, 1, 14, 0, tzinfo=UTC)
    assert request.timezone_name == NEW_YORK


def test_zone_round_trips_through_the_instant() -> None:
    request = _create(start_at=datetime(2026, 7, 4, 9, 0, tzinfo=ZoneInfo(NEW_YORK)))
    civil = request.start_at.astimezone(ZoneInfo(request.timezone_name))
    assert (civil.hour, civil.minute) == (9, 0)


def test_end_at_may_equal_start_at_but_not_precede_it() -> None:
    assert _create(end_at=START).end_at == START
    assert _create(end_at=None).end_at is None
    validate_meeting_time_range(START, START + timedelta(minutes=30))
    with _refused(MeetingErrorField.END_AT):
        _create(end_at=START - timedelta(seconds=1))
    with _refused(MeetingErrorField.END_AT):
        validate_meeting_time_range(START, START - timedelta(microseconds=1))


def test_end_at_is_compared_as_an_instant_across_offsets() -> None:
    end = datetime(2026, 10, 1, 10, 0, tzinfo=timezone(timedelta(hours=-4)))  # == START
    assert _create(end_at=end).end_at == START


def test_cancellation_pairs_status_and_cancelled_at() -> None:
    validate_cancellation_pairing(MeetingStatus.SCHEDULED, None)
    validate_cancellation_pairing(MeetingStatus.CANCELLED, START)
    with _refused(MeetingErrorField.STATUS):
        validate_cancellation_pairing(MeetingStatus.CANCELLED, None)
    with _refused(MeetingErrorField.STATUS):
        validate_cancellation_pairing(MeetingStatus.SCHEDULED, START)


# ---------------------------------------------------------------- series selector


def test_selector_a_is_standalone_with_no_series() -> None:
    request = _create()
    assert request.series_selector is MeetingSeriesSelector.STANDALONE
    assert request.meeting_series_id is None
    assert request.series_title is None


def test_selector_b_is_a_new_series() -> None:
    request = _create(series_title="Board meetings")
    assert request.series_selector is MeetingSeriesSelector.NEW_SERIES


def test_selector_c_is_an_existing_series() -> None:
    request = _create(meeting_series_id=SERIES)
    assert request.series_selector is MeetingSeriesSelector.EXISTING_SERIES


def test_both_selectors_at_once_are_refused() -> None:
    with _refused(MeetingErrorField.SERIES_SELECTOR):
        _create(meeting_series_id=SERIES, series_title="Board meetings")


def test_selector_values_are_validated() -> None:
    with _refused(MeetingErrorField.MEETING_SERIES_ID):
        _create(meeting_series_id=MEETING)
    with _refused(MeetingErrorField.TITLE):
        _create(series_title="   ")


def test_series_selector_is_not_a_constructor_argument() -> None:
    with pytest.raises(TypeError):
        _create(series_selector=MeetingSeriesSelector.STANDALONE)


# ---------------------------------------------------------------------- attendees


def test_display_name_is_trimmed_and_blank_is_absent() -> None:
    attendee = normalize_attendee(display_name="  Ada Lovelace  ")
    assert attendee.display_name == "Ada Lovelace"
    with_email = normalize_attendee(display_name="   ", email="ada@example.com")
    assert with_email.display_name is None


def test_display_name_is_not_casefolded_or_collapsed() -> None:
    assert normalize_attendee(display_name="Ada  LOVELACE").display_name == "Ada  LOVELACE"


def test_email_uses_the_relationship_intelligence_email_rule() -> None:
    raw = "  Ada.Lovelace@Example.COM "
    attendee = normalize_attendee(email=raw)
    assert attendee.email_normalized == normalize_identifier(ExternalIdentifierNamespace.EMAIL, raw)
    assert attendee.email_normalized == "ada.lovelace@example.com"
    assert normalize_attendee_email(raw) == attendee.email_normalized


def test_the_email_helper_is_the_relationship_normalizer_itself() -> None:
    # No second normalizer: the module calls the imported function by name.
    assert meeting_model.normalize_identifier is normalize_identifier


@pytest.mark.parametrize(
    "email", ["", "   ", "no-at-sign", "a@b@c", "a b@example.com", "x" * 321, 7]
)
def test_malformed_emails_are_refused(email: object) -> None:
    with _refused(MeetingErrorField.ATTENDEES):
        normalize_attendee(email=email)


def test_an_attendee_needs_one_identity_signal() -> None:
    with _refused(MeetingErrorField.ATTENDEES):
        normalize_attendee()
    with _refused(MeetingErrorField.ATTENDEES):
        normalize_attendee(display_name="   ")


def test_attendee_field_shapes_are_checked() -> None:
    assert normalize_attendee(entity_id=ENTITY_A).entity_id == ENTITY_A
    with _refused(MeetingErrorField.ENTITY_ID):
        normalize_attendee(entity_id=PROJECT)
    with _refused(MeetingErrorField.ATTENDEES):
        normalize_attendee(display_name="a" * 201)
    with _refused(MeetingErrorField.ORGANIZER):
        normalize_attendee(display_name="Ada", is_organizer="yes")
    with _refused(MeetingErrorField.RESPONSE_STATUS):
        normalize_attendee(display_name="Ada", response_status="maybe")


def test_response_status_defaults_to_unknown_and_accepts_the_closed_values() -> None:
    assert normalize_attendee(display_name="Ada").response_status is AttendeeResponseStatus.UNKNOWN
    for status in AttendeeResponseStatus:
        assert (
            normalize_attendee(display_name="Ada", response_status=status.value).response_status
            is status
        )


def test_duplicate_entity_is_refused() -> None:
    with _refused(MeetingErrorField.DUPLICATE_ATTENDEE):
        validate_attendee_set(
            [normalize_attendee(entity_id=ENTITY_A), normalize_attendee(entity_id=ENTITY_A)]
        )


def test_duplicate_normalized_email_is_refused() -> None:
    with _refused(MeetingErrorField.DUPLICATE_ATTENDEE):
        validate_attendee_set(
            [
                normalize_attendee(email="ada@example.com"),
                normalize_attendee(email="ADA@Example.com"),
            ]
        )


def test_same_entity_with_different_email_is_refused() -> None:
    with _refused(MeetingErrorField.DUPLICATE_ATTENDEE):
        validate_attendee_set(
            [
                normalize_attendee(entity_id=ENTITY_A, email="a@example.com"),
                normalize_attendee(entity_id=ENTITY_A, email="b@example.com"),
            ]
        )


def test_same_email_with_different_entity_is_refused() -> None:
    with _refused(MeetingErrorField.DUPLICATE_ATTENDEE):
        validate_attendee_set(
            [
                normalize_attendee(entity_id=ENTITY_A, email="a@example.com"),
                normalize_attendee(entity_id=ENTITY_B, email="a@example.com"),
            ]
        )


def test_exact_duplicate_name_only_object_is_refused() -> None:
    with _refused(MeetingErrorField.DUPLICATE_ATTENDEE):
        validate_attendee_set(
            [normalize_attendee(display_name="Sam"), normalize_attendee(display_name=" Sam ")]
        )


def test_same_display_name_alone_is_not_identity() -> None:
    members = validate_attendee_set(
        [
            normalize_attendee(display_name="Sam", email="sam.one@example.com"),
            normalize_attendee(display_name="Sam", email="sam.two@example.com"),
            normalize_attendee(display_name="Sam", response_status="accepted"),
            normalize_attendee(display_name="Sam"),
        ]
    )
    assert len(members) == 4


def test_at_most_one_organizer() -> None:
    validate_attendee_set([normalize_attendee(display_name="A", is_organizer=True)])
    with _refused(MeetingErrorField.ORGANIZER):
        validate_attendee_set(
            [
                normalize_attendee(display_name="A", is_organizer=True),
                normalize_attendee(display_name="B", is_organizer=True),
            ]
        )


def test_attendee_count_is_bounded() -> None:
    hundred = [normalize_attendee(email=f"p{index}@example.com") for index in range(100)]
    assert len(validate_attendee_set(hundred)) == 100
    with _refused(MeetingErrorField.ATTENDEES):
        validate_attendee_set([*hundred, normalize_attendee(email="p100@example.com")])


def test_digest_sort_key_is_the_section_35_9_order() -> None:
    attendee = NormalizedAttendee(
        display_name="Ada",
        email_normalized="ada@example.com",
        entity_id=ENTITY_A,
        is_organizer=True,
        response_status=AttendeeResponseStatus.ACCEPTED,
    )
    assert attendee_digest_sort_key(attendee) == (
        ENTITY_A,
        "ada@example.com",
        "Ada",
        True,
        "accepted",
    )
    bare = normalize_attendee(display_name="Zed")
    assert attendee_digest_sort_key(bare) == ("", "", "Zed", False, "unknown")


def test_organizer_sorts_before_response_status_in_the_digest_key() -> None:
    # D-17: section 35.9 puts is_organizer before response_status.
    organizer = normalize_attendee(
        display_name="Sam", is_organizer=True, response_status="accepted"
    )
    attendee = normalize_attendee(display_name="Sam", response_status="tentative")
    assert validate_attendee_set([organizer, attendee]) == (attendee, organizer)


def test_attendee_set_order_does_not_change_the_request() -> None:
    one = normalize_attendee(email="b@example.com")
    two = normalize_attendee(entity_id=ENTITY_A)
    assert _create(attendees=(one, two)) == _create(attendees=(two, one))


# -------------------------------------------------------------------------- notes


def test_append_is_prior_separator_chunk_exactly() -> None:
    assert compose_appended_note("First line  ", "  second") == "First line  \n\n  second"
    assert compose_note_body(MeetingNotesMode.APPEND, "a", "b") == "a\n\nb"


def test_initial_append_is_the_chunk_itself() -> None:
    assert compose_appended_note(None, " chunk ") == " chunk "


def test_append_refuses_a_blank_chunk() -> None:
    with _refused(MeetingErrorField.NOTES):
        compose_appended_note("prior", "   ")


def test_append_final_body_is_bounded() -> None:
    prior = "a" * (100_000 - 3)
    assert len(compose_appended_note(prior, "b")) == 100_000
    with _refused(MeetingErrorField.NOTES):
        compose_appended_note(prior, "bb")


def test_replace_stores_supplied_content_exactly() -> None:
    assert compose_note_body(MeetingNotesMode.REPLACE, "old", "  new body\n") == "  new body\n"
    assert compose_note_body(MeetingNotesMode.REPLACE, None, "x" * 100_000) == "x" * 100_000
    with _refused(MeetingErrorField.NOTES):
        compose_note_body(MeetingNotesMode.REPLACE, "old", "")


def test_note_sha256_is_over_the_utf8_body() -> None:
    body = "Ünïcödé notes\n\nmore"
    assert note_content_sha256(body) == hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert len(note_content_sha256(body)) == 64


# --------------------------------------------------------------------- virtual URL

ACCEPTED_URLS = [
    "HTTPS://Host:443/p?q#f",
    "https://example.com",
    "https://example.com/",
    "https://meet.example.com/abc-def?pwd=x&b=2&a=1",
    "https://example.com:8443/room#frag",
    "https://[2001:db8::1]:443/x",
    "https://example.com/%7Euser",
    "hTtPs://Example.COM/Path",
]


@pytest.mark.parametrize("url", ACCEPTED_URLS)
def test_accepted_url_is_returned_verbatim(url: str) -> None:
    assert validate_virtual_meeting_url(url) == url
    assert _create(virtual_meeting_url=url).virtual_meeting_url == url


REFUSED_URLS = [
    "",
    "http://example.com",
    "ftp://example.com",
    "example.com/path",
    "//example.com/path",
    "https:///path",
    "https://:443/",
    "https://user@example.com/",
    "https://user:pw@example.com/",
    "https://@example.com/",
    "https://:@example.com/",
    "https://example.com:99999/",
    "https://example.com:abc/",
    "https://[::1/",
    " https://example.com",
    "https://example.com ",
    "https://example.com/a b",
    "https://example.com/\x00",
    "https://example.com/\x1f",
    "https://example.com/\x7f",
    "https://example.com/\t",
    "https://example.com/\n",
    "https://example.com/" + "a" * 2029,
    None,
    42,
]


@pytest.mark.parametrize("url", REFUSED_URLS)
def test_refused_url_names_only_the_field(url: object) -> None:
    with _refused(MeetingErrorField.VIRTUAL_MEETING_URL) as caught:
        validate_virtual_meeting_url(url)
    if isinstance(url, str) and url.strip():
        assert url.strip() not in str(caught.value)
    assert caught.value.__cause__ is None


def test_url_length_bound_is_2048() -> None:
    url = "https://example.com/" + "a" * (2048 - len("https://example.com/"))
    assert validate_virtual_meeting_url(url) == url


# ----------------------------------------------------------------- request values


def test_create_request_normalizes_and_is_immutable() -> None:
    request = _create(
        attachment_document_ids=(DOC_B, DOC_A),
        project_id=PROJECT,
        location_text="",
        description="",
        notes_markdown="Agenda",
    )
    assert request.attachment_document_ids == (DOC_A, DOC_B)
    assert request.location_text == ""
    assert request.description == ""
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.title = "changed"  # type: ignore[misc]


def test_create_request_refuses_bad_fields() -> None:
    with _refused(MeetingErrorField.DOCUMENT_ID):
        _create(attachment_document_ids=(DOC_A, DOC_A))
    with _refused(MeetingErrorField.DOCUMENT_ID):
        _create(attachment_document_ids=(ATTACH_A,))
    with _refused(MeetingErrorField.DOCUMENT_ID):
        _create(
            attachment_document_ids=tuple(
                make_identifier(IdKind.MANAGED_DOCUMENT, f"doc{index:08d}") for index in range(51)
            )
        )
    with _refused(MeetingErrorField.PROJECT_ID):
        _create(project_id=MEETING)
    with _refused(MeetingErrorField.NOTES):
        _create(notes_markdown=" ")
    with _refused(MeetingErrorField.TIMEZONE_NAME):
        _create(timezone_name="Mars/Olympus")
    with _refused(MeetingErrorField.VIRTUAL_MEETING_URL):
        _create(virtual_meeting_url="http://example.com")


def _update(**overrides: object) -> MeetingUpdateRequest:
    arguments: dict[str, object] = {"meeting_id": MEETING}
    arguments.update(overrides)
    return MeetingUpdateRequest(**arguments)  # type: ignore[arg-type]


def test_update_distinguishes_omitted_empty_and_clear() -> None:
    omitted = _update(title="New")
    assert omitted.attendees_replace is None
    assert omitted.location_text is None
    assert omitted.clear_fields == ()
    emptied = _update(attendees_replace=())
    assert emptied.attendees_replace == ()
    set_empty = _update(location_text="")
    assert set_empty.location_text == ""
    cleared = _update(clear_fields=(MeetingClearField.PROJECT_ID, MeetingClearField.END_AT))
    assert cleared.clear_fields == (MeetingClearField.END_AT, MeetingClearField.PROJECT_ID)


def test_update_requires_a_material_selector() -> None:
    with _refused(MeetingErrorField.MUTATIONS):
        _update()
    with _refused(MeetingErrorField.MUTATIONS):
        _update(clear_fields=(), attachment_add_document_ids=(), attachment_remove_ids=())


def test_update_project_and_clear_project_cannot_coexist() -> None:
    with _refused(MeetingErrorField.CLEAR_FIELDS):
        _update(project_id=PROJECT, clear_fields=(MeetingClearField.PROJECT_ID,))


def test_update_clear_fields_are_closed_and_unique() -> None:
    with _refused(MeetingErrorField.CLEAR_FIELDS):
        _update(clear_fields=(MeetingClearField.END_AT, MeetingClearField.END_AT))
    with _refused(MeetingErrorField.CLEAR_FIELDS):
        _update(clear_fields=("title",))


def test_update_notes_fields_are_paired() -> None:
    assert _update(notes_mode=MeetingNotesMode.APPEND, notes_markdown="x").notes_mode is (
        MeetingNotesMode.APPEND
    )
    with _refused(MeetingErrorField.NOTES):
        _update(notes_mode=MeetingNotesMode.APPEND)
    with _refused(MeetingErrorField.NOTES):
        _update(notes_markdown="x")
    with _refused(MeetingErrorField.NOTES):
        _update(notes_mode=MeetingNotesMode.REPLACE, notes_markdown="   ")


def test_update_attachments_are_sorted_unique_and_typed() -> None:
    request = _update(attachment_add_document_ids=(DOC_B, DOC_A), attachment_remove_ids=(ATTACH_A,))
    assert request.attachment_add_document_ids == (DOC_A, DOC_B)
    with _refused(MeetingErrorField.ATTACHMENT_ID):
        _update(attachment_remove_ids=(DOC_A,))
    with _refused(MeetingErrorField.ATTACHMENT_ID):
        _update(attachment_remove_ids=(ATTACH_A, ATTACH_A))


def test_update_status_and_schedule() -> None:
    assert _update(status="cancelled").status is MeetingStatus.CANCELLED
    with _refused(MeetingErrorField.STATUS):
        _update(status="deleted")
    with _refused(MeetingErrorField.END_AT):
        _update(start_at=START, end_at=START - timedelta(minutes=1))
    with _refused(MeetingErrorField.START_AT):
        _update(start_at=datetime(2026, 1, 1))


def test_update_has_no_series_fields() -> None:
    # Series membership is immutable (AC-007): update carries no selector.
    with pytest.raises(TypeError):
        _update(title="x", meeting_series_id=SERIES)
    with pytest.raises(TypeError):
        _update(title="x", series_title="y")


def test_series_update_is_title_only() -> None:
    request = MeetingSeriesUpdateRequest(meeting_series_id=SERIES, title=" Exact ")
    assert request.title == " Exact "
    assert {f.name for f in dataclasses.fields(MeetingSeriesUpdateRequest)} == {
        "meeting_series_id",
        "title",
    }
    with _refused(MeetingErrorField.MEETING_SERIES_ID):
        MeetingSeriesUpdateRequest(meeting_series_id=MEETING, title="x")
    with _refused(MeetingErrorField.TITLE):
        MeetingSeriesUpdateRequest(meeting_series_id=SERIES, title="")


def test_list_request_defaults_and_bounds() -> None:
    request = MeetingListRequest()
    assert request.page_size == 50
    assert request.time_scope is MeetingTimeScope.ALL
    assert request.sort_direction is MeetingSortDirection.ASC
    assert MeetingListRequest(page_size=100).page_size == 100
    for bad in (0, 101, True, 1.5):
        with _refused(MeetingErrorField.PAGE_SIZE):
            MeetingListRequest(page_size=bad)  # type: ignore[arg-type]


def test_list_range_is_from_inclusive_before_exclusive() -> None:
    later = START + timedelta(hours=1)
    MeetingListRequest(start_at_from=START, start_at_before=later)
    with _refused(MeetingErrorField.START_AT):
        MeetingListRequest(start_at_from=START, start_at_before=START)
    with _refused(MeetingErrorField.START_AT):
        MeetingListRequest(start_at_from=later, start_at_before=START)


def test_list_filters_are_validated_and_normalized() -> None:
    request = MeetingListRequest(
        attendee_email=" Ada@Example.COM ", after=MEETING, status="scheduled", time_scope="past"
    )
    assert request.attendee_email == "ada@example.com"
    assert request.status is MeetingStatus.SCHEDULED
    assert request.time_scope is MeetingTimeScope.PAST
    with _refused(MeetingErrorField.CURSOR):
        MeetingListRequest(after=SERIES)
    with _refused(MeetingErrorField.ENTITY_ID):
        MeetingListRequest(attendee_entity_id=PROJECT)
    with _refused(MeetingErrorField.MEETING_SERIES_ID):
        MeetingListRequest(meeting_series_id=PROJECT)


def test_search_request_query_bounds() -> None:
    assert MeetingSearchRequest(query=" budget ").query == " budget "
    assert MeetingSearchRequest(query="q" * 512).filters == MeetingListRequest()
    for bad in ("", "   ", "q" * 513):
        with _refused(MeetingErrorField.QUERY):
            MeetingSearchRequest(query=bad)


REQUEST_TYPES = [
    MeetingCreateRequest,
    MeetingUpdateRequest,
    MeetingSeriesUpdateRequest,
    MeetingListRequest,
    MeetingSearchRequest,
]


@pytest.mark.parametrize("request_type", REQUEST_TYPES)
def test_no_request_carries_principal_idempotency_or_foreign_relations(
    request_type: type,
) -> None:
    # D-24: the Principal is an application parameter; AC-021: no conversation,
    # task or general-note relation is modelled on a Meeting request.
    names = {f.name for f in dataclasses.fields(request_type)}
    forbidden = {
        "principal_id",
        "idempotency_key",
        "request_digest",
        "conversation_id",
        "task_id",
        "capture_id",
        "note_id",
    }
    assert not names & forbidden


# ------------------------------------------------------------ capability names


def test_write_capability_names_are_the_frozen_literals() -> None:
    assert MEETINGS_CREATE_NAME == "meetings.create"
    assert MEETINGS_UPDATE_NAME == "meetings.update"
    assert MEETINGS_SERIES_UPDATE_NAME == "meetings.series.update"
    assert (
        frozenset({"meetings.create", "meetings.update", "meetings.series.update"})
        == MEETING_WRITE_CAPABILITY_NAMES
    )


# ------------------------------------------------------------------ error family


def test_error_family_is_closed_and_value_free() -> None:
    for error_type in (
        MeetingInvalidRequestError,
        MeetingNotFoundError,
        MeetingStaleVersionError,
        MeetingIdempotencyConflictError,
        MeetingCursorError,
        MeetingUnavailableError,
    ):
        assert issubclass(error_type, MeetingError)
    assert issubclass(MeetingError, ValueError)
    error = MeetingNotFoundError(MeetingErrorField.MEETING_ID)
    assert error.field is MeetingErrorField.MEETING_ID
    assert str(error) == "meeting reference not found: meeting_id"


def test_error_defaults_name_their_safe_field() -> None:
    assert MeetingStaleVersionError().field is MeetingErrorField.EXPECTED_VERSION
    assert MeetingIdempotencyConflictError().field is MeetingErrorField.IDEMPOTENCY_KEY
    assert MeetingCursorError().field is MeetingErrorField.CURSOR


def test_error_tokens_are_safe_detail_values() -> None:
    # Every token is a section 35.16 SafeDetail name or an existing SafeDetail
    # value, so WP-MTG-04 translates by lookup and never adds a token.
    section_35_16 = {
        "meeting_id",
        "meeting_series_id",
        "attendees",
        "attendee_id",
        "attachment_id",
        "timezone_name",
        "start_at",
        "end_at",
        "virtual_meeting_url",
        "notes",
        "series_selector",
        "duplicate_attendee",
        "organizer",
        "location_text",
        "description",
        "response_status",
        "clear_fields",
        "title",
        "status",
        "document_id",
        "project_id",
        "entity_id",
        "expected_version",
        "idempotency_key",
        "cursor",
        "query",
    }
    existing_safe_detail = {"page_size", "mutations"}
    assert {token.value for token in MeetingErrorField} == section_35_16 | existing_safe_detail


def test_rejected_values_never_reach_the_message() -> None:
    private_email = "secret.person@example.com"
    with pytest.raises(MeetingInvalidRequestError) as caught:
        validate_attendee_set(
            [normalize_attendee(email=private_email), normalize_attendee(email=private_email)]
        )
    assert private_email not in str(caught.value)
    with pytest.raises(MeetingInvalidRequestError) as caught_title:
        validate_meeting_title("   secret title spaces " * 20)
    assert "secret" not in str(caught_title.value)
