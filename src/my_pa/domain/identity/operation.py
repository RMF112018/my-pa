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
    # The thirteenth, and it is a capability rather than a widening of
    # `knowledge.search` (`D-91`). `domain.identity.purpose` already argues why:
    # the knowledge plane is the *extraction* plane, and one grant spanning both
    # would let a `knowledge.read`-shaped request return raw user-authored
    # capture text. There is also no scope to share — `knowledge.search` is
    # scoped by enrollment and a capture belongs to none. The word `search`
    # bound to the capture noun is the canonical package's own
    # (`docs/specs/quick-capture/18_PROPOSED_API_AND_CONTRACT_PACKAGE.md:334`),
    # and two segments of `noun.verb` is the rule the four above follow.
    CAPTURE_SEARCH = "capture.search"
    # `review.list` and `review.decide` are the fourteenth and fifteenth, and
    # `3c8f1e2a5b74` already carries the forward `ALTER` that admits them — the
    # freeze is written before the members, because a member with no `ALTER`
    # leaves every test green and is refused by the stored constraint on the
    # first audited operation in the field. They are not declared here yet, and
    # the reason is a coupling this enum does not advertise: `adapters/mcp/tools`
    # builds its tool list at import from `Capability` and indexes
    # `application.commands.Command` by each member's `capability`, so a member
    # with no command raises `KeyError` at import and takes the whole package
    # with it. The member, its command and its handler are one indivisible
    # change. `tests/schema/test_capture_schema_migration.py` names exactly what
    # is missing and reddens when it arrives.


#: Capabilities restricted to an authenticated operator principal.
#:
#: `sources.enroll` alone, and no capture capability, which is a decision rather
#: than a default (`D-70`). Enrollment **grants authority** — it widens the
#: authorized scope a later request is evaluated against — while a capture
#: creates content the principal already owns and grants nothing. Making capture
#: operator-only would also contradict the canonical direction of travel, where a
#: non-operator device client holds a permitted capture capability.
#:
#: `capture.search` is decided on the same terms and reaches the same answer: it
#: reads rows `capture.read` and `capture.list` already return to the same
#: principal under the same purpose, so restricting the *search* over them while
#: leaving the *read* of them open would restrict nothing and would tell a
#: caller that finding a capture is a more privileged act than opening it.
#:
#: `review.list` and `review.decide` are decided the same way and reach the same
#: answer, and neither belongs here when it arrives. Deciding a review is the
#: most consequential capture-plane act there is, but it grants no authority: it
#: promotes the principal's own proposal about the principal's own capture.
#: Enrollment is operator-only because it *widens* the scope a later request is
#: evaluated against, and a review disposition widens nothing. Under
#: `P00-OD-010` there is one local principal in any case, so making it
#: operator-only would restrict nobody while implying an authority boundary this
#: build cannot draw.
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
        # `CAPTURE_REVIEW` reused rather than a `capture_search` purpose added
        # (`D-91`). Searching captures is a read of the same rows under the same
        # authority as `capture.read` and `capture.list`, so a purpose of its own
        # would separate nothing — it would map to exactly one capability — while
        # costing another frozen-constraint `ALTER` on `purpose_is_known`.
        Capability.CAPTURE_SEARCH: frozenset({Purpose.CAPTURE_REVIEW}),
        # `review.list` maps to `CAPTURE_REVIEW` and `review.decide` to a purpose
        # of its own; both land with the capabilities themselves, for the reason
        # the enum above records.
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
