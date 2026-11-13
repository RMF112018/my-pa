"""Financial controlled source F-1: the Decimal-only money type (contract section 3.3).

Every amount is a `decimal.Decimal` with exponent exactly -4 inside the
`NUMERIC(20,4)` range. Parsing refuses rather than rounds; arithmetic runs under
`FINANCE_CONTEXT`, which traps `Inexact`, `Rounded` and `FloatOperation`, so a
sum of storable amounts is exact or raises. The only rounding is
`presentation_amount`, for display. No binary floating point is accepted
anywhere: a non-`Decimal` amount is a `TypeError`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
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
from types import MappingProxyType
from typing import Final

__all__ = [
    "AMOUNT_LIMIT",
    "AMOUNT_QUANTUM",
    "CURRENCY_MINOR_UNITS",
    "FINANCE_CONTEXT",
    "ZERO_AMOUNT",
    "AmountError",
    "add_amounts",
    "currency_error",
    "format_amount",
    "is_storable_amount",
    "minor_units",
    "money_sum",
    "parse_amount",
    "presentation_amount",
    "subtract_amounts",
]

#: `NUMERIC(20,4)`: at most 16 integer digits, so `abs(amount) < 10**16` (exclusive).
AMOUNT_LIMIT: Final = Decimal(10) ** 16
#: Scale 4: every stored amount has exponent -4.
AMOUNT_QUANTUM: Final = Decimal("0.0001")
#: The storable zero (exponent -4, positive sign); an empty sum is this value.
ZERO_AMOUNT: Final = Decimal("0.0000")

_SCALE: Final = 4
_INTEGER_DIGITS: Final = 16

#: Section 3.3: the one arithmetic context. Sums of scale-4 values are exact, so
#: `Inexact`/`Rounded` never fire on valid data; if they fire it is a bug.
FINANCE_CONTEXT: Final = Context(
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

#: Presentation only: rounding is allowed here, nowhere else.
_PRESENTATION_CONTEXT: Final = Context(
    prec=38,
    rounding=ROUND_HALF_EVEN,
    Emin=-999999,
    Emax=999999,
    traps=[InvalidOperation, DivisionByZero, Overflow, FloatOperation],
)

#: Section 3.3: ISO 4217 minor units of the currencies the fixtures use. A
#: well-formed code outside this table is refused, never guessed.
CURRENCY_MINOR_UNITS: Final[Mapping[str, int]] = MappingProxyType({"EUR": 2, "JPY": 0, "USD": 2})

_CURRENCY: Final = re.compile(r"[A-Z]{3}")
_BROAD_AMOUNT: Final = re.compile(r"-?[0-9]+(\.[0-9]+)?")
_STRICT_AMOUNT: Final = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?")


class AmountError(ValueError):
    """An amount text outside the section 7.5 grammar; `code` names the refusal only."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def currency_error(code: object) -> str | None:
    """`currency_grammar`, `currency_unknown`, or `None` for a known ISO 4217 code."""
    if type(code) is not str or _CURRENCY.fullmatch(code) is None:
        return "currency_grammar"
    if code not in CURRENCY_MINOR_UNITS:
        return "currency_unknown"
    return None


def minor_units(currency: str) -> int:
    """The minor units of a known currency; any other code raises `ValueError`."""
    if currency_error(currency) is not None:
        raise ValueError("currency has no recorded minor units")
    return CURRENCY_MINOR_UNITS[currency]


def parse_amount(text: str) -> Decimal:
    """Section 7.5: the strict amount grammar to a storable amount; never rounds."""
    if type(text) is not str:
        raise TypeError("an amount is parsed from text only")
    if _BROAD_AMOUNT.fullmatch(text) is None or _STRICT_AMOUNT.fullmatch(text) is None:
        raise AmountError("amount_grammar")
    digits = text.removeprefix("-")
    integer, _, fraction = digits.partition(".")
    if text.startswith("-") and set(integer + fraction) == {"0"}:
        raise AmountError("amount_negative_zero")
    if len(fraction) > _SCALE:
        raise AmountError("amount_scale")
    if len(integer) > _INTEGER_DIGITS:
        raise AmountError("amount_range")
    # Raising Inexact/Rounded here is impossible: the grammar has refused every
    # input with more than 4 fraction digits.
    return Decimal(text).quantize(AMOUNT_QUANTUM, context=FINANCE_CONTEXT)


def is_storable_amount(value: object) -> bool:
    """Exactly a finite `Decimal` with exponent -4, inside the range, not negative zero."""
    if type(value) is not Decimal:
        return False
    return (
        value.is_finite()
        and value.as_tuple().exponent == -_SCALE
        and value.copy_abs() < AMOUNT_LIMIT
        and not (value.is_zero() and value.is_signed())
    )


def _require_operand(value: object) -> Decimal:
    if type(value) is not Decimal:
        raise TypeError("money arithmetic accepts Decimal only")
    if not value.is_finite() or value.as_tuple().exponent != -_SCALE:
        raise ValueError("money arithmetic accepts scale-4 amounts only")
    return value


def _normalise_zero(value: Decimal) -> Decimal:
    return ZERO_AMOUNT if value.is_zero() else value


def money_sum(values: Iterable[Decimal]) -> Decimal:
    """Exact sum from the storable zero; the result may exceed the range (caller checks)."""
    total = ZERO_AMOUNT
    for value in values:
        total = FINANCE_CONTEXT.add(total, _require_operand(value))
    return _normalise_zero(total)


def add_amounts(left: Decimal, right: Decimal) -> Decimal:
    """Exact `left + right` under `FINANCE_CONTEXT`."""
    return money_sum((left, right))


def subtract_amounts(left: Decimal, right: Decimal) -> Decimal:
    """Exact `left - right` under `FINANCE_CONTEXT`, a zero result written `0.0000`."""
    result = FINANCE_CONTEXT.subtract(_require_operand(left), _require_operand(right))
    return _normalise_zero(result)


def format_amount(value: Decimal) -> str:
    """Exactly 4 decimals, no exponent, `-` only below zero (section 3.3)."""
    if type(value) is not Decimal:
        raise TypeError("only a Decimal amount is formatted")
    if not is_storable_amount(value):
        raise ValueError("amount is not storable")
    return format(value, "f")


def presentation_amount(value: Decimal, currency: str) -> str:
    """The only rounding: half-even to the currency's minor units, for display only."""
    if type(value) is not Decimal:
        raise TypeError("only a Decimal amount is presented")
    if not is_storable_amount(value):
        raise ValueError("amount is not storable")
    quantum = Decimal(1).scaleb(-minor_units(currency))
    rounded = value.quantize(quantum, rounding=ROUND_HALF_EVEN, context=_PRESENTATION_CONTEXT)
    if rounded.is_zero():
        rounded = rounded.copy_abs()
    return format(rounded, "f")
