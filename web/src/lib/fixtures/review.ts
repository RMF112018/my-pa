/**
 * Synthetic Review fixtures — WP-05 (R4).
 *
 * The review workbench is landed against principal-scoped synthetic cases,
 * exactly as Pulse was in WP-02: every case is stamped with the signed-in
 * principal's id, and every disclosure is labeled `coverage: "synthetic"` /
 * `authority: "synthetic_fixture"` so the workbench never presents fixture
 * data as a real proposal. Live proposals from the Python pipeline replace
 * this module when the read models are wired through.
 *
 * The fixtures deliberately model *consequential* proposals — a commitment
 * and a decision — because R4 risk routing sends exactly those classes to
 * human Review rather than deterministic promotion (product package
 * `11_AI_REVIEW_AND_PROMOTION_STRATEGY.md`, "Risk routing"). Nothing here is
 * asserted on the user's behalf: each case is a proposal awaiting a
 * disposition.
 */
import type { PrincipalSession } from "@/contracts/identity";
import type { ReviewCase, ReviewDisposition } from "@/contracts/views";
import type { Receipt } from "@/contracts/envelope";

/**
 * Deterministic principal-scoped review cases. The `principalId` on every
 * case is the caller's own — a foreign principal never appears here, which
 * is the fixture-level shadow of the server-side partition invariant
 * (MU-AC-04).
 */
export function syntheticReviewCases(principal: PrincipalSession): readonly ReviewCase[] {
  const pid = principal.principalId;
  return [
    {
      reviewCaseId: `rev-${pid}-001`,
      principalId: pid,
      proposalId: `prop-${pid}-001`,
      proposalState: "needs_review",
      proposalSummary:
        "Proposed commitment: you will send the revised concrete schedule to the owner by Friday.",
      evidence: [
        {
          sourceVersionId: `srcver-${pid}-note-014`,
          startOffset: 42,
          endOffset: 112,
          surfaceText: "I'll get the revised pour schedule over to the owner before end of week.",
        },
      ],
      impactSummary:
        "Accepting records a tracked commitment with a Friday due date. It does not send anything.",
      openedAt: "2026-08-05T13:20:00+00:00",
    },
    {
      reviewCaseId: `rev-${pid}-002`,
      principalId: pid,
      proposalId: `prop-${pid}-002`,
      proposalState: "needs_review",
      proposalSummary:
        "Proposed decision: the north retaining wall design is approved to proceed to submittal.",
      evidence: [
        {
          sourceVersionId: `srcver-${pid}-mtg-031`,
          startOffset: 8,
          endOffset: 74,
          surfaceText: "We agreed the north wall design is good to move to submittal.",
        },
      ],
      impactSummary:
        "Accepting records a decision that other Situations may reference. It changes no external system.",
      openedAt: "2026-08-05T09:05:00+00:00",
    },
  ];
}

/** The set of disposition verbs the workbench may submit. Closed set. */
export const REVIEW_DISPOSITIONS: readonly ReviewDisposition[] = [
  "accept",
  "correct",
  "reject",
  "defer",
  "unresolved",
] as const;

/** Map a disposition to the proposal-state transition it records. */
const DISPOSITION_TRANSITION: Record<ReviewDisposition, string> = {
  accept: "needs_review->accepted",
  correct: "needs_review->corrected_accepted",
  reject: "needs_review->rejected",
  defer: "needs_review->deferred",
  unresolved: "needs_review->unresolved",
};

/**
 * The immutable receipt a disposition would produce. Bound to the caller's
 * principal, the review case, the policy version, and the transition — the
 * synthetic parity of the Python `capture_promotion_receipts` row that a real
 * disposition writes inside the promotion transaction.
 */
export function syntheticDecisionReceipt(
  principal: PrincipalSession,
  reviewCaseId: string,
  disposition: ReviewDisposition,
): Receipt {
  return {
    receiptId: `rcpt-${principal.principalId}-${reviewCaseId}-${disposition}`,
    principalId: principal.principalId,
    subjectKind: "review_case",
    subjectId: reviewCaseId,
    transition: DISPOSITION_TRANSITION[disposition],
    policyVersion: "review-policy-v4.0",
    issuedAt: "2026-08-05T14:00:00+00:00",
    authority: `review_disposition:${disposition}`,
  };
}
