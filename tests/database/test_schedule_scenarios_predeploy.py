"""Schedule Scenarios revision-A pre-deploy checks on a disposable scratch catalog (14.9).

Every test runs against the per-test clone of the current head on the isolated
test cluster; each plant (a default privilege, a grant, an ACL change, a
narrowed CHECK, a retired-role row, a dropped trigger, a role without reach)
dies with the clone, and a role created for a plant is dropped before the test
ends. Nothing here connects to any other database.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.dialects import postgresql

from my_pa.infrastructure.database import schedule_scenarios_predeploy as predeploy
from my_pa.infrastructure.database.schedule_scenarios_predeploy import (
    RETIRED_ROLE_PROBE,
    STATEMENTS,
    CheckStatus,
    PredeployCheck,
    PredeployPhase,
    run_predeploy_checks,
)
from tests.database.schedule_plane_world import (
    disposed_lease_engines,  # noqa: F401 - an autouse fixture
)

pytestmark = pytest.mark.database

RUNNER: Final = (
    Path(__file__).resolve().parents[2] / "ops/postgres/schedule_scenarios_predeploy_check.py"
)
ROLE: Final = "s62_predeploy_reachless"


def _run(
    engine: Engine, phase: PredeployPhase, before: str | None = None, *, role: str | None = None
) -> dict[str, PredeployCheck]:
    with engine.connect() as connection:
        if role is not None:
            connection.execute(text(f"SET ROLE {role}"))
            connection.commit()
        try:
            checks = run_predeploy_checks(connection, phase, before_acl_sha256=before)
        finally:
            if role is not None:
                connection.invalidate()  # a session role never goes back into the pool
    return {check.check_id: check for check in checks}


def _before_digest(engine: Engine) -> str:
    detail = _run(engine, PredeployPhase.BEFORE)["Q5"].detail
    assert detail.startswith("sha256=")
    return detail.removeprefix("sha256=")


def _plant(engine: Engine, *statements: str) -> None:
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


@pytest.fixture
def reachless_role(db_engine: Engine) -> Iterator[str]:
    """A cluster role with no privilege on any plane table, dropped at teardown."""
    _plant(db_engine, f"CREATE ROLE {ROLE} NOLOGIN", f"GRANT {ROLE} TO CURRENT_USER")
    try:
        yield ROLE
    finally:
        _plant(db_engine, f"DROP OWNED BY {ROLE}", f"DROP ROLE {ROLE}")


def test_predeploy_checks_pass_on_a_clean_scratch_database(db_engine: Engine) -> None:
    before = _run(db_engine, PredeployPhase.BEFORE)
    assert list(before) == ["Q0", "Q1", "Q2", "Q3", "Q4", "Q5"]
    for check_id in ("Q0", "Q1", "Q2", "Q4"):
        assert before[check_id].status is CheckStatus.HOLDS, before[check_id]
    assert before["Q2"].detail == "retired_role_rows=false"
    assert before["Q3"].status is CheckStatus.REPORT
    assert before["Q3"].detail.count("rows~") == 3
    assert "reach=owner" in before["Q4"].detail and "owner=" in before["Q4"].detail
    digest = before["Q5"].detail.removeprefix("sha256=")
    assert before["Q5"].status is CheckStatus.REPORT and len(digest) == 64
    after = _run(db_engine, PredeployPhase.AFTER, digest)
    assert list(after) == ["Q0", "Q5", "Q6", "Q7", "Q8", "Q9"]
    assert all(check.status is CheckStatus.HOLDS for check in after.values()), after
    assert after["Q9"].detail == "tables=11,functions=15,trigger=1"


def test_checks_are_read_only_and_always_roll_back(
    db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every statement is a `SELECT`; the run is `READ ONLY` and is rolled back on every path."""
    assert all(sql.lstrip().upper().startswith("SELECT ") for sql in STATEMENTS.values())
    compiled = str(RETIRED_ROLE_PROBE.compile(dialect=postgresql.dialect()))
    assert compiled.lstrip().upper().startswith("SELECT EXISTS") and ";" not in compiled
    assert compiled.count("SELECT") == 2  # the outer SELECT and its EXISTS subquery
    with db_engine.connect() as connection:
        checks = run_predeploy_checks(connection, PredeployPhase.BEFORE)
        assert not connection.in_transaction()
    assert checks[0].detail == "transaction_read_only=on"

    def failing(_connection: object) -> PredeployCheck:
        raise LookupError("a check failed")

    monkeypatch.setattr(predeploy, "_lock_sizing", failing)
    with db_engine.connect() as connection:
        with pytest.raises(LookupError):
            run_predeploy_checks(connection, PredeployPhase.BEFORE)
        assert not connection.in_transaction()
        connection.execute(text("SELECT 1"))
        with pytest.raises(ValueError, match="open transaction"):
            run_predeploy_checks(connection, PredeployPhase.BEFORE)
    # A write inside the run would be refused: the transaction really is read only.
    with db_engine.connect() as connection, connection.begin():
        connection.execute(text(predeploy.READ_ONLY))
        with pytest.raises(Exception, match="read-only transaction"):
            connection.execute(text("CREATE TABLE knowledge.predeploy_probe (x int)"))


_RETIRED_ROW: Final = (
    "INSERT INTO knowledge.schedule_publications (publication_id, principal_id, project_id, "
    "series_id, enrollment_id, source_object_id, source_version_id, idempotency_key, "
    "request_digest, publication_role, baseline_kind) VALUES ('spub_s62predep01', "
    "'prn_s62predep001', 'prj_s62predep001', 'sser_s62predep01', 'enr_s62predep001', "
    "'obj_s62predep001', 'ver_s62predep001', 'predeploy-key-01', repeat('0', 64), 'reference', "
    "NULL)"
)

#: check id -> (phase, plant statements, expected detail fragment).
_STOPS: Final[dict[str, tuple[PredeployPhase, tuple[str, ...], str]]] = {
    "Q1": (
        PredeployPhase.BEFORE,
        ("ALTER DEFAULT PRIVILEGES IN SCHEMA knowledge GRANT USAGE ON SEQUENCES TO PUBLIC",),
        ":knowledge:S:PUBLIC",
    ),
    "Q2_retired": (
        PredeployPhase.BEFORE,
        (
            "ALTER TABLE knowledge.schedule_publications DROP CONSTRAINT "
            "a_schedule_publication_role_is_known",
            "SET LOCAL session_replication_role = replica",
            _RETIRED_ROW,
        ),
        "retired_role_rows=true",
    ),
    "Q2_absent": (
        PredeployPhase.BEFORE,
        ("ALTER TABLE knowledge.schedule_import_issues RENAME TO schedule_import_issues_gone",),
        "absent=schedule_import_issues",
    ),
    "Q5": (
        PredeployPhase.AFTER,
        ("GRANT SELECT ON knowledge.record_links TO PUBLIC",),
        "sha256=",
    ),
    "Q6": (
        PredeployPhase.AFTER,
        (
            "GRANT SELECT ON knowledge.schedule_cpm_runs TO PUBLIC",
            "GRANT USAGE ON SEQUENCE knowledge.schedule_scenario_write_refusals_refusal_no_seq "
            "TO PUBLIC",
        ),
        "public:schedule_cpm_runs",
    ),
    "Q7": (
        PredeployPhase.AFTER,
        (
            "ALTER TABLE knowledge.schedule_publications DROP CONSTRAINT "
            "a_schedule_publication_role_is_known, ADD CONSTRAINT "
            "a_schedule_publication_role_is_known CHECK (publication_role IN ('baseline', "
            "'reference', 'update'))",
        ),
        "a_schedule_publication_role_is_known:!reference",
    ),
    "Q9": (
        PredeployPhase.AFTER,
        (
            "DROP TRIGGER a_schedule_intake_series_admits_no_other_publication ON "
            "knowledge.schedule_publications",
        ),
        "trigger:a_schedule_intake_series_admits_no_other_publication",
    ),
}


@pytest.mark.parametrize("case", sorted(_STOPS))
def test_each_check_reports_its_stop(db_engine: Engine, case: str) -> None:
    phase, statements, fragment = _STOPS[case]
    check_id = case.split("_", 1)[0]
    digest = _before_digest(db_engine)
    _plant(db_engine, *statements)
    found = _run(db_engine, phase, digest if phase is PredeployPhase.AFTER else None)[check_id]
    assert found.status is CheckStatus.STOP, found
    assert fragment in found.detail, found
    if case == "Q6":
        assert "sequence:schedule_scenario_write_refusals.refusal_no" in found.detail


@pytest.mark.parametrize(
    ("check_id", "phase"), [("Q4", PredeployPhase.BEFORE), ("Q8", PredeployPhase.AFTER)]
)
def test_a_role_without_reach_stops(
    db_engine: Engine, reachless_role: str, check_id: str, phase: PredeployPhase
) -> None:
    """Q4/Q8 judge the connecting runtime role (`current_user`), not the migrating owner."""
    digest = _before_digest(db_engine)
    found = _run(db_engine, phase, digest, role=reachless_role)[check_id]
    assert found.status is CheckStatus.STOP, found
    if check_id == "Q4":
        assert found.detail.endswith("reach=none") and f"current={reachless_role}" in found.detail
        q2 = _run(db_engine, phase, role=reachless_role)["Q2"]
        assert (q2.status, q2.detail) == (CheckStatus.STOP, "retired_role_rows=unreadable")
    else:
        assert "schedule_scenario_write_requests:UPDATE" in found.detail


def test_the_after_phase_stops_without_the_before_digest(db_engine: Engine) -> None:
    q5 = _run(db_engine, PredeployPhase.AFTER)["Q5"]
    assert q5.status is CheckStatus.STOP and q5.detail.endswith("before=missing")


def _runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("schedule_scenarios_predeploy_check", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_runner_prints_one_line_per_check_and_no_connection_string(
    cloned_database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ops runner over `MY_PA_DATABASE_URL`, which the fixture points at the clone."""
    main: Callable[[list[str]], int] = _runner().main
    assert main(["--phase", "before"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[1] for line in lines[:-1]] == ["Q0", "Q1", "Q2", "Q3", "Q4", "Q5"]
    assert lines[-1] == "schedule_scenarios_predeploy phase=before result=pass"
    digest = lines[5].rsplit("sha256=", 1)[1]
    assert main(["--phase", "after", "--before-acl-sha256", digest]) == 0
    after = capsys.readouterr().out
    assert after.endswith("schedule_scenarios_predeploy phase=after result=pass\n")
    assert main(["--phase", "after"]) == 1
    stopped = capsys.readouterr().out
    assert stopped.endswith("result=stop\n")
    database_name = cloned_database_url.rsplit("/", 1)[1]
    for output in (*lines, after, stopped):
        assert "postgresql" not in output
        assert database_name not in output
