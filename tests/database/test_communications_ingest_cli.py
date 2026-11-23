"""WP3a-I3: the operator command end to end on PostgreSQL, over a real workspace directory.

The `database` tier, on a disposable head-migrated clone. The command is run
through `apps.cli.communications_ingest.main` exactly as an operator runs it:
the database from `MY_PA_DATABASE_URL`, the expectations asserted, the
workspace composed from `MY_PA_FILES_WORKSPACES` over a temporary directory
whose folders and files are read-only (mode 0555/0444). The synthetic
committed fixtures play the canonical folder and the two separately admitted
rich publications (ruling R2). The sequence is the Manager's real-corpus one:
admit (three sources), backfill `--dry-run` (writes nothing), backfill
(ingests), backfill again (idempotent: no new communication row), coverage and
the rolling window, and the aggregate over all three sources, whose counts
reconcile with the tables and carry no fixture content.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli import communications_ingest as cli
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.infrastructure.jobs.cycle_scheduler import COMMS_INGEST_LOCK_KEY
from tests.fixtures.communications_evidence import synthetic as s

pytestmark = pytest.mark.database

CANONICAL: Final = "My PA/Daily Intelligence/communications"
RICH_FOLDER: Final = "My PA/Daily Intelligence"
CANONICAL_FILES: Final = {
    "20261117-comms.json": s.lean_publication,
    "20261121-comms.json": s.friday_publication,
    "20261124-comms.json": s.weekend_48h_publication,
}
RICH_FILES: Final = {
    "rich-comms-a.json": s.rich_publication,
    "rich-comms-b.json": s.weekend_49h_publication,
}
COMMS_TABLES: Final = (
    "communication_messages",
    "communication_mailbox_items",
    "communication_observations",
    "communication_participants",
    "communication_identifiers",
    "communication_quarantine",
    "ingest_snapshots",
    "ingest_snapshot_paths",
    "ingest_coverage_windows",
)


def _lock(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o444 if path.is_file() else 0o555)
    root.chmod(0o555)


def _unlock(root: Path) -> None:
    root.chmod(0o755)
    for path in root.rglob("*"):
        path.chmod(0o644 if path.is_file() else 0o755)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "workspace"
    (root / CANONICAL).mkdir(parents=True)
    for name, builder in CANONICAL_FILES.items():
        (root / CANONICAL / name).write_bytes(s.encode(builder()))
    for name, builder in RICH_FILES.items():
        (root / RICH_FOLDER / name).write_bytes(s.encode(builder()))
    _lock(root)
    assert not os.access(root / CANONICAL, os.W_OK) or os.geteuid() == 0
    monkeypatch.setenv("MY_PA_FILES_WORKSPACES", f"mcp={root};mode=direct")
    monkeypatch.delenv("MY_PA_FILES_WORKSPACE_ROOT", raising=False)
    try:
        yield root
    finally:
        _unlock(root)


class Operator:
    def __init__(self, engine: Engine, capsys: pytest.CaptureFixture[str]) -> None:
        self.engine = engine
        self.capsys = capsys
        database = make_url(os.environ["MY_PA_DATABASE_URL"]).database
        with engine.connect() as connection:
            head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        self.expect = ["--expected-database", str(database), "--expected-alembic-head", str(head)]

    def __call__(self, *argv: str) -> tuple[int, dict[str, Any], str]:
        code = cli.main([*self.expect, *argv])
        captured = self.capsys.readouterr()
        assert captured.err == ""
        lines = captured.out.splitlines()
        assert len(lines) == 1, captured.out
        return code, json.loads(lines[0]), captured.out

    def counts(self) -> dict[str, int]:
        with self.engine.connect() as connection:
            return {
                table: int(
                    connection.execute(
                        text(f"SELECT count(*) FROM knowledge.{table}")  # noqa: S608 - constants
                    ).scalar_one()
                )
                for table in (*COMMS_TABLES, "ingest_runs", "ingest_run_snapshots")
            }

    def scalar(self, sql: str) -> int:
        with self.engine.connect() as connection:
            return int(connection.execute(text(sql)).scalar_one())


def _admit(operator: Operator, prefix: str, pattern: str) -> str:
    code, out, _ = operator(
        "admit",
        "--consumer",
        "communications_evidence_v2",
        "--workspace",
        "mcp",
        "--path-prefix",
        prefix + "/",
        "--file-pattern",
        pattern,
    )
    assert code == cli.EXIT_OK, out
    return str(out["ingest_source_id"])


def _forbidden() -> set[str]:
    keys = {"address", "subject", "internet_message_id", "id", "conversation_id", "content"}
    found: set[str] = set()

    def walk(node: object, key: str | None) -> None:
        if isinstance(node, dict):
            for name, value in node.items():
                walk(value, name)
        elif isinstance(node, list):
            for value in node:
                walk(value, key)
        elif isinstance(node, str) and key in keys and len(node) >= 6:
            found.add(node)

    for builder in (*CANONICAL_FILES.values(), *RICH_FILES.values()):
        walk(builder(), None)
    return found


def test_the_operator_sequence_admit_backfill_rerun_coverage_aggregate(
    migrated_engine: Engine, workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    operator = Operator(migrated_engine, capsys)
    outputs: list[str] = []
    canonical = _admit(operator, CANONICAL, "*-comms.json")
    rich = [_admit(operator, RICH_FOLDER, name) for name in sorted(RICH_FILES)]
    sources = [canonical, *rich]
    assert operator.scalar("SELECT count(*) FROM knowledge.ingest_sources") == 3
    assert (
        operator.scalar(
            "SELECT count(*) FROM knowledge.ingest_sources WHERE admitted_by = 'operator_cli'"
        )
        == 3
    )
    assert operator.scalar("SELECT count(*) FROM knowledge.audit_events") == 0

    # Dry run: counts, and nothing written.
    before = operator.counts()
    code, dry, raw = operator("backfill", "--source", canonical, "--dry-run")
    outputs.append(raw)
    assert (code, dry["dry_run"], dry["run_id"]) == (cli.EXIT_OK, True, None)
    assert dry["counts"]["snapshots_new"] == len(CANONICAL_FILES)
    assert operator.counts() == before

    # Backfill every source.
    for source in sources:
        code, report, raw = operator("backfill", "--source", source)
        outputs.append(raw)
        assert (code, report["outcome"]) == (cli.EXIT_OK, "completed"), report
    expected_snapshots = len(CANONICAL_FILES) + len(RICH_FILES)
    assert operator.scalar("SELECT count(*) FROM knowledge.ingest_snapshots") == (
        expected_snapshots
    )
    ingested = operator.counts()

    # Rerun: idempotent, only the run and its links are new.
    for source in sources:
        code, report, raw = operator("backfill", "--source", source)
        outputs.append(raw)
        assert report["counts"]["snapshots_ingested"] == 0
        assert report["counts"]["snapshots_already_known"] >= 1
    rerun = operator.counts()
    assert {t: rerun[t] for t in COMMS_TABLES} == {t: ingested[t] for t in COMMS_TABLES}
    assert rerun["ingest_runs"] == ingested["ingest_runs"] + len(sources)

    # run-once on the enabled canonical source: known bytes, completed.
    code, once, raw = operator("run-once", "--source", canonical)
    outputs.append(raw)
    assert (code, once["trigger"], once["outcome"]) == (cli.EXIT_OK, "operator", "completed")

    # Coverage and the rolling window.
    code, coverage, raw = operator(
        "coverage",
        "--source",
        canonical,
        "--from",
        "2026-11-16T00:00:00Z",
        "--to",
        "2026-11-26T00:00:00Z",
    )
    outputs.append(raw)
    assert code == cli.EXIT_OK
    assert coverage["snapshots"] == len(CANONICAL_FILES)
    assert coverage["interval_count"] >= 1
    assert coverage["range"]["state"] in {"partial", "complete"}
    assert coverage["rolling_30d"]["state"] in {"complete", "partial", "none"}

    # The aggregate over the three sources reconciles with the tables.
    argv = ["aggregate"]
    for source in sources:
        argv += ["--source", source]
    code, aggregate, raw = operator(*argv)
    outputs.append(raw)
    assert code == cli.EXIT_OK
    assert aggregate["snapshots"] == {"ingested": expected_snapshots}
    assert aggregate["observations"]["total"] == ingested["communication_observations"]
    assert aggregate["quarantined_records"] == ingested["communication_quarantine"]
    assert aggregate["messages"] == ingested["communication_messages"]
    assert aggregate["items"] == ingested["communication_mailbox_items"]
    assert (
        sum(aggregate["observations"]["by_classification"].values())
        == (aggregate["observations"]["total"])
    )
    total_records = sum(
        len(builder()["messages"]) for builder in (*CANONICAL_FILES.values(), *RICH_FILES.values())
    )
    assert aggregate["observations"]["total"] + aggregate["quarantined_records"] == total_records
    assert aggregate["runs"]["backfill"] == {"completed": 2 * len(sources)}
    assert aggregate["runs"]["operator"] == {"completed": 1}
    assert aggregate["coverage"]["snapshots"] == expected_snapshots
    assert aggregate["multi_lane_item_snapshots"] >= aggregate["multi_lane_items"] >= 1
    identifier_rows = sum(kind["rows"] for kind in aggregate["identifiers"].values())
    assert identifier_rows == ingested["communication_identifiers"]
    assert sum(aggregate["quarantine_reasons"].values()) >= aggregate["quarantined_records"]

    # Per-source scoping: the canonical source alone sees only its snapshots.
    code, alone, raw = operator("aggregate", "--source", canonical)
    outputs.append(raw)
    assert alone["snapshots"] == {"ingested": len(CANONICAL_FILES)}
    assert alone["observations"]["total"] < aggregate["observations"]["total"]

    # Counts only: no fixture content, no path, no file name, no URL.
    forbidden = _forbidden()
    assert len(forbidden) > 20
    url = make_url(os.environ["MY_PA_DATABASE_URL"])
    for output in outputs:
        assert not sorted(value for value in forbidden if value in output)
        assert "Daily Intelligence" not in output
        assert ".json" not in output
        assert str(url.host) not in output
        assert str(workspace) not in output


def test_the_read_only_workspace_is_never_written(
    migrated_engine: Engine, workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    operator = Operator(migrated_engine, capsys)
    snapshot = {
        path: (path.stat().st_mtime_ns, stat.S_IMODE(path.stat().st_mode))
        for path in workspace.rglob("*")
    }
    canonical = _admit(operator, CANONICAL, "*-comms.json")
    operator("backfill", "--source", canonical)
    operator("run-once", "--source", canonical)
    after = {
        path: (path.stat().st_mtime_ns, stat.S_IMODE(path.stat().st_mode))
        for path in workspace.rglob("*")
    }
    assert after == snapshot


def test_run_once_and_backfill_refuse_lock_held_while_another_session_holds_the_poll_lock(
    migrated_engine: Engine, workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """F4: the command contends for `COMMS_INGEST_LOCK_KEY` with the cycles plane's poll."""
    operator = Operator(migrated_engine, capsys)
    canonical = _admit(operator, CANONICAL, "*-comms.json")
    before = operator.counts()
    with migrated_engine.connect() as holder:
        assert holder.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": COMMS_INGEST_LOCK_KEY}
        ).scalar_one()
        holder.commit()
        try:
            for argv in (("run-once",), ("backfill",)):
                code, out, _ = operator(*argv, "--source", canonical)
                assert (code, out) == (
                    cli.EXIT_REFUSED,
                    {"command": argv[0], "refused": "lock_held"},
                )
            # A dry run writes nothing and takes no lock.
            code, dry, _ = operator("backfill", "--source", canonical, "--dry-run")
            assert (code, dry["dry_run"]) == (cli.EXIT_OK, True)
            assert operator.counts() == before
        finally:
            holder.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": COMMS_INGEST_LOCK_KEY})
            holder.commit()
    code, report, _ = operator("backfill", "--source", canonical)
    assert (code, report["outcome"]) == (cli.EXIT_OK, "completed")
    assert report["counts"]["snapshots_ingested"] == len(CANONICAL_FILES)
    # Released after the run: a session can take it at once.
    with migrated_engine.connect() as probe:
        assert probe.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": COMMS_INGEST_LOCK_KEY}
        ).scalar_one()
        probe.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": COMMS_INGEST_LOCK_KEY})
        probe.commit()
