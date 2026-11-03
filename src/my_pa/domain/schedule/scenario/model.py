"""Schedule Scenarios S6-1: the scenario content records (contract sections 2.3-2.10).

Contract: `docs/architecture/schedule-scenarios-contract.md`. Pure and
standard-library only (plus the schedule domain package and the opaque
identifier validator): no clock, randomness, environment or IO, and no
`float` anywhere. Time is integer minutes on one naive axis (section 3.1):
minute `0` is `2000-01-01T00:00` and `HORIZON_MINUTES` is `2100-01-01T00:00`.

The records validate their own fields and per-activity rules on
construction. Cross-references (calendar keys, relationship ends, progress
against the data date, bounds) are checked by `content_problem`, so the CPM
engine can still be handed, and must still reject, a network whose references
dangle (section 3.4). Every collection is stored in its canonical order, so
two contents built from permuted inputs are equal.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Final

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.schedule.model import (
    ScheduleDateCell,
    ScheduleDurationCell,
    normalize_display_text,
)

__all__ = [
    "HORIZON_MINUTES",
    "MAX_ACTIVITIES",
    "MAX_ACTIVITY_NAME_CHARACTERS",
    "MAX_CALENDARS",
    "MAX_CHANGE_SET_BYTES",
    "MAX_CHANGE_SET_OPS",
    "MAX_CONTENT_BYTES",
    "MAX_CRITICAL_FLOAT_THRESHOLD_MINUTES",
    "MAX_DURATION_MINUTES",
    "MAX_EXCEPTIONS_PER_CALENDAR",
    "MAX_EXCEPTIONS_PER_VERSION",
    "MAX_INTERVALS_PER_DAY",
    "MAX_LAG_MINUTES",
    "MAX_RELATIONSHIPS",
    "MAX_VERSIONS_PER_SCENARIO",
    "MAX_WBS_LABELS",
    "MINUTES_PER_DAY",
    "ActivityConstraint",
    "ActivityKind",
    "ActivityProgress",
    "ActivityState",
    "CalendarException",
    "ConstraintType",
    "DistributionKind",
    "DurationDistribution",
    "LagCalendar",
    "ProgressPolicy",
    "PublishedReference",
    "RelationshipType",
    "ScenarioActivity",
    "ScenarioCalendar",
    "ScenarioContent",
    "ScenarioRelationship",
    "ScenarioSettings",
    "VersionLabel",
    "activity_state",
    "content_problem",
    "format_instant",
    "is_added_activity_key",
    "is_calendar_key",
    "is_source_activity_key",
    "parse_instant",
]

# --- time axis (section 3.1) ----------------------------------------------------

MINUTES_PER_DAY: Final = 1440
#: `2100-01-01T00:00` on the axis whose minute 0 is `2000-01-01T00:00`.
HORIZON_MINUTES: Final = 52_596_000
_EPOCH_ORDINAL: Final = date(2000, 1, 1).toordinal()
_FIRST_DAY: Final = date(2000, 1, 1)
_LAST_DAY: Final = date(2099, 12, 31)
_INSTANT: Final = re.compile(r"\A([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2})\Z")


def parse_instant(text: object) -> int:
    """`"YYYY-MM-DDTHH:MM"` -> axis minutes in `[0, HORIZON_MINUTES]`, or `ValueError`."""
    if not isinstance(text, str):
        raise ValueError("an instant is a YYYY-MM-DDTHH:MM string")
    match = _INSTANT.fullmatch(text)
    if match is None:
        raise ValueError("an instant is a YYYY-MM-DDTHH:MM string")
    year, month, day, hour, minute = (int(group) for group in match.groups())
    if hour > 23 or minute > 59:
        raise ValueError("an instant has a valid time of day")
    days = date(year, month, day).toordinal() - _EPOCH_ORDINAL
    value = days * MINUTES_PER_DAY + hour * 60 + minute
    if not 0 <= value <= HORIZON_MINUTES:
        raise ValueError("an instant lies in 2000-01-01T00:00..2100-01-01T00:00")
    return value


def format_instant(minutes: int) -> str:
    """Axis minutes -> `"YYYY-MM-DDTHH:MM"`."""
    if not _is_int(minutes) or not 0 <= minutes <= HORIZON_MINUTES:
        raise ValueError("an instant lies on the axis")
    days, minute_of_day = divmod(minutes, MINUTES_PER_DAY)
    hour, minute = divmod(minute_of_day, 60)
    day = date.fromordinal(_EPOCH_ORDINAL + days)
    return f"{day.isoformat()}T{hour:02d}:{minute:02d}"


# --- bounds (sections 2.4-2.10) ---------------------------------------------------

MAX_ACTIVITIES: Final = 25_000
MAX_RELATIONSHIPS: Final = 100_000
MAX_CALENDARS: Final = 32
MAX_EXCEPTIONS_PER_CALENDAR: Final = 1_000
MAX_EXCEPTIONS_PER_VERSION: Final = 2_000
MAX_INTERVALS_PER_DAY: Final = 4
MAX_DURATION_MINUTES: Final = 5_256_000
MAX_LAG_MINUTES: Final = 1_051_200
MAX_CRITICAL_FLOAT_THRESHOLD_MINUTES: Final = 525_600
MAX_ACTIVITY_NAME_CHARACTERS: Final = 2_000
MAX_WBS_LABELS: Final = 32
MAX_VERSIONS_PER_SCENARIO: Final = 500
MAX_CONTENT_BYTES: Final = 33_554_432
MAX_CHANGE_SET_OPS: Final = 5_000
MAX_CHANGE_SET_BYTES: Final = 4_194_304

_ADDED_KEY: Final = re.compile(r"\Ax:[A-Za-z0-9_.-]{1,64}\Z")
_CALENDAR_KEY: Final = re.compile(r"\A[a-z0-9_-]{1,32}\Z")


def _is_int(value: object) -> bool:
    return type(value) is int


def _is_minutes(value: object, upper: int) -> bool:
    return _is_int(value) and 0 <= value <= upper  # type: ignore[operator]


def _is_instant(value: object) -> bool:
    return _is_minutes(value, HORIZON_MINUTES)


def is_added_activity_key(value: object) -> bool:
    """A client-added key: `x:` and 1..64 of `[A-Za-z0-9_.-]`."""
    return isinstance(value, str) and _ADDED_KEY.fullmatch(value) is not None


def is_source_activity_key(value: object) -> bool:
    """A baseline-derived key: a Stable Activity identifier (`sact_`)."""
    if not isinstance(value, str):
        return False
    try:
        validate_identifier(value, IdKind.SCHEDULE_ACTIVITY)
    except InvalidIdentifierError:
        return False
    return True


def is_calendar_key(value: object) -> bool:
    return isinstance(value, str) and _CALENDAR_KEY.fullmatch(value) is not None


def _is_display_text(value: object, limit: int) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= limit
        and normalize_display_text(value) == value
    )


# --- closed vocabularies -----------------------------------------------------------


class ActivityKind(StrEnum):
    TASK = "task"
    MILESTONE = "milestone"


class RelationshipType(StrEnum):
    FS = "FS"
    SS = "SS"
    FF = "FF"
    SF = "SF"


class ConstraintType(StrEnum):
    """Section 2.8, in the canonical order of section 2.3."""

    SNET = "SNET"
    FNET = "FNET"
    SNLT = "SNLT"
    FNLT = "FNLT"
    MSO = "MSO"
    MFO = "MFO"


_EARLY: Final = frozenset({ConstraintType.SNET, ConstraintType.FNET})
_LATE: Final = frozenset({ConstraintType.SNLT, ConstraintType.FNLT})
_MANDATORY: Final = frozenset({ConstraintType.MSO, ConstraintType.MFO})
_CONSTRAINT_ORDER: Final = {member: index for index, member in enumerate(ConstraintType)}


class LagCalendar(StrEnum):
    PREDECESSOR = "predecessor"
    SUCCESSOR = "successor"
    TWENTY_FOUR_HOUR = "twenty_four_hour"


class ProgressPolicy(StrEnum):
    RETAINED_LOGIC = "retained_logic"
    PROGRESS_OVERRIDE = "progress_override"


class VersionLabel(StrEnum):
    """Version metadata only; the engine never reads it (section 2.2)."""

    WHAT_IF = "what_if"
    UPDATE = "update"
    SIMULATION_INPUT = "simulation_input"


class DistributionKind(StrEnum):
    TRIANGULAR = "triangular"
    PERT = "pert"
    UNIFORM = "uniform"
    BOUNDED_NORMAL = "bounded_normal"


class ActivityState(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"


# --- calendars (section 2.7) ---------------------------------------------------------

Interval = tuple[int, int]
DayPattern = tuple[Interval, ...]


def _is_day_pattern(value: object) -> bool:
    if not isinstance(value, tuple) or len(value) > MAX_INTERVALS_PER_DAY:
        return False
    previous_end = -1
    for interval in value:
        if not isinstance(interval, tuple) or len(interval) != 2:
            return False
        start, end = interval
        if not (_is_int(start) and _is_int(end)):
            return False
        if not 0 <= start < end <= MINUTES_PER_DAY or start <= previous_end:
            return False
        previous_end = end
    return True


def _pattern(value: Iterable[Sequence[int]]) -> DayPattern:
    return tuple((interval[0], interval[1]) for interval in value)


@dataclass(frozen=True, slots=True)
class CalendarException:
    """One date whose pattern replaces the weekday's; no intervals = holiday."""

    day: date
    intervals: DayPattern

    def __post_init__(self) -> None:
        if type(self.day) is not date or not _FIRST_DAY <= self.day <= _LAST_DAY:
            raise ValueError("a calendar exception date lies in 2000-01-01..2099-12-31")
        object.__setattr__(self, "intervals", _pattern(self.intervals))
        if not _is_day_pattern(self.intervals):
            raise ValueError("a calendar day has 0..4 sorted, separated intervals")


@dataclass(frozen=True, slots=True)
class ScenarioCalendar:
    """A working-time calendar: 7 day patterns, Monday first, and dated exceptions."""

    key: str
    week: tuple[DayPattern, ...]
    exceptions: tuple[CalendarException, ...] = ()

    def __post_init__(self) -> None:
        if not is_calendar_key(self.key):
            raise ValueError("a calendar key is 1..32 of [a-z0-9_-]")
        object.__setattr__(self, "week", tuple(_pattern(day) for day in self.week))
        if len(self.week) != 7 or not all(_is_day_pattern(day) for day in self.week):
            raise ValueError("a calendar week is 7 day patterns of sorted, separated intervals")
        if not any(self.week):
            raise ValueError("a calendar week has at least one working minute")
        exceptions = tuple(sorted(self.exceptions, key=lambda item: item.day))
        object.__setattr__(self, "exceptions", exceptions)
        if not all(isinstance(item, CalendarException) for item in exceptions):
            raise ValueError("calendar exceptions are CalendarException records")
        if len(exceptions) > MAX_EXCEPTIONS_PER_CALENDAR:
            raise ValueError("a calendar has at most 1000 exceptions")
        if len({item.day for item in exceptions}) != len(exceptions):
            raise ValueError("a calendar exception date is unique")


# --- settings ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScenarioSettings:
    default_calendar: str
    lag_calendar: LagCalendar = LagCalendar.PREDECESSOR
    progress_policy: ProgressPolicy = ProgressPolicy.RETAINED_LOGIC
    must_finish_by: int | None = None
    critical_float_threshold_minutes: int = 0

    def __post_init__(self) -> None:
        if not is_calendar_key(self.default_calendar):
            raise ValueError("the default calendar is a calendar key")
        if not isinstance(self.lag_calendar, LagCalendar):
            raise ValueError("the lag calendar is a LagCalendar")
        if not isinstance(self.progress_policy, ProgressPolicy):
            raise ValueError("the progress policy is a ProgressPolicy")
        if self.must_finish_by is not None and not _is_instant(self.must_finish_by):
            raise ValueError("must_finish_by is an instant on the axis")
        if not _is_minutes(
            self.critical_float_threshold_minutes, MAX_CRITICAL_FLOAT_THRESHOLD_MINUTES
        ):
            raise ValueError("the critical float threshold is 0..525600 minutes")


# --- activity parts (section 2.8) -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActivityConstraint:
    type: ConstraintType
    at: int

    def __post_init__(self) -> None:
        if not isinstance(self.type, ConstraintType):
            raise ValueError("a constraint type is a ConstraintType")
        if not _is_instant(self.at):
            raise ValueError("a constraint instant lies within the horizon")


@dataclass(frozen=True, slots=True)
class ActivityProgress:
    """`actual_finish` null = in progress; both set = complete."""

    actual_start: int
    actual_finish: int | None = None

    def __post_init__(self) -> None:
        if not _is_instant(self.actual_start):
            raise ValueError("an actual start is an instant on the axis")
        if self.actual_finish is not None:
            if not _is_instant(self.actual_finish):
                raise ValueError("an actual finish is an instant on the axis")
            if self.actual_finish < self.actual_start:
                raise ValueError("an actual finish is not before the actual start")


_DISTRIBUTION_FIELDS: Final[dict[DistributionKind, frozenset[str]]] = {
    DistributionKind.TRIANGULAR: frozenset({"min", "mode", "max"}),
    DistributionKind.PERT: frozenset({"min", "mode", "max"}),
    DistributionKind.UNIFORM: frozenset({"min", "max"}),
    DistributionKind.BOUNDED_NORMAL: frozenset({"min", "mean", "sd", "max"}),
}


@dataclass(frozen=True, slots=True)
class DurationDistribution:
    """Distribution data for the remaining duration; the server never samples it."""

    kind: DistributionKind
    min: int
    max: int
    mode: int | None = None
    mean: int | None = None
    sd: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DistributionKind):
            raise ValueError("a distribution kind is a DistributionKind")
        present = {
            name for name in ("min", "mode", "max", "mean", "sd") if getattr(self, name) is not None
        }
        if present != _DISTRIBUTION_FIELDS[self.kind]:
            raise ValueError("a distribution carries exactly its kind's parameters")
        if not all(_is_minutes(getattr(self, name), MAX_DURATION_MINUTES) for name in present):
            raise ValueError("distribution parameters are integer minutes 0..5256000")
        if self.min >= self.max:
            raise ValueError("a distribution has min < max")
        if self.mode is not None and not self.min <= self.mode <= self.max:
            raise ValueError("a distribution has min <= mode <= max")
        if self.mean is not None and not self.min <= self.mean <= self.max:
            raise ValueError("a distribution has min <= mean <= max")
        if self.sd is not None and self.sd <= 0:
            raise ValueError("a bounded normal has sd > 0")

    def parameters(self) -> dict[str, int]:
        """The kind's parameters by name (the canonical object's numeric keys)."""
        values = {"min": self.min, "mode": self.mode, "max": self.max}
        values |= {"mean": self.mean, "sd": self.sd}
        return {
            name: value
            for name, value in values.items()
            if name in _DISTRIBUTION_FIELDS[self.kind] and value is not None
        }


@dataclass(frozen=True, slots=True)
class PublishedReference:
    """The inert published row a baseline activity came from (section 2.5)."""

    publication_id: str
    published_activity_id: str
    original_duration: ScheduleDurationCell
    remaining_duration: ScheduleDurationCell
    start: ScheduleDateCell
    finish: ScheduleDateCell

    def __post_init__(self) -> None:
        validate_identifier(self.publication_id, IdKind.SCHEDULE_PUBLICATION)
        if not self.published_activity_id:
            raise ValueError("a published activity id is a non-empty string")
        cells = (self.original_duration, self.remaining_duration)
        if not all(isinstance(cell, ScheduleDurationCell) for cell in cells):
            raise ValueError("published durations are ScheduleDurationCell records")
        if not all(isinstance(cell, ScheduleDateCell) for cell in (self.start, self.finish)):
            raise ValueError("published dates are ScheduleDateCell records")


# --- activities and relationships (sections 2.4, 2.6) --------------------------------------


def _constraints_fit_their_slots(constraints: Sequence[ActivityConstraint]) -> bool:
    types = [item.type for item in constraints]
    if len(set(types)) != len(types):
        return False
    mandatory = [kind for kind in types if kind in _MANDATORY]
    if mandatory:
        return len(types) == 1
    early = [kind for kind in types if kind in _EARLY]
    late = [kind for kind in types if kind in _LATE]
    return len(early) <= 1 and len(late) <= 1


@dataclass(frozen=True, slots=True)
class ScenarioActivity:
    key: str
    name: str
    kind: ActivityKind
    remaining_minutes: int | None
    original_minutes: int | None = None
    calendar: str | None = None
    wbs_path: tuple[str, ...] | None = None
    constraints: tuple[ActivityConstraint, ...] = ()
    progress: ActivityProgress | None = None
    distribution: DurationDistribution | None = None
    published_reference: PublishedReference | None = None

    def __post_init__(self) -> None:
        if not (is_added_activity_key(self.key) or is_source_activity_key(self.key)):
            raise ValueError("an activity key is a Stable Activity id or x:<token>")
        if not _is_display_text(self.name, MAX_ACTIVITY_NAME_CHARACTERS):
            raise ValueError("an activity name is 1..2000 normalized characters")
        if not isinstance(self.kind, ActivityKind):
            raise ValueError("an activity kind is an ActivityKind")
        for value in (self.original_minutes, self.remaining_minutes):
            if value is not None and not _is_minutes(value, MAX_DURATION_MINUTES):
                raise ValueError("a duration is null or 0..5256000 minutes")
        if self.calendar is not None and not is_calendar_key(self.calendar):
            raise ValueError("an activity calendar is null or a calendar key")
        if self.wbs_path is not None:
            object.__setattr__(self, "wbs_path", tuple(self.wbs_path))
            path = self.wbs_path
            if not 1 <= len(path) <= MAX_WBS_LABELS or not all(
                _is_display_text(label, MAX_ACTIVITY_NAME_CHARACTERS) for label in path
            ):
                raise ValueError("a WBS path is null or 1..32 normalized labels")
        constraints = tuple(sorted(self.constraints, key=lambda item: _CONSTRAINT_ORDER[item.type]))
        object.__setattr__(self, "constraints", constraints)
        if not all(isinstance(item, ActivityConstraint) for item in constraints):
            raise ValueError("constraints are ActivityConstraint records")
        if not _constraints_fit_their_slots(constraints):
            raise ValueError("at most 1 early and 1 late constraint, or 1 mandatory alone")
        if self.progress is not None and not isinstance(self.progress, ActivityProgress):
            raise ValueError("progress is an ActivityProgress record")
        if self.distribution is not None and not isinstance(
            self.distribution, DurationDistribution
        ):
            raise ValueError("a distribution is a DurationDistribution record")
        if self.published_reference is not None and not isinstance(
            self.published_reference, PublishedReference
        ):
            raise ValueError("a published reference is a PublishedReference record")
        if self.kind is ActivityKind.MILESTONE and (
            self.original_minutes != 0 or self.remaining_minutes != 0
        ):
            raise ValueError("a milestone has both durations 0")
        if (
            self.progress is not None
            and self.progress.actual_finish is not None
            and self.remaining_minutes != 0
        ):
            raise ValueError("a complete activity has remaining_minutes 0")


def activity_state(activity: ScenarioActivity) -> ActivityState:
    if activity.progress is None:
        return ActivityState.NOT_STARTED
    if activity.progress.actual_finish is None:
        return ActivityState.IN_PROGRESS
    return ActivityState.COMPLETE


@dataclass(frozen=True, slots=True)
class ScenarioRelationship:
    pred: str
    succ: str
    type: RelationshipType
    lag_minutes: int = 0

    def __post_init__(self) -> None:
        for key in (self.pred, self.succ):
            if not (is_added_activity_key(key) or is_source_activity_key(key)):
                raise ValueError("a relationship names two activity keys")
        if not isinstance(self.type, RelationshipType):
            raise ValueError("a relationship type is a RelationshipType")
        if not _is_int(self.lag_minutes) or not -MAX_LAG_MINUTES <= self.lag_minutes <= (
            MAX_LAG_MINUTES
        ):
            raise ValueError("a lag is -1051200..1051200 minutes")


# --- the content -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScenarioContent:
    """One version's `schedule-scenario-content-v1` document (section 2.3)."""

    data_date: int
    settings: ScenarioSettings
    calendars: tuple[ScenarioCalendar, ...]
    activities: tuple[ScenarioActivity, ...]
    relationships: tuple[ScenarioRelationship, ...] = ()

    def __post_init__(self) -> None:
        if not _is_instant(self.data_date):
            raise ValueError("the data date is an instant on the axis")
        if not isinstance(self.settings, ScenarioSettings):
            raise ValueError("settings is a ScenarioSettings record")
        calendars = tuple(sorted(self.calendars, key=lambda item: item.key))
        activities = tuple(sorted(self.activities, key=lambda item: item.key))
        relationships = tuple(sorted(self.relationships, key=lambda item: (item.pred, item.succ)))
        object.__setattr__(self, "calendars", calendars)
        object.__setattr__(self, "activities", activities)
        object.__setattr__(self, "relationships", relationships)
        if not all(isinstance(item, ScenarioCalendar) for item in calendars):
            raise ValueError("calendars are ScenarioCalendar records")
        if not all(isinstance(item, ScenarioActivity) for item in activities):
            raise ValueError("activities are ScenarioActivity records")
        if not all(isinstance(item, ScenarioRelationship) for item in relationships):
            raise ValueError("relationships are ScenarioRelationship records")


def _duplicated(values: Sequence[object]) -> bool:
    return len(set(values)) != len(values)


def content_problem(content: ScenarioContent) -> str | None:
    """The first cross-reference or bound a stored version must satisfy, else `None`.

    The message names the rule only (never content). Checked after every change
    set (section 2.9 final re-validation) and on every snapshot.
    """
    calendar_keys = [calendar.key for calendar in content.calendars]
    if not 1 <= len(calendar_keys) <= MAX_CALENDARS or _duplicated(calendar_keys):
        return "1..32 calendars with unique keys"
    if sum(len(calendar.exceptions) for calendar in content.calendars) > (
        MAX_EXCEPTIONS_PER_VERSION
    ):
        return "at most 2000 calendar exceptions per version"
    known = set(calendar_keys)
    if content.settings.default_calendar not in known:
        return "the default calendar exists"
    keys = [activity.key for activity in content.activities]
    if len(keys) > MAX_ACTIVITIES or _duplicated(keys):
        return "at most 25000 activities with unique keys"
    if any(a.calendar is not None and a.calendar not in known for a in content.activities):
        return "an activity calendar exists"
    present = set(keys)
    pairs = [(item.pred, item.succ) for item in content.relationships]
    if len(pairs) > MAX_RELATIONSHIPS or _duplicated(pairs):
        return "at most 100000 relationships, one per ordered pair"
    for pred, succ in pairs:
        if pred == succ:
            return "a relationship joins two different activities"
        if pred not in present or succ not in present:
            return "both relationship ends exist"
    for activity in content.activities:
        progress = activity.progress
        if progress is None:
            continue
        if progress.actual_start > content.data_date:
            return "an actual start is not after the data date"
        if progress.actual_finish is not None and progress.actual_finish > content.data_date:
            return "an actual finish is not after the data date"
    return None
