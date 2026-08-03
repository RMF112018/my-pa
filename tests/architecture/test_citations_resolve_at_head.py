"""Every citation resolves at head, including the ones that carry no path.

`D-83` wrote the rule: an intra-file citation carries a stable identifier, never
a line number; a line number is used only for a file the change does not modify,
and is verified to resolve at head. **`D-83` was written in prose and broken in
the commit that wrote it** — the same commit gave `D-85` a bare line number for
an external spec, in a register row that names no file, so it points at the
register itself.
That is the third consecutive human sweep this class has survived. A guarantee
that exists only in prose is not a control, so this is the control.

Four rules, and the last two are the ones no `grep` can express:

1. **Every cited path names exactly one file** at head. Resolution is tried
   relative to the citing file, then to the repository root, then as the
   shorthand the corpus actually writes — a path *suffix* such as
   `tables.py` or `providers/identity.py`. Shorthand is admitted **only when it
   is unique**; a suffix matching two files is reported, because a citation a
   reader cannot follow to one file is the defect `D-83` found in `D-78`, where
   two different `09_` documents exist and the row named the wrong one.
2. **Every cited line exists in that file.** A citation past the end of a file
   reads exactly like one that lands.
3. **Every bare `:line` citation has a path in its own block.** A bare citation
   inherits its file from the nearest antecedent path, so a bare citation with
   no antecedent inherits *the file it is written in* — silently, and reading
   perfectly. Rules 1 and 2 cannot see this, because the file it accidentally
   names is long enough for the line to exist.
4. **The inherited path resolves, and the bare line lands inside it.**

**The block, not the paragraph.** A citation's antecedent is searched within one
block: a table row, a list item, a heading, or a run of lines between blank
lines. Anything wider would let a path four bullets away excuse a bare citation
no reader would connect to it, which is the reading that produced the defect —
the plan does name spec files several bullets earlier, about other criteria.
Anything narrower would reject the corpus's normal and correct form, where one
sentence names the file and the next three cite lines in it.

**Named boundaries, so this guard is not described as closing more than it
closes.**

- It decides that a citation *lands*, never that it lands on the right words. No
  mechanical rule can decide that, and a rule that pretended to would be the
  aspirational document one layer down.
- **A line number into a file this repository edits can still rot without
  reddening here**, as long as the file stays long enough. This guard shortens
  that window rather than closing it; `D-83`'s form rule — inside a file, cite
  the heading or the row id — is what closes it, and rule 3 is the mechanical
  half of that rule.

  **This is not hypothetical and the size of it is written down rather than
  left as a caveat.** Measured at `862846e`, over every citation pointing into a
  file this branch modified: **ten pointers had moved, across five files**, and
  all four rules above were green on every one of them, because each cited line
  still existed. Three of the ten were written *by this branch* and were wrong
  the day they shipped — one of them in a guard module, citing four lines of a
  test file that grew past them before the branch ended. What closes the class
  is form, not arithmetic: **cite the function, test, or constant by name
  whenever the target is a file the change touches**, which `D-83` now states.
  A rule that compared the cited line's *text* to the claim about it is the
  thing that would redden here, and it is a different parse from the four above
  — it would need to know what the sentence asserts, which is why this guard
  does not attempt it and says so instead of implying totality.
- `docs/specs/canonical-product-definition/` and `docs/specs/quick-capture/` are
  byte-faithful mirrors of external packages (`D-44`), so citations *written
  inside* them are not this repository's to correct and are not read. Citations
  *into* them from repository prose are checked like any other, and they are the
  one family of target whose line numbers cannot rot, because the mirror is
  frozen.
- A citation with no line number is not read at all; this guard is about line
  numbers. `tests/architecture/test_limitations_cite_evidence.py` and
  `tests/architecture/test_runbook_commands_name_real_paths.py` cover path
  existence in their own universes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Top-level directories holding repository-authored prose.
SEARCHED_ROOTS = ("apps", "docs", "migrations", "ops", "src", "tests")

#: Repository-root files that carry citations.
SEARCHED_ROOT_FILES = ("AGENTS.md", "CONTRIBUTING.md", "README.md", "SECURITY.md")

#: Mirrored external packages. Byte-faithful under `D-44`, so a citation inside
#: one of them cannot be corrected here without breaking the mirror.
MIRRORED = (
    ROOT / "docs" / "specs" / "canonical-product-definition",
    ROOT / "docs" / "specs" / "quick-capture",
)

#: Directories that hold no authored prose, and the virtual environment, which
#: would otherwise put thousands of third-party modules into the shorthand index
#: and make a unique suffix ambiguous for reasons no author could see.
SKIPPED_DIRECTORIES = frozenset(
    {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__", "node_modules"}
)

#: File suffixes a citation may name. Closed, because it is what separates a
#: citation from a host and port, a clock time, and the numeric shorthand the
#: corpus also uses for spec documents.
CITED_SUFFIXES = ("cfg", "ini", "json", "md", "py", "sql", "toml", "txt", "yaml", "yml")

_SUFFIX_ALTERNATION = "|".join(CITED_SUFFIXES)
_PATH = rf"[\w./-]*[\w-]\.(?:{_SUFFIX_ALTERNATION})"

#: A path and a line, written with a colon between them.
_EXPLICIT = re.compile(rf"^(?P<path>{_PATH}):(?P<start>\d+)(?:-(?P<end>\d+))?$")

#: A path with no line number: the antecedent form.
_PATH_ONLY = re.compile(rf"^{_PATH}$")

#: A line number with no path at all.
_BARE = re.compile(r"^:(?P<start>\d+)(?:-(?P<end>\d+))?$")

#: Citations are written in backticks throughout the corpus.
_BACKTICKED = re.compile(r"`([^`\n]+)`")

#: A markdown list item opens a new block.
_LIST_ITEM = re.compile(r"^(?:[-*+]\s|\d+[.)]\s)")

#: A markdown heading opens a new block. Applied to `.md` only: `#` opens a
#: comment in Python, and treating each comment line as its own block would
#: sever a bare citation from the path named on the line above it.
_HEADING = re.compile(r"^#{1,6}\s")

#: The fewest citations of each kind before this guard is deciding anything. A
#: sweep whose extractor silently returned nothing would satisfy every rule.
#:
#: Measured at this head over 327 files: **51 explicit and 9 bare, 60 in all**.
#: The reviewer's universe was 58 real citations with 14 defective, and neither
#: number is reproduced exactly here, which is expected — a universe is a
#: definition, and this one is written down in the four rules below rather than
#: carried in a head count. The floors are set well under the measurement so
#: that removing a citation does not redden the guard, and well over zero so
#: that losing the extractor does.
FEWEST_EXPLICIT = 35
FEWEST_BARE = 5


def _cite(path: str, lines: str) -> str:
    """Assemble a citation-shaped token.

    Every plant below is built through this rather than written as a literal,
    because this module is inside its own universe and a literal plant would be
    read as a real citation. The guard checking its own docstring is the point:
    a rule that exempted itself would be the one file in the repository where a
    rotten citation could not be caught.
    """
    return f"`{path}:{lines}`"


@dataclass(frozen=True)
class Citation:
    """One citation, and the path it inherits if it carries none of its own."""

    source: Path
    line: int
    token: str
    antecedent: str | None

    @property
    def where(self) -> str:
        return f"{self.source.relative_to(ROOT)}:{self.line} `{self.token}`"


def _repository_files() -> list[Path]:
    """Every file the shorthand index may resolve to."""
    found: list[Path] = []
    for path in ROOT.rglob("*"):
        if SKIPPED_DIRECTORIES & set(path.parts):
            continue
        if path.is_file():
            found.append(path)
    return found


REPOSITORY_FILES = _repository_files()


def searched_files() -> list[Path]:
    """Every repository-authored `.md` and `.py` file, mirrors excluded."""
    found: list[Path] = []
    for name in SEARCHED_ROOT_FILES:
        candidate = ROOT / name
        if candidate.is_file():
            found.append(candidate)
    for path in REPOSITORY_FILES:
        if path.suffix not in (".md", ".py"):
            continue
        if not any(path.is_relative_to(ROOT / root) for root in SEARCHED_ROOTS):
            continue
        if any(path.is_relative_to(mirror) for mirror in MIRRORED):
            continue
        found.append(path)
    return sorted(set(found))


def _block_ids(text: str, markdown: bool) -> list[int]:
    """One block identifier per line, `-1` for a blank line.

    A block is a table row, a list item, a heading, or a run of lines between
    blank lines. It is the scope in which a bare citation may find its path.
    """
    ids: list[int] = []
    block = 0
    previous_blank = True
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            ids.append(-1)
            previous_blank = True
            continue
        opens = (
            previous_blank
            or stripped.startswith("|")
            or bool(_LIST_ITEM.match(stripped))
            or (markdown and bool(_HEADING.match(stripped)))
        )
        if opens:
            block += 1
        ids.append(block)
        previous_blank = False
    return ids


def citations(source: Path) -> tuple[list[Citation], list[Citation]]:
    """Every explicit and every bare citation in `source`, in reading order.

    Each bare citation carries the last path token seen **earlier in its own
    block**, which is the antecedent a reader would resolve it against.
    """
    text = source.read_text(encoding="utf-8")
    blocks = _block_ids(text, markdown=source.suffix == ".md")
    explicit: list[Citation] = []
    bare: list[Citation] = []
    antecedent: str | None = None
    current_block = -1

    for lineno, line in enumerate(text.splitlines(), 1):
        block = blocks[lineno - 1]
        if block != current_block:
            current_block = block
            antecedent = None
        for token in _BACKTICKED.findall(line):
            match = _EXPLICIT.match(token)
            if match is not None:
                explicit.append(Citation(source, lineno, token, match["path"]))
                antecedent = match["path"]
                continue
            if _PATH_ONLY.match(token):
                antecedent = token
                continue
            if _BARE.match(token):
                bare.append(Citation(source, lineno, token, antecedent))
    return explicit, bare


def resolve(citing: Path, path: str) -> tuple[Path | None, str]:
    """The file `path` names, and why it resolved or did not.

    Three forms, all live in this corpus: relative to the citing file
    (`docs/plans/` writes `../specs/…`), relative to the repository root (`src/`
    writes `docs/specs/…`), and the path-suffix shorthand (`tables.py`,
    `providers/identity.py`). The shorthand resolves only when exactly one file
    ends with it — two matches means a reader cannot follow it, which is the
    ambiguity `D-83` found sitting under `D-78`.
    """
    for candidate in (citing.parent / path, ROOT / path):
        try:
            resolved = candidate.resolve()
        except OSError:  # pragma: no cover - defensive
            continue
        if resolved.is_file():
            return resolved, "exact"

    suffix = f"/{path}"
    matches = sorted(
        found for found in REPOSITORY_FILES if str(found.relative_to(ROOT)).endswith(suffix)
    )
    if len(matches) == 1:
        return matches[0], "shorthand"
    if len(matches) > 1:
        return None, "ambiguous: " + ", ".join(str(m.relative_to(ROOT)) for m in matches)
    return None, "no such file"


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def last_line(token: str) -> int:
    match = _EXPLICIT.match(token) or _BARE.match(token)
    assert match is not None, token
    return int(match["end"] or match["start"])


def _all_citations() -> tuple[list[Citation], list[Citation]]:
    explicit: list[Citation] = []
    bare: list[Citation] = []
    for source in searched_files():
        found_explicit, found_bare = citations(source)
        explicit.extend(found_explicit)
        bare.extend(found_bare)
    return explicit, bare


EXPLICIT, BARE = _all_citations()


def test_the_sweep_found_citations_of_both_kinds() -> None:
    """Guard the extractor: every rule below is an emptiness test over its parse."""
    assert len(EXPLICIT) >= FEWEST_EXPLICIT, f"only {len(EXPLICIT)} explicit citations parsed"
    assert len(BARE) >= FEWEST_BARE, f"only {len(BARE)} bare citations parsed"


def test_every_cited_path_names_exactly_one_file() -> None:
    unresolved: list[str] = []
    for citation in EXPLICIT:
        assert citation.antecedent is not None
        target, why = resolve(citation.source, citation.antecedent)
        if target is None:
            unresolved.append(f"{citation.where} -> {citation.antecedent} ({why})")
    assert not unresolved, (
        f"{len(unresolved)} citation(s) name no file, or name two, at head; a citation "
        f"a reader cannot follow to one file is a claim about nothing: {unresolved}"
    )


def test_every_cited_line_lands_inside_the_file_it_names() -> None:
    beyond: list[str] = []
    for citation in EXPLICIT:
        assert citation.antecedent is not None
        target, _ = resolve(citation.source, citation.antecedent)
        if target is None:
            continue  # reported by the rule above
        length = line_count(target)
        if last_line(citation.token) > length:
            beyond.append(
                f"{citation.where} lands past the end of {citation.antecedent} ({length})"
            )
    assert not beyond, (
        f"{len(beyond)} citation(s) point past the end of the file they name; a citation "
        f"that rotted reads exactly like one that did not: {beyond}"
    )


def test_every_bare_citation_has_a_path_in_its_own_block() -> None:
    """`D-83`'s rule as a control rather than as prose.

    A bare citation with no antecedent does not fail to resolve — it resolves to
    the file it is written in, which is why three sweeps read past it.
    """
    orphaned = sorted(citation.where for citation in BARE if citation.antecedent is None)
    assert not orphaned, (
        f"{len(orphaned)} bare citation(s) name no file in their own block, so each "
        "silently cites the file it is written in; name the file, or use the section "
        f"heading or row id `D-83` requires: {orphaned}"
    )


def test_every_bare_citation_resolves_through_its_antecedent() -> None:
    unresolved: list[str] = []
    for citation in BARE:
        if citation.antecedent is None:
            continue  # reported by the rule above
        target, why = resolve(citation.source, citation.antecedent)
        if target is None:
            unresolved.append(f"{citation.where} inherits {citation.antecedent} ({why})")
            continue
        length = line_count(target)
        if last_line(citation.token) > length:
            unresolved.append(
                f"{citation.where} inherits {citation.antecedent} and lands past its end ({length})"
            )
    assert not unresolved, (
        f"{len(unresolved)} bare citation(s) do not resolve through the path nearest "
        f"them: {unresolved}"
    )


# ---- the plants ---------------------------------------------------------------


def _plant(tmp_path: Path, body: str) -> Path:
    planted = tmp_path / "planted.md"
    planted.write_text(body, encoding="utf-8")
    return planted


def test_a_citation_past_the_end_of_a_real_file_is_reported(tmp_path: Path) -> None:
    """The first plant the brief requires, and its green half in the same test.

    `AGENTS.md` is real and shorter than the planted line, so the citation names
    a file that exists and still cannot land. The green half — a line inside the
    same file — is what says this rule is not simply refusing every citation
    into that file.
    """
    length = line_count(ROOT / "AGENTS.md")
    planted = _plant(
        tmp_path,
        f"Beyond: {_cite('AGENTS.md', str(length + 1))}. Inside: {_cite('AGENTS.md', '1')}.\n",
    )

    explicit, _ = citations(planted)
    assert len(explicit) == 2, explicit
    assert resolve(planted, "AGENTS.md")[0] is not None
    assert last_line(explicit[0].token) > length
    assert last_line(explicit[1].token) <= length


def test_a_citation_to_a_path_that_does_not_exist_is_reported(tmp_path: Path) -> None:
    """The second plant the brief requires, with its green half."""
    gone = "docs/plans/no-such-plan.md"
    planted = _plant(tmp_path, f"Gone: {_cite(gone, '3')}. Real: {_cite('AGENTS.md', '3')}.\n")

    explicit, _ = citations(planted)
    assert len(explicit) == 2, explicit
    assert resolve(planted, gone) == (None, "no such file")
    assert resolve(planted, "AGENTS.md")[0] is not None


def test_a_shorthand_matching_two_files_is_reported_and_a_unique_one_is_not() -> None:
    """The third failure shape, planted against the real tree rather than a fixture.

    `__init__.py` is the shorthand every package in `src/` matches, so it is the
    ambiguity a reader cannot resolve; `AGENTS.md` is unique. Both halves are
    asserted because a rule that rejected all shorthand would reject the form
    most of this corpus is written in.
    """
    target, why = resolve(ROOT / "README.md", "__init__.py")
    assert target is None and why.startswith("ambiguous: "), why

    unique, how = resolve(ROOT / "README.md", "AGENTS.md")
    assert unique == ROOT / "AGENTS.md" and how == "exact", how


def test_a_bare_citation_with_no_path_in_its_block_is_reported(tmp_path: Path) -> None:
    """The defect that survived three sweeps, in the two shapes it took.

    The first row is the shape that shipped: a bare citation in a register row
    whose row names no file. The second is the corpus's correct and common form
    and must stay green, or this rule would forbid the shorthand the documents
    are written in.
    """
    planted = _plant(
        tmp_path,
        "| D-85 | Spec `" + ":208` reads something else entirely |\n"
        "| D-82 | Verified at " + _cite("AGENTS.md", "1") + " and `" + ":2` |\n",
    )

    _, bare = citations(planted)
    assert [(citation.token, citation.antecedent) for citation in bare] == [
        (":208", None),
        (":2", "AGENTS.md"),
    ]


def test_a_path_four_bullets_away_does_not_excuse_a_bare_citation(tmp_path: Path) -> None:
    """Block scope, planted at its boundary.

    A path in an earlier list item is not an antecedent, because no reader
    connects them. Widening the scope to the paragraph is exactly the reading
    that let the defect pass: the plan does name spec files, several bullets
    earlier, about different criteria.
    """
    planted = _plant(
        tmp_path,
        f"- First, measured against {_cite('AGENTS.md', '1')}.\n"
        "- Second, and this one cites `" + ":2` with nothing of its own.\n",
    )

    _, bare = citations(planted)
    assert [(citation.token, citation.antecedent) for citation in bare] == [(":2", None)]


@pytest.mark.parametrize(
    ("token", "is_a_citation"),
    [
        ("docs/plans/mcv-completion-plan.md:208", True),
        ("../specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:47", True),
        ("18:14", False),
        ("127.0.0.1:5433", False),
        ("9c6b4a18ed72", False),
        ("capabilities.get", False),
    ],
    ids=[
        "a root-relative path and line",
        "a relative path and line",
        "the numeric shorthand is not a path",
        "nor is a host and port",
        "nor is a revision identifier",
        "nor is a capability name",
    ],
)
def test_the_classifier_separates_citations_from_the_other_colons(
    tmp_path: Path, token: str, is_a_citation: bool
) -> None:
    """The false-finding end. Every rejected token is live in this corpus."""
    planted = _plant(tmp_path, f"Token: `{token}`.\n")
    explicit, _ = citations(planted)
    assert bool(explicit) is is_a_citation
