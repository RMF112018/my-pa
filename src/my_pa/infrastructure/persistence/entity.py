"""Generalized entity persistence for relationship intelligence.

**Every statement in this module is bound to the `principal_id` each method
receives as its first argument**, exactly as `persistence.task_management`
does. All four entity tables carry a text `principal_id`, and the partition is
applied per-statement rather than at construction, so the same repository
instance can serve multiple Principals within the same transaction.

Three consequences follow, mirroring `persistence.task_management`:

* a foreign identifier answers exactly what an absent one answers -- ``None``
  from a get, and the same empty lists from every enumeration;
* an INSERT that names another Principal's entity is refused before it is
  written rather than accepted and filtered later;
* the partition predicate is part of every statement, not a check the caller
  was asked to remember.

**The foreign-key columns need the partition check the schema cannot give
them.** `entity_id`, `scope_entity_id`, `from_entity_id` and `to_entity_id` all
reference `entities.entity_id`, and that reference is global: PostgreSQL will
accept an assignment whose scope is another Principal's project, because the
row it points at exists. So every write here verifies each entity reference
against the acting Principal's partition first. A false join across Principals
is exactly the failure this plane exists to avoid, and a foreign key is not a
partition.

**The matched form is checked at this boundary, in both directions.** Every
column resolution compares against -- ``entities.canonical_name``,
``entity_aliases.normalized_value``, ``entity_external_identifiers.normalized_value``
-- is checked against `relationship.normalization` before it is written *and*
before a row carrying it is served. This repeats a rule the domain records
already state, and the repetition is the point (`RI-PR135-MAJOR-002`): the
records enforce it for anything that constructs one, and this enforces it for
anything that reaches the table. A row stored in a form the resolver's equality
predicate cannot match does not merely fail to resolve -- it *removes itself
from the candidate set*, so a same-named neighbour stops being ambiguous and is
returned as a confident answer. A wrong identity asserted with no warning is the
one failure `RI-RISK-001` is written about, and it is reached by writing a row,
not by resolving one.

**Why this is not a CHECK constraint.** `normalize_name` is NFKD, combining-mark
removal, punctuation-to-space, whitespace collapse, then `str.casefold`, and no
part of the second half survives translation to SQL. `lower(x) = x` is not
implied by it: 172 codepoints -- the Cherokee syllabary -- case-fold to
*uppercase*, so that predicate refuses a legitimately normalized Cherokee name.
A punctuation predicate over a word-character class is worse, because
`[[:alnum:]]` is decided by
the server's collation, so the same constraint refuses a legitimately normalized
CJK name on one server and admits it on another. A constraint that rejects
correct data is not a stricter guard than none; it is a different defect. The
invariant therefore lives where the algorithm does, and the cost of that choice
is stated rather than hidden: a hand-run `INSERT` on the server still bypasses
it, and **no test measures that bypass.** An earlier version of this paragraph
cited `tests/database/test_entity_storage_state_is_adversarial.py` for it. That
file has never existed. The guard itself is real -- `_require_normalized_name`
runs on the write path and on every read mapper, so nothing routed through this
repository can store or return an unnormalized name -- but the residual is
carried by argument, not by evidence, and saying so is the difference between a
known gap and a false citation.

**Idempotency, stated honestly.** ``bind_identifier`` and ``record_alias`` are
idempotent against a natural key -- each arbitrates a real partial unique index
over the *active* row, so a repeat is a no-op whatever identifier the caller
minted. Partial rather than total since ``2fe4e13fb449``, which is what lets a
retired binding and its replacement both be recorded; the residue is that the
identifier index is per Principal rather than per entity, so an address already
current on a *different* entity conflicts without being this caller's row, and
``bind_identifier`` reads the holder back and refuses rather than reporting a
write that did not happen. That read-back is a *second* statement under READ
COMMITTED, so the holder it looks for can be retired and committed by another
session in between; the bind is then re-attempted against the state that now
exists rather than answered with a ``NoResultFound`` from the driver, which is
the shape ``BIND_ATTEMPTS`` bounds. ``create``, ``record_assignment`` and
``record_relationship`` are idempotent against *their own identifier*: a repeat
carrying the same values returns quietly, and a repeat carrying different values
under an identifier already issued is refused rather than silently dropped. The
latter two now have a natural key on the server -- ``2fe4e13fb449`` added a
partial unique over the active row of each -- but neither write arbitrates it,
so a retry that mints a fresh identifier is refused by the server rather than
quietly deduplicated. Closing that needs an idempotency key on the write path,
and the write path arrives with the work package that has something observed to
write.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Final

from sqlalchemy import (
    Column,
    Row,
    Select,
    Table,
    insert,
    null,
    or_,
    select,
    true,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement, Label

from my_pa.contracts.ports import (
    AssignmentWriteRequest,
    DirectedReceipt,
    EntitiesRepository,
    EntityChildPage,
    EntityMutationAdmission,
    EntityMutationReceipt,
    EntitySummary,
    EntityWriteRequest,
    RelationshipWriteRequest,
    UnknownScopeError,
)
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.identity.operation import Capability
from my_pa.domain.relationship.authoring import (
    ConflictedIdentifierError,
    UnsettledBindingError,
)
from my_pa.domain.relationship.entity import (
    AliasState,
    AliasType,
    Assignment,
    AssignmentState,
    AssignmentType,
    DirectedWriteError,
    DirectedWriteOperation,
    DuplicateDirectedFactError,
    Entity,
    EntityAlias,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
    IdentifierState,
    MergedEndpointError,
    RelationshipState,
    StaleDirectedVersionError,
    descriptor_key,
)
from my_pa.domain.relationship.governance import (
    ActorClass,
    EntityFactEvidenceLink,
    EntityMergeRecord,
    EntityMutationConflictError,
    EntityMutationEvent,
    EntityObservation,
    EntityProposal,
    EntityProposalKind,
    EntityProposalState,
    EntityResolutionDecision,
    EvidenceRole,
    MutationAuthority,
    MutationRecordFamily,
    ObservationAuthority,
    ObservationKind,
    ObservationState,
    ResolutionDisposition,
)
from my_pa.domain.relationship.normalization import (
    is_normalized_identifier,
    is_normalized_name,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.entity_authoring import (
    ACTIVE_ALIAS_INDEX,
    ACTIVE_BINDING_INDEX,
    BIND_ATTEMPTS,
    admit_mutation,
    arbiter,
    mutation_replay_for,
)
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    entities,
    entity_aliases,
    entity_assignments,
    entity_external_identifiers,
    entity_fact_evidence_links,
    entity_merge_records,
    entity_mutation_events,
    entity_observations,
    entity_proposals,
    entity_relationships,
    entity_resolution_decisions,
)

__all__ = ["SqlEntityRepository"]

#: The `entities` columns one `Entity` is built from. Named once so the get,
#: the create-collision read, and the row mapper cannot drift apart.
_ENTITY_COLUMNS = (
    entities.c.entity_id,
    entities.c.principal_id,
    entities.c.entity_type,
    entities.c.canonical_name,
    entities.c.display_name,
    entities.c.status,
    entities.c.created_at,
    entities.c.updated_at,
    entities.c.version,
    entities.c.superseded_by_entity_id,
    entities.c.archived_from_status,
)

#: The prefix the two joined resolution lookups label their child table's
#: columns with.
#:
#: `entities`, `entity_external_identifiers` and `entity_aliases` all declare
#: `entity_id`, `principal_id`, `updated_at` and `version`. A `Row` read by
#: attribute answers with the *first* column of that name in the statement --
#: the entity's -- so an unlabelled joined select hydrated every identifier and
#: every alias with the entity's version and the entity's revision moment. The
#: first two collide harmlessly, because the join condition and the partition
#: predicate make them equal; the last two do not, and nothing catches it: both
#: are the same type, `int()` succeeds, and the record simply says something
#: false. Labelling the child side and reading it back through `_ChildRow` is
#: the shape `relationship_memory._VersionRow` already uses for the same
#: collision.
_CHILD_PREFIX = "child_"


def _labelled(column: Column[Any]) -> Label[Any]:
    """One child-table column under the prefix `_ChildRow` reads it back through."""
    return column.label(f"{_CHILD_PREFIX}{column.name}")


class _ChildRow:
    """A joined row read as though it held only the child table's columns.

    Both joined resolution lookups select `entities` and one child table at
    once, and label the child side; this adapts the labelled row back to the
    attribute names the child row mappers read, so those mappers stay the single
    definition of what a stored identifier or alias means.
    """

    def __init__(self, row: Row[Any]) -> None:
        self._row = row

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401 - mirrors a SQLAlchemy Row
        return getattr(self._row, f"{_CHILD_PREFIX}{name}")


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    """``table`` constrained to the given Principal."""
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, **values: object) -> dict[str, object]:
    """``values`` stamped with the given Principal for ``table``."""
    return principal_bound_values(dict(values), table, capture_context(principal_id))


def _optional(criterion: ColumnElement[bool] | None) -> ColumnElement[bool]:
    """``criterion`` when the caller asked for it, and an always-true one otherwise.

    So an optional filter stays *inside* the statement it filters. Appending it
    to a `conditions` list, or re-`where`-ing a saved statement, would move the
    partition predicate into a different statement from the `select` it guards,
    and `tests/architecture/test_principal_partition_is_reached_through_the_guard`
    reads one statement at a time -- correctly, since a partition a reader has
    to assemble from two places is a partition a reader can miss.
    """
    return true() if criterion is None else criterion


def _require_normalized_name(value: str) -> None:
    """Refuse a name that is not already the form resolution compares in.

    Checked here as well as in `Entity.__post_init__` and
    `EntityAlias.__post_init__`, and the duplication is deliberate. Those
    constructors bind anything that *builds a record*; this binds anything that
    *reaches the table*, which is a different population -- a bulk import, a
    backfill assembling rows from a source dump, a future writer that reuses a
    stored value without re-validating it, or a record whose validation was
    relaxed. `RI-PR135-MAJOR-002` is that these two populations were assumed to
    be the same one and are not.

    Raised as `ValueError` rather than `UnknownScopeError` because it is a
    malformed value rather than a foreign one: the caller named something real
    and named it wrongly, and `docs/specs` section 10 puts that under
    `invalid_request`, not `not_found`.
    """
    if not is_normalized_name(value):
        raise ValueError("an entity name is stored in the form resolution compares in")


def _require_normalized_identifier(namespace: ExternalIdentifierNamespace, value: str) -> None:
    """Refuse an external identifier value that is not already its normalized form.

    The same rule as `_require_normalized_name`, against the per-namespace
    algorithm rather than the name one, because the two are not the same
    function: an email folds its local part and its domain and keeps its `@`,
    which `normalize_name` would replace with a space. Checking a stored email
    against the name rule would refuse every correct row on the plane.

    The consequence of a miss is worse here than for a name, not better: the
    identifier path's ambiguity gate is `len({entity_id}) > 1` over the rows the
    equality predicate returned, so one unmatched row turns a
    `CONFLICTED_IDENTIFIER` refusal -- two people claiming one address, exactly
    the state a human must adjudicate -- into a silent `RESOLVED_EXACT`.
    """
    if not is_normalized_identifier(namespace, value):
        raise ValueError("an external identifier is stored in the form resolution compares in")


def _require_row_limit(limit: int | None) -> None:
    """Refuse a row limit that asks for nothing.

    `LIMIT 0` returns an empty page, which a caller reads as "there is nothing
    recorded" -- the one answer a bounded read must never give by accident. A
    negative limit is refused for the same reason rather than clamped, because
    silently substituting a limit the caller did not ask for is how a bound
    stops matching what the caller then discloses about it. This is the rule
    `observations` already states, factored out so that the six bounded reads
    on this plane cannot drift apart on it.
    """
    if limit is not None and limit < 1:
        raise ValueError("an entity row limit asks for at least one row")


def _limited[StatementT: Select[Any]](statement: StatementT, limit: int | None) -> StatementT:
    """`statement` with a `LIMIT`, or unchanged when the caller asked for none.

    Applied here rather than at each call site so that the `LIMIT` lands on the
    statement the partition predicate is already part of. It never touches the
    `where` clause, so it cannot move a partition predicate out of the statement
    it guards -- which is what
    `tests/architecture/test_principal_partition_is_reached_through_the_guard`
    reads one statement at a time to notice.
    """
    return statement if limit is None else statement.limit(limit)


def _contains(term: str) -> str:
    """``term`` as a LIKE pattern matching it literally, anywhere.

    `%` and `_` are LIKE metacharacters, so a query containing either would
    otherwise match more than the caller asked for -- a bare `%` matching every
    entity the Principal holds. Escaped against a stated ESCAPE character
    rather than stripped, because a name may legitimately contain both.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class SqlEntityRepository(EntitiesRepository):
    """SQLAlchemy implementation of ``EntitiesRepository``.

    Takes the connection rather than opening one, exactly as
    ``SqlTaskManagementRepository`` does: the caller owns the transaction,
    this class only issues statements on it. ``principal_id`` is passed per
    method and applied per statement, rather than bound at construction.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    # --- Partition guards ----------------------------------------------------

    def _require_own_entity(self, principal_id: str, entity_id: str) -> None:
        """Refuse an entity identifier the acting Principal does not hold."""
        validate_identifier(entity_id, IdKind.ENTITY)
        held = self._connection.execute(
            select(entities.c.entity_id).where(
                _mine(entities, principal_id),
                entities.c.entity_id == entity_id,
            )
        ).scalar_one_or_none()
        if held is None:
            raise UnknownScopeError("an entity operation names an entity outside this scope")

    def _require_own_entities(self, principal_id: str, *entity_ids: str | None) -> None:
        """The same guard over every entity reference a write carries.

        `None` is skipped: an absent optional scope is not a foreign one.
        """
        for entity_id in entity_ids:
            if entity_id is not None:
                self._require_own_entity(principal_id, entity_id)

    # --- Read operations -----------------------------------------------------

    def search(
        self,
        principal_id: str,
        query: str,
        entity_type: EntityType | None = None,
        limit: int = 50,
        *,
        after_entity_id: str | None = None,
    ) -> list[EntitySummary]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        _require_row_limit(limit)
        pattern = _contains(query)
        # **The cursor is an entity identifier, and the keyset is the sort key.**
        # This read orders by `(canonical_name, entity_id)` because a browse
        # surface sorts by name, so a cursor naming only the identifier would not
        # locate a position in that order. Rather than hand the caller an opaque
        # encoded pair, the cursor stays the last row's `entity_id` — validated,
        # partition-scoped, and already in the payload — and its sort position is
        # looked up here. A caller cannot forge a position it could not read.
        after = None
        if after_entity_id is not None:
            validate_identifier(after_entity_id, IdKind.ENTITY)
            located = self._connection.execute(
                select(entities.c.canonical_name, entities.c.entity_id).where(
                    _mine(entities, principal_id),
                    entities.c.entity_id == after_entity_id,
                )
            ).first()
            # **Refused, not silently restarted and not silently emptied.** A
            # cursor naming an entity this Principal cannot read is not a
            # position in their ordering. Left as a subquery it evaluated to
            # NULL, the row comparison went unknown, and the read answered with
            # an empty page — which a caller cannot tell from having reached the
            # end. Reporting completeness on a cursor that was never valid is
            # the shape of wrong answer this plane refuses everywhere else.
            if located is None:
                raise UnknownScopeError("a search cursor names an entity in this scope")
            after = (located.canonical_name, located.entity_id)
        rows = self._connection.execute(
            select(
                entities.c.entity_id,
                entities.c.entity_type,
                entities.c.canonical_name,
                entities.c.display_name,
                entities.c.status,
            )
            .where(
                _mine(entities, principal_id),
                or_(
                    entities.c.canonical_name.ilike(pattern, escape="\\"),
                    entities.c.display_name.ilike(pattern, escape="\\"),
                ),
                _optional(entities.c.entity_type == entity_type.value if entity_type else None),
                _optional(
                    tuple_(entities.c.canonical_name, entities.c.entity_id) > after
                    if after is not None
                    else None
                ),
            )
            .order_by(entities.c.canonical_name, entities.c.entity_id)
            .limit(limit)
        ).all()
        return [_row_to_summary(row) for row in rows]

    def get(self, principal_id: str, entity_id: str) -> Entity | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(entity_id, IdKind.ENTITY)
        row = self._connection.execute(
            select(*_ENTITY_COLUMNS).where(
                _mine(entities, principal_id),
                entities.c.entity_id == entity_id,
            )
        ).one_or_none()
        return None if row is None else _row_to_entity(row)

    def external_identifiers(
        self, principal_id: str, entity_id: str, *, limit: int | None = None
    ) -> list[ExternalIdentifier]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(entity_id, IdKind.ENTITY)
        _require_row_limit(limit)
        statement = (
            select(entity_external_identifiers)
            .where(
                _mine(entity_external_identifiers, principal_id),
                entity_external_identifiers.c.entity_id == entity_id,
            )
            .order_by(entity_external_identifiers.c.identifier_id)
        )
        rows = self._connection.execute(_limited(statement, limit)).all()
        return [_row_to_external_identifier(row) for row in rows]

    def aliases(
        self, principal_id: str, entity_id: str, *, limit: int | None = None
    ) -> list[EntityAlias]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(entity_id, IdKind.ENTITY)
        _require_row_limit(limit)
        statement = (
            select(entity_aliases)
            .where(
                _mine(entity_aliases, principal_id),
                entity_aliases.c.entity_id == entity_id,
            )
            .order_by(entity_aliases.c.alias_id)
        )
        rows = self._connection.execute(_limited(statement, limit)).all()
        return [_row_to_alias(row) for row in rows]

    def entities_by_identifier(
        self,
        principal_id: str,
        namespace: ExternalIdentifierNamespace,
        normalized_value: str,
    ) -> list[tuple[Entity, ExternalIdentifier]]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        rows = self._connection.execute(
            select(
                *_ENTITY_COLUMNS,
                *(_labelled(column) for column in entity_external_identifiers.c),
            )
            .join_from(
                entities,
                entity_external_identifiers,
                entities.c.entity_id == entity_external_identifiers.c.entity_id,
            )
            .where(
                _mine(entities, principal_id),
                _mine(entity_external_identifiers, principal_id),
                entity_external_identifiers.c.namespace == namespace.value,
                entity_external_identifiers.c.normalized_value == normalized_value,
            )
            .order_by(entities.c.entity_id)
        ).all()
        return [(_row_to_entity(row), _row_to_external_identifier(_ChildRow(row))) for row in rows]

    def entities_by_alias(
        self, principal_id: str, normalized_value: str
    ) -> list[tuple[Entity, EntityAlias]]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        rows = self._connection.execute(
            select(*_ENTITY_COLUMNS, *(_labelled(column) for column in entity_aliases.c))
            .join_from(
                entities,
                entity_aliases,
                entities.c.entity_id == entity_aliases.c.entity_id,
            )
            .where(
                _mine(entities, principal_id),
                _mine(entity_aliases, principal_id),
                entity_aliases.c.normalized_value == normalized_value,
            )
            .order_by(entities.c.entity_id, entity_aliases.c.alias_id)
        ).all()
        return [(_row_to_entity(row), _row_to_alias(_ChildRow(row))) for row in rows]

    def entities_by_canonical_name(self, principal_id: str, normalized_value: str) -> list[Entity]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        rows = self._connection.execute(
            select(*_ENTITY_COLUMNS)
            .where(
                _mine(entities, principal_id),
                entities.c.canonical_name == normalized_value,
            )
            .order_by(entities.c.entity_id)
        ).all()
        return [_row_to_entity(row) for row in rows]

    def assignments(
        self,
        principal_id: str,
        entity_id: str,
        active_only: bool = True,
        *,
        limit: int | None = None,
    ) -> list[Assignment]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(entity_id, IdKind.ENTITY)
        _require_row_limit(limit)
        statement = (
            select(entity_assignments)
            .where(
                _mine(entity_assignments, principal_id),
                entity_assignments.c.entity_id == entity_id,
                _optional(
                    entity_assignments.c.state == AssignmentState.ACTIVE.value
                    if active_only
                    else None
                ),
            )
            .order_by(entity_assignments.c.assignment_id)
        )
        rows = self._connection.execute(_limited(statement, limit)).all()
        return [_row_to_assignment(row) for row in rows]

    def relationships(
        self,
        principal_id: str,
        entity_id: str,
        direction: str = "any",
        *,
        limit: int | None = None,
        after_relationship_id: str | None = None,
    ) -> list[EntityRelationship]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(entity_id, IdKind.ENTITY)
        if direction not in _DIRECTIONS:
            raise ValueError("an entity relationship direction is any, outgoing, or incoming")
        _require_row_limit(limit)
        if after_relationship_id is not None:
            validate_identifier(after_relationship_id, IdKind.ENTITY_RELATIONSHIP)
            # Refused on the same terms `search` refuses one. A well-formed
            # cursor naming an edge this Principal cannot read is not a position
            # in their ordering, and the bare `>` below is true of it — so the
            # read would answer with an empty page and no truncation, which a
            # caller cannot tell from having reached the end.
            reachable = self._connection.execute(
                select(entity_relationships.c.relationship_id).where(
                    _mine(entity_relationships, principal_id),
                    entity_relationships.c.relationship_id == after_relationship_id,
                )
            ).first()
            if reachable is None:
                raise UnknownScopeError("a relationship cursor names an edge in this scope")
        # The continuation predicate is `>` against the same column the
        # `order_by` uses, inside the same statement as the partition. A cursor
        # applied by dropping rows after the fetch would still have read them,
        # and a cursor applied to a differently ordered statement would skip
        # edges rather than continue past them.
        statement = (
            select(entity_relationships)
            .where(
                _mine(entity_relationships, principal_id),
                _DIRECTIONS[direction](entity_id),
                _optional(
                    entity_relationships.c.relationship_id > after_relationship_id
                    if after_relationship_id is not None
                    else None
                ),
            )
            .order_by(entity_relationships.c.relationship_id)
        )
        rows = self._connection.execute(_limited(statement, limit)).all()
        return [_row_to_relationship(row) for row in rows]

    # --- WP-RI-A-02: the paged child reads -----------------------------------
    #
    # Separate from `external_identifiers` and `aliases` rather than parameters
    # on them, and the port docstrings say why: those two default to unbounded
    # because resolution reads each collection whole to decide whether an
    # identifier is conflicted, and a bound applied beneath resolution would let
    # a conflict fall off the end of a page and read as a clean match. These two
    # are bounded, filterable, and *disclose* their bound.

    def identifier_page(
        self,
        entity_id: str,
        *,
        principal_id: str,
        limit: int,
        states: frozenset[IdentifierState] | None = None,
        namespaces: frozenset[ExternalIdentifierNamespace] | None = None,
        after_identifier_id: str | None = None,
    ) -> EntityChildPage[ExternalIdentifier]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(entity_id, IdKind.ENTITY)
        _require_row_limit(limit)
        self._require_own_entity(principal_id, entity_id)
        after = self._located_child(
            entity_external_identifiers.c.identifier_id,
            entity_external_identifiers.c.entity_id,
            _mine(entity_external_identifiers, principal_id),
            entity_id=entity_id,
            cursor=after_identifier_id,
            kind=IdKind.EXTERNAL_IDENTIFIER,
        )
        rows = self._connection.execute(
            select(entity_external_identifiers)
            .where(
                _mine(entity_external_identifiers, principal_id),
                entity_external_identifiers.c.entity_id == entity_id,
                _optional(
                    entity_external_identifiers.c.state.in_(sorted(state.value for state in states))
                    if states
                    else None
                ),
                _optional(
                    entity_external_identifiers.c.namespace.in_(
                        sorted(namespace.value for namespace in namespaces)
                    )
                    if namespaces
                    else None
                ),
                _optional(entity_external_identifiers.c.identifier_id > after if after else None),
            )
            .order_by(entity_external_identifiers.c.identifier_id)
            # One row past the ceiling, so truncation is proved rather than
            # inferred from a page that happened to be full.
            .limit(limit + 1)
        ).all()
        return EntityChildPage(
            records=tuple(_row_to_external_identifier(row) for row in rows[:limit]),
            is_truncated=len(rows) > limit,
        )

    def alias_page(
        self,
        entity_id: str,
        *,
        principal_id: str,
        limit: int,
        states: frozenset[AliasState] | None = None,
        alias_types: frozenset[AliasType] | None = None,
        after_alias_id: str | None = None,
    ) -> EntityChildPage[EntityAlias]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(entity_id, IdKind.ENTITY)
        _require_row_limit(limit)
        self._require_own_entity(principal_id, entity_id)
        after = self._located_child(
            entity_aliases.c.alias_id,
            entity_aliases.c.entity_id,
            _mine(entity_aliases, principal_id),
            entity_id=entity_id,
            cursor=after_alias_id,
            kind=IdKind.ENTITY_ALIAS,
        )
        rows = self._connection.execute(
            select(entity_aliases)
            .where(
                _mine(entity_aliases, principal_id),
                entity_aliases.c.entity_id == entity_id,
                _optional(
                    entity_aliases.c.state.in_(sorted(state.value for state in states))
                    if states
                    else None
                ),
                _optional(
                    entity_aliases.c.alias_type.in_(sorted(kind.value for kind in alias_types))
                    if alias_types
                    else None
                ),
                _optional(entity_aliases.c.alias_id > after if after else None),
            )
            .order_by(entity_aliases.c.alias_id)
            .limit(limit + 1)
        ).all()
        return EntityChildPage(
            records=tuple(_row_to_alias(row) for row in rows[:limit]),
            is_truncated=len(rows) > limit,
        )

    def _located_child(
        self,
        key: Column[Any],
        owner: Column[Any],
        partition: ColumnElement[bool],
        *,
        entity_id: str,
        cursor: str | None,
        kind: IdKind,
    ) -> str | None:
        """Refuse a cursor that names no record of this entity, or return it.

        **Refused, not silently restarted and not silently emptied**, which is
        the rule `search` states for its own cursor: a caller handed an empty
        page cannot tell it from having reached the end, and reporting
        completeness on a cursor that was never valid is a wrong answer rather
        than a missing one.

        The partition arrives already built rather than as a `principal_id` this
        method scopes for itself, and that is not a style choice:
        `tests/architecture/test_principal_partition_is_reached_through_the_guard`
        reads one *statement* at a time, so a shared helper that named the table
        while its caller named the Principal would put the two halves of one
        predicate in two statements -- which is exactly the shape that guard
        exists to notice, and it cannot tell a safe instance of it from an
        unsafe one.
        """
        if cursor is None:
            return None
        validate_identifier(cursor, kind)
        located = self._connection.execute(
            select(key).where(partition, owner == entity_id, key == cursor)
        ).scalar_one_or_none()
        if located is None:
            raise UnknownScopeError("a child cursor names a record of this entity in this scope")
        return str(located)

    # --- WP-RI-A-02: the governed write path ---------------------------------

    def admit_mutation(self, request: EntityWriteRequest) -> EntityMutationAdmission:
        return admit_mutation(self._connection, request)

    def mutation_replay_for(
        self,
        idempotency_key: str,
        request_digest: str,
        *,
        principal_id: str,
        capability: str,
    ) -> EntityMutationReceipt | None:
        return mutation_replay_for(
            self._connection,
            idempotency_key,
            request_digest,
            principal_id=principal_id,
            capability=capability,
        )

    # --- Write operations ----------------------------------------------------

    def create(self, principal_id: str, entity: Entity) -> Entity:
        """Insert one entity row, or return the identical existing one."""
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if entity.principal_id != principal_id:
            raise ValueError("an entity belongs to the acting Principal")
        _require_normalized_name(entity.canonical_name)
        existing = self._connection.execute(
            select(*_ENTITY_COLUMNS).where(
                _mine(entities, entity.principal_id),
                entities.c.entity_id == entity.entity_id,
            )
        ).one_or_none()
        if existing is not None:
            held = _row_to_entity(existing)
            if held != entity:
                raise ValueError("an entity identifier cannot be rebound to different values")
            return held
        if entity.superseded_by_entity_id is not None:
            self._require_own_entity(entity.principal_id, entity.superseded_by_entity_id)
        self._connection.execute(
            insert(entities).values(
                _bound(
                    entities,
                    entity.principal_id,
                    entity_id=entity.entity_id,
                    entity_type=entity.entity_type.value,
                    canonical_name=entity.canonical_name,
                    display_name=entity.display_name,
                    status=entity.status.value,
                    created_at=entity.created_at,
                    updated_at=entity.updated_at,
                    version=entity.version,
                    superseded_by_entity_id=entity.superseded_by_entity_id,
                    archived_from_status=(
                        None
                        if entity.archived_from_status is None
                        else entity.archived_from_status.value
                    ),
                )
            )
        )
        return entity

    def bind_identifier(
        self, principal_id: str, entity_id: str, identifier: ExternalIdentifier
    ) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if identifier.entity_id != entity_id:
            raise ValueError("an external identifier binds to the entity it names")
        if identifier.principal_id != principal_id:
            raise ValueError("an external identifier belongs to the acting Principal")
        _require_normalized_identifier(identifier.namespace, identifier.normalized_value)
        self._require_own_entity(principal_id, entity_id)
        # Arbitrated on the *active* binding rather than on a total unique over
        # `(entity_id, namespace, normalized_value)`, which `2fe4e13fb449`
        # dropped: a total unique made recording the replacement of a retired
        # address require deleting the row that resolves a message sent before
        # it was reissued. Idempotency against a re-bind is kept; what the
        # arbiter cannot express is that the conflicting active row might be
        # another entity's, so that case is read back and identified below
        # rather than reported to the caller as a write that happened.
        for _ in range(BIND_ATTEMPTS):
            if self._wrote_the_binding(principal_id, entity_id, identifier):
                return
            holder = self._the_active_binding_holder(principal_id, identifier)
            if holder is None:
                # The row that refused the insert is gone by the time the
                # read-back runs. Under READ COMMITTED that is a real
                # interleaving, not an impossible one: another session retired
                # the holder and committed inside the window between the two
                # statements. Neither refusing nor returning is right -- the
                # address now belongs to nobody, so the caller's bind is the
                # write a serialized execution would have performed after that
                # retirement -- and the honest answer is to attempt it again
                # against the state that now exists. The read-back is what makes
                # this bounded rather than a spin: it distinguishes "somebody
                # else holds it" from "nobody does", so the loop only turns on
                # the second.
                continue
            if holder != entity_id:
                raise ConflictedIdentifierError(
                    "an active external identity binds exactly one entity"
                )
            return
        # Every attempt was refused by a holder that had vanished before it could
        # be named. A typed error rather than a `NoResultFound` because this is
        # the port's boundary: `EntitiesRepository.bind_identifier` says a store
        # that cannot settle the question raises its own error, and a
        # `sqlalchemy.exc` class escaping here would make every caller of the
        # port import SQLAlchemy to handle it.
        #
        # **Typed, and until `WP-RI-A-02` it was not.** This and the refusal
        # above were both a bare `ValueError` separated only by message, so a
        # handler classifying `ValueError` reported this retryable race as the
        # permanent conflict above -- telling a caller to stop when the address
        # may already be free. Both classes still subclass `ValueError`, so
        # every existing handler is unchanged.
        raise UnsettledBindingError(
            "an external identity binding could not be settled against a concurrent retirement"
        )

    def _wrote_the_binding(
        self, principal_id: str, entity_id: str, identifier: ExternalIdentifier
    ) -> bool:
        """Attempt the insert once; `True` when a row was actually written."""
        written = self._connection.execute(
            pg_insert(entity_external_identifiers)
            .values(
                _bound(
                    entity_external_identifiers,
                    principal_id,
                    identifier_id=identifier.identifier_id,
                    entity_id=entity_id,
                    namespace=identifier.namespace.value,
                    normalized_value=identifier.normalized_value,
                    display_value=identifier.display_value,
                    verified=identifier.verified,
                    effective_from=identifier.effective_from,
                    effective_to=identifier.effective_to,
                    state=identifier.state.value,
                    version=identifier.version,
                    updated_at=identifier.updated_at,
                    retired_at=identifier.retired_at,
                    superseded_by_identifier_id=identifier.superseded_by_identifier_id,
                )
            )
            .on_conflict_do_nothing(**arbiter(ACTIVE_BINDING_INDEX))
            # `RETURNING` rather than `rowcount`, which this driver reports as
            # `-1` for an INSERT and so cannot distinguish a written row from a
            # skipped one. A skipped `DO NOTHING` returns no row at all.
            .returning(entity_external_identifiers.c.identifier_id)
        )
        return written.first() is not None

    def _the_active_binding_holder(
        self, principal_id: str, identifier: ExternalIdentifier
    ) -> str | None:
        """The entity whose current identity this address is, or `None`.

        Read only when the insert wrote nothing, which happens exactly when an
        active row of this Principal held this namespace and value at the moment
        the insert arbitrated. If that row is the binding entity's, the caller
        re-bound what is already recorded and there is nothing to do. If it is
        another entity's, the caller asked for a second current claimant of one
        address, which is the state
        `an_active_external_identifier_binding_is_unique` exists to prevent --
        and answering that with silence would report a binding the store does
        not hold.

        `scalar_one_or_none` rather than `scalar_one`, and the difference is not
        defensive: this connection reads under READ COMMITTED, so the row the
        insert conflicted with can be retired and committed by another session
        before this statement takes its snapshot. `scalar_one` raises
        `sqlalchemy.exc.NoResultFound` for that, which is an infrastructure
        exception crossing a port that promises `ValueError`. `None` says
        "nobody holds it now" and lets the caller decide, which is the only
        answer this read is entitled to give.
        """
        holder = self._connection.execute(
            select(entity_external_identifiers.c.entity_id).where(
                _mine(entity_external_identifiers, principal_id),
                entity_external_identifiers.c.namespace == identifier.namespace.value,
                entity_external_identifiers.c.normalized_value == identifier.normalized_value,
                entity_external_identifiers.c.state == IdentifierState.ACTIVE.value,
            )
        ).scalar_one_or_none()
        return None if holder is None else str(holder)

    def record_alias(self, principal_id: str, alias: EntityAlias) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if alias.principal_id != principal_id:
            raise ValueError("an alias belongs to the acting Principal")
        _require_normalized_name(alias.normalized_value)
        self._require_own_entity(principal_id, alias.entity_id)
        self._connection.execute(
            pg_insert(entity_aliases)
            .values(
                _bound(
                    entity_aliases,
                    principal_id,
                    alias_id=alias.alias_id,
                    entity_id=alias.entity_id,
                    alias_type=alias.alias_type.value,
                    normalized_value=alias.normalized_value,
                    display_value=alias.display_value,
                    effective_from=alias.effective_from,
                    effective_to=alias.effective_to,
                    state=alias.state.value,
                    version=alias.version,
                    updated_at=alias.updated_at,
                    retired_at=alias.retired_at,
                    superseded_by_alias_id=alias.superseded_by_alias_id,
                )
            )
            # The same move as `bind_identifier`, and without its residue: the
            # active alias unique is already per entity, so a conflict here can
            # only be this entity's own row and DO NOTHING says exactly that.
            .on_conflict_do_nothing(**arbiter(ACTIVE_ALIAS_INDEX))
        )

    def record_assignment(self, principal_id: str, assignment: Assignment) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if assignment.principal_id != principal_id:
            raise ValueError("an assignment belongs to the acting Principal")
        self._require_own_entities(principal_id, assignment.entity_id, assignment.scope_entity_id)
        existing = self._connection.execute(
            select(entity_assignments).where(
                _mine(entity_assignments, principal_id),
                entity_assignments.c.assignment_id == assignment.assignment_id,
            )
        ).one_or_none()
        if existing is not None:
            if _row_to_assignment(existing) != assignment:
                raise ValueError("an assignment identifier cannot be rebound to different values")
            return
        self._connection.execute(
            insert(entity_assignments).values(
                _bound(
                    entity_assignments,
                    principal_id,
                    assignment_id=assignment.assignment_id,
                    entity_id=assignment.entity_id,
                    scope_entity_id=assignment.scope_entity_id,
                    assignment_type=assignment.assignment_type.value,
                    role=assignment.role,
                    discipline=assignment.discipline,
                    responsibility_class=assignment.responsibility_class,
                    effective_from=assignment.effective_from,
                    effective_to=assignment.effective_to,
                    state=assignment.state.value,
                    version=assignment.version,
                    updated_at=assignment.updated_at,
                    ended_at=assignment.ended_at,
                    superseded_by_assignment_id=assignment.superseded_by_assignment_id,
                )
            )
        )

    def record_relationship(self, principal_id: str, rel: EntityRelationship) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if rel.principal_id != principal_id:
            raise ValueError("an entity relationship belongs to the acting Principal")
        self._require_own_entities(
            principal_id, rel.from_entity_id, rel.to_entity_id, rel.scope_entity_id
        )
        existing = self._connection.execute(
            select(entity_relationships).where(
                _mine(entity_relationships, principal_id),
                entity_relationships.c.relationship_id == rel.relationship_id,
            )
        ).one_or_none()
        if existing is not None:
            if _row_to_relationship(existing) != rel:
                raise ValueError(
                    "an entity relationship identifier cannot be rebound to different values"
                )
            return
        self._connection.execute(
            insert(entity_relationships).values(
                _bound(
                    entity_relationships,
                    principal_id,
                    relationship_id=rel.relationship_id,
                    from_entity_id=rel.from_entity_id,
                    to_entity_id=rel.to_entity_id,
                    relationship_type=rel.relationship_type.value,
                    scope_entity_id=rel.scope_entity_id,
                    effective_from=rel.effective_from,
                    effective_to=rel.effective_to,
                    state=rel.state.value,
                    version=rel.version,
                    updated_at=rel.updated_at,
                    ended_at=rel.ended_at,
                    superseded_by_relationship_id=rel.superseded_by_relationship_id,
                )
            )
        )

    # --- WP-RI-06: observation, proposal, and merge lineage ------------------

    # --- The directed-relationship write path (WP-RI-A-03) -------------------
    #
    # Six writes and two lookups, and one shape they all take:
    #
    #   1. read the current record, or the endpoints a create binds to;
    #   2. refuse a stale expectation *before* anything is written;
    #   3. write the record;
    #   4. write the evidence links;
    #   5. append the ledger row, which is the receipt.
    #
    # The order is the guarantee. A stale expectation leaves at step two, so it
    # writes no record, no evidence link and no ledger row, and the prior state
    # stands exactly as it did -- which is what "fails deterministically and
    # preserves prior state" has to mean if it is to be testable. The ledger is
    # last because it records what happened, and a ledger row written before the
    # record would describe a write that could still fail.
    #
    # **The active semantic uniques are the database's, not this module's.**
    # `an_active_assignment_is_recorded_once` and
    # `an_active_entity_relationship_is_recorded_once` are what actually refuse a
    # duplicate; the pre-read below exists only so the refusal arrives as
    # `DuplicateDirectedFactError` rather than as a driver exception, and the
    # `IntegrityError` handler is what catches the case the pre-read cannot see:
    # two concurrent writers that both read nothing.

    def assignment(self, principal_id: str, assignment_id: str) -> Assignment | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(assignment_id, IdKind.ASSIGNMENT)
        row = self._connection.execute(
            select(entity_assignments).where(
                _mine(entity_assignments, principal_id),
                entity_assignments.c.assignment_id == assignment_id,
            )
        ).one_or_none()
        return None if row is None else _row_to_assignment(row)

    def relationship(self, principal_id: str, relationship_id: str) -> EntityRelationship | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(relationship_id, IdKind.ENTITY_RELATIONSHIP)
        row = self._connection.execute(
            select(entity_relationships).where(
                _mine(entity_relationships, principal_id),
                entity_relationships.c.relationship_id == relationship_id,
            )
        ).one_or_none()
        return None if row is None else _row_to_relationship(row)

    def assignments_page(
        self,
        principal_id: str,
        entity_id: str,
        *,
        active_only: bool,
        limit: int,
        after_assignment_id: str | None = None,
    ) -> list[Assignment]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(entity_id, IdKind.ENTITY)
        _require_row_limit(limit)
        if after_assignment_id is not None:
            validate_identifier(after_assignment_id, IdKind.ASSIGNMENT)
            # Refused on the terms `relationships` refuses an unreachable edge
            # cursor. A well-formed cursor naming an assignment this Principal
            # cannot read is not a position in their ordering, and the bare `>`
            # below is true of it -- so the read would answer with an empty page
            # and no truncation, which a caller cannot tell from the end.
            reachable = self._connection.execute(
                select(entity_assignments.c.assignment_id).where(
                    _mine(entity_assignments, principal_id),
                    entity_assignments.c.assignment_id == after_assignment_id,
                )
            ).first()
            if reachable is None:
                raise UnknownScopeError("an assignment cursor names a row in this scope")
        statement = (
            select(entity_assignments)
            .where(
                _mine(entity_assignments, principal_id),
                entity_assignments.c.entity_id == entity_id,
                _optional(
                    entity_assignments.c.state == AssignmentState.ACTIVE.value
                    if active_only
                    else None
                ),
                _optional(
                    entity_assignments.c.assignment_id > after_assignment_id
                    if after_assignment_id is not None
                    else None
                ),
            )
            .order_by(entity_assignments.c.assignment_id)
        )
        rows = self._connection.execute(_limited(statement, limit)).all()
        return [_row_to_assignment(row) for row in rows]

    def directed_replay(
        self,
        capability: str,
        idempotency_key: str,
        payload_digest: str,
        *,
        principal_id: str,
    ) -> DirectedReceipt | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        row = self._connection.execute(
            select(entity_mutation_events).where(
                _mine(entity_mutation_events, principal_id),
                entity_mutation_events.c.capability == capability,
                entity_mutation_events.c.idempotency_key == idempotency_key,
            )
        ).one_or_none()
        if row is None:
            return None
        if str(row.request_digest) != payload_digest:
            raise DirectedWriteError("this idempotency key is bound to a different request")
        return _row_to_directed_receipt(row, replayed=True)

    def create_assignment(self, request: AssignmentWriteRequest) -> DirectedReceipt:
        entity_id = request.entity_id
        assignment_type = request.assignment_type
        if entity_id is None or assignment_type is None:
            # `AssignmentWriteRequest.__post_init__` already refuses both, so
            # this narrows for the type checker rather than restating a rule. It
            # raises rather than asserting: an assertion disappears under `-O`,
            # and a create reaching here without a subject would insert a row
            # with a null one.
            raise DirectedWriteError("an assignment creation names its subject and its type")
        self._require_writable_entity(
            request.principal_id, entity_id, request.expected_entity_version
        )
        if request.scope_entity_id is not None:
            self._require_writable_entity(
                request.principal_id, request.scope_entity_id, request.expected_scope_version
            )
        self._refuse_duplicate_assignment(request, entity_id, assignment_type)
        assignment_id = issue_identifier(IdKind.ASSIGNMENT)
        assignment = Assignment(
            assignment_id=assignment_id,
            entity_id=entity_id,
            assignment_type=assignment_type,
            principal_id=request.principal_id,
            scope_entity_id=request.scope_entity_id,
            role=request.role,
            discipline=request.discipline,
            responsibility_class=request.responsibility_class,
            effective_from=request.effective_from,
            effective_to=request.effective_to,
            state=AssignmentState.ACTIVE,
            version=1,
            updated_at=request.server_received_at,
        )
        with _duplicate_translated(_ASSIGNMENT_UNIQUE):
            self._connection.execute(
                insert(entity_assignments).values(
                    _bound(
                        entity_assignments,
                        request.principal_id,
                        assignment_id=assignment.assignment_id,
                        entity_id=assignment.entity_id,
                        scope_entity_id=assignment.scope_entity_id,
                        assignment_type=assignment.assignment_type.value,
                        role=assignment.role,
                        discipline=assignment.discipline,
                        responsibility_class=assignment.responsibility_class,
                        effective_from=assignment.effective_from,
                        effective_to=assignment.effective_to,
                        state=assignment.state.value,
                        version=assignment.version,
                        updated_at=assignment.updated_at,
                    )
                )
            )
        self._link_evidence(request, assignment_id=assignment_id)
        return self._append_mutation(
            request,
            capability=_ASSIGNMENT_CAPABILITIES[request.operation],
            family=MutationRecordFamily.ASSIGNMENT,
            record_id=assignment_id,
            prior_version=None,
            new_version=1,
            before_state=None,
            after_state=_assignment_state(assignment),
            state=assignment.state.value,
        )

    def revise_assignment(self, request: AssignmentWriteRequest) -> DirectedReceipt:
        return self._mutate_assignment(request, ending=False)

    def end_assignment(self, request: AssignmentWriteRequest) -> DirectedReceipt:
        return self._mutate_assignment(request, ending=True)

    def create_relationship(self, request: RelationshipWriteRequest) -> DirectedReceipt:
        from_entity_id = request.from_entity_id
        to_entity_id = request.to_entity_id
        relationship_type = request.relationship_type
        if from_entity_id is None or to_entity_id is None or relationship_type is None:
            raise DirectedWriteError("an edge creation names both endpoints and its type")
        self._require_writable_entity(
            request.principal_id, from_entity_id, request.expected_from_version
        )
        self._require_writable_entity(
            request.principal_id, to_entity_id, request.expected_to_version
        )
        if request.scope_entity_id is not None:
            self._require_writable_entity(
                request.principal_id, request.scope_entity_id, request.expected_scope_version
            )
        self._refuse_duplicate_relationship(
            request, from_entity_id, relationship_type, to_entity_id
        )
        relationship_id = issue_identifier(IdKind.ENTITY_RELATIONSHIP)
        edge = EntityRelationship(
            relationship_id=relationship_id,
            from_entity_id=from_entity_id,
            relationship_type=relationship_type,
            to_entity_id=to_entity_id,
            principal_id=request.principal_id,
            scope_entity_id=request.scope_entity_id,
            effective_from=request.effective_from,
            effective_to=request.effective_to,
            state=RelationshipState.ACTIVE,
            version=1,
            updated_at=request.server_received_at,
        )
        with _duplicate_translated(_RELATIONSHIP_UNIQUE):
            self._connection.execute(
                insert(entity_relationships).values(
                    _bound(
                        entity_relationships,
                        request.principal_id,
                        relationship_id=edge.relationship_id,
                        from_entity_id=edge.from_entity_id,
                        to_entity_id=edge.to_entity_id,
                        relationship_type=edge.relationship_type.value,
                        scope_entity_id=edge.scope_entity_id,
                        effective_from=edge.effective_from,
                        effective_to=edge.effective_to,
                        state=edge.state.value,
                        version=edge.version,
                        updated_at=edge.updated_at,
                    )
                )
            )
        self._link_evidence(request, relationship_id=relationship_id)
        return self._append_mutation(
            request,
            capability=_RELATIONSHIP_CAPABILITIES[request.operation],
            family=MutationRecordFamily.RELATIONSHIP,
            record_id=relationship_id,
            prior_version=None,
            new_version=1,
            before_state=None,
            after_state=_relationship_state(edge),
            state=edge.state.value,
        )

    def revise_relationship(self, request: RelationshipWriteRequest) -> DirectedReceipt:
        return self._mutate_relationship(request, ending=False)

    def end_relationship(self, request: RelationshipWriteRequest) -> DirectedReceipt:
        return self._mutate_relationship(request, ending=True)

    # --- the two guarded mutations -------------------------------------------

    def _mutate_assignment(
        self, request: AssignmentWriteRequest, *, ending: bool
    ) -> DirectedReceipt:
        """Revise or end one assignment behind a single guarded `UPDATE`.

        The current row is read first so the ledger can record what the record
        said before, and so an absent or foreign assignment is `not_found`
        rather than a stale-version conflict -- but the read is not the guard.
        The guard is the `version = :expected` predicate on the `UPDATE` itself,
        whose rowcount is checked before anything else is written, so a row that
        changed between the read and the write is refused rather than
        overwritten.
        """
        assignment_id = request.assignment_id
        if assignment_id is None:
            raise DirectedWriteError("a state-dependent assignment write names its assignment")
        current = self.assignment(request.principal_id, assignment_id)
        if current is None:
            raise UnknownScopeError("an assignment write names a row outside this scope")
        cleared = frozenset(request.cleared)
        if ending:
            values: dict[str, Any] = {
                "state": AssignmentState.ENDED.value,
                "ended_at": request.server_received_at,
                "effective_to": request.effective_to,
            }
            after_role = current.role
            after_discipline = current.discipline
            after_responsibility = current.responsibility_class
            after_from = current.effective_from
            after_to = request.effective_to
            after_state_name = AssignmentState.ENDED.value
        else:
            after_role = _resolved(request.role, current.role, "role" in cleared)
            after_discipline = _resolved(
                request.discipline, current.discipline, "discipline" in cleared
            )
            after_responsibility = _resolved(
                request.responsibility_class,
                current.responsibility_class,
                "responsibility_class" in cleared,
            )
            after_from = _resolved(
                request.effective_from, current.effective_from, "effective_from" in cleared
            )
            after_to = _resolved(
                request.effective_to, current.effective_to, "effective_to" in cleared
            )
            if after_from is not None and after_to is not None and after_to < after_from:
                raise DirectedWriteError("an assignment cannot end before it begins")
            values = {
                "role": after_role,
                "discipline": after_discipline,
                "responsibility_class": after_responsibility,
                "effective_from": after_from,
                "effective_to": after_to,
            }
            after_state_name = current.state.value
        values["version"] = current.version + 1
        values["updated_at"] = request.server_received_at
        with _duplicate_translated(_ASSIGNMENT_UNIQUE):
            updated = self._connection.execute(
                update(entity_assignments)
                .where(
                    _mine(entity_assignments, request.principal_id),
                    entity_assignments.c.assignment_id == assignment_id,
                    entity_assignments.c.version == request.expected_version,
                )
                .values(**values)
            ).rowcount
        if updated != 1:
            raise StaleDirectedVersionError("the expected assignment version is stale")
        after = {
            "assignment_id": assignment_id,
            "entity_id": current.entity_id,
            "assignment_type": current.assignment_type.value,
            "scope_entity_id": current.scope_entity_id,
            "role": after_role,
            "discipline": after_discipline,
            "responsibility_class": after_responsibility,
            "effective_from": _isoformat(after_from),
            "effective_to": _isoformat(after_to),
            "state": after_state_name,
            "version": current.version + 1,
        }
        self._link_evidence(request, assignment_id=assignment_id, replace=True)
        return self._append_mutation(
            request,
            capability=_ASSIGNMENT_CAPABILITIES[request.operation],
            family=MutationRecordFamily.ASSIGNMENT,
            record_id=assignment_id,
            prior_version=current.version,
            new_version=current.version + 1,
            before_state=_assignment_state(current),
            after_state=after,
            state=after_state_name,
        )

    def _mutate_relationship(
        self, request: RelationshipWriteRequest, *, ending: bool
    ) -> DirectedReceipt:
        """Revise or end one directed edge, on `_mutate_assignment`'s guard."""
        relationship_id = request.relationship_id
        if relationship_id is None:
            raise DirectedWriteError("a state-dependent edge write names its edge")
        current = self.relationship(request.principal_id, relationship_id)
        if current is None:
            raise UnknownScopeError("an edge write names a row outside this scope")
        cleared = frozenset(request.cleared)
        if ending:
            values: dict[str, Any] = {
                "state": RelationshipState.ENDED.value,
                "ended_at": request.server_received_at,
                "effective_to": request.effective_to,
            }
            after_from = current.effective_from
            after_to = request.effective_to
            after_state_name = RelationshipState.ENDED.value
        else:
            after_from = _resolved(
                request.effective_from, current.effective_from, "effective_from" in cleared
            )
            after_to = _resolved(
                request.effective_to, current.effective_to, "effective_to" in cleared
            )
            if after_from is not None and after_to is not None and after_to < after_from:
                raise DirectedWriteError("an entity relationship cannot end before it begins")
            values = {"effective_from": after_from, "effective_to": after_to}
            after_state_name = current.state.value
        values["version"] = current.version + 1
        values["updated_at"] = request.server_received_at
        updated = self._connection.execute(
            update(entity_relationships)
            .where(
                _mine(entity_relationships, request.principal_id),
                entity_relationships.c.relationship_id == relationship_id,
                entity_relationships.c.version == request.expected_version,
            )
            .values(**values)
        ).rowcount
        if updated != 1:
            raise StaleDirectedVersionError("the expected entity relationship version is stale")
        after = {
            "relationship_id": relationship_id,
            "from_entity_id": current.from_entity_id,
            "relationship_type": current.relationship_type.value,
            "to_entity_id": current.to_entity_id,
            "scope_entity_id": current.scope_entity_id,
            "effective_from": _isoformat(after_from),
            "effective_to": _isoformat(after_to),
            "state": after_state_name,
            "version": current.version + 1,
        }
        self._link_evidence(request, relationship_id=relationship_id, replace=True)
        return self._append_mutation(
            request,
            capability=_RELATIONSHIP_CAPABILITIES[request.operation],
            family=MutationRecordFamily.RELATIONSHIP,
            record_id=relationship_id,
            prior_version=current.version,
            new_version=current.version + 1,
            before_state=_relationship_state(current),
            after_state=after,
            state=after_state_name,
        )

    # --- the shared guards and the ledger ------------------------------------

    def _require_writable_entity(
        self, principal_id: str, entity_id: str, expected_version: int | None
    ) -> None:
        """The entity is this Principal's, is not merged away, and is at its version.

        Three refusals with three meanings, and they are deliberately not
        collapsed. A foreign or absent entity is `UnknownScopeError`, which the
        application renders as `not_found` -- identical to the answer for an
        entity that does not exist, so this cannot be used to learn what another
        Principal holds. A merged-away entity is `MergedEndpointError`: the row
        is the caller's and is real, and following its redirect would rebind the
        write to a different identity than the one the user chose. A version
        mismatch is `StaleDirectedVersionError`, because the caller read
        something and the world moved.
        """
        validate_identifier(entity_id, IdKind.ENTITY)
        row = self._connection.execute(
            select(
                entities.c.entity_id,
                entities.c.status,
                entities.c.version,
            ).where(_mine(entities, principal_id), entities.c.entity_id == entity_id)
        ).one_or_none()
        if row is None:
            raise UnknownScopeError("a directed write names an entity outside this scope")
        if str(row.status) == EntityStatus.MERGED_REDIRECT.value:
            raise MergedEndpointError("a directed write names an entity that was merged away")
        if expected_version is not None and int(row.version) != expected_version:
            raise StaleDirectedVersionError("the expected entity version is stale")

    def _refuse_duplicate_assignment(
        self,
        request: AssignmentWriteRequest,
        entity_id: str,
        assignment_type: AssignmentType,
    ) -> None:
        """The active semantic key, read before the insert so the refusal is classified.

        The folding is `descriptor_key`, which restates
        `COALESCE(lower(trim(x)), '')` in Python. That second copy is checked
        against the first rather than trusted: the database tier proves the two
        agree on NULL, `''`, `'  '`, `'Lead'` and `' LEAD '`, because a folding
        rule stated twice and compared once is one rule and stated twice and
        never compared is two.
        """
        rows = self._connection.execute(
            select(
                entity_assignments.c.role,
                entity_assignments.c.discipline,
                entity_assignments.c.responsibility_class,
            ).where(
                _mine(entity_assignments, request.principal_id),
                entity_assignments.c.entity_id == entity_id,
                entity_assignments.c.assignment_type == assignment_type.value,
                entity_assignments.c.scope_entity_id.is_(request.scope_entity_id)
                if request.scope_entity_id is None
                else entity_assignments.c.scope_entity_id == request.scope_entity_id,
                entity_assignments.c.state == AssignmentState.ACTIVE.value,
            )
        ).all()
        wanted = (
            descriptor_key(request.role),
            descriptor_key(request.discipline),
            descriptor_key(request.responsibility_class),
        )
        for row in rows:
            held = (
                descriptor_key(_text_or_none(row.role)),
                descriptor_key(_text_or_none(row.discipline)),
                descriptor_key(_text_or_none(row.responsibility_class)),
            )
            if held == wanted:
                raise DuplicateDirectedFactError("an identical active assignment is recorded")

    def _refuse_duplicate_relationship(
        self,
        request: RelationshipWriteRequest,
        from_entity_id: str,
        relationship_type: EntityRelationshipType,
        to_entity_id: str,
    ) -> None:
        """The active `(from, type, to, scope)` key, read before the insert.

        The opposite direction is a different key and is not read here at all,
        which is what makes an inverse edge admissible rather than a duplicate.
        """
        held = self._connection.execute(
            select(entity_relationships.c.relationship_id).where(
                _mine(entity_relationships, request.principal_id),
                entity_relationships.c.from_entity_id == from_entity_id,
                entity_relationships.c.relationship_type == relationship_type.value,
                entity_relationships.c.to_entity_id == to_entity_id,
                entity_relationships.c.scope_entity_id.is_(request.scope_entity_id)
                if request.scope_entity_id is None
                else entity_relationships.c.scope_entity_id == request.scope_entity_id,
                entity_relationships.c.state == RelationshipState.ACTIVE.value,
            )
        ).first()
        if held is not None:
            raise DuplicateDirectedFactError("an identical active entity relationship is recorded")

    def _link_evidence(
        self,
        request: AssignmentWriteRequest | RelationshipWriteRequest,
        *,
        assignment_id: str | None = None,
        relationship_id: str | None = None,
        replace: bool = False,
    ) -> None:
        """Bind the cited observations to the fact this write recorded.

        `replace` on a revise, because `evidence_refs` replaces the cited set
        rather than adding to it: a citation a caller has since learned is wrong
        has to be withdrawable, and an additive field gives no way to withdraw
        one. A revise that cites nothing therefore clears the links, which is
        what an empty stated tuple means.

        The observation is verified against the acting Principal first. The
        schema's composite foreign key would refuse a foreign one anyway, but it
        would refuse it as an `IntegrityError` naming a constraint, and a caller
        that can tell "no such observation" from "that observation is not yours"
        can enumerate what another Principal holds.
        """
        if replace:
            self._connection.execute(
                entity_fact_evidence_links.delete().where(
                    _mine(entity_fact_evidence_links, request.principal_id),
                    entity_fact_evidence_links.c.assignment_id.is_(assignment_id)
                    if assignment_id is None
                    else entity_fact_evidence_links.c.assignment_id == assignment_id,
                    entity_fact_evidence_links.c.relationship_id.is_(relationship_id)
                    if relationship_id is None
                    else entity_fact_evidence_links.c.relationship_id == relationship_id,
                )
            )
        for reference in request.evidence_refs:
            validate_identifier(reference, IdKind.ENTITY_OBSERVATION)
            held = self._connection.execute(
                select(entity_observations.c.observation_id).where(
                    _mine(entity_observations, request.principal_id),
                    entity_observations.c.observation_id == reference,
                )
            ).first()
            if held is None:
                raise UnknownScopeError("a directed write cites evidence outside this scope")
            self._connection.execute(
                insert(entity_fact_evidence_links).values(
                    _bound(
                        entity_fact_evidence_links,
                        request.principal_id,
                        link_id=issue_identifier(IdKind.ENTITY_FACT_EVIDENCE_LINK),
                        assignment_id=assignment_id,
                        relationship_id=relationship_id,
                        entity_observation_id=reference,
                        role=EvidenceRole.DIRECT.value,
                        authority=MutationAuthority.USER_CONFIRMED_ASSERTION.value,
                    )
                )
            )

    def _append_mutation(
        self,
        request: AssignmentWriteRequest | RelationshipWriteRequest,
        *,
        capability: str,
        family: MutationRecordFamily,
        record_id: str,
        prior_version: int | None,
        new_version: int,
        before_state: dict[str, Any] | None,
        after_state: dict[str, Any],
        state: str,
    ) -> DirectedReceipt:
        """Append the ledger row that *is* this plane's receipt, and return it.

        `authority` is `user_confirmed_assertion` and `actor_class` is `user`,
        both constants: this is the capability path, and the only thing that
        reaches it is a Principal that authenticated and asked. A model-derived
        change goes through `entity_proposals` and arrives, if a reviewer accepts
        it, as `review_accepted` from a different writer.

        `receipt_id` is left null. The ledger row is the receipt on this plane --
        it carries the digest, the key, the before and after state and the audit
        identifier -- and that column exists for a separate receipt store this
        package does not build. Writing the event's own identifier into it would
        be a self-reference dressed as a reference.

        The unique on `(principal_id, capability, idempotency_key)` is what makes
        the whole write idempotent, which is why this insert is last: two
        concurrent writers that both passed the replay pre-read both reach here,
        and exactly one of them commits.
        """
        event_id = issue_identifier(IdKind.ENTITY_MUTATION_EVENT)
        # `null()` rather than `None` for the absent prior state, and this is not
        # style. A Python `None` bound to a `JSONB` column is the JSON value
        # `null`, not SQL `NULL`, so `a_mutation_before_state_is_an_object`
        # refuses it: `jsonb_typeof('null')` is `'null'` and not `'object'`. A
        # create genuinely has no prior state, and the column has to say so in
        # the language the CHECK reads.
        with _duplicate_translated(_MUTATION_KEY_UNIQUE):
            self._connection.execute(
                insert(entity_mutation_events).values(
                    _bound(
                        entity_mutation_events,
                        request.principal_id,
                        event_id=event_id,
                        capability=capability,
                        record_family=family.value,
                        record_id=record_id,
                        prior_version=prior_version,
                        new_version=new_version,
                        authority=MutationAuthority.USER_CONFIRMED_ASSERTION.value,
                        before_state=null() if before_state is None else before_state,
                        after_state=after_state,
                        reason=request.reason,
                        idempotency_key=request.idempotency_key,
                        request_digest=request.payload_digest,
                        correlation_id=request.correlation_id,
                        audit_id=request.audit_id,
                        receipt_id=None,
                        actor_class=ActorClass.USER.value,
                        recorded_at=request.server_received_at,
                    )
                )
            )
        return DirectedReceipt(
            mutation_event_id=event_id,
            record_id=record_id,
            record_family=family,
            prior_version=prior_version,
            version=new_version,
            state=state,
            audit_id=request.audit_id,
            idempotency_key=request.idempotency_key,
            superseded_id=None,
            evidence_refs=request.evidence_refs,
            issued_at=request.server_received_at,
            replayed=False,
        )

    def record_observation(self, principal_id: str, observation: EntityObservation) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if observation.principal_id != principal_id:
            raise ValueError("an observation belongs to the acting Principal")
        # This was the one write on the plane that constrained no form. It no
        # longer feeds anything the queue publishes: `f3a8c1d7e592` moved the
        # disclosure to `mention_display_name`, and this column is now internal
        # to matching. The guard stays because a value the resolver's equality
        # predicate cannot match still removes its row from the candidate set,
        # which is the `RI-PR135-MAJOR-002` argument and has nothing to do with
        # disclosure.
        _require_normalized_name(observation.normalized_value)
        if observation.entity_id is not None:
            self._require_own_entity(principal_id, observation.entity_id)
        existing = self._connection.execute(
            select(entity_observations).where(
                _mine(entity_observations, principal_id),
                entity_observations.c.observation_id == observation.observation_id,
            )
        ).one_or_none()
        if existing is not None:
            if _row_to_observation(existing) != observation:
                raise ValueError("an observation identifier cannot be rebound to different values")
            return
        self._connection.execute(
            insert(entity_observations).values(
                _bound(
                    entity_observations,
                    principal_id,
                    observation_id=observation.observation_id,
                    kind=observation.kind.value,
                    observed_value=observation.observed_value,
                    normalized_value=observation.normalized_value,
                    mention_display_name=observation.mention_display_name,
                    source_id=observation.source_id,
                    source_object_id=observation.source_object_id,
                    source_version_id=observation.source_version_id,
                    observed_at=observation.observed_at,
                    recorded_at=observation.recorded_at,
                    entity_id=observation.entity_id,
                    authority=observation.authority.value,
                    state=observation.state.value,
                    state_reason=observation.state_reason,
                    superseded_by_observation_id=observation.superseded_by_observation_id,
                    resolution_version=observation.resolution_version,
                )
            )
        )

    def observations(
        self,
        principal_id: str,
        entity_id: str | None = None,
        *,
        unresolved_only: bool = False,
        limit: int | None = None,
        after_observation_id: str | None = None,
    ) -> list[EntityObservation]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if entity_id is not None:
            validate_identifier(entity_id, IdKind.ENTITY)
        _require_row_limit(limit)
        if after_observation_id is not None:
            validate_identifier(after_observation_id, IdKind.ENTITY_OBSERVATION)
            # Refused on the same terms the other two paged reads refuse one.
            # The queue is the surface where this matters most: an empty page
            # reported as complete reads as "nothing left to resolve", which is
            # the opposite of what an unreadable cursor establishes.
            reachable = self._connection.execute(
                select(entity_observations.c.observation_id).where(
                    _mine(entity_observations, principal_id),
                    entity_observations.c.observation_id == after_observation_id,
                )
            ).first()
            if reachable is None:
                raise UnknownScopeError("an observation cursor names an observation in this scope")
        statement = (
            select(entity_observations)
            .where(
                _mine(entity_observations, principal_id),
                _optional(entity_observations.c.entity_id == entity_id if entity_id else None),
                _optional(entity_observations.c.entity_id.is_(None) if unresolved_only else None),
                # Keyset on the column the order is taken on, which is the
                # primary key — so the cursor is unique, nothing shifts between
                # pages, and a caller walking the queue sees each mention once.
                _optional(
                    entity_observations.c.observation_id > after_observation_id
                    if after_observation_id is not None
                    else None
                ),
            )
            .order_by(entity_observations.c.observation_id)
        )
        # `LIMIT` on the statement, not a slice of the result: the point of the
        # cap is that the rows never leave the server, and truncating after the
        # fact would have already paid for all of them.
        rows = self._connection.execute(_limited(statement, limit)).all()
        return [_row_to_observation(row) for row in rows]

    def observation(self, principal_id: str, observation_id: str) -> EntityObservation | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(observation_id, IdKind.ENTITY_OBSERVATION)
        row = self._connection.execute(
            select(entity_observations).where(
                _mine(entity_observations, principal_id),
                entity_observations.c.observation_id == observation_id,
            )
        ).one_or_none()
        return None if row is None else _row_to_observation(row)

    def link_observation(self, principal_id: str, observation_id: str, entity_id: str) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(observation_id, IdKind.ENTITY_OBSERVATION)
        self._require_own_entity(principal_id, entity_id)
        result = self._connection.execute(
            update(entity_observations)
            .where(
                _mine(entity_observations, principal_id),
                entity_observations.c.observation_id == observation_id,
            )
            .values(entity_id=entity_id)
        )
        if result.rowcount == 0:
            raise UnknownScopeError("an observation link names an observation outside this scope")

    # --- WP-RI-A-04: the three ledgers, written for the first time -----------

    def record_mutation_event(self, principal_id: str, event: EntityMutationEvent) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if event.principal_id != principal_id:
            raise ValueError("a mutation event belongs to the acting Principal")
        held = self.mutation_event(
            principal_id,
            capability=event.capability,
            idempotency_key=event.idempotency_key,
        )
        if held is not None:
            # A key already in use under this capability. Same request digest is
            # the caller retrying and the row already answers it; a different
            # one is a second request wearing the first one's key, which is the
            # single case that has to be refused rather than absorbed.
            if held.request_digest != event.request_digest:
                raise EntityMutationConflictError(
                    "an entity mutation key is held for a different request"
                )
            return
        self._connection.execute(
            insert(entity_mutation_events).values(
                _bound(
                    entity_mutation_events,
                    principal_id,
                    event_id=event.event_id,
                    capability=event.capability,
                    record_family=event.record_family.value,
                    record_id=event.record_id,
                    prior_version=event.prior_version,
                    new_version=event.new_version,
                    authority=event.authority.value,
                    # `null()` and not `None`. A Python `None` bound to a
                    # `JSONB` column is stored as the JSON value `null`, not as
                    # SQL NULL -- so `a_mutation_before_state_is_an_object`,
                    # which reads `IS NULL OR jsonb_typeof(...) = 'object'`,
                    # refuses every row that carries no photograph. Measured
                    # against a live server; the fake cannot see the difference,
                    # which is exactly why this is written out here.
                    before_state=(
                        null() if event.before_state is None else dict(event.before_state)
                    ),
                    after_state=(null() if event.after_state is None else dict(event.after_state)),
                    reason=event.reason,
                    idempotency_key=event.idempotency_key,
                    request_digest=event.request_digest,
                    correlation_id=event.correlation_id,
                    audit_id=event.audit_id,
                    receipt_id=event.receipt_id,
                    actor_class=event.actor_class.value,
                    recorded_at=event.recorded_at,
                )
            )
        )

    def mutation_event(
        self, principal_id: str, *, capability: str, idempotency_key: str
    ) -> EntityMutationEvent | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        row = self._connection.execute(
            select(entity_mutation_events).where(
                _mine(entity_mutation_events, principal_id),
                entity_mutation_events.c.capability == capability,
                entity_mutation_events.c.idempotency_key == idempotency_key,
            )
        ).one_or_none()
        return None if row is None else _row_to_mutation_event(row)

    def record_resolution_decision(
        self, principal_id: str, decision: EntityResolutionDecision
    ) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if decision.principal_id != principal_id:
            raise ValueError("a resolution decision belongs to the acting Principal")
        if decision.entity_id is not None:
            self._require_own_entity(principal_id, decision.entity_id)
        self._connection.execute(
            insert(entity_resolution_decisions).values(
                _bound(
                    entity_resolution_decisions,
                    principal_id,
                    decision_id=decision.decision_id,
                    observation_id=decision.observation_id,
                    sequence=decision.sequence,
                    expected_resolution_version=decision.expected_resolution_version,
                    disposition=decision.disposition.value,
                    entity_id=decision.entity_id,
                    reason=decision.reason,
                    evidence_link_ids=list(decision.evidence_link_ids),
                    decided_by=decision.decided_by,
                    actor_class=decision.actor_class.value,
                    review_case_id=decision.review_case_id,
                    correlation_id=decision.correlation_id,
                    audit_id=decision.audit_id,
                    receipt_id=decision.receipt_id,
                    decided_at=decision.decided_at,
                )
            )
        )

    def resolution_decisions(
        self,
        principal_id: str,
        observation_id: str | None = None,
        *,
        limit: int | None = None,
    ) -> list[EntityResolutionDecision]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if observation_id is not None:
            validate_identifier(observation_id, IdKind.ENTITY_OBSERVATION)
        _require_row_limit(limit)
        statement = (
            select(entity_resolution_decisions)
            .where(
                _mine(entity_resolution_decisions, principal_id),
                _optional(
                    entity_resolution_decisions.c.observation_id == observation_id
                    if observation_id is not None
                    else None
                ),
            )
            .order_by(
                entity_resolution_decisions.c.observation_id,
                entity_resolution_decisions.c.sequence,
            )
        )
        rows = self._connection.execute(_limited(statement, limit)).all()
        return [_row_to_resolution_decision(row) for row in rows]

    def decide_observation(
        self,
        principal_id: str,
        observation_id: str,
        *,
        expected_resolution_version: int,
        entity_id: str | None = None,
        state: ObservationState | None = None,
        state_reason: str | None = None,
    ) -> bool:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(observation_id, IdKind.ENTITY_OBSERVATION)
        if expected_resolution_version < 0:
            raise ValueError("an expected resolution version is not negative")
        if entity_id is not None:
            self._require_own_entity(principal_id, entity_id)
        values: dict[str, object] = {
            "resolution_version": expected_resolution_version + 1,
        }
        if entity_id is not None:
            values["entity_id"] = entity_id
        if state is not None:
            values["state"] = state.value
            values["state_reason"] = state_reason
        # One guarded UPDATE, and its rowcount is the whole decision. The
        # version predicate is in the `WHERE`, so a stale expectation matches no
        # row and writes nothing -- not the version, not the link, not the
        # state. The caller checks this answer before it writes a ledger row or
        # an evidence link, which is what makes "a stale write writes nothing"
        # true of the transaction and not only of this statement.
        updated = self._connection.execute(
            update(entity_observations)
            .where(
                _mine(entity_observations, principal_id),
                entity_observations.c.observation_id == observation_id,
                entity_observations.c.resolution_version == expected_resolution_version,
            )
            .values(**values)
        ).rowcount
        return updated == 1

    def record_fact_evidence_link(self, principal_id: str, link: EntityFactEvidenceLink) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if link.principal_id != principal_id:
            raise ValueError("an evidence link belongs to the acting Principal")
        # Same-Principal is structural for the fact half -- every target column
        # carries a composite `(id, principal_id)` reference -- and is proved
        # here for the entity, because a foreign key that refuses the write is a
        # worse answer than a refusal naming the scope. The evidence half cannot
        # be proved either way for `capture_spans` or `knowledge_id`, which
        # carry no Principal partition to compose with; that residual is
        # `entity_fact_evidence_links`' own and is stated on the table.
        if link.entity_id is not None:
            self._require_own_entity(principal_id, link.entity_id)
        self._connection.execute(
            insert(entity_fact_evidence_links).values(
                _bound(
                    entity_fact_evidence_links,
                    principal_id,
                    link_id=link.link_id,
                    entity_id=link.entity_id,
                    identifier_id=link.identifier_id,
                    alias_id=link.alias_id,
                    assignment_id=link.assignment_id,
                    relationship_id=link.relationship_id,
                    entity_observation_id=link.entity_observation_id,
                    capture_span_id=link.capture_span_id,
                    knowledge_id=link.knowledge_id,
                    role=link.role.value,
                    authority=link.authority.value,
                    created_at=link.created_at,
                )
            )
        )

    def fact_evidence_links(
        self,
        principal_id: str,
        *,
        entity_observation_id: str | None = None,
        role: EvidenceRole | None = None,
        limit: int | None = None,
    ) -> list[EntityFactEvidenceLink]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if entity_observation_id is not None:
            validate_identifier(entity_observation_id, IdKind.ENTITY_OBSERVATION)
        _require_row_limit(limit)
        statement = (
            select(entity_fact_evidence_links)
            .where(
                _mine(entity_fact_evidence_links, principal_id),
                _optional(
                    entity_fact_evidence_links.c.entity_observation_id == entity_observation_id
                    if entity_observation_id is not None
                    else None
                ),
                _optional(
                    entity_fact_evidence_links.c.role == role.value if role is not None else None
                ),
            )
            .order_by(entity_fact_evidence_links.c.link_id)
        )
        rows = self._connection.execute(_limited(statement, limit)).all()
        return [_row_to_fact_evidence_link(row) for row in rows]

    def record_proposal(self, principal_id: str, proposal: EntityProposal) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if proposal.principal_id != principal_id:
            raise ValueError("a proposal belongs to the acting Principal")
        existing = self.proposal(principal_id, proposal.proposal_id)
        if existing is not None:
            if existing != proposal:
                raise ValueError("a proposal identifier cannot be rebound to different values")
            return
        self._connection.execute(
            insert(entity_proposals).values(
                _bound(
                    entity_proposals,
                    principal_id,
                    proposal_id=proposal.proposal_id,
                    kind=proposal.kind.value,
                    state=proposal.state.value,
                    payload=dict(proposal.payload),
                    observation_ids=list(proposal.observation_ids),
                    proposed_at=proposal.proposed_at,
                    proposed_by=proposal.proposed_by,
                    decided_by=proposal.decided_by,
                    decided_at=proposal.decided_at,
                    decision_reason=proposal.decision_reason,
                )
            )
        )

    def proposal(self, principal_id: str, proposal_id: str) -> EntityProposal | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        validate_identifier(proposal_id, IdKind.ENTITY_PROPOSAL)
        row = self._connection.execute(
            select(entity_proposals).where(
                _mine(entity_proposals, principal_id),
                entity_proposals.c.proposal_id == proposal_id,
            )
        ).one_or_none()
        return None if row is None else _row_to_proposal(row)

    def proposals(
        self, principal_id: str, state: EntityProposalState | None = None
    ) -> list[EntityProposal]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        rows = self._connection.execute(
            select(entity_proposals)
            .where(
                _mine(entity_proposals, principal_id),
                _optional(entity_proposals.c.state == state.value if state else None),
            )
            .order_by(entity_proposals.c.proposal_id)
        ).all()
        return [_row_to_proposal(row) for row in rows]

    def decide_proposal(self, principal_id: str, proposal: EntityProposal) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if proposal.principal_id != principal_id:
            raise ValueError("a proposal belongs to the acting Principal")
        # `state = 'proposed'` is part of the predicate, not a check made before
        # it. A decision is a one-time act: without this, deciding an already
        # decided proposal overwrites `decided_by`, `decided_at` and the reason,
        # so the record of who made the call and why is replaced by whoever
        # called last -- and a rejected merge could be re-accepted with no trace
        # that it had ever been refused. Two concurrent deciders now settle at
        # the database rather than by arrival order.
        result = self._connection.execute(
            update(entity_proposals)
            .where(
                _mine(entity_proposals, principal_id),
                entity_proposals.c.proposal_id == proposal.proposal_id,
                entity_proposals.c.state == EntityProposalState.PROPOSED.value,
            )
            .values(
                state=proposal.state.value,
                decided_by=proposal.decided_by,
                decided_at=proposal.decided_at,
                decision_reason=proposal.decision_reason,
            )
        )
        if result.rowcount == 0:
            # One message for both, deliberately: distinguishing "not yours"
            # from "already decided" would tell a caller that a proposal they
            # cannot see exists.
            raise UnknownScopeError("a decision names an open proposal in this scope")

    def record_merge(self, principal_id: str, record: EntityMergeRecord) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if record.principal_id != principal_id:
            raise ValueError("a merge record belongs to the acting Principal")
        self._require_own_entities(principal_id, record.retained_entity_id, record.merged_entity_id)
        # The proposal is partitioned too. `proposal_id` is the record's link
        # back to the decision that authorised the merge, and a row citing a
        # proposal in another Principal's partition would present that decision
        # as this Principal's own -- lineage that reads as authority and is not.
        cited = self._connection.execute(
            select(entity_proposals.c.proposal_id).where(
                _mine(entity_proposals, principal_id),
                entity_proposals.c.proposal_id == record.proposal_id,
            )
        ).first()
        if cited is None:
            raise UnknownScopeError("a merge record cites a proposal in this scope")
        self._connection.execute(
            insert(entity_merge_records).values(
                _bound(
                    entity_merge_records,
                    principal_id,
                    merge_id=record.merge_id,
                    retained_entity_id=record.retained_entity_id,
                    merged_entity_id=record.merged_entity_id,
                    proposal_id=record.proposal_id,
                    decided_by=record.decided_by,
                    reason=record.reason,
                    decided_at=record.decided_at,
                )
            )
        )

    def merges(self, principal_id: str, entity_id: str | None = None) -> list[EntityMergeRecord]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if entity_id is not None:
            validate_identifier(entity_id, IdKind.ENTITY)
        rows = self._connection.execute(
            select(entity_merge_records)
            .where(
                _mine(entity_merge_records, principal_id),
                _optional(
                    or_(
                        entity_merge_records.c.retained_entity_id == entity_id,
                        entity_merge_records.c.merged_entity_id == entity_id,
                    )
                    if entity_id
                    else None
                ),
            )
            .order_by(entity_merge_records.c.merge_id)
        ).all()
        return [_row_to_merge(row) for row in rows]

    def redirect_entity(
        self, principal_id: str, merged_entity_id: str, retained_entity_id: str
    ) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        self._require_own_entities(principal_id, merged_entity_id, retained_entity_id)
        if merged_entity_id == retained_entity_id:
            raise ValueError("an entity cannot be merged into itself")
        # **Both rows are locked before either guard reads.** The two checks
        # below read one row and then update a *different* one, so under READ
        # COMMITTED two concurrent redirects never contend and both pass: run
        # `redirect(BOB, ALICE)` beside `redirect(ALICE, CARLA)` and each sees a
        # current survivor and no inbound pointer, leaving the chain
        # `BOB -> ALICE -> CARLA` that the guard exists to prevent. The mirror
        # pair leaves a cycle, which makes the runbook's "follow
        # `superseded_by_entity_id`" non-terminating. Nothing in the schema
        # catches either state and there is no repair path.
        #
        # Locked in identifier order so two callers naming the same pair in
        # opposite directions queue rather than deadlock.
        self._connection.execute(
            select(entities.c.entity_id)
            .where(
                _mine(entities, principal_id),
                entities.c.entity_id.in_(sorted((merged_entity_id, retained_entity_id))),
            )
            .order_by(entities.c.entity_id)
            .with_for_update()
        ).all()
        # The survivor must be an entity a reader can land on. Without this a
        # second merge in the other direction produced a redirect *cycle*, and a
        # merge onto an already-merged entity produced a chain -- both of which
        # make `superseded_by_entity_id` a pointer that never arrives, against
        # the declaration's own claim that "a redirect always resolves" and the
        # runbook's instruction to follow it.
        survivor = self.get(principal_id, retained_entity_id)
        if survivor is None or survivor.status is EntityStatus.MERGED_REDIRECT:
            raise ValueError("an entity is merged into one that is still current")
        # And the entity being merged away must not already be merged. This is
        # the fourth arrangement of the same guard, and the third one found by a
        # reviewer rather than by this code: the survivor check inspects only
        # `retained`, and the inbound check looks for rows pointing *at*
        # `merged` -- neither asks whether `merged` already points somewhere.
        # So `redirect(M, S1)` then `redirect(M, S2)` was accepted and silently
        # rewrote M's target, leaving `entity_merge_records` naming S1 while the
        # entity plane named S2.
        #
        # The invariant was previously held by `entity_merge_records`'s unique
        # constraint on `merged_entity_id` -- a table this method does not
        # touch, enforcing a rule about this method, and only for callers that
        # write a merge record afterwards. A repair script or a backfill that
        # redirects without recording would not have met it.
        merged = self.get(principal_id, merged_entity_id)
        if merged is not None and merged.status is EntityStatus.MERGED_REDIRECT:
            raise ValueError("an entity that is already merged away is not merged again")
        # And nothing may already point *at* the entity being merged away. The
        # survivor check above closes cycles and closes chains built in one
        # order; it does not close them built in the other. `redirect(BOB,
        # ALICE)` then `redirect(ALICE, CARLA)` passed both guards and left
        # `BOB -> ALICE -> CARLA`, because when ALICE was merged she was still
        # current and CARLA still is. A reader following one hop from BOB lands
        # on a `merged_redirect`, which is the pointer that never arrives that
        # this guard exists to prevent -- and `ops/runbooks/relationship-
        # intelligence.md` tells an operator to follow exactly that hop.
        inbound = self._connection.execute(
            select(entities.c.entity_id).where(
                _mine(entities, principal_id),
                entities.c.superseded_by_entity_id == merged_entity_id,
            )
        ).first()
        if inbound is not None:
            raise ValueError("an entity that others redirect to is not merged away")
        result = self._connection.execute(
            update(entities)
            .where(_mine(entities, principal_id), entities.c.entity_id == merged_entity_id)
            .values(
                status=EntityStatus.MERGED_REDIRECT.value,
                superseded_by_entity_id=retained_entity_id,
            )
        )
        if result.rowcount == 0:
            raise UnknownScopeError("a redirect names an entity outside this scope")


#: The three directions `relationships` admits, as predicates. A mapping rather
#: than an if-chain so an unknown direction is a refusal rather than a silent
#: fall-through to "any" -- a caller who asked for outgoing edges and got every
#: edge would read a false answer as a true one.
_DIRECTIONS: dict[str, Any] = {
    "outgoing": lambda entity_id: entity_relationships.c.from_entity_id == entity_id,
    "incoming": lambda entity_id: entity_relationships.c.to_entity_id == entity_id,
    "any": lambda entity_id: or_(
        entity_relationships.c.from_entity_id == entity_id,
        entity_relationships.c.to_entity_id == entity_id,
    ),
}


#: The three unique constraints the directed write path may collide with, and
#: what each collision *means*. Named rather than matched loosely, because
#: `IntegrityError` is one exception class over every constraint on the table:
#: catching it without reading `constraint_name` would report a duplicate
#: assignment for a violated foreign key, which is a wrong answer rather than a
#: missing one.
_ASSIGNMENT_UNIQUE: Final = "an_active_assignment_is_recorded_once"
_RELATIONSHIP_UNIQUE: Final = "an_active_entity_relationship_is_recorded_once"
_MUTATION_KEY_UNIQUE: Final = "one_entity_mutation_per_key_and_capability"

#: Which capability name one ledger row records, by the operation that wrote it.
#: The ledger's `capability` column is what the idempotency unique is keyed on
#: together with the Principal and the key, so this mapping is what makes one key
#: reusable across `create` and `revise` -- which is the honest reading: they are
#: different acts on different state.
_ASSIGNMENT_CAPABILITIES: Final[dict[DirectedWriteOperation, str]] = {
    DirectedWriteOperation.CREATE: Capability.ENTITIES_ASSIGNMENTS_CREATE.value,
    DirectedWriteOperation.REVISE: Capability.ENTITIES_ASSIGNMENTS_REVISE.value,
    DirectedWriteOperation.END: Capability.ENTITIES_ASSIGNMENTS_END.value,
}
_RELATIONSHIP_CAPABILITIES: Final[dict[DirectedWriteOperation, str]] = {
    DirectedWriteOperation.CREATE: Capability.ENTITIES_RELATIONSHIPS_CREATE.value,
    DirectedWriteOperation.REVISE: Capability.ENTITIES_RELATIONSHIPS_REVISE.value,
    DirectedWriteOperation.END: Capability.ENTITIES_RELATIONSHIPS_END.value,
}


def _constraint_name(error: IntegrityError) -> str | None:
    """psycopg's stable constraint identity, without exposing its message."""
    diagnostic = getattr(error.orig, "diag", None)
    return getattr(diagnostic, "constraint_name", None)


@contextmanager
def _duplicate_translated(constraint: str) -> Iterator[None]:
    """Classify a violation of `constraint` and re-raise anything else untouched.

    **The index is the decision and this is the classification.** The pre-reads
    above cannot see a concurrent writer -- two sessions that both find no active
    duplicate both proceed, and only the index refuses the second -- so the
    refusal has to be catchable here or it leaves as a driver exception across a
    port whose vocabulary is `PortError` and `DirectedWriteError`.

    The transaction is aborted by the violation and is not repaired here.
    Nothing needs it to be: the caller raises out of `ApplicationService.invoke`,
    which rolls the work back, and the audit event recording the authorization
    was committed on a *separate connection* before the handler ran -- which is
    `persistence.audit`'s whole reason for taking its own connection.
    """
    failure: Exception | None = None
    try:
        yield
    except IntegrityError as error:
        if _constraint_name(error) != constraint:
            raise
        failure = (
            DirectedWriteError("this idempotency key is bound to a different request")
            if constraint == _MUTATION_KEY_UNIQUE
            else DuplicateDirectedFactError("an identical active record is recorded")
        )
    if failure is not None:
        # Raised outside the handler, so the driver's own message -- which
        # renders bound parameters -- is not left in `__context__` for a
        # traceback to print.
        raise failure


def _resolved[ValueT](
    stated: ValueT | None, current: ValueT | None, cleared: bool
) -> ValueT | None:
    """What a revise leaves in one field: stated, cleared, or carried forward.

    Absence means carry forward. That is the correction the Relationship Memory
    plane's `pinned` field records: writing the absent value unconditionally made
    an ordinary wording fix throw away a choice the caller never mentioned. A
    field is emptied only by being named in `cleared`, and the command already
    refused a request that both states a value and names it.
    """
    if cleared:
        return None
    return current if stated is None else stated


def _isoformat(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _assignment_state(assignment: Assignment) -> dict[str, Any]:
    """One assignment as the mutation ledger records it.

    Every column that carries meaning and none that carries only bookkeeping:
    `updated_at` is when the ledger row itself was written and is already on the
    ledger row, and repeating it inside the state document would let a reader
    diff two rows and find a difference that is not a change to the record.
    """
    return {
        "assignment_id": assignment.assignment_id,
        "entity_id": assignment.entity_id,
        "assignment_type": assignment.assignment_type.value,
        "scope_entity_id": assignment.scope_entity_id,
        "role": assignment.role,
        "discipline": assignment.discipline,
        "responsibility_class": assignment.responsibility_class,
        "effective_from": _isoformat(assignment.effective_from),
        "effective_to": _isoformat(assignment.effective_to),
        "state": assignment.state.value,
        "version": assignment.version,
    }


def _relationship_state(edge: EntityRelationship) -> dict[str, Any]:
    """One directed edge as the mutation ledger records it."""
    return {
        "relationship_id": edge.relationship_id,
        "from_entity_id": edge.from_entity_id,
        "relationship_type": edge.relationship_type.value,
        "to_entity_id": edge.to_entity_id,
        "scope_entity_id": edge.scope_entity_id,
        "effective_from": _isoformat(edge.effective_from),
        "effective_to": _isoformat(edge.effective_to),
        "state": edge.state.value,
        "version": edge.version,
    }


def _row_to_directed_receipt(row: Row[Any], *, replayed: bool) -> DirectedReceipt:
    """One ledger row as the receipt it is.

    The lifecycle state is read out of `after_state` rather than stored a second
    time on the row: it is already there, and a duplicated column is a column two
    writers can disagree about. `evidence_refs` is empty on a replay and says so
    -- the links are on `entity_fact_evidence_links` and are read from there, not
    reconstructed from a ledger row that never carried them.
    """
    after = row.after_state if isinstance(row.after_state, dict) else {}
    return DirectedReceipt(
        mutation_event_id=str(row.event_id),
        record_id=str(row.record_id),
        record_family=MutationRecordFamily(str(row.record_family)),
        prior_version=None if row.prior_version is None else int(row.prior_version),
        version=int(row.new_version),
        state=str(after.get("state", "")),
        audit_id=str(row.audit_id),
        idempotency_key=str(row.idempotency_key),
        superseded_id=None,
        evidence_refs=(),
        issued_at=row.recorded_at,
        replayed=replayed,
    )


def _text_or_none(value: object) -> str | None:
    """A nullable text column as `str | None`, without collapsing an empty one.

    `str(value) if value else None` would turn a stored empty string into
    `None`, which is a different fact.
    """
    return None if value is None else str(value)


def _row_to_summary(row: Row[Any]) -> EntitySummary:
    """One search row as a summary, refusing a name the resolver could not match.

    `EntitySummary` carries no `__post_init__` on purpose -- it is a list row,
    not a record -- so this is the only place the check can happen for the
    browse surface. Without it, `search` was the one read on this plane that
    served a malformed stored name without complaint, while `get` on the same
    row raised: the surface an operator browses would show the row as ordinary
    at exactly the moment its unmatchability was silently changing who
    `entities.resolve` named. Failing here makes the malformed row visible on
    the surface most likely to be looked at, in the same way and with the same
    message as every other read of it.
    """
    canonical_name = str(row.canonical_name)
    _require_normalized_name(canonical_name)
    return EntitySummary(
        entity_id=str(row.entity_id),
        entity_type=EntityType(str(row.entity_type)),
        canonical_name=canonical_name,
        display_name=str(row.display_name),
        status=EntityStatus(str(row.status)),
    )


def _row_to_entity(row: Row[Any]) -> Entity:
    return Entity(
        entity_id=str(row.entity_id),
        principal_id=str(row.principal_id),
        entity_type=EntityType(str(row.entity_type)),
        canonical_name=str(row.canonical_name),
        display_name=str(row.display_name),
        status=EntityStatus(str(row.status)),
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=int(row.version),
        superseded_by_entity_id=_text_or_none(row.superseded_by_entity_id),
        archived_from_status=(
            None
            if row.archived_from_status is None
            else EntityStatus(str(row.archived_from_status))
        ),
    )


def _row_to_external_identifier(row: Any) -> ExternalIdentifier:  # noqa: ANN401 - Row or _ChildRow
    """One stored identifier, from a `Row` or from `_ChildRow` over a joined one.

    `Any` rather than `Row`, and that is the honest annotation: the joined
    lookup labels its identifier columns and reads them back through the
    adapter, which is not a `Row` and does not pretend to be one.
    """
    return ExternalIdentifier(
        identifier_id=str(row.identifier_id),
        entity_id=str(row.entity_id),
        namespace=ExternalIdentifierNamespace(str(row.namespace)),
        normalized_value=str(row.normalized_value),
        display_value=str(row.display_value),
        principal_id=str(row.principal_id),
        verified=bool(row.verified),
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        state=IdentifierState(str(row.state)),
        version=int(row.version),
        updated_at=row.updated_at,
        retired_at=row.retired_at,
        superseded_by_identifier_id=_text_or_none(row.superseded_by_identifier_id),
    )


def _row_to_alias(row: Any) -> EntityAlias:  # noqa: ANN401 - a Row or a labelled view
    """One stored alias, from a `Row` or from `_ChildRow` over a joined one."""
    return EntityAlias(
        alias_id=str(row.alias_id),
        entity_id=str(row.entity_id),
        alias_type=AliasType(str(row.alias_type)),
        normalized_value=str(row.normalized_value),
        display_value=str(row.display_value),
        principal_id=str(row.principal_id),
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        state=AliasState(str(row.state)),
        version=int(row.version),
        updated_at=row.updated_at,
        retired_at=row.retired_at,
        superseded_by_alias_id=_text_or_none(row.superseded_by_alias_id),
    )


def _row_to_assignment(row: Row[Any]) -> Assignment:
    return Assignment(
        assignment_id=str(row.assignment_id),
        entity_id=str(row.entity_id),
        assignment_type=AssignmentType(str(row.assignment_type)),
        principal_id=str(row.principal_id),
        scope_entity_id=_text_or_none(row.scope_entity_id),
        role=_text_or_none(row.role),
        discipline=_text_or_none(row.discipline),
        responsibility_class=_text_or_none(row.responsibility_class),
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        state=AssignmentState(str(row.state)),
        version=int(row.version),
        updated_at=row.updated_at,
        ended_at=row.ended_at,
        superseded_by_assignment_id=_text_or_none(row.superseded_by_assignment_id),
    )


def _row_to_relationship(row: Row[Any]) -> EntityRelationship:
    return EntityRelationship(
        relationship_id=str(row.relationship_id),
        from_entity_id=str(row.from_entity_id),
        relationship_type=EntityRelationshipType(str(row.relationship_type)),
        to_entity_id=str(row.to_entity_id),
        principal_id=str(row.principal_id),
        scope_entity_id=_text_or_none(row.scope_entity_id),
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        state=RelationshipState(str(row.state)),
        version=int(row.version),
        updated_at=row.updated_at,
        ended_at=row.ended_at,
        superseded_by_relationship_id=_text_or_none(row.superseded_by_relationship_id),
    )


def _row_to_observation(row: Row[Any]) -> EntityObservation:
    # The read half of the guard on `record_observation`. `EntityObservation`
    # checks only that its normalized value is non-blank -- unlike `Entity`,
    # `EntityAlias` and `ExternalIdentifier`, whose own `__post_init__` refuse an
    # unnormalized value and so make this repository's claim true for their
    # mappers without a line here. Without this, the module docstring's "on
    # every read mapper" was false of this column: a row written around the
    # repository came back verbatim, angle brackets and all. That mattered for
    # disclosure until `f3a8c1d7e592`; it still matters for matching, which is
    # what the guard is actually about.
    _require_normalized_name(str(row.normalized_value))
    return EntityObservation(
        observation_id=str(row.observation_id),
        principal_id=str(row.principal_id),
        kind=ObservationKind(str(row.kind)),
        observed_value=str(row.observed_value),
        normalized_value=str(row.normalized_value),
        mention_display_name=_text_or_none(row.mention_display_name),
        source_id=str(row.source_id),
        source_object_id=str(row.source_object_id),
        source_version_id=str(row.source_version_id),
        observed_at=row.observed_at,
        recorded_at=row.recorded_at,
        entity_id=_text_or_none(row.entity_id),
        authority=ObservationAuthority(str(row.authority)),
        state=ObservationState(str(row.state)),
        state_reason=_text_or_none(row.state_reason),
        superseded_by_observation_id=_text_or_none(row.superseded_by_observation_id),
        resolution_version=int(row.resolution_version),
    )


def _row_to_mutation_event(row: Row[Any]) -> EntityMutationEvent:
    return EntityMutationEvent(
        event_id=str(row.event_id),
        principal_id=str(row.principal_id),
        capability=str(row.capability),
        record_family=MutationRecordFamily(str(row.record_family)),
        record_id=str(row.record_id),
        new_version=int(row.new_version),
        authority=MutationAuthority(str(row.authority)),
        actor_class=ActorClass(str(row.actor_class)),
        idempotency_key=str(row.idempotency_key),
        request_digest=str(row.request_digest),
        correlation_id=str(row.correlation_id),
        audit_id=str(row.audit_id),
        recorded_at=row.recorded_at,
        prior_version=None if row.prior_version is None else int(row.prior_version),
        before_state=row.before_state if isinstance(row.before_state, dict) else None,
        after_state=row.after_state if isinstance(row.after_state, dict) else None,
        reason=_text_or_none(row.reason),
        receipt_id=_text_or_none(row.receipt_id),
    )


def _row_to_resolution_decision(row: Row[Any]) -> EntityResolutionDecision:
    cited = row.evidence_link_ids if isinstance(row.evidence_link_ids, list) else []
    return EntityResolutionDecision(
        decision_id=str(row.decision_id),
        principal_id=str(row.principal_id),
        observation_id=str(row.observation_id),
        sequence=int(row.sequence),
        expected_resolution_version=int(row.expected_resolution_version),
        disposition=ResolutionDisposition(str(row.disposition)),
        decided_by=str(row.decided_by),
        actor_class=ActorClass(str(row.actor_class)),
        correlation_id=str(row.correlation_id),
        audit_id=str(row.audit_id),
        decided_at=row.decided_at,
        entity_id=_text_or_none(row.entity_id),
        reason=_text_or_none(row.reason),
        evidence_link_ids=tuple(str(item) for item in cited),
        review_case_id=_text_or_none(row.review_case_id),
        receipt_id=_text_or_none(row.receipt_id),
    )


def _row_to_fact_evidence_link(row: Row[Any]) -> EntityFactEvidenceLink:
    return EntityFactEvidenceLink(
        link_id=str(row.link_id),
        principal_id=str(row.principal_id),
        role=EvidenceRole(str(row.role)),
        authority=MutationAuthority(str(row.authority)),
        created_at=row.created_at,
        entity_id=_text_or_none(row.entity_id),
        identifier_id=_text_or_none(row.identifier_id),
        alias_id=_text_or_none(row.alias_id),
        assignment_id=_text_or_none(row.assignment_id),
        relationship_id=_text_or_none(row.relationship_id),
        entity_observation_id=_text_or_none(row.entity_observation_id),
        capture_span_id=_text_or_none(row.capture_span_id),
        knowledge_id=_text_or_none(row.knowledge_id),
    )


def _row_to_proposal(row: Row[Any]) -> EntityProposal:
    payload = row.payload if isinstance(row.payload, dict) else {}
    observation_ids = row.observation_ids if isinstance(row.observation_ids, list) else []
    return EntityProposal(
        proposal_id=str(row.proposal_id),
        principal_id=str(row.principal_id),
        kind=EntityProposalKind(str(row.kind)),
        state=EntityProposalState(str(row.state)),
        payload=tuple(sorted((str(k), str(v)) for k, v in payload.items())),
        observation_ids=tuple(str(item) for item in observation_ids),
        proposed_at=row.proposed_at,
        proposed_by=str(row.proposed_by),
        decided_by=_text_or_none(row.decided_by),
        decided_at=row.decided_at,
        decision_reason=_text_or_none(row.decision_reason),
    )


def _row_to_merge(row: Row[Any]) -> EntityMergeRecord:
    return EntityMergeRecord(
        merge_id=str(row.merge_id),
        principal_id=str(row.principal_id),
        retained_entity_id=str(row.retained_entity_id),
        merged_entity_id=str(row.merged_entity_id),
        proposal_id=str(row.proposal_id),
        decided_by=str(row.decided_by),
        reason=str(row.reason),
        decided_at=row.decided_at,
    )
