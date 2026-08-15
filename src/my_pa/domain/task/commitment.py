"""`Commitment`, extended: the WP-TM-05 domain model over `knowledge.commitments`.

WP-11's `situation.continuity.Commitment` remains the minimal continuity
object: it is what `continuity_lifecycle_events`, the Pulse derivation, and the
existing `situation_repository` read and write today, and none of those
callers change under this work package. This module is the richer model the
task-management work adds *alongside* it, over the same row — every field
`continuity.Commitment` carries is still a column on `knowledge.commitments`,
and this `Commitment` adds the one WP-TM-05 requires, `version`, the
optimistic-concurrency counter `CommitmentHistoryEntry` reads before and after
every attempted mutation — without removing or renaming any of the legacy
ones. This is exactly the relationship `domain.task.task.Task` already holds
with `continuity.Task`: a richer model over the same table, not a
replacement of it.

`direction`, `state`, and `evidence_state` are reused from
`domain.situation.continuity` verbatim, per the operator-confirmed scope: this
module defines no new vocabulary for any of the three, and does not redefine
`CommitmentDirection`, `CommitmentState`, or `ContinuityEvidenceState`.

`__post_init__` mirrors `domain.task.task.Task`'s own validation style and
`continuity.Commitment`'s own invariants: an opaque identifier for every
identifier field, a non-blank summary and origin evidence, UTC-aware instants,
the accepted/review-decision biconditional, and the closed/closure-evidence
biconditional.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.situation.continuity import (
    CommitmentDirection,
    CommitmentState,
    ContinuityEvidenceState,
)

__all__ = ["Commitment"]


@dataclass(frozen=True, slots=True)
class Commitment:
    """A social obligation between the Principal and one named counterparty.

    `version` starts at `1` and is the optimistic-concurrency counter every
    applied mutation advances by exactly one, exactly as `Task.version` is for
    the task-management plane — it is not a row count and not a revision
    identifier.
    """

    commitment_id: str
    principal_id: str
    counterparty_person_id: str
    direction: CommitmentDirection
    summary: str
    state: CommitmentState
    evidence_state: ContinuityEvidenceState
    origin_evidence_ref: str
    opened_at: datetime
    created_at: datetime
    updated_at: datetime
    version: int = 1
    due_at: datetime | None = None
    project_id: str | None = None
    situation_id: str | None = None
    closed_at: datetime | None = None
    closure_evidence_ref: str | None = None
    accepted_by_review_decision_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.commitment_id, IdKind.COMMITMENT)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.counterparty_person_id, IdKind.PERSON)
        if not isinstance(self.direction, CommitmentDirection):
            raise ValueError("a commitment names which way the obligation runs")
        if not self.summary.strip():
            raise ValueError("a commitment carries a non-blank summary")
        if not isinstance(self.state, CommitmentState):
            raise ValueError("a commitment names one known lifecycle state")
        if not isinstance(self.evidence_state, ContinuityEvidenceState):
            raise ValueError("a commitment names one known evidence state")
        if not self.origin_evidence_ref.strip():
            raise ValueError("a commitment records the evidence it was read out of")
        if self.version < 1:
            raise ValueError("a commitment version starts at one and only increases")
        if self.project_id is not None:
            validate_identifier(self.project_id, IdKind.PROJECT)
        if self.situation_id is not None:
            validate_identifier(self.situation_id, IdKind.SITUATION)
        if self.accepted_by_review_decision_id is not None:
            validate_identifier(self.accepted_by_review_decision_id, IdKind.REVIEW_DECISION)
        _require_acceptance_pairing(self.evidence_state, self.accepted_by_review_decision_id)

        ensure_utc(self.opened_at)
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)
        for optional_instant in (self.due_at, self.closed_at):
            if optional_instant is not None:
                ensure_utc(optional_instant)

        is_closed = self.state is CommitmentState.CLOSED
        if is_closed is not (self.closed_at is not None):
            raise ValueError("a closed commitment records when it closed, and only then")
        if is_closed and not (self.closure_evidence_ref or "").strip():
            raise ValueError("a closed commitment carries the evidence that closed it")


def _require_acceptance_pairing(
    evidence_state: ContinuityEvidenceState, review_decision_id: str | None
) -> None:
    if (evidence_state is ContinuityEvidenceState.ACCEPTED) is not (review_decision_id is not None):
        raise ValueError("an accepted commitment names the review decision that accepted it")
