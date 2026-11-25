"""Project reports: the row-role classifier (plan section 4.3, 12.1; PULSE-AC-02, AC-06).

Synthetic rows only: generic header names, invented keys and amounts.
"""

from __future__ import annotations

import pytest

from my_pa.domain.project_reports.measures import (
    MeasureColumn,
    MeasureRow,
    detail_sum,
)
from my_pa.domain.project_reports.model import (
    UNCLASSIFIED_COUNT_KEY,
    Additivity,
    CompletenessClass,
    FamilyView,
    RowReason,
    RowRole,
)
from my_pa.domain.project_reports.money import read_cell
from my_pa.domain.project_reports.roles import (
    GRAND_TOTAL_MARKER,
    ClassifiedRow,
    GroupKeys,
    PathStep,
    RoleCountError,
    classify_rows,
    completeness_class,
    malformed_ratio_exceeded,
    quarantined_role_counts,
    role_counts,
)

NO_KEYS = GroupKeys()
ONE_LEVEL = GroupKeys(level1=0)
TWO_LEVELS = GroupKeys(level1=0, level2=1)


def _roles(rows: list[list[str]], width: int, keys: GroupKeys) -> list[RowRole]:
    return [row.role for row in classify_rows(rows, width=width, keys=keys)]


def test_a_flat_export_is_all_detail_with_a_grand_total() -> None:
    rows = [["1", "a"], ["2", "b"], [GRAND_TOTAL_MARKER, ""]]
    assert _roles(rows, 2, NO_KEYS) == [RowRole.DETAIL, RowRole.DETAIL, RowRole.GRAND_TOTAL]


def test_a_spacer_is_every_cell_empty() -> None:
    rows = [["G1", "", ""], ["", "x", "1"], ["", "", ""], ["", "y", "2"]]
    assert _roles(rows, 3, ONE_LEVEL) == [
        RowRole.GROUP_HEADER,
        RowRole.DETAIL,
        RowRole.SPACER,
        RowRole.DETAIL,
    ]


def test_a_one_level_export_inherits_the_group_path() -> None:
    rows = [["G1", "", "3"], ["", "x", "1"], ["", "y", "2"], ["(Blank)", "", "5"], ["", "z", "5"]]
    classified = classify_rows(rows, width=3, keys=ONE_LEVEL)
    assert [row.role for row in classified] == [
        RowRole.GROUP_HEADER,
        RowRole.DETAIL,
        RowRole.DETAIL,
        RowRole.GROUP_HEADER,
        RowRole.DETAIL,
    ]
    assert classified[0].group_level == 1 and classified[0].group_key == "G1"
    assert classified[0].parent_header_ordinal is None
    assert classified[1].group_path == (PathStep(1, "G1", 1),)
    assert classified[1].parent_header_ordinal == 1
    # `(Blank)` is a real key with a real subtotal, not a missing one.
    assert classified[3].group_key == "(Blank)"
    assert classified[4].group_path == (PathStep(1, "(Blank)", 4),)


def test_a_two_level_export_carries_both_levels() -> None:
    rows = [
        ["V1", "", "3"],
        ["", "S1", "3"],
        ["", "", "1"],
        ["", "", "2"],
    ]
    classified = classify_rows(rows, width=3, keys=TWO_LEVELS)
    assert [row.role for row in classified] == [
        RowRole.GROUP_HEADER,
        RowRole.GROUP_HEADER,
        RowRole.DETAIL,
        RowRole.DETAIL,
    ]
    assert classified[1].group_level == 2
    assert classified[1].parent_header_ordinal == 1
    assert classified[2].group_path == (PathStep(1, "V1", 1), PathStep(2, "S1", 2))
    assert classified[2].parent_header_ordinal == 2


def test_a_header_with_no_detail_is_relabelled_grouping_only() -> None:
    rows = [["G1", "", ""], ["G2", "", "4"], ["", "x", "4"], ["G3", "", ""]]
    classified = classify_rows(rows, width=3, keys=ONE_LEVEL)
    assert [row.role for row in classified] == [
        RowRole.GROUPING_ONLY,
        RowRole.GROUP_HEADER,
        RowRole.DETAIL,
        RowRole.GROUPING_ONLY,
    ]
    # A grouping-only row keeps its level and key (the export stated the group).
    assert (classified[0].group_level, classified[0].group_key) == (1, "G1")


def test_a_header_before_the_grand_total_with_no_detail_is_grouping_only() -> None:
    rows = [["G1", "", "1"], ["", "x", "1"], ["G2", "", ""], [GRAND_TOTAL_MARKER, "", "1"]]
    assert _roles(rows, 3, ONE_LEVEL)[2] is RowRole.GROUPING_ONLY


def test_a_level_1_header_followed_by_its_level_2_headers_stays_a_header() -> None:
    rows = [
        ["V1", "", ""],  # level 1, directly followed by level-2 headers
        ["", "S1", ""],  # level 2 with no detail before the next level-2 header
        ["", "S2", ""],  # level 2 with detail
        ["", "", "1"],
        ["V2", "", ""],  # level 1 whose only level-2 header has no detail
        ["", "S3", ""],
    ]
    assert _roles(rows, 3, TWO_LEVELS) == [
        RowRole.GROUP_HEADER,
        RowRole.GROUPING_ONLY,
        RowRole.GROUP_HEADER,
        RowRole.DETAIL,
        RowRole.GROUPING_ONLY,
        RowRole.GROUPING_ONLY,
    ]


def test_a_wrong_width_is_malformed_and_a_stray_level_2_header_too() -> None:
    rows = [["", "S1", "1"], ["a", "b"], ["V1", "", ""], ["", "", "1"]]
    classified = classify_rows(rows, width=3, keys=TWO_LEVELS)
    assert [row.role for row in classified] == [
        RowRole.MALFORMED,
        RowRole.MALFORMED,
        RowRole.GROUP_HEADER,
        RowRole.DETAIL,
    ]
    assert classified[1].reason is RowReason.WIDTH_MISMATCH


def test_role_counts_sum_to_the_data_rows_and_name_every_role() -> None:
    rows = [["G1", "", "1"], ["", "x", "1"], ["", "", ""], ["bad"], [GRAND_TOTAL_MARKER, "", "1"]]
    classified = classify_rows(rows, width=3, keys=ONE_LEVEL)
    counts = role_counts(classified, len(rows))
    assert set(counts) == {role.value for role in RowRole}
    assert sum(counts.values()) == len(rows)
    assert counts == {
        "detail": 1,
        "group_header": 1,
        "grand_total": 1,
        "spacer": 1,
        "grouping_only": 0,
        "malformed": 1,
    }


def test_role_counts_refuse_a_lost_row() -> None:
    classified = classify_rows([["1"], ["2"], ["3"]], width=1, keys=NO_KEYS)
    with pytest.raises(RoleCountError, match="sum"):
        role_counts(classified[:2], 3)


def test_role_counts_refuse_a_doubled_or_reordered_row() -> None:
    classified = classify_rows([["1"], ["2"], ["3"]], width=1, keys=NO_KEYS)
    with pytest.raises(RoleCountError):
        role_counts((*classified, classified[-1]), 3)
    with pytest.raises(RoleCountError, match="exactly one role"):
        role_counts((classified[0], classified[0], classified[2]), 3)
    with pytest.raises(RoleCountError, match="exactly one role"):
        role_counts((classified[1], classified[0], classified[2]), 3)


def test_a_quarantined_derivation_counts_every_row_unclassified() -> None:
    assert quarantined_role_counts(7) == {UNCLASSIFIED_COUNT_KEY: 7}
    assert UNCLASSIFIED_COUNT_KEY not in {role.value for role in RowRole}


def test_completeness_classes() -> None:
    def cls(rows: list[list[str]]) -> CompletenessClass:
        classified = classify_rows(rows, width=2, keys=ONE_LEVEL)
        return completeness_class(role_counts(classified, len(rows)))

    assert cls([["G", ""], ["", "1"]]) is CompletenessClass.POPULATED
    assert cls([["G", ""]]) is CompletenessClass.GROUPING_ONLY
    assert cls([]) is CompletenessClass.VALID_EMPTY
    assert cls([["", ""]]) is CompletenessClass.VALID_EMPTY


def test_the_malformed_ratio_is_above_one_percent_in_integers() -> None:
    assert not malformed_ratio_exceeded({"malformed": 1}, 100)
    assert malformed_ratio_exceeded({"malformed": 2}, 100)
    assert malformed_ratio_exceeded({"malformed": 1}, 99)
    assert not malformed_ratio_exceeded({}, 0)


def test_group_keys_are_validated() -> None:
    with pytest.raises(ValueError, match="level-1"):
        GroupKeys(level2=1)
    with pytest.raises(ValueError, match="level-1"):
        GroupKeys(level1=1, level2=1)
    with pytest.raises(ValueError, match="outside"):
        classify_rows([["a"]], width=1, keys=GroupKeys(level1=2))


def test_the_two_level_double_count_returns_the_detail_sum() -> None:
    """Grain section 6: detail-only gives 99 where a naive 1-level reading gives 198."""
    rows = [
        ["V1", "", "99"],
        ["", "S1", "40"],
        ["", "", "15"],
        ["", "", "25"],
        ["", "S2", "59"],
        ["", "", "59"],
        [GRAND_TOTAL_MARKER, "", "99"],
    ]
    classified = classify_rows(rows, width=3, keys=TWO_LEVELS)
    measure_rows = [
        MeasureRow(FamilyView.OPEN_BY_VENDOR, row.role, read_cell(cells[2], money=False))
        for row, cells in zip(classified, rows, strict=True)
    ]
    column = MeasureColumn("synthetic.count", Additivity.ADDITIVE)
    result = detail_sum(measure_rows, column, view=FamilyView.OPEN_BY_VENDOR)
    assert result.value is not None and int(result.value) == 99
    naive = sum(int(cells[2]) for cells in rows[1:6])
    assert naive == 198


def test_classified_rows_are_immutable() -> None:
    row = ClassifiedRow(1, RowRole.DETAIL)
    with pytest.raises(AttributeError):
        row.role = RowRole.SPACER  # type: ignore[misc]
