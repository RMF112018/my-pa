"""Every "N tests" claim the plan makes about a suite, checked against collection.

The spelled-count sweep next door reads words — a spelled capability total —
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
from tests import pins

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


# --- the current tier and corpus figures: bound through the generated page ------
#
# The plan's evidence table used to state the current FAST, architecture,
# database and evaluation figures and the `mypy` corpus by hand, and the four
# readers below bound each one to a fresh collection. That guard was right and
# its cost was every pull request that added a test: the plan was edited each
# time, and the two plan files were permanently contended.
#
# Phase P5 (operator decision O1-a, GENERATE) moves the *current* figures into
# `tests/pins.json`'s `census` section, rendered into
# `docs/generated/repository-state.md`. The equality survives unchanged in
# strength: `test_the_census_matches_a_fresh_measurement` compares each committed
# figure with the same single collection this module always took, so a test
# added without `regen --measure` fails here, one figure per test. The page is
# held to the snapshot by `test_generated_repository_state_is_rendered`.
#
# The plan keeps its dated paragraphs as history. They are no longer current, so
# they are no longer bound; what is bound instead is that the plan *restates no
# current figure* in any of the four shapes these readers recognise, and that
# each evidence row links to the generated page. A current figure re-added to the
# plan, right or wrong, fails `test_the_plan_restates_no_current_tier_figure`.

#: A claim of the form `` `pytest -m "<expr>"` … **N passed** ``: a whole-tier
#: figure, stated as a bare number beside the exact command that produces it.
#:
#: **This is the shape that carried the largest wrong number this plan has
#: held.** The database-tier row claimed 1,926 passed for a selection that
#: collects 951. An independent reviewer found it with one `--collect-only`;
#: this reader closed it, and now keeps the shape out of the plan.
TIER_CLAIM: Final = re.compile(
    r"`pytest\s+-m\s+\"(?P<expr>[^\"]+)\"[^`]*`[^|]{0,400}?\*\*(?P<count>[\d,]+)\s+passed"
    r"(?P<tail>[^|]{0,200})",
)

#: `mypy` only. `ruff` was bound once and should not have been: it walks the
#: working directory rather than the index, so its corpus size is a property of
#: what happens to be on disk (925 locally, 927 in CI, at one commit).
_TOOL_CLAIM: Final = re.compile(
    r"`(?P<tool>mypy)[^`]*`[^|]{0,200}?clean over (?P<count>[\d,]+) files"
)

#: The architecture tier, named by path rather than by marker, and the
#: evaluation tier, whose marker is written without quotes.
_PATH_TIER_CLAIM: Final = re.compile(r"Architecture tier \*\*(?P<count>[\d,]+)\s+passed")
_BARE_MARKER_CLAIM: Final = re.compile(
    r"`pytest\s+-m\s+(?P<expr>[a-z_]+)`[^|]{0,120}?(?P<count>[\d,]+)\s+passed"
)

#: Every reader of a current tier or corpus figure, by name.
CURRENT_FIGURE_READERS: Final = {
    "tier": TIER_CLAIM,
    "tool": _TOOL_CLAIM,
    "path tier": _PATH_TIER_CLAIM,
    "bare marker": _BARE_MARKER_CLAIM,
}

#: The plan's evidence rows that used to carry the current figures, by label.
#: Each must now point at the generated page.
LINKED_ROWS: Final = (
    "FAST tier validation",
    "Architecture tier",
    "Types",
    "Full database tier disposition",
    "Evaluation tier",
)
GENERATED_STATE: Final = "docs/generated/repository-state.md"

#: One collection, reused by every figure this module checks.
#:
#: **Four selections meant four full-tree collections, and that broke CI.** Each
#: `pytest --collect-only` re-imports the whole suite (38 to 40 seconds apiece)
#: and the `dependency-floor` job timed out at 10m16s. One census answers every
#: selection; the script is `tests.pins.CENSUS_SCRIPT`, which `regen --measure`
#: runs too.
_CENSUS: list[tuple[str, frozenset[str]]] = []


def _census() -> list[tuple[str, frozenset[str]]]:
    """Every collected test, with the markers it carries and the path it sits at."""
    if not _CENSUS:
        _CENSUS.extend(pins.census_rows())
    return _CENSUS


@pytest.mark.parametrize("figure", pins.MEASURED)
def test_the_census_matches_a_fresh_measurement(figure: str) -> None:
    """A committed tier or corpus figure, against a fresh collection and `find`.

    An equality, for the reason the plan-bound version recorded: an upper bound
    admitted the understatement that actually happened, twice, each time stale
    by exactly the tests the same commit added.
    """
    committed = pins.load()["census"][figure]
    measured = pins.measure(_census())[figure]
    assert committed == measured, (
        f"tests/pins.json census {figure!r} is {committed}; a fresh measurement finds "
        f"{measured}. Run `PYTHONPATH=src .venv/bin/python -m tests.pins regen --measure` "
        f"(it also rewrites {GENERATED_STATE}) rather than editing this test."
    )


def _current_figures(text: str) -> list[tuple[str, str, int]]:
    """`(reader, matched text, line)` for every current-figure shape in `text`."""
    found: list[tuple[str, str, int]] = []
    for name, reader in CURRENT_FIGURE_READERS.items():
        for match in reader.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            found.append((name, match.group(0)[:160], line))
    return found


def test_the_plan_restates_no_current_tier_figure() -> None:
    """The replacement guard for the plan-bound figures (O1-a).

    Current figures live in the generated page; a figure in the plan's shape is a
    second, hand-maintained copy that the census no longer binds.
    """
    found = _current_figures(PLAN.read_text(encoding="utf-8"))
    assert not found, (
        f"{PLAN.name} restates a current tier or corpus figure: {found}. Current figures "
        f"are generated into {GENERATED_STATE}; link to it and keep dated figures as "
        "unbolded history."
    )


def test_each_plan_evidence_row_links_to_the_generated_state() -> None:
    rows = {
        label: [
            line
            for line in PLAN.read_text(encoding="utf-8").splitlines()
            if line.startswith(f"| {label} |")
        ]
        for label in LINKED_ROWS
    }
    missing = [label for label, lines in rows.items() if len(lines) != 1]
    assert not missing, f"{PLAN.name} no longer has exactly one row for {missing}"
    unlinked = [label for label, (line,) in rows.items() if GENERATED_STATE not in line]
    assert not unlinked, f"{PLAN.name} rows {unlinked} do not link to {GENERATED_STATE}"


def test_every_current_figure_reader_still_reads_its_shape() -> None:
    """The plan-side guard is only as good as its readers, so each is planted."""
    planted = (
        '| a | `pytest -m "not slow"` — collects 9; a green execution requires '
        "**9 passed**, 0 skipped |\n"
        "| b | `mypy` (configured targets) — clean over 745 files |\n"
        "| c | the tier guard binds Architecture tier **9,508 passed** |\n"
        "| d | `pytest -m evaluation` — 2 passed |\n"
    )
    assert sorted(name for name, _, _ in _current_figures(planted)) == sorted(
        CURRENT_FIGURE_READERS
    )
