"""Closed vocabularies of Program reporting (record lineage S4 contract section 3).

Program answers are not lineage reads, so these sets live here and
`domain.lineage.vocabulary` is unchanged (S4 contract section 12, D-13). The
one database value among them -- `ProgramVerificationState`, the manifest's
`program_verification_state` column -- is restated by the S4 revision as a
frozen literal; the revision imports nothing from here.

Pure data: this module persists nothing and grants nothing.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final

__all__ = [
    "MAX_MEMBER_EDGES",
    "MAX_PROGRAMS_PER_REQUEST",
    "MAX_PROGRAM_PROJECTS",
    "MAX_PROJECT_FILTER",
    "MAX_REDIRECT_HOPS",
    "PROGRAM_CALCULATION_VERSION",
    "PROGRAM_COMPLETENESS_PRECEDENCE",
    "PROGRAM_FAMILY_READS",
    "PROGRAM_METRIC_SCHEMA_VERSION",
    "PROGRAM_OVERVIEW_FAMILIES",
    "PROGRAM_READ_CAPABILITIES",
    "PROGRAM_REFERENCE_BLOCK_KEY",
    "PROGRAM_REPORTING_CAPABILITIES",
    "PROGRAM_REPORTING_PURPOSE",
    "REPORT_MANIFEST_SCHEMA_VERSION",
    "AcceptanceVerification",
    "CandidateStatus",
    "ConstraintSourceState",
    "ManifestState",
    "MemberUnresolvedReason",
    "MemberUnverifiedReason",
    "MembershipMode",
    "MetricGrain",
    "MetricValueState",
    "NotReportableReason",
    "ProgramCompleteness",
    "ProgramFamily",
    "ProgramVerificationState",
    "RecomputeFailure",
    "ReferenceState",
]

#: Section 3.2: the version of the metric catalogue an overview reports.
PROGRAM_METRIC_SCHEMA_VERSION: Final = 1
#: Section 3.2: the version of the overview calculation (and its digest prefix).
PROGRAM_CALCULATION_VERSION: Final = "program-overview-v1"
#: Section 7: at most 10 distinct Program Entities per request.
MAX_PROGRAMS_PER_REQUEST: Final = 10
#: Section 3.1 step 6: at most 100 distinct Projects over one request.
MAX_PROGRAM_PROJECTS: Final = 100
#: Section 3.1 step 2: at most 400 member edges scanned per request.
MAX_MEMBER_EDGES: Final = 400
#: Section 3.1 step 1: a redirect chain longer than 8 hops is a conflict.
MAX_REDIRECT_HOPS: Final = 8
#: Section 7.3: a `commitments.v2.*` `project_ids` filter names 1..100 Projects.
MAX_PROJECT_FILTER: Final = 100
#: Section 5.3: the version of the report manifest's canonical shape.
REPORT_MANIFEST_SCHEMA_VERSION: Final = 1
#: Section 5.4: the reserved top-level `structured_content` key of a Program
#: reference block.
PROGRAM_REFERENCE_BLOCK_KEY: Final = "program_overview_ref"

#: Section 7: the 7 S4 capability names, as strings (the identity registry
#: declares them as `Capability` members). Withheld unless both
#: `MY_PA_LINEAGE_ENABLED` and `MY_PA_PROGRAM_REPORTING_ENABLED` are on.
PROGRAM_REPORTING_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "programs.members.resolve",
        "programs.overview",
        "commitments.v2.read",
        "commitments.v2.list",
        "commitments.v2.search",
        "commitments.v2.waiting_on",
        "reports.manifest",
    }
)
#: Section 7.6: the 2 Program reads, which also need the Entity plane and the
#: Program read factory (and the overview the Constraint plane).
PROGRAM_READ_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {"programs.members.resolve", "programs.overview"}
)
#: Section 7: the one S4 purpose, used by exactly the 2 Program reads.
PROGRAM_REPORTING_PURPOSE: Final = "program_reporting_read"


class MembershipMode(StrEnum):
    """Section 3.1: current membership, or membership at a stated `valid_at`."""

    CURRENT = "current"
    HISTORICAL = "historical"


class MemberUnresolvedReason(StrEnum):
    """Section 3.1 steps 4 and 5: why a member edge names no exact Project."""

    BRIDGE_MISSING = "bridge_missing"
    BRIDGE_AMBIGUOUS = "bridge_ambiguous"
    REDIRECT_UNRESOLVABLE = "redirect_unresolvable"


class MemberUnverifiedReason(StrEnum):
    """Section 3.1 step 3: why a historical member cannot be proven at `valid_at`."""

    START_NOT_RECORDED = "start_not_recorded"
    END_NOT_RECORDED = "end_not_recorded"


class ProgramCompleteness(StrEnum):
    """Section 3: one `complete_state` per Program answer, by the precedence below."""

    COMPLETE = "complete"
    HISTORICAL_MEMBERSHIP_UNVERIFIED = "historical_membership_unverified"
    MEMBERSHIP_UNRESOLVED = "membership_unresolved"
    TRUNCATED_BUDGET = "truncated_budget"
    RESTRICTED_EVIDENCE = "restricted_evidence"


#: Section 3 (S3 D-36): `qualifiers[0]` is the `complete_state`, the first
#: applicable code of this order.
PROGRAM_COMPLETENESS_PRECEDENCE: Final[tuple[ProgramCompleteness, ...]] = (
    ProgramCompleteness.TRUNCATED_BUDGET,
    ProgramCompleteness.MEMBERSHIP_UNRESOLVED,
    ProgramCompleteness.HISTORICAL_MEMBERSHIP_UNVERIFIED,
    ProgramCompleteness.RESTRICTED_EVIDENCE,
    ProgramCompleteness.COMPLETE,
)


class MetricGrain(StrEnum):
    """Section 3.2: the identifier a metric counts distinct values of."""

    COMMITMENT = "commitment"
    ISSUE = "issue"
    CONSTRAINT = "constraint"


class MetricValueState(StrEnum):
    """Section 3.3: whether a metric value is a reported count."""

    REPORTED = "reported"
    NOT_REPORTABLE = "not_reportable"
    RESTRICTED = "restricted"


class NotReportableReason(StrEnum):
    """Section 3.3: every reason a Program or portfolio total is not reported."""

    MEMBERSHIP_UNRESOLVED = "membership_unresolved"
    MEMBERSHIP_TRUNCATED = "membership_truncated"
    ACCEPTANCE_UNVERIFIED = "acceptance_unverified"
    ISSUE_LINK_UNVERIFIED = "issue_link_unverified"
    CALENDAR_UNCONFIGURED = "calendar_unconfigured"
    NEVER_SYNCED = "never_synced"
    SYNC_UNVERIFIED = "sync_unverified"
    SYNC_DEGRADED = "sync_degraded"
    SYNC_CONFLICT = "sync_conflict"


class ConstraintSourceState(StrEnum):
    """Section 3.3: a Project's Constraint source state, from its stored sync data."""

    IN_SYNC = "in_sync"
    NEVER_SYNCED = "never_synced"
    UNVERIFIED = "unverified"
    SYNC_DEGRADED = "sync_degraded"
    CONFLICT = "conflict"
    CALENDAR_UNCONFIGURED = "calendar_unconfigured"


class AcceptanceVerification(StrEnum):
    """Sections 3.3 and 7.3: native acceptance is never a verified acceptance in S4."""

    UNVERIFIED_REVIEW_REFERENCE = "unverified_review_reference"
    NOT_ACCEPTED = "not_accepted"


class ReferenceState(StrEnum):
    """Section 7.3: how a v2 Commitment view shows a stored Project or Situation id."""

    OWNED = "owned"
    NONE = "none"
    NOT_OWNED = "not_owned"
    RESTRICTED = "restricted"


class ProgramVerificationState(StrEnum):
    """Sections 4.1 and 7.4: what the commit-time recompute of a Program reference found."""

    VERIFIED_AT_COMMIT = "verified_at_commit"
    CHANGED_SINCE_READ = "changed_since_read"
    RECOMPUTE_FAILED = "recompute_failed"
    NOT_ATTEMPTED = "not_attempted"


class RecomputeFailure(StrEnum):
    """Section 7.4: why a commit-time recompute recorded `recompute_failed`."""

    BUDGET_EXCEEDED = "budget_exceeded"
    STATEMENT_TIMEOUT = "statement_timeout"
    POOL_UNAVAILABLE = "pool_unavailable"
    PROGRAM_NOT_FOUND = "program_not_found"
    PROGRAM_INVALID = "program_invalid"


class ManifestState(StrEnum):
    """Section 7.4: what `reports.manifest` answers about one artifact."""

    RECORDED = "recorded"
    MANIFEST_UNAVAILABLE_LEGACY = "manifest_unavailable_legacy"
    RESTRICTED_EVIDENCE = "restricted_evidence"


class CandidateStatus(StrEnum):
    """Section 5.3: a collector artifact is an unaccepted candidate; nothing else is one."""

    UNACCEPTED_CANDIDATE = "unaccepted_candidate"
    NOT_A_CANDIDATE = "not_a_candidate"


class ProgramFamily(StrEnum):
    """Section 6.2: the record families a remote Program reader may or may not see."""

    ENTITY = "entity"
    PROJECT = "project"
    SITUATION = "situation"
    COMMITMENT = "commitment"
    ISSUE = "issue"
    CONSTRAINT = "constraint"


#: Section 6.2: a remote caller sees a family only while it holds a grant, for
#: one of its purposes, on one of the family's reads (capability names).
PROGRAM_FAMILY_READS: Final = MappingProxyType(
    {
        ProgramFamily.ENTITY: frozenset({"entities.get", "entities.search"}),
        ProgramFamily.PROJECT: frozenset({"continuity.projects", "continuity.projects.read"}),
        ProgramFamily.SITUATION: frozenset({"continuity.situations"}),
        ProgramFamily.COMMITMENT: frozenset({"commitments.read", "commitments.list"}),
        ProgramFamily.ISSUE: frozenset({"issues.read", "issues.list"}),
        ProgramFamily.CONSTRAINT: frozenset({"constraints.read", "constraints.list"}),
    }
)

#: Section 5.3 (R4-F23): the 5 families an overview field derives from; a
#: manifest's `families_seen` is a subset of these, never `situation`.
PROGRAM_OVERVIEW_FAMILIES: Final[frozenset[ProgramFamily]] = frozenset(
    {
        ProgramFamily.ENTITY,
        ProgramFamily.PROJECT,
        ProgramFamily.COMMITMENT,
        ProgramFamily.ISSUE,
        ProgramFamily.CONSTRAINT,
    }
)
