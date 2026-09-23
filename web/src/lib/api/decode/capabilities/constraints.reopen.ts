/**
 * `constraints.reopen`: return one closed or void Constraint to an active state.
 *
 * The shared single-record projection and disposition invariants live in
 * `_constraint-authoring-helpers.ts`; this module only names the capability.
 */
import type { Decoder } from "../types";
import {
  decodeConstraintMutationResult,
  type ConstraintMutationResult,
} from "./_constraint-authoring-helpers";

export type ConstraintsReopenResult = ConstraintMutationResult;

export const decodeConstraintsReopen: Decoder<ConstraintsReopenResult> = (input) =>
  decodeConstraintMutationResult(input);
