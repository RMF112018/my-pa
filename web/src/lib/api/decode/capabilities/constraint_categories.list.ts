/**
 * `constraint_categories.list`: one Project's Category scheme, in display order.
 *
 * `prefixLocked` is published by the backend and is never inferred here from
 * whether a Register row happens to exist under the prefix.
 */
import { ok } from "../primitives";
import type { Decoder } from "../types";
import {
  decodeConstraintCategory,
  type ConstraintCategory,
} from "./_constraint-helpers";
import { decodeItems, fail, pick } from "./_read-helpers";

export type { ConstraintCategory };

export interface ConstraintCategoriesListResult {
  readonly categories: readonly ConstraintCategory[];
}

export const decodeConstraintCategoriesList: Decoder<ConstraintCategoriesListResult> = (
  input,
) => {
  const known = pick(input, ["categories"]);
  if (!known.ok) return known;
  if (known.value.categories === undefined) return fail("a required array was omitted");
  const categories = decodeItems(known.value.categories, decodeConstraintCategory);
  if (!categories.ok) return categories;
  return ok({ categories: categories.value });
};
