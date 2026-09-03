import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeCommitmentView,
  pick,
  requiredBoolean,
  type CommitmentView,
} from "./_mutation-helpers";

export interface CommitmentsCloseResult {
  readonly commitment: CommitmentView;
  readonly replayed: boolean;
}

export const decodeCommitmentsClose: Decoder<CommitmentsCloseResult> = (input) => {
  const known = pick(input, ["commitment", "replayed"]);
  if (!known.ok) return known;
  const commitment = decodeCommitmentView(known.value.commitment);
  if (!commitment.ok) return commitment;
  const replayed = requiredBoolean(known.value.replayed);
  if (!replayed.ok) return replayed;
  return ok({ commitment: commitment.value, replayed: replayed.value });
};
