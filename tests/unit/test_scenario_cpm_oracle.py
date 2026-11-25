"""Schedule Scenarios S6-1: the CPM engine against an independent longest-path oracle (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` section 3.13 (2). On
an all-working calendar every calendar function is plain arithmetic, so the
early start of `j` is the data date plus the longest of **every enumerated
path** ending at `j` (or 0), with edge weights `FS d_i + L`, `SS L`,
`FF d_i + L - d_j`, `SF L - d_j`; the late start is the project finish minus
the longest path from `j` to a sink `s` (plus `d_s`). TF and the critical set
follow. The oracle enumerates paths explicitly and shares no code with the
engine. 2,000 seeded random DAGs of 2..7 activities, all 4 types, lags in
[-480, 480], durations in [0, 960], no constraint or progress.

S7-0 (import contract section 11.7): the same oracle checks `my-pa-cpm-v2`.
On an all-working calendar `next_work` and `prev_end` are the identity, so a
zero-duration activity written `start_milestone` or `finish_milestone` has the
oracle's dates, and a fixed lag calendar (`calendar:all`) measures lags exactly
like the activities' own calendar.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from typing import Final

import pytest

from my_pa.domain.schedule.scenario.cpm import ENGINE_VERSION_V2, CpmStatus, run_cpm
from my_pa.domain.schedule.scenario.model import (
    ActivityKind,
    FixedLagCalendar,
    LagCalendar,
    LagCalendarSetting,
    ScenarioActivity,
    ScenarioCalendar,
    parse_instant,
)
from tests.fixtures.schedule_scenario import key, link, milestone, network, task

ALL_DAY: Final = ScenarioCalendar("all", (((0, 1440),),) * 7)
DATA_DATE: Final = "2027-01-04T00:00"
NETWORKS: Final = 2_000
BATCHES: Final = 8
TYPES: Final = ("FS", "SS", "FF", "SF")

Edge = tuple[int, int, str, int]


def _rng(seed: int) -> random.Random:
    """A seeded, test-only generator (section 3.13); never security material."""
    return random.Random(seed)  # noqa: S311 - deterministic test data, not a secret


def _weight(edge: Edge, durations: list[int]) -> int:
    i, j, kind, lag = edge
    return {
        "FS": durations[i] + lag,
        "SS": lag,
        "FF": durations[i] + lag - durations[j],
        "SF": lag - durations[j],
    }[kind]


def _paths_into(target: int, edges: list[Edge]) -> Iterator[list[Edge]]:
    """Every path (as edge lists) that ends at `target`, the empty path included."""
    yield []
    for edge in edges:
        if edge[1] == target:
            for prefix in _paths_into(edge[0], edges):
                yield [*prefix, edge]


def _paths_from(source: int, edges: list[Edge], sinks: set[int]) -> Iterator[list[Edge]]:
    """Every path from `source` to a sink."""
    if source in sinks:
        yield []
    for edge in edges:
        if edge[0] == source:
            for suffix in _paths_from(edge[1], edges, sinks):
                yield [edge, *suffix]


def _random_dag(rng: random.Random) -> tuple[list[int], list[Edge]]:
    count = rng.randint(2, 7)
    durations = [rng.randint(0, 960) for _ in range(count)]
    edges = [
        (i, j, rng.choice(TYPES), rng.randint(-480, 480))
        for i in range(count)
        for j in range(i + 1, count)
        if rng.random() < 0.45
    ]
    return durations, edges


def _check(seed: int, *, v2: bool = False) -> None:
    rng = _rng(seed)
    durations, edges = _random_dag(rng)
    # Shuffle the names so key order is not the generation order.
    names = [f"N{index}" for index in range(len(durations))]
    rng.shuffle(names)
    lag_calendar: LagCalendarSetting = rng.choice(list(LagCalendar))
    activities = [task(names[i], durations[i]) for i in range(len(durations))]
    if v2:
        # A separate stream, so the v1 networks are exactly the S6 ones.
        edged = _rng(1_000_000 + seed)
        durations = [0 if edged.random() < 0.5 else value for value in durations]
        activities = [_v2_activity(names[i], durations[i], edged) for i in range(len(durations))]
        lag_calendar = FixedLagCalendar("all") if edged.random() < 0.5 else lag_calendar
    content = network(
        activities,
        [link(names[i], names[j], kind, lag) for i, j, kind, lag in edges],
        data_date=DATA_DATE,
        calendars=(ALL_DAY,),
        default_calendar="all",
        lag_calendar=lag_calendar,
    )
    result = run_cpm(content)
    assert result.status is CpmStatus.COMPUTED, seed
    origin = parse_instant(DATA_DATE)
    count = len(durations)
    early = [
        origin
        + max(sum(_weight(edge, durations) for edge in path) for path in _paths_into(j, edges))
        for j in range(count)
    ]
    finish = max(early[j] + durations[j] for j in range(count))
    sinks = {j for j in range(count) if not any(edge[0] == j for edge in edges)}
    late = [
        min(
            finish
            - durations[path[-1][1] if path else j]
            - sum(_weight(e, durations) for e in path)
            for path in _paths_from(j, edges, sinks)
        )
        for j in range(count)
    ]
    by_key = {item.key: item for item in result.activities}
    assert result.summary.project_finish == finish, seed
    critical = set()
    for j in range(count):
        item = by_key[key(names[j])]
        total_float = late[j] - early[j]
        assert (item.early_start, item.early_finish) == (early[j], early[j] + durations[j]), seed
        assert (item.late_start, item.late_finish) == (late[j], late[j] + durations[j]), seed
        assert item.total_float_minutes == total_float, seed
        assert item.critical is (total_float <= 0), seed
        if total_float <= 0:
            critical.add(item.key)
    assert {item.key for item in result.activities if item.critical} == critical


def _v2_activity(name: str, duration: int, rng: random.Random) -> ScenarioActivity:
    if duration:
        return task(name, duration)
    return milestone(
        name,
        rng.choice(
            [ActivityKind.START_MILESTONE, ActivityKind.FINISH_MILESTONE, ActivityKind.MILESTONE]
        ),
    )


@pytest.mark.parametrize("batch", range(BATCHES))
def test_cpm_v2_matches_the_longest_path_oracle(batch: int) -> None:
    """S7-0: `my-pa-cpm-v2` with edged milestones and fixed lag calendars, same oracle."""
    size = NETWORKS // BATCHES
    for seed in range(batch * size, (batch + 1) * size):
        _check(seed, v2=True)


def test_an_edged_milestone_network_runs_on_v2() -> None:
    content = network(
        [task("A", 60), milestone("M", ActivityKind.START_MILESTONE)],
        [link("A", "M")],
        data_date=DATA_DATE,
        calendars=(ALL_DAY,),
        default_calendar="all",
    )
    assert run_cpm(content).engine_version == ENGINE_VERSION_V2


@pytest.mark.parametrize("batch", range(BATCHES))
def test_cpm_matches_the_longest_path_oracle(batch: int) -> None:
    size = NETWORKS // BATCHES
    for seed in range(batch * size, (batch + 1) * size):
        _check(seed)


def test_the_oracle_covers_every_relationship_type_and_sign() -> None:
    seen: set[tuple[str, bool]] = set()
    for seed in range(NETWORKS):
        _, edges = _random_dag(_rng(seed))
        seen |= {(kind, lag < 0) for _, _, kind, lag in edges}
    assert seen == {(kind, negative) for kind in TYPES for negative in (False, True)}
