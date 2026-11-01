"""CPM Workbench pre-deploy checks on a disposable scratch catalog (worker contract 3.16).

Every test runs against the per-test clone of the current head on the isolated
test cluster; the plants (a default privilege, a grant, an ACL change, a narrowed
CHECK) die with the clone. Nothing here connects to any other database.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest
from sqlalchemy import Engine, text

from my_pa.infrastructure.database.cpm_workbench_predeploy import (
    CheckStatus,
    PredeployCheck,
    PredeployPhase,
    run_predeploy_checks,
)

pytestmark = pytest.mark.database

RUNNER: Final = (
    Path(__file__).resolve().parents[2] / "ops/postgres/cpm_workbench_predeploy_check.py"
)


def _run(
    engine: Engine, phase: PredeployPhase, before: str | None = None
) -> dict[str, PredeployCheck]:
    with engine.connect() as connection:
        checks = run_predeploy_checks(connection, phase, before_acl_sha256=before)
    return {check.check_id: check for check in checks}


def _before_digest(engine: Engine) -> str:
    detail = _run(engine, PredeployPhase.BEFORE)["P5"].detail
    assert detail.startswith("sha256=")
    return detail.removeprefix("sha256=")


def _plant(engine: Engine, *statements: str) -> None:
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def test_predeploy_checks_pass_on_a_clean_scratch_database(db_engine: Engine) -> None:
    before = _run(db_engine, PredeployPhase.BEFORE)
    assert list(before) == ["P0", "P1", "P2", "P3", "P4", "P5"]
    assert before["P0"].status is CheckStatus.HOLDS
    assert before["P0"].detail == "transaction_read_only=on"
    for check_id in ("P1", "P2", "P4"):
        assert before[check_id].status is CheckStatus.HOLDS, before[check_id]
    assert before["P3"].status is CheckStatus.REPORT
    assert before["P3"].detail.count("rows~") == 4
    assert before["P5"].status is CheckStatus.REPORT
    digest = before["P5"].detail.removeprefix("sha256=")
    assert len(digest) == 64

    after = _run(db_engine, PredeployPhase.AFTER, digest)
    assert list(after) == ["P0", "P5", "P6", "P7", "P8"]
    assert all(check.status is CheckStatus.HOLDS for check in after.values()), after


def test_the_after_phase_stops_without_the_before_digest(db_engine: Engine) -> None:
    after = _run(db_engine, PredeployPhase.AFTER)
    assert after["P5"].status is CheckStatus.STOP
    assert after["P5"].detail.endswith("before=missing")


def test_predeploy_check_reports_a_planted_default_privilege(db_engine: Engine) -> None:
    _plant(
        db_engine, "ALTER DEFAULT PRIVILEGES IN SCHEMA knowledge GRANT SELECT ON TABLES TO PUBLIC"
    )
    p1 = _run(db_engine, PredeployPhase.BEFORE)["P1"]
    assert p1.status is CheckStatus.STOP
    assert p1.detail.endswith(":knowledge:PUBLIC"), p1.detail


def test_a_global_default_privilege_is_a_stop_too(db_engine: Engine) -> None:
    _plant(db_engine, "ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO PUBLIC")
    p1 = _run(db_engine, PredeployPhase.BEFORE)["P1"]
    assert p1.status is CheckStatus.STOP
    assert ":<global>:PUBLIC" in p1.detail


def test_a_default_privilege_in_another_schema_is_not_a_stop(db_engine: Engine) -> None:
    _plant(
        db_engine,
        "CREATE SCHEMA predeploy_elsewhere",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA predeploy_elsewhere GRANT SELECT ON TABLES TO PUBLIC",
    )
    assert _run(db_engine, PredeployPhase.BEFORE)["P1"].status is CheckStatus.HOLDS


def test_a_grant_on_a_cpm_table_stops_the_after_phase(db_engine: Engine) -> None:
    digest = _before_digest(db_engine)
    _plant(db_engine, "GRANT SELECT ON knowledge.schedule_rows TO PUBLIC")
    p6 = _run(db_engine, PredeployPhase.AFTER, digest)["P6"]
    assert p6.status is CheckStatus.STOP
    assert p6.detail == "public:schedule_rows"


def test_a_changed_live_acl_stops_the_after_phase(db_engine: Engine) -> None:
    digest = _before_digest(db_engine)
    _plant(db_engine, "GRANT SELECT ON knowledge.enrollments TO PUBLIC")
    p5 = _run(db_engine, PredeployPhase.AFTER, digest)["P5"]
    assert p5.status is CheckStatus.STOP
    assert p5.detail != f"sha256={digest}"


def test_a_vocabulary_check_without_the_schedule_plane_stops(db_engine: Engine) -> None:
    digest = _before_digest(db_engine)
    _plant(
        db_engine,
        "ALTER TABLE knowledge.worker_heartbeats DROP CONSTRAINT worker_plane_is_known",
        "ALTER TABLE knowledge.worker_heartbeats ADD CONSTRAINT worker_plane_is_known "
        "CHECK (plane IN ('capture', 'enrollment', 'reenrichment'))",
    )
    p7 = _run(db_engine, PredeployPhase.AFTER, digest)["P7"]
    assert p7.status is CheckStatus.STOP
    assert p7.detail == "worker_plane_is_known:schedule"


def test_the_checks_refuse_an_open_transaction(db_engine: Engine) -> None:
    with db_engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        with pytest.raises(ValueError, match="open transaction"):
            run_predeploy_checks(connection, PredeployPhase.BEFORE)


def _runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cpm_workbench_predeploy_check", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_runner_prints_one_line_per_check_and_no_connection_string(
    cloned_database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ops runner over `MY_PA_DATABASE_URL`, which the fixture points at the clone."""
    runner = _runner()
    assert runner.main(["--phase", "before"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[1] for line in lines[:-1]] == ["P0", "P1", "P2", "P3", "P4", "P5"]
    assert lines[-1] == "cpm_workbench_predeploy phase=before result=pass"
    digest = lines[5].rsplit("sha256=", 1)[1]
    assert runner.main(["--phase", "after", "--before-acl-sha256", digest]) == 0
    after = capsys.readouterr().out
    assert after.endswith("cpm_workbench_predeploy phase=after result=pass\n")
    assert runner.main(["--phase", "after"]) == 1
    stopped = capsys.readouterr().out
    assert stopped.endswith("result=stop\n")
    database_name = cloned_database_url.rsplit("/", 1)[1]
    for output in (*lines, after, stopped):
        assert "postgresql" not in output
        assert database_name not in output
