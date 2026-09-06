import type { NextRequest } from "next/server";
import {
  goodnotesGet,
  goodnotesInvalid,
  noStore,
  optionalPageSize,
  optionalQuery,
} from "@/lib/api/goodnotes-route";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const pageSize = optionalPageSize(params);
  if (pageSize === "invalid") return noStore(goodnotesInvalid("pageSize must be an integer"));
  return goodnotesGet(request, "goodnotes:goodnotes.runs.list", "goodnotes.runs.list", {
    notebook_id: optionalQuery(params, "notebookId"),
    page_version_id: optionalQuery(params, "pageVersionId"),
    page_size: pageSize,
    cursor: optionalQuery(params, "cursor"),
  });
}
