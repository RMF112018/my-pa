"""Schedule Scenarios S6-1: CPM properties over seeded random networks on `std` (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` section 3.13 (3):

* on general networks (every relationship type, leads and lags, constraints,
  progress, both progress policies): byte-identical output across 2 runs and
  across input permutations; `FF <= TF`; `TF = W(C, RS, LS) = W(C, EF, LF)`;
* restricted to FS-only networks with non-negative lags and no constraint,
  progress or `must_finish_by` (R8-F03: SS/FF/SF and leads admit
  dangling-finish float and the duration paradox): at least 1 activity has
  `TF = 0`; every critical path ends at an activity with `EF = PF`;
  increasing one remaining duration never decreases `PF`.
"""

from __future__ import annotations

import random
from dataclasses import replace
from typing import Final

import pytest

from my_pa.domain.schedule.scenario.calendar import compile_calendar, working_minutes
from my_pa.domain.schedule.scenario.canonical import content_sha256, result_bytes
from my_pa.domain.schedule.scenario.cpm import CpmStatus, result_document, run_cpm
from my_pa.domain.schedule.scenario.model import (
    ActivityState,
    ConstraintType,
    ProgressPolicy,
    ScenarioActivity,
    ScenarioContent,
    format_instant,
)
from tests.fixtures.schedule_scenario import STD, at, link, network, task

SEEDS: Final = range(60)
CALENDAR: Final = compile_calendar(STD)
DAY: Final = 480


def _rng(seed: int) -> random.Random:
    """A seeded, test-only generator (section 3.13); never security material."""
    return random.Random(seed)  # noqa: S311 - deterministic test data, not a secret


def _general(rng: random.Random) -> ScenarioContent:
    count = rng.randint(2, 18)
    names = [f"N{index:02d}" for index in range(count)]
    activities = []
    for index, name in enumerate(names):
        duration = rng.choice([0, 240, DAY, 2 * DAY, 3 * DAY + 120])
        state = rng.random()
        if index < 3 and state < 0.2:
            activities.append(task(name, 0, started="01-04 08:00", finished="01-05 12:00"))
            continue
        if index < 4 and state < 0.4:
            activities.append(task(name, duration, started="01-05 08:00"))
            continue
        constraints = []
        if rng.random() < 0.15:
            constraints.append(
                (rng.choice([ConstraintType.SNET, ConstraintType.FNET]), "01-08 12:00")
            )
        if rng.random() < 0.15:
            constraints.append(
                (rng.choice([ConstraintType.SNLT, ConstraintType.FNLT]), "01-13 16:00")
            )
        if not constraints and rng.random() < 0.05:
            constraints.append(
                (rng.choice([ConstraintType.MSO, ConstraintType.MFO]), "01-12 08:00")
            )
        activities.append(task(name, duration, constraints=constraints))
    relationships = [
        link(names[i], names[j], rng.choice(["FS", "SS", "FF", "SF"]), rng.randint(-600, 900))
        for i in range(count)
        for j in range(i + 1, count)
        if rng.random() < 0.25
    ]
    return network(
        activities,
        relationships,
        data_date="01-06 00:00",
        progress_policy=rng.choice(list(ProgressPolicy)),
        must_finish_by=rng.choice([None, "01-20 16:00"]),
    )


def _fs_only(rng: random.Random) -> ScenarioContent:
    count = rng.randint(2, 20)
    names = [f"N{index:02d}" for index in range(count)]
    return network(
        [task(name, rng.choice([0, 120, DAY, 2 * DAY, 1000])) for name in names],
        [
            link(names[i], names[j], "FS", rng.choice([0, 0, 60, 480, 900]))
            for i in range(count)
            for j in range(i + 1, count)
            if rng.random() < 0.3
        ],
    )


def _permuted(content: ScenarioContent, rng: random.Random) -> ScenarioContent:
    activities = list(content.activities)
    relationships = list(content.relationships)
    rng.shuffle(activities)
    rng.shuffle(relationships)
    return ScenarioContent(
        data_date=content.data_date,
        settings=content.settings,
        calendars=content.calendars,
        activities=tuple(activities),
        relationships=tuple(relationships),
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_output_is_byte_identical_across_runs_and_permutations(seed: int) -> None:
    rng = _rng(seed)
    content = _general(rng)
    first = result_bytes(result_document(run_cpm(content)))
    assert result_bytes(result_document(run_cpm(content))) == first
    for _ in range(3):
        permuted = _permuted(content, rng)
        assert content_sha256(permuted) == content_sha256(content)
        assert result_bytes(result_document(run_cpm(permuted))) == first


@pytest.mark.parametrize("seed", SEEDS)
def test_floats_are_consistent_on_general_networks(seed: int) -> None:
    result = run_cpm(_general(_rng(seed)))
    assert result.status is CpmStatus.COMPUTED, seed
    for item in result.activities:
        if item.state is ActivityState.COMPLETE:
            assert item.total_float_minutes is None
            assert item.free_float_minutes is None
            assert item.critical is False
            continue
        total = item.total_float_minutes
        assert total is not None
        assert item.free_float_minutes is not None
        assert item.free_float_minutes <= total
        assert item.remaining_start is not None
        assert total == working_minutes(CALENDAR, item.early_finish, item.late_finish)
        assert total == working_minutes(CALENDAR, item.remaining_start, item.late_start), (
            seed,
            item.key,
            format_instant(item.remaining_start),
        )


@pytest.mark.parametrize("seed", SEEDS)
def test_fs_only_networks_have_a_zero_float_critical_path_to_the_finish(seed: int) -> None:
    result = run_cpm(_fs_only(_rng(seed)))
    assert result.status is CpmStatus.COMPUTED
    project_finish = result.summary.project_finish
    by_key = {item.key: item for item in result.activities}
    assert any(item.total_float_minutes == 0 for item in result.activities)
    assert all(item.total_float_minutes >= 0 for item in result.activities)  # type: ignore[operator]
    assert result.critical_paths
    for path in result.critical_paths:
        assert by_key[path[-1]].early_finish == project_finish


@pytest.mark.parametrize("seed", SEEDS)
def test_lengthening_one_duration_never_shortens_the_project(seed: int) -> None:
    rng = _rng(seed)
    content = _fs_only(rng)
    base = run_cpm(content).summary.project_finish
    assert base is not None
    victim = rng.randrange(len(content.activities))
    activity: ScenarioActivity = content.activities[victim]
    longer = replace(
        activity,
        remaining_minutes=(activity.remaining_minutes or 0) + rng.choice([1, 60, DAY, 1500]),
    )
    activities = list(content.activities)
    activities[victim] = longer
    lengthened = run_cpm(replace(content, activities=tuple(activities))).summary.project_finish
    assert lengthened is not None
    assert lengthened >= base


def test_general_generator_reaches_every_state_and_policy() -> None:
    states: set[ActivityState] = set()
    policies: set[ProgressPolicy] = set()
    for seed in SEEDS:
        content = _general(_rng(seed))
        policies.add(content.settings.progress_policy)
        states |= {item.state for item in run_cpm(content).activities}
    assert states == set(ActivityState)
    assert policies == set(ProgressPolicy)


def test_the_data_date_bounds_every_remaining_start() -> None:
    result = run_cpm(_general(_rng(7)))
    data_date = at("01-06 00:00")
    for item in result.activities:
        if item.remaining_start is not None:
            assert item.remaining_start >= data_date
