"""Claims attributed to the canonical package must be supported by it.

This guards one recurring defect, stated as a shape rather than as a list of
past mistakes: *the plan asserts that some identifier or wording comes from the
ratified canonical product definition, and the package does not contain it.*

It has now occurred three times, each time surviving into a commit and each time
found by a human-equivalent reader rather than by a check:

- `Entity` was given as the canonical target for `Person` and `Organization`.
  The ratified model has no `Entity`; both are first-class. The claim came from
  the superseded `my-pa vNext` document.
- `ContextLink` was then given as the canonical target for project association,
  on the strength of appearing in `09`'s *Supporting records* list — a list of
  bare names with no definitions. Appearing in that list is not a definition,
  and this was introduced by the commit that fixed `Entity`.
- An `Assertion` trust ladder ("Confirmed, Strongly Supported, Probable,
  Possible, Unverified…") was given to WP-7 as an instruction. None of those
  values appear anywhere in the package.

Every one of those is the same failure with a different noun, and prose review
kept catching them one at a time. The counts in section 14 went the other way:
once `test_open_decision_counts.py` derived them, that class never regressed.
This test extends the same treatment to the object-model mapping.

What it does NOT do: judge whether a mapping is *apt*. `Capture` → `Capture` and
`Capture` → `Receipt` are equally well-supported by existence alone. Aptness
still needs a reader. What this removes is the failure mode where the target
does not exist in the document at all, which is what actually kept happening.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs" / "plans" / "mcv-completion-plan.md"
MIRROR = ROOT / "docs" / "specs" / "canonical-product-definition"
OBJECT_MODEL = MIRROR / "09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md"

MAPPING_HEADER = "| Built here | Canonical object | Note |"

#: Words that appear backticked in the canonical-object column but name a
#: repository or plan concept rather than a canonical object. Each is listed
#: with its reason so a future narrowing has to state one too.
NOT_CANONICAL_OBJECTS = {
    "v1": "the repository's contract version, not an object",
    "D-09": "a plan decision ID",
    "R0": "a canonical roadmap stage, checked by other means",
    "R1": "a canonical roadmap stage, checked by other means",
}


def _mirror_text() -> str:
    """Every byte of the mirrored package, concatenated."""
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(MIRROR.iterdir()) if p.is_file())


def _mapping_rows() -> list[tuple[str, str, str]]:
    """The section 12 object-model mapping table, as (built, canonical, note)."""
    lines = PLAN.read_text(encoding="utf-8").splitlines()
    rows: list[tuple[str, str, str]] = []
    in_table = False
    for line in lines:
        if line.strip() == MAPPING_HEADER:
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            if line.startswith("|---"):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 3:
                rows.append((cells[0], cells[1], cells[2]))
    return rows


def _claimed_objects() -> list[tuple[str, str]]:
    """Backticked identifiers claimed as canonical objects, with their row."""
    claimed: list[tuple[str, str]] = []
    for built, canonical, _note in _mapping_rows():
        for token in re.findall(r"`([A-Za-z][A-Za-z0-9_.-]*)`", canonical):
            if token in NOT_CANONICAL_OBJECTS:
                continue
            claimed.append((token, built))
    return claimed


def test_mapping_table_is_present_and_populated() -> None:
    """Guard the parser: an empty table would make every check below vacuous."""
    assert MAPPING_HEADER in PLAN.read_text(encoding="utf-8"), (
        f"The section 12 mapping table header {MAPPING_HEADER!r} is gone from "
        f"{PLAN.name}. Every check in this module is keyed on it and would "
        "otherwise pass by parsing nothing. Fix the header or fix this test."
    )
    rows = _mapping_rows()
    assert len(rows) >= 5, (
        f"Parsed only {len(rows)} rows from the section 12 mapping table. Either "
        "the table moved or its header changed; fix this test alongside it."
    )
    assert _claimed_objects(), "No canonical objects parsed out of the table."


def _defined_objects() -> set[str]:
    """Names `09` actually defines, as `- **Name:** …` under *Definitions*."""
    model = OBJECT_MODEL.read_text(encoding="utf-8")
    return set(re.findall(r"^- \*\*([A-Za-z][A-Za-z0-9_]*)[:\*]", model, re.MULTILINE))


def _bare_names() -> set[str]:
    """Names `09` lists under *Supporting records* without defining them."""
    model = OBJECT_MODEL.read_text(encoding="utf-8")
    match = re.search(
        r"^## Supporting records\s*\n\s*(.+?)\n\s*\n", model, re.DOTALL | re.MULTILINE
    )
    if not match:
        return set()
    names = {n.strip().rstrip(".").strip() for n in match.group(1).split(",")}
    return {n for n in names if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", n)}


#: Wording that acknowledges a target rests on something weaker than a `09`
#: definition. A row using a bare name must say so and cite its real basis.
BARE_NAME_DISCLOSURES = ("without definitions", "bare name", "Supporting records")

#: Wording with which a note *disowns* the name it sits next to: the note is
#: saying that name is unsupported, not that it is the target. The plan writes
#: its own corrections this way — "`Entity` does not exist in the ratified
#: model", "`ContextLink` … is defined nowhere" — so the set of disowned names
#: is derived from the prose rather than listed here, and a future correction
#: written in the same voice is covered without editing this test.
DISOWNING_PHRASES = (
    "does not exist",
    "do not exist",
    "defined nowhere",
    "appears nowhere",
    "appear nowhere",
    "asserted rather than derived",
    "inferred rather than derived",
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_BACKTICKED = re.compile(r"`([A-Za-z][A-Za-z0-9_.-]*)`")


def _disowned_names() -> dict[str, str]:
    """Names the notes declare unsupported, mapped to the wording that does it.

    A disowning phrase is attributed to the nearest backticked name to its left
    *within the same sentence*. That scoping matters: the sentence that retires
    `Entity` goes on to say `Person` and `Organization` are first-class, and a
    note-wide match would sweep those two in as well.
    """
    disowned: dict[str, str] = {}
    for _built, _canonical, note in _mapping_rows():
        for sentence in _SENTENCE.split(note):
            lowered = sentence.lower()
            for phrase in DISOWNING_PHRASES:
                index = lowered.find(phrase)
                if index == -1:
                    continue
                preceding = [m for m in _BACKTICKED.finditer(sentence) if m.end() <= index]
                if preceding:
                    disowned.setdefault(preceding[-1].group(1), sentence.strip())
    return disowned


def _note_for(row: str) -> str:
    """The Note cell of the row whose *Built here* cell is `row`."""
    return next((note for built, _c, note in _mapping_rows() if built == row), "")


def test_object_model_parses_into_defined_and_bare_names() -> None:
    """Guard the two `09` readings the defined/bare distinction rests on.

    If either regex stopped matching — a heading reworded, the *Definitions*
    bullets restyled — the checks below would not fail, they would stop having
    an opinion. An empty *Supporting records* set in particular makes the
    disclosure rule unreachable while every test still reports green.
    """
    defined = _defined_objects()
    bare = _bare_names()
    assert len(defined) >= 20, (
        f"Parsed only {len(defined)} definitions out of {OBJECT_MODEL.name}. Its "
        "'## Definitions' bullets must have changed shape; re-derive the regex."
    )
    assert len(bare) >= 10, (
        f"Parsed only {len(bare)} names out of {OBJECT_MODEL.name}'s "
        "'## Supporting records' paragraph. Without them nothing can be "
        "recognised as undefined and the disclosure rule below never applies."
    )
    assert not (defined & bare), (
        "Names appear both as `09` definitions and in its 'Supporting records' "
        f"list: {sorted(defined & bare)}. The two readings must stay disjoint "
        "for 'defined' versus 'bare' to mean anything."
    )


def test_the_notes_still_disown_something() -> None:
    """Guard the disowning reader, which is what catches a reinstated name.

    The plan currently retires two names in prose. If that wording is reworded
    past `DISOWNING_PHRASES`, the reinstatement check goes quiet rather than
    red — which is the failure mode this whole module exists to remove.
    """
    disowned = _disowned_names()
    assert disowned, (
        "No disowned name was read out of the mapping table's notes. The plan "
        "retires names in prose ('`Entity` does not exist in the ratified "
        "model'), and that wording is how a reinstated name is caught. Either "
        "the notes were reworded past DISOWNING_PHRASES or the table stopped "
        "parsing; update this test deliberately, not by watching it pass."
    )


@pytest.mark.parametrize("token,row", _claimed_objects())
def test_claimed_canonical_object_exists_in_the_package(token: str, row: str) -> None:
    """Every object the mapping names must appear in the mirrored package.

    `Entity` failed this: it came from the superseded vNext document and appears
    nowhere in the package.
    """
    assert re.search(rf"\b{re.escape(token)}\b", _mirror_text()), (
        f"The mapping table maps {row!r} onto canonical object `{token}`, but "
        f"`{token}` appears nowhere in docs/specs/canonical-product-definition/. "
        "Either it came from the superseded vNext document, or it was inferred "
        "rather than derived. Re-derive the row from "
        "09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md."
    )


@pytest.mark.parametrize("token,row", _claimed_objects())
def test_undefined_target_discloses_that_it_is_undefined(token: str, row: str) -> None:
    """A bare name in *Supporting records* is not a derivation on its own.

    Existence alone is too weak a bar, and this is not hypothetical: the commit
    that removed `Entity` introduced `ContextLink`, which *is* in the package —
    but only as one comma-separated token in a list of names `09` never defines.
    An existence check passes it. What separates it from the legitimate case is
    disclosure: `SourceSpan` is equally undefined in `09`, and the row that uses
    it says so and cites `10`'s *Text spans* section for the real basis.

    So the rule is: use a defined name, or say plainly that you are not.
    """
    if token in _defined_objects():
        return
    if token not in _bare_names():
        return  # covered by the existence test above
    note = _note_for(row)
    assert any(phrase in note for phrase in BARE_NAME_DISCLOSURES), (
        f"The mapping table maps {row!r} onto `{token}`, which 09 lists under "
        "'Supporting records' but never defines. Appearing in that list is not a "
        "derivation. Either map onto a name 09 defines, or state in the row's "
        "note that the name is undefined there and cite what actually supports "
        f"it — as the `SourceSpan` row does. Current note: {note[:120]!r}"
    )


@pytest.mark.parametrize("token,row", _claimed_objects())
def test_claimed_object_is_not_one_the_notes_disown(token: str, row: str) -> None:
    """A note that retires a name cannot also be the licence to use it.

    This is the hole the disclosure test above cannot close on its own. That
    test reads the note as a whole, because the `SourceSpan` row discloses with
    "Both names appear … without definitions" and never repeats `SourceSpan`
    itself — so disclosure cannot be tied to the token. The consequence is that
    a note *explaining why a name was removed* reads, to a whole-note check,
    exactly like a note disclosing that the name is weakly supported. Putting
    `ContextLink` back into the canonical column of the very row whose note
    retires it therefore slips through: the phrases "bare name" and "Supporting
    records" are right there, describing the removal.

    What separates the two is direction. The `SourceSpan` note discloses a
    weakness and then supplies the basis anyway. The `ContextLink` sentence says
    the name "exists only as a bare name … is defined nowhere, and was asserted
    rather than derived" — it is a repudiation. A row may not claim a name its
    own table has repudiated, whatever else the note says.
    """
    disowned = _disowned_names()
    if token not in disowned:
        return
    where = "09 lists it under 'Supporting records' but never defines it"
    if token not in _bare_names():
        where = "it appears nowhere in the ratified package"
    pytest.fail(
        f"The mapping table maps {row!r} onto canonical object `{token}`, but "
        f"the table's own notes disown `{token}`: {where}. The note says: "
        f"{disowned[token]!r} A name the plan has retired cannot be reinstated "
        "as a canonical target by a note that is still explaining why it was "
        "retired. Map onto a name 09 defines, or re-derive the row from "
        "09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md and rewrite the note."
    )


#: The sentence in section 12 that introduces the quoted state vocabularies.
#: Matched with `\s+` for the line wrap, so reflowing the paragraph is safe.
STATE_SET_INTRO = re.compile(r"The ratified state\s+sets are:\s*\n\n(.+?)\n\n", re.DOTALL)


def _quoted_state_sets() -> list[tuple[str, tuple[str, ...]]]:
    """The state vocabularies section 12 quotes, read out of the plan itself.

    Previously these two lists were hard-coded here, which checked the *test's*
    copy of them against `09` and left the plan's copy unbound: editing a value
    in section 12 produced no signal at all. They are now derived the way
    `test_open_decision_counts.py` derives its counts — from the prose that makes
    the claim — so the claim is what gets checked.
    """
    match = STATE_SET_INTRO.search(PLAN.read_text(encoding="utf-8"))
    if not match:
        return []
    sets: list[tuple[str, tuple[str, ...]]] = []
    for bullet in re.findall(r"^- (.+?)(?=\n- |\Z)", match.group(1), re.MULTILINE | re.DOTALL):
        named = re.match(r"`([A-Za-z][A-Za-z0-9_]*)`:\s*(.+)", re.sub(r"\s+", " ", bullet).strip())
        if not named:
            continue
        values = tuple(v for v in (c.strip().strip("`;. ") for c in named.group(2).split(",")) if v)
        sets.append((named.group(1), values))
    return sets


QUOTED_STATE_SETS = _quoted_state_sets()


def test_quoted_state_sets_were_read_out_of_the_plan() -> None:
    """Guard the parser: an empty parse would make the check below vacuous.

    `pytest.mark.parametrize` over an empty list reports as skipped, not failed,
    so without this the whole state-set check could disappear silently the moment
    section 12 reworded its lead-in.
    """
    assert len(QUOTED_STATE_SETS) >= 2, (
        f"Parsed {len(QUOTED_STATE_SETS)} state sets out of {PLAN.name}. Section "
        "12 quotes the ratified `Proposal` and `Assertion` vocabularies after "
        "'The ratified state sets are:'; either that lead-in or the bullet shape "
        "changed. Fix the parser deliberately, not by watching it pass."
    )
    thin = [name for name, values in QUOTED_STATE_SETS if len(values) < 5]
    assert not thin, (
        f"State sets parsed with fewer than five values: {thin}. A truncated "
        "parse would check a prefix and call it verbatim."
    )


@pytest.mark.parametrize("object_name,values", QUOTED_STATE_SETS)
def test_quoted_state_sets_are_verbatim_from_the_object_model(
    object_name: str, values: tuple[str, ...]
) -> None:
    """The state vocabularies the plan gives WP-7 must be the ratified ones.

    The plan previously handed WP-7 a trust ladder that existed only in the
    superseded document. The object name is checked along with its values, so a
    correct list attached to the wrong object fails too.
    """
    normalized_model = re.sub(r"\s+", " ", OBJECT_MODEL.read_text(encoding="utf-8"))
    quoted = f"{object_name}: {', '.join(values)}"
    assert quoted in normalized_model, (
        f"Section 12 quotes '{quoted}' as the ratified state set, but it does not "
        "appear verbatim in 09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md's 'State "
        "patterns' section. Re-derive the plan's list from the package."
    )


def test_superseded_vocabulary_is_not_presented_as_canonical() -> None:
    """The vNext trust ladder must not reappear as a canonical claim.

    Its terms may still be named in the plan — the correction record quotes them
    to say they are wrong — so this asserts the narrower thing that matters: no
    term of that ladder appears inside the mapping table itself.
    """
    ladder = ["Strongly Supported", "Probable", "Possible", "Confirmed"]
    table = "\n".join(" | ".join(row) for row in _mapping_rows())
    found = [term for term in ladder if term in table]
    assert not found, (
        f"Superseded vNext trust-state terms are back inside the mapping table: "
        f"{found}. The ratified sets are in 09's 'State patterns' section."
    )
