import type { NextRequest } from "next/server";
import { invalidWorkRequest } from "@/lib/api/work-route";
import { isReportId, reportsMutation, UPDATE_FIELDS } from "@/lib/api/reports-route";

/** `POST /api/reports/[reportId]/update` -> `reports.update` (409 carries `current`). */
export async function POST(
  request: NextRequest,
  context: { params: Promise<{ reportId: string }> },
) {
  const { reportId } = await context.params;
  if (!isReportId(reportId)) return invalidWorkRequest("reportId is malformed");
  return reportsMutation(request, "reports.update", UPDATE_FIELDS, { report_id: reportId });
}
