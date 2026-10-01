"""WP-RE-05: Meeting and MeetingSeries Record Events on a real database (RE-AC-052..056).

Marked `database` (auto `database_clone`) and routed to `database-current-head`.
Every write goes through `ApplicationService.invoke` on the production general
unit of work (U1), so what is checked is the committed feed row beside the
committed Meeting, series and receipt rows:

* **RE-AC-052** -- `meetings.create` commits one Meeting `created` event whose
  receipt is the committed `meeting_history` row and whose correlation is the
  request's.
* **RE-AC-053** -- a create that makes a new series commits the series event
  first and the Meeting event caused by it, in one allocator batch.
* **RE-AC-054** -- a material child change (attendees, attachments, a note) and
  a cancel each commit one Meeting `updated` event at the new version.
* **RE-AC-055** -- a no-op update, a no-op retitle, every replay and a stale
  version commit zero events and advance no sequence.
* **RE-AC-056** -- a material retitle commits one series `updated` event at the
  new series version, and under OD-7 (i) the SQL `meetings.read` and
  `meetings.list` answers carry that same `series_version` (D-21).

Every identity, title and address here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import ColumnElement, Engine, Table, select

from my_pa.application.commands import (
    Command,
    CreateMeeting,
    ListMeetings,
    ReadMeeting,
    UpdateMeeting,
    UpdateMeetingSeries,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.meeting.model import MeetingNotesMode, MeetingStatus
from my_pa.infrastructure.persistence.tables import (
    meeting_history,
    meeting_series,
    meeting_series_history,
)
from tests.contract.test_meeting_mcp import Partition, _insert_partition
from tests.database.test_task_record_events import Runtime, feed, next_sequence

pytestmark = pytest.mark.database

START: Final = datetime(2026, 10, 1, 13, tzinfo=UTC)
ADA: Final = {"display_name": "Ada", "email": "ada@example.com"}
BEA: Final = {"display_name": "Bea", "email": "bea@example.com"}


@dataclass
class Scene:
    runtime: Runtime
    mine: Partition

    @property
    def principal_id(self) -> str:
        return self.mine.principal.principal_id

    @property
    def engine(self) -> Engine:
        return self.runtime.work_engine

    def ok(self, command: Command) -> dict[str, Any]:
        return self.runtime.ok(command, principal_id=self.principal_id)

    def feed(self) -> list[dict[str, Any]]:
        return feed(self.engine, self.principal_id)

    def next_sequence(self) -> int | None:
        return next_sequence(self.engine, self.principal_id)


@pytest.fixture
def scene(disposable_database: str) -> Iterator[Scene]:
    runtime = Runtime(disposable_database)
    try:
        with runtime.work_engine.begin() as connection:
            mine = _insert_partition(connection)
        yield Scene(runtime=runtime, mine=mine)
    finally:
        runtime.close()


def _create(scene: Scene, key: str, **extra: object) -> dict[str, Any]:
    return scene.ok(
        CreateMeeting(
            title="Synthetic sync",
            start_at=START,
            timezone_name="UTC",
            idempotency_key=key,
            **extra,
        )
    )


def _row(engine: Engine, table: Table, column: ColumnElement[Any], value: str) -> dict[str, Any]:
    with engine.connect() as connection:
        return dict(connection.execute(select(table).where(column == value)).mappings().one())


# ---- RE-AC-052 ---------------------------------------------------------------


def test_create_commits_one_meeting_created_event(scene: Scene) -> None:
    created = _create(scene, "db-create-0001", location_text="Room 4", attendees=(ADA,))
    meeting = created["meeting"]
    events = scene.feed()
    assert len(events) == 1, events
    (event,) = events
    assert event["sequence_number"] == 1
    assert scene.next_sequence() == 2
    assert event["record_family"] == "meeting"
    assert event["record_id"] == meeting["meeting_id"]
    assert event["event_kind"] == "created"
    assert event["record_version"] == 1 == meeting["version"]
    assert event["changed_fields"] == [
        "attendees",
        "location_text",
        "start_at",
        "status",
        "timezone_name",
        "title",
    ]
    assert event["source_capability"] == "meetings.create"
    assert event["actor_class"] == "principal"
    assert event["classification"] == "private_local"
    assert event["correlation_id"] is not None
    assert event["correlation_id"].startswith("corr_")
    assert event["causation_event_id"] is None
    receipt = _row(
        scene.engine, meeting_history, meeting_history.c.history_id, event["source_receipt_id"]
    )
    assert receipt["meeting_id"] == meeting["meeting_id"]
    assert receipt["after_version"] == 1
    assert created["history"]["history_id"] == event["source_receipt_id"]


# ---- RE-AC-053 ---------------------------------------------------------------


def test_new_series_create_commits_series_then_caused_meeting(scene: Scene) -> None:
    created = _create(scene, "db-series-0001", series_title="Synthetic series")
    events = scene.feed()
    assert len(events) == 2, events
    series_event, meeting_event = events
    assert [series_event["sequence_number"], meeting_event["sequence_number"]] == [1, 2]
    assert series_event["record_family"] == "meeting_series"
    assert series_event["record_id"] == created["series"]["meeting_series_id"]
    assert series_event["event_kind"] == "created"
    assert series_event["record_version"] == 1
    assert series_event["changed_fields"] == ["title"]
    assert series_event["source_receipt_id"] == created["series_history"]["series_history_id"]
    assert series_event["causation_event_id"] is None
    series_receipt = _row(
        scene.engine,
        meeting_series_history,
        meeting_series_history.c.series_history_id,
        series_event["source_receipt_id"],
    )
    assert series_receipt["after_version"] == 1

    assert meeting_event["record_family"] == "meeting"
    assert meeting_event["record_id"] == created["meeting"]["meeting_id"]
    assert meeting_event["causation_event_id"] == series_event["event_id"]
    assert meeting_event["correlation_id"] == series_event["correlation_id"]
    assert meeting_event["recorded_at"] == series_event["recorded_at"]


# ---- RE-AC-054 ---------------------------------------------------------------


def test_material_child_changes_each_commit_one_updated_event(scene: Scene) -> None:
    created = _create(scene, "db-children-0001", attendees=(ADA,))
    meeting_id = created["meeting"]["meeting_id"]
    attendees = scene.ok(
        UpdateMeeting(
            meeting_id=meeting_id,
            expected_version=1,
            idempotency_key="db-children-attendees",
            attendees_replace=(ADA, BEA),
        )
    )
    attached = scene.ok(
        UpdateMeeting(
            meeting_id=meeting_id,
            expected_version=2,
            idempotency_key="db-children-attach",
            attachment_add_document_ids=(scene.mine.document_id,),
        )
    )
    noted = scene.ok(
        UpdateMeeting(
            meeting_id=meeting_id,
            expected_version=3,
            idempotency_key="db-children-notes",
            notes_mode=MeetingNotesMode.APPEND,
            notes_markdown="Synthetic notes",
        )
    )
    cancelled = scene.ok(
        UpdateMeeting(
            meeting_id=meeting_id,
            expected_version=4,
            idempotency_key="db-children-cancel",
            status=MeetingStatus.CANCELLED,
        )
    )
    events = scene.feed()
    assert len(events) == 5, events
    _, *updates = events
    assert [(u["event_kind"], u["record_version"], u["changed_fields"]) for u in updates] == [
        ("updated", 2, ["attendees"]),
        ("updated", 3, ["attachments"]),
        ("updated", 4, ["notes"]),
        ("updated", 5, ["cancelled_at", "status"]),
    ]
    receipts = [attendees, attached, noted, cancelled]
    for update, written in zip(updates, receipts, strict=True):
        assert update["record_id"] == meeting_id
        assert update["source_capability"] == "meetings.update"
        assert update["source_receipt_id"] == written["history"]["history_id"]
        assert update["causation_event_id"] is None
    assert cancelled["meeting"]["version"] == 5
    assert scene.next_sequence() == 6


# ---- RE-AC-055 ---------------------------------------------------------------


def test_no_op_replay_and_stale_commit_no_event_and_no_sequence(scene: Scene) -> None:
    created = _create(scene, "db-quiet-0001", series_title="Synthetic series", attendees=(ADA,))
    meeting_id = created["meeting"]["meeting_id"]
    series_id = created["series"]["meeting_series_id"]
    before = scene.feed()
    assert len(before) == 2
    assert scene.next_sequence() == 3

    no_op = scene.ok(
        UpdateMeeting(
            meeting_id=meeting_id,
            expected_version=1,
            idempotency_key="db-quiet-noop",
            title="Synthetic sync",
            attendees_replace=(ADA,),
        )
    )
    assert no_op["history"]["outcome"] == "no_op"
    series_no_op = scene.ok(
        UpdateMeetingSeries(
            meeting_series_id=series_id,
            expected_version=1,
            idempotency_key="db-quiet-series-noop",
            title="Synthetic series",
        )
    )
    assert series_no_op["history"]["outcome"] == "no_op"
    replay = _create(scene, "db-quiet-0001", series_title="Synthetic series", attendees=(ADA,))
    assert replay["replayed"] is True
    stale = scene.runtime.invoke(
        UpdateMeeting(
            meeting_id=meeting_id,
            expected_version=9,
            idempotency_key="db-quiet-stale",
            title="Renamed",
        ),
        principal_id=scene.principal_id,
    )
    assert stale.error is not None
    assert stale.error.code is ErrorCode.CONFLICT

    assert scene.feed() == before
    assert scene.next_sequence() == 3


def test_replays_of_updates_commit_no_event(scene: Scene) -> None:
    created = _create(scene, "db-replay-0001", series_title="Synthetic series")
    meeting_id = created["meeting"]["meeting_id"]
    series_id = created["series"]["meeting_series_id"]
    update = UpdateMeeting(
        meeting_id=meeting_id, expected_version=1, idempotency_key="db-replay-u", title="Renamed"
    )
    retitle = UpdateMeetingSeries(
        meeting_series_id=series_id,
        expected_version=1,
        idempotency_key="db-replay-s",
        title="Renamed series",
    )
    scene.ok(update)
    scene.ok(retitle)
    before = scene.feed()
    assert len(before) == 4
    assert scene.ok(update)["replayed"] is True
    assert scene.ok(retitle)["replayed"] is True
    assert scene.feed() == before
    assert scene.next_sequence() == 5


# ---- RE-AC-056 ---------------------------------------------------------------


def test_material_retitle_commits_one_series_updated_event(scene: Scene) -> None:
    created = _create(scene, "db-retitle-0001", series_title="Synthetic series")
    series_id = created["series"]["meeting_series_id"]
    retitled = scene.ok(
        UpdateMeetingSeries(
            meeting_series_id=series_id,
            expected_version=1,
            idempotency_key="db-retitle-s",
            title="Renamed series",
        )
    )
    events = scene.feed()
    assert len(events) == 3, events
    *_, event = events
    assert event["sequence_number"] == 3
    assert event["record_family"] == "meeting_series"
    assert event["record_id"] == series_id
    assert event["event_kind"] == "updated"
    assert event["record_version"] == 2 == retitled["series"]["version"]
    assert event["changed_fields"] == ["title"]
    assert event["source_capability"] == "meetings.series.update"
    assert event["source_receipt_id"] == retitled["history"]["series_history_id"]
    assert event["causation_event_id"] is None
    row = _row(scene.engine, meeting_series, meeting_series.c.meeting_series_id, series_id)
    assert row["version"] == event["record_version"]


def test_sql_reads_carry_the_series_version_the_feed_names(scene: Scene) -> None:
    """OD-7 (i), D-21: a consumer can compare a series event against a read."""
    standalone = _create(scene, "db-sv-standalone")
    created = _create(scene, "db-sv-series", series_title="Synthetic series")
    series_id = created["series"]["meeting_series_id"]
    meeting_id = created["meeting"]["meeting_id"]
    assert created["meeting"]["series_version"] == 1
    assert standalone["meeting"]["series_version"] is None
    scene.ok(
        UpdateMeetingSeries(
            meeting_series_id=series_id,
            expected_version=1,
            idempotency_key="db-sv-retitle",
            title="Renamed series",
        )
    )
    series_event = next(
        event
        for event in reversed(scene.feed())
        if event["record_family"] == "meeting_series" and event["record_id"] == series_id
    )
    read = scene.ok(ReadMeeting(meeting_id=meeting_id))["meeting"]
    assert read["series_version"] == series_event["record_version"] == 2
    assert read["version"] == 1
    entries = {
        entry["meeting_id"]: entry for entry in scene.ok(ListMeetings(page_size=10))["meetings"]
    }
    assert entries[meeting_id]["series_version"] == 2
    assert entries[meeting_id]["version"] == 1
    assert entries[standalone["meeting"]["meeting_id"]]["series_version"] is None
