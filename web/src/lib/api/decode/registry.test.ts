// @vitest-environment node
import { describe, expect, it } from "vitest";
import contract from "@/contracts/gateway.json";
import { DECODERS } from "./index";

describe("DECODERS registry", () => {
  it("covers exactly the gateway.json capabilities", () => {
    const contractKeys = Object.keys(contract.capabilities).sort();
    const decoderKeys = Object.keys(DECODERS).sort();
    expect(decoderKeys).toEqual(contractKeys);
    expect(decoderKeys).toHaveLength(contractKeys.length);
    expect(decoderKeys.length).toBeGreaterThan(0);
    expect(decoderKeys).toContain("capture.create");
    expect(decoderKeys).toContain("tasks.read");
  });

  it("does not include SESSION_INTERNAL_SERVICE or WEBAUTHN", () => {
    expect(DECODERS).not.toHaveProperty("SESSION_INTERNAL_SERVICE");
    expect(DECODERS).not.toHaveProperty("WEBAUTHN");
    expect(Object.keys(DECODERS).some((key) => /webauthn|session_internal/i.test(key))).toBe(
      false,
    );
  });
});
