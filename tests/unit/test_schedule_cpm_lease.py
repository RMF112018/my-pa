"""Schedule Scenarios S6-2: the CPM compute lease, with no database (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` section 14.8.4
(R9-F03 P2-24b/c, RR2-F02). The unit of work and the lease engine are
replaced by fakes: the process lock answers busy on its own, and the
dedicated lease connection is unlocked (when it held C), invalidated and
closed on every path, with the process lock released. Every value is
synthetic.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import URL
from sqlalchemy.pool import NullPool

from my_pa.contracts.ports import (
    CpmComputeBusyError,
    PlaneReservation,
    PlaneReservationOutcome,
    StoredCpmRun,
    VerifiedScenarioContent,
)
from my_pa.domain.schedule.plane import PlaneProvenance
from my_pa.domain.schedule.scenario.canonical import content_bytes
from my_pa.domain.schedule.scenario.cpm import CpmResult, CpmStatus, run_cpm
from my_pa.domain.schedule.scenario.model import ScenarioContent
from my_pa.infrastructure.persistence import schedule_cpm_lease as lease
from tests.fixtures.schedule_scenario import link, network, task

P: Final = "prn_cpmlease0001"
VERSION: Final = "sscv_cpmlease0001"
CONTENT: Final = network([task("A", 480), task("B", 960)], [link("A", "B")])
WRITER: Final = PlaneProvenance(
    authority_class="ordinary_reviewer",
    decision_channel="remote_interactive",
    asserting_client_id="client-lease",
    acceptance_basis="client_identified",
)


@dataclass
class _LeaseConnection:
    held: bool = True
    unlock_fails: bool = False
    calls: list[str] = field(default_factory=list)

    def execute(self, statement: Any) -> Any:  # noqa: ANN401 - a fake of Connection.execute
        text = str(statement)
        if "pg_try_advisory_lock" in text:
            self.calls.append("try_lock")
            return _Scalar(self.held)
        if "pg_advisory_unlock" in text:
            self.calls.append("unlock")
            if self.unlock_fails:
                raise RuntimeError("the connection broke")
            return _Scalar(True)
        raise AssertionError(text)

    def invalidate(self) -> None:
        self.calls.append("invalidate")

    def close(self) -> None:
        self.calls.append("close")


@dataclass
class _Scalar:
    value: object

    def scalar(self) -> object:
        return self.value


@dataclass
class _LeaseEngine:
    connections: list[_LeaseConnection]
    url: URL = field(default_factory=lambda: URL.create("postgresql+psycopg", host="x.invalid"))

    def connect(self) -> _LeaseConnection:
        return self.connections.pop(0)


class _Repository:
    def __init__(self, world: _World) -> None:
        self._world = world

    def find_request(self, *_: object) -> PlaneReservation | None:
        return None

    def get_cpm_run(self, *_: object) -> StoredCpmRun | None:
        return None

    def load_content(self, *_: object) -> VerifiedScenarioContent:
        canonical = content_bytes(CONTENT)
        return VerifiedScenarioContent(content=CONTENT, canonical=canonical, size=len(canonical))

    def lock_principal(self, *_: object) -> None:
        self._world.steps.append("lock_principal")
        if self._world.units_read_fails:
            raise RuntimeError("the units read failed")

    def cpm_units_since(self, *_: object) -> int:
        return 0

    def reserve_request(self, *_: object) -> PlaneReservation:
        return PlaneReservation(PlaneReservationOutcome.RESERVED)

    def insert_cpm_run(self, _principal: str, run: Any, writer: Any) -> tuple[StoredCpmRun, bool]:  # noqa: ANN401
        if self._world.write_fails:
            raise RuntimeError("the write failed")
        self._world.steps.append("insert")
        stored = StoredCpmRun(
            cpm_run_id="scpm_cpmlease0001",
            version_id=run.version_id,
            engine_version=run.engine_version,
            input_content_sha256=run.input_content_sha256,
            status=run.status,
            result_sha256=run.result_sha256,
            result_size_bytes=run.result_size_bytes,
            activity_count=run.activity_count,
            relationship_count=run.relationship_count,
            project_finish=run.project_finish,
            provenance=writer,
            created_at=datetime(2026, 11, 3, tzinfo=UTC),
        )
        return stored, True

    def complete_request(self, *_: object, **__: object) -> None:
        self._world.steps.append("complete")


@dataclass
class _World:
    steps: list[str] = field(default_factory=list)
    units_read_fails: bool = False
    write_fails: bool = False


class _UnitOfWork:
    def __init__(self, world: _World) -> None:
        self._world = world

    def __enter__(self) -> _UnitOfWork:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    @property
    def scenarios(self) -> _Repository:
        return _Repository(self._world)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[_World]:
    state = _World()
    monkeypatch.setattr(lease, "SqlAlchemyScenarioUnitOfWork", lambda _engine: _UnitOfWork(state))
    yield state


def _serve(monkeypatch: pytest.MonkeyPatch, *connections: _LeaseConnection) -> _LeaseEngine:
    engine = _LeaseEngine(list(connections))
    monkeypatch.setattr(lease, "lease_engine", lambda _url: engine)
    return engine


def _run(
    engine: _LeaseEngine,
    *,
    key: str = "cpm-lease-key-0001",
    admit: Callable[[int, int], None] = lambda _used, _requested: None,
    compute: Callable[[ScenarioContent], CpmResult] = run_cpm,
) -> Any:  # noqa: ANN401 - CpmRunWritten
    return lease.compute_and_store_cpm_run(
        engine,  # type: ignore[arg-type]
        P,
        VERSION,
        capability_key=key,
        request_digest="d" * 64,
        writer=WRITER,
        admit_compute=admit,
        compute=compute,
    )


def _free(principal: str = P) -> bool:
    """The process lock of `principal` is free (acquired and released again)."""
    lock = lease._process_lock(principal)
    if not lock.acquire(blocking=False):
        return False
    lock.release()
    return True


def test_the_process_lock_answers_busy_alone(
    monkeypatch: pytest.MonkeyPatch, world: _World
) -> None:
    """P2-24b: C always granted (stubbed); the second thread is refused by the process lock."""
    engine = _serve(monkeypatch, _LeaseConnection(held=True), _LeaseConnection(held=True))
    entered = threading.Event()
    release = threading.Event()
    computed: list[str] = []

    def blocking(content: ScenarioContent) -> CpmResult:
        computed.append("first")
        entered.set()
        assert release.wait(30)
        return run_cpm(content)

    outcome: dict[str, object] = {}

    def first() -> None:
        outcome["first"] = _run(engine, key="cpm-lease-key-0001", compute=blocking)

    thread = threading.Thread(target=first)
    thread.start()
    try:
        assert entered.wait(30)

        def second(content: ScenarioContent) -> CpmResult:
            computed.append("second")
            return run_cpm(content)

        with pytest.raises(CpmComputeBusyError):
            _run(engine, key="cpm-lease-key-0002", compute=second)
    finally:
        release.set()
        thread.join(30)
    assert computed == ["first"]
    assert getattr(outcome["first"], "created") is True  # noqa: B009
    assert _free()


_PATHS: Final = ("success", "compute_raises", "admit_refuses", "units_read_fails", "write_fails")


@pytest.mark.parametrize("path", [*_PATHS, "busy", "unlock_fails"])
def test_lease_unlocks_and_invalidates_on_every_path(
    monkeypatch: pytest.MonkeyPatch, world: _World, path: str
) -> None:
    """P2-24c: step 6 runs whatever happened; a lease that was never held is not unlocked."""
    connection = _LeaseConnection(held=path != "busy", unlock_fails=path == "unlock_fails")
    engine = _serve(monkeypatch, connection)
    world.units_read_fails = path == "units_read_fails"
    world.write_fails = path == "write_fails"

    def compute(content: ScenarioContent) -> CpmResult:
        if path == "compute_raises":
            raise RuntimeError("the compute failed")
        return run_cpm(content)

    def admit(_used: int, _requested: int) -> None:
        if path == "admit_refuses":
            raise LookupError("the units bound refuses")

    expected: type[BaseException] | None = {
        "compute_raises": RuntimeError,
        "admit_refuses": LookupError,
        "units_read_fails": RuntimeError,
        "write_fails": RuntimeError,
        "busy": CpmComputeBusyError,
    }.get(path)
    if expected is None:
        written = _run(engine, admit=admit, compute=compute)
        assert written.created is True
        assert written.cpm_run.status is CpmStatus.COMPUTED
    else:
        with pytest.raises(expected):
            _run(engine, admit=admit, compute=compute)
    if path == "busy":
        assert connection.calls == ["try_lock", "invalidate", "close"]
    else:
        assert connection.calls == ["try_lock", "unlock", "invalidate", "close"]
    assert _free(), "the process lock was not released"


def test_the_lease_engine_is_cached_per_url_and_disposed() -> None:
    """RR1-F03 / RR2-F02: `NullPool`, `AUTOCOMMIT`, one engine per URL, disposed on demand."""
    url = URL.create("postgresql+psycopg", username="lease", host="lease.invalid", database="d")
    try:
        first = lease.lease_engine(url)
        assert lease.lease_engine(url) is first
        assert isinstance(first.pool, NullPool)
        assert first.dialect._on_connect_isolation_level == "AUTOCOMMIT"
    finally:
        lease.dispose_lease_engines()
    assert lease.lease_engine(url) is not first
    lease.dispose_lease_engines()
    with pytest.raises(TypeError, match="parsed URL"):
        lease.lease_engine("postgresql+psycopg://lease.invalid/d")  # type: ignore[arg-type]
