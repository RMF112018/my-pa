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

#: Dependencies the phase forbids, by import root.
PROHIBITED_IMPORT_ROOTS = frozenset(
    {
        "fastapi",
        "starlette",
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


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.name))
def test_no_prohibited_dependency_is_imported(path: Path) -> None:
    offending = _imports(path) & PROHIBITED_IMPORT_ROOTS
    assert not offending, f"{path.relative_to(PACKAGE)} imports out-of-scope {sorted(offending)}"


def test_declared_runtime_dependencies_are_the_agreed_set() -> None:
    """Runtime dependencies are enumerated, not open-ended.

    Adding one has to be a deliberate edit here as well as in `pyproject.toml`,
    which is what keeps "a library for that" from arriving unremarked.
    """
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = data["project"]["dependencies"]
    roots = {re.split(r"[><=!~\[]", item)[0].strip().lower() for item in runtime}
    assert roots == {"pydantic", "sqlalchemy", "psycopg", "alembic"}


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
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = list(data["project"]["dependencies"])
    for group in data["project"].get("optional-dependencies", {}).values():
        declared.extend(group)
    roots = {re.split(r"[><=!\[]", item)[0].strip().lower() for item in declared}
    assert not (roots & PROHIBITED_IMPORT_ROOTS)


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
#: `registry` was a bare term here until the source registry entered scope. The
#: MCV specification section 9.6 requires registering and enrolling configured
#: sources, so a registry of sources is a product capability, not an extension
#: point, and banning the word outright would have forced a worse name on a
#: required concept. The speculative sense is what the guard was for, so the
#: compounds that carry that sense stay banned and the bare noun no longer is.
#:
#: Narrowing a guard is only safe if the guard still bites, which
#: `test_the_speculative_module_guard_still_catches_what_it_is_for` proves.
_SPECULATIVE_MODULE_NAMES = re.compile(
    r"(plugin|factory_factory|abstract_base|extension_point"
    r"|(?:plugin|service|provider|component|handler|adapter|capability)_registry)",
    re.I,
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


@pytest.mark.parametrize("name", ["registry.py", "sources.py", "enrollment.py", "jobs.py"])
def test_the_speculative_module_guard_permits_domain_nouns(name: str) -> None:
    """The narrowing is deliberate and bounded, not incidental."""
    assert not _SPECULATIVE_MODULE_NAMES.search(name), f"{name} should be permitted"
