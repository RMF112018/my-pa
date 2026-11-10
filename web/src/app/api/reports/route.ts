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
 * Each branch names its capability as a literal: the BFF contract lock reads
 * only literal route-helper capabilities and refuses any other expression.
 */
export async function GET(request: NextRequest) {
  if (request.nextUrl.searchParams.has("query")) {
    return reportsRead(request, "reports.search", CATALOG_FIELDS);
  }
  return reportsRead(request, "reports.list", CATALOG_FIELDS);
}

/** `POST /api/reports` -> `reports.publish`. */
export async function POST(request: NextRequest) {
  return reportsMutation(request, "reports.publish", PUBLISH_FIELDS);
}
