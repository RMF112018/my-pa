"""The entity plane's governed write path, and the one ledger that records it.

`persistence.entity` holds the plane's reads and its three *unguarded* writes --
the ones resolution and re-enrichment use, which take no expected version and no
idempotency key. This module holds the guarded ones, and it is a separate module
for the reason `persistence.reveal` is separate from `persistence.capture`: what
a write to this plane costs is a transaction spanning four tables, an optimistic
guard, an idempotency store and an append-only ledger, and none of that belongs
inside a class whose other thirty methods are `SELECT`s.

**One transaction, and the guarded `UPDATE` is always its first write.** Every
operation that names an existing entity advances that entity's version before it
touches anything else, and reads the row count before any other row is written.
A stale expectation therefore leaves *nothing* behind -- not a successor that is
rolled back, but a successor that was never inserted. The entity is the
aggregate: binding an address and retiring an alias both change what the entity
says about itself, so both advance its version, and a caller holding a version
from before either one is refused.

**`entity_mutation_events` is both the ledger and the idempotency store**, and
the second role is what `UNIQUE (principal_id, capability, idempotency_key)` is
for. A replay is answered from the row rather than by re-running the write, and
what makes that safe is that the row carries the *digest* of the request that
wrote it: a key arriving with a different payload is a conflict rather than a
replay, and answering it with the stored receipt would report a write that never
happened as durable.

**The receipt is rebuilt from `after_state`.** That column is documented on the
table as evidence rather than authority -- the canonical fact is the row in the
canonical table, and this is a photograph of it -- and a receipt is exactly the
kind of thing a photograph can answer: it says what the write produced, at the
moment it produced it, which is what a replaying caller asked for.

**Private helpers are imported from `persistence.entity` rather than restated.**
`_arbiter`, the two partial-unique index objects and `_BIND_ATTEMPTS` all encode
rules the server holds, and a second spelling of an `ON CONFLICT` predicate is a
second place the arbiter can stop matching the index it names.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import Index, Row, Table, insert, null, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement

from my_pa.contracts.ports import (
    EntityMutationAdmission,
    EntityMutationReceipt,
    EntityWriteRequest,
    UnknownScopeError,
)
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.relationship.authoring import (
    AmbiguousEntityError,
    ConflictedIdentifierError,
    DuplicateEntityFactError,
    EntityEvidenceError,
    EntityIdempotencyConflictError,
    EntityWriteOperation,
    HistoricalEntityError,
    StaleEntityVersionError,
    UnsettledBindingError,
)
from my_pa.domain.relationship.entity import (
    AliasState,
    AliasType,
    EntityStatus,
    EntityType,
    IdentifierState,
)
from my_pa.domain.relationship.governance import (
    EvidenceRole,
    MutationRecordFamily,
)
from my_pa.infrastructure.persistence.identifier_claim_lock import (
    lock_entity_mutation_scopes,
    lock_identifier_claim_keys,
    lock_identifier_entity_scopes,
)
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    capture_spans,
    capture_versions,
    captures,
    entities,
    entity_aliases,
    entity_external_identifiers,
    entity_fact_evidence_links,
    entity_mutation_events,
)

__all__ = [
    "ACTIVE_ALIAS_INDEX",
    "ACTIVE_BINDING_INDEX",
    "BIND_ATTEMPTS",
    "admit_mutation",
    "arbiter",
    "declared_index",
    "mutation_replay_for",
]


def declared_index(table: Table, name: str) -> Index:
    """The index `table` declares under `name`, or a failure that says which one.

    Looked up rather than restated so an `ON CONFLICT` arbiter cannot drift from
    the index it is meant to name. Restating it is not merely duplication here:
    a *partial* index is inferred only when the statement's predicate implies the
    index's, and PostgreSQL cannot prove that of a bound parameter -- a
    hand-written `state = :state` compiles, then fails at execution with "there
    is no unique or exclusion constraint matching the ON CONFLICT
    specification", and only against rows whose other bind parameters made the
    driver cast it. Reusing the declaration's own predicate object emits the
    same literal the index carries.

    Public here, and imported by `persistence.entity`, because the two modules
    write the same two tables through the same two partial uniques. One
    definition is what stops an unguarded write and a guarded one from
    arbitrating differently on the row they share.
    """
    for index in table.indexes:
        if index.name == name:
            return index
    raise LookupError(f"{table.name} declares no index named {name}")


#: The two partial unique indexes every idempotent write on this plane arbitrates.
ACTIVE_BINDING_INDEX = declared_index(
    entity_external_identifiers, "an_active_external_identifier_binding_is_unique"
)
ACTIVE_ALIAS_INDEX = declared_index(entity_aliases, "an_active_alias_is_unique_per_entity_and_type")

#: How many times a binding insert is attempted before giving up.
#:
#: Two, not one and not unbounded. One is what leaked a `NoResultFound` out of
#: the port: the insert was refused by an active holder, the read-back that
#: names the holder found nothing because another session had retired it in
#: between, and there was no branch for that. Unbounded is a spin -- a workload
#: that binds and retires the same address in a loop would hold this connection
#: forever. Two is enough because the interleaving that costs the first attempt
#: is a *committed* retirement: the second attempt sees a fresh snapshot with
#: the address free, and only a second, independent session claiming it in the
#: same window costs the second. That is a race this repository cannot resolve
#: by trying harder, so it is reported rather than retried away.
BIND_ATTEMPTS = 2


def arbiter(index: Index) -> dict[str, Any]:
    """`index` as the `on_conflict_do_nothing` arguments that infer it."""
    return {
        "index_elements": list(index.expressions),
        "index_where": index.dialect_options["postgresql"]["where"],
    }


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    """``table`` constrained to the given Principal."""
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, **values: object) -> dict[str, object]:
    """``values`` stamped with the given Principal for ``table``."""
    return principal_bound_values(dict(values), table, capture_context(principal_id))


#: SQLSTATE for a unique violation, which is the one `IntegrityError` this
#: module's ledger insert is entitled to interpret. Restated here rather than
#: imported from the driver, so the persistence layer's error classification
#: does not become a reason for every reader of this file to import psycopg.
_UNIQUE_VIOLATION = "23505"

#: What a write on this path carries when nothing says otherwise, and what it
#: meant when it was the only value one could carry.
#:
#: `USER_CONFIRMED_ASSERTION` because these capabilities are ordinarily reached
#: by a request an authenticated Principal made, naming the version it read: the
#: user was asked and answered. `SYSTEM_DETERMINISTIC` is what an
#: inference-driven writer would carry and is unreachable here, because
#: `MutationAuthority` records that it "may never, by itself, create or merge an
#: identity" -- and a create is one of the capabilities this path serves; the
#: request refuses it outright rather than leaving the refusal to this module.
#:
#: **These are now the defaults rather than the only values, and `WP-RI-B-05` is
#: the change.** They were two module constants here, and the reason given was
#: that an authority a caller could state is an authority a caller could raise.
#: That reason still holds and is still enforced -- no transport command carries
#: either field, and a proposal payload naming one is refused by
#: `FORBIDDEN_PAYLOAD_FIELDS` -- but the premise it rested on, that the request
#: "has no field for it", stopped being true when review promotion had to
#: execute: a fact a reviewer accepted from a source or a local model recorded
#: as `user_confirmed_assertion` is a record claiming the user asserted what
#: somebody else did.
#:
#: So the writers below read `request.authority` and `request.actor_class`, and
#: the two constants moved to `domain.relationship.governance` as
#: `DEFAULT_MUTATION_AUTHORITY` and `DEFAULT_MUTATION_ACTOR_CLASS`, which is
#: where `EntityWriteRequest` declares them as its field defaults. They were not
#: left here as aliases beside the readers: a constant nothing reads is a claim
#: nothing checks, and two spellings of one default are two things that can
#: drift apart.

#: Which fact column of `entity_fact_evidence_links` each record family fills.
_EVIDENCE_TARGET_COLUMN: Mapping[MutationRecordFamily, str] = {
    MutationRecordFamily.ENTITY: "entity_id",
    MutationRecordFamily.IDENTIFIER: "identifier_id",
    MutationRecordFamily.ALIAS: "alias_id",
}


class _Outcome:
    """What one operation produced, before it becomes a ledger row and a receipt.

    A mutable carrier rather than a frozen record, because it is filled in by
    the operation that produces it and read once by the two functions that
    persist it. It never leaves this module.
    """

    __slots__ = (
        "before_state",
        "child_id",
        "child_state",
        "child_version",
        "entity_id",
        "entity_status",
        "entity_version",
        "new_version",
        "prior_version",
        "record_id",
        "superseded_ids",
    )

    def __init__(
        self,
        *,
        entity_id: str,
        entity_version: int,
        entity_status: EntityStatus,
        record_id: str,
        prior_version: int | None,
        new_version: int,
        before_state: dict[str, Any],
        child_id: str | None = None,
        child_version: int | None = None,
        child_state: str | None = None,
        superseded_ids: tuple[str, ...] = (),
    ) -> None:
        self.entity_id = entity_id
        self.entity_version = entity_version
        self.entity_status = entity_status
        self.record_id = record_id
        self.prior_version = prior_version
        self.new_version = new_version
        self.before_state = before_state
        self.child_id = child_id
        self.child_version = child_version
        self.child_state = child_state
        self.superseded_ids = superseded_ids


def mutation_replay_for(
    connection: Connection,
    idempotency_key: str,
    request_digest: str,
    *,
    principal_id: str,
    capability: str,
) -> EntityMutationReceipt | None:
    """The receipt this Principal's key is bound to on this capability, or `None`."""
    row = connection.execute(
        select(entity_mutation_events).where(
            _mine(entity_mutation_events, principal_id),
            entity_mutation_events.c.capability == capability,
            entity_mutation_events.c.idempotency_key == idempotency_key,
        )
    ).one_or_none()
    if row is None:
        return None
    if row.request_digest != request_digest:
        raise EntityIdempotencyConflictError(
            "an entity idempotency key is bound to a different request"
        )
    return _receipt_from(row)


def admit_mutation(connection: Connection, request: EntityWriteRequest) -> EntityMutationAdmission:
    """Admit one governed entity write. See `EntitiesRepository.admit_mutation`."""
    _serialize_identifier_request(connection, request)
    if request.operation is EntityWriteOperation.CREATE:
        outcome = _create(connection, request)
    else:
        outcome = _mutate(connection, request)
    link_ids = _record_evidence(connection, request, outcome)
    _record_mutation(connection, request, outcome, link_ids)
    return EntityMutationAdmission(
        receipt=EntityMutationReceipt(
            event_id=request.event_id,
            capability=request.capability,
            record_family=request.record_family,
            record_id=outcome.record_id,
            entity_id=outcome.entity_id,
            entity_version=outcome.entity_version,
            entity_status=outcome.entity_status,
            idempotency_key=request.idempotency_key,
            issued_at=request.server_received_at,
            created=True,
            child_id=outcome.child_id,
            child_version=outcome.child_version,
            child_state=outcome.child_state,
            superseded_ids=outcome.superseded_ids,
            evidence_link_ids=link_ids,
        ),
        created=True,
    )


def _serialize_identifier_request(connection: Connection, request: EntityWriteRequest) -> None:
    """Acquire Entity and identifier locks before this request's first read/write."""
    claims: set[tuple[str, str]] = set()
    entity_id: str | None = None
    if request.operation is EntityWriteOperation.CREATE:
        entity_id = str(request.minted_entity_id)
    elif request.entity_id is not None:
        entity_id = str(request.entity_id)
    if entity_id is None:
        return

    lock_entity_mutation_scopes(connection, request.principal_id, (entity_id,))

    if request.operation not in {
        EntityWriteOperation.CREATE,
        EntityWriteOperation.BIND_IDENTIFIER,
        EntityWriteOperation.RETIRE_IDENTIFIER,
        EntityWriteOperation.SUPERSEDE_IDENTIFIER,
    }:
        return

    # The Entity lock precedes reading a held claim: otherwise a retire or
    # supersede could read one key, wait, and mutate a row whose key changed
    # before the lock was acquired.
    lock_identifier_entity_scopes(connection, request.principal_id, (entity_id,))
    if request.operation is EntityWriteOperation.CREATE:
        claims.update(
            (item.namespace.value, item.normalized_value) for item in request.initial_identifiers
        )
    else:
        if request.operation in {
            EntityWriteOperation.BIND_IDENTIFIER,
            EntityWriteOperation.SUPERSEDE_IDENTIFIER,
        }:
            claims.add((str(request.namespace), str(request.normalized_value)))
        if request.operation in {
            EntityWriteOperation.RETIRE_IDENTIFIER,
            EntityWriteOperation.SUPERSEDE_IDENTIFIER,
        }:
            held = _identifier_claim_for_target(connection, request, str(request.target_child_id))
            if held is not None:
                claims.add(held)
    lock_identifier_claim_keys(connection, request.principal_id, claims)


# --- the operations -----------------------------------------------------------


def _create(connection: Connection, request: EntityWriteRequest) -> _Outcome:
    """Insert one entity and whatever it was created carrying.

    The duplicate resolution `EntityAuthoringService.create` ran is *this*
    transaction's read, so it is already transactional. What it cannot cover is
    a binding another session commits between that read and these inserts, and
    that is what the per-identifier arbiter below catches: the insert is refused
    by the partial unique, the holder is read back, and a holder that is not
    this brand-new entity refuses the whole create rather than leaving a
    half-created person behind.
    """
    entity_id = str(request.minted_entity_id)
    entity_type = request.entity_type
    if entity_type is None or request.display_name is None or request.canonical_name is None:
        raise AmbiguousEntityError("an entity creation carries a type and both name forms")
    connection.execute(
        insert(entities).values(
            _bound(
                entities,
                request.principal_id,
                entity_id=entity_id,
                entity_type=EntityType(entity_type).value,
                canonical_name=request.canonical_name,
                display_name=request.display_name,
                status=EntityStatus.ACTIVE.value,
                created_at=request.server_received_at,
                updated_at=request.server_received_at,
                version=1,
                superseded_by_entity_id=None,
                archived_from_status=None,
            )
        )
    )
    for alias in request.initial_aliases:
        _insert_alias(
            connection,
            request,
            entity_id=entity_id,
            alias_id=alias.alias_id,
            alias_type=alias.alias_type,
            normalized_value=alias.normalized_value,
            display_value=alias.display_value,
            effective_from=None,
            effective_to=None,
        )
    for identifier in request.initial_identifiers:
        _insert_binding(
            connection,
            request,
            entity_id=entity_id,
            identifier_id=identifier.identifier_id,
            namespace=identifier.namespace.value,
            normalized_value=identifier.normalized_value,
            display_value=identifier.display_value,
            effective_from=None,
            effective_to=None,
        )
    return _Outcome(
        entity_id=entity_id,
        entity_version=1,
        entity_status=EntityStatus.ACTIVE,
        record_id=entity_id,
        prior_version=None,
        new_version=1,
        before_state={},
    )


def _mutate(connection: Connection, request: EntityWriteRequest) -> _Outcome:
    """Every operation that names an entity that already exists."""
    entity_id = str(request.entity_id)
    row = _live_entity(connection, request.principal_id, entity_id)
    before = _entity_state(row)
    operation = request.operation
    if operation is EntityWriteOperation.UPDATE:
        return _update(connection, request, row, before)
    if operation is EntityWriteOperation.ARCHIVE:
        return _archive(connection, request, row, before)
    if operation is EntityWriteOperation.RESTORE:
        return _restore(connection, request, row, before)
    entity_version = _advance_entity(connection, request)
    # Named branches rather than a dispatch table, and the reason is a guard
    # rather than taste: `tests/architecture/
    # test_every_capability_reaching_a_memory_row_is_declared` follows calls by
    # name and cannot follow one made through a subscript, so a table here would
    # hide six functions from a walk over the modules that build this plane's
    # SQL. A branch it can read is worth more than a table that is shorter.
    if operation is EntityWriteOperation.BIND_IDENTIFIER:
        return _bind(connection, request, entity_version, before)
    if operation is EntityWriteOperation.RETIRE_IDENTIFIER:
        return _retire_identifier(connection, request, entity_version, before)
    if operation is EntityWriteOperation.SUPERSEDE_IDENTIFIER:
        return _supersede_identifier(connection, request, entity_version, before)
    if operation is EntityWriteOperation.ADD_ALIAS:
        return _add_alias(connection, request, entity_version, before)
    if operation is EntityWriteOperation.RETIRE_ALIAS:
        return _retire_alias(connection, request, entity_version, before)
    return _supersede_alias(connection, request, entity_version, before)


def _update(
    connection: Connection, request: EntityWriteRequest, row: Row[Any], before: dict[str, Any]
) -> _Outcome:
    status = row.status
    values: dict[str, Any] = {}
    if request.display_name is not None:
        values["display_name"] = request.display_name
    if request.canonical_name is not None:
        values["canonical_name"] = request.canonical_name
    if request.status is not None:
        # An archived entity is restored, not updated back into service.
        # `entities.restore` is the capability that knows which status to return
        # it to -- it reads `archived_from_status` -- and an update that set
        # `active` here would both guess and leave the column that makes the
        # archive reversible pointing at a status the row no longer holds.
        if status == EntityStatus.ARCHIVED.value:
            raise DuplicateEntityFactError("an archived entity is restored rather than updated")
        values["status"] = EntityStatus(request.status).value
    new_version = _advance_entity(connection, request, **values)
    alias_id: str | None = None
    if request.canonical_name is not None and request.canonical_name != row.canonical_name:
        # **The prior name is preserved as a `former_name` alias, and the
        # `display_value` is the prior *display* name.** The normalized column is
        # what a lookup compares against and the display column is the evidence
        # -- what a source actually wrote -- so keeping the old matched form
        # beside the old written form is what lets a reference made under the
        # previous name keep resolving and still be shown the way it was written.
        #
        # `ON CONFLICT DO NOTHING` is the "unless already equivalent" half of the
        # rule, decided by the partial unique rather than by a second read: if
        # this entity already actively carries that name form as a former name,
        # there is nothing to record.
        written = _insert_alias(
            connection,
            request,
            entity_id=str(request.entity_id),
            alias_id=str(request.minted_child_id),
            alias_type=AliasType.FORMER_NAME,
            normalized_value=row.canonical_name,
            display_value=row.display_name,
            effective_from=None,
            effective_to=None,
            refuse_a_duplicate=False,
        )
        alias_id = str(request.minted_child_id) if written else None
    return _Outcome(
        entity_id=str(request.entity_id),
        entity_version=new_version,
        entity_status=EntityStatus(values.get("status", status)),
        record_id=str(request.entity_id),
        prior_version=request.expected_version,
        new_version=new_version,
        before_state=before,
        child_id=alias_id,
        child_version=1 if alias_id else None,
        child_state=AliasState.ACTIVE.value if alias_id else None,
    )


def _archive(
    connection: Connection, request: EntityWriteRequest, row: Row[Any], before: dict[str, Any]
) -> _Outcome:
    if row.status == EntityStatus.ARCHIVED.value:
        raise DuplicateEntityFactError("an archived entity is already withdrawn")
    new_version = _advance_entity(
        connection,
        request,
        status=EntityStatus.ARCHIVED.value,
        archived_from_status=row.status,
    )
    return _Outcome(
        entity_id=str(request.entity_id),
        entity_version=new_version,
        entity_status=EntityStatus.ARCHIVED,
        record_id=str(request.entity_id),
        prior_version=request.expected_version,
        new_version=new_version,
        before_state=before,
    )


def _restore(
    connection: Connection, request: EntityWriteRequest, row: Row[Any], before: dict[str, Any]
) -> _Outcome:
    if row.status != EntityStatus.ARCHIVED.value:
        raise DuplicateEntityFactError("an entity that is not archived cannot be restored")
    restored = EntityStatus(row.archived_from_status)
    new_version = _advance_entity(
        connection,
        request,
        status=restored.value,
        archived_from_status=None,
    )
    return _Outcome(
        entity_id=str(request.entity_id),
        entity_version=new_version,
        entity_status=restored,
        record_id=str(request.entity_id),
        prior_version=request.expected_version,
        new_version=new_version,
        before_state=before,
    )


def _bind(
    connection: Connection,
    request: EntityWriteRequest,
    entity_version: int,
    before: dict[str, Any],
) -> _Outcome:
    entity_id = str(request.entity_id)
    identifier_id = str(request.minted_child_id)
    _insert_binding(
        connection,
        request,
        entity_id=entity_id,
        identifier_id=identifier_id,
        namespace=str(request.namespace),
        normalized_value=str(request.normalized_value),
        display_value=str(request.display_value),
        effective_from=request.effective_from,
        effective_to=request.effective_to,
    )
    return _Outcome(
        entity_id=entity_id,
        entity_version=entity_version,
        entity_status=EntityStatus(before["status"]),
        record_id=identifier_id,
        prior_version=None,
        new_version=1,
        before_state=before,
        child_id=identifier_id,
        child_version=1,
        child_state=IdentifierState.ACTIVE.value,
    )


def _retire_identifier(
    connection: Connection,
    request: EntityWriteRequest,
    entity_version: int,
    before: dict[str, Any],
) -> _Outcome:
    target = str(request.target_child_id)
    prior = _transition_identifier(
        connection,
        request,
        state=IdentifierState.RETIRED,
        retired_at=request.server_received_at,
        superseded_by_identifier_id=None,
    )
    return _Outcome(
        entity_id=str(request.entity_id),
        entity_version=entity_version,
        entity_status=EntityStatus(before["status"]),
        record_id=target,
        prior_version=request.target_child_version,
        new_version=int(request.target_child_version or 0) + 1,
        before_state={**before, "identifier": prior},
        child_id=target,
        child_version=int(request.target_child_version or 0) + 1,
        child_state=IdentifierState.RETIRED.value,
    )


def _supersede_identifier(
    connection: Connection,
    request: EntityWriteRequest,
    entity_version: int,
    before: dict[str, Any],
) -> _Outcome:
    entity_id = str(request.entity_id)
    replacement = str(request.minted_child_id)
    target = str(request.target_child_id)
    lock_identifier_entity_scopes(connection, request.principal_id, (entity_id,))
    claims = {
        (str(request.namespace), str(request.normalized_value)),
    }
    held_claim = _identifier_claim_for_target(connection, request, target)
    if held_claim is not None:
        claims.add(held_claim)
    lock_identifier_claim_keys(connection, request.principal_id, claims)
    # The replacement is written first, because the row being superseded points
    # at it and a foreign key needs its target. The old row is still `active` at
    # this moment, so a replacement carrying the *same* value is refused by the
    # partial unique and reported as the duplicate it is.
    _insert_binding(
        connection,
        request,
        entity_id=entity_id,
        identifier_id=replacement,
        namespace=str(request.namespace),
        normalized_value=str(request.normalized_value),
        display_value=str(request.display_value),
        effective_from=request.effective_from,
        effective_to=request.effective_to,
        serialize=False,
    )
    prior = _transition_identifier(
        connection,
        request,
        state=IdentifierState.SUPERSEDED,
        retired_at=request.server_received_at,
        superseded_by_identifier_id=replacement,
        serialize=False,
    )
    return _Outcome(
        entity_id=entity_id,
        entity_version=entity_version,
        entity_status=EntityStatus(before["status"]),
        record_id=replacement,
        prior_version=None,
        new_version=1,
        before_state={**before, "identifier": prior},
        child_id=replacement,
        child_version=1,
        child_state=IdentifierState.ACTIVE.value,
        superseded_ids=(str(request.target_child_id),),
    )


def _add_alias(
    connection: Connection,
    request: EntityWriteRequest,
    entity_version: int,
    before: dict[str, Any],
) -> _Outcome:
    entity_id = str(request.entity_id)
    alias_id = str(request.minted_child_id)
    _insert_alias(
        connection,
        request,
        entity_id=entity_id,
        alias_id=alias_id,
        alias_type=AliasType(str(request.alias_type)),
        normalized_value=str(request.normalized_value),
        display_value=str(request.display_value),
        effective_from=request.effective_from,
        effective_to=request.effective_to,
    )
    return _Outcome(
        entity_id=entity_id,
        entity_version=entity_version,
        entity_status=EntityStatus(before["status"]),
        record_id=alias_id,
        prior_version=None,
        new_version=1,
        before_state=before,
        child_id=alias_id,
        child_version=1,
        child_state=AliasState.ACTIVE.value,
    )


def _retire_alias(
    connection: Connection,
    request: EntityWriteRequest,
    entity_version: int,
    before: dict[str, Any],
) -> _Outcome:
    target = str(request.target_child_id)
    prior = _transition_alias(
        connection,
        request,
        state=AliasState.RETIRED,
        superseded_by_alias_id=None,
    )
    return _Outcome(
        entity_id=str(request.entity_id),
        entity_version=entity_version,
        entity_status=EntityStatus(before["status"]),
        record_id=target,
        prior_version=request.target_child_version,
        new_version=int(request.target_child_version or 0) + 1,
        before_state={**before, "alias": prior},
        child_id=target,
        child_version=int(request.target_child_version or 0) + 1,
        child_state=AliasState.RETIRED.value,
    )


def _supersede_alias(
    connection: Connection,
    request: EntityWriteRequest,
    entity_version: int,
    before: dict[str, Any],
) -> _Outcome:
    entity_id = str(request.entity_id)
    replacement = str(request.minted_child_id)
    _insert_alias(
        connection,
        request,
        entity_id=entity_id,
        alias_id=replacement,
        alias_type=AliasType(str(request.alias_type)),
        normalized_value=str(request.normalized_value),
        display_value=str(request.display_value),
        effective_from=request.effective_from,
        effective_to=request.effective_to,
    )
    prior = _transition_alias(
        connection,
        request,
        state=AliasState.SUPERSEDED,
        superseded_by_alias_id=replacement,
    )
    return _Outcome(
        entity_id=entity_id,
        entity_version=entity_version,
        entity_status=EntityStatus(before["status"]),
        record_id=replacement,
        prior_version=None,
        new_version=1,
        before_state={**before, "alias": prior},
        child_id=replacement,
        child_version=1,
        child_state=AliasState.ACTIVE.value,
        superseded_ids=(str(request.target_child_id),),
    )


# --- the shared statements ----------------------------------------------------


def _live_entity(connection: Connection, principal_id: str, entity_id: str) -> Row[Any]:
    """The entity this write names, or the refusal that says why it cannot be written.

    A foreign entity answers exactly what an absent one answers, because
    `principal_id` is part of the lookup rather than a filter applied after it.
    A merged-away entity is a third answer and a different one: it exists, it is
    this Principal's, and it is no longer the row that stands.
    """
    validate_identifier(entity_id, IdKind.ENTITY)
    row = connection.execute(
        select(entities).where(
            _mine(entities, principal_id),
            entities.c.entity_id == entity_id,
        )
    ).one_or_none()
    if row is None:
        raise UnknownScopeError("an entity write names an entity outside this scope")
    if row.status == EntityStatus.MERGED_REDIRECT.value:
        raise HistoricalEntityError(str(row.superseded_by_entity_id))
    return row


def _advance_entity(connection: Connection, request: EntityWriteRequest, **values: object) -> int:
    """The one guarded `UPDATE`, and the first write of every operation that has one.

    `version + 1` is computed by the server rather than from the row this
    transaction read, so the value written cannot disagree with the predicate
    that admitted it. The row count is the concurrency control and the existence
    check at once, and it is read before anything else is written.
    """
    expected = int(request.expected_version or 0)
    updated = connection.execute(
        update(entities)
        .where(
            _mine(entities, request.principal_id),
            entities.c.entity_id == request.entity_id,
            entities.c.version == expected,
        )
        .values(
            version=entities.c.version + 1,
            updated_at=request.server_received_at,
            **values,
        )
    ).rowcount
    if updated != 1:
        raise StaleEntityVersionError("the expected entity version is stale")
    return expected + 1


def _insert_binding(
    connection: Connection,
    request: EntityWriteRequest,
    *,
    entity_id: str,
    identifier_id: str,
    namespace: str,
    normalized_value: str,
    display_value: str,
    effective_from: datetime | None,
    effective_to: datetime | None,
    serialize: bool = True,
) -> None:
    """Write one `active` binding, or refuse with the reason the store holds.

    The bounded re-attempt is `SqlEntityRepository.bind_identifier`'s, and it is
    here rather than delegated to that method because the refusals differ: that
    one absorbs a re-bind of an address the entity already holds, and a governed
    write must not hand back a receipt for a binding it did not make.
    """
    if serialize:
        lock_identifier_entity_scopes(connection, request.principal_id, (entity_id,))
        lock_identifier_claim_keys(
            connection, request.principal_id, ((namespace, normalized_value),)
        )
    for _ in range(BIND_ATTEMPTS):
        # The stamp is built inside the statement rather than hoisted above the
        # loop, and that is not incidental:
        # `tests/architecture/test_principal_partition_is_reached_through_the_guard`
        # reads one statement at a time, so a `values` dict assembled in an
        # earlier statement puts the partition and the insert in two places --
        # the shape that guard exists to notice, and one it cannot tell a safe
        # instance of from an unsafe one.
        written = connection.execute(
            pg_insert(entity_external_identifiers)
            .values(
                _bound(
                    entity_external_identifiers,
                    request.principal_id,
                    identifier_id=identifier_id,
                    entity_id=entity_id,
                    namespace=namespace,
                    normalized_value=normalized_value,
                    display_value=display_value,
                    # Server-owned and always false on this path. `verified`
                    # asserts that something checked the address really belongs
                    # to this entity, and a caller stating it would be the
                    # assertion verifying itself.
                    verified=False,
                    effective_from=effective_from,
                    effective_to=effective_to,
                    state=IdentifierState.ACTIVE.value,
                    version=1,
                    updated_at=None,
                    retired_at=None,
                    superseded_by_identifier_id=None,
                )
            )
            .on_conflict_do_nothing(**arbiter(ACTIVE_BINDING_INDEX))
            # `RETURNING` rather than `rowcount`: this driver reports `-1` for an
            # INSERT and so cannot tell a written row from a skipped one.
            .returning(entity_external_identifiers.c.identifier_id)
        ).first()
        if written is not None:
            return
        holder = connection.execute(
            select(entity_external_identifiers.c.entity_id).where(
                _mine(entity_external_identifiers, request.principal_id),
                entity_external_identifiers.c.namespace == namespace,
                entity_external_identifiers.c.normalized_value == normalized_value,
                entity_external_identifiers.c.state == IdentifierState.ACTIVE.value,
            )
        ).scalar_one_or_none()
        if holder is None:
            # The holder that refused the insert was retired and committed by
            # another session inside the window between the two statements. The
            # address belongs to nobody now, so the caller's write is the one a
            # serialized execution would have performed next; attempt it again
            # against the state that exists.
            continue
        if str(holder) != entity_id:
            raise ConflictedIdentifierError("an active external identity binds exactly one entity")
        raise DuplicateEntityFactError("this entity already holds that external identity")
    raise UnsettledBindingError(
        "an external identity binding could not be settled against a concurrent retirement"
    )


def _insert_alias(
    connection: Connection,
    request: EntityWriteRequest,
    *,
    entity_id: str,
    alias_id: str,
    alias_type: AliasType,
    normalized_value: str,
    display_value: str,
    effective_from: datetime | None,
    effective_to: datetime | None,
    refuse_a_duplicate: bool = True,
) -> bool:
    """Write one `active` alias. Answers whether a row was actually written.

    `refuse_a_duplicate` is the one place the two callers differ. A caller that
    *asked* for this alias is told when the entity already carries it, because a
    receipt for a row that was not written is a false receipt. The `former_name`
    alias an `entities.update` leaves behind was not asked for, and the rule the
    contract states for it is "unless already equivalent" -- so there, a
    duplicate is the expected outcome and the answer is simply that nothing was
    added.
    """
    written = connection.execute(
        pg_insert(entity_aliases)
        .values(
            _bound(
                entity_aliases,
                request.principal_id,
                alias_id=alias_id,
                entity_id=entity_id,
                alias_type=alias_type.value,
                normalized_value=normalized_value,
                display_value=display_value,
                effective_from=effective_from,
                effective_to=effective_to,
                state=AliasState.ACTIVE.value,
                version=1,
                updated_at=None,
                retired_at=None,
                superseded_by_alias_id=None,
            )
        )
        # The active alias unique is per entity, so a conflict here can only ever
        # be this entity's own row -- two different entities carrying one name is
        # a fact rather than a collision, because two real people share names.
        .on_conflict_do_nothing(**arbiter(ACTIVE_ALIAS_INDEX))
        .returning(entity_aliases.c.alias_id)
    ).first()
    if written is None and refuse_a_duplicate:
        raise DuplicateEntityFactError("this entity already carries that name form")
    return written is not None


def _transition_identifier(
    connection: Connection,
    request: EntityWriteRequest,
    *,
    state: IdentifierState,
    retired_at: datetime,
    superseded_by_identifier_id: str | None,
    serialize: bool = True,
) -> dict[str, Any]:
    """Move one active binding out of service, guarded on its own version."""
    target = str(request.target_child_id)
    expected = int(request.target_child_version or 0)
    if serialize:
        lock_identifier_entity_scopes(connection, request.principal_id, (str(request.entity_id),))
        held_claim = _identifier_claim_for_target(connection, request, target)
        if held_claim is not None:
            lock_identifier_claim_keys(connection, request.principal_id, (held_claim,))
    updated = connection.execute(
        update(entity_external_identifiers)
        .where(
            _mine(entity_external_identifiers, request.principal_id),
            entity_external_identifiers.c.identifier_id == target,
            entity_external_identifiers.c.entity_id == request.entity_id,
            entity_external_identifiers.c.version == expected,
            entity_external_identifiers.c.state == IdentifierState.ACTIVE.value,
        )
        .values(
            state=state.value,
            retired_at=retired_at,
            updated_at=request.server_received_at,
            version=entity_external_identifiers.c.version + 1,
            superseded_by_identifier_id=superseded_by_identifier_id,
        )
        .returning(entity_external_identifiers.c.identifier_id)
    ).first()
    if updated is not None:
        return {"identifier_id": target, "version": expected, "state": IdentifierState.ACTIVE.value}
    row = connection.execute(
        select(entity_external_identifiers).where(
            _mine(entity_external_identifiers, request.principal_id),
            entity_external_identifiers.c.identifier_id == target,
            entity_external_identifiers.c.entity_id == request.entity_id,
        )
    ).one_or_none()
    # Three different facts, told apart only after the guard has already
    # refused: the record is not this Principal's or not this entity's, the
    # caller read an older version of it, or it has already left service. Only
    # the second is worth re-reading and retrying, and a caller told `conflict`
    # for all three would not know which it had.
    if row is None:
        raise UnknownScopeError("an identifier transition names a record outside this scope")
    if int(row.version) != expected:
        raise StaleEntityVersionError("the expected identifier version is stale")
    raise DuplicateEntityFactError("that binding has already left service")


def _identifier_claim_for_target(
    connection: Connection, request: EntityWriteRequest, target: str
) -> tuple[str, str] | None:
    row = connection.execute(
        select(
            entity_external_identifiers.c.namespace,
            entity_external_identifiers.c.normalized_value,
        ).where(
            _mine(entity_external_identifiers, request.principal_id),
            entity_external_identifiers.c.identifier_id == target,
            entity_external_identifiers.c.entity_id == request.entity_id,
        )
    ).one_or_none()
    if row is None:
        return None
    return str(row.namespace), str(row.normalized_value)


def _transition_alias(
    connection: Connection,
    request: EntityWriteRequest,
    *,
    state: AliasState,
    superseded_by_alias_id: str | None,
) -> dict[str, Any]:
    """Move one active alias out of service, guarded on its own version."""
    target = str(request.target_child_id)
    expected = int(request.target_child_version or 0)
    updated = connection.execute(
        update(entity_aliases)
        .where(
            _mine(entity_aliases, request.principal_id),
            entity_aliases.c.alias_id == target,
            entity_aliases.c.entity_id == request.entity_id,
            entity_aliases.c.version == expected,
            entity_aliases.c.state == AliasState.ACTIVE.value,
        )
        .values(
            state=state.value,
            retired_at=request.server_received_at,
            updated_at=request.server_received_at,
            version=entity_aliases.c.version + 1,
            superseded_by_alias_id=superseded_by_alias_id,
        )
        .returning(entity_aliases.c.alias_id)
    ).first()
    if updated is not None:
        return {"alias_id": target, "version": expected, "state": AliasState.ACTIVE.value}
    row = connection.execute(
        select(entity_aliases).where(
            _mine(entity_aliases, request.principal_id),
            entity_aliases.c.alias_id == target,
            entity_aliases.c.entity_id == request.entity_id,
        )
    ).one_or_none()
    if row is None:
        raise UnknownScopeError("an alias transition names a record outside this scope")
    if int(row.version) != expected:
        raise StaleEntityVersionError("the expected alias version is stale")
    raise DuplicateEntityFactError("that name form has already left service")


def _record_evidence(
    connection: Connection, request: EntityWriteRequest, outcome: _Outcome
) -> tuple[str, ...]:
    """Bind each cited capture span to the fact this write produced.

    **The same-Principal check on the evidence half is the application's, and
    this is where it is made.** `entity_fact_evidence_links` says so on the
    table: the *fact* columns carry composite `(id, principal_id)` foreign keys
    and are structural, and the evidence columns cannot be, because
    `capture_spans` carries no principal partition at all. So the ownership is
    proved by walking the span to the capture that owns it, and a span behind
    another Principal's capture answers exactly what a span that does not exist
    answers.

    **The shape is checked before the walk, and `WP-RI-B-05` added that line.**
    PR #154's fifth non-blocking observation is exactly this omission, and
    Phase B touches the invariant: `EntitiesRepository.record_proposal_evidence_link`
    is a second writer of capture-span evidence, so the plane now has three of
    them and two spellings of the same precondition. `persistence.entity`'s
    `_link_evidence` has always validated its reference before the read; this
    one did not, and relied on the transport command's `_entity_evidence` --
    which is real but is a boundary that an in-process caller of
    `EntityAuthoringService` does not have to cross. A malformed reference
    reaching the query is answered "outside this scope", which is a statement
    about a Principal's partition made about a value that could never have been
    in anybody's.
    """
    if not request.evidence:
        return ()
    target_column = _EVIDENCE_TARGET_COLUMN[request.record_family]
    target_id = outcome.record_id
    link_ids: list[str] = []
    for reference, link_id in zip(request.evidence, request.minted_evidence_link_ids, strict=True):
        validate_identifier(reference, IdKind.SPAN)
        owned = connection.execute(
            select(capture_spans.c.span_id)
            .select_from(
                capture_spans.join(
                    capture_versions,
                    capture_versions.c.version_id == capture_spans.c.version_id,
                ).join(captures, captures.c.capture_id == capture_versions.c.capture_id)
            )
            .where(
                capture_spans.c.span_id == reference,
                captures.c.owner_principal_id == request.principal_id,
            )
        ).first()
        if owned is None:
            raise EntityEvidenceError("an entity write cites evidence outside this scope")
        connection.execute(
            insert(entity_fact_evidence_links).values(
                _bound(
                    entity_fact_evidence_links,
                    request.principal_id,
                    link_id=link_id,
                    **{target_column: target_id},
                    capture_span_id=reference,
                    # `DIRECT` and never `COUNTEREVIDENCE`. A caller citing
                    # evidence for its own write is saying "this is why"; a
                    # record arguing *against* a fact is something a reviewer
                    # attaches, and a role a writer could choose would let one
                    # file its own objection alongside its own assertion.
                    role=EvidenceRole.DIRECT.value,
                    authority=request.authority.value,
                    created_at=request.server_received_at,
                )
            )
        )
        link_ids.append(link_id)
    return tuple(link_ids)


def _record_mutation(
    connection: Connection,
    request: EntityWriteRequest,
    outcome: _Outcome,
    link_ids: tuple[str, ...],
) -> None:
    """Append the ledger row, which is also this plane's idempotency store.

    **`receipt_id` is null, and the identifier a caller is handed back is this
    row's own `event_id`.** The two are not the same decision. This plane issues
    no separate receipt record, so the column -- which exists to point at one --
    has nothing to point at; writing the row's own primary key into it would be
    a self-reference dressed as a reference, and would make `receipt_id IS NOT
    NULL` mean nothing to anyone reading the ledger. What the completion
    contract requires is that the *result* carry a `receipt_id`, and it does:
    `_entity_receipt` returns this row's `event_id`, which is durable, readable
    and carries the digest, the key, the before and after state and the audit
    identifier. Every write that reaches this function agrees on both halves,
    by construction: it is the single place this module appends the row.

    **No count is stated here, and the omission is deliberate.** This
    docstring said "all eighteen writes on this plane" from Phase A, when
    eighteen was the whole entity write surface. It is now thirty-eight, and
    the fifteen RI-ENT-WP-11 record-family writes do not reach this function
    at all -- they land through `my_pa.application.entity_record_families`.
    Whether those fifteen satisfy both halves is a question about their own
    write path, not about this one, and **it is unverified**: no test asserts
    it. Writing "thirty-eight" here would have asserted a coverage property
    nothing has checked, which is why the number was removed rather than
    corrected. A count is not derivable at this site in any case -- this
    module has no class whose writes could be enumerated -- so stating one
    would mean maintaining a figure by hand that nothing binds, which is the
    defect `test_entity_plane_prose_matches_the_capability_sets.py` exists to
    prevent.
    """
    try:
        connection.execute(
            insert(entity_mutation_events).values(
                _bound(
                    entity_mutation_events,
                    request.principal_id,
                    event_id=request.event_id,
                    capability=request.capability,
                    record_family=request.record_family.value,
                    record_id=outcome.record_id,
                    prior_version=outcome.prior_version,
                    new_version=outcome.new_version,
                    authority=request.authority.value,
                    # `null()` rather than `None`: a `None` handed to a JSONB
                    # column is the JSON value `null`, not SQL NULL, and
                    # `a_mutation_before_state_is_an_object` refuses it --
                    # correctly, because `'null'::jsonb` is not an object and a
                    # creation has no prior state to photograph.
                    before_state=outcome.before_state or null(),
                    after_state=_after_state(outcome, link_ids),
                    reason=request.reason,
                    idempotency_key=request.idempotency_key,
                    request_digest=request.payload_digest,
                    correlation_id=request.correlation_id,
                    audit_id=request.audit_id,
                    receipt_id=None,
                    actor_class=request.actor_class.value,
                    recorded_at=request.server_received_at,
                )
            )
        )
    except IntegrityError as violated:
        # `one_entity_mutation_per_key_and_capability`, and **only** that one.
        # A bare `except IntegrityError` here reported every constraint this
        # insert can break -- a malformed digest, an unknown authority, a
        # `before_state` that is not an object -- as an idempotency conflict,
        # which tells a caller to change its key over a defect in this module.
        # `23505` is SQLSTATE for a unique violation; anything else leaves as it
        # arrived, to be classified as the internal failure it is.
        if getattr(violated.orig, "sqlstate", None) != _UNIQUE_VIOLATION:
            raise
        raise EntityIdempotencyConflictError(
            "an entity idempotency key is bound to a different request"
        ) from None


def _entity_state(row: Row[Any]) -> dict[str, Any]:
    """One entity as the ledger photographs it. Evidence, never authority."""
    return {
        "entity_id": row.entity_id,
        "entity_type": row.entity_type,
        "canonical_name": row.canonical_name,
        "display_name": row.display_name,
        "status": row.status,
        "version": int(row.version),
        "archived_from_status": row.archived_from_status,
    }


def _after_state(outcome: _Outcome, link_ids: tuple[str, ...]) -> dict[str, Any]:
    """What the receipt is rebuilt from on a replay. See the module docstring."""
    return {
        "entity_id": outcome.entity_id,
        "entity_version": outcome.entity_version,
        "entity_status": outcome.entity_status.value,
        "child_id": outcome.child_id,
        "child_version": outcome.child_version,
        "child_state": outcome.child_state,
        "superseded_ids": list(outcome.superseded_ids),
        "evidence_link_ids": list(link_ids),
    }


def _receipt_from(row: Row[Any]) -> EntityMutationReceipt:
    """The stored ledger row as the receipt its original caller was handed."""
    after = row.after_state if isinstance(row.after_state, dict) else json.loads(row.after_state)
    return EntityMutationReceipt(
        event_id=row.event_id,
        capability=row.capability,
        record_family=MutationRecordFamily(row.record_family),
        record_id=row.record_id,
        entity_id=after["entity_id"],
        entity_version=int(after["entity_version"]),
        entity_status=EntityStatus(after["entity_status"]),
        idempotency_key=row.idempotency_key,
        issued_at=row.recorded_at,
        # **False, and this is the whole point of the flag.** The write happened
        # once; this caller is being handed the receipt for it rather than a
        # receipt for a second write, and a client retrying after a lost
        # response can tell the two apart without comparing versions.
        created=False,
        child_id=after["child_id"],
        child_version=None if after["child_version"] is None else int(after["child_version"]),
        child_state=after["child_state"],
        superseded_ids=tuple(after["superseded_ids"]),
        evidence_link_ids=tuple(after["evidence_link_ids"]),
    )
