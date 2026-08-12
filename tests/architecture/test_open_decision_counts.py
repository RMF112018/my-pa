"""Section 14's open-decision counts are derived, not asserted.

`docs/plans/mcv-completion-plan.md` section 14 opens with a paragraph stating how
many operator decisions are open, how many block a work package, and how they
split across the three ledgers. Those figures were hand-maintained and went
stale: the paragraph claimed forty-one open and sixteen blocking while the tables
beneath it held forty-six distinct IDs, twenty-eight of them blocking. Correcting
the numbers alone would have left the same defect in place for the next reader,
because nothing connected the prose to the tables.

This test is that connection. It recomputes every figure from the tables and
fails when the paragraph disagrees with them, so the count cannot drift again
without something going red. It also enforces that no ID appears in two tables,
since an ID counted twice would inflate the total while every individual row
still looked correct.

Scope note: `D-nn` plan-register IDs, the canonical package's `OP-nn` and
`CR-D-nnn`, the connector's `MCP-OP-nnn`, and Native Apple Reminders'
`NAR-OP-nnn`, and Apple Mail, Calendar & Contacts' `NAPDCB-OP-nnn` are
deliberately excluded. Section 14 tracks three ledgers — Phase 00, Quick Capture,
and Relationship Intelligence — and folding another package's internal decisions
into its totals would misstate what the plan is accountable for. The exclusion is
mechanical rather than maintained: `LEDGER_ID` cannot match any of those families,
so a new one arriving in the plan's prose cannot silently join the counts.
`NAR-OP-nnn` and `NAPDCB-OP-nnn` are named here because section 14 asserts the
package families are excluded on the same grounds, and a claim the plan makes
about this test's scope should be readable in this test's scope note.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs" / "plans" / "mcv-completion-plan.md"
README = ROOT / "README.md"
SOURCE_INDEX = ROOT / "docs" / "00_REPOSITORY_SOURCE_INDEX.md"
CANONICAL_LEDGER = (
    ROOT / "docs" / "specs" / "canonical-product-definition" / "15_OPEN_OPERATOR_DECISIONS.md"
)

#: The three ledgers section 14 tracks. Ordered so the longer prefixes match
#: first: `O-\d{2}` must not be tried against the `OD-004` inside `P00-OD-004`.
LEDGER_ID = re.compile(r"\b(?:P00-OD-\d{3}|RI-OD-\d{3}|O-\d{2})\b")
PACKAGE_ID = re.compile(r"^(?P<family>OP|MCP-OP|NAR-OP|NAPDCB-OP)-(?P<number>\d{2,3})$")

#: Headings that open each of section 14's three groups.
BLOCKING_HEADING = "### Blocking — "
RESERVED_HEADING = "### Blocking, and reserved"
NOT_BLOCKING_HEADING = "### Not blocking"

#: Any *other* heading closes whichever group is open, and that is what ends the
#: scan. This was the literal `"### Five questions"` until 2026-08-08, which made
#: this guard's own terminator a spelled count of a set that grows. Adding a
#: sixth question renamed that heading, the scan ran past it, and the ledger
#: tables in the following subsections were swept into `not_blocking`. Measured
#: when it happened: `not_blocking` derived **24** against a stated **19**, and
#: `test_no_decision_appears_in_two_groups` failed too, because IDs past the
#: boundary already appear in the groups above. So the guard did not report "the
#: heading moved" — it reported a wrong number and a spurious duplicate, which is
#: the failure mode a reader is least likely to diagnose correctly. A guard whose
#: purpose is to stop a stale count should not itself be keyed to one. Taking the
#: boundary from the document's structure removes the coupling: renaming a
#: heading, inserting a subsection, or reordering them can no longer widen the
#: sweep, and no edit to this file is needed when the question list next grows.
HEADING = re.compile(r"^#{1,6} ")

_UNITS = [
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
]
_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty"}


def _number_words(limit: int = 69) -> dict[str, int]:
    """Map English number words to integers, for 0 through ``limit``.

    Built rather than listed so that a *readable but wrong* figure fails on the
    count comparison, which is the failure this test exists to catch. A
    hand-listed map would instead reject the wrong number as unparseable, which
    passes for a failure but proves the comparison never ran.
    """
    words = {word: value for value, word in enumerate(_UNITS)}
    for base, tens_word in _TENS.items():
        if base > limit:
            continue
        words[tens_word] = base
        for unit in range(1, 10):
            if base + unit <= limit:
                words[f"{tens_word}-{_UNITS[unit]}"] = base + unit
    return words


NUMBER_WORDS = _number_words()


def _ledger_of(decision_id: str) -> str:
    if decision_id.startswith("P00-OD-"):
        return "phase00"
    if decision_id.startswith("RI-OD-"):
        return "relationship_intelligence"
    return "quick_capture"


def _section_14_groups() -> dict[str, list[str]]:
    """Extract the decision IDs in each of section 14's three groups.

    The first two groups are tables whose first column is the ID; the third is
    prose. Both forms are read, because the plan uses whichever fits.
    """
    lines = PLAN.read_text(encoding="utf-8").splitlines()
    groups: dict[str, list[str]] = {"blocking": [], "reserved": [], "not_blocking": []}
    current: str | None = None

    for line in lines:
        if line.startswith(BLOCKING_HEADING):
            current = "blocking"
            continue
        if line.startswith(RESERVED_HEADING):
            current = "reserved"
            continue
        if line.startswith(NOT_BLOCKING_HEADING):
            current = "not_blocking"
            continue
        # Checked after the three above so a group heading opens its group
        # rather than closing the previous one.
        if HEADING.match(line):
            current = None
            continue
        if current is None:
            continue

        if current == "not_blocking":
            groups[current].extend(LEDGER_ID.findall(line))
            continue

        # Table row: take the ID from the first column only, so an ID mentioned
        # in a "Blocks" or "Question" cell is not counted as its own row.
        if line.startswith("|") and not line.startswith(("|---", "| ID")):
            cells = [cell.strip().strip("`") for cell in line.split("|")[1:-1]]
            if cells and LEDGER_ID.fullmatch(cells[0]):
                groups[current].append(cells[0])

    return groups


def _stated_numbers() -> dict[str, int]:
    """Read the figures the section 14 paragraph states in words."""
    text = PLAN.read_text(encoding="utf-8")
    match = re.search(
        r"(?P<total>[A-Za-z-]+) decisions are open: (?P<phase00>[a-z-]+) from the\s+"
        r"Phase 00 ledger, (?P<qc>[a-z-]+) from Quick\s+Capture, and (?P<ri>[a-z-]+) "
        r"from Relationship Intelligence\.\s+(?P<blocking>[A-Za-z-]+) of them block\s+"
        r"a work package in section 12 — (?P<blocking_ordinary>[a-z-]+) on ordinary "
        r"grounds and (?P<blocking_reserved>[a-z-]+) more that\s+are reserved to the "
        r"operator by policy and block for that reason\. The remaining\s+"
        r"(?P<not_blocking>[a-z-]+) do not block",
        text,
    )
    assert match is not None, (
        "Section 14's opening paragraph no longer matches the shape this test "
        "reads. Update the test and the paragraph together."
    )
    stated: dict[str, int] = {}
    for key, value in match.groupdict().items():
        word = value.lower()
        assert word in NUMBER_WORDS, (
            f"Section 14 states '{value}' for '{key}', which this test cannot read. "
            f"Add it to NUMBER_WORDS. Known words: {sorted(NUMBER_WORDS)}."
        )
        stated[key] = NUMBER_WORDS[word]
    return stated


def test_no_decision_appears_in_two_groups() -> None:
    groups = _section_14_groups()
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for group, ids in groups.items():
        for decision_id in ids:
            if decision_id in seen:
                duplicates.append(f"{decision_id} in both {seen[decision_id]} and {group}")
            seen[decision_id] = group
    assert not duplicates, (
        "An open decision is listed in more than one section 14 group, which "
        f"would double-count it in the totals: {duplicates}"
    )


def test_no_group_is_empty() -> None:
    """Guard the parser itself.

    Every count below would agree trivially if the extraction silently returned
    nothing, so an empty group is treated as a parser failure rather than as a
    section with no decisions in it.
    """
    groups = _section_14_groups()
    empty = [name for name, ids in groups.items() if not ids]
    assert not empty, f"Section 14 groups parsed as empty, so the parser is broken: {empty}"


@pytest.mark.parametrize(
    ("stated_key", "group_keys"),
    [
        ("blocking_ordinary", ("blocking",)),
        ("blocking_reserved", ("reserved",)),
        ("blocking", ("blocking", "reserved")),
        ("not_blocking", ("not_blocking",)),
        ("total", ("blocking", "reserved", "not_blocking")),
    ],
)
def test_stated_count_matches_tables(stated_key: str, group_keys: tuple[str, ...]) -> None:
    groups = _section_14_groups()
    derived = len({d for key in group_keys for d in groups[key]})
    stated = _stated_numbers()[stated_key]
    assert stated == derived, (
        f"Section 14 states {stated} for '{stated_key}' but its tables contain "
        f"{derived}. Recompute the paragraph from the tables rather than editing "
        "this test."
    )


@pytest.mark.parametrize(
    ("stated_key", "ledger"),
    [
        ("phase00", "phase00"),
        ("qc", "quick_capture"),
        ("ri", "relationship_intelligence"),
    ],
)
def test_stated_ledger_split_matches_tables(stated_key: str, ledger: str) -> None:
    groups = _section_14_groups()
    everything = {d for ids in groups.values() for d in ids}
    derived = sum(1 for d in everything if _ledger_of(d) == ledger)
    stated = _stated_numbers()[stated_key]
    assert stated == derived, (
        f"Section 14 states {stated} decisions from the {ledger} ledger but its "
        f"tables contain {derived}."
    )


def _canonical_package_families() -> dict[str, list[tuple[str, int]]]:
    families: dict[str, list[tuple[str, int]]] = {}
    for line in CANONICAL_LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith(("|---", "| ID")):
            continue
        decision_id = line.split("|", 2)[1].strip().strip("`")
        match = PACKAGE_ID.fullmatch(decision_id)
        if match is None:
            continue
        families.setdefault(match["family"], []).append((decision_id, int(match["number"])))
    return families


def test_canonical_package_decision_counts_and_ranges_are_derived() -> None:
    families = _canonical_package_families()
    assert set(families) == {"OP", "MCP-OP", "NAR-OP", "NAPDCB-OP"}

    ranges: dict[str, str] = {}
    counts: dict[str, int] = {}
    for family, rows in families.items():
        ids = [decision_id for decision_id, _number in rows]
        numbers = [number for _decision_id, number in rows]
        assert len(ids) == len(set(ids)), f"duplicate {family} decision ID"
        assert numbers == list(range(1, max(numbers) + 1)), (
            f"{family} decisions are not a contiguous range from 1: {numbers}"
        )
        counts[family] = len(numbers)
        ranges[family] = f"`{ids[0]}` through `{ids[-1]}`"

    total = sum(counts.values())
    readme = " ".join(README.read_text(encoding="utf-8").split())
    source_index = SOURCE_INDEX.read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")

    assert f"The {total} operator decisions" in readme
    for family, count in counts.items():
        assert f"{count} `{family}`" in readme
        assert ranges[family] in source_index
        assert ranges[family] in plan
    assert f"own {total} operator decisions" in source_index
    assert plan.count(f"{total} operator decisions") >= 2
    assert f"counts exclude all {total}" in plan
