// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeCommitmentsCreate } from "./commitments.create";

const AT = "2026-08-09T12:00:00.000Z";

function commitment(overrides: Record<string, unknown> = {}) {
  return {
    commitment_id: "cmt_aaaaaaaa11111111",
    direction: "owed_to_principal",
    state: "open",
    counterparty_person_id: "per_aaaaaaaa11111111",
    title: "Canonical",
    description: null,
    due_date: null,
    created_at: AT,
    updated_at: AT,
    version: 1,
    evidence_state: "accepted",
    origin_evidence_ref: "cap_aaaaaaaa11111111",
    closure_evidence_ref: null,
    accepted_by_review_decision_id: null,
    closed_at: null,
    counterparty: { person_id: "per_aaaaaaaa11111111", display_name: "Ada" },
    ...overrides,
  };
}

function payload(overrides: Record<string, unknown> = {}) {
  return { commitment: commitment(), replayed: false, ...overrides };
}

describe("decodeCommitmentsCreate", () => {
  it("accepts a Python create payload", () => {
    const decoded = decodeCommitmentsCreate(payload());
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.commitment.version).toBe(1);
  });

  it("fails closed when commitment is omitted", () => {
    const { commitment: _, ...rest } = payload();
    expect(decodeCommitmentsCreate(rest).ok).toBe(false);
  });

  it("fails closed when replayed is omitted", () => {
    const { replayed: _, ...rest } = payload();
    expect(decodeCommitmentsCreate(rest).ok).toBe(false);
  });

  it("fails closed when version is missing rather than inferring it", () => {
    const { version: _, ...rest } = commitment();
    expect(decodeCommitmentsCreate(payload({ commitment: rest })).ok).toBe(false);
  });

  it("fails closed on an invalid direction enum", () => {
    expect(
      decodeCommitmentsCreate(payload({ commitment: commitment({ direction: "inbound" }) })).ok,
    ).toBe(false);
  });

  it("fails closed when commitment is the wrong type", () => {
    expect(decodeCommitmentsCreate(payload({ commitment: [] })).ok).toBe(false);
  });

  it("ignores unknown extra fields including a spurious history key", () => {
    expect(decodeCommitmentsCreate(payload({ history: { invented: true } })).ok).toBe(true);
  });
});
