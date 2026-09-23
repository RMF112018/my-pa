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
 *
 * `POST` (R01-WP09) creates a Constraint directly in its published state through
 * `constraints.create_published`. The Project is the path segment's and never
 * the body's; everything else — Origin admission, the session Principal, the
 * clean body, the closed field map, the decode — is `workPost`'s, so this
 * handler is a path guard and one call. A Draft is created at `…/drafts`.
 */
import { NextResponse, type NextRequest } from "next/server";
import { workGet, workPost } from "@/lib/api/work-route";
import {
  CONSTRAINT_CREATE_PUBLISHED_FIELDS,
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

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ projectId: string }> },
): Promise<NextResponse> {
  const { projectId } = await context.params;
  if (!isProjectId(projectId)) return invalidPathIdentifier("projectId");
  return workPost(
    request,
    "constraint-create-published",
    "constraints.create_published",
    CONSTRAINT_CREATE_PUBLISHED_FIELDS,
    { project_id: projectId },
  );
}
