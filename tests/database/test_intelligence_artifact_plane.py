"""Intelligence Artifact plane against disposable PostgreSQL at Alembic head."""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.application.commands import (
    BeginIntelligenceCycle,
    CommitIntelligenceArtifact,
    ReadIntelligenceArtifact,
)
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    CYCLE_MORNING_INTELLIGENCE,
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
)
from my_pa.domain.intelligence.models import content_digest
from my_pa.infrastructure.database.engine import create_database_engine
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


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    try:
        _administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        yield url
    finally:
        _administer(drop)
        maintenance.dispose()


@pytest.fixture
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


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
