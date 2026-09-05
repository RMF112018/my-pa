// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeEntitiesRelationshipsRevise } from "./entities.relationships.revise";

const AT = "2026-08-09T12:00:00.000Z";

function receipt(overrides: Record<string, unknown> = {}) {
  return {
    record_id: "erel_aaaaaaaa11111111",
    record_family: "relationship",
    prior_version: 1,
    version: 2,
    state: "active",
    receipt_id: "emut_aaaaaaaa11111111",
    audit_id: "audit_aaaaaaaa11111111",
    idempotency_key: "idem-1",
    superseded_id: null,
    evidence_refs: ["eobs_aaaaaaaa11111111"],
    replayed: false,
    issued_at: AT,
    ...overrides,
  };
}

describe("decodeEntitiesRelationshipsRevise", () => {
  it("accepts a Python directed receipt with a prior version", () => {
    const decoded = decodeEntitiesRelationshipsRevise(receipt());
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.prior_version).toBe(1);
      expect(decoded.value.version).toBe(2);
      expect(decoded.value.evidence_refs).toEqual(["eobs_aaaaaaaa11111111"]);
    }
  });

  it("fails closed when version is below 1", () => {
    expect(decodeEntitiesRelationshipsRevise(receipt({ version: 0 })).ok).toBe(false);
  });

  it("fails closed when state is not a directed state", () => {
    expect(decodeEntitiesRelationshipsRevise(receipt({ state: "retired" })).ok).toBe(false);
  });

  it("fails closed when replayed is omitted", () => {
    const { replayed: _, ...rest } = receipt();
    expect(decodeEntitiesRelationshipsRevise(rest).ok).toBe(false);
  });

  it("fails closed when issued_at is the wrong type", () => {
    expect(decodeEntitiesRelationshipsRevise(receipt({ issued_at: 1 })).ok).toBe(false);
  });

  it("fails closed when record_family is not relationship", () => {
    expect(decodeEntitiesRelationshipsRevise(receipt({ record_family: "entity" })).ok).toBe(false);
  });
});
