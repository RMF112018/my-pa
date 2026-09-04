"""Intelligence Artifact plane against disposable PostgreSQL at Alembic head."""

from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text

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
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    CYCLE_MORNING_INTELLIGENCE,
    EXPECTED_FOCUS_AREAS,
    EXPECTED_SOURCE_LANES,
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
    ProducerRunState,
    ResolverSetId,
    SourceLaneId,
)
from my_pa.domain.intelligence.models import content_digest
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.conftest import DEFAULT_LIMITS, metadata_for, operator

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
DISPOSABLE_DATABASE: Final = "my_pa_intelligence_artifact_test"
WHEN: Final = datetime(2026, 8, 20, 12, tzinfo=UTC)
BODY: Final = "# Collector\n\nsynthetic PostgreSQL path"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def _service(engine: Engine) -> ApplicationService:
    audit = SqlAlchemyAuditSink(engine)
    return ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(engine, audit=audit),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
    )


def test_sql_commit_and_readback_match_digest(migrated_engine: Engine) -> None:
    service = _service(migrated_engine)
    principal = operator()
    begin = service.invoke(
        metadata_for(BeginIntelligenceCycle.capability, Purpose.REPORT_AUTHORING, principal),
        BeginIntelligenceCycle(
            cycle_id=CYCLE_MORNING_INTELLIGENCE,
            business_date="2026-08-20",
            idempotency_key="sql-cycle",
        ),
        principal=principal,
    )
    assert begin.error is None, begin.error
    assert begin.result is not None
    cycle_run_id = begin.result["cycle_run_id"]
    assert isinstance(cycle_run_id, str)
    committed = service.invoke(
        metadata_for(CommitIntelligenceArtifact.capability, Purpose.REPORT_AUTHORING, principal),
        CommitIntelligenceArtifact(
            cycle_run_id=cycle_run_id,
            stage=IntelligenceStage.COLLECTOR,
            artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES,
            producer_task_id="sql-collector",
            producer_task_name="SQL Collector",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="SQL collector",
            body_markdown=BODY,
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="sql-collector",
            focus_area_id=FocusAreaId.COMMUNICATIONS,
        ),
        principal=principal,
    )
    assert committed.error is None, committed.error
    assert committed.result is not None
    assert committed.result["content_sha256"] == content_digest(BODY)
    report_id = committed.result["report_id"]
    assert isinstance(report_id, str)
    read = service.invoke(
        metadata_for(ReadIntelligenceArtifact.capability, Purpose.REPORT_READ, principal),
        ReadIntelligenceArtifact(report_id=report_id),
        principal=principal,
    )
    assert read.error is None, read.error
    assert read.result is not None
    assert read.result["body_markdown"] == BODY
    with migrated_engine.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM knowledge.intelligence_artifacts")
        ).scalar_one()
    assert count == 1


def _invoke(
    service: ApplicationService, principal: Principal, purpose: Purpose, command: object
) -> ResponseEnvelope:
    return service.invoke(
        metadata_for(command.capability, purpose, principal),  # type: ignore[attr-defined]
        command,  # type: ignore[arg-type]
        principal=principal,
    )


def _ok(
    service: ApplicationService, principal: Principal, purpose: Purpose, command: object
) -> dict[str, object]:
    envelope = _invoke(service, principal, purpose, command)
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    return envelope.result


def _begin(service: ApplicationService, principal: Principal, key: str) -> str:
    result = _ok(
        service,
        principal,
        Purpose.REPORT_AUTHORING,
        BeginIntelligenceCycle(
            cycle_id=CYCLE_MORNING_INTELLIGENCE,
            business_date="2026-08-20",
            idempotency_key=key,
        ),
    )
    cycle_run_id = result["cycle_run_id"]
    assert isinstance(cycle_run_id, str)
    return cycle_run_id


def _commit(
    service: ApplicationService,
    principal: Principal,
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
) -> dict[str, object]:
    return _ok(
        service,
        principal,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle_run_id,
            stage=stage,
            artifact_kind=kind,
            producer_task_id=f"sql-{stage.value}",
            producer_task_name=title,
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title=title,
            body_markdown=body,
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key=key,
            focus_area_id=focus,
            source_lane=lane,
            dependency_report_ids=dependencies,
        ),
    )


def _focus_branch(
    service: ApplicationService, principal: Principal, cycle: str, focus: FocusAreaId
) -> str:
    collector = _commit(
        service,
        principal,
        cycle_run_id=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        key=f"{cycle}-{focus.value}-c",
        title=f"Collector {focus.value}",
        body=f"collector {focus.value} xylophone",
        focus=focus,
    )
    collector_id = collector["report_id"]
    assert isinstance(collector_id, str)
    researcher_ids: list[str] = []
    for lane in EXPECTED_SOURCE_LANES:
        research = _commit(
            service,
            principal,
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
    synthesis = _commit(
        service,
        principal,
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
    reporter = _commit(
        service,
        principal,
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


def test_sql_forty_nine_cycle_kind_counts_and_digest_readback(migrated_engine: Engine) -> None:
    service = _service(migrated_engine)
    principal = operator()
    cycle = _begin(service, principal, "sql-full-cycle")
    reporters = tuple(
        _focus_branch(service, principal, cycle, focus) for focus in EXPECTED_FOCUS_AREAS
    )
    brief_body = "Morning Brief xylophone digest"
    brief = _commit(
        service,
        principal,
        cycle_run_id=cycle,
        stage=IntelligenceStage.MORNING_BRIEF,
        kind=ArtifactKind.MORNING_BRIEF,
        key=f"{cycle}-brief",
        title="Morning Brief",
        body=brief_body,
        dependencies=reporters,
    )
    listed = _ok(
        service,
        principal,
        Purpose.REPORT_READ,
        ListIntelligenceArtifacts(cycle_run_id=cycle, page_size=100),
    )
    items = listed["items"]
    assert isinstance(items, list)
    kinds = [item["artifact_kind"] for item in items]
    assert kinds.count("collector_candidates") == 6
    assert kinds.count("research_context") == 30
    assert kinds.count("synthesis_package") == 6
    assert kinds.count("focus_report") == 6
    assert kinds.count("morning_brief") == 1
    assert len(items) == 49
    brief_id = brief["report_id"]
    assert isinstance(brief_id, str)
    read = _ok(
        service,
        principal,
        Purpose.REPORT_READ,
        ReadIntelligenceArtifact(report_id=brief_id),
    )
    assert read["body_markdown"] == brief_body
    assert read["content_sha256"] == brief["content_sha256"] == content_digest(brief_body)
    assert {c.value for c in Capability if c.value.startswith("reports.")} == {
        "reports.begin_cycle",
        "reports.commit",
        "reports.record_run_state",
        "reports.read",
        "reports.latest",
        "reports.list",
        "reports.search",
        "reports.resolve_set",
    }


def test_sql_fts_search_matches_title_term(migrated_engine: Engine) -> None:
    service = _service(migrated_engine)
    principal = operator()
    cycle = _begin(service, principal, "sql-fts")
    _commit(
        service,
        principal,
        cycle_run_id=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        key="sql-fts-c",
        title="Xylophone collector title",
        body="ordinary body text",
        focus=FocusAreaId.COMMUNICATIONS,
    )
    found = _ok(
        service,
        principal,
        Purpose.REPORT_READ,
        SearchIntelligenceArtifacts(query="xylophone", cycle_run_id=cycle),
    )
    items = found["items"]
    assert isinstance(items, list)
    assert len(items) == 1
    assert items[0]["title"] == "Xylophone collector title"
    assert "snippet" in items[0]


def test_sql_one_lane_failure_blocks_synthesizer_without_old_fallback(
    migrated_engine: Engine,
) -> None:
    service = _service(migrated_engine)
    principal = operator()
    cycle = _begin(service, principal, "sql-lane-fail")
    collector = _commit(
        service,
        principal,
        cycle_run_id=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        key="sql-lane-c",
        title="collector",
        body="collector",
        focus=FocusAreaId.COMMUNICATIONS,
    )
    collector_id = collector["report_id"]
    assert isinstance(collector_id, str)
    live_ids: list[str] = []
    failed_run_id = ""
    for lane in EXPECTED_SOURCE_LANES:
        if lane is SourceLaneId.TEAMS:
            failed = _ok(
                service,
                principal,
                Purpose.REPORT_AUTHORING,
                RecordIntelligenceRunState(
                    cycle_run_id=cycle,
                    stage=IntelligenceStage.RESEARCHER,
                    artifact_kind=ArtifactKind.RESEARCH_CONTEXT,
                    producer_task_id="sql-teams-fail",
                    producer_task_name="Teams",
                    automation_platform="abacus_chatllm",
                    report_date="2026-08-20",
                    state=ProducerRunState.FAILED,
                    idempotency_key="sql-teams-fail",
                    focus_area_id=FocusAreaId.COMMUNICATIONS,
                    source_lane=lane,
                    failure_code="source_unavailable",
                ),
            )
            run_id = failed["report_run_id"]
            assert isinstance(run_id, str)
            failed_run_id = run_id
            continue
        research = _commit(
            service,
            principal,
            cycle_run_id=cycle,
            stage=IntelligenceStage.RESEARCHER,
            kind=ArtifactKind.RESEARCH_CONTEXT,
            key=f"sql-lane-{lane.value}",
            title=lane.value,
            body=f"research {lane.value}",
            focus=FocusAreaId.COMMUNICATIONS,
            lane=lane,
            dependencies=(collector_id,),
        )
        report_id = research["report_id"]
        assert isinstance(report_id, str)
        live_ids.append(report_id)
    resolved = _ok(
        service,
        principal,
        Purpose.REPORT_READ,
        ResolveIntelligenceSet(
            cycle_run_id=cycle,
            set_id=ResolverSetId.SYNTHESIZER_INPUTS,
            focus_area_id=FocusAreaId.COMMUNICATIONS,
        ),
    )
    assert resolved["aggregate"] == "BLOCKED"
    resolved_members = resolved["members"]
    assert isinstance(resolved_members, list)
    teams = next(member for member in resolved_members if member["source_lane"] == "teams")
    assert teams["readiness"] == "FAILED"
    assert teams["producer_run_id"] == failed_run_id
    assert teams["artifact_id"] is None
    other_cycle = _begin(service, principal, "sql-lane-old")
    old_collector = _commit(
        service,
        principal,
        cycle_run_id=other_cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        key="sql-old-c",
        title="old",
        body="old",
        focus=FocusAreaId.COMMUNICATIONS,
    )
    old_id = old_collector["report_id"]
    assert isinstance(old_id, str)
    old_research = _commit(
        service,
        principal,
        cycle_run_id=other_cycle,
        stage=IntelligenceStage.RESEARCHER,
        kind=ArtifactKind.RESEARCH_CONTEXT,
        key="sql-old-teams",
        title="old teams",
        body="old teams",
        focus=FocusAreaId.COMMUNICATIONS,
        lane=SourceLaneId.TEAMS,
        dependencies=(old_id,),
    )
    old_research_id = old_research["report_id"]
    assert isinstance(old_research_id, str)
    mixed = _invoke(
        service,
        principal,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.SYNTHESIZER,
            artifact_kind=ArtifactKind.SYNTHESIS_PACKAGE,
            producer_task_id="sql-mixed-synth",
            producer_task_name="mixed",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="mixed",
            body_markdown="no",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="sql-mixed-synth",
            focus_area_id=FocusAreaId.COMMUNICATIONS,
            dependency_report_ids=(*live_ids, old_research_id),
        ),
    )
    assert mixed.error is not None
    assert mixed.error.code is ErrorCode.INVALID_REQUEST


def test_sql_concurrent_begin_cycle_has_one_durable_effect(migrated_engine: Engine) -> None:
    service = _service(migrated_engine)
    principal = operator()
    key = "sql-race-cycle"

    def _race() -> ResponseEnvelope:
        return _invoke(
            service,
            principal,
            Purpose.REPORT_AUTHORING,
            BeginIntelligenceCycle(
                cycle_id=CYCLE_MORNING_INTELLIGENCE,
                business_date="2026-08-20",
                idempotency_key=key,
            ),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_race)
        second = pool.submit(_race)
        envelopes = (first.result(), second.result())
    assert all(envelope.error is None for envelope in envelopes)
    ids = {envelope.result["cycle_run_id"] for envelope in envelopes if envelope.result}
    assert len(ids) == 1
    created = [envelope.result["created"] for envelope in envelopes if envelope.result]
    assert created.count(True) == 1
    assert created.count(False) == 1
    with migrated_engine.connect() as connection:
        cycles = connection.execute(
            text("SELECT count(*) FROM knowledge.intelligence_cycle_runs")
        ).scalar_one()
        receipts = connection.execute(
            text("SELECT count(*) FROM knowledge.intelligence_commit_receipts")
        ).scalar_one()
    assert cycles == 1
    assert receipts == 1


def test_sql_collector_rerun_stales_descendants(migrated_engine: Engine) -> None:
    service = _service(migrated_engine)
    principal = operator()
    cycle = _begin(service, principal, "sql-stale-desc")
    reporter_id = _focus_branch(service, principal, cycle, FocusAreaId.COMMUNICATIONS)
    _commit(
        service,
        principal,
        cycle_run_id=cycle,
        stage=IntelligenceStage.COLLECTOR,
        kind=ArtifactKind.COLLECTOR_CANDIDATES,
        key="sql-stale-c2",
        title="c2",
        body="v2",
        focus=FocusAreaId.COMMUNICATIONS,
    )
    swarm = _ok(
        service,
        principal,
        Purpose.REPORT_READ,
        ResolveIntelligenceSet(
            cycle_run_id=cycle,
            set_id=ResolverSetId.RESEARCH_SWARM,
            focus_area_id=FocusAreaId.COMMUNICATIONS,
        ),
    )
    assert swarm["aggregate"] == "BLOCKED"
    swarm_members = swarm["members"]
    assert isinstance(swarm_members, list)
    assert {member["readiness"] for member in swarm_members} == {"STALE"}
    reporter_set = _ok(
        service,
        principal,
        Purpose.REPORT_READ,
        ResolveIntelligenceSet(
            cycle_run_id=cycle,
            set_id=ResolverSetId.REPORTER_INPUT,
            focus_area_id=FocusAreaId.COMMUNICATIONS,
        ),
    )
    assert reporter_set["aggregate"] != "READY"
    brief_inputs = _ok(
        service,
        principal,
        Purpose.REPORT_READ,
        ResolveIntelligenceSet(cycle_run_id=cycle, set_id=ResolverSetId.MORNING_BRIEF_INPUTS),
    )
    assert brief_inputs["aggregate"] != "READY"
    historical = _ok(
        service,
        principal,
        Purpose.REPORT_READ,
        ReadIntelligenceArtifact(report_id=reporter_id),
    )
    assert historical["body_markdown"] == "report communications"


def _sql_latest(
    service: ApplicationService,
    principal: Principal,
    cycle: str,
    stage: IntelligenceStage,
    *,
    focus: FocusAreaId | None = None,
    lane: SourceLaneId | None = None,
) -> str:
    result = _ok(
        service,
        principal,
        Purpose.REPORT_READ,
        GetLatestIntelligenceArtifact(
            cycle_run_id=cycle, stage=stage, focus_area_id=focus, source_lane=lane
        ),
    )
    report_id = result["report_id"]
    assert isinstance(report_id, str)
    return report_id


def test_sql_researcher_rerun_stales_reporter_input(migrated_engine: Engine) -> None:
    service = _service(migrated_engine)
    principal = operator()
    cycle = _begin(service, principal, "sql-r-rerun")
    reporter_id = _focus_branch(service, principal, cycle, FocusAreaId.COMMUNICATIONS)
    synth_id = _sql_latest(
        service, principal, cycle, IntelligenceStage.SYNTHESIZER, focus=FocusAreaId.COMMUNICATIONS
    )
    collector_id = _sql_latest(
        service, principal, cycle, IntelligenceStage.COLLECTOR, focus=FocusAreaId.COMMUNICATIONS
    )
    _commit(
        service,
        principal,
        cycle_run_id=cycle,
        stage=IntelligenceStage.RESEARCHER,
        kind=ArtifactKind.RESEARCH_CONTEXT,
        key="sql-r-teams-v2",
        title="teams v2",
        body="v2",
        focus=FocusAreaId.COMMUNICATIONS,
        lane=SourceLaneId.TEAMS,
        dependencies=(collector_id,),
    )
    reporter_set = _ok(
        service,
        principal,
        Purpose.REPORT_READ,
        ResolveIntelligenceSet(
            cycle_run_id=cycle,
            set_id=ResolverSetId.REPORTER_INPUT,
            focus_area_id=FocusAreaId.COMMUNICATIONS,
        ),
    )
    assert reporter_set["aggregate"] != "READY"
    members = reporter_set["members"]
    assert isinstance(members, list)
    assert members[0]["readiness"] == "STALE"
    stale = _invoke(
        service,
        principal,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.REPORTER,
            artifact_kind=ArtifactKind.FOCUS_REPORT,
            producer_task_id="sql-stale-r",
            producer_task_name="stale",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="stale",
            body_markdown="no",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="sql-stale-r",
            focus_area_id=FocusAreaId.COMMUNICATIONS,
            dependency_report_ids=(synth_id,),
        ),
    )
    assert stale.error is not None
    assert stale.error.code is ErrorCode.CONFLICT
    historical = _ok(
        service,
        principal,
        Purpose.REPORT_READ,
        ReadIntelligenceArtifact(report_id=reporter_id),
    )
    assert historical["body_markdown"] == "report communications"


def test_sql_synthesizer_rerun_stales_brief_and_rejects_old_reporters(
    migrated_engine: Engine,
) -> None:
    service = _service(migrated_engine)
    principal = operator()
    cycle = _begin(service, principal, "sql-s-rerun")
    reporters = tuple(
        _focus_branch(service, principal, cycle, focus) for focus in EXPECTED_FOCUS_AREAS
    )
    brief = _commit(
        service,
        principal,
        cycle_run_id=cycle,
        stage=IntelligenceStage.MORNING_BRIEF,
        kind=ArtifactKind.MORNING_BRIEF,
        key=f"{cycle}-brief",
        title="Morning Brief",
        body="brief body",
        dependencies=reporters,
    )
    researcher_ids = tuple(
        _sql_latest(
            service,
            principal,
            cycle,
            IntelligenceStage.RESEARCHER,
            focus=FocusAreaId.COMMUNICATIONS,
            lane=lane,
        )
        for lane in EXPECTED_SOURCE_LANES
    )
    _commit(
        service,
        principal,
        cycle_run_id=cycle,
        stage=IntelligenceStage.SYNTHESIZER,
        kind=ArtifactKind.SYNTHESIS_PACKAGE,
        key="sql-s-v2",
        title="synthesis v2",
        body="synthesis v2",
        focus=FocusAreaId.COMMUNICATIONS,
        dependencies=researcher_ids,
    )
    brief_inputs = _ok(
        service,
        principal,
        Purpose.REPORT_READ,
        ResolveIntelligenceSet(cycle_run_id=cycle, set_id=ResolverSetId.MORNING_BRIEF_INPUTS),
    )
    assert brief_inputs["aggregate"] != "READY"
    members = brief_inputs["members"]
    assert isinstance(members, list)
    communications = next(
        member for member in members if member["focus_area_id"] == "communications"
    )
    assert communications["readiness"] == "STALE"
    stale = _invoke(
        service,
        principal,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.MORNING_BRIEF,
            artifact_kind=ArtifactKind.MORNING_BRIEF,
            producer_task_id="sql-stale-brief",
            producer_task_name="stale brief",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="stale brief",
            body_markdown="no",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="sql-stale-brief",
            dependency_report_ids=reporters,
        ),
    )
    assert stale.error is not None
    assert stale.error.code is ErrorCode.CONFLICT
    brief_id = brief["report_id"]
    assert isinstance(brief_id, str)
    historical = _ok(
        service,
        principal,
        Purpose.REPORT_READ,
        ReadIntelligenceArtifact(report_id=brief_id),
    )
    assert historical["body_markdown"] == "brief body"
