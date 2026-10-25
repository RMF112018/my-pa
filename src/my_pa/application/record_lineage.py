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
moved; and `records.associations.assert` refuses the composite-only relations
and admits `escalated_from` (Issue-scoped, Project-qualified, after its Task)
and `blocks` (no self-loop; a bounded cycle search under the Principal's
`:blocks` advisory key).

**S3** (S3 contract sections 3.1, 3.2, 6.2 and 7.4): `records.associations.contest`
and `.reinstate` move a semantic link between `active` and `contested` under
the transition table (`domain.lineage.closure.link_transition`); a contest
needs an exact `contradicts` anchor and a reinstate re-applies the relation's
own evidence rule. A contested link keeps its identity, so an assert of it is
`conflict` / `state`. `related_context` is asserted Issue-scoped, with both
endpoints inside the context Issue and an exact `corroborates` anchor, stored
once in canonical order. Every semantic revision takes `FOR SHARE` on every
Issue the link is in the context of (section 3.2's one predicate,
`issues_in_context_of`) -- including the Issues a null-context link lies
inside -- and a closed one refuses it (`conflict` / `state`), so a closed
Issue never acquires or loses a dispute.

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

import hashlib
import json
import re
import time
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from my_pa.application.errors import (
    ConflictError,
    DeniedError,
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
from my_pa.application.lineage_rate import require_client_write_budget
from my_pa.application.lineage_visibility import (
    LineageVisibility,
    lineage_visibility,
    withhold_client_ids,
)
from my_pa.contracts.ports import (
    IssueRepository,
    LineageEndpoint,
    LineageFactCut,
    LineageIssueAsOf,
    LineageLinkEvidence,
    LineageNoteVersionRef,
    LineageReadTimeoutError,
    LineageResolvedRecord,
    LineageWriteRequestRecord,
    LinkHeadRecord,
    LinkRevisionRecord,
    RecordLineageRepository,
    RecordLinkRecord,
    RepositoryFailureError,
    ReviewScopeLink,
    UnitOfWork,
)
from my_pa.contracts.v1.record_lineage import (
    MAX_ISSUE_MEMBERSHIPS,
    MAX_MATCHING_ISSUES,
    AssociationView,
    EvidenceAnchorView,
    LineageIssueMatch,
    LineageNodeView,
    LineagePathEdgeView,
    LineageView,
    LinkHistoryRevisionView,
    LinkHistoryRootView,
    RecordRefView,
    RelatedRecordsView,
    RelatedRecordView,
    VirtualEdgeView,
)
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.operation import Capability
from my_pa.domain.intelligence.source_manifest import (
    LineageRecomputeFailure,
    LineageReferenceBlock,
    lineage_section,
    lineage_server_counts,
)
from my_pa.domain.lineage.asof import (
    CutAfterNowError,
    completeness,
    effective_known_at,
    knowledge_cut,
    native_cut,
)
from my_pa.domain.lineage.canonical import (
    canonical_json,
    evidence_set_digest,
    normalized_identity,
    request_digest,
)
from my_pa.domain.lineage.closure import (
    VERSIONED_MEMBER_FAMILIES,
    has_resolution_anchor,
    in_issue_context,
    in_review_scope,
    is_contest_evidence,
    is_unreviewed,
    link_transition,
)
from my_pa.domain.lineage.cursor import (
    MAX_CURSOR_CHARACTERS,
    CursorMalformedError,
    LineageCursor,
    cursor_binding,
    decode_cursor,
    encode_cursor,
    instant_token,
    scope_digest,
)
from my_pa.domain.lineage.model import EvidenceAnchor, RecordRef
from my_pa.domain.lineage.vocabulary import (
    COMPOSITE_ONLY_RELATIONS,
    LINEAGE_RELATED_DIGEST_PREFIX,
    RECORD_FAMILY_ID_KINDS,
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
from my_pa.domain.project_controls.constraint import ConstraintLifecycleState
from my_pa.domain.source.registry import issue_identifier

if TYPE_CHECKING:
    from my_pa.application.lineage_authority import LineageAuthority, LineageProvenance

__all__ = [
    "DEFAULT_LINEAGE_DEPTH",
    "LINEAGE_DEADLINE_SECONDS",
    "LINEAGE_RECOMPUTE_BUDGET_SECONDS",
    "LINEAGE_STATEMENT_TIMEOUT_MS",
    "MAX_BLOCKS_SEARCH",
    "MAX_LINEAGE_BYTES",
    "MAX_LINEAGE_DEPTH",
    "MAX_LINEAGE_EDGES",
    "MAX_LINEAGE_NODES",
    "MAX_VISIBILITY_SCAN",
    "MEMBERSHIP_SCAN_BATCH",
    "AssociationAssertRequest",
    "AssociationCorrectRequest",
    "AssociationEndRequest",
    "AssociationHistoryRequest",
    "AssociationHistoryResult",
    "AssociationResult",
    "LineageBoundedResult",
    "LineageReadRequest",
    "LineageReportedCuts",
    "LinkConfirmRequest",
    "MembershipAddRequest",
    "MembershipCorrectRequest",
    "MembershipEndRequest",
    "RecordLineageApplication",
    "RelatedBoundedResult",
    "RelatedReadRequest",
    "anchor_view",
    "association_view",
    "association_views",
    "bounded_lineage",
    "bounded_related",
    "evidence_availability",
    "insert_new_link",
    "issue_inside_set",
    "issue_inside_set_at",
    "issues_in_context_of",
    "lineage_known_at",
    "lineage_request_document",
    "links_in_context",
    "links_in_context_at",
    "member_native_version",
    "read_lineage_as_of",
    "read_related_as_of",
    "recompute_lineage_reference",
    "related_digest",
    "related_request_document",
    "require_no_blocks_cycle",
    "traverse_lineage",
    "unreviewed_links_in_scope",
    "visible_anchor_sets",
    "visible_association_views",
]

_MEMBERSHIP_ADD: Final = Capability.ISSUES_MEMBERSHIPS_ADD.value
_MEMBERSHIP_END: Final = Capability.ISSUES_MEMBERSHIPS_END.value
_MEMBERSHIP_CORRECT: Final = Capability.ISSUES_MEMBERSHIPS_CORRECT.value
_ASSERT: Final = Capability.RECORDS_ASSOCIATIONS_ASSERT.value
_CORRECT: Final = Capability.RECORDS_ASSOCIATIONS_CORRECT.value
_END: Final = Capability.RECORDS_ASSOCIATIONS_END.value
_CONTEST: Final = Capability.RECORDS_ASSOCIATIONS_CONTEST.value
_REINSTATE: Final = Capability.RECORDS_ASSOCIATIONS_REINSTATE.value
_CONFIRM: Final = Capability.RECORDS_ASSOCIATIONS_CONFIRM.value
_MEMBERSHIP_CONFIRM: Final = Capability.ISSUES_MEMBERSHIPS_CONFIRM.value

#: `records.lineage` bounds (section 7.2; design values, not benchmarks).
MAX_LINEAGE_DEPTH: Final = 4
DEFAULT_LINEAGE_DEPTH: Final = 4
MAX_LINEAGE_NODES: Final = 250
MAX_LINEAGE_EDGES: Final = 400
MAX_LINEAGE_BYTES: Final = 512 * 1024
#: A typed edge's serialized size as the expansion estimates it before the
#: edge's evidence is read; the exact bound is applied to the finished answer.
_EDGE_ESTIMATE: Final = 768

#: S3 FR3-F08: the most entries one visibility-filtered list request reads
#: (`issues.read` memberships, `issues.handoffs.list`), at the 400-edge budget's
#: scale; and the keyset batch the membership read takes.
MAX_VISIBILITY_SCAN: Final = 400
MEMBERSHIP_SCAN_BATCH: Final = MAX_ISSUE_MEMBERSHIPS + 1

#: S2 section 3.1: the most records one `blocks` cycle search visits. A search
#: that would visit more before its frontier is exhausted refuses the assert
#: (`invalid_request` / `blocks_cycle`): an undecidable answer is a refusal.
MAX_BLOCKS_SEARCH: Final = 1000


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
class LinkConfirmRequest:
    """`records.associations.confirm` / `issues.memberships.confirm`, parsed (S3.1 7.2)."""

    link_id: str
    expected_revision: int
    reason: str


@dataclass(frozen=True, slots=True)
class LineageReadRequest:
    """`records.lineage`, parsed. S3 (section 7.2) adds the cuts and the paging fields.

    `known_at` and `valid_at` are aware instants; `page_size` is 10..100 and a
    `cursor` comes only with a `page_size` (the command checked both).
    """

    origin: RecordRef
    issue_id: str | None
    max_depth: int
    known_at: datetime | None = None
    valid_at: datetime | None = None
    page_size: int | None = None
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class AssociationResult:
    """What a link write answers. `created` is `None` for `.end` and `.correct`."""

    association: AssociationView
    created: bool | None
    replayed: bool
    #: S3.1 section 6.4: whether the answer filter withheld an anchor (remote).
    restricted: bool = False


@dataclass(frozen=True, slots=True)
class AssociationHistoryRequest:
    """`records.associations.history`, parsed (S3 section 7.3)."""

    link_id: str
    known_at: datetime | None
    page_size: int
    after: int | None


@dataclass(frozen=True, slots=True)
class AssociationHistoryResult:
    """One page of one link's revisions as known at `known_at` (`T_k`)."""

    link: LinkHistoryRootView
    known_at: datetime | None
    revisions: tuple[LinkHistoryRevisionView, ...]
    next_cursor: int | None
    #: S3 section 6.4 (FR3-F04): whether an anchor was withheld from this page.
    restricted: bool = False


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


def open_write_digest(
    capability: str,
    principal_id: str,
    document: Mapping[str, object],
    provenance: LineageProvenance,
) -> str:
    """S3.1 section 4.9: an open write's digest, binding a client writer and its claim.

    The human channel's document is exactly the S1-S4 one, so every recorded
    S1-S4 key replays byte-identically for the operator; a client's gains the
    server-only `writer` key. `user_directed` enters the request document only
    when `true`, so absent and `false` leave every existing digest unchanged.
    """
    claimed = dict(document)
    if provenance.user_directed_claim:
        claimed["user_directed"] = True
    writer = (
        None
        if provenance.acceptance_basis is AcceptanceBasis.USER_CONFIRMED
        else {
            "decision_channel": provenance.decision_channel.value,
            "asserting_client_id": provenance.asserting_client_id,
        }
    )
    return request_digest(capability, principal_id, claimed, writer=writer)


def reserve_open_write(
    issues: IssueRepository,
    principal_id: str,
    capability: str,
    idempotency_key: str,
    digest: str,
    provenance: LineageProvenance | LineageAuthority,
    at: datetime,
    *,
    asserting_client_id: str | None = None,
) -> LineageWriteRequestRecord | None:
    """Reserve a lineage write request with its writer columns (S3.1 section 5.2)."""
    client = getattr(provenance, "asserting_client_id", asserting_client_id)
    return issues.reserve_write_request(
        principal_id,
        capability,
        idempotency_key,
        digest,
        created_at=at,
        decision_channel=provenance.decision_channel.value,
        asserting_client_id=client,
    )


def require_client_may_revise(
    lineage: RecordLineageRepository,
    principal_id: str,
    head: LinkHeadRecord,
    action: LinkRevisionAction,
    provenance: LineageProvenance,
) -> None:
    """S3.1 section 4.4: a client never revises lineage the human channel accepted.

    Keyed on the link's **history**, not its head (RR1-F01): when any revision
    of the link is `user_confirmed`, a client revision is `denied`, except 1
    `contest` of an `active` link whose head is `user_confirmed` -- after
    which the head is the client's contest and only the human channel writes
    it. The caller holds the head `FOR UPDATE` and has passed the CAS check.
    """
    if provenance.acceptance_basis is not AcceptanceBasis.CLIENT_IDENTIFIED:
        return
    link_id = head.link.link_id
    if not lineage.link_confirmed(principal_id, link_id):
        return
    if action is LinkRevisionAction.CONTEST and head.lifecycle_state is LinkLifecycleState.ACTIVE:
        current = _revision_of(lineage, principal_id, link_id, head.revision_no)
        if current.acceptance_basis is AcceptanceBasis.USER_CONFIRMED:
            return
    raise DeniedError()


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
        user_directed_claim=revision.user_directed_claim,
        asserting_client_id=revision.asserting_client_id,
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


def association_views(
    lineage: RecordLineageRepository,
    principal_id: str,
    pairs: Sequence[tuple[RecordLinkRecord, LinkRevisionRecord]],
) -> tuple[AssociationView, ...]:
    """Each `(root, revision)` as an `AssociationView`, availability computed now."""
    return _views(lineage, principal_id, pairs)


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
        authority: LineageProvenance,
        now: datetime,
    ) -> AssociationResult:
        """An Issue membership of a non-Project record, or the active one it repeats."""
        at = ensure_utc(now)
        issues, lineage = uow.issues, uow.record_lineage
        digest = open_write_digest(
            _MEMBERSHIP_ADD, principal_id, _membership_add_document(request), authority
        )
        prior = reserve_open_write(
            issues, principal_id, _MEMBERSHIP_ADD, idempotency_key, digest, authority, at
        )
        if prior is not None:
            return _replayed(uow, principal_id, prior)
        # S3 section 6.2 step 1b: the commit mark, before any other lock.
        uow.record_lineage.take_commit_mark(principal_id)
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
            authority,
            member_version=member_native_version(member),
        )

    def assert_association(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: AssociationAssertRequest,
        idempotency_key: str,
        authority: LineageProvenance,
        now: datetime,
    ) -> AssociationResult:
        """A semantic association, or the active one with the same identity."""
        at = ensure_utc(now)
        issues, lineage = uow.issues, uow.record_lineage
        digest = open_write_digest(_ASSERT, principal_id, _assert_document(request), authority)
        prior = reserve_open_write(
            issues, principal_id, _ASSERT, idempotency_key, digest, authority, at
        )
        if prior is not None:
            return _replayed(uow, principal_id, prior)
        # S3 section 6.2 step 1b: the commit mark, before any other lock.
        uow.record_lineage.take_commit_mark(principal_id)
        kind = relation_kind(request.relation_type, request.from_ref, request.to_ref)
        if kind is not RecordLinkKind.SEMANTIC or request.relation_type in COMPOSITE_ONLY_RELATIONS:
            # `issue_member`, and (S2 section 3.1) `delegated_from` and
            # `created_to_resolve`, which only the creating transaction attests.
            raise InvalidRequestError(SafeDetail.RELATION_TYPE)
        context = request.context_issue_id
        if request.relation_type is RelationType.ESCALATED_FROM and context is None:
            # S2 section 3.1: an escalation is always Issue-scoped.
            raise InvalidRequestError(SafeDetail.CONTEXT_ISSUE_ID)
        if (
            context is not None
            and request.relation_type is RelationType.DISCUSSES
            and request.to_ref.family is RecordFamily.SITUATION
            and context != request.to_ref.record_id
        ):
            raise InvalidRequestError(SafeDetail.CONTEXT_ISSUE_ID)
        if request.relation_type is RelationType.RELATED_CONTEXT:
            # S3 section 3.1: always Issue-scoped, between two distinct records
            # (the command stored them in canonical order).
            if context is None:
                raise InvalidRequestError(SafeDetail.CONTEXT_ISSUE_ID)
            if request.from_ref == request.to_ref:
                raise InvalidRequestError(SafeDetail.TO_RECORD)
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
        blocks: tuple[RecordRef, RecordRef] | None = None
        if request.relation_type is RelationType.ESCALATED_FROM and context is not None:
            _require_escalation(
                uow,
                principal_id,
                context,
                locked.endpoints[request.from_ref],
                locked.endpoints[request.to_ref],
            )
        elif request.relation_type is RelationType.BLOCKS:
            if request.from_ref == request.to_ref:
                raise InvalidRequestError(SafeDetail.TO_RECORD)
            blocks = (request.from_ref, request.to_ref)
        elif request.relation_type is RelationType.RELATED_CONTEXT and context is not None:
            # S3 section 3.1: both endpoints inside the context Issue now.
            inside = issue_inside_set(lineage, principal_id, context)
            if request.from_ref not in inside:
                raise InvalidRequestError(SafeDetail.FROM_RECORD)
            if request.to_ref not in inside:
                raise InvalidRequestError(SafeDetail.TO_RECORD)
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
            uow,
            principal_id,
            _ASSERT,
            idempotency_key,
            digest,
            root,
            anchors,
            at,
            authority,
            blocks=blocks,
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
        provenance: LineageProvenance,
        *,
        member_version: int | None = None,
        blocks: tuple[RecordRef, RecordRef] | None = None,
    ) -> AssociationResult:
        """Section 6.2 steps 4 and 5, then the writes: a new root, or the active one.

        S3.1 (sections 4.5 and 6.2 step 7): an identity answered `created:
        false` keeps its provenance whoever asserts it, and -- like a new root
        -- is checked against and counted toward a client's write budgets,
        after every refusal and before its first row.

        `member_version` is the member's observed native `version` a new
        membership's revision 1 records (S2 section 3.3); `None` otherwise.
        `blocks` is a new `blocks` link's `(from, to)` (S2 section 3.1): the
        Principal's `:blocks` key is taken after the identity key (S2 section
        6.2 step 4 order), and a new link is written only when no cycle forms.
        """
        issues, lineage = uow.issues, uow.record_lineage
        lineage.lock_identity(principal_id, root.normalized_identity)
        if blocks is not None:
            lineage.lock_blocks(principal_id)
        existing = lineage.active_head_by_identity(principal_id, root.normalized_identity)
        if existing is not None and existing.lifecycle_state is LinkLifecycleState.CONTESTED:
            # S3 section 3.1: a disputed claim is never handed back as success.
            raise ConflictError(SafeDetail.STATE)
        if existing is not None:
            # The active link with this meaning answers; its authority and
            # evidence never change, and only the request row is written.
            require_client_write_budget(
                uow, principal_id, provenance, provenance.asserting_client_id, at
            )
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
        if blocks is not None:
            require_no_blocks_cycle(lineage, principal_id, *blocks)
        require_client_write_budget(
            uow, principal_id, provenance, provenance.asserting_client_id, at
        )
        revision = insert_new_link(
            uow,
            principal_id,
            root,
            anchors,
            at,
            provenance=provenance,
            member_version=member_version,
        )
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
        authority: LineageProvenance,
        now: datetime,
    ) -> AssociationResult:
        """End an active Issue membership at its expected revision."""
        digest = open_write_digest(
            _MEMBERSHIP_END, principal_id, _membership_end_document(request), authority
        )
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
        authority: LineageProvenance,
        now: datetime,
    ) -> AssociationResult:
        """Replace a membership's evidence set (S2 section 7.2); root, role and identity stay.

        The set is the complete new set (0..32, any role) and differs from the
        head's, except the section 3.3 re-affirmation. The revision records the
        member's native `version` observed now.
        """
        digest = open_write_digest(
            _MEMBERSHIP_CORRECT, principal_id, _revise_document(request), authority
        )
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
        authority: LineageProvenance,
        now: datetime,
    ) -> AssociationResult:
        """Replace a semantic association's evidence set; the root never changes."""
        digest = open_write_digest(_CORRECT, principal_id, _revise_document(request), authority)
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
        authority: LineageProvenance,
        now: datetime,
    ) -> AssociationResult:
        """End a semantic association; an ended link is terminal in S1."""
        digest = open_write_digest(_END, principal_id, _revise_document(request), authority)
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

    def contest_association(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: AssociationCorrectRequest,
        idempotency_key: str,
        authority: LineageProvenance,
        now: datetime,
    ) -> AssociationResult:
        """Dispute an active semantic association (S3 section 3.1): it reads `contested`."""
        digest = open_write_digest(_CONTEST, principal_id, _revise_document(request), authority)
        return self._revise(
            uow,
            principal_id,
            capability=_CONTEST,
            kind=RecordLinkKind.SEMANTIC,
            action=LinkRevisionAction.CONTEST,
            link_id=request.link_id,
            expected_revision=request.expected_revision,
            reason=request.reason,
            evidence=request.evidence_anchors,
            idempotency_key=idempotency_key,
            digest=digest,
            authority=authority,
            now=now,
        )

    def reinstate_association(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: AssociationCorrectRequest,
        idempotency_key: str,
        authority: LineageProvenance,
        now: datetime,
    ) -> AssociationResult:
        """Resolve a contested semantic association back to `active` (S3 section 3.1)."""
        digest = open_write_digest(_REINSTATE, principal_id, _revise_document(request), authority)
        return self._revise(
            uow,
            principal_id,
            capability=_REINSTATE,
            kind=RecordLinkKind.SEMANTIC,
            action=LinkRevisionAction.REINSTATE,
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
        authority: LineageProvenance,
        now: datetime,
    ) -> AssociationResult:
        at = ensure_utc(now)
        issues, lineage = uow.issues, uow.record_lineage
        prior = reserve_open_write(
            issues, principal_id, capability, idempotency_key, digest, authority, at
        )
        if prior is not None:
            return _replayed(uow, principal_id, prior)
        # S3 section 6.2 step 1b: the commit mark, before any other lock.
        uow.record_lineage.take_commit_mark(principal_id)
        link = lineage.read_link(principal_id, link_id)
        if link is None:
            raise NotFoundError(SafeDetail.LINK_ID)
        if link.kind is not kind:
            # A membership id given to `records.associations.*`, or a semantic
            # link id given to `issues.memberships.end`/`.correct`.
            raise InvalidRequestError(SafeDetail.LINK_ID)
        records_member = capability == _MEMBERSHIP_CORRECT
        named = _named_issues(link)
        if link.kind is RecordLinkKind.SEMANTIC:
            # S3 section 3.2: every Issue the link is in the context of, including
            # those a null-context link lies inside, so the frozen-closed rule
            # holds and a contest serializes with `issues.close`.
            already = {issue_id for issue_id, _ in named}
            named = named + tuple(
                (issue_id, SafeDetail.CONTEXT_ISSUE_ID)
                for issue_id in sorted(issues_in_context_of(lineage, principal_id, link))
                if issue_id not in already
            )
        locked = lock_lineage_sources(
            issues,
            lineage,
            principal_id,
            # S2 section 6.2 step 3: the owning or context Issue, and an Issue
            # endpoint, so a revision serializes with `issues.close`.
            issue_ids=named,
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
        if head.revision_no != expected_revision:
            raise ConflictError(SafeDetail.STALE_VERSION)
        # S3.1 section 4.4: under the head lock, after the CAS check, before
        # any row and before the rate count.
        require_client_may_revise(lineage, principal_id, head, action, authority)
        state = link_transition(action, head.lifecycle_state)
        if state is None:
            # S3 section 7.5: a contest of a non-active or a reinstate of a
            # non-contested link is `state`; S1/S2 kept `stale_version` for a
            # correction or end of a link that is no longer active.
            raise ConflictError(
                SafeDetail.STATE
                if action in (LinkRevisionAction.CONTEST, LinkRevisionAction.REINSTATE)
                else SafeDetail.STALE_VERSION
            )
        anchors = admit_evidence_set(issues, principal_id, locked.evidence)
        digest_of_set = evidence_set_digest(anchors)
        if action is LinkRevisionAction.CONTEST and not is_contest_evidence(anchors):
            raise InvalidRequestError(SafeDetail.EVIDENCE_ANCHORS)
        if action is LinkRevisionAction.REINSTATE:
            require_relation_evidence(link.relation_type, link.from_ref, link.to_ref, anchors)
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
        # S3.1 section 6.2 step 7: every refusal is behind us; the first row follows.
        require_client_write_budget(uow, principal_id, authority, authority.asserting_client_id, at)
        revision = LinkRevisionRecord(
            link_id=link_id,
            revision_no=head.revision_no + 1,
            revision_id=issue_identifier(IdKind.RECORD_LINK_REVISION),
            predecessor_revision_no=head.revision_no,
            action=action,
            lifecycle_state=state,
            acceptance_basis=authority.acceptance_basis,
            authority_class=authority.authority_class.value,
            decision_channel=authority.decision_channel.value,
            source_capability=capability,
            reason=reason,
            evidence_set_digest=digest_of_set,
            recorded_at=at,
            evidence=_inserted(issues, principal_id, anchors, at),
            member_native_version=observed,
            asserting_client_id=authority.asserting_client_id,
            user_directed_claim=authority.user_directed_claim,
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

    # --- records.associations.confirm / issues.memberships.confirm (S3.1) -------

    def confirm_link(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: LinkConfirmRequest,
        idempotency_key: str,
        authority: LineageAuthority,
        now: datetime,
        *,
        kind: RecordLinkKind,
    ) -> AssociationResult:
        """Promote a client-identified link with a `confirm` revision (S3.1 sections 4.7, 7.2).

        Attested: the handler refused every other caller before this, so the
        digest is the human channel's document. The S1 `link_id` checks
        (`not_found` alike for absent and foreign; the wrong kind is
        `invalid_request`), the link's Issues in context `FOR SHARE` (a closed
        one is `conflict` / `state`), the identity key, the head `FOR UPDATE`,
        CAS, then section 4.7: the head revision must be `client_identified`
        and `active` or `ended` (else `conflict` / `state`). Revision `n + 1`
        keeps the head's state, re-cites its evidence anchor by anchor (same
        anchors, roles and order, so the same digest) and copies its member
        version, so stale evidence stays stale.
        """
        capability = _CONFIRM if kind is RecordLinkKind.SEMANTIC else _MEMBERSHIP_CONFIRM
        at = ensure_utc(now)
        issues, lineage = uow.issues, uow.record_lineage
        digest = request_digest(
            capability,
            principal_id,
            {
                "link_id": request.link_id,
                "expected_revision": request.expected_revision,
                "reason": request.reason,
            },
        )
        prior = reserve_open_write(
            issues, principal_id, capability, idempotency_key, digest, authority, at
        )
        if prior is not None:
            return _replayed(uow, principal_id, prior)
        # S3 section 6.2 step 1b: the commit mark, before any other lock.
        lineage.take_commit_mark(principal_id)
        link = lineage.read_link(principal_id, request.link_id)
        if link is None:
            raise NotFoundError(SafeDetail.LINK_ID)
        if link.kind is not kind:
            raise InvalidRequestError(SafeDetail.LINK_ID)
        named = _named_issues(link)
        if link.kind is RecordLinkKind.SEMANTIC:
            already = {issue_id for issue_id, _ in named}
            named = named + tuple(
                (issue_id, SafeDetail.CONTEXT_ISSUE_ID)
                for issue_id in sorted(issues_in_context_of(lineage, principal_id, link))
                if issue_id not in already
            )
        locked = lock_lineage_sources(issues, lineage, principal_id, issue_ids=named)
        require_open_issues(locked)
        lineage.lock_identity(principal_id, link.normalized_identity)
        head = lineage.lock_head(principal_id, request.link_id)
        if head is None:
            raise RepositoryFailureError
        if head.revision_no != request.expected_revision:
            raise ConflictError(SafeDetail.STALE_VERSION)
        current = _revision_of(lineage, principal_id, request.link_id, head.revision_no)
        if not is_unreviewed(current.acceptance_basis) or head.lifecycle_state not in (
            LinkLifecycleState.ACTIVE,
            LinkLifecycleState.ENDED,
        ):
            # An already accepted head, or a contested one (a human who agrees
            # with a client's dispute ends the link instead).
            raise ConflictError(SafeDetail.STATE)
        revision = LinkRevisionRecord(
            link_id=request.link_id,
            revision_no=head.revision_no + 1,
            revision_id=issue_identifier(IdKind.RECORD_LINK_REVISION),
            predecessor_revision_no=head.revision_no,
            action=LinkRevisionAction.CONFIRM,
            lifecycle_state=head.lifecycle_state,
            acceptance_basis=AcceptanceBasis.USER_CONFIRMED,
            authority_class=authority.authority_class.value,
            decision_channel=authority.decision_channel.value,
            source_capability=capability,
            reason=request.reason,
            evidence_set_digest=current.evidence_set_digest,
            recorded_at=at,
            evidence=current.evidence,
            member_native_version=current.member_native_version,
        )
        lineage.append_revision(principal_id, revision)
        issues.complete_write_request(
            principal_id,
            capability,
            idempotency_key,
            request_digest=digest,
            completed_at=at,
            result_link_id=request.link_id,
            result_link_revision_no=revision.revision_no,
        )
        (view,) = _views(lineage, principal_id, [(link, revision)])
        return AssociationResult(association=view, created=None, replayed=False)

    # --- reads ------------------------------------------------------------------

    def memberships(
        self,
        uow: UnitOfWork,
        principal_id: str,
        issue_id: str,
        *,
        visible: Callable[[RecordRef], bool] | None = None,
    ) -> tuple[tuple[AssociationView, ...], bool, bool]:
        """An Issue's active memberships the reader may see (at most 100).

        Returns the views, whether more *visible* ones exist, and whether any
        membership was withheld (S3 section 6.4, FR3-F01): a member the reader
        may not see is neither shown nor counted toward `memberships_truncated`,
        so the flag is no count oracle over hidden members.
        """
        lineage = uow.record_lineage
        sees = visible if visible is not None else (lambda _ref: True)
        # FR3-F08: keyset batches, and at most `MAX_VISIBILITY_SCAN` memberships
        # read per request; reaching the bound says `truncated` (more may exist).
        seen: list[LinkHeadRecord] = []
        scanned = 0
        capped = False
        after: tuple[datetime, str] | None = None
        while True:
            heads = lineage.issue_memberships(
                principal_id, issue_id, limit=MEMBERSHIP_SCAN_BATCH, after=after
            )
            for head in heads:
                scanned += 1
                if sees(head.link.to_ref):
                    seen.append(head)
                    if len(seen) > MAX_ISSUE_MEMBERSHIPS:
                        break
            if len(seen) > MAX_ISSUE_MEMBERSHIPS or len(heads) < MEMBERSHIP_SCAN_BATCH:
                break
            if scanned >= MAX_VISIBILITY_SCAN:
                capped = True
                break
            last = heads[-1].link
            after = (last.created_at, last.link_id)
        shown = seen[:MAX_ISSUE_MEMBERSHIPS]
        return (
            _head_views(lineage, principal_id, shown),
            len(seen) > MAX_ISSUE_MEMBERSHIPS or capped,
            scanned > len(seen),
        )

    def association_history(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: AssociationHistoryRequest,
        *,
        now: datetime,
        visibility: LineageVisibility,
    ) -> AssociationHistoryResult:
        """`records.associations.history` (S3 section 7.3): one link's revisions at `T_k`.

        Memberships and semantic links alike. A link that is absent, foreign,
        not yet known at `T_k`, or (remote) with an invisible endpoint is
        `not_found` / `link_id`, alike. Evidence is visibility-filtered.
        """
        lineage = uow.record_lineage
        link = lineage.read_link(principal_id, request.link_id)
        if link is None or not (visibility.sees(link.from_ref) and visibility.sees(link.to_ref)):
            raise NotFoundError(SafeDetail.LINK_ID)
        if link.context_issue_id is not None and not visibility.sees_family(RecordFamily.SITUATION):
            # FR3-F03 (S3 section 7.3): an Issue-scoped link names its Issue, which
            # a reader without Issue visibility may not learn: answered as absent.
            raise NotFoundError(SafeDetail.LINK_ID)
        known_at = lineage_known_at(uow, principal_id, request.known_at, now)
        cut = LineageFactCut(
            watermark=None
            if known_at is None
            else lineage.commit_watermark(principal_id, known_at),
            at=known_at,
        )
        if not lineage.link_revisions_known_at(
            principal_id, link.link_id, cut, after=None, limit=1
        ):
            # The root is not known at `T_k`: the link did not exist then.
            raise NotFoundError(SafeDetail.LINK_ID)
        revisions = lineage.link_revisions_known_at(
            principal_id, link.link_id, cut, after=request.after, limit=request.page_size + 1
        )
        shown = revisions[: request.page_size]
        sets, withheld = visible_anchor_sets(
            lineage, principal_id, [revision.evidence for revision in shown], visibility
        )
        return AssociationHistoryResult(
            link=LinkHistoryRootView(
                link_id=link.link_id,
                kind=link.kind,
                relation_type=link.relation_type,
                from_ref=_ref_view(link.from_ref),
                to_ref=_ref_view(link.to_ref),
                member_role=link.member_role,
                context_issue_id=link.context_issue_id,
                created_at=link.created_at,
            ),
            known_at=known_at,
            revisions=tuple(
                LinkHistoryRevisionView(
                    revision_no=revision.revision_no,
                    revision_id=revision.revision_id,
                    action=revision.action,
                    lifecycle_state=revision.lifecycle_state,
                    acceptance_basis=revision.acceptance_basis,
                    authority_class=revision.authority_class,
                    user_directed_claim=revision.user_directed_claim,
                    asserting_client_id=revision.asserting_client_id,
                    reason=revision.reason,
                    evidence=evidence,
                    recorded_at=revision.recorded_at,
                )
                for revision, evidence in zip(shown, sets, strict=True)
            ),
            next_cursor=(
                shown[-1].revision_no if len(revisions) > request.page_size and shown else None
            ),
            restricted=withheld,
        )

    def read_lineage(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: LineageReadRequest,
        *,
        now: datetime,
        visibility: LineageVisibility,
    ) -> LineageView:
        """`records.lineage` (S3 section 7.2): as of a cut, visibility-filtered, paged."""
        return read_lineage_as_of(uow, principal_id, request, now=now, visibility=visibility)

    def read_related(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: RelatedReadRequest,
        *,
        now: datetime,
        visibility: LineageVisibility,
    ) -> RelatedRecordsView:
        """`records.lineage.related` (S3.1 section 7.4): related records of 1..25 seeds."""
        return read_related_as_of(uow, principal_id, request, now=now, visibility=visibility)


def insert_new_link(
    uow: UnitOfWork,
    principal_id: str,
    root: RecordLinkRecord,
    anchors: tuple[EvidenceAnchor, ...],
    at: datetime,
    *,
    provenance: LineageProvenance,
    reason: str | None = None,
    member_version: int | None = None,
) -> LinkRevisionRecord:
    """Write a new root and its revision 1 (`assert`, `active`): anchors, root, revision, head.

    The root-writing step `_assert_root` and the S2 composites share (S2
    section 6.4). The caller holds the root's identity advisory lock and has
    proven no active head carries that identity. `reason` is revision 1's
    (a `created_to_resolve` purpose, S2 section 3.1; else `None`);
    `member_version` the member's observed native `version` a membership's
    revision 1 records (S2 section 3.3; else `None`). `provenance` is the
    writer's (S3.1 section 4.1): its basis, client and claim; the root carries
    its class and channel.
    """
    revision = LinkRevisionRecord(
        link_id=root.link_id,
        revision_no=1,
        revision_id=issue_identifier(IdKind.RECORD_LINK_REVISION),
        predecessor_revision_no=None,
        action=LinkRevisionAction.ASSERT,
        lifecycle_state=LinkLifecycleState.ACTIVE,
        acceptance_basis=provenance.acceptance_basis,
        authority_class=root.authority_class,
        decision_channel=root.decision_channel,
        source_capability=root.source_capability,
        reason=reason,
        evidence_set_digest=evidence_set_digest(anchors),
        recorded_at=at,
        evidence=_inserted(uow.issues, principal_id, anchors, at),
        member_native_version=member_version,
        asserting_client_id=provenance.asserting_client_id,
        user_directed_claim=provenance.user_directed_claim,
    )
    uow.record_lineage.insert_link(principal_id, root, revision)
    return revision


def _require_escalation(
    uow: UnitOfWork,
    principal_id: str,
    issue_id: str,
    constraint: LineageEndpoint,
    task: LineageEndpoint,
) -> None:
    """S2 section 3.1's `escalated_from` assert-time rules, after the evidence rule.

    The Constraint is not `draft` (`endpoint`) and was not created before the
    Task (`from`); its Project has an active link to the context Issue, the
    triplet shared (`project_id`); the Task is an active member of that Issue
    (`to`). A correction never re-runs these (R2-F07).
    """
    if constraint.native_state == ConstraintLifecycleState.DRAFT.value:
        raise InvalidRequestError(SafeDetail.ENDPOINT)
    if (
        constraint.created_at is None
        or task.created_at is None
        or constraint.created_at < task.created_at
    ):
        raise InvalidRequestError(SafeDetail.FROM_RECORD)
    if constraint.project_id is None or not uow.issues.share_active_project_link(
        principal_id, constraint.project_id, issue_id
    ):
        raise InvalidRequestError(SafeDetail.PROJECT_ID)
    task_ref = RecordRef(family=RecordFamily.TASK, record_id=task.record_id)
    if uow.record_lineage.active_membership(principal_id, issue_id, task_ref) is None:
        raise InvalidRequestError(SafeDetail.TO_RECORD)


def require_no_blocks_cycle(
    lineage: RecordLineageRepository, principal_id: str, from_ref: RecordRef, to_ref: RecordRef
) -> None:
    """S2 section 3.1's cycle rule: `from` must not be reachable from `to`.

    Breadth-first over the Principal's active `blocks` heads in any context,
    under the `:blocks` key the caller holds. At most `MAX_BLOCKS_SEARCH`
    records are visited; a search that would visit more before its frontier is
    exhausted refuses, like a cycle (`invalid_request` / `blocks_cycle`).
    """
    seen = {to_ref}
    frontier: set[RecordRef] = {to_ref}
    while frontier:
        reached: set[RecordRef] = set()
        for ref in lineage.blocks_successors(principal_id, frontier):
            if ref == from_ref:
                raise InvalidRequestError(SafeDetail.BLOCKS_CYCLE)
            if ref not in seen:
                seen.add(ref)
                if len(seen) > MAX_BLOCKS_SEARCH:
                    raise InvalidRequestError(SafeDetail.BLOCKS_CYCLE)
                reached.add(ref)
        frontier = reached


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


# --- S3 section 3.2: inside sets and "in the Issue's context" (current heads) ------


def _pair_set(
    lineage: RecordLineageRepository, principal_id: str, ref: RecordRef
) -> tuple[RecordRef, ...]:
    """A record's pair set now: itself, its Meeting, or its Meeting's note versions."""
    if ref.family is RecordFamily.MEETING_NOTE_VERSION:
        record = lineage.resolve_records(principal_id, (ref,)).get(ref)
        if record is not None and record.meeting_id is not None:
            return (ref, RecordRef(family=RecordFamily.MEETING, record_id=record.meeting_id))
        return (ref,)
    if ref.family is RecordFamily.MEETING:
        notes = lineage.note_versions_of(principal_id, (ref.record_id,)).get(ref.record_id, ())
        return (
            ref,
            *(
                RecordRef(family=RecordFamily.MEETING_NOTE_VERSION, record_id=note.note_version_id)
                for note in notes
            ),
        )
    return (ref,)


def issue_inside_set(
    lineage: RecordLineageRepository, principal_id: str, issue_id: str
) -> frozenset[RecordRef]:
    """Issue *I*'s inside set now: *I*, its active members and their pair sets."""
    issue = RecordRef(family=RecordFamily.SITUATION, record_id=issue_id)
    inside = {issue}
    for head in lineage.active_links_incident(principal_id, (issue,)):
        link = head.link
        if link.kind is RecordLinkKind.ISSUE_MEMBERSHIP and link.from_ref == issue:
            inside.update(_pair_set(lineage, principal_id, link.to_ref))
    return frozenset(inside)


def _issues_holding(
    lineage: RecordLineageRepository, principal_id: str, ref: RecordRef
) -> frozenset[str]:
    """The Issues `ref` is inside now: itself, or those with an active member in its pair set.

    The pair relation is symmetric (a note version and its Meeting), so `ref`
    is in an active member's pair set exactly when that member is in `ref`'s.
    """
    pair = set(_pair_set(lineage, principal_id, ref))
    holding = {ref.record_id} if ref.family is RecordFamily.SITUATION else set()
    for head in lineage.active_links_incident(principal_id, pair):
        link = head.link
        if link.kind is RecordLinkKind.ISSUE_MEMBERSHIP and link.to_ref in pair:
            holding.add(link.from_ref.record_id)
    return frozenset(holding)


def issues_in_context_of(
    lineage: RecordLineageRepository, principal_id: str, link: RecordLinkRecord
) -> frozenset[str]:
    """Every Issue one link is in the context of now (section 3.2, current heads).

    The candidates are its context, its Issue endpoints and, for a
    null-context semantic link, the Issues both endpoints are inside; each is
    kept only when `in_issue_context` says so against that Issue's inside set.
    """
    candidates: set[str] = set()
    if link.context_issue_id is not None:
        candidates.add(link.context_issue_id)
    candidates.update(
        ref.record_id
        for ref in (link.from_ref, link.to_ref)
        if ref.family is RecordFamily.SITUATION
    )
    if link.kind is RecordLinkKind.SEMANTIC and link.context_issue_id is None:
        candidates.update(
            _issues_holding(lineage, principal_id, link.from_ref)
            & _issues_holding(lineage, principal_id, link.to_ref)
        )
    return frozenset(
        issue_id
        for issue_id in candidates
        if in_issue_context(
            kind=link.kind,
            from_ref=link.from_ref,
            to_ref=link.to_ref,
            context_issue_id=link.context_issue_id,
            issue_id=issue_id,
            inside=(
                issue_inside_set(lineage, principal_id, issue_id)
                if link.context_issue_id is None
                else frozenset()
            ),
        )
    )


def links_in_context(
    lineage: RecordLineageRepository, principal_id: str, issue_id: str
) -> tuple[LinkHeadRecord, ...]:
    """Every live semantic link in Issue *I*'s context now, by `link_id` (code point)."""
    inside = issue_inside_set(lineage, principal_id, issue_id)
    return tuple(
        head
        for head in lineage.links_in_issue_context(principal_id, issue_id, inside)
        if in_issue_context(
            kind=head.link.kind,
            from_ref=head.link.from_ref,
            to_ref=head.link.to_ref,
            context_issue_id=head.link.context_issue_id,
            issue_id=issue_id,
            inside=inside,
        )
    )


def unreviewed_links_in_scope(
    lineage: RecordLineageRepository, principal_id: str, issue_id: str
) -> tuple[ReviewScopeLink, ...]:
    """S3.1 section 4.6: every link in Issue *I*'s review scope whose head is unreviewed.

    Current heads in any state (live and ended), by `link_id` (code point):
    the links whose head revision is `client_identified`, which hold the close
    until the human channel confirms or revises each.
    """
    inside = issue_inside_set(lineage, principal_id, issue_id)
    return tuple(
        candidate
        for candidate in lineage.review_scope_links(principal_id, issue_id, inside)
        if is_unreviewed(candidate.acceptance_basis)
        and in_review_scope(
            kind=candidate.head.link.kind,
            from_ref=candidate.head.link.from_ref,
            to_ref=candidate.head.link.to_ref,
            context_issue_id=candidate.head.link.context_issue_id,
            issue_id=issue_id,
            inside=inside,
        )
    )


def issue_inside_set_at(
    lineage: RecordLineageRepository, principal_id: str, issue_id: str, cut: LineageFactCut
) -> tuple[frozenset[RecordRef], tuple[LinkHeadRecord, ...]]:
    """Issue *I*'s inside set at a read cut, and its memberships active then (section 3.2).

    The memberships are those whose revision selected at `cut` is `active`
    (from revisions, never from heads). A member's pair set is resolved now:
    a note version and its Meeting are immutable, and no link known at the cut
    can name a note version saved after it.
    """
    issue = RecordRef(family=RecordFamily.SITUATION, record_id=issue_id)
    members = tuple(
        head
        for head in lineage.live_links_incident(principal_id, (issue,), cut)
        if head.link.kind is RecordLinkKind.ISSUE_MEMBERSHIP
        and head.link.from_ref == issue
        and head.lifecycle_state is LinkLifecycleState.ACTIVE
    )
    inside = {issue}
    for head in members:
        inside.update(_pair_set(lineage, principal_id, head.link.to_ref))
    return frozenset(inside), members


def links_in_context_at(
    lineage: RecordLineageRepository,
    principal_id: str,
    issue_id: str,
    cut: LineageFactCut,
    *,
    inside: frozenset[RecordRef] | None = None,
) -> tuple[LinkHeadRecord, ...]:
    """Every link in Issue *I*'s context at a read cut, in any state then (section 3.2).

    The as-of variant of `links_in_context`: the one `in_issue_context`
    predicate against the inside set at the cut, over every link of either kind
    known at the cut, each with its state then. A membership is in context only
    from *I*. Ordered by `link_id` (code point). `inside` is the inside set at
    `cut` when the caller already holds it.
    """
    if inside is None:
        inside, _ = issue_inside_set_at(lineage, principal_id, issue_id, cut)
    return tuple(
        head
        for head in lineage.links_in_issue_context_at(principal_id, issue_id, inside, cut)
        if in_issue_context(
            kind=head.link.kind,
            from_ref=head.link.from_ref,
            to_ref=head.link.to_ref,
            context_issue_id=head.link.context_issue_id,
            issue_id=issue_id,
            inside=inside,
        )
    )


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
#
# S1 section 7.2, widened by S3 section 7.2 (worker L3). One traversal, read
# through a `_Reader`: `_AsOfReader` selects every link, membership and Issue
# revision at the knowledge cut `W(T_v)` from revisions (never from
# `record_link_heads`) and every note version at the native cut `N`; the S1
# current-state `_CurrentReader` over heads is kept only for the in-memory
# source the S1 FAST read-contract tests drive `traverse_lineage` with. The
# service always reads as of a cut.

#: S3 section 7.2 step 5: a traversal deadline per page; reaching it truncates
#: and ends paging, because a time cut is not reproducible.
LINEAGE_DEADLINE_SECONDS: Final = 2.0
#: S3 section 7.2 step 5: `SET LOCAL statement_timeout` per statement of a read.
LINEAGE_STATEMENT_TIMEOUT_MS: Final = 2000
#: The clock the deadline reads; a module attribute so a test can move it.
_monotonic: Callable[[], float] = time.monotonic

_RECORDS_LINEAGE: Final = Capability.RECORDS_LINEAGE.value
_TYPED: Final = "typed"
_VIRTUAL: Final = "virtual"

type _Via = tuple[str, str | None]


class _CurrentReader:
    """S1's current-state reads over heads (the S1 FAST in-memory source only)."""

    def __init__(self, source: RecordLineageRepository, owner: str) -> None:
        self.source = source
        self.owner = owner

    def incident(self, refs: Collection[RecordRef]) -> tuple[LinkHeadRecord, ...]:
        return self.source.active_links_incident(self.owner, refs)

    def notes(self, meeting_ids: Collection[str]) -> Mapping[str, Sequence[LineageNoteVersionRef]]:
        return self.source.note_versions_of(self.owner, meeting_ids)

    def note_in_cut(self, ref: RecordRef) -> bool:
        del ref
        return True

    def issues(self, issue_ids: Collection[str]) -> Mapping[str, LineageIssueAsOf] | None:
        del issue_ids
        return None

    def restricted_roots(self, root_ids: Collection[str]) -> frozenset[str]:
        del root_ids
        return frozenset()


class _AsOfReader(_CurrentReader):
    """S3 section 7.2 step 2: links and Issue revisions at the cut, notes at `N`."""

    def __init__(
        self,
        source: RecordLineageRepository,
        owner: str,
        cut: LineageFactCut,
        native_cut_at: datetime,
    ) -> None:
        super().__init__(source, owner)
        self.cut = cut
        self.native_cut_at = native_cut_at
        self._recorded: dict[str, datetime | None] = {}

    def incident(self, refs: Collection[RecordRef]) -> tuple[LinkHeadRecord, ...]:
        return self.source.live_links_incident(self.owner, refs, self.cut)

    def notes(self, meeting_ids: Collection[str]) -> Mapping[str, Sequence[LineageNoteVersionRef]]:
        return self.source.note_versions_until(self.owner, meeting_ids, self.native_cut_at)

    def note_in_cut(self, ref: RecordRef) -> bool:
        if ref.record_id not in self._recorded:
            found = self.source.note_version_recorded_at(self.owner, (ref.record_id,))
            self._recorded[ref.record_id] = found.get(ref.record_id)
        recorded = self._recorded[ref.record_id]
        return recorded is not None and recorded <= self.native_cut_at

    def issues(self, issue_ids: Collection[str]) -> Mapping[str, LineageIssueAsOf] | None:
        return self.source.issues_known_at(self.owner, issue_ids, self.cut)

    def restricted_roots(self, root_ids: Collection[str]) -> frozenset[str]:
        return self.source.restricted_capture_roots(self.owner, root_ids)


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
    """Section 7.2 step 5's whole-query budget; `max_bytes` is `None` when paged."""

    max_bytes: int | None = None
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
            or (self.max_bytes is not None and self.size + size > self.max_bytes)
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

    def __init__(
        self,
        reader: _CurrentReader,
        root: RecordRef,
        visibility: LineageVisibility,
        *,
        paged: bool,
        deadline: float | None,
    ) -> None:
        self.reader = reader
        self.source = reader.source
        self.owner = reader.owner
        self.visibility = visibility
        self.budget = _Budget(max_bytes=None if paged else MAX_LINEAGE_BYTES)
        self.deadline = deadline
        self.deadline_hit = False
        self.restricted = False
        self.depth: dict[RecordRef, int] = {}
        self.paths: dict[RecordRef, tuple[RecordRef, _Via] | None] = {}
        self.order: list[RecordRef] = []
        self.links: dict[str, LinkHeadRecord] = {}
        self.resolved: dict[RecordRef, LineageResolvedRecord] = {}
        self.notes: dict[str, tuple[RecordRef, ...]] = {}
        self.note_numbers: dict[RecordRef, int] = {}
        self.issue_states: dict[str, LineageIssueAsOf | None] = {}
        self.root = root

    def out_of_time(self) -> bool:
        """Section 7.2 step 5: the per-page deadline; reaching it exhausts the budget."""
        if self.deadline is not None and _monotonic() > self.deadline:
            self.deadline_hit = True
            self.budget.exhausted = True
        return self.deadline_hit

    def visible(self, ref: RecordRef) -> bool:
        return self.visibility.sees(ref)

    def resolve(self, refs: Iterable[RecordRef]) -> None:
        missing = {ref for ref in refs if ref not in self.resolved}
        if missing:
            self.resolved.update(self.source.resolve_records(self.owner, missing))

    def load_notes(self, meeting_ids: Iterable[str]) -> None:
        missing = {meeting_id for meeting_id in meeting_ids if meeting_id not in self.notes}
        if not missing:
            return
        found = self.reader.notes(missing)
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

    def meeting_of(self, ref: RecordRef) -> RecordRef | None:
        """A note version's Meeting, when the note is within the native cut (section 3.4)."""
        record = self.resolved.get(ref)
        if record is None or record.meeting_id is None or not self.reader.note_in_cut(ref):
            return None
        return RecordRef(family=RecordFamily.MEETING, record_id=record.meeting_id)

    def extension(self, ref: RecordRef) -> tuple[RecordRef, ...]:
        self.resolve((ref,))
        if ref.family is RecordFamily.MEETING:
            self.load_notes((ref.record_id,))
            return _pair_extension(ref, self.resolved, self.notes)
        if ref.family is RecordFamily.MEETING_NOTE_VERSION:
            meeting = self.meeting_of(ref)
            return (ref,) if meeting is None else (ref, meeting)
        return (ref,)

    def load_issues(self, issue_ids: Iterable[str]) -> None:
        missing = {issue_id for issue_id in issue_ids if issue_id not in self.issue_states}
        if not missing:
            return
        found = self.reader.issues(missing)
        for issue_id in missing:
            if found is None:
                record = self.resolved.get(
                    RecordRef(family=RecordFamily.SITUATION, record_id=issue_id)
                )
                self.issue_states[issue_id] = (
                    None
                    if record is None
                    else LineageIssueAsOf(
                        issue_id=issue_id,
                        version=0,
                        title=record.title or "",
                        state=record.state or "",
                    )
                )
            else:
                self.issue_states[issue_id] = found.get(issue_id)

    def is_issue(self, ref: RecordRef) -> bool:
        """An Issue Situation that exists at the cut (its revision is known there)."""
        if not _is_issue(ref, self.resolved):
            return False
        self.load_issues((ref.record_id,))
        return self.issue_states.get(ref.record_id) is not None

    def reach(self, ref: RecordRef, depth: int, parent: RecordRef | None, via: _Via | None) -> bool:
        """Add a node at `depth` with its path step, unless reached already or over budget."""
        if ref in self.depth:
            return True
        if not self.budget.admit(nodes=1, size=_size(_ref_document(ref)) + 160):
            return False
        self.depth[ref] = depth
        self.paths[ref] = None if parent is None or via is None else (parent, via)
        self.order.append(ref)
        return True

    def follow(self, head: LinkHeadRecord) -> bool:
        if head.link.link_id in self.links:
            return True
        if not self.budget.admit(edges=1, size=_EDGE_ESTIMATE):
            return False
        self.links[head.link.link_id] = head
        return True


def _matching_issues(
    graph: _Graph, pair: Sequence[RecordRef], *, root: RecordRef | None = None
) -> list[str]:
    """Section 7.2 step 2 over the root's pair set; an invisible Issue is never a candidate.

    `root` is the graph's own root unless given (S3.1: each related-read seed).
    """
    origin = graph.root if root is None else root
    matching: set[str] = set()
    if graph.is_issue(origin):
        matching.add(origin.record_id)
    pair_set = set(pair)
    for head in graph.reader.incident(pair_set):
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
    graph.load_issues(ref.record_id for ref in refs)
    found: list[str] = []
    for ref in refs:
        if not graph.is_issue(ref):
            continue
        if not graph.visible(ref):
            graph.restricted = True
            continue
        found.append(ref.record_id)
    return sorted(found)


def _members_in(graph: _Graph, issue_id: str) -> set[RecordRef]:
    """*I*, its live members, and every member of a live member's pair set, at the cut.

    Structural only (it decides which null-context links are followable): an
    invisible member is in it, but no link to an invisible record is emitted.
    """
    issue = RecordRef(family=RecordFamily.SITUATION, record_id=issue_id)
    inside = {issue}
    members = [
        head.link.to_ref
        for head in graph.reader.incident((issue,))
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
    """Section 7.2 steps 3 and 4: breadth-first from the root under the one Issue *I*.

    Every frontier state carries *I* (S3 section 7.2 step 3): a shared Meeting
    never expands into another Issue's links. The first edge that reaches a
    record is its path step; ties fall to the S1 order -- frontier
    `(depth, family, record_id)`, edges `(created_at, link_id)`, then the
    `meeting_note_version_of` step.
    """
    inside = _members_in(graph, issue_id)
    frontier = [graph.root]
    depth = 0
    while frontier and depth < max_depth and not graph.budget.exhausted:
        nxt: list[RecordRef] = []
        for node in sorted(frontier, key=lambda ref: (ref.family.value, ref.record_id)):
            if graph.out_of_time():
                return
            extension = graph.extension(node)
            for head in graph.reader.incident(extension):
                if not _followable(head, issue_id, inside):
                    continue
                link = head.link
                near = link.from_ref if link.from_ref in extension else link.to_ref
                far = link.to_ref if near == link.from_ref else link.from_ref
                if not (graph.visible(near) and graph.visible(far)):
                    # Section 6.4: neither emitted, expanded nor counted.
                    graph.restricted = True
                    continue
                if not graph.follow(head):
                    return
                if near not in graph.depth:
                    if not graph.reach(near, depth + 1, node, (_VIRTUAL, None)):
                        return
                    nxt.append(near)
                if far not in graph.depth:
                    if not graph.reach(far, depth + 1, near, (_TYPED, link.link_id)):
                        return
                    nxt.append(far)
            if node.family is RecordFamily.MEETING_NOTE_VERSION:
                parent = graph.meeting_of(node)
                if parent is not None and parent not in graph.depth:
                    if not graph.reach(parent, depth + 1, node, (_VIRTUAL, None)):
                        return
                    nxt.append(parent)
        frontier = nxt
        depth += 1


def _one_hop(graph: _Graph, max_depth: int) -> None:
    """Section 7.2 step 3, no Issue: context-free semantic links at the root, one hop."""
    if max_depth < 1:
        return
    root = graph.root
    for head in graph.reader.incident((root,)):
        link = head.link
        if link.kind is not RecordLinkKind.SEMANTIC or link.context_issue_id is not None:
            continue
        far = link.to_ref if link.from_ref == root else link.from_ref
        if not graph.visible(far):
            graph.restricted = True
            continue
        if not graph.follow(head) or not graph.reach(far, 1, root, (_TYPED, link.link_id)):
            return
    if root.family is RecordFamily.MEETING_NOTE_VERSION:
        meeting = graph.meeting_of(root)
        if meeting is not None:
            graph.reach(meeting, 1, root, (_VIRTUAL, None))


def _virtual_edges(graph: _Graph, nodes: Collection[RecordRef]) -> list[VirtualEdgeView]:
    """Every `meeting_note_version_of` edge touching a reached node, by version number.

    Only note versions within the native cut (S3 section 3.4); a whole-query
    edge budget applies.
    """
    meetings: set[str] = set()
    for ref in nodes:
        if ref.family is RecordFamily.MEETING:
            meetings.add(ref.record_id)
        elif ref.family is RecordFamily.MEETING_NOTE_VERSION:
            meeting = graph.meeting_of(ref)
            if meeting is not None:
                meetings.add(meeting.record_id)
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


def _path_view(step: tuple[RecordRef, _Via] | None) -> dict[str, Any]:
    if step is None:
        return {"reached_from": None, "reached_via": None}
    parent, (edge, link_id) = step
    via = (
        LineagePathEdgeView(edge="typed", link_id=link_id)
        if edge == _TYPED
        else LineagePathEdgeView(
            edge="virtual", edge_type=NativeVirtualEdge.MEETING_NOTE_VERSION_OF
        )
    )
    return {"reached_from": _ref_view(parent), "reached_via": via}


def _node_view(graph: _Graph, ref: RecordRef) -> LineageNodeView:
    record = graph.resolved[ref]
    is_issue = ref.family is RecordFamily.SITUATION
    issue = graph.issue_states.get(ref.record_id) if is_issue else None
    return LineageNodeView(
        family=ref.family,
        record_id=ref.record_id,
        depth=graph.depth[ref],
        meeting_id=record.meeting_id if ref.family is RecordFamily.MEETING_NOTE_VERSION else None,
        title=(issue.title if issue is not None else record.title) if is_issue else None,
        state=(issue.state if issue is not None else record.state) if is_issue else None,  # type: ignore[arg-type]
        availability=(
            ("archived" if record.capture_archived else "available")
            if ref.family is RecordFamily.CAPTURE_VERSION
            else None
        ),
        **_path_view(graph.paths.get(ref)),
    )


def _edge_views(
    graph: _Graph, heads: Sequence[LinkHeadRecord]
) -> tuple[list[AssociationView], bool]:
    """The typed edges at their selected revisions, anchors visibility-filtered (section 6.4).

    Returns the views by `link_id` (code point) and whether an anchor was
    withheld. A legacy Capture anchor whose root now holds a `restricted_local`
    version reads `restricted` to a local reader and is withheld remotely.
    """
    pairs = [
        (head.link, _revision_of(graph.source, graph.owner, head.link.link_id, head.revision_no))
        for head in sorted(heads, key=lambda head: head.link.link_id)
    ]
    return visible_association_views(
        graph.source, graph.owner, pairs, graph.visibility, graph.reader
    )


def visible_anchor_sets(
    source: RecordLineageRepository,
    principal_id: str,
    evidence_sets: Sequence[Sequence[LineageLinkEvidence]],
    visibility: LineageVisibility,
    *,
    restricted_roots: Callable[[Collection[str]], frozenset[str]] | None = None,
) -> tuple[list[tuple[EvidenceAnchorView, ...]], bool]:
    """Each evidence set as its visible anchor views, and whether any anchor was withheld.

    Section 6.4: an anchor is shown iff its source family is visible; a legacy
    `capture` anchor whose root currently holds a `restricted_local` version
    (S1 F24's forward rule) reads `restricted` to a local reader and is
    withheld from a remote one. Availability is computed now.
    """
    flat = [cited for evidence in evidence_sets for cited in evidence]
    archived = source.archived_capture_roots(principal_id, _capture_roots_of(flat))
    legacy = {
        cited.anchor.source_root_id
        for cited in flat
        if cited.anchor.source_family is EvidenceSourceFamily.CAPTURE
    }
    lookup = restricted_roots or (
        lambda roots: source.restricted_capture_roots(principal_id, roots)
    )
    restricted = lookup(legacy) if legacy else frozenset()
    withheld = False
    shown_sets: list[tuple[EvidenceAnchorView, ...]] = []
    for evidence in evidence_sets:
        shown: list[EvidenceAnchorView] = []
        for cited in evidence:
            anchor = cited.anchor
            is_restricted = (
                anchor.source_family is EvidenceSourceFamily.CAPTURE
                and anchor.source_root_id in restricted
            )
            if not visibility.sees_anchor(anchor) or (is_restricted and visibility.remote):
                withheld = True
                continue
            view = anchor_view(cited, archived)
            if is_restricted:
                view = view.model_copy(update={"availability": EvidenceAvailability.RESTRICTED})
            shown.append(view)
        shown_sets.append(tuple(shown))
    return shown_sets, withheld


def _capture_roots_of(evidence: Iterable[LineageLinkEvidence]) -> frozenset[str]:
    return frozenset(
        cited.anchor.source_root_id
        for cited in evidence
        if cited.anchor.source_family is not EvidenceSourceFamily.MEETING_NOTE_VERSION
    )


def visible_association_views(
    source: RecordLineageRepository,
    principal_id: str,
    pairs: Sequence[tuple[RecordLinkRecord, LinkRevisionRecord]],
    visibility: LineageVisibility,
    reader: _CurrentReader | None = None,
) -> tuple[list[AssociationView], bool]:
    """Each `(root, revision)` as an `AssociationView` with only the visible anchors."""
    sets, withheld = visible_anchor_sets(
        source,
        principal_id,
        [revision.evidence for _, revision in pairs],
        visibility,
        restricted_roots=None if reader is None else reader.restricted_roots,
    )
    archived: frozenset[str] = frozenset()
    views = [
        association_view(link, revision, archived).model_copy(update={"evidence": shown})
        for (link, revision), shown in zip(pairs, sets, strict=True)
    ]
    return views, withheld


@dataclass(frozen=True, slots=True)
class LineageBoundedResult:
    """The whole bounded result of one `records.lineage` read, before paging (section 7.2)."""

    root: RecordRef
    selected_issue_id: str | None
    issues_matching_root: tuple[LineageIssueMatch, ...]
    nodes: tuple[LineageNodeView, ...]
    typed_edges: tuple[AssociationView, ...]
    virtual_native_edges: tuple[VirtualEdgeView, ...]
    codes: frozenset[LineageCompleteness]
    deadline_hit: bool


def bounded_lineage(
    source: RecordLineageRepository,
    principal_id: str,
    request: LineageReadRequest,
    *,
    reader: _CurrentReader | None = None,
    visibility: LineageVisibility | None = None,
    paged: bool = False,
    deadline: float | None = None,
) -> LineageBoundedResult:
    """Section 7.2 steps 1 to 5 and 8: the traversal, before output order and paging."""
    root = request.origin
    seen = (
        visibility
        if visibility is not None
        else lineage_visibility(None, Capability.RECORDS_LINEAGE)
    )
    graph = _Graph(
        reader if reader is not None else _CurrentReader(source, principal_id),
        root,
        seen,
        paged=paged,
        deadline=deadline,
    )
    graph.resolve((root,))
    if root not in graph.resolved or not graph.visible(root):
        # Section 6.4: an invisible root answers exactly as an absent one.
        raise NotFoundError(SafeDetail.ORIGIN)
    if root.family is RecordFamily.SITUATION:
        if not _is_issue(root, graph.resolved):
            raise InvalidRequestError(SafeDetail.ORIGIN)
        if not graph.is_issue(root):
            # An Issue with no revision known at the cut did not exist then.
            raise NotFoundError(SafeDetail.ORIGIN)
    pair = graph.extension(root)
    graph.resolve(pair)
    matching = _matching_issues(graph, pair)
    graph.reach(root, 0, None, None)
    selected: str | None = None
    codes: set[LineageCompleteness] = set()
    if request.issue_id is not None:
        if request.issue_id not in matching:
            raise NotFoundError(SafeDetail.ISSUE_ID)
        selected = request.issue_id
    elif len(matching) == 1:
        selected = matching[0]
    elif len(matching) > 1:
        codes.add(LineageCompleteness.UNRESOLVED_AMBIGUITY)
    if selected is not None:
        _expand(graph, selected, request.max_depth)
    elif not codes:
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
        codes.add(LineageCompleteness.TRUNCATED_BUDGET)
    if dropped:
        codes.add(LineageCompleteness.PARTIAL_NATIVE_HISTORY)
    issue_refs = [RecordRef(family=RecordFamily.SITUATION, record_id=issue) for issue in matching]
    graph.resolve(issue_refs)
    graph.load_issues(matching)
    matches = []
    for ref in issue_refs[:MAX_MATCHING_ISSUES]:
        state = graph.issue_states[ref.record_id]
        if state is None:
            raise RepositoryFailureError
        matches.append(
            LineageIssueMatch(
                issue_id=ref.record_id,
                title=state.title,
                state=state.state,  # type: ignore[arg-type]
            )
        )
    graph.load_issues(ref.record_id for ref in nodes if ref.family is RecordFamily.SITUATION)
    edges, withheld = _edge_views(graph, heads)
    if graph.restricted or withheld:
        codes.add(LineageCompleteness.RESTRICTED_EVIDENCE)
    node_views = tuple(
        _node_view(graph, ref)
        for ref in sorted(
            nodes, key=lambda ref: (graph.depth[ref], ref.family.value, ref.record_id)
        )
    )
    return LineageBoundedResult(
        root=root,
        selected_issue_id=selected,
        issues_matching_root=tuple(matches),
        nodes=node_views,
        typed_edges=tuple(edges),
        virtual_native_edges=tuple(virtual),
        codes=frozenset(codes),
        deadline_hit=graph.deadline_hit,
    )


def traverse_lineage(
    source: RecordLineageRepository,
    principal_id: str,
    request: LineageReadRequest,
    *,
    reader: _CurrentReader | None = None,
    visibility: LineageVisibility | None = None,
    cuts: LineageReportedCuts | None = None,
    deadline: float | None = None,
) -> LineageView:
    """`records.lineage` as one page (S1 section 7.2 single-page rule, S3 cuts reported).

    The S1 serialized-size loop bounds what is returned; `next_cursor` is
    `null`. Without a `reader` the S1 current-state reads over heads are used
    (the S1 FAST in-memory source only); the service always passes the as-of
    reader of section 7.2 step 2.
    """
    result = bounded_lineage(
        source,
        principal_id,
        request,
        reader=reader,
        visibility=visibility,
        paged=False,
        deadline=deadline,
    )
    codes = set(result.codes)
    edges = list(result.typed_edges)
    virtual = list(result.virtual_native_edges)
    while True:
        view = _view(result, cuts, codes, result.nodes, edges, virtual, None)
        # Step 6, the serialized budget: the per-item estimates above stop
        # expansion early; this is the exact bound on what is returned.
        if _size(view.to_canonical_dict()) <= MAX_LINEAGE_BYTES or not (edges or virtual):
            return view
        codes.add(LineageCompleteness.TRUNCATED_BUDGET)
        if virtual:
            virtual.pop()
        else:
            edges.pop()


@dataclass(frozen=True, slots=True)
class LineageReportedCuts:
    """The cuts one answer reports (S3 section 3.4): `T_k`, `valid_at`, `T_v`, `N`."""

    known_at: datetime | None
    valid_at: datetime | None
    lineage_valid_at: datetime | None
    native_cut_at: datetime | None


def _view(
    result: LineageBoundedResult,
    cuts: LineageReportedCuts | None,
    codes: Collection[LineageCompleteness],
    nodes: Sequence[LineageNodeView],
    edges: Sequence[AssociationView],
    virtual: Sequence[VirtualEdgeView],
    next_cursor: str | None,
) -> LineageView:
    state, qualifiers = completeness(codes)
    return LineageView(
        root=_ref_view(result.root),
        selected_issue_id=result.selected_issue_id,
        issues_matching_root=result.issues_matching_root,
        nodes=tuple(nodes),
        typed_edges=tuple(edges),
        virtual_native_edges=tuple(virtual),
        complete_state=state,
        qualifiers=qualifiers,
        known_at=None if cuts is None else cuts.known_at,
        valid_at=None if cuts is None else cuts.valid_at,
        lineage_valid_at=None if cuts is None else cuts.lineage_valid_at,
        native_cut_at=None if cuts is None else cuts.native_cut_at,
        next_cursor=next_cursor,
    )


# --- paging and the cursor (S3 sections 5 and 7.2 steps 6 and 7) ---------------------

_POSITION: Final = re.compile(r"\A(?P<kind>[nev]):(?P<rest>.+)\Z")


def _lineage_position(value: object) -> bool:
    """Section 5: `n:<family>:<record_id>`, `e:<link_id>` or `v:<note_version_id>`."""
    if not isinstance(value, str):
        return False
    matched = _POSITION.fullmatch(value)
    if matched is None:
        return False
    kind, rest = matched["kind"], matched["rest"]
    try:
        if kind == "n":
            family_token, _, record_id = rest.partition(":")
            family = RecordFamily(family_token)
            validate_identifier(record_id, RECORD_FAMILY_ID_KINDS[family])
        elif kind == "e":
            validate_identifier(rest, IdKind.RECORD_LINK)
        else:
            validate_identifier(rest, IdKind.MEETING_NOTE_VERSION)
    except ValueError:
        return False
    return True


def _item_key(item: LineageNodeView | AssociationView | VirtualEdgeView) -> str:
    if isinstance(item, LineageNodeView):
        return f"n:{item.family.value}:{item.record_id}"
    if isinstance(item, AssociationView):
        return f"e:{item.link_id}"
    return f"v:{item.from_ref.record_id}"


def _item_document(item: LineageNodeView | AssociationView | VirtualEdgeView) -> object:
    return item.to_canonical_dict()


def lineage_request_document(request: LineageReadRequest) -> dict[str, object]:
    """The parsed request without its cursor, optional fields `null` (section 5's `b`)."""
    return {
        "origin": _ref_document(request.origin),
        "issue_id": request.issue_id,
        "max_depth": request.max_depth,
        "known_at": instant_token(request.known_at),
        "valid_at": instant_token(request.valid_at),
        "page_size": request.page_size,
    }


def _restart(request: LineageReadRequest, cuts: LineageReportedCuts) -> LineageView:
    """Section 7.2 step 7: `scope_changed_restart_required`, nothing beyond the origin."""
    code = LineageCompleteness.SCOPE_CHANGED_RESTART_REQUIRED
    return LineageView(
        root=_ref_view(request.origin),
        selected_issue_id=None,
        issues_matching_root=(),
        nodes=(),
        typed_edges=(),
        virtual_native_edges=(),
        complete_state=code,
        qualifiers=(code,),
        known_at=cuts.known_at,
        valid_at=cuts.valid_at,
        lineage_valid_at=cuts.lineage_valid_at,
        native_cut_at=cuts.native_cut_at,
        next_cursor=None,
    )


def _page(
    result: LineageBoundedResult,
    cuts: LineageReportedCuts,
    *,
    page_size: int,
    after: str | None,
    cursor_for: Callable[[str], str],
) -> LineageView | None:
    """Section 7.2 step 6: the items after `after`, up to `page_size` or 512 KiB.

    `None` when `after` is not an item of this result (the caller answers
    `scope_changed_restart_required`).
    """
    items: list[LineageNodeView | AssociationView | VirtualEdgeView] = [
        *result.nodes,
        *result.typed_edges,
        *result.virtual_native_edges,
    ]
    keys = [_item_key(item) for item in items]
    start = 0
    if after is not None:
        if after not in keys:
            return None
        start = keys.index(after) + 1
    codes = result.codes
    # The page frame with the longest possible cursor: what every item adds to it.
    frame = _size(
        _view(result, cuts, codes, (), (), (), "x" * MAX_CURSOR_CHARACTERS).to_canonical_dict()
    )
    chosen: list[LineageNodeView | AssociationView | VirtualEdgeView] = []
    size = frame
    for item in items[start:]:
        if len(chosen) >= page_size:
            break
        grows = _size(_item_document(item)) + 1
        if chosen and size + grows > MAX_LINEAGE_BYTES:
            break
        chosen.append(item)
        size += grows
    end = start + len(chosen)
    more = end < len(items) and not result.deadline_hit
    next_cursor = cursor_for(keys[end - 1]) if more and chosen else None
    return _view(
        result,
        cuts,
        codes,
        [item for item in chosen if isinstance(item, LineageNodeView)],
        [item for item in chosen if isinstance(item, AssociationView)],
        [item for item in chosen if isinstance(item, VirtualEdgeView)],
        next_cursor,
    )


def lineage_known_at(
    uow: UnitOfWork, principal_id: str, requested: datetime | None, now: datetime
) -> datetime | None:
    """`T_k` for a history read (S3 section 3.4); `invalid_request` / `known_at` after now."""
    try:
        return effective_known_at(
            None if requested is None else ensure_utc(requested),
            now=ensure_utc(now),
            horizon=uow.record_lineage.commit_horizon(principal_id),
        )
    except CutAfterNowError as error:
        raise InvalidRequestError(SafeDetail.KNOWN_AT) from error


def read_lineage_as_of(
    uow: UnitOfWork,
    principal_id: str,
    request: LineageReadRequest,
    *,
    now: datetime,
    visibility: LineageVisibility,
) -> LineageView:
    """`records.lineage` (S3 section 7.2): as of a cut, visibility-filtered, optionally paged."""
    lineage = uow.record_lineage
    lineage.bound_read_statements(LINEAGE_STATEMENT_TIMEOUT_MS)
    at = ensure_utc(now)
    horizon = lineage.commit_horizon(principal_id)
    scope = scope_digest(visibility.grant_digest)
    cursor: LineageCursor | None = None
    if request.cursor is not None:
        cursor = _checked_cursor(request, principal_id, horizon=horizon, now=at)
        cuts = LineageReportedCuts(
            known_at=cursor.known_at,
            valid_at=request.valid_at if request.valid_at is not None else cursor.known_at,
            lineage_valid_at=cursor.lineage_valid_at,
            native_cut_at=cursor.native_cut_at,
        )
        if cursor.scope != scope:
            return _restart(request, cuts)
    else:
        try:
            cut = knowledge_cut(
                known_at=request.known_at, valid_at=request.valid_at, now=at, horizon=horizon
            )
        except CutAfterNowError as error:
            detail = SafeDetail.KNOWN_AT if error.field == "known_at" else SafeDetail.VALID_AT
            raise InvalidRequestError(detail) from error
        cuts = LineageReportedCuts(
            known_at=cut.known_at,
            valid_at=cut.valid_at,
            lineage_valid_at=cut.lineage_valid_at,
            native_cut_at=native_cut(
                known_at=request.known_at, valid_at=request.valid_at, read_time=at
            ),
        )
    t_v = cuts.lineage_valid_at
    fact_cut = LineageFactCut(
        watermark=None if t_v is None else lineage.commit_watermark(principal_id, t_v), at=t_v
    )
    native_cut_at = cuts.native_cut_at
    if native_cut_at is None:
        raise RepositoryFailureError
    reader = _AsOfReader(lineage, principal_id, fact_cut, native_cut_at)
    deadline = _monotonic() + LINEAGE_DEADLINE_SECONDS
    if request.page_size is None:
        return traverse_lineage(
            lineage,
            principal_id,
            request,
            reader=reader,
            visibility=visibility,
            cuts=cuts,
            deadline=deadline,
        )
    result = bounded_lineage(
        lineage,
        principal_id,
        request,
        reader=reader,
        visibility=visibility,
        paged=True,
        deadline=deadline,
    )
    binding = cursor_binding(
        capability=_RECORDS_LINEAGE,
        principal_id=principal_id,
        request=lineage_request_document(request),
        known_at=cuts.known_at,
        lineage_valid_at=cuts.lineage_valid_at,
        native_cut_at=cuts.native_cut_at,
        record_event_watermark=None,
    )

    def cursor_for(position: str) -> str:
        return encode_cursor(
            LineageCursor(
                binding=binding,
                scope=scope,
                known_at=cuts.known_at,
                lineage_valid_at=cuts.lineage_valid_at,
                native_cut_at=cuts.native_cut_at,
                record_event_watermark=None,
                position=position,
            )
        )

    after = None if cursor is None else str(cursor.position)
    page = _page(result, cuts, page_size=request.page_size, after=after, cursor_for=cursor_for)
    if page is None:
        # R3-F14, R3-F23: a well-formed position that is not an item of the
        # recomputed result -- vanished, hidden or edited -- answers alike.
        return _restart(request, cuts)
    return page


def _checked_cursor(
    request: LineageReadRequest, principal_id: str, *, horizon: datetime | None, now: datetime
) -> LineageCursor:
    """Section 7.2 step 7, the checks before the scope: shape, binding, cuts."""
    try:
        cursor = decode_cursor(request.cursor, _lineage_position)
    except CursorMalformedError as error:
        raise InvalidRequestError(SafeDetail.CURSOR) from error
    if cursor.record_event_watermark is not None:
        # `records.lineage` carries no Record Event watermark (section 5).
        raise InvalidRequestError(SafeDetail.CURSOR)
    expected = cursor_binding(
        capability=_RECORDS_LINEAGE,
        principal_id=principal_id,
        request=lineage_request_document(request),
        known_at=cursor.known_at,
        lineage_valid_at=cursor.lineage_valid_at,
        native_cut_at=cursor.native_cut_at,
        record_event_watermark=cursor.record_event_watermark,
    )
    if cursor.binding != expected:
        raise ConflictError(SafeDetail.CURSOR)
    known, valid, native = cursor.known_at, cursor.lineage_valid_at, cursor.native_cut_at
    if known is not None and (horizon is None or known > horizon):
        raise InvalidRequestError(SafeDetail.CURSOR)
    if (known is None) is not (valid is None) or (
        known is not None and valid is not None and valid > known
    ):
        raise InvalidRequestError(SafeDetail.CURSOR)
    # `n` is never compared with `k` (R3-F25): a current read's native cut is
    # its read time, after `T_k = H` by design.
    if native is None or native > now:
        raise InvalidRequestError(SafeDetail.CURSOR)
    for stated in (request.known_at, request.valid_at):
        if stated is not None and native > ensure_utc(stated):
            raise InvalidRequestError(SafeDetail.CURSOR)
    return cursor


# --- records.lineage.related (S3.1 contract section 7.4) ------------------------------
#
# A multi-seed related-records read over the S3 traversal machinery: the same
# as-of reader (`_AsOfReader`), the same Issue confinement (`_members_in`,
# `_followable`), the same visibility rules (S3 section 6.4), budgets
# (`MAX_LINEAGE_NODES`, `MAX_LINEAGE_EDGES`, the per-page deadline), cursor and
# paging. One bounded result is recomputed per page; `related_sha256` binds it.

_RECORDS_LINEAGE_RELATED: Final = Capability.RECORDS_LINEAGE_RELATED.value


@dataclass(frozen=True, slots=True)
class RelatedReadRequest:
    """`records.lineage.related`, parsed (S3.1 section 7.4).

    `seeds` are 1..25 distinct records in request order; `acceptance_bases` and
    `relation_types` are the admitted filter sets in vocabulary order (the
    defaults are every member); `page_size` is 10..100 and a `cursor` comes
    only with a `page_size` (the command checked both).
    """

    seeds: tuple[RecordRef, ...]
    max_depth: int
    acceptance_bases: tuple[AcceptanceBasis, ...]
    relation_types: tuple[RelationType, ...]
    known_at: datetime | None = None
    valid_at: datetime | None = None
    page_size: int | None = None
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class RelatedBoundedResult:
    """The whole bounded result of one related read, before paging (section 7.4)."""

    records: tuple[RelatedRecordView, ...]
    links: tuple[AssociationView, ...]
    virtual_edges: tuple[VirtualEdgeView, ...]
    codes: frozenset[LineageCompleteness]
    deadline_hit: bool
    related_sha256: str


class _Related:
    """The traversal state of one related read: the S3 graph plus who reached what.

    `graph.depth`, `graph.paths` and `graph.order` hold the union over seeds:
    a record's least depth and the first reaching step in `(depth, seed
    position, expansion order)`, where a seed's expansions run in order -- its
    one hop, then each of its Issues in `issue_id` order -- and each one is
    breadth-first in the S3 tie-break order.
    """

    def __init__(self, graph: _Graph, request: RelatedReadRequest) -> None:
        self.graph = graph
        self.bases = frozenset(request.acceptance_bases)
        self.relations = frozenset(request.relation_types)
        self.seeds_of: dict[RecordRef, set[int]] = {}
        self.issues_of: dict[RecordRef, set[str]] = {}
        self.revisions: dict[tuple[str, int], LinkRevisionRecord] = {}

    def revision(self, head: LinkHeadRecord) -> LinkRevisionRecord:
        key = (head.link.link_id, head.revision_no)
        if key not in self.revisions:
            self.revisions[key] = _revision_of(
                self.graph.source, self.graph.owner, head.link.link_id, head.revision_no
            )
        return self.revisions[key]

    def admitted(self, head: LinkHeadRecord) -> bool:
        """Step 2: a link outside the filters is neither followed nor emitted."""
        if head.link.relation_type not in self.relations:
            return False
        return self.revision(head).acceptance_basis in self.bases

    def reach(
        self,
        ref: RecordRef,
        depth: int,
        step: tuple[RecordRef, _Via] | None,
        position: int,
        issue_id: str | None,
    ) -> bool:
        """Record that seed `position` (under `issue_id`) reached `ref` at `depth`.

        A record new to the union is admitted against the node budget; a known
        one keeps its least depth and the first step at it.
        """
        graph: _Graph = self.graph
        known = graph.depth.get(ref)
        if known is None:
            if not graph.budget.admit(nodes=1):
                return False
            graph.depth[ref] = depth
            graph.paths[ref] = step
            graph.order.append(ref)
        elif depth < known:
            graph.depth[ref] = depth
            graph.paths[ref] = step
        self.seeds_of.setdefault(ref, set()).add(position)
        if issue_id is not None:
            self.issues_of.setdefault(ref, set()).add(issue_id)
        return True


def _related_seed(graph: _Graph, seed: RecordRef) -> None:
    """Step 1: a seed absent, foreign, invisible or not known at the cut is `not_found`."""
    graph.resolve((seed,))
    if seed not in graph.resolved or not graph.visible(seed):
        raise NotFoundError(SafeDetail.SEEDS)
    if seed.family is RecordFamily.SITUATION:
        if not _is_issue(seed, graph.resolved):
            # As `records.lineage`'s origin (S1 section 3.2): not an Issue.
            raise InvalidRequestError(SafeDetail.SEEDS)
        if not graph.is_issue(seed):
            raise NotFoundError(SafeDetail.SEEDS)
    if seed.family is RecordFamily.MEETING_NOTE_VERSION and not graph.reader.note_in_cut(seed):
        raise NotFoundError(SafeDetail.SEEDS)


def _related_one_hop(state: _Related, position: int, seed: RecordRef) -> bool:
    """Step 3a: every admitted live link incident to the seed's pair set, any context."""
    graph = state.graph
    pair = graph.extension(seed)
    for head in graph.reader.incident(pair):
        if graph.out_of_time():
            return False
        if not state.admitted(head):
            continue
        link = head.link
        near = link.from_ref if link.from_ref in pair else link.to_ref
        far = link.to_ref if near == link.from_ref else link.from_ref
        if not (graph.visible(near) and graph.visible(far)):
            # S3 section 6.4: neither emitted, expanded nor counted.
            graph.restricted = True
            continue
        if not graph.follow(head):
            return False
        if near != seed and not state.reach(near, 1, (seed, (_VIRTUAL, None)), position, None):
            return False
        if not state.reach(far, 1, (near, (_TYPED, link.link_id)), position, None):
            return False
    if seed.family is RecordFamily.MEETING_NOTE_VERSION:
        meeting = graph.meeting_of(seed)
        if meeting is not None and not state.reach(
            meeting, 1, (seed, (_VIRTUAL, None)), position, None
        ):
            return False
    return True


def _related_under_issue(
    state: _Related, position: int, seed: RecordRef, issue_id: str, max_depth: int
) -> bool:
    """Step 3b: S3 section 7.2 step 3 from the seed under one visible Issue, to `max_depth`.

    The Issue context is fixed for the whole expansion, so a shared Meeting,
    Project, Series or participant never bridges 2 Issues (AT-006). Visited
    records are this expansion's own, so a record another seed reached first
    is still expanded here.
    """
    graph = state.graph
    inside = _members_in(graph, issue_id)
    if not state.reach(seed, 0, None, position, issue_id):
        return False
    seen = {seed}
    frontier = [seed]
    depth = 0
    while frontier and depth < max_depth and not graph.budget.exhausted:
        nxt: list[RecordRef] = []
        for node in sorted(frontier, key=lambda ref: (ref.family.value, ref.record_id)):
            if graph.out_of_time():
                return False
            extension = graph.extension(node)
            for head in graph.reader.incident(extension):
                if not _followable(head, issue_id, inside) or not state.admitted(head):
                    continue
                link = head.link
                near = link.from_ref if link.from_ref in extension else link.to_ref
                far = link.to_ref if near == link.from_ref else link.from_ref
                if not (graph.visible(near) and graph.visible(far)):
                    graph.restricted = True
                    continue
                if not graph.follow(head):
                    return False
                for ref, step in (
                    (near, (node, (_VIRTUAL, None))),
                    (far, (near, (_TYPED, link.link_id))),
                ):
                    if ref in seen:
                        continue
                    if not state.reach(ref, depth + 1, step, position, issue_id):
                        return False
                    seen.add(ref)
                    nxt.append(ref)
            if node.family is RecordFamily.MEETING_NOTE_VERSION:
                parent = graph.meeting_of(node)
                if parent is not None and parent not in seen:
                    if not state.reach(
                        parent, depth + 1, (node, (_VIRTUAL, None)), position, issue_id
                    ):
                        return False
                    seen.add(parent)
                    nxt.append(parent)
        frontier = nxt
        depth += 1
    return True


def related_digest(
    request: RelatedReadRequest,
    records: Sequence[RelatedRecordView],
    links: Sequence[AssociationView],
    virtual_edges: Sequence[VirtualEdgeView],
    codes: Collection[LineageCompleteness],
    *,
    remote: bool,
) -> str:
    """Step 8: `related_sha256` over the whole bounded result, without the read stamps.

    The items as this reader is answered them (a remote reader's without client
    ids, section 4.3), so the digest is of metadata the reader can read.
    """
    state, qualifiers = completeness(codes)
    document: dict[str, object] = {
        "schema_version": 1,
        "seeds": [_ref_document(seed) for seed in request.seeds],
        "max_depth": request.max_depth,
        "acceptance_bases": [basis.value for basis in request.acceptance_bases],
        "relation_types": [relation.value for relation in request.relation_types],
        "records": [record.to_canonical_dict() for record in records],
        "links": [link.to_canonical_dict() for link in links],
        "virtual_edges": [edge.to_canonical_dict() for edge in virtual_edges],
        "complete_state": state.value,
        "qualifiers": [code.value for code in qualifiers],
    }
    if remote:
        document = withhold_client_ids(document)
    body = LINEAGE_RELATED_DIGEST_PREFIX + canonical_json(document).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def bounded_related(
    source: RecordLineageRepository,
    principal_id: str,
    request: RelatedReadRequest,
    *,
    reader: _CurrentReader,
    visibility: LineageVisibility,
    deadline: float | None,
) -> RelatedBoundedResult:
    """Section 7.4 steps 1 to 5, 7 and 8: the traversal of every seed, before paging.

    The whole-query budgets are the S3 node and edge budgets; the byte bound
    applies per page. Hidden data is never emitted, expanded or counted.
    """
    graph = _Graph(reader, request.seeds[0], visibility, paged=True, deadline=deadline)
    for seed in request.seeds:
        _related_seed(graph, seed)
    state = _Related(graph, request)
    codes: set[LineageCompleteness] = set()
    for position, seed in enumerate(request.seeds):
        state.reach(seed, 0, None, position, None)
    for position, seed in enumerate(request.seeds):
        if graph.budget.exhausted or graph.deadline_hit:
            break
        if not _related_one_hop(state, position, seed):
            break
        pair = graph.extension(seed)
        matching = _matching_issues(graph, pair, root=seed)
        if len(matching) > MAX_MATCHING_ISSUES:
            codes.add(LineageCompleteness.TRUNCATED_BUDGET)
        stopped = False
        for issue_id in matching[:MAX_MATCHING_ISSUES]:
            if not _related_under_issue(state, position, seed, issue_id, request.max_depth):
                stopped = True
                break
        if stopped:
            break
    # Step 5 (S3 section 7.2): re-resolve every reached record natively.
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
        codes.add(LineageCompleteness.TRUNCATED_BUDGET)
    if dropped:
        codes.add(LineageCompleteness.PARTIAL_NATIVE_HISTORY)
    graph.load_issues(ref.record_id for ref in nodes if ref.family is RecordFamily.SITUATION)
    pairs = [
        (head.link, state.revision(head)) for head in sorted(heads, key=lambda h: h.link.link_id)
    ]
    edges, withheld = visible_association_views(source, principal_id, pairs, visibility, reader)
    if graph.restricted or withheld:
        codes.add(LineageCompleteness.RESTRICTED_EVIDENCE)
    records = tuple(
        RelatedRecordView(
            **_node_view(graph, ref).model_dump(),
            seeds=tuple(sorted(state.seeds_of[ref])),
            issue_ids=tuple(sorted(state.issues_of.get(ref, ())))[:MAX_MATCHING_ISSUES],
        )
        for ref in sorted(
            nodes, key=lambda ref: (graph.depth[ref], ref.family.value, ref.record_id)
        )
    )
    frozen = frozenset(codes)
    return RelatedBoundedResult(
        records=records,
        links=tuple(edges),
        virtual_edges=tuple(virtual),
        codes=frozen,
        deadline_hit=graph.deadline_hit,
        related_sha256=related_digest(
            request, records, edges, virtual, frozen, remote=visibility.remote
        ),
    )


def related_request_document(request: RelatedReadRequest) -> dict[str, object]:
    """The parsed request without its cursor, optional fields `null` (S3 section 5's `b`)."""
    return {
        "seeds": [_ref_document(seed) for seed in request.seeds],
        "max_depth": request.max_depth,
        "acceptance_bases": [basis.value for basis in request.acceptance_bases],
        "relation_types": [relation.value for relation in request.relation_types],
        "known_at": instant_token(request.known_at),
        "valid_at": instant_token(request.valid_at),
        "page_size": request.page_size,
    }


def _related_view(
    request: RelatedReadRequest,
    cuts: LineageReportedCuts,
    codes: Collection[LineageCompleteness],
    digest: str,
    items: Sequence[RelatedRecordView | AssociationView | VirtualEdgeView],
    next_cursor: str | None,
) -> RelatedRecordsView:
    state, qualifiers = completeness(codes)
    return RelatedRecordsView(
        seeds=tuple(_ref_view(seed) for seed in request.seeds),
        records=tuple(item for item in items if isinstance(item, RelatedRecordView)),
        links=tuple(item for item in items if isinstance(item, AssociationView)),
        virtual_edges=tuple(item for item in items if isinstance(item, VirtualEdgeView)),
        complete_state=state,
        qualifiers=qualifiers,
        known_at=cuts.known_at,
        valid_at=cuts.valid_at,
        lineage_valid_at=cuts.lineage_valid_at,
        native_cut_at=cuts.native_cut_at,
        related_sha256=digest,
        next_cursor=next_cursor,
    )


def _related_restart(request: RelatedReadRequest, cuts: LineageReportedCuts) -> RelatedRecordsView:
    """S3 section 7.2 step 7: `scope_changed_restart_required`, no item."""
    code = frozenset({LineageCompleteness.SCOPE_CHANGED_RESTART_REQUIRED})
    digest = related_digest(request, (), (), (), code, remote=False)
    return _related_view(request, cuts, code, digest, (), None)


def _related_document(
    item: RelatedRecordView | AssociationView | VirtualEdgeView, *, remote: bool
) -> object:
    document = item.to_canonical_dict()
    return withhold_client_ids(document) if remote else document


def _related_page(
    request: RelatedReadRequest,
    result: RelatedBoundedResult,
    cuts: LineageReportedCuts,
    *,
    after: str | None,
    remote: bool,
    cursor_for: Callable[[str], str],
) -> RelatedRecordsView | None:
    """Step 6: the items after `after`, up to `page_size` (or all) within 512 KiB.

    `None` when `after` is not an item of this result. Without a `page_size`
    the read is one page: what does not fit is dropped (`truncated_budget`).
    """
    items: list[RelatedRecordView | AssociationView | VirtualEdgeView] = [
        *result.records,
        *result.links,
        *result.virtual_edges,
    ]
    keys = [_item_key(item) for item in items]
    start = 0
    if after is not None:
        if after not in keys:
            return None
        start = keys.index(after) + 1
    limit = len(items) if request.page_size is None else request.page_size
    codes = set(result.codes)
    frame = _size(
        _related_view(
            request,
            cuts,
            codes | {LineageCompleteness.TRUNCATED_BUDGET},
            result.related_sha256,
            (),
            "x" * MAX_CURSOR_CHARACTERS,
        ).to_canonical_dict()
    )
    chosen: list[RelatedRecordView | AssociationView | VirtualEdgeView] = []
    size = frame
    for item in items[start:]:
        if len(chosen) >= limit:
            break
        grows = _size(_related_document(item, remote=remote)) + 1
        if chosen and size + grows > MAX_LINEAGE_BYTES:
            break
        chosen.append(item)
        size += grows
    end = start + len(chosen)
    more = end < len(items)
    next_cursor: str | None = None
    if more and request.page_size is None:
        codes.add(LineageCompleteness.TRUNCATED_BUDGET)
    elif more and chosen and not result.deadline_hit:
        next_cursor = cursor_for(keys[end - 1])
    return _related_view(request, cuts, codes, result.related_sha256, chosen, next_cursor)


def _checked_related_cursor(
    request: RelatedReadRequest, principal_id: str, *, horizon: datetime | None, now: datetime
) -> LineageCursor:
    """S3 section 7.2 step 7 for the related read: shape, binding, cuts."""
    try:
        cursor = decode_cursor(request.cursor, _lineage_position)
    except CursorMalformedError as error:
        raise InvalidRequestError(SafeDetail.CURSOR) from error
    if cursor.record_event_watermark is not None:
        raise InvalidRequestError(SafeDetail.CURSOR)
    expected = cursor_binding(
        capability=_RECORDS_LINEAGE_RELATED,
        principal_id=principal_id,
        request=related_request_document(request),
        known_at=cursor.known_at,
        lineage_valid_at=cursor.lineage_valid_at,
        native_cut_at=cursor.native_cut_at,
        record_event_watermark=None,
    )
    if cursor.binding != expected:
        raise ConflictError(SafeDetail.CURSOR)
    known, valid, native = cursor.known_at, cursor.lineage_valid_at, cursor.native_cut_at
    if known is not None and (horizon is None or known > horizon):
        raise InvalidRequestError(SafeDetail.CURSOR)
    if (known is None) is not (valid is None) or (
        known is not None and valid is not None and valid > known
    ):
        raise InvalidRequestError(SafeDetail.CURSOR)
    if native is None or native > now:
        raise InvalidRequestError(SafeDetail.CURSOR)
    for stated in (request.known_at, request.valid_at):
        if stated is not None and native > ensure_utc(stated):
            raise InvalidRequestError(SafeDetail.CURSOR)
    return cursor


def read_related_as_of(
    uow: UnitOfWork,
    principal_id: str,
    request: RelatedReadRequest,
    *,
    now: datetime,
    visibility: LineageVisibility,
) -> RelatedRecordsView:
    """`records.lineage.related` (S3.1 section 7.4): as of a cut, visibility-filtered, paged."""
    lineage = uow.record_lineage
    lineage.bound_read_statements(LINEAGE_STATEMENT_TIMEOUT_MS)
    at = ensure_utc(now)
    horizon = lineage.commit_horizon(principal_id)
    scope = scope_digest(visibility.grant_digest)
    cursor: LineageCursor | None = None
    if request.cursor is not None:
        cursor = _checked_related_cursor(request, principal_id, horizon=horizon, now=at)
        cuts = LineageReportedCuts(
            known_at=cursor.known_at,
            valid_at=request.valid_at if request.valid_at is not None else cursor.known_at,
            lineage_valid_at=cursor.lineage_valid_at,
            native_cut_at=cursor.native_cut_at,
        )
        if cursor.scope != scope:
            return _related_restart(request, cuts)
    else:
        try:
            cut = knowledge_cut(
                known_at=request.known_at, valid_at=request.valid_at, now=at, horizon=horizon
            )
        except CutAfterNowError as error:
            detail = SafeDetail.KNOWN_AT if error.field == "known_at" else SafeDetail.VALID_AT
            raise InvalidRequestError(detail) from error
        cuts = LineageReportedCuts(
            known_at=cut.known_at,
            valid_at=cut.valid_at,
            lineage_valid_at=cut.lineage_valid_at,
            native_cut_at=native_cut(
                known_at=request.known_at, valid_at=request.valid_at, read_time=at
            ),
        )
    t_v = cuts.lineage_valid_at
    fact_cut = LineageFactCut(
        watermark=None if t_v is None else lineage.commit_watermark(principal_id, t_v), at=t_v
    )
    native_cut_at = cuts.native_cut_at
    if native_cut_at is None:
        raise RepositoryFailureError
    result = bounded_related(
        lineage,
        principal_id,
        request,
        reader=_AsOfReader(lineage, principal_id, fact_cut, native_cut_at),
        visibility=visibility,
        deadline=_monotonic() + LINEAGE_DEADLINE_SECONDS,
    )
    binding = cursor_binding(
        capability=_RECORDS_LINEAGE_RELATED,
        principal_id=principal_id,
        request=related_request_document(request),
        known_at=cuts.known_at,
        lineage_valid_at=cuts.lineage_valid_at,
        native_cut_at=cuts.native_cut_at,
        record_event_watermark=None,
    )

    def cursor_for(position: str) -> str:
        return encode_cursor(
            LineageCursor(
                binding=binding,
                scope=scope,
                known_at=cuts.known_at,
                lineage_valid_at=cuts.lineage_valid_at,
                native_cut_at=cuts.native_cut_at,
                record_event_watermark=None,
                position=position,
            )
        )

    page = _related_page(
        request,
        result,
        cuts,
        after=None if cursor is None else str(cursor.position),
        remote=visibility.remote,
        cursor_for=cursor_for,
    )
    if page is None:
        # R3-F14, R3-F23: a position that is not an item of the recomputed result.
        return _related_restart(request, cuts)
    return page


# ---- S3.1 section 7.9: the `reports.commit` recompute of a lineage reference ----

#: S3.1 section 7.9: the total budget of one report's lineage recompute; each
#: statement runs under `min(2000, remaining)` ms (the S4 D-36 deadline hook).
LINEAGE_RECOMPUTE_BUDGET_SECONDS: Final = 5.0
_REFERENCE_INSTANT: Final = "%Y-%m-%dT%H:%M:%S.%fZ"


class _CutBeyondHorizonError(Exception):
    """The block's `known_at` lies after the Principal's commit horizon (or after now)."""


def _recomputed_related(
    lineage: RecordLineageRepository,
    principal_id: str,
    request: RelatedReadRequest,
    *,
    now: datetime,
    visibility: LineageVisibility,
    deadline: float,
) -> dict[str, object] | None:
    """Section 7.4 as one unpaged bounded result at the block's `known_at`: the `server` part.

    `None` when the traversal deadline ended the result early (a spent budget).
    """
    known_at = request.known_at
    horizon = lineage.commit_horizon(principal_id)
    if known_at is None or horizon is None or known_at > horizon or known_at > now:
        raise _CutBeyondHorizonError
    cut = knowledge_cut(known_at=known_at, valid_at=None, now=now, horizon=horizon)
    t_v = cut.lineage_valid_at
    fact_cut = LineageFactCut(
        watermark=None if t_v is None else lineage.commit_watermark(principal_id, t_v), at=t_v
    )
    native_cut_at = native_cut(known_at=known_at, valid_at=None, read_time=now)
    result = bounded_related(
        lineage,
        principal_id,
        request,
        reader=_AsOfReader(lineage, principal_id, fact_cut, native_cut_at),
        visibility=visibility,
        deadline=deadline,
    )
    if result.deadline_hit:
        return None
    state, qualifiers = completeness(result.codes)
    return {
        "related_sha256": result.related_sha256,
        "known_at": instant_token(cut.known_at),
        "complete_state": state.value,
        "qualifiers": [code.value for code in qualifiers],
        "record_count": len(result.records),
        **lineage_server_counts([link.to_canonical_dict() for link in result.links]),
    }


def recompute_lineage_reference(
    uow: UnitOfWork,
    principal_id: str,
    block: LineageReferenceBlock,
    *,
    visibility: LineageVisibility | None,
    now: datetime,
) -> dict[str, object]:
    """S3.1 section 7.9: the manifest's lineage section for one reference block.

    `visibility` is `None` when `records.lineage.related` does not admit the
    committing caller (its remote grant re-check); a seed of a family the
    caller cannot see is not admitted either: both record `not_attempted` and
    read nothing. Otherwise the section 7.4 computation runs for the block's
    seeds, filters and `known_at` (`valid_at` omitted) with the caller's
    visibility, as one unpaged bounded result, on the request's own work
    connection, under the 5000 ms total budget (`bounded_by_deadline`: a
    savepoint always rolled back, each statement at `min(2000, remaining)`
    ms). The server's `related_sha256` equal to the claim is
    `verified_at_commit`, else `changed_since_read`; a spent budget, a
    statement timeout, a missing seed or a `known_at` after the horizon is
    `recompute_failed` with its token and never refuses the commit.
    """
    if visibility is None or not all(visibility.sees(seed) for seed in block.seeds):
        return lineage_section(block)
    at = ensure_utc(now)
    request = RelatedReadRequest(
        seeds=block.seeds,
        max_depth=block.max_depth,
        acceptance_bases=block.acceptance_bases,
        relation_types=block.relation_types,
        known_at=datetime.strptime(block.known_at, _REFERENCE_INSTANT).replace(tzinfo=UTC),
    )
    lineage = uow.record_lineage
    deadline = time.monotonic() + LINEAGE_RECOMPUTE_BUDGET_SECONDS
    failure: LineageRecomputeFailure | None = None
    server: dict[str, object] | None = None
    try:
        with lineage.bounded_by_deadline(deadline):
            server = _recomputed_related(
                lineage, principal_id, request, now=at, visibility=visibility, deadline=deadline
            )
    except _CutBeyondHorizonError:
        failure = LineageRecomputeFailure.CUT_BEYOND_HORIZON
    except (NotFoundError, InvalidRequestError):
        # Section 7.4 step 1: a seed absent, foreign or not an Issue at the cut.
        failure = LineageRecomputeFailure.SEED_NOT_FOUND
    except LineageReadTimeoutError:
        # A statement cancelled at the remaining budget spent the budget.
        failure = (
            LineageRecomputeFailure.BUDGET_EXCEEDED
            if time.monotonic() >= deadline
            else LineageRecomputeFailure.STATEMENT_TIMEOUT
        )
    if failure is None and server is None:
        failure = LineageRecomputeFailure.BUDGET_EXCEEDED
    if failure is not None:
        return lineage_section(block, failure=failure)
    return lineage_section(block, server=server, families_seen=visibility.families)
