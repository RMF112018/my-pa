"""Synthetic Morning Intelligence artifact pipeline against the application service."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.adapters.normalization import normalize
from my_pa.application.commands import (
    BeginIntelligenceCycle,
    CommitIntelligenceArtifact,
    CreateReportType,
    GetLatestIntelligenceArtifact,
    ListIntelligenceArtifacts,
    ListReportTypes,
    ReadIntelligenceArtifact,
    RecordIntelligenceRunState,
    ResolveIntelligenceSet,
    SearchIntelligenceArtifacts,
)
from my_pa.application.errors import (
    ConflictError,
    InvalidRequestError,
    SafeDetail,
    problem_detail,
)
from my_pa.application.intelligence import (
    InMemoryIntelligenceStore,
    commit_artifact,
    record_run_state,
)
from my_pa.application.producer_origin import ProducerOrigin
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    BUILTIN_REPORT_TYPES,
    CYCLE_MORNING_INTELLIGENCE,
    EXPECTED_FOCUS_AREAS,
    EXPECTED_SOURCE_LANES,
    FOCUS_AREA_IDS,
    MAX_ARTIFACT_BODY_BYTES,
    MAX_CLIENT_REPORT_TYPES,
    MAX_MORNING_BRIEF_DEPENDENCY_COUNT,
    REQUIRED_DEPENDENCY_COUNT,
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
    ProducerRunState,
    ReportTypeOrigin,
    ResolverSetId,
    SourceLaneId,
    expected_members,
    parse_artifact_kind,
)
from my_pa.domain.intelligence.errors import (
    IntelligenceConflictError,
    IntelligenceCoordinateError,
)
from my_pa.domain.intelligence.models import (
    ReportTypeDefinition,
    builtin_report_type_definitions,
    content_digest,
)
from my_pa.domain.source.registry import issue_identifier
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


def _focus_branch(
    service: ApplicationService,
    scene: Scene,
    cycle: str,
    focus: FocusAreaId,
    reporter_state: ArtifactState = ArtifactState.FINAL,
) -> str:
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
        state=reporter_state,
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


def test_failed_researcher_lane_exposes_run_id_and_does_not_block_synthesizer(
    scene: Scene,
) -> None:
    """A failed lane is reported (FAILED, with its run id) and is not required.

    Was "blocks synthesizer" under the every-lane-required policy. The four live
    lanes are eligible, so the set is READY and a Synthesizer over exactly those
    four commits; the failed lane has no artifact to name.
    """
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
    assert resolved["aggregate"] == "READY"
    resolved_members = resolved["members"]
    assert isinstance(resolved_members, list)
    teams = next(member for member in resolved_members if member["source_lane"] == "teams")
    assert teams["readiness"] == "FAILED"
    assert teams["producer_run_id"] == failed_run_id
    assert teams["artifact_id"] is None
    assert teams["required"] is False
    envelope = run(
        service,
        scene,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.SYNTHESIZER,
            artifact_kind=ArtifactKind.SYNTHESIS_PACKAGE,
            producer_task_id="four-lane-synth",
            producer_task_name="four lanes",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="four lanes",
            body_markdown="four lanes",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="four-lane-synth",
            focus_area_id=FOCUS,
            dependency_report_ids=tuple(live_ids),
        ),
    )
    assert envelope.error is None, envelope.error


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


# ---- admitted but not expected focus areas ---------------------------------------

#: The three focus areas admitted for commit and run-state recording that no
#: cycle requires. Written out so the test states the operator-accepted set
#: rather than inheriting it from the catalog it checks.
ADMITTED_ONLY: tuple[FocusAreaId, ...] = (
    FocusAreaId.CAPTURES,
    FocusAreaId.NOTES,
    FocusAreaId.FIELD_INTELLIGENCE,
)
ORIGINAL_SIX: tuple[str, ...] = (
    "risk_deadline_exception",
    "decision_approval",
    "communications",
    "project_program_pulse",
    "watchlist_dependency",
    "action_commitment",
)


def test_admitted_only_areas_are_allowed_but_not_expected() -> None:
    assert [area.value for area in ADMITTED_ONLY] == ["captures", "notes", "field_intelligence"]
    assert tuple(area.value for area in FOCUS_AREA_IDS) == (
        *ORIGINAL_SIX,
        "captures",
        "notes",
        "field_intelligence",
    )
    assert tuple(area.value for area in EXPECTED_FOCUS_AREAS) == ORIGINAL_SIX
    # R1: the brief takes at most one reporter per expected area and has no minimum.
    assert IntelligenceStage.MORNING_BRIEF not in REQUIRED_DEPENDENCY_COUNT
    assert len(ORIGINAL_SIX) == MAX_MORNING_BRIEF_DEPENDENCY_COUNT
    for set_id in (ResolverSetId.COLLECTORS, ResolverSetId.MORNING_BRIEF_INPUTS):
        members = expected_members(set_id)
        assert tuple(key for key, _, _ in members) == ORIGINAL_SIX
        assert tuple(area.value for _, area, _ in members if area is not None) == ORIGINAL_SIX
        assert all(lane is None for _, _, lane in members)


def _wire(scene: Scene, capability: Capability, body: dict[str, object]) -> dict[str, object]:
    return {
        "request_id": f"req-{capability.value}",
        "purpose": Purpose.REPORT_AUTHORING.value,
        "principal_id": scene.principal.principal_id,
        "requested_at": "2026-08-20T12:00:00Z",
        "payload": body,
    }


def _wire_commit(cycle: str, focus: str, key: str) -> dict[str, object]:
    return {
        "cycle_run_id": cycle,
        "stage": "collector",
        "artifact_kind": "collector_candidates",
        "focus_area_id": focus,
        "producer_task_id": f"task-{key}",
        "producer_task_name": f"Collector {focus}",
        "automation_platform": "abacus_chatllm",
        "report_date": "2026-08-20",
        "title": f"Collector {focus}",
        "body_markdown": f"collector {focus}",
        "artifact_state": "final",
        "schema_version": "1",
        "idempotency_key": key,
    }


def _wire_run_state(cycle: str, focus: str, key: str) -> dict[str, object]:
    return {
        "cycle_run_id": cycle,
        "stage": "researcher",
        "artifact_kind": "research_context",
        "focus_area_id": focus,
        "source_lane": "teams",
        "producer_task_id": f"task-{key}",
        "producer_task_name": f"Researcher {focus}",
        "automation_platform": "abacus_chatllm",
        "report_date": "2026-08-20",
        "state": "failed",
        "idempotency_key": key,
        "failure_code": "source_unavailable",
    }


@pytest.mark.parametrize("focus", ADMITTED_ONLY, ids=lambda area: area.value)
def test_admitted_only_area_commits_and_records_run_state_from_the_wire(
    scene: Scene, focus: FocusAreaId
) -> None:
    """`reports.commit` and `reports.record_run_state` admit the area end to end."""
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, f"cycle-wire-{focus.value}")
    metadata, command = normalize(
        Capability.REPORTS_COMMIT.value,
        _wire(
            scene,
            Capability.REPORTS_COMMIT,
            _wire_commit(cycle, focus.value, f"wire-{focus.value}-c"),
        ),
    )
    assert isinstance(command, CommitIntelligenceArtifact)
    assert command.focus_area_id is focus
    committed = payload(service.invoke(metadata, command, principal=scene.principal))
    assert committed["created"] is True
    metadata, command = normalize(
        Capability.REPORTS_RECORD_RUN_STATE.value,
        _wire(
            scene,
            Capability.REPORTS_RECORD_RUN_STATE,
            _wire_run_state(cycle, focus.value, f"wire-{focus.value}-r"),
        ),
    )
    assert isinstance(command, RecordIntelligenceRunState)
    assert command.focus_area_id is focus
    recorded = payload(service.invoke(metadata, command, principal=scene.principal))
    assert recorded["state"] == "failed"
    assert recorded["created"] is True


@pytest.mark.parametrize(
    ("capability", "body"),
    [
        (Capability.REPORTS_COMMIT, _wire_commit),
        (Capability.REPORTS_RECORD_RUN_STATE, _wire_run_state),
    ],
    ids=["commit", "record_run_state"],
)
def test_an_unknown_focus_area_is_still_refused_at_normalization(
    scene: Scene,
    capability: Capability,
    body: object,
) -> None:
    assert callable(body)
    with pytest.raises(InvalidRequestError) as refused:
        normalize(
            capability.value,
            _wire(scene, capability, body("micr_00000000bogus", "bogus", "wire-bogus")),
        )
    assert list(refused.value.safe_details) == ["focus_area_id"]


@pytest.mark.parametrize("focus", ADMITTED_ONLY, ids=lambda area: area.value)
def test_admitted_only_area_runs_its_full_branch(scene: Scene, focus: FocusAreaId) -> None:
    """Collector, five researchers, synthesizer and reporter, with typed dependencies."""
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, f"cycle-branch-{focus.value}")
    reporter = _focus_branch(service, scene, cycle, focus)
    resolved = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ResolveIntelligenceSet(
                cycle_run_id=cycle, set_id=ResolverSetId.REPORTER_INPUT, focus_area_id=focus
            ),
        )
    )
    assert resolved["aggregate"] == "READY"
    read = payload(
        run(service, scene, Purpose.REPORT_READ, ReadIntelligenceArtifact(report_id=reporter))
    )
    assert read["focus_area_id"] == focus.value


def _brief(
    service: ApplicationService,
    scene: Scene,
    cycle: str,
    key: str,
    reporters: tuple[str, ...],
    state: ArtifactState = ArtifactState.FINAL,
) -> ResponseEnvelope:
    return run(
        service,
        scene,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.MORNING_BRIEF,
            artifact_kind=ArtifactKind.MORNING_BRIEF,
            producer_task_id="brief",
            producer_task_name="brief",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="Morning Brief",
            body_markdown="brief body",
            artifact_state=state,
            schema_version="1",
            idempotency_key=key,
            dependency_report_ids=reporters,
        ),
    )


def test_the_morning_brief_takes_only_the_original_six_areas(scene: Scene) -> None:
    """New-area reporters exist in the cycle; the brief neither needs nor accepts them."""
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-brief-six")
    six = tuple(_focus_branch(service, scene, cycle, focus) for focus in EXPECTED_FOCUS_AREAS)
    extra = tuple(_focus_branch(service, scene, cycle, focus) for focus in ADMITTED_ONLY)

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
    assert [member["member_id"] for member in members] == list(ORIGINAL_SIX)
    assert {member["artifact_id"] for member in members} == set(six)

    swapped = _brief(service, scene, cycle, "brief-swapped", (*six[:-1], extra[0]))
    assert swapped.error is not None
    assert swapped.error.code is ErrorCode.INVALID_REQUEST
    added = _brief(service, scene, cycle, "brief-added", (*six, extra[0]))
    assert added.error is not None
    assert added.error.code is ErrorCode.INVALID_REQUEST

    brief = payload(_brief(service, scene, cycle, "brief-six", six))
    assert brief["created"] is True


# --- R1: the Daily Briefing is never blocked by a missing or partial reporter ---

ARTIFACT_STATE_REFUSAL = ("artifact_state",)
BARE_DEPENDENCY_REFUSAL = ("dependency_report_ids",)
STALE_BRIEF_REFUSAL = ("artifact_id",)

#: Per expected focus area: ``final`` / ``partial`` reporter heads; ``absent``
#: (nothing); ``failed`` and ``partial_run`` (a reporter run with no artifact);
#: ``stale`` (a reporter whose synthesizer was rerun); ``superseded`` (a v1
#: reporter replaced by an eligible v2).
AreaSpec = dict[FocusAreaId, str]


def _resolve_brief_inputs(
    service: ApplicationService, scene: Scene, cycle: str
) -> dict[str, object]:
    return payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ResolveIntelligenceSet(cycle_run_id=cycle, set_id=ResolverSetId.MORNING_BRIEF_INPUTS),
        )
    )


def _reporter_run(
    service: ApplicationService, scene: Scene, cycle: str, focus: FocusAreaId, state: str
) -> None:
    payload(
        run(
            service,
            scene,
            Purpose.REPORT_AUTHORING,
            RecordIntelligenceRunState(
                cycle_run_id=cycle,
                stage=IntelligenceStage.REPORTER,
                artifact_kind=ArtifactKind.FOCUS_REPORT,
                producer_task_id=f"task-run-{focus.value}",
                producer_task_name="reporter run",
                automation_platform="abacus_chatllm",
                report_date="2026-08-20",
                state=ProducerRunState(state),
                idempotency_key=f"{cycle}-{focus.value}-run",
                focus_area_id=focus,
                failure_code="source_unavailable" if state == "failed" else None,
            ),
        )
    )


def _brief_areas(
    service: ApplicationService, scene: Scene, cycle: str, spec: AreaSpec
) -> dict[str, tuple[str, ...]]:
    """Build ``spec``; return the eligible heads and the ineligible artifacts by kind."""
    heads: list[str] = []
    stale: list[str] = []
    superseded: list[str] = []
    for focus, kind in spec.items():
        if kind in {"final", "partial"}:
            heads.append(
                _focus_branch(
                    service,
                    scene,
                    cycle,
                    focus,
                    reporter_state=ArtifactState(kind),
                )
            )
        elif kind in {"failed", "partial_run"}:
            _reporter_run(service, scene, cycle, focus, "failed" if kind == "failed" else "partial")
        elif kind == "stale":
            stale.append(_focus_branch(service, scene, cycle, focus))
            researcher_ids = tuple(
                _latest(service, scene, cycle, IntelligenceStage.RESEARCHER, focus=focus, lane=lane)
                for lane in EXPECTED_SOURCE_LANES
            )
            commit(
                service,
                scene,
                cycle_run_id=cycle,
                stage=IntelligenceStage.SYNTHESIZER,
                kind=ArtifactKind.SYNTHESIS_PACKAGE,
                key=f"{cycle}-{focus.value}-s2",
                title="synthesis v2",
                body="synthesis v2",
                focus=focus,
                dependencies=researcher_ids,
            )
        elif kind == "superseded":
            superseded.append(_focus_branch(service, scene, cycle, focus))
            synth_id = _latest(service, scene, cycle, IntelligenceStage.SYNTHESIZER, focus=focus)
            v2 = commit(
                service,
                scene,
                cycle_run_id=cycle,
                stage=IntelligenceStage.REPORTER,
                kind=ArtifactKind.FOCUS_REPORT,
                key=f"{cycle}-{focus.value}-r2",
                title="report v2",
                body="report v2",
                focus=focus,
                dependencies=(synth_id,),
            )
            heads.append(str(v2["report_id"]))
        else:
            assert kind == "absent"
    return {"heads": tuple(heads), "stale": tuple(stale), "superseded": tuple(superseded)}


def _refusal(envelope: ResponseEnvelope) -> tuple[ErrorCode, tuple[str, ...]]:
    assert envelope.error is not None, "expected an error envelope"
    return envelope.error.code, tuple(envelope.error.safe_details)


def _areas(*kinds: str) -> AreaSpec:
    return dict(zip(EXPECTED_FOCUS_AREAS, kinds, strict=False))


@pytest.mark.parametrize(
    ("name", "spec"),
    [
        ("zero", {}),
        ("one-final", _areas("final")),
        ("one-partial", _areas("partial")),
        ("n-mixed", _areas("final", "partial", "final")),
        ("six-one-partial", _areas("final", "final", "partial", "final", "final", "final")),
        ("six-final", _areas(*(["final"] * len(EXPECTED_FOCUS_AREAS)))),
    ],
)
def test_the_brief_commits_over_zero_one_and_n_reporters(
    scene: Scene, name: str, spec: AreaSpec
) -> None:
    """R1: partial whenever an input is partial or an area is uncovered; final only when whole."""
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, f"cycle-r1-{name}")
    reporters = _brief_areas(service, scene, cycle, spec)["heads"]
    complete = len(spec) == len(EXPECTED_FOCUS_AREAS) and set(spec.values()) == {"final"}
    claimed_final = _brief(service, scene, cycle, f"r1-{name}-final", reporters)
    if complete:
        assert payload(claimed_final)["artifact_state"] == "final"
        return
    assert _refusal(claimed_final) == (ErrorCode.INVALID_REQUEST, ARTIFACT_STATE_REFUSAL)
    accepted = payload(
        _brief(service, scene, cycle, f"r1-{name}-partial", reporters, state=ArtifactState.PARTIAL)
    )
    assert accepted["created"] is True
    assert accepted["artifact_state"] == "partial"
    brief = scene.world.intelligence.get_artifact(
        scene.principal.principal_id, str(accepted["report_id"])
    )
    assert brief is not None
    assert {dependency.upstream_artifact_id for dependency in brief.dependencies} == set(reporters)


def test_resolve_set_names_every_gap_and_never_blocks_the_brief(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-r1-gaps")
    empty = _resolve_brief_inputs(service, scene, cycle)
    assert empty["aggregate"] == "DEGRADED"
    assert empty["missing_focus_areas"] == sorted(ORIGINAL_SIX)
    assert empty["partial_focus_areas"] == []
    spec = _areas("final", "partial", "failed", "stale", "absent", "partial_run")
    _brief_areas(service, scene, cycle, spec)
    resolved = _resolve_brief_inputs(service, scene, cycle)
    assert resolved["aggregate"] == "DEGRADED"
    by_area = {
        member["focus_area_id"]: member
        for member in resolved["members"]  # type: ignore[union-attr]
    }
    assert {
        area.value: (by_area[area.value]["readiness"], by_area[area.value]["readiness_reason"])
        for area in EXPECTED_FOCUS_AREAS
    } == {
        EXPECTED_FOCUS_AREAS[0].value: ("READY", "ready"),
        EXPECTED_FOCUS_AREAS[1].value: ("PARTIAL", "eligible_partial"),
        EXPECTED_FOCUS_AREAS[2].value: ("FAILED", "failed"),
        EXPECTED_FOCUS_AREAS[3].value: ("STALE", "stale_upstream"),
        EXPECTED_FOCUS_AREAS[4].value: ("MISSING", "absent"),
        EXPECTED_FOCUS_AREAS[5].value: ("MISSING", "partial_run_without_artifact"),
    }
    assert {member["required"] for member in by_area.values()} == {False}
    assert resolved["missing_focus_areas"] == sorted(
        area.value for area in EXPECTED_FOCUS_AREAS[2:]
    )
    assert resolved["partial_focus_areas"] == [EXPECTED_FOCUS_AREAS[1].value]
    collectors = payload(
        run(
            service,
            scene,
            Purpose.REPORT_READ,
            ResolveIntelligenceSet(cycle_run_id=cycle, set_id=ResolverSetId.COLLECTORS),
        )
    )
    assert collectors["aggregate"] == "BLOCKED"
    assert collectors["missing_focus_areas"] == []
    assert collectors["partial_focus_areas"] == []


def test_ineligible_reporters_are_still_refused_whatever_the_brief_claims(
    scene: Scene,
) -> None:
    """Stale, superseded, cross-cycle, foreign, wrong-stage, duplicate, unexpected: refused."""
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-r1-refused")
    built = _brief_areas(service, scene, cycle, _areas("final", "stale", "superseded", "partial"))
    heads = built["heads"]
    other_cycle = begin(service, scene, "cycle-r1-other")
    elsewhere = _focus_branch(service, scene, other_cycle, EXPECTED_FOCUS_AREAS[4])
    # The stale area's rerun synthesizer: eligible, of an uncited expected area,
    # so only the stage rule can refuse it.
    synthesizer = _latest(
        service, scene, cycle, IntelligenceStage.SYNTHESIZER, focus=EXPECTED_FOCUS_AREAS[1]
    )
    unexpected = _focus_branch(service, scene, cycle, ADMITTED_ONLY[0])
    cases: dict[str, tuple[tuple[str, ...], tuple[ErrorCode, tuple[str, ...]]]] = {
        "stale": ((*heads, built["stale"][0]), (ErrorCode.CONFLICT, STALE_BRIEF_REFUSAL)),
        "superseded": (
            (heads[0], built["superseded"][0]),
            (ErrorCode.CONFLICT, STALE_BRIEF_REFUSAL),
        ),
        "cross-cycle": ((*heads, elsewhere), (ErrorCode.INVALID_REQUEST, BARE_DEPENDENCY_REFUSAL)),
        "wrong-stage": (
            (heads[0], synthesizer),
            (ErrorCode.INVALID_REQUEST, BARE_DEPENDENCY_REFUSAL),
        ),
        # The superseded v1 and its v2 head share a focus area.
        "duplicate-area": (
            (built["superseded"][0], heads[1]),
            (ErrorCode.INVALID_REQUEST, BARE_DEPENDENCY_REFUSAL),
        ),
        "unexpected-area": (
            (*heads, unexpected),
            (ErrorCode.INVALID_REQUEST, BARE_DEPENDENCY_REFUSAL),
        ),
        "over-count": (
            (*heads, built["stale"][0], elsewhere, synthesizer, unexpected),
            (ErrorCode.INVALID_REQUEST, BARE_DEPENDENCY_REFUSAL),
        ),
    }
    for name, (reporters, expected) in cases.items():
        for state in (ArtifactState.PARTIAL, ArtifactState.FINAL):
            outcome = _brief(service, scene, cycle, f"r1-{name}-{state.value}", reporters, state)
            assert _refusal(outcome) == expected, name
    # Another Principal citing this Principal's reporters sees them as absent.
    other = operator()
    scene.world.producer_origins[other.principal_id] = ProducerOrigin(
        principal_id=other.principal_id,
        principal_kind=other.kind,
        method="rule",
        method_version="synthetic-rule-producer.1",
    )
    begin_command = BeginIntelligenceCycle(
        cycle_id=CYCLE_MORNING_INTELLIGENCE, business_date="2026-08-20", idempotency_key="r1-o"
    )
    foreign_cycle = payload(
        service.invoke(
            metadata_for(begin_command.capability, Purpose.REPORT_AUTHORING, other),
            begin_command,
            principal=other,
        )
    )["cycle_run_id"]
    for state in (ArtifactState.PARTIAL, ArtifactState.FINAL):
        foreign = CommitIntelligenceArtifact(
            cycle_run_id=str(foreign_cycle),
            stage=IntelligenceStage.MORNING_BRIEF,
            artifact_kind=ArtifactKind.MORNING_BRIEF,
            producer_task_id="brief",
            producer_task_name="brief",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="foreign",
            body_markdown="foreign",
            artifact_state=state,
            schema_version="1",
            idempotency_key=f"r1-foreign-{state.value}",
            dependency_report_ids=(heads[0],),
        )
        envelope = service.invoke(
            metadata_for(foreign.capability, Purpose.REPORT_AUTHORING, other),
            foreign,
            principal=other,
        )
        assert _refusal(envelope) == (ErrorCode.INVALID_REQUEST, BARE_DEPENDENCY_REFUSAL)
    # The eligible heads alone still commit, as partial: two areas are uncovered.
    accepted = _brief(service, scene, cycle, "r1-eligible", heads, ArtifactState.PARTIAL)
    assert payload(accepted)["created"] is True


RESOLVER_AGREEMENT: dict[str, AreaSpec] = {
    "empty": {},
    "all-final": _areas(*(["final"] * len(EXPECTED_FOCUS_AREAS))),
    "all-final-but-one-stale": _areas("final", "final", "final", "final", "final", "stale"),
    "superseded-heads": _areas("superseded", "final", "final", "final", "final", "superseded"),
    "mixed": _areas("partial", "failed", "final", "absent", "stale", "partial_run"),
    "all-partial": _areas(*(["partial"] * len(EXPECTED_FOCUS_AREAS))),
}


@pytest.mark.parametrize("name", list(RESOLVER_AGREEMENT))
def test_brief_commit_acceptance_equals_the_resolver_gaps(scene: Scene, name: str) -> None:
    """A brief over the resolver's eligible members commits final iff the resolver names no gap."""
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, f"cycle-r1-agree-{name}")
    built = _brief_areas(service, scene, cycle, RESOLVER_AGREEMENT[name])
    resolved = _resolve_brief_inputs(service, scene, cycle)
    rows = resolved["members"]
    assert isinstance(rows, list)
    eligible = tuple(
        str(member["artifact_id"]) for member in rows if member["readiness"] in {"READY", "PARTIAL"}
    )
    assert set(eligible) == set(built["heads"])
    gaps = resolved["missing_focus_areas"], resolved["partial_focus_areas"]
    whole = gaps == ([], [])
    assert resolved["aggregate"] == ("READY" if whole else "DEGRADED")
    final = _brief(service, scene, cycle, f"agree-{name}-final", eligible)
    if whole:
        assert final.error is None, final.error
    else:
        assert _refusal(final) == (ErrorCode.INVALID_REQUEST, ARTIFACT_STATE_REFUSAL)
    # Each ineligible artifact added to the eligible set is refused, never downgraded.
    for index, bad in enumerate((*built["stale"], *built["superseded"])):
        base = tuple(head for head in eligible if _area_of(scene, head) != _area_of(scene, bad))
        refused = _brief(
            service, scene, cycle, f"agree-{name}-bad-{index}", (*base, bad), ArtifactState.PARTIAL
        )
        assert _refusal(refused) == (ErrorCode.CONFLICT, STALE_BRIEF_REFUSAL)
    if whole:
        return
    partial = _brief(
        service, scene, cycle, f"agree-{name}-partial", eligible, ArtifactState.PARTIAL
    )
    assert payload(partial)["created"] is True


def _area_of(scene: Scene, artifact_id: str) -> FocusAreaId | None:
    artifact = scene.world.intelligence.get_artifact(scene.principal.principal_id, artifact_id)
    assert artifact is not None
    return artifact.focus_area_id


# ---- the report type registry: domain and the FAST-tier store ------------------------


def test_parse_artifact_kind_keeps_builtins_as_members_and_validates_tokens() -> None:
    for kind in ArtifactKind:
        assert parse_artifact_kind(kind.value) is kind
    parsed = parse_artifact_kind("weekly_digest")
    assert parsed == "weekly_digest"
    assert type(parsed) is str
    assert parse_artifact_kind("w" * 64) == "w" * 64
    for bad in ("", "Weekly", "9weekly", "weekly-digest", "weekly digest", "w" * 65, None, 7):
        with pytest.raises(ValueError, match="artifact_kind"):
            parse_artifact_kind(bad)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"artifact_kind": "Weekly"}, "artifact_kind"),
        ({"description": ""}, "description"),
        ({"description": "d" * 501}, "description"),
        ({"display_name": ""}, "display name"),
        ({"display_name": "n" * 121}, "display name"),
        ({"artifact_kind": "focus_report"}, "built-in"),
        ({"origin": ReportTypeOrigin.BUILTIN}, "built-in"),
        (
            {"origin": ReportTypeOrigin.BUILTIN, "artifact_kind": "morning_brief"},
            "built-in",
        ),
        ({"stage": "reporter"}, "stage"),
    ],
)
def test_a_report_type_definition_refuses_each_malformed_field(
    overrides: dict[str, object], message: str
) -> None:
    fields: dict[str, object] = {
        "artifact_kind": "weekly_digest",
        "stage": IntelligenceStage.REPORTER,
        "description": "A weekly digest.",
        "origin": ReportTypeOrigin.CLIENT,
        "display_name": None,
        **overrides,
    }
    with pytest.raises(ValueError, match=message):
        ReportTypeDefinition(**fields)  # type: ignore[arg-type]


def test_the_builtin_definitions_are_the_five_pairs_and_fingerprint_stably() -> None:
    definitions = builtin_report_type_definitions()
    assert [(d.artifact_kind, d.stage) for d in definitions] == [
        (kind, stage) for kind, stage, _, _ in BUILTIN_REPORT_TYPES
    ]
    assert all(d.origin is ReportTypeOrigin.BUILTIN for d in definitions)
    assert all(isinstance(d.artifact_kind, ArtifactKind) for d in definitions)
    assert len({d.fingerprint for d in definitions}) == 5
    weekly = ReportTypeDefinition(
        artifact_kind="weekly_digest",
        stage=IntelligenceStage.REPORTER,
        description="A weekly digest.",
        origin=ReportTypeOrigin.CLIENT,
    )
    renamed = ReportTypeDefinition(
        artifact_kind="weekly_digest",
        stage=IntelligenceStage.REPORTER,
        description="A weekly digest.",
        origin=ReportTypeOrigin.CLIENT,
        display_name="Weekly",
    )
    assert weekly.fingerprint != renamed.fingerprint
    assert (
        weekly.fingerprint
        == ReportTypeDefinition(
            artifact_kind="weekly_digest",
            stage=IntelligenceStage.REPORTER,
            description="A weekly digest.",
            origin=ReportTypeOrigin.CLIENT,
        ).fingerprint
    )


def test_the_in_memory_registry_is_idempotent_ordered_and_principal_isolated() -> None:
    when = datetime(2026, 10, 11, 12, tzinfo=UTC)
    store = InMemoryIntelligenceStore()
    owner = operator().principal_id
    other = operator().principal_id
    weekly = ReportTypeDefinition(
        artifact_kind="weekly_digest",
        stage=IntelligenceStage.REPORTER,
        description="A weekly digest.",
        origin=ReportTypeOrigin.CLIENT,
    )
    first = store.insert_report_type(owner, weekly, created_at=when)
    assert first.inserted is True
    assert first.report_type.definition_fingerprint == weekly.fingerprint
    replay = store.insert_report_type(
        owner,
        ReportTypeDefinition(
            artifact_kind="weekly_digest",
            stage=IntelligenceStage.REPORTER,
            description="Changed.",
            origin=ReportTypeOrigin.CLIENT,
        ),
        created_at=when,
    )
    assert replay.inserted is False
    assert replay.report_type == first.report_type
    assert store.ensure_builtin_report_types(owner, created_at=when) == 5
    assert store.ensure_builtin_report_types(owner, created_at=when) == 0
    listed = store.list_report_types(owner)
    assert [(r.definition.stage.value, str(r.definition.artifact_kind)) for r in listed] == sorted(
        [(stage.value, kind.value) for kind, stage, _, _ in BUILTIN_REPORT_TYPES]
        + [("reporter", "weekly_digest")]
    )
    assert [
        str(r.definition.artifact_kind)
        for r in store.list_report_types(owner, stage=IntelligenceStage.REPORTER)
    ] == ["focus_report", "weekly_digest"]
    assert store.list_report_types(other) == ()
    assert store.get_report_type(other, "weekly_digest") is None
    assert store.get_report_type(owner, "weekly_digest") == first.report_type


# --- R2/R3: the per-Principal report type registry ---------------------------


def _as(
    service: ApplicationService, principal: Principal, purpose: Purpose, command: object
) -> ResponseEnvelope:
    return service.invoke(
        metadata_for(command.capability, purpose, principal),  # type: ignore[attr-defined]
        command,  # type: ignore[arg-type]
        principal=principal,
    )


def _register(
    service: ApplicationService,
    principal: Principal,
    kind: str,
    stage: IntelligenceStage,
    description: str = "A synthetic client report type.",
    display_name: str | None = None,
) -> ResponseEnvelope:
    return _as(
        service,
        principal,
        Purpose.REPORT_AUTHORING,
        CreateReportType(
            artifact_kind=kind, stage=stage, description=description, display_name=display_name
        ),
    )


def _types(
    service: ApplicationService, principal: Principal, stage: IntelligenceStage | None = None
) -> list[dict[str, object]]:
    listed = payload(_as(service, principal, Purpose.REPORT_READ, ListReportTypes(stage=stage)))
    report_types = listed["report_types"]
    assert isinstance(report_types, list)
    return report_types


def _commit_kind(
    service: ApplicationService,
    principal: Principal,
    *,
    cycle: str,
    stage: IntelligenceStage,
    kind: str,
    key: str,
    focus: FocusAreaId | None = FOCUS,
    lane: SourceLaneId | None = None,
    dependencies: tuple[str, ...] = (),
    state: ArtifactState = ArtifactState.FINAL,
) -> ResponseEnvelope:
    return _as(
        service,
        principal,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=stage,
            artifact_kind=kind,
            producer_task_id=f"task-{kind}",
            producer_task_name=f"Producer {kind}",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title=f"Artifact {kind}",
            body_markdown=f"body {kind}",
            artifact_state=state,
            schema_version="1",
            idempotency_key=key,
            focus_area_id=focus,
            source_lane=lane,
            dependency_report_ids=dependencies,
        ),
    )


def _allowed(envelope: ResponseEnvelope) -> dict[str, list[str]]:
    assert envelope.error is not None, "expected an error envelope"
    return {entry.detail: list(entry.values) for entry in envelope.error.allowed_values}


def _builtin_row(kind: ArtifactKind) -> dict[str, object]:
    (definition,) = [d for d in builtin_report_type_definitions() if d.artifact_kind is kind]
    return {
        "artifact_kind": kind.value,
        "stage": definition.stage.value,
        "description": definition.description,
        "display_name": definition.display_name,
        "origin": "builtin",
    }


def test_report_types_create_lists_and_replays_an_identical_definition(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    principal = scene.principal
    assert [row["artifact_kind"] for row in _types(service, principal)] == [
        kind.value for kind, _stage, _d, _n in BUILTIN_REPORT_TYPES
    ]
    created = payload(
        _register(
            service, principal, "weekly_digest", IntelligenceStage.REPORTER, "Weekly.", "Weekly"
        )
    )
    weekly = {
        "artifact_kind": "weekly_digest",
        "stage": "reporter",
        "description": "Weekly.",
        "display_name": "Weekly",
        "origin": "client",
    }
    assert created == {**weekly, "created": True, "replayed": False}
    replayed = payload(
        _register(
            service, principal, "weekly_digest", IntelligenceStage.REPORTER, "Weekly.", "Weekly"
        )
    )
    assert replayed == {**weekly, "created": False, "replayed": True}
    payload(_register(service, principal, "alpha_scan", IntelligenceStage.COLLECTOR))
    # Pipeline-stage order, the built-in kind first within a stage, then by kind.
    assert [(row["stage"], row["artifact_kind"]) for row in _types(service, principal)] == [
        ("collector", "collector_candidates"),
        ("collector", "alpha_scan"),
        ("researcher", "research_context"),
        ("synthesizer", "synthesis_package"),
        ("reporter", "focus_report"),
        ("reporter", "weekly_digest"),
        ("morning_brief", "morning_brief"),
    ]
    assert _types(service, principal, IntelligenceStage.REPORTER) == [
        _builtin_row(ArtifactKind.FOCUS_REPORT),
        weekly,
    ]
    # The registry is the acting Principal's own: another sees only the built-ins.
    other = operator()
    assert [row["origin"] for row in _types(service, other)] == ["builtin"] * 5
    # The stored registry carries the built-in rows beside the client ones.
    stored = scene.world.intelligence.list_report_types(principal.principal_id)
    assert {str(row.definition.artifact_kind) for row in stored} == {
        *(kind.value for kind in ArtifactKind),
        "weekly_digest",
        "alpha_scan",
    }


def test_a_different_definition_or_a_builtin_kind_is_a_conflict(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    payload(_register(service, scene.principal, "weekly_digest", IntelligenceStage.REPORTER))
    for envelope in (
        _register(service, scene.principal, "weekly_digest", IntelligenceStage.COLLECTOR),
        _register(service, scene.principal, "weekly_digest", IntelligenceStage.REPORTER, "Other."),
        _register(
            service,
            scene.principal,
            "weekly_digest",
            IntelligenceStage.REPORTER,
            display_name="Named now",
        ),
        _register(service, scene.principal, "focus_report", IntelligenceStage.REPORTER),
        _register(service, scene.principal, "morning_brief", IntelligenceStage.COLLECTOR),
    ):
        assert _refusal(envelope) == (ErrorCode.CONFLICT, ("artifact_kind",))
        assert envelope.error is not None and envelope.error.allowed_values == ()
    # Nothing was rewritten.
    (row,) = [r for r in _types(service, scene.principal) if r["artifact_kind"] == "weekly_digest"]
    assert (row["stage"], row["description"], row["display_name"]) == (
        "reporter",
        "A synthetic client report type.",
        None,
    )


@pytest.mark.parametrize(
    ("fields", "detail", "allowed"),
    [
        ({"artifact_kind": "Weekly Digest"}, "artifact_kind", None),
        ({"artifact_kind": "9weekly"}, "artifact_kind", None),
        ({"artifact_kind": "w" * 65}, "artifact_kind", None),
        ({"stage": "editor"}, "stage", [stage.value for stage in IntelligenceStage]),
        ({"description": ""}, "description", None),
        ({"description": "d" * 501}, "description", None),
        ({"display_name": "n" * 121}, "display_name", None),
    ],
)
def test_report_types_create_refuses_each_malformed_field(
    fields: dict[str, object], detail: str, allowed: list[str] | None
) -> None:
    """A malformed token lists nothing; an unknown stage lists the five stages."""
    principal = operator()
    request = {
        "contract_version": "v1",
        "request_id": "req-types-create",
        "purpose": Purpose.REPORT_AUTHORING.value,
        "principal_id": principal.principal_id,
        "requested_at": "2026-10-11T12:00:00Z",
        "payload": {
            "artifact_kind": "weekly_digest",
            "stage": "reporter",
            "description": "A synthetic client report type.",
            **fields,
        },
    }
    with pytest.raises(InvalidRequestError) as refused:
        normalize(Capability.REPORTS_TYPES_CREATE.value, request)
    assert refused.value.safe_details == (SafeDetail(detail),)
    expected = {} if allowed is None else {SafeDetail(detail): tuple(allowed)}
    assert dict(refused.value.allowed_values) == expected


def test_a_client_kind_commits_at_its_stage_and_is_refused_at_another(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    principal = scene.principal
    payload(_register(service, principal, "alpha_scan", IntelligenceStage.COLLECTOR))
    payload(_register(service, principal, "lane_notes", IntelligenceStage.RESEARCHER))
    cycle = begin(service, scene, "cycle-client-kind")
    committed = payload(
        _commit_kind(
            service,
            principal,
            cycle=cycle,
            stage=IntelligenceStage.COLLECTOR,
            kind="alpha_scan",
            key="client-kind-c",
        )
    )
    assert committed["artifact_kind"] == "alpha_scan"
    assert committed["stage"] == "collector"
    report_id = committed["report_id"]
    assert isinstance(report_id, str)
    # A client kind is a standalone report with its own head: it never becomes
    # the stage's built-in head, and citing it as a dependency is refused for a
    # client and a built-in researcher alike (the bare dependency refusal).
    for kind, key in (("lane_notes", "client-dep"), ("research_context", "builtin-dep")):
        cited = _commit_kind(
            service,
            principal,
            cycle=cycle,
            stage=IntelligenceStage.RESEARCHER,
            kind=kind,
            key=key,
            lane=SourceLaneId.TEAMS,
            dependencies=(report_id,),
        )
        assert _refusal(cited) == (ErrorCode.INVALID_REQUEST, ("dependency_report_ids",))
    # A client researcher takes the built-in researcher's upstream: the built-in
    # collector head, never the client collector committed beside it.
    collector = payload(
        _commit_kind(
            service,
            principal,
            cycle=cycle,
            stage=IntelligenceStage.COLLECTOR,
            kind="collector_candidates",
            key="builtin-collector",
        )
    )
    lane_notes = payload(
        _commit_kind(
            service,
            principal,
            cycle=cycle,
            stage=IntelligenceStage.RESEARCHER,
            kind="lane_notes",
            key="client-kind-r",
            lane=SourceLaneId.TEAMS,
            dependencies=(str(collector["report_id"]),),
        )
    )
    assert lane_notes["artifact_kind"] == "lane_notes"
    # Each kind kept its own head at the collector coordinate.
    collector_id = collector["report_id"]
    for kind, expected in (("alpha_scan", report_id), ("collector_candidates", collector_id)):
        head = payload(
            _as(
                service,
                principal,
                Purpose.REPORT_READ,
                GetLatestIntelligenceArtifact(cycle_run_id=cycle, artifact_kind=kind),
            )
        )
        assert head["report_id"] == expected
        assert head["artifact_state"] == "final"
    read = payload(
        _as(service, principal, Purpose.REPORT_READ, ReadIntelligenceArtifact(report_id))
    )
    assert read["artifact_kind"] == "alpha_scan"
    latest = payload(
        _as(
            service,
            principal,
            Purpose.REPORT_READ,
            GetLatestIntelligenceArtifact(cycle_run_id=cycle, artifact_kind="alpha_scan"),
        )
    )
    assert latest["report_id"] == report_id
    listed = payload(
        _as(
            service,
            principal,
            Purpose.REPORT_READ,
            ListIntelligenceArtifacts(cycle_run_id=cycle, artifact_kind="alpha_scan"),
        )
    )
    assert [item["report_id"] for item in listed["items"]] == [report_id]  # type: ignore[union-attr]
    found = payload(
        _as(
            service,
            principal,
            Purpose.REPORT_READ,
            SearchIntelligenceArtifacts(query="alpha_scan", artifact_kind="alpha_scan"),
        )
    )
    assert [item["report_id"] for item in found["items"]] == [report_id]  # type: ignore[union-attr]
    recorded = payload(
        _as(
            service,
            principal,
            Purpose.REPORT_AUTHORING,
            RecordIntelligenceRunState(
                cycle_run_id=cycle,
                stage=IntelligenceStage.COLLECTOR,
                artifact_kind="alpha_scan",
                producer_task_id="task-alpha",
                producer_task_name="alpha",
                automation_platform="abacus_chatllm",
                report_date="2026-08-20",
                state=ProducerRunState.SUCCEEDED,
                idempotency_key="client-kind-run",
                focus_area_id=FOCUS,
            ),
        )
    )
    assert recorded["state"] == "succeeded"

    # At another stage the kind is refused, listing the kinds of *that* stage.
    misplaced = _commit_kind(
        service,
        principal,
        cycle=cycle,
        stage=IntelligenceStage.RESEARCHER,
        kind="alpha_scan",
        key="client-kind-misplaced",
        lane=SourceLaneId.TEAMS,
        dependencies=(report_id,),
    )
    assert _refusal(misplaced) == (ErrorCode.INVALID_REQUEST, ("stage", "artifact_kind"))
    assert _allowed(misplaced) == {"artifact_kind": ["research_context", "lane_notes"]}
    run_misplaced = _as(
        service,
        principal,
        Purpose.REPORT_AUTHORING,
        RecordIntelligenceRunState(
            cycle_run_id=cycle,
            stage=IntelligenceStage.REPORTER,
            artifact_kind="alpha_scan",
            producer_task_id="task-alpha",
            producer_task_name="alpha",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            state=ProducerRunState.FAILED,
            idempotency_key="client-kind-run-misplaced",
            focus_area_id=FOCUS,
        ),
    )
    assert _refusal(run_misplaced) == (ErrorCode.INVALID_REQUEST, ("stage", "artifact_kind"))
    assert _allowed(run_misplaced) == {"artifact_kind": ["focus_report"]}


def test_a_builtin_kind_at_the_wrong_stage_lists_that_stages_kinds(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    cycle = begin(service, scene, "cycle-builtin-misplaced")
    refused = _commit_kind(
        service,
        scene.principal,
        cycle=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind="focus_report",
        key="builtin-misplaced",
    )
    assert _refusal(refused) == (ErrorCode.INVALID_REQUEST, ("stage", "artifact_kind"))
    assert _allowed(refused) == {"artifact_kind": ["collector_candidates"]}


def test_an_unregistered_kind_lists_only_the_acting_principals_kinds(scene: Scene) -> None:
    """R3 isolation: Principal B's kind never reaches Principal A's refusal, or the reverse."""
    service = build_service(scene.world, scene.providers)
    alice = scene.principal
    bob = operator()
    payload(_register(service, alice, "alice_scan", IntelligenceStage.COLLECTOR))
    payload(_register(service, bob, "bob_secret_scan", IntelligenceStage.COLLECTOR))
    payload(_register(service, bob, "bob_secret_brief", IntelligenceStage.MORNING_BRIEF))
    cycle = begin(service, scene, "cycle-unregistered")

    # Bob's kind is unregistered for Alice, at commit and as a read filter.
    refused = _commit_kind(
        service,
        alice,
        cycle=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind="bob_secret_scan",
        key="alice-uses-bob",
    )
    assert _refusal(refused) == (ErrorCode.INVALID_REQUEST, ("artifact_kind",))
    assert _allowed(refused) == {"artifact_kind": ["collector_candidates", "alice_scan"]}
    filtered = _as(
        service,
        alice,
        Purpose.REPORT_READ,
        ListIntelligenceArtifacts(artifact_kind="bob_secret_brief"),
    )
    assert _refusal(filtered) == (ErrorCode.INVALID_REQUEST, ("artifact_kind",))
    every_kind = [
        "collector_candidates",
        "alice_scan",
        "research_context",
        "synthesis_package",
        "focus_report",
        "morning_brief",
    ]
    assert _allowed(filtered) == {"artifact_kind": every_kind}
    staged = _as(
        service,
        alice,
        Purpose.REPORT_READ,
        SearchIntelligenceArtifacts(
            query="x", stage=IntelligenceStage.COLLECTOR, artifact_kind="never_registered"
        ),
    )
    assert _allowed(staged) == {"artifact_kind": ["collector_candidates", "alice_scan"]}
    latest = _as(
        service,
        alice,
        Purpose.REPORT_READ,
        GetLatestIntelligenceArtifact(cycle_run_id=cycle, artifact_kind="bob_secret_scan"),
    )
    assert _allowed(latest) == {"artifact_kind": every_kind}
    for envelope in (refused, filtered, staged, latest):
        assert "bob_secret" not in envelope.model_dump_json()

    # And Alice's kind is unregistered for Bob.
    bobs = _as(
        service, bob, Purpose.REPORT_READ, ListIntelligenceArtifacts(artifact_kind="alice_scan")
    )
    assert _allowed(bobs) == {
        "artifact_kind": [
            "collector_candidates",
            "bob_secret_scan",
            "research_context",
            "synthesis_package",
            "focus_report",
            "morning_brief",
            "bob_secret_brief",
        ]
    }
    assert "alice_scan" not in bobs.model_dump_json()


def test_the_client_type_cap_is_enforced_and_an_existing_kind_still_replays(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    for index in range(MAX_CLIENT_REPORT_TYPES):
        payload(
            _register(service, scene.principal, f"kind_{index:02d}", IntelligenceStage.REPORTER)
        )
    full = _register(service, scene.principal, "one_too_many", IntelligenceStage.REPORTER)
    assert _refusal(full) == (ErrorCode.CONFLICT, ("artifact_kind", "max_items"))
    assert (
        payload(_register(service, scene.principal, "kind_00", IntelligenceStage.REPORTER))[
            "replayed"
        ]
        is True
    )
    assert len(_types(service, scene.principal)) == 5 + MAX_CLIENT_REPORT_TYPES
    # A full registry still bounds the listing a refusal carries: truncated at 64.
    refused = _commit_kind(
        service,
        scene.principal,
        cycle=begin(service, scene, "cycle-cap"),
        stage=IntelligenceStage.REPORTER,
        kind="not_registered",
        key="cap-unregistered",
    )
    assert refused.error is not None
    (entry,) = refused.error.allowed_values
    assert entry.detail == "artifact_kind" and entry.truncated is True
    assert len(entry.values) == 64 and entry.values[0] == "focus_report"
    # Another Principal is not affected by this one's cap.
    assert (
        payload(_register(service, operator(), "one_too_many", IntelligenceStage.REPORTER))[
            "created"
        ]
        is True
    )


def _latest_of(
    service: ApplicationService,
    principal: Principal,
    cycle: str,
    kind: str,
    focus: FocusAreaId | None = None,
) -> dict[str, object]:
    return payload(
        _as(
            service,
            principal,
            Purpose.REPORT_READ,
            GetLatestIntelligenceArtifact(
                cycle_run_id=cycle, artifact_kind=kind, focus_area_id=focus
            ),
        )
    )


def test_a_client_brief_kind_never_displaces_the_builtin_daily_briefing(scene: Scene) -> None:
    """F1 (a): heads are per kind, so a client kind at `morning_brief` has its own lineage.

    The final built-in brief over six final reporters stays the built-in head
    after a client brief kind commits at the same stage, and the client kind
    takes the Daily Briefing's own rules: zero to six built-in reporters,
    partial forced on gaps, a false `final` refused.
    """
    service = build_service(scene.world, scene.providers)
    principal = scene.principal
    payload(_register(service, principal, "weekly_brief", IntelligenceStage.MORNING_BRIEF))
    cycle = begin(service, scene, "cycle-client-brief")
    heads = tuple(_focus_branch(service, scene, cycle, focus) for focus in EXPECTED_FOCUS_AREAS)
    builtin = payload(_brief(service, scene, cycle, "builtin-brief", heads))
    assert builtin["artifact_state"] == "final"

    # The client kind with zero reporters: a gap, so `final` is refused ...
    false_final = _commit_kind(
        service,
        principal,
        cycle=cycle,
        stage=IntelligenceStage.MORNING_BRIEF,
        kind="weekly_brief",
        key="client-brief-final",
        focus=None,
    )
    assert _refusal(false_final) == (ErrorCode.INVALID_REQUEST, ARTIFACT_STATE_REFUSAL)
    # ... and `partial` is admitted, as its own lineage's first version.
    client = payload(
        _commit_kind(
            service,
            principal,
            cycle=cycle,
            stage=IntelligenceStage.MORNING_BRIEF,
            kind="weekly_brief",
            key="client-brief-partial",
            focus=None,
            state=ArtifactState.PARTIAL,
        )
    )
    assert (client["version"], client["supersedes_report_id"]) == (1, None)

    latest_builtin = _latest_of(service, principal, cycle, "morning_brief")
    assert latest_builtin["report_id"] == builtin["report_id"]
    assert latest_builtin["artifact_state"] == "final"
    latest_client = _latest_of(service, principal, cycle, "weekly_brief")
    assert latest_client["report_id"] == client["report_id"]
    assert latest_client["artifact_state"] == "partial"

    # Over the six built-in final reporters the client kind may be final, and it
    # supersedes only its own previous head.
    client_v2 = payload(
        _commit_kind(
            service,
            principal,
            cycle=cycle,
            stage=IntelligenceStage.MORNING_BRIEF,
            kind="weekly_brief",
            key="client-brief-v2",
            focus=None,
            dependencies=heads,
        )
    )
    assert (client_v2["version"], client_v2["supersedes_report_id"]) == (2, client["report_id"])
    latest_builtin = _latest_of(service, principal, cycle, "morning_brief")
    assert latest_builtin["report_id"] == builtin["report_id"]
    # A built-in rerun supersedes the built-in head, never the client one.
    builtin_v2 = payload(_brief(service, scene, cycle, "builtin-brief-v2", heads))
    assert (builtin_v2["version"], builtin_v2["supersedes_report_id"]) == (2, builtin["report_id"])
    latest_client = _latest_of(service, principal, cycle, "weekly_brief")
    assert latest_client["report_id"] == client_v2["report_id"]


def test_a_client_reporter_kind_never_displaces_the_builtin_focus_report(scene: Scene) -> None:
    """F1 (b): a client reporter kind keeps its own head; the Daily Briefing never sees it."""
    service = build_service(scene.world, scene.providers)
    principal = scene.principal
    payload(_register(service, principal, "client_focus_report", IntelligenceStage.REPORTER))
    cycle = begin(service, scene, "cycle-client-reporter")
    heads = tuple(_focus_branch(service, scene, cycle, focus) for focus in EXPECTED_FOCUS_AREAS)
    last = EXPECTED_FOCUS_AREAS[-1]
    synth_id = _latest(service, scene, cycle, IntelligenceStage.SYNTHESIZER, focus=last)
    client = payload(
        _commit_kind(
            service,
            principal,
            cycle=cycle,
            stage=IntelligenceStage.REPORTER,
            kind="client_focus_report",
            key="client-reporter",
            focus=last,
            dependencies=(synth_id,),
        )
    )
    assert (client["version"], client["supersedes_report_id"]) == (1, None)
    builtin_head = _latest_of(service, principal, cycle, "focus_report", last)
    assert builtin_head["report_id"] == heads[-1]
    assert builtin_head["artifact_state"] == "final"
    assert (
        _latest_of(service, principal, cycle, "client_focus_report", last)["report_id"]
        == (client["report_id"])
    )
    # `morning_brief_inputs` and the brief commit still see the built-in reporter.
    resolved = _resolve_brief_inputs(service, scene, cycle)
    assert resolved["aggregate"] == "READY"
    by_area = {m["focus_area_id"]: m for m in resolved["members"]}  # type: ignore[union-attr]
    assert by_area[last.value]["artifact_id"] == heads[-1]
    assert by_area[last.value]["readiness"] == "READY"
    brief = payload(_brief(service, scene, cycle, "brief-over-builtins", heads))
    assert brief["artifact_state"] == "final"


def test_a_client_kind_cited_as_a_dependency_is_refused(scene: Scene) -> None:
    """F1 (c): client kinds are standalone; no commit, built-in or client, consumes one."""
    service = build_service(scene.world, scene.providers)
    principal = scene.principal
    payload(_register(service, principal, "client_focus_report", IntelligenceStage.REPORTER))
    payload(_register(service, principal, "weekly_brief", IntelligenceStage.MORNING_BRIEF))
    cycle = begin(service, scene, "cycle-client-dependency")
    heads = tuple(_focus_branch(service, scene, cycle, focus) for focus in EXPECTED_FOCUS_AREAS)
    last = EXPECTED_FOCUS_AREAS[-1]
    synth_id = _latest(service, scene, cycle, IntelligenceStage.SYNTHESIZER, focus=last)
    client_id = str(
        payload(
            _commit_kind(
                service,
                principal,
                cycle=cycle,
                stage=IntelligenceStage.REPORTER,
                kind="client_focus_report",
                key="client-reporter-dep",
                focus=last,
                dependencies=(synth_id,),
            )
        )["report_id"]
    )
    cited = (*heads[:-1], client_id)
    for state in (ArtifactState.FINAL, ArtifactState.PARTIAL):
        refused = _brief(service, scene, cycle, f"builtin-cites-client-{state.value}", cited, state)
        assert _refusal(refused) == (ErrorCode.INVALID_REQUEST, BARE_DEPENDENCY_REFUSAL)
        client_brief = _commit_kind(
            service,
            principal,
            cycle=cycle,
            stage=IntelligenceStage.MORNING_BRIEF,
            kind="weekly_brief",
            key=f"client-cites-client-{state.value}",
            focus=None,
            dependencies=(client_id,),
            state=state,
        )
        assert _refusal(client_brief) == (ErrorCode.INVALID_REQUEST, BARE_DEPENDENCY_REFUSAL)
    # Nothing was committed at the brief stage.
    listed = payload(
        _as(
            service,
            principal,
            Purpose.REPORT_READ,
            ListIntelligenceArtifacts(cycle_run_id=cycle, stage=IntelligenceStage.MORNING_BRIEF),
        )
    )
    assert listed["items"] == []


def test_an_invalid_purpose_lists_the_purposes_the_capability_permits() -> None:
    """R3: the one envelope vocabulary, listed for the capability that was named."""
    principal = operator()
    for capability, permitted in (
        (Capability.REPORTS_TYPES_CREATE, ["report_authoring"]),
        (Capability.REPORTS_TYPES_LIST, ["report_read"]),
        (
            Capability.CAPABILITIES_GET,
            [p.value for p in Purpose if p in permitted_purposes(Capability.CAPABILITIES_GET)],
        ),
    ):
        for bad in ("not_a_purpose", 7, None):
            request = {
                "contract_version": "v1",
                "request_id": "req-bad-purpose",
                "principal_id": principal.principal_id,
                "requested_at": "2026-10-11T12:00:00Z",
                "payload": {},
            }
            if bad is not None:
                request["purpose"] = bad
            with pytest.raises(InvalidRequestError) as refused:
                normalize(capability.value, request)
            assert refused.value.safe_details == (SafeDetail.PURPOSE,)
            assert dict(refused.value.allowed_values) == {SafeDetail.PURPOSE: tuple(permitted)}
            rendered = problem_detail(
                refused.value, correlation_id=issue_identifier(IdKind.CORRELATION)
            ).model_dump_json()
            assert "not_a_purpose" not in rendered
    # A valid purpose with another envelope fault keeps the bare refusal.
    with pytest.raises(InvalidRequestError) as bare:
        normalize(
            Capability.REPORTS_TYPES_LIST.value,
            {
                "contract_version": "v1",
                "request_id": "",
                "purpose": "report_read",
                "principal_id": principal.principal_id,
                "requested_at": "2026-10-11T12:00:00Z",
                "payload": {},
            },
        )
    assert bare.value.safe_details == ()
    assert dict(bare.value.allowed_values) == {}


def test_the_report_commands_check_the_kind_token_and_accept_any_well_formed_one() -> None:
    """The command layer, without normalization: shape here, registration in the application."""
    for bad in ("Weekly", "", "w" * 65, 7, None):
        with pytest.raises(InvalidRequestError) as refused:
            CreateReportType(
                artifact_kind=bad,  # type: ignore[arg-type]
                stage=IntelligenceStage.REPORTER,
                description="A synthetic client report type.",
            )
        assert refused.value.safe_details == (SafeDetail.ARTIFACT_KIND,)
        with pytest.raises(InvalidRequestError) as listed:
            ListIntelligenceArtifacts(artifact_kind=bad if bad is not None else "Bad")  # type: ignore[arg-type]
        assert listed.value.safe_details == (SafeDetail.ARTIFACT_KIND,)
    accepted = ListIntelligenceArtifacts(artifact_kind="weekly_digest")
    assert accepted.artifact_kind == "weekly_digest"
    assert ListIntelligenceArtifacts(artifact_kind="focus_report").artifact_kind is (
        ArtifactKind.FOCUS_REPORT
    )


class _FaultingRegistryStore(InMemoryIntelligenceStore):
    """A store whose registry lookup fails with the given error."""

    def __init__(self, fault: Exception) -> None:
        super().__init__()
        self.fault = fault

    def get_report_type(self, principal_id: str, artifact_kind: str) -> None:  # type: ignore[override]
        raise self.fault


@pytest.mark.parametrize("operation", ["commit", "record_run_state"])
def test_a_registry_lookup_fault_is_handled_like_every_other_store_fault(operation: str) -> None:
    """F6: the kind lookup runs inside the translated block of both writes.

    A plane error from the lookup is translated exactly as one from any later
    store call; any other fault propagates unchanged, as it always has.
    """
    common = {
        "principal_id": operator().principal_id,
        "cycle_run_id": "micr_faultfault0001",
        "stage": IntelligenceStage.COLLECTOR,
        "artifact_kind": "client_scan",
        "focus_area_id": FOCUS,
        "source_lane": None,
        "producer_task_id": "task",
        "producer_task_name": "task",
        "automation_platform": "abacus_chatllm",
        "automation_run_id": None,
        "report_date": datetime(2026, 8, 20, tzinfo=UTC).date(),
        "idempotency_key": "fault",
        "at": datetime(2026, 8, 20, 12, tzinfo=UTC),
    }

    def invoke(store: InMemoryIntelligenceStore) -> object:
        if operation == "commit":
            return commit_artifact(
                store,
                title="t",
                body_markdown="b",
                artifact_state=ArtifactState.FINAL,
                schema_version="1",
                **common,  # type: ignore[arg-type]
            )
        return record_run_state(
            store,
            state=ProducerRunState.FAILED,
            expected_version=None,
            failure_code=None,
            failure_summary=None,
            **common,  # type: ignore[arg-type]
        )

    with pytest.raises(InvalidRequestError) as translated:
        invoke(_FaultingRegistryStore(IntelligenceCoordinateError()))
    assert translated.value.safe_details == (SafeDetail.STAGE,)
    with pytest.raises(ConflictError) as conflict:
        invoke(_FaultingRegistryStore(IntelligenceConflictError()))
    assert conflict.value.safe_details == (SafeDetail.CYCLE_RUN_ID,)
    fault = RuntimeError("store unavailable")
    with pytest.raises(RuntimeError) as unchanged:
        invoke(_FaultingRegistryStore(fault))
    assert unchanged.value is fault
