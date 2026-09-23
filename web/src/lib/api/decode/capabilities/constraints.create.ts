/**
 * `constraints.create`: mint one Draft. The receipt is the `create` one, `before_version` 0.
 *
 * The shared single-record projection and disposition invariants live in
 * `_constraint-authoring-helpers.ts`; this module only names the capability.
 */
import type { Decoder } from "../types";
import {
  decodeConstraintMutationResult,
  type ConstraintMutationResult,
} from "./_constraint-authoring-helpers";

export type ConstraintsCreateResult = ConstraintMutationResult;

export const decodeConstraintsCreate: Decoder<ConstraintsCreateResult> = (input) =>
  decodeConstraintMutationResult(input);
