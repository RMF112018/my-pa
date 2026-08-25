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


_STANDARD = frozenset(
    {
        Capability.ENTITIES_SEARCH,
        Capability.ENTITIES_GET,
        Capability.ENTITIES_RESOLVE,
        Capability.ENTITIES_CONTEXT,
        Capability.ENTITIES_RELATIONSHIPS,
        Capability.RELATIONSHIP_MEMORY_LIST,
        Capability.RELATIONSHIP_MEMORY_GET,
    }
)
_PRODUCER = _STANDARD | frozenset(
    {
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
    }
)
_REVIEWER = _STANDARD | frozenset(
    {
        Capability.REVIEW_LIST,
        Capability.REVIEW_DECIDE,
    }
)
_OPERATOR = _REVIEWER | frozenset(
    {
        Capability.ENTITIES_UNRESOLVED_MENTIONS,
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
