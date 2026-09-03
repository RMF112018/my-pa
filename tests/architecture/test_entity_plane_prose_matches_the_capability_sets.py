"""The entity plane's prose counts match the sets those sentences describe.

**A half-correction survived a full review cycle and an unqualified PASS,
because nothing read this prose.** `RI-ENT-WP-10`'s `fc735550`, whose subject
line is "correct every count derived from the read/write split", corrected two
of the three numbers in `settings.py`'s plane-gate docstring and left the third
standing. The result did not even close arithmetically -- it claimed 16 reads
and 23 writes over a set of 54 -- and it sat four lines above a sibling
docstring in the same file stating the write count correctly. `ruff`, `mypy`,
every tier and an independent review all passed over it.

**Why this is not merely a stale number.** The sentence is a privacy gate's own
docstring. An operator deciding whether to set
`MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` reads it to learn how large the
mutation surface behind the second switch is, and it understated that surface
by 15 -- the whole of the `entities.names.*`, `addresses.*`, `communication.*`,
`participations.*` and `affiliations.*` write families. A reader deciding an
access question from a number is the case where a wrong number does harm.

`tests/architecture/test_spelled_counts_match_the_sets_they_name.py` binds the
`Capability` and `Purpose` totals in the same shape and has caught this class
twice. It does not reach these sentences: their nouns are `writes`, `reads` and
`` `entities.` names ``, none of which that module's claim pattern reads. This
module is the missing equivalent, and it is deliberately narrow -- three derived
quantities, named sentences, no allowlist -- because a guard that fires on
prose it cannot derive becomes a guard people delete.

**Every pattern below is required to match.** A sentence that is reworded so
this module stops seeing it reddens `test_every_bound_sentence_is_still_there`
rather than passing silently, which is the failure mode that let the original
defect through: an unread claim and an unmatched pattern look identical from
the success path.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from my_pa.application.service import _ENTITY_CAPABILITIES, _ENTITY_WRITE_CAPABILITIES

ROOT: Final = Path(__file__).resolve().parents[2]

#: Built rather than written out, so this module states no spelled number of its
#: own next to a noun the sibling guard reads.
_UNITS: Final[tuple[str, ...]] = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS: Final[tuple[str, ...]] = (
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)


def _spelled(value: int) -> str:
    """The English form this corpus uses for a two-digit count."""
    if value < len(_UNITS):
        return _UNITS[value]
    tens, unit = divmod(value, 10)
    head = _TENS[tens - 2]
    return head if unit == 0 else f"{head}-{_UNITS[unit]}"


def _parse(word: str) -> int | None:
    """The inverse, for whatever a bound sentence actually says."""
    word = word.strip().lower()
    if word in _UNITS:
        return _UNITS.index(word)
    head, _, tail = word.partition("-")
    if head in _TENS:
        base = (_TENS.index(head) + 2) * 10
        if not tail:
            return base
        if tail in _UNITS and _UNITS.index(tail) < 10:
            return base + _UNITS.index(tail)
    return None


def _quantities() -> dict[str, int]:
    """The three facts these sentences describe, derived from the sets."""
    every = frozenset(_ENTITY_CAPABILITIES)
    writes = frozenset(_ENTITY_WRITE_CAPABILITIES)
    assert writes <= every, "the write set is a subset of the plane's names"
    return {"every": len(every), "reads": len(every - writes), "writes": len(writes)}


def _unwrapped(path: Path) -> str:
    """File text with comment continuations joined, so a wrap cannot hide a claim.

    The sentences below span lines and carry `#:` or `#` markers mid-sentence.
    A pattern applied to the raw text would miss a claim purely because of where
    the author's editor wrapped it -- which is a way for this guard to go quiet
    without anyone changing a word.
    """
    text = path.read_text(encoding="utf-8")
    return re.sub(r"\n\s*#:?\s*", " ", text)


#: `(file, pattern, quantity)`. Each pattern captures the spelled number in one
#: named sentence. All of them must match; see the module docstring.
_BOUND: Final[tuple[tuple[str, str, str], ...]] = (
    ("src/my_pa/bootstrap/settings.py", r"composes all ([a-z-]+) `entities\.` names", "every"),
    ("src/my_pa/bootstrap/settings.py", r"publishes the ([a-z-]+) that read", "reads"),
    ("src/my_pa/bootstrap/settings.py", r"the ([a-z-]+) that write need the switch", "writes"),
    ("src/my_pa/bootstrap/settings.py", r"plane flag publishes ([a-z-]+) reads over", "reads"),
    ("src/my_pa/bootstrap/settings.py", r"prerequisite for all ([a-z-]+) writes", "writes"),
    ("src/my_pa/bootstrap/settings.py", r"write switch gates all ([a-z-]+) Entity", "writes"),
    ("tests/conftest.py", r"the ([a-z-]+) `entities\.` names are", "every"),
    ("tests/conftest.py", r"refuses the plane's ([a-z-]+) writes", "writes"),
    (
        "tests/contract/test_entity_remote_exposure.py",
        r"one of the ([a-z-]+) is mapped to `entity_read`",
        "writes",
    ),
)


@pytest.mark.parametrize(("relative", "pattern", "quantity"), _BOUND)
def test_every_bound_sentence_states_the_count_its_set_derives_to(
    relative: str, pattern: str, quantity: str
) -> None:
    """One derived quantity, against the sentence that claims it."""
    expected = _quantities()[quantity]
    text = _unwrapped(ROOT / relative)
    found = re.findall(pattern, text)
    assert found, (
        f"{relative}: the bound sentence matching {pattern!r} is gone. Either restore "
        "the wording or update this pattern -- an unread claim and an unmatched "
        "pattern look identical from the success path, which is how the defect "
        "this module exists for survived a review."
    )
    for word in found:
        actual = _parse(word)
        assert actual == expected, (
            f"{relative} says {word!r} where the {quantity} set holds {expected} "
            f"(it should read {_spelled(expected)!r}). This is a privacy gate's own "
            "prose: an operator reads it to size the surface a switch opens. "
            "Correct the sentence, not this test."
        )


def test_every_bound_sentence_is_still_there() -> None:
    """Anti-vacuity: every pattern matches something, so a reword cannot silence this."""
    missing = [
        f"{relative}: {pattern}"
        for relative, pattern, _ in _BOUND
        if not re.search(pattern, _unwrapped(ROOT / relative))
    ]
    assert not missing, f"bound sentences that no longer match: {missing}"


def test_the_three_quantities_partition_the_plane() -> None:
    """Reads plus writes is the whole set, so no sentence can be right in isolation.

    The original defect passed every arithmetic check available to a reader
    *because there was none*: 16 and 23 over a set of 54 is visibly wrong the
    moment anything adds it up, and nothing did.
    """
    q = _quantities()
    assert q["reads"] + q["writes"] == q["every"], (
        f"reads {q['reads']} + writes {q['writes']} != {q['every']}"
    )
