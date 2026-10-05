import type { Decoder } from "../types";
import { strictObject, nullable, arrayOf, checked, text, integer, boolean, enumeration, identifier, timestamp, type Decoded } from "./continuity.projects.create";

const participation = strictObject({
  participant_entity_id: identifier("ent"), role_code: nullable(text()),
  relationship_status_code: enumeration(["active", "completed", "terminated", "on_hold", "unresolved"]),
  participation_id: identifier("eppt"), state: enumeration(["active"]),
});
export const projectMutation = checked(strictObject({
  project_id: identifier("prj"), name: checked(text(1), (value) => /[^\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/u.test(value)), state: enumeration(["active", "on_hold", "closed"]),
  description: nullable(text()), participants: arrayOf(text()), canonical_participations: arrayOf(participation),
  opened_at: timestamp, closed_at: nullable(timestamp), created_at: timestamp, updated_at: timestamp,
  version: integer(1), replayed: boolean,
}), (value) => (value.state === "closed") === (value.closed_at !== null));
export type ContinuityProjectsUpdateResult = Decoded<typeof projectMutation>;
export const decodeContinuityProjectsUpdate: Decoder<ContinuityProjectsUpdateResult> = projectMutation;
