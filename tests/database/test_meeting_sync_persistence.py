"""WP3b-S1: `SqlMeetingSyncRepository` and the binding snapshot columns, on a live server.

The `database` tier, on a disposable head-migrated clone. What is proved here is
the persistence half the WP3b slices build on: each repository operation writes
and reads back exactly what it was given; every read is partitioned, so another
Principal's row answers as an absent one; a targeted update of a row that does
not exist (or is another Principal's) is `RepositoryFailureError`; the
revision's guards surface through the repository unabsorbed (a second apply, a
second latch, a staged event of another Principal's publication); the review
mark is idempotent by Meeting; publications list in apply order (Manager ruling
D8); a binding round-trips its `origin_snapshot_id` and `last_seen_snapshot_id`
(D10); and the general unit of work exposes the repository on its connection.

Every identifier and text here is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Engine, insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from my_pa.contracts.ports import (
    IngestConsumer,
    IngestSnapshotRecord,
    IngestSourceRecord,
    MeetingProviderBindingRecord,
    MeetingProviderKeyTombstoneRecord,
    MeetingProviderReconciliationPassRecord,
    MeetingProviderReviewMarkRecord,
    MeetingSyncApplyOutcome,
    MeetingSyncEventRecord,
    MeetingSyncPublicationRecord,
    RepositoryFailureError,
)
from my_pa.domain.meeting_sync.model import (
    EventStatus,
    ProviderBindingState,
    ProviderEventIdFormat,
)
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.ingestion import SqlIngestionRepository
from my_pa.infrastructure.persistence.meeting_sync import SqlMeetingSyncRepository
from my_pa.infrastructure.persistence.meetings import SqlMeetingRepository
from my_pa.infrastructure.persistence.tables import meeting_history, meetings
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

P: Final = "prn_msyncrepo0001aaaa"
OTHER: Final = "prn_msyncrepo0002bbbb"
WHEN: Final = datetime(2026, 11, 23, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)
RESTRICT_VIOLATION: Final = "23001"
UNIQUE_VIOLATION: Final = "23505"
FOREIGN_KEY_VIOLATION: Final = "23503"

SOURCE: Final = IngestSourceRecord(
    ingest_source_id="isrc_msyncrepo0001",
    consumer=IngestConsumer.MEETING_SYNC_V1,
    workspace_id="mcp",
    path_prefix="My PA/Daily Intelligence/meetings/",
    file_pattern="*-meetings.json",
    enabled=True,
    admitted_at=WHEN,
)
SNAP_A: Final = "isnp_msyncrepo000a"
SNAP_B: Final = "isnp_msyncrepo000b"
SNAP_C: Final = "isnp_msyncrepo000c"
M1: Final = "mtg_msyncrepo00001"
M2: Final = "mtg_msyncrepo00002"
H1: Final = "mhst_msyncrepo0001"


def _publication(snapshot_id: str, **overrides: object) -> MeetingSyncPublicationRecord:
    values: dict[str, object] = {
        "snapshot_id": snapshot_id,
        "ingest_source_id": SOURCE.ingest_source_id,
        "generated_at_utc": WHEN,
        "record_count": 3,
        "accepted_count": 2,
        "quarantined_count": 1,
        "staged_at": WHEN,
    }
    values.update(overrides)
    return MeetingSyncPublicationRecord(**values)  # type: ignore[arg-type]


def _event(event_id: str, ordinal: int, **overrides: object) -> MeetingSyncEventRecord:
    values: dict[str, object] = {
        "event_id": event_id,
        "snapshot_id": SNAP_A,
        "record_ordinal": ordinal,
        "calendar_ref": "cal-synthetic",
        "ical_uid": f"uid-{ordinal}@example.invalid",
        "series_ical_uid": None,
        "occurrence_original_start_utc": None,
        "start_utc": WHEN,
        "end_utc": LATER,
        "timezone_name": "America/New_York",
        "status": EventStatus.CONFIRMED,
        "title": "A synthetic meeting",
        "location_text": None,
        "virtual_meeting_url": None,
        "provider_event_id": None,
        "provider_event_id_format": ProviderEventIdFormat.UNKNOWN,
        "staged_at": WHEN,
    }
    values.update(overrides)
    return MeetingSyncEventRecord(**values)  # type: ignore[arg-type]


@pytest.fixture
def connection(migrated_engine: Engine) -> Iterator[Connection]:
    """One transaction, rolled back after the test."""
    with migrated_engine.connect() as opened:
        transaction = opened.begin()
        try:
            yield opened
        finally:
            transaction.rollback()


@pytest.fixture
def repository(connection: Connection) -> SqlMeetingSyncRepository:
    """A source with three snapshots (A and C share a digest's source, B another
    digest), two Meetings and one receipt of the first."""
    ingestion = SqlIngestionRepository(connection)
    ingestion.insert_source(P, SOURCE)
    for snapshot_id, digest in ((SNAP_A, "a"), (SNAP_B, "b"), (SNAP_C, "c")):
        ingestion.insert_snapshot(
            P,
            IngestSnapshotRecord(
                snapshot_id=snapshot_id,
                ingest_source_id=SOURCE.ingest_source_id,
                file_sha256=digest * 64,
                byte_count=10,
                observed_version_token=None,
                first_seen_at=WHEN,
            ),
        )
    for meeting_id in (M1, M2):
        connection.execute(
            insert(meetings).values(
                meeting_id=meeting_id,
                principal_id=P,
                title="A synthetic meeting",
                start_at=WHEN,
                timezone_name="UTC",
                status="scheduled",
                version=1,
                created_at=WHEN,
                updated_at=WHEN,
            )
        )
    connection.execute(
        insert(meeting_history).values(
            history_id=H1,
            principal_id=P,
            meeting_id=M1,
            action="create",
            actor="principal",
            outcome="applied",
            before_version=0,
            after_version=1,
            idempotency_key="msync-repo-0001",
            request_digest="d" * 64,
            occurred_at=WHEN,
            recorded_at=WHEN,
        )
    )
    return SqlMeetingSyncRepository(connection)


def _sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None)


def _refused(connection: Connection, call: Callable[[], object]) -> str | None:
    """Run `call` under a savepoint; return its SQLSTATE (and undo the failure)."""
    savepoint = connection.begin_nested()
    try:
        call()
    except DBAPIError as error:
        savepoint.rollback()
        return _sqlstate(error)
    savepoint.commit()
    return None


# ---- staging ----------------------------------------------------------------------


def test_a_publication_round_trips_with_and_without_coverage(
    repository: SqlMeetingSyncRepository,
) -> None:
    bare = _publication(SNAP_A)
    covered = _publication(
        SNAP_B,
        coverage_start_utc=WHEN - timedelta(days=30),
        coverage_end_utc=WHEN,
        coverage_calendar_refs=("cal-synthetic", "cal-other"),
    )
    repository.insert_publication(P, bare)
    repository.insert_publication(P, covered)
    assert repository.get_publication(P, SNAP_A) == bare
    assert repository.get_publication(P, SNAP_B) == covered
    assert repository.get_publication(OTHER, SNAP_A) is None


def test_a_publication_is_applied_once_and_the_second_is_refused(
    connection: Connection, repository: SqlMeetingSyncRepository
) -> None:
    repository.insert_publication(P, _publication(SNAP_A))
    repository.complete_publication(
        P,
        SNAP_A,
        applied_at=LATER,
        apply_outcome=MeetingSyncApplyOutcome.APPLIED,
        apply_counts={"records_applied": 2, "meetings_created": 1},
    )
    assert repository.get_publication(P, SNAP_A) == _publication(
        SNAP_A,
        applied_at=LATER,
        apply_outcome=MeetingSyncApplyOutcome.APPLIED,
        apply_counts={"records_applied": 2, "meetings_created": 1},
    )
    again = _refused(
        connection,
        lambda: repository.complete_publication(
            P,
            SNAP_A,
            applied_at=LATER,
            apply_outcome=MeetingSyncApplyOutcome.SKIPPED_STALE,
            apply_counts={},
        ),
    )
    assert again == RESTRICT_VIOLATION


def test_completing_a_missing_or_foreign_publication_is_a_repository_failure(
    repository: SqlMeetingSyncRepository,
) -> None:
    repository.insert_publication(P, _publication(SNAP_A))
    for principal, snapshot_id in ((P, SNAP_B), (OTHER, SNAP_A)):
        with pytest.raises(RepositoryFailureError):
            repository.complete_publication(
                principal,
                snapshot_id,
                applied_at=LATER,
                apply_outcome=MeetingSyncApplyOutcome.APPLIED,
                apply_counts={},
            )


def test_publications_list_in_apply_order(repository: SqlMeetingSyncRepository) -> None:
    """D8: by `generated_at_utc`, then the snapshot's digest, then the id."""
    newest = _publication(SNAP_A, generated_at_utc=LATER)
    tie_c = _publication(SNAP_C)  # digest c...
    tie_b = _publication(SNAP_B)  # digest b..., so before c on the same stamp
    for publication in (newest, tie_c, tie_b):
        repository.insert_publication(P, publication)
    ordered = repository.list_publications(P, SOURCE.ingest_source_id)
    assert [p.snapshot_id for p in ordered] == [SNAP_B, SNAP_C, SNAP_A]
    repository.complete_publication(
        P,
        SNAP_B,
        applied_at=LATER,
        apply_outcome=MeetingSyncApplyOutcome.APPLIED,
        apply_counts={"records_applied": 2},
    )
    unapplied = repository.list_publications(P, SOURCE.ingest_source_id, unapplied_only=True)
    assert [p.snapshot_id for p in unapplied] == [SNAP_C, SNAP_A]
    assert repository.list_publications(OTHER, SOURCE.ingest_source_id) == ()


def test_events_round_trip_in_ordinal_order(repository: SqlMeetingSyncRepository) -> None:
    repository.insert_publication(P, _publication(SNAP_A))
    occurrence = _event(
        "msevt_msyncrepo0002",
        2,
        series_ical_uid="series@example.invalid",
        occurrence_original_start_utc=WHEN - timedelta(days=7),
        status=EventStatus.CANCELLED,
        location_text="Trailer 2",
        virtual_meeting_url="https://meet.example.invalid/x",
        provider_event_id="AAMk-synthetic",
        provider_event_id_format=ProviderEventIdFormat.MUTABLE,
    )
    single = _event("msevt_msyncrepo0001", 0)
    repository.insert_events(P, [occurrence, single])
    repository.insert_events(P, [])
    assert repository.list_events(P, SNAP_A) == (single, occurrence)
    assert repository.get_event(P, "msevt_msyncrepo0002") == occurrence
    assert repository.get_event(OTHER, "msevt_msyncrepo0002") is None
    assert repository.list_events(OTHER, SNAP_A) == ()


def test_an_event_names_a_publication_of_its_principal(
    connection: Connection, repository: SqlMeetingSyncRepository
) -> None:
    repository.insert_publication(P, _publication(SNAP_A))
    foreign = _refused(
        connection, lambda: repository.insert_events(OTHER, [_event("msevt_msyncrepo0009", 0)])
    )
    assert foreign == FOREIGN_KEY_VIOLATION
    duplicate = _refused(
        connection,
        lambda: repository.insert_events(
            P, [_event("msevt_msyncrepo0003", 1), _event("msevt_msyncrepo0004", 1)]
        ),
    )
    assert duplicate == UNIQUE_VIOLATION


# ---- review marks and the latch -------------------------------------------------------


def test_a_review_mark_is_idempotent_by_meeting(repository: SqlMeetingSyncRepository) -> None:
    first = MeetingProviderReviewMarkRecord(meeting_id=M1, marked_at=WHEN)
    assert repository.insert_review_mark(P, first) is True
    assert repository.insert_review_mark(P, replace(first, marked_at=LATER)) is False
    assert repository.get_review_mark(P, M1) == first
    repository.insert_review_mark(
        P, MeetingProviderReviewMarkRecord(meeting_id=M2, marked_at=LATER)
    )
    assert [mark.meeting_id for mark in repository.list_review_marks(P)] == [M1, M2]
    assert repository.get_review_mark(OTHER, M1) is None
    assert repository.list_review_marks(OTHER) == ()


def test_the_latch_is_recorded_once(
    connection: Connection, repository: SqlMeetingSyncRepository
) -> None:
    assert repository.get_reconciliation_pass(P) is None
    latch = MeetingProviderReconciliationPassRecord(
        completed_at=WHEN, reviewed_meetings=2, reconcile_correlation_id="corr_msyncrepo0001"
    )
    repository.insert_reconciliation_pass(P, latch)
    assert repository.get_reconciliation_pass(P) == latch
    assert repository.get_reconciliation_pass(OTHER) is None
    again = _refused(connection, lambda: repository.insert_reconciliation_pass(P, latch))
    assert again == UNIQUE_VIOLATION


# ---- key tombstones -------------------------------------------------------------------


def test_tombstones_list_by_key(repository: SqlMeetingSyncRepository) -> None:
    original = WHEN - timedelta(days=7)
    single = MeetingProviderKeyTombstoneRecord(
        binding_id="mpbnd_msyncrepo0001",
        meeting_id=M1,
        calendar_ref="cal-synthetic",
        ical_uid="uid-1@example.invalid",
        occurrence_original_start_utc=None,
        series_ical_uid=None,
        unbound_at=WHEN,
        meeting_history_id=H1,
    )
    again = replace(single, binding_id="mpbnd_msyncrepo0002", unbound_at=LATER)
    occurrence = replace(
        single,
        binding_id="mpbnd_msyncrepo0003",
        occurrence_original_start_utc=original,
        series_ical_uid="uid-1@example.invalid",
    )
    for tombstone in (again, occurrence, single):
        repository.insert_key_tombstone(P, tombstone)
    key = ("cal-synthetic", "uid-1@example.invalid")
    assert repository.list_key_tombstones(P, *key, None) == (single, again)
    assert repository.list_key_tombstones(P, *key, original) == (occurrence,)
    assert repository.list_key_tombstones(OTHER, *key, None) == ()


# ---- the binding snapshot columns (D10) ----------------------------------------------------


def _binding(**overrides: object) -> MeetingProviderBindingRecord:
    values: dict[str, object] = {
        "binding_id": "mpbnd_msyncrepob001",
        "meeting_id": M2,
        "calendar_ref": "cal-synthetic",
        "ical_uid": "uid-bound@example.invalid",
        "occurrence_original_start_utc": None,
        "series_ical_uid": None,
        "provider_event_id": None,
        "provider_event_id_format": ProviderEventIdFormat.UNKNOWN,
        "provider_state": ProviderBindingState.ACTIVE,
        "last_seen_source_sha256": "a" * 64,
        "last_seen_record_ordinal": 0,
        "last_seen_at": WHEN,
        "version": 1,
        "created_at": WHEN,
        "updated_at": WHEN,
        "last_applied_generated_at_utc": WHEN,
        "origin_snapshot_id": SNAP_A,
        "last_seen_snapshot_id": SNAP_A,
    }
    values.update(overrides)
    return MeetingProviderBindingRecord(**values)  # type: ignore[arg-type]


def test_a_binding_round_trips_its_snapshot_columns(
    connection: Connection, repository: SqlMeetingSyncRepository
) -> None:
    del repository
    meetings_repository = SqlMeetingRepository(connection)
    created = _binding()
    meetings_repository.insert_provider_binding(P, created)
    assert meetings_repository.read_provider_binding_for_meeting(P, M2) == created
    observed = replace(
        created,
        last_seen_source_sha256="b" * 64,
        last_seen_record_ordinal=4,
        last_seen_at=LATER,
        last_seen_snapshot_id=SNAP_B,
        updated_at=LATER,
    )
    meetings_repository.update_provider_binding(P, observed)
    assert meetings_repository.read_provider_binding_for_meeting(P, M2) == observed
    # An update never rewrites the origin, even when the record says otherwise.
    meetings_repository.update_provider_binding(P, replace(observed, origin_snapshot_id=SNAP_C))
    stored = meetings_repository.read_provider_binding_for_meeting(P, M2)
    assert stored is not None
    assert stored.origin_snapshot_id == SNAP_A


def test_a_binding_digest_must_be_its_snapshots(
    connection: Connection, repository: SqlMeetingSyncRepository
) -> None:
    del repository
    meetings_repository = SqlMeetingRepository(connection)
    mismatched = _binding(last_seen_snapshot_id=SNAP_B)  # B's digest is b..., not a...
    refused = _refused(
        connection, lambda: meetings_repository.insert_provider_binding(P, mismatched)
    )
    assert refused == FOREIGN_KEY_VIOLATION


def test_an_explicit_bind_names_no_snapshot(
    connection: Connection, repository: SqlMeetingSyncRepository
) -> None:
    del repository
    meetings_repository = SqlMeetingRepository(connection)
    explicit = _binding(
        last_seen_source_sha256=None,
        last_seen_record_ordinal=None,
        last_seen_at=None,
        last_applied_generated_at_utc=None,
        origin_snapshot_id=None,
        last_seen_snapshot_id=None,
    )
    meetings_repository.insert_provider_binding(P, explicit)
    assert meetings_repository.read_provider_binding_for_meeting(P, M2) == explicit


# ---- the unit of work -----------------------------------------------------------------------


def test_the_unit_of_work_exposes_the_repository(migrated_engine: Engine) -> None:
    with SqlAlchemyUnitOfWork(migrated_engine, audit=SqlAlchemyAuditSink(migrated_engine)) as uow:
        assert isinstance(uow.meeting_sync, SqlMeetingSyncRepository)
        assert uow.meeting_sync.get_reconciliation_pass(P) is None
