import type { NextRequest } from "next/server";
import {
  invalidWorkRequest,
  isCanonicalId,
  workPost,
} from "@/lib/api/work-route";

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ projectId: string }> },
) {
  const { projectId } = await context.params;
  if (!isCanonicalId(projectId, "prj")) {
    return invalidWorkRequest("projectId is malformed");
  }
  return workPost(request, "project-close", "continuity.projects.close", {
    expectedVersion: {
      gateway: "expected_version", type: "integer", required: true, minimum: 1,
    },
    idempotencyKey: {
      gateway: "idempotency_key", type: "string", required: true,
      minLength: 8, maxLength: 128, pattern: /^[A-Za-z0-9_-]{8,128}$/,
    },
  }, { project_id: projectId }, { strictQuery: true });
}
