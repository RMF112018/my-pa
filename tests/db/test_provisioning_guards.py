"""Static guards that ordinary current-schema tests do not replay Alembic."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
TESTS: Final = ROOT / "tests"
WORKFLOW: Final = ROOT / ".github/workflows/repository-checks.yml"

#: Files that still call Alembic for an explicit migration-contract fixture
#: living beside ordinary current-schema tests. Documented exceptions, not a
#: second provisioning path.
EXCEPTION_EXPLICIT_UPGRADE: Final = frozenset(
    {
        "tests/contract/test_health_probe.py",
    }
)

MIGRATION_MARKERS: Final = frozenset(
    {
        "migration",
        "migration_edge",
        "migration_empty_to_head",
        "migration_historical",
    }
)


def _python_files() -> tuple[Path, ...]:
    return tuple(path for path in TESTS.rglob("*.py") if path.name != "__pycache__")


def _marker_names(node: ast.AST) -> frozenset[str]:
    names: set[str] = set()
    for decorator in getattr(node, "decorator_list", ()):
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute):
            names.add(target.attr)
    return frozenset(names)


def test_create_database_lives_only_in_the_owned_provisioning_helper() -> None:
    offenders: list[str] = []
    for path in _python_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("tests/db/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if 'CREATE DATABASE "' in node.value or "CREATE DATABASE '" in node.value:
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, "CREATE DATABASE must go through tests/db/provisioning.py:\n" + "\n".join(
        offenders
    )


def test_ordinary_current_schema_modules_do_not_call_alembic_upgrade() -> None:
    offenders: list[str] = []
    for path in _python_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("tests/db/"):
            continue
        if rel in EXCEPTION_EXPLICIT_UPGRADE:
            continue
        if rel.endswith("_migration.py") or rel.endswith(
            "test_every_revision_denotes_one_schema.py"
        ):
            continue
        if rel.endswith("test_head_round_trip.py"):
            continue
        if rel.startswith("tests/migration/"):
            continue
        if rel.endswith("test_ri_remediation_predecessor_migration.py"):
            continue
        source = path.read_text(encoding="utf-8")
        if "command.upgrade" not in source and "alembic_command.upgrade" not in source:
            continue
        tree = ast.parse(source, filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if _marker_names(node) & MIGRATION_MARKERS:
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
                    continue
                if child.func.attr != "upgrade":
                    continue
                owner = child.func.value
                if isinstance(owner, ast.Name) and owner.id in {"command", "alembic_command"}:
                    offenders.append(f"{rel}:{node.name}:{node.lineno}")
                    break
    assert offenders == [], "ordinary current-schema tests still call Alembic:\n" + "\n".join(
        offenders
    )


def test_pr_ci_keeps_the_split_database_lanes() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for job in (
        "database-current-head:",
        "database-recovery:",
        "migration-empty-to-head:",
        "migration-edge:",
        "database-e2e:",
        "database-tier:",
    ):
        assert job in text, job
    assert "python -m pytest -m migration_empty_to_head" in text
    assert "python -m pytest -m recovery" in text
    assert "python -m pytest -m e2e" in text
    assert 'python -m pytest -m "migration_edge or migration"' in text
