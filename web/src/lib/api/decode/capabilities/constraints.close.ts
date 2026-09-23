/**
 * `constraints.close`: close one Constraint and record how.
 *
 * The shared single-record projection and disposition invariants live in
 * `_constraint-authoring-helpers.ts`; this module only names the capability.
 */
import type { Decoder } from "../types";
import {
  decodeConstraintMutationResult,
  type ConstraintMutationResult,
} from "./_constraint-authoring-helpers";

export type ConstraintsCloseResult = ConstraintMutationResult;

export const decodeConstraintsClose: Decoder<ConstraintsCloseResult> = (input) =>
  decodeConstraintMutationResult(input);
