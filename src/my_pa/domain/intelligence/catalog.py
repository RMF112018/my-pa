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
    "MIN_SYNTHESIZER_DEPENDENCY_COUNT",
    "REQUIRED_DEPENDENCY_COUNT",
    "REQUIRED_MEMBERSHIP",
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
    """Stable focus-area identities, independent of Abacus task IDs.

    Every member is admitted for commit and run-state recording; only
    ``EXPECTED_FOCUS_AREAS`` is required by cycle membership.
    """

    RISK_DEADLINE_EXCEPTION = "risk_deadline_exception"
    DECISION_APPROVAL = "decision_approval"
    COMMUNICATIONS = "communications"
    PROJECT_PROGRAM_PULSE = "project_program_pulse"
    WATCHLIST_DEPENDENCY = "watchlist_dependency"
    ACTION_COMMITMENT = "action_commitment"
    CAPTURES = "captures"
    NOTES = "notes"
    FIELD_INTELLIGENCE = "field_intelligence"


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
    """Aggregate resolver state. Degraded only when catalog policy says so.

    For the optional-membership sets, ``DEGRADED`` means at least one eligible
    member is partial; ``BLOCKED`` means no member is eligible.
    """

    READY = "READY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


FOCUS_AREA_IDS: Final = tuple(FocusAreaId)
SOURCE_LANE_IDS: Final = tuple(SourceLaneId)
#: The focus areas every Morning Intelligence cycle requires. ``FOCUS_AREA_IDS``
#: is the admitted set; ``captures``, ``notes`` and ``field_intelligence`` are
#: admitted but deliberately not expected, so collector and morning-brief
#: membership stays these six.
EXPECTED_FOCUS_AREAS: Final[tuple[FocusAreaId, ...]] = (
    FocusAreaId.RISK_DEADLINE_EXCEPTION,
    FocusAreaId.DECISION_APPROVAL,
    FocusAreaId.COMMUNICATIONS,
    FocusAreaId.PROJECT_PROGRAM_PULSE,
    FocusAreaId.WATCHLIST_DEPENDENCY,
    FocusAreaId.ACTION_COMMITMENT,
)
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

#: Exact dependency count for every stage whose dependency set is fixed. The
#: Synthesizer is deliberately absent: it takes any non-empty set of distinct
#: Researcher lanes, bounded below by ``MIN_SYNTHESIZER_DEPENDENCY_COUNT`` and
#: above by the lane vocabulary, because each lane may appear at most once.
REQUIRED_DEPENDENCY_COUNT: Final[dict[IntelligenceStage, int]] = {
    IntelligenceStage.COLLECTOR: 0,
    IntelligenceStage.RESEARCHER: 1,
    IntelligenceStage.REPORTER: 1,
    IntelligenceStage.MORNING_BRIEF: 6,
}

#: The fewest Researcher dependencies a Synthesizer may name. Which lanes a
#: focus area runs is an operator decision, not a catalog fact, so there is no
#: "missing commissioned lane" rule: an absent lane is simply not an input.
MIN_SYNTHESIZER_DEPENDENCY_COUNT: Final = 1

#: Whether each member of a resolver set must be ready for the set to be ready.
#:
#: ``research_swarm`` and ``synthesizer_inputs`` list every source lane for
#: information, but no lane is required: the set is ready when at least one lane
#: is eligible (a current, lineage-fresh Researcher head), degraded when any
#: eligible lane is partial, and blocked only when no lane is eligible. The
#: eligible lanes are exactly the set a Synthesizer commit accepts.
#: ``reporter_input`` stays required: the one Synthesizer head must be eligible.
#: ``collectors`` and ``morning_brief_inputs`` keep the original every-member
#: policy.
REQUIRED_MEMBERSHIP: Final[dict[ResolverSetId, bool]] = {
    ResolverSetId.COLLECTORS: True,
    ResolverSetId.RESEARCH_SWARM: False,
    ResolverSetId.SYNTHESIZER_INPUTS: False,
    ResolverSetId.REPORTER_INPUT: True,
    ResolverSetId.MORNING_BRIEF_INPUTS: True,
}


def expected_members(
    set_id: ResolverSetId, *, focus_area_id: FocusAreaId | None = None
) -> tuple[tuple[str, FocusAreaId | None, SourceLaneId | None], ...]:
    """Expected resolver members as (member_key, focus_area, source_lane).

    ``research_swarm`` and ``synthesizer_inputs`` list every source lane so a
    caller sees each lane's state; ``REQUIRED_MEMBERSHIP`` says none of them is
    required.
    """
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
