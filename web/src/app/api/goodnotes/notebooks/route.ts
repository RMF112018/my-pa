import type { NextRequest } from "next/server";
import { goodnotesGet, goodnotesInvalid, noStore, optionalPageSize, optionalQuery } from "@/lib/api/goodnotes-route";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const pageSize = optionalPageSize(params);
  if (pageSize === "invalid") return noStore(goodnotesInvalid("pageSize must be an integer"));
  const cursor = optionalQuery(params, "cursor");
  return goodnotesGet(request, "goodnotes:goodnotes.notebooks.list", "goodnotes.notebooks.list", {
    page_size: pageSize,
    cursor,
  });
}
