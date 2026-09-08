"""`ConstraintManagementService`: the one canonical way to mutate a Constraint.

PC-CM-IMP-WP06. WP01 built the domain (`domain.project_controls.constraint`,
`.category`, `.party`, `.business_time`), WP02 the persistence and the receipt
ledgers, WP03 the read plane. This module is the mutation plane between them:
the only place in the product that creates, publishes, updates, transitions,
closes, voids, or reopens a `ProjectConstraint`, or creates, updates,
deactivates or reorders a `ConstraintCategory`.

It is **internal**. It admits no Capability, defines no command, is wired into
no dispatcher, and reaches no transport: `ApplicationService` does not know it
exists, and making it reachable is a later work package's decision, not a side
effect of building it.

**Every mutation is one transaction.** `_mutate` is the single private
mechanism every Constraint method delegates to and `_mutate_category` its
Category sibling; each opens exactly one unit of work per call, or joins the
caller's through `active_uow`. The unit of work owns the boundary — nothing
here commits, and `infrastructure.persistence.unit_of_work` states the rule.
Inside one call the idempotency lookup, the row-locked read, the version
comparison, the domain `change`, the record write, the immutable revision and
the receipt all run together, so an attempt commits whole or leaves nothing.
There is deliberately no method that writes a Constraint row without also
writing the revision and receipt that attempt produced.

**Version is checked under the row lock and moves exactly once.** A record
starts at version 1, an `APPLIED` mutation advances it by one, a `NO_OP`
advances it by none, and a rejected `expected_version` advances it by none
either. `ConstraintVersionConflictError` is raised *after* the transaction
block closes, never inside it: raising inside would roll back the `REJECTED`
receipt that a stale-version refusal must still commit — the
`TaskVersionConflictError` precedent.

**Idempotency is bound to normalized request content, never to bytes.** The
digest is computed over the semantic values of the request (`_digest`), so key
order, whitespace in a serialization, or the shape of a transport payload
cannot change replay identity. A key this Principal has already used for the
same digest returns the original receipt with disposition `REPLAYED` and
executes nothing; the same key with a materially different digest is
`ConstraintIdempotencyConflictError` and executes nothing either.

**No generic status patch exists.** `transition_active` can only ask the domain
for `ConstraintLifecycleOperation.TRANSITION`, which `check_lifecycle_move`
refuses for every move into or out of `DRAFT` or a terminal state. Close, Void
and Reopen are separate named methods with their own field rules, and there is
no method here that takes a lifecycle state and applies it unconditionally.

**Legacy is unreachable from here.** No method accepts an `origin` or a
`record_quality`: every record this module creates is `PRODUCT` and `NORMAL`,
so an ordinary product mutation cannot manufacture the `LEGACY_INCOMPLETE`
shape that the accepted §17 import exception reserves for a workbook import
nobody has written yet. Nothing here repairs a missing legacy value either.

**Errors are plain module-local exceptions**, not `application.errors` codes —
the `TaskManagementService` and `CommitmentManagementService` shape. Nothing
here translates them into the public taxonomy, because nothing here is publicly
reachable; that translation belongs at the `ApplicationService.invoke` boundary
on the day a capability admits these operations. Domain failures
(`ConstraintLifecycleError`, `ConstraintInvariantError`, `ConstraintPublishError`,
`ConstraintCategoryError`, `ProjectTimezoneError`) propagate unchanged, and all
of them fire before this module has written anything.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Final, Protocol

from my_pa.contracts.ports import ConstraintManagementRepository, ConstraintManagementUnitOfWork
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import utc_now
from my_pa.domain.project_controls.business_time import default_due_date, project_today
from my_pa.domain.project_controls.category import (
    ConstraintCategory,
    ConstraintCategoryState,
    revise_category,
)
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleMove,
    ConstraintLifecycleOperation,
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintPublishError,
    ConstraintRecordQuality,
    ProjectConstraint,
    check_lifecycle_move,
    missing_publish_fields,
    validate_publish_completeness,
)
from my_pa.domain.project_controls.history import (
    CONSTRAINT_IDEMPOTENCY_KEY_PATTERN,
    ConstraintCategoryHistoryEntry,
    ConstraintCategoryMutationOperation,
    ConstraintHistoryEntry,
    ConstraintMutationActor,
    ConstraintMutationOperation,
    ConstraintMutationOutcome,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.read_models import (
    ConstraintCategoryRow,
    RelationshipDirection,
)
from my_pa.domain.project_controls.relationship import (
    ConstraintRelationship,
    ConstraintRelationshipType,
)
from my_pa.domain.project_controls.revision import ConstraintRevision
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "ConstraintCategoryMutationResult",
    "ConstraintCategoryNotFoundError",
    "ConstraintCategoryReorderResult",
    "ConstraintCategoryVersionConflictError",
    "ConstraintFollowUpResult",
    "ConstraintIdempotencyConflictError",
    "ConstraintManagementService",
    "ConstraintMutationDisposition",
    "ConstraintMutationResult",
    "ConstraintNotFoundError",
    "ConstraintOperationError",
    "ConstraintPartyError",
    "ConstraintProjectUnavailableError",
    "ConstraintReorderError",
    "ConstraintVersionConflictError",
]

#: The accepted public-code suffix rendering: a *minimum* width of two, so the
#: first code is `X.01`, the tenth `X.10`, and the hundredth `X.100` rather
#: than a truncated or zero-padded fixed-width value. The code is text at every
#: step — it is never parsed, compared, or stored as a number, which is what
#: keeps `1.10` from becoming `1.1`.
MINIMUM_CODE_SUFFIX_WIDTH: Final = 2

#: The fields a bounded update may set. Lifecycle is absent on purpose: it moves
#: only through the named operations. So are the published-identity fields of
#: the accepted §16 list, except while the record is still a Draft.
UPDATABLE_FIELDS: Final = frozenset(
    {
        "description",
        "date_identified",
        "due_date",
        "reference",
        "current_update",
        "bic",
        "responsible",
        "project_id",
        "category_id",
    }
)

#: Of those, the two that are identity after Publish and therefore changeable
#: only while the record is a Draft (CM-BE-AC-004).
DRAFT_ONLY_FIELDS: Final = frozenset({"project_id", "category_id"})

#: Fields a published record may not have removed: a normal Publish required
#: each of them, and an update that cleared one would leave a published record
#: in a shape Publish itself would have refused.
PUBLISH_REQUIRED_FIELDS: Final = frozenset({"description", "date_identified", "due_date"})


class ConstraintNotFoundError(Exception):
    """A mutation named a `constraint_id` absent from this Principal's partition.

    Absent and foreign are the same answer, so a caller learns nothing about
    another Principal's records from the shape of the refusal (CM-BE-AC-132).
    """


class ConstraintCategoryNotFoundError(Exception):
    """A mutation named a `category_id` absent from this Principal's partition."""


class ConstraintProjectUnavailableError(Exception):
    """The named Project is not one this Principal has Constraint settings for.

    Unconfigured and foreign are deliberately the same answer, exactly as the
    WP03 read plane already answers them.
    """


class ConstraintVersionConflictError(Exception):
    """`expected_version` did not match the Constraint's current version.

    Carries the record as it still stands and the `REJECTED` receipt the
    attempt produced. That receipt is written and committed before this is
    raised, so a caller that catches it can inspect exactly what was recorded.
    A rejected attempt has no disposition, because nothing is returned to a
    caller: it is raised, and `ConstraintMutationDisposition` has no member
    for it.
    """

    def __init__(self, record: ProjectConstraint, receipt: ConstraintHistoryEntry) -> None:
        super().__init__("the constraint's current version does not match expected_version")
        self.record = record
        self.receipt = receipt


class ConstraintCategoryVersionConflictError(Exception):
    """`expected_version` did not match a Category's current version.

    Carries every `REJECTED` Category receipt the attempt produced. A reorder
    that conflicts on one member rejects the whole reorder, so this may carry
    more than one.
    """

    def __init__(self, receipts: tuple[ConstraintCategoryHistoryEntry, ...]) -> None:
        super().__init__("the category's current version does not match expected_version")
        self.receipts = receipts


class ConstraintIdempotencyConflictError(Exception):
    """An idempotency key was reused for materially different normalized content."""


class ConstraintPartyError(ValueError):
    """A BIC or Responsible collection named a party this build cannot accept.

    `code` is stable. The only failure available is `constraint_party_entity_
    unavailable`: an `ENTITY` reference to an Entity that is not in this
    Principal's partition. It never says whether that Entity exists elsewhere,
    and no party is ever resolved by name, email, label, or substring.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConstraintOperationError(ValueError):
    """A named operation's own field rule refused the request. `code` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConstraintReorderError(ValueError):
    """A Category reorder did not name this Project's Categories exactly once each."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConstraintMutationDisposition(StrEnum):
    """What became of a mutation request, as its caller is told.

    Distinct from `ConstraintMutationOutcome`, which is what the *ledger*
    records: a replay writes no ledger row at all, so `REPLAYED` exists here
    and cannot exist there, and `REJECTED` exists there and never reaches a
    caller as a value — it arrives as a raised conflict carrying its receipt.
    """

    APPLIED = "applied"
    NO_OP = "no_op"
    REPLAYED = "replayed"


@dataclass(frozen=True, slots=True)
class ConstraintMutationResult:
    """The authoritative result of one Constraint mutation attempt.

    `record` is the Constraint as it now stands and `receipt` the ledger row
    that accounts for the attempt. Nothing downstream may synthesize any of
    these three values: disposition, version, public code, receipt and
    atomicity are decided here and nowhere else.
    """

    disposition: ConstraintMutationDisposition
    record: ProjectConstraint
    receipt: ConstraintHistoryEntry


@dataclass(frozen=True, slots=True)
class ConstraintCategoryMutationResult:
    """The authoritative result of one Category mutation attempt."""

    disposition: ConstraintMutationDisposition
    record: ConstraintCategory
    receipt: ConstraintCategoryHistoryEntry


@dataclass(frozen=True, slots=True)
class ConstraintCategoryReorderResult:
    """The result of one atomic reorder: every Category, in its new order.

    A reorder is one operation over the Project's whole ordered sequence, not a
    loop of independent updates, so its result is the whole sequence and its
    receipts are the whole set — all written in one transaction or none.
    """

    disposition: ConstraintMutationDisposition
    records: tuple[ConstraintCategory, ...]
    receipts: tuple[ConstraintCategoryHistoryEntry, ...]


@dataclass(frozen=True, slots=True)
class ConstraintFollowUpResult:
    """The result of Close + Follow-up: both records, both receipts, the edge.

    One operation, one transaction: the predecessor is closed, the successor is
    created, published and given its own public code, and the `FOLLOW_UP_OF`
    edge from successor to predecessor is written — all of it, or none of it.
    """

    disposition: ConstraintMutationDisposition
    predecessor: ProjectConstraint
    successor: ProjectConstraint
    predecessor_receipt: ConstraintHistoryEntry
    successor_receipt: ConstraintHistoryEntry
    relationship_id: str


class _ActiveConstraintUnitOfWork(Protocol):
    @property
    def constraints(self) -> ConstraintManagementRepository: ...


@dataclass(frozen=True, slots=True)
class _Mutation:
    """What a `change` closure is handed: the transaction, the row, the instant.

    The authenticated `principal_id` is deliberately **not** a field here: it
    is already the enclosing method's argument, every closure closes over it,
    and a second copy travelling in a context object is a value a future
    reader could mistake for one the request supplied.

    `change` may read and write through `uow` — Publish allocates a public code
    under the Category row lock, and that allocation has to happen inside the
    same transaction as the record write. A closure that writes must also
    return a record that differs from `current`, or the `NO_OP` branch would
    discard the record write while keeping the side effect; every closure here
    that writes changes the lifecycle state, so none can.
    """

    uow: _ActiveConstraintUnitOfWork
    current: ProjectConstraint | None
    now: datetime

    def existing(self) -> ProjectConstraint:
        """The row this mutation names, for the operations that name one."""
        if self.current is None:  # pragma: no cover - `_mutate` decides this
            raise RuntimeError("this operation names an existing constraint")
        return self.current


_Change = Callable[[_Mutation], ProjectConstraint]


@dataclass(frozen=True, slots=True)
class _CategoryMutation:
    """What a Category `change` closure is handed. The `_Mutation` sibling."""

    uow: _ActiveConstraintUnitOfWork
    current: ConstraintCategory | None
    now: datetime

    def existing(self) -> ConstraintCategory:
        """The row this mutation names, for the operations that name one."""
        if self.current is None:  # pragma: no cover - `_mutate_category` decides this
            raise RuntimeError("this operation names an existing category")
        return self.current


_CategoryChange = Callable[[_CategoryMutation], ConstraintCategory]


class ConstraintManagementService:
    """The one canonical entry point for mutating a Constraint or a Category."""

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], ConstraintManagementUnitOfWork],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    # --- Constraints -----------------------------------------------------

    def create_draft(
        self,
        *,
        principal_id: str,
        actor: ConstraintMutationActor,
        project_id: str | None = None,
        category_id: str | None = None,
        description: str | None = None,
        date_identified: date | None = None,
        due_date: date | None = None,
        reference: str | None = None,
        current_update: str | None = None,
        bic: Sequence[PartyRef] = (),
        responsible: Sequence[PartyRef] = (),
        idempotency_key: str | None = None,
        client_context: str | None = None,
        correlation_id: str | None = None,
        active_uow: _ActiveConstraintUnitOfWork | None = None,
    ) -> ConstraintMutationResult:
        """Create and save a Draft.

        The Draft receives an opaque `cst_` identity, version 1, and no public
        code — Publish allocates one, so a Draft consumes no permanent number
        (CM-BE-AC-005/026). It may be incomplete: description, dates, category
        and parties are all optional here, and `missing_publish_fields` is what
        reports the gap. Origin is always `PRODUCT` and quality always `NORMAL`.

        The Principal is the authenticated caller's, never a value from the
        request; naming a Project requires one this Principal has Constraint
        settings for, and naming a Category requires one of this Principal's,
        in that Project.
        """
        parties = (tuple(bic), tuple(responsible))

        def change(mutation: _Mutation) -> ProjectConstraint:
            if project_id is not None:
                self._require_project(mutation.uow, principal_id, project_id)
            if category_id is not None:
                self._require_category(mutation.uow, principal_id, category_id, project_id)
            self._validate_parties(mutation.uow, principal_id, parties[0] + parties[1])
            return ProjectConstraint(
                constraint_id=issue_identifier(IdKind.PROJECT_CONSTRAINT),
                principal_id=principal_id,
                lifecycle_state=ConstraintLifecycleState.DRAFT,
                origin=ConstraintOrigin.PRODUCT,
                created_at=mutation.now,
                updated_at=mutation.now,
                project_id=project_id,
                category_id=category_id,
                description=description,
                date_identified=date_identified,
                due_date=due_date,
                reference=reference,
                current_update=current_update,
                bic=parties[0],
                responsible=parties[1],
                record_quality=ConstraintRecordQuality.NORMAL,
            )

        return self._mutate(
            principal_id=principal_id,
            constraint_id=None,
            expected_version=None,
            operation=ConstraintMutationOperation.CREATE,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            correlation_id=correlation_id,
            request_digest=_digest(
                project_id=project_id,
                category_id=category_id,
                description=description,
                date_identified=date_identified,
                due_date=due_date,
                reference=reference,
                bic=_party_digest(parties[0]),
                responsible=_party_digest(parties[1]),
                target_state=ConstraintLifecycleState.DRAFT,
            ),
            change=change,
            active_uow=active_uow,
        )

    def publish(
        self,
        *,
        principal_id: str,
        constraint_id: str,
        expected_version: int,
        actor: ConstraintMutationActor,
        target_state: ConstraintLifecycleState = ConstraintLifecycleState.IDENTIFIED,
        category_id: str | None = None,
        date_identified: date | None = None,
        due_date: date | None = None,
        bic: Sequence[PartyRef] | None = None,
        responsible: Sequence[PartyRef] | None = None,
        idempotency_key: str | None = None,
        client_context: str | None = None,
        correlation_id: str | None = None,
        active_uow: _ActiveConstraintUnitOfWork | None = None,
        digest_override: str | None = None,
    ) -> ConstraintMutationResult:
        """Publish a Draft: allocate its public code and give it an active state.

        The order is the contract. Resolve the accepted defaults (state
        `IDENTIFIED`; Date Identified `projectToday`; Due `+10` business days),
        lock the Category allocator row, validate every Publish precondition
        against the *resolved* record, allocate the next code under that lock,
        lock the prefix, and only then write the record, its first published
        revision and its receipt — all in the one transaction `_mutate` owns,
        so a Publish that fails anywhere consumes no number.

        A default that needs the Project calendar fails closed when no calendar
        is configured; explicitly supplied dates need none.
        """
        requested_bic = None if bic is None else tuple(bic)
        requested_responsible = None if responsible is None else tuple(responsible)

        def change(mutation: _Mutation) -> ProjectConstraint:
            current = mutation.existing()
            candidate = self._resolve_publication(
                mutation,
                principal_id,
                current,
                category_id=category_id,
                date_identified=date_identified,
                due_date=due_date,
                bic=requested_bic,
                responsible=requested_responsible,
            )
            category = self._locked_category(mutation.uow, principal_id, candidate)
            validate_publish_completeness(candidate, category, target_state)
            check_lifecycle_move(
                current.lifecycle_state, target_state, ConstraintLifecycleOperation.PUBLISH
            )
            self._validate_parties(
                mutation.uow, principal_id, candidate.bic + candidate.responsible
            )
            code = self._allocate_code(mutation.uow, principal_id, category, mutation.now)
            return dataclasses.replace(
                candidate,
                lifecycle_state=target_state,
                constraint_code=code,
                published_at=mutation.now,
            )

        return self._mutate(
            principal_id=principal_id,
            constraint_id=constraint_id,
            expected_version=expected_version,
            operation=ConstraintMutationOperation.PUBLISH,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            correlation_id=correlation_id,
            request_digest=_digest(
                constraint_id=constraint_id,
                expected_version=expected_version,
                target_state=target_state,
                date_identified=date_identified,
                due_date=due_date,
                bic=None if requested_bic is None else _party_digest(requested_bic),
                responsible=(
                    None if requested_responsible is None else _party_digest(requested_responsible)
                ),
                category_id=category_id,
            ),
            change=change,
            active_uow=active_uow,
            digest_override=digest_override,
        )

    def update(
        self,
        *,
        principal_id: str,
        constraint_id: str,
        expected_version: int,
        actor: ConstraintMutationActor,
        values: Mapping[str, object] | None = None,
        clear_fields: frozenset[str] = frozenset(),
        idempotency_key: str | None = None,
        client_context: str | None = None,
        correlation_id: str | None = None,
        active_uow: _ActiveConstraintUnitOfWork | None = None,
    ) -> ConstraintMutationResult:
        """Apply one bounded patch under one row lock and one receipt.

        Bounded in three ways at once. `UPDATABLE_FIELDS` is the whole set an
        update may touch, so lifecycle can only move through its named
        operations; `DRAFT_ONLY_FIELDS` are the published-identity fields that
        stop being writable the moment a code is issued (CM-BE-AC-004); and
        `PUBLISH_REQUIRED_FIELDS` may not be cleared from a published record,
        because Publish itself would have refused a record without them.

        A patch that changes nothing is a `NO_OP`: it writes a receipt, no
        revision, and does not advance the version.
        """
        patch = dict(values or {})
        if unknown := (set(patch) | set(clear_fields)) - UPDATABLE_FIELDS:
            raise ConstraintOperationError(
                "constraint_update_field_unknown",
                f"not updatable constraint fields: {sorted(unknown)!r}",
            )
        if overlap := set(patch) & set(clear_fields):
            raise ConstraintOperationError(
                "constraint_update_field_set_and_cleared",
                f"a field cannot be both set and cleared: {sorted(overlap)!r}",
            )

        def change(mutation: _Mutation) -> ProjectConstraint:
            current = mutation.existing()
            touched = set(patch) | set(clear_fields)
            is_draft = current.lifecycle_state is ConstraintLifecycleState.DRAFT
            if not is_draft and (frozen := touched & DRAFT_ONLY_FIELDS):
                raise ConstraintOperationError(
                    "constraint_published_identity_immutable",
                    f"a published constraint's {sorted(frozen)!r} is immutable",
                )
            if not is_draft and (emptied := set(clear_fields) & PUBLISH_REQUIRED_FIELDS):
                raise ConstraintOperationError(
                    "constraint_published_field_required",
                    f"a published constraint keeps {sorted(emptied)!r}",
                )
            replacements: dict[str, Any] = {
                field: (_parties(value) if field in {"bic", "responsible"} else value)
                for field, value in patch.items()
            }
            replacements.update(dict.fromkeys(clear_fields))
            proposed = dataclasses.replace(current, **replacements)
            if "project_id" in touched or "category_id" in touched:
                if proposed.project_id is not None:
                    self._require_project(mutation.uow, principal_id, proposed.project_id)
                if proposed.category_id is not None:
                    self._require_category(
                        mutation.uow, principal_id, proposed.category_id, proposed.project_id
                    )
            if touched & {"bic", "responsible"}:
                self._validate_parties(
                    mutation.uow, principal_id, proposed.bic + proposed.responsible
                )
            return proposed

        return self._mutate(
            principal_id=principal_id,
            constraint_id=constraint_id,
            expected_version=expected_version,
            operation=ConstraintMutationOperation.UPDATE,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            correlation_id=correlation_id,
            request_digest=_digest(
                constraint_id=constraint_id,
                expected_version=expected_version,
                values=_normalized_patch(patch),
                clear_fields=sorted(clear_fields),
            ),
            change=change,
            active_uow=active_uow,
        )

    def transition_active(
        self,
        *,
        principal_id: str,
        constraint_id: str,
        target_state: ConstraintLifecycleState,
        expected_version: int,
        actor: ConstraintMutationActor,
        idempotency_key: str | None = None,
        client_context: str | None = None,
        correlation_id: str | None = None,
        active_uow: _ActiveConstraintUnitOfWork | None = None,
    ) -> ConstraintMutationResult:
        """Move an active Constraint to another active state.

        The only lifecycle operation this method can ask for is
        `TRANSITION`, so `check_lifecycle_move` refuses every crossing the
        matrix reserves for Publish, Close, Void or Reopen — including the
        prohibited active→DRAFT — and this is therefore not a generic status
        patch by construction. Asking for the state the record already holds is
        the accepted `NO_OP`.
        """

        def change(mutation: _Mutation) -> ProjectConstraint:
            current = mutation.existing()
            move = check_lifecycle_move(
                current.lifecycle_state, target_state, ConstraintLifecycleOperation.TRANSITION
            )
            if move is ConstraintLifecycleMove.NO_OP:
                return current
            return dataclasses.replace(current, lifecycle_state=target_state)

        return self._mutate(
            principal_id=principal_id,
            constraint_id=constraint_id,
            expected_version=expected_version,
            operation=ConstraintMutationOperation.TRANSITION,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            correlation_id=correlation_id,
            request_digest=_digest(
                constraint_id=constraint_id,
                expected_version=expected_version,
                target_state=target_state,
            ),
            change=change,
            active_uow=active_uow,
        )

    def close(
        self,
        *,
        principal_id: str,
        constraint_id: str,
        expected_version: int,
        actor: ConstraintMutationActor,
        completion_date: date | None = None,
        closure_commentary: str | None = None,
        idempotency_key: str | None = None,
        client_context: str | None = None,
        correlation_id: str | None = None,
        active_uow: _ActiveConstraintUnitOfWork | None = None,
        digest_override: str | None = None,
    ) -> ConstraintMutationResult:
        """Close an active Constraint: successful resolution, with its completion date.

        `completion_date` defaults to the Project's own calendar date when
        omitted, which fails closed if that Project has no configured calendar.
        The VOID-only fields are cleared rather than merely left alone, and the
        aggregate refuses the record if either survives.
        """

        def change(mutation: _Mutation) -> ProjectConstraint:
            current = mutation.existing()
            check_lifecycle_move(
                current.lifecycle_state,
                ConstraintLifecycleState.CLOSED,
                ConstraintLifecycleOperation.CLOSE,
            )
            completed = completion_date or self._project_today(
                mutation.uow, principal_id, current.project_id, mutation.now
            )
            return dataclasses.replace(
                current,
                lifecycle_state=ConstraintLifecycleState.CLOSED,
                completion_date=completed,
                closure_commentary=closure_commentary,
                voided_date=None,
                void_reason=None,
            )

        return self._mutate(
            principal_id=principal_id,
            constraint_id=constraint_id,
            expected_version=expected_version,
            operation=ConstraintMutationOperation.CLOSE,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            correlation_id=correlation_id,
            request_digest=_digest(
                constraint_id=constraint_id,
                expected_version=expected_version,
                completion_date=completion_date,
                closure_commentary=closure_commentary,
            ),
            change=change,
            active_uow=active_uow,
            digest_override=digest_override,
        )

    def void(
        self,
        *,
        principal_id: str,
        constraint_id: str,
        expected_version: int,
        actor: ConstraintMutationActor,
        void_reason: str,
        voided_date: date | None = None,
        idempotency_key: str | None = None,
        client_context: str | None = None,
        correlation_id: str | None = None,
        active_uow: _ActiveConstraintUnitOfWork | None = None,
    ) -> ConstraintMutationResult:
        """Void an active Constraint: it will not happen, and this is why.

        VOID is not completion. A non-blank reason is required, the voided date
        defaults to the Project calendar date, and `completion_date` is cleared
        and refused by the aggregate — the two terminal states carry disjoint
        fields so that a reader can never mistake one for the other.
        """
        if not void_reason.strip():
            raise ConstraintOperationError(
                "constraint_void_reason_blank", "voiding a constraint requires a reason"
            )

        def change(mutation: _Mutation) -> ProjectConstraint:
            current = mutation.existing()
            check_lifecycle_move(
                current.lifecycle_state,
                ConstraintLifecycleState.VOID,
                ConstraintLifecycleOperation.VOID,
            )
            voided = voided_date or self._project_today(
                mutation.uow, principal_id, current.project_id, mutation.now
            )
            return dataclasses.replace(
                current,
                lifecycle_state=ConstraintLifecycleState.VOID,
                voided_date=voided,
                void_reason=void_reason,
                completion_date=None,
                closure_commentary=None,
            )

        return self._mutate(
            principal_id=principal_id,
            constraint_id=constraint_id,
            expected_version=expected_version,
            operation=ConstraintMutationOperation.VOID,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            correlation_id=correlation_id,
            request_digest=_digest(
                constraint_id=constraint_id,
                expected_version=expected_version,
                void_reason=void_reason,
                voided_date=voided_date,
            ),
            change=change,
            active_uow=active_uow,
        )

    def reopen(
        self,
        *,
        principal_id: str,
        constraint_id: str,
        target_state: ConstraintLifecycleState,
        expected_version: int,
        actor: ConstraintMutationActor,
        reason: str | None = None,
        idempotency_key: str | None = None,
        client_context: str | None = None,
        correlation_id: str | None = None,
        active_uow: _ActiveConstraintUnitOfWork | None = None,
    ) -> ConstraintMutationResult:
        """Return a CLOSED or VOID Constraint to an explicit active state.

        REOPEN is an operation and never a stored state: what is written is the
        active `target_state` the caller named. Every terminal-only field is
        cleared from the *current* projection; the immutable revisions that
        recorded the closure or the voiding are untouched, which is where the
        prior terminal data remains readable (CM-BE-AC-017).

        `reason` participates in replay identity. The accepted contract defines
        no stored field for it, so this build records it in the request digest
        and nowhere else rather than inventing a column for it.
        """

        def change(mutation: _Mutation) -> ProjectConstraint:
            current = mutation.existing()
            check_lifecycle_move(
                current.lifecycle_state, target_state, ConstraintLifecycleOperation.REOPEN
            )
            return dataclasses.replace(
                current,
                lifecycle_state=target_state,
                completion_date=None,
                closure_commentary=None,
                voided_date=None,
                void_reason=None,
            )

        return self._mutate(
            principal_id=principal_id,
            constraint_id=constraint_id,
            expected_version=expected_version,
            operation=ConstraintMutationOperation.REOPEN,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            correlation_id=correlation_id,
            request_digest=_digest(
                constraint_id=constraint_id,
                expected_version=expected_version,
                target_state=target_state,
                reason=reason,
            ),
            change=change,
            active_uow=active_uow,
        )

    def close_with_follow_up(
        self,
        *,
        principal_id: str,
        constraint_id: str,
        expected_version: int,
        actor: ConstraintMutationActor,
        successor_description: str,
        completion_date: date | None = None,
        closure_commentary: str | None = None,
        successor_category_id: str | None = None,
        successor_due_date: date | None = None,
        successor_state: ConstraintLifecycleState = ConstraintLifecycleState.IDENTIFIED,
        successor_bic: Sequence[PartyRef] | None = None,
        successor_responsible: Sequence[PartyRef] | None = None,
        idempotency_key: str | None = None,
        client_context: str | None = None,
        correlation_id: str | None = None,
    ) -> ConstraintFollowUpResult:
        """Close a Constraint and publish its follow-up, as one atomic operation.

        One unit of work covers all six steps: close the predecessor, create
        the successor, publish it, allocate its own public code, write every
        revision and receipt, and record the `FOLLOW_UP_OF` edge from successor
        to predecessor. A failure at any of them — a stale version, an
        incomplete successor, a Category that is no longer active, an integrity
        violation on the code — rolls the whole transaction back and leaves
        zero partial state: no closed predecessor, no orphan successor, no
        consumed number, no edge.

        Successor defaults follow §15: same Project, the predecessor's Category
        unless a valid override is supplied before publication, Date Identified
        `projectToday`, state `IDENTIFIED`, BIC and Responsible inherited only
        when omitted, and Due `+10` business days when omitted. Description is
        required. Reference and current-update are never inherited silently.

        This method takes no `active_uow`: it *is* a composite, and letting a
        caller supply the transaction would let a larger unit commit a partial
        follow-up that this operation's whole contract is that it cannot.
        """
        if not successor_description.strip():
            raise ConstraintOperationError(
                "constraint_follow_up_description_blank",
                "a follow-up constraint requires a description",
            )
        digest = _digest(
            constraint_id=constraint_id,
            expected_version=expected_version,
            completion_date=completion_date,
            closure_commentary=closure_commentary,
            successor_description=successor_description,
            successor_category_id=successor_category_id,
            successor_due_date=successor_due_date,
            successor_state=successor_state,
            successor_bic=None if successor_bic is None else _party_digest(tuple(successor_bic)),
            successor_responsible=(
                None
                if successor_responsible is None
                else _party_digest(tuple(successor_responsible))
            ),
        )
        successor_key = None if idempotency_key is None else _derived_key(idempotency_key)
        if idempotency_key is not None:
            _validate_idempotency_key(idempotency_key)

        with self._unit_of_work() as uow:
            # The predecessor's row lock comes first and the replay gate sits
            # behind it, for the reason `_mutate` states. This composite names a
            # row it can lock, so it must: two requests carrying one key would
            # otherwise both read an empty ledger, and the loser — whose inner
            # `close` replays rather than closing again — would still fall
            # through the remaining five steps to a duplicate `FOLLOW_UP_OF`
            # edge, which the stored uniqueness on that edge refuses. The
            # transaction would roll back whole, but the caller would receive a
            # driver integrity error where CM-BE-AC-065 requires `REPLAYED`.
            # Locking first makes the loser wait and then read the ledger the
            # winner committed; `close` re-locks the same row inside the same
            # transaction, which costs nothing.
            uow.constraints.get_for_update(principal_id, constraint_id)
            if idempotency_key is not None:
                prior = uow.constraints.find_history_by_idempotency_key(
                    principal_id, idempotency_key
                )
                if prior is not None:
                    if prior.request_digest != digest:
                        raise ConstraintIdempotencyConflictError(
                            "the idempotency key was used for different normalized content"
                        )
                    return self._replayed_follow_up(uow, principal_id, prior, successor_key)

            closed = self.close(
                principal_id=principal_id,
                constraint_id=constraint_id,
                expected_version=expected_version,
                actor=actor,
                completion_date=completion_date,
                closure_commentary=closure_commentary,
                idempotency_key=idempotency_key,
                client_context=client_context,
                correlation_id=correlation_id,
                active_uow=uow,
                digest_override=digest,
            )
            if closed.disposition is ConstraintMutationDisposition.REPLAYED:
                # The second guard behind the same fact: `close`'s own gate found
                # a receipt under this request's key, so the whole composite has
                # already been applied and the remaining five steps must not run
                # again. Reachable only if the lock above were ever removed, and
                # kept because falling through here is what turned a replay into
                # an integrity error.
                return self._replayed_follow_up(uow, principal_id, closed.receipt, successor_key)
            predecessor = closed.record
            if predecessor.project_id is None:
                raise ConstraintOperationError(
                    "constraint_follow_up_predecessor_unpublished",
                    "only a published constraint can carry a follow-up",
                )
            now = self._clock()
            identified = self._project_today(uow, principal_id, predecessor.project_id, now)
            draft = self.create_draft(
                principal_id=principal_id,
                actor=actor,
                project_id=predecessor.project_id,
                category_id=successor_category_id or predecessor.category_id,
                description=successor_description,
                date_identified=identified,
                due_date=successor_due_date or default_due_date(identified),
                bic=predecessor.bic if successor_bic is None else tuple(successor_bic),
                responsible=(
                    predecessor.responsible
                    if successor_responsible is None
                    else tuple(successor_responsible)
                ),
                client_context=client_context,
                correlation_id=correlation_id,
                active_uow=uow,
            )
            published = self.publish(
                principal_id=principal_id,
                constraint_id=draft.record.constraint_id,
                expected_version=draft.record.version,
                actor=actor,
                target_state=successor_state,
                idempotency_key=successor_key,
                client_context=client_context,
                correlation_id=correlation_id,
                active_uow=uow,
                digest_override=digest,
            )
            relationship = ConstraintRelationship(
                relationship_id=issue_identifier(IdKind.PROJECT_CONSTRAINT_RELATIONSHIP),
                principal_id=principal_id,
                project_id=predecessor.project_id,
                source_constraint_id=published.record.constraint_id,
                target_constraint_id=predecessor.constraint_id,
                relationship_type=ConstraintRelationshipType.FOLLOW_UP_OF,
                created_by_history_id=published.receipt.history_id,
                created_at=now,
            )
            uow.constraints.insert_relationship(principal_id, relationship)

        return ConstraintFollowUpResult(
            disposition=ConstraintMutationDisposition.APPLIED,
            predecessor=predecessor,
            successor=published.record,
            predecessor_receipt=closed.receipt,
            successor_receipt=published.receipt,
            relationship_id=relationship.relationship_id,
        )

    # --- Categories ------------------------------------------------------

    def create_category(
        self,
        *,
        principal_id: str,
        project_id: str,
        prefix: str,
        title: str,
        actor: ConstraintMutationActor,
        description: str | None = None,
        display_order: int = 0,
        state: ConstraintCategoryState = ConstraintCategoryState.ACTIVE,
        idempotency_key: str | None = None,
        client_context: str | None = None,
        correlation_id: str | None = None,
        active_uow: _ActiveConstraintUnitOfWork | None = None,
    ) -> ConstraintCategoryMutationResult:
        """Create one Constraint Category in one of this Principal's Projects.

        The prefix syntax is the domain's (`CONSTRAINT_CATEGORY_PREFIX_PATTERN`)
        and its Project-uniqueness is the stored index's; the allocator starts
        unused, so a brand new Category has issued nothing and its prefix is not
        yet locked.
        """

        def build(mutation: _CategoryMutation) -> ConstraintCategory:
            self._require_project(mutation.uow, principal_id, project_id)
            return ConstraintCategory(
                category_id=issue_identifier(IdKind.CONSTRAINT_CATEGORY),
                principal_id=principal_id,
                project_id=project_id,
                prefix=prefix,
                title=title,
                state=state,
                created_at=mutation.now,
                updated_at=mutation.now,
                description=description,
                display_order=display_order,
            )

        return self._mutate_category(
            principal_id=principal_id,
            project_id=project_id,
            category_id=None,
            expected_version=None,
            operation=ConstraintCategoryMutationOperation.CREATE,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            correlation_id=correlation_id,
            request_digest=_digest(
                project_id=project_id,
                prefix=prefix,
                title=title,
                description=description,
                display_order=display_order,
                state=state,
            ),
            change=build,
            active_uow=active_uow,
        )

    def update_category(
        self,
        *,
        principal_id: str,
        category_id: str,
        expected_version: int,
        actor: ConstraintMutationActor,
        values: Mapping[str, object] | None = None,
        idempotency_key: str | None = None,
        client_context: str | None = None,
        correlation_id: str | None = None,
        active_uow: _ActiveConstraintUnitOfWork | None = None,
    ) -> ConstraintCategoryMutationResult:
        """Change a Category's title, description, display order, or unlocked prefix.

        `revise_category` is where the one rule lives: a prefix change is
        refused once the prefix is locked, while title, description and display
        order stay changeable on the same locked Category (CM-BE-AC-021/022).
        State is not settable here — deactivation is its own operation, and the
        accepted operation contract exposes no archive.
        """
        patch = dict(values or {})
        allowed = {"prefix", "title", "description", "display_order"}
        if unknown := set(patch) - allowed:
            raise ConstraintOperationError(
                "constraint_category_update_field_unknown",
                f"not updatable category fields: {sorted(unknown)!r}",
            )

        def build(mutation: _CategoryMutation) -> ConstraintCategory:
            current = mutation.existing()
            revised = revise_category(
                current,
                prefix=_text(patch.get("prefix")),
                title=_text(patch.get("title")),
                description=_text(patch.get("description")),
                display_order=_whole(patch.get("display_order")),
            )
            if revised == current:
                return current
            return dataclasses.replace(revised, updated_at=mutation.now)

        return self._mutate_category(
            principal_id=principal_id,
            project_id=None,
            category_id=category_id,
            expected_version=expected_version,
            operation=ConstraintCategoryMutationOperation.UPDATE,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            correlation_id=correlation_id,
            request_digest=_digest(
                category_id=category_id,
                expected_version=expected_version,
                values=_normalized_patch(patch),
            ),
            change=build,
            active_uow=active_uow,
        )

    def deactivate_category(
        self,
        *,
        principal_id: str,
        category_id: str,
        expected_version: int,
        actor: ConstraintMutationActor,
        idempotency_key: str | None = None,
        client_context: str | None = None,
        correlation_id: str | None = None,
        active_uow: _ActiveConstraintUnitOfWork | None = None,
    ) -> ConstraintCategoryMutationResult:
        """Retire a Category from new Publishes without deleting anything.

        `INACTIVE` is a state, not a deletion: the Category, its issued codes
        and the Constraints under it all remain (CM-BE-AC-023), and this build
        offers no hard delete at any layer. Deactivating an already-inactive
        Category is a `NO_OP`.
        """

        def build(mutation: _CategoryMutation) -> ConstraintCategory:
            current = mutation.existing()
            if current.state is ConstraintCategoryState.ARCHIVED:
                raise ConstraintOperationError(
                    "constraint_category_archived",
                    "an archived category is not deactivated again",
                )
            if current.state is ConstraintCategoryState.INACTIVE:
                return current
            return dataclasses.replace(
                current, state=ConstraintCategoryState.INACTIVE, updated_at=mutation.now
            )

        return self._mutate_category(
            principal_id=principal_id,
            project_id=None,
            category_id=category_id,
            expected_version=expected_version,
            operation=ConstraintCategoryMutationOperation.UPDATE,
            actor=actor,
            idempotency_key=idempotency_key,
            client_context=client_context,
            correlation_id=correlation_id,
            request_digest=_digest(category_id=category_id, expected_version=expected_version),
            change=build,
            active_uow=active_uow,
        )

    def reorder_categories(
        self,
        *,
        principal_id: str,
        project_id: str,
        ordered_category_ids: Sequence[str],
        expected_versions: Mapping[str, int],
        actor: ConstraintMutationActor,
        idempotency_key: str | None = None,
        client_context: str | None = None,
        correlation_id: str | None = None,
    ) -> ConstraintCategoryReorderResult:
        """Set the whole display order of a Project's Categories, atomically.

        The input is the *complete* ordered sequence of the Project's Category
        identifiers, each exactly once — a partial sequence is refused rather
        than applied to the part it named, because a reorder of some categories
        is not a well-defined order of all of them. Every named row is locked,
        every `expected_versions` entry is compared under those locks, and a
        conflict on any one member rejects the whole reorder with no display
        order changed. This is one operation with one transaction, never a loop
        of independent public updates.

        The caller's idempotency key is recorded on the first receipt of the
        sequence: the two ledgers hold one key per Principal, so a reorder that
        wrote the same key on every member would collide with itself.
        """
        wanted = tuple(ordered_category_ids)
        if len(set(wanted)) != len(wanted):
            raise ConstraintReorderError(
                "constraint_category_reorder_repeats_a_category",
                "a reorder names each category exactly once",
            )
        digest = _digest(project_id=project_id, ordered_category_ids=list(wanted))
        if idempotency_key is not None:
            _validate_idempotency_key(idempotency_key)

        with self._unit_of_work() as uow:
            self._require_project(uow, principal_id, project_id)
            known = {
                row.category_id: row
                for row in uow.constraints.list_categories(
                    principal_id, project_id, include_states=None
                )
            }
            if set(known) != set(wanted):
                raise ConstraintReorderError(
                    "constraint_category_reorder_is_not_the_whole_project",
                    "a reorder names every category of the project, exactly once each",
                )
            # Locked in a stable identifier order rather than the caller's, so
            # two concurrent reorders of the same Project queue instead of
            # deadlocking on each other's second row. The locks are taken before
            # the replay gate below, for the reason `_mutate` states: this
            # operation names every row it touches, so two requests carrying one
            # key must not both read an empty ledger and both proceed — the
            # loser would write a second receipt under a key the stored partial
            # unique index reserves, turning an accepted replay into an
            # integrity error. Holding the rows first makes it wait and read the
            # ledger the winner committed.
            locked = {
                category_id: self._locked_category_row(uow, principal_id, category_id)
                for category_id in sorted(wanted)
            }
            if idempotency_key is not None:
                prior = uow.constraints.find_category_history_by_idempotency_key(
                    principal_id, idempotency_key
                )
                if prior is not None:
                    if prior.request_digest != digest:
                        raise ConstraintIdempotencyConflictError(
                            "the idempotency key was used for different normalized content"
                        )
                    return self._replayed_reorder(uow, principal_id, project_id, wanted, prior)

            now = self._clock()
            records: list[ConstraintCategory] = []
            receipts: list[ConstraintCategoryHistoryEntry] = []
            rejected = tuple(
                self._record_category(
                    uow=uow,
                    principal_id=principal_id,
                    project_id=project_id,
                    category_id=category_id,
                    operation=ConstraintCategoryMutationOperation.UPDATE,
                    actor=actor,
                    outcome=ConstraintMutationOutcome.REJECTED,
                    before_version=known[category_id].version,
                    after_version=known[category_id].version,
                    occurred_at=now,
                    idempotency_key=None,
                    client_context=client_context,
                    correlation_id=correlation_id,
                    request_digest=digest,
                    safe_failure_reason="version_conflict",
                )
                for category_id in sorted(wanted)
                if expected_versions.get(category_id) != known[category_id].version
            )
            if not rejected:
                for position, category_id in enumerate(wanted):
                    row = known[category_id]
                    category = locked[category_id]
                    reordered = dataclasses.replace(
                        category, display_order=position, updated_at=now
                    )
                    uow.constraints.update_category(
                        principal_id,
                        reordered,
                        next_sequence=row.next_sequence,
                        issued_count=row.issued_count,
                        version=row.version + 1,
                    )
                    records.append(reordered)
                    receipts.append(
                        self._record_category(
                            uow=uow,
                            principal_id=principal_id,
                            project_id=project_id,
                            category_id=category_id,
                            operation=ConstraintCategoryMutationOperation.UPDATE,
                            actor=actor,
                            outcome=ConstraintMutationOutcome.APPLIED,
                            before_version=row.version,
                            after_version=row.version + 1,
                            occurred_at=now,
                            idempotency_key=idempotency_key if position == 0 else None,
                            client_context=client_context,
                            correlation_id=correlation_id,
                            request_digest=digest,
                        )
                    )

        if rejected:
            raise ConstraintCategoryVersionConflictError(rejected)
        return ConstraintCategoryReorderResult(
            disposition=ConstraintMutationDisposition.APPLIED,
            records=tuple(records),
            receipts=tuple(receipts),
        )

    # --- The one transactional mechanism ---------------------------------

    def _mutate(
        self,
        *,
        principal_id: str,
        constraint_id: str | None,
        expected_version: int | None,
        operation: ConstraintMutationOperation,
        actor: ConstraintMutationActor,
        idempotency_key: str | None,
        client_context: str | None,
        correlation_id: str | None,
        request_digest: str,
        change: _Change,
        active_uow: _ActiveConstraintUnitOfWork | None = None,
        digest_override: str | None = None,
    ) -> ConstraintMutationResult:
        """The single transactional mechanism every Constraint method delegates to.

        One unit of work per call — or the caller's, when `active_uow` is given
        — holding the idempotency lookup, the row-locked read, the version
        comparison, `change`, the record write, the immutable revision and the
        receipt. `ConstraintNotFoundError` and `ConstraintVersionConflictError`
        are raised *after* the block, never inside it: raising inside would roll
        back the `REJECTED` receipt the refusal must still commit. Domain
        errors from `change` propagate from inside, and always before this
        attempt has written anything.

        `digest_override` exists for `close_with_follow_up`, whose sub-steps
        are parts of one request and must therefore replay under that one
        request's identity rather than under three of their own.
        """
        digest = digest_override or request_digest
        if idempotency_key is not None:
            _validate_idempotency_key(idempotency_key)

        pending_not_found = False
        pending_conflict: tuple[ProjectConstraint, ConstraintHistoryEntry] | None = None
        result: ConstraintMutationResult | None = None

        context = self._unit_of_work() if active_uow is None else nullcontext(active_uow)
        with context as uow:
            # The row lock comes first, and the replay gate sits behind it. Two
            # requests carrying one key would otherwise both read an empty
            # ledger, both proceed, and the loser would try to write a second
            # receipt under a key the stored partial unique index reserves —
            # turning an accepted replay into an integrity error. Locking first
            # makes the second request wait, and read the ledger the winner
            # committed. A creation names no row to lock and therefore has no
            # such gate; a concurrent duplicate creation under one key is
            # refused by that same index, which is the fail-closed answer.
            current = (
                uow.constraints.get_for_update(principal_id, constraint_id)
                if constraint_id is not None
                else None
            )
            if idempotency_key is not None:
                prior = uow.constraints.find_history_by_idempotency_key(
                    principal_id, idempotency_key
                )
                if prior is not None:
                    if prior.request_digest != digest:
                        raise ConstraintIdempotencyConflictError(
                            "the idempotency key was used for different normalized content"
                        )
                    replayed = (
                        current
                        if current is not None and current.constraint_id == prior.constraint_id
                        else uow.constraints.get(principal_id, prior.constraint_id)
                    )
                    if replayed is None:
                        raise RuntimeError(
                            "a recorded receipt names a constraint that still exists"
                        )
                    result = ConstraintMutationResult(
                        disposition=ConstraintMutationDisposition.REPLAYED,
                        record=replayed,
                        receipt=prior,
                    )

            if result is None:
                now = self._clock()
                if constraint_id is not None and current is None:
                    pending_not_found = True
                elif (
                    current is not None
                    and expected_version is not None
                    and current.version != expected_version
                ):
                    rejected = self._record(
                        uow=uow,
                        principal_id=principal_id,
                        constraint=current,
                        operation=operation,
                        actor=actor,
                        outcome=ConstraintMutationOutcome.REJECTED,
                        before_version=current.version,
                        after_version=current.version,
                        occurred_at=now,
                        idempotency_key=idempotency_key,
                        client_context=client_context,
                        correlation_id=correlation_id,
                        request_digest=digest,
                        revision_id=None,
                        safe_failure_reason="version_conflict",
                    )
                    pending_conflict = (current, rejected)
                else:
                    proposed = change(_Mutation(uow=uow, current=current, now=now))
                    before_version = current.version if current is not None else 0
                    if current is not None and proposed == current:
                        receipt = self._record(
                            uow=uow,
                            principal_id=principal_id,
                            constraint=current,
                            operation=operation,
                            actor=actor,
                            outcome=ConstraintMutationOutcome.NO_OP,
                            before_version=before_version,
                            after_version=before_version,
                            occurred_at=now,
                            idempotency_key=idempotency_key,
                            client_context=client_context,
                            correlation_id=correlation_id,
                            request_digest=digest,
                            revision_id=None,
                        )
                        result = ConstraintMutationResult(
                            disposition=ConstraintMutationDisposition.NO_OP,
                            record=current,
                            receipt=receipt,
                        )
                    else:
                        applied = dataclasses.replace(
                            proposed, version=before_version + 1, updated_at=now
                        )
                        revision_id = issue_identifier(IdKind.PROJECT_CONSTRAINT_REVISION)
                        if current is None:
                            uow.constraints.insert_constraint(
                                principal_id, applied, current_revision_id=revision_id
                            )
                        else:
                            uow.constraints.update_constraint(
                                principal_id, applied, current_revision_id=revision_id
                            )
                        receipt = self._record(
                            uow=uow,
                            principal_id=principal_id,
                            constraint=applied,
                            operation=operation,
                            actor=actor,
                            outcome=ConstraintMutationOutcome.APPLIED,
                            before_version=before_version,
                            after_version=applied.version,
                            occurred_at=now,
                            idempotency_key=idempotency_key,
                            client_context=client_context,
                            correlation_id=correlation_id,
                            request_digest=digest,
                            revision_id=revision_id,
                        )
                        uow.constraints.insert_revision(
                            principal_id,
                            ConstraintRevision.from_constraint(
                                applied,
                                revision_id=revision_id,
                                history_id=receipt.history_id,
                                recorded_at=now,
                            ),
                        )
                        result = ConstraintMutationResult(
                            disposition=ConstraintMutationDisposition.APPLIED,
                            record=applied,
                            receipt=receipt,
                        )

        if pending_not_found:
            raise ConstraintNotFoundError(
                f"no constraint {constraint_id!r} in this principal's partition"
            )
        if pending_conflict is not None:
            raise ConstraintVersionConflictError(*pending_conflict)
        if result is None:  # pragma: no cover - the three branches above are total
            raise RuntimeError("_mutate left its transaction with no result")
        return result

    def _record(
        self,
        *,
        uow: _ActiveConstraintUnitOfWork,
        principal_id: str,
        constraint: ProjectConstraint,
        operation: ConstraintMutationOperation,
        actor: ConstraintMutationActor,
        outcome: ConstraintMutationOutcome,
        before_version: int,
        after_version: int,
        occurred_at: datetime,
        idempotency_key: str | None,
        client_context: str | None,
        correlation_id: str | None,
        request_digest: str,
        revision_id: str | None,
        safe_failure_reason: str | None = None,
    ) -> ConstraintHistoryEntry:
        """Append one Constraint receipt. The only place this module writes one."""
        entry = ConstraintHistoryEntry(
            history_id=issue_identifier(IdKind.PROJECT_CONSTRAINT_HISTORY),
            principal_id=principal_id,
            constraint_id=constraint.constraint_id,
            operation=operation,
            actor=actor,
            outcome=outcome,
            before_version=before_version,
            after_version=after_version,
            occurred_at=occurred_at,
            recorded_at=self._clock(),
            project_id=constraint.project_id,
            revision_id=revision_id,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            client_context=client_context,
            correlation_id=correlation_id,
            safe_failure_reason=safe_failure_reason,
        )
        uow.constraints.insert_history(principal_id, entry)
        return entry

    def _mutate_category(
        self,
        *,
        principal_id: str,
        project_id: str | None,
        category_id: str | None,
        expected_version: int | None,
        operation: ConstraintCategoryMutationOperation,
        actor: ConstraintMutationActor,
        idempotency_key: str | None,
        client_context: str | None,
        correlation_id: str | None,
        request_digest: str,
        change: _CategoryChange,
        active_uow: _ActiveConstraintUnitOfWork | None = None,
    ) -> ConstraintCategoryMutationResult:
        """The Category sibling of `_mutate`. Same discipline, one ledger over.

        There is no Category revision ledger — a deliberate WP02 limitation —
        so an applied Category mutation writes the row and its receipt and
        nothing else, and the receipt carries no `revision_id` because the
        stored table has no column for one.
        """
        if idempotency_key is not None:
            _validate_idempotency_key(idempotency_key)

        pending_not_found = False
        pending_conflict: ConstraintCategoryHistoryEntry | None = None
        result: ConstraintCategoryMutationResult | None = None

        context = self._unit_of_work() if active_uow is None else nullcontext(active_uow)
        with context as uow:
            # Locked first, replay gate behind it, for the reason `_mutate`
            # states over the Constraint ledger.
            current = (
                uow.constraints.get_category_for_update(principal_id, category_id)
                if category_id is not None
                else None
            )
            if idempotency_key is not None:
                prior = uow.constraints.find_category_history_by_idempotency_key(
                    principal_id, idempotency_key
                )
                if prior is not None:
                    if prior.request_digest != request_digest:
                        raise ConstraintIdempotencyConflictError(
                            "the idempotency key was used for different normalized content"
                        )
                    replayed = (
                        current
                        if current is not None and current.category_id == prior.category_id
                        else uow.constraints.get_category(principal_id, prior.category_id)
                    )
                    if replayed is None:
                        raise RuntimeError("a recorded receipt names a category that still exists")
                    result = ConstraintCategoryMutationResult(
                        disposition=ConstraintMutationDisposition.REPLAYED,
                        record=replayed,
                        receipt=prior,
                    )

            if result is None:
                now = self._clock()
                row = (
                    None
                    if current is None
                    else self._allocator_row(
                        uow, principal_id, current.project_id, current.category_id
                    )
                )
                if category_id is not None and current is None:
                    pending_not_found = True
                elif (
                    row is not None
                    and expected_version is not None
                    and row.version != expected_version
                ):
                    pending_conflict = self._record_category(
                        uow=uow,
                        principal_id=principal_id,
                        project_id=row.project_id,
                        category_id=row.category_id,
                        operation=operation,
                        actor=actor,
                        outcome=ConstraintMutationOutcome.REJECTED,
                        before_version=row.version,
                        after_version=row.version,
                        occurred_at=now,
                        idempotency_key=idempotency_key,
                        client_context=client_context,
                        correlation_id=correlation_id,
                        request_digest=request_digest,
                        safe_failure_reason="version_conflict",
                    )
                else:
                    proposed = change(_CategoryMutation(uow=uow, current=current, now=now))
                    before_version = row.version if row is not None else 0
                    if current is not None and proposed == current:
                        receipt = self._record_category(
                            uow=uow,
                            principal_id=principal_id,
                            project_id=proposed.project_id,
                            category_id=proposed.category_id,
                            operation=operation,
                            actor=actor,
                            outcome=ConstraintMutationOutcome.NO_OP,
                            before_version=before_version,
                            after_version=before_version,
                            occurred_at=now,
                            idempotency_key=idempotency_key,
                            client_context=client_context,
                            correlation_id=correlation_id,
                            request_digest=request_digest,
                        )
                        result = ConstraintCategoryMutationResult(
                            disposition=ConstraintMutationDisposition.NO_OP,
                            record=current,
                            receipt=receipt,
                        )
                    else:
                        if row is None:
                            uow.constraints.insert_category(principal_id, proposed)
                        else:
                            uow.constraints.update_category(
                                principal_id,
                                proposed,
                                next_sequence=row.next_sequence,
                                issued_count=row.issued_count,
                                version=before_version + 1,
                            )
                        receipt = self._record_category(
                            uow=uow,
                            principal_id=principal_id,
                            project_id=proposed.project_id,
                            category_id=proposed.category_id,
                            operation=operation,
                            actor=actor,
                            outcome=ConstraintMutationOutcome.APPLIED,
                            before_version=before_version,
                            after_version=before_version + 1,
                            occurred_at=now,
                            idempotency_key=idempotency_key,
                            client_context=client_context,
                            correlation_id=correlation_id,
                            request_digest=request_digest,
                        )
                        result = ConstraintCategoryMutationResult(
                            disposition=ConstraintMutationDisposition.APPLIED,
                            record=proposed,
                            receipt=receipt,
                        )

        if pending_not_found:
            raise ConstraintCategoryNotFoundError(
                f"no category {category_id!r} in this principal's partition"
            )
        if pending_conflict is not None:
            raise ConstraintCategoryVersionConflictError((pending_conflict,))
        if result is None:  # pragma: no cover - the three branches above are total
            raise RuntimeError("_mutate_category left its transaction with no result")
        return result

    def _record_category(
        self,
        *,
        uow: _ActiveConstraintUnitOfWork,
        principal_id: str,
        project_id: str,
        category_id: str,
        operation: ConstraintCategoryMutationOperation,
        actor: ConstraintMutationActor,
        outcome: ConstraintMutationOutcome,
        before_version: int,
        after_version: int,
        occurred_at: datetime,
        idempotency_key: str | None,
        client_context: str | None,
        correlation_id: str | None,
        request_digest: str,
        safe_failure_reason: str | None = None,
    ) -> ConstraintCategoryHistoryEntry:
        """Append one Category receipt. The only place this module writes one."""
        entry = ConstraintCategoryHistoryEntry(
            history_id=issue_identifier(IdKind.CONSTRAINT_CATEGORY_HISTORY),
            principal_id=principal_id,
            project_id=project_id,
            category_id=category_id,
            operation=operation,
            actor=actor,
            outcome=outcome,
            before_version=before_version,
            after_version=after_version,
            occurred_at=occurred_at,
            recorded_at=self._clock(),
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            client_context=client_context,
            correlation_id=correlation_id,
            safe_failure_reason=safe_failure_reason,
        )
        uow.constraints.insert_category_history(principal_id, entry)
        return entry

    # --- Seams and helpers ------------------------------------------------

    def _require_project(
        self, uow: _ActiveConstraintUnitOfWork, principal_id: str, project_id: str
    ) -> None:
        """Refuse a Project this Principal has no Constraint settings for.

        The same seam and the same answer the WP03 read plane uses: unconfigured
        and foreign are indistinguishable, so naming another Principal's Project
        discloses nothing about whether it exists.
        """
        if uow.constraints.get_project_settings(principal_id, project_id) is None:
            raise ConstraintProjectUnavailableError(
                "the project is not available to this principal"
            )

    def _require_category(
        self,
        uow: _ActiveConstraintUnitOfWork,
        principal_id: str,
        category_id: str,
        project_id: str | None,
    ) -> ConstraintCategory:
        """The named Category, if it is this Principal's and in `project_id`."""
        category = uow.constraints.get_category(principal_id, category_id)
        if category is None or (project_id is not None and category.project_id != project_id):
            raise ConstraintCategoryNotFoundError(
                f"no category {category_id!r} in this principal's partition"
            )
        return category

    def _validate_parties(
        self,
        uow: _ActiveConstraintUnitOfWork,
        principal_id: str,
        parties: tuple[PartyRef, ...],
    ) -> None:
        """Refuse any `ENTITY` party outside this Principal's partition.

        Batched through the existing `entity_labels` seam rather than a new
        entity port method, and by identifier only: `PRINCIPAL` needs no lookup,
        `UNRESOLVED` is preserved wording that resolves to nothing, and no
        party is ever matched by name, email, label, or substring.
        """
        wanted = sorted(
            {
                party.entity_id
                for party in parties
                if party.kind is PartyKind.ENTITY and party.entity_id is not None
            }
        )
        if not wanted:
            return
        known = uow.constraints.entity_labels(principal_id, wanted)
        if missing := [entity_id for entity_id in wanted if entity_id not in known]:
            raise ConstraintPartyError(
                "constraint_party_entity_unavailable",
                f"{len(missing)} entity party reference(s) are not available to this principal",
            )

    def _project_today(
        self,
        uow: _ActiveConstraintUnitOfWork,
        principal_id: str,
        project_id: str | None,
        now: datetime,
    ) -> date:
        """The Project's own calendar date, or the typed failure that says why not.

        `project_today` raises `project_timezone_unconfigured` for a Project
        with no settings row, which is the accepted fail-closed behaviour: this
        build never guesses a fallback timezone on a caller's behalf.
        """
        settings = (
            None
            if project_id is None
            else uow.constraints.get_project_settings(principal_id, project_id)
        )
        return project_today(now, None if settings is None else settings.timezone_name)

    def _resolve_publication(
        self,
        mutation: _Mutation,
        principal_id: str,
        current: ProjectConstraint,
        *,
        category_id: str | None,
        date_identified: date | None,
        due_date: date | None,
        bic: tuple[PartyRef, ...] | None,
        responsible: tuple[PartyRef, ...] | None,
    ) -> ProjectConstraint:
        """The Draft with every accepted Publish default resolved, still a Draft.

        Resolved before validation so the completeness check sees the record
        that would actually be published, and resolved before the code is
        allocated so a Publish that is going to be refused never consumes one.
        """
        if current.project_id is None:
            raise ConstraintPublishError(
                "constraint_publish_incomplete",
                "publish requires: project_id",
                missing_publish_fields(current),
            )
        self._require_project(mutation.uow, principal_id, current.project_id)
        identified = date_identified or current.date_identified
        if identified is None:
            identified = self._project_today(
                mutation.uow, principal_id, current.project_id, mutation.now
            )
        due = due_date or current.due_date or default_due_date(identified)
        return dataclasses.replace(
            current,
            category_id=category_id or current.category_id,
            date_identified=identified,
            due_date=due,
            bic=current.bic if bic is None else bic,
            responsible=current.responsible if responsible is None else responsible,
        )

    def _locked_category(
        self, uow: _ActiveConstraintUnitOfWork, principal_id: str, candidate: ProjectConstraint
    ) -> ConstraintCategory:
        """Lock the allocator row this Publish will draw its code from."""
        if candidate.category_id is None:
            raise ConstraintPublishError(
                "constraint_publish_incomplete",
                "publish requires: category_id",
                missing_publish_fields(candidate),
            )
        category = uow.constraints.get_category_for_update(principal_id, candidate.category_id)
        if category is None:
            raise ConstraintCategoryNotFoundError(
                f"no category {candidate.category_id!r} in this principal's partition"
            )
        return category

    def _locked_category_row(
        self, uow: _ActiveConstraintUnitOfWork, principal_id: str, category_id: str
    ) -> ConstraintCategory:
        category = uow.constraints.get_category_for_update(principal_id, category_id)
        if category is None:
            raise ConstraintCategoryNotFoundError(
                f"no category {category_id!r} in this principal's partition"
            )
        return category

    def _allocator_row(
        self,
        uow: _ActiveConstraintUnitOfWork,
        principal_id: str,
        project_id: str,
        category_id: str,
    ) -> ConstraintCategoryRow:
        """The allocator counters and `version` of one already-locked Category.

        `ConstraintCategory` is the domain shape and carries none of the three:
        allocation is not a rule of a Category, it is what a service does to
        one. They are read here through the existing bounded Category listing
        rather than through a second locking select, because the row is already
        held and `tests/architecture/test_constraint_reads_take_no_update_lock`
        keeps `get_for_update` and `get_category_for_update` the only two
        locking call sites in the Constraint plane.
        """
        for row in uow.constraints.list_categories(principal_id, project_id, include_states=None):
            if row.category_id == category_id:
                return row
        raise ConstraintCategoryNotFoundError(
            f"no category {category_id!r} in this principal's partition"
        )

    def _allocate_code(
        self,
        uow: _ActiveConstraintUnitOfWork,
        principal_id: str,
        category: ConstraintCategory,
        now: datetime,
    ) -> str:
        """Allocate the next public code under the held Category row lock.

        The suffix is rendered at a *minimum* width of two and never truncated,
        so the sequence runs `X.01`, `X.09`, `X.10`, `X.100` as exact text. The
        code is a string at every step; nothing here parses one, so `1.10` can
        never become `1.1`. The sequence advances and the issue count rises in
        the same statement, and the prefix locks at the first issuance — the
        stored `(issued_count = 0) = (prefix_locked_at IS NULL)` check restates
        exactly that pairing. The Category's own `version` is untouched: issuing
        a code is not a Category mutation, and advancing it here would make
        every concurrent Publish invalidate an unrelated Category edit.
        """
        row = self._allocator_row(uow, principal_id, category.project_id, category.category_id)
        code = f"{category.prefix}.{row.next_sequence:0{MINIMUM_CODE_SUFFIX_WIDTH}d}"
        locked = (
            category
            if category.is_prefix_locked
            else dataclasses.replace(category, prefix_locked_at=now)
        )
        uow.constraints.update_category(
            principal_id,
            locked,
            next_sequence=row.next_sequence + 1,
            issued_count=row.issued_count + 1,
            version=row.version,
        )
        return code

    def _replayed_follow_up(
        self,
        uow: _ActiveConstraintUnitOfWork,
        principal_id: str,
        prior: ConstraintHistoryEntry,
        successor_key: str | None,
    ) -> ConstraintFollowUpResult:
        """Return the original Close + Follow-up without executing anything again.

        Both halves are recovered from what the first attempt committed: the
        predecessor from its keyed receipt, the successor from the
        `FOLLOW_UP_OF` edge that points at it, and the successor's receipt from
        the derived key that attempt recorded it under.
        """
        predecessor = uow.constraints.get(principal_id, prior.constraint_id)
        edges = [
            row
            for row in uow.constraints.relationships_for(principal_id, prior.constraint_id)
            if row.relationship_type == ConstraintRelationshipType.FOLLOW_UP_OF.value
            and row.direction is RelationshipDirection.INCOMING
        ]
        successor = (
            None if not edges else uow.constraints.get(principal_id, edges[0].related_constraint_id)
        )
        successor_receipt = (
            None
            if successor_key is None
            else uow.constraints.find_history_by_idempotency_key(principal_id, successor_key)
        )
        if predecessor is None or successor is None or successor_receipt is None or not edges:
            raise RuntimeError("a recorded follow-up receipt names state that still exists")
        return ConstraintFollowUpResult(
            disposition=ConstraintMutationDisposition.REPLAYED,
            predecessor=predecessor,
            successor=successor,
            predecessor_receipt=prior,
            successor_receipt=successor_receipt,
            relationship_id=edges[0].relationship_id,
        )

    def _replayed_reorder(
        self,
        uow: _ActiveConstraintUnitOfWork,
        principal_id: str,
        project_id: str,
        wanted: tuple[str, ...],
        prior: ConstraintCategoryHistoryEntry,
    ) -> ConstraintCategoryReorderResult:
        """Return the Project's Categories as the original reorder left them."""
        known = {
            row.category_id: row
            for row in uow.constraints.list_categories(
                principal_id, project_id, include_states=None
            )
        }
        records = []
        for category_id in wanted:
            category = uow.constraints.get_category(principal_id, category_id)
            if category is None or category_id not in known:
                raise RuntimeError("a recorded reorder receipt names categories that still exist")
            records.append(category)
        return ConstraintCategoryReorderResult(
            disposition=ConstraintMutationDisposition.REPLAYED,
            records=tuple(records),
            receipts=(prior,),
        )


def _validate_idempotency_key(idempotency_key: object) -> str:
    """Refuse a key that is not a well-formed one, by type and then by shape.

    Type first and truthiness never: `if not key` accepts an integer and passes
    it to code that assumes a string, which is the defect
    `tests/architecture/test_every_write_validates_its_idempotency_key.py`
    exists to keep out of the command plane. The pattern is the domain's own
    (`CONSTRAINT_IDEMPOTENCY_KEY_PATTERN`), so the value this service accepts
    is exactly the value the stored receipt will accept.
    """
    if not isinstance(idempotency_key, str):
        raise ConstraintOperationError(
            "constraint_idempotency_key_not_a_string",
            "an idempotency key is a string",
        )
    if not CONSTRAINT_IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise ConstraintOperationError(
            "constraint_idempotency_key_malformed",
            "an idempotency key is 8-128 characters of [A-Za-z0-9_-]",
        )
    return idempotency_key


def _derived_key(idempotency_key: str) -> str:
    """The successor's replay key inside one Close + Follow-up.

    One request, two keyed receipts: the two ledgers hold one key per Principal,
    so the successor's publication cannot reuse the caller's key verbatim. It is
    derived rather than concatenated so the result is bounded whatever the
    caller's key length, and deterministic so a replay finds the same row.
    """
    suffix = hashlib.sha256(f"follow-up-successor:{idempotency_key}".encode()).hexdigest()
    return f"cfu-{suffix[:40]}"


def _text(value: object) -> str | None:
    """One optional text field of a patch, refused rather than coerced."""
    if value is None or isinstance(value, str):
        return value
    raise ConstraintOperationError("constraint_field_not_text", "this field takes text or nothing")


def _whole(value: object) -> int | None:
    """One optional whole-number field of a patch, refused rather than coerced."""
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    raise ConstraintOperationError(
        "constraint_field_not_a_whole_number", "this field takes a whole number or nothing"
    )


def _parties(value: object) -> tuple[PartyRef, ...]:
    """One party collection of a patch, as the ordered tuple the aggregate holds."""
    if not isinstance(value, tuple | list) or any(
        not isinstance(party, PartyRef) for party in value
    ):
        raise ConstraintOperationError(
            "constraint_field_not_party_references",
            "a party collection is a sequence of party references",
        )
    return tuple(value)


def _party_digest(parties: tuple[PartyRef, ...]) -> list[list[str | None]]:
    """One party collection as ordered semantic values, for the request digest.

    Order is preserved because BIC and Responsible are ordered collections and
    reordering them is a different request.
    """
    return [[party.kind.value, party.entity_id, party.label] for party in parties]


def _normalized_patch(patch: Mapping[str, object]) -> dict[str, object]:
    """One field patch as semantic values, sorted by field name.

    The digest is over what was asked for, not over how it was serialized: a
    party collection becomes its ordered value list, and everything else keeps
    its own value, which `_digest` then renders deterministically.
    """
    normalized: dict[str, object] = {}
    for field in sorted(patch):
        value = patch[field]
        if field in {"bic", "responsible"} and isinstance(value, tuple | list):
            normalized[field] = _party_digest(tuple(value))
        else:
            normalized[field] = value
    return normalized


def _digest(**values: object) -> str:
    """The SHA-256 of one request's normalized semantic content.

    Key order cannot change it (`sort_keys`), whitespace cannot change it
    (`separators`), and no raw request body reaches it: what is hashed is the
    named values this module resolved, which is what the accepted contract
    calls the request identity.
    """
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
