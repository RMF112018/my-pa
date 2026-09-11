"""`knowledge.tasks`/`knowledge.task_history`, behind `contracts.ports.TaskManagementRepository`.

WP-TM-02. This module is the one adapter that puts WP-TM-01's richer
`domain.task.task.Task` on a connection: every statement carries
`principal_id`, exactly as `situation_repository.SqlContinuityRepository`
carries it for the two-state model, so a read or write against another
Principal's task is answered as though the task did not exist.

**`get_for_update` issues `SELECT ... FOR UPDATE`.** `TaskManagementRepository`'s
own docstring states why: `TaskManagementService` reads a task and conditionally
writes it back inside the same transaction, and the row lock is what keeps that
comparison honest against a second writer racing between the two statements
rather than merely likely to be.

**`insert_task`/`update_task` derive the legacy `state` column themselves.**
`domain.task.task.Task` does not carry `state` at all — only `lifecycle_state`
— because `lifecycle.legacy_state_for` is the single source of truth for the
mapping and `tables.py`'s `a_task_lifecycle_state_matches_its_legacy_state`
CHECK is the server's restatement of the same rule. Deriving `state` here,
rather than asking a caller to pass it, is what keeps every write through this
module unable to let the two columns disagree.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from types import TracebackType
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Engine,
    and_,
    asc,
    case,
    desc,
    false,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.engine import Connection, Row
from sqlalchemy.exc import IntegrityError

from my_pa.contracts.ports import (
    BulkIdempotencyConflictError,
    TaskManagementRepository,
    TaskManagementUnitOfWork,
    WorkCursorError,
)
from my_pa.domain.situation.continuity import ContinuityAcceptanceKind, ContinuityEvidenceState
from my_pa.domain.task.bulk import TaskBulkOperation
from my_pa.domain.task.comment import TaskComment
from my_pa.domain.task.history import TaskHistoryEntry, TaskMutationAction, TaskMutationActor
from my_pa.domain.task.history import TaskMutationOutcome as _TaskMutationOutcome
from my_pa.domain.task.lifecycle import (
    TERMINAL_TASK_LIFECYCLE_STATES,
    TaskArchiveMode,
    TaskLifecycleState,
    TaskOriginKind,
    TaskPriority,
    TaskWorkView,
    legacy_state_for,
)
from my_pa.domain.task.role import TaskRole
from my_pa.domain.task.task import Task
from my_pa.infrastructure.persistence.tables import (
    task_bulk_operations,
    task_comments,
    task_history,
    tasks,
)

__all__ = ["SqlAlchemyTaskManagementUnitOfWork", "SqlTaskManagementRepository"]


def _constraint_name(error: IntegrityError) -> str | None:
    """Return psycopg's stable constraint identity without exposing its message."""
    diagnostic = getattr(error.orig, "diag", None)
    return getattr(diagnostic, "constraint_name", None)


class SqlTaskManagementRepository(TaskManagementRepository):
    """`TaskManagementRepository`, over a plain SQLAlchemy Core `Connection`.

    Takes the connection rather than opening one, exactly as every other
    `Sql*Repository` in this package does: the caller owns the transaction,
    this class only issues statements on it.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    # --- tasks -------------------------------------------------------------

    def get_for_update(self, principal_id: str, task_id: str) -> Task | None:
        row = self._connection.execute(
            select(*tasks.c)
            .where(and_(tasks.c.task_id == task_id, tasks.c.principal_id == principal_id))
            .with_for_update()
        ).one_or_none()
        return None if row is None else _to_task(row)

    def insert_task(self, task: Task) -> None:
        self._connection.execute(
            insert(tasks).values(
                task_id=task.task_id,
                principal_id=task.principal_id,
                title=task.title,
                description=task.description,
                state=legacy_state_for(task.lifecycle_state),
                evidence_state=task.evidence_state.value,
                origin_kind=task.origin_kind.value,
                origin_evidence_ref=task.origin_evidence_ref,
                project_id=task.project_id,
                situation_id=task.situation_id,
                due_at=task.due_at,
                opened_at=task.opened_at,
                closed_at=task.closed_at,
                closure_evidence_ref=task.closure_evidence_ref,
                accepted_by_review_decision_id=task.accepted_by_review_decision_id,
                acceptance_kind=_acceptance_kind_value(task),
                created_at=task.created_at,
                updated_at=task.updated_at,
                lifecycle_state=task.lifecycle_state.value,
                priority=None if task.priority is None else task.priority.value,
                scheduled_at=task.scheduled_at,
                deferred_until=task.deferred_until,
                archived_at=task.archived_at,
                version=task.version,
                recurrence_id=task.recurrence_id,
                commitment_id=task.commitment_id,
                role=None if task.role is None else task.role.value,
            )
        )

    def update_task(self, task: Task) -> None:
        self._connection.execute(
            update(tasks)
            .where(and_(tasks.c.task_id == task.task_id, tasks.c.principal_id == task.principal_id))
            .values(
                title=task.title,
                description=task.description,
                state=legacy_state_for(task.lifecycle_state),
                evidence_state=task.evidence_state.value,
                project_id=task.project_id,
                situation_id=task.situation_id,
                due_at=task.due_at,
                closed_at=task.closed_at,
                closure_evidence_ref=task.closure_evidence_ref,
                accepted_by_review_decision_id=task.accepted_by_review_decision_id,
                acceptance_kind=_acceptance_kind_value(task),
                updated_at=task.updated_at,
                lifecycle_state=task.lifecycle_state.value,
                priority=None if task.priority is None else task.priority.value,
                scheduled_at=task.scheduled_at,
                deferred_until=task.deferred_until,
                archived_at=task.archived_at,
                version=task.version,
                recurrence_id=task.recurrence_id,
                commitment_id=task.commitment_id,
                role=None if task.role is None else task.role.value,
            )
        )

    # --- WP-TM-03: the read plane -------------------------------------------
    #
    # None of the four methods below issues `FOR UPDATE`: `get_for_update`'s own
    # module docstring states why the lock exists at all — `TaskManagementService`
    # conditionally overwrites the row it read — and none of these ever writes,
    # so there is no comparison for a lock to protect.

    def get(self, principal_id: str, task_id: str) -> Task | None:
        row = self._connection.execute(
            select(*tasks.c).where(
                and_(tasks.c.task_id == task_id, tasks.c.principal_id == principal_id)
            )
        ).one_or_none()
        return None if row is None else _to_task(row)

    def list_tasks(
        self,
        principal_id: str,
        *,
        lifecycle_state: TaskLifecycleState | None = None,
        priority: TaskPriority | None = None,
        archive_mode: TaskArchiveMode = TaskArchiveMode.EXCLUDE,
        after: str | None = None,
        work_view: TaskWorkView | None = None,
        work_start: datetime | None = None,
        work_end: datetime | None = None,
        work_now: datetime | None = None,
        limit: int,
    ) -> tuple[Task, ...]:
        conditions = [tasks.c.principal_id == principal_id]
        if lifecycle_state is not None:
            conditions.append(tasks.c.lifecycle_state == lifecycle_state.value)
        if priority is not None:
            conditions.append(tasks.c.priority == priority.value)
        if archive_mode is TaskArchiveMode.EXCLUDE:
            conditions.append(tasks.c.archived_at.is_(None))
        else:
            conditions.append(tasks.c.archived_at.is_not(None))
        # A task first becomes actionable at the earlier of due/scheduled,
        # but a later deferral wins. PostgreSQL LEAST/GREATEST are null-safe
        # for this use: they return the non-null operand when only one exists.
        effective_at = func.greatest(
            func.least(tasks.c.due_at, tasks.c.scheduled_at), tasks.c.deferred_until
        )
        calendar_at = func.least(tasks.c.due_at, tasks.c.scheduled_at)
        priority_rank = case(
            (tasks.c.priority == "p1", 1),
            (tasks.c.priority == "p2", 2),
            (tasks.c.priority == "p3", 3),
            (tasks.c.priority == "p4", 4),
            else_=5,
        )
        order_columns: tuple[Any, ...]
        order_columns = _extend_work_view_conditions(
            conditions,
            work_view=work_view,
            work_start=work_start,
            work_end=work_end,
            work_now=work_now,
            effective_at=effective_at,
            calendar_at=calendar_at,
            priority_rank=priority_rank,
        )
        if after is not None:
            anchor = self._connection.execute(
                select(
                    *tasks.c,
                    effective_at.label("effective_at"),
                    calendar_at.label("calendar_at"),
                    priority_rank.label("rank"),
                ).where(and_(*conditions, tasks.c.task_id == after))
            ).one_or_none()
            if anchor is None:
                raise WorkCursorError
            if work_view in {TaskWorkView.TODAY, TaskWorkView.UPCOMING}:
                conditions.append(
                    or_(
                        calendar_at > anchor.calendar_at,
                        and_(calendar_at == anchor.calendar_at, priority_rank > anchor.rank),
                        and_(
                            calendar_at == anchor.calendar_at,
                            priority_rank == anchor.rank,
                            tasks.c.task_id > anchor.task_id,
                        ),
                    )
                )
            elif work_view is TaskWorkView.OVERDUE:
                conditions.append(
                    or_(
                        tasks.c.due_at > anchor.due_at,
                        and_(tasks.c.due_at == anchor.due_at, priority_rank > anchor.rank),
                        and_(
                            tasks.c.due_at == anchor.due_at,
                            priority_rank == anchor.rank,
                            tasks.c.task_id > anchor.task_id,
                        ),
                    )
                )
            elif work_view is TaskWorkView.UNSCHEDULED:
                same_due = (
                    tasks.c.due_at.is_(None)
                    if anchor.due_at is None
                    else tasks.c.due_at == anchor.due_at
                )
                later_due = (
                    false()
                    if anchor.due_at is None
                    else or_(tasks.c.due_at > anchor.due_at, tasks.c.due_at.is_(None))
                )
                conditions.append(
                    or_(
                        later_due,
                        and_(same_due, priority_rank > anchor.rank),
                        and_(
                            same_due,
                            priority_rank == anchor.rank,
                            tasks.c.task_id > anchor.task_id,
                        ),
                    )
                )
            elif work_view is TaskWorkView.RECENTLY_UPDATED:
                conditions.append(
                    or_(
                        tasks.c.updated_at < anchor.updated_at,
                        and_(
                            tasks.c.updated_at == anchor.updated_at,
                            tasks.c.task_id > anchor.task_id,
                        ),
                    )
                )
            elif work_view in {
                TaskWorkView.WAITING,
                TaskWorkView.BLOCKED,
                TaskWorkView.ALL_OPEN,
            }:
                # NULL effective dates sort last. PostgreSQL's comparison with
                # NULL is unknown, so the two NULL branches are explicit.
                later_effective = (
                    or_(effective_at > anchor.effective_at, effective_at.is_(None))
                    if anchor.effective_at is not None
                    else effective_at.is_(None)
                )
                same_effective = (
                    effective_at == anchor.effective_at
                    if anchor.effective_at is not None
                    else effective_at.is_(None)
                )
                conditions.append(
                    or_(
                        priority_rank > anchor.rank,
                        and_(priority_rank == anchor.rank, later_effective),
                        and_(
                            priority_rank == anchor.rank,
                            same_effective,
                            tasks.c.created_at < anchor.created_at,
                        ),
                        and_(
                            priority_rank == anchor.rank,
                            same_effective,
                            tasks.c.created_at == anchor.created_at,
                            tasks.c.task_id > anchor.task_id,
                        ),
                    )
                )
            elif work_view is TaskWorkView.COMPLETED:
                conditions.append(
                    or_(
                        tasks.c.closed_at < anchor.closed_at,
                        and_(
                            tasks.c.closed_at == anchor.closed_at,
                            tasks.c.task_id > anchor.task_id,
                        ),
                    )
                )
            else:
                conditions.append(
                    or_(
                        tasks.c.created_at < anchor.created_at,
                        and_(
                            tasks.c.created_at == anchor.created_at,
                            tasks.c.task_id > anchor.task_id,
                        ),
                    )
                )
        rows = self._connection.execute(
            select(*tasks.c).where(and_(*conditions)).order_by(*order_columns).limit(limit)
        ).all()
        return tuple(_to_task(row) for row in rows)

    def search(
        self,
        principal_id: str,
        query: str,
        limit: int,
        *,
        after: str | None = None,
        archive_mode: TaskArchiveMode = TaskArchiveMode.EXCLUDE,
        work_view: TaskWorkView | None = None,
        work_start: datetime | None = None,
        work_end: datetime | None = None,
        work_now: datetime | None = None,
    ) -> tuple[Task, ...]:
        # `_` and `%` are `ILIKE` wildcards; a query containing either as a
        # literal character (a task titled "50% done", say) is escaped so the
        # match stays lexical rather than accidentally becoming a wildcard the
        # caller never asked for. `\` is escaped first so the two escapes just
        # inserted are not themselves re-escaped.
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        conditions = [
            tasks.c.principal_id == principal_id,
            tasks.c.title.ilike(pattern, escape="\\"),
        ]
        if archive_mode is TaskArchiveMode.EXCLUDE:
            conditions.append(tasks.c.archived_at.is_(None))
        else:
            conditions.append(tasks.c.archived_at.is_not(None))
        effective_at = func.greatest(
            func.least(tasks.c.due_at, tasks.c.scheduled_at), tasks.c.deferred_until
        )
        calendar_at = func.least(tasks.c.due_at, tasks.c.scheduled_at)
        priority_rank = case(
            (tasks.c.priority == "p1", 1),
            (tasks.c.priority == "p2", 2),
            (tasks.c.priority == "p3", 3),
            (tasks.c.priority == "p4", 4),
            else_=5,
        )
        order_columns = _extend_work_view_conditions(
            conditions,
            work_view=work_view,
            work_start=work_start,
            work_end=work_end,
            work_now=work_now,
            effective_at=effective_at,
            calendar_at=calendar_at,
            priority_rank=priority_rank,
        )
        if after is not None:
            anchor = self._connection.execute(
                select(
                    *tasks.c,
                    effective_at.label("effective_at"),
                    calendar_at.label("calendar_at"),
                    priority_rank.label("rank"),
                ).where(and_(*conditions, tasks.c.task_id == after))
            ).one_or_none()
            if anchor is None:
                raise WorkCursorError
            if work_view in {TaskWorkView.TODAY, TaskWorkView.UPCOMING}:
                conditions.append(
                    or_(
                        calendar_at > anchor.calendar_at,
                        and_(calendar_at == anchor.calendar_at, priority_rank > anchor.rank),
                        and_(
                            calendar_at == anchor.calendar_at,
                            priority_rank == anchor.rank,
                            tasks.c.task_id > anchor.task_id,
                        ),
                    )
                )
            elif work_view is TaskWorkView.OVERDUE:
                conditions.append(
                    or_(
                        tasks.c.due_at > anchor.due_at,
                        and_(tasks.c.due_at == anchor.due_at, priority_rank > anchor.rank),
                        and_(
                            tasks.c.due_at == anchor.due_at,
                            priority_rank == anchor.rank,
                            tasks.c.task_id > anchor.task_id,
                        ),
                    )
                )
            elif work_view is TaskWorkView.UNSCHEDULED:
                same_due = (
                    tasks.c.due_at.is_(None)
                    if anchor.due_at is None
                    else tasks.c.due_at == anchor.due_at
                )
                later_due = (
                    false()
                    if anchor.due_at is None
                    else or_(tasks.c.due_at > anchor.due_at, tasks.c.due_at.is_(None))
                )
                conditions.append(
                    or_(
                        later_due,
                        and_(same_due, priority_rank > anchor.rank),
                        and_(
                            same_due,
                            priority_rank == anchor.rank,
                            tasks.c.task_id > anchor.task_id,
                        ),
                    )
                )
            elif work_view is TaskWorkView.RECENTLY_UPDATED:
                conditions.append(
                    or_(
                        tasks.c.updated_at < anchor.updated_at,
                        and_(
                            tasks.c.updated_at == anchor.updated_at,
                            tasks.c.task_id > anchor.task_id,
                        ),
                    )
                )
            elif work_view in {
                TaskWorkView.WAITING,
                TaskWorkView.BLOCKED,
                TaskWorkView.ALL_OPEN,
            }:
                later_effective = (
                    or_(effective_at > anchor.effective_at, effective_at.is_(None))
                    if anchor.effective_at is not None
                    else effective_at.is_(None)
                )
                same_effective = (
                    effective_at == anchor.effective_at
                    if anchor.effective_at is not None
                    else effective_at.is_(None)
                )
                conditions.append(
                    or_(
                        priority_rank > anchor.rank,
                        and_(priority_rank == anchor.rank, later_effective),
                        and_(
                            priority_rank == anchor.rank,
                            same_effective,
                            tasks.c.created_at < anchor.created_at,
                        ),
                        and_(
                            priority_rank == anchor.rank,
                            same_effective,
                            tasks.c.created_at == anchor.created_at,
                            tasks.c.task_id > anchor.task_id,
                        ),
                    )
                )
            elif work_view is TaskWorkView.COMPLETED:
                conditions.append(
                    or_(
                        tasks.c.closed_at < anchor.closed_at,
                        and_(
                            tasks.c.closed_at == anchor.closed_at,
                            tasks.c.task_id > anchor.task_id,
                        ),
                    )
                )
            else:
                conditions.append(
                    or_(
                        tasks.c.created_at < anchor.created_at,
                        and_(
                            tasks.c.created_at == anchor.created_at,
                            tasks.c.task_id > anchor.task_id,
                        ),
                    )
                )
        rows = self._connection.execute(
            select(*tasks.c).where(and_(*conditions)).order_by(*order_columns).limit(limit)
        ).all()
        return tuple(_to_task(row) for row in rows)

    def list_history(
        self, principal_id: str, task_id: str, limit: int, *, after: str | None = None
    ) -> tuple[TaskHistoryEntry, ...]:
        conditions = [
            task_history.c.principal_id == principal_id,
            task_history.c.task_id == task_id,
        ]
        if after is not None:
            anchor = self._connection.execute(
                select(task_history.c.recorded_at, task_history.c.history_id).where(
                    and_(
                        task_history.c.principal_id == principal_id,
                        task_history.c.task_id == task_id,
                        task_history.c.history_id == after,
                    )
                )
            ).one_or_none()
            if anchor is None:
                raise WorkCursorError
            conditions.append(
                or_(
                    task_history.c.recorded_at > anchor.recorded_at,
                    and_(
                        task_history.c.recorded_at == anchor.recorded_at,
                        task_history.c.history_id > anchor.history_id,
                    ),
                )
            )
        rows = self._connection.execute(
            select(*task_history.c)
            .where(and_(*conditions))
            .order_by(asc(task_history.c.recorded_at), asc(task_history.c.history_id))
            .limit(limit)
        ).all()
        return tuple(_to_history(row) for row in rows)

    def latest_applied_terminal_history(
        self, principal_id: str, task_id: str
    ) -> TaskHistoryEntry | None:
        row = self._connection.execute(
            select(*task_history.c)
            .where(
                and_(
                    task_history.c.principal_id == principal_id,
                    task_history.c.task_id == task_id,
                    task_history.c.action == TaskMutationAction.TRANSITION_LIFECYCLE.value,
                    task_history.c.outcome == _TaskMutationOutcome.APPLIED.value,
                )
            )
            .order_by(desc(task_history.c.recorded_at), desc(task_history.c.history_id))
            .limit(1)
        ).one_or_none()
        return None if row is None else _to_history(row)

    # --- history -------------------------------------------------------------

    def find_history_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> TaskHistoryEntry | None:
        row = self._connection.execute(
            select(*task_history.c).where(
                and_(
                    task_history.c.principal_id == principal_id,
                    task_history.c.idempotency_key == idempotency_key,
                )
            )
        ).one_or_none()
        return None if row is None else _to_history(row)

    def insert_history(self, entry: TaskHistoryEntry) -> None:
        self._connection.execute(
            insert(task_history).values(
                history_id=entry.history_id,
                principal_id=entry.principal_id,
                task_id=entry.task_id,
                action=entry.action.value,
                actor=entry.actor.value,
                outcome=entry.outcome.value,
                before_version=entry.before_version,
                after_version=entry.after_version,
                idempotency_key=entry.idempotency_key,
                client_context=entry.client_context,
                request_digest=entry.request_digest,
                bulk_operation_id=entry.bulk_operation_id,
                occurred_at=entry.occurred_at,
                recorded_at=entry.recorded_at,
            )
        )

    def find_bulk_by_preview_key(
        self, principal_id: str, idempotency_key: str
    ) -> TaskBulkOperation | None:
        row = self._connection.execute(
            select(*task_bulk_operations.c).where(
                and_(
                    task_bulk_operations.c.principal_id == principal_id,
                    task_bulk_operations.c.preview_idempotency_key == idempotency_key,
                )
            )
        ).one_or_none()
        return None if row is None else _to_bulk(row)

    def find_bulk_by_confirm_key(
        self, principal_id: str, idempotency_key: str
    ) -> TaskBulkOperation | None:
        row = self._connection.execute(
            select(*task_bulk_operations.c).where(
                and_(
                    task_bulk_operations.c.principal_id == principal_id,
                    task_bulk_operations.c.confirm_idempotency_key == idempotency_key,
                )
            )
        ).one_or_none()
        return None if row is None else _to_bulk(row)

    def get_bulk_for_update(
        self, principal_id: str, bulk_operation_id: str
    ) -> TaskBulkOperation | None:
        row = self._connection.execute(
            select(*task_bulk_operations.c)
            .where(
                and_(
                    task_bulk_operations.c.principal_id == principal_id,
                    task_bulk_operations.c.bulk_operation_id == bulk_operation_id,
                )
            )
            .with_for_update()
        ).one_or_none()
        return None if row is None else _to_bulk(row)

    def insert_bulk(self, operation: TaskBulkOperation) -> None:
        try:
            self._connection.execute(
                insert(task_bulk_operations).values(
                    bulk_operation_id=operation.bulk_operation_id,
                    principal_id=operation.principal_id,
                    preview_idempotency_key=operation.preview_idempotency_key,
                    request_digest=operation.request_digest,
                    previewed_at=operation.previewed_at,
                    expires_at=operation.expires_at,
                    preview_affected=operation.preview_affected,
                    preview_no_op=operation.preview_no_op,
                    confirmed_at=operation.confirmed_at,
                    confirm_idempotency_key=operation.confirm_idempotency_key,
                    affected=operation.affected,
                    no_op=operation.no_op,
                    rejected=operation.rejected,
                    history_ids=list(operation.history_ids),
                )
            )
        except IntegrityError as error:
            if _constraint_name(error) == "one_task_bulk_preview_key_per_principal":
                raise BulkIdempotencyConflictError from error
            raise

    def confirm_bulk(self, operation: TaskBulkOperation) -> None:
        try:
            self._connection.execute(
                update(task_bulk_operations)
                .where(
                    and_(
                        task_bulk_operations.c.principal_id == operation.principal_id,
                        task_bulk_operations.c.bulk_operation_id == operation.bulk_operation_id,
                    )
                )
                .values(
                    confirmed_at=operation.confirmed_at,
                    confirm_idempotency_key=operation.confirm_idempotency_key,
                    affected=operation.affected,
                    no_op=operation.no_op,
                    rejected=operation.rejected,
                    history_ids=list(operation.history_ids),
                )
            )
        except IntegrityError as error:
            if _constraint_name(error) == "one_task_bulk_confirm_key_per_principal":
                raise BulkIdempotencyConflictError from error
            raise

    # --- WP-TUX-01: append-only comments ------------------------------------

    def find_comment_by_idempotency_key(
        self, principal_id: str, idempotency_key: str
    ) -> TaskComment | None:
        row = self._connection.execute(
            select(*task_comments.c).where(
                and_(
                    task_comments.c.principal_id == principal_id,
                    task_comments.c.idempotency_key == idempotency_key,
                )
            )
        ).one_or_none()
        return None if row is None else _to_comment(row)

    def create_comment(self, comment: TaskComment) -> TaskComment:
        """Insert one comment, or return the prior row for the same Principal/key.

        Idempotent at the unique constraint: a concurrent insert that lost the
        race is answered by looking the surviving row back up rather than by
        raising. The insert runs in a savepoint so PostgreSQL can recover from
        the unique violation without aborting the outer unit-of-work
        transaction. A digest mismatch is the caller's problem to refuse at the
        application boundary; this adapter preserves the stored receipt.
        """
        existing = self.find_comment_by_idempotency_key(
            comment.principal_id, comment.idempotency_key
        )
        if existing is not None:
            return existing
        try:
            with self._connection.begin_nested():
                self._connection.execute(
                    insert(task_comments).values(
                        comment_id=comment.comment_id,
                        principal_id=comment.principal_id,
                        task_id=comment.task_id,
                        body=comment.body,
                        author_kind=comment.author_kind.value,
                        author_id=comment.author_id,
                        created_at=comment.created_at,
                        idempotency_key=comment.idempotency_key,
                        request_digest=comment.request_digest,
                    )
                )
        except IntegrityError as error:
            if _constraint_name(error) == "task_comments_idempotency_key_is_unique_per_principal":
                replayed = self.find_comment_by_idempotency_key(
                    comment.principal_id, comment.idempotency_key
                )
                if replayed is not None:
                    return replayed
            raise
        return comment

    def list_comments(
        self,
        principal_id: str,
        task_id: str,
        *,
        after: str | None = None,
        limit: int,
    ) -> tuple[TaskComment, ...]:
        """One bounded page of comments for a Principal-owned Task, oldest first.

        Keyset on `(created_at ASC, comment_id ASC)`. `after` is a comment_id
        that must already belong to this Principal/Task pair; an absent anchor
        is answered as `WorkCursorError`, the same refusal `list_tasks` uses.
        """
        conditions = [
            task_comments.c.principal_id == principal_id,
            task_comments.c.task_id == task_id,
        ]
        if after is not None:
            anchor = self._connection.execute(
                select(*task_comments.c).where(
                    and_(
                        task_comments.c.principal_id == principal_id,
                        task_comments.c.task_id == task_id,
                        task_comments.c.comment_id == after,
                    )
                )
            ).one_or_none()
            if anchor is None:
                raise WorkCursorError
            conditions.append(
                or_(
                    task_comments.c.created_at > anchor.created_at,
                    and_(
                        task_comments.c.created_at == anchor.created_at,
                        task_comments.c.comment_id > anchor.comment_id,
                    ),
                )
            )
        rows = self._connection.execute(
            select(*task_comments.c)
            .where(and_(*conditions))
            .order_by(asc(task_comments.c.created_at), asc(task_comments.c.comment_id))
            .limit(limit)
        ).all()
        return tuple(_to_comment(row) for row in rows)

    def get_follow_up_for_commitment(self, principal_id: str, commitment_id: str) -> Task | None:
        row = self._connection.execute(
            select(*tasks.c)
            .where(
                and_(
                    tasks.c.principal_id == principal_id,
                    tasks.c.commitment_id == commitment_id,
                    tasks.c.role == TaskRole.FOLLOW_UP.value,
                )
            )
            .order_by(desc(tasks.c.created_at), asc(tasks.c.task_id))
            .limit(1)
        ).one_or_none()
        return None if row is None else _to_task(row)


def _acceptance_kind_value(task: Task) -> str:
    """Persist the same three-way pairing `tables.py` CHECKs on `knowledge.tasks`."""

    if task.acceptance_kind is not None:
        return task.acceptance_kind.value
    if task.accepted_by_review_decision_id is not None:
        return ContinuityAcceptanceKind.REVIEW.value
    if task.evidence_state is ContinuityEvidenceState.ACCEPTED:
        return ContinuityAcceptanceKind.DIRECT_PRINCIPAL.value
    return ContinuityAcceptanceKind.NONE.value


def _extend_work_view_conditions(
    conditions: list[ColumnElement[bool]],
    *,
    work_view: TaskWorkView | None,
    work_start: datetime | None,
    work_end: datetime | None,
    work_now: datetime | None,
    effective_at: ColumnElement[Any],
    calendar_at: ColumnElement[Any],
    priority_rank: ColumnElement[Any],
) -> tuple[Any, ...]:
    """Append Work-view predicates shared by `list_tasks` and `search`.

    WP-TUX-01 civil-day buckets use `work_start`/`work_end` only:

    * OVERDUE: `due_at < work_start` (not wall-clock `work_now`);
    * TODAY: due or scheduled inside `[work_start, work_end)`, including due
      times earlier the same civil day than `work_now`;
    * UPCOMING: due or scheduled at/after `work_end`.

    `work_now` remains accepted for call-site compatibility (visual overdue is
    presentation, not a persisted bucket) but is not consulted here.
    """
    del work_now  # presentation-only; bucket membership is civil-day.
    if work_view in {
        TaskWorkView.OVERDUE,
        TaskWorkView.TODAY,
        TaskWorkView.UPCOMING,
        TaskWorkView.RECENTLY_UPDATED,
    }:
        if work_start is None or work_end is None:
            raise ValueError("date-bounded Work views require both UTC boundaries")
        if work_view is TaskWorkView.RECENTLY_UPDATED:
            conditions.extend((tasks.c.updated_at >= work_start, tasks.c.updated_at < work_end))
            return (desc(tasks.c.updated_at), asc(tasks.c.task_id))
        conditions.append(
            tasks.c.lifecycle_state.not_in(
                tuple(state.value for state in TERMINAL_TASK_LIFECYCLE_STATES)
            )
        )
        if work_view is TaskWorkView.OVERDUE:
            conditions.extend((tasks.c.due_at.is_not(None), tasks.c.due_at < work_start))
            return (asc(tasks.c.due_at), asc(priority_rank), asc(tasks.c.task_id))
        if work_view is TaskWorkView.TODAY:
            conditions.append(
                or_(
                    and_(tasks.c.due_at >= work_start, tasks.c.due_at < work_end),
                    and_(
                        tasks.c.scheduled_at >= work_start,
                        tasks.c.scheduled_at < work_end,
                    ),
                )
            )
            return (asc(calendar_at), asc(priority_rank), asc(tasks.c.task_id))
        conditions.append(or_(tasks.c.due_at >= work_end, tasks.c.scheduled_at >= work_end))
        return (asc(calendar_at), asc(priority_rank), asc(tasks.c.task_id))
    if work_view is TaskWorkView.UNSCHEDULED:
        conditions.extend(
            (
                tasks.c.lifecycle_state.not_in(
                    tuple(state.value for state in TERMINAL_TASK_LIFECYCLE_STATES)
                ),
                tasks.c.scheduled_at.is_(None),
            )
        )
        return (
            asc(tasks.c.due_at).nullslast(),
            asc(priority_rank),
            asc(tasks.c.task_id),
        )
    if work_view is TaskWorkView.WAITING:
        conditions.append(tasks.c.lifecycle_state == TaskLifecycleState.WAITING.value)
        return (
            asc(priority_rank),
            asc(effective_at).nullslast(),
            desc(tasks.c.created_at),
            asc(tasks.c.task_id),
        )
    if work_view is TaskWorkView.BLOCKED:
        conditions.append(tasks.c.lifecycle_state == TaskLifecycleState.BLOCKED.value)
        return (
            asc(priority_rank),
            asc(effective_at).nullslast(),
            desc(tasks.c.created_at),
            asc(tasks.c.task_id),
        )
    if work_view is TaskWorkView.ALL_OPEN:
        conditions.append(
            tasks.c.lifecycle_state.in_(("open", "in_progress", "waiting", "blocked"))
        )
        return (
            asc(priority_rank),
            asc(effective_at).nullslast(),
            desc(tasks.c.created_at),
            asc(tasks.c.task_id),
        )
    if work_view is TaskWorkView.COMPLETED:
        conditions.append(tasks.c.lifecycle_state.in_(("completed", "cancelled")))
        return (desc(tasks.c.closed_at), asc(tasks.c.task_id))
    return (desc(tasks.c.created_at), asc(tasks.c.task_id))


def _to_task(row: Row[Any]) -> Task:
    mapping = row._mapping
    raw_origin = mapping.get("origin_kind")
    # Transition safety only: writers must set origin_kind after the WP-TUX-01
    # migration. A legacy evidence row is the only shape that could ever reach
    # here without the column.
    origin_kind = TaskOriginKind.EVIDENCE if raw_origin is None else TaskOriginKind(raw_origin)
    return Task(
        task_id=mapping["task_id"],
        principal_id=mapping["principal_id"],
        title=mapping["title"],
        description=mapping["description"],
        lifecycle_state=TaskLifecycleState(mapping["lifecycle_state"]),
        evidence_state=ContinuityEvidenceState(mapping["evidence_state"]),
        origin_kind=origin_kind,
        origin_evidence_ref=mapping["origin_evidence_ref"],
        opened_at=mapping["opened_at"],
        created_at=mapping["created_at"],
        updated_at=mapping["updated_at"],
        version=mapping["version"],
        priority=None if mapping["priority"] is None else TaskPriority(mapping["priority"]),
        due_at=mapping["due_at"],
        scheduled_at=mapping["scheduled_at"],
        deferred_until=mapping["deferred_until"],
        archived_at=mapping["archived_at"],
        project_id=mapping["project_id"],
        situation_id=mapping["situation_id"],
        recurrence_id=mapping["recurrence_id"],
        closed_at=mapping["closed_at"],
        closure_evidence_ref=mapping["closure_evidence_ref"],
        accepted_by_review_decision_id=mapping["accepted_by_review_decision_id"],
        acceptance_kind=(
            ContinuityAcceptanceKind(mapping["acceptance_kind"])
            if mapping.get("acceptance_kind") is not None
            else None
        ),
        commitment_id=mapping.get("commitment_id"),
        role=None if mapping.get("role") is None else TaskRole(mapping["role"]),
    )


def _to_comment(row: Row[Any]) -> TaskComment:
    mapping = row._mapping
    return TaskComment(
        comment_id=mapping["comment_id"],
        principal_id=mapping["principal_id"],
        task_id=mapping["task_id"],
        body=mapping["body"],
        author_kind=TaskMutationActor(mapping["author_kind"]),
        author_id=mapping["author_id"],
        created_at=mapping["created_at"],
        idempotency_key=mapping["idempotency_key"],
        request_digest=mapping["request_digest"],
    )


class SqlAlchemyTaskManagementUnitOfWork(TaskManagementUnitOfWork):
    """One PostgreSQL transaction over the task-management tables.

    The identical shape `unit_of_work.SqlAlchemyUnitOfWork` establishes: not
    reusable while open and not reentrant, so a composition root hands
    `application.tasks.TaskManagementService` a factory and each mutation
    attempt gets its own transaction — which is the whole of "single database
    transaction per mutation attempt": the version check, the task row write,
    and the history row write all run on the one connection this object opens
    and are committed or rolled back together by `__exit__`.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._context: AbstractContextManager[Connection] | None = None
        self._connection: Connection | None = None

    def __enter__(self) -> TaskManagementUnitOfWork:
        if self._context is not None:
            raise RuntimeError("this unit of work is already inside a transaction")
        context = self._engine.begin()
        self._connection = context.__enter__()
        self._context = context
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        context = self._context
        self._context = None
        self._connection = None
        if context is not None:
            context.__exit__(exc_type, exc, traceback)

    @property
    def tasks(self) -> TaskManagementRepository:
        connection = self._connection
        if connection is None:
            raise RuntimeError("this unit of work is not inside a transaction")
        return SqlTaskManagementRepository(connection)


def _to_history(row: Row[Any]) -> TaskHistoryEntry:
    mapping = row._mapping
    return TaskHistoryEntry(
        history_id=mapping["history_id"],
        principal_id=mapping["principal_id"],
        task_id=mapping["task_id"],
        action=TaskMutationAction(mapping["action"]),
        actor=TaskMutationActor(mapping["actor"]),
        outcome=_TaskMutationOutcome(mapping["outcome"]),
        before_version=mapping["before_version"],
        after_version=mapping["after_version"],
        occurred_at=mapping["occurred_at"],
        recorded_at=mapping["recorded_at"],
        idempotency_key=mapping["idempotency_key"],
        client_context=mapping["client_context"],
        request_digest=mapping.get("request_digest"),
        bulk_operation_id=mapping.get("bulk_operation_id"),
    )


def _to_bulk(row: Row[Any]) -> TaskBulkOperation:
    mapping = row._mapping
    return TaskBulkOperation(
        bulk_operation_id=mapping["bulk_operation_id"],
        principal_id=mapping["principal_id"],
        preview_idempotency_key=mapping["preview_idempotency_key"],
        request_digest=mapping["request_digest"],
        previewed_at=mapping["previewed_at"],
        expires_at=mapping["expires_at"],
        preview_affected=mapping["preview_affected"],
        preview_no_op=mapping["preview_no_op"],
        confirmed_at=mapping["confirmed_at"],
        confirm_idempotency_key=mapping["confirm_idempotency_key"],
        affected=mapping["affected"],
        no_op=mapping["no_op"],
        rejected=mapping["rejected"],
        history_ids=tuple(mapping["history_ids"] or ()),
    )
