"""WP-MTG-02: Meeting write arbitration and lock order, under actual concurrency.

Marked `database` and `recovery` (routed to database-recovery). Authored in
WP-MTG-02 and first executed in WP-MTG-04, once the Meeting revision exists in a
migrated database (plan D-12).

A sequential test can show that a reservation replays or conflicts; it cannot
show what happens when two requests overlap, which is the case package section
35.7 is written for. So each test here runs the overlapping transactions on
separate connections, with the second in a thread, and waits until PostgreSQL
reports the second as blocked on a lock before letting the first finish. Every
waiting transaction carries a `lock_timeout`, so a build that does not take the
lock this module expects fails loudly instead of hanging the tier.

What is proved:

* two first uses of one key have exactly one owner; the loser replays the
  committed winner, or conflicts on a different digest, and never sees a raw
  `IntegrityError` (AC-029, AC-041);
* a rolled-back owner releases its reservation, and a whole failed write leaves
  no Meeting, series, child, receipt, note or request row behind (AC-031);
* the Meeting and MeetingSeries parents serialize writers `FOR UPDATE`
  (AC-030, AC-043);
* attendee Entities are share-locked in ascending id order, and two writers
  naming the same Entities in opposite orders do not deadlock (AC-043).

Every identity here is synthetic.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Engine, func, insert, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError

from my_pa.contracts.ports import (
    MeetingAttendeeRecord,
    MeetingNoteRecord,
    MeetingRecord,
    MeetingWriteRequestRecord,
    RepositoryFailureError,
)
from my_pa.contracts.v1.meetings import (
    MeetingHistoryView,
    MeetingSeriesHistoryView,
    MeetingSeriesView,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.meeting.model import (
    MEETINGS_CREATE_NAME,
    MEETINGS_UPDATE_NAME,
    AttendeeResponseStatus,
    MeetingActor,
    MeetingHistoryAction,
    MeetingIdempotencyConflictError,
    MeetingOutcome,
    MeetingStatus,
    NormalizedAttendee,
    note_content_sha256,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.meetings import SqlMeetingRepository
from my_pa.infrastructure.persistence.tables import (
    entities,
    meeting_attendees,
    meeting_history,
    meeting_note_versions,
    meeting_series,
    meeting_series_history,
    meeting_write_requests,
    meetings,
)

pytestmark = [pytest.mark.database, pytest.mark.recovery]

T0: Final = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
DIGEST: Final = "c" * 64
OTHER_DIGEST: Final = "d" * 64

#: How long a waiting transaction waits for a lock before failing. Long enough
#: that a loaded host does not turn a pass into a failure, short enough that a
#: build with no lock at all reports rather than hangs.
LOCK_TIMEOUT: Final = "20s"

#: How long the test waits for the waiting thread once the holder has finished.
#: Strictly greater than `LOCK_TIMEOUT`, so a timeout surfaces as the database's
#: own error rather than as an abandoned thread.
JOIN_TIMEOUT_SECONDS: Final = 60.0

#: How long the test waits to observe the second transaction blocked.
BLOCK_DEADLINE_SECONDS: Final = 15.0


@dataclass(frozen=True)
class Stage:
    principal_id: str
    lower_entity_id: str
    upper_entity_id: str


@pytest.fixture
def engine(db_engine: Engine) -> Iterator[Engine]:
    yield db_engine


@pytest.fixture
def stage(engine: Engine) -> Stage:
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    first, second = sorted(issue_identifier(IdKind.ENTITY) for _ in range(2))
    with engine.begin() as connection:
        # The upper id is inserted first, so heap order is the reverse of id
        # order: an unsorted lock statement would reach the upper row first.
        for entity_id in (second, first):
            connection.execute(
                insert(entities).values(
                    entity_id=entity_id,
                    principal_id=principal_id,
                    entity_type="person",
                    canonical_name="synthetic person",
                    display_name="Synthetic Person",
                    status="active",
                    created_at=T0,
                    updated_at=T0,
                    version=1,
                )
            )
    return Stage(principal_id=principal_id, lower_entity_id=first, upper_entity_id=second)


def _lock_timeout(connection: Connection) -> None:
    connection.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))


def _in_own_transaction[ResultT](
    engine: Engine, work: Callable[[SqlMeetingRepository], ResultT]
) -> ResultT:
    with engine.begin() as connection:
        _lock_timeout(connection)
        return work(SqlMeetingRepository(connection))


def _wait_until_blocked[ResultT](engine: Engine, future: Future[ResultT]) -> None:
    """Return once another backend of this database waits on a lock.

    Fails if the future finished first: the whole point is that it could not.
    """
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


def _meeting(meeting_id: str | None = None, *, version: int = 1) -> MeetingRecord:
    return MeetingRecord(
        meeting_id=meeting_id or issue_identifier(IdKind.MEETING),
        meeting_series_id=None,
        title="Synthetic sync",
        start_at=T0,
        end_at=None,
        timezone_name="UTC",
        status=MeetingStatus.SCHEDULED,
        cancelled_at=None,
        location_text=None,
        virtual_meeting_url=None,
        description=None,
        project_id=None,
        version=version,
        created_at=T0,
        updated_at=T0,
    )


def _receipt(
    meeting_id: str, *, update: bool = False, before: int = 0, after: int = 1
) -> MeetingHistoryView:
    return MeetingHistoryView(
        history_id=issue_identifier(IdKind.MEETING_HISTORY),
        meeting_id=meeting_id,
        action=MeetingHistoryAction.UPDATE if update else MeetingHistoryAction.CREATE,
        actor=MeetingActor.PRINCIPAL,
        outcome=MeetingOutcome.APPLIED,
        before_version=before,
        after_version=after,
        occurred_at=T0,
        recorded_at=T0,
    )


def _create_through(
    repository: SqlMeetingRepository, principal_id: str, key: str, digest: str
) -> tuple[MeetingRecord, MeetingHistoryView]:
    """The persistence steps of one standalone create after its reservation."""
    record = _meeting()
    receipt = _receipt(record.meeting_id)
    repository.insert_meeting(principal_id, record)
    repository.insert_meeting_history(
        principal_id, receipt, meeting_series_id=None, idempotency_key=key, request_digest=digest
    )
    repository.complete_write_request(
        principal_id,
        MEETINGS_CREATE_NAME,
        key,
        request_digest=digest,
        meeting_id=record.meeting_id,
        meeting_series_id=None,
        meeting_history_id=receipt.history_id,
        meeting_series_history_id=None,
        result_version=1,
        completed_at=T0,
    )
    return record, receipt


def _committed_meeting(engine: Engine, principal_id: str) -> MeetingRecord:
    with engine.begin() as connection:
        repository = SqlMeetingRepository(connection)
        repository.reserve_write_request(
            principal_id, MEETINGS_CREATE_NAME, "seed", DIGEST, created_at=T0
        )
        record, _ = _create_through(repository, principal_id, "seed", DIGEST)
    return record


# --------------------------------------------------------- reservation races


@pytest.mark.parametrize("second_digest", [DIGEST, OTHER_DIGEST])
def test_two_first_uses_of_one_key_have_exactly_one_owner(
    engine: Engine, stage: Stage, second_digest: str
) -> None:
    """AC-029/AC-041: the loser waits, then replays the winner or conflicts."""
    principal = stage.principal_id
    key = "same-key"
    with engine.connect() as holder, ThreadPoolExecutor(max_workers=1) as pool:
        transaction = holder.begin()
        repository = SqlMeetingRepository(holder)
        assert (
            repository.reserve_write_request(
                principal, MEETINGS_CREATE_NAME, key, DIGEST, created_at=T0
            )
            is None
        )
        record, receipt = _create_through(repository, principal, key, DIGEST)

        loser: Future[MeetingWriteRequestRecord | None] = pool.submit(
            _in_own_transaction,
            engine,
            lambda other: other.reserve_write_request(
                principal, MEETINGS_CREATE_NAME, key, second_digest, created_at=T0
            ),
        )
        _wait_until_blocked(engine, loser)
        transaction.commit()

        if second_digest == DIGEST:
            replay = loser.result(timeout=JOIN_TIMEOUT_SECONDS)
            assert replay is not None
            assert replay.meeting_id == record.meeting_id
            assert replay.meeting_receipt == receipt
        else:
            with pytest.raises(MeetingIdempotencyConflictError):
                loser.result(timeout=JOIN_TIMEOUT_SECONDS)

    with engine.connect() as connection:
        rows = connection.execute(
            select(func.count()).select_from(meeting_write_requests)
        ).scalar_one()
        created = connection.execute(select(func.count()).select_from(meetings)).scalar_one()
    assert (rows, created) == (1, 1)


def test_a_rolled_back_owner_releases_its_reservation(engine: Engine, stage: Stage) -> None:
    """AC-031/AC-041: the waiting request becomes the owner once the first rolls back."""
    principal = stage.principal_id
    key = "released-key"
    with engine.connect() as holder, ThreadPoolExecutor(max_workers=1) as pool:
        transaction = holder.begin()
        assert (
            SqlMeetingRepository(holder).reserve_write_request(
                principal, MEETINGS_CREATE_NAME, key, DIGEST, created_at=T0
            )
            is None
        )
        waiter: Future[MeetingWriteRequestRecord | None] = pool.submit(
            _in_own_transaction,
            engine,
            lambda other: other.reserve_write_request(
                principal, MEETINGS_CREATE_NAME, key, DIGEST, created_at=T0
            ),
        )
        _wait_until_blocked(engine, waiter)
        transaction.rollback()
        assert waiter.result(timeout=JOIN_TIMEOUT_SECONDS) is None


def test_a_failed_write_leaves_nothing_and_frees_its_key(engine: Engine, stage: Stage) -> None:
    """AC-031: reservation, series, occurrence, children, receipts and note roll back together."""
    principal = stage.principal_id
    key = "failed-key"
    series = MeetingSeriesView(
        meeting_series_id=issue_identifier(IdKind.MEETING_SERIES),
        title="Synthetic series",
        version=1,
        created_at=T0,
        updated_at=T0,
    )

    class InjectedError(RuntimeError):
        pass

    with pytest.raises(InjectedError), engine.begin() as connection:
        repository = SqlMeetingRepository(connection)
        repository.reserve_write_request(
            principal, MEETINGS_CREATE_NAME, key, DIGEST, created_at=T0
        )
        repository.insert_series(principal, series)
        repository.insert_series_history(
            principal,
            MeetingSeriesHistoryView(
                series_history_id=issue_identifier(IdKind.MEETING_SERIES_HISTORY),
                meeting_series_id=series.meeting_series_id,
                action=MeetingHistoryAction.CREATE,
                actor=MeetingActor.PRINCIPAL,
                outcome=MeetingOutcome.APPLIED,
                before_version=0,
                after_version=1,
                occurred_at=T0,
                recorded_at=T0,
            ),
            idempotency_key=key,
            request_digest=DIGEST,
        )
        record = MeetingRecord(
            **{
                **{name: getattr(_meeting(), name) for name in MeetingRecord.__dataclass_fields__},
                "meeting_series_id": series.meeting_series_id,
            }
        )
        repository.insert_meeting(principal, record)
        repository.insert_attendees(
            principal,
            record.meeting_id,
            [
                MeetingAttendeeRecord(
                    attendee_id=issue_identifier(IdKind.MEETING_ATTENDEE),
                    attendee=NormalizedAttendee(
                        display_name=None,
                        email_normalized=None,
                        entity_id=stage.lower_entity_id,
                        is_organizer=True,
                        response_status=AttendeeResponseStatus.ACCEPTED,
                    ),
                )
            ],
            added_at=T0,
        )
        receipt = _receipt(record.meeting_id)
        repository.insert_meeting_history(
            principal,
            receipt,
            meeting_series_id=series.meeting_series_id,
            idempotency_key=key,
            request_digest=DIGEST,
        )
        repository.insert_note_version(
            principal,
            MeetingNoteRecord(
                note_version_id=issue_identifier(IdKind.MEETING_NOTE_VERSION),
                meeting_id=record.meeting_id,
                version_number=1,
                supersedes_note_version_id=None,
                content_markdown="Synthetic minutes",
                content_sha256=note_content_sha256("Synthetic minutes"),
                meeting_history_id=receipt.history_id,
                recorded_at=T0,
            ),
        )
        raise InjectedError("the write failed after every row was written")

    with engine.connect() as connection:
        for table in (
            meeting_write_requests,
            meeting_series,
            meeting_series_history,
            meetings,
            meeting_attendees,
            meeting_history,
            meeting_note_versions,
        ):
            assert connection.execute(select(func.count()).select_from(table)).scalar_one() == 0
    with engine.begin() as connection:
        assert (
            SqlMeetingRepository(connection).reserve_write_request(
                principal, MEETINGS_CREATE_NAME, key, DIGEST, created_at=T0
            )
            is None
        )


# ------------------------------------------------------------- parent locks


def test_the_meeting_parent_lock_serializes_writers(engine: Engine, stage: Stage) -> None:
    """AC-030/AC-043: the second writer waits at the parent and then sees the first's write."""
    principal = stage.principal_id
    record = _committed_meeting(engine, principal)
    with engine.connect() as holder, ThreadPoolExecutor(max_workers=1) as pool:
        transaction = holder.begin()
        repository = SqlMeetingRepository(holder)
        locked = repository.lock_meeting_for_update(principal, record.meeting_id)
        assert locked is not None
        assert locked.version == 1

        def second_writer(other: SqlMeetingRepository) -> int:
            view = other.lock_meeting_for_update(principal, record.meeting_id)
            assert view is not None
            return view.version

        waiter: Future[int] = pool.submit(_in_own_transaction, engine, second_writer)
        _wait_until_blocked(engine, waiter)
        repository.update_meeting(principal, _meeting(record.meeting_id, version=2))
        repository.insert_meeting_history(
            principal,
            _receipt(record.meeting_id, update=True, before=1, after=2),
            meeting_series_id=None,
            idempotency_key="update",
            request_digest=DIGEST,
        )
        transaction.commit()
        # A stale writer that read version 1 before the lock would now be refused
        # by `expected_version` in the application; here it simply sees 2.
        assert waiter.result(timeout=JOIN_TIMEOUT_SECONDS) == 2


def test_the_series_parent_lock_serializes_writers(engine: Engine, stage: Stage) -> None:
    principal = stage.principal_id
    series = MeetingSeriesView(
        meeting_series_id=issue_identifier(IdKind.MEETING_SERIES),
        title="Before",
        version=1,
        created_at=T0,
        updated_at=T0,
    )
    with engine.begin() as connection:
        SqlMeetingRepository(connection).insert_series(principal, series)
    with engine.connect() as holder, ThreadPoolExecutor(max_workers=1) as pool:
        transaction = holder.begin()
        repository = SqlMeetingRepository(holder)
        assert repository.lock_series_for_update(principal, series.meeting_series_id) is not None

        def second_writer(other: SqlMeetingRepository) -> tuple[str, int]:
            view = other.lock_series_for_update(principal, series.meeting_series_id)
            assert view is not None
            return view.title, view.version

        waiter: Future[tuple[str, int]] = pool.submit(_in_own_transaction, engine, second_writer)
        _wait_until_blocked(engine, waiter)
        repository.update_series_title(
            principal,
            series.meeting_series_id,
            title="After",
            version=2,
            updated_at=T0 + timedelta(minutes=1),
        )
        transaction.commit()
        assert waiter.result(timeout=JOIN_TIMEOUT_SECONDS) == ("After", 2)


def test_an_occurrence_read_of_its_series_takes_no_lock(engine: Engine, stage: Stage) -> None:
    """Section 35.10: occurrence create reads its existing series without locking it."""
    principal = stage.principal_id
    series = MeetingSeriesView(
        meeting_series_id=issue_identifier(IdKind.MEETING_SERIES),
        title="Unlocked",
        version=1,
        created_at=T0,
        updated_at=T0,
    )
    with engine.begin() as connection:
        SqlMeetingRepository(connection).insert_series(principal, series)
    with engine.connect() as holder:
        transaction = holder.begin()
        assert (
            SqlMeetingRepository(holder).read_owned_series(principal, series.meeting_series_id)
            is not None
        )
        with engine.connect() as probe:
            probe.execute(
                select(meeting_series.c.meeting_series_id)
                .where(meeting_series.c.meeting_series_id == series.meeting_series_id)
                .with_for_update(nowait=True)
            ).one()
            probe.rollback()
        transaction.rollback()


# --------------------------------------------------------------- entity locks


def test_person_entities_are_share_locked_in_ascending_id_order(
    engine: Engine, stage: Stage
) -> None:
    """AC-043: the lower id is locked before the writer blocks on the upper one."""
    principal = stage.principal_id
    with engine.connect() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        blocking = blocker.begin()
        blocker.execute(
            select(entities.c.entity_id)
            .where(entities.c.entity_id == stage.upper_entity_id)
            .with_for_update()
        ).one()
        # Requested upper-first; the repository must still lock lower-first.
        waiter: Future[tuple[str, ...]] = pool.submit(
            _in_own_transaction,
            engine,
            lambda other: tuple(
                state.entity_id
                for state in other.share_lock_person_entities(
                    principal, [stage.upper_entity_id, stage.lower_entity_id]
                )
            ),
        )
        _wait_until_blocked(engine, waiter)
        with engine.connect() as probe:
            with pytest.raises(OperationalError):
                probe.execute(
                    select(entities.c.entity_id)
                    .where(entities.c.entity_id == stage.lower_entity_id)
                    .with_for_update(nowait=True)
                ).one()
            probe.rollback()
            # A share lock is compatible with another share lock.
            probe.execute(
                select(entities.c.entity_id)
                .where(entities.c.entity_id == stage.lower_entity_id)
                .with_for_update(read=True, nowait=True)
            ).one()
            probe.rollback()
        blocking.rollback()
        assert waiter.result(timeout=JOIN_TIMEOUT_SECONDS) == (
            stage.lower_entity_id,
            stage.upper_entity_id,
        )


def test_two_writers_naming_the_same_entities_in_opposite_orders_do_not_deadlock(
    engine: Engine, stage: Stage
) -> None:
    """AC-043: parent first, then sorted Person FOR SHARE, then children -- no cycle.

    Review F-02: two Meeting writers alone cannot deadlock, because `FOR SHARE`
    locks are mutually compatible, so a test of only those would pass with
    unsorted locking too. The opposite-order party here is therefore a
    conflicting one: an Entity writer taking `FOR UPDATE` in ascending id order,
    as every sorted-order writer does. It holds the lower Entity first; the
    Meeting writer names the Entities upper-first and blocks. With the sorted
    lock order the Meeting writer holds nothing yet, so the Entity writer's
    `FOR UPDATE` of the upper row is granted at once and both finish. With the
    order violated the Meeting writer already share-holds the upper row, the
    Entity writer waits on it, and PostgreSQL reports a deadlock -- which fails
    this test from whichever side it is raised on.
    """
    principal = stage.principal_id
    meeting = _committed_meeting(engine, principal)

    def meeting_writer(repository: SqlMeetingRepository) -> int:
        key = "opposite-order"
        assert (
            repository.reserve_write_request(
                principal, MEETINGS_UPDATE_NAME, key, DIGEST, created_at=T0
            )
            is None
        )
        view = repository.lock_meeting_for_update(principal, meeting.meeting_id)
        assert view is not None
        order = [stage.upper_entity_id, stage.lower_entity_id]
        locked = repository.share_lock_person_entities(principal, order)
        assert [state.entity_id for state in locked] == sorted(order)
        repository.insert_attendees(
            principal,
            meeting.meeting_id,
            [
                MeetingAttendeeRecord(
                    attendee_id=issue_identifier(IdKind.MEETING_ATTENDEE),
                    attendee=NormalizedAttendee(
                        display_name=None,
                        email_normalized=None,
                        entity_id=entity_id,
                        is_organizer=False,
                        response_status=AttendeeResponseStatus.UNKNOWN,
                    ),
                )
                for entity_id in sorted(order)
            ],
            added_at=T0,
        )
        receipt = _receipt(meeting.meeting_id, update=True, before=1, after=2)
        repository.update_meeting(principal, _meeting(meeting.meeting_id, version=2))
        repository.insert_meeting_history(
            principal,
            receipt,
            meeting_series_id=None,
            idempotency_key=key,
            request_digest=DIGEST,
        )
        repository.complete_write_request(
            principal,
            MEETINGS_UPDATE_NAME,
            key,
            request_digest=DIGEST,
            meeting_id=meeting.meeting_id,
            meeting_series_id=None,
            meeting_history_id=receipt.history_id,
            meeting_series_history_id=None,
            result_version=2,
            completed_at=T0,
        )
        return 2

    def lock_entity(connection: Connection, entity_id: str) -> None:
        connection.execute(
            select(entities.c.entity_id).where(entities.c.entity_id == entity_id).with_for_update()
        ).one()

    with engine.connect() as entity_writer, ThreadPoolExecutor(max_workers=1) as pool:
        transaction = entity_writer.begin()
        _lock_timeout(entity_writer)
        # Ascending: the lower Entity first.
        lock_entity(entity_writer, stage.lower_entity_id)
        waiter: Future[int] = pool.submit(_in_own_transaction, engine, meeting_writer)
        _wait_until_blocked(engine, waiter)
        # Then the upper Entity. Granted at once only if the Meeting writer, which
        # named it first, did not lock it before blocking on the lower one.
        lock_entity(entity_writer, stage.upper_entity_id)
        transaction.commit()
        assert waiter.result(timeout=JOIN_TIMEOUT_SECONDS) == 2

    with engine.connect() as connection:
        view = SqlMeetingRepository(connection).read_meeting(principal, meeting.meeting_id)
    assert view is not None
    assert view.version == 2
    assert sorted(a.entity_id or "" for a in view.attendees) == sorted(
        [stage.lower_entity_id, stage.upper_entity_id]
    )


def test_an_incomplete_reservation_committed_by_its_owner_is_an_internal_failure(
    engine: Engine, stage: Stage
) -> None:
    """Section 35.7: a same-digest winner still incomplete after it ended is never stolen."""
    principal = stage.principal_id
    with engine.begin() as connection:
        SqlMeetingRepository(connection).reserve_write_request(
            principal, MEETINGS_CREATE_NAME, "abandoned", DIGEST, created_at=T0
        )
    with pytest.raises(RepositoryFailureError):
        _in_own_transaction(
            engine,
            lambda repository: repository.reserve_write_request(
                principal, MEETINGS_CREATE_NAME, "abandoned", DIGEST, created_at=T0
            ),
        )
