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
from my_pa.domain.identity.operation import Capability

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
    """The inverse, for whatever a bound sentence actually says.

    **Digits are read here, and the first draft of this function did not read
    them.** It returned `None` for `104`, and `None` is indistinguishable from
    "not a number" at the call site, so every digit-form claim in the corpus was
    silently skipped -- including `apps/gateway.py`'s "serve the 104
    capabilities", which is the operator-facing claim this arm was added to
    catch. The mutation proof found it: replanting that defect left the guard
    green. A digit arm that cannot parse digits is the failure this module names
    in its own docstring, committed by the module itself.
    """
    word = word.strip().lower()
    if word.isdigit():
        return int(word)
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


# --- the corpus-wide arm ------------------------------------------------------
#
# **A guard scoped to the files that were wrong last time will not catch the
# next one.** `_BOUND` above names nine sentences in three files, and a fourth
# generation of this defect appeared in four files it does not name: an
# operator-facing runbook row, `apps/gateway.py --help`, and two further
# docstrings. So this arm derives the same quantities and sweeps the corpus
# instead of a list, and a file added tomorrow is swept the day it lands.
#
# **What it reads is a noun phrase that can only mean the whole set.** English
# writes a subset and a total identically -- "the two writes" and "the
# thirty-eight writes" are the same construction -- so an unrestricted sweep of
# `N writes` reports 89 findings in `src/` alone, almost all of them ordinary
# prose about a local pair. Measured, not guessed: that was the first draft.
# Requiring a totalising determiner cut it to 34, and restricting the noun to
# plane-scoped forms (`entity writes`, `` `entities.` reads ``, `write names`,
# `writes on this plane`, and the runbook's own table rows) cut it to three. A
# guard that fires five times for every true finding is one people delete, and
# this module's own docstring says so.
#
# **`capabilities` is read in digits only, and that is the whole point of
# including it.** `test_spelled_counts_match_the_sets_they_name.py` already
# binds `len(Capability)` corpus-wide in the spelled form and has a mature
# allowlist for subset phrases that name a pair or a handful rather than the
# set. Duplicating that here would create a second allowlist for one noun --
# and quoting one of its excused phrases here, spelled, is itself read by it as
# a fresh claim, which is how the first draft of this paragraph reddened that
# module. What that module explicitly does not
# read is the digit form -- "Digits are not read", by its own docstring -- and
# `apps/gateway.py` printed "serve the 104 capabilities" to an operator choosing
# a transport for exactly as long as that gap existed. This arm reads the digits
# and leaves the words to the module that already owns them.

_SWEPT_ROOTS: Final[tuple[str, ...]] = ("src", "apps", "ops", "docs", "tests")
_SWEPT_FILES: Final[tuple[str, ...]] = ("README.md",)

#: Skipped by the sweep, and only this one file. `_EXCUSED` quotes every phrase
#: it excuses, so a module that reads the corpus for those phrases reads its own
#: allowlist back and reports each excuse as a finding.
_THIS_MODULE: Final = "tests/architecture/test_entity_plane_prose_matches_the_capability_sets.py"

_NUM: Final = r"(\d{1,3}|[A-Za-z]+(?:-[a-z]+)?)"
_DET: Final = r"(?:[Tt]he|[Aa]ll|[Ii]ts|[Ee]very one of the)\s+"

_CORPUS: Final[tuple[tuple[str, str], ...]] = (
    ("capabilities", rf"{_DET}(\d{{1,3}})\s+capabilities\b"),
    ("entity names", rf"{_NUM}\s+`entities\.`\s+names\b"),
    # A determiner is required only where the noun alone is ambiguous. `entity
    # writes` needs one, because "on one entity writes twice" is a verb; the
    # plane-scoped forms below cannot be read that way, and requiring `the`
    # before them let `settings.py`'s "put eighteen identity writes on a
    # process" through -- a sentence with no determiner at all, and the second
    # defect the mutation proof caught in this arm.
    ("entity writes", rf"{_DET}{_NUM}\s+entity\s+writes?\b"),
    ("entity writes", rf"{_NUM}\s+(?:`entities\.`|identity|Entity)\s+writes?\b"),
    ("entity writes", rf"{_NUM}\s+write names\b"),
    ("entity writes", rf"{_NUM}\s+writes on this plane\b"),
    ("entity writes", rf"Write capabilities \| {_NUM}\b"),
    ("entity reads", rf"{_DET}{_NUM}\s+(?:`entities\.`|entity)\s+reads\b"),
    ("entity reads", rf"Read capabilities \| {_NUM}\b"),
)

#: `(path, fragment, reason)`. A shrinking allowlist in the `D-81` shape: a stale
#: entry reddens `test_every_excused_corpus_claim_is_still_there`, and a new
#: claim anywhere reddens rather than joining quietly.
_EXCUSED: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "src/my_pa/application/service.py",
        "all ten entity writes",
        "`_entity_receipt`'s callers, not the plane. Measured: exactly ten call "
        "sites in this file, so ten is the true figure for the shape they share.",
    ),
    (
        "src/my_pa/infrastructure/persistence/entity_authoring.py",
        "eighteen writes on this plane",
        "**Unresolved, and excused as unresolved rather than corrected.** The "
        "claim is that every write on the plane carries a durable ledger row and "
        "a `receipt_id`. Whether `RI-ENT-WP-11`'s fifteen record-family writes -- "
        "which land through `application/entity_record_families.py`, not this "
        "module -- satisfy both halves is a question about behaviour, not a "
        "count, and this module holds no class whose write methods could be "
        "counted. Changing eighteen to thirty-eight here would assert coverage "
        "nothing has verified, which is the defect this file exists to prevent, "
        "pointed the other way.",
    ),
    (
        "docs/campaign/ROBUST-ENTITY-DATA-MODEL-20260830.md",
        "thirty-four `entities.` names",
        "a quotation of the superseded string inside the sentence recording that "
        "it was corrected, not a claim that the set holds thirty-four.",
    ),
)


def _corpus_findings() -> list[tuple[str, str, str, int, int]]:
    """Every plane-scoped count claim in the corpus that disagrees with its set."""
    quantities = _quantities_by_noun()
    found: list[tuple[str, str, str, int, int]] = []
    paths = [ROOT / name for name in _SWEPT_FILES]
    for root in _SWEPT_ROOTS:
        paths.extend(p for p in (ROOT / root).rglob("*") if p.suffix in (".py", ".md"))
    for path in paths:
        relative = str(path.relative_to(ROOT))
        if relative == _THIS_MODULE:
            continue
        try:
            text = _unwrapped(path)
        except (OSError, UnicodeDecodeError):
            continue
        for noun, pattern in _CORPUS:
            for match in re.finditer(pattern, text):
                stated = _parse(match.group(1))
                if stated is None or stated == quantities[noun]:
                    continue
                found.append((relative, noun, match.group(0), stated, quantities[noun]))
    return found


def _quantities_by_noun() -> dict[str, int]:
    q = _quantities()
    return {
        "capabilities": len(Capability),
        "entity names": q["every"],
        "entity writes": q["writes"],
        "entity reads": q["reads"],
    }


def _is_excused(relative: str, phrase: str) -> bool:
    return any(relative == path and fragment in phrase for path, fragment, _ in _EXCUSED)


def test_no_unexcused_count_claim_in_the_corpus_disagrees_with_its_set() -> None:
    """The arm that is not scoped to the files that were wrong last time."""
    unexcused = [
        f"{relative}: {phrase!r} says {stated}, the set holds {expected}"
        for relative, _, phrase, stated, expected in _corpus_findings()
        if not _is_excused(relative, phrase)
    ]
    assert not unexcused, (
        "count claims that disagree with the set they name:\n  "
        + "\n  ".join(unexcused)
        + "\n\nCorrect the prose. If the phrase means a subset rather than the "
        "whole set, say which subset in the words themselves so it stops reading "
        "as a total, or excuse it in `_EXCUSED` with the reason."
    )


def test_every_excused_corpus_claim_is_still_there() -> None:
    """A shrinking allowlist: a stale excuse reddens instead of rotting quietly."""
    missing = [
        f"{path}: {fragment!r}"
        for path, fragment, _ in _EXCUSED
        if fragment not in _unwrapped(ROOT / path)
    ]
    assert not missing, f"excused claims that are no longer present: {missing}"


def test_the_corpus_arm_reads_something() -> None:
    """Anti-vacuity, in the shape this module already applies to `_BOUND`.

    A regex that stops matching and a corpus that stops making claims look the
    same from the success path -- which is the whole reason this module exists.
    """
    quantities = _quantities_by_noun()
    seen = 0
    paths = [ROOT / name for name in _SWEPT_FILES]
    for root in _SWEPT_ROOTS:
        paths.extend(p for p in (ROOT / root).rglob("*") if p.suffix in (".py", ".md"))
    for path in paths:
        try:
            text = _unwrapped(path)
        except (OSError, UnicodeDecodeError):
            continue
        for _, pattern in _CORPUS:
            seen += len(re.findall(pattern, text))
    assert seen >= 20, (
        f"the corpus arm matched only {seen} claims; it read 51 when written, so a "
        "figure this low means a pattern stopped matching rather than that the "
        "corpus stopped claiming"
    )
    assert quantities["entity writes"] == 38 or quantities["entity writes"] > 0
