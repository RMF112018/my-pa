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

Backups need not include the preservation namespace (H4): the copy is a
point-in-time custody record of the live store, and a restore that lacks it
is reported by this verification, not hidden.

Library only; the operator command and the namespace scan are WP05b W3's.
Nothing here returns a body, a path or a digest value.
"""

from __future__ import annotations

from my_pa.contracts.ports import (
    ReportContentPart,
    ReportContentStore,
    ReportContentStoreError,
    ReportPreservationError,
)
from my_pa.domain.reports.custody import ReportHoldEventRecord, preservation_seal_parts

__all__ = ["verify_preservation_copy"]


def verify_preservation_copy(store: ReportContentStore, hold_event: ReportHoldEventRecord) -> int:
    """Re-verify the sealed copy of one `place` event; the number of parts verified.

    `store` is the report content store of the `preservation` namespace. A
    release event (no copy), a seal or part that is absent, of another size
    or digest, or a malformed seal raises `ReportPreservationError`.
    """
    preservation = hold_event.preservation
    if preservation is None:
        raise ReportPreservationError()
    try:
        seal = store.read(
            preservation.seal_object_id,
            ReportContentPart.DECODED,
            expected_sha256=preservation.seal_sha256,
            expected_byte_count=preservation.seal_byte_count,
        )
        parts = preservation_seal_parts(seal)
        objects = {part.preservation_object_id for part in parts}
        if len(objects) != preservation.object_count:
            raise ReportPreservationError()
        for part in parts:
            store.verify(
                part.preservation_object_id,
                ReportContentPart(part.part),
                expected_sha256=part.sha256,
                expected_byte_count=part.byte_count,
            )
    except (ReportContentStoreError, ValueError):
        raise ReportPreservationError() from None
    return len(parts)
