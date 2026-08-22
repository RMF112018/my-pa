import type { NextRequest } from "next/server";
import { workPost } from "@/lib/api/work-route";
export async function POST(request: NextRequest, context: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await context.params;
  return workPost(request, "task-transition", "tasks.transition", {
    toState: { gateway: "to_state", type: "string" },
    expectedVersion: { gateway: "expected_version", type: "integer" },
    idempotencyKey: { gateway: "idempotency_key", type: "string" },
    closureEvidenceRef: { gateway: "closure_evidence_ref", type: "string" },
    clientContext: { gateway: "client_context", type: "string" },
  }, { task_id: taskId });
}
