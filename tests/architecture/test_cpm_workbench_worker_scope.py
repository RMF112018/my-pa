"""What the S5b-2 schedule worker may load and say (worker contract 3.3, 3.4.2, 3.15).

The parser child's import closure holds no network or database module, the
worker parent never loads PDFium, and the new worker modules neither log nor
print: the only bytes any of them writes are the child's one frame on its
`stdout`. The closures are measured in fresh isolated interpreters, so nothing
this test process has already imported can hide or fake a module.

The `schedule` worker plane refuses to run (exit 2, before an engine is built)
while `MY_PA_SCHEDULE_ENABLED` is off or with a lease shorter than 300 s.

FAST: no database, no PDF; two short subprocesses.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[2]
SRC: Final = ROOT / "src"
JOBS: Final = SRC / "my_pa/infrastructure/jobs"
HANDLER: Final = JOBS / "schedule.py"
PARENT: Final = JOBS / "schedule_parser_process.py"
CHILD: Final = JOBS / "schedule_parser_child.py"
WORKER_MODULES: Final = (HANDLER, PARENT, CHILD)

#: No network, TLS, HTTP or database client, and no application layer, may be
#: reachable from the child (contract 3.4.2: `urllib.parse` only).
_FORBIDDEN_IN_CHILD: Final = (
    "sqlalchemy",
    "psycopg",
    "psycopg2",
    "socket",
    "_socket",
    "ssl",
    "_ssl",
    "http",
    "urllib.request",
    "requests",
    "httpx",
    "asyncio",
    "my_pa.application",
    "my_pa.adapters",
    "my_pa.bootstrap",
    "my_pa.contracts",
    "my_pa.infrastructure.persistence",
    "my_pa.infrastructure.providers",
)
_PDFIUM: Final = ("pypdfium2", "my_pa.infrastructure.schedule")


def _modules_after(statement: str) -> set[str]:
    """`sys.modules` of a fresh isolated interpreter after `statement`."""
    script = (
        "import sys, json; sys.path.insert(0, sys.argv[1])\n"
        f"{statement}\n"
        "sys.stdout.write(json.dumps(sorted(sys.modules)))"
    )
    completed = subprocess.run(  # noqa: S603 - this interpreter, a fixed script
        [sys.executable, "-I", "-B", "-c", script, str(SRC)],
        capture_output=True,
        check=True,
        timeout=120,
        env={},
        cwd="/",
    )
    return set(json.loads(completed.stdout))


def _reached(modules: set[str], prefix: str) -> list[str]:
    return sorted(name for name in modules if name == prefix or name.startswith(prefix + "."))


def test_child_import_closure_has_no_network_or_database_module() -> None:
    """Everything the child imports: its module, the parser package and the domain."""
    modules = _modules_after(
        "from my_pa.infrastructure.jobs import schedule_parser_child\n"
        "import my_pa.infrastructure.schedule, my_pa.domain.schedule"
    )
    assert "pypdfium2" in modules, "the closure was not measured after the parser import"
    for forbidden in _FORBIDDEN_IN_CHILD:
        assert not _reached(modules, forbidden), forbidden


def test_the_worker_parent_never_imports_pdfium() -> None:
    """The handler and the parent-side process module leave PDFium unloaded (S5a U-12)."""
    modules = _modules_after(
        "import my_pa.infrastructure.jobs.schedule, "
        "my_pa.infrastructure.jobs.schedule_parser_process"
    )
    assert "my_pa.infrastructure.jobs.schedule" in modules
    for name in _PDFIUM:
        assert not _reached(modules, name), name
    for path in (HANDLER, PARENT):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        for name in imported:
            assert not name.startswith(_PDFIUM), f"{path.name} imports {name}"


def _calls(tree: ast.AST) -> list[str]:
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.append(func.id)
            elif isinstance(func, ast.Attribute):
                names.append(ast.unparse(func))
    return names


def test_new_worker_modules_neither_log_nor_print() -> None:
    """No `print`, `logging`, `warnings` or stream write but the child's one frame."""
    for path in WORKER_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert not imported & {"logging", "warnings", "traceback"}, path.name
        calls = _calls(tree)
        assert "print" not in calls, path.name
        writes = [call for call in calls if call.startswith(("sys.stdout", "sys.stderr"))]
        if path == CHILD:
            assert writes == ["sys.stdout.buffer.write", "sys.stdout.buffer.flush"], writes
        else:
            assert writes == [], f"{path.name}: {writes}"


# ---- the `schedule` plane's own refusals (contract 3.1, 3.2; I7-B) ---------------


class _EngineBuiltError(Exception):
    """Raised by the stand-in engine factory: the refusal did not come first."""


def _run_worker(monkeypatch: pytest.MonkeyPatch, *, enabled: bool | None, argv: list[str]) -> int:
    """`apps/worker.py` `main` with a synthetic environment and no engine factory."""
    from apps import worker as worker_app

    for key in [key for key in os.environ if key.startswith("MY_PA_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://someone@db.invalid:5432/x")
    if enabled is not None:
        monkeypatch.setenv("MY_PA_SCHEDULE_ENABLED", "true" if enabled else "false")

    def no_engine(*_args: object, **_kwargs: object) -> object:
        raise _EngineBuiltError

    monkeypatch.setattr(worker_app, "create_database_engine", no_engine)
    return worker_app.main(argv)


@pytest.mark.parametrize("enabled", [None, False], ids=["unset", "false"])
def test_worker_refuses_the_schedule_plane_while_disabled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], enabled: bool | None
) -> None:
    """Exit 2 with one message, before an engine, a claim or a heartbeat."""
    code = _run_worker(monkeypatch, enabled=enabled, argv=["run", "--plane", "schedule", "--once"])
    assert code == 2
    assert capsys.readouterr().out == "plane schedule disabled\n"


def test_worker_refuses_a_lease_shorter_than_three_hundred_seconds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """299 s is refused before an engine; 300 s passes the refusal (the engine is reached)."""
    argv = ["run", "--plane", "schedule", "--once", "--lease-seconds"]
    assert _run_worker(monkeypatch, enabled=True, argv=[*argv, "299"]) == 2
    assert capsys.readouterr().out == "plane schedule requires --lease-seconds >= 300\n"
    with pytest.raises(_EngineBuiltError):
        _run_worker(monkeypatch, enabled=True, argv=[*argv, "300"])
    # The other planes keep their own lease rules: a short lease is not refused there.
    with pytest.raises(_EngineBuiltError):
        _run_worker(monkeypatch, enabled=False, argv=["run", "--plane", "capture", *argv[3:], "60"])


# ---- no baseline is ever derived (contract 3.11; I7-C) -------------------------------

#: The modules that read and compare publications: neither may choose a baseline.
BASELINE_FREE: Final = (
    SRC / "my_pa/application/schedules.py",
    SRC / "my_pa/domain/schedule/compare.py",
)


def test_no_baseline_is_derived() -> None:
    """R2 section 30: an update is never a baseline, and nothing infers one.

    The role is an explicit command field with no default (the command test
    proves that); here, neither the read service nor the delta holds a
    `"baseline"` literal to default to, a `BASELINE` role member to choose, or
    a `current_baseline` / `previous` symbol to look one up by. A comparison
    pair is always the caller's two ids.
    """
    for path in BASELINE_FREE:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and node.value == "baseline"
        ]
        assert not literals, f"{path.name} holds a 'baseline' literal"
        identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        identifiers |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        identifiers |= {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef)
        }
        assert "BASELINE" not in identifiers, f"{path.name} names the baseline role"
        derived = sorted(
            name
            for name in identifiers
            if "current_baseline" in name.lower() or "previous" in name.lower()
        )
        assert not derived, f"{path.name} derives a pair: {derived}"


# ---- the S5b-2 contract's crosswalk is real (contract sections 6-8; I7-D) ---------------

CONTRACT: Final = ROOT / "docs/architecture/cpm-workbench-worker-capabilities-contract.md"
#: A backticked test function name, optionally with a parameter id, closed by its backtick.
_NAMED_TEST: Final = re.compile(r"`(test_[a-z0-9_]+)(?:\[[^\]`]*\])?`")
_NAMED_MODULE: Final = re.compile(r"`(tests/[a-z0-9_/]+\.py)`")


def _crosswalk_text() -> str:
    """Sections 6 (test plan, R2 clause map, prove-red), 7 (section 45) and 8."""
    text = CONTRACT.read_text(encoding="utf-8")
    start = text.index("\n## 6. Test plan and crosswalk")
    return text[start:]


def _defined_tests() -> set[str]:
    defined: set[str] = set()
    for path in (ROOT / "tests").rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        defined |= {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name.startswith("test_")
        }
    return defined


def test_the_s5b2_contract_crosswalk_names_tests_that_exist() -> None:
    """Every test function and test module sections 6-8 name exists in the tree.

    It cannot prove a named test is collected or passes (the tiers run them; the
    section 7 table records the executed results), only that the crosswalk does
    not cite a test nobody wrote or one a rename left behind.
    """
    text = _crosswalk_text()
    named = set(_NAMED_TEST.findall(text))
    assert len(named) >= 120, f"the crosswalk parse found only {len(named)} names"
    missing = sorted(named - _defined_tests())
    assert not missing, f"the contract names tests that do not exist: {missing}"
    modules = set(_NAMED_MODULE.findall(text))
    assert modules, "the crosswalk names no module?"
    absent = sorted(module for module in modules if not (ROOT / module).is_file())
    assert not absent, f"the contract names test modules that do not exist: {absent}"
