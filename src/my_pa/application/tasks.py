"""Task and Commitment use cases. Called only from ApplicationService handlers."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime
from hashlib import sha256
from typing import Any

from my_pa.application.commands import (
    ApplyTaskBulk,
    CreateCommitment,
    CreateTask,
    ListCommitments,
    ListTasks,
    PreviewTaskBulk,
    ReadTask,
    ReadTaskHistory,
    SearchTasks,
    TasksAttention,
    TransitionTask,
    UpdateTask,
)
from my_pa.application.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.contracts.ports import TaskPreviewRecord, TaskRepository
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import format_rfc3339
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.tasks.attention import rank_attention
from my_pa.domain.tasks.models import (
    AcceptanceKind,
    Commitment,
    CommitmentDirection,
    CommitmentState,
    ContinuityEvidenceState,
    RecurrenceFrequency,
    RecurrenceRule,
    Task,
    TaskContextLink,
    TaskError,
    TaskOrigin,
    TaskPriority,
    TaskRevision,
    TaskRole,
    TaskState,
    Weekday,
    can_transition,
    next_occurrence,
    normalize_priority,
    occurrence_key_for,
)
from my_pa.domain.tasks.resolution import ResolutionOutcome, resolve_task_reference

__all__ = [
    "apply_bulk",
    "attention",
    "create_commitment",
    "create_task",
    "history",
    "list_commitments",
    "list_tasks",
    "preview_bulk",
    "promote_reviewed_task",
    "read_task",
    "search_tasks",
    "transition_task",
    "update_task",
    "waiting_on",
]


def _hash(document: dict[str, Any]) -> str:
    encoded = json.dumps(document, sort_keys=True, default=str, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _replay_or_conflict(
    store: TaskRepository, principal_id: str, key: str, request_hash: str
) -> dict[str, Any] | None:
    existing = store.get_idempotency(principal_id, key)
    if existing is None:
        return None
    if existing.request_hash != request_hash:
        raise ConflictError(SafeDetail.IDEMPOTENCY_KEY)
    return dict(existing.result)


def _task_view(task: Task) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "title": task.title,
        "description": task.description,
        "state": task.state.value,
        "task_role": task.task_role.value,
        "priority": task.priority.value,
        "evidence_state": task.evidence_state.value,
        "acceptance_kind": task.acceptance_kind.value,
        "accepted_by_review_decision_id": task.accepted_by_review_decision_id,
        "origin_evidence_ref": task.origin_evidence_ref,
        "due_date": None if task.due_date is None else task.due_date.isoformat(),
        "due_at": None if task.due_at is None else format_rfc3339(task.due_at),
        "due_timezone": task.due_timezone,
        "scheduled_date": None if task.scheduled_date is None else task.scheduled_date.isoformat(),
        "scheduled_at": None if task.scheduled_at is None else format_rfc3339(task.scheduled_at),
        "deferred_until": (
            None if task.deferred_until is None else format_rfc3339(task.deferred_until)
        ),
        "archived_at": None if task.archived_at is None else format_rfc3339(task.archived_at),
        "current_version": task.current_version,
        "recurrence_id": task.recurrence_id,
        "occurrence_key": task.occurrence_key,
        "project_id": task.project_id,
        "situation_id": task.situation_id,
        "person_id": task.person_id,
        "opened_at": format_rfc3339(task.opened_at),
        "closed_at": None if task.closed_at is None else format_rfc3339(task.closed_at),
    }


def _commitment_view(commitment: Commitment) -> dict[str, Any]:
    return {
        "commitment_id": commitment.commitment_id,
        "counterparty_person_id": commitment.counterparty_person_id,
        "direction": commitment.direction.value,
        "summary": commitment.summary,
        "state": commitment.state.value,
        "evidence_state": commitment.evidence_state.value,
        "due_date": None if commitment.due_date is None else commitment.due_date.isoformat(),
        "due_at": None if commitment.due_at is None else format_rfc3339(commitment.due_at),
        "due_timezone": commitment.due_timezone,
        "current_version": commitment.current_version,
        "opened_at": format_rfc3339(commitment.opened_at),
        "closed_at": None if commitment.closed_at is None else format_rfc3339(commitment.closed_at),
        "origin_evidence_ref": commitment.origin_evidence_ref,
    }


def _revision_for(task: Task, *, origin: TaskOrigin, prior: str | None) -> TaskRevision:
    return TaskRevision(
        revision_id=issue_identifier(IdKind.TASK_REVISION),
        task_id=task.task_id,
        principal_id=task.principal_id,
        version=task.current_version,
        origin=origin,
        state=task.state,
        priority=task.priority,
        recorded_at=task.updated_at,
        title=task.title,
        prior_revision_id=prior,
    )


def _remember(
    store: TaskRepository,
    principal_id: str,
    key: str,
    request_hash: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    store.put_idempotency(principal_id, key, request_hash, result)
    return result


def _weekdays(values: tuple[int, ...], frequency: RecurrenceFrequency) -> frozenset[Weekday]:
    if frequency is RecurrenceFrequency.WEEKLY and not values:
        return frozenset({Weekday.FRIDAY})
    return frozenset(Weekday(value) for value in values)


def create_task(
    store: TaskRepository,
    *,
    principal_id: str,
    command: CreateTask,
    at: datetime,
) -> dict[str, Any]:
    request = {
        "title": command.title,
        "description": command.description,
        "priority": command.priority,
        "task_role": command.task_role.value,
        "due_date": None if command.due_date is None else command.due_date.isoformat(),
        "due_at": None if command.due_at is None else format_rfc3339(command.due_at),
        "due_timezone": command.due_timezone,
        "scheduled_date": (
            None if command.scheduled_date is None else command.scheduled_date.isoformat()
        ),
        "scheduled_at": (
            None if command.scheduled_at is None else format_rfc3339(command.scheduled_at)
        ),
        "deferred_until": (
            None if command.deferred_until is None else format_rfc3339(command.deferred_until)
        ),
        "person_id": command.person_id,
        "project_id": command.project_id,
        "situation_id": command.situation_id,
        "origin_evidence_ref": command.origin_evidence_ref,
        "proposed": command.proposed,
        "recurrence_frequency": (
            None if command.recurrence_frequency is None else command.recurrence_frequency.value
        ),
        "recurrence_weekdays": list(command.recurrence_weekdays),
    }
    digest = _hash(request)
    replayed = _replay_or_conflict(store, principal_id, command.idempotency_key, digest)
    if replayed is not None:
        return replayed
    try:
        priority = normalize_priority(command.priority)
    except TaskError:
        raise InvalidRequestError(SafeDetail.PRIORITY) from None
    recurrence_id = None
    occurrence_key = None
    due_date = command.due_date
    due_at = command.due_at
    scheduled_date = command.scheduled_date
    scheduled_at = command.scheduled_at
    if command.recurrence_frequency is not None:
        recurrence_id = issue_identifier(IdKind.TASK_RECURRENCE)
        try:
            rule = RecurrenceRule(
                recurrence_id=recurrence_id,
                principal_id=principal_id,
                frequency=command.recurrence_frequency,
                timezone=command.due_timezone or "UTC",
                weekdays=_weekdays(command.recurrence_weekdays, command.recurrence_frequency),
                start_at=command.due_at or command.scheduled_at,
                start_date=(
                    None
                    if (command.due_at or command.scheduled_at) is not None
                    else (command.due_date or command.scheduled_date or at.date())
                ),
                series_title=command.title,
            )
        except TaskError:
            raise InvalidRequestError(SafeDetail.RECURRENCE) from None
        store.insert_recurrence(rule)
        first = next_occurrence(rule)
        occurrence_key = occurrence_key_for(first, rule.timezone)
        if isinstance(first, datetime):
            due_at = first
            due_date = None
        else:
            due_date = first
            due_at = None
    try:
        task = Task(
            task_id=issue_identifier(IdKind.TASK),
            principal_id=principal_id,
            title=command.title,
            description=command.description,
            state=TaskState.OPEN,
            task_role=command.task_role,
            priority=priority,
            evidence_state=(
                ContinuityEvidenceState.PROPOSED
                if command.proposed
                else ContinuityEvidenceState.ACCEPTED
            ),
            acceptance_kind=(
                AcceptanceKind.NONE if command.proposed else AcceptanceKind.DIRECT_PRINCIPAL
            ),
            current_version=1,
            opened_at=at,
            created_at=at,
            updated_at=at,
            due_date=due_date,
            due_at=due_at,
            due_timezone=command.due_timezone,
            scheduled_date=scheduled_date,
            scheduled_at=scheduled_at,
            deferred_until=command.deferred_until,
            person_id=command.person_id,
            project_id=command.project_id,
            situation_id=command.situation_id,
            origin_evidence_ref=command.origin_evidence_ref,
            recurrence_id=recurrence_id,
            occurrence_key=occurrence_key,
        )
    except TaskError:
        raise InvalidRequestError(SafeDetail.TITLE) from None
    store.insert_task(task)
    store.append_revision(_revision_for(task, origin=TaskOrigin.PRINCIPAL_DIRECT, prior=None))
    result = {
        "status": "ok",
        "task": _task_view(task),
        "version_before": 0,
        "version_after": 1,
        "acceptance_kind": (
            AcceptanceKind.NONE.value if command.proposed else AcceptanceKind.DIRECT_PRINCIPAL.value
        ),
    }
    return _remember(store, principal_id, command.idempotency_key, digest, result)


def _resolve(
    store: TaskRepository, principal_id: str, command: UpdateTask | TransitionTask
) -> Task:
    resolved = resolve_task_reference(
        explicit_task_id=command.task_id,
        referenced_task_id=command.referenced_task_id,
        known=(),
    )
    if resolved.outcome is ResolutionOutcome.EXACT and resolved.task_id is not None:
        task = store.get_task(principal_id, resolved.task_id)
        if task is None:
            raise NotFoundError(SafeDetail.TASK_ID)
        return task
    raise NotFoundError(SafeDetail.TASK_ID)


def update_task(
    store: TaskRepository,
    *,
    principal_id: str,
    command: UpdateTask,
    at: datetime,
) -> dict[str, Any]:
    digest = _hash(
        {
            "task_id": command.task_id,
            "referenced_task_id": command.referenced_task_id,
            "expected_version": command.expected_version,
            "title": command.title,
            "description": command.description,
            "priority": command.priority,
            "due_date": None if command.due_date is None else command.due_date.isoformat(),
            "due_at": None if command.due_at is None else format_rfc3339(command.due_at),
            "scheduled_date": (
                None if command.scheduled_date is None else command.scheduled_date.isoformat()
            ),
            "scheduled_at": (
                None if command.scheduled_at is None else format_rfc3339(command.scheduled_at)
            ),
            "deferred_until": (
                None if command.deferred_until is None else format_rfc3339(command.deferred_until)
            ),
            "clear_deferred": command.clear_deferred,
            "archived": command.archived,
            "accept": command.accept,
        }
    )
    replayed = _replay_or_conflict(store, principal_id, command.idempotency_key, digest)
    if replayed is not None:
        return replayed
    task = _resolve(store, principal_id, command)
    if task.current_version != command.expected_version:
        raise ConflictError(SafeDetail.EXPECTED_VERSION)
    if command.accept and task.evidence_state is not ContinuityEvidenceState.PROPOSED:
        raise InvalidRequestError(SafeDetail.STATE)
    try:
        priority = (
            task.priority if command.priority is None else normalize_priority(command.priority)
        )
    except TaskError:
        raise InvalidRequestError(SafeDetail.PRIORITY) from None
    updated = Task(
        task_id=task.task_id,
        principal_id=task.principal_id,
        title=task.title if command.title is None else command.title,
        description=task.description if command.description is None else command.description,
        state=task.state,
        task_role=task.task_role if command.task_role is None else command.task_role,
        priority=priority,
        evidence_state=(
            ContinuityEvidenceState.ACCEPTED if command.accept else task.evidence_state
        ),
        acceptance_kind=(
            AcceptanceKind.DIRECT_PRINCIPAL if command.accept else task.acceptance_kind
        ),
        accepted_by_review_decision_id=task.accepted_by_review_decision_id,
        origin_evidence_ref=task.origin_evidence_ref,
        due_date=(
            task.due_date
            if command.due_date is None and command.due_at is None
            else command.due_date
        ),
        due_at=(
            task.due_at if command.due_at is None and command.due_date is None else command.due_at
        ),
        due_timezone=task.due_timezone if command.due_timezone is None else command.due_timezone,
        scheduled_date=(
            task.scheduled_date
            if command.scheduled_date is None and command.scheduled_at is None
            else command.scheduled_date
        ),
        scheduled_at=(
            task.scheduled_at
            if command.scheduled_at is None and command.scheduled_date is None
            else command.scheduled_at
        ),
        deferred_until=(
            None
            if command.clear_deferred
            else (task.deferred_until if command.deferred_until is None else command.deferred_until)
        ),
        archived_at=(
            at
            if command.archived is True
            else (None if command.archived is False else task.archived_at)
        ),
        current_version=task.current_version + 1,
        recurrence_id=task.recurrence_id,
        occurrence_key=task.occurrence_key,
        project_id=task.project_id,
        situation_id=task.situation_id,
        person_id=task.person_id if command.person_id is None else command.person_id,
        opened_at=task.opened_at,
        closed_at=task.closed_at,
        closure_evidence_ref=task.closure_evidence_ref,
        created_at=task.created_at,
        updated_at=at,
    )
    if not store.save_task(updated, expected_version=command.expected_version):
        raise ConflictError(SafeDetail.EXPECTED_VERSION)
    prior = store.history(principal_id, task.task_id)
    prior_id = prior[-1].revision_id if prior else None
    store.append_revision(
        _revision_for(updated, origin=TaskOrigin.PRINCIPAL_DIRECT, prior=prior_id)
    )
    result = {
        "status": "ok",
        "task": _task_view(updated),
        "version_before": command.expected_version,
        "version_after": updated.current_version,
    }
    return _remember(store, principal_id, command.idempotency_key, digest, result)


def _mark_series_cancelled(store: TaskRepository, task: Task, *, at: datetime) -> None:
    if task.recurrence_id is None:
        return
    rule = store.get_recurrence(task.principal_id, task.recurrence_id)
    if rule is None or rule.cancelled_at is not None:
        return
    store.save_recurrence(replace(rule, cancelled_at=at))


def _spawn_next_occurrence(store: TaskRepository, task: Task, *, at: datetime) -> None:
    if task.recurrence_id is None:
        return
    rule = store.get_recurrence(task.principal_id, task.recurrence_id)
    if rule is None or rule.cancelled_at is not None:
        return
    after: date | datetime
    if task.due_at is not None:
        after = task.due_at
    elif task.due_date is not None:
        after = task.due_date
    elif task.occurrence_key is not None:
        after = date.fromisoformat(task.occurrence_key)
    else:
        after = at
    nxt = next_occurrence(rule, after=after)
    key = occurrence_key_for(nxt, rule.timezone)
    if store.occurrence(task.principal_id, task.recurrence_id, key) is not None:
        return
    if store.actionable_occurrence(task.principal_id, task.recurrence_id) is not None:
        return
    if isinstance(nxt, datetime):
        due_at = nxt
        due_date = None
    else:
        due_date = nxt
        due_at = None
    spawned = Task(
        task_id=issue_identifier(IdKind.TASK),
        principal_id=task.principal_id,
        title=task.title,
        description=task.description,
        state=TaskState.OPEN,
        task_role=task.task_role,
        priority=task.priority,
        evidence_state=ContinuityEvidenceState.ACCEPTED,
        acceptance_kind=AcceptanceKind.DIRECT_PRINCIPAL,
        current_version=1,
        opened_at=at,
        created_at=at,
        updated_at=at,
        due_date=due_date,
        due_at=due_at,
        due_timezone=rule.timezone,
        recurrence_id=task.recurrence_id,
        occurrence_key=key,
    )
    store.insert_task(spawned)
    store.append_revision(_revision_for(spawned, origin=TaskOrigin.SYSTEM_RECURRENCE, prior=None))


def transition_task(
    store: TaskRepository,
    *,
    principal_id: str,
    command: TransitionTask,
    at: datetime,
) -> dict[str, Any]:
    digest = _hash(
        {
            "task_id": command.task_id,
            "referenced_task_id": command.referenced_task_id,
            "expected_version": command.expected_version,
            "target_state": command.target_state.value,
            "cancel_series": command.cancel_series,
        }
    )
    replayed = _replay_or_conflict(store, principal_id, command.idempotency_key, digest)
    if replayed is not None:
        return replayed
    task = _resolve(store, principal_id, command)
    if task.current_version != command.expected_version:
        raise ConflictError(SafeDetail.EXPECTED_VERSION)
    if command.cancel_series and command.target_state not in {
        TaskState.COMPLETED,
        TaskState.CANCELLED,
    }:
        raise InvalidRequestError(SafeDetail.RECURRENCE)
    try:
        updated = task.transitioned(command.target_state, at=at, version=command.expected_version)
    except TaskError:
        raise InvalidRequestError(SafeDetail.STATE) from None
    if not store.save_task(updated, expected_version=command.expected_version):
        raise ConflictError(SafeDetail.EXPECTED_VERSION)
    prior = store.history(principal_id, task.task_id)
    prior_id = prior[-1].revision_id if prior else None
    store.append_revision(
        _revision_for(updated, origin=TaskOrigin.PRINCIPAL_DIRECT, prior=prior_id)
    )
    if command.cancel_series:
        _mark_series_cancelled(store, updated, at=at)
    if command.target_state is TaskState.COMPLETED:
        _spawn_next_occurrence(store, updated, at=at)
    result = {
        "status": "ok",
        "task": _task_view(updated),
        "version_before": command.expected_version,
        "version_after": updated.current_version,
    }
    return _remember(store, principal_id, command.idempotency_key, digest, result)


def read_task(store: TaskRepository, *, principal_id: str, command: ReadTask) -> dict[str, Any]:
    task = store.get_task(principal_id, command.task_id)
    if task is None:
        raise NotFoundError(SafeDetail.TASK_ID)
    return {"status": "ok", "task": _task_view(task)}


def list_tasks(
    store: TaskRepository, *, principal_id: str, command: ListTasks, page_size: int
) -> dict[str, Any]:
    found = store.list_tasks(
        principal_id,
        state=command.state,
        task_role=command.task_role,
        include_archived=command.include_archived,
        limit=page_size,
    )
    visible = [task for task in found if task.evidence_state is ContinuityEvidenceState.ACCEPTED]
    return {"status": "ok", "tasks": [_task_view(task) for task in visible]}


def search_tasks(
    store: TaskRepository, *, principal_id: str, command: SearchTasks, page_size: int
) -> dict[str, Any]:
    found = store.search_tasks(principal_id, command.query, limit=page_size)
    return {"status": "ok", "tasks": [_task_view(task) for task in found]}


def history(
    store: TaskRepository, *, principal_id: str, command: ReadTaskHistory
) -> dict[str, Any]:
    if store.get_task(principal_id, command.task_id) is None:
        raise NotFoundError(SafeDetail.TASK_ID)
    rows = store.history(principal_id, command.task_id)
    return {
        "status": "ok",
        "revisions": [
            {
                "revision_id": row.revision_id,
                "version": row.version,
                "origin": row.origin.value,
                "state": row.state.value,
                "priority": row.priority.value,
                "title": row.title,
                "recorded_at": format_rfc3339(row.recorded_at),
            }
            for row in rows
        ],
    }


def attention(
    store: TaskRepository,
    *,
    principal_id: str,
    command: TasksAttention,
    now: datetime,
    page_size: int,
) -> dict[str, Any]:
    tasks = store.list_tasks(
        principal_id, state=None, task_role=None, include_archived=False, limit=page_size * 4
    )
    commitments = store.list_commitments(principal_id, direction=None, limit=page_size * 4)
    ranked = rank_attention(
        tasks,
        commitments,
        now=now,
        include_waiting=command.include_waiting,
        include_deferred=command.include_deferred,
        timezone=command.timezone,
    )[:page_size]
    return {
        "status": "ok",
        "items": [
            {
                "task_id": item.task_id,
                "commitment_id": item.commitment_id,
                "title": item.title,
                "priority": item.priority.value,
                "reasons": [reason.value for reason in item.reasons],
            }
            for item in ranked
        ],
    }


def preview_bulk(
    store: TaskRepository, *, principal_id: str, command: PreviewTaskBulk
) -> dict[str, Any]:
    targets: list[tuple[str, int]] = []
    for task_id, expected in zip(command.task_ids, command.expected_versions, strict=True):
        task = store.get_task(principal_id, task_id)
        if task is None:
            raise NotFoundError(SafeDetail.TASK_ID)
        if task.current_version != expected:
            return {
                "status": "drift",
                "task_id": task_id,
                "expected_version": expected,
                "current_version": task.current_version,
            }
        targets.append((task_id, expected))
    operation_hash = _hash(
        {
            "operation": command.operation,
            "targets": [[task_id, version] for task_id, version in targets],
            "scheduled_date": (
                None if command.scheduled_date is None else command.scheduled_date.isoformat()
            ),
            "scheduled_at": (
                None if command.scheduled_at is None else format_rfc3339(command.scheduled_at)
            ),
            "due_date": None if command.due_date is None else command.due_date.isoformat(),
            "due_at": None if command.due_at is None else format_rfc3339(command.due_at),
            "target_state": None if command.target_state is None else command.target_state.value,
        }
    )
    preview = TaskPreviewRecord(
        preview_id=issue_identifier(IdKind.BULK_PREVIEW),
        principal_id=principal_id,
        operation=command.operation,
        operation_hash=operation_hash,
        targets=tuple(targets),
        scheduled_date=command.scheduled_date,
        scheduled_at=command.scheduled_at,
        due_date=command.due_date,
        due_at=command.due_at,
        due_timezone=command.due_timezone,
        target_state=command.target_state,
    )
    store.insert_preview(preview)
    return {
        "status": "preview_bound",
        "preview_token": preview.preview_id,
        "operation_hash": operation_hash,
        "targets": [{"task_id": task_id, "version": version} for task_id, version in targets],
    }


def apply_bulk(
    store: TaskRepository,
    *,
    principal_id: str,
    command: ApplyTaskBulk,
    at: datetime,
) -> dict[str, Any]:
    digest = _hash({"preview_token": command.preview_token})
    replayed = _replay_or_conflict(store, principal_id, command.idempotency_key, digest)
    if replayed is not None:
        return replayed
    preview = store.get_preview(principal_id, command.preview_token)
    if preview is None:
        raise NotFoundError(SafeDetail.PREVIEW_TOKEN)
    for task_id, expected in preview.targets:
        task = store.get_task(principal_id, task_id)
        if task is None or task.current_version != expected:
            return {
                "status": "drift",
                "task_id": task_id,
                "expected_version": expected,
                "current_version": None if task is None else task.current_version,
            }
        if preview.target_state is not None and not can_transition(
            task.state, preview.target_state
        ):
            raise InvalidRequestError(SafeDetail.STATE)
    applied: list[dict[str, Any]] = []
    for task_id, expected in preview.targets:
        current = store.get_task(principal_id, task_id)
        if current is None or current.current_version != expected:
            raise ConflictError(SafeDetail.EXPECTED_VERSION)
        try:
            updated = _apply_preview_fields(current, preview, at=at, expected_version=expected)
        except TaskError:
            raise InvalidRequestError(SafeDetail.STATE) from None
        if not store.save_task(updated, expected_version=expected):
            raise ConflictError(SafeDetail.EXPECTED_VERSION)
        prior = store.history(principal_id, task_id)
        prior_id = prior[-1].revision_id if prior else None
        store.append_revision(
            _revision_for(updated, origin=TaskOrigin.PRINCIPAL_DIRECT, prior=prior_id)
        )
        if preview.target_state is TaskState.COMPLETED:
            _spawn_next_occurrence(store, updated, at=at)
        applied.append(_task_view(updated))
    result = {"status": "ok", "tasks": applied}
    return _remember(store, principal_id, command.idempotency_key, digest, result)


def _apply_preview_fields(
    task: Task, preview: TaskPreviewRecord, *, at: datetime, expected_version: int
) -> Task:
    if preview.target_state is not None:
        updated = task.transitioned(preview.target_state, at=at, version=expected_version)
    else:
        updated = replace(task, current_version=task.current_version + 1, updated_at=at)
    due_date = updated.due_date
    due_at = updated.due_at
    if preview.due_date is not None or preview.due_at is not None:
        due_date = preview.due_date
        due_at = preview.due_at
    scheduled_date = updated.scheduled_date
    scheduled_at = updated.scheduled_at
    if preview.scheduled_date is not None or preview.scheduled_at is not None:
        scheduled_date = preview.scheduled_date
        scheduled_at = preview.scheduled_at
    return replace(
        updated,
        due_date=due_date,
        due_at=due_at,
        due_timezone=updated.due_timezone if preview.due_timezone is None else preview.due_timezone,
        scheduled_date=scheduled_date,
        scheduled_at=scheduled_at,
        updated_at=at,
    )


def create_commitment(
    store: TaskRepository,
    *,
    principal_id: str,
    command: CreateCommitment,
    at: datetime,
) -> dict[str, Any]:
    digest = _hash(
        {
            "counterparty_person_id": command.counterparty_person_id,
            "direction": command.direction.value,
            "summary": command.summary,
            "due_date": None if command.due_date is None else command.due_date.isoformat(),
            "due_at": None if command.due_at is None else format_rfc3339(command.due_at),
        }
    )
    replayed = _replay_or_conflict(store, principal_id, command.idempotency_key, digest)
    if replayed is not None:
        return replayed
    try:
        commitment = Commitment(
            commitment_id=issue_identifier(IdKind.COMMITMENT),
            principal_id=principal_id,
            counterparty_person_id=command.counterparty_person_id,
            direction=command.direction,
            summary=command.summary,
            state=CommitmentState.OPEN,
            evidence_state=ContinuityEvidenceState.ACCEPTED,
            current_version=1,
            opened_at=at,
            created_at=at,
            updated_at=at,
            due_date=command.due_date,
            due_at=command.due_at,
            due_timezone=command.due_timezone,
            origin_evidence_ref=command.origin_evidence_ref,
        )
    except TaskError:
        raise InvalidRequestError(SafeDetail.TITLE) from None
    store.insert_commitment(commitment)
    result = {"status": "ok", "commitment": _commitment_view(commitment)}
    return _remember(store, principal_id, command.idempotency_key, digest, result)


def list_commitments(
    store: TaskRepository, *, principal_id: str, command: ListCommitments, page_size: int
) -> dict[str, Any]:
    found = store.list_commitments(principal_id, direction=command.direction, limit=page_size)
    return {"status": "ok", "commitments": [_commitment_view(item) for item in found]}


def waiting_on(store: TaskRepository, *, principal_id: str, page_size: int) -> dict[str, Any]:
    commitments = store.list_commitments(
        principal_id, direction=CommitmentDirection.OWED_TO_PRINCIPAL, limit=page_size
    )
    open_owed = [item for item in commitments if item.state is CommitmentState.OPEN]
    follow_ups = store.list_tasks(
        principal_id,
        state=None,
        task_role=TaskRole.FOLLOW_UP,
        include_archived=False,
        limit=page_size,
    )
    accepted_open = [
        item
        for item in follow_ups
        if not item.is_terminal and item.evidence_state is ContinuityEvidenceState.ACCEPTED
    ]
    return {
        "status": "ok",
        "commitments": [_commitment_view(item) for item in open_owed],
        "follow_ups": [_task_view(item) for item in accepted_open],
    }


def promote_reviewed_task(
    store: TaskRepository,
    *,
    principal_id: str,
    title: str,
    review_decision_id: str,
    origin_evidence_ref: str,
    at: datetime,
) -> Task:
    """Create an accepted Task from a review promotion. Idempotent on evidence."""
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
    store.append_revision(_revision_for(task, origin=TaskOrigin.REVIEW_PROMOTION, prior=None))
    return task


def link_task(
    store: TaskRepository,
    *,
    task: Task,
    kind: str,
    target_id: str,
) -> None:
    from my_pa.domain.tasks.models import ContextLinkKind

    store.insert_link(
        TaskContextLink(
            link_id=issue_identifier(IdKind.TASK_LINK),
            task_id=task.task_id,
            principal_id=task.principal_id,
            kind=ContextLinkKind(kind),
            target_id=target_id,
        )
    )
