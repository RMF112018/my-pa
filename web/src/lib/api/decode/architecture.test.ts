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

const SRC = join(process.cwd(), "src");

function sources(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [path] : [];
  });
}

describe("decoder architecture", () => {
  it("production web/src has no generic callGateway<T definition", () => {
    // Route/RSC call sites may still pass type arguments (`callGateway<{…}>`)
    // until Workers C/D migrate them. The generic *definition* `callGateway<T`
    // is the verified defect and must not remain in production sources.
    const offenders = sources(SRC).filter((path) => {
      const text = readFileSync(path, "utf8");
      return /callGateway<T\b/.test(text) || /function callGateway\s*</.test(text);
    });
    expect(offenders).toEqual([]);
  });

  it("the transport module no longer casts envelope.result as T", () => {
    const text = readFileSync(join(SRC, "lib/api/gateway.ts"), "utf8");
    expect(text).not.toMatch(/callGateway\s*</);
    expect(text).not.toMatch(/envelope\.result \?\? \{\}[\s\S]*as T/);
    expect(text).not.toMatch(/as T\b/);
  });

  it("owned decode and gateway production files contain no callGateway<", () => {
    const owned = [join(SRC, "lib/api/gateway.ts"), ...sources(join(SRC, "lib/api/decode"))];
    const offenders = owned.filter((path) => /callGateway</.test(readFileSync(path, "utf8")));
    expect(offenders).toEqual([]);
  });

  it("Object.keys(gateway.json.capabilities) sorted equals Object.keys(DECODERS) sorted", () => {
    expect(Object.keys(DECODERS).sort()).toEqual(Object.keys(contract.capabilities).sort());
  });

  it("each decoder rejects at least one malformed fixture", () => {
    for (const [capability, decode] of Object.entries(DECODERS)) {
      const empty = decode({});
      expect(empty.ok, `${capability} accepted {}`).toBe(false);
      const plausible = decode({ pulse_items: 1 });
      expect(plausible.ok, `${capability} accepted a plausible object`).toBe(false);
    }
  });
});
