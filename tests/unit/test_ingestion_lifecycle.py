"""WP3a-I2: the consumer-neutral ingestion lifecycle (`application.ingestion`), FAST tier.

A toy consumer stands in for a real one, so what is proved here is the
lifecycle alone: SHA-256 idempotency, aliases, supersession, the path revert,
the two-poll stability rule, a changing file retried and a still one rejected,
oldest-window-first ordering, per-snapshot rollback, run outcomes and counts,
admission refusals, and a dry run that writes nothing. Everything is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.application.ingestion import (
    RUN_COUNT_KEYS,
    IngestionLifecycle,
    IngestRefusalCode,
    IngestRefusedError,
    StabilityMemory,
)
from my_pa.contracts.ports import (
    FileWorkspaceStore,
    IngestApplied,
    IngestConsumer,
    IngestConsumerHandler,
    IngestCoverageDeclaration,
    IngestPrepared,
    IngestRunOutcome,
    IngestRunSnapshotOutcome,
    IngestRunTrigger,
    IngestSnapshotRecord,
    IngestSnapshotStatus,
    UnitOfWork,
)
from tests.unit.communications_ingest_fakes import (
    FakeStore,
    IngestWorld,
    unit_of_work_factory,
)

P: Final = "prn_lifecycle0001"
DIRECTORY: Final = "Daily/comms"
PREFIX: Final = DIRECTORY + "/"
T0: Final = datetime(2026, 11, 22, 12, tzinfo=UTC)


def doc(day: int, *, tag: str = "") -> bytes:
    start = datetime(2026, 11, day, 5, tzinfo=UTC)
    end = start + timedelta(hours=24) - timedelta(seconds=1)
    return json.dumps({"start": start.isoformat(), "end": end.isoformat(), "tag": tag}).encode()


class ToyHandler(IngestConsumerHandler):
    """A consumer-neutral stand-in: `{"start", "end"}` JSON, else `malformed_json`."""

    def __init__(self) -> None:
        self.applied: list[datetime] = []
        self.fail_next = False
        self.max = 10_000

    @property
    def consumer(self) -> IngestConsumer:
        return IngestConsumer.PULSE_CSV_EXPORT

    @property
    def parser_version(self) -> str:
        return "toy_parser_v1"

    @property
    def max_bytes(self) -> int:
        return self.max

    def prepare(self, data: bytes) -> IngestPrepared:
        try:
            parsed = json.loads(data)
            start = datetime.fromisoformat(parsed["start"])
            end = datetime.fromisoformat(parsed["end"])
        except (ValueError, KeyError, TypeError):
            return IngestPrepared("malformed_json", None, None, {})
        return IngestPrepared(
            rejection_code=None,
            window_start=start,
            coverage=IngestCoverageDeclaration(start, end, "complete", ()),
            record_counts={"records_total": 1},
            payload=start,
        )

    def apply(
        self,
        unit: UnitOfWork,
        principal_id: str,
        snapshot: IngestSnapshotRecord,
        prepared: IngestPrepared,
    ) -> IngestApplied:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("injected handler failure")
        assert isinstance(prepared.payload, datetime)
        self.applied.append(prepared.payload)
        return IngestApplied({"records_total": 1, "records_accepted": 1})


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


class Scene:
    def __init__(self, *, page_size: int | None = None) -> None:
        self.world = IngestWorld()
        self.store = FakeStore(page_size=page_size)
        self.handler = ToyHandler()
        self.memory = StabilityMemory()
        self.clock = Clock()
        self.lifecycle = self.make()
        self.source_id = self.lifecycle.admit(
            P,
            consumer=IngestConsumer.PULSE_CSV_EXPORT,
            workspace_id="mcp",
            path_prefix=PREFIX,
            file_pattern="*-comms.json",
        ).ingest_source_id

    def make(self, stores: Callable[[str], FileWorkspaceStore] | None = None) -> IngestionLifecycle:
        return IngestionLifecycle(
            unit_of_work=unit_of_work_factory(self.world),
            stores=stores or self._stores,
            handlers=[self.handler],
            clock=self.clock,
            stability=self.memory,
        )

    def _stores(self, workspace_id: str) -> FileWorkspaceStore:
        if workspace_id != "mcp":
            raise LookupError(workspace_id)
        return self.store

    def put(self, name: str, data: bytes) -> str:
        path = f"{DIRECTORY}/{name}"
        self.store.put(path, data)
        return path

    def poll(self) -> dict[str, int]:
        return dict(self.lifecycle.poll(P, self.source_id).counts)

    def backfill(self, **kwargs: object) -> dict[str, int]:
        return dict(self.lifecycle.backfill(P, self.source_id, **kwargs).counts)  # type: ignore[arg-type]

    def snapshots(self) -> list[IngestSnapshotRecord]:
        return sorted(self.world.snapshots.values(), key=lambda s: s.first_seen_at)

    def current(self, path: str) -> str | None:
        rows = [
            p
            for p in self.world.paths.values()
            if p.relative_path == path and p.superseded_by_snapshot_id is None
        ]
        assert len(rows) <= 1
        return rows[0].snapshot_id if rows else None


def nonzero(counts: dict[str, int]) -> dict[str, int]:
    return {key: value for key, value in counts.items() if value}


# ---- admission --------------------------------------------------------------------


def test_admission_refuses_a_consumer_with_no_registered_handler() -> None:
    scene = Scene()
    with pytest.raises(IngestRefusedError) as refused:
        scene.lifecycle.admit(
            P,
            consumer=IngestConsumer.MEETING_SYNC_V1,
            workspace_id="mcp",
            path_prefix=PREFIX,
            file_pattern="*.json",
        )
    assert refused.value.code is IngestRefusalCode.CONSUMER_NOT_REGISTERED
    assert str(refused.value) == "consumer_not_registered"
    assert len(scene.world.sources) == 1


@pytest.mark.parametrize(
    ("workspace_id", "path_prefix", "file_pattern"),
    [
        ("MCP", PREFIX, "*.json"),
        ("mcp", "/abs/", "*.json"),
        ("mcp", "a/../b/", "*.json"),
        ("mcp", "a//b/", "*.json"),
        ("mcp", PREFIX, "sub/*.json"),
        ("mcp", PREFIX, ""),
    ],
)
def test_admission_refuses_an_invalid_location(
    workspace_id: str, path_prefix: str, file_pattern: str
) -> None:
    scene = Scene()
    with pytest.raises(IngestRefusedError) as refused:
        scene.lifecycle.admit(
            P,
            consumer=IngestConsumer.PULSE_CSV_EXPORT,
            workspace_id=workspace_id,
            path_prefix=path_prefix,
            file_pattern=file_pattern,
        )
    assert refused.value.code is IngestRefusalCode.INVALID_LOCATION


def test_admission_refuses_a_second_source_at_the_same_location() -> None:
    scene = Scene()
    with pytest.raises(IngestRefusedError) as refused:
        scene.lifecycle.admit(
            P,
            consumer=IngestConsumer.PULSE_CSV_EXPORT,
            workspace_id="mcp",
            path_prefix=PREFIX,
            file_pattern="*-comms.json",
        )
    assert refused.value.code is IngestRefusalCode.SOURCE_ALREADY_ADMITTED


def test_disable_and_enable_govern_the_scheduled_poll_only() -> None:
    scene = Scene()
    scene.put("20261117-comms.json", doc(17))
    scene.lifecycle.set_enabled(P, scene.source_id, False)
    with pytest.raises(IngestRefusedError) as refused:
        scene.poll()
    assert refused.value.code is IngestRefusalCode.SOURCE_DISABLED
    assert scene.lifecycle.poll_enabled(P) == ()
    # A backfill is an explicit operator action and runs on a disabled source.
    assert scene.backfill()["snapshots_ingested"] == 1
    scene.lifecycle.set_enabled(P, scene.source_id, True)
    assert len(scene.lifecycle.poll_enabled(P)) == 1
    with pytest.raises(IngestRefusedError) as missing:
        scene.lifecycle.set_enabled(P, "isrc_absent00000001", True)
    assert missing.value.code is IngestRefusalCode.SOURCE_NOT_FOUND


def test_an_unknown_workspace_is_refused_before_a_run_is_written() -> None:
    scene = Scene()
    lifecycle = scene.make(stores=lambda workspace_id: (_ for _ in ()).throw(LookupError()))
    runs = len(scene.world.runs)
    with pytest.raises(IngestRefusedError) as refused:
        lifecycle.backfill(P, scene.source_id)
    assert refused.value.code is IngestRefusalCode.WORKSPACE_UNAVAILABLE
    assert len(scene.world.runs) == runs


def test_a_backfill_path_outside_the_source_is_refused() -> None:
    scene = Scene()
    for path in ("Daily/other/20261117-comms.json", f"{PREFIX}sub/x-comms.json", f"{PREFIX}a.txt"):
        with pytest.raises(IngestRefusedError) as refused:
            scene.backfill(paths=[path])
        assert refused.value.code is IngestRefusalCode.PATH_OUTSIDE_SOURCE


# ---- discovery --------------------------------------------------------------------


def test_discovery_matches_the_pattern_over_every_page_without_recursion() -> None:
    scene = Scene(page_size=2)
    for day in (17, 18, 19):
        scene.put(f"202611{day}-comms.json", doc(day))
    scene.put("notes.txt", b"not a candidate")
    scene.store.put(f"{DIRECTORY}/nested/20261120-comms.json", doc(20))
    counts = scene.backfill()
    assert counts["snapshots_seen"] == 3
    assert counts["snapshots_ingested"] == 3
    assert scene.store.calls.count("list_directory") == 3  # two pages of two, one of one
    assert set(scene.store.calls) <= {"list_directory", "stat", "open_download"}


def test_a_backfill_name_pattern_narrows_the_listed_candidates() -> None:
    """Contract section 10 "path glob": both the source pattern and the narrowing match."""
    scene = Scene()
    for day in (17, 18, 19):
        scene.put(f"202611{day}-comms.json", doc(day))
    scene.put("20261118-notes.json", doc(18))  # matches the narrowing, not the source pattern
    counts = scene.backfill(name_pattern="20261118-*")
    assert (counts["snapshots_seen"], counts["snapshots_ingested"]) == (1, 1)
    assert scene.handler.applied == [datetime(2026, 11, 18, 5, tzinfo=UTC)]
    rest = scene.backfill()
    # The narrowed file is the one this process already finished: unchanged, not re-read.
    assert (rest["skipped_unchanged"], rest["snapshots_ingested"]) == (1, 2)


@pytest.mark.parametrize("pattern", ["", "a/b", "x" * 1_000])
def test_a_backfill_name_pattern_that_is_not_one_name_is_refused(pattern: str) -> None:
    scene = Scene()
    runs = len(scene.world.runs)
    with pytest.raises(IngestRefusedError) as refused:
        scene.backfill(name_pattern=pattern)
    assert refused.value.code is IngestRefusalCode.INVALID_LOCATION
    assert len(scene.world.runs) == runs


def test_a_backfill_takes_paths_or_a_name_pattern_never_both() -> None:
    scene = Scene()
    path = scene.put("20261117-comms.json", doc(17))
    runs = len(scene.world.runs)
    with pytest.raises(ValueError, match="exclusive"):
        scene.backfill(paths=[path], name_pattern="*")
    assert len(scene.world.runs) == runs
    assert scene.handler.applied == []


# ---- idempotency, aliases, supersession, revert ----------------------------------


def test_the_same_bytes_twice_are_ingested_once_and_linked_already_known() -> None:
    scene = Scene()
    scene.put("20261117-comms.json", doc(17))
    first = scene.lifecycle.backfill(P, scene.source_id)
    assert nonzero(dict(first.counts)) == {
        "snapshots_seen": 1,
        "snapshots_new": 1,
        "snapshots_ingested": 1,
        "records_total": 1,
        "records_accepted": 1,
    }
    second_lifecycle = scene.make()
    scene.memory.finished.clear()  # a restarted process re-reads
    second = second_lifecycle.backfill(P, scene.source_id)
    assert nonzero(dict(second.counts)) == {"snapshots_seen": 1, "snapshots_already_known": 1}
    assert len(scene.world.snapshots) == 1
    assert scene.handler.applied == [datetime(2026, 11, 17, 5, tzinfo=UTC)]
    links = sorted(scene.world.run_snapshots.values(), key=lambda link: link.recorded_at)
    assert [link.outcome for link in links] == [
        IngestRunSnapshotOutcome.INGESTED,
        IngestRunSnapshotOutcome.ALREADY_KNOWN,
    ]


def test_an_unchanged_path_is_not_re_read_within_one_process() -> None:
    scene = Scene()
    scene.put("20261117-comms.json", doc(17))
    scene.backfill()
    reads = scene.store.calls.count("open_download")
    counts = scene.backfill()
    assert nonzero(counts) == {
        "snapshots_seen": 1,
        "snapshots_skipped": 1,
        "skipped_unchanged": 1,
    }
    assert scene.store.calls.count("open_download") == reads


def test_the_same_bytes_at_another_path_are_an_alias() -> None:
    scene = Scene()
    a = scene.put("20261117-comms.json", doc(17))
    scene.backfill()
    b = scene.put("copy-20261117-comms.json", doc(17))
    counts = scene.backfill()
    assert counts["snapshots_already_known"] == 1
    assert counts["snapshots_aliased"] == 1
    (snapshot,) = scene.snapshots()
    assert scene.current(a) == scene.current(b) == snapshot.snapshot_id
    assert scene.handler.applied == [datetime(2026, 11, 17, 5, tzinfo=UTC)]


def test_two_paths_with_the_same_new_bytes_in_one_run_make_one_snapshot() -> None:
    scene = Scene()
    a = scene.put("a-comms.json", doc(17))
    b = scene.put("b-comms.json", doc(17))
    counts = scene.backfill()
    assert (counts["snapshots_new"], counts["snapshots_ingested"]) == (1, 1)
    assert counts["snapshots_aliased"] == 1
    (snapshot,) = scene.snapshots()
    assert scene.current(a) == scene.current(b) == snapshot.snapshot_id
    assert len(scene.world.run_snapshots) == 1


def test_new_bytes_at_a_path_supersede_its_previous_snapshot() -> None:
    scene = Scene()
    path = scene.put("20261117-comms.json", doc(17))
    scene.backfill()
    scene.put("20261117-comms.json", doc(17, tag="republished"))
    counts = scene.backfill()
    assert (counts["snapshots_new"], counts["snapshots_superseded"]) == (1, 1)
    old, new = scene.snapshots()
    assert scene.current(path) == new.snapshot_id
    old_row = scene.world.paths[(P, old.snapshot_id, path)]
    assert old_row.superseded_by_snapshot_id == new.snapshot_id
    assert old.status is IngestSnapshotStatus.INGESTED  # superseded is per path, not a status


def test_a_path_reverting_to_earlier_bytes_leaves_the_newer_snapshot_current() -> None:
    scene = Scene()
    path = scene.put("20261117-comms.json", doc(17))
    scene.backfill()
    scene.put("20261117-comms.json", doc(17, tag="v2"))
    scene.backfill()
    old, new = scene.snapshots()
    scene.put("20261117-comms.json", doc(17))  # the original bytes again
    report = scene.lifecycle.backfill(P, scene.source_id)
    assert nonzero(dict(report.counts)) == {
        "snapshots_seen": 1,
        "snapshots_already_known": 1,
        "snapshots_path_reverted": 1,
    }
    assert report.outcome is IngestRunOutcome.COMPLETED
    assert scene.current(path) == new.snapshot_id
    assert len(scene.world.snapshots) == 2
    assert (P, report.run_id, old.snapshot_id) in scene.world.run_snapshots


# ---- stability ----------------------------------------------------------------------


def test_a_scheduled_poll_reads_a_file_only_after_two_polls_see_it_unchanged() -> None:
    scene = Scene()
    scene.put("20261117-comms.json", doc(17))
    assert nonzero(scene.poll()) == {
        "snapshots_seen": 1,
        "snapshots_skipped": 1,
        "skipped_unstable": 1,
    }
    assert "open_download" not in scene.store.calls
    scene.put("20261117-comms.json", doc(17, tag="still writing"))
    assert scene.poll()["skipped_unstable"] == 1
    assert scene.poll()["snapshots_ingested"] == 1
    assert scene.poll()["skipped_unchanged"] == 1
    assert len(scene.world.snapshots) == 1


def test_an_operator_run_and_a_backfill_read_on_first_sight() -> None:
    scene = Scene()
    scene.put("20261117-comms.json", doc(17))
    report = scene.lifecycle.run_once(P, scene.source_id)
    assert report.trigger is IngestRunTrigger.OPERATOR
    assert report.counts["snapshots_ingested"] == 1


def test_a_file_failing_json_while_still_changing_is_retried_not_rejected() -> None:
    scene = Scene()
    path = scene.put("20261117-comms.json", doc(17)[:10])  # half written
    scene.poll()
    full = doc(17)
    scene.store.during_read[path] = lambda: scene.store.put(path, full)
    counts = scene.poll()
    assert counts["skipped_changing"] == 1
    assert counts["snapshots_rejected"] == 0
    assert scene.world.snapshots == {}
    scene.poll()  # first sight of the completed file
    assert scene.poll()["snapshots_ingested"] == 1


def test_a_refused_file_that_moved_after_its_read_is_retried() -> None:
    scene = Scene()
    path = scene.put("20261117-comms.json", b"{not json")
    scene.poll()

    class Moving(ToyHandler):
        def prepare(self, data: bytes) -> IngestPrepared:
            scene.store.put(path, doc(17))  # the writer finishes after the read
            return super().prepare(data)

    scene.handler.__class__ = Moving
    counts = scene.poll()
    assert (counts["skipped_changing"], counts["snapshots_rejected"]) == (1, 0)
    assert counts["snapshots_new"] == 0
    assert scene.world.snapshots == {}


def test_a_stable_file_failing_json_is_rejected_and_writes_nothing_else() -> None:
    scene = Scene()
    path = scene.put("20261117-comms.json", b"{not json")
    scene.poll()
    report = scene.lifecycle.poll(P, scene.source_id)
    assert report.counts["snapshots_rejected"] == 1
    (snapshot,) = scene.snapshots()
    assert (snapshot.status, snapshot.rejection_code) == (
        IngestSnapshotStatus.REJECTED,
        "malformed_json",
    )
    assert snapshot.parser_version == "toy_parser_v1"
    assert scene.current(path) == snapshot.snapshot_id
    assert scene.world.coverage == {}
    assert scene.handler.applied == []
    (link,) = scene.world.run_snapshots.values()
    assert link.outcome is IngestRunSnapshotOutcome.REJECTED
    assert report.outcome is IngestRunOutcome.COMPLETED


def test_a_file_too_large_is_refused_before_any_byte_is_read() -> None:
    scene = Scene()
    scene.handler.max = 10
    scene.put("20261117-comms.json", doc(17))
    counts = scene.backfill()
    assert counts["skipped_too_large"] == 1
    assert "open_download" not in scene.store.calls
    assert scene.world.snapshots == {}


def test_a_file_changing_during_a_backfill_read_is_skipped_not_rejected() -> None:
    scene = Scene()
    path = scene.put("20261117-comms.json", doc(17))
    scene.store.during_read[path] = lambda: scene.store.put(path, doc(17, tag="moved"))
    counts = scene.backfill(paths=[path])
    assert (counts["skipped_changing"], counts["snapshots_new"]) == (1, 0)
    assert scene.world.snapshots == {}
    assert scene.backfill(paths=[path])["snapshots_ingested"] == 1


def test_a_missing_explicit_path_is_counted() -> None:
    scene = Scene()
    counts = scene.backfill(paths=[f"{DIRECTORY}/20261101-comms.json"])
    assert (counts["snapshots_seen"], counts["skipped_missing"]) == (1, 1)


# ---- ordering, rollback, outcomes ----------------------------------------------------


def test_snapshots_are_applied_oldest_window_first_whatever_the_listing_order() -> None:
    scene = Scene()
    scene.put("a-comms.json", doc(19))
    scene.put("b-comms.json", doc(17))
    scene.put("c-comms.json", doc(18))
    scene.backfill()
    assert [moment.day for moment in scene.handler.applied] == [17, 18, 19]


def test_equal_windows_order_by_file_digest() -> None:
    scene = Scene()
    first, second = doc(17, tag="x"), doc(17, tag="y")
    scene.put("a-comms.json", first)
    scene.put("b-comms.json", second)
    scene.backfill()
    ordered = sorted(scene.world.snapshots.values(), key=lambda s: s.first_seen_at)
    assert [s.file_sha256 for s in ordered] == sorted(s.file_sha256 for s in ordered)


def test_a_handler_failure_rolls_back_that_snapshot_only() -> None:
    scene = Scene()
    scene.put("a-comms.json", doc(17))
    scene.put("b-comms.json", doc(18))
    scene.handler.fail_next = True  # the oldest (17) fails
    report = scene.lifecycle.backfill(P, scene.source_id)
    assert report.outcome is IngestRunOutcome.PARTIAL
    assert (report.counts["snapshots_failed"], report.counts["snapshots_ingested"]) == (1, 1)
    assert report.counts["records_total"] == 1  # the rolled-back snapshot's counts are undone
    assert len(scene.world.snapshots) == 1
    assert len(scene.world.coverage) == 1
    assert len(scene.world.paths) == 1
    # The rerun resumes: the failed file is new, the ingested one already known.
    rerun = scene.lifecycle.backfill(P, scene.source_id)
    assert (rerun.counts["snapshots_ingested"], rerun.counts["skipped_unchanged"]) == (1, 1)
    assert [moment.day for moment in scene.handler.applied] == [18, 17]


def test_a_run_whose_only_snapshot_failed_is_failed() -> None:
    scene = Scene()
    scene.put("a-comms.json", doc(17))
    scene.handler.fail_next = True
    report = scene.lifecycle.backfill(P, scene.source_id)
    assert report.outcome is IngestRunOutcome.FAILED
    run = scene.world.runs[(P, report.run_id)]
    assert run.outcome is IngestRunOutcome.FAILED
    assert run.counts == dict(report.counts)


def test_a_listing_failure_fails_the_run() -> None:
    scene = Scene()
    report = scene.lifecycle.backfill(P, scene.source_id)  # the directory does not exist
    assert report.outcome is IngestRunOutcome.FAILED
    assert scene.world.runs[(P, report.run_id)].finished_at is not None


def test_run_counts_are_the_closed_keys_and_record_codes_only() -> None:
    scene = Scene()
    scene.put("a-comms.json", doc(17))
    report = scene.lifecycle.backfill(P, scene.source_id)
    assert set(RUN_COUNT_KEYS) <= set(report.counts)
    assert set(report.counts) - set(RUN_COUNT_KEYS) == {"records_total", "records_accepted"}
    assert all(isinstance(value, int) for value in report.counts.values())
    stored = scene.world.runs[(P, report.run_id)]
    assert stored.trigger is IngestRunTrigger.BACKFILL
    assert stored.counts == dict(report.counts)


# ---- dry run ----------------------------------------------------------------------------


def test_a_dry_run_reports_aggregates_and_writes_nothing() -> None:
    scene = Scene()
    scene.put("a-comms.json", doc(17))
    scene.put("b-comms.json", b"{not json")
    rows, writes = scene.world.row_count(), list(scene.world.writes)
    report = scene.lifecycle.backfill(P, scene.source_id, dry_run=True)
    assert report.dry_run and report.run_id is None
    assert nonzero(dict(report.counts)) == {
        "snapshots_seen": 2,
        "snapshots_new": 2,
        "snapshots_ingested": 1,
        "snapshots_rejected": 1,
        "records_total": 1,
    }
    assert scene.world.row_count() == rows
    assert scene.world.writes == writes
    assert scene.handler.applied == []
    assert scene.memory.finished == {}
    # A real run afterwards still sees both files as new.
    assert scene.backfill()["snapshots_new"] == 2


def test_a_dry_run_sees_known_digests() -> None:
    scene = Scene()
    scene.put("a-comms.json", doc(17))
    scene.backfill()
    writes = list(scene.world.writes)
    counts = scene.backfill(dry_run=True)
    assert counts["snapshots_already_known"] == 1
    assert scene.world.writes == writes


def test_a_failing_alias_write_rolls_back_alone_and_the_run_continues() -> None:
    scene = Scene()
    scene.put("a-comms.json", doc(17))
    scene.backfill()
    scene.put("copy-comms.json", doc(17))
    scene.put("z-comms.json", doc(18))
    scene.world.fail_on.add("insert_snapshot_path")
    report = scene.lifecycle.backfill(P, scene.source_id)
    assert report.outcome is IngestRunOutcome.PARTIAL
    assert report.counts["snapshots_failed"] == 1
    assert report.counts["snapshots_already_known"] == 0
    assert report.counts["snapshots_ingested"] == 1
    assert scene.current(f"{DIRECTORY}/copy-comms.json") is None


def test_a_rolled_back_snapshot_contributes_no_path_counts() -> None:
    scene = Scene()
    path = scene.put("20261117-comms.json", doc(17))
    scene.backfill()
    scene.put("20261117-comms.json", doc(17, tag="republished"))
    scene.handler.fail_next = True
    report = scene.lifecycle.backfill(P, scene.source_id)
    assert report.counts["snapshots_failed"] == 1
    assert report.counts["snapshots_superseded"] == 0
    (only,) = scene.snapshots()
    assert scene.current(path) == only.snapshot_id
