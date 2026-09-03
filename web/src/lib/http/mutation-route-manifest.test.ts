import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  MUTATION_ROUTE_MANIFEST,
  type MutationHttpMethod,
  type MutationRouteClassification,
} from "@/lib/http/mutation-route-manifest";

const MUTATING_EXPORT_PATTERN =
  String.raw`export\s+(?:async\s+)?function\s+(POST|PUT|PATCH|DELETE)\b`;
const GET_EXPORT = /export\s+(?:async\s+)?function\s+GET\b/;

function mutatingExportRegex(): RegExp {
  return new RegExp(MUTATING_EXPORT_PATTERN, "g");
}

const CLASSIFICATIONS: ReadonlySet<MutationRouteClassification> = new Set([
  "AUTHENTICATED_BROWSER_MUTATION",
  "PRE_AUTH_BROWSER_MUTATION",
  "INTERNAL_NOT_BROWSER",
]);

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = join(here, "../../..");
const apiRoot = join(here, "../../app/api");

type Discovered = { readonly method: MutationHttpMethod; readonly path: string };

function keyOf(method: string, path: string): string {
  return `${method} ${path}`;
}

function walkRouteFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const full = join(directory, entry);
    if (statSync(full).isDirectory()) return walkRouteFiles(full);
    return entry === "route.ts" ? [full] : [];
  });
}

function discoverMutatingHandlers(): Discovered[] {
  const found: Discovered[] = [];
  for (const full of walkRouteFiles(apiRoot)) {
    const source = readFileSync(full, "utf8");
    const path = relative(webRoot, full).split("\\").join("/");
    for (const match of source.matchAll(mutatingExportRegex())) {
      found.push({ method: match[1] as MutationHttpMethod, path });
    }
  }
  return found;
}

describe("mutation route inventory", () => {
  const discovered = discoverMutatingHandlers();
  const discoveredKeys = new Set(discovered.map((entry) => keyOf(entry.method, entry.path)));
  const manifestKeys = new Set(MUTATION_ROUTE_MANIFEST.map((entry) => keyOf(entry.method, entry.path)));

  it("matches both async and non-async mutating exports", () => {
    expect(mutatingExportRegex().exec("export async function POST")?.[1]).toBe("POST");
    expect(mutatingExportRegex().exec("export function POST")?.[1]).toBe("POST");
    expect(mutatingExportRegex().exec("export function PATCH")?.[1]).toBe("PATCH");
    expect(mutatingExportRegex().exec("export async function DELETE")?.[1]).toBe("DELETE");
    expect(mutatingExportRegex().exec("export function GET")).toBeNull();
  });

  it("discovers mutating handlers on disk, including Capture and Review decide", () => {
    expect(discovered.length).toBeGreaterThan(0);
    expect(discoveredKeys.has("POST src/app/api/capture/route.ts")).toBe(true);
    expect(discoveredKeys.has("POST src/app/api/review/[id]/decide/route.ts")).toBe(true);
    expect(discoveredKeys.has("POST src/app/api/commitments/route.ts")).toBe(true);
    expect(discoveredKeys.has("POST src/app/api/tasks/route.ts")).toBe(true);
  });

  it("classifies every discovered mutating handler", () => {
    const unclassified = discovered.filter(
      (entry) => !manifestKeys.has(keyOf(entry.method, entry.path)),
    );
    expect(
      unclassified,
      unclassified.map((entry) => `unclassified mutating handler: ${keyOf(entry.method, entry.path)}`).join("\n"),
    ).toEqual([]);
  });

  it("has no extra manifest entries that do not exist on disk", () => {
    const extras = MUTATION_ROUTE_MANIFEST.filter((entry) => {
      const onDisk = existsSync(join(webRoot, entry.path));
      const discoveredHere = discoveredKeys.has(keyOf(entry.method, entry.path));
      return !onDisk || !discoveredHere;
    });
    expect(
      extras,
      extras.map((entry) => `manifest entry has no mutating handler on disk: ${keyOf(entry.method, entry.path)}`).join("\n"),
    ).toEqual([]);
  });

  it("uses only the contracted classification enum", () => {
    expect(CLASSIFICATIONS).toEqual(
      new Set<MutationRouteClassification>([
        "AUTHENTICATED_BROWSER_MUTATION",
        "PRE_AUTH_BROWSER_MUTATION",
        "INTERNAL_NOT_BROWSER",
      ]),
    );
    for (const entry of MUTATION_ROUTE_MANIFEST) {
      expect(CLASSIFICATIONS.has(entry.classification)).toBe(true);
    }
    expect(MUTATION_ROUTE_MANIFEST.some((entry) => entry.classification === "INTERNAL_NOT_BROWSER")).toBe(
      false,
    );
  });

  it("does not inventory GET-only routes", () => {
    const getOnly = walkRouteFiles(apiRoot).filter((full) => {
      const source = readFileSync(full, "utf8");
      return GET_EXPORT.test(source) && source.match(mutatingExportRegex()) === null;
    });
    expect(getOnly.length).toBeGreaterThan(0);
    const getOnlyPaths = new Set(
      getOnly.map((full) => relative(webRoot, full).split("\\").join("/")),
    );
    const leaked = MUTATION_ROUTE_MANIFEST.filter((entry) => getOnlyPaths.has(entry.path));
    expect(
      leaked,
      leaked.map((entry) => `GET-only route in mutating inventory: ${keyOf(entry.method, entry.path)}`).join("\n"),
    ).toEqual([]);
  });
});
