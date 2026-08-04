"""Review routing, dispositions, promotion, and source-edit revalidation.

All functions run on the caller's transaction. Canonical assertions can be
created only by :func:`promote_proposal`, and that function requires a stored
accepting decision for the same proposal. There is no direct-promotion mode.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from my_pa.contracts.ports import ReviewDecisionRequest
from my_pa.domain.capture.assertion import ACCEPTED_RECORD_TYPE, AssertionState
from my_pa.domain.capture.proposal import ProposalState, ProposalType, RiskClass
from my_pa.domain.capture.review import (
    Disposition,
    ReviewCase,
    ReviewConflictError,
    ReviewDecision,
    ReviewNotFoundError,
    ReviewRequiredError,
    ReviewUnsupportedError,
)
from my_pa.domain.capture.version import digest_of
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.proposals import invalidate_proposal, span_faults
from my_pa.infrastructure.persistence.tables import (
    capture_assertion_spans,
    capture_assertions,
    capture_promotion_receipts,
    capture_proposal_spans,
    capture_proposals,
    capture_review_cases,
    capture_review_decisions,
    capture_spans,
    capture_versions,
)

__all__ = [
    "decide_review",
    "mark_changed_assertions_for_revalidation",
    "open_review_case",
    "promote_proposal",
    "review_cases",
    "routes_to_review",
]


def routes_to_review(proposal_type: ProposalType, risk_class: RiskClass) -> bool:
    """Whether policy opens a case for this proposal.

    Commitments and decisions are consequential regardless of confidence or the
    extractor's risk label. Any high/critical proposal is also routed. Low-risk
    technical enrichment remains useful without mandatory review.
    """
    return proposal_type in {ProposalType.COMMITMENT, ProposalType.DECISION} or risk_class in {
        RiskClass.HIGH,
        RiskClass.CRITICAL,
    }


def open_review_case(connection: Connection, proposal_id: str) -> str | None:
    """Open one case when the proposal is consequential; otherwise return None."""
    validate_identifier(proposal_id, IdKind.PROPOSAL)
    row = connection.execute(
        select(
            capture_proposals.c.version_id,
            capture_proposals.c.proposal_type,
            capture_proposals.c.risk_class,
            capture_versions.c.capture_id,
        )
        .join(capture_versions, capture_versions.c.version_id == capture_proposals.c.version_id)
        .where(capture_proposals.c.proposal_id == proposal_id)
    ).one()
    if not routes_to_review(ProposalType(row.proposal_type), RiskClass(row.risk_class)):
        return None
    review_case_id = issue_identifier(IdKind.REVIEW_CASE)
    inserted = connection.execute(
        pg_insert(capture_review_cases)
        .values(
            review_case_id=review_case_id,
            proposal_id=proposal_id,
            capture_id=row.capture_id,
            version_id=row.version_id,
        )
        .on_conflict_do_nothing(index_elements=[capture_review_cases.c.proposal_id])
        .returning(capture_review_cases.c.review_case_id)
    ).scalar_one_or_none()
    if inserted is not None:
        connection.execute(
            capture_proposals.update()
            .where(capture_proposals.c.proposal_id == proposal_id)
            .values(state=ProposalState.NEEDS_REVIEW.value)
        )
        return str(inserted)
    return str(
        connection.execute(
            select(capture_review_cases.c.review_case_id).where(
                capture_review_cases.c.proposal_id == proposal_id
            )
        ).scalar_one()
    )


def review_cases(connection: Connection, *, limit: int) -> tuple[ReviewCase, ...]:
    """Read one bounded page, oldest first, with current version derived from rows."""
    if limit < 1:
        raise ValueError("a review page contains at least one case")
    latest_sequence = (
        select(func.max(capture_review_decisions.c.sequence))
        .where(capture_review_decisions.c.review_case_id == capture_review_cases.c.review_case_id)
        .correlate(capture_review_cases)
        .scalar_subquery()
    )
    latest_disposition = (
        select(capture_review_decisions.c.disposition)
        .where(capture_review_decisions.c.review_case_id == capture_review_cases.c.review_case_id)
        .order_by(capture_review_decisions.c.sequence.desc())
        .limit(1)
        .correlate(capture_review_cases)
        .scalar_subquery()
    )
    rows = connection.execute(
        select(
            capture_review_cases.c.review_case_id,
            capture_review_cases.c.proposal_id,
            capture_review_cases.c.capture_id,
            capture_review_cases.c.version_id,
            capture_review_cases.c.opened_at,
            capture_proposals.c.proposal_type,
            capture_proposals.c.state,
            capture_proposals.c.risk_class,
            func.coalesce(latest_sequence, 0).label("review_version"),
            latest_disposition.label("latest_disposition"),
        )
        .join(
            capture_proposals, capture_proposals.c.proposal_id == capture_review_cases.c.proposal_id
        )
        .order_by(capture_review_cases.c.opened_at, capture_review_cases.c.review_case_id)
        .limit(limit)
    ).all()
    return tuple(
        ReviewCase(
            review_case_id=str(row.review_case_id),
            proposal_id=str(row.proposal_id),
            capture_id=str(row.capture_id),
            version_id=str(row.version_id),
            proposal_type=ProposalType(row.proposal_type),
            proposal_state=ProposalState(row.state),
            risk_class=RiskClass(row.risk_class),
            opened_at=row.opened_at,
            review_version=int(row.review_version),
            latest_disposition=(
                None if row.latest_disposition is None else Disposition(row.latest_disposition)
            ),
        )
        for row in rows
    )


def decide_review(connection: Connection, request: ReviewDecisionRequest) -> ReviewDecision | None:
    """Append a reachable disposition and perform its one transition."""
    case = connection.execute(
        select(
            capture_review_cases.c.proposal_id,
            capture_review_cases.c.version_id,
            capture_proposals.c.state,
        )
        .join(
            capture_proposals, capture_proposals.c.proposal_id == capture_review_cases.c.proposal_id
        )
        .where(capture_review_cases.c.review_case_id == request.review_case_id)
        .with_for_update(of=capture_review_cases)
    ).one_or_none()
    if case is None:
        raise ReviewNotFoundError("the request names no stored review case")
    current = int(
        connection.execute(
            select(func.count())
            .select_from(capture_review_decisions)
            .where(capture_review_decisions.c.review_case_id == request.review_case_id)
        ).scalar_one()
    )
    if current != request.expected_review_version:
        raise ReviewConflictError("the expected review version is stale")
    if request.disposition in {Disposition.REPROCESS, Disposition.ESCALATE}:
        raise ReviewUnsupportedError("the requested disposition has no eligible route")
    if request.disposition in {Disposition.ACCEPT, Disposition.CORRECT_AND_ACCEPT}:
        faults = span_faults(connection, str(case.proposal_id))
        if faults:
            invalidate_proposal(connection, str(case.proposal_id), faults[0].reason)
            return None

    decision_id = issue_identifier(IdKind.REVIEW_DECISION)
    sequence = current + 1
    connection.execute(
        capture_review_decisions.insert().values(
            decision_id=decision_id,
            review_case_id=request.review_case_id,
            sequence=sequence,
            disposition=request.disposition.value,
            principal_id=request.principal_id,
            correlation_id=request.correlation_id,
            audit_id=request.audit_id,
            decided_at=request.decided_at,
        )
    )

    assertion_id: str | None = None
    receipt_id: str | None = None
    if request.disposition in {Disposition.ACCEPT, Disposition.CORRECT_AND_ACCEPT}:
        assertion_id, receipt_id = promote_proposal(
            connection,
            proposal_id=str(case.proposal_id),
            decision_id=decision_id,
            policy_version=request.policy_version,
            accepted_at=request.decided_at,
            corrected_value=request.corrected_value,
        )
        state = (
            ProposalState.CORRECTED_ACCEPTED
            if request.disposition is Disposition.CORRECT_AND_ACCEPT
            else ProposalState.ACCEPTED
        )
    else:
        state = {
            Disposition.REJECT: ProposalState.REJECTED,
            Disposition.DEFER: ProposalState.DEFERRED,
            Disposition.MARK_UNRESOLVED: ProposalState.UNRESOLVED,
        }[request.disposition]
        connection.execute(
            capture_proposals.update()
            .where(capture_proposals.c.proposal_id == case.proposal_id)
            .values(state=state.value)
        )

    return ReviewDecision(
        decision_id=decision_id,
        review_case_id=request.review_case_id,
        sequence=sequence,
        disposition=request.disposition,
        principal_id=request.principal_id,
        correlation_id=request.correlation_id,
        audit_id=request.audit_id,
        decided_at=request.decided_at,
        proposal_state=state,
        assertion_id=assertion_id,
        receipt_id=receipt_id,
        normalized_value=request.corrected_value,
    )


def promote_proposal(
    connection: Connection,
    *,
    proposal_id: str,
    decision_id: str | None,
    policy_version: str,
    accepted_at: datetime,
    corrected_value: str | None = None,
) -> tuple[str, str]:
    """Promote only under a stored accepting decision for this proposal."""
    validate_identifier(proposal_id, IdKind.PROPOSAL)
    if decision_id is None:
        raise ReviewRequiredError("canonical promotion requires a review disposition")
    validate_identifier(decision_id, IdKind.REVIEW_DECISION)
    row = connection.execute(
        select(
            capture_proposals.c.version_id,
            capture_proposals.c.proposal_type,
            capture_proposals.c.normalized_value,
            capture_review_decisions.c.disposition,
        )
        .join(
            capture_review_cases,
            capture_review_cases.c.proposal_id == capture_proposals.c.proposal_id,
        )
        .join(
            capture_review_decisions,
            capture_review_decisions.c.review_case_id == capture_review_cases.c.review_case_id,
        )
        .where(
            capture_proposals.c.proposal_id == proposal_id,
            capture_review_decisions.c.decision_id == decision_id,
        )
    ).one_or_none()
    if row is None or Disposition(row.disposition) not in {
        Disposition.ACCEPT,
        Disposition.CORRECT_AND_ACCEPT,
    }:
        raise ReviewRequiredError("canonical promotion requires an accepting disposition")
    disposition = Disposition(row.disposition)
    if (disposition is Disposition.CORRECT_AND_ACCEPT) is not (corrected_value is not None):
        raise ReviewRequiredError("the correction must match its accepting disposition")
    if span_faults(connection, proposal_id):
        raise ReviewRequiredError("canonical promotion requires valid source spans")

    assertion_id = issue_identifier(IdKind.ASSERTION)
    receipt_id = issue_identifier(IdKind.RECEIPT)
    value = corrected_value if corrected_value is not None else row.normalized_value
    connection.execute(
        capture_assertions.insert().values(
            assertion_id=assertion_id,
            version_id=row.version_id,
            proposal_id=proposal_id,
            decision_id=decision_id,
            assertion_type=row.proposal_type,
            state=AssertionState.ACCEPTED.value,
            normalized_value=value,
            accepted_at=accepted_at,
        )
    )
    span_rows = connection.execute(
        select(capture_proposal_spans.c.span_id).where(
            capture_proposal_spans.c.proposal_id == proposal_id
        )
    ).all()
    connection.execute(
        capture_assertion_spans.insert(),
        [{"assertion_id": assertion_id, "span_id": row.span_id} for row in span_rows],
    )
    state = (
        ProposalState.CORRECTED_ACCEPTED if corrected_value is not None else ProposalState.ACCEPTED
    )
    connection.execute(
        capture_proposals.update()
        .where(capture_proposals.c.proposal_id == proposal_id)
        .values(
            state=state.value,
            accepted_record_type=ACCEPTED_RECORD_TYPE,
            accepted_record_id=assertion_id,
        )
    )
    connection.execute(
        capture_promotion_receipts.insert().values(
            receipt_id=receipt_id,
            assertion_id=assertion_id,
            decision_id=decision_id,
            policy_version=policy_version,
            issued_at=accepted_at,
        )
    )
    return assertion_id, receipt_id


def mark_changed_assertions_for_revalidation(
    connection: Connection,
    *,
    prior_version_id: str,
    successor_content: str,
    at: datetime,
) -> int:
    """Mark accepted assertions whose cited slice no longer re-derives."""
    capture_id = connection.execute(
        select(capture_versions.c.capture_id).where(
            capture_versions.c.version_id == prior_version_id
        )
    ).scalar_one()
    rows = connection.execute(
        select(
            capture_assertions.c.assertion_id,
            capture_spans.c.start_offset,
            capture_spans.c.end_offset,
            capture_spans.c.quoted_text_sha256,
        )
        .join(
            capture_versions,
            capture_versions.c.version_id == capture_assertions.c.version_id,
        )
        .join(
            capture_assertion_spans,
            capture_assertion_spans.c.assertion_id == capture_assertions.c.assertion_id,
        )
        .join(capture_spans, capture_spans.c.span_id == capture_assertion_spans.c.span_id)
        .where(
            capture_versions.c.capture_id == capture_id,
            capture_assertions.c.state == AssertionState.ACCEPTED.value,
        )
    ).all()
    changed: set[str] = set()
    for row in rows:
        start, end = int(row.start_offset), int(row.end_offset)
        if end > len(successor_content) or digest_of(successor_content[start:end]) != str(
            row.quoted_text_sha256
        ):
            changed.add(str(row.assertion_id))
    if changed:
        connection.execute(
            update(capture_assertions)
            .where(capture_assertions.c.assertion_id.in_(changed))
            .values(
                state=AssertionState.REVALIDATION_REQUIRED.value,
                revalidation_required_at=at,
            )
        )
    return len(changed)
