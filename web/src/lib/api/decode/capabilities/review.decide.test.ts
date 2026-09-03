// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReviewDecide } from "./review.decide";

function decision(overrides: Record<string, unknown> = {}) {
  return {
    review_case_id: "rvw_aaaaaaaa11111111",
    decision_id: "rdec_aaaaaaaa11111111",
    review_version: 1,
    disposition: "correct_and_accept",
    proposal_state: "corrected_accepted",
    assertion_id: "asrt_aaaaaaaa11111111",
    receipt_id: "rcpt_bbbbbbbb22222222",
    ...overrides,
  };
}

describe("decodeReviewDecide", () => {
  it("accepts a Python decision receipt", () => {
    const decoded = decodeReviewDecide(decision());
    expect(decoded.ok).toBe(true);
    if (decoded.ok && "decision_id" in decoded.value) {
      expect(decoded.value.review_version).toBe(1);
      expect(decoded.value.disposition).toBe("correct_and_accept");
    }
  });

  it("accepts an invalidated result without inventing a receipt", () => {
    const decoded = decodeReviewDecide({
      review_case_id: "rvw_aaaaaaaa11111111",
      result: "invalidated",
    });
    expect(decoded.ok).toBe(true);
    if (decoded.ok && "result" in decoded.value) {
      expect(decoded.value.result).toBe("invalidated");
      expect(decoded.value).not.toHaveProperty("decision_id");
    }
  });

  it("fails closed on a guessed-version fixture the route used to accept", () => {
    const guessed = {
      review_case_id: "rvw_aaaaaaaa11111111",
      decision_id: "rdec_aaaaaaaa11111111",
      proposal_state: "accepted",
      assertion_id: null,
      receipt_id: null,
    };
    expect(decodeReviewDecide(guessed).ok).toBe(false);
  });

  it("fails closed when review_version is missing", () => {
    const { review_version: _, ...rest } = decision();
    expect(decodeReviewDecide(rest).ok).toBe(false);
  });

  it("fails closed when disposition is missing", () => {
    const { disposition: _, ...rest } = decision();
    expect(decodeReviewDecide(rest).ok).toBe(false);
  });

  it("fails closed on an invalid disposition enum", () => {
    expect(decodeReviewDecide(decision({ disposition: "correct" })).ok).toBe(false);
  });

  it("fails closed when decision_id is the wrong type", () => {
    expect(decodeReviewDecide(decision({ decision_id: 12 })).ok).toBe(false);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeReviewDecide(decision({ extra_decision_field: "ignored" })).ok).toBe(true);
  });
});
