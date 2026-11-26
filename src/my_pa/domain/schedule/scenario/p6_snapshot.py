"""P6 XER S7-4b: version 1 of a Scenario as a snapshot of one P6 publication.

Contract: `docs/architecture/schedule-xer-import-contract.md` section 11.5 (the
mapping table, row for row), 11.6 (the MY-PA standard calendar) and 11.7 (edged
milestones, the fixed lag calendar, content v1/v2). Pure and standard-library
only: the application reads the accepted run and hands this module plain
records; nothing here reads a database, a clock or the environment.

Unlike the PDF snapshot no client calendar or `minutes_per_source_unit` is
needed: a P6 export carries durations in hours, relationships with types and
lags, calendars, constraints and actual dates. The request may add or
substitute calendars (already resolved by the caller to `p6-<id>` keyed
records of the same Project), name the default calendar, remap activity
calendars, and choose up to 50 captured fields to travel inert.

Every decision a source does not make for itself is counted in
`P6SnapshotReport`; nothing is invented silently. The engine never reads a
captured field. A content using none of the S7-0 additions (no edged
milestone, no `calendar:` lag calendar, no captured fields) is a byte-identical
`schedule-scenario-content-v1` document; any one of them makes it `-v2`.

S7-7: every relationship between two included activities is kept, so a P6
ladder (an SS and an FF between the same 2 activities) is whole and the content
does not depend on the export's row order; a content holding such a pair is
`-v3`. Only a repeated `(pred, succ, type)` (which P6 does not write) is still
counted `relationships_parallel_dropped`: the one with the largest lag is kept,
which binds every date exactly as both would.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.schedule.model import (
    MAX_DURATION_EXCLUSIVE,
    ScheduleCellState,
    ScheduleDateCell,
    ScheduleDurationCell,
    normalize_display_text,
)
from my_pa.domain.schedule.scenario.model import (
    MAX_ACTIVITIES,
    MAX_CAPTURED_FIELDS,
    MAX_CRITICAL_FLOAT_THRESHOLD_MINUTES,
    MAX_DURATION_MINUTES,
    MAX_INTERVALS_PER_DAY,
    MAX_LAG_MINUTES,
    MAX_WBS_LABELS,
    ActivityConstraint,
    ActivityKind,
    ActivityProgress,
    CalendarException,
    CapturedValue,
    ConstraintType,
    FixedLagCalendar,
    LagCalendar,
    LagCalendarSetting,
    ProgressPolicy,
    PublishedReference,
    RelationshipType,
    ScenarioActivity,
    ScenarioCalendar,
    ScenarioContent,
    ScenarioRelationship,
    ScenarioSettings,
    content_problem,
    parse_instant,
)
from my_pa.domain.schedule.scenario.snapshot import SnapshotReport, snapshot_wbs_path
from my_pa.domain.schedule.scenario.standard_calendar import (
    standard_calendar,
    standard_calendar_horizon_exceeded,
)

__all__ = [
    "P6_CALENDAR_PREFIX",
    "REPORT_COUNTS",
    "P6Snapshot",
    "P6SnapshotActivity",
    "P6SnapshotCalendar",
    "P6SnapshotProject",
    "P6SnapshotRefusal",
    "P6SnapshotRefusalError",
    "P6SnapshotRelationship",
    "P6SnapshotReport",
    "P6SnapshotRequest",
    "p6_calendar_key",
    "snapshot_from_p6",
]

#: A P6 calendar's key in a scenario content: `p6-<clndr_id>` (section 11.5).
P6_CALENDAR_PREFIX: Final = "p6-"
_WHOLE: Final = Decimal(1)
_MINUTES_PER_HOUR: Final = 60
_DURATION_QUANTUM: Final = Decimal("0.001")
_FIRST_DAY: Final = date(2000, 1, 1)
_LAST_DAY: Final = date(2099, 12, 31)

#: Section 11.5 activity kinds; LOE and WBS summary are excluded (counted).
_KINDS: Final[Mapping[str, ActivityKind]] = MappingProxyType(
    {
        "TT_Task": ActivityKind.TASK,
        "TT_Rsrc": ActivityKind.TASK,
        "TT_Mile": ActivityKind.START_MILESTONE,
        "TT_FinMile": ActivityKind.FINISH_MILESTONE,
    }
)
_EXCLUDED: Final[Mapping[str, str]] = MappingProxyType(
    {"TT_LOE": "loe_excluded", "TT_WBS": "wbs_summary_excluded"}
)
#: Section 11.5 constraint mapping; the 3 unrepresentable ones are dropped (counted).
_CONSTRAINTS: Final[Mapping[str, ConstraintType]] = MappingProxyType(
    {
        "CS_MSOA": ConstraintType.SNET,
        "CS_MEOA": ConstraintType.FNET,
        "CS_MSOB": ConstraintType.SNLT,
        "CS_MEOB": ConstraintType.FNLT,
        "CS_MANDSTART": ConstraintType.MSO,
        "CS_MANDFIN": ConstraintType.MFO,
    }
)
#: Section 11.7: a constraint on the other side of an edged milestone becomes its twin.
_TO_START_SIDE: Final[Mapping[ConstraintType, ConstraintType]] = MappingProxyType(
    {
        ConstraintType.FNET: ConstraintType.SNET,
        ConstraintType.FNLT: ConstraintType.SNLT,
        ConstraintType.MFO: ConstraintType.MSO,
    }
)
_TO_FINISH_SIDE: Final[Mapping[ConstraintType, ConstraintType]] = MappingProxyType(
    {start: finish for finish, start in _TO_START_SIDE.items()}
)
_RELATIONSHIP_TYPES: Final[Mapping[str, RelationshipType]] = MappingProxyType(
    {
        "PR_FS": RelationshipType.FS,
        "PR_SS": RelationshipType.SS,
        "PR_FF": RelationshipType.FF,
        "PR_SF": RelationshipType.SF,
    }
)
_LAG_CALENDARS: Final[Mapping[str, LagCalendar]] = MappingProxyType(
    {
        "rcal_Predecessor": LagCalendar.PREDECESSOR,
        "rcal_Successor": LagCalendar.SUCCESSOR,
        "rcal_24Hour": LagCalendar.TWENTY_FOUR_HOUR,
    }
)
_RCAL_PROJECT: Final = "rcal_Project"
_COMPLETE: Final = "TK_Complete"
_ACTIVE: Final = "TK_Active"


def p6_calendar_key(p6_calendar_id: int) -> str:
    """`p6-<clndr_id>` (a key of at most 32 characters: an id has at most 29 digits)."""
    return f"{P6_CALENDAR_PREFIX}{p6_calendar_id}"


class P6SnapshotRefusal(StrEnum):
    """Closed refusal tokens; the application maps them to its public details."""

    CALENDAR = "calendar"
    DATA_DATE = "data_date"
    ROWS = "rows"


class P6SnapshotRefusalError(ValueError):
    def __init__(self, reason: P6SnapshotRefusal) -> None:
        super().__init__(reason)
        self.reason = reason


# ---- inputs (plain records the application builds from the stored run) ------------------


@dataclass(frozen=True, slots=True)
class P6SnapshotCalendar:
    """One stored P6 calendar: week Monday first (empty = unparseable) and its exceptions."""

    p6_calendar_id: int
    week: tuple[tuple[tuple[int, int], ...], ...]
    exceptions: tuple[tuple[date, tuple[tuple[int, int], ...]], ...] = ()

    @property
    def parseable(self) -> bool:
        return len(self.week) == 7


@dataclass(frozen=True, slots=True)
class P6SnapshotProject:
    """The PROJECT and SCHEDOPTIONS values the mapping reads."""

    data_date: datetime
    default_p6_calendar_id: int | None = None
    lag_calendar: str | None = None
    retained_logic: bool | None = None
    progress_override: bool | None = None
    must_finish_by: datetime | None = None
    critical_float_hours: Decimal | None = None
    ss_lag_from_early_start: bool | None = None
    use_expected_finish: bool | None = None


@dataclass(frozen=True, slots=True)
class P6SnapshotActivity:
    """One stored activity: identity, kind, durations, calendar, constraints, actual dates."""

    schedule_activity_id: str | None
    activity_id: str
    name: str
    task_type: str
    status: str
    wbs_path: tuple[str, ...]
    p6_calendar_id: int | None
    original_hours: Decimal | None
    remaining_hours: Decimal | None
    start: datetime | None = None
    finish: datetime | None = None
    late_finish: datetime | None = None
    actual_start: datetime | None = None
    actual_finish: datetime | None = None
    constraint: tuple[str | None, datetime | None] = (None, None)
    constraint2: tuple[str | None, datetime | None] = (None, None)
    fields: Mapping[str, CapturedValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class P6SnapshotRelationship:
    pred_activity_id: str | None
    succ_activity_id: str | None
    relationship_type: str
    lag_hours: Decimal | None
    is_external: bool


@dataclass(frozen=True, slots=True)
class P6SnapshotRequest:
    """What the request may choose (section 11.5); everything else is mapped.

    `calendars` are the request's added or substituting calendars, resolved by
    the caller from any P6 publication of the same Project the caller owns,
    keyed `p6-<id>`; a key the origin also has is substituted. `calendar_map`
    remaps an activity calendar key to another available key. `include_fields`
    are captured keys (at most 50) to carry inert; none is a null `fields`.
    """

    calendars: tuple[P6SnapshotCalendar, ...] = ()
    default_calendar: str | None = None
    calendar_map: Mapping[str, str] = field(default_factory=dict)
    include_fields: tuple[str, ...] = ()


# ---- outputs -------------------------------------------------------------------------------

#: The report's counts, in report order (section 11.5: "the snapshot report lists every count").
REPORT_COUNTS: Final = (
    "activities",
    "tasks",
    "start_milestones",
    "finish_milestones",
    "loe_excluded",
    "wbs_summary_excluded",
    "resource_dependent_tasks",
    "durations_quantized",
    "durations_out_of_range",
    "original_missing",
    "remaining_missing",
    "complete_remaining_zeroed",
    "calendars",
    "calendars_defaulted",
    "default_calendar_standard",
    "lag_calendar_standard",
    "progress_policy_defaulted",
    "exceptions_out_of_range",
    "constraints_unsupported",
    "constraints_dropped",
    "milestone_constraints_converted",
    "relationships",
    "external_relationships_dropped",
    "relationships_excluded",
    "relationships_parallel_dropped",
    "lags_quantized",
    "wbs_paths_dropped",
    "instants_truncated",
)


@dataclass(frozen=True, slots=True)
class P6SnapshotReport:
    """Every count of section 11.5, the unmodelled settings and the outrun standard calendars."""

    counts: Mapping[str, int]
    unmodelled_settings: tuple[str, ...]
    standard_calendar_horizon_exceeded: tuple[str, ...]

    def __post_init__(self) -> None:
        if tuple(self.counts) != REPORT_COUNTS:
            raise ValueError("a P6 snapshot report names every count in report order")


@dataclass(frozen=True, slots=True)
class P6Snapshot:
    content: ScenarioContent
    #: The stored S6 report (its 6 columns), the P6 report beside it.
    report: SnapshotReport
    p6_report: P6SnapshotReport


# ---- the mapping ---------------------------------------------------------------------------


class _Counts:
    def __init__(self) -> None:
        self.values = dict.fromkeys(REPORT_COUNTS, 0)

    def add(self, name: str, amount: int = 1) -> None:
        self.values[name] += amount


def _instant(value: datetime, counts: _Counts) -> int:
    """A stored P6 timestamp on the axis (minute exact; seconds truncated, counted)."""
    if value.second or value.microsecond:
        counts.add("instants_truncated")
    try:
        return parse_instant(value.strftime("%Y-%m-%dT%H:%M"))
    except ValueError:
        raise P6SnapshotRefusalError(P6SnapshotRefusal.ROWS) from None


def _reached(value: datetime) -> int | None:
    """A stored timestamp on the axis, or `None` when it lies off it (never a refusal)."""
    try:
        return parse_instant(value.strftime("%Y-%m-%dT%H:%M"))
    except ValueError:
        return None


def _optional_instant(value: datetime | None, counts: _Counts) -> int | None:
    return None if value is None else _instant(value, counts)


def _minutes(hours: Decimal) -> tuple[int, bool]:
    """`hours x 60` rounded half-even, and whether the product was non-integral."""
    product = hours * _MINUTES_PER_HOUR
    minutes = int(product.quantize(_WHOLE, rounding=ROUND_HALF_EVEN))
    return minutes, product != minutes


def _duration(hours: Decimal | None, counts: _Counts, *, original: bool) -> int | None:
    if hours is None:
        counts.add("original_missing" if original else "remaining_missing")
        return None
    minutes, quantized = _minutes(hours)
    if not 0 <= minutes <= MAX_DURATION_MINUTES:
        counts.add("durations_out_of_range")
        return None
    if quantized:
        counts.add("durations_quantized")
    return minutes


def _calendar(source: P6SnapshotCalendar, key: str, counts: _Counts) -> ScenarioCalendar:
    """A parseable P6 calendar as a scenario calendar; more than 4 intervals a day is refused."""
    if any(len(day) > MAX_INTERVALS_PER_DAY for day in source.week):
        raise P6SnapshotRefusalError(P6SnapshotRefusal.CALENDAR)
    exceptions: list[CalendarException] = []
    for day, intervals in source.exceptions:
        if not _FIRST_DAY <= day <= _LAST_DAY:
            counts.add("exceptions_out_of_range")
            continue
        if len(intervals) > MAX_INTERVALS_PER_DAY:
            raise P6SnapshotRefusalError(P6SnapshotRefusal.CALENDAR)
        try:
            exceptions.append(CalendarException(day=day, intervals=intervals))
        except ValueError:
            raise P6SnapshotRefusalError(P6SnapshotRefusal.CALENDAR) from None
    try:
        return ScenarioCalendar(key=key, week=source.week, exceptions=tuple(exceptions))
    except ValueError:
        raise P6SnapshotRefusalError(P6SnapshotRefusal.CALENDAR) from None


def _constraint_type(token: str | None, counts: _Counts) -> ConstraintType | None:
    if token is None:
        return None
    mapped = _CONSTRAINTS.get(token)
    if mapped is None:
        counts.add("constraints_unsupported")
    return mapped


def _on_its_side(kind: ActivityKind, constraint: ConstraintType, counts: _Counts) -> ConstraintType:
    """Section 11.7: a finish-side constraint on a start milestone becomes its start twin."""
    table = (
        _TO_START_SIDE
        if kind is ActivityKind.START_MILESTONE
        else _TO_FINISH_SIDE
        if kind is ActivityKind.FINISH_MILESTONE
        else None
    )
    if table is not None and constraint in table:
        counts.add("milestone_constraints_converted")
        return table[constraint]
    return constraint


def _fits(constraints: Sequence[ActivityConstraint]) -> bool:
    """The engine's slot rule (1 early + 1 late, or 1 mandatory alone, no repeat)."""
    types = [item.type for item in constraints]
    if len(set(types)) != len(types):
        return False
    mandatory = {ConstraintType.MSO, ConstraintType.MFO}
    if any(kind in mandatory for kind in types):
        return len(types) == 1
    early = sum(kind in {ConstraintType.SNET, ConstraintType.FNET} for kind in types)
    late = sum(kind in {ConstraintType.SNLT, ConstraintType.FNLT} for kind in types)
    return early <= 1 and late <= 1


def _constraints(
    activity: P6SnapshotActivity, kind: ActivityKind, counts: _Counts
) -> tuple[ActivityConstraint, ...]:
    kept: list[ActivityConstraint] = []
    for token, at in (activity.constraint, activity.constraint2):
        mapped = _constraint_type(token, counts)
        if mapped is None:
            continue
        moment = None if at is None else _reached(at)
        if moment is None:
            # No date, or one off the engine's axis: not representable.
            counts.add("constraints_unsupported")
            continue
        if at is not None and (at.second or at.microsecond):
            counts.add("instants_truncated")
        candidate = ActivityConstraint(_on_its_side(kind, mapped, counts), moment)
        if kept and not _fits((*kept, candidate)):
            # The primary is kept; the secondary the slot rule refuses is dropped.
            counts.add("constraints_dropped")
            continue
        kept.append(candidate)
    return tuple(kept)


def _progress(
    activity: P6SnapshotActivity, kind: ActivityKind, counts: _Counts
) -> ActivityProgress | None:
    """Section 11.5 progress; a complete activity without its needed actual date is refused."""
    start = _optional_instant(activity.actual_start, counts)
    finish = _optional_instant(activity.actual_finish, counts)
    complete = activity.status == _COMPLETE
    if kind is ActivityKind.START_MILESTONE:
        if start is None:
            if complete:
                raise P6SnapshotRefusalError(P6SnapshotRefusal.ROWS)
            return None
        return ActivityProgress(start, start)
    if kind is ActivityKind.FINISH_MILESTONE:
        if finish is None:
            if complete:
                raise P6SnapshotRefusalError(P6SnapshotRefusal.ROWS)
            return None
        return ActivityProgress(finish, finish)
    if complete:
        if start is None or finish is None:
            raise P6SnapshotRefusalError(P6SnapshotRefusal.ROWS)
        return ActivityProgress(start, finish)
    if activity.status == _ACTIVE and start is not None:
        return ActivityProgress(start)
    return None


def _hours_cell(hours: Decimal | None) -> ScheduleDurationCell:
    """The published hours, inert; one not exact at 3 decimals is `ambiguous`."""
    if hours is None:
        return ScheduleDurationCell(ScheduleCellState.PUBLISHED_BLANK, None)
    quantized = hours.quantize(_DURATION_QUANTUM)
    if quantized != hours or not 0 <= quantized < MAX_DURATION_EXCLUSIVE:
        return ScheduleDurationCell(ScheduleCellState.AMBIGUOUS, None)
    return ScheduleDurationCell(ScheduleCellState.PUBLISHED_VALUE, quantized)


def _day_cell(value: datetime | None) -> ScheduleDateCell:
    if value is None:
        return ScheduleDateCell(ScheduleCellState.PUBLISHED_BLANK, None, None)
    return ScheduleDateCell(ScheduleCellState.PUBLISHED_VALUE, value.date(), None)


def _fields(
    activity: P6SnapshotActivity, include: tuple[str, ...]
) -> tuple[tuple[str, CapturedValue], ...] | None:
    """`null` (never `{}`) when the request carries no captured field (section 11.5)."""
    if not include:
        return None
    return tuple((key, activity.fields.get(key)) for key in include)


def _wbs(path: tuple[str, ...], counts: _Counts) -> tuple[str, ...] | None:
    if len(path) > MAX_WBS_LABELS:
        counts.add("wbs_paths_dropped")
        return None
    labels = snapshot_wbs_path(path)
    if path and labels is None:
        counts.add("wbs_paths_dropped")
    return labels


@dataclass(slots=True)
class _Calendars:
    """The calendars a snapshot may use, by key; `used` are those the content holds."""

    available: dict[str, P6SnapshotCalendar | None]
    standard: ScenarioCalendar
    used: dict[str, ScenarioCalendar] = field(default_factory=dict)

    def usable(self, key: str | None) -> bool:
        if key is None:
            return False
        if key == self.standard.key:
            return True
        source = self.available.get(key)
        return source is not None and source.parseable

    def use(self, key: str, counts: _Counts) -> str:
        if key not in self.used:
            if key == self.standard.key:
                self.used[key] = self.standard
            else:
                source = self.available.get(key)
                if source is None or not source.parseable:
                    raise P6SnapshotRefusalError(P6SnapshotRefusal.CALENDAR)
                self.used[key] = _calendar(source, key, counts)
        return key


def _available(
    calendars: Sequence[P6SnapshotCalendar], request: P6SnapshotRequest, data_date: datetime
) -> _Calendars:
    available: dict[str, P6SnapshotCalendar | None] = {
        p6_calendar_key(item.p6_calendar_id): item for item in calendars
    }
    requested = [p6_calendar_key(item.p6_calendar_id) for item in request.calendars]
    if len(set(requested)) != len(requested):
        raise P6SnapshotRefusalError(P6SnapshotRefusal.CALENDAR)
    for item in request.calendars:
        if not item.parseable:
            raise P6SnapshotRefusalError(P6SnapshotRefusal.CALENDAR)
        available[p6_calendar_key(item.p6_calendar_id)] = item
    return _Calendars(available=available, standard=standard_calendar(data_date.year))


def _lag_calendar(
    project: P6SnapshotProject, calendars: _Calendars, counts: _Counts
) -> LagCalendarSetting:
    token = project.lag_calendar
    if token == _RCAL_PROJECT:
        default = (
            None
            if project.default_p6_calendar_id is None
            else p6_calendar_key(project.default_p6_calendar_id)
        )
        if default is not None and calendars.usable(default):
            return FixedLagCalendar(calendars.use(default, counts))
        counts.add("lag_calendar_standard")
        return FixedLagCalendar(calendars.use(calendars.standard.key, counts))
    # P6's own default (rcal_Predecessor) for an absent or unknown token.
    return _LAG_CALENDARS.get(token or "", LagCalendar.PREDECESSOR)


def _progress_policy(project: P6SnapshotProject, counts: _Counts) -> ProgressPolicy:
    if project.progress_override:
        return ProgressPolicy.PROGRESS_OVERRIDE
    if project.retained_logic:
        return ProgressPolicy.RETAINED_LOGIC
    # P6 "actual dates": retained logic by default (section 11.5, why in the contract).
    counts.add("progress_policy_defaulted")
    return ProgressPolicy.RETAINED_LOGIC


def _threshold(hours: Decimal | None) -> int:
    if hours is None:
        return 0
    minutes, _ = _minutes(hours)
    return min(max(minutes, 0), MAX_CRITICAL_FLOAT_THRESHOLD_MINUTES)


def _unmodelled(project: P6SnapshotProject) -> tuple[str, ...]:
    """Section 11.5: the P6 options the engine lacks that this export sets."""
    found: list[str] = []
    if project.ss_lag_from_early_start:
        found.append("ss_lag_from_early_start")
    if project.use_expected_finish:
        found.append("use_expected_finish")
    return tuple(found)


def snapshot_from_p6(
    *,
    publication_id: str,
    project: P6SnapshotProject,
    calendars: Sequence[P6SnapshotCalendar],
    activities: Sequence[P6SnapshotActivity],
    relationships: Sequence[P6SnapshotRelationship],
    request: P6SnapshotRequest | None = None,
    legacy_relationships: bool = False,
) -> P6Snapshot:
    """Build version 1 from one P6 publication's accepted run (section 11.5).

    `legacy_relationships` reconstructs a pre-S7-7 snapshot for idempotent replay.
    """
    request = request or P6SnapshotRequest()
    if len(request.include_fields) > MAX_CAPTURED_FIELDS or len(set(request.include_fields)) != len(
        request.include_fields
    ):
        raise P6SnapshotRefusalError(P6SnapshotRefusal.ROWS)
    if len(activities) > MAX_ACTIVITIES:
        raise P6SnapshotRefusalError(P6SnapshotRefusal.ROWS)
    counts = _Counts()
    try:
        data_date = _instant(project.data_date, counts)
    except P6SnapshotRefusalError:
        raise P6SnapshotRefusalError(P6SnapshotRefusal.DATA_DATE) from None
    pool = _available(calendars, request, project.data_date)
    for extra in request.calendars:
        pool.use(p6_calendar_key(extra.p6_calendar_id), counts)
    for source, target in request.calendar_map.items():
        if (source not in pool.available and source != pool.standard.key) or not pool.usable(
            target
        ):
            raise P6SnapshotRefusalError(P6SnapshotRefusal.CALENDAR)
    if request.default_calendar is not None:
        if not pool.usable(request.default_calendar):
            raise P6SnapshotRefusalError(P6SnapshotRefusal.CALENDAR)
        default_calendar = pool.use(request.default_calendar, counts)
    else:
        default_key = (
            None
            if project.default_p6_calendar_id is None
            else p6_calendar_key(project.default_p6_calendar_id)
        )
        if default_key is not None and pool.usable(default_key):
            default_calendar = pool.use(default_key, counts)
        else:
            counts.add("default_calendar_standard")
            default_calendar = pool.use(pool.standard.key, counts)
    lag_calendar = _lag_calendar(project, pool, counts)
    settings_policy = _progress_policy(project, counts)
    must_finish_by = None if project.must_finish_by is None else _reached(project.must_finish_by)

    included: dict[str, str] = {}
    built: list[ScenarioActivity] = []
    latest = data_date
    for activity in activities:
        excluded = _EXCLUDED.get(activity.task_type)
        if excluded is not None:
            counts.add(excluded)
            continue
        kind = _KINDS.get(activity.task_type)
        if kind is None or activity.schedule_activity_id is None:
            raise P6SnapshotRefusalError(P6SnapshotRefusal.ROWS)
        if activity.task_type == "TT_Rsrc":
            counts.add("resource_dependent_tasks")
        key = None if activity.p6_calendar_id is None else p6_calendar_key(activity.p6_calendar_id)
        if not pool.usable(key):
            counts.add("calendars_defaulted")
            key = pool.standard.key
        assert key is not None  # noqa: S101 - usable() refused None
        key = pool.use(request.calendar_map.get(key, key), counts)
        if kind is ActivityKind.TASK:
            counts.add("tasks")
            original = _duration(activity.original_hours, counts, original=True)
            remaining = _duration(activity.remaining_hours, counts, original=False)
        else:
            counts.add(
                "start_milestones" if kind is ActivityKind.START_MILESTONE else "finish_milestones"
            )
            original, remaining = 0, 0
        progress = _progress(activity, kind, counts)
        if progress is not None and progress.actual_finish is not None and remaining != 0:
            counts.add("complete_remaining_zeroed")
            remaining = 0
        for reached in (activity.finish, activity.late_finish):
            instant = None if reached is None else _reached(reached)
            if instant is not None:
                latest = max(latest, instant)
        try:
            built.append(
                ScenarioActivity(
                    key=activity.schedule_activity_id,
                    name=normalize_display_text(activity.name),
                    kind=kind,
                    remaining_minutes=remaining,
                    original_minutes=original,
                    calendar=key,
                    wbs_path=_wbs(activity.wbs_path, counts),
                    constraints=_constraints(activity, kind, counts),
                    progress=progress,
                    published_reference=PublishedReference(
                        publication_id=publication_id,
                        published_activity_id=activity.activity_id,
                        original_duration=_hours_cell(activity.original_hours),
                        remaining_duration=_hours_cell(activity.remaining_hours),
                        start=_day_cell(activity.start),
                        finish=_day_cell(activity.finish),
                        fields=_fields(activity, request.include_fields),
                    ),
                )
            )
        except ValueError:
            raise P6SnapshotRefusalError(P6SnapshotRefusal.ROWS) from None
        included[activity.activity_id] = activity.schedule_activity_id

    links: dict[tuple[str, str, RelationshipType | None], tuple[ScenarioRelationship, bool]] = {}
    for relationship in relationships:
        if relationship.is_external:
            counts.add("external_relationships_dropped")
            continue
        pred = included.get(relationship.pred_activity_id or "")
        succ = included.get(relationship.succ_activity_id or "")
        rel_type = _RELATIONSHIP_TYPES.get(relationship.relationship_type)
        if pred is None or succ is None or rel_type is None:
            counts.add("relationships_excluded")
            continue
        link = (pred, succ, None if legacy_relationships else rel_type)
        kept = links.get(link)
        if kept is not None:
            counts.add("relationships_parallel_dropped")
            # The first-per-pair mapper did not validate or count lags of later rows.
            if legacy_relationships:
                continue
        lag, quantized = _minutes(relationship.lag_hours or Decimal(0))
        if not -MAX_LAG_MINUTES <= lag <= MAX_LAG_MINUTES:
            raise P6SnapshotRefusalError(P6SnapshotRefusal.ROWS)
        # A repeated type retains the largest lag, the binding one in both passes.
        # Keep the first on a tie so equal legacy and current content has the same report.
        if kept is not None and kept[0].lag_minutes >= lag:
            continue
        links[link] = (
            ScenarioRelationship(pred=pred, succ=succ, type=rel_type, lag_minutes=lag),
            quantized,
        )

    # At most 32 calendars (section 11.5): `content_problem` below is the one guard.
    counts.add("activities", len(built))
    counts.add("relationships", len(links))
    counts.add("lags_quantized", sum(quantized for _, quantized in links.values()))
    counts.add("calendars", len(pool.used))
    try:
        content = ScenarioContent(
            data_date=data_date,
            settings=ScenarioSettings(
                default_calendar=default_calendar,
                lag_calendar=lag_calendar,
                progress_policy=settings_policy,
                must_finish_by=must_finish_by,
                critical_float_threshold_minutes=_threshold(project.critical_float_hours),
            ),
            calendars=tuple(pool.used.values()),
            activities=tuple(built),
            relationships=tuple(relationship for relationship, _ in links.values()),
        )
    except ValueError:
        raise P6SnapshotRefusalError(P6SnapshotRefusal.CALENDAR) from None
    problem = content_problem(content)
    if problem is not None:
        reason = P6SnapshotRefusal.CALENDAR if "calendar" in problem else P6SnapshotRefusal.ROWS
        raise P6SnapshotRefusalError(reason)
    if must_finish_by is not None:
        latest = max(latest, must_finish_by)
    values = counts.values
    report = SnapshotReport(
        activities=values["activities"],
        milestones=values["start_milestones"] + values["finish_milestones"],
        durations_quantized=values["durations_quantized"],
        durations_out_of_range=values["durations_out_of_range"],
        original_missing=values["original_missing"],
        remaining_missing=values["remaining_missing"],
    )
    return P6Snapshot(
        content=content,
        report=report,
        p6_report=P6SnapshotReport(
            counts=MappingProxyType(dict(values)),
            unmodelled_settings=_unmodelled(project),
            standard_calendar_horizon_exceeded=standard_calendar_horizon_exceeded(content, latest),
        ),
    )
