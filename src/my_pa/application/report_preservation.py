"""Re-verify a legal hold's sealed preservation copy (Reports Modernization WP05b B5).

Placing a hold (`GeneralReportRepository.place_hold`) writes, before its hold
row commits, one preservation object per distinct content object of the
report and a seal listing them, all in the `preservation` namespace of the
report content store, and verifies the whole copy. The copy is kept after
the hold is released and is never destroyed: the store port has no delete.

`verify_preservation_copy` proves a copy is still intact later: the seal's
own bytes against the digest and size its hold row records, then every part
of every object the seal lists against the digest and size the seal names.
It reports by raising `ReportPreservationError` and never repairs anything.

Backups need not honor holds (H4, an operator decision). **Actual behaviour:**
`apps/cli/report_content.py backup`/`restore` copy only the `content`
namespace objects that `managed_blob` rows name; the `preservation` namespace
is NOT copied by them. A restore that lacks the copy is reported by this
module's verification (`missing` parts), not hidden; an operator who wants
preservation copies in a backup copies the store root's `preservation`
directory by other means.

`scan_report_preservation` is the operator reconciliation of the namespace
(`apps/cli/report_content.py preservation-verify`): every `place` hold event
of every Principal (`GeneralReportRepository.hold_seal_events`, unpartitioned
on purpose) re-verified as `verify_preservation_copy` verifies one -- the
same `_seal_findings` -- reporting each missing or mismatched part instead of
raising, plus the orphans (stored preservation ids that are neither a seal
of a hold row nor listed by any readable seal) and the store's unreadable
entries. It reports and never repairs, deletes or reclaims anything.

The scan keeps two kinds of result apart (finding 2). **Integrity findings**
-- a missing or mismatched part or seal of a copy a hold row references
(including a malformed seal or an object count other than the row's), and an
unreadable store entry -- mean a copy is damaged (`intact` is false).
**Orphans** are informational: a placement that failed after some puts
leaves its objects behind by design (the store has no delete), so they are
reported apart and do not make the copy damaged. **Stale temporaries**
(Reports Modernization WP08) are informational too: the store's own
`.decoded.tmp` / `.original.tmp` left in an object directory by a process
killed mid-put (`ReportContentStore.stale_temporaries`). They are not
unreadable entries and not integrity findings; a referenced copy whose final
part is absent or unverifiable beside one is still a missing or mismatched
part. Nothing removes them. `consistent` is the fully clean case: intact, no
orphan and no stale temporary.

Nothing here returns a body, a path or a digest value.
"""

from __future__ import annotations

from dataclasses import dataclass

from my_pa.contracts.ports import (
    GeneralReportRepository,
    ReportContentIntegrityError,
    ReportContentPart,
    ReportContentStore,
    ReportContentStoreError,
    ReportPreservationError,
)
from my_pa.domain.reports.custody import ReportHoldEventRecord, preservation_seal_parts

__all__ = [
    "PreservationMismatch",
    "ReportPreservationScan",
    "scan_report_preservation",
    "verify_preservation_copy",
]


@dataclass(frozen=True, slots=True)
class PreservationMismatch:
    """One preservation part (or seal) that is not what its hold row or seal names."""

    object_id: str
    part: ReportContentPart
    #: `"size"` or `"digest"` (the store's), `"malformed"` for a seal that
    #: verifies but does not parse, `"object_count"` for a seal listing another
    #: number of objects than its hold row records.
    mismatch: str


@dataclass(frozen=True, slots=True)
class _SealFindings:
    listed: frozenset[str]
    parts: int
    missing: tuple[tuple[str, ReportContentPart], ...]
    mismatched: tuple[PreservationMismatch, ...]

    @property
    def intact(self) -> bool:
        return not (self.missing or self.mismatched)


def _check(
    store: ReportContentStore,
    object_id: str,
    part: ReportContentPart,
    sha256: str,
    byte_count: int,
    missing: list[tuple[str, ReportContentPart]],
    mismatched: list[PreservationMismatch],
    *,
    read: bool = False,
) -> bytes | None:
    try:
        if read:
            return store.read(
                object_id, part, expected_sha256=sha256, expected_byte_count=byte_count
            )
        store.verify(object_id, part, expected_sha256=sha256, expected_byte_count=byte_count)
    except ReportContentIntegrityError as error:
        mismatched.append(PreservationMismatch(object_id, part, error.mismatch))
    except ReportContentStoreError:
        # Absent, or not reachable as a plain part: for the copy it is not there.
        missing.append((object_id, part))
    return None


def _seal_findings(store: ReportContentStore, hold_event: ReportHoldEventRecord) -> _SealFindings:
    """Every finding of one `place` event's copy: the seal, then every part it lists."""
    preservation = hold_event.preservation
    if preservation is None:
        raise ReportPreservationError()
    missing: list[tuple[str, ReportContentPart]] = []
    mismatched: list[PreservationMismatch] = []
    seal_id = preservation.seal_object_id
    seal = _check(
        store,
        seal_id,
        ReportContentPart.DECODED,
        preservation.seal_sha256,
        preservation.seal_byte_count,
        missing,
        mismatched,
        read=True,
    )
    listed: set[str] = set()
    checked = 1
    if seal is not None:
        try:
            parts = preservation_seal_parts(seal)
        except ValueError:
            mismatched.append(PreservationMismatch(seal_id, ReportContentPart.DECODED, "malformed"))
            parts = ()
        listed = {part.preservation_object_id for part in parts}
        if parts and len(listed) != preservation.object_count:
            mismatched.append(
                PreservationMismatch(seal_id, ReportContentPart.DECODED, "object_count")
            )
        for part in parts:
            checked += 1
            _check(
                store,
                part.preservation_object_id,
                ReportContentPart(part.part),
                part.sha256,
                part.byte_count,
                missing,
                mismatched,
            )
    return _SealFindings(
        listed=frozenset(listed),
        parts=checked,
        missing=tuple(missing),
        mismatched=tuple(mismatched),
    )


def verify_preservation_copy(store: ReportContentStore, hold_event: ReportHoldEventRecord) -> int:
    """Re-verify the sealed copy of one `place` event; the number of parts verified.

    `store` is the report content store of the `preservation` namespace. A
    release event (no copy), a seal or part that is absent, of another size
    or digest, or a malformed seal raises `ReportPreservationError`. The
    count excludes the seal itself, as the parts the seal lists.
    """
    findings = _seal_findings(store, hold_event)
    if not findings.intact:
        raise ReportPreservationError()
    return findings.parts - 1


@dataclass(frozen=True, slots=True)
class ReportPreservationScan:
    """What one preservation scan found. Identifiers, parts and counts only."""

    #: `place` hold events whose sealed copy was checked (every Principal).
    checked: int
    #: `(object id, part)` of every seal or listed part the store lacks.
    missing: tuple[tuple[str, ReportContentPart], ...]
    mismatched: tuple[PreservationMismatch, ...]
    #: Stored preservation ids no hold seal is and no readable seal lists.
    orphans: tuple[str, ...]
    #: Store entries that are not well-formed objects, relative to its root.
    unreadable: tuple[str, ...]
    #: The store's own put temporaries a killed process left (informational).
    stale_temporaries: tuple[str, ...] = ()

    @property
    def integrity_findings(self) -> int:
        """Missing and mismatched parts or seals of referenced copies, and unreadable entries."""
        return len(self.missing) + len(self.mismatched) + len(self.unreadable)

    @property
    def intact(self) -> bool:
        """No integrity finding; orphans may be present (they are informational)."""
        return self.integrity_findings == 0

    @property
    def consistent(self) -> bool:
        """Fully clean: intact, no orphan and no stale temporary."""
        return self.intact and not self.orphans and not self.stale_temporaries


def scan_report_preservation(
    repository: GeneralReportRepository, store: ReportContentStore
) -> ReportPreservationScan:
    """Re-verify every sealed copy and find the namespace's orphans (see the module docstring).

    `store` is the `preservation` namespace. Hold rows are read across
    Principals: an orphan belongs to no hold, so a partitioned read would
    report every other Principal's copy as one. An object put by a placement
    that then failed (its hold row never committed) is an orphan by design:
    the store has no delete.
    """
    missing: list[tuple[str, ReportContentPart]] = []
    mismatched: list[PreservationMismatch] = []
    known: set[str] = set()
    events = repository.hold_seal_events()
    for event in events:
        if event.preservation is None:
            continue
        findings = _seal_findings(store, event)
        known.add(event.preservation.seal_object_id)
        known.update(findings.listed)
        missing.extend(findings.missing)
        mismatched.extend(findings.mismatched)
    return ReportPreservationScan(
        checked=len(events),
        missing=tuple(sorted(set(missing))),
        mismatched=tuple(
            sorted(set(mismatched), key=lambda item: (item.object_id, item.part, item.mismatch))
        ),
        orphans=tuple(sorted(set(store.stored_object_ids()) - known)),
        unreadable=store.unreadable_entries(),
        stale_temporaries=store.stale_temporaries(),
    )
