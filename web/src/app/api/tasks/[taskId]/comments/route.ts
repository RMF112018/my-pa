import type { NextRequest } from "next/server";
import { workGet, workPost } from "@/lib/api/work-route";

export async function GET(request: NextRequest, context: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await context.params;
  return workGet(request, "task-comments", "tasks.comments.list", {
    pageSize: { gateway: "page_size", type: "integer" },
    after: { gateway: "after", type: "string" },
  }, { task_id: taskId });
}

export async function POST(request: NextRequest, context: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await context.params;
  return workPost(request, "task-comments", "tasks.comments.create", {
    body: { gateway: "body", type: "string" },
    idempotencyKey: { gateway: "idempotency_key", type: "string" },
    clientContext: { gateway: "client_context", type: "string" },
  }, { task_id: taskId });
}
