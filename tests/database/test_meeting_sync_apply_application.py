"""WP3b-S3: the meeting sync applier end to end on PostgreSQL (rulings D1, D4, D5, D7, D8).

The `database` tier, on a disposable head-migrated clone. Proved here: admit,
backfill (staging), `apply_pending` without the latch (nothing applied, no
Meeting-plane row), the latch inserted through the repository, apply (Meetings
and bindings created, the snapshot foreign keys set), a rerun idempotent;
`not_seen` through the real window query, the Meeting untouched; the unbind
tombstone suppressing a re-create; the binding-writer advisory lock
serializing two connections whose row locks do not overlap, and concurrent
binding writers in opposite orders finishing without a deadlock; and the
cycles-plane step and the operator CLI `run-once` applying. Everything is
synthetic.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from apps import worker as worker_app
from apps.cli import communications_ingest as cli
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.application.ingestion import IngestionLifecycle, StabilityMemory
from my_pa.application.meeting_sync_apply import MeetingSyncApplier
from my_pa.application.meetings import MeetingApplication
from my_pa.bootstrap.communications_ingest import (
    communications_handler,
    ingest_unit_of_work,
    meeting_sync_handler,
)
from my_pa.bootstrap.gateway import local_principal
from my_pa.contracts.ports import (
    IngestConsumer,
    MeetingProviderReconciliationPassRecord,
    UnitOfWork,
)
from my_pa.domain.meeting.model import MeetingCreateRequest
from my_pa.domain.meeting_sync.binding import MeetingProviderBindRequest, ProviderBindAction
from my_pa.infrastructure.persistence.meetings import MEETING_PROVIDER_BINDING_LOCK_CLASS
from tests.unit.communications_ingest_fakes import FakeStore

pytestmark = pytest.mark.database

P: Final = "prn_msyncapplydb0001"
DIRECTORY: Final = "My PA/Daily Intelligence/meetings"
T0: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)
APP: Final = MeetingApplication()
COVERAGE: Final = {
    "start_utc": "2026-11-01T00:00:00Z",
    "end_utc": "2027-01-31T00:00:00Z",
    "calendar_refs": ["cal-synthetic"],
}
MEETING_PLANE: Final = (
    "meetings",
    "meeting_history",
    "meeting_provider_bindings",
    "meeting_series_provider_bindings",
    "meeting_write_requests",
)


def _event(uid: str, title: str = "Synthetic", **overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "calendar_ref": "cal-synthetic",
        "ical_uid": uid,
        "start_utc": "2026-12-01T15:00:00Z",
        "end_utc": "2026-12-01T16:00:00Z",
        "timezone_name": "America/New_York",
        "status": "confirmed",
        "all_day": False,
        "title": title,
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
    def __init__(self, engine: Engine, principal: str = P, *, admit: bool = True) -> None:
        self.engine = engine
        self.principal = principal
        self.store = FakeStore()
        self.now = T0
        self.applier = MeetingSyncApplier(unit_of_work=self.unit, clock=self.clock)
        if not admit:
            return
        self.source_id = (
            self.lifecycle()
            .admit(
                principal,
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
        return ingest_unit_of_work(self.engine)()

    def lifecycle(self) -> IngestionLifecycle:
        return IngestionLifecycle(
            unit_of_work=self.unit,
            stores=lambda _: self.store,
            handlers=[communications_handler(), meeting_sync_handler(clock=self.clock)],
            clock=self.clock,
            stability=StabilityMemory(),
        )

    def stage(self, name: str, data: bytes) -> None:
        self.store.put(f"{DIRECTORY}/{name}", data)
        report = self.lifecycle().backfill(self.principal, self.source_id)
        assert report.counts["snapshots_ingested"] == 1, dict(report.counts)

    def latch(self) -> None:
        with self.unit() as unit:
            unit.meeting_sync.insert_reconciliation_pass(
                self.principal,
                MeetingProviderReconciliationPassRecord(
                    completed_at=self.now,
                    reviewed_meetings=0,
                    reconcile_correlation_id="corr_synthetic00001",
                ),
            )

    def apply(self) -> dict[str, int]:
        return dict(self.applier.apply_pending(self.principal).counts)

    def count(self, table: str) -> int:
        return int(self.scalar(f"SELECT count(*) FROM knowledge.{table}"))  # noqa: S608

    def scalar(self, sql: str, **params: object) -> Any:  # noqa: ANN401
        with self.engine.connect() as connection:
            return connection.execute(text(sql), params).scalar_one()

    def rows(self, sql: str, **params: object) -> list[Any]:
        with self.engine.connect() as connection:
            return list(connection.execute(text(sql), params))


@pytest.fixture
def scene(migrated_engine: Engine) -> Scene:
    return Scene(migrated_engine)


def test_nothing_applies_before_the_latch_then_everything_and_a_rerun_is_idempotent(
    scene: Scene,
) -> None:
    scene.stage("20261122-meetings.json", _publication("2026-11-22T06:00:00Z", _event("uid-1")))
    scene.stage(
        "20261123-meetings.json",
        _publication("2026-11-23T06:00:00Z", _event("uid-1", "Moved"), _event("uid-2")),
    )
    assert scene.apply() == {"unapplied_awaiting_reconciliation": 2}
    assert {table: scene.count(table) for table in MEETING_PLANE} == dict.fromkeys(MEETING_PLANE, 0)
    assert scene.count("meeting_sync_publications") == 2
    assert (
        scene.scalar(
            "SELECT count(*) FROM knowledge.meeting_sync_publications WHERE applied_at IS NULL"
        )
        == 2
    )

    scene.latch()
    assert scene.apply() == {
        "events_created": 2,
        "events_updated": 1,
        "publications_applied": 2,
    }
    titles = [row.title for row in scene.rows("SELECT title FROM knowledge.meetings ORDER BY 1")]
    assert titles == ["Moved", "Synthetic"]
    bindings = scene.rows(
        "SELECT b.ical_uid, b.origin_snapshot_id, b.last_seen_snapshot_id,"
        " b.last_seen_source_sha256, s.file_sha256 AS last_sha, o.generated_at_utc AS origin_at"
        " FROM knowledge.meeting_provider_bindings b"
        " JOIN knowledge.ingest_snapshots s ON s.snapshot_id = b.last_seen_snapshot_id"
        " JOIN knowledge.meeting_sync_publications o ON o.snapshot_id = b.origin_snapshot_id"
        " ORDER BY b.ical_uid"
    )
    assert [row.ical_uid for row in bindings] == ["uid-1", "uid-2"]
    uid1, uid2 = bindings
    assert uid1.origin_at == datetime(2026, 11, 22, 6, tzinfo=UTC)
    assert uid1.last_seen_snapshot_id != uid1.origin_snapshot_id
    assert uid2.last_seen_snapshot_id == uid2.origin_snapshot_id
    assert all(row.last_seen_source_sha256 == row.last_sha for row in bindings)
    outcomes = scene.rows(
        "SELECT apply_outcome, apply_counts FROM knowledge.meeting_sync_publications"
        " ORDER BY generated_at_utc"
    )
    assert [(row.apply_outcome, row.apply_counts) for row in outcomes] == [
        ("applied", {"events_created": 1}),
        ("applied", {"events_created": 1, "events_updated": 1}),
    ]
    # No audit row (ruling D9): the evidence is the Meeting history and the Record Events.
    assert scene.count("meeting_history") == 3

    before = {table: scene.count(table) for table in (*MEETING_PLANE, "record_events")}
    assert scene.apply() == {}
    assert {table: scene.count(table) for table in before} == before


def test_a_stale_publication_is_skipped_and_writes_only_its_apply_columns(scene: Scene) -> None:
    scene.latch()
    scene.stage("b-meetings.json", _publication("2026-11-23T06:00:00Z", _event("uid-1", "New")))
    scene.apply()
    scene.stage(
        "a-meetings.json",
        _publication("2026-11-22T06:00:00Z", _event("uid-1", "Old"), _event("uid-x")),
    )
    assert scene.apply() == {"publications_skipped_stale": 1}
    assert scene.count("meetings") == 1
    assert scene.scalar("SELECT title FROM knowledge.meetings") == "New"


def test_not_seen_through_the_window_query_leaves_the_meeting_untouched(scene: Scene) -> None:
    scene.latch()
    scene.stage(
        "1-meetings.json",
        _publication("2026-11-22T06:00:00Z", _event("uid-1"), _event("uid-2"), coverage=COVERAGE),
    )
    scene.apply()
    meeting = scene.rows(
        "SELECT m.* FROM knowledge.meetings m JOIN knowledge.meeting_provider_bindings b"
        " USING (meeting_id) WHERE b.ical_uid = 'uid-2'"
    )
    binding_before = scene.rows(
        "SELECT * FROM knowledge.meeting_provider_bindings WHERE ical_uid = 'uid-2'"
    )
    scene.stage(
        "2-meetings.json",
        _publication("2026-11-23T06:00:00Z", _event("uid-1"), coverage=COVERAGE),
    )
    assert scene.apply() == {
        "bindings_marked_not_seen": 1,
        "events_unchanged": 1,
        "publications_applied": 1,
    }
    (after,) = scene.rows(
        "SELECT * FROM knowledge.meeting_provider_bindings WHERE ical_uid = 'uid-2'"
    )
    (before,) = binding_before
    assert (after.provider_state, after.version) == ("not_seen", before.version + 1)
    assert after.last_applied_generated_at_utc == datetime(2026, 11, 23, 6, tzinfo=UTC)
    assert (after.last_seen_snapshot_id, after.last_seen_at) == (
        before.last_seen_snapshot_id,
        before.last_seen_at,
    )
    assert (
        scene.rows(
            "SELECT m.* FROM knowledge.meetings m JOIN knowledge.meeting_provider_bindings b"
            " USING (meeting_id) WHERE b.ical_uid = 'uid-2'"
        )
        == meeting
    )
    scene.stage(
        "3-meetings.json",
        _publication("2026-11-24T06:00:00Z", _event("uid-1"), _event("uid-2"), coverage=COVERAGE),
    )
    scene.apply()
    assert (
        scene.scalar(
            "SELECT provider_state FROM knowledge.meeting_provider_bindings"
            " WHERE ical_uid = 'uid-2'"
        )
        == "active"
    )


def test_an_unbound_key_is_suppressed_and_its_tombstone_names_the_receipt(scene: Scene) -> None:
    scene.latch()
    scene.stage("1-meetings.json", _publication("2026-11-22T06:00:00Z", _event("uid-1")))
    scene.apply()
    meeting_id = scene.scalar("SELECT meeting_id FROM knowledge.meetings")
    with scene.unit() as unit:
        result = APP.bind_meeting_provider(
            unit,
            P,
            MeetingProviderBindRequest(action=ProviderBindAction.UNBIND, meeting_id=meeting_id),
            1,
            "unbind-db-0001",
            T0,
        )
    (tombstone,) = scene.rows("SELECT * FROM knowledge.meeting_provider_key_tombstones")
    assert (tombstone.meeting_id, tombstone.meeting_history_id, tombstone.ical_uid) == (
        meeting_id,
        result.receipt.history_id,
        "uid-1",
    )
    scene.stage("2-meetings.json", _publication("2026-11-23T06:00:00Z", _event("uid-1", "Again")))
    assert scene.apply() == {
        "events_skipped": 1,
        "events_skipped_unbound_key_suppressed": 1,
        "publications_applied": 1,
    }
    assert scene.count("meetings") == 1
    assert scene.count("meeting_provider_bindings") == 0


# ---- the binding-writer lock (D8) -----------------------------------------------------


def _waiting_on_the_binding_lock(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
                    " AND NOT granted AND classid = CAST(:cls AS oid)"
                ),
                {"cls": MEETING_PROVIDER_BINDING_LOCK_CLASS},
            ).scalar_one()
        )


def _hand_made(scene: Scene, key: str) -> str:
    with scene.unit() as unit:
        created = APP.create_meeting(
            unit,
            P,
            MeetingCreateRequest(
                title="Hand made", start_at=T0 + timedelta(days=7), timezone_name="UTC"
            ),
            key,
            T0,
        )
    return created.meeting.meeting_id


def test_two_connections_serialize_on_the_binding_writer_lock(scene: Scene) -> None:
    """A bind and a sync apply touching disjoint rows still serialize: only the lock can."""
    scene.latch()
    scene.stage("1-meetings.json", _publication("2026-11-22T06:00:00Z", _event("uid-1")))
    scene.apply()
    hand = _hand_made(scene, "create-lock-0001")
    scene.stage("2-meetings.json", _publication("2026-11-23T06:00:00Z", _event("uid-1", "B")))

    holding = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def bind_and_hold() -> None:
        try:
            with scene.unit() as unit:
                APP.bind_meeting_provider(
                    unit,
                    P,
                    MeetingProviderBindRequest(
                        action=ProviderBindAction.BIND,
                        meeting_id=hand,
                        calendar_ref="cal-synthetic",
                        ical_uid="uid-hand",
                    ),
                    1,
                    "bind-lock-0001",
                    T0,
                )
                holding.set()
                assert release.wait(30)
        except BaseException as error:
            errors.append(error)
            holding.set()

    applied: dict[str, dict[str, int]] = {}
    finished = threading.Event()

    def apply() -> None:
        try:
            applied["counts"] = scene.apply()
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    holder = threading.Thread(target=bind_and_hold)
    holder.start()
    assert holding.wait(30)
    applier = threading.Thread(target=apply)
    started = time.monotonic()
    applier.start()
    deadline = started + 10
    while _waiting_on_the_binding_lock(scene.engine) == 0 and time.monotonic() < deadline:
        time.sleep(0.05)
    try:
        assert _waiting_on_the_binding_lock(scene.engine) == 1
        assert not finished.is_set()
    finally:
        release.set()
        holder.join(30)
        applier.join(30)
    assert errors == []
    waited = time.monotonic() - started
    assert applied["counts"] == {"events_updated": 1, "publications_applied": 1}
    assert scene.count("meeting_provider_bindings") == 2
    assert waited < 30


def test_concurrent_binding_writers_finish_without_a_deadlock(scene: Scene) -> None:
    """Repeated binds and unbinds of two Meetings and a six-publication sync apply,
    each on its own connection and started together, all finish: no deadlock."""
    scene.latch()
    first = _hand_made(scene, "create-cross-1")
    second = _hand_made(scene, "create-cross-2")
    for stamp in range(6):
        scene.store.put(
            f"{DIRECTORY}/{stamp}-meetings.json",
            _publication(
                f"2026-11-2{stamp}T06:00:00Z",
                _event("uid-b", f"B{stamp}"),
                _event("uid-a", f"A{stamp}"),
            ),
        )
    scene.lifecycle().backfill(P, scene.source_id)
    errors: list[BaseException] = []
    barrier = threading.Barrier(3)

    def cycle(meeting_id: str, uid: str, label: str) -> None:
        try:
            barrier.wait(10)
            version = 1
            for turn in range(4):
                for action in (ProviderBindAction.BIND, ProviderBindAction.UNBIND):
                    with scene.unit() as unit:
                        APP.bind_meeting_provider(
                            unit,
                            P,
                            MeetingProviderBindRequest(
                                action=action,
                                meeting_id=meeting_id,
                                calendar_ref="cal-synthetic"
                                if action is ProviderBindAction.BIND
                                else None,
                                ical_uid=f"{uid}-{turn}"
                                if action is ProviderBindAction.BIND
                                else None,
                            ),
                            version,
                            f"{label}-{turn}-{action.value}",
                            T0,
                        )
                    version += 1
        except BaseException as error:
            errors.append(error)

    def sync() -> None:
        try:
            barrier.wait(10)
            scene.apply()
        except BaseException as error:
            errors.append(error)

    threads = [
        threading.Thread(target=cycle, args=(first, "uid-x", "first")),
        threading.Thread(target=cycle, args=(second, "uid-y", "second")),
        threading.Thread(target=sync),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(120)
    assert errors == []
    assert (
        scene.scalar(
            "SELECT count(*) FROM knowledge.meeting_sync_publications"
            " WHERE apply_outcome = 'applied'"
        )
        == 6
    )
    assert scene.count("meeting_provider_key_tombstones") == 8


# ---- the wiring: the cycles step and the operator CLI ------------------------------


def test_the_cycles_step_polls_then_applies(
    scene: Scene, capsys: pytest.CaptureFixture[str]
) -> None:
    scene.latch()
    scene.store.put(
        f"{DIRECTORY}/1-meetings.json", _publication("2026-11-22T06:00:00Z", _event("uid-1"))
    )
    lifecycle = scene.lifecycle()
    step = worker_app._comms_ingest_step(lifecycle, scene.applier, P, 900)
    # The stability gate needs two polls with the same size and token.
    assert step.run_once() is True
    assert step.run_once() is True
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["event"] for line in lines] == [
        "comms_ingest.run",
        "meeting_sync.apply",
        "comms_ingest.run",
        "meeting_sync.apply",
    ]
    assert lines[-1]["counts"] == {"events_created": 1, "publications_applied": 1}
    assert scene.count("meetings") == 1


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "workspace"
    (root / DIRECTORY).mkdir(parents=True)
    (root / DIRECTORY / "20261122-meetings.json").write_bytes(
        _publication("2026-11-22T06:00:00Z", _event("uid-1"))
    )
    monkeypatch.setenv("MY_PA_FILES_WORKSPACES", f"mcp={root};mode=direct")
    monkeypatch.delenv("MY_PA_FILES_WORKSPACE_ROOT", raising=False)
    yield root


def test_the_cli_run_once_applies_under_the_poll_lock(
    migrated_engine: Engine,
    workspace: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operator = Scene(migrated_engine, principal=local_principal().principal_id, admit=False)
    database = make_url(os.environ["MY_PA_DATABASE_URL"]).database
    head = operator.scalar("SELECT version_num FROM alembic_version")
    expect = ["--expected-database", str(database), "--expected-alembic-head", str(head)]

    def run(*argv: str) -> tuple[int, dict[str, Any]]:
        code = cli.main([*expect, *argv])
        out = capsys.readouterr().out.splitlines()
        assert len(out) == 1
        return code, json.loads(out[0])

    code, admitted = run(
        "admit",
        "--consumer",
        "meeting_sync_v1",
        "--workspace",
        "mcp",
        "--path-prefix",
        DIRECTORY + "/",
        "--file-pattern",
        "*-meetings.json",
    )
    assert code == cli.EXIT_OK
    source = str(admitted["ingest_source_id"])
    code, out = run("backfill", "--source", source, "--dry-run")
    assert "meeting_sync_apply" not in out
    code, out = run("backfill", "--source", source)
    assert (code, out["meeting_sync_apply"]) == (
        cli.EXIT_OK,
        {"unapplied_awaiting_reconciliation": 1},
    )
    operator.latch()
    code, out = run("run-once", "--source", source)
    assert out["meeting_sync_apply"] == {"events_created": 1, "publications_applied": 1}
    assert operator.count("meetings") == 1
