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
    "AliasType",
    "Assignment",
    "AssignmentType",
    "Entity",
    "EntityAlias",
    "EntityRelationship",
    "EntityRelationshipType",
    "EntityStatus",
    "EntityType",
    "ExternalIdentifier",
    "ExternalIdentifierNamespace",
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
    """

    alias_id: str
    entity_id: str
    alias_type: AliasType
    normalized_value: str
    display_value: str
    principal_id: str
    effective_from: datetime | None = None
    effective_to: datetime | None = None

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


@dataclass(frozen=True, slots=True)
class Assignment:
    """A typed assignment of an entity to a scope entity.

    `scope_entity_id` is nullable because some assignments (e.g. EMPLOYMENT)
    may not yet have a resolved scope entity; the role, discipline, and
    responsibility_class are free-form and nullable for the same reason.
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
    status: str = "active"

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


@dataclass(frozen=True, slots=True)
class EntityRelationship:
    """A directed, typed relationship between two entities.

    `from_entity_id` and `to_entity_id` are required; `scope_entity_id`
    is nullable because some relationships (e.g. WORKS_FOR) have an inherent
    scope while others (e.g. AFFILIATED_WITH) do not.
    """

    relationship_id: str
    from_entity_id: str
    relationship_type: EntityRelationshipType
    to_entity_id: str
    principal_id: str
    scope_entity_id: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    state: str = "active"
    version: int = 1

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
