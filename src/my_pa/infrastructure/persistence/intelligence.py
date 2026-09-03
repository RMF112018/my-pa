"""PostgreSQL store for the Intelligence Artifact plane."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, cast

from sqlalchemy import Connection, and_, desc, func, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.sql.elements import ColumnElement

from my_pa.domain.intelligence.catalog import (
    ArtifactKind,
    ArtifactState,
    CycleState,
    FocusAreaId,
    IntelligenceStage,
    ProducerRunState,
    ProvenanceRelation,
    SourceLaneId,
)
from my_pa.domain.intelligence.models import (
    IntelligenceArtifact,
    IntelligenceCommitReceipt,
    IntelligenceCycleRun,
    IntelligencePipelineDependency,
    IntelligenceProducerRun,
    IntelligenceProvenanceRef,
)
from my_pa.domain.search.query import SearchQuery, SearchQueryError
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
    principal_scoped,
)
from my_pa.infrastructure.persistence.tables import (
    intelligence_artifacts,
    intelligence_commit_receipts,
    intelligence_cycle_runs,
    intelligence_pipeline_dependencies,
    intelligence_producer_runs,
    intelligence_provenance_refs,
)

__all__ = ["SqlIntelligenceStore"]


def _area(value: str | None) -> FocusAreaId | None:
    return None if value is None else FocusAreaId(value)


def _lane(value: str | None) -> SourceLaneId | None:
    return None if value is None else SourceLaneId(value)


class SqlIntelligenceStore:
    """Connection-bound IntelligenceStore. Every read is principal-scoped."""

    def __init__(self, connection: Connection, principal_id: str) -> None:
        self._connection = connection
        self._principal_id = principal_id
        self._context = capture_context(principal_id)

    def get_receipt(
        self, principal_id: str, idempotency_key: str
    ) -> IntelligenceCommitReceipt | None:
        statement = principal_scoped(
            select(intelligence_commit_receipts).where(
                intelligence_commit_receipts.c.idempotency_key == idempotency_key
            ),
            intelligence_commit_receipts,
            self._context,
        )
        row = self._connection.execute(statement).mappings().first()
        return None if row is None else self._receipt(row)

    def put_receipt(self, receipt: IntelligenceCommitReceipt) -> bool:
        values = principal_bound_values(
            {
                "receipt_id": receipt.receipt_id,
                "idempotency_key": receipt.idempotency_key,
                "mutation_kind": receipt.mutation_kind,
                "fingerprint_sha256": receipt.fingerprint_sha256,
                "cycle_run_id": receipt.cycle_run_id,
                "producer_run_id": receipt.producer_run_id,
                "artifact_id": receipt.artifact_id,
                "content_sha256": receipt.content_sha256,
                "content_bytes": receipt.content_bytes,
                "created_at": receipt.created_at,
            },
            intelligence_commit_receipts,
            self._context,
        )
        result = self._connection.execute(
            pg_insert(intelligence_commit_receipts)
            .values(**values)
            .on_conflict_do_nothing(constraint="one_intelligence_key_per_principal")
            .returning(intelligence_commit_receipts.c.receipt_id)
        )
        return result.first() is not None

    def get_cycle(self, principal_id: str, cycle_run_id: str) -> IntelligenceCycleRun | None:
        statement = principal_scoped(
            select(intelligence_cycle_runs).where(
                intelligence_cycle_runs.c.cycle_run_id == cycle_run_id
            ),
            intelligence_cycle_runs,
            self._context,
        )
        row = self._connection.execute(statement).mappings().first()
        return None if row is None else self._cycle(row)

    def cycle_for_external_root(
        self, principal_id: str, platform: str, external_root_run_id: str
    ) -> IntelligenceCycleRun | None:
        statement = principal_scoped(
            select(intelligence_cycle_runs).where(
                intelligence_cycle_runs.c.automation_platform == platform,
                intelligence_cycle_runs.c.external_root_run_id == external_root_run_id,
            ),
            intelligence_cycle_runs,
            self._context,
        )
        row = self._connection.execute(statement).mappings().first()
        return None if row is None else self._cycle(row)

    def put_cycle(self, cycle: IntelligenceCycleRun) -> None:
        values = principal_bound_values(
            {
                "cycle_run_id": cycle.cycle_run_id,
                "cycle_id": cycle.cycle_id,
                "business_date": cycle.business_date,
                "state": cycle.state.value,
                "version": cycle.version,
                "automation_platform": cycle.automation_platform,
                "external_root_run_id": cycle.external_root_run_id,
                "created_at": cycle.created_at,
                "started_at": cycle.started_at,
                "finished_at": cycle.finished_at,
            },
            intelligence_cycle_runs,
            self._context,
        )
        self._connection.execute(intelligence_cycle_runs.insert().values(**values))

    def get_run(self, principal_id: str, run_id: str) -> IntelligenceProducerRun | None:
        statement = principal_scoped(
            select(intelligence_producer_runs).where(intelligence_producer_runs.c.run_id == run_id),
            intelligence_producer_runs,
            self._context,
        )
        row = self._connection.execute(statement).mappings().first()
        return None if row is None else self._run(row)

    def put_run(self, run: IntelligenceProducerRun) -> None:
        values = principal_bound_values(
            {
                "run_id": run.run_id,
                "cycle_run_id": run.cycle_run_id,
                "focus_area_id": None if run.focus_area_id is None else run.focus_area_id.value,
                "stage": run.stage.value,
                "artifact_kind": run.artifact_kind.value,
                "source_lane": None if run.source_lane is None else run.source_lane.value,
                "producer_task_id": run.producer_task_id,
                "producer_task_name": run.producer_task_name,
                "automation_platform": run.automation_platform,
                "automation_run_id": run.automation_run_id,
                "report_date": run.report_date,
                "coverage_start": run.coverage_start,
                "coverage_end": run.coverage_end,
                "state": run.state.value,
                "version": run.version,
                "failure_code": run.failure_code,
                "failure_summary": run.failure_summary,
                "created_at": run.created_at,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
            },
            intelligence_producer_runs,
            self._context,
        )
        self._connection.execute(intelligence_producer_runs.insert().values(**values))

    def replace_run(self, run: IntelligenceProducerRun, *, expected_version: int) -> bool:
        result = self._connection.execute(
            update(intelligence_producer_runs)
            .where(
                partition_criterion(intelligence_producer_runs, self._context),
                intelligence_producer_runs.c.run_id == run.run_id,
                intelligence_producer_runs.c.version == expected_version,
            )
            .values(state=run.state.value, version=run.version, finished_at=run.finished_at)
        )
        return result.rowcount == 1

    def run_for_external(
        self,
        principal_id: str,
        platform: str,
        producer_task_id: str,
        automation_run_id: str,
    ) -> IntelligenceProducerRun | None:
        statement = principal_scoped(
            select(intelligence_producer_runs).where(
                intelligence_producer_runs.c.automation_platform == platform,
                intelligence_producer_runs.c.producer_task_id == producer_task_id,
                intelligence_producer_runs.c.automation_run_id == automation_run_id,
            ),
            intelligence_producer_runs,
            self._context,
        )
        row = self._connection.execute(statement).mappings().first()
        return None if row is None else self._run(row)

    def get_artifact(self, principal_id: str, artifact_id: str) -> IntelligenceArtifact | None:
        statement = principal_scoped(
            select(intelligence_artifacts).where(
                intelligence_artifacts.c.artifact_id == artifact_id
            ),
            intelligence_artifacts,
            self._context,
        )
        row = self._connection.execute(statement).mappings().first()
        return None if row is None else self._artifact(row)

    def put_artifact(self, artifact: IntelligenceArtifact) -> None:
        payload: dict[str, object] = {
            "artifact_id": artifact.artifact_id,
            "cycle_run_id": artifact.cycle_run_id,
            "producer_run_id": artifact.producer_run_id,
            "focus_area_id": None
            if artifact.focus_area_id is None
            else artifact.focus_area_id.value,
            "stage": artifact.stage.value,
            "artifact_kind": artifact.artifact_kind.value,
            "source_lane": None if artifact.source_lane is None else artifact.source_lane.value,
            "report_date": artifact.report_date,
            "title": artifact.title,
            "body_markdown": artifact.body_markdown,
            "content_sha256": artifact.content_sha256,
            "content_bytes": artifact.content_bytes,
            "artifact_state": artifact.artifact_state.value,
            "completeness": artifact.completeness,
            "schema_version": artifact.schema_version,
            "producer_prompt_version": artifact.producer_prompt_version,
            "generated_at": artifact.generated_at,
            "committed_at": artifact.committed_at,
            "version": artifact.version,
            "is_current": artifact.is_current,
            "supersedes_artifact_id": artifact.supersedes_artifact_id,
        }
        if artifact.structured_content is not None:
            payload["structured_content"] = artifact.structured_content
        values = principal_bound_values(
            payload,
            intelligence_artifacts,
            self._context,
        )
        self._connection.execute(intelligence_artifacts.insert().values(**values))
        for dependency in artifact.dependencies:
            dep_values = principal_bound_values(
                {
                    "downstream_artifact_id": artifact.artifact_id,
                    "upstream_artifact_id": dependency.upstream_artifact_id,
                    "dependency_role": dependency.dependency_role,
                    "required": dependency.required,
                    "expected_stage": None
                    if dependency.expected_stage is None
                    else dependency.expected_stage.value,
                    "expected_focus_area_id": None
                    if dependency.expected_focus_area_id is None
                    else dependency.expected_focus_area_id.value,
                    "expected_source_lane": None
                    if dependency.expected_source_lane is None
                    else dependency.expected_source_lane.value,
                },
                intelligence_pipeline_dependencies,
                self._context,
            )
            self._connection.execute(
                intelligence_pipeline_dependencies.insert().values(**dep_values)
            )
        for position, ref in enumerate(artifact.provenance, start=1):
            prov_values = principal_bound_values(
                {
                    "artifact_id": artifact.artifact_id,
                    "position": position,
                    "source_system": ref.source_system,
                    "source_ref": ref.source_ref,
                    "relation": ref.relation.value,
                    "source_url": ref.source_url,
                    "observed_at": ref.observed_at,
                    "retrieved_at": ref.retrieved_at,
                    "evidence_subject_id": ref.evidence_subject_id,
                },
                intelligence_provenance_refs,
                self._context,
            )
            self._connection.execute(intelligence_provenance_refs.insert().values(**prov_values))

    def mark_superseded(self, principal_id: str, artifact_id: str) -> None:
        self._connection.execute(
            update(intelligence_artifacts)
            .where(
                partition_criterion(intelligence_artifacts, self._context),
                intelligence_artifacts.c.artifact_id == artifact_id,
            )
            .values(is_current=False, artifact_state=ArtifactState.SUPERSEDED.value)
        )

    def current_head(
        self,
        principal_id: str,
        cycle_run_id: str,
        stage: IntelligenceStage,
        focus_area_id: FocusAreaId | None,
        source_lane: SourceLaneId | None,
    ) -> IntelligenceArtifact | None:
        filters = [
            intelligence_artifacts.c.cycle_run_id == cycle_run_id,
            intelligence_artifacts.c.stage == stage.value,
            intelligence_artifacts.c.is_current.is_(True),
        ]
        if focus_area_id is None:
            filters.append(intelligence_artifacts.c.focus_area_id.is_(None))
        else:
            filters.append(intelligence_artifacts.c.focus_area_id == focus_area_id.value)
        if source_lane is None:
            filters.append(intelligence_artifacts.c.source_lane.is_(None))
        else:
            filters.append(intelligence_artifacts.c.source_lane == source_lane.value)
        statement = principal_scoped(
            select(intelligence_artifacts)
            .where(*filters)
            .order_by(
                desc(intelligence_artifacts.c.committed_at),
                desc(intelligence_artifacts.c.artifact_id),
            ),
            intelligence_artifacts,
            self._context,
        )
        row = self._connection.execute(statement).mappings().first()
        return None if row is None else self._artifact(row)

    def list_artifacts(
        self,
        principal_id: str,
        *,
        cycle_run_id: str | None,
        stage: IntelligenceStage | None,
        artifact_kind: ArtifactKind | None,
        focus_area_id: FocusAreaId | None,
        source_lane: SourceLaneId | None,
        report_date: date | None,
        include_superseded: bool,
        limit: int,
        after_committed_at: datetime | None = None,
        after_artifact_id: str | None = None,
    ) -> tuple[IntelligenceArtifact, ...]:
        filters: list[ColumnElement[bool]] = []
        if cycle_run_id is not None:
            filters.append(intelligence_artifacts.c.cycle_run_id == cycle_run_id)
        if stage is not None:
            filters.append(intelligence_artifacts.c.stage == stage.value)
        if artifact_kind is not None:
            filters.append(intelligence_artifacts.c.artifact_kind == artifact_kind.value)
        if focus_area_id is not None:
            filters.append(intelligence_artifacts.c.focus_area_id == focus_area_id.value)
        if source_lane is not None:
            filters.append(intelligence_artifacts.c.source_lane == source_lane.value)
        if report_date is not None:
            filters.append(intelligence_artifacts.c.report_date == report_date)
        if not include_superseded:
            filters.append(intelligence_artifacts.c.is_current.is_(True))
            filters.append(
                intelligence_artifacts.c.artifact_state != ArtifactState.SUPERSEDED.value
            )
        if after_committed_at is not None and after_artifact_id is not None:
            filters.append(
                or_(
                    intelligence_artifacts.c.committed_at < after_committed_at,
                    and_(
                        intelligence_artifacts.c.committed_at == after_committed_at,
                        intelligence_artifacts.c.artifact_id < after_artifact_id,
                    ),
                )
            )
        query = select(intelligence_artifacts)
        if filters:
            query = query.where(*filters)
        statement = principal_scoped(
            query.order_by(
                desc(intelligence_artifacts.c.committed_at),
                desc(intelligence_artifacts.c.artifact_id),
            ).limit(limit),
            intelligence_artifacts,
            self._context,
        )
        return tuple(self._artifact(row) for row in self._connection.execute(statement).mappings())

    def search_artifacts(
        self,
        principal_id: str,
        query: str,
        *,
        cycle_run_id: str | None,
        stage: IntelligenceStage | None,
        artifact_kind: ArtifactKind | None,
        focus_area_id: FocusAreaId | None,
        source_lane: SourceLaneId | None,
        limit: int,
    ) -> tuple[tuple[IntelligenceArtifact, str], ...]:
        try:
            parsed = SearchQuery(query)
        except SearchQueryError:
            return ()
        tsquery = func.websearch_to_tsquery("english", parsed.text)
        filters: list[ColumnElement[bool]] = [intelligence_artifacts.c.is_current.is_(True)]
        if cycle_run_id is not None:
            filters.append(intelligence_artifacts.c.cycle_run_id == cycle_run_id)
        if stage is not None:
            filters.append(intelligence_artifacts.c.stage == stage.value)
        if artifact_kind is not None:
            filters.append(intelligence_artifacts.c.artifact_kind == artifact_kind.value)
        if focus_area_id is not None:
            filters.append(intelligence_artifacts.c.focus_area_id == focus_area_id.value)
        if source_lane is not None:
            filters.append(intelligence_artifacts.c.source_lane == source_lane.value)
        search_document: ColumnElement[Any] = literal_column("search_document")
        rank = func.ts_rank(search_document, tsquery)
        headline = func.ts_headline(
            "english",
            intelligence_artifacts.c.title,
            tsquery,
            "MaxWords=20,MinWords=5",
        )
        statement = principal_scoped(
            select(intelligence_artifacts, headline.label("snippet"))
            .where(*filters, search_document.op("@@")(tsquery))
            .order_by(
                desc(rank),
                desc(intelligence_artifacts.c.committed_at),
                intelligence_artifacts.c.artifact_id,
            )
            .limit(limit),
            intelligence_artifacts,
            self._context,
        )
        rows = self._connection.execute(statement).mappings()
        return tuple((self._artifact(row), str(row["snippet"])) for row in rows)

    def failed_run(
        self,
        principal_id: str,
        cycle_run_id: str,
        stage: IntelligenceStage,
        focus_area_id: FocusAreaId | None,
        source_lane: SourceLaneId | None,
    ) -> IntelligenceProducerRun | None:
        filters = [
            intelligence_producer_runs.c.cycle_run_id == cycle_run_id,
            intelligence_producer_runs.c.stage == stage.value,
        ]
        if focus_area_id is None:
            filters.append(intelligence_producer_runs.c.focus_area_id.is_(None))
        else:
            filters.append(intelligence_producer_runs.c.focus_area_id == focus_area_id.value)
        if source_lane is None:
            filters.append(intelligence_producer_runs.c.source_lane.is_(None))
        else:
            filters.append(intelligence_producer_runs.c.source_lane == source_lane.value)
        statement = principal_scoped(
            select(intelligence_producer_runs)
            .where(*filters)
            .order_by(desc(intelligence_producer_runs.c.created_at)),
            intelligence_producer_runs,
            self._context,
        )
        row = self._connection.execute(statement).mappings().first()
        return None if row is None else self._run(row)

    def _cycle(self, row: RowMapping) -> IntelligenceCycleRun:
        mapping = dict(row)
        return IntelligenceCycleRun(
            cycle_run_id=mapping["cycle_run_id"],
            principal_id=mapping["principal_id"],
            cycle_id=mapping["cycle_id"],
            business_date=mapping["business_date"],
            state=CycleState(mapping["state"]),
            version=mapping["version"],
            created_at=mapping["created_at"],
            started_at=mapping["started_at"],
            finished_at=mapping["finished_at"],
            automation_platform=mapping["automation_platform"],
            external_root_run_id=mapping["external_root_run_id"],
        )

    def _run(self, row: RowMapping) -> IntelligenceProducerRun:
        mapping = dict(row)
        return IntelligenceProducerRun(
            run_id=mapping["run_id"],
            principal_id=mapping["principal_id"],
            cycle_run_id=mapping["cycle_run_id"],
            stage=IntelligenceStage(mapping["stage"]),
            artifact_kind=ArtifactKind(mapping["artifact_kind"]),
            state=ProducerRunState(mapping["state"]),
            version=mapping["version"],
            producer_task_id=mapping["producer_task_id"],
            producer_task_name=mapping["producer_task_name"],
            automation_platform=mapping["automation_platform"],
            report_date=mapping["report_date"],
            created_at=mapping["created_at"],
            focus_area_id=_area(mapping["focus_area_id"]),
            source_lane=_lane(mapping["source_lane"]),
            automation_run_id=mapping["automation_run_id"],
            coverage_start=mapping["coverage_start"],
            coverage_end=mapping["coverage_end"],
            started_at=mapping["started_at"],
            finished_at=mapping["finished_at"],
            failure_code=mapping["failure_code"],
            failure_summary=mapping["failure_summary"],
        )

    def _artifact(self, row: RowMapping) -> IntelligenceArtifact:
        mapping = dict(row)
        deps = self._dependencies(mapping["artifact_id"])
        refs = self._provenance(mapping["artifact_id"])
        structured = mapping.get("structured_content")
        if isinstance(structured, str):
            structured = json.loads(structured)
        if structured is not None and not isinstance(structured, dict):
            structured = None
        structured_content = cast(dict[str, object] | None, structured)
        return IntelligenceArtifact(
            artifact_id=mapping["artifact_id"],
            principal_id=mapping["principal_id"],
            cycle_run_id=mapping["cycle_run_id"],
            producer_run_id=mapping["producer_run_id"],
            stage=IntelligenceStage(mapping["stage"]),
            artifact_kind=ArtifactKind(mapping["artifact_kind"]),
            report_date=mapping["report_date"],
            title=mapping["title"],
            body_markdown=mapping["body_markdown"],
            content_sha256=mapping["content_sha256"],
            content_bytes=mapping["content_bytes"],
            artifact_state=ArtifactState(mapping["artifact_state"]),
            schema_version=mapping["schema_version"],
            generated_at=mapping["generated_at"],
            committed_at=mapping["committed_at"],
            version=mapping["version"],
            is_current=bool(mapping["is_current"]),
            focus_area_id=_area(mapping["focus_area_id"]),
            source_lane=_lane(mapping["source_lane"]),
            structured_content=structured_content,
            completeness=mapping["completeness"],
            producer_prompt_version=mapping["producer_prompt_version"],
            supersedes_artifact_id=mapping["supersedes_artifact_id"],
            dependencies=deps,
            provenance=refs,
        )

    def _dependencies(self, artifact_id: str) -> tuple[IntelligencePipelineDependency, ...]:
        statement = principal_scoped(
            select(intelligence_pipeline_dependencies).where(
                intelligence_pipeline_dependencies.c.downstream_artifact_id == artifact_id
            ),
            intelligence_pipeline_dependencies,
            self._context,
        )
        found = []
        for row in self._connection.execute(statement).mappings():
            found.append(
                IntelligencePipelineDependency(
                    upstream_artifact_id=row["upstream_artifact_id"],
                    dependency_role=row["dependency_role"],
                    required=bool(row["required"]),
                    expected_stage=None
                    if row["expected_stage"] is None
                    else IntelligenceStage(row["expected_stage"]),
                    expected_focus_area_id=_area(row["expected_focus_area_id"]),
                    expected_source_lane=_lane(row["expected_source_lane"]),
                )
            )
        return tuple(found)

    def _provenance(self, artifact_id: str) -> tuple[IntelligenceProvenanceRef, ...]:
        statement = principal_scoped(
            select(intelligence_provenance_refs)
            .where(intelligence_provenance_refs.c.artifact_id == artifact_id)
            .order_by(intelligence_provenance_refs.c.position),
            intelligence_provenance_refs,
            self._context,
        )
        found = []
        for row in self._connection.execute(statement).mappings():
            found.append(
                IntelligenceProvenanceRef(
                    source_system=row["source_system"],
                    source_ref=row["source_ref"],
                    relation=ProvenanceRelation(row["relation"]),
                    source_url=row["source_url"],
                    observed_at=row["observed_at"],
                    retrieved_at=row["retrieved_at"],
                    evidence_subject_id=row["evidence_subject_id"],
                )
            )
        return tuple(found)

    def _receipt(self, row: RowMapping) -> IntelligenceCommitReceipt:
        mapping = dict(row)
        return IntelligenceCommitReceipt(
            receipt_id=mapping["receipt_id"],
            principal_id=mapping["principal_id"],
            idempotency_key=mapping["idempotency_key"],
            mutation_kind=mapping["mutation_kind"],
            fingerprint_sha256=mapping["fingerprint_sha256"],
            created_at=mapping["created_at"],
            cycle_run_id=mapping["cycle_run_id"],
            producer_run_id=mapping["producer_run_id"],
            artifact_id=mapping["artifact_id"],
            content_sha256=mapping["content_sha256"],
            content_bytes=mapping["content_bytes"],
        )
