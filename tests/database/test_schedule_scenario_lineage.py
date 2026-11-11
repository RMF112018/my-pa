"""Schedule Scenarios S6-3 package I10-B: lineage for schedule and scenario data.

Contract `docs/architecture/schedule-scenarios-contract.md` sections 5 and
15.11, through `ApplicationService` composed with the lineage, Work, Constraint,
Schedule and Schedule Scenarios planes over a migrated database: the 6 Schedule
families and 3 relations are admitted exactly in their section 5.2 pairs, each
with its evidence rule and its linkability (an intake publication, a proposal's
approval evidence); a withheld family (the plane off) answers as absent to a new
assertion and drops out of reads, while an existing link to it stays
confirmable and endable and its Issue closable (R8-F10); and `share_endpoint`
reads the 6 families under a role holding exactly the pre-deploy privileges
(P-check and Q8), so no `FOR SHARE` (and no `UPDATE`) is needed (S6-3-D21,
R10-F12). Publications come from the real S5 import and worker; every identity,
name and value is synthetic.
"""

from __future__ import annotations

import functools
import hashlib
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import text

from my_pa.application.commands import (
    AssertRecordAssociation,
    CloseIssue,
    ConfirmRecordAssociation,
    CreateCapture,
    CreateCommitment,
    CreateConstraintCategory,
    CreateIssue,
    CreateMeeting,
    CreatePublishedConstraint,
    CreateTask,
    EndRecordAssociation,
    ReadRecordLineage,
    ReadScheduleScenarioVersion,
    RecordScheduleScenarioOutput,
    RevokeScheduleBaseline,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import ScenarioRecordBuilders, UnitOfWork
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.lineage.vocabulary import RecordFamily
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.domain.situation.continuity import CommitmentDirection
from my_pa.domain.task.lifecycle import TaskOriginKind
from my_pa.infrastructure.database.cpm_workbench_predeploy import (
    _UPDATED_TABLES as P_CHECK_UPDATED_TABLES,
)
from my_pa.infrastructure.database.cpm_workbench_predeploy import CPM_TABLES
from my_pa.infrastructure.database.schedule_scenarios_predeploy import (
    _UPDATED_TABLE as Q8_UPDATED_TABLE,
)
from my_pa.infrastructure.database.schedule_scenarios_predeploy import PLANE_TABLES
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.commitment_management import (
    SqlAlchemyCommitmentManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.constraints import SqlAlchemyConstraintManagementUnitOfWork
from my_pa.infrastructure.persistence.record_lineage import SqlRecordLineageRepository
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
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.lineage_s3_read_harness import READS, grant
from tests.database.schedule_capability_harness import LIMITS, PRINCIPAL, ScheduleRuntime, World
from tests.database.schedule_plane_world import seed_publication
from tests.database.test_commitment_entity_counterparty import seed_counterparty_entity
from tests.database.test_schedule_scenario_capabilities import (
    _approve,
    _create,
    _key,
    _output_document,
    _propose,
    _publish,
)

pytestmark = pytest.mark.database

CLI: Final = OperatorSurface.CLI
REMOTE: Final = "synthetic-s63-lineage-client"
BODY: Final = "Decisions: the crane slips a week. Next: resequence the pour."
_STARTS: Final = datetime(2026, 10, 1, 15, tzinfo=UTC)


class LineagePlane:
    """`ApplicationService` with lineage, Work, Constraint, Schedule and the plane composed."""

    def __init__(self, rt: ScheduleRuntime, *, scenarios: bool = True) -> None:
        self.rt = rt
        engine = rt.engine
        audit = SqlAlchemyAuditSink(rt.audit_engine)

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(
                engine, audit=audit, relationship_memory_enabled=True, schedule_enabled=True
            )

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            clock=rt._clock,
            task_management_unit_of_work=lambda: SqlAlchemyTaskManagementUnitOfWork(engine),
            commitment_management_unit_of_work=lambda: SqlAlchemyCommitmentManagementUnitOfWork(
                engine
            ),
            constraint_management_unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(
                engine
            ),
            relationship_intelligence_enabled=True,
            relationship_intelligence_writes_enabled=True,
            relationship_memory_enabled=True,
            lineage_enabled=True,
            schedule_enabled=True,
            schedule_unit_of_work=lambda: SqlAlchemyScheduleUnitOfWork(engine),
            schedule_scenarios_enabled=scenarios,
            scenario_unit_of_work=lambda: SqlAlchemyScenarioUnitOfWork(engine),
            scenario_cpm_runner=functools.partial(compute_and_store_cpm_run, engine),
            scenario_record_builders=ScenarioRecordBuilders(
                new_version=new_scenario_version, new_output=new_scenario_output
            ),
        )

    def ok(self, command: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        return self.rt.ok(command, service=self.service, **kwargs)

    def refused(self, command: Any, **kwargs: Any) -> tuple[str, list[str]]:  # noqa: ANN401
        return self.rt.refused(command, service=self.service, **kwargs)


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
    return rt.world(PRINCIPAL, "s63lin")


# ---- the scene -----------------------------------------------------------------------


@dataclass(frozen=True)
class Scene:
    """One record of every family a section 5.2 pair names, and the evidence it needs."""

    refs: dict[str, str]
    meeting: str
    note: str
    capture: str
    capture_version: str
    proposal: str
    intake_publication: str
    queued_publication: str


def _sha(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _passage(passage: str) -> dict[str, object]:
    start = BODY.index(passage)
    end = start + len(passage)
    return {
        "passage_start_cp": start,
        "passage_end_cp": end,
        "passage_sha256": _sha(BODY[start:end]),
    }


def note_anchor(scene: Scene, role: str) -> dict[str, object]:
    return {
        "family": "meeting_note_version",
        "root_id": scene.meeting,
        "version_kind": "immutable_version",
        "version_id": scene.note,
        "source_sha256": _sha(BODY),
        "role": role,
        **_passage("the crane slips a week"),
    }


def capture_anchor(scene: Scene, role: str) -> dict[str, object]:
    return {
        "family": "capture_version",
        "root_id": scene.capture,
        "version_kind": "immutable_version",
        "version_id": scene.capture_version,
        "source_sha256": _sha(BODY),
        "role": role,
        **_passage("the crane slips a week"),
    }


def _constraint(plane: LineagePlane, project: str) -> str:
    with SqlAlchemyConstraintManagementUnitOfWork(plane.rt.engine) as uow:
        uow.constraints.insert_project_settings(
            PRINCIPAL,
            ConstraintProjectSettings(
                principal_id=PRINCIPAL,
                project_id=project,
                timezone_name="UTC",
                version=1,
                created_at=_STARTS,
                updated_at=_STARTS,
            ),
        )
    category = plane.ok(
        CreateConstraintCategory(project_id=project, code_segment="SCH", title="Schedule")
    )["category"]["category_id"]
    written = plane.ok(
        CreatePublishedConstraint(
            project_id=project,
            category_id=category,
            description="Synthetic crane constraint",
            date_identified=date(2026, 9, 2),
            due_date=date(2026, 9, 30),
            bic=(PartyRef(kind=PartyKind.PRINCIPAL),),
            responsible=(PartyRef(kind=PartyKind.PRINCIPAL),),
            idempotency_key=_key("constraint"),
        )
    )
    return str(written["constraint"]["constraint_id"])


def _intake_and_queued(rt: ScheduleRuntime, w: World) -> tuple[str, str]:
    """An intake Series with its one complete publication, and a queued one in a plain Series."""
    intake_series, intake = "sser_s63linintake1", "spub_s63linintake1"
    queued_series, queued = "sser_s63linqueued1", "spub_s63linqueued1"
    with rt.engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        for series, name in (
            (intake_series, "Schedule intake s63lin"),
            (queued_series, "Queued s63lin"),
        ):
            c.execute(
                text(
                    "INSERT INTO knowledge.schedule_series (series_id, principal_id, project_id, "
                    "name, name_key) VALUES (:s, :p, :j, :n, lower(:n))"
                ),
                {"s": series, "p": PRINCIPAL, "j": w.project, "n": name},
            )
        seed_publication(c, PRINCIPAL, intake, intake_series, w.project, "complete", 0)
        seed_publication(c, PRINCIPAL, queued, queued_series, w.project, "queued", 1)
        c.execute(
            text(
                "INSERT INTO knowledge.schedule_intake_series (principal_id, project_id, "
                "series_id, publication_id) VALUES (:p, :j, :s, :pub)"
            ),
            {"p": PRINCIPAL, "j": w.project, "s": intake_series, "pub": intake},
        )
    return intake, queued


def build_scene(
    rt: ScheduleRuntime, w: World, plane: LineagePlane, monkeypatch: pytest.MonkeyPatch
) -> Scene:
    publication = _publish(rt, w, monkeypatch)
    activity = str(
        rt.scalar(
            "SELECT min(schedule_activity_id) FROM knowledge.schedule_activities "
            "WHERE principal_id = :p",
            p=PRINCIPAL,
        )
    )
    created = plane.ok(_create(publication))
    version = plane.ok(ReadScheduleScenarioVersion(version_id=created["version_id"]))
    output = plane.ok(
        RecordScheduleScenarioOutput(
            document=_output_document(version), idempotency_key=_key("output")
        )
    )
    approved = plane.ok(_propose(publication), surface=CLI)
    plane.ok(_approve(baseline_id=approved["baseline_id"]), surface=CLI)
    second = _publish(rt, w, monkeypatch, data_date=date(2026, 6, 1), series_name="Second")
    proposal = plane.ok(_propose(second))
    meeting = plane.ok(
        CreateMeeting(
            title="Synthetic schedule review",
            start_at=_STARTS,
            timezone_name="UTC",
            idempotency_key=_key("meeting"),
            notes_markdown=BODY,
        )
    )["meeting"]
    captured = plane.ok(CreateCapture(text=BODY, idempotency_key=_key("capture")))
    origin = plane.ok(CreateCapture(text="Synthetic origin", idempotency_key=_key("origin")))
    commitment = plane.ok(
        CreateCommitment(
            counterparty_entity_id=seed_counterparty_entity(rt.engine, PRINCIPAL),
            direction=CommitmentDirection.OWED_BY_PRINCIPAL,
            summary="Synthetic recovery commitment",
            origin_evidence_ref=origin["capture_id"],
            idempotency_key=_key("commitment"),
        )
    )["commitment"]["commitment_id"]
    task = plane.ok(
        CreateTask(
            title="Synthetic resequencing task",
            idempotency_key=_key("task"),
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        )
    )["task"]["task_id"]
    issue = plane.ok(CreateIssue(title="Synthetic crane delay", idempotency_key=_key("issue")))
    intake, queued = _intake_and_queued(rt, w)
    return Scene(
        refs={
            "situation": str(issue["issue"]["issue_id"]),
            "task": str(task),
            "commitment": str(commitment),
            "constraint": _constraint(plane, w.project),
            "meeting": str(meeting["meeting_id"]),
            "meeting_note_version": str(meeting["notes"]["note_version_id"]),
            "capture_version": str(captured["version_id"]),
            "schedule_publication": publication,
            "schedule_activity": activity,
            "schedule_baseline": str(approved["baseline_id"]),
            "scenario": str(created["scenario_id"]),
            "scenario_version": str(created["version_id"]),
            "scenario_output": str(output["output_id"]),
        },
        meeting=str(meeting["meeting_id"]),
        note=str(meeting["notes"]["note_version_id"]),
        capture=str(captured["capture_id"]),
        capture_version=str(captured["version_id"]),
        proposal=str(proposal["baseline_id"]),
        intake_publication=intake,
        queued_publication=queued,
    )


def _anchors(scene: Scene, relation: str, to_family: str) -> tuple[dict[str, object], ...]:
    """The evidence each relation's section 5.2 rule needs.

    `concerns` has no rule, but every assertion cites 1..32 anchors (S1 7.1).
    """
    if relation in ("concerns", "delays", "mitigates"):
        return (capture_anchor(scene, "corroborates"),)
    if relation == "discusses":
        return (note_anchor(scene, "discussion"),)
    if relation == "originated_from":
        return (
            note_anchor(scene, "origin")
            if to_family == "meeting_note_version"
            else capture_anchor(scene, "origin"),
        )
    return ()


def assertion(
    relation: str,
    from_ref: tuple[str, str],
    to_ref: tuple[str, str],
    anchors: tuple[dict[str, object], ...] = (),
) -> AssertRecordAssociation:
    return AssertRecordAssociation(
        from_record={"family": from_ref[0], "record_id": from_ref[1]},
        to_record={"family": to_ref[0], "record_id": to_ref[1]},
        relation_type=relation,
        idempotency_key=_key("assert"),
        evidence_anchors=anchors,
    )


def _ref(scene: Scene, family: str) -> tuple[str, str]:
    return family, scene.refs[family]


#: Section 5.2: every pair the 5 relations admit that names a Schedule family.
ADMITTED: Final = {
    "concerns": [
        (source, target)
        for source in ("scenario", "scenario_version", "scenario_output")
        for target in (
            "situation",
            "constraint",
            "task",
            "commitment",
            "schedule_activity",
            "schedule_baseline",
        )
    ],
    "delays": [("constraint", "schedule_activity"), ("situation", "schedule_activity")],
    "mitigates": [
        (source, target)
        for source in ("task", "commitment", "scenario_version")
        for target in ("constraint", "situation")
    ],
    "discusses": [
        (source, target)
        for source in ("meeting", "meeting_note_version")
        for target in (
            "schedule_publication",
            "schedule_activity",
            "schedule_baseline",
            "scenario",
            "scenario_output",
        )
    ],
    "originated_from": [
        (source, target)
        for source in ("scenario_version", "schedule_baseline")
        for target in ("meeting_note_version", "capture_version")
    ],
}
#: One pair outside each relation's matrix row.
REFUSED_PAIR: Final = {
    "concerns": ("schedule_activity", "scenario"),
    "delays": ("schedule_activity", "constraint"),
    "mitigates": ("constraint", "task"),
    "discusses": ("meeting", "scenario_version"),
    "originated_from": ("scenario", "capture_version"),
}


@pytest.mark.parametrize(
    "case",
    [
        *ADMITTED,
        "intake_publication_refused",
        "originated_from_proposal_refused",
        "delays_without_anchor_refused",
    ],
)
def test_scenario_lineage_relations_are_admitted(
    case: str,
    rt: ScheduleRuntime,
    w: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sections 5.2 and 15.11.2: each admitted pair, its evidence rule and linkability."""
    plane = LineagePlane(rt)
    scene = build_scene(rt, w, plane, monkeypatch)
    if case in ADMITTED:
        for source, target in ADMITTED[case]:
            written = plane.ok(
                assertion(
                    case, _ref(scene, source), _ref(scene, target), _anchors(scene, case, target)
                )
            )
            association = written["association"]
            assert written["created"] is True, (case, source, target)
            assert association["relation_type"] == case
            assert association["from"] == {"family": source, "record_id": scene.refs[source]}
            assert association["to"] == {"family": target, "record_id": scene.refs[target]}
            assert association["acceptance_basis"] == "client_identified"
        # A pair outside the matrix never parses (normalization answers it,
        # before authentication, section 15.10 / S6-3-D13).
        source, target = REFUSED_PAIR[case]
        with pytest.raises(InvalidRequestError) as refused:
            assertion(case, _ref(scene, source), _ref(scene, target), _anchors(scene, case, target))
        assert refused.value.safe_details == (SafeDetail.RELATION_TYPE,)
        return
    if case == "intake_publication_refused":
        # An intake publication, or a non-terminal one, is never linkable.
        for publication in (scene.intake_publication, scene.queued_publication):
            assert plane.refused(
                assertion(
                    "discusses",
                    _ref(scene, "meeting"),
                    ("schedule_publication", publication),
                    (note_anchor(scene, "discussion"),),
                )
            ) == ("invalid_request", ["endpoint"])
        # An activity no accepted row of a complete/partial publication links
        # is not visible (S5b-1 U-03), so it is not linkable either.
        hidden = "sact_s63linhidden0001"
        with rt.engine.begin() as c:
            c.execute(text("SET LOCAL session_replication_role = replica"))
            c.execute(
                text(
                    "INSERT INTO knowledge.schedule_activities (schedule_activity_id, "
                    "principal_id, project_id, series_id, published_activity_id) SELECT :a, "
                    "principal_id, project_id, series_id, 'A999' FROM "
                    "knowledge.schedule_activities WHERE schedule_activity_id = :seen"
                ),
                {"a": hidden, "seen": scene.refs["schedule_activity"]},
            )
        assert plane.refused(
            assertion(
                "discusses",
                _ref(scene, "meeting"),
                ("schedule_activity", hidden),
                (note_anchor(scene, "discussion"),),
            )
        ) == ("invalid_request", ["endpoint"])
        # A native virtual edge is never asserted.
        with pytest.raises(InvalidRequestError) as refused:
            assertion(
                "scenario_version_of",
                _ref(scene, "scenario_version"),
                _ref(scene, "scenario"),
                (capture_anchor(scene, "corroborates"),),
            )
        assert refused.value.safe_details == (SafeDetail.RELATION_TYPE,)
    elif case == "originated_from_proposal_refused":
        evidence = (capture_anchor(scene, "origin"),)
        proposal = ("schedule_baseline", scene.proposal)
        to = _ref(scene, "capture_version")
        assert plane.refused(assertion("originated_from", proposal, to, evidence)) == (
            "invalid_request",
            ["relation_type"],
        )
        # A revoked Baseline is no longer approval evidence either.
        plane.ok(
            RevokeScheduleBaseline(
                baseline_id=scene.refs["schedule_baseline"],
                reason="Synthetic revoke",
                idempotency_key=_key("revoke"),
            ),
            surface=CLI,
        )
        assert plane.refused(
            assertion("originated_from", _ref(scene, "schedule_baseline"), to, evidence)
        ) == ("invalid_request", ["relation_type"])
        # It stays linkable by every other relation (any lifecycle state, section 5.1).
        plane.ok(
            assertion(
                "concerns",
                _ref(scene, "scenario"),
                _ref(scene, "schedule_baseline"),
                (capture_anchor(scene, "corroborates"),),
            )
        )
    else:
        situation, activity = _ref(scene, "situation"), _ref(scene, "schedule_activity")
        # A cited set with no exact `corroborates` anchor (a contradicting or a
        # discussion anchor) does not carry a causal claim.
        for role in ("contradicts", "discussion"):
            anchors = (
                capture_anchor(scene, role) if role == "contradicts" else note_anchor(scene, role),
            )
            assert plane.refused(assertion("delays", situation, activity, anchors)) == (
                "invalid_request",
                ["evidence_anchors"],
            )
        assert plane.refused(
            assertion(
                "mitigates",
                _ref(scene, "scenario_version"),
                situation,
                (capture_anchor(scene, "contradicts"),),
            )
        ) == ("invalid_request", ["evidence_anchors"])
        # `concerns` has no rule: a contradicting anchor alone is admitted.
        plane.ok(
            assertion(
                "concerns",
                _ref(scene, "scenario"),
                situation,
                (capture_anchor(scene, "contradicts"),),
            )
        )


# ---- withheld families (section 15.11.4, R8-F10) -----------------------------------------


def _lineage_nodes(plane: LineagePlane, issue: str) -> tuple[set[str], list[str]]:
    answer = plane.ok(ReadRecordLineage(origin={"family": "situation", "record_id": issue}))
    return {node["family"] for node in answer["nodes"]}, list(answer["qualifiers"])


def test_withheld_family_link_stays_confirmable_and_endable(
    rt: ScheduleRuntime, w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A link to a withheld family is confirmed or ended by its identity; the Issue closes."""
    on = LineagePlane(rt)
    scene = build_scene(rt, w, on, monkeypatch)
    issue = _ref(scene, "situation")
    cited = (capture_anchor(scene, "corroborates"),)
    confirmed = on.ok(assertion("concerns", _ref(scene, "scenario"), issue, cited))["association"]
    ended = on.ok(assertion("concerns", _ref(scene, "scenario_version"), issue, cited))[
        "association"
    ]
    families, _ = _lineage_nodes(on, issue[1])
    assert {"scenario", "scenario_version"} <= families
    off = LineagePlane(rt, scenarios=False)
    # A new assertion naming a withheld family answers as an absent one.
    assert off.refused(assertion("concerns", _ref(scene, "scenario_output"), issue, cited)) == (
        "not_found",
        ["from"],
    )
    assert off.refused(
        assertion(
            "discusses",
            _ref(scene, "meeting"),
            _ref(scene, "schedule_publication"),
            (note_anchor(scene, "discussion"),),
        )
    ) == ("not_found", ["to"])
    # So it does to a remote client granted every family read, the plane's included.
    remote = grant(*READS, "schedule_scenarios.read", "records.associations.assert")
    assert (
        on.ok(
            assertion("concerns", _ref(scene, "scenario"), _ref(scene, "task"), cited),
            remote_client=REMOTE,
            grants=remote,
        )["association"]["acceptance_basis"]
        == "client_identified"
    )
    assert off.refused(
        assertion("concerns", _ref(scene, "scenario"), _ref(scene, "commitment"), cited),
        remote_client=REMOTE,
        grants=remote,
    ) == ("not_found", ["from"])
    # Reads drop its endpoints: neither emitted nor counted, only `restricted_evidence`.
    families, qualifiers = _lineage_nodes(off, issue[1])
    assert families == {"situation"}
    assert "restricted_evidence" in qualifiers
    # The unreviewed client links hold the close (S3.1 section 4.6) ...
    issue_version = 1
    close = CloseIssue(
        issue_id=issue[1],
        expected_version=issue_version,
        idempotency_key=_key("close"),
        outcome="Resolved.",
        closure_evidence_anchors=(note_anchor(scene, "resolution"),),
    )
    assert off.refused(close, surface=CLI) == ("conflict", ["closure_gate"])
    # ... and the human channel confirms one and ends the other by identity alone.
    answer = off.ok(
        ConfirmRecordAssociation(
            link_id=confirmed["link_id"],
            expected_revision=1,
            reason="Reviewed.",
            idempotency_key=_key("confirm"),
        ),
        surface=CLI,
    )
    assert answer["association"]["acceptance_basis"] == "user_confirmed"
    assert answer["association"]["from"]["family"] == "scenario"
    answer = off.ok(
        EndRecordAssociation(
            link_id=ended["link_id"],
            expected_revision=1,
            reason="No longer relevant.",
            idempotency_key=_key("end"),
        ),
        surface=CLI,
    )
    assert answer["association"]["lifecycle_state"] == "ended"
    # The Issue was never made unclosable by the switch.
    closed = off.ok(
        CloseIssue(
            issue_id=issue[1],
            expected_version=issue_version,
            idempotency_key=_key("close"),
            outcome="Resolved.",
            closure_evidence_anchors=(note_anchor(scene, "resolution"),),
        ),
        surface=CLI,
    )
    assert closed["issue"]["state"] == "closed"


# ---- the precondition: no lock, no `UPDATE` (S6-3-D21, R10-F12) ---------------------------


#: Every family `share_endpoint` reads without a row lock.
SCHEDULE_FAMILIES: Final = (
    "schedule_publication",
    "schedule_activity",
    "schedule_baseline",
    "scenario",
    "scenario_version",
    "scenario_output",
)


@pytest.fixture
def predeploy_role(rt: ScheduleRuntime) -> Iterator[str]:
    """A role holding exactly the P-check and Q8 privileges, and schema usage."""
    role = f"s63_lineage_probe_{uuid.uuid4().hex[:12]}"
    grants = [f"GRANT USAGE ON SCHEMA knowledge TO {role}"]
    for table in CPM_TABLES:
        privileges = "SELECT, INSERT" + (", UPDATE" if table in P_CHECK_UPDATED_TABLES else "")
        grants.append(f"GRANT {privileges} ON knowledge.{table} TO {role}")
    for table in PLANE_TABLES:
        privileges = "SELECT, INSERT" + (", UPDATE" if table == Q8_UPDATED_TABLE else "")
        grants.append(f"GRANT {privileges} ON knowledge.{table} TO {role}")
    rt.execute(f"CREATE ROLE {role} NOLOGIN")
    try:
        for grant in grants:
            rt.execute(grant)
        yield role
    finally:
        rt.execute(f"DROP OWNED BY {role}")
        rt.execute(f"DROP ROLE {role}")


def test_the_probe_role_holds_no_update_on_the_five_tables(
    rt: ScheduleRuntime, predeploy_role: str
) -> None:
    """The role is the one R3-29 describes: no `UPDATE` on 5 of the 6 endpoint tables."""
    for table, update in (
        ("schedule_publications", True),
        ("schedule_activities", False),
        ("schedule_baselines", False),
        ("schedule_scenarios", False),
        ("schedule_scenario_versions", False),
        ("schedule_scenario_outputs", False),
    ):
        holds = rt.scalar(
            "SELECT has_table_privilege(:role, :table, 'UPDATE')",
            role=predeploy_role,
            table=f"knowledge.{table}",
        )
        assert holds is update, table


@pytest.mark.parametrize("family", SCHEDULE_FAMILIES)
def test_share_endpoint_needs_only_select_on_the_schedule_tables(
    family: str,
    rt: ScheduleRuntime,
    w: World,
    monkeypatch: pytest.MonkeyPatch,
    predeploy_role: str,
) -> None:
    """R10-F12: every Schedule family is shared under exactly the P-check and Q8 privileges."""
    scene = build_scene(rt, w, LineagePlane(rt), monkeypatch)
    with rt.engine.begin() as connection:
        connection.execute(text(f"SET LOCAL ROLE {predeploy_role}"))
        repository = SqlRecordLineageRepository(connection)
        endpoint = repository.share_endpoint(PRINCIPAL, RecordFamily(family), scene.refs[family])
        proposal = repository.share_endpoint(
            PRINCIPAL, RecordFamily.SCHEDULE_BASELINE, scene.proposal
        )
        intake = repository.share_endpoint(
            PRINCIPAL, RecordFamily.SCHEDULE_PUBLICATION, scene.intake_publication
        )
    assert endpoint is not None and endpoint.schedule_linkable, family
    assert endpoint.baseline_approved is (family == "schedule_baseline")
    assert proposal is not None and proposal.schedule_linkable and not proposal.baseline_approved
    assert intake is not None and not intake.schedule_linkable
