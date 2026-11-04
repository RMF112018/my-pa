"""Revising a general report: the patch, the update and lifecycle requests, their results.

WP03 contract B (decisions D4, D5, D7, D8). Pure and stdlib only.

**Patch semantics (D4).** A `ReportPatch` holds the caller fields of one
`reports.update`; a field left `None` is *absent* and keeps the head's value, a
present field *replaces* the whole value (no deep merge: `topics`, `tags`,
`associations` and `metadata` are replaced wholesale, and an empty one clears
it). A JSON null never reaches this type: the transport refuses it, and a
nullable field is cleared only through `clear_fields` (`type`, `summary`,
`report_date`, `coverage_period`). A field may not be both patched and cleared,
and a request must patch or clear something.

**Change kind (D5).** `apply_patch` is the whole rule. New content whose
format, encoding and decoded digest differ from the head's makes a `content`
change; content absent from the patch, or present and equal to the head's by
those three, keeps the head's content object (so persistence reuses its
`content_id`) and the change is `metadata`. When the resulting snapshot equals
the head snapshot the answer is `None`: a no-op, which writes a receipt and no
version. `change_reason` is not part of the snapshot, so a reason alone never
makes a change.

**Intent digests (D8).** The SHA-256 of the canonical JSON of the normalized
caller payload, never a server field: an update's report, expected version,
normalized patch (present keys only), sorted `clear_fields` and reason; a
lifecycle request's operation, report, expected revision and reason.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Final

from my_pa.domain.reports.content import ReportContent, canonical_json
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.publication import (
    PublicationRequest,
    RequestedAssociation,
    aware_timestamp,
    content_payload,
    format_timestamp,
)
from my_pa.domain.reports.values import (
    ReportAssociation,
    validate_associations,
    validate_change_reason,
    validate_metadata,
    validate_summary,
    validate_tags,
    validate_title,
    validate_topics,
    validate_type_token,
)
from my_pa.domain.reports.vocabulary import (
    AssociationVerification,
    ChangeKind,
    LifecycleOperation,
    LifecycleState,
    ReceiptOutcome,
)

__all__ = [
    "PATCH_FIELDS",
    "ClearableField",
    "CoveragePeriod",
    "LifecycleRequest",
    "LifecycleResult",
    "ReportPatch",
    "ReportSnapshot",
    "UpdateRequest",
    "UpdateResult",
    "apply_patch",
    "snapshot_of_publication",
    "snapshot_of_version",
    "validate_clear_fields",
]

#: The wire names a patch may carry: the publish caller fields minus `client_intent_id`.
PATCH_FIELDS: Final = (
    "title",
    "content",
    "type",
    "topics",
    "tags",
    "summary",
    "report_date",
    "coverage_period",
    "metadata",
    "associations",
)


class ClearableField(StrEnum):
    """A nullable field `clear_fields` may set to null, by its wire name."""

    TYPE = "type"
    SUMMARY = "summary"
    REPORT_DATE = "report_date"
    COVERAGE_PERIOD = "coverage_period"


def validate_clear_fields(value: object) -> frozenset[ClearableField]:
    """A caller's `clear_fields` list: known names, none twice."""
    if value is None:
        return frozenset()
    if isinstance(value, str | bytes | Mapping) or not isinstance(value, Iterable):
        raise ReportValidationError("clear_fields", "type")
    accepted: set[ClearableField] = set()
    for entry in value:
        if isinstance(entry, ClearableField):
            name = entry
        elif type(entry) is str:
            try:
                name = ClearableField(entry)
            except ValueError:
                raise ReportValidationError("clear_fields", "unknown") from None
        else:
            raise ReportValidationError("clear_fields", "type")
        if name in accepted:
            raise ReportValidationError("clear_fields", "duplicate")
        accepted.add(name)
    return frozenset(accepted)


@dataclass(frozen=True, slots=True)
class CoveragePeriod:
    """A patched coverage period: aware, ordered, at least one bound."""

    start: datetime | None = None
    end: datetime | None = None

    def __post_init__(self) -> None:
        start = aware_timestamp(self.start, "coverage_start")
        end = aware_timestamp(self.end, "coverage_end")
        if start is None and end is None:
            raise ReportValidationError("coverage_period", "empty")
        if start is not None and end is not None and start > end:
            raise ReportValidationError("coverage_period", "order")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)


def _coverage_payload(start: datetime | None, end: datetime | None) -> dict[str, Any] | None:
    if start is None and end is None:
        return None
    return {
        "start": None if start is None else format_timestamp(start),
        "end": None if end is None else format_timestamp(end),
    }


def _association_payload(item: RequestedAssociation) -> dict[str, Any]:
    return {
        "target_kind": item.target_kind.value,
        "target_ref": item.target_ref,
        "relation": item.relation,
        "target_version_ref": item.target_version_ref,
    }


def _requested(associations: object) -> tuple[RequestedAssociation, ...]:
    if not isinstance(associations, tuple | list) or any(
        not isinstance(item, RequestedAssociation) for item in associations
    ):
        raise ReportValidationError("associations", "type")
    validate_associations(
        [item.as_stored(AssociationVerification.ASSERTED) for item in associations]
    )
    return tuple(associations)


def _report_date(value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ReportValidationError("report_date", "type")
    return value


@dataclass(frozen=True, slots=True)
class ReportPatch:
    """The present fields of one update, each validated as publish validates it.

    `None` means absent. `report_type` is the wire field `type`.
    """

    title: str | None = None
    content: ReportContent | None = None
    report_type: str | None = None
    topics: tuple[str, ...] | None = None
    tags: tuple[str, ...] | None = None
    summary: str | None = None
    report_date: date | None = None
    coverage_period: CoveragePeriod | None = None
    metadata: Mapping[str, Any] | None = field(default=None, repr=False)
    associations: tuple[RequestedAssociation, ...] | None = None

    def __post_init__(self) -> None:
        def put(name: str, value: object) -> None:
            object.__setattr__(self, name, value)

        if self.title is not None:
            put("title", validate_title(self.title))
        if self.content is not None and not isinstance(self.content, ReportContent):
            raise ReportValidationError("content", "type")
        if self.report_type is not None:
            put("report_type", validate_type_token(self.report_type))
        if self.topics is not None:
            put("topics", validate_topics(self.topics))
        if self.tags is not None:
            put("tags", validate_tags(self.tags))
        if self.summary is not None:
            put("summary", validate_summary(self.summary))
        if self.report_date is not None:
            put("report_date", _report_date(self.report_date))
        if self.coverage_period is not None and not isinstance(
            self.coverage_period, CoveragePeriod
        ):
            raise ReportValidationError("coverage_period", "type")
        if self.metadata is not None:
            put("metadata", validate_metadata(self.metadata))
        if self.associations is not None:
            put("associations", _requested(self.associations))

    @property
    def present(self) -> frozenset[str]:
        """The wire names of the fields this patch carries."""
        names = {
            "title": self.title,
            "content": self.content,
            "type": self.report_type,
            "topics": self.topics,
            "tags": self.tags,
            "summary": self.summary,
            "report_date": self.report_date,
            "coverage_period": self.coverage_period,
            "metadata": self.metadata,
            "associations": self.associations,
        }
        return frozenset(name for name, value in names.items() if value is not None)

    def payload(self) -> dict[str, Any]:
        """The normalized patch an intent digest names: present keys only, wire names."""
        payload: dict[str, Any] = {}
        if self.title is not None:
            payload["title"] = self.title
        if self.content is not None:
            payload["content"] = content_payload(self.content)
        if self.report_type is not None:
            payload["type"] = self.report_type
        if self.topics is not None:
            payload["topics"] = list(self.topics)
        if self.tags is not None:
            payload["tags"] = list(self.tags)
        if self.summary is not None:
            payload["summary"] = self.summary
        if self.report_date is not None:
            payload["report_date"] = self.report_date.isoformat()
        if self.coverage_period is not None:
            payload["coverage_period"] = _coverage_payload(
                self.coverage_period.start, self.coverage_period.end
            )
        if self.metadata is not None:
            payload["metadata"] = dict(self.metadata)
        if self.associations is not None:
            payload["associations"] = [_association_payload(item) for item in self.associations]
        return payload


@dataclass(frozen=True, slots=True)
class ReportSnapshot:
    """Every field one version holds, as `apply_patch` compares and replaces them.

    `associations` are in the caller-stated form: the server re-derives their
    verification when it stores them, so two snapshots that differ only in a
    verification the server would decide again are the same snapshot.
    """

    title: str
    content: ReportContent
    report_type: str | None = None
    topics: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    summary: str | None = None
    report_date: date | None = None
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    associations: tuple[RequestedAssociation, ...] = ()

    @property
    def content_key(self) -> tuple[str, str, str]:
        """What makes two content values the same content (D5)."""
        return (
            self.content.format.value,
            self.content.encoding.value,
            self.content.decoded_sha256,
        )

    def document(self) -> dict[str, Any]:
        """The canonical comparison form: content by its key, numbers by their digits."""
        return {
            "title": self.title,
            "content": list(self.content_key),
            "report_type": self.report_type,
            "topics": list(self.topics),
            "tags": list(self.tags),
            "summary": self.summary,
            "report_date": None if self.report_date is None else self.report_date.isoformat(),
            "coverage_period": _coverage_payload(self.coverage_start, self.coverage_end),
            "metadata": dict(self.metadata),
            "associations": [_association_payload(item) for item in self.associations],
        }


def _requested_form(item: ReportAssociation) -> RequestedAssociation:
    return RequestedAssociation(
        target_kind=item.target_kind,
        target_ref=item.target_ref,
        relation=item.relation,
        target_version_ref=item.target_version_ref,
    )


def snapshot_of_version(
    *,
    title: str,
    content: ReportContent,
    report_type: str | None,
    topics: Sequence[str],
    tags: Sequence[str],
    summary: str | None,
    report_date: date | None,
    coverage_start: datetime | None,
    coverage_end: datetime | None,
    metadata: Mapping[str, Any],
    associations: Sequence[ReportAssociation],
) -> ReportSnapshot:
    """The snapshot of a stored version (its record's fields, content and associations)."""
    return ReportSnapshot(
        title=title,
        content=content,
        report_type=report_type,
        topics=tuple(topics),
        tags=tuple(tags),
        summary=summary,
        report_date=report_date,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        metadata=dict(metadata),
        associations=tuple(_requested_form(item) for item in associations),
    )


def snapshot_of_publication(request: PublicationRequest) -> ReportSnapshot:
    """The snapshot a publish writes as version 1."""
    return ReportSnapshot(
        title=request.title,
        content=request.content,
        report_type=request.report_type,
        topics=request.topics,
        tags=request.tags,
        summary=request.summary,
        report_date=request.report_date,
        coverage_start=request.coverage_start,
        coverage_end=request.coverage_end,
        metadata=dict(request.metadata),
        associations=request.associations,
    )


def _check_patch_and_clear(patch: object, clear_fields: object) -> None:
    """Typed as `object`: a transport hands both in unchecked."""
    if not isinstance(patch, ReportPatch):
        raise ReportValidationError("patch", "type")
    if not isinstance(clear_fields, frozenset) or any(
        not isinstance(name, ClearableField) for name in clear_fields
    ):
        raise ReportValidationError("clear_fields", "type")
    if not patch.present and not clear_fields:
        raise ReportValidationError("patch", "empty")
    if patch.present & {name.value for name in clear_fields}:
        raise ReportValidationError("clear_fields", "conflict")


def apply_patch(
    head: ReportSnapshot,
    patch: ReportPatch,
    clear_fields: frozenset[ClearableField] = frozenset(),
) -> tuple[ReportSnapshot, ChangeKind | None]:
    """The snapshot `patch` and `clear_fields` make of `head`, and the change kind.

    `None` for the kind means the result equals `head` (a no-op); the snapshot
    returned is then `head` itself. Content equal to the head's by format,
    encoding and decoded digest keeps the head's content value.
    """
    _check_patch_and_clear(patch, clear_fields)
    changes: dict[str, Any] = {}
    if patch.title is not None:
        changes["title"] = patch.title
    if patch.content is not None:
        candidate = replace(head, content=patch.content)
        changes["content"] = (
            head.content if candidate.content_key == head.content_key else patch.content
        )
    if patch.report_type is not None:
        changes["report_type"] = patch.report_type
    if patch.topics is not None:
        changes["topics"] = patch.topics
    if patch.tags is not None:
        changes["tags"] = patch.tags
    if patch.summary is not None:
        changes["summary"] = patch.summary
    if patch.report_date is not None:
        changes["report_date"] = patch.report_date
    if patch.coverage_period is not None:
        changes["coverage_start"] = patch.coverage_period.start
        changes["coverage_end"] = patch.coverage_period.end
    if patch.metadata is not None:
        changes["metadata"] = dict(patch.metadata)
    if patch.associations is not None:
        changes["associations"] = patch.associations
    for name in clear_fields:
        if name is ClearableField.TYPE:
            changes["report_type"] = None
        elif name is ClearableField.SUMMARY:
            changes["summary"] = None
        elif name is ClearableField.REPORT_DATE:
            changes["report_date"] = None
        else:
            changes["coverage_start"] = None
            changes["coverage_end"] = None
    result = replace(head, **changes)
    if canonical_json(result.document()) == canonical_json(head.document()):
        return head, None
    if result.content_key != head.content_key:
        return result, ChangeKind.CONTENT
    return result, ChangeKind.METADATA


def _report_id(value: object) -> str:
    if type(value) is not str or not value:
        raise ReportValidationError("report_id", "type")
    return value


def _count(value: object, field_name: str, minimum: int) -> int:
    if type(value) is not int:
        raise ReportValidationError(field_name, "type")
    if value < minimum:
        raise ReportValidationError(field_name, "too_small")
    return value


@dataclass(frozen=True, slots=True)
class UpdateRequest:
    """Every caller field of one `reports.update`, validated on construction."""

    report_id: str
    expected_version: int
    patch: ReportPatch
    clear_fields: frozenset[ClearableField] = frozenset()
    change_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "report_id", _report_id(self.report_id))
        _count(self.expected_version, "expected_version", 1)
        _check_patch_and_clear(self.patch, self.clear_fields)
        if self.change_reason is None:
            raise ReportValidationError("change_reason", "required")
        validate_change_reason(self.change_reason)

    @property
    def intent_digest(self) -> str:
        """SHA-256 of the canonical JSON of the normalized caller payload (D8)."""
        payload = {
            "report_id": self.report_id,
            "expected_version": self.expected_version,
            "patch": self.patch.payload(),
            "clear_fields": sorted(name.value for name in self.clear_fields),
            "change_reason": self.change_reason,
        }
        return hashlib.sha256(canonical_json(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class LifecycleRequest:
    """Every caller field of one `reports.archive`, `reports.delete` or `reports.restore`."""

    operation: LifecycleOperation
    report_id: str
    expected_lifecycle_revision: int
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation, LifecycleOperation):
            raise ReportValidationError("lifecycle_operation", "type")
        object.__setattr__(self, "report_id", _report_id(self.report_id))
        _count(self.expected_lifecycle_revision, "expected_lifecycle_revision", 0)
        validate_change_reason(self.reason, "reason")

    @property
    def intent_digest(self) -> str:
        """SHA-256 of the canonical JSON of the normalized caller payload (D8)."""
        payload = {
            "operation": self.operation.value,
            "report_id": self.report_id,
            "expected_lifecycle_revision": self.expected_lifecycle_revision,
            "reason": self.reason,
        }
        return hashlib.sha256(canonical_json(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class UpdateResult:
    """What an update answers, rebuilt from the stored receipt on every replay.

    An `applied` result names the new version and its `change_kind`; a `no_op`
    names the head version it found at `expected_version` and has no kind.
    """

    receipt_id: str
    report_id: str
    outcome: ReceiptOutcome
    expected_version: int
    version_id: str
    version_number: int
    change_kind: ChangeKind | None
    content_id: str
    decoded_sha256: str
    manifest_sha256: str
    idempotency_key: str
    intent_digest: str
    issued_at: datetime
    correlation_id: str
    audit_id: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    """What an archive, delete or restore answers, the first time and on every replay.

    `lifecycle_revision` is the resulting revision (the expected one for a
    no-op); `event_id` is the event written, or for a no-op the current event
    when it is an archive, else `None`.
    """

    receipt_id: str
    report_id: str
    operation: LifecycleOperation
    outcome: ReceiptOutcome
    prior_state: LifecycleState
    resulting_state: LifecycleState
    expected_lifecycle_revision: int
    lifecycle_revision: int
    event_id: str | None
    idempotency_key: str
    intent_digest: str
    issued_at: datetime
    correlation_id: str
    audit_id: str
    replayed: bool
