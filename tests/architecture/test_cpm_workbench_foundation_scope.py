"""The S5b-1 Schedule foundation's boundaries (foundation contract 3.3, 5.4).

WP-01 added the `SCHEDULE_JOBS` plane constant and nothing that could run it.
S5b-2 (WP-03, worker and capabilities contract section 3.2) moved the four
surfaces together: the worker plane, the heartbeat vocabulary, the health
surface and the application fallback now name `schedule` (the last two only
while the Schedule plane is served). Each surface is still asserted
separately, so a message names the surface that moved.

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
from unittest.mock import MagicMock, patch

import pytest
from apps import worker as worker_app
from tests.conftest import Scene, build_service, metadata_for

from my_pa.application.commands import GetCapabilities
from my_pa.contracts import ports
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.jobs.schedule import process_schedule_publication
from my_pa.infrastructure.persistence import jobs, worker_health
from my_pa.infrastructure.persistence import unit_of_work as unit_of_work_module
from my_pa.infrastructure.persistence.tables import worker_heartbeats

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEDULE_MODULE: Final = ROOT / "src/my_pa/infrastructure/persistence/schedule.py"
PRINCIPAL: Final = "prn_cpmscope0001"


def _uow_planes(*, schedule_enabled: bool) -> list[str]:
    """The planes the unit-of-work health read asks `worker_plane_health` for."""
    asked: list[str] = []

    def health(_connection: object, *, principal_id: str, plane_name: str) -> object:
        asked.append(plane_name)
        return worker_health.WorkerPlaneHealth(plane_name, "idle_or_not_required", 0, 0, None)

    with patch.object(unit_of_work_module, "worker_plane_health", health):
        unit_of_work_module._WorkerHealth(
            MagicMock(), schedule_enabled=schedule_enabled
        ).for_principal(PRINCIPAL)
    return asked


def _fallback_planes(scene: Scene, *, schedule_enabled: bool) -> list[str]:
    """The planes `capabilities.get` reports when no worker-health read exists."""
    service = build_service(scene.world, scene.providers, schedule_enabled=schedule_enabled)
    envelope = service.invoke(
        metadata_for(Capability.CAPABILITIES_GET, Purpose.STATUS_OBSERVATION, scene.principal),
        GetCapabilities(),
        principal=scene.principal,
    )
    assert envelope.error is None and envelope.result is not None, envelope.error
    planes = envelope.result["worker_planes"]
    assert isinstance(planes, list)
    assert all(plane["state"] == "unavailable" for plane in planes), "the fallback was not reached"
    return [str(plane["plane"]) for plane in planes]


def test_schedule_plane_is_runnable_on_all_four_surfaces(scene: Scene) -> None:
    """S5b-2 (worker and capabilities contract section 3.2): the 4 surfaces moved together.

    Converted in place from S5b-1's `test_schedule_plane_is_not_runnable_before_its_handler`;
    each surface is still asserted separately and a message names it.
    """
    # 1. `apps/worker.py`: the schedule job plane and its handler.
    assert worker_app._JOB_PLANES.get("schedule") == (
        jobs.SCHEDULE_JOBS,
        process_schedule_publication,
    ), "surface 1: apps/worker.py _JOB_PLANES"
    assert "schedule" in worker_app._PLANES, "surface 1: apps/worker.py _PLANES"
    # 2. The heartbeat CHECK at head.
    (plane_check,) = (
        constraint
        for constraint in worker_heartbeats.constraints
        if constraint.name == "worker_plane_is_known"
    )
    check_text = str(plane_check.sqltext)  # type: ignore[attr-defined]
    assert "'capture'" in check_text, "surface 2: the heartbeat CHECK was not read"
    assert "'schedule'" in check_text, "surface 2: worker_heartbeats.worker_plane_is_known"
    # 3. The heartbeat allowlist and the health map admit the plane.
    connection = MagicMock()
    worker_health.record_worker_heartbeat(
        connection, owner="cpm-scope", principal_id=PRINCIPAL, plane="schedule"
    )
    assert len(connection.execute.mock_calls) == 1, "surface 3: record_worker_heartbeat"
    health = MagicMock()
    health.scalar.side_effect = RuntimeError("first statement reached")
    with pytest.raises(RuntimeError, match="first statement reached"):
        worker_health.worker_plane_health(health, principal_id=PRINCIPAL, plane_name="schedule")
    # 4. The unit-of-work health read and the application fallback name `schedule`
    # exactly when the Schedule plane is served (both polarities).
    assert _uow_planes(schedule_enabled=False) == ["capture", "enrollment"], (
        "surface 4: the unit-of-work read names schedule while the plane is off"
    )
    assert _uow_planes(schedule_enabled=True) == ["capture", "enrollment", "schedule"], (
        "surface 4: the unit-of-work read omits schedule while the plane is on"
    )
    assert _fallback_planes(scene, schedule_enabled=False) == ["capture", "enrollment"], (
        "surface 4: the service fallback names schedule while the plane is off"
    )
    assert _fallback_planes(scene, schedule_enabled=True) == [
        "capture",
        "enrollment",
        "schedule",
    ], "surface 4: the service fallback omits schedule while the plane is on"


def test_schedule_jobs_is_the_schedule_plane() -> None:
    assert "SCHEDULE_JOBS" in jobs.__all__
    plane = jobs.SCHEDULE_JOBS
    assert (plane.table.name, plane.subject, plane.owner_table.name) == (
        "schedule_jobs",
        "publication_id",
        "schedule_publications",
    )
    assert plane.lease_generation is None and plane.pause_cause is None
    planes = {plane for plane, _ in worker_app._JOB_PLANES.values()}
    assert jobs.SCHEDULE_JOBS in planes


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
    ScheduleBaselineKind, ScheduleImportApproval, ScheduleImportRequest,
    SchedulePublicationRole, normalize_series_name, schedule_import_request_digest,
)
name = normalize_series_name("  Master\\u00a0SCHEDULE\\tÉtape  ")
request = ScheduleImportRequest(
    project_id="prj_cpmscope0001", series_id=None, series_name=name,
    enrollment_id="enr_cpmscope0001", source_object_id="obj_cpmscope0001",
    source_version_id="ver_cpmscope0001", publication_role=SchedulePublicationRole.BASELINE,
    baseline_kind=ScheduleBaselineKind.CONTRACT, expected_data_date=date(2026, 5, 4),
    supersedes_publication_id=None, idempotency_key="cpm-scope-0001",
    approval=ScheduleImportApproval("Award letter", date(2026, 6, 1), "Synthetic"),
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
