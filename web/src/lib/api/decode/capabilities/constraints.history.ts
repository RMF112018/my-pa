/**
 * `constraints.history`: one bounded page of a Constraint's mutation receipts.
 *
 * `before_version` and `after_version` are the backend's own; a receipt whose
 * versions are missing or unreadable is a malformed success, not a receipt with
 * an unknown version.
 */
import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeConstraintHistoryEntry,
  type ConstraintHistoryEntry,
} from "./_constraint-helpers";
import { decodeItems, fail, pick } from "./_read-helpers";

export type { ConstraintHistoryEntry };

export interface ConstraintsHistoryResult {
  readonly history: readonly ConstraintHistoryEntry[];
}

export const decodeConstraintsHistory: Decoder<ConstraintsHistoryResult> = (input) => {
  const known = pick(input, ["history"]);
  if (!known.ok) return known;
  if (known.value.history === undefined) return fail("a required array was omitted");
  const history = decodeItems(known.value.history, decodeConstraintHistoryEntry);
  if (!history.ok) return history;
  return ok({ history: history.value });
};
