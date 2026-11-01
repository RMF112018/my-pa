"""CPM Workbench S5b-2: the on-demand A-to-B delta `cpm-workbench-full-delta-v1`.

Contract: `docs/architecture/cpm-workbench-worker-capabilities-contract.md`
section 3.10 (R2 section 29). Pure and standard-library only: the repository
streams each side's accepted-run activity and milestone rows ordered by
`published_activity_id COLLATE "C"` (byte order of UTF-8 = code-point order =
Python `str` order), the application asks the repository once which of the
B-only Stable Activities were observed before A, and `compare_publications`
merges the 2 sorted sides in one pass.

Nothing here fabricates a number: a duration or date delta exists only when
both sides are `published_value`; any other state difference is
`field_state_changed` with both states and no delta. Provenance (page,
ordinal, box, style) is never a change, and neither is a marker-only
difference on an equal date (residual U2-07).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.schedule.model import (
    MAX_PUBLISHED_ACTIVITY_ID_CHARACTERS,
    ScheduleCellState,
    ScheduleDateCell,
    ScheduleDurationCell,
    ScheduleFieldCode,
    ScheduleRowType,
)

__all__ = [
    "DELTA_ALGORITHM_VERSION",
    "ScheduleActivityIdentity",
    "ScheduleChange",
    "ScheduleChangeKind",
    "ScheduleChangeSet",
    "ScheduleChangeSide",
    "ScheduleComparisonRow",
    "ScheduleHierarchySide",
    "change_sort_key",
    "compare_publications",
    "unmatched_target_activity_ids",
]

#: The versioned algorithm name every changes answer and cursor carries.
DELTA_ALGORITHM_VERSION: Final = "cpm-workbench-full-delta-v1"


class ScheduleChangeKind(StrEnum):
    """R2 section 43.2 change kinds; declaration order is the sort rank 1..11."""

    ADDED = "added"
    REMOVED = "removed"
    REINTRODUCED = "reintroduced"
    RENAMED = "renamed"
    ROW_TYPE_CHANGED = "row_type_changed"
    ORIGINAL_DURATION_CHANGED = "original_duration_changed"
    REMAINING_DURATION_CHANGED = "remaining_duration_changed"
    START_CHANGED = "start_changed"
    FINISH_CHANGED = "finish_changed"
    HIERARCHY_CHANGED = "hierarchy_changed"
    FIELD_STATE_CHANGED = "field_state_changed"


_KIND_RANK: Final[Mapping[ScheduleChangeKind, int]] = MappingProxyType(
    {kind: rank for rank, kind in enumerate(ScheduleChangeKind, start=1)}
)
#: `ScheduleFieldCode` declaration order; a change with no field ranks 0.
_FIELD_RANK: Final[Mapping[ScheduleFieldCode, int]] = MappingProxyType(
    {field: rank for rank, field in enumerate(ScheduleFieldCode, start=1)}
)
_COMPARABLE_TYPES: Final = frozenset({ScheduleRowType.ACTIVITY, ScheduleRowType.MILESTONE})


@dataclass(frozen=True, slots=True)
class ScheduleComparisonRow:
    """One side's accepted-run activity or milestone row, as the delta reads it."""

    schedule_activity_id: str
    published_activity_id: str
    activity_name: str
    row_type: ScheduleRowType
    hierarchy_path: tuple[str, ...] | None
    original_duration: ScheduleDurationCell
    remaining_duration: ScheduleDurationCell
    start: ScheduleDateCell
    finish: ScheduleDateCell

    def __post_init__(self) -> None:
        validate_identifier(self.schedule_activity_id, IdKind.SCHEDULE_ACTIVITY)
        published: object = self.published_activity_id
        if (
            not isinstance(published, str)
            or not 1 <= len(published) <= MAX_PUBLISHED_ACTIVITY_ID_CHARACTERS
        ):
            raise ValueError("a compared row carries a published activity id")
        name: object = self.activity_name
        if not isinstance(name, str) or not name:
            raise ValueError("a compared row carries an activity name")
        if self.row_type not in _COMPARABLE_TYPES:
            raise ValueError("only activity and milestone rows are compared")


@dataclass(frozen=True, slots=True)
class ScheduleActivityIdentity:
    """The `{activity_name, row_type}` side of an added, removed or reintroduced change."""

    activity_name: str
    row_type: ScheduleRowType


@dataclass(frozen=True, slots=True)
class ScheduleHierarchySide:
    """One side of a hierarchy `field_state_changed` (E-09): a path, or NULL as ambiguous."""

    state: ScheduleCellState
    path: tuple[str, ...] | None

    def __post_init__(self) -> None:
        if (self.path is None) != (self.state is ScheduleCellState.AMBIGUOUS):
            raise ValueError("a hierarchy side is a published path or an ambiguous NULL")


#: What a change's `before`/`after` may hold, by kind (contract section 3.10).
type ScheduleChangeSide = (
    ScheduleActivityIdentity
    | str
    | ScheduleRowType
    | ScheduleDurationCell
    | ScheduleDateCell
    | tuple[str, ...]
    | ScheduleHierarchySide
    | None
)


@dataclass(frozen=True, slots=True)
class ScheduleChange:
    """One change from A to B of one Stable Activity."""

    schedule_activity_id: str
    published_activity_id: str
    change_kind: ScheduleChangeKind
    field: ScheduleFieldCode | None
    before: ScheduleChangeSide
    after: ScheduleChangeSide
    delta_calendar_days: int | None = None
    delta_source_units: Decimal | None = None

    def __post_init__(self) -> None:
        if self.delta_calendar_days is not None and self.delta_source_units is not None:
            raise ValueError("a change carries at most one delta")


@dataclass(frozen=True, slots=True)
class ScheduleChangeSet:
    """The full, sorted change list and its per-kind counts (all 11 keys)."""

    changes: tuple[ScheduleChange, ...]
    counts_by_kind: Mapping[ScheduleChangeKind, int]

    def __post_init__(self) -> None:
        if tuple(self.counts_by_kind) != tuple(ScheduleChangeKind):
            raise ValueError("counts name every change kind in rank order")
        if sum(self.counts_by_kind.values()) != len(self.changes):
            raise ValueError("counts sum to the change list")


def change_sort_key(change: ScheduleChange) -> tuple[str, int, int]:
    """`(published_activity_id, kind_rank, field_rank)`; a null field ranks 0."""
    field = 0 if change.field is None else _FIELD_RANK[change.field]
    return (change.published_activity_id, _KIND_RANK[change.change_kind], field)


def _rank(change: ScheduleChange) -> tuple[int, int]:
    return change_sort_key(change)[1:]


def unmatched_target_activity_ids(
    from_rows: Iterable[ScheduleComparisonRow], to_rows: Iterable[ScheduleComparisonRow]
) -> frozenset[str]:
    """The Stable Activities of B that A does not carry (the `prior_observations` question)."""
    seen = {row.schedule_activity_id for row in from_rows}
    return frozenset(
        row.schedule_activity_id for row in to_rows if row.schedule_activity_id not in seen
    )


def _identity(row: ScheduleComparisonRow) -> ScheduleActivityIdentity:
    return ScheduleActivityIdentity(activity_name=row.activity_name, row_type=row.row_type)


def _only(row: ScheduleComparisonRow, kind: ScheduleChangeKind, *, before: bool) -> ScheduleChange:
    side = _identity(row)
    return ScheduleChange(
        schedule_activity_id=row.schedule_activity_id,
        published_activity_id=row.published_activity_id,
        change_kind=kind,
        field=None,
        before=side if before else None,
        after=None if before else side,
    )


def _durations(
    a: ScheduleComparisonRow,
    b: ScheduleComparisonRow,
    field: ScheduleFieldCode,
    kind: ScheduleChangeKind,
    before: ScheduleDurationCell,
    after: ScheduleDurationCell,
) -> Iterator[ScheduleChange]:
    published = ScheduleCellState.PUBLISHED_VALUE
    if before.state is published and after.state is published:
        if before.value is None or after.value is None:  # pragma: no cover - cell invariant
            raise ValueError("a published duration carries a value")
        # R7-F11: compared as Decimal, never as text.
        if before.value != after.value:
            yield ScheduleChange(
                a.schedule_activity_id,
                b.published_activity_id,
                kind,
                field,
                before,
                after,
                delta_source_units=after.value - before.value,
            )
    elif before.state is not after.state:
        yield ScheduleChange(
            a.schedule_activity_id,
            b.published_activity_id,
            ScheduleChangeKind.FIELD_STATE_CHANGED,
            field,
            before,
            after,
        )


def _dates(
    a: ScheduleComparisonRow,
    b: ScheduleComparisonRow,
    field: ScheduleFieldCode,
    kind: ScheduleChangeKind,
    before: ScheduleDateCell,
    after: ScheduleDateCell,
) -> Iterator[ScheduleChange]:
    published = ScheduleCellState.PUBLISHED_VALUE
    if before.state is published and after.state is published:
        if before.value is None or after.value is None:  # pragma: no cover - cell invariant
            raise ValueError("a published date carries a value")
        # A marker-only difference on an equal date is not a v1 change (U2-07).
        if before.value != after.value:
            yield ScheduleChange(
                a.schedule_activity_id,
                b.published_activity_id,
                kind,
                field,
                before,
                after,
                delta_calendar_days=(after.value - before.value).days,
            )
    elif before.state is not after.state:
        yield ScheduleChange(
            a.schedule_activity_id,
            b.published_activity_id,
            ScheduleChangeKind.FIELD_STATE_CHANGED,
            field,
            before,
            after,
        )


def _hierarchy_side(path: tuple[str, ...] | None) -> ScheduleHierarchySide:
    if path is None:
        return ScheduleHierarchySide(state=ScheduleCellState.AMBIGUOUS, path=None)
    return ScheduleHierarchySide(state=ScheduleCellState.PUBLISHED_VALUE, path=path)


def _matched(a: ScheduleComparisonRow, b: ScheduleComparisonRow) -> Iterator[ScheduleChange]:
    """Every rule over one matched pair, evaluated independently (contract 3.10)."""
    if a.activity_name != b.activity_name:
        yield ScheduleChange(
            a.schedule_activity_id,
            b.published_activity_id,
            ScheduleChangeKind.RENAMED,
            ScheduleFieldCode.ACTIVITY_NAME,
            a.activity_name,
            b.activity_name,
        )
    if a.row_type is not b.row_type:
        yield ScheduleChange(
            a.schedule_activity_id,
            b.published_activity_id,
            ScheduleChangeKind.ROW_TYPE_CHANGED,
            None,
            a.row_type,
            b.row_type,
        )
    yield from _durations(
        a,
        b,
        ScheduleFieldCode.ORIGINAL_DURATION,
        ScheduleChangeKind.ORIGINAL_DURATION_CHANGED,
        a.original_duration,
        b.original_duration,
    )
    yield from _durations(
        a,
        b,
        ScheduleFieldCode.REMAINING_DURATION,
        ScheduleChangeKind.REMAINING_DURATION_CHANGED,
        a.remaining_duration,
        b.remaining_duration,
    )
    yield from _dates(
        a, b, ScheduleFieldCode.START, ScheduleChangeKind.START_CHANGED, a.start, b.start
    )
    yield from _dates(
        a, b, ScheduleFieldCode.FINISH, ScheduleChangeKind.FINISH_CHANGED, a.finish, b.finish
    )
    before, after = a.hierarchy_path, b.hierarchy_path
    if before is not None and after is not None:
        if before != after:
            yield ScheduleChange(
                a.schedule_activity_id,
                b.published_activity_id,
                ScheduleChangeKind.HIERARCHY_CHANGED,
                ScheduleFieldCode.HIERARCHY,
                before,
                after,
            )
    elif (before is None) != (after is None):
        yield ScheduleChange(
            a.schedule_activity_id,
            b.published_activity_id,
            ScheduleChangeKind.FIELD_STATE_CHANGED,
            ScheduleFieldCode.HIERARCHY,
            _hierarchy_side(before),
            _hierarchy_side(after),
        )


def compare_publications(
    from_rows: Sequence[ScheduleComparisonRow] | Iterable[ScheduleComparisonRow],
    to_rows: Sequence[ScheduleComparisonRow] | Iterable[ScheduleComparisonRow],
    prior: frozenset[str],
) -> ScheduleChangeSet:
    """The full A-to-B change list, sorted, with counts over every kind.

    Both sides must be ordered by `published_activity_id` in code-point order
    with no repeat (the repository's `COLLATE "C"` order over one accepted
    run, whose IDs canonicalization proved unique). One merge pass: each step
    compares the 2 current IDs at most twice and consumes at least 1 row.
    Exact `published_activity_id` equality inside one Series is the same Stable
    Activity. `prior` names the B-only Stable Activities observed in an
    eligible publication of the Series before A: those are `reintroduced`,
    every other B-only one `added`.
    """
    left = iter(from_rows)
    right = iter(to_rows)
    a = next(left, None)
    b = next(right, None)
    changes: list[ScheduleChange] = []
    while a is not None or b is not None:
        if b is None or (a is not None and a.published_activity_id < b.published_activity_id):
            if a is None:  # pragma: no cover - loop condition
                break
            changes.append(_only(a, ScheduleChangeKind.REMOVED, before=True))
            a = next(left, None)
        elif a is None or a.published_activity_id != b.published_activity_id:
            kind = (
                ScheduleChangeKind.REINTRODUCED
                if b.schedule_activity_id in prior
                else ScheduleChangeKind.ADDED
            )
            changes.append(_only(b, kind, before=False))
            b = next(right, None)
        else:
            if a.schedule_activity_id != b.schedule_activity_id:
                raise ValueError("one published id inside one series is one stable activity")
            # Within one activity, rank order; across activities the merge
            # already emits published-ID order, so no global sort compares IDs.
            changes.extend(sorted(_matched(a, b), key=_rank))
            a = next(left, None)
            b = next(right, None)
    counts = dict.fromkeys(ScheduleChangeKind, 0)
    for change in changes:
        counts[change.change_kind] += 1
    return ScheduleChangeSet(changes=tuple(changes), counts_by_kind=MappingProxyType(counts))
