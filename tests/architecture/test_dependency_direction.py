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
    """Every dotted import target in `path`, wherever in the file it appears.

    `ast.walk` rather than a scan of the module body, so an import buried in a
    function or a `TYPE_CHECKING` block counts; a comment or a string that
    happens to name a layer does not.

    `from X import Y` contributes `X.Y` as well as `X`, because
    `from my_pa import infrastructure` is the same crossing as
    `import my_pa.infrastructure` and would otherwise read as a plain `my_pa`.
    """
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
                names.update(f"{node.module}.{alias.name}" for alias in node.names)
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


# `infrastructure` is deliberately absent from `LAYER_ORDER`: it is not a rung on
# a single ladder but a sibling of `application` that implements domain ports, so
# ordering it against `bootstrap` would assert something AGENTS.md does not say.
# The consequence is that `test_no_module_imports_an_outer_layer` skips every
# `my_pa.infrastructure` import, and the two rules below are what state the
# section 4 boundary for it directly rather than leaving it to a side effect of
# the dependency list.

#: Third-party roots that carry a persistence or transport concern. A domain
#: model that imports one has a provider detail in it, which section 4 forbids.
#: Enumerated rather than inferred so the failure names the specific mistake;
#: `test_domain_uses_only_the_standard_library` is the broader net behind it.
DATABASE_AND_FRAMEWORK_ROOTS = frozenset(
    {
        "alembic",
        "asyncpg",
        "django",
        "fastapi",
        "flask",
        "psycopg",
        "psycopg2",
        "sqlalchemy",
        "sqlmodel",
        "starlette",
        "tortoise",
        "uvicorn",
    }
)


@pytest.mark.parametrize(
    "path", [p for p in _modules() if _layer_of(p) == "domain"], ids=lambda p: str(p.name)
)
def test_domain_imports_neither_application_nor_infrastructure(path: Path) -> None:
    """AGENTS.md section 4: `domain` depends on neither application nor infrastructure."""
    offending = sorted(
        imported
        for imported in _imported_modules(path)
        if imported == "my_pa.application"
        or imported == "my_pa.infrastructure"
        or imported.startswith(("my_pa.application.", "my_pa.infrastructure."))
    )
    assert not offending, (
        f"{path.relative_to(PACKAGE)} is domain code and imports {offending}; "
        "domain depends on neither application nor infrastructure"
    )


@pytest.mark.parametrize(
    "path", [p for p in _modules() if _layer_of(p) == "domain"], ids=lambda p: str(p.name)
)
def test_domain_imports_no_database_or_framework_package(path: Path) -> None:
    offending = sorted(
        {i.split(".")[0] for i in _imported_modules(path)} & DATABASE_AND_FRAMEWORK_ROOTS
    )
    assert not offending, (
        f"{path.relative_to(PACKAGE)} is domain code and imports {offending}; "
        "persistence and transport details do not belong in a domain model"
    )


@pytest.mark.parametrize(
    "path", [p for p in _modules() if _layer_of(p) == "application"], ids=lambda p: str(p.name)
)
def test_application_does_not_import_infrastructure(path: Path) -> None:
    """AGENTS.md section 4: application depends inward; infrastructure implements ports.

    Composition is bootstrap's job, so an `application` module that names a
    concrete adapter has taken it.
    """
    offending = sorted(
        imported
        for imported in _imported_modules(path)
        if imported == "my_pa.infrastructure" or imported.startswith("my_pa.infrastructure.")
    )
    assert not offending, (
        f"{path.relative_to(PACKAGE)} is application code and imports {offending}; "
        "infrastructure is wired in at bootstrap, not imported by application code"
    )


def test_the_guarded_layers_have_modules_to_guard() -> None:
    # Parametrizing over an empty list collects nothing and reports success, so
    # the three rules above would pass on a tree where `domain` had been deleted.
    for layer in ("domain", "application"):
        assert [p for p in _modules() if _layer_of(p) == layer], f"no module in '{layer}'"
    assert (PACKAGE / "infrastructure").is_dir()
