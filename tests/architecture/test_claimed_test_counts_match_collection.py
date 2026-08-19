"""Every "N tests" the plan claims about a suite, checked against collection.

The spelled-count sweep next door reads *words* — "fifty-three capabilities" —
and is blind to digits. The implementation plan's evidence table is written in
digits, so the figures most likely to drift were bound to nothing at all.

They drifted. Two of them were wrong at the head that introduced them: the plan
said `test_entity_governance.py` had 19 tests in a cell *rewritten by that same
commit as a dated correction*, while the same commit added six more; and it said
`test_entity_repository.py` had 40 while five were added beside it. One cell even
printed the `--collect-only` command that disproves it.

That is the shape this guard exists for: a claim about a suite is checked by
running the suite's collection, so adding a test to a file the plan describes
either updates the plan or fails here.

Collection is run in a subprocess rather than counting `def test_`, because
`@pytest.mark.parametrize` makes those two numbers differ — and it is the
collected count that a reader takes "19 tests" to mean.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[2]
PLAN: Final = ROOT / "docs" / "plans" / "relationship-intelligence-implementation-plan.md"

#: A claim naming a test file and how many tests it holds:
#: `` `tests/unit/test_entity_context.py` — 9 tests ``. The dash may be an em
#: dash or a hyphen, and the number may carry a comma.
CLAIM: Final = re.compile(r"`(tests/[\w/]+\.py)`\s*[—-]\s*(\d+)\s+tests\b")

#: Collection counts are stable but not free; one subprocess per *file*, not per
#: claim, since the plan names some files more than once.
_COLLECTED: dict[str, int] = {}


def _collected(relative_path: str) -> int:
    if relative_path not in _COLLECTED:
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
                relative_path,
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
        found = re.search(r"(\d+) tests? collected", result.stdout)
        assert found is not None, (
            f"could not collect {relative_path}:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
        )
        _COLLECTED[relative_path] = int(found.group(1))
    return _COLLECTED[relative_path]


def _claims() -> list[tuple[str, int, int]]:
    text = PLAN.read_text(encoding="utf-8")
    found: list[tuple[str, int, int]] = []
    for match in CLAIM.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        found.append((match.group(1), int(match.group(2)), line))
    return found


def test_the_plan_claims_a_test_count_for_at_least_one_suite() -> None:
    """If the pattern stops matching, this guard silently guards nothing."""
    assert _claims(), (
        "no `tests/....py` — N tests claim found in the plan; either the evidence "
        "table changed shape or this pattern went stale"
    )


@pytest.mark.parametrize(("path", "claimed", "line"), _claims())
def test_every_claimed_test_count_matches_collection(path: str, claimed: int, line: int) -> None:
    """The plan's figure, against what pytest actually collects."""
    assert (ROOT / path).exists(), f"{PLAN.name}:{line} names {path}, which does not exist"
    actual = _collected(path)
    assert claimed == actual, (
        f"{PLAN.name}:{line} says {path} holds {claimed} tests; collection finds {actual}. "
        "Correct the plan rather than this test."
    )
