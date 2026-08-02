"""Scope, neutral naming, and secret hygiene.

These guard the boundaries the work is bounded by: no transport, provider, or
model dependency; one PostgreSQL driver rather than several; neutral naming;
nothing secret-shaped committed.

A guard here is narrowed only when scope legitimately grows, never to make a
change pass. Each narrowing states its reason beside the pattern and is paired
with planted violations, so a relaxed guard cannot silently become a guard that
matches nothing.

Persistence entered scope with the PostgreSQL foundation, so SQLAlchemy,
Alembic, and `psycopg` moved from the prohibited list to the declared set below.
The alternative drivers stay prohibited: two drivers for one database is the
duplicate-library case AGENTS.md section 2 rules out, and it would make the
connection URL's scheme ambiguous.

The HTTP transport entered scope with WP-4B2a, and the two dependencies it
brings are narrowed differently rather than both being deleted from the list,
because they are permitted in different places and "permitted" would be weaker
than the truth in both cases:

* **Starlette is confined**, not admitted. It may be imported by
  `adapters/http`, which is the transport, and nowhere else — an application or
  infrastructure module that imported it would have taken a transport concern,
  and the layer rules in `test_dependency_direction.py` would not catch it,
  because they are about direction rather than about libraries.
* **uvicorn stays prohibited inside the package** and is a declared runtime
  dependency all the same. It is the server that runs the application, which is
  the composition root's business: `apps/gateway.py` imports it and nothing
  under `src/` may. That is why the declared-set check and the import check now
  read two different lists rather than one.

FastAPI stays prohibited. `D-25` chose Starlette precisely so that HTTP would
not acquire a second validation layer that the MCP adapter has no counterpart
for, and a dependency admitted "just for one route" is how that decision would
be reversed without being revisited.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
PACKAGE = SRC / "my_pa"

#: Dependencies no module under `src/my_pa` may import, by root. `uvicorn` is
#: here *and* declared in `pyproject.toml`: running a server is the composition
#: root's act, and `apps/gateway.py` lives outside this tree.
PROHIBITED_IMPORT_ROOTS = frozenset(
    {
        "fastapi",
        "uvicorn",
        "psycopg2",
        "asyncpg",
        "redis",
        "celery",
        "mcp",
        "anthropic",
        "openai",
        "httpx",
        "requests",
        "aiohttp",
        "neo4j",
        "chromadb",
        "pinecone",
        "pypdf",
        "pdfminer",
        "fitz",
        "paramiko",
        "boto3",
        "dotenv",
        "environs",
        "attrs",
        "marshmallow",
        "cerberus",
    }
)


def _modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


#: Dependencies the package may import in exactly one subtree, and the subtree.
#: See the module docstring: a transport library is not "in scope", it is in the
#: transport.
CONFINED_IMPORT_ROOTS = {"starlette": "adapters/http"}


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.name))
def test_no_prohibited_dependency_is_imported(path: Path) -> None:
    offending = _imports(path) & PROHIBITED_IMPORT_ROOTS
    assert not offending, f"{path.relative_to(PACKAGE)} imports out-of-scope {sorted(offending)}"


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.name))
def test_a_confined_dependency_is_imported_only_where_it_belongs(path: Path) -> None:
    where = path.relative_to(PACKAGE).as_posix()
    for root, subtree in CONFINED_IMPORT_ROOTS.items():
        if root not in _imports(path):
            continue
        assert where.startswith(f"{subtree}/"), (
            f"{where} imports {root!r}, which belongs to {subtree}/ and nowhere else"
        )


def test_every_confined_dependency_is_actually_used_there() -> None:
    """A confinement nothing tests is a rule about an empty set.

    Without this, deleting the transport would leave the rule above passing on
    every module in the tree while confining nothing.
    """
    for root, subtree in CONFINED_IMPORT_ROOTS.items():
        importers = [p for p in _modules() if root in _imports(p)]
        assert importers, f"nothing imports {root!r}; the confinement guards nothing"
        for path in importers:
            assert path.relative_to(PACKAGE).as_posix().startswith(f"{subtree}/")


def test_declared_runtime_dependencies_are_the_agreed_set() -> None:
    """Runtime dependencies are enumerated, not open-ended.

    Adding one has to be a deliberate edit here as well as in `pyproject.toml`,
    which is what keeps "a library for that" from arriving unremarked.
    """
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = data["project"]["dependencies"]
    roots = {re.split(r"[><=!~\[]", item)[0].strip().lower() for item in runtime}
    assert roots == {"pydantic", "sqlalchemy", "psycopg", "alembic", "starlette", "uvicorn"}


def test_every_runtime_dependency_declares_a_range() -> None:
    # A floor without a ceiling lets a major release land untested; a pin
    # without a floor makes the `dependency-floor` CI job meaningless.
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for item in data["project"]["dependencies"]:
        assert ">=" in item, f"{item} declares no lower bound"
        assert "<" in item.split(">=", 1)[1], f"{item} declares no upper bound"


def test_declared_dev_dependencies_are_the_agreed_set() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = data["project"]["optional-dependencies"]["dev"]
    roots = {re.split(r"[><=!\[]", item)[0].strip() for item in dev}
    assert roots == {"pytest", "ruff", "mypy"}


def test_no_declared_dependency_is_prohibited() -> None:
    """Nothing out of scope is declared, which is a narrower list than the imports.

    `uvicorn` is subtracted because it is deliberately both: declared, so the
    gateway process can run, and un-importable by the package, so that running a
    server stays the composition root's act. Every other prohibited root is
    prohibited outright and may not be declared either.
    """
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = list(data["project"]["dependencies"])
    for group in data["project"].get("optional-dependencies", {}).values():
        declared.extend(group)
    roots = {re.split(r"[><=!\[]", item)[0].strip().lower() for item in declared}
    assert not (roots & (PROHIBITED_IMPORT_ROOTS - {"uvicorn"}))


def test_the_only_shipped_module_that_runs_a_server_is_the_composition_root() -> None:
    """Across `src/` and `apps/`, `uvicorn` appears in exactly one file.

    The import rule above says the package may not import it. This says where it
    *is* imported, because "nowhere in the package" is also satisfied by a build
    with no gateway at all.

    **The scan is `src/` and `apps/`, and the qualifier is load-bearing.**
    `tests/wire.py` imports uvicorn and runs a server too, deliberately: the
    HTTP tests drive a real one rather than calling an ASGI app in process, and
    it imports `apps.gateway`'s own settings so the two configurations cannot
    drift. What is enforced here is that nothing *shipped* starts a server
    except the composition root, which is the property that matters; a test
    harness is not shipped, and naming this test after the wider claim would
    have made it read as one it does not check.
    """
    shipped = [*_modules(), *sorted((ROOT / "apps").rglob("*.py"))]
    importers = sorted(
        path.relative_to(ROOT).as_posix() for path in shipped if "uvicorn" in _imports(path)
    )
    assert importers == ["apps/gateway.py"]
    assert "uvicorn" in _imports(ROOT / "tests" / "wire.py"), (
        "the harness no longer runs a real server; this test's qualifier is stale"
    )


def test_package_uses_the_neutral_namespace() -> None:
    assert (SRC / "my_pa").is_dir()
    assert not list(SRC.glob("hb_*"))


def test_no_active_former_employer_identifier() -> None:
    pattern = re.compile(r"hb[-_]nas|hb[-_]intel|hbintel|hedrick", re.IGNORECASE)
    for path in [*_modules(), ROOT / "pyproject.toml", ROOT / ".env.example"]:
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), f"{path} names a legacy identity"


def test_configuration_prefix_is_neutral() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    declared = re.findall(r"^([A-Z][A-Z0-9_]*)=", example, flags=re.MULTILINE)
    assert declared
    assert all(name.startswith("MY_PA_") for name in declared)


def test_env_example_contains_no_secret_value() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    forbidden = re.compile(
        r"(password|secret|api[_-]?key|token|BEGIN [A-Z ]*PRIVATE KEY|postgres://|://[^/\s]+:[^@\s]+@)",
        re.IGNORECASE,
    )
    for line in example.splitlines():
        if line.strip().startswith("#") or not line.strip():
            continue
        assert not forbidden.search(line), f"possible secret in .env.example: {line}"


def test_no_source_file_embeds_a_personal_path_or_credential() -> None:
    forbidden = re.compile(
        r"(/Users/[a-z]|/home/[a-z]|/Volumes/|postgres://|BEGIN [A-Z ]*PRIVATE KEY|ssh\s+\w+-nas)",
        re.IGNORECASE,
    )
    for path in _modules():
        text = path.read_text(encoding="utf-8")
        assert not forbidden.search(text), f"{path} embeds a private value"


def test_every_package_directory_is_importable() -> None:
    for directory in {p.parent for p in _modules()}:
        assert (directory / "__init__.py").exists(), f"{directory} lacks __init__.py"


#: Module names that mean speculative machinery rather than a domain noun.
#:
#: `registry` was a bare term here until the source registry entered scope.
#: `docs/plans/mcv-completion-plan.md` section 7 names "source registry, bounded
#: enrollment with idempotency keys, job lease/retry, opaque ID issuance" as the
#: WP-2 deliverable, so a registry of sources is a planned product capability
#: rather than an extension point, and banning the word outright would have
#: forced a worse name on a required concept. The speculative sense is what the
#: guard was for, so the compounds carrying that sense stay banned.
#:
#: Two tests hold this pattern in place, and it is worth being exact about what
#: they can and cannot show. The planted violations below prove the pattern is
#: not vacuous; they cannot prove it is general, because any finite list of
#: examples is also satisfied by a pattern that matches only those examples.
#: `test_the_speculative_module_guard_is_exactly_this_pattern` closes that gap
#: structurally: shrinking the pattern to fit its own fixtures fails there.
#:
#: Coverage was genuinely lost, not merely relocated. The old bare term also
#: caught `tool_registry`, `strategy_registry`, `port_registry`, and
#: `registry_factory`; those are named below to recover them. It also caught
#: `source_registry`, which is now deliberately permitted — that name is the
#: legitimate one for this concept.
_SPECULATIVE_MODULE_NAMES = re.compile(
    r"(plugin|factory_factory|abstract_base|extension_point|registry_factory"
    r"|(?:plugin|service|provider|component|handler|adapter|capability|tool"
    r"|strategy|port)_registry)",
    re.I,
)

#: The pattern above, pinned. An edit to the guard has to be an edit here too.
_EXPECTED_SPECULATIVE_PATTERN = (
    r"(plugin|factory_factory|abstract_base|extension_point|registry_factory"
    r"|(?:plugin|service|provider|component|handler|adapter|capability|tool"
    r"|strategy|port)_registry)"
)


def test_no_placeholder_or_speculative_module_was_added() -> None:
    offenders = [
        p.relative_to(PACKAGE) for p in _modules() if _SPECULATIVE_MODULE_NAMES.search(p.name)
    ]
    assert not offenders, f"speculative modules present: {offenders}"


@pytest.mark.parametrize(
    "name",
    [
        "plugin.py",
        "plugin_loader.py",
        "plugin_registry.py",
        "service_registry.py",
        "provider_registry.py",
        "component_registry.py",
        "handler_registry.py",
        "adapter_registry.py",
        "capability_registry.py",
        "factory_factory.py",
        "abstract_base.py",
        "extension_point.py",
    ],
)
def test_the_speculative_module_guard_still_catches_what_it_is_for(name: str) -> None:
    """Planted violations, so narrowing the pattern cannot quietly gut it.

    Without this, a later edit could relax the pattern to the point where it
    matches nothing and the guard above would still pass, reporting a boundary
    it no longer enforces.
    """
    assert _SPECULATIVE_MODULE_NAMES.search(name), f"{name} should be rejected"


@pytest.mark.parametrize(
    "name", ["registry.py", "source_registry.py", "sources.py", "enrollment.py", "jobs.py"]
)
def test_the_speculative_module_guard_permits_domain_nouns(name: str) -> None:
    """The narrowing is deliberate and bounded, not incidental."""
    assert not _SPECULATIVE_MODULE_NAMES.search(name), f"{name} should be permitted"


def test_the_speculative_module_guard_is_exactly_this_pattern() -> None:
    """Pin the pattern, because planted violations alone cannot pin it.

    An anchored alternation of exactly the names listed above would satisfy
    every planted-violation test while catching nothing else. Comparing the
    pattern itself means a narrowing has to be written twice, deliberately,
    rather than arrived at by relaxing a regex until the suite goes green.
    """
    assert _SPECULATIVE_MODULE_NAMES.pattern == _EXPECTED_SPECULATIVE_PATTERN
