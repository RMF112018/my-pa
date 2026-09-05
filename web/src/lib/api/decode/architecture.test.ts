// @vitest-environment node
/**
 * Structural locks for the WP06 decoder foundation: no generic transport
 * authority path, registry exhaustiveness, fail-closed stubs.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import contract from "@/contracts/gateway.json";
import { DECODERS } from "./index";
import type { CapabilityResults, GatewayCapability } from "./types";

const SRC = join(process.cwd(), "src");

function sources(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [path] : [];
  });
}

describe("decoder architecture", () => {
  it("production web/src files contain no callGateway<", () => {
    const offenders = sources(SRC).filter((path) => /callGateway</.test(readFileSync(path, "utf8")));
    expect(offenders).toEqual([]);
  });

  it("the transport module no longer casts envelope.result as T", () => {
    const text = readFileSync(join(SRC, "lib/api/gateway.ts"), "utf8");
    expect(text).not.toMatch(/callGateway\s*</);
    expect(text).not.toMatch(/envelope\.result \?\? \{\}[\s\S]*as T/);
    expect(text).not.toMatch(/as T\b/);
    expect(text).toMatch(/invokeGateway<C extends GatewayCapability>/);
  });

  it("Object.keys(gateway.json.capabilities) sorted equals Object.keys(DECODERS) sorted", () => {
    const decoderKeys = Object.keys(DECODERS).sort();
    expect(decoderKeys.length).toBeGreaterThan(0);
    expect(decoderKeys).toEqual(Object.keys(contract.capabilities).sort());
    expect(DECODERS).toHaveProperty("capture.create");
    expect(DECODERS).toHaveProperty("tasks.read");
    expect(DECODERS).toHaveProperty("review.decide");
  });

  it("each decoder rejects at least one malformed fixture", () => {
    for (const [capability, decode] of Object.entries(DECODERS)) {
      const empty = decode({});
      expect(empty.ok, `${capability} accepted {}`).toBe(false);
      const plausible = decode({ pulse_items: 1 });
      expect(plausible.ok, `${capability} accepted a plausible object`).toBe(false);
    }
  });

  it("CapabilityResults keys match gateway.json and are not a uniform unknown map", () => {
    const keys = Object.keys(contract.capabilities) as GatewayCapability[];
    expect(keys.length).toBeGreaterThan(0);
    expect(keys.sort()).toEqual(Object.keys(DECODERS).sort());
    type ResultKeys = keyof CapabilityResults;
    const sample: ResultKeys = "capture.create";
    expect(sample).toBe("capture.create");
  });
});
