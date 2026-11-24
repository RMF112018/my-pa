"""Project-report fixtures are synthetic (WP3P-S2; PULSE-AC-18).

Every file under `tests/fixtures/project_reports/` (CSV fixtures and the
expected-figures JSON) is scanned:

* **always (structural):** no `prj_` identifier outside the synthetic
  `prj_SYNTH...` shape; no `ent_`/`prn_` identifier; none of the real project
  numbers named in `docs/evidence/pulse/README.md` (read from that file, so
  this test never spells one); no token of the real project-number shape (a
  capital letter and 6 digits) in a file or its name;
* **when the environment provides one (denylist):** no term of the file named
  by `MY_PA_PROJECT_REPORTS_FIXTURE_DENYLIST` (one term per line, `#` comments
  and blank lines ignored, case-folded substring match). The denylist is never
  committed: it holds the real display names, folder codes and amounts only
  the Manager may see. A failure names the fixture and the denylist line
  number, never the term.

The planted cases prove each scanner sees what it claims to.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[2]
FIXTURES: Final = ROOT / "tests" / "fixtures" / "project_reports"
EVIDENCE_README: Final = ROOT / "docs" / "evidence" / "pulse" / "README.md"
DENYLIST_ENV: Final = "MY_PA_PROJECT_REPORTS_FIXTURE_DENYLIST"

PRJ: Final = re.compile(r"prj_[A-Za-z0-9]+")
SYNTHETIC_PRJ: Final = re.compile(r"prj_SYNTH[A-Za-z0-9]*")
OTHER_IDS: Final = re.compile(r"\b(?:ent|prn)_[A-Za-z0-9]{4,}")
PROJECT_NUMBER_SHAPE: Final = re.compile(r"(?<![A-Za-z0-9])[A-Z][0-9]{6}(?![0-9])")


def _fixture_files() -> list[Path]:
    return sorted(p for p in FIXTURES.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def _evidence_project_numbers() -> frozenset[str]:
    text = EVIDENCE_README.read_text(encoding="utf-8")
    return frozenset(re.findall(r"`([A-Z][0-9]{6})`", text))


def structural_violations(name: str, text: str, real_numbers: frozenset[str]) -> list[str]:
    found: list[str] = []
    for token in PRJ.findall(text):
        if SYNTHETIC_PRJ.fullmatch(token) is None:
            found.append("non-synthetic prj_ identifier")
    if OTHER_IDS.search(text):
        found.append("ent_/prn_ identifier")
    for haystack, where in ((text, "content"), (name, "name")):
        if any(number in haystack for number in real_numbers):
            found.append(f"real project number in {where}")
        if PROJECT_NUMBER_SHAPE.search(haystack):
            found.append(f"project-number shape in {where}")
    return found


def load_denylist(path: Path) -> list[tuple[int, str]]:
    terms: list[tuple[int, str]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        term = line.strip()
        if term and not term.startswith("#"):
            terms.append((number, term.casefold()))
    return terms


def denylist_violations(name: str, text: str, terms: Sequence[tuple[int, str]]) -> list[int]:
    haystack = f"{name}\n{text}".casefold()
    return [number for number, term in terms if term in haystack]


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")


def test_the_scan_sees_the_fixtures_and_the_evidence_numbers() -> None:
    files = _fixture_files()
    assert len(files) >= 40
    assert {p.suffix for p in files} == {".csv", ".json"}
    assert (FIXTURES / "expected" / "evidence_aggregate_v1.json") in files
    assert len(_evidence_project_numbers()) == 3


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: str(p.relative_to(FIXTURES)))
def test_every_fixture_is_structurally_synthetic(path: Path) -> None:
    relative = str(path.relative_to(FIXTURES))
    assert structural_violations(relative, _text(path), _evidence_project_numbers()) == []


def test_no_fixture_holds_a_denylisted_term() -> None:
    configured = os.environ.get(DENYLIST_ENV)
    if not configured:
        pytest.skip(f"{DENYLIST_ENV} is not set (the denylist is never committed)")
    terms = load_denylist(Path(configured))
    assert terms, "the denylist file has no term"
    hits = {
        str(path.relative_to(FIXTURES)): lines
        for path in _fixture_files()
        if (lines := denylist_violations(path.name, _text(path), terms))
    }
    assert hits == {}, "denylisted terms (by denylist line number) found in fixtures"


# --- planted prove-red controls -------------------------------------------


def test_planted_identifiers_and_numbers_are_caught() -> None:
    real = frozenset({"Q123456"})
    assert structural_violations("a.csv", "prj_SYNTHabc ok", real) == []
    assert structural_violations("a.csv", "x,prj_01HREALID9", real) == [
        "non-synthetic prj_ identifier"
    ]
    assert structural_violations("a.csv", "ent_01ABCDEF", real) == ["ent_/prn_ identifier"]
    assert "real project number in content" in structural_violations("a.csv", "Q123456", real)
    assert structural_violations("a.csv", "code R654321.01", real) == [
        "project-number shape in content"
    ]
    assert structural_violations("X765432-buyout.csv", "", real) == ["project-number shape in name"]
    assert structural_violations("a.csv", "SYN-0001.01-100 and 20261105", real) == []


def test_a_planted_denylist_term_is_caught_without_printing_it(tmp_path: Path) -> None:
    denylist = tmp_path / "deny.txt"
    denylist.write_text("# comment\n\nSecret Vendor\n$9,876.54\n", encoding="utf-8")
    terms = load_denylist(denylist)
    assert [number for number, _ in terms] == [3, 4]
    assert denylist_violations("a.csv", "x,SECRET vendor,y", terms) == [3]
    assert denylist_violations("a.csv", "($9,876.54)", terms) == [4]
    assert denylist_violations("secret vendor.csv", "", terms) == [3]
    assert denylist_violations("a.csv", "Synthetic Vendor A", terms) == []
