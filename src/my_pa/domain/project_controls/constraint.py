"""The ProjectConstraint aggregate: lifecycle, invariants, Publish completeness.

A `ProjectConstraint` is a first-class Project Controls record — something a
construction project is waiting on — owned by one Principal (`prn_`) and bound
to one existing continuity Project (`prj_`). It is deliberately *not* a
`domain.task.Task` or a `Commitment`, and this module imports neither: a
Constraint can outlive, precede, or have nothing to do with any Task, and no
Task completing or Commitment closing ever moves a Constraint's lifecycle.
`tests/unit/test_project_controls_constraint.py` guards that this package never
imports `my_pa.domain.task`.

Lifecycle is seven stored states in three classes. `DRAFT` is unpublished and
carries no public code; the four active states are the published working
states; `CLOSED` and `VOID` are terminal. `REOPEN`, like `PUBLISH`, `CLOSE`,
and `VOID`, is an *operation*, not a state: `check_lifecycle_move` is the one
place the accepted transition matrix lives, and it refuses a generic
`TRANSITION` for any move into or out of `DRAFT` or a terminal state, so that
none of the four named operations can be smuggled in as a status patch.

`record_quality` is data quality, never lifecycle: a `LEGACY_INCOMPLETE` record
imported from a workbook may be missing fields a normal Publish requires, and
`ConstraintAttention` is how that is reported, without any eighth state.

Number allocation, persistence, revisions, and sync are later work packages.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.project_controls.category import ConstraintCategory, ConstraintCategoryState
from my_pa.domain.project_controls.party import PartyKind, PartyRef

__all__ = [
    "ACTIVE_CONSTRAINT_LIFECYCLE_STATES",
    "DRAFT_CONSTRAINT_LIFECYCLE_STATES",
    "TERMINAL_CONSTRAINT_LIFECYCLE_STATES",
    "ConstraintAttention",
    "ConstraintAttentionReason",
    "ConstraintFieldKey",
    "ConstraintInvariantError",
    "ConstraintLifecycleError",
    "ConstraintLifecycleMove",
    "ConstraintLifecycleOperation",
    "ConstraintLifecycleState",
    "ConstraintOrigin",
    "ConstraintPublishError",
    "ConstraintRecordQuality",
    "ProjectConstraint",
    "check_lifecycle_move",
    "in_my_court",
    "missing_publish_fields",
    "validate_publish_completeness",
]


class ConstraintLifecycleState(StrEnum):
    """The seven stored lifecycle states. `REOPEN` is an operation, not a member."""

    DRAFT = "draft"
    IDENTIFIED = "identified"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    ON_HOLD = "on_hold"
    CLOSED = "closed"
    VOID = "void"


#: The three lifecycle classes. Every state is in exactly one.
DRAFT_CONSTRAINT_LIFECYCLE_STATES: Final[frozenset[ConstraintLifecycleState]] = frozenset(
    {ConstraintLifecycleState.DRAFT}
)
ACTIVE_CONSTRAINT_LIFECYCLE_STATES: Final[frozenset[ConstraintLifecycleState]] = frozenset(
    {
        ConstraintLifecycleState.IDENTIFIED,
        ConstraintLifecycleState.PENDING,
        ConstraintLifecycleState.IN_PROGRESS,
        ConstraintLifecycleState.ON_HOLD,
    }
)
TERMINAL_CONSTRAINT_LIFECYCLE_STATES: Final[frozenset[ConstraintLifecycleState]] = frozenset(
    {ConstraintLifecycleState.CLOSED, ConstraintLifecycleState.VOID}
)


class ConstraintLifecycleOperation(StrEnum):
    """How a lifecycle move is being asked for.

    `TRANSITION` is the generic active-to-active move (and the same-state
    no-op). The other four are the named operations the matrix reserves for
    crossing a class boundary; each is only legal for its own move.
    """

    PUBLISH = "publish"
    TRANSITION = "transition"
    CLOSE = "close"
    VOID = "void"
    REOPEN = "reopen"


class ConstraintLifecycleMove(StrEnum):
    """What `check_lifecycle_move` decided: nothing changes, or the state does."""

    NO_OP = "no_op"
    CHANGE = "change"


class ConstraintLifecycleError(ValueError):
    """A lifecycle move was refused. `code` is stable.

    `constraint_lifecycle_move_prohibited`: no operation makes this state pair
    legal. `constraint_lifecycle_operation_mismatch`: the pair is legal, but
    only under a different operation than the one offered.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def check_lifecycle_move(
    current: ConstraintLifecycleState,
    target: ConstraintLifecycleState,
    operation: ConstraintLifecycleOperation,
) -> ConstraintLifecycleMove:
    """Decide whether `operation` may move a Constraint from `current` to `target`.

    Same-state under `TRANSITION` is the no-op the matrix names for every
    state (DRAFT edit, active same-state, CLOSED→CLOSED, VOID→VOID) and returns
    `NO_OP`. Same-state under any named operation is refused: a second Close
    on a closed record is not a no-op a caller should be able to express
    silently. Every other legal pair returns `CHANGE`; everything else raises.
    """
    if current == target:
        if operation is ConstraintLifecycleOperation.TRANSITION:
            return ConstraintLifecycleMove.NO_OP
        raise ConstraintLifecycleError(
            "constraint_lifecycle_operation_mismatch",
            f"{operation.value} cannot target the current state {current.value}",
        )
    current_active = current in ACTIVE_CONSTRAINT_LIFECYCLE_STATES
    target_active = target in ACTIVE_CONSTRAINT_LIFECYCLE_STATES
    if current is ConstraintLifecycleState.DRAFT and target_active:
        required = ConstraintLifecycleOperation.PUBLISH
    elif current_active and target_active:
        required = ConstraintLifecycleOperation.TRANSITION
    elif current_active and target is ConstraintLifecycleState.CLOSED:
        required = ConstraintLifecycleOperation.CLOSE
    elif current_active and target is ConstraintLifecycleState.VOID:
        required = ConstraintLifecycleOperation.VOID
    elif current in TERMINAL_CONSTRAINT_LIFECYCLE_STATES and target_active:
        required = ConstraintLifecycleOperation.REOPEN
    else:
        raise ConstraintLifecycleError(
            "constraint_lifecycle_move_prohibited",
            f"no operation moves a constraint from {current.value} to {target.value}",
        )
    if operation is not required:
        raise ConstraintLifecycleError(
            "constraint_lifecycle_operation_mismatch",
            f"{current.value} to {target.value} requires {required.value}, not {operation.value}",
        )
    return ConstraintLifecycleMove.CHANGE


class ConstraintRecordQuality(StrEnum):
    """Data quality of the record. Never a lifecycle state."""

    NORMAL = "normal"
    LEGACY_INCOMPLETE = "legacy_incomplete"


class ConstraintOrigin(StrEnum):
    """Bounded provenance: where the record came from. Immutable once set.

    `LEGACY_WORKBOOK_IMPORT` is the only origin that, together with
    `LEGACY_INCOMPLETE` quality, may bypass normal completeness (the accepted
    §17 migration exception). `PRODUCT` is a record authored in `my-pa`.
    """

    PRODUCT = "product"
    LEGACY_WORKBOOK_IMPORT = "legacy_workbook_import"


class ConstraintAttentionReason(StrEnum):
    """Why a record needs attention. Vocabulary only; derivation of the last
    two is later sync/data-quality work and is not implemented here."""

    LEGACY_INCOMPLETE = "legacy_incomplete"
    OPEN_SYNC_CONFLICT = "open_sync_conflict"
    DATA_QUALITY_EXCEPTION = "data_quality_exception"


class ConstraintFieldKey(StrEnum):
    """The fields a normal Publish requires, as typed values a reader can name.

    The browser must not infer missing fields; it consumes these.
    """

    PROJECT_ID = "project_id"
    CATEGORY_ID = "category_id"
    CONSTRAINT_CODE = "constraint_code"
    DESCRIPTION = "description"
    DATE_IDENTIFIED = "date_identified"
    DUE_DATE = "due_date"
    BIC = "bic"


@dataclass(frozen=True, slots=True)
class ConstraintAttention:
    """The derived needs-attention projection: reasons and the fields missing.

    `needs_attention` is exactly "there is at least one reason", so a record
    with missing fields but no reason (a Draft mid-authoring) does not need
    attention, and a sync conflict with nothing missing does.
    """

    reasons: tuple[ConstraintAttentionReason, ...] = ()
    missing_fields: tuple[ConstraintFieldKey, ...] = ()

    @property
    def needs_attention(self) -> bool:
        """Whether any attention reason holds."""
        return bool(self.reasons)


class ConstraintInvariantError(ValueError):
    """A `ProjectConstraint` violated a structural invariant. `code` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ProjectConstraint:
    """One Constraint record, in any lifecycle state, with its invariants enforced.

    Draft records may be incomplete: `project_id`, `category_id`,
    `description`, `date_identified`, and `due_date` are all optional here so
    a Draft can be saved mid-authoring, and `validate_publish_completeness` is
    where "complete enough to Publish" is decided. What this class enforces is
    what must hold in *every* state: identity shape, the published/Draft code
    rule (CM-BE-AC-004/005), the terminal-field rules, and that legacy quality
    is only claimed by a legacy origin.
    """

    constraint_id: str
    principal_id: str
    lifecycle_state: ConstraintLifecycleState
    origin: ConstraintOrigin
    created_at: datetime
    updated_at: datetime
    version: int = 1
    project_id: str | None = None
    category_id: str | None = None
    constraint_code: str | None = None
    description: str | None = None
    date_identified: date | None = None
    due_date: date | None = None
    reference: str | None = None
    current_update: str | None = None
    bic: tuple[PartyRef, ...] = ()
    responsible: tuple[PartyRef, ...] = ()
    completion_date: date | None = None
    closure_commentary: str | None = None
    voided_date: date | None = None
    void_reason: str | None = None
    record_quality: ConstraintRecordQuality = ConstraintRecordQuality.NORMAL
    published_at: datetime | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.constraint_id, IdKind.PROJECT_CONSTRAINT)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if self.project_id is not None:
            validate_identifier(self.project_id, IdKind.PROJECT)
        if self.category_id is not None:
            validate_identifier(self.category_id, IdKind.CONSTRAINT_CATEGORY)
        if self.version < 1:
            raise ConstraintInvariantError(
                "constraint_version_not_positive", "version is a positive integer"
            )
        if self.constraint_code is not None and not self.constraint_code.strip():
            raise ConstraintInvariantError(
                "constraint_code_blank", "a constraint code, when present, is non-blank"
            )
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))
        if self.published_at is not None:
            object.__setattr__(self, "published_at", ensure_utc(self.published_at))
        self._check_publication_shape()
        self._check_terminal_fields()
        if (
            self.record_quality is ConstraintRecordQuality.LEGACY_INCOMPLETE
            and self.origin is not ConstraintOrigin.LEGACY_WORKBOOK_IMPORT
        ):
            raise ConstraintInvariantError(
                "constraint_legacy_quality_requires_legacy_origin",
                "only a legacy workbook import may carry LEGACY_INCOMPLETE quality",
            )

    def _check_publication_shape(self) -> None:
        is_draft = self.lifecycle_state is ConstraintLifecycleState.DRAFT
        if is_draft and (self.constraint_code is not None or self.published_at is not None):
            raise ConstraintInvariantError(
                "constraint_draft_has_publication",
                "a DRAFT carries no public code and no published_at",
            )
        if not is_draft and (self.constraint_code is None or self.published_at is None):
            raise ConstraintInvariantError(
                "constraint_published_without_code",
                "a published constraint carries a public code and published_at",
            )

    def _check_terminal_fields(self) -> None:
        state = self.lifecycle_state
        if state is ConstraintLifecycleState.CLOSED:
            if self.completion_date is None:
                raise ConstraintInvariantError(
                    "constraint_closed_requires_completion_date",
                    "a CLOSED constraint records its completion date",
                )
            if self.voided_date is not None or self.void_reason is not None:
                raise ConstraintInvariantError(
                    "constraint_closed_carries_void_fields",
                    "a CLOSED constraint carries no void fields",
                )
            return
        if state is ConstraintLifecycleState.VOID:
            if self.voided_date is None or self.void_reason is None or not self.void_reason.strip():
                raise ConstraintInvariantError(
                    "constraint_void_requires_reason",
                    "a VOID constraint records its voided date and a non-blank reason",
                )
            if self.completion_date is not None:
                raise ConstraintInvariantError(
                    "constraint_void_carries_completion_date",
                    "a VOID constraint carries no completion date",
                )
            return
        if (
            self.completion_date is not None
            or self.voided_date is not None
            or self.void_reason is not None
        ):
            raise ConstraintInvariantError(
                "constraint_active_carries_terminal_fields",
                "only a terminal constraint carries completion or void fields",
            )

    @property
    def is_published(self) -> bool:
        """Whether the record has left Draft. Equivalent to `constraint_code is not None`."""
        return self.lifecycle_state is not ConstraintLifecycleState.DRAFT


class ConstraintPublishError(ValueError):
    """A Draft is not ready for normal Publish. `code` is stable.

    `constraint_publish_incomplete` carries the missing `ConstraintFieldKey`
    values in `missing_fields`; the other codes name the one rule that failed.
    """

    def __init__(
        self,
        code: str,
        message: str,
        missing_fields: tuple[ConstraintFieldKey, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.missing_fields = missing_fields


def missing_publish_fields(draft: ProjectConstraint) -> tuple[ConstraintFieldKey, ...]:
    """The Publish-required fields `draft` has not yet supplied, in contract order.

    Pure and never raises: this is the `missingFields` projection a reader is
    shown, not the gate. `CONSTRAINT_CODE` is never reported here because the
    code is allocated *by* Publish, not supplied before it.
    """
    missing: list[ConstraintFieldKey] = []
    if draft.project_id is None:
        missing.append(ConstraintFieldKey.PROJECT_ID)
    if draft.category_id is None:
        missing.append(ConstraintFieldKey.CATEGORY_ID)
    if draft.description is None or not draft.description.strip():
        missing.append(ConstraintFieldKey.DESCRIPTION)
    if draft.date_identified is None:
        missing.append(ConstraintFieldKey.DATE_IDENTIFIED)
    if draft.due_date is None:
        missing.append(ConstraintFieldKey.DUE_DATE)
    if not draft.bic:
        missing.append(ConstraintFieldKey.BIC)
    return tuple(missing)


def validate_publish_completeness(
    draft: ProjectConstraint,
    category: ConstraintCategory,
    initial_state: ConstraintLifecycleState = ConstraintLifecycleState.IDENTIFIED,
) -> None:
    """Refuse a normal Publish of `draft` unless every accepted precondition holds.

    Checks, in order: the record is a Draft of `NORMAL` quality; every
    required field is present (`constraint_publish_incomplete`); the Category
    is the one the Draft names, in the same Principal and Project partition,
    and `ACTIVE`; and `initial_state` is an active state. Allocating the code
    and writing the record are the caller's transaction, not this function's.
    """
    if draft.lifecycle_state is not ConstraintLifecycleState.DRAFT:
        raise ConstraintPublishError(
            "constraint_publish_not_draft", "only a DRAFT can be published"
        )
    if draft.record_quality is not ConstraintRecordQuality.NORMAL:
        raise ConstraintPublishError(
            "constraint_publish_quality_not_normal",
            "a normal Publish requires NORMAL record quality",
        )
    missing = missing_publish_fields(draft)
    if missing:
        raise ConstraintPublishError(
            "constraint_publish_incomplete",
            "publish requires: " + ", ".join(key.value for key in missing),
            missing,
        )
    if (
        category.category_id != draft.category_id
        or category.principal_id != draft.principal_id
        or category.project_id != draft.project_id
    ):
        raise ConstraintPublishError(
            "constraint_publish_category_partition_mismatch",
            "the category must be the draft's own, in the same Principal and Project",
        )
    if category.state is not ConstraintCategoryState.ACTIVE:
        raise ConstraintPublishError(
            "constraint_publish_category_not_active", "publish requires an ACTIVE category"
        )
    if initial_state not in ACTIVE_CONSTRAINT_LIFECYCLE_STATES:
        raise ConstraintPublishError(
            "constraint_publish_state_not_active",
            f"the initial published state must be active, not {initial_state.value}",
        )


def in_my_court(
    lifecycle_state: ConstraintLifecycleState,
    bic: tuple[PartyRef, ...],
    principal_bound_entity_ids: frozenset[str] = frozenset(),
) -> bool:
    """Whether the owning Principal is the one this Constraint is waiting on.

    True iff the state is active and BIC explicitly contains `PRINCIPAL`, or
    contains an `ENTITY` whose id is in `principal_bound_entity_ids` — a set
    the caller has *proven* through a later authoritative repository binding.
    This function does no lookup and no label, name, or email comparison;
    `UNRESOLVED` parties never count, whatever their wording.
    """
    if lifecycle_state not in ACTIVE_CONSTRAINT_LIFECYCLE_STATES:
        return False
    for party in bic:
        if party.kind is PartyKind.PRINCIPAL:
            return True
        if party.kind is PartyKind.ENTITY and party.entity_id in principal_bound_entity_ids:
            return True
    return False
