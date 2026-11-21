"""The daily cycle scheduler against disposable PostgreSQL (ADR-010 amendment of 2026-11-20).

The store transitions, `reports.begin_cycle` converging under concurrency, a
ChatLLM fallback converging on the scheduler's cycle, a commit racing a close,
and the single-flight lock between two scheduler processes.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from typing import Final
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, text

from my_pa.application.commands import BeginIntelligenceCycle, CommitIntelligenceArtifact
from my_pa.application.daily_cycle import DailyCycleRunner
from my_pa.application.intelligence import CycleClosureOutcome, close_cycle
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    CYCLE_MORNING_INTELLIGENCE,
    ArtifactKind,
    ArtifactState,
    CycleState,
    FocusAreaId,
    IntelligenceStage,
)
from my_pa.domain.intelligence.daily_cycle import scheduled_idempotency_key
from my_pa.infrastructure.jobs.cycle_scheduler import run_cycle_scheduler, single_flight
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.intelligence import SqlIntelligenceStore
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.conftest import DEFAULT_LIMITS, metadata_for, operator

pytestmark = pytest.mark.database

WHEN: Final = datetime(2026, 11, 20, 5, tzinfo=UTC)
TODAY: Final = date(2026, 11, 20)


def _uow(engine: Engine) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(engine, audit=SqlAlchemyAuditSink(engine))


def _service(engine: Engine) -> ApplicationService:
    return ApplicationService(
        unit_of_work=lambda: _uow(engine), limits=DEFAULT_LIMITS, clock=lambda: WHEN
    )


def _invoke(service: ApplicationService, principal: Principal, command: object) -> ResponseEnvelope:
    return service.invoke(
        metadata_for(command.capability, Purpose.REPORT_AUTHORING, principal),  # type: ignore[attr-defined]
        command,  # type: ignore[arg-type]
        principal=principal,
    )


def _begin(
    service: ApplicationService, principal: Principal, key: str, day: date = TODAY
) -> dict[str, object]:
    envelope = _invoke(
        service,
        principal,
        BeginIntelligenceCycle(
            cycle_id=CYCLE_MORNING_INTELLIGENCE,
            business_date=day.isoformat(),
            idempotency_key=key,
        ),
    )
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    return envelope.result


def _commit(
    service: ApplicationService, principal: Principal, cycle_run_id: str, key: str
) -> ResponseEnvelope:
    return _invoke(
        service,
        principal,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle_run_id,
            stage=IntelligenceStage.COLLECTOR,
            artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES,
            producer_task_id="task-collector",
            producer_task_name="Collector",
            automation_platform="abacus_chatllm",
            report_date=TODAY.isoformat(),
            title="Collector",
            body_markdown="# Collector\n\nsynthetic",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key=key,
            focus_area_id=FocusAreaId.COMMUNICATIONS,
        ),
    )


def _row(engine: Engine, cycle_run_id: str) -> tuple[str, int, datetime | None]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT state, version, finished_at FROM knowledge.intelligence_cycle_runs"
                " WHERE cycle_run_id = :id"
            ),
            {"id": cycle_run_id},
        ).one()
    return str(row.state), int(row.version), row.finished_at


def _runner(engine: Engine, principal: Principal) -> DailyCycleRunner:
    return DailyCycleRunner(
        service=_service(engine),
        unit_of_work=lambda: _uow(engine),
        principal=principal,
        clock=lambda: WHEN,
    )


def test_sql_close_writes_complete_or_cancelled_once(migrated_engine: Engine) -> None:
    service = _service(migrated_engine)
    principal = operator()
    used = str(_begin(service, principal, "used", day=date(2026, 11, 18))["cycle_run_id"])
    unused = str(_begin(service, principal, "unused", day=date(2026, 11, 19))["cycle_run_id"])
    assert _commit(service, principal, used, "commit-used").error is None

    outcome = _runner(migrated_engine, principal)(TODAY)
    assert (outcome.closed_complete, outcome.closed_cancelled, outcome.close_failed) == (1, 1, 0)
    assert _row(migrated_engine, used) == ("complete", 2, WHEN)
    assert _row(migrated_engine, unused) == ("cancelled", 2, WHEN)

    with migrated_engine.begin() as connection:
        again = close_cycle(
            SqlIntelligenceStore(connection, principal.principal_id),
            principal_id=principal.principal_id,
            cycle_run_id=used,
            at=WHEN,
        )
    assert again.outcome is CycleClosureOutcome.ALREADY_CLOSED
    assert _row(migrated_engine, used) == ("complete", 2, WHEN)


def test_sql_chatllm_fallback_converges_on_the_scheduled_cycle(migrated_engine: Engine) -> None:
    service = _service(migrated_engine)
    principal = operator()
    scheduled = _runner(migrated_engine, principal)(TODAY)
    assert scheduled.created
    fallback = _begin(service, principal, "chatllm-fallback")
    assert fallback["cycle_run_id"] == scheduled.cycle_run_id
    assert (fallback["created"], fallback["replayed"]) == (False, True)
    rerun = _runner(migrated_engine, principal)(TODAY)
    assert (rerun.cycle_run_id, rerun.replayed) == (scheduled.cycle_run_id, True)
    with migrated_engine.connect() as connection:
        cycles = connection.execute(
            text("SELECT count(*) FROM knowledge.intelligence_cycle_runs")
        ).scalar_one()
        audited = connection.execute(
            text(
                "SELECT count(*) FROM knowledge.audit_events"
                " WHERE capability = 'reports.begin_cycle' AND principal_id = :p"
            ),
            {"p": principal.principal_id},
        ).scalar_one()
    assert cycles == 1
    # Every begin, the scheduler's included, went through the audited path.
    assert audited == 3
    assert scheduled.cycle_run_id is not None
    assert _row(migrated_engine, scheduled.cycle_run_id)[0] == "open"
    assert scheduled_idempotency_key(TODAY) == "auto-morning_intelligence-2026-11-20"


def test_sql_concurrent_begins_with_different_keys_make_one_cycle(migrated_engine: Engine) -> None:
    service = _service(migrated_engine)
    principal = operator()

    def _race(key: str) -> dict[str, object]:
        return _begin(service, principal, key)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_race, ["race-a", "race-b", "race-c", "race-d"]))
    assert len({result["cycle_run_id"] for result in results}) == 1
    assert [result["created"] for result in results].count(True) == 1
    with migrated_engine.connect() as connection:
        cycles = connection.execute(
            text("SELECT count(*) FROM knowledge.intelligence_cycle_runs")
        ).scalar_one()
    assert cycles == 1


def test_sql_a_commit_racing_a_close_is_refused_after_it(migrated_engine: Engine) -> None:
    service = _service(migrated_engine)
    principal = operator()
    cycle = str(_begin(service, principal, "raced", day=date(2026, 11, 19))["cycle_run_id"])
    with ThreadPoolExecutor(max_workers=1) as pool, migrated_engine.begin() as connection:
        store = SqlIntelligenceStore(connection, principal.principal_id)
        locked = store.cycle_for_close(principal.principal_id, cycle)
        assert locked is not None
        pending = pool.submit(_commit, service, principal, cycle, "raced-commit")
        time.sleep(0.5)
        # The commit is waiting on the row lock the close holds.
        assert not pending.done()
        closed = close_cycle(
            store, principal_id=principal.principal_id, cycle_run_id=cycle, at=WHEN
        )
        assert closed.outcome is CycleClosureOutcome.CANCELLED
    late = pending.result(timeout=30)
    assert late.error is not None
    assert late.error.code is ErrorCode.CONFLICT
    assert late.error.safe_details == ("cycle_run_id", "cycle_closed")
    assert _row(migrated_engine, cycle)[0] == CycleState.CANCELLED.value


def test_sql_single_flight_admits_one_scheduler_at_a_time(migrated_engine: Engine) -> None:
    with single_flight(migrated_engine) as first:
        assert first is True
        with single_flight(migrated_engine) as second:
            assert second is False
        # A loop that cannot take the lock skips without running.
        skipped = run_cycle_scheduler(
            migrated_engine,
            zone=ZoneInfo("America/New_York"),
            run_for=lambda business_date: pytest.fail("ran without the lock"),
            stop=threading.Event(),
            clock=lambda: WHEN,
            log=lambda fields: None,
            max_iterations=1,
        )
        assert (skipped.skipped, skipped.runs) == (1, 0)
    with single_flight(migrated_engine) as after:
        assert after is True
