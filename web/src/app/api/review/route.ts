/**
 * Review listing — the principal's own consequential proposal cases.
 *
 * Backed by the Python `review.list`, whose read is `principal_scoped`: the
 * listing is filtered by the acting Principal at the persistence boundary, so a
 * caller cannot list another Principal's cases (MU-AC-04). The principal this
 * tier resolves comes from the verified session cookie and nothing else, and the
 * response deliberately does not echo an identity field back — the cookie is the
 * only identity carrier.
 *
 * **The backend listing carries no content, and this route does not add any.**
 * `review.list` returns the case, proposal and version identifiers, the proposal
 * type and state, the risk class, the opened-at moment, the review version and
 * the latest disposition — and no proposal text, no evidence span, and no impact
 * summary, because the listing is not the read. The synthetic fixture shape has
 * all three of those fields; a real case does not, so the two are returned as
 * different shapes rather than one shape with three invented nulls. `shape` on
 * the response says which one a reader is holding.
 *
 * **`reviewVersion` matters to the caller.** `review.decide` runs under
 * optimistic concurrency and requires the version the caller believes it is
 * deciding against, so the listing is where a client learns it.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal } from "@/lib/api/guard";
import { backendDisclosure, invokeGateway, transportLimitations } from "@/lib/api/gateway";
import { gatewayRefusal, resolveServing } from "@/lib/api/serving";
import { syntheticReviewCases } from "@/lib/fixtures/review";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";
import { toBackendReviewCase } from "@/components/review/to-backend-case";

const SCOPE = "review";

export async function GET(request: NextRequest) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;

  if (serving.kind === "synthetic") {
    return NextResponse.json({
      shape: "synthetic",
      cases: syntheticReviewCases(guard.principal),
      disclosure: syntheticDisclosure(SCOPE),
    });
  }

  const outcome = await invokeGateway(guard.principal, "review.list");
  if (!outcome.ok) return gatewayRefusal(SCOPE, outcome.status, outcome.error);
  const result = outcome.result;

  return NextResponse.json({
    shape: "backend",
    cases: result.review_cases.map(toBackendReviewCase),
    disclosure: backendDisclosure(SCOPE, outcome.disclosure, transportLimitations()),
  });
}
