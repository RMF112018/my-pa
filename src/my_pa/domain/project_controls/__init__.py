"""PC-CM-IMP-WP01: the Project Controls Constraint Management domain foundation.

`constraint.py` is the first-class `ProjectConstraint` aggregate with its
lifecycle vocabulary, transition rule, terminal invariants, Publish
completeness, record-quality/attention vocabulary, and the In My Court rule;
`category.py` is the Project-scoped Constraint Category and its prefix lock;
`party.py` is the BIC/Responsible party-reference vocabulary;
`business_time.py` is the project calendar date and the Monday-Friday
business-day, default Due, Due Soon, and Overdue rules. Pure domain: nothing
here persists, allocates a public code, syncs, or reaches `domain.task`.
"""

from __future__ import annotations

from my_pa.domain.project_controls.business_time import (
    DEFAULT_DUE_BUSINESS_DAYS,
    DUE_SOON_BUSINESS_DAYS,
    BusinessDayError,
    ProjectTimezoneError,
    business_day_add,
    business_days_elapsed,
    default_due_date,
    due_soon_through,
    is_due_soon,
    is_overdue,
    is_weekday,
    project_today,
)
from my_pa.domain.project_controls.category import (
    CONSTRAINT_CATEGORY_PREFIX_PATTERN,
    ConstraintCategory,
    ConstraintCategoryError,
    ConstraintCategoryState,
    revise_category,
)
from my_pa.domain.project_controls.constraint import (
    ACTIVE_CONSTRAINT_LIFECYCLE_STATES,
    DRAFT_CONSTRAINT_LIFECYCLE_STATES,
    TERMINAL_CONSTRAINT_LIFECYCLE_STATES,
    ConstraintAttention,
    ConstraintAttentionReason,
    ConstraintFieldKey,
    ConstraintInvariantError,
    ConstraintLifecycleError,
    ConstraintLifecycleMove,
    ConstraintLifecycleOperation,
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintPublishError,
    ConstraintRecordQuality,
    ProjectConstraint,
    check_lifecycle_move,
    in_my_court,
    missing_publish_fields,
    validate_publish_completeness,
)
from my_pa.domain.project_controls.history import (
    CONSTRAINT_IDEMPOTENCY_KEY_PATTERN,
    MAX_CONSTRAINT_CLIENT_CONTEXT_CHARACTERS,
    MAX_CONSTRAINT_FAILURE_REASON_CHARACTERS,
    ConstraintCategoryHistoryEntry,
    ConstraintCategoryMutationOperation,
    ConstraintHistoryEntry,
    ConstraintHistoryError,
    ConstraintMutationActor,
    ConstraintMutationOperation,
    ConstraintMutationOutcome,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef, PartyRefError
from my_pa.domain.project_controls.revision import ConstraintRevision, ConstraintRevisionError
from my_pa.domain.project_controls.settings import (
    MAX_PROJECT_TIMEZONE_NAME_CHARACTERS,
    ConstraintProjectSettings,
    ConstraintProjectSettingsError,
)

__all__ = [
    "ACTIVE_CONSTRAINT_LIFECYCLE_STATES",
    "CONSTRAINT_CATEGORY_PREFIX_PATTERN",
    "CONSTRAINT_IDEMPOTENCY_KEY_PATTERN",
    "DEFAULT_DUE_BUSINESS_DAYS",
    "DRAFT_CONSTRAINT_LIFECYCLE_STATES",
    "DUE_SOON_BUSINESS_DAYS",
    "MAX_CONSTRAINT_CLIENT_CONTEXT_CHARACTERS",
    "MAX_CONSTRAINT_FAILURE_REASON_CHARACTERS",
    "MAX_PROJECT_TIMEZONE_NAME_CHARACTERS",
    "TERMINAL_CONSTRAINT_LIFECYCLE_STATES",
    "BusinessDayError",
    "ConstraintAttention",
    "ConstraintAttentionReason",
    "ConstraintCategory",
    "ConstraintCategoryError",
    "ConstraintCategoryHistoryEntry",
    "ConstraintCategoryMutationOperation",
    "ConstraintCategoryState",
    "ConstraintFieldKey",
    "ConstraintHistoryEntry",
    "ConstraintHistoryError",
    "ConstraintInvariantError",
    "ConstraintLifecycleError",
    "ConstraintLifecycleMove",
    "ConstraintLifecycleOperation",
    "ConstraintLifecycleState",
    "ConstraintMutationActor",
    "ConstraintMutationOperation",
    "ConstraintMutationOutcome",
    "ConstraintOrigin",
    "ConstraintProjectSettings",
    "ConstraintProjectSettingsError",
    "ConstraintPublishError",
    "ConstraintRecordQuality",
    "ConstraintRevision",
    "ConstraintRevisionError",
    "PartyKind",
    "PartyRef",
    "PartyRefError",
    "ProjectConstraint",
    "ProjectTimezoneError",
    "business_day_add",
    "business_days_elapsed",
    "check_lifecycle_move",
    "default_due_date",
    "due_soon_through",
    "in_my_court",
    "is_due_soon",
    "is_overdue",
    "is_weekday",
    "missing_publish_fields",
    "project_today",
    "revise_category",
    "validate_publish_completeness",
]
