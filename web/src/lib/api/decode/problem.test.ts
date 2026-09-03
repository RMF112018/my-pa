// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeProblem, ERROR_CODES, PROBLEM_ERROR_CLASS } from "./problem";

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

  it("maps rate_limited as unavailable until Worker E", () => {
    // WP06-E: rate_limited HTTP status stays 503 until Worker E
    expect(PROBLEM_ERROR_CLASS.rate_limited).toBe("unavailable");
  });
});
