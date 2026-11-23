"""ADR numbers are unique, contiguous, indexed once in order, and every citation resolves.

ADR numbers are allocated by hand from `docs/decisions/00_ADR_INDEX.md`, so two
branches can each take the next number and both merge green. These guards make
the collision visible on the second branch's rebase instead of on `main`:

- every ADR file is named `ADR-NNN-<slug>.md`, no number is used twice, and the
  numbers run from 001 without a gap;
- the index has exactly one row per ADR, in ascending order, each linking to
  the file of that number;
- every `ADR-NNN` cited anywhere under `docs/` names an ADR file that exists.

Each rule is one test, so a planted break turns exactly one of them red.
Unmarked: FAST. Reads `docs/` only.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
DOCS: Final = ROOT / "docs"
DECISIONS: Final = DOCS / "decisions"
INDEX: Final = DECISIONS / "00_ADR_INDEX.md"

#: Files in `docs/decisions/` that are not ADRs.
NOT_ADRS: Final = frozenset({"00_ADR_INDEX.md", "README.md"})

_FILE: Final = re.compile(r"^ADR-(\d{3})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
_ROW: Final = re.compile(r"^\| \[ADR-(\d{3})\]\(([^)]+)\) \|")
_CITATION: Final = re.compile(r"\bADR-(\d{3})\b")


def _adr_files() -> list[tuple[int, str]]:
    """(number, file name) for every ADR file; a misnamed file fails here."""
    found: list[tuple[int, str]] = []
    for path in sorted(DECISIONS.iterdir()):
        if path.name in NOT_ADRS:
            continue
        match = _FILE.fullmatch(path.name)
        assert match, f"docs/decisions/{path.name} is not named ADR-NNN-<slug>.md"
        found.append((int(match.group(1)), path.name))
    return found


def test_adr_numbers_are_unique_and_contiguous_from_one() -> None:
    files = _adr_files()
    assert files, "no ADR found"
    counts = Counter(number for number, _ in files)
    duplicated = {
        f"ADR-{number:03d}": sorted(name for n, name in files if n == number)
        for number, count in counts.items()
        if count > 1
    }
    assert not duplicated, f"an ADR number is used more than once: {duplicated}"
    numbers = sorted(counts)
    assert numbers == list(range(1, len(numbers) + 1)), f"ADR numbers have a gap: {numbers}"


def test_the_index_lists_every_adr_once_in_order() -> None:
    rows = [
        (int(match.group(1)), match.group(2))
        for line in INDEX.read_text(encoding="utf-8").splitlines()
        if (match := _ROW.match(line))
    ]
    numbers = [number for number, _ in rows]
    assert numbers == sorted(set(numbers)), f"index rows repeat or are out of order: {numbers}"
    # Names per number: a duplicated number is the uniqueness test's to report.
    by_number: dict[int, set[str]] = {}
    for number, name in _adr_files():
        by_number.setdefault(number, set()).add(name)
    assert set(numbers) == set(by_number), (
        f"indexed {sorted(set(numbers) - set(by_number))} without a file; "
        f"files {sorted(set(by_number) - set(numbers))} not indexed"
    )
    for number, target in rows:
        assert target in by_number[number], f"ADR-{number:03d} row links to {target}"


def test_every_adr_cited_in_docs_exists() -> None:
    existing = {number for number, _ in _adr_files()}
    unresolved: dict[str, list[str]] = {}
    for path in sorted(DOCS.rglob("*.md")):
        cited = {int(n) for n in _CITATION.findall(path.read_text(encoding="utf-8"))}
        for number in sorted(cited - existing):
            unresolved.setdefault(f"ADR-{number:03d}", []).append(path.relative_to(ROOT).as_posix())
    assert not unresolved, f"cited ADRs with no file: {unresolved}"
