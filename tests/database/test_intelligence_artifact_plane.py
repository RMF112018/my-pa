"""Intelligence Artifact plane against disposable PostgreSQL at Alembic head."""

from __future__ import annotations

import io
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

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
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    BUILTIN_REPORT_TYPES,
    CYCLE_MORNING_INTELLIGENCE,
    EXPECTED_FOCUS_AREAS,
    EXPECTED_SOURCE_LANES,
    MAX_CLIENT_REPORT_TYPES,
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
    ProducerRunState,
    ReportTypeOrigin,
    ResolverSetId,
    SourceLaneId,
)
from my_pa.domain.intelligence.models import (
    IntelligenceArtifact,
    IntelligenceProducerRun,
    ReportTypeDefinition,
    content_digest,
)
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.intelligence import SqlIntelligenceStore
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
        "reports.types.create",
        "reports.types.list",
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


def test_sql_one_lane_failure_does_not_block_synthesizer_and_refuses_old_fallback(
    migrated_engine: Engine,
) -> None:
    """A failed lane is reported and not required; another cycle's lane is still refused.

    Was "blocks synthesizer" under the every-lane-required policy. The four live
    lanes resolve READY and commit; substituting another cycle's teams
    researcher stays `invalid_request` (`dependency_wrong_cycle`).
    """
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
    assert resolved["aggregate"] == "READY"
    resolved_members = resolved["members"]
    assert isinstance(resolved_members, list)
    teams = next(member for member in resolved_members if member["source_lane"] == "teams")
    assert teams["readiness"] == "FAILED"
    assert teams["producer_run_id"] == failed_run_id
    assert teams["artifact_id"] is None
    assert teams["required"] is False
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
    assert mixed.error.safe_details == ("dependency_report_ids", "dependency_wrong_cycle")
    four = _invoke(
        service,
        principal,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.SYNTHESIZER,
            artifact_kind=ArtifactKind.SYNTHESIS_PACKAGE,
            producer_task_id="sql-four-synth",
            producer_task_name="four lanes",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="four lanes",
            body_markdown="four lanes",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="sql-four-synth",
            focus_area_id=FocusAreaId.COMMUNICATIONS,
            dependency_report_ids=tuple(live_ids),
        ),
    )
    assert four.error is None, four.error


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


# ---- admitted but not expected focus areas ---------------------------------------

#: Admitted for commit, run state and pipeline dependencies; required by no cycle.
ADMITTED_ONLY: Final[tuple[FocusAreaId, ...]] = (
    FocusAreaId.CAPTURES,
    FocusAreaId.NOTES,
    FocusAreaId.FIELD_INTELLIGENCE,
)
CHECK_VIOLATION: Final = "23514"
#: (table, focus column, primary-key column substituted on a copy, CHECK name).
FOCUS_CHECKS: Final = (
    (
        "intelligence_producer_runs",
        "focus_area_id",
        "run_id",
        "intelligence_producer_runs_focus_area_id_check",
    ),
    (
        "intelligence_artifacts",
        "focus_area_id",
        "artifact_id",
        "intelligence_artifacts_focus_area_id_check",
    ),
    (
        "intelligence_pipeline_dependencies",
        "expected_focus_area_id",
        "downstream_artifact_id",
        "intelligence_pipeline_dependencies_expected_focus_area_id_check",
    ),
)


def _count(engine: Engine, table: str, column: str, value: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(f"SELECT count(*) FROM knowledge.{table} WHERE {column} = :value"),  # noqa: S608
                {"value": value},
            ).scalar_one()
        )


@pytest.mark.parametrize("focus", ADMITTED_ONLY, ids=lambda area: area.value)
def test_sql_admitted_only_area_persists_on_all_three_tables(
    migrated_engine: Engine, focus: FocusAreaId
) -> None:
    """Commit, run state and typed dependencies all reach PostgreSQL for the area."""
    service = _service(migrated_engine)
    principal = operator()
    cycle = _begin(service, principal, f"sql-admit-{focus.value}")
    reporter = _focus_branch(service, principal, cycle, focus)
    failed_cycle = _begin(service, principal, f"sql-admit-fail-{focus.value}")
    failed = _ok(
        service,
        principal,
        Purpose.REPORT_AUTHORING,
        RecordIntelligenceRunState(
            cycle_run_id=failed_cycle,
            stage=IntelligenceStage.RESEARCHER,
            artifact_kind=ArtifactKind.RESEARCH_CONTEXT,
            producer_task_id=f"sql-{focus.value}-teams-fail",
            producer_task_name="Teams",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            state=ProducerRunState.FAILED,
            idempotency_key=f"sql-{focus.value}-teams-fail",
            focus_area_id=focus,
            source_lane=SourceLaneId.TEAMS,
            failure_code="source_unavailable",
        ),
    )
    assert failed["state"] == "failed"
    # Collector, five researchers, synthesizer and reporter: eight artifacts and
    # eight producer runs, plus the failed run with no body.
    assert _count(migrated_engine, "intelligence_artifacts", "focus_area_id", focus.value) == 8
    assert _count(migrated_engine, "intelligence_producer_runs", "focus_area_id", focus.value) == 9
    # Five researcher->collector, five synthesizer->researcher, one reporter->synthesizer.
    assert (
        _count(
            migrated_engine,
            "intelligence_pipeline_dependencies",
            "expected_focus_area_id",
            focus.value,
        )
        == 11
    )
    read = _ok(
        service, principal, Purpose.REPORT_READ, ReadIntelligenceArtifact(report_id=reporter)
    )
    assert read["focus_area_id"] == focus.value


def test_sql_morning_brief_takes_only_the_original_six_areas(migrated_engine: Engine) -> None:
    service = _service(migrated_engine)
    principal = operator()
    cycle = _begin(service, principal, "sql-brief-cycle")
    six = tuple(_focus_branch(service, principal, cycle, focus) for focus in EXPECTED_FOCUS_AREAS)
    extra = _focus_branch(service, principal, cycle, FocusAreaId.CAPTURES)
    resolved = _ok(
        service,
        principal,
        Purpose.REPORT_READ,
        ResolveIntelligenceSet(cycle_run_id=cycle, set_id=ResolverSetId.MORNING_BRIEF_INPUTS),
    )
    assert resolved["aggregate"] == "READY"
    members = resolved["members"]
    assert isinstance(members, list)
    assert [member["member_id"] for member in members] == [
        area.value for area in EXPECTED_FOCUS_AREAS
    ]
    assert {member["artifact_id"] for member in members} == set(six)

    def brief(key: str, reporters: tuple[str, ...]) -> ResponseEnvelope:
        return _invoke(
            service,
            principal,
            Purpose.REPORT_AUTHORING,
            CommitIntelligenceArtifact(
                cycle_run_id=cycle,
                stage=IntelligenceStage.MORNING_BRIEF,
                artifact_kind=ArtifactKind.MORNING_BRIEF,
                producer_task_id="sql-brief",
                producer_task_name="brief",
                automation_platform="abacus_chatllm",
                report_date="2026-08-20",
                title="Morning Brief",
                body_markdown="brief",
                artifact_state=ArtifactState.FINAL,
                schema_version="1",
                idempotency_key=key,
                dependency_report_ids=reporters,
            ),
        )

    for key, reporters in (
        ("sql-brief-swapped", (*six[:-1], extra)),
        ("sql-brief-added", (*six, extra)),
    ):
        refused = brief(key, reporters)
        assert refused.error is not None
        assert refused.error.code is ErrorCode.INVALID_REQUEST
    accepted = brief("sql-brief-six", six)
    assert accepted.error is None, accepted.error
    with migrated_engine.connect() as connection:
        roles = connection.execute(
            text(
                "SELECT d.expected_focus_area_id "
                "FROM knowledge.intelligence_pipeline_dependencies d "
                "JOIN knowledge.intelligence_artifacts a "
                "ON a.principal_id = d.principal_id AND a.artifact_id = d.downstream_artifact_id "
                "WHERE a.stage = 'morning_brief'"
            )
        ).scalars()
        assert sorted(roles) == sorted(area.value for area in EXPECTED_FOCUS_AREAS)


def _copy_with(
    connection: Connection, table: str, key_column: str, column: str, value: str
) -> None:
    """Insert a copy of one row with a fresh key and `column` set to `value`.

    No intelligence table has a BEFORE INSERT trigger, so the CHECK under test is
    what decides the insert, not an append-only guard.
    """
    columns = list(
        connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'knowledge' AND table_name = :table "
                "AND is_generated = 'NEVER' ORDER BY ordinal_position"
            ),
            {"table": table},
        ).scalars()
    )
    if table == "intelligence_pipeline_dependencies":
        # A reversed edge is a fresh primary key over the same two artifacts.
        source = {
            "downstream_artifact_id": "upstream_artifact_id",
            "upstream_artifact_id": "downstream_artifact_id",
        }
        chosen = [source.get(name, name) for name in columns]
    else:
        chosen = [f"{name} || 'Zz9'" if name == key_column else name for name in columns]
    chosen = [
        ":value" if name == column else expression
        for name, expression in zip(columns, chosen, strict=True)
    ]
    inserted = connection.execute(
        text(
            f"INSERT INTO knowledge.{table} ({', '.join(columns)}) "  # noqa: S608
            f"SELECT {', '.join(chosen)} FROM knowledge.{table} "
            f"WHERE {column} = 'communications' LIMIT 1"
        ),
        {"value": value},
    )
    assert inserted.rowcount == 1, f"no source row was copied in {table}"


@pytest.mark.parametrize(
    ("table", "column", "key_column", "constraint"),
    FOCUS_CHECKS,
    ids=[table for table, *_ in FOCUS_CHECKS],
)
def test_sql_focus_area_check_admits_the_nine_and_refuses_an_unknown_value(
    migrated_engine: Engine, table: str, column: str, key_column: str, constraint: str
) -> None:
    service = _service(migrated_engine)
    principal = operator()
    cycle = _begin(service, principal, f"sql-check-{table}")
    _focus_branch(service, principal, cycle, FocusAreaId.COMMUNICATIONS)
    for focus in ADMITTED_ONLY:
        with migrated_engine.connect() as connection, connection.begin() as transaction:
            _copy_with(connection, table, key_column, column, focus.value)
            transaction.rollback()
    with (
        migrated_engine.connect() as connection,
        connection.begin(),
        pytest.raises(DBAPIError) as refused,
    ):
        _copy_with(connection, table, key_column, column, "bogus")
    diag = getattr(refused.value.orig, "diag", None)
    assert getattr(refused.value.orig, "sqlstate", None) == CHECK_VIOLATION
    assert diag is not None
    assert diag.constraint_name == constraint


# ---- the per-Principal report type registry ---------------------------------------------

WEEKLY: Final = ReportTypeDefinition(
    artifact_kind="weekly_digest",
    stage=IntelligenceStage.REPORTER,
    description="A weekly digest of one focus area.",
    origin=ReportTypeOrigin.CLIENT,
    display_name="Weekly digest",
)


def _store(connection: Connection, principal: Principal) -> SqlIntelligenceStore:
    return SqlIntelligenceStore(connection, principal.principal_id)


def test_sql_registry_insert_is_idempotent_and_returns_the_existing_row(
    migrated_engine: Engine,
) -> None:
    principal = operator()
    with migrated_engine.begin() as connection:
        store = _store(connection, principal)
        first = store.insert_report_type(principal.principal_id, WEEKLY, created_at=WHEN)
        assert first.inserted is True
        assert first.report_type.principal_id == principal.principal_id
        assert first.report_type.definition == WEEKLY
        assert first.report_type.definition_fingerprint == WEEKLY.fingerprint
        assert first.report_type.created_at == WHEN
        changed = ReportTypeDefinition(
            artifact_kind="weekly_digest",
            stage=IntelligenceStage.REPORTER,
            description="Something else entirely.",
            origin=ReportTypeOrigin.CLIENT,
        )
        replay = store.insert_report_type(principal.principal_id, changed, created_at=WHEN)
        assert replay.inserted is False
        assert replay.report_type == first.report_type
        assert store.get_report_type(principal.principal_id, "weekly_digest") == first.report_type
        assert store.get_report_type(principal.principal_id, "never_registered") is None


def test_sql_registry_builtins_are_ensured_once_and_listed_by_stage(
    migrated_engine: Engine,
) -> None:
    principal = operator()
    with migrated_engine.begin() as connection:
        store = _store(connection, principal)
        assert store.list_report_types(principal.principal_id) == ()
        assert store.ensure_builtin_report_types(principal.principal_id, created_at=WHEN) == 5
        assert store.ensure_builtin_report_types(principal.principal_id, created_at=WHEN) == 0
        store.insert_report_type(principal.principal_id, WEEKLY, created_at=WHEN)
        listed = store.list_report_types(principal.principal_id)
        assert [
            (row.definition.stage.value, str(row.definition.artifact_kind)) for row in listed
        ] == sorted(
            [(stage.value, kind.value) for kind, stage, _, _ in BUILTIN_REPORT_TYPES]
            + [("reporter", "weekly_digest")]
        )
        assert {row.definition.origin for row in listed} == {
            ReportTypeOrigin.BUILTIN,
            ReportTypeOrigin.CLIENT,
        }
        builtin = store.get_report_type(principal.principal_id, "focus_report")
        assert builtin is not None
        assert builtin.definition.artifact_kind is ArtifactKind.FOCUS_REPORT
        reporters = store.list_report_types(
            principal.principal_id, stage=IntelligenceStage.REPORTER
        )
        assert [str(row.definition.artifact_kind) for row in reporters] == [
            "focus_report",
            "weekly_digest",
        ]


def test_sql_registry_is_principal_isolated(migrated_engine: Engine) -> None:
    owner = operator()
    other = operator()
    with migrated_engine.begin() as connection:
        _store(connection, owner).insert_report_type(owner.principal_id, WEEKLY, created_at=WHEN)
        _store(connection, owner).ensure_builtin_report_types(owner.principal_id, created_at=WHEN)
    with migrated_engine.begin() as connection:
        foreign = _store(connection, other)
        assert foreign.list_report_types(other.principal_id) == ()
        assert foreign.list_report_types(other.principal_id, stage=IntelligenceStage.REPORTER) == ()
        assert foreign.get_report_type(other.principal_id, "weekly_digest") is None
        assert foreign.get_report_type(other.principal_id, "focus_report") is None
        # The same kind under another Principal is a different, independent row.
        mine = foreign.insert_report_type(other.principal_id, WEEKLY, created_at=WHEN)
        assert mine.inserted is True
        assert mine.report_type.principal_id == other.principal_id
        assert len(_store(connection, owner).list_report_types(owner.principal_id)) == 6
        assert len(foreign.list_report_types(other.principal_id)) == 1


def test_sql_a_client_kind_run_and_artifact_read_back_as_the_stored_token(
    migrated_engine: Engine,
) -> None:
    service = _service(migrated_engine)
    principal = operator()
    cycle = _begin(service, principal, "sql-client-kind")
    body = "# Weekly\n\nsynthetic client kind"
    with migrated_engine.begin() as connection:
        store = _store(connection, principal)
        run = IntelligenceProducerRun(
            run_id="rrun_clientkind0001",
            principal_id=principal.principal_id,
            cycle_run_id=cycle,
            stage=IntelligenceStage.REPORTER,
            artifact_kind="weekly_digest",
            state=ProducerRunState.SUCCEEDED,
            version=1,
            producer_task_id="sql-weekly",
            producer_task_name="weekly",
            automation_platform="abacus_chatllm",
            report_date=WHEN.date(),
            created_at=WHEN,
            focus_area_id=FocusAreaId.COMMUNICATIONS,
        )
        store.put_run(run)
        store.put_artifact(
            IntelligenceArtifact(
                artifact_id="rpt_clientkind0001",
                principal_id=principal.principal_id,
                cycle_run_id=cycle,
                producer_run_id=run.run_id,
                stage=IntelligenceStage.REPORTER,
                artifact_kind="weekly_digest",
                report_date=WHEN.date(),
                title="Weekly",
                body_markdown=body,
                content_sha256=content_digest(body),
                content_bytes=len(body.encode("utf-8")),
                artifact_state=ArtifactState.FINAL,
                schema_version="1",
                generated_at=WHEN,
                committed_at=WHEN,
                version=1,
                is_current=True,
                focus_area_id=FocusAreaId.COMMUNICATIONS,
            )
        )
    with migrated_engine.begin() as connection:
        store = _store(connection, principal)
        stored_run = store.get_run(principal.principal_id, "rrun_clientkind0001")
        stored = store.get_artifact(principal.principal_id, "rpt_clientkind0001")
        assert stored_run is not None
        assert stored is not None
        assert stored_run.artifact_kind == stored.artifact_kind == "weekly_digest"
        assert type(stored.artifact_kind) is str
        listed = store.list_artifacts(
            principal.principal_id,
            cycle_run_id=cycle,
            stage=None,
            artifact_kind="weekly_digest",
            focus_area_id=None,
            source_lane=None,
            report_date=None,
            include_superseded=False,
            limit=10,
        )
        assert [artifact.artifact_id for artifact in listed] == ["rpt_clientkind0001"]


def test_sql_report_types_create_list_commit_and_refuse_through_the_service(
    migrated_engine: Engine,
) -> None:
    """R2/R3 over PostgreSQL: register, replay, commit at the stage, refuse elsewhere.

    The refusal lists the acting Principal's own kinds and never another's, and
    the audit row names the new capability (the restated `capability_is_known`).
    """
    service = _service(migrated_engine)
    alice = operator()
    bob = operator()
    definition = {
        "artifact_kind": "sql_weekly_scan",
        "stage": IntelligenceStage.COLLECTOR,
        "description": "A synthetic client collector kind.",
        "display_name": "SQL weekly scan",
    }
    created = _ok(service, alice, Purpose.REPORT_AUTHORING, CreateReportType(**definition))  # type: ignore[arg-type]
    assert (created["created"], created["replayed"], created["origin"]) == (True, False, "client")
    replayed = _ok(service, alice, Purpose.REPORT_AUTHORING, CreateReportType(**definition))  # type: ignore[arg-type]
    assert (replayed["created"], replayed["replayed"]) == (False, True)
    changed = _invoke(
        service,
        alice,
        Purpose.REPORT_AUTHORING,
        CreateReportType(**{**definition, "description": "Changed."}),  # type: ignore[arg-type]
    )
    assert changed.error is not None
    assert (changed.error.code, changed.error.safe_details) == (
        ErrorCode.CONFLICT,
        ("artifact_kind",),
    )
    _ok(
        service,
        bob,
        Purpose.REPORT_AUTHORING,
        CreateReportType(
            artifact_kind="sql_bob_secret", stage=IntelligenceStage.COLLECTOR, description="Bob's."
        ),
    )
    listed = _ok(
        service, alice, Purpose.REPORT_READ, ListReportTypes(stage=IntelligenceStage.COLLECTOR)
    )
    assert [(row["artifact_kind"], row["origin"]) for row in listed["report_types"]] == [  # type: ignore[union-attr]
        ("collector_candidates", "builtin"),
        ("sql_weekly_scan", "client"),
    ]
    with migrated_engine.connect() as connection:
        stored = _store(connection, alice).list_report_types(alice.principal_id)
        audited = connection.execute(
            text(
                "SELECT count(*) FROM knowledge.audit_events "
                "WHERE capability IN ('reports.types.create', 'reports.types.list')"
            )
        ).scalar_one()
    assert {str(row.definition.artifact_kind) for row in stored} == {
        *(kind.value for kind in ArtifactKind),
        "sql_weekly_scan",
    }
    assert audited >= 4

    cycle = _begin(service, alice, "sql-client-kind-cycle")
    committed = _ok(
        service,
        alice,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.COLLECTOR,
            artifact_kind="sql_weekly_scan",
            producer_task_id="sql-client",
            producer_task_name="SQL client",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="SQL client kind",
            body_markdown=BODY,
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="sql-client-kind",
            focus_area_id=FocusAreaId.COMMUNICATIONS,
        ),
    )
    assert committed["artifact_kind"] == "sql_weekly_scan"
    filtered = _ok(
        service,
        alice,
        Purpose.REPORT_READ,
        ListIntelligenceArtifacts(cycle_run_id=cycle, artifact_kind="sql_weekly_scan"),
    )
    assert [item["report_id"] for item in filtered["items"]] == [committed["report_id"]]  # type: ignore[union-attr]
    for kind in ("sql_bob_secret", "sql_weekly_scan"):
        misplaced = _invoke(
            service,
            alice,
            Purpose.REPORT_AUTHORING,
            CommitIntelligenceArtifact(
                cycle_run_id=cycle,
                stage=IntelligenceStage.REPORTER,
                artifact_kind=kind,
                producer_task_id="sql-client",
                producer_task_name="SQL client",
                automation_platform="abacus_chatllm",
                report_date="2026-08-20",
                title="misplaced",
                body_markdown=BODY,
                artifact_state=ArtifactState.FINAL,
                schema_version="1",
                idempotency_key=f"sql-misplaced-{kind}",
                focus_area_id=FocusAreaId.COMMUNICATIONS,
            ),
        )
        assert misplaced.error is not None
        assert misplaced.error.code is ErrorCode.INVALID_REQUEST
        assert [(entry.detail, entry.values) for entry in misplaced.error.allowed_values] == [
            ("artifact_kind", ("focus_report",))
        ]
        assert "sql_bob_secret" not in misplaced.model_dump_json()


def _commit_as(
    service: ApplicationService,
    principal: Principal,
    *,
    cycle: str,
    stage: IntelligenceStage,
    kind: str,
    key: str,
    focus: FocusAreaId | None = None,
    dependencies: tuple[str, ...] = (),
    state: ArtifactState = ArtifactState.FINAL,
) -> ResponseEnvelope:
    return _invoke(
        service,
        principal,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=stage,
            artifact_kind=kind,
            producer_task_id=f"sql-{kind}",
            producer_task_name=kind,
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title=f"SQL {kind}",
            body_markdown=f"synthetic {kind}",
            artifact_state=state,
            schema_version="1",
            idempotency_key=key,
            focus_area_id=focus,
            dependency_report_ids=dependencies,
        ),
    )


def _sql_latest_of(
    service: ApplicationService,
    principal: Principal,
    cycle: str,
    kind: str,
    focus: FocusAreaId | None = None,
) -> dict[str, object]:
    return _ok(
        service,
        principal,
        Purpose.REPORT_READ,
        GetLatestIntelligenceArtifact(cycle_run_id=cycle, artifact_kind=kind, focus_area_id=focus),
    )


def _register_sql(
    service: ApplicationService, principal: Principal, kind: str, stage: IntelligenceStage
) -> None:
    _ok(
        service,
        principal,
        Purpose.REPORT_AUTHORING,
        CreateReportType(artifact_kind=kind, stage=stage, description="A synthetic client kind."),
    )


def test_sql_a_client_brief_kind_never_displaces_the_builtin_daily_briefing(
    migrated_engine: Engine,
) -> None:
    """F1 (a) over PostgreSQL: the head index and lookups are per kind."""
    service = _service(migrated_engine)
    principal = operator()
    _register_sql(service, principal, "sql_weekly_brief", IntelligenceStage.MORNING_BRIEF)
    cycle = _begin(service, principal, "sql-client-brief-cycle")
    heads = tuple(_focus_branch(service, principal, cycle, focus) for focus in EXPECTED_FOCUS_AREAS)
    builtin = _ok(
        service,
        principal,
        Purpose.REPORT_AUTHORING,
        CommitIntelligenceArtifact(
            cycle_run_id=cycle,
            stage=IntelligenceStage.MORNING_BRIEF,
            artifact_kind=ArtifactKind.MORNING_BRIEF,
            producer_task_id="sql-brief",
            producer_task_name="brief",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="Daily Briefing",
            body_markdown="brief",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="sql-builtin-brief",
            dependency_report_ids=heads,
        ),
    )
    false_final = _commit_as(
        service,
        principal,
        cycle=cycle,
        stage=IntelligenceStage.MORNING_BRIEF,
        kind="sql_weekly_brief",
        key="sql-client-brief-final",
    )
    assert false_final.error is not None
    assert (false_final.error.code, false_final.error.safe_details) == (
        ErrorCode.INVALID_REQUEST,
        ("artifact_state",),
    )
    client = _commit_as(
        service,
        principal,
        cycle=cycle,
        stage=IntelligenceStage.MORNING_BRIEF,
        kind="sql_weekly_brief",
        key="sql-client-brief-partial",
        state=ArtifactState.PARTIAL,
    )
    assert client.error is None, client.error
    assert client.result is not None
    assert (client.result["version"], client.result["supersedes_report_id"]) == (1, None)
    latest = _sql_latest_of(service, principal, cycle, "morning_brief")
    assert (latest["report_id"], latest["artifact_state"]) == (builtin["report_id"], "final")
    mine = _sql_latest_of(service, principal, cycle, "sql_weekly_brief")
    assert (mine["report_id"], mine["artifact_state"]) == (client.result["report_id"], "partial")
    with migrated_engine.connect() as connection:
        current = connection.execute(
            text(
                "SELECT artifact_kind FROM knowledge.intelligence_artifacts "
                "WHERE principal_id = :principal AND stage = 'morning_brief' AND is_current "
                "ORDER BY artifact_kind"
            ),
            {"principal": principal.principal_id},
        ).scalars()
        assert list(current) == ["morning_brief", "sql_weekly_brief"]


def test_sql_a_client_reporter_kind_never_displaces_the_builtin_focus_report(
    migrated_engine: Engine,
) -> None:
    """F1 (b) and (c) over PostgreSQL: the brief inputs see only the built-in reporter."""
    service = _service(migrated_engine)
    principal = operator()
    _register_sql(service, principal, "sql_client_report", IntelligenceStage.REPORTER)
    cycle = _begin(service, principal, "sql-client-reporter-cycle")
    heads = tuple(_focus_branch(service, principal, cycle, focus) for focus in EXPECTED_FOCUS_AREAS)
    last = EXPECTED_FOCUS_AREAS[-1]
    synth = _sql_latest(service, principal, cycle, IntelligenceStage.SYNTHESIZER, focus=last)
    client = _commit_as(
        service,
        principal,
        cycle=cycle,
        stage=IntelligenceStage.REPORTER,
        kind="sql_client_report",
        key="sql-client-reporter",
        focus=last,
        dependencies=(synth,),
    )
    assert client.error is None, client.error
    assert client.result is not None
    client_id = client.result["report_id"]
    assert isinstance(client_id, str)
    assert (client.result["version"], client.result["supersedes_report_id"]) == (1, None)
    builtin = _sql_latest_of(service, principal, cycle, "focus_report", last)
    assert (builtin["report_id"], builtin["artifact_state"]) == (heads[-1], "final")
    resolved = _ok(
        service,
        principal,
        Purpose.REPORT_READ,
        ResolveIntelligenceSet(cycle_run_id=cycle, set_id=ResolverSetId.MORNING_BRIEF_INPUTS),
    )
    assert resolved["aggregate"] == "READY"
    by_area = {m["focus_area_id"]: m for m in resolved["members"]}  # type: ignore[union-attr]
    assert by_area[last.value]["artifact_id"] == heads[-1]
    # (c) the client reporter cited by a brief is the bare dependency refusal.
    cited = _commit_as(
        service,
        principal,
        cycle=cycle,
        stage=IntelligenceStage.MORNING_BRIEF,
        kind="morning_brief",
        key="sql-brief-cites-client",
        dependencies=(*heads[:-1], client_id),
        state=ArtifactState.PARTIAL,
    )
    assert cited.error is not None
    assert (cited.error.code, cited.error.safe_details) == (
        ErrorCode.INVALID_REQUEST,
        ("dependency_report_ids",),
    )
    brief = _commit_as(
        service,
        principal,
        cycle=cycle,
        stage=IntelligenceStage.MORNING_BRIEF,
        kind="morning_brief",
        key="sql-brief-over-builtins",
        dependencies=heads,
    )
    assert brief.error is None, brief.error


def _commit_later(service: ApplicationService) -> None:
    """Move the fixed clock forward, so the next commit is strictly the newest."""
    service._clock = lambda: WHEN + timedelta(minutes=1)


def test_sql_a_stage_only_latest_stays_on_the_builtin_brief(migrated_engine: Engine) -> None:
    """A later client kind at `morning_brief` is never a stage-only latest."""
    service = _service(migrated_engine)
    principal = operator()
    _register_sql(service, principal, "sql_stage_brief", IntelligenceStage.MORNING_BRIEF)
    cycle = _begin(service, principal, "sql-stage-only-brief-cycle")
    heads = tuple(_focus_branch(service, principal, cycle, focus) for focus in EXPECTED_FOCUS_AREAS)
    builtin = _commit_as(
        service,
        principal,
        cycle=cycle,
        stage=IntelligenceStage.MORNING_BRIEF,
        kind="morning_brief",
        key="sql-stage-only-builtin-brief",
        dependencies=heads,
    )
    assert builtin.error is None, builtin.error
    assert builtin.result is not None
    _commit_later(service)
    client = _commit_as(
        service,
        principal,
        cycle=cycle,
        stage=IntelligenceStage.MORNING_BRIEF,
        kind="sql_stage_brief",
        key="sql-stage-only-client-brief",
        dependencies=heads,
    )
    assert client.error is None, client.error
    assert client.result is not None
    assert (
        _sql_latest(service, principal, cycle, IntelligenceStage.MORNING_BRIEF)
        == builtin.result["report_id"]
    )
    assert (
        _sql_latest_of(service, principal, cycle, "sql_stage_brief")["report_id"]
        == client.result["report_id"]
    )


def test_sql_a_stage_only_latest_stays_on_the_builtin_focus_report(
    migrated_engine: Engine,
) -> None:
    """A later client kind at `reporter` is never a stage-only latest for the area."""
    service = _service(migrated_engine)
    principal = operator()
    _register_sql(service, principal, "sql_stage_report", IntelligenceStage.REPORTER)
    cycle = _begin(service, principal, "sql-stage-only-reporter-cycle")
    heads = tuple(_focus_branch(service, principal, cycle, focus) for focus in EXPECTED_FOCUS_AREAS)
    last = EXPECTED_FOCUS_AREAS[-1]
    synth = _sql_latest(service, principal, cycle, IntelligenceStage.SYNTHESIZER, focus=last)
    _commit_later(service)
    client = _commit_as(
        service,
        principal,
        cycle=cycle,
        stage=IntelligenceStage.REPORTER,
        kind="sql_stage_report",
        key="sql-stage-only-client-reporter",
        focus=last,
        dependencies=(synth,),
    )
    assert client.error is None, client.error
    assert client.result is not None
    assert (
        _sql_latest(service, principal, cycle, IntelligenceStage.REPORTER, focus=last) == heads[-1]
    )
    assert (
        _sql_latest_of(service, principal, cycle, "sql_stage_report", last)["report_id"]
        == client.result["report_id"]
    )


def _client(kind: str) -> ReportTypeDefinition:
    return ReportTypeDefinition(
        artifact_kind=kind,
        stage=IntelligenceStage.REPORTER,
        description="A synthetic client kind.",
        origin=ReportTypeOrigin.CLIENT,
    )


def _client_count(engine: Engine, principal: Principal) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM knowledge.intelligence_report_types "
                    "WHERE principal_id = :principal AND origin = 'client'"
                ),
                {"principal": principal.principal_id},
            ).scalar_one()
        )


def test_sql_concurrent_registrations_at_the_cap_admit_exactly_one(
    migrated_engine: Engine,
) -> None:
    """F2: two registrations racing at 63 client kinds; the advisory lock admits one.

    A holds the registry lock with its 64th row uncommitted while B registers
    another kind. B must wait for A's commit and then see 64 rows; without the
    lock B would count 63, insert, and the Principal would hold 65.
    """
    principal = operator()
    other = operator()
    with migrated_engine.begin() as connection:
        store = _store(connection, principal)
        for index in range(MAX_CLIENT_REPORT_TYPES - 1):
            store.insert_report_type(
                principal.principal_id, _client(f"seeded_{index:02d}"), created_at=WHEN
            )
    assert _client_count(migrated_engine, principal) == MAX_CLIENT_REPORT_TYPES - 1

    def register(kind: str) -> bool | None:
        with migrated_engine.begin() as connection:
            outcome = _store(connection, principal).register_client_report_type(
                principal.principal_id,
                _client(kind),
                created_at=WHEN,
                limit=MAX_CLIENT_REPORT_TYPES,
            )
        return None if outcome is None else outcome.inserted

    def waiting_on_the_lock(connection: Connection) -> bool:
        return bool(
            connection.execute(
                text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted")
            ).scalar_one()
        )

    with migrated_engine.connect() as holder, migrated_engine.connect() as observer:
        transaction = holder.begin()
        first = _store(holder, principal).register_client_report_type(
            principal.principal_id,
            _client("race_first"),
            created_at=WHEN,
            limit=MAX_CLIENT_REPORT_TYPES,
        )
        assert first is not None and first.inserted is True
        with ThreadPoolExecutor(max_workers=1) as pool:
            second = pool.submit(register, "race_second")
            deadline = datetime.now(UTC).timestamp() + 30
            while not second.done() and not waiting_on_the_lock(observer):
                observer.rollback()
                time.sleep(0.02)
                assert datetime.now(UTC).timestamp() < deadline, "B neither ran nor waited"
            # Another Principal's registry is a different key: it is never blocked.
            assert _register_other(migrated_engine, other) is True
            transaction.commit()
            outcome = second.result(timeout=30)
    assert outcome is None
    assert _client_count(migrated_engine, principal) == MAX_CLIENT_REPORT_TYPES


def _register_other(engine: Engine, principal: Principal) -> bool:
    with engine.begin() as connection:
        # Fail rather than hang if another Principal's key were ever shared.
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        outcome = _store(connection, principal).register_client_report_type(
            principal.principal_id, _client("other_kind"), created_at=WHEN, limit=1
        )
    assert outcome is not None
    return outcome.inserted
