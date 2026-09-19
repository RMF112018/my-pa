/**
 * `GET /api/project-controls/portfolio/constraints` — the cross-Project Register.
 *
 * Outside the `projects/[projectId]/` tree deliberately: a portfolio read takes
 * no Project identifier, so there is no segment to put one in, and a path that
 * offered one would be the ownership oracle this family refuses. The Project set
 * is derived server-side from the Principal and is never a request field.
 *
 * One route serves two capabilities, branching on a non-empty `q`, exactly as
 * the exact-Project Register does and for the same reason: the accepted BFF
 * route contract publishes no `/search` path, and `SearchPortfolioConstraints`
 * accepts a strictly narrower request, so a filter, sort or grouping supplied
 * with a term is refused rather than dropped.
 *
 * **One gateway call per request.** Whichever branch is taken, `workGet` issues
 * a single capability invocation and the server answers across every owned
 * Project inside it. Nothing here enumerates Projects and nothing here calls the
 * exact-Project capability, so the browser has no fanout to perform and no route
 * that would perform one on its behalf.
 */
import { NextResponse, type NextRequest } from "next/server";
import { workGet } from "@/lib/api/work-route";
import {
  PORTFOLIO_REGISTER_FIELDS,
  PORTFOLIO_SEARCH_FIELDS,
} from "@/app/api/project-controls/constraint-requests";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const term = request.nextUrl.searchParams.get("q");
  return term
    ? workGet(
        request,
        "constraint-portfolio-register",
        "constraints.portfolio_search",
        PORTFOLIO_SEARCH_FIELDS,
      )
    : workGet(
        request,
        "constraint-portfolio-register",
        "constraints.portfolio_list",
        PORTFOLIO_REGISTER_FIELDS,
      );
}
