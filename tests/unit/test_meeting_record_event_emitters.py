"""WP-RE-05: Meeting and MeetingSeries writes stage exactly the Record Events they should.

The FAST half (no marker). Driven through `MeetingApplication` over the
conftest `FakeUnitOfWork`, whose `FakeRecordEventStager` publishes to
`World.record_events` only when the block ends normally. The database half is
`tests/database/test_meeting_record_events.py`; T-13 is
`tests/concurrency/test_meeting_record_events.py`.

* **RE-AC-052 (MT2)** -- a create stages one Meeting `created` event at version
  1, naming the static scalar fields plus each optional part it holds, with the
  history receipt as `source_receipt_id`.
* **RE-AC-053 (MT1)** -- a create that makes a new series stages the series
  `created` event first, then the Meeting `created` event caused by it; an
  occurrence of an existing series stages only the Meeting event.
* **RE-AC-054 (MT3)** -- a material update stages one `updated` event at
  `version + 1` whose `changed_fields` names exactly the changed scalars and
  children; a cancel is `updated`, never `state_changed`.
* **RE-AC-055** -- a no-op update, a no-op retitle and every replay stage
  nothing, and a stale version stages nothing.
* **RE-AC-056 (MT4)** -- a material retitle stages one series `updated` event
  over `{title}` at the new series version.

Every identity, title and address here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.application.meetings import MeetingApplication, MeetingWriteResult
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.documents.managed import ManagedDocumentVersion
from my_pa.domain.meeting.model import (
    MeetingClearField,
    MeetingCreateRequest,
    MeetingNotesMode,
    MeetingSeriesUpdateRequest,
    MeetingStaleVersionError,
    MeetingStatus,
    MeetingUpdateRequest,
    normalize_attendee,
)
from my_pa.domain.record_events import (
    RecordEventActorClass,
    RecordEventDraft,
    RecordEventFamily,
    RecordEventKind,
)
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import FakeUnitOfWork, World

PRINCIPAL: Final = "prn_meetemit00000001"
WHEN: Final = datetime(2026, 9, 29, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)
CORRELATION: Final = "corr_meetemit0000001"
APP: Final = MeetingApplication()

ADA: Final = normalize_attendee(display_name="Ada", email="ada@example.com")
BEA: Final = normalize_attendee(display_name="Bea", email="bea@example.com")


@pytest.fixture
def world() -> World:
    return World()


def _document(world: World) -> str:
    document_id = issue_identifier(IdKind.MANAGED_DOCUMENT)
    world.managed_versions.append(
        ManagedDocumentVersion(
            version_id=issue_identifier(IdKind.MANAGED_DOCUMENT_VERSION),
            document_id=document_id,
            version_number=1,
            supersedes_version_id=None,
            owner_principal_id=PRINCIPAL,
            title="Synthetic agenda",
            media_type="text/markdown",
            content_sha256="a" * 64,
            byte_size=16,
            idempotency_key=f"doc-{document_id}",
            correlation_id=CORRELATION,
            recorded_at=WHEN,
        )
    )
    return document_id


def _create(
    world: World, request: MeetingCreateRequest, key: str = "create-0001"
) -> MeetingWriteResult:
    with FakeUnitOfWork(world) as uow:
        return APP.create_meeting(
            uow,
            PRINCIPAL,
            request,
            key,
            WHEN,
            source_capability="meetings.create",
            correlation_id=CORRELATION,
        )


def _update(
    world: World, request: MeetingUpdateRequest, version: int, key: str
) -> MeetingWriteResult:
    with FakeUnitOfWork(world) as uow:
        return APP.update_meeting(
            uow,
            PRINCIPAL,
            request,
            version,
            key,
            LATER,
            source_capability="meetings.update",
            correlation_id=CORRELATION,
        )


def _minimal(**extra: object) -> MeetingCreateRequest:
    return MeetingCreateRequest(
        title="Synthetic sync",
        start_at=WHEN,
        timezone_name="UTC",
        **extra,  # type: ignore[arg-type]
    )


def _seeded(world: World, **extra: object) -> MeetingWriteResult:
    written = _create(world, _minimal(**extra), key="seed-0001")
    world.record_events.clear()
    return written


def _only(world: World) -> RecordEventDraft:
    assert len(world.record_events) == 1, world.record_events
    return world.record_events[0]


def _assert_common(event: RecordEventDraft, capability: str) -> None:
    assert event.principal_id == PRINCIPAL
    assert event.source_capability == capability
    assert event.actor_class is RecordEventActorClass.PRINCIPAL
    assert event.classification is Classification.PRIVATE_LOCAL
    assert event.correlation_id == CORRELATION
    assert event.authority is None


# ---- RE-AC-052 (MT2) ---------------------------------------------------------


def test_a_standalone_create_stages_one_meeting_created_event(world: World) -> None:
    written = _create(world, _minimal())
    event = _only(world)
    _assert_common(event, "meetings.create")
    assert event.record_family is RecordEventFamily.MEETING
    assert event.record_id == written.meeting.meeting_id
    assert event.event_kind is RecordEventKind.CREATED
    assert event.record_version == 1
    assert event.changed_fields == ("start_at", "status", "timezone_name", "title")
    assert event.source_receipt_id == written.receipt.history_id
    assert event.causation_event_id is None


def test_a_full_create_names_every_optional_part_it_holds(world: World) -> None:
    written = _create(
        world,
        _minimal(
            end_at=LATER,
            location_text="Room 4",
            virtual_meeting_url="https://example.com/sync",
            description="Agenda",
            attendees=(ADA,),
            attachment_document_ids=(_document(world),),
            notes_markdown="First notes",
        ),
    )
    event = _only(world)
    assert event.record_id == written.meeting.meeting_id
    assert event.changed_fields == (
        "attachments",
        "attendees",
        "description",
        "end_at",
        "location_text",
        "notes",
        "start_at",
        "status",
        "timezone_name",
        "title",
        "virtual_meeting_url",
    )


def test_the_default_capability_is_the_exact_public_name(world: World) -> None:
    with FakeUnitOfWork(world) as uow:
        APP.create_meeting(uow, PRINCIPAL, _minimal(), "default-0001", WHEN)
    event = _only(world)
    assert event.source_capability == "meetings.create"
    assert event.correlation_id is None


# ---- RE-AC-053 (MT1) ---------------------------------------------------------


def test_a_new_series_create_stages_the_series_first_then_the_caused_meeting(
    world: World,
) -> None:
    written = _create(world, _minimal(series_title="Synthetic series"))
    assert written.series_receipt is not None
    assert len(world.record_events) == 2, world.record_events
    series_event, meeting_event = world.record_events
    _assert_common(series_event, "meetings.create")
    _assert_common(meeting_event, "meetings.create")
    assert series_event.record_family is RecordEventFamily.MEETING_SERIES
    assert series_event.record_id == written.series_receipt.meeting_series_id
    assert series_event.event_kind is RecordEventKind.CREATED
    assert series_event.record_version == 1
    assert series_event.changed_fields == ("title",)
    assert series_event.source_receipt_id == written.series_receipt.series_history_id
    assert series_event.causation_event_id is None

    assert meeting_event.record_family is RecordEventFamily.MEETING
    assert meeting_event.record_id == written.meeting.meeting_id
    assert meeting_event.causation_event_id == series_event.event_id
    assert meeting_event.source_receipt_id == written.receipt.history_id
    assert meeting_event.changed_fields == (
        "meeting_series_id",
        "start_at",
        "status",
        "timezone_name",
        "title",
    )


def test_an_existing_series_occurrence_stages_only_the_uncaused_meeting_event(
    world: World,
) -> None:
    first = _seeded(world, series_title="Synthetic series")
    series_id = first.meeting.meeting_series_id
    assert series_id is not None
    written = _create(world, _minimal(meeting_series_id=series_id), key="occurrence-0001")
    event = _only(world)
    assert event.record_family is RecordEventFamily.MEETING
    assert event.record_id == written.meeting.meeting_id
    assert event.causation_event_id is None
    assert "meeting_series_id" in event.changed_fields


# ---- RE-AC-054 (MT3) ---------------------------------------------------------


def test_a_scalar_update_names_exactly_the_changed_scalars(world: World) -> None:
    seed = _seeded(world, location_text="Room 1", description="Old")
    meeting_id = seed.meeting.meeting_id
    written = _update(
        world,
        MeetingUpdateRequest(
            meeting_id=meeting_id,
            title="Synthetic sync",  # unchanged value: not named
            location_text="Room 2",
            clear_fields=(MeetingClearField.DESCRIPTION,),
        ),
        1,
        "update-0001",
    )
    event = _only(world)
    _assert_common(event, "meetings.update")
    assert event.record_family is RecordEventFamily.MEETING
    assert event.record_id == meeting_id
    assert event.event_kind is RecordEventKind.UPDATED
    assert event.record_version == 2 == written.meeting.version
    assert event.changed_fields == ("description", "location_text")
    assert event.source_receipt_id == written.receipt.history_id
    assert event.causation_event_id is None


def test_a_cancel_is_updated_and_names_status_and_cancelled_at(world: World) -> None:
    seed = _seeded(world)
    _update(
        world,
        MeetingUpdateRequest(meeting_id=seed.meeting.meeting_id, status=MeetingStatus.CANCELLED),
        1,
        "cancel-0001",
    )
    event = _only(world)
    assert event.event_kind is RecordEventKind.UPDATED
    assert event.changed_fields == ("cancelled_at", "status")


def test_an_attendee_replacement_names_only_attendees(world: World) -> None:
    seed = _seeded(world, attendees=(ADA,))
    _update(
        world,
        MeetingUpdateRequest(meeting_id=seed.meeting.meeting_id, attendees_replace=(ADA, BEA)),
        1,
        "attendees-0001",
    )
    assert _only(world).changed_fields == ("attendees",)


def test_an_attachment_delta_names_only_attachments(world: World) -> None:
    seed = _seeded(world)
    _update(
        world,
        MeetingUpdateRequest(
            meeting_id=seed.meeting.meeting_id, attachment_add_document_ids=(_document(world),)
        ),
        1,
        "attach-0001",
    )
    assert _only(world).changed_fields == ("attachments",)


def test_a_note_append_names_only_notes(world: World) -> None:
    seed = _seeded(world)
    _update(
        world,
        MeetingUpdateRequest(
            meeting_id=seed.meeting.meeting_id,
            notes_mode=MeetingNotesMode.APPEND,
            notes_markdown="More notes",
        ),
        1,
        "notes-0001",
    )
    assert _only(world).changed_fields == ("notes",)


def test_a_combined_update_names_scalars_and_children_together(world: World) -> None:
    seed = _seeded(world, attendees=(ADA,))
    _update(
        world,
        MeetingUpdateRequest(
            meeting_id=seed.meeting.meeting_id,
            title="Renamed sync",
            attendees_replace=(BEA,),
            notes_mode=MeetingNotesMode.REPLACE,
            notes_markdown="Replaced notes",
        ),
        1,
        "combined-0001",
    )
    assert _only(world).changed_fields == ("attendees", "notes", "title")


# ---- RE-AC-055 ---------------------------------------------------------------


def test_a_no_op_update_stages_nothing(world: World) -> None:
    seed = _seeded(world, attendees=(ADA,))
    written = _update(
        world,
        MeetingUpdateRequest(
            meeting_id=seed.meeting.meeting_id, title="Synthetic sync", attendees_replace=(ADA,)
        ),
        1,
        "noop-0001",
    )
    assert written.meeting.version == 1
    assert world.record_events == []


def test_replays_of_every_write_stage_nothing(world: World) -> None:
    request = _minimal(series_title="Synthetic series")
    first = _create(world, request, key="replay-create")
    series_id = first.meeting.meeting_series_id
    assert series_id is not None
    update = MeetingUpdateRequest(meeting_id=first.meeting.meeting_id, title="Renamed")
    _update(world, update, 1, "replay-update")
    with FakeUnitOfWork(world) as uow:
        APP.update_meeting_series(
            uow,
            PRINCIPAL,
            MeetingSeriesUpdateRequest(meeting_series_id=series_id, title="Renamed series"),
            1,
            "replay-series",
            LATER,
        )
    world.record_events.clear()

    replayed = _create(world, request, key="replay-create")
    assert replayed.replayed is True
    assert _update(world, update, 1, "replay-update").replayed is True
    with FakeUnitOfWork(world) as uow:
        series_replay = APP.update_meeting_series(
            uow,
            PRINCIPAL,
            MeetingSeriesUpdateRequest(meeting_series_id=series_id, title="Renamed series"),
            1,
            "replay-series",
            LATER,
        )
    assert series_replay.replayed is True
    assert world.record_events == []


def test_a_stale_version_stages_nothing(world: World) -> None:
    seed = _seeded(world)
    with pytest.raises(MeetingStaleVersionError):
        _update(
            world,
            MeetingUpdateRequest(meeting_id=seed.meeting.meeting_id, title="Renamed"),
            7,
            "stale-0001",
        )
    assert world.record_events == []


def test_a_no_op_retitle_stages_nothing(world: World) -> None:
    seed = _seeded(world, series_title="Synthetic series")
    series_id = seed.meeting.meeting_series_id
    assert series_id is not None
    with FakeUnitOfWork(world) as uow:
        written = APP.update_meeting_series(
            uow,
            PRINCIPAL,
            MeetingSeriesUpdateRequest(meeting_series_id=series_id, title="Synthetic series"),
            1,
            "series-noop-0001",
            LATER,
        )
    assert written.series.version == 1
    assert world.record_events == []


# ---- RE-AC-056 (MT4) ---------------------------------------------------------


def test_a_material_retitle_stages_one_series_updated_event(world: World) -> None:
    seed = _seeded(world, series_title="Synthetic series")
    series_id = seed.meeting.meeting_series_id
    assert series_id is not None
    with FakeUnitOfWork(world) as uow:
        written = APP.update_meeting_series(
            uow,
            PRINCIPAL,
            MeetingSeriesUpdateRequest(meeting_series_id=series_id, title="Renamed series"),
            1,
            "series-0001",
            LATER,
            source_capability="meetings.series.update",
            correlation_id=CORRELATION,
        )
    event = _only(world)
    _assert_common(event, "meetings.series.update")
    assert event.record_family is RecordEventFamily.MEETING_SERIES
    assert event.record_id == series_id
    assert event.event_kind is RecordEventKind.UPDATED
    assert event.record_version == 2 == written.series.version
    assert event.changed_fields == ("title",)
    assert event.source_receipt_id == written.receipt.series_history_id
    assert event.causation_event_id is None
