"""T-13 (WP-RE-05): Meeting Record Events under concurrency (RE-AC-052, RE-AC-053).

Marked `database` only (auto `database_clone`: every test here runs several
connections), so it routes to `database-current-head`. It is deliberately not
colocated with `test_meeting_writes.py` and so carries no `recovery` marker
(transaction matrix T-13). Every connection of the runtime carries a
`lock_timeout`, so a lock this module does not expect fails loudly instead of
hanging the tier; a deadlock (40P01) or a lock timeout in any run here is stop
N14.

What is proved, on the production `ApplicationService` over the general unit of
work (U1):

* **series then meeting, allocator last** -- a create that makes a new series
  and share-locks its attendee Entities finishes all of its domain work before
  it waits on the Principal's allocator row, then commits its series event and
  the Meeting event caused by it as one contiguous batch;
* **a domain wait holds no allocator** -- while one create waits on an attendee
  Entity lock, another writer of the same Principal commits its events;
* **opposite-order attendee writers** -- writers naming the same Person
  Entities in opposite request orders (updates, a new-series create, an
  occurrence create) race a series retitle for several rounds with no
  deadlock, no lock timeout and no refusal, and the committed feed is gap-free
  with every transaction's events one contiguous batch and every Meeting event
  caused only by its own transaction's series event.

Every identity here is synthetic.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, event, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError
from tests.concurrency.test_meeting_writes import _wait_until_blocked
from tests.contract.test_meeting_mcp import Partition, _insert_partition
from tests.database.test_task_record_events import Runtime, assert_gap_free, feed

from my_pa.application.commands import Command, CreateMeeting, UpdateMeeting, UpdateMeetingSeries
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.infrastructure.persistence.tables import entities, record_event_sequences

pytestmark = pytest.mark.database

START: Final = datetime(2026, 10, 1, 13, tzinfo=UTC)
LOCK_TIMEOUT: Final = "20s"
JOIN_TIMEOUT_SECONDS: Final = 60.0
ROUNDS: Final = 3


@dataclass
class Scene:
    runtime: Runtime
    mine: Partition

    @property
    def principal_id(self) -> str:
        return self.mine.principal.principal_id

    @property
    def engine(self) -> Engine:
        return self.runtime.work_engine

    @property
    def lower(self) -> dict[str, object]:
        return {"entity_id": self.mine.person_ids[0]}

    @property
    def upper(self) -> dict[str, object]:
        return {"entity_id": self.mine.person_ids[1]}

    def invoke(self, command: Command) -> ResponseEnvelope:
        return self.runtime.invoke(command, principal_id=self.principal_id)

    def ok(self, command: Command) -> dict[str, Any]:
        return _ok(self.invoke(command))


def _ok(response: ResponseEnvelope) -> dict[str, Any]:
    """Stop N14 surfaces here: a deadlock or lock timeout is an error envelope."""
    assert response.error is None, f"STOP N14 candidate or refusal: {response.error}"
    assert response.result is not None
    return response.result


@pytest.fixture
def scene(disposable_database: str) -> Iterator[Scene]:
    runtime = Runtime(disposable_database)

    @event.listens_for(runtime.work_engine, "connect")
    def _impatient(dbapi_connection: object, _record: object) -> None:
        with dbapi_connection.cursor() as cursor:  # type: ignore[attr-defined]
            cursor.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")

    try:
        with runtime.work_engine.begin() as connection:
            mine = _insert_partition(connection)
        yield Scene(runtime=runtime, mine=mine)
    finally:
        runtime.close()


def _create(key: str, **extra: object) -> CreateMeeting:
    return CreateMeeting(
        title="Synthetic sync",
        start_at=START,
        timezone_name="UTC",
        idempotency_key=key,
        **extra,  # type: ignore[arg-type]
    )


def _batches(scene: Scene) -> list[list[dict[str, Any]]]:
    """Every transaction's events, as contiguous allocator batches in feed order."""
    assert_gap_free(scene.engine, scene.principal_id)
    with scene.engine.connect() as connection:
        writer = dict(
            connection.execute(
                text("SELECT event_id, xmin::text FROM knowledge.record_events")
            ).all()
        )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in feed(scene.engine, scene.principal_id):
        grouped.setdefault(writer[item["event_id"]], []).append(item)
    for events in grouped.values():
        numbers = [item["sequence_number"] for item in events]
        assert numbers == list(range(numbers[0], numbers[0] + len(numbers))), numbers
    return sorted(grouped.values(), key=lambda events: events[0]["sequence_number"])


def _assert_series_then_meeting(batch: list[dict[str, Any]]) -> None:
    """RE-AC-053: the series event first, the Meeting event caused by it."""
    assert len(batch) == 2, batch
    series_event, meeting_event = batch
    assert series_event["record_family"] == "meeting_series"
    assert series_event["event_kind"] == "created"
    assert series_event["causation_event_id"] is None
    assert meeting_event["record_family"] == "meeting"
    assert meeting_event["event_kind"] == "created"
    assert meeting_event["causation_event_id"] == series_event["event_id"]


def _is_share_locked(probe: Connection, entity_id: str) -> bool:
    """Whether another transaction holds a lock that refuses `FOR UPDATE NOWAIT`."""
    try:
        probe.execute(
            select(entities.c.entity_id)
            .where(entities.c.entity_id == entity_id)
            .with_for_update(nowait=True)
        ).one()
    except OperationalError:
        return True
    finally:
        probe.rollback()
    return False


# ---- series then meeting, allocator last --------------------------------------


def test_a_series_create_does_all_domain_work_before_waiting_on_the_allocator(
    scene: Scene,
) -> None:
    scene.ok(_create("t13-seed"))  # the Principal's allocator row now exists
    with scene.engine.connect() as holder, ThreadPoolExecutor(max_workers=1) as pool:
        transaction = holder.begin()
        holder.execute(
            select(record_event_sequences.c.principal_id)
            .where(record_event_sequences.c.principal_id == scene.principal_id)
            .with_for_update()
        ).one()
        waiter: Future[ResponseEnvelope] = pool.submit(
            scene.invoke,
            _create(
                "t13-series",
                series_title="Synthetic series",
                attendees=(scene.upper, scene.lower),
            ),
        )
        _wait_until_blocked(scene.engine, waiter)
        # The waiter already share-locked both attendee Entities: its domain
        # work is done, and only the allocator is left.
        with scene.engine.connect() as probe:
            for entity_id in scene.mine.person_ids:
                assert _is_share_locked(probe, entity_id), (
                    "the create waited on the allocator before its attendee locks"
                )
        transaction.rollback()
        created = _ok(waiter.result(timeout=JOIN_TIMEOUT_SECONDS))
    batches = _batches(scene)
    assert len(batches) == 2, batches
    seed, batch = batches
    assert [item["record_family"] for item in seed] == ["meeting"]
    _assert_series_then_meeting(batch)
    assert batch[0]["record_id"] == created["series"]["meeting_series_id"]
    assert batch[1]["record_id"] == created["meeting"]["meeting_id"]


def test_a_create_waiting_on_an_attendee_lock_holds_no_allocator(scene: Scene) -> None:
    scene.ok(_create("t13-seed"))
    with scene.engine.connect() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        blocking = blocker.begin()
        blocker.execute(
            select(entities.c.entity_id)
            .where(entities.c.entity_id == scene.mine.person_ids[1])
            .with_for_update()
        ).one()
        waiter: Future[ResponseEnvelope] = pool.submit(
            scene.invoke,
            _create(
                "t13-waiting",
                series_title="Synthetic series",
                attendees=(scene.lower, scene.upper),
            ),
        )
        _wait_until_blocked(scene.engine, waiter)
        # Another writer of the same Principal flushes and commits meanwhile.
        other = scene.ok(_create("t13-other", series_title="Other series"))
        assert not waiter.done()
        blocking.rollback()
        waiting = _ok(waiter.result(timeout=JOIN_TIMEOUT_SECONDS))
    batches = _batches(scene)
    assert len(batches) == 3, batches
    seed, first, second = batches
    assert len(seed) == 1
    _assert_series_then_meeting(first)
    _assert_series_then_meeting(second)
    assert first[1]["record_id"] == other["meeting"]["meeting_id"]
    assert second[1]["record_id"] == waiting["meeting"]["meeting_id"]


# ---- opposite-order attendee writers -------------------------------------------


def _race(scene: Scene, *commands: Command) -> list[ResponseEnvelope]:
    """Invoke every command at once, one thread each, released by a barrier."""
    barrier = threading.Barrier(len(commands), timeout=JOIN_TIMEOUT_SECONDS)

    def run(command: Command) -> ResponseEnvelope:
        barrier.wait()
        return scene.invoke(command)

    with ThreadPoolExecutor(max_workers=len(commands)) as pool:
        futures = [pool.submit(run, command) for command in commands]
        return [future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in futures]


def test_opposite_order_attendee_writers_race_a_retitle_without_deadlock(scene: Scene) -> None:
    lower, upper = scene.lower, scene.upper
    first = scene.ok(_create("t13-m1", attendees=(lower,)))
    second = scene.ok(_create("t13-m2", attendees=(upper,)))
    series = scene.ok(_create("t13-s", series_title="Raced series"))
    series_id = series["series"]["meeting_series_id"]
    m1, m2 = first["meeting"]["meeting_id"], second["meeting"]["meeting_id"]
    orders = ((upper, lower), (lower, upper))
    for round_number in range(ROUNDS):
        version = round_number + 1
        forward, backward = orders[round_number % 2], orders[(round_number + 1) % 2]
        # Each round really changes each Meeting's attendee set: a single
        # attendee one round, both the next.
        m1_set = forward if round_number % 2 == 0 else (lower,)
        m2_set = backward if round_number % 2 == 0 else (upper,)
        outcomes = _race(
            scene,
            UpdateMeeting(
                meeting_id=m1,
                expected_version=version,
                idempotency_key=f"t13-u1-{round_number}",
                attendees_replace=m1_set,
            ),
            UpdateMeeting(
                meeting_id=m2,
                expected_version=version,
                idempotency_key=f"t13-u2-{round_number}",
                attendees_replace=m2_set,
            ),
            _create(
                f"t13-new-{round_number}",
                series_title=f"New series {round_number}",
                attendees=forward,
            ),
            _create(f"t13-occ-{round_number}", meeting_series_id=series_id, attendees=backward),
            UpdateMeetingSeries(
                meeting_series_id=series_id,
                expected_version=version,
                idempotency_key=f"t13-rt-{round_number}",
                title=f"Raced series {round_number}",
            ),
        )
        for outcome in outcomes:
            _ok(outcome)

    batches = _batches(scene)
    # Three setup transactions, then five per round, one batch each.
    assert len(batches) == 3 + 5 * ROUNDS
    event_ids = {item["event_id"] for batch in batches for item in batch}
    for batch in batches:
        if len(batch) == 2:
            _assert_series_then_meeting(batch)
        else:
            (only,) = batch
            # Nothing outside a new-series batch is caused by anything.
            assert only["causation_event_id"] is None
    for batch in batches:
        for item in batch:
            cause = item["causation_event_id"]
            assert cause is None or cause in {other["event_id"] for other in batch}
            assert cause is None or cause in event_ids
    kinds = [(item["record_family"], item["event_kind"]) for batch in batches for item in batch]
    assert kinds.count(("meeting_series", "updated")) == ROUNDS
    assert kinds.count(("meeting", "updated")) == 2 * ROUNDS
    assert kinds.count(("meeting_series", "created")) == 1 + ROUNDS
    assert kinds.count(("meeting", "created")) == 3 + 2 * ROUNDS
