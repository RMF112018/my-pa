"""Principal-partitioned Task and Commitment persistence."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.engine import Connection

from my_pa.contracts.ports import TaskIdempotencyRecord, TaskPreviewRecord, TaskRepository
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.tasks.models import (
    AcceptanceKind,
    Commitment,
    CommitmentDirection,
    CommitmentState,
    ContextLinkKind,
    ContinuityEvidenceState,
    RecurrenceFrequency,
    RecurrenceRule,
    Task,
    TaskContextLink,
    TaskOrigin,
    TaskPriority,
    TaskRevision,
    TaskRole,
    TaskState,
    Weekday,
)
from my_pa.infrastructure.persistence.tables import (
    commitments,
    task_bulk_previews,
    task_context_links,
    task_idempotency,
    task_recurrences,
    task_revisions,
    tasks,
)

__all__ = [
    "SqlAlchemyTaskRepository",
    "persist_reviewed_task",
]


def persist_reviewed_task(
    connection: Connection,
    *,
    principal_id: str,
    title: str,
    review_decision_id: str,
    origin_evidence_ref: str,
    at: datetime,
) -> Task:
    store = SqlAlchemyTaskRepository(connection)
    existing = store.tasks_with_title(principal_id, title)
    for task in existing:
        if (
            task.accepted_by_review_decision_id == review_decision_id
            or task.origin_evidence_ref == origin_evidence_ref
        ):
            return task
    task = Task(
        task_id=issue_identifier(IdKind.TASK),
        principal_id=principal_id,
        title=title,
        state=TaskState.OPEN,
        task_role=TaskRole.ACTION,
        priority=TaskPriority.P3,
        evidence_state=ContinuityEvidenceState.ACCEPTED,
        acceptance_kind=AcceptanceKind.REVIEW,
        accepted_by_review_decision_id=review_decision_id,
        origin_evidence_ref=origin_evidence_ref,
        current_version=1,
        opened_at=at,
        created_at=at,
        updated_at=at,
    )
    store.insert_task(task)
    store.append_revision(
        TaskRevision(
            revision_id=issue_identifier(IdKind.TASK_REVISION),
            task_id=task.task_id,
            principal_id=principal_id,
            version=1,
            origin=TaskOrigin.REVIEW_PROMOTION,
            state=task.state,
            priority=task.priority,
            recorded_at=at,
            title=task.title,
        )
    )
    return task


class _MappedTaskRow(Protocol):
    task_id: str
    principal_id: str
    title: str
    description: str | None
    state: str
    task_role: str
    priority: str
    evidence_state: str
    acceptance_kind: str
    accepted_by_review_decision_id: str | None
    origin_evidence_ref: str | None
    due_date: date | None
    due_at: datetime | None
    due_timezone: str | None
    scheduled_date: date | None
    scheduled_at: datetime | None
    deferred_until: datetime | None
    archived_at: datetime | None
    current_version: int
    recurrence_id: str | None
    occurrence_key: str | None
    project_id: str | None
    situation_id: str | None
    person_id: str | None
    opened_at: datetime
    closed_at: datetime | None
    closure_evidence_ref: str | None
    created_at: datetime
    updated_at: datetime


class _MappedCommitmentRow(Protocol):
    commitment_id: str
    principal_id: str
    counterparty_person_id: str
    direction: str
    summary: str
    state: str
    evidence_state: str
    origin_evidence_ref: str | None
    due_date: date | None
    due_at: datetime | None
    due_timezone: str | None
    current_version: int
    opened_at: datetime
    closed_at: datetime | None
    closure_evidence_ref: str | None
    created_at: datetime
    updated_at: datetime


def _task_from_row(row: _MappedTaskRow) -> Task:
    return Task(
        task_id=row.task_id,
        principal_id=row.principal_id,
        title=row.title,
        description=row.description,
        state=TaskState(row.state),
        task_role=TaskRole(row.task_role),
        priority=TaskPriority(row.priority),
        evidence_state=ContinuityEvidenceState(row.evidence_state),
        acceptance_kind=AcceptanceKind(row.acceptance_kind),
        accepted_by_review_decision_id=row.accepted_by_review_decision_id,
        origin_evidence_ref=row.origin_evidence_ref,
        due_date=row.due_date,
        due_at=row.due_at,
        due_timezone=row.due_timezone,
        scheduled_date=row.scheduled_date,
        scheduled_at=row.scheduled_at,
        deferred_until=row.deferred_until,
        archived_at=row.archived_at,
        current_version=int(row.current_version),
        recurrence_id=row.recurrence_id,
        occurrence_key=row.occurrence_key,
        project_id=row.project_id,
        situation_id=row.situation_id,
        person_id=row.person_id,
        opened_at=row.opened_at,
        closed_at=row.closed_at,
        closure_evidence_ref=row.closure_evidence_ref,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _commitment_from_row(row: _MappedCommitmentRow) -> Commitment:
    return Commitment(
        commitment_id=row.commitment_id,
        principal_id=row.principal_id,
        counterparty_person_id=row.counterparty_person_id,
        direction=CommitmentDirection(row.direction),
        summary=row.summary,
        state=CommitmentState(row.state),
        evidence_state=ContinuityEvidenceState(row.evidence_state),
        origin_evidence_ref=row.origin_evidence_ref,
        due_date=row.due_date,
        due_at=row.due_at,
        due_timezone=row.due_timezone,
        current_version=int(row.current_version),
        opened_at=row.opened_at,
        closed_at=row.closed_at,
        closure_evidence_ref=row.closure_evidence_ref,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _task_values(task: Task) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "principal_id": task.principal_id,
        "title": task.title,
        "description": task.description,
        "state": task.state.value,
        "task_role": task.task_role.value,
        "priority": task.priority.value,
        "evidence_state": task.evidence_state.value,
        "acceptance_kind": task.acceptance_kind.value,
        "accepted_by_review_decision_id": task.accepted_by_review_decision_id,
        "origin_evidence_ref": task.origin_evidence_ref,
        "due_date": task.due_date,
        "due_at": task.due_at,
        "due_timezone": task.due_timezone,
        "scheduled_date": task.scheduled_date,
        "scheduled_at": task.scheduled_at,
        "deferred_until": task.deferred_until,
        "archived_at": task.archived_at,
        "current_version": task.current_version,
        "recurrence_id": task.recurrence_id,
        "occurrence_key": task.occurrence_key,
        "project_id": task.project_id,
        "situation_id": task.situation_id,
        "person_id": task.person_id,
        "opened_at": task.opened_at,
        "closed_at": task.closed_at,
        "closure_evidence_ref": task.closure_evidence_ref,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


class SqlAlchemyTaskRepository(TaskRepository):
    """Task store bound to one open connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get_task(self, principal_id: str, task_id: str) -> Task | None:
        row = self._connection.execute(
            select(tasks).where(tasks.c.principal_id == principal_id, tasks.c.task_id == task_id)
        ).one_or_none()
        return None if row is None else _task_from_row(row)

    def list_tasks(
        self,
        principal_id: str,
        *,
        state: TaskState | None,
        task_role: TaskRole | None,
        include_archived: bool,
        limit: int,
    ) -> tuple[Task, ...]:
        query = select(tasks).where(tasks.c.principal_id == principal_id)
        if state is not None:
            query = query.where(tasks.c.state == state.value)
        if task_role is not None:
            query = query.where(tasks.c.task_role == task_role.value)
        if not include_archived:
            query = query.where(tasks.c.archived_at.is_(None))
        query = query.order_by(tasks.c.updated_at.desc()).limit(limit)
        return tuple(_task_from_row(row) for row in self._connection.execute(query))

    def search_tasks(self, principal_id: str, query: str, *, limit: int) -> tuple[Task, ...]:
        pattern = f"%{query}%"
        statement = (
            select(tasks)
            .where(
                tasks.c.principal_id == principal_id,
                tasks.c.title.ilike(pattern) | tasks.c.description.ilike(pattern),
            )
            .order_by(tasks.c.updated_at.desc())
            .limit(limit)
        )
        return tuple(_task_from_row(row) for row in self._connection.execute(statement))

    def tasks_with_title(self, principal_id: str, title: str) -> tuple[Task, ...]:
        statement = select(tasks).where(
            tasks.c.principal_id == principal_id, tasks.c.title == title
        )
        return tuple(_task_from_row(row) for row in self._connection.execute(statement))

    def insert_task(self, task: Task) -> None:
        self._connection.execute(tasks.insert().values(**_task_values(task)))

    def save_task(self, task: Task, *, expected_version: int) -> bool:
        result = self._connection.execute(
            tasks.update()
            .where(
                tasks.c.principal_id == task.principal_id,
                tasks.c.task_id == task.task_id,
                tasks.c.current_version == expected_version,
            )
            .values(**{key: value for key, value in _task_values(task).items() if key != "task_id"})
        )
        return result.rowcount == 1

    def append_revision(self, revision: TaskRevision) -> None:
        self._connection.execute(
            task_revisions.insert().values(
                revision_id=revision.revision_id,
                task_id=revision.task_id,
                principal_id=revision.principal_id,
                version=revision.version,
                origin=revision.origin.value,
                state=revision.state.value,
                priority=revision.priority.value,
                title=revision.title,
                prior_revision_id=revision.prior_revision_id,
                recorded_at=revision.recorded_at,
            )
        )

    def history(self, principal_id: str, task_id: str) -> tuple[TaskRevision, ...]:
        rows = self._connection.execute(
            select(task_revisions)
            .where(
                task_revisions.c.principal_id == principal_id,
                task_revisions.c.task_id == task_id,
            )
            .order_by(task_revisions.c.version)
        )
        return tuple(
            TaskRevision(
                revision_id=row.revision_id,
                task_id=row.task_id,
                principal_id=row.principal_id,
                version=int(row.version),
                origin=TaskOrigin(row.origin),
                state=TaskState(row.state),
                priority=TaskPriority(row.priority),
                title=row.title,
                prior_revision_id=row.prior_revision_id,
                recorded_at=row.recorded_at,
            )
            for row in rows
        )

    def insert_recurrence(self, rule: RecurrenceRule) -> None:
        self._connection.execute(
            task_recurrences.insert().values(
                recurrence_id=rule.recurrence_id,
                principal_id=rule.principal_id,
                frequency=rule.frequency.value,
                timezone=rule.timezone,
                interval=rule.interval,
                weekdays=sorted(int(day) for day in rule.weekdays),
                start_date=rule.start_date,
                start_at=rule.start_at,
                series_title=rule.series_title,
            )
        )

    def get_recurrence(self, principal_id: str, recurrence_id: str) -> RecurrenceRule | None:
        row = self._connection.execute(
            select(task_recurrences).where(
                task_recurrences.c.principal_id == principal_id,
                task_recurrences.c.recurrence_id == recurrence_id,
            )
        ).one_or_none()
        if row is None:
            return None
        return RecurrenceRule(
            recurrence_id=row.recurrence_id,
            principal_id=row.principal_id,
            frequency=RecurrenceFrequency(row.frequency),
            timezone=row.timezone,
            interval=int(row.interval),
            weekdays=frozenset(Weekday(int(day)) for day in (row.weekdays or ())),
            start_date=row.start_date,
            start_at=row.start_at,
            series_title=row.series_title,
        )

    def actionable_occurrence(self, principal_id: str, recurrence_id: str) -> Task | None:
        row = self._connection.execute(
            select(tasks).where(
                tasks.c.principal_id == principal_id,
                tasks.c.recurrence_id == recurrence_id,
                tasks.c.state.notin_((TaskState.COMPLETED.value, TaskState.CANCELLED.value)),
            )
        ).one_or_none()
        return None if row is None else _task_from_row(row)

    def occurrence(self, principal_id: str, recurrence_id: str, occurrence_key: str) -> Task | None:
        row = self._connection.execute(
            select(tasks).where(
                tasks.c.principal_id == principal_id,
                tasks.c.recurrence_id == recurrence_id,
                tasks.c.occurrence_key == occurrence_key,
            )
        ).one_or_none()
        return None if row is None else _task_from_row(row)

    def insert_commitment(self, commitment: Commitment) -> None:
        self._connection.execute(
            commitments.insert().values(
                commitment_id=commitment.commitment_id,
                principal_id=commitment.principal_id,
                counterparty_person_id=commitment.counterparty_person_id,
                direction=commitment.direction.value,
                summary=commitment.summary,
                state=commitment.state.value,
                evidence_state=commitment.evidence_state.value,
                origin_evidence_ref=commitment.origin_evidence_ref,
                due_date=commitment.due_date,
                due_at=commitment.due_at,
                due_timezone=commitment.due_timezone,
                current_version=commitment.current_version,
                opened_at=commitment.opened_at,
                closed_at=commitment.closed_at,
                closure_evidence_ref=commitment.closure_evidence_ref,
                created_at=commitment.created_at,
                updated_at=commitment.updated_at,
            )
        )

    def get_commitment(self, principal_id: str, commitment_id: str) -> Commitment | None:
        row = self._connection.execute(
            select(commitments).where(
                commitments.c.principal_id == principal_id,
                commitments.c.commitment_id == commitment_id,
            )
        ).one_or_none()
        return None if row is None else _commitment_from_row(row)

    def save_commitment(self, commitment: Commitment, *, expected_version: int) -> bool:
        result = self._connection.execute(
            commitments.update()
            .where(
                commitments.c.principal_id == commitment.principal_id,
                commitments.c.commitment_id == commitment.commitment_id,
                commitments.c.current_version == expected_version,
            )
            .values(
                state=commitment.state.value,
                closed_at=commitment.closed_at,
                closure_evidence_ref=commitment.closure_evidence_ref,
                current_version=commitment.current_version,
                updated_at=commitment.updated_at,
            )
        )
        return result.rowcount == 1

    def list_commitments(
        self,
        principal_id: str,
        *,
        direction: CommitmentDirection | None,
        limit: int,
    ) -> tuple[Commitment, ...]:
        query = select(commitments).where(commitments.c.principal_id == principal_id)
        if direction is not None:
            query = query.where(commitments.c.direction == direction.value)
        query = query.order_by(commitments.c.updated_at.desc()).limit(limit)
        return tuple(_commitment_from_row(row) for row in self._connection.execute(query))

    def insert_link(self, link: TaskContextLink) -> None:
        self._connection.execute(
            task_context_links.insert().values(
                link_id=link.link_id,
                task_id=link.task_id,
                principal_id=link.principal_id,
                kind=link.kind.value,
                target_id=link.target_id,
            )
        )

    def links_for(self, principal_id: str, task_id: str) -> tuple[TaskContextLink, ...]:
        rows = self._connection.execute(
            select(task_context_links).where(
                task_context_links.c.principal_id == principal_id,
                task_context_links.c.task_id == task_id,
            )
        )
        return tuple(
            TaskContextLink(
                link_id=row.link_id,
                task_id=row.task_id,
                principal_id=row.principal_id,
                kind=ContextLinkKind(row.kind),
                target_id=row.target_id,
            )
            for row in rows
        )

    def get_idempotency(self, principal_id: str, key: str) -> TaskIdempotencyRecord | None:
        row = self._connection.execute(
            select(task_idempotency).where(
                task_idempotency.c.principal_id == principal_id,
                task_idempotency.c.idempotency_key == key,
            )
        ).one_or_none()
        if row is None:
            return None
        return TaskIdempotencyRecord(
            request_hash=row.request_hash, result=json.loads(row.result_json)
        )

    def put_idempotency(
        self, principal_id: str, key: str, request_hash: str, result: dict[str, object]
    ) -> None:
        self._connection.execute(
            task_idempotency.insert().values(
                principal_id=principal_id,
                idempotency_key=key,
                request_hash=request_hash,
                result_json=json.dumps(result, default=str),
            )
        )

    def insert_preview(self, preview: TaskPreviewRecord) -> None:
        self._connection.execute(
            task_bulk_previews.insert().values(
                preview_id=preview.preview_id,
                principal_id=preview.principal_id,
                operation=preview.operation,
                operation_hash=preview.operation_hash,
                targets_json=json.dumps(
                    {
                        "targets": [list(item) for item in preview.targets],
                        "scheduled_date": (
                            None
                            if preview.scheduled_date is None
                            else preview.scheduled_date.isoformat()
                        ),
                        "scheduled_at": (
                            None
                            if preview.scheduled_at is None
                            else preview.scheduled_at.isoformat()
                        ),
                        "due_date": (
                            None if preview.due_date is None else preview.due_date.isoformat()
                        ),
                        "due_at": None if preview.due_at is None else preview.due_at.isoformat(),
                        "due_timezone": preview.due_timezone,
                        "target_state": (
                            None if preview.target_state is None else preview.target_state.value
                        ),
                    }
                ),
            )
        )

    def get_preview(self, principal_id: str, preview_id: str) -> TaskPreviewRecord | None:
        row = self._connection.execute(
            select(task_bulk_previews).where(
                task_bulk_previews.c.principal_id == principal_id,
                task_bulk_previews.c.preview_id == preview_id,
            )
        ).one_or_none()
        if row is None:
            return None
        payload = json.loads(row.targets_json)
        return TaskPreviewRecord(
            preview_id=row.preview_id,
            principal_id=row.principal_id,
            operation=row.operation,
            operation_hash=row.operation_hash,
            targets=tuple((item[0], int(item[1])) for item in payload["targets"]),
            scheduled_date=(
                None
                if payload.get("scheduled_date") is None
                else date.fromisoformat(payload["scheduled_date"])
            ),
            scheduled_at=(
                None
                if payload.get("scheduled_at") is None
                else datetime.fromisoformat(payload["scheduled_at"])
            ),
            due_date=(
                None if payload.get("due_date") is None else date.fromisoformat(payload["due_date"])
            ),
            due_at=(
                None if payload.get("due_at") is None else datetime.fromisoformat(payload["due_at"])
            ),
            due_timezone=payload.get("due_timezone"),
            target_state=(
                None if payload.get("target_state") is None else TaskState(payload["target_state"])
            ),
        )
