"""`SqlTaskManagementRepository` row hydration and civil-day Work predicates.

The live ChatLLM `tasks.list`/`tasks.read` crash was `_to_task` raising
inside `Task.__post_init__` for accepted rows authored as
`direct_principal`. Those rows are legal in `knowledge.tasks` and already
readable on the Pulse; this proves the task-management mapper can load them.

WP-TUX-01 adds `origin_kind` mapping and civil-day Today/Overdue predicates that
no longer exclude same-day dues earlier than wall-clock `work_now`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import case

from my_pa.domain.situation.continuity import ContinuityAcceptanceKind, ContinuityEvidenceState
from my_pa.domain.task.lifecycle import TaskLifecycleState, TaskOriginKind, TaskWorkView
from my_pa.infrastructure.persistence.tables import tasks
from my_pa.infrastructure.persistence.task_management import (
    _extend_work_view_conditions,
    _to_task,
)

PRINCIPAL_ID = "prn_aaaa0001aaaa0001aaaa0001"
TASK_ID = "tsk_aaaa0001aaaa0001aaaa"
ORIGIN = "cap_aaaa0001aaaa0001aaaa"
WHEN = datetime(2026, 8, 15, 11, 52, 11, tzinfo=UTC)
DAY_START = datetime(2026, 3, 8, 5, 0, tzinfo=UTC)  # US/Eastern civil midnight after DST
DAY_END = datetime(2026, 3, 9, 4, 0, tzinfo=UTC)
WORK_NOW = datetime(2026, 3, 8, 18, 0, tzinfo=UTC)


class _Row:
    def __init__(self, mapping: dict[str, object]) -> None:
        self._mapping = mapping


def test_to_task_hydrates_a_direct_principal_accepted_row() -> None:
    task = _to_task(
        _Row(
            {
                "task_id": TASK_ID,
                "principal_id": PRINCIPAL_ID,
                "title": "Verify ChatLLM write behavior on pulse",
                "description": None,
                "lifecycle_state": "open",
                "evidence_state": "accepted",
                "origin_kind": "evidence",
                "origin_evidence_ref": ORIGIN,
                "opened_at": WHEN,
                "created_at": WHEN,
                "updated_at": WHEN,
                "version": 1,
                "priority": None,
                "due_at": WHEN,
                "scheduled_at": None,
                "deferred_until": None,
                "archived_at": None,
                "project_id": None,
                "situation_id": None,
                "recurrence_id": None,
                "closed_at": None,
                "closure_evidence_ref": None,
                "accepted_by_review_decision_id": None,
                "acceptance_kind": "direct_principal",
            }
        )
    )
    assert task.task_id == TASK_ID
    assert task.lifecycle_state is TaskLifecycleState.OPEN
    assert task.evidence_state is ContinuityEvidenceState.ACCEPTED
    assert task.origin_kind is TaskOriginKind.EVIDENCE
    assert task.acceptance_kind is ContinuityAcceptanceKind.DIRECT_PRINCIPAL
    assert task.accepted_by_review_decision_id is None


def test_to_task_hydrates_a_direct_principal_origin_without_evidence() -> None:
    task = _to_task(
        _Row(
            {
                "task_id": TASK_ID,
                "principal_id": PRINCIPAL_ID,
                "title": "Principal-authored create",
                "description": None,
                "lifecycle_state": "open",
                "evidence_state": "accepted",
                "origin_kind": "direct_principal",
                "origin_evidence_ref": None,
                "opened_at": WHEN,
                "created_at": WHEN,
                "updated_at": WHEN,
                "version": 1,
                "priority": None,
                "due_at": None,
                "scheduled_at": None,
                "deferred_until": None,
                "archived_at": None,
                "project_id": None,
                "situation_id": None,
                "recurrence_id": None,
                "closed_at": None,
                "closure_evidence_ref": None,
                "accepted_by_review_decision_id": None,
                "acceptance_kind": "direct_principal",
            }
        )
    )
    assert task.origin_kind is TaskOriginKind.DIRECT_PRINCIPAL
    assert task.origin_evidence_ref is None


def test_to_task_defaults_missing_origin_kind_to_evidence_during_transition() -> None:
    task = _to_task(
        _Row(
            {
                "task_id": TASK_ID,
                "principal_id": PRINCIPAL_ID,
                "title": "Legacy evidence row",
                "description": None,
                "lifecycle_state": "open",
                "evidence_state": "proposed",
                "origin_evidence_ref": ORIGIN,
                "opened_at": WHEN,
                "created_at": WHEN,
                "updated_at": WHEN,
                "version": 1,
                "priority": None,
                "due_at": None,
                "scheduled_at": None,
                "deferred_until": None,
                "archived_at": None,
                "project_id": None,
                "situation_id": None,
                "recurrence_id": None,
                "closed_at": None,
                "closure_evidence_ref": None,
                "accepted_by_review_decision_id": None,
                "acceptance_kind": "none",
            }
        )
    )
    assert task.origin_kind is TaskOriginKind.EVIDENCE


def test_today_predicate_uses_civil_day_not_work_now() -> None:
    conditions: list[object] = []
    priority_rank = case((tasks.c.priority == "p1", 1), else_=5)
    _extend_work_view_conditions(
        conditions,
        work_view=TaskWorkView.TODAY,
        work_start=DAY_START,
        work_end=DAY_END,
        work_now=WORK_NOW,
        effective_at=tasks.c.due_at,
        calendar_at=tasks.c.due_at,
        priority_rank=priority_rank,
    )
    compiled = " | ".join(str(condition) for condition in conditions)
    assert str(WORK_NOW) not in compiled
    assert "due_at" in compiled
    assert "scheduled_at" in compiled
    # Membership is the civil-day window alone — no wall-clock exclusion.
    assert " >= " in compiled and " < " in compiled


def test_overdue_predicate_uses_day_start_not_work_now() -> None:
    conditions: list[object] = []
    priority_rank = case((tasks.c.priority == "p1", 1), else_=5)
    _extend_work_view_conditions(
        conditions,
        work_view=TaskWorkView.OVERDUE,
        work_start=DAY_START,
        work_end=DAY_END,
        work_now=WORK_NOW,
        effective_at=tasks.c.due_at,
        calendar_at=tasks.c.due_at,
        priority_rank=priority_rank,
    )
    compiled = " | ".join(str(condition) for condition in conditions)
    assert str(WORK_NOW) not in compiled
    assert "due_at" in compiled
    # Civil-day start is the overdue cutoff, not wall-clock now.
    assert any(
        getattr(getattr(condition, "right", None), "value", None) == DAY_START
        for condition in conditions
    )


def test_upcoming_predicate_uses_day_end_without_work_now_gate() -> None:
    conditions: list[object] = []
    priority_rank = case((tasks.c.priority == "p1", 1), else_=5)
    _extend_work_view_conditions(
        conditions,
        work_view=TaskWorkView.UPCOMING,
        work_start=DAY_START,
        work_end=DAY_END,
        work_now=WORK_NOW,
        effective_at=tasks.c.due_at,
        calendar_at=tasks.c.due_at,
        priority_rank=priority_rank,
    )
    compiled = " | ".join(str(condition) for condition in conditions)
    assert str(WORK_NOW) not in compiled
    assert any(
        getattr(getattr(condition, "right", None), "value", None) == DAY_END
        or DAY_END
        in [
            getattr(getattr(element, "right", None), "value", None)
            for element in getattr(condition, "clauses", ())
        ]
        for condition in conditions
    )
