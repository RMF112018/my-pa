"""Knowledge value normalization rules (KLP-WP-01; AC-009 normalization slice).

R6 plan section 4, `knowledge_normalization_rule`:
- text: Unicode NFC, strip, collapse internal whitespace runs to one U+0020, no
  case folding;
- datetime: convert to UTC, truncate to microseconds, RFC 3339 'Z' form
  `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
"""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime, timedelta, timezone

import pytest

from my_pa.domain.knowledge_assertion.digest import (
    MAX_TEXT_VALUE_CHARACTERS,
    InvalidKnowledgeValueError,
    canonical_json_bytes,
    normalize_datetime,
    normalize_text,
    normalize_value,
    normalized_value_sha256,
)
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeNormalizationRule,
    KnowledgeValueType,
)

TEXT_RULE = KnowledgeNormalizationRule.TEXT_NFC_TRIM_COLLAPSE_WHITESPACE
DATETIME_RULE = KnowledgeNormalizationRule.DATETIME_UTC_MICROSECOND


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Net 30", "Net 30"),
        ("  Net 30  ", "Net 30"),
        ("Net\t\t30", "Net 30"),
        ("Net\n\r\n30", "Net 30"),
        ("Net\u00a030", "Net 30"),  # NO-BREAK SPACE is whitespace
        ("Net\u2003\u200930", "Net 30"),  # EM SPACE + THIN SPACE run
        ("a  b   c", "a b c"),
    ],
)
def test_text_is_stripped_and_whitespace_runs_collapse_to_one_space(
    raw: str, expected: str
) -> None:
    assert normalize_text(raw) == expected


def test_text_is_nfc_normalized() -> None:
    decomposed = "Cafe\u0301"
    assert unicodedata.is_normalized("NFD", decomposed)
    assert normalize_text(decomposed) == "Caf\u00e9"
    assert normalize_text("Caf\u00e9") == normalize_text(decomposed)


def test_text_is_not_case_folded() -> None:
    assert normalize_text("ACME Corp") == "ACME Corp"
    assert normalize_text("ACME Corp") != normalize_text("acme corp")


def test_normalization_is_idempotent() -> None:
    once = normalize_text("  Cafe\u0301 \t terms ")
    assert normalize_text(once) == once


@pytest.mark.parametrize("raw", ["", "   ", "\t\n", "\u00a0"])
def test_text_empty_after_normalization_is_refused(raw: str) -> None:
    with pytest.raises(InvalidKnowledgeValueError):
        normalize_text(raw)


def test_text_longer_than_the_bound_is_refused() -> None:
    assert len(normalize_text("x" * MAX_TEXT_VALUE_CHARACTERS)) == MAX_TEXT_VALUE_CHARACTERS
    with pytest.raises(InvalidKnowledgeValueError):
        normalize_text("x" * (MAX_TEXT_VALUE_CHARACTERS + 1))


@pytest.mark.parametrize("raw", [None, 30, b"Net 30", ["Net 30"]])
def test_non_text_is_refused_as_a_domain_error(raw: object) -> None:
    with pytest.raises(InvalidKnowledgeValueError):
        normalize_text(raw)


def test_datetime_converts_to_utc_with_six_fractional_digits() -> None:
    plus_two = timezone(timedelta(hours=2))
    assert (
        normalize_datetime(datetime(2026, 10, 1, 14, 0, 0, 123456, tzinfo=plus_two))
        == "2026-10-01T12:00:00.123456Z"
    )
    assert normalize_datetime(datetime(2026, 10, 1, tzinfo=UTC)) == "2026-10-01T00:00:00.000000Z"


def test_datetime_crossing_midnight_and_year_normalizes_in_utc() -> None:
    minus_five = timezone(timedelta(hours=-5))
    assert (
        normalize_datetime(datetime(2026, 12, 31, 21, 30, tzinfo=minus_five))
        == "2027-01-01T02:30:00.000000Z"
    )


def test_the_same_instant_at_different_offsets_normalizes_identically() -> None:
    a = datetime(2026, 3, 1, 9, 15, 0, 1, tzinfo=timezone(timedelta(hours=9)))
    b = datetime(2026, 3, 1, 0, 15, 0, 1, tzinfo=UTC)
    assert normalize_datetime(a) == normalize_datetime(b) == "2026-03-01T00:15:00.000001Z"


def test_naive_datetime_is_refused() -> None:
    with pytest.raises(InvalidKnowledgeValueError):
        normalize_datetime(datetime(2026, 10, 1, 12, 0))


@pytest.mark.parametrize("raw", ["2026-10-01T12:00:00Z", 1_700_000_000, None])
def test_a_datetime_rule_never_parses_text_or_numbers(raw: object) -> None:
    with pytest.raises(InvalidKnowledgeValueError):
        normalize_datetime(raw)


def test_normalize_value_refuses_a_rule_that_does_not_follow_the_value_type() -> None:
    assert normalize_value(KnowledgeValueType.TEXT, TEXT_RULE, " a  b ") == "a b"
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    assert normalize_value(KnowledgeValueType.DATETIME, DATETIME_RULE, stamp).endswith("Z")
    with pytest.raises(InvalidKnowledgeValueError):
        normalize_value(KnowledgeValueType.TEXT, DATETIME_RULE, "a")
    with pytest.raises(InvalidKnowledgeValueError):
        normalize_value(KnowledgeValueType.DATETIME, TEXT_RULE, stamp)


def test_normalized_value_sha256_is_over_nfc_utf8() -> None:
    assert normalized_value_sha256("Caf\u00e9") == normalized_value_sha256("Cafe\u0301")
    # Hard-coded: sha256 of "Caf\u00e9" as UTF-8 (`printf 'Caf\xc3\xa9' | shasum -a 256`).
    assert (
        normalized_value_sha256("Caf\u00e9")
        == "73473dcc12b763085904a5279d048c4d5b3b008c46f1f32443b99de04aa83a14"
    )


def test_canonical_json_is_nfc_sorted_compact_and_not_ascii_escaped() -> None:
    encoded = canonical_json_bytes({"b": "Cafe\u0301", "a": None, "c": [1, {"z": 1, "y": 2}]})
    assert encoded == '{"a":null,"b":"Caf\u00e9","c":[1,{"y":2,"z":1}]}'.encode()


def test_canonical_json_refuses_floats_and_non_string_keys() -> None:
    with pytest.raises(InvalidKnowledgeValueError):
        canonical_json_bytes({"a": 1.5})
    with pytest.raises(InvalidKnowledgeValueError):
        canonical_json_bytes({1: "a"})
