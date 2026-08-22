import type { NextRequest } from "next/server";
import { workGet, workPost } from "@/lib/api/work-route";
export async function GET(request: NextRequest, context: { params: Promise<{ commitmentId: string }> }) {
  const { commitmentId } = await context.params;
  return workGet(request, "commitment-detail", "commitments.read", {}, { commitment_id: commitmentId });
}
export async function PATCH(request: NextRequest, context: { params: Promise<{ commitmentId: string }> }) {
  const { commitmentId } = await context.params;
  return workPost(request, "commitment-update", "commitments.update", {
    expectedVersion: { gateway: "expected_version", type: "integer" },
    idempotencyKey: { gateway: "idempotency_key", type: "string" },
    summary: { gateway: "summary", type: "string" },
    dueAt: { gateway: "due_at", type: "string" },
    counterpartyPersonId: { gateway: "counterparty_person_id", type: "string" },
    clearDueAt: { gateway: "clear_due_at", type: "boolean" },
    clientContext: { gateway: "client_context", type: "string" },
  }, { commitment_id: commitmentId });
}
