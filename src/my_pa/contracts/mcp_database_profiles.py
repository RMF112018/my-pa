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

# Record lineage S3.1 (S3.1 contract section 7.11): the closed, code-owned names
# an operator may opt in to the restricted profiles, never a default ceiling
# member. With no opt-in -- the default -- both ceilings are exactly the sets
# above. An opt-in never issues a grant: a profile client still reaches only
# what its own durable grants name. Never admissible: `issues.close`,
# `issues.reopen` and the 3 confirms (attested; a profile client is never the
# human channel), `records.backfill.*` (operator-only), the 2 Program reads (a
# profile composition builds no Program read engine, S4 D-46) and
# `reports.manifest` (its `intelligence_` table cannot be granted to an MCP
# role, R31-F04). No privilege mechanism exists yet for the existing lineage
# tables, so an opted-in lineage call on a profile service fails closed.
MCP_PROFILE_OPT_IN_READ_CAPABILITIES: Final = frozenset(
    {
        Capability.RECORDS_LINEAGE,
        Capability.RECORDS_LINEAGE_RELATED,
        Capability.RECORDS_ASSOCIATIONS_HISTORY,
        Capability.ISSUES_READ,
        Capability.ISSUES_LIST,
        Capability.ISSUES_HISTORY,
        Capability.ISSUES_TIMELINE,
        Capability.ISSUES_HANDOFFS_LIST,
        Capability.ISSUES_CLOSURE_READINESS,
        Capability.MEETINGS_NOTES_VERSIONS,
        Capability.MEETINGS_NOTES_READ_VERSION,
        Capability.COMMITMENTS_V2_READ,
        Capability.COMMITMENTS_V2_LIST,
        Capability.COMMITMENTS_V2_SEARCH,
        Capability.COMMITMENTS_V2_WAITING_ON,
    }
)
MCP_PROFILE_OPT_IN_WRITE_CAPABILITIES: Final = frozenset(
    {
        Capability.RECORDS_ASSOCIATIONS_ASSERT,
        Capability.RECORDS_ASSOCIATIONS_CORRECT,
        Capability.RECORDS_ASSOCIATIONS_END,
        Capability.RECORDS_ASSOCIATIONS_CONTEST,
        Capability.RECORDS_ASSOCIATIONS_REINSTATE,
        Capability.ISSUES_MEMBERSHIPS_ADD,
        Capability.ISSUES_MEMBERSHIPS_END,
        Capability.ISSUES_MEMBERSHIPS_CORRECT,
        Capability.ISSUES_PROJECT_LINKS_ADD,
        Capability.ISSUES_PROJECT_LINKS_END,
        Capability.ISSUES_HANDOFFS_RECORD,
        Capability.ISSUES_HANDOFFS_CORRECT,
        Capability.ISSUES_WORK_CREATE_TASK,
        Capability.ISSUES_WORK_CREATE_COMMITMENT,
        Capability.ISSUES_CREATE,
        Capability.ISSUES_UPDATE,
    }
)
#: Every name `MY_PA_MCP_DATABASE_PROFILE_OPT_INS` may carry.
MCP_PROFILE_OPT_IN_CAPABILITY_NAMES: Final = frozenset(
    capability.value
    for capability in MCP_PROFILE_OPT_IN_READ_CAPABILITIES | MCP_PROFILE_OPT_IN_WRITE_CAPABILITIES
)


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


def opted_in_write_capabilities(opt_ins: frozenset[str] = frozenset()) -> frozenset[Capability]:
    """The opted-in write names (S3.1 section 7.11); a name outside the set adds nothing."""
    return frozenset(
        capability
        for capability in MCP_PROFILE_OPT_IN_WRITE_CAPABILITIES
        if capability.value in opt_ins
    )


def profile_capabilities(
    profile: McpDatabaseProfile, opt_ins: frozenset[str] = frozenset()
) -> frozenset[str]:
    """A profile's ceiling: the reviewed set, plus the opted-in names it admits.

    S3.1 section 7.11: opted-in read names reach both profiles, opted-in write
    names `rw` only; with no opt-in the ceiling is byte-identical to #339.
    """
    allowed = MCP_PROFILE_READ_CAPABILITIES | frozenset(
        capability
        for capability in MCP_PROFILE_OPT_IN_READ_CAPABILITIES
        if capability.value in opt_ins
    )
    if profile is McpDatabaseProfile.READ_WRITE:
        allowed = allowed | MCP_PROFILE_WRITE_CAPABILITIES | opted_in_write_capabilities(opt_ins)
    return frozenset(capability.value for capability in allowed)
