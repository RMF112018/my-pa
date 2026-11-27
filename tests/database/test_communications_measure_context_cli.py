"""WP5-S6: `communications_ingest.py measure-context` end to end on PostgreSQL.

The `database` tier, on a disposable head-migrated clone. The WP4 latency set
(`test_communications_search_latency._seed`: 3,500 messages, 28,000
participant rows, identifiers) and the synthetic project-report world
(`build_world`, through the real WP3P path) are written under the local
operator Principal, the one the command acts as; a second Principal's messages
are written beside them with addresses of their own. The command is run
through `apps.cli.communications_ingest.main`, exactly as the Manager runs it.

Proved here: the probe facts come from the operator's own rows only (no
foreign address reaches a probe: each probe's attendees match its messages);
the probes link to the bound Projects, so PULSE on answers `available`; the
statement count of 1 and of 10 probes is equal (the anti-N+1 proof, through
the seam); the output carries no address, subject, Project number or id; and
a head mismatch refuses `target_mismatch` before anything is measured. Every
value is synthetic.
"""

from __future__ import annotations

import json
import os
from typing import Any, Final

import pytest
from apps.cli import communications_ingest as cli
from sqlalchemy import text, update
from sqlalchemy.engine import make_url

from my_pa.bootstrap.gateway import local_principal
from my_pa.bootstrap.project_reports import project_reports_unit_of_work
from my_pa.infrastructure.persistence.tables import projects
from tests.database.communications_search_world import OTHER, World, at
from tests.database.test_communications_search_latency import _seed
from tests.database.test_task_record_events import Runtime
from tests.unit.project_report_reads_scene import (
    OBS_PROJECT,
    RFI_PROJECT,
    ReadsScene,
    build_world,
    database_scene,
)

pytestmark = pytest.mark.database

#: Synthetic Project numbers, each occurring in the seed's text (`RFI 175`...).
NUMBERS: Final = ("175", "176")
FOREIGN: Final = "foreign.only@example.invalid"


def _run(capsys: pytest.CaptureFixture[str], expect: list[str], *argv: str) -> tuple[int, Any, str]:
    code = cli.main([*expect, "measure-context", *argv])
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = captured.out.splitlines()
    assert len(lines) == 1, captured.out
    return code, json.loads(lines[0]), lines[0]


def test_measure_context_on_the_seed(
    disposable_database: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = Runtime(disposable_database)
    try:
        principal_id = local_principal().principal_id
        _seed(runtime.work_engine, principal_id)
        foreign = World(runtime.work_engine, principal_id=OTHER, tag="f")
        for n in range(5):
            foreign.message(
                n,
                subject=f"Foreign subject {n}",
                text="RFI 174 foreign",
                when=at(18 + n % 3, 9),
                participants=(
                    ("from", FOREIGN),
                    *(("to", f"foreign{n}x{k}@example.invalid") for k in range(4)),
                ),
                lanes=(("sent", "verified"),),
            )
        reports = ReadsScene(
            unit=project_reports_unit_of_work(runtime.work_engine),
            add_project=database_scene(runtime.work_engine).add_project,
            principal_id=principal_id,
        )
        build_world(reports)
        with runtime.work_engine.begin() as connection:
            for project_id, number in zip((RFI_PROJECT[1], OBS_PROJECT[1]), NUMBERS, strict=True):
                connection.execute(
                    update(projects)
                    .where(projects.c.project_id == project_id)
                    .values(project_number=number)
                )
            for table in ("messages", "participants", "identifiers", "observations"):
                connection.exec_driver_sql(f"ANALYZE knowledge.communication_{table}")
        monkeypatch.setenv("MY_PA_DATABASE_URL", disposable_database)
        database = make_url(os.environ["MY_PA_DATABASE_URL"]).database
        with runtime.work_engine.connect() as connection:
            head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        expect = ["--expected-database", str(database), "--expected-alembic-head", str(head)]

        code, out, line = _run(capsys, expect, "--runs", "3")
        assert code == cli.EXIT_OK, out
        assert (out["probes"], out["anchor_basis"]) == (10, "coverage")
        latency = out["latency"]
        assert set(latency) == {f"meetings_{n}_pulse_{p}" for n in (1, 10) for p in ("off", "on")}
        # The anti-N+1 proof through the seam: 1 and 10 probes cost the same statements.
        assert (
            latency["meetings_1_pulse_off"]["statements"]
            == (latency["meetings_10_pulse_off"]["statements"])
        )
        assert all(shape["statements"] > 0 for shape in latency.values())
        probes = out["per_probe"]
        assert all(p["inputs"]["attendee_keys"] >= 3 for p in probes)
        assert all(p["inputs"]["identifiers"] >= 1 for p in probes)
        assert all(p["matched_total"] > 0 for p in probes)
        # Every probe's attendees are participants of the operator's own messages.
        assert all(p["by_matched_by"].get("participants", 0) > 0 for p in probes)
        assert out["pulse"]["bound_projects"] >= 2
        assert out["pulse"]["by_state"].get("available", 0) >= 1
        assert out["quarantined_identity_kind_mismatch"] == 0
        assert out["bridge"]["truncated"] is False
        # Counts only.
        assert "@" not in line
        for value in ("example.invalid", "Foreign", "mtg_", "matt_", "prj_", "cmsg_", "conv-"):
            assert value not in line
        for number in NUMBERS:
            assert f'"{number}"' not in line

        assert _run(capsys, [*expect[:3], "0123abcd"])[1] == {
            "command": "measure-context",
            "refused": "target_mismatch",
        }
    finally:
        runtime.close()
