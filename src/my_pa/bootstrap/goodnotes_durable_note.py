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

from typing import Final

from my_pa.application.goodnotes_orchestrator import GoodNotesDurableNoteOrchestrator
from my_pa.bootstrap.settings import Settings
from my_pa.domain.identity.operation import Capability

__all__ = [
    "ALLOWED_CAPABILITIES",
    "DRAFT_STATUS",
    "TASK_NAME",
    "activated_task_capabilities",
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


def mcp_profile_refuses(tool_name: str, *, published: frozenset[str]) -> bool:
    """Refuse before invoke when the tool is unpublished or outside the profile.

    Matches the remote MCP `allowed_tools` failure direction: an out-of-profile
    name never reaches `ApplicationService.invoke`, so it cannot write a
    proposal. Live Abacus `tools/list` remains operator-gated.
    """
    return tool_name not in published or tool_name not in profile_tool_names()


def compose_durable_note_orchestrator() -> GoodNotesDurableNoteOrchestrator:
    """Dormant composition helper. Not invoked from gateway startup.

    Production persistence is `PostgresDurableNoteStore` on a caller-supplied
    connection. This helper does not open a connection or auto-wire the store.
    """
    return GoodNotesDurableNoteOrchestrator()
