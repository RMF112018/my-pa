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

**Idempotency, stated honestly.** ``bind_identifier`` is idempotent against a
natural key -- ``(entity_id, namespace, normalized_value)`` is a real unique
constraint, so a repeat is a no-op whatever identifier the caller minted.
``create``, ``record_assignment`` and ``record_relationship`` are idempotent
against *their own identifier*: a repeat carrying the same values returns
quietly, and a repeat carrying different values under an identifier already
issued is refused rather than silently dropped. Neither of the latter two has a
natural key yet, so a retry that mints a fresh identifier writes a second row.
Closing that needs an idempotency key on the write path, and the write path
arrives with the work package that has something observed to write.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Row, Select, Table, insert, or_, select, true, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection
from sqlalchemy.sql.elements import ColumnElement

from my_pa.contracts.ports import EntitiesRepository, EntitySummary, UnknownScopeError
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.relationship.entity import (
    AliasType,
    Assignment,
    AssignmentType,
    Entity,
    EntityAlias,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
)
from my_pa.domain.relationship.governance import (
    EntityMergeRecord,
    EntityObservation,
    EntityProposal,
    EntityProposalKind,
    EntityProposalState,
    ObservationKind,
)
from my_pa.domain.relationship.normalization import (
    is_normalized_identifier,
    is_normalized_name,
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
    entity_merge_records,
    entity_observations,
    entity_proposals,
    entity_relationships,
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
)


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
            select(*_ENTITY_COLUMNS, entity_external_identifiers)
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
        return [(_row_to_entity(row), _row_to_external_identifier(row)) for row in rows]

    def entities_by_alias(
        self, principal_id: str, normalized_value: str
    ) -> list[tuple[Entity, EntityAlias]]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        rows = self._connection.execute(
            select(*_ENTITY_COLUMNS, entity_aliases)
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
        return [(_row_to_entity(row), _row_to_alias(row)) for row in rows]

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
                _optional(entity_assignments.c.status == "active" if active_only else None),
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
        self._connection.execute(
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
                )
            )
            .on_conflict_do_nothing(
                constraint="an_external_identifier_is_recorded_once_per_namespace"
            )
        )

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
                )
            )
            .on_conflict_do_nothing(constraint="an_alias_is_recorded_once_per_entity_and_type")
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
                    status=assignment.status,
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
                    state=rel.state,
                    version=rel.version,
                )
            )
        )

    # --- WP-RI-06: observation, proposal, and merge lineage ------------------

    def record_observation(self, principal_id: str, observation: EntityObservation) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if observation.principal_id != principal_id:
            raise ValueError("an observation belongs to the acting Principal")
        # This was the one write on the plane that constrained no form, and it
        # feeds the one field `entities.unresolved_mentions` discloses. The
        # guard is necessary and it is **not sufficient**: it establishes that
        # the value is normalized, not that it is a name — normalized raw text
        # passes it. What keeps an envelope out is the caller's contract on
        # `EntityRepository.record_observation`, which this cannot check.
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
    )


def _row_to_external_identifier(row: Row[Any]) -> ExternalIdentifier:
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
    )


def _row_to_alias(row: Row[Any]) -> EntityAlias:
    return EntityAlias(
        alias_id=str(row.alias_id),
        entity_id=str(row.entity_id),
        alias_type=AliasType(str(row.alias_type)),
        normalized_value=str(row.normalized_value),
        display_value=str(row.display_value),
        principal_id=str(row.principal_id),
        effective_from=row.effective_from,
        effective_to=row.effective_to,
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
        status=str(row.status),
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
        state=str(row.state),
        version=int(row.version),
    )


def _row_to_observation(row: Row[Any]) -> EntityObservation:
    # The read half of the guard on `record_observation`. `EntityObservation`
    # checks only that its normalized value is non-blank -- unlike `Entity`,
    # `EntityAlias` and `ExternalIdentifier`, whose own `__post_init__` refuse an
    # unnormalized value and so make this repository's claim true for their
    # mappers without a line here. Without this, the module docstring's "on
    # every read mapper" was false of the one field
    # `entities.unresolved_mentions` discloses: a row written around the
    # repository came back verbatim, angle brackets and all.
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
