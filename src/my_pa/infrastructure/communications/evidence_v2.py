"""The `communications_evidence_v2` source-contract parser (both dialects).

`parse_publication(data)` turns the bytes of one publication into a
`PublicationParse`: either `accepted` with a domain `Publication` (every record
classified), or `rejected` with one `PublicationRejection` code. Rejection is
reserved for the publication envelope; **one bad record never rejects a
publication** -- it is quarantined with reason codes instead.

Publication validation, in order (the first failure decides):

1. size <= `MAX_PUBLICATION_BYTES`; strict UTF-8; JSON with no duplicate object
   key and no `NaN`/`Infinity` (`malformed_json` carries line/column/offset only,
   never a snippet of the document);
2. a JSON object whose `schema` is `communications_evidence_v2`;
3. `schema_version` is `MAJOR.MINOR.PATCH`; major `2` only
   (`unsupported_major_version` otherwise); a newer minor is accepted and
   reported (`schema_minor_newer`) -- forward-compatible minor additions;
4. required keys `schema, schema_version, business_date, window, coverage,
   mailbox_ref, messages` (`id_header`, `cycle_run_id` optional);
5. `business_date` an ISO date, `mailbox_ref` a non-empty string, `messages` a
   list, `coverage` an object; `window.start_utc`/`end_utc` aware ISO-8601
   timestamps with `end >= start` (`invalid_window`).

Dialect: `lean` carries the canonical keys only; `rich` adds `candidates,
counts, provenance, threads, transport` (and per-message privacy screen,
`unique_body`, links, `fetch_state`, `in_window`, ...). Detection is by those
five top-level markers: none -> lean, any -> rich (some but not all is reported
as `dialect_markers_incomplete`). Records are parsed field-driven, so either
dialect's per-message fields are understood wherever they appear. Unknown keys
are tolerated and counted, never fatal.

Provider vocabulary handled here and nowhere else: id formats
(`graph_default_mutable`, `graph_immutable_verified`), selected timestamp
fields (`receivedDateTime`, `sentDateTime`), body completeness
(`graph_full_body`, `truncated_unknown`), participant `raw.emailAddress`, and
the `procore` coverage lane.

The parser is pure (bytes in, values out) and records diagnostics through the
bounded, content-free `DiagnosticCollector`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from my_pa.domain.communications.classification import classify_records
from my_pa.domain.communications.diagnostics import (
    QUARANTINE_REASONS,
    DiagnosticCode,
    DiagnosticCollector,
    Diagnostics,
    PublicationRejection,
    ReasonCode,
)
from my_pa.domain.communications.integrity import check_content, check_text_digest, is_sha256_hex
from my_pa.domain.communications.model import (
    SCHEMA_NAME,
    SUPPORTED_MAJOR,
    BodyCompleteness,
    BodyPart,
    BodyState,
    ContentType,
    ConversationState,
    CoverageState,
    Dialect,
    FolderRole,
    IdentityState,
    IntegrityOutcome,
    MessageTimestamps,
    NormalizedMessage,
    ParticipantField,
    ParticipantState,
    ProducerDerivedText,
    ProviderIdFormat,
    Publication,
    QuarantinedRecord,
    SchemaVersion,
    SourceCoverage,
    SourceLane,
    TimestampField,
    Window,
    WindowRule,
)

__all__ = [
    "MAX_PUBLICATION_BYTES",
    "PARSER_VERSION",
    "PublicationParse",
    "PublicationStatus",
    "parse_publication",
]

PARSER_VERSION: Final = "communications_evidence_v2_parser_v1"
MAX_PUBLICATION_BYTES: Final = 64 * 1024 * 1024

REQUIRED_TOP_LEVEL: Final = (
    "schema",
    "schema_version",
    "business_date",
    "window",
    "coverage",
    "mailbox_ref",
    "messages",
)
OPTIONAL_TOP_LEVEL: Final = frozenset({"id_header", "cycle_run_id"})
RICH_MARKERS: Final = frozenset({"candidates", "counts", "provenance", "threads", "transport"})
KNOWN_TOP_LEVEL: Final = frozenset(REQUIRED_TOP_LEVEL) | OPTIONAL_TOP_LEVEL | RICH_MARKERS

#: Every per-message key either dialect is known to carry. Anything else is
#: tolerated and counted as an unknown record key.
KNOWN_RECORD_KEYS: Final = frozenset(
    {
        "attachments_note", "bcc", "body", "body_derived_plain_text", "body_preview",
        "body_preview_note", "cc", "conversation_id", "conversation_id_state", "dedup_key",
        "duplicate_observations", "fetch_error", "fetch_state", "flags", "from",
        "from_sender_differ", "has_attachments", "id", "id_format", "id_header", "importance",
        "in_window", "internet_message_id", "internet_message_id_state", "is_read", "links",
        "mailbox_ref", "message_id", "privacy", "provenance", "reply_to", "sender",
        "shares_internet_message_id_with", "source_folder", "source_folders_observed",
        "source_lane", "subject", "timestamps", "to", "unique_body",
    }
)  # fmt: skip

PARTICIPANT_FIELDS: Final = ("from", "sender", "to", "cc", "bcc", "reply_to")

_SEMVER: Final = re.compile(r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})")
_ISO_DATE: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_ISO_TIMESTAMP: Final = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)
_TZ_NAME: Final = re.compile(r"UTC|[A-Z][A-Za-z_]{1,30}(?:/[A-Za-z_\-+0-9]{1,30}){1,2}")
_HOURS_TOLERANCE_SECONDS: Final = 60

_ID_FORMATS: Final = MappingProxyType(
    {
        "graph_default_mutable": ProviderIdFormat.MUTABLE,
        "graph_immutable_verified": ProviderIdFormat.IMMUTABLE_VERIFIED,
        "unknown": ProviderIdFormat.UNKNOWN,
    }
)
_SELECTED_FIELDS: Final = MappingProxyType(
    {"receivedDateTime": TimestampField.RECEIVED, "sentDateTime": TimestampField.SENT}
)
_COMPLETENESS: Final = MappingProxyType(
    {
        "graph_full_body": BodyCompleteness.COMPLETE,
        "truncated_unknown": BodyCompleteness.TRUNCATED_UNKNOWN,
    }
)
_FOLDER_ROLES: Final = MappingProxyType(
    {"inbox": FolderRole.INBOX, "sent": FolderRole.SENT, "other": FolderRole.OTHER}
)
_LANES: Final = MappingProxyType({"mail": SourceLane.MAIL, "procore": SourceLane.PROJECT_SYSTEM})
_COVERAGE_STATES: Final = MappingProxyType(
    {state.value: state for state in CoverageState if state is not CoverageState.UNKNOWN}
)
_PARTICIPANT_STATES: Final = MappingProxyType(
    {
        "provider_returned": ParticipantState.PROVIDER_RETURNED,
        "not_exposed": ParticipantState.NOT_EXPOSED,
    }
)
_WINDOW_RULES: Final = MappingProxyType(
    {rule.value: rule for rule in WindowRule if rule is not WindowRule.OTHER}
)


class PublicationStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class PublicationParse:
    status: PublicationStatus
    rejection: PublicationRejection | None
    publication: Publication | None
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


def _parse_utc(value: object) -> datetime | None:
    """An aware ISO-8601 `YYYY-MM-DDTHH:MM:SS[.f](Z|+HH:MM)` as UTC, else `None`."""
    if not isinstance(value, str) or _ISO_TIMESTAMP.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC)


def _as_count(value: object) -> int | None:
    """A non-negative JSON integer (a boolean is not one), else `None`."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _enum[E: StrEnum](table: Mapping[str, E], raw: object, default: E) -> E:
    return table.get(raw, default) if isinstance(raw, str) else default


def _nonempty_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _as_mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, dict) else None


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
        # Line, column and offset only: `error.doc` and `error.msg` context are
        # never retained, so no document text can reach a diagnostic.
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
    if version.minor > 0:
        d.add(DiagnosticCode.SCHEMA_MINOR_NEWER, "schema_version", minor=version.minor)
    return version


def _parse(data: bytes, d: DiagnosticCollector) -> Publication:
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
    for key in REQUIRED_TOP_LEVEL:
        if key not in document:
            raise _reject(d, PublicationRejection.MISSING_REQUIRED_KEY, key)

    raw_date = document["business_date"]
    try:
        if not isinstance(raw_date, str) or _ISO_DATE.fullmatch(raw_date) is None:
            raise ValueError
        business_date = date.fromisoformat(raw_date)
    except ValueError:
        raise _reject(d, PublicationRejection.INVALID_TOP_LEVEL_FIELD, "business_date") from None
    mailbox_ref = _nonempty_str(document["mailbox_ref"])
    if mailbox_ref is None:
        raise _reject(d, PublicationRejection.INVALID_TOP_LEVEL_FIELD, "mailbox_ref")
    messages = document["messages"]
    if not isinstance(messages, list):
        raise _reject(d, PublicationRejection.INVALID_TOP_LEVEL_FIELD, "messages")
    coverage = _as_mapping(document["coverage"])
    if coverage is None:
        raise _reject(d, PublicationRejection.INVALID_TOP_LEVEL_FIELD, "coverage")
    window = _window(document["window"], d)

    markers = RICH_MARKERS & document.keys()
    dialect = Dialect.RICH if markers else Dialect.LEAN
    if markers and markers != RICH_MARKERS:
        d.add(DiagnosticCode.DIALECT_MARKERS_INCOMPLETE, "$", present=len(markers))
    unknown_top = len(document.keys() - KNOWN_TOP_LEVEL)
    if unknown_top:
        d.add(DiagnosticCode.UNKNOWN_TOP_LEVEL_KEYS, "$", count=unknown_top)

    overall, sources = _coverage(coverage, d)

    entries: list[NormalizedMessage | QuarantinedRecord] = []
    unknown_record_keys = 0
    folder_counts: dict[str, int] = {}
    for ordinal, raw in enumerate(messages):
        if isinstance(raw, dict):
            unknown = len(raw.keys() - KNOWN_RECORD_KEYS)
            if unknown:
                unknown_record_keys += unknown
                d.add(DiagnosticCode.UNKNOWN_RECORD_KEYS, "messages[]", ordinal, count=unknown)
            folder = _as_mapping(raw.get("source_folder"))
            folder_key = folder.get("key") if folder is not None else None
            if isinstance(folder_key, str):
                folder_counts[folder_key] = folder_counts.get(folder_key, 0) + 1
        entries.append(_RecordParser(ordinal, mailbox_ref, d).parse(raw))

    for source in sources:
        if (
            source.lane is SourceLane.MAIL
            and source.key is not None
            and source.raw_messages is not None
        ):
            observed = folder_counts.get(source.key, 0)
            if observed != source.raw_messages:
                d.add(
                    DiagnosticCode.COVERAGE_COUNT_MISMATCH,
                    "coverage.sources[].raw_messages",
                    declared=source.raw_messages,
                    observed=observed,
                )

    return Publication(
        dialect=dialect,
        schema_version=version,
        business_date=business_date,
        mailbox_ref=mailbox_ref,
        window=window,
        coverage_overall=overall,
        sources=sources,
        cycle_run_id_present=document.get("cycle_run_id") is not None,
        records=classify_records(entries, window, d),
        unknown_top_level_keys=unknown_top,
        unknown_record_keys=unknown_record_keys,
    )


def _window(raw: object, d: DiagnosticCollector) -> Window:
    window = _as_mapping(raw)
    if window is None:
        raise _reject(d, PublicationRejection.INVALID_WINDOW, "window")
    start, end = _parse_utc(window.get("start_utc")), _parse_utc(window.get("end_utc"))
    if start is None:
        raise _reject(d, PublicationRejection.INVALID_WINDOW, "window.start_utc")
    if end is None:
        raise _reject(d, PublicationRejection.INVALID_WINDOW, "window.end_utc")
    if end < start:
        raise _reject(d, PublicationRejection.INVALID_WINDOW, "window.end_utc")

    hours_raw = window.get("hours")
    declared_hours: float | None = None
    if isinstance(hours_raw, int | float) and not isinstance(hours_raw, bool):
        declared_hours = float(hours_raw)
    elif hours_raw is not None:
        d.add(DiagnosticCode.WINDOW_FIELD_INVALID, "window.hours")

    rule = _enum(_WINDOW_RULES, window.get("rule"), WindowRule.OTHER)

    tz_raw = window.get("tz")
    tz = tz_raw if isinstance(tz_raw, str) and _TZ_NAME.fullmatch(tz_raw) else None
    if tz_raw is not None and tz is None:
        d.add(DiagnosticCode.WINDOW_FIELD_INVALID, "window.tz")

    def optional_bool(key: str) -> bool | None:
        value = window.get(key)
        if value is None or isinstance(value, bool):
            return value
        d.add(DiagnosticCode.WINDOW_FIELD_INVALID, f"window.{key}")
        return None

    backfill = optional_bool("backfill")
    dst_declared = optional_bool("dst_offset_changes_in_window")
    dst_computed: bool | None = None
    if tz is not None:
        try:
            zone = ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            d.add(DiagnosticCode.TZ_UNRESOLVABLE, "window.tz")
        else:
            dst_computed = start.astimezone(zone).utcoffset() != end.astimezone(zone).utcoffset()
            if dst_declared is not None and dst_declared != dst_computed:
                d.add(DiagnosticCode.DST_FLAG_DISAGREEMENT, "window.dst_offset_changes_in_window")

    result = Window(start, end, declared_hours, rule, tz, backfill, dst_declared, dst_computed)
    if declared_hours is not None:
        declared_seconds = round(declared_hours * 3600)
        if abs(declared_seconds - result.actual_seconds) > _HOURS_TOLERANCE_SECONDS:
            d.add(
                DiagnosticCode.WINDOW_HOURS_MISMATCH,
                "window.hours",
                declared_seconds=declared_seconds,
                actual_seconds=result.actual_seconds,
            )
    return result


def _count(value: object) -> int:
    if isinstance(value, list):
        return len(value)
    count = _as_count(value)
    return 0 if count is None else count


def _coverage(
    coverage: Mapping[str, object], d: DiagnosticCollector
) -> tuple[CoverageState, tuple[SourceCoverage, ...]]:
    overall_raw = coverage.get("overall")
    overall = (
        _COVERAGE_STATES.get(overall_raw, CoverageState.UNKNOWN)
        if isinstance(overall_raw, str)
        else CoverageState.UNKNOWN
    )
    if overall is CoverageState.UNKNOWN:
        d.add(DiagnosticCode.COVERAGE_INVALID, "coverage.overall")
    raw_sources = coverage.get("sources")
    if not isinstance(raw_sources, list):
        d.add(DiagnosticCode.COVERAGE_INVALID, "coverage.sources")
        return overall, ()
    sources: list[SourceCoverage] = []
    for raw in raw_sources:
        source = _as_mapping(raw)
        if source is None:
            d.add(DiagnosticCode.COVERAGE_SOURCE_INVALID, "coverage.sources[]")
            continue
        key = source.get("key")
        role = source.get("role")
        lane = source.get("lane")
        authorized = source.get("authorized")
        state = source.get("coverage")
        raw_messages = source.get("raw_messages")
        pages = source.get("pages")
        page_list = pages if isinstance(pages, list) else []
        sources.append(
            SourceCoverage(
                key=key if isinstance(key, str) else None,
                role=_enum(_FOLDER_ROLES, role, FolderRole.OTHER),
                lane=_enum(_LANES, lane, SourceLane.OTHER),
                authorized=authorized if isinstance(authorized, bool) else None,
                state=_enum(_COVERAGE_STATES, state, CoverageState.UNKNOWN),
                raw_messages=_as_count(raw_messages),
                pages=_count(pages),
                pages_not_ok=sum(
                    1
                    for page in page_list
                    if not (isinstance(page, dict) and page.get("status") == "ok")
                ),
                errors=_count(source.get("errors")),
                warnings=_count(source.get("warnings")),
            )
        )
    return overall, tuple(sources)


class _RecordParser:
    """Normalizes one record, collecting quarantine and degradation reasons."""

    def __init__(self, ordinal: int, mailbox_ref: str, diagnostics: DiagnosticCollector) -> None:
        self.ordinal = ordinal
        self.mailbox_ref = mailbox_ref
        self.d = diagnostics
        self.reasons: list[ReasonCode] = []

    def flag(self, reason: ReasonCode, path: str) -> None:
        self.d.add(reason, path, self.ordinal)
        if reason not in self.reasons:
            self.reasons.append(reason)

    def parse(self, raw: object) -> NormalizedMessage | QuarantinedRecord:
        record = _as_mapping(raw)
        if record is None:
            self.flag(ReasonCode.RECORD_NOT_AN_OBJECT, "messages[]")
            return QuarantinedRecord(self.ordinal, tuple(self.reasons))
        message = self._normalize(record)
        if message is None or any(r in QUARANTINE_REASONS for r in self.reasons):
            return QuarantinedRecord(self.ordinal, tuple(self.reasons))
        return message

    def required(self, record: Mapping[str, object], key: str, path: str) -> object:
        value = record.get(key)
        if value is None:
            self.flag(ReasonCode.MISSING_REQUIRED_FIELD, path)
        return value

    def _normalize(self, record: Mapping[str, object]) -> NormalizedMessage | None:
        provider_id = self._provider_id(record)
        id_format = self._id_format(record)
        mailbox = self._mailbox(record)
        folder_key, folder_role = self._folder(record)
        identity_state, imid = self._internet_message_id(record)
        conversation_state, conversation_id = self._conversation(record)
        subject = record.get("subject")
        if subject is not None and not isinstance(subject, str):
            self.flag(ReasonCode.INVALID_FIELD_TYPE, "messages[].subject")
            subject = None
        participants = MappingProxyType(
            {name: self._participant(record, name) for name in PARTICIPANT_FIELDS}
        )
        timestamps = self._timestamps(record)
        privacy = _as_mapping(record.get("privacy"))
        privacy_withheld = privacy is not None and privacy.get("policy_withheld") is True
        body = self._body(record.get("body"), "messages[].body", privacy_withheld, required=True)
        unique_raw = record.get("unique_body")
        unique = (
            None
            if unique_raw is None
            else self._body(unique_raw, "messages[].unique_body", privacy_withheld, required=False)
        )
        derived = self._derived(record.get("body_derived_plain_text"), body)
        has_attachments = record.get("has_attachments")
        in_window = record.get("in_window")
        if record.get("fetch_error") is not None:
            self.flag(ReasonCode.FETCH_ERROR_REPORTED, "messages[].fetch_error")

        if provider_id is None or mailbox is None or timestamps is None or body is None:
            return None
        return NormalizedMessage(
            ordinal=self.ordinal,
            provider_id=provider_id,
            provider_id_format=id_format,
            mailbox_ref=mailbox,
            folder_key=folder_key,
            folder_role=folder_role,
            identity_state=identity_state,
            internet_message_id=imid,
            conversation_state=conversation_state,
            conversation_id=conversation_id,
            subject=subject,
            participants=participants,
            timestamps=timestamps,
            body=body,
            unique_body=unique,
            derived_text=derived,
            has_attachments=has_attachments if isinstance(has_attachments, bool) else None,
            declared_in_window=in_window if isinstance(in_window, bool) else None,
            degraded_reasons=tuple(self.reasons),
        )

    def _provider_id(self, record: Mapping[str, object]) -> str | None:
        raw = self.required(record, "id", "messages[].id")
        if raw is None:
            return None
        provider_id = _nonempty_str(raw)
        if provider_id is None:
            self.flag(ReasonCode.INVALID_FIELD_VALUE, "messages[].id")
            return None
        message_id = record.get("message_id")
        if message_id is not None and message_id != raw:
            self.flag(ReasonCode.PROVIDER_ID_FIELDS_DISAGREE, "messages[].message_id")
        return provider_id

    def _id_format(self, record: Mapping[str, object]) -> ProviderIdFormat:
        raw = record.get("id_format")
        if isinstance(raw, str) and raw in _ID_FORMATS:
            return _ID_FORMATS[raw]
        self.flag(ReasonCode.UNKNOWN_ID_FORMAT, "messages[].id_format")
        return ProviderIdFormat.UNKNOWN

    def _mailbox(self, record: Mapping[str, object]) -> str | None:
        raw = self.required(record, "mailbox_ref", "messages[].mailbox_ref")
        if raw is None:
            return None
        if not isinstance(raw, str) or raw.strip() != self.mailbox_ref:
            self.flag(ReasonCode.MAILBOX_REF_MISMATCH, "messages[].mailbox_ref")
            return None
        return self.mailbox_ref

    def _folder(self, record: Mapping[str, object]) -> tuple[str | None, FolderRole]:
        folder = self.required(record, "source_folder", "messages[].source_folder")
        if folder is None:
            return None, FolderRole.OTHER
        if not isinstance(folder, dict):
            self.flag(ReasonCode.INVALID_FIELD_TYPE, "messages[].source_folder")
            return None, FolderRole.OTHER
        key = folder.get("key")
        role = self.required(folder, "role", "messages[].source_folder.role")
        if role is None:
            return None, FolderRole.OTHER
        if not isinstance(role, str):
            self.flag(ReasonCode.INVALID_FIELD_TYPE, "messages[].source_folder.role")
            return None, FolderRole.OTHER
        mapped = _FOLDER_ROLES.get(role)
        if mapped is None:
            self.flag(ReasonCode.UNKNOWN_FOLDER_ROLE, "messages[].source_folder.role")
            mapped = FolderRole.OTHER
        return (key if isinstance(key, str) else None), mapped

    def _internet_message_id(
        self, record: Mapping[str, object]
    ) -> tuple[IdentityState, str | None]:
        raw = record.get("internet_message_id")
        state = record.get("internet_message_id_state")
        if raw is not None and not isinstance(raw, str):
            self.flag(ReasonCode.INVALID_FIELD_TYPE, "messages[].internet_message_id")
            return IdentityState.PROVIDER_ID_ONLY, None
        imid = _nonempty_str(raw)
        if imid is not None:
            if state is not None and state != "provider_returned":
                self.flag(
                    ReasonCode.IDENTITY_STATE_INCONSISTENT, "messages[].internet_message_id_state"
                )
            return IdentityState.PROVIDER_RETURNED, imid
        self.flag(ReasonCode.IDENTITY_PROVIDER_ID_ONLY, "messages[].internet_message_id")
        if state == "provider_returned":
            self.flag(
                ReasonCode.IDENTITY_STATE_INCONSISTENT, "messages[].internet_message_id_state"
            )
        return IdentityState.PROVIDER_ID_ONLY, None

    def _conversation(self, record: Mapping[str, object]) -> tuple[ConversationState, str | None]:
        raw = record.get("conversation_id")
        if raw is not None and not isinstance(raw, str):
            self.flag(ReasonCode.INVALID_FIELD_TYPE, "messages[].conversation_id")
            return ConversationState.ABSENT, None
        conversation_id = _nonempty_str(raw)
        if conversation_id is None:
            self.flag(ReasonCode.CONVERSATION_ID_ABSENT, "messages[].conversation_id")
            return ConversationState.ABSENT, None
        return ConversationState.PROVIDER_RETURNED, conversation_id

    def _participant(self, record: Mapping[str, object], name: str) -> ParticipantField:
        path = f"messages[].{name}"
        raw = record.get(name)
        if raw is None:
            if name == "from":
                self.flag(ReasonCode.PARTICIPANT_FROM_ABSENT, path)
            return ParticipantField(ParticipantState.ABSENT, ())
        if not isinstance(raw, dict):
            self.flag(ReasonCode.INVALID_FIELD_TYPE, path)
            return ParticipantField(ParticipantState.ABSENT, ())
        state_raw = raw.get("state")
        state = _PARTICIPANT_STATES.get(state_raw) if isinstance(state_raw, str) else None
        if state is None:
            self.flag(ReasonCode.UNKNOWN_PARTICIPANT_STATE, f"{path}.state")
            state = ParticipantState.UNKNOWN
        value = raw.get("value")
        entries: list[object]
        if value is None:
            entries = []
        elif isinstance(value, dict):
            entries = [value]
        elif isinstance(value, list):
            entries = value
        else:
            self.flag(ReasonCode.INVALID_FIELD_TYPE, f"{path}.value")
            entries = []
        addresses: list[str] = []
        for entry in entries:
            address = _participant_address(entry)
            if address is None:
                self.flag(ReasonCode.PARTICIPANT_ENTRY_INVALID, f"{path}.value")
            elif address not in addresses:
                addresses.append(address)
        if name == "from" and not addresses:
            self.flag(ReasonCode.PARTICIPANT_FROM_ABSENT, path)
        return ParticipantField(state, tuple(addresses))

    def _timestamps(self, record: Mapping[str, object]) -> MessageTimestamps | None:
        raw = self.required(record, "timestamps", "messages[].timestamps")
        if raw is None:
            return None
        if not isinstance(raw, dict):
            self.flag(ReasonCode.INVALID_FIELD_TYPE, "messages[].timestamps")
            return None
        selected_raw = self.required(raw, "selected_utc", "messages[].timestamps.selected_utc")
        field_raw = self.required(raw, "selected_field", "messages[].timestamps.selected_field")
        if selected_raw is None or field_raw is None:
            return None
        selected = _parse_utc(selected_raw)
        if selected is None:
            self.flag(ReasonCode.UNPARSEABLE_TIMESTAMP, "messages[].timestamps.selected_utc")
            return None
        field = _SELECTED_FIELDS.get(field_raw) if isinstance(field_raw, str) else None
        if field is None:
            self.flag(ReasonCode.INVALID_FIELD_VALUE, "messages[].timestamps.selected_field")
            return None

        def optional(key: str) -> datetime | None:
            value = raw.get(key)
            if value is None:
                return None
            parsed = _parse_utc(value)
            if parsed is None:
                self.flag(ReasonCode.RAW_TIMESTAMP_UNPARSEABLE, f"messages[].timestamps.{key}")
            return parsed

        received, sent = optional("received_raw"), optional("sent_raw")
        selected_echo = optional("selected_raw")
        own = received if field is TimestampField.RECEIVED else sent
        if (own is not None and own != selected) or (
            selected_echo is not None and selected_echo != selected
        ):
            self.flag(ReasonCode.SELECTED_TIMESTAMP_INCONSISTENT, "messages[].timestamps")
        return MessageTimestamps(selected, field, received, sent)

    def _body(
        self, raw: object, path: str, privacy_withheld: bool, *, required: bool
    ) -> BodyPart | None:
        if raw is None:
            if required:
                self.flag(ReasonCode.MISSING_REQUIRED_FIELD, path)
            return None
        if not isinstance(raw, dict):
            self.flag(ReasonCode.INVALID_FIELD_TYPE, path)
            return None
        content_type_raw = self.required(raw, "content_type", f"{path}.content_type")
        sha_raw = self.required(raw, "sha256", f"{path}.sha256")
        bytes_raw = self.required(raw, "utf8_bytes", f"{path}.utf8_bytes")
        if content_type_raw is None or sha_raw is None or bytes_raw is None:
            return None
        content_type = (
            {"html": ContentType.HTML, "text": ContentType.TEXT}.get(content_type_raw.lower())
            if isinstance(content_type_raw, str)
            else None
        )
        if content_type is None:
            self.flag(ReasonCode.INVALID_FIELD_VALUE, f"{path}.content_type")
            return None
        sha256 = sha_raw.lower() if isinstance(sha_raw, str) else None
        if sha256 is None or not is_sha256_hex(sha256):
            self.flag(ReasonCode.INVALID_FIELD_VALUE, f"{path}.sha256")
            return None
        utf8_bytes = _as_count(bytes_raw)
        if utf8_bytes is None:
            self.flag(ReasonCode.INVALID_FIELD_TYPE, f"{path}.utf8_bytes")
            return None

        completeness = BodyCompleteness.COMPLETE
        if required:
            completeness_raw = raw.get("body_completeness")
            mapped = (
                _COMPLETENESS.get(completeness_raw) if isinstance(completeness_raw, str) else None
            )
            if mapped is None:
                self.flag(ReasonCode.UNKNOWN_BODY_COMPLETENESS, f"{path}.body_completeness")
                mapped = BodyCompleteness.UNKNOWN
            completeness = mapped

        content = raw.get("content")
        withheld_marker = _nonempty_str(raw.get("content_withheld")) is not None
        if content is not None and not isinstance(content, str):
            self.flag(ReasonCode.INVALID_FIELD_TYPE, f"{path}.content")
            return None
        if content is None:
            if not (withheld_marker or privacy_withheld):
                self.flag(ReasonCode.BODY_CONTENT_MISSING, f"{path}.content")
                return None
            return BodyPart(
                BodyState.WITHHELD, content_type, None, sha256, utf8_bytes, completeness,
                IntegrityOutcome.NOT_VERIFIABLE_WITHHELD,
            )  # fmt: skip
        if withheld_marker or privacy_withheld:
            # Marked withheld yet content is present: honour the screen, discard it.
            self.flag(ReasonCode.PRIVACY_WITHHELD_CONTENT_PRESENT, f"{path}.content")
            return BodyPart(
                BodyState.WITHHELD, content_type, None, sha256, utf8_bytes, completeness,
                IntegrityOutcome.NOT_VERIFIABLE_WITHHELD,
            )  # fmt: skip
        integrity = check_content(content, sha256, utf8_bytes)
        if integrity is IntegrityOutcome.MISMATCH:
            self.flag(ReasonCode.INTEGRITY_MISMATCH, path)
        if completeness is BodyCompleteness.TRUNCATED_UNKNOWN:
            self.flag(ReasonCode.BODY_TRUNCATED, f"{path}.body_completeness")
            state = BodyState.TRUNCATED
        elif not content.strip():
            state = BodyState.EMPTY
        else:
            state = BodyState.PRESENT
        return BodyPart(state, content_type, content, sha256, utf8_bytes, completeness, integrity)

    def _derived(self, raw: object, body: BodyPart | None) -> ProducerDerivedText | None:
        path = "messages[].body_derived_plain_text"
        if raw is None:
            return None
        if not isinstance(raw, dict):
            self.flag(ReasonCode.DERIVED_TEXT_INVALID, path)
            return None
        text = raw.get("text")
        if text is not None and not isinstance(text, str):
            self.flag(ReasonCode.DERIVED_TEXT_INVALID, f"{path}.text")
            return ProducerDerivedText(None, IntegrityOutcome.NOT_DECLARED, False)
        if body is not None and body.state is BodyState.WITHHELD:
            # A withheld body yields no searchable text, whatever else was sent.
            return ProducerDerivedText(None, IntegrityOutcome.NOT_VERIFIABLE_WITHHELD, False)
        sha_raw = raw.get("sha256")
        sha256: str | None = None
        if sha_raw is not None:
            sha256 = sha_raw.lower() if isinstance(sha_raw, str) else None
            if sha256 is None or not is_sha256_hex(sha256):
                self.flag(ReasonCode.DERIVED_TEXT_INVALID, f"{path}.sha256")
                return ProducerDerivedText(text, IntegrityOutcome.NOT_DECLARED, False)
        integrity = check_text_digest(text, sha256)
        if integrity is IntegrityOutcome.MISMATCH:
            self.flag(ReasonCode.INTEGRITY_MISMATCH, path)
        usable = (
            raw.get("derived") is True
            and bool(text and text.strip())
            and integrity is IntegrityOutcome.VERIFIED
        )
        return ProducerDerivedText(text, integrity, usable)


def _participant_address(entry: object) -> str | None:
    if not isinstance(entry, dict):
        return None
    for candidate in (entry.get("address_normalized"), entry.get("address")):
        address = _nonempty_str(candidate)
        if address is not None:
            return address.lower()
    raw = _as_mapping(entry.get("raw"))
    email = _as_mapping(raw.get("emailAddress")) if raw is not None else None
    address = _nonempty_str(email.get("address")) if email is not None else None
    return address.lower() if address is not None else None
