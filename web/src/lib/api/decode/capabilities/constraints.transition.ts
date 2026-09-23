/**
 * `constraints.transition`: one active-state move. A move to the current state is the accepted `no_op`.
 *
 * The shared single-record projection and disposition invariants live in
 * `_constraint-authoring-helpers.ts`; this module only names the capability.
 */
import type { Decoder } from "../types";
import {
  decodeConstraintMutationResult,
  type ConstraintMutationResult,
} from "./_constraint-authoring-helpers";

export type ConstraintsTransitionResult = ConstraintMutationResult;

export const decodeConstraintsTransition: Decoder<ConstraintsTransitionResult> = (input) =>
  decodeConstraintMutationResult(input);
