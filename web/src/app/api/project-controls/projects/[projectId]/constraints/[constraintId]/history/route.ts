/**
 * `GET …/constraints/[constraintId]/history` — one page of mutation receipts.
 *
 * A page size and an opaque cursor, and nothing else. The cursor is passed
 * through untouched; this tier neither reads nor rebuilds one.
 */
import { NextResponse, type NextRequest } from "next/server";
import { workGet } from "@/lib/api/work-route";
import {
  HISTORY_FIELDS,
  invalidPathIdentifier,
  isConstraintId,
  isProjectId,
} from "@/app/api/project-controls/constraint-requests";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ projectId: string; constraintId: string }> },
): Promise<NextResponse> {
  const { projectId, constraintId } = await context.params;
  if (!isProjectId(projectId)) return invalidPathIdentifier("projectId");
  if (!isConstraintId(constraintId)) return invalidPathIdentifier("constraintId");
  return workGet(request, "constraint-history", "constraints.history", HISTORY_FIELDS, {
    constraint_id: constraintId,
  });
}
