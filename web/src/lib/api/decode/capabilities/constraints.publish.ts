/**
 * `constraints.publish`: a Draft leaves Draft and gains its public code under the Category lock.
 *
 * The shared single-record projection and disposition invariants live in
 * `_constraint-authoring-helpers.ts`; this module only names the capability.
 */
import type { Decoder } from "../types";
import {
  decodeConstraintMutationResult,
  type ConstraintMutationResult,
} from "./_constraint-authoring-helpers";

export type ConstraintsPublishResult = ConstraintMutationResult;

export const decodeConstraintsPublish: Decoder<ConstraintsPublishResult> = (input) =>
  decodeConstraintMutationResult(input);
