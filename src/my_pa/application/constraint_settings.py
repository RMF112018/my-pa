"""`ProjectControlsConfigurationService`: the one way to state a Project's calendar.

PC-CM-RUN01-WP05. `ConstraintProjectSettings` has existed since WP02 and the
read plane has resolved every Overdue and Due Soon boundary through it ever
since, but nothing in the product could ever *write* one: a row arrived by
fixture, by seed script, or not at all. This module is that missing write, and
its read companion — `configure` states which IANA calendar one Project's
Constraint dates mean, and `read_status` answers whether anybody has.

**Three checks, in this order, and they are three.** Canonical Project
ownership is `ProjectRepository.lock_project` (configure) or `get_project`
(status): a Principal-scoped row read that answers `None` for a Project that
does not exist, was deleted, or belongs to somebody else — identically, which
is the nondisclosure §14 requires. Settings *presence* is a second and separate
question asked of `constraint_project_settings` only after the first has said
whose Project it is, and it is the difference between `configured` and
`not_configured` rather than between authorized and refused. Timezone
*validity* is a third question, asked of `zoneinfo` and of nothing else. The
defect this ordering exists to prevent is the one the plan names: treating the
presence of a settings row as proof that the caller owns the Project, which
makes "not configured" and "not yours" the same answer and makes configuring a
Project impossible without already having configured it.

**Every configure is one transaction, and the Project row lock comes first.**
`lock_project` both proves ownership and serialises absent-row creation: two
requests racing to configure the same Project for the first time would
otherwise both read an empty settings table, both insert, and the loser would
hit the settings primary key. Locking first makes the second wait and read what
the winner committed, which is what turns a race into a replay.

**Idempotency is bound to normalized intent, never to bytes.** The digest
covers exactly four values — the operation, the Project, the exact validated
timezone name, and the settings `expected_version` *including* when it is null.
The Principal scopes the key, so it is not in the digest; client context,
correlation identifier, actor, timestamps and the shape of whatever transport
carried the request are excluded, because none of them changes what was asked
for. A key this Principal has already used with the same digest replays the
original answer out of the ledger; the same key with a different Project,
timezone or expected version is a typed conflict and writes nothing.

**A rejection is evidence and commits.** A stale `expected_version`, a
timezone change offered without one, and an `expected_version` offered for a
Project with no settings row at all each write a `REJECTED` receipt and then
raise — and the raise happens *after* the transaction block closes, exactly as
`ConstraintManagementService._mutate` does it, because raising inside would roll
the receipt back and leave no record that the attempt was made.

**Errors are plain module-local exceptions**, the shape
`constraint_management` uses and for the same reason: this module classifies
nothing into the public taxonomy. `ApplicationService` does that at its own
boundary, which is the only place that knows a caller is on the other end.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.contracts.ports import ConstraintManagementUnitOfWork
from my_pa.domain.common.time import utc_now
from my_pa.domain.project_controls.business_time import validate_project_timezone_name
from my_pa.domain.project_controls.history import (
    CONSTRAINT_IDEMPOTENCY_KEY_PATTERN,
    CONSTRAINT_PROJECT_SETTINGS_ACTION,
    ConstraintMutationActor,
    ConstraintProjectSettingsHistoryEntry,
    ConstraintProjectSettingsHistoryKeyConflictError,
    ConstraintProjectSettingsOutcome,
    issue_settings_history_id,
)
from my_pa.domain.project_controls.settings import ConstraintProjectSettings

__all__ = [
    "ProjectControlsConfigurationResult",
    "ProjectControlsConfigurationService",
    "ProjectControlsDisposition",
    "ProjectControlsIdempotencyConflictError",
    "ProjectControlsNotConfiguredError",
    "ProjectControlsOperationError",
    "ProjectControlsProjectUnavailableError",
    "ProjectControlsState",
    "ProjectControlsStatusResult",
    "ProjectControlsVersionConflictError",
]


class ProjectControlsProjectUnavailableError(Exception):
    """The named Project is not one this Principal owns.

    Unknown, deleted, inaccessible and foreign are the same answer and are
    raised from the same single line, so there is no branch here that could
    tell them apart even by accident. It is deliberately **not** the answer to
    "this Project has no settings row": that is
    `ProjectControlsNotConfiguredError`, and conflating the two is the defect
    this work package exists to remove.
    """


class ProjectControlsNotConfiguredError(Exception):
    """An `expected_version` was offered for a Project with no settings row.

    Reachable only after `lock_project` has already proved the Project is this
    Principal's, so saying so discloses nothing. A caller that reaches this
    asked to update a configuration that does not exist; the request it meant
    is the same one with no `expected_version`, which creates version 1.
    """


class ProjectControlsVersionConflictError(Exception):
    """The settings row is not at the version the request expected.

    Carries the `REJECTED` receipt the attempt wrote, which is committed before
    this is raised — the `ConstraintVersionConflictError` precedent — and the
    settings row as it still stands, so a caller that catches this can see
    exactly what it would have had to expect.

    A timezone change offered with no `expected_version` at all arrives here
    too. That is not a missing field so much as a stale one: the caller is
    asking to replace a calendar it never read, and a Project whose Overdue
    boundary moves because two administrators each believed they were the first
    is precisely what `expected_version` exists to prevent.
    """

    def __init__(
        self,
        settings: ConstraintProjectSettings,
        receipt: ConstraintProjectSettingsHistoryEntry,
    ) -> None:
        super().__init__("the project settings version does not match expected_version")
        self.settings = settings
        self.receipt = receipt


class ProjectControlsIdempotencyConflictError(Exception):
    """An idempotency key was reused for materially different normalized content."""


class ProjectControlsOperationError(ValueError):
    """The request's own field rule refused it before anything was read.

    `code` is stable. The only failures available are the two an idempotency
    key can have — not a string, and not the persisted alphabet and length —
    because every other field this service takes is validated by the domain it
    belongs to.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProjectControlsState(StrEnum):
    """Whether one Project's Constraint calendar has been stated.

    The stable internal result §14 requires, and the only thing `read_status`
    reports about a Project beyond the settings row's own public values. It is
    reached only after Project authorization has succeeded, so `NOT_CONFIGURED`
    is a fact about configuration and never about existence.
    """

    CONFIGURED = "configured"
    NOT_CONFIGURED = "not_configured"


class ProjectControlsDisposition(StrEnum):
    """What became of one configure attempt, as its caller is told.

    The same three members `ConstraintMutationDisposition` carries and spelled
    separately for the reason the two history vocabularies are spelled
    separately: this plane's answer is its own, and a shared enum would make one
    plane's vocabulary change the other's. `REJECTED` is absent here exactly as
    it is there — a rejection is raised carrying its receipt, never returned.
    """

    APPLIED = "applied"
    NO_OP = "no_op"
    REPLAYED = "replayed"


@dataclass(frozen=True, slots=True)
class ProjectControlsStatusResult:
    """Whether one Project is configured, and — when it is — with what.

    `settings` is `None` exactly when `state` is `NOT_CONFIGURED`; the two are
    not independent and nothing downstream may report one without the other.
    """

    project_id: str
    state: ProjectControlsState
    settings: ConstraintProjectSettings | None


@dataclass(frozen=True, slots=True)
class ProjectControlsConfigurationResult:
    """The authoritative result of one configure attempt.

    The three settings values are carried explicitly rather than as a
    `ConstraintProjectSettings`, because a `REPLAYED` answer is reconstructed
    from the ledger's snapshot of what the *original* attempt produced and not
    from the row as it stands now. A row that has since moved on must not make
    an old receipt report a new version.
    """

    disposition: ProjectControlsDisposition
    project_id: str
    timezone_name: str
    settings_version: int
    settings_updated_at: datetime
    receipt: ConstraintProjectSettingsHistoryEntry


#: The stable machine labels a `REJECTED` settings receipt may carry. Closed,
#: lowercase, and bounded by the stored `failure_code` CHECK.
_FAILURE_VERSION_CONFLICT: Final = "settings_version_conflict"
_FAILURE_VERSION_REQUIRED: Final = "settings_expected_version_required"
_FAILURE_NOT_CONFIGURED: Final = "project_controls_not_configured"


class ProjectControlsConfigurationService:
    """The one canonical entry point for reading and stating a Project's calendar."""

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], ConstraintManagementUnitOfWork],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    # --- reads ------------------------------------------------------------

    def read_status(self, *, principal_id: str, project_id: str) -> ProjectControlsStatusResult:
        """Whether this Principal's Project has a Constraint calendar.

        Ownership first and presence second. `get_project` rather than
        `lock_project`: both are the same Principal-scoped ownership answer, and
        §14 names `get_project` as the resolution every Project-bound *read*
        makes. A `SELECT ... FOR UPDATE` taken to answer a question that writes
        nothing would serialise readers against every concurrent configure for
        no gain, which is a cost the ownership proof does not require.

        No timezone check happens here, and that omission is deliberate. A
        stored name that `zoneinfo` no longer recognises still means this
        Project *is* configured — the row exists and somebody stated it — and
        reporting it as unconfigured would invite a silent reconfiguration of a
        calendar the Register is still failing closed on.
        """
        with self._unit_of_work() as uow:
            if uow.projects.get_project(principal_id, project_id) is None:
                raise ProjectControlsProjectUnavailableError(
                    "the project is not available to this principal"
                )
            settings = uow.constraints.get_project_settings(principal_id, project_id)
        if settings is None:
            return ProjectControlsStatusResult(
                project_id=project_id,
                state=ProjectControlsState.NOT_CONFIGURED,
                settings=None,
            )
        return ProjectControlsStatusResult(
            project_id=project_id,
            state=ProjectControlsState.CONFIGURED,
            settings=settings,
        )

    # --- the one transactional mechanism ----------------------------------

    def configure(
        self,
        *,
        principal_id: str,
        actor: ConstraintMutationActor,
        project_id: str,
        timezone_name: str,
        idempotency_key: str,
        expected_version: int | None = None,
        client_context: str | None = None,
        correlation_id: str | None = None,
    ) -> ProjectControlsConfigurationResult:
        """State this Project's Constraint calendar, or say why it was not stated.

        The order below is the contract. The key is validated before anything
        is read, the timezone before anything is written, the Project lock
        before the ledger is consulted, and the settings row after the Project
        has already been qualified.

        Nothing here touches a Constraint, a revision, a receipt of the
        Constraint ledgers, a Category, or an allocator sequence: changing which
        calendar a Project's dates are *read* on does not rewrite the dates, and
        this service holds no method that could.
        """
        _validate_idempotency_key(idempotency_key)
        # Before any write, and before the Project is even looked at: an
        # unknown zone is a malformed request, and answering it after a lock
        # would make a refusal depend on whether the caller owned the Project.
        validated_timezone = validate_project_timezone_name(timezone_name)
        digest = _digest(
            operation=CONSTRAINT_PROJECT_SETTINGS_ACTION,
            project_id=project_id,
            timezone_name=validated_timezone,
            expected_version=expected_version,
        )

        try:
            return self._configure_once(
                principal_id=principal_id,
                actor=actor,
                project_id=project_id,
                timezone_name=validated_timezone,
                idempotency_key=idempotency_key,
                expected_version=expected_version,
                client_context=client_context,
                correlation_id=correlation_id,
                digest=digest,
            )
        except ConstraintProjectSettingsHistoryKeyConflictError:
            # The key was bound by a request this transaction could not see.
            # Same Project is impossible here -- `lock_project` serialises those
            # and the loser reads the winner's committed row through the replay
            # gate -- so what reaches this is a key reused across Projects, and
            # the losing transaction has already rolled back. The stored row is
            # then read in a fresh transaction, because the aborted one can
            # answer nothing, and the digest decides which answer it is. A raw
            # `IntegrityError` never leaves this module for this constraint.
            return self._resolve_bound_key(principal_id, idempotency_key, digest)

    def _configure_once(
        self,
        *,
        principal_id: str,
        actor: ConstraintMutationActor,
        project_id: str,
        timezone_name: str,
        idempotency_key: str,
        expected_version: int | None,
        client_context: str | None,
        correlation_id: str | None,
        digest: str,
    ) -> ProjectControlsConfigurationResult:
        """One transaction: lock, replay gate, version comparison, write, receipt."""
        pending_unavailable = False
        pending_not_configured: ConstraintProjectSettingsHistoryEntry | None = None
        pending_idempotency_conflict = False
        pending_conflict: (
            tuple[ConstraintProjectSettings, ConstraintProjectSettingsHistoryEntry] | None
        ) = None
        result: ProjectControlsConfigurationResult | None = None

        with self._unit_of_work() as uow:
            # The canonical ownership proof, and the serialisation point. Both,
            # from one call: a row inside this Principal's partition or `None`.
            if uow.projects.lock_project(principal_id, project_id) is None:
                pending_unavailable = True
            else:
                prior = uow.constraints.get_project_settings_history_by_idempotency_key(
                    principal_id, idempotency_key
                )
                if prior is not None and prior.request_digest != digest:
                    pending_idempotency_conflict = True
                elif prior is not None:
                    result = _replayed(prior)
                else:
                    now = self._clock()
                    # Only now, and only for a Project already qualified: an
                    # absent row here is "nobody has configured this", never
                    # "this is not yours".
                    settings = uow.constraints.get_project_settings_for_update(
                        principal_id, project_id
                    )
                    if settings is None and expected_version is not None:
                        pending_not_configured = self._record(
                            uow=uow,
                            principal_id=principal_id,
                            project_id=project_id,
                            actor=actor,
                            outcome=ConstraintProjectSettingsOutcome.REJECTED,
                            before_version=None,
                            after_version=None,
                            occurred_at=now,
                            idempotency_key=idempotency_key,
                            request_digest=digest,
                            client_context=client_context,
                            correlation_id=correlation_id,
                            failure_code=_FAILURE_NOT_CONFIGURED,
                        )
                    elif settings is None:
                        result = self._apply(
                            uow=uow,
                            principal_id=principal_id,
                            project_id=project_id,
                            actor=actor,
                            current=None,
                            timezone_name=timezone_name,
                            occurred_at=now,
                            idempotency_key=idempotency_key,
                            request_digest=digest,
                            client_context=client_context,
                            correlation_id=correlation_id,
                        )
                    elif expected_version is not None and settings.version != expected_version:
                        rejected = self._record(
                            uow=uow,
                            principal_id=principal_id,
                            project_id=project_id,
                            actor=actor,
                            outcome=ConstraintProjectSettingsOutcome.REJECTED,
                            before_version=settings.version,
                            after_version=settings.version,
                            occurred_at=now,
                            idempotency_key=idempotency_key,
                            request_digest=digest,
                            client_context=client_context,
                            correlation_id=correlation_id,
                            failure_code=_FAILURE_VERSION_CONFLICT,
                        )
                        pending_conflict = (settings, rejected)
                    elif settings.timezone_name == timezone_name:
                        # Asked for the calendar it already has. One receipt for
                        # a new key -- the attempt happened and is accountable --
                        # and no settings write, so the version does not move.
                        receipt = self._record(
                            uow=uow,
                            principal_id=principal_id,
                            project_id=project_id,
                            actor=actor,
                            outcome=ConstraintProjectSettingsOutcome.NO_OP,
                            before_version=settings.version,
                            after_version=settings.version,
                            occurred_at=now,
                            idempotency_key=idempotency_key,
                            request_digest=digest,
                            client_context=client_context,
                            correlation_id=correlation_id,
                            resulting_timezone_name=settings.timezone_name,
                            resulting_settings_updated_at=settings.updated_at,
                        )
                        result = ProjectControlsConfigurationResult(
                            disposition=ProjectControlsDisposition.NO_OP,
                            project_id=project_id,
                            timezone_name=settings.timezone_name,
                            settings_version=settings.version,
                            settings_updated_at=settings.updated_at,
                            receipt=receipt,
                        )
                    elif expected_version is None:
                        rejected = self._record(
                            uow=uow,
                            principal_id=principal_id,
                            project_id=project_id,
                            actor=actor,
                            outcome=ConstraintProjectSettingsOutcome.REJECTED,
                            before_version=settings.version,
                            after_version=settings.version,
                            occurred_at=now,
                            idempotency_key=idempotency_key,
                            request_digest=digest,
                            client_context=client_context,
                            correlation_id=correlation_id,
                            failure_code=_FAILURE_VERSION_REQUIRED,
                        )
                        pending_conflict = (settings, rejected)
                    else:
                        result = self._apply(
                            uow=uow,
                            principal_id=principal_id,
                            project_id=project_id,
                            actor=actor,
                            current=settings,
                            timezone_name=timezone_name,
                            occurred_at=now,
                            idempotency_key=idempotency_key,
                            request_digest=digest,
                            client_context=client_context,
                            correlation_id=correlation_id,
                        )

        # Outside the block, always: every refusal above that wrote a `REJECTED`
        # receipt needs that receipt committed, and raising inside would roll it
        # back along with everything else the transaction held.
        if pending_unavailable:
            raise ProjectControlsProjectUnavailableError(
                "the project is not available to this principal"
            )
        if pending_idempotency_conflict:
            raise ProjectControlsIdempotencyConflictError(
                "the idempotency key was used for different normalized content"
            )
        if pending_not_configured is not None:
            raise ProjectControlsNotConfiguredError(
                "the project has no constraint settings to update"
            )
        if pending_conflict is not None:
            raise ProjectControlsVersionConflictError(*pending_conflict)
        if result is None:  # pragma: no cover - every branch above decides one
            raise RuntimeError("a configure attempt produced neither a result nor a refusal")
        return result

    def _resolve_bound_key(
        self, principal_id: str, idempotency_key: str, digest: str
    ) -> ProjectControlsConfigurationResult:
        """Read the row that took the key, and let its digest decide the answer."""
        with self._unit_of_work() as uow:
            prior = uow.constraints.get_project_settings_history_by_idempotency_key(
                principal_id, idempotency_key
            )
        if prior is None:  # pragma: no cover - the unique index said it is there
            raise RuntimeError("a bound idempotency key names a receipt that still exists")
        if prior.request_digest != digest:
            raise ProjectControlsIdempotencyConflictError(
                "the idempotency key was used for different normalized content"
            )
        return _replayed(prior)

    # --- writes -----------------------------------------------------------

    def _apply(
        self,
        *,
        uow: ConstraintManagementUnitOfWork,
        principal_id: str,
        project_id: str,
        actor: ConstraintMutationActor,
        current: ConstraintProjectSettings | None,
        timezone_name: str,
        occurred_at: datetime,
        idempotency_key: str,
        request_digest: str,
        client_context: str | None,
        correlation_id: str | None,
    ) -> ProjectControlsConfigurationResult:
        """Insert or update the one settings row, and account for it.

        An absent row is version 0, so the first configure writes version 1 —
        which is the arithmetic the stored `APPLIED` pairing CHECK enforces and
        which `ConstraintProjectSettingsHistoryEntry` restates.
        """
        before_version = None if current is None else current.version
        settings = ConstraintProjectSettings(
            principal_id=principal_id,
            project_id=project_id,
            timezone_name=timezone_name,
            version=(before_version or 0) + 1,
            created_at=occurred_at if current is None else current.created_at,
            updated_at=occurred_at,
        )
        if current is None:
            uow.constraints.insert_project_settings(principal_id, settings)
        else:
            uow.constraints.update_project_settings(principal_id, settings)
        receipt = self._record(
            uow=uow,
            principal_id=principal_id,
            project_id=project_id,
            actor=actor,
            outcome=ConstraintProjectSettingsOutcome.APPLIED,
            before_version=before_version,
            after_version=settings.version,
            occurred_at=occurred_at,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            client_context=client_context,
            correlation_id=correlation_id,
            resulting_timezone_name=settings.timezone_name,
            resulting_settings_updated_at=settings.updated_at,
        )
        return ProjectControlsConfigurationResult(
            disposition=ProjectControlsDisposition.APPLIED,
            project_id=project_id,
            timezone_name=settings.timezone_name,
            settings_version=settings.version,
            settings_updated_at=settings.updated_at,
            receipt=receipt,
        )

    def _record(
        self,
        *,
        uow: ConstraintManagementUnitOfWork,
        principal_id: str,
        project_id: str,
        actor: ConstraintMutationActor,
        outcome: ConstraintProjectSettingsOutcome,
        before_version: int | None,
        after_version: int | None,
        occurred_at: datetime,
        idempotency_key: str,
        request_digest: str,
        client_context: str | None,
        correlation_id: str | None,
        resulting_timezone_name: str | None = None,
        resulting_settings_updated_at: datetime | None = None,
        failure_code: str | None = None,
    ) -> ConstraintProjectSettingsHistoryEntry:
        """Append one settings receipt inside this transaction.

        `failure_detail` is deliberately never supplied. The stored column
        exists and is bounded, but every refusal this service can produce is
        already fully described by its `failure_code`, and a second free-text
        field would be the one place a request value could reach a log.
        """
        entry = ConstraintProjectSettingsHistoryEntry(
            history_id=issue_settings_history_id(),
            principal_id=principal_id,
            project_id=project_id,
            actor=actor,
            outcome=outcome,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            occurred_at=occurred_at,
            recorded_at=self._clock(),
            before_settings_version=before_version,
            after_settings_version=after_version,
            resulting_timezone_name=resulting_timezone_name,
            resulting_settings_updated_at=resulting_settings_updated_at,
            client_context=client_context,
            correlation_id=correlation_id,
            failure_code=failure_code,
        )
        uow.constraints.insert_project_settings_history(principal_id, entry)
        return entry


def _replayed(prior: ConstraintProjectSettingsHistoryEntry) -> ProjectControlsConfigurationResult:
    """The original answer, rebuilt from the receipt that recorded it.

    Only a succeeded receipt can be replayed, which the stored snapshot pairing
    already guarantees: `resulting_timezone_name` and
    `resulting_settings_updated_at` are present exactly when the outcome was
    `APPLIED` or `NO_OP`. A `REJECTED` receipt is never reached here, because a
    rejection raises rather than binding a key to an answer — the transaction
    that wrote it committed the receipt and then refused, and a retry carrying
    that key finds the rejection's digest and is told so.
    """
    if (
        prior.resulting_timezone_name is None
        or prior.resulting_settings_updated_at is None
        or prior.after_settings_version is None
    ):
        raise ProjectControlsIdempotencyConflictError(
            "the idempotency key is bound to an attempt that produced no settings"
        )
    return ProjectControlsConfigurationResult(
        disposition=ProjectControlsDisposition.REPLAYED,
        project_id=prior.project_id,
        timezone_name=prior.resulting_timezone_name,
        settings_version=prior.after_settings_version,
        settings_updated_at=prior.resulting_settings_updated_at,
        receipt=prior,
    )


def _validate_idempotency_key(idempotency_key: object) -> str:
    """Refuse a key that is not a well-formed one, by type and then by shape.

    Type first and truthiness never, the discipline
    `tests/architecture/test_every_write_validates_its_idempotency_key.py`
    exists to keep: `if not key` accepts an integer and hands it to code that
    assumes a string. The pattern is the domain's own, so the value this
    service accepts is exactly the value the stored receipt will accept.
    """
    if not isinstance(idempotency_key, str):
        raise ProjectControlsOperationError(
            "project_controls_idempotency_key_not_a_string",
            "an idempotency key is a string",
        )
    if not CONSTRAINT_IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise ProjectControlsOperationError(
            "project_controls_idempotency_key_malformed",
            "an idempotency key is 8-128 characters of [A-Za-z0-9_-]",
        )
    return idempotency_key


def _digest(**values: object) -> str:
    """The SHA-256 of one configure request's normalized semantic content.

    The identical function `constraint_management._digest` is, spelled here
    rather than imported for the reason the two history vocabularies are
    spelled separately: what this plane counts as the same request is
    this plane's own decision, and a shared helper would make one plane's change
    silently redefine the other's replay identity.

    What reaches it is four named values and nothing else. No `principal_id`
    (the key is already scoped to it), no actor, no client context, no
    correlation identifier, no clock reading, and no transport representation:
    none of them changes what was asked for, and including one would make an
    honest retry look like a different request.
    """
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
