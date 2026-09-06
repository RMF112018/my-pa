import type { NextRequest } from "next/server";
import {
  goodnotesGet,
  goodnotesInvalid,
  noStore,
  optionalQuery,
  requiredQuery,
} from "@/lib/api/goodnotes-route";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const runId = requiredQuery(params, "runId");
  const pageVersionId = requiredQuery(params, "pageVersionId");
  if (runId === null || pageVersionId === null) {
    return noStore(goodnotesInvalid("item requires runId and pageVersionId"));
  }
  return goodnotesGet(request, "goodnotes:goodnotes.read", "goodnotes.read", {
    run_id: runId,
    page_version_id: pageVersionId,
    content_sha256: optionalQuery(params, "contentSha256"),
  });
}
