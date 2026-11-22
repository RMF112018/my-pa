"""Communications evidence stays a pure, self-contained slice (WP1 source contract).

* `my_pa.domain.communications` imports only the standard library and itself,
  and does no IO: no file, network, subprocess, environment or logging module;
* `my_pa.infrastructure.communications` imports only the standard library, the
  communications domain and itself -- no database, network or framework;
* nothing else in `src/` imports either package yet: there is no persistence,
  application service or capability for communications in WP1;
* provider vocabulary stays in the parser: the domain names no provider.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "my_pa"
DOMAIN = PACKAGE / "domain" / "communications"
INFRASTRUCTURE = PACKAGE / "infrastructure" / "communications"
DOMAIN_NAME = "my_pa.domain.communications"
INFRASTRUCTURE_NAME = "my_pa.infrastructure.communications"

#: Standard-library modules that would let pure code do IO.
IO_MODULES = frozenset(
    {"os", "io", "pathlib", "shutil", "socket", "subprocess", "urllib", "http", "logging", "sys"}
)
#: Provider and producer vocabulary that belongs to the parser alone.
PROVIDER_WORDS = ("graph", "outlook", "receivedDateTime", "sentDateTime", "emailAddress", "procore")


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


def test_the_slice_exists() -> None:
    assert len(_modules(DOMAIN)) >= 7
    assert len(_modules(INFRASTRUCTURE)) >= 3


@pytest.mark.parametrize("path", _modules(DOMAIN), ids=lambda p: p.name)
def test_domain_imports_only_stdlib_and_itself_and_does_no_io(path: Path) -> None:
    for name in _imports(path):
        root = name.split(".")[0]
        if root == "my_pa":
            assert name.startswith(DOMAIN_NAME), name
        else:
            assert root in sys.stdlib_module_names, name
            assert root not in IO_MODULES, name


@pytest.mark.parametrize("path", _modules(DOMAIN), ids=lambda p: p.name)
def test_domain_names_no_provider(path: Path) -> None:
    """No identifier or string literal in the domain carries provider vocabulary."""
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


def test_nothing_outside_the_slice_imports_it() -> None:
    offenders = [
        str(path.relative_to(PACKAGE))
        for path in _modules(PACKAGE)
        if DOMAIN not in path.parents
        and INFRASTRUCTURE not in path.parents
        and any(n.startswith((DOMAIN_NAME, INFRASTRUCTURE_NAME)) for n in _imports(path))
    ]
    assert offenders == []
