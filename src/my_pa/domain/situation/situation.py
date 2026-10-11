"""The R5 continuity surface: Situation, Frame, Trace, Project, and PulseItem.

These are the durable objects the daily-orientation, project-continuity, and
briefing workflows (WF-01, WF-12, WF-10, WF-15) operate over. Each is defined by
the canonical object model:

- **Situation** — "purposeful operational context referencing one or more
  objects; does not own them." It carries `object_refs` (opaque references to
  the objects it is about) but never owns those objects, so closing a Situation
  never deletes what it referenced (WF-18).
- **Frame** — "current/saved view of what matters, evidence, alternatives,
  obligations, uncertainty, and next authority point." A Frame belongs to one
  Situation and is the reviewer's working view within it.
- **Trace** — "derived source-linked temporal reconstruction; not source
  evidence." A Trace reconstructs one object over a time range from the source
  events it cites and exposes the gaps it could not fill (WF-15). It is a
  projection and is never authoritative.
- **Project** — "durable work context with participants, sources, Situations,
  ..." A Project groups Situations and carries its participant set.
- **PulseItem** — "derived attention recommendation with reason, consequence,
  evidence, uncertainty, next step." A Pulse item is generated only from
  *accepted* state — `accepted_only` is structurally pinned true (the migration
  CHECK `pulse_reads_only_accepted_records`) so the WP-06 criterion "Today/Pulse
  read only accepted records" cannot be weakened by a writer.

**Every object carries `principal_id`.** These surfaces are read by Today/Pulse
and by the relationship/project briefing, all of which must be strictly
principal-scoped (invariant 11: `principal_id` is a mandatory predicate on every
read path). A Frame carries `principal_id` explicitly even though it inherits
its Situation's Principal, so a query can enforce the partition without joining
back to the parent — the same reasoning the WP-05 review partition used for span
tables.

`RelationshipEvent` and `RelationshipEventType` are re-exported from
`domain.relationship.event`; they are relationship-domain facts, not continuity
views, but a caller building a Project/Relationship timeline reaches them
alongside these objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "PROJECT_VALUE_LIMIT",
    "TYPE_TO_SECTOR",
    "Frame",
    "FrameState",
    "Project",
    "ProjectEntityLink",
    "ProjectEntityLinkageState",
    "ProjectSector",
    "ProjectState",
    "ProjectType",
    "PulseItem",
    "PulseItemType",
    "PulseReasonCode",
    "Situation",
    "SituationState",
    "Trace",
    "is_storable_project_value",
]


class SituationState(StrEnum):
    """Where a Situation is in its lifecycle. Frozen in the `state` CHECK."""

    OPEN = "open"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class FrameState(StrEnum):
    """Whether a Frame is the current working view, a saved one, or archived."""

    CURRENT = "current"
    SAVED = "saved"
    ARCHIVED = "archived"


class ProjectState(StrEnum):
    """Whether a Project is active, paused, or closed."""

    ACTIVE = "active"
    ON_HOLD = "on_hold"
    CLOSED = "closed"


class ProjectSector(StrEnum):
    """The 9 sectors of `Construction_Project_Taxonomy_v1.csv`.

    Values are derived snake_case slugs of the CSV's own `Sector` column, not
    retyped by hand, so they cannot silently diverge from the source of
    record. `ProjectType` membership (below) is the finer-grained taxonomy
    level; `TYPE_TO_SECTOR` is the one place the two are tied together.
    """

    HOUSING_AND_RESIDENTIAL = "housing_and_residential"
    HOSPITALITY_AND_COMMERCIAL = "hospitality_and_commercial"
    HEALTHCARE_AND_LIFE_SCIENCES = "healthcare_and_life_sciences"
    EDUCATION_CIVIC_AND_COMMUNITY = "education_civic_and_community"
    INDUSTRIAL_LOGISTICS_AND_TECHNOLOGY = "industrial_logistics_and_technology"
    RECREATION_AND_ENTERTAINMENT = "recreation_and_entertainment"
    TRANSPORTATION_AND_MOBILITY = "transportation_and_mobility"
    UTILITIES_ENERGY_AND_ENVIRONMENTAL = "utilities_energy_and_environmental"
    LAND_RESOURCE_AND_SPECIALTY = "land_resource_and_specialty"


class ProjectType(StrEnum):
    """The 42 project types of `Construction_Project_Taxonomy_v1.csv`.

    Values are derived snake_case slugs of the CSV's own `Project Type`
    column; the source `Type ID` code is kept only as a trailing comment for
    traceability back to the v1 taxonomy, never as the stored/wire value —
    this file's enums are always human-legible words, never opaque codes.
    """

    SINGLE_FAMILY_HOUSING = "single_family_housing"  # T01
    MULTIFAMILY_HOUSING = "multifamily_housing"  # T02
    SENIOR_LIVING_AND_RESIDENTIAL_CARE = "senior_living_and_residential_care"  # T03
    STUDENT_STAFF_AND_GROUP_HOUSING = "student_staff_and_group_housing"  # T04
    TRANSITIONAL_SUPPORTIVE_AND_EMERGENCY_HOUSING = (  # T05
        "transitional_supportive_and_emergency_housing"
    )
    HOTELS_RESORTS_AND_LODGING = "hotels_resorts_and_lodging"  # T06
    RESTAURANTS_AND_FOODSERVICE = "restaurants_and_foodservice"  # T07
    RETAIL_SHOPPING_AND_CONSUMER_SERVICES = "retail_shopping_and_consumer_services"  # T08
    OFFICE_AND_WORKPLACE = "office_and_workplace"  # T09
    AUTOMOTIVE_AND_CONSUMER_MOBILITY_SERVICES = "automotive_and_consumer_mobility_services"  # T10
    MIXED_USE_BUILDINGS_AND_DISTRICTS = "mixed_use_buildings_and_districts"  # T11
    ACUTE_CARE_AND_HOSPITALS = "acute_care_and_hospitals"  # T12
    OUTPATIENT_AND_SPECIALTY_HEALTHCARE = "outpatient_and_specialty_healthcare"  # T13
    LIFE_SCIENCES_AND_LABORATORY_FACILITIES = "life_sciences_and_laboratory_facilities"  # T14
    EARLY_CHILDHOOD_AND_K_12_SCHOOLS = "early_childhood_and_k_12_schools"  # T15
    HIGHER_EDUCATION_AND_ACADEMIC_FACILITIES = "higher_education_and_academic_facilities"  # T16
    GOVERNMENT_AND_CIVIC_BUILDINGS = "government_and_civic_buildings"  # T17
    PUBLIC_SAFETY_COURTS_AND_CORRECTIONS = "public_safety_courts_and_corrections"  # T18
    DEFENSE_AND_MILITARY_FACILITIES = "defense_and_military_facilities"  # T19
    CULTURE_PERFORMING_ARTS_AND_RELIGIOUS_FACILITIES = (  # T20
        "culture_performing_arts_and_religious_facilities"
    )
    SOCIAL_SERVICES_AND_COMMUNITY_FACILITIES = "social_services_and_community_facilities"  # T21
    INDUSTRIAL_MANUFACTURING_AND_PROCESSING = "industrial_manufacturing_and_processing"  # T22
    WAREHOUSING_LOGISTICS_AND_COLD_CHAIN = "warehousing_logistics_and_cold_chain"  # T23
    DATA_CENTERS_AND_TELECOMMUNICATIONS = "data_centers_and_telecommunications"  # T24
    AGRICULTURAL_HORTICULTURAL_AND_AQUACULTURE_FACILITIES = (  # T25
        "agricultural_horticultural_and_aquaculture_facilities"
    )
    SPORTS_RECREATION_AND_WELLNESS_FACILITIES = "sports_recreation_and_wellness_facilities"  # T26
    ENTERTAINMENT_GAMING_AND_ATTRACTIONS = "entertainment_gaming_and_attractions"  # T27
    PARKS_LANDSCAPE_AND_PUBLIC_REALM = "parks_landscape_and_public_realm"  # T28
    ROADS_BRIDGES_AND_TUNNELS = "roads_bridges_and_tunnels"  # T29
    RAIL_BUS_AND_PUBLIC_TRANSIT = "rail_bus_and_public_transit"  # T30
    AVIATION_AND_SPACEPORT_INFRASTRUCTURE = "aviation_and_spaceport_infrastructure"  # T31
    MARINE_PORT_AND_COASTAL_TRANSPORTATION = "marine_port_and_coastal_transportation"  # T32
    PARKING_AND_FLEET_INFRASTRUCTURE = "parking_and_fleet_infrastructure"  # T33
    WATER_SUPPLY_AND_TREATMENT = "water_supply_and_treatment"  # T34
    WASTEWATER_AND_SOLID_WASTE = "wastewater_and_solid_waste"  # T35
    STORMWATER_FLOOD_CONTROL_AND_COASTAL_PROTECTION = (  # T36
        "stormwater_flood_control_and_coastal_protection"
    )
    POWER_GENERATION_AND_ENERGY_STORAGE = "power_generation_and_energy_storage"  # T37
    POWER_FUEL_AND_UTILITY_NETWORKS = "power_fuel_and_utility_networks"  # T38
    ENVIRONMENTAL_REMEDIATION_AND_ECOSYSTEM_RESTORATION = (  # T39
        "environmental_remediation_and_ecosystem_restoration"
    )
    LAND_DEVELOPMENT_ENABLING_AND_CIVIL_SITEWORK = (  # T40
        "land_development_enabling_and_civil_sitework"
    )
    EXTRACTIVE_AND_MINERAL_RESOURCES_FACILITIES = (  # T41
        "extractive_and_mineral_resources_facilities"
    )
    SPECIALTY_CONSTRUCTION_SCOPES_AND_BUILDING_RENEWAL = (  # T42
        "specialty_construction_scopes_and_building_renewal"
    )


#: The taxonomy's 1-sector-per-type rule, as the one place it is stated.
#: Checked in `Project.__post_init__` (and redundantly, for a classified
#: refusal, in `CreateProject`/`UpdateProject.__post_init__`) rather than as a
#: duplicated 42-branch DB CHECK, so the taxonomy is never stated twice able
#: to disagree with itself or with a future v2 CSV.
TYPE_TO_SECTOR: Final[MappingProxyType[ProjectType, ProjectSector]] = MappingProxyType(
    {
        ProjectType.SINGLE_FAMILY_HOUSING: ProjectSector.HOUSING_AND_RESIDENTIAL,
        ProjectType.MULTIFAMILY_HOUSING: ProjectSector.HOUSING_AND_RESIDENTIAL,
        ProjectType.SENIOR_LIVING_AND_RESIDENTIAL_CARE: ProjectSector.HOUSING_AND_RESIDENTIAL,
        ProjectType.STUDENT_STAFF_AND_GROUP_HOUSING: ProjectSector.HOUSING_AND_RESIDENTIAL,
        ProjectType.TRANSITIONAL_SUPPORTIVE_AND_EMERGENCY_HOUSING: (
            ProjectSector.HOUSING_AND_RESIDENTIAL
        ),
        ProjectType.HOTELS_RESORTS_AND_LODGING: ProjectSector.HOSPITALITY_AND_COMMERCIAL,
        ProjectType.RESTAURANTS_AND_FOODSERVICE: ProjectSector.HOSPITALITY_AND_COMMERCIAL,
        ProjectType.RETAIL_SHOPPING_AND_CONSUMER_SERVICES: ProjectSector.HOSPITALITY_AND_COMMERCIAL,
        ProjectType.OFFICE_AND_WORKPLACE: ProjectSector.HOSPITALITY_AND_COMMERCIAL,
        ProjectType.AUTOMOTIVE_AND_CONSUMER_MOBILITY_SERVICES: (
            ProjectSector.HOSPITALITY_AND_COMMERCIAL
        ),
        ProjectType.MIXED_USE_BUILDINGS_AND_DISTRICTS: ProjectSector.HOSPITALITY_AND_COMMERCIAL,
        ProjectType.ACUTE_CARE_AND_HOSPITALS: ProjectSector.HEALTHCARE_AND_LIFE_SCIENCES,
        ProjectType.OUTPATIENT_AND_SPECIALTY_HEALTHCARE: ProjectSector.HEALTHCARE_AND_LIFE_SCIENCES,
        ProjectType.LIFE_SCIENCES_AND_LABORATORY_FACILITIES: (
            ProjectSector.HEALTHCARE_AND_LIFE_SCIENCES
        ),
        ProjectType.EARLY_CHILDHOOD_AND_K_12_SCHOOLS: ProjectSector.EDUCATION_CIVIC_AND_COMMUNITY,
        ProjectType.HIGHER_EDUCATION_AND_ACADEMIC_FACILITIES: (
            ProjectSector.EDUCATION_CIVIC_AND_COMMUNITY
        ),
        ProjectType.GOVERNMENT_AND_CIVIC_BUILDINGS: ProjectSector.EDUCATION_CIVIC_AND_COMMUNITY,
        ProjectType.PUBLIC_SAFETY_COURTS_AND_CORRECTIONS: (
            ProjectSector.EDUCATION_CIVIC_AND_COMMUNITY
        ),
        ProjectType.DEFENSE_AND_MILITARY_FACILITIES: ProjectSector.EDUCATION_CIVIC_AND_COMMUNITY,
        ProjectType.CULTURE_PERFORMING_ARTS_AND_RELIGIOUS_FACILITIES: (
            ProjectSector.EDUCATION_CIVIC_AND_COMMUNITY
        ),
        ProjectType.SOCIAL_SERVICES_AND_COMMUNITY_FACILITIES: (
            ProjectSector.EDUCATION_CIVIC_AND_COMMUNITY
        ),
        ProjectType.INDUSTRIAL_MANUFACTURING_AND_PROCESSING: (
            ProjectSector.INDUSTRIAL_LOGISTICS_AND_TECHNOLOGY
        ),
        ProjectType.WAREHOUSING_LOGISTICS_AND_COLD_CHAIN: (
            ProjectSector.INDUSTRIAL_LOGISTICS_AND_TECHNOLOGY
        ),
        ProjectType.DATA_CENTERS_AND_TELECOMMUNICATIONS: (
            ProjectSector.INDUSTRIAL_LOGISTICS_AND_TECHNOLOGY
        ),
        ProjectType.AGRICULTURAL_HORTICULTURAL_AND_AQUACULTURE_FACILITIES: (
            ProjectSector.INDUSTRIAL_LOGISTICS_AND_TECHNOLOGY
        ),
        ProjectType.SPORTS_RECREATION_AND_WELLNESS_FACILITIES: (
            ProjectSector.RECREATION_AND_ENTERTAINMENT
        ),
        ProjectType.ENTERTAINMENT_GAMING_AND_ATTRACTIONS: (
            ProjectSector.RECREATION_AND_ENTERTAINMENT
        ),
        ProjectType.PARKS_LANDSCAPE_AND_PUBLIC_REALM: ProjectSector.RECREATION_AND_ENTERTAINMENT,
        ProjectType.ROADS_BRIDGES_AND_TUNNELS: ProjectSector.TRANSPORTATION_AND_MOBILITY,
        ProjectType.RAIL_BUS_AND_PUBLIC_TRANSIT: ProjectSector.TRANSPORTATION_AND_MOBILITY,
        ProjectType.AVIATION_AND_SPACEPORT_INFRASTRUCTURE: (
            ProjectSector.TRANSPORTATION_AND_MOBILITY
        ),
        ProjectType.MARINE_PORT_AND_COASTAL_TRANSPORTATION: (
            ProjectSector.TRANSPORTATION_AND_MOBILITY
        ),
        ProjectType.PARKING_AND_FLEET_INFRASTRUCTURE: ProjectSector.TRANSPORTATION_AND_MOBILITY,
        ProjectType.WATER_SUPPLY_AND_TREATMENT: ProjectSector.UTILITIES_ENERGY_AND_ENVIRONMENTAL,
        ProjectType.WASTEWATER_AND_SOLID_WASTE: ProjectSector.UTILITIES_ENERGY_AND_ENVIRONMENTAL,
        ProjectType.STORMWATER_FLOOD_CONTROL_AND_COASTAL_PROTECTION: (
            ProjectSector.UTILITIES_ENERGY_AND_ENVIRONMENTAL
        ),
        ProjectType.POWER_GENERATION_AND_ENERGY_STORAGE: (
            ProjectSector.UTILITIES_ENERGY_AND_ENVIRONMENTAL
        ),
        ProjectType.POWER_FUEL_AND_UTILITY_NETWORKS: (
            ProjectSector.UTILITIES_ENERGY_AND_ENVIRONMENTAL
        ),
        ProjectType.ENVIRONMENTAL_REMEDIATION_AND_ECOSYSTEM_RESTORATION: (
            ProjectSector.UTILITIES_ENERGY_AND_ENVIRONMENTAL
        ),
        ProjectType.LAND_DEVELOPMENT_ENABLING_AND_CIVIL_SITEWORK: (
            ProjectSector.LAND_RESOURCE_AND_SPECIALTY
        ),
        ProjectType.EXTRACTIVE_AND_MINERAL_RESOURCES_FACILITIES: (
            ProjectSector.LAND_RESOURCE_AND_SPECIALTY
        ),
        ProjectType.SPECIALTY_CONSTRUCTION_SCOPES_AND_BUILDING_RENEWAL: (
            ProjectSector.LAND_RESOURCE_AND_SPECIALTY
        ),
    }
)

#: Exclusive upper bound of `knowledge.projects.value`, a `numeric(14, 2)`.
PROJECT_VALUE_LIMIT: Final = Decimal(10) ** 12


def is_storable_project_value(value: object) -> bool:
    """True when `value` fits `numeric(14, 2)` exactly, so the stored amount is the one given."""
    return (
        isinstance(value, Decimal)
        and value.is_finite()
        and not value.is_signed()
        and value < PROJECT_VALUE_LIMIT
        and int(value.as_tuple().exponent) >= -2
    )


class ProjectEntityLinkageState(StrEnum):
    """How a Continuity Project relates to a project-type Entity.

    `bound` is a minted or later-resolved identity. The two unresolved states
    are durable backfill outcomes: missing (no candidate) and ambiguous (more
    than one candidate). Neither unresolved state stores an entity id, and
    neither is produced by matching on name.
    """

    BOUND = "bound"
    UNRESOLVED_MISSING = "unresolved_missing"
    UNRESOLVED_AMBIGUOUS = "unresolved_ambiguous"


class PulseItemType(StrEnum):
    """What kind of accepted record a Pulse item points at.

    Every member names a record class that only exists once *accepted*, which is
    the type-level half of the `accepted_only` gate: a Pulse item can only be
    about a commitment, decision, task, observation, relationship event, or
    situation that a human has already promoted.
    """

    COMMITMENT = "commitment"
    DECISION = "decision"
    TASK = "task"
    OBSERVATION = "observation"
    RELATIONSHIP_EVENT = "relationship_event"
    SITUATION = "situation"


class PulseReasonCode(StrEnum):
    """Why an item is on the Pulse *now*, from a closed vocabulary (WP-11).

    **This is the field that separates a Pulse from an activity feed.** A feed
    surfaces an item because something happened to it; a Pulse surfaces an item
    because a named, checkable condition holds about it right now. Every member
    here names such a condition, and each one is computed from evidence the
    reader can go and look at — a due moment that has passed, a due moment that
    is close, a decision waiting on a named authority point, an obligation on a
    Situation's current Frame that is still unmet.

    Closed, and closed in the schema too
    (`knowledge.pulse_items.a_pulse_reason_code_is_known`), because an open
    vocabulary would let "recently updated" be written here and the distinction
    would be gone in one commit. There is deliberately no member meaning
    "recent", "new", "active", or "changed": recency is not a reason, and the
    absence of a member for it is what makes that a structural claim rather than
    a stylistic one.
    """

    COMMITMENT_OVERDUE = "commitment_overdue"
    COMMITMENT_DUE_SOON = "commitment_due_soon"
    TASK_OVERDUE = "task_overdue"
    TASK_DUE_SOON = "task_due_soon"
    DECISION_AWAITING_AUTHORITY = "decision_awaiting_authority"
    SITUATION_OBLIGATION_UNMET = "situation_obligation_unmet"


@dataclass(frozen=True, slots=True)
class Situation:
    """A purposeful operational context that references objects but owns none.

    `object_refs` are opaque references the Situation is *about*; the Situation
    never owns them, so closing it (recording `outcome` and `closed_at`) leaves
    every referenced object intact. The closed-state/closed-time pairing mirrors
    the migration CHECK `a_closed_situation_records_when_it_closed`: a Situation
    is closed exactly when it records when it closed.
    """

    situation_id: str
    principal_id: str
    title: str
    state: SituationState
    opened_at: datetime
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    object_refs: tuple[str, ...] = ()
    closed_at: datetime | None = None
    outcome: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.situation_id, IdKind.SITUATION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not self.title.strip():
            raise ValueError("a situation carries a non-blank title")
        if not isinstance(self.state, SituationState):
            raise ValueError("a situation names one lifecycle state")
        ensure_utc(self.opened_at)
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)
        if self.closed_at is not None:
            ensure_utc(self.closed_at)
        if (self.state is SituationState.CLOSED) is not (self.closed_at is not None):
            raise ValueError("a closed situation records when it closed, and only then")


@dataclass(frozen=True, slots=True)
class Frame:
    """The current or saved view within one Situation of what matters.

    Carries `principal_id` explicitly so the partition can be enforced without
    joining back to the parent Situation, even though it inherits that
    Situation's Principal.
    """

    frame_id: str
    situation_id: str
    principal_id: str
    label: str
    state: FrameState
    created_at: datetime
    updated_at: datetime
    evidence_refs: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    obligations: tuple[str, ...] = ()
    uncertainty: str | None = None
    next_authority: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.frame_id, IdKind.FRAME)
        validate_identifier(self.situation_id, IdKind.SITUATION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not self.label.strip():
            raise ValueError("a frame carries a non-blank label")
        if not isinstance(self.state, FrameState):
            raise ValueError("a frame names one state")
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)


@dataclass(frozen=True, slots=True)
class Trace:
    """A derived, source-linked temporal reconstruction of one object.

    A Trace is a projection, never source evidence: `source_events` records the
    events it reconstructed and `gaps` records the intervals it could not fill,
    so an incomplete reconstruction is legible as incomplete rather than passed
    off as whole. The range, when both ends are present, ends no earlier than it
    starts — the migration CHECK `a_trace_range_ends_after_it_starts`.
    """

    trace_id: str
    principal_id: str
    object_id: str
    object_type: str
    created_at: datetime
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None
    source_events: tuple[dict[str, object], ...] = ()
    gaps: tuple[dict[str, object], ...] = ()

    def __post_init__(self) -> None:
        validate_identifier(self.trace_id, IdKind.TRACE)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not self.object_id.strip():
            raise ValueError("a trace names the object it reconstructs")
        if not self.object_type.strip():
            raise ValueError("a trace records the kind of object it reconstructs")
        ensure_utc(self.created_at)
        if self.time_range_start is not None:
            ensure_utc(self.time_range_start)
        if self.time_range_end is not None:
            ensure_utc(self.time_range_end)
        if (
            self.time_range_start is not None
            and self.time_range_end is not None
            and self.time_range_end < self.time_range_start
        ):
            raise ValueError("a trace range ends no earlier than it starts")


@dataclass(frozen=True, slots=True)
class Project:
    """A durable work context with participants that groups Situations.

    The closed-state/closed-time pairing mirrors the migration CHECK
    `a_closed_project_records_when_it_closed`.
    """

    project_id: str
    principal_id: str
    name: str
    state: ProjectState
    opened_at: datetime
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    participants: tuple[str, ...] = ()
    closed_at: datetime | None = None
    version: int = 1
    aliases: tuple[str, ...] = ()
    project_number: str | None = None
    sector: ProjectSector | None = None
    type: ProjectType | None = None
    address: str | None = None
    city: str | None = None
    county: str | None = None
    address_state: str | None = None
    zip: str | None = None
    value: Decimal | None = None
    scheduled_start: date | None = None
    contract_start: date | None = None
    actual_start: date | None = None
    scheduled_finish: date | None = None
    contract_finish: date | None = None
    actual_finish: date | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.project_id, IdKind.PROJECT)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not self.name.strip():
            raise ValueError("a project carries a non-blank name")
        if not isinstance(self.state, ProjectState):
            raise ValueError("a project names one lifecycle state")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("a project version is an integer of at least one")
        ensure_utc(self.opened_at)
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)
        if self.closed_at is not None:
            ensure_utc(self.closed_at)
        if (self.state is ProjectState.CLOSED) is not (self.closed_at is not None):
            raise ValueError("a closed project records when it closed, and only then")
        if self.project_number is not None:
            if not self.project_number.strip():
                raise ValueError("a project number, if present, is non-blank")
            if len(self.project_number) > 64:
                raise ValueError("a project number is at most 64 characters")
        for field_name, bound in (
            ("address", 256),
            ("city", 128),
            ("county", 128),
            ("address_state", 128),
            ("zip", 32),
        ):
            value = getattr(self, field_name)
            if value is not None:
                if not value.strip():
                    raise ValueError(f"a project {field_name}, if present, is non-blank")
                if len(value) > bound:
                    raise ValueError(f"a project {field_name} is at most {bound} characters")
        if self.value is not None and not is_storable_project_value(self.value):
            raise ValueError("a project value is a finite, non-negative amount in whole cents")
        if (self.sector is None) != (self.type is None):
            raise ValueError("a project sector and type are set together, or neither")
        if self.sector is not None:
            if not isinstance(self.sector, ProjectSector):
                raise ValueError("a project names one known sector")
            if not isinstance(self.type, ProjectType):
                raise ValueError("a project names one known type")
            if TYPE_TO_SECTOR[self.type] is not self.sector:
                raise ValueError(
                    f"project type {self.type.value} belongs to sector "
                    f"{TYPE_TO_SECTOR[self.type].value}, not {self.sector.value}"
                )
        for field_name in (
            "scheduled_start",
            "contract_start",
            "actual_start",
            "scheduled_finish",
            "contract_finish",
            "actual_finish",
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, date):
                raise ValueError(f"a project {field_name} is a date")
            if isinstance(value, datetime):
                raise ValueError(f"a project {field_name} is a date, not a datetime")


@dataclass(frozen=True, slots=True)
class ProjectEntityLink:
    """One Continuity Project's durable binding to a project-type Entity.

    The primary key is the Continuity Project itself `(principal_id, project_id)`.
    A bound row names exactly one Entity; an unresolved row names none. The
    pairing is the domain half of the schema CHECK
    `a_bound_project_entity_link_names_its_entity`.
    """

    principal_id: str
    project_id: str
    linkage_state: ProjectEntityLinkageState
    created_at: datetime
    updated_at: datetime
    project_entity_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.project_id, IdKind.PROJECT)
        if not isinstance(self.linkage_state, ProjectEntityLinkageState):
            raise ValueError("a project-entity link names one linkage state")
        if (self.linkage_state is ProjectEntityLinkageState.BOUND) is not (
            self.project_entity_id is not None
        ):
            raise ValueError("a bound project-entity link names its entity, and only then")
        if self.project_entity_id is not None:
            validate_identifier(self.project_entity_id, IdKind.ENTITY)
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)


@dataclass(frozen=True, slots=True)
class PulseItem:
    """A derived attention recommendation generated only from accepted state.

    `accepted_only` is pinned true and validated as such: it is the domain half
    of the migration CHECK `pulse_reads_only_accepted_records`. The invariant is
    that a Pulse item is *derived from accepted records only* — never from a
    proposal — so `priority` orders attention among accepted facts and nothing
    here can surface an unaccepted one.

    **`reason_code` and `basis_refs` are mandatory (WP-11), and that is what
    makes "not an activity feed" a property rather than a promise.**
    `reason_code` is the closed why-now vocabulary; `basis_refs` are the records
    a reader can open to check the reason, and an empty basis is refused here and
    by the schema CHECK `a_pulse_item_carries_an_evidentiary_basis`. An item that
    is merely recent has no reason code to write and no basis to cite, so it
    cannot be constructed and cannot be stored.

    `attention_rank` is a bounded urgency rank on the *item*. Nothing here ranks,
    scores, or characterises a person: `§22` forbids it, and there is no field
    one could go in.
    """

    pulse_id: str
    principal_id: str
    item_type: PulseItemType
    item_ref: str
    reason: str
    reason_code: PulseReasonCode
    basis_refs: tuple[str, ...]
    generated_at: datetime
    consequence: str | None = None
    next_step: str | None = None
    attention_rank: int = 5
    accepted_only: bool = field(default=True)
    dismissed_at: datetime | None = None
    subject_title: str | None = None
    subject_state: str | None = None
    subject_version: int | None = None
    subject_priority: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.pulse_id, IdKind.PULSE)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.item_type, PulseItemType):
            raise ValueError("a pulse item names one item type")
        if not self.item_ref.strip():
            raise ValueError("a pulse item points at one record")
        if not self.reason.strip():
            raise ValueError("a pulse item states why it is surfaced")
        if not isinstance(self.reason_code, PulseReasonCode):
            raise ValueError("a pulse item names one why-now reason code")
        if not self.basis_refs or any(not str(ref).strip() for ref in self.basis_refs):
            raise ValueError("a pulse item cites at least one non-blank evidentiary basis")
        if isinstance(self.attention_rank, bool) or not isinstance(self.attention_rank, int):
            raise ValueError("attention_rank is an integer")
        if not 1 <= self.attention_rank <= 10:
            raise ValueError("attention_rank is between one and ten")
        if self.accepted_only is not True:
            raise ValueError("a pulse item reads only accepted records")
        ensure_utc(self.generated_at)
        if self.dismissed_at is not None:
            ensure_utc(self.dismissed_at)
        if self.subject_version is not None and self.subject_version < 1:
            raise ValueError("subject_version must be >= 1 when set")
