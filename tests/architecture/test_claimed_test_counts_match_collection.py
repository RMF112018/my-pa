"""Every "N tests" claim the plan makes about a suite, checked against collection.

The spelled-count sweep next door reads *words* — "fifty-four capabilities" —
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

#: A claim naming a test file and how many tests it holds. The separator is
#: whatever short punctuation the prose uses, because it varies and the guard
#: must not: `` `…test_entity_repository.py` — 46 tests ``,
#: `` `…test_entity_context.py`, 9 tests ``, `` `…privacy_regression.py` (19
#: tests ``.
#:
#: Requiring an em dash bound four of the seven claims in this table. A plant
#: changing `, 9 tests` to `, 44 tests` and `(19 tests` to `(31 tests` was not
#: caught — the guard's docstring said "every" and it meant "every one written
#: with a dash".
CLAIM: Final = re.compile(r"`(tests/[\w/]+\.py)`[^.\n|]{0,4}?(\d+)\s+tests\b")

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


#: The plan's claims about the labelled resolution corpus, which no other guard
#: reads. The spelled-count sweep only reads numbers before capability/purpose
#: nouns; the pattern above only reads `` `tests/….py` — N tests ``. So the
#: corpus figures sat between two guards and drifted twice — once by four cases
#: when the currency axis was added, and again by two when the liveness axis
#: was. Both times the commit that moved the number left the prose behind, and
#: both times a reviewer found it rather than a test.
CORPUS_CLAIM: Final = re.compile(
    r"(?P<cases>[\w-]+) labelled (?:collision-biased )?cases (?:in|over) (?P<over>[\w-]+) "
    r"(?P<noun>famil(?:y|ies)|entities)"
)

_WORDS: Final = {
    "thirty-one": 31,
    "thirty-three": 33,
    "thirty-five": 35,
    "thirty-seven": 37,
    "fifteen": 15,
    "nineteen": 19,
    "twenty": 20,
    "twenty-one": 21,
    "twenty-three": 23,
    "twenty-five": 25,
}


def _spelled(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    return _WORDS.get(value.lower())


def _corpus_truth() -> dict[str, int]:
    from tests.evaluation.fixtures.resolution_cases import RESOLUTION_CASES
    from tests.evaluation.fixtures.resolution_corpus import CORPUS_ENTITIES

    return {
        "cases": len(RESOLUTION_CASES),
        "families": len({case.family for case in RESOLUTION_CASES}),
        "entities": len(CORPUS_ENTITIES),
    }


def test_every_claimed_corpus_size_matches_the_corpus() -> None:
    """Corpus-size claims in the plan, against the fixture that is measured."""
    text = PLAN.read_text(encoding="utf-8")
    truth = _corpus_truth()
    wrong: list[str] = []
    seen = 0
    for match in CORPUS_CLAIM.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        cases = _spelled(match.group("cases"))
        over = _spelled(match.group("over"))
        if cases is None or over is None:
            wrong.append(f"{PLAN.name}:{line} spells a number this guard cannot read")
            continue
        seen += 1
        over_noun = match.group("noun")
        expected_over = truth["entities"] if over_noun == "entities" else truth["families"]
        if cases != truth["cases"] or over != expected_over:
            wrong.append(
                f"{PLAN.name}:{line} says {cases} cases over {over} "
                f"{over_noun}; the corpus holds {truth['cases']} and {expected_over}"
            )
    assert seen, "no corpus-size claim found; the pattern or the prose changed shape"
    assert not wrong, wrong


#: A claim of the form `` `pytest -m "<expr>"` … **N passed** ``: a whole-tier
#: figure, stated as a bare number beside the exact command that produces it.
#:
#: **This is the shape that carried the largest wrong number this plan has
#: held.** The database-tier row claimed 1,926 passed for a selection that
#: collects 951 — the figure was produced by running whole directories with no
#: `-m` filter and then described as partitioning the marker selection. Every
#: guard in the repository was green: the spelled-count sweep reads words and
#: not digits, and the file-claim pattern above requires a backticked test
#: *path*, which a tier figure does not have. An independent reviewer found it
#: with one `--collect-only`, which is the check this closes.
#:
#: Collection, not execution: this asserts the claim is about the right *set*.
#: A tier's pass count may fall below its collected count for a legitimate
#: reason — a skip — so the rule is that a claim may not exceed collection, and
#: a shortfall is reported with its size rather than silently allowed.
TIER_CLAIM: Final = re.compile(
    r"`pytest\s+-m\s+\"(?P<expr>[^\"]+)\"[^`]*`[^|]{0,400}?\*\*(?P<count>[\d,]+)\s+passed",
)

_TIER_COLLECTED: dict[str, int] = {}


def _tier_collected(expression: str) -> int:
    if expression not in _TIER_COLLECTED:
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
                "-m",
                expression,
                "tests",
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
        found = re.search(r"(\d+)/\d+ tests collected", result.stdout) or re.search(
            r"(\d+) tests? collected", result.stdout
        )
        assert found is not None, (
            f"could not collect -m {expression!r}:\n"
            f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
        )
        _TIER_COLLECTED[expression] = int(found.group(1))
    return _TIER_COLLECTED[expression]


def _tier_claims() -> list[tuple[str, int, int]]:
    text = PLAN.read_text(encoding="utf-8")
    found: list[tuple[str, int, int]] = []
    for match in TIER_CLAIM.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        found.append((match.group("expr"), int(match.group("count").replace(",", "")), line))
    return found


def test_the_plan_claims_a_pass_count_for_at_least_one_tier() -> None:
    """If this pattern stops matching, the guard guards nothing — and it did once."""
    assert _tier_claims(), (
        'no `pytest -m "..."` — **N passed** claim found in the plan; either the '
        "evidence table changed shape or this pattern went stale"
    )


@pytest.mark.parametrize(("expression", "claimed", "line"), _tier_claims())
def test_no_claimed_tier_pass_count_exceeds_what_that_selection_collects(
    expression: str, claimed: int, line: int
) -> None:
    """A tier figure, against the selection the sentence beside it names.

    Deliberately an upper bound rather than an equality: a skipped test is a
    real reason for a pass count to sit below collection, and a guard that
    forbade it would be corrected by weakening the claim rather than by fixing
    anything. Claiming *more* passes than the selection holds has no benign
    reading at all.
    """
    collected = _tier_collected(expression)
    assert claimed <= collected, (
        f"{PLAN.name}:{line} claims {claimed} passed for `-m {expression!r}`, which "
        f"collects only {collected}. The figure was measured against a different "
        "selection than the one it names. Correct the plan rather than this test."
    )
