"""Dormant, immutable Relationship Intelligence grant profiles.

These declarations do not activate a task, credential, or production grant.
They are the bounded ceilings a composition may choose to apply.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

from my_pa.domain.identity.operation import Capability


@dataclass(frozen=True, slots=True)
class RelationshipGrantProfile:
    name: str
    transport: Literal["local", "remote"]
    capabilities: frozenset[Capability]
    denied: frozenset[Capability]


_ENTITY_READS = frozenset(
    {
        Capability.ENTITIES_SEARCH,
        Capability.ENTITIES_GET,
        Capability.ENTITIES_RESOLVE,
        Capability.ENTITIES_CONTEXT,
        Capability.ENTITIES_IDENTIFIERS_LIST,
        Capability.ENTITIES_ALIASES_LIST,
        Capability.ENTITIES_ASSIGNMENTS_LIST,
        Capability.ENTITIES_RELATIONSHIPS,
        Capability.ENTITIES_OBSERVATIONS_LIST,
        Capability.ENTITIES_UNRESOLVED_MENTIONS,
    }
)
_ROUTINE_ENTITY_AUTHORING = frozenset(
    {
        Capability.ENTITIES_CREATE,
        Capability.ENTITIES_UPDATE,
        Capability.ENTITIES_ARCHIVE,
        Capability.ENTITIES_RESTORE,
        Capability.ENTITIES_IDENTIFIERS_BIND,
        Capability.ENTITIES_IDENTIFIERS_RETIRE,
        Capability.ENTITIES_IDENTIFIERS_SUPERSEDE,
        Capability.ENTITIES_ALIASES_ADD,
        Capability.ENTITIES_ALIASES_RETIRE,
        Capability.ENTITIES_ALIASES_SUPERSEDE,
        Capability.ENTITIES_ASSIGNMENTS_CREATE,
        Capability.ENTITIES_ASSIGNMENTS_REVISE,
        Capability.ENTITIES_ASSIGNMENTS_END,
        Capability.ENTITIES_RELATIONSHIPS_CREATE,
        Capability.ENTITIES_RELATIONSHIPS_REVISE,
        Capability.ENTITIES_RELATIONSHIPS_END,
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE,
    }
)
_RELATIONSHIP_MEMORY = frozenset(
    {
        Capability.RELATIONSHIP_MEMORY_CREATE,
        Capability.RELATIONSHIP_MEMORY_LIST,
        Capability.RELATIONSHIP_MEMORY_GET,
        Capability.RELATIONSHIP_MEMORY_SEARCH,
        Capability.RELATIONSHIP_MEMORY_HISTORY,
        Capability.RELATIONSHIP_MEMORY_REVISE,
        Capability.RELATIONSHIP_MEMORY_ARCHIVE,
        Capability.RELATIONSHIP_MEMORY_RESTORE,
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
    }
)
_STANDARD = (
    _ENTITY_READS
    | _ROUTINE_ENTITY_AUTHORING
    | _RELATIONSHIP_MEMORY
    | frozenset({Capability.ENTITIES_PROPOSALS_CREATE, Capability.REVIEW_LIST})
)
_PRODUCER = frozenset(
    {
        Capability.ENTITIES_SEARCH,
        Capability.ENTITIES_GET,
        Capability.ENTITIES_RESOLVE,
        Capability.ENTITIES_CONTEXT,
        Capability.ENTITIES_RELATIONSHIPS,
        Capability.ENTITIES_OBSERVE,
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
        Capability.REVIEW_LIST,
    }
)
_REVIEWER = _STANDARD | frozenset({Capability.REVIEW_DECIDE})
_OPERATOR = _REVIEWER | frozenset(
    {
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
    }
)
_IDENTITY_MUTATIONS = frozenset({Capability.ENTITIES_MERGE_PREVIEW, Capability.ENTITIES_MERGE})
_TRANSPORTS: Final[tuple[Literal["local", "remote"], ...]] = ("local", "remote")


def _profile(
    name: str,
    transport: Literal["local", "remote"],
    capabilities: frozenset[Capability],
) -> RelationshipGrantProfile:
    denied = _IDENTITY_MUTATIONS if name != "operator" else frozenset()
    return RelationshipGrantProfile(name, transport, capabilities, denied)


RELATIONSHIP_GRANT_PROFILES: Final[Mapping[str, RelationshipGrantProfile]] = MappingProxyType(
    {
        f"{transport}.{name}": _profile(name, transport, capabilities)
        for transport in _TRANSPORTS
        for name, capabilities in (
            ("standard", _STANDARD),
            ("producer", _PRODUCER),
            ("reviewer", _REVIEWER),
            ("operator", _OPERATOR),
        )
    }
)

__all__ = ["RELATIONSHIP_GRANT_PROFILES", "RelationshipGrantProfile"]
