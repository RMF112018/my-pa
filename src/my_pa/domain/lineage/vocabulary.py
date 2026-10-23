"""Closed vocabularies of record lineage, Slices S1, S2 and S3 (each contract's section 3).

Each enum here holds exactly what S1 admits, which is also exactly what the S1
database CHECKs admit (`docs/architecture/record-lineage-s1-contract.md`
section 3). The members the contract lists as "specified, admitted later" are
deliberately absent: a later slice widens an enum and its CHECK together, never
one without the other.

The S1 revision (`264310e0416a`) restates every list below as a frozen literal
and imports nothing from here (`D-48`, `D-69`): a schema revision is a fixed
point in history and must not change meaning when Python changes.

Reused rather than redefined: the Issue state is the existing
`domain.situation.situation.SituationState` (S1 admits its three non-terminal
members, `ISSUE_STATES`), and the authority class and decision channel are the
Knowledge plane's `KnowledgeReviewAuthorityClass` and
`KnowledgeDecisionChannel` (`ISSUE_AUTHORITY_CLASSES`,
`ATTESTED_AUTHORITY_CLASSES`, `ATTESTED_DECISION_CHANNELS`).

**S2** (`docs/architecture/record-lineage-s2-contract.md` section 3) widens
the Issue states (`closed`), the Issue revision actions (`closed`, `reopened`,
`corrected`) and the relation types (`delegated_from`, `escalated_from`,
`blocks`, `created_to_resolve`), adds the handoff holder vocabulary and the
read-only closure blockers, and widens the capability sets the S2 revision
(`d020b532ad7d`) restates as frozen literals, in the same change.

**S3** (`docs/architecture/record-lineage-s3-contract.md` section 3) adds the
relation `related_context`, the link actions `contest` and `reinstate` and the
state `contested`, the read-only `restricted` availability and the two S3
completeness codes, the handoff-correction, timeline and backfill vocabularies,
and the S3 capability sets; the S3 revision restates each as a frozen literal
in the same change. The backfill's own source, class, reason and run-state
vocabularies are `domain.lineage_backfill.vocabulary`'s: the dry run reads
native shapes (a Meeting's Series among them) that lineage itself never reads.

Pure data: this module persists nothing and grants nothing.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeDecisionChannel,
    KnowledgeReviewAuthorityClass,
)

__all__ = [
    "ATTESTED_AUTHORITY_CLASSES",
    "ATTESTED_DECISION_CHANNELS",
    "BACKFILL_WRITE_CAPABILITIES",
    "COMPOSITE_CAPABILITIES",
    "COMPOSITE_ONLY_RELATIONS",
    "CONTESTABLE_RELATIONS",
    "HANDOFF_CAPABILITIES",
    "HANDOFF_CORRECTION_CAPABILITIES",
    "ISSUE_AUTHORITY_CLASSES",
    "ISSUE_REVISION_CAPABILITIES",
    "ISSUE_STATES",
    "LINEAGE_BACKFILL_CAPABILITIES",
    "LINEAGE_FAMILY_READS",
    "LINEAGE_READ_GENERATION",
    "LINEAGE_WRITE_CAPABILITIES",
    "LINK_REVISION_CAPABILITIES",
    "LIVE_LINK_STATES",
    "MANDATORY_MEMBER_ROLES",
    "MEMBERSHIP_EVENT_CAPABILITIES",
    "MEMBER_VERSION_CAPABILITIES",
    "RECORD_FAMILY_ID_KINDS",
    "RECORD_LINK_CAPABILITIES",
    "RELATION_MATRIX",
    "S1_LINEAGE_WRITE_CAPABILITIES",
    "S2_LINEAGE_WRITE_CAPABILITIES",
    "AcceptanceBasis",
    "EvidenceAvailability",
    "EvidenceRole",
    "EvidenceSourceFamily",
    "ExistingLinkState",
    "HandoffCorrectionAction",
    "HandoffHolderKind",
    "HandoffSide",
    "IssueClosureBlocker",
    "IssueProjectMembershipAction",
    "IssueProjectMembershipState",
    "IssueRevisionAction",
    "LineageCompleteness",
    "LinkLifecycleState",
    "LinkRevisionAction",
    "MemberRole",
    "NativeVirtualEdge",
    "RecordFamily",
    "RecordLinkKind",
    "RelationType",
    "Selector",
    "SituationKind",
    "SourceVersionKind",
    "TimelineEntryKind",
]


class SituationKind(StrEnum):
    """What a `situations` row is: a context Situation or an Issue (OD-01)."""

    CONTEXT = "context"
    ISSUE_WORKSTREAM = "issue_workstream"


class IssueRevisionAction(StrEnum):
    """Why an Issue revision was written.

    S2 adds `closed` (`issues.close`), `reopened` (`issues.reopen`) and
    `corrected` (an `issues.update` of a closed Issue's title or description,
    which keeps it closed).
    """

    CREATED = "created"
    UPDATED = "updated"
    ACTIVATED = "activated"
    SUSPENDED = "suspended"
    CLOSED = "closed"
    REOPENED = "reopened"
    CORRECTED = "corrected"


class IssueProjectMembershipAction(StrEnum):
    """One event on an Issue's native Project link."""

    ASSERT = "assert"
    END = "end"
    REINSTATE = "reinstate"


class IssueProjectMembershipState(StrEnum):
    """Where an Issue's native Project link stands after an event."""

    ACTIVE = "active"
    ENDED = "ended"


class RecordFamily(StrEnum):
    """An endpoint family a record link may name in S1."""

    SITUATION = "situation"
    MEETING = "meeting"
    MEETING_NOTE_VERSION = "meeting_note_version"
    TASK = "task"
    COMMITMENT = "commitment"
    CONSTRAINT = "constraint"
    CAPTURE_VERSION = "capture_version"


class RecordLinkKind(StrEnum):
    """An Issue membership or a semantic association."""

    ISSUE_MEMBERSHIP = "issue_membership"
    SEMANTIC = "semantic"


class RelationType(StrEnum):
    """The S1 relation types (S1 section 3.1), the four S2 adds (S2 section 3.1) and S3's one.

    S3 (section 3.1) adds `related_context`: symmetric, stored once in canonical
    order, and always Issue-scoped.
    """

    ISSUE_MEMBER = "issue_member"
    ORIGINATED_FROM = "originated_from"
    DISCUSSES = "discusses"
    DELEGATED_FROM = "delegated_from"
    ESCALATED_FROM = "escalated_from"
    BLOCKS = "blocks"
    CREATED_TO_RESOLVE = "created_to_resolve"
    RELATED_CONTEXT = "related_context"


class MemberRole(StrEnum):
    """The role a record plays as a member of an Issue."""

    ORIGIN_EVIDENCE = "origin_evidence"
    DISCUSSION = "discussion"
    WORK = "work"
    CONSTRAINT = "constraint"
    SUPPORTING_EVIDENCE = "supporting_evidence"
    REFERENCE = "reference"


class Selector(StrEnum):
    """How an endpoint is selected. S1 links name roots only."""

    ROOT = "root"


class LinkRevisionAction(StrEnum):
    """One revision of a record link. S3 (section 3.1) adds `contest` and `reinstate`."""

    ASSERT = "assert"
    END = "end"
    CORRECT_EVIDENCE = "correct_evidence"
    CONTEST = "contest"
    REINSTATE = "reinstate"


class LinkLifecycleState(StrEnum):
    """Where a record link stands after a revision. S3 adds `contested` (section 3.1)."""

    ACTIVE = "active"
    ENDED = "ended"
    CONTESTED = "contested"


class AcceptanceBasis(StrEnum):
    """Why a link or Project-link event is accepted. S1: an attested user."""

    USER_CONFIRMED = "user_confirmed"


class EvidenceSourceFamily(StrEnum):
    """The source an evidence anchor binds."""

    MEETING_NOTE_VERSION = "meeting_note_version"
    CAPTURE_VERSION = "capture_version"
    #: A Capture root with no version (`legacy_unversioned` only).
    CAPTURE = "capture"


class SourceVersionKind(StrEnum):
    """Whether an anchor pins an exact immutable version."""

    IMMUTABLE_VERSION = "immutable_version"
    LEGACY_UNVERSIONED = "legacy_unversioned"


class EvidenceRole(StrEnum):
    """The role one anchor plays in one link revision's evidence set."""

    ORIGIN = "origin"
    CORROBORATES = "corroborates"
    CONTRADICTS = "contradicts"
    DISCUSSION = "discussion"
    HANDOFF = "handoff"
    RESOLUTION = "resolution"


class EvidenceAvailability(StrEnum):
    """Read-only: how an anchor's source stands now (computed at read time)."""

    AVAILABLE = "available"
    ARCHIVED = "archived"
    LEGACY_UNVERSIONED = "legacy_unversioned"
    #: S3 (section 6.4): a legacy Capture anchor whose root now has a
    #: `restricted_local` version.
    RESTRICTED = "restricted"


class LineageCompleteness(StrEnum):
    """Read-only: what a `records.lineage` answer is able to claim.

    S3 (section 3) adds `restricted_evidence` and `scope_changed_restart_required`;
    `domain.lineage.asof.completeness` orders the codes by section 3's precedence.
    """

    COMPLETE = "complete"
    TRUNCATED_BUDGET = "truncated_budget"
    UNRESOLVED_AMBIGUITY = "unresolved_ambiguity"
    PARTIAL_NATIVE_HISTORY = "partial_native_history"
    RESTRICTED_EVIDENCE = "restricted_evidence"
    SCOPE_CHANGED_RESTART_REQUIRED = "scope_changed_restart_required"


class NativeVirtualEdge(StrEnum):
    """Read-only: an edge derived from native rows rather than stored."""

    MEETING_NOTE_VERSION_OF = "meeting_note_version_of"


class HandoffHolderKind(StrEnum):
    """Who holds a Commitment's next management action in one handoff event (S2 3.4)."""

    PRINCIPAL = "principal"
    ENTITY = "entity"


class HandoffSide(StrEnum):
    """Request only: the side a handoff's responsibility leaves (S2 section 3.4)."""

    PRINCIPAL = "principal"
    COUNTERPARTY = "counterparty"


class IssueClosureBlocker(StrEnum):
    """Read-only: why one mandatory member blocks an Issue's close (S2 section 3.3).

    Declared in the order the gate reports them: the native conditions first,
    then the resolution-evidence conditions.
    """

    NATIVE_OPEN = "native_open"
    NATIVE_TERMINAL_UNSUCCESSFUL = "native_terminal_unsuccessful"
    NATIVE_NOT_ACCEPTED = "native_not_accepted"
    ROLE_FAMILY_NOT_CLOSABLE = "role_family_not_closable"
    RESOLUTION_EVIDENCE_MISSING = "resolution_evidence_missing"
    RESOLUTION_EVIDENCE_UNAVAILABLE = "resolution_evidence_unavailable"
    RESOLUTION_EVIDENCE_CONTRADICTED = "resolution_evidence_contradicted"
    RESOLUTION_EVIDENCE_STALE = "resolution_evidence_stale"


class HandoffCorrectionAction(StrEnum):
    """S3 section 3.3: how one append-only correction changes one handoff's meaning."""

    RETIME = "retime"
    VOID = "void"


class TimelineEntryKind(StrEnum):
    """Read-only: one `issues.timeline` entry's kind, in the section 7.3 table order."""

    ISSUE_REVISION = "issue_revision"
    PROJECT_LINK = "project_link"
    MEMBERSHIP = "membership"
    ASSOCIATION = "association"
    HANDOFF = "handoff"
    HANDOFF_CORRECTION = "handoff_correction"
    NATIVE_EVENT = "native_event"


class ExistingLinkState(StrEnum):
    """Read-only: the state, at a run's cutoff, of a link between a candidate's endpoints."""

    NONE = "none"
    ACTIVE = "active"
    CONTESTED = "contested"
    ENDED = "ended"


#: The Issue states admitted on `issue_revisions`: S1's three non-terminal
#: states and, from S2, `closed`. Spelled rather than read off
#: `SituationState`, because `domain.situation` imports `SituationKind` from
#: here; `tests/unit/test_lineage_canonical.py` holds the four to that enum.
ISSUE_STATES: Final[frozenset[str]] = frozenset({"open", "active", "suspended", "closed"})

#: The authority classes an Issue revision may record. `remote_operator_attested`
#: is unreachable in S1 (contract section 6.1).
ISSUE_AUTHORITY_CLASSES: Final[frozenset[str]] = frozenset(
    {
        KnowledgeReviewAuthorityClass.LOCAL_OPERATOR.value,
        KnowledgeReviewAuthorityClass.ORDINARY_REVIEWER.value,
    }
)

#: The only authority class an attested lineage row may carry (F21).
ATTESTED_AUTHORITY_CLASSES: Final[frozenset[str]] = frozenset(
    {KnowledgeReviewAuthorityClass.LOCAL_OPERATOR.value}
)

#: The only decision channels an attested lineage row may carry (F21).
ATTESTED_DECISION_CHANNELS: Final[frozenset[str]] = frozenset(
    {KnowledgeDecisionChannel.LOCAL_CLI.value, KnowledgeDecisionChannel.LOCAL_WEB.value}
)

#: The capabilities that write an Issue revision.
ISSUE_REVISION_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {"issues.create", "issues.update", "issues.close", "issues.reopen"}
)

#: The capabilities that write an Issue↔Project membership event.
MEMBERSHIP_EVENT_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {"issues.project_links.add", "issues.project_links.end"}
)

#: The two S2 composite writes (S2 section 6.4): a native Work create, its
#: Issue membership and its association intents in one unit of work.
COMPOSITE_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {"issues.work.create_task", "issues.work.create_commitment"}
)

#: The capabilities that create a record link root.
RECORD_LINK_CAPABILITIES: Final[frozenset[str]] = (
    frozenset({"issues.memberships.add", "records.associations.assert"}) | COMPOSITE_CAPABILITIES
)

#: The capabilities that write a record link revision. S3 (section 3) adds
#: `records.associations.contest` and `records.associations.reinstate`.
LINK_REVISION_CAPABILITIES: Final[frozenset[str]] = RECORD_LINK_CAPABILITIES | frozenset(
    {
        "issues.memberships.end",
        "issues.memberships.correct",
        "records.associations.correct",
        "records.associations.end",
        "records.associations.contest",
        "records.associations.reinstate",
    }
)

#: The capabilities whose link revision may record the member's observed native
#: `version` (`record_link_revisions.member_native_version`, S2 section 3.3).
MEMBER_VERSION_CAPABILITIES: Final[frozenset[str]] = (
    frozenset({"issues.memberships.add", "issues.memberships.correct"}) | COMPOSITE_CAPABILITIES
)

#: The capability that appends a responsibility handoff event (S2 section 3.4).
HANDOFF_CAPABILITIES: Final[frozenset[str]] = frozenset({"issues.handoffs.record"})

#: The nine S1 write capabilities, as S1 named them.
S1_LINEAGE_WRITE_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "issues.create",
        "issues.update",
        "issues.project_links.add",
        "issues.project_links.end",
        "issues.memberships.add",
        "issues.memberships.end",
        "records.associations.assert",
        "records.associations.correct",
        "records.associations.end",
    }
)

#: The six S2 write capabilities, as S2 named them.
S2_LINEAGE_WRITE_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "issues.close",
        "issues.reopen",
        "issues.memberships.correct",
        "issues.handoffs.record",
        "issues.work.create_task",
        "issues.work.create_commitment",
    }
)

#: S3 section 3.3: the capability that writes a handoff correction (the
#: fact-writing set of `issue_responsibility_corrections`).
HANDOFF_CORRECTION_CAPABILITIES: Final[frozenset[str]] = frozenset({"issues.handoffs.correct"})

#: S3 section 8.3: the backfill write. It writes ledger rows only -- no fact and
#: no commit mark.
BACKFILL_WRITE_CAPABILITIES: Final[frozenset[str]] = frozenset({"records.backfill.plan"})

#: The nineteen lineage write capabilities (`lineage_write_requests.capability`):
#: S1's nine, S2's six and S3's four.
LINEAGE_WRITE_CAPABILITIES: Final[frozenset[str]] = (
    ISSUE_REVISION_CAPABILITIES
    | MEMBERSHIP_EVENT_CAPABILITIES
    | LINK_REVISION_CAPABILITIES
    | HANDOFF_CAPABILITIES
    | HANDOFF_CORRECTION_CAPABILITIES
    | BACKFILL_WRITE_CAPABILITIES
)

#: S3 section 7.7: the two operator-only backfill capabilities, withheld unless
#: both the lineage switch and `MY_PA_LINEAGE_BACKFILL_ENABLED` are on.
LINEAGE_BACKFILL_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {"records.backfill.plan", "records.backfill.report"}
)

#: S3 section 3: bumped by any change to traversal, visibility, ordering or
#: paging rules, and bound in every lineage cursor (section 5).
LINEAGE_READ_GENERATION: Final = 1

#: The identifier kind every endpoint family's record id carries.
RECORD_FAMILY_ID_KINDS: Final[MappingProxyType[RecordFamily, IdKind]] = MappingProxyType(
    {
        RecordFamily.SITUATION: IdKind.SITUATION,
        RecordFamily.MEETING: IdKind.MEETING,
        RecordFamily.MEETING_NOTE_VERSION: IdKind.MEETING_NOTE_VERSION,
        RecordFamily.TASK: IdKind.TASK,
        RecordFamily.COMMITMENT: IdKind.COMMITMENT,
        RecordFamily.CONSTRAINT: IdKind.PROJECT_CONSTRAINT,
        RecordFamily.CAPTURE_VERSION: IdKind.CAPTURE_VERSION,
    }
)

#: S3 section 6.4: a remote reader sees a lineage family only while it holds a
#: grant on one of these reads (precedent `RECORD_EVENT_FAMILY_READS`).
LINEAGE_FAMILY_READS: Final[MappingProxyType[RecordFamily, frozenset[str]]] = MappingProxyType(
    {
        RecordFamily.SITUATION: frozenset({"issues.read", "issues.list"}),
        RecordFamily.MEETING: frozenset({"meetings.read", "meetings.list"}),
        RecordFamily.MEETING_NOTE_VERSION: frozenset({"meetings.read", "meetings.list"}),
        RecordFamily.TASK: frozenset({"tasks.read", "tasks.list"}),
        RecordFamily.COMMITMENT: frozenset({"commitments.read", "commitments.list"}),
        RecordFamily.CONSTRAINT: frozenset({"constraints.read", "constraints.list"}),
        RecordFamily.CAPTURE_VERSION: frozenset({"capture.read", "capture.list"}),
    }
)

#: The membership roles the closure gate evaluates (S2 section 3.3).
MANDATORY_MEMBER_ROLES: Final[frozenset[MemberRole]] = frozenset(
    {MemberRole.WORK, MemberRole.CONSTRAINT}
)

#: The relations only a composite's own transaction may write (S2 section 3.1):
#: `records.associations.assert` refuses them as it refuses `issue_member`.
COMPOSITE_ONLY_RELATIONS: Final[frozenset[RelationType]] = frozenset(
    {RelationType.DELEGATED_FROM, RelationType.CREATED_TO_RESOLVE}
)

#: S3 section 3: the link states that hold an identity and are traversed.
LIVE_LINK_STATES: Final[frozenset[LinkLifecycleState]] = frozenset(
    {LinkLifecycleState.ACTIVE, LinkLifecycleState.CONTESTED}
)

#: S3 section 3.1: the relations `contest` admits -- every semantic relation.
CONTESTABLE_RELATIONS: Final[frozenset[RelationType]] = frozenset(RelationType) - {
    RelationType.ISSUE_MEMBER
}

#: S3 section 3.1: the six families a `related_context` link may join, both ways.
_RELATED_CONTEXT_FAMILIES: Final = frozenset(
    {
        RecordFamily.MEETING,
        RecordFamily.MEETING_NOTE_VERSION,
        RecordFamily.TASK,
        RecordFamily.COMMITMENT,
        RecordFamily.CONSTRAINT,
        RecordFamily.CAPTURE_VERSION,
    }
)

#: The section 3.1 relation matrix: `relation -> (kind, from families, to families)`.
#: Any other `(from, to, relation)` is refused, by the application and by the
#: `a_record_link_pair_is_admitted` CHECK alike.
RELATION_MATRIX: Final[
    MappingProxyType[
        RelationType, tuple[RecordLinkKind, frozenset[RecordFamily], frozenset[RecordFamily]]
    ]
] = MappingProxyType(
    {
        RelationType.ISSUE_MEMBER: (
            RecordLinkKind.ISSUE_MEMBERSHIP,
            frozenset({RecordFamily.SITUATION}),
            frozenset(
                {
                    RecordFamily.MEETING,
                    RecordFamily.MEETING_NOTE_VERSION,
                    RecordFamily.TASK,
                    RecordFamily.COMMITMENT,
                    RecordFamily.CONSTRAINT,
                    RecordFamily.CAPTURE_VERSION,
                }
            ),
        ),
        RelationType.ORIGINATED_FROM: (
            RecordLinkKind.SEMANTIC,
            frozenset({RecordFamily.COMMITMENT, RecordFamily.TASK, RecordFamily.CONSTRAINT}),
            frozenset({RecordFamily.MEETING_NOTE_VERSION, RecordFamily.CAPTURE_VERSION}),
        ),
        RelationType.DISCUSSES: (
            RecordLinkKind.SEMANTIC,
            frozenset({RecordFamily.MEETING, RecordFamily.MEETING_NOTE_VERSION}),
            frozenset(
                {
                    RecordFamily.SITUATION,
                    RecordFamily.TASK,
                    RecordFamily.COMMITMENT,
                    RecordFamily.CONSTRAINT,
                }
            ),
        ),
        # S2 section 3.1.
        RelationType.DELEGATED_FROM: (
            RecordLinkKind.SEMANTIC,
            frozenset({RecordFamily.COMMITMENT}),
            frozenset({RecordFamily.TASK}),
        ),
        RelationType.ESCALATED_FROM: (
            RecordLinkKind.SEMANTIC,
            frozenset({RecordFamily.CONSTRAINT}),
            frozenset({RecordFamily.TASK}),
        ),
        RelationType.BLOCKS: (
            RecordLinkKind.SEMANTIC,
            frozenset({RecordFamily.TASK, RecordFamily.CONSTRAINT}),
            frozenset({RecordFamily.TASK, RecordFamily.CONSTRAINT}),
        ),
        RelationType.CREATED_TO_RESOLVE: (
            RecordLinkKind.SEMANTIC,
            frozenset({RecordFamily.TASK, RecordFamily.COMMITMENT}),
            frozenset({RecordFamily.SITUATION, RecordFamily.CONSTRAINT}),
        ),
        # S3 section 3.1.
        RelationType.RELATED_CONTEXT: (
            RecordLinkKind.SEMANTIC,
            _RELATED_CONTEXT_FAMILIES,
            _RELATED_CONTEXT_FAMILIES,
        ),
    }
)
