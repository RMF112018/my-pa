"""Financial controlled source F-1: the Decimal-only money type (contract section 3.3, 8.6)."""

from __future__ import annotations

from decimal import Decimal, FloatOperation, Inexact, Rounded, localcontext

import pytest

from my_pa.domain.project_controls.financial.model import AccountLine, AccountMeasure
from my_pa.domain.project_controls.financial.money import (
    AMOUNT_LIMIT,
    CURRENCY_MINOR_UNITS,
    FINANCE_CONTEXT,
    ZERO_AMOUNT,
    AmountError,
    currency_error,
    format_amount,
    is_storable_amount,
    minor_units,
    money_sum,
    parse_amount,
    presentation_amount,
    subtract_amounts,
)

MAX = "9999999999999999.9999"


def _code(text: str) -> str:
    with pytest.raises(AmountError) as caught:
        parse_amount(text)
    return caught.value.code


def test_amount_grammar_accepts_the_frozen_forms() -> None:
    vectors = {
        "0": "0.0000",
        "1.5": "1.5000",
        "-0.0001": "-0.0001",
        "150000": "150000.0000",
        "-150000.0000": "-150000.0000",
        "12500.5": "12500.5000",
        MAX: MAX,
        "-" + MAX: "-" + MAX,
    }
    for text, expected in vectors.items():
        value = parse_amount(text)
        assert is_storable_amount(value)
        assert format_amount(value) == expected


def test_amount_grammar_refuses_exponent_separators_and_locale() -> None:
    for text in ("1E3", "1e6", "1,000", "1 000", "1.000,5", "1_000", "NaN", "Infinity", "-inf"):
        assert _code(text) == "amount_grammar", text
    for text in (".5", "5.", "", "-", " 1", "1 ", "1\n", chr(0xFF11), "=1+1", "@SUM(A1)"):
        assert _code(text) == "amount_grammar", repr(text)


def test_amount_refuses_negative_zero_leading_plus_and_leading_zeros() -> None:
    assert _code("-0") == "amount_negative_zero"
    assert _code("-0.0000") == "amount_negative_zero"
    assert _code("-0.00") == "amount_negative_zero"
    for text in ("+1", "+5", "+1000000.0000", "00.1", "01000000.0000", "-01"):
        assert _code(text) == "amount_grammar", text


def test_amount_scale_above_4_is_refused_never_rounded() -> None:
    for text in ("0.00001", "1000000.00001", "0.00005", "1.12345", "-2.50000"):
        assert _code(text) == "amount_scale", text
    # Exactly 4 places is the input, unchanged.
    assert parse_amount("1.2345") == Decimal("1.2345")
    assert parse_amount("1.2345").as_tuple().exponent == -4


def test_amount_range_is_numeric_20_4() -> None:
    assert Decimal(10) ** 16 == AMOUNT_LIMIT
    assert is_storable_amount(parse_amount(MAX))
    assert is_storable_amount(parse_amount("-" + MAX))
    assert _code("10000000000000000") == "amount_range"
    assert _code("-10000000000000000.0000") == "amount_range"
    assert not is_storable_amount(Decimal("10000000000000000.0000"))
    assert not is_storable_amount(Decimal("1.5"))  # exponent -1, not -4
    assert not is_storable_amount(Decimal("NaN"))
    assert not is_storable_amount(Decimal("-0.0000"))


def test_no_float_is_accepted_anywhere() -> None:
    assert is_storable_amount(1.5) is False
    assert is_storable_amount(0.0) is False
    with pytest.raises(TypeError):
        parse_amount(1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        format_amount(1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        money_sum([parse_amount("1"), 1.5])  # type: ignore[list-item]
    with pytest.raises(TypeError):
        presentation_amount(1.5, "USD")  # type: ignore[arg-type]
    with pytest.raises(FloatOperation):
        FINANCE_CONTEXT.create_decimal(1.5)
    with pytest.raises(TypeError):
        AccountLine(
            "SYN-L-1",
            "SYN-P-1",
            None,
            "SYN-CC",
            "SYN-WBS",
            AccountMeasure.ACTUAL_COST,
            1.5,  # type: ignore[arg-type]
        )


def test_money_sum_is_exact_at_full_precision() -> None:
    # Built without `parse_amount`, so only `money_sum` runs under FINANCE_CONTEXT.
    total = money_sum([Decimal(MAX)] * 3)
    assert total == Decimal("29999999999999999.9997")
    assert format(total, "f") == "29999999999999999.9997"
    assert not is_storable_amount(total)  # the caller turns it into aggregate_out_of_range


def test_money_sum_is_exact_and_traps_inexact() -> None:
    with pytest.raises((Inexact, Rounded)), localcontext(FINANCE_CONTEXT):
        _ = Decimal("1") / Decimal("3")
    values = [parse_amount(t) for t in ("0.0001", "0.0002", "1234567.8901", "-0.0003")]
    assert money_sum(values) == Decimal("1234567.8901")


def test_empty_sum_and_negated_zero_are_storable() -> None:
    empty = money_sum([])
    assert empty == ZERO_AMOUNT
    assert is_storable_amount(empty)
    assert format_amount(empty) == "0.0000"
    one = parse_amount("1")
    cancelled = money_sum([parse_amount("-1"), one])
    assert is_storable_amount(cancelled)
    assert not cancelled.is_signed()
    difference = subtract_amounts(parse_amount("0"), parse_amount("0"))
    assert is_storable_amount(difference)
    assert format_amount(difference) == "0.0000"
    assert format_amount(subtract_amounts(one, one)) == "0.0000"


PRESENTATION = (
    ("0.0050", "USD", "0.00"),
    ("0.0150", "USD", "0.02"),
    ("0.0250", "USD", "0.02"),
    ("-0.0250", "USD", "-0.02"),
    ("-0.0050", "USD", "0.00"),
    ("0.0251", "USD", "0.03"),
    ("1234.5650", "EUR", "1234.56"),
    ("1234.5750", "EUR", "1234.58"),
    ("2.5000", "JPY", "2"),
    ("3.5000", "JPY", "4"),
    ("-2.5000", "JPY", "-2"),
    (MAX, "USD", "10000000000000000.00"),
)


def test_presentation_rounding_is_half_even_per_currency() -> None:
    for amount, currency, expected in PRESENTATION:
        assert presentation_amount(parse_amount(amount), currency) == expected, amount


def test_unknown_currency_has_no_minor_units() -> None:
    assert dict(CURRENCY_MINOR_UNITS) == {"EUR": 2, "JPY": 0, "USD": 2}
    assert currency_error("XTS") == "currency_unknown"
    assert currency_error("usd") == "currency_grammar"
    assert currency_error("US") == "currency_grammar"
    assert currency_error("USD") is None
    with pytest.raises(ValueError, match="minor units"):
        minor_units("XTS")
    with pytest.raises(ValueError, match="minor units"):
        presentation_amount(parse_amount("1"), "XTS")
    assert minor_units("JPY") == 0


def test_format_amount_always_writes_4_places() -> None:
    for text, expected in (
        ("0", "0.0000"),
        ("-150000", "-150000.0000"),
        ("1000000", "1000000.0000"),
        ("0.0001", "0.0001"),
    ):
        assert format_amount(parse_amount(text)) == expected
    assert "E" not in format_amount(parse_amount("1000000000000000"))
    with pytest.raises(ValueError, match="storable"):
        format_amount(Decimal("1.5"))
    with pytest.raises(ValueError, match="storable"):
        format_amount(Decimal("-0.0000"))
