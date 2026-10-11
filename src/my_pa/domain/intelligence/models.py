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
    BUILTIN_REPORT_TYPES,
    MAX_REPORT_TYPE_DESCRIPTION_CHARACTERS,
    MAX_REPORT_TYPE_DISPLAY_NAME_CHARACTERS,
    ArtifactKind,
    ArtifactState,
    CycleState,
    FocusAreaId,
    IntelligenceStage,
    ProducerRunState,
    ProvenanceRelation,
    ReportTypeOrigin,
    SourceLaneId,
    parse_artifact_kind,
)

__all__ = [
    "IntelligenceArtifact",
    "IntelligenceCommitReceipt",
    "IntelligenceCycleRun",
    "IntelligencePipelineDependency",
    "IntelligenceProducerRun",
    "IntelligenceProvenanceRef",
    "IntelligenceReportType",
    "MutationAdmission",
    "ReportTypeDefinition",
    "ReportTypeInsertion",
    "builtin_report_type_definitions",
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
    #: A validated kind token: an ``ArtifactKind`` member for a built-in kind,
    #: otherwise a kind registered for this Principal at ``stage``.
    artifact_kind: str
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
        object.__setattr__(self, "artifact_kind", parse_artifact_kind(self.artifact_kind))
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
    #: A validated kind token; see ``IntelligenceProducerRun.artifact_kind``.
    artifact_kind: str
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
        object.__setattr__(self, "artifact_kind", parse_artifact_kind(self.artifact_kind))
        if self.supersedes_artifact_id is not None:
            validate_identifier(self.supersedes_artifact_id, IdKind.INTELLIGENCE_ARTIFACT)
        if self.version < 1:
            raise ValueError("artifact version starts at one")
        if len(self.content_sha256) != 64 or self.content_sha256 != self.content_sha256.lower():
            raise ValueError("content digest is lowercase hex SHA-256")
        if self.content_bytes < 0:
            raise ValueError("content byte count cannot be negative")


@dataclass(frozen=True, slots=True)
class ReportTypeDefinition:
    """One report type's definition, without the Principal it is registered for.

    The Principal is never part of a definition: a store stamps it from its own
    scope, so a definition cannot name somebody else's registry.
    """

    artifact_kind: str
    stage: IntelligenceStage
    description: str
    origin: ReportTypeOrigin
    display_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_kind", parse_artifact_kind(self.artifact_kind))
        if not isinstance(self.stage, IntelligenceStage):
            raise ValueError("a report type names a known stage")
        if not isinstance(self.origin, ReportTypeOrigin):
            raise ValueError("a report type names a known origin")
        if not 1 <= len(self.description) <= MAX_REPORT_TYPE_DESCRIPTION_CHARACTERS:
            raise ValueError("a report type description is 1 to 500 characters")
        if self.display_name is not None and not (
            1 <= len(self.display_name) <= MAX_REPORT_TYPE_DISPLAY_NAME_CHARACTERS
        ):
            raise ValueError("a report type display name is 1 to 120 characters")
        builtin = isinstance(self.artifact_kind, ArtifactKind)
        if self.origin is ReportTypeOrigin.CLIENT and builtin:
            raise ValueError("a client report type cannot redefine a built-in kind")
        if self.origin is ReportTypeOrigin.BUILTIN and (
            not builtin
            or (self.artifact_kind, self.stage)
            not in {(kind, stage) for kind, stage, _, _ in BUILTIN_REPORT_TYPES}
        ):
            raise ValueError("a built-in report type is one of the built-in kind and stage pairs")

    @property
    def fingerprint(self) -> str:
        """SHA-256 of the canonical definition; replay compares this."""
        return fingerprint_payload(
            {
                "artifact_kind": str(self.artifact_kind),
                "description": self.description,
                "display_name": self.display_name,
                "stage": self.stage.value,
            }
        )


@dataclass(frozen=True, slots=True)
class IntelligenceReportType:
    """One registered report type, as stored for one Principal. Immutable."""

    principal_id: str
    definition: ReportTypeDefinition
    definition_fingerprint: str
    created_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if (
            len(self.definition_fingerprint) != 64
            or self.definition_fingerprint != self.definition_fingerprint.lower()
        ):
            raise ValueError("definition fingerprint is lowercase hex SHA-256")


@dataclass(frozen=True, slots=True)
class ReportTypeInsertion:
    """Result of an insert-if-absent: the stored row and whether this call wrote it.

    ``inserted`` is False when a row for the kind already existed; the stored
    row is then the existing one, which may hold a different definition.
    """

    report_type: IntelligenceReportType
    inserted: bool


def builtin_report_type_definitions() -> tuple[ReportTypeDefinition, ...]:
    """The five built-in definitions, in pipeline order."""
    return tuple(
        ReportTypeDefinition(
            artifact_kind=kind,
            stage=stage,
            description=description,
            origin=ReportTypeOrigin.BUILTIN,
            display_name=display_name,
        )
        for kind, stage, description, display_name in BUILTIN_REPORT_TYPES
    )


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
