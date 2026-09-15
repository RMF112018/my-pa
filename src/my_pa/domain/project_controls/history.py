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

PC-CM-RUN01-WP05 adds a third, narrower receipt at the end of this module:
`ConstraintProjectSettingsHistoryEntry`, over one Project's Constraint settings
and the single `configure` action. It is scoped like `ProjectHistoryEntry`
rather than like the two receipts above, and it is not a second Project
mutation plane — see the section comment there for why it has to exist at all.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.project_controls.settings import MAX_PROJECT_TIMEZONE_NAME_CHARACTERS

__all__ = [
    "CONSTRAINT_IDEMPOTENCY_KEY_PATTERN",
    "CONSTRAINT_PROJECT_SETTINGS_ACTION",
    "CONSTRAINT_PROJECT_SETTINGS_HISTORY_ID_PATTERN",
    "MAX_CONSTRAINT_CLIENT_CONTEXT_CHARACTERS",
    "MAX_CONSTRAINT_FAILURE_REASON_CHARACTERS",
    "MAX_SETTINGS_FAILURE_DETAIL_CHARACTERS",
    "ConstraintCategoryHistoryEntry",
    "ConstraintCategoryMutationOperation",
    "ConstraintHistoryEntry",
    "ConstraintHistoryError",
    "ConstraintMutationActor",
    "ConstraintMutationOperation",
    "ConstraintMutationOutcome",
    "ConstraintProjectSettingsHistoryEntry",
    "ConstraintProjectSettingsHistoryError",
    "ConstraintProjectSettingsHistoryKeyConflictError",
    "ConstraintProjectSettingsOutcome",
    "issue_settings_history_id",
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


# --- Explicit Project Controls settings configuration ----------------------
#
# PC-CM-RUN01-WP05. `ConstraintProjectSettingsHistoryEntry` is the domain half
# of `knowledge.constraint_project_settings_history`, and it exists for exactly
# one reason the settings row itself cannot serve: `constraint_project_settings`
# holds only the *current* timezone and version, so a replayed configure request
# has nothing to reconstruct its original answer from. This ledger is that
# reconstruction and nothing more.
#
# It is deliberately **not** a second Project mutation plane. Project identity,
# Project version, and the generic Project receipt stay owned by `projects` and
# `domain.situation.project_history`; this model is scoped to the single
# `configure` action over one Project's Constraint settings, modelled narrowly
# on `ProjectHistoryEntry` rather than on the wide Constraint receipt above.
# That is also why `action` is a column with one legal value instead of an enum
# of operations: there is one operation, and a second one would be a new design
# decision rather than a new member.
#
# Every invariant below restates a landed CHECK from revision `e6a4c2f91b73`, in
# domain code, on purpose: the pairing rules are the ledger's whole meaning, and
# a rule provable only against PostgreSQL is a rule no FAST test can hold the
# service to. The database remains the authority; this is the same authority
# said twice so both halves can be relied on.


class ConstraintProjectSettingsHistoryError(ValueError):
    """A settings-configuration receipt violated a structural invariant. `code` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConstraintProjectSettingsHistoryKeyConflictError(Exception):
    """This Principal already bound that idempotency key to a settings configure.

    Raised by persistence in place of the raw `IntegrityError` that
    `constraint_settings_history_idempotency_is_unique_per_principal` produces,
    so the service can re-read the stored receipt and decide replay versus
    conflict without importing SQLAlchemy or parsing a driver message. It says
    only that the key is taken; whether the stored request was the *same*
    request is the digest's answer, read from the row, not this exception's.
    """

    code: Final = "constraint_settings_history_idempotency_key_taken"


class ConstraintProjectSettingsOutcome(StrEnum):
    """What became of one configure attempt. The stored CHECK's three literals.

    A separate vocabulary from `ConstraintMutationOutcome` even though the three
    members coincide, for the reason the module docstring already gives: two
    tables hold two CHECKs, and a shared enum would make one table's vocabulary
    change the other's.
    """

    APPLIED = "applied"
    NO_OP = "no_op"
    REJECTED = "rejected"


#: The stored `action` CHECK: one operation, spelled once.
CONSTRAINT_PROJECT_SETTINGS_ACTION: Final = "configure"

#: `^cpsh_[A-Za-z0-9]{8,64}$`, the stored primary-key CHECK. Spelled here rather
#: than reached through `IdKind`, because `cpsh` is not a contract-v1 identifier
#: kind and inventing one would be a `contracts` change this package does not own.
CONSTRAINT_PROJECT_SETTINGS_HISTORY_ID_PATTERN: Final = re.compile(r"\Acpsh_[A-Za-z0-9]{8,64}\Z")

#: The stored `failure_code` CHECK: a stable machine label, never a message.
_FAILURE_CODE: Final = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z")

#: The stored `failure_detail` bound. Wider than the Constraint receipt's
#: `safe_failure_reason` because the landed column says 256, not 128.
MAX_SETTINGS_FAILURE_DETAIL_CHARACTERS: Final = 256


def issue_settings_history_id() -> str:
    """A fresh `cpsh_` receipt identifier, from a non-semantic source.

    The same discipline `source.registry.issue_identifier` states and for the
    same reason — it takes no subject argument, so it cannot encode one — but
    spelled here because `cpsh` is not an `IdKind` and `make_identifier` would
    refuse it.
    """
    return f"cpsh_{secrets.token_hex(16)}"


def _check_settings_outcome_pairing(
    outcome: ConstraintProjectSettingsOutcome,
    *,
    before_settings_version: int | None,
    after_settings_version: int | None,
) -> None:
    """The three stored version-pairing CHECKs, said once each."""
    for label, version in (
        ("before", before_settings_version),
        ("after", after_settings_version),
    ):
        if version is not None and version < 1:
            raise ConstraintProjectSettingsHistoryError(
                f"constraint_settings_history_{label}_version_not_positive",
                f"a recorded {label}-version is null or a positive integer",
            )
    if outcome is ConstraintProjectSettingsOutcome.APPLIED:
        # `an_applied_constraint_settings_change_advances_its_version`: an
        # absent settings row is version 0, so the first configure writes 1.
        if after_settings_version != (before_settings_version or 0) + 1:
            raise ConstraintProjectSettingsHistoryError(
                "constraint_settings_history_applied_without_advance",
                "an applied configure advances the settings version by exactly one",
            )
    elif outcome is ConstraintProjectSettingsOutcome.NO_OP:
        # `a_no_op_constraint_settings_change_preserves_its_version`: a no-op
        # answered an existing row, so both versions are present and equal.
        if before_settings_version is None or after_settings_version != before_settings_version:
            raise ConstraintProjectSettingsHistoryError(
                "constraint_settings_history_no_op_changed_version",
                "a no-op configure preserves the settings version it read",
            )
    elif after_settings_version != before_settings_version:
        # `a_rejected_constraint_settings_change_writes_no_new_version`, which
        # the stored CHECK spells `IS NOT DISTINCT FROM` so that a rejection
        # against no settings row (null, null) is as legal as one against a row.
        raise ConstraintProjectSettingsHistoryError(
            "constraint_settings_history_rejected_advanced",
            "a rejected configure writes no new settings version",
        )


def _check_settings_snapshot(
    outcome: ConstraintProjectSettingsOutcome,
    *,
    resulting_timezone_name: str | None,
    resulting_settings_updated_at: datetime | None,
) -> None:
    """`a_successful_constraint_settings_change_records_its_snapshot`.

    A succeeded configure — applied or no-op — is the only kind that can be
    replayed into an answer, so it is the only kind that stores one; a rejection
    has no settings state to report and must store neither half.
    """
    succeeded = outcome is not ConstraintProjectSettingsOutcome.REJECTED
    if succeeded != (resulting_timezone_name is not None) or succeeded != (
        resulting_settings_updated_at is not None
    ):
        raise ConstraintProjectSettingsHistoryError(
            "constraint_settings_history_snapshot_pairing",
            "a succeeded configure records its resulting timezone and timestamp, "
            "and only a succeeded one does",
        )
    if resulting_timezone_name is None:
        return
    if not resulting_timezone_name.strip():
        raise ConstraintProjectSettingsHistoryError(
            "constraint_settings_history_timezone_blank",
            "a recorded resulting timezone is non-blank",
        )
    if len(resulting_timezone_name) > MAX_PROJECT_TIMEZONE_NAME_CHARACTERS:
        raise ConstraintProjectSettingsHistoryError(
            "constraint_settings_history_timezone_too_long",
            "a recorded resulting timezone exceeds the stored bound",
        )
    if any(character.isspace() for character in resulting_timezone_name):
        raise ConstraintProjectSettingsHistoryError(
            "constraint_settings_history_timezone_has_whitespace",
            "a recorded resulting timezone carries no whitespace",
        )


def _check_settings_failure(
    outcome: ConstraintProjectSettingsOutcome,
    *,
    failure_code: str | None,
    failure_detail: str | None,
) -> None:
    """`only_a_rejected…records_failure` and `failure_detail_belongs_only_to_a_rejected…`."""
    rejected = outcome is ConstraintProjectSettingsOutcome.REJECTED
    if rejected != (failure_code is not None):
        raise ConstraintProjectSettingsHistoryError(
            "constraint_settings_history_failure_code_pairing",
            "a rejected configure names its failure code, and only a rejected one does",
        )
    if failure_code is not None and not _FAILURE_CODE.fullmatch(failure_code):
        raise ConstraintProjectSettingsHistoryError(
            "constraint_settings_history_failure_code_malformed",
            "a failure code is a stable lowercase machine label",
        )
    if failure_detail is None:
        return
    if not rejected:
        raise ConstraintProjectSettingsHistoryError(
            "constraint_settings_history_detail_without_rejection",
            "only a rejected configure carries a failure detail",
        )
    detail = failure_detail.strip()
    if not detail:
        raise ConstraintProjectSettingsHistoryError(
            "constraint_settings_history_detail_blank",
            "a failure detail is non-blank when present",
        )
    if len(detail) > MAX_SETTINGS_FAILURE_DETAIL_CHARACTERS:
        raise ConstraintProjectSettingsHistoryError(
            "constraint_settings_history_detail_too_long",
            "a failure detail exceeds the stored bound",
        )


@dataclass(frozen=True, slots=True)
class ConstraintProjectSettingsHistoryEntry:
    """One append-only row of `knowledge.constraint_project_settings_history`.

    `before_settings_version`/`after_settings_version` are
    `constraint_project_settings.version` read before and after the attempt, and
    are null where no settings row existed to have one — which is why they are
    nullable here and `ConstraintHistoryEntry`'s are not.

    Unlike the Constraint receipt, `idempotency_key` and `request_digest` are
    **required**: this ledger exists to answer replays, and a row that cannot be
    found by key or compared by digest would occupy the table without serving
    its only purpose. The key is unique within the Principal, never globally.
    """

    history_id: str
    principal_id: str
    project_id: str
    actor: ConstraintMutationActor
    outcome: ConstraintProjectSettingsOutcome
    idempotency_key: str
    request_digest: str
    occurred_at: datetime
    recorded_at: datetime
    action: str = CONSTRAINT_PROJECT_SETTINGS_ACTION
    before_settings_version: int | None = None
    after_settings_version: int | None = None
    resulting_timezone_name: str | None = None
    resulting_settings_updated_at: datetime | None = None
    client_context: str | None = None
    correlation_id: str | None = None
    failure_code: str | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if not CONSTRAINT_PROJECT_SETTINGS_HISTORY_ID_PATTERN.fullmatch(self.history_id):
            raise ConstraintProjectSettingsHistoryError(
                "constraint_settings_history_id_malformed",
                "a settings receipt identifier is an opaque cpsh_ value",
            )
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.project_id, IdKind.PROJECT)
        if self.correlation_id is not None:
            validate_identifier(self.correlation_id, IdKind.CORRELATION)
        if self.action != CONSTRAINT_PROJECT_SETTINGS_ACTION:
            raise ConstraintProjectSettingsHistoryError(
                "constraint_settings_history_action_unknown",
                "the only settings action this build records is 'configure'",
            )
        if not isinstance(self.actor, ConstraintMutationActor):
            raise ConstraintProjectSettingsHistoryError(
                "constraint_settings_history_actor_unknown",
                "a settings receipt names one known actor",
            )
        if not isinstance(self.outcome, ConstraintProjectSettingsOutcome):
            raise ConstraintProjectSettingsHistoryError(
                "constraint_settings_history_outcome_unknown",
                "a settings receipt names one known outcome",
            )
        if not CONSTRAINT_IDEMPOTENCY_KEY_PATTERN.fullmatch(self.idempotency_key):
            raise ConstraintProjectSettingsHistoryError(
                "constraint_settings_history_idempotency_key_malformed",
                "an idempotency key is 8-128 characters of [A-Za-z0-9_-]",
            )
        if not _SHA256_HEX.fullmatch(self.request_digest):
            raise ConstraintProjectSettingsHistoryError(
                "constraint_settings_history_request_digest_malformed",
                "a request digest is a lowercase SHA-256 hex value",
            )
        if self.client_context is not None:
            context = self.client_context.strip()
            if not context:
                raise ConstraintProjectSettingsHistoryError(
                    "constraint_settings_history_client_context_blank",
                    "client context is non-blank when present",
                )
            if len(context) > MAX_CONSTRAINT_CLIENT_CONTEXT_CHARACTERS:
                raise ConstraintProjectSettingsHistoryError(
                    "constraint_settings_history_client_context_too_long",
                    "client context exceeds the stored bound",
                )
        _check_settings_outcome_pairing(
            self.outcome,
            before_settings_version=self.before_settings_version,
            after_settings_version=self.after_settings_version,
        )
        _check_settings_snapshot(
            self.outcome,
            resulting_timezone_name=self.resulting_timezone_name,
            resulting_settings_updated_at=self.resulting_settings_updated_at,
        )
        _check_settings_failure(
            self.outcome,
            failure_code=self.failure_code,
            failure_detail=self.failure_detail,
        )
        object.__setattr__(self, "occurred_at", ensure_utc(self.occurred_at))
        object.__setattr__(self, "recorded_at", ensure_utc(self.recorded_at))
        if self.resulting_settings_updated_at is not None:
            object.__setattr__(
                self,
                "resulting_settings_updated_at",
                ensure_utc(self.resulting_settings_updated_at),
            )
        # `settings_history_is_recorded_after_it_occurs`, checked last so it
        # compares two already-UTC instants rather than two offsets.
        if self.recorded_at < self.occurred_at:
            raise ConstraintProjectSettingsHistoryError(
                "constraint_settings_history_recorded_before_occurred",
                "a settings receipt is recorded no earlier than it occurred",
            )
