"""WP-RE-01: the Record Event allocator under actual concurrency (T-02/03/04/07/09).

Marked `database` (auto `database_clone`: every test uses several connections)
and `recovery`, so it is routed to `database-recovery`. The precedent is
`tests/concurrency/test_meeting_writes.py`: overlapping transactions run on
separate connections, the waiting one in a thread, and the test observes
PostgreSQL reporting it blocked before letting the holder finish. Every
transaction carries a `lock_timeout`, so a build that takes a lock this module
does not expect fails loudly instead of hanging the tier.

* **T-02** (RE-AC-009, 010) -- concurrent batches for one Principal are each
  contiguous, pairwise disjoint, and together exactly `1..sum`.
* **T-03** (RE-AC-007, 010) -- two first batches for a Principal with no
  allocator row: one creates the row, the other waits for it and continues after
  it; neither sees a raw conflict.
* **T-04** (RE-AC-010) -- a batch held open for one Principal does not block
  another Principal's batch.
* **T-07** (RE-AC-066's substrate) -- a later batch for the same Principal
  cannot commit while an earlier one is uncommitted, so the committed feed is
  always a gap-free prefix. Prove-red: an allocator in its own autocommit
  transaction lets the later batch commit past the gap.
* **T-09** (RE-AC-014, 043) -- a domain lock taken before the allocator cannot
  invert against it: a composite that locks R1 then R2 while another
  transaction holds R2 and flushes completes with no deadlock. Prove-red: a
  per-substep allocation (allocate while still taking domain locks) deadlocks
  (40P01) or times out.

A deadlock or `lock_timeout` in an unmutated run is stop N14. Every identity here
is synthetic.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Final

import pytest
from sqlalchemy import Connection, Engine, insert, select, text

from my_pa.contracts.ports import AuditSink
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.record_events import (
    RecordEventActorClass,
    RecordEventDraft,
    RecordEventFamily,
    RecordEventKind,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.record_events import SqlRecordEventWriter
from my_pa.infrastructure.persistence.tables import meeting_series, record_events
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = [pytest.mark.database, pytest.mark.recovery]

WHEN: Final = datetime(2026, 9, 29, 12, tzinfo=UTC)
LOCK_TIMEOUT: Final = "20s"
JOIN_TIMEOUT_SECONDS: Final = 60.0
BLOCK_DEADLINE_SECONDS: Final = 15.0
#: The Principal-isolation test asserts *no* wait, so it runs with a short
#: timeout: a wrongly shared lock fails it in two seconds rather than twenty.
ISOLATION_LOCK_TIMEOUT: Final = "2s"


class _Audit(AuditSink):
    def record(self, event: object) -> None:  # type: ignore[override]
        del event


@pytest.fixture
def engine(db_engine: Engine) -> Engine:
    return db_engine


def _unit(engine: Engine) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(engine, audit=_Audit())


def _connection(unit: SqlAlchemyUnitOfWork) -> Connection:
    connection = unit._connection
    assert connection is not None
    return connection


def _lock_timeout(connection: Connection, value: str = LOCK_TIMEOUT) -> None:
    connection.execute(text(f"SET LOCAL lock_timeout = '{value}'"))


def _draft(principal_id: str, record_id: str | None = None) -> RecordEventDraft:
    return RecordEventDraft.issue(
        principal_id=principal_id,
        record_family=RecordEventFamily.MEETING_SERIES,
        record_id=record_id or issue_identifier(IdKind.MEETING_SERIES),
        event_kind=RecordEventKind.UPDATED,
        record_version=2,
        changed_fields=("title",),
        source_capability="meetings.series.update",
        actor_class=RecordEventActorClass.PRINCIPAL,
        classification=Classification.PRIVATE_LOCAL,
        occurred_at=WHEN,
    )


def _committed_sequences(engine: Engine, principal_id: str) -> list[int]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                select(record_events.c.sequence_number)
                .where(record_events.c.principal_id == principal_id)
                .order_by(record_events.c.sequence_number)
            ).scalars()
        )


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


def _flush_batch(engine: Engine, principal_id: str, size: int) -> list[str]:
    """One U1 transaction staging `size` drafts; returns their ids in stage order."""
    drafts = [_draft(principal_id) for _ in range(size)]
    unit = _unit(engine)
    with unit:
        _lock_timeout(_connection(unit))
        for draft in drafts:
            unit.record_events.stage(draft)
    return [draft.event_id for draft in drafts]


def _sequences_of(engine: Engine, event_ids: list[str]) -> list[int]:
    with engine.connect() as connection:
        by_id = dict(
            connection.execute(
                select(record_events.c.event_id, record_events.c.sequence_number).where(
                    record_events.c.event_id.in_(event_ids)
                )
            ).all()
        )
    return [by_id[event_id] for event_id in event_ids]


# ---- T-02 -------------------------------------------------------------------


def test_concurrent_batches_are_contiguous_and_disjoint(engine: Engine) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    _flush_batch(engine, principal, 1)  # the row exists; T-03 covers its creation race
    sizes = [3, 1, 4, 2, 5, 2, 3, 4]
    barrier = threading.Barrier(len(sizes), timeout=JOIN_TIMEOUT_SECONDS)

    def batch(size: int) -> list[str]:
        barrier.wait()
        return _flush_batch(engine, principal, size)

    with ThreadPoolExecutor(max_workers=len(sizes)) as pool:
        batches = [
            future.result(timeout=JOIN_TIMEOUT_SECONDS)
            for future in [pool.submit(batch, size) for size in sizes]
        ]
    seen: list[int] = []
    for event_ids in batches:
        numbers = _sequences_of(engine, event_ids)
        assert numbers == list(range(numbers[0], numbers[0] + len(numbers))), numbers
        seen.extend(numbers)
    assert sorted(seen) == list(range(2, 2 + sum(sizes)))
    assert _committed_sequences(engine, principal) == list(range(1, 2 + sum(sizes)))


# ---- T-03 -------------------------------------------------------------------


def test_first_row_race_for_a_new_principal(engine: Engine) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    holder_unit = _unit(engine)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with holder_unit:
            _lock_timeout(_connection(holder_unit))
            # Allocate inside the holder's transaction without finishing it: the
            # holder has created the Principal's row and holds its lock.
            assert SqlRecordEventWriter(_connection(holder_unit)).allocate(principal, 2) == 1
            waiter = pool.submit(_flush_batch, engine, principal, 3)
            _wait_until_blocked(engine, waiter)
        later = waiter.result(timeout=JOIN_TIMEOUT_SECONDS)
    assert _sequences_of(engine, later) == [3, 4, 5]


# ---- T-04 -------------------------------------------------------------------


def test_other_principal_is_not_blocked(engine: Engine) -> None:
    held, other = (issue_identifier(IdKind.PRINCIPAL) for _ in range(2))
    _flush_batch(engine, held, 1)
    _flush_batch(engine, other, 1)
    holder_unit = _unit(engine)
    with holder_unit:
        SqlRecordEventWriter(_connection(holder_unit)).allocate(held, 1)
        drafts = [_draft(other) for _ in range(2)]
        unit = _unit(engine)
        with unit:
            _lock_timeout(_connection(unit), ISOLATION_LOCK_TIMEOUT)
            for draft in drafts:
                unit.record_events.stage(draft)
        # The other Principal committed while `held`'s row lock is still held.
        assert _sequences_of(engine, [draft.event_id for draft in drafts]) == [2, 3]


# ---- T-07 -------------------------------------------------------------------


def test_out_of_order_commit_is_not_visible(engine: Engine) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    _flush_batch(engine, principal, 1)
    earlier = [_draft(principal) for _ in range(2)]
    holder_unit = _unit(engine)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with holder_unit:
            connection = _connection(holder_unit)
            _lock_timeout(connection)
            writer = SqlRecordEventWriter(connection)
            first = writer.allocate(principal, len(earlier))
            writer.insert(first, earlier)
            later = pool.submit(_flush_batch, engine, principal, 2)
            _wait_until_blocked(engine, later)
            # While the earlier batch is uncommitted, nothing past it is visible.
            assert _committed_sequences(engine, principal) == [1]
        later_ids = later.result(timeout=JOIN_TIMEOUT_SECONDS)
    assert _sequences_of(engine, later_ids) == [4, 5]
    assert _committed_sequences(engine, principal) == [1, 2, 3, 4, 5]


# ---- T-09 -------------------------------------------------------------------


def _series(engine: Engine, principal_id: str) -> str:
    series_id = issue_identifier(IdKind.MEETING_SERIES)
    with engine.begin() as connection:
        connection.execute(
            insert(meeting_series).values(
                meeting_series_id=series_id,
                principal_id=principal_id,
                title="Synthetic series",
                created_at=WHEN,
                updated_at=WHEN,
            )
        )
    return series_id


def _lock_row(connection: Connection, series_id: str) -> None:
    connection.execute(
        select(meeting_series.c.meeting_series_id)
        .where(meeting_series.c.meeting_series_id == series_id)
        .with_for_update()
    )


def _substep(unit: SqlAlchemyUnitOfWork, principal_id: str, series_id: str) -> None:
    """One composite substep: take the domain lock, then stage (memory only)."""
    _lock_row(_connection(unit), series_id)
    unit.record_events.stage(_draft(principal_id, series_id))


def test_domain_lock_then_allocator_cannot_invert(engine: Engine) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    first_row, second_row = _series(engine, principal), _series(engine, principal)
    _flush_batch(engine, principal, 1)
    holder_ready = threading.Event()
    release_holder = threading.Event()

    def holder() -> None:
        unit = _unit(engine)
        with unit:
            _lock_timeout(_connection(unit))
            # The holder takes its domain lock, then does more domain work while
            # the composite runs; it stages and allocates only at its exit.
            _lock_row(_connection(unit), second_row)
            holder_ready.set()
            assert release_holder.wait(JOIN_TIMEOUT_SECONDS)
            unit.record_events.stage(_draft(principal, second_row))
        # Exit: flush (allocator) and COMMIT.

    def composite() -> None:
        unit = _unit(engine)
        with unit:
            _lock_timeout(_connection(unit))
            _substep(unit, principal, first_row)
            _substep(unit, principal, second_row)  # waits for the holder

    with ThreadPoolExecutor(max_workers=2) as pool:
        held = pool.submit(holder)
        assert holder_ready.wait(JOIN_TIMEOUT_SECONDS)
        waiting = pool.submit(composite)
        _wait_until_blocked(engine, waiting)
        release_holder.set()
        # A deadlock (40P01) or a lock timeout surfaces here as the thread's error.
        for future in (held, waiting):
            future.result(timeout=JOIN_TIMEOUT_SECONDS)
    assert _committed_sequences(engine, principal) == [1, 2, 3, 4]
