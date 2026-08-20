"""Synthetic Morning Intelligence artifact pipeline against the application service."""

from __future__ import annotations

from my_pa.application.commands import (
    BeginIntelligenceCycle,
    CommitIntelligenceArtifact,
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
