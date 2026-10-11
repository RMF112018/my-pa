// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  decodeProblem,
  ERROR_CODES,
  httpStatusForProblem,
  MAX_ALLOWED_VALUE_ENTRIES,
  MAX_ALLOWED_VALUES,
  PROBLEM_ERROR_CLASS,
} from "./problem";

describe("decodeProblem", () => {
  it("reads code, message, and correlation id", () => {
    const decoded = decodeProblem({
      code: "denied",
      message: "refused",
      correlation_id: "corr_synthetic_0001",
      retry: "after_authority_change",
    });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value).toEqual({
        code: "denied",
        message: "refused",
        correlationId: "corr_synthetic_0001",
      });
    }
  });

  it("ignores extra unknown keys and does not echo safe_details", () => {
    const decoded = decodeProblem({
      code: "invalid_request",
      message: "the request was refused",
      correlation_id: "corr_synthetic_0002",
      retry: "after_correction",
      safe_details: ["capture_text", "sid_must_not_leak"],
      extra: { payload: "nope" },
    });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value).not.toHaveProperty("safe_details");
      expect(JSON.stringify(decoded.value)).not.toContain("sid_must_not_leak");
      expect(JSON.stringify(decoded.value)).not.toContain("capture_text");
    }
  });

  it("fails closed when code is missing", () => {
    const decoded = decodeProblem({ message: "refused" });
    expect(decoded.ok).toBe(false);
    if (!decoded.ok) {
      expect(decoded.code).toBe("upstream_contract_invalid");
      expect(decoded.message).not.toContain("refused");
    }
  });

  it("covers the eleven public error codes in the class map", () => {
    expect(Object.keys(PROBLEM_ERROR_CLASS).sort()).toEqual([...ERROR_CODES].sort());
  });

  it("keeps rate_limited as errorClass unavailable with HTTP 429", () => {
    expect(PROBLEM_ERROR_CLASS.rate_limited).toBe("unavailable");
    expect(httpStatusForProblem("rate_limited")).toBe(429);
    expect(httpStatusForProblem("unavailable")).toBeUndefined();
    expect(httpStatusForProblem("denied")).toBeUndefined();
    expect(httpStatusForProblem("conflict")).toBeUndefined();
  });

  it("does not echo safe_details or extra keys into a decoded problem", () => {
    const decoded = decodeProblem({
      code: "rate_limited",
      message: "slow down",
      correlation_id: "corr_synthetic_0003",
      safe_details: ["assertion_payload", "recovery_code_xyz"],
    });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value.code).toBe("rate_limited");
      expect(JSON.stringify(decoded.value)).not.toContain("assertion_payload");
      expect(JSON.stringify(decoded.value)).not.toContain("recovery_code_xyz");
    }
  });
});

describe("decodeProblem allowed_values", () => {
  const base = {
    code: "invalid_request",
    message: "the request was refused",
    correlation_id: "corr_synthetic_0004",
    retry: "after_correction",
    safe_details: ["artifact_kind", "stage"],
  };
  const stage = {
    detail: "stage",
    values: ["collector", "researcher", "synthesizer", "reporter", "morning_brief"],
    truncated: false,
  };

  it("decodes a well-formed list on invalid_request without echoing safe_details", () => {
    const decoded = decodeProblem({ ...base, allowed_values: [stage] });
    expect(decoded.ok).toBe(true);
    if (decoded.ok) {
      expect(decoded.value).toEqual({
        code: "invalid_request",
        message: "the request was refused",
        correlationId: "corr_synthetic_0004",
        allowedValues: [stage],
      });
      expect(decoded.value).not.toHaveProperty("safe_details");
      expect(decoded.value).not.toHaveProperty("safeDetails");
    }
  });

  it("keeps capitalised vocabulary tokens and the truncated marker", () => {
    const entry = { detail: "artifact_kind", values: ["READY", "focus_report", "v1.2-a"], truncated: true };
    const decoded = decodeProblem({ ...base, allowed_values: [entry] });
    expect(decoded.ok && decoded.value.allowedValues).toEqual([entry]);
  });

  it("is backward compatible: no allowed_values key means no allowedValues", () => {
    const decoded = decodeProblem(base);
    expect(decoded.ok).toBe(true);
    if (decoded.ok) expect(decoded.value).not.toHaveProperty("allowedValues");
  });

  it("drops the list on any code other than invalid_request", () => {
    for (const code of ERROR_CODES.filter((item) => item !== "invalid_request")) {
      const decoded = decodeProblem({ ...base, code, allowed_values: [stage] });
      expect(decoded.ok).toBe(true);
      if (decoded.ok) expect(decoded.value).not.toHaveProperty("allowedValues");
    }
  });

  it("drops an entry whose detail is not a safe_details token", () => {
    const stray = { ...stage, detail: "focus_area_id" };
    const decoded = decodeProblem({ ...base, allowed_values: [stray, stage] });
    expect(decoded.ok && decoded.value.allowedValues).toEqual([stage]);
    const noDetails = decodeProblem({ ...base, safe_details: undefined, allowed_values: [stage] });
    expect(noDetails.ok).toBe(true);
    if (noDetails.ok) expect(noDetails.value).not.toHaveProperty("allowedValues");
  });

  it("drops malformed entries without failing the problem", () => {
    const malformed: unknown[] = [
      "stage",
      null,
      { ...stage, detail: "Stage" },
      { ...stage, values: [] },
      { ...stage, values: ["has space"] },
      { ...stage, values: ["/etc/passwd"] },
      { ...stage, values: ["-leading"] },
      { ...stage, values: ["a".repeat(65)] },
      { ...stage, values: ["dup", "dup"] },
      { ...stage, values: [7] },
      { ...stage, values: "collector" },
      { ...stage, values: Array.from({ length: MAX_ALLOWED_VALUES + 1 }, (_, i) => `v${i}`) },
      { ...stage, truncated: "false" },
      { detail: "stage", values: ["collector"] },
    ];
    for (const entry of malformed) {
      const decoded = decodeProblem({ ...base, allowed_values: [entry] });
      expect(decoded.ok).toBe(true);
      if (decoded.ok) {
        expect(decoded.value.code).toBe("invalid_request");
        expect(decoded.value).not.toHaveProperty("allowedValues");
      }
    }
  });

  it("accepts exactly the value bound and drops a duplicate detail after the first", () => {
    const full = {
      detail: "artifact_kind",
      values: Array.from({ length: MAX_ALLOWED_VALUES }, (_, i) => `v${i}`),
      truncated: true,
    };
    const decoded = decodeProblem({
      ...base,
      allowed_values: [full, { ...full, values: ["other"] }],
    });
    expect(decoded.ok && decoded.value.allowedValues).toEqual([full]);
  });

  it("drops the whole list when it is not an array or exceeds the entry bound", () => {
    const details = Array.from({ length: MAX_ALLOWED_VALUE_ENTRIES + 1 }, (_, i) => `field_${i}`);
    const overLong = details.map((detail) => ({ detail, values: ["a"], truncated: false }));
    for (const allowed_values of [stage, "stage", overLong]) {
      const decoded = decodeProblem({ ...base, safe_details: details, allowed_values });
      expect(decoded.ok).toBe(true);
      if (decoded.ok) expect(decoded.value).not.toHaveProperty("allowedValues");
    }
  });

  it("does not echo unknown keys inside an entry", () => {
    const decoded = decodeProblem({
      ...base,
      allowed_values: [{ ...stage, leak: "sid_must_not_leak" }],
    });
    expect(decoded.ok && decoded.value.allowedValues).toEqual([stage]);
    expect(JSON.stringify(decoded)).not.toContain("sid_must_not_leak");
  });
});
