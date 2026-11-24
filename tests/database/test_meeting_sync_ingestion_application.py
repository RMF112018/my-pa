"""WP3b-S2: the ingestion lifecycle stages `meeting_sync_v1` snapshots, end to end on PostgreSQL.

The `database` tier, on a disposable head-migrated clone: the real lifecycle,
the real `MeetingSyncHandler` with parser v2 (both wired by
`bootstrap.communications_ingest`, next to the communications handler), the
real repositories through the general unit of work, and synthetic
publications served by the in-memory file store double. Proved here: a
`meeting_sync_v1` source is admitted (no longer `consumer_not_registered`); a
backfill stages one publication per snapshot (oldest `generated_at_utc`
first) and one event per accepted record, with totals that reconcile to the
publication's records and the run counts; a 1.1.0 coverage is stored on the
publication and as a `complete` lifecycle window with no lane objects; a rerun
in a new process writes nothing new; a malformed coverage rejects the snapshot
`invalid_coverage`; and no Meeting, series, binding or write request is
written (applying is S3's). Everything is synthetic.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text

from my_pa.application.ingestion import IngestionLifecycle, IngestRunReport, StabilityMemory
from my_pa.bootstrap.communications_ingest import communications_handler, meeting_sync_handler
from my_pa.contracts.ports import IngestConsumer, IngestRunOutcome, UnitOfWork
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.unit.communications_ingest_fakes import FakeStore

pytestmark = pytest.mark.database

P: Final = "prn_msyncingestdb0001"
DIRECTORY: Final = "My PA/Daily Intelligence/meetings"
T0: Final = datetime(2026, 11, 23, 12, tzinfo=UTC)
STAGING: Final = ("meeting_sync_publications", "meeting_sync_events")
LIFECYCLE: Final = ("ingest_snapshots", "ingest_runs", "ingest_coverage_windows")
#: Every Meeting-plane table a sync apply could write: S2 writes none of them.
MEETING_PLANE: Final = (
    "meetings",
    "meeting_series",
    "meeting_history",
    "meeting_provider_bindings",
    "meeting_series_provider_bindings",
    "meeting_write_requests",
    "meeting_provider_review_marks",
    "meeting_provider_reconciliation_passes",
    "meeting_provider_key_tombstones",
)
COVERAGE: Final = {
    "start_utc": "2026-10-22T00:00:00Z",
    "end_utc": "2027-01-20T00:00:00Z",
    "calendar_refs": ["cal-synthetic-b", "cal-synthetic-a"],
}


def _event(ordinal: int, **overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "calendar_ref": "cal-synthetic-a",
        "ical_uid": f"uid-{ordinal:04d}@example.invalid",
        "start_utc": "2026-12-01T15:00:00Z",
        "end_utc": "2026-12-01T16:00:00Z",
        "timezone_name": "America/New_York",
        "status": "confirmed",
        "all_day": False,
        "title": f"Synthetic meeting {ordinal}",
        "attendees": [{"email": "guest@example.invalid"}],
    }
    event.update(overrides)
    return event


def _publication(stamp: str, *events: object, coverage: object = None) -> bytes:
    document: dict[str, Any] = {
        "schema": "meeting_sync_v1",
        "schema_version": "1.1.0" if coverage is not None else "1.0.0",
        "generated_at_utc": stamp,
        "events": list(events),
    }
    if coverage is not None:
        document["coverage"] = coverage
    return json.dumps(document).encode()


class Scene:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.store = FakeStore()
        self.now = T0
        self.source_id = (
            self.lifecycle()
            .admit(
                P,
                consumer=IngestConsumer.MEETING_SYNC_V1,
                workspace_id="mcp",
                path_prefix=DIRECTORY + "/",
                file_pattern="*-meetings.json",
            )
            .ingest_source_id
        )

    def clock(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now

    def unit(self) -> UnitOfWork:
        return SqlAlchemyUnitOfWork(self.engine, audit=SqlAlchemyAuditSink(self.engine))

    def lifecycle(self) -> IngestionLifecycle:
        # A new lifecycle is a new process: empty stability memory.
        return IngestionLifecycle(
            unit_of_work=self.unit,
            stores=lambda _: self.store,
            handlers=[communications_handler(), meeting_sync_handler(clock=self.clock)],
            clock=self.clock,
            stability=StabilityMemory(),
        )

    def put(self, name: str, data: bytes) -> None:
        self.store.put(f"{DIRECTORY}/{name}", data)

    def backfill(self) -> IngestRunReport:
        return self.lifecycle().backfill(P, self.source_id)

    def count(self, table: str) -> int:
        with self.engine.connect() as connection:
            return int(
                connection.execute(
                    text(f"SELECT count(*) FROM knowledge.{table}")  # noqa: S608 - constant names
                ).scalar_one()
            )

    def rows(self, sql: str) -> list[Any]:
        with self.engine.connect() as connection:
            return list(connection.execute(text(sql)))


@pytest.fixture
def scene(migrated_engine: Engine) -> Scene:
    return Scene(migrated_engine)


def _put_three(scene: Scene) -> None:
    # Name order is the reverse of stamp order.
    scene.put("20261123-meetings.json", _publication("2026-11-23T06:00:00Z", _event(0), _event(1)))
    scene.put(
        "20261122-meetings.json",
        _publication(
            "2026-11-22T06:00:00Z",
            _event(0),
            _event(1, all_day=True),
            _event(2, timezone_name="Eastern Standard Time"),
            coverage=COVERAGE,
        ),
    )
    scene.put("20261121-meetings.json", _publication("2026-11-21T06:00:00Z", _event(0)))


def test_a_backfill_stages_every_snapshot_oldest_stamp_first(scene: Scene) -> None:
    _put_three(scene)
    report = scene.backfill()
    assert report.outcome is IngestRunOutcome.COMPLETED
    counts = {key: value for key, value in report.counts.items() if value}
    assert counts == {
        "records_quarantined": 2,
        "records_quarantined_all_day_unsupported": 1,
        "records_quarantined_timezone_not_iana": 1,
        "records_staged": 4,
        "records_total": 6,
        "snapshots_ingested": 3,
        "snapshots_new": 3,
        "snapshots_seen": 3,
    }
    publications = scene.rows(
        "SELECT p.generated_at_utc, p.record_count, p.accepted_count, p.quarantined_count,"
        " p.coverage_calendar_refs, p.applied_at, s.status, s.parser_version"
        " FROM knowledge.meeting_sync_publications p"
        " JOIN knowledge.ingest_snapshots s USING (principal_id, snapshot_id)"
        " ORDER BY p.staged_at"
    )
    assert [row.generated_at_utc for row in publications] == [
        datetime(2026, 11, 21, 6, tzinfo=UTC),
        datetime(2026, 11, 22, 6, tzinfo=UTC),
        datetime(2026, 11, 23, 6, tzinfo=UTC),
    ]
    assert [(r.record_count, r.accepted_count, r.quarantined_count) for r in publications] == [
        (1, 1, 0),
        (3, 1, 2),
        (2, 2, 0),
    ]
    assert [r.coverage_calendar_refs for r in publications] == [
        None,
        ["cal-synthetic-a", "cal-synthetic-b"],
        None,
    ]
    assert {(r.status, r.parser_version, r.applied_at) for r in publications} == {
        ("ingested", "meeting_sync_v1_parser_v2", None)
    }
    per_snapshot = scene.rows(
        "SELECT p.accepted_count, count(e.event_id) AS staged"
        " FROM knowledge.meeting_sync_publications p"
        " LEFT JOIN knowledge.meeting_sync_events e USING (principal_id, snapshot_id)"
        " GROUP BY p.snapshot_id, p.accepted_count"
    )
    assert all(row.accepted_count == row.staged for row in per_snapshot)
    assert scene.count("meeting_sync_events") == 4
    assert all(
        row.event_id.startswith("msevt_")
        for row in scene.rows("SELECT event_id FROM knowledge.meeting_sync_events")
    )
    (window,) = scene.rows(
        "SELECT start_utc, end_utc, coverage_state, lane_states"
        " FROM knowledge.ingest_coverage_windows"
    )
    assert (window.start_utc, window.end_utc, window.coverage_state, window.lane_states) == (
        datetime(2026, 10, 22, tzinfo=UTC),
        datetime(2027, 1, 20, tzinfo=UTC),
        "complete",
        [],
    )
    for table in MEETING_PLANE:
        assert scene.count(table) == 0, table


def test_a_rerun_in_a_new_process_writes_nothing_new(scene: Scene) -> None:
    _put_three(scene)
    scene.backfill()
    before = {table: scene.count(table) for table in (*STAGING, *LIFECYCLE)}
    report = scene.backfill()
    assert report.outcome is IngestRunOutcome.COMPLETED
    assert report.counts["snapshots_already_known"] == 3
    assert report.counts["snapshots_ingested"] == 0
    after = {table: scene.count(table) for table in (*STAGING, *LIFECYCLE)}
    assert after == {**before, "ingest_runs": before["ingest_runs"] + 1}
    for table in MEETING_PLANE:
        assert scene.count(table) == 0, table


def test_a_malformed_coverage_rejects_the_snapshot(scene: Scene) -> None:
    scene.put(
        "20261121-meetings.json",
        _publication(
            "2026-11-21T06:00:00Z",
            _event(0),
            coverage={**COVERAGE, "calendar_refs": ["cal-synthetic-a", "cal-synthetic-a"]},
        ),
    )
    report = scene.backfill()
    assert report.counts["snapshots_rejected"] == 1
    (snapshot,) = scene.rows("SELECT status, rejection_code FROM knowledge.ingest_snapshots")
    assert (snapshot.status, snapshot.rejection_code) == ("rejected", "invalid_coverage")
    for table in (*STAGING, "ingest_coverage_windows", *MEETING_PLANE):
        assert scene.count(table) == 0, table
