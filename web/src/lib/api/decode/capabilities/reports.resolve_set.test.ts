// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeReportsResolveSet } from "./reports.resolve_set";

const MEMBER = {
  member_id: "communications",
  focus_area_id: "communications",
  source_lane: null,
  readiness: "MISSING",
  required: false,
  artifact_id: null,
  producer_run_id: null,
  content_sha256: null,
  committed_at: null,
  readiness_reason: "absent",
};

const PAYLOAD = {
  cycle_run_id: "micr_aaaaaaaa11111111",
  cycle_id: "morning_intelligence",
  business_date: "2026-08-20",
  set_id: "morning_brief_inputs",
  aggregate: "DEGRADED",
  members: [MEMBER],
  missing_focus_areas: ["communications"],
  partial_focus_areas: [],
};

describe("decodeReportsResolveSet", () => {
  it("accepts a Python-derived success payload without flattening members", () => {
    const decoded = decodeReportsResolveSet(PAYLOAD);
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.aggregate).toBe("DEGRADED");
      expect(decoded.value.members).toHaveLength(1);
      expect(decoded.value.members[0]?.readiness).toBe("MISSING");
      expect(decoded.value.members[0]?.required).toBe(false);
      expect(decoded.value.members[0]?.readiness_reason).toBe("absent");
      expect(decoded.value.missing_focus_areas).toEqual(["communications"]);
      expect(decoded.value.partial_focus_areas).toEqual([]);
    }
  });

  it("keeps partial focus areas distinct from missing ones", () => {
    const decoded = decodeReportsResolveSet({
      ...PAYLOAD,
      missing_focus_areas: [],
      partial_focus_areas: ["communications", "decision_approval"],
    });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.missing_focus_areas).toEqual([]);
      expect(decoded.value.partial_focus_areas).toEqual(["communications", "decision_approval"]);
    }
  });

  it("still decodes a BLOCKED aggregate for the sets that can block", () => {
    const decoded = decodeReportsResolveSet({
      ...PAYLOAD,
      set_id: "reporter_input",
      aggregate: "BLOCKED",
      missing_focus_areas: [],
      partial_focus_areas: [],
    });
    expect(decoded.ok && decoded.value.aggregate).toBe("BLOCKED");
  });

  it("fails closed when a focus-area gap array is omitted or not strings", () => {
    for (const key of ["missing_focus_areas", "partial_focus_areas"] as const) {
      const rest: Record<string, unknown> = { ...PAYLOAD };
      delete rest[key];
      expect(decodeReportsResolveSet(rest).ok).toBe(false);
      expect(decodeReportsResolveSet({ ...PAYLOAD, [key]: [1] }).ok).toBe(false);
      expect(decodeReportsResolveSet({ ...PAYLOAD, [key]: "communications" }).ok).toBe(false);
      expect(decodeReportsResolveSet({ ...PAYLOAD, [key]: null }).ok).toBe(false);
    }
  });

  it("ignores unknown extra fields", () => {
    expect(decodeReportsResolveSet({ ...PAYLOAD, extra: 1, members: [{ ...MEMBER, extra: 1 }] }).ok).toBe(
      true,
    );
  });

  it("fails closed when members is omitted", () => {
    const { members: _, ...rest } = PAYLOAD;
    expect(decodeReportsResolveSet(rest).ok).toBe(false);
  });

  it("does not treat an omitted array as empty success", () => {
    expect(decodeReportsResolveSet({}).ok).toBe(false);
    const empty = decodeReportsResolveSet({ ...PAYLOAD, members: [] });
    expect(empty.ok).toBe(true);
    if (empty.ok) expect(empty.value.members).toEqual([]);
  });

  it("fails closed on a wrong type", () => {
    expect(decodeReportsResolveSet({ ...PAYLOAD, members: 1 }).ok).toBe(false);
  });

  it("fails closed when a required field is missing", () => {
    const { member_id: _, ...rest } = MEMBER;
    expect(decodeReportsResolveSet({ ...PAYLOAD, members: [rest] }).ok).toBe(false);
  });

  it("fails closed on an invalid enum", () => {
    expect(decodeReportsResolveSet({ ...PAYLOAD, aggregate: "OK" }).ok).toBe(false);
    expect(
      decodeReportsResolveSet({ ...PAYLOAD, members: [{ ...MEMBER, readiness: "ok" }] }).ok,
    ).toBe(false);
  });
});
