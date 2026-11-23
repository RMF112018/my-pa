"""The `communications_evidence_v2` consumer of the ingestion lifecycle (WP3a).

`CommunicationsEvidenceHandler` is the `IngestConsumerHandler` for
communications publications. The parser is injected (`parse`, wired at
bootstrap from `infrastructure.communications.evidence_v2`): application code
does not import infrastructure.

**Every record ordinal leaves exactly one row (contract section 4.3).** A usable
record (accepted, degraded, merged lane, out of window, or an exact repeat
stored as `duplicate_observation` on its provider id's item) is one
observation; a quarantined record -- by the parser, by the within-publication
rules, or by the cross-publication identity check below -- is one quarantine
row. The totals are checked in memory and against `tally_snapshot`; a mismatch
raises, so the snapshot rolls back rather than committing short.

**Identity across publications (Manager ruling M6, contract section 3).** For
each mailbox item of the publication:

1. its provider id already has a stored item: that item's message is the
   match -- matched, never rekeyed. When the stored message is keyed by a
   different Internet Message-ID than the one this publication carries, that is
   one provider id with two Message-IDs (check c): an identity conflict. When
   the stored message is keyed in the *other* identity kind (a stored
   `provider_id_only` message and a publication carrying the Message-ID, or
   the reverse; finding R3-2 / check e), the two key spaces never merge
   (contract section 3, ADR-022 decision 4): every observation of the item in
   this snapshot is quarantined `identity_kind_mismatch`, counted
   `records_identity_kind_mismatch`, and creates no message and no item; the
   stored item and message are not touched (not even flagged). The join is
   WP3b;
2. otherwise the canonical key `(principal, mailbox_ref, identity_kind,
   identity_value)` finds the message, or a new one is created;
3. the item's primary observation is checked against the stored message: a
   sender address (when both are known) or body digest that differs is an
   identity conflict. A conflict quarantines every observation of the item in
   this snapshot (`identity_conflict`), sets `identity_conflict` on the stored
   message, and rewrites nothing else.

**In-window, per observation (check d).** Every observation -- merged lane
siblings and repeats included, not only primaries -- is compared with the
window; a declared `in_window` that disagrees adds `in_window_disagreement` to
that observation's reasons. `out_of_window` observations are stored and never
contribute coverage (coverage is the declared window only).

**Participants are append-only (ruling M7).** The item's reconciled
participants are added set-like with the observation that first contributed
each; a present one is kept. `participants_reconciled` / `participants_disagreed`
are raised on the message when an item reports them, never lowered.

**Projection (contract section 11, rulings m1, m2).** A message's text and its
`body_*` columns come from one observation, the one with the greatest key
`(has text, window end, window start, snapshot SHA-256, lowest ordinal)`: any
observation with a usable text basis beats every one without, then the latest
declared window wins -- a total order, so the projection does not depend on
arrival order. `search_text` is `derive_search_text` (`comms_search_text_v1`,
frozen) and is `NULL` whenever the body is withheld, truncated or empty.
`latest_snapshot_id` is the observing snapshot with the greatest `(window end,
window start, SHA-256)`. The message's identity columns (subject, sender,
time, conversation) are set once, by the snapshot that created it.

**Identifiers** are `extract_identifiers(subject + "\\n" + search_text)`
(`comms_identifiers_v1`), added whenever a message is created or its text is
replaced; set-like, so earlier versions' rows stay.

**Coverage.** `prepare` declares the window and one lane object per declared
source: `key_kind` (`inbox`, `sent`, `procore_rfis`, else `other` -- the
producer-key mapping lives here, not in the domain), `role`, `lane`,
`authorized`, `state`. The lifecycle stores it as the snapshot's coverage
window; `CommunicationsCoverageReader` reads it back.

Counts are closed tokens and integers; nothing here logs or returns content.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from my_pa.contracts.ports import (
    CommunicationIdentifierRecord,
    CommunicationMailboxItemRecord,
    CommunicationMessageRecord,
    CommunicationObservationRecord,
    CommunicationParticipantRecord,
    CommunicationProjection,
    CommunicationQuarantineRecord,
    CommunicationsRepository,
    IngestApplied,
    IngestConsumer,
    IngestConsumerHandler,
    IngestCoverageDeclaration,
    IngestCoverageWindowRecord,
    IngestionRepository,
    IngestPrepared,
    IngestSnapshotRecord,
    UnitOfWork,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import utc_now
from my_pa.domain.communications.coverage import (
    CoverageSummary,
    LaneFact,
    RangeCoverage,
    WindowFact,
    range_coverage,
    rolling_coverage,
    summarize_coverage,
)
from my_pa.domain.communications.diagnostics import PublicationRejection, ReasonCode
from my_pa.domain.communications.identifiers import IDENTIFIER_VERSION, extract_identifiers
from my_pa.domain.communications.model import (
    ItemFlag,
    MailboxItem,
    NormalizedMessage,
    Publication,
    RecordClassification,
    RecordOutcome,
    SourceCoverage,
)
from my_pa.domain.communications.search_text import SearchText, derive_search_text
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "KNOWN_SOURCE_KEYS",
    "CommunicationsCoverageReader",
    "CommunicationsEvidenceHandler",
    "CommunicationsTotalsError",
    "ParsedPublication",
]

#: Producer source keys stored by name as `key_kind`; any other key is `other`.
KNOWN_SOURCE_KEYS: Final = frozenset({"inbox", "sent", "procore_rfis"})


@dataclass(frozen=True, slots=True)
class ParsedPublication:
    """The injected parser's answer: exactly one of `publication` and `rejection`."""

    publication: Publication | None
    rejection: PublicationRejection | None
    diagnostic_counts: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (self.publication is None) == (self.rejection is None):
            raise ValueError("a parse is accepted or rejected, not both")


class CommunicationsTotalsError(Exception):
    """A snapshot's rows do not reconcile to its record count; the snapshot rolls back."""


type _TextKey = tuple[bool, datetime, datetime, str, int]
type _WindowKey = tuple[datetime, datetime, str]


def lane_state(source: SourceCoverage) -> dict[str, object]:
    """One declared source as its stored lane object (ruling m4)."""
    return {
        "key_kind": source.key if source.key in KNOWN_SOURCE_KEYS else "other",
        "role": source.role.value,
        "lane": source.lane.value,
        "authorized": source.authorized,
        "state": source.state.value,
    }


def _projection(
    message: NormalizedMessage, search: SearchText, snapshot_id: str
) -> CommunicationProjection:
    text = search.text
    return CommunicationProjection(
        body_state=message.body.state.value,
        body_sha256=message.body.sha256,
        body_utf8_bytes=message.body.utf8_bytes,
        content_type=message.body.content_type.value,
        search_text=text,
        search_text_sha256=None if text is None else hashlib.sha256(text.encode()).hexdigest(),
        search_text_version=search.version,
        search_text_basis=search.basis.value,
        search_text_flags=tuple(sorted(flag.value for flag in search.flags)),
        text_snapshot_id=snapshot_id,
        text_record_ordinal=message.ordinal,
    )


@dataclass
class _Candidate:
    """The text candidate one snapshot offers one message (its best item primary)."""

    key: _TextKey
    projection: CommunicationProjection


@dataclass
class _Touched:
    """What this snapshot did to one message."""

    record: CommunicationMessageRecord
    created: bool
    candidate: _Candidate | None = None
    flags: set[ItemFlag] = field(default_factory=set)


class _Apply:
    """One snapshot's communications writes, inside the lifecycle's transaction."""

    def __init__(
        self,
        unit: UnitOfWork,
        principal_id: str,
        snapshot: IngestSnapshotRecord,
        publication: Publication,
    ) -> None:
        self.repo: CommunicationsRepository = unit.communications
        self.ingestion: IngestionRepository = unit.ingestion
        self.principal_id = principal_id
        self.snapshot = snapshot
        self.publication = publication
        self.window_key: _WindowKey = (
            publication.window.end_utc,
            publication.window.start_utc,
            snapshot.file_sha256,
        )
        self.counts: Counter[str] = Counter()
        self.touched: dict[str, _Touched] = {}
        self.flagged: set[str] = set()
        self.observations = 0
        self.quarantined = 0
        self._window_keys: dict[str, _WindowKey] = {snapshot.snapshot_id: self.window_key}

    # --- keys ------------------------------------------------------------------

    def snapshot_key(self, snapshot_id: str) -> _WindowKey:
        cached = self._window_keys.get(snapshot_id)
        if cached is not None:
            return cached
        window = self.ingestion.get_coverage_window(self.principal_id, snapshot_id)
        snapshot = self.ingestion.get_snapshot(self.principal_id, snapshot_id)
        if window is None or snapshot is None:
            raise CommunicationsTotalsError("a stored pointer names no ingested window")
        key = (window.end_utc, window.start_utc, snapshot.file_sha256)
        self._window_keys[snapshot_id] = key
        return key

    def text_key(self, projection: CommunicationProjection) -> _TextKey:
        end, start, digest = self.snapshot_key(projection.text_snapshot_id)
        return (
            projection.search_text is not None,
            end,
            start,
            digest,
            -projection.text_record_ordinal,
        )

    # --- identity ----------------------------------------------------------------

    def _disagrees(self, stored: CommunicationMessageRecord, primary: NormalizedMessage) -> bool:
        sender = primary.sender_address
        if (
            stored.sender_address is not None
            and sender is not None
            and stored.sender_address != sender
        ):
            return True
        return stored.projection.body_sha256 != primary.body.sha256

    def track_message(self, record: CommunicationMessageRecord, *, created: bool) -> _Touched:
        touched = self.touched.get(record.message_id)
        if touched is None:
            touched = _Touched(record=record, created=created)
            self.touched[record.message_id] = touched
        return touched

    def _create(self, item: MailboxItem, primary: NormalizedMessage) -> CommunicationMessageRecord:
        key = item.canonical_key
        search = derive_search_text(primary)
        record = CommunicationMessageRecord(
            message_id=issue_identifier(IdKind.COMMUNICATION_MESSAGE),
            mailbox_ref=key.mailbox_ref,
            identity_kind=key.kind.value,
            identity_value=key.value,
            conversation_id=primary.conversation_id,
            subject=primary.subject,
            sender_address=primary.sender_address,
            message_time=item.message_time,
            message_time_basis=item.message_time_basis.value,
            has_attachments=primary.has_attachments,
            projection=_projection(primary, search, self.snapshot.snapshot_id),
            first_snapshot_id=self.snapshot.snapshot_id,
            latest_snapshot_id=self.snapshot.snapshot_id,
        )
        self.repo.insert_message(self.principal_id, record)
        self.counts["messages_created"] += 1
        return record

    def _new_item(self, message_id: str, item: MailboxItem, primary: NormalizedMessage) -> str:
        item_id = issue_identifier(IdKind.COMMUNICATION_MAILBOX_ITEM)
        self.repo.insert_item(
            self.principal_id,
            CommunicationMailboxItemRecord(
                item_id=item_id,
                message_id=message_id,
                mailbox_ref=primary.mailbox_ref,
                provider_id=item.provider_id,
                provider_id_format=primary.provider_id_format.value,
                first_snapshot_id=self.snapshot.snapshot_id,
            ),
        )
        self.counts["items_created"] += 1
        return item_id

    def resolve(
        self, item: MailboxItem, primary: NormalizedMessage
    ) -> tuple[CommunicationMessageRecord | None, str | None]:
        """The item's message and its item id; `(message, None)` on a conflict.

        `(None, None)` when the provider id's stored item belongs to a message
        of the other identity kind: the record is quarantined
        `identity_kind_mismatch` and nothing stored is touched.
        """
        key = item.canonical_key
        stored_item = self.repo.find_item_by_provider_id(
            self.principal_id, primary.mailbox_ref, item.provider_id
        )
        if stored_item is not None:
            message = self.touched.get(stored_item.message_id)
            record = (
                message.record
                if message is not None
                else self.repo.get_message(
                    self.principal_id, stored_item.message_id, for_update=True
                )
            )
            if record is None:
                raise CommunicationsTotalsError("a stored item names no message")
            if record.identity_kind != key.kind.value:
                # Check (e): the key spaces never merge, in either direction.
                return None, None
            if record.identity_value != key.value:
                # Check (c): one provider id, two Internet Message-IDs.
                self.counts["records_provider_id_message_id_conflict"] += 1
                return record, None
            if self._disagrees(record, primary):
                return record, None
            return record, stored_item.item_id
        touched = next(
            (
                t
                for t in self.touched.values()
                if (t.record.mailbox_ref, t.record.identity_kind, t.record.identity_value)
                == (key.mailbox_ref, key.kind.value, key.value)
            ),
            None,
        )
        record = (
            touched.record
            if touched is not None
            else self.repo.find_message_by_identity(
                self.principal_id, key.mailbox_ref, key.kind.value, key.value, for_update=True
            )
        )
        if record is None:
            record = self._create(item, primary)
            self.track_message(record, created=True)
        elif self._disagrees(record, primary):
            return record, None
        return record, self._new_item(record.message_id, item, primary)

    # --- rows ----------------------------------------------------------------------

    def quarantine(self, ordinal: int, reasons: tuple[str, ...]) -> None:
        if not reasons:
            raise CommunicationsTotalsError("a quarantined record names no reason")
        self.repo.insert_quarantine(
            self.principal_id,
            CommunicationQuarantineRecord(
                quarantine_id=issue_identifier(IdKind.COMMUNICATION_QUARANTINE),
                snapshot_id=self.snapshot.snapshot_id,
                record_ordinal=ordinal,
                reasons=tuple(sorted(set(reasons))),
            ),
        )
        self.quarantined += 1

    def add_observation(
        self, item_id: str, record: RecordOutcome, message: NormalizedMessage
    ) -> str:
        reasons = {reason.value for reason in record.reasons}
        in_window = self.publication.window.contains(message.timestamps.selected_utc)
        if (
            message.declared_in_window is not None
            and message.declared_in_window != in_window
            and ReasonCode.IN_WINDOW_DISAGREEMENT.value not in reasons
        ):
            reasons.add(ReasonCode.IN_WINDOW_DISAGREEMENT.value)
            self.counts["records_in_window_disagreement_added"] += 1
        timestamps = message.timestamps
        observation_id = issue_identifier(IdKind.COMMUNICATION_OBSERVATION)
        self.repo.insert_observation(
            self.principal_id,
            CommunicationObservationRecord(
                observation_id=observation_id,
                item_id=item_id,
                snapshot_id=self.snapshot.snapshot_id,
                record_ordinal=record.ordinal,
                classification=record.classification.value,
                reasons=tuple(sorted(reasons)),
                folder_role=message.folder_role.value,
                lane_verification=message.folder_verification.value,
                selected_field=timestamps.selected_field.value,
                selected_utc=timestamps.selected_utc,
                received_utc=timestamps.received_utc,
                received_state=timestamps.received_state.value,
                sent_utc=timestamps.sent_utc,
                sent_state=timestamps.sent_state.value,
                body_sha256=message.body.sha256,
                unique_body_sha256=(
                    None if message.unique_body is None else message.unique_body.sha256
                ),
                participants={
                    name: participant.addresses
                    for name, participant in message.participants.items()
                },
            ),
        )
        self.observations += 1
        return observation_id

    def participants(
        self, message_id: str, item: MailboxItem, observation_ids: Mapping[int, str]
    ) -> None:
        rows = [
            CommunicationParticipantRecord(
                message_id=message_id,
                field=name,
                address=participant.address,
                first_observation_id=observation_ids[participant.ordinals[0]],
            )
            for name, participants in item.participants.items()
            for participant in participants
        ]
        self.counts["participants_added"] += self.repo.insert_participants(self.principal_id, rows)

    def offer(self, touched: _Touched, primary: NormalizedMessage) -> None:
        projection = _projection(primary, derive_search_text(primary), self.snapshot.snapshot_id)
        candidate = _Candidate(
            key=(projection.search_text is not None, *self.window_key, -primary.ordinal),
            projection=projection,
        )
        if touched.candidate is None or candidate.key > touched.candidate.key:
            touched.candidate = candidate

    # --- per-message settlement --------------------------------------------------

    def settle(self, touched: _Touched) -> None:
        record = touched.record
        message_id = record.message_id
        candidate = touched.candidate
        replaced = False
        latest = record.latest_snapshot_id
        if self.window_key > self.snapshot_key(latest):
            latest = self.snapshot.snapshot_id
        if candidate is not None:
            current = record.projection
            if touched.created:
                replaced = candidate.projection != current
            else:
                replaced = candidate.key > self.text_key(current)
        if replaced and candidate is not None:
            self.repo.update_message_projection(
                self.principal_id,
                message_id,
                projection=candidate.projection,
                latest_snapshot_id=latest,
            )
            if not touched.created:
                self.counts["projections_replaced"] += 1
        elif latest != record.latest_snapshot_id:
            self.repo.set_latest_snapshot(self.principal_id, message_id, latest)
        raise_reconciled = (
            ItemFlag.PARTICIPANTS_RECONCILED in touched.flags and not record.participants_reconciled
        )
        raise_disagreed = (
            ItemFlag.PARTICIPANTS_DISAGREED in touched.flags and not record.participants_disagreed
        )
        if raise_reconciled or raise_disagreed:
            self.repo.set_message_flags(
                self.principal_id,
                message_id,
                participants_reconciled=True if raise_reconciled else None,
                participants_disagreed=True if raise_disagreed else None,
            )
        if touched.created or replaced:
            text = (
                candidate.projection.search_text
                if replaced and candidate is not None
                else record.projection.search_text
            )
            identifiers = extract_identifiers(f"{record.subject or ''}\n{text or ''}")
            self.counts["identifiers_added"] += self.repo.insert_identifiers(
                self.principal_id,
                [
                    CommunicationIdentifierRecord(
                        message_id=message_id,
                        kind=identifier.kind.value,
                        value=identifier.value,
                        extractor_version=IDENTIFIER_VERSION,
                    )
                    for identifier in identifiers
                ],
            )


class CommunicationsEvidenceHandler(IngestConsumerHandler):
    """The `communications_evidence_v2` handler (module docstring)."""

    def __init__(
        self,
        *,
        parse: Callable[[bytes], ParsedPublication],
        parser_version: str,
        max_bytes: int,
    ) -> None:
        self._parse = parse
        self._parser_version = parser_version
        self._max_bytes = max_bytes

    @property
    def consumer(self) -> IngestConsumer:
        return IngestConsumer.COMMUNICATIONS_EVIDENCE_V2

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
            assert rejection is not None  # noqa: S101 - ParsedPublication's invariant
            return IngestPrepared(
                rejection_code=rejection.value, window_start=None, coverage=None, record_counts={}
            )
        counts: Counter[str] = Counter({"records_total": len(publication.records)})
        counts.update(f"records_{r.classification.value}" for r in publication.records)
        counts.update(
            {f"diagnostics_{code}": count for code, count in parsed.diagnostic_counts.items()}
        )
        window = publication.window
        return IngestPrepared(
            rejection_code=None,
            window_start=window.start_utc,
            coverage=IngestCoverageDeclaration(
                start_utc=window.start_utc,
                end_utc=window.end_utc,
                coverage_state=publication.coverage_overall.value,
                lane_states=tuple(lane_state(source) for source in publication.sources),
            ),
            record_counts=dict(sorted(counts.items())),
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
        if not isinstance(publication, Publication):
            raise TypeError("a communications snapshot carries its parsed publication")
        run = _Apply(unit, principal_id, snapshot, publication)
        final: Counter[str] = Counter()
        by_provider_id: dict[str, list[RecordOutcome]] = {}
        for record in publication.records:
            if record.classification is RecordClassification.QUARANTINED:
                run.quarantine(record.ordinal, tuple(reason.value for reason in record.reasons))
                final[RecordClassification.QUARANTINED.value] += 1
                continue
            if record.message is None:
                raise CommunicationsTotalsError("a usable record carries no message")
            by_provider_id.setdefault(record.message.provider_id, []).append(record)
        items = {item.provider_id: item for item in publication.items}
        if set(by_provider_id) - set(items):
            raise CommunicationsTotalsError("a usable record belongs to no mailbox item")
        by_ordinal = {record.ordinal: record for record in publication.records}
        for item in publication.items:
            primary = by_ordinal[item.primary_ordinal].message
            if primary is None:
                raise CommunicationsTotalsError("a primary observation carries no message")
            records = sorted(by_provider_id[item.provider_id], key=lambda r: r.ordinal)
            message, item_id = run.resolve(item, primary)
            if message is None:
                run.counts["records_identity_kind_mismatch"] += len(records)
                for record in records:
                    run.quarantine(
                        record.ordinal,
                        (
                            *(reason.value for reason in record.reasons),
                            ReasonCode.IDENTITY_KIND_MISMATCH.value,
                        ),
                    )
                    final[RecordClassification.QUARANTINED.value] += 1
                continue
            if item_id is None:
                run.counts["records_identity_conflict_cross_publication"] += len(records)
                for record in records:
                    run.quarantine(
                        record.ordinal,
                        (
                            *(reason.value for reason in record.reasons),
                            ReasonCode.IDENTITY_CONFLICT.value,
                        ),
                    )
                    final[RecordClassification.QUARANTINED.value] += 1
                if not message.identity_conflict and message.message_id not in run.flagged:
                    unit.communications.set_message_flags(
                        principal_id, message.message_id, identity_conflict=True
                    )
                    run.flagged.add(message.message_id)
                    run.counts["messages_identity_conflict_flagged"] += 1
                continue
            observation_ids: dict[int, str] = {}
            for record in records:
                assert record.message is not None  # noqa: S101 - grouped on it above
                observation_ids[record.ordinal] = run.add_observation(
                    item_id, record, record.message
                )
                final[record.classification.value] += 1
            run.participants(message.message_id, item, observation_ids)
            touched = run.track_message(message, created=False)
            touched.flags |= item.flags
            run.offer(touched, primary)
        for touched in run.touched.values():
            run.settle(touched)
        total = len(publication.records)
        tally = unit.communications.tally_snapshot(principal_id, snapshot.snapshot_id)
        if run.observations + run.quarantined != total or (
            tally.observations,
            tally.quarantined,
        ) != (run.observations, run.quarantined):
            raise CommunicationsTotalsError("snapshot rows do not reconcile to its records")
        counts = Counter(run.counts)
        counts["records_total"] = total
        counts.update({f"records_{name}": value for name, value in final.items()})
        return IngestApplied(record_counts=dict(sorted(counts.items())))


def _window_fact(window: IngestCoverageWindowRecord) -> WindowFact:
    return WindowFact(
        start=window.start_utc,
        end=window.end_utc,
        state=window.coverage_state,
        lanes=tuple(
            LaneFact(
                key_kind=str(lane.get("key_kind")),
                role=str(lane.get("role")),
                lane=str(lane.get("lane")),
                authorized=(
                    authorized if isinstance(authorized := lane.get("authorized"), bool) else None
                ),
                state=str(lane.get("state")),
            )
            for lane in window.lane_states
        ),
    )


class CommunicationsCoverageReader:
    """The coverage read over one source's stored windows (contract sections 9 and 19)."""

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], UnitOfWork],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def _facts(self, principal_id: str, ingest_source_id: str) -> tuple[WindowFact, ...]:
        with self._unit_of_work() as unit:
            windows = unit.ingestion.list_coverage_windows(principal_id, ingest_source_id)
        return tuple(_window_fact(window) for window in windows)

    def summary(self, principal_id: str, ingest_source_id: str) -> CoverageSummary:
        """Merged intervals, gaps, lanes, freshness and snapshot counts."""
        return summarize_coverage(self._facts(principal_id, ingest_source_id), now=self._clock())

    def rolling(self, principal_id: str, ingest_source_id: str) -> RangeCoverage | None:
        """The monitoring read for holes: `[latest covered - 30 d, latest covered]`.

        Complete or partial (with gaps); `None` when nothing is covered.
        Staleness is the summary's `freshness_seconds`, not this read.
        """
        return rolling_coverage(self._facts(principal_id, ingest_source_id))

    def range(
        self, principal_id: str, ingest_source_id: str, *, start: datetime, end: datetime
    ) -> RangeCoverage:
        """`[start, end]` (whole seconds, inclusive): complete, partial (with gaps) or none."""
        summary = self.summary(principal_id, ingest_source_id)
        return range_coverage(summary.intervals, start=start, end=end)

    def combined(self, principal_id: str, ingest_source_ids: Sequence[str]) -> CoverageSummary:
        """One summary over the windows of several sources (overlaps merge, contract 9)."""
        facts = tuple(
            fact
            for source_id in sorted(set(ingest_source_ids))
            for fact in self._facts(principal_id, source_id)
        )
        return summarize_coverage(facts, now=self._clock())
