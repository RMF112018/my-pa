"""WP3a-I2: the ingestion lifecycle and the communications consumer, end to end on PostgreSQL.

The `database` tier, on a disposable head-migrated clone: the real lifecycle,
the real handler (WP1 parser wired by `bootstrap.communications_ingest`), the
real repositories through the general unit of work, and the synthetic
committed fixtures served by the in-memory file store double. Proved here: a
backfill ingests every fixture oldest window first with per-snapshot totals
that reconcile; a rerun is idempotent (no new row); a re-publication
supersedes the path and adds observations without new messages; a failure
injected into one snapshot rolls back that snapshot only and a rerun resumes;
a path revert writes nothing the revision's one-way supersession would refuse;
and a dry run writes nothing. Everything is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Engine, text

from my_pa.application.communications_ingest import CommunicationsEvidenceHandler
from my_pa.application.ingestion import IngestionLifecycle, IngestRunReport, StabilityMemory
from my_pa.bootstrap.communications_ingest import communications_handler, parse_for_ingestion
from my_pa.contracts.ports import (
    IngestApplied,
    IngestConsumer,
    IngestPrepared,
    IngestRunOutcome,
    IngestSnapshotRecord,
    UnitOfWork,
)
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.fixtures.communications_evidence import synthetic as s
from tests.unit.communications_ingest_fakes import FakeStore

pytestmark = pytest.mark.database

P: Final = "prn_commsapp0001aaaa"
DIRECTORY: Final = "My PA/Daily Intelligence/communications"
T0: Final = datetime(2026, 11, 22, 12, tzinfo=UTC)
TABLES: Final = (
    "ingest_sources",
    "ingest_snapshots",
    "ingest_snapshot_paths",
    "ingest_runs",
    "ingest_run_snapshots",
    "ingest_coverage_windows",
    "communication_messages",
    "communication_mailbox_items",
    "communication_observations",
    "communication_participants",
    "communication_identifiers",
    "communication_quarantine",
)
#: Committed fixture -> file name; listing order deliberately not window order.
FILES: Final = {
    "a-lean-comms.json": s.lean_publication,
    "b-rich-comms.json": s.rich_publication,
    "c-friday-comms.json": s.friday_publication,
    "d-weekend49-comms.json": s.weekend_49h_publication,
    "e-weekend48-comms.json": s.weekend_48h_publication,
}


class FailingOnce(CommunicationsEvidenceHandler):
    """The real handler, raising after its writes for one chosen window start."""

    def __init__(self, fail_start: datetime) -> None:
        real = communications_handler()
        super().__init__(
            parse=parse_for_ingestion,
            parser_version=real.parser_version,
            max_bytes=real.max_bytes,
        )
        self.fail_start: datetime | None = fail_start

    def apply(
        self,
        unit: UnitOfWork,
        principal_id: str,
        snapshot: IngestSnapshotRecord,
        prepared: IngestPrepared,
    ) -> IngestApplied:
        applied = super().apply(unit, principal_id, snapshot, prepared)
        if prepared.window_start == self.fail_start:
            self.fail_start = None
            raise RuntimeError("injected failure after the snapshot's writes")
        return applied


class Scene:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.store = FakeStore()
        self.now = T0
        self.source_id = (
            self.lifecycle()
            .admit(
                P,
                consumer=IngestConsumer.COMMUNICATIONS_EVIDENCE_V2,
                workspace_id="mcp",
                path_prefix=DIRECTORY + "/",
                file_pattern="*-comms.json",
            )
            .ingest_source_id
        )

    def clock(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now

    def unit(self) -> UnitOfWork:
        return SqlAlchemyUnitOfWork(self.engine, audit=SqlAlchemyAuditSink(self.engine))

    def lifecycle(self, handler: CommunicationsEvidenceHandler | None = None) -> IngestionLifecycle:
        return IngestionLifecycle(
            unit_of_work=self.unit,
            stores=lambda _: self.store,
            handlers=[handler or communications_handler()],
            clock=self.clock,
            stability=StabilityMemory(),
        )

    def put_all(self) -> None:
        for name, builder in FILES.items():
            self.store.put(f"{DIRECTORY}/{name}", s.encode(builder()))

    def backfill(self, handler: CommunicationsEvidenceHandler | None = None) -> IngestRunReport:
        return self.lifecycle(handler).backfill(P, self.source_id)

    def counts(self) -> dict[str, int]:
        with self.engine.connect() as connection:
            return {
                table: connection.execute(
                    text(f"SELECT count(*) FROM knowledge.{table}")  # noqa: S608 - constant names
                ).scalar_one()
                for table in TABLES
            }

    def scalar(self, sql: str) -> object:
        with self.engine.connect() as connection:
            return connection.execute(text(sql)).scalar_one()


@pytest.fixture
def scene(migrated_engine: Engine) -> Scene:
    return Scene(migrated_engine)


def _total_records() -> int:
    return sum(len(builder()["messages"]) for builder in FILES.values())


def test_a_backfill_ingests_every_fixture_oldest_window_first(scene: Scene) -> None:
    scene.put_all()
    report = scene.backfill()
    assert report.outcome is IngestRunOutcome.COMPLETED
    assert report.counts["snapshots_ingested"] == len(FILES)
    assert report.counts["records_total"] == _total_records()
    rows = scene.counts()
    assert rows["communication_observations"] + rows["communication_quarantine"] == (
        _total_records()
    )
    # Applied oldest first: the coverage windows were recorded in start order.
    with scene.engine.connect() as connection:
        starts = connection.execute(
            text(
                "SELECT start_utc FROM knowledge.ingest_coverage_windows "
                "ORDER BY recorded_at, coverage_window_id"
            )
        ).scalars()
        ordered = list(starts)
        per_snapshot = connection.execute(
            text(
                "SELECT s.snapshot_id, "
                "(SELECT count(*) FROM knowledge.communication_observations o "
                " WHERE o.snapshot_id = s.snapshot_id) + "
                "(SELECT count(*) FROM knowledge.communication_quarantine q "
                " WHERE q.snapshot_id = s.snapshot_id) FROM knowledge.ingest_snapshots s"
            )
        ).all()
    assert ordered == sorted(ordered)
    assert sorted(count for _, count in per_snapshot) == sorted(
        len(builder()["messages"]) for builder in FILES.values()
    )
    # The generated English document exists for a message with text and not for withheld ones.
    assert (
        scene.scalar(
            "SELECT count(*) FROM knowledge.communication_messages "
            "WHERE search_text IS NOT NULL AND search_document = ''::tsvector"
        )
        == 0
    )
    assert (
        scene.scalar(
            "SELECT count(*) FROM knowledge.communication_messages "
            "WHERE body_state = 'withheld' AND search_text IS NOT NULL"
        )
        == 0
    )
    assert (
        scene.scalar(
            "SELECT count(*) FROM knowledge.communication_identifiers "
            "WHERE extractor_version = 'comms_identifiers_v1' AND kind = 'rfi' AND value = '174'"
        )
        >= 1
    )
    # WP4 ruling R2: every message records the version its identifier rows were
    # written under, and ingestion writes that one version only (R10).
    assert (
        scene.scalar(
            "SELECT count(*) FROM knowledge.communication_messages "
            "WHERE identifiers_version IS DISTINCT FROM 'comms_identifiers_v1'"
        )
        == 0
    )
    assert (
        scene.scalar(
            "SELECT count(*) FROM knowledge.communication_identifiers "
            "WHERE extractor_version <> 'comms_identifiers_v1'"
        )
        == 0
    )
    assert scene.scalar("SELECT count(*) FROM knowledge.communication_messages") > 0


def test_a_rerun_is_idempotent(scene: Scene) -> None:
    scene.put_all()
    scene.backfill()
    before = scene.counts()
    rerun = scene.backfill()  # a fresh lifecycle: no in-process memory, re-reads
    assert rerun.counts["snapshots_already_known"] == len(FILES)
    assert rerun.counts["snapshots_new"] == 0
    after = scene.counts()
    assert after["ingest_runs"] == before["ingest_runs"] + 1
    assert after["ingest_run_snapshots"] == before["ingest_run_snapshots"] + len(FILES)
    unchanged = {k: v for k, v in after.items() if k not in {"ingest_runs", "ingest_run_snapshots"}}
    assert unchanged == {
        k: v for k, v in before.items() if k not in {"ingest_runs", "ingest_run_snapshots"}
    }


def test_a_republication_supersedes_the_path_and_adds_observations(scene: Scene) -> None:
    path = f"{DIRECTORY}/a-lean-comms.json"
    scene.store.put(path, s.encode(s.lean_publication()))
    scene.backfill()
    before = scene.counts()
    republished = s.lean_publication()
    republished["business_date"] = "2026-11-18"  # new bytes, same messages
    scene.store.put(path, s.encode(republished))
    report = scene.backfill()
    assert (report.counts["snapshots_ingested"], report.counts["snapshots_superseded"]) == (1, 1)
    after = scene.counts()
    assert after["communication_messages"] == before["communication_messages"]
    assert after["communication_observations"] == 2 * before["communication_observations"]
    assert after["ingest_coverage_windows"] == 2
    assert (
        scene.scalar(
            "SELECT count(*) FROM knowledge.ingest_snapshot_paths "
            "WHERE superseded_by_snapshot_id IS NULL"
        )
        == 1
    )


def test_a_failure_rolls_back_one_snapshot_and_a_rerun_resumes(scene: Scene) -> None:
    scene.put_all()
    failing_start = datetime(2026, 11, 13, 7, tzinfo=UTC)  # the rich fixture's window
    report = scene.backfill(FailingOnce(failing_start))
    assert report.outcome is IngestRunOutcome.PARTIAL
    assert report.counts["snapshots_failed"] == 1
    assert report.counts["snapshots_ingested"] == len(FILES) - 1
    rich_records = len(s.rich_publication()["messages"])
    rows = scene.counts()
    assert rows["ingest_snapshots"] == len(FILES) - 1
    assert rows["communication_observations"] + rows["communication_quarantine"] == (
        _total_records() - rich_records
    )
    assert (
        scene.scalar(
            "SELECT count(*) FROM knowledge.ingest_coverage_windows WHERE start_utc = "
            "'2026-11-13T07:00:00Z'"
        )
        == 0
    )
    resumed = scene.backfill()
    assert resumed.counts["snapshots_ingested"] == 1
    assert resumed.counts["snapshots_already_known"] == len(FILES) - 1
    rows = scene.counts()
    assert rows["communication_observations"] + rows["communication_quarantine"] == (
        _total_records()
    )


def test_a_path_revert_writes_nothing_the_one_way_supersession_refuses(scene: Scene) -> None:
    path = f"{DIRECTORY}/a-lean-comms.json"
    original = s.encode(s.lean_publication())
    scene.store.put(path, original)
    scene.backfill()
    changed = s.lean_publication()
    changed["business_date"] = "2026-11-18"
    scene.store.put(path, s.encode(changed))
    scene.backfill()
    scene.store.put(path, original)
    report = scene.backfill()
    assert report.outcome is IngestRunOutcome.COMPLETED
    assert report.counts["snapshots_path_reverted"] == 1
    assert scene.counts()["ingest_snapshot_paths"] == 2


def test_a_dry_run_writes_nothing(scene: Scene) -> None:
    scene.put_all()
    before = scene.counts()
    report = scene.lifecycle().backfill(P, scene.source_id, dry_run=True)
    assert report.counts["snapshots_ingested"] == len(FILES)
    assert scene.counts() == before


def _day_publication(day: int, messages: list[dict[str, object]]) -> bytes:
    start = datetime(2026, 11, day, 5, tzinfo=UTC)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    window = s.window(
        start.isoformat().replace("+00:00", "Z"),
        end.isoformat().replace("+00:00", "Z"),
        24,
        "weekday_prior_24h",
    )
    return s.encode(s.publication(messages, window))


def test_a_cross_kind_provider_id_is_quarantined_identity_kind_mismatch(scene: Scene) -> None:
    """F1 on PostgreSQL: the closed reason is admitted by the revision's CHECK, the
    stored message is untouched, and the Message-ID is one provider_returned message."""
    message_id = "<synthetic-0001@example.invalid>"
    scene.store.put(
        f"{DIRECTORY}/20261117-comms.json",
        _day_publication(17, [s.message(1, selected="2026-11-17T12:00:00Z", imid=None)]),
    )
    scene.backfill()
    stored = scene.counts()
    sent_copy = s.message(
        2,
        folder="sent",
        selected="2026-11-18T12:00:00Z",
        selected_field="sentDateTime",
        imid=message_id,
    )
    scene.store.put(
        f"{DIRECTORY}/20261118-comms.json",
        _day_publication(
            18, [s.message(1, selected="2026-11-18T12:00:00Z", imid=message_id), sent_copy]
        ),
    )
    report = scene.backfill()
    assert report.outcome is IngestRunOutcome.COMPLETED
    assert report.counts["records_identity_kind_mismatch"] == 1
    rows = scene.counts()
    assert rows["communication_quarantine"] == stored["communication_quarantine"] + 1
    assert rows["communication_messages"] == stored["communication_messages"] + 1
    assert (
        scene.scalar(
            "SELECT count(*) FROM knowledge.communication_quarantine "
            "WHERE 'identity_kind_mismatch' = ANY(reasons)"
        )
        == 1
    )
    assert (
        scene.scalar(
            "SELECT count(*) FROM knowledge.communication_messages "
            "WHERE identity_kind = 'provider_returned' "
            "AND identity_value = '<synthetic-0001@example.invalid>'"
        )
        == 1
    )
    assert (
        scene.scalar(
            "SELECT count(*) FROM knowledge.communication_messages WHERE identity_conflict"
        )
        == 0
    )
