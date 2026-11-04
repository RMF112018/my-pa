"""The version manifest: a deterministic, principal-free description of one version.

`build_version_manifest` assembles the manifest of any version (contract B2,
generalized by WP03 D10 with a `change_reason` key, null for version 1) and
returns its canonical bytes and their SHA-256; `build_initial_manifest` is
that builder over a publish request. The canonical
bytes are bounded at `MAX_MANIFEST_CANONICAL_BYTES` (43690, `65536 / 1.5`): the
WP01 argument for metadata shows jsonb text is at most 1.5 times the canonical
bytes, so every accepted manifest fits the stored `manifest::text` bound of
65536. The manifest names no owner.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final

from my_pa.domain.reports.content import ReportContent, canonical_json
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.publication import PublicationRequest, format_timestamp
from my_pa.domain.reports.values import ReportAssociation
from my_pa.domain.reports.vocabulary import MANIFEST_SCHEMA, ChangeKind, StorageKind

__all__ = [
    "MAX_MANIFEST_CANONICAL_BYTES",
    "ReportManifest",
    "build_initial_manifest",
    "build_version_manifest",
    "manifest_digest",
]

MAX_MANIFEST_CANONICAL_BYTES: Final = 43690


def manifest_digest(document: Mapping[str, Any]) -> str:
    """SHA-256 of a manifest's canonical bytes, for writing and for verifying."""
    return hashlib.sha256(canonical_json(document)).hexdigest()


@dataclass(frozen=True, slots=True)
class ReportManifest:
    document: Mapping[str, Any]
    canonical: bytes
    sha256: str


def build_version_manifest(
    *,
    report_id: str,
    version_id: str,
    version_number: int,
    supersedes_version_id: str | None,
    change_kind: ChangeKind,
    change_reason: str | None,
    title: str,
    report_type: str | None,
    topics: Sequence[str],
    tags: Sequence[str],
    summary: str | None,
    report_date: date | None,
    coverage_start: datetime | None,
    coverage_end: datetime | None,
    metadata: Mapping[str, Any],
    content: ReportContent,
    content_id: str,
    associations: Sequence[ReportAssociation],
    recorded_at: datetime,
    storage_kind: StorageKind = StorageKind.INLINE,
) -> ReportManifest:
    """The manifest of any version, or `manifest_too_large`.

    The one builder every writer and every reader uses: a publish (version 1,
    `initial`, no predecessor, `change_reason` null), an update (version N+1)
    and the read paths, which rebuild the whole expected document from the
    stored version, content and association rows and require it to equal the
    stored one canonically. `associations` are the stored forms, in ordinal
    order, with the verification the server decided.
    """
    document: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "report_id": report_id,
        "version_id": version_id,
        "version_number": version_number,
        "supersedes_version_id": supersedes_version_id,
        "change_kind": change_kind.value,
        "change_reason": change_reason,
        "title": title,
        "report_type": report_type,
        "topics": list(topics),
        "tags": list(tags),
        "summary": summary,
        "report_date": None if report_date is None else report_date.isoformat(),
        "coverage_start": None if coverage_start is None else format_timestamp(coverage_start),
        "coverage_end": None if coverage_end is None else format_timestamp(coverage_end),
        "metadata": dict(metadata),
        "content": {
            "content_id": content_id,
            "format": content.format.value,
            "encoding": content.encoding.value,
            "storage_kind": storage_kind.value,
            "decoded_sha256": content.decoded_sha256,
            "decoded_byte_count": content.decoded_byte_count,
            "canonical_sha256": content.canonical_sha256,
            "original_sha256": content.original_sha256,
            "original_byte_count": content.original_byte_count,
        },
        "associations": [
            {
                "ordinal": ordinal,
                "target_kind": item.target_kind.value,
                "target_ref": item.target_ref,
                "target_version_ref": item.target_version_ref,
                "relation": item.relation,
                "verification": item.verification.value,
            }
            for ordinal, item in enumerate(associations)
        ],
        "recorded_at": format_timestamp(recorded_at),
    }
    canonical = canonical_json(document)
    if len(canonical) > MAX_MANIFEST_CANONICAL_BYTES:
        raise ReportValidationError("manifest", "manifest_too_large")
    return ReportManifest(
        document=document, canonical=canonical, sha256=hashlib.sha256(canonical).hexdigest()
    )


def build_initial_manifest(
    request: PublicationRequest,
    *,
    report_id: str,
    version_id: str,
    content_id: str,
    associations: Sequence[ReportAssociation],
    recorded_at: datetime,
) -> ReportManifest:
    """The manifest of version 1: `build_version_manifest` over a publish request."""
    return build_version_manifest(
        report_id=report_id,
        version_id=version_id,
        version_number=1,
        supersedes_version_id=None,
        change_kind=ChangeKind.INITIAL,
        change_reason=None,
        title=request.title,
        report_type=request.report_type,
        topics=request.topics,
        tags=request.tags,
        summary=request.summary,
        report_date=request.report_date,
        coverage_start=request.coverage_start,
        coverage_end=request.coverage_end,
        metadata=request.metadata,
        content=request.content,
        content_id=content_id,
        associations=associations,
        recorded_at=recorded_at,
    )
