"""Relationship Memory use cases: what the server decides, and what the caller may.

One service, and its whole job is the line between the two. A transport hands it
a command carrying only what a user could legitimately have chosen — the
subject, the kind, the words, when it applies, where it applies — and this module
supplies everything else from authenticated context and policy:

* the owning Principal, from `Authorization` and never from a payload;
* the authority, which is always `user_authored_private_note` on this path,
  because a public create or revise that could claim `source_backed_assertion`
  would let a caller manufacture a finding out of a note;
* the classification, from the kind's own floor, so a `sensitivity` is
  `restricted_local` whether or not the caller thought about it;
* cloud eligibility, which is false and has no path to true;
* the actor class, the receipt time, and the correlation identity.

**The caller cannot widen any of them, and the mechanism is absence rather than
validation.** The command dataclasses have no `authority`, `classification`,
`cloud_eligible`, `principal_id`, `recorded_at`, `actor` or `review_state` field,
so a payload naming one is refused by the constructor before this module runs.
There is nothing here that reads such a field and decides to ignore it, because
a field that can be sent is a field a later change can start honouring.

**Restriction is monotonic, and only in one direction.** A caller may not choose
a classification at all in v0.1. What it can do is choose the `sensitivity`
kind, which raises the floor. Nothing lowers one.

**A model cannot reach this module's writes.** The proposal plane
(`relationship_memory_proposals`) is where a source-, rule- or model-derived
candidate lives until a reviewer decides, and acceptance goes through the Review
path rather than through `create`. That separation is why `MemoryActorClass.USER`
is hard-coded here rather than taken from the request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from my_pa.contracts.ports import (
    MemoryDetail,
    MemoryPage,
    MemoryWriteRequest,
    RelationshipMemoryRepository,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.memory import (
    DIRECT_USER_AUTHORITY,
    MemoryActorClass,
    MemoryAdmission,
    MemoryKind,
    MemoryLifecycle,
    MemoryOperation,
    RelationshipMemoryVersion,
    classification_floor_for,
    statement_digest,
    validate_statement,
    validate_structured_value,
)
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "ArchiveMemoryCommand",
    "CreateMemoryCommand",
    "RelationshipMemoryService",
    "ReviseMemoryCommand",
]


@dataclass(frozen=True, slots=True)
class CreateMemoryCommand:
    """One direct user-authored memory, with the Principal already resolved."""

    principal_id: str
    subject_entity_id: str
    memory_kind: MemoryKind
    statement: str
    structured_value: dict[str, Any] | None
    context_links: tuple[dict[str, str], ...]
    pinned: bool
    observed_at: datetime | None
    effective_from: datetime | None
    effective_to: datetime | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ReviseMemoryCommand:
    """One successor version, with the Principal already resolved."""

    principal_id: str
    memory_id: str
    expected_version: int
    statement: str
    memory_kind: MemoryKind | None
    structured_value: dict[str, Any] | None
    context_links: tuple[dict[str, str], ...]
    pinned: bool
    observed_at: datetime | None
    effective_from: datetime | None
    effective_to: datetime | None
    correction_reason: str | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ArchiveMemoryCommand:
    """One reversible lifecycle transition, with the Principal already resolved."""

    principal_id: str
    memory_id: str
    expected_version: int
    idempotency_key: str


class RelationshipMemoryService:
    """Route each Relationship Memory command to the port that answers it."""

    def create(
        self,
        repository: RelationshipMemoryRepository,
        command: CreateMemoryCommand,
        *,
        at: datetime,
    ) -> MemoryAdmission:
        """Record the first immutable version of a new memory."""
        statement = validate_statement(command.statement)
        structured = validate_structured_value(command.memory_kind, command.structured_value)
        request = self._request(
            MemoryOperation.CREATE,
            principal_id=command.principal_id,
            memory_id=None,
            expected_version=None,
            subject_entity_id=command.subject_entity_id,
            memory_kind=command.memory_kind,
            statement=statement,
            structured_value=structured,
            context_links=command.context_links,
            pinned=command.pinned,
            observed_at=command.observed_at,
            effective_from=command.effective_from,
            effective_to=command.effective_to,
            correction_reason=None,
            idempotency_key=command.idempotency_key,
            at=at,
        )
        return self._admit(repository, request)

    def revise(
        self,
        repository: RelationshipMemoryRepository,
        command: ReviseMemoryCommand,
        *,
        at: datetime,
        current_kind: MemoryKind,
    ) -> MemoryAdmission:
        """Append a successor version, refusing a stale expected version.

        `current_kind` is the kind the aggregate holds now, read by the caller.
        A revision that does not restate the kind keeps it, and one that does
        revalidates the structured value against the *new* kind — otherwise a
        caller could move an `important_date` to `general_note` and leave a date
        envelope behind that nothing would validate again.
        """
        statement = validate_statement(command.statement)
        kind = command.memory_kind or current_kind
        structured = validate_structured_value(kind, command.structured_value)
        request = self._request(
            MemoryOperation.REVISE,
            principal_id=command.principal_id,
            memory_id=command.memory_id,
            expected_version=command.expected_version,
            subject_entity_id=None,
            memory_kind=kind,
            statement=statement,
            structured_value=structured,
            context_links=command.context_links,
            pinned=command.pinned,
            observed_at=command.observed_at,
            effective_from=command.effective_from,
            effective_to=command.effective_to,
            correction_reason=command.correction_reason,
            idempotency_key=command.idempotency_key,
            at=at,
        )
        return self._admit(repository, request)

    def archive(
        self,
        repository: RelationshipMemoryRepository,
        command: ArchiveMemoryCommand,
        *,
        at: datetime,
    ) -> MemoryAdmission:
        """Withdraw one memory from the current set. Reversible; not a delete."""
        return self._transition(repository, command, MemoryOperation.ARCHIVE, at=at)

    def restore(
        self,
        repository: RelationshipMemoryRepository,
        command: ArchiveMemoryCommand,
        *,
        at: datetime,
    ) -> MemoryAdmission:
        """Return one archived memory to the current set."""
        return self._transition(repository, command, MemoryOperation.RESTORE, at=at)

    # ---- reads -----------------------------------------------------------

    def get(
        self, repository: RelationshipMemoryRepository, memory_id: str, *, principal_id: str
    ) -> MemoryDetail | None:
        return repository.detail(memory_id, principal_id=principal_id)

    def list_for_entity(
        self,
        repository: RelationshipMemoryRepository,
        *,
        principal_id: str,
        subject_entity_id: str,
        limit: int,
        kinds: frozenset[MemoryKind] | None,
        lifecycle: MemoryLifecycle,
        context_entity_id: str | None,
        as_of: datetime | None,
        after_memory_id: str | None,
    ) -> MemoryPage:
        """One bounded page of one entity's memories.

        `include_restricted` is *not* a parameter a caller reaches. A restricted
        memory is disclosed on this path because the request already names one
        entity the Principal owns and holds the read purpose for it, which is the
        narrow profile view the contract admits it in — and it is withheld from
        `search`, which is the broad one. The distinction is made here rather
        than by the caller so a transport cannot ask for the wider behaviour.
        """
        return repository.page_for_entity(
            subject_entity_id,
            principal_id=principal_id,
            limit=limit,
            kinds=kinds,
            lifecycle=lifecycle,
            context_entity_id=context_entity_id,
            as_of=as_of,
            after_memory_id=after_memory_id,
            include_restricted=True,
        )

    def search(
        self,
        repository: RelationshipMemoryRepository,
        *,
        principal_id: str,
        query: str,
        limit: int,
        subject_entity_id: str | None,
        kinds: frozenset[MemoryKind] | None,
        after_memory_id: str | None,
    ) -> MemoryPage:
        return repository.search(
            query,
            principal_id=principal_id,
            limit=limit,
            subject_entity_id=subject_entity_id,
            kinds=kinds,
            after_memory_id=after_memory_id,
        )

    def history(
        self,
        repository: RelationshipMemoryRepository,
        memory_id: str,
        *,
        principal_id: str,
        limit: int,
        after_version_id: str | None,
    ) -> tuple[tuple[RelationshipMemoryVersion, ...], bool]:
        return repository.history(
            memory_id,
            principal_id=principal_id,
            limit=limit,
            after_version_id=after_version_id,
        )

    # ---- the one write path ----------------------------------------------

    def _transition(
        self,
        repository: RelationshipMemoryRepository,
        command: ArchiveMemoryCommand,
        operation: MemoryOperation,
        *,
        at: datetime,
    ) -> MemoryAdmission:
        request = self._request(
            operation,
            principal_id=command.principal_id,
            memory_id=command.memory_id,
            expected_version=command.expected_version,
            subject_entity_id=None,
            memory_kind=None,
            statement=None,
            structured_value=None,
            context_links=(),
            pinned=False,
            observed_at=None,
            effective_from=None,
            effective_to=None,
            correction_reason=None,
            idempotency_key=command.idempotency_key,
            at=at,
        )
        return self._admit(repository, request)

    def _request(
        self,
        operation: MemoryOperation,
        *,
        principal_id: str,
        memory_id: str | None,
        expected_version: int | None,
        subject_entity_id: str | None,
        memory_kind: MemoryKind | None,
        statement: str | None,
        structured_value: dict[str, Any] | None,
        context_links: tuple[dict[str, str], ...],
        pinned: bool,
        observed_at: datetime | None,
        effective_from: datetime | None,
        effective_to: datetime | None,
        correction_reason: str | None,
        idempotency_key: str,
        at: datetime,
    ) -> MemoryWriteRequest:
        """The one place server-owned fields are decided. See the module docstring.

        A transition carries no kind, so it takes the floor of the least
        restrictive classification — which is never stored, because archive and
        restore write no version. The value is supplied only because
        `MemoryWriteRequest` is one shape for four operations.
        """
        floor = classification_floor_for(memory_kind) if memory_kind else None
        return MemoryWriteRequest(
            operation=operation,
            memory_id=memory_id,
            memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
            expected_version=expected_version,
            principal_id=principal_id,
            subject_entity_id=subject_entity_id,
            memory_kind=memory_kind,
            statement=statement,
            statement_sha256=None if statement is None else statement_digest(statement),
            structured_value=structured_value,
            authority=DIRECT_USER_AUTHORITY,
            classification=floor or classification_floor_for(MemoryKind.GENERAL_NOTE),
            created_by_actor=MemoryActorClass.USER,
            context_links=context_links,
            pinned=pinned,
            observed_at=observed_at,
            effective_from=effective_from,
            effective_to=effective_to,
            correction_reason=correction_reason,
            idempotency_key=idempotency_key,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            server_received_at=at,
        )

    def _admit(
        self, repository: RelationshipMemoryRepository, request: MemoryWriteRequest
    ) -> MemoryAdmission:
        """Replay first, then write. See `ManagedDocumentService._write` for the shape.

        The replay pre-read happens after the request is built, because the
        payload digest is what decides whether a key in use is a replay or a
        conflict and the request is what computes it. It is an optimisation and
        never the decision: `admit` still relies on the unique constraint, so two
        concurrent writers that both read `None` still produce one memory.
        """
        replayed = repository.replay_for(
            request.idempotency_key, request.payload_digest, principal_id=request.principal_id
        )
        if replayed is not None:
            return MemoryAdmission(receipt=replayed, created=False)
        return repository.admit(request)
