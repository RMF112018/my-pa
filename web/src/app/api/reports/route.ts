import type { NextRequest } from "next/server";
import {
  CATALOG_FIELDS,
  PUBLISH_FIELDS,
  reportsMutation,
  reportsRead,
} from "@/lib/api/reports-route";

/**
 * `GET /api/reports`: the plane-selected catalog. `reports.search` when a
 * `query` is present, otherwise `reports.list`; `plane` (`standalone` | `all`)
 * is required and is refused before any gateway call when absent or other.
 */
export async function GET(request: NextRequest) {
  const capability = request.nextUrl.searchParams.has("query") ? "reports.search" : "reports.list";
  return reportsRead(request, capability, CATALOG_FIELDS);
}

/** `POST /api/reports` -> `reports.publish`. */
export async function POST(request: NextRequest) {
  return reportsMutation(request, "reports.publish", PUBLISH_FIELDS);
}
