"""Static guards for the Capture-root Project binding."""

from __future__ import annotations

import ast
import dataclasses
import hashlib
from pathlib import Path
from typing import Final

from sqlalchemy.sql.selectable import TableClause

from my_pa.application.commands import CreateCapture, ReviseCapture
from my_pa.infrastructure.persistence import capture, capture_search
from my_pa.infrastructure.persistence.tables import captures

ROOT: Final = Path(__file__).resolve().parents[2]
TABLES_SHA256: Final = "49dc4fe963a4434a9d955ab2cf60e79d7c83b3c1ad04b2495451857467fef2f0"
WP03_MIGRATION_SHA256: Final = "098edd98ccc1846b01c58f42e296e4751e7841b562a2827616cc4337e174c354"
WP03_MIGRATION: Final = (
    ROOT / "migrations/versions/20260914_e6a4c2f91b73_project_controls_run01_integrity.py"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _calls(path: Path, receiver: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == receiver
    }


def test_frozen_capture_table_and_wp03_migration_are_byte_unchanged() -> None:
    assert _sha256(ROOT / "src/my_pa/infrastructure/persistence/tables.py") == TABLES_SHA256
    assert _sha256(WP03_MIGRATION) == WP03_MIGRATION_SHA256
    assert "project_id" not in captures.c


def test_runtime_projections_are_metadata_free_and_exact() -> None:
    expected = {"capture_id", "owner_principal_id", "created_at", "project_id"}
    for projected in (capture._capture_roots, capture_search._capture_roots):
        assert isinstance(projected, TableClause)
        assert not hasattr(projected, "metadata")
        assert set(projected.c.keys()) == expected
        assert projected.schema == "knowledge"


def test_project_binding_has_one_insert_and_no_update_or_delete_route() -> None:
    writer = ROOT / "src/my_pa/infrastructure/persistence/capture.py"
    assert _calls(writer, "_capture_roots") == {"insert"}
    source = writer.read_text(encoding="utf-8").upper()
    assert "UPDATE KNOWLEDGE.CAPTURES" not in source
    assert "DELETE FROM KNOWLEDGE.CAPTURES" not in source


def test_only_create_can_assign_a_project() -> None:
    assert "project_id" in {field.name for field in dataclasses.fields(CreateCapture)}
    assert "project_id" not in {field.name for field in dataclasses.fields(ReviseCapture)}
