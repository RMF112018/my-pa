/**
 * `PATCH …/constraint-categories/[categoryId]` — `constraint_categories.update`:
 * rename, re-prefix, re-describe or re-position one Category. State is not
 * settable here; deactivation is its own route.
 *
 * The command is keyed by `category_id` alone, so `admitExistingCategory`
 * requires the path Category to be a member of this URL's Project before the
 * write is dispatched; otherwise the answer is a nondisclosing not-found and
 * the mutation is never sent. The static `reorder` sibling is resolved by
 * Next.js ahead of this dynamic segment, and `reorder` is not a Category id in
 * any case, so the two cannot be confused.
 */
import { NextResponse, type NextRequest } from "next/server";
import { workPost } from "@/lib/api/work-route";
import { admitExistingCategory } from "@/app/api/project-controls/constraint-mutation-admission";
import {
  CATEGORY_UPDATE_FIELDS,
  invalidPathIdentifier,
  isCategoryId,
  isProjectId,
} from "@/app/api/project-controls/constraint-requests";

export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ projectId: string; categoryId: string }> },
): Promise<NextResponse> {
  const { projectId, categoryId } = await context.params;
  if (!isProjectId(projectId)) return invalidPathIdentifier("projectId");
  if (!isCategoryId(categoryId)) return invalidPathIdentifier("categoryId");
  return workPost(
    request,
    "constraint-category-update",
    "constraint_categories.update",
    CATEGORY_UPDATE_FIELDS,
    { category_id: categoryId },
    { admit: admitExistingCategory(projectId, categoryId) },
  );
}
