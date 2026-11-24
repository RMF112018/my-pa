"""Project reports: record identity and exact RFI matching (plan 6.3; PULSE-AC-14).

Synthetic identifiers only.
"""

from __future__ import annotations

import pytest

from my_pa.domain.project_reports.identity import (
    AMBIGUOUS_PREFIX,
    RecordIdentity,
    RecordKeyKind,
    RfiNumber,
    match_rfi,
    normalize_commitment_number,
    record_identity,
    split_rfi_number,
)
from my_pa.domain.project_reports.model import IdentityBasis, IdentityState


@pytest.mark.parametrize(
    ("kind", "parts", "key", "basis"),
    [
        (RecordKeyKind.ITEM, ("4",), "item:4", IdentityBasis.EXPORTED_NUMBER),
        (RecordKeyKind.OBSERVATION, ("12",), "observation:12", IdentityBasis.EXPORTED_NUMBER),
        (
            RecordKeyKind.COORDINATION_ISSUE,
            ("7",),
            "coordination_issue:7",
            IdentityBasis.EXPORTED_NUMBER,
        ),
        (RecordKeyKind.RFI, (" ZZ  1-9 ",), "rfi:ZZ 1-9", IdentityBasis.EXPORTED_NUMBER),
        (RecordKeyKind.BUDGET_CHANGE, ("3",), "budget_change:3", IdentityBasis.EXPORTED_NUMBER),
        (
            RecordKeyKind.COMMITMENT,
            ("T900.00042", "T900-01-001"),
            "commitment:T900.42@T900-01-001",
            IdentityBasis.EXPORTED_NUMBER_NORMALIZED,
        ),
        (RecordKeyKind.PRIME_CO, ("2",), "prime_co:2", IdentityBasis.EXPORTED_NUMBER),
        (RecordKeyKind.PCO, ("15",), "pco:15", IdentityBasis.EXPORTED_NUMBER),
        (
            RecordKeyKind.MANPOWER,
            ("1/2/2030", "Vendor A"),
            "manpower:1/2/2030@Vendor A",
            IdentityBasis.EXPORTED_COMPOSITE,
        ),
        (RecordKeyKind.WEATHER, ("1/2/2030",), "weather:1/2/2030", IdentityBasis.EXPORTED_NUMBER),
    ],
)
def test_family_record_keys(
    kind: RecordKeyKind, parts: tuple[str, ...], key: str, basis: IdentityBasis
) -> None:
    assert record_identity(kind, *parts) == RecordIdentity(IdentityState.IDENTIFIED, key, basis)


def test_an_empty_identifier_has_no_identity() -> None:
    assert record_identity(RecordKeyKind.RFI, "  ").state is IdentityState.IDENTITY_MISSING
    assert record_identity(RecordKeyKind.MANPOWER, "1/2/2030", "").key is None


def test_an_at_sign_before_the_last_part_is_ambiguous() -> None:
    identity = record_identity(RecordKeyKind.COMMITMENT, "T900@1", "C1")
    assert identity.state is IdentityState.AMBIGUOUS_IDENTITY and identity.key is None
    assert record_identity(RecordKeyKind.MANPOWER, "1/2/2030", "A@B").key == "manpower:1/2/2030@A@B"


def test_a_key_takes_exactly_its_familys_parts() -> None:
    with pytest.raises(ValueError, match="exported parts"):
        record_identity(RecordKeyKind.COMMITMENT, "T900.001")
    with pytest.raises(ValueError, match="exported parts"):
        record_identity(RecordKeyKind.RFI, "1", "2")


def test_commitment_numbers_normalize_both_padding_styles_alike() -> None:
    assert normalize_commitment_number("T900.00042") == "T900.42"
    assert normalize_commitment_number("T900.0042") == "T900.42"
    assert normalize_commitment_number("T900.000") == "T900.0"
    assert normalize_commitment_number("T900") == "T900"
    assert normalize_commitment_number("T900.A01") == "T900.A01"
    one = record_identity(RecordKeyKind.COMMITMENT, "T900.00042", "C1")
    other = record_identity(RecordKeyKind.COMMITMENT, "T900.0042", "C1")
    assert one.key == other.key
    # The same commitment under 2 budget codes is 2 keys.
    assert record_identity(RecordKeyKind.COMMITMENT, "T900.0042", "C2").key != one.key


def test_rfi_numbers_split_on_a_token_bounded_suffix() -> None:
    assert split_rfi_number("ZZ-174") == RfiNumber("ZZ-174", "ZZ", 174)
    assert split_rfi_number("QQ 50%-174") == RfiNumber("QQ 50%-174", "QQ 50%", 174)
    assert split_rfi_number("174") == RfiNumber("174", None, 174)
    assert split_rfi_number("ZZ-1740") == RfiNumber("ZZ-1740", "ZZ", 1740)
    assert split_rfi_number("ZZ-A") is None
    assert split_rfi_number("") is None


CANDIDATES = tuple(
    number
    for text in ("ZZ-174", "QQ 50%-174", "ZZ-1740", "ZZ-17", "174", "ZZ-0174", "QQ 50%-1")
    if (number := split_rfi_number(text)) is not None
)


def _matched(prefix: str | None, suffix: int) -> tuple[list[str], str | None]:
    result = match_rfi(prefix, suffix, CANDIDATES)
    return [number.exported for number in result.matches], result.flag


def test_rfi_matching_is_exact_on_the_suffix() -> None:
    exported, _ = _matched(None, 174)
    assert "ZZ-1740" not in exported and "ZZ-17" not in exported
    assert _matched("ZZ", 17) == (["ZZ-17"], None)


def test_a_given_prefix_must_match_exactly() -> None:
    assert _matched("ZZ", 174) == (["ZZ-174", "ZZ-0174"], None)
    assert _matched("ZZ-", 174) == (["ZZ-174", "ZZ-0174"], None)
    assert _matched("QQ 50%", 174) == (["QQ 50%-174"], None)
    assert _matched("Z", 174) == ([], None)


def test_no_prefix_matches_every_prefix_and_flags_ambiguity() -> None:
    assert _matched(None, 174) == (["ZZ-174", "QQ 50%-174", "174", "ZZ-0174"], AMBIGUOUS_PREFIX)
    assert _matched(None, 1740) == (["ZZ-1740"], None)
    assert _matched(None, 9) == ([], None)


def test_rfi_suffix_is_validated() -> None:
    with pytest.raises(ValueError, match="suffix"):
        match_rfi(None, -1, CANDIDATES)
