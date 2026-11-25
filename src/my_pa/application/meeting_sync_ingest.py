"""The `meeting_sync_v1` consumer of the ingestion lifecycle: it stages, never applies (WP3b).

`MeetingSyncHandler` is the `IngestConsumerHandler` for meeting-sync
publications (Manager ruling D1, stage-then-apply). The parser is injected
(`parse`, wired at bootstrap from `infrastructure.meeting_sync.parser`):
application code does not import infrastructure.

**Staging only.** `apply` writes one `meeting_sync_publications` row and one
`meeting_sync_events` row (identifier kind `msevt`) per accepted record, in
the snapshot's transaction, and nothing else: no Meeting, series, binding or
write request. Applying a staged publication to Meetings is the applier's
(`MeetingSyncApplier`, WP3b-S3), which runs only once the reconciliation latch
exists; so a snapshot ingested before the pass is still applied after it (the
W1 finding F-B). This module imports neither the Meeting application nor the
provider sync (`tests/architecture/test_meeting_sync_ingest_stages_only.py`).

**Counts-only quarantine (ruling D14).** A quarantined record leaves no row:
the publication's `quarantined_count` and the run counts are its evidence.
Every record ordinal is either staged or quarantined; the totals are checked
in memory and against the stored rows, and a mismatch raises, so the snapshot
rolls back rather than committing short.

Counts (closed tokens and integers, never content):

* `records_total` -- the publication's records;
* `records_staged` -- accepted records, one staged event each;
* `records_quarantined` -- quarantined records, each counted once;
* `records_quarantined_<reason>` -- records carrying that `ReasonCode`; a
  record with two reasons is counted under each, so these may sum to more than
  `records_quarantined`;
* `diagnostics_<code>` -- the parser's informational `DiagnosticCode`s.

`records_total = records_staged + records_quarantined` always.

**Ordering and coverage.** `prepare` sets `window_start` to the publication's
`generated_at_utc`, so the lifecycle stages snapshots oldest stamp first. A
1.1.0 publication that declares `coverage` records that window as `complete`
with no lane objects (`lane_states` is empty: no calendar reference, a
producer string, reaches the lifecycle's JSON); its calendar references are
kept on the staged publication only. A publication that declares none
records no window.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from my_pa.contracts.ports import (
    IngestApplied,
    IngestConsumer,
    IngestConsumerHandler,
    IngestCoverageDeclaration,
    IngestPrepared,
    IngestSnapshotRecord,
    MeetingSyncEventRecord,
    MeetingSyncPublicationRecord,
    UnitOfWork,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import utc_now
from my_pa.domain.meeting_sync.diagnostics import DiagnosticCode, PublicationRejection
from my_pa.domain.meeting_sync.model import MeetingSyncEvent, MeetingSyncPublication
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "COVERAGE_STATE",
    "MeetingSyncHandler",
    "MeetingSyncTotalsError",
    "ParsedMeetingSync",
]

#: The lifecycle coverage state of a declared 1.1.0 coverage: a claim of completeness.
COVERAGE_STATE: Final = "complete"
_INFORMATIONAL: Final = frozenset(code.value for code in DiagnosticCode)


@dataclass(frozen=True, slots=True)
class ParsedMeetingSync:
    """The injected parser's answer: exactly one of `publication` and `rejection`."""

    publication: MeetingSyncPublication | None
    rejection: PublicationRejection | None
    diagnostic_counts: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (self.publication is None) == (self.rejection is None):
            raise ValueError("a parse is accepted or rejected, not both")


class MeetingSyncTotalsError(Exception):
    """A snapshot's staged rows do not reconcile to its records; the snapshot rolls back."""


def _record_counts(
    publication: MeetingSyncPublication, diagnostic_counts: Mapping[str, int]
) -> dict[str, int]:
    counts: Counter[str] = Counter(
        {
            "records_total": publication.record_count,
            "records_staged": len(publication.events),
            "records_quarantined": len(publication.quarantined),
        }
    )
    for entry in publication.quarantined:
        counts.update(f"records_quarantined_{reason.value}" for reason in entry.reasons)
    counts.update(
        {
            f"diagnostics_{code}": count
            for code, count in diagnostic_counts.items()
            if code in _INFORMATIONAL
        }
    )
    if counts["records_total"] != counts["records_staged"] + counts["records_quarantined"]:
        raise MeetingSyncTotalsError("records do not reconcile to staged plus quarantined")
    return dict(sorted(counts.items()))


def _diagnostics_of(counts: Mapping[str, int]) -> dict[str, int]:
    """The `diagnostics_<code>` entries of prepared counts, as parser code counts."""
    return {
        key.removeprefix("diagnostics_"): value
        for key, value in counts.items()
        if key.startswith("diagnostics_")
    }


def _staged_event(
    event: MeetingSyncEvent, snapshot_id: str, staged_at: datetime
) -> MeetingSyncEventRecord:
    """The staged row of one accepted record: its key and provider-owned fields only."""
    return MeetingSyncEventRecord(
        event_id=issue_identifier(IdKind.MEETING_SYNC_EVENT),
        snapshot_id=snapshot_id,
        record_ordinal=event.ordinal,
        calendar_ref=event.calendar_ref,
        ical_uid=event.ical_uid,
        series_ical_uid=event.series_ical_uid,
        occurrence_original_start_utc=event.occurrence_original_start_utc,
        start_utc=event.start_utc,
        end_utc=event.end_utc,
        timezone_name=event.timezone_name,
        status=event.status,
        title=event.title,
        location_text=event.location_text,
        virtual_meeting_url=event.virtual_meeting_url,
        provider_event_id=event.provider_event_id,
        provider_event_id_format=event.provider_event_id_format,
        staged_at=staged_at,
    )


class MeetingSyncHandler(IngestConsumerHandler):
    """The `meeting_sync_v1` handler (module docstring)."""

    def __init__(
        self,
        *,
        parse: Callable[[bytes], ParsedMeetingSync],
        parser_version: str,
        max_bytes: int,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._parse = parse
        self._parser_version = parser_version
        self._max_bytes = max_bytes
        self._clock = clock

    @property
    def consumer(self) -> IngestConsumer:
        return IngestConsumer.MEETING_SYNC_V1

    @property
    def parser_version(self) -> str:
        return self._parser_version

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    def prepare(self, data: bytes) -> IngestPrepared:
        parsed = self._parse(data)
        publication = parsed.publication
        if publication is None:
            rejection = parsed.rejection
            assert rejection is not None  # noqa: S101 - ParsedMeetingSync's invariant
            return IngestPrepared(
                rejection_code=rejection.value, window_start=None, coverage=None, record_counts={}
            )
        coverage = publication.coverage
        return IngestPrepared(
            rejection_code=None,
            window_start=publication.generated_at_utc,
            coverage=None
            if coverage is None
            else IngestCoverageDeclaration(
                start_utc=coverage.start_utc,
                end_utc=coverage.end_utc,
                coverage_state=COVERAGE_STATE,
                lane_states=(),
            ),
            record_counts=_record_counts(publication, parsed.diagnostic_counts),
            payload=publication,
        )

    def apply(
        self,
        unit: UnitOfWork,
        principal_id: str,
        snapshot: IngestSnapshotRecord,
        prepared: IngestPrepared,
    ) -> IngestApplied:
        publication = prepared.payload
        if not isinstance(publication, MeetingSyncPublication):
            raise TypeError("a meeting sync snapshot carries its parsed publication")
        counts = dict(prepared.record_counts)
        if counts != _record_counts(publication, _diagnostics_of(counts)):
            raise MeetingSyncTotalsError("prepared counts do not match the publication")
        staged_at = self._clock()
        coverage = publication.coverage
        accepted, quarantined = len(publication.events), len(publication.quarantined)
        repository = unit.meeting_sync
        repository.insert_publication(
            principal_id,
            MeetingSyncPublicationRecord(
                snapshot_id=snapshot.snapshot_id,
                ingest_source_id=snapshot.ingest_source_id,
                generated_at_utc=publication.generated_at_utc,
                record_count=publication.record_count,
                accepted_count=accepted,
                quarantined_count=quarantined,
                staged_at=staged_at,
                coverage_start_utc=None if coverage is None else coverage.start_utc,
                coverage_end_utc=None if coverage is None else coverage.end_utc,
                coverage_calendar_refs=None if coverage is None else coverage.calendar_refs,
            ),
        )
        repository.insert_events(
            principal_id,
            [
                _staged_event(event, snapshot.snapshot_id, staged_at)
                for event in sorted(publication.events, key=lambda e: e.ordinal)
            ],
        )
        stored = repository.list_events(principal_id, snapshot.snapshot_id)
        ordinals = {event.ordinal for event in publication.events}
        quarantined_ordinals = {entry.ordinal for entry in publication.quarantined}
        if (
            len(stored) != accepted
            or {row.record_ordinal for row in stored} != ordinals
            or ordinals & quarantined_ordinals
            or ordinals | quarantined_ordinals != set(range(publication.record_count))
        ):
            raise MeetingSyncTotalsError("staged rows do not reconcile to the publication")
        return IngestApplied(record_counts=counts)
