"""Values the Intelligence Artifact plane persists.

Committed artifact bodies and digests are immutable. Corrections create a
successor version with explicit lineage. Pipeline dependencies and external
provenance remain distinct relations.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
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

__all__ = [
    "IntelligenceArtifact",
    "IntelligenceCommitReceipt",
    "IntelligenceCycleRun",
    "IntelligencePipelineDependency",
    "IntelligenceProducerRun",
    "IntelligenceProvenanceRef",
    "MutationAdmission",
    "content_digest",
    "content_utf8_bytes",
    "fingerprint_payload",
]

_JSON_SEPARATORS: Final = (",", ":")


def content_utf8_bytes(body_markdown: str) -> bytes:
    """UTF-8 encoding of the stored Markdown/text body."""
    return body_markdown.encode("utf-8")


def content_digest(body_markdown: str) -> str:
    """Lowercase SHA-256 of the canonical stored UTF-8 Markdown."""
    return hashlib.sha256(content_utf8_bytes(body_markdown)).hexdigest()


def fingerprint_payload(payload: Mapping[str, Any]) -> str:
    """SHA-256 of canonical JSON. Key order is not caller-controlled."""
    encoded = json.dumps(
        payload, sort_keys=True, separators=_JSON_SEPARATORS, ensure_ascii=False, default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IntelligenceCycleRun:
    """One Morning Intelligence attempt. A business date alone is not identity."""

    cycle_run_id: str
    principal_id: str
    cycle_id: str
    business_date: date
    state: CycleState
    version: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    automation_platform: str | None = None
    external_root_run_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.cycle_run_id, IdKind.INTELLIGENCE_CYCLE_RUN)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if self.version < 1:
            raise ValueError("cycle version starts at one")


@dataclass(frozen=True, slots=True)
class IntelligenceProducerRun:
    """One producer attempt, including failure with no artifact body."""

    run_id: str
    principal_id: str
    cycle_run_id: str
    stage: IntelligenceStage
    artifact_kind: ArtifactKind
    state: ProducerRunState
    version: int
    producer_task_id: str
    producer_task_name: str
    automation_platform: str
    report_date: date
    created_at: datetime
    focus_area_id: FocusAreaId | None = None
    source_lane: SourceLaneId | None = None
    automation_run_id: str | None = None
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_code: str | None = None
    failure_summary: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.run_id, IdKind.INTELLIGENCE_RUN)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.cycle_run_id, IdKind.INTELLIGENCE_CYCLE_RUN)
        if self.version < 1:
            raise ValueError("run version starts at one")


@dataclass(frozen=True, slots=True)
class IntelligencePipelineDependency:
    """Exact upstream my-pa Intelligence artifact used to produce a downstream one."""

    upstream_artifact_id: str
    dependency_role: str
    required: bool = True
    expected_stage: IntelligenceStage | None = None
    expected_focus_area_id: FocusAreaId | None = None
    expected_source_lane: SourceLaneId | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.upstream_artifact_id, IdKind.INTELLIGENCE_ARTIFACT)
        if not self.dependency_role.strip():
            raise ValueError("a pipeline dependency names its role")


@dataclass(frozen=True, slots=True)
class IntelligenceProvenanceRef:
    """Compact external source reference. Not a copied source body."""

    source_system: str
    source_ref: str
    relation: ProvenanceRelation
    source_url: str | None = None
    observed_at: datetime | None = None
    retrieved_at: datetime | None = None
    evidence_subject_id: str | None = None

    def __post_init__(self) -> None:
        if not self.source_system.strip() or not self.source_ref.strip():
            raise ValueError("provenance names a system and a source ref")


@dataclass(frozen=True, slots=True)
class IntelligenceArtifact:
    """Immutable committed artifact content."""

    artifact_id: str
    principal_id: str
    cycle_run_id: str
    producer_run_id: str
    stage: IntelligenceStage
    artifact_kind: ArtifactKind
    report_date: date
    title: str
    body_markdown: str
    content_sha256: str
    content_bytes: int
    artifact_state: ArtifactState
    schema_version: str
    generated_at: datetime
    committed_at: datetime
    version: int
    is_current: bool
    focus_area_id: FocusAreaId | None = None
    source_lane: SourceLaneId | None = None
    structured_content: dict[str, object] | None = None
    completeness: str | None = None
    producer_prompt_version: str | None = None
    supersedes_artifact_id: str | None = None
    evaluation_metric_id: str | None = None
    evaluation_metric_version: str | None = None
    evaluation_score: str | None = None
    evaluation_state: str | None = None
    dependencies: tuple[IntelligencePipelineDependency, ...] = ()
    provenance: tuple[IntelligenceProvenanceRef, ...] = ()

    def __post_init__(self) -> None:
        validate_identifier(self.artifact_id, IdKind.INTELLIGENCE_ARTIFACT)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.cycle_run_id, IdKind.INTELLIGENCE_CYCLE_RUN)
        validate_identifier(self.producer_run_id, IdKind.INTELLIGENCE_RUN)
        if self.supersedes_artifact_id is not None:
            validate_identifier(self.supersedes_artifact_id, IdKind.INTELLIGENCE_ARTIFACT)
        if self.version < 1:
            raise ValueError("artifact version starts at one")
        if len(self.content_sha256) != 64 or self.content_sha256 != self.content_sha256.lower():
            raise ValueError("content digest is lowercase hex SHA-256")
        if self.content_bytes < 0:
            raise ValueError("content byte count cannot be negative")


@dataclass(frozen=True, slots=True)
class IntelligenceCommitReceipt:
    """Durable admission of one cycle begin, artifact commit, or run-state write."""

    receipt_id: str
    principal_id: str
    idempotency_key: str
    mutation_kind: str
    fingerprint_sha256: str
    created_at: datetime
    cycle_run_id: str
    producer_run_id: str | None = None
    artifact_id: str | None = None
    content_sha256: str | None = None
    content_bytes: int | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.receipt_id, IdKind.INTELLIGENCE_RECEIPT)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.cycle_run_id, IdKind.INTELLIGENCE_CYCLE_RUN)


@dataclass(frozen=True, slots=True)
class MutationAdmission:
    """Result of an idempotent mutation."""

    receipt: IntelligenceCommitReceipt
    created: bool
    replayed: bool
    cycle: IntelligenceCycleRun | None = None
    run: IntelligenceProducerRun | None = None
    artifact: IntelligenceArtifact | None = None
