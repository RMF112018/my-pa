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
repeatable-read snapshot. Worker M4's rows drive real `programs.overview`
requests through the gateway's own pools: 5 at once all complete without a
stall (each holding its work connection while it takes its Program one), and
10 at once queue on the **work** pool -- 5 run, 5 wait for a work connection,
never for a Program one -- and all complete. Worker M5's row drives 5 concurrent
`reports.commit` requests carrying a Program reference block: each recompute
holds its request's work connection and draws only one Program connection,
and all 5 complete `verified_at_commit`.

The barrier makes the overlap certain rather than hoped for. Every test runs
against a disposable database; everything in it is synthetic.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Final

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from tests.database.lineage_s4_harness import T0, ProgramSeeds

from my_pa.application.commands import (
    BeginIntelligenceCycle,
    Command,
    CommitIntelligenceArtifact,
    ReadProgramOverview,
)
from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime
from my_pa.bootstrap.settings import Settings
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    ARTIFACT_KIND_FOR_STAGE,
    CYCLE_MORNING_INTELLIGENCE,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
    SourceLaneId,
)
from my_pa.domain.program.vocabulary import PROGRAM_REFERENCE_BLOCK_KEY
from my_pa.domain.source.registry import issue_identifier
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


# --- programs.overview through the gateway's pools (worker M4) ------------------

#: The overview's first statement: the one that takes the snapshot.
SNAPSHOT_MARK: Final = "statement_timestamp()"


@pytest.fixture
def overview_runtime(disposable_database: str) -> Iterator[GatewayRuntime]:
    """The gateway composition that serves `programs.overview` (entity plane on)."""
    built = build_gateway_runtime(
        Settings(
            database_url=disposable_database,
            lineage_enabled=True,
            program_reporting_enabled=True,
            relationship_intelligence_enabled=True,
        )
    )
    try:
        yield built
    finally:
        built.close()


def _seeded_program(runtime: GatewayRuntime) -> str:
    """A Program of 3 calendared, synced Projects of `PRINCIPAL` (direct SQL)."""
    seeds = ProgramSeeds(runtime.work_engine)
    program = seeds.program("Pool Program", principal_id=PRINCIPAL)
    for index in range(3):
        project_id, entity_id = seeds.project(f"Pool member {index}", principal_id=PRINCIPAL)
        seeds.edge(entity_id, program, effective_from=T0, principal_id=PRINCIPAL)
        category = seeds.constraint_calendar(project_id, principal_id=PRINCIPAL)
        seeds.sync_target(project_id, principal_id=PRINCIPAL)
        assert category
    return program


def _overview(runtime: GatewayRuntime, program: str, index: int) -> ResponseEnvelope:
    return runtime.service.invoke(
        RequestMetadata(
            request_id=issue_identifier(IdKind.CORRELATION),
            capability=Capability.PROGRAMS_OVERVIEW,
            purpose=Purpose.PROGRAM_REPORTING_READ,
            principal_id=PRINCIPAL,
            requested_at=datetime.now(UTC),
        ),
        ReadProgramOverview(program_entity_ids=(program,)),
        principal=Principal(
            principal_id=PRINCIPAL, kind=PrincipalKind.OPERATOR, authenticated=True
        ),
    )


def _overviews_held_at_the_snapshot(
    runtime: GatewayRuntime, program: str, count: int
) -> tuple[list[ResponseEnvelope], list[tuple[int, int]], float]:
    """`count` concurrent overviews, each held right after its snapshot query.

    The cyclic barrier of `CONCURRENCY` makes each group of 5 hold, at once,
    its work connection (the request's unit of work) and its Program
    connection; at that instant the 2 pools' checkouts are recorded.
    """
    barrier = threading.Barrier(CONCURRENCY)
    held: list[tuple[int, int]] = []
    lock = threading.Lock()
    assert runtime.program_read_engine is not None
    program_engine = runtime.program_read_engine

    def after(_connection: object, _cursor: object, statement: str, *_rest: object) -> None:
        if SNAPSHOT_MARK not in statement:
            return
        barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)
        with lock:
            held.append(
                (
                    int(runtime.work_engine.pool.checkedout()),  # type: ignore[attr-defined]
                    int(program_engine.pool.checkedout()),  # type: ignore[attr-defined]
                )
            )
        barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)

    event.listen(program_engine, "after_cursor_execute", after)
    started = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=count) as pool:
            envelopes = list(
                pool.map(lambda index: _overview(runtime, program, index), range(count))
            )
    finally:
        event.remove(program_engine, "after_cursor_execute", after)
    return envelopes, held, time.monotonic() - started


def test_five_concurrent_overviews_through_the_gateway_pools_complete_without_stall(
    overview_runtime: GatewayRuntime,
) -> None:
    program = _seeded_program(overview_runtime)
    envelopes, held, elapsed = _overviews_held_at_the_snapshot(
        overview_runtime, program, CONCURRENCY
    )
    assert [envelope.error for envelope in envelopes] == [None] * CONCURRENCY
    digests = {envelope.to_canonical_dict()["result"]["overview_sha256"] for envelope in envelopes}
    assert len(digests) == 1
    # At the barrier every request held its work connection and its Program
    # connection: the whole work pool, and 5 Program connections beside it.
    assert held == [(CONCURRENCY, CONCURRENCY)] * CONCURRENCY
    # No stall: far below the Program engine's 1 s checkout timeout per wait,
    # and nothing waited for the work pool's 30 s.
    assert elapsed < BARRIER_TIMEOUT_SECONDS / 3, elapsed
    assert overview_runtime.program_read_engine is not None
    assert overview_runtime.program_read_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    assert overview_runtime.work_engine.pool.checkedout() == 0  # type: ignore[attr-defined]


def test_ten_concurrent_overviews_queue_on_the_work_pool_and_complete(
    overview_runtime: GatewayRuntime,
) -> None:
    program = _seeded_program(overview_runtime)
    envelopes, held, _elapsed = _overviews_held_at_the_snapshot(
        overview_runtime, program, 2 * CONCURRENCY
    )
    # All 10 complete: none was refused `unavailable` for want of a Program
    # connection, none failed a work checkout.
    assert [envelope.error for envelope in envelopes] == [None] * (2 * CONCURRENCY)
    # They ran in 2 groups of 5: while 5 held both connections the other 5
    # were queued on the work pool -- the Program pool never held more than
    # the 5 requests holding a work connection.
    assert len(held) == 2 * CONCURRENCY
    assert {work for work, _program in held} == {CONCURRENCY}
    assert {program_out for _work, program_out in held} == {CONCURRENCY}


# --- reports.commit recomputes through the gateway's pools (worker M5) ----------


def _invoke(runtime: GatewayRuntime, command: Command, purpose: Purpose) -> ResponseEnvelope:
    return runtime.service.invoke(
        RequestMetadata(
            request_id=issue_identifier(IdKind.CORRELATION),
            capability=command.capability,
            purpose=purpose,
            principal_id=PRINCIPAL,
            requested_at=datetime.now(UTC),
        ),
        command,
        principal=Principal(
            principal_id=PRINCIPAL, kind=PrincipalKind.OPERATOR, authenticated=True
        ),
    )


def _report(
    cycle: str,
    stage: IntelligenceStage,
    key: str,
    *,
    dependencies: tuple[str, ...] = (),
    structured_content: dict[str, object] | None = None,
) -> CommitIntelligenceArtifact:
    return CommitIntelligenceArtifact(
        cycle_run_id=cycle,
        stage=stage,
        artifact_kind=ARTIFACT_KIND_FOR_STAGE[stage],
        producer_task_id=f"pool-{stage.value}",
        producer_task_name="Pool report",
        automation_platform="abacus_chatllm",
        report_date="2026-10-24",
        title="Pool report",
        body_markdown="Synthetic pool report",
        artifact_state=ArtifactState.PARTIAL,
        schema_version="1",
        idempotency_key=f"pool-{key}",
        focus_area_id=FocusAreaId.PROJECT_PROGRAM_PULSE,
        source_lane=SourceLaneId.MY_PA if stage is IntelligenceStage.RESEARCHER else None,
        structured_content=structured_content,
        dependency_report_ids=dependencies,
    )


def _committed(envelope: ResponseEnvelope) -> str:
    assert envelope.error is None, envelope.error
    result = envelope.to_canonical_dict()["result"]
    return str(result["report_id"] if "report_id" in result else result["cycle_run_id"])


def _researcher_in_its_own_cycle(runtime: GatewayRuntime, index: int) -> tuple[str, str]:
    """A cycle with a collector and a researcher: `(cycle, researcher)`.

    One cycle per concurrent commit, so the 5 synthesizers share no head.
    """
    cycle = _committed(
        _invoke(
            runtime,
            BeginIntelligenceCycle(
                cycle_id=CYCLE_MORNING_INTELLIGENCE,
                business_date=f"2026-10-{index + 1:02d}",
                idempotency_key=f"pool-cycle-{index}",
            ),
            Purpose.REPORT_AUTHORING,
        )
    )
    collector = _committed(
        _invoke(
            runtime,
            _report(cycle, IntelligenceStage.COLLECTOR, f"collector-{index}"),
            Purpose.REPORT_AUTHORING,
        )
    )
    researcher = _committed(
        _invoke(
            runtime,
            _report(
                cycle,
                IntelligenceStage.RESEARCHER,
                f"researcher-{index}",
                dependencies=(collector,),
            ),
            Purpose.REPORT_AUTHORING,
        )
    )
    return cycle, researcher


def test_a_commit_recompute_draws_only_from_the_program_pool_and_completes_at_five(
    overview_runtime: GatewayRuntime,
) -> None:
    runtime = overview_runtime
    program = _seeded_program(runtime)
    overview = _overview(runtime, program, 0).to_canonical_dict()["result"]
    block = {
        PROGRAM_REFERENCE_BLOCK_KEY: {
            "block_schema_version": 1,
            "program_entity_ids": [program],
            "overview_sha256": overview["overview_sha256"],
            "source_cutoff_at": overview["source_cutoff_at"],
        }
    }
    chains = [_researcher_in_its_own_cycle(runtime, index) for index in range(CONCURRENCY)]
    barrier = threading.Barrier(CONCURRENCY)
    held: list[tuple[int, int]] = []
    lock = threading.Lock()
    assert runtime.program_read_engine is not None
    program_engine = runtime.program_read_engine

    def after(_connection: object, _cursor: object, statement: str, *_rest: object) -> None:
        # At its snapshot query every recompute holds its request's work
        # connection and its one Program connection.
        if SNAPSHOT_MARK not in statement:
            return
        barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)
        with lock:
            held.append(
                (
                    int(runtime.work_engine.pool.checkedout()),  # type: ignore[attr-defined]
                    int(program_engine.pool.checkedout()),  # type: ignore[attr-defined]
                )
            )
        barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)

    def commit(index: int) -> ResponseEnvelope:
        cycle, researcher = chains[index]
        return _invoke(
            runtime,
            _report(
                cycle,
                IntelligenceStage.SYNTHESIZER,
                f"synthesizer-{index}",
                dependencies=(researcher,),
                structured_content=block,
            ),
            Purpose.REPORT_AUTHORING,
        )

    event.listen(program_engine, "after_cursor_execute", after)
    started = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            envelopes = list(pool.map(commit, range(CONCURRENCY)))
    finally:
        event.remove(program_engine, "after_cursor_execute", after)
    elapsed = time.monotonic() - started
    report_ids = [_committed(envelope) for envelope in envelopes]
    # All 5 held the whole work pool and 5 Program connections at once: the
    # recompute never took a second work connection.
    assert held == [(CONCURRENCY, CONCURRENCY)] * CONCURRENCY
    assert elapsed < BARRIER_TIMEOUT_SECONDS / 3, elapsed
    with runtime.work_engine.connect() as connection:
        states = connection.execute(
            text(
                "SELECT program_verification_state FROM knowledge.intelligence_artifact_manifests "
                "WHERE artifact_id = ANY(:ids)"
            ),
            {"ids": report_ids},
        ).scalars()
        assert sorted(states) == ["verified_at_commit"] * CONCURRENCY
    assert program_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    assert runtime.work_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
