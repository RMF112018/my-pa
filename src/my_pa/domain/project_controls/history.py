"""One append-only mutation receipt per Constraint write, and one per Category write.

PC-CM-IMP-WP02. `ConstraintHistoryEntry` is the domain half of
`knowledge.project_constraint_history` and `ConstraintCategoryHistoryEntry` the
domain half of `knowledge.constraint_category_history`: a record that a mutation
was *attempted*, what version the record was at before and after, who asked, and
what happened — never the caller's raw request. There is no payload column and
no place for one: `client_context` is a short closed-shape client label and
`safe_failure_reason` is a bounded, already-safe refusal label, which is what
`AGENTS.md` section 5 requires of a log of this kind (CM-BE-AC-067).

The three vocabularies here are this plane's own. They are deliberately *not*
imported from `domain.task.history`, even where the members coincide: the
Constraint plane does not depend on the Task plane, and a shared enum would make
one plane's vocabulary change the other's stored CHECK. `ConstraintMutationOperation`
is the five lifecycle operations of `constraint.py` plus `create` and `update`;
category mutations get their own three-member operation vocabulary because a
Category is never published, closed, or voided.

**Idempotency is optional and scoped per Principal**, the shape
`task_history` and `commitment_history` already use: a mutation carrying no
`idempotency_key` is simply not replay-protected, and one that carries a key is
protected only against another mutation from the same Principal reusing it. The
two ledgers hold separate partial unique indexes, so a key is unique within a
ledger rather than across both.

**The version pairing is the receipt's whole point.** `APPLIED` requires
`after_version > before_version` *and* a `revision_id`: an applied Constraint
mutation that recorded no immutable snapshot is a claim the revision ledger
cannot corroborate. `REJECTED` and `NO_OP` record no version change and no
revision, and only `REJECTED` may carry a `safe_failure_reason`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "CONSTRAINT_IDEMPOTENCY_KEY_PATTERN",
    "MAX_CONSTRAINT_CLIENT_CONTEXT_CHARACTERS",
    "MAX_CONSTRAINT_FAILURE_REASON_CHARACTERS",
    "ConstraintCategoryHistoryEntry",
    "ConstraintCategoryMutationOperation",
    "ConstraintHistoryEntry",
    "ConstraintHistoryError",
    "ConstraintMutationActor",
    "ConstraintMutationOperation",
    "ConstraintMutationOutcome",
]

#: Opaque and bounded, the same shape `task_history.idempotency_key` restates:
#: never a value a request body could smuggle meaning through.
CONSTRAINT_IDEMPOTENCY_KEY_PATTERN: Final = re.compile(r"\A[A-Za-z0-9_-]{8,128}\Z")

#: A client label, not a request. Bounded well below anything a body could fit.
MAX_CONSTRAINT_CLIENT_CONTEXT_CHARACTERS: Final = 128

#: A refusal label that has already been made safe for the caller who asked.
MAX_CONSTRAINT_FAILURE_REASON_CHARACTERS: Final = 128

_SHA256_HEX: Final = re.compile(r"\A[0-9a-f]{64}\Z")


class ConstraintHistoryError(ValueError):
    """A mutation receipt violated a structural invariant. `code` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConstraintMutationOperation(StrEnum):
    """What this build normalised a Constraint mutation request into.

    The five lifecycle operations `ConstraintLifecycleOperation` names, plus
    `create` (a record came into existence) and `update` (a field write that
    moved no state). Closed, so a reader of the ledger can say what happened
    without diffing two revisions.
    """

    CLOSE = "close"
    CREATE = "create"
    PUBLISH = "publish"
    REOPEN = "reopen"
    TRANSITION = "transition"
    UPDATE = "update"
    VOID = "void"


class ConstraintCategoryMutationOperation(StrEnum):
    """What a Category mutation was. Three: a Category is never published or closed."""

    ARCHIVE = "archive"
    CREATE = "create"
    UPDATE = "update"


class ConstraintMutationActor(StrEnum):
    """Who or what asked for the mutation, closed to the three kinds this build has."""

    PRINCIPAL = "principal"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ConstraintMutationOutcome(StrEnum):
    """What became of the mutation, once this build finished interpreting it."""

    APPLIED = "applied"
    NO_OP = "no_op"
    REJECTED = "rejected"


def _check_versions(
    outcome: ConstraintMutationOutcome, before_version: int, after_version: int
) -> None:
    if before_version < 0:
        raise ConstraintHistoryError(
            "constraint_history_before_version_negative",
            "a mutation receipt records a non-negative before-version",
        )
    if outcome is ConstraintMutationOutcome.APPLIED:
        if after_version <= before_version:
            raise ConstraintHistoryError(
                "constraint_history_applied_without_advance",
                "an applied mutation advances the version it recorded",
            )
    elif after_version != before_version:
        raise ConstraintHistoryError(
            "constraint_history_unapplied_advanced",
            "a rejected or no-op mutation records no version change",
        )


def _check_safe_fields(
    outcome: ConstraintMutationOutcome,
    *,
    idempotency_key: str | None,
    request_digest: str | None,
    client_context: str | None,
    safe_failure_reason: str | None,
) -> None:
    if idempotency_key is not None and not CONSTRAINT_IDEMPOTENCY_KEY_PATTERN.fullmatch(
        idempotency_key
    ):
        raise ConstraintHistoryError(
            "constraint_history_idempotency_key_malformed",
            "an idempotency key is 8-128 characters of [A-Za-z0-9_-]",
        )
    if request_digest is not None and not _SHA256_HEX.fullmatch(request_digest):
        raise ConstraintHistoryError(
            "constraint_history_request_digest_malformed",
            "a request digest is a lowercase SHA-256 hex value",
        )
    if client_context is not None:
        stripped = client_context.strip()
        if not stripped:
            raise ConstraintHistoryError(
                "constraint_history_client_context_blank",
                "client context is non-blank when present",
            )
        if len(stripped) > MAX_CONSTRAINT_CLIENT_CONTEXT_CHARACTERS:
            raise ConstraintHistoryError(
                "constraint_history_client_context_too_long",
                "client context exceeds the stored bound",
            )
    if safe_failure_reason is None:
        return
    if outcome is not ConstraintMutationOutcome.REJECTED:
        raise ConstraintHistoryError(
            "constraint_history_reason_without_rejection",
            "only a rejected mutation carries a failure reason",
        )
    reason = safe_failure_reason.strip()
    if not reason:
        raise ConstraintHistoryError(
            "constraint_history_reason_blank",
            "a failure reason is non-blank when present",
        )
    if len(reason) > MAX_CONSTRAINT_FAILURE_REASON_CHARACTERS:
        raise ConstraintHistoryError(
            "constraint_history_reason_too_long",
            "a failure reason exceeds the stored bound",
        )


@dataclass(frozen=True, slots=True)
class ConstraintHistoryEntry:
    """One append-only row of `knowledge.project_constraint_history`.

    `before_version`/`after_version` are the Constraint's `version` column read
    before and after the attempt; `revision_id` names the immutable snapshot the
    applied mutation wrote, and is present exactly when the outcome is
    `APPLIED`.
    """

    history_id: str
    principal_id: str
    constraint_id: str
    operation: ConstraintMutationOperation
    actor: ConstraintMutationActor
    outcome: ConstraintMutationOutcome
    before_version: int
    after_version: int
    occurred_at: datetime
    recorded_at: datetime
    project_id: str | None = None
    revision_id: str | None = None
    idempotency_key: str | None = None
    request_digest: str | None = None
    client_context: str | None = None
    correlation_id: str | None = None
    safe_failure_reason: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.history_id, IdKind.PROJECT_CONSTRAINT_HISTORY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.constraint_id, IdKind.PROJECT_CONSTRAINT)
        if self.project_id is not None:
            validate_identifier(self.project_id, IdKind.PROJECT)
        if self.revision_id is not None:
            validate_identifier(self.revision_id, IdKind.PROJECT_CONSTRAINT_REVISION)
        if self.correlation_id is not None:
            validate_identifier(self.correlation_id, IdKind.CORRELATION)
        if not isinstance(self.operation, ConstraintMutationOperation):
            raise ConstraintHistoryError(
                "constraint_history_operation_unknown",
                "a constraint mutation receipt names one known operation",
            )
        if not isinstance(self.actor, ConstraintMutationActor):
            raise ConstraintHistoryError(
                "constraint_history_actor_unknown",
                "a constraint mutation receipt names one known actor",
            )
        if not isinstance(self.outcome, ConstraintMutationOutcome):
            raise ConstraintHistoryError(
                "constraint_history_outcome_unknown",
                "a constraint mutation receipt names one known outcome",
            )
        _check_versions(self.outcome, self.before_version, self.after_version)
        if (self.outcome is ConstraintMutationOutcome.APPLIED) != (self.revision_id is not None):
            raise ConstraintHistoryError(
                "constraint_history_revision_pairing",
                "an applied mutation names its revision, and only an applied one does",
            )
        _check_safe_fields(
            self.outcome,
            idempotency_key=self.idempotency_key,
            request_digest=self.request_digest,
            client_context=self.client_context,
            safe_failure_reason=self.safe_failure_reason,
        )
        object.__setattr__(self, "occurred_at", ensure_utc(self.occurred_at))
        object.__setattr__(self, "recorded_at", ensure_utc(self.recorded_at))


@dataclass(frozen=True, slots=True)
class ConstraintCategoryHistoryEntry:
    """One append-only row of `knowledge.constraint_category_history`.

    The same receipt shape as `ConstraintHistoryEntry` over a Category, with two
    differences the stored table makes too: a Category is always Project-bound,
    so `project_id` is required; and there is no Category revision ledger, so no
    `revision_id` is recorded (a deliberate WP02 limitation, not an omission).
    """

    history_id: str
    principal_id: str
    project_id: str
    category_id: str
    operation: ConstraintCategoryMutationOperation
    actor: ConstraintMutationActor
    outcome: ConstraintMutationOutcome
    before_version: int
    after_version: int
    occurred_at: datetime
    recorded_at: datetime
    idempotency_key: str | None = None
    request_digest: str | None = None
    client_context: str | None = None
    correlation_id: str | None = None
    safe_failure_reason: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.history_id, IdKind.CONSTRAINT_CATEGORY_HISTORY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.project_id, IdKind.PROJECT)
        validate_identifier(self.category_id, IdKind.CONSTRAINT_CATEGORY)
        if self.correlation_id is not None:
            validate_identifier(self.correlation_id, IdKind.CORRELATION)
        if not isinstance(self.operation, ConstraintCategoryMutationOperation):
            raise ConstraintHistoryError(
                "constraint_category_history_operation_unknown",
                "a category mutation receipt names one known operation",
            )
        if not isinstance(self.actor, ConstraintMutationActor):
            raise ConstraintHistoryError(
                "constraint_category_history_actor_unknown",
                "a category mutation receipt names one known actor",
            )
        if not isinstance(self.outcome, ConstraintMutationOutcome):
            raise ConstraintHistoryError(
                "constraint_category_history_outcome_unknown",
                "a category mutation receipt names one known outcome",
            )
        _check_versions(self.outcome, self.before_version, self.after_version)
        _check_safe_fields(
            self.outcome,
            idempotency_key=self.idempotency_key,
            request_digest=self.request_digest,
            client_context=self.client_context,
            safe_failure_reason=self.safe_failure_reason,
        )
        object.__setattr__(self, "occurred_at", ensure_utc(self.occurred_at))
        object.__setattr__(self, "recorded_at", ensure_utc(self.recorded_at))
