"""Commitments, Decisions, Tasks, and the lifecycle evidence that closes them.

WP-11. The R5 surface `situation.py` declares stops at Situation, Frame, Trace,
Project and PulseItem, and the canonical object model names three more durable
continuity objects that had no type and no table at all. They are here, and so is
the one append-only record that makes their lifecycle legible.

**A Commitment is a social obligation, not a Task with a date.** It names a
counterparty and a direction — who owes what to whom — and that distinction is
the reason it is a separate type rather than a `kind` column on `Task`. A Task is
work the Principal holds alone; a Commitment is work that another person is
entitled to expect, so closing one silently is a different kind of failure. The
counterparty is a `per_…` reference and **carries no foreign key**, for the same
reason `Situation.object_refs` carries none and for one more: `relationship_people`
is itself principal-partitioned, so a foreign key would let one Principal learn
that another Principal's Person row exists by observing which insert succeeds.

**Accepted-only continuity.** Every object here carries `evidence_state`, a closed
two-member vocabulary, and it is `PROPOSED` unless a human accepted it. Continuity
reads — the Pulse derivation above all — filter to `ACCEPTED`, so a proposal is
reachable *as a proposal* and never as established continuity. The domain half is
the enum and the CHECK on it; the storage half is
`knowledge.commitments.commitment_evidence_state_is_known` and its two siblings.

**Lifecycle and closure evidence.** `ContinuityLifecycleEvent` is one append-only
row per transition, and a `CLOSED` transition **requires** a non-blank
`evidence_ref`: a status field flipping with no trace is exactly what this table
exists to refuse. The same table carries `ASSOCIATED`, which is how an object's
membership of a Project or a Situation becomes reconstructable from evidence
rather than inferred from a column — the association row names the evidence that
justified it.

**No scoring of people anywhere.** `CommitmentDirection` is a property of an
obligation, not of a person; nothing here ranks, scores, or characterises a
counterparty, and `§22` forbids adding anything that would.

Every identifier is opaque and server-issued. Nothing in this module reads or
writes a store.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "ClosureEvidenceKind",
    "Commitment",
    "CommitmentDirection",
    "CommitmentState",
    "CommitmentWorkView",
    "ContinuityAcceptanceKind",
    "ContinuityEvidenceState",
    "ContinuityLifecycleEvent",
    "ContinuityObjectKind",
    "Decision",
    "DecisionState",
    "LifecycleTransition",
    "Task",
    "TaskState",
]


class ContinuityEvidenceState(StrEnum):
    """Whether a continuity object is a proposal or established continuity.

    Two members and no third. `PROPOSED` is what a derivation or an import may
    write; `ACCEPTED` is established continuity. Every continuity read filters
    to `ACCEPTED`, so widening this vocabulary would widen what counts as
    established fact — which is why it is closed here and in the schema.
    """

    PROPOSED = "proposed"
    ACCEPTED = "accepted"


class ContinuityAcceptanceKind(StrEnum):
    """How an accepted continuity object became accepted.

    `none` is the proposed state. `review` names a capture-review decision.
    `direct_principal` is an explicit user-directed write: the Principal
    instructed the create, which is not the same act as a model inferring a
    commitment from a note.
    """

    NONE = "none"
    REVIEW = "review"
    DIRECT_PRINCIPAL = "direct_principal"


class CommitmentState(StrEnum):
    """Where a Commitment is in its lifecycle."""

    OPEN = "open"
    CLOSED = "closed"


class DecisionState(StrEnum):
    """Where a Decision is in its lifecycle."""

    OPEN = "open"
    CLOSED = "closed"


class TaskState(StrEnum):
    """Where a Task is in its lifecycle."""

    OPEN = "open"
    CLOSED = "closed"


class CommitmentDirection(StrEnum):
    """Which way a social obligation runs.

    A property of the obligation. Nothing derives a score, a rank, or a
    characterisation of the counterparty from it, and `§22` forbids anything
    that would.
    """

    OWED_BY_PRINCIPAL = "owed_by_principal"
    OWED_TO_PRINCIPAL = "owed_to_principal"


class CommitmentWorkView(StrEnum):
    """Server-owned Commitment sections for the Work hub.

    ``due`` means open obligations due within the selected civil day;
    ``recently-updated`` means records updated within the bounded seven-day
    window calculated by the application service.
    """

    DUE = "due"
    RECENTLY_UPDATED = "recently-updated"


class ContinuityObjectKind(StrEnum):
    """What kind of continuity object a lifecycle row is about.

    Five members: the three this module adds and the two `situation.py` already
    declares, because a Situation and a Project are closed with evidence on the
    same terms and there is no reason for two lifecycle tables.
    """

    COMMITMENT = "commitment"
    DECISION = "decision"
    TASK = "task"
    SITUATION = "situation"
    PROJECT = "project"


class LifecycleTransition(StrEnum):
    """What a lifecycle row records.

    `OPENED` and `CLOSED` are the lifecycle; `ASSOCIATED` is the membership
    record that makes a project/context association reconstructable. All three
    are appended and none is ever updated or deleted.
    """

    OPENED = "opened"
    CLOSED = "closed"
    ASSOCIATED = "associated"


class ClosureEvidenceKind(StrEnum):
    """What kind of thing an `evidence_ref` points at.

    Closed, because "evidence" with an open vocabulary is a free-text field with
    a better name. Each member names a record class this build actually holds, so
    a reader of a closure row can tell what it would have to open to check it.
    """

    REVIEW_DECISION = "review_decision"
    CAPTURE = "capture"
    ASSERTION = "assertion"
    RELATIONSHIP_EVENT = "relationship_event"
    FRAME = "frame"
    SITUATION = "situation"
    PROJECT = "project"
    PRINCIPAL_STATEMENT = "principal_statement"


def _require_identifier(value: str, kind: IdKind, noun: str) -> None:
    if not value.strip():
        raise ValueError(f"{noun} is not blank")
    validate_identifier(value, kind)


def _require_closure_pairing(state_is_closed: bool, closed_at: datetime | None, noun: str) -> None:
    """A closed object records when it closed, and only then.

    The same pairing `situations` and `projects` already enforce, restated for
    the three objects this module adds so all five behave alike.
    """
    if state_is_closed is not (closed_at is not None):
        raise ValueError(f"a closed {noun} records when it closed, and only then")


def _require_acceptance_pairing(
    evidence_state: ContinuityEvidenceState,
    review_decision_id: str | None,
    noun: str,
    acceptance_kind: ContinuityAcceptanceKind | None = None,
) -> None:
    """Accepted continuity names how it became accepted.

    Review-accepted objects still name the review decision. Direct Principal
    authoring names no review decision, because the write *is* the instruction.
    A proposed row carrying either would be a promotion somebody started and
    did not finish.
    """
    kind = acceptance_kind
    if kind is None:
        kind = (
            ContinuityAcceptanceKind.REVIEW
            if review_decision_id is not None
            else ContinuityAcceptanceKind.NONE
        )
    if evidence_state is ContinuityEvidenceState.PROPOSED:
        if kind is not ContinuityAcceptanceKind.NONE or review_decision_id is not None:
            raise ValueError(f"a proposed {noun} names the review decision that accepted it")
        return
    if kind is ContinuityAcceptanceKind.REVIEW:
        if review_decision_id is None:
            raise ValueError(f"an accepted {noun} names the review decision that accepted it")
        validate_identifier(review_decision_id, IdKind.REVIEW_DECISION)
        return
    if kind is ContinuityAcceptanceKind.DIRECT_PRINCIPAL:
        if review_decision_id is not None:
            raise ValueError(f"a directly authored {noun} does not cite a review decision")
        return
    raise ValueError(f"an accepted {noun} names the review decision that accepted it")


@dataclass(frozen=True, slots=True)
class Commitment:
    """A social obligation between the Principal and one named counterparty.

    `origin_evidence_ref` is what the obligation was read out of, and it is
    mandatory: a commitment nobody can trace back to something said or written is
    an assertion about a person made by this product, which is the thing it must
    never do. `closure_evidence_ref` is mandatory *once closed*, and the schema
    CHECK `a_closed_commitment_carries_closure_evidence` says the same thing one
    layer down.
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
    due_at: datetime | None = None
    project_id: str | None = None
    situation_id: str | None = None
    closed_at: datetime | None = None
    closure_evidence_ref: str | None = None
    accepted_by_review_decision_id: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.commitment_id, IdKind.COMMITMENT, "a commitment identifier")
        _require_identifier(self.principal_id, IdKind.PRINCIPAL, "a principal identifier")
        _require_identifier(self.counterparty_person_id, IdKind.PERSON, "a commitment counterparty")
        if not isinstance(self.direction, CommitmentDirection):
            raise ValueError("a commitment names which way the obligation runs")
        if not self.summary.strip():
            raise ValueError("a commitment carries a non-blank summary")
        if not isinstance(self.state, CommitmentState):
            raise ValueError("a commitment names one lifecycle state")
        if not isinstance(self.evidence_state, ContinuityEvidenceState):
            raise ValueError("a commitment names one evidence state")
        _require_acceptance_pairing(
            self.evidence_state, self.accepted_by_review_decision_id, "commitment"
        )
        if not self.origin_evidence_ref.strip():
            raise ValueError("a commitment records the evidence it was read out of")
        if self.project_id is not None:
            validate_identifier(self.project_id, IdKind.PROJECT)
        if self.situation_id is not None:
            validate_identifier(self.situation_id, IdKind.SITUATION)
        ensure_utc(self.opened_at)
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)
        if self.due_at is not None:
            ensure_utc(self.due_at)
        if self.closed_at is not None:
            ensure_utc(self.closed_at)
        _require_closure_pairing(self.state is CommitmentState.CLOSED, self.closed_at, "commitment")
        if self.state is CommitmentState.CLOSED and not (self.closure_evidence_ref or "").strip():
            raise ValueError("a closed commitment carries the evidence that closed it")


@dataclass(frozen=True, slots=True)
class Decision:
    """One decision the Principal holds, and the authority point it waits on.

    `awaiting_authority_ref` is the "next authority point" the Frame vocabulary
    already names: the thing that has to happen, or the person who has to answer,
    before the decision can be taken. It is what makes a decision *blocked* in a
    way a reader can check, rather than in a way a model asserted.
    """

    decision_id: str
    principal_id: str
    question: str
    state: DecisionState
    evidence_state: ContinuityEvidenceState
    origin_evidence_ref: str
    opened_at: datetime
    created_at: datetime
    updated_at: datetime
    awaiting_authority_ref: str | None = None
    project_id: str | None = None
    situation_id: str | None = None
    closed_at: datetime | None = None
    closure_evidence_ref: str | None = None
    outcome: str | None = None
    accepted_by_review_decision_id: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.decision_id, IdKind.CONTINUITY_DECISION, "a decision identifier")
        _require_identifier(self.principal_id, IdKind.PRINCIPAL, "a principal identifier")
        if not self.question.strip():
            raise ValueError("a decision carries a non-blank question")
        if not isinstance(self.state, DecisionState):
            raise ValueError("a decision names one lifecycle state")
        if not isinstance(self.evidence_state, ContinuityEvidenceState):
            raise ValueError("a decision names one evidence state")
        _require_acceptance_pairing(
            self.evidence_state, self.accepted_by_review_decision_id, "decision"
        )
        if not self.origin_evidence_ref.strip():
            raise ValueError("a decision records the evidence it was read out of")
        if self.project_id is not None:
            validate_identifier(self.project_id, IdKind.PROJECT)
        if self.situation_id is not None:
            validate_identifier(self.situation_id, IdKind.SITUATION)
        ensure_utc(self.opened_at)
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)
        if self.closed_at is not None:
            ensure_utc(self.closed_at)
        _require_closure_pairing(self.state is DecisionState.CLOSED, self.closed_at, "decision")
        if self.state is DecisionState.CLOSED and not (self.closure_evidence_ref or "").strip():
            raise ValueError("a closed decision carries the evidence that closed it")


@dataclass(frozen=True, slots=True)
class Task:
    """Work the Principal holds alone, with no counterparty entitled to expect it.

    The absence of a counterparty is the whole difference from `Commitment` and is
    structural rather than conventional: there is no field one could go in.
    """

    task_id: str
    principal_id: str
    title: str
    state: TaskState
    evidence_state: ContinuityEvidenceState
    origin_evidence_ref: str
    opened_at: datetime
    created_at: datetime
    updated_at: datetime
    due_at: datetime | None = None
    project_id: str | None = None
    situation_id: str | None = None
    closed_at: datetime | None = None
    closure_evidence_ref: str | None = None
    accepted_by_review_decision_id: str | None = None
    acceptance_kind: ContinuityAcceptanceKind | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.task_id, IdKind.TASK, "a task identifier")
        _require_identifier(self.principal_id, IdKind.PRINCIPAL, "a principal identifier")
        if not self.title.strip():
            raise ValueError("a task carries a non-blank title")
        if not isinstance(self.state, TaskState):
            raise ValueError("a task names one lifecycle state")
        if not isinstance(self.evidence_state, ContinuityEvidenceState):
            raise ValueError("a task names one evidence state")
        _require_acceptance_pairing(
            self.evidence_state,
            self.accepted_by_review_decision_id,
            "task",
            self.acceptance_kind,
        )
        if not self.origin_evidence_ref.strip():
            raise ValueError("a task records the evidence it was read out of")
        if self.project_id is not None:
            validate_identifier(self.project_id, IdKind.PROJECT)
        if self.situation_id is not None:
            validate_identifier(self.situation_id, IdKind.SITUATION)
        ensure_utc(self.opened_at)
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)
        if self.due_at is not None:
            ensure_utc(self.due_at)
        if self.closed_at is not None:
            ensure_utc(self.closed_at)
        _require_closure_pairing(self.state is TaskState.CLOSED, self.closed_at, "task")
        if self.state is TaskState.CLOSED and not (self.closure_evidence_ref or "").strip():
            raise ValueError("a closed task carries the evidence that closed it")


@dataclass(frozen=True, slots=True)
class ContinuityLifecycleEvent:
    """One append-only row: an object opened, closed, or associated, with evidence.

    `occurred_at` is when the transition happened in the world and `recorded_at`
    is when this build learned it; keeping them apart is what stops a backdated
    import from reading as a live event. A `CLOSED` transition requires a
    non-blank `evidence_ref` here and in the schema
    (`a_closed_transition_carries_evidence`), which is the whole point of the
    table: a closure with no evidence cannot be written at either layer.
    """

    event_id: str
    principal_id: str
    object_kind: ContinuityObjectKind
    object_id: str
    transition: LifecycleTransition
    evidence_kind: ClosureEvidenceKind
    occurred_at: datetime
    recorded_at: datetime
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.event_id, IdKind.LIFECYCLE_EVENT, "a lifecycle event identifier")
        _require_identifier(self.principal_id, IdKind.PRINCIPAL, "a principal identifier")
        if not isinstance(self.object_kind, ContinuityObjectKind):
            raise ValueError("a lifecycle event names one object kind")
        if not self.object_id.strip():
            raise ValueError("a lifecycle event names the object it is about")
        if not isinstance(self.transition, LifecycleTransition):
            raise ValueError("a lifecycle event names one transition")
        if not isinstance(self.evidence_kind, ClosureEvidenceKind):
            raise ValueError("a lifecycle event names one evidence kind")
        ensure_utc(self.occurred_at)
        ensure_utc(self.recorded_at)
        if self.transition is LifecycleTransition.CLOSED and not (self.evidence_ref or "").strip():
            raise ValueError("a closed transition carries the evidence that closed it")
        if (
            self.transition is LifecycleTransition.ASSOCIATED
            and not (self.evidence_ref or "").strip()
        ):
            raise ValueError("an association carries the evidence that justifies it")
