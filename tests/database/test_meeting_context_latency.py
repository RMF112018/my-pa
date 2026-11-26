"""WP5-C (WP5-R1 F-1): the latency guard of `meetings.context.read` on the WP4 latency seed.

The `database` tier. The WP4 latency set (`test_communications_search_latency._seed`:
3,500 messages, 28,000 participant rows, every message inside a 14-day window)
is bulk-written under a real Meeting partition, then batches of 1 and 10
Meetings are read end to end through `MeetingContextReads` (unit of work, every
statement, the Python assembly) at the defaults (14 days, 15 per Meeting) and
at the maximum (90 days, 50 per Meeting).

Every Meeting asks with every criterion, in the dense shape: 8 attendees, three
identifiers, a Project number that occurs in the corpus, and title terms that
are common words (nearly every message matches them).

The p50 and p95 over `RUNS` runs are recorded (`record_property`, printed under
`-s`). The assertion is the loose test ceiling of ruling D15 (3 s at p95); the
D15 budget itself is evidence, and the Manager's real-corpus run its authority.
Every value is synthetic.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Final

import pytest
from sqlalchemy import update

from my_pa.application.commands import CreateMeeting
from my_pa.application.meeting_context import MeetingContextReads, MeetingContextRequest
from my_pa.infrastructure.persistence.tables import projects
from tests.contract.test_meeting_mcp import _insert_partition
from tests.database.communications_search_world import NOW, unit_of_work
from tests.database.test_communications_search_latency import _seed
from tests.database.test_task_record_events import Runtime

pytestmark = pytest.mark.database

RUNS: Final = 20
CEILING_SECONDS: Final = 3.0
#: A synthetic Project number that occurs in the seed's text (`RFI 174`).
NUMBER: Final = "174"


def _timed(call: Callable[[], object]) -> tuple[float, float]:
    call()  # warm the plan and the cache
    samples = []
    for _ in range(RUNS):
        start = time.perf_counter()
        call()
        samples.append(time.perf_counter() - start)
    samples.sort()
    return statistics.median(samples), samples[int(0.95 * (len(samples) - 1))]


def test_the_context_latency_on_the_wp4_seed(
    disposable_database: str, record_property: Callable[[str, object], None]
) -> None:
    runtime = Runtime(disposable_database)
    try:
        with runtime.work_engine.begin() as connection:
            partition = _insert_partition(connection)
            connection.execute(
                update(projects)
                .where(projects.c.project_id == partition.project_id)
                .values(project_number=NUMBER)
            )
        principal_id = partition.principal.principal_id
        _seed(runtime.work_engine, principal_id)
        with runtime.work_engine.begin() as connection:
            for table in ("messages", "participants", "identifiers", "observations"):
                connection.exec_driver_sql(f"ANALYZE knowledge.communication_{table}")
        ids = []
        for k in range(10):
            created = runtime.ok(
                CreateMeeting(
                    title=f"Concrete inspection crane {k}",
                    start_at=NOW - timedelta(hours=3),
                    timezone_name="UTC",
                    idempotency_key=f"latency-{k}",
                    attendees=tuple(
                        {"email": f"person{(k * 13 + j) % 600}@example.invalid"} for j in range(8)
                    ),
                    description=f"RFI {k * 7}, RFI {k * 7 + 1} and CO 3",
                    project_id=partition.project_id,
                ),
                principal_id=principal_id,
            )
            ids.append(str(created["meeting"]["meeting_id"]))
        service = MeetingContextReads(
            unit_of_work=unit_of_work(runtime.work_engine), clock=lambda: NOW
        )

        def read(count: int, **bounds: int) -> Callable[[], object]:
            request = MeetingContextRequest(meeting_ids=ids[:count], **bounds)
            return lambda: service.read(principal_id, request)

        answer = service.read(principal_id, MeetingContextRequest(meeting_ids=ids))
        sections = [context.communications for context in answer.meetings]
        assert all(section.matched_total > 15 for section in sections)
        assert all(section.inputs.project_number.value == "used" for section in sections)
        # The Project number occurs in the corpus: its branch returns rows, not only asks.
        assert any(
            "project_number" in [r.value for r in m.matched_by]
            for section in sections
            for m in section.messages
        )
        shapes: dict[str, Callable[[], object]] = {
            "context_1_defaults": read(1),
            "context_10_defaults": read(10),
            "context_1_maximum": read(1, lookback_days=90, per_meeting_limit=50),
            "context_10_maximum": read(10, lookback_days=90, per_meeting_limit=50),
        }
        figures = {}
        for name, call in shapes.items():
            p50, p95 = _timed(call)
            figures[name] = (round(p50 * 1000, 1), round(p95 * 1000, 1))
            record_property(name, f"p50={p50 * 1000:.1f}ms p95={p95 * 1000:.1f}ms")
        print(f"\ncontext latency (ms, p50/p95) over {RUNS} runs:")
        for name, (p50, p95) in figures.items():
            print(f"  {name}: {p50} / {p95}")
        assert all(p95 / 1000 < CEILING_SECONDS for _, p95 in figures.values()), figures
    finally:
        runtime.close()
