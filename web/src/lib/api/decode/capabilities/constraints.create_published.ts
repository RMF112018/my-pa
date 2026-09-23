/**
 * `constraints.create_published`: mint and publish in one transaction. The receipt is the *publication* receipt, the second of the two the composite writes; a replay recovers that same one.
 *
 * The shared single-record projection and disposition invariants live in
 * `_constraint-authoring-helpers.ts`; this module only names the capability.
 */
import type { Decoder } from "../types";
import {
  decodeConstraintMutationResult,
  type ConstraintMutationResult,
} from "./_constraint-authoring-helpers";

export type ConstraintsCreatePublishedResult = ConstraintMutationResult;

export const decodeConstraintsCreatePublished: Decoder<ConstraintsCreatePublishedResult> = (
  input,
) => decodeConstraintMutationResult(input);
