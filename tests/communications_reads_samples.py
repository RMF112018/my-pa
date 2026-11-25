"""Synthetic sample payloads for the 3 communications reads (WP4-S5).

The transport-parity, negative-evidence and policy suites keep one valid
payload per handler-backed capability. Every id, query and instant here is
synthetic; each payload passes its command's own validation (communications
contract section 16), so a transport reaches authorization and the read
switch's composition check (off in those worlds).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

from my_pa.application.commands import (
    CommunicationsCoverage,
    ReadCommunications,
    SearchCommunications,
)
from my_pa.domain.identity.operation import Capability

__all__ = [
    "COMMUNICATIONS_READ_CAPABILITIES",
    "communications_commands",
    "communications_payloads",
]

#: The 3 reads, each withheld unless `MY_PA_COMMUNICATIONS_ENABLED` is on.
COMMUNICATIONS_READ_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.COMMUNICATIONS_SEARCH,
        Capability.COMMUNICATIONS_READ,
        Capability.COMMUNICATIONS_COVERAGE,
    }
)

_FROM: Final = datetime(2026, 11, 1, tzinfo=UTC)
_TO: Final = datetime(2026, 11, 20, tzinfo=UTC)


def communications_payloads(tag: str) -> dict[Capability, dict[str, Any]]:
    """One valid payload per read; `tag` (alphanumeric) marks the suite."""
    return {
        Capability.COMMUNICATIONS_SEARCH: {"query": f"synthetic {tag}", "limit": 5},
        Capability.COMMUNICATIONS_READ: {"message_ids": [f"cmsg_{tag}message0001"]},
        Capability.COMMUNICATIONS_COVERAGE: {
            "from_utc": "2026-11-01T00:00:00Z",
            "to_utc": "2026-11-20T00:00:00Z",
        },
    }


def communications_commands(tag: str) -> dict[Capability, Any]:
    """The same samples as built commands."""
    return {
        Capability.COMMUNICATIONS_SEARCH: SearchCommunications(query=f"synthetic {tag}", limit=5),
        Capability.COMMUNICATIONS_READ: ReadCommunications(message_ids=(f"cmsg_{tag}message0001",)),
        Capability.COMMUNICATIONS_COVERAGE: CommunicationsCoverage(from_utc=_FROM, to_utc=_TO),
    }
