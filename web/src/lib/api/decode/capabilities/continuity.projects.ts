import { ok, type DecodeResult } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeItems,
  fail,
  oneOf,
  pick,
  requiredNullableString,
  requiredString,
  requiredStringArray,
} from "./_read-helpers";

export const PROJECT_STATES = ["active", "on_hold", "closed"] as const;

export type ProjectState = (typeof PROJECT_STATES)[number];

export interface ProjectRow {
  readonly project_id: string;
  readonly name: string;
  readonly state: ProjectState;
  readonly description: string | null;
  readonly participants: readonly string[];
  readonly opened_at: string;
  readonly closed_at: string | null;
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
  "opened_at",
  "closed_at",
] as const;

function decodeProject(input: unknown): DecodeResult<ProjectRow> {
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
  const openedAt = requiredString(known.value.opened_at);
  if (!openedAt.ok) return openedAt;
  const closedAt = requiredNullableString(known.value.closed_at);
  if (!closedAt.ok) return closedAt;
  return ok({
    project_id: projectId.value,
    name: name.value,
    state: state.value,
    description: description.value,
    participants: participants.value,
    opened_at: openedAt.value,
    closed_at: closedAt.value,
  });
}

export const decodeContinuityProjects: Decoder<ContinuityProjectsResult> = (input) => {
  const known = pick(input, ["projects"]);
  if (!known.ok) return known;
  if (known.value.projects === undefined) {
    return fail("a required array was omitted");
  }
  const projects = decodeItems(known.value.projects, decodeProject);
  if (!projects.ok) return projects;
  return ok({ projects: projects.value });
};
