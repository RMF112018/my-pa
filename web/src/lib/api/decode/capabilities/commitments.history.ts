import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeCommitmentHistoryEntry,
  decodeItems,
  fail,
  pick,
  type CommitmentHistoryEntry,
} from "./_read-helpers";

export type { CommitmentHistoryEntry };

export interface CommitmentsHistoryResult {
  readonly history: readonly CommitmentHistoryEntry[];
}

export const decodeCommitmentsHistory: Decoder<CommitmentsHistoryResult> = (input) => {
  const known = pick(input, ["history"]);
  if (!known.ok) return known;
  if (known.value.history === undefined) return fail("a required array was omitted");
  const history = decodeItems(known.value.history, decodeCommitmentHistoryEntry);
  if (!history.ok) return history;
  return ok({ history: history.value });
};
