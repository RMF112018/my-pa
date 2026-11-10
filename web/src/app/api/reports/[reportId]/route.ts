import type { NextRequest } from "next/server";
import { invalidWorkRequest } from "@/lib/api/work-route";
import { isReportId, READ_FIELDS, reportsRead } from "@/lib/api/reports-route";

/** `GET /api/reports/[reportId]` -> `reports.read` of a standalone (`grpt_`) report. */
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ reportId: string }> },
) {
  const { reportId } = await context.params;
  if (!isReportId(reportId)) return invalidWorkRequest("reportId is malformed");
  return reportsRead(request, "reports.read", READ_FIELDS, { report_id: reportId });
}
