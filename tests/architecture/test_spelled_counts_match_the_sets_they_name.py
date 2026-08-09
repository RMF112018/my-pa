"""A spelled-out count of a derivable set matches what the set derives to.

Three consecutive human-authored sweeps left stale spelled counts standing, and
each survived for a reason worth writing down:

- **The verification grep was case-sensitive.** `grep -rn "eight capabilit"`
  returns four hits; `grep -rni` returns five. That one flag is why a module
  docstring opening `Eight capabilities over a socket` shipped four lines above
  two lines the same commit corrected to `twelve`. Every rule here is
  case-insensitive.
- **The sweep was scoped to `src/`.** `tests/` held eleven more. This reads
  `src/`, `tests/`, `apps/`, `ops/`, and every section of the plan that the
  plan's own line 7 declares to be current state — sections 1 and 3, not
  section 3 alone. **Scoping it to section 3 was itself an instance of the
  defect**: section 1's Alembic row and section 3's said ten revisions and
  eleven at the same head, 48 lines apart, and only the lower one was read.
  A rule that covers the section that motivated it and not its neighbour is
  the shape this campaign keeps catching.
- **The count was written down.** A guard holding a literal `12` is the next
  stale claim, one release later. Every count here is derived: from `Capability`
  and `Purpose` themselves, and from the very `find` commands section 3 names.

**What a claim is.** A spelled number immediately before `capabilities`,
`capability names`, `purposes`, or — inside a block that is already talking about
capabilities — `member`; plus the phrase `closed at <number>`, which is how this
corpus states the capability set's size without naming it. Ordinals are read as
the *next* member: `a ninth capability` asserts the set has eight, and is stale
in exactly the way `eight capabilities` is. The branch that added `capture.*`
corrected one ordinal site and left eight, which is why ordinals are in.

**Named boundaries, so this guard is not described as closing more than it
closes.**

- **The cardinal `one` is not read.** It is an English article throughout this
  corpus — "one capability per invocation", "One purpose the domain permits" —
  and reading it would produce fifteen false findings and no true one. A claim
  that the set holds *one* capability would therefore escape. That is the price,
  and it is named rather than hidden.
- **Digits are not read.** `readiness.implemented 12 of 12` is a transcript, and
  `tests/architecture/test_readme_state_claims.py` derives the README's numeric
  claims already. This guard is about the spelled form, which is the form that
  reads as prose and so gets skimmed.
- **Only two sets are derivable here**, the capability set and the purpose set,
  plus section 3's module counts and revision count. A spelled count of anything
  else — refusals in a parity matrix, sinks in a criterion — is not read, because
  nothing in the tree derives it.
- Claims that are *not* about a set's size are excused **one at a time**, by an
  entry naming the file, the exact phrase, and a distinctive fragment of the
  block it sits in. `EXCUSED` is a shrinking allowlist in the `D-81` shape: a
  stale entry reddens, and a new claim anywhere reddens rather than joining
  quietly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs" / "plans" / "mcv-completion-plan.md"

#: Where a claim may be written. The plan is read too, but only its current-state
#: sections, which are maintained prose; the register below them is a history and
#: its rows say what was true when they were written.
SWEPT_ROOTS = ("apps", "ops", "src", "tests")

#: Swept files that sit under none of those roots. `README.md` states current
#: capability and schema figures in the same prose shapes the roots are read
#: for, and it lives at the repository root, so until this constant existed
#: every count in it was bound to nothing — including one this repository's own
#: package added. A root-relative file list rather than a fifth entry in
#: `SWEPT_ROOTS`, because sweeping `.` would pull in the plan's register and
#: every other document whose rows are history rather than current state.
SWEPT_FILES = ("README.md",)

SKIPPED_DIRECTORIES = frozenset({"__pycache__", ".ruff_cache", ".mypy_cache", ".pytest_cache"})

#: `src/my_pa.egg-info/` is a build artifact, untracked, and holds a stale copy
#: of `README.md`; correcting it would be correcting a file `pip` rewrites.
SKIPPED_SUFFIXES = (".egg-info",)

_UNITS = (
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
_TENS = {
    20: "twenty",
    30: "thirty",
    40: "forty",
    50: "fifty",
    60: "sixty",
    70: "seventy",
    80: "eighty",
    90: "ninety",
}

_ORDINAL_UNITS = (
    "zeroth",
    "first",
    "second",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
    "eleventh",
    "twelfth",
    "thirteenth",
    "fourteenth",
    "fifteenth",
    "sixteenth",
    "seventeenth",
    "eighteenth",
    "nineteenth",
)


def _cardinals(limit: int = 999) -> dict[str, int]:
    """English cardinals, built rather than listed.

    Built, so that a readable but wrong figure fails on the *comparison*. A
    hand-listed map would reject an unexpected word as unparseable, which looks
    like a failure and proves the comparison never ran.

    **The limit was 99 and had to move, and the reason is worth recording.**
    `src/my_pa` crossed a hundred modules in WP-7, and section 3's own derived
    claim then had no spelling this map could read. That did not fail loudly:
    "one hundred and three" contains "three", so the longest-match scan below
    read the claim as **3** and reported the tree as holding 103 against a
    stated 3 — a wrong answer rather than a refusal, which is the shape of
    defect every rule in this module exists to refuse. Hundreds are built the
    same way tens are, so the next boundary announces itself the same way.
    """
    words = {word: value for value, word in enumerate(_UNITS) if value <= limit}
    for base, tens_word in _TENS.items():
        if base > limit:
            continue
        words[tens_word] = base
        for unit in range(1, 10):
            if base + unit <= limit:
                words[f"{tens_word}-{_UNITS[unit]}"] = base + unit
    below_a_hundred = dict(words)
    for hundreds in range(1, 10):
        if hundreds * 100 > limit:
            break
        prefix = f"{_UNITS[hundreds]} hundred"
        words[prefix] = hundreds * 100
        for word, value in below_a_hundred.items():
            if value and hundreds * 100 + value <= limit:
                words[f"{prefix} and {word}"] = hundreds * 100 + value
    return words


CARDINALS = _cardinals()
#: The inverse of `CARDINALS`: the one spelling each value is written with. Used
#: where a test constructs the *correct* sentence to check its own reader against
#: a derived count, so the spelling works past nineteen (a bare `_UNITS[n]` index
#: raised once the Alembic chain crossed twenty).
SPELLED = {value: word for word, value in CARDINALS.items()}
ORDINALS = {word: value for value, word in enumerate(_ORDINAL_UNITS)}

#: The article, not a count. See the boundary note in the module docstring.
UNREAD_CARDINALS = frozenset({"one"})

_READ_CARDINALS = sorted(set(CARDINALS) - UNREAD_CARDINALS, key=len, reverse=True)
_READ_ORDINALS = sorted(set(ORDINALS) - {"zeroth"}, key=len, reverse=True)

_NUMBER = "|".join(re.escape(word) for word in _READ_CARDINALS + _READ_ORDINALS)

#: Adjectives the corpus writes between the number and the noun.
_ADJECTIVE = r"(?:existing|new|public|remaining|other|further|capability)\s+"

#: Nouns that name the set outright, wherever they are written.
NAMED_NOUNS = ("capabilit(?:y|ies)", "purposes?")

#: Nouns that name the set only where the block is already about capabilities.
#: `member`, `name`, `string` and `tool` are all how this corpus refers to a
#: capability without saying the word — "eight names typed out by hand", "none
#: of the eight strings", "a ninth member of it" — and all four are also
#: ordinary English about other things, so context decides.
BORROWED_NOUNS = ("members?", "names?", "strings?", "tools?")

CLAIM = re.compile(
    rf"\b(?P<number>{_NUMBER})[\s-]+(?:{_ADJECTIVE})?"
    rf"(?P<noun>{'|'.join(NAMED_NOUNS + BORROWED_NOUNS)})\b",
    re.IGNORECASE,
)

_BORROWED = re.compile(rf"^(?:{'|'.join(BORROWED_NOUNS)})$", re.IGNORECASE)

#: How this corpus states the capability set's size without naming the noun.
CLOSED_AT = re.compile(rf"\bclosed at (?P<number>{_NUMBER})\b", re.IGNORECASE)

#: The elided form, where the noun is left to the reader: `All eight, addressed
#: by name` and `not one capability, all eight, and for each`. Two conditions,
#: because this shape is the one that would otherwise be a false-finding machine:
#: the block must already be about capabilities, and the phrase must **end** —
#: comma or full stop. `all three call it` and `all three transports` carry
#: their own subject and are not elided; `all eight,` has nothing after it but
#: the set the sentence has been discussing. The corpus says `all three` eleven
#: times, always about the three transports, and every one of them continues.
ALL_OF = re.compile(rf"\ball (?P<number>{_NUMBER})(?=[,.])", re.IGNORECASE)

#: A borrowed noun is read only where the block is already about capabilities,
#: because five enums in `src/` are described as having "one member" or gaining
#: "a second member" and none of them is the capability set.
_MEMBER_NEEDS = re.compile(r"capabilit", re.IGNORECASE)


def capability_count() -> int:
    return len(Capability)


def purpose_count() -> int:
    return len(Purpose)


def source_modules() -> int:
    """Section 3's own command: `find src/my_pa -name "*.py"`."""
    return len(list((ROOT / "src" / "my_pa").rglob("*.py")))


def counted_test_modules() -> int:
    """Section 3's own command: `find tests -name "test_*.py"`."""
    return len(list((ROOT / "tests").rglob("test_*.py")))


def revision_files() -> list[Path]:
    return sorted((ROOT / "migrations" / "versions").glob("*.py"))


def alembic_head() -> str:
    """The revision no other revision names as its `down_revision`.

    Derived rather than read from a document, for the same reason every count
    here is: the head moves whenever a revision is added, and a written head is
    a claim with a shelf life.
    """
    revisions: dict[str, str | None] = {}
    identifier = re.compile(r"^revision: str = \"(?P<id>[0-9a-f]+)\"", re.MULTILINE)
    parent = re.compile(r"^down_revision: str \| None = \"(?P<id>[0-9a-f]+)\"", re.MULTILINE)
    for path in revision_files():
        text = path.read_text(encoding="utf-8")
        found = identifier.search(text)
        if found is None:
            continue
        below = parent.search(text)
        revisions[found["id"]] = below["id"] if below else None
    parents = {below for below in revisions.values() if below is not None}
    heads = sorted(set(revisions) - parents)
    assert len(heads) == 1, f"expected a single Alembic head, found {heads}"
    return heads[0]


def expected(noun: str, number: str) -> int:
    """What a claim about `noun` written as `number` must say.

    An ordinal names the *next* member, so it asserts a set one smaller than
    itself: `a thirteenth capability` is right exactly when the set holds twelve.
    """
    size = purpose_count() if noun.lower().startswith("purpose") else capability_count()
    return size + 1 if number.lower() in ORDINALS else size


def stated(number: str) -> int:
    word = number.lower()
    return ORDINALS[word] if word in ORDINALS else CARDINALS[word]


#: Claims that are not about a set's size, each with the reason it is not.
#:
#: A shrinking allowlist, in the shape `D-81` set for derived constraints: an
#: entry that no longer matches reddens, so this list cannot rot into a list of
#: excuses for claims that have since changed meaning. `context` is a
#: distinctive fragment of the block, so an entry excuses one occurrence rather
#: than every occurrence of the same words in the same file.
EXCUSED: tuple[tuple[str, str, str, str], ...] = (
    (
        "ops/runbooks/gateway-operations.md",
        "eight capabilities",
        'It read "eight capabilities" until this run.',
        "quoted prior text in a provenance note, not a claim in the author's voice",
    ),
    (
        "ops/runbooks/mcp-and-cli-operations.md",
        "eight capabilities",
        'It read "eight capabilities" until this run.',
        "the same provenance note in the second runbook",
    ),
    (
        "tests/schema/test_capture_schema_migration.py",
        "eight\n    capabilities",
        "that revision emitted when it merged",
        "the frozen historical vocabulary of a merged revision, which `D-69` "
        "requires to stay at eight and seven forever",
    ),
    (
        "tests/schema/test_capture_schema_migration.py",
        "seven purposes",
        "that revision emitted when it merged",
        "the purpose half of the same frozen vocabulary",
    ),
    (
        "src/my_pa/adapters/mcp/tools.py",
        "four capabilities",
        "four capabilities were added, and the only change here",
        "a delta this package applied, not the size of the set",
    ),
    (
        "README.md",
        "four capabilities",
        "was in the not-implemented list below",
        "the same WP-6 delta, in the entry recording what one not-implemented "
        "item became; not the size of any set. Stated as a delta because the "
        "first version of this row called it the size of the `capture.*` subset "
        '"named in full", and that was false: `capture.*` holds five members, '
        "not four, once `capture.search` is counted",
    ),
    (
        "ops/runbooks/mcp-and-cli-operations.md",
        "four capabilities",
        "WP-6 added four capabilities and this list grew by four",
        "the same delta, in the runbook that measured it",
    ),
    (
        "ops/runbooks/end-to-end-operations.md",
        "two capabilities",
        "two capabilities is the end of the slice",
        "the two capabilities this walkthrough reaches, not the set",
    ),
    (
        "ops/runbooks/end-to-end-operations.md",
        "four capabilities",
        "while the same four capabilities through",
        "the four capture capabilities, named as a family",
    ),
    (
        "src/my_pa/domain/identity/purpose.py",
        "Two purposes",
        "Two purposes for the capture plane rather than a reuse",
        "the two purposes this package adds, not the size of `Purpose`",
    ),
    (
        "tests/end_to_end/test_vertical_slice.py",
        "eight-capability",
        "eight-capability sweep over fakes",
        "names another module's matrix as it stood when this sentence was "
        "written; the matrix itself is parametrised over `Capability`",
    ),
    (
        "ops/runbooks/mcp-and-cli-operations.md",
        "all three",
        "holds across all three. A migration phase",
        "the three transports, in a sentence whose subject is `--help`",
    ),
    (
        "tests/contract/test_capabilities_and_readiness.py",
        "all three",
        "would answer identically in all three.",
        "the three scenarios the docstring just listed, not the capability set",
    ),
)


def swept_files() -> list[Path]:
    """Every swept file except this one.

    This module is the one file in the sweep whose spelled counts are *data
    about* claims rather than claims: `EXCUSED` quotes each excused phrase
    verbatim, and the plants below are written wrong on purpose. Reading itself
    would make every entry in its own allowlist a finding.
    """
    found: list[Path] = []
    for root_name in SWEPT_ROOTS:
        root = ROOT / root_name
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix not in (".md", ".py") or not path.is_file():
                continue
            if SKIPPED_DIRECTORIES & set(path.parts):
                continue
            if any(part.endswith(SKIPPED_SUFFIXES) for part in path.parts):
                continue
            if path == Path(__file__).resolve():
                continue
            found.append(path)
    for file_name in SWEPT_FILES:
        path = ROOT / file_name
        if path.is_file():
            found.append(path)
    return sorted(found)


#: Every section the plan's own line 7 declares to be current state. Named for
#: what that line declares rather than for one heading number, because a helper
#: called `plan_section_3` that also reads section 1 is the next stale claim.
CURRENT_STATE_SECTIONS = (
    (1, "\n## 1. Authenticated identities"),
    (3, "\n## 3. What is implemented"),
)


def plan_current_state() -> list[tuple[str, int]]:
    """Each current-state section's text, with the line its slice starts on.

    Sections rather than a section: line 7 of the plan declares section 1 to be
    current identities, and section 1 carries the same two Alembic figures that
    section 3 carries. Reading only section 3 is what let this branch add a
    revision, correct the row that was checked, and leave the row 48 lines above
    it saying `ten` at a head that had moved — a control that does not cover its
    neighbour, inside the package that built the control.
    """
    text = PLAN.read_text(encoding="utf-8")
    found: list[tuple[str, int]] = []
    for _number, heading in CURRENT_STATE_SECTIONS:
        start = text.index(heading)
        # From the end of the anchor line, not from `start`: these anchors begin
        # with a newline, so `start` sits *before* the section's own heading and
        # a scan from there terminates on that heading and returns nothing.
        # Measured — the first version of this fix did exactly that and both
        # tests below went red on an empty section.
        following = [
            match.start()
            for match in _HEADING.finditer(text)
            if match.start() >= start + len(heading)
        ]
        end = following[0] if following else len(text)
        found.append((text[start:end], text[:start].count("\n")))
    return found


def plan_current_state_text() -> str:
    """The current-state sections as one passage, for rules that only match."""
    return "\n".join(section for section, _ in plan_current_state())


#: What ends a current-state section: the next heading of any level. This read
#: `text.index(f"\\n## {number + 1}. ")` until 2026-08-08 — the successor's
#: number written out, which is the same defect three other guards in this
#: directory carried and this package removed from each of them. It was loud
#: rather than silent, because `str.index` raises when the literal is absent, so
#: it was the least dangerous instance; but loudness came from `index` raising,
#: not from the boundary being derived, and a reordering that moved a section
#: without renumbering would have widened the scan with nothing going red. The
#: section is still *anchored* by its own heading — only the boundary is
#: structural — so the numbers in `CURRENT_STATE_SECTIONS` still say which
#: sections are read.
#:
#: Same-or-shallower, not any heading. A `## ` section legitimately contains
#: `### ` subsections, and terminating at the first heading of *any* level cuts
#: the section off at its own first subheading. That was measured rather than
#: reasoned about: the first version of this fix used `^#{1,6} ` and two tests
#: went red, which is the direction this class of error should fail in — a
#: narrowed scan finds less and complains, where a widened one finds more and
#: stays quiet.
_HEADING = re.compile(r"^#{1,2} ", re.MULTILINE)


#: Leading markers that are layout rather than prose: a Python comment hash, a
#: markdown heading hash, a blockquote arrow, a bullet.
_MARKER = re.compile(r"^(?:#+|>+|[-*+])\s*")


def _blocks(text: str) -> list[tuple[str, list[int]]]:
    """One `(flattened text, line number per character)` pair per block.

    Two decisions, and each was forced by a real defect.

    **Blocks are flattened.** `the eight` and `existing purposes` sat on
    consecutive lines of one `#` comment, with a hash and four spaces between
    them, and a line-at-a-time rule reads straight past it. Each line is
    stripped of leading layout and joined with a single space, so a claim
    written across a line break reads as one phrase.

    **A block is a table row, a list item, or a run of lines between blank
    lines.** In Python that keeps a decorator, a `def`, its docstring and its
    body together, which is what puts the word `capability` in scope for a
    one-line docstring that says only `All eight`.
    """
    blocks: list[tuple[list[str], list[int]]] = []
    previous_blank = True
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            previous_blank = True
            continue
        opens = (
            previous_blank
            or stripped.startswith("|")
            or bool(re.match(r"^(?:[-*+]\s|\d+[.)]\s)", stripped))
        )
        piece = _MARKER.sub("", stripped)
        if opens or not blocks:
            blocks.append(([piece], [lineno] * len(piece)))
        else:
            pieces, linemap = blocks[-1]
            pieces.append(piece)
            linemap.append(lineno)
            linemap.extend([lineno] * len(piece))
        previous_blank = False
    return [(" ".join(pieces), linemap) for pieces, linemap in blocks]


@dataclass(frozen=True)
class Claim:
    """One spelled count, and the block it was written in."""

    path: Path
    line: int
    phrase: str
    number: str
    noun: str
    block: str

    @property
    def where(self) -> str:
        return f"{self.path.relative_to(ROOT)}:{self.line} '{self.phrase}'"

    def excused_by(self) -> tuple[str, str, str, str] | None:
        relative = str(self.path.relative_to(ROOT))
        collapsed = " ".join(self.phrase.split()).lower()
        for entry in EXCUSED:
            path, phrase, context, _ = entry
            if path != relative:
                continue
            if " ".join(phrase.split()).lower() != collapsed:
                continue
            if " ".join(context.split()) in " ".join(self.block.split()):
                return entry
        return None


def _claims_in(path: Path, text: str, offset: int = 0) -> list[Claim]:
    found: list[Claim] = []
    for block, linemap in _blocks(text):
        about_capabilities = bool(_MEMBER_NEEDS.search(block))
        taken: list[tuple[int, int]] = []
        for pattern in (CLAIM, CLOSED_AT, ALL_OF):
            for match in pattern.finditer(block):
                noun = match.groupdict().get("noun") or "capabilities"
                if pattern is not CLAIM and not about_capabilities:
                    # `member`, `closed at N` and a bare `all N` name no set of
                    # their own; they are read only where the block is already
                    # about capabilities. Five enums in `src/` are described as
                    # having one member or gaining a second, and none is this one.
                    continue
                if _BORROWED.match(noun) and not about_capabilities:
                    continue
                if any(start < match.end() and match.start() < end for start, end in taken):
                    # `all twelve capabilities` is one claim, not two: the noun
                    # form wins and the bare form does not re-report it.
                    continue
                taken.append((match.start(), match.end()))
                found.append(
                    Claim(
                        path,
                        linemap[match.start()] + offset,
                        match.group(0),
                        match["number"],
                        noun,
                        block,
                    )
                )
    return found


def claims() -> list[Claim]:
    found: list[Claim] = []
    for path in swept_files():
        found.extend(_claims_in(path, path.read_text(encoding="utf-8")))
    for section, offset in plan_current_state():
        found.extend(_claims_in(PLAN, section, offset=offset))
    return found


CLAIMS = claims()

#: The fewest claims before this guard is deciding anything. An extractor that
#: silently returned nothing would satisfy every rule below.
FEWEST_CLAIMS = 25


def test_the_sweep_found_claims_to_check() -> None:
    assert len(CLAIMS) >= FEWEST_CLAIMS, f"only {len(CLAIMS)} spelled counts parsed"


def test_every_spelled_count_matches_the_set_it_names() -> None:
    wrong = sorted(
        f"{claim.where} says {stated(claim.number)}, the set holds "
        f"{expected(claim.noun, claim.number)}"
        for claim in CLAIMS
        if claim.excused_by() is None and stated(claim.number) != expected(claim.noun, claim.number)
    )
    assert not wrong, (
        f"{len(wrong)} spelled count(s) disagree with `Capability` or `Purpose`, which "
        "are what the repository actually declares; correct the prose rather than this "
        f"test, and excuse a claim only if it is not about the set's size: {wrong}"
    )


def test_every_excused_claim_is_still_there() -> None:
    """The allowlist shrinks or reddens; it never rots.

    An entry whose claim has been reworded stops excusing anything and starts
    hiding the next one, which is how an allowlist becomes a list of excuses.
    """
    stale = [
        f"{path} '{phrase}' ({reason})"
        for path, phrase, context, reason in EXCUSED
        if not any(claim.excused_by() == (path, phrase, context, reason) for claim in CLAIMS)
    ]
    assert not stale, (
        f"{len(stale)} allowlist entries match no claim at head; remove them rather "
        f"than leaving them to excuse something else: {stale}"
    )


def test_section_3_states_the_module_counts_it_says_it_derives() -> None:
    """Section 3 names its own two commands. This runs them.

    The paragraph says the figures were "recomputed at WP-4B3 rather than
    restated" and prints the `find` commands that produce them — and then went
    stale across the six packages that followed, which is the whole argument for
    a rule instead of a recomputation.
    """
    # Up to four words per figure, because a count above ninety-nine is spelled
    # with spaces in it — "one hundred and three". A single-word capture read
    # that as "three" and compared 3 against 103, which is a wrong answer rather
    # than the unreadable-word refusal the assertion below is written for.
    match = re.search(
        r"(?P<modules>(?:[A-Za-z-]+ ){0,3}[A-Za-z-]+) Python modules under `src/my_pa` and\s+"
        r"(?P<tests>(?:[A-Za-z-]+ ){0,3}[A-Za-z-]+) test modules",
        plan_current_state_text(),
    )
    assert match is not None, (
        "Section 3's module-count sentence no longer matches the shape this test "
        "reads. Update the sentence and this test together."
    )
    for key, derived in (("modules", source_modules()), ("tests", counted_test_modules())):
        word = match[key].lower()
        assert word in CARDINALS, f"section 3 states '{match[key]}', which this test cannot read"
        assert CARDINALS[word] == derived, (
            f"section 3 states {CARDINALS[word]} for '{key}' and the tree holds {derived}"
        )


#: A spelled count of Alembic revisions, wherever a current-state section states
#: one. The noun is not in `NAMED_NOUNS` because nothing else in the corpus
#: derives it; here it is derived from `migrations/versions/` directly.
REVISION_COUNT = re.compile(rf"\b(?P<count>{_NUMBER})\s+revisions\b", re.IGNORECASE)

#: A chain head, in either shape the plan writes it: `head \`x\`` in section 3's
#: row and `Alembic head | \`x\`` in section 1's identity table. Twelve hex
#: digits followed by the closing backtick, so the forty-character git SHA in
#: section 1's `Local \`main\` head` row is not read as a revision.
CHAIN_HEAD = re.compile(r"\bhead\b[^`\n]{0,12}`(?P<head>[0-9a-f]{12})`", re.IGNORECASE)

#: The fewest of each before this rule is deciding anything. Set at the
#: measurement rather than under it, because the universe is two rows and both
#: are load-bearing: section 1's identity table and section 3's row. Losing
#: either — by rewording it out of this shape, which is exactly how a stale
#: figure escapes a rule — reddens here rather than silently halving the check.
FEWEST_REVISION_COUNTS = 2
FEWEST_CHAIN_HEADS = 2


def chain_claims() -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Every revision count and every chain head in the current-state sections."""
    counts: list[tuple[int, str]] = []
    heads: list[tuple[int, str]] = []
    for section, offset in plan_current_state():
        for match in REVISION_COUNT.finditer(section):
            counts.append((offset + section[: match.start()].count("\n") + 1, match["count"]))
        for match in CHAIN_HEAD.finditer(section):
            heads.append((offset + section[: match.start()].count("\n") + 1, match["head"]))
    return counts, heads


def test_every_current_state_section_states_the_chain_it_derives() -> None:
    """Both places the plan names the chain, not only the lower one.

    The count is spelled and the head is not, but they rot together and from the
    same cause, so they are derived together — and they are stated **twice**, in
    section 1's identity table and in section 3's row, 48 lines apart. The
    predecessor of this test read section 3 alone. The branch that added
    `1a4c9e77b2d5` corrected the row that was read and left the row that was
    not, so the plan asserted ten revisions and eleven revisions at the same
    head, and every rule in this module stayed green. The derivation was already
    here; only the universe was wrong.
    """
    counts, heads = chain_claims()
    assert len(counts) >= FEWEST_REVISION_COUNTS, (
        f"only {len(counts)} spelled revision count(s) found in the plan's current-state "
        "sections; both the section 1 identity table and the section 3 row state one, so "
        "a rewording that hides one from this rule is the way a stale figure escapes"
    )
    assert len(heads) >= FEWEST_CHAIN_HEADS, (
        f"only {len(heads)} chain head(s) found in the plan's current-state sections; "
        "see the note on the revision count above"
    )

    expected_count = len(revision_files())
    expected_head = alembic_head()
    wrong = [
        f"{PLAN.relative_to(ROOT)}:{line} states {stated(word)} revisions and "
        f"`migrations/versions/` holds {expected_count}"
        for line, word in counts
        if word.lower() not in CARDINALS or CARDINALS[word.lower()] != expected_count
    ]
    wrong += [
        f"{PLAN.relative_to(ROOT)}:{line} states head {head} and the chain's head is "
        f"{expected_head}"
        for line, head in heads
        if head != expected_head
    ]
    assert not wrong, (
        f"{len(wrong)} Alembic claim(s) in the plan's current-state sections disagree with "
        f"`migrations/versions/`, which is what the repository actually declares: {wrong}"
    )


# ---- the plants ---------------------------------------------------------------


def test_a_chain_claim_is_read_in_both_shapes_the_plan_writes() -> None:
    """The two shapes, and the two tokens that must not be read as either.

    Section 1 writes the head inside an identity table and section 3 writes it
    in a row of prose. A rule that read only one of those shapes is what this
    cycle corrected, so both are planted wrong and both must be read. The two
    rejections are live in section 1 and are the reason this rule is not simply
    "a backticked hex string": a forty-character git SHA under ``Local `main`
    head``, and the canonical database's revision, which is deliberately *not*
    the chain head and is introduced by no `head` at all.
    """
    planted = (
        "| Alembic head | `0123456789ab` in the repository, ten revisions; the\n"
        "canonical database remains at `6c4d3ea82f10` |\n"
        "| Local `main` head | `8274d88a6211c417c43d2d937edfe2c8ccc369be` |\n"
        "| Alembic revisions | Implemented, twelve revisions, head `abcdef012345` |\n"
    )

    assert [match["count"] for match in REVISION_COUNT.finditer(planted)] == ["ten", "twelve"]
    assert [match["head"] for match in CHAIN_HEAD.finditer(planted)] == [
        "0123456789ab",
        "abcdef012345",
    ]

    correct = f"Implemented, {SPELLED[len(revision_files())]} revisions, head `{alembic_head()}`"
    count = REVISION_COUNT.search(correct)
    head = CHAIN_HEAD.search(correct)
    assert count is not None and CARDINALS[count["count"].lower()] == len(revision_files())
    assert head is not None and head["head"] == alembic_head()


def test_the_case_insensitive_flag_is_the_one_that_mattered(tmp_path: Path) -> None:
    """The exact defect the last cycle's grep missed, in both cases.

    A sentence-initial `Eight` is what a case-sensitive sweep walks past, and it
    is how a module docstring opens. Both cases are asserted, because a rule
    that only read the capitalised form would have the mirror-image hole.
    """
    planted = tmp_path / "planted.md"
    planted.write_text("Eight capabilities over a socket. And eight capabilities again.\n", "utf-8")

    found = _claims_in(planted, planted.read_text(encoding="utf-8"))
    assert [claim.number.lower() for claim in found] == ["eight", "eight"]
    assert all(stated(claim.number) != expected(claim.noun, claim.number) for claim in found)


def test_a_planted_claim_of_every_shape_is_caught(tmp_path: Path) -> None:
    """One plant per shape this guard reads, all wrong, none excused."""
    planted = tmp_path / "planted.md"
    planted.write_text(
        "The set is closed at eight. There are eight capability names and seven\n"
        "purposes, so a ninth capability and an eighth purpose would be new.\n",
        encoding="utf-8",
    )

    found = _claims_in(planted, planted.read_text(encoding="utf-8"))
    phrases = sorted(" ".join(claim.phrase.split()).lower() for claim in found)
    assert phrases == [
        "closed at eight",
        "eight capability names",
        "eighth purpose",
        "ninth capability",
        "seven\npurposes".replace("\n", " "),
    ], phrases
    assert all(stated(claim.number) != expected(claim.noun, claim.number) for claim in found), [
        (claim.phrase, stated(claim.number), expected(claim.noun, claim.number)) for claim in found
    ]


def test_a_correct_claim_of_every_shape_passes(tmp_path: Path) -> None:
    """The green half. A rule that flagged every number would prove nothing."""
    planted = tmp_path / "planted.md"
    planted.write_text(
        f"The set is closed at {_UNITS[capability_count()]}. There are "
        f"{_UNITS[capability_count()]} capability names and "
        f"{_UNITS[purpose_count()]} purposes, so a "
        f"{_ORDINAL_UNITS[capability_count() + 1]} capability would be new.\n",
        encoding="utf-8",
    )

    found = _claims_in(planted, planted.read_text(encoding="utf-8"))
    assert len(found) == 4, [claim.phrase for claim in found]
    assert all(stated(claim.number) == expected(claim.noun, claim.number) for claim in found)


@pytest.mark.parametrize(
    ("body", "reads"),
    [
        ("One capability per invocation.", False),
        ("`LimitationReason` has one member today.", False),
        ("A second member arrives with the adapter.", False),
        ("The capability set is closed at eight; a ninth member is forbidden.", True),
        ("readiness.implemented 12 of 12", False),
    ],
    ids=[
        "the article is not a count",
        "nor is a member count of another enum",
        "nor is an ordinal member of another enum",
        "but a member of the capability set is",
        "and digits are out of scope by design",
    ],
)
def test_the_classifier_separates_counts_from_articles_and_other_enums(
    tmp_path: Path, body: str, reads: bool
) -> None:
    """Every rejected sentence is live in `src/`, and the accepted one shipped stale."""
    planted = tmp_path / "planted.md"
    planted.write_text(body + "\n", encoding="utf-8")
    assert bool(_claims_in(planted, planted.read_text(encoding="utf-8"))) is reads
