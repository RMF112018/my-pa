import { ok } from "../primitives";
import type { Decoder } from "../types";
import { decodeItems, fail, pick } from "./_read-helpers";
import { decodeAssignmentView, type AssignmentView } from "./_entity-read-helpers";

export type { AssignmentView };

export interface EntitiesAssignmentsListResult {
  readonly assignments: readonly AssignmentView[];
}

export const decodeEntitiesAssignmentsList: Decoder<EntitiesAssignmentsListResult> = (input) => {
  const known = pick(input, ["assignments"]);
  if (!known.ok) return known;
  if (known.value.assignments === undefined) return fail("a required array was omitted");
  const assignments = decodeItems(known.value.assignments, decodeAssignmentView);
  if (!assignments.ok) return assignments;
  return ok({ assignments: assignments.value });
};
