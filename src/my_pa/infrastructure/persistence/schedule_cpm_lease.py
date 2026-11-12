"""Schedule Scenarios S6-2: one CPM compute per Principal, and the run it stores.

Contract: `docs/architecture/schedule-scenarios-contract.md` sections 3.11 and
14.8.4 (R8 ruling R-5, R9-F12, RR1-F03, RR2-F02). The compute lease has two
layers, each of which answers `CpmComputeBusyError` on its own:

1. a process lock -- a module-level `dict[str, threading.Lock]`, acquired
   without blocking -- so two threads of one process never both compute; and
2. the session lock C, `pg_try_advisory_lock(int4, int4)` in its own namespace
   `SCHEDULE_CPM_ADVISORY_NAMESPACE`, on a **dedicated** connection from a
   `NullPool` lease engine outside the request pool. It never waits.

The compute itself (`run_cpm`) runs outside any transaction, with no database
lock but C; the write transaction then takes P and inserts by the natural key
`ON CONFLICT DO NOTHING`. Whatever happens, the `finally` block unlocks C on
the dedicated connection (an error or `false` is swallowed: the lease is
already lost), invalidates and closes that connection -- it never returns to
any pool, so no pooled connection can carry a session lock -- and releases the
process lock.

C has its own namespace so that a 32-bit `hashtext` collision can never make a
held lease block the P or J lock of its own request (a wait PostgreSQL cannot
detect). Lease connections sit outside the gateway's pool of 5: at most 1 extra
connection per concurrently computing Principal per process (S6-2-U12).
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import (
    URL,
    Connection,
    Engine,
    Integer,
    Text,
    cast,
    create_engine,
    func,
    literal,
    select,
)
from sqlalchemy.pool import NullPool

from my_pa.contracts.ports import (
    CpmComputeBusyError,
    CpmRunWritten,
    NewCpmRun,
    PlaneReservation,
    PlaneReservationOutcome,
    PlaneSubjectAbsentError,
    ScenarioIntegrityError,
    ScenarioRepository,
)
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.schedule.plane import PlaneProvenance
from my_pa.domain.schedule.scenario.cpm import ENGINE_VERSION, CpmResult, run_cpm
from my_pa.domain.schedule.scenario.model import ScenarioContent
from my_pa.infrastructure.persistence.schedule_scenarios import (
    SqlAlchemyScenarioUnitOfWork,
    new_cpm_run,
)

__all__ = [
    "CPM_RUN_CAPABILITY",
    "SCHEDULE_CPM_ADVISORY_NAMESPACE",
    "compute_and_store_cpm_run",
    "cpm_lease_key",
    "dispose_lease_engines",
    "lease_engine",
]

#: Section 14.8.4: the compute lease namespace, "SCPM" (S6-2-D06).
SCHEDULE_CPM_ADVISORY_NAMESPACE: Final = 0x5343504D
CPM_RUN_CAPABILITY: Final = "schedule_cpm_runs.create"
_HOUR: Final = timedelta(hours=1)

#: One guard for the process-lock dict and the lease-engine cache (RR2-F02).
_GUARD: Final = threading.Lock()
_PROCESS_LOCKS: Final[dict[str, threading.Lock]] = {}
_LEASE_ENGINES: Final[dict[URL, Engine]] = {}


def cpm_lease_key(principal_id: str) -> str:
    """The `hashtext` input of C: `cpm:<principal_id>` (a module seam for collision tests)."""
    return "cpm:" + principal_id


def lease_engine(url: URL) -> Engine:
    """The process-cached lease engine for `url`: `NullPool`, `AUTOCOMMIT`, no timeout.

    Takes the parsed `URL` (never `str(engine.url)`, which masks the password).
    The connect arguments are stated, not copied: the lease connection runs
    only `pg_try_advisory_lock` and `pg_advisory_unlock`, so it needs no
    `statement_timeout`. Created and read under the module guard, so 2 first
    uses never build 2 engines.
    """
    if not isinstance(url, URL):
        raise TypeError("a lease engine is built from a parsed URL")
    with _GUARD:
        engine = _LEASE_ENGINES.get(url)
        if engine is None:
            engine = create_engine(
                url, poolclass=NullPool, isolation_level="AUTOCOMMIT", connect_args={}
            )
            _LEASE_ENGINES[url] = engine
        return engine


def dispose_lease_engines() -> None:
    """Dispose every cached lease engine (shutdown, and test teardown)."""
    with _GUARD:
        engines = list(_LEASE_ENGINES.values())
        _LEASE_ENGINES.clear()
    for engine in engines:
        engine.dispose()


def _process_lock(principal_id: str) -> threading.Lock:
    with _GUARD:
        lock = _PROCESS_LOCKS.get(principal_id)
        if lock is None:
            lock = threading.Lock()
            _PROCESS_LOCKS[principal_id] = lock
        return lock


def _lease_key(principal_id: str) -> tuple[object, object]:
    return (
        cast(literal(SCHEDULE_CPM_ADVISORY_NAMESPACE), Integer),
        func.hashtext(literal(cpm_lease_key(principal_id), Text)),
    )


def _try_lease(connection: Connection, principal_id: str) -> bool:
    """`pg_try_advisory_lock(C)`: never waits; `False` when another session holds C."""
    return bool(
        connection.execute(select(func.pg_try_advisory_lock(*_lease_key(principal_id)))).scalar()
    )


def _end_lease(connection: Connection, principal_id: str, *, held: bool) -> None:
    """Step 6: unlock C if it was taken, then invalidate and close; never raises the unlock."""
    try:
        if held:
            # An error or a `false` answer means the lease is already lost.
            with contextlib.suppress(Exception):
                connection.execute(select(func.pg_advisory_unlock(*_lease_key(principal_id))))
        connection.invalidate()
    finally:
        connection.close()


def _now() -> datetime:
    return datetime.now(UTC)


def _admit_nothing(
    repository: ScenarioRepository, principal_id: str, new_bytes: int | None
) -> None:
    """The default `admit_write`: no write budget (S6-2 callers and tests)."""
    del repository, principal_id, new_bytes


def compute_and_store_cpm_run(
    engine: Engine,
    principal_id: str,
    version_id: str,
    *,
    capability_key: str,
    request_digest: str,
    writer: PlaneProvenance,
    admit_compute: Callable[[int, int], None],
    admit_write: Callable[[ScenarioRepository, str, int | None], None] = _admit_nothing,
    compute: Callable[[ScenarioContent], CpmResult] = run_cpm,
    clock: Callable[[], datetime] = _now,
) -> CpmRunWritten:
    """Section 14.8.4 steps 1-6: replay, natural key, or one leased compute and its write.

    `admit_compute(units_used_last_hour, units_requested)` is S6-3's
    activity-units check, called while the lease is held; it raises to refuse.
    `compute` is injected so tests can hold a compute on a barrier.

    `admit_write(repository, principal_id, new_bytes)` is S6-3's client
    write-budget check (section 15.10, R10-F02, R10-N01, S6-3-D23), called
    twice: only on the compute path -- after the ledger probe and the
    natural-key probe both found nothing -- in a short transaction under P with
    `new_bytes=None` (nothing stored yet: S6-3 refuses a client already at or
    over a budget or quota), immediately before the leased compute, so such a
    client never computes; and authoritatively in the write transaction after
    a `RESERVED` reservation and before the insert, with the bytes the write
    stores (0 for a natural-key hit). It raises to refuse.
    """
    validate_identifier(principal_id, IdKind.PRINCIPAL)
    # Step 1: the ledger probe, the natural-key probe and the verified content.
    with SqlAlchemyScenarioUnitOfWork(engine) as uow:
        replay = uow.scenarios.find_request(
            principal_id, CPM_RUN_CAPABILITY, capability_key, request_digest
        )
        if replay is not None:
            return _replayed(uow.scenarios, principal_id, replay)
        existing = uow.scenarios.get_cpm_run(principal_id, version_id, ENGINE_VERSION)
        verified = (
            None if existing is not None else uow.scenarios.load_content(principal_id, version_id)
        )
        if existing is None and verified is None:
            raise PlaneSubjectAbsentError()
    stored = None
    if verified is not None:
        # R10-F02/R10-N01: the read-only pre-check, never reached by a replay or
        # a natural-key hit, with no new bytes (step 5 re-checks the actual size).
        with SqlAlchemyScenarioUnitOfWork(engine) as uow:
            uow.scenarios.lock_principal(principal_id)
            admit_write(uow.scenarios, principal_id, None)
        stored = _leased_compute(
            engine,
            principal_id,
            version_id,
            verified.content,
            admit_compute=admit_compute,
            compute=compute,
            clock=clock,
        )
    # Step 5: the write transaction (prologue, natural-key insert, completion).
    with SqlAlchemyScenarioUnitOfWork(engine) as uow:
        scenarios = uow.scenarios
        scenarios.lock_principal(principal_id)
        reservation = scenarios.reserve_request(
            principal_id, CPM_RUN_CAPABILITY, capability_key, request_digest, writer
        )
        if reservation.outcome is not PlaneReservationOutcome.RESERVED:
            return _replayed(scenarios, principal_id, reservation)
        if stored is None:
            run = existing
            created = False
            if run is None:  # pragma: no cover - step 1 returned or computed
                raise ScenarioIntegrityError("cpm_run_missing")
            admit_write(scenarios, principal_id, 0)
        else:
            admit_write(scenarios, principal_id, stored.result_size_bytes)
            run, created = scenarios.insert_cpm_run(principal_id, stored, writer)
        scenarios.complete_request(
            principal_id,
            CPM_RUN_CAPABILITY,
            capability_key,
            run.cpm_run_id,
            created=created,
            stored_bytes=run.result_size_bytes if created else 0,
        )
        return CpmRunWritten(PlaneReservationOutcome.RESERVED, run, created)


def _replayed(
    scenarios: ScenarioRepository, principal_id: str, reservation: PlaneReservation
) -> CpmRunWritten:
    """A replay answers the stored run and its original `created` (S6-3, section 15.6.1)."""
    result_id = reservation.result_id
    if reservation.outcome is PlaneReservationOutcome.CONFLICT or result_id is None:
        return CpmRunWritten(PlaneReservationOutcome.CONFLICT, None, None)
    run = scenarios.get_cpm_run_by_id(principal_id, result_id)
    return CpmRunWritten(PlaneReservationOutcome.REPLAYED, run, bool(reservation.result_created))


def _leased_compute(
    engine: Engine,
    principal_id: str,
    version_id: str,
    content: ScenarioContent,
    *,
    admit_compute: Callable[[int, int], None],
    compute: Callable[[ScenarioContent], CpmResult],
    clock: Callable[[], datetime],
) -> NewCpmRun:
    """Steps 2-4 under both lease layers; step 6 on every path."""
    process_lock = _process_lock(principal_id)
    if not process_lock.acquire(blocking=False):
        raise CpmComputeBusyError()
    try:
        connection = lease_engine(engine.url).connect()
        held = False
        try:
            held = _try_lease(connection, principal_id)
            if not held:
                raise CpmComputeBusyError()
            # Step 3: S6-3's units check, read under P while the lease is held.
            with SqlAlchemyScenarioUnitOfWork(engine) as uow:
                uow.scenarios.lock_principal(principal_id)
                used = uow.scenarios.cpm_units_since(principal_id, clock() - _HOUR)
            admit_compute(used, len(content.activities))
            # Step 4: the compute, outside any transaction.
            return new_cpm_run(version_id, compute(content))
        finally:
            _end_lease(connection, principal_id, held=held)
    finally:
        process_lock.release()
