"""The row-role classifier (plan section 4.3; grain analysis sections 2 and 3).

Pure and parameterised by a family's group-key columns (none, 1 or 2). It walks
the data rows in order and gives every row exactly one role:

1. a row whose width is not the header's is `malformed` (`width_mismatch`);
2. every cell empty is a `spacer`;
3. a first cell holding the literal `Grand Totals` is the `grand_total`;
4. the level-1 key filled starts a level-1 group (`(Blank)` is a real key);
5. the level-2 key filled with the level-1 key empty, inside a level-1 group,
   starts a level-2 group; outside one it is `malformed`;
6. any other row is a `detail` row inheriting the current group path;
7. a group header with no detail row before the next header of the same or a
   higher level, the grand total, or the end of the file is re-labelled
   `grouping_only`. A level-1 header followed directly by its level-2 headers
   keeps its role when detail follows under them.

Every derivation's role counts must sum to its data-row count
(`role_counts` raises otherwise), and only `detail` rows ever reach a sum.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from my_pa.domain.project_reports.model import (
    UNCLASSIFIED_COUNT_KEY,
    CompletenessClass,
    RowReason,
    RowRole,
)

__all__ = [
    "GRAND_TOTAL_MARKER",
    "MAX_MALFORMED_PERCENT",
    "ClassifiedRow",
    "GroupKeys",
    "PathStep",
    "RoleCountError",
    "classify_rows",
    "completeness_class",
    "malformed_ratio_exceeded",
    "quarantined_role_counts",
    "role_counts",
]

#: The first cell of the report-total row.
GRAND_TOTAL_MARKER: Final = "Grand Totals"
#: Ruling D17: more than 1 % malformed rows quarantines the derivation.
MAX_MALFORMED_PERCENT: Final = 1

_HEADER_ROLES: Final = frozenset({RowRole.GROUP_HEADER, RowRole.GROUPING_ONLY})


class RoleCountError(ValueError):
    """The role counts do not account for every data row exactly once."""


@dataclass(frozen=True, slots=True)
class GroupKeys:
    """The 0-based group-key columns of a family view; level 2 needs level 1."""

    level1: int | None = None
    level2: int | None = None

    def __post_init__(self) -> None:
        for column in (self.level1, self.level2):
            if column is not None and (type(column) is not int or column < 0):
                raise ValueError("a group-key column is a non-negative index")
        if self.level2 is not None and (self.level1 is None or self.level2 == self.level1):
            raise ValueError("a level-2 key needs a distinct level-1 key")


@dataclass(frozen=True, slots=True)
class PathStep:
    """One enclosing group: its level, its raw key and its header row ordinal."""

    level: int
    key: str
    header_ordinal: int


@dataclass(frozen=True, slots=True)
class ClassifiedRow:
    """One data row's role; `ordinal` is 1-based after the header record."""

    ordinal: int
    role: RowRole
    group_level: int | None = None
    group_key: str | None = None
    group_path: tuple[PathStep, ...] = ()
    reason: RowReason | None = None

    @property
    def parent_header_ordinal(self) -> int | None:
        """The innermost enclosing header (a header's own step excluded)."""
        steps = self.group_path[:-1] if self.role in _HEADER_ROLES else self.group_path
        return steps[-1].header_ordinal if steps else None


def _provisional(rows: Sequence[Sequence[str]], width: int, keys: GroupKeys) -> list[ClassifiedRow]:
    out: list[ClassifiedRow] = []
    level1: PathStep | None = None
    level2: PathStep | None = None
    key1, key2 = keys.level1, keys.level2
    for index, cells in enumerate(rows):
        ordinal = index + 1
        if len(cells) != width:
            out.append(ClassifiedRow(ordinal, RowRole.MALFORMED, reason=RowReason.WIDTH_MISMATCH))
        elif all(cell == "" for cell in cells):
            out.append(ClassifiedRow(ordinal, RowRole.SPACER))
        elif cells[0] == GRAND_TOTAL_MARKER:
            level1 = level2 = None
            out.append(ClassifiedRow(ordinal, RowRole.GRAND_TOTAL))
        elif key1 is not None and cells[key1] != "":
            level1 = PathStep(1, cells[key1], ordinal)
            level2 = None
            out.append(ClassifiedRow(ordinal, RowRole.GROUP_HEADER, 1, level1.key, (level1,)))
        elif key2 is not None and cells[key2] != "":
            if level1 is None:
                out.append(ClassifiedRow(ordinal, RowRole.MALFORMED))
                continue
            level2 = PathStep(2, cells[key2], ordinal)
            out.append(
                ClassifiedRow(ordinal, RowRole.GROUP_HEADER, 2, level2.key, (level1, level2))
            )
        else:
            path = tuple(step for step in (level1, level2) if step is not None)
            out.append(ClassifiedRow(ordinal, RowRole.DETAIL, group_path=path))
    return out


def _has_detail(rows: Sequence[ClassifiedRow], start: int, level: int) -> bool:
    for row in rows[start + 1 :]:
        if row.role is RowRole.GRAND_TOTAL:
            return False
        if row.role is RowRole.GROUP_HEADER and row.group_level is not None:
            if row.group_level <= level:
                return False
        elif row.role is RowRole.DETAIL:
            return True
    return False


def classify_rows(
    rows: Sequence[Sequence[str]], *, width: int, keys: GroupKeys
) -> tuple[ClassifiedRow, ...]:
    """Every data row's role, in order (rules 1-7 of the module docstring)."""
    if type(width) is not int or width < 1:
        raise ValueError("the header width is a positive integer")
    for column in (keys.level1, keys.level2):
        if column is not None and column >= width:
            raise ValueError("a group-key column lies outside the header")
    provisional = _provisional(rows, width, keys)
    result: list[ClassifiedRow] = []
    for index, row in enumerate(provisional):
        if (
            row.role is RowRole.GROUP_HEADER
            and row.group_level is not None
            and not _has_detail(provisional, index, row.group_level)
        ):
            result.append(
                ClassifiedRow(
                    row.ordinal,
                    RowRole.GROUPING_ONLY,
                    row.group_level,
                    row.group_key,
                    row.group_path,
                )
            )
        else:
            result.append(row)
    return tuple(result)


def role_counts(rows: Sequence[ClassifiedRow], data_row_count: int) -> Mapping[str, int]:
    """Every role's count (zeros included); raises unless they sum to the data rows."""
    counts = dict.fromkeys((role.value for role in RowRole), 0)
    for row in rows:
        counts[row.role.value] += 1
    if sum(counts.values()) != data_row_count:
        raise RoleCountError("the role counts do not sum to the data-row count")
    # The sum above guards the count; this guards a row classified twice or out
    # of order (strictly increasing ordinals inside 1..n).
    ordinals = [row.ordinal for row in rows]
    if ordinals != sorted(set(ordinals)) or any(not 1 <= o <= data_row_count for o in ordinals):
        raise RoleCountError("every data row needs exactly one role, in order")
    return MappingProxyType(counts)


def quarantined_role_counts(data_row_count: int) -> Mapping[str, int]:
    """A quarantined derivation classifies nothing: every row is `unclassified`."""
    if type(data_row_count) is not int or data_row_count < 0:
        raise ValueError("a data-row count is a non-negative integer")
    return MappingProxyType({UNCLASSIFIED_COUNT_KEY: data_row_count})


def completeness_class(counts: Mapping[str, int]) -> CompletenessClass:
    """`populated` with any detail row, else `grouping_only` with one, else `valid_empty`."""
    if counts.get(RowRole.DETAIL.value, 0) > 0:
        return CompletenessClass.POPULATED
    if counts.get(RowRole.GROUPING_ONLY.value, 0) > 0:
        return CompletenessClass.GROUPING_ONLY
    return CompletenessClass.VALID_EMPTY


def malformed_ratio_exceeded(counts: Mapping[str, int], data_row_count: int) -> bool:
    """More than `MAX_MALFORMED_PERCENT` % of the data rows are malformed (integer test)."""
    malformed = counts.get(RowRole.MALFORMED.value, 0)
    return malformed * 100 > data_row_count * MAX_MALFORMED_PERCENT
