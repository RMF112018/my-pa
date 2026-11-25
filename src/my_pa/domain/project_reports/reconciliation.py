"""Stated-total reconciliation and the cross-report check (plan section 7.4, ruling D15).

Group headers and the grand total carry aggregates the exporter printed. They
are evidence used to **verify** detail sums, never inputs to a measure. For a
catalogued numeric column:

* a column that is not `additive` is `not_checked` (stated non-additive totals
  are kept as evidence only);
* a stated empty cell and no detail value in scope is `both_empty`;
* any other empty side, or any refused cell in scope, is `mismatch`
  (fail-closed);
* otherwise the stated value against the exact decimal sum of the detail
  values in scope is `match` or `mismatch`.

A group header's scope is the detail rows whose group path passes through it,
so a level-1 subtotal covers the detail under its level-2 groups once and the
level-2 headers never enter it. The grand total is compared with the sum of
every detail row and, when the export has level-1 headers, with the sum of
their stated values; it matches only when both checks agree.

Both evidence units are reported (ruling D15): per column-group (one header
row and one column) and per group (a header row all of whose checked columns
agree).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Final

from my_pa.domain.project_reports.model import (
    Additivity,
    ReconciliationOutcome,
    RowRole,
    StatusClass,
    TotalScope,
)
from my_pa.domain.project_reports.money import NumericCell, amount_sum, read_cell
from my_pa.domain.project_reports.roles import ClassifiedRow

__all__ = [
    "BLANK_GROUP_KEY",
    "CROSS_CHECK_KIND",
    "CrossReportCheck",
    "ReconciliationSummary",
    "StatedTotalCheck",
    "TotalColumn",
    "compare",
    "cross_report_check",
    "reconcile_totals",
    "summarize",
]

#: The group of records whose key is null: a real group with a real subtotal.
BLANK_GROUP_KEY: Final = "(Blank)"
CROSS_CHECK_KIND: Final = "buyout_prime_co_vs_co_reconciliation_v1"


@dataclass(frozen=True, slots=True)
class TotalColumn:
    """One catalogued numeric column of a family view."""

    column_index: int
    field_key: str
    additivity: Additivity
    money: bool


@dataclass(frozen=True, slots=True)
class StatedTotalCheck:
    row_ordinal: int
    scope: TotalScope
    group_level: int | None
    group_key: str | None
    column_index: int
    field_key: str
    raw_text: str
    value: Decimal | None
    additivity: Additivity
    computed_value: Decimal | None
    outcome: ReconciliationOutcome


def _sum(cells: Sequence[NumericCell]) -> Decimal | None:
    values = [cell.value for cell in cells if cell.value is not None]
    return amount_sum(values) if values else None


def compare(
    stated: NumericCell, parts: Sequence[NumericCell], additivity: Additivity
) -> tuple[ReconciliationOutcome, Decimal | None]:
    """The outcome of one stated value against the parts it should total, and their sum."""
    if additivity is not Additivity.ADDITIVE:
        return ReconciliationOutcome.NOT_CHECKED, None
    computed = _sum(parts)
    if stated.failed or any(part.failed for part in parts):
        return ReconciliationOutcome.MISMATCH, computed
    if stated.value is None and computed is None:
        return ReconciliationOutcome.BOTH_EMPTY, None
    if stated.value is None or computed is None or stated.value != computed:
        return ReconciliationOutcome.MISMATCH, computed
    return ReconciliationOutcome.MATCH, computed


def _cell(cells: Sequence[Sequence[str]], row: ClassifiedRow, column: TotalColumn) -> NumericCell:
    return read_cell(cells[row.ordinal - 1][column.column_index], money=column.money)


def _in_scope(detail: ClassifiedRow, header_ordinal: int) -> bool:
    return any(step.header_ordinal == header_ordinal for step in detail.group_path)


def _combine(first: ReconciliationOutcome, second: ReconciliationOutcome) -> ReconciliationOutcome:
    return first if first is second else ReconciliationOutcome.MISMATCH


def reconcile_totals(
    rows: Sequence[ClassifiedRow],
    cells: Sequence[Sequence[str]],
    columns: Sequence[TotalColumn],
) -> tuple[StatedTotalCheck, ...]:
    """One check per (group header or grand total row, catalogued column)."""
    if len(rows) != len(cells):
        raise ValueError("every classified row needs its cells")
    details = [row for row in rows if row.role is RowRole.DETAIL]
    level1 = [
        row
        for row in rows
        if row.role in (RowRole.GROUP_HEADER, RowRole.GROUPING_ONLY) and row.group_level == 1
    ]
    checks: list[StatedTotalCheck] = []
    for row in rows:
        if row.role not in (RowRole.GROUP_HEADER, RowRole.GRAND_TOTAL):
            continue
        for column in columns:
            stated = _cell(cells, row, column)
            if row.role is RowRole.GROUP_HEADER:
                scope = TotalScope.GROUP
                in_scope = [d for d in details if _in_scope(d, row.ordinal)]
                parts = [_cell(cells, d, column) for d in in_scope]
                outcome, computed = compare(stated, parts, column.additivity)
            else:
                scope = TotalScope.GRAND
                parts = [_cell(cells, d, column) for d in details]
                outcome, computed = compare(stated, parts, column.additivity)
                if level1 and outcome is not ReconciliationOutcome.NOT_CHECKED:
                    headers = [_cell(cells, h, column) for h in level1]
                    by_headers, _ = compare(stated, headers, column.additivity)
                    outcome = _combine(outcome, by_headers)
            checks.append(
                StatedTotalCheck(
                    row_ordinal=row.ordinal,
                    scope=scope,
                    group_level=row.group_level,
                    group_key=row.group_key,
                    column_index=column.column_index,
                    field_key=column.field_key,
                    raw_text=stated.raw,
                    value=stated.value,
                    additivity=column.additivity,
                    computed_value=computed,
                    outcome=outcome,
                )
            )
    return tuple(checks)


@dataclass(frozen=True, slots=True)
class ReconciliationSummary:
    """Both evidence units: column-groups and whole groups, plus the grand totals."""

    group_columns: Mapping[str, int]
    groups_checked: int
    groups_all_columns_match: int
    grand_columns: Mapping[str, int]


def _outcome_counts(checks: Sequence[StatedTotalCheck]) -> Mapping[str, int]:
    counts = dict.fromkeys((outcome.value for outcome in ReconciliationOutcome), 0)
    for check in checks:
        counts[check.outcome.value] += 1
    return MappingProxyType(counts)


def summarize(checks: Sequence[StatedTotalCheck]) -> ReconciliationSummary:
    group = [check for check in checks if check.scope is TotalScope.GROUP]
    by_row: dict[int, list[ReconciliationOutcome]] = {}
    for check in group:
        if check.outcome is not ReconciliationOutcome.NOT_CHECKED:
            by_row.setdefault(check.row_ordinal, []).append(check.outcome)
    agreeing = sum(
        1
        for outcomes in by_row.values()
        if ReconciliationOutcome.MISMATCH not in outcomes
        and ReconciliationOutcome.MATCH in outcomes
    )
    return ReconciliationSummary(
        group_columns=_outcome_counts(group),
        groups_checked=len(by_row),
        groups_all_columns_match=agreeing,
        grand_columns=_outcome_counts([c for c in checks if c.scope is TotalScope.GRAND]),
    )


@dataclass(frozen=True, slots=True)
class CrossReportCheck:
    kind: str
    left_value: Decimal | None
    right_value: Decimal | None
    outcome: ReconciliationOutcome


def cross_report_check(
    approved_grand_total: NumericCell | None,
    change_order_subtotals: Sequence[tuple[str, NumericCell]],
    blank_group_lines: Sequence[tuple[StatusClass, NumericCell]],
) -> CrossReportCheck:
    """Buyout's approved prime-change total against the reconciliation export.

    The right side is the numbered change-order subtotals (every key but
    `(Blank)`) plus the **approved** lines of the `(Blank)` group only: pending
    and void lines never enter it. Without the pair (`None` on the left) the
    check is `not_checked` and nothing is inferred.
    """
    if approved_grand_total is None:
        return CrossReportCheck(CROSS_CHECK_KIND, None, None, ReconciliationOutcome.NOT_CHECKED)
    parts = [cell for key, cell in change_order_subtotals if key != BLANK_GROUP_KEY]
    parts += [cell for status, cell in blank_group_lines if status is StatusClass.APPROVED]
    outcome, right = compare(approved_grand_total, parts, Additivity.ADDITIVE)
    return CrossReportCheck(CROSS_CHECK_KIND, approved_grand_total.value, right, outcome)
