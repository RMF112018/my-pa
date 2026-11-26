"""The Meeting context inputs, pure (communications intelligence WP5-S2).

The lookback window and its clipping at the read instant, the title terms
(`meeting_title_terms_v1`: the generic list, the stop words, no numbers, at
most eight) and the identifier inputs (source order, the bare kinds excluded by
ruling D4, at most twenty, the 20,000-character scan of ruling D14). Every
title and text is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from my_pa.domain.communications.identifiers import (
    IDENTIFIER_VERSION_V1,
    IdentifierKind,
    TechnicalIdentifier,
)
from my_pa.domain.meeting.context import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_PER_MEETING_LIMIT,
    ENGLISH_STOP_WORDS,
    EXCLUDED_IDENTIFIER_KINDS,
    GENERIC_MEETING_TERMS,
    IDENTIFIER_SCAN_CHARACTERS,
    MAX_CONTEXT_IDENTIFIERS,
    MAX_CONTEXT_MEETINGS,
    MAX_LOOKBACK_DAYS,
    MAX_PER_MEETING_LIMIT,
    MAX_TITLE_TERMS,
    TITLE_TERMS_RULE,
    ContextText,
    ContextTextSource,
    lookback_window,
    select_context_identifiers,
    title_terms,
)

START: Final = datetime(2026, 11, 20, 14, 30, 15, 750_000, tzinfo=UTC)
FLOOR: Final = datetime(2026, 11, 20, 14, 30, 15, tzinfo=UTC)


def _id(kind: IdentifierKind, value: str) -> TechnicalIdentifier:
    return TechnicalIdentifier(kind, value)


# ------------------------------------------------------------------ bounds


def test_the_bounds_are_the_design_values() -> None:
    assert MAX_CONTEXT_MEETINGS == 10
    assert (DEFAULT_LOOKBACK_DAYS, MAX_LOOKBACK_DAYS) == (14, 90)
    assert (DEFAULT_PER_MEETING_LIMIT, MAX_PER_MEETING_LIMIT) == (15, 50)
    assert IDENTIFIER_SCAN_CHARACTERS == 20_000
    assert MAX_CONTEXT_IDENTIFIERS == 20
    assert MAX_TITLE_TERMS == 8
    assert TITLE_TERMS_RULE == "meeting_title_terms_v1"


# ------------------------------------------------------------------ window


def test_a_past_meeting_looks_back_from_its_start_in_whole_seconds() -> None:
    window = lookback_window(START, 14, START + timedelta(days=3))
    assert window.end == FLOOR
    assert window.start == FLOOR - timedelta(days=14)
    assert window.clipped_to_now is False


def test_a_meeting_starting_now_is_not_clipped() -> None:
    window = lookback_window(START, 14, FLOOR + timedelta(microseconds=10))
    assert window.end == FLOOR
    assert window.clipped_to_now is False


def test_an_upcoming_meeting_is_clipped_at_the_read_instant() -> None:
    now = START - timedelta(days=2, microseconds=300)
    window = lookback_window(START, 14, now)
    assert window.end == now.replace(microsecond=0)
    assert window.start == FLOOR - timedelta(days=14)
    assert window.clipped_to_now is True


def test_a_meeting_beyond_the_lookback_has_a_single_instant_window() -> None:
    now = START - timedelta(days=30)
    window = lookback_window(START, 14, now)
    assert window.start == window.end == now.replace(microsecond=0)
    assert window.clipped_to_now is True


@pytest.mark.parametrize("days", [1, 90])
def test_the_lookback_bounds_are_inclusive(days: int) -> None:
    window = lookback_window(START, days, START)
    assert window.end - window.start == timedelta(days=days)


@pytest.mark.parametrize("days", [0, -1, 91])
def test_a_lookback_out_of_bounds_is_refused(days: int) -> None:
    with pytest.raises(ValueError, match="lookback_days"):
        lookback_window(START, days, START)


# ------------------------------------------------------------------ title terms


def test_title_terms_drop_generic_words_stop_words_and_numbers() -> None:
    assert title_terms("Weekly OAC coordination meeting #12 for the RFI 174 review") == (
        "oac",
        "coordination",
        "rfi",
    )


def test_title_terms_are_casefolded_distinct_and_in_first_occurrence_order() -> None:
    assert title_terms("Curtain Wall / curtain WALL mockup - Façade") == (
        "curtain",
        "wall",
        "mockup",
        "façade",
    )


def test_title_terms_are_at_most_eight() -> None:
    title = "alpha bravo charlie delta echo foxtrot golf hotel india juliet"
    assert title_terms(title) == (
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
    )


def test_a_generic_title_has_no_terms() -> None:
    assert title_terms("Weekly team sync - status update call") == ()
    assert title_terms("2026 11 20") == ()


def test_mixed_letters_and_digits_are_terms() -> None:
    assert title_terms("Level 3 L3B pour") == ("level", "l3b", "pour")


def test_the_generic_list_is_the_closed_design_list() -> None:
    assert len(GENERIC_MEETING_TERMS) == 28
    assert {"meeting", "meetings", "teams", "zoom", "prep", "touchbase"} <= GENERIC_MEETING_TERMS


def test_the_stop_words_are_the_postgresql_english_list() -> None:
    assert len(ENGLISH_STOP_WORDS) == 127
    assert {"the", "and", "for", "s", "t", "don"} <= ENGLISH_STOP_WORDS
    shipped = Path("/opt/homebrew/opt/postgresql@15/share/postgresql@15/tsearch_data/english.stop")
    if shipped.is_file():
        assert frozenset(shipped.read_text(encoding="utf-8").split()) == ENGLISH_STOP_WORDS


# ------------------------------------------------------------------ identifiers


def test_identifiers_rank_by_first_source_then_kind_and_value() -> None:
    selected = select_context_identifiers(
        {
            ContextTextSource.DESCRIPTION: ContextText("see CO #5 and RFI 9"),
            ContextTextSource.NOTES: ContextText("Submittal 033000-01 still open"),
            ContextTextSource.PREP: ContextText("RFI 9 response, CB 3"),
            ContextTextSource.TITLE: ContextText("RFI 174 coordination"),
        }
    )
    assert [(item.identifier.normalized, item.sources) for item in selected.identifiers] == [
        ("rfi:174", (ContextTextSource.TITLE,)),
        ("cb:3", (ContextTextSource.PREP,)),
        ("rfi:9", (ContextTextSource.PREP, ContextTextSource.DESCRIPTION)),
        ("submittal:033000-01", (ContextTextSource.NOTES,)),
        ("co:5", (ContextTextSource.DESCRIPTION,)),
    ]
    assert selected.scan_truncated is False


def test_the_bare_kinds_are_never_context_inputs() -> None:
    assert frozenset({IdentifierKind.GMP, IdentifierKind.FPL}) == EXCLUDED_IDENTIFIER_KINDS
    selected = select_context_identifiers(
        {ContextTextSource.TITLE: ContextText("GMP and FPL review for RFI 2")}
    )
    assert [item.identifier for item in selected.identifiers] == [_id(IdentifierKind.RFI, "2")]


def test_at_most_twenty_identifiers_are_kept() -> None:
    prep = " ".join(f"RFI {number}" for number in range(1, 31))
    selected = select_context_identifiers(
        {
            ContextTextSource.TITLE: ContextText("CO 7"),
            ContextTextSource.PREP: ContextText(prep),
        }
    )
    assert len(selected.identifiers) == MAX_CONTEXT_IDENTIFIERS
    assert selected.identifiers[0].identifier == _id(IdentifierKind.CHANGE_ORDER, "7")


def test_only_the_first_twenty_thousand_characters_are_scanned() -> None:
    head = "x" * (IDENTIFIER_SCAN_CHARACTERS - 8) + " RFI 11"
    long_text = head + " RFI 12"
    assert len(head) < IDENTIFIER_SCAN_CHARACTERS < len(long_text)
    selected = select_context_identifiers({ContextTextSource.NOTES: ContextText(long_text)})
    assert [item.identifier.normalized for item in selected.identifiers] == ["rfi:11"]
    assert selected.scan_truncated is True


def test_a_reader_capped_text_states_truncation() -> None:
    selected = select_context_identifiers(
        {ContextTextSource.PREP: ContextText("RFI 3", truncated=True)}
    )
    assert selected.scan_truncated is True
    assert [item.identifier.normalized for item in selected.identifiers] == ["rfi:3"]


def test_a_text_of_exactly_the_cap_is_not_truncated() -> None:
    text = "RFI 4 " + "y" * (IDENTIFIER_SCAN_CHARACTERS - 6)
    assert len(text) == IDENTIFIER_SCAN_CHARACTERS
    selected = select_context_identifiers({ContextTextSource.DESCRIPTION: ContextText(text)})
    assert selected.scan_truncated is False


def test_absent_fields_contribute_nothing() -> None:
    selected = select_context_identifiers(
        {ContextTextSource.TITLE: ContextText("Kickoff"), ContextTextSource.NOTES: None}
    )
    assert selected.identifiers == ()
    assert selected.scan_truncated is False


def test_the_extractor_version_is_honoured() -> None:
    text = ContextText("PCO 12 pricing")
    assert [
        item.identifier.normalized
        for item in select_context_identifiers({ContextTextSource.TITLE: text}).identifiers
    ] == ["pco:12"]
    assert (
        select_context_identifiers(
            {ContextTextSource.TITLE: text}, version=IDENTIFIER_VERSION_V1
        ).identifiers
        == ()
    )
