"""CPM Workbench S5b-2: the A-to-B delta over 2 publications of 25,000 rows each (database, slow).

Worker and capabilities contract section 3.10 (Bounds) and residual U2-05: both
publications are written by the real handler (25 row batches and 25
canonicalization batches each), then `schedule_changes.list` recomputes the
full delta. The target is a 25,000-row A-to-B scan under 5 s on the isolated
database; a miss fails here and is reported, never hidden by widening the
bound. The handler's persistence time per publication is recorded beside it
(`record_testsuite_property`) for the U2-05 measurement. Every value is synthetic.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from typing import Final

import pytest

from my_pa.application.commands import ListScheduleChanges
from tests.database.schedule_capability_harness import PRINCIPAL, Activity, ScheduleRuntime

pytestmark = [pytest.mark.database, pytest.mark.slow]

ROWS: Final = 25_000
TARGET_SECONDS: Final = 5.0


@pytest.fixture
def rt(disposable_database: str) -> Iterator[ScheduleRuntime]:
    runtime = ScheduleRuntime(disposable_database)
    try:
        yield runtime
    finally:
        runtime.close()


def _side(*, changed: bool) -> list[Activity]:
    start = date(2026, 5, 4)
    activities = []
    for n in range(ROWS):
        moved = changed and n % 10 == 0
        activities.append(
            Activity(
                f"PERF-{n:06d}",
                name="Renamed activity" if changed and n % 25 == 0 else "Synthetic activity",
                path=("Synthetic WBS", f"Area {n // 1_000:02d}"),
                start=start + timedelta(days=n % 30 + (3 if moved else 0)),
                finish=start + timedelta(days=n % 30 + 10),
                page=n // 250 + 1,
            )
        )
    return activities


def test_change_scan_of_25000_rows_meets_the_target(
    rt: ScheduleRuntime,
    monkeypatch: pytest.MonkeyPatch,
    record_testsuite_property: Callable[[str, object], None],
) -> None:
    world = rt.world(PRINCIPAL, "schedperf")
    began = time.perf_counter()
    first = rt.publish(monkeypatch, world, _side(changed=False), data_date=date(2026, 5, 4))
    persisted = time.perf_counter() - began
    series = rt.scalar(
        "SELECT series_id FROM knowledge.schedule_publications WHERE publication_id = :p",
        p=first,
    )
    second = rt.publish(
        monkeypatch,
        world,
        _side(changed=True),
        data_date=date(2026, 6, 1),
        series_id=series,
    )
    assert (
        rt.scalar(
            "SELECT count(*) FROM knowledge.schedule_rows WHERE publication_id = :p", p=second
        )
        == ROWS
    )
    command = ListScheduleChanges(
        from_publication_id=first, to_publication_id=second, page_size=100
    )
    began = time.perf_counter()
    answer = rt.ok(command)
    scanned = time.perf_counter() - began
    record_testsuite_property("handler_persistence_seconds_per_25000_rows", round(persisted, 3))
    record_testsuite_property("change_scan_seconds", round(scanned, 3))
    counts = answer["counts_by_kind"]
    assert counts["start_changed"] == ROWS // 10
    assert counts["renamed"] == ROWS // 25
    assert sum(counts.values()) == ROWS // 10 + ROWS // 25
    assert len(answer["changes"]) == 100
    assert scanned < TARGET_SECONDS, (
        f"a 25,000-row change scan took {scanned:.2f} s against the {TARGET_SECONDS} s target"
    )
