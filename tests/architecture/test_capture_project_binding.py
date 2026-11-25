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
TABLES_MODULE: Final = ROOT / "src/my_pa/infrastructure/persistence/tables.py"
#: The `tables.py` declarations that shape `captures`, each sliced from source and
#: hashed in this order (precedent: `BASE_CONSTRAINT_TABLES_SHA256`), so a
#: migration editing another table leaves this pin alone.
CAPTURES_DECLARATIONS: Final = ("_IDENTIFIER_SUFFIX", "_is_identifier", "captures")
CAPTURES_DECLARATIONS_SHA256: Final = (
    "cd20aaef76d09a3188a0e57866a3e5924913eff7330cf7f2bc60eecaa7d418b8"
)
WP03_MIGRATION_SHA256: Final = "098edd98ccc1846b01c58f42e296e4751e7841b562a2827616cc4337e174c354"
WP03_MIGRATION: Final = (
    ROOT / "migrations/versions/20260914_e6a4c2f91b73_project_controls_run01_integrity.py"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _declarations(path: Path, names: tuple[str, ...]) -> str:
    """The source of each named module-level assignment or function, in `names` order."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    found: dict[str, str] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef):
            name = node.name
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        else:
            continue
        if name in names and node.end_lineno is not None:
            found[name] = "".join(lines[node.lineno - 1 : node.end_lineno])
    assert sorted(found) == sorted(names), f"tables.py declares {sorted(found)}, not {names}"
    return "".join(found[name] for name in names)


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
    captures_source = _declarations(TABLES_MODULE, CAPTURES_DECLARATIONS)
    assert hashlib.sha256(captures_source.encode("utf-8")).hexdigest() == (
        CAPTURES_DECLARATIONS_SHA256
    ), "the `captures` declaration in tables.py changed; it is frozen"
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


def test_the_capture_owner_comment_names_the_durable_partition() -> None:
    """RE-AC-108: the `capture_versions` comment states WP-03's durable partition.

    D-72's premise -- a restart mints a new principal, so the owner is recorded
    and never authorized on -- was dissolved by WP-03; the comment above the
    Table must say so, and the stale sentences must stay gone.
    """
    source = (ROOT / "src/my_pa/infrastructure/persistence/tables.py").read_text(encoding="utf-8")
    comment_lines = source.split("\ncapture_versions = Table(", 1)[0].rsplit("\n\n", 1)[1]
    comment = " ".join(line.removeprefix("#:").strip() for line in comment_lines.splitlines())
    assert "is the partition and is authorized on" in comment
    assert "superseding `D-72`" in comment
    assert "recorded and never authorized on" not in comment
    assert "a restart mints a new principal" not in comment
    assert "*not* an authorization input" not in source
