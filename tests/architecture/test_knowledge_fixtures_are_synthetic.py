"""Knowledge evaluation and provider-conformance fixtures are synthetic (KLP-AC-082).

KLP-WP-04, unmarked (FAST), routed to repository-checks / validate and
dependency-floor.

AC-082: every fixture module under `tests/evaluation/knowledge*` and
`tests/provider_conformance/*knowledge*` declares `SYNTHETIC = True` at module
level, and every classification literal in it is `synthetic_test`.

Scope, read most restrictively: any file below `tests/evaluation/` or
`tests/provider_conformance/` whose relative path has a component containing
`knowledge` (case-insensitive) -- so a `knowledge*` directory, a nested
`fixtures/knowledge_*.py` and a `*knowledge*` module are all in. Python modules
must declare a module-level `SYNTHETIC = True` (a plain or annotated assignment
of the literal `True`, not a computed value) and spell no non-synthetic
classification: neither the string value of a non-`synthetic_test`
`Classification` member nor `Classification.<MEMBER>` for one. Non-Python data
files in scope (JSON, YAML, text) cannot declare the flag; they must spell no
non-synthetic classification value (DEV-90).

Vacuity, stated rather than hidden: at this head no file is in scope (WP-07/WP-08
add the evaluation corpus). The scope test therefore proves the glob against the
real roots (they exist and the scan visits them) and the plant tests prove that a
planted in-scope module without the flag, with `SYNTHETIC = False`, or with a
`private_local` literal is caught, and that a compliant one passes.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from my_pa.domain.common.classification import Classification

ROOT: Final = Path(__file__).resolve().parents[2]
SCOPE_ROOTS: Final = ("tests/evaluation", "tests/provider_conformance")
NON_SYNTHETIC: Final = frozenset(
    member for member in Classification if member is not Classification.SYNTHETIC_TEST
)


def in_scope(root: Path) -> Iterator[Path]:
    """Every file under the scope roots of `root` whose path names Knowledge."""
    for scope in SCOPE_ROOTS:
        base = root / scope
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(base).parts
            if any("knowledge" in part.lower() for part in relative):
                yield path


def _declares_synthetic(tree: ast.Module) -> bool:
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if (
            any(isinstance(target, ast.Name) and target.id == "SYNTHETIC" for target in targets)
            and isinstance(value, ast.Constant)
            and value.value is True
        ):
            return True
    return False


def violations(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    values = {member.value for member in NON_SYNTHETIC}
    if path.suffix != ".py":
        return [
            f"non-synthetic classification {value!r}" for value in sorted(values) if value in text
        ]
    found: list[str] = []
    tree = ast.parse(text)
    if not _declares_synthetic(tree):
        found.append("no module-level SYNTHETIC = True")
    names = {member.name for member in NON_SYNTHETIC}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in values:
            found.append(f"classification literal {node.value!r} at line {node.lineno}")
        if (
            isinstance(node, ast.Attribute)
            and node.attr in names
            and isinstance(node.value, ast.Name)
            and node.value.id == "Classification"
        ):
            found.append(f"Classification.{node.attr} at line {node.lineno}")
    return found


def test_every_in_scope_fixture_is_synthetic() -> None:
    offenders = {
        path.relative_to(ROOT).as_posix(): found
        for path in in_scope(ROOT)
        if (found := violations(path))
    }
    assert offenders == {}


def test_the_scope_roots_exist_and_are_scanned() -> None:
    """The scope is the real trees; today they hold no Knowledge fixture (vacuous, stated)."""
    for scope in SCOPE_ROOTS:
        assert (ROOT / scope).is_dir(), scope
        assert any((ROOT / scope).rglob("*.py")), scope
    assert {member.value for member in NON_SYNTHETIC} == {"private_local", "restricted_local"}


def test_a_planted_violation_is_caught_and_a_compliant_fixture_passes(tmp_path: Path) -> None:
    evaluation = tmp_path / "tests/evaluation"
    conformance = tmp_path / "tests/provider_conformance"
    (evaluation / "knowledge_corpus" / "nested").mkdir(parents=True)
    conformance.mkdir(parents=True)
    (evaluation / "fixtures").mkdir()
    planted = {
        evaluation / "knowledge_corpus" / "nested" / "missing_flag.py": "ROWS = []\n",
        evaluation / "knowledge_corpus" / "false_flag.py": "SYNTHETIC = False\n",
        evaluation / "fixtures" / "knowledge_rows.py": (
            "SYNTHETIC = True\nROWS = [{'classification': 'private_local'}]\n"
        ),
        conformance / "test_knowledge_provider.py": (
            "from my_pa.domain.common.classification import Classification\n"
            "SYNTHETIC: bool = True\nCLASS = Classification.RESTRICTED_LOCAL\n"
        ),
        evaluation / "knowledge_corpus" / "rows.json": '[{"classification": "restricted_local"}]',
    }
    compliant = {
        evaluation / "knowledge_corpus" / "ok.py": (
            "SYNTHETIC = True\nROWS = [{'classification': 'synthetic_test'}]\n"
        ),
        conformance / "test_knowledge_ok.py": "SYNTHETIC: bool = True\n",
        evaluation / "knowledge_corpus" / "ok.json": '[{"classification": "synthetic_test"}]',
    }
    outside = evaluation / "harness.py"
    for path, text in {**planted, **compliant, outside: "CLASS = 'private_local'\n"}.items():
        path.write_text(text, encoding="utf-8")
    scanned = set(in_scope(tmp_path))
    assert scanned == set(planted) | set(compliant)
    for path in planted:
        assert violations(path), path.name
    for path in compliant:
        assert violations(path) == [], path.name
