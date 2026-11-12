"""Schedule Scenarios S6-3 package I10-A: the 26 plane capabilities end to end.

Contract `docs/architecture/schedule-scenarios-contract.md` sections 15.3-15.10
and 15.16: every handler through `ApplicationService` composed as
`bootstrap/gateway.py` composes it (the plane unit of work, the CPM runner with
the work engine bound and the record builders), over a migrated database with
synthetic publications written by the real S5 import and worker. Writes, reads,
replays, the refusal mapping, the client budgets and quotas, the refusal bound,
operator-only, the operator proposal (S6-3-O01) and the switch.

The CPM compute (`compute`) and the 2 decode seams (`ScenarioWriteBuilders`)
are injected so a test can assert a seam was, or was never, reached. Budgets
are module constants of `application.schedule_scenarios`, lowered per test.
Every identity, name and value is synthetic.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import pytest

from my_pa.adapters.mcp.remote import remote_tool_names
from my_pa.adapters.remote_request import compose_remote_arguments
from my_pa.application import schedule_scenarios as plane_module
from my_pa.application.commands import (
    ApproveScheduleBaseline,
    CompareScheduleBaseline,
    CreateScheduleCpmRun,
    CreateScheduleScenario,
    CreateScheduleScenarioVersion,
    ImportSchedulePublication,
    ListScheduleBaselines,
    ListScheduleChanges,
    ListScheduleCpmRunActivities,
    ListSchedulePublications,
    ListScheduleScenarioActivities,
    ListScheduleScenarioChanges,
    ListScheduleScenarioOutputs,
    ListScheduleScenarioRelationships,
    ListScheduleScenarios,
    ListScheduleSeries,
    ListScheduleSeriesMatchDecisions,
    ProposeScheduleBaseline,
    ReadGoverningScheduleBaseline,
    ReadScheduleBaseline,
    ReadScheduleCpmRun,
    ReadSchedulePublication,
    ReadScheduleScenario,
    ReadScheduleScenarioOutput,
    ReadScheduleScenarioVersion,
    ReadScheduleSeriesCurrent,
    RecordScheduleScenarioOutput,
    RejectScheduleBaseline,
    RevokeScheduleBaseline,
    SetGoverningScheduleBaseline,
    WithdrawScheduleBaseline,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import ScenarioRecordBuilders, UnitOfWork
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.schedule import SchedulePublicationStatus
from my_pa.domain.schedule.scenario.cpm import CpmResult, run_cpm
from my_pa.domain.schedule.scenario.model import ScenarioContent
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.schedule import SqlAlchemyScheduleUnitOfWork
from my_pa.infrastructure.persistence.schedule_cpm_lease import (
    compute_and_store_cpm_run,
    dispose_lease_engines,
)
from my_pa.infrastructure.persistence.schedule_scenarios import (
    SqlAlchemyScenarioUnitOfWork,
    new_scenario_output,
    new_scenario_version,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.schedule_capability_harness import (
    LIMITS,
    OTHER_PRINCIPAL,
    PRINCIPAL,
    Activity,
    ScheduleRuntime,
    World,
)
from tests.schedule_scenario_samples import SCHEDULE_SCENARIO_CAPABILITIES, scenario_commands

pytestmark = pytest.mark.database

CLIENT_A: Final = "synthetic-scenario-client-a"
CLIENT_B: Final = "synthetic-scenario-client-b"
CALENDARS: Final = [{"key": "std", "week": [[[480, 1020]]] * 5 + [[], []], "exceptions": []}]
WRITES: Final = frozenset(
    {
        Capability.SCHEDULE_SCENARIOS_CREATE,
        Capability.SCHEDULE_SCENARIO_VERSIONS_CREATE,
        Capability.SCHEDULE_CPM_RUNS_CREATE,
        Capability.SCHEDULE_SCENARIO_OUTPUTS_RECORD,
        Capability.SCHEDULE_BASELINES_PROPOSE,
        Capability.SCHEDULE_BASELINES_WITHDRAW,
    }
)
OPERATOR_WRITES: Final = (
    Capability.SCHEDULE_BASELINES_APPROVE,
    Capability.SCHEDULE_BASELINES_REJECT,
    Capability.SCHEDULE_BASELINES_REVOKE,
    Capability.SCHEDULE_BASELINES_SET_GOVERNING,
)
_COUNTER: list[int] = [0]


def _rename() -> dict[str, Any]:
    """A valid one-op change set: move the data date."""
    return {"op": "data_date.set", "at": "2026-05-05T08:00"}


def _key(tag: str) -> str:
    _COUNTER[0] += 1
    return f"s63-{tag}-{_COUNTER[0]:06d}"


class Plane:
    """`ApplicationService` composed with the plane, as the gateway composes it."""

    def __init__(
        self,
        rt: ScheduleRuntime,
        *,
        schedule: bool = True,
        scenarios: bool = True,
        composed: bool = True,
    ) -> None:
        self.rt = rt
        self.computes: list[int] = []
        self.decodes: list[str] = []
        self.compute: Callable[[ScenarioContent], CpmResult] = run_cpm
        audit = SqlAlchemyAuditSink(rt.audit_engine)

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(rt.engine, audit=audit, schedule_enabled=schedule)

        def spy(content: ScenarioContent) -> CpmResult:
            self.computes.append(len(content.activities))
            return self.compute(content)

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            clock=rt._clock,
            schedule_enabled=schedule,
            schedule_unit_of_work=lambda: SqlAlchemyScheduleUnitOfWork(rt.engine),
            schedule_scenarios_enabled=scenarios,
            scenario_unit_of_work=(
                (lambda: SqlAlchemyScenarioUnitOfWork(rt.engine)) if composed else None
            ),
            scenario_cpm_runner=(
                functools.partial(compute_and_store_cpm_run, rt.engine, compute=spy)
                if composed
                else None
            ),
            scenario_record_builders=(
                ScenarioRecordBuilders(
                    new_version=new_scenario_version, new_output=new_scenario_output
                )
                if composed
                else None
            ),
        )

    def ok(self, command: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        return self.rt.ok(command, service=self.service, **kwargs)

    def refused(self, command: Any, **kwargs: Any) -> tuple[str, list[str]]:  # noqa: ANN401
        return self.rt.refused(command, service=self.service, **kwargs)

    def operator(self, command: Any) -> dict[str, Any]:  # noqa: ANN401
        return self.ok(command, surface=OperatorSurface.CLI)

    def count(self, table: str) -> int:
        return int(self.rt.scalar(f"SELECT count(*) FROM knowledge.{table}"))  # noqa: S608

    def refusals(self) -> int:
        return self.count("schedule_scenario_write_refusals")


@pytest.fixture
def rt(disposable_database: str) -> Iterator[ScheduleRuntime]:
    runtime = ScheduleRuntime(disposable_database)
    try:
        yield runtime
    finally:
        runtime.close()
        dispose_lease_engines()


@pytest.fixture
def w(rt: ScheduleRuntime) -> World:
    return rt.world(PRINCIPAL, "s63cap")


@pytest.fixture
def plane(rt: ScheduleRuntime) -> Plane:
    return Plane(rt)


def _publish(
    rt: ScheduleRuntime,
    w: World,
    monkeypatch: pytest.MonkeyPatch,
    *,
    data_date: date = date(2026, 5, 4),
    series_name: str = "Master Schedule",
    outcome: SchedulePublicationStatus = SchedulePublicationStatus.COMPLETE,
    **options: Any,  # noqa: ANN401
) -> str:
    return rt.publish(
        monkeypatch,
        w,
        [Activity("A100", "Synthetic excavation"), Activity("A110", "Synthetic foundations")],
        data_date=data_date,
        series_name=series_name,
        outcome=outcome,
        **options,
    )


def _create(publication: str, **changes: Any) -> CreateScheduleScenario:  # noqa: ANN401
    fields: dict[str, Any] = {
        "from_publication_id": publication,
        "name": "Synthetic what-if",
        "label": "what_if",
        "minutes_per_source_unit": 480,
        "calendars": CALENDARS,
        "default_calendar": "std",
        "idempotency_key": _key("create"),
    }
    fields.update(changes)
    return CreateScheduleScenario(**fields)


def _append(scenario: str, head: int = 1, **changes: Any) -> CreateScheduleScenarioVersion:  # noqa: ANN401
    fields: dict[str, Any] = {
        "scenario_id": scenario,
        "expected_head_version_no": head,
        "label": "update",
        "change_set": [_rename()],
        "idempotency_key": _key("append"),
    }
    fields.update(changes)
    return CreateScheduleScenarioVersion(**fields)


def _cpm(version: str, **changes: Any) -> CreateScheduleCpmRun:  # noqa: ANN401
    return CreateScheduleCpmRun(version_id=version, idempotency_key=_key("cpm"), **changes)


def _propose(publication: str, **changes: Any) -> ProposeScheduleBaseline:  # noqa: ANN401
    fields: dict[str, Any] = {
        "publication_id": publication,
        "type": "contract",
        "reason": "Synthetic proposal",
        "idempotency_key": _key("propose"),
    }
    fields.update(changes)
    return ProposeScheduleBaseline(**fields)


def _approve(**fields: Any) -> ApproveScheduleBaseline:  # noqa: ANN401
    base: dict[str, Any] = {
        "approval_reference": "Synthetic NTP 0001",
        "effective_from": "2026-05-04",
        "reason": "Synthetic approval",
        "idempotency_key": _key("approve"),
    }
    base.update(fields)
    return ApproveScheduleBaseline(**base)


def _output_document(version: dict[str, Any]) -> dict[str, Any]:
    return {
        "version_id": version["version_id"],
        "content_sha256": version["content_sha256"],
        "kind": "monte_carlo",
        "run_config": {
            "tool_name": "synthetic-mc",
            "tool_version": "1.0",
            "seed": "seed-0001",
            "iterations": 1000,
            "sampling": "independent",
            "engine": "other",
            "distribution_spec_sha256": version["distribution_spec_sha256"],
        },
        "finish_percentiles": [{"p": 50, "finish": "2026-06-01T17:00"}],
    }


def _scenario(plane: Plane, publication: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    return plane.ok(_create(publication), **kwargs)


# ---- writes and reads ------------------------------------------------------------------


def test_scenario_write_read_round_trip(
    rt: ScheduleRuntime, w: World, plane: Plane, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Create, append, run CPM, record an output, and read each back."""
    publication = _publish(rt, w, monkeypatch)
    created = _scenario(plane, publication)
    assert created["version_no"] == 1 and created["replayed"] is False
    assert created["labels"] == {
        "data_class": "schedule_scenario",
        "authority": "client_authored",
        "authoritative": False,
        "reportable": False,
    }
    assert created["snapshot_report"]["activities"] == 2
    assert created["__disclosure__"]["trust"] == {
        "level": "model_proposed",
        "basis": ["schedule_scenario", "client_authored"],
    }
    activities = plane.ok(ListScheduleScenarioActivities(version_id=created["version_id"]))
    keys = [row["key"] for row in activities["activities"]]
    assert keys == sorted(keys) and len(keys) == 2
    appended = plane.ok(
        _append(
            created["scenario_id"],
            change_set=[
                {
                    "op": "relationship.add",
                    "pred": keys[0],
                    "succ": keys[1],
                    "type": "FS",
                    "lag_minutes": 0,
                }
            ],
        )
    )
    assert appended["version_no"] == 2
    assert appended["parent_version_id"] == created["version_id"]
    assert appended["change_report"]["op_count"] == 1
    relationships = plane.ok(ListScheduleScenarioRelationships(version_id=appended["version_id"]))
    assert [(r["pred"], r["succ"]) for r in relationships["relationships"]] == [(keys[0], keys[1])]
    changes = plane.ok(ListScheduleScenarioChanges(version_id=appended["version_id"]))
    assert [op["op"] for op in changes["ops"]] == ["relationship.add"]
    run = plane.ok(_cpm(appended["version_id"]))
    assert run["created"] is True and run["status"] == "computed"
    assert run["labels"]["authority"] == "server_computed"
    detail = plane.ok(ReadScheduleCpmRun(cpm_run_id=run["cpm_run_id"]))
    assert detail["summary"]["activity_count"] == 2
    rows = plane.ok(ListScheduleCpmRunActivities(cpm_run_id=run["cpm_run_id"], critical_only=True))
    assert rows["activities"] and all(row["critical"] for row in rows["activities"])
    version = plane.ok(ReadScheduleScenarioVersion(version_id=appended["version_id"]))
    assert version["calendars"][0]["key"] == "std"
    read = plane.ok(ReadScheduleScenario(scenario_id=created["scenario_id"]))
    assert [item["version_no"] for item in read["versions"]] == [2, 1]
    listed = plane.ok(ListScheduleScenarios(project_id=w.project))
    assert [item["scenario_id"] for item in listed["scenarios"]] == [created["scenario_id"]]


def test_output_record_is_client_asserted(
    rt: ScheduleRuntime, w: World, plane: Plane, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = _publish(rt, w, monkeypatch)
    created = _scenario(plane, publication)
    version = plane.ok(ReadScheduleScenarioVersion(version_id=created["version_id"]))
    recorded = plane.ok(
        RecordScheduleScenarioOutput(
            document=_output_document(version), idempotency_key=_key("output")
        ),
        remote_client=CLIENT_A,
    )
    assert recorded["labels"] == {
        "data_class": "schedule_scenario_output",
        "authority": "client_asserted",
        "authoritative": False,
        "reportable": False,
    }
    assert recorded["__disclosure__"]["trust"]["basis"] == [
        "schedule_scenario",
        "client_authored",
        "schedule_scenario_output",
        "client_asserted",
    ]
    read = plane.ok(ReadScheduleScenarioOutput(output_id=recorded["output_id"]))
    assert read["document"]["kind"] == "monte_carlo"
    assert read["provenance"]["decision_channel"] == "remote_interactive"
    listed = plane.ok(ListScheduleScenarioOutputs(version_id=created["version_id"]))
    assert [item["output_id"] for item in listed["outputs"]] == [recorded["output_id"]]
    # A document bound to another version's content is refused, never stored.
    wrong = {**_output_document(version), "content_sha256": "0" * 64}
    assert plane.refused(
        RecordScheduleScenarioOutput(document=wrong, idempotency_key=_key("output"))
    ) == ("invalid_request", ["output"])


def test_replay_answers_the_stored_result_and_a_changed_request_conflicts(
    rt: ScheduleRuntime, w: World, plane: Plane, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = _publish(rt, w, monkeypatch)
    command = _create(publication)
    first = plane.ok(command)
    again = plane.ok(command)
    assert again["replayed"] is True
    strip = {"replayed", "__disclosure__"}
    assert {k: v for k, v in first.items() if k not in strip} == {
        k: v for k, v in again.items() if k not in strip
    }
    changed = _create(publication, name="Another name", idempotency_key=command.idempotency_key)
    assert plane.refused(changed) == ("conflict", ["idempotency_key"])
    assert plane.count("schedule_scenarios") == 1
    run = _cpm(first["version_id"])
    ran = plane.ok(run)
    replayed = plane.ok(run)
    assert replayed["replayed"] is True and replayed["created"] is ran["created"] is True
    natural = plane.ok(_cpm(first["version_id"]))
    assert natural["created"] is False and natural["cpm_run_id"] == ran["cpm_run_id"]
    assert plane.computes == [2]


def test_scenario_records_the_exact_baseline(
    rt: ScheduleRuntime, w: World, plane: Plane, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 12.1: `from_baseline_id` needs an effective Baseline (P3-20)."""
    publication = _publish(rt, w, monkeypatch)
    proposal = plane.ok(_propose(publication), remote_client=CLIENT_A)
    # A proposal is not a baseline: refused as section 7 "refused" (R10-F13).
    assert plane.refused(
        _create(None, from_publication_id=None, from_baseline_id=proposal["baseline_id"])
    ) == ("conflict", ["baseline_id"])
    approved = plane.operator(_approve(baseline_id=proposal["baseline_id"]))
    assert approved["status"] == "approved" and approved["label"] == "BL-0"
    created = plane.ok(
        _create(None, from_publication_id=None, from_baseline_id=proposal["baseline_id"])
    )
    assert created["origin"] == {
        "kind": "publication",
        "publication_id": publication,
        "baseline_id": proposal["baseline_id"],
        "version_id": None,
    }
    assert plane.refused(
        _create(None, from_publication_id=None, from_baseline_id="sbl_s63absent0001")
    ) == ("not_found", ["from_baseline_id"])


def test_series_current_read_reports_ambiguity(
    rt: ScheduleRuntime, w: World, plane: Plane, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _publish(rt, w, monkeypatch, data_date=date(2026, 5, 4))
    series = rt.scalar(
        "SELECT series_id FROM knowledge.schedule_publications WHERE publication_id = :p", p=first
    )
    second = _publish(rt, w, monkeypatch, data_date=date(2026, 6, 1), series_id=series)
    current = plane.ok(ReadScheduleSeriesCurrent(series_id=series))
    assert current["current_publication_id"] == second
    assert current["same_data_date_ambiguity"] is False
    assert current["labels"]["data_class"] == "schedule_series_current"
    third = _publish(rt, w, monkeypatch, data_date=date(2026, 6, 1), series_id=series)
    tied = plane.ok(ReadScheduleSeriesCurrent(series_id=series))
    assert tied["current_publication_id"] in {second, third}
    assert tied["same_data_date_ambiguity"] is True
    # An effective baseline publication is never the current standard update.
    proposal = plane.operator(_propose(tied["current_publication_id"]))
    plane.operator(_approve(baseline_id=proposal["baseline_id"]))
    after = plane.ok(ReadScheduleSeriesCurrent(series_id=series))
    assert after["current_publication_id"] in {second, third} - {tied["current_publication_id"]}
    assert after["same_data_date_ambiguity"] is False


# ---- operator-only and S6-3-O01 -----------------------------------------------------------


def _operator_command(capability: Capability, baseline: str, project: str) -> Any:  # noqa: ANN401
    match capability:
        case Capability.SCHEDULE_BASELINES_APPROVE:
            return _approve(baseline_id=baseline)
        case Capability.SCHEDULE_BASELINES_REJECT:
            return RejectScheduleBaseline(
                baseline_id=baseline, reason="Synthetic", idempotency_key=_key("reject")
            )
        case Capability.SCHEDULE_BASELINES_REVOKE:
            return RevokeScheduleBaseline(
                baseline_id=baseline, reason="Synthetic", idempotency_key=_key("revoke")
            )
    return SetGoverningScheduleBaseline(
        project_id=project,
        baseline_id=baseline,
        expected_governing_baseline_id=None,
        reason="Synthetic",
        idempotency_key=_key("governing"),
    )


@pytest.mark.parametrize("capability", OPERATOR_WRITES, ids=lambda c: c.value)
def test_baseline_approval_is_attested_operator_only(
    rt: ScheduleRuntime,
    w: World,
    plane: Plane,
    monkeypatch: pytest.MonkeyPatch,
    capability: Capability,
) -> None:
    """P48: a remote client, stdio MCP and `local_unattested` never decide (P3-01, P3-02)."""
    # Never published remotely (`_OPERATOR_ONLY`), even with remote writes on and
    # the compact operator publication (P3-01).
    for compact in (False, True):
        published = remote_tool_names(
            plane.service, writes_enabled=True, compact_operator_publication=compact
        )
        assert capability.value not in published
        assert Capability.SCHEDULE_BASELINES_PROPOSE.value in published
    publication = _publish(rt, w, monkeypatch)
    proposal = plane.ok(_propose(publication), remote_client=CLIENT_A)
    if capability in (
        Capability.SCHEDULE_BASELINES_REVOKE,
        Capability.SCHEDULE_BASELINES_SET_GOVERNING,
    ):
        plane.operator(_approve(baseline_id=proposal["baseline_id"]))
    command = _operator_command(capability, proposal["baseline_id"], w.project)
    before = plane.count("schedule_baseline_events") + plane.count("schedule_governing_events")
    code, _details = plane.refused(command, remote_client=CLIENT_A)
    assert code in {"denied", "unsupported"}
    # Local, unattested (stdio MCP, an unstamped local caller): `denied`.
    assert plane.refused(command) == ("denied", [])
    after = plane.count("schedule_baseline_events") + plane.count("schedule_governing_events")
    assert after == before
    # The attested CLI operator is admitted.
    admitted = plane.operator(command)
    assert admitted["replayed"] is False


_PROPOSAL_CASES: Final = (
    "operator_proposes",
    "operator_withdraws_client_proposal",
    "client_withdraws_other_bucket",
    "local_unattested",
    "client_withdraws_operator_proposal",
)


@pytest.mark.parametrize("case", _PROPOSAL_CASES)
def test_operator_may_propose_and_only_the_operator_withdraws_it(
    rt: ScheduleRuntime,
    w: World,
    plane: Plane,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """Section 15.4 (S6-3-O01, S6-3-D15, S6-3-D24, P3-21, P3-42)."""
    publication = _publish(rt, w, monkeypatch)

    def withdraw(baseline: str, **kwargs: Any) -> Any:  # noqa: ANN401
        return WithdrawScheduleBaseline(
            baseline_id=baseline, reason="Synthetic", idempotency_key=_key("withdraw")
        ), kwargs

    if case == "operator_proposes":
        monkeypatch.setattr("my_pa.domain.schedule.baselines.MAX_PENDING_PER_BUCKET", 1)
        # A `local_unattested` caller fills its own bucket (`"local_unattested\x1f"`);
        # the operator's bucket is none a client can reach, so it is not counted there.
        unattested = _publish(rt, w, monkeypatch, data_date=date(2026, 7, 1))
        assert plane.ok(_propose(unattested))["status"] == "proposed"
        first = plane.operator(_propose(publication))
        assert first["status"] == "proposed" and first["labels"]["authority"] == "proposed"
        second_publication = _publish(rt, w, monkeypatch, data_date=date(2026, 6, 1))
        # The 10-per-bucket cap (lowered to 1 here) never binds the operator.
        second = plane.operator(_propose(second_publication))
        assert second["status"] == "proposed"
        read = plane.ok(ReadScheduleBaseline(baseline_id=first["baseline_id"]))
        assert read["proposer"] == {"kind": "operator", "channel": "local_cli"}
        # A client-reachable bucket cannot withdraw it.
        command, _ = withdraw(first["baseline_id"])
        assert plane.refused(command) == ("denied", ["baseline_id"])
        return
    if case == "client_withdraws_operator_proposal":
        mine = plane.operator(_propose(publication))
        command, _ = withdraw(mine["baseline_id"])
        assert plane.refused(command, remote_client=CLIENT_A) == ("denied", ["baseline_id"])
        assert plane.operator(command)["status"] == "withdrawn"
        return
    theirs = plane.ok(_propose(publication), remote_client=CLIENT_A)
    command, _ = withdraw(theirs["baseline_id"])
    if case == "operator_withdraws_client_proposal":
        assert plane.operator(command)["status"] == "withdrawn"
    elif case == "client_withdraws_other_bucket":
        assert plane.refused(command, remote_client=CLIENT_B) == ("denied", ["baseline_id"])
        assert plane.ok(command, remote_client=CLIENT_A)["status"] == "withdrawn"
    else:
        assert plane.refused(command) == ("denied", ["baseline_id"])


_PROVENANCE_CASES: Final = ("local_reader", "remote_reader", "proposal", "approved")


@pytest.mark.parametrize("case", _PROVENANCE_CASES)
def test_baseline_outputs_show_provenance(
    rt: ScheduleRuntime,
    w: World,
    plane: Plane,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """Section 15.6.3/15.6.4: labels, proposer, client ids (P3-17, P3-19)."""
    publication = _publish(rt, w, monkeypatch)
    proposal = plane.ok(_propose(publication), remote_client=CLIENT_A)
    baseline = proposal["baseline_id"]
    if case == "proposal":
        read = plane.ok(ReadScheduleBaseline(baseline_id=baseline))
        assert read["labels"] == {
            "data_class": "schedule_baseline",
            "authority": "proposed",
            "authoritative": False,
            "reportable": False,
        }
        assert read["status"] == "proposed" and read["governing"] is False
        listed = plane.ok(ListScheduleBaselines(project_id=w.project, status="proposed"))
        assert [item["labels"]["authoritative"] for item in listed["baselines"]] == [False]
        return
    if case == "approved":
        plane.operator(_approve(baseline_id=baseline))
        read = plane.ok(ReadScheduleBaseline(baseline_id=baseline))
        assert read["labels"]["authority"] == "operator_approved"
        assert read["labels"]["authoritative"] is True
        assert read["approver"] == {"kind": "operator", "channel": "local_cli"}
        assert [event["action"] for event in read["events"]] == ["propose", "approve"]
        return
    remote = case == "remote_reader"
    kwargs: dict[str, Any] = {"remote_client": CLIENT_B} if remote else {}
    read = plane.ok(ReadScheduleBaseline(baseline_id=baseline), **kwargs)
    expected = None if remote else CLIENT_A
    assert read["proposer"] == {
        "kind": "client",
        "channel": "remote_interactive",
        "client_id": expected,
    }
    assert read["provenance"]["asserting_client_id"] == expected
    assert read["events"][0]["provenance"]["asserting_client_id"] == expected


def test_governing_designation_and_compare(
    rt: ScheduleRuntime, w: World, plane: Plane, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _publish(rt, w, monkeypatch, data_date=date(2026, 5, 4))
    series = rt.scalar(
        "SELECT series_id FROM knowledge.schedule_publications WHERE publication_id = :p", p=first
    )
    later = _publish(rt, w, monkeypatch, data_date=date(2026, 6, 1), series_id=series)
    approved = plane.operator(_approve(publication_id=first, type="contract"))
    assert plane.ok(ReadGoverningScheduleBaseline(project_id=w.project))["baseline_id"] is None
    governed = plane.operator(
        _operator_command(
            Capability.SCHEDULE_BASELINES_SET_GOVERNING, approved["baseline_id"], w.project
        )
    )
    assert governed["governing"] is True and "governing_event_id" in governed
    now = plane.ok(ReadGoverningScheduleBaseline(project_id=w.project))
    assert now["baseline_id"] == approved["baseline_id"] and now["basis"] == "as_recorded"
    earlier = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert (
        plane.ok(ReadGoverningScheduleBaseline(project_id=w.project, as_of=earlier))["baseline_id"]
        is None
    )
    compared = plane.ok(
        CompareScheduleBaseline(baseline_id=approved["baseline_id"], to_publication_id=later)
    )
    assert compared["baseline"]["label"] == "BL-0"
    assert compared["labels"]["authoritative"] is True
    # Revoking the governing Baseline is refused; the governing chain is the operator's.
    revoke = _operator_command(Capability.SCHEDULE_BASELINES_REVOKE, approved["baseline_id"], "")
    assert plane.refused(revoke, surface=OperatorSurface.CLI) == ("conflict", ["governing"])


def _series_pair(
    rt: ScheduleRuntime,
    w: World,
    monkeypatch: pytest.MonkeyPatch,
    **options: Any,  # noqa: ANN401
) -> tuple[str, str]:
    """A publication (imported with `options`) and a later complete one in its Series."""
    first = _publish(rt, w, monkeypatch, data_date=date(2026, 5, 4), **options)
    series = rt.scalar(
        "SELECT series_id FROM knowledge.schedule_publications WHERE publication_id = :p", p=first
    )
    later = _publish(rt, w, monkeypatch, data_date=date(2026, 6, 1), series_id=series)
    return first, later


@pytest.mark.parametrize("status", ["proposed", "rejected", "withdrawn", "revoked"])
def test_compare_refuses_a_non_effective_baseline(
    rt: ScheduleRuntime,
    w: World,
    plane: Plane,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    """Section 15.7.2 (R10-F13, FR10-F01): compare names an effective Baseline only."""
    first, later = _series_pair(rt, w, monkeypatch)
    baseline = plane.ok(_propose(first), remote_client=CLIENT_A)["baseline_id"]
    if status == "rejected":
        plane.operator(_operator_command(Capability.SCHEDULE_BASELINES_REJECT, baseline, ""))
    elif status == "withdrawn":
        plane.operator(
            WithdrawScheduleBaseline(
                baseline_id=baseline, reason="Synthetic", idempotency_key=_key("withdraw")
            )
        )
    elif status == "revoked":
        plane.operator(_approve(baseline_id=baseline))
        plane.operator(_operator_command(Capability.SCHEDULE_BASELINES_REVOKE, baseline, ""))
    assert plane.ok(ReadScheduleBaseline(baseline_id=baseline))["status"] == status
    compare = CompareScheduleBaseline(baseline_id=baseline, to_publication_id=later)
    assert plane.refused(compare) == ("conflict", ["baseline_id"])
    assert plane.refused(compare, remote_client=CLIENT_A) == ("conflict", ["baseline_id"])


@pytest.mark.parametrize("capability", ["schedule_scenarios.create", "schedule_baselines.compare"])
def test_an_ineligible_baseline_answers_conflict_status(
    rt: ScheduleRuntime,
    w: World,
    plane: Plane,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
) -> None:
    """Section 15.7.2 (FR10-F02): approved, but its publication is not effective.

    An import-time approval whose publication ends `review_required` is
    `ineligible`: `from_baseline_id` and compare answer `conflict(status)`, not
    the non-effective `conflict(baseline_id)`.
    """
    first, later = _series_pair(
        rt,
        w,
        monkeypatch,
        role="baseline",
        outcome=SchedulePublicationStatus.REVIEW_REQUIRED,
    )
    baseline = rt.scalar(
        "SELECT baseline_id FROM knowledge.schedule_baselines WHERE publication_id = :p", p=first
    )
    assert plane.ok(ReadScheduleBaseline(baseline_id=baseline))["status"] == "ineligible"
    command: Any = (
        _create(None, from_publication_id=None, from_baseline_id=baseline)
        if capability == "schedule_scenarios.create"
        else CompareScheduleBaseline(baseline_id=baseline, to_publication_id=later)
    )
    assert plane.refused(command) == ("conflict", ["status"])
    assert plane.count("schedule_scenarios") == 0


# ---- the switch ---------------------------------------------------------------------------


_SWITCHES: Final = {
    "schedule_off": {"schedule": False, "scenarios": True},
    "scenarios_off": {"schedule": True, "scenarios": False},
    "both_off": {"schedule": False, "scenarios": False},
    "not_composed": {"schedule": True, "scenarios": True, "composed": False},
}


@pytest.mark.parametrize("switch", sorted(_SWITCHES))
@pytest.mark.parametrize(
    "capability", sorted(SCHEDULE_SCENARIO_CAPABILITIES), ids=lambda c: c.value
)
def test_every_scenario_name_is_unsupported_while_the_plane_is_off(
    rt: ScheduleRuntime, w: World, capability: Capability, switch: str
) -> None:
    """Section 15.8: withheld from the manifest and `unsupported` before any read (P3-03/04).

    The ports stay composed in every case but `not_composed`, so a handler that
    skipped `_scenario_plane()` would reach the plane and answer otherwise.
    """
    off = Plane(rt, **_SWITCHES[switch])
    assert capability not in off.service.available_capabilities
    command = scenario_commands("s63off")[capability]
    before = off.count("schedule_scenario_write_requests")
    for kwargs in ({"surface": OperatorSurface.CLI}, {}, {"remote_client": CLIENT_A}):
        assert off.refused(command, **kwargs) == ("unsupported", []), kwargs
    assert off.count("schedule_scenario_write_requests") == before
    assert off.refusals() == 0
    assert capability in Plane(rt).service.available_capabilities


def test_scenario_switch_changes_no_row(
    rt: ScheduleRuntime, w: World, plane: Plane, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = _publish(rt, w, monkeypatch)
    _scenario(plane, publication)
    tables = (
        "schedule_scenarios",
        "schedule_scenario_versions",
        "schedule_scenario_write_requests",
        "schedule_scenario_write_refusals",
        "schedule_publications",
    )
    before = {table: plane.count(table) for table in tables}
    for scenarios in (False, True, False):
        Plane(rt, scenarios=scenarios).service.available_capabilities  # noqa: B018
        assert {table: plane.count(table) for table in tables} == before


# ---- the import gates (section 15.9) -----------------------------------------------------


def _import(rt: ScheduleRuntime, w: World, **fields: Any) -> ImportSchedulePublication:  # noqa: ANN401
    object_id, version_id = rt.source_object(w)
    base: dict[str, Any] = {
        "project_id": w.project,
        "series_name": "Gate Schedule",
        "enrollment_id": w.enrollment,
        "source_object_id": object_id,
        "source_version_id": version_id,
        "publication_role": "update",
        "idempotency_key": _key("import"),
    }
    base.update(fields)
    return ImportSchedulePublication(**base)


_APPROVAL: Final = {
    "publication_role": "baseline",
    "baseline_kind": "contract",
    "approval_reference": "Synthetic NTP 0002",
    "effective_from": "2026-05-04",
    "reason": "Synthetic import approval",
}


def test_baseline_import_refused_while_plane_off(rt: ScheduleRuntime, w: World) -> None:
    """P56 (R10-F07, S6-3-D14, S6-3-D22; P3-05, P3-43)."""
    off = Plane(rt, scenarios=False)
    command = _import(rt, w, **_APPROVAL)
    before = off.count("schedule_publications")
    # The CLI operator with only the Schedule switch: `invalid_request(publication_role)`.
    assert off.refused(command, surface=OperatorSurface.CLI) == (
        "invalid_request",
        ["publication_role"],
    )
    # A remote or unattested caller meets E-10/E-12 first and never learns of the plane.
    assert off.refused(command, remote_client=CLIENT_A)[0] == "unsupported"
    assert off.refused(command) == ("denied", [])
    # `reference` and `working` are refused whatever the switches, at the command.
    for fields, detail in (
        ({"publication_role": "reference"}, SafeDetail.PUBLICATION_ROLE),
        ({**_APPROVAL, "baseline_kind": "working"}, SafeDetail.BASELINE_KIND),
    ):
        with pytest.raises(InvalidRequestError) as refused:
            _import(rt, w, **fields)
        assert refused.value.safe_details == (detail,)
    assert off.count("schedule_publications") == before
    # With the plane on, the same import designates and approves in one act.
    admitted = Plane(rt).operator(command)
    assert admitted["created"] is True
    assert off.count("schedule_baseline_events") == 1


def test_series_auto_refused_while_plane_off(rt: ScheduleRuntime, w: World) -> None:
    """Section 15.9 step 4 (P3-06)."""
    command = _import(rt, w, series_name=None, series_auto=True)
    off = Plane(rt, scenarios=False)
    assert off.refused(command, surface=OperatorSurface.CLI) == ("invalid_request", ["series_auto"])
    assert off.refused(command) == ("denied", [])
    admitted = Plane(rt).operator(command)
    assert admitted["created"] is True


def test_intake_series_name_is_refused(rt: ScheduleRuntime, w: World, plane: Plane) -> None:
    for fields in (
        {"series_name": "Schedule intake 0123456789ab"},
        {"series_name": None, "series_auto": True, "series_name_if_new": "Schedule Intake X"},
    ):
        with pytest.raises(InvalidRequestError) as refused:
            _import(rt, w, **fields)
        assert refused.value.safe_details == (SafeDetail.SERIES_NAME,)


def test_s5_reads_show_series_kind_and_match_state(
    rt: ScheduleRuntime, w: World, plane: Plane, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 15.6.2 (S6-3-D18): `series_kind`, `match_state`, and the intake delta refusal."""
    standard = _publish(rt, w, monkeypatch)
    object_id, version_id = rt.source_object(w)
    admitted = plane.operator(
        ImportSchedulePublication(
            project_id=w.project,
            series_auto=True,
            enrollment_id=w.enrollment,
            source_object_id=object_id,
            source_version_id=version_id,
            publication_role="update",
            idempotency_key=_key("auto"),
        )
    )
    intake = admitted["publication_id"]
    pending = plane.ok(ReadSchedulePublication(publication_id=intake))
    assert pending["series_kind"] == "intake" and pending["match_state"] == "pending"
    read = plane.ok(ReadSchedulePublication(publication_id=standard))
    assert read["series_kind"] == "standard" and "match_state" not in read
    series = plane.ok(ListScheduleSeries(project_id=w.project))
    assert sorted(item["series_kind"] for item in series["series"]) == ["intake", "standard"]
    standard_series = rt.scalar(
        "SELECT series_id FROM knowledge.schedule_publications WHERE publication_id = :p",
        p=standard,
    )
    publications = plane.ok(ListSchedulePublications(series_id=standard_series))
    assert {row["series_kind"] for row in publications["publications"]} == {"standard"}
    assert plane.refused(
        ListScheduleChanges(from_publication_id=standard, to_publication_id=intake)
    ) == ("invalid_request", ["to_publication_id"])
    assert plane.refused(
        ListScheduleChanges(from_publication_id=intake, to_publication_id=standard)
    ) == ("invalid_request", ["from_publication_id"])
    decisions = plane.ok(ListScheduleSeriesMatchDecisions(project_id=w.project))
    assert decisions["decisions"] == []


# ---- budgets, quotas and the refusal bound (section 15.10) --------------------------------


@pytest.mark.parametrize("bound", ["bucket_hour", "bucket_day", "principal_day"])
def test_client_write_budget_is_enforced_per_bucket_and_principal(
    rt: ScheduleRuntime,
    w: World,
    plane: Plane,
    monkeypatch: pytest.MonkeyPatch,
    bound: str,
) -> None:
    """Section 8.3 (P3-13): the 6 client writes together; replays consume nothing."""
    publication = _publish(rt, w, monkeypatch)
    limits = {"bucket_hour": "BUCKET_WRITES_PER_HOUR", "bucket_day": "BUCKET_WRITES_PER_DAY"}
    monkeypatch.setattr(plane_module, limits.get(bound, "PRINCIPAL_WRITES_PER_DAY"), 2)
    first = _create(publication)
    plane.ok(first, remote_client=CLIENT_A)
    plane.ok(first, remote_client=CLIENT_A)  # a replay consumes nothing
    plane.ok(_create(publication), remote_client=CLIENT_A)
    assert plane.refused(_create(publication), remote_client=CLIENT_A) == (
        "rate_limited",
        ["scenario_write_budget"],
    )
    other = (
        plane.ok(_create(publication), remote_client=CLIENT_B) if bound != "principal_day" else None
    )
    if bound == "principal_day":
        assert plane.refused(_create(publication), remote_client=CLIENT_B)[0] == "rate_limited"
    else:
        assert other is not None
    # The attested operator is never budgeted.
    assert plane.operator(_create(publication))["replayed"] is False


@pytest.mark.parametrize("quota", ["bucket_day", "principal_day", "principal_total"])
def test_storage_quota_is_enforced(
    rt: ScheduleRuntime,
    w: World,
    plane: Plane,
    monkeypatch: pytest.MonkeyPatch,
    quota: str,
) -> None:
    """Section 2.10/8.3 (P3-14): new canonical bytes against the Principal's and bucket's quota."""
    publication = _publish(rt, w, monkeypatch)
    created = plane.ok(_create(publication), remote_client=CLIENT_A)
    size = int(created["content_size_bytes"])
    names = {
        "bucket_day": "BUCKET_BYTES_PER_DAY",
        "principal_day": "PRINCIPAL_BYTES_PER_DAY",
        "principal_total": "PRINCIPAL_BYTES_TOTAL",
    }
    monkeypatch.setattr(plane_module, names[quota], size + size // 2)
    assert plane.refused(_create(publication), remote_client=CLIENT_A) == (
        "rate_limited",
        ["storage_quota"],
    )
    if quota == "bucket_day":
        assert plane.ok(_create(publication), remote_client=CLIENT_B)["version_no"] == 1


def test_refusal_bound_answers_before_decoding(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 15.10 step 4 (P3-12, P3-40): recorded refusals, then the bound before any decode."""
    decoded: list[object] = []
    real = plane_module.ScenarioWriteBuilders()

    def decode(value: object) -> Any:  # noqa: ANN401
        decoded.append(value)
        return real.decode_calendar(value)

    monkeypatch.setattr(
        plane_module.ScheduleScenarioApplication,
        "__init__",
        _with_builders(plane_module.ScenarioWriteBuilders(decode_calendar=decode)),
    )
    plane = Plane(rt)
    publication = _publish(rt, w, monkeypatch)
    monkeypatch.setattr(plane_module, "REFUSALS_PER_HOUR", 2)
    bad = [{"key": "std"}]
    # [recorded] Each refusal from step 5 on is recorded for the client's bucket.
    for _ in range(2):
        assert plane.refused(_create(publication, calendars=bad), remote_client=CLIENT_A) == (
            "invalid_request",
            ["calendar"],
        )
    assert plane.refusals() == 2
    decoded.clear()
    # [bound] The third answers the bound before any decode, and is not recorded.
    assert plane.refused(_create(publication, calendars=bad), remote_client=CLIENT_A) == (
        "rate_limited",
        ["scenario_refusal_budget"],
    )
    assert decoded == []
    assert plane.refusals() == 2
    # Another bucket is unaffected; the attested operator is never bound.
    assert plane.ok(_create(publication), remote_client=CLIENT_B)["version_no"] == 1
    assert plane.operator(_create(publication))["version_no"] == 1


def _with_builders(builders: Any) -> Callable[..., None]:  # noqa: ANN401
    original = plane_module.ScheduleScenarioApplication.__init__

    def init(self: Any, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        kwargs["builders"] = builders
        original(self, *args, **kwargs)

    return init


def test_refusal_counting_scope(
    rt: ScheduleRuntime, w: World, plane: Plane, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S6-3-D13 (R10-F11, P3-45, FR10-F03): steps 1-4 refusals never, steps 5-6 always."""
    publication = _publish(rt, w, monkeypatch)
    off = Plane(rt, scenarios=False)
    assert off.refused(_create(publication), remote_client=CLIENT_A) == ("unsupported", [])
    # A missing grant (a remote caller granted another capability only).
    grants = frozenset({(Capability.SCHEDULE_SCENARIOS_LIST, None)})
    assert plane.refused(_create(publication), remote_client=CLIENT_A, grants=grants)[0] in {
        "unsupported",
        "denied",
    }
    # An authority `denied` (an operator write by an unattested caller).
    proposal = plane.ok(_propose(publication), remote_client=CLIENT_A)
    assert plane.refused(_approve(baseline_id=proposal["baseline_id"])) == ("denied", [])
    assert plane.refusals() == 0
    # A step-5 refusal is counted.
    assert plane.refused(_create(publication, calendars=[{}]), remote_client=CLIENT_A)[0] == (
        "invalid_request"
    )
    assert plane.refusals() == 1
    # So are a step-6 conflict (a moved head, FR10-F03) and a quota refusal.
    created = plane.ok(_create(publication), remote_client=CLIENT_A)
    assert plane.refused(_append(created["scenario_id"], head=2), remote_client=CLIENT_A) == (
        "conflict",
        ["expected_version"],
    )
    assert plane.refusals() == 2
    monkeypatch.setattr(plane_module, "PRINCIPAL_BYTES_TOTAL", 1)
    assert plane.refused(_create(publication), remote_client=CLIENT_A) == (
        "rate_limited",
        ["storage_quota"],
    )
    assert plane.refusals() == 3
    rows = rt.scalar(
        "SELECT string_agg(error_code, ',' ORDER BY error_code) "
        "FROM knowledge.schedule_scenario_write_refusals"
    )
    assert rows == "conflict,invalid_request,rate_limited"


def test_cpm_units_bound_is_enforced_client(
    rt: ScheduleRuntime, w: World, plane: Plane, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 15.10 (P3-15): a client over the hourly CPM units never stores a run."""
    publication = _publish(rt, w, monkeypatch)
    created = _scenario(plane, publication)
    monkeypatch.setattr(plane_module, "CPM_UNITS_PER_HOUR", 3)
    plane.ok(_cpm(created["version_id"]), remote_client=CLIENT_A)
    second = plane.ok(_append(created["scenario_id"], change_set=[_rename()]))
    assert plane.refused(_cpm(second["version_id"]), remote_client=CLIENT_A) == (
        "rate_limited",
        ["cpm_run"],
    )
    assert plane.count("schedule_cpm_runs") == 1


@pytest.mark.parametrize("case", ["client", "operator_exempt"])
def test_cpm_units_bound_is_enforced(
    rt: ScheduleRuntime,
    w: World,
    plane: Plane,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """R10-F04 (P3-15, P3-16): a client filling the units never locks the operator out."""
    publication = _publish(rt, w, monkeypatch)
    created = _scenario(plane, publication)
    second = plane.ok(_append(created["scenario_id"], change_set=[_rename()]))
    monkeypatch.setattr(plane_module, "CPM_UNITS_PER_HOUR", 2)
    plane.ok(_cpm(created["version_id"]), remote_client=CLIENT_A)
    if case == "client":
        assert plane.refused(_cpm(second["version_id"]), remote_client=CLIENT_B) == (
            "rate_limited",
            ["cpm_run"],
        )
        assert plane.computes == [2]
    else:
        assert plane.operator(_cpm(second["version_id"]))["created"] is True
        assert plane.computes == [2, 2]


@pytest.mark.parametrize("case", ["writes", "bytes", "cpm_units"])
def test_attested_operator_is_never_budgeted(
    rt: ScheduleRuntime,
    w: World,
    plane: Plane,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """Section 15.10 (P3-16): never budgeted, quota-limited or held to the units bound."""
    publication = _publish(rt, w, monkeypatch)
    created = plane.operator(_create(publication))
    names = {
        "writes": ("BUCKET_WRITES_PER_HOUR", "PRINCIPAL_WRITES_PER_DAY"),
        "bytes": ("BUCKET_BYTES_PER_DAY", "PRINCIPAL_BYTES_PER_DAY", "PRINCIPAL_BYTES_TOTAL"),
        "cpm_units": ("CPM_UNITS_PER_HOUR",),
    }
    for name in names[case]:
        monkeypatch.setattr(plane_module, name, 0)
    if case == "cpm_units":
        assert plane.operator(_cpm(created["version_id"]))["created"] is True
    else:
        assert plane.operator(_create(publication))["version_no"] == 1
        assert plane.refused(_create(publication), remote_client=CLIENT_A)[0] == "rate_limited"
    assert plane.refusals() <= 1


_OVER_BUDGET: Final = (
    "write_budget",
    "byte_quota",
    "refusal_bound",
    "replay_over_budget",
    "natural_key_over_byte_quota",
    "byte_headroom_below_content_size",
)


@pytest.mark.parametrize("case", _OVER_BUDGET)
def test_over_budget_cpm_run_never_computes(
    rt: ScheduleRuntime,
    w: World,
    plane: Plane,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """R10-F02/R10-N01/R10-N06 (P3-41, P3-46, P3-47): the pre-check runs before the compute."""
    publication = _publish(rt, w, monkeypatch)
    created = plane.ok(_create(publication), remote_client=CLIENT_A)
    version = created["version_id"]
    size = int(created["content_size_bytes"])
    if case == "replay_over_budget":
        command = _cpm(version)
        plane.ok(command, remote_client=CLIENT_A)
        monkeypatch.setattr(plane_module, "BUCKET_WRITES_PER_HOUR", 0)
        replayed = plane.ok(command, remote_client=CLIENT_A)
        assert replayed["replayed"] is True
        assert plane.computes == [2]
        return
    if case == "natural_key_over_byte_quota":
        plane.operator(_cpm(version))
        assert plane.computes == [2]
        monkeypatch.setattr(plane_module, "BUCKET_BYTES_PER_DAY", size)
        natural = plane.ok(_cpm(version), remote_client=CLIENT_A)
        assert natural["created"] is False and natural["replayed"] is False
        assert plane.computes == [2]
        return
    if case == "byte_headroom_below_content_size":
        # Headroom > 0 and < the version's content size: the pre-check (0 new bytes)
        # admits, so the compute seam is reached; step 5 decides with the real size.
        monkeypatch.setattr(plane_module, "BUCKET_BYTES_PER_DAY", size + size // 2)
        plane.rt.invoke(_cpm(version), service=plane.service, remote_client=CLIENT_A)
        assert plane.computes == [2]
        return
    if case == "write_budget":
        monkeypatch.setattr(plane_module, "BUCKET_WRITES_PER_HOUR", 1)
        expected: tuple[str, list[str]] = ("rate_limited", ["scenario_write_budget"])
    elif case == "byte_quota":
        monkeypatch.setattr(plane_module, "BUCKET_BYTES_PER_DAY", size)
        expected = ("rate_limited", ["storage_quota"])
    else:
        monkeypatch.setattr(plane_module, "REFUSALS_PER_HOUR", 1)
        plane.refused(_create(publication, calendars=[{}]), remote_client=CLIENT_A)
        expected = ("rate_limited", ["scenario_refusal_budget"])
    assert plane.refused(_cpm(version), remote_client=CLIENT_A) == expected
    assert plane.computes == []
    assert plane.count("schedule_cpm_runs") == 0


def test_version_append_conflict_is_reported_before_computing(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 15.10 step 5 (P3-11): a moved head never reaches `apply_change_set`."""
    plane = Plane(rt)
    publication = _publish(rt, w, monkeypatch)
    created = _scenario(plane, publication)
    plane.ok(_append(created["scenario_id"], change_set=[_rename()]))
    applied: list[object] = []
    real = plane_module.ScenarioWriteBuilders()

    def spy(parent: Any, ops: Any) -> Any:  # noqa: ANN401
        applied.append(ops)
        return real.apply_change_set(parent, ops)

    monkeypatch.setattr(
        plane_module.ScheduleScenarioApplication,
        "__init__",
        _with_builders(plane_module.ScenarioWriteBuilders(apply_change_set=spy)),
    )
    assert plane.refused(_append(created["scenario_id"], 1, change_set=[_rename()])) == (
        "conflict",
        ["expected_version"],
    )
    assert applied == []
    assert plane.ok(_append(created["scenario_id"], 2, change_set=[_rename()]))["version_no"] == 3
    assert len(applied) == 1


# ---- the refusal mapping (section 15.7.2) ---------------------------------------------------


def test_every_repository_outcome_maps_to_its_public_answer(
    rt: ScheduleRuntime, w: World, plane: Plane, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 15.7.2: the reachable rows, each answered as the table states."""
    publication = _publish(rt, w, monkeypatch)
    failed = _publish(
        rt,
        w,
        monkeypatch,
        data_date=date(2026, 6, 1),
        outcome=SchedulePublicationStatus.REVIEW_REQUIRED,
    )
    created = _scenario(plane, publication)
    cases: list[tuple[Any, tuple[str, list[str]]]] = [
        (_create("spub_s63absent0001"), ("not_found", ["from_publication_id"])),
        (_create(failed), ("conflict", ["status"])),
        (
            _create(
                None,
                from_publication_id=None,
                from_version_id="sscv_s63absent0001",
                minutes_per_source_unit=None,
                calendars=None,
                default_calendar=None,
            ),
            ("not_found", ["from_version_id"]),
        ),
        (_create(publication, default_calendar="nope"), ("invalid_request", ["calendar"])),
        (_append("sscn_s63absent0001"), ("not_found", ["scenario_id"])),
        (_append(created["scenario_id"], 5), ("conflict", ["expected_version"])),
        (
            _append(created["scenario_id"], change_set=[{"op": "no.such"}]),
            ("invalid_request", ["change_set_unknown_op"]),
        ),
        (
            _append(
                created["scenario_id"], change_set=[{"op": "activity.remove", "key": "x:none"}]
            ),
            ("invalid_request", ["change_set_key_absent"]),
        ),
        (_cpm("sscv_s63absent0001"), ("not_found", ["version_id"])),
        (
            RecordScheduleScenarioOutput(
                document={"version_id": "sscv_s63absent0001"}, idempotency_key=_key("out")
            ),
            ("invalid_request", ["output"]),
        ),
        (_propose("spub_s63absent0001"), ("not_found", ["publication_id"])),
        (_propose(failed), ("conflict", ["status"])),
        (ReadScheduleScenario(scenario_id="sscn_s63absent0001"), ("not_found", ["scenario_id"])),
        (
            ReadScheduleScenarioVersion(version_id="sscv_s63absent0001"),
            ("not_found", ["version_id"]),
        ),
        (ReadScheduleCpmRun(cpm_run_id="scpm_s63absent0001"), ("not_found", ["cpm_run_id"])),
        (ReadScheduleScenarioOutput(output_id="ssco_s63absent0001"), ("not_found", ["output_id"])),
        (ReadScheduleBaseline(baseline_id="sbl_s63absent0001"), ("not_found", ["baseline_id"])),
        (ReadScheduleSeriesCurrent(series_id="sser_s63absent0001"), ("not_found", ["series_id"])),
        (ListScheduleScenarios(project_id="prj_s63absent0001"), ("not_found", ["project_id"])),
        (
            ListScheduleScenarios(project_id=w.project, cursor="bm90IGEgY3Vyc29y"),
            ("invalid_request", ["cursor"]),
        ),
    ]
    for command, expected in cases:
        assert plane.refused(command) == expected, (command.capability.value, expected)
    # Duplicate proposals and a second approval of one publication conflict.
    proposal = plane.ok(_propose(publication), remote_client=CLIENT_A)
    assert plane.refused(_propose(publication), remote_client=CLIENT_A) == (
        "conflict",
        ["baseline_id"],
    )
    plane.operator(_approve(baseline_id=proposal["baseline_id"]))
    assert plane.refused(
        _approve(baseline_id=proposal["baseline_id"]), surface=OperatorSurface.CLI
    ) == (
        "conflict",
        ["baseline_id"],
    )
    # A governing CAS mismatch.
    governing = SetGoverningScheduleBaseline(
        project_id=w.project,
        baseline_id=proposal["baseline_id"],
        expected_governing_baseline_id="sbl_s63absent0001",
        reason="Synthetic",
        idempotency_key=_key("gov"),
    )
    assert plane.refused(governing, surface=OperatorSurface.CLI) == ("conflict", ["governing"])
    # The pending-per-bucket cap.
    monkeypatch.setattr("my_pa.domain.schedule.baselines.MAX_PENDING_PER_BUCKET", 0)
    second = _publish(rt, w, monkeypatch, data_date=date(2026, 7, 1))
    assert plane.refused(_propose(second), remote_client=CLIENT_A) == (
        "rate_limited",
        ["baseline_id"],
    )


@pytest.mark.parametrize(
    "capability",
    [
        Capability.SCHEDULE_SCENARIOS_LIST,
        Capability.SCHEDULE_SCENARIOS_READ,
        Capability.SCHEDULE_SCENARIO_VERSIONS_READ,
        Capability.SCHEDULE_CPM_RUNS_READ,
        Capability.SCHEDULE_SCENARIO_OUTPUTS_LIST,
        Capability.SCHEDULE_BASELINES_READ,
    ],
    ids=lambda c: c.value,
)
def test_hidden_is_absent_for_every_read(
    rt: ScheduleRuntime,
    w: World,
    plane: Plane,
    monkeypatch: pytest.MonkeyPatch,
    capability: Capability,
) -> None:
    """Section 15.6.2 (P3-18): another Principal's row is absent, never counted."""
    publication = _publish(rt, w, monkeypatch)
    created = _scenario(plane, publication)
    run = plane.ok(_cpm(created["version_id"]))
    proposal = plane.operator(_propose(publication))
    other = rt.world(OTHER_PRINCIPAL, "s63oth", source=w.source)
    commands = {
        Capability.SCHEDULE_SCENARIOS_LIST: ListScheduleScenarios(project_id=w.project),
        Capability.SCHEDULE_SCENARIOS_READ: ReadScheduleScenario(
            scenario_id=created["scenario_id"]
        ),
        Capability.SCHEDULE_SCENARIO_VERSIONS_READ: ReadScheduleScenarioVersion(
            version_id=created["version_id"]
        ),
        Capability.SCHEDULE_CPM_RUNS_READ: ReadScheduleCpmRun(cpm_run_id=run["cpm_run_id"]),
        Capability.SCHEDULE_SCENARIO_OUTPUTS_LIST: ListScheduleScenarioOutputs(
            version_id=created["version_id"]
        ),
        Capability.SCHEDULE_BASELINES_READ: ReadScheduleBaseline(
            baseline_id=proposal["baseline_id"]
        ),
    }
    command = commands[capability]
    code, _ = plane.refused(command, principal_id=other.principal)
    assert code == "not_found"
    if capability is Capability.SCHEDULE_SCENARIOS_LIST:
        # The other Principal's own Project lists none of this Principal's Scenarios.
        listed = plane.ok(
            ListScheduleScenarios(project_id=other.project), principal_id=other.principal
        )
        assert listed["scenarios"] == []


# ---- remote keys (sections 6.7, 15.12.2; R8-F09) ---------------------------------------------


def _remote_create(plane: Plane, publication: str, client: str) -> dict[str, Any]:
    payload = {
        "from_publication_id": publication,
        "name": "Synthetic remote scenario",
        "label": "what_if",
        "minutes_per_source_unit": 480,
        "calendars": CALENDARS,
        "default_calendar": "std",
    }
    composed = compose_remote_arguments(
        capability_name=Capability.SCHEDULE_SCENARIOS_CREATE.value,
        arguments={"payload": payload},
        principal=Principal(
            principal_id=PRINCIPAL, kind=PrincipalKind.OPERATOR, authenticated=True
        ),
        grants=frozenset({(Capability.SCHEDULE_SCENARIOS_CREATE, None)}),
        clock=lambda: datetime(2026, 11, 11, tzinfo=UTC),
        authenticated_client_id=client,
    )
    return plane.ok(CreateScheduleScenario(**composed["payload"]), remote_client=client)


def test_identical_payloads_from_two_clients_create_two_rows(
    rt: ScheduleRuntime, w: World, plane: Plane, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R8-F09 (P3-08): the stamped key binds the OAuth client."""
    publication = _publish(rt, w, monkeypatch)
    first = _remote_create(plane, publication, CLIENT_A)
    second = _remote_create(plane, publication, CLIENT_B)
    assert first["scenario_id"] != second["scenario_id"]
    assert second["replayed"] is False
    assert plane.count("schedule_scenarios") == 2


def test_identical_retry_from_one_client_replays(
    rt: ScheduleRuntime, w: World, plane: Plane, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S6-3-D06 (P3-09): one client's identical retry derives its own key and replays."""
    publication = _publish(rt, w, monkeypatch)
    first = _remote_create(plane, publication, CLIENT_A)
    again = _remote_create(plane, publication, CLIENT_A)
    assert again["replayed"] is True and again["scenario_id"] == first["scenario_id"]
    assert plane.count("schedule_scenarios") == 1


def test_baseline_list_pages_by_creation(
    rt: ScheduleRuntime, w: World, plane: Plane, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S6-3-D08: `baselines_created_desc_id_desc`, filtered before paging."""
    proposals = []
    for month in (5, 6, 7):
        publication = _publish(rt, w, monkeypatch, data_date=date(2026, month, 4))
        proposals.append(plane.operator(_propose(publication))["baseline_id"])
    plane.operator(
        WithdrawScheduleBaseline(
            baseline_id=proposals[1], reason="Synthetic", idempotency_key=_key("withdraw")
        )
    )
    page = plane.ok(ListScheduleBaselines(project_id=w.project, status="proposed", page_size=1))
    assert [item["baseline_id"] for item in page["baselines"]] == [proposals[2]]
    cursor = page["__disclosure__"]["truncation"]["next_cursor"]
    rest = plane.ok(
        ListScheduleBaselines(project_id=w.project, status="proposed", page_size=1, cursor=cursor)
    )
    assert [item["baseline_id"] for item in rest["baselines"]] == [proposals[0]]
    assert rest["__disclosure__"]["truncation"]["is_truncated"] is False


def test_rejected_baseline_reads_rejected(
    rt: ScheduleRuntime, w: World, plane: Plane, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = _publish(rt, w, monkeypatch)
    proposal = plane.ok(_propose(publication), remote_client=CLIENT_A)
    rejected = plane.operator(
        RejectScheduleBaseline(
            baseline_id=proposal["baseline_id"], reason="Synthetic", idempotency_key=_key("rej")
        )
    )
    assert rejected["status"] == "rejected" and rejected["action"] == "reject"
    revoke = RevokeScheduleBaseline(
        baseline_id=proposal["baseline_id"], reason="Synthetic", idempotency_key=_key("rev")
    )
    assert plane.refused(revoke, surface=OperatorSurface.CLI) == ("conflict", ["baseline_id"])
