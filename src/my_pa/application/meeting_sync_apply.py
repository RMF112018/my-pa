"""Apply staged `meeting_sync_v1` publications to Meetings, behind the latch (WP3b-S3).

`MeetingSyncApplier.apply_pending(principal_id)` is the second half of
stage-then-apply (Manager ruling D1): `MeetingSyncHandler` staged each ingested
publication; this applies them. The cycles plane's `comms_ingest` step calls it
after `poll_enabled`, and the operator CLI's `run-once` and `backfill` call it
under the same session lock (`COMMS_INGEST_LOCK_KEY`).

**The latch gates everything (ruling D4).** Until the Principal's
reconciliation latch row exists (`meeting_provider_reconciliation_passes`,
written by the S4 reconcile), nothing is applied and nothing is written: the
answer counts the publications waiting (`unapplied_awaiting_reconciliation`).
Once it exists, every staged publication still unapplied is applied at the next
call, the ones staged before the latch included.

**Order and the high-water gate (ruling D8).** Each admitted `meeting_sync_v1`
source is taken in turn, and its unapplied publications in
`(generated_at_utc, file_sha256)` order. Against the newest publication of the
same source already *applied*:

* an older stamp is `skipped_stale`;
* an equal stamp (necessarily other bytes: one snapshot per digest) is
  `skipped_ordering_conflict`;
* a newer stamp is `applied`.

A skipped publication writes nothing but its own apply columns and never
advances the high-water mark. Each publication is one transaction: the
binding-writer advisory lock first, then the re-read of the latch, the
publication and the high-water mark, the events, the `not_seen` pass and the
apply columns, written once. A publication whose transaction raises rolls back
alone, is counted `publications_failed`, stays unapplied for the next call, and
ends this call's pass over its source, so a later publication of that source
can never be applied ahead of it.

**Events** are applied in key order `(calendar_ref, ical_uid,
occurrence_original_start_utc NULLS FIRST, record_ordinal)`, each through
`MeetingProviderSync.apply_event` with the publication's digest and snapshot
id, in the publication's transaction.

**`not_seen` (ruling D7)**, after the events, only for a publication that
declares coverage and has no quarantined record: every binding the window
reaches (its calendar listed, its bound Meeting's current start inside) whose
key is absent from the publication's accepted keys, which has applied no stamp
of this publication or a newer one, and which is not already `not_seen`, is
marked `not_seen` with its version bumped and the publication's stamp; its
`last_seen_*` stay. The Meeting is never touched. A quarantined record
suppresses the whole pass (`not_seen_suppressed_quarantine`): an event that
failed to parse may be exactly the one that looks absent. A later sighting
restores the state through the ordinary refresh. Because the window is judged
by the bound Meeting's current start, an event moved out of the window may be
marked `not_seen` (state only) and is restored when next seen.

**No audit row (ruling D9).** The evidence is the Meeting history (actor
`system`), the Record Events (`system.meeting_provider.sync`), the publication's
apply columns and these counts. Counts are closed names and integers, never
content.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Final

from my_pa.application.meeting_provider_sync import MeetingProviderSync
from my_pa.contracts.ports import (
    IngestConsumer,
    MeetingSyncApplyOutcome,
    MeetingSyncEventRecord,
    MeetingSyncPublicationRecord,
    RepositoryFailureError,
    UnitOfWork,
)
from my_pa.domain.common.time import ensure_utc, utc_now
from my_pa.domain.meeting_sync.model import (
    MeetingSyncEvent,
    OccurrenceKey,
    ProviderBindingState,
    PublicationCoverage,
)
from my_pa.domain.meeting_sync.resolution import marks_not_seen

__all__ = [
    "APPLY_COUNT_NAMES",
    "MeetingSyncApplier",
    "MeetingSyncApplyReport",
    "publication_gate",
]

#: Every count `apply_pending` may report, besides `events_skipped_<diagnostic>`.
APPLY_COUNT_NAMES: Final = frozenset(
    {
        "unapplied_awaiting_reconciliation",
        "publications_applied",
        "publications_skipped_stale",
        "publications_skipped_ordering_conflict",
        "publications_failed",
        "events_created",
        "events_updated",
        "events_unchanged",
        "events_replayed",
        "events_skipped",
        "bindings_marked_not_seen",
        "not_seen_suppressed_quarantine",
    }
)

_PUBLICATION_COUNT: Final = {
    MeetingSyncApplyOutcome.APPLIED: "publications_applied",
    MeetingSyncApplyOutcome.SKIPPED_STALE: "publications_skipped_stale",
    MeetingSyncApplyOutcome.SKIPPED_ORDERING_CONFLICT: "publications_skipped_ordering_conflict",
}


@dataclass(frozen=True, slots=True)
class MeetingSyncApplyReport:
    """What one `apply_pending` call did: closed names to integers, never content."""

    counts: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Pending:
    snapshot_id: str
    generated_at_utc: datetime
    file_sha256: str


def _event(record: MeetingSyncEventRecord, stamp: datetime) -> MeetingSyncEvent:
    """The staged record as the event `apply_event` resolves (no attendee is staged)."""
    return MeetingSyncEvent(
        ordinal=record.record_ordinal,
        calendar_ref=record.calendar_ref,
        ical_uid=record.ical_uid,
        series_ical_uid=record.series_ical_uid,
        occurrence_original_start_utc=record.occurrence_original_start_utc,
        start_utc=record.start_utc,
        end_utc=record.end_utc,
        timezone_name=record.timezone_name,
        status=record.status,
        provider_event_id=record.provider_event_id,
        provider_event_id_format=record.provider_event_id_format,
        title=record.title,
        location_text=record.location_text,
        virtual_meeting_url=record.virtual_meeting_url,
        generated_at_utc=stamp,
    )


def _event_order(record: MeetingSyncEventRecord) -> tuple[str, str, bool, datetime | None, int]:
    """`(calendar_ref, ical_uid, occurrence_original_start_utc NULLS FIRST, ordinal)`."""
    original = record.occurrence_original_start_utc
    return (
        record.calendar_ref,
        record.ical_uid,
        original is not None,
        original,
        record.record_ordinal,
    )


def _coverage(publication: MeetingSyncPublicationRecord) -> PublicationCoverage | None:
    if (
        publication.coverage_calendar_refs is None
        or publication.coverage_start_utc is None
        or publication.coverage_end_utc is None
    ):
        return None
    return PublicationCoverage(
        start_utc=publication.coverage_start_utc,
        end_utc=publication.coverage_end_utc,
        calendar_refs=publication.coverage_calendar_refs,
    )


def publication_gate(stamp: datetime, high_water: datetime | None) -> MeetingSyncApplyOutcome:
    """The high-water decision for one unapplied publication of a source (D8)."""
    if high_water is None or stamp > high_water:
        return MeetingSyncApplyOutcome.APPLIED
    if stamp < high_water:
        return MeetingSyncApplyOutcome.SKIPPED_STALE
    return MeetingSyncApplyOutcome.SKIPPED_ORDERING_CONFLICT


class MeetingSyncApplier:
    """`apply_pending` over fresh units of work (module docstring)."""

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], UnitOfWork],
        clock: Callable[[], datetime] = utc_now,
        sync: MeetingProviderSync | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._sync = MeetingProviderSync() if sync is None else sync

    def apply_pending(self, principal_id: str) -> MeetingSyncApplyReport:
        counts: Counter[str] = Counter()
        with self._unit_of_work() as unit:
            latched = unit.meeting_sync.get_reconciliation_pass(principal_id) is not None
            pending = {
                source.ingest_source_id: self._pending(unit, principal_id, source.ingest_source_id)
                for source in unit.ingestion.list_sources(principal_id)
                if source.consumer is IngestConsumer.MEETING_SYNC_V1
            }
        if not latched:
            waiting = sum(len(entries) for entries in pending.values())
            if waiting:
                counts["unapplied_awaiting_reconciliation"] = waiting
            return MeetingSyncApplyReport(counts=dict(sorted(counts.items())))
        for source_id in sorted(pending):
            for entry in pending[source_id]:
                try:
                    with self._unit_of_work() as unit:
                        counts.update(self._apply_one(unit, principal_id, source_id, entry))
                except Exception:  # this publication rolls back; its source stops here
                    counts["publications_failed"] += 1
                    break
        return MeetingSyncApplyReport(
            counts={name: value for name, value in sorted(counts.items()) if value}
        )

    @staticmethod
    def _pending(unit: UnitOfWork, principal_id: str, source_id: str) -> list[_Pending]:
        """The source's unapplied publications in apply order, with their digests."""
        entries: list[_Pending] = []
        for publication in unit.meeting_sync.list_publications(
            principal_id, source_id, unapplied_only=True
        ):
            snapshot = unit.ingestion.get_snapshot(principal_id, publication.snapshot_id)
            if snapshot is None:  # the composite foreign key keeps it in this partition
                raise RepositoryFailureError
            entries.append(
                _Pending(
                    publication.snapshot_id, publication.generated_at_utc, snapshot.file_sha256
                )
            )
        return sorted(entries, key=lambda e: (e.generated_at_utc, e.file_sha256, e.snapshot_id))

    def _apply_one(
        self, unit: UnitOfWork, principal_id: str, source_id: str, entry: _Pending
    ) -> Counter[str]:
        """One publication in its own transaction (module docstring)."""
        # The binding-writer lock first (D8), held to commit.
        unit.meetings.lock_provider_binding_writers(principal_id)
        staging = unit.meeting_sync
        counts: Counter[str] = Counter()
        if staging.get_reconciliation_pass(principal_id) is None:  # append-only: cannot vanish
            raise RepositoryFailureError
        publication = staging.get_publication(principal_id, entry.snapshot_id)
        if publication is None:
            raise RepositoryFailureError
        if publication.applied_at is not None:
            return counts  # applied since the listing (another process); nothing to do
        applied = [
            p.generated_at_utc
            for p in staging.list_publications(principal_id, source_id)
            if p.apply_outcome is MeetingSyncApplyOutcome.APPLIED
        ]
        outcome = publication_gate(publication.generated_at_utc, max(applied, default=None))
        at = ensure_utc(self._clock())
        apply_counts: Counter[str] = Counter()
        if outcome is MeetingSyncApplyOutcome.APPLIED:
            apply_counts = self._apply_events(unit, principal_id, publication, entry, at)
        staging.complete_publication(
            principal_id,
            publication.snapshot_id,
            applied_at=at,
            apply_outcome=outcome,
            apply_counts=dict(sorted(apply_counts.items())),
        )
        counts[_PUBLICATION_COUNT[outcome]] += 1
        counts.update(apply_counts)
        return counts

    def _apply_events(
        self,
        unit: UnitOfWork,
        principal_id: str,
        publication: MeetingSyncPublicationRecord,
        entry: _Pending,
        at: datetime,
    ) -> Counter[str]:
        counts: Counter[str] = Counter()
        stamp = publication.generated_at_utc
        records = sorted(
            unit.meeting_sync.list_events(principal_id, publication.snapshot_id), key=_event_order
        )
        accepted: set[OccurrenceKey] = set()
        for record in records:
            event = _event(record, stamp)
            accepted.add(event.key)
            outcome = self._sync.apply_event(
                unit,
                principal_id,
                event,
                source_sha256=entry.file_sha256,
                source_snapshot_id=publication.snapshot_id,
                now=at,
            )
            counts[f"events_{outcome.kind.value}"] += 1
            if outcome.diagnostic is not None:
                counts[f"events_skipped_{outcome.diagnostic.value}"] += 1
        coverage = _coverage(publication)
        if coverage is None:
            return counts
        if publication.quarantined_count > 0:
            counts["not_seen_suppressed_quarantine"] += 1
            return counts
        counts["bindings_marked_not_seen"] += self._mark_not_seen(
            unit, principal_id, coverage, stamp, frozenset(accepted), at
        )
        return counts

    @staticmethod
    def _mark_not_seen(
        unit: UnitOfWork,
        principal_id: str,
        coverage: PublicationCoverage,
        stamp: datetime,
        accepted: frozenset[OccurrenceKey],
        at: datetime,
    ) -> int:
        """Ruling D7 over the bindings the window reaches. Bindings only, never a Meeting."""
        repository = unit.meetings
        marked = 0
        for covered in repository.lock_provider_bindings_in_window(
            principal_id, coverage.calendar_refs, coverage.start_utc, coverage.end_utc
        ):
            binding = covered.binding
            key = OccurrenceKey(
                binding.calendar_ref, binding.ical_uid, binding.occurrence_original_start_utc
            )
            if not marks_not_seen(
                key=key,
                provider_state=binding.provider_state,
                last_applied_generated_at_utc=binding.last_applied_generated_at_utc,
                meeting_start_at=covered.meeting_start_at,
                coverage=coverage,
                generated_at_utc=stamp,
                accepted_keys=accepted,
            ):
                continue
            repository.update_provider_binding(
                principal_id,
                replace(
                    binding,
                    provider_state=ProviderBindingState.NOT_SEEN,
                    last_applied_generated_at_utc=stamp,
                    version=binding.version + 1,
                    updated_at=at,
                ),
            )
            marked += 1
        return marked
