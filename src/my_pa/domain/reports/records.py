"""The stored form of one general report version, as a read returns it, and its history.

A `StoredReportVersion` is only ever built from rows whose digests the reader
recomputed and found equal to the stored ones: the content's decoded digest
from its body and data, and the manifest's digest from its document, which is
also rebuilt whole from the stored rows and compared canonically.

`ReportHistoryPage` is one page of a report's version or lifecycle ledger,
oldest first (WP03 D9): `next_cursor` is the id of the page's last item when
more follow, else `None`.

`CatalogEntry` is one standalone report as the catalog lists it (WP04 C4): the
root and its HEAD version's metadata, never content.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Final

from my_pa.domain.reports.content import ReportContent
from my_pa.domain.reports.creator import ReportCreator
from my_pa.domain.reports.values import ReportAssociation
from my_pa.domain.reports.vocabulary import (
    ChangeKind,
    ContentEncoding,
    ContentFormat,
    LifecycleOperation,
    LifecycleState,
    StorageKind,
)

__all__ = [
    "DEFAULT_HISTORY_PAGE",
    "MAX_HISTORY_PAGE",
    "MAX_HISTORY_PAGE_WITH_MANIFESTS",
    "CatalogEntry",
    "HistoryEntries",
    "ReportHistoryPage",
    "ReportLifecycleEventRecord",
    "ReportRootRecord",
    "ReportVersionRecord",
    "ReportVersionSummary",
    "StoredReportVersion",
]

#: History page sizes (D9): 1..50 items, 20 by default, at most 10 with manifests.
DEFAULT_HISTORY_PAGE: Final = 20
MAX_HISTORY_PAGE: Final = 50
MAX_HISTORY_PAGE_WITH_MANIFESTS: Final = 10


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One standalone report at its HEAD version, as a catalog page lists it.

    `created_at` is the root's (the list order's sort time, immutable);
    `updated_at` is the head version's `recorded_at`. `rank` is the integer
    search rank `floor(ts_rank(search_document, q) * 1e6)` and `snippet` the
    headline over the summary (else the title), both `None` in a list.
    """

    report_id: str
    title: str
    report_type: str | None
    topics: tuple[str, ...]
    tags: tuple[str, ...]
    summary: str | None
    report_date: date | None
    lifecycle_state: LifecycleState
    lifecycle_revision: int
    head_version_id: str
    head_version_number: int
    created_at: datetime
    updated_at: datetime
    rank: int | None
    snippet: str | None
    #: WP05 A4: the root's creator (who published the report).
    creator: ReportCreator


@dataclass(frozen=True, slots=True)
class ReportRootRecord:
    report_id: str
    created_at: datetime
    head_version_id: str
    head_version_number: int
    lifecycle_state: LifecycleState
    lifecycle_revision: int
    #: WP05 A2: who published the report; immutable, equal to version 1's author.
    creator: ReportCreator


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
    #: WP05 A2: who wrote this version (the publisher for version 1).
    author: ReportCreator


@dataclass(frozen=True, slots=True)
class StoredReportVersion:
    root: ReportRootRecord
    version: ReportVersionRecord
    content_id: str
    storage_kind: StorageKind
    content: ReportContent
    manifest: Mapping[str, Any]
    associations: tuple[ReportAssociation, ...]


class HistoryEntries(StrEnum):
    """Which ledger a history page walks."""

    VERSIONS = "versions"
    LIFECYCLE = "lifecycle"


@dataclass(frozen=True, slots=True)
class ReportVersionSummary:
    """One version as a history page lists it: no body, the manifest only on request."""

    version_id: str
    version_number: int
    supersedes_version_id: str | None
    change_kind: ChangeKind
    change_reason: str | None
    title: str
    recorded_at: datetime
    content_id: str
    format: ContentFormat
    encoding: ContentEncoding
    storage_kind: StorageKind
    decoded_sha256: str
    decoded_byte_count: int
    canonical_sha256: str | None
    original_sha256: str
    manifest_sha256: str
    manifest: Mapping[str, Any] | None
    #: WP05 A4: who wrote this version.
    author: ReportCreator


@dataclass(frozen=True, slots=True)
class ReportLifecycleEventRecord:
    event_id: str
    lifecycle_revision: int
    operation: LifecycleOperation
    prior_state: LifecycleState
    resulting_state: LifecycleState
    reason: str | None
    transitioned_at: datetime


@dataclass(frozen=True, slots=True)
class ReportHistoryPage[ItemT: (ReportVersionSummary, ReportLifecycleEventRecord)]:
    """One page: `ReportVersionSummary` items for versions, events for lifecycle."""

    root: ReportRootRecord
    entries: HistoryEntries
    items: tuple[ItemT, ...]
    next_cursor: str | None
