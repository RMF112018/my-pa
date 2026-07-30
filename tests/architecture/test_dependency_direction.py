"""Dependency direction: apps/bootstrap -> application/infrastructure -> domain/contracts.

These tests parse the source tree rather than importing it, so a violation is
caught even when the offending module is never executed by another test.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
PACKAGE = SRC / "my_pa"

#: Layers, inner first. A layer may import itself and anything to its left.
LAYER_ORDER: tuple[str, ...] = ("domain", "contracts", "application", "bootstrap")


def _modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def _layer_of(path: Path) -> str | None:
    parts = path.relative_to(PACKAGE).parts
    return parts[0] if parts and parts[0] in LAYER_ORDER else None


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                pytest.fail(f"{path}: relative import; use absolute my_pa imports")
            if node.module:
                names.add(node.module)
    return names


def test_the_source_tree_is_not_empty() -> None:
    # Guards every other test in this file against passing vacuously.
    assert len(_modules()) >= 10
    assert {_layer_of(p) for p in _modules()} >= set(LAYER_ORDER)


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.name))
def test_no_module_imports_an_outer_layer(path: Path) -> None:
    layer = _layer_of(path)
    if layer is None:
        return
    allowed = set(LAYER_ORDER[: LAYER_ORDER.index(layer) + 1])
    for imported in _imported_modules(path):
        if not imported.startswith("my_pa."):
            continue
        parts = imported.split(".")
        if len(parts) < 2 or parts[1] not in LAYER_ORDER:
            continue
        target = parts[1]
        assert target in allowed, (
            f"{path.relative_to(PACKAGE)} is in '{layer}' and imports '{target}', "
            f"which is outside {sorted(allowed)}"
        )


@pytest.mark.parametrize(
    "path", [p for p in _modules() if _layer_of(p) == "domain"], ids=lambda p: str(p.name)
)
def test_domain_uses_only_the_standard_library(path: Path) -> None:
    for imported in _imported_modules(path):
        root = imported.split(".")[0]
        if root == "my_pa":
            continue
        assert root in sys.stdlib_module_names, (
            f"{path.relative_to(PACKAGE)} imports third-party module '{imported}'; "
            "domain code may use only the standard library"
        )


@pytest.mark.parametrize(
    "path", [p for p in _modules() if _layer_of(p) == "domain"], ids=lambda p: str(p.name)
)
def test_domain_does_not_import_pydantic(path: Path) -> None:
    # Called out separately from the stdlib rule because Pydantic at the domain
    # boundary is the specific mistake this architecture forbids.
    assert not any(i.split(".")[0] == "pydantic" for i in _imported_modules(path)), (
        f"{path.relative_to(PACKAGE)} imports Pydantic; it belongs at the contract "
        "and settings boundary only"
    )


def test_contracts_do_not_import_application_or_bootstrap() -> None:
    for path in (p for p in _modules() if _layer_of(p) == "contracts"):
        for imported in _imported_modules(path):
            assert not imported.startswith(("my_pa.application", "my_pa.bootstrap")), (
                f"{path.relative_to(PACKAGE)} imports {imported}"
            )


def test_pydantic_is_confined_to_contracts_and_settings() -> None:
    offenders = [
        path.relative_to(PACKAGE)
        for path in _modules()
        if any(i.split(".")[0] == "pydantic" for i in _imported_modules(path))
        and _layer_of(path) != "contracts"
        and path.name != "settings.py"
    ]
    assert not offenders, f"Pydantic used outside contracts and settings: {offenders}"
