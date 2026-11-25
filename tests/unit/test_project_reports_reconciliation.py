"""Project reports: stated-total reconciliation and the cross-report check (plan 7.4, D15).

Synthetic rows and amounts only.
"""

from __future__ import annotations

from decimal import Decimal

from my_pa.domain.project_reports.model import (
    Additivity,
    ReconciliationOutcome,
    StatusClass,
    TotalScope,
)
from my_pa.domain.project_reports.money import NumericCell, read_cell
from my_pa.domain.project_reports.reconciliation import (
    BLANK_GROUP_KEY,
    CROSS_CHECK_KIND,
    StatedTotalCheck,
    TotalColumn,
    compare,
    cross_report_check,
    reconcile_totals,
    summarize,
)
from my_pa.domain.project_reports.roles import GRAND_TOTAL_MARKER, GroupKeys, classify_rows

MATCH = ReconciliationOutcome.MATCH
MISMATCH = ReconciliationOutcome.MISMATCH
BOTH_EMPTY = ReconciliationOutcome.BOTH_EMPTY
NOT_CHECKED = ReconciliationOutcome.NOT_CHECKED

AMOUNT = TotalColumn(2, "synthetic.amount", Additivity.ADDITIVE, money=True)
OTHER = TotalColumn(3, "synthetic.other", Additivity.ADDITIVE, money=True)
DAYS = TotalColumn(3, "synthetic.days", Additivity.NON_ADDITIVE, money=False)


def _checks(
    rows: list[list[str]], keys: GroupKeys, columns: list[TotalColumn]
) -> tuple[StatedTotalCheck, ...]:
    classified = classify_rows(rows, width=len(rows[0]), keys=keys)
    return reconcile_totals(classified, rows, columns)


def _money(text: str) -> NumericCell:
    return read_cell(text, money=True)


def test_compare_rules() -> None:
    one = _money("$1.00")
    assert compare(one, [_money("$0.40"), _money("$0.60")], Additivity.ADDITIVE)[0] is MATCH
    assert compare(one, [_money("$0.40")], Additivity.ADDITIVE)[0] is MISMATCH
    assert compare(_money(""), [_money(""), _money("")], Additivity.ADDITIVE)[0] is BOTH_EMPTY
    assert compare(_money(""), [], Additivity.ADDITIVE)[0] is BOTH_EMPTY
    assert compare(_money(""), [_money("$1.00")], Additivity.ADDITIVE)[0] is MISMATCH
    assert compare(one, [_money("")], Additivity.ADDITIVE)[0] is MISMATCH
    # A refused cell on either side is never a match (fail-closed).
    assert compare(_money("$1.0"), [_money("$1.00")], Additivity.ADDITIVE)[0] is MISMATCH
    assert compare(one, [_money("$1.00"), _money("x")], Additivity.ADDITIVE)[0] is MISMATCH
    assert compare(one, [one], Additivity.NON_ADDITIVE) == (NOT_CHECKED, None)
    assert compare(one, [one], Additivity.UNKNOWN) == (NOT_CHECKED, None)


def test_group_subtotals_reconcile_against_their_detail_only() -> None:
    rows = [
        ["G1", "", "$3.00", ""],
        ["", "a", "$1.00", ""],
        ["", "b", "$2.00", ""],
        ["G2", "", "$5.00", "$1.00"],
        ["", "c", "$4.00", "$1.00"],
        [GRAND_TOTAL_MARKER, "", "$8.00", "$1.00"],
    ]
    checks = _checks(rows, GroupKeys(level1=0), [AMOUNT, OTHER])
    outcomes = {(c.row_ordinal, c.column_index): c.outcome for c in checks}
    assert outcomes == {
        (1, 2): MATCH,
        (1, 3): BOTH_EMPTY,
        (4, 2): MISMATCH,
        (4, 3): MATCH,
        (6, 2): MISMATCH,  # the detail sum is 7.00
        (6, 3): MATCH,
    }
    first = checks[0]
    assert first.scope is TotalScope.GROUP and first.group_key == "G1"
    assert first.value == Decimal("3.0000") and first.computed_value == Decimal("3.0000")
    assert first.raw_text == "$3.00"
    grand = [c for c in checks if c.scope is TotalScope.GRAND]
    assert [c.computed_value for c in grand] == [Decimal("7.0000"), Decimal("1.0000")]


def test_a_level_1_subtotal_covers_its_level_2_detail_once() -> None:
    rows = [
        ["V1", "", "$10.00", ""],
        ["", "S1", "$4.00", ""],
        ["", "", "$4.00", ""],
        ["", "S2", "$6.00", ""],
        ["", "", "$1.00", ""],
        ["", "", "$5.00", ""],
        [GRAND_TOTAL_MARKER, "", "$10.00", ""],
    ]
    checks = _checks(rows, GroupKeys(level1=0, level2=1), [AMOUNT])
    assert [(c.row_ordinal, c.group_level, c.outcome) for c in checks] == [
        (1, 1, MATCH),
        (2, 2, MATCH),
        (4, 2, MATCH),
        (7, None, MATCH),
    ]
    assert checks[0].computed_value == Decimal("10.0000")


def test_the_grand_total_must_also_equal_the_level_1_headers() -> None:
    # The detail sums to 3.00 like the grand total, but the stated level-1
    # subtotal says 4.00: the grand total does not reconcile with its headers.
    rows = [["G1", "", "$4.00", ""], ["", "a", "$3.00", ""], [GRAND_TOTAL_MARKER, "", "$3.00", ""]]
    checks = _checks(rows, GroupKeys(level1=0), [AMOUNT])
    assert [c.outcome for c in checks] == [MISMATCH, MISMATCH]


def test_a_flat_grand_total_reconciles_against_detail() -> None:
    rows = [
        ["a", "", "$1.00", "3"],
        ["b", "", "$2.00", "4"],
        [GRAND_TOTAL_MARKER, "", "$3.00", "7"],
    ]
    checks = _checks(rows, GroupKeys(), [AMOUNT, DAYS])
    assert [c.outcome for c in checks] == [MATCH, NOT_CHECKED]
    # The non-additive total stays evidence: no computed value is offered.
    assert checks[1].computed_value is None and checks[1].additivity is Additivity.NON_ADDITIVE


def test_grouping_only_headers_are_not_reconciled_as_groups() -> None:
    rows = [["G1", "", "", ""], ["G2", "", "$1.00", ""], ["", "a", "$1.00", ""]]
    checks = _checks(rows, GroupKeys(level1=0), [AMOUNT])
    assert [c.row_ordinal for c in checks] == [2]


def test_the_summary_reports_both_units() -> None:
    rows = [
        ["G1", "", "$3.00", ""],
        ["", "a", "$3.00", ""],
        ["G2", "", "", ""],  # grouping only: no detail
        ["G3", "", "", "$2.00"],
        ["", "b", "", "$2.00"],
        ["G4", "", "$9.00", "$1.00"],
        ["", "c", "$1.00", "$1.00"],
        [GRAND_TOTAL_MARKER, "", "$4.00", "$3.00"],
    ]
    summary = summarize(_checks(rows, GroupKeys(level1=0), [AMOUNT, OTHER]))
    assert summary.group_columns == {"match": 3, "mismatch": 1, "both_empty": 2, "not_checked": 0}
    assert summary.groups_checked == 3
    assert summary.groups_all_columns_match == 2
    # The amount grand total equals its detail but not its level-1 headers.
    assert summary.grand_columns == {"match": 1, "mismatch": 1, "both_empty": 0, "not_checked": 0}


def test_the_cross_report_check_takes_approved_blank_lines_only() -> None:
    subtotals = [
        ("1", _money("$10.00")),
        ("2", _money("$5.00")),
        (BLANK_GROUP_KEY, _money("$9.00")),
    ]
    blank_lines = [
        (StatusClass.APPROVED, _money("$2.00")),
        (StatusClass.PENDING, _money("$3.00")),
        (StatusClass.VOID, _money("$4.00")),
        (StatusClass.APPROVED, _money("$1.00")),
    ]
    check = cross_report_check(_money("$18.00"), subtotals, blank_lines)
    assert check.kind == CROSS_CHECK_KIND
    assert check.outcome is MATCH
    assert (check.left_value, check.right_value) == (Decimal("18.0000"), Decimal("18.0000"))
    # The all-status total differs by exactly the pending and void amounts.
    assert cross_report_check(_money("$25.00"), subtotals, blank_lines).outcome is MISMATCH


def test_the_cross_report_check_without_its_pair_is_not_checked() -> None:
    check = cross_report_check(None, [("1", _money("$1.00"))], [])
    assert check.outcome is NOT_CHECKED
    assert check.left_value is None and check.right_value is None
