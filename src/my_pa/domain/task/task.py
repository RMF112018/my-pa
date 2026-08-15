"""`Task`, extended: the WP-TM-01 domain model over `knowledge.tasks`.

WP-11's `situation.continuity.Task` remains the minimal continuity object: it
is what `continuity_lifecycle_events`, the Pulse derivation, and the existing
`situation_repository` read and write today, and none of those callers change
under this work package. This module is the richer model the task-management
foundation adds *alongside* it, over the same row: every field
`continuity.Task` carries is still a column on `knowledge.tasks`, and this
`Task` adds the ones WP-TM-01 requires — `lifecycle_state`, `priority`,
`scheduled_at`, `deferred_until`, `archived_at`, `version`, and `recurrence_id`
— without removing or renaming any of the legacy ones. Wiring an application
surface to read and write through *this* model instead of `continuity.Task` is
a later work package's job, not this one's.

`__post_init__` enforces exactly the invariants
`tables.py`'s CHECK constraints enforce at the server, restated here so a
caller gets the same refusal in-process before a write is even attempted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.situation.continuity import ContinuityEvidenceState
from my_pa.domain.task.lifecycle import (
    TERMINAL_TASK_LIFECYCLE_STATES,
    TaskLifecycleState,
    TaskPriority,
)
from my_pa.domain.task.role import TaskRole

__all__ = ["Task"]


@dataclass(frozen=True, slots=True)
class Task:
    """Work the Principal holds alone, at the fidelity task management needs.

    `version` starts at `1` and is the optimistic-concurrency counter: every
    applied mutation advances it by exactly one, and
    `TaskHistoryEntry.before_version`/`after_version` are read against it. It is
    not a row count and not a revision identifier; it exists to let a writer
    detect that the row it read is no longer the row it would be writing back.
    """

    task_id: str
    principal_id: str
    title: str
    lifecycle_state: TaskLifecycleState
    evidence_state: ContinuityEvidenceState
    origin_evidence_ref: str
    opened_at: datetime
    created_at: datetime
    updated_at: datetime
    version: int = 1
    priority: TaskPriority | None = None
    due_at: datetime | None = None
    scheduled_at: datetime | None = None
    deferred_until: datetime | None = None
    archived_at: datetime | None = None
    project_id: str | None = None
    situation_id: str | None = None
    recurrence_id: str | None = None
    closed_at: datetime | None = None
    closure_evidence_ref: str | None = None
    accepted_by_review_decision_id: str | None = None
    #: WP-TM-05: the `Commitment` this Task is linked to, if any, and the role
    #: it serves. Neither field turns a Task into a Commitment or vice versa —
    #: `Task` and `Commitment` remain distinct canonical objects, and a linked
    #: Task's completion never fulfils or closes the Commitment it names; only
    #: an explicit `close_commitment` call does that.
    commitment_id: str | None = None
    role: TaskRole | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.task_id, IdKind.TASK)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not self.title.strip():
            raise ValueError("a task carries a non-blank title")
        if not isinstance(self.lifecycle_state, TaskLifecycleState):
            raise ValueError("a task names one known lifecycle state")
        if not isinstance(self.evidence_state, ContinuityEvidenceState):
            raise ValueError("a task names one known evidence state")
        if not self.origin_evidence_ref.strip():
            raise ValueError("a task records the evidence it was read out of")
        if self.version < 1:
            raise ValueError("a task version starts at one and only increases")
        if self.priority is not None and not isinstance(self.priority, TaskPriority):
            raise ValueError("a task priority, when set, is one known value")
        if self.project_id is not None:
            validate_identifier(self.project_id, IdKind.PROJECT)
        if self.situation_id is not None:
            validate_identifier(self.situation_id, IdKind.SITUATION)
        if self.recurrence_id is not None:
            validate_identifier(self.recurrence_id, IdKind.TASK_RECURRENCE)
        if self.commitment_id is not None:
            validate_identifier(self.commitment_id, IdKind.COMMITMENT)
        if self.role is not None and not isinstance(self.role, TaskRole):
            raise ValueError("a task role, when set, is one known value")
        if self.accepted_by_review_decision_id is not None:
            validate_identifier(self.accepted_by_review_decision_id, IdKind.REVIEW_DECISION)
        _require_acceptance_pairing(self.evidence_state, self.accepted_by_review_decision_id)

        ensure_utc(self.opened_at)
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)
        for optional_instant in (
            self.due_at,
            self.scheduled_at,
            self.deferred_until,
            self.archived_at,
            self.closed_at,
        ):
            if optional_instant is not None:
                ensure_utc(optional_instant)

        is_terminal = self.lifecycle_state in TERMINAL_TASK_LIFECYCLE_STATES
        if is_terminal is not (self.closed_at is not None):
            raise ValueError("a terminal task records when it closed, and only then")
        if is_terminal and not (self.closure_evidence_ref or "").strip():
            raise ValueError("a terminal task carries the evidence that closed it")


def _require_acceptance_pairing(
    evidence_state: ContinuityEvidenceState, review_decision_id: str | None
) -> None:
    if (evidence_state is ContinuityEvidenceState.ACCEPTED) is not (review_decision_id is not None):
        raise ValueError("an accepted task names the review decision that accepted it")
