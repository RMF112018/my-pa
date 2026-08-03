"""The public capabilities and the purposes that may invoke them.

Binding capability to purpose in the domain keeps the rule in one place instead
of scattering it through transport or adapter conditionals.

**The failure mode here is silent, which is why both maps are exhaustive.**
`permitted_purposes` answers with the empty set for a capability nobody mapped,
so an unmapped member is denied for every purpose with no error anywhere — the
policy denial reads exactly like a deliberate one. `_OPERATOR_ONLY` fails the
other way: an unlisted member defaults to *not* operator-only, so a capability
that should have been restricted is silently open. Neither absence raises, so a
member added to `Capability` without a decision in both maps below is a defect
that no test of this module alone can see. `tests/unit/test_policy.py` compares
the mapping against the enum for exactly that reason.
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
    # The capture plane (`D-70`). `capture.create` is the name the canonical
    # package fixes in six places; the other three are this repository's choice
    # under `ADR-003:107`, which gives capability names to "an implementing work
    # package and its pull request". Two segments each, like the eight above,
    # and a domain act rather than CRUD — `revise` is ADR-003 clause 3's own
    # frame for an edit that appends a successor version.
    CAPTURE_CREATE = "capture.create"
    CAPTURE_REVISE = "capture.revise"
    CAPTURE_READ = "capture.read"
    CAPTURE_LIST = "capture.list"


#: Capabilities restricted to an authenticated operator principal.
#:
#: `sources.enroll` alone, and no capture capability, which is a decision rather
#: than a default (`D-70`). Enrollment **grants authority** — it widens the
#: authorized scope a later request is evaluated against — while a capture
#: creates content the principal already owns and grants nothing. Making capture
#: operator-only would also contradict the canonical direction of travel, where a
#: non-operator device client holds a permitted capture capability.
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
        Capability.CAPTURE_CREATE: frozenset({Purpose.CAPTURE_AUTHORING}),
        Capability.CAPTURE_REVISE: frozenset({Purpose.CAPTURE_AUTHORING}),
        Capability.CAPTURE_READ: frozenset({Purpose.CAPTURE_REVIEW}),
        Capability.CAPTURE_LIST: frozenset({Purpose.CAPTURE_REVIEW}),
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
