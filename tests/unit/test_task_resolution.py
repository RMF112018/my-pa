"""Conversational resolution never mutates on a fuzzy match."""

from __future__ import annotations

from datetime import UTC, datetime

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.tasks.models import (
    AcceptanceKind,
    ContinuityEvidenceState,
    Task,
    TaskPriority,
    TaskRole,
    TaskState,
)
from my_pa.domain.tasks.resolution import ResolutionOutcome, resolve_task_reference

WHEN = datetime(2026, 8, 10, tzinfo=UTC)


def _task(title: str) -> Task:
    return Task(
        task_id=issue_identifier(IdKind.TASK),
        principal_id=issue_identifier(IdKind.PRINCIPAL),
        title=title,
        state=TaskState.OPEN,
        task_role=TaskRole.ACTION,
        priority=TaskPriority.P3,
        evidence_state=ContinuityEvidenceState.ACCEPTED,
        acceptance_kind=AcceptanceKind.DIRECT_PRINCIPAL,
        current_version=1,
        opened_at=WHEN,
        created_at=WHEN,
        updated_at=WHEN,
    )


def test_explicit_id_wins() -> None:
    first = _task("call Mike")
    second = _task("call Mike")
    resolved = resolve_task_reference(
        explicit_task_id=second.task_id, referenced_task_id=first.task_id, known=(first, second)
    )
    assert resolved.outcome is ResolutionOutcome.EXACT
    assert resolved.task_id == second.task_id


def test_referenced_task_id_resolves_that_task() -> None:
    task = _task("call Mike")
    resolved = resolve_task_reference(referenced_task_id=task.task_id, known=(task,))
    assert resolved.outcome is ResolutionOutcome.EXACT
    assert resolved.task_id == task.task_id


def test_exact_title_is_used_only_when_unique() -> None:
    task = _task("call Mike")
    resolved = resolve_task_reference(title="call Mike", known=(task,))
    assert resolved.task_id == task.task_id
    duplicate = _task("call Mike")
    ambiguous = resolve_task_reference(title="call Mike", known=(task, duplicate))
    assert ambiguous.outcome is ResolutionOutcome.AMBIGUOUS
    assert set(ambiguous.candidates) == {task.task_id, duplicate.task_id}


def test_fuzzy_title_is_refused() -> None:
    task = _task("call Mike about Turner permit")
    refused = resolve_task_reference(title="that Turner thing", known=(task,), allow_fuzzy=True)
    assert refused.outcome is ResolutionOutcome.REFUSED_FUZZY
    missing = resolve_task_reference(title="that Turner thing", known=(task,))
    assert missing.outcome is ResolutionOutcome.NOT_FOUND
