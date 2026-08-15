"""WP-TM-01: the task-management domain built on top of the continuity `Task`.

`task.py` is the extended `Task` model; `lifecycle.py` names its lifecycle and
priority vocabulary; `recurrence.py` names recurring series and computes the one
actionable next occurrence for one; `history.py` names one append-only mutation
receipt. See `task.py`'s module docstring for how this relates to
`domain.situation.continuity.Task`, which this package does not replace.
"""

from __future__ import annotations

from my_pa.domain.task.commitment import Commitment
from my_pa.domain.task.commitment_history import CommitmentHistoryEntry, CommitmentMutationAction
from my_pa.domain.task.history import (
    IDEMPOTENCY_KEY_PATTERN,
    MAX_CLIENT_CONTEXT_CHARACTERS,
    TaskHistoryEntry,
    TaskMutationAction,
    TaskMutationActor,
    TaskMutationOutcome,
)
from my_pa.domain.task.lifecycle import (
    TERMINAL_TASK_LIFECYCLE_STATES,
    TaskLifecycleState,
    TaskPriority,
    legacy_state_for,
)
from my_pa.domain.task.recurrence import (
    MAX_RECURRENCE_SEARCH_STEPS,
    RecurrenceError,
    RecurrenceFrequency,
    RecurrenceRule,
    Weekday,
    next_occurrence,
)
from my_pa.domain.task.role import TaskRole
from my_pa.domain.task.task import Task

__all__ = [
    "IDEMPOTENCY_KEY_PATTERN",
    "MAX_CLIENT_CONTEXT_CHARACTERS",
    "MAX_RECURRENCE_SEARCH_STEPS",
    "TERMINAL_TASK_LIFECYCLE_STATES",
    "Commitment",
    "CommitmentHistoryEntry",
    "CommitmentMutationAction",
    "RecurrenceError",
    "RecurrenceFrequency",
    "RecurrenceRule",
    "Task",
    "TaskHistoryEntry",
    "TaskLifecycleState",
    "TaskMutationAction",
    "TaskMutationActor",
    "TaskMutationOutcome",
    "TaskPriority",
    "TaskRole",
    "Weekday",
    "legacy_state_for",
    "next_occurrence",
]
