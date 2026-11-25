"""WP3P-F1 S3: a project-report amount `NUMERIC(20,4)` would round or overflow is refused.

The column rounds a fifth decimal silently (`1.23456` is stored as `1.2346`)
and no CHECK sees the value before it is rounded, so the port records refuse
it at construction: a line value's Decimal, a stated total's stated and
computed values, and a cross-check's two values. NaN, an infinity and more
than 16 integer digits are refused too; `None` and every storable amount pass.
The refusal names the rule, never the value. Every value is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

import pytest

from my_pa.contracts.ports import (
    ProjectReportCrossCheckRecord,
    ProjectReportLineValueRecord,
    ProjectReportStatedTotalRecord,
)
from my_pa.domain.project_reports.model import (
    Additivity,
    ReconciliationOutcome,
    RowRole,
    TotalScope,
    ValueKind,
)
from my_pa.domain.project_reports.reconciliation import CROSS_CHECK_KIND

WHEN: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)

REFUSED: Final = (
    Decimal("1.23456"),
    Decimal("-0.00001"),
    Decimal("1E-5"),
    Decimal("NaN"),
    Decimal("sNaN"),
    Decimal("Infinity"),
    Decimal("-Infinity"),
    Decimal("10000000000000000"),
    Decimal("1E+16"),
    Decimal("-10000000000000000.0000"),
    Decimal("1.000000001"),
)
STORABLE: Final = (
    Decimal("9999999999999999.9999"),
    Decimal("-9999999999999999.9999"),
    Decimal("1.2346"),
    Decimal("1.5"),
    Decimal(0),
    Decimal("0E-4"),
    Decimal("0E+20"),
    Decimal("1E+15"),
    Decimal("-0.0001"),
    # Trailing zeros past the fourth decimal round to nothing (the exact rule).
    Decimal("1.50000"),
    Decimal("0E-10"),
    Decimal("-2.123400000"),
)


def _line_value(amount: Decimal | None) -> ProjectReportLineValueRecord:
    return ProjectReportLineValueRecord("rfi.amount", ValueKind.MONEY, "1.00", amount)


def _stated_value(amount: Decimal | None) -> ProjectReportStatedTotalRecord:
    return ProjectReportStatedTotalRecord(
        "prdrv_prunit0001",
        1,
        2,
        RowRole.GRAND_TOTAL,
        TotalScope.GRAND,
        "rfi.amount",
        "1.00",
        Additivity.ADDITIVE,
        ReconciliationOutcome.MISMATCH,
        value=amount,
    )


def _computed_value(amount: Decimal | None) -> ProjectReportStatedTotalRecord:
    return ProjectReportStatedTotalRecord(
        "prdrv_prunit0001",
        1,
        2,
        RowRole.GRAND_TOTAL,
        TotalScope.GRAND,
        "rfi.amount",
        "",
        Additivity.ADDITIVE,
        ReconciliationOutcome.MISMATCH,
        computed_value=amount,
    )


def _cross_check(*, left: Decimal | None = None, right: Decimal | None = None) -> object:
    return ProjectReportCrossCheckRecord(
        check_kind=CROSS_CHECK_KIND,
        left_derivation_id="prdrv_prunit0001",
        right_derivation_id="prdrv_prunit0002",
        project_id="prj_prunit0001",
        outcome=ReconciliationOutcome.MISMATCH,
        checked_at=WHEN,
        left_value=left,
        right_value=right,
    )


BUILDERS: Final[dict[str, Callable[[Decimal | None], object]]] = {
    "line_value": _line_value,
    "stated_total_value": _stated_value,
    "stated_total_computed_value": _computed_value,
    "cross_check_left_value": lambda amount: _cross_check(left=amount),
    "cross_check_right_value": lambda amount: _cross_check(right=amount),
}


@pytest.mark.parametrize("builder", BUILDERS, ids=str)
@pytest.mark.parametrize("amount", REFUSED, ids=str)
def test_an_amount_numeric_20_4_would_round_or_overflow_is_refused(
    builder: str, amount: Decimal
) -> None:
    with pytest.raises(ValueError, match="project-report amount") as refused:
        BUILDERS[builder](amount)
    # The rule, never the value.
    assert str(amount) not in str(refused.value)


@pytest.mark.parametrize("builder", BUILDERS, ids=str)
@pytest.mark.parametrize("amount", (*STORABLE, None), ids=str)
def test_a_storable_amount_or_none_is_accepted(builder: str, amount: Decimal | None) -> None:
    BUILDERS[builder](amount)


def test_the_rounding_hazard_itself_is_refused_with_its_rule() -> None:
    """`1.23456` would be stored as `1.2346`: the record refuses it, naming the scale."""
    with pytest.raises(ValueError, match="at most 4 decimals"):
        _line_value(Decimal("1.23456"))
    with pytest.raises(ValueError, match="at most 16 integer digits"):
        _line_value(Decimal("10000000000000000"))
    with pytest.raises(ValueError, match="finite"):
        _line_value(Decimal("NaN"))


@pytest.mark.parametrize("builder", sorted(set(BUILDERS) - {"line_value"}))
def test_a_non_decimal_amount_is_a_type_error(builder: str) -> None:
    with pytest.raises(TypeError):
        BUILDERS[builder](1.5)  # type: ignore[arg-type]


def test_a_line_values_other_kinds_are_not_amounts() -> None:
    """Only a Decimal is an amount; text, dates and booleans pass through untouched."""
    ProjectReportLineValueRecord("rfi.subject", ValueKind.TEXT, "1.23456", "1.23456")
    ProjectReportLineValueRecord("rfi.closed", ValueKind.BOOLEAN, "Yes", True)
