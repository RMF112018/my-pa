import type { NextRequest } from "next/server";
import { workGet } from "@/lib/api/work-route";
export function GET(request: NextRequest) { return workGet(request, "commitments-waiting-on", "commitments.waiting_on", {
  pageSize: { gateway: "page_size", type: "integer" },
  after: { gateway: "after", type: "string" },
}); }
