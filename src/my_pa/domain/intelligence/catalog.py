"""Controlled Morning Intelligence catalog.

v1 keeps cycle membership, stages, focus areas, and source lanes in code so the
expected graph is not inferred from filenames or external task IDs. Adding a
future focus area or stage is a catalog change, not a schema redesign.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = [
    "ALLOWED_PROVENANCE_URL_SCHEMES",
    "ARTIFACT_KIND_FOR_STAGE",
    "CYCLE_MORNING_INTELLIGENCE",
    "EXPECTED_FOCUS_AREAS",
    "EXPECTED_SOURCE_LANES",
    "FOCUS_AREA_IDS",
    "MAX_ARTIFACT_BODY_BYTES",
    "MAX_IDEMPOTENCY_KEY_LENGTH",
    "MAX_STRUCTURED_CONTENT_BYTES",
    "REQUIRED_DEPENDENCY_COUNT",
    "RESOLVER_SET_IDS",
    "SOURCE_LANE_IDS",
    "STAGE_FOR_KIND",
    "ArtifactKind",
    "ArtifactState",
    "CycleState",
    "FocusAreaId",
    "IntelligenceStage",
    "ProducerRunState",
    "ProvenanceRelation",
    "ReadinessMemberState",
    "ResolverAggregateState",
    "ResolverSetId",
    "SourceLaneId",
    "expected_members",
    "validate_stage_coordinates",
]


CYCLE_MORNING_INTELLIGENCE: Final = "morning_intelligence"
MAX_ARTIFACT_BODY_BYTES: Final = 2 * 1024 * 1024
MAX_STRUCTURED_CONTENT_BYTES: Final = 64 * 1024
MAX_IDEMPOTENCY_KEY_LENGTH: Final = 128
ALLOWED_PROVENANCE_URL_SCHEMES: Final = frozenset({"https", "http"})


class FocusAreaId(StrEnum):
    """Stable focus-area identities, independent of Abacus task IDs."""

    RISK_DEADLINE_EXCEPTION = "risk_deadline_exception"
    DECISION_APPROVAL = "decision_approval"
    COMMUNICATIONS = "communications"
    PROJECT_PROGRAM_PULSE = "project_program_pulse"
    WATCHLIST_DEPENDENCY = "watchlist_dependency"
    ACTION_COMMITMENT = "action_commitment"


class SourceLaneId(StrEnum):
    """Researcher source lanes for one focus-area swarm."""

    SHAREPOINT = "sharepoint"
    ONEDRIVE = "onedrive"
    MY_PA = "my_pa"
    OUTLOOK = "outlook"
    TEAMS = "teams"


class IntelligenceStage(StrEnum):
    """Pipeline stages that persist a durable output."""

    COLLECTOR = "collector"
    RESEARCHER = "researcher"
    SYNTHESIZER = "synthesizer"
    REPORTER = "reporter"
    MORNING_BRIEF = "morning_brief"


class ArtifactKind(StrEnum):
    """Semantic artifact kinds that remain queryable and enforceable."""

    COLLECTOR_CANDIDATES = "collector_candidates"
    RESEARCH_CONTEXT = "research_context"
    SYNTHESIS_PACKAGE = "synthesis_package"
    FOCUS_REPORT = "focus_report"
    MORNING_BRIEF = "morning_brief"


class ArtifactState(StrEnum):
    """Committed artifact lifecycle. Body/digest are never rewritten."""

    PARTIAL = "partial"
    FINAL = "final"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class ProducerRunState(StrEnum):
    """Producer attempt state, including failure with no body."""

    SCHEDULED = "scheduled"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CycleState(StrEnum):
    """Mutable cycle-run state."""

    OPEN = "open"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProvenanceRelation(StrEnum):
    """How an external source relates to an artifact. Not pipeline lineage."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT = "context"
    DERIVED_FROM = "derived_from"


class ResolverSetId(StrEnum):
    """Declared resolver sets. Consumers never search filenames."""

    COLLECTORS = "collectors"
    RESEARCH_SWARM = "research_swarm"
    SYNTHESIZER_INPUTS = "synthesizer_inputs"
    REPORTER_INPUT = "reporter_input"
    MORNING_BRIEF_INPUTS = "morning_brief_inputs"


class ReadinessMemberState(StrEnum):
    """Per-member resolver readiness."""

    READY = "READY"
    MISSING = "MISSING"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"
    NOT_EXPECTED = "NOT_EXPECTED"


class ResolverAggregateState(StrEnum):
    """Aggregate resolver state. Degraded only when catalog policy says so."""

    READY = "READY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


FOCUS_AREA_IDS: Final = tuple(FocusAreaId)
SOURCE_LANE_IDS: Final = tuple(SourceLaneId)
EXPECTED_FOCUS_AREAS: Final = FOCUS_AREA_IDS
EXPECTED_SOURCE_LANES: Final = SOURCE_LANE_IDS
RESOLVER_SET_IDS: Final = tuple(ResolverSetId)

ARTIFACT_KIND_FOR_STAGE: Final[dict[IntelligenceStage, ArtifactKind]] = {
    IntelligenceStage.COLLECTOR: ArtifactKind.COLLECTOR_CANDIDATES,
    IntelligenceStage.RESEARCHER: ArtifactKind.RESEARCH_CONTEXT,
    IntelligenceStage.SYNTHESIZER: ArtifactKind.SYNTHESIS_PACKAGE,
    IntelligenceStage.REPORTER: ArtifactKind.FOCUS_REPORT,
    IntelligenceStage.MORNING_BRIEF: ArtifactKind.MORNING_BRIEF,
}

STAGE_FOR_KIND: Final[dict[ArtifactKind, IntelligenceStage]] = {
    kind: stage for stage, kind in ARTIFACT_KIND_FOR_STAGE.items()
}

REQUIRED_DEPENDENCY_COUNT: Final[dict[IntelligenceStage, int]] = {
    IntelligenceStage.COLLECTOR: 0,
    IntelligenceStage.RESEARCHER: 1,
    IntelligenceStage.SYNTHESIZER: 5,
    IntelligenceStage.REPORTER: 1,
    IntelligenceStage.MORNING_BRIEF: 6,
}

#: v1 Morning Intelligence policy: every expected member is required. A missing
#: Researcher lane blocks the Synthesizer; there is no silent degraded fallback.
REQUIRED_MEMBERSHIP: Final[dict[ResolverSetId, bool]] = {
    ResolverSetId.COLLECTORS: True,
    ResolverSetId.RESEARCH_SWARM: True,
    ResolverSetId.SYNTHESIZER_INPUTS: True,
    ResolverSetId.REPORTER_INPUT: True,
    ResolverSetId.MORNING_BRIEF_INPUTS: True,
}


def expected_members(
    set_id: ResolverSetId, *, focus_area_id: FocusAreaId | None = None
) -> tuple[tuple[str, FocusAreaId | None, SourceLaneId | None], ...]:
    """Expected resolver members as (member_key, focus_area, source_lane)."""
    if set_id is ResolverSetId.COLLECTORS:
        return tuple((area.value, area, None) for area in EXPECTED_FOCUS_AREAS)
    if set_id is ResolverSetId.RESEARCH_SWARM:
        if focus_area_id is None:
            raise ValueError("research_swarm requires a focus area")
        return tuple((lane.value, focus_area_id, lane) for lane in EXPECTED_SOURCE_LANES)
    if set_id is ResolverSetId.SYNTHESIZER_INPUTS:
        if focus_area_id is None:
            raise ValueError("synthesizer_inputs requires a focus area")
        return tuple((lane.value, focus_area_id, lane) for lane in EXPECTED_SOURCE_LANES)
    if set_id is ResolverSetId.REPORTER_INPUT:
        if focus_area_id is None:
            raise ValueError("reporter_input requires a focus area")
        return ((focus_area_id.value, focus_area_id, None),)
    return tuple((area.value, area, None) for area in EXPECTED_FOCUS_AREAS)


def validate_stage_coordinates(
    *,
    stage: IntelligenceStage,
    artifact_kind: ArtifactKind,
    focus_area_id: FocusAreaId | None,
    source_lane: SourceLaneId | None,
) -> None:
    """Fail closed when stage, kind, focus, and source-lane do not match."""
    expected_kind = ARTIFACT_KIND_FOR_STAGE[stage]
    if artifact_kind is not expected_kind:
        raise ValueError("stage and artifact_kind do not match")
    if stage is IntelligenceStage.MORNING_BRIEF:
        if focus_area_id is not None or source_lane is not None:
            raise ValueError("morning_brief forbids focus area and source lane")
        return
    if focus_area_id is None:
        raise ValueError("focus area is required for this stage")
    if stage is IntelligenceStage.RESEARCHER:
        if source_lane is None:
            raise ValueError("researcher requires a source lane")
        return
    if source_lane is not None:
        raise ValueError("source lane is forbidden for this stage")
