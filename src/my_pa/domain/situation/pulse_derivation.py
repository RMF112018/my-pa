"""Deriving a Pulse: why an item is here *now*, from evidence rather than recency.

WP-11. Before this module the Pulse was a table somebody had to fill in and a
`SELECT … ORDER BY priority DESC, generated_at DESC` over it. Nothing derived an
item from anything, which meant the only thing standing between the product and
an activity feed was whoever wrote the rows.

**What this module is.** One pure function. It takes the Principal's *accepted*
commitments, tasks, decisions and framed obligations, and a moment, and returns
the items for which a named why-now condition holds — each carrying a closed
`PulseReasonCode`, the `basis_refs` a reader can open to check it, a consequence,
and a next step. It opens no connection, reads no store, and writes nothing: the
derivation is a **read**, and `tests/architecture` holds that as a structural
claim rather than a convention.

**Why it is not an activity feed, stated as four properties.**

1. *Nothing qualifies by having happened.* There is no rule keyed on
   `created_at`, `updated_at`, or any other "recently" predicate, and
   `PulseReasonCode` has no member one could write for it. An object that is new,
   or that changed a minute ago, and that carries no due moment, no authority
   point and no unmet obligation produces **no item at all**.
2. *Every item cites its basis.* `basis_refs` is non-empty by construction and by
   the schema CHECK, so "why am I seeing this" is answerable by opening rows
   rather than by trusting a sentence.
3. *Ranking is by evidentiary urgency.* The order is `priority`, then the
   magnitude of the condition — how far past due, how close to due, how many
   obligations stand unmet — then the subject identifier for determinism.
   `generated_at` is not in the key at all, and every derived item carries the
   *same* `generated_at` (the moment of the read), so recency cannot order them
   even accidentally.
4. *Escalation is evidentiary too.* A commitment further past its due moment
   outranks one just past it, because the evidence says so — not because it was
   touched more recently.

**Accepted-only.** The caller passes accepted rows; this function does not
re-check a state it was not given, so the filter lives at the query boundary
where it can be a `WHERE` clause the server enforces
(`SqlPulseRepository.derive_pulse`). The two halves are deliberate: a filter in
Python that a query forgot is the leak, and a query filter with no Python
counterpart is the one that reads as an accident.

**§22.** Nothing here scores, ranks, or characterises a *person*. `priority` is a
bounded rank on an item; a counterparty appears only as an opaque `per_…`
reference in `basis_refs`, never as an input to the rank. There is no sentiment,
no personality, no relationship score, and no aggregation across Principals — the
function takes one Principal's rows and returns one Principal's items.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.situation.continuity import (
    Commitment,
    CommitmentState,
    Decision,
    DecisionState,
    TaskState,
)
from my_pa.domain.situation.continuity import Task as ContinuityTask
from my_pa.domain.situation.situation import PulseItem, PulseItemType, PulseReasonCode

__all__ = [
    "DUE_SOON_WINDOW",
    "FramedObligation",
    "derive_pulse",
]

#: How close a due moment has to be before it is a reason to act today.
#: Three days rather than one, because a commitment due tomorrow that needs a
#: counterparty's answer is already late to raise. Bounded and written down so a
#: reader can see what "soon" means rather than infer it.
DUE_SOON_WINDOW: Final = timedelta(hours=72)

#: When being past due stops being a slip and starts being a failure, and when it
#: stops being a failure and becomes a broken commitment. Both are evidentiary
#: thresholds on the same measurement, not decay curves over activity.
_ESCALATION: Final = timedelta(days=7)
_SEVERE_ESCALATION: Final = timedelta(days=30)

#: The base rank of each why-now condition, as a bounded 1..10 item urgency.
#: An obligation somebody else is entitled to expect outranks work the Principal
#: holds alone; a passed due moment outranks an approaching one; a decision
#: blocked on a named authority point sits between them, because it is the one
#: condition nobody else can clear.
_BASE_PRIORITY: Final[dict[PulseReasonCode, int]] = {
    PulseReasonCode.COMMITMENT_OVERDUE: 8,
    PulseReasonCode.TASK_OVERDUE: 6,
    PulseReasonCode.DECISION_AWAITING_AUTHORITY: 5,
    PulseReasonCode.COMMITMENT_DUE_SOON: 4,
    PulseReasonCode.SITUATION_OBLIGATION_UNMET: 3,
    PulseReasonCode.TASK_DUE_SOON: 2,
}

#: The domain separator for the derived identifier below. Fixed, so the same
#: subject under the same reason yields the same item id on every read.
_PULSE_ID_DOMAIN: Final = "my-pa/pulse-derivation/v1"


@dataclass(frozen=True, slots=True)
class FramedObligation:
    """An obligation standing unmet on the current Frame of an open Situation.

    A count rather than the obligation text, deliberately: the derivation needs
    to know *that* obligations stand and how many, and the text is the
    Principal's own writing about other people. Keeping it out of this layer
    keeps it out of the reason string, out of any log line, and out of anything
    a `§22` review would have to read.
    """

    situation_id: str
    frame_id: str
    obligation_count: int

    def __post_init__(self) -> None:
        if not self.situation_id.strip() or not self.frame_id.strip():
            raise ValueError("a framed obligation names its situation and its frame")
        if self.obligation_count < 1:
            raise ValueError("a framed obligation stands for at least one obligation")


@dataclass(frozen=True, slots=True)
class _Candidate:
    """One derived item and the magnitude of the condition that produced it."""

    item: PulseItem
    magnitude: float


def _derived_pulse_id(principal_id: str, reason_code: PulseReasonCode, subject_id: str) -> str:
    """A deterministic, opaque identifier for a derived item.

    Deterministic so a reader can dismiss one and have the dismissal still name
    it on the next read, and so a rendered page has a stable key. Opaque because
    it is a SHA-256 digest: the suffix encodes no principal, no subject, and no
    reason a holder of it could read back.
    """
    digest = hashlib.sha256(
        f"{_PULSE_ID_DOMAIN}|{principal_id}|{reason_code.value}|{subject_id}".encode()
    ).hexdigest()
    return make_identifier(IdKind.PULSE, digest[:32])


def _overdue_priority(base: int, overdue: timedelta) -> int:
    """Escalate a passed due moment by how far past it is, capped at ten."""
    priority = base
    if overdue >= _ESCALATION:
        priority += 1
    if overdue >= _SEVERE_ESCALATION:
        priority += 1
    return min(priority, 10)


def _days(span: timedelta) -> int:
    return max(int(span.total_seconds() // 86400), 0)


def _hours(span: timedelta) -> int:
    return max(int(span.total_seconds() // 3600), 0)


def _item(
    *,
    principal_id: str,
    now: datetime,
    item_type: PulseItemType,
    subject_id: str,
    reason_code: PulseReasonCode,
    reason: str,
    consequence: str,
    next_step: str,
    basis_refs: Sequence[str],
    priority: int,
    subject_title: str | None = None,
    subject_state: str | None = None,
    subject_version: int | None = None,
    subject_priority: str | None = None,
) -> PulseItem:
    return PulseItem(
        pulse_id=_derived_pulse_id(principal_id, reason_code, subject_id),
        principal_id=principal_id,
        item_type=item_type,
        item_ref=subject_id,
        reason=reason,
        reason_code=reason_code,
        basis_refs=tuple(ref for ref in basis_refs if ref),
        generated_at=now,
        consequence=consequence,
        next_step=next_step,
        attention_rank=priority,
        subject_title=subject_title,
        subject_state=subject_state,
        subject_version=subject_version,
        subject_priority=subject_priority,
    )


def _from_commitment(
    commitment: Commitment, *, principal_id: str, now: datetime
) -> _Candidate | None:
    """A commitment is on the Pulse when its due moment has passed or is close.

    An open commitment with **no** due moment produces nothing, however recently
    it was created or touched. That is the rule that makes this a Pulse: there is
    no why-now to state about it, so there is nothing to say today.
    """
    if commitment.state is not CommitmentState.OPEN or commitment.due_at is None:
        return None
    basis = (commitment.commitment_id, commitment.origin_evidence_ref)
    if commitment.due_at <= now:
        overdue = now - commitment.due_at
        return _Candidate(
            item=_item(
                principal_id=principal_id,
                now=now,
                item_type=PulseItemType.COMMITMENT,
                subject_id=commitment.commitment_id,
                reason_code=PulseReasonCode.COMMITMENT_OVERDUE,
                reason=(
                    "The agreed moment passed "
                    f"{_days(overdue)} day(s) ago and the commitment is still open."
                ),
                consequence=(
                    "A counterparty is still entitled to expect this, and nothing here "
                    "has told them otherwise."
                ),
                next_step=(
                    "Close it with the evidence that discharged it, or re-agree the moment "
                    "with the counterparty."
                ),
                basis_refs=basis,
                priority=_overdue_priority(
                    _BASE_PRIORITY[PulseReasonCode.COMMITMENT_OVERDUE], overdue
                ),
            ),
            magnitude=overdue.total_seconds(),
        )
    remaining = commitment.due_at - now
    if remaining > DUE_SOON_WINDOW:
        return None
    return _Candidate(
        item=_item(
            principal_id=principal_id,
            now=now,
            item_type=PulseItemType.COMMITMENT,
            subject_id=commitment.commitment_id,
            reason_code=PulseReasonCode.COMMITMENT_DUE_SOON,
            reason=f"The agreed moment is {_hours(remaining)} hour(s) away.",
            consequence="Leaving it later removes the option of re-agreeing the moment.",
            next_step="Confirm it will be met, or say now that it will not.",
            basis_refs=basis,
            priority=_BASE_PRIORITY[PulseReasonCode.COMMITMENT_DUE_SOON],
        ),
        # Sooner is more urgent, so the magnitude runs the other way: a
        # commitment due in an hour outranks one due in two days.
        magnitude=DUE_SOON_WINDOW.total_seconds() - remaining.total_seconds(),
    )


def _from_task(task: ContinuityTask, *, principal_id: str, now: datetime) -> _Candidate | None:
    """The same two conditions as a commitment, ranked below it.

    Below, because nobody else is waiting on a Task. That is the whole of the
    difference the two types encode, and it is the whole of the difference in the
    rank.
    """
    if task.state is not TaskState.OPEN or task.due_at is None:
        return None
    basis = (task.task_id, task.origin_evidence_ref)
    if task.due_at <= now:
        overdue = now - task.due_at
        return _Candidate(
            item=_item(
                principal_id=principal_id,
                now=now,
                item_type=PulseItemType.TASK,
                subject_id=task.task_id,
                reason_code=PulseReasonCode.TASK_OVERDUE,
                reason=f"The due moment passed {_days(overdue)} day(s) ago and it is still open.",
                consequence="Work the Principal holds alone is drifting past the date set for it.",
                next_step="Close it with the evidence that completed it, or move the date.",
                basis_refs=basis,
                priority=_overdue_priority(_BASE_PRIORITY[PulseReasonCode.TASK_OVERDUE], overdue),
                subject_title=task.title,
                subject_state=task.state.value,
            ),
            magnitude=overdue.total_seconds(),
        )
    remaining = task.due_at - now
    if remaining > DUE_SOON_WINDOW:
        return None
    return _Candidate(
        item=_item(
            principal_id=principal_id,
            now=now,
            item_type=PulseItemType.TASK,
            subject_id=task.task_id,
            reason_code=PulseReasonCode.TASK_DUE_SOON,
            reason=f"The due moment is {_hours(remaining)} hour(s) away.",
            consequence="It is close enough that starting it later is a choice, not an accident.",
            next_step="Start it, or move the date deliberately.",
            basis_refs=basis,
            priority=_BASE_PRIORITY[PulseReasonCode.TASK_DUE_SOON],
            subject_title=task.title,
            subject_state=task.state.value,
        ),
        magnitude=DUE_SOON_WINDOW.total_seconds() - remaining.total_seconds(),
    )


def _from_decision(decision: Decision, *, principal_id: str, now: datetime) -> _Candidate | None:
    """A decision is on the Pulse when it names the authority point it waits on.

    An open decision with no named authority point produces nothing. That is
    deliberate and is the same rule as the missing due moment: "you have an open
    decision" is a listing, and a listing is what a Pulse is not.
    """
    if decision.state is not DecisionState.OPEN:
        return None
    authority = (decision.awaiting_authority_ref or "").strip()
    if not authority:
        return None
    return _Candidate(
        item=_item(
            principal_id=principal_id,
            now=now,
            item_type=PulseItemType.DECISION,
            subject_id=decision.decision_id,
            reason_code=PulseReasonCode.DECISION_AWAITING_AUTHORITY,
            reason="The decision is blocked on a named authority point that has not answered.",
            consequence="Nothing downstream of the decision can move while it stands unanswered.",
            next_step="Put the question to the named authority point, or decide without it.",
            basis_refs=(decision.decision_id, decision.origin_evidence_ref, authority),
            priority=_BASE_PRIORITY[PulseReasonCode.DECISION_AWAITING_AUTHORITY],
        ),
        magnitude=0.0,
    )


def _from_obligation(
    obligation: FramedObligation, principal_id: str, *, now: datetime
) -> _Candidate:
    """Obligations standing unmet on an open Situation's current Frame."""
    return _Candidate(
        item=_item(
            principal_id=principal_id,
            now=now,
            item_type=PulseItemType.SITUATION,
            subject_id=obligation.situation_id,
            reason_code=PulseReasonCode.SITUATION_OBLIGATION_UNMET,
            reason=(
                f"{obligation.obligation_count} obligation(s) recorded on the current frame "
                "are still unmet."
            ),
            consequence="The situation cannot close while its own frame says work is outstanding.",
            next_step="Discharge the obligations, or record why they no longer apply.",
            basis_refs=(obligation.situation_id, obligation.frame_id),
            priority=_BASE_PRIORITY[PulseReasonCode.SITUATION_OBLIGATION_UNMET],
        ),
        # More outstanding obligations is a stronger claim on attention, and it
        # is a count of evidence rather than a measure of activity.
        magnitude=float(obligation.obligation_count),
    )


def derive_pulse(
    *,
    principal_id: str,
    now: datetime,
    commitments: Iterable[Commitment] = (),
    tasks: Iterable[ContinuityTask] = (),
    decisions: Iterable[Decision] = (),
    obligations: Iterable[FramedObligation] = (),
    dismissed_pulse_ids: frozenset[str] = frozenset(),
) -> tuple[PulseItem, ...]:
    """The Principal's Pulse at `now`, ranked by evidentiary urgency.

    Every input must already be this Principal's and already accepted; the
    partition and the acceptance filter are the query's, so that a forgotten
    `WHERE` clause fails at the boundary that can actually enforce it rather than
    being masked here. What this function refuses is anything with no why-now
    condition, and that refusal is total: an object with no due moment, no named
    authority point and no unmet obligation contributes nothing at all.

    The returned order is `(priority, magnitude, item_ref)`, all descending but
    the last. `generated_at` appears in no comparison and is identical across
    every item, so no ordering here can degenerate into reverse-chronological.
    """
    ensure_utc(now)
    candidates: list[_Candidate] = []
    for commitment in commitments:
        found = _from_commitment(commitment, principal_id=principal_id, now=now)
        if found is not None:
            candidates.append(found)
    for task in tasks:
        found = _from_task(task, principal_id=principal_id, now=now)
        if found is not None:
            candidates.append(found)
    for decision in decisions:
        found = _from_decision(decision, principal_id=principal_id, now=now)
        if found is not None:
            candidates.append(found)
    for obligation in obligations:
        candidates.append(_from_obligation(obligation, principal_id, now=now))

    kept = [
        candidate for candidate in candidates if candidate.item.pulse_id not in dismissed_pulse_ids
    ]
    kept.sort(key=lambda candidate: candidate.item.item_ref)
    kept.sort(
        key=lambda candidate: (candidate.item.attention_rank, candidate.magnitude),
        reverse=True,
    )
    return tuple(candidate.item for candidate in kept)
