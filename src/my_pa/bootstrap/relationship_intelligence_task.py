"""Dormant Relationship Intelligence Task profile.

Repository-side contract for a proposed regular intelligence Task. This module
does not create, edit, enable, or disable a live Abacus or ChatLLM Task, does
not call any provider API, and sends no network traffic anywhere. It states
which capabilities such a Task *would* be allowed, so the answer exists in the
repository before anyone is in a position to grant it.

**This named Task profile is the standard read-only ceiling.** A Task may search,
read, resolve, assemble a context card, and walk one entity's edges. It may not
read the unresolved-mention queue, which the plane serves and this profile
deliberately withholds — see `ALLOWED_CAPABILITIES`. It may not
observe, propose, decide, or merge. Those capabilities now exist behind their
own feature gates and immutable producer/reviewer/operator profiles, but remain
absent from this standard profile. The named local and remote ceilings live in
`relationship_intelligence_profiles`; declaring them activates no grant.
Specification section 21.4 forbids a model creating a canonical person or
merging identities autonomously, and `RI-AC-039` says the same; a profile that
allowed a write would be the sentence in this repository that contradicted them.

**Two gates, and they are different questions.**
`MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` decides whether this *build* serves
the entity capabilities at all. This profile decides which of the served ones a
Task may reach. A Task cannot reach what the build does not publish, so
`mcp_profile_refuses` checks both — the published set and the profile — and an
unpublished name is refused before it reaches `ApplicationService.invoke`.

**Nothing here activates anything.** The status is `DRAFT_NOT_ACTIVATED` and
stays so: activating a live Task is an operator act, reserved by `AGENTS.md`
section 8.2, and out of scope for this campaign by explicit instruction.
"""

from __future__ import annotations

from typing import Final

from my_pa.bootstrap.settings import Settings
from my_pa.domain.identity.operation import Capability

__all__ = [
    "ALLOWED_CAPABILITIES",
    "DRAFT_STATUS",
    "TASK_NAME",
    "activated_task_capabilities",
    "mcp_profile_refuses",
    "profile_tool_names",
    "relationship_task_is_activated",
]

TASK_NAME: Final = "Relationship Intelligence"
DRAFT_STATUS: Final = "DRAFT_NOT_ACTIVATED"

#: Every capability the proposed Task may call. All five are reads, and the
#: plane serves six.
#:
#: Written out rather than derived from the `entities.` prefix, for the reason
#: `application.service._ENTITY_CAPABILITIES` is: admitting another has to be a
#: decision here and not a spelling that happens to start the right way. If a
#: write capability is ever added to the plane, this set does not grow with it.
#:
#: **`entities.unresolved_mentions` is deliberately excluded**, decided when it
#: was added rather than left as an omission the hand-written set would hide.
#: The proposed Task's job is attaching canonical entity IDs to intelligence
#: output — it asks "who is this reference", which is `resolve`. The queue of
#: references *nobody* could place is a human review surface: it exists to be
#: worked, working it is a governed write, and no transport publishes one. A
#: grant to read it would let a Task enumerate every mention the system failed
#: to resolve while being unable to act on any of them, which is reach without
#: purpose. Least privilege, and revisit it if a Task is ever given a reason.
ALLOWED_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.ENTITIES_SEARCH,
        Capability.ENTITIES_GET,
        Capability.ENTITIES_RESOLVE,
        Capability.ENTITIES_CONTEXT,
        Capability.ENTITIES_RELATIONSHIPS,
    }
)


def profile_tool_names() -> frozenset[str]:
    """The proposed Task allowlist, independent of process activation."""
    return frozenset(capability.value for capability in ALLOWED_CAPABILITIES)


def relationship_task_is_activated(settings: Settings) -> bool:
    """Process-local gate. True does not create or enable a live Task."""
    return settings.relationship_intelligence_enabled


def activated_task_capabilities(settings: Settings) -> frozenset[Capability]:
    """Capabilities this process would grant the Task.

    Empty while the gate is off, so an unconfigured process does not treat the
    draft profile as live. The proposed allowlist remains
    `ALLOWED_CAPABILITIES` either way — what the gate changes is whether this
    build would honour it, not what it says.
    """
    if not relationship_task_is_activated(settings):
        return frozenset()
    return ALLOWED_CAPABILITIES


def mcp_profile_refuses(tool_name: str, *, published: frozenset[str]) -> bool:
    """Refuse before invoke when the tool is unpublished or outside the profile.

    Both halves, in that order. A build that has not enabled the plane publishes
    none of these names, so every one of them is refused on the first check —
    which means the profile cannot be the thing that accidentally opens a
    surface the build meant to withhold.
    """
    return tool_name not in published or tool_name not in profile_tool_names()
