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
from types import TracebackType
from typing import Any

from sqlalchemy import Engine, and_, asc, desc, insert, select, update
from sqlalchemy.engine import Connection, Row

from my_pa.contracts.ports import TaskManagementRepository, TaskManagementUnitOfWork
from my_pa.domain.situation.continuity import ContinuityAcceptanceKind, ContinuityEvidenceState
from my_pa.domain.task.history import TaskHistoryEntry, TaskMutationAction, TaskMutationActor
from my_pa.domain.task.history import TaskMutationOutcome as _TaskMutationOutcome
from my_pa.domain.task.lifecycle import TaskLifecycleState, TaskPriority, legacy_state_for
from my_pa.domain.task.task import Task
from my_pa.infrastructure.persistence.tables import task_history, tasks

__all__ = ["SqlAlchemyTaskManagementUnitOfWork", "SqlTaskManagementRepository"]


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
        include_archived: bool = False,
        limit: int,
    ) -> tuple[Task, ...]:
        conditions = [tasks.c.principal_id == principal_id]
        if lifecycle_state is not None:
            conditions.append(tasks.c.lifecycle_state == lifecycle_state.value)
        if priority is not None:
            conditions.append(tasks.c.priority == priority.value)
        if not include_archived:
            conditions.append(tasks.c.archived_at.is_(None))
        rows = self._connection.execute(
            select(*tasks.c)
            .where(and_(*conditions))
            .order_by(desc(tasks.c.created_at), asc(tasks.c.task_id))
            .limit(limit)
        ).all()
        return tuple(_to_task(row) for row in rows)

    def search(self, principal_id: str, query: str, limit: int) -> tuple[Task, ...]:
        # `_` and `%` are `ILIKE` wildcards; a query containing either as a
        # literal character (a task titled "50% done", say) is escaped so the
        # match stays lexical rather than accidentally becoming a wildcard the
        # caller never asked for. `\` is escaped first so the two escapes just
        # inserted are not themselves re-escaped.
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        rows = self._connection.execute(
            select(*tasks.c)
            .where(
                and_(
                    tasks.c.principal_id == principal_id,
                    tasks.c.title.ilike(pattern, escape="\\"),
                )
            )
            .order_by(desc(tasks.c.created_at), asc(tasks.c.task_id))
            .limit(limit)
        ).all()
        return tuple(_to_task(row) for row in rows)

    def list_history(
        self, principal_id: str, task_id: str, limit: int
    ) -> tuple[TaskHistoryEntry, ...]:
        rows = self._connection.execute(
            select(*task_history.c)
            .where(
                and_(
                    task_history.c.principal_id == principal_id,
                    task_history.c.task_id == task_id,
                )
            )
            .order_by(asc(task_history.c.recorded_at), asc(task_history.c.history_id))
            .limit(limit)
        ).all()
        return tuple(_to_history(row) for row in rows)

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
                occurred_at=entry.occurred_at,
                recorded_at=entry.recorded_at,
            )
        )


def _acceptance_kind_value(task: Task) -> str:
    """Persist the same three-way pairing `tables.py` CHECKs on `knowledge.tasks`."""

    if task.acceptance_kind is not None:
        return task.acceptance_kind.value
    if task.accepted_by_review_decision_id is not None:
        return ContinuityAcceptanceKind.REVIEW.value
    if task.evidence_state is ContinuityEvidenceState.ACCEPTED:
        return ContinuityAcceptanceKind.DIRECT_PRINCIPAL.value
    return ContinuityAcceptanceKind.NONE.value


def _to_task(row: Row[Any]) -> Task:
    mapping = row._mapping
    return Task(
        task_id=mapping["task_id"],
        principal_id=mapping["principal_id"],
        title=mapping["title"],
        description=mapping["description"],
        lifecycle_state=TaskLifecycleState(mapping["lifecycle_state"]),
        evidence_state=ContinuityEvidenceState(mapping["evidence_state"]),
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
    )
