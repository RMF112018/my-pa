import type { NextRequest } from "next/server";
import type { IssuesReadResult } from "@/lib/api/decode/capabilities/issues.read";
import { invalidWorkRequest, isCanonicalId, workGet } from "@/lib/api/work-route";

/**
 * One Issue's header (record lineage S3 contract section 7.6): one `issues.read`
 * call, without the memberships (the lineage table carries those). An answer
 * about another Issue is not an answer to this request.
 */
type Context = { params: Promise<{ issueId: string }> };

export async function GET(request: NextRequest, context: Context) {
  const { issueId } = await context.params;
  if (!isCanonicalId(issueId, "sit")) return invalidWorkRequest("issueId was malformed");
  return workGet(request, `issue:${issueId}`, "issues.read", {}, { issue_id: issueId }, {
    strictQuery: true,
    project: (result) => {
      const { issue, memberships } = result as IssuesReadResult;
      return issue.issue_id === issueId && memberships === undefined ? { ...result } : null;
    },
  });
}
