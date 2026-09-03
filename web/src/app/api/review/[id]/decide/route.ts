/**
 * Review disposition — `/api/review/:id/decide`.
 *
 * A disposition is the only thing that turns a noncanonical proposal into a
 * canonical reviewed assertion; AI never asserts on the user's behalf. Backed by
 * the Python `review.decide`, which appends the decision, promotes the proposal
 * where the disposition says to, and writes the assertion and promotion receipt
 * inside the same transaction as the audit event.
 *
 * **`acknowledged_not_persisted` is gone from this route.** It was accurate while
 * nothing was wired: the route matched a fixture case and returned a receipt it
 * had constructed itself. What comes back now is the receipt the backend
 * produced — `decisionId`, `reviewVersion`, `proposalState`, and the
 * `assertionId` / `receiptId` when the disposition minted them — or a typed
 * refusal. Neither is acknowledged-and-dropped.
 *
 * **`expectedReviewVersion` is required and is not defaulted.** `review.decide`
 * runs under optimistic concurrency, and a client that did not state the version
 * it believes it is deciding against would be asking the server to guess; a
 * stale version is answered `conflict` rather than silently winning. The listing
 * is where a client learns the current value.
 *
 * **Scope is the backend's, and it is indistinguishable by design.** A case the
 * caller does not own is `not_found` on the Python side — `decide_review` is
 * principal-scoped and a cross-principal decision raises `ReviewNotFoundError` —
 * so a foreign identifier and an unknown one produce the same answer here, and
 * this tier does not need a membership check of its own to make that true.
 *
 * **Two disposition vocabularies, translated in one place.** The workbench sends
 * `correct` and `unresolved`; the domain calls them `correct_and_accept` and
 * `mark_unresolved`. The map lives in `contracts/gateway.json` and a parity test
 * checks every value against the Python enum.
 */
import { NextResponse, type NextRequest } from "next/server";
import { requirePrincipal, readCleanBody } from "@/lib/api/guard";
import { admitBrowserMutation } from "@/lib/http/mutation-admission";
import contract from "@/contracts/gateway.json";
import { backendDisclosure, callGateway, transportLimitations } from "@/lib/api/gateway";
import { gatewayRefusal, resolveServing } from "@/lib/api/serving";
import {
  REVIEW_DISPOSITIONS,
  syntheticReviewCases,
  syntheticDecisionReceipt,
} from "@/lib/fixtures/review";
import { syntheticDisclosure } from "@/lib/fixtures/pulse";
import type { ReviewDisposition, ReviewDecisionReceipt } from "@/contracts/views";

/** The five verbs the workbench may submit, read off the shared contract. */
const DISPOSITIONS = contract.dispositions as Record<string, string>;

interface PythonDecision {
  readonly review_case_id: string;
  readonly decision_id?: string;
  readonly review_version?: number;
  readonly disposition?: string;
  readonly proposal_state?: string;
  readonly assertion_id?: string | null;
  readonly receipt_id?: string | null;
  readonly result?: string;
}

function refuse(code: string, message: string, status: number): NextResponse {
  return NextResponse.json({ error: { errorClass: "validation", code, message } }, { status });
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ id: string }> },
) {
  const blocked = admitBrowserMutation(request);
  if (blocked) return blocked;

  const guard = await requirePrincipal(request);
  if (!guard.ok) return guard.response;

  const parsed = await readCleanBody(request);
  if (!parsed.ok) return parsed.response;

  const { id } = await context.params;
  const scope = `review:${id}:decide`;

  const disposition = parsed.body["disposition"];
  if (
    typeof disposition !== "string" ||
    !(disposition in DISPOSITIONS) ||
    !REVIEW_DISPOSITIONS.includes(disposition as ReviewDisposition)
  ) {
    return refuse(
      "invalid_disposition",
      `disposition must be one of: ${Object.keys(DISPOSITIONS).join(", ")}`,
      400,
    );
  }

  // A correction must carry the reviewed canonical value; it preserves the
  // original proposal rather than rewriting derivation history.
  const correctedValue = parsed.body["correctedValue"];
  if (disposition === "correct") {
    if (typeof correctedValue !== "string" || correctedValue.trim().length === 0) {
      return refuse(
        "missing_corrected_value",
        "a correct-and-accept disposition must carry a non-empty correctedValue",
        400,
      );
    }
  } else if (correctedValue !== undefined) {
    return refuse(
      "unexpected_corrected_value",
      "only a correct-and-accept disposition carries a correctedValue",
      400,
    );
  }

  const serving = resolveServing();
  if (serving.kind === "refused") return serving.response;

  if (serving.kind === "synthetic") {
    // The case must live in the caller's own partition. Foreign or unknown ids
    // are indistinguishable — never confirm another principal's case exists.
    const owned = syntheticReviewCases(guard.principal).some((c) => c.reviewCaseId === id);
    if (!owned) {
      return NextResponse.json(
        { error: { errorClass: "not_found", code: "not_found", message: "no such review case" } },
        { status: 404 },
      );
    }
    return NextResponse.json({
      shape: "synthetic",
      receipt: syntheticDecisionReceipt(guard.principal, id, disposition as ReviewDisposition),
      status: "acknowledged_not_persisted",
      disclosure: syntheticDisclosure(scope),
    });
  }

  const expected = parsed.body["expectedReviewVersion"];
  if (typeof expected !== "number" || !Number.isInteger(expected) || expected < 0) {
    return refuse(
      "missing_expected_review_version",
      "expectedReviewVersion must be the non-negative integer version this decision is " +
        "made against; the review listing publishes the current value",
      400,
    );
  }

  const outcome = await callGateway<PythonDecision>(guard.principal, "review.decide", {
    review_case_id: id,
    expected_review_version: expected,
    disposition: DISPOSITIONS[disposition],
    corrected_value: disposition === "correct" ? (correctedValue as string).trim() : undefined,
  });
  if (!outcome.ok) return gatewayRefusal(scope, outcome.status, outcome.error);

  // A proposal invalidated before the decision landed has no decision row, so
  // the backend reports the outcome rather than a receipt. Reported as it is.
  if (outcome.result.decision_id === undefined) {
    return NextResponse.json({
      shape: "backend",
      status: outcome.result.result ?? "no_decision_recorded",
      receipt: null,
      disclosure: backendDisclosure(scope, outcome.disclosure, transportLimitations()),
    });
  }

  const receipt: ReviewDecisionReceipt = {
    reviewCaseId: outcome.result.review_case_id,
    decisionId: outcome.result.decision_id,
    reviewVersion: outcome.result.review_version ?? expected + 1,
    disposition: outcome.result.disposition ?? DISPOSITIONS[disposition],
    proposalState: outcome.result.proposal_state ?? "unknown",
    assertionId: outcome.result.assertion_id ?? null,
    receiptId: outcome.result.receipt_id ?? null,
  };
  return NextResponse.json({
    shape: "backend",
    status: "persisted",
    receipt,
    disclosure: backendDisclosure(scope, outcome.disclosure, transportLimitations()),
  });
}
