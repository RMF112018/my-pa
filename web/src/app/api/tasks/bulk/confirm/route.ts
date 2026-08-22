import type { NextRequest } from "next/server";
import { workPost } from "@/lib/api/work-route";

export function POST(request: NextRequest) {
  return workPost(request, "task-bulk-confirm", "tasks.bulk_confirm", {
    bulkOperationId: { gateway: "bulk_operation_id", type: "string" },
    idempotencyKey: { gateway: "idempotency_key", type: "string" },
    mutations: { gateway: "mutations", type: "mutation-array", maxItems: 100 },
  });
}
