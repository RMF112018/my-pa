"""Exhaustive ChatLLM full-data-management capability policy.

Every public Capability has exactly one classification. A new enum member
without an explicit entry fails import. This module does not grant authority,
publish MCP tools, or mutate remote grants.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.identity.operation import Capability

CHATLLM_DATA_PROFILE_VERSION: Final = "chatllm-data-v1"


class ChatLLMCapabilityClass(StrEnum):
    DATA_REQUIRED = "CHATLLM_DATA_REQUIRED"
    DATA_CONDITIONAL = "CHATLLM_DATA_CONDITIONAL"
    COMPATIBILITY_ONLY = "CHATLLM_COMPATIBILITY_ONLY"
    CONTROL_PLANE_EXCLUDED = "CHATLLM_CONTROL_PLANE_EXCLUDED"
    OPERATOR_DECISION_REQUIRED = "CHATLLM_OPERATOR_DECISION_REQUIRED"
    RETIRED = "CHATLLM_RETIRED"


class ChatLLMCompositionPrerequisite(StrEnum):
    ALWAYS = "ALWAYS"
    MANAGED_DOCUMENTS = "MANAGED_DOCUMENTS"
    RELATIONSHIP_INTELLIGENCE = "RELATIONSHIP_INTELLIGENCE"
    RELATIONSHIP_MEMORY = "RELATIONSHIP_MEMORY"
    CONSTRAINTS = "CONSTRAINTS"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class ChatLLMCapabilityPolicy:
    capability: Capability
    classification: ChatLLMCapabilityClass
    family: str
    composition_prerequisite: ChatLLMCompositionPrerequisite
    compatibility_replacement: Capability | None
    exclusion_rationale: str | None


_DATA_REQUIRED: Final[frozenset[Capability]] = frozenset(
    {
        Capability.CANVAS_WORKSPACE_GET,
        Capability.CANVAS_WORKSPACE_PUT,
        Capability.CAPTURE_CREATE,
        Capability.CAPTURE_LIST,
        Capability.CAPTURE_READ,
        Capability.CAPTURE_REVISE,
        Capability.CAPTURE_SEARCH,
        Capability.COMMITMENTS_CLOSE,
        Capability.COMMITMENTS_CREATE,
        Capability.COMMITMENTS_HISTORY,
        Capability.COMMITMENTS_LIST,
        Capability.COMMITMENTS_READ,
        Capability.COMMITMENTS_SEARCH,
        Capability.COMMITMENTS_UPDATE,
        Capability.COMMITMENTS_WAITING_ON,
        Capability.CONTEXT_FEEDBACK,
        Capability.CONTEXT_PREPARE,
        Capability.CONTINUITY_PROJECTS,
        Capability.CONTINUITY_PROJECTS_CLOSE,
        Capability.CONTINUITY_PROJECTS_CREATE,
        Capability.CONTINUITY_PROJECTS_READ,
        Capability.CONTINUITY_PROJECTS_UPDATE,
        Capability.CONTINUITY_PULSE,
        Capability.CONTINUITY_SITUATIONS,
        Capability.CONTINUITY_SITUATIONS_CREATE,
        Capability.GOODNOTES_CONTENT,
        Capability.GOODNOTES_CORRECT,
        Capability.GOODNOTES_NOTEBOOKS_LIST,
        Capability.GOODNOTES_PAGES_LIST,
        Capability.GOODNOTES_PROPOSE,
        Capability.GOODNOTES_READ,
        Capability.GOODNOTES_RUNS_LIST,
        Capability.GOODNOTES_SEARCH,
        Capability.GOODNOTES_WORK,
        Capability.KNOWLEDGE_COVERAGE,
        Capability.KNOWLEDGE_READ,
        Capability.KNOWLEDGE_REVEAL,
        Capability.KNOWLEDGE_SEARCH,
        Capability.REPORTS_LATEST,
        Capability.REPORTS_LIST,
        Capability.REPORTS_READ,
        Capability.REPORTS_RESOLVE_SET,
        Capability.REPORTS_SEARCH,
        Capability.REVIEW_DECIDE,
        Capability.REVIEW_LIST,
        Capability.SOURCES_FETCH,
        Capability.SOURCES_LIST,
        Capability.SOURCES_METADATA,
        Capability.SOURCES_STATUS,
        Capability.TASKS_BULK_CONFIRM,
        Capability.TASKS_BULK_PREVIEW,
        Capability.TASKS_COMMENTS_CREATE,
        Capability.TASKS_COMMENTS_LIST,
        Capability.TASKS_CREATE,
        Capability.TASKS_HISTORY,
        Capability.TASKS_LIST,
        Capability.TASKS_READ,
        Capability.TASKS_SEARCH,
        Capability.TASKS_TRANSITION,
        Capability.TASKS_UPDATE,
    }
)

_DATA_CONDITIONAL: Final[frozenset[Capability]] = frozenset(
    {
        Capability.CONSTRAINT_CATEGORIES_CREATE,
        Capability.CONSTRAINT_CATEGORIES_DEACTIVATE,
        Capability.CONSTRAINT_CATEGORIES_LIST,
        Capability.CONSTRAINT_CATEGORIES_REORDER,
        Capability.CONSTRAINT_CATEGORIES_UPDATE,
        Capability.CONSTRAINTS_CLOSE,
        Capability.CONSTRAINTS_CLOSE_FOLLOW_UP,
        Capability.CONSTRAINTS_CREATE,
        Capability.CONSTRAINTS_CREATE_PUBLISHED,
        Capability.CONSTRAINTS_HISTORY,
        Capability.CONSTRAINTS_LIST,
        Capability.CONSTRAINTS_OVERVIEW,
        Capability.CONSTRAINTS_PORTFOLIO_LIST,
        Capability.CONSTRAINTS_PORTFOLIO_OVERVIEW,
        Capability.CONSTRAINTS_PORTFOLIO_SEARCH,
        Capability.CONSTRAINTS_PUBLISH,
        Capability.CONSTRAINTS_READ,
        Capability.CONSTRAINTS_REOPEN,
        Capability.CONSTRAINTS_SEARCH,
        Capability.CONSTRAINTS_TRANSITION,
        Capability.CONSTRAINTS_UPDATE,
        Capability.CONSTRAINTS_VOID,
        Capability.DOCUMENTS_ARCHIVE,
        Capability.DOCUMENTS_CREATE,
        Capability.DOCUMENTS_LIST,
        Capability.DOCUMENTS_READ,
        Capability.DOCUMENTS_RESTORE,
        Capability.DOCUMENTS_REVISE,
        Capability.ENTITIES_ADDRESSES_ADD,
        Capability.ENTITIES_ADDRESSES_LIST,
        Capability.ENTITIES_ADDRESSES_RETIRE,
        Capability.ENTITIES_ADDRESSES_REVISE,
        Capability.ENTITIES_AFFILIATIONS_CREATE,
        Capability.ENTITIES_AFFILIATIONS_END,
        Capability.ENTITIES_AFFILIATIONS_REVISE,
        Capability.ENTITIES_ALIASES_ADD,
        Capability.ENTITIES_ALIASES_LIST,
        Capability.ENTITIES_ALIASES_RETIRE,
        Capability.ENTITIES_ALIASES_SUPERSEDE,
        Capability.ENTITIES_ARCHIVE,
        Capability.ENTITIES_ASSIGNMENTS_CREATE,
        Capability.ENTITIES_ASSIGNMENTS_END,
        Capability.ENTITIES_ASSIGNMENTS_LIST,
        Capability.ENTITIES_ASSIGNMENTS_REVISE,
        Capability.ENTITIES_COMMUNICATION_ADD,
        Capability.ENTITIES_COMMUNICATION_LIST,
        Capability.ENTITIES_COMMUNICATION_RETIRE,
        Capability.ENTITIES_COMMUNICATION_REVISE,
        Capability.ENTITIES_CONTEXT,
        Capability.ENTITIES_CREATE,
        Capability.ENTITIES_GET,
        Capability.ENTITIES_GRAPH,
        Capability.ENTITIES_IDENTIFIERS_BIND,
        Capability.ENTITIES_IDENTIFIERS_LIST,
        Capability.ENTITIES_IDENTIFIERS_RETIRE,
        Capability.ENTITIES_IDENTIFIERS_SUPERSEDE,
        Capability.ENTITIES_IDENTITY_HISTORY,
        Capability.ENTITIES_NAMES_ADD,
        Capability.ENTITIES_NAMES_LIST,
        Capability.ENTITIES_NAMES_RETIRE,
        Capability.ENTITIES_NAMES_SUPERSEDE,
        Capability.ENTITIES_OBSERVATIONS_LIST,
        Capability.ENTITIES_OBSERVE,
        Capability.ENTITIES_PARTICIPATIONS_CREATE,
        Capability.ENTITIES_PARTICIPATIONS_END,
        Capability.ENTITIES_PARTICIPATIONS_LIST,
        Capability.ENTITIES_PARTICIPATIONS_REVISE,
        Capability.ENTITIES_PROFILE,
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.ENTITIES_RELATIONSHIPS,
        Capability.ENTITIES_RELATIONSHIPS_CREATE,
        Capability.ENTITIES_RELATIONSHIPS_END,
        Capability.ENTITIES_RELATIONSHIPS_REVISE,
        Capability.ENTITIES_RESOLVE,
        Capability.ENTITIES_RESTORE,
        Capability.ENTITIES_SEARCH,
        Capability.ENTITIES_UNRESOLVED_MENTIONS,
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE,
        Capability.ENTITIES_UPDATE,
        Capability.PROJECT_CONTROLS_CONFIGURE,
        Capability.PROJECT_CONTROLS_STATUS,
        Capability.RELATIONSHIP_MEMORY_ARCHIVE,
        Capability.RELATIONSHIP_MEMORY_CREATE,
        Capability.RELATIONSHIP_MEMORY_GET,
        Capability.RELATIONSHIP_MEMORY_HISTORY,
        Capability.RELATIONSHIP_MEMORY_LIST,
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
        Capability.RELATIONSHIP_MEMORY_RESTORE,
        Capability.RELATIONSHIP_MEMORY_REVISE,
        Capability.RELATIONSHIP_MEMORY_SEARCH,
    }
)

_COMPATIBILITY_ONLY: Final[frozenset[Capability]] = frozenset(
    {
        Capability.CAPABILITIES_GET,
        Capability.CONTINUITY_TASKS_CREATE,
    }
)

_CONTROL_PLANE_EXCLUDED: Final[frozenset[Capability]] = frozenset(
    {
        Capability.CONSTRAINT_SYNC_ACKNOWLEDGE,
        Capability.CONSTRAINT_SYNC_APPLY,
        Capability.CONSTRAINT_SYNC_CONFLICTS,
        Capability.CONSTRAINT_SYNC_DELTA,
        Capability.CONSTRAINT_SYNC_PREVIEW,
        Capability.CONSTRAINT_SYNC_RESOLVE,
        Capability.CONSTRAINT_SYNC_STATE,
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_SPLIT,
        Capability.ENTITIES_SPLIT_PREVIEW,
        Capability.GOODNOTES_COMPLETE,
        Capability.GOODNOTES_PULL,
        Capability.GOODNOTES_STATUS,
        Capability.SOURCES_ENROLL,
    }
)

_OPERATOR_DECISION_REQUIRED: Final[frozenset[Capability]] = frozenset(
    {
        Capability.GSQS_START,
        Capability.GSQS_STATUS,
        Capability.REPORTS_BEGIN_CYCLE,
        Capability.REPORTS_COMMIT,
        Capability.REPORTS_RECORD_RUN_STATE,
    }
)

_RETIRED: Final[frozenset[Capability]] = frozenset()

_COMPATIBILITY_REPLACEMENTS: Final[Mapping[Capability, Capability]] = MappingProxyType(
    {
        Capability.CONTINUITY_TASKS_CREATE: Capability.TASKS_CREATE,
    }
)

_SYNC_EXCLUSION: Final = "device sync protocol, not constraint record management"
_GSQS_EXCLUSION: Final = "GSQS campaign lifecycle held out pending reclassification"
_REPORT_CYCLE_EXCLUSION: Final = "report pipeline control held out pending reclassification"

_EXCLUSION_RATIONALE: Final[Mapping[Capability, str]] = MappingProxyType(
    {
        Capability.CAPABILITIES_GET: "ChatLLM my_pa.describe replaces catalog introspection",
        Capability.CONSTRAINT_SYNC_ACKNOWLEDGE: _SYNC_EXCLUSION,
        Capability.CONSTRAINT_SYNC_APPLY: _SYNC_EXCLUSION,
        Capability.CONSTRAINT_SYNC_CONFLICTS: _SYNC_EXCLUSION,
        Capability.CONSTRAINT_SYNC_DELTA: _SYNC_EXCLUSION,
        Capability.CONSTRAINT_SYNC_PREVIEW: _SYNC_EXCLUSION,
        Capability.CONSTRAINT_SYNC_RESOLVE: _SYNC_EXCLUSION,
        Capability.CONSTRAINT_SYNC_STATE: _SYNC_EXCLUSION,
        Capability.CONTINUITY_TASKS_CREATE: "Work-plane tasks.create is the ChatLLM replacement",
        Capability.ENTITIES_MERGE: "operator-only identity correction",
        Capability.ENTITIES_MERGE_PREVIEW: "operator-only identity correction",
        Capability.ENTITIES_SPLIT: "operator-only identity correction",
        Capability.ENTITIES_SPLIT_PREVIEW: "operator-only identity correction",
        Capability.GOODNOTES_COMPLETE: "source ingest/pull pipeline",
        Capability.GOODNOTES_PULL: "source ingest/pull pipeline",
        Capability.GOODNOTES_STATUS: "source ingest/pull pipeline",
        Capability.GSQS_START: _GSQS_EXCLUSION,
        Capability.GSQS_STATUS: _GSQS_EXCLUSION,
        Capability.REPORTS_BEGIN_CYCLE: _REPORT_CYCLE_EXCLUSION,
        Capability.REPORTS_COMMIT: _REPORT_CYCLE_EXCLUSION,
        Capability.REPORTS_RECORD_RUN_STATE: _REPORT_CYCLE_EXCLUSION,
        Capability.SOURCES_ENROLL: "operator-only source enrollment / authority expansion",
    }
)


def _family_of(capability: Capability) -> str:
    value = capability.value
    if value.startswith("constraint_categories."):
        return "constraint_categories"
    if value.startswith("constraint_sync."):
        return "constraint_sync"
    if value.startswith("project_controls."):
        return "project_controls"
    if value.startswith("relationship_memory."):
        return "relationship_memory"
    return value.split(".", 1)[0]


def _prerequisite_of(
    capability: Capability, classification: ChatLLMCapabilityClass
) -> ChatLLMCompositionPrerequisite:
    if classification in {
        ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED,
        ChatLLMCapabilityClass.COMPATIBILITY_ONLY,
        ChatLLMCapabilityClass.OPERATOR_DECISION_REQUIRED,
        ChatLLMCapabilityClass.RETIRED,
    }:
        return ChatLLMCompositionPrerequisite.NONE
    value = capability.value
    if value.startswith("documents."):
        return ChatLLMCompositionPrerequisite.MANAGED_DOCUMENTS
    if value.startswith("entities."):
        return ChatLLMCompositionPrerequisite.RELATIONSHIP_INTELLIGENCE
    if value.startswith("relationship_memory."):
        return ChatLLMCompositionPrerequisite.RELATIONSHIP_MEMORY
    if (
        value.startswith("constraints.")
        or value.startswith("constraint_categories.")
        or value.startswith("project_controls.")
    ):
        return ChatLLMCompositionPrerequisite.CONSTRAINTS
    return ChatLLMCompositionPrerequisite.ALWAYS


def _classification_of(capability: Capability) -> ChatLLMCapabilityClass:
    if capability in _DATA_REQUIRED:
        return ChatLLMCapabilityClass.DATA_REQUIRED
    if capability in _DATA_CONDITIONAL:
        return ChatLLMCapabilityClass.DATA_CONDITIONAL
    if capability in _COMPATIBILITY_ONLY:
        return ChatLLMCapabilityClass.COMPATIBILITY_ONLY
    if capability in _CONTROL_PLANE_EXCLUDED:
        return ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED
    if capability in _OPERATOR_DECISION_REQUIRED:
        return ChatLLMCapabilityClass.OPERATOR_DECISION_REQUIRED
    if capability in _RETIRED:
        return ChatLLMCapabilityClass.RETIRED
    raise RuntimeError(f"unclassified ChatLLM capability: {capability.value}")


def _build_policy() -> Mapping[Capability, ChatLLMCapabilityPolicy]:
    classified = (
        _DATA_REQUIRED
        | _DATA_CONDITIONAL
        | _COMPATIBILITY_ONLY
        | _CONTROL_PLANE_EXCLUDED
        | _OPERATOR_DECISION_REQUIRED
        | _RETIRED
    )
    missing = frozenset(Capability) - classified
    extra = classified - frozenset(Capability)
    if missing or extra:
        raise RuntimeError(
            "ChatLLM capability policy is not exhaustive: "
            f"missing={sorted(item.value for item in missing)} "
            f"extra={sorted(item.value for item in extra)}"
        )
    overlap_sources = (
        _DATA_REQUIRED,
        _DATA_CONDITIONAL,
        _COMPATIBILITY_ONLY,
        _CONTROL_PLANE_EXCLUDED,
        _OPERATOR_DECISION_REQUIRED,
        _RETIRED,
    )
    seen: set[Capability] = set()
    for group in overlap_sources:
        if seen & group:
            raise RuntimeError("ChatLLM capability policy has duplicate classification")
        seen |= set(group)
    built: dict[Capability, ChatLLMCapabilityPolicy] = {}
    for capability in Capability:
        classification = _classification_of(capability)
        built[capability] = ChatLLMCapabilityPolicy(
            capability=capability,
            classification=classification,
            family=_family_of(capability),
            composition_prerequisite=_prerequisite_of(capability, classification),
            compatibility_replacement=_COMPATIBILITY_REPLACEMENTS.get(capability),
            exclusion_rationale=_EXCLUSION_RATIONALE.get(capability),
        )
    return MappingProxyType(built)


CHATLLM_CAPABILITY_POLICY: Final[Mapping[Capability, ChatLLMCapabilityPolicy]] = _build_policy()


def chatllm_policy_for(capability: Capability) -> ChatLLMCapabilityPolicy:
    return CHATLLM_CAPABILITY_POLICY[capability]


def is_chatllm_data_management(capability: Capability) -> bool:
    classification = CHATLLM_CAPABILITY_POLICY[capability].classification
    return classification in {
        ChatLLMCapabilityClass.DATA_REQUIRED,
        ChatLLMCapabilityClass.DATA_CONDITIONAL,
    }
