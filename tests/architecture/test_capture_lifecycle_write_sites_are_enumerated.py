"""CRL-AC-D5: the lifecycle writer's write sites are enumerated.

`transition_capture` may insert one lifecycle event, insert one receipt, and
suspend or resume that root's jobs. A new write on the lifecycle port, the
capture store, or the record-event buffer fails here.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
SOURCE: Final = ROOT / "src" / "my_pa" / "application" / "capture_lifecycle.py"

LIFECYCLE_WRITES: Final = frozenset(
    {"suspend_jobs", "resume_jobs", "record_event", "record_receipt"}
)
LIFECYCLE_READS: Final = frozenset({"lock_root", "receipt", "latest"})


def _transition() -> ast.FunctionDef:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    found = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "transition_capture"
    ]
    assert len(found) == 1
    return found[0]


def _receiver(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _attribute_calls(function: ast.FunctionDef) -> set[tuple[str, str]]:
    calls: set[tuple[str, str]] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        receiver = _receiver(node.func.value)
        if receiver is not None:
            calls.add((receiver, node.func.attr))
    return calls


def test_transition_capture_writes_only_the_event_the_receipt_and_the_jobs() -> None:
    calls = _attribute_calls(_transition())
    lifecycle = {name for owner, name in calls if owner == "lifecycle"}
    assert lifecycle == LIFECYCLE_WRITES | LIFECYCLE_READS
    assert ("captures", "version") in calls
    assert ("record_events", "stage") in calls
    assert ("lifecycle", "record_event") in calls
    assert ("lifecycle", "record_receipt") in calls
