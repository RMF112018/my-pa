"""The pipeline's pure derivations, on FAST, where they belong.

`P-02`'s offset mapping, `P-03`'s detection, `P-04`'s segmentation, `P-05`'s
matchers, `P-08`'s normalization and `P-09`'s drafts are functions of one string.
They need no server, so they are here rather than in the `database` tier — and
they are the layer that makes the tier's assertions about *rows* short, because
the arithmetic they rest on has already been checked.

**Determinism is asserted directly**, and not only through the replay tests: the
whole `QC-AC-035` argument is that a stage is a function of the immutable version
and nothing else, and the cheapest place to break that is a matcher that iterates
a set. Every derivation here is run twice over the same text and compared.

No database, no network, no path. Every fixture is synthetic
(`QC-AC-073`, `AGENTS.md` section 5).
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from my_pa.domain.capture.classification import CaptureLabel
from my_pa.domain.capture.proposal import ProposalField, ProposalType, RiskClass
from my_pa.infrastructure.jobs.capture_pipeline import (
    SegmentKind,
    commitment_cues,
    derive,
    detect_language,
    normalize_text,
    normalized_moments,
    segment_text,
    text_matches,
    work_object_drafts,
)

#: One note carrying every match kind, so a single fixture exercises the whole
#: matcher set rather than one rule at a time.
NOTE = (
    "Buyout review 2026-09-14.\n"
    "I will send the RFI-0421 response and the $12,500.00 revision by Friday.\n"
    "> I will handle the PRJ-0007 paperwork.\n"
    "See https://example.invalid/rfi/0421.\n"
)


def test_the_offset_mapping_is_reversible_over_every_normalized_offset() -> None:
    """`P-02`: every normalized offset maps back to the original it came from.

    Checked across the whole string rather than at a sample, because a mapping
    that is right at the edges and wrong in a run is exactly what a spot check
    misses. `10_…:89` — no proposal may cite only normalized text — is what makes
    this load-bearing rather than tidy.
    """
    original = "a \u00a0b\r\nc\td e"  # a space, a no-break space, a CRLF, and a tab
    normalized, mapping = normalize_text(original)
    assert normalized == "a b\nc d e"

    for offset, character in enumerate(normalized):
        origin = mapping.original_offset_of(offset)
        assert 0 <= origin < len(original)
        if character not in {" ", "\n"}:
            assert original[origin] == character, (
                f"normalized offset {offset} ({character!r}) maps to "
                f"{original[origin]!r} in the original"
            )

    with pytest.raises(ValueError, match="outside this mapping"):
        mapping.original_offset_of(len(normalized) + 5)


def test_normalization_changes_no_character_that_carries_meaning() -> None:
    """`11_…:61`: nothing is translated, folded, or transliterated silently.

    Only whitespace moves. Case, punctuation and accents are untouched, which is
    what lets a span measured against processing text be carried back and still
    re-derive against the version.
    """
    original = "Café — RFI-0421 (¥1,000)? Yes."
    normalized, _ = normalize_text(original)
    assert normalized == original


def test_a_language_is_detected_or_reported_unknown() -> None:
    """`P-03`: `unknown` is a real answer, and both answers are reachable."""
    assert detect_language("the meeting will be with the team and that is that") == "en"
    assert detect_language("RFI-0421") == "unknown"


def test_a_quoted_region_is_segmented_as_quoted() -> None:
    """`P-04`, and the clause the plan drops: quoted and pasted regions.

    The three kinds this build decides are all reachable in one fixture, and the
    quoted one is asserted by offset so that a segmenter which labelled the whole
    document `quoted` would fail rather than pass.
    """
    segments = segment_text("A paragraph.\n- a bullet\n> a quote\n```\nfenced\n```\n")
    kinds = [segment.kind for segment in segments]
    assert SegmentKind.PARAGRAPH in kinds
    assert SegmentKind.BULLET in kinds
    assert kinds.count(SegmentKind.QUOTED) >= 3, f"quoted regions were not marked: {kinds}"
    assert segments[0].kind is SegmentKind.PARAGRAPH


def test_every_deterministic_match_kind_is_found_with_its_label() -> None:
    """`P-05`: five labels, each produced by a rule and each carrying offsets.

    `11_…:81` requires the authority classification beside the match — a match
    with no statement of what kind of fact it is, is a fact nobody can act on —
    so the labels are what is asserted rather than the count.
    """
    matches = text_matches(NOTE)
    assert matches, "the matcher found nothing in a note built to exercise it"
    found = {match.label for match in matches}
    assert found == set(CaptureLabel), f"only {sorted(label.value for label in found)} were found"

    for match in matches:
        assert 0 <= match.start_offset < match.end_offset <= len(NOTE)

    amounts = [m for m in matches if m.label is CaptureLabel.FINANCIAL_MENTION]
    assert [m.normalized_value for m in amounts] == ["12500.00"]
    dates = [m for m in matches if m.label is CaptureLabel.DATE_MENTION]
    assert "2026-09-14" in {m.normalized_value for m in dates}


def test_matches_do_not_overlap_and_are_ordered() -> None:
    """Two rules cannot both claim one run of text and produce two labels for it.

    Ordering is not cosmetic: the stage digest is taken over this tuple, so an
    unstable order would make the same text replay to a different digest and
    `QC-AC-035` would be false for a reason nobody could see.
    """
    matches = text_matches(NOTE)
    for earlier, later in pairwise(matches):
        assert earlier.end_offset <= later.start_offset, f"{earlier} overlaps {later}"
        assert earlier.start_offset < later.start_offset


def test_a_relative_moment_is_recorded_without_being_resolved() -> None:
    """`P-08`: the raw phrase is preserved and the ambiguity is recorded, not settled.

    "Friday" has no answer without a clock, and a stage that read one would stop
    being replayable — which is the property `QC-AC-035` rests on. So it is a
    date mention with **no** normalized value, beside an absolute date that
    **has** one. Both in this test, because the empty value only means
    "unresolved" if a resolved one is possible.
    """
    moments = normalized_moments(NOTE, text_matches(NOTE))
    values = {moment.normalized_value for moment in moments}
    assert "2026-09-14" in values, (
        "no absolute date was resolved, so the None below is not a choice"
    )
    assert None in values, "the relative phrase was resolved, or was not recognised at all"

    for moment in moments:
        assert NOTE[moment.start_offset : moment.end_offset], "a moment span covers nothing"


def test_an_ambiguous_numeric_date_is_not_resolved_to_either_reading() -> None:
    """`03/04/2026` is two dates, and choosing one would invent a fact.

    The control is beside it: the ISO form *is* resolved, so "not resolved" is a
    decision about ambiguity rather than a parser that resolves nothing.
    """
    ambiguous = text_matches("Due 03/04/2026.")
    assert not [m for m in ambiguous if m.label is CaptureLabel.DATE_MENTION]
    resolved = text_matches("Due 2026-03-04.")
    assert [m.normalized_value for m in resolved if m.label is CaptureLabel.DATE_MENTION] == [
        "2026-03-04"
    ]


def test_a_pasted_cue_becomes_a_follow_up_and_the_users_own_a_commitment() -> None:
    """`P-09` reading `P-04`'s structure, which is `QC-AC-042`'s structural half.

    Both in one test, because the distinction is the assertion: a commitment
    somebody else wrote and the user pasted is not the user's commitment, and a
    build that produced the same type for both would have recorded the quoting
    and then ignored it.
    """
    drafts = work_object_drafts(
        text_matches(NOTE), segment_text(NOTE), normalized_moments(NOTE, text_matches(NOTE))
    )
    assert drafts, "the note carries commitment cues and produced no draft"
    types = [draft.proposal_type for draft in drafts]
    assert ProposalType.COMMITMENT in types
    assert ProposalType.FOLLOW_UP in types, (
        "the cue inside the quoted region was typed as the user's own commitment"
    )


def test_a_draft_records_the_fields_it_could_not_fill() -> None:
    """`11_…:131`'s "missing required fields", which is what keeps a partial honest.

    The actor, the counterparty and the status need a resolver this build does
    not have, so all three are reported absent. The action is present because the
    cue *is* the action. Asserted as an exact set, so a build that quietly filled
    one in would fail here rather than ship an invented complete record.
    """
    drafts = work_object_drafts(
        text_matches(NOTE), segment_text(NOTE), normalized_moments(NOTE, text_matches(NOTE))
    )
    for draft in drafts:
        assert ProposalField.ACTION not in draft.missing_fields
        assert {ProposalField.ACTOR, ProposalField.COUNTERPARTY, ProposalField.STATUS} <= set(
            draft.missing_fields
        ), f"a draft claimed a field no rule can fill: {draft.missing_fields}"


def test_a_cue_beside_an_amount_is_recorded_at_a_higher_risk_class() -> None:
    """The risk class is a rule, and both of its outcomes are reachable."""

    def draft_for(note: str) -> RiskClass:
        drafts = work_object_drafts(
            text_matches(note), segment_text(note), normalized_moments(note, text_matches(note))
        )
        assert len(drafts) == 1, f"expected one draft from {note!r}, got {drafts}"
        return drafts[0].risk_class

    assert draft_for("I will send the summary.") is RiskClass.LOW
    assert draft_for("I will approve the $12,500.00 change.") is RiskClass.MODERATE


def test_a_commitment_cue_is_matched_without_folding_the_text() -> None:
    """The cue comparison folds a copy; the offsets index the original.

    A span measured from a folded string would point into text that does not
    exist, and would then fail to re-derive against the version — the
    `QC-AC-011` failure, arriving from `P-05`.
    """
    note = "We WILL send it. i will too."
    cues = sorted(commitment_cues(note), key=lambda cue: cue.start_offset)
    assert len(cues) == 2, f"the cue match is case-sensitive: {cues}"

    # Each span points into the original, with the original's own casing — which
    # is what a folded-string match would have destroyed.
    assert [note[cue.start_offset : cue.end_offset] for cue in cues] == ["We WILL", "i will"]


def test_every_derivation_is_the_same_twice_over_the_same_text() -> None:
    """Determinism, asserted where it is cheapest to break.

    `QC-AC-035` rests on a stage being a function of the version and nothing
    else, and the replay tests measure that against a server. This measures the
    same property against the functions themselves, so a matcher that iterated a
    set — a defect a single database run would not reliably show — fails on FAST.
    """
    first, second = derive(NOTE), derive(NOTE)
    assert first == second, "two derivations over one immutable text disagree"
    assert first.matches, "the derivation produced nothing, so the equality is vacuous"
    assert first.drafts, "the derivation produced no draft, so the equality is partly vacuous"
