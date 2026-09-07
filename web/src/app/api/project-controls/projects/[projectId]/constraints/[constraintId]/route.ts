/**
 * `GET …/constraints/[constraintId]` — one Constraint in full.
 *
 * The payload is the constraint id alone: `ReadConstraint` resolves the Project
 * from the record itself, so a caller cannot name a Project the record does not
 * belong to. Relationships and evidence links are members of this projection —
 * there are deliberately no separate routes for them.
 */
import { NextResponse, type NextRequest } from "next/server";
import { workGet } from "@/lib/api/work-route";
import {
  invalidPathIdentifier,
  isConstraintId,
  isProjectId,
  NO_FIELDS,
} from "@/app/api/project-controls/constraint-requests";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ projectId: string; constraintId: string }> },
): Promise<NextResponse> {
  const { projectId, constraintId } = await context.params;
  if (!isProjectId(projectId)) return invalidPathIdentifier("projectId");
  if (!isConstraintId(constraintId)) return invalidPathIdentifier("constraintId");
  return workGet(request, "constraint-detail", "constraints.read", NO_FIELDS, {
    constraint_id: constraintId,
  });
}
