import { ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  oneOf,
  pick,
  requiredInt,
  requiredArray,
  requiredNullableString,
  requiredString,
  requiredStringArray,
} from "./_read-helpers";

export const PROJECT_STATES = ["active", "on_hold", "closed"] as const;

export type ProjectState = (typeof PROJECT_STATES)[number];

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
