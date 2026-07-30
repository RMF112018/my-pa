"""The eight public capabilities and the purposes that may invoke them.

Binding capability to purpose in the domain keeps the rule in one place instead
of scattering it through transport or adapter conditionals.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from my_pa.domain.identity.purpose import Purpose

__all__ = ["Capability", "is_operator_only", "permitted_purposes"]


class Capability(StrEnum):
    """Public capability names in the `my-pa-public-capabilities` v1 family."""

    CAPABILITIES_GET = "capabilities.get"
    SOURCES_LIST = "sources.list"
    SOURCES_METADATA = "sources.metadata"
    SOURCES_FETCH = "sources.fetch"
    SOURCES_STATUS = "sources.status"
    SOURCES_ENROLL = "sources.enroll"
    KNOWLEDGE_SEARCH = "knowledge.search"
    KNOWLEDGE_READ = "knowledge.read"


#: Capabilities restricted to an authenticated operator principal.
_OPERATOR_ONLY: frozenset[Capability] = frozenset({Capability.SOURCES_ENROLL})

_PERMITTED_PURPOSES: Mapping[Capability, frozenset[Purpose]] = MappingProxyType(
    {
        Capability.CAPABILITIES_GET: frozenset(
            {Purpose.STATUS_OBSERVATION, Purpose.SECURITY_VALIDATION}
        ),
        Capability.SOURCES_LIST: frozenset({Purpose.SOURCE_INSPECTION}),
        Capability.SOURCES_METADATA: frozenset({Purpose.SOURCE_INSPECTION}),
        Capability.SOURCES_FETCH: frozenset(
            {Purpose.SOURCE_INSPECTION, Purpose.CONTENT_EXTRACTION}
        ),
        Capability.SOURCES_STATUS: frozenset({Purpose.STATUS_OBSERVATION}),
        Capability.SOURCES_ENROLL: frozenset({Purpose.BOUNDED_ENROLLMENT}),
        Capability.KNOWLEDGE_SEARCH: frozenset({Purpose.KNOWLEDGE_SEARCH}),
        Capability.KNOWLEDGE_READ: frozenset({Purpose.KNOWLEDGE_READ}),
    }
)


def is_operator_only(capability: Capability) -> bool:
    """Return whether `capability` requires an authenticated operator."""
    return capability in _OPERATOR_ONLY


def permitted_purposes(capability: Capability) -> frozenset[Purpose]:
    """Return the purposes that may invoke `capability`.

    An unmapped capability yields the empty set, so policy denies it.
    """
    return _PERMITTED_PURPOSES.get(capability, frozenset())
