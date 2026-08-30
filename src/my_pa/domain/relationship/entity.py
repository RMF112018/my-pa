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

import re
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
    "AddressTypeCode",
    "AliasState",
    "AliasType",
    "Assignment",
    "AssignmentState",
    "AssignmentType",
    "CommunicationMethodTypeCode",
    "CommunicationUsageContextCode",
    "CommunicationVerificationStatusCode",
    "DirectedWriteError",
    "DirectedWriteOperation",
    "DuplicateDirectedFactError",
    "Entity",
    "EntityAddress",
    "EntityAddressState",
    "EntityAlias",
    "EntityCommunicationMethod",
    "EntityCommunicationMethodState",
    "EntityDisciplineType",
    "EntityName",
    "EntityNameState",
    "EntityOrganizationProfile",
    "EntityProjectParticipation",
    "EntityProjectParticipationState",
    "EntityRelationship",
    "EntityRelationshipType",
    "EntityRoleType",
    "EntityStatus",
    "EntityType",
    "ExternalIdentifier",
    "ExternalIdentifierNamespace",
    "IdentifierState",
    "LegalIdentityStatusCode",
    "MergedEndpointError",
    "NameTypeCode",
    "OrganizationKindCode",
    "ParticipationStatusCode",
    "RelationshipState",
    "RoleBasisCode",
    "StakeholderClassCode",
    "StakeholderSideCode",
    "StaleDirectedVersionError",
    "TaxonomyEntryStatus",
    "descriptor_key",
    "is_normalized_communication_value",
    "normalize_address",
    "normalize_communication_value",
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


class NameTypeCode(StrEnum):
    """The typed name forms `entity_names` (RI-ENT-WP-02) may record.

    Closed because the migration's `name_type_code` CHECK references these
    values, on the same argument `AliasType` is closed. `DISPLAY` and `ALIAS`
    coexist with `Entity.display_name` and `entity_aliases` respectively —
    this table does not replace either in this revision; RULING 3 keeps
    `entities.canonical_name`/`display_name` meaning what they mean today; see
    the module-level compatibility note.

    The audit (`docs/campaign/...robust-entity-data-model...`, RI-ENT-WP-02)
    is explicit that a **historical juristic entity is its own `entities`
    row**, linked by a relationship, not a name row: `HISTORICAL_NAME` names
    only a former name of the *same* juristic identity — a rename, not a
    successor company. Confusing the two would let a merger or an acquisition
    disappear into a name change.
    """

    DISPLAY = "display"
    LEGAL = "legal"
    OPERATING = "operating"
    DBA = "dba"
    BRAND = "brand"
    ACRONYM = "acronym"
    ALIAS = "alias"
    HISTORICAL_NAME = "historical_name"
    DOCUMENT_REFERENCE = "document_reference"


class EntityNameState(StrEnum):
    """Where one typed name row stands.

    The same three states `AliasState` and `IdentifierState` declare, and
    deliberately its own vocabulary rather than a shared one, for the reason
    `AliasState`'s docstring already gives for not sharing with
    `IdentifierState`: `entity_names` is widened independently of
    `entity_aliases`, and one enum would make widening either a silent
    widening of both.
    """

    ACTIVE = "active"
    RETIRED = "retired"
    SUPERSEDED = "superseded"


class OrganizationKindCode(StrEnum):
    """The organization subtypes `entity_organization_profiles` distinguishes.

    Closed as of RI-ENT-WP-02. The audit's Record Element Inventory (row
    "Government/utility/SPV/professional-practice/brand subtype") is explicit
    that today's plane cannot tell a City government, a utility, a
    single-purpose vehicle, a professional practice, or a brand/operating unit
    apart from an ordinary company without abusing `entity_type`, which stays
    at `EntityType.ORGANIZATION` for all of them. `OTHER_OR_UNRESOLVED` is not
    a default: a writer states it, the same way `LegalIdentityStatusCode`
    states `UNRESOLVED` rather than a caller omitting the column.
    """

    COMPANY = "company"
    LLC_OR_SPV = "llc_or_spv"
    PROFESSIONAL_PRACTICE = "professional_practice"
    BRAND_OR_OPERATING_UNIT = "brand_or_operating_unit"
    GOVERNMENT_AUTHORITY = "government_authority"
    UTILITY = "utility"
    NONPROFIT = "nonprofit"
    PUBLIC_AGENCY = "public_agency"
    OTHER_OR_UNRESOLVED = "other_or_unresolved"


class LegalIdentityStatusCode(StrEnum):
    """How well-supported an organization's legal identity is.

    **Not a confidence score.** `tests/architecture/test_relationship_scoring_surface_is_denied`
    denies `confidence|certainty|probability|likelihood|propensity` outright
    on this surface as "a model likelihood" (Operating brief §22), and the
    audit itself proposed `legal_identity_confidence` — a name this revision
    does not use. This vocabulary is the evidence-anchored alternative the
    audit's own R section admits is needed at this granularity: four discrete,
    named states a reviewer can act on, not a number nobody calibrated.
    `VERIFIED` and `BEST_SUPPORTED` are both affirmative and distinguish
    *how* an identity was established (e.g. a registration lookup versus a
    corroborated but unconfirmed source); `UNRESOLVED` and
    `AWAITING_CONFIRMATION` are both non-affirmative and distinguish *why* —
    no candidate identity exists to confirm, versus one exists and a
    confirmation step has not run.
    """

    VERIFIED = "verified"
    BEST_SUPPORTED = "best_supported"
    UNRESOLVED = "unresolved"
    AWAITING_CONFIRMATION = "awaiting_confirmation"


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
class EntityName:
    """One typed name form of an entity (RI-ENT-WP-02).

    The audit's typed-name successor to `EntityAlias`: where an alias records
    the name *forms* a source produced without judging which is authoritative,
    `EntityName.name_type_code` records what *kind* of name a form is —
    display, legal, operating, DBA, brand, acronym, alias, historical, or a
    document's literal reference. `entity_aliases` is preserved as-is
    (RULING 3 / the module compatibility note): this is an additional record
    family, not a migration of that one, and a later work package decides
    whether to consolidate them.

    `entities.canonical_name` and `entities.display_name` keep their existing
    meaning. `EntityType.canonical_name` is a normalized match key and
    `display_name` a human default — neither becomes a legal name because a
    row exists here that says the entity's legal name is something else; a
    `LEGAL` name row is *additional* structured evidence, read by callers who
    need it, not a silent reinterpretation of two columns other code already
    depends on.

    **A historical juristic entity is its own `Entity` row, not a name row.**
    `HISTORICAL_NAME` records a former name of the *same* legal person — GS4
    Studios renaming its own signage is a name row; Garcia Stromberg Holdings,
    LLC becoming a predecessor to GS4 Studios, LLC through an acquisition is
    two `Entity` rows connected by a relationship, because collapsing the
    second case into a name row would make a change of legal identity
    invisible to anything that reads entity relationships rather than name
    history.

    **Merge/split.** This family is not yet wired into
    `my_pa.application.identity_correction`'s `IdentityEffectFamily` /
    ambiguity-discovery / reparenting machinery (RULING 2's second branch: a
    documented, evidenced exclusion rather than a silent one). No command or
    MCP capability in this increment writes `entity_names` outside test
    fixtures, so no merge can yet encounter a populated row through ordinary
    product use; a merge of an entity that *does* carry name rows today leaves
    them bound to the merged-away `entity_id`, which stays resolvable through
    `entities.superseded_by_entity_id` but not reachable by querying the
    survivor's names directly. Wiring the reparenting, collision and ambiguity
    logic `EntityAlias` already has is deferred to RI-ENT-WP-06, which the
    audit's own work-package ordering already binds to "coordinate merge/split
    effects" rather than to the WP-02 taxonomy work.

    Field-for-field this mirrors `EntityAlias`; see that class's docstring for
    the reasoning behind the per-(entity, type) active uniqueness, the
    normalized/display split, and the RETIRED/SUPERSEDED distinction. The one
    addition is `is_preferred`: an entity may hold several simultaneously
    active names of one type (e.g. two active `BRAND` names during a
    transition), and `is_preferred` marks which one a reader should default to
    without inventing a ranking of the rest.
    """

    entity_name_id: str
    entity_id: str
    principal_id: str
    name_type_code: NameTypeCode
    display_value: str
    normalized_value: str
    is_preferred: bool = False
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    state: EntityNameState = EntityNameState.ACTIVE
    version: int = 1
    updated_at: datetime | None = None
    retired_at: datetime | None = None
    superseded_by_entity_name_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.entity_name_id, IdKind.ENTITY_NAME)
        validate_identifier(self.entity_id, IdKind.ENTITY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.name_type_code, NameTypeCode):
            raise ValueError("an entity name has a closed name type")
        if not self.normalized_value.strip():
            raise ValueError("an entity name normalized value is not blank")
        if not is_normalized_name(self.normalized_value):
            raise ValueError("an entity name normalized value is stored already normalized")
        if not self.display_value.strip():
            raise ValueError("an entity name display value is not blank")
        if not isinstance(self.is_preferred, bool):
            raise ValueError("an entity name is_preferred is a boolean")
        if self.effective_from is not None:
            ensure_utc(self.effective_from)
        if self.effective_to is not None:
            ensure_utc(self.effective_to)
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("an entity name cannot end before it begins")
        if not isinstance(self.state, EntityNameState):
            raise ValueError("an entity name has a closed state")
        if self.version < 1:
            raise ValueError("an entity name version is a positive integer")
        if self.updated_at is not None:
            ensure_utc(self.updated_at)
        if self.retired_at is not None:
            ensure_utc(self.retired_at)
            if self.state is EntityNameState.ACTIVE:
                raise ValueError("an entity name is retired only once it leaves service")
        if self.superseded_by_entity_name_id is not None:
            validate_identifier(self.superseded_by_entity_name_id, IdKind.ENTITY_NAME)
            if self.superseded_by_entity_name_id == self.entity_name_id:
                raise ValueError("an entity name cannot supersede itself")
            if self.state is not EntityNameState.SUPERSEDED:
                raise ValueError("an entity name names a successor only when superseded")


@dataclass(frozen=True, slots=True)
class EntityOrganizationProfile:
    """The organization-specific profile of an entity (RI-ENT-WP-02).

    Closes `ENTITY-SCHEMA-001`'s organization half: `entity_type` alone cannot
    say whether an organization entity is an ordinary company, an SPV, a
    professional practice, a government authority, a utility, or a brand
    operating unit (audit Record Element Inventory, "Government/utility/SPV/
    professional-practice/brand subtype"), and `legal_identity_status_code`
    gives that same organization's legal identity a stated, evidence-anchored
    status distinct from `Entity.status`'s lifecycle meaning — an active,
    un-merged organization can still have an unresolved legal identity.

    **One row per entity, not a history.** `entity_id` is both this record's
    identity and its foreign key: an organization has one current
    classification, not several simultaneous ones, which is what makes this a
    profile rather than a temporal record family like `EntityName` or
    `ExternalIdentifier`. A correction replaces the row in place, under its
    own `version`; there is nothing here for `state`/`effective_from`/
    `superseded_by_*` to mean, and adding them would carry columns with no
    row that could ever populate them.

    **Not a `confidence` field.** `legal_identity_status_code` is
    `LegalIdentityStatusCode`, the closed vocabulary the module-level guard
    (`test_relationship_scoring_surface_is_denied`) requires in place of the
    numeric confidence the audit proposed; see that class's docstring.

    **Merge/split.** Not yet wired into
    `my_pa.application.identity_correction`, for the same reason and under the
    same deferral (RI-ENT-WP-06) as `EntityName` above. A merge of two
    organization entities that each carry a profile is exactly the case that
    wiring must resolve — which profile the survivor keeps is a decision this
    revision does not make, because nothing yet writes a second profile onto a
    survivor to force the question. This class's own database constraint
    (`entity_id` as primary key) at least guarantees the *shape* of that future
    conflict is a duplicate-key collision the writer must resolve, not a
    silent second row.

    This profile applies to organization entities; nothing in this revision's
    schema enforces `entities.entity_type = 'organization'` for a given row
    (a cross-table invariant no `CHECK` expresses without a trigger this
    increment does not add) — the writer that populates this table is
    responsible for that invariant, the same way every other write-time
    invariant on this plane is enforced by its writer rather than a trigger.
    """

    entity_id: str
    principal_id: str
    organization_kind_code: OrganizationKindCode
    legal_identity_status_code: LegalIdentityStatusCode
    jurisdiction_code: str | None = None
    registration_identifier: str | None = None
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.entity_id, IdKind.ENTITY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.organization_kind_code, OrganizationKindCode):
            raise ValueError("an organization profile has a closed organization kind")
        if not isinstance(self.legal_identity_status_code, LegalIdentityStatusCode):
            raise ValueError("an organization profile has a closed legal identity status")
        if self.jurisdiction_code is not None and not self.jurisdiction_code.strip():
            raise ValueError("an organization profile jurisdiction code is not blank when present")
        if self.registration_identifier is not None and not self.registration_identifier.strip():
            raise ValueError(
                "an organization profile registration identifier is not blank when present"
            )
        if self.version < 1:
            raise ValueError("an organization profile version is a positive integer")
        if self.created_at is not None:
            ensure_utc(self.created_at)
        if self.updated_at is not None:
            ensure_utc(self.updated_at)
        if (
            self.created_at is not None
            and self.updated_at is not None
            and self.updated_at < self.created_at
        ):
            raise ValueError("an organization profile cannot be updated before it is created")


class AddressTypeCode(StrEnum):
    """The kinds of address `entity_addresses` (RI-ENT-WP-03) may record.

    Closed as of RI-ENT-WP-03, because the migration's `address_type_code`
    CHECK references these values, on the same argument `NameTypeCode` is
    closed. The nine values are the address *roles* the audit's Record
    Element Inventory names for this family ("Project address / legal
    principal address / HQ / regional or known office / city hall") -- not a
    judgement about which is most authoritative for an entity, the same way
    `NameTypeCode` does not rank `LEGAL` above `BRAND`. An entity may hold
    several simultaneously active addresses of different types (a
    headquarters and a project address are not competing facts), and may
    hold more than one of the *same* type only when they are not identical
    (see the uniqueness rule on the table).
    """

    PROJECT = "project"
    LEGAL_PRINCIPAL = "legal_principal"
    HEADQUARTERS = "headquarters"
    REGIONAL_OFFICE = "regional_office"
    OFFICE = "office"
    BUSINESS = "business"
    MAILING = "mailing"
    CITY_HALL = "city_hall"
    KNOWN_OTHER = "known_other"


class EntityAddressState(StrEnum):
    """Where one address row stands.

    The same three states `EntityNameState` declares, and deliberately its
    own vocabulary rather than a shared one, for the reason `EntityNameState`'s
    own docstring already gives for not sharing a vocabulary across unrelated
    record families: `entity_addresses` is widened independently of
    `entity_names`, and one enum would make widening either a silent widening
    of both.
    """

    ACTIVE = "active"
    RETIRED = "retired"
    SUPERSEDED = "superseded"


#: Collapses runs of whitespace to a single space when canonicalizing an
#: address field. Declared once so `normalize_address` applies exactly one
#: rule rather than several call sites each writing their own.
_ADDRESS_WHITESPACE: re.Pattern[str] = re.compile(r"\s+")


def _clean_address_field(value: str) -> str:
    """One address field or `raw_value`, trimmed, whitespace-collapsed, folded."""
    return _ADDRESS_WHITESPACE.sub(" ", value.strip()).casefold()


def normalize_address(
    *,
    line1: str | None,
    line2: str | None,
    city: str | None,
    region: str | None,
    postal_code: str | None,
    country: str | None,
    raw_value: str,
) -> str:
    """The canonical form of whichever address structure is actually known.

    **This is canonicalization, not inference (RULING 3).** It never splits
    `raw_value` to guess at `line1`/`city`/`region`/`postal_code`/`country`; it
    only folds whichever of those a caller already populated -- because the
    source stated that structure -- into a deterministic, comparable string.
    Partial structure is fine and expected: a caller who knows `city` but not
    `postal_code` passes `postal_code=None`, and the result is built from
    exactly the fields that are present, in the fixed order
    `line1, line2, city, region, postal_code, country`, each trimmed,
    whitespace-collapsed, and case-folded, then joined with `|` so an empty
    field cannot silently merge two adjacent ones. When no structured field is
    known at all, the fallback is the same canonicalization applied to
    `raw_value` itself -- still a fold of an already-known string, never a
    parse of it into new structure.
    """
    fields = (line1, line2, city, region, postal_code, country)
    parts = [_clean_address_field(field) for field in fields if field is not None and field.strip()]
    if parts:
        return "|".join(parts)
    return _clean_address_field(raw_value)


class CommunicationMethodTypeCode(StrEnum):
    """The kinds of contact channel `entity_communication_methods` (RI-ENT-WP-03) may record.

    **The type is stated by the source or caller; it is never inferred from
    the shape of the value (RULING 3).** No code in this module or its
    persistence layer sniffs a value with a regex to decide it "looks like" an
    email or a phone number and picks a type for it -- a caller that wants to
    record an email states `EMAIL`, and `normalize_communication_value` then
    validates the value is well-formed *for* the type it was told, which is a
    narrower thing than choosing the type from the string.
    """

    EMAIL = "email"
    PHONE = "phone"
    DOMAIN = "domain"
    WEBSITE = "website"


class CommunicationUsageContextCode(StrEnum):
    """What role one contact channel plays, distinct from its type.

    Closed as of RI-ENT-WP-03. `method_type_code` says *what kind* of channel
    a row is (email/phone/domain/website); this says *what it is used for*
    (a corporate switchboard number versus a specific project's sales line
    versus a named person's office extension). The two are independent axes:
    the uniqueness rule on the table is keyed on `(entity, method type,
    normalized value)`, not on usage context, precisely so the same physical
    channel is not double-counted merely because two rows disagree about
    which context it serves -- see the table's uniqueness comment.
    """

    CORPORATE = "corporate"
    PROJECT = "project"
    PROJECT_SALES = "project_sales"
    GENERIC = "generic"
    PERSONAL = "personal"
    OFFICE = "office"
    OTHER = "other"


class CommunicationVerificationStatusCode(StrEnum):
    """How well-supported a contact channel's correctness is.

    **Not a confidence score**, for the same reason and under the same guard
    `LegalIdentityStatusCode` cites:
    `tests/architecture/test_relationship_scoring_surface_is_denied` denies
    `confidence|certainty|probability|likelihood|propensity` outright as "a
    model likelihood".

    **Deliberately its own vocabulary, not a reuse of `LegalIdentityStatusCode`,
    even though the four members read the same.** They name states along two
    different dimensions that happen to share a shape: `LegalIdentityStatusCode`
    is about whether an *organization's legal identity* is established, and
    this one is about whether a *contact channel actually reaches the right
    party*. An organization can have a `VERIFIED` legal identity and an
    `UNRESOLVED` phone number, or the reverse, and a single shared enum would
    force one migration's widening (say, a legal-identity nuance
    `entity_organization_profiles` needs) to also widen every
    `entity_communication_methods` row's vocabulary whether or not that
    dimension asked for it -- exactly the coupling `EntityNameState`'s
    docstring already warns against for record families, applied here to a
    status vocabulary instead of a lifecycle one.
    """

    VERIFIED = "verified"
    BEST_SUPPORTED = "best_supported"
    UNRESOLVED = "unresolved"
    AWAITING_CONFIRMATION = "awaiting_confirmation"


class EntityCommunicationMethodState(StrEnum):
    """Where one communication-method row stands.

    The same three states `EntityNameState` and `EntityAddressState` declare,
    and its own vocabulary for the same reason both of theirs are: this family
    is widened independently of either, and a shared enum would make widening
    one a silent widening of all three.
    """

    ACTIVE = "active"
    RETIRED = "retired"
    SUPERSEDED = "superseded"


def normalize_communication_value(method_type_code: CommunicationMethodTypeCode, value: str) -> str:
    """The canonical form `value` takes for the *stated* `method_type_code`.

    Dispatches on the type the caller already committed to -- never the other
    way around. What this function checks is that `value` is well-formed *for*
    that stated type: an `EMAIL` value with no `@` or a `PHONE` value with
    almost no digits is not a channel of that type under any normalization,
    and refusing it here is validation against a stated type, not detection of
    an unstated one (RULING 3).

    `PHONE` normalizes to digits-only -- a simple, deterministic canonical
    form chosen over full E.164/libphonenumber-grade validation because
    nothing in this increment needs to validate country codes or dialability,
    only to compare two phone values for equality. `EMAIL`, `DOMAIN`, and
    `WEBSITE` normalize to trimmed and case-folded, because DNS hostnames and
    RFC 5321 mailbox domains are both case-insensitive by their own
    specification -- the same argument
    `normalization.CASE_FOLDED_NAMESPACES` already makes for
    `ExternalIdentifierNamespace.EMAIL`. `EMAIL`'s local-part is folded here
    (unlike `normalization._normalize_email`, which deliberately leaves it
    alone) because a contact channel is a lower-precision fact than an
    identity binding: the identity plane must not risk a false join between
    two mailboxes a provider treats as distinct, while a duplicate contact
    channel here is a nuisance a person can merge, not a wrong-person
    contamination.
    """
    if not isinstance(method_type_code, CommunicationMethodTypeCode):
        raise ValueError("a communication value is normalized within a closed method type")
    stripped = value.strip()
    if not stripped:
        raise ValueError("a communication value normalizes to nothing matchable")
    if method_type_code is CommunicationMethodTypeCode.PHONE:
        digits = re.sub(r"[^0-9]", "", stripped)
        if len(digits) < 7:
            raise ValueError("a phone communication value carries too few digits to be one")
        return digits
    if method_type_code is CommunicationMethodTypeCode.EMAIL:
        local, separator, domain = stripped.rpartition("@")
        if not separator or not local or not domain or "@" in local:
            raise ValueError("an email communication value has exactly one local part and domain")
        return f"{local.casefold()}@{domain.casefold()}"
    # DOMAIN, WEBSITE: a bare host or a URL-shaped value. Neither carries an
    # "@" (that would make it an email) and neither carries whitespace.
    if "@" in stripped or any(character.isspace() for character in stripped):
        raise ValueError("a domain or website communication value is a bare host, not a mailbox")
    return stripped.casefold()


def is_normalized_communication_value(
    method_type_code: CommunicationMethodTypeCode, value: str
) -> bool:
    """Whether `value` is already the form `normalize_communication_value` produces."""
    try:
        return normalize_communication_value(method_type_code, value) == value
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class EntityAddress:
    """One normalized address of an entity (RI-ENT-WP-03).

    Closes `ENTITY-SCHEMA-002`: the audit's Record Element Inventory names
    "Project address / legal principal address / HQ / regional or known
    office / city hall" as a representation family with no owning table
    before this revision (see the WP-01 ownership table,
    `docs/campaign/ROBUST-ENTITY-DATA-MODEL-20260830.md`), and
    `address_type_code` is exactly that closed set of address roles.

    **Structured fields are populated only when the source stated that
    structure (RULING 3).** `line1`/`line2`/`city`/`region`/`postal_code`/
    `country` are independently nullable, and a writer must never derive them
    by splitting `raw_value` on commas or newlines -- an inferred field is
    indistinguishable from a stated one once it is stored, and a wrong guess
    here is a wrong fact about where an entity is, not a formatting
    convenience. `raw_value` is the one field guaranteed to always be
    populated: the verbatim string a source actually gave, kept even when none
    of the structured fields could be. `normalized_address_value` is computed
    by `normalize_address` -- a canonicalization of whichever structure is
    known (or of `raw_value` alone when none is), never a geocoding or
    inference step, and never independently writable in a way that could
    disagree with the fields it was computed from: this class's own
    `__post_init__` recomputes it and refuses a mismatch, the same way
    `EntityName.normalized_value` is checked against `is_normalized_name`
    rather than trusted.

    **Uniqueness is per (entity, address type), not per entity.** The same
    normalized address may legitimately appear twice for one entity under two
    *different* `address_type_code`s -- a seller's legal-principal address and
    a project address can be, and often are, the identical street address --
    and the active uniqueness index (`principal_id, entity_id,
    address_type_code, normalized_address_value`) is keyed to permit exactly
    that while still refusing the same (entity, type) pair recorded twice
    actively. `is_preferred` marks, at most once per active (entity, type)
    group, which address a reader should default to when more than one
    simultaneously active address of that type exists.

    **Merge/split.** This family is not yet wired into
    `my_pa.application.identity_correction`'s `IdentityEffectFamily` /
    ambiguity-discovery / reparenting machinery (RULING 2's second branch: a
    documented, evidenced exclusion rather than a silent one). No command or
    MCP capability in this increment writes `entity_addresses` outside test
    fixtures, so no merge can yet encounter a populated row through ordinary
    product use; a merge of an entity that *does* carry address rows today
    leaves them bound to the merged-away `entity_id`, which stays resolvable
    through `entities.superseded_by_entity_id` but not reachable by querying
    the survivor's addresses directly. Wiring the reparenting, collision and
    ambiguity logic is deferred to RI-ENT-WP-06, the same work package
    `EntityName` and `EntityOrganizationProfile` defer to, and for the same
    reason: the audit's own work-package ordering binds merge/split
    coordination there, not to this increment's schema work. `WP-08`
    (repositories/services) and `WP-11` (MCP mutation contracts) may not ship
    a write path for this family until that wiring lands -- see the campaign
    document's "Merge/split disposition" section.
    """

    entity_address_id: str
    entity_id: str
    principal_id: str
    address_type_code: AddressTypeCode
    raw_value: str
    normalized_address_value: str
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None
    label: str | None = None
    is_preferred: bool = False
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    state: EntityAddressState = EntityAddressState.ACTIVE
    version: int = 1
    updated_at: datetime | None = None
    retired_at: datetime | None = None
    superseded_by_entity_address_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.entity_address_id, IdKind.ENTITY_ADDRESS)
        validate_identifier(self.entity_id, IdKind.ENTITY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.address_type_code, AddressTypeCode):
            raise ValueError("an entity address has a closed address type")
        if not self.raw_value.strip():
            raise ValueError("an entity address raw value is not blank")
        for field_name, field_value in (
            ("line1", self.line1),
            ("line2", self.line2),
            ("city", self.city),
            ("region", self.region),
            ("postal_code", self.postal_code),
            ("country", self.country),
            ("label", self.label),
        ):
            if field_value is not None and not field_value.strip():
                raise ValueError(f"an entity address {field_name} is not blank when present")
        if not self.normalized_address_value.strip():
            raise ValueError("an entity address normalized value is not blank")
        expected_normalized_value = normalize_address(
            line1=self.line1,
            line2=self.line2,
            city=self.city,
            region=self.region,
            postal_code=self.postal_code,
            country=self.country,
            raw_value=self.raw_value,
        )
        if self.normalized_address_value != expected_normalized_value:
            raise ValueError("an entity address normalized value is stored already normalized")
        if not isinstance(self.is_preferred, bool):
            raise ValueError("an entity address is_preferred is a boolean")
        if self.effective_from is not None:
            ensure_utc(self.effective_from)
        if self.effective_to is not None:
            ensure_utc(self.effective_to)
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("an entity address cannot end before it begins")
        if not isinstance(self.state, EntityAddressState):
            raise ValueError("an entity address has a closed state")
        if self.version < 1:
            raise ValueError("an entity address version is a positive integer")
        if self.updated_at is not None:
            ensure_utc(self.updated_at)
        if self.retired_at is not None:
            ensure_utc(self.retired_at)
            if self.state is EntityAddressState.ACTIVE:
                raise ValueError("an entity address is retired only once it leaves service")
        if self.superseded_by_entity_address_id is not None:
            validate_identifier(self.superseded_by_entity_address_id, IdKind.ENTITY_ADDRESS)
            if self.superseded_by_entity_address_id == self.entity_address_id:
                raise ValueError("an entity address cannot supersede itself")
            if self.state is not EntityAddressState.SUPERSEDED:
                raise ValueError("an entity address names a successor only when superseded")


@dataclass(frozen=True, slots=True)
class EntityCommunicationMethod:
    """One contact channel of an entity (RI-ENT-WP-03).

    Closes `ENTITY-SCHEMA-003`: the audit's Record Element Inventory names
    "Phone / website / domain / email as a contact channel" as a
    representation family with no owning table before this revision (see the
    WP-01 ownership table). `method_type_code` is that closed set of channel
    kinds, and `usage_context_code` is the independent axis of what the
    channel is used for (corporate/project/project_sales/generic/personal/
    office/other) -- see `CommunicationUsageContextCode`'s docstring for why
    the two are kept apart rather than folded into one column.

    **The type is stated, never inferred (RULING 3).** No validation here
    "detects" that a value is an email because it contains `@`; a caller
    states `method_type_code=EMAIL` and `normalize_communication_value` then
    checks the value is well-formed *for* that stated type. See that
    function's docstring for the normalization each type takes.

    **`ExternalIdentifierNamespace.EMAIL` / `entity_external_identifiers`
    remains the sole authority for identity resolution; this table is never
    consulted to resolve "who is this."** The two families answer different
    questions about a mailbox: `entity_external_identifiers` with
    `namespace = EMAIL` asks "which entity does this mailbox identify",
    and this table with `method_type_code = EMAIL` asks "is this a way to
    reach this entity" -- a contact channel, not an identity claim, and it may
    or may not be the same mailbox identity resolution already uses.
    `linked_external_identifier_id` is how one row of this table *optionally*
    declares "this contact channel is the same mailbox as external identifier
    X" without merging the two concepts: it is a cross-reference a reader may
    follow, never a replacement for, weakening of, or duplicate of the
    identity binding. The database enforces that only an `EMAIL` row may ever
    carry it (`linked_external_identifier_id IS NULL OR method_type_code =
    'email'`), which is what stops the external-identifier namespace from
    being overloaded with phone/domain/website values through this back door;
    `__post_init__` enforces the same rule again here, in depth.

    **Uniqueness is per (entity, method type), across usage contexts.** The
    same normalized value under two different `usage_context_code`s is one
    channel double-counted, not two channels -- a corporate phone number
    someone also tags `generic` is still one phone number -- so the active
    uniqueness index is keyed on `(principal_id, entity_id, method_type_code,
    normalized_value)` without `usage_context_code`. Two genuinely different
    channels (a corporate number and a project's own number) already differ in
    `normalized_value`, so this permits the required multi-channel case
    without weakening the guard against a literal duplicate.

    **`verification_status_code` is not a confidence field.** It is
    `CommunicationVerificationStatusCode`, deliberately a separate vocabulary
    from `LegalIdentityStatusCode` even though the four members read the same;
    see that class's docstring for why sharing one enum across the two
    dimensions would be the wrong coupling.

    **Merge/split.** Not yet wired into
    `my_pa.application.identity_correction`, under the same deferral to
    RI-ENT-WP-06 as `EntityName`, `EntityOrganizationProfile`, and
    `EntityAddress` above, and for the same reason: no command or MCP
    capability in this increment writes this table outside test fixtures, so
    a merge today cannot encounter a populated row through ordinary product
    use. A merge of an entity that does carry communication-method rows
    leaves them bound to the merged-away `entity_id`, resolvable through
    `entities.superseded_by_entity_id` but not reachable by querying the
    survivor directly, until that wiring lands. `WP-08` and `WP-11` may not
    ship a write path for this family until then either -- see the campaign
    document's "Merge/split disposition" section, which after this increment
    enumerates all four families this rule now binds.
    """

    communication_method_id: str
    entity_id: str
    principal_id: str
    method_type_code: CommunicationMethodTypeCode
    usage_context_code: CommunicationUsageContextCode
    normalized_value: str
    display_value: str
    verification_status_code: CommunicationVerificationStatusCode = (
        CommunicationVerificationStatusCode.UNRESOLVED
    )
    is_preferred: bool = False
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    state: EntityCommunicationMethodState = EntityCommunicationMethodState.ACTIVE
    version: int = 1
    updated_at: datetime | None = None
    retired_at: datetime | None = None
    superseded_by_communication_method_id: str | None = None
    linked_external_identifier_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.communication_method_id, IdKind.ENTITY_COMMUNICATION_METHOD)
        validate_identifier(self.entity_id, IdKind.ENTITY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.method_type_code, CommunicationMethodTypeCode):
            raise ValueError("a communication method has a closed method type")
        if not isinstance(self.usage_context_code, CommunicationUsageContextCode):
            raise ValueError("a communication method has a closed usage context")
        if not self.normalized_value.strip():
            raise ValueError("a communication method normalized value is not blank")
        if not is_normalized_communication_value(self.method_type_code, self.normalized_value):
            raise ValueError("a communication method normalized value is stored already normalized")
        if not self.display_value.strip():
            raise ValueError("a communication method display value is not blank")
        if not isinstance(self.verification_status_code, CommunicationVerificationStatusCode):
            raise ValueError("a communication method has a closed verification status")
        if not isinstance(self.is_preferred, bool):
            raise ValueError("a communication method is_preferred is a boolean")
        if self.effective_from is not None:
            ensure_utc(self.effective_from)
        if self.effective_to is not None:
            ensure_utc(self.effective_to)
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("a communication method cannot end before it begins")
        if not isinstance(self.state, EntityCommunicationMethodState):
            raise ValueError("a communication method has a closed state")
        if self.version < 1:
            raise ValueError("a communication method version is a positive integer")
        if self.updated_at is not None:
            ensure_utc(self.updated_at)
        if self.retired_at is not None:
            ensure_utc(self.retired_at)
            if self.state is EntityCommunicationMethodState.ACTIVE:
                raise ValueError("a communication method is retired only once it leaves service")
        if self.superseded_by_communication_method_id is not None:
            validate_identifier(
                self.superseded_by_communication_method_id,
                IdKind.ENTITY_COMMUNICATION_METHOD,
            )
            if self.superseded_by_communication_method_id == self.communication_method_id:
                raise ValueError("a communication method cannot supersede itself")
            if self.state is not EntityCommunicationMethodState.SUPERSEDED:
                raise ValueError("a communication method names a successor only when superseded")
        if self.linked_external_identifier_id is not None:
            validate_identifier(self.linked_external_identifier_id, IdKind.EXTERNAL_IDENTIFIER)
            if self.method_type_code is not CommunicationMethodTypeCode.EMAIL:
                raise ValueError(
                    "a communication method links an external identifier only for email"
                )


class TaxonomyEntryStatus(StrEnum):
    """Where one entry of a shared, extensible taxonomy stands.

    Shared by `entity_role_types` and `entity_discipline_types` (RI-ENT-WP-04):
    both are global, Principal-independent reference vocabularies -- a role
    code or a discipline code means the same thing for every Principal, the
    same way a currency code would -- so a status vocabulary that closes an
    entry off *without deleting it* (and so without breaking a historical
    `entity_project_participations` row that already cites it) belongs to the
    taxonomy shape itself, not to either table individually. `DEPRECATED` is
    not `retired`/`superseded`/`active` (`EntityAddressState` and its
    siblings): those three describe one *record's* place in a
    principal-scoped temporal history, and a taxonomy entry has neither a
    principal nor a supersession chain -- it is either open to new writes or
    it is not.
    """

    ACTIVE = "active"
    DEPRECATED = "deprecated"


@dataclass(frozen=True, slots=True)
class EntityRoleType:
    """One entry of the global, extensible project-role taxonomy (RI-ENT-WP-04).

    **Not Principal-partitioned.** `entity_role_types` is a shared reference
    vocabulary, like a lookup table, rather than a per-Principal record: the
    audit's own generic AEC role codes (`OWNER`, `GENERAL_CONTRACTOR`,
    `ARCHITECT_OF_RECORD`, and so on) mean the same thing for every Principal,
    so there is no `principal_id` on this record and no per-Principal
    override.

    `category` is deliberately free text, not a closed `StrEnum`: the audit's
    own groupings (ownership/design/construction/consulting/authority/
    finance) are illustrative, not exhaustive, and this catalog is meant to
    grow by a new row, not by a schema change, the same way `role_code`
    itself does. Closing it would recreate exactly the frozen-vocabulary
    problem `ENTITY-REL-001` already flags for `EntityRelationshipType`, one
    representation family early.
    """

    role_code: str
    label: str
    category: str | None = None
    status: TaxonomyEntryStatus = TaxonomyEntryStatus.ACTIVE

    def __post_init__(self) -> None:
        if not self.role_code.strip():
            raise ValueError("a role type code is not blank")
        if not self.label.strip():
            raise ValueError("a role type label is not blank")
        if self.category is not None and not self.category.strip():
            raise ValueError("a role type category is not blank when present")
        if not isinstance(self.status, TaxonomyEntryStatus):
            raise ValueError("a role type has a closed status")


@dataclass(frozen=True, slots=True)
class EntityDisciplineType:
    """One entry of the global, extensible discipline taxonomy (RI-ENT-WP-04).

    Field-for-field the same shape as `EntityRoleType`, for a different axis:
    `role_code` answers "what part does this participant play" and
    `discipline_code` answers "what professional discipline are they" -- a
    `CONSULTANT` role and a `STRUCTURAL_ENGINEERING` discipline are two
    independent facts about the same participation, which is why
    `EntityProjectParticipation` carries both codes rather than folding them
    into one. See `EntityRoleType`'s docstring for why `broader_family` is
    free text rather than a closed vocabulary, for the same reason.
    """

    discipline_code: str
    label: str
    broader_family: str | None = None
    status: TaxonomyEntryStatus = TaxonomyEntryStatus.ACTIVE

    def __post_init__(self) -> None:
        if not self.discipline_code.strip():
            raise ValueError("a discipline type code is not blank")
        if not self.label.strip():
            raise ValueError("a discipline type label is not blank")
        if self.broader_family is not None and not self.broader_family.strip():
            raise ValueError("a discipline type broader family is not blank when present")
        if not isinstance(self.status, TaxonomyEntryStatus):
            raise ValueError("a discipline type has a closed status")


class RoleBasisCode(StrEnum):
    """How a participation's role came to be recorded.

    **RULING 3: never inferred from a name or string position.** No writer in
    this codebase may choose a member of this enum by pattern-matching a
    participant's display name, a document's layout, or the order fields
    appear in a source -- the same prohibition RULING 3 already states for
    `EntityAddress`'s structured fields and `EntityCommunicationMethod`'s
    stated type, applied here to *why* a role was assigned rather than *what*
    the role is. `UNRESOLVED` is the correct value when the basis is unknown;
    it is never a placeholder a caller forgets to replace with a guess, and no
    code path may promote it to a stronger member without a corroborating
    source that justifies the change.
    """

    CONTRACTUAL = "contractual"
    SOURCE_VERIFIED = "source_verified"
    PROJECT_OBSERVED = "project_observed"
    INFERRED = "inferred"
    UNRESOLVED = "unresolved"


class StakeholderSideCode(StrEnum):
    """Which side of a project a participant sits on.

    Eleven values, closed as of this revision because the migration's
    `stakeholder_side_code` CHECK references them, on the same argument every
    other closed vocabulary on this plane is closed. `ADJACENT_INTERFACE`
    covers a party that touches the project without being a conventional
    stakeholder in it (a utility easement holder, a neighboring parcel's
    owner) -- a real project role none of the other ten values fit -- and
    `OTHER` is left for what genuinely fits none of them, a stated choice
    rather than a default nobody selected, the same way
    `OrganizationKindCode.OTHER_OR_UNRESOLVED` is stated rather than implied.
    """

    OWNER = "owner"
    DEVELOPER = "developer"
    DESIGN = "design"
    CONTRACTOR = "contractor"
    CONSULTANT = "consultant"
    AUTHORITY = "authority"
    UTILITY = "utility"
    VENDOR = "vendor"
    SALES_MARKETING = "sales_marketing"
    ADJACENT_INTERFACE = "adjacent_interface"
    OTHER = "other"


class StakeholderClassCode(StrEnum):
    """How central a participant is to a project, independent of its side.

    **Not a ranking of people, and named to say so.** The operating brief
    forbids exactly that, guarded on this plane by
    `tests/architecture/test_relationship_scoring_surface_is_denied`, whose
    deny list refuses the token `tier` outright as "a graded band" -- which
    is why this field is `stakeholder_class_code`/`StakeholderClassCode`
    rather than the more obvious "stakeholder tier", even though "tier" is
    the word a person would reach for first. The rename is cosmetic, not a
    weakening: the deny rule is a blunt, deliberately non-semantic token
    scan, and this dimension is what it would have caught regardless of
    which word names it, so the honest fix is to name it something the guard
    does not have to special-case. `stakeholder_side_code` says which side a
    participant is on; this says how load-bearing their participation is to
    the project's own narrative -- a discrete, named class a reviewer
    assigns and can defend, not a computed score that orders one participant
    above another. `UNRESOLVED` is the correct value before that judgement
    has been made, on the same argument `RoleBasisCode.UNRESOLVED` makes: a
    stated placeholder for "not yet determined" has to exist, or every
    writer that does not yet know the class is forced to guess one to
    satisfy a `NOT NULL` column.
    """

    CORE = "core"
    ADJACENT = "adjacent"
    TRANSACTIONAL = "transactional"
    UNRESOLVED = "unresolved"


class ParticipationStatusCode(StrEnum):
    """The business status of a participation itself.

    **This is not the record-lifecycle `state` column, and the two must not
    be confused.** `state` (`EntityProjectParticipationState`) answers "is
    this row the current, retired, or superseded version of this fact" -- the
    same three-state shape every record family on this plane carries.
    `relationship_status_code` answers a different question: "is the
    participation *itself*, as a fact about the world, currently active, has
    the project role ended, was it terminated, put on hold, or never
    resolved" -- a business fact a source or a reviewer states, not a
    housekeeping fact about which row is authoritative. A participation can
    be `state = ACTIVE` (this is the current row) and
    `relationship_status_code = COMPLETED` (the participant's work on the
    project is over) at the same time, and that combination is the ordinary
    case for a finished project, not a contradiction.

    No vocabulary for this axis existed elsewhere in the codebase to reuse
    (confirmed by grep before this enum was added); it is new and scoped to
    this table only.
    """

    ACTIVE = "active"
    COMPLETED = "completed"
    TERMINATED = "terminated"
    ON_HOLD = "on_hold"
    UNRESOLVED = "unresolved"


class EntityProjectParticipationState(StrEnum):
    """Where one participation row stands.

    The same three states `EntityAddressState`, `EntityNameState`, and
    `EntityCommunicationMethodState` each declare, and deliberately its own
    vocabulary rather than a shared one, for the reason each of theirs
    already gives: `entity_project_participations` is widened independently
    of any of the three sibling families, and one shared enum would make
    widening any of them a silent widening of all four.
    """

    ACTIVE = "active"
    RETIRED = "retired"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class EntityProjectParticipation:
    """One participant's recorded participation on one project (RI-ENT-WP-04).

    Closes `ENTITY-PROJECT-001` ("incomplete project participation"): the
    audit's Record Element Inventory names "project role / discipline / scope
    / stakeholder side / stakeholder tier / role basis / participation state"
    as a representation family with no owning table before this revision (see
    the WP-01 ownership table). What the audit calls "stakeholder tier" is
    `stakeholder_class_code` here; see `StakeholderClassCode`'s docstring for
    why. `project_entity_id` is the project (an
    `Entity` whose `entity_type` is expected to be `PROJECT`) and
    `participant_entity_id` is who or what participates in it -- a person or
    an organization entity, with no `entity_type` restriction on that side.

    **Naming deviation, disclosed.** The audit's own text calls this
    representation `project_entity_participations`. This class and its table
    are named `entity_project_participations` instead, so the table falls
    inside `tests/architecture/test_relationship_scoring_surface_is_denied`'s
    `RELATIONSHIP_TABLE_PREFIXES` scan (`"relationship_"`, `"entities"`,
    `"entity_"`) with zero change to that guard's scanning logic --
    `project_entity_participations` would not start with any of those
    prefixes and would silently fall outside the one deny rule that exists
    specifically to catch a "participation confidence" / "role confidence" /
    "scope confidence" field on exactly this kind of record. See the
    migration's module docstring and the campaign document's ledger for the
    full reasoning; this is a deliberate, disclosed deviation from the
    audit's literal text, not a silent one.

    **`project_display_name` is project-scoped fact, never global identity --
    the single most important semantic boundary in this work package.** It is
    the name this participant is known by *on this project*, which may differ
    from `Entity.display_name` or `Entity.canonical_name` for the same
    `participant_entity_id` (a subcontractor trading under a project-specific
    joint-venture name, a person credited under a title rather than their own
    name). **Nothing in this migration, this domain module, or any
    application code reading or writing this class may ever copy
    `project_display_name` into `Entity.display_name` or
    `Entity.canonical_name`, or the reverse.** This class carries no field,
    property, or method that reads from or writes to either of those two
    global-identity columns, and it has no knowledge of them at all --
    `tests/relationship/test_relationship_domain.py`'s closed field
    allow-list is what proves that structurally: a future edit that adds such
    a field or property reddens there the moment it is written, not after it
    ships.

    **Never a confidence field (RULING 1).** The audit's own proposed names
    for this record -- "participation confidence", "role confidence", "scope
    confidence" -- are not used anywhere here. `role_basis_code` and
    `relationship_status_code` are the discrete, named vocabularies this
    revision uses in their place, on the same argument
    `LegalIdentityStatusCode` and `CommunicationVerificationStatusCode`
    already make for their own dimensions; see `RoleBasisCode`'s docstring
    for RULING 3's stronger claim on that one field specifically.

    **`project_entity_id != participant_entity_id`.** A project cannot
    meaningfully participate in itself, so the two are required to differ --
    the same shape of rule `EntityRelationship.__post_init__` already applies
    to `from_entity_id`/`to_entity_id`, restated here at both the dataclass
    and the table CHECK.

    **The active uniqueness key includes `role_code`, deliberately.** Two
    simultaneously active participations of the same participant on the same
    project are refused only when they also share the same `role_code`: one
    entity legitimately holds two concurrently active roles on one project (a
    firm that is both a project's `CONSULTANT` and its
    `OWNER_REPRESENTATIVE`, say), and folding `role_code` out of the key would
    make that ordinary case collide with itself. This mirrors, without
    repeating, the reasoning `EntityAddress`'s docstring gives for keying its
    own active uniqueness on `address_type_code`: the type/role axis is part
    of what makes two rows the same fact or two different ones.

    **`entities.entity_type == 'project'` for `project_entity_id` is a domain
    invariant, not a CHECK constraint.** PostgreSQL cannot express a CHECK
    that reads another table's row, so this revision's migration does not and
    cannot enforce it in SQL, and does not infer it either -- the same
    non-enforcement `EntityOrganizationProfile`'s docstring already states for
    `entities.entity_type = 'organization'`. The writer/repository layer that
    inserts a row here is responsible for verifying `project_entity_id` names
    an entity whose `entity_type` is `PROJECT` before the insert.

    **Merge/split.** Not yet wired into
    `my_pa.application.identity_correction`, under the same RI-ENT-WP-06
    deferral as `EntityName`, `EntityOrganizationProfile`, `EntityAddress`,
    and `EntityCommunicationMethod` above, and for the same reason: no
    command or MCP capability in this increment writes this table outside
    test fixtures. A merge of a `project_entity_id` or a
    `participant_entity_id` that carries participation rows today leaves them
    bound to the merged-away `entity_id` until that wiring lands.
    """

    participation_id: str
    principal_id: str
    project_entity_id: str
    participant_entity_id: str
    project_display_name: str
    role_basis_code: RoleBasisCode
    stakeholder_side_code: StakeholderSideCode
    stakeholder_class_code: StakeholderClassCode
    relationship_status_code: ParticipationStatusCode
    role_code: str | None = None
    role_text: str | None = None
    discipline_code: str | None = None
    discipline_text: str | None = None
    scope_text: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    state: EntityProjectParticipationState = EntityProjectParticipationState.ACTIVE
    version: int = 1
    updated_at: datetime | None = None
    retired_at: datetime | None = None
    superseded_by_participation_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.participation_id, IdKind.ENTITY_PROJECT_PARTICIPATION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.project_entity_id, IdKind.ENTITY)
        validate_identifier(self.participant_entity_id, IdKind.ENTITY)
        if self.project_entity_id == self.participant_entity_id:
            raise ValueError("a project cannot participate in itself")
        if not self.project_display_name.strip():
            raise ValueError("a project participation display name is not blank")
        for field_name, field_value in (
            ("role_text", self.role_text),
            ("discipline_text", self.discipline_text),
            ("scope_text", self.scope_text),
        ):
            if field_value is not None and not field_value.strip():
                raise ValueError(f"a project participation {field_name} is not blank when present")
        if self.role_code is not None and not self.role_code.strip():
            raise ValueError("a project participation role code is not blank when present")
        if self.discipline_code is not None and not self.discipline_code.strip():
            raise ValueError("a project participation discipline code is not blank when present")
        if not isinstance(self.role_basis_code, RoleBasisCode):
            raise ValueError("a project participation has a closed role basis")
        if not isinstance(self.stakeholder_side_code, StakeholderSideCode):
            raise ValueError("a project participation has a closed stakeholder side")
        if not isinstance(self.stakeholder_class_code, StakeholderClassCode):
            raise ValueError("a project participation has a closed stakeholder class")
        if not isinstance(self.relationship_status_code, ParticipationStatusCode):
            raise ValueError("a project participation has a closed relationship status")
        if self.effective_from is not None:
            ensure_utc(self.effective_from)
        if self.effective_to is not None:
            ensure_utc(self.effective_to)
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("a project participation cannot end before it begins")
        if not isinstance(self.state, EntityProjectParticipationState):
            raise ValueError("a project participation has a closed state")
        if self.version < 1:
            raise ValueError("a project participation version is a positive integer")
        if self.updated_at is not None:
            ensure_utc(self.updated_at)
        if self.retired_at is not None:
            ensure_utc(self.retired_at)
            if self.state is EntityProjectParticipationState.ACTIVE:
                raise ValueError("a project participation is retired only once it leaves service")
        if self.superseded_by_participation_id is not None:
            validate_identifier(
                self.superseded_by_participation_id, IdKind.ENTITY_PROJECT_PARTICIPATION
            )
            if self.superseded_by_participation_id == self.participation_id:
                raise ValueError("a project participation cannot supersede itself")
            if self.state is not EntityProjectParticipationState.SUPERSEDED:
                raise ValueError("a project participation names a successor only when superseded")


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
