// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeEntitiesRelationshipsEnd } from "./entities.relationships.end";

const AT = "2026-08-09T12:00:00.000Z";

function receipt(overrides: Record<string, unknown> = {}) {
  return {
    record_id: "erel_aaaaaaaa11111111",
    record_family: "relationship",
    prior_version: 1,
    version: 2,
    state: "ended",
    receipt_id: "emut_aaaaaaaa11111111",
    audit_id: "audit_aaaaaaaa11111111",
    idempotency_key: "idem-1",
    superseded_id: null,
    evidence_refs: [],
    replayed: true,
    issued_at: AT,
    ...overrides,
  };
}

describe("decodeEntitiesRelationshipsEnd", () => {
  it("accepts a Python directed receipt in the ended state", () => {
    const decoded = decodeEntitiesRelationshipsEnd(receipt());
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.state).toBe("ended");
      expect(decoded.value.replayed).toBe(true);
      expect(decoded.value.superseded_id).toBeNull();
    }
  });

  it("accepts superseded_id when present", () => {
    const decoded = decodeEntitiesRelationshipsEnd(
      receipt({ state: "superseded", superseded_id: "erel_bbbbbbbb22222222" }),
    );
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.superseded_id).toBe("erel_bbbbbbbb22222222");
    }
  });

  it("fails closed when audit_id is missing", () => {
    const { audit_id: _, ...rest } = receipt();
    expect(decodeEntitiesRelationshipsEnd(rest).ok).toBe(false);
  });

  it("fails closed when prior_version is the wrong type", () => {
    expect(decodeEntitiesRelationshipsEnd(receipt({ prior_version: "1" })).ok).toBe(false);
  });

  it("fails closed when evidence_refs is omitted", () => {
    const { evidence_refs: _, ...rest } = receipt();
    expect(decodeEntitiesRelationshipsEnd(rest).ok).toBe(false);
  });
});
