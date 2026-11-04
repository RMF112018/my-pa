"""The version manifest: a deterministic, principal-free description of one version.

`build_initial_manifest` assembles the manifest of a report's first version
(contract B2) and returns its canonical bytes and their SHA-256. The canonical
bytes are bounded at `MAX_MANIFEST_CANONICAL_BYTES` (43690, `65536 / 1.5`): the
WP01 argument for metadata shows jsonb text is at most 1.5 times the canonical
bytes, so every accepted manifest fits the stored `manifest::text` bound of
65536. The manifest names no owner.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from my_pa.domain.reports.content import canonical_json
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.publication import PublicationRequest, format_timestamp
from my_pa.domain.reports.values import ReportAssociation
from my_pa.domain.reports.vocabulary import MANIFEST_SCHEMA, ChangeKind, StorageKind

__all__ = [
    "MAX_MANIFEST_CANONICAL_BYTES",
    "ReportManifest",
    "build_initial_manifest",
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


def build_initial_manifest(
    request: PublicationRequest,
    *,
    report_id: str,
    version_id: str,
    content_id: str,
    associations: Sequence[ReportAssociation],
    recorded_at: datetime,
) -> ReportManifest:
    """The manifest of version 1, or `manifest_too_large`.

    `associations` are the stored forms, in ordinal order, with the
    verification the server decided.
    """
    content = request.content
    document: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "report_id": report_id,
        "version_id": version_id,
        "version_number": 1,
        "supersedes_version_id": None,
        "change_kind": ChangeKind.INITIAL.value,
        "title": request.title,
        "report_type": request.report_type,
        "topics": list(request.topics),
        "tags": list(request.tags),
        "summary": request.summary,
        "report_date": None if request.report_date is None else request.report_date.isoformat(),
        "coverage_start": None
        if request.coverage_start is None
        else format_timestamp(request.coverage_start),
        "coverage_end": None
        if request.coverage_end is None
        else format_timestamp(request.coverage_end),
        "metadata": dict(request.metadata),
        "content": {
            "content_id": content_id,
            "format": content.format.value,
            "encoding": content.encoding.value,
            "storage_kind": StorageKind.INLINE.value,
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
