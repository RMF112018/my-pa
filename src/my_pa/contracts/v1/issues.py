"""The public shapes of an Issue answer (record lineage S1 and S2 contracts, section 7.1).

S1's four models: `IssueRevisionView` for the Issue write results, `IssueView`
for an `issues.read`, `ProjectLinkView` for one native Issue↔Project link, and
`IssueListEntry` for an `issues.list` row. S2 adds `IssueClosureView` (the
closing revision's basis, on `IssueView.closure` and the `issues.close`
answer), `IssueReopeningView` (the `issues.reopen` answer's basis) and
`ClosureBlockerView` (one blocked mandatory member, `issues.closure_readiness`),
and `HandoffView` / `HandoffHolderView` (one responsibility handoff event,
`issues.handoffs.record` and `.list`).
S3 adds `ContestedLinkView` (one contested link in the Issue's context,
`issues.closure_readiness`), `HandoffCorrectionView` (one append-only handoff
correction) and three `HandoffView` keys: `current_effective_at`, `voided` and
`correction_ids` (`effective_at` keeps its recorded S2 meaning, R3-F18).
S3.1 adds `UnreviewedLinkView` (one link in the Issue's review scope whose
head revision is `client_identified`, `issues.closure_readiness`) and the
section 7.6 labels: `ProjectLinkView`, `HandoffView` and `HandoffCorrectionView`
gain `user_directed_claim` and `asserting_client_id` (the writing OAuth client,
`null` for every remote reader), and `HandoffCorrectionView` its
`acceptance_basis`.
No S1 key changes meaning; `state` may now be `closed` and `action` names the
S2 actions. No closure evidence digest is ever shown (FR1-F05).

**What these models cannot carry is the point of them.** No `principal_id`, no
idempotency key and no request digest: the caller acts inside its own partition,
and the request identity is the server's arbitration of a write, not part of
what the write did. `IssueRevisionView` is rebuilt from the immutable revision a
write recorded, so a replay answers byte-for-byte what the original did (apart
from `replayed`, which is beside it) even after the Issue moved on.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from my_pa.contracts.v1.base import StrictModel, UtcDatetime
from my_pa.contracts.v1.record_lineage import (
    ASSERTING_CLIENT_ID,
    EvidenceAnchorView,
    RecordRefView,
)
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.lineage.model import (
    MAX_EVIDENCE_ANCHORS,
    MAX_ISSUE_DESCRIPTION_CHARACTERS,
    MAX_ISSUE_TITLE_CHARACTERS,
    MAX_LINEAGE_REASON_CHARACTERS,
)
from my_pa.domain.lineage.vocabulary import (
    MAX_UNREVIEWED_LINKS,
    AcceptanceBasis,
    EvidenceRole,
    HandoffCorrectionAction,
    HandoffHolderKind,
    IssueClosureBlocker,
    IssueProjectMembershipState,
    IssueRevisionAction,
    LinkLifecycleState,
    LinkRevisionAction,
    MemberRole,
    RecordLinkKind,
    RelationType,
)

__all__ = [
    "MAX_CLOSURE_BLOCKERS",
    "MAX_CONTESTED_LINKS",
    "MAX_HANDOFF_CORRECTIONS",
    "MAX_ISSUE_PROJECT_LINKS",
    "MAX_UNREVIEWED_LINKS",
    "ClosureBlockerView",
    "ContestedLinkView",
    "HandoffCorrectionView",
    "HandoffHolderView",
    "HandoffView",
    "IssueClosureView",
    "IssueHistoryEntryView",
    "IssueListEntry",
    "IssueReopeningView",
    "IssueRevisionView",
    "IssueView",
    "ProjectLinkView",
    "UnreviewedLinkView",
]

#: At most this many Project links in one `IssueView` (section 7.1).
MAX_ISSUE_PROJECT_LINKS = 100
#: At most this many blocked members in one `issues.closure_readiness` (S2 7.2).
MAX_CLOSURE_BLOCKERS = 100
#: At most this many contested links in one `issues.closure_readiness` (S3 7.1).
MAX_CONTESTED_LINKS = 100
#: At most this many correction ids on one `HandoffView` (S3 7.1).
MAX_HANDOFF_CORRECTIONS = 32

#: The Issue states: S1's three non-terminal states and S2's `closed`.
IssueState = Literal["open", "active", "suspended", "closed"]

_Title = Field(min_length=1, max_length=MAX_ISSUE_TITLE_CHARACTERS)
_Description = Field(default=None, max_length=MAX_ISSUE_DESCRIPTION_CHARACTERS)


def _valid_issue_id(value: str) -> str:
    return validate_identifier(value, IdKind.SITUATION)


class IssueRevisionView(StrictModel):
    """One immutable Issue revision as an `issues.create`/`issues.update` result.

    Carries no Project links: a link write never changes the Issue's version.
    """

    issue_id: str
    kind: Literal["issue_workstream"] = "issue_workstream"
    version: int = Field(ge=1)
    state: IssueState
    title: str = _Title
    description: str | None = _Description
    revision_id: str
    action: IssueRevisionAction
    opened_at: UtcDatetime
    created_at: UtcDatetime
    recorded_at: UtcDatetime

    @field_validator("issue_id")
    @classmethod
    def _issue_id(cls, value: str) -> str:
        return _valid_issue_id(value)

    @field_validator("revision_id")
    @classmethod
    def _revision_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.ISSUE_REVISION)


class IssueHistoryEntryView(IssueRevisionView):
    """One revision in `issues.history` (S3 section 7.3).

    The S1 `IssueRevisionView` keys plus the revision's own closure basis:
    `closed_at` and `outcome` (a `closed` or `corrected` revision), `reason`
    (a `reopened` one) and its closing or reopening evidence set, each anchor
    visibility-filtered (section 6.4). No digest (FR1-F05).
    """

    closed_at: UtcDatetime | None = None
    outcome: str | None = None
    reason: str | None = Field(default=None, max_length=MAX_LINEAGE_REASON_CHARACTERS)
    evidence: tuple[EvidenceAnchorView, ...] = Field(default=(), max_length=MAX_EVIDENCE_ANCHORS)


class ProjectLinkView(StrictModel):
    """One native Issue↔Project link, as its latest membership event states it."""

    project_id: str
    project_situation_id: str
    state: IssueProjectMembershipState
    membership_revision_no: int = Field(ge=1)
    acceptance_basis: AcceptanceBasis
    #: S3.1 section 7.6: the writing client's unverified claim, and its OAuth id.
    user_directed_claim: bool = False
    asserting_client_id: str | None = ASSERTING_CLIENT_ID
    evidence_anchor_id: str | None = None
    recorded_at: UtcDatetime

    @field_validator("project_id")
    @classmethod
    def _project_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.PROJECT)

    @field_validator("project_situation_id")
    @classmethod
    def _project_situation_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.PROJECT_SITUATION)

    @field_validator("evidence_anchor_id")
    @classmethod
    def _evidence_anchor_id(cls, value: str | None) -> str | None:
        return None if value is None else validate_identifier(value, IdKind.LINEAGE_EVIDENCE_ANCHOR)


class IssueClosureView(StrictModel):
    """The basis an Issue is closed on (S2 section 7.1): the latest `closed` revision.

    A `corrected` revision copies its `closed_at` and `outcome`; the evidence
    stays the closing revision's. Availability is computed at read time. No
    digest.
    """

    version: int = Field(ge=1)
    closed_at: UtcDatetime
    outcome: str = Field(min_length=1, max_length=MAX_LINEAGE_REASON_CHARACTERS)
    evidence: tuple[EvidenceAnchorView, ...] = Field(min_length=1, max_length=MAX_EVIDENCE_ANCHORS)


class IssueReopeningView(StrictModel):
    """Why an Issue was reopened, and the evidence it was reopened with (S2 section 7.2)."""

    reason: str = Field(min_length=1, max_length=MAX_LINEAGE_REASON_CHARACTERS)
    evidence: tuple[EvidenceAnchorView, ...] = Field(max_length=MAX_EVIDENCE_ANCHORS)


class ClosureBlockerView(StrictModel):
    """One mandatory member that blocks an Issue's close, and every reason (S2 section 7.1).

    `native_state` is the member's native lifecycle token (`lifecycle_state` or
    `state`); `evidence_state` is a Task's or Commitment's, else `None`.
    """

    link_id: str
    member: RecordRefView
    role: MemberRole
    native_state: str | None
    evidence_state: str | None
    reasons: tuple[IssueClosureBlocker, ...] = Field(min_length=1)

    @field_validator("link_id")
    @classmethod
    def _link_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.RECORD_LINK)


class IssueView(StrictModel):
    """One Issue as `issues.read` answers it, with at most 100 Project links.

    `closure` (S2) is non-null exactly while the Issue is `closed`.
    """

    issue_id: str
    kind: Literal["issue_workstream"] = "issue_workstream"
    version: int = Field(ge=1)
    state: IssueState
    title: str = _Title
    description: str | None = _Description
    opened_at: UtcDatetime
    created_at: UtcDatetime
    updated_at: UtcDatetime
    project_links: tuple[ProjectLinkView, ...] = Field(max_length=MAX_ISSUE_PROJECT_LINKS)
    project_links_truncated: bool
    closure: IssueClosureView | None = None

    @field_validator("issue_id")
    @classmethod
    def _issue_id(cls, value: str) -> str:
        return _valid_issue_id(value)


class IssueListEntry(StrictModel):
    """One Issue as an `issues.list` page row: no description, no links."""

    issue_id: str
    version: int = Field(ge=1)
    state: IssueState
    title: str = _Title
    updated_at: UtcDatetime

    @field_validator("issue_id")
    @classmethod
    def _issue_id(cls, value: str) -> str:
        return _valid_issue_id(value)


class HandoffHolderView(StrictModel):
    """One handoff holder (S2 section 7.1): the Principal, or one Entity by id."""

    kind: HandoffHolderKind
    entity_id: str | None

    @model_validator(mode="after")
    def _check(self) -> HandoffHolderView:
        if (self.kind is HandoffHolderKind.PRINCIPAL) is not (self.entity_id is None):
            raise ValueError("only an Entity holder names an Entity")
        if self.entity_id is not None:
            validate_identifier(self.entity_id, IdKind.ENTITY)
        return self


class HandoffView(StrictModel):
    """One immutable responsibility handoff event (S2 sections 3.4 and 7.1).

    `from_holder`/`to_holder` serialize as `from`/`to`, as `AssociationView`'s
    endpoints do. `evidence` is the one `handoff` anchor, its availability
    computed at read time.
    """

    handoff_id: str
    issue_id: str
    commitment_id: str
    sequence_no: int = Field(ge=1)
    from_holder: HandoffHolderView = Field(serialization_alias="from")
    to_holder: HandoffHolderView = Field(serialization_alias="to")
    effective_at: UtcDatetime
    recorded_at: UtcDatetime
    reason: str = Field(min_length=1, max_length=MAX_LINEAGE_REASON_CHARACTERS)
    evidence: EvidenceAnchorView
    acceptance_basis: AcceptanceBasis
    authority_class: str
    #: S3.1 section 7.6: the writing client's unverified claim, and its OAuth id.
    user_directed_claim: bool = False
    asserting_client_id: str | None = ASSERTING_CLIENT_ID
    #: S3 section 7.1: the current effective time at the read's `known_at` (the
    #: latest known `retime`'s instant, else `effective_at`), whether a `void`
    #: is known, and the known corrections in `correction_no` order.
    current_effective_at: UtcDatetime
    voided: bool
    correction_ids: tuple[str, ...] = Field(max_length=MAX_HANDOFF_CORRECTIONS)

    @field_validator("handoff_id")
    @classmethod
    def _handoff_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.ISSUE_HANDOFF)

    @field_validator("issue_id")
    @classmethod
    def _issue_id(cls, value: str) -> str:
        return _valid_issue_id(value)

    @field_validator("commitment_id")
    @classmethod
    def _commitment_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.COMMITMENT)

    @field_validator("correction_ids")
    @classmethod
    def _correction_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for correction_id in value:
            validate_identifier(correction_id, IdKind.ISSUE_HANDOFF_CORRECTION)
        return value

    def to_canonical_dict(self) -> dict[str, Any]:
        """The JSON-mode representation, with the section 7.1 `from`/`to` keys."""
        return self.model_dump(mode="json", by_alias=True)


class HandoffCorrectionView(StrictModel):
    """One immutable handoff correction (S3 sections 3.3 and 7.1).

    `effective_at` is the retimed instant (`retime`), `null` for a `void`;
    `evidence` is the one cited anchor (`handoff` for a retime, `contradicts`
    for a void), its availability computed at read time.
    """

    correction_id: str
    handoff_id: str
    correction_no: int = Field(ge=1)
    action: HandoffCorrectionAction
    effective_at: UtcDatetime | None
    reason: str = Field(min_length=1, max_length=MAX_LINEAGE_REASON_CHARACTERS)
    evidence: EvidenceAnchorView
    recorded_at: UtcDatetime
    authority_class: str
    #: S3.1 section 7.6: the correction's own basis, claim and writing client.
    acceptance_basis: AcceptanceBasis = AcceptanceBasis.USER_CONFIRMED
    user_directed_claim: bool = False
    asserting_client_id: str | None = ASSERTING_CLIENT_ID

    @field_validator("correction_id")
    @classmethod
    def _correction_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.ISSUE_HANDOFF_CORRECTION)

    @field_validator("handoff_id")
    @classmethod
    def _handoff_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.ISSUE_HANDOFF)

    @model_validator(mode="after")
    def _retime_states_its_instant(self) -> HandoffCorrectionView:
        retime = self.action is HandoffCorrectionAction.RETIME
        if retime is not (self.effective_at is not None):
            raise ValueError("a retime states its effective time; a void none")
        role = EvidenceRole.HANDOFF if retime else EvidenceRole.CONTRADICTS
        if self.evidence.role is not role:
            raise ValueError("a correction cites its action's evidence role")
        return self

    def to_canonical_dict(self) -> dict[str, Any]:
        """The JSON-mode representation."""
        return self.model_dump(mode="json")


class ContestedLinkView(StrictModel):
    """One contested semantic link in an Issue's context (S3 sections 3.2 and 7.1)."""

    link_id: str
    relation_type: RelationType

    @field_validator("link_id")
    @classmethod
    def _link_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.RECORD_LINK)

    def to_canonical_dict(self) -> dict[str, Any]:
        """The JSON-mode representation."""
        return self.model_dump(mode="json")


class UnreviewedLinkView(StrictModel):
    """One unreviewed link in an Issue's review scope (S3.1 contract sections 4.6 and 7.5).

    Its head revision is `client_identified`: it holds the close until the human
    channel confirms or revises it. `user_directed_claim` is the writing
    client's own, unverified statement; it changes no outcome.
    """

    link_id: str
    kind: RecordLinkKind
    relation_type: RelationType
    member_role: MemberRole | None = None
    lifecycle_state: LinkLifecycleState
    revision_no: int = Field(ge=1)
    action: LinkRevisionAction
    user_directed_claim: bool
    recorded_at: UtcDatetime

    @field_validator("link_id")
    @classmethod
    def _link_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.RECORD_LINK)

    def to_canonical_dict(self) -> dict[str, Any]:
        """The JSON-mode representation."""
        return self.model_dump(mode="json")
