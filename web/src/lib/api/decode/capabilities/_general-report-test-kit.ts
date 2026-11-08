/**
 * Shared closed-contract checks for the standalone report decoder tests (WP07 U2).
 *
 * Test support only: imported by `reports.*.test.ts`, never by production code.
 * Every check starts from the committed Python fixture (`success.json`), so a
 * check describes the payload the gateway actually sends.
 */
import { expect } from "vitest";
import fixtures from "../fixtures/python/success.json";
import type { DecodeResult } from "../primitives";

type Path = readonly (string | number)[];
type Json = Record<string, unknown>;

export function canonicalFixture(capability: keyof typeof fixtures): Json {
  return structuredClone(fixtures[capability]) as Json;
}

function at(input: unknown, path: Path): Json {
  let value: unknown = input;
  for (const key of path) value = (value as Record<string | number, unknown>)[key];
  return value as Json;
}

/** Every object path (the root included) of `value`. */
export function objectPaths(value: unknown, path: Path = []): Path[] {
  if (Array.isArray(value)) return value.flatMap((item, index) => objectPaths(item, [...path, index]));
  if (value === null || typeof value !== "object") return [];
  return [path, ...Object.entries(value).flatMap(([key, item]) => objectPaths(item, [...path, key]))];
}

/** Every primitive leaf of `value`. */
export function leafPaths(value: unknown, path: Path = []): { path: Path; value: unknown }[] {
  if (Array.isArray(value)) return value.flatMap((item, index) => leafPaths(item, [...path, index]));
  if (value !== null && typeof value === "object") {
    return Object.entries(value).flatMap(([key, item]) => leafPaths(item, [...path, key]));
  }
  return [{ path, value }];
}

export function withValue(input: Json, path: Path, value: unknown): Json {
  const copy = structuredClone(input);
  at(copy, path.slice(0, -1))[String(path[path.length - 1])] = value;
  return copy;
}

/**
 * The closed-contract battery: the canonical fixture decodes to itself; every
 * key at every depth is required; an unknown or private key at any depth is
 * refused; no primitive is coerced; a failure never echoes a value.
 * `openPaths` are objects carried as data (a manifest), exempt from closure;
 * `optionalPaths` are keys the builder emits only on request, so omitting them
 * still decodes.
 */
export function expectClosedContract(
  decode: (input: unknown) => DecodeResult<unknown>,
  canonical: Json,
  openPaths: readonly string[] = [],
  optionalPaths: readonly string[] = [],
): void {
  expect(decode(canonical)).toEqual({ ok: true, value: canonical });
  const isOpen = (path: Path) => openPaths.some((open) => path.join(".").startsWith(open));
  for (const path of objectPaths(canonical).filter((path) => !isOpen(path))) {
    for (const key of Object.keys(at(canonical, path))) {
      const value = structuredClone(canonical);
      delete at(value, path)[key];
      const optional = optionalPaths.includes([...path, key].join("."));
      expect(decode(value).ok, `${path.join(".")}.${key} omitted`).toBe(optional);
    }
    for (const key of ["unexpected", "principal_id", "owner_principal_id", "intent_digest", "idempotency_key"]) {
      const value = structuredClone(canonical);
      at(value, path)[key] = "synthetic-private";
      expect(decode(value).ok, `${path.join(".")}.${key} added`).toBe(false);
    }
  }
  for (const leaf of leafPaths(canonical).filter((leaf) => !isOpen(leaf.path))) {
    const wrong =
      typeof leaf.value === "string" ? 17 : typeof leaf.value === "number" ? "1" : typeof leaf.value === "boolean" ? "false" : {};
    const refused = decode(withValue(canonical, leaf.path, wrong));
    expect(refused.ok, leaf.path.join(".")).toBe(false);
    if (!refused.ok) {
      expect(refused.code).toBe("upstream_contract_invalid");
      expect(refused.message).not.toContain(String(leaf.value));
    }
  }
  expect(decode([]).ok).toBe(false);
  expect(decode(null).ok).toBe(false);
}
