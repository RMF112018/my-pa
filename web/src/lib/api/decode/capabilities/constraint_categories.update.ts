/**
 * `constraint_categories.update`: revise one Category's prefix, title, description or display order.
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

export type ConstraintCategoriesUpdateResult = ConstraintCategoryMutationResult;

export const decodeConstraintCategoriesUpdate: Decoder<ConstraintCategoriesUpdateResult> = (
  input,
) => decodeCategoryMutationResult(input);
