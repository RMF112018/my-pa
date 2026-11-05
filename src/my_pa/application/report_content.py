"""Reconcile, back up and restore the report content store (Reports Modernization WP05 C7).

The report content store holds the parts of every `managed_blob` content row
(`infrastructure.report_content_stores`). The filesystem and the database are
not one transaction: the repository writes an object *before* the first INSERT
of its request (C4), so the failure that can survive is an object no row names
-- an orphan -- and never a row naming absent bytes, short of the store being
damaged afterwards. These operations find both, mirroring
`ManagedDocumentService.verify`/`back_up`/`restore_from_backup`:

* `scan_report_content` checks, for one Principal, every `managed_blob` row's
  parts against the store (size and SHA-256 of the decoded part, and of the
  original for a `gzip+base64` upload), and, across Principals, every stored
  object against the set of known `managed_blob` content ids (orphans), plus
  the store's own unreadable entries. It reports and never repairs, deletes or
  reclaims anything: an orphan may be an object whose transaction has not
  committed yet, and destroying bytes is the operator's act (`AGENTS.md` 8.2).
* `back_up_report_content` copies one Principal's objects, each part read
  *verified against its row*, into a second store -- a `ReportContentStore`
  with the same containment, never an arbitrary directory -- whose `put`
  re-reads and verifies what it wrote. An object already in the destination
  is verified there instead of copied.
* `restore_report_content` is the same copy from a backup store into the live
  one, for the rows the (separately restored, e.g. `pg_restore`d) database
  holds.

Library only, with an operator command (`apps/cli/report_content.py`) in the
shape of `apps/cli/managed_documents.py`; no capability. Nothing here returns a
body, a path or a digest value -- identifiers, parts and counts only.
"""

from __future__ import annotations

from dataclasses import dataclass

from my_pa.contracts.ports import (
    GeneralReportRepository,
    ReportContentIntegrityError,
    ReportContentMissingError,
    ReportContentPart,
    ReportContentStore,
    ReportContentStoreError,
)
from my_pa.domain.reports.records import ManagedContentRecord
from my_pa.domain.reports.vocabulary import ContentEncoding

__all__ = [
    "ReportContentCopySummary",
    "ReportContentMismatch",
    "ReportContentScan",
    "back_up_report_content",
    "restore_report_content",
    "scan_report_content",
]


@dataclass(frozen=True, slots=True)
class ReportContentMismatch:
    """One stored part whose size or digest is not its row's."""

    content_id: str
    part: ReportContentPart
    #: `"size"` or `"digest"`.
    mismatch: str


@dataclass(frozen=True, slots=True)
class ReportContentScan:
    """What one reconciliation scan found. Identifiers and counts only."""

    #: `managed_blob` content rows of the Principal whose parts were checked.
    checked: int
    #: `(content id, part)` of every part a row names that the store lacks.
    missing: tuple[tuple[str, ReportContentPart], ...]
    mismatched: tuple[ReportContentMismatch, ...]
    #: Stored object ids that no `managed_blob` row of any Principal names.
    orphans: tuple[str, ...]
    #: Store entries that are not well-formed objects, relative to its root.
    unreadable: tuple[str, ...]

    @property
    def consistent(self) -> bool:
        return not (self.missing or self.mismatched or self.orphans or self.unreadable)


@dataclass(frozen=True, slots=True)
class ReportContentCopySummary:
    """What one backup or restore did."""

    objects: int
    copied: int
    already_present: int
    bytes_copied: int


def _parts(record: ManagedContentRecord) -> tuple[tuple[ReportContentPart, str, int], ...]:
    """The parts a row names, each with its expected digest and size."""
    parts = [(ReportContentPart.DECODED, record.decoded_sha256, record.decoded_byte_count)]
    if record.encoding is ContentEncoding.GZIP_BASE64:
        parts.append(
            (ReportContentPart.ORIGINAL, record.original_sha256, record.original_byte_count)
        )
    return tuple(parts)


def scan_report_content(
    repository: GeneralReportRepository, store: ReportContentStore, *, principal_id: str
) -> ReportContentScan:
    """Compare the rows against the store, in both directions (see the module docstring).

    The row-to-object direction is per Principal, the direction a partition
    can answer. The orphan direction cannot be: an orphan belongs to *no*
    row, so it is subtracted from every known `managed_blob` content id
    (`known_managed_content_ids`, the plane's one unpartitioned read).
    """
    missing: list[tuple[str, ReportContentPart]] = []
    mismatched: list[ReportContentMismatch] = []
    records = repository.managed_content(principal_id=principal_id)
    for record in records:
        for part, expected_sha256, expected_byte_count in _parts(record):
            try:
                store.verify(
                    record.content_id,
                    part,
                    expected_sha256=expected_sha256,
                    expected_byte_count=expected_byte_count,
                )
            except ReportContentIntegrityError as error:
                mismatched.append(ReportContentMismatch(record.content_id, part, error.mismatch))
            except ReportContentMissingError:
                missing.append((record.content_id, part))
            except ReportContentStoreError:
                # Not reachable as a plain part (a link, a swapped directory):
                # for this row's purposes it is not there.
                missing.append((record.content_id, part))
    known = repository.known_managed_content_ids()
    orphans = tuple(sorted(set(store.stored_object_ids()) - known))
    return ReportContentScan(
        checked=len(records),
        missing=tuple(sorted(missing)),
        mismatched=tuple(sorted(mismatched, key=lambda item: (item.content_id, item.part))),
        orphans=orphans,
        unreadable=store.unreadable_entries(),
    )


def _copy(
    repository: GeneralReportRepository,
    source: ReportContentStore,
    destination: ReportContentStore,
    *,
    principal_id: str,
) -> ReportContentCopySummary:
    """Copy every row's object, verified against the row at both ends."""
    copied = 0
    already = 0
    total = 0
    records = repository.managed_content(principal_id=principal_id)
    for record in records:
        parts = _parts(record)
        if destination.has(record.content_id):
            for part, expected_sha256, expected_byte_count in parts:
                destination.verify(
                    record.content_id,
                    part,
                    expected_sha256=expected_sha256,
                    expected_byte_count=expected_byte_count,
                )
            already += 1
            continue
        read = {
            part: source.read(
                record.content_id,
                part,
                expected_sha256=expected_sha256,
                expected_byte_count=expected_byte_count,
            )
            for part, expected_sha256, expected_byte_count in parts
        }
        destination.put(
            record.content_id,
            decoded=read[ReportContentPart.DECODED],
            original=read.get(ReportContentPart.ORIGINAL),
        )
        copied += 1
        total += sum(len(data) for data in read.values())
    return ReportContentCopySummary(
        objects=len(records), copied=copied, already_present=already, bytes_copied=total
    )


def back_up_report_content(
    repository: GeneralReportRepository,
    store: ReportContentStore,
    destination: ReportContentStore,
    *,
    principal_id: str,
) -> ReportContentCopySummary:
    """Copy one Principal's verified objects from the live store into a backup store.

    A missing or mismatched object raises (the store's port error) rather
    than being backed up: a backup must not carry bytes their row disowns.
    Orphans are not copied; no row names them.
    """
    return _copy(repository, store, destination, principal_id=principal_id)


def restore_report_content(
    repository: GeneralReportRepository,
    backup: ReportContentStore,
    store: ReportContentStore,
    *,
    principal_id: str,
) -> ReportContentCopySummary:
    """Copy one Principal's objects back from a backup store, verified against the rows.

    Run after the database is restored: the rows are the authority on what
    each object must be.
    """
    return _copy(repository, backup, store, principal_id=principal_id)
