import { describe, expect, it } from "vitest";
import {
  buildResourceKey,
  resourceKeysEqual,
  serializeResourceKey,
  type BuildResourceKeyInput,
} from "@/lib/workspace/query-key";

const BASE: BuildResourceKeyInput = {
  family: "synthetic",
  mode: "list",
  sessionEpoch: "epoch-1",
};

describe("ResourceKey identity", () => {
  it("serializes the exact logical array with sorted filter names", () => {
    const key = buildResourceKey({
      ...BASE,
      family: " synthetic ",
      mode: " list ",
      identity: " item ",
      filters: { z: ["second", "first"], a: null, b: " value ", n: 2, ok: true },
      cursor: " opaque cursor ",
      pageSize: 25,
      sessionEpoch: " epoch-1 ",
    });
    expect(serializeResourceKey(key)).toBe(
      '["resource-key:v1","synthetic","list"," item ",[["a",null],["b"," value "],["n",2],["ok",true],["z",["second","first"]]]," opaque cursor ",25,"epoch-1"]',
    );
    expect(Object.keys(key)).toEqual([
      "family", "mode", "identity", "filters", "cursor", "pageSize", "sessionEpoch",
    ]);
  });

  it("omits undefined filters but preserves explicit null", () => {
    const omitted = buildResourceKey({ ...BASE, filters: { a: undefined } });
    expect(resourceKeysEqual(omitted, buildResourceKey(BASE))).toBe(true);
    expect(resourceKeysEqual(omitted, buildResourceKey({ ...BASE, filters: { a: null } }))).toBe(false);
  });

  it("ignores filter insertion order using ordinary string ordering", () => {
    const left = buildResourceKey({ ...BASE, filters: { z: 1, A: 2, a: 3 } });
    const right = buildResourceKey({ ...BASE, filters: { a: 3, A: 2, z: 1 } });
    expect(resourceKeysEqual(left, right)).toBe(true);
    expect(serializeResourceKey(left)).toContain('[["A",2],["a",3],["z",1]]');
  });

  it("preserves homogeneous array types and order without retaining mutable inputs", () => {
    const values = ["b", "a"];
    const key = buildResourceKey({ ...BASE, filters: { values, n: [1, 2], b: [true, false], empty: [] } });
    values.reverse();
    expect(key.filters.values).toEqual(["b", "a"]);
    expect(resourceKeysEqual(key, buildResourceKey({ ...BASE, filters: { values: ["a", "b"], n: [1, 2], b: [true, false], empty: [] } }))).toBe(false);
  });

  it.each([undefined, null, ""])("normalizes missing/empty identity and cursor (%s)", (value) => {
    const key = buildResourceKey({ ...BASE, identity: value, cursor: value });
    expect(key.identity).toBeNull();
    expect(key.cursor).toBeNull();
    expect(key.pageSize).toBeNull();
  });

  it("preserves whitespace-only opaque identity and cursor", () => {
    const key = buildResourceKey({ ...BASE, identity: " ", cursor: " " });
    expect(key.identity).toBe(" ");
    expect(key.cursor).toBe(" ");
  });

  it("normalizes valid numeric/string epochs and partitions every field", () => {
    expect(resourceKeysEqual(buildResourceKey({ ...BASE, sessionEpoch: 7 }), buildResourceKey({ ...BASE, sessionEpoch: " 7 " }))).toBe(true);
    for (const patch of [
      { family: "other" }, { mode: "detail" }, { identity: "item" },
      { cursor: "cursor" }, { pageSize: 1 }, { sessionEpoch: "epoch-2" },
    ]) {
      expect(resourceKeysEqual(buildResourceKey(BASE), buildResourceKey({ ...BASE, ...patch }))).toBe(false);
    }
  });

  it("copies only contract fields, never Principal or credential fields", () => {
    const key = buildResourceKey({ ...BASE, principal: "synthetic", credential: "synthetic" } as BuildResourceKeyInput);
    expect(Object.keys(key)).not.toContain("principal");
    expect(Object.keys(key)).not.toContain("credential");
  });
});

describe("ResourceKey structural validation", () => {
  it.each(["family", "mode", "sessionEpoch"] as const)("rejects blank %s", (field) => {
    expect(() => buildResourceKey({ ...BASE, [field]: "  " })).toThrow(TypeError);
  });

  it.each([0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])("rejects pageSize %s", (pageSize) => {
    expect(() => buildResourceKey({ ...BASE, pageSize })).toThrow(RangeError);
  });

  it.each([NaN, Infinity, 1.5, Number.MAX_SAFE_INTEGER + 1])("rejects non-integer-representable epoch %s", (sessionEpoch) => {
    expect(() => buildResourceKey({ ...BASE, sessionEpoch })).toThrow(TypeError);
  });

  it.each([NaN, Infinity, {}, ["a", 1], [["a"]], [1, Infinity]])("rejects invalid filter value %j", (value) => {
    expect(() => buildResourceKey({ ...BASE, filters: { value } } as unknown as BuildResourceKeyInput)).toThrow(TypeError);
  });

  it.each([
    { family: 1 }, { mode: null }, { identity: 1 }, { cursor: false },
    { filters: [] }, { filters: new Date(0) }, { sessionEpoch: false },
  ])("rejects malformed structural input %j", (patch) => {
    expect(() => buildResourceKey({ ...BASE, ...patch } as unknown as BuildResourceKeyInput)).toThrow(TypeError);
  });

  it("accepts boundary-safe numbers without coercing numeric strings", () => {
    expect(buildResourceKey({ ...BASE, pageSize: Number.MAX_SAFE_INTEGER, sessionEpoch: Number.MAX_SAFE_INTEGER }).sessionEpoch).toBe("9007199254740991");
    expect(() => buildResourceKey({ ...BASE, pageSize: "1" } as unknown as BuildResourceKeyInput)).toThrow(RangeError);
  });
});
