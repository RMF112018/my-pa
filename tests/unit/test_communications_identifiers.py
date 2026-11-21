"""`comms_identifiers_v1`: technical identifiers, with near-miss negatives."""

from __future__ import annotations

import pytest

from my_pa.domain.communications.identifiers import (
    IDENTIFIER_VERSION,
    IdentifierKind,
    TechnicalIdentifier,
    extract_identifiers,
)

K = IdentifierKind


def normalized(text: str) -> set[str]:
    return {identifier.normalized for identifier in extract_identifiers(text)}


def test_the_version_is_named() -> None:
    assert IDENTIFIER_VERSION == "comms_identifiers_v1"


@pytest.mark.parametrize(
    "text",
    ["RFI 174", "RFI-174", "RFI #174", "RFI# 174", "RFI No. 174", "RFI no 174", "rfi 174",
     "RFI174", "(RFI 174)", "re: RFI 174.", "RFI 0174"],
)  # fmt: skip
def test_rfi_forms_normalize_to_one_identifier(text: str) -> None:
    assert normalized(text) == {"rfi:174"}


@pytest.mark.parametrize("text", ["RFI 1740", "RFI 174.1", "RFI 174-2", "XRFI 174", "RFI1 74"])
def test_rfi_174_is_not_found_inside_a_longer_token(text: str) -> None:
    assert "rfi:174" not in normalized(text)


@pytest.mark.parametrize("text", ["RFI 1,740", "CB 1,250", "CO 2,500", "Submittal 3,100"])
def test_a_thousands_separator_never_yields_the_leading_group(text: str) -> None:
    # R1's probe 7: `RFI 1,740` was `rfi:1`.
    assert normalized(text) == set()


def test_a_comma_before_a_space_still_ends_the_number() -> None:
    assert normalized("RFI 174, RFI 175") == {"rfi:174", "rfi:175"}


def test_a_query_for_rfi_17_does_not_match_rfi_174() -> None:
    query = normalized("RFI 17")
    assert query == {"rfi:17"}
    assert not query & normalized("Please see RFI 174")
    assert query <= normalized("Please see RFI-17 and RFI 174")


def test_leading_zeros_are_dropped_for_integer_kinds() -> None:
    assert normalized("RFI 000") == {"rfi:0"}
    assert normalized("CB #002") == {"cb:2"}


@pytest.mark.parametrize("text", ["CB #2", "CB 2", "CB-2", "CB No. 2"])
def test_change_bulletins(text: str) -> None:
    assert normalized(text) == {"cb:2"}


@pytest.mark.parametrize("text", ["CB2", "cb 2", "XCB 2", "CB 23"])
def test_change_bulletin_near_misses(text: str) -> None:
    assert "cb:2" not in normalized(text)


@pytest.mark.parametrize("text", ["CO #5", "CO 5", "CO-5", "CO No. 5"])
def test_change_orders(text: str) -> None:
    assert normalized(text) == {"co:5"}


@pytest.mark.parametrize("text", ["CO2 levels", "co 5", "PCO 5", "COR 5", "CO 55"])
def test_change_order_near_misses(text: str) -> None:
    assert "co:5" not in normalized(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Submittal 12", "submittal:12"),
        ("submittal #12", "submittal:12"),
        ("Submittal No. 05.12", "submittal:05.12"),
        ("Submittal 033000-01", "submittal:033000-01"),
        ("Submittal 033000-01.", "submittal:033000-01"),
    ],
)
def test_submittals_keep_their_number_verbatim(text: str, expected: str) -> None:
    assert expected in normalized(text)


@pytest.mark.parametrize("text", ["Submittals 12", "Submittal twelve", "resubmittal 12x"])
def test_submittal_near_misses(text: str) -> None:
    assert not any(n.startswith("submittal:") for n in normalized(text))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The GMP is final", {"gmp"}),
        ("both GMPs and the GMP's terms", {"gmp"}),
        ("FPL outage; FPLs", {"fpl"}),
        ("GMP/FPL", {"fpl", "gmp"}),
    ],
)
def test_bare_acronyms(text: str, expected: set[str]) -> None:
    assert normalized(text) == expected


@pytest.mark.parametrize("text", ["gmp", "GMPX", "aGMP", "FPLX", "GMPS", "fpl"])
def test_bare_acronym_near_misses(text: str) -> None:
    assert normalized(text) == set()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Section 03 30 00.13 applies", "spec:033000.13"),
        ("Spec 033000", "spec:033000"),
        ("Section #033000", "spec:033000"),
        ("Specification 099123", "spec:099123"),
    ],
)
def test_spec_sections(text: str, expected: str) -> None:
    assert normalized(text) == {expected}


@pytest.mark.parametrize(
    "text",
    [
        "Call 561 555 0123",
        "call (561) 555-0123",
        "561-555-0123",
        "at 10:30:00",
        "on 2026-11-20",
        "on 11/20/26",
        "PO 033000",
        "zip 33401",
        "03 30 00 12 34",
        "1 03 30 00",
        "93 30 00",
        "03 30 00.135",
        "Section 0330001",
    ],
)
def test_spec_section_false_positives_are_rejected(text: str) -> None:
    for opt_in in (False, True):
        found = extract_identifiers(text, include_uncued_spec_sections=opt_in)
        assert not any(i.kind is K.SPEC_SECTION for i in found), (text, opt_in)


@pytest.mark.parametrize(
    "text",
    [
        "Quote 033000 and 099123 attached",
        "ref 03 30 00 in the log",
        "job 260411 / PO 033000-1",
        "invoice 033000.13",
    ],
)
def test_bare_spec_like_numbers_yield_nothing_by_default(text: str) -> None:
    assert normalized(text) == set()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SECTION 09 91 23", {"spec:099123"}),
        ("per specs 033000", {"spec:033000"}),
        ("Sections 03 30 00 and 09 91 23", {"spec:033000"}),
        ("section no. 03 30 00.13", {"spec:033000.13"}),
    ],
)
def test_cued_spec_sections(text: str, expected: set[str]) -> None:
    assert normalized(text) == expected


def test_the_opt_in_admits_only_the_bare_spaced_form() -> None:
    text = "ref 03 30 00 and 099123"
    assert normalized(text) == set()
    found = extract_identifiers(text, include_uncued_spec_sections=True)
    assert {i.normalized for i in found} == {"spec:033000"}


def test_results_are_distinct_sorted_and_typed() -> None:
    result = extract_identifiers("RFI 2, RFI 1, RFI 2, GMP, CB #3, Submittal 7, Section 05 12 00")
    assert result == tuple(sorted(result))
    assert TechnicalIdentifier(K.RFI, "1") in result
    assert [i.normalized for i in result].count("rfi:2") == 1
    assert {i.kind for i in result} == {
        K.RFI,
        K.GMP,
        K.CHANGE_BULLETIN,
        K.SUBMITTAL,
        K.SPEC_SECTION,
    }
