"""Communications evidence stays a pure, self-contained slice (WP1 source contract).

* `my_pa.domain.communications` imports only the standard library and itself,
  and does no IO: no file, network, subprocess, environment or logging module;
* `my_pa.infrastructure.communications` imports only the standard library, the
  communications domain and itself -- no database, network or framework;
* nothing else in `src/` imports either package except the explicit
  `IMPORTERS` allowlist (Manager ruling M5): WP3a's table declarations read the
  closed vocabularies their CHECKs constrain;
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


#: The modules outside the slice that may import it (Manager ruling M5), each
#: with its reason. Exact: an importer added elsewhere fails, and an entry that
#: stops importing must be removed.
IMPORTERS = {
    # WP3a: the communications tables derive their closed-vocabulary CHECKs
    # from the domain enums (the `_one_of` convention).
    "infrastructure/persistence/tables.py",
}


def _importers(package: Path) -> set[str]:
    return {
        str(path.relative_to(package))
        for path in _modules(package)
        if DOMAIN not in path.parents
        and INFRASTRUCTURE not in path.parents
        and any(n.startswith((DOMAIN_NAME, INFRASTRUCTURE_NAME)) for n in _imports(path))
    }


def test_only_the_allowlisted_modules_import_the_slice() -> None:
    assert _importers(PACKAGE) == IMPORTERS


def test_a_module_outside_the_allowlist_that_imports_the_slice_is_caught(tmp_path: Path) -> None:
    """Prove-red for the allowlist: a planted importer is reported, not absorbed."""
    planted = tmp_path / "application" / "planted.py"
    planted.parent.mkdir(parents=True)
    planted.write_text(f"from {DOMAIN_NAME}.model import Dialect\n", encoding="utf-8")
    assert _importers(tmp_path) == {"application/planted.py"}
