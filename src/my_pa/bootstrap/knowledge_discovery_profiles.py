"""Knowledge client profiles and the one deny overlay (KLP-WP-04, R6 section 3.4).

Three kinds of remote OAuth client reach the Knowledge plane, and the Settings
allowlists -- not grant rows -- say which kind a client is:

* a **discovery** client (`MY_PA_KNOWLEDGE_DISCOVERY_OAUTH_CLIENT_IDS`) sees
  exactly its discovery profile, `knowledge-discovery-v2` since KLP-WP-05:
  submit, checkpoint, `knowledge.assertions.read`, `record_events.list` and
  `record_events.provenance`, intersected with what it was granted;
* an **operator-review** client (`MY_PA_KNOWLEDGE_OPERATOR_REVIEW_OAUTH_CLIENT_IDS`)
  sees exactly `knowledge-operator-review-v1`;
* every **unbound** client keeps its grants minus submit and checkpoint.

`resolve_knowledge_client_overlay` is the single resolver for both outputs the
gateway passes on -- the capability set *and* the purpose-bearing grant set --
so purpose-driven visibility (`record_events.visible_families`, the Review
Knowledge-read predicate) follows the overlay too. It is applied even when grant
rows conflict with it: a stray `tasks.read` or `knowledge.assertions.create`
grant on a discovery client is simply not in the overlaid output.

The allowlist fingerprint is what profile and grant tooling prints and what the
gateway's runtime attestation will be compared with (WP-13): sha256 over the
canonical JSON of the three sorted allowlists.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Protocol

from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose

__all__ = [
    "DISCOVERY_PROFILE",
    "DISCOVERY_PROFILES",
    "KNOWLEDGE_CLIENT_PROFILES",
    "KNOWLEDGE_DISCOVERY_ONLY_CAPABILITIES",
    "KNOWLEDGE_DISCOVERY_V1",
    "KNOWLEDGE_DISCOVERY_V2",
    "KNOWLEDGE_OPERATOR_REVIEW_V1",
    "OPERATOR_REVIEW_PROFILE",
    "KnowledgeAllowlists",
    "KnowledgeClientRole",
    "allowlist_fingerprint",
    "knowledge_allowlists",
    "knowledge_client_role",
    "profile_for_role",
    "resolve_knowledge_client_overlay",
]

#: The KLP-WP-04 profile, kept as history (matrix `profile_contract` lists both);
#: no client is bound to it any more.
KNOWLEDGE_DISCOVERY_V1: Final = "knowledge-discovery-v1"
#: KLP-WP-05 (WP-04 DEV-02 closed): v1 plus `record_events.provenance`, which a
#: discovery client needs to tell its own effect from a new trigger.
KNOWLEDGE_DISCOVERY_V2: Final = "knowledge-discovery-v2"
KNOWLEDGE_OPERATOR_REVIEW_V1: Final = "knowledge-operator-review-v1"

#: The discovery pair: only a bound discovery client may ever hold either.
KNOWLEDGE_DISCOVERY_ONLY_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {Capability.KNOWLEDGE_ASSERTIONS_SUBMIT, Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT}
)
#: What a discovery client never holds, whatever its grants say (KLP-AC-040).
_NEVER_FOR_DISCOVERY: Final[frozenset[Capability]] = frozenset(
    {Capability.KNOWLEDGE_ASSERTIONS_CREATE, Capability.REVIEW_DECIDE}
)

DISCOVERY_PROFILES: Final[Mapping[str, frozenset[Capability]]] = MappingProxyType(
    {
        KNOWLEDGE_DISCOVERY_V1: frozenset(
            {
                Capability.KNOWLEDGE_ASSERTIONS_SUBMIT,
                Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT,
                Capability.KNOWLEDGE_ASSERTIONS_READ,
                Capability.RECORD_EVENTS_LIST,
            }
        ),
        KNOWLEDGE_DISCOVERY_V2: frozenset(
            {
                Capability.KNOWLEDGE_ASSERTIONS_SUBMIT,
                Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT,
                Capability.KNOWLEDGE_ASSERTIONS_READ,
                Capability.RECORD_EVENTS_LIST,
                Capability.RECORD_EVENTS_PROVENANCE,
            }
        ),
    }
)
#: The discovery profile this build binds every discovery client to.
DISCOVERY_PROFILE: Final = KNOWLEDGE_DISCOVERY_V2
OPERATOR_REVIEW_PROFILE: Final = KNOWLEDGE_OPERATOR_REVIEW_V1

KNOWLEDGE_CLIENT_PROFILES: Final[Mapping[str, frozenset[Capability]]] = MappingProxyType(
    {
        **DISCOVERY_PROFILES,
        KNOWLEDGE_OPERATOR_REVIEW_V1: frozenset(
            {
                Capability.REVIEW_LIST,
                Capability.REVIEW_DECIDE,
                Capability.KNOWLEDGE_ASSERTIONS_READ,
            }
        ),
    }
)

# A discovery profile can never name what a discovery client must never hold.
if any(profile & _NEVER_FOR_DISCOVERY for profile in DISCOVERY_PROFILES.values()):
    raise RuntimeError("a Knowledge discovery profile names create or review.decide")


class _AllowlistSettings(Protocol):
    def knowledge_discovery_oauth_client_id_set(self) -> frozenset[str]: ...

    def knowledge_operator_review_oauth_client_id_set(self) -> frozenset[str]: ...

    def chatllm_gateway_oauth_client_id_set(self) -> frozenset[str]: ...


@dataclass(frozen=True, slots=True)
class KnowledgeAllowlists:
    """The three exact role allowlists one evaluation read."""

    discovery: frozenset[str]
    operator_review: frozenset[str]
    chatllm_gateway: frozenset[str]


def knowledge_allowlists(settings: _AllowlistSettings) -> KnowledgeAllowlists:
    """Read the three allowlists once, so one decision never mixes two readings."""
    return KnowledgeAllowlists(
        discovery=settings.knowledge_discovery_oauth_client_id_set(),
        operator_review=settings.knowledge_operator_review_oauth_client_id_set(),
        chatllm_gateway=settings.chatllm_gateway_oauth_client_id_set(),
    )


def allowlist_fingerprint(allowlists: KnowledgeAllowlists) -> str:
    """sha256 hex over the canonical JSON of the three sorted allowlists."""
    document = {
        "chatllm_gateway": sorted(allowlists.chatllm_gateway),
        "knowledge_discovery": sorted(allowlists.discovery),
        "knowledge_operator_review": sorted(allowlists.operator_review),
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class KnowledgeClientRole:
    """The closed set of roles an OAuth client can have for the Knowledge plane."""

    DISCOVERY: Final = "discovery"
    OPERATOR_REVIEW: Final = "operator_review"
    UNBOUND: Final = "unbound"


def knowledge_client_role(allowlists: KnowledgeAllowlists, client_id: str | None) -> str:
    """Which role `client_id` has. Exact membership only; no client is unbound.

    `Settings._check` refuses overlapping allowlists, so at most one matches. A
    hand-built overlap still fails closed: discovery is checked first because its
    profile is the narrowest that grants no Review decision.
    """
    if client_id is not None and client_id in allowlists.discovery:
        return KnowledgeClientRole.DISCOVERY
    if client_id is not None and client_id in allowlists.operator_review:
        return KnowledgeClientRole.OPERATOR_REVIEW
    return KnowledgeClientRole.UNBOUND


def profile_for_role(role: str) -> str | None:
    """The exact profile name a bound role is overlaid with, or `None` when unbound."""
    if role == KnowledgeClientRole.DISCOVERY:
        return DISCOVERY_PROFILE
    if role == KnowledgeClientRole.OPERATOR_REVIEW:
        return OPERATOR_REVIEW_PROFILE
    return None


def resolve_knowledge_client_overlay(
    settings: _AllowlistSettings,
    client_id: str | None,
    capabilities: frozenset[Capability],
    capability_purposes: frozenset[tuple[Capability, Purpose | None]],
) -> tuple[frozenset[Capability], frozenset[tuple[Capability, Purpose | None]]]:
    """The overlaid `(capabilities, capability_purposes)` pair for one client.

    * discovery-bound -> intersected with its exact discovery profile, and never
      `knowledge.assertions.create` or `review.decide`;
    * operator-review-bound -> intersected with `knowledge-operator-review-v1`;
    * unbound -> submit and checkpoint removed.

    Both outputs are filtered by the same allowed set, so a grant pair can never
    survive for a capability the overlay removed.
    """
    allowlists = knowledge_allowlists(settings)
    profile = profile_for_role(knowledge_client_role(allowlists, client_id))
    if profile is None:
        allowed = frozenset(capabilities) - KNOWLEDGE_DISCOVERY_ONLY_CAPABILITIES
    else:
        allowed = frozenset(capabilities) & KNOWLEDGE_CLIENT_PROFILES[profile]
        if profile in DISCOVERY_PROFILES:
            allowed -= _NEVER_FOR_DISCOVERY
    purposes = frozenset(pair for pair in capability_purposes if pair[0] in allowed)
    return allowed, purposes
