/**
 * `POST …/constraint-categories/[categoryId]/deactivate` —
 * `constraint_categories.deactivate`: retire one Category from new filings.
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
  CATEGORY_DEACTIVATE_FIELDS,
  invalidPathIdentifier,
  isCategoryId,
  isProjectId,
} from "@/app/api/project-controls/constraint-requests";

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ projectId: string; categoryId: string }> },
): Promise<NextResponse> {
  const { projectId, categoryId } = await context.params;
  if (!isProjectId(projectId)) return invalidPathIdentifier("projectId");
  if (!isCategoryId(categoryId)) return invalidPathIdentifier("categoryId");
  return workPost(
    request,
    "constraint-category-deactivate",
    "constraint_categories.deactivate",
    CATEGORY_DEACTIVATE_FIELDS,
    { category_id: categoryId },
    { admit: admitExistingCategory(projectId, categoryId) },
  );
}
