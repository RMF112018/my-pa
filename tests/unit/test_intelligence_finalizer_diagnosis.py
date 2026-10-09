"""Characterization of the synthesizer/reporter dependency gate (finalizer diagnosis).

Each test violates exactly one branch of ``_validate_dependencies`` (or the
resolver) and pins the code and safe-detail field returned today. Fixture
shapes are synthetic. One strict xfail records the target behaviour.
"""

from __future__ import annotations

import pytest

from my_pa.adapters.normalization import normalize
from my_pa.application.commands import (
    BeginIntelligenceCycle,
    CommitIntelligenceArtifact,
    RecordIntelligenceRunState,
    ResolveIntelligenceSet,
)
from my_pa.application.producer_origin import ProducerOrigin
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
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
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import Scene, build_service, metadata_for, operator

FOCUS = FocusAreaId.COMMUNICATIONS
DEPENDENCY_FIELD = "dependency_report_ids"


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
        body_markdown=f"body {key}",
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


def collector(service: ApplicationService, scene: Scene, cycle: str, key: str) -> str:
    return commit_ok(
        service,
        scene,
        command(
            cycle=cycle,
            stage=IntelligenceStage.COLLECTOR,
            kind=ArtifactKind.COLLECTOR_CANDIDATES,
            key=key,
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
    cycle: str, ids: tuple[str, ...], key: str, producer: str | None = None
) -> CommitIntelligenceArtifact:
    return command(
        cycle=cycle,
        stage=IntelligenceStage.SYNTHESIZER,
        kind=ArtifactKind.SYNTHESIS_PACKAGE,
        key=key,
        dependencies=ids,
        producer=producer,
    )


def assert_error(envelope: ResponseEnvelope, code: ErrorCode, field: str) -> None:
    assert envelope.error is not None, "expected an error envelope"
    assert envelope.error.code is code
    assert envelope.error.safe_details == (field,)


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


def fresh(scene: Scene, key: str) -> tuple[ApplicationService, str, str]:
    service = build_service(scene.world, scene.providers)
    cycle = str(begin(service, scene, key)["cycle_run_id"])
    return service, cycle, collector(service, scene, cycle, f"{key}-c")


THREE = (SourceLaneId.SHAREPOINT, SourceLaneId.MY_PA, SourceLaneId.OUTLOOK)


def test_d1_three_commissioned_lanes_rejected_by_count(scene: Scene) -> None:
    """D1 (_validate_dependencies len != REQUIRED_DEPENDENCY_COUNT[synthesizer]=5)."""
    service, cycle, coll = fresh(scene, "d1a")
    ids = tuple(
        researcher(service, scene, cycle, coll, lane, f"d1a-{lane.value}") for lane in THREE
    )
    assert_error(
        attempt(service, scene, synth_command(cycle, ids, "d1a-s")),
        ErrorCode.INVALID_REQUEST,
        DEPENDENCY_FIELD,
    )


def test_d1_adding_collector_id_still_rejected(scene: Scene) -> None:
    """D1 again: 3 researchers + collector id = 4 ids, still != 5."""
    service, cycle, coll = fresh(scene, "d1b")
    ids = tuple(
        researcher(service, scene, cycle, coll, lane, f"d1b-{lane.value}") for lane in THREE
    )
    assert_error(
        attempt(service, scene, synth_command(cycle, (*ids, coll), "d1b-s")),
        ErrorCode.INVALID_REQUEST,
        DEPENDENCY_FIELD,
    )


def test_d6_five_ids_wrong_lane_set_rejected(scene: Scene) -> None:
    """D6: five distinct ids (passes D1-D3, same cycle, all known) with a duplicated lane.

    Repeating one id is refused earlier, at CommitIntelligenceArtifact construction
    (commands.py duplicate-id check raises InvalidRequestError, no envelope). So the
    lane set is made wrong with a superseded teams researcher v1 plus the current v2
    and four other lanes: len(lanes) == 5 but set(lanes) has 4, so
    ``set(lanes) != set(EXPECTED_SOURCE_LANES)`` fires before the D7 loop.
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
        DEPENDENCY_FIELD,
    )


def test_d7_five_ids_wrong_focus_rejected(scene: Scene) -> None:
    """D7: full 5-lane set, but researchers belong to another focus area."""
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
        for lane in EXPECTED_SOURCE_LANES
    )
    assert_error(
        attempt(service, scene, synth_command(cycle, ids, "d7-s")),
        ErrorCode.INVALID_REQUEST,
        DEPENDENCY_FIELD,
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
        DEPENDENCY_FIELD,
    )


def test_d2_unknown_and_cross_principal_ids_rejected(scene: Scene) -> None:
    """D2: store.get_artifact(principal, id) is None for unknown and foreign ids."""
    service, cycle, coll = fresh(scene, "d2")
    ids = researchers(service, scene, cycle, coll, "d2")
    unknown = (*ids[:4], issue_identifier(IdKind.INTELLIGENCE_ARTIFACT))
    assert_error(
        attempt(service, scene, synth_command(cycle, unknown, "d2-s1")),
        ErrorCode.INVALID_REQUEST,
        DEPENDENCY_FIELD,
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
    assert_error(envelope, ErrorCode.INVALID_REQUEST, DEPENDENCY_FIELD)


@pytest.mark.parametrize("producer", ["task-anything", "x", "some other automation"])
def test_producer_identity_not_checked(scene: Scene, producer: str) -> None:
    """Producer task id/name is not a rejection branch: five legit lanes succeed."""
    service, cycle, coll = fresh(scene, f"prod-{producer[:1]}{len(producer)}")
    ids = tuple(researchers(service, scene, cycle, coll, f"p{len(producer)}"))
    key = f"prod-s-{len(producer)}"
    report = commit_ok(service, scene, synth_command(cycle, ids, key, producer=producer))
    assert report


def test_omitted_dependency_ids_rejected_as_count(scene: Scene) -> None:
    """Omitted dependency_report_ids -> () -> D1, in-process and via the wire normalizer."""
    service, cycle, _coll = fresh(scene, "omit")
    assert_error(
        attempt(service, scene, synth_command(cycle, (), "omit-s")),
        ErrorCode.INVALID_REQUEST,
        DEPENDENCY_FIELD,
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
    assert_error(envelope, ErrorCode.INVALID_REQUEST, DEPENDENCY_FIELD)


def test_s3_collector_recommit_stales_researchers(scene: Scene) -> None:
    """S3: a re-committed collector stales the five researchers; commit is a CONFLICT."""
    service, cycle, coll = fresh(scene, "s3")
    ids = tuple(researchers(service, scene, cycle, coll, "s3"))
    before = resolve(service, scene, cycle, ResolverSetId.SYNTHESIZER_INPUTS)
    assert before["aggregate"] == "READY"
    commit_ok(
        service,
        scene,
        command(
            cycle=cycle,
            stage=IntelligenceStage.COLLECTOR,
            kind=ArtifactKind.COLLECTOR_CANDIDATES,
            key="s3-c2",
        ),
    )
    for set_id in (ResolverSetId.RESEARCH_SWARM, ResolverSetId.SYNTHESIZER_INPUTS):
        resolved = resolve(service, scene, cycle, set_id)
        assert resolved["aggregate"] == "BLOCKED"
        assert [m["readiness"] for m in members(resolved)] == ["STALE"] * 5
    assert_error(
        attempt(service, scene, synth_command(cycle, ids, "s3-s")),
        ErrorCode.CONFLICT,
        "artifact_id",
    )


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
    assert [m["artifact_id"] for m in members(resolved)] == list(ids) or {
        m["artifact_id"] for m in members(resolved)
    } == set(ids)
    other = begin(service, scene, "replay-2", date="2026-08-21")
    assert other["cycle_run_id"] != cycle
    assert other["created"] is True


def test_resolver_validator_disagree_on_partial(scene: Scene) -> None:
    """Disagreement: commit accepts a PARTIAL researcher; resolve_set blocks on it."""
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
    assert resolved["aggregate"] == "BLOCKED"
    teams = next(m for m in members(resolved) if m["source_lane"] == "teams")
    assert teams["readiness"] == "PARTIAL"
    # The validator nevertheless accepts the same inputs.
    assert commit_ok(service, scene, synth_command(cycle, tuple(ids), "partial-s"))


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


@pytest.mark.xfail(strict=True, reason="target: three commissioned lanes")
def test_target_three_lane_synthesizer_then_reporter_succeeds(scene: Scene) -> None:
    service, cycle, coll = fresh(scene, "target")
    ids = tuple(
        researcher(service, scene, cycle, coll, lane, f"target-{lane.value}") for lane in THREE
    )
    synth = commit_ok(service, scene, synth_command(cycle, ids, "target-s"))
    reporter = commit_ok(
        service,
        scene,
        command(
            cycle=cycle,
            stage=IntelligenceStage.REPORTER,
            kind=ArtifactKind.FOCUS_REPORT,
            key="target-r",
            dependencies=(synth,),
        ),
    )
    assert reporter


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
    coll = commit_ok(
        service,
        scene,
        command(
            cycle=cycle,
            stage=IntelligenceStage.COLLECTOR,
            kind=ArtifactKind.COLLECTOR_CANDIDATES,
            key="tm-c",
            report_date=old,
        ),
    )
    for lane in THREE:
        commit_ok(
            service,
            scene,
            command(
                cycle=cycle,
                stage=IntelligenceStage.RESEARCHER,
                kind=ArtifactKind.RESEARCH_CONTEXT,
                key=f"tm-{lane.value}",
                lane=lane,
                dependencies=(coll,),
                report_date=old,
            ),
        )

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
                RecordIntelligenceRunState(
                    cycle_run_id=cycle,
                    stage=IntelligenceStage.RESEARCHER,
                    artifact_kind=ArtifactKind.RESEARCH_CONTEXT,
                    producer_task_id=f"tm-fail-{lane.value}",
                    producer_task_name="failed lane",
                    automation_platform="abacus_chatllm",
                    report_date=old,
                    state=ProducerRunState.FAILED,
                    idempotency_key=f"tm-fail-{lane.value}",
                    focus_area_id=FOCUS,
                    source_lane=lane,
                    failure_code="source_unavailable",
                ),
            )
        )
    failed = {lane.value: "READY" for lane in THREE} | {"onedrive": "FAILED", "teams": "FAILED"}
    assert readiness() == failed
    commit_ok(
        service,
        scene,
        command(
            cycle=cycle,
            stage=IntelligenceStage.COLLECTOR,
            kind=ArtifactKind.COLLECTOR_CANDIDATES,
            key="tm-c2",
            report_date=old,
        ),
    )
    stale = {lane.value: "STALE" for lane in THREE} | {"onedrive": "FAILED", "teams": "FAILED"}
    assert readiness() == stale


def test_f5_record_run_state_accepts_succeeded_without_artifact(scene: Scene) -> None:
    """F5: record_run_state admits every ProducerRunState (no state allowlist, no artifact
    requirement; intelligence.py record_run_state / commands.RecordIntelligenceRunState only
    type-check the enum). A synthesizer SUCCEEDED run with no artifact is accepted, and the
    resolver then reports the member MISSING (failed_run only maps FAILED/PARTIAL).
    """
    service, cycle, _coll = fresh(scene, "f5")
    recorded = payload(
        run(
            service,
            scene,
            Purpose.REPORT_AUTHORING,
            RecordIntelligenceRunState(
                cycle_run_id=cycle,
                stage=IntelligenceStage.SYNTHESIZER,
                artifact_kind=ArtifactKind.SYNTHESIS_PACKAGE,
                producer_task_id="f5-synth",
                producer_task_name="synth",
                automation_platform="abacus_chatllm",
                report_date="2026-08-20",
                state=ProducerRunState.SUCCEEDED,
                idempotency_key="f5-run",
                focus_area_id=FOCUS,
            ),
        )
    )
    assert recorded["state"] == "succeeded"
    assert recorded["created"] is True
    for set_id in (ResolverSetId.REPORTER_INPUT,):
        resolved = resolve(service, scene, cycle, set_id)
        assert resolved["aggregate"] == "BLOCKED"
        assert [m["readiness"] for m in members(resolved)] == ["MISSING"]
        assert [m["artifact_id"] for m in members(resolved)] == [None]
    assert {
        m["readiness"]
        for m in members(resolve(service, scene, cycle, ResolverSetId.SYNTHESIZER_INPUTS))
    } == {"MISSING"}


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
