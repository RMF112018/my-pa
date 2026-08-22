import type { NextRequest } from "next/server";
import { workPost } from "@/lib/api/work-route";

export function POST(request: NextRequest) {
  return workPost(request, "task-bulk-preview", "tasks.bulk_preview", {
    mutations: { gateway: "mutations", type: "mutation-array", maxItems: 100 },
    idempotencyKey: { gateway: "idempotency_key", type: "string" },
  });
}
