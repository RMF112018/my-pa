/**
 * Review listing route — WP-05 (R4).
 *
 * The principal comes from the verified session only; the listing can only
 * ever return that principal's own review cases. This is the web-tier shadow
 * of the Python `review_cases` read path, which is `principal_scoped` so a
 * caller cannot list another principal's cases (MU-AC-04). The response
 * deliberately does not echo an identity field back to the client — the
 * session cookie is the only identity carrier.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { syntheticReviewCases } from "@/lib/fixtures/review";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";

export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  return NextResponse.json({
    cases: syntheticReviewCases(guard.principal),
    disclosure: syntheticDisclosure("review"),
  });
}
