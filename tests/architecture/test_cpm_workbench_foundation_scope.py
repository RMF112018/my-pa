"""What the S5b-1 Schedule foundation deliberately does not do yet (foundation contract 3.3, 5.4).

WP-01 adds the `SCHEDULE_JOBS` plane constant and nothing that could run it:
no worker plane, no heartbeat vocabulary, no health surface and no
application fallback names `schedule` until WP-03 lands the handler (D-02).
Each of the four surfaces is asserted separately, so WP-03 has to flip each
one on purpose and a message names the surface that moved.

The dedicated `ScheduleUnitOfWork` stays out of the general `UnitOfWork`
(D-21), the repository module writes no raw SQL and no grant, and the admission
digest and Series key are deterministic across processes.

FAST: nothing here opens a database connection.
"""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock

import pytest
from apps import worker as worker_app

from my_pa.contracts import ports
from my_pa.infrastructure.persistence import jobs, worker_health
from my_pa.infrastructure.persistence.tables import worker_heartbeats

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEDULE_MODULE: Final = ROOT / "src/my_pa/infrastructure/persistence/schedule.py"
PLANE_TUPLE_FILES: Final = (
    ROOT / "src/my_pa/application/service.py",
    ROOT / "src/my_pa/infrastructure/persistence/unit_of_work.py",
)
PRINCIPAL: Final = "prn_cpmscope0001"


def _plane_tuples(path: Path) -> list[tuple[str, ...]]:
    """Every tuple of string literals naming both the capture and enrollment planes."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Tuple) and all(
            isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.elts
        ):
            values = tuple(str(item.value) for item in node.elts)  # type: ignore[attr-defined]
            if {"capture", "enrollment"} <= set(values):
                found.append(values)
    return found


def test_schedule_plane_is_not_runnable_before_its_handler() -> None:
    # 1. `apps/worker.py`: `--plane schedule` stays an argparse error.
    assert "schedule" not in worker_app._PLANES, "surface 1: apps/worker.py _PLANES"
    assert "schedule" not in worker_app._JOB_PLANES, "surface 1: apps/worker.py _JOB_PLANES"
    # 2. The heartbeat CHECK at head.
    (plane_check,) = (
        constraint
        for constraint in worker_heartbeats.constraints
        if constraint.name == "worker_plane_is_known"
    )
    check_text = str(plane_check.sqltext)  # type: ignore[attr-defined]
    assert "'capture'" in check_text, "surface 2: the heartbeat CHECK was not read"
    assert "schedule" not in check_text, "surface 2: worker_heartbeats.worker_plane_is_known"
    # 3. The heartbeat allowlist and the health map refuse before any statement.
    connection = MagicMock()
    with pytest.raises(ValueError, match="unknown worker plane"):
        worker_health.record_worker_heartbeat(
            connection, owner="cpm-scope", principal_id=PRINCIPAL, plane="schedule"
        )
    assert not connection.mock_calls, "surface 3: record_worker_heartbeat issued a statement"
    with pytest.raises(ValueError, match="unknown worker plane"):
        worker_health.worker_plane_health(connection, principal_id=PRINCIPAL, plane_name="schedule")
    assert not connection.mock_calls, "surface 3: worker_plane_health issued a statement"
    # 4. The application fallback and the unit-of-work health read.
    for path in PLANE_TUPLE_FILES:
        tuples = _plane_tuples(path)
        assert tuples, f"surface 4: no worker-plane tuple found in {path.name}"
        for values in tuples:
            assert "schedule" not in values, f"surface 4: {path.name} names a schedule plane"


def test_schedule_jobs_is_a_plane_constant_only() -> None:
    assert "SCHEDULE_JOBS" in jobs.__all__
    plane = jobs.SCHEDULE_JOBS
    assert (plane.table.name, plane.subject, plane.owner_table.name) == (
        "schedule_jobs",
        "publication_id",
        "schedule_publications",
    )
    assert plane.lease_generation is None and plane.pause_cause is None
    planes = {plane for plane, _ in worker_app._JOB_PLANES.values()}
    assert jobs.SCHEDULE_JOBS not in planes


def test_schedule_ports_are_not_on_the_general_unit_of_work() -> None:
    general = inspect.getsource(ports.UnitOfWork)
    assert "Schedule" not in general
    assert not hasattr(ports.UnitOfWork, "schedules")
    members = {name for name, _ in inspect.getmembers(ports.ScheduleUnitOfWork)}
    assert "schedules" in members
    assert {"record_events", "projects"}.isdisjoint(members)
    assert not issubclass(ports.ScheduleUnitOfWork, ports.UnitOfWork)


def test_the_schedule_repository_writes_no_raw_sql_and_no_grant() -> None:
    source = SCHEDULE_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "text" not in imported
    assert "mcp_object_grants" not in source
    for word in ("GRANT ", "REVOKE ", "TRUNCATE", "DELETE FROM"):
        assert word not in source.upper(), word


_DETERMINISM: Final = """
from datetime import date
from my_pa.domain.schedule import (
    ScheduleBaselineKind, ScheduleImportRequest, SchedulePublicationRole,
    normalize_series_name, schedule_import_request_digest,
)
name = normalize_series_name("  Master\\u00a0SCHEDULE\\tÉtape  ")
request = ScheduleImportRequest(
    project_id="prj_cpmscope0001", series_id=None, series_name=name,
    enrollment_id="enr_cpmscope0001", source_object_id="obj_cpmscope0001",
    source_version_id="ver_cpmscope0001", publication_role=SchedulePublicationRole.BASELINE,
    baseline_kind=ScheduleBaselineKind.CONTRACT, expected_data_date=date(2026, 5, 4),
    supersedes_publication_id=None, idempotency_key="cpm-scope-0001",
)
print(name.name, name.key, schedule_import_request_digest("prn_cpmscope0001", request), sep="|")
"""


def test_request_digest_and_series_key_are_deterministic_across_processes() -> None:
    """No set ordering or hash seed reaches the digest or the Series key."""
    outputs = set()
    for seed in ("0", "1", "4242"):
        environment = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT / "src")}
        completed = subprocess.run(  # noqa: S603 - this interpreter, a fixed script
            [sys.executable, "-c", _DETERMINISM],
            capture_output=True,
            check=True,
            env=environment,
            text=True,
            timeout=60,
        )
        outputs.add(completed.stdout.strip())
    (output,) = outputs
    name, key, digest = output.split("|")
    assert (name, key) == ("Master SCHEDULE Étape", "master schedule étape")
    assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")
