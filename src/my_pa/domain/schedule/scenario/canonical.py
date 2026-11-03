"""Schedule Scenarios S6-1: canonical documents and their digests.

Contract: `docs/architecture/schedule-scenarios-contract.md` sections 2.3, 3.11,
4.1, 4.3 and 6.3. Every digest is `sha256(domain_prefix + canonical)` with a
`\\n`-terminated prefix per document and the one canonical encoder of the
schedule package (`my_pa.domain.schedule.canonical.canonical_json_bytes`:
sorted keys, compact, ASCII, no NaN). Lists keep the canonical order the
records already hold; numbers are Python `int` only.

`content_from_object` is the strict inverse of `content_object`: exact key
sets, closed values, and every record rebuilt through its constructor. Any
refusal is `ScenarioDecodeError`, whose message carries nothing of the object.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Final

from my_pa.domain.schedule.canonical import canonical_json_bytes
from my_pa.domain.schedule.model import ScheduleCellState, ScheduleDateCell, ScheduleDurationCell
from my_pa.domain.schedule.scenario.model import (
    ActivityConstraint,
    ActivityKind,
    ActivityProgress,
    CalendarException,
    ConstraintType,
    DistributionKind,
    DurationDistribution,
    LagCalendar,
    ProgressPolicy,
    PublishedReference,
    RelationshipType,
    ScenarioActivity,
    ScenarioCalendar,
    ScenarioContent,
    ScenarioRelationship,
    ScenarioSettings,
    format_instant,
    parse_instant,
)

__all__ = [
    "CHANGE_SET_SCHEMA",
    "CONTENT_SCHEMA",
    "DISTRIBUTIONS_SCHEMA",
    "OUTPUT_SCHEMA",
    "REQUEST_SCHEMA",
    "RESULT_SCHEMA",
    "ScenarioDecodeError",
    "activity_object",
    "calendar_from_object",
    "change_set_bytes",
    "change_set_object",
    "change_set_sha256",
    "content_bytes",
    "content_from_object",
    "content_object",
    "content_sha256",
    "distribution_from_object",
    "distribution_spec_sha256",
    "output_payload_sha256",
    "result_bytes",
    "result_sha256",
    "scenario_request_digest",
]

CONTENT_SCHEMA: Final = "schedule-scenario-content-v1"
CHANGE_SET_SCHEMA: Final = "schedule-scenario-change-set-v1"
RESULT_SCHEMA: Final = "schedule-cpm-result-v1"
OUTPUT_SCHEMA: Final = "schedule-scenario-output-v1"
DISTRIBUTIONS_SCHEMA: Final = "schedule-scenario-distributions-v1"
REQUEST_SCHEMA: Final = "schedule-scenario-request-v1"


def _digest(schema: str, payload: bytes) -> str:
    return hashlib.sha256(schema.encode("ascii") + b"\n" + payload).hexdigest()


# --- content (section 2.3) --------------------------------------------------------


def _optional_instant(value: int | None) -> str | None:
    return None if value is None else format_instant(value)


def _intervals(pattern: Sequence[tuple[int, int]]) -> list[list[int]]:
    return [[start, end] for start, end in pattern]


def _calendar_object(calendar: ScenarioCalendar) -> dict[str, object]:
    return {
        "key": calendar.key,
        "week": [_intervals(day) for day in calendar.week],
        "exceptions": [
            {"date": item.day.isoformat(), "intervals": _intervals(item.intervals)}
            for item in calendar.exceptions
        ],
    }


def _duration_cell(cell: ScheduleDurationCell) -> dict[str, object]:
    return {
        "state": cell.state.value,
        "value": None if cell.value is None else format(cell.value, "f"),
    }


def _date_cell(cell: ScheduleDateCell) -> dict[str, object]:
    return {
        "state": cell.state.value,
        "value": None if cell.value is None else cell.value.isoformat(),
        "marker": cell.marker,
    }


def _reference_object(reference: PublishedReference | None) -> dict[str, object] | None:
    if reference is None:
        return None
    return {
        "publication_id": reference.publication_id,
        "published_activity_id": reference.published_activity_id,
        "original_duration": _duration_cell(reference.original_duration),
        "remaining_duration": _duration_cell(reference.remaining_duration),
        "start": _date_cell(reference.start),
        "finish": _date_cell(reference.finish),
    }


def _distribution_object(value: DurationDistribution | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {"kind": value.kind.value, **value.parameters()}


def activity_object(activity: ScenarioActivity) -> dict[str, object]:
    progress = activity.progress
    return {
        "key": activity.key,
        "name": activity.name,
        "kind": activity.kind.value,
        "wbs_path": None if activity.wbs_path is None else list(activity.wbs_path),
        "calendar": activity.calendar,
        "original_minutes": activity.original_minutes,
        "remaining_minutes": activity.remaining_minutes,
        "constraints": [
            {"type": item.type.value, "at": format_instant(item.at)}
            for item in activity.constraints
        ],
        "progress": None
        if progress is None
        else {
            "actual_start": format_instant(progress.actual_start),
            "actual_finish": _optional_instant(progress.actual_finish),
        },
        "distribution": _distribution_object(activity.distribution),
        "published_reference": _reference_object(activity.published_reference),
    }


def content_object(content: ScenarioContent) -> dict[str, object]:
    """The `schedule-scenario-content-v1` object; every key present, absent = null."""
    settings = content.settings
    return {
        "schema": CONTENT_SCHEMA,
        "data_date": format_instant(content.data_date),
        "settings": {
            "default_calendar": settings.default_calendar,
            "lag_calendar": settings.lag_calendar.value,
            "progress_policy": settings.progress_policy.value,
            "must_finish_by": _optional_instant(settings.must_finish_by),
            "critical_float_threshold_minutes": settings.critical_float_threshold_minutes,
        },
        "calendars": [_calendar_object(calendar) for calendar in content.calendars],
        "activities": [activity_object(activity) for activity in content.activities],
        "relationships": [
            {
                "pred": item.pred,
                "succ": item.succ,
                "type": item.type.value,
                "lag_minutes": item.lag_minutes,
            }
            for item in content.relationships
        ],
    }


def content_bytes(content: ScenarioContent) -> bytes:
    return canonical_json_bytes(content_object(content))


def content_sha256(content: ScenarioContent) -> str:
    """`sha256(b"schedule-scenario-content-v1\\n" + canonical)`."""
    return _digest(CONTENT_SCHEMA, content_bytes(content))


# --- decoding --------------------------------------------------------------------------


class ScenarioDecodeError(ValueError):
    """The object is not a valid canonical scenario content. No content in the message."""


def _refuse() -> ScenarioDecodeError:
    return ScenarioDecodeError("not a valid schedule-scenario-content-v1 object")


def _mapping(value: object, keys: frozenset[str]) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise _refuse()
    return value


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise _refuse()
    return value


def _int(value: object) -> int:
    if type(value) is not int:
        raise _refuse()
    return value


def _optional_int(value: object) -> int | None:
    return None if value is None else _int(value)


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise _refuse()
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value)


def _instant(value: object) -> int:
    return parse_instant(_text(value))


def _optional_instant_value(value: object) -> int | None:
    return None if value is None else _instant(value)


def _day(value: object) -> date:
    text = _text(value)
    parsed = date.fromisoformat(text)
    if parsed.isoformat() != text:
        raise _refuse()
    return parsed


def _pattern(value: object) -> tuple[tuple[int, int], ...]:
    intervals: list[tuple[int, int]] = []
    for item in _list(value):
        pair = _list(item)
        if len(pair) != 2:
            raise _refuse()
        intervals.append((_int(pair[0]), _int(pair[1])))
    return tuple(intervals)


_CALENDAR_KEYS: Final = frozenset({"key", "week", "exceptions"})
_EXCEPTION_KEYS: Final = frozenset({"date", "intervals"})
_SETTINGS_KEYS: Final = frozenset(
    {
        "default_calendar",
        "lag_calendar",
        "progress_policy",
        "must_finish_by",
        "critical_float_threshold_minutes",
    }
)
_ACTIVITY_KEYS: Final = frozenset(
    {
        "key",
        "name",
        "kind",
        "wbs_path",
        "calendar",
        "original_minutes",
        "remaining_minutes",
        "constraints",
        "progress",
        "distribution",
        "published_reference",
    }
)
_REFERENCE_KEYS: Final = frozenset(
    {
        "publication_id",
        "published_activity_id",
        "original_duration",
        "remaining_duration",
        "start",
        "finish",
    }
)
_RELATIONSHIP_KEYS: Final = frozenset({"pred", "succ", "type", "lag_minutes"})
_CONTENT_KEYS: Final = frozenset(
    {"schema", "data_date", "settings", "calendars", "activities", "relationships"}
)
_DISTRIBUTION_KEYS: Final[dict[DistributionKind, frozenset[str]]] = {
    DistributionKind.TRIANGULAR: frozenset({"kind", "min", "mode", "max"}),
    DistributionKind.PERT: frozenset({"kind", "min", "mode", "max"}),
    DistributionKind.UNIFORM: frozenset({"kind", "min", "max"}),
    DistributionKind.BOUNDED_NORMAL: frozenset({"kind", "min", "mean", "sd", "max"}),
}


def calendar_from_object(value: object) -> ScenarioCalendar:
    """One calendar object (also the `calendar.put` op's payload)."""
    item = _mapping(value, _CALENDAR_KEYS)
    week = _list(item["week"])
    return ScenarioCalendar(
        key=_text(item["key"]),
        week=tuple(_pattern(day) for day in week),
        exceptions=tuple(
            CalendarException(day=_day(entry["date"]), intervals=_pattern(entry["intervals"]))
            for entry in (_mapping(raw, _EXCEPTION_KEYS) for raw in _list(item["exceptions"]))
        ),
    )


def distribution_from_object(value: object) -> DurationDistribution:
    if not isinstance(value, dict):
        raise _refuse()
    kind = DistributionKind(_text(value.get("kind")))
    item = _mapping(value, _DISTRIBUTION_KEYS[kind])
    return DurationDistribution(
        kind=kind,
        min=_int(item["min"]),
        max=_int(item["max"]),
        mode=_optional_int(item.get("mode")),
        mean=_optional_int(item.get("mean")),
        sd=_optional_int(item.get("sd")),
    )


def _duration_cell_from(value: object) -> ScheduleDurationCell:
    cell = _mapping(value, frozenset({"state", "value"}))
    raw = _optional_text(cell["value"])
    return ScheduleDurationCell(
        state=ScheduleCellState(_text(cell["state"])),
        value=None if raw is None else Decimal(raw),
    )


def _date_cell_from(value: object) -> ScheduleDateCell:
    cell = _mapping(value, frozenset({"state", "value", "marker"}))
    raw = cell["value"]
    return ScheduleDateCell(
        state=ScheduleCellState(_text(cell["state"])),
        value=None if raw is None else _day(raw),
        marker=_optional_text(cell["marker"]),
    )


def _reference_from(value: object) -> PublishedReference | None:
    if value is None:
        return None
    item = _mapping(value, _REFERENCE_KEYS)
    return PublishedReference(
        publication_id=_text(item["publication_id"]),
        published_activity_id=_text(item["published_activity_id"]),
        original_duration=_duration_cell_from(item["original_duration"]),
        remaining_duration=_duration_cell_from(item["remaining_duration"]),
        start=_date_cell_from(item["start"]),
        finish=_date_cell_from(item["finish"]),
    )


def _progress_from(value: object) -> ActivityProgress | None:
    if value is None:
        return None
    item = _mapping(value, frozenset({"actual_start", "actual_finish"}))
    return ActivityProgress(
        actual_start=_instant(item["actual_start"]),
        actual_finish=_optional_instant_value(item["actual_finish"]),
    )


def _activity_from(value: object) -> ScenarioActivity:
    item = _mapping(value, _ACTIVITY_KEYS)
    path = item["wbs_path"]
    distribution = item["distribution"]
    return ScenarioActivity(
        key=_text(item["key"]),
        name=_text(item["name"]),
        kind=ActivityKind(_text(item["kind"])),
        wbs_path=None if path is None else tuple(_text(label) for label in _list(path)),
        calendar=_optional_text(item["calendar"]),
        original_minutes=_optional_int(item["original_minutes"]),
        remaining_minutes=_optional_int(item["remaining_minutes"]),
        constraints=tuple(
            ActivityConstraint(type=ConstraintType(_text(entry["type"])), at=_instant(entry["at"]))
            for entry in (
                _mapping(raw, frozenset({"type", "at"})) for raw in _list(item["constraints"])
            )
        ),
        progress=_progress_from(item["progress"]),
        distribution=None if distribution is None else distribution_from_object(distribution),
        published_reference=_reference_from(item["published_reference"]),
    )


def _relationship_from(value: object) -> ScenarioRelationship:
    item = _mapping(value, _RELATIONSHIP_KEYS)
    return ScenarioRelationship(
        pred=_text(item["pred"]),
        succ=_text(item["succ"]),
        type=RelationshipType(_text(item["type"])),
        lag_minutes=_int(item["lag_minutes"]),
    )


def content_from_object(obj: object) -> ScenarioContent:
    """Rebuild a content from its object, or raise `ScenarioDecodeError`.

    List order is not required (the records sort themselves); keys, types and
    closed values are. Cross-references are left to `content_problem`.
    """
    try:
        item = _mapping(obj, _CONTENT_KEYS)
        if item["schema"] != CONTENT_SCHEMA:
            raise _refuse()
        settings = _mapping(item["settings"], _SETTINGS_KEYS)
        return ScenarioContent(
            data_date=_instant(item["data_date"]),
            settings=ScenarioSettings(
                default_calendar=_text(settings["default_calendar"]),
                lag_calendar=LagCalendar(_text(settings["lag_calendar"])),
                progress_policy=ProgressPolicy(_text(settings["progress_policy"])),
                must_finish_by=_optional_instant_value(settings["must_finish_by"]),
                critical_float_threshold_minutes=_int(settings["critical_float_threshold_minutes"]),
            ),
            calendars=tuple(calendar_from_object(raw) for raw in _list(item["calendars"])),
            activities=tuple(_activity_from(raw) for raw in _list(item["activities"])),
            relationships=tuple(_relationship_from(raw) for raw in _list(item["relationships"])),
        )
    except ScenarioDecodeError:
        raise
    except (ValueError, TypeError, KeyError, ArithmeticError):
        raise _refuse() from None


# --- change set, result, distributions, outputs, requests -----------------------------


def change_set_object(ops: Sequence[object]) -> dict[str, object]:
    """`schedule-scenario-change-set-v1`: the ops in request order."""
    return {"schema": CHANGE_SET_SCHEMA, "ops": list(ops)}


def change_set_bytes(ops: Sequence[object]) -> bytes:
    return canonical_json_bytes(change_set_object(ops))


def change_set_sha256(ops: Sequence[object]) -> str:
    return _digest(CHANGE_SET_SCHEMA, change_set_bytes(ops))


def result_bytes(document: Mapping[str, object]) -> bytes:
    return canonical_json_bytes(dict(document))


def result_sha256(document: Mapping[str, object]) -> str:
    """`sha256(b"schedule-cpm-result-v1\\n" + canonical)` of a result document."""
    if document.get("schema") != RESULT_SCHEMA:
        raise ValueError("a result document carries the schedule-cpm-result-v1 schema")
    return _digest(RESULT_SCHEMA, result_bytes(document))


def distribution_spec_sha256(content: ScenarioContent) -> str:
    """Section 4.3: the activities that carry a distribution, by key."""
    spec = [
        {"key": activity.key, "distribution": _distribution_object(activity.distribution)}
        for activity in content.activities
        if activity.distribution is not None
    ]
    return _digest(DISTRIBUTIONS_SCHEMA, canonical_json_bytes(spec))


def output_payload_sha256(document: Mapping[str, object]) -> str:
    """`sha256(b"schedule-scenario-output-v1\\n" + canonical)` of a validated output."""
    if document.get("schema") != OUTPUT_SCHEMA:
        raise ValueError("an output document carries the schedule-scenario-output-v1 schema")
    return _digest(OUTPUT_SCHEMA, canonical_json_bytes(dict(document)))


def scenario_request_digest(
    principal_id: str, capability: str, request: Mapping[str, object]
) -> str:
    """Section 6.3: the plane idempotency digest; the key itself is never digested."""
    body = {
        "principal_id": principal_id,
        "capability": capability,
        "request": {name: value for name, value in request.items() if name != "idempotency_key"},
    }
    return _digest(REQUEST_SCHEMA, canonical_json_bytes(body))
