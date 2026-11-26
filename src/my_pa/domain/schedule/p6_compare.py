"""P6 XER S7-4b: the on-demand A-to-B delta `cpm-workbench-p6-delta-v1`.

Contract: `docs/architecture/schedule-xer-import-contract.md` sections 11.2-11.4.
Pure and standard-library only. The application reads both publications'
accepted runs (project, calendars, activities ordered by Activity ID in code
point order, relationships and the activity values of the captured fields both
capture sets hold), asks the repository once which of B's unmatched Stable
Activities were observed before A, and `compare_p6_publications` computes the
change list in one pass over each collection. Nothing is stored: the delta is
recomputed on every request and every answer and cursor names the algorithm.

Rules (11.3, 11.4):

- An activity is matched by its exact Activity ID inside the Series (one ID is
  one Stable Activity). A code only in A is `removed`; one only in B is `added`,
  or `reintroduced` when observed in an earlier publication of the Series. A
  renumbered activity (a changed code) stays `removed` + `added`; when the two
  rows share a P6 GUID an informational `renumber_candidate` names both codes --
  a hint, never a link, never a merged history.
- A matched pair is compared field by field, each rule independently; a date
  delta is signed calendar minutes `B - A`, a number delta is `B - A`, and a
  value present on one side only is a change with no delta.
- Relationships (both ends in the project) match by their (predecessor,
  successor) Activity-ID pair; an external relationship is not compared (its
  other end is outside the export) and is counted.
- Calendars match by P6 calendar id, else by a name unique among the unmatched
  calendars of both sides; the rest are counted, never reported as changes. An
  activity's calendar is compared by content (the calendar's data digest), so a
  re-import that renumbers calendars reports no `calendar_changed`.
- A captured field held by only one publication's capture set is counted
  `fields_not_comparable`, never reported as a change; a personal field is
  never compared here (its values are served only by
  `schedule_p6_field_values.list` to a holder of that grant), and is counted
  `fields_withheld`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final

__all__ = [
    "P6_DELTA_ALGORITHM_VERSION",
    "P6_DELTA_PROJECT_FIELDS",
    "P6Change",
    "P6ChangeKind",
    "P6ChangeScope",
    "P6ChangeSet",
    "P6DeltaActivity",
    "P6DeltaCalendar",
    "P6DeltaRelationship",
    "P6DeltaSide",
    "change_sort_key",
    "compare_p6_publications",
    "p6_unmatched_target_activity_ids",
]

#: The versioned algorithm name every P6 changes answer and cursor carries.
P6_DELTA_ALGORITHM_VERSION: Final = "cpm-workbench-p6-delta-v1"


class P6ChangeScope(StrEnum):
    """What a change is about; declaration order is the first sort rank."""

    PROJECT = "project"
    CALENDAR = "calendar"
    ACTIVITY = "activity"
    RELATIONSHIP = "relationship"


class P6ChangeKind(StrEnum):
    """Section 11.4 change kinds; declaration order is the kind rank inside a subject."""

    DATA_DATE_CHANGED = "data_date_changed"
    SETTINGS_CHANGED = "settings_changed"
    CALENDAR_WEEK_CHANGED = "calendar_week_changed"
    CALENDAR_EXCEPTIONS_CHANGED = "calendar_exceptions_changed"
    ADDED = "added"
    REMOVED = "removed"
    REINTRODUCED = "reintroduced"
    RENUMBER_CANDIDATE = "renumber_candidate"
    RENAMED = "renamed"
    WBS_MOVED = "wbs_moved"
    TYPE_CHANGED = "type_changed"
    STATUS_CHANGED = "status_changed"
    DURATION_CHANGED = "duration_changed"
    DATES_CHANGED = "dates_changed"
    FLOAT_CHANGED = "float_changed"
    CONSTRAINT_CHANGED = "constraint_changed"
    CALENDAR_CHANGED = "calendar_changed"
    PROGRESS_CHANGED = "progress_changed"
    FIELD_CHANGED = "field_changed"
    RELATIONSHIP_ADDED = "relationship_added"
    RELATIONSHIP_REMOVED = "relationship_removed"
    RELATIONSHIP_CHANGED = "relationship_changed"


_KIND_RANK: Final[Mapping[P6ChangeKind, int]] = MappingProxyType(
    {kind: rank for rank, kind in enumerate(P6ChangeKind, start=1)}
)
_SCOPE_RANK: Final[Mapping[P6ChangeScope, int]] = MappingProxyType(
    {scope: rank for rank, scope in enumerate(P6ChangeScope, start=1)}
)

#: The project settings compared by `settings_changed`, in report order (the
#: `p6` block's settings of `schedule_publications.read`, then the ERMHDR header
#: a re-export changes, section 11.2).
P6_DELTA_PROJECT_FIELDS: Final = (
    "planned_start",
    "must_finish_by",
    "scheduled_finish",
    "critical_float_hours",
    "critical_path_type",
    "next_data_date",
    "lag_calendar",
    "retained_logic",
    "progress_override",
    "float_type",
    "open_ends_critical",
    "external_dependencies",
    "use_expected_finish",
    "ss_lag_from_early_start",
    "float_from_project_finish",
    "default_p6_calendar_id",
    "export_version",
    "export_date",
)
_DURATIONS: Final = ("original_hours", "remaining_hours")
_DATES: Final = (
    "start",
    "finish",
    "early_start",
    "early_finish",
    "late_start",
    "late_finish",
    "planned_start",
    "planned_finish",
    "actual_start",
    "actual_finish",
)
_FLOATS: Final = ("total_float_hours", "free_float_hours")
#: Fixed field order inside one subject; a captured field key ranks after them.
_FIELD_RANK: Final[Mapping[str, int]] = MappingProxyType(
    {
        name: rank
        for rank, name in enumerate(
            (
                "data_date",
                *P6_DELTA_PROJECT_FIELDS,
                "week",
                "exceptions",
                "name",
                "wbs_path",
                "task_type",
                "status",
                *_DURATIONS,
                *_DATES,
                *_FLOATS,
                "constraint",
                "constraint2",
                "calendar",
                "physical_pct",
                "type",
                "lag_hours",
            ),
            start=1,
        )
    }
)
_MINUTE: Final = timedelta(minutes=1)

#: A value a change's `before`/`after` may hold (already rendered for the wire).
type P6Rendered = str | int | bool | list[object] | dict[str, object] | None


# ---- inputs ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class P6DeltaCalendar:
    """One stored calendar: P6 id, name, week (7 x `(start, end)` minutes) and exceptions."""

    p6_calendar_id: int
    name: str | None
    week: tuple[tuple[tuple[int, int], ...], ...]
    exceptions: Mapping[str, tuple[tuple[int, int], ...]]
    data_sha256: str | None


@dataclass(frozen=True, slots=True)
class P6DeltaActivity:
    """One stored activity of an accepted run, with its comparable captured values."""

    schedule_activity_id: str
    activity_id: str
    name: str
    wbs_path: tuple[str, ...]
    task_type: str
    status: str
    p6_calendar_id: int | None
    numbers: Mapping[str, Decimal | None]
    dates: Mapping[str, datetime | None]
    constraint: tuple[str | None, datetime | None]
    constraint2: tuple[str | None, datetime | None]
    guid: str | None
    fields: Mapping[str, tuple[P6Rendered, ...]]


@dataclass(frozen=True, slots=True)
class P6DeltaRelationship:
    """One stored relationship: its ends' Activity IDs (null across projects), type and lag."""

    pred_activity_id: str | None
    succ_activity_id: str | None
    relationship_type: str
    lag_hours: Decimal | None
    is_external: bool


@dataclass(frozen=True, slots=True)
class P6DeltaSide:
    """One publication as the delta reads it."""

    data_date: datetime | None
    project: Mapping[str, object]
    calendars: Sequence[P6DeltaCalendar]
    activities: Sequence[P6DeltaActivity]
    relationships: Sequence[P6DeltaRelationship]
    capture_keys: frozenset[str]


# ---- outputs ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class P6Change:
    """One change from A to B; `subject` names what changed inside its scope."""

    scope: P6ChangeScope
    kind: P6ChangeKind
    subject: tuple[str, ...]
    field: str | None
    before: P6Rendered
    after: P6Rendered
    schedule_activity_id: str | None = None
    delta_minutes: int | None = None
    delta: Decimal | None = None
    counts: Mapping[str, int] | None = None

    def __post_init__(self) -> None:
        if self.delta_minutes is not None and self.delta is not None:
            raise ValueError("a change carries at most one delta")


@dataclass(frozen=True, slots=True)
class P6ChangeSet:
    """The full, sorted change list, the per-kind counts (every kind) and what was not compared."""

    changes: tuple[P6Change, ...]
    counts_by_kind: Mapping[P6ChangeKind, int]
    fields_not_comparable: int
    fields_withheld: int
    external_relationships: int
    calendars_unmatched: int

    def __post_init__(self) -> None:
        if tuple(self.counts_by_kind) != tuple(P6ChangeKind):
            raise ValueError("counts name every change kind in rank order")
        if sum(self.counts_by_kind.values()) != len(self.changes):
            raise ValueError("counts sum to the change list")


# ---- rendering -------------------------------------------------------------------------


def _number(value: Decimal | None) -> str | None:
    if value is None:
        return None
    rendered = format(value.normalize(), "f")
    return "0" if rendered in ("-0", "") else rendered


def _instant(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="minutes" if value.second == 0 else "seconds")


def _setting(value: object) -> P6Rendered:
    if isinstance(value, Decimal):
        return _number(value)
    if isinstance(value, datetime):
        return _instant(value)
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, str | int | bool):
        return value
    return str(value)


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _week(week: tuple[tuple[tuple[int, int], ...], ...]) -> list[object]:
    return [[[_hhmm(start), _hhmm(end)] for start, end in day] for day in week]


def _calendar_ref(calendar: P6DeltaCalendar | None, p6_id: int | None) -> dict[str, object]:
    return {"calendar_id": p6_id, "name": None if calendar is None else calendar.name}


def _minutes(before: datetime, after: datetime) -> int:
    """Signed calendar minutes `after - before` (whole minutes, floored)."""
    return (after - before) // _MINUTE


# ---- the comparison --------------------------------------------------------------------


def p6_unmatched_target_activity_ids(
    from_activities: Iterable[P6DeltaActivity], to_activities: Iterable[P6DeltaActivity]
) -> frozenset[str]:
    """The Stable Activities of B that A does not carry (the prior-observation question)."""
    seen = {activity.schedule_activity_id for activity in from_activities}
    return frozenset(
        activity.schedule_activity_id
        for activity in to_activities
        if activity.schedule_activity_id not in seen
    )


def _project_changes(a: P6DeltaSide, b: P6DeltaSide) -> list[P6Change]:
    found: list[P6Change] = []
    if a.data_date != b.data_date:
        found.append(
            P6Change(
                P6ChangeScope.PROJECT,
                P6ChangeKind.DATA_DATE_CHANGED,
                (),
                "data_date",
                _instant(a.data_date),
                _instant(b.data_date),
                delta_minutes=(
                    None
                    if a.data_date is None or b.data_date is None
                    else _minutes(a.data_date, b.data_date)
                ),
            )
        )
    for name in P6_DELTA_PROJECT_FIELDS:
        before, after = _setting(a.project.get(name)), _setting(b.project.get(name))
        if before != after:
            found.append(
                P6Change(
                    P6ChangeScope.PROJECT, P6ChangeKind.SETTINGS_CHANGED, (), name, before, after
                )
            )
    return found


def _match_calendars(
    left: Sequence[P6DeltaCalendar], right: Sequence[P6DeltaCalendar]
) -> tuple[list[tuple[P6DeltaCalendar, P6DeltaCalendar]], int]:
    """Pairs by P6 id, then by a name unique among both sides' unmatched; and how many are not."""
    by_id = {calendar.p6_calendar_id: calendar for calendar in right}
    pairs: list[tuple[P6DeltaCalendar, P6DeltaCalendar]] = []
    rest_left: list[P6DeltaCalendar] = []
    used: set[int] = set()
    for calendar in left:
        other = by_id.get(calendar.p6_calendar_id)
        if other is None:
            rest_left.append(calendar)
        else:
            pairs.append((calendar, other))
            used.add(other.p6_calendar_id)
    rest_right = [calendar for calendar in right if calendar.p6_calendar_id not in used]

    def unique(items: Sequence[P6DeltaCalendar]) -> dict[str, P6DeltaCalendar]:
        names: dict[str, list[P6DeltaCalendar]] = {}
        for item in items:
            if item.name is not None:
                names.setdefault(item.name, []).append(item)
        return {name: found[0] for name, found in names.items() if len(found) == 1}

    left_names, right_names = unique(rest_left), unique(rest_right)
    named = sorted(set(left_names) & set(right_names))
    pairs.extend((left_names[name], right_names[name]) for name in named)
    unmatched = len(rest_left) + len(rest_right) - 2 * len(named)
    return pairs, unmatched


def _calendar_changes(
    pairs: Sequence[tuple[P6DeltaCalendar, P6DeltaCalendar]],
) -> list[P6Change]:
    found: list[P6Change] = []
    for before, after in pairs:
        subject = (str(after.p6_calendar_id),)
        ref = _calendar_ref(after, after.p6_calendar_id)
        if before.week != after.week:
            found.append(
                P6Change(
                    P6ChangeScope.CALENDAR,
                    P6ChangeKind.CALENDAR_WEEK_CHANGED,
                    subject,
                    "week",
                    {**_calendar_ref(before, before.p6_calendar_id), "week": _week(before.week)},
                    {**ref, "week": _week(after.week)},
                )
            )
        old, new = before.exceptions, after.exceptions
        added = sum(1 for day in new if day not in old)
        removed = sum(1 for day in old if day not in new)
        changed = sum(1 for day, pattern in new.items() if day in old and old[day] != pattern)
        if added or removed or changed:
            found.append(
                P6Change(
                    P6ChangeScope.CALENDAR,
                    P6ChangeKind.CALENDAR_EXCEPTIONS_CHANGED,
                    subject,
                    "exceptions",
                    {**_calendar_ref(before, before.p6_calendar_id), "exception_count": len(old)},
                    {**ref, "exception_count": len(new)},
                    counts=MappingProxyType(
                        {"dates_added": added, "dates_removed": removed, "dates_changed": changed}
                    ),
                )
            )
    return found


def _activity_identity(activity: P6DeltaActivity) -> dict[str, object]:
    return {"name": activity.name, "task_type": activity.task_type}


def _calendar_identity(
    calendars: Mapping[int, P6DeltaCalendar], p6_id: int | None
) -> tuple[object, ...]:
    """By content (section 11.2): the data digest, else the id of an unparseable or missing one."""
    if p6_id is None:
        return ("none",)
    calendar = calendars.get(p6_id)
    if calendar is None:
        return ("missing", p6_id)
    if calendar.data_sha256 is None:
        return ("unparseable", p6_id)
    return ("data", calendar.data_sha256)


@dataclass(frozen=True, slots=True)
class _Context:
    calendars_a: Mapping[int, P6DeltaCalendar]
    calendars_b: Mapping[int, P6DeltaCalendar]
    field_keys: tuple[str, ...]


def _number_change(
    a: P6DeltaActivity, b: P6DeltaActivity, kind: P6ChangeKind, name: str
) -> P6Change | None:
    before, after = a.numbers.get(name), b.numbers.get(name)
    if before == after:
        return None
    return P6Change(
        P6ChangeScope.ACTIVITY,
        kind,
        (b.activity_id,),
        name,
        _number(before),
        _number(after),
        schedule_activity_id=b.schedule_activity_id,
        delta=None if before is None or after is None else after - before,
    )


def _date_change(a: P6DeltaActivity, b: P6DeltaActivity, name: str) -> P6Change | None:
    before, after = a.dates.get(name), b.dates.get(name)
    if before == after:
        return None
    return P6Change(
        P6ChangeScope.ACTIVITY,
        P6ChangeKind.DATES_CHANGED,
        (b.activity_id,),
        name,
        _instant(before),
        _instant(after),
        schedule_activity_id=b.schedule_activity_id,
        delta_minutes=None if before is None or after is None else _minutes(before, after),
    )


def _constraint(value: tuple[str | None, datetime | None]) -> dict[str, object]:
    return {"type": value[0], "date": _instant(value[1])}


def _captured(values: tuple[P6Rendered, ...] | None) -> P6Rendered:
    if not values:
        return None
    return values[0] if len(values) == 1 else list(values)


def _matched(a: P6DeltaActivity, b: P6DeltaActivity, context: _Context) -> list[P6Change]:
    """Every rule over one matched pair, evaluated independently (section 11.4)."""
    subject = (b.activity_id,)
    sact = b.schedule_activity_id
    found: list[P6Change] = []

    def plain(kind: P6ChangeKind, name: str, before: P6Rendered, after: P6Rendered) -> None:
        if before != after:
            found.append(
                P6Change(
                    P6ChangeScope.ACTIVITY,
                    kind,
                    subject,
                    name,
                    before,
                    after,
                    schedule_activity_id=sact,
                )
            )

    plain(P6ChangeKind.RENAMED, "name", a.name, b.name)
    plain(P6ChangeKind.WBS_MOVED, "wbs_path", list(a.wbs_path), list(b.wbs_path))
    plain(P6ChangeKind.TYPE_CHANGED, "task_type", a.task_type, b.task_type)
    plain(P6ChangeKind.STATUS_CHANGED, "status", a.status, b.status)
    for name in _DURATIONS:
        change = _number_change(a, b, P6ChangeKind.DURATION_CHANGED, name)
        if change is not None:
            found.append(change)
    for name in _DATES:
        change = _date_change(a, b, name)
        if change is not None:
            found.append(change)
    for name in _FLOATS:
        change = _number_change(a, b, P6ChangeKind.FLOAT_CHANGED, name)
        if change is not None:
            found.append(change)
    plain(
        P6ChangeKind.CONSTRAINT_CHANGED,
        "constraint",
        _constraint(a.constraint),
        _constraint(b.constraint),
    )
    plain(
        P6ChangeKind.CONSTRAINT_CHANGED,
        "constraint2",
        _constraint(a.constraint2),
        _constraint(b.constraint2),
    )
    if _calendar_identity(context.calendars_a, a.p6_calendar_id) != _calendar_identity(
        context.calendars_b, b.p6_calendar_id
    ):
        found.append(
            P6Change(
                P6ChangeScope.ACTIVITY,
                P6ChangeKind.CALENDAR_CHANGED,
                subject,
                "calendar",
                _calendar_ref(context.calendars_a.get(a.p6_calendar_id or -1), a.p6_calendar_id),
                _calendar_ref(context.calendars_b.get(b.p6_calendar_id or -1), b.p6_calendar_id),
                schedule_activity_id=sact,
            )
        )
    change = _number_change(a, b, P6ChangeKind.PROGRESS_CHANGED, "physical_pct")
    if change is not None:
        found.append(change)
    for key in context.field_keys:
        before_values, after_values = a.fields.get(key, ()), b.fields.get(key, ())
        if before_values != after_values:
            found.append(
                P6Change(
                    P6ChangeScope.ACTIVITY,
                    P6ChangeKind.FIELD_CHANGED,
                    subject,
                    key,
                    _captured(before_values),
                    _captured(after_values),
                    schedule_activity_id=sact,
                )
            )
    return found


def _only(activity: P6DeltaActivity, kind: P6ChangeKind, *, before: bool) -> P6Change:
    side = _activity_identity(activity)
    return P6Change(
        P6ChangeScope.ACTIVITY,
        kind,
        (activity.activity_id,),
        None,
        side if before else None,
        None if before else side,
        schedule_activity_id=activity.schedule_activity_id,
    )


def _activity_changes(
    left: Sequence[P6DeltaActivity],
    right: Sequence[P6DeltaActivity],
    prior: frozenset[str],
    context: _Context,
) -> list[P6Change]:
    """One merge pass over both sides ordered by Activity ID (code point order, no repeat)."""
    changes: list[P6Change] = []
    removed: list[P6DeltaActivity] = []
    added: list[P6DeltaActivity] = []
    i = j = 0
    while i < len(left) or j < len(right):
        a = left[i] if i < len(left) else None
        b = right[j] if j < len(right) else None
        if b is None or (a is not None and a.activity_id < b.activity_id):
            if a is None:  # pragma: no cover - loop condition
                break
            changes.append(_only(a, P6ChangeKind.REMOVED, before=True))
            removed.append(a)
            i += 1
        elif a is None or a.activity_id != b.activity_id:
            kind = (
                P6ChangeKind.REINTRODUCED if b.schedule_activity_id in prior else P6ChangeKind.ADDED
            )
            changes.append(_only(b, kind, before=False))
            added.append(b)
            j += 1
        else:
            if a.schedule_activity_id != b.schedule_activity_id:
                raise ValueError("one Activity ID inside one series is one stable activity")
            changes.extend(_matched(a, b, context))
            i += 1
            j += 1
    changes.extend(_renumber_candidates(removed, added))
    return changes


def _renumber_candidates(
    removed: Sequence[P6DeltaActivity], added: Sequence[P6DeltaActivity]
) -> list[P6Change]:
    """Section 11.3: a removed and an added row sharing one P6 GUID (exactly one each)."""

    def by_guid(items: Sequence[P6DeltaActivity]) -> dict[str, list[P6DeltaActivity]]:
        found: dict[str, list[P6DeltaActivity]] = {}
        for item in items:
            if item.guid:
                found.setdefault(item.guid, []).append(item)
        return found

    olds, news = by_guid(removed), by_guid(added)
    hints: list[P6Change] = []
    for guid in sorted(set(olds) & set(news)):
        if len(olds[guid]) != 1 or len(news[guid]) != 1:
            continue
        old, new = olds[guid][0], news[guid][0]
        hints.append(
            P6Change(
                P6ChangeScope.ACTIVITY,
                P6ChangeKind.RENUMBER_CANDIDATE,
                (new.activity_id,),
                None,
                {"activity_id": old.activity_id, "schedule_activity_id": old.schedule_activity_id},
                {"activity_id": new.activity_id, "schedule_activity_id": new.schedule_activity_id},
                schedule_activity_id=new.schedule_activity_id,
            )
        )
    return hints


type _Pair = tuple[str, str]


def _relationship_key(item: P6DeltaRelationship) -> _Pair:
    if item.pred_activity_id is None or item.succ_activity_id is None:  # pragma: no cover
        raise ValueError("an internal relationship names both ends")
    return (item.pred_activity_id, item.succ_activity_id)


def _relationship_side(item: P6DeltaRelationship) -> dict[str, object]:
    return {"type": item.relationship_type, "lag_hours": _number(item.lag_hours)}


def _relationship_changes(
    left: Sequence[P6DeltaRelationship], right: Sequence[P6DeltaRelationship]
) -> tuple[list[P6Change], int]:
    external = sum(1 for item in (*left, *right) if item.is_external)

    def grouped(
        items: Sequence[P6DeltaRelationship],
    ) -> dict[tuple[str, str], list[P6DeltaRelationship]]:
        found: dict[tuple[str, str], list[P6DeltaRelationship]] = {}
        for item in items:
            if not item.is_external:
                found.setdefault(_relationship_key(item), []).append(item)
        for group in found.values():
            group.sort(key=lambda rel: (rel.relationship_type, rel.lag_hours or Decimal(0)))
        return found

    olds, news = grouped(left), grouped(right)
    changes: list[P6Change] = []
    for key in sorted(set(olds) | set(news)):
        before_group, after_group = olds.get(key, []), news.get(key, [])
        for index in range(max(len(before_group), len(after_group))):
            before = before_group[index] if index < len(before_group) else None
            after = after_group[index] if index < len(after_group) else None
            if before is None and after is not None:
                changes.append(
                    P6Change(
                        P6ChangeScope.RELATIONSHIP,
                        P6ChangeKind.RELATIONSHIP_ADDED,
                        key,
                        None,
                        None,
                        _relationship_side(after),
                    )
                )
            elif after is None and before is not None:
                changes.append(
                    P6Change(
                        P6ChangeScope.RELATIONSHIP,
                        P6ChangeKind.RELATIONSHIP_REMOVED,
                        key,
                        None,
                        _relationship_side(before),
                        None,
                    )
                )
            elif before is not None and after is not None:
                if before.relationship_type != after.relationship_type:
                    changes.append(
                        P6Change(
                            P6ChangeScope.RELATIONSHIP,
                            P6ChangeKind.RELATIONSHIP_CHANGED,
                            key,
                            "type",
                            before.relationship_type,
                            after.relationship_type,
                        )
                    )
                if before.lag_hours != after.lag_hours:
                    changes.append(
                        P6Change(
                            P6ChangeScope.RELATIONSHIP,
                            P6ChangeKind.RELATIONSHIP_CHANGED,
                            key,
                            "lag_hours",
                            _number(before.lag_hours),
                            _number(after.lag_hours),
                            delta=(
                                None
                                if before.lag_hours is None or after.lag_hours is None
                                else after.lag_hours - before.lag_hours
                            ),
                        )
                    )
    return changes, external


def change_sort_key(change: P6Change) -> tuple[int, tuple[str, ...], int, int, str]:
    """`(scope, subject, kind, field)`; a captured field key ranks after the fixed fields."""
    field = change.field or ""
    rank = 0 if change.field is None else _FIELD_RANK.get(field, len(_FIELD_RANK) + 1)
    return (_SCOPE_RANK[change.scope], change.subject, _KIND_RANK[change.kind], rank, field)


def compare_p6_publications(
    from_side: P6DeltaSide,
    to_side: P6DeltaSide,
    prior: frozenset[str],
    *,
    personal_keys: frozenset[str] = frozenset(),
) -> P6ChangeSet:
    """The full A-to-B change list, sorted, with counts over every kind (section 11.4).

    Both sides' activities are ordered by Activity ID in code point order with
    no repeat (the repository's `COLLATE "C"` order over one accepted run).
    `prior` names B's unmatched Stable Activities observed in an eligible
    publication of the Series before A: those are `reintroduced`.
    `personal_keys` are the personal captured keys, never compared.
    """
    both = from_side.capture_keys & to_side.capture_keys
    one = from_side.capture_keys ^ to_side.capture_keys
    comparable = tuple(sorted(key for key in both if key not in personal_keys))
    context = _Context(
        calendars_a={item.p6_calendar_id: item for item in from_side.calendars},
        calendars_b={item.p6_calendar_id: item for item in to_side.calendars},
        field_keys=comparable,
    )
    pairs, unmatched = _match_calendars(from_side.calendars, to_side.calendars)
    relationships, external = _relationship_changes(from_side.relationships, to_side.relationships)
    changes = [
        *_project_changes(from_side, to_side),
        *_calendar_changes(pairs),
        *_activity_changes(from_side.activities, to_side.activities, prior, context),
        *relationships,
    ]
    changes.sort(key=change_sort_key)
    counts = dict.fromkeys(P6ChangeKind, 0)
    for change in changes:
        counts[change.kind] += 1
    return P6ChangeSet(
        changes=tuple(changes),
        counts_by_kind=MappingProxyType(counts),
        fields_not_comparable=len(one),
        fields_withheld=len(both) - len(comparable),
        external_relationships=external,
        calendars_unmatched=unmatched,
    )
