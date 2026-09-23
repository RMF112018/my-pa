/**
 * `constraints.update`: a bounded field patch. A patch that changes nothing is a `no_op` with an unmoved version.
 *
 * The shared single-record projection and disposition invariants live in
 * `_constraint-authoring-helpers.ts`; this module only names the capability.
 */
import type { Decoder } from "../types";
import {
  decodeConstraintMutationResult,
  type ConstraintMutationResult,
} from "./_constraint-authoring-helpers";

export type ConstraintsUpdateResult = ConstraintMutationResult;

export const decodeConstraintsUpdate: Decoder<ConstraintsUpdateResult> = (input) =>
  decodeConstraintMutationResult(input);
