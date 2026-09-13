"""One append-only mutation receipt per Continuity Project write.

WP-MCP-PROJ-03. `ProjectHistoryEntry` mirrors `CommitmentHistoryEntry`
structurally: a record that an update or close was *attempted*, what this build
normalised the request into, what version the Project was at before and after,
who asked, and what happened — never the caller's raw request.

`TaskMutationActor` and `TaskMutationOutcome` are reused from
`domain.task.history`: an actor kind and a mutation outcome mean the same thing
for a Project mutation as they do for a Task or Commitment one.

`ProjectMutationAction` is its own closed vocabulary, sized to only what this
package needs: `UPDATE` (name, description, and/or nonterminal state) and
`CLOSE` (an explicit `close_project` call). There is no `CREATE` member —
project creation is recorded on `continuity_authoring_submissions`, not here —
and no `DELETE`, `REOPEN`, or `ARCHIVE`.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.situation.situation import Project, ProjectState
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.history import (
    IDEMPOTENCY_KEY_PATTERN,
    TaskMutationActor,
    TaskMutationOutcome,
)

__all__ = [
    "ProjectHistoryEntry",
    "ProjectHistoryOps",
    "ProjectIdempotencyConflictError",
    "ProjectIllegalTransitionError",
    "ProjectMutationAction",
    "ProjectMutationReceipt",
    "ProjectVersionConflictError",
    "execute_close_project",
    "execute_update_project",
]


class ProjectMutationAction(StrEnum):
    """What this build normalised a project mutation request into."""

    UPDATE = "update"
    CLOSE = "close"


class ProjectIllegalTransitionError(ValueError):
    """Raised when a requested project lifecycle transition is not permitted."""


class ProjectIdempotencyConflictError(Exception):
    """Raised when a key is reused for different normalized project content."""


@dataclass(frozen=True, slots=True)
class ProjectMutationReceipt:
    """What a mutation attempt returns: the history row it produced, and the project now."""

    history: ProjectHistoryEntry
    project: Project
    replayed: bool = False


class ProjectVersionConflictError(Exception):
    """Raised when `expected_version` does not match the project's current version.

    Carries the `ProjectMutationReceipt` this attempt still produced — the
    `REJECTED` history row is written before this is raised, exactly as
    `TaskVersionConflictError` states for the task plane.
    """

    def __init__(self, receipt: ProjectMutationReceipt) -> None:
        super().__init__("the project's current version does not match expected_version")
        self.receipt = receipt


@dataclass(frozen=True, slots=True)
class ProjectHistoryEntry:
    """One append-only row: a project mutation, its target, and what happened."""

    history_id: str
    principal_id: str
    project_id: str
    action: ProjectMutationAction
    actor: TaskMutationActor
    outcome: TaskMutationOutcome
    before_version: int
    after_version: int
    occurred_at: datetime
    recorded_at: datetime
    idempotency_key: str | None = None
    request_digest: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.history_id, IdKind.PROJECT_HISTORY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.project_id, IdKind.PROJECT)
        if not isinstance(self.action, ProjectMutationAction):
            raise ValueError("a project history entry names one known action")
        if not isinstance(self.actor, TaskMutationActor):
            raise ValueError("a project history entry names one known actor")
        if not isinstance(self.outcome, TaskMutationOutcome):
            raise ValueError("a project history entry names one known outcome")
        if self.before_version < 0:
            raise ValueError("a project history entry records a non-negative before-version")
        if self.outcome is TaskMutationOutcome.APPLIED:
            if self.after_version <= self.before_version:
                raise ValueError("an applied mutation advances the version it recorded")
        elif self.after_version != self.before_version:
            raise ValueError("a rejected or no-op mutation records no version change")
        ensure_utc(self.occurred_at)
        ensure_utc(self.recorded_at)
        if self.idempotency_key is not None and not IDEMPOTENCY_KEY_PATTERN.fullmatch(
            self.idempotency_key
        ):
            raise ValueError("an idempotency key must be 8-128 opaque characters")
        if self.request_digest is not None and not re.fullmatch(
            r"[0-9a-f]{64}", self.request_digest
        ):
            raise ValueError("a request digest is a lowercase SHA-256 hex value")


class ProjectHistoryOps(Protocol):
    """Persistence primitives the mutation protocol needs."""

    def lock_project(self, principal_id: str, project_id: str) -> Project | None: ...

    def persist_project(self, project: Project) -> None: ...

    def persist_history(self, entry: ProjectHistoryEntry) -> None: ...

    def history_for_key(
        self, principal_id: str, idempotency_key: str
    ) -> ProjectHistoryEntry | None: ...


def execute_update_project(
    ops: ProjectHistoryOps,
    *,
    principal_id: str,
    project_id: str,
    expected_version: int,
    idempotency_key: str,
    request_digest: str,
    name: str | None,
    description: str | None,
    state: ProjectState | None,
    now: datetime,
    actor: TaskMutationActor = TaskMutationActor.PRINCIPAL,
) -> ProjectMutationReceipt | None:
    """Apply a versioned project update, or return None when the row is absent."""

    def change(current: Project) -> Project:
        if current.state is ProjectState.CLOSED:
            raise ProjectIllegalTransitionError("a closed project cannot be updated")
        if state is not None and state not in (ProjectState.ACTIVE, ProjectState.ON_HOLD):
            raise ProjectIllegalTransitionError(
                "a project update may only move between active and on_hold"
            )
        replacements: dict[str, object] = {}
        if name is not None:
            replacements["name"] = name
        if description is not None:
            replacements["description"] = description
        if state is not None:
            replacements["state"] = state
        return dataclasses.replace(current, **replacements)

    return _mutate(
        ops,
        principal_id=principal_id,
        project_id=project_id,
        expected_version=expected_version,
        action=ProjectMutationAction.UPDATE,
        actor=actor,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        change=change,
        now=now,
    )


def execute_close_project(
    ops: ProjectHistoryOps,
    *,
    principal_id: str,
    project_id: str,
    expected_version: int,
    idempotency_key: str,
    request_digest: str,
    now: datetime,
    actor: TaskMutationActor = TaskMutationActor.PRINCIPAL,
) -> ProjectMutationReceipt | None:
    """Close a project, or return None when the row is absent.

    Already-closed is an illegal transition, not a silent no-op.
    """

    def change(current: Project) -> Project:
        if current.state is ProjectState.CLOSED:
            raise ProjectIllegalTransitionError("a closed project cannot be closed again")
        if current.state not in (ProjectState.ACTIVE, ProjectState.ON_HOLD):
            raise ProjectIllegalTransitionError("only an active or on-hold project may close")
        return dataclasses.replace(current, state=ProjectState.CLOSED, closed_at=now)

    return _mutate(
        ops,
        principal_id=principal_id,
        project_id=project_id,
        expected_version=expected_version,
        action=ProjectMutationAction.CLOSE,
        actor=actor,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        change=change,
        now=now,
    )


def _mutate(
    ops: ProjectHistoryOps,
    *,
    principal_id: str,
    project_id: str,
    expected_version: int,
    action: ProjectMutationAction,
    actor: TaskMutationActor,
    idempotency_key: str,
    request_digest: str,
    change: Callable[[Project], Project],
    now: datetime,
) -> ProjectMutationReceipt | None:
    prior = ops.history_for_key(principal_id, idempotency_key)
    if prior is not None:
        if prior.request_digest != request_digest:
            raise ProjectIdempotencyConflictError(
                "the idempotency key was used for different normalized content"
            )
        current = ops.lock_project(principal_id, prior.project_id)
        if current is None:
            raise RuntimeError("a recorded history entry names a project that still exists")
        return ProjectMutationReceipt(history=prior, project=current, replayed=True)

    current = ops.lock_project(principal_id, project_id)
    if current is None:
        return None
    if current.version != expected_version:
        rejected = _record(
            ops,
            principal_id=principal_id,
            project_id=current.project_id,
            action=action,
            actor=actor,
            outcome=TaskMutationOutcome.REJECTED,
            before_version=current.version,
            after_version=current.version,
            occurred_at=now,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        raise ProjectVersionConflictError(ProjectMutationReceipt(history=rejected, project=current))

    proposed = change(current)
    applied = dataclasses.replace(proposed, version=current.version + 1, updated_at=now)
    ops.persist_project(applied)
    history = _record(
        ops,
        principal_id=principal_id,
        project_id=applied.project_id,
        action=action,
        actor=actor,
        outcome=TaskMutationOutcome.APPLIED,
        before_version=current.version,
        after_version=applied.version,
        occurred_at=now,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    )
    return ProjectMutationReceipt(history=history, project=applied)


def _record(
    ops: ProjectHistoryOps,
    *,
    principal_id: str,
    project_id: str,
    action: ProjectMutationAction,
    actor: TaskMutationActor,
    outcome: TaskMutationOutcome,
    before_version: int,
    after_version: int,
    occurred_at: datetime,
    idempotency_key: str,
    request_digest: str,
) -> ProjectHistoryEntry:
    entry = ProjectHistoryEntry(
        history_id=issue_identifier(IdKind.PROJECT_HISTORY),
        principal_id=principal_id,
        project_id=project_id,
        action=action,
        actor=actor,
        outcome=outcome,
        before_version=before_version,
        after_version=after_version,
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    )
    ops.persist_history(entry)
    return entry
