"""The cycles plane as a tuple of steps (communications WP3a, Manager ruling M2; contract 19).

FAST tier. The step loop (`infrastructure.jobs.cycle_scheduler.run_scheduler_steps`):
each step contends for its own advisory lock, a busy lock skips only that
step, the daily step keeps its date-due rule and the ingestion step its
interval; and the plane's switch matrix in `apps/worker.py` (both off refuses
before an engine is built, each alone composes only its own step, both compose
both), `--once` running the ingestion poll once over one long-lived
lifecycle, and the read-only compose overlay. Single flight against a real
PostgreSQL is `tests/database/test_cycle_plane_steps.py`.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import pytest

from my_pa.application.ingestion import IngestRunReport
from my_pa.bootstrap.settings import load_settings
from my_pa.contracts.ports import FileWorkspaceRootError, IngestRunOutcome, IngestRunTrigger
from my_pa.infrastructure.jobs import cycle_scheduler
from my_pa.infrastructure.jobs.cycle_scheduler import (
    COMMS_INGEST_LOCK_KEY,
    CYCLE_SCHEDULER_LOCK_KEY,
    CycleSchedulerRun,
    DailyStep,
    IntervalStep,
    run_scheduler_steps,
)

ROOT: Final = Path(__file__).resolve().parents[2]
NEW_YORK: Final = ZoneInfo("America/New_York")
T0: Final = datetime(2026, 11, 22, 17, 0, tzinfo=UTC)


def _signed(label: bytes) -> int:
    return int.from_bytes(hashlib.sha256(label).digest()[:8], byteorder="big", signed=True)


def test_the_lock_keys_are_the_ruling_derivation_and_distinct() -> None:
    assert _signed(b"my-pa-ingest-poll") == COMMS_INGEST_LOCK_KEY
    assert _signed(b"my-pa-daily-cycle-scheduler") == CYCLE_SCHEDULER_LOCK_KEY
    assert COMMS_INGEST_LOCK_KEY != CYCLE_SCHEDULER_LOCK_KEY


# ---- the loop --------------------------------------------------------------------


class _Locks:
    """A stand-in for `single_flight`: the keys in `busy` are held by another process."""

    def __init__(self, busy: set[int] | None = None) -> None:
        self.busy = busy or set()
        self.taken: list[int] = []

    @contextmanager
    def __call__(self, engine: object, *, key: int) -> Iterator[bool]:
        self.taken.append(key)
        yield key not in self.busy


class _Clock:
    def __init__(self, *instants: datetime) -> None:
        self.instants = list(instants)

    def __call__(self) -> datetime:
        return self.instants[0]


def _loop(
    steps: list[DailyStep | IntervalStep],
    clock: object,
    *,
    iterations: int,
    log: list[dict[str, object]] | None = None,
) -> CycleSchedulerRun:
    return run_scheduler_steps(
        object(),  # type: ignore[arg-type]
        steps=steps,
        stop=threading.Event(),
        clock=clock,  # type: ignore[arg-type]
        log=(lambda fields: log.append(dict(fields))) if log is not None else (lambda _: None),
        max_iterations=iterations,
    )


def _ingest(calls: list[datetime], clock: _Clock, *, answer: bool = True) -> IntervalStep:
    """The ingestion step; `calls` records the instant each attempt was made at."""

    def run_once() -> bool:
        assert step.last_attempt is not None
        calls.append(step.last_attempt)
        return answer

    step = IntervalStep(
        name="comms_ingest",
        event="comms_ingest",
        lock_key=COMMS_INGEST_LOCK_KEY,
        interval_seconds=900,
        run_once=run_once,
    )
    return step


def _daily(calls: list[date]) -> DailyStep:
    def run_for(business_date: date) -> bool:
        calls.append(business_date)
        return True

    return DailyStep(zone=NEW_YORK, run_for=run_for)


class _SteppingClock(_Clock):
    """Advances one instant per loop iteration (two steps ask per iteration)."""

    def __init__(self, steps: int, *instants: datetime) -> None:
        super().__init__(*instants)
        self.asks = 0
        self.per_iteration = steps

    def __call__(self) -> datetime:
        moment = self.instants[min(self.asks // self.per_iteration, len(self.instants) - 1)]
        self.asks += 1
        return moment


def test_each_step_contends_for_its_own_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    locks = _Locks()
    monkeypatch.setattr(cycle_scheduler, "single_flight", locks)
    clock = _SteppingClock(2, T0)
    days: list[date] = []
    polls: list[datetime] = []
    result = _loop([_daily(days), _ingest(polls, clock)], clock, iterations=1)
    assert locks.taken == [CYCLE_SCHEDULER_LOCK_KEY, COMMS_INGEST_LOCK_KEY]
    assert (len(days), len(polls), result.runs) == (1, 1, 2)
    assert set(result.steps) == {"daily_cycle", "comms_ingest"}


@pytest.mark.parametrize(
    ("busy", "ran", "skipped"),
    [
        (COMMS_INGEST_LOCK_KEY, "daily_cycle", "comms_ingest"),
        (CYCLE_SCHEDULER_LOCK_KEY, "comms_ingest", "daily_cycle"),
    ],
    ids=["ingest-busy", "daily-busy"],
)
def test_a_busy_lock_skips_only_its_own_step(
    monkeypatch: pytest.MonkeyPatch, busy: int, ran: str, skipped: str
) -> None:
    monkeypatch.setattr(cycle_scheduler, "single_flight", _Locks({busy}))
    clock = _SteppingClock(2, T0)
    days: list[date] = []
    polls: list[datetime] = []
    log: list[dict[str, object]] = []
    result = _loop([_daily(days), _ingest(polls, clock)], clock, iterations=1, log=log)
    assert result.steps[ran].runs == 1
    assert result.steps[ran].skipped == 0
    assert result.steps[skipped].runs == 0
    assert result.steps[skipped].skipped == 1
    event = "comms_ingest.skipped" if skipped == "comms_ingest" else "cycle_scheduler.skipped"
    assert [line["event"] for line in log] == [event]
    assert log[0]["reason"] == "lock_held"


def test_a_skipped_step_stays_due_and_runs_on_the_next_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locks = _Locks({COMMS_INGEST_LOCK_KEY})
    monkeypatch.setattr(cycle_scheduler, "single_flight", locks)
    clock = _SteppingClock(1, T0, T0 + timedelta(seconds=60))
    polls: list[datetime] = []
    step = _ingest(polls, clock)
    first = _loop([step], clock, iterations=1)
    locks.busy.clear()
    second = _loop([step], clock, iterations=1)
    assert (first.skipped, second.runs) == (1, 1)
    assert polls == [T0 + timedelta(seconds=60)]


def test_the_ingest_step_runs_on_start_then_every_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cycle_scheduler, "single_flight", _Locks())
    instants = [T0 + timedelta(seconds=s) for s in (0, 60, 899, 900, 960, 1800)]
    clock = _SteppingClock(1, *instants)
    polls: list[datetime] = []
    result = _loop([_ingest(polls, clock)], clock, iterations=len(instants))
    assert polls == [T0, T0 + timedelta(seconds=900), T0 + timedelta(seconds=1800)]
    assert (result.runs, result.iterations) == (3, 6)


def test_a_failed_or_raising_ingest_attempt_waits_the_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cycle_scheduler, "single_flight", _Locks())
    instants = [T0, T0 + timedelta(seconds=60), T0 + timedelta(seconds=900)]
    clock = _SteppingClock(1, *instants)
    attempts: list[datetime] = []

    def run_once() -> bool:
        attempts.append(clock.instants[0])
        raise RuntimeError("boom")

    step = IntervalStep(
        name="comms_ingest",
        event="comms_ingest",
        lock_key=COMMS_INGEST_LOCK_KEY,
        interval_seconds=900,
        run_once=run_once,
    )
    log: list[dict[str, object]] = []
    result = _loop([step], clock, iterations=3, log=log)
    assert len(attempts) == 2  # at start and after the interval, not at +60 s
    assert result.failed == 2
    assert log == [{"event": "comms_ingest.failed", "reason": "internal_error"}] * 2


def test_a_raising_step_never_stops_the_other(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cycle_scheduler, "single_flight", _Locks())
    clock = _SteppingClock(2, T0)

    def boom(business_date: date) -> bool:
        raise RuntimeError("boom")

    polls: list[datetime] = []
    result = _loop(
        [DailyStep(zone=NEW_YORK, run_for=boom), _ingest(polls, clock)], clock, iterations=1
    )
    assert (result.steps["daily_cycle"].failed, result.steps["comms_ingest"].runs) == (1, 1)


def test_step_names_must_be_distinct_and_intervals_positive() -> None:
    clock = _Clock(T0)
    with pytest.raises(ValueError, match="distinct"):
        _loop([_ingest([], clock), _ingest([], clock)], clock, iterations=1)
    with pytest.raises(ValueError, match="positive"):
        IntervalStep(name="x", event="x", lock_key=1, interval_seconds=0, run_once=lambda: True)


# ---- the plane's switch matrix ---------------------------------------------------


class _EngineBuiltError(Exception):
    pass


class _Engine:
    disposed = 0

    def dispose(self) -> None:
        type(self).disposed += 1


class _Lifecycle:
    def __init__(self) -> None:
        self.polls: list[str] = []

    def poll_enabled(self, principal_id: str) -> tuple[IngestRunReport, ...]:
        self.polls.append(principal_id)
        return (
            IngestRunReport(
                ingest_source_id="isrc_synthetic",
                trigger=IngestRunTrigger.SCHEDULE,
                dry_run=False,
                run_id="irun_synthetic",
                outcome=IngestRunOutcome.COMPLETED,
                counts={"snapshots_seen": 2, "skipped_unstable": 2},
            ),
        )


def _env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key in [key for key in os.environ if key.startswith("MY_PA_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://someone@db.invalid:5432/x")
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def _plane(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], *, real_loop: bool = False
) -> tuple[int, list[str], _Lifecycle]:
    from apps import worker as worker_app

    _env(monkeypatch, env)
    lifecycle = _Lifecycle()
    seen: list[str] = []
    monkeypatch.setattr(worker_app, "create_database_engine", lambda *a, **k: _Engine())
    monkeypatch.setattr(worker_app, "ingestion_lifecycle", lambda *a, **k: lifecycle)
    monkeypatch.setattr(worker_app, "_install_stop_handlers", lambda stop: None)
    if real_loop:
        monkeypatch.setattr(cycle_scheduler, "single_flight", _Locks())
    else:

        def capture(engine: object, *, steps: list[object], **kwargs: object) -> CycleSchedulerRun:
            seen.extend(step.name for step in steps)  # type: ignore[attr-defined]
            return CycleSchedulerRun()

        monkeypatch.setattr(worker_app, "run_scheduler_steps", capture)
    code = worker_app.main(["run", "--plane", "cycles", "--once"])
    return code, seen, lifecycle


@pytest.mark.parametrize(
    "env",
    [
        {},
        {
            "MY_PA_CYCLE_SCHEDULER_ENABLED": "false",
            "MY_PA_COMMUNICATIONS_INGEST_ENABLED": "false",
        },
    ],
    ids=["unset", "false"],
)
def test_both_switches_off_refuse_before_an_engine(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], env: dict[str, str]
) -> None:
    from apps import worker as worker_app

    _env(monkeypatch, env)

    def no_engine(*_args: object, **_kwargs: object) -> object:
        raise _EngineBuiltError

    monkeypatch.setattr(worker_app, "create_database_engine", no_engine)
    assert worker_app.main(["run", "--plane", "cycles", "--once"]) == 2
    assert capsys.readouterr().out == "plane cycles disabled\n"


@pytest.mark.parametrize(
    ("env", "steps"),
    [
        ({"MY_PA_CYCLE_SCHEDULER_ENABLED": "true"}, ["daily_cycle"]),
        ({"MY_PA_COMMUNICATIONS_INGEST_ENABLED": "true"}, ["comms_ingest"]),
        (
            {
                "MY_PA_CYCLE_SCHEDULER_ENABLED": "true",
                "MY_PA_COMMUNICATIONS_INGEST_ENABLED": "true",
            },
            ["daily_cycle", "comms_ingest"],
        ),
    ],
    ids=["daily-only", "ingest-only", "both"],
)
def test_each_switch_composes_only_its_own_step(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], steps: list[str]
) -> None:
    code, seen, _ = _plane(monkeypatch, env)
    assert (code, seen) == (0, steps)


def test_once_runs_the_ingest_poll_once_with_a_counts_only_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, lifecycle = _plane(
        monkeypatch, {"MY_PA_COMMUNICATIONS_INGEST_ENABLED": "true"}, real_loop=True
    )
    assert code == 0
    assert len(lifecycle.polls) == 1
    out = capsys.readouterr().out.splitlines()
    line = json.loads(out[0])
    assert line == {
        "counts": {"skipped_unstable": 2, "snapshots_seen": 2},
        "event": "comms_ingest.run",
        "outcomes": {"completed": 1},
        "sources": 1,
    }
    assert "step         comms_ingest runs=1 skipped=0 failed=0" in out


def test_a_misconfigured_workspace_refuses_the_plane(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from apps import worker as worker_app

    _env(monkeypatch, {"MY_PA_COMMUNICATIONS_INGEST_ENABLED": "true"})
    monkeypatch.setattr(worker_app, "create_database_engine", lambda *a, **k: _Engine())

    def refuse(*_args: object, **_kwargs: object) -> object:
        raise FileWorkspaceRootError("the configured file workspace root is not absolute")

    monkeypatch.setattr(worker_app, "ingestion_lifecycle", refuse)
    assert worker_app.main(["run", "--plane", "cycles", "--once"]) == 2
    assert capsys.readouterr().out == "plane cycles workspace_misconfigured\n"


def test_the_ingest_settings_default_off_and_bound_the_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch, {})
    settings = load_settings()
    assert settings.communications_ingest_enabled is False
    assert settings.communications_ingest_poll_seconds == 900
    monkeypatch.setenv("MY_PA_COMMUNICATIONS_INGEST_POLL_SECONDS", "59")
    with pytest.raises(ValueError, match="greater than or equal"):
        load_settings()


# ---- the read-only overlay --------------------------------------------------------

OVERLAY: Final = ROOT / "ops/nas/remote/compose.comms-ingest.remote.example.yml"


def _body() -> list[str]:
    text = OVERLAY.read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.strip() and not line.startswith("#")]


def test_the_overlay_gives_the_cycles_service_a_read_only_workspace() -> None:
    body = _body()
    services = [line for line in body if line.startswith("  ") and not line.startswith("   ")]
    assert services == ["  my-pa-cycle-scheduler:"]
    assert '      MY_PA_FILES_WORKSPACES: "mcp=/srv/my-pa/workspaces/mcp;mode=read_only"' in body
    mounts = [line.strip() for line in body if line.startswith("      - ") or "read_only" in line]
    assert "- type: bind" in mounts
    assert "read_only: true" in [line.strip() for line in body]
    assert not any("read_only: false" in line for line in body)
    assert "        target: /srv/my-pa/workspaces/mcp" in body


def test_the_overlay_leaves_ingestion_off_and_publishes_nothing() -> None:
    text = OVERLAY.read_text(encoding="utf-8")
    body = _body()
    assert '#      MY_PA_COMMUNICATIONS_INGEST_ENABLED: "true"' in text.splitlines()
    assert not any("MY_PA_COMMUNICATIONS_INGEST_ENABLED" in line for line in body)
    for absent in ("ports:", "expose:", "command:", "image:"):
        assert not any(line.strip().startswith(absent) for line in body)
