/**
 * Intelligence listing and lexical search.
 *
 * * `?q=` -> `reports.search`
 * * otherwise -> `reports.list`
 *
 * Synthetic serving answers not_implemented. The session cookie is the only
 * identity; query strings cannot select a Principal or a purpose.
 */
import { NextResponse, type NextRequest } from "next/server";
import {
  intelligenceGet,
  invalidField,
  optionalBoolean,
  optionalIdentifier,
  optionalInteger,
  optionalString,
} from "./dispatch";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const query = optionalString(params.get("q"));
  const cycleRunId = optionalIdentifier(params.get("cycleRunId"), "cycleRunId");
  if (cycleRunId instanceof NextResponse) return cycleRunId;
  const cursor = optionalIdentifier(params.get("cursor"), "cursor");
  if (cursor instanceof NextResponse) return cursor;
  const pageSize = optionalInteger(params.get("pageSize"), "pageSize");
  if (pageSize instanceof NextResponse) return pageSize;
  const includeSuperseded = optionalBoolean(params.get("includeSuperseded"), "includeSuperseded");
  if (includeSuperseded instanceof NextResponse) return includeSuperseded;
  const stage = optionalString(params.get("stage"));
  const artifactKind = optionalString(params.get("artifactKind"));
  const focusAreaId = optionalString(params.get("focusAreaId"));
  const sourceLane = optionalString(params.get("sourceLane"));
  const reportDate = optionalString(params.get("reportDate"));
  if (query && includeSuperseded !== undefined) {
    return invalidField("includeSuperseded is not a search field");
  }
  if (query && cursor !== undefined) {
    return invalidField("cursor is not a search field");
  }
  const common = {
    ...(cycleRunId !== undefined ? { cycle_run_id: cycleRunId } : {}),
    ...(stage !== undefined ? { stage } : {}),
    ...(artifactKind !== undefined ? { artifact_kind: artifactKind } : {}),
    ...(focusAreaId !== undefined ? { focus_area_id: focusAreaId } : {}),
    ...(sourceLane !== undefined ? { source_lane: sourceLane } : {}),
    ...(reportDate !== undefined ? { report_date: reportDate } : {}),
    ...(pageSize !== undefined ? { page_size: pageSize } : {}),
  };
  if (query) {
    return intelligenceGet(request, "reports.search", { query, ...common });
  }
  return intelligenceGet(request, "reports.list", {
    ...common,
    ...(cursor !== undefined ? { cursor } : {}),
    ...(includeSuperseded !== undefined ? { include_superseded: includeSuperseded } : {}),
  });
}
