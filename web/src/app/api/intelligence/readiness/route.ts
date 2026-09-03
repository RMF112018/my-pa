/**
 * Cycle-bound expected-member resolution — `reports.resolve_set`.
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
  const setId = optionalString(params.get("setId"));
  if (setId === undefined) return invalidField("setId is required");
  const focusAreaId = optionalString(params.get("focusAreaId"));
  return intelligenceGet(request, "reports.resolve_set", {
    cycle_run_id: cycleRunId,
    set_id: setId,
    ...(focusAreaId !== undefined ? { focus_area_id: focusAreaId } : {}),
  });
}
