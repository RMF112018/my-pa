"""Attention ranking is deterministic and does not mutate priority."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.tasks.attention import AttentionReason, rank_attention
from my_pa.domain.tasks.models import (
    AcceptanceKind,
    Commitment,
    CommitmentDirection,
    CommitmentState,
    ContinuityEvidenceState,
    Task,
    TaskPriority,
    TaskRole,
    TaskState,
)

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
PRINCIPAL = issue_identifier(IdKind.PRINCIPAL)


def _task(**overrides: object) -> Task:
    values: dict[str, object] = {
        "task_id": issue_identifier(IdKind.TASK),
        "principal_id": PRINCIPAL,
        "title": "work",
        "state": TaskState.OPEN,
        "task_role": TaskRole.ACTION,
        "priority": TaskPriority.P3,
        "evidence_state": ContinuityEvidenceState.ACCEPTED,
        "acceptance_kind": AcceptanceKind.DIRECT_PRINCIPAL,
        "current_version": 1,
        "opened_at": NOW - timedelta(days=1),
        "created_at": NOW - timedelta(days=1),
        "updated_at": NOW - timedelta(days=1),
    }
    values.update(overrides)
    return Task(**values)  # type: ignore[arg-type]


def test_overdue_ranks_above_future_p1() -> None:
    overdue = _task(title="overdue p3", due_date=date(2026, 8, 9), priority=TaskPriority.P3)
    future = _task(title="future p1", due_date=date(2026, 8, 20), priority=TaskPriority.P1)
    ranked = rank_attention((future, overdue), now=NOW)
    assert ranked[0].task_id == overdue.task_id
    assert AttentionReason.OVERDUE in ranked[0].reasons
    assert overdue.priority is TaskPriority.P3


def test_deferred_future_work_is_suppressed_unless_overdue() -> None:
    deferred = _task(
        title="snoozed",
        due_date=date(2026, 8, 20),
        deferred_until=NOW + timedelta(days=2),
    )
    overdue_deferred = _task(
        title="risk",
        due_date=date(2026, 8, 9),
        deferred_until=NOW + timedelta(days=2),
    )
    ranked = rank_attention((deferred, overdue_deferred), now=NOW)
    assert [item.task_id for item in ranked] == [overdue_deferred.task_id]
    included = rank_attention((deferred,), now=NOW, include_deferred=True)
    assert included[0].task_id == deferred.task_id


def test_waiting_is_suppressed_from_next_work() -> None:
    waiting = _task(state=TaskState.WAITING, due_date=date(2026, 8, 10))
    assert rank_attention((waiting,), now=NOW) == ()
    included = rank_attention((waiting,), now=NOW, include_waiting=True)
    assert included[0].task_id == waiting.task_id


def test_follow_up_due_and_commitment_waiting_are_reason_codes() -> None:
    person = issue_identifier(IdKind.PERSON)
    follow = _task(
        title="chase Sarah",
        task_role=TaskRole.FOLLOW_UP,
        person_id=person,
        due_date=date(2026, 8, 10),
    )
    commitment = Commitment(
        commitment_id=issue_identifier(IdKind.COMMITMENT),
        principal_id=PRINCIPAL,
        counterparty_person_id=person,
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
        summary="Sarah owes the log",
        state=CommitmentState.OPEN,
        evidence_state=ContinuityEvidenceState.ACCEPTED,
        current_version=1,
        opened_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    ranked = rank_attention((follow,), (commitment,), now=NOW)
    assert AttentionReason.FOLLOW_UP_DUE in ranked[0].reasons
    assert AttentionReason.COMMITMENT_WAITING in ranked[0].reasons


def test_proposed_tasks_are_not_ranked() -> None:
    proposed = _task(
        title="inferred",
        due_date=date(2026, 8, 10),
        evidence_state=ContinuityEvidenceState.PROPOSED,
        acceptance_kind=AcceptanceKind.NONE,
    )
    assert rank_attention((proposed,), now=NOW) == ()
