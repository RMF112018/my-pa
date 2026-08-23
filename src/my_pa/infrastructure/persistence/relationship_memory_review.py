"""Relationship Memory on the canonical Review surface, and the only promotion path.

**A candidate memory becomes memory here and nowhere else.** The public
`relationship_memory.create` path writes what the *user* typed, under the one
authority a direct write may carry (`USER_AUTHORED_PRIVATE_NOTE`); a
source-derived, rule-derived or model-derived candidate lives in
`relationship_memory_proposals` and enters `relationship_memories` only when a
reviewer accepts it through `decide_relationship_memory_review`. That is
`RM-AC-005`/`RM-AC-016`/`RM-API-AC-011`/`RM-API-AC-012`/`RM-P-AC-008`, and it is
structural rather than a rule a query could forget: the two record sets are
different tables, so an unaccepted proposal cannot appear in a memory read.

**This is the third subject kind on one Review surface, not a second surface.**
`goodnotes.py` established the shape — cases derived from the plane's own
proposal table, a `is_…_review_case` router, and a `decide_…` that appends to the
plane's own decision ledger — and `_Reviews.cases`/`_Reviews.decide` already
dispatch on which kind a case is. Reusing the shared `ProposalState`,
`RiskClass` and `Disposition` vocabularies as *values* is what lets a memory
proposal join that surface without widening any frozen capture-plane CHECK.

**The promoted authority is decided here, and never `user_authored_private_note`.**
Three cases, and each rests on what actually warrants the statement:

* **`CORRECT_AND_ACCEPT` → `USER_CONFIRMED_ASSERTION`.** The committed text is the
  reviewer's own words, not the proposer's, so no source can be said to back it;
  what stands behind it is a person who read the candidate and rewrote it. It is
  emphatically *not* `SOURCE_BACKED_ASSERTION`: the copied evidence bears on what
  was proposed, and a correction is the reviewer saying the proposal was wrong.
* **`ACCEPT` of an evidence-backed proposal → `SOURCE_BACKED_ASSERTION`.** The
  exact evidence records are copied forward against the new version
  (`RM-AC-015`), so the claim remains checkable against the records it came from,
  which is precisely what that authority asserts and what a bare confirmation
  does not.
* **`ACCEPT` of a proposal with no evidence → `USER_CONFIRMED_ASSERTION`.** There
  is nothing to be backed *by*; the only warrant is the human decision. Calling
  it source-backed would be a claim with no record behind it, and the honest
  weaker authority is the confirmation that really happened.

`PUBLIC_ASSERTION` is never written by this path — nothing here is externally
published or externally verifiable — and `USER_AUTHORED_PRIVATE_NOTE` never is,
because it means "the user wrote this", which a promotion did not. The version's
`created_by_actor` is `REVIEW_PROMOTION` throughout, which is also why the
schema's `a_user_written_memory_version_is_user_authored` CHECK does not fire:
that constraint binds the `user` actor, and this one is not it.

**Promotion re-validates the subject, and refuses rather than follows.** A
subject merged away between the proposal and the decision is a
`ReviewConflictError`, not a promotion onto the canonical successor: following
the redirect would bind a candidate raised about a historical identity to the
current person, which is a different statement than the one that was reviewed.
The same refusal covers a subject that has left this Principal's partition and a
Person-only kind whose subject is not a Person. `ReviewConflictError` rather than
a new error class because the service already routes it to a conflict answer and
the case is genuinely one: the world moved under a decision that named a stale
version of it.

**A second acceptance is refused, never duplicated.** Two independent guards:
any stored accepting disposition makes the case terminal, and a proposal already
carrying `accepted_memory_id` is refused even if its decision ledger were
somehow empty. Reject, defer and mark-unresolved write a decision row and
nothing else — no memory, no version, no evidence link.

Every statement reaches the partition through `persistence.principal_scope`, via
the same `_mine`/`_bound` one-line wrappers `relationship_memory.py` uses.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from my_pa.contracts.ports import ReviewDecisionRequest
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.review import (
    Disposition,
    ReviewConflictError,
    ReviewDecision,
    ReviewNotFoundError,
    ReviewUnsupportedError,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.entity import EntityStatus, EntityType
from my_pa.domain.relationship.memory import (
    EvidenceLinkRole,
    MemoryActorClass,
    MemoryAuthority,
    MemoryKind,
    MemoryKindNotPermittedError,
    MemoryLifecycle,
    MemoryProposalState,
    RelationshipMemoryReviewCase,
    check_kind_permits_subject,
    classification_floor_for,
    satisfies_floor,
    statement_digest,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    entities,
    relationship_memories,
    relationship_memory_evidence_links,
    relationship_memory_proposal_evidence,
    relationship_memory_proposals,
    relationship_memory_review_decisions,
    relationship_memory_versions,
)

__all__ = [
    "decide_relationship_memory_review",
    "is_relationship_memory_review_case",
    "relationship_memory_review_cases",
]

#: The dispositions that turn a candidate into memory.
_ACCEPTING: frozenset[Disposition] = frozenset(
    {
        Disposition.ACCEPT,
        Disposition.CORRECT_AND_ACCEPT,
    }
)

#: The stored proposal state each disposition leaves behind, where the closed
#: vocabulary has a member that says exactly that.
#:
#: `MARK_UNRESOLVED` maps to `None`, and the `None` is the decision rather than
#: an omission. `MemoryProposalState` deliberately declares no `unresolved`
#: member — the enum is what the schema's `a_memory_proposal_state_is_known`
#: CHECK is generated from, so inventing one would be a schema change this work
#: package is forbidden to make, and borrowing `invalidated` would report the
#: candidate's *evidence* as withdrawn when a reviewer only declined to settle
#: it. The decision row is the record in that case, and the review case reads its
#: state from the decision chain exactly as `goodnotes_review_cases` does, so
#: nothing is lost but a denormalized copy.
_STORED_STATE: dict[Disposition, MemoryProposalState | None] = {
    Disposition.ACCEPT: MemoryProposalState.ACCEPTED,
    Disposition.CORRECT_AND_ACCEPT: MemoryProposalState.CORRECTED_ACCEPTED,
    Disposition.REJECT: MemoryProposalState.REJECTED,
    Disposition.DEFER: MemoryProposalState.DEFERRED,
    Disposition.MARK_UNRESOLVED: None,
}

#: The public review state each disposition presents on the shared surface.
_CASE_STATE: dict[Disposition, ProposalState] = {
    Disposition.ACCEPT: ProposalState.ACCEPTED,
    Disposition.CORRECT_AND_ACCEPT: ProposalState.CORRECTED_ACCEPTED,
    Disposition.REJECT: ProposalState.REJECTED,
    Disposition.DEFER: ProposalState.DEFERRED,
    Disposition.MARK_UNRESOLVED: ProposalState.UNRESOLVED,
}


def _mine(table: Any, principal_id: str) -> Any:  # noqa: ANN401 - a SQLAlchemy Table
    """`table` constrained to the given Principal, through the one guard."""
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Any, principal_id: str, values: dict[str, object]) -> dict[str, object]:  # noqa: ANN401
    """`values` stamped with the given Principal for `table`, through the one guard."""
    return principal_bound_values(values, table, capture_context(principal_id))


def _memory_review_state(disposition: Disposition | None) -> ProposalState:
    """The review state a case presents, derived from its latest disposition."""
    if disposition is None:
        return ProposalState.NEEDS_REVIEW
    return _CASE_STATE[disposition]


def relationship_memory_review_cases(
    connection: Connection, *, principal_id: str, limit: int
) -> tuple[RelationshipMemoryReviewCase, ...]:
    """One bounded page of this Principal's memory proposals, oldest first.

    Only proposals that were actually routed to review are here: a row with no
    `review_case_id` was never opened as a case and has no identity a reviewer
    could decide against, so it is filtered in SQL rather than skipped in Python.

    `proposed_at` is the case's `opened_at`. The proposal table records no
    separate opening moment and adding one would be a migration; the moment the
    candidate was produced is the moment it became a thing awaiting a decision,
    which is what the ordering needs it for.
    """
    if limit < 1:
        raise ValueError("a review page contains at least one case")
    latest_sequence = (
        select(func.max(relationship_memory_review_decisions.c.sequence))
        .where(
            relationship_memory_review_decisions.c.review_case_id
            == relationship_memory_proposals.c.review_case_id
        )
        .correlate(relationship_memory_proposals)
        .scalar_subquery()
    )
    latest_disposition = (
        select(relationship_memory_review_decisions.c.disposition)
        .where(
            relationship_memory_review_decisions.c.review_case_id
            == relationship_memory_proposals.c.review_case_id
        )
        .order_by(relationship_memory_review_decisions.c.sequence.desc())
        .limit(1)
        .correlate(relationship_memory_proposals)
        .scalar_subquery()
    )
    rows = connection.execute(
        select(
            relationship_memory_proposals.c.review_case_id,
            relationship_memory_proposals.c.memory_proposal_id,
            relationship_memory_proposals.c.subject_entity_id,
            relationship_memory_proposals.c.principal_id,
            relationship_memory_proposals.c.proposed_kind,
            relationship_memory_proposals.c.proposed_at,
            relationship_memory_proposals.c.accepted_memory_id,
            relationship_memory_proposals.c.accepted_memory_version_id,
            func.coalesce(latest_sequence, 0).label("review_version"),
            latest_disposition.label("latest_disposition"),
        )
        .where(
            _mine(relationship_memory_proposals, principal_id),
            relationship_memory_proposals.c.review_case_id.is_not(None),
        )
        .order_by(
            relationship_memory_proposals.c.proposed_at,
            relationship_memory_proposals.c.review_case_id,
        )
        .limit(limit)
    ).mappings()
    cases: list[RelationshipMemoryReviewCase] = []
    for row in rows:
        disposition = (
            None if row["latest_disposition"] is None else Disposition(row["latest_disposition"])
        )
        cases.append(
            RelationshipMemoryReviewCase(
                review_case_id=row["review_case_id"],
                proposal_id=row["memory_proposal_id"],
                subject_entity_id=row["subject_entity_id"],
                principal_id=row["principal_id"],
                proposed_kind=MemoryKind(row["proposed_kind"]),
                opened_at=row["proposed_at"],
                proposal_state=_memory_review_state(disposition),
                review_version=int(row["review_version"]),
                latest_disposition=disposition,
                accepted_memory_id=row["accepted_memory_id"],
                accepted_memory_version_id=row["accepted_memory_version_id"],
            )
        )
    return tuple(cases)


def is_relationship_memory_review_case(
    connection: Connection, *, review_case_id: str, principal_id: str
) -> bool:
    """Whether `review_case_id` names a memory proposal this Principal holds.

    The router `_Reviews.decide` asks before dispatching. A case in another
    Principal's partition answers `False`, which sends the request down the
    capture route and out as "no such case" — the same answer an absent
    identifier gets, which is what stops a decision probe from confirming that a
    memory proposal exists.
    """
    return (
        connection.execute(
            select(relationship_memory_proposals.c.review_case_id).where(
                relationship_memory_proposals.c.review_case_id == review_case_id,
                _mine(relationship_memory_proposals, principal_id),
            )
        ).scalar_one_or_none()
        is not None
    )


def _promotion_authority(disposition: Disposition, *, evidence_count: int) -> MemoryAuthority:
    """The authority a promoted version carries. See this module's docstring."""
    if disposition is Disposition.CORRECT_AND_ACCEPT:
        return MemoryAuthority.USER_CONFIRMED_ASSERTION
    if evidence_count > 0:
        return MemoryAuthority.SOURCE_BACKED_ASSERTION
    return MemoryAuthority.USER_CONFIRMED_ASSERTION


def _promotion_classification(stored: Classification, kind: MemoryKind) -> Classification:
    """At least what the proposal claimed, and never below the kind's floor.

    Monotonic in the restrictive direction only. A proposal recorded as
    `RESTRICTED_LOCAL` stays restricted even for a kind whose floor is lower —
    the proposer had a reason and a promotion is not the place to relax it — and
    a proposal that somehow sat below its kind's floor is raised to it rather
    than written as-is, which the version's own CHECK would refuse anyway.
    """
    if satisfies_floor(stored, kind):
        return stored
    return classification_floor_for(kind)


def _writable_subject(connection: Connection, *, principal_id: str, entity_id: str) -> EntityType:
    """The subject's type, or a conflict. Merged-away subjects are refused, not followed."""
    row = connection.execute(
        select(
            entities.c.entity_type,
            entities.c.status,
        ).where(
            _mine(entities, principal_id),
            entities.c.entity_id == entity_id,
        )
    ).one_or_none()
    if row is None:
        raise ReviewConflictError("the promoted subject is no longer in this scope")
    if EntityStatus(row.status) is EntityStatus.MERGED_REDIRECT:
        raise ReviewConflictError("a merged-away subject cannot receive a promoted memory")
    return EntityType(row.entity_type)


def _copy_evidence(
    connection: Connection,
    *,
    principal_id: str,
    memory_proposal_id: str,
    memory_version_id: str,
) -> None:
    """Copy the proposal's exact basis onto the promoted version (`RM-AC-015`).

    Copied rather than repointed. `relationship_memory_proposal_evidence` is the
    proposal's own record and stays readable beside the decision that used it;
    the memory needs its basis on `relationship_memory_evidence_links`, where
    every other memory's basis lives and where the read paths already count it.
    A single shared row would make one delete reach both planes.
    """
    rows = connection.execute(
        select(
            relationship_memory_proposal_evidence.c.role,
            relationship_memory_proposal_evidence.c.entity_observation_id,
            relationship_memory_proposal_evidence.c.capture_span_id,
            relationship_memory_proposal_evidence.c.knowledge_id,
            relationship_memory_proposal_evidence.c.created_at,
        )
        .where(
            _mine(relationship_memory_proposal_evidence, principal_id),
            relationship_memory_proposal_evidence.c.memory_proposal_id == memory_proposal_id,
        )
        .order_by(relationship_memory_proposal_evidence.c.proposal_evidence_id)
    ).all()
    for row in rows:
        connection.execute(
            insert(relationship_memory_evidence_links).values(
                _bound(
                    relationship_memory_evidence_links,
                    principal_id,
                    {
                        "evidence_link_id": issue_identifier(
                            IdKind.RELATIONSHIP_MEMORY_EVIDENCE_LINK
                        ),
                        "memory_version_id": memory_version_id,
                        "role": EvidenceLinkRole(row.role).value,
                        "entity_observation_id": row.entity_observation_id,
                        "capture_span_id": row.capture_span_id,
                        "knowledge_id": row.knowledge_id,
                        "created_at": row.created_at,
                    },
                )
            )
        )


def _promote(
    connection: Connection,
    request: ReviewDecisionRequest,
    proposal: Any,  # noqa: ANN401 - a SQLAlchemy Row of the proposal's columns
    *,
    decision_id: str,
) -> tuple[str, str]:
    """Create the real memory this acceptance produced, in this transaction.

    Returns the aggregate and version identifiers the proposal is then stamped
    with. Nothing here is deferred to a later job: a promotion that committed the
    decision and left the memory to a queue would be a review whose result a
    reader could not find, and a queue entry is a second place the same rule
    would have to hold.

    The version's `idempotency_key` is the decision identifier. Every memory
    version records the key that admitted it, and for a promotion the admitting
    act is the reviewer's decision — a synthesized key would name nothing, and
    the public path's submission ledger is not written here because a promotion
    is not a replayable client write. Its idempotency is the terminal-acceptance
    rule above plus the unique `(review_case_id, sequence)` on the ledger.
    """
    kind = MemoryKind(proposal.proposed_kind)
    entity_type = _writable_subject(
        connection, principal_id=request.principal_id, entity_id=proposal.subject_entity_id
    )
    try:
        check_kind_permits_subject(kind, entity_type)
    except MemoryKindNotPermittedError as exc:
        raise ReviewConflictError("the proposed kind does not describe this subject") from exc

    corrected = request.disposition is Disposition.CORRECT_AND_ACCEPT
    statement = str(request.corrected_value) if corrected else str(proposal.proposed_statement)
    evidence_count = int(
        connection.execute(
            select(func.count())
            .select_from(relationship_memory_proposal_evidence)
            .where(
                _mine(relationship_memory_proposal_evidence, request.principal_id),
                relationship_memory_proposal_evidence.c.memory_proposal_id
                == proposal.memory_proposal_id,
            )
        ).scalar_one()
    )
    memory_id = issue_identifier(IdKind.RELATIONSHIP_MEMORY)
    memory_version_id = issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION)
    connection.execute(
        insert(relationship_memories).values(
            _bound(
                relationship_memories,
                request.principal_id,
                {
                    "memory_id": memory_id,
                    "subject_entity_id": proposal.subject_entity_id,
                    "memory_kind": kind.value,
                    "lifecycle_state": MemoryLifecycle.ACTIVE.value,
                    "current_version_id": memory_version_id,
                    "current_version_number": 1,
                    "version": 1,
                    "pinned": False,
                    "created_at": request.decided_at,
                    "updated_at": request.decided_at,
                    "archived_at": None,
                },
            )
        )
    )
    connection.execute(
        insert(relationship_memory_versions).values(
            _bound(
                relationship_memory_versions,
                request.principal_id,
                {
                    "memory_version_id": memory_version_id,
                    "memory_id": memory_id,
                    "version_number": 1,
                    "statement_text": statement,
                    "statement_sha256": statement_digest(statement),
                    "structured_value": proposal.structured_value,
                    "memory_kind": kind.value,
                    "authority": _promotion_authority(
                        request.disposition, evidence_count=evidence_count
                    ).value,
                    "classification": _promotion_classification(
                        Classification(proposal.classification), kind
                    ).value,
                    "cloud_eligible": False,
                    "created_by_actor": MemoryActorClass.REVIEW_PROMOTION.value,
                    "observed_at": None,
                    "effective_from": None,
                    "effective_to": None,
                    "recorded_at": request.decided_at,
                    "prior_version_id": None,
                    "correction_reason": None,
                    "proposal_id": proposal.memory_proposal_id,
                    "review_case_id": request.review_case_id,
                    "idempotency_key": decision_id,
                    "correlation_id": request.correlation_id,
                },
            )
        )
    )
    _copy_evidence(
        connection,
        principal_id=request.principal_id,
        memory_proposal_id=proposal.memory_proposal_id,
        memory_version_id=memory_version_id,
    )
    return memory_id, memory_version_id


def decide_relationship_memory_review(
    connection: Connection, request: ReviewDecisionRequest
) -> ReviewDecision:
    """Append one disposition and, for an acceptance, promote in the same transaction.

    The order is deliberate: the case is located and locked, the terminal and
    stale-version refusals run, the promotion runs, and only then is the decision
    row appended and the proposal stamped. A refused promotion therefore leaves
    no decision row to explain and no sequence number consumed, which is what
    makes "reject, defer and mark-unresolved leave no memory" and "a refused
    acceptance leaves no decision" the same statement about one transaction.
    """
    proposal = connection.execute(
        select(
            relationship_memory_proposals.c.memory_proposal_id,
            relationship_memory_proposals.c.subject_entity_id,
            relationship_memory_proposals.c.proposed_kind,
            relationship_memory_proposals.c.proposed_statement,
            relationship_memory_proposals.c.structured_value,
            relationship_memory_proposals.c.classification,
            relationship_memory_proposals.c.accepted_memory_id,
        )
        .where(
            relationship_memory_proposals.c.review_case_id == request.review_case_id,
            _mine(relationship_memory_proposals, request.principal_id),
        )
        .with_for_update(of=relationship_memory_proposals)
    ).one_or_none()
    if proposal is None:
        raise ReviewNotFoundError("the request names no stored review case")
    decisions = connection.execute(
        select(
            relationship_memory_review_decisions.c.sequence,
            relationship_memory_review_decisions.c.disposition,
        )
        .where(relationship_memory_review_decisions.c.review_case_id == request.review_case_id)
        .order_by(relationship_memory_review_decisions.c.sequence)
    ).all()
    if any(Disposition(row.disposition) in _ACCEPTING for row in decisions):
        raise ReviewConflictError("an accepted review case is terminal")
    if proposal.accepted_memory_id is not None:
        # Belt and braces against the ledger and the proposal disagreeing: the
        # stamp is the durable evidence that a memory already exists, and a
        # second promotion would create a duplicate that no reader could tell
        # from a genuine second memory about the same subject.
        raise ReviewConflictError("this proposal has already produced a memory")
    current = len(decisions)
    if current != request.expected_review_version:
        raise ReviewConflictError("the expected review version is stale")
    if request.disposition in {Disposition.REPROCESS, Disposition.ESCALATE}:
        raise ReviewUnsupportedError("the requested disposition has no eligible route")

    sequence = current + 1
    decision_id = issue_identifier(IdKind.REVIEW_DECISION)
    promoted: tuple[str, str] | None = None
    if request.disposition in _ACCEPTING:
        promoted = _promote(connection, request, proposal, decision_id=decision_id)
    connection.execute(
        insert(relationship_memory_review_decisions).values(
            _bound(
                relationship_memory_review_decisions,
                request.principal_id,
                {
                    "decision_id": decision_id,
                    "memory_proposal_id": proposal.memory_proposal_id,
                    "review_case_id": request.review_case_id,
                    "sequence": sequence,
                    "disposition": request.disposition.value,
                    "corrected_statement": request.corrected_value,
                    "correlation_id": request.correlation_id,
                    "audit_id": request.audit_id,
                    "decided_at": request.decided_at,
                },
            )
        )
    )
    stored_state = _STORED_STATE[request.disposition]
    if stored_state is not None:
        connection.execute(
            update(relationship_memory_proposals)
            .where(
                _mine(relationship_memory_proposals, request.principal_id),
                relationship_memory_proposals.c.memory_proposal_id == proposal.memory_proposal_id,
            )
            .values(
                state=stored_state.value,
                accepted_memory_id=None if promoted is None else promoted[0],
                accepted_memory_version_id=None if promoted is None else promoted[1],
            )
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
        proposal_state=_memory_review_state(request.disposition),
        normalized_value=request.corrected_value,
    )
