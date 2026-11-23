"""The ingestion poll step's single flight against PostgreSQL (communications contract 19).

`COMMS_INGEST_LOCK_KEY` held by **another process** (a child Python holding a
session advisory lock on its own connection) makes this process's ingestion
step skip without running, while the daily step on its own key still runs in
the same iteration; once the child lets go, the step takes the lock.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from datetime import UTC, date, datetime
from typing import Final
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine

from my_pa.infrastructure.jobs.cycle_scheduler import (
    COMMS_INGEST_LOCK_KEY,
    CYCLE_SCHEDULER_LOCK_KEY,
    DailyStep,
    IntervalStep,
    run_scheduler_steps,
    single_flight,
)

pytestmark = pytest.mark.database

WHEN: Final = datetime(2026, 11, 22, 17, tzinfo=UTC)

_HOLDER: Final = """
import sys
import psycopg
with psycopg.connect(sys.argv[1], autocommit=True) as connection:
    held = connection.execute("SELECT pg_try_advisory_lock(%s)", (int(sys.argv[2]),)).fetchone()[0]
    print("held" if held else "busy", flush=True)
    sys.stdin.readline()
"""


def _holder(url: str, key: int) -> subprocess.Popen[str]:
    dsn = url.replace("postgresql+psycopg://", "postgresql://", 1)
    child = subprocess.Popen(  # noqa: S603 - a fixed interpreter and script
        [sys.executable, "-c", _HOLDER, dsn, str(key)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None
    assert child.stdout.readline().strip() == "held"
    return child


def _release(child: subprocess.Popen[str]) -> None:
    assert child.stdin is not None
    child.stdin.write("\n")
    child.stdin.flush()
    assert child.wait(timeout=30) == 0


def test_sql_another_process_holding_the_ingest_key_skips_only_the_ingest_step(
    migrated_engine: Engine, cloned_database_url: str
) -> None:
    child = _holder(cloned_database_url, COMMS_INGEST_LOCK_KEY)
    try:
        with single_flight(migrated_engine, key=COMMS_INGEST_LOCK_KEY) as held:
            assert held is False
        with single_flight(migrated_engine, key=CYCLE_SCHEDULER_LOCK_KEY) as daily:
            assert daily is True
        days: list[date] = []

        def run_for(business_date: date) -> bool:
            days.append(business_date)
            return True

        result = run_scheduler_steps(
            migrated_engine,
            steps=(
                DailyStep(zone=ZoneInfo("America/New_York"), run_for=run_for),
                IntervalStep(
                    name="comms_ingest",
                    event="comms_ingest",
                    lock_key=COMMS_INGEST_LOCK_KEY,
                    interval_seconds=900,
                    run_once=lambda: pytest.fail("polled without the lock"),
                ),
            ),
            stop=threading.Event(),
            clock=lambda: WHEN,
            log=lambda fields: None,
            max_iterations=1,
        )
        assert result.steps["comms_ingest"].skipped == 1
        assert result.steps["daily_cycle"].runs == 1
        assert days == [date(2026, 11, 22)]
    finally:
        _release(child)
    with single_flight(migrated_engine, key=COMMS_INGEST_LOCK_KEY) as after:
        assert after is True
