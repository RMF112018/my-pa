"""T-19 (WP-RE-01; R-009): the Record Event allocator is a row lock, never an advisory lock.

RE-AC-007 and RE-AC-014. The lock-order proof (TRANSACTION matrix section 5)
needs the allocator's only lock to be the `record_event_sequences` row lock that
`INSERT ... ON CONFLICT ... DO UPDATE` takes and holds to COMMIT. An advisory
lock would be a second, Principal-wide serialization point with its own wait
edges, which the proof does not account for (G1-TX-008).

`GLOBAL_ADVISORY_LOCK_CALLS` in `test_user_owned_tables_are_partitioned.py`
counts only `native_sources.py`'s three calls and does not reach this module
(T-010), so this is the guard that does.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
ALLOCATOR: Final = ROOT / "src" / "my_pa" / "infrastructure" / "persistence" / "record_events.py"

#: Any spelling of a PostgreSQL advisory-lock function: `pg_advisory_lock`,
#: `pg_advisory_xact_lock`, `pg_try_advisory_...`, shared variants.
ADVISORY: Final = re.compile(r"pg_(?:try_)?advisory", re.IGNORECASE)


def _code_text() -> str:
    """Every string and name in the module's code, docstrings excluded."""
    tree = ast.parse(ALLOCATOR.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    parts: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                parts.append(node.value)
        elif isinstance(node, ast.Name):
            parts.append(node.id)
        elif isinstance(node, ast.Attribute):
            parts.append(node.attr)
    return "\n".join(parts)


def test_the_allocator_module_names_no_advisory_lock() -> None:
    assert not ADVISORY.search(_code_text())


def test_the_allocator_is_the_on_conflict_row_lock() -> None:
    """The positive half: the row-lock statement is what the module actually builds."""
    code = _code_text()
    assert "on_conflict_do_update" in code
    assert "record_event_sequences" in code


def test_the_scan_sees_an_advisory_lock_in_code() -> None:
    """The control: a planted call is found by the same pattern."""
    assert ADVISORY.search("func.pg_advisory_xact_lock(key)")
    assert ADVISORY.search("SELECT pg_try_advisory_lock(1)")
