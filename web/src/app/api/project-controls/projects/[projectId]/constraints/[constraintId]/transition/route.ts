/**
 * `POST …/constraints/[constraintId]/transition` — `constraints.transition`: move a published Constraint to another active state; which moves are legal
 * is the backend's lifecycle graph and is not restated here.
 *
 * The command is keyed by `constraint_id` alone, so `admitExistingConstraint`
 * binds the write to this URL's Project before it is dispatched: a record in
 * another Project gets the detail read's own not-found and the mutation is
 * never sent. Origin admission, the session Principal, the clean body and the
 * closed field map are `workPost`'s; this handler is path guards and one call.
 */
import { NextResponse, type NextRequest } from "next/server";
import { workPost } from "@/lib/api/work-route";
import { admitExistingConstraint } from "@/app/api/project-controls/constraint-mutation-admission";
import {
  CONSTRAINT_TRANSITION_FIELDS,
  invalidPathIdentifier,
  isConstraintId,
  isProjectId,
} from "@/app/api/project-controls/constraint-requests";

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ projectId: string; constraintId: string }> },
): Promise<NextResponse> {
  const { projectId, constraintId } = await context.params;
  if (!isProjectId(projectId)) return invalidPathIdentifier("projectId");
  if (!isConstraintId(constraintId)) return invalidPathIdentifier("constraintId");
  return workPost(
    request,
    "constraint-transition",
    "constraints.transition",
    CONSTRAINT_TRANSITION_FIELDS,
    { constraint_id: constraintId },
    { admit: admitExistingConstraint(projectId, constraintId) },
  );
}
