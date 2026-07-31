"""Phase 01 scope, neutral naming, and secret hygiene.

These guard the boundaries the phase is explicitly bounded by: no transport,
persistence, provider, or model dependency; neutral naming; nothing
secret-shaped committed.
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
        "sqlalchemy",
        "alembic",
        "psycopg",
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


def test_declared_runtime_dependency_is_pydantic_only() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = data["project"]["dependencies"]
    assert len(runtime) == 1
    assert runtime[0].startswith("pydantic")


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


def test_no_placeholder_or_speculative_module_was_added() -> None:
    # Phase 01 forbids plugin frameworks, registries, and speculative extension points.
    banned = re.compile(r"(plugin|registry|factory_factory|abstract_base|extension_point)", re.I)
    offenders = [p.relative_to(PACKAGE) for p in _modules() if banned.search(p.name)]
    assert not offenders, f"speculative modules present: {offenders}"
