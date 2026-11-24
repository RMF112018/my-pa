"""Project reports: Decimal-only amounts (plan section 7.1 option B; PULSE-AC-05).

The parity cases hold the project-reports parser to the controlled financial
source's money module (imported here, in a test, only: the ADR-018 isolation
guard scans the served roots, not `tests/`). Synthetic amounts only.
"""

from __future__ import annotations

from decimal import Decimal, FloatOperation, localcontext

import pytest

from my_pa.domain.project_controls.financial import money as controlled
from my_pa.domain.project_reports.model import RowReason
from my_pa.domain.project_reports.money import (
    AMOUNT_CONTEXT,
    ZERO,
    AmountRefusedError,
    NumericCell,
    amount_sum,
    parse_decimal,
    parse_money,
    read_cell,
)

#: Plain-decimal texts both parsers accept, and must read identically.
SHARED_ACCEPTED = ("0", "7", "12.5", "-3.25", "1000000", "0.0001", "-0.0100", "9999999999999999")
#: Texts both parsers refuse.
SHARED_REFUSED = ("1.23456", "-0", "-0.00", "01", "+1", "1e3", "1,000", " 1", "1.", ".5", "NaN")


@pytest.mark.parametrize("text", SHARED_ACCEPTED)
def test_plain_decimals_match_the_controlled_source(text: str) -> None:
    ours = parse_decimal(text)
    assert ours == controlled.parse_amount(text)
    assert ours is not None
    assert ours.as_tuple().exponent == -4


@pytest.mark.parametrize("text", SHARED_REFUSED)
def test_plain_refusals_match_the_controlled_source(text: str) -> None:
    with pytest.raises(controlled.AmountError):
        controlled.parse_amount(text)
    with pytest.raises(AmountRefusedError):
        parse_decimal(text)


@pytest.mark.parametrize(
    ("money", "plain"),
    [
        ("$0.00", "0.00"),
        ("$7.10", "7.10"),
        ("$1,234.56", "1234.56"),
        ("$12,345,678.90", "12345678.90"),
        ("($1,234.56)", "-1234.56"),
        ("($0.01)", "-0.01"),
    ],
)
def test_money_shapes_match_the_controlled_source(money: str, plain: str) -> None:
    assert parse_money(money) == controlled.parse_amount(plain)


@pytest.mark.parametrize(
    "text",
    [
        "1,234.56",  # no currency sign
        "$1234.56",  # no thousands separator
        "$1,23.45",  # a misplaced separator
        "$1,234.5",  # one decimal
        "$1,234",  # no decimals
        "$1,234.567",  # 3 decimals: not the export shape
        "-$1.00",  # a minus sign, not parentheses
        "($1.00",  # unbalanced
        "$1.00)",
        "($0.00)",  # negative zero
        "$01.00",
        " $1.00",
        "€1.00",
    ],
)
def test_money_outside_the_export_shape_is_a_type_error(text: str) -> None:
    with pytest.raises(AmountRefusedError) as refused:
        parse_money(text)
    assert refused.value.reason is RowReason.TYPE_ERROR


@pytest.mark.parametrize("text", ["$1.23456", "($1,000.00001)"])
def test_money_with_more_than_4_decimals_is_refused_never_rounded(text: str) -> None:
    with pytest.raises(AmountRefusedError) as refused:
        parse_money(text)
    assert refused.value.reason is RowReason.MORE_THAN_4_DECIMALS


@pytest.mark.parametrize("text", ["1.23456", "-0.00001", "0.123456789"])
def test_plain_decimals_with_more_than_4_decimals_are_refused(text: str) -> None:
    with pytest.raises(AmountRefusedError) as refused:
        parse_decimal(text)
    assert refused.value.reason is RowReason.MORE_THAN_4_DECIMALS


def test_4_decimals_are_accepted_exactly() -> None:
    assert parse_decimal("1.2345") == Decimal("1.2345")


def test_more_than_16_integer_digits_is_refused() -> None:
    with pytest.raises(AmountRefusedError):
        parse_decimal("1" + "0" * 16)
    with pytest.raises(AmountRefusedError):
        parse_money("$10,000,000,000,000,000.00")


def test_an_empty_cell_is_none_never_zero() -> None:
    assert parse_money("") is None
    assert parse_decimal("") is None
    assert read_cell("", money=True) == NumericCell("", None)
    assert not read_cell("", money=True).failed


def test_read_cell_keeps_a_refusal_as_its_reason() -> None:
    cell = read_cell("$1.2", money=True)
    assert cell == NumericCell("$1.2", None, RowReason.TYPE_ERROR)
    assert cell.failed
    assert read_cell("$1.00", money=True).value == Decimal("1.0000")


def test_no_float_is_accepted_anywhere() -> None:
    with pytest.raises(TypeError):
        parse_money(1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        parse_decimal(1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        amount_sum([1.5])  # type: ignore[list-item]
    with pytest.raises(FloatOperation), localcontext(AMOUNT_CONTEXT):
        Decimal(1.5)  # noqa: RUF032 - the float is the point


def test_amount_sum_is_exact_and_matches_the_controlled_source() -> None:
    values = [parse_money("$0.10"), parse_money("$0.20"), parse_money("($0.30)")]
    present = [value for value in values if value is not None]
    assert amount_sum(present) == ZERO == controlled.money_sum(present)
    big = [Decimal("9999999999999999.9999")] * 3
    assert amount_sum(big) == controlled.money_sum(big)
    assert amount_sum([]) == ZERO


def test_amount_sum_refuses_a_value_that_is_not_scale_4() -> None:
    with pytest.raises(ValueError, match="scale-4"):
        amount_sum([Decimal("1.5")])
