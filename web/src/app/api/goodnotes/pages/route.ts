import type { NextRequest } from "next/server";
import {
  goodnotesGet,
  goodnotesInvalid,
  noStore,
  optionalPageSize,
  optionalQuery,
  requiredQuery,
} from "@/lib/api/goodnotes-route";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const notebookId = requiredQuery(params, "notebookId");
  if (notebookId === null) return noStore(goodnotesInvalid("pages requires notebookId"));
  const pageSize = optionalPageSize(params);
  if (pageSize === "invalid") return noStore(goodnotesInvalid("pageSize must be an integer"));
  const cursor = optionalQuery(params, "cursor");
  return goodnotesGet(request, "goodnotes:goodnotes.pages.list", "goodnotes.pages.list", {
    notebook_id: notebookId,
    page_size: pageSize,
    cursor,
  });
}
