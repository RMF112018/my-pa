/**
 * `GET …/constraints/[constraintId]` — one Constraint in full.
 *
 * The payload is the constraint id alone: `ReadConstraint` resolves the Project
 * from the record itself, so a caller cannot name a Project the record does not
 * belong to. Relationships and evidence links are members of this projection —
 * there are deliberately no separate routes for them.
 *
 * `PATCH` (R01-WP09) edits the Constraint through `constraints.update`. The
 * command is keyed by `constraint_id` alone, so the exact-Project preflight
 * (`admitExistingConstraint`) is what binds the write to this URL's Project; a
 * record elsewhere is answered with this route's own not-found. No `project_id`
 * is sent: on `UpdateConstraint` it means "move to this Project", and no move is
 * browser-reachable (plan D6).
 */
import { NextResponse, type NextRequest } from "next/server";
import { workGet, workPost } from "@/lib/api/work-route";
import { admitExistingConstraint } from "@/app/api/project-controls/constraint-mutation-admission";
import {
  CONSTRAINT_UPDATE_FIELDS,
  constraintNotFound,
  invalidPathIdentifier,
  isConstraintId,
  isProjectId,
  NO_FIELDS,
} from "@/app/api/project-controls/constraint-requests";

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ projectId: string; constraintId: string }> },
): Promise<NextResponse> {
  const { projectId, constraintId } = await context.params;
  if (!isProjectId(projectId)) return invalidPathIdentifier("projectId");
  if (!isConstraintId(constraintId)) return invalidPathIdentifier("constraintId");
  const response = await workGet(request, "constraint-detail", "constraints.read", NO_FIELDS, {
    constraint_id: constraintId,
  });
  if (!response.ok) return response;
  const answer = (await response.clone().json()) as unknown;
  if (
    !isRecord(answer) ||
    !isRecord(answer.constraint) ||
    answer.constraint.projectId !== projectId
  ) {
    return constraintNotFound();
  }
  return response;
}

export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ projectId: string; constraintId: string }> },
): Promise<NextResponse> {
  const { projectId, constraintId } = await context.params;
  if (!isProjectId(projectId)) return invalidPathIdentifier("projectId");
  if (!isConstraintId(constraintId)) return invalidPathIdentifier("constraintId");
  return workPost(
    request,
    "constraint-update",
    "constraints.update",
    CONSTRAINT_UPDATE_FIELDS,
    { constraint_id: constraintId },
    { admit: admitExistingConstraint(projectId, constraintId) },
  );
}
