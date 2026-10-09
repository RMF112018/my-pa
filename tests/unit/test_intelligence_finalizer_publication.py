"""Synthesizer/Reporter publication rules (PCC Report Finalizer fix).

Grew out of the finalizer diagnosis characterization: every test that pinned a
branch of ``_validate_dependencies`` or the resolver keeps that branch id in its
docstring (D1-D7, S3, F1, F5, F7) and now asserts the fixed behaviour:

- P1: a Synthesizer takes one or more distinct, eligible Researcher lanes of
  its own cycle and focus; absent lanes never block ``resolve_set``.
- P2: a Synthesizer or Reporter over a partial input must itself be partial.
- P3: a Finalizer selects its cycle from ``reports.list``; a forked cycle is
  refused as the wrong cycle.
- P4: refusals carry ``dependency_report_ids`` plus one reason token.
- P5: ``succeeded`` run state requires a current artifact head.

Fixture shapes are synthetic.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date

import pytest

from my_pa.adapters.normalization import normalize
from my_pa.application.commands import (
    BeginIntelligenceCycle,
    CommitIntelligenceArtifact,
    ListIntelligenceArtifacts,
    ReadIntelligenceArtifact,
    RecordIntelligenceRunState,
    ResolveIntelligenceSet,
)
from my_pa.application.intelligence import REASON_NOT_CURRENT_HEAD, artifact_eligibility
from my_pa.application.producer_origin import ProducerOrigin
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    CYCLE_MORNING_INTELLIGENCE,
    EXPECTED_SOURCE_LANES,
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
    ProducerRunState,
    ResolverSetId,
    SourceLaneId,
)
from my_pa.domain.intelligence.models import IntelligenceArtifact
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import WHEN, Scene, build_service, metadata_for, operator

FOCUS = FocusAreaId.COMMUNICATIONS
DEPENDENCY_FIELD = "dependency_report_ids"
MISSING = (DEPENDENCY_FIELD, "dependency_missing")
WRONG_CYCLE = (DEPENDENCY_FIELD, "dependency_wrong_cycle")
WRONG_FOCUS = (DEPENDENCY_FIELD, "dependency_wrong_focus")
WRONG_STAGE = (DEPENDENCY_FIELD, "dependency_wrong_stage")
DUPLICATE_LANE = (DEPENDENCY_FIELD, "dependency_duplicate_lane")
COUNT = (DEPENDENCY_FIELD, "dependency_count")
STALE = (DEPENDENCY_FIELD, "dependency_stale")
PARTIAL_INPUT = (DEPENDENCY_FIELD, "dependency_partial_input", "artifact_state")
RUN_WITHOUT_ARTIFACT = ("selector", "run_state_without_artifact")


def run(
    service: ApplicationService, scene: Scene, purpose: Purpose, command: object
) -> ResponseEnvelope:
    return service.invoke(
        metadata_for(command.capability, purpose, scene.principal),  # type: ignore[attr-defined]
        command,  # type: ignore[arg-type]
        principal=scene.principal,
    )


def payload(envelope: ResponseEnvelope) -> dict[str, object]:
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    return envelope.result


def begin(
    service: ApplicationService,
    scene: Scene,
    key: str,
    date: str = "2026-08-20",
) -> dict[str, object]:
    return payload(
        run(
            service,
            scene,
            Purpose.REPORT_AUTHORING,
            BeginIntelligenceCycle(
                cycle_id=CYCLE_MORNING_INTELLIGENCE, business_date=date, idempotency_key=key
            ),
        )
    )


def command(
    *,
    cycle: str,
    stage: IntelligenceStage,
    kind: ArtifactKind,
    key: str,
    focus: FocusAreaId | None = FOCUS,
    lane: SourceLaneId | None = None,
    dependencies: tuple[str, ...] = (),
    state: ArtifactState = ArtifactState.FINAL,
    producer: str | None = None,
    report_date: str = "2026-08-20",
    body: str | None = None,
) -> CommitIntelligenceArtifact:
    return CommitIntelligenceArtifact(
        cycle_run_id=cycle,
        stage=stage,
        artifact_kind=kind,
        producer_task_id=producer or f"task-{key}",
        producer_task_name=f"name-{key}",
        automation_platform="abacus_chatllm",
        report_date=report_date,
        title=f"title-{key}",
        body_markdown=body if body is not None else f"body {key}",
        artifact_state=state,
        schema_version="1",
        idempotency_key=key,
        focus_area_id=focus,
        source_lane=lane,
        dependency_report_ids=dependencies,
    )


def commit_ok(service: ApplicationService, scene: Scene, cmd: CommitIntelligenceArtifact) -> str:
    report_id = payload(run(service, scene, Purpose.REPORT_AUTHORING, cmd))["report_id"]
    assert isinstance(report_id, str)
    return report_id


def collector(
    service: ApplicationService,
    scene: Scene,
    cycle: str,
    key: str,
    *,
    report_date: str = "2026-08-20",
    body: str | None = None,
) -> str:
    return commit_ok(
        service,
        scene,
        command(
            cycle=cycle,
            stage=IntelligenceStage.COLLECTOR,
            kind=ArtifactKind.COLLECTOR_CANDIDATES,
            key=key,
            report_date=report_date,
            body=body,
        ),
    )


def researcher(
    service: ApplicationService,
    scene: Scene,
    cycle: str,
    collector_id: str,
    lane: SourceLaneId,
    key: str,
    state: ArtifactState = ArtifactState.FINAL,
    report_date: str = "2026-08-20",
) -> str:
    return commit_ok(
        service,
        scene,
        command(
            cycle=cycle,
            stage=IntelligenceStage.RESEARCHER,
            kind=ArtifactKind.RESEARCH_CONTEXT,
            key=key,
            lane=lane,
            dependencies=(collector_id,),
            state=state,
            report_date=report_date,
        ),
    )


def researchers(
    service: ApplicationService, scene: Scene, cycle: str, collector_id: str, tag: str
) -> list[str]:
    return [
        researcher(service, scene, cycle, collector_id, lane, f"{tag}-{lane.value}")
        for lane in EXPECTED_SOURCE_LANES
    ]


def synth_command(
    cycle: str,
    ids: tuple[str, ...],
    key: str,
    producer: str | None = None,
    state: ArtifactState = ArtifactState.FINAL,
    report_date: str = "2026-08-20",
) -> CommitIntelligenceArtifact:
    return command(
        cycle=cycle,
        stage=IntelligenceStage.SYNTHESIZER,
        kind=ArtifactKind.SYNTHESIS_PACKAGE,
        key=key,
        dependencies=ids,
        producer=producer,
        state=state,
        report_date=report_date,
    )


def reporter_command(
    cycle: str,
    ids: tuple[str, ...],
    key: str,
    state: ArtifactState = ArtifactState.FINAL,
    report_date: str = "2026-08-20",
) -> CommitIntelligenceArtifact:
    return command(
        cycle=cycle,
        stage=IntelligenceStage.REPORTER,
        kind=ArtifactKind.FOCUS_REPORT,
        key=key,
        dependencies=ids,
        state=state,
        report_date=report_date,
    )


def assert_error(envelope: ResponseEnvelope, code: ErrorCode, *details: str) -> None:
    assert envelope.error is not None, "expected an error envelope"
    assert envelope.error.code is code
    assert envelope.error.safe_details == details


def attempt(
    service: ApplicationService, scene: Scene, cmd: CommitIntelligenceArtifact
) -> ResponseEnvelope:
    return run(service, scene, Purpose.REPORT_AUTHORING, cmd)


def resolve(
    service: ApplicationService, scene: Scene, cycle: str, set_id: ResolverSetId
) -> dict[str, object]:
    return payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ResolveIntelligenceSet(cycle_run_id=cycle, set_id=set_id, focus_area_id=FOCUS),
        )
    )


def members(resolved: dict[str, object]) -> list[dict[str, object]]:
    rows = resolved["members"]
    assert isinstance(rows, list)
    return rows


def by_lane(resolved: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(member["source_lane"]): member for member in members(resolved)}


def read(service: ApplicationService, scene: Scene, report_id: str) -> dict[str, object]:
    return payload(
        run(service, scene, Purpose.REPORT_READ, ReadIntelligenceArtifact(report_id=report_id))
    )


def fresh(scene: Scene, key: str) -> tuple[ApplicationService, str, str]:
    service = build_service(scene.world, scene.providers)
    cycle = str(begin(service, scene, key)["cycle_run_id"])
    return service, cycle, collector(service, scene, cycle, f"{key}-c")


def run_state(
    *,
    cycle: str,
    stage: IntelligenceStage,
    kind: ArtifactKind,
    state: ProducerRunState,
    key: str,
    lane: SourceLaneId | None = None,
    report_date: str = "2026-08-20",
) -> RecordIntelligenceRunState:
    return RecordIntelligenceRunState(
        cycle_run_id=cycle,
        stage=stage,
        artifact_kind=kind,
        producer_task_id=f"task-{key}",
        producer_task_name="run",
        automation_platform="abacus_chatllm",
        report_date=report_date,
        state=state,
        idempotency_key=key,
        focus_area_id=FOCUS,
        source_lane=lane,
        failure_code="source_unavailable" if state is ProducerRunState.FAILED else None,
    )


THREE = (SourceLaneId.SHAREPOINT, SourceLaneId.MY_PA, SourceLaneId.OUTLOOK)


# --- P1: one or more lanes ---------------------------------------------------


@pytest.mark.parametrize(
    "lanes",
    [(SourceLaneId.SHAREPOINT,), THREE, tuple(EXPECTED_SOURCE_LANES)],
    ids=["one", "three", "five"],
)
def test_target_lane_subset_synthesizer_then_reporter_succeeds(
    scene: Scene, lanes: tuple[SourceLaneId, ...]
) -> None:
    """Formerly the strict-xfail target (D1/D6 refused any set but all lanes)."""
    service, cycle, coll = fresh(scene, f"target{len(lanes)}")
    ids = tuple(
        researcher(service, scene, cycle, coll, lane, f"target{len(lanes)}-{lane.value}")
        for lane in lanes
    )
    resolved = resolve(service, scene, cycle, ResolverSetId.SYNTHESIZER_INPUTS)
    assert resolved["aggregate"] == "READY"
    eligible = {
        m["artifact_id"] for m in members(resolved) if m["readiness"] in {"READY", "PARTIAL"}
    }
    assert eligible == set(ids)
    synth = commit_ok(service, scene, synth_command(cycle, ids, f"target{len(lanes)}-s"))
    assert set(read(service, scene, synth)["dependency_report_ids"]) == set(ids)  # type: ignore[call-overload]
    reporter = commit_ok(service, scene, reporter_command(cycle, (synth,), f"target{len(lanes)}-r"))
    assert read(service, scene, reporter)["dependency_report_ids"] == [synth]
    assert resolve(service, scene, cycle, ResolverSetId.REPORTER_INPUT)["aggregate"] == "READY"


def test_d1_three_lanes_accepted_count_is_a_minimum(scene: Scene) -> None:
    """D1 (was ``len != REQUIRED_DEPENDENCY_COUNT[synthesizer]=5``): now a minimum of 1."""
    service, cycle, coll = fresh(scene, "d1a")
    ids = tuple(
        researcher(service, scene, cycle, coll, lane, f"d1a-{lane.value}") for lane in THREE
    )
    assert commit_ok(service, scene, synth_command(cycle, ids, "d1a-s"))


def test_d1_adding_collector_id_rejected_as_wrong_stage(scene: Scene) -> None:
    """D1 then D7 stage check: 3 researchers + the collector id is a wrong-stage dependency."""
    service, cycle, coll = fresh(scene, "d1b")
    ids = tuple(
        researcher(service, scene, cycle, coll, lane, f"d1b-{lane.value}") for lane in THREE
    )
    assert_error(
        attempt(service, scene, synth_command(cycle, (*ids, coll), "d1b-s")),
        ErrorCode.INVALID_REQUEST,
        *WRONG_STAGE,
    )


def test_synthesizer_id_given_to_synthesizer_rejected_as_wrong_stage(scene: Scene) -> None:
    """D7 stage check: a Synthesizer is not a Researcher input."""
    service, cycle, coll = fresh(scene, "ws")
    ids = tuple(researcher(service, scene, cycle, coll, lane, f"ws-{lane.value}") for lane in THREE)
    synth = commit_ok(service, scene, synth_command(cycle, ids, "ws-s"))
    assert_error(
        attempt(service, scene, synth_command(cycle, (synth,), "ws-s2")),
        ErrorCode.INVALID_REQUEST,
        *WRONG_STAGE,
    )


def test_d6_duplicate_lane_superseded_v1_and_current_v2_is_duplicate_lane(scene: Scene) -> None:
    """D6 (was the five-lane set equality): a lane named twice is ``duplicate_lane``.

    A superseded teams v1 plus the current v2: the structural duplicate-lane
    check runs before eligibility, so the answer is deterministically
    ``invalid_request``/``dependency_duplicate_lane``, never the stale conflict.
    Repeating one id is refused earlier, at command construction.
    """
    service, cycle, coll = fresh(scene, "d6")
    ids = researchers(service, scene, cycle, coll, "d6")
    teams_v2 = researcher(service, scene, cycle, coll, SourceLaneId.TEAMS, "d6-teams-v2")
    teams_v1 = ids[list(EXPECTED_SOURCE_LANES).index(SourceLaneId.TEAMS)]
    assert teams_v1 != teams_v2
    others = tuple(i for i in ids if i != teams_v1)
    assert_error(
        attempt(service, scene, synth_command(cycle, (*others, teams_v1, teams_v2), "d6-s")),
        ErrorCode.INVALID_REQUEST,
        *DUPLICATE_LANE,
    )
    # The superseded v1 alone in place of v2 is the stale conflict.
    assert_error(
        attempt(service, scene, synth_command(cycle, (*others, teams_v1), "d6-s2")),
        ErrorCode.CONFLICT,
        *STALE,
    )


def test_d7_wrong_focus_rejected(scene: Scene) -> None:
    """D7: researchers belong to another focus area."""
    service = build_service(scene.world, scene.providers)
    cycle = str(begin(service, scene, "d7")["cycle_run_id"])
    other = FocusAreaId.DECISION_APPROVAL
    coll = commit_ok(
        service,
        scene,
        command(
            cycle=cycle,
            stage=IntelligenceStage.COLLECTOR,
            kind=ArtifactKind.COLLECTOR_CANDIDATES,
            key="d7-c",
            focus=other,
        ),
    )
    ids = tuple(
        commit_ok(
            service,
            scene,
            command(
                cycle=cycle,
                stage=IntelligenceStage.RESEARCHER,
                kind=ArtifactKind.RESEARCH_CONTEXT,
                key=f"d7-{lane.value}",
                focus=other,
                lane=lane,
                dependencies=(coll,),
            ),
        )
        for lane in THREE
    )
    assert_error(
        attempt(service, scene, synth_command(cycle, ids, "d7-s")),
        ErrorCode.INVALID_REQUEST,
        *WRONG_FOCUS,
    )


def test_d3_cross_cycle_dependencies_rejected(scene: Scene) -> None:
    """D3: artifact.cycle_run_id != cycle.cycle_run_id (cycle A researchers, cycle B synth)."""
    service, cycle_a, coll = fresh(scene, "d3")
    ids = tuple(researchers(service, scene, cycle_a, coll, "d3"))
    cycle_b = str(begin(service, scene, "d3-b", date="2026-08-21")["cycle_run_id"])
    assert cycle_b != cycle_a
    assert_error(
        attempt(service, scene, synth_command(cycle_b, ids, "d3-s")),
        ErrorCode.INVALID_REQUEST,
        *WRONG_CYCLE,
    )


def test_d2_unknown_and_cross_principal_ids_rejected_as_missing(scene: Scene) -> None:
    """D2: store.get_artifact(principal, id) is None for unknown and foreign ids alike."""
    service, cycle, coll = fresh(scene, "d2")
    ids = researchers(service, scene, cycle, coll, "d2")
    unknown = (*ids[:2], issue_identifier(IdKind.INTELLIGENCE_ARTIFACT))
    assert_error(
        attempt(service, scene, synth_command(cycle, unknown, "d2-s1")),
        ErrorCode.INVALID_REQUEST,
        *MISSING,
    )
    # Cross-principal: a second principal owns its own cycle and cites the first's ids.
    other = operator()
    scene.world.producer_origins[other.principal_id] = ProducerOrigin(
        principal_id=other.principal_id,
        principal_kind=other.kind,
        method="rule",
        method_version="synthetic-rule-producer.1",
    )
    begin_cmd = BeginIntelligenceCycle(
        cycle_id=CYCLE_MORNING_INTELLIGENCE, business_date="2026-08-20", idempotency_key="d2-o"
    )
    other_cycle = service.invoke(
        metadata_for(begin_cmd.capability, Purpose.REPORT_AUTHORING, other),
        begin_cmd,
        principal=other,
    )
    other_cycle_id = str(payload(other_cycle)["cycle_run_id"])
    foreign = synth_command(other_cycle_id, tuple(ids), "d2-s2")
    envelope = service.invoke(
        metadata_for(foreign.capability, Purpose.REPORT_AUTHORING, other),
        foreign,
        principal=other,
    )
    assert_error(envelope, ErrorCode.INVALID_REQUEST, *MISSING)


@pytest.mark.parametrize("producer", ["task-anything", "x", "some other automation"])
def test_producer_identity_not_checked(scene: Scene, producer: str) -> None:
    """F7 / producer: task id/name is not a rejection branch."""
    service, cycle, coll = fresh(scene, f"prod-{producer[:1]}{len(producer)}")
    ids = tuple(researchers(service, scene, cycle, coll, f"p{len(producer)}"))
    key = f"prod-s-{len(producer)}"
    report = commit_ok(service, scene, synth_command(cycle, ids, key, producer=producer))
    assert report


@pytest.mark.parametrize(
    ("purpose", "principal_kind"),
    [
        (Purpose.REPORT_READ, PrincipalKind.OPERATOR),
        (Purpose.REPORT_AUTHORING, PrincipalKind.CLOUD_MODEL_PROVIDER),
    ],
    ids=["read-purpose", "model-principal"],
)
def test_unauthorized_producer_is_refused_before_any_write(
    scene: Scene, purpose: Purpose, principal_kind: PrincipalKind
) -> None:
    """Authorization is the (capability, purpose) grant and principal kind, not producer text.

    A ``reports.commit`` under a purpose that does not permit it, or from a
    principal that may not hold authority, is refused and writes nothing.
    """
    service, cycle, coll = fresh(scene, f"unauth-{principal_kind.value}")
    ids = tuple(
        researcher(service, scene, cycle, coll, lane, f"unauth-{principal_kind.value}-{lane}")
        for lane in THREE
    )
    store = scene.world.intelligence
    before = (len(store.artifacts), len(store.runs), len(store.receipts))
    principal = (
        scene.principal
        if principal_kind is PrincipalKind.OPERATOR
        else Principal(
            principal_id=scene.principal.principal_id, kind=principal_kind, authenticated=True
        )
    )
    cmd = synth_command(cycle, ids, f"unauth-{principal_kind.value}-s")
    envelope = service.invoke(
        metadata_for(cmd.capability, purpose, principal), cmd, principal=principal
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.DENIED
    assert (len(store.artifacts), len(store.runs), len(store.receipts)) == before


def test_omitted_dependency_ids_rejected_as_count(scene: Scene) -> None:
    """D1: omitted dependency_report_ids -> () -> ``dependency_count``, in-process and wire."""
    service, cycle, _coll = fresh(scene, "omit")
    assert_error(
        attempt(service, scene, synth_command(cycle, (), "omit-s")),
        ErrorCode.INVALID_REQUEST,
        *COUNT,
    )
    body: dict[str, object] = {
        "cycle_run_id": cycle,
        "stage": "synthesizer",
        "artifact_kind": "synthesis_package",
        "focus_area_id": FOCUS.value,
        "producer_task_id": "task-omit-wire",
        "producer_task_name": "Synthesizer",
        "automation_platform": "abacus_chatllm",
        "report_date": "2026-08-20",
        "title": "Synthesis",
        "body_markdown": "synthesis",
        "artifact_state": "final",
        "schema_version": "1",
        "idempotency_key": "omit-wire",
    }
    assert "dependency_report_ids" not in body
    metadata, wire_cmd = normalize(
        Capability.REPORTS_COMMIT.value,
        {
            "request_id": "req-omit",
            "purpose": Purpose.REPORT_AUTHORING.value,
            "principal_id": scene.principal.principal_id,
            "requested_at": "2026-08-20T12:00:00Z",
            "payload": body,
        },
    )
    assert isinstance(wire_cmd, CommitIntelligenceArtifact)
    assert wire_cmd.dependency_report_ids == ()
    envelope = service.invoke(metadata, wire_cmd, principal=scene.principal)
    assert_error(envelope, ErrorCode.INVALID_REQUEST, *COUNT)


def test_reporter_dependency_count_and_stage(scene: Scene) -> None:
    """Reporter: exactly one dependency, and it must be the Synthesizer."""
    service, cycle, coll = fresh(scene, "rc")
    ids = tuple(researcher(service, scene, cycle, coll, lane, f"rc-{lane.value}") for lane in THREE)
    synth = commit_ok(service, scene, synth_command(cycle, ids, "rc-s"))
    assert_error(
        attempt(service, scene, reporter_command(cycle, (), "rc-r0")),
        ErrorCode.INVALID_REQUEST,
        *COUNT,
    )
    assert_error(
        attempt(service, scene, reporter_command(cycle, (synth, ids[0]), "rc-r2")),
        ErrorCode.INVALID_REQUEST,
        *COUNT,
    )
    assert_error(
        attempt(service, scene, reporter_command(cycle, (ids[0],), "rc-rw")),
        ErrorCode.INVALID_REQUEST,
        *WRONG_STAGE,
    )


def test_s3_collector_recommit_stales_researchers(scene: Scene) -> None:
    """S3: a re-committed collector stales the researchers; commit is a CONFLICT."""
    service, cycle, coll = fresh(scene, "s3")
    ids = tuple(researchers(service, scene, cycle, coll, "s3"))
    before = resolve(service, scene, cycle, ResolverSetId.SYNTHESIZER_INPUTS)
    assert before["aggregate"] == "READY"
    collector(service, scene, cycle, "s3-c2")
    for set_id in (ResolverSetId.RESEARCH_SWARM, ResolverSetId.SYNTHESIZER_INPUTS):
        resolved = resolve(service, scene, cycle, set_id)
        assert resolved["aggregate"] == "BLOCKED"
        assert [m["readiness"] for m in members(resolved)] == ["STALE"] * 5
        assert {m["readiness_reason"] for m in members(resolved)} == {"stale_upstream"}
        assert {m["required"] for m in members(resolved)} == {False}
    assert_error(
        attempt(service, scene, synth_command(cycle, ids, "s3-s")),
        ErrorCode.CONFLICT,
        *STALE,
    )


def test_n4_researcher_naming_a_replaced_collector_is_stale(scene: Scene) -> None:
    """A Researcher commit naming a Collector that is no longer the head is refused."""
    service, cycle, coll = fresh(scene, "n4")
    collector(service, scene, cycle, "n4-c2")
    assert_error(
        attempt(
            service,
            scene,
            command(
                cycle=cycle,
                stage=IntelligenceStage.RESEARCHER,
                kind=ArtifactKind.RESEARCH_CONTEXT,
                key="n4-r",
                lane=SourceLaneId.SHAREPOINT,
                dependencies=(coll,),
            ),
        ),
        ErrorCode.CONFLICT,
        *STALE,
    )


def _store_row(scene: Scene, artifact_id: str) -> tuple[tuple[str, str], IntelligenceArtifact]:
    key = (scene.principal.principal_id, artifact_id)
    return key, scene.world.intelligence.artifacts[key]


@pytest.mark.parametrize("state", [ArtifactState.SUPERSEDED, ArtifactState.REJECTED])
def test_n3a_state_guard_alone_refuses_a_current_non_consumable_row(
    scene: Scene, state: ArtifactState
) -> None:
    """Isolates the state guard: the row is still the current head, only its state differs."""
    tag = f"n3a-{state.value}"
    service, cycle, coll = fresh(scene, tag)
    bad = researcher(service, scene, cycle, coll, SourceLaneId.SHAREPOINT, f"{tag}-bad")
    good = researcher(service, scene, cycle, coll, SourceLaneId.MY_PA, f"{tag}-good")
    key, row = _store_row(scene, bad)
    scene.world.intelligence.artifacts[key] = replace(row, artifact_state=state)
    stored = scene.world.intelligence.artifacts[key]
    assert stored.is_current and stored.artifact_state is state
    verdict = artifact_eligibility(
        scene.world.intelligence,
        principal_id=scene.principal.principal_id,
        cycle_run_id=cycle,
        artifact=stored,
    )
    assert (verdict.state.value, verdict.reason, verdict.eligible) == (
        "SUPERSEDED",
        "superseded",
        False,
    )
    resolved = resolve(service, scene, cycle, ResolverSetId.SYNTHESIZER_INPUTS)
    member = by_lane(resolved)["sharepoint"]
    assert (member["readiness"], member["readiness_reason"]) == ("SUPERSEDED", "superseded")
    assert member["artifact_id"] == bad
    assert by_lane(resolved)["my_pa"]["readiness"] == "READY"
    assert_error(
        attempt(service, scene, synth_command(cycle, (bad, good), f"{tag}-s")),
        ErrorCode.CONFLICT,
        *STALE,
    )


def test_n3b_current_head_guard_alone_refuses_a_final_non_head_row(scene: Scene) -> None:
    """Isolates the head guard: a FINAL row, not current, while a v2 is the coordinate head."""
    service, cycle, coll = fresh(scene, "n3b")
    v1 = researcher(service, scene, cycle, coll, SourceLaneId.SHAREPOINT, "n3b-v1")
    v2 = researcher(service, scene, cycle, coll, SourceLaneId.SHAREPOINT, "n3b-v2")
    assert store_head_id(scene, cycle) == v2
    key, row = _store_row(scene, v1)
    scene.world.intelligence.artifacts[key] = replace(
        row, artifact_state=ArtifactState.FINAL, is_current=False
    )
    stored = scene.world.intelligence.artifacts[key]
    assert stored.artifact_state is ArtifactState.FINAL and not stored.is_current
    verdict = artifact_eligibility(
        scene.world.intelligence,
        principal_id=scene.principal.principal_id,
        cycle_run_id=cycle,
        artifact=stored,
    )
    assert (verdict.state.value, verdict.reason, verdict.eligible) == (
        "STALE",
        REASON_NOT_CURRENT_HEAD,
        False,
    )
    assert_error(
        attempt(service, scene, synth_command(cycle, (v1,), "n3b-s")),
        ErrorCode.CONFLICT,
        *STALE,
    )
    assert commit_ok(service, scene, synth_command(cycle, (v2,), "n3b-s2"))


def test_supersedes_mismatch_keeps_artifact_id_token(scene: Scene) -> None:
    """The non-dependency stale reference (``supersedes_artifact_id``) keeps ``artifact_id``."""
    service, cycle, coll = fresh(scene, "sup")
    collector(service, scene, cycle, "sup-c2")
    cmd = CommitIntelligenceArtifact(
        cycle_run_id=cycle,
        stage=IntelligenceStage.COLLECTOR,
        artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES,
        producer_task_id="sup",
        producer_task_name="sup",
        automation_platform="abacus_chatllm",
        report_date="2026-08-20",
        title="sup",
        body_markdown="sup",
        artifact_state=ArtifactState.FINAL,
        schema_version="1",
        idempotency_key="sup-c3",
        focus_area_id=FOCUS,
        supersedes_artifact_id=coll,
    )
    assert_error(attempt(service, scene, cmd), ErrorCode.CONFLICT, "artifact_id")


def test_begin_cycle_replay_semantics(scene: Scene) -> None:
    """Replay only on identical payload+key; business_date change needs a new key."""
    service, cycle, coll = fresh(scene, "replay")
    ids = tuple(researchers(service, scene, cycle, coll, "replay"))
    again = begin(service, scene, "replay")
    assert again["cycle_run_id"] == cycle
    assert again["replayed"] is True
    assert again["created"] is False
    resolved = resolve(service, scene, cycle, ResolverSetId.SYNTHESIZER_INPUTS)
    assert resolved["aggregate"] == "READY"
    assert {m["artifact_id"] for m in members(resolved)} == set(ids)
    other = begin(service, scene, "replay-2", date="2026-08-21")
    assert other["cycle_run_id"] != cycle
    assert other["created"] is True


# --- P2: partial is allowed and marked ---------------------------------------


def test_resolver_and_validator_agree_on_partial(scene: Scene) -> None:
    """Was the PARTIAL disagreement: resolver DEGRADED, commit must claim partial."""
    service, cycle, coll = fresh(scene, "partial")
    ids = [
        researcher(
            service,
            scene,
            cycle,
            coll,
            lane,
            f"partial-{lane.value}",
            state=ArtifactState.PARTIAL if lane is SourceLaneId.TEAMS else ArtifactState.FINAL,
        )
        for lane in EXPECTED_SOURCE_LANES
    ]
    resolved = resolve(service, scene, cycle, ResolverSetId.SYNTHESIZER_INPUTS)
    assert resolved["aggregate"] == "DEGRADED"
    teams = by_lane(resolved)["teams"]
    assert teams["readiness"] == "PARTIAL"
    assert teams["readiness_reason"] == "eligible_partial"
    assert_error(
        attempt(service, scene, synth_command(cycle, tuple(ids), "partial-s-final")),
        ErrorCode.INVALID_REQUEST,
        *PARTIAL_INPUT,
    )
    synth = commit_ok(
        service,
        scene,
        synth_command(cycle, tuple(ids), "partial-s", state=ArtifactState.PARTIAL),
    )
    assert read(service, scene, synth)["artifact_state"] == "partial"


def test_partial_claim_over_final_inputs_is_allowed(scene: Scene) -> None:
    service, cycle, coll = fresh(scene, "pf")
    ids = tuple(researcher(service, scene, cycle, coll, lane, f"pf-{lane.value}") for lane in THREE)
    assert commit_ok(service, scene, synth_command(cycle, ids, "pf-s", state=ArtifactState.PARTIAL))


def test_reporter_over_partial_synthesizer_must_be_partial(scene: Scene) -> None:
    service, cycle, coll = fresh(scene, "rp")
    ids = tuple(researcher(service, scene, cycle, coll, lane, f"rp-{lane.value}") for lane in THREE)
    synth = commit_ok(
        service, scene, synth_command(cycle, ids, "rp-s", state=ArtifactState.PARTIAL)
    )
    reporter_input = resolve(service, scene, cycle, ResolverSetId.REPORTER_INPUT)
    assert reporter_input["aggregate"] == "DEGRADED"
    assert members(reporter_input)[0]["readiness"] == "PARTIAL"
    assert members(reporter_input)[0]["required"] is True
    assert_error(
        attempt(service, scene, reporter_command(cycle, (synth,), "rp-r-final")),
        ErrorCode.INVALID_REQUEST,
        *PARTIAL_INPUT,
    )
    assert commit_ok(
        service,
        scene,
        reporter_command(cycle, (synth,), "rp-r", state=ArtifactState.PARTIAL),
    )


# --- resolver: absent lanes never block ----------------------------------------


def test_absent_failed_and_partial_run_lanes_are_non_blocking(scene: Scene) -> None:
    service, cycle, coll = fresh(scene, "nb")
    for lane in THREE:
        researcher(service, scene, cycle, coll, lane, f"nb-{lane.value}")
    payload(
        run(
            service,
            scene,
            Purpose.REPORT_AUTHORING,
            run_state(
                cycle=cycle,
                stage=IntelligenceStage.RESEARCHER,
                kind=ArtifactKind.RESEARCH_CONTEXT,
                state=ProducerRunState.FAILED,
                key="nb-teams-fail",
                lane=SourceLaneId.TEAMS,
            ),
        )
    )
    payload(
        run(
            service,
            scene,
            Purpose.REPORT_AUTHORING,
            run_state(
                cycle=cycle,
                stage=IntelligenceStage.RESEARCHER,
                kind=ArtifactKind.RESEARCH_CONTEXT,
                state=ProducerRunState.PARTIAL,
                key="nb-onedrive-partial",
                lane=SourceLaneId.ONEDRIVE,
            ),
        )
    )
    for set_id in (ResolverSetId.RESEARCH_SWARM, ResolverSetId.SYNTHESIZER_INPUTS):
        resolved = resolve(service, scene, cycle, set_id)
        assert resolved["aggregate"] == "READY"
        lanes = by_lane(resolved)
        assert {lane: m["readiness"] for lane, m in lanes.items()} == {
            "sharepoint": "READY",
            "my_pa": "READY",
            "outlook": "READY",
            "teams": "FAILED",
            "onedrive": "MISSING",
        }
        assert lanes["teams"]["readiness_reason"] == "failed"
        assert lanes["onedrive"]["readiness_reason"] == "partial_run_without_artifact"
        assert lanes["sharepoint"]["readiness_reason"] == "ready"
        assert all(m["required"] is False for m in lanes.values())
    empty_service, empty_cycle, _ = fresh(scene, "nb-empty")
    absent = resolve(empty_service, scene, empty_cycle, ResolverSetId.SYNTHESIZER_INPUTS)
    assert absent["aggregate"] == "BLOCKED"
    assert {m["readiness_reason"] for m in members(absent)} == {"absent"}


# --- P5: succeeded requires an artifact ---------------------------------------


def test_f5_succeeded_without_artifact_is_refused(scene: Scene) -> None:
    """F5 (was: SUCCEEDED accepted with no artifact). Now refused; commit-then-succeeded holds."""
    service, cycle, coll = fresh(scene, "f5")
    succeeded = run_state(
        cycle=cycle,
        stage=IntelligenceStage.SYNTHESIZER,
        kind=ArtifactKind.SYNTHESIS_PACKAGE,
        state=ProducerRunState.SUCCEEDED,
        key="f5-run",
    )
    store = scene.world.intelligence
    before = (len(store.runs), len(store.receipts))
    assert_error(
        run(service, scene, Purpose.REPORT_AUTHORING, succeeded),
        ErrorCode.INVALID_REQUEST,
        *RUN_WITHOUT_ARTIFACT,
    )
    assert (len(store.runs), len(store.receipts)) == before
    # A head at another coordinate does not count: the researcher lane is exact.
    researcher(service, scene, cycle, coll, SourceLaneId.SHAREPOINT, "f5-sp")
    assert_error(
        run(
            service,
            scene,
            Purpose.REPORT_AUTHORING,
            run_state(
                cycle=cycle,
                stage=IntelligenceStage.RESEARCHER,
                kind=ArtifactKind.RESEARCH_CONTEXT,
                state=ProducerRunState.SUCCEEDED,
                key="f5-outlook",
                lane=SourceLaneId.OUTLOOK,
            ),
        ),
        ErrorCode.INVALID_REQUEST,
        *RUN_WITHOUT_ARTIFACT,
    )
    # Production ordering: commit first, then succeeded.
    commit_ok(service, scene, synth_command(cycle, (store_head_id(scene, cycle),), "f5-s"))
    recorded = payload(run(service, scene, Purpose.REPORT_AUTHORING, succeeded))
    assert recorded["state"] == "succeeded"
    assert recorded["created"] is True
    # Non-succeeded states still need no artifact.
    failed = run_state(
        cycle=cycle,
        stage=IntelligenceStage.RESEARCHER,
        kind=ArtifactKind.RESEARCH_CONTEXT,
        state=ProducerRunState.FAILED,
        key="f5-teams-fail",
        lane=SourceLaneId.TEAMS,
    )
    assert payload(run(service, scene, Purpose.REPORT_AUTHORING, failed))["state"] == "failed"


def store_head_id(scene: Scene, cycle: str) -> str:
    head = scene.world.intelligence.current_head(
        scene.principal.principal_id,
        cycle,
        IntelligenceStage.RESEARCHER,
        FOCUS,
        SourceLaneId.SHAREPOINT,
    )
    assert head is not None
    return head.artifact_id


def test_f5_stored_receipt_replays_before_the_artifact_guard(scene: Scene) -> None:
    """The guard runs on new receipts only: a stored receipt replays even if the head is gone."""
    service, cycle, coll = fresh(scene, "f5r")
    report = researcher(service, scene, cycle, coll, SourceLaneId.OUTLOOK, "f5r-outlook")
    succeeded = run_state(
        cycle=cycle,
        stage=IntelligenceStage.RESEARCHER,
        kind=ArtifactKind.RESEARCH_CONTEXT,
        state=ProducerRunState.SUCCEEDED,
        key="f5r-run",
        lane=SourceLaneId.OUTLOOK,
    )
    first = payload(run(service, scene, Purpose.REPORT_AUTHORING, succeeded))
    assert first["created"] is True
    # Remove the head behind the service's back: only a replay can still succeed.
    del scene.world.intelligence.artifacts[(scene.principal.principal_id, report)]
    again = payload(run(service, scene, Purpose.REPORT_AUTHORING, succeeded))
    assert again["replayed"] is True
    assert again["report_run_id"] == first["report_run_id"]


# --- lifecycle replay and idempotency -----------------------------------------


def test_identical_synthesizer_and_reporter_commits_replay_without_duplicates(
    scene: Scene,
) -> None:
    service, cycle, coll = fresh(scene, "life")
    ids = tuple(
        researcher(service, scene, cycle, coll, lane, f"life-{lane.value}") for lane in THREE
    )
    store = scene.world.intelligence

    def upstream_snapshot() -> dict[str, tuple[int, bool, str]]:
        return {
            artifact_id: (artifact.version, artifact.is_current, artifact.content_sha256)
            for (_, artifact_id), artifact in store.artifacts.items()
            if artifact_id in {coll, *ids}
        }

    upstream_before = upstream_snapshot()
    synth_cmd = synth_command(cycle, ids, "life-s")
    synth = payload(attempt(service, scene, synth_cmd))
    reporter_cmd = reporter_command(cycle, (str(synth["report_id"]),), "life-r")
    reporter = payload(attempt(service, scene, reporter_cmd))
    counts = (len(store.artifacts), len(store.runs), len(store.receipts))
    synth_again = payload(attempt(service, scene, synth_cmd))
    reporter_again = payload(attempt(service, scene, reporter_cmd))
    assert synth_again["replayed"] is True
    assert reporter_again["replayed"] is True
    assert synth_again["report_id"] == synth["report_id"]
    assert reporter_again["report_id"] == reporter["report_id"]
    assert (len(store.artifacts), len(store.runs), len(store.receipts)) == counts
    assert upstream_snapshot() == upstream_before
    assert len(upstream_before) == 4


# --- P3: cycle selection --------------------------------------------------------


def test_p3_cycle_selection_by_list_and_forked_cycle_refused(scene: Scene) -> None:
    """F1/M2: a Finalizer selects the one current cycle from ``reports.list``.

    A forked empty cycle for the same date never appears in the researcher
    listing, and a Synthesizer committed into it with the real cycle's
    researchers is refused as the wrong cycle.
    """
    service = build_service(scene.world, scene.providers)
    day = "2026-08-20"
    real = str(begin(service, scene, "p3-real", date=day)["cycle_run_id"])
    coll = collector(service, scene, real, "p3-c")
    ids = tuple(researcher(service, scene, real, coll, lane, f"p3-{lane.value}") for lane in THREE)
    forked = payload(
        run(
            service,
            scene,
            Purpose.REPORT_AUTHORING,
            BeginIntelligenceCycle(
                cycle_id=CYCLE_MORNING_INTELLIGENCE,
                business_date=day,
                idempotency_key="p3-fork",
                automation_platform="abacusai_agent",
                external_orchestration_id="pcc_report_finalizer_fork",
            ),
        )
    )
    forked_id = str(forked["cycle_run_id"])
    assert forked["created"] is True
    assert forked_id != real
    listed = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ListIntelligenceArtifacts(
                stage=IntelligenceStage.RESEARCHER, focus_area_id=FOCUS, report_date=day
            ),
        )
    )
    items = listed["items"]
    assert isinstance(items, list)
    assert {item["cycle_run_id"] for item in items} == {real}
    assert {item["report_id"] for item in items} == set(ids)
    assert_error(
        attempt(service, scene, synth_command(forked_id, ids, "p3-s-fork")),
        ErrorCode.INVALID_REQUEST,
        *WRONG_CYCLE,
    )
    assert commit_ok(service, scene, synth_command(real, ids, "p3-s"))


def test_unknown_cycle_reports_stage_field(scene: Scene) -> None:
    """commit_artifact: store.get_cycle is None -> IntelligenceCoordinateError -> field stage."""
    service = build_service(scene.world, scene.providers)
    assert_error(
        attempt(
            service,
            scene,
            synth_command(issue_identifier(IdKind.INTELLIGENCE_CYCLE_RUN), (), "nocycle"),
        ),
        ErrorCode.INVALID_REQUEST,
        "stage",
    )


def test_f1_begin_cycle_with_different_platform_and_external_root_forks_new_cycle(
    scene: Scene,
) -> None:
    """F1: platform/external root are in the fingerprint; a new key forks a new cycle."""
    service = build_service(scene.world, scene.providers)

    def begin_with(key: str, date: str, platform: str, root: str | None) -> ResponseEnvelope:
        return run(
            service,
            scene,
            Purpose.REPORT_AUTHORING,
            BeginIntelligenceCycle(
                cycle_id=CYCLE_MORNING_INTELLIGENCE,
                business_date=date,
                idempotency_key=key,
                automation_platform=platform,
                external_orchestration_id=root,
            ),
        )

    first = payload(begin_with("f1-a", "2026-08-20", "p1", None))
    second = payload(begin_with("f1-b", "2026-08-20", "p2", "root-x"))
    assert first["cycle_run_id"] != second["cycle_run_id"]
    assert second["created"] is True
    assert second["replayed"] is False
    resolved = resolve(
        service, scene, str(second["cycle_run_id"]), ResolverSetId.SYNTHESIZER_INPUTS
    )
    assert resolved["aggregate"] == "BLOCKED"
    assert {m["readiness"] for m in members(resolved)} == {"MISSING"}
    replay = payload(begin_with("f1-b", "2026-08-20", "p2", "root-x"))
    assert replay["cycle_run_id"] == second["cycle_run_id"]
    assert replay["replayed"] is True
    # intelligence.py begin_cycle: cycle_for_external_root bound -> IntelligenceConflictError.
    assert_error(
        begin_with("f1-c", "2026-08-21", "p2", "root-x"), ErrorCode.CONFLICT, "cycle_run_id"
    )


def test_stale_derives_only_from_collector_supersession_not_time(scene: Scene) -> None:
    """Staleness is lineage-only. The service clock is fixed (conftest build_service
    ``clock=lambda: WHEN``, 2026-08-02) and has no injection hook, so time cannot be
    advanced; instead report_date is set far in the past relative to the clock and
    relative to the cycle's business_date, which must change nothing.
    """
    service = build_service(scene.world, scene.providers)
    cycle = str(begin(service, scene, "tm")["cycle_run_id"])
    old = "2026-01-01"
    coll = collector(service, scene, cycle, "tm-c", report_date=old)
    for lane in THREE:
        researcher(service, scene, cycle, coll, lane, f"tm-{lane.value}", report_date=old)

    def readiness() -> dict[str, str]:
        resolved = resolve(service, scene, cycle, ResolverSetId.SYNTHESIZER_INPUTS)
        return {str(m["source_lane"]): str(m["readiness"]) for m in members(resolved)}

    expected = {lane.value: "READY" for lane in THREE} | {"onedrive": "MISSING", "teams": "MISSING"}
    assert readiness() == expected
    for lane in (SourceLaneId.ONEDRIVE, SourceLaneId.TEAMS):
        payload(
            run(
                service,
                scene,
                Purpose.REPORT_AUTHORING,
                run_state(
                    cycle=cycle,
                    stage=IntelligenceStage.RESEARCHER,
                    kind=ArtifactKind.RESEARCH_CONTEXT,
                    state=ProducerRunState.FAILED,
                    key=f"tm-fail-{lane.value}",
                    lane=lane,
                    report_date=old,
                ),
            )
        )
    failed = {lane.value: "READY" for lane in THREE} | {"onedrive": "FAILED", "teams": "FAILED"}
    assert readiness() == failed
    collector(service, scene, cycle, "tm-c2", report_date=old)
    stale = {lane.value: "STALE" for lane in THREE} | {"onedrive": "FAILED", "teams": "FAILED"}
    assert readiness() == stale


def test_f7_producer_task_id_shared_across_stages(scene: Scene) -> None:
    """F7: the same producer_task_id commits a collector and a synthesizer (no stage binding)."""
    service = build_service(scene.world, scene.providers)
    cycle = str(begin(service, scene, "f7")["cycle_run_id"])
    shared = "shared-task"
    coll = commit_ok(
        service,
        scene,
        command(
            cycle=cycle,
            stage=IntelligenceStage.COLLECTOR,
            kind=ArtifactKind.COLLECTOR_CANDIDATES,
            key="f7-c",
            producer=shared,
        ),
    )
    ids = tuple(researchers(service, scene, cycle, coll, "f7"))
    assert commit_ok(service, scene, synth_command(cycle, ids, "f7-s", producer=shared))


# --- agreement: resolve_set eligibility == commit acceptance -------------------

#: Per-lane scenario specs. ``stale`` lanes are committed against a collector
#: that is then superseded; ``superseded`` lanes have a v1 replaced by a fresh
#: v2 (the v2 head is eligible, the v1 is the ineligible artifact).
LaneSpec = str


@dataclass(frozen=True)
class Built:
    service: ApplicationService
    cycle: str
    stale_heads: tuple[str, ...]
    superseded: tuple[str, ...]


def build_scenario(scene: Scene, tag: str, spec: dict[SourceLaneId, LaneSpec]) -> Built:
    service, cycle, coll_v1 = fresh(scene, tag)
    stale_heads = tuple(
        researcher(service, scene, cycle, coll_v1, lane, f"{tag}-{lane.value}-stale")
        for lane, kind in spec.items()
        if kind == "stale"
    )
    coll = collector(service, scene, cycle, f"{tag}-c2") if stale_heads else coll_v1
    superseded: list[str] = []
    for lane, kind in spec.items():
        if kind in {"final", "partial"}:
            researcher(
                service,
                scene,
                cycle,
                coll,
                lane,
                f"{tag}-{lane.value}",
                state=ArtifactState.PARTIAL if kind == "partial" else ArtifactState.FINAL,
            )
        elif kind == "superseded":
            superseded.append(researcher(service, scene, cycle, coll, lane, f"{tag}-{lane}-v1"))
            researcher(service, scene, cycle, coll, lane, f"{tag}-{lane.value}-v2")
        elif kind in {"failed", "partial_run"}:
            payload(
                run(
                    service,
                    scene,
                    Purpose.REPORT_AUTHORING,
                    run_state(
                        cycle=cycle,
                        stage=IntelligenceStage.RESEARCHER,
                        kind=ArtifactKind.RESEARCH_CONTEXT,
                        state=ProducerRunState.FAILED
                        if kind == "failed"
                        else ProducerRunState.PARTIAL,
                        key=f"{tag}-{lane.value}-run",
                        lane=lane,
                    ),
                )
            )
    return Built(service, cycle, stale_heads, tuple(superseded))


SCENARIOS: dict[str, dict[SourceLaneId, LaneSpec]] = {
    "mixed": {
        SourceLaneId.SHAREPOINT: "final",
        SourceLaneId.MY_PA: "partial",
        SourceLaneId.OUTLOOK: "stale",
        SourceLaneId.ONEDRIVE: "failed",
        SourceLaneId.TEAMS: "absent",
    },
    "superseded-and-partial-run": {
        SourceLaneId.SHAREPOINT: "superseded",
        SourceLaneId.MY_PA: "final",
        SourceLaneId.OUTLOOK: "final",
        SourceLaneId.ONEDRIVE: "partial_run",
        SourceLaneId.TEAMS: "stale",
    },
    "all-final": dict.fromkeys(EXPECTED_SOURCE_LANES, "final"),
    "only-partial": {SourceLaneId.TEAMS: "partial", SourceLaneId.OUTLOOK: "failed"},
    "none-eligible": {
        SourceLaneId.SHAREPOINT: "stale",
        SourceLaneId.MY_PA: "failed",
        SourceLaneId.OUTLOOK: "partial_run",
    },
}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_resolver_eligible_set_equals_synthesizer_commit_acceptance(
    scene: Scene, name: str
) -> None:
    spec = SCENARIOS[name]
    tag = f"ag-{name}"
    built = build_scenario(scene, tag, spec)
    service, cycle = built.service, built.cycle
    resolved = resolve(service, scene, cycle, ResolverSetId.SYNTHESIZER_INPUTS)
    rows = members(resolved)
    eligible = [m for m in rows if m["readiness"] in {"READY", "PARTIAL"}]
    eligible_ids = tuple(str(m["artifact_id"]) for m in eligible)
    assert {m["source_lane"] for m in eligible} == {
        lane.value for lane, kind in spec.items() if kind in {"final", "partial", "superseded"}
    }
    any_partial = any(m["readiness"] == "PARTIAL" for m in eligible)
    expected_aggregate = "BLOCKED" if not eligible else "DEGRADED" if any_partial else "READY"
    assert resolved["aggregate"] == expected_aggregate
    # Ineligible members with an artifact are exactly the stale heads.
    ineligible_heads = {
        str(m["artifact_id"])
        for m in rows
        if m["readiness"] not in {"READY", "PARTIAL"} and m["artifact_id"] is not None
    }
    assert ineligible_heads == set(built.stale_heads)
    state = ArtifactState.PARTIAL if any_partial else ArtifactState.FINAL
    if not eligible_ids:
        assert_error(
            attempt(service, scene, synth_command(cycle, (), f"{tag}-empty")),
            ErrorCode.INVALID_REQUEST,
            *COUNT,
        )
    # Each eligible member alone is accepted (subset closure).
    for index, member in enumerate(eligible):
        alone_state = (
            ArtifactState.PARTIAL if member["readiness"] == "PARTIAL" else ArtifactState.FINAL
        )
        assert commit_ok(
            service,
            scene,
            synth_command(
                cycle, (str(member["artifact_id"]),), f"{tag}-alone-{index}", state=alone_state
            ),
        )
    # Each ineligible artifact, added alone to the eligible set, is refused as stale.
    for index, bad in enumerate((*built.stale_heads, *built.superseded)):
        base = tuple(
            artifact_id
            for artifact_id in eligible_ids
            if bad not in built.superseded or lane_of(scene, artifact_id) != lane_of(scene, bad)
        )
        assert_error(
            attempt(
                service,
                scene,
                synth_command(cycle, (*base, bad), f"{tag}-bad-{index}", state=state),
            ),
            ErrorCode.CONFLICT,
            *STALE,
        )
    if eligible_ids:
        assert commit_ok(
            service, scene, synth_command(cycle, eligible_ids, f"{tag}-s", state=state)
        )


def lane_of(scene: Scene, artifact_id: str) -> SourceLaneId | None:
    artifact = scene.world.intelligence.get_artifact(scene.principal.principal_id, artifact_id)
    assert artifact is not None
    return artifact.source_lane


@pytest.mark.parametrize("case", ["final", "partial", "stale", "superseded", "missing"])
def test_reporter_input_eligibility_equals_reporter_commit_acceptance(
    scene: Scene, case: str
) -> None:
    tag = f"agr-{case}"
    service, cycle, coll = fresh(scene, tag)
    ids = tuple(
        researcher(service, scene, cycle, coll, lane, f"{tag}-{lane.value}") for lane in THREE
    )
    candidate: str | None = None
    if case != "missing":
        candidate = commit_ok(
            service,
            scene,
            synth_command(
                cycle,
                ids,
                f"{tag}-s",
                state=ArtifactState.PARTIAL if case == "partial" else ArtifactState.FINAL,
            ),
        )
    if case == "stale":
        researcher(service, scene, cycle, coll, THREE[0], f"{tag}-rerun")
    if case == "superseded":
        commit_ok(service, scene, synth_command(cycle, ids, f"{tag}-s2"))
    resolved = resolve(service, scene, cycle, ResolverSetId.REPORTER_INPUT)
    member = members(resolved)[0]
    assert member["required"] is True
    expected = {
        "final": ("READY", "READY", "ready"),
        "partial": ("PARTIAL", "DEGRADED", "eligible_partial"),
        "stale": ("STALE", "BLOCKED", "stale_upstream"),
        "superseded": ("READY", "READY", "ready"),
        "missing": ("MISSING", "BLOCKED", "absent"),
    }[case]
    assert (member["readiness"], resolved["aggregate"], member["readiness_reason"]) == expected
    if case == "superseded":
        # The resolver names the v2 head; the superseded v1 is refused as stale.
        assert member["artifact_id"] != candidate
        assert candidate is not None
        assert_error(
            attempt(service, scene, reporter_command(cycle, (candidate,), f"{tag}-r-old")),
            ErrorCode.CONFLICT,
            *STALE,
        )
        candidate = str(member["artifact_id"])
    if candidate is None:
        return
    outcome = attempt(
        service,
        scene,
        reporter_command(
            cycle,
            (candidate,),
            f"{tag}-r",
            state=ArtifactState.PARTIAL if case == "partial" else ArtifactState.FINAL,
        ),
    )
    if member["readiness"] in {"READY", "PARTIAL"} or case == "superseded":
        assert outcome.error is None, outcome.error
    else:
        assert_error(outcome, ErrorCode.CONFLICT, *STALE)


# --- H': the historical recovery path is the normal path --------------------------


def test_historical_recovery_runs_through_the_normal_path(scene: Scene) -> None:
    """H' (no code): recollect, re-research, then synthesize and report a past date.

    1. The collector bypass re-commits the collector, staling the researchers.
    2. The synthesizer is refused as stale.
    3. The original raw collector content is re-committed as a new head.
    4. The researchers are re-committed against it.
    5. Synthesizer then reporter commit with the cycle's original business date.
    """
    service = build_service(scene.world, scene.providers)
    past = "2026-07-15"
    assert date.fromisoformat(past) < WHEN.astimezone(UTC).date()
    cycle = str(begin(service, scene, "hist", date=past)["cycle_run_id"])
    raw = "# Collector\n\noriginal raw candidates"
    coll_v1 = collector(service, scene, cycle, "hist-c1", report_date=past, body=raw)
    old_ids = tuple(
        researcher(service, scene, cycle, coll_v1, lane, f"hist-{lane.value}", report_date=past)
        for lane in THREE
    )
    bypass = collector(service, scene, cycle, "hist-bypass", report_date=past, body="bypass")
    assert_error(
        attempt(service, scene, synth_command(cycle, old_ids, "hist-s-stale", report_date=past)),
        ErrorCode.CONFLICT,
        *STALE,
    )
    store = scene.world.intelligence
    principal_id = scene.principal.principal_id
    superseded_ids = (coll_v1, bypass, *old_ids)

    def stamps() -> dict[str, tuple[object, object, int]]:
        found: dict[str, tuple[object, object, int]] = {}
        for artifact_id in superseded_ids:
            artifact = store.get_artifact(principal_id, artifact_id)
            assert artifact is not None
            found[artifact_id] = (artifact.committed_at, artifact.generated_at, artifact.version)
        return found

    coll_v3 = collector(service, scene, cycle, "hist-c3", report_date=past, body=raw)
    before = stamps()
    assert coll_v3 != coll_v1
    v1 = store.get_artifact(principal_id, coll_v1)
    v3 = store.get_artifact(principal_id, coll_v3)
    assert v1 is not None
    assert v3 is not None
    assert v3.content_sha256 == v1.content_sha256
    new_ids = tuple(
        researcher(
            service, scene, cycle, coll_v3, lane, f"hist-{lane.value}-rerun", report_date=past
        )
        for lane in THREE
    )
    synth = commit_ok(service, scene, synth_command(cycle, new_ids, "hist-s", report_date=past))
    report = commit_ok(
        service, scene, reporter_command(cycle, (synth,), "hist-r", report_date=past)
    )
    assert read(service, scene, report)["report_date"] == past
    assert read(service, scene, synth)["report_date"] == past
    assert stamps() == before
    for artifact_id in superseded_ids:
        artifact = store.get_artifact(principal_id, artifact_id)
        assert artifact is not None
        assert artifact.is_current is False
        assert artifact.artifact_state is ArtifactState.SUPERSEDED


def test_historical_reporter_commit_has_no_briefing_side_effect(scene: Scene) -> None:
    """There is no webhook or outbox in this repository. A historical Reporter commit
    writes its artifact, run and receipt (dependencies ride on the artifact) and
    nothing else: no Record Event, no job, no cycle transition, and it never
    appears in a listing for today's date.
    """
    service = build_service(scene.world, scene.providers)
    past = "2026-07-15"
    today = WHEN.astimezone(UTC).date().isoformat()
    cycle = str(begin(service, scene, "brief", date=past)["cycle_run_id"])
    coll = collector(service, scene, cycle, "brief-c", report_date=past)
    ids = tuple(
        researcher(service, scene, cycle, coll, lane, f"brief-{lane.value}", report_date=past)
        for lane in THREE
    )
    synth = commit_ok(service, scene, synth_command(cycle, ids, "brief-s", report_date=past))
    world = scene.world
    store = world.intelligence
    events_before = list(world.record_events)
    jobs_before = dict(world.jobs)
    cycles_before = dict(store.cycles)
    counts_before = (len(store.artifacts), len(store.runs), len(store.receipts))
    report = commit_ok(
        service, scene, reporter_command(cycle, (synth,), "brief-r", report_date=past)
    )
    assert (len(store.artifacts), len(store.runs), len(store.receipts)) == tuple(
        n + 1 for n in counts_before
    )
    assert world.record_events == events_before
    assert world.jobs == jobs_before
    assert store.cycles == cycles_before
    todays = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ListIntelligenceArtifacts(report_date=today),
        )
    )
    items = todays["items"]
    assert isinstance(items, list)
    assert report not in {item["report_id"] for item in items}
    todays_reporters = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ListIntelligenceArtifacts(stage=IntelligenceStage.REPORTER, report_date=today),
        )
    )
    assert todays_reporters["items"] == []
