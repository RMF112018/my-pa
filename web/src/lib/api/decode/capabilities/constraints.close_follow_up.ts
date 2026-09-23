/**
 * `constraints.close_follow_up`: close one Constraint and publish its successor as one atomic operation. Both records, both receipts and the `FOLLOW_UP_OF` edge arrive together or not at all.
 *
 * Predecessor and successor are each checked against their own receipt with
 * the shared disposition rule; a replay may carry records newer than the
 * original receipts, and `no_op` is not a disposition this capability emits.
 */
import type { Decoder } from "../types";
import {
  decodeConstraintFollowUpResult,
  type ConstraintFollowUpResult,
} from "./_constraint-authoring-helpers";

export type ConstraintsCloseFollowUpResult = ConstraintFollowUpResult;

export const decodeConstraintsCloseFollowUp: Decoder<ConstraintsCloseFollowUpResult> = (input) =>
  decodeConstraintFollowUpResult(input);
