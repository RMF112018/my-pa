/**
 * `GET …/constraint-categories` — the Project's Category scheme, in display order.
 *
 * Its own route because it is its own capability: a Category is the Project's
 * classification rather than a record filed under one, so it reads when the
 * Register is empty and needs no Project calendar.
 */
import { NextResponse, type NextRequest } from "next/server";
import { workGet } from "@/lib/api/work-route";
import {
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
