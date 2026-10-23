import type { NextRequest } from "next/server";
import type { RecordsLineageResult } from "@/lib/api/decode/capabilities/records.lineage";
import { invalidWorkRequest, isCanonicalId, workGet } from "@/lib/api/work-route";

/**
 * One page of an Issue's lineage (record lineage S3 contract sections 7.2 and
 * 7.6): one `records.lineage` call per page, the Issue as both origin and
 * selected Issue. No per-node or per-edge fetch and no client-side join: the
 * whole bounded, visibility-filtered answer comes from this one read.
 */
type Context = { params: Promise<{ issueId: string }> };

export async function GET(request: NextRequest, context: Context) {
  const { issueId } = await context.params;
  if (!isCanonicalId(issueId, "sit")) return invalidWorkRequest("issueId was malformed");
  return workGet(request, `issue-lineage:${issueId}`, "records.lineage", {
    pageSize: { gateway: "page_size", type: "integer", minimum: 10, maximum: 100 },
    cursor: { gateway: "cursor", type: "string", pattern: /^[A-Za-z0-9_-]{1,2048}$/ },
    knownAt: { gateway: "known_at", type: "string", format: "timestamp" },
  }, { origin: { family: "situation", record_id: issueId }, issue_id: issueId }, {
    strictQuery: true,
    validate: (payload) => payload.cursor !== undefined && payload.page_size === undefined
      ? "cursor requires pageSize" : null,
    // The decoder has already proved the shape; an answer about another root
    // (or under another Issue) is not an answer to this request.
    project: (result) => {
      const { root, selected_issue_id: selected } = result as RecordsLineageResult;
      const ownRoot = root.family === "situation" && root.record_id === issueId;
      return ownRoot && (selected === null || selected === issueId) ? { ...result } : null;
    },
  });
}
