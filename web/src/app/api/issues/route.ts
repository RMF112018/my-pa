import type { NextRequest } from "next/server";
import { workGet } from "@/lib/api/work-route";

/**
 * The Issues index read (record lineage S3 contract section 7.6): one
 * `issues.list` page, newest first, optionally of one state, continued by the
 * previous page's last `issue_id` ("More"). Read-only; one gateway call.
 */
export async function GET(request: NextRequest) {
  return workGet(request, "issues", "issues.list", {
    pageSize: { gateway: "page_size", type: "integer", minimum: 1, maximum: 100 },
    after: { gateway: "after", type: "string", pattern: /^sit_[A-Za-z0-9]{8,64}$/ },
    state: { gateway: "state", type: "string", values: ["open", "active", "suspended", "closed"] },
  }, {}, { strictQuery: true });
}
