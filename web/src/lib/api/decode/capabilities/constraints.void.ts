/**
 * `constraints.void`: withdraw one Constraint. Nothing is deleted.
 *
 * The shared single-record projection and disposition invariants live in
 * `_constraint-authoring-helpers.ts`; this module only names the capability.
 */
import type { Decoder } from "../types";
import {
  decodeConstraintMutationResult,
  type ConstraintMutationResult,
} from "./_constraint-authoring-helpers";

export type ConstraintsVoidResult = ConstraintMutationResult;

export const decodeConstraintsVoid: Decoder<ConstraintsVoidResult> = (input) =>
  decodeConstraintMutationResult(input);
