"""Decimal-only amounts of exported project reports (plan section 7.1, option B).

A project-reports-local parser, deliberately not an import of the controlled
financial source's money module (that module's isolation is unchanged); a
parity test holds the two to the same results over shared cases.

* Every amount is a `decimal.Decimal` with exponent exactly -4 inside the
  `NUMERIC(20,4)` range; no binary floating point is accepted or produced.
* Money cells: a currency sign, thousands separators and exactly 2 decimals
  (`$1,234.56`), a negative in parentheses (`($1,234.56)`).
* Plain decimal cells (daily-log measures, counts): the controlled source's
  strict grammar, `-?(0|[1-9][0-9]*)(\\.[0-9]+)?`.
* More than 4 decimals is refused as `more_than_4_decimals`, never rounded;
  every other shape, a negative zero, or more than 16 integer digits is a
  `type_error`. An empty cell is `None`, never zero.
* Sums run under `AMOUNT_CONTEXT`, which traps `Inexact`, `Rounded` and
  `FloatOperation`, so a sum is exact or raises.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    FloatOperation,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
)
from typing import Final

from my_pa.domain.project_reports.model import RowReason

__all__ = [
    "AMOUNT_CONTEXT",
    "AMOUNT_QUANTUM",
    "MAX_SCALE",
    "ZERO",
    "AmountRefusedError",
    "NumericCell",
    "amount_sum",
    "parse_decimal",
    "parse_money",
    "read_cell",
]

MAX_SCALE: Final = 4
_INTEGER_DIGITS: Final = 16
AMOUNT_QUANTUM: Final = Decimal("0.0001")
ZERO: Final = Decimal("0.0000")

AMOUNT_CONTEXT: Final = Context(
    prec=38,
    rounding=ROUND_HALF_EVEN,
    Emin=-999999,
    Emax=999999,
    traps=[
        InvalidOperation,
        DivisionByZero,
        Overflow,
        Underflow,
        Subnormal,
        Inexact,
        Rounded,
        FloatOperation,
    ],
)

_MONEY: Final = re.compile(r"(\()?\$(0|[1-9][0-9]{0,2}(?:,[0-9]{3})*)(?:\.([0-9]+))?(\))?")
_PLAIN: Final = re.compile(r"(-)?(0|[1-9][0-9]*)(?:\.([0-9]+))?")
_MONEY_SCALE: Final = 2


class AmountRefusedError(ValueError):
    """A cell that is not an amount; `reason` is the row reason code only."""

    def __init__(self, reason: RowReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


def _build(negative: bool, integer: str, fraction: str) -> Decimal:
    if len(fraction) > MAX_SCALE:
        raise AmountRefusedError(RowReason.MORE_THAN_4_DECIMALS)
    if len(integer) > _INTEGER_DIGITS:
        raise AmountRefusedError(RowReason.TYPE_ERROR)
    if negative and set(integer + fraction) <= {"0"}:
        raise AmountRefusedError(RowReason.TYPE_ERROR)
    text = ("-" if negative else "") + integer + ("." + fraction if fraction else "")
    return Decimal(text).quantize(AMOUNT_QUANTUM, context=AMOUNT_CONTEXT)


def parse_money(text: str) -> Decimal | None:
    """A money cell to a scale-4 `Decimal`; `None` for an empty cell."""
    if type(text) is not str:
        raise TypeError("an amount is parsed from text only")
    if text == "":
        return None
    match = _MONEY.fullmatch(text)
    if match is None or (match.group(1) is None) != (match.group(4) is None):
        raise AmountRefusedError(RowReason.TYPE_ERROR)
    fraction = match.group(3) or ""
    # `_build` is the one place more than 4 decimals is refused; only then is a
    # storable value outside the 2-decimal export shape a `type_error`.
    value = _build(match.group(1) is not None, match.group(2).replace(",", ""), fraction)
    if len(fraction) != _MONEY_SCALE:
        raise AmountRefusedError(RowReason.TYPE_ERROR)
    return value


def parse_decimal(text: str) -> Decimal | None:
    """A plain decimal cell to a scale-4 `Decimal`; `None` for an empty cell."""
    if type(text) is not str:
        raise TypeError("an amount is parsed from text only")
    if text == "":
        return None
    match = _PLAIN.fullmatch(text)
    if match is None:
        raise AmountRefusedError(RowReason.TYPE_ERROR)
    return _build(match.group(1) is not None, match.group(2), match.group(3) or "")


def amount_sum(values: Iterable[Decimal]) -> Decimal:
    """The exact sum of scale-4 amounts from `ZERO`; a non-`Decimal` is a `TypeError`."""
    total = ZERO
    for value in values:
        if type(value) is not Decimal:
            raise TypeError("an amount sum accepts Decimal only")
        if not value.is_finite() or value.as_tuple().exponent != -MAX_SCALE:
            raise ValueError("an amount sum accepts scale-4 amounts only")
        total = AMOUNT_CONTEXT.add(total, value)
    return ZERO if total.is_zero() else total


@dataclass(frozen=True, slots=True)
class NumericCell:
    """A numeric cell as exported beside its typed value.

    `value` is `None` for an empty cell and for a refused one; `reason` is set
    exactly when the cell was refused, so an empty cell is never a failure and a
    failure is never zero.
    """

    raw: str
    value: Decimal | None
    reason: RowReason | None = None

    @property
    def failed(self) -> bool:
        return self.reason is not None


def read_cell(raw: str, *, money: bool) -> NumericCell:
    """Type one numeric cell; a refusal is kept as its reason, never raised."""
    try:
        value = parse_money(raw) if money else parse_decimal(raw)
    except AmountRefusedError as refused:
        return NumericCell(raw, None, refused.reason)
    return NumericCell(raw, value)
