"""WP-MTG-02: the Meeting records tables and `SqlMeetingRepository`, on a live server.

The `database` tier (routed to database-current-head), on a disposable
head-migrated clone. The Meeting tables exist in a migrated database only once
the WP-MTG-04 revision does, so this module is authored in WP-MTG-02 and first
executed in WP-MTG-04 (plan D-12); nothing here builds a schema of its own.

What is proved here is the persistence half of the Meeting acceptance criteria:
every declared table, constraint and index is on the server; the composite
same-Principal foreign keys refuse a cross-Principal reference; the partial
uniques admit exactly one active relation and let a retired one be re-added; note
lineage is a same-Meeting chain; the write-request invariants hold; reads are
partitioned so a foreign row answers as an absent one; list and search implement
the package section 34.15 contract; and the core, series-title and current-note
GIN indexes and the list btrees are eligible for their predicates.

Every identifier, title, name and address here is synthetic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, event, func, insert, inspect, literal_column, select, text
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import ClauseElement

from my_pa.contracts.ports import (
    MeetingAttachmentRecord,
    MeetingAttendeeRecord,
    MeetingNoteRecord,
    MeetingRecord,
    RepositoryFailureError,
)
from my_pa.contracts.v1.meetings import (
    MeetingHistoryView,
    MeetingSeriesHistoryView,
    MeetingSeriesView,
    MeetingView,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.documents.managed import DocumentState
from my_pa.domain.meeting.model import (
    MEETINGS_CREATE_NAME,
    MEETINGS_SERIES_UPDATE_NAME,
    MEETINGS_UPDATE_NAME,
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
    NormalizedAttendee,
    note_content_sha256,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.meetings import (
    SqlMeetingRepository,
    _core_document,
    _note_document,
    _series_document,
)
from my_pa.infrastructure.persistence.tables import (
    METADATA,
    SCHEMA,
    entities,
    managed_document_lifecycle_events,
    managed_document_versions,
    managed_documents,
    meeting_attendees,
    meeting_history,
    meeting_note_versions,
    meeting_series,
    meeting_write_requests,
    meetings,
    projects,
)

pytestmark = pytest.mark.database

T0: Final = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
NOW: Final = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
DIGEST: Final = "a" * 64
OTHER_DIGEST: Final = "b" * 64

MEETING_TABLES: Final = (
    "meeting_series",
    "meetings",
    "meeting_attendees",
    "meeting_attachments",
    "meeting_history",
    "meeting_note_versions",
    "meeting_series_history",
    "meeting_write_requests",
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
    values: dict[str, object] = {
        "entity_id": entity_id,
        "principal_id": principal_id,
        "entity_type": entity_type,
        "canonical_name": f"synthetic {entity_type}",
        "display_name": f"Synthetic {entity_type}",
        "status": status,
        "created_at": T0,
        "updated_at": T0,
        "version": 1,
    }
    if status == "archived":
        values["archived_from_status"] = "active"
    connection.execute(insert(entities).values(**values))
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


@pytest.fixture
def stage(db_engine: Engine) -> Stage:
    with db_engine.begin() as connection:
        return Stage(mine=_partition(connection), theirs=_partition(connection))


@pytest.fixture
def engine(db_engine: Engine) -> Iterator[Engine]:
    yield db_engine


def _repository(connection: Connection) -> SqlMeetingRepository:
    return SqlMeetingRepository(connection)


def _meeting(
    *,
    meeting_id: str | None = None,
    meeting_series_id: str | None = None,
    title: str = "Synthetic weekly sync",
    start_at: datetime = T0,
    end_at: datetime | None = None,
    status: MeetingStatus = MeetingStatus.SCHEDULED,
    cancelled_at: datetime | None = None,
    location_text: str | None = None,
    description: str | None = None,
    project_id: str | None = None,
    version: int = 1,
) -> MeetingRecord:
    return MeetingRecord(
        meeting_id=meeting_id or issue_identifier(IdKind.MEETING),
        meeting_series_id=meeting_series_id,
        title=title,
        start_at=start_at,
        end_at=end_at,
        timezone_name="America/New_York",
        status=status,
        cancelled_at=cancelled_at,
        location_text=location_text,
        virtual_meeting_url=None,
        description=description,
        project_id=project_id,
        version=version,
        created_at=T0,
        updated_at=T0,
    )


def _series(title: str = "Synthetic series") -> MeetingSeriesView:
    return MeetingSeriesView(
        meeting_series_id=issue_identifier(IdKind.MEETING_SERIES),
        title=title,
        version=1,
        created_at=T0,
        updated_at=T0,
    )


def _receipt(
    meeting_id: str,
    *,
    action: MeetingHistoryAction = MeetingHistoryAction.CREATE,
    outcome: MeetingOutcome = MeetingOutcome.APPLIED,
    before: int = 0,
    after: int = 1,
) -> MeetingHistoryView:
    return MeetingHistoryView(
        history_id=issue_identifier(IdKind.MEETING_HISTORY),
        meeting_id=meeting_id,
        action=action,
        actor=MeetingActor.PRINCIPAL,
        outcome=outcome,
        before_version=before,
        after_version=after,
        occurred_at=T0,
        recorded_at=T0,
    )


def _series_receipt(meeting_series_id: str) -> MeetingSeriesHistoryView:
    return MeetingSeriesHistoryView(
        series_history_id=issue_identifier(IdKind.MEETING_SERIES_HISTORY),
        meeting_series_id=meeting_series_id,
        action=MeetingHistoryAction.CREATE,
        actor=MeetingActor.PRINCIPAL,
        outcome=MeetingOutcome.APPLIED,
        before_version=0,
        after_version=1,
        occurred_at=T0,
        recorded_at=T0,
    )


def _attendee(
    *,
    entity_id: str | None = None,
    display_name: str | None = None,
    email: str | None = None,
    organizer: bool = False,
) -> MeetingAttendeeRecord:
    return MeetingAttendeeRecord(
        attendee_id=issue_identifier(IdKind.MEETING_ATTENDEE),
        attendee=NormalizedAttendee(
            display_name=display_name,
            email_normalized=email,
            entity_id=entity_id,
            is_organizer=organizer,
            response_status=AttendeeResponseStatus.UNKNOWN,
        ),
    )


def _note(
    meeting_id: str,
    history_id: str,
    body: str,
    *,
    version_number: int = 1,
    supersedes: str | None = None,
) -> MeetingNoteRecord:
    return MeetingNoteRecord(
        note_version_id=issue_identifier(IdKind.MEETING_NOTE_VERSION),
        meeting_id=meeting_id,
        version_number=version_number,
        supersedes_note_version_id=supersedes,
        content_markdown=body,
        content_sha256=note_content_sha256(body),
        meeting_history_id=history_id,
        recorded_at=T0,
    )


def _created(engine: Engine, principal_id: str, **overrides: object) -> MeetingRecord:
    """One committed Meeting with its create receipt."""
    record = _meeting(**overrides)  # type: ignore[arg-type]
    with engine.begin() as connection:
        repository = _repository(connection)
        repository.insert_meeting(principal_id, record)
        repository.insert_meeting_history(
            principal_id,
            _receipt(record.meeting_id),
            meeting_series_id=record.meeting_series_id,
            idempotency_key=f"create-{record.meeting_id}",
            request_digest=DIGEST,
        )
    return record


def _refused(engine: Engine, statement: Callable[[Connection], object]) -> str | None:
    """Run `statement` in its own transaction; it must be refused by the server.

    Returns the violated constraint's name, so each test names the one rule it
    exercises rather than accepting any refusal at all.
    """
    with pytest.raises(IntegrityError) as caught, engine.begin() as connection:
        statement(connection)
    diagnostic = getattr(caught.value.orig, "diag", None)
    name = getattr(diagnostic, "constraint_name", None)
    return None if name is None else str(name)


# ------------------------------------------------------------- schema at head


def test_every_meeting_table_is_on_the_server_with_its_declared_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    present = set(inspector.get_table_names(schema=SCHEMA))
    for name in MEETING_TABLES:
        assert name in present, name
        declared = {column.name for column in METADATA.tables[f"{SCHEMA}.{name}"].columns}
        stored = {column["name"] for column in inspector.get_columns(name, schema=SCHEMA)}
        assert stored == declared, name


def test_every_declared_meeting_index_is_on_the_server(engine: Engine) -> None:
    inspector = inspect(engine)
    for name in MEETING_TABLES:
        declared = {index.name for index in METADATA.tables[f"{SCHEMA}.{name}"].indexes}
        stored = {index["name"] for index in inspector.get_indexes(name, schema=SCHEMA)}
        assert declared <= stored, (name, declared - stored)


def test_no_meeting_table_has_a_binary_column(engine: Engine) -> None:
    """AC-016: attachments reuse ManagedDocument custody; no parallel byte store."""
    with engine.connect() as connection:
        binary = connection.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = :schema AND data_type = 'bytea' "
                "AND table_name = ANY(:tables)"
            ),
            {"schema": SCHEMA, "tables": list(MEETING_TABLES)},
        ).all()
    assert binary == []


def test_managed_documents_are_identified_within_their_owner(engine: Engine) -> None:
    uniques = inspect(engine).get_unique_constraints("managed_documents", schema=SCHEMA)
    assert {
        "name": "a_managed_document_is_identified_within_its_owner",
        "column_names": ["document_id", "owner_principal_id"],
    } in [{"name": u["name"], "column_names": u["column_names"]} for u in uniques]


#: The merged revision that creates `managed_documents`, and the owner-scoped
#: unique the Meeting revision (WP-MTG-04) adds to it.
MANAGED_DOCUMENT_REVISION: Final = "4c7b2e91d8a5"
OWNER_UNIQUE: Final = "a_managed_document_is_identified_within_its_owner"
ROOT: Final = Path(__file__).resolve().parents[2]


@pytest.mark.migration_edge
def test_the_owner_unique_is_absent_at_the_managed_document_revision(
    empty_database_url: str,
) -> None:
    """Review F-01 / D-48: the historical revision keeps meaning what it merged as.

    `4c7b2e91d8a5` copies the live `managed_documents` declaration, which now
    carries the Meeting target unique. Its freeze-out keeps that unique out of
    the revision, so a fresh database upgraded only to it has the PK and the two
    identifier CHECKs and nothing else; the Meeting revision adds the unique
    unconditionally, and WP-MTG-04 proves it present at head.
    """
    command.upgrade(Config(str(ROOT / "alembic.ini")), MANAGED_DOCUMENT_REVISION)
    engine = create_database_engine(empty_database_url)
    try:
        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            constraints = set(
                connection.execute(
                    text(
                        "SELECT c.conname FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "WHERE n.nspname = :schema AND t.relname = 'managed_documents'"
                    ),
                    {"schema": SCHEMA},
                ).scalars()
            )
            relation = connection.execute(
                text(
                    "SELECT count(*) FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :schema AND c.relname = :name"
                ),
                {"schema": SCHEMA, "name": OWNER_UNIQUE},
            ).scalar_one()
    finally:
        engine.dispose()
    assert version == MANAGED_DOCUMENT_REVISION
    assert "managed_documents_pkey" in constraints
    assert OWNER_UNIQUE not in constraints
    assert relation == 0


def test_there_is_no_duplicate_descending_meeting_btree(engine: Engine) -> None:
    """AC-038: the ascending `(principal_id, start_at, meeting_id)` btree serves reverse scans."""
    with engine.connect() as connection:
        definitions = connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE schemaname = :schema AND tablename = :t"),
            {"schema": SCHEMA, "t": "meetings"},
        ).scalars()
        assert not [d for d in definitions if "start_at DESC" in d]


# --------------------------------------------------------- table constraints


def test_a_meeting_series_title_must_be_nonblank_and_bounded(engine: Engine, stage: Stage) -> None:
    for title in ("   ", "x" * 201):
        assert (
            _refused(
                engine,
                lambda connection, title=title: connection.execute(
                    insert(meeting_series).values(
                        meeting_series_id=issue_identifier(IdKind.MEETING_SERIES),
                        principal_id=stage.mine.principal_id,
                        title=title,
                        created_at=T0,
                        updated_at=T0,
                    )
                ),
            )
            == "a_meeting_series_title_is_bounded"
        )


def test_a_meeting_cannot_end_before_it_starts(engine: Engine, stage: Stage) -> None:
    record = _meeting(end_at=T0 - timedelta(minutes=1))
    name = _refused(
        engine,
        lambda connection: _repository(connection).insert_meeting(stage.mine.principal_id, record),
    )
    assert name == "a_meeting_does_not_end_before_it_starts"
    # Zero duration is legal.
    _created(engine, stage.mine.principal_id, end_at=T0)


def test_cancellation_and_its_instant_are_paired(engine: Engine, stage: Stage) -> None:
    for record in (
        _meeting(status=MeetingStatus.CANCELLED, cancelled_at=None),
        _meeting(status=MeetingStatus.SCHEDULED, cancelled_at=T0),
    ):
        assert (
            _refused(
                engine,
                lambda connection, record=record: _repository(connection).insert_meeting(
                    stage.mine.principal_id, record
                ),
            )
            == "a_cancelled_meeting_records_when_it_was_cancelled"
        )


def test_a_meeting_cannot_name_another_principals_project(engine: Engine, stage: Stage) -> None:
    """AC-020/AC-032: the composite project FK refuses a foreign Project."""
    record = _meeting(project_id=stage.theirs.project_id)
    name = _refused(
        engine,
        lambda connection: _repository(connection).insert_meeting(stage.mine.principal_id, record),
    )
    assert name == "a_meeting_names_a_project_of_its_principal"
    # Its own Project is accepted in any state (the staged Project is closed).
    _created(engine, stage.mine.principal_id, project_id=stage.mine.project_id)


def test_a_meeting_cannot_join_another_principals_series(engine: Engine, stage: Stage) -> None:
    series = _series()
    with engine.begin() as connection:
        _repository(connection).insert_series(stage.theirs.principal_id, series)
    record = _meeting(meeting_series_id=series.meeting_series_id)
    name = _refused(
        engine,
        lambda connection: _repository(connection).insert_meeting(stage.mine.principal_id, record),
    )
    assert name == "a_meeting_belongs_to_a_series_of_its_principal"


def test_an_attendee_cannot_name_another_principals_entity(engine: Engine, stage: Stage) -> None:
    meeting = _created(engine, stage.mine.principal_id)
    name = _refused(
        engine,
        lambda connection: _repository(connection).insert_attendees(
            stage.mine.principal_id,
            meeting.meeting_id,
            [_attendee(entity_id=stage.theirs.person_ids[0])],
            added_at=T0,
        ),
    )
    assert name == "a_meeting_attendee_names_an_entity_of_its_principal"


def test_an_attendee_carries_at_least_one_identity_signal(engine: Engine, stage: Stage) -> None:
    meeting = _created(engine, stage.mine.principal_id)
    name = _refused(
        engine,
        lambda connection: connection.execute(
            insert(meeting_attendees).values(
                attendee_id=issue_identifier(IdKind.MEETING_ATTENDEE),
                principal_id=stage.mine.principal_id,
                meeting_id=meeting.meeting_id,
                added_at=T0,
            )
        ),
    )
    assert name == "a_meeting_attendee_carries_an_identity_signal"


def test_an_attendee_response_status_is_closed(engine: Engine, stage: Stage) -> None:
    meeting = _created(engine, stage.mine.principal_id)
    name = _refused(
        engine,
        lambda connection: connection.execute(
            insert(meeting_attendees).values(
                attendee_id=issue_identifier(IdKind.MEETING_ATTENDEE),
                principal_id=stage.mine.principal_id,
                meeting_id=meeting.meeting_id,
                display_name="Synthetic Person",
                response_status="maybe",
                added_at=T0,
            )
        ),
    )
    assert name == "a_meeting_attendee_response_status_is_known"


@pytest.mark.parametrize(
    ("first", "second", "index"),
    [
        (
            {"entity": 0},
            {"entity": 0, "display_name": "Other label"},
            "meeting_attendees_one_active_entity",
        ),
        (
            {"email": "person@example.test"},
            {"email": "person@example.test", "display_name": "Another"},
            "meeting_attendees_one_active_email",
        ),
        (
            {"display_name": "Organizer One", "organizer": True},
            {"display_name": "Organizer Two", "organizer": True},
            "meeting_attendees_one_active_organizer",
        ),
    ],
)
def test_an_active_attendee_identity_is_unique_and_a_retired_one_may_return(
    engine: Engine, stage: Stage, first: dict[str, Any], second: dict[str, Any], index: str
) -> None:
    """AC-012/AC-013: partial uniques on the active set; retirement frees the slot."""

    def build(spec: dict[str, Any]) -> MeetingAttendeeRecord:
        entity = spec.get("entity")
        return _attendee(
            entity_id=None if entity is None else stage.mine.person_ids[entity],
            display_name=spec.get("display_name"),
            email=spec.get("email"),
            organizer=bool(spec.get("organizer", False)),
        )

    meeting = _created(engine, stage.mine.principal_id)
    original = build(first)
    with engine.begin() as connection:
        _repository(connection).insert_attendees(
            stage.mine.principal_id, meeting.meeting_id, [original], added_at=T0
        )
    name = _refused(
        engine,
        lambda connection: _repository(connection).insert_attendees(
            stage.mine.principal_id, meeting.meeting_id, [build(second)], added_at=T0
        ),
    )
    assert name == index

    later = T0 + timedelta(hours=1)
    with engine.begin() as connection:
        repository = _repository(connection)
        retired = repository.retire_attendees(
            stage.mine.principal_id, meeting.meeting_id, [original.attendee_id], removed_at=later
        )
        assert retired == 1
        repository.insert_attendees(
            stage.mine.principal_id, meeting.meeting_id, [build(second)], added_at=later
        )
    with engine.connect() as connection:
        view = _repository(connection).read_meeting(stage.mine.principal_id, meeting.meeting_id)
    assert view is not None
    assert [attendee.attendee_id for attendee in view.attendees] != [original.attendee_id]
    assert len(view.attendees) == 1


def test_a_shared_display_name_alone_is_not_an_identity(engine: Engine, stage: Stage) -> None:
    """AC-012: two distinct people may share a name."""
    meeting = _created(engine, stage.mine.principal_id)
    with engine.begin() as connection:
        _repository(connection).insert_attendees(
            stage.mine.principal_id,
            meeting.meeting_id,
            [_attendee(display_name="Sam Synthetic"), _attendee(display_name="Sam Synthetic")],
            added_at=T0,
        )
    with engine.connect() as connection:
        view = _repository(connection).read_meeting(stage.mine.principal_id, meeting.meeting_id)
    assert view is not None
    assert len(view.attendees) == 2


def test_an_attachment_cannot_name_another_principals_document(
    engine: Engine, stage: Stage
) -> None:
    """AC-016/AC-042: the composite managed-document FK refuses a foreign document."""
    meeting = _created(engine, stage.mine.principal_id)
    name = _refused(
        engine,
        lambda connection: _repository(connection).insert_attachments(
            stage.mine.principal_id,
            meeting.meeting_id,
            [
                MeetingAttachmentRecord(
                    issue_identifier(IdKind.MEETING_ATTACHMENT), stage.theirs.document_id
                )
            ],
            added_at=T0,
        ),
    )
    assert name == "a_meeting_attachment_names_a_document_of_its_principal"


def test_an_active_attachment_is_unique_and_detaching_never_touches_the_document(
    engine: Engine, stage: Stage
) -> None:
    """AC-016/AC-017: one active relation per document; detach retires only the relation."""
    meeting = _created(engine, stage.mine.principal_id)
    first = MeetingAttachmentRecord(
        issue_identifier(IdKind.MEETING_ATTACHMENT), stage.mine.document_id
    )
    with engine.begin() as connection:
        _repository(connection).insert_attachments(
            stage.mine.principal_id, meeting.meeting_id, [first], added_at=T0
        )
    name = _refused(
        engine,
        lambda connection: _repository(connection).insert_attachments(
            stage.mine.principal_id,
            meeting.meeting_id,
            [
                MeetingAttachmentRecord(
                    issue_identifier(IdKind.MEETING_ATTACHMENT), stage.mine.document_id
                )
            ],
            added_at=T0,
        ),
    )
    assert name == "meeting_attachments_one_active_document"

    def document_rows(connection: Connection) -> tuple[object, ...]:
        return (
            tuple(
                connection.execute(
                    select(managed_documents).where(
                        managed_documents.c.document_id == stage.mine.document_id
                    )
                ).all()
            ),
            tuple(
                connection.execute(
                    select(managed_document_versions).where(
                        managed_document_versions.c.document_id == stage.mine.document_id
                    )
                ).all()
            ),
            tuple(
                connection.execute(
                    select(managed_document_lifecycle_events).where(
                        managed_document_lifecycle_events.c.document_id == stage.mine.document_id
                    )
                ).all()
            ),
        )

    with engine.connect() as connection:
        before = document_rows(connection)
    later = T0 + timedelta(hours=1)
    with engine.begin() as connection:
        repository = _repository(connection)
        assert (
            repository.retire_attachments(
                stage.mine.principal_id, meeting.meeting_id, [first.attachment_id], removed_at=later
            )
            == 1
        )
        # Retiring an already-retired relation retires nothing.
        assert (
            repository.retire_attachments(
                stage.mine.principal_id, meeting.meeting_id, [first.attachment_id], removed_at=later
            )
            == 0
        )
        repository.insert_attachments(
            stage.mine.principal_id,
            meeting.meeting_id,
            [
                MeetingAttachmentRecord(
                    issue_identifier(IdKind.MEETING_ATTACHMENT), stage.mine.document_id
                )
            ],
            added_at=later,
        )
    with engine.connect() as connection:
        assert document_rows(connection) == before


def test_an_archived_document_remains_attachable_and_projects_as_archived(
    engine: Engine, stage: Stage
) -> None:
    meeting = _created(engine, stage.mine.principal_id)
    with engine.begin() as connection:
        repository = _repository(connection)
        repository.insert_attachments(
            stage.mine.principal_id,
            meeting.meeting_id,
            [
                MeetingAttachmentRecord(
                    issue_identifier(IdKind.MEETING_ATTACHMENT), stage.mine.document_id
                ),
                MeetingAttachmentRecord(
                    issue_identifier(IdKind.MEETING_ATTACHMENT), stage.mine.archived_document_id
                ),
            ],
            added_at=T0,
        )
        states = repository.owned_managed_documents(
            stage.mine.principal_id,
            [stage.mine.document_id, stage.mine.archived_document_id, stage.theirs.document_id],
        )
    assert states == {
        stage.mine.document_id: DocumentState.ACTIVE,
        stage.mine.archived_document_id: DocumentState.ARCHIVED,
    }
    with engine.connect() as connection:
        view = _repository(connection).read_meeting(stage.mine.principal_id, meeting.meeting_id)
    assert view is not None
    projected = {a.document_id: a for a in view.attachments}
    assert projected[stage.mine.document_id].availability is MeetingAttachmentAvailability.ACTIVE
    assert (
        projected[stage.mine.archived_document_id].availability
        is MeetingAttachmentAvailability.ARCHIVED
    )
    assert projected[stage.mine.document_id].title == "Synthetic agenda"
    assert projected[stage.mine.document_id].media_type == "text/markdown"


# ------------------------------------------------------------ note lineage


def test_note_versions_form_one_same_meeting_chain(engine: Engine, stage: Stage) -> None:
    """AC-018/AC-042: composite predecessor and receipt linkage; a durable head."""
    principal = stage.mine.principal_id
    meeting = _created(engine, principal)
    other = _created(engine, principal)
    first_receipt = _receipt(meeting.meeting_id)
    second_receipt = _receipt(
        meeting.meeting_id, action=MeetingHistoryAction.UPDATE, before=1, after=2
    )
    other_receipt = _receipt(other.meeting_id)
    with engine.begin() as connection:
        repository = _repository(connection)
        for receipt, _target in (
            (first_receipt, meeting),
            (second_receipt, meeting),
            (other_receipt, other),
        ):
            repository.insert_meeting_history(
                principal,
                receipt,
                meeting_series_id=None,
                idempotency_key=f"k-{receipt.history_id}",
                request_digest=DIGEST,
            )
    first = _note(meeting.meeting_id, first_receipt.history_id, "First body")
    other_first = _note(other.meeting_id, other_receipt.history_id, "Other body")
    with engine.begin() as connection:
        _repository(connection).insert_note_version(principal, first)
        _repository(connection).insert_note_version(principal, other_first)

    # A second version must supersede; a first version must not.
    assert (
        _refused(
            engine,
            lambda c: _repository(c).insert_note_version(
                principal,
                _note(meeting.meeting_id, second_receipt.history_id, "x", version_number=2),
            ),
        )
        == "only_the_first_meeting_note_supersedes_nothing"
    )
    # A predecessor of another Meeting is refused by the composite self-FK.
    assert (
        _refused(
            engine,
            lambda c: _repository(c).insert_note_version(
                principal,
                _note(
                    meeting.meeting_id,
                    second_receipt.history_id,
                    "x",
                    version_number=2,
                    supersedes=other_first.note_version_id,
                ),
            ),
        )
        == "a_meeting_note_supersedes_a_note_of_its_meeting"
    )
    # A receipt of another Meeting is refused by the composite history FK.
    assert (
        _refused(
            engine,
            lambda c: _repository(c).insert_note_version(
                principal,
                _note(
                    meeting.meeting_id,
                    other_receipt.history_id,
                    "x",
                    version_number=2,
                    supersedes=first.note_version_id,
                ),
            ),
        )
        == "a_meeting_note_names_a_receipt_of_its_meeting"
    )
    second = _note(
        meeting.meeting_id,
        second_receipt.history_id,
        "Second body",
        version_number=2,
        supersedes=first.note_version_id,
    )
    with engine.begin() as connection:
        _repository(connection).insert_note_version(principal, second)
    # The chain is a line: a second successor of the same predecessor is refused.
    assert (
        _refused(
            engine,
            lambda c: _repository(c).insert_note_version(
                principal,
                _note(
                    meeting.meeting_id,
                    second_receipt.history_id,
                    "fork",
                    version_number=3,
                    supersedes=first.note_version_id,
                ),
            ),
        )
        == "a_meeting_note_version_is_superseded_once"
    )
    with engine.connect() as connection:
        head = _repository(connection).current_note(principal, meeting.meeting_id)
        foreign = _repository(connection).current_note(
            stage.theirs.principal_id, meeting.meeting_id
        )
    assert head is not None
    assert (head.note_version_id, head.version_number, head.body_markdown) == (
        second.note_version_id,
        2,
        "Second body",
    )
    assert foreign is None


def test_a_note_digest_must_be_lowercase_sha256(engine: Engine, stage: Stage) -> None:
    principal = stage.mine.principal_id
    meeting = _created(engine, principal)
    receipt = _receipt(meeting.meeting_id)
    with engine.begin() as connection:
        _repository(connection).insert_meeting_history(
            principal, receipt, meeting_series_id=None, idempotency_key="k", request_digest=DIGEST
        )
    name = _refused(
        engine,
        lambda c: c.execute(
            insert(meeting_note_versions).values(
                note_version_id=issue_identifier(IdKind.MEETING_NOTE_VERSION),
                principal_id=principal,
                meeting_id=meeting.meeting_id,
                version_number=1,
                content_markdown="Body",
                content_sha256="A" * 64,
                meeting_history_id=receipt.history_id,
                recorded_at=T0,
            )
        ),
    )
    assert name == "a_meeting_note_digest_is_sha256"


# ----------------------------------------------------------------- receipts


@pytest.mark.parametrize(
    ("action", "outcome", "before", "after", "constraint"),
    [
        ("create", "applied", 0, 2, "a_meeting_history_create_is_version_zero_to_one"),
        ("create", "no_op", 0, 1, "a_meeting_history_create_is_version_zero_to_one"),
        ("update", "applied", 1, 3, "a_meeting_history_applied_update_advances_one_version"),
        ("update", "no_op", 2, 3, "a_meeting_history_no_op_changes_no_version"),
    ],
)
def test_a_meeting_receipt_records_a_legal_version_transition(
    engine: Engine,
    stage: Stage,
    action: str,
    outcome: str,
    before: int,
    after: int,
    constraint: str,
) -> None:
    meeting = _created(engine, stage.mine.principal_id)
    name = _refused(
        engine,
        lambda c: c.execute(
            insert(meeting_history).values(
                history_id=issue_identifier(IdKind.MEETING_HISTORY),
                principal_id=stage.mine.principal_id,
                meeting_id=meeting.meeting_id,
                action=action,
                actor="principal",
                outcome=outcome,
                before_version=before,
                after_version=after,
                idempotency_key="key",
                request_digest=DIGEST,
                occurred_at=T0,
                recorded_at=T0,
            )
        ),
    )
    assert name == constraint


@pytest.mark.parametrize("key", ["k", "k" * 128])
def test_a_one_to_128_character_key_is_a_legal_audit_key(
    engine: Engine, stage: Stage, key: str
) -> None:
    """D-16: every Meeting key CHECK is 1..128, so a short valid key is not an internal error."""
    principal = stage.mine.principal_id
    meeting = _created(engine, principal)
    series = _series()
    with engine.begin() as connection:
        repository = _repository(connection)
        repository.insert_meeting_history(
            principal,
            _receipt(meeting.meeting_id, action=MeetingHistoryAction.UPDATE, before=1, after=2),
            meeting_series_id=None,
            idempotency_key=key,
            request_digest=DIGEST,
        )
        repository.insert_series(principal, series)
        repository.insert_series_history(
            principal,
            _series_receipt(series.meeting_series_id),
            idempotency_key=key,
            request_digest=DIGEST,
        )
        assert (
            repository.reserve_write_request(
                principal, MEETINGS_UPDATE_NAME, key, DIGEST, created_at=T0
            )
            is None
        )


@pytest.mark.parametrize(
    ("table", "constraint"),
    [
        ("meeting_history", "a_meeting_history_key_is_bounded"),
        ("meeting_series_history", "a_meeting_series_history_key_is_bounded"),
        ("meeting_write_requests", "a_meeting_write_request_key_is_bounded"),
    ],
)
@pytest.mark.parametrize("key", ["", "k" * 129])
def test_an_empty_or_overlong_key_is_refused(
    engine: Engine, stage: Stage, table: str, constraint: str, key: str
) -> None:
    principal = stage.mine.principal_id
    meeting = _created(engine, principal)
    series = _series()
    with engine.begin() as connection:
        _repository(connection).insert_series(principal, series)

    def write(connection: Connection) -> None:
        repository = _repository(connection)
        if table == "meeting_history":
            repository.insert_meeting_history(
                principal,
                _receipt(meeting.meeting_id, action=MeetingHistoryAction.UPDATE, before=1, after=2),
                meeting_series_id=None,
                idempotency_key=key,
                request_digest=DIGEST,
            )
        elif table == "meeting_series_history":
            repository.insert_series_history(
                principal,
                _series_receipt(series.meeting_series_id),
                idempotency_key=key,
                request_digest=DIGEST,
            )
        else:
            repository.reserve_write_request(
                principal, MEETINGS_CREATE_NAME, key, DIGEST, created_at=T0
            )

    assert _refused(engine, write) == constraint


# ------------------------------------------------------------ write requests


def _raw_request(principal_id: str, **values: object) -> dict[str, object]:
    base: dict[str, object] = {
        "principal_id": principal_id,
        "capability": MEETINGS_CREATE_NAME,
        "idempotency_key": issue_identifier(IdKind.CORRELATION),
        "request_digest": DIGEST,
        "created_at": T0,
    }
    base.update(values)
    return base


def test_the_write_request_invariants_hold_structurally(engine: Engine, stage: Stage) -> None:
    """AC-041: the section 35.7 incomplete/completed invariants and the capability set."""
    principal = stage.mine.principal_id
    meeting = _created(engine, principal)
    receipt = _receipt(meeting.meeting_id, action=MeetingHistoryAction.UPDATE, before=1, after=2)
    series = _series()
    series_receipt = _series_receipt(series.meeting_series_id)
    with engine.begin() as connection:
        repository = _repository(connection)
        repository.insert_meeting_history(
            principal, receipt, meeting_series_id=None, idempotency_key="k", request_digest=DIGEST
        )
        repository.insert_series(principal, series)
        repository.insert_series_history(
            principal, series_receipt, idempotency_key="k", request_digest=DIGEST
        )
    cases: list[tuple[dict[str, object], str]] = [
        (
            _raw_request(principal, capability="meetings.delete"),
            "a_meeting_write_request_capability_is_known",
        ),
        (
            _raw_request(principal, request_digest="A" * 64),
            "a_meeting_write_request_digest_is_sha256",
        ),
        (
            _raw_request(principal, meeting_id=meeting.meeting_id),
            "an_incomplete_meeting_write_request_names_no_result",
        ),
        (
            _raw_request(
                principal, completed_at=T0, meeting_id=meeting.meeting_id, result_version=1
            ),
            "a_completed_meeting_create_names_its_result",
        ),
        (
            _raw_request(
                principal,
                capability=MEETINGS_UPDATE_NAME,
                completed_at=T0,
                meeting_id=meeting.meeting_id,
                meeting_history_id=receipt.history_id,
                meeting_series_id=series.meeting_series_id,
                meeting_series_history_id=series_receipt.series_history_id,
                result_version=2,
            ),
            "a_completed_meeting_update_names_its_result",
        ),
        (
            _raw_request(
                principal,
                capability=MEETINGS_SERIES_UPDATE_NAME,
                completed_at=T0,
                meeting_id=meeting.meeting_id,
                meeting_series_id=series.meeting_series_id,
                meeting_series_history_id=series_receipt.series_history_id,
                result_version=1,
            ),
            "a_completed_meeting_series_update_names_its_result",
        ),
        (
            _raw_request(
                principal,
                capability=MEETINGS_SERIES_UPDATE_NAME,
                completed_at=T0,
                meeting_series_id=series.meeting_series_id,
                meeting_series_history_id=series_receipt.series_history_id,
                result_version=0,
            ),
            "a_meeting_write_request_result_version_is_positive",
        ),
    ]
    for values, constraint in cases:
        assert (
            _refused(
                engine,
                lambda c, values=values: c.execute(insert(meeting_write_requests).values(**values)),
            )
            == constraint
        )


def test_the_write_request_result_references_are_same_principal(
    engine: Engine, stage: Stage
) -> None:
    """AC-041/AC-032: all four composite result FKs refuse a foreign or mismatched target."""
    mine = stage.mine.principal_id
    theirs = stage.theirs.principal_id
    my_meeting = _created(engine, mine)
    my_other_meeting = _created(engine, mine)
    their_meeting = _created(engine, theirs)
    my_receipt = _receipt(
        my_meeting.meeting_id, action=MeetingHistoryAction.UPDATE, before=1, after=2
    )
    their_series = _series()
    their_series_receipt = _series_receipt(their_series.meeting_series_id)
    with engine.begin() as connection:
        repository = _repository(connection)
        repository.insert_meeting_history(
            mine, my_receipt, meeting_series_id=None, idempotency_key="k", request_digest=DIGEST
        )
        repository.insert_series(theirs, their_series)
        repository.insert_series_history(
            theirs, their_series_receipt, idempotency_key="k", request_digest=DIGEST
        )
    completed_update = {
        "capability": MEETINGS_UPDATE_NAME,
        "completed_at": T0,
        "result_version": 2,
    }
    # A foreign target fails both composites that include it; PostgreSQL reports
    # whichever referential trigger fires first, so each case names the set.
    cases: list[tuple[dict[str, object], set[str]]] = [
        (
            _raw_request(
                mine,
                **completed_update,
                meeting_id=their_meeting.meeting_id,
                meeting_history_id=my_receipt.history_id,
            ),
            {
                "a_meeting_write_request_names_a_meeting_of_its_principal",
                "a_meeting_write_request_names_a_receipt_of_its_meeting",
            },
        ),
        (
            _raw_request(
                mine,
                **completed_update,
                meeting_id=my_other_meeting.meeting_id,
                meeting_history_id=my_receipt.history_id,
            ),
            {"a_meeting_write_request_names_a_receipt_of_its_meeting"},
        ),
        (
            _raw_request(
                mine,
                capability=MEETINGS_SERIES_UPDATE_NAME,
                completed_at=T0,
                result_version=1,
                meeting_series_id=their_series.meeting_series_id,
                meeting_series_history_id=their_series_receipt.series_history_id,
            ),
            {
                "a_meeting_write_request_names_a_series_of_its_principal",
                "a_meeting_write_request_names_a_receipt_of_its_series",
            },
        ),
    ]
    for values, constraints in cases:
        assert (
            _refused(
                engine,
                lambda c, values=values: c.execute(insert(meeting_write_requests).values(**values)),
            )
            in constraints
        )


def test_reserve_complete_and_replay_through_the_repository(engine: Engine, stage: Stage) -> None:
    """AC-029/AC-041: first use owns; the same digest replays; a different digest conflicts."""
    principal = stage.mine.principal_id
    key = "create-key-1"
    series = _series()
    record = _meeting(meeting_series_id=series.meeting_series_id)
    receipt = _receipt(record.meeting_id)
    series_receipt = _series_receipt(series.meeting_series_id)
    with engine.begin() as connection:
        repository = _repository(connection)
        assert (
            repository.reserve_write_request(
                principal, MEETINGS_CREATE_NAME, key, DIGEST, created_at=T0
            )
            is None
        )
        incomplete = repository.read_write_request(principal, MEETINGS_CREATE_NAME, key)
        assert incomplete is not None
        assert incomplete.completed_at is None
        assert incomplete.meeting_receipt is None
        repository.insert_series(principal, series)
        repository.insert_series_history(
            principal, series_receipt, idempotency_key=key, request_digest=DIGEST
        )
        repository.insert_meeting(principal, record)
        repository.insert_meeting_history(
            principal,
            receipt,
            meeting_series_id=series.meeting_series_id,
            idempotency_key=key,
            request_digest=DIGEST,
        )
        repository.complete_write_request(
            principal,
            MEETINGS_CREATE_NAME,
            key,
            request_digest=DIGEST,
            meeting_id=record.meeting_id,
            meeting_series_id=series.meeting_series_id,
            meeting_history_id=receipt.history_id,
            meeting_series_history_id=series_receipt.series_history_id,
            result_version=1,
            completed_at=T0,
        )

    with engine.begin() as connection:
        replay = _repository(connection).reserve_write_request(
            principal, MEETINGS_CREATE_NAME, key, DIGEST, created_at=NOW
        )
    assert replay is not None
    assert replay.completed_at is not None
    assert replay.meeting_receipt == receipt
    assert replay.series_receipt == series_receipt
    assert (replay.meeting_id, replay.meeting_series_id, replay.result_version) == (
        record.meeting_id,
        series.meeting_series_id,
        1,
    )

    with pytest.raises(MeetingIdempotencyConflictError), engine.begin() as connection:
        _repository(connection).reserve_write_request(
            principal, MEETINGS_CREATE_NAME, key, OTHER_DIGEST, created_at=NOW
        )

    # The key is scoped by capability and Principal.
    with engine.begin() as connection:
        repository = _repository(connection)
        assert (
            repository.reserve_write_request(
                principal, MEETINGS_UPDATE_NAME, key, DIGEST, created_at=NOW
            )
            is None
        )
        assert (
            repository.reserve_write_request(
                stage.theirs.principal_id, MEETINGS_CREATE_NAME, key, DIGEST, created_at=NOW
            )
            is None
        )


def test_a_completed_request_cannot_be_completed_again(engine: Engine, stage: Stage) -> None:
    principal = stage.mine.principal_id
    meeting = _created(engine, principal)
    receipt = _receipt(meeting.meeting_id, action=MeetingHistoryAction.UPDATE, before=1, after=2)

    def complete(repository: SqlMeetingRepository) -> None:
        repository.complete_write_request(
            principal,
            MEETINGS_UPDATE_NAME,
            "update-key",
            request_digest=DIGEST,
            meeting_id=meeting.meeting_id,
            meeting_series_id=None,
            meeting_history_id=receipt.history_id,
            meeting_series_history_id=None,
            result_version=2,
            completed_at=T0,
        )

    with engine.begin() as connection:
        repository = _repository(connection)
        repository.reserve_write_request(
            principal, MEETINGS_UPDATE_NAME, "update-key", DIGEST, created_at=T0
        )
        repository.insert_meeting_history(
            principal,
            receipt,
            meeting_series_id=None,
            idempotency_key="update-key",
            request_digest=DIGEST,
        )
        complete(repository)
    with pytest.raises(RepositoryFailureError), engine.begin() as connection:
        complete(_repository(connection))


def test_an_incomplete_request_left_by_an_ended_owner_is_never_stolen(
    engine: Engine, stage: Stage
) -> None:
    """Section 35.7: same digest, still incomplete after its owner ended -> internal error."""
    principal = stage.mine.principal_id
    with engine.begin() as connection:
        connection.execute(
            insert(meeting_write_requests).values(
                **_raw_request(principal, idempotency_key="orphan")
            )
        )
    with pytest.raises(RepositoryFailureError), engine.begin() as connection:
        _repository(connection).reserve_write_request(
            principal, MEETINGS_CREATE_NAME, "orphan", DIGEST, created_at=NOW
        )
    with pytest.raises(MeetingIdempotencyConflictError), engine.begin() as connection:
        _repository(connection).reserve_write_request(
            principal, MEETINGS_CREATE_NAME, "orphan", OTHER_DIGEST, created_at=NOW
        )


# ------------------------------------------------------------ partitioned reads


def test_a_foreign_row_answers_exactly_as_an_absent_one(engine: Engine, stage: Stage) -> None:
    """AC-032: every read and lock is constrained to the calling Principal."""
    mine = stage.mine
    theirs = stage.theirs
    series = _series()
    with engine.begin() as connection:
        _repository(connection).insert_series(mine.principal_id, series)
    meeting = _created(engine, mine.principal_id, meeting_series_id=series.meeting_series_id)
    absent_meeting = issue_identifier(IdKind.MEETING)
    with engine.begin() as connection:
        repository = _repository(connection)
        for principal, meeting_id in (
            (theirs.principal_id, meeting.meeting_id),
            (mine.principal_id, absent_meeting),
        ):
            assert repository.read_meeting(principal, meeting_id) is None
            assert repository.lock_meeting_for_update(principal, meeting_id) is None
            assert repository.current_note(principal, meeting_id) is None
        assert repository.read_owned_series(theirs.principal_id, series.meeting_series_id) is None
        assert (
            repository.lock_series_for_update(theirs.principal_id, series.meeting_series_id) is None
        )
        assert repository.project_is_owned(theirs.principal_id, mine.project_id) is False
        assert repository.project_is_owned(mine.principal_id, mine.project_id) is True
        assert repository.owned_managed_documents(theirs.principal_id, [mine.document_id]) == {}
        assert repository.share_lock_person_entities(theirs.principal_id, mine.person_ids) == ()
        assert (
            repository.retire_attendees(
                theirs.principal_id, meeting.meeting_id, ["matt_aaaaaaaa1111"], removed_at=NOW
            )
            == 0
        )
        assert (
            repository.read_write_request(
                theirs.principal_id, MEETINGS_CREATE_NAME, f"create-{meeting.meeting_id}"
            )
            is None
        )
        with pytest.raises(RepositoryFailureError):
            repository.update_meeting(theirs.principal_id, meeting)
        with pytest.raises(RepositoryFailureError):
            repository.update_series_title(
                theirs.principal_id, series.meeting_series_id, title="x", version=2, updated_at=NOW
            )


def test_share_locked_entities_answer_ascending_with_type_and_status(
    engine: Engine, stage: Stage
) -> None:
    mine = stage.mine
    wanted = [mine.person_ids[2], mine.organization_id, mine.inactive_person_id, mine.person_ids[0]]
    with engine.begin() as connection:
        found = _repository(connection).share_lock_person_entities(mine.principal_id, wanted)
        assert _repository(connection).share_lock_person_entities(mine.principal_id, []) == ()
    assert [state.entity_id for state in found] == sorted(wanted)
    by_id = {state.entity_id: state for state in found}
    assert (by_id[mine.organization_id].entity_type, by_id[mine.organization_id].status) == (
        "organization",
        "active",
    )
    assert (by_id[mine.inactive_person_id].entity_type, by_id[mine.inactive_person_id].status) == (
        "person",
        "inactive",
    )


def test_an_update_rewrites_scalars_and_the_series_but_never_creation(
    engine: Engine, stage: Stage
) -> None:
    """Series membership is reassignable (operator decision 2026-10-09, retiring
    AC-007): the UPDATE writes `meeting_series_id`, never `created_at`, and
    neither the old nor the new series row is touched."""
    principal = stage.mine.principal_id
    series = _series("Canonical series title")
    target = _series("Target series title")
    with engine.begin() as connection:
        _repository(connection).insert_series(principal, series)
        _repository(connection).insert_series(principal, target)
    meeting = _created(engine, principal, meeting_series_id=series.meeting_series_id)

    def rewrite(version: int, meeting_series_id: str | None) -> MeetingView:
        changed = MeetingRecord(
            **{
                **{field: getattr(meeting, field) for field in MeetingRecord.__dataclass_fields__},
                "meeting_series_id": meeting_series_id,
                "created_at": NOW,
                "title": "Renamed occurrence",
                "status": MeetingStatus.CANCELLED,
                "cancelled_at": NOW,
                "version": version + 1,
                "updated_at": NOW,
            }
        )
        with engine.begin() as connection:
            repository = _repository(connection)
            locked = repository.lock_meeting_for_update(principal, meeting.meeting_id)
            assert locked is not None
            assert locked.version == version
            repository.update_meeting(principal, changed)
        with engine.connect() as connection:
            view = _repository(connection).read_meeting(principal, meeting.meeting_id)
        assert view is not None
        return view

    moved = rewrite(1, target.meeting_series_id)
    assert moved.meeting_series_id == target.meeting_series_id
    assert moved.series_title == "Target series title"
    assert moved.created_at == T0
    assert (moved.title, moved.status, moved.version) == (
        "Renamed occurrence",
        MeetingStatus.CANCELLED,
        2,
    )
    detached = rewrite(2, None)
    assert detached.meeting_series_id is None
    assert detached.series_title is None
    assert detached.created_at == T0
    assert detached.version == 3
    with engine.connect() as connection:
        repository = _repository(connection)
        assert repository.read_owned_series(principal, series.meeting_series_id) == series
        assert repository.read_owned_series(principal, target.meeting_series_id) == target


def test_a_full_read_assembles_the_view_in_its_deterministic_order(
    engine: Engine, stage: Stage
) -> None:
    principal = stage.mine.principal_id
    meeting = _created(engine, principal, location_text="Room 1", description="Agenda")
    organizer = _attendee(email="host@example.test", organizer=True)
    others = [_attendee(entity_id=stage.mine.person_ids[0]), _attendee(display_name="Guest")]
    with engine.begin() as connection:
        _repository(connection).insert_attendees(
            principal, meeting.meeting_id, [*others, organizer], added_at=T0
        )
    with engine.connect() as connection:
        view = _repository(connection).read_meeting(principal, meeting.meeting_id)
    assert view is not None
    assert view.attendees[0].attendee_id == organizer.attendee_id
    assert [a.attendee_id for a in view.attendees[1:]] == sorted(a.attendee_id for a in others)
    assert view.attendees[0].email == "host@example.test"
    assert view.notes is None
    assert view.series_title is None


# ------------------------------------------------------------------- list


def _list(engine: Engine, principal_id: str, request: MeetingListRequest) -> list[str]:
    with engine.connect() as connection:
        page = _repository(connection).list_meetings(principal_id, request, now=NOW)
    return [entry.meeting_id for entry in page.entries]


def test_list_filters_are_anded_inside_the_partition(engine: Engine, stage: Stage) -> None:
    """AC-024: structured filters; `start_at_from` inclusive, `start_at_before` exclusive."""
    principal = stage.mine.principal_id
    series = _series()
    with engine.begin() as connection:
        _repository(connection).insert_series(principal, series)
    early = _created(engine, principal, start_at=T0)
    in_series = _created(
        engine,
        principal,
        start_at=T0 + timedelta(days=1),
        meeting_series_id=series.meeting_series_id,
    )
    with_project = _created(
        engine, principal, start_at=T0 + timedelta(days=2), project_id=stage.mine.project_id
    )
    cancelled = _created(
        engine,
        principal,
        start_at=T0 + timedelta(days=3),
        status=MeetingStatus.CANCELLED,
        cancelled_at=T0,
    )
    upcoming = _created(engine, principal, start_at=NOW + timedelta(days=1))
    # Ends in the future although it started in the past: upcoming by COALESCE(end_at, start_at).
    ongoing = _created(
        engine, principal, start_at=NOW - timedelta(hours=1), end_at=NOW + timedelta(hours=1)
    )
    _created(engine, stage.theirs.principal_id, start_at=T0)

    assert _list(engine, principal, MeetingListRequest()) == [
        early.meeting_id,
        in_series.meeting_id,
        with_project.meeting_id,
        cancelled.meeting_id,
        ongoing.meeting_id,
        upcoming.meeting_id,
    ]
    assert _list(
        engine, principal, MeetingListRequest(meeting_series_id=series.meeting_series_id)
    ) == [in_series.meeting_id]
    assert _list(engine, principal, MeetingListRequest(project_id=stage.mine.project_id)) == [
        with_project.meeting_id
    ]
    assert _list(engine, principal, MeetingListRequest(status=MeetingStatus.CANCELLED)) == [
        cancelled.meeting_id
    ]
    assert _list(
        engine,
        principal,
        MeetingListRequest(
            start_at_from=T0 + timedelta(days=1), start_at_before=T0 + timedelta(days=3)
        ),
    ) == [in_series.meeting_id, with_project.meeting_id]
    assert _list(engine, principal, MeetingListRequest(time_scope=MeetingTimeScope.UPCOMING)) == [
        ongoing.meeting_id,
        upcoming.meeting_id,
    ]
    assert _list(engine, principal, MeetingListRequest(time_scope=MeetingTimeScope.PAST)) == [
        early.meeting_id,
        in_series.meeting_id,
        with_project.meeting_id,
        cancelled.meeting_id,
    ]


def test_attendee_filters_match_only_active_relations(engine: Engine, stage: Stage) -> None:
    principal = stage.mine.principal_id
    person = stage.mine.person_ids[0]
    active = _created(engine, principal, start_at=T0)
    retired = _created(engine, principal, start_at=T0 + timedelta(days=1))
    with engine.begin() as connection:
        repository = _repository(connection)
        repository.insert_attendees(
            principal,
            active.meeting_id,
            [_attendee(entity_id=person, email="person@example.test")],
            added_at=T0,
        )
        gone = _attendee(entity_id=person, email="person@example.test")
        repository.insert_attendees(principal, retired.meeting_id, [gone], added_at=T0)
        repository.retire_attendees(
            principal, retired.meeting_id, [gone.attendee_id], removed_at=NOW
        )
    assert _list(engine, principal, MeetingListRequest(attendee_entity_id=person)) == [
        active.meeting_id
    ]
    assert _list(engine, principal, MeetingListRequest(attendee_email="Person@Example.test")) == [
        active.meeting_id
    ]


def test_list_pages_by_keyset_in_both_directions(engine: Engine, stage: Stage) -> None:
    """AC-024: `(start_at, meeting_id)` keyset, ties broken by id, bounded page."""
    principal = stage.mine.principal_id
    created = [
        _created(engine, principal, start_at=T0 + timedelta(hours=index // 2)) for index in range(5)
    ]
    expected = [m.meeting_id for m in sorted(created, key=lambda m: (m.start_at, m.meeting_id))]
    with engine.connect() as connection:
        repository = _repository(connection)
        first = repository.list_meetings(principal, MeetingListRequest(page_size=2), now=NOW)
        second = repository.list_meetings(
            principal, MeetingListRequest(page_size=2, after=first.entries[-1].meeting_id), now=NOW
        )
        third = repository.list_meetings(
            principal, MeetingListRequest(page_size=2, after=second.entries[-1].meeting_id), now=NOW
        )
        backwards = repository.list_meetings(
            principal,
            MeetingListRequest(
                page_size=3, sort_direction=MeetingSortDirection.DESC, after=expected[-1]
            ),
            now=NOW,
        )
    assert [e.meeting_id for e in first.entries + second.entries + third.entries] == expected
    assert (first.has_more, second.has_more, third.has_more) == (True, True, False)
    assert [e.meeting_id for e in backwards.entries] == list(reversed(expected[1:4]))
    assert backwards.has_more is True


def test_the_default_list_is_bounded(engine: Engine, stage: Stage) -> None:
    """AC-038: no unbounded default enumeration -- 50 rows, then `has_more`."""
    principal = stage.mine.principal_id
    with engine.begin() as connection:
        connection.execute(
            insert(meetings),
            [
                {
                    "meeting_id": issue_identifier(IdKind.MEETING),
                    "principal_id": principal,
                    "title": "Bulk",
                    "start_at": T0 + timedelta(minutes=index),
                    "timezone_name": "UTC",
                    "created_at": T0,
                    "updated_at": T0,
                }
                for index in range(60)
            ],
        )
    with engine.connect() as connection:
        page = _repository(connection).list_meetings(principal, MeetingListRequest(), now=NOW)
    assert len(page.entries) == 50
    assert page.has_more is True


def test_a_cursor_outside_the_partition_or_the_filters_is_refused(
    engine: Engine, stage: Stage
) -> None:
    """AC-024: the anchor is resolved under the identical Principal and filters."""
    principal = stage.mine.principal_id
    inside = _created(engine, principal, project_id=stage.mine.project_id)
    outside = _created(engine, principal)
    foreign = _created(engine, stage.theirs.principal_id)
    with engine.connect() as connection:
        repository = _repository(connection)
        for request in (
            MeetingListRequest(after=foreign.meeting_id),
            MeetingListRequest(after=issue_identifier(IdKind.MEETING)),
            MeetingListRequest(project_id=stage.mine.project_id, after=outside.meeting_id),
        ):
            with pytest.raises(MeetingCursorError):
                repository.list_meetings(principal, request, now=NOW)
        anchor = repository.resolve_cursor_anchor(
            principal,
            MeetingListRequest(project_id=stage.mine.project_id, after=inside.meeting_id),
            now=NOW,
        )
        assert (anchor.meeting_id, anchor.start_at) == (inside.meeting_id, inside.start_at)
        with pytest.raises(MeetingCursorError):
            repository.search_meetings(
                principal,
                MeetingSearchRequest(
                    query="nothing-matches", filters=MeetingListRequest(after=inside.meeting_id)
                ),
                now=NOW,
            )


# ------------------------------------------------------------------ search


def _search(engine: Engine, principal_id: str, query: str) -> list[str]:
    with engine.connect() as connection:
        page = _repository(connection).search_meetings(
            principal_id, MeetingSearchRequest(query=query), now=NOW
        )
    return [entry.meeting_id for entry in page.entries]


def test_search_matches_core_series_and_current_note_only(engine: Engine, stage: Stage) -> None:
    """AC-025: the section 34.15 statement -- three branches, current note only, no duplicates."""
    principal = stage.mine.principal_id
    series = _series("Quarterly zebra review")
    with engine.begin() as connection:
        _repository(connection).insert_series(principal, series)
    by_title = _created(engine, principal, title="Budget okapi planning", start_at=T0)
    by_description = _created(
        engine, principal, description="discuss the okapi habitat", start_at=T0 + timedelta(hours=1)
    )
    by_location = _created(
        engine, principal, location_text="Okapi room", start_at=T0 + timedelta(hours=2)
    )
    by_series = _created(
        engine,
        principal,
        meeting_series_id=series.meeting_series_id,
        start_at=T0 + timedelta(hours=3),
    )
    by_note = _created(engine, principal, start_at=T0 + timedelta(hours=4))
    superseded = _created(engine, principal, start_at=T0 + timedelta(hours=5))
    by_attendee = _created(engine, principal, start_at=T0 + timedelta(hours=6))
    everywhere = _created(
        engine,
        principal,
        title="Pangolin pangolin",
        meeting_series_id=series.meeting_series_id,
        start_at=T0 + timedelta(hours=7),
    )
    _created(engine, stage.theirs.principal_id, title="Budget okapi planning")

    receipts = {}
    with engine.begin() as connection:
        repository = _repository(connection)
        for meeting in (by_note, superseded, everywhere):
            receipts[meeting.meeting_id] = _receipt(meeting.meeting_id)
            repository.insert_meeting_history(
                principal,
                receipts[meeting.meeting_id],
                meeting_series_id=None,
                idempotency_key="k",
                request_digest=DIGEST,
            )
        repository.insert_note_version(
            principal,
            _note(
                by_note.meeting_id, receipts[by_note.meeting_id].history_id, "The capybara minutes"
            ),
        )
        old = _note(
            superseded.meeting_id, receipts[superseded.meeting_id].history_id, "Old capybara text"
        )
        repository.insert_note_version(principal, old)
        update_receipt = _receipt(
            superseded.meeting_id, action=MeetingHistoryAction.UPDATE, before=1, after=2
        )
        repository.insert_meeting_history(
            principal,
            update_receipt,
            meeting_series_id=None,
            idempotency_key="k2",
            request_digest=DIGEST,
        )
        repository.insert_note_version(
            principal,
            _note(
                superseded.meeting_id,
                update_receipt.history_id,
                "Rewritten wording",
                version_number=2,
                supersedes=old.note_version_id,
            ),
        )
        repository.insert_note_version(
            principal,
            _note(
                everywhere.meeting_id, receipts[everywhere.meeting_id].history_id, "pangolin notes"
            ),
        )
        repository.insert_attendees(
            principal,
            by_attendee.meeting_id,
            [_attendee(display_name="Wombat Person", email="wombat@example.test")],
            added_at=T0,
        )

    assert _search(engine, principal, "okapi") == [
        by_title.meeting_id,
        by_description.meeting_id,
        by_location.meeting_id,
    ]
    assert _search(engine, principal, "zebra") == [by_series.meeting_id, everywhere.meeting_id]
    assert _search(engine, principal, "capybara") == [by_note.meeting_id]
    assert _search(engine, principal, "rewritten") == [superseded.meeting_id]
    assert _search(engine, principal, "wombat") == []
    assert _search(engine, principal, "pangolin") == [everywhere.meeting_id]


def test_search_applies_the_list_filters_and_keyset(engine: Engine, stage: Stage) -> None:
    principal = stage.mine.principal_id
    first = _created(engine, principal, title="Lemur sync", start_at=T0)
    second = _created(engine, principal, title="Lemur sync", start_at=T0 + timedelta(days=1))
    third = _created(
        engine,
        principal,
        title="Lemur sync",
        start_at=T0 + timedelta(days=2),
        project_id=stage.mine.project_id,
    )
    with engine.connect() as connection:
        repository = _repository(connection)
        page = repository.search_meetings(
            principal,
            MeetingSearchRequest(
                query="lemur", filters=MeetingListRequest(page_size=1, after=first.meeting_id)
            ),
            now=NOW,
        )
        filtered = repository.search_meetings(
            principal,
            MeetingSearchRequest(
                query="lemur", filters=MeetingListRequest(project_id=stage.mine.project_id)
            ),
            now=NOW,
        )
    assert [e.meeting_id for e in page.entries] == [second.meeting_id]
    assert page.has_more is True
    assert [e.meeting_id for e in filtered.entries] == [third.meeting_id]


def test_a_list_entry_counts_only_active_relations(engine: Engine, stage: Stage) -> None:
    principal = stage.mine.principal_id
    meeting = _created(engine, principal)
    kept = _attendee(display_name="Kept")
    dropped = _attendee(display_name="Dropped")
    with engine.begin() as connection:
        repository = _repository(connection)
        repository.insert_attendees(principal, meeting.meeting_id, [kept, dropped], added_at=T0)
        repository.retire_attendees(
            principal, meeting.meeting_id, [dropped.attendee_id], removed_at=NOW
        )
        repository.insert_attachments(
            principal,
            meeting.meeting_id,
            [
                MeetingAttachmentRecord(
                    issue_identifier(IdKind.MEETING_ATTACHMENT), stage.mine.document_id
                )
            ],
            added_at=T0,
        )
    with engine.connect() as connection:
        page = _repository(connection).list_meetings(principal, MeetingListRequest(), now=NOW)
    assert (page.entries[0].attendee_count, page.entries[0].attachment_count) == (1, 1)


# ----------------------------------------------------------- EXPLAIN evidence


def _seed_synthetic_volume(engine: Engine, stage: Stage) -> tuple[str, str]:
    """Enough synthetic rows for the planner's choice to mean something."""
    principal = stage.mine.principal_id
    series = _series("Synthetic volume series")
    with engine.begin() as connection:
        _repository(connection).insert_series(principal, series)
        rows: list[dict[str, object]] = []
        attendees: list[dict[str, object]] = []
        for index in range(3000):
            meeting_id = issue_identifier(IdKind.MEETING)
            rows.append(
                {
                    "meeting_id": meeting_id,
                    "principal_id": principal,
                    "meeting_series_id": series.meeting_series_id if index % 7 == 0 else None,
                    "project_id": stage.mine.project_id if index % 11 == 0 else None,
                    "title": f"Synthetic meeting {index} word{index % 97}",
                    "description": f"description token{index % 89}",
                    "location_text": f"room{index % 13}",
                    "status": "cancelled" if index % 17 == 0 else "scheduled",
                    "cancelled_at": T0 if index % 17 == 0 else None,
                    "start_at": T0 + timedelta(hours=index),
                    "timezone_name": "UTC",
                    "created_at": T0,
                    "updated_at": T0,
                }
            )
            attendees.append(
                {
                    "attendee_id": issue_identifier(IdKind.MEETING_ATTENDEE),
                    "principal_id": principal,
                    "meeting_id": meeting_id,
                    "email_normalized": f"person{index % 101}@example.test",
                    "entity_id": stage.mine.person_ids[index % 3] if index % 5 == 0 else None,
                    "added_at": T0,
                }
            )
        connection.execute(insert(meetings), rows)
        connection.execute(insert(meeting_attendees), attendees)
        history_rows = []
        note_rows = []
        for row in rows[::10]:
            history_id = issue_identifier(IdKind.MEETING_HISTORY)
            history_rows.append(
                {
                    "history_id": history_id,
                    "principal_id": principal,
                    "meeting_id": row["meeting_id"],
                    "action": "create",
                    "actor": "principal",
                    "outcome": "applied",
                    "before_version": 0,
                    "after_version": 1,
                    "idempotency_key": "k",
                    "request_digest": DIGEST,
                    "occurred_at": T0,
                    "recorded_at": T0,
                }
            )
            body = f"note body {row['meeting_id']} lexeme{len(note_rows) % 50}"
            note_rows.append(
                {
                    "note_version_id": issue_identifier(IdKind.MEETING_NOTE_VERSION),
                    "principal_id": principal,
                    "meeting_id": row["meeting_id"],
                    "version_number": 1,
                    "content_markdown": body,
                    "content_sha256": note_content_sha256(body),
                    "meeting_history_id": history_id,
                    "recorded_at": T0,
                }
            )
        connection.execute(insert(meeting_history), history_rows)
        connection.execute(insert(meeting_note_versions), note_rows)
        many_series = [
            {
                "meeting_series_id": issue_identifier(IdKind.MEETING_SERIES),
                "principal_id": principal,
                "title": f"Series title {index} tag{index % 31}",
                "created_at": T0,
                "updated_at": T0,
            }
            for index in range(1000)
        ]
        connection.execute(insert(meeting_series), many_series)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for name in ("meetings", "meeting_series", "meeting_attendees", "meeting_note_versions"):
            connection.execute(text(f"ANALYZE {SCHEMA}.{name}"))
    return principal, series.meeting_series_id


def _plan(connection: Connection, statement: ClauseElement) -> str:
    compiled = statement.compile(connection)
    rows = connection.exec_driver_sql(f"EXPLAIN {compiled.string}", compiled.params).scalars()
    return "\n".join(rows)


def _captured_plans(
    connection: Connection, run: Callable[[SqlMeetingRepository], object]
) -> list[str]:
    """EXPLAIN every statement the repository issues for `run`."""
    captured: list[tuple[str, object]] = []

    def record(
        _conn: object, _cursor: object, statement: str, parameters: object, *_: object
    ) -> None:
        captured.append((statement, parameters))

    event.listen(connection, "before_cursor_execute", record)
    try:
        run(_repository(connection))
    finally:
        event.remove(connection, "before_cursor_execute", record)
    return [
        "\n".join(connection.exec_driver_sql(f"EXPLAIN {statement}", parameters).scalars())
        for statement, parameters in captured
    ]


def test_the_text_predicates_are_eligible_for_their_gin_indexes(
    engine: Engine, stage: Stage
) -> None:
    """AC-025/AC-038: core, series-title and current-note expressions match their GIN trees."""
    principal, _ = _seed_synthetic_volume(engine, stage)
    query = func.websearch_to_tsquery(literal_column("'simple'", REGCONFIG), "word13")
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        core = _plan(
            connection,
            select(meetings.c.meeting_id).where(
                meetings.c.principal_id == principal, _core_document().bool_op("@@")(query)
            ),
        )
        series = _plan(
            connection,
            select(meeting_series.c.meeting_series_id).where(
                meeting_series.c.principal_id == principal, _series_document().bool_op("@@")(query)
            ),
        )
        note = _plan(
            connection,
            select(meeting_note_versions.c.note_version_id).where(
                meeting_note_versions.c.principal_id == principal,
                _note_document().bool_op("@@")(query),
            ),
        )
        # The whole search statement runs and stays inside the partition.
        whole = _captured_plans(
            connection,
            lambda r: r.search_meetings(principal, MeetingSearchRequest(query="word13"), now=NOW),
        )
    assert "meetings_core_text" in core
    assert "meeting_series_title_text" in series
    assert "meeting_note_versions_text" in note
    assert len(whole) == 1
    assert whole[0]


@pytest.mark.parametrize(
    ("request_for", "indexes"),
    [
        ("project", {"meetings_by_principal_project_start"}),
        ("series", {"meetings_by_principal_series_start"}),
        ("status", {"meetings_by_principal_status_start"}),
        ("time", {"meetings_by_principal_start"}),
        ("email", {"meeting_attendees_active_by_email", "meeting_attendees_one_active_email"}),
        ("entity", {"meeting_attendees_active_by_entity", "meeting_attendees_one_active_entity"}),
    ],
)
def test_the_list_predicates_are_eligible_for_their_btrees(
    engine: Engine, stage: Stage, request_for: str, indexes: set[str]
) -> None:
    """AC-024/AC-038: project, series, status, time and attendee predicates use btrees."""
    principal, series_id = _seed_synthetic_volume(engine, stage)
    requests = {
        "project": MeetingListRequest(project_id=stage.mine.project_id),
        "series": MeetingListRequest(meeting_series_id=series_id),
        "status": MeetingListRequest(status=MeetingStatus.CANCELLED),
        "time": MeetingListRequest(
            start_at_from=T0 + timedelta(days=30), start_at_before=T0 + timedelta(days=40)
        ),
        "email": MeetingListRequest(attendee_email="person7@example.test"),
        "entity": MeetingListRequest(attendee_entity_id=stage.mine.person_ids[1]),
    }
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plans = _captured_plans(
            connection, lambda r: r.list_meetings(principal, requests[request_for], now=NOW)
        )
    assert len(plans) == 1
    assert any(index in plans[0] for index in indexes), plans[0]


def test_no_meeting_write_path_updates_a_history_or_note_row(engine: Engine, stage: Stage) -> None:
    """The repository never issues an UPDATE on an immutable ledger (the triggers are WP04's)."""
    principal = stage.mine.principal_id
    meeting = _created(engine, principal)
    statements: list[str] = []
    with engine.begin() as connection:

        def record(_c: object, _cur: object, statement: str, *_: object) -> None:
            statements.append(statement)

        event.listen(connection, "before_cursor_execute", record)
        repository = _repository(connection)
        receipt = _receipt(
            meeting.meeting_id, action=MeetingHistoryAction.UPDATE, before=1, after=2
        )
        repository.insert_meeting_history(
            principal, receipt, meeting_series_id=None, idempotency_key="k", request_digest=DIGEST
        )
        repository.insert_note_version(
            principal, _note(meeting.meeting_id, receipt.history_id, "Body")
        )
        repository.update_meeting(principal, _meeting(meeting_id=meeting.meeting_id, version=2))
        event.remove(connection, "before_cursor_execute", record)
    updates = [s for s in statements if s.lstrip().upper().startswith("UPDATE")]
    assert updates
    assert all(
        f"{SCHEMA}.meeting_history" not in s and f"{SCHEMA}.meeting_note_versions" not in s
        for s in updates
    )
    with engine.connect() as connection:
        stored = connection.execute(
            select(meeting_history.c.after_version).where(
                meeting_history.c.history_id == receipt.history_id
            )
        ).scalar_one()
    assert stored == 2
