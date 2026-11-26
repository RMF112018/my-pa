"""P6 XER admission and worker decisions, slice S7-3 (pure).

Contract `docs/architecture/schedule-xer-import-contract.md` sections 9.1
(admission), 9.3 (worker), 10.3 (inputs), 11.1 (Series identity) and 11.3
(activity matching) under ADR-023. Everything here is a value or a pure
function: the strict request and its digest, the byte sniff (the extension is
never read), the admitted snapshot, the typed admission refusals, the project
identity rule and the activity matching across two publications of a Series.

Standard library and `my_pa.domain.schedule` / `my_pa.domain.common` only
(`tests/architecture/test_cpm_full_parser_scope.py`): no clock, database,
file or network. The parser package is never imported here.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.schedule.model import (
    MAX_SCHEDULE_SOURCE_BYTES,
    SCHEDULE_IDEMPOTENCY_KEY_PATTERN,
    InvalidScheduleSeriesNameError,
    ScheduleSeriesName,
    normalize_series_name,
)

__all__ = [
    "MAX_P6_SNAPSHOT_BYTES",
    "P6_IMPORT_FIELDS",
    "P6_PARSER_NAME",
    "P6_XER_MEDIA_TYPE",
    "P6ActivityIdentity",
    "P6ActivityMatching",
    "P6Admission",
    "P6AdmissionLimits",
    "P6AdmissionOutcome",
    "P6AdmissionRefusal",
    "P6AdmissionRejectedError",
    "P6ImportRequest",
    "P6ProjectIdentity",
    "P6RenumberCandidate",
    "P6RequestError",
    "P6Snapshot",
    "P6SourceFormat",
    "match_p6_activities",
    "p6_identity_changed",
    "p6_import_request",
    "p6_import_request_digest",
    "sniff_p6_format",
]

#: Section 9.1 step 3: there is no registered media type for XER [D].
P6_XER_MEDIA_TYPE: Final = "application/vnd.my-pa.p6-xer"
#: Section 9.3 H5: the parser a P6 run names (its version is the catalogue's).
P6_PARSER_NAME: Final = "cpm-workbench-p6-xer"
#: Section 9.1 step 2 / 5.4: the admitted file bound.
MAX_P6_SNAPSHOT_BYTES: Final = MAX_SCHEDULE_SOURCE_BYTES
#: Files workspace contract section 4: a workspace path is 1 to 4,096 bytes.
_MAX_PATH_BYTES: Final = 4096
_WORKSPACE_ALIAS: Final = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z")
_VERSION_TOKEN: Final = re.compile(r"\Afv1_[0-9a-f]{64}\Z")
_SHA256: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_HEADER: Final = b"ERMHDR\t"
_END: Final = b"%E"
_DIGEST_DOMAIN: Final = b"my-pa-p6-import-request-v1\n"


class P6SourceFormat(StrEnum):
    """Section 8.2 `source_format` values a P6 publication may carry."""

    P6_XER = "p6_xer"
    P6_XML = "p6_xml"


def sniff_p6_format(data: bytes) -> P6SourceFormat | None:
    """Section 9.1 step 3: `p6_xer` iff the bytes start `ERMHDR<TAB>` and end `%E`.

    Only the bytes decide (a file name or extension is never consulted). The
    last non-empty line, with its line end removed, must be exactly `%E`;
    blank lines after it are tolerated as the parser tolerates them (5.5).
    `p6_xml` is not sniffed until the XML slice.
    """
    given: object = data
    if not isinstance(given, bytes) or not given.startswith(_HEADER):
        return None
    for line in reversed(data.split(b"\n")):
        stripped = line.removesuffix(b"\r")
        if stripped.strip(b" \t\r") == b"":
            continue
        return P6SourceFormat.P6_XER if stripped == _END else None
    return None  # pragma: no cover - a header line is never empty


class P6RequestError(ValueError):
    """A strict-input refusal naming the request field, never its value."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class P6AdmissionRefusal(StrEnum):
    """Every typed refusal of the admission transaction (section 9.1 step 4)."""

    PROJECT_NOT_FOUND = "project_not_found"
    SERIES_NOT_FOUND = "series_not_found"
    SERIES_FORMAT = "series_format"
    IDEMPOTENCY_KEY_CONFLICT = "idempotency_key_conflict"
    SUPERSEDED_PUBLICATION_NOT_FOUND = "superseded_publication_not_found"
    SUPERSEDED_PUBLICATION_NOT_TERMINAL = "superseded_publication_not_terminal"
    SUPERSEDED_PUBLICATION_HAS_SUCCESSOR = "superseded_publication_has_successor"
    #: S7-4a (section 7.7): the new snapshot would pass the Principal's quota.
    STORAGE_QUOTA = "storage_quota"
    #: S7-4a (section 7.7): the Principal's hourly or daily import budget is spent.
    IMPORT_RATE = "import_rate"


class P6AdmissionRejectedError(Exception):
    """The admission transaction refused; the reason is a closed token."""

    def __init__(self, reason: P6AdmissionRefusal) -> None:
        super().__init__(reason.value)
        self.reason = reason


class P6AdmissionOutcome(StrEnum):
    """`created`; `replayed` (same key, same digest); `already_present` (same bytes, 9.1)."""

    CREATED = "created"
    REPLAYED = "replayed"
    ALREADY_PRESENT = "already_present"


@dataclass(frozen=True, slots=True)
class P6AdmissionLimits:
    """Section 7.7 (S7-4a): the snapshot quota and the import budgets of one Principal.

    Checked inside the admission transaction after the key replay and content
    idempotency (which write nothing and so spend nothing): a new snapshot
    must fit `snapshot_quota_bytes` beside the Principal's retained snapshots
    (bytes already held are never counted twice), and fewer than
    `imports_per_hour` / `imports_per_day` P6 publications may have been
    admitted in the trailing hour / day.
    """

    snapshot_quota_bytes: int
    imports_per_hour: int
    imports_per_day: int

    def __post_init__(self) -> None:
        for value in (self.snapshot_quota_bytes, self.imports_per_hour, self.imports_per_day):
            if type(value) is not int or value < 1:
                raise ValueError("an admission limit is a positive integer")


@dataclass(frozen=True, slots=True)
class P6ImportRequest:
    """Section 10.3 `import_p6` inputs, validated; exactly one Series selector.

    `series_name_if_new` is always `None` (10.3 has no such input); it exists so
    the S5/S6 Series resolution reads one shape for both formats.
    """

    project_id: str
    series_id: str | None
    series_name: ScheduleSeriesName | None
    series_auto: bool
    workspace_id: str
    path: str
    expected_version: str
    expected_sha256: str
    format: P6SourceFormat
    accept_project_identity_change: bool
    supersedes_publication_id: str | None
    idempotency_key: str

    @property
    def series_name_if_new(self) -> None:
        return None

    def __post_init__(self) -> None:
        validate_identifier(self.project_id, IdKind.PROJECT)
        if not isinstance(self.series_auto, bool):
            raise P6RequestError("series_auto")
        named = (self.series_id is not None, self.series_name is not None, self.series_auto)
        if sum(named) != 1:
            raise P6RequestError("series_id")
        if self.series_id is not None:
            validate_identifier(self.series_id, IdKind.SCHEDULE_SERIES)
        if self.series_name is not None and not isinstance(self.series_name, ScheduleSeriesName):
            raise P6RequestError("series_name")
        if not _matches(_WORKSPACE_ALIAS, self.workspace_id):
            raise P6RequestError("workspace_id")
        if not _is_workspace_path(self.path):
            raise P6RequestError("path")
        if not _matches(_VERSION_TOKEN, self.expected_version):
            raise P6RequestError("expected_version")
        if not _matches(_SHA256, self.expected_sha256):
            raise P6RequestError("expected_sha256")
        if not isinstance(self.format, P6SourceFormat):
            raise P6RequestError("format")
        if not isinstance(self.accept_project_identity_change, bool):
            raise P6RequestError("accept_project_identity_change")
        if self.supersedes_publication_id is not None:
            validate_identifier(self.supersedes_publication_id, IdKind.SCHEDULE_PUBLICATION)
            if self.series_auto:
                raise P6RequestError("supersedes_publication_id")
        if not _matches(SCHEDULE_IDEMPOTENCY_KEY_PATTERN, self.idempotency_key):
            raise P6RequestError("idempotency_key")


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _is_workspace_path(value: object) -> bool:
    """A workspace-relative path shape; the files-workspace store is the authority."""
    if not isinstance(value, str) or "\x00" in value:
        return False
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        return False
    return 1 <= size <= _MAX_PATH_BYTES and not value.startswith("/") and not value.endswith("/")


#: Section 10.3: the request keys `import_p6` admits; any other key is refused.
P6_IMPORT_FIELDS: Final = frozenset(
    {
        "project_id",
        "series_id",
        "series_name",
        "series_auto",
        "workspace_id",
        "path",
        "expected_version",
        "expected_sha256",
        "format",
        "accept_project_identity_change",
        "supersedes_publication_id",
        "idempotency_key",
    }
)
_REQUIRED_FIELDS: Final = frozenset(
    {
        "project_id",
        "workspace_id",
        "path",
        "expected_version",
        "expected_sha256",
        "format",
        "idempotency_key",
    }
)


def _text(payload: Mapping[str, object], key: str) -> str:
    value = payload[key]
    if type(value) is not str:
        raise P6RequestError(key)
    return value


def _optional_text(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if type(value) is not str:
        raise P6RequestError(key)
    return value


def _flag(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key, False)
    if type(value) is not bool:
        raise P6RequestError(key)
    return value


def p6_import_request(payload: Mapping[str, object]) -> P6ImportRequest:
    """Section 10.3 strict inputs: an unknown, missing or mistyped key is refused.

    Raises `P6RequestError` naming the first offending field (unknown keys
    first, in sorted order); identifier shape errors surface as `ValueError`
    from the identifier validator and are refused by the caller the same way.
    """
    if not isinstance(payload, Mapping):
        raise P6RequestError("request")
    unknown = sorted(str(key) for key in payload if key not in P6_IMPORT_FIELDS)
    if unknown:
        raise P6RequestError(unknown[0])
    missing = sorted(_REQUIRED_FIELDS - set(payload))
    if missing:
        raise P6RequestError(missing[0])
    raw_name = _optional_text(payload, "series_name")
    try:
        series_name = None if raw_name is None else normalize_series_name(raw_name)
    except InvalidScheduleSeriesNameError:
        raise P6RequestError("series_name") from None
    raw_format = _text(payload, "format")
    try:
        source_format = P6SourceFormat(raw_format)
    except ValueError:
        raise P6RequestError("format") from None
    try:
        return P6ImportRequest(
            project_id=_text(payload, "project_id"),
            series_id=_optional_text(payload, "series_id"),
            series_name=series_name,
            series_auto=_flag(payload, "series_auto"),
            workspace_id=_text(payload, "workspace_id"),
            path=_text(payload, "path"),
            expected_version=_text(payload, "expected_version"),
            expected_sha256=_text(payload, "expected_sha256"),
            format=source_format,
            accept_project_identity_change=_flag(payload, "accept_project_identity_change"),
            supersedes_publication_id=_optional_text(payload, "supersedes_publication_id"),
            idempotency_key=_text(payload, "idempotency_key"),
        )
    except P6RequestError:
        raise
    except ValueError:
        # An identifier of the wrong shape: name the field, never the value.
        for key in ("project_id", "series_id", "supersedes_publication_id"):
            value = payload.get(key)
            if value is not None and not _identifier_ok(key, value):
                raise P6RequestError(key) from None
        raise P6RequestError("request") from None


_IDENTIFIER_KINDS: Final = {
    "project_id": IdKind.PROJECT,
    "series_id": IdKind.SCHEDULE_SERIES,
    "supersedes_publication_id": IdKind.SCHEDULE_PUBLICATION,
}


def _identifier_ok(key: str, value: object) -> bool:
    try:
        validate_identifier(value, _IDENTIFIER_KINDS[key])  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return False
    return True


def p6_import_request_digest(principal_id: str, request: P6ImportRequest) -> str:
    """Section 9.1 step 4: the request digest -- everything but the idempotency key.

    The Series is named by id, by casefold key or as automatic, so names that
    differ only in case or whitespace digest equal (the S5 rule). The
    workspace provenance and both expectations are part of the request.
    """
    validate_identifier(principal_id, IdKind.PRINCIPAL)
    body = {
        "principal_id": principal_id,
        "request": {
            "project_id": request.project_id,
            "series_id": request.series_id,
            "series_name_key": None if request.series_name is None else request.series_name.key,
            "series_auto": request.series_auto,
            "workspace_id": request.workspace_id,
            "path": request.path,
            "expected_version": request.expected_version,
            "expected_sha256": request.expected_sha256,
            "format": request.format.value,
            "accept_project_identity_change": request.accept_project_identity_change,
            "supersedes_publication_id": request.supersedes_publication_id,
        },
    }
    canonical = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")
    return hashlib.sha256(_DIGEST_DOMAIN + canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class P6Snapshot:
    """Section 9.1: the admitted bytes, their SHA-256 and size, and their format."""

    content: bytes
    format: P6SourceFormat

    def __post_init__(self) -> None:
        content: object = self.content
        if not isinstance(content, bytes) or not 1 <= len(content) <= MAX_P6_SNAPSHOT_BYTES:
            raise ValueError("a p6 snapshot is 1 to 16777216 bytes")
        if not isinstance(self.format, P6SourceFormat):
            raise ValueError("a p6 snapshot carries a closed format")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    @property
    def size_bytes(self) -> int:
        return len(self.content)


@dataclass(frozen=True, slots=True)
class P6Admission:
    """What the admission transaction decided (no workspace path: it is never served)."""

    series_id: str
    series_created: bool
    publication_id: str
    operation_id: str
    outcome: P6AdmissionOutcome
    status: str
    snapshot_id: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        validate_identifier(self.series_id, IdKind.SCHEDULE_SERIES)
        validate_identifier(self.publication_id, IdKind.SCHEDULE_PUBLICATION)
        validate_identifier(self.operation_id, IdKind.OPERATION)
        validate_identifier(self.snapshot_id, IdKind.SCHEDULE_P6_SNAPSHOT)
        if not isinstance(self.outcome, P6AdmissionOutcome):
            raise ValueError("an admission carries a closed outcome")
        if self.series_created and self.outcome is not P6AdmissionOutcome.CREATED:
            raise ValueError("only a created admission creates a series")


# ---- section 11.1: Series identity ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class P6ProjectIdentity:
    """A publication's P6 project identity: short name and GUID (either may be absent)."""

    short_name: str | None
    guid: str | None


def p6_identity_changed(
    current: P6ProjectIdentity, earlier: Iterable[P6ProjectIdentity], *, accepted: bool
) -> bool:
    """Section 11.1: `True` when no earlier P6 publication shares the short name or GUID.

    A first P6 publication of a Series has nothing to compare against and is
    never a change; `accepted` (`accept_project_identity_change`) waives it.
    """
    if accepted:
        return False
    seen = list(earlier)
    if not seen:
        return False
    for other in seen:
        if current.short_name is not None and other.short_name == current.short_name:
            return False
        if current.guid is not None and other.guid == current.guid:
            return False
    return True


# ---- section 11.3: activity matching across versions -----------------------------------


@dataclass(frozen=True, slots=True)
class P6ActivityIdentity:
    """One activity of a publication: its exact Activity ID (`task_code`) and P6 GUID."""

    activity_id: str
    guid: str | None


@dataclass(frozen=True, slots=True)
class P6RenumberCandidate:
    """Section 11.3: a hint that an Activity ID changed (shared GUID); never a link."""

    from_activity_id: str
    to_activity_id: str


@dataclass(frozen=True, slots=True)
class P6ActivityMatching:
    """Section 11.3 between two publications of one Series (`to - from`)."""

    added: tuple[str, ...]
    removed: tuple[str, ...]
    renumber_candidates: tuple[P6RenumberCandidate, ...]


def match_p6_activities(
    previous: Sequence[P6ActivityIdentity], current: Sequence[P6ActivityIdentity]
) -> P6ActivityMatching:
    """Exact `task_code` identity: a code that disappears is `removed`, one that appears
    `added`; a removed and an added activity sharing a GUID are a `renumber_candidate`.

    Renumbering is never merged (no shared Stable Activity, no history): the
    candidate is informational. A GUID shared by more than one removed or
    added activity names no candidate (nothing is guessed).
    """
    before = {item.activity_id: item for item in previous}
    after = {item.activity_id: item for item in current}
    removed = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))

    def by_guid(codes: Sequence[str], side: Mapping[str, P6ActivityIdentity]) -> dict[str, str]:
        found: dict[str, list[str]] = {}
        for code in codes:
            guid = side[code].guid
            if guid:
                found.setdefault(guid, []).append(code)
        return {guid: owners[0] for guid, owners in found.items() if len(owners) == 1}

    gone, new = by_guid(removed, before), by_guid(added, after)
    candidates = sorted(
        (P6RenumberCandidate(gone[guid], new[guid]) for guid in set(gone) & set(new)),
        key=lambda item: (item.from_activity_id, item.to_activity_id),
    )
    return P6ActivityMatching(tuple(added), tuple(removed), tuple(candidates))
