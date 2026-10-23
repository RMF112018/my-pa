import type { NextRequest } from "next/server";
import type { IssuesTimelineResult } from "@/lib/api/decode/capabilities/issues.timeline";
import { invalidWorkRequest, isCanonicalId, workGet } from "@/lib/api/work-route";

/**
 * One page of an Issue's timeline (record lineage S3 contract sections 7.3 and
 * 7.6): one `issues.timeline` call per page. A later page sends only the
 * previous page's opaque `cursor` and the same `pageSize`; the cut it was read
 * at travels inside the cursor, never as separate fields the browser keeps.
 */
type Context = { params: Promise<{ issueId: string }> };

export async function GET(request: NextRequest, context: Context) {
  const { issueId } = await context.params;
  if (!isCanonicalId(issueId, "sit")) return invalidWorkRequest("issueId was malformed");
  return workGet(request, `issue-timeline:${issueId}`, "issues.timeline", {
    pageSize: { gateway: "page_size", type: "integer", minimum: 10, maximum: 100 },
    cursor: { gateway: "cursor", type: "string", pattern: /^[A-Za-z0-9_-]{1,2048}$/ },
    knownAt: { gateway: "known_at", type: "string", format: "timestamp" },
  }, { issue_id: issueId }, {
    strictQuery: true,
    validate: (payload) => payload.cursor !== undefined && payload.page_size === undefined
      ? "cursor requires pageSize" : null,
    project: (result) => (result as IssuesTimelineResult).issue_id === issueId ? { ...result } : null,
  });
}
