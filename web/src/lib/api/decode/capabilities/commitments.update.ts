import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeCommitmentHistoryEntry,
  decodeCommitmentView,
  pick,
  requiredBoolean,
  type CommitmentHistoryEntry,
  type CommitmentView,
} from "./_mutation-helpers";

export interface CommitmentsUpdateResult {
  readonly commitment: CommitmentView;
  readonly history: CommitmentHistoryEntry;
  readonly replayed: boolean;
}

export const decodeCommitmentsUpdate: Decoder<CommitmentsUpdateResult> = (input) => {
  const known = pick(input, ["commitment", "history", "replayed"]);
  if (!known.ok) return known;
  const commitment = decodeCommitmentView(known.value.commitment);
  if (!commitment.ok) return commitment;
  const history = decodeCommitmentHistoryEntry(known.value.history);
  if (!history.ok) return history;
  const replayed = requiredBoolean(known.value.replayed);
  if (!replayed.ok) return replayed;
  return ok({
    commitment: commitment.value,
    history: history.value,
    replayed: replayed.value,
  });
};
