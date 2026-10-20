"""Deterministic CI test shards: `--ci-shard INDEX/COUNT --ci-shard-lane LANE`.

Why this exists. The FAST selection (`validate`, `dependency-floor`) and the
`migration_edge or migration` selection (`migration-edge`) outgrew the 60-minute
job budget on PR #337 (run 39283086971: both cancelled at exactly 60m, nothing
failed). The operator authorised sharding them on 2026-10-20 ("Shard FAST +
migration-edge") with **no coverage reduction**. This plugin is the selector the
matrix shards in `.github/workflows/repository-checks.yml` use.

What it guarantees, by construction:

- **Selection first, then sharding.** The hook is `trylast`, so it sees the
  items left after the `-m` expression (and the auto-marking in
  `tests/db/fixtures.py`) has run. A shard is therefore always a subset of the
  unsharded selection, never a different expression.
- **Exactly one shard per test.** The shard of a test is a pure function of its
  *file path* (the node ID before the first `::`), the shard count, and this
  module's committed weight table. It does not depend on what else was
  collected, so two shard processes cannot disagree about a file, and the
  shards are pairwise disjoint and together exhaustive.
- **New tests land automatically.** Files in the weight table are placed by a
  longest-processing-time-first greedy pass over measured seconds (balance);
  any other file -- a new one -- is placed by a stable SHA-256 of its path.
  Nothing is hand-listed, so nothing can be silently omitted; a stale table only
  costs balance, never coverage.
- **Whole files stay together**, so module- and class-scoped fixtures keep
  their locality.

The partition is also proved against real collections: `python -m tests.ci_shard
verify` runs `pytest --collect-only -q` unsharded and once per shard and
compares node-ID sets (the `validate-static` job runs it in CI). The workflow
matrix sizes are pinned to the `/COUNT` in each shard command and to the verify
step by `tests/architecture/test_ci_shards.py`.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import Final

import pytest

WEIGHTS_PATH: Final = Path(__file__).with_name("ci_shard_weights.json")
_SUMMARY: Final = pytest.StashKey[str]()


@cache
def lane_weights() -> Mapping[str, Mapping[str, float]]:
    """Lane -> {test file path: measured seconds}. Committed, regenerable."""
    loaded = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
    lanes = loaded["lanes"]
    return {
        lane: {str(path): float(seconds) for path, seconds in table.items()}
        for lane, table in lanes.items()
    }


def parse_shard(spec: str) -> tuple[int, int]:
    """`"2/3"` -> `(2, 3)`; 1-based index, refusing anything else."""
    index_text, separator, count_text = spec.partition("/")
    if (
        separator != "/"
        or not index_text.isdigit()
        or not count_text.isdigit()
        or index_text != str(int(index_text))
        or count_text != str(int(count_text))
    ):
        raise pytest.UsageError(f"--ci-shard expects INDEX/COUNT, got {spec!r}")
    index, count = int(index_text), int(count_text)
    if count < 1 or not 1 <= index <= count:
        raise pytest.UsageError(f"--ci-shard index must be within 1..COUNT, got {spec!r}")
    return index, count


def _hashed_shard(path: str, count: int) -> int:
    return int(hashlib.sha256(path.encode("utf-8")).hexdigest(), 16) % count


@cache
def _weighted_plan(lane: str, count: int) -> Mapping[str, int]:
    """Longest-processing-time-first over the committed table: path -> 0-based shard."""
    table = lane_weights()[lane]
    loads = [0.0] * count
    plan: dict[str, int] = {}
    for path, seconds in sorted(table.items(), key=lambda entry: (-entry[1], entry[0])):
        target = min(range(count), key=lambda shard: (loads[shard], shard))
        plan[path] = target
        loads[target] += seconds
    return plan


def shard_of(path: str, lane: str, count: int) -> int:
    """The 0-based shard of a test file. Pure: path, lane, count, committed table."""
    planned = _weighted_plan(lane, count).get(path)
    return planned if planned is not None else _hashed_shard(path, count)


def item_path(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("ci-shard", "deterministic CI shards (tests/ci_shard.py)")
    group.addoption(
        "--ci-shard",
        dest="ci_shard",
        default=None,
        metavar="INDEX/COUNT",
        help="run only the 1-based INDEX of COUNT deterministic file-level shards",
    )
    group.addoption(
        "--ci-shard-lane",
        dest="ci_shard_lane",
        default=None,
        metavar="LANE",
        help="the weight table (tests/ci_shard_weights.json) that balances the shards",
    )


def pytest_configure(config: pytest.Config) -> None:
    spec = config.getoption("ci_shard")
    lane = config.getoption("ci_shard_lane")
    if spec is None:
        if lane is not None:
            raise pytest.UsageError("--ci-shard-lane requires --ci-shard")
        return
    parse_shard(spec)
    if lane not in lane_weights():
        raise pytest.UsageError(
            f"--ci-shard requires --ci-shard-lane in {sorted(lane_weights())}, got {lane!r}"
        )


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Keep only this shard's files, after every selecting hook has run."""
    spec = config.getoption("ci_shard")
    if spec is None:
        return
    index, count = parse_shard(spec)
    lane = config.getoption("ci_shard_lane")
    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        if shard_of(item_path(item.nodeid), lane, count) == index - 1:
            selected.append(item)
        else:
            deselected.append(item)
    config.stash[_SUMMARY] = (
        f"ci-shard {index}/{count} lane={lane}: "
        f"{len(selected)} of {len(selected) + len(deselected)} selected tests"
    )
    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = selected


def pytest_report_collectionfinish(config: pytest.Config) -> str | None:
    return config.stash.get(_SUMMARY, None)


# --- The partition proof against real collections ---------------------------------


def _collect(arguments: Sequence[str]) -> frozenset[str]:
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"]
    completed = subprocess.run(  # noqa: S603 - this interpreter, fixed pytest arguments
        [*command, *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    # 5 is pytest's "no tests collected": an empty selection, reported below.
    if completed.returncode not in (0, 5):
        raise SystemExit(
            f"collection failed ({completed.returncode}) for {list(arguments)}:\n"
            f"{completed.stdout[-4000:]}{completed.stderr[-4000:]}"
        )
    nodes = [line for line in completed.stdout.splitlines() if line.startswith("tests/")]
    if len(nodes) != len(set(nodes)):
        raise SystemExit(f"duplicate node IDs in one collection for {list(arguments)}")
    return frozenset(nodes)


def verify(
    lane: str,
    shards: int,
    expression: str,
    paths: Sequence[str] = (),
    *,
    require_every_shard: bool = True,
) -> list[str]:
    """Collect unsharded and every shard; return the partition violations (empty = proved).

    Node IDs are compared exactly. The unsharded selection is collected twice:
    a file whose node IDs differ between those two collections has
    nondeterministic parametrize IDs (for example a freshly issued identifier in
    the ID), so for that file alone exact IDs cannot be compared across
    processes and its per-file test count is compared instead. Every file is
    also checked at file level -- in exactly one shard, with the unsharded
    count -- which is the unit the selector assigns.

    `require_every_shard=False` is for a bounded subtree, where a shard may own
    none of the files; the full-selection proof in CI always requires every shard.
    """
    base = ["-m", expression, *paths]
    runs = [base, base] + [
        [*base, "--ci-shard", f"{index}/{shards}", "--ci-shard-lane", lane]
        for index in range(1, shards + 1)
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(runs)) as pool:
        control, unsharded, *parts = list(pool.map(_collect, runs))
    problems: list[str] = []
    if not unsharded:
        problems.append("the unsharded selection is empty")
    unstable = frozenset(item_path(node) for node in control ^ unsharded)
    for path in sorted(unstable):
        print(
            f"::warning title=test shards::{path} has nondeterministic node IDs; compared by count"
        )

    def stable(nodes: frozenset[str]) -> frozenset[str]:
        return frozenset(node for node in nodes if item_path(node) not in unstable)

    def per_file(nodes: frozenset[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for node in nodes:
            counts[item_path(node)] = counts.get(item_path(node), 0) + 1
        return counts

    owners: dict[str, int] = {}
    for index, part in enumerate(parts, start=1):
        print(f"lane={lane} shard {index}/{shards}: {len(part)} tests")
        if not part and require_every_shard:
            problems.append(f"shard {index}/{shards} selects nothing")
        for path in per_file(part):
            if path in owners:
                problems.append(f"shards {owners[path]} and {index} both select {path}")
            owners[path] = index
        for other_index, other in enumerate(parts[index:], start=index + 1):
            overlap = part & other
            if overlap:
                problems.append(
                    f"shards {index} and {other_index} overlap on {len(overlap)} tests, "
                    f"e.g. {sorted(overlap)[0]}"
                )
    union = frozenset().union(*parts)
    missing = stable(unsharded) - stable(union)
    extra = stable(union) - stable(unsharded)
    if missing:
        problems.append(f"{len(missing)} selected tests are in no shard, e.g. {sorted(missing)[0]}")
    if extra:
        problems.append(f"{len(extra)} shard tests are not selected, e.g. {sorted(extra)[0]}")
    expected, found = per_file(unsharded), per_file(union)
    for path in sorted(set(expected) | set(found)):
        if expected.get(path, 0) != found.get(path, 0):
            problems.append(
                f"{path}: {expected.get(path, 0)} selected tests, "
                f"{found.get(path, 0)} across the shards"
            )
    print(
        f"lane={lane} unsharded={len(unsharded)} union={len(union)} "
        f"sum={sum(len(part) for part in parts)} shards={shards} "
        f"files={len(expected)} unstable_files={len(unstable)}"
    )
    return problems


def write_weights(lane: str, reports: Sequence[str]) -> None:
    """Per-file seconds summed from JUnit `testcase` times. Balance only, never coverage."""
    import xml.etree.ElementTree as ElementTree

    seconds: dict[str, float] = {}
    for report in reports:
        for case in ElementTree.parse(report).iter("testcase"):  # noqa: S314
            path = case.get("file")
            if not path:
                raise SystemExit(f"{report}: testcase without `file`; use junit_family=xunit1")
            seconds[path] = seconds.get(path, 0.0) + float(case.get("time") or 0.0)
    loaded = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
    loaded["lanes"][lane] = {path: round(seconds[path], 1) for path in sorted(seconds)}
    WEIGHTS_PATH.write_text(json.dumps(loaded, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lane_weights.cache_clear()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.ci_shard")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("verify", help="prove the shards partition a selection")
    check.add_argument("--lane", required=True)
    check.add_argument("--shards", required=True, type=int)
    check.add_argument("-m", dest="expression", required=True)
    check.add_argument("paths", nargs="*")
    weigh = commands.add_parser(
        "weigh",
        help="rewrite one lane's weight table from `-o junit_family=xunit1` JUnit XML files",
    )
    weigh.add_argument("--lane", required=True)
    weigh.add_argument("reports", nargs="+")
    arguments = parser.parse_args(argv)
    if arguments.command == "weigh":
        write_weights(arguments.lane, arguments.reports)
        return 0
    problems = verify(arguments.lane, arguments.shards, arguments.expression, arguments.paths)
    for problem in problems:
        print(f"::error title=test shards::{problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
