/**
 * Current-head Intelligence artifact — `reports.latest`.
 */
import { NextResponse, type NextRequest } from "next/server";
import {
  intelligenceGet,
  invalidField,
  optionalIdentifier,
  optionalString,
} from "../dispatch";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const cycleRunId = optionalIdentifier(params.get("cycleRunId"), "cycleRunId");
  if (cycleRunId instanceof NextResponse) return cycleRunId;
  if (cycleRunId === undefined) return invalidField("cycleRunId is required");
  const stage = optionalString(params.get("stage"));
  const artifactKind = optionalString(params.get("artifactKind"));
  const focusAreaId = optionalString(params.get("focusAreaId"));
  const sourceLane = optionalString(params.get("sourceLane"));
  const reportDate = optionalString(params.get("reportDate"));
  return intelligenceGet(request, "reports.latest", {
    cycle_run_id: cycleRunId,
    ...(stage !== undefined ? { stage } : {}),
    ...(artifactKind !== undefined ? { artifact_kind: artifactKind } : {}),
    ...(focusAreaId !== undefined ? { focus_area_id: focusAreaId } : {}),
    ...(sourceLane !== undefined ? { source_lane: sourceLane } : {}),
    ...(reportDate !== undefined ? { report_date: reportDate } : {}),
  });
}
