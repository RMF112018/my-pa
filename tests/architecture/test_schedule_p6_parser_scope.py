"""P6 XER S7-1: the parser package stays pure (acceptance A8) (FAST).

Contract `docs/architecture/schedule-xer-import-contract.md` sections 6.1,
13.2 and 14 (S7-1, A8). The S5a guards of `test_cpm_full_parser_scope.py`
walk `src/my_pa/domain/schedule` recursively, so they already bind
`domain/schedule/p6` (import allowlist, no logging, printing or file access,
neutral naming); the first test below proves that reach. This sibling adds,
by AST over the `p6` package:

* imports are the standard library and `my_pa.domain.schedule.p6` only (not
  even `my_pa.domain.common`): the parser needs nothing else;
* no clock, randomness, environment, IO, process or network module, and no
  XML library (the S5b-2 runtime guard stays unnarrowed until the XML slice);
* no `now`/`today`/`utcnow`, `open`/`print`/`input`, `eval`/`exec`/`compile`
  call, and no `float` call or literal (the frame admits no float);

and over the fixture generator and the conformance script:

* the generator is standard library only at module level, reaches the parser
  only lazily inside its golden writer, and only it names `record_goldens`;
* the generator, its goldens and the package carry no denylisted token;
* the script imports the standard library and `my_pa.domain.schedule.p6`
  only (no database, settings, network) and never writes a file.

What it cannot prove: that no `set` iteration order reaches the frame (the
golden digests under several hash seeds check that behaviourally).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Final

from tests.architecture import test_cpm_full_parser_scope as s5a_scope

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa" / "domain" / "schedule" / "p6"
GENERATOR: Final = ROOT / "tests" / "fixtures" / "schedule_p6_xer.py"
GOLDENS: Final = ROOT / "tests" / "fixtures" / "schedule_p6_xer_goldens.json"
SCRIPT: Final = ROOT / "ops" / "schedule" / "p6_export_profile.py"

FORBIDDEN_ROOTS: Final = frozenset(
    {
        "random",
        "time",
        "secrets",
        "uuid",
        "os",
        "io",
        "pathlib",
        "socket",
        "subprocess",
        "shutil",
        "tempfile",
        "logging",
        "sys",
        "urllib",
        "http",
        "xml",
        "lxml",
        "defusedxml",
        "sqlite3",
        "pickle",
        "marshal",
    }
)
BUILTIN_CALLS: Final = frozenset(
    {"open", "print", "input", "breakpoint", "eval", "exec", "compile", "float", "__import__"}
)
CLOCK_CALLS: Final = frozenset({"now", "today", "utcnow", "time", "monotonic", "perf_counter"})


def _modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            name = "." * node.level + (node.module or "")
            found.append((node.lineno, name))
    return found


def test_the_s5a_domain_guards_reach_the_p6_package() -> None:
    modules = _modules()
    assert {path.name for path in modules} >= {
        "__init__.py",
        "catalogue.py",
        "calendar.py",
        "frame.py",
        "model.py",
        "parser.py",
        "profile.py",
        "reader.py",
        "values.py",
    }
    assert set(modules) <= set(s5a_scope._modules(s5a_scope.DOMAIN))


def test_p6_imports_only_the_standard_library_and_itself() -> None:
    stdlib = sys.stdlib_module_names
    wrong: list[str] = []
    for path in _modules():
        for line, name in _imports(_tree(path)):
            where = f"{path.relative_to(ROOT)}:{line} imports {name}"
            root = name.split(".")[0]
            if name.startswith(".") or root in FORBIDDEN_ROOTS:
                wrong.append(where)
            elif root in stdlib or root == "__future__":
                continue
            elif not (
                name == "my_pa.domain.schedule.p6" or name.startswith("my_pa.domain.schedule.p6.")
            ):
                wrong.append(where)
    assert not wrong, wrong


def test_p6_has_no_clock_io_evaluation_or_float() -> None:
    wrong: list[str] = []
    for path in _modules():
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Call):
                builtin = isinstance(node.func, ast.Name) and node.func.id in BUILTIN_CALLS
                clock = isinstance(node.func, ast.Attribute) and node.func.attr in CLOCK_CALLS
                if builtin or clock:
                    wrong.append(
                        f"{path.relative_to(ROOT)}:{node.lineno} calls {ast.unparse(node.func)}"
                    )
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                wrong.append(f"{path.relative_to(ROOT)}:{node.lineno} float literal")
    assert not wrong, wrong


def test_generator_is_standard_library_only_and_reaches_the_parser_lazily() -> None:
    tree = _tree(GENERATOR)
    top_level = [
        name
        for node in tree.body
        if isinstance(node, ast.Import | ast.ImportFrom)
        for _, name in _imports(node)
    ]
    assert top_level
    for name in top_level:
        root = name.split(".")[0]
        assert root in sys.stdlib_module_names or root == "__future__", name
        assert root not in {"random", "time", "secrets", "uuid"}, name
    lazy = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node not in tree.body
        for _, name in _imports(node)
    }
    assert lazy <= {"my_pa.domain.schedule.p6", "my_pa.domain.schedule.p6.profile"}


def test_only_the_generator_references_record_goldens() -> None:
    wrong: list[str] = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        if path == GENERATOR:
            continue
        for node in ast.walk(_tree(path)):
            named = (isinstance(node, ast.Name) and node.id == "record_goldens") or (
                isinstance(node, ast.Attribute) and node.attr == "record_goldens"
            )
            imported = isinstance(node, ast.ImportFrom) and any(
                alias.name == "record_goldens" for alias in node.names
            )
            if named or imported:
                wrong.append(f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', '?')}")
    assert not wrong, wrong


def test_p6_files_carry_no_denylisted_token() -> None:
    offending = {
        str(path.relative_to(ROOT)): sorted(found)
        for path in (*_modules(), GENERATOR, GOLDENS, SCRIPT)
        if (found := s5a_scope._denylisted(path.read_bytes()))
    }
    assert not offending, offending


def test_the_conformance_script_cannot_reach_a_database_network_or_write() -> None:
    tree = _tree(SCRIPT)
    stdlib = sys.stdlib_module_names
    for _, name in _imports(tree):
        root = name.split(".")[0]
        assert root not in {"socket", "urllib", "http", "subprocess", "sqlite3"}, name
        assert root in stdlib or root == "__future__" or name == "my_pa.domain.schedule.p6", name
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"write_bytes", "write_text", "unlink", "rename", "replace"}, (
                node.attr
            )
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in {"w", "wb", "a", "ab", "r+", "rb+", "w+", "x"}, node.value
