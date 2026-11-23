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

from my_pa.application.communications_ingest import CommunicationsCoverageReader
from my_pa.application.ingestion import IngestionLifecycle, StabilityMemory
from my_pa.bootstrap.communications_ingest import communications_handler
from tests.fixtures.communications_evidence import synthetic as s
from tests.unit.communications_ingest_fakes import FakeStore, IngestWorld, unit_of_work_factory

ROOT: Final = Path(__file__).resolve().parents[2]
COMMAND: Final = ROOT / "apps" / "cli" / "communications_ingest.py"
DIRECTORY: Final = "My PA/Daily Intelligence/communications"
#: A URL whose every part is distinctive, so an echo of any part is caught.
DSN: Final = "postgresql+psycopg://dsnuser:dsnsecret@dsnhost.invalid:6543/dsncatalog"
DSN_PARTS: Final = ("dsnuser", "dsnsecret", "dsnhost", "6543", "postgresql+psycopg")
HEAD: Final = "52a829ef718a"
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

    def execute(self, statement: object) -> _Result:
        sql = str(statement)
        if "current_database" in sql:
            return _Result([self.database])
        if "alembic_version" in sql:
            return _Result(list(self.heads))
        raise AssertionError("the fake engine answers only the identity queries")


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
        _Engine(heads=["6418b57081c3"]),
        _Engine(heads=[]),
        _Engine(heads=[HEAD, "6418b57081c3"]),
    ],
    ids=["catalog", "older-head", "no-head", "two-heads"],
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


def test_the_command_imports_only_the_aggregate_reads_from_persistence() -> None:
    named: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            if node.module.startswith("my_pa.infrastructure.persistence"):
                named.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    assert named == {"communications_aggregate", "ingest_aggregate"}
    assert not any(module.startswith("my_pa.adapters") for module in modules)
    application = {module for module in modules if module.startswith("my_pa.application")}
    assert application == {"my_pa.application.ingestion"}
