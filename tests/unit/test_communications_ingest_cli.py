"""`apps/cli/communications_ingest.py`, the operator command (WP3a rulings m7, m8).

FAST tier, with fakes: the lifecycle tables are the in-memory `IngestWorld`,
the workspace is the in-memory `FakeStore`, and the engine answers only the
two identity queries. Proved here: argument parsing (required expectations,
exclusive file selectors, a paired range); the expectation refusals (before an
engine is built when the configured name differs, on the live connection
when the catalog or the Alembic head differs); the database URL never
appearing in any output; a dry run writing nothing; and output that carries
no fixture subject, address, provider id, digest or path. The end-to-end run
against PostgreSQL is `tests/database/test_communications_ingest_cli.py`.

This module also governs the command for
`tests/architecture/test_operator_commands_are_not_capabilities.py` (it is
`EXEMPT` there because it reaches the ingestion lifecycle in
`my_pa.application`): it names no `Capability`, builds no `ApplicationService`,
and imports from persistence only the two aggregate reads.
"""

from __future__ import annotations

import ast
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli import communications_ingest as cli
from sqlalchemy.exc import OperationalError

from my_pa.application import communications_ingest as ingest_module
from my_pa.application.communications_ingest import CommunicationsCoverageReader
from my_pa.application.communications_rederive import REDERIVE_COUNT_KEYS, CommunicationsRederiver
from my_pa.application.ingestion import IngestionLifecycle, StabilityMemory
from my_pa.application.meeting_sync_apply import MeetingSyncApplier
from my_pa.bootstrap.communications_ingest import communications_handler, parse_for_ingestion
from my_pa.domain.communications.identifiers import IDENTIFIER_VERSION_V1
from my_pa.domain.communications.search_text import derive_search_text_v1
from my_pa.infrastructure.communications.evidence_v2 import MAX_PUBLICATION_BYTES
from tests.fixtures.communications_evidence import synthetic as s
from tests.unit.communications_ingest_fakes import FakeStore, IngestWorld, unit_of_work_factory

ROOT: Final = Path(__file__).resolve().parents[2]
COMMAND: Final = ROOT / "apps" / "cli" / "communications_ingest.py"
DIRECTORY: Final = "My PA/Daily Intelligence/communications"
#: A URL whose every part is distinctive, so an echo of any part is caught.
DSN: Final = "postgresql+psycopg://dsnuser:dsnsecret@dsnhost.invalid:6543/dsncatalog"
DSN_PARTS: Final = ("dsnuser", "dsnsecret", "dsnhost", "6543", "postgresql+psycopg")
#: A synthetic revision: the command compares it with the (fake) live
#: `alembic_version` row, so naming the real chain head here would only make
#: this file a head pin that every later migration has to advance.
HEAD: Final = "feedfacecafe"
EXPECT: Final = ["--expected-database", "dsncatalog", "--expected-alembic-head", HEAD]
#: The fixture fields whose values are content and must never be printed.
CONTENT_KEYS: Final = frozenset(
    {
        "address",
        "address_normalized",
        "content",
        "conversation_id",
        "display",
        "display_name",
        "id",
        "internet_message_id",
        "mailbox_ref",
        "message_id",
        "name",
        "sha256",
        "subject",
        "text",
    }
)


# ---- fakes -----------------------------------------------------------------------


class _Result:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalar_one(self) -> object:
        return self._values[0]

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[object]:
        return self._values


class _Connection:
    def __init__(self, database: str, heads: list[str]) -> None:
        self.database = database
        self.heads = heads
        #: The poll lock: free, or held by another session (F4).
        self.lock_free = True
        self.lock_calls: list[str] = []

    def execute(self, statement: object) -> _Result:
        sql = str(statement)
        if "current_database" in sql:
            return _Result([self.database])
        if "alembic_version" in sql:
            return _Result(list(self.heads))
        if "pg_try_advisory_lock" in sql:
            self.lock_calls.append("try")
            return _Result([self.lock_free])
        if "pg_advisory_unlock" in sql:
            self.lock_calls.append("unlock")
            return _Result([True])
        raise AssertionError("the fake engine answers only the identity and lock queries")

    def commit(self) -> None:
        return None


class _Engine:
    def __init__(self, database: str = "dsncatalog", heads: list[str] | None = None) -> None:
        self.connection = _Connection(database, [HEAD] if heads is None else heads)
        self.disposed = False

    @contextmanager
    def connect(self) -> Iterator[_Connection]:
        yield self.connection

    def dispose(self) -> None:
        self.disposed = True


class _Scene:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, engine: _Engine | None = None) -> None:
        for key in [key for key in os.environ if key.startswith("MY_PA_")]:
            monkeypatch.delenv(key)
        monkeypatch.setenv("MY_PA_DATABASE_URL", DSN)
        self.world = IngestWorld()
        self.store = FakeStore()
        self.engine = engine or _Engine()
        self.engines_built = 0
        self.stability = StabilityMemory()
        unit = unit_of_work_factory(self.world)

        def build(*_args: object, **kwargs: object) -> _Engine:
            assert kwargs.get("statement_timeout_ms") == cli.STATEMENT_TIMEOUT_MS
            self.engines_built += 1
            return self.engine

        monkeypatch.setattr(cli, "create_database_engine", build)

        def lifecycle(*_args: object, **_kwargs: object) -> IngestionLifecycle:
            # One process per invocation: a fresh stability memory each time.
            self.stability = StabilityMemory()
            return IngestionLifecycle(
                unit_of_work=unit,
                stores=self._store,
                handlers=[communications_handler()],
                stability=self.stability,
            )

        monkeypatch.setattr(cli, "ingestion_lifecycle", lifecycle)
        monkeypatch.setattr(
            cli,
            "coverage_reader",
            lambda *_a, **_k: CommunicationsCoverageReader(unit_of_work=unit),
        )
        monkeypatch.setattr(cli, "ingest_unit_of_work", lambda _engine: unit)
        # WP3b-S3: run-once and backfill apply the staged meeting sync after the
        # run; no latch in these worlds, so it applies nothing.
        monkeypatch.setattr(
            cli,
            "meeting_sync_applier",
            lambda *_a, **_k: MeetingSyncApplier(unit_of_work=unit),
        )
        # WP4-S3: the rederive over the same world and store.
        monkeypatch.setattr(
            cli,
            "communications_rederiver",
            lambda *_a, **_k: CommunicationsRederiver(
                unit_of_work=unit,
                stores=self._store,
                parse=parse_for_ingestion,
                max_bytes=MAX_PUBLICATION_BYTES,
            ),
        )

    def _store(self, workspace_id: str) -> FakeStore:
        if workspace_id != "mcp":
            raise LookupError(workspace_id)
        return self.store

    def put_fixtures(self) -> None:
        self.store.put(f"{DIRECTORY}/a-lean-comms.json", s.encode(s.lean_publication()))
        self.store.put(f"{DIRECTORY}/b-rich-comms.json", s.encode(s.rich_publication()))
        self.store.put(f"{DIRECTORY}/c-friday-comms.json", s.encode(s.friday_publication()))

    def admit(self, capsys: pytest.CaptureFixture[str]) -> str:
        code, out = run(
            capsys,
            "admit",
            "--consumer",
            "communications_evidence_v2",
            "--workspace",
            "mcp",
            "--path-prefix",
            DIRECTORY + "/",
            "--file-pattern",
            "*-comms.json",
        )
        assert code == cli.EXIT_OK, out
        return str(out["ingest_source_id"])


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any]]:
    code = cli.main([*EXPECT, *argv])
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = captured.out.splitlines()
    assert len(lines) == 1, captured.out
    return code, json.loads(lines[0])


def _content_strings() -> set[str]:
    found: set[str] = set()

    def walk(node: object, key: str | None) -> None:
        if isinstance(node, dict):
            for name, value in node.items():
                walk(value, name)
        elif isinstance(node, list):
            for value in node:
                walk(value, key)
        elif isinstance(node, str) and key in CONTENT_KEYS and len(node) >= 6:
            found.add(node)

    for builder in (s.lean_publication, s.rich_publication, s.friday_publication):
        walk(builder(), None)
    return found


# ---- parsing ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["admit", "--consumer", "communications_evidence_v2"],
        ["--expected-database", "x", "enable", "--source", "isrc_x"],
        ["--expected-alembic-head", HEAD, "enable", "--source", "isrc_x"],
        [*EXPECT, "enable"],
        [*EXPECT, "backfill", "--source", "isrc_x", "--file", "a", "--glob", "*"],
        [*EXPECT, "coverage", "--source", "isrc_x", "--from", "2026-11-01T00:00:00Z"],
        [*EXPECT, "admit", "--consumer", "nonsense", "--workspace", "mcp"],
        [*EXPECT, "purge"],
        [*EXPECT, "rederive", "--limit", "0"],
        [*EXPECT, "rederive", "--limit", "20001"],
        [*EXPECT, "rederive", "--limit", "many"],
        [*EXPECT, "measure-fts", "--limit", "0"],
        [*EXPECT, "rederive", "--prune-version", "comms_identifiers_v1"],
    ],
    ids=[
        "no-expectations",
        "no-head",
        "no-database",
        "no-source",
        "file-and-glob",
        "from-without-to",
        "unknown-consumer",
        "unknown-command",
        "rederive-limit-zero",
        "rederive-limit-above-maximum",
        "rederive-limit-not-integer",
        "measure-limit-zero",
        "no-prune-r4",
    ],
)
def test_usage_errors_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    scene = _Scene(monkeypatch)
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    assert raised.value.code == 2
    assert scene.engines_built == 0
    captured = capsys.readouterr()
    assert not any(part in captured.out + captured.err for part in DSN_PARTS)


def test_the_dsn_is_never_an_argument() -> None:
    options = {option for action in cli.build_parser()._actions for option in action.option_strings}
    assert not any("url" in option or "dsn" in option for option in options)


# ---- the expectations ------------------------------------------------------------


def test_a_mismatched_configured_database_refuses_before_an_engine(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = _Scene(monkeypatch)
    code = cli.main(
        ["--expected-database", "my_pa", "--expected-alembic-head", HEAD, "enable", "--source", "x"]
    )
    out = capsys.readouterr().out
    assert code == cli.EXIT_REFUSED
    assert json.loads(out) == {"command": "enable", "refused": "target_mismatch"}
    assert scene.engines_built == 0


@pytest.mark.parametrize(
    "engine",
    [
        _Engine(database="other_catalog"),
        _Engine(heads=["deadbeef0001"]),
        _Engine(heads=[]),
        _Engine(heads=[HEAD, "0123456789ab"]),
    ],
    ids=["catalog", "other-head", "no-head", "two-heads"],
)
def test_a_mismatched_connected_identity_refuses_before_any_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], engine: _Engine
) -> None:
    scene = _Scene(monkeypatch, engine)
    code, out = run(capsys, "aggregate", "--source", "isrc_x")
    assert (code, out) == (cli.EXIT_REFUSED, {"command": "aggregate", "refused": "target_mismatch"})
    assert scene.world.row_count() == 0
    assert engine.disposed


def test_the_dsn_never_appears_on_any_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sqlalchemy.exc import OperationalError

    scene = _Scene(monkeypatch)
    outputs: list[str] = []
    source = scene.admit(capsys)
    for argv in (
        ["enable", "--source", source],
        ["run-once", "--source", source],
        ["backfill", "--source", source, "--dry-run"],
        ["coverage", "--source", source],
        ["enable", "--source", "isrc_missing"],
    ):
        cli.main([*EXPECT, *argv])
        captured = capsys.readouterr()
        outputs.append(captured.out + captured.err)

    class Unreachable(_Engine):
        @contextmanager
        def connect(self) -> Iterator[_Connection]:
            raise OperationalError(DSN, {}, Exception(DSN))
            yield self.connection  # pragma: no cover

    scene.engine = Unreachable()
    assert cli.main([*EXPECT, "enable", "--source", source]) == cli.EXIT_REFUSED
    captured = capsys.readouterr()
    assert json.loads(captured.out)["refused"] == "database_unreachable"
    outputs.append(captured.out + captured.err)
    monkeypatch.setenv("MY_PA_CYCLE_SCHEDULER_TIMEZONE", "Mars/" + DSN)
    assert cli.main([*EXPECT, "enable", "--source", source]) == cli.EXIT_REFUSED
    captured = capsys.readouterr()
    assert json.loads(captured.out)["refused"] == "settings_invalid"
    outputs.append(captured.out + captured.err)
    for output in outputs:
        assert not any(part in output for part in DSN_PARTS), output


# ---- the commands ----------------------------------------------------------------


def test_admit_prints_the_source_id_and_refuses_a_second_admission(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = _Scene(monkeypatch)
    source = scene.admit(capsys)
    assert source.startswith("isrc_")
    with pytest.raises(AssertionError):
        scene.admit(capsys)  # the refusal is exit 1, not 0
    assert len(scene.world.sources) == 1


def test_a_lifecycle_refusal_is_its_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = _Scene(monkeypatch)
    source = scene.admit(capsys)
    assert run(capsys, "disable", "--source", source) == (
        cli.EXIT_OK,
        {"command": "disable", "enabled": False, "ingest_source_id": source},
    )
    assert run(capsys, "run-once", "--source", source) == (
        cli.EXIT_REFUSED,
        {"command": "run-once", "refused": "source_disabled"},
    )
    assert run(capsys, "backfill", "--source", source, "--file", "../escape-comms.json")[1] == {
        "command": "backfill",
        "refused": "path_outside_source",
    }
    assert run(capsys, "backfill", "--source", source, "--glob", "a/b")[1] == {
        "command": "backfill",
        "refused": "invalid_location",
    }
    assert run(capsys, "enable", "--source", "isrc_missing")[1] == {
        "command": "enable",
        "refused": "source_not_found",
    }


@pytest.mark.parametrize(
    "argv",
    [["run-once"], ["backfill"], ["backfill", "--file", "a-lean-comms.json"]],
    ids=["run-once", "backfill", "backfill-file"],
)
def test_a_held_poll_lock_refuses_lock_held_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    """F4: `run-once` and `backfill` take the poll's lock; held elsewhere, they refuse."""
    scene = _Scene(monkeypatch)
    source = scene.admit(capsys)
    scene.put_fixtures()
    scene.engine.connection.lock_free = False
    before = (scene.world.row_count(), list(scene.world.writes))
    command, *rest = argv
    assert run(capsys, command, "--source", source, *rest) == (
        cli.EXIT_REFUSED,
        {"command": command, "refused": "lock_held"},
    )
    assert scene.engine.connection.lock_calls == ["try"]
    assert (scene.world.row_count(), list(scene.world.writes)) == before


def test_a_free_poll_lock_is_taken_and_released_and_a_dry_run_takes_none(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = _Scene(monkeypatch)
    source = scene.admit(capsys)
    scene.put_fixtures()
    calls = scene.engine.connection.lock_calls
    scene.engine.connection.lock_free = False
    assert run(capsys, "backfill", "--source", source, "--dry-run")[0] == cli.EXIT_OK
    assert run(capsys, "coverage", "--source", source)[0] == cli.EXIT_OK
    assert calls == []
    scene.engine.connection.lock_free = True
    assert run(capsys, "backfill", "--source", source)[0] == cli.EXIT_OK
    assert calls == ["try", "unlock"]


class _Applying:
    """Records whether, and under which lock state, the CLI applied the meeting sync."""

    def __init__(self, connection: _Connection, counts: dict[str, int]) -> None:
        self.connection = connection
        self.counts_out = counts
        self.locks_when_called: list[list[str]] = []

    def apply_pending(self, principal_id: str) -> object:
        self.locks_when_called.append(list(self.connection.lock_calls))

        class _Report:
            counts = self.counts_out

        return _Report()


@pytest.mark.parametrize("command", [["run-once"], ["backfill"]])
def test_run_once_and_backfill_apply_the_meeting_sync_under_the_lock(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: list[str]
) -> None:
    """WP3b-S3: applied after the run, while the poll lock is still held; dry run applies none."""
    scene = _Scene(monkeypatch)
    source = scene.admit(capsys)
    scene.put_fixtures()
    applying = _Applying(scene.engine.connection, {"unapplied_awaiting_reconciliation": 3})
    monkeypatch.setattr(cli, "meeting_sync_applier", lambda *_a, **_k: applying)
    assert (
        run(capsys, "backfill", "--source", source, "--dry-run")[1].get("meeting_sync_apply")
        is None
    )
    assert applying.locks_when_called == []
    code, out = run(capsys, *command, "--source", source)
    assert out["meeting_sync_apply"] == {"unapplied_awaiting_reconciliation": 3}
    assert applying.locks_when_called == [["try"]]  # taken, not yet released
    assert code == cli.EXIT_OK or out["outcome"] != "completed"
    applying.counts_out = {"publications_failed": 1}
    code, out = run(capsys, *command, "--source", source)
    assert (code, out["meeting_sync_apply"]) == (
        cli.EXIT_RUN_INCOMPLETE,
        {"publications_failed": 1},
    )


@pytest.mark.parametrize("command", ["coverage", "aggregate"])
def test_reads_of_an_unknown_source_refuse_source_not_found(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    """F6: a read never answers an empty coverage for a source that does not exist."""
    scene = _Scene(monkeypatch)
    source = scene.admit(capsys)
    assert run(capsys, command, "--source", "isrc_missing0000") == (
        cli.EXIT_REFUSED,
        {"command": command, "refused": "source_not_found"},
    )
    if command == "aggregate":
        assert run(capsys, command, "--source", source, "--source", "isrc_missing0000")[1] == {
            "command": command,
            "refused": "source_not_found",
        }
    else:  # the aggregate's SQL reads run in tests/database (the fake engine has none)
        assert run(capsys, command, "--source", source)[0] == cli.EXIT_OK


def test_a_dry_run_writes_nothing_and_reports_counts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = _Scene(monkeypatch)
    source = scene.admit(capsys)
    scene.put_fixtures()
    before = (scene.world.row_count(), list(scene.world.writes))
    code, out = run(capsys, "backfill", "--source", source, "--dry-run")
    assert code == cli.EXIT_OK
    assert (out["dry_run"], out["run_id"], out["outcome"]) == (True, None, "completed")
    assert out["counts"]["snapshots_new"] == 3
    assert (scene.world.row_count(), list(scene.world.writes)) == before
    assert scene.stability.finished == {}
    assert scene.stability.observed == {}


def test_backfill_then_rerun_is_idempotent_and_selects_by_file_or_glob(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = _Scene(monkeypatch)
    source = scene.admit(capsys)
    scene.put_fixtures()
    code, one = run(capsys, "backfill", "--source", source, "--file", "a-lean-comms.json")
    assert (code, one["counts"]["snapshots_ingested"], one["counts"]["snapshots_seen"]) == (
        cli.EXIT_OK,
        1,
        1,
    )
    code, glob = run(capsys, "backfill", "--source", source, "--glob", "b-*")
    assert (glob["counts"]["snapshots_seen"], glob["counts"]["snapshots_ingested"]) == (1, 1)
    code, rest = run(capsys, "backfill", "--source", source)
    assert rest["counts"]["snapshots_already_known"] == 2
    assert rest["counts"]["snapshots_ingested"] == 1
    rows = scene.world.row_count()
    code, again = run(capsys, "backfill", "--source", source)
    assert again["counts"]["snapshots_ingested"] == 0
    assert again["counts"]["snapshots_already_known"] == 3
    assert scene.world.row_count() == rows + 1 + 3  # one run row, three run links


def test_output_carries_no_fixture_content(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = _Scene(monkeypatch)
    source = scene.admit(capsys)
    scene.put_fixtures()
    texts: list[str] = []
    for argv in (
        ["backfill", "--source", source, "--dry-run"],
        ["backfill", "--source", source],
        ["run-once", "--source", source],
        ["coverage", "--source", source],
        [
            "coverage",
            "--source",
            source,
            "--from",
            "2026-11-01T00:00:00Z",
            "--to",
            "2026-11-20T00:00:00Z",
        ],
    ):
        code = cli.main([*EXPECT, *argv])
        assert code == cli.EXIT_OK
        texts.append(capsys.readouterr().out)
    forbidden = _content_strings()
    assert len(forbidden) > 20  # the check decides something
    for text in texts:
        leaked = sorted(value for value in forbidden if value in text)
        assert not leaked, leaked
        assert DIRECTORY not in text
        assert "comms.json" not in text


def test_coverage_reports_intervals_gaps_freshness_and_the_rolling_window(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = _Scene(monkeypatch)
    source = scene.admit(capsys)
    scene.put_fixtures()
    run(capsys, "backfill", "--source", source)
    code, out = run(
        capsys,
        "coverage",
        "--source",
        source,
        "--from",
        "2026-11-01T00:00:00Z",
        "--to",
        "2026-11-20T00:00:00Z",
    )
    assert code == cli.EXIT_OK
    assert out["snapshots"] == 3
    assert out["interval_count"] == len(out["intervals"]) >= 1
    assert out["gap_count"] == out["interval_count"] - 1
    assert set(out["rolling_30d"]) == {
        "start",
        "end",
        "state",
        "covered_seconds",
        "gap_count",
        "gap_seconds",
    }
    assert out["range"]["state"] in {"complete", "partial", "none"}
    assert out["range"]["start"] == "2026-11-01T00:00:00Z"
    assert run(
        capsys, "coverage", "--source", source, "--from", "2026-11-20T00:00:00Z", "--to", "x"
    )[1] == {"command": "coverage", "refused": "invalid_range"}


def test_coverage_of_an_admitted_source_with_no_snapshot_prints_rolling_none(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """W1 nit: nothing ingested, so the rolling read has no anchor and prints `none`."""
    scene = _Scene(monkeypatch)
    source = scene.admit(capsys)
    code, out = run(capsys, "coverage", "--source", source)
    assert code == cli.EXIT_OK
    assert out["snapshots"] == 0
    assert out["rolling_30d"] == {
        "start": None,
        "end": None,
        "state": "none",
        "covered_seconds": 0,
        "gap_count": 0,
        "gap_seconds": 0,
    }


# ---- the governed rules (operator-commands EXEMPT entry) ---------------------------


def _tree() -> ast.Module:
    return ast.parse(COMMAND.read_text(encoding="utf-8"))


def test_the_command_names_no_capability_and_builds_no_service() -> None:
    names: set[str] = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.rsplit(".", 1)[-1])
    assert "Capability" not in names
    assert "ApplicationService" not in names
    assert "AuditEvent" not in names


def test_the_command_imports_only_the_counts_only_reads_from_persistence() -> None:
    named: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            if node.module.startswith("my_pa.infrastructure.persistence"):
                named.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    assert named == {
        "communications_aggregate",
        "communications_fts_measurement",
        "ingest_aggregate",
    }
    assert not any(module.startswith("my_pa.adapters") for module in modules)
    application = {module for module in modules if module.startswith("my_pa.application")}
    assert application == {"my_pa.application.ingestion"}


# ---- rederive and measure-fts (WP4-S3) ----------------------------------------------


def _v1_backfill(
    scene: _Scene, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> str:
    """Admit and backfill the fixtures with the v1 text and identifiers (a WP3a database)."""
    source = scene.admit(capsys)
    scene.put_fixtures()
    with monkeypatch.context() as patch:
        patch.setattr(ingest_module, "derive_search_text", derive_search_text_v1)
        patch.setattr(ingest_module, "IDENTIFIER_VERSION", IDENTIFIER_VERSION_V1)
        assert run(capsys, "backfill", "--source", source)[0] == cli.EXIT_OK
    return source


def test_rederive_under_the_poll_lock_prints_closed_counts_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = _Scene(monkeypatch)
    source = _v1_backfill(scene, capsys, monkeypatch)
    calls = scene.engine.connection.lock_calls
    calls.clear()
    code, out = run(capsys, "rederive", "--source", source, "--limit", "2")
    assert code == cli.EXIT_OK
    assert calls == ["try", "unlock"]
    assert set(out) == {
        "command",
        "ingest_source_id",
        "dry_run",
        "search_text_version",
        "identifier_version",
        "counts",
    }
    assert (out["command"], out["dry_run"], out["ingest_source_id"]) == ("rederive", False, source)
    assert (out["search_text_version"], out["identifier_version"]) == (
        "comms_search_text_v2",
        "comms_identifiers_v2",
    )
    assert set(out["counts"]) == set(REDERIVE_COUNT_KEYS)
    assert all(type(value) is int for value in out["counts"].values())
    assert out["counts"]["messages_checked"] == 2
    assert out["counts"]["messages_deferred"] > 0
    # The rest, unscoped, then nothing left.
    code, rest = run(capsys, "rederive")
    assert (code, rest["ingest_source_id"], rest["counts"]["messages_deferred"]) == (
        cli.EXIT_OK,
        None,
        0,
    )
    assert run(capsys, "rederive")[1]["counts"]["messages_checked"] == 0
    raw = json.dumps([out, rest])
    leaked = sorted(value for value in _content_strings() if value in raw)
    assert leaked == []
    assert not any(part in raw for part in DSN_PARTS)
    assert "Daily Intelligence" not in raw


def test_rederive_refuses_lock_held_and_a_dry_run_takes_no_lock(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = _Scene(monkeypatch)
    _v1_backfill(scene, capsys, monkeypatch)
    calls = scene.engine.connection.lock_calls
    calls.clear()
    scene.engine.connection.lock_free = False
    before = (scene.world.row_count(), list(scene.world.writes))
    assert run(capsys, "rederive") == (
        cli.EXIT_REFUSED,
        {"command": "rederive", "refused": "lock_held"},
    )
    assert calls == ["try"]
    code, dry = run(capsys, "rederive", "--dry-run")
    assert (code, dry["dry_run"]) == (cli.EXIT_OK, True)
    assert dry["counts"]["messages_due_text"] > 0
    assert calls == ["try"]  # the dry run took no lock
    assert (scene.world.row_count(), list(scene.world.writes)) == before


def test_rederive_exits_3_when_a_group_failed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = _Scene(monkeypatch)
    _v1_backfill(scene, capsys, monkeypatch)
    scene.world.fail_on.add("update_message_projection")
    code, out = run(capsys, "rederive")
    assert code == cli.EXIT_RUN_INCOMPLETE
    assert out["counts"]["messages_failed"] >= 1


@pytest.mark.parametrize("command", ["rederive", "measure-fts"])
def test_an_unknown_source_refuses_source_not_found(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    _Scene(monkeypatch)
    assert run(capsys, command, "--source", "isrc_doesnotexist0000") == (
        cli.EXIT_REFUSED,
        {"command": command, "refused": "source_not_found"},
    )


def test_measure_fts_prints_the_measurement_under_its_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The SQL is the database tier's; here, the wiring: version, scope, limit, shape."""
    _Scene(monkeypatch)
    seen: dict[str, object] = {}

    def measured(_connection: object, principal_id: str, **kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return {"messages_measured": 0, "classes": {}}

    monkeypatch.setattr(cli, "communications_fts_measurement", measured)
    code, out = run(capsys, "measure-fts", "--limit", "7")
    assert code == cli.EXIT_OK
    assert out == {
        "command": "measure-fts",
        "ingest_source_id": None,
        "messages_measured": 0,
        "classes": {},
    }
    assert seen == {
        "identifiers_version": "comms_identifiers_v2",
        "ingest_source_id": None,
        "limit": 7,
    }


@pytest.mark.parametrize(
    ("sqlstate", "refused"),
    [("57014", "statement_timeout"), ("08006", "database_unreachable")],
)
def test_measure_fts_maps_a_statement_timeout_to_its_own_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sqlstate: str,
    refused: str,
) -> None:
    """WP4-R1 F7: a cancelled measurement is not an unreachable database."""
    _Scene(monkeypatch)

    class _DriverError(Exception):
        pass

    orig = _DriverError("cancelled")
    orig.sqlstate = sqlstate  # type: ignore[attr-defined]

    def cancelled(_connection: object, _principal_id: str, **_kwargs: object) -> object:
        raise OperationalError("SELECT", {}, orig)

    monkeypatch.setattr(cli, "communications_fts_measurement", cancelled)
    assert run(capsys, "measure-fts") == (
        cli.EXIT_REFUSED,
        {"command": "measure-fts", "refused": refused},
    )
