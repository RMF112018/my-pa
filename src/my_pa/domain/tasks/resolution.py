"""Resolve a conversational Task reference without guessing.

Order is fixed: explicit identifier, then a conversation-referenced identifier,
then an exact title match. Fuzzy or semantic-only matches never mutate.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.tasks.models import Task

__all__ = ["ResolutionOutcome", "ResolvedReference", "resolve_task_reference"]


class ResolutionOutcome(StrEnum):
    """How resolution stopped. Mutation proceeds only on ``exact``."""

    EXACT = "exact"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    REFUSED_FUZZY = "refused_fuzzy"


@dataclass(frozen=True, slots=True)
class ResolvedReference:
    """The outcome of one resolution attempt."""

    outcome: ResolutionOutcome
    task_id: str | None
    candidates: tuple[str, ...]


def resolve_task_reference(
    *,
    explicit_task_id: str | None = None,
    referenced_task_id: str | None = None,
    title: str | None = None,
    known: Sequence[Task] = (),
    allow_fuzzy: bool = False,
) -> ResolvedReference:
    """Resolve in the documented order. ``allow_fuzzy`` is always refused."""
    if allow_fuzzy:
        return ResolvedReference(ResolutionOutcome.REFUSED_FUZZY, None, ())
    if explicit_task_id is not None:
        return _by_id(explicit_task_id, known)
    if referenced_task_id is not None:
        return _by_id(referenced_task_id, known)
    if title is not None:
        return _by_exact_title(title, known)
    return ResolvedReference(ResolutionOutcome.NOT_FOUND, None, ())


def _by_id(task_id: str, known: Sequence[Task]) -> ResolvedReference:
    try:
        validate_identifier(task_id, IdKind.TASK)
    except InvalidIdentifierError:
        return ResolvedReference(ResolutionOutcome.NOT_FOUND, None, ())
    if any(task.task_id == task_id for task in known) or not known:
        # An empty known set means the caller will load by identifier next.
        return ResolvedReference(ResolutionOutcome.EXACT, task_id, (task_id,))
    return ResolvedReference(ResolutionOutcome.NOT_FOUND, None, ())


def _by_exact_title(title: str, known: Sequence[Task]) -> ResolvedReference:
    needle = title.strip()
    matches = tuple(task.task_id for task in known if task.title == needle)
    if len(matches) == 1:
        return ResolvedReference(ResolutionOutcome.EXACT, matches[0], matches)
    if len(matches) > 1:
        return ResolvedReference(ResolutionOutcome.AMBIGUOUS, None, matches)
    return ResolvedReference(ResolutionOutcome.NOT_FOUND, None, ())
