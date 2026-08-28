"""The Relationship Memory plane, in SQL.

One class, and every statement it issues reaches the partition through
`persistence.principal_scope`. That is not decoration: a memory is the most
private thing this product stores, the identifiers are globally unique, and a
foreign-key constraint proves a row *exists* rather than that it belongs to the
acting Principal. So same-Principal ownership of the subject entity, of every
context target and of the memory itself is proven here, before the insert, which
is the only place it can be proven.

**A foreign memory answers exactly what an absent one answers.** Every read
returns `None` or an empty page for a memory another Principal holds, so a
refusal cannot be used to learn that an identifier names something.

**Idempotency is the unique constraint, not the pre-read.** `replay_for` is an
optimisation that lets an ordinary retry return without touching the aggregate;
`admit` still relies on `a_memory_key_admits_one_submission_per_principal`, so
two concurrent writers that both read `None` still produce one memory. The
pre-read takes the payload digest for the reason
`ManagedDocumentRepository.replay_for` states: a lookup on the key alone would
answer a *conflicting* request with the original receipt, reporting a write that
never happened as durable.

**Optimistic concurrency is `UPDATE … WHERE version = expected`.** The row count
is the answer: one means this writer held the version it claimed, zero means it
did not, and the second case raises before any successor version is inserted.
Nothing here reads the version and then writes, which would be the check-then-act
race the counter exists to close.

**Archive and restore write no statement.** They advance the aggregate version
and the lifecycle and leave the version chain alone, because a lifecycle
transition is not a correction. The submission row still names the current
version, so a replayed archive returns the same receipt as the original.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Row,
    Text,
    bindparam,
    column,
    func,
    insert,
    not_,
    or_,
    select,
    text,
    true,
    tuple_,
    union,
    update,
)
from sqlalchemy.engine import Connection
from sqlalchemy.sql.elements import ColumnElement

from my_pa.contracts.ports import (
    MemoryDetail,
    MemoryListingFacts,
    MemoryPage,
    MemoryWriteRequest,
    RelationshipMemoryRepository,
    UnknownScopeError,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.relationship.entity import EntityStatus, EntityType
from my_pa.domain.relationship.identity_correction import (
    IdentityEffect,
    IdentityEffectDraft,
    IdentityEffectFamily,
    IdentityEffectKind,
)
from my_pa.domain.relationship.memory import (
    ContextLinkAuthority,
    ContextLinkRole,
    ContextLinkTargetType,
    MemoryActorClass,
    MemoryAdmission,
    MemoryAuthority,
    MemoryConflictError,
    MemoryContextLink,
    MemoryKind,
    MemoryLifecycle,
    MemoryOperation,
    MemoryProposalState,
    MemoryReceipt,
    MergedSubjectError,
    RelationshipMemory,
    RelationshipMemoryError,
    RelationshipMemoryVersion,
    StaleMemoryVersionError,
    check_kind_permits_subject,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.identifier_claim_lock import lock_entity_mutation_scopes
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.relationship_memory_context import (
    requested_entity_context_ids,
    require_own_writable_context_targets,
)
from my_pa.infrastructure.persistence.tables import (
    entities,
    relationship_memories,
    relationship_memory_context_links,
    relationship_memory_evidence_links,
    relationship_memory_proposals,
    relationship_memory_submissions,
    relationship_memory_versions,
)

__all__ = ["SqlRelationshipMemoryRepository"]

#: The text-search configuration this plane matches under.
#:
#: `simple` rather than `english`, the same choice `capture_search` makes and for
#: a sharper version of its reason: a memory statement is one short sentence a
#: person wrote, and stemming "interests" to "interest" matters far less than
#: matching a proper noun, a project name or a spelling the user chose exactly as
#: they wrote it. It is a SQL literal and never a bound parameter, because a
#: bound configuration compiles to `to_tsvector($1, …)` and stops matching the
#: functional index.
_SEARCH_CONFIG = "simple"

_MEMORY_COLUMNS = (
    relationship_memories.c.memory_id,
    relationship_memories.c.principal_id,
    relationship_memories.c.subject_entity_id,
    relationship_memories.c.memory_kind,
    relationship_memories.c.lifecycle_state,
    relationship_memories.c.current_version_id,
    relationship_memories.c.current_version_number,
    relationship_memories.c.version,
    relationship_memories.c.pinned,
    relationship_memories.c.created_at,
    relationship_memories.c.updated_at,
    relationship_memories.c.archived_at,
)

_VERSION_COLUMNS = (
    relationship_memory_versions.c.memory_version_id,
    relationship_memory_versions.c.memory_id,
    relationship_memory_versions.c.principal_id,
    relationship_memory_versions.c.version_number,
    relationship_memory_versions.c.statement_text,
    relationship_memory_versions.c.statement_sha256,
    relationship_memory_versions.c.structured_value,
    relationship_memory_versions.c.memory_kind,
    relationship_memory_versions.c.authority,
    relationship_memory_versions.c.classification,
    relationship_memory_versions.c.cloud_eligible,
    relationship_memory_versions.c.created_by_actor,
    relationship_memory_versions.c.observed_at,
    relationship_memory_versions.c.effective_from,
    relationship_memory_versions.c.effective_to,
    relationship_memory_versions.c.recorded_at,
    relationship_memory_versions.c.prior_version_id,
    relationship_memory_versions.c.correction_reason,
    relationship_memory_versions.c.proposal_id,
    relationship_memory_versions.c.review_case_id,
    relationship_memory_versions.c.idempotency_key,
    relationship_memory_versions.c.correlation_id,
)


def _mine(table: Any, principal_id: str) -> Any:  # noqa: ANN401 - a SQLAlchemy Table
    """`table` constrained to the given Principal, through the one guard."""
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Any, principal_id: str, values: dict[str, object]) -> dict[str, object]:  # noqa: ANN401
    """`values` stamped with the given Principal for `table`, through the one guard."""
    return principal_bound_values(values, table, capture_context(principal_id))


def _to_memory(row: Row[Any]) -> RelationshipMemory:
    return RelationshipMemory(
        memory_id=row.memory_id,
        principal_id=row.principal_id,
        subject_entity_id=row.subject_entity_id,
        memory_kind=MemoryKind(row.memory_kind),
        lifecycle_state=MemoryLifecycle(row.lifecycle_state),
        current_version_id=row.current_version_id,
        current_version_number=row.current_version_number,
        version=row.version,
        pinned=row.pinned,
        created_at=row.created_at,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
    )


def _to_version(row: Any) -> RelationshipMemoryVersion:  # noqa: ANN401 - a Row or a labelled view
    """One stored version, from a `Row` or from `_VersionRow` over a joined one.

    `Any` rather than `Row`, and that is the honest annotation: the context-card
    query selects both tables at once and reads its version columns through
    `_VersionRow`, which is not a `Row` and cannot be. Narrowing the parameter
    would be a suppression at the call site instead, and the
    dependency-floor job forbids one.
    """
    structured = row.structured_value
    if isinstance(structured, str):
        structured = json.loads(structured)
    return RelationshipMemoryVersion(
        memory_version_id=row.memory_version_id,
        memory_id=row.memory_id,
        principal_id=row.principal_id,
        version_number=row.version_number,
        statement=row.statement_text,
        statement_sha256=row.statement_sha256,
        structured_value=structured,
        memory_kind=MemoryKind(row.memory_kind),
        authority=MemoryAuthority(row.authority),
        classification=Classification(row.classification),
        cloud_eligible=row.cloud_eligible,
        created_by_actor=MemoryActorClass(row.created_by_actor),
        observed_at=row.observed_at,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        recorded_at=row.recorded_at,
        prior_version_id=row.prior_version_id,
        correction_reason=row.correction_reason,
        proposal_id=row.proposal_id,
        review_case_id=row.review_case_id,
        idempotency_key=row.idempotency_key,
        correlation_id=row.correlation_id,
    )


class SqlRelationshipMemoryRepository(RelationshipMemoryRepository):
    """SQLAlchemy implementation of `RelationshipMemoryRepository`.

    Takes the connection rather than opening one, exactly as
    `SqlEntityRepository` does: the caller owns the transaction and this class
    only issues statements on it.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    # ---- writes ----------------------------------------------------------

    def replay_for(
        self, idempotency_key: str, payload_digest: str, *, principal_id: str
    ) -> MemoryReceipt | None:
        row = self._connection.execute(
            select(
                relationship_memory_submissions.c.memory_id,
                relationship_memory_submissions.c.memory_version_id,
                relationship_memory_submissions.c.payload_sha256,
                relationship_memory_submissions.c.aggregate_version,
                relationship_memory_submissions.c.lifecycle_state,
                relationship_memory_submissions.c.server_received_at,
            ).where(
                _mine(relationship_memory_submissions, principal_id),
                relationship_memory_submissions.c.idempotency_key == idempotency_key,
            )
        ).one_or_none()
        if row is None:
            return None
        if row.payload_sha256 != payload_digest:
            raise MemoryConflictError("this idempotency key is bound to a different request")
        version = self._connection.execute(
            select(
                relationship_memory_versions.c.version_number,
                relationship_memory_versions.c.statement_sha256,
            ).where(
                _mine(relationship_memory_versions, principal_id),
                relationship_memory_versions.c.memory_version_id == row.memory_version_id,
            )
        ).one()
        return MemoryReceipt(
            memory_id=row.memory_id,
            memory_version_id=row.memory_version_id,
            version_number=version.version_number,
            aggregate_version=row.aggregate_version,
            lifecycle_state=MemoryLifecycle(row.lifecycle_state),
            idempotency_key=idempotency_key,
            statement_sha256=version.statement_sha256,
            issued_at=row.server_received_at,
            created=False,
        )

    def admit(self, request: MemoryWriteRequest) -> MemoryAdmission:
        if request.operation is MemoryOperation.CREATE:
            return self._create(request)
        return self._mutate(request)

    def _require_writable_subject(self, principal_id: str, subject_entity_id: str) -> EntityType:
        """The subject must be this Principal's and must not be merged away.

        A merged-away subject raises rather than being followed. Following it
        would rebind the caller's write to a different identity, turning a
        deliberate annotation about a historical person into one about the
        current one — a different statement than the user made.
        """
        row = self._connection.execute(
            select(
                entities.c.entity_id,
                entities.c.entity_type,
                entities.c.status,
                entities.c.superseded_by_entity_id,
            ).where(
                _mine(entities, principal_id),
                entities.c.entity_id == subject_entity_id,
            )
        ).one_or_none()
        if row is None:
            raise UnknownScopeError("a memory write names an entity outside this scope")
        if EntityStatus(row.status) is EntityStatus.MERGED_REDIRECT:
            raise MergedSubjectError(row.superseded_by_entity_id)
        return EntityType(row.entity_type)

    def _require_own_context_targets(
        self, principal_id: str, links: tuple[Mapping[str, str], ...]
    ) -> None:
        """Every context target belongs to this Principal, or the write is refused.

        Only `entity` targets are verifiable here, and the other three are
        refused outright rather than accepted unverified. That is narrower than
        the contract's candidate set on purpose: `situation`, `task` and
        `commitment` rows exist, but this plane holds no port to their partitions
        and admitting a link this repository cannot prove ownership of would be
        exactly the unvalidated polymorphic edge the target vocabulary exists to
        prevent. The enum keeps the three, so admitting them later is a
        repository change and not a schema migration.
        """
        require_own_writable_context_targets(self._connection, principal_id, links)

    @staticmethod
    def _requested_entity_context_ids(
        links: tuple[Mapping[str, str], ...],
    ) -> frozenset[str]:
        return requested_entity_context_ids(links)

    def _current_entity_context_ids(
        self, principal_id: str, memory_version_id: str
    ) -> frozenset[str]:
        return frozenset(
            str(row[0])
            for row in self._connection.execute(
                select(relationship_memory_context_links.c.target_id).where(
                    _mine(relationship_memory_context_links, principal_id),
                    relationship_memory_context_links.c.memory_version_id == memory_version_id,
                    relationship_memory_context_links.c.target_type
                    == ContextLinkTargetType.ENTITY.value,
                )
            ).all()
        )

    def _insert_version(
        self,
        request: MemoryWriteRequest,
        *,
        memory_id: str,
        version_number: int,
        prior_version_id: str | None,
        memory_kind: MemoryKind,
    ) -> None:
        self._connection.execute(
            insert(relationship_memory_versions).values(
                _bound(
                    relationship_memory_versions,
                    request.principal_id,
                    {
                        "memory_version_id": request.memory_version_id,
                        "memory_id": memory_id,
                        "version_number": version_number,
                        "statement_text": request.statement,
                        "statement_sha256": request.statement_sha256,
                        "structured_value": request.structured_value,
                        "memory_kind": memory_kind.value,
                        "authority": request.authority.value,
                        "classification": request.classification.value,
                        "cloud_eligible": False,
                        "created_by_actor": request.created_by_actor.value,
                        "observed_at": request.observed_at,
                        "effective_from": request.effective_from,
                        "effective_to": request.effective_to,
                        "recorded_at": request.server_received_at,
                        "prior_version_id": prior_version_id,
                        "correction_reason": request.correction_reason,
                        "proposal_id": request.proposal_id,
                        "review_case_id": request.review_case_id,
                        "idempotency_key": request.idempotency_key,
                        "correlation_id": request.correlation_id,
                    },
                )
            )
        )
        for link in request.context_links:
            self._connection.execute(
                insert(relationship_memory_context_links).values(
                    _bound(
                        relationship_memory_context_links,
                        request.principal_id,
                        {
                            "context_link_id": issue_identifier(
                                IdKind.RELATIONSHIP_MEMORY_CONTEXT_LINK
                            ),
                            "memory_version_id": request.memory_version_id,
                            "target_type": link["target_type"],
                            "target_id": link["target_id"],
                            "origin_subject_entity_id": (
                                link["target_id"] if link["target_type"] == "entity" else None
                            ),
                            "role": link["role"],
                            "authority": ContextLinkAuthority.USER_CONFIRMED.value,
                            "created_at": request.server_received_at,
                        },
                    )
                )
            )

    def _record_submission(
        self,
        request: MemoryWriteRequest,
        *,
        memory_id: str,
        aggregate_version: int,
        lifecycle: MemoryLifecycle,
    ) -> None:
        self._connection.execute(
            insert(relationship_memory_submissions).values(
                _bound(
                    relationship_memory_submissions,
                    request.principal_id,
                    {
                        "submission_id": issue_identifier(IdKind.RELATIONSHIP_MEMORY_SUBMISSION),
                        "idempotency_key": request.idempotency_key,
                        "correlation_id": request.correlation_id,
                        "operation": request.operation.value,
                        "payload_sha256": request.payload_digest,
                        "server_received_at": request.server_received_at,
                        "memory_id": memory_id,
                        "memory_version_id": request.memory_version_id,
                        "aggregate_version": aggregate_version,
                        "lifecycle_state": lifecycle.value,
                    },
                )
            )
        )

    def _create(self, request: MemoryWriteRequest) -> MemoryAdmission:
        subject_entity_id = request.subject_entity_id
        memory_kind = request.memory_kind
        if subject_entity_id is None or memory_kind is None:
            # `MemoryWriteRequest.__post_init__` already refuses both, so this is
            # a narrowing for the type checker rather than a second rule. It
            # raises rather than asserting: an assertion disappears under `-O`,
            # and a create reaching here without a subject would then insert a
            # row with a null one.
            raise RelationshipMemoryError("a memory creation names its subject and kind")
        context_entities = self._requested_entity_context_ids(request.context_links)
        lock_entity_mutation_scopes(
            self._connection,
            request.principal_id,
            {subject_entity_id, *context_entities},
        )
        entity_type = self._require_writable_subject(request.principal_id, subject_entity_id)
        # Checked here rather than in the application service because the
        # subject's type is a fact this read already has: asking for it again
        # a layer up would be a second query, and deciding without it would be
        # a Person-only kind admitted against an organization.
        check_kind_permits_subject(memory_kind, entity_type)
        self._require_own_context_targets(request.principal_id, request.context_links)
        for context_entity_id in context_entities:
            self._require_writable_subject(request.principal_id, context_entity_id)
        memory_id = issue_identifier(IdKind.RELATIONSHIP_MEMORY)
        self._connection.execute(
            insert(relationship_memories).values(
                _bound(
                    relationship_memories,
                    request.principal_id,
                    {
                        "memory_id": memory_id,
                        "subject_entity_id": subject_entity_id,
                        "origin_subject_entity_id": subject_entity_id,
                        "memory_kind": memory_kind.value,
                        "lifecycle_state": MemoryLifecycle.ACTIVE.value,
                        "current_version_id": request.memory_version_id,
                        "current_version_number": 1,
                        "version": 1,
                        "pinned": bool(request.pinned),
                        "created_at": request.server_received_at,
                        "updated_at": request.server_received_at,
                        "archived_at": None,
                    },
                )
            )
        )
        self._insert_version(
            request,
            memory_id=memory_id,
            version_number=1,
            prior_version_id=None,
            memory_kind=memory_kind,
        )
        self._record_submission(
            request,
            memory_id=memory_id,
            aggregate_version=1,
            lifecycle=MemoryLifecycle.ACTIVE,
        )
        return MemoryAdmission(
            receipt=MemoryReceipt(
                memory_id=memory_id,
                memory_version_id=request.memory_version_id,
                version_number=1,
                aggregate_version=1,
                lifecycle_state=MemoryLifecycle.ACTIVE,
                idempotency_key=request.idempotency_key,
                statement_sha256=str(request.statement_sha256),
                issued_at=request.server_received_at,
                created=True,
            ),
            created=True,
        )

    def _mutate(self, request: MemoryWriteRequest) -> MemoryAdmission:
        """Revise, archive or restore: one guarded `UPDATE` and, for a revise, a successor.

        The `UPDATE … WHERE version = expected` is the concurrency control and the
        existence check at once. Its row count is read before anything else is
        written, so a stale expectation leaves no partial state — there is no
        successor version to roll back because none was inserted.
        """
        memory_id = str(request.memory_id)
        observed = self._connection.execute(
            select(*_MEMORY_COLUMNS).where(
                _mine(relationship_memories, request.principal_id),
                relationship_memories.c.memory_id == memory_id,
            )
        ).one_or_none()
        if observed is None:
            raise UnknownScopeError("a memory write names a memory outside this scope")
        observed_context = self._current_entity_context_ids(
            request.principal_id, str(observed.current_version_id)
        )
        requested_context = self._requested_entity_context_ids(request.context_links)
        lock_entity_mutation_scopes(
            self._connection,
            request.principal_id,
            {str(observed.subject_entity_id), *observed_context, *requested_context},
        )
        current = self._connection.execute(
            select(*_MEMORY_COLUMNS).where(
                _mine(relationship_memories, request.principal_id),
                relationship_memories.c.memory_id == memory_id,
            )
        ).one_or_none()
        if current is None:
            raise UnknownScopeError("a memory write names a memory outside this scope")
        if current.subject_entity_id != observed.subject_entity_id:
            raise StaleMemoryVersionError("the memory subject changed while this write waited")
        if (
            self._current_entity_context_ids(request.principal_id, str(current.current_version_id))
            != observed_context
        ):
            raise StaleMemoryVersionError("the memory context changed while this write waited")
        if request.operation is MemoryOperation.RESTORE:
            # Checked on restore and not on archive: returning a memory to the
            # current set against an identity that has since been merged away
            # would put a live note on a person the user did not choose, while
            # withdrawing one from a merged-away subject is always safe.
            self._require_writable_subject(request.principal_id, current.subject_entity_id)
            for context_entity_id in observed_context:
                self._require_writable_subject(request.principal_id, context_entity_id)

        revising = request.operation is MemoryOperation.REVISE
        memory_kind = request.memory_kind or MemoryKind(current.memory_kind)
        if revising:
            entity_type = self._require_writable_subject(
                request.principal_id, current.subject_entity_id
            )
            check_kind_permits_subject(memory_kind, entity_type)
            self._require_own_context_targets(request.principal_id, request.context_links)
            for context_entity_id in requested_context:
                self._require_writable_subject(request.principal_id, context_entity_id)

        lifecycle = {
            MemoryOperation.REVISE: MemoryLifecycle(current.lifecycle_state),
            MemoryOperation.ARCHIVE: MemoryLifecycle.ARCHIVED,
            MemoryOperation.RESTORE: MemoryLifecycle.ACTIVE,
        }[request.operation]
        next_version = int(current.version) + 1
        next_number = int(current.current_version_number) + (1 if revising else 0)
        values: dict[str, Any] = {
            "version": next_version,
            "lifecycle_state": lifecycle.value,
            "updated_at": request.server_received_at,
            "archived_at": (
                request.server_received_at if lifecycle is MemoryLifecycle.ARCHIVED else None
            ),
        }
        if revising:
            values["current_version_id"] = request.memory_version_id
            values["current_version_number"] = next_number
            values["memory_kind"] = memory_kind.value
            if request.pinned is not None:
                # Omitted means keep it. Writing `False` here unconditionally is
                # what made an ordinary wording correction silently unpin a
                # pinned memory.
                values["pinned"] = request.pinned
        updated = self._connection.execute(
            update(relationship_memories)
            .where(
                _mine(relationship_memories, request.principal_id),
                relationship_memories.c.memory_id == memory_id,
                relationship_memories.c.version == request.expected_version,
            )
            .values(**values)
        ).rowcount
        if updated != 1:
            raise StaleMemoryVersionError("the expected memory version is stale")

        if revising:
            self._insert_version(
                request,
                memory_id=memory_id,
                version_number=next_number,
                prior_version_id=current.current_version_id,
                memory_kind=memory_kind,
            )
            recorded_version_id = request.memory_version_id
        else:
            # Archive and restore write no statement, so the submission names the
            # version that is still current. A replayed archive then returns the
            # same receipt the original did rather than a receipt for a version
            # that was never written.
            recorded_version_id = current.current_version_id
        self._record_submission(
            _with_version(request, recorded_version_id),
            memory_id=memory_id,
            aggregate_version=next_version,
            lifecycle=lifecycle,
        )
        digest = self._connection.execute(
            select(relationship_memory_versions.c.statement_sha256).where(
                _mine(relationship_memory_versions, request.principal_id),
                relationship_memory_versions.c.memory_version_id == recorded_version_id,
            )
        ).scalar_one()
        return MemoryAdmission(
            receipt=MemoryReceipt(
                memory_id=memory_id,
                memory_version_id=recorded_version_id,
                version_number=next_number,
                aggregate_version=next_version,
                lifecycle_state=lifecycle,
                idempotency_key=request.idempotency_key,
                statement_sha256=digest,
                issued_at=request.server_received_at,
                created=True,
            ),
            created=True,
        )

    # ---- reads -----------------------------------------------------------

    def detail(self, memory_id: str, *, principal_id: str) -> MemoryDetail | None:
        validate_identifier(memory_id, IdKind.RELATIONSHIP_MEMORY)
        row = self._connection.execute(
            select(*_MEMORY_COLUMNS).where(
                _mine(relationship_memories, principal_id),
                relationship_memories.c.memory_id == memory_id,
            )
        ).one_or_none()
        if row is None:
            return None
        memory = _to_memory(row)
        version_row = self._connection.execute(
            select(*_VERSION_COLUMNS).where(
                _mine(relationship_memory_versions, principal_id),
                relationship_memory_versions.c.memory_version_id == memory.current_version_id,
            )
        ).one()
        links = tuple(
            MemoryContextLink(
                context_link_id=link.context_link_id,
                memory_version_id=link.memory_version_id,
                principal_id=link.principal_id,
                target_type=ContextLinkTargetType(link.target_type),
                target_id=link.target_id,
                role=ContextLinkRole(link.role),
                authority=ContextLinkAuthority(link.authority),
                created_at=link.created_at,
            )
            for link in self._connection.execute(
                select(relationship_memory_context_links).where(
                    _mine(relationship_memory_context_links, principal_id),
                    relationship_memory_context_links.c.memory_version_id
                    == memory.current_version_id,
                )
            )
        )
        evidence = self._connection.execute(
            select(func.count())
            .select_from(relationship_memory_evidence_links)
            .where(
                _mine(relationship_memory_evidence_links, principal_id),
                relationship_memory_evidence_links.c.memory_version_id == memory.current_version_id,
            )
        ).scalar_one()
        canonical = self._connection.execute(
            select(entities.c.superseded_by_entity_id).where(
                _mine(entities, principal_id),
                entities.c.entity_id == memory.subject_entity_id,
            )
        ).scalar_one_or_none()
        return MemoryDetail(
            memory=memory,
            current_version=_to_version(version_row),
            context_links=links,
            evidence_count=int(evidence),
            canonical_entity_id=canonical,
        )

    def page_for_entity(
        self,
        subject_entity_id: str,
        *,
        principal_id: str,
        limit: int,
        kinds: frozenset[MemoryKind] | None = None,
        lifecycle: MemoryLifecycle = MemoryLifecycle.ACTIVE,
        context_entity_id: str | None = None,
        as_of: datetime | None = None,
        after_memory_id: str | None = None,
        include_restricted: bool = False,
    ) -> MemoryPage:
        validate_identifier(subject_entity_id, IdKind.ENTITY)
        if limit < 1:
            raise ValueError("a memory page contains at least one memory")
        current = relationship_memory_versions.alias("current")
        statement = (
            select(
                *_MEMORY_COLUMNS,
                current.c.statement_text,
                current.c.authority,
                current.c.classification,
            )
            .select_from(
                relationship_memories.join(
                    current,
                    current.c.memory_version_id == relationship_memories.c.current_version_id,
                )
            )
            .where(
                _mine(relationship_memories, principal_id),
                # The version alias carries the predicate too. The join through
                # the partitioned aggregate already confines these rows, so this
                # is redundant *today* — and that is the point: it makes the
                # guarantee a property of the statement rather than a property
                # of the join, so a later reader that changes the join condition
                # cannot widen the partition without noticing.
                _mine(current, principal_id),
                relationship_memories.c.subject_entity_id == subject_entity_id,
                relationship_memories.c.lifecycle_state == lifecycle.value,
            )
        )
        if kinds:
            statement = statement.where(
                relationship_memories.c.memory_kind.in_(sorted(k.value for k in kinds))
            )
        if as_of is not None:
            statement = statement.where(
                or_(current.c.effective_from.is_(None), current.c.effective_from <= as_of),
                or_(current.c.effective_to.is_(None), current.c.effective_to >= as_of),
            )
        if context_entity_id is not None:
            validate_identifier(context_entity_id, IdKind.ENTITY)
            scoped = (
                select(relationship_memory_context_links.c.memory_version_id)
                .where(
                    _mine(relationship_memory_context_links, principal_id),
                    relationship_memory_context_links.c.target_type
                    == ContextLinkTargetType.ENTITY.value,
                    relationship_memory_context_links.c.target_id == context_entity_id,
                )
                .scalar_subquery()
            )
            statement = statement.where(relationship_memories.c.current_version_id.in_(scoped))
        # **The keyset is the whole sort key, and it has to be.** This read orders
        # pinned memories first, so a cursor compared on `memory_id` alone names
        # a position in a *different* ordering than the one being paged: with one
        # pinned memory sorting ahead of a lower identifier, page two skips every
        # unpinned row whose identifier precedes the pinned one, and those rows
        # are unreachable by any page. Measured on three memories with one
        # pinned at `limit=1`, which lost one of the three entirely.
        #
        # `pinned DESC` is expressed as `NOT pinned ASC` so the comparison is one
        # ordinary tuple comparison in the same direction as the sort, rather
        # than an OR of two cases that has to be kept in step with the ORDER BY
        # by hand.
        # Annotated, and the annotation is load-bearing rather than decorative.
        # `not_` is typed loosely enough at the declared SQLAlchemy floor that
        # mypy cannot infer this, and the `dependency-floor` CI job checks the
        # floor rather than the resolved newest release — so an inference that
        # succeeds locally fails there. A suppression is the wrong fix: that job
        # exists to keep the declared minimum a checked claim.
        rank: ColumnElement[bool] = not_(relationship_memories.c.pinned)
        if after_memory_id is not None:
            validate_identifier(after_memory_id, IdKind.RELATIONSHIP_MEMORY)
            located = self._connection.execute(
                select(relationship_memories.c.pinned).where(
                    _mine(relationship_memories, principal_id),
                    relationship_memories.c.memory_id == after_memory_id,
                )
            ).one_or_none()
            # Refused rather than silently restarted: a cursor naming a memory
            # this Principal cannot read is not a position in their ordering, and
            # an empty page is indistinguishable from having reached the end.
            if located is None:
                raise UnknownScopeError("a memory cursor names a memory in this scope")
            # Bound parameters rather than inlined literals, the shape
            # `persistence.search` uses for its own keyset: the cursor is
            # caller-supplied and belongs in the parameter list, not in the
            # statement text.
            statement = statement.where(
                tuple_(rank, relationship_memories.c.memory_id)
                > tuple_(
                    bindparam("memory_cursor_rank", value=not located.pinned, type_=Boolean),
                    bindparam("memory_cursor_id", value=after_memory_id, type_=Text),
                )
            )
        rows = list(
            self._connection.execute(
                statement.order_by(rank, relationship_memories.c.memory_id).limit(limit + 1)
            )
        )
        return _page(rows, limit=limit, include_restricted=include_restricted)

    def search(
        self,
        query: str,
        *,
        principal_id: str,
        limit: int,
        subject_entity_id: str | None = None,
        kinds: frozenset[MemoryKind] | None = None,
        after_memory_id: str | None = None,
    ) -> MemoryPage:
        if limit < 1:
            raise ValueError("a memory page contains at least one memory")
        current = relationship_memory_versions.alias("current")
        vector = func.to_tsvector(text(f"'{_SEARCH_CONFIG}'"), current.c.statement_text)
        parsed = func.websearch_to_tsquery(text(f"'{_SEARCH_CONFIG}'"), query)
        statement = (
            select(
                *_MEMORY_COLUMNS,
                current.c.statement_text,
                current.c.authority,
                current.c.classification,
            )
            .select_from(
                relationship_memories.join(
                    current,
                    current.c.memory_version_id == relationship_memories.c.current_version_id,
                )
            )
            .where(
                _mine(relationship_memories, principal_id),
                # See `page_for_entity`: the predicate on the version alias is
                # redundant through the join and stated anyway, so the partition
                # is local to this statement.
                _mine(current, principal_id),
                relationship_memories.c.lifecycle_state == MemoryLifecycle.ACTIVE.value,
                # **The exclusion is a predicate, not a post-filter.** A
                # restricted memory is never selected, so it cannot reach a
                # count, a truncation flag or a cursor — which is what stops a
                # caller learning one exists by probing terms and watching the
                # page shape change.
                current.c.classification != Classification.RESTRICTED_LOCAL.value,
                vector.bool_op("@@")(parsed),
            )
        )
        if subject_entity_id is not None:
            validate_identifier(subject_entity_id, IdKind.ENTITY)
            statement = statement.where(
                relationship_memories.c.subject_entity_id == subject_entity_id
            )
        if kinds:
            statement = statement.where(
                relationship_memories.c.memory_kind.in_(sorted(k.value for k in kinds))
            )
        if after_memory_id is not None:
            validate_identifier(after_memory_id, IdKind.RELATIONSHIP_MEMORY)
            statement = statement.where(relationship_memories.c.memory_id > after_memory_id)
        rows = list(
            self._connection.execute(
                statement.order_by(relationship_memories.c.memory_id).limit(limit + 1)
            )
        )
        # `include_restricted=False` and no withheld count: the restricted rows
        # were never selected, so there is nothing to count and reporting a zero
        # here would be the only honest number anyway.
        return _page(rows, limit=limit, include_restricted=False)

    def history(
        self, memory_id: str, *, principal_id: str, limit: int, after_version_id: str | None = None
    ) -> tuple[tuple[RelationshipMemoryVersion, ...], bool]:
        validate_identifier(memory_id, IdKind.RELATIONSHIP_MEMORY)
        if limit < 1:
            raise ValueError("a history page contains at least one version")
        held = self._connection.execute(
            select(relationship_memories.c.memory_id).where(
                _mine(relationship_memories, principal_id),
                relationship_memories.c.memory_id == memory_id,
            )
        ).scalar_one_or_none()
        if held is None:
            return (), False
        statement = select(*_VERSION_COLUMNS).where(
            _mine(relationship_memory_versions, principal_id),
            relationship_memory_versions.c.memory_id == memory_id,
        )
        if after_version_id is not None:
            validate_identifier(after_version_id, IdKind.RELATIONSHIP_MEMORY_VERSION)
            position = self._connection.execute(
                select(relationship_memory_versions.c.version_number).where(
                    _mine(relationship_memory_versions, principal_id),
                    relationship_memory_versions.c.memory_version_id == after_version_id,
                    relationship_memory_versions.c.memory_id == memory_id,
                )
            ).scalar_one_or_none()
            if position is None:
                raise UnknownScopeError("a history cursor names a version of this memory")
            statement = statement.where(relationship_memory_versions.c.version_number > position)
        rows = list(
            self._connection.execute(
                statement.order_by(relationship_memory_versions.c.version_number).limit(limit + 1)
            )
        )
        truncated = len(rows) > limit
        return tuple(_to_version(row) for row in rows[:limit]), truncated

    def summaries_for_context(
        self, subject_entity_id: str, *, principal_id: str, limit: int
    ) -> tuple[tuple[MemoryDetail, ...], bool, int]:
        validate_identifier(subject_entity_id, IdKind.ENTITY)
        if limit < 1:
            raise ValueError("a context card carries at least one memory")
        current = relationship_memory_versions.alias("current")
        rows = list(
            self._connection.execute(
                select(*_MEMORY_COLUMNS, *[c.label(f"v_{c.name}") for c in current.c])
                .select_from(
                    relationship_memories.join(
                        current,
                        current.c.memory_version_id == relationship_memories.c.current_version_id,
                    )
                )
                .where(
                    _mine(relationship_memories, principal_id),
                    _mine(current, principal_id),
                    relationship_memories.c.subject_entity_id == subject_entity_id,
                    relationship_memories.c.lifecycle_state == MemoryLifecycle.ACTIVE.value,
                )
                .order_by(
                    relationship_memories.c.pinned.desc(),
                    relationship_memories.c.memory_id,
                )
                .limit(limit + 1)
            )
        )
        truncated = len(rows) > limit
        kept = rows[:limit]
        # Restricted memories are withheld from the card and *counted*, which is
        # the opposite of what search does and is right for the opposite reason:
        # a card is one entity the caller already named and already reads, so
        # "three memories are withheld here" discloses no existence the caller
        # did not have, while a search count would let a term probe find one.
        withheld = sum(
            1 for row in kept if row.v_classification == Classification.RESTRICTED_LOCAL.value
        )
        summaries = tuple(
            MemoryDetail(
                memory=_to_memory(row),
                current_version=_to_version(_VersionRow(row)),
            )
            for row in kept
            if row.v_classification != Classification.RESTRICTED_LOCAL.value
        )
        return summaries, truncated, withheld

    def subject_entity_ids(
        self, entity_ids: frozenset[str], *, principal_id: str
    ) -> frozenset[str]:
        """Which input entities this plane currently binds into canonical memory state.

        Four binding classes are reported: canonical memory subjects, proposal
        subjects, Entity targets linked from a memory's current canonical version,
        and Entity context targets on an open proposal. Governed merge planning
        now uses `plan_identity_merge` to record their mutable bindings as
        content-blind effects while retaining immutable subject/context origins.

        **Classification is not read, and that is the point.** Every other read
        on this plane filters or counts restricted rows; this one asks a question
        whose answer must be the same whether the memory is restricted or not,
        because a merge preview that could distinguish them would be a probe.
        What comes back is only the subset of input `entity_ids` affected by at
        least one binding -- no memory identifier, no per-Entity memory count, no
        statement.
        """
        for entity_id in entity_ids:
            validate_identifier(entity_id, IdKind.ENTITY)
        if not entity_ids:
            return frozenset()
        # Sorted so two calls over the same set build the same statement.
        named = sorted(entity_ids)
        proposal_context = (
            func.jsonb_array_elements(relationship_memory_proposals.c.context_links)
            .table_valued(column("value", relationship_memory_proposals.c.context_links.type))
            .lateral()
        )
        subjects = self._connection.execute(
            union(
                select(relationship_memories.c.subject_entity_id).where(
                    _mine(relationship_memories, principal_id),
                    relationship_memories.c.subject_entity_id.in_(named),
                ),
                select(relationship_memory_proposals.c.subject_entity_id).where(
                    _mine(relationship_memory_proposals, principal_id),
                    relationship_memory_proposals.c.subject_entity_id.in_(named),
                ),
                select(relationship_memory_context_links.c.target_id)
                .select_from(
                    relationship_memory_context_links.join(
                        relationship_memories,
                        relationship_memories.c.current_version_id
                        == relationship_memory_context_links.c.memory_version_id,
                    )
                )
                .where(
                    _mine(relationship_memory_context_links, principal_id),
                    _mine(relationship_memories, principal_id),
                    relationship_memory_context_links.c.target_type
                    == ContextLinkTargetType.ENTITY.value,
                    relationship_memory_context_links.c.target_id.in_(named),
                ),
                select(proposal_context.c.value["target_id"].astext)
                .select_from(relationship_memory_proposals.join(proposal_context, true()))
                .where(
                    _mine(relationship_memory_proposals, principal_id),
                    relationship_memory_proposals.c.state.in_(
                        [
                            MemoryProposalState.PROPOSED.value,
                            MemoryProposalState.NEEDS_REVIEW.value,
                            MemoryProposalState.DEFERRED.value,
                        ]
                    ),
                    proposal_context.c.value["target_type"].astext
                    == ContextLinkTargetType.ENTITY.value,
                    proposal_context.c.value["target_id"].astext.in_(named),
                ),
            )
        ).all()
        return frozenset(str(row[0]) for row in subjects)

    def identity_effect_matches_after_state(
        self, principal_id: str, effect: IdentityEffect
    ) -> bool:
        table, id_column, admitted = _memory_identity_effect_read_subject(effect.family)
        if set(effect.after_state) != admitted:
            return False
        row = self._connection.execute(
            select(*(table.c[name] for name in sorted(admitted))).where(
                _mine(table, principal_id), table.c[id_column] == effect.record_id
            )
        ).one_or_none()
        return row is not None and {name: getattr(row, name) for name in admitted} == dict(
            effect.after_state
        )

    def plan_identity_merge(
        self,
        principal_id: str,
        merged_entity_ids: frozenset[str],
        survivor_entity_id: str,
    ) -> tuple[IdentityEffectDraft, ...]:
        """Plan opaque subject/context moves; never select statement or classification."""
        named = sorted(merged_entity_ids)
        drafts: list[IdentityEffectDraft] = []
        memory_rows = self._connection.execute(
            select(
                relationship_memories.c.memory_id,
                relationship_memories.c.subject_entity_id,
                relationship_memories.c.origin_subject_entity_id,
                relationship_memories.c.version,
            ).where(
                _mine(relationship_memories, principal_id),
                relationship_memories.c.subject_entity_id.in_(named),
            )
        ).all()
        for row in memory_rows:
            before = {
                "subject_entity_id": str(row.subject_entity_id),
                "origin_subject_entity_id": str(row.origin_subject_entity_id),
                "version": int(row.version),
            }
            drafts.append(
                IdentityEffectDraft(
                    family=IdentityEffectFamily.RELATIONSHIP_MEMORY,
                    record_id=str(row.memory_id),
                    kind=IdentityEffectKind.OWNER_REPARENTED,
                    before_state=before,
                    after_state={
                        **before,
                        "subject_entity_id": survivor_entity_id,
                        "version": int(row.version) + 1,
                    },
                )
            )
        proposal_rows = self._connection.execute(
            select(
                relationship_memory_proposals.c.memory_proposal_id,
                relationship_memory_proposals.c.subject_entity_id,
                relationship_memory_proposals.c.origin_subject_entity_id,
                relationship_memory_proposals.c.expected_subject_version,
                relationship_memory_proposals.c.context_links,
            ).where(_mine(relationship_memory_proposals, principal_id))
        ).all()
        for row in proposal_rows:
            before_links = list(row.context_links or [])
            after_links = [
                {
                    **link,
                    "origin_subject_entity_id": link.get("origin_subject_entity_id")
                    or link["target_id"],
                    "target_id": survivor_entity_id,
                }
                if link.get("target_type") == ContextLinkTargetType.ENTITY.value
                and link.get("target_id") in merged_entity_ids
                else dict(link)
                for link in before_links
            ]
            subject = str(row.subject_entity_id)
            if subject not in merged_entity_ids and before_links == after_links:
                continue
            before = {
                "subject_entity_id": subject,
                "origin_subject_entity_id": str(row.origin_subject_entity_id),
                "expected_subject_version": int(row.expected_subject_version),
                "context_links": before_links,
            }
            drafts.append(
                IdentityEffectDraft(
                    family=IdentityEffectFamily.MEMORY_PROPOSAL,
                    record_id=str(row.memory_proposal_id),
                    kind=IdentityEffectKind.OWNER_REPARENTED,
                    before_state=before,
                    after_state={
                        **before,
                        "subject_entity_id": (
                            survivor_entity_id if subject in merged_entity_ids else subject
                        ),
                        "context_links": after_links,
                    },
                )
            )
        link_rows = self._connection.execute(
            select(
                relationship_memory_context_links.c.context_link_id,
                relationship_memory_context_links.c.target_id,
                relationship_memory_context_links.c.origin_subject_entity_id,
            ).where(
                _mine(relationship_memory_context_links, principal_id),
                relationship_memory_context_links.c.target_type
                == ContextLinkTargetType.ENTITY.value,
                relationship_memory_context_links.c.target_id.in_(named),
            )
        ).all()
        for row in link_rows:
            before = {
                "target_id": str(row.target_id),
                "origin_subject_entity_id": str(row.origin_subject_entity_id),
            }
            drafts.append(
                IdentityEffectDraft(
                    family=IdentityEffectFamily.MEMORY_CONTEXT_LINK,
                    record_id=str(row.context_link_id),
                    kind=IdentityEffectKind.OWNER_REPARENTED,
                    before_state=before,
                    after_state={**before, "target_id": survivor_entity_id},
                )
            )
        return tuple(drafts)

    def apply_identity_effect(self, principal_id: str, effect: IdentityEffectDraft) -> None:
        table, id_column, admitted = _memory_identity_effect_write_subject(effect.family)
        if set(effect.before_state) != admitted or set(effect.after_state) != admitted:
            raise ValueError("a memory identity effect contains only binding state")
        conditions = [_mine(table, principal_id), table.c[id_column] == effect.record_id]
        for name, value in effect.before_state.items():
            conditions.append(table.c[name].is_(None) if value is None else table.c[name] == value)
        result = self._connection.execute(
            update(table).where(*conditions).values(**dict(effect.after_state))
        )
        if result.rowcount != 1:
            raise UnknownScopeError("a memory binding changed after merge preview")

    def restore_identity_effect(self, principal_id: str, effect: IdentityEffect) -> None:
        """Restore only opaque bindings; narrative and classification never enter the ledger."""
        table, id_column, admitted = _memory_identity_effect_write_subject(effect.family)
        if set(effect.before_state) != admitted or set(effect.after_state) != admitted:
            raise ValueError("a memory identity effect contains only binding state")
        conditions = [_mine(table, principal_id), table.c[id_column] == effect.record_id]
        for name, value in effect.after_state.items():
            conditions.append(table.c[name].is_(None) if value is None else table.c[name] == value)
        restored = dict(effect.before_state)
        if effect.family is IdentityEffectFamily.RELATIONSHIP_MEMORY:
            current_version = effect.after_state.get("version")
            if not isinstance(current_version, int):
                raise ValueError("a Relationship Memory identity effect records its version")
            restored["version"] = current_version + 1
        elif effect.family is IdentityEffectFamily.MEMORY_PROPOSAL:
            before_links = effect.before_state.get("context_links")
            after_links = effect.after_state.get("context_links")
            if not isinstance(before_links, list) or not isinstance(after_links, list):
                raise ValueError("a memory proposal identity effect records its context links")
            if len(before_links) != len(after_links):
                raise ValueError("a memory proposal identity effect preserves its link set")
            restored_links: list[dict[str, object]] = []
            for before_link, after_link in zip(before_links, after_links, strict=True):
                if not isinstance(before_link, dict) or not isinstance(after_link, dict):
                    raise ValueError("a memory proposal identity effect records link objects")
                restored_link = dict(before_link)
                origin = after_link.get("origin_subject_entity_id")
                if origin is not None:
                    restored_link["origin_subject_entity_id"] = origin
                restored_links.append(restored_link)
            restored["context_links"] = restored_links
        result = self._connection.execute(update(table).where(*conditions).values(**restored))
        if result.rowcount != 1:
            raise UnknownScopeError("a memory binding no longer matches its source merge")


def _memory_identity_effect_read_subject(family: IdentityEffectFamily) -> tuple[Any, str, set[str]]:
    """Map the three opaque RM binding families; no content column is admitted."""
    subjects = {
        IdentityEffectFamily.RELATIONSHIP_MEMORY: (
            relationship_memories,
            "memory_id",
            {"subject_entity_id", "origin_subject_entity_id", "version"},
        ),
        IdentityEffectFamily.MEMORY_PROPOSAL: (
            relationship_memory_proposals,
            "memory_proposal_id",
            {
                "subject_entity_id",
                "origin_subject_entity_id",
                "expected_subject_version",
                "context_links",
            },
        ),
        IdentityEffectFamily.MEMORY_CONTEXT_LINK: (
            relationship_memory_context_links,
            "context_link_id",
            {"target_id", "origin_subject_entity_id"},
        ),
    }
    subject = subjects.get(family)
    if subject is None:
        raise ValueError("a memory identity effect names a memory binding family")
    return subject


def _memory_identity_effect_write_subject(
    family: IdentityEffectFamily,
) -> tuple[Any, str, set[str]]:
    """The same closed bindings, named separately so the access audit sees writes."""
    subjects = {
        IdentityEffectFamily.RELATIONSHIP_MEMORY: (
            relationship_memories,
            "memory_id",
            {"subject_entity_id", "origin_subject_entity_id", "version"},
        ),
        IdentityEffectFamily.MEMORY_PROPOSAL: (
            relationship_memory_proposals,
            "memory_proposal_id",
            {
                "subject_entity_id",
                "origin_subject_entity_id",
                "expected_subject_version",
                "context_links",
            },
        ),
        IdentityEffectFamily.MEMORY_CONTEXT_LINK: (
            relationship_memory_context_links,
            "context_link_id",
            {"target_id", "origin_subject_entity_id"},
        ),
    }
    subject = subjects.get(family)
    if subject is None:
        raise ValueError("a memory identity effect names a memory binding family")
    return subject


class _VersionRow:
    """A joined row read as though it were a version row.

    The context-card query selects both tables at once and labels the version
    columns `v_…` so the two `memory_kind` columns do not collide. This adapts
    the labelled row back to the attribute names `_to_version` reads, rather than
    issuing a second query per memory — which is what a card over twenty-five
    memories would otherwise cost.
    """

    def __init__(self, row: Row[Any]) -> None:
        self._row = row

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401 - mirrors a SQLAlchemy Row
        return getattr(self._row, f"v_{name}")


def _with_version(request: MemoryWriteRequest, memory_version_id: str) -> MemoryWriteRequest:
    """`request` with the version identifier the submission should name."""
    if request.memory_version_id == memory_version_id:
        return request
    return replace(request, memory_version_id=memory_version_id)


def _page(rows: list[Row[Any]], *, limit: int, include_restricted: bool) -> MemoryPage:
    """One page from the joined rows both listing reads select.

    The three current-version values land in one `MemoryListingFacts` inside the
    same loop iteration that appends the memory, which is what keeps the page's
    own invariant satisfiable: the withholding `continue` is above both, so a
    withheld row contributes neither a memory nor a facts record and cannot be
    inferred from a key that outlived its row.
    """
    truncated = len(rows) > limit
    kept = rows[:limit]
    withheld = 0
    memories: list[RelationshipMemory] = []
    facts: dict[str, MemoryListingFacts] = {}
    for row in kept:
        if not include_restricted and row.classification == Classification.RESTRICTED_LOCAL.value:
            withheld += 1
            continue
        memory = _to_memory(row)
        memories.append(memory)
        facts[memory.memory_id] = MemoryListingFacts(
            statement=row.statement_text,
            authority=MemoryAuthority(row.authority),
            classification=Classification(row.classification),
        )
    return MemoryPage(
        memories=tuple(memories),
        listing_facts=facts,
        is_truncated=truncated,
        withheld_by_policy=withheld,
    )
