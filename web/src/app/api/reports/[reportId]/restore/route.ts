import type { NextRequest } from "next/server";
import { invalidWorkRequest } from "@/lib/api/work-route";
import { isReportId, LIFECYCLE_FIELDS, reportsMutation } from "@/lib/api/reports-route";

/** `POST /api/reports/[reportId]/restore` -> `reports.restore` (409 carries `current`). */
export async function POST(
  request: NextRequest,
  context: { params: Promise<{ reportId: string }> },
) {
  const { reportId } = await context.params;
  if (!isReportId(reportId)) return invalidWorkRequest("reportId is malformed");
  return reportsMutation(request, "reports.restore", LIFECYCLE_FIELDS, { report_id: reportId });
}
