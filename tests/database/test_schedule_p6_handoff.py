"""P6 XER S7-4b: the P6 delta and the P6 scenario hand-off, end to end (D5, D6).

Schedule XER import contract (`docs/architecture/schedule-xer-import-contract.md`)
sections 11.3-11.7 and the S7-4 acceptance D5 and D6. Every request goes
through `ApplicationService.invoke`, composed as `bootstrap/gateway.py`
composes it (the Schedule plane, the P6 switch and unit of work, the Scenario
plane and its CPM runner); each export is admitted from a real files workspace
under `tmp_path` and parsed by the real `schedule` worker in the contained
child. The pure rules are proven row by row in `tests/unit/test_schedule_p6_compare.py`
and `tests/unit/test_scenario_p6_snapshot.py`; this module proves the reads,
the routing, the partition, the cursor, the persistence and the report.

`database` tier (`database_clone`). Every export is synthetic
(`tests/fixtures/schedule_p6_xer.py`).
"""

from __future__ import annotations

import functools
import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text

from my_pa.application import schedule_p6_snapshot
from my_pa.application.commands import (
    ApproveScheduleBaseline,
    Command,
    CompareScheduleBaseline,
    CreateScheduleCpmRun,
    CreateScheduleScenario,
    CreateScheduleScenarioVersion,
    ImportScheduleP6Publication,
    ListScheduleChanges,
    ListScheduleP6FieldValues,
    ListScheduleScenarioActivities,
    ListScheduleScenarioRelationships,
    ProposeScheduleBaseline,
    ReadScheduleActivityHistory,
    ReadScheduleCpmRun,
    ReadScheduleScenarioVersion,
    SetScheduleP6CapturedFields,
)
from my_pa.application.file_workspace import FileWorkspaceApplication
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import ScenarioRecordBuilders, UnitOfWork
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import permitted_purposes
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.schedule.p6_import import P6AdmissionLimits
from my_pa.domain.schedule.scenario.canonical import (
    CONTENT_SCHEMA,
    CONTENT_SCHEMA_V3,
    content_schema,
    content_sha256,
)
from my_pa.domain.schedule.scenario.cpm import run_cpm
from my_pa.domain.schedule.scenario.p6_snapshot import snapshot_from_p6
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.file_workspace.store import FilesystemFileWorkspaceStore
from my_pa.infrastructure.jobs.schedule import process_schedule_publication
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.jobs import SCHEDULE_JOBS, claim_job
from my_pa.infrastructure.persistence.schedule import SqlAlchemyScheduleUnitOfWork
from my_pa.infrastructure.persistence.schedule_cpm_lease import (
    compute_and_store_cpm_run,
    dispose_lease_engines,
)
from my_pa.infrastructure.persistence.schedule_p6 import (
    SqlAlchemyScheduleP6UnitOfWork,
    SqlScheduleP6Repository,
)
from my_pa.infrastructure.persistence.schedule_scenarios import (
    SqlAlchemyScenarioUnitOfWork,
    new_scenario_output,
    new_scenario_version,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.schedule_capability_harness import LIMITS
from tests.fixtures import schedule_p6_xer as xer

pytestmark = pytest.mark.database

P: Final = "prn_sp6hand0001"
Q: Final = "prn_sp6hand0002"
PROJECT: Final = "prj_sp6hand0001"
OTHER_PROJECT: Final = "prj_sp6hand0002"
FOREIGN_PROJECT: Final = "prj_sp6hand0003"
WORKSPACE: Final = "syn"
OWNER: Final = "p6-handoff-worker"
P6_DELTA: Final = "cpm-workbench-p6-delta-v1"
EST_WT: Final = "xer:TASK.est_wt"
_KEYS: list[int] = [0]
#: The tables a delta must never write (it is never stored).
_STATE_TABLES: Final = (
    "schedule_series",
    "schedule_publications",
    "schedule_activities",
    "schedule_p6_capture_events",
    "schedule_p6_activities",
    "schedule_p6_field_values",
    "schedule_scenarios",
    "schedule_scenario_versions",
)


def _key(tag: str) -> str:
    _KEYS[0] += 1
    return f"p6hand-{tag}-{_KEYS[0]:06d}"


def _project(engine: Engine, principal: str, project: str) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO knowledge.projects (project_id, principal_id, name, opened_at, "
                "created_at, updated_at) VALUES (:j, :p, 'Synthetic Project', now(), now(), "
                "now())"
            ),
            {"j": project, "p": principal},
        )


class World:
    """`ApplicationService` with the Schedule, P6 and Scenario planes (the gateway's shape)."""

    def __init__(self, engine: Engine, root: Path) -> None:
        self.engine = engine
        self.root = root
        self.store = FilesystemFileWorkspaceStore(root)
        audit = SqlAlchemyAuditSink(engine)

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(engine, audit=audit, schedule_enabled=True)

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            schedule_enabled=True,
            schedule_unit_of_work=lambda: SqlAlchemyScheduleUnitOfWork(engine),
            schedule_p6_enabled=True,
            schedule_p6_unit_of_work=lambda: SqlAlchemyScheduleP6UnitOfWork(engine),
            schedule_p6_limits=P6AdmissionLimits(
                snapshot_quota_bytes=8 * 1024**3, imports_per_hour=60, imports_per_day=500
            ),
            file_workspace=FileWorkspaceApplication(store=self.store, workspace_id=WORKSPACE),
            schedule_scenarios_enabled=True,
            scenario_unit_of_work=lambda: SqlAlchemyScenarioUnitOfWork(engine),
            scenario_cpm_runner=functools.partial(
                compute_and_store_cpm_run, engine, compute=run_cpm
            ),
            scenario_record_builders=ScenarioRecordBuilders(
                new_version=new_scenario_version, new_output=new_scenario_output
            ),
        )

    def invoke(
        self,
        command: Command,
        *,
        principal_id: str = P,
        surface: OperatorSurface | None = None,
    ) -> ResponseEnvelope:
        capability = command.capability
        return self.service.invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=capability,
                purpose=sorted(permitted_purposes(capability))[0],
                principal_id=principal_id,
                requested_at=datetime.now(UTC),
            ),
            command,
            principal=Principal(
                principal_id=principal_id, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
            transport=CaptureTransport.LOCAL,
            operator_surface=surface,
        )

    def ok(self, command: Command, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        envelope = self.invoke(command, **kwargs)
        assert envelope.error is None, (command.capability.value, envelope.error)
        dumped = envelope.to_canonical_dict()
        result = dumped["result"]
        assert isinstance(result, dict)
        return {**result, "__disclosure__": dumped["disclosure"]}

    def refused(self, command: Command, **kwargs: Any) -> tuple[str, list[str]]:  # noqa: ANN401
        envelope = self.invoke(command, **kwargs)
        assert envelope.error is not None, command.capability.value
        error = envelope.to_canonical_dict()["error"]
        assert isinstance(error, dict)
        return str(error["code"]), list(error.get("safe_details") or [])

    def publish(
        self,
        model: xer.Model,
        path: str,
        *,
        project: str = PROJECT,
        series: str = "Master Schedule",
        principal: str = P,
    ) -> dict[str, Any]:
        data = xer.encode(xer.layout(model).lines)
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        admitted = self.ok(
            ImportScheduleP6Publication(
                project_id=project,
                series_name=series,
                workspace_id=WORKSPACE,
                path=path,
                expected_version=self.store.stat(path).version,
                expected_sha256=hashlib.sha256(data).hexdigest(),
                format="p6_xer",
                idempotency_key=_key("import"),
            ),
            principal_id=principal,
        )
        with self.engine.begin() as c:
            job = claim_job(
                c, owner=OWNER, lease_seconds=300, principal_id=principal, plane=SCHEDULE_JOBS
            )
        assert job is not None
        process_schedule_publication(self.engine, job, OWNER, p6_enabled=True)
        return admitted

    def counts(self) -> dict[str, int]:
        with self.engine.connect() as c:
            return {
                table: int(
                    c.execute(text(f"SELECT count(*) FROM knowledge.{table}")).scalar_one()  # noqa: S608
                )
                for table in _STATE_TABLES
            }

    def changes(self, first: str, second: str, **extra: Any) -> dict[str, Any]:  # noqa: ANN401
        return self.ok(
            ListScheduleChanges(from_publication_id=first, to_publication_id=second, **extra)
        )

    def scenario(
        self, publication: str, p6: dict[str, Any] | None = None, **extra: object
    ) -> dict[str, Any]:
        return self.ok(self.create(publication, p6, **extra))

    @staticmethod
    def create(
        publication: str, p6: dict[str, Any] | None = None, **extra: object
    ) -> CreateScheduleScenario:
        fields: dict[str, Any] = {
            "name": "Synthetic P6 Scenario",
            "label": "what_if",
            "idempotency_key": _key("scenario"),
            "from_publication_id": publication,
            "p6": {} if p6 is None else p6,
        }
        fields.update(extra)
        return CreateScheduleScenario(**fields)


@pytest.fixture
def w(db_engine: Engine, tmp_path: Path) -> Iterator[World]:
    _project(db_engine, P, PROJECT)
    _project(db_engine, P, OTHER_PROJECT)
    _project(db_engine, Q, FOREIGN_PROJECT)
    root = tmp_path / "workspace"
    root.mkdir()
    try:
        yield World(db_engine, root)
    finally:
        dispose_lease_engines()


def _std() -> xer.Model:
    return xer.base_model("standard")


def _task(model: xer.Model, code: str) -> dict[str, str]:
    (row,) = [row for row in model.table("TASK").rows if row["task_code"] == code]
    return row


def _all_changes(w: World, first: str, second: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page = w.changes(first, second, page_size=100, cursor=cursor)
        found.extend(page["changes"])
        cursor = page["__disclosure__"]["truncation"]["next_cursor"]
        if cursor is None:
            return found


# ---- D5: the P6 delta ---------------------------------------------------------------------


def _edited() -> xer.Model:
    """The standard export, one week on, with one edit per change kind."""
    model = _std()
    model.table("PROJECT").rows[0].update(last_recalc_date="2030-01-14 08:00")
    one = _task(model, "SYN-1010")
    one.update(
        task_name="Synthetic Task One Renamed",
        wbs_id="2004",
        status_code="TK_Active",
        act_start_date="2030-01-07 08:00",
        remain_drtn_hr_cnt="24",
        early_end_date="2030-01-14 17:00",
        total_float_hr_cnt="-8",
        cstr_type="CS_MSOA",
        cstr_date="2030-01-07 08:00",
        phys_complete_pct="40",
        clndr_id="500",
    )
    _task(model, "SYN-1020").update(task_type="TT_Mile", remain_drtn_hr_cnt="0")
    rows = model.table("TASK").rows
    # SYN-1030 renumbered to SYN-1031 (same GUID); SYN-1040 added.
    finish = _task(model, "SYN-1030")
    finish.update(task_code="SYN-1031")
    rows.append(
        xer.task_row(
            "3009",
            "SYN-1040",
            "Synthetic Added",
            "TT_Task",
            "2004",
            "8",
            "2030-01-16 08:00",
            "2030-01-16 17:00",
        )
    )
    preds = model.table("TASKPRED").rows
    preds[1].update(pred_type="PR_SS", lag_hr_cnt="4")
    preds.append(xer.pred_row("4009", "3004", "3009"))
    # The project calendar gains an exception and changes its week.
    calendar = model.table("CALENDAR").rows[1]
    calendar["clndr_data"] = xer.calendar_blob(
        dict.fromkeys(range(2, 7), (("07:00", "15:00"),)),
        (*xer.BASE_EXCEPTIONS, (date(2030, 2, 18), ())),
    )
    return model


def test_the_p6_delta_reports_every_kind_between_two_publications(w: World) -> None:
    first = str(w.publish(_std(), "exports/v1.xer")["publication_id"])
    second = str(w.publish(_edited(), "exports/v2.xer")["publication_id"])
    before = w.counts()
    page = w.changes(first, second, page_size=100)
    assert w.counts() == before  # computed on demand, never stored
    assert page["algorithm_version"] == P6_DELTA
    assert page["source_format"] == "p6_xer"
    assert page["__disclosure__"]["trust"]["basis"] == [
        "p6_xer_v1",
        "p6-field-catalogue-v1",
        P6_DELTA,
    ]
    changes = _all_changes(w, first, second)
    found = {(c["change_kind"], c["field"]) for c in changes}
    for expected in (
        ("data_date_changed", "data_date"),
        ("calendar_week_changed", "week"),
        ("calendar_exceptions_changed", "exceptions"),
        ("added", None),
        ("removed", None),
        ("renumber_candidate", None),
        ("renamed", "name"),
        ("wbs_moved", "wbs_path"),
        ("type_changed", "task_type"),
        ("status_changed", "status"),
        ("duration_changed", "remaining_hours"),
        ("dates_changed", "early_finish"),
        ("dates_changed", "actual_start"),
        ("float_changed", "total_float_hours"),
        ("constraint_changed", "constraint"),
        ("calendar_changed", "calendar"),
        ("progress_changed", "physical_pct"),
        ("relationship_added", None),
        ("relationship_removed", None),
        ("relationship_changed", "type"),
        ("relationship_changed", "lag_hours"),
    ):
        assert expected in found, expected
    by = {(c["change_kind"], c["field"], c["subject"].get("activity_id")): c for c in changes}
    moved = by[("data_date_changed", "data_date", None)]
    assert moved["delta_minutes"] == 7 * 1440
    finish = by[("dates_changed", "early_finish", "SYN-1010")]
    assert (finish["before"], finish["after"], finish["delta_minutes"]) == (
        "2030-01-11T17:00",
        "2030-01-14T17:00",
        3 * 1440,
    )
    remaining = by[("duration_changed", "remaining_hours", "SYN-1010")]
    assert (remaining["before"], remaining["after"], remaining["delta"]) == ("40", "24", "-16")
    hint = by[("renumber_candidate", None, "SYN-1031")]
    assert hint["before"]["activity_id"] == "SYN-1030"
    assert hint["before"]["schedule_activity_id"] != hint["after"]["schedule_activity_id"]
    (exceptions,) = [c for c in changes if c["change_kind"] == "calendar_exceptions_changed"]
    assert exceptions["counts"] == {"dates_added": 1, "dates_removed": 0, "dates_changed": 0}
    assert page["counts_by_kind"]["renumber_candidate"] == 1
    assert sum(page["counts_by_kind"].values()) == len(changes)
    assert page["fields_not_comparable"] == 0
    # The filter names a kind of this Series' algorithm only.
    only = w.changes(first, second, change_kind="renamed")
    assert [c["change_kind"] for c in only["changes"]] == ["renamed"]
    assert w.refused(
        ListScheduleChanges(
            from_publication_id=first, to_publication_id=second, change_kind="row_type_changed"
        )
    ) == ("invalid_request", ["change_kind"])


def test_a_re_export_reports_the_header_only(w: World) -> None:
    first = str(w.publish(_std(), "exports/v1.xer")["publication_id"])
    model = _std()
    model.header[1] = "26.5" if model.header[1] != "26.5" else "26.4"
    second = str(w.publish(model, "exports/v1-again.xer")["publication_id"])
    changes = _all_changes(w, first, second)
    assert {c["scope"] for c in changes} <= {"project"}
    assert [c["field"] for c in changes] == ["export_version"]


def test_the_p6_cursor_names_its_algorithm_and_continues_only_its_request(w: World) -> None:
    first = str(w.publish(_std(), "exports/v1.xer")["publication_id"])
    second = str(w.publish(_edited(), "exports/v2.xer")["publication_id"])
    page = w.changes(first, second, page_size=2)
    cursor = page["__disclosure__"]["truncation"]["next_cursor"]
    assert cursor is not None
    nxt = w.changes(first, second, page_size=2, cursor=cursor)
    assert nxt["changes"] != page["changes"]
    assert nxt["algorithm_version"] == P6_DELTA
    assert w.refused(
        ListScheduleChanges(
            from_publication_id=first, to_publication_id=second, page_size=3, cursor=cursor
        )
    ) == ("conflict", ["cursor"])


def test_the_delta_of_another_principals_publications_is_not_found(w: World) -> None:
    first = str(w.publish(_std(), "exports/v1.xer")["publication_id"])
    second = str(w.publish(_edited(), "exports/v2.xer")["publication_id"])
    assert w.refused(
        ListScheduleChanges(from_publication_id=first, to_publication_id=second), principal_id=Q
    ) == ("not_found", ["from_publication_id"])
    # One foreign end is not found too, never compared.
    foreign = str(
        w.publish(_std(), "exports/q.xer", project=FOREIGN_PROJECT, principal=Q)["publication_id"]
    )
    assert w.refused(ListScheduleChanges(from_publication_id=first, to_publication_id=foreign)) == (
        "not_found",
        ["to_publication_id"],
    )
    # Two Series of one Principal are never one delta.
    other = str(w.publish(_std(), "exports/o.xer", series="Other Series")["publication_id"])
    assert w.refused(ListScheduleChanges(from_publication_id=first, to_publication_id=other)) == (
        "invalid_request",
        ["to_publication_id"],
    )


def test_n_versions_history_reintroduced_and_fields_not_comparable(w: World) -> None:
    one = w.publish(xer.base_model("full"), "exports/v1.xer")
    series = str(one["series_id"])
    first = str(one["publication_id"])
    without = xer.base_model("full")
    without.table("TASK").rows[:] = [
        row for row in without.table("TASK").rows if row["task_code"] != "SYN-1020"
    ]
    without.table("TASKPRED").rows[:] = [xer.pred_row("4001", "3001", "3002")]
    second = str(w.publish(without, "exports/v2.xer")["publication_id"])
    # Capture `est_wt` from the third import on (the selection applies to the next import).
    w.ok(
        SetScheduleP6CapturedFields(
            series_id=series,
            field_keys=(EST_WT,),
            expected_sequence=0,
            idempotency_key=_key("select"),
        )
    )
    third_model = xer.base_model("full")
    _task(third_model, "SYN-1010")["est_wt"] = "2.5"
    third = str(w.publish(third_model, "exports/v3.xer")["publication_id"])
    fourth_model = xer.base_model("full")
    _task(fourth_model, "SYN-1010")["est_wt"] = "3"
    fourth = str(w.publish(fourth_model, "exports/v4.xer")["publication_id"])

    back = w.changes(second, third, page_size=100)
    kinds = {(c["change_kind"], c["subject"].get("activity_id")) for c in back["changes"]}
    assert ("reintroduced", "SYN-1020") in kinds
    # The default set and the explicit one differ: counted, never a change.
    assert back["fields_not_comparable"] > 0
    assert not [c for c in back["changes"] if c["change_kind"] == "field_changed"]
    later = w.changes(third, fourth, page_size=100)
    (field,) = [c for c in later["changes"] if c["change_kind"] == "field_changed"]
    assert (field["field"], field["before"], field["after"]) == (EST_WT, "2.5", "3")
    assert later["fields_not_comparable"] == 0
    # N versions: the history of one Stable Activity across all four, and its
    # captured-field history.
    activity = field["subject"]["schedule_activity_id"]
    history = w.ok(ReadScheduleActivityHistory(schedule_activity_id=activity))
    assert [o["publication_id"] for o in history["observations"]] == [
        first,
        second,
        third,
        fourth,
    ]
    values = w.ok(ListScheduleP6FieldValues(schedule_activity_id=activity, fields=(EST_WT,)))
    assert {(v["publication_id"], v["value"]) for v in values["values"]} == {
        (third, "2.5"),
        (fourth, "3"),
    }


# ---- D6: the P6 scenario hand-off --------------------------------------------------------


def test_a_p6_snapshot_maps_the_export_and_reports_every_count(w: World) -> None:
    publication = str(w.publish(_std(), "exports/std.xer")["publication_id"])
    created = w.scenario(publication)
    assert created["snapshot_report"] == {
        "activities": 4,
        "milestones": 2,
        "durations_quantized": 0,
        "durations_out_of_range": 0,
        "original_missing": 0,
        "remaining_missing": 0,
    }
    report = created["p6_snapshot_report"]
    counts = report["counts"]
    assert (counts["start_milestones"], counts["finish_milestones"], counts["tasks"]) == (1, 1, 2)
    assert counts["calendars"] == 1
    # The standard export has no SCHEDOPTIONS: neither progress flag, so the
    # policy is retained logic, counted (section 11.5).
    assert counts["progress_policy_defaulted"] == 1
    assert counts["default_calendar_standard"] == 0
    assert report["standard_calendar_horizon_exceeded"] == []
    version = str(created["version_id"])
    activities = w.ok(ListScheduleScenarioActivities(version_id=version, page_size=100))
    kinds = {
        a["published_reference"]["published_activity_id"]: a["kind"]
        for a in activities["activities"]
    }
    assert kinds == {
        "SYN-1000": "start_milestone",
        "SYN-1010": "task",
        "SYN-1020": "task",
        "SYN-1030": "finish_milestone",
    }
    minutes = {
        a["published_reference"]["published_activity_id"]: (
            a["calendar"],
            a["original_minutes"],
            a["remaining_minutes"],
        )
        for a in activities["activities"]
    }
    assert minutes["SYN-1010"] == ("p6-501", 40 * 60, 40 * 60)
    assert minutes["SYN-1000"] == ("p6-501", 0, 0)
    assert all(a["published_reference"]["fields"] is None for a in activities["activities"])
    relationships = w.ok(ListScheduleScenarioRelationships(version_id=version, page_size=100))
    assert len(relationships["relationships"]) == 3
    # Edged milestones: a v2 content, run on my-pa-cpm-v2.
    run = w.ok(CreateScheduleCpmRun(version_id=version, idempotency_key=_key("run")))
    assert run["engine_version"] == "my-pa-cpm-v2"
    assert run["status"] == "computed"
    read = w.ok(ReadScheduleCpmRun(cpm_run_id=str(run["cpm_run_id"])))
    assert read["standard_calendar_horizon_exceeded"] == []


def test_a_task_only_snapshot_is_a_v1_content_and_runs_on_v1(w: World) -> None:
    model = _std()
    for code in ("SYN-1000", "SYN-1030"):
        _task(model, code).update(
            task_type="TT_Task", remain_drtn_hr_cnt="8", target_drtn_hr_cnt="8"
        )
    publication = str(w.publish(model, "exports/tasks.xer")["publication_id"])
    created = w.scenario(publication)
    run = w.ok(
        CreateScheduleCpmRun(version_id=str(created["version_id"]), idempotency_key=_key("run"))
    )
    assert run["engine_version"] == "my-pa-cpm-v1"
    assert created["p6_snapshot_report"]["counts"]["start_milestones"] == 0


def _tasks_only(model: xer.Model) -> xer.Model:
    for code in ("SYN-1000", "SYN-1030"):
        _task(model, code).update(
            task_type="TT_Task", remain_drtn_hr_cnt="8", target_drtn_hr_cnt="8"
        )
    return model


def test_parallel_relationships_persist_run_and_change_as_a_v3_content(w: World) -> None:
    # S7-7: an FF beside the FS between SYN-1010 and SYN-1020 is kept (content v3, run
    # on my-pa-cpm-v1); the stored content round-trips under its v3 digest, the reads
    # list both relationships, and a change set names one of them by type.
    model = _tasks_only(_std())
    model.table("TASKPRED").rows.append(xer.pred_row("4004", "3002", "3003", "PR_FF", "8"))
    publication = str(w.publish(model, "exports/ladder.xer")["publication_id"])
    command = w.create(publication)
    created = w.ok(command)
    replayed = w.ok(command)
    assert replayed["replayed"] is True
    assert replayed["p6_snapshot_report"] == created["p6_snapshot_report"]
    assert replayed["version_id"] == created["version_id"]
    counts = created["p6_snapshot_report"]["counts"]
    assert counts["relationships"] == 4
    assert counts["relationships_parallel_dropped"] == 0
    assert "parallel_relationships" not in created["p6_snapshot_report"]["unmodelled_settings"]
    version = str(created["version_id"])
    assert created["relationship_count"] == 4
    with SqlAlchemyScenarioUnitOfWork(w.engine) as work:
        loaded = work.scenarios.load_content(P, version)
    assert loaded is not None
    assert content_schema(loaded.content) == CONTENT_SCHEMA_V3
    assert content_sha256(loaded.content) == created["content_sha256"]
    keys = {
        a.published_reference.published_activity_id: a.key
        for a in loaded.content.activities
        if a.published_reference is not None
    }
    ladder = (keys["SYN-1010"], keys["SYN-1020"])
    listed = w.ok(ListScheduleScenarioRelationships(version_id=version, page_size=100))
    pair = [
        (row["type"], row["lag_minutes"])
        for row in listed["relationships"]
        if (row["pred"], row["succ"]) == ladder
    ]
    assert pair == [("FF", 480), ("FS", 0)]
    run = w.ok(CreateScheduleCpmRun(version_id=version, idempotency_key=_key("run")))
    assert run["engine_version"] == "my-pa-cpm-v1"
    assert run["status"] == "computed"
    assert (
        w.ok(ReadScheduleCpmRun(cpm_run_id=str(run["cpm_run_id"])))["summary"]["relationship_count"]
        == 4
    )
    remove: dict[str, Any] = {"op": "relationship.remove", "pred": ladder[0], "succ": ladder[1]}
    scenario = str(created["scenario_id"])
    ambiguous = CreateScheduleScenarioVersion(
        scenario_id=scenario,
        expected_head_version_no=1,
        label="update",
        change_set=[remove],
        idempotency_key=_key("append"),
    )
    assert w.refused(ambiguous) == ("invalid_request", ["change_set_invalid_field"])
    appended = w.ok(
        CreateScheduleScenarioVersion(
            scenario_id=scenario,
            expected_head_version_no=1,
            label="update",
            change_set=[{**remove, "type": "FF"}],
            idempotency_key=_key("append"),
        )
    )
    assert appended["relationship_count"] == 3
    with SqlAlchemyScenarioUnitOfWork(w.engine) as work:
        child = work.scenarios.load_content(P, str(appended["version_id"]))
    assert child is not None
    assert content_schema(child.content) == CONTENT_SCHEMA
    rerun = w.ok(
        CreateScheduleCpmRun(version_id=str(appended["version_id"]), idempotency_key=_key("run"))
    )
    assert rerun["engine_version"] == "my-pa-cpm-v1"


@pytest.mark.parametrize("lag", ["8", "17521"])
def test_a_pre_s77_p6_snapshot_replays_its_original_report(
    w: World, monkeypatch: pytest.MonkeyPatch, lag: str
) -> None:
    model = _tasks_only(_std())
    model.table("TASKPRED").rows.append(xer.pred_row("4004", "3002", "3003", "PR_FF", lag))
    publication = str(w.publish(model, "exports/legacy-ladder.xer")["publication_id"])
    command = w.create(publication)
    # Seed a first version and reservation using the pre-S7-7 relationship mapper.
    with monkeypatch.context() as legacy:
        legacy.setattr(
            schedule_p6_snapshot,
            "snapshot_from_p6",
            functools.partial(snapshot_from_p6, legacy_relationships=True),
        )
        created = w.ok(command)
    assert created["relationship_count"] == 3
    counts = created["p6_snapshot_report"]["counts"]
    assert counts["relationships"] == 3
    assert counts["relationships_parallel_dropped"] == 1
    replayed = w.ok(command)
    assert replayed["replayed"] is True
    assert replayed["version_id"] == created["version_id"]
    assert replayed["content_sha256"] == created["content_sha256"]
    assert replayed["p6_snapshot_report"] == created["p6_snapshot_report"]


def test_rcal_project_is_a_fixed_lag_calendar_and_a_replay_reports_the_same(w: World) -> None:
    model = xer.base_model("full")
    model.table("SCHEDOPTIONS").rows[0].update(
        sched_calendar_on_relationship_lag="rcal_Project",
        sched_retained_logic="N",
        sched_progress_override="N",
        sched_lag_early_start_flag="Y",
    )
    for code in ("SYN-1000", "SYN-1030"):
        _task(model, code).update(
            task_type="TT_Task", remain_drtn_hr_cnt="8", target_drtn_hr_cnt="8"
        )
    publication = str(w.publish(model, "exports/rcal.xer")["publication_id"])
    command = w.create(publication)
    created = w.ok(command)
    version = w.ok(ReadScheduleScenarioVersion(version_id=str(created["version_id"])))
    assert created["content_sha256"] in str(version)
    run = w.ok(
        CreateScheduleCpmRun(version_id=str(created["version_id"]), idempotency_key=_key("run"))
    )
    assert run["engine_version"] == "my-pa-cpm-v2"  # the fixed lag calendar alone makes it v2
    report = created["p6_snapshot_report"]
    assert report["counts"]["progress_policy_defaulted"] == 1
    assert report["counts"]["lag_calendar_standard"] == 0
    assert report["unmodelled_settings"] == ["ss_lag_from_early_start"]
    replay = w.ok(command)
    assert replay["replayed"] is True
    assert replay["p6_snapshot_report"] == report
    assert replay["version_id"] == created["version_id"]


def test_a_calendar_of_another_p6_publication_of_the_same_project(w: World) -> None:
    base = str(w.publish(_std(), "exports/base.xer")["publication_id"])
    donor_model = _std()
    donor_model.table("CALENDAR").rows[1]["clndr_data"] = xer.calendar_blob(
        dict.fromkeys(range(2, 7), (("06:00", "14:00"),))
    )
    donor_model.table("CALENDAR").rows.append(
        {
            **donor_model.table("CALENDAR").rows[0],
            "clndr_id": "777",
            "clndr_name": "Synthetic Night Calendar",
            "default_flag": "N",
            "clndr_data": xer.calendar_blob(dict.fromkeys(range(2, 7), (("20:00", "23:00"),))),
        }
    )
    donor = str(
        w.publish(donor_model, "exports/donor.xer", series="Donor Series")["publication_id"]
    )
    created = w.scenario(
        base,
        {
            "calendars": [
                {"publication_id": donor, "calendar_id": 501},
                {"publication_id": donor, "calendar_id": 777},
            ],
            "calendar_map": {"p6-501": "p6-777"},
            "default_calendar": "my-pa-us-40h-v1",
        },
    )
    version = str(created["version_id"])
    activities = w.ok(ListScheduleScenarioActivities(version_id=version, page_size=100))
    assert {a["calendar"] for a in activities["activities"]} == {"p6-777"}
    assert created["calendar_count"] == 3  # p6-501 (substituted), p6-777, standard
    # Another Project's calendar, or a foreign one, is refused alike.
    elsewhere = str(
        w.publish(_std(), "exports/elsewhere.xer", project=OTHER_PROJECT)["publication_id"]
    )
    foreign = str(
        w.publish(_std(), "exports/q.xer", project=FOREIGN_PROJECT, principal=Q)["publication_id"]
    )
    for reference in (
        {"publication_id": elsewhere, "calendar_id": 501},
        {"publication_id": foreign, "calendar_id": 501},
        {"publication_id": donor, "calendar_id": 999},
    ):
        assert w.refused(w.create(base, {"calendars": [reference]})) == (
            "invalid_request",
            ["calendar"],
        )


def test_included_fields_travel_inert_and_numbers_as_text(w: World) -> None:
    first = w.publish(xer.base_model("full"), "exports/v1.xer")
    w.ok(
        SetScheduleP6CapturedFields(
            series_id=str(first["series_id"]),
            field_keys=(EST_WT,),
            expected_sequence=0,
            idempotency_key=_key("select"),
        )
    )
    model = xer.base_model("full")
    _task(model, "SYN-1010")["est_wt"] = "2.5"
    _task(model, "SYN-1020")["est_wt"] = "4"
    publication = str(w.publish(model, "exports/v2.xer")["publication_id"])
    created = w.scenario(publication, {"include_fields": [EST_WT]})
    activities = w.ok(
        ListScheduleScenarioActivities(version_id=str(created["version_id"]), page_size=100)
    )["activities"]
    fields = {
        a["published_reference"]["published_activity_id"]: a["published_reference"]["fields"]
        for a in activities
    }
    assert fields["SYN-1010"] == {EST_WT: "2.5"}
    assert fields["SYN-1020"] == {EST_WT: 4}
    # Not captured by the origin, or never a field key: refused.
    for keys in (["xer:TASK.rev_fdbk_flag"], ["xer:TASK.create_user"]):
        assert w.refused(w.create(publication, {"include_fields": keys})) == (
            "invalid_request",
            ["field_key"],
        )


def test_the_origin_formats_options_are_required(w: World) -> None:
    publication = str(w.publish(_std(), "exports/v1.xer")["publication_id"])
    pdf_shaped = CreateScheduleScenario(
        name="Synthetic",
        label="what_if",
        idempotency_key=_key("s"),
        from_publication_id=publication,
        minutes_per_source_unit=60,
    )
    assert w.refused(pdf_shaped) == ("invalid_request", ["source_format"])
    assert w.refused(w.create(publication), principal_id=Q) == (
        "not_found",
        ["from_publication_id"],
    )
    assert w.refused(w.create(publication, {"default_calendar": "p6-999"})) == (
        "invalid_request",
        ["calendar"],
    )


def test_a_complete_activity_after_the_data_date_is_refused(w: World) -> None:
    model = _std()
    _task(model, "SYN-1010").update(
        status_code="TK_Complete",
        act_start_date="2030-01-07 08:00",
        act_end_date="2030-01-11 17:00",
        remain_drtn_hr_cnt="0",
    )
    publication = str(w.publish(model, "exports/late.xer")["publication_id"])
    assert w.refused(w.create(publication)) == ("conflict", ["from_publication_id"])
    model.table("PROJECT").rows[0]["last_recalc_date"] = "2030-01-14 08:00"
    later = str(w.publish(model, "exports/ok.xer")["publication_id"])
    created = w.scenario(later)
    assert created["p6_snapshot_report"]["counts"]["activities"] == 4


def test_an_approved_baseline_naming_a_p6_publication(w: World) -> None:
    """D6 from a baseline, and "latest vs governing baseline" as the P6 delta (11.4)."""
    publication = str(w.publish(_std(), "exports/v1.xer")["publication_id"])
    later = str(w.publish(_edited(), "exports/v2.xer")["publication_id"])
    proposal = w.ok(
        ProposeScheduleBaseline(
            publication_id=publication,
            type="contract",
            reason="Synthetic proposal",
            idempotency_key=_key("propose"),
        )
    )
    w.ok(
        ApproveScheduleBaseline(
            baseline_id=str(proposal["baseline_id"]),
            approval_reference="Synthetic NTP 0001",
            effective_from="2030-01-07",
            reason="Synthetic approval",
            idempotency_key=_key("approve"),
        ),
        surface=OperatorSurface.CLI,
    )
    created = w.ok(
        CreateScheduleScenario(
            name="Synthetic Baseline Scenario",
            label="what_if",
            idempotency_key=_key("scenario"),
            from_baseline_id=str(proposal["baseline_id"]),
            p6={},
        )
    )
    assert created["origin"]["publication_id"] == publication
    assert created["p6_snapshot_report"]["counts"]["activities"] == 4
    compared = w.ok(
        CompareScheduleBaseline(baseline_id=str(proposal["baseline_id"]), to_publication_id=later)
    )
    assert compared["algorithm_version"] == P6_DELTA
    assert compared["counts_by_kind"]["renumber_candidate"] == 1


# ---- independent review S7-4b: guards the worker's suite left unproven --------------------

CREATE_USER: Final = "xer:TASK.create_user"


def test_a_personal_field_is_never_compared_nor_carried_into_a_scenario(w: World) -> None:
    """10.4 / 11.4 / 11.5: a captured personal key is withheld by the delta and refused inert."""
    first = w.publish(xer.base_model("full"), "exports/v1.xer")
    w.ok(
        SetScheduleP6CapturedFields(
            series_id=str(first["series_id"]),
            field_keys=(CREATE_USER, EST_WT),
            include_personal=True,
            expected_sequence=0,
            idempotency_key=_key("personal"),
        )
    )
    second_model = xer.base_model("full")
    _task(second_model, "SYN-1010")["est_wt"] = "2.5"
    second = str(w.publish(second_model, "exports/v2.xer")["publication_id"])
    third_model = xer.base_model("full")
    _task(third_model, "SYN-1010").update(est_wt="3", create_user="Synthetic Other Person")
    third = str(w.publish(third_model, "exports/v3.xer")["publication_id"])
    # The personal value really is captured and differs between the two.
    values = w.ok(ListScheduleP6FieldValues(publication_id=third, fields=(CREATE_USER,)))
    assert "Synthetic Other Person" in {v["value"] for v in values["values"]}
    page = w.changes(second, third, page_size=100)
    changed = [c for c in page["changes"] if c["change_kind"] == "field_changed"]
    assert [c["field"] for c in changed] == [EST_WT]
    assert page["fields_withheld"] == 1
    assert "Synthetic Other Person" not in str(page)
    assert w.refused(w.create(third, {"include_fields": [CREATE_USER]})) == (
        "invalid_request",
        ["field_key"],
    )
    assert w.scenario(third, {"include_fields": [EST_WT]})["p6_snapshot_report"]


def test_the_delta_reads_only_the_comparable_keys_values(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F1: no personal nor one-sided captured value is read; the key filter is in SQL."""
    admitted = w.publish(xer.base_model("full"), "exports/v1.xer")
    first = str(admitted["publication_id"])
    w.ok(
        SetScheduleP6CapturedFields(
            series_id=str(admitted["series_id"]),
            field_keys=(CREATE_USER, EST_WT),
            include_personal=True,
            expected_sequence=0,
            idempotency_key=_key("f1"),
        )
    )
    second_model = xer.base_model("full")
    _task(second_model, "SYN-1010").update(est_wt="2", create_user="Synthetic Person")
    second = str(w.publish(second_model, "exports/v2.xer")["publication_id"])
    third_model = xer.base_model("full")
    _task(third_model, "SYN-1010").update(est_wt="3", create_user="Synthetic Other Person")
    third = str(w.publish(third_model, "exports/v3.xer")["publication_id"])
    asked: list[tuple[str, tuple[str, ...] | None, frozenset[str]]] = []
    original = SqlScheduleP6Repository.p6_activity_field_values

    def recorded(
        self: SqlScheduleP6Repository,
        principal_id: str,
        parser_run_id: str,
        field_keys: Any,  # noqa: ANN401
    ) -> tuple[dict[str, object], ...]:
        rows = original(self, principal_id, parser_run_id, field_keys)
        keys = None if field_keys is None else tuple(field_keys)
        asked.append((parser_run_id, keys, frozenset(str(row["field_key"]) for row in rows)))
        return rows

    monkeypatch.setattr(SqlScheduleP6Repository, "p6_activity_field_values", recorded)
    # The defaults run against the selection: the default run stores values of
    # many keys the selection does not hold, and the personal key is on both.
    with w.engine.connect() as c:
        stored = dict(
            c.execute(
                text(
                    "SELECT p.publication_id, count(DISTINCT v.field_key) FROM "
                    "knowledge.schedule_p6_field_values v JOIN knowledge.schedule_publications p "
                    "ON p.accepted_parser_run_id = v.parser_run_id WHERE p.publication_id IN "
                    "(:a, :b, :c) AND v.entity_kind = 'activity' GROUP BY p.publication_id"
                ),
                {"a": first, "b": second, "c": third},
            ).all()
        )
    assert stored[first] > 2
    assert stored[second] == stored[third] == 2
    across = w.changes(first, third, page_size=100)
    assert across["fields_not_comparable"] > 0
    page = w.changes(second, third, page_size=100)
    assert page["fields_withheld"] == 1
    assert [c["field"] for c in page["changes"] if c["change_kind"] == "field_changed"] == [EST_WT]
    assert len(asked) == 4
    for _, keys, read in asked:
        assert keys is not None
        assert CREATE_USER not in keys
        assert set(keys) <= {EST_WT}
        # The filter is the statement's: no row of a key not asked for is read.
        assert read <= set(keys)
    assert [keys for _, keys, _ in asked[2:]] == [(EST_WT,), (EST_WT,)]


def test_a_calendar_of_a_review_required_publication_is_refused(w: World) -> None:
    """11.5: only a complete P6 publication of the same Project lends a calendar."""
    base = str(w.publish(_std(), "exports/base.xer")["publication_id"])
    renamed = _std()
    renamed.table("PROJECT").rows[0].update(
        proj_short_name="SYN-OTHER", guid=xer.guid("SynOtherProject")
    )
    held = w.publish(renamed, "exports/renamed.xer")
    held_id = str(held["publication_id"])
    with w.engine.connect() as c:
        status, run = c.execute(
            text(
                "SELECT status, accepted_parser_run_id FROM knowledge.schedule_publications "
                "WHERE publication_id = :p"
            ),
            {"p": held_id},
        ).one()
    assert status == "review_required"
    assert run is not None  # its calendars are stored: only the status check refuses it
    assert w.refused(
        w.create(base, {"calendars": [{"publication_id": held_id, "calendar_id": 501}]})
    ) == ("invalid_request", ["calendar"])


def test_the_standard_calendar_horizon_is_reported_by_the_snapshot_and_the_run(w: World) -> None:
    """11.6 surfaced (S7-4b): a must-finish-by past the materialized years is reported."""
    model = _std()
    model.table("PROJECT").rows[0]["plan_end_date"] = "2060-01-07 17:00"
    publication = str(w.publish(model, "exports/far.xer")["publication_id"])
    created = w.scenario(publication, {"default_calendar": "my-pa-us-40h-v1"})
    assert created["p6_snapshot_report"]["standard_calendar_horizon_exceeded"] == [
        "my-pa-us-40h-v1"
    ]
    run = w.ok(
        CreateScheduleCpmRun(version_id=str(created["version_id"]), idempotency_key=_key("run"))
    )
    read = w.ok(ReadScheduleCpmRun(cpm_run_id=str(run["cpm_run_id"])))
    assert read["standard_calendar_horizon_exceeded"] == ["my-pa-us-40h-v1"]


def test_retired_publication_and_scenario_reads_are_withheld(w: World) -> None:
    from sqlalchemy import select

    from my_pa.infrastructure.persistence.tables import (
        schedule_scenarios,
        smoke_fixture_retirements,
    )

    publication = w.publish(_tasks_only(_std()), "exports/retired.xer")
    imported = str(publication["publication_id"])
    created = w.ok(w.create(imported))
    scenario_id = str(created["scenario_id"])
    version_id = str(created["version_id"])
    relationships = ListScheduleScenarioRelationships(version_id=version_id)
    assert w.ok(relationships)["relationships"]
    markers = smoke_fixture_retirements
    with w.engine.begin() as connection:
        connection.execute(
            markers.insert(),
            [
                {"principal_id": P, "record_id": record_id, "plan_sha256": "a" * 64}
                for record_id in (imported, scenario_id, version_id)
            ],
        )
    assert w.refused(relationships)[0] == "not_found"
    with SqlAlchemyScenarioUnitOfWork(w.engine) as work:
        assert work.scenarios.get_scenario(P, scenario_id) is None
        assert work.scenarios.load_content(P, version_id) is None
    with w.engine.begin() as connection:
        assert (
            connection.execute(
                select(schedule_scenarios.c.scenario_id).where(
                    schedule_scenarios.c.principal_id == P,
                    schedule_scenarios.c.scenario_id == scenario_id,
                )
            ).scalar_one()
            == scenario_id
        )


def test_retirement_requires_exact_preview_and_preserves_fixture_rows(w: World) -> None:
    from dataclasses import replace

    from sqlalchemy import select

    from my_pa.bootstrap.communications_ingest import ingestion_lifecycle
    from my_pa.bootstrap.settings import load_settings
    from my_pa.contracts.ports import IngestConsumer
    from my_pa.infrastructure.persistence.smoke_fixture_retirement import (
        RetirementRefusalError,
        SmokeFixtureTarget,
        retire_smoke_fixtures,
    )
    from my_pa.infrastructure.persistence.tables import (
        communication_messages,
        projects,
        smoke_fixture_retirements,
    )
    from tests.fixtures.communications_evidence import synthetic as mail

    project_name = "Qzxsmokefixtureintegration"
    fixture_title = "Retirement test"
    prefix = "mypa-smoke-wp5-test"
    fixture_path = f"{prefix}/synthetic-title-match.json"
    w.store.mkdir(prefix)
    message = mail.message(1, subject=fixture_title)
    mailbox = "synthetic_wp5_integration"
    message.update(mailbox_ref=mailbox, dedup_key=mailbox + "|" + message["id"])
    document = mail.publication(
        [message], mail.window("2026-11-17T11:00:00Z", "2026-11-17T13:00:00Z", 2, "synthetic")
    )
    document["mailbox_ref"] = mailbox
    body = mail.encode(document)
    w.store.write_text(fixture_path, body.decode())
    settings = load_settings().model_copy(
        update={"files_workspaces": f"mcp={w.root};mode=direct", "files_workspace_root": ""}
    )
    ingestor = ingestion_lifecycle(settings, w.engine)
    source = ingestor.admit(
        P,
        consumer=IngestConsumer.COMMUNICATIONS_EVIDENCE_V2,
        workspace_id="mcp",
        path_prefix=prefix + "/",
        file_pattern="synthetic-title-match.json",
        enabled=False,
    )
    report = ingestor.backfill(P, source.ingest_source_id, paths=[fixture_path])
    assert report.counts["messages_created"] == 1

    p6_path = "exports/smoke-retirement.xer"
    publication = str(w.publish(_tasks_only(_std()), p6_path)["publication_id"])
    scenario = w.ok(replace(w.create(publication), name=project_name + " parallel relationships"))
    with w.engine.begin() as connection:
        connection.execute(
            projects.update()
            .where(projects.c.principal_id == P, projects.c.project_id == PROJECT)
            .values(
                name=project_name,
                description="Dedicated synthetic WP5 and P6 smoke fixture",
                state="closed",
                closed_at=datetime.now(UTC),
            )
        )
        msg = connection.execute(
            select(communication_messages.c.message_id).where(
                communication_messages.c.principal_id == P,
                communication_messages.c.mailbox_ref == mailbox,
            )
        ).scalar_one()
    target = SmokeFixtureTarget(
        msg,
        source.ingest_source_id,
        publication,
        str(scenario["scenario_id"]),
        hashlib.sha256(body).hexdigest(),
        hashlib.sha256((w.root / p6_path).read_bytes()).hexdigest(),
        None,
    )
    expected = ("disposable", "synthetic", "7f4d9ac28631")
    with w.engine.begin() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        preview = retire_smoke_fixtures(connection, P, expected, target)
        assert preview["retired"] == []
    markers = smoke_fixture_retirements
    with w.engine.begin() as connection:
        with pytest.raises(RetirementRefusalError, match="preview_digest_mismatch"):
            retire_smoke_fixtures(
                connection, P, expected, replace(target, apply_plan_sha256="1" * 64)
            )
        assert not connection.execute(
            select(markers.c.record_id).where(markers.c.principal_id == P)
        ).all()
        apply = replace(target, apply_plan_sha256=str(preview["plan_sha256"]))
        assert retire_smoke_fixtures(connection, P, expected, apply)["retired"] == preview["ids"]
        assert retire_smoke_fixtures(connection, P, expected, apply)["retired"] == preview["ids"]
    with SqlAlchemyScenarioUnitOfWork(w.engine) as work:
        assert work.scenarios.get_scenario(P, str(scenario["scenario_id"])) is None
