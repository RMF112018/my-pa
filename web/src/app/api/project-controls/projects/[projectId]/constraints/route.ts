/**
 * `GET /api/project-controls/projects/[projectId]/constraints` — the Register.
 *
 * One route serves two capabilities, branching on a non-empty `q`: the accepted
 * BFF route contract publishes no `/search` path, and a second route would be a
 * second API for the same page of the same records. The branch is not cosmetic —
 * `constraints.search` accepts a strictly narrower request, so the search
 * allowlist is the narrower one and a filter, sort or grouping supplied with a
 * term is refused rather than dropped.
 *
 * `workGet` supplies everything else: the Principal from the opaque session SID
 * (never the browser), `cache-control: private, no-store`, the closed field map,
 * and the fail-closed decode of the gateway's success.
 */
import { NextResponse, type NextRequest } from "next/server";
import { workGet } from "@/lib/api/work-route";
import {
  invalidPathIdentifier,
  isProjectId,
  REGISTER_FIELDS,
  SEARCH_FIELDS,
} from "@/app/api/project-controls/constraint-requests";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ projectId: string }> },
): Promise<NextResponse> {
  const { projectId } = await context.params;
  if (!isProjectId(projectId)) return invalidPathIdentifier("projectId");
  const term = request.nextUrl.searchParams.get("q");
  return term
    ? workGet(request, "constraint-register", "constraints.search", SEARCH_FIELDS, {
        project_id: projectId,
      })
    : workGet(request, "constraint-register", "constraints.list", REGISTER_FIELDS, {
        project_id: projectId,
      });
}
