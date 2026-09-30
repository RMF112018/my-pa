"""WP-RE-06 Phase 6A: bootstrap, snapshot and restricted-memory races (RE-AC-065/066/070).

Marked `database` (auto `database_clone`: every test runs several connections),
routed to `database-current-head`. The list is the use case over the production
unit of work's reader (the capability is registered in Phase 6B); the writers
are the production `ApplicationService` and `RelationshipMemoryService`.

* **RE-AC-066** `test_watermark_snapshot_resume_returns_concurrent_changes` --
  the ten-step bootstrap scenario (P2c section 8): a paused writer, a watermark,
  a blocked second writer, a snapshot, the releases, one more commit, a resume
  to exhaustion and the client algorithm, whose final state equals the
  canonical state.
* **R-07 / RE-AC-065** `test_page_and_watermark_share_one_snapshot` -- a writer
  commits the instant the page statement has executed; the watermark still
  equals the last returned event, because it came from the same statement.
* **R-08** `test_watermark_never_exceeds_an_uncommitted_lower_sequence` -- while
  one writer holds an allocated but uncommitted sequence, a later writer cannot
  commit above it, so the watermark cannot pass it and a resume misses nothing.
* **R-09 / RE-AC-070** `test_remote_watermark_excludes_restricted_memory` --
  a remote read withholds every event of a memory stored restricted *and* of a
  memory whose current version is restricted, from the page and from the
  watermark, with no count anywhere.

Every identity here is synthetic.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Final

import pytest
from sqlalchemy import Engine, event, text

from my_pa.application.commands import ReadTask, UpdateTask
from my_pa.application.record_events import list_record_events, read_cursor
from my_pa.contracts.v1.record_events import RecordEventListView
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.relationship.memory import MemoryKind
from my_pa.infrastructure.persistence import record_events as feed_persistence
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.test_relationship_memory_record_events import PRINCIPAL as MEMORY_PRINCIPAL
from tests.database.test_relationship_memory_record_events import _create as create_memory
from tests.database.test_relationship_memory_record_events import _revise as revise_memory
from tests.database.test_relationship_memory_record_events import staged  # noqa: F401
from tests.database.test_task_record_events import PRINCIPAL_A, Runtime, _create, feed

pytestmark = pytest.mark.database

ALL: Final = frozenset(Capability)
JOIN_TIMEOUT_SECONDS: Final = 60.0
BLOCK_DEADLINE_SECONDS: Final = 15.0


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[Runtime]:
    composed = Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def listing(
    engine: Engine,
    principal_id: str = PRINCIPAL_A,
    *,
    capability_grants: frozenset[tuple[Capability, Any]] | None = None,
    page_size: int = 50,
    cursor: str | None = None,
) -> RecordEventListView:
    with SqlAlchemyUnitOfWork(engine, audit=SqlAlchemyAuditSink(engine)) as uow:
        return list_record_events(
            uow.record_event_reader,
            principal_id=principal_id,
            available_capabilities=ALL,
            capability_grants=capability_grants,
            record_families=None,
            page_size=page_size,
            cursor=cursor,
        )


def watermark(view: RecordEventListView) -> str | None:
    read = read_cursor(view.high_watermark_cursor)
    assert read is not None
    return read[1]


class AllocatorGate:
    """A test-only pause seam: after `allocate` returns, before the insert.

    Threads named in `held` stop there until their event is set, still holding
    the allocator row lock of an uncommitted transaction.
    """

    def __init__(self) -> None:
        self.held: dict[str, threading.Event] = {}
        self.reached: dict[str, threading.Event] = {}

    def hold(self, name: str) -> threading.Event:
        self.reached[name] = threading.Event()
        release = self.held[name] = threading.Event()
        return release

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        original = feed_persistence.SqlRecordEventWriter.allocate
        gate = self

        def allocate(writer: Any, principal_id: str, count: int) -> int:  # noqa: ANN401
            first = original(writer, principal_id, count)
            name = threading.current_thread().name
            if name in gate.held:
                gate.reached[name].set()
                assert gate.held[name].wait(JOIN_TIMEOUT_SECONDS)
            return first

        monkeypatch.setattr(feed_persistence.SqlRecordEventWriter, "allocate", allocate)


def _paused(gate: AllocatorGate, name: str, future: Future[Any]) -> None:
    """Wait until `name` holds its allocation, surfacing a writer that failed first."""
    deadline = time.monotonic() + JOIN_TIMEOUT_SECONDS
    while not gate.reached[name].wait(0.05):
        if future.done():
            future.result()
            pytest.fail(f"{name} finished without reaching the allocator")
        assert time.monotonic() < deadline, f"{name} never reached the allocator"


def _named(name: str, work: Callable[[], Any]) -> Callable[[], Any]:
    def run() -> Any:  # noqa: ANN401
        threading.current_thread().name = name
        return work()

    return run


def _blocked_or_done(engine: Engine, future: Future[Any]) -> bool:
    """True once another backend waits on a lock; False if `future` finished first."""
    deadline = time.monotonic() + BLOCK_DEADLINE_SECONDS
    with engine.connect() as observer:
        while time.monotonic() < deadline:
            if future.done():
                return False
            waiting = observer.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                    "AND pid <> pg_backend_pid()"
                )
            ).scalar_one()
            observer.rollback()
            if waiting:
                return True
            time.sleep(0.05)
    return False


def _update(runtime: Runtime, task_id: str, version: int, key: str, title: str) -> Any:  # noqa: ANN401
    return runtime.ok(
        UpdateTask(task_id=task_id, expected_version=version, idempotency_key=key, title=title)
    )


def _version(runtime: Runtime, task_id: str) -> int:
    return int(runtime.ok(ReadTask(task_id=task_id))["task"]["version"])


# ---- RE-AC-066: the ten-step bootstrap -----------------------------------------


def test_watermark_snapshot_resume_returns_concurrent_changes(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = runtime.work_engine
    # 1. Setup: T1 and T2 commit their created events.
    t1 = _create(runtime, "rcev06-boot-t1")["task"]["task_id"]
    t2 = _create(runtime, "rcev06-boot-t2")["task"]["task_id"]
    v1, v2 = _version(runtime, t1), _version(runtime, t2)
    pre_watermark = {item["event_id"] for item in feed(engine)}
    gate = AllocatorGate()
    gate.install(monkeypatch)
    release_a = gate.hold("writer-a")
    with ThreadPoolExecutor(max_workers=2) as pool:
        # 2. Writer A allocates and pauses, uncommitted, holding the allocator row.
        a = pool.submit(_named("writer-a", lambda: _update(runtime, t1, v1, "rcev06-a", "A")))
        _paused(gate, "writer-a", a)
        # 3. The watermark does not see A's uncommitted allocation.
        bootstrap = listing(engine, page_size=1)
        assert watermark(bootstrap) == feed(engine)[-1]["event_id"]
        assert watermark(bootstrap) in pre_watermark
        # 4. Writer D blocks on the allocator row A holds.
        d = pool.submit(_named("writer-d", lambda: _update(runtime, t2, v2, "rcev06-d", "D")))
        assert _blocked_or_done(engine, d), "writer D did not wait for writer A"
        # 5. The snapshot: both Tasks still at their pre-update versions.
        held = {t1: _version(runtime, t1), t2: _version(runtime, t2)}
        assert held == {t1: v1, t2: v2}
        # 6. Release A; then D commits.
        release_a.set()
        a.result(timeout=JOIN_TIMEOUT_SECONDS)
        d.result(timeout=JOIN_TIMEOUT_SECONDS)
    # 7. One more commit before the resume.
    _update(runtime, t1, v1 + 1, "rcev06-later", "Later")
    # 8. Resume from the watermark until there is no more.
    changes: list[tuple[str, int]] = []
    cursor = bootstrap.high_watermark_cursor
    while True:
        page = listing(engine, page_size=1, cursor=cursor)
        changes.extend((item.record_id, item.record_version) for item in page.events)
        assert not {item.event_id for item in page.events} & pre_watermark
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert changes == [(t1, v1 + 1), (t2, v2 + 1), (t1, v1 + 2)]
    # 9. The client algorithm: reread what moved past the held version.
    for record_id, record_version in changes:
        if record_version > held[record_id]:
            held[record_id] = _version(runtime, record_id)
    assert held == {t1: _version(runtime, t1), t2: _version(runtime, t2)}
    # 10. The watermark moved to the last event, with nothing more to read.
    assert page.next_cursor is None
    assert watermark(page) == feed(engine)[-1]["event_id"]


# ---- R-07 / RE-AC-065 -----------------------------------------------------------


def test_page_and_watermark_share_one_snapshot(runtime: Runtime) -> None:
    engine = runtime.work_engine
    for index in range(3):
        _create(runtime, f"rcev06-snap-{index}")
    fired: list[bool] = []

    @event.listens_for(engine, "after_cursor_execute")
    def _commit_a_writer(conn: Any, cursor: Any, statement: str, *_: Any) -> None:  # noqa: ANN401
        if "feed_page" in statement and not fired:
            fired.append(True)
            _create(runtime, "rcev06-snap-intruder")

    try:
        view = listing(engine, page_size=10)
    finally:
        event.remove(engine, "after_cursor_execute", _commit_a_writer)
    assert fired, "the page statement never ran"
    assert len(feed(engine)) == 4
    assert len(view.events) == 3
    assert view.next_cursor is None
    assert watermark(view) == view.events[-1].event_id


# ---- R-08 ------------------------------------------------------------------------


def test_watermark_never_exceeds_an_uncommitted_lower_sequence(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = runtime.work_engine
    t1 = _create(runtime, "rcev06-r08-t1")["task"]["task_id"]
    t2 = _create(runtime, "rcev06-r08-t2")["task"]["task_id"]
    committed = feed(engine)[-1]["event_id"]
    gate = AllocatorGate()
    gate.install(monkeypatch)
    release = gate.hold("writer-low")
    with ThreadPoolExecutor(max_workers=2) as pool:
        low = pool.submit(
            _named("writer-low", lambda: _update(runtime, t1, 1, "rcev06-r08-low", "L"))
        )
        _paused(gate, "writer-low", low)
        high = pool.submit(
            _named("writer-high", lambda: _update(runtime, t2, 1, "rcev06-r08-high", "H"))
        )
        _blocked_or_done(engine, high)
        during = listing(engine, page_size=10)
        release.set()
        low.result(timeout=JOIN_TIMEOUT_SECONDS)
        high.result(timeout=JOIN_TIMEOUT_SECONDS)
    assert watermark(during) == committed
    resumed = listing(engine, page_size=10, cursor=during.high_watermark_cursor)
    assert sorted(item.record_id for item in resumed.events) == sorted([t1, t2])


# ---- R-09 / RE-AC-070 ------------------------------------------------------------


MEMORY_GRANTS: Final = frozenset(
    (capability, next(iter(permitted_purposes(capability))))
    for capability in (Capability.RELATIONSHIP_MEMORY_GET,)
)


def _assert_no_count_channel(view: RecordEventListView) -> None:
    """No withheld count, no public sequence, and tokens that carry no number."""
    dumped = view.to_canonical_dict()
    assert set(dumped) == {"events", "next_cursor", "high_watermark_cursor", "visible_families"}
    for item in dumped["events"]:
        assert "sequence_number" not in item
    for token in (view.next_cursor, view.high_watermark_cursor):
        if token is not None:
            assert read_cursor(token) is not None


def _memory_events(engine: Engine) -> list[str]:
    return [item["event_id"] for item in feed(engine, MEMORY_PRINCIPAL)]


def test_remote_watermark_excludes_restricted_memory(staged: Engine) -> None:  # noqa: F811
    """A memory whose *current* version is restricted is withheld everywhere.

    Its earlier event is stored `private_local`, so only the current-version
    `EXISTS` withholds it -- from the page and from the watermark.
    """
    plain = create_memory(staged, kind=MemoryKind.WORKING_PREFERENCE, key="rcev06-r09-plain")
    raised = create_memory(staged, kind=MemoryKind.WORKING_PREFERENCE, key="rcev06-r09-raised")
    revise_memory(
        staged,
        raised,
        expected=1,
        key="rcev06-r09-raise",
        memory_kind=MemoryKind.SENSITIVITY,
        current_kind=MemoryKind.WORKING_PREFERENCE,
    )
    e1, e2, e3 = _memory_events(staged)
    local = listing(staged, MEMORY_PRINCIPAL)
    assert [item.event_id for item in local.events] == [e1, e2, e3]
    assert watermark(local) == e3
    remote = listing(staged, MEMORY_PRINCIPAL, capability_grants=MEMORY_GRANTS)
    assert [item.record_id for item in remote.events] == [plain]
    assert [item.event_id for item in remote.events] == [e1]
    assert watermark(remote) == e1
    _assert_no_count_channel(remote)
    resumed = listing(
        staged,
        MEMORY_PRINCIPAL,
        capability_grants=MEMORY_GRANTS,
        cursor=remote.high_watermark_cursor,
    )
    assert resumed.events == ()
    assert watermark(resumed) == e1


def test_remote_page_excludes_an_event_stored_restricted(staged: Engine) -> None:  # noqa: F811
    """An event stored `restricted_local` stays withheld after its memory is lowered.

    The memory's current version is private again, so only the stored
    classification withholds the first event.
    """
    lowered = create_memory(staged, kind=MemoryKind.SENSITIVITY, key="rcev06-r09-lowered")
    revise_memory(
        staged,
        lowered,
        expected=1,
        key="rcev06-r09-lower",
        memory_kind=MemoryKind.WORKING_PREFERENCE,
        current_kind=MemoryKind.SENSITIVITY,
    )
    restricted, private = _memory_events(staged)
    remote = listing(staged, MEMORY_PRINCIPAL, capability_grants=MEMORY_GRANTS, page_size=1)
    assert [item.event_id for item in remote.events] == [private]
    assert remote.next_cursor is None
    assert watermark(remote) == private
    assert restricted not in {item.event_id for item in remote.events}
    _assert_no_count_channel(remote)
    assert [item.event_id for item in listing(staged, MEMORY_PRINCIPAL).events] == [
        restricted,
        private,
    ]
