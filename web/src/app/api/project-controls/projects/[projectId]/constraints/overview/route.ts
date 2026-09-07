/**
 * `GET …/constraints/overview` — the Project's Constraint position, counted once.
 *
 * No query at all. `ReadConstraintOverview` takes a Project and nothing else,
 * because the overview is one aggregate over the set the Register pages and a
 * filter here would be a second definition of what is being counted.
 */
import { NextResponse, type NextRequest } from "next/server";
import { workGet } from "@/lib/api/work-route";
import {
  invalidPathIdentifier,
  isProjectId,
  NO_FIELDS,
} from "@/app/api/project-controls/constraint-requests";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ projectId: string }> },
): Promise<NextResponse> {
  const { projectId } = await context.params;
  if (!isProjectId(projectId)) return invalidPathIdentifier("projectId");
  return workGet(request, "constraint-overview", "constraints.overview", NO_FIELDS, {
    project_id: projectId,
  });
}
