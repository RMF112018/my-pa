// @vitest-environment node
import { describe, expect, it } from "vitest";
import { decodeEnvelope } from "./envelope";
import type { DecodedDisclosure } from "./disclosure";

const DISCLOSURE: DecodedDisclosure = {
  coverage: { state: "not_enrolled" },
  freshness: { observed_at: "2026-08-09T12:00:00Z", state: "current_for_observed_version" },
  trust: { level: "source_original", basis: ["user_authored_record"] },
  truncation: { is_truncated: false },
  limitations: [],
  partial_result: false,
};

const PROBLEM = {
  code: "not_found",
  message: "no such thing",
  correlation_id: "corr_synthetic_0001",
};

describe("decodeEnvelope", () => {
  it("accepts success with a result and disclosure", () => {
    const decoded = decodeEnvelope({ result: { pulse_items: [] }, disclosure: DISCLOSURE });
    expect(decoded.ok).toBe(true);
    if (decoded.ok && decoded.value.kind === "success") {
      expect(decoded.value.result).toEqual({ pulse_items: [] });
      expect(decoded.value.disclosure.coverage.state).toBe("not_enrolled");
    }
  });

  it("ignores extra unknown envelope fields", () => {
    const decoded = decodeEnvelope({
      contract_version: "v1",
      request_id: "bff-synthetic-0001",
      extra_envelope_field: "ignored",
      result: { a: 1 },
      disclosure: DISCLOSURE,
    });
    expect(decoded.ok).toBe(true);
    if (decoded.ok && decoded.value.kind === "success") {
      expect(decoded.value.result).toEqual({ a: 1 });
    }
  });

  it("reports success without disclosure as uncontracted", () => {
    const decoded = decodeEnvelope({ result: { a: 1 } });
    expect(decoded.ok).toBe(false);
    if (!decoded.ok) expect(decoded.code).toBe("gateway_response_uncontracted");
  });

  it("fails closed when result and error are both present", () => {
    const decoded = decodeEnvelope({ result: { a: 1 }, error: PROBLEM });
    expect(decoded.ok).toBe(false);
    if (!decoded.ok) expect(decoded.code).toBe("upstream_contract_invalid");
  });

  it("fails closed when disclosure and error are both present", () => {
    const decoded = decodeEnvelope({ disclosure: DISCLOSURE, error: PROBLEM });
    expect(decoded.ok).toBe(false);
    if (!decoded.ok) expect(decoded.code).toBe("upstream_contract_invalid");
  });

  it("fails closed when both disclosure and error are missing", () => {
    const decoded = decodeEnvelope({ contract_version: "v1" });
    expect(decoded.ok).toBe(false);
    if (!decoded.ok) expect(decoded.code).toBe("upstream_contract_invalid");
  });

  it("fails closed when success omits result rather than substituting {}", () => {
    const omitted = decodeEnvelope({ disclosure: DISCLOSURE });
    expect(omitted.ok).toBe(false);
    if (!omitted.ok) expect(omitted.code).toBe("upstream_contract_invalid");
    const nulled = decodeEnvelope({ result: null, disclosure: DISCLOSURE });
    expect(nulled.ok).toBe(false);
  });

  it("decodes an envelope error", () => {
    const decoded = decodeEnvelope({ error: PROBLEM });
    expect(decoded.ok).toBe(true);
    if (decoded.ok && decoded.value.kind === "problem") {
      expect(decoded.value.problem.code).toBe("not_found");
      expect(decoded.value.problem.correlationId).toBe("corr_synthetic_0001");
    }
  });

  it("decodes a bare problem detail", () => {
    const decoded = decodeEnvelope(PROBLEM);
    expect(decoded.ok).toBe(true);
    if (decoded.ok && decoded.value.kind === "problem") {
      expect(decoded.value.problem.code).toBe("not_found");
    }
  });

  it("never echoes the raw payload in a failure message", () => {
    const decoded = decodeEnvelope({ result: { secret: "sid_xxxxx" }, error: PROBLEM });
    expect(decoded.ok).toBe(false);
    if (!decoded.ok) {
      expect(decoded.message).not.toContain("sid_xxxxx");
      expect(decoded.message).not.toContain("secret");
    }
  });
});
