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

function notFound(): NextResponse {
  const response = NextResponse.json(
    {
      error: {
        errorClass: "not_found",
        code: "not_found",
        message: "Constraint was not found",
      },
    },
    { status: 404 },
  );
  response.headers.set("cache-control", "private, no-store");
  return response;
}

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
    return notFound();
  }
  return response;
}
