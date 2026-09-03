// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeDisclosure } from "./disclosure";

const VALID = {
  coverage: { state: "not_enrolled" as const },
  freshness: { observed_at: "2026-08-09T12:00:00Z", state: "current_for_observed_version" as const },
  trust: { level: "source_original" as const, basis: ["user_authored_record"] },
  truncation: { is_truncated: false },
  limitations: [] as string[],
  partial_result: false,
};

describe("decodeDisclosure", () => {
  it("accepts a valid decoded-shape object", () => {
    const decoded = decodeDisclosure(VALID);
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.coverage.state).toBe("not_enrolled");
      expect(decoded.value.trust.level).toBe("source_original");
      expect(decoded.value.freshness.observed_at).toBe("2026-08-09T12:00:00Z");
    }
  });

  it("ignores extra unknown fields", () => {
    const decoded = decodeDisclosure({
      ...VALID,
      scope: { source_ids: ["src_aaaaaaaa11111111"], enrollment_ids: ["enr_aaaaaaaa11111111"] },
      source_references: [],
      classification: "private_local",
      cloud_eligible: false,
      unavailable_evidence: [],
      coverage: {
        state: "not_enrolled",
        eligible: 0,
        processed: 0,
        quarantined: 0,
        unsupported: 0,
      },
      truncation: { is_truncated: false, reason: null },
    });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value).not.toHaveProperty("scope");
      expect(decoded.value.coverage).toEqual({ state: "not_enrolled" });
    }
  });

  it("fails closed when a required field is missing", () => {
    const { trust: _trust, ...missingTrust } = VALID;
    expect(decodeDisclosure(missingTrust).ok).toBe(false);
    expect(decodeDisclosure({ ...VALID, freshness: { state: "stale" } }).ok).toBe(false);
    expect(decodeDisclosure({ ...VALID, limitations: undefined }).ok).toBe(false);
    expect(decodeDisclosure({ ...VALID, partial_result: undefined }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(decodeDisclosure({ ...VALID, coverage: { state: "unknown" } }).ok).toBe(false);
    expect(decodeDisclosure({ ...VALID, trust: { ...VALID.trust, level: "derived" } }).ok).toBe(
      false,
    );
    expect(
      decodeDisclosure({
        ...VALID,
        freshness: { ...VALID.freshness, state: "current" },
      }).ok,
    ).toBe(false);
  });

  it("does not default missing coverage or trust", () => {
    const missingCoverage = decodeDisclosure({ ...VALID, coverage: undefined });
    expect(missingCoverage.ok).toBe(false);
    const missingLevel = decodeDisclosure({
      ...VALID,
      trust: { basis: ["user_authored_record"] },
    });
    expect(missingLevel.ok).toBe(false);
  });

  it("never echoes the raw input in the failure message", () => {
    const leaked = "sid_this_must_not_appear_in_messages";
    const decoded = decodeDisclosure({ ...VALID, trust: { level: leaked, basis: [] } });
    expect(decoded.ok).toBe(false);
    if (!decoded.ok) {
      expect(decoded.message).not.toContain(leaked);
      expect(decoded.code).toBe("upstream_contract_invalid");
    }
  });
});
