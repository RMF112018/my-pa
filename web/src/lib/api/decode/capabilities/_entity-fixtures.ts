/** Shared synthetic success rows for entity-read decoder tests. No personal data. */

export const AT = "2026-08-09T12:00:00.000Z";
export const ENTITY_ID = "ent_aaaaaaaa11111111";

export const ENTITY_VIEW = {
  entity_id: ENTITY_ID,
  entity_type: "person",
  canonical_name: "pat synthetic",
  display_name: "Pat Synthetic",
  status: "active",
  created_at: AT,
  updated_at: AT,
  version: 1,
  superseded_by_entity_id: null,
};

export const ENTITY_SUMMARY = {
  entity_id: ENTITY_ID,
  entity_type: "person",
  canonical_name: "pat synthetic",
  display_name: "Pat Synthetic",
  status: "active",
  affiliated_organizations: ["Acme Synthetic"],
  project_roles: ["architect"],
};

export const RESOLUTION = {
  outcome: "ambiguous",
  entity_id: null,
  candidates: [
    {
      entity_id: ENTITY_ID,
      entity_type: "person",
      display_name: "Alex Chen",
      status: "active",
      superseded_by_entity_id: null,
      matched_on: ["canonical_name"],
      signals: [],
    },
  ],
  warnings: ["several_entities_share_this_name"],
  candidates_were_truncated: false,
};

export const CONTEXT_CARD = {
  entity: ENTITY_VIEW,
  assembled_at: AT,
  coverage: [],
  most_recent_observation_at: null,
  limitations: ["no_source_has_been_observed", "the_memory_plane_is_unavailable"],
  is_complete: true,
  aliases: [],
  identifiers: [],
  assignments: [],
  relationships: [],
  observations: [],
  memories: [],
};

export const RELATIONSHIP = {
  relationship_id: "erel_aaaaaaaa11111111",
  is_current: true,
  from_entity_id: ENTITY_ID,
  relationship_type: "works_for",
  to_entity_id: "ent_bbbbbbbb22222222",
  scope_entity_id: null,
  state: "active",
  effective_from: null,
  effective_to: null,
  version: 1,
};

export const UNRESOLVED_MENTION = {
  observation_id: "eobs_aaaaaaaa11111111",
  kind: "document_mention",
  mention_display_name: "Pat",
  source_id: "src_aaaaaaaa11111111",
  source_object_id: "obj_aaaaaaaa11111111",
  source_version_id: "ver_aaaaaaaa11111111",
  observed_at: AT,
  recorded_at: AT,
};

export const LIFECYCLE_IDENTIFIER = {
  identifier_id: "xid_aaaaaaaa11111111",
  namespace: "email",
  display_value: "pat.synthetic@example.test",
  verified: false,
  effective_from: null,
  effective_to: null,
  state: "active",
  version: 1,
  retired_at: null,
  updated_at: AT,
  superseded_by_identifier_id: null,
};

export const LIFECYCLE_ALIAS = {
  alias_id: "eals_aaaaaaaa11111111",
  alias_type: "full_name",
  display_value: "Patricia Synthetic",
  effective_from: null,
  effective_to: null,
  state: "active",
  version: 1,
  retired_at: null,
  updated_at: AT,
  superseded_by_alias_id: null,
};

export const ASSIGNMENT = {
  assignment_id: "asn_aaaaaaaa11111111",
  entity_id: ENTITY_ID,
  assignment_type: "employment",
  scope_entity_id: "ent_bbbbbbbb22222222",
  role: "architect",
  discipline: null,
  responsibility_class: null,
  status: "active",
  is_current: true,
  effective_from: null,
  effective_to: null,
  version: 1,
};

export const RECORDED_OBSERVATION = {
  observation_id: "eobs_aaaaaaaa11111111",
  kind: "contact_record",
  authority: "source_observation",
  origin: "configured_source",
  state: "current",
  state_reason: null,
  mention_display_name: "Pat",
  source_id: "src_aaaaaaaa11111111",
  source_object_id: "obj_aaaaaaaa11111111",
  source_version_id: "ver_aaaaaaaa11111111",
  entity_id: ENTITY_ID,
  superseded_by_observation_id: null,
  resolution_version: 0,
  observed_at: AT,
  recorded_at: AT,
};

export const IDENTITY_HISTORY_ENTRY = {
  history_id: "emut_aaaaaaaa11111111",
  occurred_at: AT,
  source: "direct_mutation",
  operation: "entities.create",
  involved_entity_ids: [ENTITY_ID],
  changes: [
    {
      family: "entity",
      record_id: ENTITY_ID,
      effect_kind: "create",
      before_state: null,
      after_state: { display_name: "Pat Synthetic" },
    },
  ],
  actor_class: "user",
  actor_id: "prn_aaaaaaaa11111111",
  authority: null,
  correlation_id: null,
  audit_id: "audit_aaaaaaaa11111111",
  reason: null,
  source_identity_operation_id: null,
  receipt_id: null,
};

export const ENTITY_NAME = {
  entity_name_id: "enam_aaaaaaaa11111111",
  entity_id: ENTITY_ID,
  name_type_code: "display",
  display_value: "Pat Synthetic",
  normalized_value: "pat synthetic",
  is_preferred: true,
  effective_from: null,
  effective_to: null,
  state: "active",
  version: 1,
  updated_at: AT,
  retired_at: null,
  superseded_by_entity_name_id: null,
};

export const ENTITY_ADDRESS = {
  entity_address_id: "eadr_aaaaaaaa11111111",
  entity_id: ENTITY_ID,
  address_type_code: "office",
  raw_value: "1 Synthetic Way",
  normalized_address_value: "1 synthetic way",
  line1: "1 Synthetic Way",
  line2: null,
  city: null,
  region: null,
  postal_code: null,
  country: null,
  label: null,
  is_preferred: false,
  effective_from: null,
  effective_to: null,
  state: "active",
  version: 1,
  updated_at: AT,
  retired_at: null,
  superseded_by_entity_address_id: null,
};

export const COMMUNICATION_METHOD = {
  communication_method_id: "ecmm_aaaaaaaa11111111",
  entity_id: ENTITY_ID,
  method_type_code: "email",
  usage_context_code: "corporate",
  display_value: "pat.synthetic@example.test",
  normalized_value: "pat.synthetic@example.test",
  verification_status_code: "unresolved",
  is_preferred: true,
  effective_from: null,
  effective_to: null,
  state: "active",
  version: 1,
  updated_at: AT,
  retired_at: null,
  superseded_by_communication_method_id: null,
  linked_external_identifier_id: null,
};

export const PARTICIPATION = {
  participation_id: "eppt_aaaaaaaa11111111",
  project_entity_id: "ent_cccccccccccccccc33333333",
  participant_entity_id: ENTITY_ID,
  project_display_name: "North Pour",
  role_basis_code: "unresolved",
  stakeholder_side_code: "design",
  stakeholder_class_code: "unresolved",
  relationship_status_code: "active",
  role_code: null,
  role_text: "architect",
  discipline_code: null,
  discipline_text: null,
  scope_text: null,
  effective_from: null,
  effective_to: null,
  state: "active",
  version: 1,
  updated_at: AT,
  retired_at: null,
  superseded_by_participation_id: null,
};

export const PROFILE = {
  entity: ENTITY_VIEW,
  assembled_at: AT,
  limitations: [],
  is_complete: true,
  organization_profile: null,
  names: [ENTITY_NAME],
  addresses: [],
  communication_methods: [],
  participations_as_project: [],
  participations_as_participant: [],
  affiliations_as_person: [],
  affiliations_as_organization: [],
};
