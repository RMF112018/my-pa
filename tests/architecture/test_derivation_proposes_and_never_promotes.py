"""Nothing derived promotes itself, and the claim is structural rather than stated.

`QC-AC-020` makes consequential classes review-gated, and the failure mode that
rule exists for is not a reviewer clicking the wrong button — it is a *derivation*
quietly writing its own output back as established fact. That path is easy to
open by accident and hard to notice, because it looks like a read.

Four properties, read off the tree rather than trusted:

1. **The Pulse derivation is a pure function.** `domain/situation/pulse_derivation.py`
   imports no persistence, no SQLAlchemy, and no infrastructure module, so there
   is nothing in it that could write.
2. **The repository's derivation is a read.** `SqlPulseRepository.derive_pulse`
   builds no `insert`, `update`, or `delete`, and calls nothing that does.
3. **Only one method writes `accepted`.** `ContinuityEvidenceState.ACCEPTED`
   appears in exactly one write in `situation_repository.py`, inside
   `SqlContinuityRepository.accept`; the three `propose_*` methods write the
   `PROPOSED` literal and take no parameter that could change it.
4. **Acceptance is gated on a review decision.** `accept` reads
   `capture_review_decisions` before it writes, so promotion cannot happen
   without a review that happened.

Nothing here opens a connection. It parses source.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"

DERIVATION: Final = PACKAGE / "domain" / "situation" / "pulse_derivation.py"
REPOSITORY: Final = PACKAGE / "infrastructure" / "persistence" / "situation_repository.py"

#: Statement builders that write. Named rather than inferred, because "does this
#: expression write" is not decidable in general and these five are what this
#: repository's persistence layer actually uses.
WRITERS: Final = frozenset({"insert", "update", "delete", "pg_insert", "execute"})


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(tree: ast.Module, *, klass: str, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == klass:
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == name:
                    return member
    raise AssertionError(f"{klass}.{name} is not in the module; the guard is reading nothing")


def _called_names(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        target = child.func
        if isinstance(target, ast.Name):
            found.add(target.id)
        elif isinstance(target, ast.Attribute):
            found.add(target.attr)
    return found


def test_the_derivation_module_imports_nothing_that_could_write() -> None:
    """Property 1. A pure function cannot promote, and this is why it is pure."""
    tree = _module(DERIVATION)
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imported, "the import scan read nothing"
    forbidden = sorted(
        name
        for name in imported
        if name.startswith(("sqlalchemy", "psycopg", "my_pa.infrastructure", "my_pa.application"))
    )
    assert forbidden == [], (
        f"{DERIVATION.name} imports {forbidden}. The Pulse derivation is a read over "
        "rows it is handed; a module that can reach a connection is a module that can "
        "write its own output back as accepted state"
    )
    assert _called_names(tree).isdisjoint(WRITERS)


def test_the_repositorys_derivation_builds_no_write() -> None:
    """Property 2, over `derive_pulse` itself rather than over the module."""
    derive = _function(_module(REPOSITORY), klass="SqlPulseRepository", name="derive_pulse")
    called = _called_names(derive)
    assert "select" in called, "the guard is not reading a method that queries anything"
    writes = sorted(called & (WRITERS - {"execute"}))
    assert writes == [], (
        f"SqlPulseRepository.derive_pulse builds {writes}. A derivation that wrote its own "
        "output back would be automatic consequential promotion arriving through a listing"
    )


def test_only_the_acceptance_method_writes_the_accepted_state() -> None:
    """Property 3. One write, in one method, and the three proposers cannot reach it."""
    tree = _module(REPOSITORY)

    def _writes_accepted(node: ast.AST) -> bool:
        """Whether this function passes the accepted state into a `.values(...)`.

        A `.values(...)` keyword and not any mention of the name, because
        `derive_pulse` compares against `ACCEPTED` in a `WHERE` clause — reading
        only accepted rows is the point of it — and a guard that could not tell a
        predicate from an assignment would either miss the write or forbid the
        filter.
        """
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            target = child.func
            if not (isinstance(target, ast.Attribute) and target.attr == "values"):
                continue
            for keyword in child.keywords:
                if keyword.arg != "evidence_state":
                    continue
                if "ACCEPTED" in ast.dump(keyword.value):
                    return True
        return False

    methods_writing_accepted = sorted(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and _writes_accepted(node)
    )
    assert methods_writing_accepted == ["accept"], (
        f"{methods_writing_accepted} assign the accepted state. Exactly one method may, and "
        "it is the one that first resolves a review decision"
    )
    # And the filter the guard deliberately does not read is still there, so the
    # distinction above is a distinction rather than a way of seeing nothing.
    derive = _function(tree, klass="SqlPulseRepository", name="derive_pulse")
    assert "ACCEPTED" in ast.dump(derive)

    for proposer in ("propose_commitment", "propose_decision", "propose_task"):
        method = _function(tree, klass="SqlContinuityRepository", name=proposer)
        source = ast.dump(method)
        assert "PROPOSED" in source, f"{proposer} does not write the proposed literal"
        assert "ACCEPTED" not in source
        arguments = {argument.arg for argument in method.args.kwonlyargs}
        assert "evidence_state" not in arguments, (
            f"{proposer} takes an evidence state. It must write the literal, so that no "
            "caller can propose something already accepted"
        )


def test_acceptance_reads_a_review_decision_before_it_writes() -> None:
    """Property 4. The gate is in the method, not in a caller's discipline."""
    accept = _function(_module(REPOSITORY), klass="SqlContinuityRepository", name="accept")
    names = {node.id for node in ast.walk(accept) if isinstance(node, ast.Name)}
    assert "capture_review_decisions" in names, (
        "SqlContinuityRepository.accept does not read the review plane. Promotion that "
        "does not require a review that happened is promotion by assertion"
    )


@pytest.mark.parametrize("path", [DERIVATION, REPOSITORY], ids=lambda p: p.name)
def test_the_modules_this_guard_reads_exist_and_parse(path: Path) -> None:
    """Guards every assertion above: a moved file would make them all vacuous."""
    assert path.is_file()
    assert len(_module(path).body) > 5
