"""Meeting sync stays a pure, self-contained slice (WP2, parallel to communications).

* `my_pa.domain.meeting_sync` imports only the standard library, itself and the
  Meeting domain (`my_pa.domain.meeting`, whose validators and attendee rule it
  reuses), and does no IO: no file, network, subprocess, environment or logging
  module;
* `my_pa.infrastructure.meeting_sync` imports only the standard library, the
  meeting-sync domain and itself -- no database, network or framework;
* only the named consumers import either package: the application resolution
  service, the Meeting port and its persistence (the binding vocabularies), and
  the `meetings.provider.bind` path (WP2-W3): its command, the Meeting
  application that arbitrates it and the binding view it answers with;
* the communications and meeting-sync slices do not import each other;
* provider vocabulary stays out of the domain.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "my_pa"
DOMAIN = PACKAGE / "domain" / "meeting_sync"
INFRASTRUCTURE = PACKAGE / "infrastructure" / "meeting_sync"
DOMAIN_NAME = "my_pa.domain.meeting_sync"
INFRASTRUCTURE_NAME = "my_pa.infrastructure.meeting_sync"
MEETING_DOMAIN_NAME = "my_pa.domain.meeting"

#: The only modules outside the slice that may import it.
CONSUMERS = frozenset(
    {
        "application/commands.py",
        "application/meeting_provider_sync.py",
        "application/meetings.py",
        "contracts/ports.py",
        "contracts/v1/meetings.py",
        "infrastructure/persistence/meetings.py",
        "infrastructure/persistence/tables.py",
    }
)

IO_MODULES = frozenset(
    {"os", "io", "pathlib", "shutil", "socket", "subprocess", "urllib", "http", "logging", "sys"}
)
PROVIDER_WORDS = ("graph", "outlook", "exchange", "google", "icloud", "caldav", "procore")


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _modules(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _is_meeting_domain(name: str) -> bool:
    return name == MEETING_DOMAIN_NAME or name.startswith(MEETING_DOMAIN_NAME + ".")


def test_the_slice_exists() -> None:
    assert {path.name for path in _modules(DOMAIN)} >= {
        "__init__.py",
        "model.py",
        "diagnostics.py",
        "resolution.py",
    }
    assert {path.name for path in _modules(INFRASTRUCTURE)} >= {"__init__.py", "parser.py"}


@pytest.mark.parametrize("path", _modules(DOMAIN), ids=lambda p: p.name)
def test_domain_imports_only_stdlib_itself_and_the_meeting_domain(path: Path) -> None:
    for name in _imports(path):
        root = name.split(".")[0]
        if root == "my_pa":
            assert name.startswith(DOMAIN_NAME) or _is_meeting_domain(name), name
        else:
            assert root in sys.stdlib_module_names, name
            assert root not in IO_MODULES, name


@pytest.mark.parametrize("path", _modules(DOMAIN), ids=lambda p: p.name)
def test_domain_names_no_provider(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    words: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            words.append(node.value)
        elif isinstance(node, ast.Name):
            words.append(node.id)
        elif isinstance(node, ast.Attribute):
            words.append(node.attr)
    for word in PROVIDER_WORDS:
        pattern = re.compile(rf"(?<![a-z]){word}(?![a-z])", re.I)
        assert not any(pattern.search(w) for w in words), (path.name, word)


@pytest.mark.parametrize("path", _modules(INFRASTRUCTURE), ids=lambda p: p.name)
def test_infrastructure_imports_only_stdlib_and_the_slice(path: Path) -> None:
    for name in _imports(path):
        root = name.split(".")[0]
        if root == "my_pa":
            assert name.startswith((DOMAIN_NAME, INFRASTRUCTURE_NAME)), name
        else:
            assert root in sys.stdlib_module_names, name


def test_only_the_named_consumers_import_the_slice() -> None:
    importers = {
        str(path.relative_to(PACKAGE))
        for path in _modules(PACKAGE)
        if DOMAIN not in path.parents
        and INFRASTRUCTURE not in path.parents
        and any(n.startswith((DOMAIN_NAME, INFRASTRUCTURE_NAME)) for n in _imports(path))
    }
    assert importers <= CONSUMERS
    assert "application/meeting_provider_sync.py" in importers


def test_the_two_source_slices_are_independent() -> None:
    communications = ("my_pa.domain.communications", "my_pa.infrastructure.communications")
    for path in (*_modules(DOMAIN), *_modules(INFRASTRUCTURE)):
        assert not any(n.startswith(communications) for n in _imports(path)), path.name
    for root in (
        PACKAGE / "domain" / "communications",
        PACKAGE / "infrastructure" / "communications",
    ):
        for path in _modules(root):
            names = _imports(path)
            assert not any(n.startswith((DOMAIN_NAME, INFRASTRUCTURE_NAME)) for n in names)
