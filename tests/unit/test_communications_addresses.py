"""The address match key, C9-R1 (communications intelligence WP5-S2, ruling D11).

The fifteen synthetic cases of the WP5-W1 design report section 3.9: the
communications form is `raw.strip().lower()` (the parser), the Meeting form is
`normalize_attendee_email(raw)` (the EMAIL rule). Ten agree as stored, five do
not, and the match key bridges all fifteen. Every address is synthetic.
"""

from __future__ import annotations

import re
from typing import Final

import pytest

from my_pa.domain.communications.addresses import (
    ADDRESS_RULE,
    address_match_key,
    bridge_addresses,
    bridge_characters,
    bridge_pattern,
    is_ascii_address,
    needs_bridge,
)
from my_pa.domain.meeting.model import normalize_attendee_email

#: Case -> raw address. The first ten store identically on both sides.
EQUAL: Final = {
    "ascii_lower": "pat.lee@example.test",
    "ascii_mixed_case": "Pat.Lee@Example.TEST",
    "padded": "  pat@example.test ",
    "plus_tag": "pat+rfi@example.test",
    "punycode_domain": "pat@xn--bcher-kva.example",
    "kelvin_sign": "\u212aelvin@example.test",
    "dotted_capital_i": "\u0130lker@example.test",
    "idn_unicode_domain": "pat@b\u00fccher.example",
    "full_width": "\uff21lex@example.test",
    "decomposed_accent": "rene\u0301@example.test",
}
#: The five where `lower` and `casefold` differ.
DIFFERENT: Final = {
    "sharp_s": "stra\u00dfe@example.test",
    "capital_sharp_s": "STRA\u1e9eE@example.test",
    "final_sigma": "\u039f\u0394\u039f\u03a3@example.test",
    "ligature_fi": "\ufb01eld@example.test",
    "cherokee_small": "\uab70\uab71@example.test",
}


def _communications_form(raw: str) -> str:
    return raw.strip().lower()


def test_the_rule_is_versioned() -> None:
    assert ADDRESS_RULE == "casefold_bridge_v1"


def test_there_are_fifteen_cases_ten_equal_and_five_different() -> None:
    assert (len(EQUAL), len(DIFFERENT)) == (10, 5)
    for raw in EQUAL.values():
        assert _communications_form(raw) == normalize_attendee_email(raw), raw
    for raw in DIFFERENT.values():
        assert _communications_form(raw) != normalize_attendee_email(raw), raw


@pytest.mark.parametrize("case", sorted({**EQUAL, **DIFFERENT}))
def test_the_key_of_the_stored_address_is_the_meeting_form(case: str) -> None:
    raw = {**EQUAL, **DIFFERENT}[case]
    assert address_match_key(_communications_form(raw)) == normalize_attendee_email(raw)


def test_the_key_is_the_identity_on_a_stored_ascii_address() -> None:
    for raw in EQUAL.values():
        stored = _communications_form(raw)
        if is_ascii_address(stored):
            assert address_match_key(stored) == stored


def test_the_sharp_s_is_folded_not_lowered() -> None:
    """The prove-red anchor (m4): `.lower()` keeps `ß`; `casefold` makes it `ss`."""
    assert address_match_key("stra\u00dfe@example.test") == "strasse@example.test"


def test_the_bridge_adds_only_non_ascii_addresses_whose_key_is_an_attendee_key() -> None:
    stored = [
        _communications_form(DIFFERENT["sharp_s"]),
        _communications_form(DIFFERENT["final_sigma"]),
        _communications_form(DIFFERENT["ligature_fi"]),
        "pat@example.test",
        "stra\u00dfe@other.test",
    ]
    keys = {
        normalize_attendee_email(DIFFERENT["sharp_s"]),
        normalize_attendee_email(DIFFERENT["final_sigma"]),
        "pat@example.test",
        "nobody@example.test",
    }
    bridged = bridge_addresses(stored, keys)
    assert dict(bridged) == {
        normalize_attendee_email(DIFFERENT["sharp_s"]): (
            _communications_form(DIFFERENT["sharp_s"]),
        ),
        normalize_attendee_email(DIFFERENT["final_sigma"]): (
            _communications_form(DIFFERENT["final_sigma"]),
        ),
    }


def test_a_non_ascii_address_already_in_key_form_needs_no_bridge() -> None:
    stored = "pat@b\u00fccher.example"
    assert dict(bridge_addresses([stored], {stored})) == {}


def test_the_bridge_is_sorted_and_deterministic() -> None:
    key = "strasse@example.test"
    stored = ["stra\u00dfe@example.test", "stra\u017f\u017fe@example.test", key]
    first = bridge_addresses(stored, {key})
    assert first == bridge_addresses(list(reversed(stored)), {key})
    assert len(first[key]) == 2
    assert list(first[key]) == sorted(first[key])


def test_only_an_address_whose_casefold_differs_needs_a_bridge() -> None:
    """WP5-R1 F-4: the bridge statement reads only these; the cap binds only on them."""
    for raw in DIFFERENT.values():
        assert needs_bridge(_communications_form(raw)), raw
    for raw in EQUAL.values():
        assert not needs_bridge(_communications_form(raw)), raw
    assert not needs_bridge("café@example.test")
    assert not needs_bridge("οδοσ@example.test")  # a medial sigma
    assert {chr(c) for c in (0xDF, 0x3C2, 0xFB01, 0xAB70, 0x17F)} <= bridge_characters()
    assert not {chr(c) for c in (0xE9, 0x3C3, 0x61, 0x40)} & bridge_characters()


def test_the_bridge_pattern_is_the_bridge_characters_as_ranges() -> None:
    pattern = bridge_pattern()
    assert pattern.startswith("[") and pattern.endswith("]")
    covered: set[int] = set()
    for match in re.finditer(r"\\U([0-9a-f]{8})(?:-\\U([0-9a-f]{8}))?", pattern):
        low = int(match.group(1), 16)
        high = int(match.group(2) or match.group(1), 16)
        covered.update(range(low, high + 1))
    assert covered == {ord(character) for character in bridge_characters()}
