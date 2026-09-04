/**
 * One Intelligence artifact by identifier — `reports.read`.
 */
import { NextResponse, type NextRequest } from "next/server";
import { intelligenceGet, invalidIdentifier, optionalBoolean } from "../dispatch";

const IDENTIFIER = /^[a-z]+_[A-Za-z0-9]{8,64}$/;

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ reportId: string }> },
) {
  const { reportId } = await context.params;
  if (!IDENTIFIER.test(reportId)) return invalidIdentifier("reportId");
  const includeBody = optionalBoolean(request.nextUrl.searchParams.get("includeBody"), "includeBody");
  if (includeBody instanceof NextResponse) return includeBody;
  return intelligenceGet(request, "reports.read", {
    report_id: reportId,
    ...(includeBody !== undefined ? { include_body: includeBody } : {}),
  });
}
