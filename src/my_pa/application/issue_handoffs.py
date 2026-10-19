"""The responsibility handoff ledger, record lineage S2 (S2 contract sections 3.4, 6 and 7.2).

`IssueHandoffApplication` is stateless and takes the unit of work
`ApplicationService.invoke` has **already opened**, the authenticated
`principal_id` as a plain parameter, the parsed request and, for the write,
the attested authority pair and the authorization time. It opens no
transaction: the reservation, locks, the event and the request completion run
in the caller's one transaction, so a refusal leaves no row and no request.

**A handoff is never inferred.** Only `issues.handoffs.record` writes one: a
Commitment close, a Task transition, a composite create, an Issue close and a
membership change write none, and a handoff changes no native field.

**Order of `issues.handoffs.record`** (section 6.3): request digest;
reservation (a replay answers from the stored event); the Commitment, the
Issue and the anchor's source `FOR SHARE` in `(family token, identifier)`
order, each `not_found` with its own subject when absent or foreign (so a
foreign Commitment answers like an absent one); the closed-Issue rule
(`conflict` / `state`); the Commitment an active member of the Issue
(`invalid_request` / `commitment_id`); the anchor admitted by the S1 rules;
the business-time rules against now and the Commitment's creation; the
chain's advisory key; the chain's last event, the business-time rule against
it and the holder resolution (`domain.lineage.handoff`, R2-F02); the anchor,
the event and the completion.

**Holders are the server's.** The request names only the side the
responsibility leaves; the leaving holder is the chain's last holder (or, for
event 1, the Principal or the Commitment's current counterparty) and the
arriving one the other side, with the counterparty read now. A request naming
the wrong side is `invalid_request` / `from`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from my_pa.application.errors import ConflictError, InvalidRequestError, NotFoundError, SafeDetail
from my_pa.application.lineage_endpoints import (
    EvidenceAnchorInput,
    admit_evidence_set,
    insert_evidence_anchor,
    lock_lineage_sources,
    require_open_issues,
)
from my_pa.application.record_lineage import anchor_view
from my_pa.contracts.ports import (
    HandoffRecord,
    HandoffSequenceConflictError,
    LineageLinkEvidence,
    RepositoryFailureError,
    UnitOfWork,
)
from my_pa.contracts.v1.issues import HandoffHolderView, HandoffView
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.operation import Capability
from my_pa.domain.lineage.canonical import request_digest
from my_pa.domain.lineage.handoff import HandoffHolder, HandoffSideError, resolve_handoff
from my_pa.domain.lineage.model import RecordRef
from my_pa.domain.lineage.vocabulary import (
    AcceptanceBasis,
    EvidenceSourceFamily,
    HandoffHolderKind,
    HandoffSide,
    RecordFamily,
)
from my_pa.domain.source.registry import issue_identifier

if TYPE_CHECKING:
    from my_pa.application.lineage_authority import LineageAuthority

__all__ = [
    "DEFAULT_HANDOFF_PAGE_SIZE",
    "MAX_HANDOFF_PAGE_SIZE",
    "HandoffListRequest",
    "HandoffListResult",
    "HandoffRecordRequest",
    "HandoffResult",
    "IssueHandoffApplication",
    "handoff_document",
]

_RECORD: Final = Capability.ISSUES_HANDOFFS_RECORD.value

#: `issues.handoffs.list` page bounds (section 7.2).
DEFAULT_HANDOFF_PAGE_SIZE: Final = 25
MAX_HANDOFF_PAGE_SIZE: Final = 100


@dataclass(frozen=True, slots=True)
class HandoffRecordRequest:
    """`issues.handoffs.record`, parsed: `effective_at` is an aware instant."""

    issue_id: str
    commitment_id: str
    side: HandoffSide
    effective_at: datetime
    reason: str
    evidence_anchor: EvidenceAnchorInput


@dataclass(frozen=True, slots=True)
class HandoffListRequest:
    """`issues.handoffs.list`, parsed."""

    issue_id: str
    commitment_id: str | None
    page_size: int
    after: str | None


@dataclass(frozen=True, slots=True)
class HandoffResult:
    """What `issues.handoffs.record` answers."""

    handoff: HandoffView
    replayed: bool


@dataclass(frozen=True, slots=True)
class HandoffListResult:
    """One `issues.handoffs.list` page and its keyset cursor."""

    handoffs: tuple[HandoffView, ...]
    next_cursor: str | None


def _instant(value: datetime) -> str:
    """Section 5: the UTC ISO-8601 string of the parsed instant."""
    return value.astimezone(UTC).isoformat()


def handoff_document(request: HandoffRecordRequest) -> dict[str, object]:
    """The request as its digest holds it (S2 section 5)."""
    return {
        "issue_id": request.issue_id,
        "commitment_id": request.commitment_id,
        "from": request.side.value,
        "effective_at": _instant(request.effective_at),
        "reason": request.reason,
        "evidence_anchor": request.evidence_anchor.digest_document(),
    }


def _holder(kind: str, entity_id: str | None) -> HandoffHolder:
    return HandoffHolder(kind=HandoffHolderKind(kind), entity_id=entity_id)


def _holder_view(kind: str, entity_id: str | None) -> HandoffHolderView:
    return HandoffHolderView(kind=HandoffHolderKind(kind), entity_id=entity_id)


def _view(uow: UnitOfWork, principal_id: str, event: HandoffRecord) -> HandoffView:
    """One event's view; its anchor's availability computed now (S1 F19)."""
    anchor = event.evidence.anchor
    roots = (
        frozenset()
        if anchor.source_family is EvidenceSourceFamily.MEETING_NOTE_VERSION
        else frozenset({anchor.source_root_id})
    )
    archived = uow.record_lineage.archived_capture_roots(principal_id, roots)
    return HandoffView(
        handoff_id=event.handoff_id,
        issue_id=event.issue_id,
        commitment_id=event.commitment_id,
        sequence_no=event.sequence_no,
        from_holder=_holder_view(event.from_holder_kind, event.from_entity_id),
        to_holder=_holder_view(event.to_holder_kind, event.to_entity_id),
        effective_at=event.effective_at,
        recorded_at=event.recorded_at,
        reason=event.reason,
        evidence=anchor_view(event.evidence, archived),
        acceptance_basis=AcceptanceBasis(event.acceptance_basis),
        authority_class=event.authority_class,
    )


@dataclass(frozen=True, slots=True)
class IssueHandoffApplication:
    """`issues.handoffs.record` and `issues.handoffs.list`."""

    def record_handoff(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: HandoffRecordRequest,
        idempotency_key: str,
        authority: LineageAuthority,
        now: datetime,
    ) -> HandoffResult:
        """Append the next event of one `(Issue, Commitment)` chain (section 3.4)."""
        at = ensure_utc(now)
        issues, lineage, handoffs = uow.issues, uow.record_lineage, uow.issue_handoffs
        digest = request_digest(_RECORD, principal_id, handoff_document(request))
        prior = issues.reserve_write_request(
            principal_id, _RECORD, idempotency_key, digest, created_at=at
        )
        if prior is not None:
            if prior.result_handoff_id is None:
                raise RepositoryFailureError
            stored = handoffs.read_event(principal_id, prior.result_handoff_id)
            if stored is None:
                raise RepositoryFailureError
            return HandoffResult(handoff=_view(uow, principal_id, stored), replayed=True)
        # S3 section 6.2 step 1b: the commit mark, before any other lock.
        uow.record_lineage.take_commit_mark(principal_id)
        subject = RecordRef(family=RecordFamily.COMMITMENT, record_id=request.commitment_id)
        locked = lock_lineage_sources(
            issues,
            lineage,
            principal_id,
            issue_ids=((request.issue_id, SafeDetail.ISSUE_ID),),
            endpoints=((subject, SafeDetail.COMMITMENT_ID),),
            anchors=(request.evidence_anchor,),
            anchor_detail=SafeDetail.EVIDENCE_ANCHOR,
        )
        require_open_issues(locked)
        if lineage.active_membership(principal_id, request.issue_id, subject) is None:
            raise InvalidRequestError(SafeDetail.COMMITMENT_ID)
        (anchor,) = admit_evidence_set(
            issues, principal_id, locked.evidence, detail=SafeDetail.EVIDENCE_ANCHOR
        )
        commitment = uow.commitments.get(principal_id, request.commitment_id)
        if commitment is None:
            # Shared above under the same Principal: unreachable.
            raise NotFoundError(SafeDetail.COMMITMENT_ID)
        effective_at = ensure_utc(request.effective_at)
        if effective_at > at or effective_at < commitment.created_at:
            raise InvalidRequestError(SafeDetail.EFFECTIVE_AT)
        handoffs.lock_chain(principal_id, request.issue_id, request.commitment_id)
        last = handoffs.latest_event(principal_id, request.issue_id, request.commitment_id)
        if last is not None and effective_at < last.effective_at:
            raise InvalidRequestError(SafeDetail.EFFECTIVE_AT)
        refused = False
        try:
            leaving, arriving = resolve_handoff(
                request.side,
                last_holder=None
                if last is None
                else _holder(last.to_holder_kind, last.to_entity_id),
                counterparty_entity_id=commitment.counterparty_entity_id,
            )
        except HandoffSideError:
            refused = True
        if refused:
            raise InvalidRequestError(SafeDetail.FROM_RECORD)
        event = HandoffRecord(
            handoff_id=issue_identifier(IdKind.ISSUE_HANDOFF),
            issue_id=request.issue_id,
            commitment_id=request.commitment_id,
            sequence_no=1 if last is None else last.sequence_no + 1,
            predecessor_sequence_no=None if last is None else last.sequence_no,
            from_holder_kind=leaving.kind.value,
            from_entity_id=leaving.entity_id,
            to_holder_kind=arriving.kind.value,
            to_entity_id=arriving.entity_id,
            effective_at=effective_at,
            recorded_at=at,
            evidence=LineageLinkEvidence(
                anchor_id=insert_evidence_anchor(issues, principal_id, anchor, recorded_at=at),
                anchor=anchor,
            ),
            reason=request.reason,
            acceptance_basis=AcceptanceBasis.USER_CONFIRMED.value,
            authority_class=authority.authority_class.value,
            decision_channel=authority.decision_channel.value,
            source_capability=_RECORD,
        )
        lost = False
        try:
            handoffs.insert_event(principal_id, event)
        except HandoffSequenceConflictError:
            lost = True
        if lost:
            raise ConflictError(SafeDetail.STALE_VERSION)
        issues.complete_write_request(
            principal_id,
            _RECORD,
            idempotency_key,
            request_digest=digest,
            completed_at=at,
            result_handoff_id=event.handoff_id,
        )
        return HandoffResult(handoff=_view(uow, principal_id, event), replayed=False)

    def list_handoffs(
        self, uow: UnitOfWork, principal_id: str, request: HandoffListRequest
    ) -> HandoffListResult:
        """One keyset page, `(recorded_at, handoff_id)` ascending; lock-free.

        An absent or foreign Issue or Commitment is `not_found`, alike; an
        owned Commitment with no event in this Issue is an empty page.
        """
        if uow.issues.read_issue(principal_id, request.issue_id) is None:
            raise NotFoundError(SafeDetail.ISSUE_ID)
        if (
            request.commitment_id is not None
            and uow.commitments.get(principal_id, request.commitment_id) is None
        ):
            raise NotFoundError(SafeDetail.COMMITMENT_ID)
        page = uow.issue_handoffs.list_events(
            principal_id,
            request.issue_id,
            commitment_id=request.commitment_id,
            page_size=request.page_size,
            after=request.after,
        )
        views = tuple(_view(uow, principal_id, event) for event in page.handoffs)
        return HandoffListResult(
            handoffs=views,
            next_cursor=views[-1].handoff_id if page.has_more and views else None,
        )
