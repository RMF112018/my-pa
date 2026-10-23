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
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from my_pa.domain.lineage.model import EvidenceAnchor
from my_pa.domain.lineage.vocabulary import (
    MANDATORY_MEMBER_ROLES,
    EvidenceAvailability,
    EvidenceRole,
    IssueClosureBlocker,
    RecordFamily,
    SourceVersionKind,
)

__all__ = [
    "MANDATORY_MEMBER_ROLES",
    "VERSIONED_MEMBER_FAMILIES",
    "MemberNativeFacts",
    "MembershipHeadEvidence",
    "has_resolution_anchor",
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
    """The membership's head revision: its evidence set and observed member version."""

    anchors: tuple[EvidenceAnchor, ...]
    member_native_version: int | None


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
    resolutions = [anchor for anchor in head_evidence.anchors if _is_resolution(anchor)]
    if not resolutions:
        found.append(IssueClosureBlocker.RESOLUTION_EVIDENCE_MISSING)
    elif not any(availability(anchor) is EvidenceAvailability.AVAILABLE for anchor in resolutions):
        found.append(IssueClosureBlocker.RESOLUTION_EVIDENCE_UNAVAILABLE)
    if any(anchor.role is EvidenceRole.CONTRADICTS for anchor in head_evidence.anchors):
        found.append(IssueClosureBlocker.RESOLUTION_EVIDENCE_CONTRADICTED)
    if (
        native.family in VERSIONED_MEMBER_FAMILIES
        and head_evidence.member_native_version != native.version
    ):
        found.append(IssueClosureBlocker.RESOLUTION_EVIDENCE_STALE)
    order = list(IssueClosureBlocker)
    return tuple(sorted(set(found), key=order.index))
