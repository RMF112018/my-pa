"""The daily Morning Intelligence cycle scheduler (ADR-010 amendment of 2026-11-20), FAST.

The due rule (DST, catch-up, no backfill), the close rule and its idempotency,
the late-write refusal, `reports.begin_cycle` converging on the date's open
cycle, and a run whose close step fails still beginning the day's cycle.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import pytest

from my_pa.application.commands import (
    BeginIntelligenceCycle,
    CommitIntelligenceArtifact,
    RecordIntelligenceRunState,
)
from my_pa.application.daily_cycle import DailyCycleRunner
from my_pa.application.intelligence import (
    CycleClosureOutcome,
    InMemoryIntelligenceStore,
    close_cycle,
    stale_open_cycles,
)
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.settings import SettingsError, load_settings
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    CYCLE_MORNING_INTELLIGENCE,
    ArtifactKind,
    ArtifactState,
    CycleState,
    FocusAreaId,
    IntelligenceStage,
    ProducerRunState,
)
from my_pa.domain.intelligence.daily_cycle import (
    DEFAULT_CYCLE_TIMEZONE,
    due,
    scheduled_idempotency_key,
)
from my_pa.infrastructure.jobs import cycle_scheduler
from my_pa.infrastructure.jobs.cycle_scheduler import run_cycle_scheduler
from tests.conftest import WHEN, FakeUnitOfWork, Scene, build_service, metadata_for

NEW_YORK: Final = ZoneInfo(DEFAULT_CYCLE_TIMEZONE)
ROOT: Final = Path(__file__).resolve().parents[2]


def _ny(*parts: int, fold: int = 0) -> datetime:
    return datetime(*parts, tzinfo=NEW_YORK, fold=fold).astimezone(UTC)  # type: ignore[misc]


# ---- the due rule -------------------------------------------------------------


def test_a_fresh_process_is_due_at_once_for_the_local_date() -> None:
    # 03:30 UTC on 21 Nov is 22:30 on 20 Nov in New York: the local date wins.
    assert due(datetime(2026, 11, 21, 3, 30, tzinfo=UTC), zone=NEW_YORK, last_run=None) == date(
        2026, 11, 20
    )


def test_local_midnight_makes_the_next_date_due_once() -> None:
    last = date(2026, 11, 20)
    assert due(_ny(2026, 11, 20, 23, 59, 59), zone=NEW_YORK, last_run=last) is None
    assert due(_ny(2026, 11, 21, 0, 0), zone=NEW_YORK, last_run=last) == date(2026, 11, 21)
    assert due(_ny(2026, 11, 21, 0, 1), zone=NEW_YORK, last_run=date(2026, 11, 21)) is None


def test_a_missed_run_catches_up_once_and_never_backfills() -> None:
    # Down for four days: one run, for the latest missed date only.
    assert due(_ny(2026, 11, 24, 9, 0), zone=NEW_YORK, last_run=date(2026, 11, 20)) == date(
        2026, 11, 24
    )


def test_spring_forward_runs_once_on_the_short_day() -> None:
    # 8 March 2026: 02:00 EST jumps to 03:00 EDT.
    last = date(2026, 3, 7)
    assert due(_ny(2026, 3, 8, 0, 0), zone=NEW_YORK, last_run=last) == date(2026, 3, 8)
    assert due(_ny(2026, 3, 8, 3, 30), zone=NEW_YORK, last_run=date(2026, 3, 8)) is None
    assert due(_ny(2026, 3, 9, 0, 0), zone=NEW_YORK, last_run=date(2026, 3, 8)) == date(2026, 3, 9)


def test_fall_back_does_not_repeat_the_run_in_the_repeated_hour() -> None:
    # 1 November 2026: 02:00 EDT falls back to 01:00 EST; 01:30 happens twice.
    ran = date(2026, 11, 1)
    first = _ny(2026, 11, 1, 1, 30, fold=0)
    second = _ny(2026, 11, 1, 1, 30, fold=1)
    assert second - first == timedelta(hours=1)
    assert due(first, zone=NEW_YORK, last_run=ran) is None
    assert due(second, zone=NEW_YORK, last_run=ran) is None
    assert due(_ny(2026, 11, 2, 0, 0), zone=NEW_YORK, last_run=ran) == date(2026, 11, 2)


def test_a_naive_instant_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        due(datetime(2026, 11, 20), zone=NEW_YORK, last_run=None)


def test_the_scheduled_key_is_deterministic_per_date() -> None:
    assert scheduled_idempotency_key(date(2026, 11, 20)) == "auto-morning_intelligence-2026-11-20"


# ---- reports.begin_cycle converges on the date's open cycle ---------------------


def _invoke(service: ApplicationService, scene: Scene, command: object) -> ResponseEnvelope:
    return service.invoke(
        metadata_for(command.capability, Purpose.REPORT_AUTHORING, scene.principal),  # type: ignore[attr-defined]
        command,  # type: ignore[arg-type]
        principal=scene.principal,
    )


def _begin(
    service: ApplicationService, scene: Scene, key: str, day: str = "2026-11-20"
) -> dict[str, object]:
    envelope = _invoke(
        service,
        scene,
        BeginIntelligenceCycle(
            cycle_id=CYCLE_MORNING_INTELLIGENCE, business_date=day, idempotency_key=key
        ),
    )
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    return envelope.result


def _commit(
    service: ApplicationService, scene: Scene, cycle_run_id: str, key: str
) -> ResponseEnvelope:
    return _invoke(
        service,
        scene,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle_run_id,
            stage=IntelligenceStage.COLLECTOR,
            artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES,
            producer_task_id="task-collector",
            producer_task_name="Collector",
            automation_platform="abacus_chatllm",
            report_date="2026-11-20",
            title="Collector",
            body_markdown="# Collector\n\nsynthetic",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key=key,
            focus_area_id=FocusAreaId.COMMUNICATIONS,
        ),
    )


def _store(scene: Scene) -> InMemoryIntelligenceStore:
    store = scene.world.intelligence
    assert isinstance(store, InMemoryIntelligenceStore)
    return store


def test_a_second_key_on_the_same_date_joins_the_open_cycle(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    scheduled = _begin(service, scene, scheduled_idempotency_key(date(2026, 11, 20)))
    fallback = _begin(service, scene, "chatllm-fallback")
    assert scheduled["created"] is True
    assert fallback["cycle_run_id"] == scheduled["cycle_run_id"]
    assert (fallback["created"], fallback["replayed"]) == (False, True)
    assert fallback["receipt_id"] != scheduled["receipt_id"]
    # The new key is bound to that cycle, so it keeps replaying it.
    assert _begin(service, scene, "chatllm-fallback")["cycle_run_id"] == scheduled["cycle_run_id"]
    assert len(_store(scene).cycles) == 1


def test_the_scheduler_joins_a_cycle_chatllm_began_first(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    fallback = _begin(service, scene, "chatllm-first")
    scheduled = _begin(service, scene, scheduled_idempotency_key(date(2026, 11, 20)))
    assert scheduled["cycle_run_id"] == fallback["cycle_run_id"]
    assert (scheduled["created"], scheduled["replayed"]) == (False, True)


def test_a_reused_key_with_another_date_is_still_an_idempotency_conflict(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    _begin(service, scene, "same-key")
    envelope = _invoke(
        service,
        scene,
        BeginIntelligenceCycle(
            cycle_id=CYCLE_MORNING_INTELLIGENCE,
            business_date="2026-11-21",
            idempotency_key="same-key",
        ),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.CONFLICT
    assert envelope.error.safe_details == ("idempotency_key",)


def test_another_date_and_a_closed_date_each_get_a_new_cycle(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    first = _begin(service, scene, "day-one")
    other_day = _begin(service, scene, "day-two", day="2026-11-21")
    assert other_day["cycle_run_id"] != first["cycle_run_id"]
    close_cycle(
        _store(scene),
        principal_id=scene.principal.principal_id,
        cycle_run_id=str(first["cycle_run_id"]),
        at=WHEN,
    )
    again = _begin(service, scene, "day-one-again")
    assert again["created"] is True
    assert again["cycle_run_id"] != first["cycle_run_id"]


def test_an_unknown_cycle_id_names_cycle_id(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    envelope = _invoke(
        service,
        scene,
        BeginIntelligenceCycle(cycle_id="evening", business_date="2026-11-20", idempotency_key="k"),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.INVALID_REQUEST
    assert envelope.error.safe_details == ("cycle_id",)


# ---- closing ----------------------------------------------------------------------


def test_close_is_complete_with_a_commit_cancelled_without_and_idempotent(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    store = _store(scene)
    principal_id = scene.principal.principal_id
    used = str(_begin(service, scene, "used", day="2026-11-18")["cycle_run_id"])
    unused = str(_begin(service, scene, "unused", day="2026-11-19")["cycle_run_id"])
    today = str(_begin(service, scene, "today", day="2026-11-20")["cycle_run_id"])
    assert _commit(service, scene, used, "commit-used").error is None

    stale = stale_open_cycles(store, principal_id=principal_id, business_date=date(2026, 11, 20))
    assert stale == (used, unused)
    outcomes = [
        close_cycle(store, principal_id=principal_id, cycle_run_id=cycle, at=WHEN).outcome
        for cycle in stale
    ]
    assert outcomes == [CycleClosureOutcome.COMPLETE, CycleClosureOutcome.CANCELLED]
    closed = store.cycles[(principal_id, used)]
    assert (closed.state, closed.version, closed.finished_at) == (CycleState.COMPLETE, 2, WHEN)
    assert store.cycles[(principal_id, unused)].state is CycleState.CANCELLED
    assert store.cycles[(principal_id, today)].state is CycleState.OPEN

    again = close_cycle(store, principal_id=principal_id, cycle_run_id=used, at=WHEN)
    assert again.outcome is CycleClosureOutcome.ALREADY_CLOSED
    assert store.cycles[(principal_id, used)].version == 2
    assert (
        stale_open_cycles(store, principal_id=principal_id, business_date=date(2026, 11, 20)) == ()
    )


def test_a_late_write_to_a_closed_cycle_is_refused_and_a_replay_still_replays(
    scene: Scene,
) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = str(_begin(service, scene, "late")["cycle_run_id"])
    accepted = _commit(service, scene, cycle, "accepted")
    assert accepted.error is None
    close_cycle(
        _store(scene), principal_id=scene.principal.principal_id, cycle_run_id=cycle, at=WHEN
    )

    replay = _commit(service, scene, cycle, "accepted")
    assert replay.error is None
    assert replay.result is not None and replay.result["replayed"] is True

    late = _commit(service, scene, cycle, "too-late")
    assert late.error is not None
    assert late.error.code is ErrorCode.CONFLICT
    assert late.error.safe_details == ("cycle_run_id", "cycle_closed")

    run_state = _invoke(
        service,
        scene,
        RecordIntelligenceRunState(
            cycle_run_id=cycle,
            stage=IntelligenceStage.COLLECTOR,
            artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES,
            producer_task_id="task-collector",
            producer_task_name="Collector",
            automation_platform="abacus_chatllm",
            report_date="2026-11-20",
            state=ProducerRunState.FAILED,
            idempotency_key="late-run-state",
            focus_area_id=FocusAreaId.COMMUNICATIONS,
        ),
    )
    assert run_state.error is not None
    assert run_state.error.safe_details == ("cycle_run_id", "cycle_closed")


# ---- one run ----------------------------------------------------------------------


def _runner(scene: Scene, service: ApplicationService, *, fail_close: bool) -> DailyCycleRunner:
    calls = {"n": 0}

    @contextmanager
    def unit_of_work() -> Iterator[FakeUnitOfWork]:
        calls["n"] += 1
        if fail_close and calls["n"] > 1:
            raise RuntimeError("close transaction failed")
        with FakeUnitOfWork(scene.world) as opened:
            yield opened  # type: ignore[misc]

    return DailyCycleRunner(
        service=service,
        unit_of_work=unit_of_work,  # type: ignore[arg-type]
        principal=scene.principal,
        clock=lambda: WHEN,
    )


def test_a_run_closes_stale_cycles_then_begins_and_a_rerun_replays(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    old = str(_begin(service, scene, "old", day="2026-11-19")["cycle_run_id"])
    runner = _runner(scene, service, fail_close=False)

    first = runner(date(2026, 11, 20))
    assert (first.closed_cancelled, first.close_failed, first.created) == (1, 0, True)
    assert first.begun
    assert _store(scene).cycles[(scene.principal.principal_id, old)].state is CycleState.CANCELLED

    second = runner(date(2026, 11, 20))
    assert second.cycle_run_id == first.cycle_run_id
    assert (second.created, second.replayed, second.closed_cancelled) == (False, True, 0)
    assert second.log_fields()["event"] == "cycle_scheduler.run"


def test_a_failed_close_never_blocks_the_begin(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    old = str(_begin(service, scene, "old", day="2026-11-19")["cycle_run_id"])
    outcome = _runner(scene, service, fail_close=True)(date(2026, 11, 20))
    assert outcome.close_failed == 1
    assert outcome.begun and outcome.created
    # Still open, so the next run finds it again.
    assert _store(scene).cycles[(scene.principal.principal_id, old)].state is CycleState.OPEN


# ---- the loop (single flight is proved against PostgreSQL in tests/database) ------


@contextmanager
def _free_lock(engine: object, *, key: int) -> Iterator[bool]:
    yield True


def test_the_loop_runs_each_due_date_once_and_retries_a_failed_begin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cycle_scheduler, "single_flight", _free_lock)
    instants = iter(
        [
            _ny(2026, 11, 20, 9, 0),
            _ny(2026, 11, 20, 9, 1),
            _ny(2026, 11, 20, 9, 2),
            _ny(2026, 11, 21, 0, 0),
        ]
    )
    answers = iter([False, True, True])
    calls: list[date] = []

    def run_for(business_date: date) -> bool:
        calls.append(business_date)
        return next(answers)

    result = run_cycle_scheduler(
        object(),  # type: ignore[arg-type]
        zone=NEW_YORK,
        run_for=run_for,
        stop=threading.Event(),
        clock=lambda: next(instants),
        log=lambda fields: None,
        max_iterations=4,
    )
    # First begin failed and was retried at the next poll; then idle; then midnight.
    assert calls == [date(2026, 11, 20), date(2026, 11, 20), date(2026, 11, 21)]
    assert (result.runs, result.failed, result.iterations) == (2, 1, 4)


# ---- the plane's switch, its zone setting and its compose overlay ------------------


class _EngineBuiltError(Exception):
    """Raised by the stand-in engine factory: the refusal did not come first."""


def _run_cycles_plane(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> int:
    from apps import worker as worker_app

    for key in [key for key in os.environ if key.startswith("MY_PA_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://someone@db.invalid:5432/x")
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    def no_engine(*_args: object, **_kwargs: object) -> object:
        raise _EngineBuiltError

    monkeypatch.setattr(worker_app, "create_database_engine", no_engine)
    return worker_app.main(["run", "--plane", "cycles", "--once"])


@pytest.mark.parametrize(
    "env", [{}, {"MY_PA_CYCLE_SCHEDULER_ENABLED": "false"}], ids=["unset", "false"]
)
def test_the_cycles_plane_is_refused_while_disabled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], env: dict[str, str]
) -> None:
    assert _run_cycles_plane(monkeypatch, env) == 2
    assert capsys.readouterr().out == "plane cycles disabled\n"


def test_the_enabled_cycles_plane_reaches_the_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(_EngineBuiltError):
        _run_cycles_plane(monkeypatch, {"MY_PA_CYCLE_SCHEDULER_ENABLED": "true"})


def test_settings_default_the_zone_and_refuse_an_unknown_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in [key for key in os.environ if key.startswith("MY_PA_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://someone@db.invalid:5432/x")
    settings = load_settings()
    assert settings.cycle_scheduler_enabled is False
    assert settings.cycle_scheduler_timezone == DEFAULT_CYCLE_TIMEZONE
    monkeypatch.setenv("MY_PA_CYCLE_SCHEDULER_TIMEZONE", "Mars/Olympus_Mons")
    with pytest.raises(SettingsError, match="IANA zone"):
        load_settings()


def test_the_remote_overlay_runs_only_the_cycles_plane_on_the_data_plane() -> None:
    text = (ROOT / "ops/nas/remote/compose.cycle-scheduler.remote.example.yml").read_text(
        encoding="utf-8"
    )
    body = [line for line in text.splitlines() if line and not line.startswith("#")]
    services = [
        line.strip() for line in body if line.startswith("  ") and not line.startswith("   ")
    ]
    assert services == ["my-pa-cycle-scheduler:"]
    assert "    command: [python, apps/worker.py, run, --plane, cycles]" in body
    assert "    networks: [data-plane]" in body
    assert '      MY_PA_CYCLE_SCHEDULER_ENABLED: "true"' in body
    assert "    read_only: true" in body
    assert "    cap_drop: [ALL]" in body
    for absent in ("ports:", "expose:", "volumes:"):
        assert not any(line.strip().startswith(absent) for line in body)
