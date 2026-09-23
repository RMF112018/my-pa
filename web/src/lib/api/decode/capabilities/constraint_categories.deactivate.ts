/**
 * `constraint_categories.deactivate`: retire one Category from new Publishes. The backend records it as an `update`; deactivating an inactive Category is a `no_op`.
 *
 * The Category record has no version of its own, so the result's
 * `category.version` is the receipt's `afterVersion` — a mutation version that
 * is authoritative only until the canonical Category list is refetched.
 */
import type { Decoder } from "../types";
import {
  decodeCategoryMutationResult,
  type ConstraintCategoryMutationResult,
} from "./_constraint-authoring-helpers";

export type ConstraintCategoriesDeactivateResult = ConstraintCategoryMutationResult;

export const decodeConstraintCategoriesDeactivate: Decoder<ConstraintCategoriesDeactivateResult> = (
  input,
) => decodeCategoryMutationResult(input);
