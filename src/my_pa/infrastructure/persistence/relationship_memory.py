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

from sqlalchemy import Row, func, insert, or_, select, text, update
from sqlalchemy.engine import Connection

from my_pa.contracts.ports import (
    MemoryDetail,
    MemoryPage,
    MemoryWriteRequest,
    RelationshipMemoryRepository,
    UnknownScopeError,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.relationship.entity import EntityStatus
from my_pa.domain.relationship.memory import (
    CONTEXT_TARGET_ID_KINDS,
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
    MemoryReceipt,
    MergedSubjectError,
    RelationshipMemory,
    RelationshipMemoryError,
    RelationshipMemoryVersion,
    StaleMemoryVersionError,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    entities,
    relationship_memories,
    relationship_memory_context_links,
    relationship_memory_evidence_links,
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


def _to_version(row: Row[Any]) -> RelationshipMemoryVersion:
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

    def _require_writable_subject(self, principal_id: str, subject_entity_id: str) -> str:
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
        return str(row.entity_type)

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
        for link in links:
            target_type = ContextLinkTargetType(link["target_type"])
            target_id = link["target_id"]
            validate_identifier(target_id, CONTEXT_TARGET_ID_KINDS[target_type])
            if target_type is not ContextLinkTargetType.ENTITY:
                raise UnknownScopeError("this build validates only entity context targets")
            held = self._connection.execute(
                select(entities.c.entity_id).where(
                    _mine(entities, principal_id),
                    entities.c.entity_id == target_id,
                )
            ).scalar_one_or_none()
            if held is None:
                raise UnknownScopeError("a context link names an entity outside this scope")

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
        self._require_writable_subject(request.principal_id, subject_entity_id)
        self._require_own_context_targets(request.principal_id, request.context_links)
        memory_id = issue_identifier(IdKind.RELATIONSHIP_MEMORY)
        self._connection.execute(
            insert(relationship_memories).values(
                _bound(
                    relationship_memories,
                    request.principal_id,
                    {
                        "memory_id": memory_id,
                        "subject_entity_id": subject_entity_id,
                        "memory_kind": memory_kind.value,
                        "lifecycle_state": MemoryLifecycle.ACTIVE.value,
                        "current_version_id": request.memory_version_id,
                        "current_version_number": 1,
                        "version": 1,
                        "pinned": request.pinned,
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
        current = self._connection.execute(
            select(*_MEMORY_COLUMNS).where(
                _mine(relationship_memories, request.principal_id),
                relationship_memories.c.memory_id == memory_id,
            )
        ).one_or_none()
        if current is None:
            raise UnknownScopeError("a memory write names a memory outside this scope")
        if request.operation is MemoryOperation.RESTORE:
            # Checked on restore and not on archive: returning a memory to the
            # current set against an identity that has since been merged away
            # would put a live note on a person the user did not choose, while
            # withdrawing one from a merged-away subject is always safe.
            self._require_writable_subject(request.principal_id, current.subject_entity_id)

        revising = request.operation is MemoryOperation.REVISE
        memory_kind = request.memory_kind or MemoryKind(current.memory_kind)
        if revising:
            self._require_writable_subject(request.principal_id, current.subject_entity_id)
            self._require_own_context_targets(request.principal_id, request.context_links)

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
            select(*_MEMORY_COLUMNS, current.c.statement_text, current.c.classification)
            .select_from(
                relationship_memories.join(
                    current,
                    current.c.memory_version_id == relationship_memories.c.current_version_id,
                )
            )
            .where(
                _mine(relationship_memories, principal_id),
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
        if after_memory_id is not None:
            validate_identifier(after_memory_id, IdKind.RELATIONSHIP_MEMORY)
            located = self._connection.execute(
                select(relationship_memories.c.memory_id).where(
                    _mine(relationship_memories, principal_id),
                    relationship_memories.c.memory_id == after_memory_id,
                )
            ).scalar_one_or_none()
            # Refused rather than silently restarted: a cursor naming a memory
            # this Principal cannot read is not a position in their ordering, and
            # an empty page is indistinguishable from having reached the end.
            if located is None:
                raise UnknownScopeError("a memory cursor names a memory in this scope")
            statement = statement.where(relationship_memories.c.memory_id > after_memory_id)
        rows = list(
            self._connection.execute(
                statement.order_by(
                    relationship_memories.c.pinned.desc(),
                    relationship_memories.c.memory_id,
                ).limit(limit + 1)
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
            select(*_MEMORY_COLUMNS, current.c.statement_text, current.c.classification)
            .select_from(
                relationship_memories.join(
                    current,
                    current.c.memory_version_id == relationship_memories.c.current_version_id,
                )
            )
            .where(
                _mine(relationship_memories, principal_id),
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
    truncated = len(rows) > limit
    kept = rows[:limit]
    withheld = 0
    memories: list[RelationshipMemory] = []
    statements: dict[str, str] = {}
    for row in kept:
        if not include_restricted and row.classification == Classification.RESTRICTED_LOCAL.value:
            withheld += 1
            continue
        memory = _to_memory(row)
        memories.append(memory)
        statements[memory.memory_id] = row.statement_text
    return MemoryPage(
        memories=tuple(memories),
        statements=statements,
        is_truncated=truncated,
        withheld_by_policy=withheld,
    )
