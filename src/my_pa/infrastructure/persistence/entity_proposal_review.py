"""Entity proposals on the canonical Review surface, and their decision ledger.

**The fourth subject kind on one Review surface, not a second surface.**
`goodnotes.py` established the shape — cases derived from the plane's own
proposal table, an `is_…_review_case` router, and the plane's own append-only
decision ledger — `relationship_memory_review.py` followed it, and this follows
both. `_Reviews.cases`/`_Reviews.decide` already dispatch on which kind a case
is; nothing here adds a listing, a state machine or a reviewer route of its own.

**What is deliberately *not* here, and it is the difference from the other three
planes.** Those modules promote inside their own SQL. This one does not promote
anything: an accepted Entity proposal is executed by
`application.entity_governance.EntityGovernanceService.accept`, which routes it
through the canonical Phase A mutation services under
`review_accepted`/`review_promotion`. Duplicating that here would be the second
copy of the mutation operator section 14 forbids, and infrastructure may not
import application in any case. So this module holds exactly the five things the
Entity plane's *review* needs and the proposal plane did not already have: the
case listing, the case read, the decision ledger, the reviewer's one-statement
invalidation, and the two-step supersession a reprocess needs.

**Why supersession is two statements rather than
`EntitiesRepository.supersede_proposal`.** That method writes the state and the
successor pointer together, which cannot work here in either order. The pointer's
foreign key (`a_proposal_is_superseded_within_its_principal`) is immediate, so it
cannot name a successor row that does not exist yet; and the successor cannot be
inserted while the predecessor is still open, because `dedupe_sha256` is a digest
over the kind and the payload *only* — deliberately not over the method — so a
successor carrying the same request collides with the predecessor on
`an_open_equivalent_proposal_is_raised_once`. The only order that satisfies both
is supersede, insert, then point, and this module supplies the first and third
statements so the caller can put the insert between them in one transaction.

Every statement reaches the partition through `persistence.principal_scope`, via
the same `_mine`/`_bound` one-line wrappers `relationship_memory_review.py` uses
-- **except the three correlated subqueries `_case_columns` builds**, which are
keyed on `review_case_id` alone. Those `.correlate(entity_proposals)` to the
`_mine`-scoped select they hang off, so they are evaluated per candidate row of a
page that predicate has already admitted and can see no decision belonging to
another Principal's case. What isolates them is that scoped statement and nothing
else -- not the key, which spans every Principal -- and
`tests/architecture/test_principal_partition_is_reached_through_the_guard.py`
carries the same three, named, in this module's `PER_MODULE_ONLY` entry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.engine import Connection

from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.review import (
    Disposition,
    EntityProposalReviewCase,
    EntityProposalReviewDecision,
)
from my_pa.domain.relationship.governance import (
    UNDECIDED_PROPOSAL_STATES,
    EntityProposalKind,
    EntityProposalMethod,
    EntityProposalState,
)
from my_pa.domain.relationship.proposal_payload import schema_for
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    entity_proposal_review_decisions,
    entity_proposals,
)

__all__ = [
    "ENTITY_PAYLOAD_FIELDS",
    "decide_ledger_dispositions",
    "entity_proposal_review_case",
    "entity_proposal_review_cases",
    "invalidate_entity_proposal",
    "name_entity_proposal_successor",
    "record_entity_proposal_review_decision",
    "supersede_entity_proposal",
]

#: Every payload field that names an entity, taken from the schemas rather than
#: listed.
#:
#: Derived because a hand-written list is a list that stops being the population
#: the day a kind gains a field: `entity_id`, `scope_entity_id`,
#: `from_entity_id`, `to_entity_id`, `retained_entity_id`, `merged_entity_id`
#: and `rejected_entity_id` are what the seventeen schemas admit today, and the
#: rule that finds them is the suffix the plane already uses for every such
#: field. A tuple in sorted order rather than a `frozenset[str]`, on the terms
#: `_DECIDED_PROPOSAL_STATES` records: a live closed set of strings is what the
#: enum-derivation guard looks for a revision to have restated, and nothing here
#: should ever be restated in one.
ENTITY_PAYLOAD_FIELDS: Final[tuple[str, ...]] = tuple(
    sorted(
        {
            name
            for kind in EntityProposalKind
            for name in schema_for(kind).admitted
            if name.endswith("entity_id")
        }
    )
)

#: Which single payload field names the entity a case is *about*, in the order a
#: reader should prefer them.
#:
#: One field rather than all of them, because the listing shows one subject and a
#: relationship proposal has two ends. `entity_id` first because fourteen of the
#: seventeen kinds use it for the subject; `retained_entity_id` next because a
#: merge is about the identity that survives; `from_entity_id` last because a
#: relationship is stated from one end. A kind naming none of the three — a
#: revise or an end, which name a child record — shows no subject, which is
#: honest: the entity is one join away through a record this listing does not
#: read, and inventing the join here would put a read the reviewer did not ask
#: for inside a listing.
_SUBJECT_FIELDS: Final = ("entity_id", "retained_entity_id", "from_entity_id")

#: The proposal states a case presents on the shared surface, as the shared
#: `ProposalState` vocabulary. Both enums declare the same eight names for the
#: reason `EntityProposalState` records, so this maps by value and cannot drift
#: without one of them changing shape.
_CASE_STATE: Final = {state: ProposalState(state.value) for state in EntityProposalState}


def _mine(table: Any, principal_id: str) -> Any:  # noqa: ANN401 - a SQLAlchemy Table
    """`table` constrained to the given Principal, through the one guard."""
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Any, principal_id: str, values: dict[str, object]) -> dict[str, object]:  # noqa: ANN401
    """`values` stamped with the given Principal for `table`, through the one guard."""
    return principal_bound_values(values, table, capture_context(principal_id))


def _subject_entity_id(payload: Any) -> str | None:  # noqa: ANN401 - a decoded JSONB value
    """Which entity the listing shows as this case's subject. See `_SUBJECT_FIELDS`."""
    if not isinstance(payload, dict):
        return None
    for name in _SUBJECT_FIELDS:
        value = payload.get(name)
        if isinstance(value, str):
            return value
    return None


def _case(row: Any) -> EntityProposalReviewCase:  # noqa: ANN401 - a SQLAlchemy RowMapping
    """One row as the case a reviewer sees. Carries no payload value."""
    latest = row["latest_disposition"]
    disposition = None if latest is None else Disposition(latest)
    return EntityProposalReviewCase(
        review_case_id=row["review_case_id"],
        proposal_id=row["proposal_id"],
        principal_id=row["principal_id"],
        proposed_kind=EntityProposalKind(row["kind"]),
        method=EntityProposalMethod(row["method"]),
        opened_at=row["proposed_at"],
        target_entity_id=_subject_entity_id(row["payload"]),
        proposal_state=_CASE_STATE[EntityProposalState(row["state"])],
        review_version=int(row["review_version"]),
        latest_disposition=disposition,
        escalated=bool(row["escalated"]),
        accepted_record_id=row["accepted_record_id"],
    )


def _case_columns() -> tuple[Any, ...]:
    """The projection both reads share, with the two derived columns.

    `review_version` is the count of ledger rows and `escalated` is whether any
    of them raised the case; both are derived here rather than stored, because a
    column on the proposal saying either would be a second writer for a fact the
    ledger already owns and the two could then disagree.
    """
    decisions = entity_proposal_review_decisions
    review_version = (
        select(func.count())
        .select_from(decisions)
        .where(decisions.c.review_case_id == entity_proposals.c.review_case_id)
        .correlate(entity_proposals)
        .scalar_subquery()
    )
    escalated = (
        select(func.count())
        .select_from(decisions)
        .where(
            decisions.c.review_case_id == entity_proposals.c.review_case_id,
            decisions.c.disposition == Disposition.ESCALATE.value,
        )
        .correlate(entity_proposals)
        .scalar_subquery()
    ) > 0
    latest_disposition = (
        select(decisions.c.disposition)
        .where(decisions.c.review_case_id == entity_proposals.c.review_case_id)
        .order_by(decisions.c.sequence.desc())
        .limit(1)
        .correlate(entity_proposals)
        .scalar_subquery()
    )
    return (
        entity_proposals.c.review_case_id,
        entity_proposals.c.proposal_id,
        entity_proposals.c.principal_id,
        entity_proposals.c.kind,
        entity_proposals.c.method,
        entity_proposals.c.payload,
        entity_proposals.c.state,
        entity_proposals.c.proposed_at,
        entity_proposals.c.accepted_record_id,
        review_version.label("review_version"),
        escalated.label("escalated"),
        latest_disposition.label("latest_disposition"),
    )


def entity_proposal_review_cases(
    connection: Connection,
    *,
    principal_id: str,
    limit: int,
    state: ProposalState | None = None,
    entity_id: str | None = None,
    after_opened_at: datetime | None = None,
    after_review_case_id: str | None = None,
) -> tuple[EntityProposalReviewCase, ...]:
    """One bounded page of this Principal's Entity proposal cases, oldest first.

    Only proposals that were actually routed to review are here: a kind a
    configured threshold may accept opens no case, carries no `review_case_id`,
    and has no identity a reviewer could decide against — so it is filtered in
    SQL rather than skipped in Python.

    `proposed_at` is the case's `opened_at`, for the reason
    `relationship_memory_review_cases` gives: the proposal table records no
    separate opening moment, and the moment the candidate was produced is the
    moment it became a thing awaiting a decision.

    Both filters run in SQL. `entity_id` matches any payload field that names an
    entity rather than only the one the listing displays as the subject: a
    reviewer asking "what is outstanding about this person" means every proposal
    that would touch them, and a merge proposal that names them as the entity
    being merged *away* is the one they would least want omitted.
    """
    if limit < 1:
        raise ValueError("a review page contains at least one case")
    if (after_opened_at is None) != (after_review_case_id is None):
        raise ValueError("a review cursor position is complete or absent")
    criteria = [
        _mine(entity_proposals, principal_id),
        entity_proposals.c.review_case_id.is_not(None),
    ]
    if state is not None:
        criteria.append(entity_proposals.c.state == state.value)
    if entity_id is not None:
        criteria.append(
            or_(
                *[
                    entity_proposals.c.payload[name].astext == entity_id
                    for name in ENTITY_PAYLOAD_FIELDS
                ]
            )
        )
    if after_opened_at is not None and after_review_case_id is not None:
        criteria.append(
            or_(
                entity_proposals.c.proposed_at > after_opened_at,
                and_(
                    entity_proposals.c.proposed_at == after_opened_at,
                    entity_proposals.c.review_case_id > after_review_case_id,
                ),
            )
        )
    rows = connection.execute(
        select(*_case_columns())
        .where(*criteria)
        .order_by(entity_proposals.c.proposed_at, entity_proposals.c.review_case_id)
        .limit(limit)
    ).mappings()
    return tuple(_case(row) for row in rows)


def entity_proposal_review_case(
    connection: Connection, *, review_case_id: str, principal_id: str
) -> EntityProposalReviewCase | None:
    """The one case `review_case_id` names in this Principal's partition, or `None`.

    `None` rather than an exception, and the router `_Reviews.decide` asks before
    dispatching. A case in another Principal's partition answers `None`, which
    sends the request down the capture route and out as "no such case" — the same
    answer an absent identifier gets, which is what stops a decision probe from
    confirming that an Entity proposal exists.
    """
    found = connection.execute(
        select(*_case_columns()).where(
            entity_proposals.c.review_case_id == review_case_id,
            _mine(entity_proposals, principal_id),
        )
    )
    row = found.mappings().one_or_none()
    return None if row is None else _case(row)


def decide_ledger_dispositions(
    connection: Connection, *, review_case_id: str, principal_id: str
) -> tuple[Disposition, ...]:
    """Every decision already on this case, in sequence order.

    The whole ledger rather than a count, because three separate rules read it
    and each needs a different fact: the count is `expected_review_version`, an
    accepting member makes the case terminal, and an `escalate` member raises the
    ceiling the next acceptance has to clear. Three reads would be three places
    the same rows could be read differently.
    """
    rows = connection.execute(
        select(entity_proposal_review_decisions.c.disposition)
        .where(
            entity_proposal_review_decisions.c.review_case_id == review_case_id,
            _mine(entity_proposal_review_decisions, principal_id),
        )
        .order_by(entity_proposal_review_decisions.c.sequence)
    ).all()
    return tuple(Disposition(row.disposition) for row in rows)


def record_entity_proposal_review_decision(
    connection: Connection, principal_id: str, decision: EntityProposalReviewDecision
) -> None:
    """Append one decision. `UNIQUE (review_case_id, sequence)` is the race guard.

    Nothing here re-checks the sequence against the ledger: the unique index is
    what makes two reviewers racing on one case produce one decision, and a
    Python pre-check would be a second, weaker copy of it that a race walks
    straight past.
    """
    if decision.principal_id != principal_id:
        raise ValueError("a review decision belongs to the acting Principal")
    if (
        SqlEntityRepository(connection).serialize_entity_proposal_scope(
            principal_id, decision.proposal_id
        )
        is None
    ):
        raise ValueError("a review decision names no current proposal in this scope")
    values: dict[str, object] = {
        "decision_id": decision.decision_id,
        "proposal_id": decision.proposal_id,
        "review_case_id": decision.review_case_id,
        "sequence": decision.sequence,
        "disposition": decision.disposition.value,
        "reason": decision.reason,
        "correlation_id": decision.correlation_id,
        "audit_id": decision.audit_id,
        "decided_at": decision.decided_at,
    }
    # The key is omitted rather than set to `None`, and the omission is
    # load-bearing: SQLAlchemy renders a Python `None` bound to a `JSONB` column
    # as the JSON value `null`, which is *not* SQL NULL, so
    # `corrected_payload IS NOT NULL` would be true of a decision that corrected
    # nothing and `an_entity_correction_matches_its_disposition` would refuse
    # every disposition but one. `JSONB(none_as_null=True)` is the other cure and
    # this file's own `structured_content` records why it is not used here: the
    # constructor is untyped at the declared dependency floor and the keyword
    # fails `no-untyped-call` in that one CI job.
    if decision.corrected_payload is not None:
        values["corrected_payload"] = decision.corrected_payload.as_mapping()
    connection.execute(
        insert(entity_proposal_review_decisions).values(
            _bound(entity_proposal_review_decisions, principal_id, values)
        )
    )


def invalidate_entity_proposal(
    connection: Connection,
    principal_id: str,
    proposal_id: str,
    *,
    reason: str,
    decided_by: str,
    decided_at: datetime,
) -> bool:
    """Close an open proposal a reviewer invalidated, in one guarded statement.

    **Why this is not `EntitiesRepository.invalidate_proposal`, which writes the
    same column.** That one is the *merge's* writer: an identity correction
    closes a proposal whose subject stopped existing under that name, and there
    is no reviewer behind it, so it records `invalidated_reason` and no
    `decision_reason`. This is a *reviewer's* disposition on a review case, and
    a review decision that named no reason for itself would be the only one on
    this plane that did. The two statements write two different records of two
    different acts, and collapsing them would make one of the two lie.

    It has to be one statement rather than a decision followed by a correction,
    because `an_invalidated_proposal_records_why` fires on the row that sets
    `state = 'invalidated'`; `decide_proposal` carries no `invalidated_reason`,
    which is why this exists rather than a call to it.

    `False` rather than an exception when the proposal was decided in flight:
    that is an answer about the world, and the caller turns it into the review
    plane's own conflict.
    """
    if (
        SqlEntityRepository(connection).serialize_entity_proposal_scope(principal_id, proposal_id)
        is None
    ):
        return False
    result = connection.execute(
        update(entity_proposals)
        .where(
            entity_proposals.c.proposal_id == proposal_id,
            _mine(entity_proposals, principal_id),
            entity_proposals.c.state.in_([state.value for state in UNDECIDED_PROPOSAL_STATES]),
        )
        .values(
            state=EntityProposalState.INVALIDATED.value,
            invalidated_reason=reason,
            decided_by=decided_by,
            decided_at=decided_at,
            decision_reason=reason,
        )
    )
    return result.rowcount == 1


def supersede_entity_proposal(
    connection: Connection, principal_id: str, proposal_id: str, *, at: datetime
) -> bool:
    """Take an open proposal out of the open set, naming no successor yet.

    Returns `False` rather than raising when the proposal was decided while the
    reprocess was in flight: section 27's required outcome is that a stale
    reprocess creates nothing, which is an answer about the world and not an
    error about scope. The guarded `UPDATE` is what makes it one act.
    """
    if (
        SqlEntityRepository(connection).serialize_entity_proposal_scope(principal_id, proposal_id)
        is None
    ):
        return False
    result = connection.execute(
        update(entity_proposals)
        .where(
            entity_proposals.c.proposal_id == proposal_id,
            _mine(entity_proposals, principal_id),
            entity_proposals.c.state.in_([state.value for state in UNDECIDED_PROPOSAL_STATES]),
        )
        .values(state=EntityProposalState.SUPERSEDED.value, superseded_at=at)
    )
    return result.rowcount == 1


def name_entity_proposal_successor(
    connection: Connection, principal_id: str, proposal_id: str, *, successor_proposal_id: str
) -> None:
    """Point a superseded proposal at the successor that replaced it.

    Guarded on `superseded_by_proposal_id IS NULL` as well as on the state, so
    this is an append rather than a re-point: a proposal already naming its
    successor keeps the first one, and a proposal that is not superseded gets no
    successor at all.
    """
    if (
        SqlEntityRepository(connection).serialize_entity_proposals_scope(
            principal_id, (proposal_id, successor_proposal_id)
        )
        is None
    ):
        raise ValueError("a successor link names no current proposal in this scope")
    connection.execute(
        update(entity_proposals)
        .where(
            entity_proposals.c.proposal_id == proposal_id,
            _mine(entity_proposals, principal_id),
            entity_proposals.c.state == EntityProposalState.SUPERSEDED.value,
            entity_proposals.c.superseded_by_proposal_id.is_(None),
        )
        .values(superseded_by_proposal_id=successor_proposal_id)
    )
