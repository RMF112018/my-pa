// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeEntitiesRelationshipsCreate } from "./entities.relationships.create";

const AT = "2026-08-09T12:00:00.000Z";

function receipt(overrides: Record<string, unknown> = {}) {
  return {
    record_id: "erel_aaaaaaaa11111111",
    record_family: "relationship",
    prior_version: null,
    version: 1,
    state: "active",
    receipt_id: "emut_aaaaaaaa11111111",
    audit_id: "audit_aaaaaaaa11111111",
    idempotency_key: "idem-1",
    superseded_id: null,
    evidence_refs: [],
    replayed: false,
    issued_at: AT,
    ...overrides,
  };
}

describe("decodeEntitiesRelationshipsCreate", () => {
  it("accepts a Python directed receipt", () => {
    const decoded = decodeEntitiesRelationshipsCreate(receipt());
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.record_id).toBe("erel_aaaaaaaa11111111");
      expect(decoded.value.record_family).toBe("relationship");
      expect(decoded.value.prior_version).toBeNull();
      expect(decoded.value.version).toBe(1);
      expect(decoded.value.state).toBe("active");
      expect(decoded.value.receipt_id).toBe("emut_aaaaaaaa11111111");
      expect(decoded.value.replayed).toBe(false);
    }
  });

  it("fails closed when receipt_id is missing", () => {
    const { receipt_id: _, ...rest } = receipt();
    expect(decodeEntitiesRelationshipsCreate(rest).ok).toBe(false);
  });

  it("fails closed when a required string is empty", () => {
    expect(decodeEntitiesRelationshipsCreate(receipt({ record_id: "" })).ok).toBe(false);
    expect(decodeEntitiesRelationshipsCreate(receipt({ receipt_id: "" })).ok).toBe(false);
    expect(decodeEntitiesRelationshipsCreate(receipt({ idempotency_key: "" })).ok).toBe(false);
  });

  it("fails closed when record_family is not relationship", () => {
    expect(decodeEntitiesRelationshipsCreate(receipt({ record_family: "entity" })).ok).toBe(
      false,
    );
  });

  it("fails closed when prior_version is omitted", () => {
    const { prior_version: _, ...rest } = receipt();
    expect(decodeEntitiesRelationshipsCreate(rest).ok).toBe(false);
  });

  it("fails closed when evidence_refs is omitted or not strings", () => {
    const { evidence_refs: _, ...rest } = receipt();
    expect(decodeEntitiesRelationshipsCreate(rest).ok).toBe(false);
    expect(decodeEntitiesRelationshipsCreate(receipt({ evidence_refs: [1] })).ok).toBe(false);
    expect(decodeEntitiesRelationshipsCreate(receipt({ evidence_refs: [""] })).ok).toBe(false);
  });

  it("fails closed when version is below 1", () => {
    expect(decodeEntitiesRelationshipsCreate(receipt({ version: 0 })).ok).toBe(false);
  });

  it("ignores unknown extra top-level fields", () => {
    const decoded = decodeEntitiesRelationshipsCreate(receipt({ extra_receipt_field: "ignored" }));
    expect(decoded.ok).toBe(true);
  });
});
