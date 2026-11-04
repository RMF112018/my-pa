"""The stored form of one general report version, as a read returns it.

A `StoredReportVersion` is only ever built from rows whose digests the reader
recomputed and found equal to the stored ones: the content's decoded digest
from its body and data, and the manifest's digest from its document.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from my_pa.domain.reports.content import ReportContent
from my_pa.domain.reports.values import ReportAssociation
from my_pa.domain.reports.vocabulary import ChangeKind, LifecycleState, StorageKind

__all__ = ["ReportRootRecord", "ReportVersionRecord", "StoredReportVersion"]


@dataclass(frozen=True, slots=True)
class ReportRootRecord:
    report_id: str
    created_at: datetime
    head_version_id: str
    head_version_number: int
    lifecycle_state: LifecycleState
    lifecycle_revision: int


@dataclass(frozen=True, slots=True)
class ReportVersionRecord:
    version_id: str
    report_id: str
    version_number: int
    supersedes_version_id: str | None
    change_kind: ChangeKind
    title: str
    report_type: str | None
    topics: tuple[str, ...]
    tags: tuple[str, ...]
    summary: str | None
    report_date: date | None
    coverage_start: datetime | None
    coverage_end: datetime | None
    metadata: Mapping[str, Any]
    change_reason: str | None
    content_id: str
    manifest_sha256: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class StoredReportVersion:
    root: ReportRootRecord
    version: ReportVersionRecord
    content_id: str
    storage_kind: StorageKind
    content: ReportContent
    manifest: Mapping[str, Any]
    associations: tuple[ReportAssociation, ...]
