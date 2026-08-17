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
#:
#: `adapters` joined the list with the HTTP transport (`D-23`), between
#: `application` and `bootstrap`, and its position is the whole of the rule: a
#: driving adapter may reach the application, a composition root may reach an
#: adapter, and an application module that imports one has inverted the
#: direction a transport exists to establish.
LAYER_ORDER: tuple[str, ...] = ("domain", "contracts", "application", "adapters", "bootstrap")

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
    {"boto3", "fitz", "paramiko", "pdfminer", "pypdf", "pypdfium2", "smbclient"}
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


# `MB-AC-002` reads as a structural guarantee, and a rule that only inspects a
# module's own imports is weaker than it reads. A reviewer proved it: planting
# `import sqlalchemy` at the top of `contracts/ports.py` — the module every
# handler imports — left the whole suite green, because `contracts` is the one
# layer with no third-party guard (pydantic is deliberately allowed there) and
# the application rules above look only one hop. The two rules below close that,
# and they close it in the general form rather than by adding one more
# per-layer allowlist: the second walks the import graph, so any future module
# that becomes reachable from `application` is covered without being named.

#: Everything an application module may not reach, by any path.
FORBIDDEN_FOR_APPLICATION = (
    TRANSPORT_ROOTS | DATABASE_AND_FRAMEWORK_ROOTS | PROVIDER_AND_PARSER_ROOTS
)


def _module_name(path: Path) -> str:
    """The dotted name of one module, with `__init__` folded into its package."""
    parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _module_index() -> dict[str, Path]:
    return {_module_name(path): path for path in _modules()}


def _internal_imports(path: Path, index: dict[str, Path]) -> set[str]:
    """The `my_pa` modules `path` imports, resolved to modules that exist.

    Each dotted target is shortened until it names a real module, and it is worth
    being exact about what that loop does, because the comment here previously
    credited it with carrying the walk and a reviewer showed it does not: with
    the loop deleted the suite still passed.

    It is redundancy, not the mechanism. `_imported_modules` contributes
    `node.module` for every `from X import Y` *independently* of `X.Y`, and an
    `import a.b.c` is only legal when `c` is itself a module — so every legal
    import already contributes at least one token that is an exact module name,
    and the shortening resolves nothing the exact token would not have resolved.
    `from my_pa.contracts.ports import UnitOfWork` yields `my_pa.contracts.ports`
    on its own; only the useless `…ports.UnitOfWork` needs shortening.

    It is kept rather than deleted because what makes it redundant is a property
    of a *different* function. The day `_imported_modules` stops emitting
    `node.module` — a plausible simplification, since that entry looks duplicated
    beside `X.Y` — this loop becomes the only thing resolving a `from` import,
    and the walk would otherwise stop one hop out in silence. A guard whose
    failure mode is a hole that reports success is worth six redundant lines.
    """
    found: set[str] = set()
    for imported in _imported_modules(path):
        if not imported.startswith("my_pa"):
            continue
        parts = imported.split(".")
        while parts:
            candidate = ".".join(parts)
            if candidate in index:
                found.add(candidate)
                break
            parts.pop()
    return found


def _packages_of(name: str) -> list[str]:
    """Every package that importing `name` also executes.

    `import my_pa.contracts.v1.envelope` runs `my_pa/__init__.py`,
    `my_pa/contracts/__init__.py` and `my_pa/contracts/v1/__init__.py` before it
    runs the module itself. A walk that followed only the module's own imports
    therefore under-reported what a module can reach by exactly the amount those
    files import — which was not nothing: `contracts/v1/__init__.py` re-exports
    the whole v1 surface.
    """
    parts = name.split(".")
    return [".".join(parts[:count]) for count in range(1, len(parts))]


def _reachable(start: Path, index: dict[str, Path]) -> set[str]:
    """Every `my_pa` module reachable from `start`, including `start` itself.

    **Parent packages count, and leaving them out was a hole.** An independent
    review appended an infrastructure import to `src/my_pa/contracts/v1/__init__.py`
    and every architecture test passed, while importing `my_pa.adapters.http.app`
    demonstrably loaded SQLAlchemy: the closure held
    `my_pa.contracts.v1.envelope` but not `my_pa.contracts.v1`, so nothing ever
    read the file the violation was in. This is the same shape of hole WP-4A
    found in the one-hop rules and replaced this walk to close, one level up.
    `_packages_of` is the fix, and it strengthens every rule built on this walk
    rather than only the one that caught it.
    """
    seen: set[str] = set()
    queue = [_module_name(start)]
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        queue.extend(_packages_of(name))
        path = index.get(name)
        if path is not None:
            queue.extend(_internal_imports(path, index))
    return seen


@pytest.mark.parametrize(
    "path", [p for p in _modules() if _layer_of(p) == "contracts"], ids=lambda p: str(p.name)
)
def test_contracts_import_no_transport_orm_or_provider_module(path: Path) -> None:
    """`module-boundaries.md` section 5.2: a DTO exposes no ORM or provider object.

    Pydantic stays permitted — `test_pydantic_is_confined_to_contracts_and_settings`
    is what says where it belongs — and everything that would carry a persistence
    or transport concern does not. This layer had no third-party guard at all,
    which made it the available way past the application rules above.
    """
    offending = sorted(
        {i.split(".")[0] for i in _imported_modules(path)} & FORBIDDEN_FOR_APPLICATION
    )
    assert not offending, (
        f"{path.relative_to(PACKAGE)} is contract code and imports {offending}; "
        "public schemas and ports may not carry a persistence or transport detail"
    )


@pytest.mark.parametrize(
    "path", [p for p in _modules() if _layer_of(p) == "application"], ids=lambda p: str(p.name)
)
def test_application_reaches_no_forbidden_module_by_any_path(path: Path) -> None:
    """`MB-AC-002` as a property of the import graph, not of one hop.

    An application module is isolated from transport, ORM, provider, and parser
    detail only if *everything it can reach* is. This walks the closure and
    reports the shortest evidence it has: the module that actually imports the
    offending root.
    """
    index = _module_index()
    offences: list[str] = []
    for name in sorted(_reachable(path, index)):
        reached = index.get(name)
        if reached is None:
            continue
        offending = sorted(
            {i.split(".")[0] for i in _imported_modules(reached)} & FORBIDDEN_FOR_APPLICATION
        )
        if offending:
            offences.append(f"{name} imports {offending}")
    assert not offences, (
        f"{path.relative_to(PACKAGE)} is application code and reaches "
        f"{offences}; MB-AC-002 is about what a use case can reach, not about "
        "what it names directly"
    )


@pytest.mark.parametrize(
    "path", [p for p in _modules() if _layer_of(p) == "application"], ids=lambda p: str(p.name)
)
def test_application_reaches_no_transport_adapter_by_any_path(path: Path) -> None:
    """`MB-AC-002` against the transport that now exists, not only its libraries.

    The third-party rule above catches an application module that reaches
    Starlette. It does not catch one that reaches `my_pa.adapters.normalization`,
    which imports nothing third-party at all and is still a transport concern —
    and a transport the application can call is a transport the application
    depends on. This walks the same closure the rule above walks, so a future
    adapter is covered by having been added rather than by being named.
    """
    index = _module_index()
    offences = sorted(
        name
        for name in _reachable(path, index)
        if name == "my_pa.adapters" or name.startswith("my_pa.adapters.")
    )
    assert not offences, (
        f"{path.relative_to(PACKAGE)} is application code and reaches {offences}; "
        "a transport calls the application, never the other way round"
    )


def test_the_transport_reachability_rule_has_a_transport_to_find() -> None:
    """Guard the rule above: with no adapter in the tree it proves nothing.

    It is a rule about the *absence* of a name, so it passes on a tree where the
    name could not appear. This requires the adapters to exist, and requires
    something outside `application` to actually reach them — the composition
    root — so that "nothing reaches the adapters" is never trivially true.
    """
    index = _module_index()
    adapters = sorted(name for name in index if name.startswith("my_pa.adapters"))
    assert len(adapters) >= 3, f"only {adapters} were found"
    composition = index["my_pa.bootstrap.gateway"]
    reached = _reachable(composition, index)
    assert "my_pa.application.service" in reached, "the composition root reaches no application"


#: Everything a *driving adapter* may not reach, by any path. `starlette` is
#: subtracted from the framework list and nothing else is: it is this
#: transport's own library, and `test_scope_and_hygiene.py` is what confines it
#: to `adapters/http`. What remains is every store, driver, ORM, parser,
#: provider SDK — and every *other* framework, including `fastapi`, which `D-25`
#: excluded on the grounds that a second validation layer is what makes parity
#: unprovable, and `uvicorn`, which belongs to the composition root.
FORBIDDEN_FOR_ADAPTERS = (DATABASE_AND_FRAMEWORK_ROOTS | PROVIDER_AND_PARSER_ROOTS) - {"starlette"}


@pytest.mark.parametrize(
    "path", [p for p in _modules() if _layer_of(p) == "adapters"], ids=lambda p: str(p.name)
)
def test_adapters_reach_no_forbidden_module_by_any_path(path: Path) -> None:
    """`module-boundaries.md` section 5.7, as a property of the import graph.

    `test_transport_adds_no_behaviour.py` states the same rule one hop out, and
    one hop is not the rule: a transport that reaches a store through two
    modules has reached a store. An independent review proved the difference by
    putting the violation in a package `__init__`, where no one-hop rule looks
    and where the walk did not look either until `_packages_of` above.
    """
    index = _module_index()
    offences: list[str] = []
    for name in sorted(_reachable(path, index)):
        reached = index.get(name)
        if reached is None:
            continue
        offending = sorted(
            {i.split(".")[0] for i in _imported_modules(reached)} & FORBIDDEN_FOR_ADAPTERS
        )
        if offending:
            offences.append(f"{name} imports {offending}")
    assert not offences, (
        f"{path.relative_to(PACKAGE)} is transport code and reaches {offences}; "
        "a transport reaches the application and nothing behind it"
    )


def test_the_adapter_walk_resolves_a_package_init(tmp_path: Path) -> None:
    """Guard the fix itself: the closure must contain the files it once skipped.

    Named rather than counted, because the hole was precisely that two real
    modules — a package and its parent — were absent from a closure that
    contained their children.
    """
    index = _module_index()
    reached = _reachable(PACKAGE / "adapters" / "http" / "app.py", index)
    assert "my_pa.contracts.v1" in reached, "the walk still skips the package __init__"
    assert "my_pa.contracts" in reached
    assert "my_pa.application" in reached
    assert "my_pa.adapters.http" in reached


def test_the_reachability_walk_actually_walks(tmp_path: Path) -> None:
    """Guard the walk: one that resolved nothing would pass on any tree.

    A closure that stopped at the starting module would make the rule above a
    slower copy of the one-hop rules. `service.py` is the deepest importer in the
    package, so it is the honest sample.
    """
    index = _module_index()
    service = PACKAGE / "application" / "service.py"
    reached = _reachable(service, index)
    assert "my_pa.contracts.ports" in reached, "the walk did not resolve a `from` import"
    assert "my_pa.domain.policy.decision" in reached, "the walk stopped before the domain"
    assert len(reached) >= 20, f"the walk resolved only {len(reached)} modules"


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
    ("import pypdfium2", "PROVIDER_AND_PARSER_ROOTS"),
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
