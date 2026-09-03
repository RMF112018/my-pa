// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeCommitmentsHistory } from "./commitments.history";

const ENTRY = {
  history_id: "chst_aaaa0001aaaa0001aaaa0001",
  commitment_id: "cmt_aaaa0001aaaa0001aaaa0001",
  action: "create",
  actor: "principal",
  outcome: "applied",
  before_version: 0,
  after_version: 1,
  occurred_at: "2026-01-01T00:00:00+00:00",
  recorded_at: "2026-01-01T00:00:00+00:00",
};

describe("decodeCommitmentsHistory", () => {
  it("accepts a Python-derived history page", () => {
    expect(decodeCommitmentsHistory({ history: [ENTRY] }).ok).toBe(true);
  });

  it("ignores unknown extra fields", () => {
    expect(decodeCommitmentsHistory({ history: [{ ...ENTRY, extra: 1 }] }).ok).toBe(true);
  });

  it("fails closed when history is omitted", () => {
    expect(decodeCommitmentsHistory({}).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeCommitmentsHistory({}).ok).toBe(false);
    expect(decodeCommitmentsHistory({ history: [] }).ok).toBe(true);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeCommitmentsHistory({ history: 1 }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { actor: _, ...rest } = ENTRY;
    expect(decodeCommitmentsHistory({ history: [rest] }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(decodeCommitmentsHistory({ history: [{ ...ENTRY, action: "delete" }] }).ok).toBe(false);
  });
});
