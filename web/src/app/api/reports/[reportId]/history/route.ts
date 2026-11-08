import type { NextRequest } from "next/server";
import { invalidWorkRequest, workGet } from "@/lib/api/work-route";
import { HISTORY_FIELDS, isReportId, REPORTS_SCOPE } from "@/lib/api/reports-route";

/** `GET /api/reports/[reportId]/history` -> `reports.history`. */
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ reportId: string }> },
) {
  const { reportId } = await context.params;
  if (!isReportId(reportId)) return invalidWorkRequest("reportId is malformed");
  return workGet(request, REPORTS_SCOPE, "reports.history", HISTORY_FIELDS, { report_id: reportId }, {
    strictQuery: true,
  });
}
