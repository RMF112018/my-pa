import type { NextRequest } from "next/server";
import { invalidWorkRequest, workGet } from "@/lib/api/work-route";
import {
  CONTENT_FIELDS,
  exactlyOneVersion,
  isReportId,
  REPORTS_SCOPE,
} from "@/lib/api/reports-route";

/**
 * `GET /api/reports/[reportId]/content` -> `reports.transfer.read_chunk`: one
 * verified range of one pinned version (exactly one of versionNumber/versionId).
 */
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ reportId: string }> },
) {
  const { reportId } = await context.params;
  if (!isReportId(reportId)) return invalidWorkRequest("reportId is malformed");
  return workGet(request, REPORTS_SCOPE, "reports.transfer.read_chunk", CONTENT_FIELDS, { report_id: reportId }, {
    strictQuery: true,
    validate: exactlyOneVersion,
  });
}
