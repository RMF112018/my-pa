/**
 * `POST …/constraints/drafts` — create a Draft Constraint in this Project.
 *
 * `constraints.create`: the Project is the path segment's and never the body's,
 * and a Draft may be as incomplete as its author likes — whether it is complete
 * enough to publish is the domain's decision at Publish, not this transport's.
 * Everything else is `workPost`'s, so this handler is a path guard and a call.
 */
import { NextResponse, type NextRequest } from "next/server";
import { workPost } from "@/lib/api/work-route";
import {
  CONSTRAINT_CREATE_DRAFT_FIELDS,
  invalidPathIdentifier,
  isProjectId,
} from "@/app/api/project-controls/constraint-requests";

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ projectId: string }> },
): Promise<NextResponse> {
  const { projectId } = await context.params;
  if (!isProjectId(projectId)) return invalidPathIdentifier("projectId");
  return workPost(
    request,
    "constraint-create",
    "constraints.create",
    CONSTRAINT_CREATE_DRAFT_FIELDS,
    { project_id: projectId },
  );
}
