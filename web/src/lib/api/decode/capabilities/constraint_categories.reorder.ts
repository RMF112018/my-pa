/**
 * `constraint_categories.reorder`: set the whole display order of a Project's Categories atomically.
 *
 * `applied` carries one receipt per Category, aligned by position, with each
 * `displayOrder` equal to its index; `replayed` carries the full scheme and the
 * single keyed receipt of the first Category.
 */
import type { Decoder } from "../types";
import {
  decodeCategoryReorderResult,
  type ConstraintCategoryReorderResult,
} from "./_constraint-authoring-helpers";

export type ConstraintCategoriesReorderResult = ConstraintCategoryReorderResult;

export const decodeConstraintCategoriesReorder: Decoder<ConstraintCategoriesReorderResult> = (
  input,
) => decodeCategoryReorderResult(input);
