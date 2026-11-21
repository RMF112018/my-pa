"""Bounded, content-free diagnostics for communications evidence.

A diagnostic is a stable code, a field path, an optional record ordinal, and an
optional detail of named integers or closed-vocabulary members. It can never
carry input text: the path is chosen by the parser from its own constant field
names (never an input key), and `detail` values are `int` or `StrEnum` members.
Subjects, bodies, addresses, names, provider ids, internet message ids and
arbitrary input strings therefore have no way into a diagnostic.

A publication keeps at most `MAX_DIAGNOSTICS` entries; further ones are counted
in `overflow`, and `code_counts` counts every diagnostic, retained or not.

Three closed vocabularies share this record:

* `PublicationRejection` -- the publication as a whole is refused;
* `ReasonCode` -- why one record was quarantined or degraded;
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
    "QUARANTINE_REASONS",
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
    INVALID_WINDOW = "invalid_window"
    FILE_UNREADABLE = "file_unreadable"
    # The aggregate CLI's last resort: parsing this file raised unexpectedly.
    # Content-free by construction: no exception type, message or input.
    INTERNAL_ERROR = "internal_error"


class ReasonCode(StrEnum):
    # Quarantine: the record is not usable.
    RECORD_NOT_AN_OBJECT = "record_not_an_object"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    INVALID_FIELD_TYPE = "invalid_field_type"
    INVALID_FIELD_VALUE = "invalid_field_value"
    UNPARSEABLE_TIMESTAMP = "unparseable_timestamp"
    BODY_CONTENT_MISSING = "body_content_missing"
    INTEGRITY_MISMATCH = "integrity_mismatch"
    MAILBOX_REF_MISMATCH = "mailbox_ref_mismatch"
    PROVIDER_ID_FIELDS_DISAGREE = "provider_id_fields_disagree"
    IDENTITY_CONFLICT = "identity_conflict"
    PROVIDER_ID_CONFLICT = "provider_id_conflict"
    # Degradation: the record is usable with a stated weakness.
    IDENTITY_PROVIDER_ID_ONLY = "identity_provider_id_only"
    IDENTITY_STATE_INCONSISTENT = "identity_state_inconsistent"
    LANE_IDENTITY_INCONSISTENT = "lane_identity_inconsistent"
    CONVERSATION_ID_ABSENT = "conversation_id_absent"
    SELECTED_TIMESTAMP_INCONSISTENT = "selected_timestamp_inconsistent"
    RAW_TIMESTAMP_UNPARSEABLE = "raw_timestamp_unparseable"
    BODY_TRUNCATED = "body_truncated"
    UNKNOWN_BODY_COMPLETENESS = "unknown_body_completeness"
    PARTICIPANT_FROM_ABSENT = "participant_from_absent"
    PARTICIPANT_ENTRY_INVALID = "participant_entry_invalid"
    UNKNOWN_PARTICIPANT_STATE = "unknown_participant_state"
    UNKNOWN_FOLDER_ROLE = "unknown_folder_role"
    UNKNOWN_ID_FORMAT = "unknown_id_format"
    IN_WINDOW_DISAGREEMENT = "in_window_disagreement"
    FETCH_ERROR_REPORTED = "fetch_error_reported"
    PRIVACY_WITHHELD_CONTENT_PRESENT = "privacy_withheld_content_present"
    DERIVED_TEXT_INVALID = "derived_text_invalid"
    SUBJECT_EMPTY = "subject_empty"


#: Reasons that quarantine a record; every other `ReasonCode` only degrades it.
QUARANTINE_REASONS: Final = frozenset(
    {
        ReasonCode.RECORD_NOT_AN_OBJECT,
        ReasonCode.MISSING_REQUIRED_FIELD,
        ReasonCode.INVALID_FIELD_TYPE,
        ReasonCode.INVALID_FIELD_VALUE,
        ReasonCode.UNPARSEABLE_TIMESTAMP,
        ReasonCode.BODY_CONTENT_MISSING,
        ReasonCode.INTEGRITY_MISMATCH,
        ReasonCode.MAILBOX_REF_MISMATCH,
        ReasonCode.PROVIDER_ID_FIELDS_DISAGREE,
        ReasonCode.IDENTITY_CONFLICT,
        ReasonCode.PROVIDER_ID_CONFLICT,
    }
)


class DiagnosticCode(StrEnum):
    SCHEMA_MINOR_NEWER = "schema_minor_newer"
    DIALECT_MARKERS_INCOMPLETE = "dialect_markers_incomplete"
    UNKNOWN_TOP_LEVEL_KEYS = "unknown_top_level_keys"
    UNKNOWN_RECORD_KEYS = "unknown_record_keys"
    WINDOW_HOURS_MISMATCH = "window_hours_mismatch"
    WINDOW_FIELD_INVALID = "window_field_invalid"
    DST_FLAG_DISAGREEMENT = "dst_flag_disagreement"
    TZ_UNRESOLVABLE = "tz_unresolvable"
    COVERAGE_INVALID = "coverage_invalid"
    COVERAGE_SOURCE_INVALID = "coverage_source_invalid"
    COVERAGE_COUNT_MISMATCH = "coverage_count_mismatch"
    DUPLICATE_PROVIDER_ID = "duplicate_provider_id"
    MULTI_LANE_ITEM = "multi_lane_item"
    WINDOW_RULE_UNRECOGNIZED = "window_rule_unrecognized"
    OUT_OF_WINDOW = "out_of_window"


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
