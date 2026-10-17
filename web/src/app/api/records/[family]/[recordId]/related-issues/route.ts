import type { NextRequest } from "next/server";
import type { RecordsLineageResult } from "@/lib/api/decode/capabilities/records.lineage";
import { invalidWorkRequest, isCanonicalId, workGet } from "@/lib/api/work-route";

/**
 * The related-Issue read behind one Task, Commitment or Constraint view
 * (record lineage S1 contract section 7.4): one `records.lineage` call, one hop
 * from the record, optionally under a chosen Issue. Read-only.
 *
 * Only the three record views `web/` has are admitted; any other family is a
 * local `invalid_request` and never reaches the gateway.
 */
const FAMILY_PREFIX = { task: "tsk", commitment: "cmt", constraint: "cst" } as const;
type Family = keyof typeof FAMILY_PREFIX;

function isFamily(value: string): value is Family {
  return Object.hasOwn(FAMILY_PREFIX, value);
}

type Context = { params: Promise<{ family: string; recordId: string }> };

export async function GET(request: NextRequest, context: Context) {
  const { family, recordId } = await context.params;
  if (!isFamily(family)) return invalidWorkRequest("family must be task, commitment or constraint");
  if (!isCanonicalId(recordId, FAMILY_PREFIX[family])) return invalidWorkRequest("recordId was malformed");
  return workGet(request, "related-issues", "records.lineage", {
    issueId: { gateway: "issue_id", type: "string", pattern: /^sit_[A-Za-z0-9]{8,64}$/ },
  }, { origin: { family, record_id: recordId }, max_depth: 1 }, {
    strictQuery: true,
    // The decoder has already proved the shape; an answer about another root
    // is not an answer to this request.
    project: (result) => {
      const { root } = result as RecordsLineageResult;
      return root.family === family && root.record_id === recordId ? { ...result } : null;
    },
  });
}
