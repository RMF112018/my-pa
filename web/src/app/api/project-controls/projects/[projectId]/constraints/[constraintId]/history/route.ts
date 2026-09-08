/**
 * `GET …/constraints/[constraintId]/history` — one page of mutation receipts.
 *
 * A page size and an opaque cursor, and nothing else. The cursor is passed
 * through untouched; this tier neither reads nor rebuilds one.
 */
import { NextRequest, NextResponse } from "next/server";
import { workGet } from "@/lib/api/work-route";
import {
  HISTORY_FIELDS,
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

  // `constraints.history` is keyed only by Constraint identity. Bind that
  // read to the Project in this URL by first resolving the same-Principal
  // detail projection and comparing its backend-owned Project identity. A
  // mismatch is indistinguishable from an absent Constraint, and history is
  // never asked for it.
  const detailUrl = new URL(
    `/api/project-controls/projects/${encodeURIComponent(projectId)}/constraints/${encodeURIComponent(constraintId)}`,
    request.url,
  );
  const detailRequest = new NextRequest(detailUrl, { headers: request.headers });
  const membership = await workGet(
    detailRequest,
    "constraint-detail",
    "constraints.read",
    NO_FIELDS,
    { constraint_id: constraintId },
  );
  if (!membership.ok) {
    // Preserve the history command's nondisclosing empty-page semantics for an
    // absent/foreign-Principal Constraint. Only a detail the same Principal can
    // read can prove the cross-Project mismatch this BFF must refuse.
    if (membership.status === 404) {
      return workGet(request, "constraint-history", "constraints.history", HISTORY_FIELDS, {
        constraint_id: constraintId,
      });
    }
    return membership;
  }
  const answer = (await membership.json()) as unknown;
  if (
    !isRecord(answer) ||
    !isRecord(answer.constraint) ||
    answer.constraint.projectId !== projectId
  ) {
    return notFound();
  }
  return workGet(request, "constraint-history", "constraints.history", HISTORY_FIELDS, {
    constraint_id: constraintId,
  });
}
