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
- **The sweep did not read `docs/` at all.** The same defect again, one
  directory over, and the largest instance of it: the Relationship Intelligence
  implementation plan makes more derivable claims than any other document here
  and not one of them was bound to anything. An independent review found three
  false claims standing in it — a labelled-corpus count, a pagination claim, and
  a fixture claim — each of which had survived every sweep because no sweep
  reached the file. It is named in `SWEPT_FILES` now. A guard that reads the
  documents it was written next to and not the document that makes the claims is
  the shape above, stated a third time.
- **The count was written down.** A guard holding a literal `12` is the next
  stale claim, one release later. Every count here is derived: from `Capability`
  and `Purpose` themselves, and from the very `find` commands section 3 names.

**What a claim is.** A spelled number immediately before `capabilities`,
`capability names`, `purposes`, or — inside a block that is already talking about
capabilities — `member`; plus the phrase `closed at <number>`, which is how this
corpus states the capability set's size without naming it; plus an emphasised
number that carries no noun at all, `publishes **twenty**.`, which is how two
runbook lines stated a default publication count that was never measured and was
wrong by twenty-two. Ordinals are read as the *next* member: `a ninth capability`
asserts the set has eight, and is stale in exactly the way `eight capabilities`
is. The branch that added `capture.*` corrected one ordinal site and left eight,
which is why ordinals are in.

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
- **`all <number>` closed by an em-dash is read now.** `ALL_OF` used to require a
  comma or a full stop after the number, so `publishing all thirty — does read
  one` escaped it: a genuine stale count of a set holding fifty-four, in the
  docstring of the test this module's sibling rule cites as its own evidence.
  The rule was deliberately left open while that word sat outside the allowlist
  of the package that found it, on the grounds that closing it would land either
  half-red or with a real defect excused. Both halves landed together: the
  docstring now says `all fifty-four`, the dash is admitted, and the corpus
  yields no new claims. Recorded because "left open on purpose" is a note with a
  shelf life, and this one expired one commit after it was written.
- **The published subset is seen but not derived.** `BARE_EMPHASIS` reads
  `publishes **forty-two**` and compares it against `Capability`, which holds
  fifty-four, so the two runbook lines stating the default publication count
  are excused below rather than checked. They are *bound* — a reworded or
  renumbered claim reddens `test_every_excused_claim_is_still_there` — but the
  figure itself rests on a reason in an allowlist, not on a derivation. Deriving
  it means teaching this module the withheld prefixes that
  `tests/contract/test_mcp_transport.py` already owns, which is a second copy of
  a constant, and that trade has not been made.
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
#:
#: **`docs/` is not a swept root and the Relationship Intelligence plan is named
#: here one file at a time, for the reason this list exists.** That plan is the
#: document in this repository that makes the most derivable claims, and it was
#: bound to nothing at all: this module read `apps/`, `ops/`, `src/`, `tests/`,
#: `README.md`, and two sections of the MCV plan, and `docs/plans/` appeared in
#: none of them. An independent review then found three false claims in it that
#: had survived precisely because no rule read the file — a corpus count, a
#: pagination claim, and a fixture claim — which is the same defect this module
#: was built for, one directory over. The whole file is read rather than named
#: sections of it, because unlike the MCV plan it carries no history register
#: below a current-state line; its historical passages are individual blocks and
#: `EXCUSED` is what names those.
SKIPPED_DIRECTORIES = frozenset({"__pycache__", ".ruff_cache", ".mypy_cache", ".pytest_cache"})

#: Documents swept only in their current-state sections, because the rest of the
#: file is a dated history register whose numbers were true when written. Swept
#: whole, the MCV plan's register alone contributes seventeen historical claims —
#: which is why sweeping it section-wise came first, and why widening to `docs/`
#: must not undo that.
SECTION_SWEPT_FILES = frozenset({"docs/plans/mcv-completion-plan.md"})

#: Lineage specifications are not swept. A spec records what was proposed and
#: what was true when it was written: `mcv-read-only-vertical-slice.md` says
#: twelve capabilities because twelve is what that slice specified, and
#: `relationship-intelligence-v0.2.md` and `-v0.3.md` carry operator-review
#: statuses of their own. Sweeping them would demand that a historical proposal
#: be rewritten every time the product grew, which is the opposite of what a
#: lineage document is for.
#:
#: **Named individually rather than by directory, and an earlier version was not.**
#: Excluding all of `docs/specs/` also excluded
#: `relationship-intelligence-v0.3-acceptance.md`, which this campaign authored
#: and which makes present-tense claims about repository artifacts ("a seeded
#: synthetic fixture now exists at…", proof tiers) — exactly the kind of claim
#: this guard exists to bind. The blanket exclusion was then *cited* as the
#: reason a defect in that file could stay open. A directory is a convenient
#: unit; what a document claims about is the honest one.
LINEAGE_SPECIFICATIONS = frozenset(
    {
        "docs/specs/mcv-read-only-vertical-slice.md",
        "docs/specs/relationship-intelligence-v0.2.md",
        "docs/specs/relationship-intelligence-v0.3.md",
    }
)

#: Every other Markdown document under `docs/`, plus the top-level `README.md`.
#:
#: Named individually until now — `README.md` and the RI plan — which reproduced
#: this module's own diagnosis one file over: a plant of `forty-one capabilities`
#: in `docs/architecture/system-context.md`, whose capability figures this
#: campaign rewrote, left the suite green. A guard widened to the file where a
#: defect was found is a guard shaped by where the defect was found.
#:
#: Enumerated by walk rather than by hand so a document added tomorrow is swept
#: without anyone remembering to add it, which is the same reason every count
#: here is derived rather than written down.
SWEPT_FILES = (
    "README.md",
    # Root-level governance documents. A plant of `forty-one capabilities` in
    # each went uncaught: they sit under no swept root, and the file list held
    # only `README.md`. `AGENTS.md` is the document every agent is pointed at
    # first, so a stale set size there is read more often than one in a runbook.
    "AGENTS.md",
    "CONTRIBUTING.md",
    "AI_OPERATING_MANUAL.md",
    "SECURITY.md",
    *sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "docs").rglob("*.md")
        if not any(part in SKIPPED_DIRECTORIES for part in path.parts)
        and str(path.relative_to(ROOT)) not in SECTION_SWEPT_FILES
        and str(path.relative_to(ROOT)) not in LINEAGE_SPECIFICATIONS
    ),
)

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
    # The twenties, added when the capability set reached nineteen and
    # `a twentieth capability` became the ordinal a correct claim would use. The
    # tuple is indexed by value, so it has to be dense and in order; the next
    # boundary announces itself the same way this one did, with an `IndexError`
    # in the green-half plant rather than with a false pass.
    "twentieth",
    "twenty-first",
    "twenty-second",
    "twenty-third",
    "twenty-fourth",
    "twenty-fifth",
    "twenty-sixth",
    "twenty-seventh",
    "twenty-eighth",
    "twenty-ninth",
    "thirtieth",
    "thirty-first",
    "thirty-second",
    # The thirties/forties, added when local task-management and origin
    # context.prepare were merged and the public set reached forty-five.
    "thirty-third",
    "thirty-fourth",
    "thirty-fifth",
    "thirty-sixth",
    "thirty-seventh",
    "thirty-eighth",
    "thirty-ninth",
    "fortieth",
    "forty-first",
    "forty-second",
    "forty-third",
    "forty-fourth",
    "forty-fifth",
    "forty-sixth",
    "forty-seventh",
    "forty-eighth",
    "forty-ninth",
    # The fifties, added when WP-RI-05 admitted the five `entities.*` capabilities
    # and the public set reached fifty-four, so `a fifty-fifth capability` became
    # the ordinal a correct claim would use. This boundary announced itself exactly
    # as the two above did — an `IndexError` in the green-half plant rather than a
    # false pass — which is the property the density of this tuple buys.
    "fiftieth",
    "fifty-first",
    "fifty-second",
    "fifty-third",
    "fifty-fourth",
    "fifty-fifth",
    "fifty-sixth",
    "fifty-seventh",
    "fifty-eighth",
    "fifty-ninth",
    "sixtieth",
    # The sixties, added when the Intelligence Artifact plane admitted eight
    # `reports.*` capabilities and the public set reached sixty-two, so `a
    # sixty-third capability` became the ordinal a correct claim would use. It
    # announced itself the same way the three boundaries above did: the prose was
    # corrected to `sixty-third`, this tuple could not read it, and the claim was
    # reported as saying *three* — a false finding rather than a false pass, which
    # is what the density of this tuple is for.
    "sixty-first",
    "sixty-second",
    "sixty-third",
    "sixty-fourth",
    "sixty-fifth",
    "sixty-sixth",
    "sixty-seventh",
    "sixty-eighth",
    "sixty-ninth",
    "seventieth",
    # The seventies, added when the Relationship Memory plane admitted eight
    # `relationship_memory.*` capabilities and the public set reached seventy, so
    # `a seventy-first capability` became the ordinal a correct claim would use.
    # This boundary announced itself in both the ways the four above did at once:
    # the green-half plant raised `IndexError` on index seventy-one, and
    # `tests/contract/test_http_transport.py` — whose prose already said
    # `seventy-first` — was reported as claiming *one*, because the longest-match
    # scan could find no compound ordinal here and fell back to the bare `first`
    # inside it. A false finding rather than a false pass, which is what the
    # density of this tuple buys.
    "seventy-first",
    "seventy-second",
    "seventy-third",
    "seventy-fourth",
    "seventy-fifth",
    "seventy-sixth",
    "seventy-seventh",
    "seventy-eighth",
    "seventy-ninth",
    "eightieth",
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

#: Cardinals alone, for the rules where an ordinal is not a count.
_READ_CARDINALS_PATTERN = "|".join(re.escape(word) for word in _READ_CARDINALS)

#: Adjectives the corpus writes between the number and the noun.
#:
#: **Repeated, not single.** This admitted exactly one adjective until
#: 2026-08-20, and that is how "the entity plane adds **five** public read
#: capabilities" sat in a swept file, in a document whose job is stating what
#: the build does not do, while the plane served six — the guard read the file,
#: found no claim, and reported nothing. A count is no less a count for having
#: two words in front of the noun, and the failure mode of a guard that stops
#: reading is silence rather than a wrong answer, which is the harder kind to
#: notice. `read` and `entity` are admitted for the same reason: the corpus
#: writes them there.
_ADJECTIVE = r"(?:(?:existing|new|public|remaining|other|further|capability|read|entity)\s+)+"

#: Nouns that name the set outright, wherever they are written.
NAMED_NOUNS = ("capabilit(?:y|ies)", "purposes?")

#: Nouns that name the set only where the block is already about capabilities.
#: `member`, `name`, `string` and `tool` are all how this corpus refers to a
#: capability without saying the word — "eight names typed out by hand", "none
#: of the eight strings", "a ninth member of it" — and all four are also
#: ordinary English about other things, so context decides.
BORROWED_NOUNS = ("members?", "names?", "strings?", "tools?")

#: What may sit between the number and the noun without breaking the claim:
#: whitespace, a hyphen, and markdown emphasis markers -- but not a backtick,
#: which opens a code span and so starts a new token rather than continuing
#: this one (`the first \`capabilities.get\`` is not a count of anything).
#:
#: The emphasis half was missing, and it hid two stale counts. Both runbooks
#: wrote `**forty-eight** capabilities`, and `[\s-]+` does not match the `**`
#: between them -- so the sweep found no claim there at all and stayed green
#: while the documents said forty-eight of a set holding fifty-four. A guard
#: that reads unformatted prose only is a guard that stops reading exactly where
#: an author put emphasis, which is where the load-bearing numbers tend to be.
_GAP = r"[\s\-*_]+"

#: One code span sitting between the number and a *borrowed* noun, which is this
#: corpus's most common way of writing a count: `the six \`documents.\` names`,
#: `the five \`entities.\` names`.
#:
#: Admitted 2026-08-20, and the reason is a live miss in both directions.
#: `docs/architecture/system-context.md` read "**A default composition exposes
#: forty-two of them.** The six \`documents.\` names ... and the five
#: \`entities.\` names" -- forty-two is only consistent with six and six, so the
#: paragraph contradicted itself in one sentence, and the sweep found *no claim
#: at all* there because `_GAP` excludes a backtick.
#:
#: Restricted to `BORROWED_NOUNS`, which is what keeps the original rule intact:
#: the excluded case that rule was written for is `the first
#: \`capabilities.get\``, where the code span is the thing being counted and the
#: noun that follows is `capability` -- a `NAMED_NOUN`. A borrowed noun after a
#: code span is the corpus naming a family and then counting its members.
_SPANNED = r"(?:`(?P<span>[^`\n]{1,60})`" + _GAP + r")?"

CLAIM = re.compile(
    rf"\b(?P<number>{_NUMBER}){_GAP}(?:{_ADJECTIVE})?"
    rf"(?:{_SPANNED}(?P<borrowed>{'|'.join(BORROWED_NOUNS)})"
    rf"|(?P<noun>{'|'.join(NAMED_NOUNS + BORROWED_NOUNS)}))\b",
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
ALL_OF = re.compile(rf"\ball (?P<number>{_NUMBER})(?=[,.\u2014])", re.IGNORECASE)

#: The emphasised form with the noun left off entirely: `A default process
#: publishes **twenty**.` Two runbook lines said that of a set whose default
#: publication is forty-two, and no rule here read either, because `CLAIM` needs
#: a noun, `CLOSED_AT` needs the words `closed at`, and `ALL_OF` needs `all`. A
#: number an author bothered to emphasise is a number a reader will believe, and
#: this shape is the one that carries no noun for a grep to anchor on.
#:
#: **Both conditions are load-bearing and were measured, not reasoned about.**
#: The number must be emphasised *and* must end the phrase — comma, semicolon,
#: full stop, closing bracket, or end of block. Dropped, the end-of-phrase
#: condition turns this into a false-finding machine: `**two** revisions behind
#: head`, `**sixty-two** revisions`, `**five** revisions later` and `a **second**
#: surface` all sit in blocks that mention capabilities somewhere, and every one
#: of them already names its own noun. With the condition, one match remains in
#: the whole swept corpus and it is the defect this rule was added for. Like
#: `ALL_OF` and `CLOSED_AT`, it is read only where the block is already about
#: capabilities, which is what excludes `written **first**` and `a **third**,
#: independent thing` in `src/`.
BARE_EMPHASIS = re.compile(rf"\*\*(?P<number>{_NUMBER})\*\*(?=[.,;)]|$)", re.IGNORECASE)

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
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    heads = list(ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_heads())
    assert len(heads) == 1, f"expected a single Alembic head, found {heads}"
    return heads[0]


def entity_plane_count() -> int:
    """The entity plane's own size, derived from the `entities.` prefix."""
    return len([c for c in Capability if c.value.startswith("entities.")])


def _family(span: str | None) -> str | None:
    """The capability family a code span names, if it names one.

    `` `entities.` ``, `` `documents.` ``, `` `capture.*` `` and `` `tasks.` ``
    are how this corpus writes a family before counting its members. Reading the
    prefix out of the span is what lets those counts be **checked** against the
    family rather than excused one by one: the sweep derives the size from
    `Capability`, so the same edit that adds a member to a family reddens every
    sentence that states that family's size.
    """
    if span is None:
        return None
    prefix = span.strip().rstrip("*")
    if not prefix.endswith("."):
        return None
    return prefix if any(c.value.startswith(prefix) for c in Capability) else None


#: Claims counting a *named subset* rather than the whole enum, and the set each
#: one counts.
#:
#: These would otherwise have to be excused, and an excuse is checked against
#: nothing — `EXCUSED` verifies that the phrase is still present, never that the
#: reason still holds, so four entries here sat saying "the entity plane's own
#: five" while the plane served six. Resolving them against the subset instead
#: makes them **claims that are checked**, so the same edit that grows the plane
#: reddens them by name.
#:
#: Matched exactly as `EXCUSED` is: path, phrase, and a distinctive fragment of
#: the block, so an entry binds one occurrence rather than every occurrence of
#: the same words in the same file.
SUBSET_CLAIMS: tuple[tuple[str, str, str], ...] = (
    (
        "docs/plans/relationship-intelligence-implementation-plan.md",
        "Six `Capability` members",
        "Delivered in full",
    ),
    (
        "docs/plans/relationship-intelligence-implementation-plan.md",
        "six `Capability` members",
        "The capability and MCP surface",
    ),
    (
        "docs/operations/mcv-limitations.md",
        "six** public read capabilities",
        "this document, whose job is stating what the build does not do",
    ),
    (
        "docs/plans/relationship-intelligence-implementation-plan.md",
        "Six read capabilities",
        "each bounded and paginated",
    ),
    (
        "ops/runbooks/README.md",
        "six read capabilities",
        "how to read the unresolved-mention",
    ),
    (
        "src/my_pa/bootstrap/settings.py",
        "six read capabilities",
        "Default off",
    ),
    (
        "src/my_pa/domain/identity/operation.py",
        "Six read capabilities",
        "over `knowledge.entities` and the tables around it",
    ),
)


def expected(noun: str, number: str, subset: str | None = None) -> int:
    """What a claim about `noun` written as `number` must say.

    An ordinal names the *next* member, so it asserts a set one smaller than
    itself: `a thirteenth capability` is right exactly when the set holds twelve.

    `subset` names a set smaller than the enum when the claim is about one — see
    `SUBSET_CLAIMS` for why those are resolved rather than excused.
    """
    if subset == "entity_plane":
        size = entity_plane_count()
    elif subset is not None:
        size = len([c for c in Capability if c.value.startswith(subset)])
    elif noun.lower().startswith("purpose"):
        size = purpose_count()
    else:
        size = capability_count()
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
        "README.md",
        "four `capture.*` names",
        "WP-6 added four `capture.*` names and two capture",
        "what one work package added on the day it merged, not the family's "
        "size now -- `capture.search` arrived later and the sentence is about "
        "WP-6",
    ),
    (
        "tests/schema/test_task_read_capability_migration.py",
        "four `tasks.` names",
        "`capability_is_known` gains the four `tasks.` names",
        "the four names *this revision* admits, which is the task read plane; "
        "the `tasks.` family has since grown a write plane that this revision "
        "does not mention and must not count",
    ),
    (
        "src/my_pa/domain/identity/purpose.py",
        "second read purpose",
        "would map to exactly one capability and separate",
        "counts read purposes, which is neither `Purpose` nor a capability set, "
        "and argues that a second one would separate nothing -- a claim about "
        "what a purpose would buy, not about how many exist",
    ),
    (
        "docs/plans/relationship-intelligence-implementation-plan.md",
        "second read purpose",
        "would map to exactly one capability and",
        "the same argument as `purpose.py`, quoted in the plan: about what a "
        "second read purpose would separate, not about the size of any set",
    ),
    (
        "docs/architecture/module-boundaries.md",
        "closed at eight",
        "what does **not** stand is the reason it used to be given in",
        "the sentence quotes a superseded premise in order to withdraw it, and "
        "says so in the same clause",
    ),
    (
        "docs/architecture/module-boundaries.md",
        "ninth member",
        "closed against a ninth *source-registration* capability",
        "about what the set is closed against, not how large it is; the size "
        "claim beside it was stale and was corrected to fifty-four",
    ),
    (
        "docs/architecture/system-context.md",
        "twelve capabilities",
        "Historical note: the earlier figures",
        "an explicit historical note whose own sentence says these 'are not current-state claims'",
    ),
    (
        "docs/operations/mcv-limitations.md",
        "two purposes",
        "Six `documents.` capabilities under two purposes of their own",
        "the two purposes belonging to the documents family, not the size of `Purpose`",
    ),
    (
        "docs/security/threat-model.md",
        "two purposes",
        "Six `documents.` capabilities under two purposes of their own",
        "the same claim about the documents family, in the second document",
    ),
    (
        "ops/runbooks/gateway-operations.md",
        "twelve** capabilities",
        "Re-executed 2026-08-03",
        "a dated transcript of what one run observed at head `1a4c9e77b2d5`, "
        "which is evidence of the past rather than a claim about the set now; "
        "reachable only since the sweep learned to read across emphasis",
    ),
    (
        "ops/runbooks/mcp-and-cli-operations.md",
        "twelve** capabilities",
        "Re-executed 2026-08-03",
        "the same dated transcript in the second runbook",
    ),
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
        "src/my_pa/domain/identity/purpose.py",
        "two purposes",
        "capture and managed-document planes each have two",
        "the pair each of those two planes carries, not the size of `Purpose`. "
        "Its own entry because the entry above used to excuse it too: one "
        "`Purpose` enum holds both comments sixty lines apart, so a "
        "block-wide match handed this claim a reason written about a different "
        "sentence",
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
    (
        "tests/schema/test_managed_document_capability_migration.py",
        "two purposes",
        "two purposes more than the revision below it",
        "the two purposes that widening added, not the size of `Purpose`",
    ),
    (
        "tests/unit/test_policy.py",
        "four capabilities",
        "All four capabilities share the single",
        "the four task-read names sharing one purpose, not the size of `Capability`",
    ),
    (
        "tests/unit/test_policy.py",
        "five capabilities",
        "All five capabilities share the single",
        "the five task-write names sharing one purpose, not the size of `Capability`",
    ),
    (
        "tests/unit/test_policy.py",
        "six capabilities",
        "All six capabilities share the single",
        "the six entity-plane read names sharing one purpose, not the size of `Capability`",
    ),
    # --- the two runbook lines this package corrected --------------------------
    #
    # The default publication count. Read by `BARE_EMPHASIS` and excused rather
    # than checked, because it is the size of a *different* set — `Capability`
    # less the two families a default composition withholds — and this module
    # derives only `Capability` and `Purpose`. Excused, not unread: both lines
    # said `twenty` of a set that publishes forty-two, and if either is reworded
    # or the figure moves, `test_every_excused_claim_is_still_there` reddens and
    # an author has to come back here. The module docstring's last boundary note
    # records what deriving it would cost.
    (
        "ops/runbooks/mcp-and-cli-operations.md",
        "**fifty**",
        "A default process publishes",
        "the count a default composition publishes — `Capability` less the six "
        "`documents.` and six `entities.` names it withholds — not the size of "
        "`Capability`, which the same block states correctly as sixty-two",
    ),
    (
        "ops/runbooks/mcp-and-cli-operations.md",
        "**fifty**",
        "none beginning `documents.`",
        "the same default-publication count, in the line naming the test that measures it",
    ),
    (
        "README.md",
        "fifty tools",
        "a default process publishes fifty tools",
        "the same default-publication count, in the bullet describing the MCP "
        "adapter; the tool list is derived from `available_capabilities`, not "
        "from `Capability`, which the same bullet states correctly as sixty-two",
    ),
    # --- the Intelligence Artifact plane, newly swept --------------------------
    #
    # Each of these counts what one work package added, or quotes what a line
    # used to say. None is a claim about the size of `Capability` or `Purpose`,
    # and rewording any of them reddens `test_every_excused_claim_is_still_there`
    # rather than passing quietly.
    (
        "docs/decisions/ADR-010-intelligence-artifact-report-plane.md",
        "Eight public capabilities",
        "join the audited vocabulary",
        "the size of the `reports.*` family this ADR admits, not the size of "
        "`Capability` -- the consequence section of an ADR is about what the "
        "decision adds",
    ),
    (
        "docs/decisions/ADR-010-intelligence-artifact-report-plane.md",
        "two purposes",
        "join the audited vocabulary",
        "the two purposes this ADR admits, named in the same sentence, not the size of `Purpose`",
    ),
    (
        "src/my_pa/domain/identity/purpose.py",
        "Two purposes",
        "Intelligence Artifact / Report plane",
        "how many purposes this plane declares and why it is two rather than a "
        "reuse of an existing grant; the sentence is a `D-91` argument, not a "
        "count of the enum it sits in",
    ),
    (
        "ops/runbooks/gateway-operations.md",
        "fifty-four public capabilities",
        'this line read "serves the',
        "a quotation of what this line said before the 2026-08-19 correction, "
        "preserved so the correction can be read; quoting a superseded figure is "
        "not restating it",
    ),
    # --- the Relationship Intelligence plan, newly swept -----------------------
    #
    # Every claim this file makes about a count of capabilities is about the
    # five `entities.*` names — the family that plane added — and not about
    # `Capability`. That is the same disposition `tests/unit/test_policy.py`'s
    # two entries and the `capture.*` entries above carry, and it is why the
    # sweep reaching this file at last produced corrections in the *other*
    # figures it states (a labelled-corpus count, a pagination claim, a fixture
    # claim, two test counts) rather than in these.
    (
        "docs/plans/relationship-intelligence-implementation-plan.md",
        "two capabilities",
        "said pagination was delivered for one of the two capabilities",
        "quotes the superseded wording of this cell in order to withdraw it, "
        "and says in the same sentence that both halves are out of date; three "
        "entity reads page now, not two",
    ),
    (
        "docs/plans/relationship-intelligence-implementation-plan.md",
        "five capabilities",
        "registered all five capabilities at once",
        "`D-RI-18`: the five `entities.*` names, registered as one family rather "
        "than one at a time",
    ),
    (
        "docs/plans/relationship-intelligence-implementation-plan.md",
        "all five",
        "one purpose, `entity_read`, for all five",
        "`D-RI-19`: the same five `entities.*` names sharing one purpose",
    ),
    (
        "docs/plans/relationship-intelligence-implementation-plan.md",
        "all five",
        "the floor was missing from all five",
        "the five `entities.*` names the off-switch test is parameterized over",
    ),
    (
        "docs/plans/relationship-intelligence-implementation-plan.md",
        "five capabilities",
        "scan covered four of the five capabilities",
        "an adversarial finding about four of the entity plane's five, which is "
        "a delta within that family",
    ),
    (
        "docs/plans/relationship-intelligence-implementation-plan.md",
        "five capabilities",
        "eight tables and five capabilities had outgrown",
        "the same entity-plane five, in the paragraph explaining the schema-suite "
        "accumulation sets",
    ),
    (
        "docs/plans/relationship-intelligence-implementation-plan.md",
        "forty-eight** capabilities",
        "Two runbooks read",
        "quoted prior text: the stale figure two runbooks carried, reproduced in "
        "the finding that records its correction, not a claim in the author's voice",
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
    family: str | None = None

    @property
    def where(self) -> str:
        return f"{self.path.relative_to(ROOT)}:{self.line} '{self.phrase}'"

    def excused_by(self) -> tuple[str, str, str, str] | None:
        """The entry that excuses this claim, matched against the claim's own sentence.

        **`context` used to be matched against the whole block, and that is not
        what the `EXCUSED` docstring says it does.** The tenth review found
        `tests/unit/test_policy.py:259` — "All five capabilities" above *six*
        enumerated pairs, the same defect this campaign had just corrected in
        `README.md` — silently excused by the entry written for line 236. Both
        sentences sat inside one `PERMITTED_PAIRS` assignment, so one block
        contained both, and "a distinctive fragment of the block" distinguished
        nothing.

        Narrowing the match to the claim's own line was tried and is wrong: the
        corpus wraps these comments freely, and nine legitimate entries name a
        phrase spanning more prose than any small window holds. So the match
        stays against the block, and the ambiguity is caught directly instead —
        `test_no_excused_entry_excuses_more_than_one_claim` fails when one entry
        covers two claims, which is the shape that hid the miscount.
        """
        relative = str(self.path.relative_to(ROOT))
        collapsed = " ".join(self.phrase.split()).lower()
        for entry in EXCUSED:
            path, phrase, context, _ = entry
            if path != relative:
                continue
            if " ".join(phrase.split()).lower() != collapsed:
                continue
            collapsed_context = " ".join(context.split())
            if collapsed_context not in " ".join(self.block.split()):
                continue
            if not self._context_sits_beside_this_claim(collapsed_context):
                continue
            return entry
        return None

    def _context_sits_beside_this_claim(self, collapsed_context: str) -> bool:
        """Whether the excusing phrase is where this claim is, not merely in its block.

        A block is as large as the declaration it belongs to, and
        `src/my_pa/domain/identity/purpose.py` puts two different "two purposes"
        comments sixty lines apart inside one `Purpose` enum. Matching on the
        block alone means the first entry in `EXCUSED` claims both, so the
        second claim is excused by a reason written about the first — and
        `tests/unit/test_policy.py` was excused that way while carrying a live
        miscount.

        The phrase is located in the file by a four-line sliding window, which is
        what the corpus's wrapping needs, and the claim has to fall inside it.
        """
        lines = self.path.read_text(encoding="utf-8").splitlines()
        for start in range(len(lines)):
            window = " ".join(" ".join(lines[start : start + 4]).split())
            if collapsed_context in window and start <= self.line <= start + 4:
                return True
        return False

    def subset(self) -> str | None:
        """The named set this claim counts, when it is not the whole enum.

        A family read out of the claim's own code span wins over the allowlist
        below, because it is derived from the sentence rather than recorded
        beside it — there is nothing to keep in step.
        """
        if self.family is not None:
            return self.family
        relative = str(self.path.relative_to(ROOT))
        collapsed = " ".join(self.phrase.split()).lower()
        for path, phrase, context in SUBSET_CLAIMS:
            if path != relative:
                continue
            if " ".join(phrase.split()).lower() != collapsed:
                continue
            if " ".join(context.split()) in " ".join(self.block.split()):
                return "entity_plane"
        return None


def _claims_in(path: Path, text: str, offset: int = 0) -> list[Claim]:
    found: list[Claim] = []
    for block, linemap in _blocks(text):
        about_capabilities = bool(_MEMBER_NEEDS.search(block))
        taken: list[tuple[int, int]] = []
        for pattern in (CLAIM, CLOSED_AT, ALL_OF, BARE_EMPHASIS):
            for match in pattern.finditer(block):
                groups = match.groupdict()
                noun = groups.get("noun") or groups.get("borrowed") or "capabilities"
                family = _family(groups.get("span"))
                if pattern is not CLAIM and not about_capabilities:
                    # `member`, `closed at N`, a bare `all N` and a bare `**N**`
                    # name no set of their own; they are read only where the
                    # block is already about capabilities. Five enums in `src/`
                    # are described as having one member or gaining a second,
                    # and none is this one.
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
                        family,
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
        f"{expected(claim.noun, claim.number, claim.subset())}"
        for claim in CLAIMS
        if claim.excused_by() is None
        and stated(claim.number) != expected(claim.noun, claim.number, claim.subset())
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


def test_a_bare_emphasised_count_is_read_and_a_qualified_one_is_not(tmp_path: Path) -> None:
    """The shape two runbook lines used, and the three shapes it must not swallow.

    `publishes **twenty**.` is a claim with no noun for any other rule to anchor
    on, and it is the shape that stated a default publication count wrong by
    twenty-two under a heading reading "Measured at this head". The three
    rejections are the measured ones, not imagined: a number that names its own
    noun (`**two** revisions`) is that noun's claim and not this set's, and a
    block that is not about capabilities is not read at all — `written **first**`
    and `a **third**, independent thing` both sit in `src/` today.
    """
    planted = tmp_path / "planted.md"
    planted.write_text(
        "A default process publishes **twenty**. The capability set is larger.\n"
        "\n"
        "The schema is **two** revisions behind, which is a capability-free fact\n"
        "about migrations even in this capability-naming block.\n"
        "\n"
        "The row is written **first**, under `ON CONFLICT DO NOTHING`.\n",
        encoding="utf-8",
    )

    found = _claims_in(planted, planted.read_text(encoding="utf-8"))
    assert [" ".join(claim.phrase.split()) for claim in found] == ["**twenty**"], [
        claim.phrase for claim in found
    ]
    claim = found[0]
    assert stated(claim.number) != expected(claim.noun, claim.number)

    # The green half of this shape, spelled from the set itself so it moves when
    # the set does rather than being a second place to correct.
    correct = tmp_path / "correct.md"
    correct.write_text(
        f"A process publishes every capability: **{SPELLED[capability_count()]}**.\n",
        encoding="utf-8",
    )
    passing = _claims_in(correct, correct.read_text(encoding="utf-8"))
    assert passing, "the correct sentence was not read at all, so the rule proves nothing"
    assert all(stated(c.number) == expected(c.noun, c.number) for c in passing)


def test_a_correct_claim_of_every_shape_passes(tmp_path: Path) -> None:
    """The green half. A rule that flagged every number would prove nothing.

    The cardinals come from `SPELLED` rather than from `_UNITS`, and that is the
    boundary this module's own note on `SPELLED` predicted: `_UNITS` is dense
    from zero to nineteen and the capability set reached twenty in WP-23, so the
    bare index raised `IndexError` — a refusal rather than a false pass, which is
    the direction it was built to fail in. `SPELLED` is the inverse of the
    *built* cardinal map and so keeps spelling past every boundary the map
    itself covers. `_ORDINAL_UNITS` is still indexed directly, because it is a
    written tuple whose next boundary announces itself the same way this one did.
    """
    planted = tmp_path / "planted.md"
    planted.write_text(
        f"The set is closed at {SPELLED[capability_count()]}. There are "
        f"{SPELLED[capability_count()]} capability names and "
        f"{SPELLED[purpose_count()]} purposes, so a "
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


#: `added six, \`entities.search\`, \`entities.get\`, ...` — a spelled number
#: followed immediately by the list it counts, with no noun between them.
#:
#: `CLAIM` cannot read this shape: it requires a noun after the number, and here
#: the number is followed by a comma. That is not a hypothetical. `README.md`
#: said "the later Relationship Intelligence entity plane added **five**,
#: \`entities.search\`, ..." while three other sentences in the same file said
#: six, and the ninth review found it by reading rather than by any guard.
#:
#: This rule needs no domain set at all, which is what makes it worth having: a
#: sentence that states a number and then enumerates the members is checkable
#: against *itself*. A miscount here is arithmetic, not a claim about the world.
_COUNTED_LIST = re.compile(
    # Cardinals only. Ordinals were admitted by `_NUMBER` and produced a false
    # offence on ordinary prose — `First, \`a\` and \`b\` are read.` counts
    # nothing and was reported as a miscount of two.
    rf"\b(?P<number>{_READ_CARDINALS_PATTERN}),\s+"
    r"(?P<items>`[^`]+`(?:,\s+`[^`]+`)+(?:,?\s+and\s+`[^`]+`)?)",
    re.IGNORECASE,
)

_CODE_SPAN = re.compile(r"`[^`]+`")


def counted_lists() -> list[tuple[str, str, int, int]]:
    r"""Every ``N, `a`, `b`, ... and `c` `` in the swept corpus."""
    found: list[tuple[str, str, int, int]] = []
    for path in swept_files():
        text = path.read_text(encoding="utf-8")
        for match in _COUNTED_LIST.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            found.append(
                (
                    f"{path.name}:{line}",
                    match.group("number"),
                    stated(match.group("number")),
                    len(_CODE_SPAN.findall(match.group("items"))),
                )
            )
    return found


COUNTED_LISTS = counted_lists()


def test_the_sweep_found_a_counted_list_to_check() -> None:
    """An anti-vacuity floor, and an honest note about how far this rule reaches.

    **It binds one sentence.** The tenth review measured the population across
    787 swept files and found exactly one real claim — `README.md:30`, the
    sentence it was written for — plus a spurious ordinal match that the pattern
    now excludes. A rule with a population of one is worth having (it is the
    shape `CLAIM` structurally cannot read, and the defect it caught was live)
    and is not worth describing as a sweep.

    The floor stays at one because one is the truth. If it ever reads zero, the
    pattern has gone stale rather than the corpus having improved.

    **What it does not read, stated rather than implied.** A comma between the
    number and the list, and two or more items. Writing the same claim with a
    colon or an em dash defeats it.

    Admitting them was tried and withdrawn. The separators were widened together
    (`[,:—-]`) with a one-or-more item pattern, and four false findings followed;
    the withdrawal note then blamed the em dash and quoted an em-dash example.
    The eleventh review isolated them and that attribution is wrong: with the
    shipped two-or-more-item pattern, admitting the em dash alone produces no
    false finding, and it is the **colon** that produces one —
    `tests/architecture/test_principal_is_never_caller_supplied.py:684`, where
    "two: `first = metadata`, `second = first`, `second.principal_id`" counts
    three spans against a stated two and is not a miscount of anything. Corrected
    here rather than left, because a withdrawal note that misnames its own reason
    is the shape this module exists to catch.
    """
    assert COUNTED_LISTS, (
        "no `<number>, `a`, `b`` claim parsed from the swept corpus; the pattern "
        "has gone stale and this rule is deciding nothing"
    )


def test_every_number_followed_by_its_list_matches_that_list() -> None:
    """The shape `CLAIM` structurally cannot see, checked against itself.

    Deliberately *not* checked against a domain set: what makes this rule safe
    to state broadly is that both halves are in the sentence. If a list is
    genuinely partial the sentence should say so in words ("six, among them
    `a` and `b`"), which this pattern does not match, rather than by stating a
    number the reader is expected to disbelieve.
    """
    wrong = sorted(
        f"{where} says {stated_count} and then lists {listed}"
        for where, _, stated_count, listed in COUNTED_LISTS
        if stated_count != listed
    )
    assert wrong == [], (
        f"{wrong}. A sentence that states a count and then enumerates the "
        "members has to agree with itself."
    )


def test_no_excused_entry_excuses_more_than_one_claim() -> None:
    """An entry excuses one occurrence, which is what `EXCUSED` says it does.

    It did not. `Claim.excused_by` matches `context` against the whole block a
    claim sits in, and `tests/unit/test_policy.py`'s `PERMITTED_PAIRS` is a
    single assignment holding several of these comments — so the entry written
    for "All five capabilities" at line 236 also excused an identical phrase at
    line 259, where it sat above **six** enumerated pairs. That is the same
    defect this campaign corrected in `README.md` one commit earlier, hidden by
    the mechanism built to keep the allowlist honest.

    The phrases are distinct again, but distinctness was never enforced. This is
    what enforces it: an entry covering two claims is ambiguous by construction,
    because nothing decides which of the two the recorded reason describes.
    """
    covered: dict[tuple[str, str, str, str], list[str]] = {}
    for claim in CLAIMS:
        entry = claim.excused_by()
        if entry is not None:
            covered.setdefault(entry, []).append(claim.where)

    ambiguous = sorted(
        f"{entry[0]} {entry[1]!r} excuses {len(where)}: {', '.join(where)}"
        for entry, where in covered.items()
        if len(where) > 1
    )
    assert ambiguous == [], (
        f"{ambiguous}. Give each occurrence its own entry with a `context` that "
        "tells them apart, so the recorded reason belongs to one sentence."
    )
