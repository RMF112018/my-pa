"""Bounded, content-free diagnostics for `meeting_sync_v1` publications.

A diagnostic is a stable code, a field path chosen by the parser from its own
constant field names (never an input key), an optional record ordinal, and an
optional detail of named integers or closed-vocabulary members. It can never
carry input text: titles, locations, links, addresses, names, calendar
references, UIDs and provider event ids have no way into a diagnostic.

A publication keeps at most `MAX_DIAGNOSTICS` entries; further ones are counted
in `overflow`, and `code_counts` counts every diagnostic, retained or not. The
collector is a deliberate small copy of the communications one rather than a
shared import: the two source slices stay independent (contract section 0).

Three closed vocabularies share this record:

* `PublicationRejection` -- the publication as a whole is refused;
* `ReasonCode` -- why one event record was quarantined (every reason quarantines:
  WP2 has no degraded-but-usable event);
* `DiagnosticCode` -- informational findings that change no outcome.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

__all__ = [
    "MAX_DIAGNOSTICS",
    "Diagnostic",
    "DiagnosticCode",
    "DiagnosticCollector",
    "Diagnostics",
    "PublicationRejection",
    "ReasonCode",
]

MAX_DIAGNOSTICS: Final = 200


class PublicationRejection(StrEnum):
    FILE_TOO_LARGE = "file_too_large"
    INVALID_ENCODING = "invalid_encoding"
    MALFORMED_JSON = "malformed_json"
    DUPLICATE_JSON_KEY = "duplicate_json_key"
    NOT_AN_OBJECT = "not_an_object"
    UNKNOWN_SCHEMA = "unknown_schema"
    INVALID_SCHEMA_VERSION = "invalid_schema_version"
    UNSUPPORTED_MAJOR_VERSION = "unsupported_major_version"
    MISSING_REQUIRED_KEY = "missing_required_key"
    INVALID_TOP_LEVEL_FIELD = "invalid_top_level_field"


class ReasonCode(StrEnum):
    """Why one event record is quarantined. Every member quarantines (D3/D4).

    Nothing is truncated or coerced to fit: a value the Meeting plane cannot
    store exactly is refused under the code that names its field.
    """

    # Structural: the record cannot be read.
    RECORD_NOT_AN_OBJECT = "record_not_an_object"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    INVALID_FIELD_TYPE = "invalid_field_type"
    INVALID_FIELD_VALUE = "invalid_field_value"
    UNPARSEABLE_TIMESTAMP = "unparseable_timestamp"
    # Representability: the record reads, but the Meeting plane cannot hold it.
    IDENTIFIER_UNREPRESENTABLE = "identifier_unrepresentable"
    TITLE_UNREPRESENTABLE = "title_unrepresentable"
    TIMEZONE_NOT_IANA = "timezone_not_iana"
    URL_UNREPRESENTABLE = "url_unrepresentable"
    LOCATION_UNREPRESENTABLE = "location_unrepresentable"
    ATTENDEES_UNREPRESENTABLE = "attendees_unrepresentable"
    ALL_DAY_UNSUPPORTED = "all_day_unsupported"
    SERIES_KEY_INCOMPLETE = "series_key_incomplete"
    END_BEFORE_START = "end_before_start"
    # Within one publication: two records claim the same occurrence key, so
    # neither is trusted (the communications `provider_id_conflict` precedent).
    DUPLICATE_OCCURRENCE_KEY = "duplicate_occurrence_key"


class DiagnosticCode(StrEnum):
    SCHEMA_MINOR_NEWER = "schema_minor_newer"
    UNKNOWN_TOP_LEVEL_KEYS = "unknown_top_level_keys"
    UNKNOWN_RECORD_KEYS = "unknown_record_keys"
    #: A record carried a body or description key. It is never read: WP2
    #: admits no event bodies (Manager ruling D1).
    CONTENT_FIELD_IGNORED = "content_field_ignored"


type Code = PublicationRejection | ReasonCode | DiagnosticCode
type DetailValue = int | StrEnum


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: Code
    path: str
    ordinal: int | None = None
    detail: tuple[tuple[str, DetailValue], ...] = ()


@dataclass(frozen=True, slots=True)
class Diagnostics:
    entries: tuple[Diagnostic, ...]
    overflow: int
    code_counts: Mapping[str, int]


class DiagnosticCollector:
    """Accumulates diagnostics for one publication, retaining at most `limit`."""

    def __init__(self, limit: int = MAX_DIAGNOSTICS) -> None:
        self._limit = limit
        self._entries: list[Diagnostic] = []
        self._overflow = 0
        self._counts: Counter[str] = Counter()

    def add(
        self,
        code: Code,
        path: str,
        ordinal: int | None = None,
        **detail: DetailValue,
    ) -> None:
        for value in detail.values():
            # Booleans are ints; anything else (a str that is not an enum member)
            # is exactly what this record exists to keep out.
            if not isinstance(value, int | StrEnum):
                raise TypeError("diagnostic detail must be an int or a closed-vocabulary member")
        self._counts[str(code)] += 1
        if len(self._entries) >= self._limit:
            self._overflow += 1
            return
        self._entries.append(Diagnostic(code, path, ordinal, tuple(sorted(detail.items()))))

    def freeze(self) -> Diagnostics:
        return Diagnostics(
            tuple(self._entries),
            self._overflow,
            MappingProxyType(dict(sorted(self._counts.items()))),
        )
