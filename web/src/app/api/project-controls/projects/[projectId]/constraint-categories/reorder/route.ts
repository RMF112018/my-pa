/**
 * `POST …/constraint-categories/reorder` — `constraint_categories.reorder`.
 *
 * The whole Project's display order in one command: the ids in their new order
 * and each one's expected version. The Project is the path segment's, so no
 * preflight is needed. `validateCategoryReorder` refuses the shape rules no
 * single field can state (non-empty, Category ids only, no repeats, one version
 * per id) before dispatch; whether the list is the Project's complete active
 * set, and whether each version is current, is the backend's to decide.
 *
 * A static segment, so Next.js resolves it ahead of the dynamic
 * `[categoryId]` sibling.
 */
import { NextResponse, type NextRequest } from "next/server";
import { workPost } from "@/lib/api/work-route";
import {
  CATEGORY_REORDER_FIELDS,
  invalidPathIdentifier,
  isProjectId,
  validateCategoryReorder,
} from "@/app/api/project-controls/constraint-requests";

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ projectId: string }> },
): Promise<NextResponse> {
  const { projectId } = await context.params;
  if (!isProjectId(projectId)) return invalidPathIdentifier("projectId");
  return workPost(
    request,
    "constraint-category-reorder",
    "constraint_categories.reorder",
    CATEGORY_REORDER_FIELDS,
    { project_id: projectId },
    { validate: validateCategoryReorder },
  );
}
