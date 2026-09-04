"""Dormant GoodNotes Durable Note Intelligence Task profile.

Repository-side contract for a proposed regular Abacus Agent Task. This module
does not create, edit, enable, or disable a live Abacus Task, does not call
Abacus APIs, and does not send network to abacus.ai.

The Task, if an operator later activates it, may call only the existing GN-04
MCP tools `goodnotes.work`, `goodnotes.content`, and `goodnotes.propose`. It
analyzes immutable page-version content/context, returns schema-valid proposals,
and has no direct database, source, or destination writes. Canonical NEW-only
summary delivery is GN-06, not this Task. Fail closed when MCP, auth, or
content transfer fails: do not submit a proposal.

`MY_PA_GOODNOTES_DURABLE_NOTE_INTELLIGENCE_ENABLED` is a process-local gate
defaulting to off. True does not activate Abacus. Bounded GoodNotes OCR/review
composition in `bootstrap.goodnotes` does not read the flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from my_pa.application.goodnotes_orchestrator import GoodNotesDurableNoteOrchestrator
from my_pa.bootstrap.goodnotes_rollout import current_rollout_stage
from my_pa.bootstrap.settings import Settings
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose

__all__ = [
    "ALLOWED_CAPABILITIES",
    "DRAFT_STATUS",
    "TASK_NAME",
    "GoodNotesCapabilityStates",
    "activated_task_capabilities",
    "capability_states",
    "compose_durable_note_orchestrator",
    "durable_note_task_is_activated",
    "mcp_profile_refuses",
    "profile_tool_names",
]

TASK_NAME: Final = "GoodNotes Durable Note Intelligence"
DRAFT_STATUS: Final = "DRAFT_NOT_ACTIVATED"
ALLOWED_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.GOODNOTES_WORK,
        Capability.GOODNOTES_CONTENT,
        Capability.GOODNOTES_PROPOSE,
    }
)


@dataclass(frozen=True, slots=True)
class GoodNotesCapabilityStates:
    """The four independent boundaries between a draft profile and a caller."""

    source_defined: frozenset[Capability]
    composed: frozenset[Capability]
    runtime_published: frozenset[Capability]
    grant_visible: frozenset[Capability]


def profile_tool_names() -> frozenset[str]:
    """The proposed Task allowlist, independent of process activation."""
    return frozenset(capability.value for capability in ALLOWED_CAPABILITIES)


def durable_note_task_is_activated(settings: Settings) -> bool:
    """Process-local gate. True does not create a live Abacus Task."""
    return settings.goodnotes_durable_note_intelligence_enabled


def activated_task_capabilities(settings: Settings) -> frozenset[Capability]:
    """Capabilities this process would grant the Task.

    Empty while the gate is off so an unconfigured process does not treat the
    draft profile as live. The proposed allowlist remains `ALLOWED_CAPABILITIES`.
    """
    if not durable_note_task_is_activated(settings):
        return frozenset()
    return ALLOWED_CAPABILITIES


def capability_states(
    settings: Settings,
    *,
    runtime_published: frozenset[str],
    allowed_tools: frozenset[str],
    grants: frozenset[tuple[Capability, Purpose | None]],
) -> GoodNotesCapabilityStates:
    """Resolve the dormant Task's capability state without activating anything.

    Source definition is not composition, and composition is not publication.
    Publication still grants no caller authority: a name is visible only when
    the caller's tool ceiling and capability/purpose grant both admit it. This
    mirrors the MCP boundary while keeping the proposed Task profile local and
    free of API, model, database, or network I/O.
    """
    source_defined = ALLOWED_CAPABILITIES
    composed = activated_task_capabilities(settings)
    published = frozenset(
        capability for capability in composed if capability.value in runtime_published
    )
    visible = frozenset(
        capability
        for capability in published
        if capability.value in allowed_tools
        and (
            (capability, None) in grants
            or any((capability, purpose) in grants for purpose in permitted_purposes(capability))
        )
    )
    return GoodNotesCapabilityStates(
        source_defined=source_defined,
        composed=composed,
        runtime_published=published,
        grant_visible=visible,
    )


def mcp_profile_refuses(tool_name: str, *, published: frozenset[str]) -> bool:
    """Refuse before invoke when the tool is unpublished or outside the profile.

    Matches the remote MCP `allowed_tools` failure direction: an out-of-profile
    name never reaches `ApplicationService.invoke`, so it cannot write a
    proposal. Live Abacus `tools/list` remains operator-gated.
    """
    return tool_name not in published or tool_name not in profile_tool_names()


def compose_durable_note_orchestrator(
    settings: Settings,
) -> GoodNotesDurableNoteOrchestrator:
    """Dormant composition helper. Not invoked from gateway startup.

    Production persistence is `PostgresDurableNoteStore` on a caller-supplied
    connection. This helper does not open a connection or auto-wire the store.
    The resolved rollout stage is consumed before each effectful step.
    Representing or enabling the optional TBR bridge fails closed here.
    """
    stage = current_rollout_stage(settings)
    return GoodNotesDurableNoteOrchestrator(rollout_stage=stage.value)
