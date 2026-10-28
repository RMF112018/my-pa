"""What the S5b-2 schedule worker may load and say (worker contract 3.3, 3.4.2, 3.15).

The parser child's import closure holds no network or database module, the
worker parent never loads PDFium, and the new worker modules neither log nor
print: the only bytes any of them writes are the child's one frame on its
`stdout`. The closures are measured in fresh isolated interpreters, so nothing
this test process has already imported can hide or fake a module.

FAST: no database, no PDF; two short subprocesses.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Final

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
