"""Decode a `cpm-workbench-p6-frame-v1` frame back into the parse result (S7-3).

Contract `docs/architecture/schedule-xer-import-contract.md` sections 9.3 (H4:
one canonical frame from the contained child) and 13.2 (the frame is
re-rendered and bound to the digest by the parent). The worker parent never
imports the parser (acceptance C4); it receives JSON and rebuilds the
`P6ParseResult` here, typing every value by the catalogue alone, so the
result can be rendered again with `frame_bytes` and compared byte for byte
with what the child wrote (a lossless, canonical decode or a refusal).

Every shape is closed: an unknown key, a missing key, a value of the wrong
JSON type or a value the catalogue does not type that way is
`P6FrameDecodeError`. It proves the frame's shape, not the truth of its rows
(residual U2-10 of S5b-2, unchanged). Pure, standard library and the
catalogue/model/frame modules only -- never `parser`, `reader`, `values`,
`calendar` or `profile`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Final

from my_pa.domain.schedule.p6.catalogue import (
    CATALOGUE_VERSION,
    EntityKind,
    ValueType,
    table_fields,
)
from my_pa.domain.schedule.p6.frame import FRAME_SCHEMA
from my_pa.domain.schedule.p6.model import (
    PROFILE_ID,
    PROFILE_VERSION,
    Bound,
    CalendarStatus,
    P6Calendar,
    P6Entity,
    P6FieldValue,
    P6Header,
    P6Issue,
    P6IssueCode,
    P6ObservedField,
    P6ObservedTable,
    P6Outcome,
    P6ParseResult,
    P6Severity,
    P6Value,
)

__all__ = ["P6FrameDecodeError", "decode_p6_frame", "entity_columns"]

_NUMBER: Final = re.compile(r"\A-?\d{1,15}(\.\d{1,6})?\Z")
_TIMESTAMP_FORMAT: Final = "%Y-%m-%dT%H:%M"
_TIMESTAMP: Final = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\Z")
_DAY: Final = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_SHA256: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_WEEK_DAYS: Final = 7

type _Decoder = Callable[[object], P6Value | tuple[str, ...]]


class P6FrameDecodeError(ValueError):
    """The frame is not a well-formed `cpm-workbench-p6-frame-v1` frame."""


def _fail() -> P6FrameDecodeError:
    return P6FrameDecodeError("frame")


def _object(value: object, keys: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise _fail()
    return value


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise _fail()
    return value


def _int(value: object) -> int:
    if type(value) is not int:
        raise _fail()
    return value


def _optional_int(value: object) -> int | None:
    return None if value is None else _int(value)


def _str(value: object) -> str:
    if type(value) is not str:
        raise _fail()
    return value


def _optional_str(value: object) -> str | None:
    return None if value is None else _str(value)


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise _fail()
    return value


def _decimal(value: object) -> int | Decimal:
    if type(value) is int:
        return value
    text = _str(value)
    if not _NUMBER.match(text):
        raise _fail()
    return Decimal(text)


def _timestamp(value: object) -> datetime:
    text = _str(value)
    if not _TIMESTAMP.match(text):
        raise _fail()
    try:
        return datetime.strptime(text, _TIMESTAMP_FORMAT)
    except ValueError:
        raise _fail() from None


def _day(value: object) -> date:
    text = _str(value)
    if not _DAY.match(text):
        raise _fail()
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise _fail() from None


def _nullable(decode: Callable[[object], P6Value]) -> _Decoder:
    def decoded(value: object) -> P6Value:
        return None if value is None else decode(value)

    return decoded


def _labels(value: object) -> tuple[str, ...]:
    return tuple(_str(item) for item in _list(value))


_BY_TYPE: Final[Mapping[ValueType, _Decoder]] = {
    ValueType.ID: _nullable(_int),
    ValueType.INT: _nullable(_int),
    ValueType.HOURS: _nullable(_decimal),
    ValueType.NUM: _nullable(_decimal),
    ValueType.FLAG: _nullable(_bool),
    ValueType.TS: _nullable(_timestamp),
    ValueType.TEXT: _nullable(_str),
    ValueType.NAME: _nullable(_str),
    ValueType.ENUM: _nullable(_str),
}


def _typed(*tables: str) -> dict[str, _Decoder]:
    """The typed columns the parser writes for `tables` (its `_columns` rule)."""
    found: dict[str, _Decoder] = {}
    for table in tables:
        for field in table_fields(table):
            if field.is_typed and field.typed_column is not None and field.value_type in _BY_TYPE:
                found[field.typed_column] = _BY_TYPE[field.value_type]
    return found


def entity_columns(kind: EntityKind) -> Mapping[str, _Decoder]:
    """Every column a frame entity of `kind` carries, and how its value decodes."""
    return _ENTITY_COLUMNS[kind]


_ENTITY_COLUMNS: Final[Mapping[EntityKind, Mapping[str, _Decoder]]] = {
    EntityKind.PROJECT: {
        **_typed("PROJECT", "SCHEDOPTIONS"),
        "project_name": _str,
        "export_version": _str,
        "export_date": _nullable(_day),
        "encoding": _str,
    },
    EntityKind.WBS: {**_typed("PROJWBS"), "depth": _int, "wbs_path": _labels},
    EntityKind.ACTIVITY: {
        **_typed("TASK"),
        "start_at": _timestamp,
        "finish_at": _timestamp,
        "wbs_path": _labels,
        "kind": _str,
    },
    EntityKind.RELATIONSHIP: {
        **_typed("TASKPRED"),
        "pred_activity_id": _nullable(_str),
        "succ_activity_id": _nullable(_str),
        "is_external": _bool,
    },
}
_CALENDAR_COLUMNS: Final = _typed("CALENDAR")

_FRAME_KEYS: Final = frozenset(
    {
        "activities",
        "calendars",
        "captured_keys",
        "counts",
        "field_values",
        "header",
        "issue_counts",
        "issues",
        "observed_fields",
        "outcome",
        "profile",
        "project",
        "relationships",
        "schema",
        "tables",
        "wbs",
    }
)
_ENTITY_KEYS: Final = frozenset({"columns", "p6_id", "record_line"})
_ISSUE_KEYS: Final = frozenset({"bound", "code", "field", "line", "severity", "table"})
_TABLE_KEYS: Final = frozenset({"catalogued", "line", "name", "position", "records"})
_FIELD_KEYS: Final = frozenset(
    {
        "captured",
        "catalogued",
        "field",
        "field_key",
        "max_length",
        "min_length",
        "nonempty",
        "over_length",
        "position",
        "records",
        "shapes",
        "table",
        "table_position",
        "tier",
        "unknown_enum",
        "unknown_enum_tokens",
    }
)
_CALENDAR_KEYS: Final = frozenset(
    {
        "columns",
        "data_sha256",
        "exception_count",
        "exceptions",
        "p6_id",
        "record_line",
        "status",
        "used",
        "week",
    }
)
_VALUE_KEYS: Final = frozenset(
    {
        "activity_id",
        "code_path",
        "description",
        "entity_kind",
        "entity_p6_id",
        "field_key",
        "ordinal",
        "record_line",
        "source_table",
        "value",
        "value_type",
    }
)
_FIELD_VALUE_DECODERS: Final[Mapping[str, Callable[[object], P6Value]]] = {
    "text": _str,
    "number": _decimal,
    "ts": _timestamp,
    "flag": _bool,
}


def _closed[T](enum: Callable[[str], T], value: object) -> T:
    try:
        return enum(_str(value))
    except ValueError:
        raise _fail() from None


def _entity(kind: EntityKind, value: object) -> P6Entity:
    entity = _object(value, _ENTITY_KEYS)
    decoders = _ENTITY_COLUMNS[kind]
    columns = entity["columns"]
    if not isinstance(columns, dict) or set(columns) != set(decoders):
        raise _fail()
    return P6Entity(
        entity_kind=kind,
        p6_id=_int(entity["p6_id"]),
        record_line=_int(entity["record_line"]),
        columns=tuple((name, decoders[name](columns[name])) for name in decoders),
    )


def _intervals(value: object) -> tuple[tuple[int, int], ...]:
    pairs: list[tuple[int, int]] = []
    for item in _list(value):
        pair = _list(item)
        if len(pair) != 2:
            raise _fail()
        pairs.append((_int(pair[0]), _int(pair[1])))
    return tuple(pairs)


def _calendar(value: object) -> P6Calendar:
    calendar = _object(value, _CALENDAR_KEYS)
    columns = calendar["columns"]
    if not isinstance(columns, dict) or set(columns) != set(_CALENDAR_COLUMNS):
        raise _fail()
    week = tuple(_intervals(day) for day in _list(calendar["week"]))
    if len(week) not in (0, _WEEK_DAYS):
        raise _fail()
    exceptions: list[tuple[date, tuple[tuple[int, int], ...]]] = []
    for item in _list(calendar["exceptions"]):
        exception = _object(item, frozenset({"date", "intervals"}))
        exceptions.append((_day(exception["date"]), _intervals(exception["intervals"])))
    digest = _optional_str(calendar["data_sha256"])
    if digest is not None and not _SHA256.match(digest):
        raise _fail()
    if _int(calendar["exception_count"]) != len(exceptions):
        raise _fail()
    scalar: list[tuple[str, P6Value]] = []
    for name, decode in _CALENDAR_COLUMNS.items():
        decoded = decode(columns[name])
        if isinstance(decoded, tuple):
            raise _fail()
        scalar.append((name, decoded))
    return P6Calendar(
        p6_id=_int(calendar["p6_id"]),
        record_line=_int(calendar["record_line"]),
        columns=tuple(scalar),
        status=_closed(CalendarStatus, calendar["status"]),
        used=_bool(calendar["used"]),
        week=week,
        exceptions=tuple(exceptions),
        data_sha256=digest,
    )


def _issue(value: object) -> P6Issue:
    issue = _object(value, _ISSUE_KEYS)
    bound = issue["bound"]
    return P6Issue(
        code=_closed(P6IssueCode, issue["code"]),
        severity=_closed(P6Severity, issue["severity"]),
        table=_optional_str(issue["table"]),
        line=_optional_int(issue["line"]),
        field=_optional_str(issue["field"]),
        bound=None if bound is None else _closed(Bound, bound),
    )


def _table(value: object) -> P6ObservedTable:
    table = _object(value, _TABLE_KEYS)
    return P6ObservedTable(
        name=_optional_str(table["name"]),
        position=_int(table["position"]),
        line=_int(table["line"]),
        catalogued=_bool(table["catalogued"]),
        records=_int(table["records"]),
    )


def _observed(value: object) -> P6ObservedField:
    field = _object(value, _FIELD_KEYS)
    shapes = field["shapes"]
    if not isinstance(shapes, dict):
        raise _fail()
    return P6ObservedField(
        table=_optional_str(field["table"]),
        table_position=_int(field["table_position"]),
        field=_optional_str(field["field"]),
        position=_int(field["position"]),
        field_key=_optional_str(field["field_key"]),
        catalogued=_bool(field["catalogued"]),
        tier=_optional_str(field["tier"]),
        records=_int(field["records"]),
        nonempty=_int(field["nonempty"]),
        min_length=_optional_int(field["min_length"]),
        max_length=_optional_int(field["max_length"]),
        shapes=tuple((_str(name), _int(count)) for name, count in shapes.items()),
        unknown_enum=_int(field["unknown_enum"]),
        unknown_enum_tokens=_labels(field["unknown_enum_tokens"]),
        over_length=_int(field["over_length"]),
        captured=_bool(field["captured"]),
    )


def _field_value(value: object) -> P6FieldValue:
    item = _object(value, _VALUE_KEYS)
    value_type = _str(item["value_type"])
    decode = _FIELD_VALUE_DECODERS.get(value_type)
    if decode is None:
        raise _fail()
    return P6FieldValue(
        entity_kind=_closed(EntityKind, item["entity_kind"]),
        entity_p6_id=_int(item["entity_p6_id"]),
        activity_id=_optional_str(item["activity_id"]),
        field_key=_str(item["field_key"]),
        ordinal=_int(item["ordinal"]),
        value_type=value_type,
        value=decode(item["value"]),
        code_path=_labels(item["code_path"]),
        description=_optional_str(item["description"]),
        source_table=_str(item["source_table"]),
        record_line=_int(item["record_line"]),
    )


def _header(value: object) -> P6Header | None:
    if value is None:
        return None
    header = _object(value, frozenset({"encoding", "export_date", "export_version"}))
    exported = header["export_date"]
    return P6Header(
        export_version=_str(header["export_version"]),
        export_date=None if exported is None else _day(exported),
        encoding=_str(header["encoding"]),
    )


def decode_p6_frame(value: object) -> P6ParseResult:
    """The `P6ParseResult` a frame object renders, or `P6FrameDecodeError`.

    The profile must be this build's (`p6_xer_v1`, its version and catalogue
    version): a frame of another catalogue is refused, never reinterpreted.
    """
    try:
        frame = _object(value, _FRAME_KEYS)
        if frame["schema"] != FRAME_SCHEMA:
            raise _fail()
        profile = _object(frame["profile"], frozenset({"catalogue_version", "id", "version"}))
        if (profile["id"], profile["version"], profile["catalogue_version"]) != (
            PROFILE_ID,
            PROFILE_VERSION,
            CATALOGUE_VERSION,
        ) or type(profile["version"]) is not int:
            raise _fail()
        counts = frame["issue_counts"]
        if not isinstance(counts, dict):
            raise _fail()
        project = frame["project"]
        return P6ParseResult(
            profile_id=PROFILE_ID,
            profile_version=PROFILE_VERSION,
            catalogue_version=CATALOGUE_VERSION,
            outcome=_closed(P6Outcome, frame["outcome"]),
            header=_header(frame["header"]),
            issues=tuple(_issue(item) for item in _list(frame["issues"])),
            issue_counts=tuple((_str(code), _int(count)) for code, count in counts.items()),
            tables=tuple(_table(item) for item in _list(frame["tables"])),
            observed_fields=tuple(_observed(item) for item in _list(frame["observed_fields"])),
            project=None if project is None else _entity(EntityKind.PROJECT, project),
            wbs=tuple(_entity(EntityKind.WBS, item) for item in _list(frame["wbs"])),
            activities=tuple(
                _entity(EntityKind.ACTIVITY, item) for item in _list(frame["activities"])
            ),
            relationships=tuple(
                _entity(EntityKind.RELATIONSHIP, item) for item in _list(frame["relationships"])
            ),
            calendars=tuple(_calendar(item) for item in _list(frame["calendars"])),
            field_values=tuple(_field_value(item) for item in _list(frame["field_values"])),
            captured_keys=_labels(frame["captured_keys"]),
        )
    except P6FrameDecodeError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _fail() from None
