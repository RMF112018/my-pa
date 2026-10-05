import type { NextRequest } from "next/server";
import {
  invalidWorkRequest,
  isCanonicalId,
  workPost,
} from "@/lib/api/work-route";

export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ captureId: string }> },
) {
  const { captureId } = await context.params;
  if (!isCanonicalId(captureId, "cap")) {
    return invalidWorkRequest("captureId is malformed");
  }
  return workPost(request, "capture-revise", "capture.revise", {
    text: {
      gateway: "text", type: "string", required: true, nonBlank: true,
      maxLength: 100_000, codePointLength: true,
    },
    idempotencyKey: {
      gateway: "idempotency_key", type: "string", required: true,
      minLength: 1, maxLength: 128, codePointLength: true,
    },
    clientCreatedAt: {
      gateway: "client_created_at", type: "string", nullable: true, format: "timestamp",
    },
    occurredAt: {
      gateway: "occurred_at", type: "string", nullable: true, format: "timestamp",
    },
  }, { capture_id: captureId }, {
    strictQuery: true,
    // Dispatch directly: the backend resolves an existing key before lifecycle admission.
    project(result) {
      return Object.fromEntries(Object.entries(result).filter(([key]) => key !== "idempotency_key"));
    },
  });
}
