"""KLP-WP-04: the Knowledge persistence lock discipline, read statically (FAST).

KLP-AC-099 (static half; the real-race halves are the `tests/concurrency/`
modules) and R6 sections 5.2 / 8.1. Unmarked, routed to repository-checks /
validate and dependency-floor.

Over `src/my_pa/infrastructure/persistence/knowledge_assertions.py`:

* no `GREATEST`/`MAX` over classification text: the only SQL rank is
  `knowledge.knowledge_classification_rank(text)`;
* `lock_entity_mutation_scopes` (C3) is called at most once per transaction
  body -- once in explicit create, once in autonomous submit -- and never by
  the maintenance body;
* the one Capture fence (`require_active_capture_roots`, C4c) has one call
  site, `_capture_fence`, which each write path calls once;
* autonomous submit's Knowledge path takes its locks in the global order: C3
  (`_subject(lock=True)`) -> C4a (`_profile(lock=True)`) -> C4b
  (`_resolve_evidence`) -> C4c (`_capture_fence`) -> C5
  (`_equivalent_proposals(lock=True)`) -> C6 (`_lock_subject`), and nothing
  after C6 (`_decide_under_lock` and the writers it calls) acquires a C3-C5
  lock or re-locks evidence;
* the C4b `SELECT` is one statement whose mode is chosen once
  (`with_for_update()` vs `with_for_update(read=True)`), never upgraded later.

Slice C adds the Knowledge Review body (`_ReviewDecision`, KLP-AC-099 Review
order): C3 (`lock_entity_mutation_scopes`, once) -> `_lock_evidence` (C4b, one
sorted `FOR SHARE` SELECT) -> `_capture_fence` (C4c, once) -> `_proposal(lock=True)`
(C5) -> `_lock_subjects` (C6, once), and nothing after C6 (`_insert_decision`,
`_mutation`, `_promote`) takes a C3-C5 lock or re-locks evidence or the proposal.

Slice E (finalisation) closes the static half over every transaction body:

* every row lock on `knowledge_evidence_refs` is taken by exactly one method per
  body (`_resolve_evidence` for explicit create and submit, `_lock_evidence`
  for Review and maintenance), in the one mode the body needs: create/submit
  choose FOR UPDATE vs FOR SHARE once in one conditional expression, Review
  only shares, maintenance only takes FOR UPDATE; no other method that reads
  the evidence table locks it, and no method calls its body's evidence-lock
  method twice -- so FOR UPDATE never follows FOR SHARE on an evidence row in
  one path;
* the checkpoint body takes no C3 and no evidence lock;
* no Knowledge module (domain, application, persistence, the operator CLI)
  spells `GREATEST`/`MAX` over classification text.
"""

from __future__ import annotations

import ast
import re
from functools import cache
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
MODULE: Final = ROOT / "src/my_pa/infrastructure/persistence/knowledge_assertions.py"

C3_TO_C5: Final = frozenset(
    {"lock_entity_mutation_scopes", "_subject", "_profile", "_resolve_evidence", "_capture_fence"}
)
POST_C6: Final = ("_decide_under_lock", "_enrich", "_supersede", "_create", "_propose")


@cache
def _tree() -> ast.Module:
    return ast.parse(MODULE.read_text(encoding="utf-8"))


def _class(name: str) -> ast.ClassDef:
    for node in _tree().body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not defined")


def _method(owner: ast.ClassDef, name: str) -> ast.FunctionDef:
    for node in owner.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{owner.name}.{name} is not defined")


def _called(node: ast.AST) -> list[tuple[int, str, ast.Call]]:
    calls: list[tuple[int, str, ast.Call]] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name is not None:
                calls.append((child.lineno, name, child))
    return sorted(calls, key=lambda item: item[0])


def _keyword(call: ast.Call, name: str) -> object:
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    return None


KNOWLEDGE_MODULES: Final = (
    MODULE,
    ROOT / "src/my_pa/application/knowledge_assertions.py",
    ROOT / "apps/cli/knowledge_source_profiles.py",
    *sorted((ROOT / "src/my_pa/domain/knowledge_assertion").glob("*.py")),
)
_GREATEST: Final = re.compile(r"(?i:GREATEST\s*\(|func\.greatest|func\.max\()|\bMAX\s*\(")
#: Body -> (the one evidence-lock method, the lock modes it may use).
EVIDENCE_LOCKS: Final = {
    "_ExplicitCreate": ("_resolve_evidence", frozenset({None, True})),
    "_AutonomousSubmit": ("_resolve_evidence", frozenset({None, True})),
    "_ReviewDecision": ("_lock_evidence", frozenset({True})),
    "_Maintenance": ("_lock_evidence", frozenset({None})),
}
EVIDENCE_NAMES: Final = frozenset({"knowledge_evidence_refs", "_EVIDENCE", "_SIBLING"})


def _python_max_over_classification(text: str) -> list[int]:
    """Lines where builtin `max`/`min` ranges over a classification (lexical, not rank)."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(text)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"max", "min"}
            and "classification" in (ast.get_source_segment(text, node) or "").lower()
            and not any(keyword.arg == "key" for keyword in node.keywords)
        ):
            lines.append(node.lineno)
    return lines


def test_no_greatest_or_max_over_classification_text() -> None:
    for path in KNOWLEDGE_MODULES:
        text = path.read_text(encoding="utf-8")
        assert not _GREATEST.search(text), path.relative_to(ROOT).as_posix()
        assert _python_max_over_classification(text) == [], path.relative_to(ROOT).as_posix()


def test_the_greatest_detector_is_not_vacuous() -> None:
    assert len(KNOWLEDGE_MODULES) > 5
    for planted in (
        "GREATEST(a.classification, b.classification)",
        "func.greatest(x, y)",
        "func.max(e.c.source_classification)",
        "SELECT MAX(source_classification) FROM e",
    ):
        assert _GREATEST.search(planted), planted
    assert _python_max_over_classification("x = max(a.classification, b.classification)\n")
    assert not _python_max_over_classification(
        "x = max(classes, key=CLASSIFICATION_RANK.__getitem__)\n"
    )
    assert not _GREATEST.search("knowledge.knowledge_classification_rank(classification)")


def _reads_evidence(method: ast.FunctionDef) -> bool:
    return any(
        isinstance(node, ast.Name) and node.id in EVIDENCE_NAMES for node in ast.walk(method)
    )


def _lock_modes(method: ast.FunctionDef) -> list[object]:
    return [
        _keyword(call, "read") for _l, name, call in _called(method) if name == "with_for_update"
    ]


def test_each_body_locks_evidence_in_one_method_and_one_chosen_mode() -> None:
    for body_name, (locker, modes) in EVIDENCE_LOCKS.items():
        body = _class(body_name)
        lockers = [
            method.name
            for method in body.body
            if isinstance(method, ast.FunctionDef)
            and _reads_evidence(method)
            and _lock_modes(method)
        ]
        assert lockers == [locker], (body_name, lockers)
        method = _method(body, locker)
        assert set(_lock_modes(method)) == modes, body_name
        if len(modes) == 2:
            # Both modes sit in one conditional expression: chosen once, never upgraded.
            choices = [node for node in ast.walk(method) if isinstance(node, ast.IfExp)]
            assert any(
                {name for _l, name, _c in _called(choice)} >= {"with_for_update"}
                and len([1 for _l, n, _c in _called(choice) if n == "with_for_update"]) == 2
                for choice in choices
            ), body_name
        for caller in body.body:
            if isinstance(caller, ast.FunctionDef):
                count = [name for _l, name, _c in _called(caller)].count(locker)
                assert count <= 1, f"{body_name}.{caller.name} locks evidence {count} times"


def test_the_checkpoint_body_takes_no_entity_scope_and_no_evidence_lock() -> None:
    body = _class("_CheckpointAdvance")
    calls = [name for _l, name, _c in _called(body)]
    assert "lock_entity_mutation_scopes" not in calls
    assert "_capture_fence" not in calls
    for method in body.body:
        if isinstance(method, ast.FunctionDef):
            assert not _reads_evidence(method), method.name


def test_the_entity_scope_is_taken_once_per_write_body_and_never_by_maintenance() -> None:
    for body, expected in (
        ("_ExplicitCreate", 1),
        ("_AutonomousSubmit", 1),
        ("_ReviewDecision", 1),
        ("_Maintenance", 0),
    ):
        calls = [name for _l, name, _c in _called(_class(body))]
        assert calls.count("lock_entity_mutation_scopes") == expected, body


def test_the_capture_fence_has_one_call_site_called_once_per_write_body() -> None:
    text = MODULE.read_text(encoding="utf-8")
    assert text.count("require_active_capture_roots(") == 1
    for body in ("_ExplicitCreate", "_AutonomousSubmit", "_ReviewDecision"):
        calls = [name for _l, name, _c in _called(_class(body))]
        assert calls.count("_capture_fence") == 1, body
    assert "_capture_fence" not in [name for _l, name, _c in _called(_class("_Maintenance"))]


def test_the_submit_knowledge_path_takes_c3_to_c6_in_the_global_order() -> None:
    knowledge = _method(_class("_AutonomousSubmit"), "_knowledge")
    order: list[str] = []
    for _line, name, call in _called(knowledge):
        if name in {"_subject", "_profile"} and _keyword(call, "lock") is True:
            order.append(name)
        elif name == "_equivalent_proposals" and _keyword(call, "lock") is True:
            order.append("C5")
        elif name in {"_resolve_evidence", "_capture_fence", "_lock_subject"}:
            order.append(name)
    assert order == [
        "_subject",
        "_profile",
        "_resolve_evidence",
        "_capture_fence",
        "C5",
        "_lock_subject",
    ]


def test_nothing_after_c6_acquires_a_c3_to_c5_lock() -> None:
    body = _class("_AutonomousSubmit")
    for name in POST_C6:
        for _line, called, call in _called(_method(body, name)):
            assert called not in C3_TO_C5, f"{name} calls {called} after C6"
            if called == "_equivalent_proposals":
                assert _keyword(call, "lock") is not True, f"{name} re-locks proposals after C6"


def test_the_c4b_lock_mode_is_chosen_once_in_one_statement() -> None:
    resolve = _method(_class("_AutonomousSubmit"), "_resolve_evidence")
    modes = [call for _l, name, call in _called(resolve) if name == "with_for_update"]
    # One conditional expression picks the strongest needed mode for the one SELECT.
    assert len(modes) == 2
    assert {_keyword(call, "read") for call in modes} == {None, True}
    source = ast.get_source_segment(MODULE.read_text(encoding="utf-8"), resolve) or ""
    assert source.count(".order_by(e.c.evidence_ref_id)") == 1


def test_the_review_promotion_takes_c3_to_c6_in_the_global_order() -> None:
    run = _method(_class("_ReviewDecision"), "run")
    order: list[str] = []
    for _line, name, call in _called(run):
        if name in {"lock_entity_mutation_scopes", "_lock_evidence", "_capture_fence"}:
            order.append(name)
        elif name == "_proposal" and _keyword(call, "lock") is True:
            order.append("C5")
        elif name == "_lock_subjects":
            order.append(name)
    assert order == [
        "lock_entity_mutation_scopes",
        "_lock_evidence",
        "_capture_fence",
        "C5",
        "_lock_subjects",
    ]


def test_nothing_after_the_review_c6_acquires_a_c3_to_c5_lock() -> None:
    body = _class("_ReviewDecision")
    forbidden = {"lock_entity_mutation_scopes", "_lock_evidence", "_capture_fence"}
    for name in ("_insert_decision", "_mutation", "_promote"):
        for _line, called, call in _called(_method(body, name)):
            assert called not in forbidden, f"{name} calls {called} after C6"
            assert called != "_lock_subjects", f"{name} re-locks subjects after C6"
            if called == "_proposal":
                assert _keyword(call, "lock") is not True, f"{name} re-locks the proposal"
            assert called != "with_for_update", f"{name} takes a row lock after C6"
    run = _method(body, "run")
    c6 = next(line for line, name, _c in _called(run) if name == "_lock_subjects")
    for line, name, call in _called(run):
        if line > c6:
            assert name not in forbidden, f"run calls {name} after C6"
            if name == "_proposal":
                assert _keyword(call, "lock") is not True


def test_the_review_evidence_lock_is_one_sorted_share_select() -> None:
    lock = _method(_class("_ReviewDecision"), "_lock_evidence")
    modes = [call for _l, name, call in _called(lock) if name == "with_for_update"]
    assert len(modes) == 1
    assert _keyword(modes[0], "read") is True
    source = ast.get_source_segment(MODULE.read_text(encoding="utf-8"), lock) or ""
    assert source.count(".order_by(e.c.evidence_ref_id)") == 1
