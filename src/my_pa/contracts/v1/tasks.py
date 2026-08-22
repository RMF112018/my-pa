"""The public shapes of a task-read answer (WP-TM-03).

Three models, one per kind of answer the four `tasks.` read capabilities
produce: `TaskView` for `tasks.read`, `TaskListEntry` for `tasks.list` and
`tasks.search` alike (the two share one page shape, exactly the way `search`
and `list` are two filters over the same rows rather than two different kinds
of row), and `TaskHistoryEntryView` for `tasks.history`. Models rather than
dictionaries assembled in the use case, for the reason `contracts.v1.documents`
gives: the shape of a public answer is a contract, and a contract that exists
only as the code that happened to build it cannot be checked against anything.

**No owner, on all three.** `domain.task.task.Task` and
`domain.task.history.TaskHistoryEntry` both carry `principal_id`, and none of
these views does. A caller reaches only its own tasks — every
`TaskManagementRepository` read method filters by the authenticated
partition — so echoing the owner back would tell the caller nothing it did not
already know about itself, while making every answer a place another
Principal's identifier could appear if the filter ever broke. The safe
direction is the one where the field does not exist, exactly as
`contracts.v1.documents` argues for its own three views.

**No `client_context` on `TaskHistoryEntryView`.** `TaskHistoryEntry`'s own
module docstring is explicit that the field names a client or tool, a short
closed-shape label, and never a request body or natural-language instruction —
but `AGENTS.md` section 5 requires logs to exclude message bodies as a
property of what gets disclosed, not of what a field happens to have been
used for so far. Every other field on the domain entry is safe to publish
outright (a mutation action, an actor kind, an outcome, and the two version
numbers the receipt pairs), and this view carries exactly those.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from my_pa.contracts.v1.base import StrictModel, UtcDatetime
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.situation.continuity import ContinuityAcceptanceKind, ContinuityEvidenceState
from my_pa.domain.task.history import TaskMutationAction, TaskMutationActor, TaskMutationOutcome
from my_pa.domain.task.lifecycle import TaskLifecycleState, TaskPriority

__all__ = ["TaskHistoryEntryView", "TaskListEntry", "TaskView"]


class TaskView(StrictModel):
    """One task, exactly as `tasks.read` answers it: the caller's own copy in full."""

    task_id: str
    title: str = Field(min_length=1)
    description: str | None = None
    lifecycle_state: TaskLifecycleState
    evidence_state: ContinuityEvidenceState
    origin_evidence_ref: str = Field(min_length=1)
    closure_evidence_ref: str | None = None
    accepted_by_review_decision_id: str | None = None
    acceptance_kind: ContinuityAcceptanceKind | None = None
    closure_history_id: str | None = None
    version: int = Field(ge=1)
    priority: TaskPriority | None = None
    due_at: UtcDatetime | None = None
    scheduled_at: UtcDatetime | None = None
    deferred_until: UtcDatetime | None = None
    archived_at: UtcDatetime | None = None
    project_id: str | None = None
    situation_id: str | None = None
    recurrence_id: str | None = None
    opened_at: UtcDatetime
    closed_at: UtcDatetime | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    commitment_id: str | None = None
    role: str | None = None

    @model_validator(mode="after")
    def _check(self) -> TaskView:
        validate_identifier(self.task_id, IdKind.TASK)
        if self.project_id is not None:
            validate_identifier(self.project_id, IdKind.PROJECT)
        if self.situation_id is not None:
            validate_identifier(self.situation_id, IdKind.SITUATION)
        if self.recurrence_id is not None:
            validate_identifier(self.recurrence_id, IdKind.TASK_RECURRENCE)
        if self.commitment_id is not None:
            validate_identifier(self.commitment_id, IdKind.COMMITMENT)
        if self.accepted_by_review_decision_id is not None:
            validate_identifier(self.accepted_by_review_decision_id, IdKind.REVIEW_DECISION)
        if self.closure_history_id is not None:
            validate_identifier(self.closure_history_id, IdKind.TASK_HISTORY)
        return self


class TaskListEntry(StrictModel):
    """One task as `tasks.list`/`tasks.search` present it: a page row, not the full record.

    Deliberately narrower than `TaskView` — no `evidence_state`,
    `origin_evidence_ref`, `closure_evidence_ref`, or
    `accepted_by_review_decision_id` — because a page of many rows is read for
    triage, not for the evidentiary detail `tasks.read` returns about the one
    task a caller already named. The fields kept are exactly the ones a caller
    scanning a page needs to decide which task to read next: what it is
    called, where it stands, how urgent it is, and when it last moved.
    """

    task_id: str
    title: str = Field(min_length=1)
    lifecycle_state: TaskLifecycleState
    priority: TaskPriority | None = None
    due_at: UtcDatetime | None = None
    scheduled_at: UtcDatetime | None = None
    deferred_until: UtcDatetime | None = None
    archived_at: UtcDatetime | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def _check(self) -> TaskListEntry:
        validate_identifier(self.task_id, IdKind.TASK)
        return self


class TaskHistoryEntryView(StrictModel):
    """One append-only mutation receipt, as `tasks.history` publishes it.

    `before_version`/`after_version` are published outright, the same
    optimistic-concurrency pairing `TaskHistoryEntry`'s own docstring
    describes as the receipt's whole point: a reader confirms a claimed
    mutation against the row it names without trusting the claim.
    """

    history_id: str
    task_id: str
    action: TaskMutationAction
    actor: TaskMutationActor
    outcome: TaskMutationOutcome
    before_version: int = Field(ge=0)
    after_version: int = Field(ge=0)
    occurred_at: UtcDatetime
    recorded_at: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> TaskHistoryEntryView:
        validate_identifier(self.history_id, IdKind.TASK_HISTORY)
        validate_identifier(self.task_id, IdKind.TASK)
        return self
