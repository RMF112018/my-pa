"""Constraint Category: the Project-scoped numbering scope a Constraint belongs to.

A Category is owned by exactly one Principal and one continuity Project
(`prj_`), and carries the text `prefix` that public Constraint codes are later
allocated under. The prefix is therefore the one field that becomes immutable:
once issuance has occurred or a lock has been recorded (`prefix_locked_at`),
changing it would orphan every code already issued. Title, description, and
display order carry no such consequence and stay mutable while locked.

`ConstraintCategoryState` is `ACTIVE`, `INACTIVE`, `ARCHIVED`. Only an `ACTIVE`
Category admits a normal Publish (`constraint.py`); nothing here deletes a
Category, because v1 has no destructive historical deletion.

Project-uniqueness of the prefix, reorder persistence, and the issued counter
are later persistence concerns and are deliberately absent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "CONSTRAINT_CATEGORY_PREFIX_PATTERN",
    "ConstraintCategory",
    "ConstraintCategoryError",
    "ConstraintCategoryState",
    "revise_category",
]

#: The accepted conservative bounded prefix syntax: one alphanumeric, then up
#: to fifteen of alphanumeric, `_`, or `-`. Sixteen characters at most.
CONSTRAINT_CATEGORY_PREFIX_PATTERN: Final = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]{0,15}\Z")


class ConstraintCategoryError(ValueError):
    """A Category invariant or mutation rule refused to proceed. `code` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConstraintCategoryState(StrEnum):
    """Where a Category sits: in use, retired from new Publishes, or archived."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class ConstraintCategory:
    """One Constraint Category, scoped to one Principal and one continuity Project."""

    category_id: str
    principal_id: str
    project_id: str
    prefix: str
    title: str
    state: ConstraintCategoryState
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    display_order: int = 0
    prefix_locked_at: datetime | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.category_id, IdKind.CONSTRAINT_CATEGORY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.project_id, IdKind.PROJECT)
        if not CONSTRAINT_CATEGORY_PREFIX_PATTERN.match(self.prefix):
            raise ConstraintCategoryError(
                "category_prefix_invalid",
                "a category prefix is 1-16 characters of [A-Za-z0-9_-] and does not"
                " start with '_' or '-'",
            )
        if not self.title.strip():
            raise ConstraintCategoryError("category_title_blank", "a category carries a title")
        if self.display_order < 0:
            raise ConstraintCategoryError(
                "category_display_order_negative", "display order is zero or positive"
            )
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))
        if self.prefix_locked_at is not None:
            object.__setattr__(self, "prefix_locked_at", ensure_utc(self.prefix_locked_at))

    @property
    def is_prefix_locked(self) -> bool:
        """Whether the prefix may still change. Locked once `prefix_locked_at` is set."""
        return self.prefix_locked_at is not None


def revise_category(
    category: ConstraintCategory,
    *,
    prefix: str | None = None,
    title: str | None = None,
    description: str | None = None,
    display_order: int | None = None,
    updated_at: datetime | None = None,
) -> ConstraintCategory:
    """Return `category` with the given descriptive fields changed.

    The one rule this function exists for: a prefix change is refused with
    `category_prefix_locked` once the prefix is locked, while title,
    description, and display order remain changeable on the same locked
    Category. A prefix "change" to the same value is not a change.
    """
    if prefix is not None and prefix != category.prefix and category.is_prefix_locked:
        raise ConstraintCategoryError(
            "category_prefix_locked",
            "the prefix is immutable once codes have been issued under it",
        )
    return replace(
        category,
        prefix=category.prefix if prefix is None else prefix,
        title=category.title if title is None else title,
        description=category.description if description is None else description,
        display_order=category.display_order if display_order is None else display_order,
        updated_at=category.updated_at if updated_at is None else updated_at,
    )
