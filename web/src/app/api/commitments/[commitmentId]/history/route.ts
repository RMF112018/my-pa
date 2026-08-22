import type { NextRequest } from "next/server";
import { workGet } from "@/lib/api/work-route";
export async function GET(request: NextRequest, context: { params: Promise<{ commitmentId: string }> }) {
  const { commitmentId } = await context.params;
  return workGet(request, "commitment-history", "commitments.history", {
    pageSize: { gateway: "page_size", type: "integer" },
    after: { gateway: "after", type: "string" },
  }, { commitment_id: commitmentId });
}
