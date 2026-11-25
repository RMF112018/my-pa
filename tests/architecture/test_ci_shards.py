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
  the result of every job it needs, and -- on every run that is not a
  docs-only PR -- exits non-zero unless every one is exactly `success`,
  executed here against `failure`, `cancelled`, `skipped` and empty results
  (the docs-only exception is pinned in the classification section below);
- the partition proof runs on every push and workflow_dispatch, and on a PR
  unless `classify` succeeded and said `shard_proof=false` -- that condition
  is pinned here, so the gate cannot silently drop or widen;
- the steps that ran once in the single `validate` job still run once;
- the `classify` job and `tests/ci_classify.py`: docs-only PRs skip exactly the
  stated jobs, the aggregators pass them only then, a failed `classify` fails
  every aggregator, and `validate-docs` runs every module that reads
  documentation (the last section of this module).

Unmarked: FAST, routed to `repository-checks / validate` and `dependency-floor`.
Synthetic inputs only; the subprocesses are this interpreter running pytest's
collection or the checked-in classifier, or `/bin/bash` over checked-in
aggregator scripts.
"""

from __future__ import annotations

import ast
import itertools
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest
from tests.architecture.test_ci_invokes_mypy_over_the_declared_tree import (
    _command_lines,
    _parse_workflow,
)
from tests.ci_classify import PLUGIN_TEST_MODULES, classify, is_docs_path, is_normal
from tests.ci_shard import _hashed_shard, lane_weights, parse_shard, shard_of, verify

ROOT: Final = Path(__file__).resolve().parents[2]
WORKFLOW: Final = ROOT / ".github" / "workflows" / "repository-checks.yml"
CLASSIFIER: Final = ROOT / "tests" / "ci_classify.py"

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
    "validate": frozenset({"validate-static", "validate-fast", "validate-docs"}),
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

#: The proof's step condition. `tests/ci_classify.py` explains why a PR may
#: skip it; push and workflow_dispatch never do, nor does a failed classify.
PROOF_CONDITION: Final = (
    "steps.fast.outputs.applicable == 'true' && (github.event_name != 'pull_request' || "
    "needs.classify.result != 'success' || needs.classify.outputs.shard_proof != 'false')"
)
#: The classification every aggregator reads besides its needs' results.
_CLASSIFICATION: Final = {
    "CLASSIFY": "${{ needs.classify.result }}",
    "DOCS_ONLY": "${{ needs.classify.outputs.docs_only }}",
    "EVENT_NAME": "${{ github.event_name }}",
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


def test_the_partition_proof_step_runs_unless_classify_cleared_it_on_a_pr() -> None:
    proofs = [
        step
        for step in _steps("validate-static")
        if "tests.ci_shard verify" in str(step.get("run", ""))
    ]
    assert len(proofs) == 1
    assert proofs[0].get("if") == PROOF_CONDITION
    # `validate-static` itself must run whatever `classify` did.
    assert _jobs()["validate-static"].get("if") == "${{ !cancelled() }}"


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
    assert frozenset(needs) == AGGREGATORS[job] | {"classify"}, f"{job} needs {needs}"
    (step,) = _steps(job)
    environment = step.get("env")
    assert isinstance(environment, dict)
    for name, value in _CLASSIFICATION.items():
        assert environment.get(name) == value, (job, name)
    read = {
        str(value).removeprefix("${{ needs.").removesuffix(".result }}"): str(name)
        for name, value in environment.items()
        if name not in _CLASSIFICATION
    }
    assert set(read) == AGGREGATORS[job], f"{job} reads {sorted(read)}"
    script = step.get("run")
    assert isinstance(script, str)
    return read, script


def _reconcile(script: str, results: dict[str, str]) -> int:
    """Run an aggregator on a run that is not a docs-only PR."""
    completed = subprocess.run(  # noqa: S603 - checked-in aggregator script, synthetic env
        ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
        env={"PATH": os.defpath, **results},
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode


@pytest.mark.parametrize("event", ["pull_request", "push", "workflow_dispatch"])
@pytest.mark.parametrize("job", sorted(AGGREGATORS))
def test_each_aggregator_passes_only_when_every_need_succeeded(job: str, event: str) -> None:
    """Outside a docs-only PR: today's rule, every needed result exactly `success`.

    The one exception is `validate-docs`, which runs only on a docs-only PR and
    so must be exactly `skipped` everywhere else.
    """
    read, script = _aggregator(job)
    full = {"CLASSIFY": "success", "DOCS_ONLY": "false", "EVENT_NAME": event}
    success = {
        variable: ("skipped" if need == "validate-docs" else "success")
        for need, variable in read.items()
    }
    assert _reconcile(script, {**full, **success}) == 0
    # On push and workflow_dispatch even `docs_only=true` cannot relax the rule.
    if event != "pull_request":
        assert _reconcile(script, {**full, "DOCS_ONLY": "true", **success}) == 0
    for variable in read.values():
        for bad in ("failure", "cancelled", "skipped", "success", ""):
            if bad == success[variable]:
                continue
            for docs_only in ("false", "true") if event != "pull_request" else ("false",):
                environment = {**full, "DOCS_ONLY": docs_only, **success, variable: bad}
                assert _reconcile(script, environment) != 0, (job, variable, bad, docs_only)
    for bad in ("failure", "cancelled", "skipped", ""):
        assert _reconcile(script, {**full, **success, "CLASSIFY": bad}) != 0, (job, bad)


def test_database_tier_still_gates_on_the_migration_edge_aggregator() -> None:
    assert "migration-edge" in AGGREGATORS["database-tier"]
    assert _jobs()["migration-edge"].get("if") == "always()"


# --- The classification (`classify`, `tests/ci_classify.py`) ---------------------------
#
# Docs-only PRs and the gated partition proof, proved without `act`: every
# classifier rule by a named case (each shown to go red when its rule is broken),
# the classifier as the workflow runs it, every `if:` that reads the
# classification, every aggregator over every combination of `classify` result,
# `docs_only`, event and need results, and the `validate-docs` module list.

DOCS_SKIP: Final = (
    "${{ !cancelled() && !(github.event_name == 'pull_request' && "
    "needs.classify.result == 'success' && needs.classify.outputs.docs_only == 'true') }}"
)
DOCS_RUN: Final = (
    "github.event_name == 'pull_request' && needs.classify.result == 'success' && "
    "needs.classify.outputs.docs_only == 'true'"
)
#: Jobs a docs-only PR skips.
SKIPPABLE: Final = frozenset(
    {
        "validate-fast",
        "web-security",
        "dependency-floor-fast",
        "database-current-head",
        "database-recovery",
        "migration-empty-to-head",
        "migration-edge-shard",
        "database-e2e",
    }
)

#: Advisory jobs (operator decision O4, 2026-11-22): skipped on a docs-only PR
#: like `SKIPPABLE`, but needed by no job, so no aggregator -- and therefore no
#: required check -- can read their result.
ADVISORY: Final = frozenset({"validate-fast-xdist"})

#: Aggregator -> {need: role}. `always`: exactly `success`. `full`: `success`,
#: or `skipped` on a docs-only PR. `docs`: `success` on a docs-only PR,
#: `skipped` otherwise. Every aggregator also needs `classify` == `success`.
ROLES: Final = {
    "validate": {"validate-static": "always", "validate-fast": "full", "validate-docs": "docs"},
    "dependency-floor": {"dependency-floor-fast": "full"},
    "migration-edge": {"migration-edge-shard": "full"},
    "database-tier": {
        "database-current-head": "full",
        "database-recovery": "full",
        "migration-empty-to-head": "full",
        "migration-edge": "always",
        "database-e2e": "full",
    },
}


# --- The classifier ------------------------------------------------------------------

#: id -> (event, name-status lines or None for "not resolved", docs_only, shard_proof)
CASES: Final[dict[str, tuple[str, list[str] | None, bool, bool]]] = {
    "docs-only": ("pull_request", ["M\tdocs/plans/a.md", "A\tdocs/x/y.json"], True, False),
    "docs-plus-src": ("pull_request", ["M\tdocs/a.md", "M\tsrc/my_pa/x.py"], False, False),
    "src-only": ("pull_request", ["M\tsrc/my_pa/x.py"], False, False),
    "this-workflow": ("pull_request", ["M\t.github/workflows/repository-checks.yml"], False, True),
    "other-workflow": ("pull_request", ["M\t.github/workflows/frontend-quality.yml"], False, False),
    "empty-diff": ("pull_request", [], False, True),
    "unresolved-diff": ("pull_request", None, False, True),
    "rename-into-docs": ("pull_request", ["D\tnotes/a.md", "A\tdocs/a.md"], False, False),
    "rename-out-of-docs": ("pull_request", ["D\tdocs/a.md", "A\tsrc/a.md"], False, False),
    "rename-line-within-docs": ("pull_request", ["R100\tdocs/a.md\tdocs/b.md"], True, False),
    "rename-line-out-of-docs": ("pull_request", ["R087\tdocs/a.md\tsrc/a.md"], False, False),
    "dotdot-escape": ("pull_request", ["M\tdocs/../src/x.py"], False, True),
    "dot-segment": ("pull_request", ["M\tdocs/./a.md"], False, True),
    "empty-segment": ("pull_request", ["M\tdocs//a.md"], False, True),
    "absolute-path": ("pull_request", ["M\t/docs/a.md"], False, True),
    "backslash": ("pull_request", ["M\tdocs\\a.md"], False, True),
    "git-quoted": ("pull_request", ['M\t"docs/\\303\\251.md"'], False, True),
    "unknown-status": ("pull_request", ["X\tdocs/a.md"], False, True),
    "malformed-line": ("pull_request", ["docs/a.md"], False, True),
    "space-not-tab": ("pull_request", ["M docs/a.md"], False, True),
    "control-character": ("pull_request", ["M\tdocs/a\x7f.md"], False, True),
    "top-level-readme": ("pull_request", ["M\tREADME.md"], True, False),
    "nested-readme": ("pull_request", ["M\tsrc/README.md"], False, False),
    "runbook-md": ("pull_request", ["M\tops/runbooks/x.md"], True, False),
    "runbook-sh": ("pull_request", ["M\tops/runbooks/x.sh"], False, False),
    "push": ("push", ["M\tdocs/a.md"], False, True),
    "workflow-dispatch": ("workflow_dispatch", ["M\tdocs/a.md"], False, True),
    "test-module-added": ("pull_request", ["A\ttests/unit/test_new.py"], False, True),
    "test-module-deleted": ("pull_request", ["D\ttests/unit/test_old.py"], False, True),
    "test-module-renamed": (
        "pull_request",
        ["D\ttests/unit/test_old.py", "A\ttests/unit/test_new.py"],
        False,
        True,
    ),
    "test-module-modified": ("pull_request", ["M\ttests/unit/test_x.py"], False, False),
    "shard-weights": ("pull_request", ["M\ttests/ci_shard_weights.json"], False, True),
    "shard-selector": ("pull_request", ["M\ttests/ci_shard.py"], False, True),
    "shard-pin": ("pull_request", ["M\ttests/architecture/test_ci_shards.py"], False, True),
    "pyproject": ("pull_request", ["M\tpyproject.toml"], False, True),
    "nested-conftest": ("pull_request", ["M\ttests/pipeline/conftest.py"], False, True),
    "root-conftest": ("pull_request", ["A\tconftest.py"], False, True),
    "auto-marking": ("pull_request", ["M\ttests/db/fixtures.py"], False, True),
    "test-helper-modified": ("pull_request", ["M\ttests/wire.py"], False, True),
    "plugin-test-module": (
        "pull_request",
        ["M\ttests/security/test_cross_principal_review_isolation.py"],
        False,
        True,
    ),
    "test-data-added": ("pull_request", ["A\ttests/fixtures/x.json"], False, False),
    "docs-plus-test-added": (
        "pull_request",
        ["M\tdocs/a.md", "A\ttests/unit/test_new.py"],
        False,
        True,
    ),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_each_classifier_case(case: str) -> None:
    event, lines, docs_only, shard_proof = CASES[case]
    assert classify(event, lines) == {"docs_only": docs_only, "shard_proof": shard_proof}


@pytest.mark.parametrize(
    "path",
    ["docs/../src/x.py", "/etc/x", "docs\\a", "docs/./a", "./docs/a", "a//b", "a/", "", '"q"'],
)
def test_a_non_normal_path_is_never_normal(path: str) -> None:
    assert not is_normal(path)
    assert not is_docs_path(path)


def test_the_classifier_runs_as_the_workflow_runs_it() -> None:
    """`python3 -I`, standard library only, stdin in, exactly two lines out."""
    for stdin, expected in (
        ("M\tdocs/a.md\n", "docs_only=true\nshard_proof=false\n"),
        ("M\tsrc/a.py\nA\ttests/unit/test_a.py\n", "docs_only=false\nshard_proof=true\n"),
        ("", "docs_only=false\nshard_proof=true\n"),
    ):
        completed = subprocess.run(  # noqa: S603 - this interpreter, the checked-in script
            [sys.executable, "-I", str(CLASSIFIER), "--event", "pull_request"],
            input=stdin,
            capture_output=True,
            text=True,
            check=True,
        )
        assert completed.stdout == expected
    tree = ast.parse(CLASSIFIER.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        str(node.module).split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported


def test_every_test_module_loaded_as_a_plugin_triggers_the_proof() -> None:
    """A `pytest_plugins` entry naming a `test_*` module makes its hooks act on collection."""
    loaded: set[str] = set()
    for path in sorted((ROOT / "tests").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "pytest_plugins" not in text:
            continue
        for node in ast.parse(text).body:
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "pytest_plugins" for t in node.targets)
                and isinstance(node.value, (ast.Tuple, ast.List))
            ):
                for element in node.value.elts:
                    assert isinstance(element, ast.Constant) and isinstance(element.value, str)
                    loaded.add(element.value.replace(".", "/") + ".py")
    tested = {path for path in loaded if path.rsplit("/", 1)[-1].startswith("test_")}
    assert tested == set(PLUGIN_TEST_MODULES)


# --- The workflow ----------------------------------------------------------------------


def _needs(job: str) -> frozenset[str]:
    needs = _jobs()[job].get("needs")
    assert isinstance(needs, list), f"{job}: needs must be a block list"
    return frozenset(str(need) for need in needs)


def test_classify_uses_the_events_immutable_shas_and_fails_closed() -> None:
    job = _jobs()["classify"]
    assert "needs" not in job and "if" not in job
    assert job.get("outputs") == {
        "docs_only": "${{ steps.classify.outputs.docs_only }}",
        "shard_proof": "${{ steps.classify.outputs.shard_proof }}",
    }
    (checkout,) = [s for s in _steps("classify") if s.get("name") == "Checkout"]
    assert checkout.get("with") == {
        "persist-credentials": "false",
        "ref": "${{ github.event.pull_request.head.sha || github.sha }}",
        "fetch-depth": "0",
    }
    (step,) = [s for s in _steps("classify") if s.get("id") == "classify"]
    assert step.get("env") == {
        "EVENT_NAME": "${{ github.event_name }}",
        "PR_BASE_SHA": "${{ github.event.pull_request.base.sha }}",
        "PR_HEAD_SHA": "${{ github.event.pull_request.head.sha }}",
    }
    script = str(step.get("run"))
    flat = " ".join(script.split())
    assert 'git diff --name-status --no-renames "${base}" "${PR_HEAD_SHA}"' in flat
    assert 'git merge-base "${PR_BASE_SHA}" "${PR_HEAD_SHA}"' in flat
    # The merge-base's classifier, never the PR's own.
    assert 'git show "${base}:tests/ci_classify.py" > "${RUNNER_TEMP}/ci_classify.py"' in flat
    assert 'python3 -I "${RUNNER_TEMP}/ci_classify.py" --event "${EVENT_NAME}"' in flat
    assert "python3 tests/ci_classify.py" not in flat and "python3 -I tests/" not in flat
    # Not resolved: the full run, written by the workflow itself.
    assert "printf 'docs_only=false\\nshard_proof=true\\n'" in flat


def test_every_skippable_job_carries_exactly_the_docs_only_condition() -> None:
    conditioned = {job for job, body in _jobs().items() if body.get("if") == DOCS_SKIP}
    assert conditioned == SKIPPABLE | ADVISORY
    for job in SKIPPABLE | ADVISORY:
        assert _needs(job) == {"classify"}, job


def test_every_job_is_accounted_for() -> None:
    """A new job must be placed: skippable, always-run, or an aggregator."""
    assert set(_jobs()) == (
        SKIPPABLE | ADVISORY | set(ROLES) | {"classify", "validate-static", "validate-docs"}
    )
    assert _jobs()["validate-static"].get("if") == "${{ !cancelled() }}"
    assert _needs("validate-static") == {"classify"}
    assert _jobs()["validate-docs"].get("if") == DOCS_RUN
    assert _needs("validate-docs") == {"classify"}


def test_no_job_needs_an_advisory_job() -> None:
    """An advisory lane cannot pass or fail an aggregator, or anything else."""
    for job in _jobs():
        needs = _jobs()[job].get("needs")
        named = frozenset(str(need) for need in needs) if isinstance(needs, list) else frozenset()
        assert not named & ADVISORY, f"{job} needs advisory {sorted(named & ADVISORY)}"
    for job in ADVISORY:
        assert "continue-on-error" not in _jobs()[job], f"{job}: a failure must stay visible"


def test_the_xdist_lane_runs_the_whole_fast_selection_by_file() -> None:
    """`-n auto --dist loadfile` over FAST's exact expression, unsharded, in one step."""
    job = "validate-fast-xdist"
    assert _matrix_shards(job) is None
    runs = [step for step in _steps(job) if "python -m pytest" in str(step.get("run", ""))]
    assert len(runs) == 1, f"{job}: exactly one pytest step"
    (run,) = runs
    assert run.get("if") == "steps.fast.outputs.applicable == 'true'"
    flat = " ".join(str(run["run"]).split())
    assert flat == f'python -m pytest -m "{FAST}" -n auto --dist loadfile --durations=50', flat
    install = [s for s in _steps(job) if s.get("name") == "Install Python FAST dependencies"]
    assert len(install) == 1
    assert 'python -m pip install -e ".[dev]"' in str(install[0].get("run"))
    # The required lanes stay serial.
    for other in set(_jobs()) - ADVISORY:
        for step in _steps(other):
            script = " ".join(str(step.get("run", "")).split())
            assert "-n auto" not in script and "--dist" not in script, f"{other} runs xdist"


def _classified_aggregator(job: str) -> tuple[dict[str, str], str]:
    definition = _jobs()[job]
    assert definition.get("if") == "always()"
    assert _needs(job) == {"classify", *ROLES[job]}
    (step,) = _steps(job)
    environment = step.get("env")
    assert isinstance(environment, dict)
    assert environment.get("CLASSIFY") == "${{ needs.classify.result }}"
    assert environment.get("DOCS_ONLY") == "${{ needs.classify.outputs.docs_only }}"
    assert environment.get("EVENT_NAME") == "${{ github.event_name }}"
    read = {
        str(value).removeprefix("${{ needs.").removesuffix(".result }}"): str(name)
        for name, value in environment.items()
        if name not in {"CLASSIFY", "DOCS_ONLY", "EVENT_NAME"}
    }
    assert set(read) == set(ROLES[job]), (job, sorted(read))
    script = step.get("run")
    assert isinstance(script, str)
    return read, script


def _reconcile_one(script: str, environment: dict[str, str]) -> int:
    return _reconcile_many(script, [environment])[0]


def _reconcile_many(script: str, environments: list[dict[str, str]]) -> list[int]:
    """Exit status of `script` under each environment, one subshell apiece.

    One `/bin/bash` runs them all, each in its own `( ... )` with every variable
    set explicitly, so a combination sweep costs a fork per case, not an exec.
    """
    program = []
    for environment in environments:
        exports = " ".join(f"{name}={_quote(value)}" for name, value in environment.items())
        program.append(f'( export {exports}; eval "$AGG_SCRIPT" ) >/dev/null 2>&1; echo $?')
    completed = subprocess.run(
        ["/bin/bash", "-s"],
        input="\n".join(program) + "\n",
        env={"PATH": os.defpath, "AGG_SCRIPT": script},
        capture_output=True,
        text=True,
        check=True,
    )
    codes = [int(line) for line in completed.stdout.split()]
    assert len(codes) == len(environments)
    return codes


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _expected(
    job: str, classify_result: str, docs_only: str, event: str, results: dict[str, str]
) -> bool:
    if classify_result != "success":
        return False
    docs_lane = event == "pull_request" and docs_only == "true"
    for need, role in ROLES[job].items():
        result = results[need]
        if role == "always" and result != "success":
            return False
        if role == "full" and not (result == "success" or (docs_lane and result == "skipped")):
            return False
        if role == "docs" and result != ("success" if docs_lane else "skipped"):
            return False
    return True


@pytest.mark.parametrize("job", sorted(ROLES))
def test_each_aggregator_follows_the_stated_rule_over_every_combination(job: str) -> None:
    read, script = _classified_aggregator(job)
    needs = sorted(ROLES[job])
    outcomes = ("success", "failure", "cancelled", "skipped", "")
    cases: list[tuple[dict[str, str], bool]] = []
    for classify_result, docs_only, event in itertools.product(
        ("success", "failure", ""),
        ("true", "false"),
        ("pull_request", "push", "workflow_dispatch"),
    ):
        for combination in itertools.product(outcomes, repeat=len(needs)):
            # Every combination for up to three needs; for database-tier's five,
            # every combination with at most one result outside success/skipped.
            if len(needs) > 3 and sum(r not in {"success", "skipped"} for r in combination) > 1:
                continue
            results = dict(zip(needs, combination, strict=True))
            environment = {
                "CLASSIFY": classify_result,
                "DOCS_ONLY": docs_only,
                "EVENT_NAME": event,
                **{read[need]: result for need, result in results.items()},
            }
            cases.append((environment, _expected(job, classify_result, docs_only, event, results)))
    codes = _reconcile_many(script, [environment for environment, _ in cases])
    wrong = [
        environment
        for (environment, expected), code in zip(cases, codes, strict=True)
        if (code == 0) is not expected
    ]
    assert not wrong, (job, len(wrong), wrong[:3])
    assert any(expected for _, expected in cases) and not all(expected for _, expected in cases)


@pytest.mark.parametrize("job", sorted(ROLES))
def test_a_docs_only_pr_passes_each_aggregator_and_a_failed_classify_fails_it(job: str) -> None:
    read, script = _classified_aggregator(job)
    docs = {
        read[need]: ("success" if role in {"always", "docs"} else "skipped")
        for need, role in ROLES[job].items()
    }
    base = {"DOCS_ONLY": "true", "EVENT_NAME": "pull_request", **docs}
    assert _reconcile_one(script, {"CLASSIFY": "success", **base}) == 0
    for bad in ("failure", "cancelled", "skipped", ""):
        assert _reconcile_one(script, {"CLASSIFY": bad, **base}) != 0
    # The same skips on a push are a failure: push never takes the docs lane.
    assert _reconcile_one(script, {"CLASSIFY": "success", **base, "EVENT_NAME": "push"}) != 0


# --- validate-docs -------------------------------------------------------------------

_MODULE: Final = re.compile(r"^(tests/\S+\.py)(?: \\)?$")


def _docs_modules() -> list[str]:
    (step,) = [
        s
        for s in _steps("validate-docs")
        if s.get("name") == "Test the modules that read documentation"
    ]
    lines = str(step.get("run")).splitlines()
    assert lines[0].startswith("python -m pytest -m ")
    modules: list[str] = []
    for line in lines[1:]:
        match = _MODULE.match(line.strip())
        assert match, f"unrecognised validate-docs line: {line!r}"
        modules.append(match.group(1))
    return modules


#: Modules whose string literals name a documentation path without reading it,
#: each with the reason. Anything else that names one must be in `validate-docs`.
NAMES_WITHOUT_READING: Final = {
    "tests/ci_classify.py": "the classifier's own path vocabulary",
    "tests/architecture/test_ci_shards.py": "synthetic name-status lines for the classifier",
    "tests/unit/test_frontend_ci_classify.py": "frontend-quality classifier patterns, not reads",
    "tests/database/test_file_workspace_persistence.py": "a synthetic path inside a temp workspace",
    "tests/architecture/test_remote_nas_runtime.py": "asserts compose text names a runbook",
    "tests/pins.py": "writes the generated page; its reader, test_pins_are_current.py, is listed",
}


def _top_level_markdown() -> frozenset[str]:
    return frozenset(path.name for path in ROOT.glob("*.md"))


def _names_a_documentation_path(path: Path, top: frozenset[str]) -> bool:
    """A non-docstring string literal naming `docs/`, a runbook or a top-level `*.md`.

    `ROOT / "docs" / ...` and `"ops" / "runbooks"` are literals `"docs"` and
    `"runbooks"`; a top-level file is named exactly (`"AGENTS.md"`).
    """
    pattern = re.compile(
        r"(?:^|[\s`'\"(/])docs/|^docs$|(?:^|/)runbooks(?:/|$)|^(?:"
        + "|".join(re.escape(name) for name in sorted(top))
        + r")$"
    )
    text = path.read_text(encoding="utf-8")
    if "docs" not in text and "runbooks" not in text and not any(name in text for name in top):
        return False
    tree = ast.parse(text)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        ):
            docstrings.add(id(node.body[0].value))
    return any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and pattern.search(node.value) is not None
        for node in ast.walk(tree)
    )


def test_validate_docs_runs_the_fast_selection_over_existing_test_modules() -> None:
    (step,) = [
        s
        for s in _steps("validate-docs")
        if s.get("name") == "Test the modules that read documentation"
    ]
    first = str(step.get("run")).splitlines()[0]
    assert first == (
        'python -m pytest -m "not slow and not database and not network and not connector '
        'and not evaluation and not e2e and not recovery" --durations=20 \\'
    )
    modules = _docs_modules()
    assert modules == sorted(set(modules)), "keep the list sorted and unique"
    for module in modules:
        assert (ROOT / module).is_file(), module
        assert module.rsplit("/", 1)[-1].startswith("test_"), module


def test_every_module_that_names_a_documentation_path_is_in_validate_docs() -> None:
    """The list cannot rot: a new module that names `docs/` must join it or say why not.

    This is the static half. The list was found by tracing every `open` and
    directory listing of the full FAST selection (`sys.addaudithook`), which
    also found modules that reach documentation only by walking a tree
    (`ops/`, the repository root); those are listed but cannot be re-derived
    statically, so a *new* indirect reader is not caught here.
    """
    top = _top_level_markdown()
    listed = set(_docs_modules())
    named = {
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "tests").rglob("*.py"))
        if _names_a_documentation_path(path, top)
    }
    missing = sorted(named - listed - set(NAMES_WITHOUT_READING))
    assert not missing, f"name a documentation path but are not in validate-docs: {missing}"
    stale = sorted(set(NAMES_WITHOUT_READING) - named)
    assert not stale, f"exemptions that no longer name a documentation path: {stale}"
    assert not listed & set(NAMES_WITHOUT_READING)
