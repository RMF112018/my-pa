/**
 * Shared guards for the seventeen `entities.*` read decoders. Not a schema
 * framework: each capability still names its own result keys and required arrays.
 */
import { isBoolean, isRecord, ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  oneOf,
  pick,
  requiredArray,
  requiredBoolean,
  requiredInt,
  requiredNullableString,
  requiredString,
  requiredStringArray,
} from "./_read-helpers";

export const ENTITY_TYPES = [
  "person",
  "organization",
  "program",
  "project",
  "work_package",
  "team_or_group",
  "location",
] as const;

export type EntityType = (typeof ENTITY_TYPES)[number];

export const ENTITY_STATUSES = [
  "active",
  "inactive",
  "historical",
  "merged_redirect",
  "archived",
] as const;

export type EntityStatus = (typeof ENTITY_STATUSES)[number];

export const ALIAS_TYPES = [
  "full_name",
  "preferred_name",
  "nickname",
  "initials",
  "abbreviation",
  "former_name",
  "document_reference",
] as const;

export const IDENTIFIER_NAMESPACES = [
  "email",
  "entra_object_id",
  "teams_user_id",
  "outlook_contact_id",
  "apple_contact_id",
  "source_participant_id",
  "vendor_system_id",
  "legacy_relationship_person_id",
  "legacy_relationship_organization_id",
] as const;

export const LIFECYCLE_STATES = ["active", "retired", "superseded"] as const;

export const DIRECTED_STATES = ["active", "ended", "superseded"] as const;

export const ASSIGNMENT_TYPES = [
  "employment",
  "membership",
  "project_assignment",
  "work_package_assignment",
  "team_membership",
] as const;

export const RELATIONSHIP_TYPES = [
  "works_for",
  "reports_to",
  "represents",
  "manages",
  "leads",
  "responsible_for",
  "approver_for",
  "decision_maker_for",
  "primary_contact_for",
  "member_of",
  "consultant_to",
  "contractor_on",
  "subcontractor_to",
  "vendor_for",
  "affiliated_with",
  "brand_of",
  "operates_as",
  "dba_of",
  "historical_identity_of",
  "parent_of",
  "subsidiary_of",
  "acquired_by",
  "practice_of",
  "contracting_entity_for",
  "managed_by",
  "owner_representative_for",
  "project_controls_advisor_to",
  "technical_reviewer_of",
  "peer_reviewer_of",
  "design_coordination_with",
  "utility_provider_for",
  "permitting_authority_for",
  "seller_developer_for",
  "sales_marketing_agent_for",
  "sequence_interfaces_with",
] as const;

export const RESOLUTION_OUTCOMES = [
  "resolved_exact",
  "resolved_contextual",
  "ambiguous",
  "not_found",
  "conflicted_identifier",
  "historical_match",
] as const;

export type ResolutionOutcome = (typeof RESOLUTION_OUTCOMES)[number];

export const RESOLUTION_BASES = [
  "verified_external_identifier",
  "external_identifier",
  "alias",
  "canonical_name",
  "typed_name",
  "communication_value",
] as const;

export const CONTEXTUAL_SIGNALS = [
  "assigned_to_the_named_scope",
  "related_to_the_named_scope",
  "affiliated_with_the_named_scope",
  "participates_in_the_named_scope",
] as const;

export const RESOLUTION_WARNINGS = [
  "several_entities_share_this_name",
  "identifier_claimed_by_several_entities",
  "evidence_was_not_effective_at_that_moment",
  "entity_has_been_merged_away",
  "entity_is_not_current",
  "matched_identifier_is_unverified",
  "narrowed_by_supplied_scope",
  "more_candidates_than_this_answer_carries",
  "context_did_not_distinguish_the_candidates",
  "a_refused_pairing_was_withheld",
] as const;

export const CONTEXT_CARD_LIMITATIONS = [
  "more_aliases_than_this_card_carries",
  "more_identifiers_than_this_card_carries",
  "more_assignments_than_this_card_carries",
  "more_relationships_than_this_card_carries",
  "more_observations_than_this_card_carries",
  "no_source_has_been_observed",
  "coverage_counted_a_bounded_sample",
  "more_memories_than_this_card_carries",
  "memories_were_withheld_by_classification",
  "no_memory_has_been_recorded",
  "the_memory_plane_is_unavailable",
] as const;

export const PROFILE_LIMITATIONS = [
  "more_names_than_this_profile_carries",
  "more_addresses_than_this_profile_carries",
  "more_communication_methods_than_this_profile_carries",
  "more_participations_as_project_than_this_profile_carries",
  "more_participations_as_participant_than_this_profile_carries",
  "more_affiliations_as_person_than_this_profile_carries",
  "more_affiliations_as_organization_than_this_profile_carries",
] as const;

export const OBSERVATION_KINDS = [
  "contact_record",
  "message_participant",
  "calendar_attendee",
  "document_mention",
  "user_statement",
] as const;

export const OBSERVATION_AUTHORITIES = [
  "source_observation",
  "user_authored_statement",
  "system_deterministic_observation",
] as const;

export const OBSERVATION_ORIGINS = ["configured_source", "product_owned_capture"] as const;

export const OBSERVATION_STATES = [
  "current",
  "stale",
  "contradicted",
  "superseded",
  "quarantined",
] as const;

export const NAME_TYPE_CODES = [
  "display",
  "legal",
  "operating",
  "dba",
  "brand",
  "acronym",
  "alias",
  "historical_name",
  "document_reference",
] as const;

export const ADDRESS_TYPE_CODES = [
  "project",
  "legal_principal",
  "headquarters",
  "regional_office",
  "office",
  "business",
  "mailing",
  "city_hall",
  "known_other",
] as const;

export const COMMUNICATION_METHOD_TYPES = ["email", "phone", "domain", "website"] as const;

export const COMMUNICATION_USAGE_CONTEXTS = [
  "corporate",
  "project",
  "project_sales",
  "generic",
  "personal",
  "office",
  "other",
] as const;

export const VERIFICATION_STATUS_CODES = [
  "verified",
  "best_supported",
  "unresolved",
  "awaiting_confirmation",
] as const;

export const ORGANIZATION_KIND_CODES = [
  "company",
  "llc_or_spv",
  "professional_practice",
  "brand_or_operating_unit",
  "government_authority",
  "utility",
  "nonprofit",
  "public_agency",
  "other_or_unresolved",
] as const;

export const ROLE_BASIS_CODES = [
  "contractual",
  "source_verified",
  "project_observed",
  "inferred",
  "unresolved",
] as const;

export const STAKEHOLDER_SIDE_CODES = [
  "owner",
  "developer",
  "design",
  "contractor",
  "consultant",
  "authority",
  "utility",
  "vendor",
  "sales_marketing",
  "adjacent_interface",
  "other",
] as const;

export const STAKEHOLDER_CLASS_CODES = ["core", "adjacent", "transactional", "unresolved"] as const;

export const PARTICIPATION_STATUS_CODES = [
  "active",
  "completed",
  "terminated",
  "on_hold",
  "unresolved",
] as const;

export const AFFILIATION_TYPE_CODES = [
  "employment",
  "principal_ownership",
  "independent_consultant",
  "contractor",
  "board_member",
  "advisor",
  "other",
] as const;

export const MEMORY_KINDS = [
  "general_note",
  "personal_detail",
  "important_date",
  "interest",
  "communication_preference",
  "working_preference",
  "concern",
  "sensitivity",
  "follow_up_context",
  "user_pinned_context",
] as const;

export const MEMORY_AUTHORITIES = [
  "user_authored_private_note",
  "user_confirmed_assertion",
  "source_backed_assertion",
  "public_assertion",
] as const;

export const CLASSIFICATIONS = ["synthetic_test", "private_local", "restricted_local"] as const;

export const IDENTITY_HISTORY_SOURCES = [
  "direct_mutation",
  "identity_operation",
  "legacy_merge",
] as const;

export const IDENTITY_HISTORY_OPERATIONS = [
  "entities.create",
  "entities.update",
  "entities.archive",
  "entities.restore",
  "entities.identifiers.bind",
  "entities.identifiers.retire",
  "entities.identifiers.supersede",
  "entities.aliases.add",
  "entities.aliases.retire",
  "entities.aliases.supersede",
  "merge",
  "split",
] as const;

export const PARTICIPATION_PERSPECTIVES = ["project", "participant"] as const;

export function requiredNullableBoolean(value: unknown): DecodeResult<boolean | null> {
  if (value === undefined) return fail("a required field was missing");
  if (value === null) return ok(null);
  if (!isBoolean(value)) return fail("a required field was not the expected type");
  return ok(value);
}

function decodeClosedStringArray<T extends string>(
  value: unknown,
  allowed: readonly T[],
): DecodeResult<readonly T[]> {
  const rows = requiredArray(value);
  if (!rows.ok) return rows;
  const decoded: T[] = [];
  for (const item of rows.value) {
    const member = oneOf(item, allowed);
    if (!member.ok) return member;
    decoded.push(member.value);
  }
  return ok(decoded);
}

function requiredObject(value: unknown, message = "a required object was missing"): DecodeResult<unknown> {
  if (value === undefined) return fail(message);
  return ok(value);
}

export interface EntityView {
  readonly entity_id: string;
  readonly entity_type: EntityType;
  readonly canonical_name: string;
  readonly display_name: string;
  readonly status: EntityStatus;
  readonly created_at: string;
  readonly updated_at: string;
  readonly version: number;
  readonly superseded_by_entity_id: string | null;
}

const ENTITY_VIEW_KEYS = [
  "entity_id",
  "entity_type",
  "canonical_name",
  "display_name",
  "status",
  "created_at",
  "updated_at",
  "version",
  "superseded_by_entity_id",
] as const;

export function decodeEntityView(input: unknown): DecodeResult<EntityView> {
  const known = pick(input, ENTITY_VIEW_KEYS);
  if (!known.ok) return known;
  const entityId = requiredString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  const entityType = oneOf(known.value.entity_type, ENTITY_TYPES);
  if (!entityType.ok) return entityType;
  const canonical = requiredString(known.value.canonical_name);
  if (!canonical.ok) return canonical;
  const display = requiredString(known.value.display_name);
  if (!display.ok) return display;
  const status = oneOf(known.value.status, ENTITY_STATUSES);
  if (!status.ok) return status;
  const createdAt = requiredString(known.value.created_at);
  if (!createdAt.ok) return createdAt;
  const updatedAt = requiredString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  const superseded = requiredNullableString(known.value.superseded_by_entity_id);
  if (!superseded.ok) return superseded;
  return ok({
    entity_id: entityId.value,
    entity_type: entityType.value,
    canonical_name: canonical.value,
    display_name: display.value,
    status: status.value,
    created_at: createdAt.value,
    updated_at: updatedAt.value,
    version: version.value,
    superseded_by_entity_id: superseded.value,
  });
}

export interface EntitySummary {
  readonly entity_id: string;
  readonly entity_type: EntityType;
  readonly canonical_name: string;
  readonly display_name: string;
  readonly status: EntityStatus;
  readonly affiliated_organizations: readonly string[];
  readonly project_roles: readonly string[];
}

export function decodeEntitySummary(input: unknown): DecodeResult<EntitySummary> {
  const known = pick(input, [
    "entity_id",
    "entity_type",
    "canonical_name",
    "display_name",
    "status",
    "affiliated_organizations",
    "project_roles",
  ]);
  if (!known.ok) return known;
  const entityId = requiredString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  const entityType = oneOf(known.value.entity_type, ENTITY_TYPES);
  if (!entityType.ok) return entityType;
  const canonical = requiredString(known.value.canonical_name);
  if (!canonical.ok) return canonical;
  const display = requiredString(known.value.display_name);
  if (!display.ok) return display;
  const status = oneOf(known.value.status, ENTITY_STATUSES);
  if (!status.ok) return status;
  const orgs = requiredStringArray(known.value.affiliated_organizations);
  if (!orgs.ok) return orgs;
  const roles = requiredStringArray(known.value.project_roles);
  if (!roles.ok) return roles;
  return ok({
    entity_id: entityId.value,
    entity_type: entityType.value,
    canonical_name: canonical.value,
    display_name: display.value,
    status: status.value,
    affiliated_organizations: orgs.value,
    project_roles: roles.value,
  });
}

export interface EntitySearchResult {
  readonly entities: readonly EntitySummary[];
}

export const decodeEntitySearchResult: Decoder<EntitySearchResult> = (input) => {
  const known = pick(input, ["entities"]);
  if (!known.ok) return known;
  if (known.value.entities === undefined) return fail("a required array was omitted");
  const entities = decodeItems(known.value.entities, decodeEntitySummary);
  if (!entities.ok) return entities;
  return ok({ entities: entities.value });
};

export interface EntityGetResult {
  readonly entity: EntityView;
}

export const decodeEntityGetResult: Decoder<EntityGetResult> = (input) => {
  const known = pick(input, ["entity"]);
  if (!known.ok) return known;
  const wrapped = requiredObject(known.value.entity);
  if (!wrapped.ok) return wrapped;
  const entity = decodeEntityView(wrapped.value);
  if (!entity.ok) return entity;
  return ok({ entity: entity.value });
};

export interface ResolutionCandidate {
  readonly entity_id: string;
  readonly entity_type: EntityType;
  readonly display_name: string;
  readonly status: EntityStatus;
  readonly superseded_by_entity_id: string | null;
  readonly matched_on: readonly (typeof RESOLUTION_BASES)[number][];
  readonly signals: readonly (typeof CONTEXTUAL_SIGNALS)[number][];
}

function decodeResolutionCandidate(input: unknown): DecodeResult<ResolutionCandidate> {
  const known = pick(input, [
    "entity_id",
    "entity_type",
    "display_name",
    "status",
    "superseded_by_entity_id",
    "matched_on",
    "signals",
  ]);
  if (!known.ok) return known;
  const entityId = requiredString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  const entityType = oneOf(known.value.entity_type, ENTITY_TYPES);
  if (!entityType.ok) return entityType;
  const display = requiredString(known.value.display_name);
  if (!display.ok) return display;
  const status = oneOf(known.value.status, ENTITY_STATUSES);
  if (!status.ok) return status;
  const superseded = requiredNullableString(known.value.superseded_by_entity_id);
  if (!superseded.ok) return superseded;
  const matched = decodeClosedStringArray(known.value.matched_on, RESOLUTION_BASES);
  if (!matched.ok) return matched;
  const signals = decodeClosedStringArray(known.value.signals, CONTEXTUAL_SIGNALS);
  if (!signals.ok) return signals;
  return ok({
    entity_id: entityId.value,
    entity_type: entityType.value,
    display_name: display.value,
    status: status.value,
    superseded_by_entity_id: superseded.value,
    matched_on: matched.value,
    signals: signals.value,
  });
}

export interface EntityResolutionView {
  readonly outcome: ResolutionOutcome;
  readonly entity_id: string | null;
  readonly candidates: readonly ResolutionCandidate[];
  readonly warnings: readonly (typeof RESOLUTION_WARNINGS)[number][];
  readonly candidates_were_truncated: boolean;
}

export function decodeEntityResolutionView(input: unknown): DecodeResult<EntityResolutionView> {
  const known = pick(input, [
    "outcome",
    "entity_id",
    "candidates",
    "warnings",
    "candidates_were_truncated",
  ]);
  if (!known.ok) return known;
  const outcome = oneOf(known.value.outcome, RESOLUTION_OUTCOMES);
  if (!outcome.ok) return outcome;
  const entityId = requiredNullableString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  if (known.value.candidates === undefined) return fail("a required array was omitted");
  const candidates = decodeItems(known.value.candidates, decodeResolutionCandidate);
  if (!candidates.ok) return candidates;
  const warnings = decodeClosedStringArray(known.value.warnings, RESOLUTION_WARNINGS);
  if (!warnings.ok) return warnings;
  const truncated = requiredBoolean(known.value.candidates_were_truncated);
  if (!truncated.ok) return truncated;
  return ok({
    outcome: outcome.value,
    entity_id: entityId.value,
    candidates: candidates.value,
    warnings: warnings.value,
    candidates_were_truncated: truncated.value,
  });
}

export interface EntityResolveResult {
  readonly resolution: EntityResolutionView;
}

export const decodeEntityResolveResult: Decoder<EntityResolveResult> = (input) => {
  const known = pick(input, ["resolution"]);
  if (!known.ok) return known;
  const wrapped = requiredObject(known.value.resolution);
  if (!wrapped.ok) return wrapped;
  const resolution = decodeEntityResolutionView(wrapped.value);
  if (!resolution.ok) return resolution;
  return ok({ resolution: resolution.value });
};

export interface EntityAliasView {
  readonly alias_id: string;
  readonly alias_type: (typeof ALIAS_TYPES)[number];
  readonly display_value: string;
  readonly effective_from: string | null;
  readonly effective_to: string | null;
}

function decodeAliasView(input: unknown): DecodeResult<EntityAliasView> {
  const known = pick(input, [
    "alias_id",
    "alias_type",
    "display_value",
    "effective_from",
    "effective_to",
  ]);
  if (!known.ok) return known;
  const aliasId = requiredString(known.value.alias_id);
  if (!aliasId.ok) return aliasId;
  const aliasType = oneOf(known.value.alias_type, ALIAS_TYPES);
  if (!aliasType.ok) return aliasType;
  const display = requiredString(known.value.display_value);
  if (!display.ok) return display;
  const from = requiredNullableString(known.value.effective_from);
  if (!from.ok) return from;
  const to = requiredNullableString(known.value.effective_to);
  if (!to.ok) return to;
  return ok({
    alias_id: aliasId.value,
    alias_type: aliasType.value,
    display_value: display.value,
    effective_from: from.value,
    effective_to: to.value,
  });
}

export interface EntityIdentifierView {
  readonly identifier_id: string;
  readonly namespace: (typeof IDENTIFIER_NAMESPACES)[number];
  readonly display_value: string;
  readonly verified: boolean;
  readonly effective_from: string | null;
  readonly effective_to: string | null;
}

function decodeIdentifierView(input: unknown): DecodeResult<EntityIdentifierView> {
  const known = pick(input, [
    "identifier_id",
    "namespace",
    "display_value",
    "verified",
    "effective_from",
    "effective_to",
  ]);
  if (!known.ok) return known;
  const identifierId = requiredString(known.value.identifier_id);
  if (!identifierId.ok) return identifierId;
  const namespace = oneOf(known.value.namespace, IDENTIFIER_NAMESPACES);
  if (!namespace.ok) return namespace;
  const display = requiredString(known.value.display_value);
  if (!display.ok) return display;
  const verified = requiredBoolean(known.value.verified);
  if (!verified.ok) return verified;
  const from = requiredNullableString(known.value.effective_from);
  if (!from.ok) return from;
  const to = requiredNullableString(known.value.effective_to);
  if (!to.ok) return to;
  return ok({
    identifier_id: identifierId.value,
    namespace: namespace.value,
    display_value: display.value,
    verified: verified.value,
    effective_from: from.value,
    effective_to: to.value,
  });
}

export interface LifecycleIdentifierView extends EntityIdentifierView {
  readonly state: (typeof LIFECYCLE_STATES)[number];
  readonly version: number;
  readonly retired_at: string | null;
  readonly updated_at: string | null;
  readonly superseded_by_identifier_id: string | null;
}

export function decodeLifecycleIdentifierView(input: unknown): DecodeResult<LifecycleIdentifierView> {
  const known = pick(input, [
    "identifier_id",
    "namespace",
    "display_value",
    "verified",
    "effective_from",
    "effective_to",
    "state",
    "version",
    "retired_at",
    "updated_at",
    "superseded_by_identifier_id",
  ]);
  if (!known.ok) return known;
  const base = decodeIdentifierView(known.value);
  if (!base.ok) return base;
  const state = oneOf(known.value.state, LIFECYCLE_STATES);
  if (!state.ok) return state;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  const retiredAt = requiredNullableString(known.value.retired_at);
  if (!retiredAt.ok) return retiredAt;
  const updatedAt = requiredNullableString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  const superseded = requiredNullableString(known.value.superseded_by_identifier_id);
  if (!superseded.ok) return superseded;
  return ok({
    ...base.value,
    state: state.value,
    version: version.value,
    retired_at: retiredAt.value,
    updated_at: updatedAt.value,
    superseded_by_identifier_id: superseded.value,
  });
}

export interface LifecycleAliasView extends EntityAliasView {
  readonly state: (typeof LIFECYCLE_STATES)[number];
  readonly version: number;
  readonly retired_at: string | null;
  readonly updated_at: string | null;
  readonly superseded_by_alias_id: string | null;
}

export function decodeLifecycleAliasView(input: unknown): DecodeResult<LifecycleAliasView> {
  const known = pick(input, [
    "alias_id",
    "alias_type",
    "display_value",
    "effective_from",
    "effective_to",
    "state",
    "version",
    "retired_at",
    "updated_at",
    "superseded_by_alias_id",
  ]);
  if (!known.ok) return known;
  const base = decodeAliasView(known.value);
  if (!base.ok) return base;
  const state = oneOf(known.value.state, LIFECYCLE_STATES);
  if (!state.ok) return state;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  const retiredAt = requiredNullableString(known.value.retired_at);
  if (!retiredAt.ok) return retiredAt;
  const updatedAt = requiredNullableString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  const superseded = requiredNullableString(known.value.superseded_by_alias_id);
  if (!superseded.ok) return superseded;
  return ok({
    ...base.value,
    state: state.value,
    version: version.value,
    retired_at: retiredAt.value,
    updated_at: updatedAt.value,
    superseded_by_alias_id: superseded.value,
  });
}

export interface AssignmentView {
  readonly assignment_id: string;
  readonly entity_id: string;
  readonly assignment_type: (typeof ASSIGNMENT_TYPES)[number];
  readonly scope_entity_id: string | null;
  readonly role: string | null;
  readonly discipline: string | null;
  readonly responsibility_class: string | null;
  readonly status: (typeof DIRECTED_STATES)[number];
  readonly is_current: boolean | null;
  readonly effective_from: string | null;
  readonly effective_to: string | null;
  readonly version: number;
}

export function decodeAssignmentView(input: unknown): DecodeResult<AssignmentView> {
  const known = pick(input, [
    "assignment_id",
    "entity_id",
    "assignment_type",
    "scope_entity_id",
    "role",
    "discipline",
    "responsibility_class",
    "status",
    "is_current",
    "effective_from",
    "effective_to",
    "version",
  ]);
  if (!known.ok) return known;
  const assignmentId = requiredString(known.value.assignment_id);
  if (!assignmentId.ok) return assignmentId;
  const entityId = requiredString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  const assignmentType = oneOf(known.value.assignment_type, ASSIGNMENT_TYPES);
  if (!assignmentType.ok) return assignmentType;
  const scope = requiredNullableString(known.value.scope_entity_id);
  if (!scope.ok) return scope;
  const role = requiredNullableString(known.value.role);
  if (!role.ok) return role;
  const discipline = requiredNullableString(known.value.discipline);
  if (!discipline.ok) return discipline;
  const responsibility = requiredNullableString(known.value.responsibility_class);
  if (!responsibility.ok) return responsibility;
  const status = oneOf(known.value.status, DIRECTED_STATES);
  if (!status.ok) return status;
  const isCurrent = requiredNullableBoolean(known.value.is_current);
  if (!isCurrent.ok) return isCurrent;
  const from = requiredNullableString(known.value.effective_from);
  if (!from.ok) return from;
  const to = requiredNullableString(known.value.effective_to);
  if (!to.ok) return to;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  return ok({
    assignment_id: assignmentId.value,
    entity_id: entityId.value,
    assignment_type: assignmentType.value,
    scope_entity_id: scope.value,
    role: role.value,
    discipline: discipline.value,
    responsibility_class: responsibility.value,
    status: status.value,
    is_current: isCurrent.value,
    effective_from: from.value,
    effective_to: to.value,
    version: version.value,
  });
}

export interface RelationshipView {
  readonly relationship_id: string;
  readonly is_current: boolean | null;
  readonly from_entity_id: string;
  readonly relationship_type: (typeof RELATIONSHIP_TYPES)[number];
  readonly to_entity_id: string;
  readonly scope_entity_id: string | null;
  readonly state: (typeof DIRECTED_STATES)[number];
  readonly effective_from: string | null;
  readonly effective_to: string | null;
  readonly version: number;
}

export function decodeRelationshipView(input: unknown): DecodeResult<RelationshipView> {
  const known = pick(input, [
    "relationship_id",
    "is_current",
    "from_entity_id",
    "relationship_type",
    "to_entity_id",
    "scope_entity_id",
    "state",
    "effective_from",
    "effective_to",
    "version",
  ]);
  if (!known.ok) return known;
  const relationshipId = requiredString(known.value.relationship_id);
  if (!relationshipId.ok) return relationshipId;
  const isCurrent = requiredNullableBoolean(known.value.is_current);
  if (!isCurrent.ok) return isCurrent;
  const fromEntity = requiredString(known.value.from_entity_id);
  if (!fromEntity.ok) return fromEntity;
  const relationshipType = oneOf(known.value.relationship_type, RELATIONSHIP_TYPES);
  if (!relationshipType.ok) return relationshipType;
  const toEntity = requiredString(known.value.to_entity_id);
  if (!toEntity.ok) return toEntity;
  const scope = requiredNullableString(known.value.scope_entity_id);
  if (!scope.ok) return scope;
  const state = oneOf(known.value.state, DIRECTED_STATES);
  if (!state.ok) return state;
  const from = requiredNullableString(known.value.effective_from);
  if (!from.ok) return from;
  const to = requiredNullableString(known.value.effective_to);
  if (!to.ok) return to;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  return ok({
    relationship_id: relationshipId.value,
    is_current: isCurrent.value,
    from_entity_id: fromEntity.value,
    relationship_type: relationshipType.value,
    to_entity_id: toEntity.value,
    scope_entity_id: scope.value,
    state: state.value,
    effective_from: from.value,
    effective_to: to.value,
    version: version.value,
  });
}

export interface ContextObservationView {
  readonly observation_id: string;
  readonly kind: (typeof OBSERVATION_KINDS)[number];
  readonly source_id: string;
  readonly source_object_id: string;
  readonly source_version_id: string;
  readonly observed_at: string;
  readonly recorded_at: string;
}

function decodeContextObservation(input: unknown): DecodeResult<ContextObservationView> {
  const known = pick(input, [
    "observation_id",
    "kind",
    "source_id",
    "source_object_id",
    "source_version_id",
    "observed_at",
    "recorded_at",
  ]);
  if (!known.ok) return known;
  const observationId = requiredString(known.value.observation_id);
  if (!observationId.ok) return observationId;
  const kind = oneOf(known.value.kind, OBSERVATION_KINDS);
  if (!kind.ok) return kind;
  const sourceId = requiredString(known.value.source_id);
  if (!sourceId.ok) return sourceId;
  const sourceObjectId = requiredString(known.value.source_object_id);
  if (!sourceObjectId.ok) return sourceObjectId;
  const sourceVersionId = requiredString(known.value.source_version_id);
  if (!sourceVersionId.ok) return sourceVersionId;
  const observedAt = requiredString(known.value.observed_at);
  if (!observedAt.ok) return observedAt;
  const recordedAt = requiredString(known.value.recorded_at);
  if (!recordedAt.ok) return recordedAt;
  return ok({
    observation_id: observationId.value,
    kind: kind.value,
    source_id: sourceId.value,
    source_object_id: sourceObjectId.value,
    source_version_id: sourceVersionId.value,
    observed_at: observedAt.value,
    recorded_at: recordedAt.value,
  });
}

export interface UnresolvedMentionView {
  readonly observation_id: string;
  readonly kind: (typeof OBSERVATION_KINDS)[number];
  readonly mention_display_name: string | null;
  readonly source_id: string;
  readonly source_object_id: string;
  readonly source_version_id: string;
  readonly observed_at: string;
  readonly recorded_at: string;
}

export function decodeUnresolvedMentionView(input: unknown): DecodeResult<UnresolvedMentionView> {
  if (isRecord(input) && Object.prototype.hasOwnProperty.call(input, "observed_value")) {
    return fail("unresolved mentions must not disclose observed_value");
  }
  const known = pick(input, [
    "observation_id",
    "kind",
    "mention_display_name",
    "source_id",
    "source_object_id",
    "source_version_id",
    "observed_at",
    "recorded_at",
  ]);
  if (!known.ok) return known;
  const observationId = requiredString(known.value.observation_id);
  if (!observationId.ok) return observationId;
  const kind = oneOf(known.value.kind, OBSERVATION_KINDS);
  if (!kind.ok) return kind;
  const mention = requiredNullableString(known.value.mention_display_name);
  if (!mention.ok) return mention;
  const sourceId = requiredString(known.value.source_id);
  if (!sourceId.ok) return sourceId;
  const sourceObjectId = requiredString(known.value.source_object_id);
  if (!sourceObjectId.ok) return sourceObjectId;
  const sourceVersionId = requiredString(known.value.source_version_id);
  if (!sourceVersionId.ok) return sourceVersionId;
  const observedAt = requiredString(known.value.observed_at);
  if (!observedAt.ok) return observedAt;
  const recordedAt = requiredString(known.value.recorded_at);
  if (!recordedAt.ok) return recordedAt;
  return ok({
    observation_id: observationId.value,
    kind: kind.value,
    mention_display_name: mention.value,
    source_id: sourceId.value,
    source_object_id: sourceObjectId.value,
    source_version_id: sourceVersionId.value,
    observed_at: observedAt.value,
    recorded_at: recordedAt.value,
  });
}

export interface RecordedObservationView {
  readonly observation_id: string;
  readonly kind: (typeof OBSERVATION_KINDS)[number];
  readonly authority: (typeof OBSERVATION_AUTHORITIES)[number];
  readonly origin: (typeof OBSERVATION_ORIGINS)[number];
  readonly state: (typeof OBSERVATION_STATES)[number];
  readonly state_reason: string | null;
  readonly mention_display_name: string | null;
  readonly source_id: string;
  readonly source_object_id: string;
  readonly source_version_id: string;
  readonly entity_id: string | null;
  readonly superseded_by_observation_id: string | null;
  readonly resolution_version: number;
  readonly observed_at: string;
  readonly recorded_at: string;
}

export function decodeRecordedObservationView(input: unknown): DecodeResult<RecordedObservationView> {
  if (isRecord(input) && Object.prototype.hasOwnProperty.call(input, "observed_value")) {
    return fail("observations must not disclose observed_value");
  }
  const known = pick(input, [
    "observation_id",
    "kind",
    "authority",
    "origin",
    "state",
    "state_reason",
    "mention_display_name",
    "source_id",
    "source_object_id",
    "source_version_id",
    "entity_id",
    "superseded_by_observation_id",
    "resolution_version",
    "observed_at",
    "recorded_at",
  ]);
  if (!known.ok) return known;
  const observationId = requiredString(known.value.observation_id);
  if (!observationId.ok) return observationId;
  const kind = oneOf(known.value.kind, OBSERVATION_KINDS);
  if (!kind.ok) return kind;
  const authority = oneOf(known.value.authority, OBSERVATION_AUTHORITIES);
  if (!authority.ok) return authority;
  const origin = oneOf(known.value.origin, OBSERVATION_ORIGINS);
  if (!origin.ok) return origin;
  const state = oneOf(known.value.state, OBSERVATION_STATES);
  if (!state.ok) return state;
  const stateReason = requiredNullableString(known.value.state_reason);
  if (!stateReason.ok) return stateReason;
  const mention = requiredNullableString(known.value.mention_display_name);
  if (!mention.ok) return mention;
  const sourceId = requiredString(known.value.source_id);
  if (!sourceId.ok) return sourceId;
  const sourceObjectId = requiredString(known.value.source_object_id);
  if (!sourceObjectId.ok) return sourceObjectId;
  const sourceVersionId = requiredString(known.value.source_version_id);
  if (!sourceVersionId.ok) return sourceVersionId;
  const entityId = requiredNullableString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  const superseded = requiredNullableString(known.value.superseded_by_observation_id);
  if (!superseded.ok) return superseded;
  const resolutionVersion = requiredInt(known.value.resolution_version);
  if (!resolutionVersion.ok) return resolutionVersion;
  const observedAt = requiredString(known.value.observed_at);
  if (!observedAt.ok) return observedAt;
  const recordedAt = requiredString(known.value.recorded_at);
  if (!recordedAt.ok) return recordedAt;
  return ok({
    observation_id: observationId.value,
    kind: kind.value,
    authority: authority.value,
    origin: origin.value,
    state: state.value,
    state_reason: stateReason.value,
    mention_display_name: mention.value,
    source_id: sourceId.value,
    source_object_id: sourceObjectId.value,
    source_version_id: sourceVersionId.value,
    entity_id: entityId.value,
    superseded_by_observation_id: superseded.value,
    resolution_version: resolutionVersion.value,
    observed_at: observedAt.value,
    recorded_at: recordedAt.value,
  });
}

export interface ContextCoverageEntry {
  readonly source_id: string;
  readonly observation_count: number;
  readonly most_recent_observation_at: string;
}

function decodeCoverageEntry(input: unknown): DecodeResult<ContextCoverageEntry> {
  const known = pick(input, ["source_id", "observation_count", "most_recent_observation_at"]);
  if (!known.ok) return known;
  const sourceId = requiredString(known.value.source_id);
  if (!sourceId.ok) return sourceId;
  const count = requiredInt(known.value.observation_count);
  if (!count.ok) return count;
  const mostRecent = requiredString(known.value.most_recent_observation_at);
  if (!mostRecent.ok) return mostRecent;
  return ok({
    source_id: sourceId.value,
    observation_count: count.value,
    most_recent_observation_at: mostRecent.value,
  });
}

export interface ContextMemoryView {
  readonly memory_id: string;
  readonly kind: (typeof MEMORY_KINDS)[number];
  readonly statement: string;
  readonly authority: (typeof MEMORY_AUTHORITIES)[number];
  readonly classification: (typeof CLASSIFICATIONS)[number];
  readonly pinned: boolean;
  readonly effective_from: string | null;
  readonly effective_to: string | null;
  readonly recorded_at: string;
}

function decodeContextMemory(input: unknown): DecodeResult<ContextMemoryView> {
  const known = pick(input, [
    "memory_id",
    "kind",
    "statement",
    "authority",
    "classification",
    "pinned",
    "effective_from",
    "effective_to",
    "recorded_at",
  ]);
  if (!known.ok) return known;
  const memoryId = requiredString(known.value.memory_id);
  if (!memoryId.ok) return memoryId;
  const kind = oneOf(known.value.kind, MEMORY_KINDS);
  if (!kind.ok) return kind;
  const statement = requiredString(known.value.statement);
  if (!statement.ok) return statement;
  const authority = oneOf(known.value.authority, MEMORY_AUTHORITIES);
  if (!authority.ok) return authority;
  const classification = oneOf(known.value.classification, CLASSIFICATIONS);
  if (!classification.ok) return classification;
  const pinned = requiredBoolean(known.value.pinned);
  if (!pinned.ok) return pinned;
  const from = requiredNullableString(known.value.effective_from);
  if (!from.ok) return from;
  const to = requiredNullableString(known.value.effective_to);
  if (!to.ok) return to;
  const recordedAt = requiredString(known.value.recorded_at);
  if (!recordedAt.ok) return recordedAt;
  return ok({
    memory_id: memoryId.value,
    kind: kind.value,
    statement: statement.value,
    authority: authority.value,
    classification: classification.value,
    pinned: pinned.value,
    effective_from: from.value,
    effective_to: to.value,
    recorded_at: recordedAt.value,
  });
}

export interface EntityContextCard {
  readonly entity: EntityView;
  readonly assembled_at: string;
  readonly coverage: readonly ContextCoverageEntry[];
  readonly most_recent_observation_at: string | null;
  readonly limitations: readonly (typeof CONTEXT_CARD_LIMITATIONS)[number][];
  readonly is_complete: boolean;
  readonly aliases: readonly EntityAliasView[];
  readonly identifiers: readonly EntityIdentifierView[];
  readonly assignments: readonly AssignmentView[];
  readonly relationships: readonly RelationshipView[];
  readonly observations: readonly ContextObservationView[];
  readonly memories: readonly ContextMemoryView[];
}

export function decodeEntityContextCard(input: unknown): DecodeResult<EntityContextCard> {
  const known = pick(input, [
    "entity",
    "assembled_at",
    "coverage",
    "most_recent_observation_at",
    "limitations",
    "is_complete",
    "aliases",
    "identifiers",
    "assignments",
    "relationships",
    "observations",
    "memories",
  ]);
  if (!known.ok) return known;
  const wrapped = requiredObject(known.value.entity);
  if (!wrapped.ok) return wrapped;
  const entity = decodeEntityView(wrapped.value);
  if (!entity.ok) return entity;
  const assembledAt = requiredString(known.value.assembled_at);
  if (!assembledAt.ok) return assembledAt;
  if (known.value.coverage === undefined) return fail("a required array was omitted");
  const coverage = decodeItems(known.value.coverage, decodeCoverageEntry);
  if (!coverage.ok) return coverage;
  const mostRecent = requiredNullableString(known.value.most_recent_observation_at);
  if (!mostRecent.ok) return mostRecent;
  const limitations = decodeClosedStringArray(known.value.limitations, CONTEXT_CARD_LIMITATIONS);
  if (!limitations.ok) return limitations;
  const isComplete = requiredBoolean(known.value.is_complete);
  if (!isComplete.ok) return isComplete;
  if (known.value.aliases === undefined) return fail("a required array was omitted");
  const aliases = decodeItems(known.value.aliases, decodeAliasView);
  if (!aliases.ok) return aliases;
  if (known.value.identifiers === undefined) return fail("a required array was omitted");
  const identifiers = decodeItems(known.value.identifiers, decodeIdentifierView);
  if (!identifiers.ok) return identifiers;
  if (known.value.assignments === undefined) return fail("a required array was omitted");
  const assignments = decodeItems(known.value.assignments, decodeAssignmentView);
  if (!assignments.ok) return assignments;
  if (known.value.relationships === undefined) return fail("a required array was omitted");
  const relationships = decodeItems(known.value.relationships, decodeRelationshipView);
  if (!relationships.ok) return relationships;
  if (known.value.observations === undefined) return fail("a required array was omitted");
  const observations = decodeItems(known.value.observations, decodeContextObservation);
  if (!observations.ok) return observations;
  if (known.value.memories === undefined) return fail("a required array was omitted");
  const memories = decodeItems(known.value.memories, decodeContextMemory);
  if (!memories.ok) return memories;
  return ok({
    entity: entity.value,
    assembled_at: assembledAt.value,
    coverage: coverage.value,
    most_recent_observation_at: mostRecent.value,
    limitations: limitations.value,
    is_complete: isComplete.value,
    aliases: aliases.value,
    identifiers: identifiers.value,
    assignments: assignments.value,
    relationships: relationships.value,
    observations: observations.value,
    memories: memories.value,
  });
}

export interface EntityContextResult {
  readonly context_card: EntityContextCard;
}

export const decodeEntityContextResult: Decoder<EntityContextResult> = (input) => {
  const known = pick(input, ["context_card"]);
  if (!known.ok) return known;
  const wrapped = requiredObject(known.value.context_card);
  if (!wrapped.ok) return wrapped;
  const card = decodeEntityContextCard(wrapped.value);
  if (!card.ok) return card;
  return ok({ context_card: card.value });
};

export interface EntityNameView {
  readonly entity_name_id: string;
  readonly entity_id: string;
  readonly name_type_code: (typeof NAME_TYPE_CODES)[number];
  readonly display_value: string;
  readonly normalized_value: string;
  readonly is_preferred: boolean;
  readonly effective_from: string | null;
  readonly effective_to: string | null;
  readonly state: (typeof LIFECYCLE_STATES)[number];
  readonly version: number;
  readonly updated_at: string | null;
  readonly retired_at: string | null;
  readonly superseded_by_entity_name_id: string | null;
}

export function decodeEntityNameView(input: unknown): DecodeResult<EntityNameView> {
  const known = pick(input, [
    "entity_name_id",
    "entity_id",
    "name_type_code",
    "display_value",
    "normalized_value",
    "is_preferred",
    "effective_from",
    "effective_to",
    "state",
    "version",
    "updated_at",
    "retired_at",
    "superseded_by_entity_name_id",
  ]);
  if (!known.ok) return known;
  const nameId = requiredString(known.value.entity_name_id);
  if (!nameId.ok) return nameId;
  const entityId = requiredString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  const nameType = oneOf(known.value.name_type_code, NAME_TYPE_CODES);
  if (!nameType.ok) return nameType;
  const display = requiredString(known.value.display_value);
  if (!display.ok) return display;
  const normalized = requiredString(known.value.normalized_value);
  if (!normalized.ok) return normalized;
  const preferred = requiredBoolean(known.value.is_preferred);
  if (!preferred.ok) return preferred;
  const from = requiredNullableString(known.value.effective_from);
  if (!from.ok) return from;
  const to = requiredNullableString(known.value.effective_to);
  if (!to.ok) return to;
  const state = oneOf(known.value.state, LIFECYCLE_STATES);
  if (!state.ok) return state;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  const updatedAt = requiredNullableString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  const retiredAt = requiredNullableString(known.value.retired_at);
  if (!retiredAt.ok) return retiredAt;
  const superseded = requiredNullableString(known.value.superseded_by_entity_name_id);
  if (!superseded.ok) return superseded;
  return ok({
    entity_name_id: nameId.value,
    entity_id: entityId.value,
    name_type_code: nameType.value,
    display_value: display.value,
    normalized_value: normalized.value,
    is_preferred: preferred.value,
    effective_from: from.value,
    effective_to: to.value,
    state: state.value,
    version: version.value,
    updated_at: updatedAt.value,
    retired_at: retiredAt.value,
    superseded_by_entity_name_id: superseded.value,
  });
}

export interface EntityAddressView {
  readonly entity_address_id: string;
  readonly entity_id: string;
  readonly address_type_code: (typeof ADDRESS_TYPE_CODES)[number];
  readonly raw_value: string;
  readonly normalized_address_value: string;
  readonly line1: string | null;
  readonly line2: string | null;
  readonly city: string | null;
  readonly region: string | null;
  readonly postal_code: string | null;
  readonly country: string | null;
  readonly label: string | null;
  readonly is_preferred: boolean;
  readonly effective_from: string | null;
  readonly effective_to: string | null;
  readonly state: (typeof LIFECYCLE_STATES)[number];
  readonly version: number;
  readonly updated_at: string | null;
  readonly retired_at: string | null;
  readonly superseded_by_entity_address_id: string | null;
}

export function decodeEntityAddressView(input: unknown): DecodeResult<EntityAddressView> {
  const known = pick(input, [
    "entity_address_id",
    "entity_id",
    "address_type_code",
    "raw_value",
    "normalized_address_value",
    "line1",
    "line2",
    "city",
    "region",
    "postal_code",
    "country",
    "label",
    "is_preferred",
    "effective_from",
    "effective_to",
    "state",
    "version",
    "updated_at",
    "retired_at",
    "superseded_by_entity_address_id",
  ]);
  if (!known.ok) return known;
  const addressId = requiredString(known.value.entity_address_id);
  if (!addressId.ok) return addressId;
  const entityId = requiredString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  const addressType = oneOf(known.value.address_type_code, ADDRESS_TYPE_CODES);
  if (!addressType.ok) return addressType;
  const raw = requiredString(known.value.raw_value);
  if (!raw.ok) return raw;
  const normalized = requiredString(known.value.normalized_address_value);
  if (!normalized.ok) return normalized;
  const line1 = requiredNullableString(known.value.line1);
  if (!line1.ok) return line1;
  const line2 = requiredNullableString(known.value.line2);
  if (!line2.ok) return line2;
  const city = requiredNullableString(known.value.city);
  if (!city.ok) return city;
  const region = requiredNullableString(known.value.region);
  if (!region.ok) return region;
  const postal = requiredNullableString(known.value.postal_code);
  if (!postal.ok) return postal;
  const country = requiredNullableString(known.value.country);
  if (!country.ok) return country;
  const label = requiredNullableString(known.value.label);
  if (!label.ok) return label;
  const preferred = requiredBoolean(known.value.is_preferred);
  if (!preferred.ok) return preferred;
  const from = requiredNullableString(known.value.effective_from);
  if (!from.ok) return from;
  const to = requiredNullableString(known.value.effective_to);
  if (!to.ok) return to;
  const state = oneOf(known.value.state, LIFECYCLE_STATES);
  if (!state.ok) return state;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  const updatedAt = requiredNullableString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  const retiredAt = requiredNullableString(known.value.retired_at);
  if (!retiredAt.ok) return retiredAt;
  const superseded = requiredNullableString(known.value.superseded_by_entity_address_id);
  if (!superseded.ok) return superseded;
  return ok({
    entity_address_id: addressId.value,
    entity_id: entityId.value,
    address_type_code: addressType.value,
    raw_value: raw.value,
    normalized_address_value: normalized.value,
    line1: line1.value,
    line2: line2.value,
    city: city.value,
    region: region.value,
    postal_code: postal.value,
    country: country.value,
    label: label.value,
    is_preferred: preferred.value,
    effective_from: from.value,
    effective_to: to.value,
    state: state.value,
    version: version.value,
    updated_at: updatedAt.value,
    retired_at: retiredAt.value,
    superseded_by_entity_address_id: superseded.value,
  });
}

export interface CommunicationMethodView {
  readonly communication_method_id: string;
  readonly entity_id: string;
  readonly method_type_code: (typeof COMMUNICATION_METHOD_TYPES)[number];
  readonly usage_context_code: (typeof COMMUNICATION_USAGE_CONTEXTS)[number];
  readonly display_value: string;
  readonly normalized_value: string;
  readonly verification_status_code: (typeof VERIFICATION_STATUS_CODES)[number];
  readonly is_preferred: boolean;
  readonly effective_from: string | null;
  readonly effective_to: string | null;
  readonly state: (typeof LIFECYCLE_STATES)[number];
  readonly version: number;
  readonly updated_at: string | null;
  readonly retired_at: string | null;
  readonly superseded_by_communication_method_id: string | null;
  readonly linked_external_identifier_id: string | null;
}

export function decodeCommunicationMethodView(input: unknown): DecodeResult<CommunicationMethodView> {
  const known = pick(input, [
    "communication_method_id",
    "entity_id",
    "method_type_code",
    "usage_context_code",
    "display_value",
    "normalized_value",
    "verification_status_code",
    "is_preferred",
    "effective_from",
    "effective_to",
    "state",
    "version",
    "updated_at",
    "retired_at",
    "superseded_by_communication_method_id",
    "linked_external_identifier_id",
  ]);
  if (!known.ok) return known;
  const methodId = requiredString(known.value.communication_method_id);
  if (!methodId.ok) return methodId;
  const entityId = requiredString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  const methodType = oneOf(known.value.method_type_code, COMMUNICATION_METHOD_TYPES);
  if (!methodType.ok) return methodType;
  const usage = oneOf(known.value.usage_context_code, COMMUNICATION_USAGE_CONTEXTS);
  if (!usage.ok) return usage;
  const display = requiredString(known.value.display_value);
  if (!display.ok) return display;
  const normalized = requiredString(known.value.normalized_value);
  if (!normalized.ok) return normalized;
  const verification = oneOf(known.value.verification_status_code, VERIFICATION_STATUS_CODES);
  if (!verification.ok) return verification;
  const preferred = requiredBoolean(known.value.is_preferred);
  if (!preferred.ok) return preferred;
  const from = requiredNullableString(known.value.effective_from);
  if (!from.ok) return from;
  const to = requiredNullableString(known.value.effective_to);
  if (!to.ok) return to;
  const state = oneOf(known.value.state, LIFECYCLE_STATES);
  if (!state.ok) return state;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  const updatedAt = requiredNullableString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  const retiredAt = requiredNullableString(known.value.retired_at);
  if (!retiredAt.ok) return retiredAt;
  const superseded = requiredNullableString(known.value.superseded_by_communication_method_id);
  if (!superseded.ok) return superseded;
  const linked = requiredNullableString(known.value.linked_external_identifier_id);
  if (!linked.ok) return linked;
  return ok({
    communication_method_id: methodId.value,
    entity_id: entityId.value,
    method_type_code: methodType.value,
    usage_context_code: usage.value,
    display_value: display.value,
    normalized_value: normalized.value,
    verification_status_code: verification.value,
    is_preferred: preferred.value,
    effective_from: from.value,
    effective_to: to.value,
    state: state.value,
    version: version.value,
    updated_at: updatedAt.value,
    retired_at: retiredAt.value,
    superseded_by_communication_method_id: superseded.value,
    linked_external_identifier_id: linked.value,
  });
}

export interface ParticipationView {
  readonly participation_id: string;
  readonly project_entity_id: string;
  readonly participant_entity_id: string;
  readonly project_display_name: string | null;
  readonly role_basis_code: (typeof ROLE_BASIS_CODES)[number];
  readonly stakeholder_side_code: (typeof STAKEHOLDER_SIDE_CODES)[number];
  readonly stakeholder_class_code: (typeof STAKEHOLDER_CLASS_CODES)[number];
  readonly relationship_status_code: (typeof PARTICIPATION_STATUS_CODES)[number];
  readonly role_code: string | null;
  readonly role_text: string | null;
  readonly discipline_code: string | null;
  readonly discipline_text: string | null;
  readonly scope_text: string | null;
  readonly effective_from: string | null;
  readonly effective_to: string | null;
  readonly state: (typeof LIFECYCLE_STATES)[number];
  readonly version: number;
  readonly updated_at: string | null;
  readonly retired_at: string | null;
  readonly superseded_by_participation_id: string | null;
}

export function decodeParticipationView(input: unknown): DecodeResult<ParticipationView> {
  const known = pick(input, [
    "participation_id",
    "project_entity_id",
    "participant_entity_id",
    "project_display_name",
    "role_basis_code",
    "stakeholder_side_code",
    "stakeholder_class_code",
    "relationship_status_code",
    "role_code",
    "role_text",
    "discipline_code",
    "discipline_text",
    "scope_text",
    "effective_from",
    "effective_to",
    "state",
    "version",
    "updated_at",
    "retired_at",
    "superseded_by_participation_id",
  ]);
  if (!known.ok) return known;
  const participationId = requiredString(known.value.participation_id);
  if (!participationId.ok) return participationId;
  const projectId = requiredString(known.value.project_entity_id);
  if (!projectId.ok) return projectId;
  const participantId = requiredString(known.value.participant_entity_id);
  if (!participantId.ok) return participantId;
  const projectName = requiredNullableString(known.value.project_display_name);
  if (!projectName.ok) return projectName;
  const roleBasis = oneOf(known.value.role_basis_code, ROLE_BASIS_CODES);
  if (!roleBasis.ok) return roleBasis;
  const side = oneOf(known.value.stakeholder_side_code, STAKEHOLDER_SIDE_CODES);
  if (!side.ok) return side;
  const stakeholderClass = oneOf(known.value.stakeholder_class_code, STAKEHOLDER_CLASS_CODES);
  if (!stakeholderClass.ok) return stakeholderClass;
  const status = oneOf(known.value.relationship_status_code, PARTICIPATION_STATUS_CODES);
  if (!status.ok) return status;
  const roleCode = requiredNullableString(known.value.role_code);
  if (!roleCode.ok) return roleCode;
  const roleText = requiredNullableString(known.value.role_text);
  if (!roleText.ok) return roleText;
  const disciplineCode = requiredNullableString(known.value.discipline_code);
  if (!disciplineCode.ok) return disciplineCode;
  const disciplineText = requiredNullableString(known.value.discipline_text);
  if (!disciplineText.ok) return disciplineText;
  const scopeText = requiredNullableString(known.value.scope_text);
  if (!scopeText.ok) return scopeText;
  const from = requiredNullableString(known.value.effective_from);
  if (!from.ok) return from;
  const to = requiredNullableString(known.value.effective_to);
  if (!to.ok) return to;
  const state = oneOf(known.value.state, LIFECYCLE_STATES);
  if (!state.ok) return state;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  const updatedAt = requiredNullableString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  const retiredAt = requiredNullableString(known.value.retired_at);
  if (!retiredAt.ok) return retiredAt;
  const superseded = requiredNullableString(known.value.superseded_by_participation_id);
  if (!superseded.ok) return superseded;
  return ok({
    participation_id: participationId.value,
    project_entity_id: projectId.value,
    participant_entity_id: participantId.value,
    project_display_name: projectName.value,
    role_basis_code: roleBasis.value,
    stakeholder_side_code: side.value,
    stakeholder_class_code: stakeholderClass.value,
    relationship_status_code: status.value,
    role_code: roleCode.value,
    role_text: roleText.value,
    discipline_code: disciplineCode.value,
    discipline_text: disciplineText.value,
    scope_text: scopeText.value,
    effective_from: from.value,
    effective_to: to.value,
    state: state.value,
    version: version.value,
    updated_at: updatedAt.value,
    retired_at: retiredAt.value,
    superseded_by_participation_id: superseded.value,
  });
}

export interface AffiliationView {
  readonly affiliation_id: string;
  readonly person_entity_id: string;
  readonly affiliation_type_code: (typeof AFFILIATION_TYPE_CODES)[number];
  readonly organization_entity_id: string | null;
  readonly job_title: string | null;
  readonly effective_from: string | null;
  readonly effective_to: string | null;
  readonly state: (typeof LIFECYCLE_STATES)[number];
  readonly version: number;
  readonly updated_at: string | null;
  readonly retired_at: string | null;
  readonly superseded_by_affiliation_id: string | null;
}

export function decodeAffiliationView(input: unknown): DecodeResult<AffiliationView> {
  const known = pick(input, [
    "affiliation_id",
    "person_entity_id",
    "affiliation_type_code",
    "organization_entity_id",
    "job_title",
    "effective_from",
    "effective_to",
    "state",
    "version",
    "updated_at",
    "retired_at",
    "superseded_by_affiliation_id",
  ]);
  if (!known.ok) return known;
  const affiliationId = requiredString(known.value.affiliation_id);
  if (!affiliationId.ok) return affiliationId;
  const personId = requiredString(known.value.person_entity_id);
  if (!personId.ok) return personId;
  const affiliationType = oneOf(known.value.affiliation_type_code, AFFILIATION_TYPE_CODES);
  if (!affiliationType.ok) return affiliationType;
  const organizationId = requiredNullableString(known.value.organization_entity_id);
  if (!organizationId.ok) return organizationId;
  const jobTitle = requiredNullableString(known.value.job_title);
  if (!jobTitle.ok) return jobTitle;
  const from = requiredNullableString(known.value.effective_from);
  if (!from.ok) return from;
  const to = requiredNullableString(known.value.effective_to);
  if (!to.ok) return to;
  const state = oneOf(known.value.state, LIFECYCLE_STATES);
  if (!state.ok) return state;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  const updatedAt = requiredNullableString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  const retiredAt = requiredNullableString(known.value.retired_at);
  if (!retiredAt.ok) return retiredAt;
  const superseded = requiredNullableString(known.value.superseded_by_affiliation_id);
  if (!superseded.ok) return superseded;
  return ok({
    affiliation_id: affiliationId.value,
    person_entity_id: personId.value,
    affiliation_type_code: affiliationType.value,
    organization_entity_id: organizationId.value,
    job_title: jobTitle.value,
    effective_from: from.value,
    effective_to: to.value,
    state: state.value,
    version: version.value,
    updated_at: updatedAt.value,
    retired_at: retiredAt.value,
    superseded_by_affiliation_id: superseded.value,
  });
}

export interface OrganizationProfileView {
  readonly entity_id: string;
  readonly organization_kind_code: (typeof ORGANIZATION_KIND_CODES)[number];
  readonly legal_identity_status_code: (typeof VERIFICATION_STATUS_CODES)[number];
  readonly jurisdiction_code: string | null;
  readonly registration_identifier: string | null;
  readonly version: number;
  readonly created_at: string | null;
  readonly updated_at: string | null;
}

export function decodeOrganizationProfileView(input: unknown): DecodeResult<OrganizationProfileView> {
  const known = pick(input, [
    "entity_id",
    "organization_kind_code",
    "legal_identity_status_code",
    "jurisdiction_code",
    "registration_identifier",
    "version",
    "created_at",
    "updated_at",
  ]);
  if (!known.ok) return known;
  const entityId = requiredString(known.value.entity_id);
  if (!entityId.ok) return entityId;
  const kind = oneOf(known.value.organization_kind_code, ORGANIZATION_KIND_CODES);
  if (!kind.ok) return kind;
  const legal = oneOf(known.value.legal_identity_status_code, VERIFICATION_STATUS_CODES);
  if (!legal.ok) return legal;
  const jurisdiction = requiredNullableString(known.value.jurisdiction_code);
  if (!jurisdiction.ok) return jurisdiction;
  const registration = requiredNullableString(known.value.registration_identifier);
  if (!registration.ok) return registration;
  const version = requiredInt(known.value.version);
  if (!version.ok) return version;
  const createdAt = requiredNullableString(known.value.created_at);
  if (!createdAt.ok) return createdAt;
  const updatedAt = requiredNullableString(known.value.updated_at);
  if (!updatedAt.ok) return updatedAt;
  return ok({
    entity_id: entityId.value,
    organization_kind_code: kind.value,
    legal_identity_status_code: legal.value,
    jurisdiction_code: jurisdiction.value,
    registration_identifier: registration.value,
    version: version.value,
    created_at: createdAt.value,
    updated_at: updatedAt.value,
  });
}

export interface EntityProfileView {
  readonly entity: EntityView;
  readonly assembled_at: string;
  readonly limitations: readonly (typeof PROFILE_LIMITATIONS)[number][];
  readonly is_complete: boolean;
  readonly organization_profile: OrganizationProfileView | null;
  readonly names: readonly EntityNameView[];
  readonly addresses: readonly EntityAddressView[];
  readonly communication_methods: readonly CommunicationMethodView[];
  readonly participations_as_project: readonly ParticipationView[];
  readonly participations_as_participant: readonly ParticipationView[];
  readonly affiliations_as_person: readonly AffiliationView[];
  readonly affiliations_as_organization: readonly AffiliationView[];
}

export function decodeEntityProfileView(input: unknown): DecodeResult<EntityProfileView> {
  const known = pick(input, [
    "entity",
    "assembled_at",
    "limitations",
    "is_complete",
    "organization_profile",
    "names",
    "addresses",
    "communication_methods",
    "participations_as_project",
    "participations_as_participant",
    "affiliations_as_person",
    "affiliations_as_organization",
  ]);
  if (!known.ok) return known;
  const wrapped = requiredObject(known.value.entity);
  if (!wrapped.ok) return wrapped;
  const entity = decodeEntityView(wrapped.value);
  if (!entity.ok) return entity;
  const assembledAt = requiredString(known.value.assembled_at);
  if (!assembledAt.ok) return assembledAt;
  const limitations = decodeClosedStringArray(known.value.limitations, PROFILE_LIMITATIONS);
  if (!limitations.ok) return limitations;
  const isComplete = requiredBoolean(known.value.is_complete);
  if (!isComplete.ok) return isComplete;
  if (known.value.organization_profile === undefined) return fail("a required field was missing");
  let organization: OrganizationProfileView | null = null;
  if (known.value.organization_profile !== null) {
    const decoded = decodeOrganizationProfileView(known.value.organization_profile);
    if (!decoded.ok) return decoded;
    organization = decoded.value;
  }
  if (known.value.names === undefined) return fail("a required array was omitted");
  const names = decodeItems(known.value.names, decodeEntityNameView);
  if (!names.ok) return names;
  if (known.value.addresses === undefined) return fail("a required array was omitted");
  const addresses = decodeItems(known.value.addresses, decodeEntityAddressView);
  if (!addresses.ok) return addresses;
  if (known.value.communication_methods === undefined) return fail("a required array was omitted");
  const methods = decodeItems(known.value.communication_methods, decodeCommunicationMethodView);
  if (!methods.ok) return methods;
  if (known.value.participations_as_project === undefined) {
    return fail("a required array was omitted");
  }
  const asProject = decodeItems(known.value.participations_as_project, decodeParticipationView);
  if (!asProject.ok) return asProject;
  if (known.value.participations_as_participant === undefined) {
    return fail("a required array was omitted");
  }
  const asParticipant = decodeItems(
    known.value.participations_as_participant,
    decodeParticipationView,
  );
  if (!asParticipant.ok) return asParticipant;
  if (known.value.affiliations_as_person === undefined) return fail("a required array was omitted");
  const asPerson = decodeItems(known.value.affiliations_as_person, decodeAffiliationView);
  if (!asPerson.ok) return asPerson;
  if (known.value.affiliations_as_organization === undefined) {
    return fail("a required array was omitted");
  }
  const asOrganization = decodeItems(
    known.value.affiliations_as_organization,
    decodeAffiliationView,
  );
  if (!asOrganization.ok) return asOrganization;
  return ok({
    entity: entity.value,
    assembled_at: assembledAt.value,
    limitations: limitations.value,
    is_complete: isComplete.value,
    organization_profile: organization,
    names: names.value,
    addresses: addresses.value,
    communication_methods: methods.value,
    participations_as_project: asProject.value,
    participations_as_participant: asParticipant.value,
    affiliations_as_person: asPerson.value,
    affiliations_as_organization: asOrganization.value,
  });
}

export interface EntityProfileResult {
  readonly profile: EntityProfileView;
}

export const decodeEntityProfileResult: Decoder<EntityProfileResult> = (input) => {
  const known = pick(input, ["profile"]);
  if (!known.ok) return known;
  const wrapped = requiredObject(known.value.profile);
  if (!wrapped.ok) return wrapped;
  const profile = decodeEntityProfileView(wrapped.value);
  if (!profile.ok) return profile;
  return ok({ profile: profile.value });
};

export interface IdentityHistoryChange {
  readonly family: string;
  readonly record_id: string;
  readonly effect_kind: string;
  readonly before_state: Readonly<Record<string, unknown>> | null;
  readonly after_state: Readonly<Record<string, unknown>> | null;
}

function decodeHistoryState(
  value: unknown,
): DecodeResult<Readonly<Record<string, unknown>> | null> {
  if (value === undefined) return fail("a required field was missing");
  if (value === null) return ok(null);
  if (!isRecord(value)) return fail("a required field was not the expected type");
  return ok(value);
}

function decodeIdentityHistoryChange(input: unknown): DecodeResult<IdentityHistoryChange> {
  const known = pick(input, ["family", "record_id", "effect_kind", "before_state", "after_state"]);
  if (!known.ok) return known;
  const family = requiredString(known.value.family);
  if (!family.ok) return family;
  const recordId = requiredString(known.value.record_id);
  if (!recordId.ok) return recordId;
  const effect = requiredString(known.value.effect_kind);
  if (!effect.ok) return effect;
  const before = decodeHistoryState(known.value.before_state);
  if (!before.ok) return before;
  const after = decodeHistoryState(known.value.after_state);
  if (!after.ok) return after;
  return ok({
    family: family.value,
    record_id: recordId.value,
    effect_kind: effect.value,
    before_state: before.value,
    after_state: after.value,
  });
}

export interface IdentityHistoryEntry {
  readonly history_id: string;
  readonly occurred_at: string;
  readonly source: (typeof IDENTITY_HISTORY_SOURCES)[number];
  readonly operation: (typeof IDENTITY_HISTORY_OPERATIONS)[number];
  readonly involved_entity_ids: readonly string[];
  readonly changes: readonly IdentityHistoryChange[];
  readonly actor_class: string | null;
  readonly actor_id: string | null;
  readonly authority: string | null;
  readonly correlation_id: string | null;
  readonly audit_id: string | null;
  readonly reason: string | null;
  readonly source_identity_operation_id: string | null;
  readonly receipt_id: string | null;
}

export function decodeIdentityHistoryEntry(input: unknown): DecodeResult<IdentityHistoryEntry> {
  const known = pick(input, [
    "history_id",
    "occurred_at",
    "source",
    "operation",
    "involved_entity_ids",
    "changes",
    "actor_class",
    "actor_id",
    "authority",
    "correlation_id",
    "audit_id",
    "reason",
    "source_identity_operation_id",
    "receipt_id",
  ]);
  if (!known.ok) return known;
  const historyId = requiredString(known.value.history_id);
  if (!historyId.ok) return historyId;
  const occurredAt = requiredString(known.value.occurred_at);
  if (!occurredAt.ok) return occurredAt;
  const source = oneOf(known.value.source, IDENTITY_HISTORY_SOURCES);
  if (!source.ok) return source;
  const operation = oneOf(known.value.operation, IDENTITY_HISTORY_OPERATIONS);
  if (!operation.ok) return operation;
  const involved = requiredStringArray(known.value.involved_entity_ids);
  if (!involved.ok) return involved;
  if (known.value.changes === undefined) return fail("a required array was omitted");
  const changes = decodeItems(known.value.changes, decodeIdentityHistoryChange);
  if (!changes.ok) return changes;
  const actorClass = requiredNullableString(known.value.actor_class);
  if (!actorClass.ok) return actorClass;
  const actorId = requiredNullableString(known.value.actor_id);
  if (!actorId.ok) return actorId;
  const authority = requiredNullableString(known.value.authority);
  if (!authority.ok) return authority;
  const correlationId = requiredNullableString(known.value.correlation_id);
  if (!correlationId.ok) return correlationId;
  const auditId = requiredNullableString(known.value.audit_id);
  if (!auditId.ok) return auditId;
  const reason = requiredNullableString(known.value.reason);
  if (!reason.ok) return reason;
  const sourceOp = requiredNullableString(known.value.source_identity_operation_id);
  if (!sourceOp.ok) return sourceOp;
  const receiptId = requiredNullableString(known.value.receipt_id);
  if (!receiptId.ok) return receiptId;
  return ok({
    history_id: historyId.value,
    occurred_at: occurredAt.value,
    source: source.value,
    operation: operation.value,
    involved_entity_ids: involved.value,
    changes: changes.value,
    actor_class: actorClass.value,
    actor_id: actorId.value,
    authority: authority.value,
    correlation_id: correlationId.value,
    audit_id: auditId.value,
    reason: reason.value,
    source_identity_operation_id: sourceOp.value,
    receipt_id: receiptId.value,
  });
}
