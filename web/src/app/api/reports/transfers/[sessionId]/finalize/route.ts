import type { NextRequest } from "next/server";
import { invalidWorkRequest } from "@/lib/api/work-route";
import { isTransferSessionId, reportsMutation } from "@/lib/api/reports-route";

/** `POST /api/reports/transfers/[sessionId]/finalize` -> `reports.transfer.finalize` (empty body or `{}`). */
export async function POST(
  request: NextRequest,
  context: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await context.params;
  if (!isTransferSessionId(sessionId)) return invalidWorkRequest("sessionId is malformed");
  return reportsMutation(request, "reports.transfer.finalize", {}, { session_id: sessionId }, { bodyOptional: true });
}
