import type { NextRequest } from "next/server";
import { workGet, workPost } from "@/lib/api/work-route";
const LIST_FIELDS = {
  direction: { gateway: "direction", type: "string" },
  state: { gateway: "state", type: "string" },
  pageSize: { gateway: "page_size", type: "integer" },
  after: { gateway: "after", type: "string" },
} as const;
const CREATE_FIELDS = {
  counterpartyPersonId: { gateway: "counterparty_person_id", type: "string" },
  direction: { gateway: "direction", type: "string" },
  summary: { gateway: "summary", type: "string" },
  originEvidenceRef: { gateway: "origin_evidence_ref", type: "string" },
  idempotencyKey: { gateway: "idempotency_key", type: "string" },
  dueAt: { gateway: "due_at", type: "string" },
  projectId: { gateway: "project_id", type: "string" },
  situationId: { gateway: "situation_id", type: "string" },
  acceptedByReviewDecisionId: { gateway: "accepted_by_review_decision_id", type: "string" },
  clientContext: { gateway: "client_context", type: "string" },
} as const;
export function GET(request: NextRequest) {
  return workGet(request, "commitments", request.nextUrl.searchParams.get("q") ? "commitments.search" : "commitments.list", request.nextUrl.searchParams.get("q") ? { ...LIST_FIELDS, q: { gateway: "query", type: "string" } } : LIST_FIELDS);
}
export function POST(request: NextRequest) { return workPost(request, "commitments", "commitments.create", CREATE_FIELDS); }
