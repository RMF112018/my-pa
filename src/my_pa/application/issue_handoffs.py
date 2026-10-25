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

**S3** (S3 contract sections 3.3, 3.4, 7.1 and 7.4). `issues.handoffs.correct`
appends one immutable correction -- `retime` (a new current effective time) or
`void` (the event did not happen; only the chain's last live event, and
terminal) -- and never changes the event. Its order: request digest;
reservation (a replay answers from the stored correction, with the handoff as
it stood right after it); the commit mark; the handoff by Principal-scoped
existence (`not_found` / `handoff_id`); its Issue, Commitment and the anchor's
source `FOR SHARE`; the closed-Issue rule (`conflict` / `state`); the anchor;
the chain's `:handoff:` key (so a correction and a new handoff of one chain
serialize); the chain and its corrections; a voided event is `conflict` /
`state`; then the section 3.3 rules. The chain **skips voided events**: a new
handoff follows the last live event (its arriving holder, at or after its
current effective time) and, when none is live, the S2 event-1 rule.
`issues.handoffs.list` answers as known at `known_at` (section 3.4):
events and corrections with a mark at or below `W(T_k)`, or pre-S3 rows
recorded by `T_k`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

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
    insert_evidence_anchor,
    lock_lineage_sources,
    require_open_issues,
)
from my_pa.application.lineage_rate import require_client_write_budget
from my_pa.application.record_lineage import anchor_view, open_write_digest, reserve_open_write
from my_pa.contracts.ports import (
    HandoffCorrectionRecord,
    HandoffRecord,
    HandoffSequenceConflictError,
    LineageLinkEvidence,
    RepositoryFailureError,
    UnitOfWork,
)
from my_pa.contracts.v1.issues import HandoffCorrectionView, HandoffHolderView, HandoffView
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.operation import Capability
from my_pa.domain.lineage.asof import CutAfterNowError, effective_known_at
from my_pa.domain.lineage.handoff import (
    ChainEvent,
    HandoffCorrectionFact,
    HandoffHolder,
    HandoffSideError,
    can_void,
    chain_state,
    last_live,
    resolve_handoff,
    retime_in_order,
)
from my_pa.domain.lineage.model import RecordRef
from my_pa.domain.lineage.vocabulary import (
    AcceptanceBasis,
    EvidenceSourceFamily,
    HandoffCorrectionAction,
    HandoffHolderKind,
    HandoffSide,
    RecordFamily,
)
from my_pa.domain.source.registry import issue_identifier

if TYPE_CHECKING:
    from my_pa.application.lineage_authority import LineageProvenance

__all__ = [
    "DEFAULT_HANDOFF_PAGE_SIZE",
    "MAX_HANDOFF_PAGE_SIZE",
    "HandoffCorrectRequest",
    "HandoffCorrectResult",
    "HandoffListRequest",
    "HandoffListResult",
    "HandoffRecordRequest",
    "HandoffResult",
    "IssueHandoffApplication",
    "handoff_document",
]

_RECORD: Final = Capability.ISSUES_HANDOFFS_RECORD.value
_CORRECT: Final = Capability.ISSUES_HANDOFFS_CORRECT.value

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
    """`issues.handoffs.list`, parsed. S3 adds `known_at` (an aware instant or `None`)."""

    issue_id: str
    commitment_id: str | None
    page_size: int
    after: str | None
    known_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class HandoffCorrectRequest:
    """`issues.handoffs.correct`, parsed: `effective_at` is set exactly for a `retime`."""

    handoff_id: str
    action: HandoffCorrectionAction
    effective_at: datetime | None
    reason: str
    evidence_anchor: EvidenceAnchorInput


@dataclass(frozen=True, slots=True)
class HandoffResult:
    """What `issues.handoffs.record` answers."""

    handoff: HandoffView
    replayed: bool


@dataclass(frozen=True, slots=True)
class HandoffListResult:
    """One `issues.handoffs.list` page, its keyset cursor and its `known_at` (`T_k`)."""

    handoffs: tuple[HandoffView, ...]
    next_cursor: str | None
    known_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class HandoffCorrectResult:
    """What `issues.handoffs.correct` answers: the correction and the handoff after it."""

    correction: HandoffCorrectionView
    handoff: HandoffView
    replayed: bool


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


def correction_document(request: HandoffCorrectRequest) -> dict[str, object]:
    """The correction request as its digest holds it (S3 section 5)."""
    return {
        "handoff_id": request.handoff_id,
        "action": request.action.value,
        "effective_at": None if request.effective_at is None else _instant(request.effective_at),
        "reason": request.reason,
        "evidence_anchor": request.evidence_anchor.digest_document(),
    }


def _facts(corrections: Sequence[HandoffCorrectionRecord]) -> tuple[HandoffCorrectionFact, ...]:
    return tuple(
        HandoffCorrectionFact(
            correction_no=correction.correction_no,
            action=HandoffCorrectionAction(correction.action),
            corrected_effective_at=correction.corrected_effective_at,
        )
        for correction in corrections
    )


def _chain(
    events: Sequence[HandoffRecord],
    corrections: Mapping[str, Sequence[HandoffCorrectionRecord]],
) -> tuple[ChainEvent, ...]:
    """Each event of one chain folded with its corrections (section 3.3)."""
    return tuple(
        chain_state(
            event.sequence_no,
            event.effective_at,
            _facts(corrections.get(event.handoff_id, ())),
        )
        for event in events
    )


def _archived(uow: UnitOfWork, principal_id: str, cited: LineageLinkEvidence) -> frozenset[str]:
    anchor = cited.anchor
    roots = (
        frozenset()
        if anchor.source_family is EvidenceSourceFamily.MEETING_NOTE_VERSION
        else frozenset({anchor.source_root_id})
    )
    return uow.record_lineage.archived_capture_roots(principal_id, roots)


def _correction_view(
    uow: UnitOfWork, principal_id: str, correction: HandoffCorrectionRecord
) -> HandoffCorrectionView:
    """One correction's view; its anchor's availability computed now (S1 F19)."""
    return HandoffCorrectionView(
        correction_id=correction.correction_id,
        handoff_id=correction.handoff_id,
        correction_no=correction.correction_no,
        action=HandoffCorrectionAction(correction.action),
        effective_at=correction.corrected_effective_at,
        reason=correction.reason,
        evidence=anchor_view(
            correction.evidence, _archived(uow, principal_id, correction.evidence)
        ),
        recorded_at=correction.recorded_at,
        authority_class=correction.authority_class,
        acceptance_basis=AcceptanceBasis(correction.acceptance_basis),
        user_directed_claim=correction.user_directed_claim,
        asserting_client_id=correction.asserting_client_id,
    )


def _holder(kind: str, entity_id: str | None) -> HandoffHolder:
    return HandoffHolder(kind=HandoffHolderKind(kind), entity_id=entity_id)


def _holder_view(kind: str, entity_id: str | None) -> HandoffHolderView:
    return HandoffHolderView(kind=HandoffHolderKind(kind), entity_id=entity_id)


def _view(
    uow: UnitOfWork,
    principal_id: str,
    event: HandoffRecord,
    corrections: Sequence[HandoffCorrectionRecord] = (),
) -> HandoffView:
    """One event's view with its known corrections; its anchor's availability computed now."""
    archived = _archived(uow, principal_id, event.evidence)
    folded = chain_state(event.sequence_no, event.effective_at, _facts(corrections))
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
        user_directed_claim=event.user_directed_claim,
        asserting_client_id=event.asserting_client_id,
        current_effective_at=folded.current_effective_at,
        voided=folded.voided,
        correction_ids=tuple(
            correction.correction_id
            for correction in sorted(corrections, key=lambda item: item.correction_no)
        ),
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
        authority: LineageProvenance,
        now: datetime,
    ) -> HandoffResult:
        """Append the next event of one `(Issue, Commitment)` chain (section 3.4).

        S3.1: any admitted caller may record a handoff (it chains from the last
        live event and removes nothing); a client's is counted against its
        write budgets before the event is written.
        """
        at = ensure_utc(now)
        issues, lineage, handoffs = uow.issues, uow.record_lineage, uow.issue_handoffs
        digest = open_write_digest(_RECORD, principal_id, handoff_document(request), authority)
        prior = reserve_open_write(
            issues, principal_id, _RECORD, idempotency_key, digest, authority, at
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
        # S3 section 3.3: the chain skips voided events. The new event follows
        # the last live one (its holder, at or after its current effective
        # time); with none live, the S2 event-1 rule applies.
        events = handoffs.chain_events(principal_id, request.issue_id, request.commitment_id)
        chain = _chain(
            events,
            handoffs.corrections_of(
                principal_id, [event.handoff_id for event in events], current=True
            ),
        )
        live = last_live(chain)
        holder = (
            None
            if live is None
            else next(event for event in events if event.sequence_no == live.sequence_no)
        )
        if live is not None and effective_at < live.current_effective_at:
            raise InvalidRequestError(SafeDetail.EFFECTIVE_AT)
        refused = False
        try:
            leaving, arriving = resolve_handoff(
                request.side,
                last_holder=None
                if holder is None
                else _holder(holder.to_holder_kind, holder.to_entity_id),
                counterparty_entity_id=commitment.counterparty_entity_id,
            )
        except HandoffSideError:
            refused = True
        if refused:
            raise InvalidRequestError(SafeDetail.FROM_RECORD)
        require_client_write_budget(uow, principal_id, authority, authority.asserting_client_id, at)
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
            acceptance_basis=authority.acceptance_basis.value,
            authority_class=authority.authority_class.value,
            decision_channel=authority.decision_channel.value,
            source_capability=_RECORD,
            asserting_client_id=authority.asserting_client_id,
            user_directed_claim=authority.user_directed_claim,
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
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: HandoffListRequest,
        now: datetime,
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
        # S3 section 3.4: events and corrections as known at `T_k`.
        known_at = _known_at(uow, principal_id, request.known_at, now)
        watermark = (
            None
            if known_at is None
            else uow.record_lineage.commit_watermark(principal_id, known_at)
        )
        page = uow.issue_handoffs.known_events(
            principal_id,
            request.issue_id,
            commitment_id=request.commitment_id,
            page_size=request.page_size,
            after=request.after,
            watermark=watermark,
            at=known_at,
        )
        corrections = uow.issue_handoffs.corrections_of(
            principal_id,
            [event.handoff_id for event in page.handoffs],
            watermark=watermark,
            at=known_at,
        )
        views = tuple(
            _view(uow, principal_id, event, corrections.get(event.handoff_id, ()))
            for event in page.handoffs
        )
        return HandoffListResult(
            handoffs=views,
            next_cursor=views[-1].handoff_id if page.has_more and views else None,
            known_at=known_at,
        )

    # --- issues.handoffs.correct (S3 section 3.3) --------------------------------

    def correct_handoff(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: HandoffCorrectRequest,
        idempotency_key: str,
        authority: LineageProvenance,
        now: datetime,
    ) -> HandoffCorrectResult:
        """Append one `retime` or `void` correction of one handoff event.

        S3.1 (section 4.4, the handoff analogue): a client may not correct a
        handoff the human channel accepted -- the event or any of its
        corrections `user_confirmed` -- (`denied`, under the chain lock), and
        its correction is counted against its budgets before it is written.
        """
        at = ensure_utc(now)
        issues, lineage, handoffs = uow.issues, uow.record_lineage, uow.issue_handoffs
        digest = open_write_digest(_CORRECT, principal_id, correction_document(request), authority)
        prior = reserve_open_write(
            issues, principal_id, _CORRECT, idempotency_key, digest, authority, at
        )
        if prior is not None:
            return _replayed_correction(uow, principal_id, prior.result_handoff_correction_id)
        # S3 section 6.2 step 1b: the commit mark, before any other lock.
        lineage.take_commit_mark(principal_id)
        event = handoffs.read_event(principal_id, request.handoff_id)
        if event is None:
            raise NotFoundError(SafeDetail.HANDOFF_ID)
        subject = RecordRef(family=RecordFamily.COMMITMENT, record_id=event.commitment_id)
        locked = lock_lineage_sources(
            issues,
            lineage,
            principal_id,
            issue_ids=((event.issue_id, SafeDetail.ISSUE_ID),),
            endpoints=((subject, SafeDetail.COMMITMENT_ID),),
            anchors=(request.evidence_anchor,),
            anchor_detail=SafeDetail.EVIDENCE_ANCHOR,
        )
        # S3 section 3.2: a closed Issue's handoffs are frozen; reopen first.
        require_open_issues(locked)
        (anchor,) = admit_evidence_set(
            issues, principal_id, locked.evidence, detail=SafeDetail.EVIDENCE_ANCHOR
        )
        commitment = uow.commitments.get(principal_id, event.commitment_id)
        if commitment is None:
            # Shared above under the same Principal: unreachable.
            raise NotFoundError(SafeDetail.COMMITMENT_ID)
        handoffs.lock_chain(principal_id, event.issue_id, event.commitment_id)
        events = handoffs.chain_events(principal_id, event.issue_id, event.commitment_id)
        existing = handoffs.corrections_of(
            principal_id, [item.handoff_id for item in events], current=True
        )
        if authority.acceptance_basis is AcceptanceBasis.CLIENT_IDENTIFIED and (
            event.acceptance_basis == AcceptanceBasis.USER_CONFIRMED.value
            or any(
                correction.acceptance_basis == AcceptanceBasis.USER_CONFIRMED.value
                for correction in existing.get(event.handoff_id, ())
            )
        ):
            # S3.1 section 4.4: the history rule, under the chain's key.
            raise DeniedError()
        chain = _chain(events, existing)
        target = next(item for item in chain if item.sequence_no == event.sequence_no)
        if target.voided:
            raise ConflictError(SafeDetail.STATE)
        effective_at = None if request.effective_at is None else ensure_utc(request.effective_at)
        if request.action is HandoffCorrectionAction.VOID:
            if not can_void(chain, event.sequence_no):
                raise InvalidRequestError(SafeDetail.HANDOFF_ID)
        elif effective_at is None or not retime_in_order(
            chain,
            event.sequence_no,
            effective_at,
            commitment_created_at=commitment.created_at,
            recorded_at=at,
        ):
            raise InvalidRequestError(SafeDetail.EFFECTIVE_AT)
        require_client_write_budget(uow, principal_id, authority, authority.asserting_client_id, at)
        earlier = existing.get(event.handoff_id, ())
        number = len(earlier) + 1
        correction = HandoffCorrectionRecord(
            correction_id=issue_identifier(IdKind.ISSUE_HANDOFF_CORRECTION),
            handoff_id=event.handoff_id,
            correction_no=number,
            predecessor_correction_no=None if number == 1 else number - 1,
            action=request.action.value,
            corrected_effective_at=effective_at,
            evidence=LineageLinkEvidence(
                anchor_id=insert_evidence_anchor(issues, principal_id, anchor, recorded_at=at),
                anchor=anchor,
            ),
            reason=request.reason,
            acceptance_basis=authority.acceptance_basis.value,
            authority_class=authority.authority_class.value,
            decision_channel=authority.decision_channel.value,
            source_capability=_CORRECT,
            recorded_at=at,
            asserting_client_id=authority.asserting_client_id,
            user_directed_claim=authority.user_directed_claim,
        )
        handoffs.insert_correction(principal_id, correction)
        issues.complete_write_request(
            principal_id,
            _CORRECT,
            idempotency_key,
            request_digest=digest,
            completed_at=at,
            result_handoff_correction_id=correction.correction_id,
        )
        return HandoffCorrectResult(
            correction=_correction_view(uow, principal_id, correction),
            handoff=_view(uow, principal_id, event, (*earlier, correction)),
            replayed=False,
        )


def _known_at(
    uow: UnitOfWork, principal_id: str, requested: datetime | None, now: datetime
) -> datetime | None:
    """`T_k` for a handoff read (S3 section 3.4); `invalid_request` / `known_at` after now."""
    try:
        return effective_known_at(
            None if requested is None else ensure_utc(requested),
            now=ensure_utc(now),
            horizon=uow.record_lineage.commit_horizon(principal_id),
        )
    except CutAfterNowError as error:
        raise InvalidRequestError(SafeDetail.KNOWN_AT) from error


def _replayed_correction(
    uow: UnitOfWork, principal_id: str, correction_id: str | None
) -> HandoffCorrectResult:
    """Section 6.3 replay: the stored correction and the handoff as it stood right after it."""
    if correction_id is None:
        raise RepositoryFailureError
    handoffs = uow.issue_handoffs
    correction = handoffs.read_correction(principal_id, correction_id)
    if correction is None:
        raise RepositoryFailureError
    event = handoffs.read_event(principal_id, correction.handoff_id)
    if event is None:
        raise RepositoryFailureError
    upto = tuple(
        item
        for item in handoffs.corrections_of(principal_id, (event.handoff_id,), current=True).get(
            event.handoff_id, ()
        )
        if item.correction_no <= correction.correction_no
    )
    return HandoffCorrectResult(
        correction=_correction_view(uow, principal_id, correction),
        handoff=_view(uow, principal_id, event, upto),
        replayed=True,
    )
