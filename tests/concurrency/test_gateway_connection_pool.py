"""Five concurrent requests, and the pool arithmetic that decides whether they finish.

WP-4B1's audit sink takes a **second** connection per request, by design: an
event that must outlive the rollback of the work it describes cannot be written
on the connection doing the work. `infrastructure/persistence/audit.py` says so
in its own docstring and hands the consequence to whoever composes a concurrent
transport. This is that consequence, measured.

**The arithmetic.** With one pool of size `P` and `C` requests in flight, each
request holds a work connection for its whole life and needs an audit connection
while still holding it. Free connections are `P - C`, so the audit checkout
succeeds only while `P - C >= 1`. At `C >= P` there are none free and no work
connection can be released before its own audit completes: every request is
waiting for a connection that only another waiting request can return. The
threshold is therefore exactly `C = P`, and `create_database_engine` builds
`P = 5`.

**What the checkout timeout does to that, exactly.** It is a deadlock that ends
itself. Every request stalls for the full `pool_timeout`; the first checkout to
expire fails, its `with` block unwinds, and the work connection it was holding
returns to the pool — which unblocks whichever waiters have not expired yet. So
the measured outcome is not "all five fail" but "all five stall for the timeout
and some of them fail", and the number that fail depends on scheduling. Both
halves are the defect: the stall is not a bound anyone chose, and a request
refused because *another* request was in flight is not a refusal the caller can
act on. `internal_error` is the right code for it and the wrong thing to be
producing.

**The four tests below are that sentence, performed.**

* four concurrent requests through one shared pool of five all succeed — one
  connection stays free, so the audits proceed one after another. This is why
  the defect was not visible in a single-threaded worker;
* *five* through the same pool stall for the whole timeout and at least one
  fails — the boundary, and the defect;
* five through the two pools `bootstrap.gateway` builds all succeed and do not
  stall, because an audit connection is drawn from a pool no work connection can
  occupy;
* ten through those pools also all succeed: above the work pool's size there is
  a queue, and a queue makes progress.

**The barrier is what makes this deterministic.** A test that fired five
requests and hoped they overlapped would pass on a fast machine and fail on a
slow one, and a deadlock that only sometimes reproduces is worse evidence than
none. Each request instead waits, holding its work connection, until all five
are holding one. That is the state a concurrent transport reaches on its own;
the barrier only makes it certain.

**The shared engine differs from the production one in exactly one number.**
Same size, same absence of overflow, a one-second checkout timeout rather than
thirty — so the failure the production sizing takes half a minute to produce
takes a second. It is built here rather than through `create_database_engine`
because the composition under test is precisely the one that no longer exists.

Every test runs against a disposable database created and dropped by its
fixture, never the configured one, and everything in it is synthetic.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Final

import pytest
from sqlalchemy import Engine, create_engine, text
from tests.conftest import DEFAULT_LIMITS

from my_pa.application.commands import GetCapabilities
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.gateway import build_gateway_runtime
from my_pa.bootstrap.settings import Settings
from my_pa.contracts.ports import (
    AuditSink,
    CaptureRepository,
    CommitmentManagementRepository,
    ContextPreferenceRepository,
    ContextRunRepository,
    EnrollmentRepository,
    EntitiesRepository,
    GoodNotesSemanticRepository,
    KnowledgeRepository,
    ManagedDocumentRepository,
    OperationQueue,
    ProjectRepository,
    PulseRepository,
    ReviewRepository,
    SituationRepository,
    SourceProviders,
    SourceRepository,
    TaskManagementRepository,
    UnitOfWork,
)
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

ROOT = Path(__file__).resolve().parents[2]

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
DISPOSABLE_DATABASE: Final = "my_pa_gateway_pool_test"

WHEN: Final = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

#: How long a request may wait for a connection in the shared-pool composition.
#: The production engine waits thirty seconds and then fails the same way; one
#: second is the same failure, sooner.
SHARED_POOL_TIMEOUT_SECONDS: Final = 1

#: Long enough that a machine under load does not report a deadlock that is not
#: one, short enough that a real deadlock ends the test rather than the run.
BARRIER_TIMEOUT_SECONDS: Final = 30


def _administer(maintenance: Engine, *statements: object) -> None:
    """Run statements that cannot be inside a transaction, such as CREATE DATABASE."""
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


class _HoldsItsConnection(UnitOfWork):
    """A real unit of work that waits, holding its connection, for the others.

    The wait is after `__enter__` — that is, after the work connection has been
    checked out and before anything asks for an audit connection — which is the
    exact instant the arithmetic is about.
    """

    def __init__(self, inner: UnitOfWork, barrier: threading.Barrier) -> None:
        self._inner = inner
        self._barrier = barrier

    def __enter__(self) -> UnitOfWork:
        self._inner.__enter__()
        self._barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._inner.__exit__(exc_type, exc, traceback)

    @property
    def providers(self) -> SourceProviders:
        return self._inner.providers

    @property
    def sources(self) -> SourceRepository:
        return self._inner.sources

    @property
    def enrollments(self) -> EnrollmentRepository:
        return self._inner.enrollments

    @property
    def operations(self) -> OperationQueue:
        return self._inner.operations

    @property
    def knowledge(self) -> KnowledgeRepository:
        return self._inner.knowledge

    @property
    def captures(self) -> CaptureRepository:
        return self._inner.captures

    @property
    def reviews(self) -> ReviewRepository:
        return self._inner.reviews

    @property
    def situations(self) -> SituationRepository:
        return self._inner.situations

    @property
    def projects(self) -> ProjectRepository:
        return self._inner.projects

    @property
    def pulse(self) -> PulseRepository:
        return self._inner.pulse

    @property
    def managed_documents(self) -> ManagedDocumentRepository:
        return self._inner.managed_documents

    @property
    def tasks(self) -> TaskManagementRepository:
        return self._inner.tasks

    @property
    def commitments(self) -> CommitmentManagementRepository:
        return self._inner.commitments

    @property
    def context_runs(self) -> ContextRunRepository:
        return self._inner.context_runs

    @property
    def context_preferences(self) -> ContextPreferenceRepository:
        return self._inner.context_preferences

    @property
    def goodnotes_semantics(self) -> GoodNotesSemanticRepository:
        return self._inner.goodnotes_semantics

    @property
    def entities(self) -> EntitiesRepository:
        return self._inner.entities

    @property
    def audit(self) -> AuditSink:
        return self._inner.audit


def _service(work: Engine, audit: Engine, barrier: threading.Barrier) -> ApplicationService:
    """The real application over real engines, pausing where the arithmetic bites."""
    sink = SqlAlchemyAuditSink(audit)

    def unit_of_work() -> UnitOfWork:
        return _HoldsItsConnection(SqlAlchemyUnitOfWork(work, audit=sink), barrier)

    return ApplicationService(
        unit_of_work=unit_of_work,
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
    )


def _operator() -> Principal:
    return Principal(
        principal_id=issue_identifier(IdKind.PRINCIPAL),
        kind=PrincipalKind.OPERATOR,
        authenticated=True,
    )


def _request(service: ApplicationService, index: int) -> ResponseEnvelope:
    """One `capabilities.get`: no scope, no provider, one audit event."""
    principal = _operator()
    return service.invoke(
        RequestMetadata(
            request_id=f"req-pool-{index}",
            capability=Capability.CAPABILITIES_GET,
            purpose=Purpose.STATUS_OBSERVATION,
            principal_id=principal.principal_id,
            requested_at=WHEN,
        ),
        GetCapabilities(),
        principal=principal,
    )


def _concurrently(service: ApplicationService, count: int) -> tuple[list[ResponseEnvelope], float]:
    """Run `count` requests at once, and report how long the whole batch took."""
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=count) as pool:
        envelopes = list(pool.map(lambda index: _request(service, index), range(count)))
    return envelopes, time.monotonic() - started


@pytest.fixture
def engines(disposable_database: str) -> Iterator[tuple[Engine, Engine]]:
    """The two pools `bootstrap.gateway` composes, over a disposable database."""
    runtime = build_gateway_runtime(Settings(database_url=disposable_database))
    try:
        with runtime.work_engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE knowledge.native_simulation_receipts, "
                    "knowledge.native_checkpoints, "
                    "knowledge.native_apple_read_grants, "
                    "knowledge.native_admission_authorities, knowledge.audit_events"
                )
            )
        yield runtime.work_engine, runtime.audit_engine
    finally:
        runtime.close()


@pytest.fixture
def shared_engine(disposable_database: str) -> Iterator[Engine]:
    """One pool for both connections: the composition WP-4B2a replaced."""
    engine = create_engine(
        disposable_database,
        pool_size=5,
        max_overflow=0,
        pool_timeout=SHARED_POOL_TIMEOUT_SECONDS,
        pool_pre_ping=True,
    )
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE knowledge.native_simulation_receipts, "
                    "knowledge.native_checkpoints, "
                    "knowledge.native_apple_read_grants, "
                    "knowledge.native_admission_authorities, knowledge.audit_events"
                )
            )
        yield engine
    finally:
        engine.dispose()


def _audit_rows(engine: Engine) -> int:
    statement = text("SELECT count(*) FROM knowledge.audit_events")
    with engine.connect() as connection:
        return int(connection.execute(statement).scalar_one())


@pytest.mark.database
def test_the_pool_this_gateway_composes_is_the_size_the_arithmetic_assumes(
    engines: tuple[Engine, Engine],
) -> None:
    """Pin `P`. Every number below is derived from it, so it may not drift silently."""
    work, audit = engines
    assert work.pool.size() == 5
    assert audit.pool.size() == 5
    assert work.pool._max_overflow == 0
    assert audit.pool._max_overflow == 0


@pytest.mark.database
def test_four_concurrent_requests_through_one_shared_pool_still_complete(
    shared_engine: Engine,
) -> None:
    """Below the threshold, sharing works — which is why it was not noticed.

    Four work connections leave one free, so the four audits take it in turn.
    This is the control: without it, the failure below could be a broken engine
    rather than the arithmetic.
    """
    barrier = threading.Barrier(4)
    envelopes, elapsed = _concurrently(_service(shared_engine, shared_engine, barrier), 4)
    assert [envelope.error for envelope in envelopes] == [None] * 4
    assert _audit_rows(shared_engine) == 4
    assert elapsed < SHARED_POOL_TIMEOUT_SECONDS, "one connection short of the threshold stalled"


@pytest.mark.database
def test_five_concurrent_requests_through_one_shared_pool_all_fail(
    shared_engine: Engine,
) -> None:
    """The defect, at the exact threshold the arithmetic predicts.

    Five work connections leave none free. Every request then waits for an audit
    connection that only another waiting request can return, until the checkout
    timeout ends it. Failing closed is right; waiting for the timeout first is
    the part that is not, and it is what the two pools remove.
    """
    barrier = threading.Barrier(5)
    envelopes, elapsed = _concurrently(_service(shared_engine, shared_engine, barrier), 5)
    codes = [envelope.error.code for envelope in envelopes if envelope.error is not None]

    # The stall: nothing could progress until a checkout expired, so the batch
    # cannot have finished sooner than the timeout.
    assert elapsed >= SHARED_POOL_TIMEOUT_SECONDS, (
        f"the batch finished in {elapsed:.3f}s, sooner than the {SHARED_POOL_TIMEOUT_SECONDS}s "
        "checkout timeout; the pool was not exhausted and this test proves nothing"
    )
    # The failure: at least one request is refused for a reason that belongs to
    # another request. How many depends on which checkout expired first, which
    # is scheduling, so the assertion is the part that does not depend on it.
    assert codes, "no request failed; the pool was not exhausted"
    assert set(codes) == {ErrorCode.INTERNAL_ERROR}
    assert _audit_rows(shared_engine) == len(envelopes) - len(codes), (
        "an audit was recorded for a request that failed, or lost for one that did not"
    )


@pytest.mark.database
def test_five_concurrent_requests_through_the_split_pools_all_complete(
    engines: tuple[Engine, Engine],
) -> None:
    """The same five requests, against the composition `bootstrap.gateway` builds.

    Identical scenario, identical barrier, identical work-pool size. The only
    difference is which pool the audit connection comes from, and that is the
    whole of the fix.
    """
    work, audit = engines
    barrier = threading.Barrier(5)
    envelopes, elapsed = _concurrently(_service(work, audit, barrier), 5)
    assert [envelope.error for envelope in envelopes] == [None] * 5
    assert _audit_rows(work) == 5
    assert elapsed < SHARED_POOL_TIMEOUT_SECONDS, (
        f"the batch took {elapsed:.3f}s; with two pools no request waits for a connection"
    )


@pytest.mark.database
def test_more_requests_than_the_work_pool_holds_queue_rather_than_deadlock(
    engines: tuple[Engine, Engine],
) -> None:
    """Above the work pool's size there is a queue, and a queue makes progress.

    Ten requests against five work connections: five run, five wait for a work
    connection, and each waiter gets one as a predecessor finishes — which it
    can, because its audit never competes with a work connection. No barrier
    here, deliberately: the claim is about what happens when the *transport*
    over-subscribes, and a barrier of ten would block five requests that cannot
    reach it.
    """
    work, audit = engines
    barrier = threading.Barrier(1)
    envelopes, _elapsed = _concurrently(_service(work, audit, barrier), 10)
    assert [envelope.error for envelope in envelopes] == [None] * 10
    assert _audit_rows(work) == 10
