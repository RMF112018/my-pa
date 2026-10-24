"""Closed server-owned MCP connection profiles and reviewed capability ceilings."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from my_pa.domain.identity.operation import Capability


class McpDatabaseProfile(StrEnum):
    READ_ONLY = "ro"
    READ_WRITE = "rw"


MCP_PROFILE_READ_CAPABILITIES: Final = frozenset(
    {
        Capability.CAPABILITIES_GET,
        Capability.SOURCES_LIST,
        Capability.SOURCES_METADATA,
        Capability.SOURCES_STATUS,
        Capability.KNOWLEDGE_SEARCH,
        Capability.KNOWLEDGE_READ,
        Capability.KNOWLEDGE_COVERAGE,
        Capability.CAPTURE_READ,
        Capability.CAPTURE_LIST,
        Capability.CAPTURE_SEARCH,
        Capability.TASKS_READ,
        Capability.TASKS_LIST,
        Capability.TASKS_SEARCH,
        Capability.TASKS_HISTORY,
        Capability.TASKS_COMMENTS_LIST,
        Capability.COMMITMENTS_READ,
        Capability.COMMITMENTS_LIST,
        Capability.COMMITMENTS_SEARCH,
        Capability.COMMITMENTS_HISTORY,
        Capability.COMMITMENTS_WAITING_ON,
        Capability.CANVAS_WORKSPACE_GET,
        Capability.REPORTS_READ,
        Capability.REPORTS_LATEST,
        Capability.REPORTS_LIST,
        Capability.REPORTS_SEARCH,
        Capability.REPORTS_TYPES_LIST,
    }
)
# This handler persists only its Principal-scoped overlay and stages no feed.
# All feed/report/source/auth/control writes remain unavailable.
MCP_PROFILE_WRITE_CAPABILITIES: Final = frozenset({Capability.CANVAS_WORKSPACE_PUT})


# Preserve explicitly configured transport protections; never inherit connection
# identity, service-file, host, database or role-setting overrides from URL query.
MCP_DATABASE_TRANSPORT_QUERY_KEYS: Final = frozenset(
    {
        "sslmode",
        "sslrootcert",
        "sslcrl",
        "sslcrldir",
        "channel_binding",
        "gssencmode",
        "connect_timeout",
    }
)


def profile_capabilities(profile: McpDatabaseProfile) -> frozenset[str]:
    allowed = MCP_PROFILE_READ_CAPABILITIES
    if profile is McpDatabaseProfile.READ_WRITE:
        allowed = allowed | MCP_PROFILE_WRITE_CAPABILITIES
    return frozenset(capability.value for capability in allowed)
