// @vitest-environment node
/**
 * Vitest decoders accept the same Python-committed success bytes.
 *
 * `architecture.test.ts` already rejects `{}` for every capability. This file
 * is the positive lock: a live Python dump under fixtures/python must decode.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { DECODERS } from "./index";
import type { GatewayCapability } from "./types";

const FIXTURE = join(process.cwd(), "src/lib/api/decode/fixtures/python/success.json");

function loadSuccess(): Record<string, unknown> {
  const parsed: unknown = JSON.parse(readFileSync(FIXTURE, "utf8"));
  expect(parsed).toBeTypeOf("object");
  expect(parsed).not.toBeNull();
  return parsed as Record<string, unknown>;
}

describe("Python/Vitest success-decoder parity", () => {
  it("decodes every committed Python success payload", () => {
    const fixtures = loadSuccess();
    const capabilities = Object.keys(fixtures);
    expect(capabilities.length).toBeGreaterThan(0);
    for (const capability of capabilities) {
      expect(capability in DECODERS, `${capability} is not a registered decoder`).toBe(true);
      const decoded = DECODERS[capability as GatewayCapability](fixtures[capability]);
      expect(decoded.ok, `${capability} rejected its Python fixture`).toBe(true);
    }
  });

  it("fails closed when a required array is dropped from a Python fixture", () => {
    const fixtures = loadSuccess();
    const pulse = fixtures["continuity.pulse"];
    expect(pulse).toBeTypeOf("object");
    const mutated = { ...(pulse as Record<string, unknown>) };
    delete mutated.pulse_items;
    const decoded = DECODERS["continuity.pulse"](mutated);
    expect(decoded.ok).toBe(false);
  });

  it("every admitted capability has a Python fixture", () => {
    const fixtures = loadSuccess();
    expect(Object.keys(fixtures).sort()).toEqual(Object.keys(DECODERS).sort());
  });
});
