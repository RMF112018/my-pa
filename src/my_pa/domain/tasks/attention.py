"""Deterministic attention ranking. Never writes priority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from my_pa.domain.common.time import ensure_utc
from my_pa.domain.tasks.models import (
    Commitment,
    CommitmentDirection,
    CommitmentState,
    Task,
    TaskPriority,
    TaskRole,
    TaskState,
)

__all__ = ["AttentionItem", "AttentionReason", "rank_attention"]

_STALE_AFTER = timedelta(days=7)


class AttentionReason(StrEnum):
    """Explainable codes. Ranking uses these; stored priority is unchanged."""

    OVERDUE = "overdue"
    DUE_TODAY = "due_today"
    SCHEDULED_TODAY = "scheduled_today"
    FOLLOW_UP_DUE = "follow_up_due"
    COMMITMENT_WAITING = "commitment_waiting"
    P1_OPEN = "p1_open"
    STALE_OPEN = "stale_open"
    RECURRENCE_DUE = "recurrence_due"


_RANK: dict[AttentionReason, int] = {
    AttentionReason.OVERDUE: 0,
    AttentionReason.FOLLOW_UP_DUE: 1,
    AttentionReason.COMMITMENT_WAITING: 2,
    AttentionReason.DUE_TODAY: 3,
    AttentionReason.RECURRENCE_DUE: 4,
    AttentionReason.SCHEDULED_TODAY: 5,
    AttentionReason.P1_OPEN: 6,
    AttentionReason.STALE_OPEN: 7,
}


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """One ranked recommendation. ``priority`` is echoed, never mutated."""

    task_id: str | None
    commitment_id: str | None
    reasons: tuple[AttentionReason, ...]
    priority: TaskPriority
    title: str


def rank_attention(
    tasks: tuple[Task, ...],
    commitments: tuple[Commitment, ...] = (),
    *,
    now: datetime,
    include_waiting: bool = False,
    include_deferred: bool = False,
    timezone: str = "UTC",
) -> tuple[AttentionItem, ...]:
    """Return a stable ranking. Deferred future work is suppressed by default."""
    instant = ensure_utc(now)
    zone = ZoneInfo(timezone)
    today = instant.astimezone(zone).date()
    items: list[AttentionItem] = []
    waiting_commitments = tuple(
        commitment
        for commitment in commitments
        if commitment.direction is CommitmentDirection.OWED_TO_PRINCIPAL
        and commitment.state is CommitmentState.OPEN
    )
    for task in tasks:
        if task.archived_at is not None:
            continue
        if task.is_terminal:
            continue
        if task.state in {TaskState.WAITING, TaskState.BLOCKED} and not include_waiting:
            continue
        if (
            task.deferred_until is not None
            and ensure_utc(task.deferred_until) > instant
            and not include_deferred
            and not _overdue(task, today, instant, zone)
        ):
            continue
        reasons = _reasons(task, today, instant, zone, waiting_commitments)
        deferred = task.deferred_until is not None and ensure_utc(task.deferred_until) > instant
        if not reasons and not (include_deferred and deferred):
            continue
        items.append(
            AttentionItem(
                task_id=task.task_id,
                commitment_id=None,
                reasons=reasons,
                priority=task.priority,
                title=task.title,
            )
        )
    seen_commitments = {item.commitment_id for item in items if item.commitment_id}
    for commitment in waiting_commitments:
        if commitment.commitment_id in seen_commitments:
            continue
        items.append(
            AttentionItem(
                task_id=None,
                commitment_id=commitment.commitment_id,
                reasons=(AttentionReason.COMMITMENT_WAITING,),
                priority=TaskPriority.P3,
                title=commitment.summary,
            )
        )
    return tuple(sorted(items, key=_sort_key))


def _sort_key(item: AttentionItem) -> tuple[int, str, str]:
    best = min((_RANK[reason] for reason in item.reasons), default=99)
    identity = item.task_id or item.commitment_id or ""
    return (best, item.priority.value, identity)


def _reasons(
    task: Task,
    today: date,
    now: datetime,
    zone: ZoneInfo,
    waiting: tuple[Commitment, ...],
) -> tuple[AttentionReason, ...]:
    found: list[AttentionReason] = []
    if _overdue(task, today, now, zone):
        found.append(AttentionReason.OVERDUE)
    due = _due_date(task, zone)
    if due == today:
        found.append(AttentionReason.DUE_TODAY)
        if task.task_role is TaskRole.FOLLOW_UP:
            found.append(AttentionReason.FOLLOW_UP_DUE)
    scheduled = _scheduled_date(task, zone)
    if scheduled == today:
        found.append(AttentionReason.SCHEDULED_TODAY)
    if task.recurrence_id is not None and (due == today or scheduled == today):
        found.append(AttentionReason.RECURRENCE_DUE)
    if task.person_id and any(
        commitment.counterparty_person_id == task.person_id for commitment in waiting
    ):
        found.append(AttentionReason.COMMITMENT_WAITING)
    if task.priority is TaskPriority.P1 and task.state is TaskState.OPEN:
        found.append(AttentionReason.P1_OPEN)
    opened = ensure_utc(task.opened_at)
    if task.state is TaskState.OPEN and now - opened >= _STALE_AFTER:
        found.append(AttentionReason.STALE_OPEN)
    return tuple(found)


def _overdue(task: Task, today: date, now: datetime, zone: ZoneInfo) -> bool:
    if task.due_at is not None:
        return ensure_utc(task.due_at) < now
    if task.due_date is not None:
        return task.due_date < today
    return False


def _due_date(task: Task, zone: ZoneInfo) -> date | None:
    if task.due_date is not None:
        return task.due_date
    if task.due_at is not None:
        return ensure_utc(task.due_at).astimezone(zone).date()
    return None


def _scheduled_date(task: Task, zone: ZoneInfo) -> date | None:
    if task.scheduled_date is not None:
        return task.scheduled_date
    if task.scheduled_at is not None:
        return ensure_utc(task.scheduled_at).astimezone(zone).date()
    return None
