"""`TaskManagementService`: the one canonical way to mutate a Task.

WP-TM-01 built the domain model (`domain.task.task.Task`,
`domain.task.history.TaskHistoryEntry`) and the schema underneath it. This
module is WP-TM-02: the application-layer mechanism that actually creates,
updates, and transitions a Task, with the two guarantees the plan asks of it —
optimistic concurrency (`expected_version`) and idempotency (`idempotency_key`)
— and a receipt written for every attempt, whatever became of it.

**This is not wired into `ApplicationService.invoke` or any transport.**
`TaskManagementService` takes its own `Callable[[], TaskManagementUnitOfWork]`
factory, mirroring `ApplicationService.__init__`'s shape without touching
`ApplicationService` itself, `SqlAlchemyUnitOfWork`, the command dispatch
table, or the MCP tool surface. Composing this service into any of those,
choosing its command names and transport-facing schemas, and binding it to an
OAuth client profile are later work: this package's job is the mutation
mechanism underneath that wiring, proven against a real database, not the
wiring itself.

**Every mutation is one transaction: version check, task write, history write,
together or not at all.** `_mutate` is the single private mechanism every
public method here delegates to, and it opens exactly one
`TaskManagementUnitOfWork` per call. There is deliberately no method on this
class that writes a task row without also writing the history row that
attempt produced — an applied mutation with no receipt, or a receipt with no
matching task state, is exactly the drift this table exists to make
impossible.

**Idempotency defers entirely to the prior receipt.** A mutation carrying an
`idempotency_key` this Principal has used before returns the *original*
`TaskHistoryEntry` — whatever it recorded, applied, rejected, or no-op —
without re-validating or re-applying anything, and marks the returned
`TaskMutationReceipt.replayed` `True` so a caller can tell a replay from a
first attempt. This does not detect a key reused for a materially different
request; it only guarantees what the plan requires, that retrying the same
request never doubles its effect.

**"Direct acceptance" is a parameter on `create_task`, not a new action.**
`domain.task.history.TaskMutationAction` is a closed, ten-member vocabulary
`tables.py`'s CHECK constraint restates verbatim, and it has no member for
"accepted on creation" — reopening that migration to add one is exactly the
kind of change this package does not make. `domain.task.task.Task` already
requires (`__post_init__`'s acceptance pairing) that an
`ContinuityEvidenceState.ACCEPTED` task names the review decision that
accepted it, so `create_task`'s `accepted_by_review_decision_id` parameter is
the whole "direct acceptance path": passing it creates the task already
accepted, under the ordinary `CREATE` action, in the one call. This module
never creates, resolves, or validates a review decision itself — the
Review/AI-proposal promotion workflow that would produce one is out of scope
here, exactly as recurrence generation, bulk operations, and the Daily Brief
projection are.

**Errors here are plain exceptions, not `application.errors` codes.** The
existing precedent is `domain.source.provider.VersionChangedError`: a plain
exception a lower layer raises and a higher one (`ApplicationService.invoke`)
translates into the public taxonomy at the boundary that owns that
translation. `TaskNotFoundError`, `TaskVersionConflictError`, and
`IllegalTaskTransitionError` follow the same shape here, because the boundary
that would translate them — the dispatcher this service is not yet wired
into — does not exist yet either. Translating them into
`application.errors.NotFoundError`/`ConflictError` is that later package's
job, not a gap in this one.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from my_pa.contracts.ports import TaskManagementUnitOfWork
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import utc_now
from my_pa.domain.situation.continuity import ContinuityEvidenceState
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.history import (
    TaskHistoryEntry,
    TaskMutationAction,
    TaskMutationActor,
    TaskMutationOutcome,
)
from my_pa.domain.task.lifecycle import (
    TERMINAL_TASK_LIFECYCLE_STATES,
    TaskLifecycleState,
    TaskPriority,
)
from my_pa.domain.task.role import TaskRole
from my_pa.domain.task.task import Task

__all__ = [
    "IllegalTaskTransitionError",
    "TaskManagementService",
    "TaskMutationReceipt",
    "TaskNotFoundError",
    "TaskVersionConflictError",
]


class TaskNotFoundError(Exception):
    """Raised when a mutation names a `task_id` absent from this Principal's partition."""


class TaskVersionConflictError(Exception):
    """Raised when `expected_version` does not match the task's current version.

    Carries the `TaskMutationReceipt` this attempt still produced — the
    `REJECTED` history row is written and committed before this is raised, so
    a caller that catches this exception can still inspect exactly what was
    recorded about the refusal.
    """

    def __init__(self, receipt: TaskMutationReceipt) -> None:
        super().__init__("the task's current version does not match expected_version")
        self.receipt = receipt


class IllegalTaskTransitionError(ValueError):
    """Raised when a requested lifecycle transition is not one this build permits."""


@dataclass(frozen=True, slots=True)
class TaskMutationReceipt:
    """What a mutation attempt returns: the history row produced, and the task as it now stands."""

    history: TaskHistoryEntry
    task: Task
    #: `True` when `history` is a prior attempt's receipt, returned unchanged
    #: because the request's `idempotency_key` had already been used.
    replayed: bool = False


class TaskManagementService:
    """The one canonical entry point for creating, updating, and transitioning a Task."""

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], TaskManagementUnitOfWork],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def create_task(
        self,
        *,
        principal_id: str,
        title: str,
        origin_evidence_ref: str,
        actor: TaskMutationActor,
        description: str | None = None,
        priority: TaskPriority | None = None,
        due_at: datetime | None = None,
        project_id: str | None = None,
        situation_id: str | None = None,
        accepted_by_review_decision_id: str | None = None,
        idempotency_key: str | None = None,
        client_context: str | None = None,
    ) -> TaskMutationReceipt:
        """Create a new task. The direct-acceptance path: pass `accepted_by_review_decision_id`.

        A caller that passes `accepted_by_review_decision_id` gets a task
        created already `ContinuityEvidenceState.ACCEPTED`, in this one call,
        under the ordinary `CREATE` action — see this module's docstring for
        why that is the whole "direct acceptance path" this package builds.
        Omit it and the task is created `PROPOSED`, exactly as `create_task`
        with no acceptance argument would suggest.
        """

        def change(current: Task | None) -> Task:
            del current  # a creation attempt never reads an existing row
            now = self._clock()
            evidence_state = (
                ContinuityEvidenceState.ACCEPTED
                if accepted_by_review_decision_id is not None
                else ContinuityEvidenceState.PROPOSED
            )
            return Task(
                task_id=issue_identifier(IdKind.TASK),
                principal_id=principal_id,
                title=title,
                lifecycle_state=TaskLifecycleState.OPEN,
                evidence_state=evidence_state,
                origin_evidence_ref=origin_evidence_ref,
                opened_at=now,
                created_at=now,
                updated_at=now,
                description=description,
                priority=priority,
                due_at=due_at,
                project_id=project_id,
                situation_id=situation_id,
                accepted_by_review_decision_id=accepted_by_review_decision_id,
            )

        return self._mutate(
            principal_id=principal_id,
            task_id=None,
            expected_version=None,
            action=TaskMutationAction.CREATE,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            change=change,
        )

    def update_title(
        self,
        *,
        principal_id: str,
        task_id: str,
        title: str,
        expected_version: int,
        actor: TaskMutationActor,
        idempotency_key: str | None = None,
        client_context: str | None = None,
    ) -> TaskMutationReceipt:
        """Rename a task. A `title` equal to the current one is recorded `NO_OP`, not `APPLIED`."""
        return self._mutate(
            principal_id=principal_id,
            task_id=task_id,
            expected_version=expected_version,
            action=TaskMutationAction.UPDATE_TITLE,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            change=lambda current: dataclasses.replace(current, title=title),
        )

    def update_description(
        self,
        *,
        principal_id: str,
        task_id: str,
        description: str | None,
        expected_version: int,
        actor: TaskMutationActor,
        idempotency_key: str | None = None,
        client_context: str | None = None,
    ) -> TaskMutationReceipt:
        """Set or clear a task's description. Equal to current is `NO_OP`."""
        return self._mutate(
            principal_id=principal_id,
            task_id=task_id,
            expected_version=expected_version,
            action=TaskMutationAction.UPDATE_DESCRIPTION,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            change=lambda current: dataclasses.replace(current, description=description),
        )

    def set_priority(
        self,
        *,
        principal_id: str,
        task_id: str,
        priority: TaskPriority | None,
        expected_version: int,
        actor: TaskMutationActor,
        idempotency_key: str | None = None,
        client_context: str | None = None,
    ) -> TaskMutationReceipt:
        """Set, change, or clear (`priority=None`) a task's Principal-assigned priority."""
        return self._mutate(
            principal_id=principal_id,
            task_id=task_id,
            expected_version=expected_version,
            action=TaskMutationAction.SET_PRIORITY,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            change=lambda current: dataclasses.replace(current, priority=priority),
        )

    def schedule(
        self,
        *,
        principal_id: str,
        task_id: str,
        scheduled_at: datetime | None,
        expected_version: int,
        actor: TaskMutationActor,
        idempotency_key: str | None = None,
        client_context: str | None = None,
    ) -> TaskMutationReceipt:
        """Set or clear (`scheduled_at=None`) when a task is scheduled to be worked."""
        return self._mutate(
            principal_id=principal_id,
            task_id=task_id,
            expected_version=expected_version,
            action=TaskMutationAction.SCHEDULE,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            change=lambda current: dataclasses.replace(current, scheduled_at=scheduled_at),
        )

    def defer(
        self,
        *,
        principal_id: str,
        task_id: str,
        deferred_until: datetime | None,
        expected_version: int,
        actor: TaskMutationActor,
        idempotency_key: str | None = None,
        client_context: str | None = None,
    ) -> TaskMutationReceipt:
        """Set or clear (`deferred_until=None`) when a task should resurface."""
        return self._mutate(
            principal_id=principal_id,
            task_id=task_id,
            expected_version=expected_version,
            action=TaskMutationAction.DEFER,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            change=lambda current: dataclasses.replace(current, deferred_until=deferred_until),
        )

    def archive(
        self,
        *,
        principal_id: str,
        task_id: str,
        expected_version: int,
        actor: TaskMutationActor,
        idempotency_key: str | None = None,
        client_context: str | None = None,
    ) -> TaskMutationReceipt:
        """Archive a task. Already-archived is recorded `NO_OP`, not `APPLIED`."""
        return self._mutate(
            principal_id=principal_id,
            task_id=task_id,
            expected_version=expected_version,
            action=TaskMutationAction.ARCHIVE,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            change=lambda current: dataclasses.replace(current, archived_at=self._clock()),
        )

    def unarchive(
        self,
        *,
        principal_id: str,
        task_id: str,
        expected_version: int,
        actor: TaskMutationActor,
        idempotency_key: str | None = None,
        client_context: str | None = None,
    ) -> TaskMutationReceipt:
        """Unarchive a task. Already-unarchived is recorded `NO_OP`, not `APPLIED`."""
        return self._mutate(
            principal_id=principal_id,
            task_id=task_id,
            expected_version=expected_version,
            action=TaskMutationAction.UNARCHIVE,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            change=lambda current: dataclasses.replace(current, archived_at=None),
        )

    def transition_lifecycle(
        self,
        *,
        principal_id: str,
        task_id: str,
        to_state: TaskLifecycleState,
        expected_version: int,
        actor: TaskMutationActor,
        closure_evidence_ref: str | None = None,
        idempotency_key: str | None = None,
        client_context: str | None = None,
    ) -> TaskMutationReceipt:
        """Move a task to `to_state`.

        A terminal state (`TERMINAL_TASK_LIFECYCLE_STATES`) is one-way: this
        build refuses to transition a task out of `COMPLETED` or `CANCELLED`,
        raising `IllegalTaskTransitionError` rather than silently no-opting,
        because reopening a closed task is a decision this package does not
        make on a caller's behalf. Transitioning *into* a terminal state
        requires `closure_evidence_ref`, for the same reason
        `domain.task.task.Task.__post_init__` already enforces it. Requesting
        the state the task is already in is recorded `NO_OP`.
        """

        def change(current: Task) -> Task:
            already_terminal = current.lifecycle_state in TERMINAL_TASK_LIFECYCLE_STATES
            unchanged = to_state == current.lifecycle_state
            if already_terminal and not unchanged:
                raise IllegalTaskTransitionError(
                    "a task in a terminal lifecycle state cannot be transitioned further"
                )
            if to_state in TERMINAL_TASK_LIFECYCLE_STATES and not unchanged:
                if not (closure_evidence_ref or "").strip():
                    raise IllegalTaskTransitionError(
                        "closing a task requires the evidence that closed it"
                    )
                return dataclasses.replace(
                    current,
                    lifecycle_state=to_state,
                    closed_at=self._clock(),
                    closure_evidence_ref=closure_evidence_ref,
                )
            return dataclasses.replace(current, lifecycle_state=to_state)

        return self._mutate(
            principal_id=principal_id,
            task_id=task_id,
            expected_version=expected_version,
            action=TaskMutationAction.TRANSITION_LIFECYCLE,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            change=change,
        )

    def link_commitment(
        self,
        *,
        principal_id: str,
        task_id: str,
        commitment_id: str,
        expected_version: int,
        actor: TaskMutationActor,
        idempotency_key: str | None = None,
        client_context: str | None = None,
    ) -> TaskMutationReceipt:
        """WP-TM-05: link a task to the `Commitment` named by `commitment_id`.

        This writes only the Task row — `Task.commitment_id` — and never
        touches the Commitment itself: linking does not fulfil, close, or
        otherwise mutate the Commitment, and this build does not verify here
        that `commitment_id` names a real, principal-owned commitment, exactly
        as `create_task`'s `project_id`/`situation_id` are not cross-checked
        against their own tables at this layer. A caller that wants that
        check performs it first, at the layer that already holds a
        `CommitmentManagementRepository` (`application.service`).
        """
        return self._mutate(
            principal_id=principal_id,
            task_id=task_id,
            expected_version=expected_version,
            action=TaskMutationAction.LINK_COMMITMENT,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            change=lambda current: dataclasses.replace(current, commitment_id=commitment_id),
        )

    def set_role(
        self,
        *,
        principal_id: str,
        task_id: str,
        role: TaskRole | None,
        expected_version: int,
        actor: TaskMutationActor,
        idempotency_key: str | None = None,
        client_context: str | None = None,
    ) -> TaskMutationReceipt:
        """Set, change, or clear (`role=None`) a task's `TaskRole`."""
        return self._mutate(
            principal_id=principal_id,
            task_id=task_id,
            expected_version=expected_version,
            action=TaskMutationAction.SET_ROLE,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            change=lambda current: dataclasses.replace(current, role=role),
        )

    def _mutate(
        self,
        *,
        principal_id: str,
        task_id: str | None,
        expected_version: int | None,
        action: TaskMutationAction,
        actor: TaskMutationActor,
        idempotency_key: str | None,
        client_context: str | None,
        change: Callable[[Task], Task] | Callable[[Task | None], Task],
    ) -> TaskMutationReceipt:
        """The single transactional mechanism every public method delegates to.

        One `TaskManagementUnitOfWork` per call: idempotency lookup, the
        row-locked read, the version check, `change`, and both writes all run
        inside it, so the attempt either commits whole or leaves no trace.

        `TaskNotFoundError` and `TaskVersionConflictError` are raised *after*
        the `with` block below, never inside it — raising inside would roll
        back the `REJECTED` history row a stale-version refusal must still
        commit, and the not-found case's empty, harmless transaction commits
        just as emptily either way. `IllegalTaskTransitionError` is the one
        exception allowed to propagate from inside `change()`: it always fires
        before this attempt has written anything, so the transaction it rolls
        back is empty regardless.
        """
        pending_not_found = False
        pending_conflict: TaskMutationReceipt | None = None
        result: TaskMutationReceipt | None = None

        with self._unit_of_work() as uow:
            if idempotency_key is not None:
                prior = uow.tasks.find_history_by_idempotency_key(principal_id, idempotency_key)
                if prior is not None:
                    prior_task = uow.tasks.get_for_update(principal_id, prior.task_id)
                    if prior_task is None:
                        raise RuntimeError(
                            "a recorded history entry names a task that still exists"
                        )
                    result = TaskMutationReceipt(history=prior, task=prior_task, replayed=True)

            if result is None:
                current = (
                    uow.tasks.get_for_update(principal_id, task_id) if task_id is not None else None
                )
                version_mismatch = (
                    current is not None
                    and expected_version is not None
                    and current.version != expected_version
                )

                if task_id is not None and current is None:
                    pending_not_found = True
                elif version_mismatch and current is not None:
                    now = self._clock()
                    rejected_history = self._record(
                        uow=uow,
                        principal_id=principal_id,
                        task_id=current.task_id,
                        action=action,
                        actor=actor,
                        outcome=TaskMutationOutcome.REJECTED,
                        before_version=current.version,
                        after_version=current.version,
                        occurred_at=now,
                        idempotency_key=idempotency_key,
                        client_context=client_context,
                    )
                    pending_conflict = TaskMutationReceipt(history=rejected_history, task=current)
                else:
                    proposed = change(current)  # type: ignore[arg-type]
                    now = self._clock()
                    before_version = current.version if current is not None else 0
                    if current is not None and proposed == current:
                        no_op_history = self._record(
                            uow=uow,
                            principal_id=principal_id,
                            task_id=current.task_id,
                            action=action,
                            actor=actor,
                            outcome=TaskMutationOutcome.NO_OP,
                            before_version=before_version,
                            after_version=before_version,
                            occurred_at=now,
                            idempotency_key=idempotency_key,
                            client_context=client_context,
                        )
                        result = TaskMutationReceipt(history=no_op_history, task=current)
                    else:
                        applied_task = dataclasses.replace(
                            proposed, version=before_version + 1, updated_at=now
                        )
                        if current is None:
                            uow.tasks.insert_task(applied_task)
                        else:
                            uow.tasks.update_task(applied_task)
                        applied_history = self._record(
                            uow=uow,
                            principal_id=principal_id,
                            task_id=applied_task.task_id,
                            action=action,
                            actor=actor,
                            outcome=TaskMutationOutcome.APPLIED,
                            before_version=before_version,
                            after_version=applied_task.version,
                            occurred_at=now,
                            idempotency_key=idempotency_key,
                            client_context=client_context,
                        )
                        result = TaskMutationReceipt(history=applied_history, task=applied_task)

        if pending_not_found:
            raise TaskNotFoundError(f"no task {task_id!r} in this principal's partition")
        if pending_conflict is not None:
            raise TaskVersionConflictError(pending_conflict)
        if result is None:
            raise RuntimeError(
                "unreachable: _mutate exited its transaction with no receipt, conflict, or "
                "not-found"
            )
        return result

    def _record(
        self,
        *,
        uow: TaskManagementUnitOfWork,
        principal_id: str,
        task_id: str,
        action: TaskMutationAction,
        actor: TaskMutationActor,
        outcome: TaskMutationOutcome,
        before_version: int,
        after_version: int,
        occurred_at: datetime,
        idempotency_key: str | None,
        client_context: str | None,
    ) -> TaskHistoryEntry:
        entry = TaskHistoryEntry(
            history_id=issue_identifier(IdKind.TASK_HISTORY),
            principal_id=principal_id,
            task_id=task_id,
            action=action,
            actor=actor,
            outcome=outcome,
            before_version=before_version,
            after_version=after_version,
            occurred_at=occurred_at,
            recorded_at=self._clock(),
            idempotency_key=idempotency_key,
            client_context=client_context,
        )
        uow.tasks.insert_history(entry)
        return entry
