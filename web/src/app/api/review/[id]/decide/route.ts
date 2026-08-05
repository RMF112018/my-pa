/**
 * Review disposition route — WP-05 (R4): `/api/review/:id/decide`.
 *
 * A disposition is the *only* thing that turns a noncanonical proposal into a
 * canonical reviewed assertion — AI never asserts on the user's behalf. The
 * principal is derived from the session, never the payload, and the target
 * case must belong to that principal: a decision aimed at a case the caller
 * does not own returns `not_found` and writes nothing, mirroring the Python
 * `decide_review` scoping where a cross-principal decision raises
 * `ReviewNotFoundError` (MU-AC-04). Cross-principal existence is never
 * disclosed — a foreign id and an unknown id are indistinguishable here.
 *
 * A successful disposition returns the immutable receipt the promotion would
 * issue. Persistence into the Python promotion transaction is not yet wired;
 * the disclosure says so on every response.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal, readCleanBody } from "@/lib/api/guard";
import {
  REVIEW_DISPOSITIONS,
  syntheticReviewCases,
  syntheticDecisionReceipt,
} from "@/lib/fixtures/review";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";
import type { ReviewDisposition } from "@/contracts/views";

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ id: string }> },
) {
  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const parsed = await readCleanBody(request);
  if (!parsed.ok) return parsed.response;

  const { id } = await context.params;

  const disposition = parsed.body["disposition"];
  if (
    typeof disposition !== "string" ||
    !REVIEW_DISPOSITIONS.includes(disposition as ReviewDisposition)
  ) {
    return NextResponse.json(
      {
        error: {
          code: "invalid_disposition",
          message: `disposition must be one of: ${REVIEW_DISPOSITIONS.join(", ")}`,
        },
      },
      { status: 400 },
    );
  }

  // A correction must carry the reviewed canonical value; it preserves the
  // original proposal rather than rewriting derivation history.
  if (disposition === "correct") {
    const correctedValue = parsed.body["correctedValue"];
    if (typeof correctedValue !== "string" || correctedValue.trim().length === 0) {
      return NextResponse.json(
        {
          error: {
            code: "missing_corrected_value",
            message: "a correct-and-accept disposition must carry a non-empty correctedValue",
          },
        },
        { status: 400 },
      );
    }
  }

  // The case must live in the caller's own partition. Foreign or unknown ids
  // are indistinguishable — never confirm another principal's case exists.
  const owned = syntheticReviewCases(guard.principal).some((c) => c.reviewCaseId === id);
  if (!owned) {
    return NextResponse.json(
      { error: { code: "not_found", message: "no such review case" } },
      { status: 404 },
    );
  }

  return NextResponse.json({
    receipt: syntheticDecisionReceipt(
      guard.principal,
      id,
      disposition as ReviewDisposition,
    ),
    status: "acknowledged_not_persisted",
    disclosure: syntheticDisclosure(`review:${id}:decide`),
  });
}
