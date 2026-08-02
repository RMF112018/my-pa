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

#: Deliberately not a member of `LAYER_ORDER`; see the note further down.
INFRASTRUCTURE = "infrastructure"


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
# `my_pa.infrastructure` import *and* every import made by an infrastructure
# module, so the rules below are what state the section 4 boundary for it
# directly rather than leaving it to a side effect of the dependency list.


def _infrastructure_modules() -> list[Path]:
    """Every module under `my_pa.infrastructure`.

    `_layer_of` answers `None` for all of them, because `infrastructure` is not
    in `LAYER_ORDER`. Selecting them by prefix here is what keeps the rules that
    follow from parametrising over an empty list.
    """
    return [p for p in _modules() if p.relative_to(PACKAGE).parts[:1] == (INFRASTRUCTURE,)]


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


@pytest.mark.parametrize("path", _infrastructure_modules(), ids=lambda p: str(p.name))
def test_infrastructure_does_not_import_application(path: Path) -> None:
    """AGENTS.md section 4: `infrastructure` implements ports defined inward.

    An adapter that reaches back into `application` has inverted the dependency
    the ports exist to create, and the boundary then holds only in one
    direction. `src/my_pa/infrastructure/database/engine.py` states an invariant
    of exactly this kind in its docstring -- "nothing here reads process
    settings" -- and a docstring is not a check.
    """
    offending = sorted(
        imported
        for imported in _imported_modules(path)
        if imported == "my_pa.application" or imported.startswith("my_pa.application.")
    )
    assert not offending, (
        f"{path.relative_to(PACKAGE)} is infrastructure code and imports {offending}; "
        "infrastructure implements ports defined inward and does not call application code"
    )


@pytest.mark.parametrize("path", _infrastructure_modules(), ids=lambda p: str(p.name))
def test_infrastructure_does_not_import_bootstrap(path: Path) -> None:
    """AGENTS.md section 4: composition belongs in bootstrap, not in an adapter.

    `my_pa.bootstrap` is where settings and wiring live. An adapter that imports
    it reads process configuration for itself instead of being handed what it
    needs, which is how a component acquires a hidden dependency on the
    environment. An operator script may compose the two -- that is what an entry
    point is for -- but it lives outside the package.
    """
    offending = sorted(
        imported
        for imported in _imported_modules(path)
        if imported == "my_pa.bootstrap" or imported.startswith("my_pa.bootstrap.")
    )
    assert not offending, (
        f"{path.relative_to(PACKAGE)} is infrastructure code and imports {offending}; "
        "settings and wiring are supplied by bootstrap or an entry point, not read here"
    )


# `MB-AC-002`: domain and application are isolated from transport, ORM, provider,
# parser, host, and database details. The domain half is above; the application
# half is below, and it is stated as three separate rules rather than one because
# the three fail for different reasons and a reader has to be told which.


#: Third-party roots a transport would bring. Kept separate from
#: `DATABASE_AND_FRAMEWORK_ROOTS` because `MB-AC-002` names transport and ORM as
#: distinct concerns, and because a failure naming the specific mistake is worth
#: more than one naming a merged list. `mcp` and `anyio` are here ahead of the
#: adapters that will use them: `D-25` through `D-27` put them at the transport
#: edge in WP-4B, and this is the rule that keeps them there.
TRANSPORT_ROOTS = frozenset(
    {
        "aiohttp",
        "anyio",
        "asyncio",
        "fastapi",
        "flask",
        "httpx",
        "mcp",
        "requests",
        "starlette",
        "uvicorn",
    }
)

#: Modules whose names mean "a concrete implementation of a port". An application
#: module that imports one has taken the composition root's decision.
PROVIDER_AND_PARSER_ROOTS = frozenset(
    {"boto3", "fitz", "paramiko", "pdfminer", "pypdf", "smbclient"}
)


@pytest.mark.parametrize(
    "path", [p for p in _modules() if _layer_of(p) == "application"], ids=lambda p: str(p.name)
)
def test_application_imports_no_transport_module(path: Path) -> None:
    """`MB-AC-002`: the application does not parse HTTP or MCP, and does not await.

    `D-27` keeps async at the transport edge, so an `asyncio` or `anyio` import
    inside `application` is the boundary moving rather than a convenience.
    """
    offending = sorted({i.split(".")[0] for i in _imported_modules(path)} & TRANSPORT_ROOTS)
    assert not offending, (
        f"{path.relative_to(PACKAGE)} is application code and imports {offending}; "
        "transport parsing and its concurrency belong to an adapter"
    )


@pytest.mark.parametrize(
    "path", [p for p in _modules() if _layer_of(p) == "application"], ids=lambda p: str(p.name)
)
def test_application_imports_no_orm_sql_or_driver_module(path: Path) -> None:
    """`MB-AC-002`: the application executes no SQL and holds no connection.

    The unit of work is a port; the statements behind it are `infrastructure`'s.
    An application module that imports SQLAlchemy has the transaction *and* the
    schema, which is the coupling the port exists to remove.
    """
    offending = sorted(
        {i.split(".")[0] for i in _imported_modules(path)} & DATABASE_AND_FRAMEWORK_ROOTS
    )
    assert not offending, (
        f"{path.relative_to(PACKAGE)} is application code and imports {offending}; "
        "SQL, migrations, and drivers live behind the persistence ports"
    )


@pytest.mark.parametrize(
    "path", [p for p in _modules() if _layer_of(p) == "application"], ids=lambda p: str(p.name)
)
def test_application_imports_no_provider_or_parser_module(path: Path) -> None:
    """`MB-AC-002`: only a composition root chooses a concrete implementation."""
    offending = sorted(
        {i.split(".")[0] for i in _imported_modules(path)} & PROVIDER_AND_PARSER_ROOTS
    )
    assert not offending, (
        f"{path.relative_to(PACKAGE)} is application code and imports {offending}; "
        "a provider or parser is chosen by a composition root, not by a use case"
    )


#: Names that instantiate a concrete implementation of a port. An application
#: module that mentions one has composed something.
CONCRETE_IMPLEMENTATIONS = frozenset(
    {"FixtureSourceProvider", "SqlAlchemyUnitOfWork", "create_database_engine", "create_engine"}
)


@pytest.mark.parametrize(
    "path", [p for p in _modules() if _layer_of(p) == "application"], ids=lambda p: str(p.name)
)
def test_only_a_composition_root_instantiates_a_concrete_implementation(path: Path) -> None:
    """`MB-AC-002`, second half: composition is not a use case's decision.

    The import rules above catch the module-level crossing. This catches the name
    itself, wherever it appears — including inside a function, which is where an
    import guard is easiest to slip past.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    named = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id in CONCRETE_IMPLEMENTATIONS
    } | {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in CONCRETE_IMPLEMENTATIONS
    }
    assert not named, (
        f"{path.relative_to(PACKAGE)} is application code and names {sorted(named)}; "
        "only a composition root instantiates a concrete implementation"
    )


#: One planted import per guard set, so a set narrowed to nothing cannot keep
#: reporting success. Each of the three rules above is a set intersection, and an
#: intersection with an empty set is empty for every module in the tree.
PLANTED_IMPORTS = [
    ("import starlette", "TRANSPORT_ROOTS"),
    ("import anyio", "TRANSPORT_ROOTS"),
    ("import asyncio", "TRANSPORT_ROOTS"),
    ("from mcp.server import Server", "TRANSPORT_ROOTS"),
    ("import sqlalchemy", "DATABASE_AND_FRAMEWORK_ROOTS"),
    ("from psycopg import connect", "DATABASE_AND_FRAMEWORK_ROOTS"),
    ("import alembic", "DATABASE_AND_FRAMEWORK_ROOTS"),
    ("import pypdf", "PROVIDER_AND_PARSER_ROOTS"),
    ("import paramiko", "PROVIDER_AND_PARSER_ROOTS"),
]

GUARD_SETS = {
    "TRANSPORT_ROOTS": TRANSPORT_ROOTS,
    "DATABASE_AND_FRAMEWORK_ROOTS": DATABASE_AND_FRAMEWORK_ROOTS,
    "PROVIDER_AND_PARSER_ROOTS": PROVIDER_AND_PARSER_ROOTS,
}


@pytest.mark.parametrize(("statement", "guard"), PLANTED_IMPORTS, ids=lambda v: str(v))
def test_the_application_import_guards_catch_a_planted_import(
    tmp_path: Path, statement: str, guard: str
) -> None:
    """The rules are read the way they read a real module, against a planted one."""
    planted = tmp_path / "planted.py"
    planted.write_text(f"{statement}\n", encoding="utf-8")
    roots = {imported.split(".")[0] for imported in _imported_modules(planted)}
    assert roots & GUARD_SETS[guard], f"{statement!r} escaped {guard}"


def test_the_composition_guard_catches_a_planted_instantiation(tmp_path: Path) -> None:
    """And it catches one hidden inside a function, which is the easy way past an import."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def wire(engine: object) -> object:\n"
        "    from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork\n"
        "\n"
        "    return SqlAlchemyUnitOfWork(engine)\n",
        encoding="utf-8",
    )
    tree = ast.parse(planted.read_text(encoding="utf-8"), filename=str(planted))
    named = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id in CONCRETE_IMPLEMENTATIONS
    }
    assert named == {"SqlAlchemyUnitOfWork"}
    assert {i.split(".")[0] for i in _imported_modules(planted)} == {"my_pa"}


def test_the_guarded_layers_have_modules_to_guard() -> None:
    # Parametrizing over an empty list collects nothing and reports success, so
    # the rules above would pass on a tree where `domain` had been deleted.
    for layer in ("domain", "application"):
        assert [p for p in _modules() if _layer_of(p) == layer], f"no module in '{layer}'"
    assert _infrastructure_modules(), f"no module in '{INFRASTRUCTURE}'"
