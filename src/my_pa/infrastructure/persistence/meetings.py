"""The Meeting records tables, behind `contracts.ports.MeetingRepository` (WP-MTG-02).

Eight tables are reached here and nowhere else: `meeting_series`, `meetings`,
`meeting_attendees`, `meeting_attachments`, `meeting_history`,
`meeting_note_versions`, `meeting_series_history` and `meeting_write_requests`.
Three tables of other planes are read and never written: `entities` (the
attendee Person references, share-locked), `projects` (ownership only) and the
managed-document tables (ownership, state and the safe title/media projection of
an attachment).

**The partition is reached through the guard, never written by hand.** The
`persistence/constraints.py` idiom, exactly: every SELECT is built through
`principal_scoped` or `_mine` (a one-line wrapper over `partition_criterion`),
every UPDATE composes `_mine`, every INSERT composes `_bound` (a one-line wrapper
over `principal_bound_values`), and every correlated predicate between two
tables composes `matching_partition_criterion` with `_mine` on the outer table.
There is no hand-written partition comparison, and the Principal is only ever a
parameter: nothing here reads it back from a row or a record.

**Lock order is the package section 35.10 order, and it is structural.** The
only row locks this module takes are the Meeting or MeetingSeries parent `FOR
UPDATE` and the attendee Person Entities `FOR SHARE`, the latter sorted by
`entity_id` in SQL so two writers naming the same Entities lock them in the same
order. Children are read under the parent lock without locks of their own, and
Project and ManagedDocument references are nonlocking reads: their composite
same-Principal foreign keys supply the structural custody.

**Arbitration is the write-request primary key.** A reservation is an `INSERT
... ON CONFLICT DO NOTHING` on `(principal_id, capability, idempotency_key)`.
PostgreSQL makes a concurrent second insert wait for the first transaction and
then report the conflict, so the loser reads the committed winner and classifies
it; it never sees a raw `IntegrityError`.

**Search is the package section 34.15 statement.** One `websearch_to_tsquery`
under the `simple` configuration, matched against the Meeting core text, the
series title through its own correlated `EXISTS`, or the current note head
through a correlated `EXISTS` with a `NOT EXISTS` successor test. The text-search
configuration and the empty and separator strings are rendered as SQL literals,
never bound, so each expression is the same tree as its functional GIN index.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Any, Final, cast

from sqlalchemy import (
    ColumnElement,
    DateTime,
    Select,
    Table,
    Text,
    and_,
    func,
    insert,
    literal,
    literal_column,
    or_,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Row, RowMapping

from my_pa.contracts.ports import (
    MeetingAttachmentRecord,
    MeetingAttendeeRecord,
    MeetingCursorAnchor,
    MeetingEntityState,
    MeetingListPage,
    MeetingNoteRecord,
    MeetingRecord,
    MeetingRepository,
    MeetingWriteRequestRecord,
    RepositoryFailureError,
)
from my_pa.contracts.v1.meetings import (
    MeetingAttachmentView,
    MeetingAttendeeView,
    MeetingHistoryView,
    MeetingListEntry,
    MeetingNoteView,
    MeetingSeriesHistoryView,
    MeetingSeriesView,
    MeetingView,
)
from my_pa.domain.documents.managed import DocumentState, LifecycleTransition
from my_pa.domain.meeting.model import (
    AttendeeResponseStatus,
    MeetingActor,
    MeetingAttachmentAvailability,
    MeetingCursorError,
    MeetingHistoryAction,
    MeetingIdempotencyConflictError,
    MeetingListRequest,
    MeetingOutcome,
    MeetingSearchRequest,
    MeetingSortDirection,
    MeetingStatus,
    MeetingTimeScope,
)
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    matching_partition_criterion,
    partition_criterion,
    principal_bound_values,
    principal_scoped,
)
from my_pa.infrastructure.persistence.tables import (
    entities,
    managed_document_lifecycle_events,
    managed_document_versions,
    managed_documents,
    meeting_attachments,
    meeting_attendees,
    meeting_history,
    meeting_note_versions,
    meeting_series,
    meeting_series_history,
    meeting_write_requests,
    meetings,
    projects,
)

__all__ = ["SqlMeetingRepository"]


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


#: The named primary key of `meeting_write_requests`, the one conflict target a
#: reservation absorbs. Named rather than spelled as columns, so a conflict on
#: any other constraint still raises.
_WRITE_REQUEST_KEY: Final = "meeting_write_requests_pkey"

#: The text-search configuration, rendered as a literal: a bound configuration
#: compiles to a parameter, and a parameter is a different expression tree from
#: the `'simple'` constant every Meeting GIN index was built over.
_SIMPLE: Final = literal_column("'simple'", REGCONFIG)
#: The two string constants the core-text expression concatenates, rendered as
#: literals for the same reason.
_EMPTY: Final = literal_column("''", Text)
_SPACE: Final = literal_column("' '", Text)

#: The note version that supersedes another, as a second reference to the one
#: note table. A `Table`-typed alias so the partition helpers accept it; at run
#: time every helper reads only its column collection, which the alias has.
_SUCCESSOR: Final = cast(Table, meeting_note_versions.alias("successor"))

_MEETING_COLUMNS: Final = (
    meetings.c.meeting_id,
    meetings.c.meeting_series_id,
    meetings.c.title,
    meetings.c.start_at,
    meetings.c.end_at,
    meetings.c.timezone_name,
    meetings.c.status,
    meetings.c.cancelled_at,
    meetings.c.location_text,
    meetings.c.virtual_meeting_url,
    meetings.c.description,
    meetings.c.project_id,
    meetings.c.version,
    meetings.c.created_at,
    meetings.c.updated_at,
)

_SERIES_COLUMNS: Final = (
    meeting_series.c.meeting_series_id,
    meeting_series.c.title,
    meeting_series.c.version,
    meeting_series.c.created_at,
    meeting_series.c.updated_at,
)


# ------------------------------------------------------------------ expressions


def _core_document() -> ColumnElement[Any]:
    """The Meeting core text, the same expression as `meetings_core_text`."""
    return func.to_tsvector(
        _SIMPLE,
        func.coalesce(meetings.c.title, _EMPTY)
        .concat(_SPACE)
        .concat(func.coalesce(meetings.c.description, _EMPTY))
        .concat(_SPACE)
        .concat(func.coalesce(meetings.c.location_text, _EMPTY)),
    )


def _series_document() -> ColumnElement[Any]:
    """The series title text, the same expression as `meeting_series_title_text`."""
    return func.to_tsvector(_SIMPLE, func.coalesce(meeting_series.c.title, _EMPTY))


def _note_document() -> ColumnElement[Any]:
    """The note body text, the same expression as `meeting_note_versions_text`."""
    return func.to_tsvector(_SIMPLE, meeting_note_versions.c.content_markdown)


def _series_title() -> ColumnElement[Any]:
    """The occurrence's series title, correlated to the outer Meeting row."""
    return (
        select(meeting_series.c.title)
        .where(
            matching_partition_criterion(meeting_series, meetings),
            meeting_series.c.meeting_series_id == meetings.c.meeting_series_id,
        )
        .scalar_subquery()
    )


def _series_version() -> ColumnElement[Any]:
    """The occurrence's series version, correlated to the outer Meeting row (D-21)."""
    return (
        select(meeting_series.c.version)
        .where(
            matching_partition_criterion(meeting_series, meetings),
            meeting_series.c.meeting_series_id == meetings.c.meeting_series_id,
        )
        .scalar_subquery()
    )


def _active_count(table: Table) -> ColumnElement[Any]:
    """How many active relations of `table` the outer Meeting row has."""
    return (
        select(func.count())
        .select_from(table)
        .where(
            matching_partition_criterion(table, meetings),
            table.c.meeting_id == meetings.c.meeting_id,
            table.c.removed_at.is_(None),
        )
        .scalar_subquery()
    )


def _document_head(column: ColumnElement[Any]) -> ColumnElement[Any]:
    """`column` of the attached document's newest version, read at read time.

    No snapshot: the ManagedDocument keeps custody of its metadata, and an
    attachment projects whatever the current head says.
    """
    return (
        select(column)
        .where(
            matching_partition_criterion(managed_document_versions, meeting_attachments),
            managed_document_versions.c.document_id == meeting_attachments.c.document_id,
        )
        .order_by(managed_document_versions.c.version_number.desc())
        .limit(1)
        .scalar_subquery()
    )


def _with_active_attendee(predicate: ColumnElement[bool]) -> ColumnElement[bool]:
    """The outer Meeting has an active attendee satisfying `predicate`.

    An `EXISTS`, never a join: a join would repeat a Meeting once per matching
    attendee, and the partial active-attendee indexes serve the probe.
    """
    return (
        select(meeting_attendees.c.attendee_id)
        .where(
            matching_partition_criterion(meeting_attendees, meetings),
            meeting_attendees.c.meeting_id == meetings.c.meeting_id,
            meeting_attendees.c.removed_at.is_(None),
            predicate,
        )
        .exists()
    )


def _has_no_successor() -> ColumnElement[bool]:
    """The note version in scope is its Meeting's current head."""
    return ~(
        select(_SUCCESSOR.c.note_version_id)
        .where(
            matching_partition_criterion(_SUCCESSOR, meeting_note_versions),
            _SUCCESSOR.c.meeting_id == meeting_note_versions.c.meeting_id,
            _SUCCESSOR.c.supersedes_note_version_id == meeting_note_versions.c.note_version_id,
        )
        .exists()
    )


def _matches(query: str) -> ColumnElement[bool]:
    """Package section 34.15: core text, series-title branch, current-note branch."""
    tsquery = func.websearch_to_tsquery(_SIMPLE, literal(query, Text))
    series_branch = (
        select(meeting_series.c.meeting_series_id)
        .where(
            matching_partition_criterion(meeting_series, meetings),
            meeting_series.c.meeting_series_id == meetings.c.meeting_series_id,
            _series_document().bool_op("@@")(tsquery),
        )
        .exists()
    )
    note_branch = (
        select(meeting_note_versions.c.note_version_id)
        .where(
            matching_partition_criterion(meeting_note_versions, meetings),
            meeting_note_versions.c.meeting_id == meetings.c.meeting_id,
            _has_no_successor(),
            _note_document().bool_op("@@")(tsquery),
        )
        .exists()
    )
    return or_(_core_document().bool_op("@@")(tsquery), series_branch, note_branch)


def _filters(request: MeetingListRequest, now: datetime) -> list[ColumnElement[bool]]:
    """The request's structured filters, ANDed. The partition is added by the caller."""
    criteria: list[ColumnElement[bool]] = []
    if request.meeting_series_id is not None:
        criteria.append(meetings.c.meeting_series_id == request.meeting_series_id)
    if request.project_id is not None:
        criteria.append(meetings.c.project_id == request.project_id)
    if request.start_at_from is not None:
        criteria.append(meetings.c.start_at >= request.start_at_from)
    if request.start_at_before is not None:
        criteria.append(meetings.c.start_at < request.start_at_before)
    if request.status is not None:
        criteria.append(meetings.c.status == MeetingStatus(request.status).value)
    scope = MeetingTimeScope(request.time_scope)
    if scope is MeetingTimeScope.UPCOMING:
        criteria.append(func.coalesce(meetings.c.end_at, meetings.c.start_at) >= now)
    elif scope is MeetingTimeScope.PAST:
        criteria.append(func.coalesce(meetings.c.end_at, meetings.c.start_at) < now)
    if request.attendee_entity_id is not None:
        criteria.append(
            _with_active_attendee(meeting_attendees.c.entity_id == request.attendee_entity_id)
        )
    if request.attendee_email is not None:
        criteria.append(
            _with_active_attendee(meeting_attendees.c.email_normalized == request.attendee_email)
        )
    return criteria


# --------------------------------------------------------------------- hydration


def _to_series(row: Row[Any]) -> MeetingSeriesView:
    mapping = row._mapping
    return MeetingSeriesView(
        meeting_series_id=mapping["meeting_series_id"],
        title=mapping["title"],
        version=mapping["version"],
        created_at=mapping["created_at"],
        updated_at=mapping["updated_at"],
    )


def _to_meeting_receipt(mapping: RowMapping) -> MeetingHistoryView:
    return MeetingHistoryView(
        history_id=mapping["receipt_history_id"],
        meeting_id=mapping["receipt_meeting_id"],
        action=MeetingHistoryAction(mapping["receipt_action"]),
        actor=MeetingActor(mapping["receipt_actor"]),
        outcome=MeetingOutcome(mapping["receipt_outcome"]),
        before_version=mapping["receipt_before_version"],
        after_version=mapping["receipt_after_version"],
        occurred_at=mapping["receipt_occurred_at"],
        recorded_at=mapping["receipt_recorded_at"],
    )


def _to_series_receipt(mapping: RowMapping) -> MeetingSeriesHistoryView:
    return MeetingSeriesHistoryView(
        series_history_id=mapping["series_receipt_id"],
        meeting_series_id=mapping["series_receipt_series_id"],
        action=MeetingHistoryAction(mapping["series_receipt_action"]),
        actor=MeetingActor(mapping["series_receipt_actor"]),
        outcome=MeetingOutcome(mapping["series_receipt_outcome"]),
        before_version=mapping["series_receipt_before_version"],
        after_version=mapping["series_receipt_after_version"],
        occurred_at=mapping["series_receipt_occurred_at"],
        recorded_at=mapping["series_receipt_recorded_at"],
    )


def _to_list_entry(row: Row[Any]) -> MeetingListEntry:
    mapping = row._mapping
    return MeetingListEntry(
        meeting_id=mapping["meeting_id"],
        meeting_series_id=mapping["meeting_series_id"],
        series_title=mapping["series_title"],
        series_version=mapping["series_version"],
        title=mapping["title"],
        status=MeetingStatus(mapping["status"]),
        start_at=mapping["start_at"],
        end_at=mapping["end_at"],
        timezone_name=mapping["timezone_name"],
        location_text=mapping["location_text"],
        project_id=mapping["project_id"],
        version=mapping["version"],
        attendee_count=mapping["attendee_count"],
        attachment_count=mapping["attachment_count"],
        updated_at=mapping["updated_at"],
    )


def _availability(title: str | None, transition: str | None) -> MeetingAttachmentAvailability:
    if title is None:
        return MeetingAttachmentAvailability.UNAVAILABLE
    if transition is None:
        return MeetingAttachmentAvailability.ACTIVE
    state = LifecycleTransition(transition).resulting_state()
    if state is DocumentState.ARCHIVED:
        return MeetingAttachmentAvailability.ARCHIVED
    return MeetingAttachmentAvailability.ACTIVE


class SqlMeetingRepository(MeetingRepository):
    """`MeetingRepository`, over the general unit of work's `Connection`.

    Takes the connection rather than opening one: the caller owns the
    transaction, and this class only issues statements on it. Nothing here
    commits.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    # --- write-request arbitration ---------------------------------------

    def reserve_write_request(
        self,
        principal_id: str,
        capability: str,
        idempotency_key: str,
        request_digest: str,
        *,
        created_at: datetime,
    ) -> MeetingWriteRequestRecord | None:
        inserted = self._connection.execute(
            pg_insert(meeting_write_requests)
            .values(
                _bound(
                    meeting_write_requests,
                    principal_id,
                    {
                        "capability": capability,
                        "idempotency_key": idempotency_key,
                        "request_digest": request_digest,
                        "created_at": created_at,
                    },
                )
            )
            .on_conflict_do_nothing(constraint=_WRITE_REQUEST_KEY)
            .returning(meeting_write_requests.c.capability)
        ).first()
        if inserted is not None:
            return None

        # The key was taken. `ON CONFLICT` waited for the transaction that holds
        # it, so the row read here is that transaction's committed outcome.
        winner = self.read_write_request(principal_id, capability, idempotency_key)
        if winner is None:
            # A conflict on the primary key with no row behind it: the store is
            # inconsistent, not something a caller can repair.
            raise RepositoryFailureError
        if winner.request_digest != request_digest:
            raise MeetingIdempotencyConflictError()
        if winner.completed_at is None:
            # The same request, still incomplete after its owner ended. Never
            # stolen: an unproven reservation is an internal failure (35.7).
            raise RepositoryFailureError
        return winner

    def read_write_request(
        self, principal_id: str, capability: str, idempotency_key: str
    ) -> MeetingWriteRequestRecord | None:
        request = meeting_write_requests
        row = self._connection.execute(
            select(
                request.c.capability,
                request.c.request_digest,
                request.c.created_at,
                request.c.completed_at,
                request.c.meeting_id,
                request.c.meeting_series_id,
                request.c.meeting_history_id,
                request.c.meeting_series_history_id,
                request.c.result_version,
                meeting_history.c.history_id.label("receipt_history_id"),
                meeting_history.c.meeting_id.label("receipt_meeting_id"),
                meeting_history.c.action.label("receipt_action"),
                meeting_history.c.actor.label("receipt_actor"),
                meeting_history.c.outcome.label("receipt_outcome"),
                meeting_history.c.before_version.label("receipt_before_version"),
                meeting_history.c.after_version.label("receipt_after_version"),
                meeting_history.c.occurred_at.label("receipt_occurred_at"),
                meeting_history.c.recorded_at.label("receipt_recorded_at"),
                meeting_series_history.c.series_history_id.label("series_receipt_id"),
                meeting_series_history.c.meeting_series_id.label("series_receipt_series_id"),
                meeting_series_history.c.action.label("series_receipt_action"),
                meeting_series_history.c.actor.label("series_receipt_actor"),
                meeting_series_history.c.outcome.label("series_receipt_outcome"),
                meeting_series_history.c.before_version.label("series_receipt_before_version"),
                meeting_series_history.c.after_version.label("series_receipt_after_version"),
                meeting_series_history.c.occurred_at.label("series_receipt_occurred_at"),
                meeting_series_history.c.recorded_at.label("series_receipt_recorded_at"),
            )
            .select_from(
                request.outerjoin(
                    meeting_history,
                    and_(
                        matching_partition_criterion(meeting_history, request),
                        meeting_history.c.history_id == request.c.meeting_history_id,
                    ),
                ).outerjoin(
                    meeting_series_history,
                    and_(
                        matching_partition_criterion(meeting_series_history, request),
                        meeting_series_history.c.series_history_id
                        == request.c.meeting_series_history_id,
                    ),
                )
            )
            .where(
                _mine(request, principal_id),
                request.c.capability == capability,
                request.c.idempotency_key == idempotency_key,
            )
        ).one_or_none()
        if row is None:
            return None
        mapping = row._mapping
        return MeetingWriteRequestRecord(
            capability=mapping["capability"],
            request_digest=mapping["request_digest"],
            created_at=mapping["created_at"],
            completed_at=mapping["completed_at"],
            meeting_id=mapping["meeting_id"],
            meeting_series_id=mapping["meeting_series_id"],
            meeting_history_id=mapping["meeting_history_id"],
            meeting_series_history_id=mapping["meeting_series_history_id"],
            result_version=mapping["result_version"],
            meeting_receipt=(
                None if mapping["receipt_history_id"] is None else _to_meeting_receipt(mapping)
            ),
            series_receipt=(
                None if mapping["series_receipt_id"] is None else _to_series_receipt(mapping)
            ),
        )

    def complete_write_request(
        self,
        principal_id: str,
        capability: str,
        idempotency_key: str,
        *,
        request_digest: str,
        meeting_id: str | None,
        meeting_series_id: str | None,
        meeting_history_id: str | None,
        meeting_series_history_id: str | None,
        result_version: int,
        completed_at: datetime,
    ) -> None:
        completed = self._connection.execute(
            update(meeting_write_requests)
            .where(
                _mine(meeting_write_requests, principal_id),
                meeting_write_requests.c.capability == capability,
                meeting_write_requests.c.idempotency_key == idempotency_key,
                meeting_write_requests.c.request_digest == request_digest,
                meeting_write_requests.c.completed_at.is_(None),
            )
            .values(
                meeting_id=meeting_id,
                meeting_series_id=meeting_series_id,
                meeting_history_id=meeting_history_id,
                meeting_series_history_id=meeting_series_history_id,
                result_version=result_version,
                completed_at=completed_at,
            )
            .returning(meeting_write_requests.c.capability)
        ).first()
        if completed is None:
            raise RepositoryFailureError

    # --- parent locks and reference reads ---------------------------------

    def lock_meeting_for_update(self, principal_id: str, meeting_id: str) -> MeetingView | None:
        locked = self._connection.execute(
            principal_scoped(
                select(meetings.c.meeting_id),
                meetings,
                capture_context(principal_id),
            )
            .where(meetings.c.meeting_id == meeting_id)
            .with_for_update()
        ).one_or_none()
        if locked is None:
            return None
        return self.read_meeting(principal_id, meeting_id)

    def lock_series_for_update(
        self, principal_id: str, meeting_series_id: str
    ) -> MeetingSeriesView | None:
        row = self._connection.execute(
            self._series_statement(principal_id, meeting_series_id).with_for_update()
        ).one_or_none()
        return None if row is None else _to_series(row)

    def read_owned_series(
        self, principal_id: str, meeting_series_id: str
    ) -> MeetingSeriesView | None:
        row = self._connection.execute(
            self._series_statement(principal_id, meeting_series_id)
        ).one_or_none()
        return None if row is None else _to_series(row)

    def share_lock_person_entities(
        self, principal_id: str, entity_ids: Collection[str]
    ) -> tuple[MeetingEntityState, ...]:
        wanted = sorted(set(entity_ids))
        if not wanted:
            return ()
        rows = self._connection.execute(
            principal_scoped(
                select(entities.c.entity_id, entities.c.entity_type, entities.c.status),
                entities,
                capture_context(principal_id),
            )
            .where(entities.c.entity_id.in_(wanted))
            # The sort sits below the row locks in the plan, so the locks are
            # taken in ascending `entity_id` order: a deterministic multi-Entity
            # lock order for every Meeting writer.
            .order_by(entities.c.entity_id.asc())
            .with_for_update(read=True)
        ).all()
        return tuple(
            MeetingEntityState(
                entity_id=row._mapping["entity_id"],
                entity_type=row._mapping["entity_type"],
                status=row._mapping["status"],
            )
            for row in rows
        )

    def project_is_owned(self, principal_id: str, project_id: str) -> bool:
        row = self._connection.execute(
            principal_scoped(
                select(projects.c.project_id),
                projects,
                capture_context(principal_id),
            ).where(projects.c.project_id == project_id)
        ).first()
        return row is not None

    def owned_managed_documents(
        self, principal_id: str, document_ids: Collection[str]
    ) -> Mapping[str, DocumentState]:
        wanted = sorted(set(document_ids))
        if not wanted:
            return {}
        latest = (
            select(managed_document_lifecycle_events.c.transition)
            .where(
                matching_partition_criterion(managed_document_lifecycle_events, managed_documents),
                managed_document_lifecycle_events.c.document_id == managed_documents.c.document_id,
            )
            .order_by(managed_document_lifecycle_events.c.sequence_number.desc())
            .limit(1)
            .scalar_subquery()
        )
        rows = self._connection.execute(
            principal_scoped(
                select(managed_documents.c.document_id, latest.label("transition")),
                managed_documents,
                capture_context(principal_id),
            ).where(managed_documents.c.document_id.in_(wanted))
        ).all()
        found: dict[str, DocumentState] = {}
        for row in rows:
            transition = row._mapping["transition"]
            found[row._mapping["document_id"]] = (
                DocumentState.ACTIVE
                if transition is None
                else LifecycleTransition(transition).resulting_state()
            )
        return found

    # --- writes ------------------------------------------------------------

    def insert_series(self, principal_id: str, series: MeetingSeriesView) -> None:
        self._connection.execute(
            insert(meeting_series).values(
                _bound(
                    meeting_series,
                    principal_id,
                    {
                        "meeting_series_id": series.meeting_series_id,
                        "title": series.title,
                        "version": series.version,
                        "created_at": series.created_at,
                        "updated_at": series.updated_at,
                    },
                )
            )
        )

    def update_series_title(
        self,
        principal_id: str,
        meeting_series_id: str,
        *,
        title: str,
        version: int,
        updated_at: datetime,
    ) -> None:
        changed = self._connection.execute(
            update(meeting_series)
            .where(
                _mine(meeting_series, principal_id),
                meeting_series.c.meeting_series_id == meeting_series_id,
            )
            .values(title=title, version=version, updated_at=updated_at)
            .returning(meeting_series.c.meeting_series_id)
        ).first()
        if changed is None:
            raise RepositoryFailureError

    def insert_series_history(
        self,
        principal_id: str,
        receipt: MeetingSeriesHistoryView,
        *,
        idempotency_key: str,
        request_digest: str,
    ) -> None:
        self._connection.execute(
            insert(meeting_series_history).values(
                _bound(
                    meeting_series_history,
                    principal_id,
                    {
                        "series_history_id": receipt.series_history_id,
                        "meeting_series_id": receipt.meeting_series_id,
                        "action": MeetingHistoryAction(receipt.action).value,
                        "actor": MeetingActor(receipt.actor).value,
                        "outcome": MeetingOutcome(receipt.outcome).value,
                        "before_version": receipt.before_version,
                        "after_version": receipt.after_version,
                        "idempotency_key": idempotency_key,
                        "request_digest": request_digest,
                        "occurred_at": receipt.occurred_at,
                        "recorded_at": receipt.recorded_at,
                    },
                )
            )
        )

    def insert_meeting(self, principal_id: str, meeting: MeetingRecord) -> None:
        self._connection.execute(
            insert(meetings).values(
                _bound(
                    meetings,
                    principal_id,
                    {
                        "meeting_id": meeting.meeting_id,
                        "created_at": meeting.created_at,
                        **_mutable_meeting_values(meeting),
                    },
                )
            )
        )

    def update_meeting(self, principal_id: str, meeting: MeetingRecord) -> None:
        changed = self._connection.execute(
            update(meetings)
            .where(
                _mine(meetings, principal_id),
                meetings.c.meeting_id == meeting.meeting_id,
            )
            .values(**_mutable_meeting_values(meeting))
            .returning(meetings.c.meeting_id)
        ).first()
        if changed is None:
            raise RepositoryFailureError

    def retire_attendees(
        self,
        principal_id: str,
        meeting_id: str,
        attendee_ids: Collection[str],
        *,
        removed_at: datetime,
    ) -> int:
        return self._retire(
            meeting_attendees,
            meeting_attendees.c.attendee_id,
            principal_id,
            meeting_id,
            attendee_ids,
            removed_at,
        )

    def insert_attendees(
        self,
        principal_id: str,
        meeting_id: str,
        attendees: Sequence[MeetingAttendeeRecord],
        *,
        added_at: datetime,
    ) -> None:
        if not attendees:
            return
        self._connection.execute(
            insert(meeting_attendees),
            [
                _bound(
                    meeting_attendees,
                    principal_id,
                    {
                        "attendee_id": record.attendee_id,
                        "meeting_id": meeting_id,
                        "entity_id": record.attendee.entity_id,
                        "display_name": record.attendee.display_name,
                        "email_normalized": record.attendee.email_normalized,
                        "is_organizer": record.attendee.is_organizer,
                        "response_status": AttendeeResponseStatus(
                            record.attendee.response_status
                        ).value,
                        "added_at": added_at,
                        "removed_at": None,
                    },
                )
                for record in attendees
            ],
        )

    def retire_attachments(
        self,
        principal_id: str,
        meeting_id: str,
        attachment_ids: Collection[str],
        *,
        removed_at: datetime,
    ) -> int:
        return self._retire(
            meeting_attachments,
            meeting_attachments.c.attachment_id,
            principal_id,
            meeting_id,
            attachment_ids,
            removed_at,
        )

    def insert_attachments(
        self,
        principal_id: str,
        meeting_id: str,
        attachments: Sequence[MeetingAttachmentRecord],
        *,
        added_at: datetime,
    ) -> None:
        if not attachments:
            return
        self._connection.execute(
            insert(meeting_attachments),
            [
                _bound(
                    meeting_attachments,
                    principal_id,
                    {
                        "attachment_id": record.attachment_id,
                        "meeting_id": meeting_id,
                        "document_id": record.document_id,
                        "added_at": added_at,
                        "removed_at": None,
                    },
                )
                for record in attachments
            ],
        )

    def insert_meeting_history(
        self,
        principal_id: str,
        receipt: MeetingHistoryView,
        *,
        meeting_series_id: str | None,
        idempotency_key: str,
        request_digest: str,
    ) -> None:
        self._connection.execute(
            insert(meeting_history).values(
                _bound(
                    meeting_history,
                    principal_id,
                    {
                        "history_id": receipt.history_id,
                        "meeting_id": receipt.meeting_id,
                        "meeting_series_id": meeting_series_id,
                        "action": MeetingHistoryAction(receipt.action).value,
                        "actor": MeetingActor(receipt.actor).value,
                        "outcome": MeetingOutcome(receipt.outcome).value,
                        "before_version": receipt.before_version,
                        "after_version": receipt.after_version,
                        "idempotency_key": idempotency_key,
                        "request_digest": request_digest,
                        "occurred_at": receipt.occurred_at,
                        "recorded_at": receipt.recorded_at,
                    },
                )
            )
        )

    def insert_note_version(self, principal_id: str, note: MeetingNoteRecord) -> None:
        self._connection.execute(
            insert(meeting_note_versions).values(
                _bound(
                    meeting_note_versions,
                    principal_id,
                    {
                        "note_version_id": note.note_version_id,
                        "meeting_id": note.meeting_id,
                        "version_number": note.version_number,
                        "supersedes_note_version_id": note.supersedes_note_version_id,
                        "content_markdown": note.content_markdown,
                        "content_sha256": note.content_sha256,
                        "meeting_history_id": note.meeting_history_id,
                        "recorded_at": note.recorded_at,
                    },
                )
            )
        )

    # --- reads -------------------------------------------------------------

    def current_note(self, principal_id: str, meeting_id: str) -> MeetingNoteView | None:
        row = self._connection.execute(
            principal_scoped(
                select(
                    meeting_note_versions.c.note_version_id,
                    meeting_note_versions.c.version_number,
                    meeting_note_versions.c.content_markdown,
                    meeting_note_versions.c.recorded_at,
                ),
                meeting_note_versions,
                capture_context(principal_id),
            ).where(
                meeting_note_versions.c.meeting_id == meeting_id,
                _has_no_successor(),
            )
        ).one_or_none()
        if row is None:
            return None
        mapping = row._mapping
        return MeetingNoteView(
            note_version_id=mapping["note_version_id"],
            version_number=mapping["version_number"],
            body_markdown=mapping["content_markdown"],
            recorded_at=mapping["recorded_at"],
        )

    def read_meeting(self, principal_id: str, meeting_id: str) -> MeetingView | None:
        row = self._connection.execute(
            principal_scoped(
                select(
                    *_MEETING_COLUMNS,
                    _series_title().label("series_title"),
                    _series_version().label("series_version"),
                ),
                meetings,
                capture_context(principal_id),
            ).where(meetings.c.meeting_id == meeting_id)
        ).one_or_none()
        if row is None:
            return None
        mapping = row._mapping
        return MeetingView(
            meeting_id=mapping["meeting_id"],
            meeting_series_id=mapping["meeting_series_id"],
            series_title=mapping["series_title"],
            series_version=mapping["series_version"],
            title=mapping["title"],
            status=MeetingStatus(mapping["status"]),
            start_at=mapping["start_at"],
            end_at=mapping["end_at"],
            timezone_name=mapping["timezone_name"],
            location_text=mapping["location_text"],
            virtual_meeting_url=mapping["virtual_meeting_url"],
            description=mapping["description"],
            project_id=mapping["project_id"],
            version=mapping["version"],
            created_at=mapping["created_at"],
            updated_at=mapping["updated_at"],
            cancelled_at=mapping["cancelled_at"],
            attendees=self._active_attendees(principal_id, meeting_id),
            attachments=self._active_attachments(principal_id, meeting_id),
            notes=self.current_note(principal_id, meeting_id),
        )

    def list_meetings(
        self, principal_id: str, request: MeetingListRequest, *, now: datetime
    ) -> MeetingListPage:
        return self._page(principal_id, request, now=now, query=None)

    def search_meetings(
        self, principal_id: str, request: MeetingSearchRequest, *, now: datetime
    ) -> MeetingListPage:
        return self._page(principal_id, request.filters, now=now, query=request.query)

    def resolve_cursor_anchor(
        self,
        principal_id: str,
        request: MeetingListRequest,
        *,
        now: datetime,
        query: str | None = None,
    ) -> MeetingCursorAnchor:
        if request.after is None:
            raise MeetingCursorError()
        criteria = _filters(request, now)
        if query is not None:
            criteria.append(_matches(query))
        row = self._connection.execute(
            principal_scoped(
                select(meetings.c.start_at, meetings.c.meeting_id),
                meetings,
                capture_context(principal_id),
            ).where(meetings.c.meeting_id == request.after, *criteria)
        ).one_or_none()
        if row is None:
            raise MeetingCursorError()
        return MeetingCursorAnchor(
            start_at=row._mapping["start_at"], meeting_id=row._mapping["meeting_id"]
        )

    # --- internals ---------------------------------------------------------

    def _series_statement(self, principal_id: str, meeting_series_id: str) -> Select[Any]:
        return principal_scoped(
            select(*_SERIES_COLUMNS),
            meeting_series,
            capture_context(principal_id),
        ).where(meeting_series.c.meeting_series_id == meeting_series_id)

    def _retire(
        self,
        table: Table,
        identity: ColumnElement[Any],
        principal_id: str,
        meeting_id: str,
        identifiers: Collection[str],
        removed_at: datetime,
    ) -> int:
        wanted = sorted(set(identifiers))
        if not wanted:
            return 0
        retired = self._connection.execute(
            update(table)
            .where(
                _mine(table, principal_id),
                table.c.meeting_id == meeting_id,
                identity.in_(wanted),
                table.c.removed_at.is_(None),
            )
            .values(removed_at=removed_at)
            .returning(identity)
        ).all()
        return len(retired)

    def _active_attendees(
        self, principal_id: str, meeting_id: str
    ) -> tuple[MeetingAttendeeView, ...]:
        rows = self._connection.execute(
            principal_scoped(
                select(
                    meeting_attendees.c.attendee_id,
                    meeting_attendees.c.entity_id,
                    meeting_attendees.c.display_name,
                    meeting_attendees.c.email_normalized,
                    meeting_attendees.c.is_organizer,
                    meeting_attendees.c.response_status,
                    meeting_attendees.c.added_at,
                ),
                meeting_attendees,
                capture_context(principal_id),
            )
            .where(
                meeting_attendees.c.meeting_id == meeting_id,
                meeting_attendees.c.removed_at.is_(None),
            )
            .order_by(meeting_attendees.c.attendee_id.asc())
        ).all()
        return tuple(
            MeetingAttendeeView(
                attendee_id=row._mapping["attendee_id"],
                entity_id=row._mapping["entity_id"],
                display_name=row._mapping["display_name"],
                email=row._mapping["email_normalized"],
                is_organizer=row._mapping["is_organizer"],
                response_status=AttendeeResponseStatus(row._mapping["response_status"]),
                added_at=row._mapping["added_at"],
            )
            for row in rows
        )

    def _active_attachments(
        self, principal_id: str, meeting_id: str
    ) -> tuple[MeetingAttachmentView, ...]:
        latest = (
            select(managed_document_lifecycle_events.c.transition)
            .where(
                matching_partition_criterion(
                    managed_document_lifecycle_events, meeting_attachments
                ),
                managed_document_lifecycle_events.c.document_id
                == meeting_attachments.c.document_id,
            )
            .order_by(managed_document_lifecycle_events.c.sequence_number.desc())
            .limit(1)
            .scalar_subquery()
        )
        rows = self._connection.execute(
            principal_scoped(
                select(
                    meeting_attachments.c.attachment_id,
                    meeting_attachments.c.document_id,
                    meeting_attachments.c.added_at,
                    _document_head(managed_document_versions.c.title).label("title"),
                    _document_head(managed_document_versions.c.media_type).label("media_type"),
                    latest.label("transition"),
                ),
                meeting_attachments,
                capture_context(principal_id),
            )
            .where(
                meeting_attachments.c.meeting_id == meeting_id,
                meeting_attachments.c.removed_at.is_(None),
            )
            .order_by(meeting_attachments.c.attachment_id.asc())
        ).all()
        views: list[MeetingAttachmentView] = []
        for row in rows:
            mapping = row._mapping
            availability = _availability(mapping["title"], mapping["transition"])
            available = availability is not MeetingAttachmentAvailability.UNAVAILABLE
            views.append(
                MeetingAttachmentView(
                    attachment_id=mapping["attachment_id"],
                    document_id=mapping["document_id"],
                    availability=availability,
                    title=mapping["title"] if available else None,
                    media_type=mapping["media_type"] if available else None,
                    added_at=mapping["added_at"],
                )
            )
        return tuple(views)

    def _page(
        self,
        principal_id: str,
        request: MeetingListRequest,
        *,
        now: datetime,
        query: str | None,
    ) -> MeetingListPage:
        criteria = _filters(request, now)
        if query is not None:
            criteria.append(_matches(query))
        ascending = MeetingSortDirection(request.sort_direction) is MeetingSortDirection.ASC
        if request.after is not None:
            anchor = self.resolve_cursor_anchor(principal_id, request, now=now, query=query)
            position = tuple_(meetings.c.start_at, meetings.c.meeting_id)
            boundary = tuple_(
                literal(anchor.start_at, DateTime(timezone=True)),
                literal(anchor.meeting_id, Text),
            )
            criteria.append(position > boundary if ascending else position < boundary)
        order = (
            (meetings.c.start_at.asc(), meetings.c.meeting_id.asc())
            if ascending
            else (meetings.c.start_at.desc(), meetings.c.meeting_id.desc())
        )
        rows = self._connection.execute(
            principal_scoped(
                select(
                    meetings.c.meeting_id,
                    meetings.c.meeting_series_id,
                    _series_title().label("series_title"),
                    _series_version().label("series_version"),
                    meetings.c.title,
                    meetings.c.status,
                    meetings.c.start_at,
                    meetings.c.end_at,
                    meetings.c.timezone_name,
                    meetings.c.location_text,
                    meetings.c.project_id,
                    meetings.c.version,
                    meetings.c.updated_at,
                    _active_count(meeting_attendees).label("attendee_count"),
                    _active_count(meeting_attachments).label("attachment_count"),
                ),
                meetings,
                capture_context(principal_id),
            )
            .where(*criteria)
            .order_by(*order)
            .limit(request.page_size + 1)
        ).all()
        return MeetingListPage(
            entries=tuple(_to_list_entry(row) for row in rows[: request.page_size]),
            has_more=len(rows) > request.page_size,
        )


def _mutable_meeting_values(meeting: MeetingRecord) -> dict[str, object]:
    """The columns an update may rewrite: everything but identity and creation.

    `meeting_series_id` is among them (operator decision 2026-10-09, retiring
    AC-007): series membership is written in the same UPDATE, under the
    Meeting's existing `FOR UPDATE` lock and `expected_version` gate. Neither
    the old nor the new series is locked or version-bumped, exactly as create
    reads an existing series without a lock: a series is never deleted (its
    foreign keys are RESTRICT), the composite foreign key `(meeting_series_id,
    principal_id)` enforces same-principal custody structurally, and a series
    version covers only the series' own fields, never its occurrence set.
    """
    return {
        "meeting_series_id": meeting.meeting_series_id,
        "title": meeting.title,
        "start_at": meeting.start_at,
        "end_at": meeting.end_at,
        "timezone_name": meeting.timezone_name,
        "status": MeetingStatus(meeting.status).value,
        "cancelled_at": meeting.cancelled_at,
        "location_text": meeting.location_text,
        "virtual_meeting_url": meeting.virtual_meeting_url,
        "description": meeting.description,
        "project_id": meeting.project_id,
        "version": meeting.version,
        "updated_at": meeting.updated_at,
    }
