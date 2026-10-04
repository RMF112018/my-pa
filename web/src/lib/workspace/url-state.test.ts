import { describe, expect, it } from "vitest";
import { parseUrlState, patchUrlState, serializeUrlState, type UrlSchema } from "./url-state";

type State = { choice: { name: string }; tags: readonly string[]; page: string; after: string; fixed: number };
const schema: UrlSchema<State> = {
  fields: [
    { key: "choice", cardinality: "one", defaultValue: { name: "all" }, resetsCursor: true,
      parse: (value) => { if (value === "bad") throw new Error("invalid"); return { name: value }; },
      serialize: (value) => value.name },
    { key: "tags", cardinality: "many", defaultValue: ["base"], resetsCursor: true,
      parse: (values) => { if (values.includes("bad")) throw new Error("invalid"); return values; },
      serialize: (values) => values },
    { key: "page", cardinality: "one", defaultValue: "", parse: (value) => value, serialize: (value) => value },
    { key: "after", cardinality: "one", defaultValue: "", emitDefault: true, parse: (value) => value, serialize: (value) => value },
    { key: "fixed", cardinality: "one", defaultValue: 1, emitDefault: true, parse: Number, serialize: (value) => value.toString() },
  ],
  cursorKeys: ["page", "after"],
};

describe("generic URL state", () => {
  it("canonicalizes known order and cardinality while preserving repeated unknown order", () => {
    const parsed = parseUrlState(schema, new URLSearchParams("x=1&tags=b&choice=first&y=2&choice=ignored&tags=a&x=3"));
    expect(parsed.state.choice).toEqual({ name: "first" });
    expect(parsed.state.tags).toEqual(["b", "a"]);
    expect(parsed.passthrough).toEqual([["x", "1"], ["y", "2"], ["x", "3"]]);
    const canonical = serializeUrlState(schema, parsed);
    expect(canonical.toString()).toBe("choice=first&tags=b&tags=a&after=&fixed=1&x=1&y=2&x=3");
    expect(parseUrlState(schema, canonical)).toEqual(parsed);
  });

  it("omits semantically equal object and repeated defaults and emits configured defaults", () => {
    const parsed = parseUrlState(schema, new URLSearchParams("choice=all&tags=base"));
    expect(serializeUrlState(schema, parsed).toString()).toBe("after=&fixed=1");
    expect(parseUrlState(schema, new URLSearchParams()).state).toEqual({ choice: { name: "all" }, tags: ["base"], page: "", after: "", fixed: 1 });
  });

  it("falls back on invalid known values without passthrough or trying scalar duplicates", () => {
    const parsed = parseUrlState(schema, new URLSearchParams("choice=bad&choice=valid&tags=good&tags=bad&x=1"));
    expect(parsed.invalidKnownKeys).toEqual(["choice", "tags"]);
    expect(parsed.state.choice).toEqual({ name: "all" });
    expect(parsed.state.tags).toEqual(["base"]);
    expect(parsed.passthrough).toEqual([["x", "1"]]);
    expect(serializeUrlState(schema, parsed).toString()).toBe("after=&fixed=1&x=1");
  });

  it("retains cursors for semantic no-op patches and resets every cursor on changed filters", () => {
    const parsed = parseUrlState(schema, new URLSearchParams("choice=all&tags=base&page=p&after=a&x=1&x=2"));
    expect(patchUrlState(schema, parsed, { choice: { name: "all" }, tags: ["base"] }).toString()).toBe("page=p&after=a&fixed=1&x=1&x=2");
    expect(patchUrlState(schema, parsed, { choice: { name: "new" }, page: "replacement" }).toString()).toBe("choice=new&fixed=1&x=1&x=2");
    expect(patchUrlState(schema, parsed, { tags: ["new"] }).has("after")).toBe(false);
    expect(patchUrlState(schema, parsed, { fixed: 2 }).get("page")).toBe("p");
    expect(parsed.state.page).toBe("p");
  });

  it("roundtrips decoded special characters and an empty repeated default", () => {
    const emptySchema: UrlSchema<{ items: readonly string[] }> = {
      fields: [{ key: "items", cardinality: "many", defaultValue: [], parse: (input) => input, serialize: (input) => input }],
    };
    const parsed = parseUrlState(emptySchema, new URLSearchParams("items=a%26b&items=a+b&u=%2B&u="));
    expect(parsed.state.items).toEqual(["a&b", "a b"]);
    expect(parseUrlState(emptySchema, serializeUrlState(emptySchema, parsed))).toEqual(parsed);
    expect(serializeUrlState(emptySchema, parseUrlState(emptySchema, new URLSearchParams())).toString()).toBe("");
  });

  it("rejects duplicate field declarations and undeclared cursor keys", () => {
    expect(() => parseUrlState({ ...schema, fields: [schema.fields[0], schema.fields[0]] }, new URLSearchParams())).toThrow("unique fields");
    const missingCursorSchema: UrlSchema<State> = { fields: [schema.fields[0]], cursorKeys: ["page"] };
    expect(() => serializeUrlState(missingCursorSchema, parseUrlState(schema, new URLSearchParams()))).toThrow("declared cursor keys");
  });
});
