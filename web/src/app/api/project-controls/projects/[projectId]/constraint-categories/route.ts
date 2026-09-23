/**
 * `GET …/constraint-categories` — the Project's Category scheme, in display order.
 *
 * Its own route because it is its own capability: a Category is the Project's
 * classification rather than a record filed under one, so it reads when the
 * Register is empty and needs no Project calendar.
 *
 * `POST` (R01-WP09) adds a Category to this Project through
 * `constraint_categories.create`. The Project is the path segment's, and the
 * browser's `prefix` travels as the command's `code_segment`.
 */
import { NextResponse, type NextRequest } from "next/server";
import { workGet, workPost } from "@/lib/api/work-route";
import {
  CATEGORY_CREATE_FIELDS,
  CATEGORY_FIELDS,
  invalidPathIdentifier,
  isProjectId,
} from "@/app/api/project-controls/constraint-requests";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ projectId: string }> },
): Promise<NextResponse> {
  const { projectId } = await context.params;
  if (!isProjectId(projectId)) return invalidPathIdentifier("projectId");
  return workGet(
    request,
    "constraint-categories",
    "constraint_categories.list",
    CATEGORY_FIELDS,
    { project_id: projectId },
  );
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ projectId: string }> },
): Promise<NextResponse> {
  const { projectId } = await context.params;
  if (!isProjectId(projectId)) return invalidPathIdentifier("projectId");
  return workPost(
    request,
    "constraint-category-create",
    "constraint_categories.create",
    CATEGORY_CREATE_FIELDS,
    { project_id: projectId },
  );
}
