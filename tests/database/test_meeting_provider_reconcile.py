"""WP3b-S4: `meetings.provider.review` and `.reconcile` on PostgreSQL (rulings D2-D4, D6, D8).

The `database` tier, on a disposable current-head database, through the real
`ApplicationService` over the production general unit of work (with a fixed
clock, so the review scope is deterministic). Proved here:

* the review scope boundary -- the lookback edge included, one second older
  excluded, a cancelled Meeting excluded -- and keyset paging;
* the unbound-event list from staged publications, a bound key leaving it;
* reconcile item SAVEPOINTs: a refused item (stale version, after its
  reservation was written) rolls back alone -- no write request, binding or
  Record Event of its own -- while the items around it commit;
* marks never version a Meeting; the latch is not written while any in-scope
  Meeting is unreviewed, then written exactly once with its count and the
  call's correlation id;
* D6 adopt moving a Meeting into the bound provider series' MeetingSeries, and
  creating a series for a standalone Meeting;
* whole-batch replay answering every item from its stored state;
* end to end: stage, review, reconcile every Meeting, the latch, then
  `MeetingSyncApplier.apply_pending` applies what waited behind it.

Every identifier, title and key here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, Table, func, select

from my_pa.application.commands import (
    Command,
    CreateMeeting,
    ReconcileMeetingProviders,
    ReviewMeetingProviders,
    UpdateMeeting,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.meeting.model import MeetingStatus
from my_pa.domain.meeting_sync.model import COLLECTOR_LOOKBACK
from my_pa.domain.meeting_sync.reconcile import reconcile_item_key
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.tables import (
    audit_events,
    meeting_provider_bindings,
    meeting_provider_reconciliation_passes,
    meeting_provider_review_marks,
    meeting_series,
    meeting_write_requests,
    meetings,
    record_events,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.contract.test_meeting_mcp import _insert_partition
from tests.database.test_meeting_sync_apply_application import Scene as StagingScene
from tests.database.test_meeting_sync_apply_application import _event, _publication
from tests.database.test_task_record_events import LIMITS

pytestmark = pytest.mark.database

NOW: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)
SOON: Final = NOW + timedelta(days=7)
CAL: Final = "cal-synthetic"
SERIES_UID: Final = "uid-series@example.invalid"
ORIGINAL: Final = datetime(2026, 12, 2, 14, tzinfo=UTC)
REVIEW_COLUMNS: Final = (
    "meeting_id",
    "version",
    "title",
    "start_at",
    "end_at",
    "timezone_name",
    "meeting_series_id",
    "status",
)


@dataclass
class World:
    engine: Engine
    audit_engine: Engine
    service: ApplicationService
    principal_id: str
    url: str

    def invoke(self, command: Command) -> ResponseEnvelope:
        purpose = sorted(permitted_purposes(command.capability))[0]
        return self.service.invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=command.capability,
                purpose=purpose,
                principal_id=self.principal_id,
                requested_at=NOW,
            ),
            command,
            principal=Principal(
                principal_id=self.principal_id, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
        )

    def ok(self, command: Command) -> dict[str, Any]:
        response = self.invoke(command)
        assert response.error is None, response.error
        assert response.result is not None
        return response.result

    def meeting(
        self, title: str = "Synthetic", *, start: datetime = SOON, **extra: object
    ) -> dict[str, Any]:
        return self.ok(
            CreateMeeting(
                title=title,
                start_at=start,
                timezone_name="UTC",
                idempotency_key=issue_identifier(IdKind.CORRELATION),
                **extra,  # type: ignore[arg-type]
            )
        )["meeting"]

    def review(self, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
        return self.ok(ReviewMeetingProviders(**fields))

    def reconcile(self, *items: dict[str, Any], key: str = "batch-db-0001") -> dict[str, Any]:
        return self.ok(ReconcileMeetingProviders(items=tuple(items), idempotency_key=key))

    def count(self, table: Table, **where: object) -> int:
        statement = select(func.count()).select_from(table)
        for column, value in where.items():
            statement = statement.where(table.c[column] == value)
        with self.engine.connect() as connection:
            return int(connection.execute(statement).scalar_one())

    def rows(self, table: Table, **where: object) -> list[dict[str, Any]]:
        statement = select(table)
        for column, value in where.items():
            statement = statement.where(table.c[column] == value)
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings()]

    def version(self, meeting_id: str) -> int:
        (row,) = self.rows(meetings, meeting_id=meeting_id)
        return int(row["version"])

    def staging(self) -> StagingScene:
        return StagingScene(self.engine, self.principal_id)


@pytest.fixture
def world(disposable_database: str) -> Iterator[World]:
    engine = create_database_engine(disposable_database)
    audit_engine = create_database_engine(disposable_database)
    audit = SqlAlchemyAuditSink(audit_engine)

    def unit_of_work() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(engine, audit=audit)

    service = ApplicationService(unit_of_work=unit_of_work, limits=LIMITS, clock=lambda: NOW)
    try:
        with engine.begin() as connection:
            partition = _insert_partition(connection)
        yield World(
            engine, audit_engine, service, partition.principal.principal_id, disposable_database
        )
    finally:
        engine.dispose()
        audit_engine.dispose()


def bind(meeting: dict[str, Any], **fields: object) -> dict[str, Any]:
    item: dict[str, Any] = {
        "action": "bind",
        "meeting_id": meeting["meeting_id"],
        "expected_version": meeting["version"],
    }
    if "provider_event_ref" not in fields:
        item.update(calendar_ref=CAL, ical_uid=f"uid-{meeting['meeting_id']}")
    item.update(fields)
    return item


def mark(meeting: dict[str, Any]) -> dict[str, Any]:
    return {"action": "no_provider_event", "meeting_id": meeting["meeting_id"]}


# ---- review ----------------------------------------------------------------------


def test_the_review_scope_boundary_and_paging(world: World) -> None:
    edge = world.meeting("Edge", start=NOW - COLLECTOR_LOOKBACK)
    world.meeting("Old", start=NOW - COLLECTOR_LOOKBACK - timedelta(seconds=1))
    cancelled = world.meeting("Cancelled")
    world.ok(
        UpdateMeeting(
            meeting_id=cancelled["meeting_id"],
            expected_version=1,
            idempotency_key="cancel-db-0001",
            status=MeetingStatus.CANCELLED,
        )
    )
    later = [world.meeting(f"Later {n}", start=SOON + timedelta(hours=n)) for n in range(3)]
    first = world.review(page_size=2)
    listed = [m["meeting_id"] for m in first["unreviewed_meetings"]]
    assert listed == [edge["meeting_id"], later[0]["meeting_id"]]
    assert set(first["unreviewed_meetings"][0]) == set(REVIEW_COLUMNS)
    assert first["pass"] == {"state": "pending", "completed_at": None, "unreviewed_count": 4}
    second = world.review(page_size=2, after=first["next_after"])
    assert [m["meeting_id"] for m in second["unreviewed_meetings"]] == [
        later[1]["meeting_id"],
        later[2]["meeting_id"],
    ]
    last = world.review(page_size=2, after=second["next_after"])
    assert last["unreviewed_meetings"] == []
    assert last["next_after"] is None


def test_the_unbound_events_come_from_the_staged_publication(world: World) -> None:
    staging = world.staging()
    staging.stage(
        "20261123-meetings.json",
        _publication("2026-11-23T06:00:00Z", _event("uid-a"), _event("uid-b")),
    )
    events = world.review()["unbound_provider_events"]
    assert [e["ical_uid"] for e in events] == ["uid-a", "uid-b"]
    assert all(e["provider_event_ref"].startswith("msevt_") for e in events)
    assert not any(e["suppressed"] for e in events)
    meeting = world.meeting()
    answer = world.reconcile(bind(meeting, provider_event_ref=events[0]["provider_event_ref"]))
    assert answer["items"][0]["outcome"] == "bound"
    assert [e["ical_uid"] for e in world.review()["unbound_provider_events"]] == ["uid-b"]


# ---- reconcile -------------------------------------------------------------------


def test_a_refused_item_rolls_back_alone_under_its_savepoint(world: World) -> None:
    first, second, third = (world.meeting(t) for t in ("First", "Second", "Third"))
    answer = world.reconcile(bind(first), bind(second, expected_version=9), mark(third))
    assert [(i["index"], i["outcome"]) for i in answer["items"]] == [
        (0, "bound"),
        (1, "refused"),
        (2, "marked"),
    ]
    assert answer["items"][1]["refusal"] == {"code": "conflict", "detail": "stale_version"}
    refused_key = reconcile_item_key("batch-db-0001", 1)
    assert world.count(meeting_write_requests, idempotency_key=refused_key) == 0
    assert world.count(meeting_provider_bindings, meeting_id=second["meeting_id"]) == 0
    assert world.count(record_events, record_id=second["meeting_id"]) == 1  # its create only
    assert world.version(second["meeting_id"]) == 1
    # The neighbours committed.
    assert world.version(first["meeting_id"]) == 2
    assert world.count(meeting_provider_bindings, meeting_id=first["meeting_id"]) == 1
    assert (
        world.count(meeting_write_requests, idempotency_key=reconcile_item_key("batch-db-0001", 0))
        == 1
    )
    assert world.count(meeting_provider_review_marks, meeting_id=third["meeting_id"]) == 1
    (event,) = [
        row
        for row in world.rows(record_events, record_id=first["meeting_id"])
        if row["record_version"] == 2
    ]
    assert event["source_capability"] == "meetings.provider.reconcile"
    assert world.count(audit_events, capability="meetings.provider.reconcile") >= 1


def test_the_latch_waits_then_is_written_once(world: World) -> None:
    first, second = world.meeting("First"), world.meeting("Second")
    world.meeting("Old", start=NOW - COLLECTOR_LOOKBACK - timedelta(days=1))
    partial = world.reconcile(mark(first))
    assert partial["pass"]["state"] == "pending"
    assert partial["sync_enabled"] is False
    assert world.count(meeting_provider_reconciliation_passes) == 0
    assert world.version(first["meeting_id"]) == 1  # a mark never versions the Meeting
    done = world.reconcile(bind(second), key="batch-db-0002")
    assert done["pass"]["state"] == "complete"
    assert done["sync_enabled"] is True
    (latch,) = world.rows(meeting_provider_reconciliation_passes)
    assert latch["reviewed_meetings"] == 2
    assert latch["completed_at"] == NOW
    assert latch["reconcile_correlation_id"].startswith("corr_")
    # Written once: a later reconcile leaves the one row unchanged.
    world.meeting("New")
    after = world.reconcile(key="batch-db-0003")
    assert after["pass"] == {
        "state": "complete",
        "completed_at": done["pass"]["completed_at"],
        "unreviewed_count": 1,
    }
    assert world.rows(meeting_provider_reconciliation_passes) == [latch]


def test_a_whole_batch_replay_answers_from_the_stored_state(world: World) -> None:
    first, second = world.meeting("First"), world.meeting("Second")
    items = (bind(first), mark(second))
    original = world.reconcile(*items)
    before = {table.name: world.count(table) for table in (meetings, record_events)}
    replay = world.reconcile(*items)
    assert [i["outcome"] for i in replay["items"]] == ["replayed", "replayed"]
    assert replay["items"][0]["binding"] == original["items"][0]["binding"]
    assert replay["items"][0]["version"] == original["items"][0]["version"] == 2
    assert {table.name: world.count(table) for table in (meetings, record_events)} == before


def test_adopt_moves_into_the_provider_series_and_creates_a_series(world: World) -> None:
    anchor = world.meeting("Anchor", series_title="Provider weekly")
    occurrence = {
        "ical_uid": SERIES_UID,
        "series_ical_uid": SERIES_UID,
        "occurrence_original_start_utc": ORIGINAL,
    }
    world.reconcile(bind(anchor, **occurrence))
    stray = world.meeting("Stray", series_title="Hand-made")
    week = {**occurrence, "occurrence_original_start_utc": ORIGINAL + timedelta(days=7)}
    refused = world.reconcile(bind(stray, **week), key="batch-db-0002")
    assert refused["items"][0]["refusal"]["detail"] == "provider_series_binding_conflict"
    moved = world.reconcile(bind(stray, adopt_provider_series=True, **week), key="batch-db-0003")
    assert moved["items"][0]["outcome"] == "bound"
    (row,) = world.rows(meetings, meeting_id=stray["meeting_id"])
    assert row["meeting_series_id"] == anchor["meeting_series_id"]

    standalone = world.meeting("Standup")
    other = {
        "ical_uid": "uid-standup@example.invalid",
        "series_ical_uid": "uid-standup@example.invalid",
        "occurrence_original_start_utc": ORIGINAL,
    }
    series_before = world.count(meeting_series)
    created = world.reconcile(
        bind(standalone, adopt_provider_series=True, **other), key="batch-db-0004"
    )
    assert created["items"][0]["outcome"] == "bound"
    (row,) = world.rows(meetings, meeting_id=standalone["meeting_id"])
    assert row["meeting_series_id"] is not None
    assert world.count(meeting_series) == series_before + 1
    (series,) = world.rows(meeting_series, meeting_series_id=row["meeting_series_id"])
    assert series["title"] == "Standup"


# ---- end to end ---------------------------------------------------------------------


def test_stage_review_reconcile_latch_then_the_applier_applies(world: World) -> None:
    hand_made = world.meeting("Hand-made", start=datetime(2026, 12, 1, 15, tzinfo=UTC))
    staging = world.staging()
    staging.stage(
        "20261123-meetings.json",
        _publication("2026-11-23T06:00:00Z", _event("uid-hand"), _event("uid-new")),
    )
    assert staging.apply() == {"unapplied_awaiting_reconciliation": 1}
    review = world.review()
    refs = {e["ical_uid"]: e["provider_event_ref"] for e in review["unbound_provider_events"]}
    items = [
        bind(hand_made, provider_event_ref=refs["uid-hand"])
        if m["meeting_id"] == hand_made["meeting_id"]
        else {"action": "no_provider_event", "meeting_id": m["meeting_id"]}
        for m in review["unreviewed_meetings"]
    ]
    answer = world.reconcile(*items)
    assert answer["sync_enabled"] is True
    assert staging.apply() == {
        "events_created": 1,
        "events_updated": 1,
        "publications_applied": 1,
    }
    # The hand-made Meeting was updated through its binding, not duplicated.
    titles = sorted(
        row["title"] for row in world.rows(meetings) if row["principal_id"] == world.principal_id
    )
    assert titles.count("Synthetic") == 2  # the provider's title on both
    assert world.count(meeting_provider_bindings) == 2
