import type { NextRequest } from "next/server";
import { workPost } from "@/lib/api/work-route";
export async function POST(request: NextRequest, context: { params: Promise<{ commitmentId: string }> }) {
  const { commitmentId } = await context.params;
  return workPost(request, "commitment-close", "commitments.close", {
    expectedVersion: { gateway: "expected_version", type: "integer" },
    closureEvidenceRef: { gateway: "closure_evidence_ref", type: "string" },
    idempotencyKey: { gateway: "idempotency_key", type: "string" },
    clientContext: { gateway: "client_context", type: "string" },
  }, { commitment_id: commitmentId });
}
