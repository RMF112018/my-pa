"""Task lifecycle, date XOR, recurrence, and commitment independence."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.tasks.models import (
    ALLOWED_TRANSITIONS,
    AcceptanceKind,
    Commitment,
    CommitmentDirection,
    CommitmentState,
    ContinuityEvidenceState,
    RecurrenceFrequency,
    RecurrenceRule,
    Task,
    TaskError,
    TaskPriority,
    TaskRole,
    TaskState,
    Weekday,
    can_transition,
    next_occurrence,
    normalize_priority,
    occurrence_key_for,
    validate_temporal_pair,
)

WHEN = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)


def _task(**overrides: object) -> Task:
    values: dict[str, object] = {
        "task_id": issue_identifier(IdKind.TASK),
        "principal_id": issue_identifier(IdKind.PRINCIPAL),
        "title": "call Mike about Turner permit",
        "state": TaskState.OPEN,
        "task_role": TaskRole.ACTION,
        "priority": TaskPriority.P3,
        "evidence_state": ContinuityEvidenceState.ACCEPTED,
        "acceptance_kind": AcceptanceKind.DIRECT_PRINCIPAL,
        "current_version": 1,
        "opened_at": WHEN,
        "created_at": WHEN,
        "updated_at": WHEN,
    }
    values.update(overrides)
    return Task(**values)  # type: ignore[arg-type]


def test_priority_aliases_normalize_to_canonical_values() -> None:
    assert normalize_priority("urgent") is TaskPriority.P1
    assert normalize_priority("HIGH") is TaskPriority.P2
    assert normalize_priority("normal") is TaskPriority.P3
    assert normalize_priority("default") is TaskPriority.P3
    assert normalize_priority("low") is TaskPriority.P4
    assert normalize_priority(TaskPriority.P2) is TaskPriority.P2


def test_unknown_priority_is_refused() -> None:
    with pytest.raises(TaskError, match="priority"):
        normalize_priority("critical")


def test_date_and_instant_are_mutually_exclusive() -> None:
    with pytest.raises(TaskError, match="cannot both"):
        validate_temporal_pair(date(2026, 8, 11), WHEN, "America/New_York")
    validate_temporal_pair(date(2026, 8, 11), None, "America/New_York")
    validate_temporal_pair(None, WHEN, "America/New_York")


def test_date_only_does_not_invent_midnight() -> None:
    task = _task(due_date=date(2026, 8, 11), due_at=None, due_timezone="America/New_York")
    assert task.due_date == date(2026, 8, 11)
    assert task.due_at is None


def test_naive_instant_is_refused() -> None:
    with pytest.raises(TaskError, match="timezone-aware"):
        _task(due_at=datetime(2026, 8, 11, 15, 0), due_date=None)


def test_direct_acceptance_does_not_invent_a_review_id() -> None:
    with pytest.raises(TaskError, match="review decision"):
        _task(
            acceptance_kind=AcceptanceKind.DIRECT_PRINCIPAL,
            accepted_by_review_decision_id=issue_identifier(IdKind.REVIEW_DECISION),
        )


def test_review_acceptance_requires_the_decision() -> None:
    with pytest.raises(TaskError, match="review decision"):
        _task(acceptance_kind=AcceptanceKind.REVIEW, accepted_by_review_decision_id=None)


def test_every_non_terminal_state_can_reach_completed_or_cancelled() -> None:
    for state in (TaskState.OPEN, TaskState.IN_PROGRESS, TaskState.WAITING, TaskState.BLOCKED):
        assert TaskState.COMPLETED in ALLOWED_TRANSITIONS[state]
        assert TaskState.CANCELLED in ALLOWED_TRANSITIONS[state]


def test_terminal_states_only_reopen() -> None:
    assert ALLOWED_TRANSITIONS[TaskState.COMPLETED] == frozenset({TaskState.OPEN})
    assert ALLOWED_TRANSITIONS[TaskState.CANCELLED] == frozenset({TaskState.OPEN})
    assert not can_transition(TaskState.COMPLETED, TaskState.CANCELLED)


def test_transition_records_a_new_version_and_reopen_clears_closed_at() -> None:
    opened = _task()
    completed = opened.transitioned(TaskState.COMPLETED, at=WHEN + timedelta(hours=1), version=1)
    assert completed.current_version == 2
    assert completed.closed_at == WHEN + timedelta(hours=1)
    reopened = completed.transitioned(TaskState.OPEN, at=WHEN + timedelta(hours=2), version=2)
    assert reopened.state is TaskState.OPEN
    assert reopened.closed_at is None
    assert reopened.current_version == 3


def test_stale_expected_version_is_refused() -> None:
    with pytest.raises(TaskError, match="version"):
        _task().transitioned(TaskState.COMPLETED, at=WHEN, version=2)


def test_weekly_friday_yields_the_next_friday() -> None:
    rule = RecurrenceRule(
        recurrence_id=issue_identifier(IdKind.TASK_RECURRENCE),
        principal_id=issue_identifier(IdKind.PRINCIPAL),
        frequency=RecurrenceFrequency.WEEKLY,
        timezone="America/New_York",
        weekdays=frozenset({Weekday.FRIDAY}),
        start_date=date(2026, 8, 14),
    )
    first = next_occurrence(rule)
    assert first == date(2026, 8, 14)
    nxt = next_occurrence(rule, after=date(2026, 8, 14))
    assert nxt == date(2026, 8, 21)
    assert occurrence_key_for(nxt, rule.timezone) == "2026-08-21"


def test_weekdays_skip_the_weekend() -> None:
    rule = RecurrenceRule(
        recurrence_id=issue_identifier(IdKind.TASK_RECURRENCE),
        principal_id=issue_identifier(IdKind.PRINCIPAL),
        frequency=RecurrenceFrequency.WEEKDAYS,
        timezone="UTC",
        start_date=date(2026, 8, 14),
    )
    assert next_occurrence(rule, after=date(2026, 8, 14)) == date(2026, 8, 17)


def test_spring_forward_moves_a_gap_time_forward() -> None:
    zone = ZoneInfo("America/New_York")
    start = datetime(2026, 3, 7, 2, 30, tzinfo=zone)
    rule = RecurrenceRule(
        recurrence_id=issue_identifier(IdKind.TASK_RECURRENCE),
        principal_id=issue_identifier(IdKind.PRINCIPAL),
        frequency=RecurrenceFrequency.DAILY,
        timezone="America/New_York",
        start_at=start.astimezone(UTC),
    )
    nxt = next_occurrence(rule, after=start.astimezone(UTC))
    assert isinstance(nxt, datetime)
    local = nxt.astimezone(zone)
    assert local.date() == date(2026, 3, 8)
    assert local.hour != 2 or local.minute != 30
    assert local >= datetime(2026, 3, 8, 3, 0, tzinfo=zone)


def test_closing_a_task_does_not_touch_commitment_state() -> None:
    commitment = Commitment(
        commitment_id=issue_identifier(IdKind.COMMITMENT),
        principal_id=issue_identifier(IdKind.PRINCIPAL),
        counterparty_person_id=issue_identifier(IdKind.PERSON),
        direction=CommitmentDirection.OWED_TO_PRINCIPAL,
        summary="Sarah owes the permit log",
        state=CommitmentState.OPEN,
        evidence_state=ContinuityEvidenceState.ACCEPTED,
        current_version=1,
        opened_at=WHEN,
        created_at=WHEN,
        updated_at=WHEN,
    )
    task = _task(person_id=commitment.counterparty_person_id, task_role=TaskRole.FOLLOW_UP)
    closed = task.transitioned(TaskState.COMPLETED, at=WHEN + timedelta(days=1), version=1)
    assert closed.is_terminal
    assert commitment.state is CommitmentState.OPEN
    assert commitment.closed_at is None
