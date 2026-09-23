/**
 * `constraint_categories.create`: one new Category in the Project's scheme.
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

export type ConstraintCategoriesCreateResult = ConstraintCategoryMutationResult;

export const decodeConstraintCategoriesCreate: Decoder<ConstraintCategoriesCreateResult> = (
  input,
) => decodeCategoryMutationResult(input);
