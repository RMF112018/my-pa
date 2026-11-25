"""WP2: `MeetingProviderSync` over the FAST fake unit of work (rulings D2, D5-D7, D12).

The FAST half; the database half is
`tests/database/test_meeting_provider_sync_application.py`. Every value is
synthetic, parsed through the real `meeting_sync_v1` parser.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.application.meeting_provider_sync import (
    MEETINGS_PROVIDER_SYNC_SOURCE,
    MeetingProviderSync,
    MeetingSyncOutcome,
    SyncOutcomeKind,
)
from my_pa.application.meetings import MeetingApplication
from my_pa.domain.meeting.model import (
    MeetingActor,
    MeetingCreateRequest,
    MeetingErrorField,
    MeetingInvalidRequestError,
    MeetingStatus,
    MeetingUpdateRequest,
)
from my_pa.domain.meeting_sync.model import MeetingSyncEvent, ProviderBindingState
from my_pa.domain.meeting_sync.resolution import ResolutionDiagnostic
from my_pa.domain.record_events import RecordEventActorClass
from my_pa.infrastructure.meeting_sync.parser import parse_publication
from tests.conftest import FakeUnitOfWork, World

PRINCIPAL: Final = "prn_mpsyncfast00000001"
OTHER: Final = "prn_mpsyncfast00000002"
NOW: Final = datetime(2026, 11, 21, 6, tzinfo=UTC)
SHA_A: Final = "a" * 64
SHA_B: Final = "b" * 64
GENERATED: Final = "2026-11-21T05:00:00Z"
STAMP_A: Final = datetime(2026, 11, 21, 5, tzinfo=UTC)
STAMP_B: Final = STAMP_A + timedelta(hours=1)
#: A test's publication digest names its ordering stamp unless it states one: A,
#: B, C in publication order (resolution rule 7).
SHA_C: Final = "c" * 64
STAMP_C: Final = STAMP_B + timedelta(hours=1)
STAMPS: Final = {SHA_A: STAMP_A, SHA_B: STAMP_B, SHA_C: STAMP_C}


def _stamped(event: MeetingSyncEvent, sha: str, stamp: datetime | None) -> MeetingSyncEvent:
    return replace(event, generated_at_utc=STAMPS.get(sha, STAMP_A) if stamp is None else stamp)


SYNC: Final = MeetingProviderSync()
APP: Final = MeetingApplication()
SERIES_UID: Final = "uid-series@example.invalid"


def _event(**overrides: object) -> MeetingSyncEvent:
    record: dict[str, object] = {
        "calendar_ref": "cal-synthetic",
        "ical_uid": "uid-0001@example.invalid",
        "start_utc": "2026-12-01T15:00:00Z",
        "end_utc": "2026-12-01T16:00:00Z",
        "timezone_name": "America/New_York",
        "status": "confirmed",
        "all_day": False,
        "provider_event_id": "evt-0001",
        "provider_event_id_format": "mutable",
        "title": "Synthetic sync",
        "location_text": "Room 1",
    }
    record.update(overrides)
    data = json.dumps(
        {
            "schema": "meeting_sync_v1",
            "schema_version": "1.0.0",
            "generated_at_utc": GENERATED,
            "events": [record],
        }
    ).encode()
    publication = parse_publication(data).publication
    assert publication is not None
    (event,) = publication.events
    return event


def _occurrence(original: str = "2026-12-02T14:00:00Z", **overrides: object) -> MeetingSyncEvent:
    values: dict[str, object] = {
        "ical_uid": SERIES_UID,
        "series_ical_uid": SERIES_UID,
        "occurrence_original_start_utc": original,
        "start_utc": original,
        "end_utc": original.replace("14:00", "14:30"),
    }
    values.update(overrides)
    return _event(**values)


def _apply(
    world: World,
    event: MeetingSyncEvent,
    *,
    sha: str = SHA_A,
    principal: str = PRINCIPAL,
    stamp: datetime | None = None,
) -> MeetingSyncOutcome:
    stamped = _stamped(event, sha, stamp)
    with FakeUnitOfWork(world) as uow:
        return SYNC.apply_event(
            uow,
            principal,
            stamped,
            source_sha256=sha,
            # The FAST world models no ingest snapshot; any `isnp_` names it.
            source_snapshot_id=f"isnp_{sha[:16]}",
            now=NOW,
        )


@pytest.fixture
def world() -> World:
    return World()


def test_an_unknown_single_meeting_is_created_and_bound_by_the_system(world: World) -> None:
    outcome = _apply(world, _event())
    assert outcome.kind is SyncOutcomeKind.CREATED
    meeting = world.meetings[(PRINCIPAL, outcome.meeting_id)]
    assert meeting.meeting_series_id is None
    assert meeting.end_at == datetime(2026, 12, 1, 16, tzinfo=UTC)
    (receipt,) = world.meeting_history.values()
    assert receipt.actor is MeetingActor.SYSTEM
    (event,) = world.record_events
    assert event.source_capability == MEETINGS_PROVIDER_SYNC_SOURCE
    assert event.actor_class is RecordEventActorClass.SYSTEM
    (binding,) = world.meeting_provider_bindings.values()
    assert binding.meeting_id == outcome.meeting_id
    assert binding.last_seen_source_sha256 == SHA_A and binding.version == 1


def test_a_new_series_then_a_new_occurrence_joins_it(world: World) -> None:
    first = _apply(world, _occurrence())
    second = _apply(world, _occurrence("2026-12-09T14:00:00Z"))
    assert (first.kind, second.kind) == (SyncOutcomeKind.CREATED, SyncOutcomeKind.CREATED)
    one = world.meetings[(PRINCIPAL, first.meeting_id)]
    two = world.meetings[(PRINCIPAL, second.meeting_id)]
    assert one.meeting_series_id is not None
    assert one.meeting_series_id == two.meeting_series_id
    (series_binding,) = world.meeting_series_provider_bindings.values()
    assert series_binding.meeting_series_id == one.meeting_series_id
    assert len(world.meeting_series) == 1


def test_a_moved_occurrence_updates_its_meeting_by_original_start(world: World) -> None:
    created = _apply(world, _occurrence())
    moved = _apply(
        world,
        _occurrence(start_utc="2026-12-02T18:00:00Z", end_utc="2026-12-02T19:00:00Z"),
        sha=SHA_B,
    )
    assert moved.kind is SyncOutcomeKind.UPDATED and moved.meeting_id == created.meeting_id
    meeting = world.meetings[(PRINCIPAL, created.meeting_id)]
    assert meeting.start_at == datetime(2026, 12, 2, 18, tzinfo=UTC)
    assert meeting.version == 2
    assert len(world.meetings) == 1


def test_an_identical_replay_and_an_identical_republication_change_nothing(
    world: World,
) -> None:
    created = _apply(world, _event())
    events_before = len(world.record_events)
    assert _apply(world, _event()).kind is SyncOutcomeKind.REPLAYED
    again = _apply(world, _event(), sha=SHA_B)
    assert again.kind is SyncOutcomeKind.UNCHANGED
    meeting = world.meetings[(PRINCIPAL, created.meeting_id)]
    assert meeting.version == 1
    (binding,) = world.meeting_provider_bindings.values()
    assert binding.version == 1 and binding.last_seen_source_sha256 == SHA_B
    assert len(world.meeting_history) == 1
    assert len(world.record_events) == events_before


def test_an_older_publication_rewinds_nothing_even_after_a_no_change_record(
    world: World,
) -> None:
    created = _apply(world, _event())
    assert _apply(world, _event(), sha=SHA_C).kind is SyncOutcomeKind.UNCHANGED
    (binding,) = world.meeting_provider_bindings.values()
    assert binding.last_applied_generated_at_utc == STAMP_C
    history = len(world.meeting_history)
    stale = _apply(world, _event(title="Older", status="cancelled"), sha=SHA_B)
    assert stale.kind is SyncOutcomeKind.SKIPPED
    assert stale.diagnostic is ResolutionDiagnostic.STALE_RECORD_SKIPPED
    meeting = world.meetings[(PRINCIPAL, created.meeting_id)]
    assert (meeting.title, meeting.status, meeting.version) == (
        "Synthetic sync",
        MeetingStatus.SCHEDULED,
        1,
    )
    assert world.meeting_provider_bindings[(PRINCIPAL, binding.binding_id)] == binding
    assert len(world.meeting_history) == history


def test_an_equal_stamp_from_another_publication_is_skipped(world: World) -> None:
    created = _apply(world, _event())
    (binding,) = world.meeting_provider_bindings.values()
    conflict = _apply(world, _event(title="Same stamp"), sha=SHA_B, stamp=STAMP_A)
    assert conflict.kind is SyncOutcomeKind.SKIPPED
    assert conflict.diagnostic is ResolutionDiagnostic.ORDERING_CONFLICT_SKIPPED
    assert world.meetings[(PRINCIPAL, created.meeting_id)].title == "Synthetic sync"
    assert world.meeting_provider_bindings[(PRINCIPAL, binding.binding_id)] == binding


def test_a_cancel_keeps_the_meeting_and_a_cancelled_unknown_is_skipped(world: World) -> None:
    created = _apply(world, _event())
    cancelled = _apply(world, _event(status="cancelled"), sha=SHA_B)
    assert cancelled.kind is SyncOutcomeKind.UPDATED
    meeting = world.meetings[(PRINCIPAL, created.meeting_id)]
    assert meeting.status is MeetingStatus.CANCELLED and meeting.cancelled_at == NOW
    (binding,) = world.meeting_provider_bindings.values()
    assert binding.provider_state is ProviderBindingState.CANCELLED and binding.version == 2
    skipped = _apply(world, _event(ical_uid="uid-unknown", status="cancelled"))
    assert skipped.kind is SyncOutcomeKind.SKIPPED
    assert skipped.diagnostic is ResolutionDiagnostic.CANCELLED_UNKNOWN_SKIPPED
    assert len(world.meetings) == 1


def test_a_changed_provider_id_is_the_same_meeting(world: World) -> None:
    created = _apply(world, _event())
    renamed = _apply(world, _event(provider_event_id="evt-renamed"), sha=SHA_B)
    assert renamed.kind is SyncOutcomeKind.UPDATED and renamed.meeting_id == created.meeting_id
    assert world.meetings[(PRINCIPAL, created.meeting_id)].version == 1
    (binding,) = world.meeting_provider_bindings.values()
    assert binding.provider_event_id == "evt-renamed" and binding.version == 2


def test_the_other_kind_of_one_uid_is_skipped(world: World) -> None:
    _apply(world, _event(ical_uid=SERIES_UID))
    skipped = _apply(world, _occurrence())
    assert skipped.diagnostic is ResolutionDiagnostic.BINDING_KIND_CONFLICT
    assert len(world.meetings) == 1


def test_the_provider_never_touches_what_it_does_not_own(world: World) -> None:
    created = _apply(world, _event())
    with FakeUnitOfWork(world) as uow:
        APP.update_meeting(
            uow,
            PRINCIPAL,
            MeetingUpdateRequest(meeting_id=created.meeting_id, description="Principal's own"),
            1,
            "principal-edit-0001",
            NOW,
        )
    _apply(world, _event(title="Retitled by provider"), sha=SHA_B)
    meeting = world.meetings[(PRINCIPAL, created.meeting_id)]
    assert meeting.title == "Retitled by provider"
    assert meeting.description == "Principal's own"


def test_principals_are_isolated(world: World) -> None:
    mine = _apply(world, _event())
    theirs = _apply(world, _event(), principal=OTHER)
    assert theirs.kind is SyncOutcomeKind.CREATED
    assert theirs.meeting_id != mine.meeting_id


def test_d6_a_series_change_of_a_bound_meeting_is_refused(world: World) -> None:
    created = _apply(world, _occurrence())
    with FakeUnitOfWork(world) as uow:
        other = APP.create_meeting(
            uow,
            PRINCIPAL,
            MeetingCreateRequest(
                title="Unbound",
                start_at=NOW,
                timezone_name="UTC",
                series_title="Another series",
            ),
            "principal-create-0001",
            NOW,
        )
    for index, request in enumerate(
        (
            MeetingUpdateRequest(meeting_id=created.meeting_id, detach_series=True),
            MeetingUpdateRequest(
                meeting_id=created.meeting_id, meeting_series_id=other.meeting.meeting_series_id
            ),
        )
    ):
        with pytest.raises(MeetingInvalidRequestError) as refused, FakeUnitOfWork(world) as uow:
            APP.update_meeting(uow, PRINCIPAL, request, 1, f"principal-refused-{index}", NOW)
        assert refused.value.field is MeetingErrorField.MEETING_SERIES_CHANGE_REFUSED_PROVIDER_BOUND
    # An unbound Meeting still moves freely (operator decision 2026-10-09).
    with FakeUnitOfWork(world) as uow:
        moved = APP.update_meeting(
            uow,
            PRINCIPAL,
            MeetingUpdateRequest(meeting_id=other.meeting.meeting_id, detach_series=True),
            1,
            "principal-move-0002",
            NOW + timedelta(minutes=1),
        )
    assert moved.meeting.meeting_series_id is None


def test_the_default_actor_is_still_the_principal(world: World) -> None:
    with FakeUnitOfWork(world) as uow:
        written = APP.create_meeting(
            uow,
            PRINCIPAL,
            MeetingCreateRequest(title="Mine", start_at=NOW, timezone_name="UTC"),
            "principal-create-0002",
            NOW,
        )
    assert written.receipt.actor is MeetingActor.PRINCIPAL


def test_a_malformed_source_digest_is_refused(world: World) -> None:
    with pytest.raises(ValueError, match="source_sha256"):
        _apply(world, _event(), sha="A" * 64)
