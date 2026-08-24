"""Generalized entity model for relationship intelligence v0.3.

The Entity/ExternalIdentifier/Assignment/EntityRelationship model generalises
beyond the person-and-organization-only world of the WP-9 substrate.  An Entity
can be a Person, Organization, Program, Project, Work Package, Team-or-Group,
or Location.  ExternalIdentifier records an entity's identity in an external
namespace (email, Entra, vendor system, etc.).  Assignment records that an
entity is assigned to a scope entity under a typed role.  EntityRelationship
records a directed, typed relationship between two entities, optionally scoped
by a third.

**Every matched-against value is validated as already normalized.** An entity's
`canonical_name`, an alias's `normalized_value`, and an external identifier's
`normalized_value` are the columns resolution compares by equality, and until
these records refused an unnormalized one the whole matching policy in
`relationship.normalization` was a query-side convention no writer had to
honour. A single row stored in the wrong form did not merely make itself
unfindable: it removed itself from a candidate set and thereby promoted a
*neighbouring* entity from an ambiguous refusal to a confident wrong answer.

These types are *additive*: they do not modify or replace Person/Organization,
and they do not alter the existing relationship_people or relationship_organizations
tables.  A later work package unifies the old and new surfaces.

**What these records do not yet carry, and why.**  The specification requires
provenance on every observed and derived record (section 22.2) and an
observation behind every source-bound claim (section 12.2).  Neither is
modelled here, because neither has anything to bind to yet: nothing in this
work package observes a source, so a `provenance` column would hold NULL in
every row and an `observation_id` would name a table that does not exist.  They
arrive with the observation record itself, bound to the repository's existing
`Provenance` type rather than to free text.  `confidence` is not carried either, and that one is a
harder call: the specification does put it on these exact records (sections 12.5
and 12.15), but `tests/architecture/test_relationship_scoring_surface_is_denied`
denies the token outright on this surface as "a model likelihood", and the
specification's own section 22.3 admits a numeric only "when calibrated and
explained".  Nothing here calibrates or explains one, and nothing here produces
one.  Weakening a repository-wide prohibition to admit a field no writer fills
would be the wrong trade; the work package that first has an evidential
confidence to record makes the argument, adds the exemption, and tests it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.relationship.normalization import (
    ExternalIdentifierNamespace,
    is_normalized_identifier,
    is_normalized_name,
)

__all__ = [
    "ARCHIVABLE_STATUSES",
    "MAX_DIRECTED_EVIDENCE_REFS",
    "MAX_DIRECTED_REASON_CHARACTERS",
    "MAX_DIRECTED_TEXT_CHARACTERS",
    "AliasState",
    "AliasType",
    "Assignment",
    "AssignmentState",
    "AssignmentType",
    "DirectedWriteError",
    "DirectedWriteOperation",
    "DuplicateDirectedFactError",
    "Entity",
    "EntityAlias",
    "EntityRelationship",
    "EntityRelationshipType",
    "EntityStatus",
    "EntityType",
    "ExternalIdentifier",
    "ExternalIdentifierNamespace",
    "IdentifierState",
    "MergedEndpointError",
    "RelationshipState",
    "StaleDirectedVersionError",
    "descriptor_key",
    "validate_directed_reason",
    "validate_directed_text",
]


class EntityType(StrEnum):
    """The kinds of entity the generalized model admits.

    PERSON and ORGANIZATION mirror the existing identity-plane types; the
    remainder extend the model to programs, projects, work packages, teams,
    and locations.
    """

    PERSON = "person"
    ORGANIZATION = "organization"
    PROGRAM = "program"
    PROJECT = "project"
    WORK_PACKAGE = "work_package"
    TEAM_OR_GROUP = "team_or_group"
    LOCATION = "location"


class EntityStatus(StrEnum):
    """Lifecycle status of an entity.

    ACTIVE is the steady state.  INACTIVE and HISTORICAL record that the entity
    is no longer current.  MERGED_REDIRECT marks an entity whose identity has
    been folded into another; `superseded_by_entity_id` is then non-null.
    ARCHIVED records a soft-removal for audit continuity.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    HISTORICAL = "historical"
    MERGED_REDIRECT = "merged_redirect"
    ARCHIVED = "archived"


class AliasType(StrEnum):
    """The kinds of alias an entity may carry.

    Closed as of WP-RI-03, because the migration's `alias_type` CHECK references
    these values.  The set is the name *forms* a source can produce, not a
    judgement about which is correct: `FULL_NAME` and `PREFERRED_NAME` are both
    the person's name, and resolution treats them alike.
    """

    FULL_NAME = "full_name"
    PREFERRED_NAME = "preferred_name"
    NICKNAME = "nickname"
    INITIALS = "initials"
    ABBREVIATION = "abbreviation"
    FORMER_NAME = "former_name"
    DOCUMENT_REFERENCE = "document_reference"


class AssignmentType(StrEnum):
    """The kinds of assignment between an entity and a scope entity."""

    EMPLOYMENT = "employment"
    MEMBERSHIP = "membership"
    PROJECT_ASSIGNMENT = "project_assignment"
    WORK_PACKAGE_ASSIGNMENT = "work_package_assignment"
    TEAM_MEMBERSHIP = "team_membership"


class EntityRelationshipType(StrEnum):
    """The kinds of directed relationship between two entities.

    Frozen as of this revision; widening is a visible schema change rather than
    a silent one, because the migration's `relationship_type` CHECK constraint
    references these values.
    """

    WORKS_FOR = "works_for"
    REPORTS_TO = "reports_to"
    REPRESENTS = "represents"
    MANAGES = "manages"
    LEADS = "leads"
    RESPONSIBLE_FOR = "responsible_for"
    APPROVER_FOR = "approver_for"
    DECISION_MAKER_FOR = "decision_maker_for"
    PRIMARY_CONTACT_FOR = "primary_contact_for"
    MEMBER_OF = "member_of"
    CONSULTANT_TO = "consultant_to"
    CONTRACTOR_ON = "contractor_on"
    SUBCONTRACTOR_TO = "subcontractor_to"
    VENDOR_FOR = "vendor_for"
    AFFILIATED_WITH = "affiliated_with"


class IdentifierState(StrEnum):
    """Where one external-identifier binding stands.

    Three states rather than a boolean, because "this binding no longer holds"
    and "this binding was replaced by that one" are different facts and only the
    second names a successor. A binding that merely stopped being true --
    someone left the company and the mailbox was closed -- is RETIRED, and there
    is nothing to point at. A binding that was corrected is SUPERSEDED, and
    `superseded_by_identifier_id` says by what, so the correction is followable
    rather than a pair of rows a reader has to guess the order of.

    Nothing is deleted, which is the point of having the vocabulary at all:
    section 10.11 forbids a silent deletion, and a historical address is how a
    message from four years ago still resolves to the person who sent it.
    """

    ACTIVE = "active"
    RETIRED = "retired"
    SUPERSEDED = "superseded"


class AliasState(StrEnum):
    """Where one recorded name form stands.

    The same three states as `IdentifierState`, and deliberately a separate
    vocabulary rather than a shared one: the two records are widened
    independently, and a single enum would make widening either of them a silent
    widening of both. The distinction between RETIRED and SUPERSEDED is the one
    `IdentifierState` draws -- a former name that simply stopped being used has
    no successor to name, and a misspelling that was corrected does.
    """

    ACTIVE = "active"
    RETIRED = "retired"
    SUPERSEDED = "superseded"


class AssignmentState(StrEnum):
    """Where one assignment stands.

    This replaces an open `status: str` whose vocabulary was a convention: the
    repository filtered `active_only` on the literal `'active'` and the resolver
    treated every other value as not-live, so the column already *had* a closed
    meaning and nothing enforced it. A row written around either of those with
    `'Active'`, `'current'`, or `''` was silently excluded from the corroborating
    set, which is the direction that turns an ambiguous refusal into a confident
    wrong answer.

    ENDED rather than `inactive`, because an assignment is bounded by time and
    `ended_at` is the moment: a person stopped holding the role. SUPERSEDED is
    the correction path -- the assignment as recorded was wrong, and
    `superseded_by_assignment_id` names what replaced it.
    """

    ACTIVE = "active"
    ENDED = "ended"
    SUPERSEDED = "superseded"


class RelationshipState(StrEnum):
    """Where one directed edge stands.

    The same three states as `AssignmentState`, for the same reason: `state` was
    free text on this record too, and `entity_resolution.ACTIVE_RELATIONSHIP_STATE`
    named the one value that meant "live" while the column admitted anything.
    An unrecognised state read as *not* live, so a typo silently removed an edge
    from every corroborating read while leaving the row visibly present.
    """

    ACTIVE = "active"
    ENDED = "ended"
    SUPERSEDED = "superseded"


#: The statuses an entity may be archived *from*, and therefore the only values
#: `Entity.archived_from_status` may hold.
#:
#: ARCHIVED itself is absent because archiving an archived entity records no
#: transition, and MERGED_REDIRECT is absent because a merged-away entity is
#: already superseded by a live successor: archiving one would leave a redirect
#: whose target is reachable and whose source is not, which is a state no reader
#: could act on. What is left is the three statuses that describe an entity that
#: still stands on its own, and the whole purpose of the column is that
#: un-archiving restores one of them rather than guessing ACTIVE.
ARCHIVABLE_STATUSES: frozenset[EntityStatus] = frozenset(
    {EntityStatus.ACTIVE, EntityStatus.INACTIVE, EntityStatus.HISTORICAL}
)


@dataclass(frozen=True, slots=True)
class Entity:
    """A generalized entity in the relationship-intelligence model.

    `entity_id` and `principal_id` are required opaque identifiers validated
    against their respective IdKind.

    `created_at` and `updated_at` are both carried because the specification
    asks for both (section 12.1, "created and updated times"); a record whose
    only clock is its creation cannot answer how current it is.

    `superseded_by_entity_id` is non-null **exactly** when `status` is
    MERGED_REDIRECT, and then it must differ from `entity_id`. The
    biconditional rather than the one-way rule, and the same CHECK stands in
    the schema: a MERGED_REDIRECT with no target is a dangling redirect, and a
    target on any other status is a redirect nothing follows. Both are states a
    reader would have to guess about.

    `archived_from_status` is the same shape of rule, for the same reason.
    ARCHIVED is a soft removal that has to be reversible, and reversing it means
    restoring the status the entity actually held. Without the column, an
    un-archive has to *guess* -- almost always ACTIVE -- and an entity that was
    HISTORICAL before somebody archived it comes back claiming to be current,
    which is a false fact about a person produced by a bookkeeping operation. So
    the column is non-null exactly while the status is ARCHIVED, and it may hold
    only a status the entity could have stood in: `ARCHIVABLE_STATUSES`.
    """

    entity_id: str
    principal_id: str
    entity_type: EntityType
    canonical_name: str
    display_name: str
    status: EntityStatus
    created_at: datetime
    updated_at: datetime
    version: int
    superseded_by_entity_id: str | None = None
    archived_from_status: EntityStatus | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.entity_id, IdKind.ENTITY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.entity_type, EntityType):
            raise ValueError("an entity has a closed entity type")
        if not self.canonical_name.strip():
            raise ValueError("an entity canonical name is not blank")
        if not is_normalized_name(self.canonical_name):
            raise ValueError("an entity canonical name is stored already normalized")
        if not self.display_name.strip():
            raise ValueError("an entity display name is not blank")
        if not isinstance(self.status, EntityStatus):
            raise ValueError("an entity has a closed status")
        if self.version < 1:
            raise ValueError("an entity version is a positive integer")
        if (self.status is EntityStatus.MERGED_REDIRECT) != (
            self.superseded_by_entity_id is not None
        ):
            raise ValueError("an entity redirects exactly when it is merged away")
        if self.superseded_by_entity_id is not None:
            validate_identifier(self.superseded_by_entity_id, IdKind.ENTITY)
            if self.superseded_by_entity_id == self.entity_id:
                raise ValueError("an entity cannot supersede itself")
        if (self.status is EntityStatus.ARCHIVED) != (self.archived_from_status is not None):
            raise ValueError("an entity records the status it was archived from, and only then")
        if self.archived_from_status is not None and self.archived_from_status not in (
            ARCHIVABLE_STATUSES
        ):
            raise ValueError("an entity is archived from a status it could stand in")
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)
        if self.updated_at < self.created_at:
            raise ValueError("an entity cannot be updated before it is created")


@dataclass(frozen=True, slots=True)
class ExternalIdentifier:
    """An entity's identity in an external namespace.

    The triple (entity_id, namespace, normalized_value) must be unique, because
    the same external identity cannot be recorded twice for the same entity in
    the same namespace.

    **`state` is what makes one binding canonical.** Only one *active* binding of
    a `(namespace, normalized_value)` pair may exist per Principal, enforced by a
    partial unique index on the table, and that is the rule that stops one
    address from being the current identity of two entities at once. Retiring or
    superseding a binding rather than deleting it is what keeps the historical
    value queryable: a message from four years ago still has to resolve to the
    person who sent it, and it can only do that if the address they used then is
    still recorded.

    `updated_at` is `None` on a row nothing has revised since it was written.
    This record carries no `created_at`, so stamping `updated_at` on insert would
    make "written" indistinguishable from "revised"; `None` says which, and it is
    the whole reason the column is nullable while `entities.updated_at` is not.
    """

    identifier_id: str
    entity_id: str
    namespace: ExternalIdentifierNamespace
    normalized_value: str
    display_value: str
    principal_id: str
    verified: bool = False
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    state: IdentifierState = IdentifierState.ACTIVE
    version: int = 1
    updated_at: datetime | None = None
    retired_at: datetime | None = None
    superseded_by_identifier_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.identifier_id, IdKind.EXTERNAL_IDENTIFIER)
        validate_identifier(self.entity_id, IdKind.ENTITY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.namespace, ExternalIdentifierNamespace):
            raise ValueError("an external identifier has a closed namespace")
        if not self.normalized_value.strip():
            raise ValueError("an external identifier normalized value is not blank")
        if not is_normalized_identifier(self.namespace, self.normalized_value):
            raise ValueError("an external identifier normalized value is stored already normalized")
        if not self.display_value.strip():
            raise ValueError("an external identifier display value is not blank")
        if self.effective_from is not None:
            ensure_utc(self.effective_from)
        if self.effective_to is not None:
            ensure_utc(self.effective_to)
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("an external identifier cannot end before it begins")
        if not isinstance(self.state, IdentifierState):
            raise ValueError("an external identifier has a closed state")
        if self.version < 1:
            raise ValueError("an external identifier version is a positive integer")
        if self.updated_at is not None:
            ensure_utc(self.updated_at)
        if self.retired_at is not None:
            ensure_utc(self.retired_at)
            if self.state is IdentifierState.ACTIVE:
                raise ValueError("an external identifier is retired only once it leaves service")
        if self.superseded_by_identifier_id is not None:
            validate_identifier(self.superseded_by_identifier_id, IdKind.EXTERNAL_IDENTIFIER)
            if self.superseded_by_identifier_id == self.identifier_id:
                raise ValueError("an external identifier cannot supersede itself")
            if self.state is not IdentifierState.SUPERSEDED:
                raise ValueError("an external identifier names a successor only when superseded")


@dataclass(frozen=True, slots=True)
class EntityAlias:
    """One recorded name form of an entity.

    Named `EntityAlias` rather than `Alias` because `relationship.identity`
    already declares an `Alias`, and that one is source-bound to a single
    observation while this one belongs to the entity. Two records with one name
    in one package would make every import site say which plane it meant.

    Carried separately from `Entity.canonical_name` because an entity has one
    canonical name and many names it is actually referred to by, and resolution
    has to match on all of them (specification section 15.1, "aliases and
    initials").

    Both forms are kept for the reason `ExternalIdentifier` keeps both:
    `normalized_value` is what a lookup compares against and is lossy, and
    `display_value` is the evidence -- what a source actually wrote. An alias is
    time-aware, so a former name can be matched without being presented as
    current (section 12.3).

    **Only the active unique is per entity, and that is deliberate.** Two
    different entities may hold the same active alias -- two real people do share
    a name, and a schema that made that a conflict would force the false join
    this plane exists to avoid. What is refused is the same name form recorded
    twice as *active* for one entity under one alias type, which is a duplicate
    rather than a fact.
    """

    alias_id: str
    entity_id: str
    alias_type: AliasType
    normalized_value: str
    display_value: str
    principal_id: str
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    state: AliasState = AliasState.ACTIVE
    version: int = 1
    updated_at: datetime | None = None
    retired_at: datetime | None = None
    superseded_by_alias_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.alias_id, IdKind.ENTITY_ALIAS)
        validate_identifier(self.entity_id, IdKind.ENTITY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.alias_type, AliasType):
            raise ValueError("an alias has a closed alias type")
        if not self.normalized_value.strip():
            raise ValueError("an alias normalized value is not blank")
        if not is_normalized_name(self.normalized_value):
            raise ValueError("an alias normalized value is stored already normalized")
        if not self.display_value.strip():
            raise ValueError("an alias display value is not blank")
        if self.effective_from is not None:
            ensure_utc(self.effective_from)
        if self.effective_to is not None:
            ensure_utc(self.effective_to)
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("an alias cannot end before it begins")
        if not isinstance(self.state, AliasState):
            raise ValueError("an alias has a closed state")
        if self.version < 1:
            raise ValueError("an alias version is a positive integer")
        if self.updated_at is not None:
            ensure_utc(self.updated_at)
        if self.retired_at is not None:
            ensure_utc(self.retired_at)
            if self.state is AliasState.ACTIVE:
                raise ValueError("an alias is retired only once it leaves service")
        if self.superseded_by_alias_id is not None:
            validate_identifier(self.superseded_by_alias_id, IdKind.ENTITY_ALIAS)
            if self.superseded_by_alias_id == self.alias_id:
                raise ValueError("an alias cannot supersede itself")
            if self.state is not AliasState.SUPERSEDED:
                raise ValueError("an alias names a successor only when superseded")


@dataclass(frozen=True, slots=True)
class Assignment:
    """A typed assignment of an entity to a scope entity.

    `scope_entity_id` is nullable because some assignments (e.g. EMPLOYMENT)
    may not yet have a resolved scope entity; the role, discipline, and
    responsibility_class are free-form and nullable for the same reason.

    **`state` replaces an open `status` string.** The old column admitted any
    text while two readers -- the repository's `active_only` filter and the
    resolver's corroboration rule -- both compared it against the single literal
    `'active'`. So its vocabulary was already closed in effect and open in fact,
    and the gap between the two was silent: a row carrying `'Active'` was
    excluded from both without anything saying so. Closing it is what makes the
    two readers' agreement a property rather than a coincidence.

    **The active semantic unique is over the meaning of the assignment, not its
    identifier.** Two active rows saying the same thing about the same person in
    the same scope -- same type, same role, same discipline, same responsibility
    class, compared case- and whitespace-insensitively -- are one assignment
    written twice, and the second is a duplicate that would double-count in every
    read. `role`, `discipline` and `responsibility_class` are free text, so the
    index folds and trims them and treats NULL and the empty string alike;
    otherwise `Project Manager` and `project manager ` would be two assignments.
    """

    assignment_id: str
    entity_id: str
    assignment_type: AssignmentType
    principal_id: str
    scope_entity_id: str | None = None
    role: str | None = None
    discipline: str | None = None
    responsibility_class: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    state: AssignmentState = AssignmentState.ACTIVE
    version: int = 1
    updated_at: datetime | None = None
    ended_at: datetime | None = None
    superseded_by_assignment_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.assignment_id, IdKind.ASSIGNMENT)
        validate_identifier(self.entity_id, IdKind.ENTITY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.assignment_type, AssignmentType):
            raise ValueError("an assignment has a closed assignment type")
        if self.scope_entity_id is not None:
            validate_identifier(self.scope_entity_id, IdKind.ENTITY)
        if self.effective_from is not None:
            ensure_utc(self.effective_from)
        if self.effective_to is not None:
            ensure_utc(self.effective_to)
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("an assignment cannot end before it begins")
        if not isinstance(self.state, AssignmentState):
            raise ValueError("an assignment has a closed state")
        if self.version < 1:
            raise ValueError("an assignment version is a positive integer")
        if self.updated_at is not None:
            ensure_utc(self.updated_at)
        if self.ended_at is not None:
            ensure_utc(self.ended_at)
            if self.state is AssignmentState.ACTIVE:
                raise ValueError("an assignment ends only once it leaves service")
        if self.superseded_by_assignment_id is not None:
            validate_identifier(self.superseded_by_assignment_id, IdKind.ASSIGNMENT)
            if self.superseded_by_assignment_id == self.assignment_id:
                raise ValueError("an assignment cannot supersede itself")
            if self.state is not AssignmentState.SUPERSEDED:
                raise ValueError("an assignment names a successor only when superseded")


@dataclass(frozen=True, slots=True)
class EntityRelationship:
    """A directed, typed relationship between two entities.

    `from_entity_id` and `to_entity_id` are required; `scope_entity_id`
    is nullable because some relationships (e.g. WORKS_FOR) have an inherent
    scope while others (e.g. AFFILIATED_WITH) do not.

    `state` was free text until this revision and is now closed on the same
    argument `AssignmentState` makes: one reader treated a single literal as
    "live" and every other value as not, so an unrecognised state removed the
    edge from every corroborating read while leaving the row visibly present.

    The active unique is over `(from, type, to, scope)`, so the same *pair* may
    still appear in both directions and under different types -- which is what a
    directed model is for -- while the same edge cannot be asserted twice.
    """

    relationship_id: str
    from_entity_id: str
    relationship_type: EntityRelationshipType
    to_entity_id: str
    principal_id: str
    scope_entity_id: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    state: RelationshipState = RelationshipState.ACTIVE
    version: int = 1
    updated_at: datetime | None = None
    ended_at: datetime | None = None
    superseded_by_relationship_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.relationship_id, IdKind.ENTITY_RELATIONSHIP)
        validate_identifier(self.from_entity_id, IdKind.ENTITY)
        validate_identifier(self.to_entity_id, IdKind.ENTITY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.relationship_type, EntityRelationshipType):
            raise ValueError("an entity relationship has a closed relationship type")
        if self.from_entity_id == self.to_entity_id:
            raise ValueError("an entity relationship connects two distinct entities")
        if self.scope_entity_id is not None:
            validate_identifier(self.scope_entity_id, IdKind.ENTITY)
        if self.effective_from is not None:
            ensure_utc(self.effective_from)
        if self.effective_to is not None:
            ensure_utc(self.effective_to)
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("an entity relationship cannot end before it begins")
        if self.version < 1:
            raise ValueError("an entity relationship version is a positive integer")
        if not isinstance(self.state, RelationshipState):
            raise ValueError("an entity relationship has a closed state")
        if self.updated_at is not None:
            ensure_utc(self.updated_at)
        if self.ended_at is not None:
            ensure_utc(self.ended_at)
            if self.state is RelationshipState.ACTIVE:
                raise ValueError("an entity relationship ends only once it leaves service")
        if self.superseded_by_relationship_id is not None:
            validate_identifier(self.superseded_by_relationship_id, IdKind.ENTITY_RELATIONSHIP)
            if self.superseded_by_relationship_id == self.relationship_id:
                raise ValueError("an entity relationship cannot supersede itself")
            if self.state is not RelationshipState.SUPERSEDED:
                raise ValueError("an entity relationship names a successor only when superseded")


#: How long one free-text descriptor on an assignment may be: `role`,
#: `discipline`, `responsibility_class`. Stated here rather than in a command,
#: because the value is a property of the record and three transports would
#: otherwise each carry a ceiling able to disagree with the others.
#:
#: Long enough for `Senior Mechanical Coordinator (Central Plant)`; short enough
#: that a sentence about the person does not fit. A descriptor that has to be a
#: sentence is a Relationship Memory, not an assignment field.
MAX_DIRECTED_TEXT_CHARACTERS = 200

#: How long the explanation attached to an `end` may be. The same 500 the
#: mutation ledger's own `a_mutation_reason_is_bounded` CHECK enforces, because
#: it is the same value: this is what is written into `reason`, and a domain
#: bound wider than the column's would refuse at the database instead of at the
#: request.
MAX_DIRECTED_REASON_CHARACTERS = 500

#: How many evidence references one directed write may cite. A bound rather than
#: none, for the reason every listing on this surface is bounded: an unbounded
#: array on a write is an unbounded row set on the link table behind it.
MAX_DIRECTED_EVIDENCE_REFS = 20


class DirectedWriteOperation(StrEnum):
    """Which of the three acts one directed-relationship write performs.

    Three rather than four. There is no `delete`: a record leaves service by
    `END`, which keeps the row and its history, on the argument
    `relationship_memory` makes for having no delete capability at all.

    `CREATE` and `END` are the only two that may change what a record *means*.
    `REVISE` is deliberately the narrow one -- it carries descriptive and
    effective fields only -- because type, endpoints and scope are the record's
    semantic identity, and editing identity in place turns "this was wrong" into
    "this was always so".
    """

    CREATE = "create"
    REVISE = "revise"
    END = "end"


class DirectedWriteError(Exception):
    """A directed-relationship write this plane refuses.

    A vocabulary of its own rather than a reuse of `RelationshipMemoryError`,
    for the reason those two planes have separate purposes: they are refusals
    about different records, and one hierarchy would let a handler catching a
    memory failure absorb an assignment failure it has no answer for.
    """


class StaleDirectedVersionError(DirectedWriteError):
    """The expected version of a record or of one of its endpoints is not current."""


class DuplicateDirectedFactError(DirectedWriteError):
    """An identical active assignment or edge already exists for this Principal."""


class MergedEndpointError(DirectedWriteError):
    """An entity this write names has been merged away and is not writable.

    Raised rather than followed. Following a redirect would rebind the caller's
    write to a different identity, which records a fact the user did not state.
    """


def validate_directed_text(value: str | None, *, field: str) -> str | None:
    """One free-text descriptor, or `None`.

    Blank is `None` rather than the empty string, and this is the rule the
    active semantic unique already encodes: `COALESCE(lower(trim(role)),'')`
    folds NULL, `''` and `'  '` together, so a record written with a blank role
    and one written with no role are one assignment at the database. Collapsing
    here makes the application agree with the index instead of storing a
    distinction nothing downstream can see.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise DirectedWriteError(f"{field} is text or absent")
    trimmed = value.strip()
    if not trimmed:
        return None
    if len(trimmed) > MAX_DIRECTED_TEXT_CHARACTERS:
        raise DirectedWriteError(f"{field} exceeds the descriptor ceiling")
    return trimmed


def validate_directed_reason(value: str) -> str:
    """The bounded explanation an `end` carries.

    Required rather than optional. Ending an assignment or an edge is how the
    plane records that something stopped being true, and a withdrawal with no
    stated reason leaves a reader unable to tell a correction from a change in
    the world -- which is the distinction `ENDED` and `SUPERSEDED` exist to
    preserve one level down.
    """
    if not isinstance(value, str):
        raise DirectedWriteError("an end carries a bounded reason")
    trimmed = value.strip()
    if not trimmed or len(value) > MAX_DIRECTED_REASON_CHARACTERS:
        raise DirectedWriteError("an end carries a bounded reason")
    return trimmed


def descriptor_key(value: str | None) -> str:
    """One descriptor as the active semantic unique compares it.

    `COALESCE(lower(trim(x)), '')`, restated in Python because the application
    has to be able to answer "is this a duplicate" *before* the insert in order
    to decide replay, and the only alternative is asking the database and
    reading the answer out of an aborted transaction.

    **This is a second copy of a rule, and it is the copy that is checked
    against the first.** `tests/database/test_entity_directed_writes.py` proves
    the two agree on the null-safe and case-folded cases rather than asserting
    them separately, because a folding rule stated twice and compared once is a
    rule; stated twice and never compared it is two rules that drift.
    """
    return "" if value is None else value.strip().lower()
