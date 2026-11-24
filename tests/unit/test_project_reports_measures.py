"""Project reports: detail-only measures and status separation (plan 7.2-7.5).

PULSE-AC-06 (detail only), AC-07 (status classes separate), AC-08 partial (a
non-additive total is never a measure), AC-09 (not reportable, no zero
substituted), AC-10 (filter semantics unknown unless declared). Synthetic only.
"""

from __future__ import annotations

from decimal import Decimal
from types import MappingProxyType

import pytest

from my_pa.domain.project_reports.measures import (
    MeasureColumn,
    MeasureRow,
    MixedViewError,
    NotAMeasureError,
    classify_status,
    derivation_blockers,
    detail_sum,
    filter_qualifiers,
    keyed_detail_sums,
    status_measures,
)
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
from my_pa.domain.project_reports.money import read_cell

VIEW = FamilyView.RECONCILIATION
AMOUNT = MeasureColumn("synthetic.amount", Additivity.ADDITIVE)


def _row(
    role: RowRole,
    text: str,
    status: StatusClass | None = None,
    view: FamilyView = VIEW,
    key: tuple[str, ...] = (),
) -> MeasureRow:
    return MeasureRow(view, role, read_cell(text, money=True), status, key)


def _rows() -> list[MeasureRow]:
    return [
        _row(RowRole.GROUP_HEADER, "$100.00"),
        _row(RowRole.DETAIL, "$10.00", StatusClass.APPROVED),
        _row(RowRole.DETAIL, "$20.00", StatusClass.PENDING),
        _row(RowRole.DETAIL, "$40.00", StatusClass.VOID),
        _row(RowRole.DETAIL, "$1.00", StatusClass.APPROVED),
        _row(RowRole.SPACER, ""),
        _row(RowRole.GROUPING_ONLY, "$5.00"),
        _row(RowRole.MALFORMED, "$7.00"),
        _row(RowRole.GRAND_TOTAL, "$71.00"),
    ]


def test_a_measure_sums_detail_rows_only() -> None:
    result = detail_sum(_rows(), AMOUNT, view=VIEW)
    assert result.reportable and result.value == Decimal("71.0000")


def test_status_classes_are_measured_separately() -> None:
    measures = status_measures(_rows(), AMOUNT, view=VIEW)
    assert set(measures) == set(StatusClass)
    assert measures[StatusClass.APPROVED].value == Decimal("11.0000")
    assert measures[StatusClass.PENDING].value == Decimal("20.0000")
    assert measures[StatusClass.VOID].value == Decimal("40.0000")
    # An empty class of a populated column is an exact zero, not a gap.
    assert measures[StatusClass.UNKNOWN].value == Decimal("0.0000")
    assert all(value.reportable for value in measures.values())


def test_an_unknown_status_blocks_every_status_measure() -> None:
    rows = [*_rows(), _row(RowRole.DETAIL, "$3.00", StatusClass.UNKNOWN)]
    for value in status_measures(rows, AMOUNT, view=VIEW).values():
        assert value.value is None
        assert NotReportableReason.STATUS_UNKNOWN_PRESENT in value.reasons
    unmapped = [*_rows(), _row(RowRole.DETAIL, "$3.00", None)]
    approved = status_measures(unmapped, AMOUNT, view=VIEW)[StatusClass.APPROVED]
    assert approved.reasons == {NotReportableReason.STATUS_UNKNOWN_PRESENT}


@pytest.mark.parametrize("additivity", [Additivity.NON_ADDITIVE, Additivity.UNKNOWN])
def test_a_non_additive_column_is_never_a_measure(additivity: Additivity) -> None:
    column = MeasureColumn("synthetic.days", additivity)
    with pytest.raises(NotAMeasureError):
        detail_sum(_rows(), column, view=VIEW)
    with pytest.raises(NotAMeasureError):
        status_measures(_rows(), column, view=VIEW)
    with pytest.raises(NotAMeasureError):
        keyed_detail_sums(_rows(), column, view=VIEW)


def test_two_views_are_never_summed_together() -> None:
    rows = [
        _row(RowRole.DETAIL, "$1.00", view=FamilyView.GROUPED_BY_CHANGE),
        _row(RowRole.DETAIL, "$1.00", view=FamilyView.BY_CODE),
    ]
    with pytest.raises(MixedViewError):
        detail_sum(rows, AMOUNT, view=FamilyView.GROUPED_BY_CHANGE)
    single = detail_sum(rows[:1], AMOUNT, view=FamilyView.GROUPED_BY_CHANGE)
    assert single.value == Decimal("1.0000")


def test_a_reconciliation_mismatch_makes_the_measure_not_reportable() -> None:
    result = detail_sum(
        _rows(),
        AMOUNT,
        view=VIEW,
        reconciliation=[ReconciliationOutcome.MATCH, ReconciliationOutcome.MISMATCH],
    )
    assert result.value is None
    assert result.reasons == {NotReportableReason.RECONCILIATION_MISMATCH}
    ok = detail_sum(
        _rows(),
        AMOUNT,
        view=VIEW,
        reconciliation=[ReconciliationOutcome.BOTH_EMPTY, ReconciliationOutcome.NOT_CHECKED],
    )
    assert ok.reportable


def test_an_unpopulated_column_is_not_reportable_never_zero() -> None:
    blank = [
        _row(RowRole.DETAIL, ""),
        _row(RowRole.DETAIL, ""),
        _row(RowRole.GROUP_HEADER, "$1.00"),
    ]
    result = detail_sum(blank, AMOUNT, view=VIEW)
    assert result.value is None
    assert result.reasons == {NotReportableReason.SOURCE_COLUMN_UNPOPULATED}
    unloaded = MeasureColumn(
        "synthetic.budget", Additivity.ADDITIVE, unpopulated_when_all_zero=True
    )
    zeros = [_row(RowRole.DETAIL, "$0.00"), _row(RowRole.DETAIL, "")]
    assert detail_sum(zeros, unloaded, view=VIEW).reasons == {
        NotReportableReason.SOURCE_COLUMN_UNPOPULATED
    }
    # The same zeros in an ordinary column are a verified zero.
    assert detail_sum(zeros, AMOUNT, view=VIEW).value == Decimal("0.0000")


def test_a_refused_detail_cell_makes_the_measure_not_reportable() -> None:
    rows = [_row(RowRole.DETAIL, "$1.00"), _row(RowRole.DETAIL, "$1.0")]
    result = detail_sum(rows, AMOUNT, view=VIEW)
    assert result.value is None
    assert result.reasons == {NotReportableReason.TYPE_ERROR_PRESENT}


def test_commitments_are_summed_per_commitment_and_budget_code() -> None:
    rows = [
        _row(RowRole.DETAIL, "$5.00", key=("commitment:T9.1", "C1")),
        _row(RowRole.DETAIL, "$7.00", key=("commitment:T9.1", "C2")),
        _row(RowRole.DETAIL, "$1.00", key=("commitment:T9.1", "C1")),
        _row(RowRole.GROUP_HEADER, "$13.00", key=("commitment:T9.1", "C1")),
    ]
    sums = keyed_detail_sums(rows, AMOUNT, view=VIEW)
    assert {key: value.value for key, value in sums.items()} == {
        ("commitment:T9.1", "C1"): Decimal("6.0000"),
        ("commitment:T9.1", "C2"): Decimal("7.0000"),
    }


def test_derivation_blockers() -> None:
    assert derivation_blockers(None, None) == {NotReportableReason.NO_SNAPSHOT}
    assert derivation_blockers(DerivationState.CLASSIFIED, None) == frozenset()
    assert derivation_blockers(
        DerivationState.QUARANTINED, QuarantineReason.UNKNOWN_HEADER_SIGNATURE
    ) == {NotReportableReason.SNAPSHOT_QUARANTINED}
    assert derivation_blockers(
        DerivationState.QUARANTINED, QuarantineReason.BINDING_PROJECT_NUMBER_MISMATCH
    ) == {
        NotReportableReason.SNAPSHOT_QUARANTINED,
        NotReportableReason.BINDING_PROJECT_NUMBER_MISMATCH,
    }
    blocked = detail_sum(_rows(), AMOUNT, view=VIEW, blockers=derivation_blockers(None, None))
    assert blocked.value is None


def test_statuses_map_through_a_table_and_unmapped_is_unknown() -> None:
    exact = MappingProxyType({"Yes it is": StatusClass.APPROVED, "Gone": StatusClass.VOID})
    prefixes = MappingProxyType({"Later - ": StatusClass.PENDING})
    assert classify_status("Yes it is", exact=exact) is StatusClass.APPROVED
    assert classify_status("Later - pricing", exact=exact, prefixes=prefixes) is StatusClass.PENDING
    assert classify_status("later - pricing", exact=exact, prefixes=prefixes) is StatusClass.UNKNOWN
    assert classify_status("", exact=exact, prefixes=prefixes) is StatusClass.UNKNOWN


def test_filter_semantics_are_unknown_unless_declared() -> None:
    assert filter_qualifiers(FilterSemantics.UNKNOWN) == {ReportQualifier.FILTER_SEMANTICS_UNKNOWN}
    assert filter_qualifiers(FilterSemantics.OPERATOR_DECLARED) == frozenset()
