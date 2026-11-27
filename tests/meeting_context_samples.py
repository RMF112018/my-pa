"""Synthetic sample payloads for `meetings.context.read` (WP5-S5).

The transport-parity, negative-evidence and policy suites keep one valid
payload per handler-backed capability. Every id here is synthetic; the payload
passes the command's own validation (WP5 design section 3.1), so a transport
reaches authorization and the communications switch's composition check (off
in those worlds: the name is withheld with the 3 `communications.*` reads,
ruling D2).
"""

from __future__ import annotations

from typing import Any, Final

from my_pa.application.commands import ReadMeetingContext
from my_pa.domain.identity.operation import Capability

__all__ = [
    "MEETING_CONTEXT_CAPABILITIES",
    "meeting_context_commands",
    "meeting_context_payloads",
]

#: The one read, withheld unless `MY_PA_COMMUNICATIONS_ENABLED` is on.
MEETING_CONTEXT_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {Capability.MEETINGS_CONTEXT_READ}
)


def meeting_context_payloads(tag: str) -> dict[Capability, dict[str, Any]]:
    """One valid payload; `tag` (alphanumeric) marks the suite."""
    return {
        Capability.MEETINGS_CONTEXT_READ: {
            "meeting_ids": [f"mtg_{tag}context0001"],
            "lookback_days": 7,
            "per_meeting_limit": 5,
        },
    }


def meeting_context_commands(tag: str) -> dict[Capability, Any]:
    """The same sample as a built command."""
    return {
        Capability.MEETINGS_CONTEXT_READ: ReadMeetingContext(
            meeting_ids=(f"mtg_{tag}context0001",), lookback_days=7, per_meeting_limit=5
        ),
    }
