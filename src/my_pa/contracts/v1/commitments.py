"""The public shapes of a commitment-read answer (WP-TM-05).

Three models, one per kind of answer the commitment read capabilities produce:
`CommitmentView` for a single commitment read, `CommitmentListEntry` for list
responses, and `WaitingOnEntry` for the derived "waiting on" query that joins
commitment and follow-up task state into one row. The same contract-as-model
argument `contracts.v1.documents` gives applies here: the shape of a public
answer is a contract, and a contract that exists only as the code that happened
to build it cannot be checked against anything.

All three are plain frozen dataclasses rather than Pydantic models because the
fields are pre-serialised strings and integers — the domain layer and the
application service have already validated and formatted every value before it
reaches a view, so there is nothing left for a model validator to reject.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

__all__ = [
    "CommitmentHistoryEntryView",
    "CommitmentListEntry",
    "CommitmentView",
    "WaitingOnEntry",
]


@dataclass(frozen=True, slots=True)
class CommitmentView:
    """One commitment, exactly as a single-commitment read answers it."""

    commitment_id: str
    direction: str
    state: str
    counterparty_person_id: str | None
    title: str
    description: str | None
    due_date: str | None
    created_at: str
    updated_at: str
    version: int
    evidence_state: str
    origin_evidence_ref: str
    closure_evidence_ref: str | None
    accepted_by_review_decision_id: str | None
    closed_at: str | None

    def to_canonical_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CommitmentListEntry:
    """One commitment as list responses present it: a page row."""

    commitment_id: str
    direction: str
    state: str
    counterparty_person_id: str | None
    title: str
    description: str | None
    due_date: str | None
    created_at: str
    updated_at: str
    version: int

    def to_canonical_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WaitingOnEntry:
    """One row of the derived "waiting on" query.

    Joins commitment state with the linked follow-up task, if any, so the
    caller sees the obligation and its task in a single row without issuing
    two reads.
    """

    commitment_id: str
    title: str
    counterparty_person_id: str | None
    due_date: str | None
    state: str
    follow_up_task_id: str | None
    follow_up_task_title: str | None
    follow_up_task_state: str | None

    def to_canonical_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CommitmentHistoryEntryView:
    """One safe append-only Commitment mutation receipt."""

    history_id: str
    commitment_id: str
    action: str
    actor: str
    outcome: str
    before_version: int
    after_version: int
    occurred_at: str
    recorded_at: str

    def to_canonical_dict(self) -> dict[str, object]:
        return asdict(self)
