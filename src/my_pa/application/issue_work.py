"""The composite Work writes, record lineage S2 (S2 contract sections 3.1, 6.2, 6.4 and 7.2).

`issues.work.create_task` and `issues.work.create_commitment` are one
capability each whose one transaction performs a native create, the new
record's Issue membership and its association intents (CR-006).
`IssueWorkApplication` is stateless and takes the unit of work
`ApplicationService.invoke` has **already opened**; the native create is a
callable the service hands in, which runs exactly the v1 `tasks.create` /
`commitments.create` body on that same unit of work. Nothing here opens a
transaction, so any refusal -- before or after the native create -- rolls back
the native row, its history receipt, its staged Record Event, the links and
the request together.

**Order** (sections 6.2 and 6.3): request digest; reservation (the lineage
request row is the composite's only idempotency record; a replay rebuilds the
answer from the immutable link revisions the request names and never re-runs
the native create); the Issue, every intent target and every evidence source
`FOR SHARE` in `(family token, identifier)` order, each `not_found` with its
own subject; the closed-Issue rule; the Project qualification (a nested
`project_id` needs an active Project link to the Issue, its triplet row
shared); every anchor set admitted and every intent's section 3.1 assert-time
rule; the native create; then the identity locks of the new links (they name
the new record, so they cannot precede it), all in ascending
`normalized_identity` order; then the membership (ordinal 1, role `work`) and
the intents (ordinals 2..5, request order) and their request-link rows; the
completion.

**The intent rules** (section 3.1, assert time only): `originated_from` keeps
its S1 rule; `delegated_from` (a Commitment only) needs an exact `origin`
anchor, an `owed_to_principal` Commitment (`direction`) and a Task that is an
active member of the Issue (`to`), neither terminal nor archived
(`endpoint`); `created_to_resolve` states a `purpose` (stored as revision 1's
`reason`) and targets the composite's own Issue or a Constraint that is an
active member of it (`to`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.application.lineage_endpoints import (
    EvidenceAnchorInput,
    admit_evidence_set,
    anchor_inputs_document,
    lock_lineage_sources,
    require_linkable,
    require_open_issues,
    require_relation_evidence,
)
from my_pa.application.record_lineage import association_views, insert_new_link
from my_pa.contracts.ports import (
    LineageEndpoint,
    LineageWriteRequestRecord,
    LinkRevisionRecord,
    RecordLinkRecord,
    RepositoryFailureError,
    UnitOfWork,
)
from my_pa.contracts.v1.record_lineage import AssociationView
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.lineage.canonical import normalized_identity, request_digest
from my_pa.domain.lineage.model import EvidenceAnchor, RecordRef
from my_pa.domain.lineage.vocabulary import (
    MemberRole,
    RecordFamily,
    RecordLinkKind,
    RelationType,
)
from my_pa.domain.situation.continuity import CommitmentDirection
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.lifecycle import TERMINAL_TASK_LIFECYCLE_STATES

if TYPE_CHECKING:
    from my_pa.application.lineage_authority import LineageAuthority

__all__ = [
    "AssociationIntent",
    "IssueWorkApplication",
    "NativeCreated",
    "WorkCompositeRequest",
    "WorkCompositeResult",
]

_TERMINAL_TASK_STATES = frozenset(state.value for state in TERMINAL_TASK_LIFECYCLE_STATES)


@dataclass(frozen=True, slots=True)
class AssociationIntent:
    """One parsed association intent: the new record is `from`, the Issue the context."""

    relation_type: RelationType
    to_ref: RecordRef
    evidence_anchors: tuple[EvidenceAnchorInput, ...]
    purpose: str | None

    def digest_document(self) -> dict[str, object]:
        """The intent as the request digest holds it (S2 section 5)."""
        return {
            "relation_type": self.relation_type.value,
            "to": {"family": self.to_ref.family.value, "record_id": self.to_ref.record_id},
            "evidence_anchors": anchor_inputs_document(self.evidence_anchors),
            "purpose": self.purpose,
        }


@dataclass(frozen=True, slots=True)
class WorkCompositeRequest:
    """One composite, parsed.

    `native_key` is `task` or `commitment`; `native_document` the nested
    native object as the native command's fields (every optional field
    present, instants as UTC ISO-8601 strings, enums by value), which only the
    digest reads. `project_id` and `direction` are the two native fields the
    lineage rules read.
    """

    capability: str
    issue_id: str
    family: RecordFamily
    native_key: str
    native_document: Mapping[str, object]
    project_id: str | None
    direction: CommitmentDirection | None
    membership_evidence_anchors: tuple[EvidenceAnchorInput, ...]
    association_intents: tuple[AssociationIntent, ...]

    def digest_document(self) -> dict[str, object]:
        """The request as its digest holds it (S2 section 5)."""
        return {
            "issue_id": self.issue_id,
            self.native_key: dict(self.native_document),
            "membership_evidence_anchors": anchor_inputs_document(self.membership_evidence_anchors),
            "association_intents": [
                intent.digest_document() for intent in self.association_intents
            ],
        }


@dataclass(frozen=True, slots=True)
class NativeCreated:
    """The record the native create wrote, and its native `version`."""

    ref: RecordRef
    version: int


@dataclass(frozen=True, slots=True)
class WorkCompositeResult:
    """What a composite answers (section 6.4); the native record's own view is not echoed."""

    record: RecordRef
    membership: AssociationView
    associations: tuple[AssociationView, ...]
    replayed: bool


def _require_member(uow: UnitOfWork, principal_id: str, issue_id: str, member: RecordRef) -> None:
    if uow.record_lineage.active_membership(principal_id, issue_id, member) is None:
        raise InvalidRequestError(SafeDetail.TO_RECORD)


def _require_intent_rule(
    uow: UnitOfWork,
    principal_id: str,
    request: WorkCompositeRequest,
    intent: AssociationIntent,
    target: LineageEndpoint,
    anchors: tuple[EvidenceAnchor, ...],
) -> None:
    """Section 3.1's assert-time rule for one intent (the command already refused shapes)."""
    issue_ref = RecordRef(family=RecordFamily.SITUATION, record_id=request.issue_id)
    # The evidence rule reads only the `to` version (`originated_from`) or the
    # anchors alone (`delegated_from`); the new record's id is not needed.
    require_relation_evidence(intent.relation_type, issue_ref, intent.to_ref, anchors)
    if intent.relation_type is RelationType.DELEGATED_FROM:
        if request.direction is not CommitmentDirection.OWED_TO_PRINCIPAL:
            raise InvalidRequestError(SafeDetail.DIRECTION)
        _require_member(uow, principal_id, request.issue_id, intent.to_ref)
        if target.task_archived or target.native_state in _TERMINAL_TASK_STATES:
            raise InvalidRequestError(SafeDetail.ENDPOINT)
    elif (
        intent.relation_type is RelationType.CREATED_TO_RESOLVE
        and intent.to_ref.family is RecordFamily.CONSTRAINT
    ):
        _require_member(uow, principal_id, request.issue_id, intent.to_ref)


@dataclass(frozen=True, slots=True)
class IssueWorkApplication:
    """`issues.work.create_task` and `issues.work.create_commitment`."""

    def create(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: WorkCompositeRequest,
        idempotency_key: str,
        authority: LineageAuthority,
        now: datetime,
        native_create: Callable[[], NativeCreated],
    ) -> WorkCompositeResult:
        """The native create, its `work` membership and its intents, or nothing."""
        at = ensure_utc(now)
        issues, lineage = uow.issues, uow.record_lineage
        capability = request.capability
        digest = request_digest(capability, principal_id, request.digest_document())
        prior = issues.reserve_write_request(
            principal_id, capability, idempotency_key, digest, created_at=at
        )
        if prior is not None:
            return self._replayed(uow, principal_id, capability, idempotency_key, prior)
        issue_ref = RecordRef(family=RecordFamily.SITUATION, record_id=request.issue_id)
        intents = request.association_intents
        for intent in intents:
            if (
                intent.relation_type is RelationType.CREATED_TO_RESOLVE
                and intent.to_ref.family is RecordFamily.SITUATION
                and intent.to_ref.record_id != request.issue_id
            ):
                raise InvalidRequestError(SafeDetail.TO_RECORD)
        membership_anchors = request.membership_evidence_anchors
        locked = lock_lineage_sources(
            issues,
            lineage,
            principal_id,
            issue_ids=((request.issue_id, SafeDetail.ISSUE_ID),),
            endpoints=tuple((intent.to_ref, SafeDetail.TO_RECORD) for intent in intents),
            anchors=membership_anchors
            + tuple(anchor for intent in intents for anchor in intent.evidence_anchors),
        )
        require_open_issues(locked)
        if request.project_id is not None and not issues.share_active_project_link(
            principal_id, request.project_id, request.issue_id
        ):
            raise InvalidRequestError(SafeDetail.PROJECT_ID)
        offset = len(membership_anchors)
        membership_set = admit_evidence_set(issues, principal_id, locked.evidence[:offset])
        admitted: list[tuple[AssociationIntent, tuple[EvidenceAnchor, ...]]] = []
        for intent in intents:
            target = locked.endpoints[intent.to_ref]
            require_linkable(issues, principal_id, target)
            size = len(intent.evidence_anchors)
            anchors = admit_evidence_set(
                issues, principal_id, locked.evidence[offset : offset + size]
            )
            offset += size
            _require_intent_rule(uow, principal_id, request, intent, target, anchors)
            admitted.append((intent, anchors))
        created = native_create()
        record = created.ref
        roots = [
            self._root(
                issue_ref,
                record,
                RelationType.ISSUE_MEMBER,
                request.issue_id,
                authority,
                capability,
                at,
            ),
            *(
                self._root(
                    record,
                    intent.to_ref,
                    intent.relation_type,
                    request.issue_id,
                    authority,
                    capability,
                    at,
                )
                for intent, _ in admitted
            ),
        ]
        # Section 6.2 step 6: the new links' identity keys, taken only now and
        # in ascending identity order; each is fresh by construction.
        for identity in sorted({root.normalized_identity for root in roots}):
            lineage.lock_identity(principal_id, identity)
        for root in roots:
            if lineage.active_head_by_identity(principal_id, root.normalized_identity) is not None:
                raise RepositoryFailureError
        revisions = [
            insert_new_link(
                uow, principal_id, roots[0], membership_set, at, member_version=created.version
            ),
            *(
                insert_new_link(uow, principal_id, root, anchors, at, reason=intent.purpose)
                for root, (intent, anchors) in zip(roots[1:], admitted, strict=True)
            ),
        ]
        issues.insert_write_request_links(
            principal_id,
            capability,
            idempotency_key,
            [
                (ordinal, root.link_id, revision.revision_no)
                for ordinal, (root, revision) in enumerate(zip(roots, revisions, strict=True), 1)
            ],
        )
        issues.complete_write_request(
            principal_id,
            capability,
            idempotency_key,
            request_digest=digest,
            completed_at=at,
            result_record_family=record.family.value,
            result_record_id=record.record_id,
        )
        views = association_views(lineage, principal_id, list(zip(roots, revisions, strict=True)))
        return WorkCompositeResult(
            record=record, membership=views[0], associations=views[1:], replayed=False
        )

    @staticmethod
    def _root(
        from_ref: RecordRef,
        to_ref: RecordRef,
        relation: RelationType,
        issue_id: str,
        authority: LineageAuthority,
        capability: str,
        at: datetime,
    ) -> RecordLinkRecord:
        membership = relation is RelationType.ISSUE_MEMBER
        kind = RecordLinkKind.ISSUE_MEMBERSHIP if membership else RecordLinkKind.SEMANTIC
        role = MemberRole.WORK if membership else None
        return RecordLinkRecord(
            link_id=issue_identifier(IdKind.RECORD_LINK),
            kind=kind,
            from_ref=from_ref,
            to_ref=to_ref,
            relation_type=relation,
            member_role=role,
            context_issue_id=issue_id,
            normalized_identity=normalized_identity(
                kind=kind,
                relation_type=relation,
                from_ref=from_ref,
                to_ref=to_ref,
                member_role=role,
                context_issue_id=issue_id,
            ),
            authority_class=authority.authority_class.value,
            decision_channel=authority.decision_channel.value,
            source_capability=capability,
            created_at=at,
        )

    @staticmethod
    def _replayed(
        uow: UnitOfWork,
        principal_id: str,
        capability: str,
        idempotency_key: str,
        prior: LineageWriteRequestRecord,
    ) -> WorkCompositeResult:
        """Section 6.4 replay: the stored record and link revisions, never a native write."""
        lineage = uow.record_lineage
        family, record_id = prior.result_record_family, prior.result_record_id
        links = uow.issues.write_request_links(principal_id, capability, idempotency_key)
        if family is None or record_id is None or not links:
            raise RepositoryFailureError
        pairs: list[tuple[RecordLinkRecord, LinkRevisionRecord]] = []
        for _ordinal, link_id, revision_no in links:
            link = lineage.read_link(principal_id, link_id)
            revision = lineage.read_revision(principal_id, link_id, revision_no)
            if link is None or revision is None:
                raise RepositoryFailureError
            pairs.append((link, revision))
        views = association_views(lineage, principal_id, pairs)
        return WorkCompositeResult(
            record=RecordRef(family=RecordFamily(family), record_id=record_id),
            membership=views[0],
            associations=views[1:],
            replayed=True,
        )
