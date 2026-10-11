import { ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  oneOf,
  pick,
  requiredInt,
  requiredArray,
  requiredNullableEnum,
  requiredNullableString,
  requiredString,
  requiredStringArray,
} from "./_read-helpers";

export const PROJECT_STATES = ["active", "on_hold", "closed"] as const;

export type ProjectState = (typeof PROJECT_STATES)[number];

export const PROJECT_SECTORS = [
  "housing_and_residential",
  "hospitality_and_commercial",
  "healthcare_and_life_sciences",
  "education_civic_and_community",
  "industrial_logistics_and_technology",
  "recreation_and_entertainment",
  "transportation_and_mobility",
  "utilities_energy_and_environmental",
  "land_resource_and_specialty",
] as const;

export type ProjectSector = (typeof PROJECT_SECTORS)[number];

export const PROJECT_TYPES = [
  "single_family_housing",
  "multifamily_housing",
  "senior_living_and_residential_care",
  "student_staff_and_group_housing",
  "transitional_supportive_and_emergency_housing",
  "hotels_resorts_and_lodging",
  "restaurants_and_foodservice",
  "retail_shopping_and_consumer_services",
  "office_and_workplace",
  "automotive_and_consumer_mobility_services",
  "mixed_use_buildings_and_districts",
  "acute_care_and_hospitals",
  "outpatient_and_specialty_healthcare",
  "life_sciences_and_laboratory_facilities",
  "early_childhood_and_k_12_schools",
  "higher_education_and_academic_facilities",
  "government_and_civic_buildings",
  "public_safety_courts_and_corrections",
  "defense_and_military_facilities",
  "culture_performing_arts_and_religious_facilities",
  "social_services_and_community_facilities",
  "industrial_manufacturing_and_processing",
  "warehousing_logistics_and_cold_chain",
  "data_centers_and_telecommunications",
  "agricultural_horticultural_and_aquaculture_facilities",
  "sports_recreation_and_wellness_facilities",
  "entertainment_gaming_and_attractions",
  "parks_landscape_and_public_realm",
  "roads_bridges_and_tunnels",
  "rail_bus_and_public_transit",
  "aviation_and_spaceport_infrastructure",
  "marine_port_and_coastal_transportation",
  "parking_and_fleet_infrastructure",
  "water_supply_and_treatment",
  "wastewater_and_solid_waste",
  "stormwater_flood_control_and_coastal_protection",
  "power_generation_and_energy_storage",
  "power_fuel_and_utility_networks",
  "environmental_remediation_and_ecosystem_restoration",
  "land_development_enabling_and_civil_sitework",
  "extractive_and_mineral_resources_facilities",
  "specialty_construction_scopes_and_building_renewal",
] as const;

export type ProjectType = (typeof PROJECT_TYPES)[number];

export const PROJECT_PARTICIPATION_STATES = ["active"] as const;
export const PROJECT_RELATIONSHIP_STATUS_CODES = [
  "active",
  "completed",
  "terminated",
  "on_hold",
  "unresolved",
] as const;

export interface CanonicalProjectParticipation {
  readonly participant_entity_id: string;
  readonly role_code: string | null;
  readonly relationship_status_code: (typeof PROJECT_RELATIONSHIP_STATUS_CODES)[number];
  readonly participation_id: string;
  readonly state: (typeof PROJECT_PARTICIPATION_STATES)[number];
}

export interface ProjectRow {
  readonly project_id: string;
  readonly name: string;
  readonly state: ProjectState;
  readonly description: string | null;
  readonly participants: readonly string[];
  readonly canonical_participations: readonly CanonicalProjectParticipation[];
  readonly opened_at: string;
  readonly closed_at: string | null;
  readonly created_at: string;
  readonly updated_at: string;
  readonly version: number;
  readonly aliases: readonly string[];
  readonly project_number: string | null;
  readonly sector: ProjectSector | null;
  readonly type: ProjectType | null;
  readonly address: string | null;
  readonly city: string | null;
  readonly county: string | null;
  readonly address_state: string | null;
  readonly zip: string | null;
  readonly value: string | null;
  readonly scheduled_start: string | null;
  readonly contract_start: string | null;
  readonly actual_start: string | null;
  readonly scheduled_finish: string | null;
  readonly contract_finish: string | null;
  readonly actual_finish: string | null;
}

export interface ContinuityProjectsResult {
  readonly projects: readonly ProjectRow[];
}

const PROJECT_KEYS = [
  "project_id",
  "name",
  "state",
  "description",
  "participants",
  "canonical_participations",
  "opened_at",
  "closed_at",
  "created_at",
  "updated_at",
  "version",
  "aliases",
  "project_number",
  "sector",
  "type",
  "address",
  "city",
  "county",
  "address_state",
  "zip",
  "value",
  "scheduled_start",
  "contract_start",
  "actual_start",
  "scheduled_finish",
  "contract_finish",
  "actual_finish",
] as const;

function decodeCanonicalParticipation(
  input: unknown,
): DecodeResult<CanonicalProjectParticipation> {
  const known = pick(input, [
    "participant_entity_id",
    "role_code",
    "relationship_status_code",
    "participation_id",
    "state",
  ]);
  if (!known.ok) return known;
  const participantEntityId = requiredString(known.value.participant_entity_id);
  if (!participantEntityId.ok) return participantEntityId;
  const roleCode = requiredNullableString(known.value.role_code);
  if (!roleCode.ok) return roleCode;
  const relationshipStatus = oneOf(
    known.value.relationship_status_code,
    PROJECT_RELATIONSHIP_STATUS_CODES,
  );
  if (!relationshipStatus.ok) return relationshipStatus;
  const participationId = requiredString(known.value.participation_id);
  if (!participationId.ok) return participationId;
  const state = oneOf(known.value.state, PROJECT_PARTICIPATION_STATES);
  if (!state.ok) return state;
  return ok({
    participant_entity_id: participantEntityId.value,
    role_code: roleCode.value,
    relationship_status_code: relationshipStatus.value,
    participation_id: participationId.value,
    state: state.value,
  });
}

export function decodeProjectRow(input: unknown): DecodeResult<ProjectRow> {
  const known = pick(input, PROJECT_KEYS);
  if (!known.ok) return known;
  const projectId = requiredString(known.value.project_id);
  if (!projectId.ok) return projectId;
  const name = requiredString(known.value.name);
  if (!name.ok) return name;
  const state = oneOf(known.value.state, PROJECT_STATES);
  if (!state.ok) return state;
  const description = requiredNullableString(known.value.description);
  if (!description.ok) return description;
  const participants = requiredStringArray(known.value.participants);
  if (!participants.ok) return participants;
  const canonicalRows = requiredArray(known.value.canonical_participations);
  if (!canonicalRows.ok) return canonicalRows;
  const canonicalParticipations: CanonicalProjectParticipation[] = [];
  for (const row of canonicalRows.value) {
    const decoded = decodeCanonicalParticipation(row);
    if (!decoded.ok) return decoded;
    canonicalParticipations.push(decoded.value);
  }
  const openedAt = requiredString(known.value.opened_at);
  if (!openedAt.ok) return openedAt;
  const closedAt = requiredNullableString(known.value.closed_at);
  if (!closedAt.ok) return closedAt;
  const createdAt = requiredString(known.value.created_at);
  if (!createdAt.ok) return createdAt;
  const updatedAt = requiredString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  if (version.value < 1) return fail("a Project version was not positive");
  const aliases = requiredStringArray(known.value.aliases);
  if (!aliases.ok) return aliases;
  const projectNumber = requiredNullableString(known.value.project_number);
  if (!projectNumber.ok) return projectNumber;
  const sector = requiredNullableEnum(known.value.sector, PROJECT_SECTORS);
  if (!sector.ok) return sector;
  const type = requiredNullableEnum(known.value.type, PROJECT_TYPES);
  if (!type.ok) return type;
  const address = requiredNullableString(known.value.address);
  if (!address.ok) return address;
  const city = requiredNullableString(known.value.city);
  if (!city.ok) return city;
  const county = requiredNullableString(known.value.county);
  if (!county.ok) return county;
  const addressState = requiredNullableString(known.value.address_state);
  if (!addressState.ok) return addressState;
  const zip = requiredNullableString(known.value.zip);
  if (!zip.ok) return zip;
  const value = requiredNullableString(known.value.value);
  if (!value.ok) return value;
  const scheduledStart = requiredNullableString(known.value.scheduled_start);
  if (!scheduledStart.ok) return scheduledStart;
  const contractStart = requiredNullableString(known.value.contract_start);
  if (!contractStart.ok) return contractStart;
  const actualStart = requiredNullableString(known.value.actual_start);
  if (!actualStart.ok) return actualStart;
  const scheduledFinish = requiredNullableString(known.value.scheduled_finish);
  if (!scheduledFinish.ok) return scheduledFinish;
  const contractFinish = requiredNullableString(known.value.contract_finish);
  if (!contractFinish.ok) return contractFinish;
  const actualFinish = requiredNullableString(known.value.actual_finish);
  if (!actualFinish.ok) return actualFinish;
  return ok({
    project_id: projectId.value,
    name: name.value,
    state: state.value,
    description: description.value,
    participants: participants.value,
    canonical_participations: canonicalParticipations,
    opened_at: openedAt.value,
    closed_at: closedAt.value,
    created_at: createdAt.value,
    updated_at: updatedAt.value,
    version: version.value,
    aliases: aliases.value,
    project_number: projectNumber.value,
    sector: sector.value,
    type: type.value,
    address: address.value,
    city: city.value,
    county: county.value,
    address_state: addressState.value,
    zip: zip.value,
    value: value.value,
    scheduled_start: scheduledStart.value,
    contract_start: contractStart.value,
    actual_start: actualStart.value,
    scheduled_finish: scheduledFinish.value,
    contract_finish: contractFinish.value,
    actual_finish: actualFinish.value,
  });
}

export const decodeContinuityProjects: Decoder<ContinuityProjectsResult> = (input) => {
  const known = pick(input, ["projects"]);
  if (!known.ok) return known;
  if (known.value.projects === undefined) {
    return fail("a required array was omitted");
  }
  const projects = decodeItems(known.value.projects, decodeProjectRow);
  if (!projects.ok) return projects;
  return ok({ projects: projects.value });
};
