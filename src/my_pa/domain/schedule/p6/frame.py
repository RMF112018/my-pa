"""Canonical frame `cpm-workbench-p6-frame-v1` of a P6 XER parse (S7-1).

Contract `docs/architecture/schedule-xer-import-contract.md` section 9.3 (the
contained child writes one canonical frame) and acceptance A6 (same bytes,
identical frame bytes across runs and hosts). The frame is canonical JSON:
sorted keys, compact separators, ASCII only, no float anywhere. Numbers that
are not integers are fixed decimal strings, timestamps `YYYY-MM-DDTHH:MM`,
days `YYYY-MM-DD`. Every list is in a defined order (file order, or sorted).
The digest is SHA-256 over a domain-separated prefix and the bytes. Pure,
standard library only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Final

from my_pa.domain.schedule.p6.model import (
    P6Calendar,
    P6Entity,
    P6FieldValue,
    P6Issue,
    P6ObservedField,
    P6ObservedTable,
    P6ParseResult,
    P6Value,
)

__all__ = ["FRAME_SCHEMA", "frame_bytes", "frame_object", "frame_sha256", "render_decimal"]

FRAME_SCHEMA: Final = "cpm-workbench-p6-frame-v1"
_DOMAIN: Final = FRAME_SCHEMA.encode("ascii") + b"\n"

type _Json = bool | int | str | list[_Json] | dict[str, _Json] | None


def render_decimal(value: Decimal) -> str:
    """Fixed decimal text without exponent or trailing zeros; `-0` is `0`."""
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def _value(value: P6Value | tuple[str, ...]) -> _Json:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, Decimal):
        return render_decimal(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return list(value)


def _issue(issue: P6Issue) -> _Json:
    return {
        "bound": None if issue.bound is None else issue.bound.value,
        "code": issue.code.value,
        "field": issue.field,
        "line": issue.line,
        "severity": issue.severity.value,
        "table": issue.table,
    }


def _table(table: P6ObservedTable) -> _Json:
    return {
        "catalogued": table.catalogued,
        "line": table.line,
        "name": table.name,
        "position": table.position,
        "records": table.records,
    }


def _field(field: P6ObservedField) -> _Json:
    return {
        "captured": field.captured,
        "catalogued": field.catalogued,
        "field": field.field,
        "field_key": field.field_key,
        "max_length": field.max_length,
        "min_length": field.min_length,
        "nonempty": field.nonempty,
        "over_length": field.over_length,
        "position": field.position,
        "records": field.records,
        "shapes": dict(field.shapes),
        "table": field.table,
        "table_position": field.table_position,
        "tier": field.tier,
        "unknown_enum": field.unknown_enum,
        "unknown_enum_tokens": list(field.unknown_enum_tokens),
    }


def _entity(entity: P6Entity) -> _Json:
    return {
        "columns": {name: _value(value) for name, value in entity.columns},
        "p6_id": entity.p6_id,
        "record_line": entity.record_line,
    }


def _intervals(intervals: tuple[tuple[int, int], ...]) -> _Json:
    return [[start, end] for start, end in intervals]


def _calendar(calendar: P6Calendar) -> _Json:
    return {
        "columns": {name: _value(value) for name, value in calendar.columns},
        "data_sha256": calendar.data_sha256,
        "exception_count": len(calendar.exceptions),
        "exceptions": [
            {"date": day.isoformat(), "intervals": _intervals(intervals)}
            for day, intervals in calendar.exceptions
        ],
        "p6_id": calendar.p6_id,
        "record_line": calendar.record_line,
        "status": calendar.status.value,
        "used": calendar.used,
        "week": [_intervals(day) for day in calendar.week],
    }


def _field_value(value: P6FieldValue) -> _Json:
    return {
        "activity_id": value.activity_id,
        "code_path": list(value.code_path),
        "description": value.description,
        "entity_kind": value.entity_kind.value,
        "entity_p6_id": value.entity_p6_id,
        "field_key": value.field_key,
        "ordinal": value.ordinal,
        "record_line": value.record_line,
        "source_table": value.source_table,
        "value": _value(value.value),
        "value_type": value.value_type,
    }


def frame_object(result: P6ParseResult) -> dict[str, _Json]:
    """The frame as plain JSON-ready data."""
    header = result.header
    return {
        "activities": [_entity(entity) for entity in result.activities],
        "calendars": [_calendar(calendar) for calendar in result.calendars],
        "captured_keys": list(result.captured_keys),
        "counts": {
            "activities": len(result.activities),
            "calendars": len(result.calendars),
            "field_values": len(result.field_values),
            "relationships": len(result.relationships),
            "tables": len(result.tables),
            "wbs": len(result.wbs),
        },
        "field_values": [_field_value(value) for value in result.field_values],
        "header": None
        if header is None
        else {
            "encoding": header.encoding,
            "export_date": None if header.export_date is None else header.export_date.isoformat(),
            "export_version": header.export_version,
        },
        "issue_counts": dict(result.issue_counts),
        "issues": [_issue(issue) for issue in result.issues],
        "observed_fields": [_field(field) for field in result.observed_fields],
        "outcome": result.outcome.value,
        "profile": {
            "catalogue_version": result.catalogue_version,
            "id": result.profile_id,
            "version": result.profile_version,
        },
        "project": None if result.project is None else _entity(result.project),
        "relationships": [_entity(entity) for entity in result.relationships],
        "schema": FRAME_SCHEMA,
        "tables": [_table(table) for table in result.tables],
        "wbs": [_entity(entity) for entity in result.wbs],
    }


def frame_bytes(result: P6ParseResult) -> bytes:
    """Canonical JSON bytes of the frame (sorted keys, compact, ASCII, no NaN)."""
    return json.dumps(
        frame_object(result),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def frame_sha256(result: P6ParseResult) -> str:
    """Lowercase hex SHA-256 of `FRAME_SCHEMA + "\\n"` and the frame bytes."""
    return hashlib.sha256(_DOMAIN + frame_bytes(result)).hexdigest()
