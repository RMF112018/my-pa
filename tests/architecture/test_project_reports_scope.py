"""Project reports stay a pure, neutral, self-contained slice (WP3P-S1; plan 12.2).

* `my_pa.domain.project_reports` imports only the standard library and itself,
  and does no IO: no file, network, subprocess, environment or logging module,
  no `open`/`print`/dynamic code, and no clock read;
* no `float` (name or literal) appears in any project-reports module, in any
  layer, nor in any `project_report*` module of the domain, the application,
  `infrastructure/persistence` and `infrastructure/project_reports` (PULSE-AC-05:
  money is `Decimal` only; WP4P ruling A5 widened the reach);
* the domain names no export provider and no provider header string, and no
  project-reports module in any layer except the reader
  `infrastructure/project_reports/pulse_csv.py` holds a header string;
* no project-reports module imports a communications module, and no
  communications module imports a project-reports one;
* no `Capability`, `Purpose`, `IdKind` or table name carries `pulse` or
  `procore`, beyond the 3 names that predate WP3P and mean the continuity
  Pulse, not the export source (frozen below, so a new one fails).

Each rule is parsed from the source; the planted cases below prove the scanners
see what they claim to.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Final

import pytest

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.tables import METADATA

PACKAGE: Final = Path(__file__).resolve().parents[2] / "src" / "my_pa"
DOMAIN: Final = PACKAGE / "domain" / "project_reports"
DOMAIN_NAME: Final = "my_pa.domain.project_reports"
SLICE_NAMES: Final = (
    "my_pa.domain.project_reports",
    "my_pa.application.project_reports",
    "my_pa.infrastructure.project_reports",
    "my_pa.bootstrap.project_reports",
)
COMMUNICATIONS_NAMES: Final = (
    "my_pa.domain.communications",
    "my_pa.infrastructure.communications",
    "my_pa.application.communications_ingest",
    "my_pa.application.communications_search",
    "my_pa.bootstrap.communications_ingest",
)

IO_MODULES: Final = frozenset(
    {
        "os",
        "io",
        "pathlib",
        "shutil",
        "socket",
        "subprocess",
        "urllib",
        "http",
        "logging",
        "sys",
        "tempfile",
        "glob",
        "time",
        "pickle",
        "csv",
    }
)
BANNED_CALLS: Final = frozenset({"open", "print", "input", "eval", "exec", "compile", "__import__"})
CLOCK_ATTRIBUTES: Final = frozenset({"now", "utcnow", "today", "fromtimestamp", "utcfromtimestamp"})
PROVIDER_WORDS: Final = ("procore",)
#: An export provider's header strings have the shape `Entity > Field`.
HEADER_STRING: Final = re.compile(r"\S > \S")
EXPORT_SOURCE_NAME: Final = re.compile(r"pulse|procore", re.IGNORECASE)

#: Names that predate WP3P and mean the continuity Pulse (attention items).
PREEXISTING_PULSE_NAMES: Final = frozenset(
    {
        ("capability", "CONTINUITY_PULSE", "continuity.pulse"),
        ("id_kind", "PULSE", "puls"),
        ("table", "pulse_items", "pulse_items"),
    }
)


def _slice_modules() -> list[Path]:
    """Every project-reports module in any layer (packages and single modules)."""
    found: list[Path] = []
    for layer in ("domain", "application", "infrastructure", "bootstrap", "adapters"):
        root = PACKAGE / layer
        found += sorted(root.glob("project_reports*.py"))
        for package in sorted(root.glob("project_reports*/")):
            found += sorted(package.rglob("*.py"))
    return sorted(set(found))


#: The no-float rule's reach (WP4P ruling A5): every `project_report*` module
#: (singular or plural) in these directories, packages included.
FLOAT_SCOPE: Final = (
    PACKAGE / "domain",
    PACKAGE / "application",
    PACKAGE / "infrastructure" / "persistence",
    PACKAGE / "infrastructure" / "project_reports",
)


def _float_scope_modules() -> list[Path]:
    """Every project-report module the no-float rule reads, beside the slice modules."""
    found: list[Path] = list(_slice_modules())
    for root in FLOAT_SCOPE:
        found += sorted(root.glob("project_report*.py"))
        for package in sorted(root.glob("project_report*/")):
            found += sorted(package.rglob("*.py"))
    return sorted(set(found))


def _domain_modules() -> list[Path]:
    return sorted(DOMAIN.rglob("*.py"))


def _imports(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _floats(source: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Name) and node.id == "float") or (
            isinstance(node, ast.Constant) and type(node.value) in (float, complex)
        ):
            lines.append(node.lineno)
    return lines


def _io(source: str) -> list[str]:
    found: list[str] = []
    for name in _imports(source):
        root = name.split(".")[0]
        if root == "my_pa":
            if not (name == DOMAIN_NAME or name.startswith(DOMAIN_NAME + ".")):
                found.append(name)
        elif root in IO_MODULES or root not in (sys.stdlib_module_names | {"__future__"}):
            found.append(name)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in BANNED_CALLS:
                found.append(f"{node.func.id}()")
        elif isinstance(node, ast.Attribute) and node.attr in CLOCK_ATTRIBUTES:
            found.append(f".{node.attr}")
    return found


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_domain_slice_exists() -> None:
    assert {path.name for path in _domain_modules()} >= {
        "__init__.py",
        "model.py",
        "signature.py",
        "roles.py",
        "money.py",
        "reconciliation.py",
        "identity.py",
        "measures.py",
        "bindings.py",
        "labels.py",
        "versions.py",
        "catalogue.py",
        "cursor.py",
        "reads.py",
    }
    assert set(_domain_modules()) <= set(_slice_modules())


@pytest.mark.parametrize("path", _domain_modules(), ids=lambda p: p.name)
def test_the_domain_is_stdlib_only_and_does_no_io(path: Path) -> None:
    assert _io(_read(path)) == []


@pytest.mark.parametrize("path", _float_scope_modules(), ids=lambda p: str(p.relative_to(PACKAGE)))
def test_no_float_in_any_project_reports_module(path: Path) -> None:
    assert _floats(_read(path)) == []


def test_the_no_float_rule_reaches_every_project_report_module() -> None:
    """Ruling A5's planted control: the singular-prefix modules are in scope too."""
    scope = set(_float_scope_modules())
    for planted in (
        PACKAGE / "infrastructure" / "persistence" / "project_report_reads.py",
        PACKAGE / "infrastructure" / "persistence" / "project_reports.py",
        PACKAGE / "application" / "project_reports_reads.py",
        PACKAGE / "application" / "project_reports_coverage.py",
        PACKAGE / "infrastructure" / "project_reports" / "pulse_csv.py",
        DOMAIN / "reads.py",
    ):
        assert planted.exists(), planted
        assert planted in scope, planted.relative_to(PACKAGE)


@pytest.mark.parametrize("path", _domain_modules(), ids=lambda p: p.name)
def test_the_domain_names_no_provider_or_header_string(path: Path) -> None:
    for node in ast.walk(ast.parse(_read(path))):
        words: list[str] = []
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            words.append(node.value)
            assert HEADER_STRING.search(node.value) is None, (path.name, node.lineno)
        elif isinstance(node, ast.Name):
            words.append(node.id)
        elif isinstance(node, ast.Attribute):
            words.append(node.attr)
        for word in words:
            assert not any(w in word.lower() for w in PROVIDER_WORDS), (path.name, word)


#: The one module allowed to name the export provider's header strings.
READER: Final = PACKAGE / "infrastructure" / "project_reports" / "pulse_csv.py"


def _header_strings(source: str) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and HEADER_STRING.search(node.value)
    ]


def test_only_the_reader_names_header_strings() -> None:
    modules = _slice_modules()
    assert READER in modules
    assert _header_strings(_read(READER)) != []
    for path in modules:
        if path != READER:
            assert _header_strings(_read(path)) == [], path.relative_to(PACKAGE)


def test_project_reports_and_communications_do_not_import_each_other() -> None:
    for path in _slice_modules():
        hits = {n for n in _imports(_read(path)) if n.startswith(COMMUNICATIONS_NAMES)}
        assert hits == set(), path
    communications = [
        *sorted((PACKAGE / "domain" / "communications").rglob("*.py")),
        *sorted((PACKAGE / "infrastructure" / "communications").rglob("*.py")),
        PACKAGE / "application" / "communications_ingest.py",
        PACKAGE / "application" / "communications_search.py",
        PACKAGE / "bootstrap" / "communications_ingest.py",
    ]
    assert len(communications) > 4
    for path in communications:
        hits = {n for n in _imports(_read(path)) if n.startswith(SLICE_NAMES)}
        assert hits == set(), path


def _export_source_names() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    for kind, members in (("capability", Capability), ("purpose", Purpose), ("id_kind", IdKind)):
        for member in members:
            if EXPORT_SOURCE_NAME.search(member.name) or EXPORT_SOURCE_NAME.search(member.value):
                found.add((kind, member.name, member.value))
    for table in METADATA.tables.values():
        if EXPORT_SOURCE_NAME.search(table.name):
            found.add(("table", table.name, table.name))
    return found


def test_no_capability_purpose_id_kind_or_table_names_the_export_source() -> None:
    assert _export_source_names() == PREEXISTING_PULSE_NAMES


# --- planted prove-red controls -------------------------------------------


def test_a_planted_float_is_caught() -> None:
    source = _read(DOMAIN / "money.py")
    assert _floats(source + "\nX = float('1')\n") != []
    assert _floats(source + "\nY = 0.5\n") != []


def test_a_planted_io_import_and_clock_read_are_caught() -> None:
    source = _read(DOMAIN / "labels.py")
    assert _io(source + "\nimport os\n") == ["os"]
    assert _io(source + "\nfrom my_pa.domain.communications import model\n") != []
    assert _io(source + "\nX = date.today()\n") == [".today"]
    assert _io(source + "\nopen('x')\n") == ["open()"]


def test_a_planted_communications_import_is_caught() -> None:
    planted = "from my_pa.domain.communications.model import Publication\n"
    assert {n for n in _imports(planted) if n.startswith(COMMUNICATIONS_NAMES)}


def test_a_planted_header_string_is_caught() -> None:
    assert _header_strings('X = "RFI > Number"\n') == [1]
    assert _header_strings('X = "a >= b"\n') == []


def test_the_name_pattern_sees_a_planted_name() -> None:
    assert EXPORT_SOURCE_NAME.search("project_reports.pulse_query")
    assert EXPORT_SOURCE_NAME.search("procore_rows")
    assert EXPORT_SOURCE_NAME.search("project_report_lines") is None
    assert HEADER_STRING.search("Entity > Field")
    assert HEADER_STRING.search("a > b") and HEADER_STRING.search("a>b") is None
