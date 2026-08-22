import type { NextRequest } from "next/server";
import { workGet } from "@/lib/api/work-route";
export async function GET(request: NextRequest, context: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await context.params;
  return workGet(request, "task-history", "tasks.history", {
    pageSize: { gateway: "page_size", type: "integer" },
    after: { gateway: "after", type: "string" },
  }, { task_id: taskId });
}
