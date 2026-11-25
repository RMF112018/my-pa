"""The project-reports cycles step, its switches, the S5 operator commands and the log guard.

FAST tier (WP3P-S5; ruling D5 and the adopted log-line no-content mitigation).
Proved here:

* the switch matrix of `apps/worker.py`'s cycles plane with the third switch:
  `MY_PA_PROJECT_REPORTS_INGEST_ENABLED` alone starts the plane and composes
  only the `project_reports_ingest` step; all three compose all three; the
  step takes `PROJECT_REPORTS_POLL_LOCK_KEY`; a misconfigured workspace
  refuses the plane; the settings default off and bound the interval;
* `--once` runs the poll and then the sweep once, with two counts-only lines;
* the JSON shapes and closed exits of `run-once`, `backfill` (files, glob,
  dry run), `rederive` (and its dry run), `coverage` and `aggregate` (with an
  `--expect` that matches, exit 0, and one that differs, exit 4), and the
  `source_not_found`, `source_unbound` (up front, writing nothing) and
  `lock_held` refusals;
* **the log-line no-content guard**: every line the handler, the sweep, the
  worker step and every S5 command print over the synthetic fixtures holds
  none of the fixtures' cell texts, none of the placed file names, slugs or
  folder names, and no part of the database URL.

Every identifier, folder, number and text here is synthetic.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli import project_reports as cli

from my_pa.bootstrap.settings import load_settings
from my_pa.contracts.ports import FileWorkspaceRootError
from my_pa.domain.project_reports.model import BindingState
from my_pa.infrastructure.jobs import cycle_scheduler
from my_pa.infrastructure.jobs.cycle_scheduler import (
    PROJECT_REPORTS_POLL_LOCK_KEY,
    CycleSchedulerRun,
)
from my_pa.infrastructure.project_reports.pulse_csv import (
    ExportRejectedError,
    prepare_export,
)
from tests.unit.project_reports_scene import (
    DIRECTORIES,
    EXPORT_ROOT,
    FIXTURES,
    Scene,
    fixture_files,
    folder_of,
)
from tests.unit.test_project_reports_cli import DSN, DSN_PARTS, EXPECT, _Engine

ENABLED: Final = "MY_PA_PROJECT_REPORTS_INGEST_ENABLED"


def _env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key in [key for key in os.environ if key.startswith("MY_PA_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("MY_PA_DATABASE_URL", DSN)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


# ---- the worker step ---------------------------------------------------------------


class _Locks:
    def __init__(self) -> None:
        self.taken: list[int] = []

    @contextmanager
    def __call__(self, engine: object, *, key: int) -> Iterator[bool]:
        self.taken.append(key)
        yield True


def _plane(
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    *,
    scene: Scene | None = None,
    locks: _Locks | None = None,
) -> tuple[int, list[str]]:
    from apps import worker as worker_app

    _env(monkeypatch, env)
    seen: list[str] = []
    monkeypatch.setattr(worker_app, "create_database_engine", lambda *a, **k: _Engine())
    monkeypatch.setattr(worker_app, "_install_stop_handlers", lambda stop: None)
    monkeypatch.setattr(worker_app, "ingestion_lifecycle", lambda *a, **k: object())
    monkeypatch.setattr(worker_app, "meeting_sync_applier", lambda *a, **k: object())
    if scene is not None:
        monkeypatch.setattr(
            worker_app, "project_reports_lifecycle", lambda *a, **k: scene.lifecycle
        )
        monkeypatch.setattr(worker_app, "rederiver", lambda *a, **k: scene.rederiver())
        monkeypatch.setattr(cycle_scheduler, "single_flight", locks or _Locks())
    else:
        monkeypatch.setattr(worker_app, "project_reports_lifecycle", lambda *a, **k: object())
        monkeypatch.setattr(worker_app, "rederiver", lambda *a, **k: object())

        def capture(engine: object, *, steps: list[object], **kwargs: object) -> CycleSchedulerRun:
            seen.extend(step.name for step in steps)  # type: ignore[attr-defined]
            return CycleSchedulerRun()

        monkeypatch.setattr(worker_app, "run_scheduler_steps", capture)
    return worker_app.main(["run", "--plane", "cycles", "--once"]), seen


@pytest.mark.parametrize(
    ("env", "steps"),
    [
        ({ENABLED: "true"}, ["project_reports_ingest"]),
        (
            {
                "MY_PA_CYCLE_SCHEDULER_ENABLED": "true",
                "MY_PA_COMMUNICATIONS_INGEST_ENABLED": "true",
                ENABLED: "true",
            },
            ["daily_cycle", "comms_ingest", "project_reports_ingest"],
        ),
        ({"MY_PA_COMMUNICATIONS_INGEST_ENABLED": "true"}, ["comms_ingest"]),
    ],
    ids=["project-reports-only", "all-three", "comms-only"],
)
def test_the_third_switch_composes_only_its_own_step(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], steps: list[str]
) -> None:
    assert _plane(monkeypatch, env) == (0, steps)


def test_every_switch_off_still_refuses_before_an_engine(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from apps import worker as worker_app

    _env(monkeypatch, {ENABLED: "false"})

    def no_engine(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("no engine is built")

    monkeypatch.setattr(worker_app, "create_database_engine", no_engine)
    assert worker_app.main(["run", "--plane", "cycles", "--once"]) == 2
    assert capsys.readouterr().out == "plane cycles disabled\n"


def test_a_misconfigured_workspace_refuses_the_plane(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from apps import worker as worker_app

    _env(monkeypatch, {ENABLED: "true"})
    monkeypatch.setattr(worker_app, "create_database_engine", lambda *a, **k: _Engine())

    def refuse(*_args: object, **kwargs: object) -> object:
        assert kwargs.get("eager") is True
        raise FileWorkspaceRootError("the configured file workspace root is not absolute")

    monkeypatch.setattr(worker_app, "project_reports_lifecycle", refuse)
    assert worker_app.main(["run", "--plane", "cycles", "--once"]) == 2
    assert capsys.readouterr().out == "plane cycles workspace_misconfigured\n"


def test_the_settings_default_off_and_bound_the_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, {})
    settings = load_settings()
    assert settings.project_reports_ingest_enabled is False
    assert settings.project_reports_ingest_poll_seconds == 900
    for value in ("59", "86401"):
        monkeypatch.setenv("MY_PA_PROJECT_REPORTS_INGEST_POLL_SECONDS", value)
        with pytest.raises(ValueError, match="than or equal"):
            load_settings()


def test_once_polls_then_sweeps_under_the_project_reports_lock(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = Scene()
    scene.place(("rfc",))
    locks = _Locks()
    code, _ = _plane(monkeypatch, {ENABLED: "true"}, scene=scene, locks=locks)
    assert code == 0
    assert locks.taken == [PROJECT_REPORTS_POLL_LOCK_KEY]
    out = capsys.readouterr().out.splitlines()
    run, rederive = json.loads(out[0]), json.loads(out[1])
    assert run["event"] == "project_reports_ingest.run"
    assert (run["sources"], run["outcomes"]) == (1, {"completed": 1})
    # A scheduled poll reads a file only once it held still across two polls.
    assert run["counts"]["skipped_unstable"] == len(fixture_files("rfc"))
    assert rederive == {
        "event": "project_reports.rederive",
        "counts": {
            "derivations_checked": 0,
            "derivations_current": 0,
            "derivations_deferred": 0,
            "derivations_failed": 0,
            "derivations_skipped_unbound": 0,
        },
    }
    assert "step         project_reports_ingest runs=1 skipped=0 failed=0" in out


# ---- the operator commands -------------------------------------------------------------


class _Operator:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        _env(monkeypatch, {})
        self.capsys = capsys
        self.scene = Scene()
        self.scene.place()
        self.engine = _Engine()
        self.outputs: list[str] = []
        monkeypatch.setattr(cli, "create_database_engine", lambda *a, **k: self.engine)
        monkeypatch.setattr(cli, "project_reports_lifecycle", lambda *a, **k: self.scene.lifecycle)
        monkeypatch.setattr(cli, "rederiver", lambda *a, **k: self.scene.rederiver())
        monkeypatch.setattr(cli, "project_reports_unit_of_work", lambda *a, **k: self.scene.unit)

    def __call__(self, *argv: str) -> tuple[int, dict[str, Any]]:
        code = cli.main([*EXPECT, *argv])
        captured = self.capsys.readouterr()
        assert captured.err == ""
        lines = captured.out.splitlines()
        assert len(lines) == 1, captured.out
        self.outputs.append(captured.out)
        return code, json.loads(lines[0])

    def source(self, directory: str) -> str:
        return self.scene.sources[directory]


@pytest.fixture
def operator(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> _Operator:
    return _Operator(monkeypatch, capsys)


def test_run_once_and_backfill_print_counts_and_exit_by_outcome(operator: _Operator) -> None:
    code, out = operator("run-once", "--source", operator.source("rfc"))
    assert code == cli.EXIT_OK
    assert set(out) == {
        "command",
        "ingest_source_id",
        "trigger",
        "dry_run",
        "run_id",
        "outcome",
        "counts",
    }
    assert (out["trigger"], out["outcome"], out["dry_run"]) == ("operator", "completed", False)
    assert out["counts"]["snapshots_ingested"] == len(fixture_files("rfc"))
    first = operator.scene.placed["signatures"][0].rsplit("/", 1)[1]
    code, out = operator("backfill", "--source", operator.source("signatures"), "--file", first)
    assert (code, out["counts"]["snapshots_ingested"]) == (cli.EXIT_OK, 1)
    code, out = operator(
        "backfill", "--source", operator.source("signatures"), "--glob", "*-0[0-4].csv"
    )
    counts = out["counts"]
    # The first file is known (this process finished it: `skipped_unchanged`).
    assert (counts["skipped_unchanged"], counts["snapshots_ingested"]) == (1, 4)
    snapshots = len(operator.scene.world.project_reports.snapshots)
    code, out = operator("backfill", "--source", operator.source("signatures"), "--dry-run")
    assert (code, out["dry_run"], out["run_id"]) == (cli.EXIT_OK, True, None)
    assert out["counts"]["snapshots_ingested"] == len(fixture_files("signatures")) - 5
    assert len(operator.scene.world.project_reports.snapshots) == snapshots
    assert operator.engine.connection.lock_calls.count("try") == 3  # not for the dry run


@pytest.mark.parametrize("dry_run", [False, True])
def test_an_unbound_source_is_refused_up_front_and_nothing_is_written(
    operator: _Operator, dry_run: bool
) -> None:
    """`source_unbound` before the lifecycle runs: no run, no snapshot, not even a rejected one.

    The `rejected` fixtures would each write a rejected snapshot were the
    lifecycle reached, so an empty world proves the refusal came first.
    """
    source = operator.source("rejected")
    operator.scene.rebind("rejected", state=BindingState.RETIRED)
    extra = ["--dry-run"] if dry_run else []
    for argv in (["run-once", "--source", source], ["backfill", "--source", source, *extra]):
        code, out = operator(*argv)
        assert (code, out) == (
            cli.EXIT_REFUSED,
            {"command": argv[0], "refused": "source_unbound"},
        )
    ingest = operator.scene.ingest
    assert (ingest.snapshots, ingest.paths, ingest.runs, ingest.run_snapshots) == ({}, {}, {}, {})
    assert not operator.scene.world.project_reports.snapshots


def test_a_backfill_with_a_failed_snapshot_exits_3(
    operator: _Operator, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The handler's in-transaction `source_unbound` stays as defence in depth."""
    monkeypatch.setattr(cli, "_require_bound", lambda *a, **k: None)
    operator.scene.rebind("hostile", state=BindingState.RETIRED)
    code, out = operator("backfill", "--source", operator.source("hostile"))
    assert (code, out["outcome"], out["counts"]["snapshots_failed"]) == (
        cli.EXIT_RUN_INCOMPLETE,
        "failed",
        1,
    )


def test_rederive_and_its_dry_run(operator: _Operator) -> None:
    operator("backfill", "--source", operator.source("two_level"))
    code, out = operator("rederive", "--dry-run")
    assert (code, out["dry_run"], out["counts"]["derivations_due_operator_rebuild"]) == (
        cli.EXIT_OK,
        True,
        1,
    )
    derivations = len(operator.scene.world.project_reports.derivations)
    assert derivations == 1
    code, out = operator("rederive", "--source", operator.source("two_level"))
    assert (code, out["counts"]["derivations_written_operator_rebuild"]) == (cli.EXIT_OK, 1)
    assert len(operator.scene.world.project_reports.derivations) == 2


def test_coverage_prints_series_without_names(operator: _Operator) -> None:
    operator("backfill", "--source", operator.source("signatures"))
    operator("backfill", "--source", operator.source("rejected"))
    code, out = operator("coverage")
    assert code == cli.EXIT_OK
    by_source = {source["ingest_source_id"]: source for source in out["sources"]}
    signatures = by_source[operator.source("signatures")]
    assert (signatures["snapshots"], signatures["rejected"], signatures["quarantined"]) == (
        len(fixture_files("signatures")),
        0,
        0,
    )
    assert signatures["project_number"] == "SYN-0001"
    assert len(signatures["series"]) == len(fixture_files("signatures"))
    first = signatures["series"][0]
    assert first["latest_date_label"] == "2026-11-20"
    assert first["filter_semantics"] == "unknown"
    assert first["first_seen"].endswith("Z")
    assert by_source[operator.source("rejected")]["rejected"] == len(fixture_files("rejected"))
    code, out = operator("coverage", "--source", "isrc_synthnosuch0001")
    assert (code, out) == (cli.EXIT_REFUSED, {"command": "coverage", "refused": "source_not_found"})


def test_aggregate_from_stored_rows_with_expect(operator: _Operator, tmp_path: Path) -> None:
    for source in operator.scene.sources.values():
        operator("backfill", "--source", source)
    argv = [arg for source in operator.scene.sources.values() for arg in ("--source", source)]
    code, out = operator("aggregate", *argv)
    assert code == cli.EXIT_OK
    assert out["counts"]["files.total"] == sum(len(fixture_files(d)) for d in DIRECTORIES)
    expected = tmp_path / "expected.json"
    document = {"schema": "project_reports_evidence_aggregate_v1", "counts": out["counts"]}
    expected.write_text(json.dumps(document))
    code, matched = operator("aggregate", *argv, "--expect", str(expected))
    assert (code, matched["expect"]["differing"]) == (cli.EXIT_OK, [])
    document["counts"] = {**out["counts"], "files.total": out["counts"]["files.total"] + 1}
    expected.write_text(json.dumps(document))
    code, differs = operator("aggregate", *argv, "--expect", str(expected))
    assert code == cli.EXIT_EXPECT_DIFFERS
    assert differs["expect"]["differing"] == [
        {
            "key": "files.total",
            "expected": out["counts"]["files.total"] + 1,
            "actual": out["counts"]["files.total"],
        }
    ]
    expected.write_text("not json")
    assert operator("aggregate", *argv, "--expect", str(expected)) == (
        cli.EXIT_REFUSED,
        {"command": "aggregate", "refused": "expect_invalid"},
    )


def test_a_held_lock_refuses_the_writing_commands(operator: _Operator) -> None:
    operator.engine.connection.lock_free = False
    for argv in (
        ["run-once", "--source", operator.source("rfc")],
        ["backfill", "--source", operator.source("rfc")],
        ["rederive"],
    ):
        code, out = operator(*argv)
        assert (code, out["refused"]) == (cli.EXIT_REFUSED, "lock_held")
    assert not operator.scene.world.project_reports.snapshots


# ---- the log-line no-content guard ------------------------------------------------------


def _cell_texts() -> set[str]:
    """Every fixture cell (and header) of four characters or more that is not bare digits.

    A bare digit run (a count such as `1027`) is indistinguishable from a
    printed count; every other cell -- text, an amount, a date -- is content.
    """
    texts: set[str] = set()
    for path in sorted(FIXTURES.rglob("*.csv")):
        try:
            plan = prepare_export(path.read_bytes())
        except ExportRejectedError:
            continue
        for record in plan.records:
            texts.update(
                cell for cell in record.cells if len(cell.strip()) >= 4 and not cell.isdigit()
            )
    return texts


def _banned(scene: Scene) -> set[str]:
    names = {name for placed in scene.placed.values() for name in placed}
    banned = set(names)
    banned |= {name.rsplit("/", 1)[1] for name in names}
    banned |= {name.rsplit("/", 1)[1].split("-", 1)[1].removesuffix(".csv") for name in names}
    banned |= {folder_of(d) for d in DIRECTORIES} | {EXPORT_ROOT}
    banned |= {path.name for path in FIXTURES.rglob("*.csv")}
    banned |= set(DSN_PARTS)
    return banned


def _leaks(text: str, banned: set[str], cells: set[str]) -> list[str]:
    found = [token for token in banned if token in text]
    # A cell leaks as itself, or JSON-escaped.
    found += [cell for cell in cells if cell in text or json.dumps(cell)[1:-1] in text]
    return sorted(found)


def test_no_line_printed_over_the_fixtures_carries_content(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    operator = _Operator(monkeypatch, capsys)
    scene = operator.scene
    for source in scene.sources.values():
        operator("backfill", "--source", source, "--dry-run")
        operator("backfill", "--source", source)
        operator("run-once", "--source", source)
    scene.rebind("variants", state=BindingState.RETIRED)
    operator("backfill", "--source", scene.sources["variants"])
    operator("rederive", "--dry-run")
    operator("rederive")
    operator("coverage")
    argv = [arg for source in scene.sources.values() for arg in ("--source", source)]
    operator("aggregate", *argv)
    expected = tmp_path / "expected.json"
    expected.write_text(
        json.dumps(
            {"schema": "project_reports_evidence_aggregate_v1", "counts": {"files.total": 0}}
        )
    )
    operator("aggregate", *argv, "--expect", str(expected))
    # The worker step: the poll (twice, so the stable files are read) and the sweep.
    from apps import worker as worker_app

    step = worker_app._project_reports_step(
        scene.lifecycle, scene.rederiver(), scene.principal, 900
    )
    for _ in range(2):
        step.run_once()
    lines = [*operator.outputs, capsys.readouterr().out]
    assert len(operator.outputs) == 3 * len(scene.sources) + 6
    cells = _cell_texts()
    assert len(cells) > 100  # the guard has something to find
    leaks = [leak for line in lines for leak in _leaks(line, _banned(scene), cells)]
    assert leaks == []


def test_the_guard_sees_a_planted_leak() -> None:
    scene = Scene()
    scene.place(("signatures",))
    cells = _cell_texts()
    planted_name = json.dumps({"path": scene.placed["signatures"][0]})
    planted_cell = json.dumps({"x": sorted(cells)[0]})
    assert _leaks(planted_name, _banned(scene), cells)
    assert _leaks(planted_cell, _banned(scene), cells)
    assert not _leaks(json.dumps({"counts": {"rows.data": 3}}), _banned(scene), cells)
