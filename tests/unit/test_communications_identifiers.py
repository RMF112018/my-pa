"""`comms_identifiers_v1` and `_v2`: technical identifiers, with near-miss negatives.

Every v1 case below holds for both versions (v2 keeps every v1 form and token
boundary) unless it is marked v1-only; the v2 additions, the labelled synthetic
set and query normalization are in `test_communications_identifiers_v2.py`.
"""

from __future__ import annotations

import pytest

from my_pa.domain.communications.identifiers import (
    IDENTIFIER_VERSION,
    IDENTIFIER_VERSION_V1,
    IDENTIFIER_VERSION_V2,
    IdentifierKind,
    TechnicalIdentifier,
    extract_identifiers,
)

K = IdentifierKind


def normalized(text: str, version: str) -> set[str]:
    return {identifier.normalized for identifier in extract_identifiers(text, version=version)}


@pytest.fixture(params=[IDENTIFIER_VERSION_V1, IDENTIFIER_VERSION_V2])
def version(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def test_the_versions_are_named_and_v2_is_current() -> None:
    assert IDENTIFIER_VERSION_V1 == "comms_identifiers_v1"
    assert IDENTIFIER_VERSION_V2 == "comms_identifiers_v2"
    assert IDENTIFIER_VERSION == IDENTIFIER_VERSION_V2


def test_an_unknown_version_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown identifier version"):
        extract_identifiers("RFI 1", version="comms_identifiers_v9")


@pytest.mark.parametrize(
    "text",
    ["RFI 174", "RFI-174", "RFI #174", "RFI# 174", "RFI No. 174", "RFI no 174", "rfi 174",
     "RFI174", "(RFI 174)", "re: RFI 174.", "RFI 0174"],
)  # fmt: skip
def test_rfi_forms_normalize_to_one_identifier(text: str, version: str) -> None:
    assert normalized(text, version) == {"rfi:174"}


@pytest.mark.parametrize("text", ["RFI 1740", "RFI 174.1", "RFI 174-2", "XRFI 174", "RFI1 74"])
def test_rfi_174_is_not_found_inside_a_longer_token(text: str, version: str) -> None:
    assert "rfi:174" not in normalized(text, version)


@pytest.mark.parametrize("text", ["RFI 1,740", "CB 1,250", "CO 2,500", "Submittal 3,100"])
def test_a_thousands_separator_never_yields_the_leading_group(text: str, version: str) -> None:
    # R1's probe 7: `RFI 1,740` was `rfi:1`.
    assert normalized(text, version) == set()


def test_a_comma_before_a_space_still_ends_the_number(version: str) -> None:
    assert normalized("RFI 174, RFI 175", version) == {"rfi:174", "rfi:175"}


def test_a_query_for_rfi_17_does_not_match_rfi_174(version: str) -> None:
    query = normalized("RFI 17", version)
    assert query == {"rfi:17"}
    assert not query & normalized("Please see RFI 174", version)
    assert query <= normalized("Please see RFI-17 and RFI 174", version)


def test_leading_zeros_are_dropped_for_integer_kinds(version: str) -> None:
    assert normalized("RFI 000", version) == {"rfi:0"}
    assert normalized("CB #002", version) == {"cb:2"}


@pytest.mark.parametrize("text", ["CB #2", "CB 2", "CB-2", "CB No. 2"])
def test_change_bulletins(text: str, version: str) -> None:
    assert normalized(text, version) == {"cb:2"}


@pytest.mark.parametrize("text", ["CB2", "cb 2", "XCB 2", "CB 23"])
def test_change_bulletin_near_misses(text: str, version: str) -> None:
    assert "cb:2" not in normalized(text, version)


@pytest.mark.parametrize("text", ["CO #5", "CO 5", "CO-5", "CO No. 5"])
def test_change_orders(text: str, version: str) -> None:
    assert normalized(text, version) == {"co:5"}


@pytest.mark.parametrize("text", ["CO2 levels", "co 5", "PCO 5", "COR 5", "CO 55"])
def test_change_order_near_misses(text: str, version: str) -> None:
    assert "co:5" not in normalized(text, version)


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
def test_submittals_keep_their_number_verbatim(text: str, expected: str, version: str) -> None:
    assert expected in normalized(text, version)


@pytest.mark.parametrize("text", ["Submittal twelve", "resubmittal 12x", "submittals"])
def test_submittal_near_misses(text: str, version: str) -> None:
    assert not any(n.startswith("submittal:") for n in normalized(text, version))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The GMP is final", {"gmp"}),
        ("both GMPs and the GMP's terms", {"gmp"}),
        ("FPL outage; FPLs", {"fpl"}),
        ("GMP/FPL", {"fpl", "gmp"}),
    ],
)
def test_bare_acronyms(text: str, expected: set[str], version: str) -> None:
    assert normalized(text, version) == expected


@pytest.mark.parametrize("text", ["gmp", "GMPX", "aGMP", "FPLX", "GMPS", "fpl"])
def test_bare_acronym_near_misses(text: str, version: str) -> None:
    assert normalized(text, version) == set()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Section 03 30 00.13 applies", "spec:033000.13"),
        ("Spec 033000", "spec:033000"),
        ("Section #033000", "spec:033000"),
        ("Specification 099123", "spec:099123"),
    ],
)
def test_spec_sections(text: str, expected: str, version: str) -> None:
    assert normalized(text, version) == {expected}


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
def test_spec_section_false_positives_are_rejected(text: str, version: str) -> None:
    for opt_in in (False, True):
        found = extract_identifiers(text, include_uncued_spec_sections=opt_in, version=version)
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
def test_bare_spec_like_numbers_yield_nothing_by_default(text: str, version: str) -> None:
    assert normalized(text, version) == set()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SECTION 09 91 23", {"spec:099123"}),
        ("per specs 033000", {"spec:033000"}),
        ("Sections 03 30 00 and 09 91 23", {"spec:033000"}),
        ("section no. 03 30 00.13", {"spec:033000.13"}),
    ],
)
def test_cued_spec_sections(text: str, expected: set[str], version: str) -> None:
    assert normalized(text, version) == expected


def test_the_opt_in_admits_only_the_bare_spaced_form(version: str) -> None:
    text = "ref 03 30 00 and 099123"
    assert normalized(text, version) == set()
    found = extract_identifiers(text, include_uncued_spec_sections=True, version=version)
    assert {i.normalized for i in found} == {"spec:033000"}


def test_results_are_distinct_sorted_and_typed(version: str) -> None:
    result = extract_identifiers(
        "RFI 2, RFI 1, RFI 2, GMP, CB #3, Submittal 7, Section 05 12 00", version=version
    )
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


def test_v1_never_reads_the_forms_v2_adds() -> None:
    """v1 is frozen: the WP4 forms are v2's alone (and v1's `submittal:03` defect stays)."""
    for text in ("Submittals 12", "PCO 12", "COR 7", "Change Order 5", "RFI: 174", "FP&L"):
        assert extract_identifiers(text, version=IDENTIFIER_VERSION_V1) == (), text
    assert normalized("Submittal 03 30 00-01", IDENTIFIER_VERSION_V1) == {"submittal:03"}
