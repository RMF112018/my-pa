"""Typed reading of one XER value by its catalogue type (S7-1).

Contract `docs/architecture/schedule-xer-import-contract.md` sections 3.2
(control characters), 3.3 (value forms), 5.3 (enumerations) and 5.4 (number
and date forms). Nothing is coerced or repaired: a value either matches its
type exactly or is `invalid`. Pure, standard library only.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final

from my_pa.domain.schedule.p6.catalogue import CatalogueField, ValueType
from my_pa.domain.schedule.p6.model import P6Value

__all__ = [
    "ENUM_TOKEN",
    "Reading",
    "ReadingStatus",
    "has_forbidden_control",
    "read_text",
    "read_value",
    "value_shape",
]

_ID: Final = re.compile(r"^[0-9]{1,18}$")
_INT: Final = re.compile(r"^-?[0-9]{1,15}$")
#: Section 5.4 numbers.
_NUMBER: Final = re.compile(r"^-?[0-9]{1,15}(\.[0-9]{1,6})?$")
#: Section 5.4 dates: `YYYY-MM-DD HH:MM` with seconds tolerated only as zero seconds.
_TIMESTAMP: Final = re.compile(
    r"^([0-9]{4})-([0-9]{2})-([0-9]{2}) ([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?$"
)
#: Section 5.3: a stored enumeration token.
ENUM_TOKEN: Final = re.compile(r"^[A-Za-z0-9_]{1,64}$")
#: Section 3.2: a C0 control other than tab (a bare CR included), or DEL outside `clndr_data`.
_CONTROL: Final = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")
_CONTROL_IN_CALENDAR: Final = re.compile(r"[\x00-\x08\x0a-\x1f]")
_FIRST_YEAR: Final = 1900
_LAST_YEAR: Final = 2199

_SHAPE_INTEGER: Final = re.compile(r"^-?[0-9]+$")
_SHAPE_DECIMAL: Final = re.compile(r"^-?[0-9]+\.[0-9]+$")
_SHAPE_DATE: Final = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}( [0-9]{2}:[0-9]{2}(:[0-9]{2})?)?$")
_SHAPE_TOKEN: Final = re.compile(r"^[A-Za-z]{1,8}_[A-Za-z0-9_]{1,40}$")


class ReadingStatus(StrEnum):
    OK = "ok"
    EMPTY = "empty"
    INVALID = "invalid"
    UNKNOWN_ENUM = "unknown_enum"


@dataclass(frozen=True, slots=True)
class Reading:
    status: ReadingStatus
    value: P6Value = None


_EMPTY: Final = Reading(ReadingStatus.EMPTY)
_INVALID: Final = Reading(ReadingStatus.INVALID)


def has_forbidden_control(raw: str, *, calendar_data: bool = False) -> bool:
    pattern = _CONTROL_IN_CALENDAR if calendar_data else _CONTROL
    return pattern.search(raw) is not None


def read_text(raw: str, max_characters: int) -> Reading:
    """NFC text of at most `max_characters` (sections 6.2 `name`, 7.7 `value_text`)."""
    if raw == "":
        return _EMPTY
    if has_forbidden_control(raw):
        return _INVALID
    text = unicodedata.normalize("NFC", raw)
    if len(text) > max_characters:
        return _INVALID
    return Reading(ReadingStatus.OK, text)


def _timestamp(raw: str) -> datetime | None:
    match = _TIMESTAMP.match(raw)
    if match is None:
        return None
    year, month, day, hour, minute = (int(match.group(index)) for index in range(1, 6))
    seconds = match.group(6)
    if seconds is not None and seconds != "00":
        return None
    if not _FIRST_YEAR <= year <= _LAST_YEAR:
        return None
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def read_value(field: CatalogueField, raw: str) -> Reading:
    """Read `raw` as `field`'s type; empty is `EMPTY` whatever the tier."""
    if raw == "":
        return _EMPTY
    value_type = field.value_type
    if has_forbidden_control(raw, calendar_data=value_type is ValueType.BLOB):
        return _INVALID
    if value_type is ValueType.ID:
        return Reading(ReadingStatus.OK, int(raw)) if _ID.match(raw) else _INVALID
    if value_type is ValueType.INT:
        return Reading(ReadingStatus.OK, int(raw)) if _INT.match(raw) else _INVALID
    if value_type in {ValueType.HOURS, ValueType.NUM}:
        return Reading(ReadingStatus.OK, Decimal(raw)) if _NUMBER.match(raw) else _INVALID
    if value_type is ValueType.FLAG:
        return Reading(ReadingStatus.OK, raw == "Y") if raw in {"Y", "N"} else _INVALID
    if value_type is ValueType.TS:
        stamp = _timestamp(raw)
        return _INVALID if stamp is None else Reading(ReadingStatus.OK, stamp)
    if value_type is ValueType.ENUM:
        if not ENUM_TOKEN.match(raw):
            return _INVALID
        if field.enum_values is not None and raw not in field.enum_values:
            return Reading(ReadingStatus.UNKNOWN_ENUM, raw)
        return Reading(ReadingStatus.OK, raw)
    if value_type is ValueType.BLOB:
        return Reading(ReadingStatus.OK, raw)
    limit = field.max_characters
    if limit is None:
        raise ValueError(f"text field {field.field_key} has no bound")
    return read_text(raw, limit)


def value_shape(raw: str) -> str:
    """Section 7.4 shape of a non-empty value: integer, decimal, date, flag, token or text."""
    if _SHAPE_INTEGER.match(raw):
        return "integer"
    if _SHAPE_DECIMAL.match(raw):
        return "decimal"
    if _SHAPE_DATE.match(raw):
        return "date"
    if raw in {"Y", "N"}:
        return "flag"
    if _SHAPE_TOKEN.match(raw):
        return "token"
    return "text"
