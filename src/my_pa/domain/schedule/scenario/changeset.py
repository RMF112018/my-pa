"""Schedule Scenarios S6-1: the change-set grammar and its application (contract section 2.9).

`apply_change_set(parent, ops)` applies 1..5,000 ops **in request order** to a
working copy of the parent content, validating each against the state the ops
before it left, then re-validates the whole result (`content_problem`). It
returns the new content and an `ApplicationReport`, or the first
`ChangeSetRefusal(op_index, op_error)`; a failed final re-validation is
`op_index = len(ops)`, `content_invalid`. Nothing is partially applied.

Each op is a JSON object `{"op": <name>, ...fields}`; an unknown name is
`unknown_op`, and a missing, unknown, ill-typed or out-of-domain field is
`invalid_field`. A clear/remove of something already absent where the grammar
has no `*_absent` token (`constraint.clear`, `distribution.clear`,
`progress.clear`, `calendar.exception.remove`) is an empty effective change,
which is allowed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from typing import Any, Final

from my_pa.domain.schedule.model import normalize_display_text
from my_pa.domain.schedule.scenario.canonical import (
    calendar_from_object,
    change_set_bytes,
    distribution_from_object,
)
from my_pa.domain.schedule.scenario.model import (
    MAX_ACTIVITIES,
    MAX_CALENDARS,
    MAX_CHANGE_SET_BYTES,
    MAX_CHANGE_SET_OPS,
    MAX_EXCEPTIONS_PER_CALENDAR,
    MAX_EXCEPTIONS_PER_VERSION,
    MAX_RELATIONSHIPS,
    ActivityConstraint,
    ActivityKind,
    ActivityProgress,
    CalendarException,
    ConstraintType,
    DurationDistribution,
    LagCalendar,
    ProgressPolicy,
    RelationshipType,
    ScenarioActivity,
    ScenarioCalendar,
    ScenarioContent,
    ScenarioRelationship,
    content_problem,
    is_added_activity_key,
    parse_instant,
)

__all__ = [
    "ApplicationReport",
    "ChangeOp",
    "ChangeOpError",
    "ChangeSetApplied",
    "ChangeSetRefusal",
    "apply_change_set",
]


class ChangeOp(StrEnum):
    """The 19 op names of section 2.9."""

    ACTIVITY_ADD = "activity.add"
    ACTIVITY_EDIT = "activity.edit"
    ACTIVITY_REMOVE = "activity.remove"
    DURATION_SET = "duration.set"
    DISTRIBUTION_SET = "distribution.set"
    DISTRIBUTION_CLEAR = "distribution.clear"
    RELATIONSHIP_ADD = "relationship.add"
    RELATIONSHIP_EDIT = "relationship.edit"
    RELATIONSHIP_REMOVE = "relationship.remove"
    CALENDAR_PUT = "calendar.put"
    CALENDAR_REMOVE = "calendar.remove"
    CALENDAR_EXCEPTION_PUT = "calendar.exception.put"
    CALENDAR_EXCEPTION_REMOVE = "calendar.exception.remove"
    CONSTRAINT_SET = "constraint.set"
    CONSTRAINT_CLEAR = "constraint.clear"
    PROGRESS_SET = "progress.set"
    PROGRESS_CLEAR = "progress.clear"
    DATA_DATE_SET = "data_date.set"
    SETTINGS_SET = "settings.set"


class ChangeOpError(StrEnum):
    """`op_error`, closed (14); the public `SafeDetail` is `change_set_<op_error>`."""

    UNKNOWN_OP = "unknown_op"
    INVALID_FIELD = "invalid_field"
    KEY_EXISTS = "key_exists"
    KEY_ABSENT = "key_absent"
    SOURCE_KEY_REFUSED = "source_key_refused"
    RELATIONSHIP_EXISTS = "relationship_exists"
    RELATIONSHIP_ABSENT = "relationship_absent"
    SELF_LOOP = "self_loop"
    CALENDAR_ABSENT = "calendar_absent"
    CALENDAR_IN_USE = "calendar_in_use"
    CONSTRAINT_CONFLICT = "constraint_conflict"
    PROGRESS_INVALID = "progress_invalid"
    BOUND_EXCEEDED = "bound_exceeded"
    CONTENT_INVALID = "content_invalid"


@dataclass(frozen=True, slots=True)
class ChangeSetRefusal:
    """The first failure: its 0-based op (or `len(ops)` for the final check)."""

    op_index: int
    op_error: ChangeOpError


@dataclass(frozen=True, slots=True)
class ApplicationReport:
    ops_applied: int
    relationships_removed: int
    content_changed: bool


@dataclass(frozen=True, slots=True)
class ChangeSetApplied:
    content: ScenarioContent
    report: ApplicationReport


class _OpFailedError(Exception):
    def __init__(self, error: ChangeOpError) -> None:
        super().__init__(error.value)
        self.error = error


def _fail(error: ChangeOpError) -> _OpFailedError:
    return _OpFailedError(error)


_INVALID: Final = ChangeOpError.INVALID_FIELD

# --- field readers ------------------------------------------------------------------


def _fields(
    op: Mapping[str, object], required: frozenset[str], optional: frozenset[str] = frozenset()
) -> Mapping[str, object]:
    names = set(op) - {"op"}
    if not required <= names or not names <= required | optional:
        raise _fail(_INVALID)
    return op


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise _fail(_INVALID)
    return value


def _int(value: object) -> int:
    if type(value) is not int:
        raise _fail(_INVALID)
    return value


def _optional_int(value: object) -> int | None:
    return None if value is None else _int(value)


def _instant(value: object) -> int:
    try:
        return parse_instant(value)
    except ValueError:
        raise _fail(_INVALID) from None


def _optional_instant(value: object) -> int | None:
    return None if value is None else _instant(value)


def _display(value: object) -> str:
    return normalize_display_text(_text(value))


def _wbs(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise _fail(_INVALID)
    return tuple(_display(label) for label in value)


def _day(value: object) -> date:
    text = _text(value)
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        raise _fail(_INVALID) from None
    if parsed.isoformat() != text:
        raise _fail(_INVALID)
    return parsed


def _intervals(value: object) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, list):
        raise _fail(_INVALID)
    pairs: list[tuple[int, int]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise _fail(_INVALID)
        pairs.append((_int(item[0]), _int(item[1])))
    return tuple(pairs)


def _enum[E: StrEnum](kind: type[E], value: object) -> E:
    try:
        return kind(_text(value))
    except ValueError:
        raise _fail(_INVALID) from None


def _build[T](factory: Callable[[], T]) -> T:
    """Construct a record; a constructor refusal is `invalid_field`."""
    try:
        return factory()
    except ValueError:
        raise _fail(_INVALID) from None


# --- the working copy -----------------------------------------------------------------


_EARLY: Final = frozenset({ConstraintType.SNET, ConstraintType.FNET})
_LATE: Final = frozenset({ConstraintType.SNLT, ConstraintType.FNLT})
_MANDATORY: Final = frozenset({ConstraintType.MSO, ConstraintType.MFO})


def _slot(kind: ConstraintType) -> frozenset[ConstraintType]:
    if kind in _EARLY:
        return _EARLY
    if kind in _LATE:
        return _LATE
    return _MANDATORY


class _Working:
    def __init__(self, parent: ScenarioContent) -> None:
        self.data_date = parent.data_date
        self.settings = parent.settings
        self.calendars = {item.key: item for item in parent.calendars}
        self.activities = {item.key: item for item in parent.activities}
        self.relationships = {(item.pred, item.succ): item for item in parent.relationships}
        self.relationships_removed = 0

    def content(self) -> ScenarioContent:
        return ScenarioContent(
            data_date=self.data_date,
            settings=self.settings,
            calendars=tuple(self.calendars.values()),
            activities=tuple(self.activities.values()),
            relationships=tuple(self.relationships.values()),
        )

    def activity(self, value: object) -> ScenarioActivity:
        key = _text(value)
        if key not in self.activities:
            raise _fail(ChangeOpError.KEY_ABSENT)
        return self.activities[key]

    def calendar_key(self, value: object) -> str:
        key = _text(value)
        if key not in self.calendars:
            raise _fail(ChangeOpError.CALENDAR_ABSENT)
        return key

    def optional_calendar_key(self, value: object) -> str | None:
        return None if value is None else self.calendar_key(value)

    def put(self, activity: ScenarioActivity, changes: Mapping[str, Any]) -> None:
        self.activities[activity.key] = _build(lambda: replace(activity, **changes))

    # --- ops ---------------------------------------------------------------------------

    def activity_add(self, op: Mapping[str, object]) -> None:
        fields = _fields(
            op,
            frozenset({"key", "name", "kind"}),
            frozenset({"calendar", "original_minutes", "remaining_minutes", "wbs_path"}),
        )
        key = _text(fields["key"])
        if key.startswith("sact_"):
            raise _fail(ChangeOpError.SOURCE_KEY_REFUSED)
        if not is_added_activity_key(key):
            raise _fail(_INVALID)
        kind = _enum(ActivityKind, fields["kind"])
        default = 0 if kind is ActivityKind.MILESTONE else None
        name = _display(fields["name"])
        wbs = _wbs(fields.get("wbs_path"))
        original = _optional_int(fields.get("original_minutes", default))
        remaining = _optional_int(fields.get("remaining_minutes", default))
        calendar = self.optional_calendar_key(fields.get("calendar"))
        activity = _build(
            lambda: ScenarioActivity(
                key=key,
                name=name,
                kind=kind,
                wbs_path=wbs,
                calendar=calendar,
                original_minutes=original,
                remaining_minutes=remaining,
            )
        )
        if key in self.activities:
            raise _fail(ChangeOpError.KEY_EXISTS)
        if len(self.activities) >= MAX_ACTIVITIES:
            raise _fail(ChangeOpError.BOUND_EXCEEDED)
        self.activities[key] = activity

    def activity_edit(self, op: Mapping[str, object]) -> None:
        optional = frozenset({"name", "kind", "calendar", "wbs_path"})
        fields = _fields(op, frozenset({"key"}), optional)
        if not set(fields) & optional:
            raise _fail(_INVALID)
        activity = self.activity(fields["key"])
        changes: dict[str, Any] = {}
        if "name" in fields:
            changes["name"] = _display(fields["name"])
        if "kind" in fields:
            changes["kind"] = _enum(ActivityKind, fields["kind"])
        if "wbs_path" in fields:
            changes["wbs_path"] = _wbs(fields["wbs_path"])
        if "calendar" in fields:
            changes["calendar"] = self.optional_calendar_key(fields["calendar"])
        self.put(activity, changes)

    def activity_remove(self, op: Mapping[str, object]) -> None:
        fields = _fields(op, frozenset({"key"}))
        activity = self.activity(fields["key"])
        del self.activities[activity.key]
        touching = [pair for pair in self.relationships if activity.key in pair]
        for pair in touching:
            del self.relationships[pair]
        self.relationships_removed += len(touching)

    def duration_set(self, op: Mapping[str, object]) -> None:
        optional = frozenset({"original_minutes", "remaining_minutes"})
        fields = _fields(op, frozenset({"key"}), optional)
        if not set(fields) & optional:
            raise _fail(_INVALID)
        activity = self.activity(fields["key"])
        changes = {name: _optional_int(fields[name]) for name in optional if name in fields}
        complete = activity.progress is not None and activity.progress.actual_finish is not None
        if complete and changes.get("remaining_minutes", 0) != 0:
            raise _fail(ChangeOpError.PROGRESS_INVALID)
        self.put(activity, changes)

    def distribution_set(self, op: Mapping[str, object]) -> None:
        fields = _fields(op, frozenset({"key", "distribution"}))
        activity = self.activity(fields["key"])
        raw = fields["distribution"]
        try:
            distribution: DurationDistribution = distribution_from_object(raw)
        except ValueError:
            raise _fail(_INVALID) from None
        self.put(activity, {"distribution": distribution})

    def distribution_clear(self, op: Mapping[str, object]) -> None:
        fields = _fields(op, frozenset({"key"}))
        self.put(self.activity(fields["key"]), {"distribution": None})

    def _pair(self, fields: Mapping[str, object]) -> tuple[str, str]:
        pred, succ = _text(fields["pred"]), _text(fields["succ"])
        if pred == succ:
            raise _fail(ChangeOpError.SELF_LOOP)
        self.activity(pred)
        self.activity(succ)
        return pred, succ

    def relationship_add(self, op: Mapping[str, object]) -> None:
        fields = _fields(op, frozenset({"pred", "succ", "type"}), frozenset({"lag_minutes"}))
        kind = _enum(RelationshipType, fields["type"])
        lag = _int(fields.get("lag_minutes", 0))
        pair = self._pair(fields)
        relationship = _build(lambda: ScenarioRelationship(pair[0], pair[1], kind, lag))
        if pair in self.relationships:
            raise _fail(ChangeOpError.RELATIONSHIP_EXISTS)
        if len(self.relationships) >= MAX_RELATIONSHIPS:
            raise _fail(ChangeOpError.BOUND_EXCEEDED)
        self.relationships[pair] = relationship

    def relationship_edit(self, op: Mapping[str, object]) -> None:
        optional = frozenset({"type", "lag_minutes"})
        fields = _fields(op, frozenset({"pred", "succ"}), optional)
        if not set(fields) & optional:
            raise _fail(_INVALID)
        changes: dict[str, Any] = {}
        if "type" in fields:
            changes["type"] = _enum(RelationshipType, fields["type"])
        if "lag_minutes" in fields:
            changes["lag_minutes"] = _int(fields["lag_minutes"])
        pair = self._pair(fields)
        if pair not in self.relationships:
            raise _fail(ChangeOpError.RELATIONSHIP_ABSENT)
        current = self.relationships[pair]
        self.relationships[pair] = _build(lambda: replace(current, **changes))

    def relationship_remove(self, op: Mapping[str, object]) -> None:
        fields = _fields(op, frozenset({"pred", "succ"}))
        pair = self._pair(fields)
        if pair not in self.relationships:
            raise _fail(ChangeOpError.RELATIONSHIP_ABSENT)
        del self.relationships[pair]

    def _exceptions_fit(self, replaced_key: str, calendar: ScenarioCalendar) -> None:
        others = sum(
            len(item.exceptions) for key, item in self.calendars.items() if key != replaced_key
        )
        if others + len(calendar.exceptions) > MAX_EXCEPTIONS_PER_VERSION:
            raise _fail(ChangeOpError.BOUND_EXCEEDED)

    def calendar_put(self, op: Mapping[str, object]) -> None:
        fields = _fields(op, frozenset({"calendar"}))
        raw = fields["calendar"]
        exceptions = raw.get("exceptions") if isinstance(raw, dict) else None
        if isinstance(exceptions, list) and len(exceptions) > MAX_EXCEPTIONS_PER_CALENDAR:
            raise _fail(ChangeOpError.BOUND_EXCEEDED)
        try:
            calendar = calendar_from_object(raw)
        except ValueError:
            raise _fail(_INVALID) from None
        if calendar.key not in self.calendars and len(self.calendars) >= MAX_CALENDARS:
            raise _fail(ChangeOpError.BOUND_EXCEEDED)
        self._exceptions_fit(calendar.key, calendar)
        self.calendars[calendar.key] = calendar

    def calendar_remove(self, op: Mapping[str, object]) -> None:
        fields = _fields(op, frozenset({"key"}))
        key = self.calendar_key(fields["key"])
        in_use = key == self.settings.default_calendar or any(
            activity.calendar == key for activity in self.activities.values()
        )
        if in_use:
            raise _fail(ChangeOpError.CALENDAR_IN_USE)
        del self.calendars[key]

    def calendar_exception_put(self, op: Mapping[str, object]) -> None:
        fields = _fields(op, frozenset({"key", "date", "intervals"}))
        day, intervals = _day(fields["date"]), _intervals(fields["intervals"])
        exception = _build(lambda: CalendarException(day=day, intervals=intervals))
        calendar = self.calendars[self.calendar_key(fields["key"])]
        kept = [item for item in calendar.exceptions if item.day != day]
        if len(kept) >= MAX_EXCEPTIONS_PER_CALENDAR:
            raise _fail(ChangeOpError.BOUND_EXCEEDED)
        updated = _build(lambda: replace(calendar, exceptions=(*kept, exception)))
        self._exceptions_fit(calendar.key, updated)
        self.calendars[calendar.key] = updated

    def calendar_exception_remove(self, op: Mapping[str, object]) -> None:
        fields = _fields(op, frozenset({"key", "date"}))
        day = _day(fields["date"])
        calendar = self.calendars[self.calendar_key(fields["key"])]
        kept = tuple(item for item in calendar.exceptions if item.day != day)
        self.calendars[calendar.key] = _build(lambda: replace(calendar, exceptions=kept))

    def constraint_set(self, op: Mapping[str, object]) -> None:
        fields = _fields(op, frozenset({"key", "type", "at"}))
        kind = _enum(ConstraintType, fields["type"])
        when = _instant(fields["at"])
        activity = self.activity(fields["key"])
        slot = _slot(kind)
        kept = [item for item in activity.constraints if item.type not in slot]
        mixes_mandatory = (slot is _MANDATORY and bool(kept)) or any(
            item.type in _MANDATORY for item in kept
        )
        if mixes_mandatory:
            raise _fail(ChangeOpError.CONSTRAINT_CONFLICT)
        self.put(activity, {"constraints": (*kept, ActivityConstraint(kind, when))})

    def constraint_clear(self, op: Mapping[str, object]) -> None:
        fields = _fields(op, frozenset({"key", "type"}))
        kind = _enum(ConstraintType, fields["type"])
        activity = self.activity(fields["key"])
        kept = tuple(item for item in activity.constraints if item.type is not kind)
        self.put(activity, {"constraints": kept})

    def progress_set(self, op: Mapping[str, object]) -> None:
        fields = _fields(
            op,
            frozenset({"key", "actual_start"}),
            frozenset({"actual_finish", "remaining_minutes"}),
        )
        start = _instant(fields["actual_start"])
        finish = _optional_instant(fields.get("actual_finish"))
        remaining_given = "remaining_minutes" in fields
        remaining = _optional_int(fields.get("remaining_minutes"))
        activity = self.activity(fields["key"])
        if start > self.data_date or (finish is not None and not start <= finish <= self.data_date):
            raise _fail(ChangeOpError.PROGRESS_INVALID)
        if finish is not None:
            if remaining_given and remaining != 0:
                raise _fail(ChangeOpError.PROGRESS_INVALID)
            remaining, remaining_given = 0, True
        progress = ActivityProgress(actual_start=start, actual_finish=finish)
        changes: dict[str, Any] = {"progress": progress}
        if remaining_given:
            changes["remaining_minutes"] = remaining
        self.put(activity, changes)

    def progress_clear(self, op: Mapping[str, object]) -> None:
        fields = _fields(op, frozenset({"key"}))
        self.put(self.activity(fields["key"]), {"progress": None})

    def data_date_set(self, op: Mapping[str, object]) -> None:
        fields = _fields(op, frozenset({"at"}))
        self.data_date = _instant(fields["at"])

    def settings_set(self, op: Mapping[str, object]) -> None:
        optional = frozenset(
            {
                "default_calendar",
                "lag_calendar",
                "progress_policy",
                "must_finish_by",
                "critical_float_threshold_minutes",
            }
        )
        fields = _fields(op, frozenset(), optional)
        if not set(fields) & optional:
            raise _fail(_INVALID)
        changes: dict[str, Any] = {}
        if "lag_calendar" in fields:
            changes["lag_calendar"] = _enum(LagCalendar, fields["lag_calendar"])
        if "progress_policy" in fields:
            changes["progress_policy"] = _enum(ProgressPolicy, fields["progress_policy"])
        if "must_finish_by" in fields:
            changes["must_finish_by"] = _optional_instant(fields["must_finish_by"])
        if "critical_float_threshold_minutes" in fields:
            changes["critical_float_threshold_minutes"] = _int(
                fields["critical_float_threshold_minutes"]
            )
        if "default_calendar" in fields:
            changes["default_calendar"] = self.calendar_key(fields["default_calendar"])
        current = self.settings
        self.settings = _build(lambda: replace(current, **changes))


_HANDLERS: Final[dict[ChangeOp, Callable[[_Working, Mapping[str, object]], None]]] = {
    ChangeOp.ACTIVITY_ADD: _Working.activity_add,
    ChangeOp.ACTIVITY_EDIT: _Working.activity_edit,
    ChangeOp.ACTIVITY_REMOVE: _Working.activity_remove,
    ChangeOp.DURATION_SET: _Working.duration_set,
    ChangeOp.DISTRIBUTION_SET: _Working.distribution_set,
    ChangeOp.DISTRIBUTION_CLEAR: _Working.distribution_clear,
    ChangeOp.RELATIONSHIP_ADD: _Working.relationship_add,
    ChangeOp.RELATIONSHIP_EDIT: _Working.relationship_edit,
    ChangeOp.RELATIONSHIP_REMOVE: _Working.relationship_remove,
    ChangeOp.CALENDAR_PUT: _Working.calendar_put,
    ChangeOp.CALENDAR_REMOVE: _Working.calendar_remove,
    ChangeOp.CALENDAR_EXCEPTION_PUT: _Working.calendar_exception_put,
    ChangeOp.CALENDAR_EXCEPTION_REMOVE: _Working.calendar_exception_remove,
    ChangeOp.CONSTRAINT_SET: _Working.constraint_set,
    ChangeOp.CONSTRAINT_CLEAR: _Working.constraint_clear,
    ChangeOp.PROGRESS_SET: _Working.progress_set,
    ChangeOp.PROGRESS_CLEAR: _Working.progress_clear,
    ChangeOp.DATA_DATE_SET: _Working.data_date_set,
    ChangeOp.SETTINGS_SET: _Working.settings_set,
}


_OP_NAMES: Final = frozenset(member.value for member in ChangeOp)


def _change_set_misfit(ops: Sequence[object]) -> ChangeOpError | None:
    """`bound_exceeded` outside the bounds; `invalid_field` when not JSON-encodable."""
    if not 1 <= len(ops) <= MAX_CHANGE_SET_OPS:
        return ChangeOpError.BOUND_EXCEEDED
    try:
        encoded = change_set_bytes(ops)
    except (TypeError, ValueError):
        return ChangeOpError.INVALID_FIELD
    return ChangeOpError.BOUND_EXCEEDED if len(encoded) > MAX_CHANGE_SET_BYTES else None


def apply_change_set(
    parent: ScenarioContent, ops: Sequence[object]
) -> ChangeSetApplied | ChangeSetRefusal:
    """Apply `ops` in request order (section 2.9); never raises for client input.

    A change set outside 1..5,000 ops or 4,194,304 canonical bytes is refused before
    any op as `(0, bound_exceeded)`; one that is not JSON-encodable (which a JSON
    transport can never send) as `(0, invalid_field)`.
    """
    misfit = _change_set_misfit(ops)
    if misfit is not None:
        return ChangeSetRefusal(0, misfit)
    working = _Working(parent)
    for index, op in enumerate(ops):
        if not isinstance(op, Mapping):
            return ChangeSetRefusal(index, ChangeOpError.INVALID_FIELD)
        raw_name = op.get("op")
        if not isinstance(raw_name, str) or raw_name not in _OP_NAMES:
            return ChangeSetRefusal(index, ChangeOpError.UNKNOWN_OP)
        name = ChangeOp(raw_name)
        try:
            _HANDLERS[name](working, op)
        except _OpFailedError as failure:
            return ChangeSetRefusal(index, failure.error)
    try:
        content = working.content()
    except ValueError:
        return ChangeSetRefusal(len(ops), ChangeOpError.CONTENT_INVALID)
    if content_problem(content) is not None:
        return ChangeSetRefusal(len(ops), ChangeOpError.CONTENT_INVALID)
    report = ApplicationReport(
        ops_applied=len(ops),
        relationships_removed=working.relationships_removed,
        content_changed=content != parent,
    )
    return ChangeSetApplied(content=content, report=report)
