// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeCommitmentsUpdate } from "./commitments.update";

const AT = "2026-08-09T12:00:00.000Z";

function commitment(overrides: Record<string, unknown> = {}) {
  return {
    commitment_id: "cmt_aaaaaaaa11111111",
    direction: "owed_to_principal",
    state: "open",
    counterparty_person_id: "per_aaaaaaaa11111111",
    title: "Updated",
    description: null,
    due_date: null,
    created_at: AT,
    updated_at: AT,
    version: 2,
    evidence_state: "accepted",
    origin_evidence_ref: "cap_aaaaaaaa11111111",
    closure_evidence_ref: null,
    accepted_by_review_decision_id: null,
    closed_at: null,
    counterparty: { person_id: "per_aaaaaaaa11111111", display_name: "Ada" },
    ...overrides,
  };
}

function history(overrides: Record<string, unknown> = {}) {
  return {
    history_id: "chst_aaaaaaaa11111111",
    commitment_id: "cmt_aaaaaaaa11111111",
    action: "update",
    actor: "principal",
    outcome: "applied",
    before_version: 1,
    after_version: 2,
    occurred_at: AT,
    recorded_at: AT,
    ...overrides,
  };
}

function payload(overrides: Record<string, unknown> = {}) {
  return { commitment: commitment(), history: history(), replayed: false, ...overrides };
}

describe("decodeCommitmentsUpdate", () => {
  it("accepts a Python update payload with history", () => {
    const decoded = decodeCommitmentsUpdate(payload());
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.history.after_version).toBe(2);
  });

  it("fails closed when history is omitted", () => {
    const { history: _, ...rest } = payload();
    expect(decodeCommitmentsUpdate(rest).ok).toBe(false);
  });

  it("fails closed when replayed is the wrong type", () => {
    expect(decodeCommitmentsUpdate(payload({ replayed: "false" })).ok).toBe(false);
  });

  it("fails closed when version is missing rather than inferring it", () => {
    const { version: _, ...rest } = commitment();
    expect(decodeCommitmentsUpdate(payload({ commitment: rest })).ok).toBe(false);
  });

  it("fails closed on an invalid history action enum", () => {
    expect(
      decodeCommitmentsUpdate(payload({ history: history({ action: "patch" }) })).ok,
    ).toBe(false);
  });

  it("fails closed when commitment is omitted", () => {
    const { commitment: _, ...rest } = payload();
    expect(decodeCommitmentsUpdate(rest).ok).toBe(false);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeCommitmentsUpdate(payload({ extra_update_field: true })).ok).toBe(true);
  });
});
