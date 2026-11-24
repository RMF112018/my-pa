"""WP3b-S2: `MeetingSyncHandler`, the staging consumer of the ingestion lifecycle (ruling D1).

FAST, over the lifecycle fakes plus an in-memory staging plane with real
rollback, and the real parser v2 (`bootstrap.communications_ingest`). Proved
here: `prepare` counts every record exactly once (staged or quarantined, with
per-reason counts) and declares a 1.1.0 coverage as a `complete` window with no
lane objects; a rejection is a closed code; a backfill stages one publication
and one event per accepted record, oldest `generated_at_utc` first whatever the
listing order; the staged rows carry no attendee or body field and no
quarantined record leaves a row (ruling D14); a rerun stages nothing new; rows
that do not reconcile roll the snapshot back; and the composed lifecycle admits
a `meeting_sync_v1` source. Everything is synthetic.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Final, NoReturn

import pytest

from my_pa.application.ingestion import IngestionLifecycle, StabilityMemory
from my_pa.application.meeting_sync_ingest import (
    MeetingSyncHandler,
    MeetingSyncTotalsError,
    ParsedMeetingSync,
)
from my_pa.bootstrap.communications_ingest import (
    communications_handler,
    meeting_sync_handler,
    parse_meeting_sync_for_ingestion,
)
from my_pa.contracts.ports import (
    IngestConsumer,
    IngestRunOutcome,
    IngestSnapshotRecord,
    MeetingProviderKeyTombstoneRecord,
    MeetingProviderReconciliationPassRecord,
    MeetingProviderReviewMarkRecord,
    MeetingSyncApplyOutcome,
    MeetingSyncEventRecord,
    MeetingSyncPublicationRecord,
    MeetingSyncRepository,
    UnitOfWork,
)
from my_pa.domain.common.identifiers import IdKind
from tests.unit.communications_ingest_fakes import FakeStore, IngestUnitOfWork, IngestWorld

P: Final = "prn_msyncingest0001"
DIRECTORY: Final = "My PA/Daily Intelligence/meetings"
FIXTURES: Final = Path(__file__).resolve().parents[1] / "fixtures" / "meeting_sync"
T0: Final = datetime(2026, 11, 23, 12, tzinfo=UTC)
ATTENDEE: Final = "guest-private@example.invalid"


def _event(ordinal: int, **overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "calendar_ref": "cal-synthetic",
        "ical_uid": f"uid-{ordinal:04d}@example.invalid",
        "start_utc": "2026-12-01T15:00:00Z",
        "end_utc": "2026-12-01T16:00:00Z",
        "timezone_name": "America/New_York",
        "status": "confirmed",
        "all_day": False,
        "title": f"Synthetic meeting {ordinal}",
        "attendees": [{"email": ATTENDEE}],
        "description": "never staged",
    }
    event.update(overrides)
    return event


def publication(stamp: str, *events: object, coverage: object = None) -> bytes:
    document: dict[str, Any] = {
        "schema": "meeting_sync_v1",
        "schema_version": "1.1.0" if coverage is not None else "1.0.0",
        "generated_at_utc": stamp,
        "events": list(events),
    }
    if coverage is not None:
        document["coverage"] = coverage
    return json.dumps(document).encode()


COVERAGE: Final = {
    "start_utc": "2026-10-22T00:00:00Z",
    "end_utc": "2027-01-20T00:00:00Z",
    "calendar_refs": ["cal-synthetic"],
}


# ---- an in-memory staging plane with the revision's guards that matter here ----------


@dataclasses.dataclass
class StagingWorld:
    publications: dict[tuple[str, str], MeetingSyncPublicationRecord] = dataclasses.field(
        default_factory=dict
    )
    events: dict[tuple[str, str], MeetingSyncEventRecord] = dataclasses.field(default_factory=dict)
    #: Insertion order of publications (snapshot ids): the staging order.
    order: list[str] = dataclasses.field(default_factory=list)
    #: When set, `insert_events` silently drops the last event (a short write).
    drop_one: bool = False


class FakeStaging(MeetingSyncRepository):
    """The staging half of `MeetingSyncRepository`; the rest is S3/S4's and fails."""

    def __init__(self, world: StagingWorld) -> None:
        self.w = world

    def insert_publication(
        self, principal_id: str, publication: MeetingSyncPublicationRecord
    ) -> None:
        key = (principal_id, publication.snapshot_id)
        assert key not in self.w.publications, "one publication per snapshot"
        assert (
            publication.accepted_count + publication.quarantined_count == publication.record_count
        ), "a_meeting_sync_publication_counts_reconcile"
        self.w.publications[key] = publication
        self.w.order.append(publication.snapshot_id)

    def get_publication(
        self, principal_id: str, snapshot_id: str
    ) -> MeetingSyncPublicationRecord | None:
        return self.w.publications.get((principal_id, snapshot_id))

    def insert_events(self, principal_id: str, events: Sequence[MeetingSyncEventRecord]) -> None:
        kept = list(events)[:-1] if self.w.drop_one and events else list(events)
        for event in kept:
            assert (principal_id, event.snapshot_id) in self.w.publications
            seen = {
                (e.snapshot_id, e.record_ordinal)
                for (p, _), e in self.w.events.items()
                if p == principal_id
            }
            assert (event.snapshot_id, event.record_ordinal) not in seen
            self.w.events[(principal_id, event.event_id)] = event

    def list_events(
        self, principal_id: str, snapshot_id: str
    ) -> tuple[MeetingSyncEventRecord, ...]:
        rows = (
            e
            for (p, _), e in self.w.events.items()
            if p == principal_id and e.snapshot_id == snapshot_id
        )
        return tuple(sorted(rows, key=lambda e: e.record_ordinal))

    # The rest of the port belongs to the applier and the capabilities (S3, S4):
    # the staging handler must never reach it.

    def list_publications(
        self, principal_id: str, ingest_source_id: str, *, unapplied_only: bool = False
    ) -> NoReturn:
        raise AssertionError("list_publications")

    def complete_publication(
        self,
        principal_id: str,
        snapshot_id: str,
        *,
        applied_at: datetime,
        apply_outcome: MeetingSyncApplyOutcome,
        apply_counts: Mapping[str, int],
    ) -> NoReturn:
        raise AssertionError("complete_publication")

    def get_event(self, principal_id: str, event_id: str) -> NoReturn:
        raise AssertionError("get_event")

    def insert_review_mark(
        self, principal_id: str, mark: MeetingProviderReviewMarkRecord
    ) -> NoReturn:
        raise AssertionError("insert_review_mark")

    def get_review_mark(self, principal_id: str, meeting_id: str) -> NoReturn:
        raise AssertionError("get_review_mark")

    def list_review_marks(self, principal_id: str) -> NoReturn:
        raise AssertionError("list_review_marks")

    def insert_reconciliation_pass(
        self, principal_id: str, completed: MeetingProviderReconciliationPassRecord
    ) -> NoReturn:
        raise AssertionError("insert_reconciliation_pass")

    def get_reconciliation_pass(self, principal_id: str) -> NoReturn:
        raise AssertionError("get_reconciliation_pass")

    def insert_key_tombstone(
        self, principal_id: str, tombstone: MeetingProviderKeyTombstoneRecord
    ) -> NoReturn:
        raise AssertionError("insert_key_tombstone")

    def list_key_tombstones(
        self,
        principal_id: str,
        calendar_ref: str,
        ical_uid: str,
        occurrence_original_start_utc: datetime | None,
    ) -> NoReturn:
        raise AssertionError("list_key_tombstones")


class StagingUnitOfWork(IngestUnitOfWork):
    def __init__(self, world: IngestWorld, staging: StagingWorld) -> None:
        super().__init__(world)
        self._staging = staging
        self._staging_saved: StagingWorld | None = None

    def __enter__(self) -> UnitOfWork:
        self._staging_saved = copy.deepcopy(self._staging)
        return super().__enter__()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        super().__exit__(exc_type, exc, traceback)
        if exc is not None and self._staging_saved is not None:
            self._staging.publications = self._staging_saved.publications
            self._staging.events = self._staging_saved.events
            self._staging.order = self._staging_saved.order
        self._staging_saved = None

    @property
    def meeting_sync(self) -> MeetingSyncRepository:
        return FakeStaging(self._staging)


class Scene:
    def __init__(self) -> None:
        self.world = IngestWorld()
        self.staging = StagingWorld()
        self.store = FakeStore()
        self.now = T0
        self.restart()
        self.source_id = self.lifecycle.admit(
            P,
            consumer=IngestConsumer.MEETING_SYNC_V1,
            workspace_id="mcp",
            path_prefix=DIRECTORY + "/",
            file_pattern="*-meetings.json",
        ).ingest_source_id

    def restart(self) -> None:
        """A new process: the composed lifecycle with empty stability memory."""
        self.lifecycle = IngestionLifecycle(
            unit_of_work=lambda: StagingUnitOfWork(self.world, self.staging),
            stores=lambda _: self.store,
            handlers=[communications_handler(), meeting_sync_handler(clock=self.clock)],
            clock=self.clock,
            stability=StabilityMemory(),
        )

    def clock(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now

    def put(self, name: str, data: bytes) -> None:
        self.store.put(f"{DIRECTORY}/{name}", data)

    def backfill(self) -> dict[str, int]:
        report = self.lifecycle.backfill(P, self.source_id)
        assert report.outcome is IngestRunOutcome.COMPLETED or report.counts["snapshots_failed"]
        return dict(report.counts)

    def stamps_in_staging_order(self) -> list[datetime]:
        return [self.staging.publications[(P, sid)].generated_at_utc for sid in self.staging.order]


def nonzero(counts: dict[str, int]) -> dict[str, int]:
    return {key: value for key, value in counts.items() if value}


# ---- prepare ----------------------------------------------------------------------


def test_prepare_counts_every_record_once_and_declares_the_coverage() -> None:
    handler = meeting_sync_handler()
    assert handler.consumer is IngestConsumer.MEETING_SYNC_V1
    assert handler.parser_version == "meeting_sync_v1_parser_v2"
    assert handler.max_bytes == 16 * 1024 * 1024
    prepared = handler.prepare((FIXTURES / "sync_publication_v1_1.json").read_bytes())
    assert prepared.rejection_code is None
    assert prepared.window_start == datetime(2026, 11, 22, 6, tzinfo=UTC)
    assert prepared.coverage is not None
    assert (prepared.coverage.start_utc, prepared.coverage.end_utc) == (
        datetime(2026, 10, 23, 6, tzinfo=UTC),
        datetime(2027, 1, 21, 6, tzinfo=UTC),
    )
    assert prepared.coverage.coverage_state == "complete"
    assert prepared.coverage.lane_states == ()
    assert dict(prepared.record_counts) == {
        "diagnostics_content_field_ignored": 1,
        "records_quarantined": 1,
        "records_quarantined_all_day_unsupported": 1,
        "records_quarantined_timezone_not_iana": 1,
        "records_staged": 4,
        "records_total": 5,
    }


def test_a_publication_without_coverage_declares_no_window() -> None:
    prepared = meeting_sync_handler().prepare((FIXTURES / "sync_publication.json").read_bytes())
    assert prepared.coverage is None
    assert prepared.window_start == datetime(2026, 11, 21, 6, tzinfo=UTC)


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"not json", "malformed_json"),
        (publication("2026-11-21T06:00:00Z", coverage={"start_utc": "x"}), "invalid_coverage"),
    ],
)
def test_a_rejection_is_a_closed_code(data: bytes, code: str) -> None:
    prepared = meeting_sync_handler().prepare(data)
    assert prepared.rejection_code == code
    assert (prepared.window_start, prepared.coverage, dict(prepared.record_counts)) == (
        None,
        None,
        {},
    )


def test_a_parse_is_accepted_or_rejected_not_both() -> None:
    with pytest.raises(ValueError, match="accepted or rejected"):
        ParsedMeetingSync(publication=None, rejection=None)


# ---- the lifecycle ----------------------------------------------------------------


def test_a_backfill_stages_oldest_stamp_first_and_reconciles() -> None:
    scene = Scene()
    # Listing (name) order is the reverse of stamp order.
    scene.put("a-meetings.json", publication("2026-11-23T06:00:00Z", _event(0), _event(1)))
    scene.put(
        "b-meetings.json",
        publication("2026-11-22T06:00:00Z", _event(0), _event(1, all_day=True), coverage=COVERAGE),
    )
    scene.put("c-meetings.json", publication("2026-11-21T06:00:00Z", _event(0), "not a record"))
    counts = scene.backfill()
    assert scene.stamps_in_staging_order() == [
        datetime(2026, 11, 21, 6, tzinfo=UTC),
        datetime(2026, 11, 22, 6, tzinfo=UTC),
        datetime(2026, 11, 23, 6, tzinfo=UTC),
    ]
    assert nonzero(counts) == {
        "diagnostics_content_field_ignored": 5,
        "records_quarantined": 2,
        "records_quarantined_all_day_unsupported": 1,
        "records_quarantined_record_not_an_object": 1,
        "records_staged": 4,
        "records_total": 6,
        "snapshots_ingested": 3,
        "snapshots_new": 3,
        "snapshots_seen": 3,
    }
    assert counts["records_total"] == counts["records_staged"] + counts["records_quarantined"]
    staged = list(scene.staging.publications.values())
    assert sum(p.accepted_count for p in staged) == len(scene.staging.events) == 4
    assert all(p.accepted_count + p.quarantined_count == p.record_count for p in staged)
    for snapshot_id in scene.staging.order:
        pub = scene.staging.publications[(P, snapshot_id)]
        rows = [e for e in scene.staging.events.values() if e.snapshot_id == snapshot_id]
        assert len(rows) == pub.accepted_count
        assert all(e.event_id.startswith(IdKind.MEETING_SYNC_EVENT.value + "_") for e in rows)
    # Coverage: only the 1.1.0 publication records a window, with no lane objects.
    (window,) = scene.world.coverage.values()
    assert (window.coverage_state, window.lane_states) == ("complete", ())
    covered = [p for p in staged if p.coverage_calendar_refs is not None]
    assert [p.coverage_calendar_refs for p in covered] == [("cal-synthetic",)]
    assert all(p.ingest_source_id == scene.source_id for p in staged)
    assert all(p.applied_at is None and p.apply_outcome is None for p in staged)


def test_staged_rows_carry_no_attendee_or_body_field() -> None:
    fields = {f.name for f in dataclasses.fields(MeetingSyncEventRecord)}
    assert not fields & {"attendees", "attendee", "body", "body_preview", "description", "notes"}
    scene = Scene()
    scene.put("a-meetings.json", publication("2026-11-21T06:00:00Z", _event(0)))
    scene.backfill()
    rendered = repr(scene.staging.events) + repr(scene.staging.publications)
    assert ATTENDEE not in rendered
    assert "never staged" not in rendered


def test_a_rerun_stages_nothing_new() -> None:
    scene = Scene()
    scene.put("a-meetings.json", publication("2026-11-21T06:00:00Z", _event(0), _event(1)))
    scene.backfill()
    before = (dict(scene.staging.publications), dict(scene.staging.events))
    counts = scene.backfill()
    assert nonzero(counts) == {
        "skipped_unchanged": 1,
        "snapshots_seen": 1,
        "snapshots_skipped": 1,
    }
    scene.restart()
    counts = scene.backfill()
    assert nonzero(counts) == {"snapshots_already_known": 1, "snapshots_seen": 1}
    assert (dict(scene.staging.publications), dict(scene.staging.events)) == before


def test_rows_that_do_not_reconcile_roll_the_snapshot_back() -> None:
    scene = Scene()
    scene.staging.drop_one = True
    scene.put("a-meetings.json", publication("2026-11-21T06:00:00Z", _event(0), _event(1)))
    counts = scene.backfill()
    assert nonzero(counts) == {"snapshots_failed": 1, "snapshots_new": 1, "snapshots_seen": 1}
    assert scene.staging.publications == {}
    assert scene.staging.events == {}
    assert scene.world.snapshots == {}
    scene.staging.drop_one = False
    assert scene.backfill()["snapshots_ingested"] == 1
    assert len(scene.staging.events) == 2


def test_apply_refuses_prepared_counts_that_do_not_match() -> None:
    handler = meeting_sync_handler()
    prepared = handler.prepare(publication("2026-11-21T06:00:00Z", _event(0)))
    forged = dataclasses.replace(prepared, record_counts={"records_total": 1})
    world, staging = IngestWorld(), StagingWorld()
    with pytest.raises(MeetingSyncTotalsError), StagingUnitOfWork(world, staging) as unit:
        handler.apply(unit, P, _snapshot(), forged)
    assert staging.publications == {}


def test_apply_refuses_a_payload_that_is_not_a_publication() -> None:
    handler = MeetingSyncHandler(
        parse=parse_meeting_sync_for_ingestion, parser_version="v", max_bytes=1
    )
    prepared = handler.prepare(publication("2026-11-21T06:00:00Z"))
    with (
        pytest.raises(TypeError),
        StagingUnitOfWork(IngestWorld(), StagingWorld()) as unit,
    ):
        handler.apply(unit, P, _snapshot(), dataclasses.replace(prepared, payload=None))


def _snapshot() -> IngestSnapshotRecord:
    return IngestSnapshotRecord(
        snapshot_id="isnp_msyncingest0001",
        ingest_source_id="isrc_msyncingest0001",
        file_sha256="0" * 64,
        byte_count=1,
        observed_version_token="fv1_00000001_1",  # noqa: S106 - a file version, not a secret
        first_seen_at=T0,
    )
