"""The `meeting_sync_v1` source-contract parser (WP2, Manager ruling D1; v2 WP3b, D7).

`parse_publication(data)` turns the bytes of one publication into a
`PublicationParse`: either `accepted` with a domain `MeetingSyncPublication`, or
`rejected` with one `PublicationRejection` code. Rejection is reserved for the
envelope; **one bad event never rejects a publication** -- it is quarantined
with closed reason codes that never echo content.

Publication validation, in order (the first failure decides), mirroring
`communications_evidence_v2`:

1. size <= `MAX_PUBLICATION_BYTES`; strict UTF-8; JSON with no duplicate object
   key and no `NaN`/`Infinity` (`malformed_json` carries line/column/offset only);
2. a JSON object whose `schema` is `meeting_sync_v1`;
3. `schema_version` is `MAJOR.MINOR.PATCH`; major `1` only
   (`unsupported_major_version`); `1.0.x` and `1.1.x` are known; a newer minor
   is accepted and reported (`schema_minor_newer`);
4. required keys `schema`, `schema_version`, `events`; `events` a list;
5. required `generated_at_utc`, an aware timestamp (`missing_required_key` when
   absent, `invalid_top_level_field` when not a timestamp): the publication's
   ordering stamp, carried onto every accepted event so a re-application of an
   older publication can never rewind a bound Meeting (WP2-F1);
6. optional `cycle_run_id` (a non-empty string);
7. from minor `1` (contract 1.1.0), optional `coverage` `{start_utc, end_utc,
   calendar_refs}`: the publication is complete for those calendars over the
   inclusive window. All-or-none; both stamps UTC with `start_utc <= end_utc`;
   `calendar_refs` 1..100 distinct calendar references within the binding
   bound. A malformed coverage rejects the publication (`invalid_coverage`,
   its `CoverageDefect` in the diagnostic detail): a completeness claim is
   never half-read. In a `1.0.x` publication `coverage` is an unknown
   top-level key, ignored and counted, as parser v1 treated it.

Parser v2 (`meeting_sync_v1_parser_v2`) gives every `1.0.x` publication exactly
the outcome parser v1 gave it.

An event record carries `calendar_ref`, `ical_uid`, `series_ical_uid` and
`occurrence_original_start_utc` (both null for a single meeting), `start_utc`,
`end_utc`, `timezone_name` (IANA), `status` (`confirmed`, `tentative`,
`cancelled`), `all_day`, `provider_event_id` and `provider_event_id_format`
(`immutable_verified`, `mutable`, `unknown`), `title`, `location_text`,
`virtual_meeting_url` and `attendees` (address, display name, organizer flag,
response status). No body or description is read: such a key is reported as
`content_field_ignored` and dropped. Unknown keys are counted, never fatal.

A record that cannot be read is quarantined with a structural reason; a record
that reads but that the Meeting plane cannot hold exactly is quarantined with a
representability reason (`model.representability_reasons`). Two records with
one occurrence key are both quarantined (`duplicate_occurrence_key`).

The parser is pure (bytes in, values out) apart from reading the installed
time-zone database to confirm a zone is an IANA name.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import cache
from typing import Final
from zoneinfo import available_timezones

from my_pa.domain.meeting_sync.diagnostics import (
    CoverageDefect,
    DiagnosticCode,
    DiagnosticCollector,
    Diagnostics,
    PublicationRejection,
    ReasonCode,
)
from my_pa.domain.meeting_sync.model import (
    COVERAGE_MINOR,
    MAX_CALENDAR_REF_CHARACTERS,
    MAX_COVERAGE_CALENDAR_REFS,
    SCHEMA_NAME,
    SUPPORTED_MAJOR,
    SUPPORTED_MINOR,
    EventStatus,
    MeetingSyncEvent,
    MeetingSyncPublication,
    OccurrenceKey,
    ProviderEventIdFormat,
    PublicationCoverage,
    QuarantinedEvent,
    SchemaVersion,
    normalized_attendees,
    representability_reasons,
)

__all__ = [
    "MAX_PUBLICATION_BYTES",
    "PARSER_VERSION",
    "PublicationParse",
    "PublicationStatus",
    "parse_publication",
]

PARSER_VERSION: Final = "meeting_sync_v1_parser_v2"
MAX_PUBLICATION_BYTES: Final = 16 * 1024 * 1024

REQUIRED_TOP_LEVEL: Final = ("schema", "schema_version", "events", "generated_at_utc")
OPTIONAL_TOP_LEVEL: Final = frozenset({"cycle_run_id"})
KNOWN_TOP_LEVEL: Final = frozenset(REQUIRED_TOP_LEVEL) | OPTIONAL_TOP_LEVEL
#: Known from minor `COVERAGE_MINOR` (contract 1.1.0).
COVERAGE_KEY: Final = "coverage"
COVERAGE_KEYS: Final = frozenset({"start_utc", "end_utc", "calendar_refs"})

REQUIRED_RECORD_KEYS: Final = (
    "calendar_ref",
    "ical_uid",
    "start_utc",
    "end_utc",
    "timezone_name",
    "status",
    "all_day",
    "title",
)
OPTIONAL_RECORD_KEYS: Final = frozenset(
    {
        "series_ical_uid",
        "occurrence_original_start_utc",
        "provider_event_id",
        "provider_event_id_format",
        "location_text",
        "virtual_meeting_url",
        "attendees",
    }
)
#: Keys that would carry an event body. Never read (Manager ruling D1).
CONTENT_RECORD_KEYS: Final = frozenset({"body", "body_preview", "description", "notes"})
KNOWN_RECORD_KEYS: Final = frozenset(REQUIRED_RECORD_KEYS) | OPTIONAL_RECORD_KEYS

_SEMVER: Final = re.compile(r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})")
_ISO_TIMESTAMP: Final = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)
# Every accepted timestamp is at least a day inside the `datetime` range.
_MIN_UTC: Final = datetime.min.replace(tzinfo=UTC) + timedelta(days=1)
_MAX_UTC: Final = datetime.max.replace(tzinfo=UTC) - timedelta(days=1)

_STATUSES: Final = {status.value: status for status in EventStatus}
_ID_FORMATS: Final = {member.value: member for member in ProviderEventIdFormat}


class PublicationStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class PublicationParse:
    status: PublicationStatus
    rejection: PublicationRejection | None
    publication: MeetingSyncPublication | None
    diagnostics: Diagnostics


class _RejectedError(Exception):
    def __init__(self, code: PublicationRejection) -> None:
        super().__init__(code.value)
        self.code = code


class _DuplicateKeyError(ValueError):
    pass


def _reject_constant(_: str) -> object:
    raise ValueError("non-finite number")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


@cache
def _iana_zones() -> frozenset[str]:
    return frozenset(available_timezones())


def _parse_utc(value: object) -> datetime | None:
    """An aware ISO-8601 timestamp as UTC, else `None`."""
    if not isinstance(value, str) or _ISO_TIMESTAMP.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value).astimezone(UTC)
    except (OverflowError, ValueError):
        return None
    if not _MIN_UTC <= parsed <= _MAX_UTC:
        return None
    return parsed


def parse_publication(data: bytes) -> PublicationParse:
    """Parse and validate one publication (module docstring for the rules)."""
    diagnostics = DiagnosticCollector()
    try:
        publication = _parse(data, diagnostics)
    except _RejectedError as rejected:
        return PublicationParse(
            PublicationStatus.REJECTED, rejected.code, None, diagnostics.freeze()
        )
    return PublicationParse(PublicationStatus.ACCEPTED, None, publication, diagnostics.freeze())


def _decode(data: bytes, diagnostics: DiagnosticCollector) -> object:
    if len(data) > MAX_PUBLICATION_BYTES:
        diagnostics.add(PublicationRejection.FILE_TOO_LARGE, "$", size=len(data))
        raise _RejectedError(PublicationRejection.FILE_TOO_LARGE)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        diagnostics.add(PublicationRejection.INVALID_ENCODING, "$", offset=error.start)
        raise _RejectedError(PublicationRejection.INVALID_ENCODING) from None
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except _DuplicateKeyError:
        diagnostics.add(PublicationRejection.DUPLICATE_JSON_KEY, "$")
        raise _RejectedError(PublicationRejection.DUPLICATE_JSON_KEY) from None
    except json.JSONDecodeError as error:
        # Line, column and offset only: no document text reaches a diagnostic.
        diagnostics.add(
            PublicationRejection.MALFORMED_JSON,
            "$",
            line=error.lineno,
            column=error.colno,
            offset=error.pos,
        )
        raise _RejectedError(PublicationRejection.MALFORMED_JSON) from None
    except (ValueError, RecursionError):
        diagnostics.add(PublicationRejection.MALFORMED_JSON, "$")
        raise _RejectedError(PublicationRejection.MALFORMED_JSON) from None


def _reject(
    diagnostics: DiagnosticCollector, code: PublicationRejection, path: str
) -> _RejectedError:
    diagnostics.add(code, path)
    return _RejectedError(code)


def _schema_version(document: Mapping[str, object], d: DiagnosticCollector) -> SchemaVersion:
    raw = document.get("schema_version")
    match = _SEMVER.fullmatch(raw) if isinstance(raw, str) else None
    if match is None:
        raise _reject(d, PublicationRejection.INVALID_SCHEMA_VERSION, "schema_version")
    version = SchemaVersion(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    if version.major != SUPPORTED_MAJOR:
        d.add(PublicationRejection.UNSUPPORTED_MAJOR_VERSION, "schema_version", major=version.major)
        raise _RejectedError(PublicationRejection.UNSUPPORTED_MAJOR_VERSION)
    if version.minor > SUPPORTED_MINOR:
        d.add(DiagnosticCode.SCHEMA_MINOR_NEWER, "schema_version", minor=version.minor)
    return version


def _parse(data: bytes, d: DiagnosticCollector) -> MeetingSyncPublication:
    document = _decode(data, d)
    if not isinstance(document, dict):
        raise _reject(d, PublicationRejection.NOT_AN_OBJECT, "$")
    if "schema" not in document:
        raise _reject(d, PublicationRejection.MISSING_REQUIRED_KEY, "schema")
    if document["schema"] != SCHEMA_NAME:
        raise _reject(d, PublicationRejection.UNKNOWN_SCHEMA, "schema")
    if "schema_version" not in document:
        raise _reject(d, PublicationRejection.MISSING_REQUIRED_KEY, "schema_version")
    version = _schema_version(document, d)
    if "events" not in document:
        raise _reject(d, PublicationRejection.MISSING_REQUIRED_KEY, "events")
    events = document["events"]
    if not isinstance(events, list):
        raise _reject(d, PublicationRejection.INVALID_TOP_LEVEL_FIELD, "events")
    if "generated_at_utc" not in document:
        raise _reject(d, PublicationRejection.MISSING_REQUIRED_KEY, "generated_at_utc")
    generated_at_utc = _parse_utc(document["generated_at_utc"])
    if generated_at_utc is None:
        raise _reject(d, PublicationRejection.INVALID_TOP_LEVEL_FIELD, "generated_at_utc")
    if "cycle_run_id" in document:
        run_id = document["cycle_run_id"]
        if not isinstance(run_id, str) or not run_id.strip():
            raise _reject(d, PublicationRejection.INVALID_TOP_LEVEL_FIELD, "cycle_run_id")
    known = KNOWN_TOP_LEVEL
    coverage: PublicationCoverage | None = None
    if version.minor >= COVERAGE_MINOR:
        known = known | {COVERAGE_KEY}
        if COVERAGE_KEY in document:
            coverage = _coverage(document[COVERAGE_KEY], d)
    unknown = sum(1 for key in document if key not in known)
    if unknown:
        d.add(DiagnosticCode.UNKNOWN_TOP_LEVEL_KEYS, "$", count=unknown)

    accepted: list[MeetingSyncEvent] = []
    quarantined: list[QuarantinedEvent] = []
    for ordinal, record in enumerate(events):
        parsed = _parse_record(ordinal, record, generated_at_utc, d)
        if isinstance(parsed, QuarantinedEvent):
            quarantined.append(parsed)
        else:
            accepted.append(parsed)

    keys = Counter(event.key for event in accepted)
    duplicated: set[OccurrenceKey] = {key for key, count in keys.items() if count > 1}
    kept: list[MeetingSyncEvent] = []
    for event in accepted:
        if event.key in duplicated:
            d.add(ReasonCode.DUPLICATE_OCCURRENCE_KEY, "events", event.ordinal)
            quarantined.append(
                QuarantinedEvent(event.ordinal, (ReasonCode.DUPLICATE_OCCURRENCE_KEY,))
            )
        else:
            kept.append(event)
    return MeetingSyncPublication(
        schema_version=version,
        generated_at_utc=generated_at_utc,
        record_count=len(events),
        events=tuple(kept),
        quarantined=tuple(sorted(quarantined, key=lambda entry: entry.ordinal)),
        coverage=coverage,
    )


def _utc_stamp(value: object) -> datetime | CoverageDefect:
    """A coverage stamp: a valid timestamp (`_parse_utc`) written in UTC."""
    parsed = _parse_utc(value)
    if parsed is None:
        return CoverageDefect.INVALID_TIMESTAMP
    assert isinstance(value, str)  # noqa: S101 - `_parse_utc` accepts strings only
    if not value.endswith(("Z", "+00:00")):
        return CoverageDefect.NOT_UTC
    return parsed


def _coverage_defect(raw: object) -> PublicationCoverage | CoverageDefect:
    if not isinstance(raw, dict):
        return CoverageDefect.NOT_AN_OBJECT
    if not raw.keys() >= COVERAGE_KEYS:
        return CoverageDefect.INCOMPLETE
    if raw.keys() != COVERAGE_KEYS:
        return CoverageDefect.UNKNOWN_KEY
    start = _utc_stamp(raw["start_utc"])
    if isinstance(start, CoverageDefect):
        return start
    end = _utc_stamp(raw["end_utc"])
    if isinstance(end, CoverageDefect):
        return end
    if end < start:
        return CoverageDefect.END_BEFORE_START
    refs = raw["calendar_refs"]
    if not isinstance(refs, list):
        return CoverageDefect.CALENDAR_REFS_NOT_A_LIST
    if not refs:
        return CoverageDefect.CALENDAR_REFS_EMPTY
    if len(refs) > MAX_COVERAGE_CALENDAR_REFS:
        return CoverageDefect.CALENDAR_REFS_TOO_MANY
    for ref in refs:
        if (
            not isinstance(ref, str)
            or not 1 <= len(ref) <= MAX_CALENDAR_REF_CHARACTERS
            or not ref.strip()
        ):
            return CoverageDefect.CALENDAR_REF_UNREPRESENTABLE
    if len(set(refs)) != len(refs):
        return CoverageDefect.DUPLICATE_CALENDAR_REF
    return PublicationCoverage(start_utc=start, end_utc=end, calendar_refs=tuple(sorted(refs)))


def _coverage(raw: object, d: DiagnosticCollector) -> PublicationCoverage:
    """The declared coverage, or the publication's `invalid_coverage` rejection."""
    checked = _coverage_defect(raw)
    if isinstance(checked, CoverageDefect):
        d.add(PublicationRejection.INVALID_COVERAGE, COVERAGE_KEY, defect=checked)
        raise _RejectedError(PublicationRejection.INVALID_COVERAGE)
    return checked


def _quarantine(ordinal: int, reasons: set[ReasonCode], d: DiagnosticCollector) -> QuarantinedEvent:
    ordered = tuple(sorted(reasons, key=lambda member: member.value))
    for reason in ordered:
        d.add(reason, "events", ordinal)
    return QuarantinedEvent(ordinal, ordered)


def _parse_record(
    ordinal: int, record: object, generated_at_utc: datetime, d: DiagnosticCollector
) -> MeetingSyncEvent | QuarantinedEvent:
    if not isinstance(record, dict):
        return _quarantine(ordinal, {ReasonCode.RECORD_NOT_AN_OBJECT}, d)
    content = sum(1 for key in record if key in CONTENT_RECORD_KEYS)
    if content:
        d.add(DiagnosticCode.CONTENT_FIELD_IGNORED, "events", ordinal, count=content)
    unknown = sum(
        1 for key in record if key not in KNOWN_RECORD_KEYS and key not in CONTENT_RECORD_KEYS
    )
    if unknown:
        d.add(DiagnosticCode.UNKNOWN_RECORD_KEYS, "events", ordinal, count=unknown)

    reasons: set[ReasonCode] = set()
    if any(key not in record for key in REQUIRED_RECORD_KEYS):
        reasons.add(ReasonCode.MISSING_REQUIRED_FIELD)

    def text(key: str, *, nullable: bool) -> str | None:
        value = record.get(key)
        if value is None:
            if not nullable and key in record:
                reasons.add(ReasonCode.INVALID_FIELD_TYPE)
            return None
        if not isinstance(value, str):
            reasons.add(ReasonCode.INVALID_FIELD_TYPE)
            return None
        return value

    def instant(key: str) -> datetime | None:
        value = record.get(key)
        if value is None:
            if key in record and key in REQUIRED_RECORD_KEYS:
                reasons.add(ReasonCode.UNPARSEABLE_TIMESTAMP)
            return None
        parsed = _parse_utc(value)
        if parsed is None:
            reasons.add(ReasonCode.UNPARSEABLE_TIMESTAMP)
        return parsed

    calendar_ref = text("calendar_ref", nullable=False)
    ical_uid = text("ical_uid", nullable=False)
    series_ical_uid = text("series_ical_uid", nullable=True)
    original_start = instant("occurrence_original_start_utc")
    start_utc = instant("start_utc")
    end_utc = instant("end_utc")
    timezone_name = text("timezone_name", nullable=False)
    title = text("title", nullable=False)
    location_text = text("location_text", nullable=True)
    virtual_meeting_url = text("virtual_meeting_url", nullable=True)
    provider_event_id = text("provider_event_id", nullable=True)

    raw_status = record.get("status")
    status: EventStatus | None = None
    if isinstance(raw_status, str):
        status = _STATUSES.get(raw_status)
        if status is None:
            reasons.add(ReasonCode.INVALID_FIELD_VALUE)
    elif "status" in record:
        reasons.add(ReasonCode.INVALID_FIELD_TYPE)

    all_day = record.get("all_day")
    if "all_day" in record and not isinstance(all_day, bool):
        reasons.add(ReasonCode.INVALID_FIELD_TYPE)

    raw_format = record.get("provider_event_id_format", ProviderEventIdFormat.UNKNOWN.value)
    id_format: ProviderEventIdFormat | None = None
    if raw_format is None:
        id_format = ProviderEventIdFormat.UNKNOWN
    elif isinstance(raw_format, str):
        id_format = _ID_FORMATS.get(raw_format)
        if id_format is None:
            reasons.add(ReasonCode.INVALID_FIELD_VALUE)
    else:
        reasons.add(ReasonCode.INVALID_FIELD_TYPE)

    raw_attendees = record.get("attendees")
    attendee_objects: tuple[dict[str, object], ...] = ()
    attendees_shape_ok = True
    if raw_attendees is not None:
        if not isinstance(raw_attendees, list):
            reasons.add(ReasonCode.INVALID_FIELD_TYPE)
        elif all(isinstance(entry, dict) for entry in raw_attendees):
            attendee_objects = tuple(raw_attendees)
        else:
            attendees_shape_ok = False

    if reasons:
        return _quarantine(ordinal, reasons, d)
    # Every required field is present with its type; narrow for the checker.
    if (
        calendar_ref is None
        or ical_uid is None
        or start_utc is None
        or end_utc is None
        or timezone_name is None
        or title is None
        or status is None
        or id_format is None
        or not isinstance(all_day, bool)
    ):
        return _quarantine(ordinal, {ReasonCode.MISSING_REQUIRED_FIELD}, d)

    representable = set(
        representability_reasons(
            calendar_ref=calendar_ref,
            ical_uid=ical_uid,
            series_ical_uid=series_ical_uid,
            occurrence_original_start_utc=original_start,
            start_utc=start_utc,
            end_utc=end_utc,
            timezone_name=timezone_name,
            all_day=all_day,
            provider_event_id=provider_event_id,
            title=title,
            location_text=location_text,
            virtual_meeting_url=virtual_meeting_url,
            attendees=attendee_objects,
        )
    )
    if not attendees_shape_ok:
        representable.add(ReasonCode.ATTENDEES_UNREPRESENTABLE)
    if timezone_name not in _iana_zones():
        representable.add(ReasonCode.TIMEZONE_NOT_IANA)
    if representable:
        return _quarantine(ordinal, representable, d)
    attendees = normalized_attendees(attendee_objects) or ()
    return MeetingSyncEvent(
        ordinal=ordinal,
        calendar_ref=calendar_ref,
        ical_uid=ical_uid,
        series_ical_uid=series_ical_uid,
        occurrence_original_start_utc=original_start,
        start_utc=start_utc,
        end_utc=end_utc,
        timezone_name=timezone_name,
        status=status,
        provider_event_id=provider_event_id,
        provider_event_id_format=id_format,
        title=title,
        location_text=location_text,
        virtual_meeting_url=virtual_meeting_url,
        generated_at_utc=generated_at_utc,
        attendees=attendees,
    )
