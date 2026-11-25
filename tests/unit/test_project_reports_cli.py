"""`apps/cli/project_reports.py`, the bindings operator command (WP3P-S4), FAST tier.

With fakes: the lifecycle rows are the in-memory `IngestWorld`, the Projects
and the project-report rows the general `World`, the workspace the in-memory
`FakeStore` (with directories), and the engine answers only the identity and
advisory-lock queries. Proved here: argument parsing (required expectations,
file; no `--reason`, Manager ruling on S4); the expectation refusals (before an engine is
built when the configured name differs, on the live connection when the
catalog or the Alembic head differs); the database URL never appearing in any
output; the closed exit codes; the JSON shape of `check` and `apply`; a
second apply writing nothing; the refusal codes; and output that carries
counts, codes and project numbers only -- no folder, path, file name, slug or
filter text of the fixture. The end-to-end run on PostgreSQL is
`tests/database/test_project_reports_bindings.py`.

This module also governs the command for
`tests/architecture/test_operator_commands_are_not_capabilities.py` (it is
`EXEMPT` there because it reaches `my_pa.application`): it names no
`Capability`, builds no `ApplicationService`, writes no `AuditEvent`, imports
nothing from persistence or the adapters, and reaches only the ingestion
lifecycle's refusals and the bindings service in the application layer.

Every identifier, folder, number and text here is synthetic.
"""

from __future__ import annotations

import ast
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli import project_reports as cli

from my_pa.application.ingestion import IngestionLifecycle
from my_pa.application.project_reports_bindings import ProjectReportBindings
from my_pa.bootstrap.gateway import local_principal
from my_pa.bootstrap.project_reports import (
    PROJECT_REPORTS_WORKSPACE_ID,
    poll_lock,
    project_reports_handler,
)
from my_pa.contracts.ports import FileWorkspaceEntry, IngestConsumer
from my_pa.domain.files.errors import FilesRefusal
from my_pa.domain.files.versions import EntryKind
from my_pa.domain.files.vocabulary import FilesReason
from my_pa.domain.situation.situation import Project, ProjectState
from tests.conftest import World
from tests.unit.communications_ingest_fakes import FakeStore, IngestUnitOfWork, IngestWorld

ROOT: Final = Path(__file__).resolve().parents[2]
COMMAND: Final = ROOT / "apps" / "cli" / "project_reports.py"
DSN: Final = "postgresql+psycopg://dsnuser:dsnsecret@dsnhost.invalid:6543/dsncatalog"
DSN_PARTS: Final = ("dsnuser", "dsnsecret", "dsnhost", "6543", "postgresql+psycopg")
#: A synthetic revision, compared with the fake live `alembic_version` row.
HEAD: Final = "feedfacecafe"
EXPECT: Final = ["--expected-database", "dsncatalog", "--expected-alembic-head", HEAD]
WHEN: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)

EXPORT_ROOT: Final = "Synthetic Area"
FOLDER_A: Final = f"{EXPORT_ROOT}/Alpha Synth/REPORTS/EXPORTS"
FOLDER_B: Final = f"{EXPORT_ROOT}/Bravo Synth/REPORTS/EXPORTS"
#: A CSV folder no binding names (counted, never printed).
FOLDER_UNBOUND: Final = f"{EXPORT_ROOT}/Charlie Synth/REPORTS/EXPORTS"
PROJECT_A: Final = "prj_synclialpha01"
PROJECT_B: Final = "prj_syncli0bravo1"
NUMBER_A: Final = "SYN-7101"
NUMBER_B: Final = "SYN-7102"
SLUG: Final = "synthetic-saved-report-slug"
FILTER: Final = "Synthetic filter text: open items only"
FILE_NAME: Final = "20261120-synthetic-saved-report-slug.csv"


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


class _DirectoryStore(FakeStore):
    """`FakeStore` whose `stat` also answers the directories its files imply."""

    def stat(self, path: str, *, include_sha256: bool = False) -> FileWorkspaceEntry:
        if path in self.files:
            return super().stat(path, include_sha256=include_sha256)
        self.calls.append("stat")
        if not any(name.startswith(path + "/") for name in self.files):
            raise FilesRefusal("path", FilesReason.NOT_FOUND)
        return FileWorkspaceEntry(
            path=path,
            name=path.rsplit("/", 1)[-1],
            kind=EntryKind.DIRECTORY,
            size=None,
            mtime_ns=0,
            version="fv1_dir",
        )


class _Scene:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, engine: _Engine | None = None) -> None:
        for key in [key for key in os.environ if key.startswith("MY_PA_")]:
            monkeypatch.delenv(key)
        monkeypatch.setenv("MY_PA_DATABASE_URL", DSN)
        self.principal = local_principal().principal_id
        self.ingest = IngestWorld()
        self.world = World()
        for project_id, number in ((PROJECT_A, NUMBER_A), (PROJECT_B, NUMBER_B)):
            self.world.projects.append(
                Project(
                    project_id=project_id,
                    principal_id=self.principal,
                    name="Synthetic project",
                    state=ProjectState.ACTIVE,
                    opened_at=WHEN,
                    created_at=WHEN,
                    updated_at=WHEN,
                    project_number=number,
                )
            )
        self.store = _DirectoryStore()
        for folder in (FOLDER_A, FOLDER_B, FOLDER_UNBOUND):
            self.store.put(f"{folder}/{FILE_NAME}", b"Synthetic,Header\n")
        self.engine = engine or _Engine()
        self.engines_built = 0

        def build(*_args: object, **kwargs: object) -> _Engine:
            assert kwargs.get("statement_timeout_ms") == cli.STATEMENT_TIMEOUT_MS
            self.engines_built += 1
            return self.engine

        monkeypatch.setattr(cli, "create_database_engine", build)
        monkeypatch.setattr(cli, "bindings_service", self._service)

    def _unit(self) -> IngestUnitOfWork:
        return IngestUnitOfWork(self.ingest, meetings=self.world)

    def _stores(self, workspace_id: str) -> FakeStore:
        if workspace_id != PROJECT_REPORTS_WORKSPACE_ID:
            raise LookupError(workspace_id)
        return self.store

    def _service(self, _settings: object, engine: _Engine) -> ProjectReportBindings:
        lifecycle = IngestionLifecycle(
            unit_of_work=self._unit, stores=self._stores, handlers=[project_reports_handler()]
        )
        return ProjectReportBindings(
            unit_of_work=self._unit,
            lifecycle=lifecycle,
            stores=self._stores,
            workspace_id=PROJECT_REPORTS_WORKSPACE_ID,
            lock=poll_lock(engine),  # type: ignore[arg-type]
        )

    def rows(self) -> tuple[int, ...]:
        reports = self.world.project_reports
        return (
            len(self.ingest.sources),
            len(reports.revisions),
            len(reports.declarations),
            len(reports.bindings),
        )


def _file(tmp_path: Path, document: object, name: str = "bindings.json") -> str:
    path = tmp_path / name
    path.write_text(document if isinstance(document, str) else json.dumps(document))
    return str(path)


def _document(*bindings: dict[str, object]) -> dict[str, object]:
    return {
        "schema": "my_pa_project_report_bindings_v1",
        "workspace_id": "mcp",
        "export_root": EXPORT_ROOT,
        "bindings": list(bindings),
    }


def _a() -> dict[str, object]:
    return {
        "folder": FOLDER_A,
        "project_id": PROJECT_A,
        "project_number": NUMBER_A,
        "reports": [{"slug": SLUG, "filter": FILTER}],
    }


def _b() -> dict[str, object]:
    return {"folder": FOLDER_B, "project_id": PROJECT_B, "project_number": NUMBER_B}


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any], str]:
    code = cli.main([*EXPECT, *argv])
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = captured.out.splitlines()
    assert len(lines) == 1, captured.out
    return code, json.loads(lines[0]), captured.out


# ---- parsing ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["bindings", "check", "--file", "f.json"],
        [*EXPECT, "bindings"],
        [*EXPECT, "bindings", "check"],
        [*EXPECT, "bindings", "apply"],
        [*EXPECT, "bindings", "apply", "--file", "f.json", "--reason", "initial"],
        [*EXPECT, "bindings", "purge", "--file", "f.json"],
        [*EXPECT, "run-once"],
    ],
    ids=[
        "no-expectations",
        "no-action",
        "no-file",
        "apply-without-file",
        "a-reason-is-no-argument",
        "unknown-action",
        "run-once-without-source",
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
    options: set[str] = set()
    pending = [cli.build_parser()]
    while pending:
        parser = pending.pop()
        for action in parser._actions:
            options.update(action.option_strings)
            choices = getattr(action, "choices", None)
            if isinstance(choices, dict):
                pending.extend(choices.values())
    assert "--file" in options
    assert not any("url" in option or "dsn" in option for option in options)


# ---- the expectations ------------------------------------------------------------


def test_a_mismatched_configured_database_refuses_before_an_engine(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    scene = _Scene(monkeypatch)
    path = _file(tmp_path, _document(_a()))
    code = cli.main(
        [
            "--expected-database",
            "my_pa",
            "--expected-alembic-head",
            HEAD,
            "bindings",
            "check",
            "--file",
            path,
        ]
    )
    out = capsys.readouterr().out
    assert code == cli.EXIT_REFUSED
    assert json.loads(out) == {"command": "bindings_check", "refused": "target_mismatch"}
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
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    engine: _Engine,
) -> None:
    scene = _Scene(monkeypatch, engine)
    path = _file(tmp_path, _document(_a()))
    code, out, _ = run(capsys, "bindings", "apply", "--file", path)
    assert (code, out) == (
        cli.EXIT_REFUSED,
        {"command": "bindings_apply", "refused": "target_mismatch"},
    )
    assert scene.rows() == (0, 0, 0, 0)
    assert scene.store.calls == []
    assert engine.disposed


def test_the_dsn_never_appears_on_any_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from sqlalchemy.exc import OperationalError

    scene = _Scene(monkeypatch)
    path = _file(tmp_path, _document(_a()))
    outputs: list[str] = []
    for argv in (
        ["bindings", "check", "--file", path],
        ["bindings", "apply", "--file", path],
        ["bindings", "check", "--file", str(tmp_path / "missing.json")],
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
    assert cli.main([*EXPECT, "bindings", "check", "--file", path]) == cli.EXIT_REFUSED
    captured = capsys.readouterr()
    assert json.loads(captured.out)["refused"] == "database_unreachable"
    outputs.append(captured.out + captured.err)
    monkeypatch.setenv("MY_PA_CYCLE_SCHEDULER_TIMEZONE", "Mars/" + DSN)
    assert cli.main([*EXPECT, "bindings", "check", "--file", path]) == cli.EXIT_REFUSED
    captured = capsys.readouterr()
    assert json.loads(captured.out)["refused"] == "settings_invalid"
    outputs.append(captured.out + captured.err)
    for output in outputs:
        assert not any(part in output for part in DSN_PARTS), output


# ---- the commands ----------------------------------------------------------------


def test_check_prints_the_diff_and_the_unbound_folders_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    scene = _Scene(monkeypatch)
    path = _file(tmp_path, _document(_a(), _b()))
    code, out, _ = run(capsys, "bindings", "check", "--file", path)
    assert code == cli.EXIT_OK
    assert out == {
        "command": "bindings_check",
        "applied": False,
        "counts": {
            "add": 2,
            "correction": 0,
            "filter_update": 0,
            "retire": 0,
            "unchanged": 0,
            "filter_declarations": 1,
        },
        "project_numbers": {
            "add": [NUMBER_A, NUMBER_B],
            "correction": [],
            "filter_update": [],
            "retire": [],
        },
        "unbound_folders": 1,
        "unbound_folder_depth": 3,
        "unbound_listing_truncated": False,
    }
    assert scene.rows() == (0, 0, 0, 0)
    assert scene.engine.connection.lock_calls == []  # check takes no lock
    assert set(scene.store.calls) <= {"stat", "list_directory"}


def test_apply_writes_once_then_finds_nothing_to_change(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    scene = _Scene(monkeypatch)
    path = _file(tmp_path, _document(_a(), _b()))
    code, out, _ = run(capsys, "bindings", "apply", "--file", path)
    assert code == cli.EXIT_OK
    assert out["applied"] is True
    assert "reason" not in out  # each revision records its own change kind's reason
    assert out["counts"]["add"] == 2
    assert out["writes"] == {
        "revisions": 2,
        "filter_declarations": 1,
        "sources_admitted": 2,
        "sources_enabled": 0,
        "sources_disabled": 0,
    }
    assert "unbound_folders" not in out
    assert scene.rows() == (2, 2, 1, 2)
    assert scene.engine.connection.lock_calls == ["try", "unlock"]
    assert {s.consumer for s in scene.ingest.sources.values()} == {IngestConsumer.PULSE_CSV_EXPORT}
    code, again, _ = run(capsys, "bindings", "apply", "--file", path)
    assert code == cli.EXIT_OK
    assert again["counts"]["unchanged"] == 2
    assert set(again["writes"].values()) == {0}
    assert scene.rows() == (2, 2, 1, 2)


@pytest.mark.parametrize(
    ("document", "code"),
    [
        ('{"schema": "a", "schema": "b"}', "duplicate_json_key"),
        (
            json.dumps(_document(_a())).replace(
                '"schema": ', '"schema": "my_pa_project_report_bindings_v1", "schema": ', 1
            ),
            "duplicate_json_key",
        ),
        ({**_document(_a()), "extra": True}, "unknown_key"),
        (_document({**_a(), "project_id": "prj_synclimissing"}), "project_not_found"),
        (_document({**_a(), "project_number": "SYN-0000"}), "project_number_mismatch"),
        (
            _document({**_a(), "folder": f"{EXPORT_ROOT}/Missing Synth/REPORTS"}),
            "folder_not_found",
        ),
        (_document(_a(), {**_b(), "folder": FOLDER_A + "/Nested"}), "folder_nested"),
        ("not json", "schema_invalid"),
    ],
    ids=[
        "duplicate-key",
        "duplicate-key-otherwise-valid",
        "unknown-key",
        "project-not-found",
        "number-mismatch",
        "folder-not-found",
        "folder-nested",
        "not-json",
    ],
)
def test_a_refused_file_exits_1_with_its_code_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    document: object,
    code: str,
) -> None:
    scene = _Scene(monkeypatch)
    path = _file(tmp_path, document)
    for action in (["check"], ["apply"]):
        exit_code, out, _ = run(capsys, "bindings", action[0], "--file", path, *action[1:])
        assert (exit_code, out) == (
            cli.EXIT_REFUSED,
            {"command": f"bindings_{action[0]}", "refused": code},
        )
    assert scene.rows() == (0, 0, 0, 0)


def test_an_unreadable_file_is_file_unreadable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _Scene(monkeypatch)
    big = tmp_path / "big.json"
    big.write_bytes(b" " * (cli.MAX_FILE_BYTES + 1))
    for path in (str(tmp_path / "missing.json"), str(big), str(tmp_path)):
        code, out, raw = run(capsys, "bindings", "check", "--file", path)
        assert (code, out) == (
            cli.EXIT_REFUSED,
            {"command": "bindings_check", "refused": "file_unreadable"},
        )
        assert str(tmp_path) not in raw


def test_a_held_poll_lock_refuses_lock_held_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    scene = _Scene(monkeypatch)
    scene.engine.connection.lock_free = False
    path = _file(tmp_path, _document(_a()))
    code, out, _ = run(capsys, "bindings", "apply", "--file", path)
    assert (code, out) == (
        cli.EXIT_REFUSED,
        {"command": "bindings_apply", "refused": "lock_held"},
    )
    assert scene.engine.connection.lock_calls == ["try"]
    assert scene.rows() == (0, 0, 0, 0)
    # `check` writes nothing and takes no lock.
    assert run(capsys, "bindings", "check", "--file", path)[0] == cli.EXIT_OK


def test_output_is_counts_codes_and_project_numbers_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    scene = _Scene(monkeypatch)
    first = _file(tmp_path, _document(_a(), _b()), "first.json")
    second = _file(
        tmp_path,
        _document({**_a(), "reports": [{"slug": SLUG, "filter": FILTER + " (revised)"}]}),
        "second.json",
    )
    texts = [
        run(capsys, "bindings", "check", "--file", first)[2],
        run(capsys, "bindings", "apply", "--file", first)[2],
        run(capsys, "bindings", "check", "--file", second)[2],
        run(capsys, "bindings", "apply", "--file", second)[2],
    ]
    final = json.loads(texts[-1])
    assert final["project_numbers"]["filter_update"] == [NUMBER_A]
    assert final["project_numbers"]["retire"] == [NUMBER_B]
    assert scene.rows()[0] == 2
    forbidden = (
        EXPORT_ROOT,
        "Alpha Synth",
        "Bravo Synth",
        "Charlie Synth",
        "REPORTS",
        "EXPORTS",
        SLUG,
        FILTER,
        FILE_NAME,
        ".csv",
        ".json",
        str(tmp_path),
        PROJECT_A,
        PROJECT_B,
    )
    for text in texts:
        leaked = [value for value in forbidden if value in text]
        assert not leaked, leaked


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


def test_the_command_imports_nothing_from_persistence_or_the_adapters() -> None:
    modules: set[str] = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    assert not any(module.startswith("my_pa.infrastructure.persistence") for module in modules)
    assert not any(module.startswith("my_pa.adapters") for module in modules)
    application = {module for module in modules if module.startswith("my_pa.application")}
    assert application == {
        "my_pa.application.ingestion",
        "my_pa.application.project_reports_bindings",
        "my_pa.application.project_reports_coverage",
        "my_pa.application.project_reports_ingest",
        "my_pa.application.project_reports_rederive",
    }
