import type { NextRequest } from "next/server";
import { workGet, workPost } from "@/lib/api/work-route";

const UPDATE_FIELDS = {
  expectedVersion: { gateway: "expected_version", type: "integer" },
  idempotencyKey: { gateway: "idempotency_key", type: "string" },
  title: { gateway: "title", type: "string" },
  description: { gateway: "description", type: "string" },
  priority: { gateway: "priority", type: "string" },
  dueAt: { gateway: "due_at", type: "string" },
  scheduledAt: { gateway: "scheduled_at", type: "string" },
  deferredUntil: { gateway: "deferred_until", type: "string" },
  commitmentId: { gateway: "commitment_id", type: "string" },
  role: { gateway: "role", type: "string" },
  clearFields: { gateway: "clear_fields", type: "string-array", maxItems: 7 },
  archived: { gateway: "archived", type: "boolean" },
  clientContext: { gateway: "client_context", type: "string" },
} as const;

export async function GET(request: NextRequest, context: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await context.params;
  return workGet(request, "task-detail", "tasks.read", {}, { task_id: taskId });
}
export async function PATCH(request: NextRequest, context: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await context.params;
  return workPost(request, "task-update", "tasks.update", UPDATE_FIELDS, { task_id: taskId });
}
