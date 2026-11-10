import type { NextRequest } from "next/server";
import { invalidWorkRequest } from "@/lib/api/work-route";
import { isTransferSessionId, reportsMutation, TRANSFER_APPEND_FIELDS } from "@/lib/api/reports-route";

/** `POST /api/reports/transfers/[sessionId]/append` -> `reports.transfer.append`. */
export async function POST(
  request: NextRequest,
  context: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await context.params;
  if (!isTransferSessionId(sessionId)) return invalidWorkRequest("sessionId is malformed");
  return reportsMutation(request, "reports.transfer.append", TRANSFER_APPEND_FIELDS, { session_id: sessionId });
}
