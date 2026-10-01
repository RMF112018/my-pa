"""RECR-2: a new consumer's no-gap bootstrap, on a real database (RECR-AC-009..011).

Marked `database` (auto `database_clone`: every test runs several connections),
routed to `database-current-head`. The consumer under test is a small in-test
class implementing the documented contract
(`docs/specs/record-event-consumer-contract-v0.1.md`, section "Bootstrap"):

1. **W0** -- one `record_events.list` call with no cursor, under the page size
   and family narrowing the consumer will consume with; keep
   `high_watermark_cursor` and discard the events;
2. **snapshot** -- enumerate the current records through the existing reads
   (`tasks.list` paged, then `tasks.read` and `tasks.comments.list` per Task),
   each in its own transaction;
3. **process** -- upsert by `(family, record_id)`;
4. **delta** -- consume `record_events.list` from W0 until `next_cursor` is
   null, rereading each event's record through its family's read, keyed by
   `routing_record_id` for a routed family (`task_comment` routes to its Task).

The writers are the production `ApplicationService` over the production units
of work; the interleavings use the deterministic allocator gate and lock-wait
probe of `tests/database/test_record_events_bootstrap_race.py`, never a sleep.

* **RECR-AC-009** `test_a_write_in_flight_at_w0_is_seen_by_the_delta` -- a
  comment paused at the allocator (uncommitted, holding the allocator row) is
  absent from W0 and from the snapshot, and the delta delivers it.
* **RECR-AC-010** `test_a_write_committed_between_w0_and_the_snapshot_is_seen_by_both`
  -- the snapshot already holds it; the delta's event is applied again as a
  no-op, with no duplicate record.
* **RECR-AC-011** `test_a_write_committed_during_snapshot_enumeration_is_seen_by_the_delta`
  -- between two snapshot pages, a Task already read is updated and gains a
  comment; both events come after W0 and the delta delivers them, each once.

Every test ends with the consumer's state equal to a fresh canonical
enumeration, no event at or before W0 consumed, every event after W0 consumed
exactly once, and a null final `next_cursor`. Every identity is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Final

import pytest

from my_pa.application.commands import CreateTaskComment, ListTaskComments, ListTasks, ReadTask
from my_pa.application.record_events import list_record_events, read_cursor
from my_pa.contracts.v1.record_events import RecordEventListView
from my_pa.domain.identity.operation import Capability
from my_pa.domain.record_events import RecordEventFamily
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.test_record_events_bootstrap_race import (
    JOIN_TIMEOUT_SECONDS,
    AllocatorGate,
    _named,
    _paused,
    _update,
    _version,
)
from tests.database.test_task_record_events import PRINCIPAL_A, Runtime, _create, feed

pytestmark = pytest.mark.database

ALL: Final = frozenset(Capability)
#: The consumer's page size: small, so every delta crosses several pages.
PAGE_SIZE: Final = 2

type Key = tuple[str, str]


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[Runtime]:
    composed = Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _comment(runtime: Runtime, task_id: str, key: str) -> str:
    created = runtime.ok(CreateTaskComment(task_id=task_id, body="Synthetic", idempotency_key=key))
    return str(created["comment"]["comment_id"])


class Consumer:
    """The documented bootstrap, over the production list and the production reads."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.state: dict[Key, dict[str, Any]] = {}
        self.consumed: list[str] = []
        self.w0_event: str | None = None
        self.final: RecordEventListView | None = None

    # -- the feed -------------------------------------------------------------------

    def _list(self, cursor: str | None) -> RecordEventListView:
        engine = self.runtime.work_engine
        with SqlAlchemyUnitOfWork(engine, audit=SqlAlchemyAuditSink(engine)) as uow:
            return list_record_events(
                uow.record_event_reader,
                principal_id=PRINCIPAL_A,
                available_capabilities=ALL,
                capability_grants=None,
                record_families=None,
                page_size=PAGE_SIZE,
                cursor=cursor,
            )

    def take_w0(self) -> str:
        """Step 1: the high watermark, under the consumption page size and narrowing."""
        w0 = self._list(None).high_watermark_cursor
        read = read_cursor(w0)
        assert read is not None
        self.w0_event = read[1]
        return w0

    def delta(self, cursor: str) -> None:
        """Step 4: everything after W0, each event reread through its family's read."""
        while True:
            page = self._list(cursor)
            for item in page.events:
                self.consumed.append(item.event_id)
                if item.record_family is RecordEventFamily.TASK:
                    self._upsert_task(item.record_id)
                elif item.record_family is RecordEventFamily.TASK_COMMENT:
                    assert item.routing_family is RecordEventFamily.TASK
                    assert item.routing_record_id is not None
                    self._upsert_comments(item.routing_record_id)
                else:  # pragma: no cover - this world writes nothing else
                    pytest.fail(f"unexpected family {item.record_family}")
            self.final = page
            if page.next_cursor is None:
                return
            cursor = page.next_cursor

    # -- the snapshot ---------------------------------------------------------------

    def _upsert_task(self, task_id: str) -> None:
        self.state[("task", task_id)] = self.runtime.ok(ReadTask(task_id=task_id))["task"]

    def _upsert_comments(self, task_id: str) -> None:
        for comment in self.runtime.ok(ListTaskComments(task_id=task_id))["comments"]:
            self.state[("task_comment", comment["comment_id"])] = comment

    def snapshot(self, between_pages: Callable[[int], None] = lambda _: None) -> None:
        """Step 2 and 3: page the Tasks one at a time; per Task, its record and comments."""
        after: str | None = None
        page_number = 0
        while True:
            envelope = self.runtime.invoke(ListTasks(page_size=1, after=after))
            assert envelope.error is None, envelope.error
            assert envelope.result is not None and envelope.disclosure is not None
            for task in envelope.result["tasks"]:
                self._upsert_task(task["task_id"])
                self._upsert_comments(task["task_id"])
            page_number += 1
            after = envelope.disclosure.truncation.next_cursor
            if after is None:
                return
            between_pages(page_number)

    # -- the algorithm --------------------------------------------------------------

    def bootstrap(
        self,
        *,
        after_snapshot: Callable[[], None] = lambda: None,
        between_pages: Callable[[int], None] = lambda _: None,
    ) -> None:
        w0 = self.take_w0()
        self.snapshot(between_pages)
        after_snapshot()
        self.delta(w0)


def canonical(runtime: Runtime) -> dict[Key, dict[str, Any]]:
    fresh = Consumer(runtime)
    fresh.snapshot()
    return fresh.state


def assert_converged(consumer: Consumer, runtime: Runtime) -> None:
    """The common end state of every interleaving."""
    assert consumer.state == canonical(runtime)
    assert consumer.final is not None
    assert consumer.final.next_cursor is None
    events = [row["event_id"] for row in feed(runtime.work_engine)]
    after_w0 = (
        events if consumer.w0_event is None else events[events.index(consumer.w0_event) + 1 :]
    )
    # Nothing at or before W0, everything after it, each exactly once.
    assert consumer.consumed == after_w0
    assert len(set(consumer.consumed)) == len(consumer.consumed)


# ---- RECR-AC-009 -------------------------------------------------------------------


def test_a_write_in_flight_at_w0_is_seen_by_the_delta(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_x = _create(runtime, "recr02-boot-x")["task"]["task_id"]
    _create(runtime, "recr02-boot-y")
    gate = AllocatorGate()
    gate.install(monkeypatch)
    release = gate.hold("writer-a")
    consumer = Consumer(runtime)
    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(
            _named("writer-a", lambda: _comment(runtime, task_x, "recr02-boot-inflight"))
        )
        _paused(gate, "writer-a", writer)
        committed_before = {row["event_id"] for row in feed(runtime.work_engine)}

        def release_writer() -> None:
            # The snapshot ran while A was uncommitted: X has no comment yet.
            assert not [key for key in consumer.state if key[0] == "task_comment"]
            release.set()
            writer.result(timeout=JOIN_TIMEOUT_SECONDS)

        consumer.bootstrap(after_snapshot=release_writer)
    comment_a = writer.result()
    # The final state first: losing A's write is the failure this test exists for.
    assert ("task_comment", comment_a) in consumer.state
    assert_converged(consumer, runtime)
    assert consumer.w0_event in committed_before
    events = {row["event_id"]: row for row in feed(runtime.work_engine)}
    delivered = [events[event_id] for event_id in consumer.consumed]
    assert [(row["record_family"], row["record_id"]) for row in delivered] == [
        ("task_comment", comment_a)
    ]
    assert consumer.state[("task_comment", comment_a)]["task_id"] == task_x


# ---- RECR-AC-010 -------------------------------------------------------------------


def test_a_write_committed_between_w0_and_the_snapshot_is_seen_by_both(
    runtime: Runtime,
) -> None:
    _create(runtime, "recr02-both-x")
    task_y = _create(runtime, "recr02-both-y")["task"]["task_id"]
    version = _version(runtime, task_y)
    consumer = Consumer(runtime)
    w0 = consumer.take_w0()
    _update(runtime, task_y, version, "recr02-both-update", "Updated between")
    consumer.snapshot()
    # The snapshot already holds Y at the new version.
    assert consumer.state[("task", task_y)]["version"] == version + 1
    before_delta = dict(consumer.state)
    consumer.delta(w0)
    # The delta's event is the same version, applied again as a no-op.
    events = {row["event_id"]: row for row in feed(runtime.work_engine)}
    assert [
        (events[event_id]["record_id"], events[event_id]["record_version"])
        for event_id in consumer.consumed
    ] == [(task_y, version + 1)]
    assert consumer.state == before_delta
    assert_converged(consumer, runtime)


# ---- RECR-AC-011 -------------------------------------------------------------------


def test_a_write_committed_during_snapshot_enumeration_is_seen_by_the_delta(
    runtime: Runtime,
) -> None:
    for index in range(3):
        _create(runtime, f"recr02-during-{index}")
    consumer = Consumer(runtime)
    touched: list[str] = []

    def write_between(page_number: int) -> None:
        if page_number != 1:
            return
        # The Task page 1 returned is already in the consumer's state.
        (task_key,) = [key for key in consumer.state if key[0] == "task"]
        task_id = task_key[1]
        _update(runtime, task_id, _version(runtime, task_id), "recr02-during-upd", "Moved")
        touched.append(_comment(runtime, task_id, "recr02-during-comment"))
        touched.append(task_id)

    consumer.bootstrap(between_pages=write_between)
    comment_id, task_id = touched
    events = {row["event_id"]: row for row in feed(runtime.work_engine)}
    delivered = [
        (events[event_id]["record_family"], events[event_id]["record_id"])
        for event_id in consumer.consumed
    ]
    assert delivered == [("task", task_id), ("task_comment", comment_id)]
    assert consumer.state[("task", task_id)]["title"] == "Moved"
    assert ("task_comment", comment_id) in consumer.state
    assert_converged(consumer, runtime)
