"""The review record may not claim a number of rounds it does not carry rows for.

`docs/plans/relationship-intelligence-implementation-plan.md` records independent
merge review in two places: section 4a states how many rounds have run, and
section 4c carries one table row per round. Both numbers were written by hand,
and both went wrong in the same way twice.

At `4542109` section 4a said **seven** while section 4c said **three** and
carried three rows; the commit messages documented **eight**. Rounds 4 through 8
appeared nowhere in the section whose stated purpose is to record independent
review — including round 8, whose `DO NOT MERGE` verdict the very next commit was
written to answer. One round earlier, that same section had recorded its own
version of this defect: it had listed round 1 only, while the commit adding its
corrections was titled for round 2.

A count restated by hand beside the set it counts is a count that drifts the
first time the set grows and nobody looks. So neither number is trusted here:
the rows are the population, and both spellings are checked against them.

**What this does not check.** Whether a recorded round happened, whether its
verdict is reported honestly, or whether the head it names is real. Those are
claims about the world that a repository test cannot settle, and pretending
otherwise would be the vacuous-guard shape this campaign has now been caught by
repeatedly. What it settles is narrower and was the actual failure: the document
says a number, and the number disagrees with the document.
"""

from __future__ import annotations

import re
from pathlib import Path

PLAN = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "plans"
    / "relationship-intelligence-implementation-plan.md"
)

#: Spelled numbers as they appear in the prose. Only the range the document can
#: plausibly reach is listed; a round past it fails the lookup rather than
#: passing silently, which is the direction a missing entry should fail in.
_SPELLED: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

#: A row of section 4c's table: `| 4 | \\`271e949\\` | 2 of 4 blocked | ... |`
_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*`([0-9a-f]{7,40})`\s*\|", re.MULTILINE)

#: Section 4c's opening claim, and section 4a's.
_ROUNDS_SO_FAR = re.compile(r"\*\*([A-Za-z]+) rounds so far", re.IGNORECASE)
_ROUNDS_HAVE_RUN = re.compile(r"([A-Za-z]+) rounds have now run", re.IGNORECASE)


def _text() -> str:
    return PLAN.read_text(encoding="utf-8")


def _recorded() -> list[tuple[int, str]]:
    return [(int(number), head) for number, head in _ROW.findall(_text())]


def test_the_table_this_module_reads_is_not_empty() -> None:
    """An anti-vacuity floor, so a changed table shape cannot read as agreement.

    Every assertion below compares a claim against `_recorded()`. If the row
    pattern stopped matching — a column added, the head spelled without
    backticks, the table replaced with a list — `_recorded()` would return
    nothing and the two count assertions would compare a claim against zero,
    which fails loudly rather than passing. What would *not* fail loudly is a
    future edit that also removed the claims. This floor is what makes that
    case red.
    """
    recorded = _recorded()
    assert len(recorded) >= 3, (
        f"only {len(recorded)} review rounds parsed from {PLAN.name}; the table "
        "shape this module reads has changed"
    )


def test_the_rounds_are_numbered_consecutively_from_one() -> None:
    """A missing round is a gap in the numbering, which is how five went missing."""
    numbers = [number for number, _ in _recorded()]
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"the recorded rounds are numbered {numbers}; a gap means a round the "
        "document skipped, which is exactly what this section did between "
        "rounds 3 and 9"
    )


def test_each_round_names_a_distinct_head() -> None:
    """Two rounds against one head would mean one of them reviewed nothing new."""
    heads = [head for _, head in _recorded()]
    assert len(set(heads)) == len(heads), f"a head is recorded twice: {heads}"


def test_both_spelled_counts_match_the_rows_the_document_carries() -> None:
    """The defect itself: section 4a said seven, section 4c said three, eight had run."""
    recorded = len(_recorded())
    text = _text()

    so_far = _ROUNDS_SO_FAR.search(text)
    assert so_far is not None, (
        "section 4c no longer states how many rounds it records; the claim this "
        "module exists to check has been deleted rather than corrected"
    )
    claimed_in_table = _SPELLED.get(so_far.group(1).lower())
    assert claimed_in_table == recorded, (
        f"section 4c says {so_far.group(1)!r} rounds so far and carries {recorded} rows"
    )

    have_run = _ROUNDS_HAVE_RUN.search(text)
    assert have_run is not None, "section 4a no longer states how many rounds have run; see above"
    claimed_in_prose = _SPELLED.get(have_run.group(1).lower())
    assert claimed_in_prose == recorded, (
        f"section 4a says {have_run.group(1)!r} rounds have now run while "
        f"section 4c carries {recorded} rows. These two sentences are "
        "seventy-six lines apart and disagreed for two rounds"
    )
