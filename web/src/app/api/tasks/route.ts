import type { NextRequest } from "next/server";
import { workGet, workPost } from "@/lib/api/work-route";

const LIST_FIELDS = {
  lifecycleState: { gateway: "lifecycle_state", type: "string" },
  priority: { gateway: "priority", type: "string" },
  archived: { gateway: "archive_mode", type: "string" },
  pageSize: { gateway: "page_size", type: "integer" },
  after: { gateway: "after", type: "string" },
  workView: { gateway: "work_view", type: "string" },
  workDate: { gateway: "work_date", type: "string" },
  timezone: { gateway: "timezone", type: "string" },
} as const;
const CREATE_FIELDS = {
  title: { gateway: "title", type: "string" },
  originEvidenceRef: { gateway: "origin_evidence_ref", type: "string" },
  idempotencyKey: { gateway: "idempotency_key", type: "string" },
  description: { gateway: "description", type: "string" },
  priority: { gateway: "priority", type: "string" },
  dueAt: { gateway: "due_at", type: "string" },
  projectId: { gateway: "project_id", type: "string" },
  situationId: { gateway: "situation_id", type: "string" },
  acceptedByReviewDecisionId: { gateway: "accepted_by_review_decision_id", type: "string" },
  commitmentId: { gateway: "commitment_id", type: "string" },
  role: { gateway: "role", type: "string" },
  clientContext: { gateway: "client_context", type: "string" },
} as const;

export function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams.get("q");
  return workGet(request, "tasks", q ? "tasks.search" : "tasks.list", q ? { ...LIST_FIELDS, q: { gateway: "query", type: "string" } } : LIST_FIELDS);
}
export function POST(request: NextRequest) {
  return workPost(request, "tasks", "tasks.create", CREATE_FIELDS);
}
