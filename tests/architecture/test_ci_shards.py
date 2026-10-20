"""The CI shards run exactly the unsharded selections, and their gates fail closed.

Operator authority 2026-10-20, "Shard FAST + migration-edge": `validate`,
`dependency-floor` and `migration-edge` run as matrix shards (`tests/ci_shard.py`)
with **no coverage reduction**. This module is what makes "no coverage
reduction" a checked claim rather than a description:

- the selector partitions every input it is given (pure function, any count);
- the plugin partitions a real `pytest --collect-only` collection, checked by
  comparing node-ID sets (unsharded == union of shards, pairwise disjoint) on a
  bounded subtree so it stays cheap in FAST. The same comparison over the *full*
  FAST and migration selections runs in CI, in `validate-static`
  (`python -m tests.ci_shard verify`), and this module pins that step to the
  matrices;
- each sharded job's matrix is exactly `1..N`, its `CI_SHARD` is `/N`, its `-m`
  expression is the original unsharded one, and the verify step proves that
  same `(lane, N, expression)`;
- every aggregator with a stable required-check name (`validate`,
  `dependency-floor`, `migration-edge`, `database-tier`) runs `always()`, reads
  the result of every job it needs, and exits non-zero unless every one is
  exactly `success` -- executed here against `failure`, `cancelled`, `skipped`
  and empty results;
- the steps that ran once in the single `validate` job still run once.

Unmarked: FAST, routed to `repository-checks / validate` and `dependency-floor`.
Synthetic inputs only; the subprocesses are this interpreter running pytest's
collection or `/bin/bash` over checked-in aggregator scripts.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Final

import pytest
from tests.architecture.test_ci_invokes_mypy_over_the_declared_tree import (
    _command_lines,
    _parse_workflow,
)
from tests.ci_shard import _hashed_shard, lane_weights, parse_shard, shard_of, verify

ROOT: Final = Path(__file__).resolve().parents[2]
WORKFLOW: Final = ROOT / ".github" / "workflows" / "repository-checks.yml"

FAST: Final = (
    "not slow and not database and not network and not connector and not evaluation "
    "and not e2e and not recovery"
)
MIGRATION: Final = "migration_edge or migration"

#: Sharded job -> (lane, the unsharded `-m` expression it must keep).
SHARDED: Final = {
    "validate-fast": ("fast", FAST),
    "dependency-floor-fast": ("fast", FAST),
    "migration-edge-shard": ("migration", MIGRATION),
}

#: Stable required-check aggregator -> exactly the jobs it must gate.
AGGREGATORS: Final = {
    "validate": frozenset({"validate-static", "validate-fast"}),
    "dependency-floor": frozenset({"dependency-floor-fast"}),
    "migration-edge": frozenset({"migration-edge-shard"}),
    "database-tier": frozenset(
        {
            "database-current-head",
            "database-recovery",
            "migration-empty-to-head",
            "migration-edge",
            "database-e2e",
        }
    ),
}

_VERIFY: Final = re.compile(
    r'^python -m tests\.ci_shard verify --lane (\S+) --shards (\d+) -m "([^"]+)"$'
)
_SHARD_RUN: Final = re.compile(
    r'python -m pytest -m "([^"]+)" --ci-shard "\$CI_SHARD" --ci-shard-lane (\S+)'
)


def _jobs() -> dict[str, dict[str, object]]:
    jobs = _parse_workflow(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _steps(job: str) -> list[dict[str, object]]:
    steps = _jobs()[job]["steps"]
    assert isinstance(steps, list)
    return steps


def _matrix_shards(job: str) -> list[int] | None:
    strategy = _jobs()[job].get("strategy")
    if not isinstance(strategy, dict):
        return None
    matrix = strategy.get("matrix")
    assert isinstance(matrix, dict), f"{job}: a strategy without a matrix"
    raw = matrix.get("shard")
    assert isinstance(raw, str), f"{job}: matrix.shard must be a flow list"
    assert set(matrix) == {"shard"}, f"{job}: matrix must vary only the shard"
    assert strategy.get("fail-fast") == "false", f"{job}: one failed shard must not hide others"
    assert raw.startswith("[") and raw.endswith("]"), raw
    return [int(value) for value in raw[1:-1].split(",")]


def _verify_triples() -> set[tuple[str, int, str]]:
    triples: set[tuple[str, int, str]] = set()
    for step in _steps("validate-static"):
        script = step.get("run")
        if isinstance(script, str) and "tests.ci_shard verify" in script:
            for command in _command_lines(script):
                match = _VERIFY.match(command)
                assert match, f"unrecognised verify command: {command!r}"
                triples.add((match.group(1), int(match.group(2)), match.group(3)))
    return triples


# --- The selector itself ------------------------------------------------------------


@pytest.mark.parametrize("spec", ["0/3", "4/3", "3", "1/0", "a/b", "01/3", "1/03", "-1/3", ""])
def test_a_malformed_shard_is_refused(spec: str) -> None:
    with pytest.raises(pytest.UsageError):
        parse_shard(spec)


def test_the_selector_places_every_file_in_exactly_one_shard_for_every_count() -> None:
    weighted = {path for table in lane_weights().values() for path in table}
    unweighted = {f"tests/unit/test_synthetic_new_{index}.py" for index in range(50)}
    for lane in lane_weights():
        for count in range(1, 9):
            for path in sorted(weighted | unweighted):
                assert 0 <= shard_of(path, lane, count) < count, (lane, count, path)
            assert {_hashed_shard(path, count) for path in unweighted} == set(range(count))


def test_the_weight_tables_cover_both_lanes_and_balance_the_committed_counts() -> None:
    """A table is regenerable; an empty one would silently fall back to hashing."""
    assert set(lane_weights()) == {lane for lane, _ in SHARDED.values()}
    for job, (lane, _expression) in SHARDED.items():
        shards = _matrix_shards(job)
        assert shards
        table = lane_weights()[lane]
        assert table, f"lane {lane} has no committed weights"
        loads = [0.0] * len(shards)
        for path, seconds in table.items():
            loads[shard_of(path, lane, len(shards))] += seconds
        assert max(loads) <= 1.25 * (sum(loads) / len(loads)), (job, loads)


def test_the_plugin_partitions_a_real_collection() -> None:
    """Unsharded == union of shards and pairwise disjoint, by real node IDs."""
    # Bounded subtrees, so this stays a few seconds in FAST. Weighted files and
    # hashed ones are both present; the full selections are proved in CI.
    fast_paths = ["tests/policy", "tests/migration", "tests/architecture/test_ci_shards.py"]
    assert verify("fast", 3, FAST, fast_paths, require_every_shard=False) == []
    migration_paths = [
        "tests/migration",
        "tests/schema/test_audit_schema_migration.py",
        "tests/schema/test_task_schema_migration.py",
        "tests/schema/test_continuity_migration.py",
        "tests/schema/test_review_schema_migration.py",
    ]
    assert verify("migration", 4, MIGRATION, migration_paths, require_every_shard=False) == []


# --- The workflow ---------------------------------------------------------------------


def test_each_sharded_job_runs_its_unsharded_selection_over_a_matrix_of_its_count() -> None:
    sharded = {job for job in _jobs() if _matrix_shards(job) is not None}
    assert sharded == set(SHARDED)
    expected_triples: set[tuple[str, int, str]] = set()
    for job, (lane, expression) in SHARDED.items():
        shards = _matrix_shards(job)
        assert shards is not None
        count = len(shards)
        assert shards == list(range(1, count + 1)), f"{job}: matrix {shards}"
        runs = [step for step in _steps(job) if "--ci-shard" in str(step.get("run", ""))]
        assert len(runs) == 1, f"{job}: exactly one sharded pytest step"
        environment = runs[0].get("env")
        assert isinstance(environment, dict)
        assert environment.get("CI_SHARD") == f"${{{{ matrix.shard }}}}/{count}", job
        flat = " ".join(str(runs[0]["run"]).split())
        found = _SHARD_RUN.findall(flat)
        assert found == [(expression, lane)], f"{job}: {found}"
        expected_triples.add((lane, count, expression))
    assert _verify_triples() == expected_triples
    for job in set(_jobs()) - set(SHARDED):
        for step in _steps(job):
            assert "--ci-shard " not in str(step.get("run", "")), f"{job} shards without a matrix"


def test_the_partition_proof_step_runs_whenever_fast_is_applicable() -> None:
    proofs = [
        step
        for step in _steps("validate-static")
        if "tests.ci_shard verify" in str(step.get("run", ""))
    ]
    assert len(proofs) == 1
    assert proofs[0].get("if") == "steps.fast.outputs.applicable == 'true'"


def test_the_steps_of_the_single_validate_job_still_run_exactly_once() -> None:
    once = {
        "Validate repository documents and configuration",
        "Check Python FAST applicability",
        "Install Python FAST dependencies",
        "Smoke-test Python FAST imports",
        "Lint and format-check Python FAST tier",
        "Type-check Python FAST tier",
        "Package governance candidate",
    }
    static = [step.get("name") for step in _steps("validate-static")]
    assert once <= set(static)
    fast = {str(step.get("name")) for step in _steps("validate-fast")}
    assert fast == {
        "Checkout",
        "Record checkout identity",
        "Set up Python",
        "Check Python FAST applicability",
        "Install Python FAST dependencies",
        "Test Python FAST tier",
    }
    assert "Test Python FAST tier" not in static
    for job in ("validate-static", "validate-fast"):
        test_step = [s for s in _steps(job) if s.get("name") == "Test Python FAST tier"]
        install = [s for s in _steps(job) if s.get("name") == "Install Python FAST dependencies"]
        assert install and install[0].get("if") == "steps.fast.outputs.applicable == 'true'"
        if test_step:
            assert test_step[0].get("if") == "steps.fast.outputs.applicable == 'true'"
    for name in ("Smoke-test contracts at the declared floor", "Type-check at the declared floor"):
        (step,) = [s for s in _steps("dependency-floor-fast") if s.get("name") == name]
        assert step.get("if") == "steps.floor.outputs.applicable == 'true' && matrix.shard == 1"


# --- The aggregators ------------------------------------------------------------------


def _aggregator(job: str) -> tuple[dict[str, str], str]:
    definition = _jobs()[job]
    assert definition.get("if") == "always()", f"{job} must run when a need failed or was skipped"
    needs = definition.get("needs")
    assert isinstance(needs, list)
    assert frozenset(needs) == AGGREGATORS[job], f"{job} needs {needs}"
    (step,) = _steps(job)
    environment = step.get("env")
    assert isinstance(environment, dict)
    read = {
        str(value).removeprefix("${{ needs.").removesuffix(".result }}"): str(name)
        for name, value in environment.items()
    }
    assert set(read) == AGGREGATORS[job], f"{job} reads {sorted(read)}"
    script = step.get("run")
    assert isinstance(script, str)
    return read, script


def _reconcile(script: str, results: dict[str, str]) -> int:
    completed = subprocess.run(  # noqa: S603 - checked-in aggregator script, synthetic env
        ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
        env={"PATH": os.defpath, **results},
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode


@pytest.mark.parametrize("job", sorted(AGGREGATORS))
def test_each_aggregator_passes_only_when_every_need_succeeded(job: str) -> None:
    read, script = _aggregator(job)
    success = dict.fromkeys(read.values(), "success")
    assert _reconcile(script, success) == 0
    for variable in read.values():
        for bad in ("failure", "cancelled", "skipped", ""):
            assert _reconcile(script, {**success, variable: bad}) != 0, (job, variable, bad)


def test_database_tier_still_gates_on_the_migration_edge_aggregator() -> None:
    assert "migration-edge" in AGGREGATORS["database-tier"]
    assert _jobs()["migration-edge"].get("if") == "always()"
