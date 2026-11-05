"""The publication of a general report: the request, its intent digest, its receipt.

`PublicationRequest` holds every caller field of `reports.publish`, validated
and normalized on construction, and nothing the server derives (owner,
identifiers, timestamps, verification, digests). Its `intent_digest` is the
SHA-256 of the canonical JSON of that normalized payload, `client_intent_id`
included (contract B3), so a replayed request is recognised by value and two
requests that differ only in `client_intent_id` are two intents.

`PublicationReceipt` and `PublicationResult` are what a publish returns, the
first time and on every replay of the same key and digest.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Final

from my_pa.domain.reports.content import ReportContent, canonical_json
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.values import (
    ReportAssociation,
    validate_associations,
    validate_metadata,
    validate_summary,
    validate_tags,
    validate_title,
    validate_topics,
    validate_type_token,
)
from my_pa.domain.reports.vocabulary import (
    AssociationTargetKind,
    AssociationVerification,
    ContentFormat,
    ReceiptOutcome,
)

__all__ = [
    "CLIENT_INTENT_ID_PATTERN",
    "PublicationReceipt",
    "PublicationRequest",
    "PublicationResult",
    "RequestedAssociation",
    "aware_timestamp",
    "content_payload",
    "format_timestamp",
    "validate_client_intent_id",
]

#: An optional caller token that makes an otherwise identical request a new intent.
CLIENT_INTENT_ID_PATTERN: Final = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def validate_client_intent_id(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ReportValidationError("client_intent_id", "type")
    if not CLIENT_INTENT_ID_PATTERN.fullmatch(value):
        raise ReportValidationError("client_intent_id", "pattern")
    return value


def content_payload(content: ReportContent) -> dict[str, object]:
    """A content value as an intent digest names it: format, encoding, body and/or data."""
    payload: dict[str, object] = {
        "format": content.format.value,
        "encoding": content.encoding.value,
    }
    if content.format is not ContentFormat.JSON:
        payload["body"] = content.body
    if content.format in (ContentFormat.JSON, ContentFormat.MIXED):
        payload["data"] = content.data
    if content.original is not None:
        # WP05: a gzip upload is named by its exact bytes too, so a retry with
        # the same `encoded` replays and another stream under the key
        # conflicts. Identity payloads (and their digests) are unchanged.
        payload["original_sha256"] = content.original_sha256
    return payload


def format_timestamp(value: datetime) -> str:
    """RFC 3339 in UTC with microseconds and a `Z` suffix, the manifest's form."""
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def aware_timestamp(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ReportValidationError(field_name, "type")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ReportValidationError(field_name, "naive")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class RequestedAssociation:
    """One association as the caller states it; the server decides its verification."""

    target_kind: AssociationTargetKind
    target_ref: str
    relation: str
    target_version_ref: str | None = None

    def __post_init__(self) -> None:
        # The shared validator of the stored form checks every field this one has.
        self.as_stored(AssociationVerification.ASSERTED)

    def as_stored(self, verification: AssociationVerification) -> ReportAssociation:
        return ReportAssociation(
            target_kind=self.target_kind,
            target_ref=self.target_ref,
            relation=self.relation,
            verification=verification,
            target_version_ref=self.target_version_ref,
        )


@dataclass(frozen=True, slots=True)
class PublicationRequest:
    """Every caller field of one publish, validated and normalized on construction."""

    title: str
    content: ReportContent
    report_type: str | None = None
    topics: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    summary: str | None = None
    report_date: date | None = None
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    associations: tuple[RequestedAssociation, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    client_intent_id: str | None = None

    def __post_init__(self) -> None:
        def put(name: str, value: object) -> None:
            object.__setattr__(self, name, value)

        put("title", validate_title(self.title))
        if not isinstance(self.content, ReportContent):
            raise ReportValidationError("content", "type")
        if self.report_type is not None:
            put("report_type", validate_type_token(self.report_type))
        put("topics", validate_topics(self.topics))
        put("tags", validate_tags(self.tags))
        put("summary", validate_summary(self.summary))
        if self.report_date is not None and (
            isinstance(self.report_date, datetime) or not isinstance(self.report_date, date)
        ):
            raise ReportValidationError("report_date", "type")
        start = aware_timestamp(self.coverage_start, "coverage_start")
        end = aware_timestamp(self.coverage_end, "coverage_end")
        if start is not None and end is not None and start > end:
            raise ReportValidationError("coverage_period", "order")
        put("coverage_start", start)
        put("coverage_end", end)
        # Typed as `object`: a transport hands this field in unchecked.
        requested: object = self.associations
        if not isinstance(requested, tuple | list) or any(
            not isinstance(item, RequestedAssociation) for item in requested
        ):
            raise ReportValidationError("associations", "type")
        validate_associations(
            [item.as_stored(AssociationVerification.ASSERTED) for item in requested]
        )
        put("associations", tuple(requested))
        put("metadata", validate_metadata(self.metadata))
        put("client_intent_id", validate_client_intent_id(self.client_intent_id))

    @property
    def intent_digest(self) -> str:
        """SHA-256 of the canonical JSON of the normalized caller payload."""
        coverage = (
            None
            if self.coverage_start is None and self.coverage_end is None
            else {
                "start": None
                if self.coverage_start is None
                else format_timestamp(self.coverage_start),
                "end": None if self.coverage_end is None else format_timestamp(self.coverage_end),
            }
        )
        payload = {
            "title": self.title,
            "content": content_payload(self.content),
            "report_type": self.report_type,
            "topics": list(self.topics),
            "tags": list(self.tags),
            "summary": self.summary,
            "report_date": None if self.report_date is None else self.report_date.isoformat(),
            "coverage_period": coverage,
            "associations": [
                {
                    "target_kind": item.target_kind.value,
                    "target_ref": item.target_ref,
                    "relation": item.relation,
                    "target_version_ref": item.target_version_ref,
                }
                for item in self.associations
            ],
            "metadata": dict(self.metadata),
            "client_intent_id": self.client_intent_id,
        }
        return hashlib.sha256(canonical_json(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    """The stored `publish` receipt: one applied write of version 1."""

    receipt_id: str
    report_id: str
    version_id: str
    version_number: int
    idempotency_key: str
    intent_digest: str
    outcome: ReceiptOutcome
    issued_at: datetime
    correlation_id: str
    audit_id: str


@dataclass(frozen=True, slots=True)
class PublicationResult:
    """What a publish answers, rebuilt from the stored rows on every replay.

    `replayed` is `False` only for the call that wrote the rows.
    """

    receipt: PublicationReceipt
    content_id: str
    format: ContentFormat
    decoded_sha256: str
    decoded_byte_count: int
    canonical_sha256: str | None
    manifest_sha256: str
    recorded_at: datetime
    replayed: bool
