"""The Issue closure gate (OD-03), record lineage S2 contract section 3.3.

Pure: given one mandatory member's native facts and its membership's head
revision evidence, `member_blockers` answers every reason the member does not
satisfy the gate, in the contract's order (the native conditions, then the
resolution-evidence conditions; `IssueClosureBlocker` is declared in that
order). It reads nothing, writes nothing and never changes a native record:
the gate observes native truth and the evidence that proves it.

**Mandatory members** are active `issue_member` links whose role is `work` or
`constraint` (`MANDATORY_MEMBER_ROLES`); every other role, every semantic link
and every ended membership is evaluated for nothing.

**Native conditions** (never written by the gate):

* a Task is satisfied when `lifecycle_state = completed` and
  `evidence_state = accepted` -- else `native_open` (non-terminal),
  `native_terminal_unsuccessful` (`cancelled`), `native_not_accepted`;
* a Commitment when `state = closed` and `evidence_state = accepted` -- else
  `native_open`, `native_not_accepted` (closed but `proposed`: AT-015);
* a Constraint when `lifecycle_state = closed` -- else `native_open` (`draft`
  or active), `native_terminal_unsuccessful` (`void`);
* any other family is `role_family_not_closable`.

**Resolution evidence** (the membership's head revision): at least one anchor
with role `resolution` and kind `immutable_version` (else
`resolution_evidence_missing`) whose availability now is `available` (else
`resolution_evidence_unavailable`), and no anchor with role `contradicts`
(else `resolution_evidence_contradicted`). A `legacy_unversioned` anchor never
satisfies anything. For a Task, Commitment or Constraint the head revision's
`member_native_version` must equal the member's current native `version`, so
evidence recorded before any later native change is
`resolution_evidence_stale` (R2-F01).

**S3** (`docs/architecture/record-lineage-s3-contract.md` sections 3.1 and
3.2) adds the link transition table (`link_transition`), the contest evidence
rule (`is_contest_evidence`) and the one "in the Issue's context" predicate
(`in_issue_context`) the gate, readiness, the frozen-closed refusals and the
timeline all use: a membership from *I*; a semantic link whose context is *I*;
a semantic link with *I* as an endpoint; or a null-context semantic link whose
two endpoints are both *inside* *I* (*I*, an active member, or a member of an
active member's pair set). The gate's one S3 condition is that no link in the
Issue's context has a `contested` head.

**S3.1** (`docs/architecture/record-lineage-s31-open-writes-contract.md`
sections 4.6 and 4.7) adds 1 condition: no link in the Issue's **review
scope** (`in_review_scope`: the `in_issue_context` predicate over links in
*any* head state, so ended heads count too) has an unreviewed head -- a
`client_identified` head revision (`is_unreviewed`). And a mandatory member
whose head revision is client-identified offers no resolution evidence
(`MembershipHeadEvidence.accepted`): client resolution evidence never
satisfies the gate until the human channel confirms or revises it. Nothing
here reads a client's declared claim about who directed a write.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from my_pa.domain.lineage.model import EvidenceAnchor, RecordRef
from my_pa.domain.lineage.vocabulary import (
    MANDATORY_MEMBER_ROLES,
    AcceptanceBasis,
    EvidenceAvailability,
    EvidenceRole,
    IssueClosureBlocker,
    LinkLifecycleState,
    LinkRevisionAction,
    RecordFamily,
    RecordLinkKind,
    SourceVersionKind,
)

__all__ = [
    "LINK_TRANSITIONS",
    "MANDATORY_MEMBER_ROLES",
    "VERSIONED_MEMBER_FAMILIES",
    "MemberNativeFacts",
    "MembershipHeadEvidence",
    "has_resolution_anchor",
    "in_issue_context",
    "in_review_scope",
    "is_contest_evidence",
    "is_unreviewed",
    "link_transition",
    "member_blockers",
]

#: The member families whose membership revisions record the member's native
#: `version` and whose resolution evidence can go stale.
VERSIONED_MEMBER_FAMILIES: Final[frozenset[RecordFamily]] = frozenset(
    {RecordFamily.TASK, RecordFamily.COMMITMENT, RecordFamily.CONSTRAINT}
)

_ACCEPTED: Final = "accepted"


@dataclass(frozen=True, slots=True)
class MemberNativeFacts:
    """One member's native facts: its lifecycle token, acceptance and version.

    `native_state` is the Task or Constraint `lifecycle_state` or the
    Commitment `state`; `evidence_state` is a Task's or Commitment's (else
    `None`); `version` is the native optimistic-concurrency counter (else
    `None`).
    """

    family: RecordFamily
    native_state: str | None
    evidence_state: str | None
    version: int | None


@dataclass(frozen=True, slots=True)
class MembershipHeadEvidence:
    """The membership's head revision: its evidence set and observed member version.

    S3.1 (section 4.6): `accepted` is false for a `client_identified` head,
    whose anchors are then evaluated as no resolution evidence at all.
    """

    anchors: tuple[EvidenceAnchor, ...]
    member_native_version: int | None
    accepted: bool = True


def has_resolution_anchor(anchors: Sequence[EvidenceAnchor]) -> bool:
    """Whether a set holds an `immutable_version` anchor with role `resolution`."""
    return any(_is_resolution(anchor) for anchor in anchors)


def _is_resolution(anchor: EvidenceAnchor) -> bool:
    return (
        anchor.role is EvidenceRole.RESOLUTION
        and anchor.source_version_kind is SourceVersionKind.IMMUTABLE_VERSION
    )


def _native_blockers(native: MemberNativeFacts) -> list[IssueClosureBlocker]:
    found: list[IssueClosureBlocker] = []
    state = native.native_state
    if native.family is RecordFamily.TASK:
        if state == "cancelled":
            found.append(IssueClosureBlocker.NATIVE_TERMINAL_UNSUCCESSFUL)
        elif state != "completed":
            found.append(IssueClosureBlocker.NATIVE_OPEN)
        if native.evidence_state != _ACCEPTED:
            found.append(IssueClosureBlocker.NATIVE_NOT_ACCEPTED)
    elif native.family is RecordFamily.COMMITMENT:
        if state != "closed":
            found.append(IssueClosureBlocker.NATIVE_OPEN)
        if native.evidence_state != _ACCEPTED:
            found.append(IssueClosureBlocker.NATIVE_NOT_ACCEPTED)
    elif native.family is RecordFamily.CONSTRAINT:
        if state == "void":
            found.append(IssueClosureBlocker.NATIVE_TERMINAL_UNSUCCESSFUL)
        elif state != "closed":
            found.append(IssueClosureBlocker.NATIVE_OPEN)
    else:
        found.append(IssueClosureBlocker.ROLE_FAMILY_NOT_CLOSABLE)
    return found


def member_blockers(
    native: MemberNativeFacts,
    head_evidence: MembershipHeadEvidence,
    availability: Callable[[EvidenceAnchor], EvidenceAvailability],
) -> tuple[IssueClosureBlocker, ...]:
    """Every reason one mandatory member blocks the close, in the contract's order.

    `availability` answers an anchor's availability now (computed at
    evaluation time, never stored). An empty answer means the member is
    satisfied.
    """
    found = _native_blockers(native)
    # S3.1 section 4.6: a client's resolution evidence is not accepted-grade.
    cited = head_evidence.anchors if head_evidence.accepted else ()
    resolutions = [anchor for anchor in cited if _is_resolution(anchor)]
    if not resolutions:
        found.append(IssueClosureBlocker.RESOLUTION_EVIDENCE_MISSING)
    elif not any(availability(anchor) is EvidenceAvailability.AVAILABLE for anchor in resolutions):
        found.append(IssueClosureBlocker.RESOLUTION_EVIDENCE_UNAVAILABLE)
    if any(anchor.role is EvidenceRole.CONTRADICTS for anchor in cited):
        found.append(IssueClosureBlocker.RESOLUTION_EVIDENCE_CONTRADICTED)
    if (
        native.family in VERSIONED_MEMBER_FAMILIES
        and head_evidence.member_native_version != native.version
    ):
        found.append(IssueClosureBlocker.RESOLUTION_EVIDENCE_STALE)
    order = list(IssueClosureBlocker)
    return tuple(sorted(set(found), key=order.index))


# --- S3: link transitions, the contest rule and "in the Issue's context" ------

#: S3 section 3.1: each revision action's admitted head states and the state it
#: leaves. `ended` is terminal; `assert` writes revision 1 and has no row here.
LINK_TRANSITIONS: Final[
    Mapping[LinkRevisionAction, tuple[frozenset[LinkLifecycleState], LinkLifecycleState]]
] = MappingProxyType(
    {
        LinkRevisionAction.CORRECT_EVIDENCE: (
            frozenset({LinkLifecycleState.ACTIVE}),
            LinkLifecycleState.ACTIVE,
        ),
        LinkRevisionAction.END: (
            frozenset({LinkLifecycleState.ACTIVE, LinkLifecycleState.CONTESTED}),
            LinkLifecycleState.ENDED,
        ),
        LinkRevisionAction.CONTEST: (
            frozenset({LinkLifecycleState.ACTIVE}),
            LinkLifecycleState.CONTESTED,
        ),
        LinkRevisionAction.REINSTATE: (
            frozenset({LinkLifecycleState.CONTESTED}),
            LinkLifecycleState.ACTIVE,
        ),
    }
)


def link_transition(
    action: LinkRevisionAction, head_state: LinkLifecycleState
) -> LinkLifecycleState | None:
    """The state `action` leaves from `head_state`, or `None` when it is not admitted."""
    admitted = LINK_TRANSITIONS.get(action)
    if admitted is None or head_state not in admitted[0]:
        return None
    return admitted[1]


def is_contest_evidence(anchors: Sequence[EvidenceAnchor]) -> bool:
    """S3 section 3.1: a contest set holds an `immutable_version` anchor with role `contradicts`."""
    return any(
        anchor.role is EvidenceRole.CONTRADICTS
        and anchor.source_version_kind is SourceVersionKind.IMMUTABLE_VERSION
        for anchor in anchors
    )


def in_issue_context(
    *,
    kind: RecordLinkKind,
    from_ref: RecordRef,
    to_ref: RecordRef,
    context_issue_id: str | None,
    issue_id: str,
    inside: Collection[RecordRef],
) -> bool:
    """S3 section 3.2: whether one link is in the context of Issue `issue_id`.

    `inside` is the Issue's inside set at the cut: the Issue itself, its active
    members and every member of an active member's pair set. A membership is
    in context only from its own Issue; a semantic link when its context is the
    Issue, when the Issue is one of its endpoints (whatever its context), or
    when its context is null and both endpoints are inside.
    """
    issue = RecordRef(family=RecordFamily.SITUATION, record_id=issue_id)
    if kind is RecordLinkKind.ISSUE_MEMBERSHIP:
        return from_ref == issue
    if context_issue_id == issue_id or issue in (from_ref, to_ref):
        return True
    return context_issue_id is None and from_ref in inside and to_ref in inside


# --- S3.1: the review scope and the unreviewed condition (section 4.6) -------


def is_unreviewed(acceptance_basis: AcceptanceBasis) -> bool:
    """Whether a head revision of this basis holds the close until the human channel reviews it."""
    return acceptance_basis is AcceptanceBasis.CLIENT_IDENTIFIED


def in_review_scope(
    *,
    kind: RecordLinkKind,
    from_ref: RecordRef,
    to_ref: RecordRef,
    context_issue_id: str | None,
    issue_id: str,
    inside: Collection[RecordRef],
) -> bool:
    """S3.1 section 4.6: whether one link, in any head state, is in Issue `issue_id`'s review scope.

    The S3 predicate `in_issue_context`, applied to every link -- `active`,
    `contested` and `ended` heads alike -- against the Issue's current inside
    set, so a client's end of a mandatory member, reinstate of a contested link
    or correction of resolution evidence stays in scope and holds the close.
    """
    return in_issue_context(
        kind=kind,
        from_ref=from_ref,
        to_ref=to_ref,
        context_issue_id=context_issue_id,
        issue_id=issue_id,
        inside=inside,
    )
