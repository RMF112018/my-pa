"""Shared world for the Schedule Scenarios S6-2 plane database tests.

A helper module, not a test module: pytest does not collect it. It seeds the
S5 rows the plane names -- Projects, Series and terminal publications -- under
`SET LOCAL session_replication_role = replica` (transaction-scoped, so no pooled
connection keeps it), the `test_schedule_scenarios_schema_guards.py` shape, so
the S5 lifecycle need not be replayed; every plane write then runs in the
default mode through the repository under test. It also holds the writers,
the version builder and the deterministic two-writer interleaving the race
tests use (a seam plus an observed advisory-lock wait in `pg_locks`; no sleep
decides an order). Every value is synthetic.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text

from my_pa.domain.schedule.plane import PlaneProvenance
from my_pa.domain.schedule.scenario.model import ScenarioContent, VersionLabel
from my_pa.domain.schedule.scenario.snapshot import SnapshotReport
from my_pa.infrastructure.persistence import schedule_scenarios as plane_module
from my_pa.infrastructure.persistence.schedule_cpm_lease import dispose_lease_engines
from my_pa.infrastructure.persistence.schedule_scenarios import (
    SqlAlchemyScenarioUnitOfWork,
    new_scenario_version,
)
from tests.fixtures.schedule_scenario import link, network, task

__all__ = [
    "CONTENT",
    "DIGEST",
    "OPERATOR",
    "SNAPSHOT",
    "Interleaving",
    "PlaneWorld",
    "advisory_waiter_seen",
    "client",
    "count_rows",
    "disposed_lease_engines",
    "first_version",
    "seed_publication",
    "seed_world",
]

DIGEST: Final = "0123456789abcdef" * 4
OPERATOR: Final = PlaneProvenance(
    authority_class="local_operator",
    decision_channel="local_cli",
    asserting_client_id=None,
    acceptance_basis="user_confirmed",
)
CONTENT: Final[ScenarioContent] = network([task("A", 480), task("B", 960)], [link("A", "B")])
SNAPSHOT: Final = SnapshotReport(
    activities=2,
    milestones=0,
    durations_quantized=0,
    durations_out_of_range=0,
    original_missing=0,
    remaining_missing=0,
)


def client(name: str = "client-7") -> PlaneProvenance:
    """A connected remote client's provenance (its own writer bucket)."""
    return PlaneProvenance(
        authority_class="ordinary_reviewer",
        decision_channel="remote_interactive",
        asserting_client_id=name,
        acceptance_basis="client_identified",
    )


def first_version(content: ScenarioContent = CONTENT) -> Any:  # noqa: ANN401 - NewScenarioVersion
    return new_scenario_version(content, label=VersionLabel.WHAT_IF, snapshot=SNAPSHOT)


@dataclass(frozen=True)
class PlaneWorld:
    principal: str
    project: str
    other_project: str
    series: str
    publications: tuple[str, ...]
    queued: str
    failed: str
    intake_series: str
    intake_publication: str
    other_series: str
    other_publication: str


def seed_world(engine: Engine, principal: str, tag: str, *, complete: int = 6) -> PlaneWorld:
    """P's Projects, a Series with `complete` complete publications, and an intake Series."""
    world = PlaneWorld(
        principal=principal,
        project=f"prj_{tag}0001",
        other_project=f"prj_{tag}0002",
        series=f"sser_{tag}0001",
        publications=tuple(f"spub_{tag}c{index:03d}" for index in range(complete)),
        queued=f"spub_{tag}q001",
        failed=f"spub_{tag}f001",
        intake_series=f"sser_{tag}0002",
        intake_publication=f"spub_{tag}i001",
        other_series=f"sser_{tag}0003",
        other_publication=f"spub_{tag}o001",
    )
    with engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        for project in (world.project, world.other_project):
            c.execute(
                text(
                    "INSERT INTO knowledge.projects (project_id, principal_id, name, opened_at, "
                    "created_at, updated_at) VALUES (:j, :p, 'Synthetic Project', now(), now(), "
                    "now())"
                ),
                {"j": project, "p": principal},
            )
        intake_name = "Schedule intake " + DIGEST[:12]
        for series, project, name in (
            (world.series, world.project, "Master"),
            (world.intake_series, world.project, intake_name),
            (world.other_series, world.other_project, "Elsewhere"),
        ):
            c.execute(
                text(
                    "INSERT INTO knowledge.schedule_series (series_id, principal_id, project_id, "
                    "name, name_key) VALUES (:s, :p, :j, :n, lower(:n))"
                ),
                {"s": series, "p": principal, "j": project, "n": name},
            )
        rows = [
            (publication, world.series, world.project, "complete")
            for publication in world.publications
        ]
        rows += [
            (world.queued, world.series, world.project, "queued"),
            (world.failed, world.series, world.project, "failed"),
            (world.intake_publication, world.intake_series, world.project, "complete"),
            (world.other_publication, world.other_series, world.other_project, "complete"),
        ]
        for ordinal, (publication, series, project, status) in enumerate(rows):
            seed_publication(c, principal, publication, series, project, status, ordinal)
        c.execute(
            text(
                "INSERT INTO knowledge.schedule_intake_series (principal_id, project_id, "
                "series_id, publication_id) VALUES (:p, :j, :s, :pub)"
            ),
            {
                "p": principal,
                "j": world.project,
                "s": world.intake_series,
                "pub": world.intake_publication,
            },
        )
    return world


def seed_publication(
    c: Any,  # noqa: ANN401 - a Connection
    principal: str,
    publication: str,
    series: str,
    project: str,
    status: str,
    ordinal: int,
) -> None:
    suffix = publication[5:]
    c.execute(
        text(
            "INSERT INTO knowledge.schedule_publications (publication_id, principal_id, "
            "project_id, series_id, enrollment_id, source_object_id, source_version_id, "
            "idempotency_key, request_digest, publication_role) VALUES (:pub, :p, :j, :s, "
            ":enr, :obj, :ver, :key, :digest, 'update')"
        ),
        {
            "pub": publication,
            "p": principal,
            "j": project,
            "s": series,
            "enr": "enr_" + suffix,
            "obj": "obj_" + suffix,
            "ver": "ver_" + suffix,
            "key": "key-" + suffix,
            "digest": DIGEST,
        },
    )
    if status == "queued":
        return
    progress = (
        "processing_started_at = now(), completed_at = now(), issue_count = 1"
        if status == "failed"
        else (
            "processing_started_at = now(), completed_at = now(), accepted_parser_run_id = "
            ":run, document_sha256 = :digest, document_size_bytes = 10, page_count = 1, "
            "row_count = 1, activity_count = 1, ambiguous_row_count = 0, issue_count = 0, "
            "data_date = :data_date"
        )
    )
    c.execute(
        text(
            f"UPDATE knowledge.schedule_publications SET status = :status, {progress} "  # noqa: S608
            "WHERE publication_id = :pub"
        ),
        {
            "status": status,
            "pub": publication,
            "digest": DIGEST,
            "run": "sprun_" + suffix,
            "data_date": date(2026, 5, 4) + timedelta(weeks=ordinal),
        },
    )


def count_rows(engine: Engine, table: str, principal: str | None = None) -> int:
    sql = f"SELECT count(*) FROM knowledge.{table}"  # noqa: S608 - a fixed table name
    params: dict[str, object] = {}
    if principal is not None:
        sql += " WHERE principal_id = :p"
        params["p"] = principal
    with engine.connect() as connection:
        return int(connection.execute(text(sql), params).scalar_one())


def advisory_waiter_seen(engine: Engine) -> bool:
    """Some session of this catalog waits on an advisory lock (`granted = false`)."""
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND "
                    "NOT granted AND database = (SELECT oid FROM pg_database WHERE datname = "
                    "current_database()))"
                )
            ).scalar_one()
        )


@pytest.fixture(autouse=True)
def disposed_lease_engines() -> Iterator[None]:
    """RR2-F02: no cached lease engine outlives the per-test scratch catalog."""
    yield
    dispose_lease_engines()


@dataclass
class Interleaving:
    """Two writers forced through one interleaving at a named seam (R9-F03).

    The first writer stops at `stage`; the second is started and the first is
    released only once the second either reached the same seam (no lock held
    it back) or is observed waiting on an advisory lock in `pg_locks`. Both
    interleavings are therefore forced; nothing is decided by a sleep.
    """

    engine: Engine
    stage: str
    first_at_seam: threading.Event
    second_at_seam: threading.Event
    release: threading.Event
    first_thread: threading.Thread | None = None

    @classmethod
    def install(cls, monkeypatch: pytest.MonkeyPatch, engine: Engine, stage: str) -> Interleaving:
        race = cls(engine, stage, threading.Event(), threading.Event(), threading.Event())
        monkeypatch.setattr(plane_module, "_seam", race._seam)
        return race

    def _seam(self, stage: str) -> None:
        if stage != self.stage:
            return
        if threading.current_thread() is self.first_thread:
            self.first_at_seam.set()
            assert self.release.wait(60), "the first writer was never released"
        else:
            self.second_at_seam.set()

    def run(
        self,
        first: Callable[[SqlAlchemyScenarioUnitOfWork], object],
        second: Callable[[SqlAlchemyScenarioUnitOfWork], object],
        *,
        second_started: Callable[[], None] | None = None,
    ) -> tuple[tuple[str, object], tuple[str, object]]:
        outcomes: dict[str, tuple[str, object]] = {}

        def worker(name: str, action: Callable[[SqlAlchemyScenarioUnitOfWork], object]) -> None:
            try:
                with SqlAlchemyScenarioUnitOfWork(self.engine) as uow:
                    outcomes[name] = ("ok", action(uow))
            except BaseException as error:
                outcomes[name] = ("error", error)
            finally:
                if name == "first":
                    self.first_at_seam.set()

        self.first_thread = threading.Thread(target=worker, args=("first", first))
        self.first_thread.start()
        assert self.first_at_seam.wait(60), "the first writer never reached the seam"
        if second_started is not None:
            second_started()
        second_thread = threading.Thread(target=worker, args=("second", second))
        second_thread.start()
        waiting = threading.Event()
        for _ in range(6000):
            if self.second_at_seam.is_set() or advisory_waiter_seen(self.engine):
                break
            if not second_thread.is_alive():
                break
            waiting.wait(0.01)
        else:
            raise AssertionError("the second writer neither waited nor reached the seam")
        self.release.set()
        self.first_thread.join(60)
        second_thread.join(60)
        return outcomes["first"], outcomes["second"]
