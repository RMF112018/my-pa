"""Classify a `repository-checks` run from its changed paths: `docs_only=` and `shard_proof=`.

Usage (the `classify` job in `.github/workflows/repository-checks.yml`)::

    git diff --name-status --no-renames BASE HEAD \\
      | python3 -I ci_classify.py --event "$GITHUB_EVENT_NAME" >> "$GITHUB_OUTPUT"

Standard library only, run as a script: the job installs nothing. The job runs
the merge-base's copy of this file, never the PR's, and writes the full-run
answer itself when it cannot resolve the diff.

Both answers fail closed. Anything this module cannot establish -- a non-PR
event, a diff the workflow could not resolve, an empty diff, a status letter it
does not know, a path that is not a plain normal relative path -- answers
`docs_only=false` (the full run) and `shard_proof=true` (the partition proof).

`docs_only=true` iff the event is `pull_request` and EVERY changed path, on
both sides of any rename or copy line, is under `docs/`, or a top-level `*.md`,
or a `*.md` under `ops/runbooks/`. On such a PR the workflow skips every pytest,
database, migration, dependency-floor and web job and runs only
`validate-static` (document/configuration validation, ruff, mypy) and
`validate-docs` (the test modules that read those paths, listed in that job).

`shard_proof=true` unless the event is `pull_request` and no changed path can
change how `tests/ci_shard.py` partitions a selection. The partition is a pure
function of a test's *file path*, the shard count and
`tests/ci_shard_weights.json` (`shard_of`), applied after selection by a
`trylast` hook; the proof (`python -m tests.ci_shard verify`) compares a real
unsharded collection against the union of the shards. Editing the body of an
existing test module cannot move its tests between files, so it cannot break
that equality. What can: the selector, its weights, its pin
(`tests/architecture/test_ci_shards.py`), the workflow commands, pytest
configuration (`pyproject.toml`, `pytest.ini`, `tox.ini`, `setup.cfg`), any
`conftest.py` or other non-`test_*` module under `tests/` (hooks, plugins and
the auto-marking in `tests/db/fixtures.py`), a test module loaded as a plugin
(`PLUGIN_TEST_MODULES`), and adding, deleting or renaming any `*.py` under
`tests/` (a rename appears as `A`+`D` under `--no-renames`).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

#: Paths whose change always re-runs the partition proof.
SHARD_PROOF_PATHS: Final = frozenset(
    {
        "tests/ci_shard.py",
        "tests/ci_shard_weights.json",
        "tests/architecture/test_ci_shards.py",
        "tests/db/fixtures.py",
        ".github/workflows/repository-checks.yml",
        "pyproject.toml",
        "pytest.ini",
        "tox.ini",
        "setup.cfg",
    }
)

#: `test_*.py` modules another module loads through `pytest_plugins`, so their
#: hooks act on collection. Pinned by `tests/architecture/test_ci_shards.py`.
PLUGIN_TEST_MODULES: Final = frozenset({"tests/security/test_cross_principal_review_isolation.py"})

_STATUSES: Final = frozenset("AMDT")
_PAIRED: Final = frozenset("RC")


@dataclass(frozen=True)
class Change:
    status: str
    paths: tuple[str, ...]


def is_normal(path: str) -> bool:
    """A plain relative POSIX path: no empty, `.` or `..` segment, no backslash or quoting."""
    if not path or path.startswith("/") or "\\" in path or path.startswith('"'):
        return False
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in path):
        return False
    return all(segment not in ("", ".", "..") for segment in path.split("/"))


def is_docs_path(path: str) -> bool:
    if not is_normal(path):
        return False
    segments = path.split("/")
    if segments[0] == "docs":
        return len(segments) > 1
    if len(segments) == 1:
        return path.endswith(".md") and path != ".md"
    if segments[:2] == ["ops", "runbooks"]:
        return len(segments) > 2 and path.endswith(".md") and segments[-1] != ".md"
    return False


def _is_test_python(path: str) -> bool:
    return path.startswith("tests/") and path.endswith(".py")


def needs_shard_proof(change: Change) -> bool:
    for path in change.paths:
        if not is_normal(path):
            return True
        name = path.rsplit("/", 1)[-1]
        if path in SHARD_PROOF_PATHS or path in PLUGIN_TEST_MODULES or name == "conftest.py":
            return True
        if _is_test_python(path):
            if change.status != "M":
                return True
            if not name.startswith("test_"):
                return True
    return False


def parse(lines: Iterable[str]) -> list[Change] | None:
    """`git diff --name-status` lines -> changes; `None` for anything unrecognised."""
    changes: list[Change] = []
    for raw in lines:
        line = raw.rstrip("\n")
        if not line:
            continue
        fields = line.split("\t")
        status, paths = fields[0], tuple(fields[1:])
        letter = status[:1]
        single = letter in _STATUSES and status == letter and len(paths) == 1
        paired = letter in _PAIRED and status[1:].isdigit() and len(paths) == 2
        if not (single or paired):
            return None
        changes.append(Change(letter, paths))
    return changes


def classify(event: str, lines: Iterable[str] | None) -> dict[str, bool]:
    """`lines is None` means the workflow could not resolve the diff."""
    full = {"docs_only": False, "shard_proof": True}
    if event != "pull_request" or lines is None:
        return full
    changes = parse(lines)
    if not changes:
        return full
    docs_only = all(is_docs_path(path) for change in changes for path in change.paths)
    return {
        "docs_only": docs_only,
        "shard_proof": not docs_only and any(needs_shard_proof(change) for change in changes),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 tests/ci_classify.py")
    parser.add_argument("--event", required=True)
    arguments = parser.parse_args(argv)
    result = classify(arguments.event, sys.stdin.read().splitlines())
    for key in ("docs_only", "shard_proof"):
        print(f"{key}={'true' if result[key] else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
