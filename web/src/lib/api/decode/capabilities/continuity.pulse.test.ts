// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeContinuityPulse, type ContinuityPulseResult } from "./continuity.pulse";

const ITEM = {
  pulse_id: "pls_aaaa0001aaaa0001aaaa0001",
  item_type: "commitment" as const,
  item_ref: "cmt_aaaa0001aaaa0001aaaa0001",
  reason_code: "commitment_overdue" as const,
  reason: "two days past its agreed moment",
  basis_refs: ["asr_aaaa0001aaaa0001aaaa0001"],
  consequence: null,
  next_step: null,
  attention_rank: 1,
  generated_at: "2026-01-01T00:00:00Z",
};

const VALID: ContinuityPulseResult = { pulse_items: [ITEM] };

describe("decodeContinuityPulse", () => {
  it("accepts a Python-derived success payload", () => {
    const decoded = decodeContinuityPulse(VALID);
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value.pulse_items[0]?.attention_rank).toBe(1);
  });

  it("ignores unknown extra fields", () => {
    const decoded = decodeContinuityPulse({
      ...VALID,
      unexpected: 1,
      pulse_items: [{ ...ITEM, extra_item_field: true }],
    });
    expect(decoded.ok).toBe(true);
  });

  it("fails closed when pulse_items is omitted", () => {
    const decoded = decodeContinuityPulse({ generated_at: ITEM.generated_at });
    expect(decoded.ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    const omitted = decodeContinuityPulse({});
    expect(omitted.ok).toBe(false);
    const empty = decodeContinuityPulse({ pulse_items: [] });
    expect(empty.ok).toBe(true);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeContinuityPulse({ pulse_items: 1 }).ok).toBe(false);
    expect(decodeContinuityPulse({ pulse_items: [{ ...ITEM, basis_refs: "x" }] }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { reason_code: _, ...rest } = ITEM;
    expect(decodeContinuityPulse({ pulse_items: [rest] }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(
      decodeContinuityPulse({ pulse_items: [{ ...ITEM, item_type: "recent" }] }).ok,
    ).toBe(false);
    expect(
      decodeContinuityPulse({ pulse_items: [{ ...ITEM, reason_code: "recently_updated" }] }).ok,
    ).toBe(false);
  });
});
