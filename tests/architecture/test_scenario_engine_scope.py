"""Schedule Scenarios S6-1: the pure domain and engine stay pure (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` section 9.1. Over
every S6-1 module (the `scenario` package plus `series_match.py`,
`currency.py` and `baselines.py`), by AST:

* imports are the standard library, `my_pa.domain.schedule` and
  `my_pa.domain.common.identifiers` only (the S5a allowlist, inherited);
* no import of `random`, `time`, `secrets`, `uuid` or `os` (no randomness,
  clock or environment);
* no `now`/`today`/`utcnow` call;
* no `float(` call, `float` literal or `/` operator (`ast.Div`): the engine is
  integer minutes only (S6-D06).

And the contract's S6-1 crosswalk is real: every test the section 9.1, 11.5
and 12.7 prove-red tables assign to S6-1 exists as a top-level test function
in the module this slice owns.

What it cannot prove: that no `set`/`dict` iteration order reaches an output
(the permutation property tests check that behaviourally).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEDULE: Final = ROOT / "src" / "my_pa" / "domain" / "schedule"
CONTRACT: Final = ROOT / "docs" / "architecture" / "schedule-scenarios-contract.md"

S61_MODULES: Final = (
    *sorted((SCHEDULE / "scenario").glob("*.py")),
    SCHEDULE / "series_match.py",
    SCHEDULE / "currency.py",
    SCHEDULE / "baselines.py",
)
ALLOWED_PREFIXES: Final = ("my_pa.domain.schedule", "my_pa.domain.common.identifiers")
FORBIDDEN_ROOTS: Final = frozenset({"random", "time", "secrets", "uuid", "os"})
FORBIDDEN_CALLS: Final = frozenset({"now", "today", "utcnow"})


def _imports(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.append((node.lineno, "." * node.level + (node.module or "")))
            elif node.module:
                found.append((node.lineno, node.module))
    return found


def _violations(path: Path) -> list[str]:
    return _source_violations(path.read_text(encoding="utf-8"), str(path.relative_to(ROOT)))


def _source_violations(source: str, where: str) -> list[str]:
    tree = ast.parse(source, filename=where)
    wrong: list[str] = []
    for line, name in _imports(tree):
        root = name.split(".")[0]
        if name.startswith("."):
            wrong.append(f"{where}:{line} relative import {name}")
        elif root in FORBIDDEN_ROOTS or (
            root not in sys.stdlib_module_names
            and root != "__future__"
            and not any(
                name == prefix or name.startswith(f"{prefix}.") for prefix in ALLOWED_PREFIXES
            )
        ):
            wrong.append(f"{where}:{line} imports {name}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function = node.func
            called = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else None
            )
            if called in FORBIDDEN_CALLS:
                wrong.append(f"{where}:{node.lineno} calls {called}()")
            if called == "float":
                wrong.append(f"{where}:{node.lineno} calls float()")
        elif isinstance(node, ast.Constant) and type(node.value) is float:
            wrong.append(f"{where}:{node.lineno} float literal {node.value!r}")
        elif isinstance(node, ast.BinOp | ast.AugAssign) and isinstance(node.op, ast.Div):
            wrong.append(f"{where}:{node.lineno} uses the / operator")
        elif isinstance(node, ast.Name) and node.id == "float":
            wrong.append(f"{where}:{node.lineno} names float")
    return wrong


def test_the_s61_module_set_is_the_contract_set() -> None:
    names = sorted(path.relative_to(SCHEDULE).as_posix() for path in S61_MODULES)
    assert names == [
        "baselines.py",
        "currency.py",
        "scenario/__init__.py",
        "scenario/calendar.py",
        "scenario/canonical.py",
        "scenario/changeset.py",
        "scenario/cpm.py",
        "scenario/model.py",
        "scenario/outputs.py",
        "scenario/snapshot.py",
        "series_match.py",
    ]


def test_scenario_package_has_no_float_clock_or_randomness() -> None:
    wrong = [problem for path in S61_MODULES for problem in _violations(path)]
    assert not wrong, wrong


def test_the_guard_sees_each_forbidden_form() -> None:
    samples = {
        "import random\n": "imports random",
        "from time import monotonic\n": "imports time",
        "import uuid\n": "imports uuid",
        "import secrets\n": "imports secrets",
        "from os import environ\n": "imports os",
        "import sqlalchemy\n": "imports sqlalchemy",
        "from my_pa.application import commands\n": "imports my_pa.application",
        "x = clock.now()\n": "calls now()",
        "x = date.today()\n": "calls today()",
        "x = datetime.utcnow()\n": "calls utcnow()",
        "x = float('1')\n": "calls float()",
        "x = 0.5\n": "float literal",
        "x = 3 / 2\n": "uses the / operator",
        "x = 3\nx /= 2\n": "uses the / operator",
        "from . import model\n": "relative import",
    }
    for source, expected in samples.items():
        found = _source_violations(source, "probe.py")
        assert any(expected in problem for problem in found), (source, found)
    assert _source_violations("from decimal import Decimal\nx = 7 // 2\n", "ok.py") == []


#: Contract sections 9.1, 11.5 and 12.7: the S6-1 prove-red tests by module.
CROSSWALK: Final[dict[str, tuple[str, ...]]] = {
    "tests/unit/test_scenario_cpm_goldens.py": (
        "test_golden_network_matches",
        "test_topological_order_is_key_ordered",
        "test_critical_path_enumeration_is_bounded",
        "test_operation_budget_is_exact",
    ),
    "tests/architecture/test_scenario_engine_scope.py": (
        "test_scenario_package_has_no_float_clock_or_randomness",
    ),
    "tests/unit/test_scenario_model.py": ("test_content_sha256_vector",),
    "tests/unit/test_scenario_changeset.py": (
        "test_change_set_applies_in_request_order",
        "test_added_activity_cannot_take_a_source_key",
        "test_final_revalidation_refuses_with_content_invalid",
    ),
    "tests/unit/test_scenario_snapshot.py": ("test_golden_snapshot",),
    "tests/unit/test_scenario_outputs.py": (
        "test_output_distribution_digest_must_match",
        "test_output_histogram_counts_sum_to_iterations",
    ),
    "tests/unit/test_schedule_series_match.py": ("test_series_match_vectors",),
    "tests/unit/test_schedule_currency.py": ("test_current_standard_update_vectors",),
    "tests/unit/test_schedule_baselines.py": ("test_baseline_vectors",),
}


def _test_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }


def test_the_contract_crosswalk_names_s61_tests_that_exist() -> None:
    contract = CONTRACT.read_text(encoding="utf-8")
    missing: list[str] = []
    for module, names in CROSSWALK.items():
        defined = _test_functions(ROOT / module)
        for name in names:
            if name not in defined:
                missing.append(f"{module}::{name} is not defined")
            if f"`{name}" not in contract:
                missing.append(f"{name} is no longer named by the contract")
    assert not missing, missing
