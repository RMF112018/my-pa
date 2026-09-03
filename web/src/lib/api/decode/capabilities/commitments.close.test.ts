// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeCommitmentsClose } from "./commitments.close";

const AT = "2026-08-09T12:00:00.000Z";

function commitment(overrides: Record<string, unknown> = {}) {
  return {
    commitment_id: "cmt_aaaaaaaa11111111",
    direction: "owed_to_principal",
    state: "closed",
    counterparty_person_id: "per_aaaaaaaa11111111",
    title: "Canonical",
    description: null,
    due_date: null,
    created_at: AT,
    updated_at: AT,
    version: 2,
    evidence_state: "accepted",
    origin_evidence_ref: "cap_aaaaaaaa11111111",
    closure_evidence_ref: "cap_bbbbbbbb22222222",
    accepted_by_review_decision_id: null,
    closed_at: AT,
    counterparty: { person_id: "per_aaaaaaaa11111111", display_name: "Ada" },
    ...overrides,
  };
}

function payload(overrides: Record<string, unknown> = {}) {
  return { commitment: commitment(), replayed: false, ...overrides };
}

describe("decodeCommitmentsClose", () => {
  it("accepts a Python close payload", () => {
    const decoded = decodeCommitmentsClose(payload());
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.commitment.state).toBe("closed");
  });

  it("fails closed when commitment is omitted", () => {
    const { commitment: _, ...rest } = payload();
    expect(decodeCommitmentsClose(rest).ok).toBe(false);
  });

  it("fails closed when replayed is omitted", () => {
    const { replayed: _, ...rest } = payload();
    expect(decodeCommitmentsClose(rest).ok).toBe(false);
  });

  it("fails closed when version is missing rather than inferring it", () => {
    const { version: _, ...rest } = commitment();
    expect(decodeCommitmentsClose(payload({ commitment: rest })).ok).toBe(false);
  });

  it("fails closed on an invalid state enum", () => {
    expect(
      decodeCommitmentsClose(payload({ commitment: commitment({ state: "done" }) })).ok,
    ).toBe(false);
  });

  it("fails closed when replayed is the wrong type", () => {
    expect(decodeCommitmentsClose(payload({ replayed: 1 })).ok).toBe(false);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeCommitmentsClose(payload({ extra_close_field: "ignored" })).ok).toBe(true);
  });
});
