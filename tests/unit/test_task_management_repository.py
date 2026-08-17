"""`SqlTaskManagementRepository` row hydration, without a database.

The live ChatLLM `tasks.list`/`tasks.read` crash was `_to_task` raising
inside `Task.__post_init__` for accepted rows authored as
`direct_principal`. Those rows are legal in `knowledge.tasks` and already
readable on the Pulse; this proves the task-management mapper can load them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from my_pa.domain.situation.continuity import ContinuityAcceptanceKind, ContinuityEvidenceState
from my_pa.domain.task.lifecycle import TaskLifecycleState
from my_pa.infrastructure.persistence.task_management import _to_task

PRINCIPAL_ID = "prn_aaaa0001aaaa0001aaaa0001"
TASK_ID = "tsk_aaaa0001aaaa0001aaaa"
ORIGIN = "cap_aaaa0001aaaa0001aaaa"
WHEN = datetime(2026, 8, 15, 11, 52, 11, tzinfo=UTC)


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
    assert task.acceptance_kind is ContinuityAcceptanceKind.DIRECT_PRINCIPAL
    assert task.accepted_by_review_decision_id is None
