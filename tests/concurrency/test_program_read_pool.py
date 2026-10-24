"""AT-019 (pool): the Program read pool, and why a Program read never stalls a request.

Record lineage S4 contract section 6.3 (R4-F05, R4-F18). A Program read needs
one `REPEATABLE READ, READ ONLY` snapshot that cannot be the request's own
connection and must not be a second checkout from the work pool (the `C = P`
deadlock `tests/concurrency/test_gateway_connection_pool.py` measures). The
gateway therefore builds a **third** engine, only while
`MY_PA_PROGRAM_REPORTING_ENABLED` is on, from which nothing else draws.

The tests here are worker M1's part of the section 10 pool row, over the
Program read unit of work itself: with every work connection held -- the state
five concurrent requests reach -- each holder still takes its Program
connection at once, from the Program pool only, inside a read-only
repeatable-read snapshot. The overview- and commit-driven rows of the same
section 10 entry run once `programs.overview` (worker M4) and the commit
recompute (worker M5) exist.

The barrier makes the overlap certain rather than hoped for. Every test runs
against a disposable database; everything in it is synthetic.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Final

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime
from my_pa.bootstrap.settings import Settings
from my_pa.infrastructure.persistence.program_reads import SqlAlchemyProgramReadUnitOfWork

pytestmark = pytest.mark.database

#: Long enough that a loaded machine does not report a stall that is not one.
BARRIER_TIMEOUT_SECONDS: Final = 30
#: Far below the Program engine's 1 s checkout timeout: a checkout that waited
#: for another request's connection would take at least that long to fail.
NO_WAIT_SECONDS: Final = 0.5
CONCURRENCY: Final = 5
PRINCIPAL: Final = "prn_lineages4pool0001"
READ_ONLY_SQL_TRANSACTION: Final = "25006"


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[GatewayRuntime]:
    built = build_gateway_runtime(
        Settings(
            database_url=disposable_database,
            lineage_enabled=True,
            program_reporting_enabled=True,
        )
    )
    try:
        yield built
    finally:
        built.close()


def _hold_work_then_read(
    runtime: GatewayRuntime, barrier: threading.Barrier
) -> tuple[float, str, str, int, int]:
    """Hold one work connection (as a request does), then take one Program snapshot.

    Returns `(checkout seconds, isolation, read_only, work checked out, program
    checked out)`, the last two measured while every holder holds both.
    """
    assert runtime.program_read_engine is not None
    with runtime.work_engine.connect() as work:
        work.execute(text("SELECT 1"))
        barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)
        started = time.monotonic()
        with SqlAlchemyProgramReadUnitOfWork(runtime.program_read_engine) as program:
            waited = time.monotonic() - started
            program.snapshot(PRINCIPAL)
            connection = program.connection  # type: ignore[attr-defined]
            isolation = connection.execute(text("SHOW transaction_isolation")).scalar_one()
            read_only = connection.execute(text("SHOW transaction_read_only")).scalar_one()
            barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)
            work_out = runtime.work_engine.pool.checkedout()  # type: ignore[attr-defined]
            program_out = runtime.program_read_engine.pool.checkedout()  # type: ignore[attr-defined]
            barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)
    return waited, str(isolation), str(read_only), int(work_out), int(program_out)


def _concurrently(runtime: GatewayRuntime) -> list[tuple[float, str, str, int, int]]:
    barrier = threading.Barrier(CONCURRENCY)
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        return list(
            pool.map(lambda _index: _hold_work_then_read(runtime, barrier), range(CONCURRENCY))
        )


def test_a_program_read_never_draws_from_the_work_pool(runtime: GatewayRuntime) -> None:
    results = _concurrently(runtime)
    assert len(results) == CONCURRENCY
    for _waited, isolation, read_only, work_out, program_out in results:
        # The whole work pool is held by the requests, and every Program read
        # came from its own pool: the work pool never lent a sixth connection.
        assert work_out == CONCURRENCY == runtime.work_engine.pool.size()  # type: ignore[attr-defined]
        assert program_out == CONCURRENCY
        assert isolation == "repeatable read"
        assert read_only == "on"
    # The read transaction refuses a write, and is rolled back on exit.
    assert runtime.program_read_engine is not None
    with SqlAlchemyProgramReadUnitOfWork(runtime.program_read_engine) as program:
        program.snapshot(PRINCIPAL)
        with pytest.raises(DBAPIError) as refused:
            program.connection.execute(  # type: ignore[attr-defined]
                text("CREATE TEMPORARY TABLE program_read_probe (x integer)")
            )
    assert getattr(refused.value.orig, "sqlstate", None) == READ_ONLY_SQL_TRANSACTION
    assert runtime.program_read_engine.pool.checkedout() == 0  # type: ignore[attr-defined]


def test_no_program_checkout_waits_in_the_gateway(runtime: GatewayRuntime) -> None:
    results = _concurrently(runtime)
    waits = sorted(waited for waited, *_rest in results)
    # Every holder of a work connection took its Program connection without
    # waiting: the 5-connection Program pool never queues behind 5 requests.
    assert waits[-1] < NO_WAIT_SECONDS, waits
    assert runtime.program_read_engine is not None
    assert runtime.program_read_engine.pool.timeout() == 1  # type: ignore[attr-defined]
    assert runtime.program_read_engine.pool.size() == CONCURRENCY  # type: ignore[attr-defined]
