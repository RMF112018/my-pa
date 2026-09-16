/**
 * `GET /api/project-controls/portfolio/constraints/overview` — every owned
 * Project's Constraint position, each on its own calendar.
 *
 * No query at all, and no path segment either: `ReadPortfolioConstraintOverview`
 * has no fields, so `NO_FIELDS` is the whole admitted vocabulary and any query
 * name is refused before a capability is spent. The payload the gateway receives
 * is therefore the empty object, which the capability accepts — its MCP schema
 * makes `payload` itself optional because it has no required field.
 *
 * One gateway call, one answer. The per-Project entries come back from that
 * single call already computed against each Project's own calendar; this route
 * neither enumerates Projects nor combines their counts, and the response
 * carries no portfolio-wide roll-up because counts taken against different
 * Project dates are not summable.
 */
import { NextResponse, type NextRequest } from "next/server";
import { workGet } from "@/lib/api/work-route";
import { NO_FIELDS } from "@/app/api/project-controls/constraint-requests";

export async function GET(request: NextRequest): Promise<NextResponse> {
  return workGet(
    request,
    "constraint-portfolio-overview",
    "constraints.portfolio_overview",
    NO_FIELDS,
  );
}
