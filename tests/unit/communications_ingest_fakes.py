"""FAST doubles for the WP3a ingestion lifecycle and its communications consumer.

* `IngestWorld` holds every row the two WP3a repositories know, plus the list
  of write calls made (`writes`), so a dry run can be proved to write nothing;
* `IngestUnitOfWork` is the general `FakeUnitOfWork` with real `ingestion` and
  `communications` planes over an `IngestWorld`: entering the block snapshots
  the world and leaving it by exception restores it, so a rolled-back snapshot
  leaves no row, as on PostgreSQL;
* the repositories enforce the revision's guards that the lifecycle relies on:
  one snapshot per `(source, sha256)`, finalize once from `pending`, one path row
  per `(snapshot, path)`, one current row per path, supersede once from NULL,
  one finish per run, one link per `(run, snapshot)`, one message per canonical
  key, one item per provider id, one row per `(snapshot, ordinal)`;
* `FakeStore` is a `FileWorkspaceStore` whose read path works over an
  in-memory tree and whose every other method fails the test.

Everything here is synthetic.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import TracebackType
from typing import Any

from my_pa.contracts.ports import (
    CommunicationIdentifierRecord,
    CommunicationMailboxItemRecord,
    CommunicationMessageRecord,
    CommunicationObservationRecord,
    CommunicationParticipantRecord,
    CommunicationProjection,
    CommunicationQuarantineRecord,
    CommunicationRederiveDueRecord,
    CommunicationSearchQuery,
    CommunicationSearchQueryShape,
    CommunicationSearchRow,
    CommunicationSelfAddresses,
    CommunicationSnapshotTally,
    CommunicationsRepository,
    FileWorkspaceEntry,
    FileWorkspacePage,
    FileWorkspaceReader,
    FileWorkspaceStore,
    IngestCoverageWindowRecord,
    IngestionRepository,
    IngestRunOutcome,
    IngestRunRecord,
    IngestRunSnapshotRecord,
    IngestSnapshotPathRecord,
    IngestSnapshotRecord,
    IngestSnapshotStatus,
    IngestSourceRecord,
    MeetingContextCandidateQuery,
    MeetingContextCandidateRow,
    RepositoryFailureError,
    UnitOfWork,
)
from my_pa.domain.files.errors import FilesRefusal
from my_pa.domain.files.versions import EntryKind
from my_pa.domain.files.vocabulary import FilesReason
from tests.conftest import FakeUnitOfWork, World


class GuardRefusalError(Exception):
    """What a database guard would have refused (a trigger or a unique index)."""


@dataclass
class IngestWorld:
    sources: dict[tuple[str, str], IngestSourceRecord] = field(default_factory=dict)
    snapshots: dict[tuple[str, str], IngestSnapshotRecord] = field(default_factory=dict)
    paths: dict[tuple[str, str, str], IngestSnapshotPathRecord] = field(default_factory=dict)
    runs: dict[tuple[str, str], IngestRunRecord] = field(default_factory=dict)
    run_snapshots: dict[tuple[str, str, str], IngestRunSnapshotRecord] = field(default_factory=dict)
    coverage: dict[tuple[str, str], IngestCoverageWindowRecord] = field(default_factory=dict)
    messages: dict[tuple[str, str], CommunicationMessageRecord] = field(default_factory=dict)
    items: dict[tuple[str, str], CommunicationMailboxItemRecord] = field(default_factory=dict)
    observations: dict[tuple[str, str], CommunicationObservationRecord] = field(
        default_factory=dict
    )
    participants: dict[tuple[str, str, str, str], CommunicationParticipantRecord] = field(
        default_factory=dict
    )
    identifiers: dict[tuple[str, str, str, str, str], CommunicationIdentifierRecord] = field(
        default_factory=dict
    )
    quarantine: dict[tuple[str, str], CommunicationQuarantineRecord] = field(default_factory=dict)
    writes: list[str] = field(default_factory=list)
    commits: int = 0
    rollbacks: int = 0
    #: A write method name that raises on its next call (an injected failure).
    fail_on: set[str] = field(default_factory=set)
    #: The WP4 search's SQL answers, canned (the statement is the database tier's).
    query_shape: CommunicationSearchQueryShape = field(
        default_factory=lambda: CommunicationSearchQueryShape(english_nodes=1, simple_nodes=1)
    )
    search_rows: list[CommunicationSearchRow] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    search_calls: list[CommunicationSearchQuery] = field(default_factory=list)
    #: The WP5 context statement's answers, canned per Meeting ordinal, and its calls.
    context_rows: list[MeetingContextCandidateRow] = field(default_factory=list)
    context_calls: list[MeetingContextCandidateQuery] = field(default_factory=list)

    def write(self, name: str) -> None:
        self.writes.append(name)
        if name in self.fail_on:
            self.fail_on.discard(name)
            raise RuntimeError("injected failure")

    def row_count(self) -> int:
        return sum(
            len(table)
            for table in (
                self.sources,
                self.snapshots,
                self.paths,
                self.runs,
                self.run_snapshots,
                self.coverage,
                self.messages,
                self.items,
                self.observations,
                self.participants,
                self.identifiers,
                self.quarantine,
            )
        )

    def mine(self, principal_id: str, table: Mapping[Any, Any]) -> list[Any]:
        return [value for key, value in table.items() if key[0] == principal_id]


_ROWS = (
    "sources",
    "snapshots",
    "paths",
    "runs",
    "run_snapshots",
    "coverage",
    "messages",
    "items",
    "observations",
    "participants",
    "identifiers",
    "quarantine",
)


class FakeIngestion(IngestionRepository):
    def __init__(self, world: IngestWorld) -> None:
        self.w = world

    def insert_source(self, principal_id: str, source: IngestSourceRecord) -> None:
        self.w.write("insert_source")
        self.w.sources[(principal_id, source.ingest_source_id)] = source

    def get_source(self, principal_id: str, ingest_source_id: str) -> IngestSourceRecord | None:
        return self.w.sources.get((principal_id, ingest_source_id))

    def list_sources(
        self, principal_id: str, *, enabled_only: bool = False
    ) -> tuple[IngestSourceRecord, ...]:
        rows = [
            s for s in self.w.mine(principal_id, self.w.sources) if s.enabled or not enabled_only
        ]
        return tuple(sorted(rows, key=lambda s: s.ingest_source_id))

    def set_source_enabled(self, principal_id: str, ingest_source_id: str, enabled: bool) -> None:
        self.w.write("set_source_enabled")
        key = (principal_id, ingest_source_id)
        if key not in self.w.sources:
            raise RepositoryFailureError
        self.w.sources[key] = replace(self.w.sources[key], enabled=enabled)

    def find_snapshot(
        self, principal_id: str, ingest_source_id: str, file_sha256: str
    ) -> IngestSnapshotRecord | None:
        return next(
            (
                s
                for s in self.w.mine(principal_id, self.w.snapshots)
                if s.ingest_source_id == ingest_source_id and s.file_sha256 == file_sha256
            ),
            None,
        )

    def get_snapshot(self, principal_id: str, snapshot_id: str) -> IngestSnapshotRecord | None:
        return self.w.snapshots.get((principal_id, snapshot_id))

    def list_snapshots(
        self, principal_id: str, ingest_source_id: str
    ) -> tuple[IngestSnapshotRecord, ...]:
        rows = [
            s
            for s in self.w.mine(principal_id, self.w.snapshots)
            if s.ingest_source_id == ingest_source_id
        ]
        return tuple(sorted(rows, key=lambda s: (s.first_seen_at, s.snapshot_id)))

    def insert_snapshot(self, principal_id: str, snapshot: IngestSnapshotRecord) -> None:
        self.w.write("insert_snapshot")
        if self.find_snapshot(principal_id, snapshot.ingest_source_id, snapshot.file_sha256):
            raise GuardRefusalError("one_ingest_snapshot_per_source_content")
        self.w.snapshots[(principal_id, snapshot.snapshot_id)] = snapshot

    def finalize_snapshot(
        self,
        principal_id: str,
        snapshot_id: str,
        *,
        status: IngestSnapshotStatus,
        rejection_code: str | None,
        parser_version: str | None,
    ) -> None:
        self.w.write("finalize_snapshot")
        key = (principal_id, snapshot_id)
        if key not in self.w.snapshots:
            raise RepositoryFailureError
        current = self.w.snapshots[key]
        if current.status is not IngestSnapshotStatus.PENDING or status is (
            IngestSnapshotStatus.PENDING
        ):
            raise GuardRefusalError("a snapshot is finalized once")
        if (status is IngestSnapshotStatus.REJECTED) != (rejection_code is not None):
            raise GuardRefusalError("a_rejected_ingest_snapshot_names_its_code")
        self.w.snapshots[key] = replace(
            current, status=status, rejection_code=rejection_code, parser_version=parser_version
        )

    def insert_snapshot_path(self, principal_id: str, path: IngestSnapshotPathRecord) -> None:
        self.w.write("insert_snapshot_path")
        key = (principal_id, path.snapshot_id, path.relative_path)
        if key in self.w.paths:
            raise GuardRefusalError("ingest_snapshot_paths_pkey")
        if (principal_id, path.snapshot_id) not in self.w.snapshots:
            raise GuardRefusalError("a path names a snapshot")
        if path.superseded_by_snapshot_id is None and self.current_path(
            principal_id, path.ingest_source_id, path.relative_path
        ):
            raise GuardRefusalError("one_current_ingest_snapshot_per_path")
        self.w.paths[key] = path

    def current_path(
        self, principal_id: str, ingest_source_id: str, relative_path: str
    ) -> IngestSnapshotPathRecord | None:
        return next(
            (
                p
                for p in self.w.mine(principal_id, self.w.paths)
                if p.ingest_source_id == ingest_source_id
                and p.relative_path == relative_path
                and p.superseded_by_snapshot_id is None
            ),
            None,
        )

    def supersede_path(
        self,
        principal_id: str,
        snapshot_id: str,
        relative_path: str,
        *,
        superseded_by_snapshot_id: str,
        superseded_at: datetime,
    ) -> None:
        self.w.write("supersede_path")
        key = (principal_id, snapshot_id, relative_path)
        if key not in self.w.paths:
            raise RepositoryFailureError
        current = self.w.paths[key]
        if current.superseded_by_snapshot_id is not None:
            raise GuardRefusalError("a path is superseded once, from NULL")
        self.w.paths[key] = replace(
            current,
            superseded_by_snapshot_id=superseded_by_snapshot_id,
            superseded_at=superseded_at,
        )

    def list_snapshot_paths(
        self, principal_id: str, ingest_source_id: str
    ) -> tuple[IngestSnapshotPathRecord, ...]:
        rows = [
            p
            for p in self.w.mine(principal_id, self.w.paths)
            if p.ingest_source_id == ingest_source_id
        ]
        return tuple(sorted(rows, key=lambda p: (p.relative_path, p.first_seen_at, p.snapshot_id)))

    def list_paths_of_snapshot(
        self, principal_id: str, snapshot_id: str
    ) -> tuple[IngestSnapshotPathRecord, ...]:
        rows = [p for p in self.w.mine(principal_id, self.w.paths) if p.snapshot_id == snapshot_id]
        return tuple(sorted(rows, key=lambda p: (p.first_seen_at, p.relative_path)))

    def find_snapshot_path(
        self, principal_id: str, snapshot_id: str, relative_path: str
    ) -> IngestSnapshotPathRecord | None:
        return self.w.paths.get((principal_id, snapshot_id, relative_path))

    def insert_run(self, principal_id: str, run: IngestRunRecord) -> None:
        self.w.write("insert_run")
        self.w.runs[(principal_id, run.run_id)] = run

    def get_run(self, principal_id: str, run_id: str) -> IngestRunRecord | None:
        return self.w.runs.get((principal_id, run_id))

    def finish_run(
        self,
        principal_id: str,
        run_id: str,
        *,
        finished_at: datetime,
        outcome: IngestRunOutcome,
        counts: Mapping[str, int],
    ) -> None:
        self.w.write("finish_run")
        key = (principal_id, run_id)
        if key not in self.w.runs:
            raise RepositoryFailureError
        if self.w.runs[key].finished_at is not None:
            raise GuardRefusalError("a run finishes once")
        self.w.runs[key] = replace(
            self.w.runs[key], finished_at=finished_at, outcome=outcome, counts=dict(counts)
        )

    def link_run_snapshot(self, principal_id: str, link: IngestRunSnapshotRecord) -> None:
        self.w.write("link_run_snapshot")
        key = (principal_id, link.run_id, link.snapshot_id)
        if key in self.w.run_snapshots:
            raise GuardRefusalError("ingest_run_snapshots_pkey")
        self.w.run_snapshots[key] = link

    def list_run_snapshots(
        self, principal_id: str, run_id: str
    ) -> tuple[IngestRunSnapshotRecord, ...]:
        rows = [
            link
            for link in self.w.mine(principal_id, self.w.run_snapshots)
            if link.run_id == run_id
        ]
        return tuple(sorted(rows, key=lambda link: (link.recorded_at, link.snapshot_id)))

    def insert_coverage_window(self, principal_id: str, window: IngestCoverageWindowRecord) -> None:
        self.w.write("insert_coverage_window")
        key = (principal_id, window.snapshot_id)
        if key in self.w.coverage:
            raise GuardRefusalError("one_ingest_coverage_window_per_snapshot")
        self.w.coverage[key] = window

    def list_coverage_windows(
        self, principal_id: str, ingest_source_id: str
    ) -> tuple[IngestCoverageWindowRecord, ...]:
        rows = [
            c
            for c in self.w.mine(principal_id, self.w.coverage)
            if c.ingest_source_id == ingest_source_id
        ]
        return tuple(sorted(rows, key=lambda c: (c.start_utc, c.end_utc, c.coverage_window_id)))

    def get_coverage_window(
        self, principal_id: str, snapshot_id: str
    ) -> IngestCoverageWindowRecord | None:
        return self.w.coverage.get((principal_id, snapshot_id))


class FakeCommunications(CommunicationsRepository):
    def __init__(self, world: IngestWorld) -> None:
        self.w = world

    def get_message(
        self, principal_id: str, message_id: str, *, for_update: bool = False
    ) -> CommunicationMessageRecord | None:
        return self.w.messages.get((principal_id, message_id))

    def find_message_by_identity(
        self,
        principal_id: str,
        mailbox_ref: str,
        identity_kind: str,
        identity_value: str,
        *,
        for_update: bool = False,
    ) -> CommunicationMessageRecord | None:
        return next(
            (
                m
                for m in self.w.mine(principal_id, self.w.messages)
                if (m.mailbox_ref, m.identity_kind, m.identity_value)
                == (mailbox_ref, identity_kind, identity_value)
            ),
            None,
        )

    def find_item_by_provider_id(
        self, principal_id: str, mailbox_ref: str, provider_id: str
    ) -> CommunicationMailboxItemRecord | None:
        return next(
            (
                i
                for i in self.w.mine(principal_id, self.w.items)
                if (i.mailbox_ref, i.provider_id) == (mailbox_ref, provider_id)
            ),
            None,
        )

    def find_message_by_provider_id(
        self,
        principal_id: str,
        mailbox_ref: str,
        provider_id: str,
        *,
        for_update: bool = False,
    ) -> CommunicationMessageRecord | None:
        item = self.find_item_by_provider_id(principal_id, mailbox_ref, provider_id)
        return None if item is None else self.get_message(principal_id, item.message_id)

    def list_items(
        self, principal_id: str, message_id: str
    ) -> tuple[CommunicationMailboxItemRecord, ...]:
        rows = [i for i in self.w.mine(principal_id, self.w.items) if i.message_id == message_id]
        return tuple(sorted(rows, key=lambda i: i.item_id))

    def insert_message(self, principal_id: str, message: CommunicationMessageRecord) -> None:
        self.w.write("insert_message")
        if self.find_message_by_identity(
            principal_id, message.mailbox_ref, message.identity_kind, message.identity_value
        ):
            raise GuardRefusalError("one_communication_message_per_identity")
        projection = message.projection
        if projection.search_text is not None and projection.body_state in {
            "withheld",
            "truncated",
        }:
            raise GuardRefusalError("a_withheld_or_truncated_body_has_no_search_text")
        self.w.messages[(principal_id, message.message_id)] = message

    def _change(self, principal_id: str, message_id: str, **changes: object) -> None:
        key = (principal_id, message_id)
        if key not in self.w.messages:
            raise RepositoryFailureError
        self.w.messages[key] = replace(self.w.messages[key], **changes)  # type: ignore[arg-type]

    def update_message_projection(
        self,
        principal_id: str,
        message_id: str,
        *,
        projection: CommunicationProjection,
        latest_snapshot_id: str,
    ) -> None:
        self.w.write("update_message_projection")
        self._change(
            principal_id, message_id, projection=projection, latest_snapshot_id=latest_snapshot_id
        )

    def set_latest_snapshot(self, principal_id: str, message_id: str, snapshot_id: str) -> None:
        self.w.write("set_latest_snapshot")
        self._change(principal_id, message_id, latest_snapshot_id=snapshot_id)

    def set_message_flags(
        self,
        principal_id: str,
        message_id: str,
        *,
        identity_conflict: bool | None = None,
        participants_reconciled: bool | None = None,
        participants_disagreed: bool | None = None,
    ) -> None:
        self.w.write("set_message_flags")
        changes = {
            name: value
            for name, value in (
                ("identity_conflict", identity_conflict),
                ("participants_reconciled", participants_reconciled),
                ("participants_disagreed", participants_disagreed),
            )
            if value is not None
        }
        if not changes:
            raise ValueError("set_message_flags names no flag")
        self._change(principal_id, message_id, **changes)

    def set_source_unavailable(
        self, principal_id: str, message_id: str, *, source_unavailable: bool
    ) -> None:
        self.w.write("set_source_unavailable")
        self._change(principal_id, message_id, source_unavailable=source_unavailable)

    def set_identifiers_version(self, principal_id: str, message_id: str, version: str) -> None:
        self.w.write("set_identifiers_version")
        self._change(principal_id, message_id, identifiers_version=version)

    def insert_item(self, principal_id: str, item: CommunicationMailboxItemRecord) -> None:
        self.w.write("insert_item")
        if self.find_item_by_provider_id(principal_id, item.mailbox_ref, item.provider_id):
            raise GuardRefusalError("one_mailbox_item_per_provider_id")
        if (principal_id, item.message_id) not in self.w.messages:
            raise GuardRefusalError("an item names a message")
        self.w.items[(principal_id, item.item_id)] = item

    def _ordinal_taken(self, principal_id: str, snapshot_id: str, ordinal: int) -> bool:
        return any(
            (row.snapshot_id, row.record_ordinal) == (snapshot_id, ordinal)
            for table in (self.w.observations, self.w.quarantine)
            for row in self.w.mine(principal_id, table)
        )

    def insert_observation(
        self, principal_id: str, observation: CommunicationObservationRecord
    ) -> None:
        self.w.write("insert_observation")
        if self._ordinal_taken(principal_id, observation.snapshot_id, observation.record_ordinal):
            raise GuardRefusalError("one row per record ordinal")
        if (principal_id, observation.item_id) not in self.w.items:
            raise GuardRefusalError("an observation names an item")
        self.w.observations[(principal_id, observation.observation_id)] = observation

    def insert_participants(
        self, principal_id: str, participants: Sequence[CommunicationParticipantRecord]
    ) -> int:
        self.w.write("insert_participants")
        added = 0
        for participant in participants:
            key = (principal_id, participant.message_id, participant.field, participant.address)
            if key not in self.w.participants:
                self.w.participants[key] = participant
                added += 1
        return added

    def list_participants(
        self, principal_id: str, message_id: str
    ) -> tuple[CommunicationParticipantRecord, ...]:
        rows = [
            p for p in self.w.mine(principal_id, self.w.participants) if p.message_id == message_id
        ]
        return tuple(sorted(rows, key=lambda p: (p.field, p.address)))

    def insert_identifiers(
        self, principal_id: str, identifiers: Sequence[CommunicationIdentifierRecord]
    ) -> int:
        self.w.write("insert_identifiers")
        added = 0
        for identifier in identifiers:
            key = (
                principal_id,
                identifier.message_id,
                identifier.kind,
                identifier.value,
                identifier.extractor_version,
            )
            if key not in self.w.identifiers:
                self.w.identifiers[key] = identifier
                added += 1
        return added

    def list_identifiers(
        self, principal_id: str, message_id: str
    ) -> tuple[CommunicationIdentifierRecord, ...]:
        rows = [
            i for i in self.w.mine(principal_id, self.w.identifiers) if i.message_id == message_id
        ]
        return tuple(sorted(rows, key=lambda i: (i.extractor_version, i.kind, i.value)))

    def insert_quarantine(
        self, principal_id: str, quarantine: CommunicationQuarantineRecord
    ) -> None:
        self.w.write("insert_quarantine")
        if self._ordinal_taken(principal_id, quarantine.snapshot_id, quarantine.record_ordinal):
            raise GuardRefusalError("one row per record ordinal")
        self.w.quarantine[(principal_id, quarantine.quarantine_id)] = quarantine

    def list_observations(
        self, principal_id: str, message_id: str
    ) -> tuple[CommunicationObservationRecord, ...]:
        items = {i.item_id for i in self.list_items(principal_id, message_id)}
        rows = [o for o in self.w.mine(principal_id, self.w.observations) if o.item_id in items]
        return tuple(sorted(rows, key=lambda o: (o.snapshot_id, o.record_ordinal)))

    def tally_snapshot(self, principal_id: str, snapshot_id: str) -> CommunicationSnapshotTally:
        return CommunicationSnapshotTally(
            observations=sum(
                1
                for o in self.w.mine(principal_id, self.w.observations)
                if o.snapshot_id == snapshot_id
            ),
            quarantined=sum(
                1
                for q in self.w.mine(principal_id, self.w.quarantine)
                if q.snapshot_id == snapshot_id
            ),
        )

    def _rederive_due(
        self,
        principal_id: str,
        search_text_version: str,
        identifiers_version: str,
        ingest_source_id: str | None,
    ) -> list[CommunicationMessageRecord]:
        def in_scope(message: CommunicationMessageRecord) -> bool:
            if ingest_source_id is None:
                return True
            snapshot = self.w.snapshots.get((principal_id, message.projection.text_snapshot_id))
            return snapshot is not None and snapshot.ingest_source_id == ingest_source_id

        due = [
            m
            for m in self.w.mine(principal_id, self.w.messages)
            if (
                m.projection.search_text_version != search_text_version
                or m.identifiers_version != identifiers_version
                or m.source_unavailable
            )
            and in_scope(m)
        ]
        return sorted(due, key=lambda m: m.message_id)

    def list_rederive_due(
        self,
        principal_id: str,
        *,
        search_text_version: str,
        identifiers_version: str,
        ingest_source_id: str | None = None,
        limit: int,
    ) -> tuple[CommunicationRederiveDueRecord, ...]:
        due = self._rederive_due(
            principal_id, search_text_version, identifiers_version, ingest_source_id
        )
        return tuple(
            CommunicationRederiveDueRecord(
                message_id=m.message_id,
                search_text_version=m.projection.search_text_version,
                identifiers_version=m.identifiers_version,
                source_unavailable=m.source_unavailable,
                text_snapshot_id=m.projection.text_snapshot_id,
            )
            for m in due[:limit]
        )

    def count_rederive_due(
        self,
        principal_id: str,
        *,
        search_text_version: str,
        identifiers_version: str,
        ingest_source_id: str | None = None,
    ) -> int:
        return len(
            self._rederive_due(
                principal_id, search_text_version, identifiers_version, ingest_source_id
            )
        )

    # --- the WP4 reads: the plain ones modelled; the SQL ones canned on the world ----------

    def search_query_shape(self, query: str) -> CommunicationSearchQueryShape:
        self.w.search_queries.append(query)
        return self.w.query_shape

    def search_messages(
        self, principal_id: str, query: CommunicationSearchQuery
    ) -> tuple[CommunicationSearchRow, ...]:
        self.w.search_calls.append(query)
        return tuple(self.w.search_rows[: query.limit])

    def list_message_lanes(
        self, principal_id: str, message_ids: Sequence[str]
    ) -> Mapping[str, tuple[tuple[str, str], ...]]:
        lanes: dict[str, set[tuple[str, str]]] = {}
        for (owner, _), item in self.w.items.items():
            if owner != principal_id or item.message_id not in message_ids:
                continue
            for observation in self.w.mine(principal_id, self.w.observations):
                if observation.item_id == item.item_id:
                    lanes.setdefault(item.message_id, set()).add(
                        (observation.folder_role, observation.lane_verification)
                    )
        return {message_id: tuple(sorted(found)) for message_id, found in lanes.items()}

    def list_messages(
        self, principal_id: str, message_ids: Sequence[str]
    ) -> tuple[CommunicationMessageRecord, ...]:
        return tuple(
            m for m in self.w.mine(principal_id, self.w.messages) if m.message_id in message_ids
        )

    def list_conversation_page(
        self,
        principal_id: str,
        conversation_id: str,
        *,
        after: tuple[datetime, str] | None,
        limit: int,
    ) -> tuple[CommunicationMessageRecord, ...]:
        rows = sorted(
            (
                m
                for m in self.w.mine(principal_id, self.w.messages)
                if m.conversation_id == conversation_id
            ),
            key=lambda m: (m.message_time, m.message_id),
        )
        if after is not None:
            rows = [m for m in rows if (m.message_time, m.message_id) > after]
        return tuple(rows[:limit])

    def count_identifier_version_pending(self, principal_id: str, version: str) -> int:
        return sum(
            1
            for m in self.w.mine(principal_id, self.w.messages)
            if m.identifiers_version != version
        )

    def list_search_text_versions(self, principal_id: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    m.projection.search_text_version
                    for m in self.w.mine(principal_id, self.w.messages)
                }
            )
        )

    # --- the WP5 context reads: the plain ones modelled; the statement canned -------------

    def context_self_addresses(
        self, principal_id: str, *, limit: int
    ) -> CommunicationSelfAddresses:
        # `self_from_sent_lane_v2`: message -> whether any of its `sent` lanes is verified.
        sent: dict[str, bool] = {}
        for item in self.w.mine(principal_id, self.w.items):
            for observation in self.w.mine(principal_id, self.w.observations):
                if observation.item_id == item.item_id and observation.folder_role == "sent":
                    sent[item.message_id] = sent.get(item.message_id, False) or (
                        observation.lane_verification == "verified"
                    )
        verified: dict[str, bool] = {}
        for p in self.w.mine(principal_id, self.w.participants):
            if p.field == "from" and p.message_id in sent:
                verified[p.address] = verified.get(p.address, False) or sent[p.message_id]
        any_verified = any(verified.values())
        owners = sorted(a for a, v in verified.items() if v == any_verified)
        return CommunicationSelfAddresses(
            addresses=tuple(owners[:limit]), total=len(owners), verified=any_verified
        )

    def non_ascii_participant_addresses(self, principal_id: str, *, limit: int) -> tuple[str, ...]:
        found = {
            p.address
            for p in self.w.mine(principal_id, self.w.participants)
            if not p.address.isascii()
        }
        return tuple(sorted(found)[:limit])

    def context_candidates(
        self, principal_id: str, query: MeetingContextCandidateQuery
    ) -> tuple[MeetingContextCandidateRow, ...]:
        self.w.context_calls.append(query)
        ordinals = {meeting.ordinal for meeting in query.meetings}
        kept: dict[int, int] = {}
        rows: list[MeetingContextCandidateRow] = []
        for row in self.w.context_rows:
            if row.ordinal in ordinals and kept.get(row.ordinal, 0) < query.limit:
                kept[row.ordinal] = kept.get(row.ordinal, 0) + 1
                rows.append(row)
        return tuple(rows)

    def list_message_identifiers(
        self, principal_id: str, message_ids: Sequence[str], *, kind: str, version: str
    ) -> Mapping[str, tuple[str, ...]]:
        found: dict[str, set[str]] = {}
        for identifier in self.w.mine(principal_id, self.w.identifiers):
            if (
                identifier.message_id in message_ids
                and identifier.kind == kind
                and identifier.extractor_version == version
            ):
                found.setdefault(identifier.message_id, set()).add(identifier.value)
        return {message_id: tuple(sorted(values)) for message_id, values in sorted(found.items())}


class IngestUnitOfWork(FakeUnitOfWork):
    """`FakeUnitOfWork` with the two WP3a planes modelled, and real rollback."""

    def __init__(self, world: IngestWorld, meetings: World | None = None) -> None:
        # `meetings`: a shared general `World` (the WP3b-S3 applier reads the
        # ingestion plane beside the Meeting and staging planes); fresh otherwise.
        super().__init__(World() if meetings is None else meetings)
        self._ingest_world = world
        self._saved: dict[str, Any] | None = None

    def __enter__(self) -> UnitOfWork:
        self._saved = {name: copy.copy(getattr(self._ingest_world, name)) for name in _ROWS}
        return super().__enter__()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        super().__exit__(exc_type, exc, traceback)
        if exc is None:
            self._ingest_world.commits += 1
        else:
            self._ingest_world.rollbacks += 1
            assert self._saved is not None
            for name, saved in self._saved.items():
                setattr(self._ingest_world, name, saved)
        self._saved = None

    @property
    def ingestion(self) -> IngestionRepository:
        return FakeIngestion(self._ingest_world)

    @property
    def communications(self) -> CommunicationsRepository:
        return FakeCommunications(self._ingest_world)


def unit_of_work_factory(world: IngestWorld) -> Callable[[], UnitOfWork]:
    return lambda: IngestUnitOfWork(world)


# ---- the file workspace store ------------------------------------------------------


@dataclass
class _File:
    data: bytes
    generation: int


class _Reader(FileWorkspaceReader):
    def __init__(self, store: FakeStore, path: str, version: str) -> None:
        self._store = store
        self._path = path
        self.version = version
        self.size = len(store.files[path].data)
        self.closed = False

    def _check(self) -> None:
        if self._store.version_of(self._path) != self.version:
            raise FilesRefusal("path", FilesReason.EXTERNAL_CHANGE_DETECTED)

    def read_range(self, start: int, length: int) -> Iterator[bytes]:
        self._check()
        data = self._store.files[self._path].data[start : start + length]
        hook = self._store.during_read.pop(self._path, None)
        for offset in range(0, len(data), 7):
            if offset and hook is not None:
                hook()
                hook = None
                self._check()
            yield data[offset : offset + 7]

    def sha256(self) -> str:
        self._check()
        return hashlib.sha256(self._store.files[self._path].data).hexdigest()

    def close(self) -> None:
        self.closed = True


class FakeStore(FileWorkspaceStore):
    """The read path over `files` (path -> bytes); every other method fails the test."""

    def __init__(self, page_size: int | None = None) -> None:
        self.files: dict[str, _File] = {}
        self.calls: list[str] = []
        self.page_size = page_size
        #: path -> a callable run once mid-read (to change a file while it is read).
        self.during_read: dict[str, Callable[[], None]] = {}
        self._generation = 0

    def put(self, path: str, data: bytes) -> None:
        self._generation += 1
        self.files[path] = _File(data, self._generation)

    def remove(self, path: str) -> None:
        del self.files[path]

    def version_of(self, path: str) -> str:
        file = self.files[path]
        return f"fv1_{file.generation:08d}_{len(file.data)}"

    def _entry(self, path: str) -> FileWorkspaceEntry:
        file = self.files[path]
        return FileWorkspaceEntry(
            path=path,
            name=path.rsplit("/", 1)[-1],
            kind=EntryKind.FILE,
            size=len(file.data),
            mtime_ns=file.generation,
            version=self.version_of(path),
        )

    def list_directory(
        self, path: str, *, after: str | None = None, page_size: int = 200
    ) -> FileWorkspacePage:
        self.calls.append("list_directory")
        size = self.page_size or page_size
        prefix = f"{path}/" if path else ""
        names: set[str] = set()
        directories: set[str] = set()
        for full in self.files:
            if not full.startswith(prefix):
                continue
            rest = full[len(prefix) :]
            if "/" in rest:
                directories.add(rest.split("/", 1)[0])
            else:
                names.add(rest)
        if path and not (names or directories):
            raise FilesRefusal("path", FilesReason.NOT_FOUND)
        entries: list[FileWorkspaceEntry] = []
        for name in sorted(names | directories):
            if after is not None and name <= after:
                continue
            if name in names:
                entries.append(self._entry(prefix + name))
            else:
                entries.append(
                    FileWorkspaceEntry(
                        path=prefix + name,
                        name=name,
                        kind=EntryKind.DIRECTORY,
                        size=None,
                        mtime_ns=0,
                        version="fv1_dir",
                    )
                )
        page = entries[:size]
        more = len(entries) > size
        return FileWorkspacePage(tuple(page), next_after=page[-1].name if more else None)

    def stat(self, path: str, *, include_sha256: bool = False) -> FileWorkspaceEntry:
        self.calls.append("stat")
        if path not in self.files:
            raise FilesRefusal("path", FilesReason.NOT_FOUND)
        return self._entry(path)

    def open_download(self, path: str, *, expected_version: str) -> FileWorkspaceReader:
        self.calls.append("open_download")
        if path not in self.files:
            raise FilesRefusal("path", FilesReason.NOT_FOUND)
        if self.version_of(path) != expected_version:
            raise FilesRefusal("path", FilesReason.EXTERNAL_CHANGE_DETECTED)
        return _Reader(self, path, expected_version)


def _forbidden(name: str) -> Callable[..., object]:
    def refuse(self: FakeStore, *args: object, **kwargs: object) -> object:
        self.calls.append(name)
        raise AssertionError(f"the ingestion lifecycle called FileWorkspaceStore.{name}")

    return refuse


for _name in sorted(FakeStore.__abstractmethods__):
    setattr(FakeStore, _name, _forbidden(_name))
FakeStore.__abstractmethods__ = frozenset()
