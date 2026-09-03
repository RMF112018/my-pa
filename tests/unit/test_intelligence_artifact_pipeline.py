"""Synthetic Morning Intelligence artifact pipeline against the application service."""

from __future__ import annotations

from my_pa.application.commands import (
    BeginIntelligenceCycle,
    CommitIntelligenceArtifact,
    GetLatestIntelligenceArtifact,
    ListIntelligenceArtifacts,
    ReadIntelligenceArtifact,
    RecordIntelligenceRunState,
    ResolveIntelligenceSet,
    SearchIntelligenceArtifacts,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    CYCLE_MORNING_INTELLIGENCE,
    EXPECTED_FOCUS_AREAS,
    EXPECTED_SOURCE_LANES,
    MAX_ARTIFACT_BODY_BYTES,
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
    ProducerRunState,
    ResolverSetId,
    SourceLaneId,
)
from my_pa.domain.intelligence.models import content_digest
from tests.conftest import Scene, build_service, metadata_for, operator

FOCUS = FocusAreaId.COMMUNICATIONS


def run(
    service: ApplicationService,
    scene: Scene,
    purpose: Purpose,
    command: object,
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


def begin(service: ApplicationService, scene: Scene, key: str, date: str = "2026-08-20") -> str:
    result = payload(
        run(
            service,
            scene,
            Purpose.REPORT_AUTHORING,
            BeginIntelligenceCycle(
                cycle_id=CYCLE_MORNING_INTELLIGENCE,
                business_date=date,
                idempotency_key=key,
            ),
        )
    )
    cycle_run_id = result["cycle_run_id"]
    assert isinstance(cycle_run_id, str)
    return cycle_run_id


def commit(
    service: ApplicationService,
    scene: Scene,
    *,
    cycle_run_id: str,
    stage: IntelligenceStage,
    kind: ArtifactKind,
    key: str,
    title: str,
    body: str,
    focus: FocusAreaId | None = None,
    lane: SourceLaneId | None = None,
    dependencies: tuple[str, ...] = (),
    state: ArtifactState = ArtifactState.FINAL,
) -> dict[str, object]:
    return payload(
        run(
            service,
            scene,
            Purpose.REPORT_AUTHORING,
            CommitIntelligenceArtifact(
                cycle_run_id=cycle_run_id,
                stage=stage,
                artifact_kind=kind,
                producer_task_id=f"task-{stage.value}",
                producer_task_name=title,
                automation_platform="abacus_chatllm",
                report_date="2026-08-20",
                title=title,
                body_markdown=body,
                artifact_state=state,
                schema_version="1",
                idempotency_key=key,
                focus_area_id=focus,
                source_lane=lane,
                dependency_report_ids=dependencies,
            ),
        )
    )


def test_cycle_replay_returns_the_same_identity(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    first = payload(
        run(
            service,
            scene,
            Purpose.REPORT_AUTHORING,
            BeginIntelligenceCycle(
                cycle_id=CYCLE_MORNING_INTELLIGENCE,
                business_date="2026-08-20",
                idempotency_key="cycle-a",
            ),
        )
    )
    second = payload(
        run(
            service,
            scene,
            Purpose.REPORT_AUTHORING,
            BeginIntelligenceCycle(
                cycle_id=CYCLE_MORNING_INTELLIGENCE,
                business_date="2026-08-20",
                idempotency_key="cycle-a",
            ),
        )
    )
    assert first["cycle_run_id"] == second["cycle_run_id"]
    assert second["replayed"] is True
    assert second["created"] is False


def test_conflicting_cycle_replay_does_not_mutate(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    begin(service, scene, "cycle-conflict")
    envelope = run(
        service,
        scene,
        Purpose.REPORT_AUTHORING,
        BeginIntelligenceCycle(
            cycle_id=CYCLE_MORNING_INTELLIGENCE,
            business_date="2026-08-21",
            idempotency_key="cycle-conflict",
        ),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.CONFLICT


def test_collector_commit_and_readback_preserve_digest(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-collect")
    body = "# Collector\n\nsynthetic candidates"
    committed = commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        key="collect-1",
        title="Collector communications",
        body=body,
        focus=FOCUS,
    )
    assert committed["created"] is True
    assert committed["content_sha256"] == content_digest(body)
    report_id = committed["report_id"]
    assert isinstance(report_id, str)
    read = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ReadIntelligenceArtifact(report_id=report_id),
        )
    )
    assert read["body_markdown"] == body
    assert read["content_sha256"] == committed["content_sha256"]
    assert read["cycle_run_id"] == cycle
    assert "structured_content" not in read


def test_researcher_without_collector_dependency_is_rejected(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-researcher")
    envelope = run(
        service,
        scene,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.RESEARCHER,
            artifact_kind=ArtifactKind.RESEARCH_CONTEXT,
            producer_task_id="r1",
            producer_task_name="Teams",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="Teams research",
            body_markdown="no collector",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="research-bad",
            focus_area_id=FOCUS,
            source_lane=SourceLaneId.TEAMS,
        ),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.INVALID_REQUEST


def test_identical_commit_replay_does_not_duplicate(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-replay-commit")
    first = commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        key="same-collect",
        title="Collector",
        body="body",
        focus=FOCUS,
    )
    second = commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        key="same-collect",
        title="Collector",
        body="body",
        focus=FOCUS,
    )
    assert first["report_id"] == second["report_id"]
    assert second["replayed"] is True
    assert len(scene.world.intelligence.artifacts) == 1


def test_oversize_body_is_rejected_before_durable_write(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-limit")
    envelope = run(
        service,
        scene,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.COLLECTOR,
            artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES,
            producer_task_id="big",
            producer_task_name="big",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="too large",
            body_markdown="x" * (MAX_ARTIFACT_BODY_BYTES + 1),
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="too-big",
            focus_area_id=FOCUS,
        ),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.INVALID_REQUEST
    assert scene.world.intelligence.artifacts == {}


def test_unsafe_provenance_url_is_rejected(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-url")
    envelope = run(
        service,
        scene,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.COLLECTOR,
            artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES,
            producer_task_id="url",
            producer_task_name="url",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="url",
            body_markdown="body",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="url-key",
            focus_area_id=FOCUS,
            provenance=(
                {
                    "source_system": "sharepoint",
                    "source_ref": "item-1",
                    "relation": "supports",
                    "source_href": "javascript:alert(1)",
                },
            ),
        ),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.INVALID_REQUEST


def test_failed_run_is_durable_without_a_body(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-fail")
    result = payload(
        run(
            service,
            scene,
            Purpose.REPORT_AUTHORING,
            RecordIntelligenceRunState(
                cycle_run_id=cycle,
                stage=IntelligenceStage.RESEARCHER,
                artifact_kind=ArtifactKind.RESEARCH_CONTEXT,
                producer_task_id="teams",
                producer_task_name="Teams",
                automation_platform="abacus_chatllm",
                report_date="2026-08-20",
                state=ProducerRunState.FAILED,
                idempotency_key="fail-teams",
                focus_area_id=FOCUS,
                source_lane=SourceLaneId.TEAMS,
                failure_code="source_unavailable",
            ),
        )
    )
    assert result["state"] == "failed"
    assert result["created"] is True


def _focus_branch(service: ApplicationService, scene: Scene, cycle: str, focus: FocusAreaId) -> str:
    collector = commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        key=f"{cycle}-{focus.value}-c",
        title=f"Collector {focus.value}",
        body=f"collector {focus.value}",
        focus=focus,
    )
    collector_id = collector["report_id"]
    assert isinstance(collector_id, str)
    researcher_ids: list[str] = []
    for lane in EXPECTED_SOURCE_LANES:
        research = commit(
            service,
            scene,
            cycle_run_id=cycle,
            stage=IntelligenceStage.RESEARCHER,
            kind=ArtifactKind.RESEARCH_CONTEXT,
            key=f"{cycle}-{focus.value}-{lane.value}",
            title=f"{focus.value} {lane.value}",
            body=f"research {lane.value}",
            focus=focus,
            lane=lane,
            dependencies=(collector_id,),
        )
        report_id = research["report_id"]
        assert isinstance(report_id, str)
        researcher_ids.append(report_id)
    synthesis = commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.SYNTHESIZER,
        kind=ArtifactKind.SYNTHESIS_PACKAGE,
        key=f"{cycle}-{focus.value}-s",
        title=f"Synthesis {focus.value}",
        body="synthesis",
        focus=focus,
        dependencies=tuple(researcher_ids),
    )
    synth_id = synthesis["report_id"]
    assert isinstance(synth_id, str)
    reporter = commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.REPORTER,
        kind=ArtifactKind.FOCUS_REPORT,
        key=f"{cycle}-{focus.value}-r",
        title=f"Report {focus.value}",
        body=f"report {focus.value}",
        focus=focus,
        dependencies=(synth_id,),
    )
    report_id = reporter["report_id"]
    assert isinstance(report_id, str)
    return report_id


def test_full_synthetic_cycle_persists_forty_nine_executions(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-full")
    reporters = tuple(_focus_branch(service, scene, cycle, focus) for focus in EXPECTED_FOCUS_AREAS)
    brief = commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.MORNING_BRIEF,
        kind=ArtifactKind.MORNING_BRIEF,
        key=f"{cycle}-brief",
        title="Morning Brief",
        body="brief body",
        dependencies=reporters,
    )
    assert brief["created"] is True
    assert len(scene.world.intelligence.artifacts) == 49
    resolved = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ResolveIntelligenceSet(cycle_run_id=cycle, set_id=ResolverSetId.MORNING_BRIEF_INPUTS),
        )
    )
    assert resolved["aggregate"] == "READY"
    members = resolved["members"]
    assert isinstance(members, list)
    assert len(members) == 6
    assert {member["artifact_id"] for member in members} == set(reporters)


def test_morning_brief_cannot_mix_cycle_runs(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle_a = begin(service, scene, "cycle-a-mix")
    cycle_b = begin(service, scene, "cycle-b-mix")
    reporters_a = tuple(
        _focus_branch(service, scene, cycle_a, focus) for focus in EXPECTED_FOCUS_AREAS
    )
    reporters_b = tuple(
        _focus_branch(service, scene, cycle_b, focus) for focus in EXPECTED_FOCUS_AREAS
    )
    mixed = (reporters_a[0], *reporters_b[1:])
    envelope = run(
        service,
        scene,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle_b,
            stage=IntelligenceStage.MORNING_BRIEF,
            artifact_kind=ArtifactKind.MORNING_BRIEF,
            producer_task_id="brief",
            producer_task_name="brief",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="mixed",
            body_markdown="mixed",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="mixed-brief",
            dependency_report_ids=mixed,
        ),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.INVALID_REQUEST


def test_collector_rerun_stales_old_researchers(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-stale")
    first = commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        key="c1",
        title="c1",
        body="v1",
        focus=FOCUS,
    )
    collector_v1 = first["report_id"]
    assert isinstance(collector_v1, str)
    research = commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.RESEARCHER,
        kind=ArtifactKind.RESEARCH_CONTEXT,
        key="r1",
        title="r1",
        body="from v1",
        focus=FOCUS,
        lane=SourceLaneId.TEAMS,
        dependencies=(collector_v1,),
    )
    second = commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        key="c2",
        title="c2",
        body="v2",
        focus=FOCUS,
    )
    assert second["supersedes_report_id"] == collector_v1
    envelope = run(
        service,
        scene,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.RESEARCHER,
            artifact_kind=ArtifactKind.RESEARCH_CONTEXT,
            producer_task_id="r-stale",
            producer_task_name="stale",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="stale use",
            body_markdown="no",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="stale-r",
            focus_area_id=FOCUS,
            source_lane=SourceLaneId.OUTLOOK,
            dependency_report_ids=(collector_v1,),
        ),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.CONFLICT
    historical = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ReadIntelligenceArtifact(report_id=str(research["report_id"])),
        )
    )
    assert historical["body_markdown"] == "from v1"


def test_collector_rerun_stales_descendant_readiness_and_commits(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-lineage")
    reporter_id = _focus_branch(service, scene, cycle, FOCUS)
    synthesizer = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            GetLatestIntelligenceArtifact(
                cycle_run_id=cycle,
                stage=IntelligenceStage.SYNTHESIZER,
                focus_area_id=FOCUS,
            ),
        )
    )
    synth_id = synthesizer["report_id"]
    assert isinstance(synth_id, str)
    swarm = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ResolveIntelligenceSet(
                cycle_run_id=cycle,
                set_id=ResolverSetId.RESEARCH_SWARM,
                focus_area_id=FOCUS,
            ),
        )
    )
    assert swarm["aggregate"] == "READY"
    reporter_set = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ResolveIntelligenceSet(
                cycle_run_id=cycle,
                set_id=ResolverSetId.REPORTER_INPUT,
                focus_area_id=FOCUS,
            ),
        )
    )
    assert reporter_set["aggregate"] == "READY"
    commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        key="c-lineage-v2",
        title="c2",
        body="v2",
        focus=FOCUS,
    )
    swarm_after = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ResolveIntelligenceSet(
                cycle_run_id=cycle,
                set_id=ResolverSetId.RESEARCH_SWARM,
                focus_area_id=FOCUS,
            ),
        )
    )
    assert swarm_after["aggregate"] == "BLOCKED"
    members = swarm_after["members"]
    assert isinstance(members, list)
    assert {member["readiness"] for member in members} == {"STALE"}
    reporter_after = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ResolveIntelligenceSet(
                cycle_run_id=cycle,
                set_id=ResolverSetId.REPORTER_INPUT,
                focus_area_id=FOCUS,
            ),
        )
    )
    assert reporter_after["aggregate"] != "READY"
    reporter_members = reporter_after["members"]
    assert isinstance(reporter_members, list)
    assert reporter_members[0]["readiness"] == "STALE"
    brief_inputs = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ResolveIntelligenceSet(cycle_run_id=cycle, set_id=ResolverSetId.MORNING_BRIEF_INPUTS),
        )
    )
    assert brief_inputs["aggregate"] != "READY"
    brief_members = brief_inputs["members"]
    assert isinstance(brief_members, list)
    communications = next(
        member for member in brief_members if member["focus_area_id"] == FOCUS.value
    )
    assert communications["readiness"] == "STALE"
    stale_reporter = run(
        service,
        scene,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.REPORTER,
            artifact_kind=ArtifactKind.FOCUS_REPORT,
            producer_task_id="stale-reporter",
            producer_task_name="stale reporter",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="stale reporter",
            body_markdown="no",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="stale-reporter",
            focus_area_id=FOCUS,
            dependency_report_ids=(synth_id,),
        ),
    )
    assert stale_reporter.error is not None
    assert stale_reporter.error.code is ErrorCode.CONFLICT
    historical = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ReadIntelligenceArtifact(report_id=reporter_id),
        )
    )
    assert historical["body_markdown"] == f"report {FOCUS.value}"


def _latest(
    service: ApplicationService,
    scene: Scene,
    cycle: str,
    stage: IntelligenceStage,
    *,
    focus: FocusAreaId | None = None,
    lane: SourceLaneId | None = None,
) -> str:
    result = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            GetLatestIntelligenceArtifact(
                cycle_run_id=cycle,
                stage=stage,
                focus_area_id=focus,
                source_lane=lane,
            ),
        )
    )
    report_id = result["report_id"]
    assert isinstance(report_id, str)
    return report_id


def test_researcher_rerun_stales_reporter_input_and_rejects_old_synthesizer(
    scene: Scene,
) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-r-rerun")
    reporter_id = _focus_branch(service, scene, cycle, FOCUS)
    synth_id = _latest(service, scene, cycle, IntelligenceStage.SYNTHESIZER, focus=FOCUS)
    collector_id = _latest(service, scene, cycle, IntelligenceStage.COLLECTOR, focus=FOCUS)
    commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.RESEARCHER,
        kind=ArtifactKind.RESEARCH_CONTEXT,
        key="r-teams-v2",
        title="teams v2",
        body="from current collector",
        focus=FOCUS,
        lane=SourceLaneId.TEAMS,
        dependencies=(collector_id,),
    )
    reporter_set = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ResolveIntelligenceSet(
                cycle_run_id=cycle,
                set_id=ResolverSetId.REPORTER_INPUT,
                focus_area_id=FOCUS,
            ),
        )
    )
    assert reporter_set["aggregate"] != "READY"
    members = reporter_set["members"]
    assert isinstance(members, list)
    assert members[0]["readiness"] == "STALE"
    stale = run(
        service,
        scene,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.REPORTER,
            artifact_kind=ArtifactKind.FOCUS_REPORT,
            producer_task_id="stale-after-r",
            producer_task_name="stale",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="stale",
            body_markdown="no",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="stale-after-r",
            focus_area_id=FOCUS,
            dependency_report_ids=(synth_id,),
        ),
    )
    assert stale.error is not None
    assert stale.error.code is ErrorCode.CONFLICT
    historical = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ReadIntelligenceArtifact(report_id=reporter_id),
        )
    )
    assert historical["body_markdown"] == f"report {FOCUS.value}"


def test_synthesizer_rerun_stales_brief_inputs_and_rejects_old_reporters(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-s-rerun")
    reporters = tuple(_focus_branch(service, scene, cycle, focus) for focus in EXPECTED_FOCUS_AREAS)
    brief = commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.MORNING_BRIEF,
        kind=ArtifactKind.MORNING_BRIEF,
        key=f"{cycle}-brief",
        title="Morning Brief",
        body="brief body",
        dependencies=reporters,
    )
    researcher_ids = tuple(
        _latest(
            service,
            scene,
            cycle,
            IntelligenceStage.RESEARCHER,
            focus=FOCUS,
            lane=lane,
        )
        for lane in EXPECTED_SOURCE_LANES
    )
    commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.SYNTHESIZER,
        kind=ArtifactKind.SYNTHESIS_PACKAGE,
        key="s-v2",
        title="synthesis v2",
        body="synthesis v2",
        focus=FOCUS,
        dependencies=researcher_ids,
    )
    brief_inputs = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ResolveIntelligenceSet(cycle_run_id=cycle, set_id=ResolverSetId.MORNING_BRIEF_INPUTS),
        )
    )
    assert brief_inputs["aggregate"] != "READY"
    members = brief_inputs["members"]
    assert isinstance(members, list)
    communications = next(member for member in members if member["focus_area_id"] == FOCUS.value)
    assert communications["readiness"] == "STALE"
    stale_brief = run(
        service,
        scene,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.MORNING_BRIEF,
            artifact_kind=ArtifactKind.MORNING_BRIEF,
            producer_task_id="stale-brief",
            producer_task_name="stale brief",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="stale brief",
            body_markdown="no",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="stale-brief",
            dependency_report_ids=reporters,
        ),
    )
    assert stale_brief.error is not None
    assert stale_brief.error.code is ErrorCode.CONFLICT
    historical = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ReadIntelligenceArtifact(report_id=str(brief["report_id"])),
        )
    )
    assert historical["body_markdown"] == "brief body"


def test_failed_researcher_lane_exposes_run_id_and_blocks_synthesizer(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-blocked-lane")
    collector = commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        key="block-c",
        title="collector",
        body="collector",
        focus=FOCUS,
    )
    collector_id = collector["report_id"]
    assert isinstance(collector_id, str)
    live_ids: list[str] = []
    failed_run_id = ""
    for lane in EXPECTED_SOURCE_LANES:
        if lane is SourceLaneId.TEAMS:
            failed = payload(
                run(
                    service,
                    scene,
                    Purpose.REPORT_AUTHORING,
                    RecordIntelligenceRunState(
                        cycle_run_id=cycle,
                        stage=IntelligenceStage.RESEARCHER,
                        artifact_kind=ArtifactKind.RESEARCH_CONTEXT,
                        producer_task_id="teams-fail",
                        producer_task_name="Teams",
                        automation_platform="abacus_chatllm",
                        report_date="2026-08-20",
                        state=ProducerRunState.FAILED,
                        idempotency_key="block-teams-fail",
                        focus_area_id=FOCUS,
                        source_lane=lane,
                        failure_code="source_unavailable",
                    ),
                )
            )
            run_id = failed["report_run_id"]
            assert isinstance(run_id, str)
            failed_run_id = run_id
            continue
        research = commit(
            service,
            scene,
            cycle_run_id=cycle,
            stage=IntelligenceStage.RESEARCHER,
            kind=ArtifactKind.RESEARCH_CONTEXT,
            key=f"block-{lane.value}",
            title=lane.value,
            body=f"research {lane.value}",
            focus=FOCUS,
            lane=lane,
            dependencies=(collector_id,),
        )
        report_id = research["report_id"]
        assert isinstance(report_id, str)
        live_ids.append(report_id)
    resolved = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ResolveIntelligenceSet(
                cycle_run_id=cycle,
                set_id=ResolverSetId.SYNTHESIZER_INPUTS,
                focus_area_id=FOCUS,
            ),
        )
    )
    assert resolved["aggregate"] == "BLOCKED"
    resolved_members = resolved["members"]
    assert isinstance(resolved_members, list)
    teams = next(member for member in resolved_members if member["source_lane"] == "teams")
    assert teams["readiness"] == "FAILED"
    assert teams["producer_run_id"] == failed_run_id
    assert teams["artifact_id"] is None
    envelope = run(
        service,
        scene,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.SYNTHESIZER,
            artifact_kind=ArtifactKind.SYNTHESIS_PACKAGE,
            producer_task_id="blocked-synth",
            producer_task_name="blocked",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="blocked",
            body_markdown="no",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="blocked-synth",
            focus_area_id=FOCUS,
            dependency_report_ids=tuple(live_ids),
        ),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.INVALID_REQUEST


def test_search_and_resolve_are_principal_scoped(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-search")
    commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        key="search-c",
        title="UniqueZebraTitle",
        body="collector body",
        focus=FOCUS,
    )
    found = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            SearchIntelligenceArtifacts(query="UniqueZebraTitle", cycle_run_id=cycle),
        )
    )
    items = found["items"]
    assert isinstance(items, list)
    assert len(items) == 1
    other = operator()
    envelope = service.invoke(
        metadata_for(Capability.REPORTS_SEARCH, Purpose.REPORT_READ, other),
        SearchIntelligenceArtifacts(query="UniqueZebraTitle", cycle_run_id=cycle),
        principal=other,
    )
    assert envelope.error is None
    assert envelope.result is not None
    assert envelope.result["items"] == []


def test_read_returns_persisted_structured_content(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-structured")
    structure = {"kind": "opaque", "items": [{"id": "sec-1"}]}
    committed = payload(
        run(
            service,
            scene,
            Purpose.REPORT_AUTHORING,
            CommitIntelligenceArtifact(
                cycle_run_id=cycle,
                stage=IntelligenceStage.COLLECTOR,
                artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES,
                producer_task_id="task-collector",
                producer_task_name="Collector communications",
                automation_platform="abacus_chatllm",
                report_date="2026-08-20",
                title="Collector communications",
                body_markdown="# Collector\n",
                artifact_state=ArtifactState.FINAL,
                schema_version="1",
                idempotency_key="structured-1",
                focus_area_id=FOCUS,
                structured_content=structure,
            ),
        )
    )
    report_id = committed["report_id"]
    assert isinstance(report_id, str)
    read = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ReadIntelligenceArtifact(report_id=report_id),
        )
    )
    assert read["structured_content"] == structure
    assert read["body_markdown"] == "# Collector\n"


def test_list_honors_cursor_and_refuses_a_foreign_one(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-list-cursor")
    first = commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        key="list-a",
        title="Collector A",
        body="a",
        focus=FocusAreaId.COMMUNICATIONS,
    )
    second = commit(
        service,
        scene,
        cycle_run_id=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        key="list-b",
        title="Collector B",
        body="b",
        focus=FocusAreaId.DECISION_APPROVAL,
    )
    page = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ListIntelligenceArtifacts(cycle_run_id=cycle, page_size=1),
        )
    )
    assert len(page["items"]) == 1
    assert page["next_cursor"] in {first["report_id"], second["report_id"]}
    rest = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ListIntelligenceArtifacts(
                cycle_run_id=cycle, page_size=1, cursor=str(page["next_cursor"])
            ),
        )
    )
    assert len(rest["items"]) == 1
    assert rest["items"][0]["report_id"] != page["items"][0]["report_id"]
    other = operator()
    envelope = service.invoke(
        metadata_for(Capability.REPORTS_LIST, Purpose.REPORT_READ, other),
        ListIntelligenceArtifacts(cycle_run_id=cycle, page_size=1, cursor=str(page["next_cursor"])),
        principal=other,
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.INVALID_REQUEST
