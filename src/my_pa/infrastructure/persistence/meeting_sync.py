"""The meeting sync staging and reconciliation tables, behind `MeetingSyncRepository` (WP3b).

Five tables are reached here and nowhere else: `meeting_sync_publications`,
`meeting_sync_events`, `meeting_provider_review_marks`,
`meeting_provider_reconciliation_passes` and `meeting_provider_key_tombstones`
(Manager rulings D1, D3, D4, D5 and D8; the WP3b revision `61fafdfd2986`).

**The partition is reached through the guard, never written by hand.** The
`persistence/ingestion.py` idiom: every SELECT and UPDATE composes `_mine` (a
one-line wrapper over `partition_criterion`), every INSERT composes `_bound` (a
one-line wrapper over `principal_bound_values`), and the one join (a
publication to its snapshot, for the apply order) composes
`matching_partition_criterion`. The WP3b-S4 review reads join the Meeting
plane (`meetings`, `meeting_provider_bindings`) the same way: every table they
name is reached through `_mine` and correlated by
`matching_partition_criterion`. The Principal is a parameter; nothing here
reads it back from a row or a record.

**The database guards are the authority.** A second apply of a publication,
any change to an event, a mark, the latch or a tombstone, and a second latch
are refused by the revision's triggers and keys; this module does not pre-check
and absorb them, so the caller sees the refusal. The one exception is the
review mark, which is idempotent by Meeting by contract (`ON CONFLICT DO
NOTHING`). A missing row on a targeted update is `RepositoryFailureError`.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from typing import Any, Final

from sqlalchemy import (
    ColumnElement,
    Table,
    and_,
    exists,
    func,
    insert,
    literal,
    or_,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Row

from my_pa.contracts.ports import (
    MeetingProviderKeyTombstoneRecord,
    MeetingProviderReconciliationPassRecord,
    MeetingProviderReviewMarkRecord,
    MeetingReviewScopeCounts,
    MeetingSyncApplyOutcome,
    MeetingSyncEventRecord,
    MeetingSyncPublicationRecord,
    MeetingSyncRepository,
    RepositoryFailureError,
    StagedProviderEvent,
    UnreviewedMeetingRecord,
)
from my_pa.domain.meeting.model import MeetingCursorError, MeetingStatus
from my_pa.domain.meeting_sync.model import EventStatus, ProviderEventIdFormat
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    matching_partition_criterion,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    ingest_snapshots,
    meeting_provider_bindings,
    meeting_provider_key_tombstones,
    meeting_provider_reconciliation_passes,
    meeting_provider_review_marks,
    meeting_sync_events,
    meeting_sync_publications,
    meetings,
)

__all__ = ["SqlMeetingSyncRepository"]


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


_PUBLICATION_COLUMNS: Final = (
    meeting_sync_publications.c.snapshot_id,
    meeting_sync_publications.c.ingest_source_id,
    meeting_sync_publications.c.generated_at_utc,
    meeting_sync_publications.c.record_count,
    meeting_sync_publications.c.accepted_count,
    meeting_sync_publications.c.quarantined_count,
    meeting_sync_publications.c.staged_at,
    meeting_sync_publications.c.coverage_start_utc,
    meeting_sync_publications.c.coverage_end_utc,
    meeting_sync_publications.c.coverage_calendar_refs,
    meeting_sync_publications.c.applied_at,
    meeting_sync_publications.c.apply_outcome,
    meeting_sync_publications.c.apply_counts,
)

_EVENT_COLUMNS: Final = (
    meeting_sync_events.c.event_id,
    meeting_sync_events.c.snapshot_id,
    meeting_sync_events.c.record_ordinal,
    meeting_sync_events.c.calendar_ref,
    meeting_sync_events.c.ical_uid,
    meeting_sync_events.c.series_ical_uid,
    meeting_sync_events.c.occurrence_original_start_utc,
    meeting_sync_events.c.start_utc,
    meeting_sync_events.c.end_utc,
    meeting_sync_events.c.timezone_name,
    meeting_sync_events.c.status,
    meeting_sync_events.c.title,
    meeting_sync_events.c.location_text,
    meeting_sync_events.c.virtual_meeting_url,
    meeting_sync_events.c.provider_event_id,
    meeting_sync_events.c.provider_event_id_format,
    meeting_sync_events.c.staged_at,
)

_MARK_COLUMNS: Final = (
    meeting_provider_review_marks.c.meeting_id,
    meeting_provider_review_marks.c.marked_at,
)

_PASS_COLUMNS: Final = (
    meeting_provider_reconciliation_passes.c.completed_at,
    meeting_provider_reconciliation_passes.c.reviewed_meetings,
    meeting_provider_reconciliation_passes.c.reconcile_correlation_id,
)

_TOMBSTONE_COLUMNS: Final = (
    meeting_provider_key_tombstones.c.binding_id,
    meeting_provider_key_tombstones.c.meeting_id,
    meeting_provider_key_tombstones.c.calendar_ref,
    meeting_provider_key_tombstones.c.ical_uid,
    meeting_provider_key_tombstones.c.occurrence_original_start_utc,
    meeting_provider_key_tombstones.c.series_ical_uid,
    meeting_provider_key_tombstones.c.unbound_at,
    meeting_provider_key_tombstones.c.meeting_history_id,
)


def _same_original(left: Table, right: Table) -> ColumnElement[bool]:
    """Null-safe equality of two tables' `occurrence_original_start_utc`."""
    a = left.c.occurrence_original_start_utc
    b = right.c.occurrence_original_start_utc
    return or_(and_(a.is_(None), b.is_(None)), a == b)


def _same_key(left: Table, right: Table) -> ColumnElement[bool]:
    """Two tables' rows name the same provider key, in the same partition."""
    return and_(
        matching_partition_criterion(left, right),
        left.c.calendar_ref == right.c.calendar_ref,
        left.c.ical_uid == right.c.ical_uid,
        _same_original(left, right),
    )


def _in_review_scope(principal_id: str, since: datetime) -> ColumnElement[bool]:
    """A Meeting of the Principal the pass reviews (D3): not cancelled, recent enough."""
    return and_(
        _mine(meetings, principal_id),
        meetings.c.status != MeetingStatus.CANCELLED.value,
        meetings.c.start_at >= since,
    )


def _unreviewed() -> ColumnElement[bool]:
    """The Meeting has neither a provider binding nor a review mark."""
    bound = exists().where(
        matching_partition_criterion(meeting_provider_bindings, meetings),
        meeting_provider_bindings.c.meeting_id == meetings.c.meeting_id,
    )
    marked = exists().where(
        matching_partition_criterion(meeting_provider_review_marks, meetings),
        meeting_provider_review_marks.c.meeting_id == meetings.c.meeting_id,
    )
    return and_(~bound, ~marked)


def _to_publication(row: Row[Any]) -> MeetingSyncPublicationRecord:
    return MeetingSyncPublicationRecord(
        snapshot_id=row.snapshot_id,
        ingest_source_id=row.ingest_source_id,
        generated_at_utc=row.generated_at_utc,
        record_count=row.record_count,
        accepted_count=row.accepted_count,
        quarantined_count=row.quarantined_count,
        staged_at=row.staged_at,
        coverage_start_utc=row.coverage_start_utc,
        coverage_end_utc=row.coverage_end_utc,
        coverage_calendar_refs=(
            None if row.coverage_calendar_refs is None else tuple(row.coverage_calendar_refs)
        ),
        applied_at=row.applied_at,
        apply_outcome=(
            None if row.apply_outcome is None else MeetingSyncApplyOutcome(row.apply_outcome)
        ),
        apply_counts=None if row.apply_counts is None else dict(row.apply_counts),
    )


def _to_event(row: Row[Any]) -> MeetingSyncEventRecord:
    return MeetingSyncEventRecord(
        event_id=row.event_id,
        snapshot_id=row.snapshot_id,
        record_ordinal=row.record_ordinal,
        calendar_ref=row.calendar_ref,
        ical_uid=row.ical_uid,
        series_ical_uid=row.series_ical_uid,
        occurrence_original_start_utc=row.occurrence_original_start_utc,
        start_utc=row.start_utc,
        end_utc=row.end_utc,
        timezone_name=row.timezone_name,
        status=EventStatus(row.status),
        title=row.title,
        location_text=row.location_text,
        virtual_meeting_url=row.virtual_meeting_url,
        provider_event_id=row.provider_event_id,
        provider_event_id_format=ProviderEventIdFormat(row.provider_event_id_format),
        staged_at=row.staged_at,
    )


def _to_mark(row: Row[Any]) -> MeetingProviderReviewMarkRecord:
    return MeetingProviderReviewMarkRecord(meeting_id=row.meeting_id, marked_at=row.marked_at)


def _to_pass(row: Row[Any]) -> MeetingProviderReconciliationPassRecord:
    return MeetingProviderReconciliationPassRecord(
        completed_at=row.completed_at,
        reviewed_meetings=row.reviewed_meetings,
        reconcile_correlation_id=row.reconcile_correlation_id,
    )


def _to_tombstone(row: Row[Any]) -> MeetingProviderKeyTombstoneRecord:
    return MeetingProviderKeyTombstoneRecord(
        binding_id=row.binding_id,
        meeting_id=row.meeting_id,
        calendar_ref=row.calendar_ref,
        ical_uid=row.ical_uid,
        occurrence_original_start_utc=row.occurrence_original_start_utc,
        series_ical_uid=row.series_ical_uid,
        unbound_at=row.unbound_at,
        meeting_history_id=row.meeting_history_id,
    )


class SqlMeetingSyncRepository(MeetingSyncRepository):
    """`MeetingSyncRepository`, over the general unit of work's `Connection`.

    Takes the connection rather than opening one: the caller owns the
    transaction, and this class only issues statements on it. Nothing here
    commits.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    # --- staging -------------------------------------------------------------

    def insert_publication(
        self, principal_id: str, publication: MeetingSyncPublicationRecord
    ) -> None:
        values: dict[str, object] = {
            "snapshot_id": publication.snapshot_id,
            "ingest_source_id": publication.ingest_source_id,
            "generated_at_utc": publication.generated_at_utc,
            "record_count": publication.record_count,
            "accepted_count": publication.accepted_count,
            "quarantined_count": publication.quarantined_count,
            "staged_at": publication.staged_at,
            "coverage_start_utc": publication.coverage_start_utc,
            "coverage_end_utc": publication.coverage_end_utc,
            "coverage_calendar_refs": (
                None
                if publication.coverage_calendar_refs is None
                else list(publication.coverage_calendar_refs)
            ),
            "applied_at": publication.applied_at,
            "apply_outcome": (
                None if publication.apply_outcome is None else publication.apply_outcome.value
            ),
        }
        if publication.apply_counts is not None:
            # Omitted rather than bound to `None`: a bound `None` is a JSON null,
            # not SQL NULL (the `structured_content` precedent in `tables.py`).
            values["apply_counts"] = dict(publication.apply_counts)
        self._connection.execute(
            insert(meeting_sync_publications).values(
                _bound(meeting_sync_publications, principal_id, values)
            )
        )

    def get_publication(
        self, principal_id: str, snapshot_id: str
    ) -> MeetingSyncPublicationRecord | None:
        row = self._connection.execute(
            select(*_PUBLICATION_COLUMNS).where(
                _mine(meeting_sync_publications, principal_id),
                meeting_sync_publications.c.snapshot_id == snapshot_id,
            )
        ).one_or_none()
        return None if row is None else _to_publication(row)

    def list_publications(
        self, principal_id: str, ingest_source_id: str, *, unapplied_only: bool = False
    ) -> tuple[MeetingSyncPublicationRecord, ...]:
        statement = (
            select(*_PUBLICATION_COLUMNS)
            .join(
                ingest_snapshots,
                matching_partition_criterion(ingest_snapshots, meeting_sync_publications)
                & (ingest_snapshots.c.snapshot_id == meeting_sync_publications.c.snapshot_id),
            )
            .where(
                _mine(meeting_sync_publications, principal_id),
                meeting_sync_publications.c.ingest_source_id == ingest_source_id,
            )
        )
        if unapplied_only:
            statement = statement.where(meeting_sync_publications.c.applied_at.is_(None))
        rows = self._connection.execute(
            statement.order_by(
                meeting_sync_publications.c.generated_at_utc,
                ingest_snapshots.c.file_sha256,
                meeting_sync_publications.c.snapshot_id,
            )
        )
        return tuple(_to_publication(row) for row in rows)

    def complete_publication(
        self,
        principal_id: str,
        snapshot_id: str,
        *,
        applied_at: datetime,
        apply_outcome: MeetingSyncApplyOutcome,
        apply_counts: Mapping[str, int],
    ) -> None:
        changed = self._connection.execute(
            update(meeting_sync_publications)
            .where(
                _mine(meeting_sync_publications, principal_id),
                meeting_sync_publications.c.snapshot_id == snapshot_id,
            )
            .values(
                applied_at=applied_at,
                apply_outcome=apply_outcome.value,
                apply_counts=dict(apply_counts),
            )
            .returning(meeting_sync_publications.c.snapshot_id)
        ).first()
        if changed is None:
            raise RepositoryFailureError

    def insert_events(self, principal_id: str, events: Sequence[MeetingSyncEventRecord]) -> None:
        if not events:
            return
        self._connection.execute(
            insert(meeting_sync_events),
            [
                _bound(
                    meeting_sync_events,
                    principal_id,
                    {
                        "event_id": event.event_id,
                        "snapshot_id": event.snapshot_id,
                        "record_ordinal": event.record_ordinal,
                        "calendar_ref": event.calendar_ref,
                        "ical_uid": event.ical_uid,
                        "series_ical_uid": event.series_ical_uid,
                        "occurrence_original_start_utc": event.occurrence_original_start_utc,
                        "start_utc": event.start_utc,
                        "end_utc": event.end_utc,
                        "timezone_name": event.timezone_name,
                        "status": event.status.value,
                        "title": event.title,
                        "location_text": event.location_text,
                        "virtual_meeting_url": event.virtual_meeting_url,
                        "provider_event_id": event.provider_event_id,
                        "provider_event_id_format": event.provider_event_id_format.value,
                        "staged_at": event.staged_at,
                    },
                )
                for event in events
            ],
        )

    def list_events(
        self, principal_id: str, snapshot_id: str
    ) -> tuple[MeetingSyncEventRecord, ...]:
        rows = self._connection.execute(
            select(*_EVENT_COLUMNS)
            .where(
                _mine(meeting_sync_events, principal_id),
                meeting_sync_events.c.snapshot_id == snapshot_id,
            )
            .order_by(meeting_sync_events.c.record_ordinal)
        )
        return tuple(_to_event(row) for row in rows)

    def get_event(self, principal_id: str, event_id: str) -> MeetingSyncEventRecord | None:
        row = self._connection.execute(
            select(*_EVENT_COLUMNS).where(
                _mine(meeting_sync_events, principal_id),
                meeting_sync_events.c.event_id == event_id,
            )
        ).one_or_none()
        return None if row is None else _to_event(row)

    def list_staging_sources(self, principal_id: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            select(meeting_sync_publications.c.ingest_source_id)
            .where(_mine(meeting_sync_publications, principal_id))
            .distinct()
            .order_by(meeting_sync_publications.c.ingest_source_id)
        )
        return tuple(row.ingest_source_id for row in rows)

    def list_unbound_events(
        self, principal_id: str, snapshot_id: str
    ) -> tuple[StagedProviderEvent, ...]:
        bound = exists().where(_same_key(meeting_provider_bindings, meeting_sync_events))
        tombstoned = exists().where(_same_key(meeting_provider_key_tombstones, meeting_sync_events))
        original = meeting_sync_events.c.occurrence_original_start_utc
        rows = self._connection.execute(
            select(*_EVENT_COLUMNS, tombstoned.label("suppressed"))
            .where(
                _mine(meeting_sync_events, principal_id),
                meeting_sync_events.c.snapshot_id == snapshot_id,
                ~bound,
            )
            .order_by(
                meeting_sync_events.c.calendar_ref,
                meeting_sync_events.c.ical_uid,
                original.asc().nulls_first(),
                meeting_sync_events.c.record_ordinal,
            )
        )
        return tuple(
            StagedProviderEvent(event=_to_event(row), suppressed=bool(row.suppressed))
            for row in rows
        )

    # --- the reconciliation pass (WP3b-S4) -----------------------------------

    def savepoint(self) -> AbstractContextManager[None]:
        return self._savepoint()

    @contextmanager
    def _savepoint(self) -> Iterator[None]:
        with self._connection.begin_nested():
            yield

    def list_unreviewed_meetings(
        self,
        principal_id: str,
        *,
        since: datetime,
        after_meeting_id: str | None,
        limit: int,
    ) -> tuple[UnreviewedMeetingRecord, ...]:
        criteria = [_in_review_scope(principal_id, since), _unreviewed()]
        if after_meeting_id is not None:
            anchor = self._connection.execute(
                select(meetings.c.start_at).where(
                    _mine(meetings, principal_id), meetings.c.meeting_id == after_meeting_id
                )
            ).one_or_none()
            if anchor is None:
                raise MeetingCursorError()
            criteria.append(
                tuple_(meetings.c.start_at, meetings.c.meeting_id)
                > tuple_(literal(anchor.start_at), literal(after_meeting_id))
            )
        rows = self._connection.execute(
            select(
                meetings.c.meeting_id,
                meetings.c.version,
                meetings.c.title,
                meetings.c.start_at,
                meetings.c.end_at,
                meetings.c.timezone_name,
                meetings.c.meeting_series_id,
                meetings.c.status,
            )
            .where(*criteria)
            .order_by(meetings.c.start_at, meetings.c.meeting_id)
            .limit(limit)
        )
        return tuple(
            UnreviewedMeetingRecord(
                meeting_id=row.meeting_id,
                version=row.version,
                title=row.title,
                start_at=row.start_at,
                end_at=row.end_at,
                timezone_name=row.timezone_name,
                meeting_series_id=row.meeting_series_id,
                status=MeetingStatus(row.status),
            )
            for row in rows
        )

    def count_review_scope(self, principal_id: str, *, since: datetime) -> MeetingReviewScopeCounts:
        row = self._connection.execute(
            select(
                func.count().label("in_scope"),
                func.count().filter(_unreviewed()).label("unreviewed"),
            ).where(_in_review_scope(principal_id, since))
        ).one()
        return MeetingReviewScopeCounts(in_scope=int(row.in_scope), unreviewed=int(row.unreviewed))

    # --- review marks --------------------------------------------------------

    def insert_review_mark(self, principal_id: str, mark: MeetingProviderReviewMarkRecord) -> bool:
        inserted = self._connection.execute(
            pg_insert(meeting_provider_review_marks)
            .values(
                _bound(
                    meeting_provider_review_marks,
                    principal_id,
                    {"meeting_id": mark.meeting_id, "marked_at": mark.marked_at},
                )
            )
            .on_conflict_do_nothing(constraint="meeting_provider_review_marks_pkey")
            .returning(meeting_provider_review_marks.c.meeting_id)
        ).first()
        return inserted is not None

    def get_review_mark(
        self, principal_id: str, meeting_id: str
    ) -> MeetingProviderReviewMarkRecord | None:
        row = self._connection.execute(
            select(*_MARK_COLUMNS).where(
                _mine(meeting_provider_review_marks, principal_id),
                meeting_provider_review_marks.c.meeting_id == meeting_id,
            )
        ).one_or_none()
        return None if row is None else _to_mark(row)

    def list_review_marks(self, principal_id: str) -> tuple[MeetingProviderReviewMarkRecord, ...]:
        rows = self._connection.execute(
            select(*_MARK_COLUMNS)
            .where(_mine(meeting_provider_review_marks, principal_id))
            .order_by(meeting_provider_review_marks.c.meeting_id)
        )
        return tuple(_to_mark(row) for row in rows)

    # --- the reconciliation latch --------------------------------------------

    def insert_reconciliation_pass(
        self, principal_id: str, completed: MeetingProviderReconciliationPassRecord
    ) -> None:
        self._connection.execute(
            insert(meeting_provider_reconciliation_passes).values(
                _bound(
                    meeting_provider_reconciliation_passes,
                    principal_id,
                    {
                        "completed_at": completed.completed_at,
                        "reviewed_meetings": completed.reviewed_meetings,
                        "reconcile_correlation_id": completed.reconcile_correlation_id,
                    },
                )
            )
        )

    def get_reconciliation_pass(
        self, principal_id: str
    ) -> MeetingProviderReconciliationPassRecord | None:
        row = self._connection.execute(
            select(*_PASS_COLUMNS).where(
                _mine(meeting_provider_reconciliation_passes, principal_id)
            )
        ).one_or_none()
        return None if row is None else _to_pass(row)

    # --- key tombstones ------------------------------------------------------

    def insert_key_tombstone(
        self, principal_id: str, tombstone: MeetingProviderKeyTombstoneRecord
    ) -> None:
        self._connection.execute(
            insert(meeting_provider_key_tombstones).values(
                _bound(
                    meeting_provider_key_tombstones,
                    principal_id,
                    {
                        "binding_id": tombstone.binding_id,
                        "meeting_id": tombstone.meeting_id,
                        "calendar_ref": tombstone.calendar_ref,
                        "ical_uid": tombstone.ical_uid,
                        "occurrence_original_start_utc": tombstone.occurrence_original_start_utc,
                        "series_ical_uid": tombstone.series_ical_uid,
                        "unbound_at": tombstone.unbound_at,
                        "meeting_history_id": tombstone.meeting_history_id,
                    },
                )
            )
        )

    def list_key_tombstones(
        self,
        principal_id: str,
        calendar_ref: str,
        ical_uid: str,
        occurrence_original_start_utc: datetime | None,
    ) -> tuple[MeetingProviderKeyTombstoneRecord, ...]:
        original = meeting_provider_key_tombstones.c.occurrence_original_start_utc
        rows = self._connection.execute(
            select(*_TOMBSTONE_COLUMNS)
            .where(
                _mine(meeting_provider_key_tombstones, principal_id),
                meeting_provider_key_tombstones.c.calendar_ref == calendar_ref,
                meeting_provider_key_tombstones.c.ical_uid == ical_uid,
                original.is_(None)
                if occurrence_original_start_utc is None
                else original == occurrence_original_start_utc,
            )
            .order_by(
                meeting_provider_key_tombstones.c.unbound_at,
                meeting_provider_key_tombstones.c.binding_id,
            )
        )
        return tuple(_to_tombstone(row) for row in rows)
