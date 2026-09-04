"""Seed one Principal-scoped Intelligence artifact for the Reports browser suite.

The disposable e2e database has no Intelligence rows after migrate-to-head. The
Reports contract journey needs a persisted artifact written by the production
writers (`begin_cycle`, `commit_artifact`) so BFF read/list/readiness can prove
`structured_content` is not invented from markdown and resolve_set members are
not flattened.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

from sqlalchemy import create_engine

from my_pa.application.intelligence import begin_cycle, commit_artifact
from my_pa.bootstrap.gateway import local_principal
from my_pa.domain.intelligence.catalog import (
    CYCLE_MORNING_INTELLIGENCE,
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
)
from my_pa.infrastructure.persistence.intelligence import SqlIntelligenceStore

MARKDOWN = "# Morning Brief\n\n- scraped item one\n- scraped item two"
STRUCTURED_CONTENT = {
    "lane": "persisted",
    "marker": "e2e-structured-not-from-markdown",
}
WHEN = datetime(2026, 8, 20, 12, tzinfo=UTC)
REPORT_DATE = date(2026, 8, 20)


def main() -> None:
    database_url = os.environ["MY_PA_DATABASE_URL"]
    principal_id = local_principal().principal_id
    with create_engine(database_url).begin() as connection:
        store = SqlIntelligenceStore(connection, principal_id)
        cycle_admission = begin_cycle(
            store,
            principal_id=principal_id,
            cycle_id=CYCLE_MORNING_INTELLIGENCE,
            business_date=REPORT_DATE,
            idempotency_key="e2e-reports-cycle",
            at=WHEN,
            automation_platform=None,
            external_orchestration_id=None,
        )
        cycle = cycle_admission.cycle
        if cycle is None:
            raise RuntimeError("begin_cycle did not return a cycle run")
        committed = commit_artifact(
            store,
            principal_id=principal_id,
            cycle_run_id=cycle.cycle_run_id,
            stage=IntelligenceStage.COLLECTOR,
            artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES,
            focus_area_id=FocusAreaId.COMMUNICATIONS,
            source_lane=None,
            producer_task_id="e2e-collector",
            producer_task_name="E2E collector",
            automation_platform="abacus_chatllm",
            automation_run_id=None,
            report_date=REPORT_DATE,
            title="E2E morning brief collector",
            body_markdown=MARKDOWN,
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="e2e-reports-collector",
            at=WHEN,
            structured_content=STRUCTURED_CONTENT,
        )
        artifact = committed.artifact
        if artifact is None:
            raise RuntimeError("commit_artifact did not return an artifact")
        if artifact.structured_content != STRUCTURED_CONTENT:
            raise RuntimeError("seeded structured_content did not round-trip")
        if artifact.body_markdown != MARKDOWN:
            raise RuntimeError("seeded body_markdown did not round-trip")


if __name__ == "__main__":
    main()
