"""WP2: the pure provider resolution rules (contract section 12.2, rulings D2, D5, D9).

Rules 1-7, idempotency (an identical event changes nothing), the provider-owned
field set and the deterministic idempotency key. Synthetic values only.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.domain.meeting.model import MeetingClearField, MeetingStatus
from my_pa.domain.meeting_sync.model import (
    EventStatus,
    MeetingSyncEvent,
    OccurrenceKey,
    ProviderBindingState,
    ProviderEventIdFormat,
)
from my_pa.domain.meeting_sync.resolution import (
    SYNC_IDEMPOTENCY_KEY_PREFIX,
    BindingAttributes,
    KnownOccurrence,
    ProviderFields,
    ResolutionDiagnostic,
    ResolutionKind,
    ordering_skip,
    provider_create,
    provider_update,
    refreshed_binding,
    resolve_event,
    sync_idempotency_key,
)

START: Final = datetime(2026, 12, 1, 15, tzinfo=UTC)
SEEN: Final = datetime(2026, 11, 21, 6, tzinfo=UTC)
GENERATED: Final = datetime(2026, 11, 21, 5, tzinfo=UTC)
SHA: Final = "a" * 64
MEETING: Final = "mtg_syncres0001syncres"
SERIES: Final = "mser_syncres0001syncres"
BOUND: Final = KnownOccurrence(binding_id="mpbnd_syncres0001syncres", meeting_id=MEETING)


def _single(**overrides: object) -> MeetingSyncEvent:
    values: dict[str, object] = {
        "ordinal": 0,
        "calendar_ref": "cal-synthetic",
        "ical_uid": "uid-0001@example.invalid",
        "series_ical_uid": None,
        "occurrence_original_start_utc": None,
        "start_utc": START,
        "end_utc": START + timedelta(hours=1),
        "timezone_name": "America/New_York",
        "status": EventStatus.CONFIRMED,
        "provider_event_id": "evt-0001",
        "provider_event_id_format": ProviderEventIdFormat.MUTABLE,
        "title": "Synthetic sync",
        "location_text": "Room 1",
        "virtual_meeting_url": "https://meet.example.invalid/x",
        "generated_at_utc": GENERATED,
    }
    values.update(overrides)
    return MeetingSyncEvent(**values)  # type: ignore[arg-type]


def _occurrence(**overrides: object) -> MeetingSyncEvent:
    return _single(
        series_ical_uid="uid-series@example.invalid",
        occurrence_original_start_utc=START,
        **overrides,
    )


def _fields(event: MeetingSyncEvent) -> ProviderFields:
    return ProviderFields(
        title=event.title,
        start_at=event.start_utc,
        end_at=event.end_utc,
        timezone_name=event.timezone_name,
        status=event.meeting_status,
        location_text=event.location_text,
        virtual_meeting_url=event.virtual_meeting_url,
    )


# ---- rules 1-6 ---------------------------------------------------------------


def test_rule_1_a_known_key_updates_the_bound_meeting() -> None:
    for event in (_single(), _occurrence()):
        resolution = resolve_event(
            event,
            bound=BOUND,
            series_id=SERIES,
            other_kind_bound=False,
            source_sha256=SHA,
            tombstoned=False,
        )
        assert resolution.kind is ResolutionKind.UPDATE_BOUND
        assert resolution.meeting_id == MEETING


def test_rule_2_an_unknown_occurrence_of_a_known_series_joins_it() -> None:
    resolution = resolve_event(
        _occurrence(),
        bound=None,
        series_id=SERIES,
        other_kind_bound=False,
        source_sha256=SHA,
        tombstoned=False,
    )
    assert resolution.kind is ResolutionKind.CREATE_IN_SERIES
    assert resolution.meeting_series_id == SERIES
    request = provider_create(_occurrence(), meeting_series_id=SERIES)
    assert request.meeting_series_id == SERIES and request.series_title is None


def test_rule_3_an_unknown_series_creates_one_titled_by_the_event() -> None:
    resolution = resolve_event(
        _occurrence(),
        bound=None,
        series_id=None,
        other_kind_bound=False,
        source_sha256=SHA,
        tombstoned=False,
    )
    assert resolution.kind is ResolutionKind.CREATE_SERIES
    request = provider_create(_occurrence(), new_series=True)
    assert request.series_title == "Synthetic sync"
    assert request.meeting_series_id is None


def test_an_unknown_single_meeting_is_a_standalone_create() -> None:
    resolution = resolve_event(
        _single(),
        bound=None,
        series_id=None,
        other_kind_bound=False,
        source_sha256=SHA,
        tombstoned=False,
    )
    assert resolution.kind is ResolutionKind.CREATE_STANDALONE
    request = provider_create(_single())
    assert request.meeting_series_id is None and request.series_title is None
    assert request.end_at == START + timedelta(hours=1)
    assert request.attendees == () and request.description is None


def test_rule_4_resolution_takes_no_title_or_time_input() -> None:
    # The decision reads only the binding lookups: two events that differ only
    # in title and time resolve identically.
    other = _single(title="Another title", start_utc=START + timedelta(days=3),
                    end_utc=START + timedelta(days=3, hours=1))  # fmt: skip
    for bound in (None, BOUND):
        assert resolve_event(
            _single(),
            bound=bound,
            series_id=None,
            other_kind_bound=False,
            source_sha256=SHA,
            tombstoned=False,
        ) == resolve_event(
            other,
            bound=bound,
            series_id=None,
            other_kind_bound=False,
            source_sha256=SHA,
            tombstoned=False,
        )


def test_rule_5_a_known_cancelled_event_cancels_and_never_deletes() -> None:
    event = _single(status=EventStatus.CANCELLED)
    assert (
        resolve_event(
            event,
            bound=BOUND,
            series_id=None,
            other_kind_bound=False,
            source_sha256=SHA,
            tombstoned=False,
        ).kind
        is ResolutionKind.UPDATE_BOUND
    )
    request = provider_update(MEETING, _fields(_single()), event)
    assert request is not None and request.status is MeetingStatus.CANCELLED
    # Un-cancel: a confirmed event over a cancelled Meeting.
    current = replace(_fields(_single()), status=MeetingStatus.CANCELLED)
    revived = provider_update(MEETING, current, _single())
    assert revived is not None and revived.status is MeetingStatus.SCHEDULED


@pytest.mark.parametrize("make", [_single, _occurrence])
def test_d5_a_cancelled_unknown_event_is_skipped(make: object) -> None:
    event = make(status=EventStatus.CANCELLED)  # type: ignore[operator]
    for series_id in (None, SERIES):
        resolution = resolve_event(
            event,
            bound=None,
            series_id=series_id,
            other_kind_bound=False,
            source_sha256=SHA,
            tombstoned=False,
        )
        assert resolution.kind is ResolutionKind.SKIP
        assert resolution.diagnostic is ResolutionDiagnostic.CANCELLED_UNKNOWN_SKIPPED


def test_rule_6_a_changed_provider_id_is_the_same_meeting() -> None:
    event = _single(provider_event_id="evt-renamed")
    assert resolve_event(
        event,
        bound=BOUND,
        series_id=None,
        other_kind_bound=False,
        source_sha256=SHA,
        tombstoned=False,
    ).meeting_id == (MEETING)
    assert event.key == _single().key
    # It changes no Meeting field: only the binding attribute.
    assert provider_update(MEETING, _fields(_single()), event) is None
    current = BindingAttributes(
        "evt-0001", ProviderEventIdFormat.MUTABLE, ProviderBindingState.ACTIVE, SHA, 0, SEEN
    )
    refreshed = refreshed_binding(current, event, source_sha256="b" * 64, seen_at=SEEN)
    assert refreshed is not None
    attributes, material = refreshed
    assert material and attributes.provider_event_id == "evt-renamed"


def test_d9_the_other_kind_bound_is_refused_not_given_a_second_identity() -> None:
    for event in (_single(), _occurrence()):
        resolution = resolve_event(
            event,
            bound=None,
            series_id=None,
            other_kind_bound=True,
            source_sha256=SHA,
            tombstoned=False,
        )
        assert resolution.kind is ResolutionKind.SKIP
        assert resolution.diagnostic is ResolutionDiagnostic.BINDING_KIND_CONFLICT


def test_a_moved_occurrence_keeps_its_key() -> None:
    moved = _occurrence(start_utc=START + timedelta(hours=2), end_utc=START + timedelta(hours=3))
    assert moved.key == _occurrence().key
    request = provider_update(MEETING, _fields(_occurrence()), moved)
    assert request is not None
    assert (request.start_at, request.end_at) == (
        START + timedelta(hours=2),
        START + timedelta(hours=3),
    )


# ---- rule 7: publication ordering (WP2-F1) -------------------------------------------


def _stamped_bound(stamp: datetime | None, sha: str | None = SHA) -> KnownOccurrence:
    return replace(BOUND, last_applied_generated_at_utc=stamp, last_seen_source_sha256=sha)


def test_rule_7_a_strictly_older_stamp_is_a_stale_skip() -> None:
    bound = _stamped_bound(GENERATED + timedelta(seconds=1))
    for event in (_single(), _occurrence(), _single(status=EventStatus.CANCELLED)):
        resolution = resolve_event(
            event,
            bound=bound,
            series_id=None,
            other_kind_bound=False,
            source_sha256="b" * 64,
            tombstoned=False,
        )
        assert resolution.kind is ResolutionKind.SKIP
        assert resolution.diagnostic is ResolutionDiagnostic.STALE_RECORD_SKIPPED
        assert resolution.meeting_id == MEETING
    # Even from the very publication the binding last recorded.
    assert ordering_skip(_single(), bound, source_sha256=SHA) is (
        ResolutionDiagnostic.STALE_RECORD_SKIPPED
    )


def test_rule_7_an_equal_stamp_from_another_publication_is_an_ordering_conflict() -> None:
    bound = _stamped_bound(GENERATED)
    resolution = resolve_event(
        _single(),
        bound=bound,
        series_id=None,
        other_kind_bound=False,
        source_sha256="b" * 64,
        tombstoned=False,
    )
    assert resolution.kind is ResolutionKind.SKIP
    assert resolution.diagnostic is ResolutionDiagnostic.ORDERING_CONFLICT_SKIPPED
    # The same publication with the same stamp is the idempotent replay path.
    same = resolve_event(
        _single(),
        bound=bound,
        series_id=None,
        other_kind_bound=False,
        source_sha256=SHA,
        tombstoned=False,
    )
    assert same.kind is ResolutionKind.UPDATE_BOUND and same.diagnostic is None


def test_rule_7_a_newer_stamp_or_an_unstamped_binding_applies() -> None:
    for bound in (
        _stamped_bound(GENERATED - timedelta(seconds=1)),
        _stamped_bound(None, None),
        BOUND,
    ):
        resolution = resolve_event(
            _single(),
            bound=bound,
            series_id=None,
            other_kind_bound=False,
            source_sha256="b" * 64,
            tombstoned=False,
        )
        assert resolution.kind is ResolutionKind.UPDATE_BOUND
        assert resolution.diagnostic is None


def test_rule_7_a_no_change_record_still_carries_its_stamp() -> None:
    current = BindingAttributes(
        "evt-0001",
        ProviderEventIdFormat.MUTABLE,
        ProviderBindingState.ACTIVE,
        SHA,
        0,
        SEEN,
        GENERATED - timedelta(hours=1),
    )
    refreshed = refreshed_binding(current, _single(), source_sha256="c" * 64, seen_at=SEEN)
    assert refreshed is not None
    attributes, material = refreshed
    assert not material
    assert attributes.last_applied_generated_at_utc == GENERATED


# ---- provider-owned fields and idempotency ------------------------------------------


def test_an_identical_event_is_no_update() -> None:
    assert provider_update(MEETING, _fields(_single()), _single()) is None


def test_only_provider_owned_fields_are_named() -> None:
    current = ProviderFields(
        title="Old",
        start_at=START - timedelta(days=1),
        end_at=None,
        timezone_name="UTC",
        status=MeetingStatus.SCHEDULED,
        location_text="Old room",
        virtual_meeting_url="https://old.example.invalid/",
    )
    request = provider_update(
        MEETING, current, _single(location_text=None, virtual_meeting_url=None)
    )
    assert request is not None
    assert request.title == "Synthetic sync"
    assert request.timezone_name == "America/New_York"
    assert request.end_at == START + timedelta(hours=1)
    assert request.clear_fields == (
        MeetingClearField.LOCATION_TEXT,
        MeetingClearField.VIRTUAL_MEETING_URL,
    )
    assert request.attendees_replace is None
    assert request.description is None and request.project_id is None
    assert request.notes_mode is None and request.prep_markdown is None
    assert request.meeting_series_id is None and not request.detach_series
    assert request.attachment_add_document_ids == () and request.attachment_remove_ids == ()


def test_a_start_change_alone_carries_the_event_end() -> None:
    current = replace(_fields(_single()), start_at=START - timedelta(minutes=5))
    request = provider_update(MEETING, current, _single())
    assert request is not None and request.end_at == START + timedelta(hours=1)


def test_the_same_observation_is_an_unchanged_binding() -> None:
    current = BindingAttributes(
        "evt-0001", ProviderEventIdFormat.MUTABLE, ProviderBindingState.ACTIVE, SHA, 0, SEEN
    )
    assert refreshed_binding(current, _single(), source_sha256=SHA, seen_at=SEEN) is None
    # A later publication with identical attributes refreshes last_seen only.
    later = refreshed_binding(
        current, _single(), source_sha256="c" * 64, seen_at=SEEN + timedelta(hours=1)
    )
    assert later is not None
    attributes, material = later
    assert not material
    assert attributes.last_seen_source_sha256 == "c" * 64
    assert attributes.last_seen_at == SEEN + timedelta(hours=1)
    # A cancellation is material on the binding.
    cancelled = refreshed_binding(
        current, _single(status=EventStatus.CANCELLED), source_sha256=SHA, seen_at=SEEN
    )
    assert cancelled is not None and cancelled[1]
    assert cancelled[0].provider_state is ProviderBindingState.CANCELLED


def test_the_idempotency_key_is_deterministic_bounded_and_distinct() -> None:
    key = OccurrenceKey("cal-synthetic", "uid-0001@example.invalid", None)
    first = sync_idempotency_key(key, source_sha256=SHA, record_ordinal=0)
    assert first == sync_idempotency_key(key, source_sha256=SHA, record_ordinal=0)
    assert first.startswith(SYNC_IDEMPOTENCY_KEY_PREFIX)
    assert 1 <= len(first) <= 128
    assert "uid-0001" not in first
    others = {
        sync_idempotency_key(key, source_sha256=SHA, record_ordinal=1),
        sync_idempotency_key(key, source_sha256="b" * 64, record_ordinal=0),
        sync_idempotency_key(
            OccurrenceKey("cal-synthetic", "uid-0001@example.invalid", START),
            source_sha256=SHA,
            record_ordinal=0,
        ),
        sync_idempotency_key(
            OccurrenceKey("cal-other", "uid-0001@example.invalid", None),
            source_sha256=SHA,
            record_ordinal=0,
        ),
    }
    assert first not in others and len(others) == 4
