"""Closed vocabularies of record lineage, Slice S1 (S1 contract section 3).

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
    "ISSUE_AUTHORITY_CLASSES",
    "ISSUE_REVISION_CAPABILITIES",
    "ISSUE_STATES",
    "LINEAGE_WRITE_CAPABILITIES",
    "LINK_REVISION_CAPABILITIES",
    "MEMBERSHIP_EVENT_CAPABILITIES",
    "RECORD_FAMILY_ID_KINDS",
    "RECORD_LINK_CAPABILITIES",
    "RELATION_MATRIX",
    "AcceptanceBasis",
    "EvidenceAvailability",
    "EvidenceRole",
    "EvidenceSourceFamily",
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
]


class SituationKind(StrEnum):
    """What a `situations` row is: a context Situation or an Issue (OD-01)."""

    CONTEXT = "context"
    ISSUE_WORKSTREAM = "issue_workstream"


class IssueRevisionAction(StrEnum):
    """Why an Issue revision was written (S1: no close, reopen or correction)."""

    CREATED = "created"
    UPDATED = "updated"
    ACTIVATED = "activated"
    SUSPENDED = "suspended"


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
    """The S1 relation types (section 3.1)."""

    ISSUE_MEMBER = "issue_member"
    ORIGINATED_FROM = "originated_from"
    DISCUSSES = "discusses"


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
    """One revision of a record link."""

    ASSERT = "assert"
    END = "end"
    CORRECT_EVIDENCE = "correct_evidence"


class LinkLifecycleState(StrEnum):
    """Where a record link stands after a revision."""

    ACTIVE = "active"
    ENDED = "ended"


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


class LineageCompleteness(StrEnum):
    """Read-only: what a `records.lineage` answer is able to claim."""

    COMPLETE = "complete"
    TRUNCATED_BUDGET = "truncated_budget"
    UNRESOLVED_AMBIGUITY = "unresolved_ambiguity"
    PARTIAL_NATIVE_HISTORY = "partial_native_history"


class NativeVirtualEdge(StrEnum):
    """Read-only: an edge derived from native rows rather than stored."""

    MEETING_NOTE_VERSION_OF = "meeting_note_version_of"


#: The Issue states S1 admits on `issue_revisions` (no `closed` before S2).
#: Spelled rather than read off `SituationState`, because `domain.situation`
#: imports `SituationKind` from here; `tests/unit/test_lineage_canonical.py`
#: holds the three to a subset of that enum.
ISSUE_STATES: Final[frozenset[str]] = frozenset({"open", "active", "suspended"})

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
ISSUE_REVISION_CAPABILITIES: Final[frozenset[str]] = frozenset({"issues.create", "issues.update"})

#: The capabilities that write an Issue↔Project membership event.
MEMBERSHIP_EVENT_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {"issues.project_links.add", "issues.project_links.end"}
)

#: The capabilities that create a record link root.
RECORD_LINK_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {"issues.memberships.add", "records.associations.assert"}
)

#: The capabilities that write a record link revision.
LINK_REVISION_CAPABILITIES: Final[frozenset[str]] = RECORD_LINK_CAPABILITIES | frozenset(
    {"issues.memberships.end", "records.associations.correct", "records.associations.end"}
)

#: The nine S1 write capabilities (`lineage_write_requests.capability`).
LINEAGE_WRITE_CAPABILITIES: Final[frozenset[str]] = (
    ISSUE_REVISION_CAPABILITIES | MEMBERSHIP_EVENT_CAPABILITIES | LINK_REVISION_CAPABILITIES
)

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
    }
)
