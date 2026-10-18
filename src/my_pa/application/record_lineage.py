"""Issue memberships, semantic associations and the reverse read (record lineage S1 and S2).

S1 contract sections 3.1, 3.2, 5, 6 and 7.2. `RecordLineageApplication` is
stateless, takes the unit of work `ApplicationService.invoke` has **already
opened**, the authenticated `principal_id` as a plain parameter, the parsed
request and, for a write, the attested authority pair and the authorization
time. It opens no transaction, so any refusal rolls back the reservation,
locks, rows and request completion together: a refused write leaves no row
and no request.

**Order of every link write** (section 6.3): request digest; reservation
(section 6.2 step 1; a replay answers from the immutable rows the stored
result names); every endpoint, Issue, Issue context and evidence source
`FOR SHARE` in `(family token, identifier)` order with existence under its
parent (`lineage_endpoints.lock_lineage_sources`); linkability; the section 3.1
matrix and evidence rule; the identity advisory lock; the head `FOR UPDATE`;
the anchors in canonical order, then the root, revision, evidence and head (or
the next revision and the head advanced); completion with `result_created`
where the capability has one.

**S2** (S2 contract sections 3.2, 3.3 and 6.2): every link write refuses a
closed Issue it names (`conflict` / `state`, `require_open_issues`); the
revisions take the link's owning or context Issue (and any Issue endpoint)
`FOR SHARE`, so they serialize with an `issues.close`; every membership
revision on a Task, Commitment or Constraint member records the member's
native `version` observed under its `FOR SHARE` (`member_native_version`);
`issues.memberships.correct` replaces a membership's evidence set, admitting
an identical set only as a re-affirmation after the member's native version
moved; and `records.associations.assert` refuses the composite-only relations.

**The reverse read** (`read_lineage`, section 7.2) is current-state,
Principal-scoped, active links only, lock-free, and bounded: matching Issues
from the root's pair set, one Issue selected (or the candidates, or one hop
when none matches), breadth-first under that Issue to `max_depth`, every reached
node re-resolved natively, and the budgets of `MAX_LINEAGE_NODES`,
`MAX_LINEAGE_EDGES` and `MAX_LINEAGE_BYTES`.

**Traversal rule (resolution of section 7.2 step 4, recorded in the handoff).**
Expanding a node expands its pair set: a note version also follows the links of
its Meeting, and a Meeting the links of its note versions. A followed link adds
its far endpoint, and -- when it was reached through a pair member -- that
member, as nodes. A reached note version always reaches its Meeting along
`meeting_note_version_of`. A reached Meeting does not make its other note
versions nodes: they appear only as its virtual edges. So for the AT-001
fixture every root reaches exactly {I, M1, N1, C1}, and N1b is "reachable only
as a virtual note edge of M1".
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final

from my_pa.application.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.application.lineage_endpoints import (
    EvidenceAnchorInput,
    admit_evidence_set,
    anchor_inputs_document,
    insert_evidence_anchor,
    lock_lineage_sources,
    relation_kind,
    require_linkable,
    require_open_issues,
    require_relation_evidence,
)
from my_pa.contracts.ports import (
    IssueRepository,
    LineageEndpoint,
    LineageLinkEvidence,
    LineageResolvedRecord,
    LineageWriteRequestRecord,
    LinkHeadRecord,
    LinkRevisionRecord,
    RecordLineageRepository,
    RecordLinkRecord,
    RepositoryFailureError,
    UnitOfWork,
)
from my_pa.contracts.v1.record_lineage import (
    MAX_ISSUE_MEMBERSHIPS,
    MAX_MATCHING_ISSUES,
    AssociationView,
    EvidenceAnchorView,
    LineageIssueMatch,
    LineageNodeView,
    LineageView,
    RecordRefView,
    VirtualEdgeView,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.operation import Capability
from my_pa.domain.lineage.canonical import evidence_set_digest, normalized_identity, request_digest
from my_pa.domain.lineage.closure import VERSIONED_MEMBER_FAMILIES, has_resolution_anchor
from my_pa.domain.lineage.model import EvidenceAnchor, RecordRef
from my_pa.domain.lineage.vocabulary import (
    COMPOSITE_ONLY_RELATIONS,
    AcceptanceBasis,
    EvidenceAvailability,
    EvidenceSourceFamily,
    LineageCompleteness,
    LinkLifecycleState,
    LinkRevisionAction,
    MemberRole,
    NativeVirtualEdge,
    RecordFamily,
    RecordLinkKind,
    RelationType,
    SituationKind,
    SourceVersionKind,
)
from my_pa.domain.source.registry import issue_identifier

if TYPE_CHECKING:
    from my_pa.application.lineage_authority import LineageAuthority

__all__ = [
    "DEFAULT_LINEAGE_DEPTH",
    "MAX_LINEAGE_BYTES",
    "MAX_LINEAGE_DEPTH",
    "MAX_LINEAGE_EDGES",
    "MAX_LINEAGE_NODES",
    "AssociationAssertRequest",
    "AssociationCorrectRequest",
    "AssociationEndRequest",
    "AssociationResult",
    "LineageReadRequest",
    "MembershipAddRequest",
    "MembershipCorrectRequest",
    "MembershipEndRequest",
    "RecordLineageApplication",
    "anchor_view",
    "association_view",
    "evidence_availability",
    "member_native_version",
    "traverse_lineage",
]

_MEMBERSHIP_ADD: Final = Capability.ISSUES_MEMBERSHIPS_ADD.value
_MEMBERSHIP_END: Final = Capability.ISSUES_MEMBERSHIPS_END.value
_MEMBERSHIP_CORRECT: Final = Capability.ISSUES_MEMBERSHIPS_CORRECT.value
_ASSERT: Final = Capability.RECORDS_ASSOCIATIONS_ASSERT.value
_CORRECT: Final = Capability.RECORDS_ASSOCIATIONS_CORRECT.value
_END: Final = Capability.RECORDS_ASSOCIATIONS_END.value

#: `records.lineage` bounds (section 7.2; design values, not benchmarks).
MAX_LINEAGE_DEPTH: Final = 4
DEFAULT_LINEAGE_DEPTH: Final = 4
MAX_LINEAGE_NODES: Final = 250
MAX_LINEAGE_EDGES: Final = 400
MAX_LINEAGE_BYTES: Final = 512 * 1024
#: A typed edge's serialized size as the expansion estimates it before the
#: edge's evidence is read; the exact bound is applied to the finished answer.
_EDGE_ESTIMATE: Final = 768

#: S2 section 3.1 relations `records.associations.assert` will admit once their
#: assert-time rules are implemented; refused until then.
_NOT_YET_ASSERTABLE: Final = frozenset({RelationType.ESCALATED_FROM, RelationType.BLOCKS})


# ------------------------------------------------------------------- requests


@dataclass(frozen=True, slots=True)
class MembershipAddRequest:
    """`issues.memberships.add`, parsed."""

    issue_id: str
    member: RecordRef
    role: MemberRole
    evidence_anchors: tuple[EvidenceAnchorInput, ...]


@dataclass(frozen=True, slots=True)
class MembershipEndRequest:
    """`issues.memberships.end`, parsed."""

    link_id: str
    expected_revision: int
    reason: str


@dataclass(frozen=True, slots=True)
class MembershipCorrectRequest:
    """`issues.memberships.correct`, parsed (S2 section 7.2): the complete new set."""

    link_id: str
    expected_revision: int
    reason: str
    evidence_anchors: tuple[EvidenceAnchorInput, ...]


@dataclass(frozen=True, slots=True)
class AssociationAssertRequest:
    """`records.associations.assert`, parsed."""

    from_ref: RecordRef
    to_ref: RecordRef
    relation_type: RelationType
    evidence_anchors: tuple[EvidenceAnchorInput, ...]
    context_issue_id: str | None


@dataclass(frozen=True, slots=True)
class AssociationCorrectRequest:
    """`records.associations.correct`, parsed."""

    link_id: str
    expected_revision: int
    reason: str
    evidence_anchors: tuple[EvidenceAnchorInput, ...]


@dataclass(frozen=True, slots=True)
class AssociationEndRequest:
    """`records.associations.end`, parsed."""

    link_id: str
    expected_revision: int
    reason: str
    evidence_anchors: tuple[EvidenceAnchorInput, ...]


@dataclass(frozen=True, slots=True)
class LineageReadRequest:
    """`records.lineage`, parsed."""

    origin: RecordRef
    issue_id: str | None
    max_depth: int


@dataclass(frozen=True, slots=True)
class AssociationResult:
    """What a link write answers. `created` is `None` for `.end` and `.correct`."""

    association: AssociationView
    created: bool | None
    replayed: bool


# --------------------------------------------------------------------- digest


def _ref_document(ref: RecordRef) -> dict[str, object]:
    return {"family": ref.family.value, "record_id": ref.record_id}


def _membership_add_document(request: MembershipAddRequest) -> dict[str, object]:
    return {
        "issue_id": request.issue_id,
        "member": _ref_document(request.member),
        "role": request.role.value,
        "evidence_anchors": anchor_inputs_document(request.evidence_anchors),
    }


def _membership_end_document(request: MembershipEndRequest) -> dict[str, object]:
    return {
        "link_id": request.link_id,
        "expected_revision": request.expected_revision,
        "reason": request.reason,
    }


def _assert_document(request: AssociationAssertRequest) -> dict[str, object]:
    return {
        "from": _ref_document(request.from_ref),
        "to": _ref_document(request.to_ref),
        "relation_type": request.relation_type.value,
        "evidence_anchors": anchor_inputs_document(request.evidence_anchors),
        "context_issue_id": request.context_issue_id,
    }


def _revise_document(
    request: AssociationCorrectRequest | AssociationEndRequest | MembershipCorrectRequest,
) -> dict[str, object]:
    return {
        "link_id": request.link_id,
        "expected_revision": request.expected_revision,
        "reason": request.reason,
        "evidence_anchors": anchor_inputs_document(request.evidence_anchors),
    }


# ---------------------------------------------------------------------- views


def evidence_availability(
    anchor: EvidenceAnchor, archived: Collection[str]
) -> EvidenceAvailability:
    """Section 7.1 (F19): computed at read time, never written back."""
    if anchor.source_family is EvidenceSourceFamily.MEETING_NOTE_VERSION:
        return EvidenceAvailability.AVAILABLE
    if anchor.source_root_id in archived:
        return EvidenceAvailability.ARCHIVED
    if anchor.source_version_kind is SourceVersionKind.LEGACY_UNVERSIONED:
        return EvidenceAvailability.LEGACY_UNVERSIONED
    return EvidenceAvailability.AVAILABLE


def anchor_view(cited: LineageLinkEvidence, archived: Collection[str]) -> EvidenceAnchorView:
    """One cited anchor's view, its availability computed against the archive set now."""
    anchor = cited.anchor
    return EvidenceAnchorView(
        anchor_id=cited.anchor_id,
        family=anchor.source_family,
        root_id=anchor.source_root_id,
        version_kind=anchor.source_version_kind,
        version_id=anchor.source_version_id,
        source_version_no=anchor.source_version_no,
        passage_start_cp=anchor.passage_start_cp,
        passage_end_cp=anchor.passage_end_cp,
        role=anchor.role,
        availability=evidence_availability(anchor, archived),
    )


def member_native_version(endpoint: LineageEndpoint) -> int | None:
    """The native `version` a membership revision records (S2 section 3.3).

    A Task, Commitment or Constraint member's `version`, read under the
    writer's `FOR SHARE`; `None` for every other family.
    """
    if endpoint.family in VERSIONED_MEMBER_FAMILIES:
        return endpoint.native_version
    return None


def _ref_view(ref: RecordRef) -> RecordRefView:
    return RecordRefView(family=ref.family, record_id=ref.record_id)


def association_view(
    link: RecordLinkRecord, revision: LinkRevisionRecord, archived: Collection[str]
) -> AssociationView:
    """One link at one revision, from immutable rows and the current archive set."""
    return AssociationView(
        link_id=link.link_id,
        kind=link.kind,
        relation_type=link.relation_type,
        from_ref=_ref_view(link.from_ref),
        to_ref=_ref_view(link.to_ref),
        member_role=link.member_role,
        context_issue_id=link.context_issue_id,
        revision_no=revision.revision_no,
        lifecycle_state=revision.lifecycle_state,
        acceptance_basis=revision.acceptance_basis,
        authority_class=revision.authority_class,
        evidence=tuple(anchor_view(cited, archived) for cited in revision.evidence),
        created_at=link.created_at,
        recorded_at=revision.recorded_at,
    )


def _capture_roots(revisions: Iterable[LinkRevisionRecord]) -> frozenset[str]:
    return frozenset(
        cited.anchor.source_root_id
        for revision in revisions
        for cited in revision.evidence
        if cited.anchor.source_family is not EvidenceSourceFamily.MEETING_NOTE_VERSION
    )


def _views(
    lineage: RecordLineageRepository,
    principal_id: str,
    pairs: Sequence[tuple[RecordLinkRecord, LinkRevisionRecord]],
) -> tuple[AssociationView, ...]:
    archived = lineage.archived_capture_roots(
        principal_id, _capture_roots(revision for _, revision in pairs)
    )
    return tuple(association_view(link, revision, archived) for link, revision in pairs)


def _revision_of(
    lineage: RecordLineageRepository, principal_id: str, link_id: str, revision_no: int
) -> LinkRevisionRecord:
    revision = lineage.read_revision(principal_id, link_id, revision_no)
    if revision is None:
        raise RepositoryFailureError
    return revision


def _head_views(
    lineage: RecordLineageRepository, principal_id: str, heads: Sequence[LinkHeadRecord]
) -> tuple[AssociationView, ...]:
    return _views(
        lineage,
        principal_id,
        [
            (head.link, _revision_of(lineage, principal_id, head.link.link_id, head.revision_no))
            for head in heads
        ],
    )


def _replayed(
    uow: UnitOfWork, principal_id: str, prior: LineageWriteRequestRecord
) -> AssociationResult:
    """Section 6.3 replay: the stored root and revision, never current state."""
    lineage = uow.record_lineage
    if prior.result_link_id is None or prior.result_link_revision_no is None:
        raise RepositoryFailureError
    link = lineage.read_link(principal_id, prior.result_link_id)
    if link is None:
        raise RepositoryFailureError
    revision = _revision_of(lineage, principal_id, link.link_id, prior.result_link_revision_no)
    (view,) = _views(lineage, principal_id, [(link, revision)])
    return AssociationResult(association=view, created=prior.result_created, replayed=True)


# ---------------------------------------------------------------- the service


@dataclass(frozen=True, slots=True)
class RecordLineageApplication:
    """The five link writes, the reverse read and an Issue's memberships."""

    # --- issues.memberships.add / records.associations.assert -----------------

    def add_membership(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: MembershipAddRequest,
        idempotency_key: str,
        authority: LineageAuthority,
        now: datetime,
    ) -> AssociationResult:
        """An Issue membership of a non-Project record, or the active one it repeats."""
        at = ensure_utc(now)
        issues, lineage = uow.issues, uow.record_lineage
        digest = request_digest(_MEMBERSHIP_ADD, principal_id, _membership_add_document(request))
        prior = issues.reserve_write_request(
            principal_id, _MEMBERSHIP_ADD, idempotency_key, digest, created_at=at
        )
        if prior is not None:
            return _replayed(uow, principal_id, prior)
        issue_ref = RecordRef(family=RecordFamily.SITUATION, record_id=request.issue_id)
        kind = relation_kind(RelationType.ISSUE_MEMBER, issue_ref, request.member)
        locked = lock_lineage_sources(
            issues,
            lineage,
            principal_id,
            issue_ids=((request.issue_id, SafeDetail.ISSUE_ID),),
            endpoints=((request.member, SafeDetail.MEMBER),),
            anchors=request.evidence_anchors,
        )
        require_open_issues(locked)
        member = locked.endpoints[request.member]
        require_linkable(issues, principal_id, member)
        anchors = admit_evidence_set(issues, principal_id, locked.evidence)
        identity = normalized_identity(
            kind=kind,
            relation_type=RelationType.ISSUE_MEMBER,
            from_ref=issue_ref,
            to_ref=request.member,
            member_role=request.role,
            context_issue_id=request.issue_id,
        )
        root = RecordLinkRecord(
            link_id=issue_identifier(IdKind.RECORD_LINK),
            kind=kind,
            from_ref=issue_ref,
            to_ref=request.member,
            relation_type=RelationType.ISSUE_MEMBER,
            member_role=request.role,
            context_issue_id=request.issue_id,
            normalized_identity=identity,
            authority_class=authority.authority_class.value,
            decision_channel=authority.decision_channel.value,
            source_capability=_MEMBERSHIP_ADD,
            created_at=at,
        )
        return self._assert_root(
            uow,
            principal_id,
            _MEMBERSHIP_ADD,
            idempotency_key,
            digest,
            root,
            anchors,
            at,
            member_version=member_native_version(member),
        )

    def assert_association(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: AssociationAssertRequest,
        idempotency_key: str,
        authority: LineageAuthority,
        now: datetime,
    ) -> AssociationResult:
        """A semantic association, or the active one with the same identity."""
        at = ensure_utc(now)
        issues, lineage = uow.issues, uow.record_lineage
        digest = request_digest(_ASSERT, principal_id, _assert_document(request))
        prior = issues.reserve_write_request(
            principal_id, _ASSERT, idempotency_key, digest, created_at=at
        )
        if prior is not None:
            return _replayed(uow, principal_id, prior)
        kind = relation_kind(request.relation_type, request.from_ref, request.to_ref)
        if kind is not RecordLinkKind.SEMANTIC or request.relation_type in COMPOSITE_ONLY_RELATIONS:
            # `issue_member`, and (S2 section 3.1) `delegated_from` and
            # `created_to_resolve`, which only the creating transaction attests.
            raise InvalidRequestError(SafeDetail.RELATION_TYPE)
        if request.relation_type in _NOT_YET_ASSERTABLE:
            # S2 section 3.1's `escalated_from` and `blocks` rules (Project
            # qualification, cycle refusal) are not implemented in this
            # change; until they are, both are refused rather than admitted
            # without them.
            raise InvalidRequestError(SafeDetail.RELATION_TYPE)
        context = request.context_issue_id
        if (
            context is not None
            and request.relation_type is RelationType.DISCUSSES
            and request.to_ref.family is RecordFamily.SITUATION
            and context != request.to_ref.record_id
        ):
            raise InvalidRequestError(SafeDetail.CONTEXT_ISSUE_ID)
        locked = lock_lineage_sources(
            issues,
            lineage,
            principal_id,
            issue_ids=() if context is None else ((context, SafeDetail.CONTEXT_ISSUE_ID),),
            endpoints=(
                (request.from_ref, SafeDetail.FROM_RECORD),
                (request.to_ref, SafeDetail.TO_RECORD),
            ),
            anchors=request.evidence_anchors,
        )
        require_open_issues(locked)
        for ref in (request.from_ref, request.to_ref):
            require_linkable(issues, principal_id, locked.endpoints[ref])
        anchors = admit_evidence_set(issues, principal_id, locked.evidence)
        require_relation_evidence(request.relation_type, request.from_ref, request.to_ref, anchors)
        identity = normalized_identity(
            kind=kind,
            relation_type=request.relation_type,
            from_ref=request.from_ref,
            to_ref=request.to_ref,
            member_role=None,
            context_issue_id=context,
        )
        root = RecordLinkRecord(
            link_id=issue_identifier(IdKind.RECORD_LINK),
            kind=kind,
            from_ref=request.from_ref,
            to_ref=request.to_ref,
            relation_type=request.relation_type,
            member_role=None,
            context_issue_id=context,
            normalized_identity=identity,
            authority_class=authority.authority_class.value,
            decision_channel=authority.decision_channel.value,
            source_capability=_ASSERT,
            created_at=at,
        )
        return self._assert_root(
            uow, principal_id, _ASSERT, idempotency_key, digest, root, anchors, at
        )

    @staticmethod
    def _assert_root(
        uow: UnitOfWork,
        principal_id: str,
        capability: str,
        idempotency_key: str,
        digest: str,
        root: RecordLinkRecord,
        anchors: tuple[EvidenceAnchor, ...],
        at: datetime,
        *,
        member_version: int | None = None,
    ) -> AssociationResult:
        """Section 6.2 steps 4 and 5, then the writes: a new root, or the active one.

        `member_version` is the member's observed native `version` a new
        membership's revision 1 records (S2 section 3.3); `None` otherwise.
        """
        issues, lineage = uow.issues, uow.record_lineage
        lineage.lock_identity(principal_id, root.normalized_identity)
        existing = lineage.active_head_by_identity(principal_id, root.normalized_identity)
        if existing is not None:
            # The active link with this meaning answers; its authority and
            # evidence never change, and only the request row is written.
            revision = _revision_of(
                lineage, principal_id, existing.link.link_id, existing.revision_no
            )
            issues.complete_write_request(
                principal_id,
                capability,
                idempotency_key,
                request_digest=digest,
                completed_at=at,
                result_link_id=existing.link.link_id,
                result_link_revision_no=existing.revision_no,
                result_created=False,
            )
            (view,) = _views(lineage, principal_id, [(existing.link, revision)])
            return AssociationResult(association=view, created=False, replayed=False)
        revision = LinkRevisionRecord(
            link_id=root.link_id,
            revision_no=1,
            revision_id=issue_identifier(IdKind.RECORD_LINK_REVISION),
            predecessor_revision_no=None,
            action=LinkRevisionAction.ASSERT,
            lifecycle_state=LinkLifecycleState.ACTIVE,
            acceptance_basis=AcceptanceBasis.USER_CONFIRMED,
            authority_class=root.authority_class,
            decision_channel=root.decision_channel,
            source_capability=capability,
            reason=None,
            evidence_set_digest=evidence_set_digest(anchors),
            recorded_at=at,
            evidence=_inserted(issues, principal_id, anchors, at),
            member_native_version=member_version,
        )
        lineage.insert_link(principal_id, root, revision)
        issues.complete_write_request(
            principal_id,
            capability,
            idempotency_key,
            request_digest=digest,
            completed_at=at,
            result_link_id=root.link_id,
            result_link_revision_no=1,
            result_created=True,
        )
        (view,) = _views(lineage, principal_id, [(root, revision)])
        return AssociationResult(association=view, created=True, replayed=False)

    # --- issues.memberships.end / records.associations.correct / .end ---------

    def end_membership(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: MembershipEndRequest,
        idempotency_key: str,
        authority: LineageAuthority,
        now: datetime,
    ) -> AssociationResult:
        """End an active Issue membership at its expected revision."""
        digest = request_digest(_MEMBERSHIP_END, principal_id, _membership_end_document(request))
        return self._revise(
            uow,
            principal_id,
            capability=_MEMBERSHIP_END,
            kind=RecordLinkKind.ISSUE_MEMBERSHIP,
            action=LinkRevisionAction.END,
            link_id=request.link_id,
            expected_revision=request.expected_revision,
            reason=request.reason,
            evidence=(),
            idempotency_key=idempotency_key,
            digest=digest,
            authority=authority,
            now=now,
        )

    def correct_membership(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: MembershipCorrectRequest,
        idempotency_key: str,
        authority: LineageAuthority,
        now: datetime,
    ) -> AssociationResult:
        """Replace a membership's evidence set (S2 section 7.2); root, role and identity stay.

        The set is the complete new set (0..32, any role) and differs from the
        head's, except the section 3.3 re-affirmation. The revision records the
        member's native `version` observed now.
        """
        digest = request_digest(_MEMBERSHIP_CORRECT, principal_id, _revise_document(request))
        return self._revise(
            uow,
            principal_id,
            capability=_MEMBERSHIP_CORRECT,
            kind=RecordLinkKind.ISSUE_MEMBERSHIP,
            action=LinkRevisionAction.CORRECT_EVIDENCE,
            link_id=request.link_id,
            expected_revision=request.expected_revision,
            reason=request.reason,
            evidence=request.evidence_anchors,
            idempotency_key=idempotency_key,
            digest=digest,
            authority=authority,
            now=now,
        )

    def correct_association(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: AssociationCorrectRequest,
        idempotency_key: str,
        authority: LineageAuthority,
        now: datetime,
    ) -> AssociationResult:
        """Replace a semantic association's evidence set; the root never changes."""
        digest = request_digest(_CORRECT, principal_id, _revise_document(request))
        return self._revise(
            uow,
            principal_id,
            capability=_CORRECT,
            kind=RecordLinkKind.SEMANTIC,
            action=LinkRevisionAction.CORRECT_EVIDENCE,
            link_id=request.link_id,
            expected_revision=request.expected_revision,
            reason=request.reason,
            evidence=request.evidence_anchors,
            idempotency_key=idempotency_key,
            digest=digest,
            authority=authority,
            now=now,
        )

    def end_association(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: AssociationEndRequest,
        idempotency_key: str,
        authority: LineageAuthority,
        now: datetime,
    ) -> AssociationResult:
        """End a semantic association; an ended link is terminal in S1."""
        digest = request_digest(_END, principal_id, _revise_document(request))
        return self._revise(
            uow,
            principal_id,
            capability=_END,
            kind=RecordLinkKind.SEMANTIC,
            action=LinkRevisionAction.END,
            link_id=request.link_id,
            expected_revision=request.expected_revision,
            reason=request.reason,
            evidence=request.evidence_anchors,
            idempotency_key=idempotency_key,
            digest=digest,
            authority=authority,
            now=now,
        )

    @staticmethod
    def _revise(
        uow: UnitOfWork,
        principal_id: str,
        *,
        capability: str,
        kind: RecordLinkKind,
        action: LinkRevisionAction,
        link_id: str,
        expected_revision: int,
        reason: str,
        evidence: tuple[EvidenceAnchorInput, ...],
        idempotency_key: str,
        digest: str,
        authority: LineageAuthority,
        now: datetime,
    ) -> AssociationResult:
        at = ensure_utc(now)
        issues, lineage = uow.issues, uow.record_lineage
        prior = issues.reserve_write_request(
            principal_id, capability, idempotency_key, digest, created_at=at
        )
        if prior is not None:
            return _replayed(uow, principal_id, prior)
        link = lineage.read_link(principal_id, link_id)
        if link is None:
            raise NotFoundError(SafeDetail.LINK_ID)
        if link.kind is not kind:
            # A membership id given to `records.associations.*`, or a semantic
            # link id given to `issues.memberships.end`/`.correct`.
            raise InvalidRequestError(SafeDetail.LINK_ID)
        records_member = capability == _MEMBERSHIP_CORRECT
        locked = lock_lineage_sources(
            issues,
            lineage,
            principal_id,
            # S2 section 6.2 step 3: the owning or context Issue, and an Issue
            # endpoint, so a revision serializes with `issues.close`.
            issue_ids=_named_issues(link),
            # The member's native row, to read the version it records.
            endpoints=((link.to_ref, SafeDetail.MEMBER),) if records_member else (),
            anchors=evidence,
        )
        require_open_issues(locked)
        observed = member_native_version(locked.endpoints[link.to_ref]) if records_member else None
        lineage.lock_identity(principal_id, link.normalized_identity)
        head = lineage.lock_head(principal_id, link_id)
        if head is None:
            raise RepositoryFailureError
        if (
            head.revision_no != expected_revision
            or head.lifecycle_state is not LinkLifecycleState.ACTIVE
        ):
            raise ConflictError(SafeDetail.STALE_VERSION)
        anchors = admit_evidence_set(issues, principal_id, locked.evidence)
        digest_of_set = evidence_set_digest(anchors)
        if action is LinkRevisionAction.CORRECT_EVIDENCE:
            require_relation_evidence(link.relation_type, link.from_ref, link.to_ref, anchors)
            current = _revision_of(lineage, principal_id, link_id, head.revision_no)
            # S2 section 3.3 re-affirmation: the same set again, with a
            # `resolution` anchor, once the member's native version has moved.
            reaffirmed = (
                records_member
                and current.member_native_version != observed
                and has_resolution_anchor(anchors)
            )
            if current.evidence_set_digest == digest_of_set and not reaffirmed:
                raise InvalidRequestError(SafeDetail.EVIDENCE_ANCHORS)
        revision = LinkRevisionRecord(
            link_id=link_id,
            revision_no=head.revision_no + 1,
            revision_id=issue_identifier(IdKind.RECORD_LINK_REVISION),
            predecessor_revision_no=head.revision_no,
            action=action,
            lifecycle_state=(
                LinkLifecycleState.ENDED
                if action is LinkRevisionAction.END
                else LinkLifecycleState.ACTIVE
            ),
            acceptance_basis=AcceptanceBasis.USER_CONFIRMED,
            authority_class=authority.authority_class.value,
            decision_channel=authority.decision_channel.value,
            source_capability=capability,
            reason=reason,
            evidence_set_digest=digest_of_set,
            recorded_at=at,
            evidence=_inserted(issues, principal_id, anchors, at),
            member_native_version=observed,
        )
        lineage.append_revision(principal_id, revision)
        issues.complete_write_request(
            principal_id,
            capability,
            idempotency_key,
            request_digest=digest,
            completed_at=at,
            result_link_id=link_id,
            result_link_revision_no=revision.revision_no,
        )
        (view,) = _views(lineage, principal_id, [(link, revision)])
        return AssociationResult(association=view, created=None, replayed=False)

    # --- reads ------------------------------------------------------------------

    def memberships(
        self, uow: UnitOfWork, principal_id: str, issue_id: str
    ) -> tuple[tuple[AssociationView, ...], bool]:
        """An Issue's active memberships (at most 100) and whether more exist."""
        lineage = uow.record_lineage
        heads = lineage.issue_memberships(principal_id, issue_id, limit=MAX_ISSUE_MEMBERSHIPS + 1)
        shown = heads[:MAX_ISSUE_MEMBERSHIPS]
        return _head_views(lineage, principal_id, shown), len(heads) > MAX_ISSUE_MEMBERSHIPS

    def read_lineage(
        self, uow: UnitOfWork, principal_id: str, request: LineageReadRequest
    ) -> LineageView:
        """`records.lineage` (section 7.2)."""
        return traverse_lineage(uow.record_lineage, principal_id, request)


def _named_issues(link: RecordLinkRecord) -> tuple[tuple[str, SafeDetail], ...]:
    """The Issues a link names: its owner or context, and any Issue endpoint, once each."""
    named: dict[str, SafeDetail] = {}
    if link.context_issue_id is not None:
        named[link.context_issue_id] = (
            SafeDetail.ISSUE_ID
            if link.kind is RecordLinkKind.ISSUE_MEMBERSHIP
            else SafeDetail.CONTEXT_ISSUE_ID
        )
    for ref, detail in (
        (link.from_ref, SafeDetail.FROM_RECORD),
        (link.to_ref, SafeDetail.TO_RECORD),
    ):
        if ref.family is RecordFamily.SITUATION:
            named.setdefault(ref.record_id, detail)
    return tuple(named.items())


def _inserted(
    issues: IssueRepository, principal_id: str, anchors: Sequence[EvidenceAnchor], at: datetime
) -> tuple[LineageLinkEvidence, ...]:
    """Reuse-or-insert each anchor in canonical order (section 5.1 anchor writes)."""
    return tuple(
        LineageLinkEvidence(
            anchor_id=insert_evidence_anchor(issues, principal_id, anchor, recorded_at=at),
            anchor=anchor,
        )
        for anchor in anchors
    )


# ----------------------------------------------------------- the reverse read


def _pair_extension(
    ref: RecordRef,
    resolved: Mapping[RecordRef, LineageResolvedRecord],
    notes_by_meeting: Mapping[str, Sequence[RecordRef]],
) -> tuple[RecordRef, ...]:
    """The record's pair set: itself, its Meeting, or its Meeting's note versions."""
    if ref.family is RecordFamily.MEETING_NOTE_VERSION:
        record = resolved.get(ref)
        if record is not None and record.meeting_id is not None:
            return (ref, RecordRef(family=RecordFamily.MEETING, record_id=record.meeting_id))
        return (ref,)
    if ref.family is RecordFamily.MEETING:
        return (ref, *notes_by_meeting.get(ref.record_id, ()))
    return (ref,)


def _is_issue(ref: RecordRef, resolved: Mapping[RecordRef, LineageResolvedRecord]) -> bool:
    record = resolved.get(ref)
    return (
        ref.family is RecordFamily.SITUATION
        and record is not None
        and record.situation_kind is SituationKind.ISSUE_WORKSTREAM
    )


@dataclass(slots=True)
class _Budget:
    nodes: int = 0
    edges: int = 0
    size: int = 0
    exhausted: bool = False

    def admit(self, *, nodes: int = 0, edges: int = 0, size: int = 0) -> bool:
        if self.exhausted:
            return False
        if (
            self.nodes + nodes > MAX_LINEAGE_NODES
            or self.edges + edges > MAX_LINEAGE_EDGES
            or self.size + size > MAX_LINEAGE_BYTES
        ):
            self.exhausted = True
            return False
        self.nodes += nodes
        self.edges += edges
        self.size += size
        return True


def _size(document: object) -> int:
    return len(json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8"))


class _Graph:
    """The traversal state of one `records.lineage` read."""

    def __init__(self, source: RecordLineageRepository, principal_id: str, root: RecordRef) -> None:
        self.source = source
        self.owner = principal_id
        self.budget = _Budget()
        self.depth: dict[RecordRef, int] = {}
        self.order: list[RecordRef] = []
        self.links: dict[str, LinkHeadRecord] = {}
        self.resolved: dict[RecordRef, LineageResolvedRecord] = {}
        self.notes: dict[str, tuple[RecordRef, ...]] = {}
        self.note_numbers: dict[RecordRef, int] = {}
        self.root = root

    def resolve(self, refs: Iterable[RecordRef]) -> None:
        missing = {ref for ref in refs if ref not in self.resolved}
        if missing:
            self.resolved.update(self.source.resolve_records(self.owner, missing))

    def load_notes(self, meeting_ids: Iterable[str]) -> None:
        missing = {meeting_id for meeting_id in meeting_ids if meeting_id not in self.notes}
        if not missing:
            return
        found = self.source.note_versions_of(self.owner, missing)
        for meeting_id in missing:
            versions = found.get(meeting_id, ())
            self.notes[meeting_id] = tuple(
                RecordRef(family=RecordFamily.MEETING_NOTE_VERSION, record_id=note.note_version_id)
                for note in versions
            )
            for note in versions:
                ref = RecordRef(
                    family=RecordFamily.MEETING_NOTE_VERSION, record_id=note.note_version_id
                )
                self.note_numbers[ref] = note.version_number
                self.resolved.setdefault(
                    ref, LineageResolvedRecord(ref=ref, meeting_id=note.meeting_id)
                )

    def extension(self, ref: RecordRef) -> tuple[RecordRef, ...]:
        self.resolve((ref,))
        if ref.family is RecordFamily.MEETING:
            self.load_notes((ref.record_id,))
        return _pair_extension(ref, self.resolved, self.notes)

    def reach(self, ref: RecordRef, depth: int) -> bool:
        """Add a node at `depth` unless it is reached already or the budget is spent."""
        if ref in self.depth:
            return True
        if not self.budget.admit(nodes=1, size=_size(_ref_document(ref)) + 64):
            return False
        self.depth[ref] = depth
        self.order.append(ref)
        return True

    def follow(self, head: LinkHeadRecord) -> bool:
        if head.link.link_id in self.links:
            return True
        if not self.budget.admit(edges=1, size=_EDGE_ESTIMATE):
            return False
        self.links[head.link.link_id] = head
        return True


def _matching_issues(graph: _Graph, pair: Sequence[RecordRef]) -> list[str]:
    """Section 7.2 step 2 over the root's pair set."""
    matching: set[str] = set()
    if _is_issue(graph.root, graph.resolved):
        matching.add(graph.root.record_id)
    pair_set = set(pair)
    for head in graph.source.active_links_incident(graph.owner, pair_set):
        link = head.link
        if link.kind is RecordLinkKind.ISSUE_MEMBERSHIP:
            if link.to_ref in pair_set:
                matching.add(link.from_ref.record_id)
            continue
        if link.context_issue_id is not None:
            matching.add(link.context_issue_id)
        if (
            link.relation_type is RelationType.DISCUSSES
            and link.from_ref in pair_set
            and link.to_ref.family is RecordFamily.SITUATION
        ):
            matching.add(link.to_ref.record_id)
    refs = [RecordRef(family=RecordFamily.SITUATION, record_id=issue_id) for issue_id in matching]
    graph.resolve(refs)
    return sorted(ref.record_id for ref in refs if _is_issue(ref, graph.resolved))


def _members_in(graph: _Graph, issue_id: str) -> set[RecordRef]:
    """*I*, its active members, and every member of an active member's pair set."""
    issue = RecordRef(family=RecordFamily.SITUATION, record_id=issue_id)
    inside = {issue}
    members = [
        head.link.to_ref
        for head in graph.source.active_links_incident(graph.owner, (issue,))
        if head.link.kind is RecordLinkKind.ISSUE_MEMBERSHIP and head.link.from_ref == issue
    ]
    for member in members:
        inside.update(graph.extension(member))
    return inside


def _followable(head: LinkHeadRecord, issue_id: str, inside: Collection[RecordRef]) -> bool:
    """Section 7.2 step 4: the links *I*'s traversal follows."""
    link = head.link
    issue = RecordRef(family=RecordFamily.SITUATION, record_id=issue_id)
    if link.kind is RecordLinkKind.ISSUE_MEMBERSHIP:
        return link.from_ref == issue
    if link.context_issue_id is not None:
        return link.context_issue_id == issue_id
    if issue in (link.from_ref, link.to_ref):
        return True
    return link.from_ref in inside and link.to_ref in inside


def _expand(graph: _Graph, issue_id: str, max_depth: int) -> None:
    """Section 7.2 step 4: breadth-first from the root under *I*."""
    inside = _members_in(graph, issue_id)
    frontier = [graph.root]
    depth = 0
    while frontier and depth < max_depth and not graph.budget.exhausted:
        nxt: list[RecordRef] = []
        for node in sorted(frontier, key=lambda ref: (ref.family.value, ref.record_id)):
            extension = graph.extension(node)
            incident = graph.source.active_links_incident(graph.owner, extension)
            for head in incident:
                if not _followable(head, issue_id, inside):
                    continue
                link = head.link
                near = link.from_ref if link.from_ref in extension else link.to_ref
                far = link.to_ref if near == link.from_ref else link.from_ref
                if not graph.follow(head):
                    return
                for ref in (near, far):
                    if ref not in graph.depth:
                        if not graph.reach(ref, depth + 1):
                            return
                        nxt.append(ref)
            if node.family is RecordFamily.MEETING_NOTE_VERSION:
                meeting = graph.resolved.get(node)
                if meeting is not None and meeting.meeting_id is not None:
                    parent = RecordRef(family=RecordFamily.MEETING, record_id=meeting.meeting_id)
                    if parent not in graph.depth:
                        if not graph.reach(parent, depth + 1):
                            return
                        nxt.append(parent)
        frontier = nxt
        depth += 1


def _one_hop(graph: _Graph, max_depth: int) -> None:
    """Section 7.2 step 3, no Issue: context-free semantic links at the root, one hop."""
    if max_depth < 1:
        return
    root = graph.root
    for head in graph.source.active_links_incident(graph.owner, (root,)):
        link = head.link
        if link.kind is not RecordLinkKind.SEMANTIC or link.context_issue_id is not None:
            continue
        far = link.to_ref if link.from_ref == root else link.from_ref
        if not graph.follow(head) or not graph.reach(far, 1):
            return
    if root.family is RecordFamily.MEETING_NOTE_VERSION:
        record = graph.resolved.get(root)
        if record is not None and record.meeting_id is not None:
            graph.reach(RecordRef(family=RecordFamily.MEETING, record_id=record.meeting_id), 1)


def _virtual_edges(graph: _Graph, nodes: Collection[RecordRef]) -> list[VirtualEdgeView]:
    """Every `meeting_note_version_of` edge touching a reached node, by version number."""
    meetings: set[str] = set()
    for ref in nodes:
        if ref.family is RecordFamily.MEETING:
            meetings.add(ref.record_id)
        elif ref.family is RecordFamily.MEETING_NOTE_VERSION:
            record = graph.resolved.get(ref)
            if record is not None and record.meeting_id is not None:
                meetings.add(record.meeting_id)
    graph.load_notes(meetings)
    edges: list[tuple[str, int, VirtualEdgeView]] = []
    for meeting_id in sorted(meetings):
        meeting = RecordRef(family=RecordFamily.MEETING, record_id=meeting_id)
        for note in graph.notes.get(meeting_id, ()):
            if meeting not in nodes and note not in nodes:
                continue
            if not graph.budget.admit(edges=1, size=256):
                return [edge for _, _, edge in sorted(edges, key=lambda item: item[:2])]
            edges.append(
                (
                    meeting_id,
                    graph.note_numbers.get(note, 0),
                    VirtualEdgeView(
                        edge_type=NativeVirtualEdge.MEETING_NOTE_VERSION_OF,
                        from_ref=_ref_view(note),
                        to_ref=_ref_view(meeting),
                    ),
                )
            )
    return [edge for _, _, edge in sorted(edges, key=lambda item: item[:2])]


def _node_view(ref: RecordRef, depth: int, record: LineageResolvedRecord) -> LineageNodeView:
    return LineageNodeView(
        family=ref.family,
        record_id=ref.record_id,
        depth=depth,
        meeting_id=record.meeting_id if ref.family is RecordFamily.MEETING_NOTE_VERSION else None,
        title=record.title if ref.family is RecordFamily.SITUATION else None,
        state=record.state if ref.family is RecordFamily.SITUATION else None,  # type: ignore[arg-type]
        availability=(
            ("archived" if record.capture_archived else "available")
            if ref.family is RecordFamily.CAPTURE_VERSION
            else None
        ),
    )


def traverse_lineage(
    source: RecordLineageRepository, principal_id: str, request: LineageReadRequest
) -> LineageView:
    """`records.lineage` over a lineage source (section 7.2 steps 1 to 7)."""
    root = request.origin
    graph = _Graph(source, principal_id, root)
    graph.resolve((root,))
    if root not in graph.resolved:
        raise NotFoundError(SafeDetail.ORIGIN)
    if root.family is RecordFamily.SITUATION and not _is_issue(root, graph.resolved):
        raise InvalidRequestError(SafeDetail.ORIGIN)
    pair = graph.extension(root)
    graph.resolve(pair)
    matching = _matching_issues(graph, pair)
    graph.reach(root, 0)
    selected: str | None = None
    completeness = LineageCompleteness.COMPLETE
    if request.issue_id is not None:
        if request.issue_id not in matching:
            raise NotFoundError(SafeDetail.ISSUE_ID)
        selected = request.issue_id
    elif len(matching) == 1:
        selected = matching[0]
    elif len(matching) > 1:
        completeness = LineageCompleteness.UNRESOLVED_AMBIGUITY
    if selected is not None:
        _expand(graph, selected, request.max_depth)
    elif completeness is LineageCompleteness.COMPLETE:
        _one_hop(graph, request.max_depth)
    # Step 5: re-resolve every reached node natively; drop what no longer resolves.
    reached = list(graph.order)
    fresh = source.resolve_records(principal_id, reached)
    dropped = {ref for ref in reached if ref not in fresh}
    graph.resolved.update(fresh)
    nodes = [ref for ref in reached if ref not in dropped]
    heads = [
        head
        for head in graph.links.values()
        if head.link.from_ref not in dropped and head.link.to_ref not in dropped
    ]
    virtual = _virtual_edges(graph, set(nodes))
    if graph.budget.exhausted:
        completeness = LineageCompleteness.TRUNCATED_BUDGET
    elif dropped and completeness is LineageCompleteness.COMPLETE:
        completeness = LineageCompleteness.PARTIAL_NATIVE_HISTORY
    issue_refs = [RecordRef(family=RecordFamily.SITUATION, record_id=issue) for issue in matching]
    graph.resolve(issue_refs)
    matches = tuple(
        LineageIssueMatch(
            issue_id=ref.record_id,
            title=graph.resolved[ref].title or "",
            state=graph.resolved[ref].state,  # type: ignore[arg-type]
        )
        for ref in issue_refs[:MAX_MATCHING_ISSUES]
    )
    edges = list(
        _head_views(source, principal_id, sorted(heads, key=lambda head: head.link.link_id))
    )
    node_views = tuple(
        _node_view(ref, graph.depth[ref], graph.resolved[ref])
        for ref in sorted(
            nodes, key=lambda ref: (graph.depth[ref], ref.family.value, ref.record_id)
        )
    )
    while True:
        view = LineageView(
            root=_ref_view(root),
            selected_issue_id=selected,
            issues_matching_root=matches,
            nodes=node_views,
            typed_edges=tuple(edges),
            virtual_native_edges=tuple(virtual),
            complete_state=completeness,
        )
        # Step 6, the serialized budget: the per-item estimates above stop
        # expansion early; this is the exact bound on what is returned.
        if _size(view.to_canonical_dict()) <= MAX_LINEAGE_BYTES or not (edges or virtual):
            return view
        completeness = LineageCompleteness.TRUNCATED_BUDGET
        if virtual:
            virtual.pop()
        else:
            edges.pop()
