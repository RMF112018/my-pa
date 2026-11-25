"""Detail-only measures with status separation (plan sections 7.2, 7.3 and 7.5).

* **Detail rows only.** Group headers, the grand total, spacers, grouping-only
  and malformed rows never contribute, so a 2-level export cannot double count.
* **Additive columns only.** A column declared `non_additive` or `unknown`
  (variance days, link and row counts) is refused as a measure outright: its
  stated totals stay evidence and are never answered as a figure.
* **One view per measure.** Every row must belong to the named family view, so
  the two budget-change views are never added together.
* **Status separation.** Change-order measures are computed per
  `StatusClass`; there is no all-status figure, and none is read from a
  subtotal.
* **Reportability (OD-08).** A measure is a value, or `None` with closed
  reasons. No zero is ever substituted: an unpopulated column is
  `source_column_unpopulated`, not zero.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from my_pa.domain.project_reports.model import (
    Additivity,
    DerivationState,
    FamilyView,
    FilterSemantics,
    NotReportableReason,
    QuarantineReason,
    ReconciliationOutcome,
    ReportQualifier,
    RowRole,
    StatusClass,
)
from my_pa.domain.project_reports.money import NumericCell, amount_sum

__all__ = [
    "MeasureColumn",
    "MeasureRow",
    "MeasureValue",
    "MixedViewError",
    "NotAMeasureError",
    "classify_status",
    "derivation_blockers",
    "detail_sum",
    "filter_qualifiers",
    "keyed_detail_sums",
    "status_measures",
]


class NotAMeasureError(ValueError):
    """A column whose totals are not additive was offered as a measure."""


class MixedViewError(ValueError):
    """A measure's rows came from more than one family view."""


@dataclass(frozen=True, slots=True)
class MeasureColumn:
    """One amount column of one view; it names one side (revenue, cost or budget)."""

    field_key: str
    additivity: Additivity
    #: The column holds an unloaded figure when every detail cell is blank or zero
    #: (the buyout original-budget case), so all-zero is not a verified zero.
    unpopulated_when_all_zero: bool = False


@dataclass(frozen=True, slots=True)
class MeasureRow:
    view: FamilyView
    role: RowRole
    cell: NumericCell
    status: StatusClass | None = None
    key: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MeasureValue:
    value: Decimal | None
    reasons: frozenset[NotReportableReason] = frozenset()

    @property
    def reportable(self) -> bool:
        return not self.reasons


def _require_measure(column: MeasureColumn) -> None:
    if column.additivity is not Additivity.ADDITIVE:
        raise NotAMeasureError("only an additive column is a measure")


def _details(rows: Sequence[MeasureRow], view: FamilyView) -> list[MeasureRow]:
    if any(row.view is not view for row in rows):
        raise MixedViewError("a measure reads one family view")
    return [row for row in rows if row.role is RowRole.DETAIL]


def _populated(details: Sequence[MeasureRow], column: MeasureColumn) -> bool:
    values = [row.cell.value for row in details if row.cell.value is not None]
    if column.unpopulated_when_all_zero:
        return any(not value.is_zero() for value in values)
    return bool(values)


def _evaluate(
    details: Sequence[MeasureRow],
    *,
    populated: bool,
    reasons: set[NotReportableReason],
) -> MeasureValue:
    """`populated` is decided over the whole measured column, never one slice of it."""
    cells = [row.cell for row in details]
    if any(cell.failed for cell in cells):
        reasons.add(NotReportableReason.TYPE_ERROR_PRESENT)
    if not populated:
        reasons.add(NotReportableReason.SOURCE_COLUMN_UNPOPULATED)
    if reasons:
        return MeasureValue(None, frozenset(reasons))
    return MeasureValue(amount_sum(cell.value for cell in cells if cell.value is not None))


def _base_reasons(
    reconciliation: Iterable[ReconciliationOutcome], blockers: Iterable[NotReportableReason]
) -> set[NotReportableReason]:
    reasons = set(blockers)
    if ReconciliationOutcome.MISMATCH in set(reconciliation):
        reasons.add(NotReportableReason.RECONCILIATION_MISMATCH)
    return reasons


def detail_sum(
    rows: Sequence[MeasureRow],
    column: MeasureColumn,
    *,
    view: FamilyView,
    reconciliation: Iterable[ReconciliationOutcome] = (),
    blockers: Iterable[NotReportableReason] = (),
    judged_over: Sequence[MeasureRow] | None = None,
) -> MeasureValue:
    """The exact sum of the column over the view's detail rows, or why there is none.

    `judged_over` is the whole column the population is judged over when
    `rows` is a slice of it (a filtered read); `rows` itself by default.
    """
    _require_measure(column)
    details = _details(rows, view)
    whole = details if judged_over is None else _details(judged_over, view)
    reasons = _base_reasons(reconciliation, blockers)
    return _evaluate(details, populated=_populated(whole, column), reasons=reasons)


def status_measures(
    rows: Sequence[MeasureRow],
    column: MeasureColumn,
    *,
    view: FamilyView,
    reconciliation: Iterable[ReconciliationOutcome] = (),
    blockers: Iterable[NotReportableReason] = (),
    judged_over: Sequence[MeasureRow] | None = None,
) -> Mapping[StatusClass, MeasureValue]:
    """One measure per status class; an `unknown` status blocks every class.

    A class with no line in a populated column is an exact zero (an empty sum
    over a verified report), not a substituted one. The population and the
    `unknown` block are judged over `judged_over` (the whole column) when
    `rows` is a slice of it; over `rows` by default.
    """
    _require_measure(column)
    details = _details(rows, view)
    whole = details if judged_over is None else _details(judged_over, view)
    base = _base_reasons(reconciliation, blockers)
    if any(row.status in (None, StatusClass.UNKNOWN) for row in whole):
        base.add(NotReportableReason.STATUS_UNKNOWN_PRESENT)
    populated = _populated(whole, column)
    return MappingProxyType(
        {
            status: _evaluate(
                [row for row in details if row.status is status],
                populated=populated,
                reasons=set(base),
            )
            for status in StatusClass
        }
    )


def keyed_detail_sums(
    rows: Sequence[MeasureRow],
    column: MeasureColumn,
    *,
    view: FamilyView,
    reconciliation: Iterable[ReconciliationOutcome] = (),
    blockers: Iterable[NotReportableReason] = (),
    judged_over: Sequence[MeasureRow] | None = None,
) -> Mapping[tuple[str, ...], MeasureValue]:
    """Detail sums per row key, e.g. `(commitment, budget code)`; population as `detail_sum`."""
    _require_measure(column)
    details = _details(rows, view)
    whole = details if judged_over is None else _details(judged_over, view)
    base = _base_reasons(reconciliation, blockers)
    populated = _populated(whole, column)
    keys = sorted({row.key for row in details})
    return MappingProxyType(
        {
            key: _evaluate(
                [row for row in details if row.key == key], populated=populated, reasons=set(base)
            )
            for key in keys
        }
    )


def classify_status(
    raw: str,
    *,
    exact: Mapping[str, StatusClass],
    prefixes: Mapping[str, StatusClass] = MappingProxyType({}),
) -> StatusClass:
    """A verbatim status through a versioned family table; unmapped is `unknown`."""
    if raw in exact:
        return exact[raw]
    for prefix, status in prefixes.items():
        if prefix and raw.startswith(prefix):
            return status
    return StatusClass.UNKNOWN


def derivation_blockers(
    state: DerivationState | None, quarantine_reason: QuarantineReason | None
) -> frozenset[NotReportableReason]:
    """Derivation-level reasons: no snapshot, or a quarantined one (with its cause)."""
    if state is None:
        return frozenset({NotReportableReason.NO_SNAPSHOT})
    if state is DerivationState.CLASSIFIED:
        return frozenset()
    reasons = {NotReportableReason.SNAPSHOT_QUARANTINED}
    if quarantine_reason is QuarantineReason.BINDING_PROJECT_NUMBER_MISMATCH:
        reasons.add(NotReportableReason.BINDING_PROJECT_NUMBER_MISMATCH)
    return frozenset(reasons)


def filter_qualifiers(semantics: FilterSemantics) -> frozenset[ReportQualifier]:
    """`filter_semantics_unknown` unless the operator declared the report's filter."""
    if semantics is FilterSemantics.OPERATOR_DECLARED:
        return frozenset()
    return frozenset({ReportQualifier.FILTER_SEMANTICS_UNKNOWN})
