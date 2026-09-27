"""WP-MTG-03: `MeetingApplication` on the general unit of work, on a live server.

The `database` tier (routed to database-current-head); the tests that inject a
mid-mutation failure or run overlapping transactions also carry `recovery`
(routed to database-recovery). The Meeting tables exist in a migrated database
only once the WP-MTG-04 revision does, so this module is authored in WP-MTG-03
and first executed in WP-MTG-04 (plan D-12); nothing here builds a schema.

Every test drives `MeetingApplication` through a real `SqlAlchemyUnitOfWork`,
the one `ApplicationService.invoke` opens, so what is proved is the
application half of the Meeting acceptance criteria as it runs in production:
create in all three series states, read, list and search, update of scalars,
attendees, attachments and notes, series retitling, no-op receipts, replay of
the original receipt beside the current state, the conflict and not-found
answers, the section 35.6 reference rules, total rollback on failure, and the
behaviour of overlapping writers.

Every identifier, title, name, address and link here is synthetic.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import ClassVar, Final, Literal

import pytest
from sqlalchemy import Engine, Table, func, insert, select, text
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import OperationalError

from my_pa.application.meetings import (
    MeetingApplication,
    MeetingSeriesWriteResult,
    MeetingWriteResult,
    meeting_request_digest,
)
from my_pa.contracts.ports import (
    MeetingAttendeeRecord,
    MeetingEntityState,
    MeetingNoteRecord,
    MeetingRecord,
    MeetingRepository,
    UnitOfWork,
)
from my_pa.contracts.v1.meetings import MeetingView
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.documents.managed import DocumentState
from my_pa.domain.meeting.model import (
    MEETINGS_CREATE_NAME,
    MEETINGS_SERIES_UPDATE_NAME,
    MEETINGS_UPDATE_NAME,
    AttendeeResponseStatus,
    MeetingAttachmentAvailability,
    MeetingClearField,
    MeetingCreateRequest,
    MeetingCursorError,
    MeetingError,
    MeetingErrorField,
    MeetingHistoryAction,
    MeetingIdempotencyConflictError,
    MeetingInvalidRequestError,
    MeetingListRequest,
    MeetingNotesMode,
    MeetingNotFoundError,
    MeetingOutcome,
    MeetingSearchRequest,
    MeetingSeriesUpdateRequest,
    MeetingStaleVersionError,
    MeetingStatus,
    MeetingUpdateRequest,
    NormalizedAttendee,
    normalize_attendee,
    normalize_attendee_email,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.meetings import SqlMeetingRepository
from my_pa.infrastructure.persistence.tables import (
    capture_conversations,
    captures,
    commitments,
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
    task_history,
    tasks,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

T0: Final = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
NOW: Final = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
LATER: Final = NOW + timedelta(hours=1)
LATEST: Final = NOW + timedelta(hours=2)
ZONE: Final = "America/New_York"

#: How long the test waits for the waiting thread once the holder has finished.
#: Every engine carries the repository's 30 s statement timeout, so a build that
#: takes no lock reports as a database error well inside this bound.
JOIN_TIMEOUT_SECONDS: Final = 60.0
#: How long the test waits to observe the second transaction blocked.
BLOCK_DEADLINE_SECONDS: Final = 15.0

APP: Final = MeetingApplication()

MEETING_TABLES: Final[tuple[Table, ...]] = (
    meeting_series,
    meetings,
    meeting_attendees,
    meeting_attachments,
    meeting_history,
    meeting_note_versions,
    meeting_series_history,
    meeting_write_requests,
)


# ------------------------------------------------------------------ staging


@dataclass(frozen=True)
class Partition:
    """One Principal's synthetic reference rows on the other planes."""

    principal_id: str
    project_id: str
    person_ids: tuple[str, str, str]
    organization_id: str
    inactive_person_id: str
    document_id: str
    archived_document_id: str


def _entity(connection: Connection, principal_id: str, entity_type: str, status: str) -> str:
    entity_id = issue_identifier(IdKind.ENTITY)
    connection.execute(
        insert(entities).values(
            entity_id=entity_id,
            principal_id=principal_id,
            entity_type=entity_type,
            canonical_name=f"synthetic {entity_type}",
            display_name=f"Synthetic {entity_type}",
            status=status,
            created_at=T0,
            updated_at=T0,
            version=1,
        )
    )
    return entity_id


def _document(connection: Connection, principal_id: str, *, archived: bool) -> str:
    document_id = issue_identifier(IdKind.MANAGED_DOCUMENT)
    connection.execute(
        insert(managed_documents).values(
            document_id=document_id, owner_principal_id=principal_id, created_at=T0
        )
    )
    connection.execute(
        insert(managed_document_versions).values(
            version_id=issue_identifier(IdKind.MANAGED_DOCUMENT_VERSION),
            document_id=document_id,
            version_number=1,
            supersedes_version_id=None,
            owner_principal_id=principal_id,
            title="Synthetic agenda",
            media_type="text/markdown",
            content_sha256=hashlib.sha256(document_id.encode()).hexdigest(),
            byte_size=16,
            idempotency_key=f"doc-{document_id}",
            correlation_id=issue_identifier(IdKind.CORRELATION),
            recorded_at=T0,
        )
    )
    if archived:
        connection.execute(
            insert(managed_document_lifecycle_events).values(
                event_id=issue_identifier(IdKind.MANAGED_LIFECYCLE),
                document_id=document_id,
                principal_id=principal_id,
                transition="archived",
                sequence_number=1,
                correlation_id=issue_identifier(IdKind.CORRELATION),
                recorded_at=T0,
            )
        )
    return document_id


def _partition(connection: Connection) -> Partition:
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    project_id = issue_identifier(IdKind.PROJECT)
    # A closed Project: Meeting accepts a same-Principal Project in any state.
    connection.execute(
        insert(projects).values(
            project_id=project_id,
            principal_id=principal_id,
            name="Synthetic project",
            state="closed",
            participants=[],
            opened_at=T0,
            closed_at=T0,
            created_at=T0,
            updated_at=T0,
        )
    )
    people = tuple(sorted(_entity(connection, principal_id, "person", "active") for _ in range(3)))
    return Partition(
        principal_id=principal_id,
        project_id=project_id,
        person_ids=(people[0], people[1], people[2]),
        organization_id=_entity(connection, principal_id, "organization", "active"),
        inactive_person_id=_entity(connection, principal_id, "person", "inactive"),
        document_id=_document(connection, principal_id, archived=False),
        archived_document_id=_document(connection, principal_id, archived=True),
    )


@dataclass(frozen=True)
class Stage:
    mine: Partition
    theirs: Partition


class Harness:
    """Opens the general unit of work exactly as `ApplicationService.invoke` does."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.audit = SqlAlchemyAuditSink(engine)

    def uow(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self.engine, audit=self.audit)

    def run[ResultT](self, work: Callable[[UnitOfWork], ResultT]) -> ResultT:
        with self.uow() as uow:
            return work(uow)

    def create(
        self, principal_id: str, request: MeetingCreateRequest, key: str, *, now: datetime = NOW
    ) -> MeetingWriteResult:
        return self.run(lambda uow: APP.create_meeting(uow, principal_id, request, key, now))

    def update(
        self,
        principal_id: str,
        request: MeetingUpdateRequest,
        expected_version: int,
        key: str,
        *,
        now: datetime = LATER,
    ) -> MeetingWriteResult:
        return self.run(
            lambda uow: APP.update_meeting(uow, principal_id, request, expected_version, key, now)
        )

    def update_series(
        self,
        principal_id: str,
        request: MeetingSeriesUpdateRequest,
        expected_version: int,
        key: str,
        *,
        now: datetime = LATER,
    ) -> MeetingSeriesWriteResult:
        return self.run(
            lambda uow: APP.update_meeting_series(
                uow, principal_id, request, expected_version, key, now
            )
        )

    def read(self, principal_id: str, meeting_id: str) -> MeetingView:
        return self.run(lambda uow: APP.read_meeting(uow, principal_id, meeting_id))


@pytest.fixture
def harness(db_engine: Engine) -> Harness:
    return Harness(db_engine)


@pytest.fixture
def stage(db_engine: Engine) -> Stage:
    with db_engine.begin() as connection:
        return Stage(mine=_partition(connection), theirs=_partition(connection))


def _create_request(**overrides: object) -> MeetingCreateRequest:
    values: dict[str, object] = {
        "title": "Synthetic weekly sync",
        "start_at": T0 + timedelta(days=30),
        "timezone_name": ZONE,
    }
    values.update(overrides)
    return MeetingCreateRequest(**values)


def _person(entity_id: str, **overrides: object) -> NormalizedAttendee:
    return normalize_attendee(entity_id=entity_id, **overrides)


def _count(engine: Engine, table: Table, **where: object) -> int:
    statement = select(func.count()).select_from(table)
    for column, value in where.items():
        statement = statement.where(table.c[column] == value)
    with engine.connect() as connection:
        return int(connection.execute(statement).scalar_one())


def _rows(engine: Engine, table: Table, **where: object) -> list[RowMapping]:
    statement = select(table)
    for column, value in where.items():
        statement = statement.where(table.c[column] == value)
    with engine.connect() as connection:
        return list(connection.execute(statement).mappings().all())


def _request_row(engine: Engine, principal_id: str, capability: str, key: str) -> RowMapping:
    (row,) = _rows(
        engine,
        meeting_write_requests,
        principal_id=principal_id,
        capability=capability,
        idempotency_key=key,
    )
    return row


def _meeting_rows_of(engine: Engine, principal_id: str) -> dict[str, int]:
    return {
        table.name: _count(engine, table, principal_id=principal_id) for table in MEETING_TABLES
    }


def _document_rows(engine: Engine, document_id: str) -> list[list[RowMapping]]:
    return [
        _rows(engine, managed_documents, document_id=document_id),
        _rows(engine, managed_document_versions, document_id=document_id),
        _rows(engine, managed_document_lifecycle_events, document_id=document_id),
    ]


def _same_refusal(first: MeetingError, second: MeetingError) -> None:
    """Absent and foreign are one answer: same class, same token, same message."""
    assert type(first) is type(second)
    assert first.field is second.field
    assert str(first) == str(second)


# ================================================================= create


def test_a_standalone_create_fabricates_no_series(harness: Harness, stage: Stage) -> None:
    """AC-003/AC-022/AC-001: selector A writes no series and a create receipt."""
    principal = stage.mine.principal_id
    result = harness.create(principal, _create_request(), "standalone")

    assert result.replayed is False
    assert result.series_receipt is None
    view = result.meeting
    assert view.meeting_series_id is None and view.series_title is None
    assert view.version == 1 and view.status is MeetingStatus.SCHEDULED
    assert view.cancelled_at is None
    assert result.receipt.meeting_id == view.meeting_id
    assert result.receipt.action is MeetingHistoryAction.CREATE
    assert result.receipt.outcome is MeetingOutcome.APPLIED
    assert (result.receipt.before_version, result.receipt.after_version) == (0, 1)
    assert _count(harness.engine, meeting_series, principal_id=principal) == 0
    assert _count(harness.engine, meeting_series_history, principal_id=principal) == 0

    row = _request_row(harness.engine, principal, MEETINGS_CREATE_NAME, "standalone")
    assert row["completed_at"] is not None
    assert row["meeting_id"] == view.meeting_id
    assert row["meeting_history_id"] == result.receipt.history_id
    assert row["result_version"] == 1
    # WP-MTG-02 F-05 (a), standalone half: neither series column is set.
    assert row["meeting_series_id"] is None
    assert row["meeting_series_history_id"] is None


def test_a_new_series_create_stores_both_series_results(harness: Harness, stage: Stage) -> None:
    """AC-009/AC-022 and WP-MTG-02 F-05 (a): one request, both receipts, consistent ids."""
    principal = stage.mine.principal_id
    result = harness.create(
        principal, _create_request(series_title="Synthetic series"), "new-series"
    )

    view = result.meeting
    series_receipt = result.series_receipt
    assert series_receipt is not None
    assert view.meeting_series_id is not None
    assert view.series_title == "Synthetic series"
    assert series_receipt.meeting_series_id == view.meeting_series_id
    assert (series_receipt.before_version, series_receipt.after_version) == (0, 1)
    (series_row,) = _rows(harness.engine, meeting_series, principal_id=principal)
    assert series_row["meeting_series_id"] == view.meeting_series_id
    assert series_row["version"] == 1

    row = _request_row(harness.engine, principal, MEETINGS_CREATE_NAME, "new-series")
    assert row["meeting_series_id"] == view.meeting_series_id
    assert row["meeting_series_history_id"] == series_receipt.series_history_id
    assert row["meeting_history_id"] == result.receipt.history_id
    (receipt_row,) = _rows(harness.engine, meeting_history, principal_id=principal)
    assert receipt_row["meeting_series_id"] == view.meeting_series_id


def test_an_existing_series_occurrence_leaves_the_series_alone(
    harness: Harness, stage: Stage
) -> None:
    """AC-022 and F-05 (a): the series id is stored, no series receipt, no version bump."""
    principal = stage.mine.principal_id
    first = harness.create(principal, _create_request(series_title="Synthetic series"), "first")
    series_id = first.meeting.meeting_series_id
    assert series_id is not None

    second = harness.create(
        principal,
        _create_request(title="Second occurrence", meeting_series_id=series_id),
        "second",
    )

    assert second.meeting.meeting_series_id == series_id
    assert second.meeting.series_title == "Synthetic series"
    assert second.series_receipt is None
    (series_row,) = _rows(harness.engine, meeting_series, principal_id=principal)
    assert series_row["version"] == 1
    assert _count(harness.engine, meeting_series_history, principal_id=principal) == 1
    row = _request_row(harness.engine, principal, MEETINGS_CREATE_NAME, "second")
    assert row["meeting_series_id"] == series_id
    assert row["meeting_series_history_id"] is None


def test_a_full_create_reads_back_exactly(harness: Harness, stage: Stage) -> None:
    """AC-004/AC-014/AC-015/AC-020: every field, stored exactly, read back whole."""
    mine = stage.mine
    url = "HTTPS://Synthetic.Example:443/Room/?b=2&a=1#frag"
    raw_email = "Synthetic.Organizer@Example.COM"
    request = _create_request(
        end_at=T0 + timedelta(days=30, hours=1),
        location_text="",
        virtual_meeting_url=url,
        description="<b>not html</b>\nline two",
        project_id=mine.project_id,
        attendees=(
            _person(
                mine.person_ids[0],
                email=raw_email,
                display_name="  Synthetic Organizer  ",
                is_organizer=True,
                response_status="accepted",
            ),
            normalize_attendee(display_name="Synthetic Guest"),
        ),
        attachment_document_ids=(mine.archived_document_id, mine.document_id),
        notes_markdown="# Synthetic agenda\n\n- item",
    )
    created = harness.create(mine.principal_id, request, "full")
    view = harness.read(mine.principal_id, created.meeting.meeting_id)

    assert view == created.meeting
    assert view.virtual_meeting_url == url
    assert view.location_text == ""
    assert view.description == "<b>not html</b>\nline two"
    assert view.project_id == mine.project_id
    assert view.end_at == T0 + timedelta(days=30, hours=1)
    organizer, guest = view.attendees
    assert organizer.is_organizer is True
    assert organizer.entity_id == mine.person_ids[0]
    assert organizer.email == normalize_attendee_email(raw_email)
    assert organizer.display_name == "Synthetic Organizer"
    assert organizer.response_status is AttendeeResponseStatus.ACCEPTED
    assert guest.entity_id is None and guest.email is None
    assert guest.display_name == "Synthetic Guest"
    availability = {a.document_id: a.availability for a in view.attachments}
    assert availability == {
        mine.document_id: MeetingAttachmentAvailability.ACTIVE,
        mine.archived_document_id: MeetingAttachmentAvailability.ARCHIVED,
    }
    assert all(a.title == "Synthetic agenda" for a in view.attachments)
    notes = view.notes
    assert notes is not None
    assert notes.version_number == 1
    assert notes.body_markdown == "# Synthetic agenda\n\n- item"
    (note_row,) = _rows(harness.engine, meeting_note_versions, principal_id=mine.principal_id)
    assert note_row["meeting_history_id"] == created.receipt.history_id
    assert note_row["supersedes_note_version_id"] is None


@pytest.mark.parametrize(
    ("start_at", "instant"),
    [
        # Spring forward in New York: 02:30 local does not exist on 2026-03-08,
        # and an offset that is not New York's is accepted as an instant anyway.
        (
            datetime.fromisoformat("2026-03-08T02:30:00+09:00"),
            datetime(2026, 3, 7, 17, 30, tzinfo=UTC),
        ),
        # Fall back: 01:30 local happens twice on 2026-11-01; each offset is
        # its own instant and nothing is guessed.
        (
            datetime.fromisoformat("2026-11-01T01:30:00-04:00"),
            datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
        ),
        (
            datetime.fromisoformat("2026-11-01T01:30:00-05:00"),
            datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
        ),
    ],
)
def test_an_aware_instant_round_trips_with_its_retained_zone(
    harness: Harness, stage: Stage, start_at: datetime, instant: datetime
) -> None:
    """AC-005/AC-006: stored as the UTC instant; the zone is retained context only."""
    principal = stage.mine.principal_id
    created = harness.create(principal, _create_request(start_at=start_at), "dst")
    view = harness.read(principal, created.meeting.meeting_id)

    assert view.start_at == instant
    assert view.start_at.utcoffset() == timedelta(0)
    assert view.timezone_name == ZONE


def test_a_naive_start_is_refused_before_any_write() -> None:
    """AC-006: a naive wall time never reaches the application."""
    with pytest.raises(MeetingInvalidRequestError) as refused:
        _create_request(start_at=datetime(2026, 3, 8, 2, 30))
    assert refused.value.field is MeetingErrorField.START_AT


def test_a_snapshot_attendee_creates_no_entity(harness: Harness, stage: Stage) -> None:
    """AC-011: name/email attendees are snapshots; no contact is created."""
    before = _count(harness.engine, entities)
    harness.create(
        stage.mine.principal_id,
        _create_request(
            attendees=(
                normalize_attendee(display_name="Synthetic Visitor", email="visitor@example.test"),
            )
        ),
        "snapshot",
    )
    assert _count(harness.engine, entities) == before


def test_meeting_writes_touch_no_task_conversation_or_capture(
    harness: Harness, stage: Stage
) -> None:
    """AC-021: no Task, Commitment, capture, conversation or Entity side effect."""
    watched = (
        tasks,
        task_history,
        commitments,
        captures,
        capture_conversations,
        entities,
        projects,
    )
    before = {table.name: _count(harness.engine, table) for table in watched}
    principal = stage.mine.principal_id
    created = harness.create(
        principal,
        _create_request(
            attendees=(_person(stage.mine.person_ids[0]),),
            notes_markdown="- follow up with synthetic vendor",
        ),
        "no-side-effect",
    )
    harness.update(
        principal,
        MeetingUpdateRequest(
            meeting_id=created.meeting.meeting_id,
            notes_mode=MeetingNotesMode.APPEND,
            notes_markdown="- action: synthetic task",
        ),
        1,
        "no-side-effect-update",
    )
    assert {table.name: _count(harness.engine, table) for table in watched} == before


def test_duplicate_attendees_are_refused_before_any_write() -> None:
    """AC-012/AC-013: normalized email collision and a second organizer are refused."""
    with pytest.raises(MeetingInvalidRequestError) as duplicate:
        _create_request(
            attendees=(
                normalize_attendee(email="Same@Example.test"),
                normalize_attendee(email="same@example.test", display_name="Other"),
            )
        )
    assert duplicate.value.field is MeetingErrorField.DUPLICATE_ATTENDEE
    with pytest.raises(MeetingInvalidRequestError) as organizers:
        _create_request(
            attendees=(
                normalize_attendee(display_name="One", is_organizer=True),
                normalize_attendee(display_name="Two", is_organizer=True),
            )
        )
    assert organizers.value.field is MeetingErrorField.ORGANIZER


# ------------------------------------------------------- reference validation


def _reference_request(kind: str, partition: Partition, absent: bool) -> MeetingCreateRequest:
    if kind == "project":
        return _create_request(
            project_id=issue_identifier(IdKind.PROJECT) if absent else partition.project_id
        )
    if kind == "document":
        return _create_request(
            attachment_document_ids=(
                issue_identifier(IdKind.MANAGED_DOCUMENT) if absent else partition.document_id,
            )
        )
    return _create_request(
        attendees=(_person(issue_identifier(IdKind.ENTITY) if absent else partition.person_ids[0]),)
    )


@pytest.mark.parametrize(
    ("kind", "token"),
    [
        ("project", MeetingErrorField.PROJECT_ID),
        ("document", MeetingErrorField.DOCUMENT_ID),
        ("entity", MeetingErrorField.ENTITY_ID),
    ],
)
def test_an_absent_and_a_foreign_reference_are_the_same_not_found(
    harness: Harness, stage: Stage, kind: str, token: MeetingErrorField
) -> None:
    """AC-020/AC-032: absent and foreign Project/Document/Entity are indistinguishable."""
    principal = stage.mine.principal_id
    with pytest.raises(MeetingNotFoundError) as absent:
        harness.create(principal, _reference_request(kind, stage.mine, absent=True), "absent")
    with pytest.raises(MeetingNotFoundError) as foreign:
        harness.create(principal, _reference_request(kind, stage.theirs, absent=False), "foreign")
    assert absent.value.field is token
    _same_refusal(absent.value, foreign.value)
    # The refused request rolled back with its reservation.
    assert _meeting_rows_of(harness.engine, principal) == dict.fromkeys(
        (table.name for table in MEETING_TABLES), 0
    )


def test_an_absent_and_a_foreign_series_are_the_same_not_found(
    harness: Harness, stage: Stage
) -> None:
    """AC-032: an occurrence of another Principal's series answers as an absent one."""
    theirs = harness.create(
        stage.theirs.principal_id, _create_request(series_title="Their series"), "theirs"
    )
    foreign_series = theirs.meeting.meeting_series_id
    assert foreign_series is not None
    principal = stage.mine.principal_id
    with pytest.raises(MeetingNotFoundError) as absent:
        harness.create(
            principal,
            _create_request(meeting_series_id=issue_identifier(IdKind.MEETING_SERIES)),
            "absent",
        )
    with pytest.raises(MeetingNotFoundError) as foreign:
        harness.create(principal, _create_request(meeting_series_id=foreign_series), "foreign")
    assert absent.value.field is MeetingErrorField.MEETING_SERIES_ID
    _same_refusal(absent.value, foreign.value)


@pytest.mark.parametrize("which", ["organization", "inactive_person"])
def test_a_non_person_or_inactive_entity_is_invalid(
    harness: Harness, stage: Stage, which: str
) -> None:
    """Section 35.6: a same-Principal Entity that is not an ACTIVE Person is refused."""
    entity_id = (
        stage.mine.organization_id if which == "organization" else stage.mine.inactive_person_id
    )
    with pytest.raises(MeetingInvalidRequestError) as refused:
        harness.create(
            stage.mine.principal_id,
            _create_request(attendees=(_person(entity_id),)),
            "not-a-person",
        )
    assert refused.value.field is MeetingErrorField.ENTITY_ID


def test_an_archived_document_is_an_eligible_attachment(harness: Harness, stage: Stage) -> None:
    """Section 35.6: ACTIVE and ARCHIVED same-Principal documents both attach."""
    created = harness.create(
        stage.mine.principal_id,
        _create_request(attachment_document_ids=(stage.mine.archived_document_id,)),
        "archived",
    )
    (attachment,) = created.meeting.attachments
    assert attachment.availability is MeetingAttachmentAvailability.ARCHIVED


# ======================================================== idempotent replay


def test_the_same_key_and_request_replays_the_original(harness: Harness, stage: Stage) -> None:
    """AC-029: a replay writes nothing and answers the original receipt."""
    principal = stage.mine.principal_id
    request = _create_request(series_title="Synthetic series", notes_markdown="agenda")
    first = harness.create(principal, request, "replay")
    before = _meeting_rows_of(harness.engine, principal)

    second = harness.create(principal, request, "replay", now=LATEST)

    assert second.replayed is True
    assert second.meeting == first.meeting
    assert second.receipt == first.receipt
    assert second.series_receipt == first.series_receipt
    assert _meeting_rows_of(harness.engine, principal) == before


def test_a_replay_after_a_later_change_shows_the_current_meeting(
    harness: Harness, stage: Stage
) -> None:
    """AC-029, section 35.7: the original receipt beside the current aggregate."""
    principal = stage.mine.principal_id
    request = _create_request()
    first = harness.create(principal, request, "create-key")
    harness.update(
        principal,
        MeetingUpdateRequest(meeting_id=first.meeting.meeting_id, title="Renamed sync"),
        1,
        "rename",
    )

    replay = harness.create(principal, request, "create-key", now=LATEST)

    assert replay.replayed is True
    assert replay.receipt == first.receipt
    assert replay.receipt.after_version == 1
    assert replay.meeting.version == 2
    assert replay.meeting.title == "Renamed sync"


def test_the_same_key_with_a_different_request_conflicts(harness: Harness, stage: Stage) -> None:
    """AC-029: a reused key with a different digest is a conflict, not a replay."""
    principal = stage.mine.principal_id
    harness.create(principal, _create_request(), "reused")
    before = _meeting_rows_of(harness.engine, principal)
    with pytest.raises(MeetingIdempotencyConflictError):
        harness.create(principal, _create_request(title="Different"), "reused")
    assert _meeting_rows_of(harness.engine, principal) == before


def test_an_update_replay_answers_its_original_receipt(harness: Harness, stage: Stage) -> None:
    """AC-029: update replay; the same key under another Principal is independent."""
    principal = stage.mine.principal_id
    created = harness.create(principal, _create_request(), "c")
    update = MeetingUpdateRequest(meeting_id=created.meeting.meeting_id, title="Renamed")
    first = harness.update(principal, update, 1, "u")
    again = harness.update(principal, update, 1, "u", now=LATEST)

    assert again.replayed is True
    assert again.receipt == first.receipt
    assert again.meeting.version == 2
    with pytest.raises(MeetingIdempotencyConflictError):
        harness.update(principal, update, 2, "u")


# ==================================================================== read


def test_an_absent_and_a_foreign_meeting_read_the_same(harness: Harness, stage: Stage) -> None:
    """AC-023/AC-032: read by durable id; foreign is indistinguishable from absent."""
    theirs = harness.create(stage.theirs.principal_id, _create_request(), "theirs")
    principal = stage.mine.principal_id
    with pytest.raises(MeetingNotFoundError) as absent:
        harness.read(principal, issue_identifier(IdKind.MEETING))
    with pytest.raises(MeetingNotFoundError) as foreign:
        harness.read(principal, theirs.meeting.meeting_id)
    assert absent.value.field is MeetingErrorField.MEETING_ID
    _same_refusal(absent.value, foreign.value)


# ============================================================ list / search


def _three_meetings(harness: Harness, principal_id: str) -> list[MeetingView]:
    return [
        harness.create(
            principal_id,
            _create_request(title=f"Synthetic sync {day}", start_at=T0 + timedelta(days=day)),
            f"list-{day}",
        ).meeting
        for day in (1, 2, 3)
    ]


def test_list_pages_by_keyset_inside_the_partition(harness: Harness, stage: Stage) -> None:
    """AC-024: bounded pages over (start_at, meeting_id); only this Principal's rows."""
    principal = stage.mine.principal_id
    made = _three_meetings(harness, principal)
    harness.create(stage.theirs.principal_id, _create_request(), "theirs")

    first = harness.run(
        lambda uow: APP.list_meetings(uow, principal, MeetingListRequest(page_size=2), NOW)
    )
    assert [e.meeting_id for e in first.entries] == [m.meeting_id for m in made[:2]]
    assert first.has_more is True
    rest = harness.run(
        lambda uow: APP.list_meetings(
            uow, principal, MeetingListRequest(page_size=2, after=made[1].meeting_id), NOW
        )
    )
    assert [e.meeting_id for e in rest.entries] == [made[2].meeting_id]
    assert rest.has_more is False


def test_a_cursor_outside_the_partition_or_filter_is_refused(
    harness: Harness, stage: Stage
) -> None:
    """AC-024/AC-032: a foreign anchor or one outside the filter is a cursor error."""
    principal = stage.mine.principal_id
    made = _three_meetings(harness, principal)
    theirs = harness.create(stage.theirs.principal_id, _create_request(), "theirs")

    with pytest.raises(MeetingCursorError):
        harness.run(
            lambda uow: APP.list_meetings(
                uow, principal, MeetingListRequest(after=theirs.meeting.meeting_id), NOW
            )
        )
    with pytest.raises(MeetingCursorError):
        harness.run(
            lambda uow: APP.list_meetings(
                uow,
                principal,
                MeetingListRequest(status=MeetingStatus.CANCELLED, after=made[0].meeting_id),
                NOW,
            )
        )


def test_search_matches_the_current_note_head_only(harness: Harness, stage: Stage) -> None:
    """AC-025: a replaced note body is no longer searchable; the current one is."""
    principal = stage.mine.principal_id
    created = harness.create(principal, _create_request(notes_markdown="zebracrossing"), "s")
    harness.update(
        principal,
        MeetingUpdateRequest(
            meeting_id=created.meeting.meeting_id,
            notes_mode=MeetingNotesMode.REPLACE,
            notes_markdown="yakshaving",
        ),
        1,
        "replace",
    )

    def search(query: str) -> list[str]:
        page = harness.run(
            lambda uow: APP.search_meetings(uow, principal, MeetingSearchRequest(query=query), NOW)
        )
        return [entry.meeting_id for entry in page.entries]

    assert search("zebracrossing") == []
    assert search("yakshaving") == [created.meeting.meeting_id]


# ================================================================== update


def _created(harness: Harness, stage: Stage, **overrides: object) -> MeetingView:
    return harness.create(stage.mine.principal_id, _create_request(**overrides), "seed").meeting


def test_a_scalar_update_bumps_the_version_once(harness: Harness, stage: Stage) -> None:
    """AC-026: one row lock, one version gate, one increment."""
    principal = stage.mine.principal_id
    seed = _created(harness, stage)
    result = harness.update(
        principal,
        MeetingUpdateRequest(
            meeting_id=seed.meeting_id,
            title="Renamed sync",
            location_text="Synthetic room",
            description="synthetic",
            project_id=stage.mine.project_id,
        ),
        1,
        "scalars",
    )
    view = result.meeting
    assert view.meeting_id == seed.meeting_id
    assert view.version == 2
    assert (view.title, view.location_text, view.project_id) == (
        "Renamed sync",
        "Synthetic room",
        stage.mine.project_id,
    )
    assert view.updated_at == LATER
    assert view.created_at == seed.created_at
    assert result.receipt.action is MeetingHistoryAction.UPDATE
    assert result.receipt.outcome is MeetingOutcome.APPLIED
    assert (result.receipt.before_version, result.receipt.after_version) == (1, 2)
    row = _request_row(harness.engine, principal, MEETINGS_UPDATE_NAME, "scalars")
    assert row["result_version"] == 2
    assert row["meeting_history_id"] == result.receipt.history_id


def test_reschedule_cancel_and_reinstate_keep_identity(harness: Harness, stage: Stage) -> None:
    """AC-007/AC-008/AC-001: meeting_id and series never change; cancelled_at is server-owned."""
    principal = stage.mine.principal_id
    seed = _created(harness, stage, series_title="Synthetic series")
    moved = harness.update(
        principal,
        MeetingUpdateRequest(
            meeting_id=seed.meeting_id,
            start_at=T0 + timedelta(days=40),
            end_at=T0 + timedelta(days=40, hours=1),
        ),
        1,
        "move",
    ).meeting
    cancelled = harness.update(
        principal,
        MeetingUpdateRequest(meeting_id=seed.meeting_id, status=MeetingStatus.CANCELLED),
        2,
        "cancel",
        now=LATER,
    ).meeting
    reinstated = harness.update(
        principal,
        MeetingUpdateRequest(meeting_id=seed.meeting_id, status=MeetingStatus.SCHEDULED),
        3,
        "reinstate",
        now=LATEST,
    ).meeting

    for view in (moved, cancelled, reinstated):
        assert view.meeting_id == seed.meeting_id
        assert view.meeting_series_id == seed.meeting_series_id
    assert moved.start_at == T0 + timedelta(days=40)
    assert cancelled.status is MeetingStatus.CANCELLED
    assert cancelled.cancelled_at == LATER
    assert reinstated.status is MeetingStatus.SCHEDULED
    assert reinstated.cancelled_at is None
    assert reinstated.version == 4


def test_a_start_that_overtakes_the_stored_end_is_refused(harness: Harness, stage: Stage) -> None:
    """Section 35.6: the resulting schedule, not only the supplied pair, is ordered."""
    seed = _created(harness, stage, end_at=T0 + timedelta(days=30, hours=1))
    with pytest.raises(MeetingInvalidRequestError) as refused:
        harness.update(
            stage.mine.principal_id,
            MeetingUpdateRequest(meeting_id=seed.meeting_id, start_at=T0 + timedelta(days=31)),
            1,
            "overtake",
        )
    assert refused.value.field is MeetingErrorField.END_AT


@pytest.mark.parametrize(
    ("field_name", "clear", "value"),
    [
        ("end_at", MeetingClearField.END_AT, T0 + timedelta(days=30, hours=2)),
        ("location_text", MeetingClearField.LOCATION_TEXT, "Other room"),
        ("virtual_meeting_url", MeetingClearField.VIRTUAL_MEETING_URL, "https://other.example"),
        ("description", MeetingClearField.DESCRIPTION, "other"),
    ],
)
def test_a_value_and_a_clear_of_the_same_field_leave_it_cleared(
    harness: Harness, stage: Stage, field_name: str, clear: MeetingClearField, value: object
) -> None:
    """WP-MTG-01 review F-01: the explicit clear wins ("clear_fields means clear")."""
    seed = _created(
        harness,
        stage,
        end_at=T0 + timedelta(days=30, hours=1),
        location_text="Synthetic room",
        virtual_meeting_url="https://synthetic.example/room",
        description="synthetic",
    )
    result = harness.update(
        stage.mine.principal_id,
        MeetingUpdateRequest(
            meeting_id=seed.meeting_id, clear_fields=(clear,), **{field_name: value}
        ),
        1,
        "set-and-clear",
    )
    assert result.meeting.model_dump()[field_name] is None
    assert result.meeting.version == 2


def test_an_update_stores_the_meetings_own_series(harness: Harness, stage: Stage) -> None:
    """WP-MTG-02 F-05 (b): request and receipt name the Meeting's own series or none."""
    principal = stage.mine.principal_id
    member = harness.create(
        principal, _create_request(series_title="Synthetic series"), "member"
    ).meeting
    alone = harness.create(principal, _create_request(), "alone").meeting
    for view, key in ((member, "u-member"), (alone, "u-alone")):
        result = harness.update(
            principal, MeetingUpdateRequest(meeting_id=view.meeting_id, title="Retitled"), 1, key
        )
        row = _request_row(harness.engine, principal, MEETINGS_UPDATE_NAME, key)
        assert row["meeting_series_id"] == view.meeting_series_id
        assert row["meeting_series_history_id"] is None
        (receipt_row,) = _rows(
            harness.engine, meeting_history, history_id=result.receipt.history_id
        )
        assert receipt_row["meeting_series_id"] == view.meeting_series_id


def test_attendees_replace_retires_and_inserts_under_the_parent(
    harness: Harness, stage: Stage
) -> None:
    """AC-026/AC-012: a full replacement retires the old active set."""
    principal = stage.mine.principal_id
    people = stage.mine.person_ids
    seed = _created(harness, stage, attendees=(_person(people[0], is_organizer=True),))
    replaced = harness.update(
        principal,
        MeetingUpdateRequest(
            meeting_id=seed.meeting_id,
            attendees_replace=(_person(people[1]), _person(people[2], is_organizer=True)),
        ),
        1,
        "replace",
    ).meeting
    assert {a.entity_id for a in replaced.attendees} == {people[1], people[2]}
    assert replaced.attendees[0].entity_id == people[2]  # the organizer reads first
    retired = _rows(harness.engine, meeting_attendees, entity_id=people[0])
    assert len(retired) == 1 and retired[0]["removed_at"] == LATER

    emptied = harness.update(
        principal, MeetingUpdateRequest(meeting_id=seed.meeting_id, attendees_replace=()), 2, "e"
    ).meeting
    assert emptied.attendees == ()
    assert emptied.version == 3


def test_an_identical_attendee_replacement_is_a_no_op(harness: Harness, stage: Stage) -> None:
    """Section 35.9: the normalized active set equals the current one."""
    people = stage.mine.person_ids
    attendees = (_person(people[0], is_organizer=True), normalize_attendee(display_name="Guest"))
    seed = _created(harness, stage, attendees=attendees)
    result = harness.update(
        stage.mine.principal_id,
        MeetingUpdateRequest(meeting_id=seed.meeting_id, attendees_replace=attendees[::-1]),
        1,
        "same-set",
    )
    assert result.receipt.outcome is MeetingOutcome.NO_OP
    assert result.meeting.version == 1
    assert {a.attendee_id for a in result.meeting.attendees} == {
        a.attendee_id for a in seed.attendees
    }


def test_attach_and_detach_never_touch_the_document(harness: Harness, stage: Stage) -> None:
    """AC-017: only the Meeting-document relation changes."""
    principal = stage.mine.principal_id
    document_id = stage.mine.document_id
    before = _document_rows(harness.engine, document_id)
    seed = _created(harness, stage)
    attached = harness.update(
        principal,
        MeetingUpdateRequest(
            meeting_id=seed.meeting_id, attachment_add_document_ids=(document_id,)
        ),
        1,
        "attach",
    ).meeting
    (attachment,) = attached.attachments
    detached = harness.update(
        principal,
        MeetingUpdateRequest(
            meeting_id=seed.meeting_id, attachment_remove_ids=(attachment.attachment_id,)
        ),
        2,
        "detach",
    ).meeting
    assert detached.attachments == ()
    (relation,) = _rows(harness.engine, meeting_attachments, attachment_id=attachment.attachment_id)
    assert relation["removed_at"] == LATER
    assert _document_rows(harness.engine, document_id) == before


def test_attachment_add_and_remove_refusals(harness: Harness, stage: Stage) -> None:
    """Section 35.9: add of an active relation is invalid; a non-active removal is not found."""
    principal = stage.mine.principal_id
    seed = _created(harness, stage, attachment_document_ids=(stage.mine.document_id,))
    (attachment,) = seed.attachments

    with pytest.raises(MeetingInvalidRequestError) as duplicate:
        harness.update(
            principal,
            MeetingUpdateRequest(
                meeting_id=seed.meeting_id, attachment_add_document_ids=(stage.mine.document_id,)
            ),
            1,
            "dup",
        )
    assert duplicate.value.field is MeetingErrorField.DOCUMENT_ID

    theirs = harness.create(
        stage.theirs.principal_id,
        _create_request(attachment_document_ids=(stage.theirs.document_id,)),
        "theirs",
    ).meeting
    refusals = []
    for missing in (
        issue_identifier(IdKind.MEETING_ATTACHMENT),
        theirs.attachments[0].attachment_id,
    ):
        with pytest.raises(MeetingNotFoundError) as refused:
            harness.update(
                principal,
                MeetingUpdateRequest(meeting_id=seed.meeting_id, attachment_remove_ids=(missing,)),
                1,
                f"rm-{missing}",
            )
        refusals.append(refused.value)
    assert refusals[0].field is MeetingErrorField.ATTACHMENT_ID
    _same_refusal(refusals[0], refusals[1])

    harness.update(
        principal,
        MeetingUpdateRequest(
            meeting_id=seed.meeting_id, attachment_remove_ids=(attachment.attachment_id,)
        ),
        1,
        "rm",
    )
    with pytest.raises(MeetingNotFoundError):
        harness.update(
            principal,
            MeetingUpdateRequest(
                meeting_id=seed.meeting_id, attachment_remove_ids=(attachment.attachment_id,)
            ),
            2,
            "rm-again",
        )
    with pytest.raises(MeetingNotFoundError) as foreign_document:
        harness.update(
            principal,
            MeetingUpdateRequest(
                meeting_id=seed.meeting_id, attachment_add_document_ids=(stage.theirs.document_id,)
            ),
            2,
            "foreign-doc",
        )
    assert foreign_document.value.field is MeetingErrorField.DOCUMENT_ID


def test_notes_append_replace_and_identical_replace(harness: Harness, stage: Stage) -> None:
    """AC-019/AC-018: append composes, replace stores, identical replace is a no-op."""
    principal = stage.mine.principal_id
    seed = _created(harness, stage)

    def notes(mode: MeetingNotesMode, body: str, version: int, key: str) -> MeetingWriteResult:
        return harness.update(
            principal,
            MeetingUpdateRequest(meeting_id=seed.meeting_id, notes_mode=mode, notes_markdown=body),
            version,
            key,
        )

    first = notes(MeetingNotesMode.APPEND, "first", 1, "n1")
    assert first.meeting.notes is not None and first.meeting.notes.body_markdown == "first"
    second = notes(MeetingNotesMode.APPEND, "second", 2, "n2")
    assert second.meeting.notes is not None
    assert second.meeting.notes.body_markdown == "first\n\nsecond"
    assert second.meeting.notes.version_number == 2
    same = notes(MeetingNotesMode.REPLACE, "first\n\nsecond", 3, "n3")
    assert same.receipt.outcome is MeetingOutcome.NO_OP
    assert same.meeting.version == 3
    replaced = notes(MeetingNotesMode.REPLACE, "third", 3, "n4")
    assert replaced.meeting.notes is not None
    assert replaced.meeting.notes.version_number == 3
    assert replaced.meeting.version == 4

    versions = sorted(
        _rows(harness.engine, meeting_note_versions, meeting_id=seed.meeting_id),
        key=lambda row: row["version_number"],
    )
    assert [row["content_markdown"] for row in versions] == ["first", "first\n\nsecond", "third"]
    assert versions[1]["supersedes_note_version_id"] == versions[0]["note_version_id"]
    assert versions[2]["supersedes_note_version_id"] == versions[1]["note_version_id"]
    assert versions[2]["meeting_history_id"] == replaced.receipt.history_id


def test_an_update_to_the_current_values_is_a_no_op_with_a_receipt(
    harness: Harness, stage: Stage
) -> None:
    """Section 35.9: no-op history, unchanged version, completed request."""
    principal = stage.mine.principal_id
    seed = _created(harness, stage)
    result = harness.update(
        principal,
        MeetingUpdateRequest(meeting_id=seed.meeting_id, title=seed.title, timezone_name=ZONE),
        1,
        "noop",
    )
    assert result.receipt.outcome is MeetingOutcome.NO_OP
    assert (result.receipt.before_version, result.receipt.after_version) == (1, 1)
    assert result.meeting.version == 1
    assert result.meeting.updated_at == seed.updated_at
    row = _request_row(harness.engine, principal, MEETINGS_UPDATE_NAME, "noop")
    assert row["completed_at"] is not None and row["result_version"] == 1
    assert _count(harness.engine, meeting_history, meeting_id=seed.meeting_id) == 2


def test_a_stale_version_conflicts_and_writes_nothing(harness: Harness, stage: Stage) -> None:
    """AC-030: expected_version is compared under the row lock; no receipt on conflict."""
    principal = stage.mine.principal_id
    seed = _created(harness, stage)
    harness.update(principal, MeetingUpdateRequest(meeting_id=seed.meeting_id, title="A"), 1, "a")
    before = _meeting_rows_of(harness.engine, principal)
    with pytest.raises(MeetingStaleVersionError):
        harness.update(
            principal, MeetingUpdateRequest(meeting_id=seed.meeting_id, title="B"), 1, "b"
        )
    assert _meeting_rows_of(harness.engine, principal) == before


def test_an_absent_and_a_foreign_meeting_update_the_same(harness: Harness, stage: Stage) -> None:
    """AC-032: update of another Principal's Meeting answers as an absent one."""
    theirs = harness.create(stage.theirs.principal_id, _create_request(), "theirs").meeting
    principal = stage.mine.principal_id
    with pytest.raises(MeetingNotFoundError) as absent:
        harness.update(
            principal,
            MeetingUpdateRequest(meeting_id=issue_identifier(IdKind.MEETING), title="x"),
            1,
            "a",
        )
    with pytest.raises(MeetingNotFoundError) as foreign:
        harness.update(
            principal, MeetingUpdateRequest(meeting_id=theirs.meeting_id, title="x"), 1, "f"
        )
    assert absent.value.field is MeetingErrorField.MEETING_ID
    _same_refusal(absent.value, foreign.value)


def test_update_project_association_rules(harness: Harness, stage: Stage) -> None:
    """AC-020: a closed own Project is accepted; a foreign one is not found; clear works."""
    principal = stage.mine.principal_id
    seed = _created(harness, stage)
    with pytest.raises(MeetingNotFoundError) as foreign:
        harness.update(
            principal,
            MeetingUpdateRequest(meeting_id=seed.meeting_id, project_id=stage.theirs.project_id),
            1,
            "foreign",
        )
    assert foreign.value.field is MeetingErrorField.PROJECT_ID
    linked = harness.update(
        principal,
        MeetingUpdateRequest(meeting_id=seed.meeting_id, project_id=stage.mine.project_id),
        1,
        "link",
    ).meeting
    assert linked.project_id == stage.mine.project_id
    cleared = harness.update(
        principal,
        MeetingUpdateRequest(
            meeting_id=seed.meeting_id, clear_fields=(MeetingClearField.PROJECT_ID,)
        ),
        2,
        "clear",
    ).meeting
    assert cleared.project_id is None


def test_replacement_attendee_entities_are_validated(harness: Harness, stage: Stage) -> None:
    """Section 35.6 on update: foreign is not found; inactive is invalid."""
    principal = stage.mine.principal_id
    seed = _created(harness, stage)
    with pytest.raises(MeetingNotFoundError):
        harness.update(
            principal,
            MeetingUpdateRequest(
                meeting_id=seed.meeting_id,
                attendees_replace=(_person(stage.theirs.person_ids[0]),),
            ),
            1,
            "foreign",
        )
    with pytest.raises(MeetingInvalidRequestError):
        harness.update(
            principal,
            MeetingUpdateRequest(
                meeting_id=seed.meeting_id,
                attendees_replace=(_person(stage.mine.inactive_person_id),),
            ),
            1,
            "inactive",
        )


# =========================================================== series update


def test_a_series_retitle_leaves_every_occurrence_untouched(harness: Harness, stage: Stage) -> None:
    """AC-009/AC-027: only the series title, version and receipt change."""
    principal = stage.mine.principal_id
    first = harness.create(principal, _create_request(series_title="Old series"), "one").meeting
    series_id = first.meeting_series_id
    assert series_id is not None
    second = harness.create(
        principal, _create_request(title="Two", meeting_series_id=series_id), "two"
    ).meeting
    occurrences_before = _rows(harness.engine, meetings, principal_id=principal)

    result = harness.update_series(
        principal,
        MeetingSeriesUpdateRequest(meeting_series_id=series_id, title="New series"),
        1,
        "retitle",
    )

    assert result.replayed is False
    assert result.series.title == "New series"
    assert result.series.version == 2
    assert result.receipt.outcome is MeetingOutcome.APPLIED
    assert (result.receipt.before_version, result.receipt.after_version) == (1, 2)
    assert _rows(harness.engine, meetings, principal_id=principal) == occurrences_before
    assert harness.read(principal, first.meeting_id).title == first.title
    assert harness.read(principal, second.meeting_id).series_title == "New series"
    row = _request_row(harness.engine, principal, MEETINGS_SERIES_UPDATE_NAME, "retitle")
    assert row["meeting_series_id"] == series_id
    assert row["meeting_series_history_id"] == result.receipt.series_history_id
    assert row["meeting_id"] is None and row["meeting_history_id"] is None
    assert row["result_version"] == 2


def test_series_update_no_op_stale_replay_and_not_found(harness: Harness, stage: Stage) -> None:
    """Section 35.9/35.10 for the series write."""
    principal = stage.mine.principal_id
    series_id = harness.create(
        principal, _create_request(series_title="Series"), "one"
    ).meeting.meeting_series_id
    assert series_id is not None

    same = harness.update_series(
        principal, MeetingSeriesUpdateRequest(meeting_series_id=series_id, title="Series"), 1, "s"
    )
    assert same.receipt.outcome is MeetingOutcome.NO_OP
    assert same.series.version == 1

    renamed = harness.update_series(
        principal, MeetingSeriesUpdateRequest(meeting_series_id=series_id, title="Other"), 1, "r"
    )
    replay = harness.update_series(
        principal,
        MeetingSeriesUpdateRequest(meeting_series_id=series_id, title="Other"),
        1,
        "r",
        now=LATEST,
    )
    assert replay.replayed is True
    assert replay.receipt == renamed.receipt
    assert replay.series == renamed.series

    with pytest.raises(MeetingStaleVersionError):
        harness.update_series(
            principal, MeetingSeriesUpdateRequest(meeting_series_id=series_id, title="X"), 1, "x"
        )
    theirs = harness.create(
        stage.theirs.principal_id, _create_request(series_title="Theirs"), "t"
    ).meeting.meeting_series_id
    assert theirs is not None
    with pytest.raises(MeetingNotFoundError) as absent:
        harness.update_series(
            principal,
            MeetingSeriesUpdateRequest(
                meeting_series_id=issue_identifier(IdKind.MEETING_SERIES), title="X"
            ),
            1,
            "absent",
        )
    with pytest.raises(MeetingNotFoundError) as foreign:
        harness.update_series(
            principal, MeetingSeriesUpdateRequest(meeting_series_id=theirs, title="X"), 1, "f"
        )
    assert absent.value.field is MeetingErrorField.MEETING_SERIES_ID
    _same_refusal(absent.value, foreign.value)


# ================================================================== digest


def test_the_digest_is_canonical_sha256_over_the_normalized_request() -> None:
    """Section 35.9: order-insensitive where the contract says so, exact elsewhere."""
    principal = issue_identifier(IdKind.PRINCIPAL)
    documents = sorted(issue_identifier(IdKind.MANAGED_DOCUMENT) for _ in range(2))
    guests = (normalize_attendee(display_name="A"), normalize_attendee(email="b@example.test"))
    one = _create_request(attachment_document_ids=tuple(documents), attendees=guests)
    two = _create_request(attachment_document_ids=tuple(documents[::-1]), attendees=guests[::-1])

    digest = meeting_request_digest(MEETINGS_CREATE_NAME, principal, one)
    assert len(digest) == 64 and digest == digest.lower()
    assert int(digest, 16) >= 0
    assert meeting_request_digest(MEETINGS_CREATE_NAME, principal, two) == digest
    # Another Principal, another capability, a microsecond, or the exact URL all differ.
    assert meeting_request_digest(MEETINGS_CREATE_NAME, "prn_other", one) != digest
    assert meeting_request_digest(MEETINGS_UPDATE_NAME, principal, one) != digest
    shifted = _create_request(
        attachment_document_ids=tuple(documents),
        attendees=guests,
        start_at=one.start_at + timedelta(microseconds=1),
    )
    assert meeting_request_digest(MEETINGS_CREATE_NAME, principal, shifted) != digest
    upper = _create_request(virtual_meeting_url="https://Synthetic.example/a")
    lower = _create_request(virtual_meeting_url="https://synthetic.example/a")
    assert meeting_request_digest(MEETINGS_CREATE_NAME, principal, upper) != (
        meeting_request_digest(MEETINGS_CREATE_NAME, principal, lower)
    )
    # The same instant written with another offset is the same request.
    offset = _create_request(
        start_at=one.start_at.astimezone(timezone(timedelta(hours=9))),
        attachment_document_ids=tuple(documents),
        attendees=guests,
    )
    assert meeting_request_digest(MEETINGS_CREATE_NAME, principal, offset) == digest


def test_the_update_digest_separates_omission_empty_clear_and_version() -> None:
    """Section 34.14: omitted, empty replacement and clear intent hash differently."""
    principal = issue_identifier(IdKind.PRINCIPAL)
    meeting_id = issue_identifier(IdKind.MEETING)

    def digest(request: MeetingUpdateRequest, version: int = 1) -> str:
        return meeting_request_digest(
            MEETINGS_UPDATE_NAME, principal, request, expected_version=version
        )

    omitted = MeetingUpdateRequest(meeting_id=meeting_id, title="T")
    emptied = MeetingUpdateRequest(meeting_id=meeting_id, title="T", attendees_replace=())
    cleared = MeetingUpdateRequest(
        meeting_id=meeting_id, title="T", clear_fields=(MeetingClearField.END_AT,)
    )
    assert len({digest(omitted), digest(emptied), digest(cleared)}) == 3
    assert digest(omitted, 1) != digest(omitted, 2)
    both = (MeetingClearField.END_AT, MeetingClearField.DESCRIPTION)
    assert digest(MeetingUpdateRequest(meeting_id=meeting_id, clear_fields=both)) == digest(
        MeetingUpdateRequest(meeting_id=meeting_id, clear_fields=both[::-1])
    )
    appended = MeetingUpdateRequest(
        meeting_id=meeting_id, notes_mode=MeetingNotesMode.APPEND, notes_markdown="n"
    )
    replaced = MeetingUpdateRequest(
        meeting_id=meeting_id, notes_mode=MeetingNotesMode.REPLACE, notes_markdown="n"
    )
    assert digest(appended) != digest(replaced)
    series_id = issue_identifier(IdKind.MEETING_SERIES)
    retitle = MeetingSeriesUpdateRequest(meeting_series_id=series_id, title="S")
    assert meeting_request_digest(
        MEETINGS_SERIES_UPDATE_NAME, principal, retitle, expected_version=1
    ) != meeting_request_digest(MEETINGS_SERIES_UPDATE_NAME, principal, retitle, expected_version=2)


def test_the_idempotency_key_is_not_part_of_the_digest(harness: Harness, stage: Stage) -> None:
    """Section 35.9: two keys, one request, one stored digest."""
    principal = stage.mine.principal_id
    request = _create_request()
    harness.create(principal, request, "k")
    harness.create(principal, request, "a-much-longer-key-" + "x" * 100)
    digests = {
        row["request_digest"]
        for row in _rows(harness.engine, meeting_write_requests, principal_id=principal)
    }
    assert digests == {meeting_request_digest(MEETINGS_CREATE_NAME, principal, request)}


@pytest.mark.parametrize("key", ["", "k" * 129])
def test_an_out_of_bounds_key_is_refused(harness: Harness, stage: Stage, key: str) -> None:
    """Section 35.6: keys are 1..128 characters."""
    with pytest.raises(MeetingInvalidRequestError) as refused:
        harness.create(stage.mine.principal_id, _create_request(), key)
    assert refused.value.field is MeetingErrorField.IDEMPOTENCY_KEY


# ================================================================ recovery


class _InjectedError(RuntimeError):
    """A failure injected between two of a write's statements."""


class _FailsAtCompletion(SqlMeetingRepository):
    def complete_write_request(self, *args: object, **kwargs: object) -> None:
        raise _InjectedError


class _FailsAtNote(SqlMeetingRepository):
    def insert_note_version(self, principal_id: str, note: MeetingNoteRecord) -> None:
        raise _InjectedError


class _InjectingUnitOfWork(SqlAlchemyUnitOfWork):
    """The general unit of work, whose Meeting repository fails on one statement."""

    def __init__(
        self, engine: Engine, *, audit: SqlAlchemyAuditSink, repository: type[SqlMeetingRepository]
    ) -> None:
        super().__init__(engine, audit=audit)
        self._repository = repository

    @property
    def meetings(self) -> MeetingRepository:
        return self._repository(self._open)


@pytest.mark.recovery
def test_a_failure_before_completion_rolls_back_the_whole_create(
    harness: Harness, stage: Stage
) -> None:
    """AC-031/AC-022: series, Meeting, children, receipts, note and request all vanish."""
    mine = stage.mine
    request = _create_request(
        series_title="Synthetic series",
        attendees=(_person(mine.person_ids[0]),),
        attachment_document_ids=(mine.document_id,),
        notes_markdown="agenda",
    )
    documents_before = _document_rows(harness.engine, mine.document_id)
    entities_before = _count(harness.engine, entities)

    with (
        pytest.raises(_InjectedError),
        _InjectingUnitOfWork(
            harness.engine, audit=harness.audit, repository=_FailsAtCompletion
        ) as uow,
    ):
        APP.create_meeting(uow, mine.principal_id, request, "atomic", NOW)

    assert _meeting_rows_of(harness.engine, mine.principal_id) == dict.fromkeys(
        (table.name for table in MEETING_TABLES), 0
    )
    assert _document_rows(harness.engine, mine.document_id) == documents_before
    assert _count(harness.engine, entities) == entities_before
    # The rolled-back reservation is gone, so the same key now owns a fresh write.
    retried = harness.create(mine.principal_id, request, "atomic")
    assert retried.replayed is False


@pytest.mark.recovery
def test_a_failure_mid_update_rolls_back_every_row(harness: Harness, stage: Stage) -> None:
    """AC-031/AC-026/AC-019/AC-017: core, children, receipt and request roll back."""
    mine = stage.mine
    seed = harness.create(
        mine.principal_id,
        _create_request(
            attendees=(_person(mine.person_ids[0]),),
            attachment_document_ids=(mine.document_id,),
            notes_markdown="first",
        ),
        "seed",
    ).meeting
    before = _meeting_rows_of(harness.engine, mine.principal_id)
    attendees_before = _rows(harness.engine, meeting_attendees, meeting_id=seed.meeting_id)
    attachments_before = _rows(harness.engine, meeting_attachments, meeting_id=seed.meeting_id)
    request = MeetingUpdateRequest(
        meeting_id=seed.meeting_id,
        title="Renamed",
        attendees_replace=(_person(mine.person_ids[1]),),
        attachment_add_document_ids=(mine.archived_document_id,),
        attachment_remove_ids=(seed.attachments[0].attachment_id,),
        notes_mode=MeetingNotesMode.APPEND,
        notes_markdown="second",
    )

    with (
        pytest.raises(_InjectedError),
        _InjectingUnitOfWork(harness.engine, audit=harness.audit, repository=_FailsAtNote) as uow,
    ):
        APP.update_meeting(uow, mine.principal_id, request, 1, "atomic-update", LATER)

    assert _meeting_rows_of(harness.engine, mine.principal_id) == before
    assert _rows(harness.engine, meeting_attendees, meeting_id=seed.meeting_id) == (
        attendees_before
    )
    assert _rows(harness.engine, meeting_attachments, meeting_id=seed.meeting_id) == (
        attachments_before
    )
    assert harness.read(mine.principal_id, seed.meeting_id) == seed


def _wait_until_blocked[ResultT](engine: Engine, future: Future[ResultT]) -> None:
    """Return once another backend of this database waits on a lock."""
    deadline = time.monotonic() + BLOCK_DEADLINE_SECONDS
    with engine.connect() as observer:
        while time.monotonic() < deadline:
            assert not future.done(), "the second transaction did not wait for the first"
            waiting = observer.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                    "AND pid <> pg_backend_pid()"
                )
            ).scalar_one()
            observer.rollback()
            if waiting:
                return
            time.sleep(0.05)
    pytest.fail("the second transaction never blocked on the first")


def _race[FirstT, SecondT](
    harness: Harness,
    first: Callable[[UnitOfWork], FirstT],
    second: Callable[[], SecondT],
) -> tuple[FirstT, Future[SecondT]]:
    """Run `first` in an open unit of work, start `second`, commit once it waits."""
    holder = harness.uow()
    uow = holder.__enter__()
    committed = False
    try:
        result = first(uow)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(second)
            _wait_until_blocked(harness.engine, future)
            holder.__exit__(None, None, None)
            committed = True
            future.exception(timeout=JOIN_TIMEOUT_SECONDS)
    finally:
        if not committed:
            holder.__exit__(_InjectedError, _InjectedError(), None)
    return result, future


@pytest.mark.recovery
def test_two_concurrent_creates_with_one_key_make_one_meeting(
    harness: Harness, stage: Stage
) -> None:
    """AC-029/AC-041: the second waits on the reservation, then replays the winner."""
    principal = stage.mine.principal_id
    request = _create_request(series_title="Synthetic series")
    first, future = _race(
        harness,
        lambda uow: APP.create_meeting(uow, principal, request, "race", NOW),
        lambda: harness.create(principal, request, "race", now=LATER),
    )
    second = future.result()
    assert second.replayed is True
    assert second.meeting.meeting_id == first.meeting.meeting_id
    assert second.receipt == first.receipt
    assert second.series_receipt == first.series_receipt
    assert _count(harness.engine, meetings, principal_id=principal) == 1
    assert _count(harness.engine, meeting_series, principal_id=principal) == 1


@pytest.mark.recovery
def test_a_concurrent_create_with_a_different_request_conflicts(
    harness: Harness, stage: Stage
) -> None:
    """AC-029/AC-041: the loser reads the committed winner's digest and conflicts."""
    principal = stage.mine.principal_id
    _, future = _race(
        harness,
        lambda uow: APP.create_meeting(uow, principal, _create_request(), "race", NOW),
        lambda: harness.create(principal, _create_request(title="Other"), "race"),
    )
    with pytest.raises(MeetingIdempotencyConflictError):
        future.result()
    assert _count(harness.engine, meetings, principal_id=principal) == 1


@pytest.mark.recovery
def test_two_concurrent_updates_serialize_and_the_second_is_stale(
    harness: Harness, stage: Stage
) -> None:
    """AC-030/AC-043: the Meeting row lock orders writers; the loser sees a new version."""
    principal = stage.mine.principal_id
    seed = harness.create(
        principal, _create_request(attendees=(_person(stage.mine.person_ids[0]),)), "seed"
    ).meeting
    first, future = _race(
        harness,
        lambda uow: APP.update_meeting(
            uow,
            principal,
            MeetingUpdateRequest(meeting_id=seed.meeting_id, title="First"),
            1,
            "first",
            LATER,
        ),
        lambda: harness.update(
            principal, MeetingUpdateRequest(meeting_id=seed.meeting_id, title="Second"), 1, "second"
        ),
    )
    assert first.meeting.version == 2
    with pytest.raises(MeetingStaleVersionError):
        future.result()
    assert harness.read(principal, seed.meeting_id).title == "First"
    assert _count(harness.engine, meeting_history, meeting_id=seed.meeting_id) == 2


@pytest.mark.recovery
def test_a_series_retitle_serializes_on_the_series_row(harness: Harness, stage: Stage) -> None:
    """AC-030/AC-043: the MeetingSeries row lock orders series writers."""
    principal = stage.mine.principal_id
    series_id = harness.create(
        principal, _create_request(series_title="Series"), "seed"
    ).meeting.meeting_series_id
    assert series_id is not None
    _, future = _race(
        harness,
        lambda uow: APP.update_meeting_series(
            uow,
            principal,
            MeetingSeriesUpdateRequest(meeting_series_id=series_id, title="First"),
            1,
            "first",
            LATER,
        ),
        lambda: harness.update_series(
            principal,
            MeetingSeriesUpdateRequest(meeting_series_id=series_id, title="Second"),
            1,
            "second",
        ),
    )
    with pytest.raises(MeetingStaleVersionError):
        future.result()


# ------------------------------------------------ AC-043 lock footprint (R3-01)

#: PostgreSQL's `lock_not_available`, raised by a `NOWAIT` probe that would wait.
LOCK_NOT_AVAILABLE: Final = "55P03"


class _RecordingRepository(SqlMeetingRepository):
    """The production repository, logging each lock and reference read in call order.

    Each test gets its own subclass, and so its own `calls`, from
    `_recording_unit_of_work`; every override delegates unchanged, so the
    transaction takes exactly the production locks.
    """

    calls: ClassVar[list[tuple[str, tuple[str, ...]]]]

    def _log(self, name: str, *values: str) -> None:
        type(self).calls.append((name, values))

    def lock_meeting_for_update(self, principal_id: str, meeting_id: str) -> MeetingView | None:
        self._log("lock_meeting_for_update", meeting_id)
        return super().lock_meeting_for_update(principal_id, meeting_id)

    def project_is_owned(self, principal_id: str, project_id: str) -> bool:
        self._log("project_is_owned", project_id)
        return super().project_is_owned(principal_id, project_id)

    def owned_managed_documents(
        self, principal_id: str, document_ids: Collection[str]
    ) -> Mapping[str, DocumentState]:
        self._log("owned_managed_documents", *document_ids)
        return super().owned_managed_documents(principal_id, document_ids)

    def share_lock_person_entities(
        self, principal_id: str, entity_ids: Collection[str]
    ) -> tuple[MeetingEntityState, ...]:
        self._log("share_lock_person_entities", *entity_ids)
        return super().share_lock_person_entities(principal_id, entity_ids)

    def insert_meeting(self, principal_id: str, meeting: MeetingRecord) -> None:
        self._log("insert_meeting", meeting.meeting_id)
        super().insert_meeting(principal_id, meeting)

    def update_meeting(self, principal_id: str, meeting: MeetingRecord) -> None:
        self._log("update_meeting", meeting.meeting_id)
        super().update_meeting(principal_id, meeting)

    def insert_attendees(
        self,
        principal_id: str,
        meeting_id: str,
        attendees: Sequence[MeetingAttendeeRecord],
        *,
        added_at: datetime,
    ) -> None:
        self._log("insert_attendees", *(record.attendee.entity_id or "" for record in attendees))
        super().insert_attendees(principal_id, meeting_id, attendees, added_at=added_at)


def _recording_unit_of_work(
    harness: Harness,
) -> tuple[_InjectingUnitOfWork, list[tuple[str, tuple[str, ...]]]]:
    log: list[tuple[str, tuple[str, ...]]] = []

    class _Recorder(_RecordingRepository):
        calls = log

    return _InjectingUnitOfWork(harness.engine, audit=harness.audit, repository=_Recorder), log


def _row_lock_granted(
    engine: Engine, table: Table, column: str, value: str, mode: Literal["NO KEY UPDATE", "SHARE"]
) -> bool:
    """Whether a second connection can row-lock one committed row right now.

    `NOWAIT` answers at once. `FOR NO KEY UPDATE` conflicts with `FOR SHARE`
    and stronger, and not with the `FOR KEY SHARE` a foreign-key insert takes
    on its parent, so it separates an application share lock from the FK's
    own footprint; `FOR UPDATE` would conflict with both and prove nothing.
    """
    statement = text(
        f"SELECT 1 FROM {table.fullname} WHERE {column} = :value FOR {mode} NOWAIT"  # noqa: S608
    )
    with engine.connect() as probe:
        try:
            assert probe.execute(statement, {"value": value}).scalar_one() == 1
        except OperationalError as error:
            if getattr(error.orig, "sqlstate", None) != LOCK_NOT_AVAILABLE:
                raise
            return False
        finally:
            probe.rollback()
    return True


def _person_is_share_locked(engine: Engine, entity_id: str) -> bool:
    """Held FOR SHARE by another transaction: exclusive modes refused, SHARE granted."""
    exclusive = _row_lock_granted(engine, entities, "entity_id", entity_id, "NO KEY UPDATE")
    shared = _row_lock_granted(engine, entities, "entity_id", entity_id, "SHARE")
    return not exclusive and shared


def _plainly_readable(engine: Engine, table: Table, column: str, value: str) -> bool:
    """No application row lock: only the FK's KEY SHARE, if anything, is held."""
    return _row_lock_granted(engine, table, column, value, "NO KEY UPDATE")


@pytest.mark.recovery
def test_an_open_create_share_locks_its_people_and_no_other_reference(
    harness: Harness, stage: Stage
) -> None:
    """AC-043 (R3-01): Person Entities FOR SHARE, sorted; Project/document unlocked.

    Probed from a second connection while the create's transaction is still
    open, after every write has run and before commit.
    """
    mine = stage.mine
    first, second, bystander = mine.person_ids
    request = _create_request(
        project_id=mine.project_id,
        attachment_document_ids=(mine.document_id,),
        attendees=(_person(second), _person(first)),
    )
    engine = harness.engine
    unit, calls = _recording_unit_of_work(harness)
    with unit as uow:
        created = APP.create_meeting(uow, mine.principal_id, request, "footprint", NOW)

        assert _person_is_share_locked(engine, first)
        assert _person_is_share_locked(engine, second)
        assert _plainly_readable(engine, entities, "entity_id", bystander)
        assert _plainly_readable(engine, projects, "project_id", mine.project_id)
        assert _plainly_readable(engine, managed_documents, "document_id", mine.document_id)

    # Every lock was the create's own: the commit released it.
    assert _plainly_readable(engine, entities, "entity_id", first)
    assert _plainly_readable(engine, entities, "entity_id", second)
    # References, then one sorted share lock, then the parent, then its children.
    assert calls == [
        ("project_is_owned", (mine.project_id,)),
        ("owned_managed_documents", (mine.document_id,)),
        ("share_lock_person_entities", (first, second)),
        ("insert_meeting", (created.meeting.meeting_id,)),
        ("insert_attendees", (first, second)),
    ]


@pytest.mark.recovery
def test_an_open_update_share_locks_its_people_and_no_other_reference(
    harness: Harness, stage: Stage
) -> None:
    """AC-043 (R3-01): Meeting FOR UPDATE first, then sorted Person FOR SHARE only."""
    mine = stage.mine
    earlier, first, second = mine.person_ids
    seed = harness.create(
        mine.principal_id, _create_request(attendees=(_person(earlier),)), "seed"
    ).meeting
    request = MeetingUpdateRequest(
        meeting_id=seed.meeting_id,
        project_id=mine.project_id,
        attachment_add_document_ids=(mine.document_id,),
        attendees_replace=(_person(second), _person(first)),
    )
    engine = harness.engine
    unit, calls = _recording_unit_of_work(harness)
    with unit as uow:
        updated = APP.update_meeting(uow, mine.principal_id, request, 1, "footprint", LATER)
        assert updated.meeting.version == 2

        assert not _plainly_readable(engine, meetings, "meeting_id", seed.meeting_id)
        assert _person_is_share_locked(engine, first)
        assert _person_is_share_locked(engine, second)
        # The retired attendee's Entity is not re-validated, so it is not locked.
        assert _plainly_readable(engine, entities, "entity_id", earlier)
        assert _plainly_readable(engine, projects, "project_id", mine.project_id)
        assert _plainly_readable(engine, managed_documents, "document_id", mine.document_id)

    assert _plainly_readable(engine, meetings, "meeting_id", seed.meeting_id)
    assert _plainly_readable(engine, entities, "entity_id", first)
    assert _plainly_readable(engine, entities, "entity_id", second)
    # The parent lock precedes every reference read, lock and child write.
    assert calls == [
        ("lock_meeting_for_update", (seed.meeting_id,)),
        ("project_is_owned", (mine.project_id,)),
        ("owned_managed_documents", (mine.document_id,)),
        ("share_lock_person_entities", (first, second)),
        ("update_meeting", (seed.meeting_id,)),
        ("insert_attendees", (first, second)),
    ]
