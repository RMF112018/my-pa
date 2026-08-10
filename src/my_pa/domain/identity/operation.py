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

__all__ = [
    "AuthorizedCapability",
    "Capability",
    "NativeSourceCapability",
    "is_operator_only",
    "permitted_purposes",
]


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
    # The sixteenth, and `5e2c7b0a94f6` carries the forward `ALTER` that admits
    # it — written before the member, for the reason the two below record.
    #
    # **A capability rather than a widening of `knowledge.read`.** `read`
    # answers *what* one stored record says inside one enrollment's grant;
    # `reveal` answers *why* a derived record exists, by returning the evidence
    # spans under it, the version and capture they lie in, and the derivation
    # trace from proposal through review case and decision to assertion and
    # promotion receipt. Those are different rows, a different scope — a capture
    # belongs to no enrollment — and a different answer, so one grant covering
    # both would let a request issued to read a record also traverse lineage.
    #
    # **`knowledge.` rather than `capture.`** because the question is about the
    # product's knowledge of a subject rather than about the capture plane's own
    # storage, and a caller holding a subject identifier does not know which
    # plane it came from. What the *build* can traverse is narrower than that
    # name, and Reveal says so in its answer rather than in its name: a subject
    # this evidence model does not cover is reported `unavailable` rather than
    # answered with an empty result.
    KNOWLEDGE_REVEAL = "knowledge.reveal"
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
    # first audited operation in the field. The members, commands, and handlers
    # land together because `adapters/mcp/tools` derives its tool set at import.
    REVIEW_LIST = "review.list"
    REVIEW_DECIDE = "review.decide"
    # The seventeenth, eighteenth and nineteenth, and `8f2b6c4d1a37` carries the
    # forward `ALTER` that admits all three — written before the members, for the
    # reason `5e2c7b0a94f6` records: a member with no `ALTER` leaves every test
    # green, because every test builds its database from scratch, and is refused
    # by the stored constraint on the first audited operation in the field.
    #
    # **`continuity.` rather than `knowledge.`** because these read the durable
    # continuity plane — Situations, Projects, Commitments, Decisions, Tasks —
    # which belongs to no enrollment and holds no extracted record. Reaching them
    # under a `knowledge.` name would tell a caller that a grant issued over the
    # extraction plane covers the Principal's own obligations, and it does not.
    #
    # **Three rather than one.** A single `continuity.read` would make the Pulse,
    # the Situation board and the Project list one grant, and they are three
    # different answers over three different row sets: Pulse *derives* and ranks,
    # Situations lists a partition, Projects lists another. `D-91`'s test — does
    # one name reach rows another does not — separates them.
    #
    # None is operator-only: each reads the acting Principal's own accepted
    # records, grants nothing, and promotes nothing.
    CONTINUITY_PULSE = "continuity.pulse"
    CONTINUITY_SITUATIONS = "continuity.situations"
    CONTINUITY_PROJECTS = "continuity.projects"


class NativeSourceCapability(StrEnum):
    """Authenticated native-host commands, separate from legacy public transports."""

    DISCOVER = "native_sources.discover"
    CONFIGURE = "native_sources.configure"
    PREFLIGHT = "native_sources.preflight"
    SYNC = "native_sources.sync"
    STATUS = "native_sources.status"
    RETRY = "native_sources.retry"
    RECONCILE = "native_sources.reconcile"
    PAUSE = "native_sources.pause"
    RESUME = "native_sources.resume"
    BACKFILL = "native_sources.backfill"
    DISABLE = "native_sources.disable"


type AuthorizedCapability = Capability | NativeSourceCapability


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
#:
#: `knowledge.reveal` is decided last and reaches the same answer for the
#: narrowest reason: it grants nothing and reads nothing a permitted capability
#: does not already return. Restricting the *explanation* of a record while
#: leaving the record itself readable would tell a caller that understanding
#: what it is looking at is more privileged than looking at it.
_OPERATOR_ONLY: frozenset[AuthorizedCapability] = frozenset(
    {
        Capability.SOURCES_ENROLL,
        NativeSourceCapability.CONFIGURE,
        NativeSourceCapability.PREFLIGHT,
        NativeSourceCapability.SYNC,
        NativeSourceCapability.RETRY,
        NativeSourceCapability.RECONCILE,
        NativeSourceCapability.PAUSE,
        NativeSourceCapability.RESUME,
        NativeSourceCapability.BACKFILL,
        NativeSourceCapability.DISABLE,
    }
)

_PERMITTED_PURPOSES: Mapping[AuthorizedCapability, frozenset[Purpose]] = MappingProxyType(
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
        # `CAPTURE_REVIEW` rather than a purpose of its own, and rather than
        # `KNOWLEDGE_READ` despite the capability's name. The test is `D-91`'s:
        # does the reuse widen the grant? Reveal reads exactly the rows
        # `capture.read`, `capture.list`, `capture.search` and `review.list`
        # already return to the same Principal, and returns no capture text at
        # all — spans carry offsets, a basis and a digest, never a quote — so it
        # widens nothing. `KNOWLEDGE_READ` would be the escalation this module
        # refuses in the other direction: that purpose is the *extraction*
        # plane's, and admitting a capture-plane traversal under it would make a
        # grant issued for one plane reach the other.
        Capability.KNOWLEDGE_REVEAL: frozenset({Purpose.CAPTURE_REVIEW}),
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
        Capability.REVIEW_LIST: frozenset({Purpose.CAPTURE_REVIEW}),
        Capability.REVIEW_DECIDE: frozenset({Purpose.REVIEW_DISPOSITION}),
        # The three continuity reads map to `CAPTURE_REVIEW`. **No purpose is
        # widened, and the residual is stated rather than smoothed over.**
        #
        # `D-91`'s test asks whether reuse widens the grant. Honestly answered:
        # partly. What the three reads return is the accepted end of the same
        # chain `capture_review` already covers — a Situation, a Project, a
        # Commitment is what a promoted proposal becomes — and they promote
        # nothing, write nothing, grant nothing, and return only the acting
        # Principal's own *accepted* rows. But `capture_review` did not reach the
        # continuity tables before this package, and after it a grant issued for
        # reviewing captures reaches them. That is the cost, and it is paid for
        # the reason the alternative is worse in both directions: a
        # `continuity_read` purpose would map one-to-three and separate nothing
        # any authority in this build can act on (under `P00-OD-010` there is one
        # local Principal), while reusing `KNOWLEDGE_READ` would be the
        # escalation `purpose.py` refuses — that purpose is the *extraction*
        # plane's and is scoped by enrollment, and continuity belongs to none.
        Capability.CONTINUITY_PULSE: frozenset({Purpose.CAPTURE_REVIEW}),
        Capability.CONTINUITY_SITUATIONS: frozenset({Purpose.CAPTURE_REVIEW}),
        Capability.CONTINUITY_PROJECTS: frozenset({Purpose.CAPTURE_REVIEW}),
        NativeSourceCapability.DISCOVER: frozenset({Purpose.SOURCE_INSPECTION}),
        NativeSourceCapability.CONFIGURE: frozenset({Purpose.BOUNDED_ENROLLMENT}),
        NativeSourceCapability.PREFLIGHT: frozenset({Purpose.SECURITY_VALIDATION}),
        NativeSourceCapability.SYNC: frozenset({Purpose.CONTENT_EXTRACTION}),
        NativeSourceCapability.STATUS: frozenset({Purpose.STATUS_OBSERVATION}),
        NativeSourceCapability.RETRY: frozenset({Purpose.CONTENT_EXTRACTION}),
        NativeSourceCapability.RECONCILE: frozenset({Purpose.CONTENT_EXTRACTION}),
        NativeSourceCapability.PAUSE: frozenset({Purpose.BOUNDED_ENROLLMENT}),
        NativeSourceCapability.RESUME: frozenset({Purpose.CONTENT_EXTRACTION}),
        NativeSourceCapability.BACKFILL: frozenset({Purpose.CONTENT_EXTRACTION}),
        NativeSourceCapability.DISABLE: frozenset({Purpose.BOUNDED_ENROLLMENT}),
    }
)


def is_operator_only(capability: AuthorizedCapability) -> bool:
    """Return whether `capability` requires an authenticated operator."""
    return capability in _OPERATOR_ONLY


def permitted_purposes(capability: AuthorizedCapability) -> frozenset[Purpose]:
    """Return the purposes that may invoke `capability`.

    An unmapped capability yields the empty set, so policy denies it.
    """
    return _PERMITTED_PURPOSES.get(capability, frozenset())
