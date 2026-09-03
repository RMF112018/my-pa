import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeCommitmentView,
  pick,
  requiredBoolean,
  type CommitmentView,
} from "./_mutation-helpers";

export interface CommitmentsCreateResult {
  readonly commitment: CommitmentView;
  readonly replayed: boolean;
}

export const decodeCommitmentsCreate: Decoder<CommitmentsCreateResult> = (input) => {
  const known = pick(input, ["commitment", "replayed"]);
  if (!known.ok) return known;
  const commitment = decodeCommitmentView(known.value.commitment);
  if (!commitment.ok) return commitment;
  const replayed = requiredBoolean(known.value.replayed);
  if (!replayed.ok) return replayed;
  return ok({ commitment: commitment.value, replayed: replayed.value });
};
